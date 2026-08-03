"""Tests for the /profile page (Step 4 — UI-only with hardcoded data)."""

import re
from pathlib import Path


# Helper ------------------------------------------------------------

def _login(client):
    """Log in as the seeded demo user (re-seeded by the autouse reset_db)."""
    return client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )


# Auth guard --------------------------------------------------------

def test_profile_redirects_to_login_when_signed_out(client):
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_profile_returns_200_when_signed_in(client):
    login_resp = _login(client)
    assert login_resp.status_code == 302

    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 200


# Content sections --------------------------------------------------

def test_profile_renders_user_info_card(client):
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 200
    body = resp.data

    # User info card must show name + email + member-since.
    assert b"Demo User" in body
    assert b"demo@spendly.com" in body
    assert b"Member since" in body


def test_profile_renders_at_least_three_stats(client):
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # The three stat labels defined in app.py.
    assert b"Total spent" in body
    assert b"Transactions" in body
    assert b"Top category" in body

    # And exactly three stat tiles in the DOM.
    assert body.count(b'class="profile-stat-label"') == 3


def test_profile_renders_at_least_three_transactions(client):
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # Both tables render — Recent transactions and Spending by category.
    # Each contributes at least one <tr> per data row plus a header row.
    # 8 transactions + 7 categories + 2 headers = 17 <tr> tags.
    assert body.count(b"<tr>") >= 15
    # Spot-check a few hardcoded rows from app.py.
    assert b"Sunday breakfast" in body
    assert b"BookMyShow movie ticket" in body
    assert b"Rapido auto to airport" in body


def test_profile_renders_recent_transactions_table(client):
    """The recent transactions table has all 5 required columns."""
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # The transactions table is the first <table> on the page.
    assert b"Recent transactions" in body
    assert b">Date<" in body
    assert b">Description<" in body
    assert b">Category<" in body
    assert b">Amount<" in body
    assert b">Balance<" in body


def test_profile_renders_balance_for_each_transaction(client):
    """Each transaction row carries a running-balance value in its last cell."""
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data.decode("utf-8")

    # 8 transactions × 1 balance cell each.
    # The class appears as "profile-table-num profile-table-balance"
    # since `profile-table-balance` is a modifier on the numeric cell.
    assert body.count('profile-table-num profile-table-balance') == 8
    # Top-row (latest) balance equals the grand total ₹8,148.00.
    assert "₹8,148.00" in body
    # Bottom-row (oldest) balance equals the first transaction amount.
    assert "₹450.00" in body


def test_profile_renders_at_least_three_categories(client):
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # The categories table is the second <table> on the page.
    assert b"Spending by category" in body
    assert b">Category<" in body
    assert b">Total spent<" in body
    assert b">Transactions<" in body
    assert b"% of total<" in body

    # At least 3 hardcoded categories render in the table body.
    assert body.count(b"profile-table-pct-value") >= 3
    assert b"Food" in body
    assert b"Transport" in body
    assert b"Bills" in body


def test_profile_renders_category_count_and_percentage(client):
    """Every category row carries a transaction count and a percentage value."""
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # 7 categories × 1 percentage value cell each.
    assert body.count(b"profile-table-pct-value") == 7
    # Each percentage bar gets a width attribute equal to its share.
    # Count the <div class="profile-table-pct-fill ..."> opening tags
    # by looking for the unique modifier class suffix that always follows.
    assert body.count(b"profile-table-pct-fill profile-table-pct-fill--") == 7
    # Highest-share category (Bills, 27.0%) must show its percentage text.
    assert b"27.0%" in body


# Navbar signed-in state (covered by Step 3, but pinned here too) --

def test_profile_shows_signed_in_navbar(client):
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    assert b"Hi, Demo User" in body
    assert b"Sign out" in body
    assert b'href="/logout"' in body


def test_profile_renders_tables_in_two_column_layout(client):
    """Both tables sit inside a single .profile-tables-row wrapper so they
    can be displayed side-by-side on desktop via CSS grid (and collapse to
    a single column at the narrow-screen breakpoint)."""
    _login(client)
    resp = client.get("/profile", follow_redirects=False)
    body = resp.data

    # Exactly one grid wrapper contains both tables.
    assert body.count(b'class="profile-tables-row"') == 1

    # Both table titles appear inside that wrapper, in source order:
    # Recent transactions (left), Spending by category (right).
    txn_idx = body.find(b"Recent transactions")
    cat_idx = body.find(b"Spending by category")
    row_idx = body.find(b'class="profile-tables-row"')
    assert 0 < txn_idx < cat_idx
    assert row_idx < txn_idx


def test_navbar_greeting_links_to_profile(client):
    """Signed-in users can navigate to /profile from any page via the navbar greeting."""
    _login(client)
    # Hit the landing page (the user's home base after sign-out).
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    # The greeting must be an anchor pointing at /profile, not a plain span.
    assert b'<a href="/profile" class="nav-greeting">' in resp.data
    assert b'<span class="nav-greeting">' not in resp.data


# Static rule check -------------------------------------------------

def test_profile_template_uses_no_hex_colors():
    """Spec rule: no hex color values in profile.html — only CSS variables."""
    template_path = Path(__file__).resolve().parents[1] / "templates" / "profile.html"
    text = template_path.read_text(encoding="utf-8")

    # Look for the CSS-comment marker that was added to document this rule.
    # (Not strictly required — the spec's DoD is the absence of hex codes.)
    hex_matches = re.findall(r"#[0-9a-fA-F]{3,8}\b", text)
    assert hex_matches == [], (
        f"profile.html must not contain hex color values; found {hex_matches}"
    )
