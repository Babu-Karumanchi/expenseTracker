"""Step 12: Budget Management — tests for `GET /budget` and `POST /budget`.

Spec: `.claude/specs/12-budget-management.md`.

These tests cover the Definition of Done for Step 12:
  * Auth boundary (signed-out GET and POST redirect to /login)
  * User can set a monthly budget amount via POST /budget
  * Budget is persisted in the `budgets` table and linked to the current user
  * GET /budget calculates total spending for the current calendar month
  * Progress bar correctly shows the ratio and changes color:
      - Green: < 70%
      - Yellow: 70% - 90%
      - Red: > 90%
  * /profile page displays budget summary (e.g., "₹X of ₹Y spent")
  * Budget settings are private to the logged-in user (isolation)
  * CSRF protection on POST /budget
"""

import datetime
from tests.conftest import (
    _db,
    _login,
    body_of,
    csrf_token_of,
    demo_id,
    make_expense,
    make_user,
)


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _get_budget(user_id):
    conn = _db.get_db()
    try:
        row = conn.execute(
            "SELECT amount FROM budgets WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["amount"] if row else None
    finally:
        conn.close()


def _today_iso():
    return datetime.date.today().isoformat()


def _last_month_iso():
    # Simple approximation for last month
    today = datetime.date.today()
    first_of_this_month = today.replace(day=1)
    last_day_of_last_month = first_of_this_month - datetime.timedelta(days=1)
    return last_day_of_last_month.isoformat()


# ------------------------------------------------------------------ #
# Auth boundary                                                       #
# ------------------------------------------------------------------ #

def test_signed_out_get_budget_redirects(client):
    """Spec: signed-out GET /budget -> 302 to /login."""
    resp = client.get("/budget", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_out_post_budget_redirects(client):
    """Spec: signed-out POST /budget -> 302 to /login."""
    resp = client.post("/budget", data={"amount": "5000"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ #
# Budget Setting (POST /budget)                                       #
# ------------------------------------------------------------------ #

def test_set_budget_happy_path(client):
    """Spec: authenticated POST /budget with valid amount updates DB and redirects."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    token = csrf_token_of(client)
    data = {"amount": "5000.00", "csrf_token": token} if token else {"amount": "5000.00"}

    resp = client.post("/budget", data=data, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/budget")
    assert _get_budget(user_id) == 5000.0


def test_set_budget_invalid_amount_non_numeric(client):
    """Spec: non-numeric budget amount should not update DB and should render error."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    token = csrf_token_of(client)
    data = {"amount": "abc", "csrf_token": token} if token else {"amount": "abc"}

    resp = client.post("/budget", data=data, follow_redirects=False)

    assert resp.status_code == 200
    assert b"Please enter a valid budget" in body_of(resp)
    assert _get_budget(user_id) is None


def test_set_budget_invalid_amount_negative(client):
    """Spec: negative budget amount should not update DB."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    token = csrf_token_of(client)
    data = {"amount": "-100", "csrf_token": token} if token else {"amount": "-100"}

    resp = client.post("/budget", data=data, follow_redirects=False)

    assert resp.status_code == 200
    assert b"Please enter a valid budget" in body_of(resp)
    assert _get_budget(user_id) is None


def test_set_budget_missing_csrf(client):
    """Spec: POST /budget without CSRF token should be rejected."""
    _login(client, "demo@spendly.com", "demo123")

    # POST with an INCORRECT token to bypass the auto-injection wrapper
    resp = client.post("/budget", data={"amount": "5000", "csrf_token": "wrong-token"}, follow_redirects=False)

    # Usually 403 Forbidden or 400 Bad Request depending on implementation
    assert resp.status_code in (400, 403)


# ------------------------------------------------------------------ #
# Budget Viewing (GET /budget)                                         #
# ------------------------------------------------------------------ #

def test_get_budget_no_budget_set(client):
    """Spec: if no budget is set, page should handle it gracefully (e.g., 0 or 'Not set')."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/budget")
    assert resp.status_code == 200
    # We check that it doesn't crash and shows something sensible
    assert b"budget" in body_of(resp).lower()


def test_get_budget_no_expenses(client):
    """Spec: Budget set but no expenses -> 0% progress, Green bar."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Set budget
    token = csrf_token_of(client)
    data = {"amount": "1000", "csrf_token": token} if token else {"amount": "1000"}
    client.post("/budget", data=data)

    resp = client.get("/budget")
    body = body_of(resp)

    assert b"0.0%" in body
    assert b"budget-fill--green" in body


def test_get_budget_progress_green(client):
    """Spec: Spent < 70% -> bg-green-500."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Budget: 1000, Spent: 600 (60%)
    token = csrf_token_of(client)
    client.post("/budget", data={"amount": "1000", "csrf_token": token} if token else {"amount": "1000"})
    make_expense(user_id, 600.00, "Food", _today_iso(), "Test expense")

    body = body_of(client.get("/budget"))
    assert b"60.0%" in body
    assert b"budget-fill--green" in body


def test_get_budget_progress_yellow(client):
    """Spec: Spent 70% - 90% -> bg-yellow-500."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Budget: 1000, Spent: 800 (80%)
    token = csrf_token_of(client)
    client.post("/budget", data={"amount": "1000", "csrf_token": token} if token else {"amount": "1000"})
    make_expense(user_id, 800.00, "Food", _today_iso(), "Test expense")

    body = body_of(client.get("/budget"))
    assert b"80.0%" in body
    assert b"budget-fill--yellow" in body


def test_get_budget_progress_red(client):
    """Spec: Spent > 90% -> bg-red-500."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Budget: 1000, Spent: 950 (95%)
    token = csrf_token_of(client)
    client.post("/budget", data={"amount": "1000", "csrf_token": token} if token else {"amount": "1000"})
    make_expense(user_id, 950.00, "Food", _today_iso(), "Test expense")

    body = body_of(client.get("/budget"))
    assert b"95.0%" in body
    assert b"budget-fill--red" in body


def test_get_budget_ignores_previous_month_expenses(client):
    """Spec: Monthly spending should only include the current calendar month."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Budget: 1000
    token = csrf_token_of(client)
    client.post("/budget", data={"amount": "1000", "csrf_token": token} if token else {"amount": "1000"})

    # Expense this month: 200
    make_expense(user_id, 200.00, "Food", _today_iso(), "Current")
    # Expense last month: 500
    make_expense(user_id, 500.00, "Food", _last_month_iso(), "Past")

    body = body_of(client.get("/budget")).decode('utf-8', errors='ignore')
    # Only 200 should be counted -> 20%
    assert "20.0%" in body
    assert "₹200" in body
    assert "₹500" not in body # Total spend display


# ------------------------------------------------------------------ #
# Integration & Isolation                                             #
# ------------------------------------------------------------------ #

def test_profile_shows_budget_summary(client):
    """Spec: /profile page displays budget status (e.g., '₹X of ₹Y spent')."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Budget: 5000, Spent: 1200
    token = csrf_token_of(client)
    client.post("/budget", data={"amount": "5000", "csrf_token": token} if token else {"amount": "5000"})
    make_expense(user_id, 1200.00, "Food", _today_iso(), "Summary test")

    body = body_of(client.get("/profile"))
    # Check for the pattern "₹1,200 of ₹5,000 spent" or similar
    # Note: currency formatting might use commas.
    assert b"1,200" in body
    assert b"5,000" in body
    assert b"spent" in body


def test_budget_isolation(client):
    """Spec: User A cannot see or modify User B's budget."""
    # User A
    _login(client, "demo@spendly.com", "demo123")
    user_a_id = demo_id()
    token_a = csrf_token_of(client)
    client.post("/budget", data={"amount": "1000", "csrf_token": token_a} if token_a else {"amount": "1000"})

    # User B
    make_user(name="Bob", email="bob@example.com", password="password123")
    client.get("/logout")
    _login(client, "bob@example.com", "password123")
    user_b_id = demo_id()

    # User B should not see User A's budget
    body_b = body_of(client.get("/budget"))
    assert b"1,000" not in body_b

    # User B sets their own budget
    token_b = csrf_token_of(client)
    client.post("/budget", data={"amount": "2000", "csrf_token": token_b} if token_b else {"amount": "2000"})

    # Verify User A still has 1000
    client.get("/logout")
    _login(client, "demo@spendly.com", "demo123")
    assert _get_budget(user_a_id) == 1000.0
