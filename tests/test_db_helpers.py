"""Tests for read helpers in database/db.py that don't have their own
test file yet. Focused on ownership scoping and ordering guarantees.

Helpers covered:
  - get_user_expenses_for_analytics (Step 10)

Mirrors the reset_db autouse fixture in conftest.py — every test gets a
clean schema + the seeded demo user via tmp_path.
"""

from tests.conftest import make_expense, make_user


# ------------------------------------------------------------------ #
# get_user_expenses_for_analytics                                     #
# ------------------------------------------------------------------ #

def test_analytics_helper_returns_only_rows_at_or_after_date_from(client):
    """Rows with date < date_from are excluded from the result."""
    user_id = make_user(name="A", email="a@example.com", password="password123")
    make_expense(user_id, 100.00, "Food", "2025-12-15", "")
    make_expense(user_id, 200.00, "Food", "2026-03-15", "")
    make_expense(user_id, 300.00, "Food", "2026-08-15", "")

    from database import db as _db
    rows = _db.get_user_expenses_for_analytics(user_id, "2026-03-01")
    dates = [r["date"] for r in rows]
    assert dates == ["2026-03-15", "2026-08-15"], f"Got: {dates}"


def test_analytics_helper_orders_by_date_ascending(client):
    """Result is sorted date ASC, id ASC — oldest first."""
    user_id = make_user(name="B", email="b@example.com", password="password123")
    # Insert in non-sorted order
    make_expense(user_id, 100.00, "Food", "2026-08-15", "third")
    make_expense(user_id, 200.00, "Food", "2026-03-15", "first")
    make_expense(user_id, 300.00, "Food", "2026-05-15", "second")

    from database import db as _db
    rows = _db.get_user_expenses_for_analytics(user_id, "0000-01-01")
    dates = [r["date"] for r in rows]
    assert dates == ["2026-03-15", "2026-05-15", "2026-08-15"]


def test_analytics_helper_orders_by_id_when_dates_tie(client):
    """Same date → second sort key is id ASC (insertion order)."""
    user_id = make_user(name="C", email="c@example.com", password="password123")
    # Three rows on the same date, inserted in this id order
    make_expense(user_id, 100.00, "Food", "2026-08-15", "a")
    make_expense(user_id, 200.00, "Food", "2026-08-15", "b")
    make_expense(user_id, 300.00, "Food", "2026-08-15", "c")

    from database import db as _db
    rows = _db.get_user_expenses_for_analytics(user_id, "0000-01-01")
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids), f"Expected ascending id order, got {ids}"


def test_analytics_helper_is_owner_scoped(client):
    """User A's helper call never returns user B's rows."""
    user_a = make_user(name="A", email="a@example.com", password="password123")
    user_b = make_user(name="B", email="b@example.com", password="password123")
    make_expense(user_a, 100.00, "Food", "2026-08-15", "a's row")
    make_expense(user_b, 999.00, "Food", "2026-08-15", "b's row")

    from database import db as _db
    rows_a = _db.get_user_expenses_for_analytics(user_a, "0000-01-01")
    rows_b = _db.get_user_expenses_for_analytics(user_b, "0000-01-01")
    assert len(rows_a) == 1
    assert len(rows_b) == 1
    assert rows_a[0]["amount"] == 100.00
    assert rows_b[0]["amount"] == 999.00
    # Cross-check: no leakage
    assert rows_a[0]["user_id"] == user_a
    assert rows_b[0]["user_id"] == user_b


def test_analytics_helper_has_no_upper_bound(client):
    """The helper has no date_to — a far-future row is included when
    date_from is before it. (Used by the 'All Time' preset.)"""
    user_id = make_user(name="D", email="d@example.com", password="password123")
    make_expense(user_id, 50.00, "Food", "2099-01-01", "future row")

    from database import db as _db
    rows = _db.get_user_expenses_for_analytics(user_id, "0000-01-01")
    assert len(rows) == 1
    assert rows[0]["date"] == "2099-01-01"


def test_analytics_helper_returns_empty_when_no_rows(client):
    """No matching rows → empty list, not None."""
    user_id = make_user(name="E", email="e@example.com", password="password123")
    from database import db as _db
    rows = _db.get_user_expenses_for_analytics(user_id, "2099-01-01")
    assert rows == []
