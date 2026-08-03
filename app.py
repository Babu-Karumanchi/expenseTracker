import os
import re
import sqlite3

from flask import Flask, render_template, request, redirect, url_for, session

from database.db import (
    get_db,
    init_db,
    seed_db,
    create_user,
    get_user_by_email,
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
    """Render the profile page with hardcoded data (Step 4 — UI only).

    Step 5 will replace these dicts/lists with real queries against the
    `users` and `expenses` tables. Authentication is still enforced at
    the route layer: an empty session redirects to /login before any
    template logic runs.
    """
    if not session.get("user_id"):
        return redirect(url_for("login"))

    # Per spec: hardcoded context, no DB calls in this step.
    # Values mirror the seeded demo expenses so the page feels coherent
    # with what the user will see once Step 5 wires real queries.
    user = {
        "name": "Demo User",
        "email": "demo@spendly.com",
        "member_since": "August 2026",
        "initial": "D",
    }

    stats = [
        {"label": "Total spent",   "value": "₹8,148.00", "meta": "August 2026"},
        {"label": "Transactions",  "value": "8",          "meta": "this month"},
        {"label": "Top category",  "value": "Bills",      "meta": "₹2,200.00"},
    ]

    # All 8 seeded expenses, newest first. Each row carries a running
    # cumulative balance so the table can show "what the cumulative spend
    # would be up to and including this row" — the top row equals the
    # total spent in the stats row above.
    transactions = [
        {"date": "2026-08-22", "description": "Sunday breakfast",        "category": "Food",          "category_class": "food",          "amount": "₹380.00",    "balance": "₹8,148.00"},
        {"date": "2026-08-15", "description": "Household supplies",      "category": "Other",         "category_class": "other",         "amount": "₹320.00",    "balance": "₹7,768.00"},
        {"date": "2026-08-12", "description": "T-shirt from Decathlon",  "category": "Shopping",      "category_class": "shopping",      "amount": "₹1,799.00",  "balance": "₹7,448.00"},
        {"date": "2026-08-08", "description": "BookMyShow movie ticket", "category": "Entertainment", "category_class": "entertainment", "amount": "₹499.00",    "balance": "₹5,649.00"},
        {"date": "2026-08-05", "description": "Pharmacy — vitamins",     "category": "Health",        "category_class": "health",        "amount": "₹650.00",    "balance": "₹5,150.00"},
        {"date": "2026-08-03", "description": "Electricity bill — Aug",  "category": "Bills",         "category_class": "bills",         "amount": "₹2,200.00",  "balance": "₹4,500.00"},
        {"date": "2026-08-02", "description": "Rapido auto to airport",  "category": "Transport",     "category_class": "transport",     "amount": "₹1,850.00",  "balance": "₹2,300.00"},
        {"date": "2026-08-01", "description": "Lunch at office canteen", "category": "Food",          "category_class": "food",          "amount": "₹450.00",    "balance": "₹450.00"},
    ]

    # Sorted high→low by total so the table reads with the biggest
    # spending categories at the top. `count` is the number of expenses
    # in that category; `percentage` is that category's share of the
    # August total (₹8,148.00). `bar_class` keeps the existing color
    # tokens used elsewhere on the page.
    categories = [
        {"name": "Bills",         "total": "₹2,200.00", "count": 1, "percentage": 27.0, "bar_class": "bills"},
        {"name": "Transport",     "total": "₹1,850.00", "count": 1, "percentage": 22.7, "bar_class": "transport"},
        {"name": "Shopping",      "total": "₹1,799.00", "count": 1, "percentage": 22.1, "bar_class": "shopping"},
        {"name": "Food",          "total": "₹830.00",   "count": 2, "percentage": 10.2, "bar_class": "food"},
        {"name": "Health",        "total": "₹650.00",   "count": 1, "percentage":  8.0, "bar_class": "health"},
        {"name": "Entertainment", "total": "₹499.00",   "count": 1, "percentage":  6.1, "bar_class": "entertainment"},
        {"name": "Other",         "total": "₹320.00",   "count": 1, "percentage":  3.9, "bar_class": "other"},
    ]

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
