"""Tests for the /login route."""
import database.db as _db


def test_login_get_renders_form(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Welcome back" in resp.data
    assert b'name="email"' in resp.data
    assert b'name="password"' in resp.data
    # Spec: form must post to url_for('login'), not a hardcoded path.
    assert b'action="/login"' in resp.data


def test_login_happy_path_redirects_to_profile(client):
    # The seeded demo user is reset before every test via the autouse fixture.
    resp = client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]

    # session is set on the test client.
    with client.session_transaction() as sess:
        assert sess["user_name"] == "Demo User"
        # The demo user must exist in the DB with this id.
        conn = _db.get_db()
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert sess["user_id"] == row["id"]


def test_login_wrong_password_shows_error(client):
    resp = client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Invalid email or password." in resp.data
    # Email should be repopulated so the user doesn't have to retype it.
    assert b'value="demo@spendly.com"' in resp.data
    # No session was created.
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_unknown_email_shows_error(client):
    resp = client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "anything123"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Invalid email or password." in resp.data
    # Email is preserved on error.
    assert b'value="nobody@example.com"' in resp.data


def test_login_empty_fields_shows_error(client):
    resp = client.post(
        "/login",
        data={"email": "", "password": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Please enter both email and password." in resp.data


def test_login_after_registration_round_trip(client):
    # Register a new user, then log in with those credentials.
    register_resp = client.post(
        "/register",
        data={
            "name": "Round Trip",
            "email": "roundtrip@example.com",
            "password": "secret123",
            "confirm_password": "secret123",
        },
        follow_redirects=False,
    )
    assert register_resp.status_code == 302
    assert "/login" in register_resp.headers["Location"]

    # Follow the redirect to the login page.
    follow_resp = client.post(
        "/login",
        data={"email": "roundtrip@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert follow_resp.status_code == 302
    assert "/profile" in follow_resp.headers["Location"]

    with client.session_transaction() as sess:
        assert sess["user_name"] == "Round Trip"
