"""Tests for the /register route (Step 2)."""
import database.db as _db


def test_register_get_renders_form(client):
    resp = client.get("/register")
    assert resp.status_code == 200
    assert b"Create your account" in resp.data
    assert b'name="email"' in resp.data
    assert b'name="password"' in resp.data
    # Spec: form must post to url_for('register'), not a hardcoded path.
    assert b'action="/register"' in resp.data


def test_register_happy_path_creates_user_and_redirects(client):
    resp = client.post(
        "/register",
        data={
            "name": "Alice Tester",
            "email": "alice@example.com",
            "password": "secret123",
            "confirm_password": "secret123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # New accounts are signed in automatically and land on the profile page.
    assert resp.headers["Location"].endswith("/profile")

    # Verify the user is in the DB with a hashed (not plaintext) password.
    conn = _db.get_db()
    try:
        row = conn.execute(
            "SELECT name, email, password_hash FROM users WHERE email = ?",
            ("alice@example.com",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["name"] == "Alice Tester"
    assert row["password_hash"] != "secret123"
    # Werkzeug's default hash format is pbkdf2: or scrypt:.
    assert row["password_hash"].startswith("pbkdf2:") or row["password_hash"].startswith("scrypt:")


def test_register_duplicate_email_shows_error_not_500(client):
    # First registration succeeds.
    first = client.post(
        "/register",
        data={
            "name": "Bob One",
            "email": "bob@example.com",
            "password": "pass1234",
            "confirm_password": "pass1234",
        },
        follow_redirects=False,
    )
    assert first.status_code == 302

    # Registration logs the new user in, so log out before the second attempt —
    # otherwise the auth guard would redirect to the home page.
    client.get("/logout", follow_redirects=False)

    # Second registration with the same email must NOT 500.
    second = client.post(
        "/register",
        data={
            "name": "Bob Two",
            "email": "bob@example.com",
            "password": "different123",
            "confirm_password": "different123",
        },
        follow_redirects=False,
    )
    assert second.status_code == 200
    assert b"An account with that email already exists." in second.data

    # The first row is unchanged; only one row exists for that email.
    conn = _db.get_db()
    try:
        rows = conn.execute(
            "SELECT name FROM users WHERE email = ?", ("bob@example.com",)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["name"] == "Bob One"


def test_register_validation_password_too_short(client):
    resp = client.post(
        "/register",
        data={
            "name": "Shorty",
            "email": "shorty@example.com",
            "password": "12345",
            "confirm_password": "12345",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Password must be at least 6 characters." in resp.data
    # Form must still be present (not lost) and the email field should be repopulated.
    assert b'name="email"' in resp.data
    assert b'value="shorty@example.com"' in resp.data
    # Password must NEVER be repopulated.
    assert b'value="12345"' not in resp.data


def test_register_passwords_do_not_match(client):
    resp = client.post(
        "/register",
        data={
            "name": "Mismatch Max",
            "email": "mismatch@example.com",
            "password": "secret123",
            "confirm_password": "different123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Passwords do not match." in resp.data
    # No user was created.
    conn = _db.get_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("mismatch@example.com",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0
