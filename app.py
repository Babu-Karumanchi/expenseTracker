import os
import re
import sqlite3
from datetime import datetime

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
    Stats, transactions, and categories are computed in pure Python from
    `get_user_expenses(...)` so DB logic stays in `database/db.py`.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_row = get_user_by_id(session["user_id"])
    if user_row is None:
        session.clear()
        return redirect(url_for("login"))

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
    user_stats = get_user_stats(session["user_id"])
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

    # Transactions table — newest first, with running cumulative balance.
    # Balance = sum of this row's amount and every row that came before it
    # on the page (i.e. older rows). The top (newest) row always equals
    # the grand total, matching the "Total spent" stat above.
    expense_rows = get_user_expenses(session["user_id"])
    grand_total = user_stats["total"]

    transactions = []
    # Walk oldest -> newest to accumulate, then re-apply in display order.
    cumulative = [0.0] * len(expense_rows)
    running = 0.0
    for i in range(len(expense_rows) - 1, -1, -1):
        running += float(expense_rows[i]["amount"])
        cumulative[i] = running

    for row, acc in zip(expense_rows, cumulative):
        transactions.append({
            "date": row["date"],
            "description": row["description"] or "",
            "category": row["category"],
            "category_class": row["category"].lower(),
            "amount": f"₹{row['amount']:,.2f}",
            "balance": f"₹{acc:,.2f}",
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
    )


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
