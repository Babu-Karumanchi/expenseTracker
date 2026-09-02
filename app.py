import calendar
import hmac
import os
import re
import secrets
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify

from database.db import (
    get_db,
    init_db,
    seed_db,
    create_user,
    create_expense,
    get_user_by_email,
    get_user_by_id,
    get_user_expenses,
    get_user_expenses_for_analytics,
    get_user_stats,
    get_expense_by_id,
    update_expense,
    delete_expense as delete_expense_row,
    update_user,
    delete_user,
    verify_password,
    get_budget,
    set_budget,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SPENDLY_SECRET_KEY") or "dev-only-not-for-production"

# Module-level regexes — compiled once, reused on every request.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Fixed category vocabulary seeded in Step 1. Reused by the add-expense
# route (validation whitelist) and the add-expense template (rendered as
# <option>s in the select). Keep this list in lock-step with the seed.
CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

# Inclusive amount bounds (in INR) — encoded as Decimal so the comparison
# is exact and the format string in the user-facing message is unambiguous.
AMOUNT_MIN = Decimal("0.01")
AMOUNT_MAX = Decimal("1000000")

# User-facing amount error. Single source of truth so the message stays
# consistent across the two amount-validation branches (non-numeric and
# out-of-range).
AMOUNT_RANGE_ERROR = "Please enter a valid amount between ₹0.01 and ₹10,00,000."


# ------------------------------------------------------------------ #
# AJAX detection + JSON helpers                                       #
# ------------------------------------------------------------------ #
# The Add/Edit/Delete modals on /profile submit via fetch() with a
# custom header so the server can return JSON instead of HTML/302.
# Direct browser navigation to /expenses/add or /expenses/<id>/edit
# (no-JS fallback) still gets the existing HTML response.
#
# NOTE: `X-Requested-With` is NOT a CSRF defense — any same-origin
# context (curl, a same-origin XSS bug, a malicious same-origin page)
# can forge the header. Every state-changing POST also carries a
# `csrf_token` form field validated against `session["csrf_token"]`
# (see `_get_or_create_csrf` / `_verify_csrf` below).

def _is_ajax():
    """True when the request comes from a fetch() call inside a modal."""
    return request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"


def _get_or_create_csrf():
    """Return the per-session CSRF token, minting one on first use.

    Token source: `secrets.token_urlsafe(32)` — 32 bytes of entropy
    base64-url-encoded (well above the OWASP minimum). Stored in
    `session["csrf_token"]` so it rotates with the session and is wiped
    by `session.clear()` on login / register / logout.
    """
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _verify_csrf():
    """Validate the form's `csrf_token` against the session's.

    Called from every state-changing POST handler, immediately AFTER
    the auth guard so signed-out POSTs continue to 302 to /login
    (not 403) — that ordering matters for the existing
    `test_signed_out_post_redirects_to_login` tests.

    Returns:
        None when the token matches.
        On mismatch / missing token:
          * AJAX (`X-Requested-With: XMLHttpRequest`) → JSON 403
            so the modal's `.catch` shows the generic error message.
          * Direct nav (no header) → Flask default HTML 403 via
            `abort(403)` (per CLAUDE.md: "`abort()` for HTTP errors").
    """
    session_token = session.get("csrf_token") or ""
    request_token = request.form.get("csrf_token") or ""
    if not session_token or not hmac.compare_digest(
        str(session_token), str(request_token)
    ):
        if _is_ajax():
            resp = jsonify({
                "ok": False,
                "error": "Security token missing or invalid.",
            })
            resp.status_code = 403
            return resp
        abort(403)
    return None


@app.context_processor
def inject_csrf():
    """Expose the CSRF token to every template via `csrf_token()`.

    Calling the helper (rather than binding the raw value) means the
    token is minted on first render and persisted in the session for
    subsequent requests, even if the template was rendered before the
    login / register POST stamped it.
    """
    return {"csrf_token": _get_or_create_csrf}


def _stats_payload():
    """Build the Total Spent + Transactions stats for the AJAX envelope.

    The modal JS handler overwrites `#profile-grand-total` and
    `#profile-txn-count` from these values so the stat tiles stay
    in sync without a page reload.

    Honours the page's `from` / `to` filter (carried as hidden form
    inputs on every modal) so a filtered `/profile?preset=last_3_months`
    keeps showing the filtered stats — without bounds, the unfiltered
    totals would jump in confusingly after an Add. Bad inputs fall
    back to no bounds rather than returning an error envelope.
    """
    from_bound = (request.form.get("from") or "").strip()
    to_bound = (request.form.get("to") or "").strip()
    if from_bound and not DATE_RE.fullmatch(from_bound):
        from_bound = ""
    if to_bound and not DATE_RE.fullmatch(to_bound):
        to_bound = ""
    stats = get_user_stats(
        session["user_id"],
        date_from=from_bound or None,
        date_to=to_bound or None,
    )
    return {
        "total": f"₹{stats['total']:,.2f}",
        "count": stats["count"],
    }


def _expense_payload(row):
    """Build the dict the modal-success JSON returns AND the profile
    template already uses for each row.

    Single source of truth so the JS-rendered row markup matches the
    server-rendered markup byte-for-byte (modulo dynamic ids).
    """
    return {
        "id": row["id"],
        "date": row["date"],
        "description": row["description"] or "",
        "category": row["category"],
        "category_class": row["category"].lower(),
        "amount": f"₹{row['amount']:,.2f}",
    }


def _json_ok(**fields):
    """Success envelope: {"ok": true, ...fields}. Status 200."""
    return jsonify({"ok": True, **fields})


def _json_error(message, **extra):
    """Failure envelope: {"ok": false, "error": message, ...extra}. Status 200.

    Validation failures use 200 (not 4xx) so the JS success path doesn't
    have to branch on status — the `ok` flag is the single source of truth.
    The extra kwargs (typically `values=...`) ride along in the payload.
    """
    return jsonify({"ok": False, "error": message, **extra})


def _add_expense_invalid(message, today, amount, category, date_str, description):
    """Branch on _is_ajax(): JSON for the modal, HTML for direct nav."""
    if _is_ajax():
        return _json_error(
            message,
            values={
                "amount": amount,
                "category": category,
                "date": date_str,
                "description": description,
            },
        )
    return _render_add_expense_error(
        message, today, amount, category, date_str, description
    )


def _edit_expense_invalid(message, expense, today, amount, category, date_str, description):
    """Branch on _is_ajax(): JSON for the modal, HTML for direct nav."""
    if _is_ajax():
        return _json_error(
            message,
            values={
                "amount": amount,
                "category": category,
                "date": date_str,
                "description": description,
            },
        )
    return _render_edit_expense_error(
        message, expense, today, amount, category, date_str, description
    )


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
    {"id": "last_12_months", "label": "Last 12 Months"},
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
    # Stamp a fresh CSRF token into the session so the post-redirect
    # /profile GET (which renders the modal forms) already has a token
    # the server will accept on the next POST.
    session["csrf_token"] = secrets.token_urlsafe(32)
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
    # Stamp a fresh CSRF token into the session so the post-redirect
    # /profile GET (which renders the modal forms) already has a token
    # the server will accept on the next POST.
    session["csrf_token"] = secrets.token_urlsafe(32)
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


@app.route("/budget", methods=["GET", "POST"])
def budget():
    """Render and process the monthly budget management page.

    GET:
        Calculate current month spend and fetch user's budget to determine
        spending progress and a visual color class (green/yellow/red).

    POST:
        Validate the budget amount and update it in the database.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today = _today()
    start_of_month = today.replace(day=1).isoformat()

    if request.method == "POST":
        csrf_error = _verify_csrf()
        if csrf_error is not None:
            return csrf_error

        amount_raw = request.form.get("amount") or ""
        try:
            amount_decimal = Decimal(amount_raw)
            if amount_decimal < AMOUNT_MIN or amount_decimal > AMOUNT_MAX:
                raise ValueError()
        except (InvalidOperation, ValueError):
            # Render with error if amount is invalid
            # Need to calculate spend and budget first to re-render the page correctly
            stats = get_user_stats(user_id, date_from=start_of_month)
            budget_row = get_budget(user_id)
            budget_amount = budget_row["amount"] if budget_row else 0.0

            # Simple pct for re-render
            pct = (stats["total"] / budget_amount * 100) if budget_amount > 0 else 0.0
            color_class = "budget-fill--green"
            if pct > 90: color_class = "budget-fill--red"
            elif pct > 70: color_class = "budget-fill--yellow"

            return render_template(
                "budget.html",
                current_spend=stats["total"],
                budget_amount=budget_amount,
                percentage=pct,
                color_class=color_class,
                error="Please enter a valid budget between ₹0.01 and ₹10,00,000.",
                amount=amount_raw,
                today=today.isoformat()
            )

        set_budget(user_id, float(amount_decimal))
        return redirect(url_for("budget"))

    # GET
    stats = get_user_stats(user_id, date_from=start_of_month)
    current_spend = stats["total"]

    budget_row = get_budget(user_id)
    budget_amount = budget_row["amount"] if budget_row else 0.0

    pct = (current_spend / budget_amount * 100) if budget_amount > 0 else 0.0

    color_class = "budget-fill--green"
    if pct > 90:
        color_class = "budget-fill--red"
    elif pct > 70:
        color_class = "budget-fill--yellow"

    return render_template(
        "budget.html",
        current_spend=current_spend,
        budget_amount=budget_amount,
        percentage=pct,
        color_class=color_class,
        today=today.isoformat()
    )


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

    # Budget status for stats row
    today_dt = _today()
    start_of_month = today_dt.replace(day=1).isoformat()
    month_stats = get_user_stats(session["user_id"], date_from=start_of_month)
    current_month_spend = month_stats["total"]
    budget_row = get_budget(session["user_id"])
    budget_val = budget_row["amount"] if budget_row else None

    if budget_val is not None:
        budget_status = f"₹{current_month_spend:,.2f} / ₹{budget_val:,.2f}"
    else:
        budget_status = "No budget set"

    stats = [
        {"label": "Total spent",  "value": f"₹{user_stats['total']:,.2f}", "meta": member_since},
        {"label": "Transactions", "value": str(user_stats["count"]),      "meta": "this month"},
        {"label": "Top category", "value": top_category_label,            "meta": top_category_meta},
        {"label": "Budget", "value": budget_status, "meta": "this month"},
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
            "id": row["id"],
            "date": row["date"],
            "description": row["description"] or "",
            "category": row["category"],
            "category_class": row["category"].lower(),
            "amount": f"₹{row['amount']:,.2f}",
            # Raw numeric string used to pre-populate the edit-modal's
            # amount input. Kept as str(row["amount"]) so the input shows
            # exactly what the DB stored (e.g. "450.0", not a re-formatted
            # rupee string).
            "amount_raw": str(row["amount"]),
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
        today=today.isoformat(),
        CATEGORIES=CATEGORIES,
    )


@app.route("/analytics")
def analytics():
    """Render the analytics dashboard for the signed-in user.

    Auth guard: an empty session redirects to /login before any DB call.
    Optional `?preset=` narrows the KPI strip + category + day-of-week
    breakdowns; the trailing-12-month bar chart is ALWAYS 12 months
    ending today, regardless of the preset (a 1-bar chart would defeat
    the purpose of an analytics page). Invalid preset values fall back
    silently to `all_time` — no 4xx, no error envelope.

    Sections rendered:
      1. KPI strip (Total spent / Transactions / Average / Top category)
      2. Preset pill row
      3. Monthly trend (inline SVG, 12 bars oldest → newest)
      4. Category breakdown (horizontal bar list, high → low)
      5. Day-of-week breakdown (Mon → Sun, average per weekday)
      6. Empty state (replaces sections 3-5 when the user has zero expenses)
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = _today()
    preset_id = request.args.get("preset", "").strip()

    preset_bounds = {
        "this_month":    (today.replace(day=1).isoformat(), today.isoformat()),
        "last_3_months": (_add_months(today, -3).isoformat(), today.isoformat()),
        "last_6_months": (_add_months(today, -6).isoformat(), today.isoformat()),
        "last_12_months": (_add_months(today, -12).isoformat(), today.isoformat()),
    }
    valid_preset_ids = {"all_time"} | set(preset_bounds.keys())
    if preset_id not in valid_preset_ids:
        preset_id = "last_12_months"
    active_preset = preset_id

    if preset_id == "all_time":
        from_bound, to_bound = None, None
    else:
        from_bound, to_bound = preset_bounds[preset_id]

    # KPI strip via the same helper /profile uses — total / count /
    # top_category / top_category_total all reflect the same preset
    # window so the values stay consistent across pages.
    stats = get_user_stats(
        session["user_id"], date_from=from_bound, date_to=to_bound
    )
    if stats["count"] > 0:
        average = stats["total"] / stats["count"]
    else:
        average = 0.0
    kpis = {
        "total":              stats["total"],
        "count":              stats["count"],
        "average":            average,
        "top_category":       stats["top_category"],
        "top_category_total": stats["top_category_total"],
    }

    # Chart window calculation based on preset
    if preset_id == "this_month":
        num_months = 1
    elif preset_id == "last_3_months":
        num_months = 3
    elif preset_id == "last_6_months":
        num_months = 6
    elif preset_id == "all_time":
        num_months = None
    else:
        num_months = 12

    if num_months:
        chart_first = _add_months(today.replace(day=1), -(num_months - 1))
        month_dates = [_add_months(chart_first, i) for i in range(num_months)]
        month_keys = [(d.year, d.month) for d in month_dates]
        chart_start_iso = chart_first.isoformat()
        month_keys_set = set(month_keys)
        rows = get_user_expenses_for_analytics(session["user_id"], chart_start_iso)
    else:
        # All time: fetch all and determine range from earliest expense
        rows = get_user_expenses_for_analytics(session["user_id"], None)
        if not rows:
            chart_first = today.replace(day=1)
            month_dates = [chart_first]
        else:
            earliest_date = date.fromisoformat(rows[0]["date"])
            chart_first = earliest_date.replace(day=1)
            diff = (today.year - chart_first.year) * 12 + (today.month - chart_first.month) + 1
            month_dates = [_add_months(chart_first, i) for i in range(diff)]

        month_keys = [(d.year, d.month) for d in month_dates]
        chart_start_iso = chart_first.isoformat()
        month_keys_set = set(month_keys)


    # Monthly buckets — total spend per calendar month, oldest → newest.
    totals_by_month = defaultdict(float)
    for row in rows:
        try:
            d = date.fromisoformat(row["date"])
        except (ValueError, TypeError):
            continue  # skip malformed rows silently
        key = (d.year, d.month)
        if key in month_keys_set:
            totals_by_month[key] += float(row["amount"])
    monthly_buckets = [
        {
            "label": calendar.month_abbr[m],
            "year": y,
            "month": m,
            "total": round(totals_by_month.get((y, m), 0.0), 2),
            "is_current": (y == today.year and m == today.month),
        }
        for (y, m) in month_keys
    ]
    max_month_total = max((b["total"] for b in monthly_buckets), default=0.0)

    # Category breakdown — totals + counts, high → low.
    totals_by_cat = defaultdict(float)
    counts_by_cat = defaultdict(int)
    for row in rows:
        totals_by_cat[row["category"]] += float(row["amount"])
        counts_by_cat[row["category"]] += 1
    grand_total = sum(totals_by_cat.values())
    category_breakdown = sorted(
        [
            {
                "category": cat,
                "total": round(total, 2),
                "count": counts_by_cat[cat],
                "share": (total / grand_total) if grand_total else 0.0,
                "bar_class": cat.lower(),
            }
            for cat, total in totals_by_cat.items()
        ],
        key=lambda x: -x["total"],
    )

    # Day-of-week breakdown — Monday → Sunday, average spend per weekday.
    DAY_LABELS = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]
    totals_by_dow = defaultdict(float)
    weeks_per_dow = defaultdict(set)
    for row in rows:
        try:
            d = date.fromisoformat(row["date"])
        except (ValueError, TypeError):
            continue
        wd = d.weekday()  # Mon=0, Sun=6
        totals_by_dow[wd] += float(row["amount"])
        weeks_per_dow[wd].add(d.isocalendar()[:2])

    day_breakdown = []
    for wd in range(7):
        weeks = len(weeks_per_dow.get(wd, set()))
        denominator = max(weeks, 1)  # never divide by zero
        avg = totals_by_dow.get(wd, 0.0) / denominator
        day_breakdown.append({
            "weekday": wd,
            "label":   DAY_LABELS[wd],
            "total":   round(totals_by_dow.get(wd, 0.0), 2),
            "weeks":   weeks,
            "average": round(avg, 2),
        })

    # Peak weekday — None when every weekday is zero so no row gets the
    # --peak highlight and the chart reads as "no data".
    peak_weekday = None
    if any(d["average"] > 0 for d in day_breakdown):
        peak_weekday = max(range(7), key=lambda i: day_breakdown[i]["average"])

    return render_template(
        "analytics.html",
        active_preset=active_preset,
        presets=PRESETS,
        kpis=kpis,
        monthly_buckets=monthly_buckets,
        max_month_total=max_month_total,
        category_breakdown=category_breakdown,
        day_breakdown=day_breakdown,
        peak_weekday=peak_weekday,
        is_empty=(kpis["count"] == 0),
        today=today.isoformat(),
        today_month_label=today.strftime("%B %Y"),
        CATEGORIES=CATEGORIES,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    """Render and process the add-expense form for the signed-in user.

    Auth guard: an empty session redirects to /login for both GET and POST
    before any rendering or DB call. The route never accepts `user_id`
    from the form — that value is always taken from `session["user_id"]`.

    GET pre-fills the `date` field with today's ISO date (`YYYY-MM-DD`)
    so the user can submit the common "I just spent it" case without
    touching the date picker. The `max="{{ today }}"` attribute on the
    date input is a UX hint; the server still rejects future dates.

    POST validates in this fixed order, returning the form with the
    user's typed values echoed back on the first failure:
        1. amount — must be a parseable Decimal, > 0, <= 1,000,000.
           Empty → "Please enter an amount."; otherwise
           "Please enter a valid amount between ₹0.01 and ₹10,00,000."
        2. category — must be in CATEGORIES after stripping.
           "Please choose a category."
        3. date — must match DATE_RE AND parse via date.fromisoformat()
           AND not be in the future.
           Bad format → "Please enter a valid date.";
           future date → "Date cannot be in the future."
        4. description — len <= 200 after stripping.
           "Description must be 200 characters or fewer."

    On success the row is inserted via `create_expense(...)` (empty
    description stored as NULL) and the response is either:
      * AJAX (modal submission) — JSON `{"ok": true, "expense": {...}}`
        so the modal's JS handler can render the new row in place.
      * Direct nav (no-JS fallback) — HTTP 302 to /profile so a refresh
        resubmits the GET there, not the POST.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = _today().isoformat()

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            today=today,
            amount="",
            category="",
            date=today,
            description="",
            CATEGORIES=CATEGORIES,
        )

    # POST: CSRF check runs only on state-changing requests.
    csrf_error = _verify_csrf()
    if csrf_error is not None:
        return csrf_error

    # POST — read raw form values. Strip whitespace on category /
    # description (free text); leave amount / date raw (mechanical).
    amount_raw = request.form.get("amount") or ""
    category = (request.form.get("category") or "").strip()
    date_raw = request.form.get("date") or ""
    description = (request.form.get("description") or "").strip()

    # 1. amount
    if amount_raw == "":
        return _add_expense_invalid(
            "Please enter an amount.",
            today, amount_raw, category, date_raw, description,
        )
    try:
        amount_decimal = Decimal(amount_raw)
    except (InvalidOperation, ValueError):
        return _add_expense_invalid(
            AMOUNT_RANGE_ERROR,
            today, amount_raw, category, date_raw, description,
        )
    # `is_finite()` rejects NaN / sNaN (Decimal comparisons with NaN are
    # always False, so a plain `<= 0` / `> AMOUNT_MAX` would let NaN slip
    # through and break SUM(amount) on /profile). The lower bound is
    # AMOUNT_MIN (₹0.01), not 0, so sub-paise values like 0.001 don't
    # pass and round to "₹0.00" on the profile page.
    if (
        not amount_decimal.is_finite()
        or amount_decimal < AMOUNT_MIN
        or amount_decimal > AMOUNT_MAX
    ):
        return _add_expense_invalid(
            AMOUNT_RANGE_ERROR,
            today, amount_raw, category, date_raw, description,
        )

    # 2. category
    if category not in CATEGORIES:
        return _add_expense_invalid(
            "Please choose a category.",
            today, amount_raw, category, date_raw, description,
        )

    # 3. date
    if not DATE_RE.fullmatch(date_raw):
        return _add_expense_invalid(
            "Please enter a valid date.",
            today, amount_raw, category, date_raw, description,
        )
    try:
        parsed_date = date.fromisoformat(date_raw)
    except ValueError:
        return _add_expense_invalid(
            "Please enter a valid date.",
            today, amount_raw, category, date_raw, description,
        )
    if parsed_date > _today():
        return _add_expense_invalid(
            "Date cannot be in the future.",
            today, amount_raw, category, date_raw, description,
        )

    # 4. description
    if len(description) > 200:
        return _add_expense_invalid(
            "Description must be 200 characters or fewer.",
            today, amount_raw, category, date_raw, description,
        )

    # Success — persist then either return JSON (modal) or redirect
    # (direct nav / no-JS fallback).
    # Empty description is stored as NULL by `create_expense` itself, so
    # the route passes the user-typed string through unchanged.
    new_id = create_expense(
        session["user_id"],
        float(amount_decimal),
        category,
        parsed_date.isoformat(),
        description,
    )
    if _is_ajax():
        new_row = get_expense_by_id(new_id, session["user_id"])
        return _json_ok(expense=_expense_payload(new_row), **_stats_payload())
    return redirect(url_for("profile"))


def _render_add_expense_error(error, today, amount, category, date_str, description):
    """Re-render add_expense.html with `error` and the typed values echoed.

    Helper for the POST validation branches so each failure path stays a
    single readable line. The `today` kwarg keeps the date input's
    `max="..."` attribute correct on re-render.
    """
    return render_template(
        "add_expense.html",
        error=error,
        today=today,
        amount=amount,
        category=category,
        date=date_str,
        description=description,
        CATEGORIES=CATEGORIES,
    )


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    """Render and process the edit-expense form for the signed-in user.

    Auth guard: an empty session redirects to /login for both GET and POST
    before any rendering or DB call. The route never accepts `user_id`
    from the form — that value is always taken from `session["user_id"]`.

    Ownership guard: `get_expense_by_id(id, session_user_id)` scopes the
    SELECT with `AND user_id = ?`. A miss covers both "doesn't exist" and
    "belongs to a different user", and the route `abort(404)`s uniformly
    so an attacker probing ids cannot distinguish the two cases by status
    code. The same guard fires for POST before validation runs, so a
    cross-user POST returns 404 without touching the row.

    GET pre-populates the form from the row's current values (amount,
    category, date, description) and sets the date input's `max` to
    today. POST validates in the same fixed order as `/expenses/add`,
    returning the form with the user's typed values echoed back on the
    first failure:
        1. amount — must parse as a finite Decimal, >= AMOUNT_MIN, <= AMOUNT_MAX.
        2. category — must be in CATEGORIES after stripping.
        3. date — must match DATE_RE, parse via date.fromisoformat(), and not be future.
        4. description — len <= 200 after stripping.

    On success the row is updated via `update_expense(...)` (empty
    description stored as NULL) and the response is either:
      * AJAX (modal submission) — JSON `{"ok": true, "expense": {...}}`
        so the modal's JS handler can update the row in place.
      * Direct nav (no-JS fallback) — HTTP 302 to /profile so a refresh
        resubmits the GET there, not the POST.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = _today().isoformat()

    if request.method == "GET":
        # GET short-circuits to the form (or 404) without touching CSRF —
        # GET is not a state-changing request. Ownership is enforced here
        # so /expenses/<id>/edit 404s uniformly for unknown and cross-user
        # ids on the standalone page.
        expense = get_expense_by_id(id, session["user_id"])
        if expense is None:
            abort(404)
        # Pre-populate from the row. `amount` is rendered as the raw float
        # `str()` cast so the input shows what the DB stored (e.g. "450.0",
        # not a re-formatted rupee string). `description` falls back to ""
        # when the column is NULL so the textarea is visibly blank.
        return render_template(
            "edit_expense.html",
            expense=expense,
            today=today,
            amount=str(expense["amount"]),
            category=expense["category"],
            date=expense["date"],
            description=expense["description"] or "",
            CATEGORIES=CATEGORIES,
        )

    # POST: CSRF check fires BEFORE the ownership check (matching
    # delete_expense's auth → CSRF → ownership ordering). This keeps the
    # CSRF defence uniform — a request without a valid token always
    # gets 403, regardless of whether the target id exists or belongs
    # to the caller.
    csrf_error = _verify_csrf()
    if csrf_error is not None:
        return csrf_error

    expense = get_expense_by_id(id, session["user_id"])
    if expense is None:
        abort(404)

    # POST — read raw form values. Strip whitespace on category /
    # description (free text); leave amount / date raw (mechanical).
    amount_raw = request.form.get("amount") or ""
    category = (request.form.get("category") or "").strip()
    date_raw = request.form.get("date") or ""
    description = (request.form.get("description") or "").strip()

    # 1. amount
    if amount_raw == "":
        return _edit_expense_invalid(
            "Please enter an amount.",
            expense, today, amount_raw, category, date_raw, description,
        )
    try:
        amount_decimal = Decimal(amount_raw)
    except (InvalidOperation, ValueError):
        return _edit_expense_invalid(
            AMOUNT_RANGE_ERROR,
            expense, today, amount_raw, category, date_raw, description,
        )
    # `is_finite()` rejects NaN / sNaN (Decimal comparisons with NaN are
    # always False). The lower bound is AMOUNT_MIN, not 0, so sub-paise
    # values like 0.001 don't pass and round to "₹0.00" on /profile.
    if (
        not amount_decimal.is_finite()
        or amount_decimal < AMOUNT_MIN
        or amount_decimal > AMOUNT_MAX
    ):
        return _edit_expense_invalid(
            AMOUNT_RANGE_ERROR,
            expense, today, amount_raw, category, date_raw, description,
        )

    # 2. category
    if category not in CATEGORIES:
        return _edit_expense_invalid(
            "Please choose a category.",
            expense, today, amount_raw, category, date_raw, description,
        )

    # 3. date
    if not DATE_RE.fullmatch(date_raw):
        return _edit_expense_invalid(
            "Please enter a valid date.",
            expense, today, amount_raw, category, date_raw, description,
        )
    try:
        parsed_date = date.fromisoformat(date_raw)
    except ValueError:
        return _edit_expense_invalid(
            "Please enter a valid date.",
            expense, today, amount_raw, category, date_raw, description,
        )
    if parsed_date > _today():
        return _edit_expense_invalid(
            "Date cannot be in the future.",
            expense, today, amount_raw, category, date_raw, description,
        )

    # 4. description
    if len(description) > 200:
        return _edit_expense_invalid(
            "Description must be 200 characters or fewer.",
            expense, today, amount_raw, category, date_raw, description,
        )

    # Success — persist then either return JSON (modal) or redirect
    # (direct nav / no-JS fallback).
    # Empty description is stored as NULL by `update_expense` itself,
    # so the route passes the user-typed string through unchanged.
    update_expense(
        id,
        session["user_id"],
        float(amount_decimal),
        category,
        parsed_date.isoformat(),
        description,
    )
    if _is_ajax():
        updated_row = get_expense_by_id(id, session["user_id"])
        return _json_ok(expense=_expense_payload(updated_row), **_stats_payload())
    return redirect(url_for("profile"))


