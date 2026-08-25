"""Shared pytest fixtures for the Spendly test suite.

The dev DB path in `database/db.py` is swapped to a temp file *before*
`app` is imported — this is required because `app.py` runs `init_db()`
and `seed_db()` at module load against the path that's active at that
moment. Every test then gets a clean schema + a fresh demo user via the
`reset_db` autouse fixture below.
"""

import pytest

# IMPORTANT: import order. Swap DB_PATH before `app` loads.
from database import db as _db

import app as _app_module  # noqa: E402  (must follow the DB_PATH swap)


flask_app = _app_module.app
# Use a per-test temp DB so we never touch the dev spendly.db.
_TEST_DB_PATH = None


@pytest.fixture(autouse=True)
def reset_db(tmp_path, monkeypatch):
    """Give every test a clean schema + the seeded demo user."""
    test_db = tmp_path / "spendly_test.db"
    monkeypatch.setattr(_db, "DB_PATH", test_db)
    _db.init_db()
    _db.seed_db()
    yield
    # tmp_path is cleaned up by pytest automatically.


@pytest.fixture
def client():
    """Flask test client with TESTING enabled and CSRF auto-injection.

    Wraps the test client's `.post` so that — when the session has a
    CSRF token (i.e. the user has logged in or registered) and the
    caller didn't supply one — the token is automatically merged into
    the form data. This keeps the existing test call sites
    (`client.post(url, data={"amount": ...})`) working unchanged.

    Tests that explicitly want the missing-token 403 path should
    pass `data={"_skip_csrf": "1"}` (or set a sentinel — see the new
    tests/test_csrf_and_envelope.py for examples).
    """
    flask_app.config["TESTING"] = True
    tc = flask_app.test_client()
    _original_post = tc.post

    def _post_with_csrf(*args, **kwargs):
        data = kwargs.get("data")
        if isinstance(data, dict) and "csrf_token" not in data:
            token = csrf_token_of(tc)
            if token is not None:
                # Don't mutate the caller's dict.
                data = {**data, "csrf_token": token}
                kwargs["data"] = data
        return _original_post(*args, **kwargs)

    tc.post = _post_with_csrf
    return tc


# ------------------------------------------------------------------ #
# Factory helpers                                                     #
# ------------------------------------------------------------------ #

def make_user(name="Test User", email="test@example.com", password="password123"):
    """Insert a user via the existing `create_user` helper. Returns the id."""
    return _db.create_user(name, email, password)


def make_expense(user_id, amount, category, date, description=""):
    """Insert one expense row directly so tests can stage exact dates/amounts.
    Returns the new row's id so callers can reference it later.
    """
    conn = _db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def csrf_token_of(client):
    """Return the CSRF token currently in the test session, or None.

    The login / register route stamps a fresh token into the session,
    so any test that has just called `_login` (or registered + logged
    in) can pull it from the cookie jar to drive a subsequent POST.

    Returns None when no token is present — callers that POST to a
    CSRF-protected endpoint can branch on this to assert 403 instead
    of building a request that will always fail.
    """
    with client.session_transaction() as sess:
        return sess.get("csrf_token")


def _login(client, email, password):
    """POST /login with the demo credentials; assert it redirects to /profile."""
    resp = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302, f"login failed: {resp.status_code} {resp.data!r}"
    assert "/profile" in resp.headers["Location"]
    return resp


def body_of(resp):
    """Convenience: pull `resp.data` once so each test reads cleanly."""
    return resp.data


def demo_id():
    """The seeded demo user's id.

    Uses the live `_db` module (post-conftest swap) so it points at the
    same per-test temp DB that the rest of the suite is exercising.
    """
    conn = _db.get_db()
    try:
        return conn.execute(
            "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()["id"]
    finally:
        conn.close()


@pytest.fixture
def seeded_user():
    """A fresh user with 3 expenses spread across 3 dates for filter tests.

    Dates: 2026-01-15, 2026-04-15, 2026-08-15. Each row has a distinct
    amount and category so any single-date filter isolates one row.
    """
    user_id = make_user(
        name="Filter User", email="filter@example.com", password="password123"
    )
    make_expense(user_id, 450.00, "Food",      "2026-01-15", "January groceries")
    make_expense(user_id, 1850.00, "Transport", "2026-04-15", "April commute")
    make_expense(user_id, 2200.00, "Bills",     "2026-08-15", "August electricity")
    return user_id