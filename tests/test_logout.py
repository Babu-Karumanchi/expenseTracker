"""Tests for the /logout route and the signed-in navbar state."""


def _login(client):
    """Log in as the seeded demo user. Returns the login response."""
    return client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )


def test_logout_clears_session_and_redirects(client):
    # Establish a session first.
    login_resp = _login(client)
    assert login_resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] is not None
        assert sess["user_name"] == "Demo User"

    # Now log out — GET is the path the navbar link uses.
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    # Session must be cleared.
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "user_name" not in sess


def test_logout_post_clears_session_too(client):
    # POST should behave identically to GET.
    _login(client)
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_logout_without_session_is_safe(client):
    # Hitting /logout while signed out must not error — it should still
    # redirect to the landing page with an empty session.
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_navbar_shows_sign_out_when_signed_in(client):
    _login(client)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    # Signed-in branch is active.
    assert b"Sign out" in resp.data
    assert b"Hi, Demo User" in resp.data
    # Signed-out branch is gone.
    assert b">Sign in<" not in resp.data
    assert b"Get started" not in resp.data
    # The Sign-out link uses url_for('logout'), not a hardcoded path.
    assert b'href="/logout"' in resp.data


def test_navbar_reverts_after_logout(client):
    _login(client)
    client.get("/logout", follow_redirects=False)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    # Signed-out branch is back.
    assert b">Sign in<" in resp.data
    assert b"Get started" in resp.data
    # Signed-in branch is gone.
    assert b"Sign out" not in resp.data
    assert b"Hi," not in resp.data