def _render_edit_expense_error(error, expense, today, amount, category, date_str, description):
    """Re-render edit_expense.html with `error` and the typed values echoed.

    Helper for the POST validation branches so each failure path stays a
    single readable line. `expense` is passed through so the template can
    render the row's id / original context (e.g. back link) when
    validation fails. The signature differs from `_render_add_expense_error`
    by the leading `expense` arg — the only intentional change.
    """
    return render_template(
        "edit_expense.html",
        error=error,
        expense=expense,
        today=today,
        amount=amount,
        category=category,
        date=date_str,
        description=description,
        CATEGORIES=CATEGORIES,
    )


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    """Owner-scoped delete. POST-only — the modal on /profile is the only UI gate.

    Auth guard: an empty session redirects to /login before any DB call.
    The route never accepts `user_id` from the form — that value is
    always taken from `session["user_id"]`.

    Ownership guard: `get_expense_by_id(id, session_user_id)` scopes the
    SELECT with `AND user_id = ?`. A miss covers both "doesn't exist" and
    "belongs to a different user", and the route `abort(404)`s uniformly
    so an attacker probing ids cannot distinguish the two cases by status
    code. The guard fires before the DELETE runs, so a cross-user POST
    returns 404 without touching the row.

    On success the row is deleted via `delete_expense_row(...)` and the
    response is either:
      * AJAX (modal submission) — JSON `{"ok": true, "id": <int>}` so the
        modal's JS handler can remove the row from /profile in place.
      * Direct nav (no-JS fallback) — HTTP 302 to /profile so a refresh
        resubmits the GET there, not the POST.

    A direct GET to this URL returns 405 Method Not Allowed (Flask's
    default) — there is no GET resource to render. The user-facing gate
    is the Delete modal on /profile, which renders a POST form that
    targets this endpoint.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    csrf_error = _verify_csrf()
    if csrf_error is not None:
        return csrf_error

    expense = get_expense_by_id(id, session["user_id"])
    if expense is None:
        abort(404)

    delete_expense_row(id, session["user_id"])
    if _is_ajax():
        return _json_ok(id=id, **_stats_payload())
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Database initialization                                              #
# ------------------------------------------------------------------ #


@app.route("/profile/edit", methods=["GET", "POST"])
def edit_profile():
    """Render and process the profile edit form for the signed-in user.
    
    Auth guard: signed-out users redirect to /login.
    
    GET fetches the current user's data to pre-fill the form.
    
    POST validates:
        1. name — cannot be empty.
        2. email — must match the standard email regex.
    
    On success, updates the user in the DB and redirects to /profile.
    Handles sqlite3.IntegrityError if the updated email is already taken.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_row = get_user_by_id(session["user_id"])
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template(
            "edit_profile.html",
            name=user_row["name"],
            email=user_row["email"],
        )

    # POST: CSRF check.
    csrf_error = _verify_csrf()
    if csrf_error is not None:
        return csrf_error

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()

    if not name:
        return render_template(
            "edit_profile.html",
            error="Please enter your name.",
            name=name,
            email=email,
        )
    if not re.fullmatch(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return render_template(
            "edit_profile.html",
            error="Please enter a valid email address.",
            name=name,
            email=email,
        )

    try:
        update_user(session["user_id"], name, email)
        # Update session name to reflect change immediately
        session["user_name"] = name
    except sqlite3.IntegrityError:
        return render_template(
            "edit_profile.html",
            error="An account with that email already exists.",
            name=name,
            email=email,
        )

    return redirect(url_for("profile"))


@app.route("/profile/delete", methods=["GET", "POST"])
def delete_profile():
    """Render and process the profile deletion confirmation.
    
    Auth guard: signed-out users redirect to /login.
    
    GET renders the confirmation page.
    
    POST verifies CSRF, deletes the user and all their expenses,
    clears the session, and redirects to the landing page.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("delete_profile.html")

    # POST: CSRF check.
    csrf_error = _verify_csrf()
    if csrf_error is not None:
        return csrf_error

    delete_user(session["user_id"])
    session.clear()
    return redirect(url_for("landing"))
with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
