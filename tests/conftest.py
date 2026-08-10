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
# Use a per-test temp DB so we never touch the dev expense_tracker.db.
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
    """Flask test client with TESTING enabled."""
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


# ------------------------------------------------------------------ #
# Factory helpers                                                     #
# ------------------------------------------------------------------ #

def make_user(name="Test User", email="test@example.com", password="password123"):
    """Insert a user via the existing `create_user` helper. Returns the id."""
    return _db.create_user(name, email, password)


def make_expense(user_id, amount, category, date, description=""):
    """Insert one expense row directly so tests can stage exact dates/amounts."""
    conn = _db.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )
        conn.commit()
    finally:
        conn.close()


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