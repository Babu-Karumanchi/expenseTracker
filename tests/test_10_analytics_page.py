"""Tests for Step 10 — the analytics dashboard at /analytics.

Mirrors the structure of tests/test_06-date-filter-profile.py:
GET-only route, regex over the rendered body, status-code assertions
on auth, and uses the conftest fixtures / helpers unchanged.

No POST handlers on /analytics — every test is `client.get(...)`.
"""

import re
from datetime import date

import pytest

from tests.conftest import _login, body_of, make_expense, make_user


# ------------------------------------------------------------------ #
# Test helpers                                                        #
# ------------------------------------------------------------------ #

def _pin_today(monkeypatch, iso):
    """Pin app._today to a fixed date so preset ranges are deterministic."""
    fixed = date.fromisoformat(iso)
    monkeypatch.setattr("app._today", lambda: fixed)


def _login_demo(client):
    """Log in as the seeded demo user."""
    _login(client, "demo@spendly.com", "demo123")


def _fresh_user_with_no_expenses():
    """Create a user that has zero expenses — for the empty-state tests."""
    return make_user(name="Empty User", email="empty@example.com", password="password123")


# ------------------------------------------------------------------ #
# Auth + render                                                       #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_to_login(client):
    """Auth guard: signed-out GET /analytics → 302 to /login."""
    resp = client.get("/analytics", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_in_renders_dashboard_sections(client):
    """Signed-in GET /analytics returns 200 with all six section headings."""
    _login_demo(client)
    resp = client.get("/analytics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Section headings present (case-insensitive matches)
    assert "Monthly trend" in body
    assert "By category" in body
    assert "By day of week" in body
    # KPI labels present
    assert "Total spent" in body
    assert "Transactions" in body
    assert "Average per transaction" in body
    assert "Top category" in body


def test_kpi_strip_shows_totals_in_inr(client):
    """KPI total matches the demo seed total (₹8,148.00), formatted as INR."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    # Demo seed sum: 450 + 1850 + 2200 + 650 + 499 + 1799 + 320 + 380 = 8148.00
    total = _extract_kpi_total(body)
    assert total == "₹8,148.00", f"KPI total: {total!r}"
    # Transactions count for demo user — extracted via the second KPI card
    cnt = re.search(
        r'profile-stat-label">Transactions</span>\s*'
        r'<span class="profile-stat-value">([^<]+)</span>',
        body,
    )
    assert cnt is not None, "Transactions KPI card not found"
    assert cnt.group(1).strip() == "8", f"Transactions: {cnt.group(1)!r}"


# ------------------------------------------------------------------ #
# Empty state                                                         #
# ------------------------------------------------------------------ #

def test_empty_state_renders_when_no_expenses(client):
    """A user with zero expenses sees the empty-state card, NOT the chart."""
    user_id = _fresh_user_with_no_expenses()
    # /login requires the user to exist already (via seed or make_user) — log in now.
    _login(client, "empty@example.com", "password123")
    resp = client.get("/analytics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Empty-state copy + CTA
    assert "No expenses yet" in body
    assert 'href="/profile"' in body
    # The category breakdown / day-of-week / monthly chart are NOT rendered
    assert "By category" not in body
    assert "By day of week" not in body
    assert "analytics-chart-svg" not in body


# ------------------------------------------------------------------ #
# Preset pill row                                                     #
# ------------------------------------------------------------------ #

def test_default_preset_is_all_time(client):
    """No ?preset= → 'All Time' pill has profile-pill--active."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    # The active pill is the one with both 'profile-pill' and 'profile-pill--active'
    # whose text is 'All Time'. Use a lookahead-style regex to bind them together.
    m = re.search(
        r'profile-pill[^"]*profile-pill--active[^"]*"[^>]*>\s*All Time\s*<',
        body,
    )
    assert m is not None, "Expected 'All Time' pill to be active by default"


def test_last_3_months_highlights_that_pill(client):
    """?preset=last_3_months → 'Last 3 Months' pill is active."""
    _login_demo(client)
    body = client.get("/analytics?preset=last_3_months").get_data(as_text=True)
    m = re.search(
        r'profile-pill[^"]*profile-pill--active[^"]*"[^>]*>\s*Last 3 Months\s*<',
        body,
    )
    assert m is not None, "Expected 'Last 3 Months' pill to be active"


def test_invalid_preset_falls_back_to_all_time(client):
    """An unknown ?preset= value silently falls back to 'All Time' (no 4xx)."""
    _login_demo(client)
    resp = client.get("/analytics?preset=garbage_value_xyz")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    m = re.search(
        r'profile-pill[^"]*profile-pill--active[^"]*"[^>]*>\s*All Time\s*<',
        body,
    )
    assert m is not None, "Invalid preset should fall back to All Time"


def test_last_3_months_narrows_kpi_total_with_pinned_today(client, monkeypatch):
    """Pinning today to 2026-08-25 + seeded expenses across Feb-Aug → KPI
    total reflects only the trailing 3 months (Jun-Aug), not all 7 months.
    The monthly chart still shows 12 bars regardless of preset."""
    _pin_today(monkeypatch, "2026-08-25")
    user_id = make_user(
        name="Range User", email="range@example.com", password="password123"
    )
    # Seed one expense per month from Feb 2026 to Aug 2026 (7 months).
    # Each is 100 INR so the math is easy.
    amounts = {
        "2026-02-15": 100.00,
        "2026-03-15": 100.00,
        "2026-04-15": 100.00,
        "2026-05-15": 100.00,
        "2026-06-15": 100.00,
        "2026-07-15": 100.00,
        "2026-08-15": 100.00,
    }
    for d, amt in amounts.items():
        make_expense(user_id, amt, "Food", d, "")

    _login(client, "range@example.com", "password123")

    # Default (All Time): KPI total = 7 * 100 = 700
    body_all = client.get("/analytics").get_data(as_text=True)
    kpi_all = _extract_kpi_total(body_all)
    assert kpi_all == "₹700.00", f"All Time KPI total: {kpi_all!r}"

    # Last 3 months: KPI total = Jun + Jul + Aug = 300
    body_3mo = client.get("/analytics?preset=last_3_months").get_data(as_text=True)
    kpi_3mo = _extract_kpi_total(body_3mo)
    assert kpi_3mo == "₹300.00", f"Last 3 months KPI total: {kpi_3mo!r}"

    # The monthly chart still shows 12 bars regardless of preset
    chart_rects = re.findall(r'<rect[^>]*class="analytics-chart-bar', body_3mo)
    assert len(chart_rects) == 12, f"Expected 12 chart bars, got {len(chart_rects)}"


def _extract_kpi_total(body):
    """Extract the 'Total spent' KPI value from the rendered analytics page.

    Reads the value of the <span class="profile-stat-value"> that immediately
    follows <span class="profile-stat-label">Total spent</span>. Used by the
    preset-narrowing test to verify the KPI reflects the filter, not the
    chart total (which is always 12 months).
    """
    m = re.search(
        r'profile-stat-label">Total spent</span>\s*'
        r'<span class="profile-stat-value">([^<]+)</span>',
        body,
    )
    assert m is not None, "Total spent KPI card not found"
    return m.group(1).strip()


# ------------------------------------------------------------------ #
# Monthly chart                                                       #
# ------------------------------------------------------------------ #

def test_monthly_chart_has_exactly_twelve_bars(client):
    """The trailing-12-month chart renders exactly 12 <rect> bar elements."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    # Bar elements inside the chart SVG
    bars = re.findall(r'<rect[^>]*class="analytics-chart-bar', body)
    assert len(bars) == 12, f"Expected 12 bars, got {len(bars)}"


def test_zero_months_render_as_marker_class(client):
    """Months with no spend get the analytics-chart-bar--zero class."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    zero_bars = re.findall(r'<rect[^>]*analytics-chart-bar--zero', body)
    assert len(zero_bars) >= 1, "Expected at least one zero-month marker"
    # Demo data only spans August 2026, so most months should be zero
    # (at least 11 of 12).
    assert len(zero_bars) >= 11


# ------------------------------------------------------------------ #
# Category breakdown                                                  #
# ------------------------------------------------------------------ #

def test_category_breakdown_is_sorted_high_to_low(client, monkeypatch):
    """Categories render in descending order of total spend."""
    _pin_today(monkeypatch, "2026-08-25")
    user_id = make_user(
        name="Cat User", email="cat@example.com", password="password123"
    )
    # Food highest, Transport lowest, Bills middle
    make_expense(user_id, 300.00, "Food",      "2026-08-05", "")
    make_expense(user_id, 100.00, "Transport", "2026-08-06", "")
    make_expense(user_id, 200.00, "Bills",     "2026-08-07", "")

    _login(client, "cat@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Extract the order of category badges inside .profile-category-list
    section = re.search(
        r'<h2[^>]*>By category</h2>(.*?)</section>',
        body, re.DOTALL,
    )
    assert section is not None, "By category section not found"
    badges = re.findall(
        r'category-badge[^"]*category-badge--(\w+)[^"]*"[^>]*>\s*([A-Za-z]+)\s*<',
        section.group(1),
    )
    cats = [b[1] for b in badges]
    assert cats == ["Food", "Bills", "Transport"], f"Got category order: {cats}"


# ------------------------------------------------------------------ #
# Day-of-week breakdown                                               #
# ------------------------------------------------------------------ #

def test_day_of_week_order_is_mon_to_sun(client):
    """The 7 rows render in Mon → Tue → ... → Sun order."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    section = re.search(
        r'<h2[^>]*>By day of week</h2>(.*?)</section>',
        body, re.DOTALL,
    )
    assert section is not None, "By day of week section not found"
    labels = re.findall(
        r'class="analytics-day-label">([A-Za-z]+)<',
        section.group(1),
    )
    assert labels == ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"], f"Got: {labels}"


def test_day_of_week_shows_average_not_total(client, monkeypatch):
    """Two Monday expenses across two weeks average to ₹150, not ₹300."""
    _pin_today(monkeypatch, "2026-08-25")
    # 2026-07-27 is a Monday (week 31); 2026-08-03 is also a Monday (week 32)
    user_id = make_user(
        name="Dow User", email="dow@example.com", password="password123"
    )
    make_expense(user_id, 100.00, "Food", "2026-07-27", "")
    make_expense(user_id, 200.00, "Food", "2026-08-03", "")

    _login(client, "dow@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Find the Monday row and extract its average value.
    m = re.search(
        r'analytics-day-label">Monday</span>.*?₹([\d,]+\.\d{2})\s+avg',
        body, re.DOTALL,
    )
    assert m is not None, "Monday row with avg value not found"
    assert m.group(1) == "150.00", f"Expected average ₹150.00, got ₹{m.group(1)}"


def test_peak_weekday_is_highlighted(client, monkeypatch):
    """The weekday with the highest average gets the .analytics-day-row--peak class."""
    _pin_today(monkeypatch, "2026-08-25")
    # Make Friday the heaviest day — 4 Fridays in Aug 2026, 4*500 = 2000 → avg 500
    user_id = make_user(
        name="Peak User", email="peak@example.com", password="password123"
    )
    # 2026-08-07, 14, 21, 28 are Fridays
    for d in ("2026-08-07", "2026-08-14", "2026-08-21", "2026-08-28"):
        make_expense(user_id, 500.00, "Food", d, "")

    _login(client, "peak@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Friday <li> must carry analytics-day-row--peak; Monday must not.
    fri_match = re.search(
        r'<li[^>]*class="[^"]*analytics-day-row--peak[^"]*"[^>]*>.*?analytics-day-label">Friday</span>',
        body, re.DOTALL,
    )
    assert fri_match is not None, "Friday row should be marked as peak"

    mon_match = re.search(
        r'<li[^>]*class="[^"]*analytics-day-row--peak[^"]*"[^>]*>.*?analytics-day-label">Monday</span>',
        body, re.DOTALL,
    )
    assert mon_match is None, "Monday should not be marked as peak"


# ------------------------------------------------------------------ #
# Currency formatting                                                 #
# ------------------------------------------------------------------ #

def test_currency_format_uses_inr_symbol_only(client):
    """All totals use ₹; the body never contains $ or USD."""
    _login_demo(client)
    body = client.get("/analytics").get_data(as_text=True)
    assert "₹" in body
    assert "$" not in body
    assert "USD" not in body
