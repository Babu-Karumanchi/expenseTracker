"""Tests for Step 6: date-range filter on the profile page.

Spec source: ``.claude/specs/06-date-filter-profile.md``.

These tests are driven by the spec text — not by reading the
implementation. They exercise the filter contract for ``GET /profile``:

* The two query params ``from`` / ``to`` narrow the transactions table,
  the stats row, and the spending-by-category table to the inclusive
  window ``[from, to]`` (open-ended on either side).
* Empty / missing bounds mean "no bound on that side".
* Malformed dates are dropped with an inline error rather than 500-ing.
* ``from > to`` is swapped so the query still returns useful data.
* Auth guard, user-info card, and Step 5 live-data behaviour all stay
  intact.

Re-uses the fixtures / factories in ``tests/conftest.py``:

* ``client``              — Flask test client
* ``reset_db`` (autouse)  — fresh schema + demo user per test
* ``seeded_user``         — fresh user with 3 expenses on
                            2026-01-15 / 2026-04-15 / 2026-08-15
* ``make_user``           — insert a user
* ``make_expense``        — insert an expense row
* ``_login``              — POST /login and assert 302 to /profile
"""

import re

import pytest

from tests.conftest import _login, make_expense, make_user


# ----------------------------------------------------------------------- #
# Small response-body helpers                                              #
# ----------------------------------------------------------------------- #

INR_RE = re.compile(r"^₹\d{1,3}(?:,\d{3})*\.\d{2}$")


def _row_count(body, needle):
    """Count how many times ``needle`` appears in the response body."""
    return body.count(needle)


