"""Tests for the signed-in guard on /login and /register.

A logged-in user must never see the login or registration pages —
they should be redirected to the home page regardless of HTTP method.
"""


def _login(client):
    return client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )


def test_signed_in_user_get_login_is_redirected_home(client):
    _login(client)
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_signed_in_user_get_register_is_redirected_home(client):
    _login(client)
    resp = client.get("/register", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_signed_in_user_post_login_is_redirected_home(client):
    _login(client)
    # A stray POST to /login (e.g. a stale form) must not be allowed to
    # re-render the login form or overwrite the session.
    resp = client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    # The original session is intact (same user, same name).
    with client.session_transaction() as sess:
        assert sess["user_name"] == "Demo User"


def test_signed_in_user_post_register_is_redirected_home(client):
    _login(client)
    # A signed-in user trying to register a new account must be bounced
    # away before any validation runs, and no new row is created.
    resp = client.post(
        "/register",
        data={
            "name": "Sneaky",
            "email": "sneaky@example.com",
            "password": "secret123",
            "confirm_password": "secret123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    import database.db as _db
    conn = _db.get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("sneaky@example.com",)
        ).fetchone()
    finally:
        conn.close()
    assert row is None


def test_signed_out_user_login_and_register_render_normally(client):
    # Sanity check: the guard does not interfere with the signed-out path.
    login_resp = client.get("/login", follow_redirects=False)
    assert login_resp.status_code == 200
    register_resp = client.get("/register", follow_redirects=False)
    assert register_resp.status_code == 200