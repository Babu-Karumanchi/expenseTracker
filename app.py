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

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
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
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
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


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


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
