import os
import re
import sqlite3
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, session

from database.db import (
    get_db,
    init_db,
    seed_db,
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_expenses,
    get_user_stats,
    verify_password,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY") or "dev-only-not-for-production"

# Module-level regexes — compiled once, reused on every request.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today():
    """Return the current date. Wrapped in a function so tests can pin it.

    Production: `date.today()`. Tests monkeypatch `app._today` to a
    fixed date so preset ranges (this month / last 3 / last 6) are
    deterministic regardless of the wall clock.
    """
    return date.today()


# Preset id -> label. Bounds are computed in the route from the preset id
# (`this_month` / `last_3_months` / `last_6_months` use today-anchored offsets;
# `all_time` emits no query so the user always lands on a clean /profile URL).
PRESETS = [
    {"id": "all_time",       "label": "All Time"},
    {"id": "this_month",     "label": "This Month"},
    {"id": "last_3_months",  "label": "Last 3 Months"},
    {"id": "last_6_months",  "label": "Last 6 Months"},
]


def _add_months(d, months):
    """Return d shifted by `months` calendar months, clamped to month-end.

    Used by the preset calculations so "this month" lands on the 1st
    regardless of the current day. Negative `months` walks backwards.
    """
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    # Last day of the target month: day before the 1st of the next month.
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - date(year, month, 1)).days
    return date(year, month, min(d.day, last_day))


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

def _redirect_if_signed_in():
    """If a user is already logged in, send them to the profile page.

    Returns a redirect Response when signed in, otherwise None.
    Both GET and POST use this so the guard fires for every entry
    point into the login/register pages.
    """
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return None


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    signed_in = _redirect_if_signed_in()
    if signed_in is not None:
        return signed_in

    if request.method == "GET":
        return render_template("register.html")

    # POST: validate, create, log in.
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    # NB: do not strip password — trailing spaces are legitimate.

    if not name:
        return render_template(
            "register.html", error="Please enter your name.", name=name, email=email
        )
    if not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template(
            "register.html",
            error="Please enter a valid email address.",
            name=name,
            email=email,
        )
    if len(password) < 6:
        return render_template(
            "register.html",
            error="Password must be at least 6 characters.",
            name=name,
            email=email,
        )
    if password != request.form.get("confirm_password") or "":
        return render_template(
            "register.html",
            error="Passwords do not match.",
            name=name,
            email=email,
        )

    try:
        user_id = create_user(name, email, password)
    except sqlite3.IntegrityError:
        return render_template(
            "register.html",
            error="An account with that email already exists.",
            name=name,
            email=email,
        )

    session.clear()
    session["user_id"] = user_id
    session["user_name"] = name
    return redirect(url_for("profile"))