def _extract_table_rows(body, table_id):
    """Return the list of <tr>...</tr> chunks inside a table by id.

    Cheap-and-cheerful regex over the rendered HTML — we only need to
    know how many rows the template emitted, plus the cells of each.
    """
    pattern = re.compile(
        r'<table[^>]*id\s*=\s*"' + re.escape(table_id) + r'"[^>]*>(.*?)</table>',
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return []
    inner = match.group(1)
    return re.findall(r"<tr.*?</tr>", inner, re.DOTALL)


# ======================================================================= #
# Auth guard + Step 5 regression                                           #
# ======================================================================= #

def test_signed_out_get_profile_redirects_to_login(client):
    """Auth guard: signed-out GET /profile -> 302 to /login."""
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_profile_renders_200_when_signed_in(client):
    """Page renders 200 when signed in (Step 5 baseline)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/profile")
    assert resp.status_code == 200


def test_user_info_card_refers_to_signed_in_user(client):
    """User-info card shows the actual signed-in user's name + email."""
    user_id = make_user("Asha Rao", "asha@example.com", "password123")
    make_expense(user_id, 100.00, "Food", "2026-03-10", "Lunch")
    _login(client, "asha@example.com", "password123")
    body = client.get("/profile").get_data(as_text=True)
    assert "Asha Rao" in body
    assert "asha@example.com" in body


def test_total_spent_matches_sum_of_expenses_for_demo_user(client):
    """Stats 'Total spent' equals the sum of all demo expenses, INR."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/profile").get_data(as_text=True)
    # Demo seed: 450 + 1850 + 2200 + 650 + 499 + 1799 + 320 + 380 = 8148.00
    assert "₹8,148.00" in body


def test_transactions_count_matches_demo_user(client):
    """Stats 'Transactions' equals the demo user's expense count (8)."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/profile").get_data(as_text=True)
    # The stat card is rendered as <span class="profile-stat-value">N</span>
    # right after a <span class="profile-stat-label">Transactions</span>.
    m = re.search(
        r'profile-stat-label["\s]*>Transactions</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m is not None, "Transactions stat card not found"
    assert m.group(1).strip() == "8"


def test_top_category_matches_highest_spend_category(client):
    """Stats 'Top category' matches the highest-spend category.

    Demo seed: Bills=2200 is the single highest, so 'Bills' is the
    top category.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/profile").get_data(as_text=True)
    m = re.search(
        r'profile-stat-label["\s]*>Top category</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m is not None, "Top category stat card not found"
    assert m.group(1).strip() == "Bills"


def test_transactions_table_rows_match_demo_user_count(client):
    """Transactions table renders one row per expense, newest first."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/profile").get_data(as_text=True)
    # Demo user has 8 expenses -> 8 body rows in the transactions table.
    assert body.count('class="profile-table-num"') >= 8


def test_categories_table_sorted_high_to_low(client):
    """Categories table is sorted by total high to low; largest first."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/profile").get_data(as_text=True)
    # First category-row in the rendered HTML must be the largest one.
    first_category = re.search(
        r'profile-category-row.*?category-badge--([a-z]+)',
        body,
        re.DOTALL,
    )
    assert first_category is not None
    # Bills = 2200 is the largest single-category total in the seed.
    assert first_category.group(1) == "bills"


def test_two_users_do_not_leak_data(client):
    """Isolation: signed in as user B, only B's data is shown."""
    a_id = make_user("Alice", "alice@example.com", "password123")
    b_id = make_user("Bob",   "bob@example.com",   "password123")
    make_expense(a_id, 9999.00, "Food",    "2026-05-01", "alice lunch")
    make_expense(b_id, 250.00,  "Bills",   "2026-05-02", "bob bill")

    _login(client, "bob@example.com", "password123")
    body = client.get("/profile").get_data(as_text=True)

    assert "bob@example.com" in body
    # Alice's row and ₹9999.00 must not appear on Bob's profile.
    assert "alice lunch" not in body
    assert "₹9,999.00" not in body
    # Bob's row should appear, with Bob's total (₹250.00).
    assert "bob bill" in body
    assert "₹250.00" in body


def test_zero_expense_user_renders_zero_total_and_dash_top_category(client):
    """Empty state: zero expenses -> ₹0.00 total, 0 count, em-dash top."""
    make_user("Newbie", "newbie@example.com", "password123")
    _login(client, "newbie@example.com", "password123")
    body = client.get("/profile").get_data(as_text=True)

    # Total spent == ₹0.00
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹0.00"

    # Transactions == 0
    m_count = re.search(
        r'profile-stat-label["\s]*>Transactions</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_count is not None
    assert m_count.group(1).strip() == "0"

    # Top category == em-dash placeholder.
    m_top = re.search(
        r'profile-stat-label["\s]*>Top category</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_top is not None
    assert m_top.group(1).strip() == "—"


# ======================================================================= #
# Step 6: from + to inclusive window                                       #
# ======================================================================= #

def test_from_and_to_window_isolates_a_single_month(client, seeded_user):
    """?from=2026-04-01&to=2026-08-31 -> 2 rows in window, stats match.

    seeded_user has expenses on 2026-01-15 / 2026-04-15 / 2026-08-15.
    The 04-01 .. 08-31 window keeps the April and August rows; the
    January row is excluded.
    """
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01&to=2026-08-31")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Status line should mention both bounds and the filtered count.
    assert "Showing 2 transactions from 2026-04-01 to 2026-08-31" in body

    # April and August descriptions should be on the page; January's must not.
    assert "April commute" in body
    assert "August electricity" in body
    assert "January groceries" not in body

    # Stats total = 1850.00 + 2200.00 = 4,050.00
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹4,050.00"

    # Transactions count == 2
    m_count = re.search(
        r'profile-stat-label["\s]*>Transactions</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_count is not None
    assert m_count.group(1).strip() == "2"

    # Top category in the window: Bills=2200 > Transport=1850.
    m_top = re.search(
        r'profile-stat-label["\s]*>Top category</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_top is not None
    assert m_top.group(1).strip() == "Bills"


def test_open_ended_upper_bound_includes_remaining_rows(client, seeded_user):
    """?from=2026-04-01 (no to) -> April + August rows (open-ended upper)."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Both April and August should be on the page; January must not.
    assert "April commute" in body
    assert "August electricity" in body
    assert "January groceries" not in body

    # Status line should report only the from-bound.
    assert "Showing 2 transactions from 2026-04-01" in body
    # Total: 1850 + 2200 = 4050.00
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹4,050.00"


def test_open_ended_lower_bound_includes_earlier_rows(client, seeded_user):
    """?to=2026-04-30 (no from) -> January + April rows (open-ended lower)."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?to=2026-04-30")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Both January and April should be on the page; August must not.
    assert "January groceries" in body
    assert "April commute" in body
    assert "August electricity" not in body

    # Status line should report only the to-bound.
    assert "Showing 2 transactions up to 2026-04-30" in body
    # Total: 450 + 1850 = 2300.00
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹2,300.00"


def test_no_query_params_shows_full_history(client, seeded_user):
    """No filter parameters -> behaviour identical to Step 5 (full history)."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # All 3 rows should be present.
    assert "January groceries" in body
    assert "April commute" in body
    assert "August electricity" in body

    # Total = 450 + 1850 + 2200 = 4500.00
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹4,500.00"

    # Status line should say "Showing all 3 transactions".
    assert "Showing all 3 transactions" in body


# ======================================================================= #
# Step 6: invalid input + from > to                                        #
# ======================================================================= #

def test_invalid_from_date_renders_200_with_inline_error(client, seeded_user):
    """Invalid `from` -> 200, bad value ignored, inline error shown.

    The good `to` bound is still applied, so the page renders the rows
    that fall on or before 2026-04-30 (January + April).
    """
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=not-a-date&to=2026-04-30")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Inline error message from the spec.
    assert "Please enter valid dates (YYYY-MM-DD)." in body
    # January and April are in the [unbounded, 2026-04-30] window.
    assert "January groceries" in body
    assert "April commute" in body
    # August is past the upper bound and must be excluded.
    assert "August electricity" not in body


def test_invalid_to_date_renders_200_with_inline_error(client, seeded_user):
    """Invalid `to` -> 200, bad value ignored, inline error shown.

    The good `from` bound is still applied, so the page renders the rows
    that fall on or after 2026-04-01 (April + August).
    """
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01&to=garbage")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Please enter valid dates (YYYY-MM-DD)." in body
    assert "April commute" in body
    assert "August electricity" in body
    assert "January groceries" not in body


def test_from_after_to_swaps_bounds_and_shows_swap_message(client, seeded_user):
    """`from > to` -> 200, bounds swapped, swap message shown.

    With from=2026-08-15 and to=2026-01-15 the route should swap to
    [2026-01-15, 2026-08-15] and surface the swap wording in the status
    line. The page should still render every row of seeded_user.
    """
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-08-15&to=2026-01-15")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "From date cannot be after To date." in body
    # All three rows fall in the swapped window, so all should appear.
    assert "January groceries" in body
    assert "April commute" in body
    assert "August electricity" in body
    # Total == full unfiltered total.
    m_total = re.search(
        r'profile-stat-label["\s]*>Total spent</span>\s*'
        r'<span[^>]*profile-stat-value["\s]*>([^<]+)</span>',
        body,
    )
    assert m_total is not None
    assert m_total.group(1).strip() == "₹4,500.00"


# ======================================================================= #
# Step 6: cross-cutting invariants                                         #
# ======================================================================= #

def test_navbar_greeting_unaffected_by_filter(client, seeded_user):
    """Navbar greeting / user identity are unaffected by the filter."""
    _login(client, "filter@example.com", "password123")

    body_unfiltered = client.get("/profile").get_data(as_text=True)
    body_filtered   = client.get(
        "/profile?from=2026-04-01&to=2026-08-31"
    ).get_data(as_text=True)

    # The signed-in user's email and name appear in both bodies.
    assert "filter@example.com" in body_unfiltered
    assert "filter@example.com" in body_filtered
    assert "Filter User" in body_unfiltered
    assert "Filter User" in body_filtered


def test_two_users_with_non_overlapping_expenses_do_not_leak_under_filter(client):
    """Two users w/ non-overlapping expenses don't leak when filtered."""
    a_id = make_user("UserA", "usera@example.com", "password123")
    b_id = make_user("UserB", "userb@example.com", "password123")
    make_expense(a_id, 5000.00, "Food", "2026-05-10", "A-may")
    make_expense(b_id, 250.00,  "Bills", "2026-05-12", "B-may")

    _login(client, "usera@example.com", "password123")
    body = client.get("/profile?from=2026-05-01&to=2026-05-31").get_data(as_text=True)

    # A sees their own row, never B's.
    assert "A-may" in body
    assert "B-may" not in body
    assert "₹5,000.00" in body
    assert "₹250.00" not in body


def test_clear_link_returns_to_unfiltered_profile(client, seeded_user):
    """The Clear link in the filter bar points to /profile with no query.

    A plain <a class="btn-ghost" href="/profile"> (no query string) must
    be present so the user can drop the filter and see full history.
    """
    _login(client, "filter@example.com", "password123")
    body = client.get("/profile?from=2026-04-01&to=2026-08-31").get_data(as_text=True)

    # Look for an href="/profile" with no query string.
    assert re.search(
        r'<a[^>]*class\s*=\s*"[^"]*btn-ghost[^"]*"[^>]*href\s*=\s*"/profile"',
        body,
    ) is not None


def test_date_inputs_prefilled_from_query_string(client, seeded_user):
    """Date inputs are pre-filled with the active from / to values."""
    _login(client, "filter@example.com", "password123")
    body = client.get(
        "/profile?from=2026-04-01&to=2026-08-31"
    ).get_data(as_text=True)

    # The from input must carry value="2026-04-01"; the to input "2026-08-31".
    assert re.search(
        r'<input[^>]*name\s*=\s*"from"[^>]*value\s*=\s*"2026-04-01"',
        body,
    ) is not None
    assert re.search(
        r'<input[^>]*name\s*=\s*"to"[^>]*value\s*=\s*"2026-08-31"',
        body,
    ) is not None


def test_invalid_date_inputs_render_with_empty_value(client, seeded_user):
    """When the query is invalid, the inputs must NOT echo the bad value.

    The form pre-fills with the user-supplied string, but the spec says
    the route ignores the offending value. The rendered input value
    should therefore be the empty string (or absent) — not "not-a-date".
    """
    _login(client, "filter@example.com", "password123")
    body = client.get("/profile?from=not-a-date").get_data(as_text=True)

    # The from input must not carry value="not-a-date".
    assert 'value="not-a-date"' not in body