@app.route("/login", methods=["GET", "POST"])
def login():
    signed_in = _redirect_if_signed_in()
    if signed_in is not None:
        return signed_in

    if request.method == "GET":
        return render_template("login.html")

    # POST: validate credentials and start a session.
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    if not email or not password:
        return render_template(
            "login.html",
            error="Please enter both email and password.",
            email=email,
        )

    user = get_user_by_email(email)
    if not verify_password(user, password):
        return render_template(
            "login.html",
            error="Invalid email or password.",
            email=email,
        )

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    # NOTE: GET-based logout is a deliberate trade-off — this is a
    # single-user personal tracker and the navbar uses a link, not a form.
    # Do not copy this pattern into a multi-user context without CSRF.
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    """Render the profile page with live DB data for the signed-in user.

    Auth guard: an empty session redirects to /login before any DB call.
    The user row is fetched by id; if it disappears between requests (e.g.
    account deleted), the session is cleared and the user is redirected.

    Optional `?from=YYYY-MM-DD` and `?to=YYYY-MM-DD` query parameters narrow
    the transactions table, the stats row, and the spending-by-category
    table to the inclusive date window `[from, to]`. Either bound is
    optional (open-ended on that side). Malformed dates are dropped with
    an inline error; `from > to` swaps the bounds so the query still
    returns useful data rather than an empty result.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_row = get_user_by_id(session["user_id"])
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))

    # Parse + validate the date filter from the query string. Presets
    # (e.g. `?preset=this_month`) auto-fill the from/to bounds; explicit
    # `?from=` / `?to=` win if supplied alongside `?preset=` so a manual
    # edit always overrides a previously-clicked pill.
    preset_id = request.args.get("preset", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    filter_error = None
    active_preset = None

    today = _today()
    preset_bounds = {
        "this_month":    (today.replace(day=1).isoformat(), today.isoformat()),
        "last_3_months": (_add_months(today, -3).isoformat(), today.isoformat()),
        "last_6_months": (_add_months(today, -6).isoformat(), today.isoformat()),
    }

    # Preset wins when no explicit dates were typed. Once the user types
    # in the date inputs, the active preset is cleared so the pill row
    # no longer highlights a preset (matches the AskUserQuestion answer).
    # "all_time" is also the implicit default when no params are present.
    if not from_raw and not to_raw:
        if preset_id in preset_bounds:
            from_raw, to_raw = preset_bounds[preset_id]
            active_preset = preset_id
        elif preset_id == "" or preset_id == "all_time":
            active_preset = "all_time"

    from_bound = None
    to_bound = None
    # Display-only echoes of the bound back into the <input value="…">.
    # Empty when the user typed garbage so the bad string isn't round-tripped
    # into the rendered HTML — the spec is explicit that invalid values are
    # "ignored". The DB-side `from_bound` / `to_bound` still reflect the
    # validated values (or `None` for invalid / empty inputs).
    from_display = ""
    to_display = ""
    if from_raw:
        if DATE_RE.fullmatch(from_raw):
            from_bound = from_raw
            from_display = from_raw
        else:
            filter_error = "Please enter valid dates (YYYY-MM-DD)."
    if to_raw:
        if DATE_RE.fullmatch(to_raw):
            to_bound = to_raw
            to_display = to_raw
        else:
            filter_error = "Please enter valid dates (YYYY-MM-DD)."

    # Swap when from > to so the query returns useful data instead of nothing.
    # The status line will surface the swap so the user sees what happened.
    if from_bound and to_bound and from_bound > to_bound:
        from_bound, to_bound = to_bound, from_bound
        from_display, to_display = to_display, from_display
        filter_error = "From date cannot be after To date."

    filter = {
        "from": from_display,
        "to": to_display,
        # "All Time" is the unfiltered default — keep `is_active` False so
        # the status line reads "Showing all N transactions" without the
        # "from X to Y" wording.
        "is_active": bool((from_display or to_display) and active_preset != "all_time"),
    }

    # User info card -------------------------------------------------------
    name = user_row["name"]
    member_since = datetime.strptime(
        user_row["created_at"], "%Y-%m-%d %H:%M:%S"
    ).strftime("%B %Y")
    user = {
        "name": name,
        "email": user_row["email"],
        "member_since": member_since,
        "initial": name[0].upper() if name else "?",
    }

    # Stats row ------------------------------------------------------------
    user_stats = get_user_stats(
        session["user_id"], date_from=from_bound, date_to=to_bound
    )
    if user_stats["top_category"] is None:
        top_category_label = "—"
        top_category_meta = "—"
    else:
        top_category_label = user_stats["top_category"]
        top_category_meta = f"₹{user_stats['top_category_total']:,.2f}"

    stats = [
        {"label": "Total spent",  "value": f"₹{user_stats['total']:,.2f}", "meta": member_since},
        {"label": "Transactions", "value": str(user_stats["count"]),      "meta": "this month"},
        {"label": "Top category", "value": top_category_label,            "meta": top_category_meta},
    ]

    # Transactions list — newest first, mapped from the filtered expense rows.
    expense_rows = get_user_expenses(
        session["user_id"], date_from=from_bound, date_to=to_bound
    )
    filtered_count = len(expense_rows)
    grand_total = user_stats["total"]

    transactions = []
    for row in expense_rows:
        transactions.append({
            "date": row["date"],
            "description": row["description"] or "",
            "category": row["category"],
            "category_class": row["category"].lower(),
            "amount": f"₹{row['amount']:,.2f}",
        })

    # Categories table — high -> low by total, with count and percentage.
    # Aggregation is done in Python so we issue one DB query
    # (`get_user_expenses`) instead of one per category.
    by_category = {}
    for row in expense_rows:
        cat = row["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0.0, "count": 0}
        by_category[cat]["total"] += float(row["amount"])
        by_category[cat]["count"] += 1

    categories = []
    for cat, agg in sorted(by_category.items(), key=lambda kv: -kv[1]["total"]):
        if grand_total > 0:
            pct = round((agg["total"] / grand_total) * 100, 1)
        else:
            pct = 0.0
        categories.append({
            "name": cat,
            "total": f"₹{agg['total']:,.2f}",
            "count": agg["count"],
            "percentage": pct,
            "bar_class": cat.lower(),
        })

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        filter=filter,
        filtered_count=filtered_count,
        filter_error=filter_error,
        presets=PRESETS,
        active_preset=active_preset,
    )


@app.route("/analytics")
def analytics():
    """Render the Analytics coming-soon page. Auth-guarded: logged-out
    users are redirected to /login before any rendering.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


# ------------------------------------------------------------------ #
# Database initialization                                              #
# ------------------------------------------------------------------ #

with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
