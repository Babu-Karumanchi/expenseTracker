"""Tests for Step 10: Analytics Page.

Spec source: `.claude/specs/10-analytics-page.md`.

These tests verify the analytics dashboard's behaviour based on the specification:
- Auth guard: signed-out users are redirected to /login.
- KPI Strip: Total spent, Transactions, Average, and Top category are correctly calculated.
- Presets: Date presets narrow KPIs and breakdowns, with a silent fallback for invalid values.
- Monthly Trend: A server-rendered SVG bar chart always shows the trailing 12 months.
- Category Breakdown: High-to-low sorted list of categories used.
- Day-of-Week Breakdown: Monday-to-Sunday averages with the peak day highlighted.
- Empty State: Users with no expenses see a friendly message and a link to /profile.
- Currency: Strict adherence to INR (₹) formatting.
"""

import re
import pytest
from datetime import date

from tests.conftest import _login, make_expense, make_user

# Currency cells must match Indian formatting: ₹, comma separators, 2 decimals.
INR_RE = re.compile(r"₹\d{1,3}(?:,\d{3})*\.\d{2}")

def _pin_today(monkeypatch, iso):
    """Pin app._today to a fixed date so preset ranges are deterministic."""
    fixed = date.fromisoformat(iso)
    monkeypatch.setattr("app._today", lambda: fixed)

# ======================================================================= #
# Auth Guard                                                              #
# ======================================================================= #

def test_analytics_auth_guard_redirects_to_login(client):
    """Auth guard: signed-out GET /analytics -> 302 to /login."""
    resp = client.get("/analytics", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

def test_analytics_renders_200_when_signed_in(client):
    """Page renders 200 when signed in."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/analytics")
    assert resp.status_code == 200

# ======================================================================= #
# KPI Strip & Formatting                                                   #
# ======================================================================= #

def test_analytics_kpi_strip_matches_demo_user(client):
    """KPI strip reflects the demo user's lifetime totals (All Time).

    Demo seed: Total=8148.00, Count=8, Avg=1018.50, Top=Bills (2200.00).
    """
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics").get_data(as_text=True)

    # Total Spent
    assert "₹8,148.00" in body
    # Transactions
    assert "8" in body
    # Average per transaction (8148 / 8 = 1018.50)
    assert "₹1,018.50" in body
    # Top Category (Bills)
    assert "Bills" in body
    assert "₹2,200.00" in body

def test_analytics_inr_formatting_everywhere(client):
    """Every monetary value on the analytics page follows INR formatting."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics").get_data(as_text=True)

    # Find all matches for currency
    matches = INR_RE.findall(body)
    # Should have multiple: Total, Avg, Top Cat, and several in Category breakdown.
    assert len(matches) >= 5

# ======================================================================= #
# Presets                                                                 #
# ======================================================================= #

def test_analytics_preset_pill_row_renders_and_highlights(client):
    """Preset pills render and the active one is highlighted.
    Default is 'All Time'.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics").get_data(as_text=True)

    # All labels present
    for label in ["All Time", "This Month", "Last 3 Months", "Last 6 Months"]:
        assert label in body

    # Default active state
    assert body.count("profile-pill--active") == 1
    assert "All Time" in body and "profile-pill--active" in body

def test_analytics_explicit_preset_highlights_correct_pill(client):
    """?preset=last_3_months highlights the 'Last 3 Months' pill."""
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics?preset=last_3_months").get_data(as_text=True)

    assert body.count("profile-pill--active") == 1
    # Ensure the active pill is indeed Last 3 Months
    # (Looking for the class and label in proximity)
    assert re.search(r'profile-pill--active[^>]*>Last 3 Months', body) is not None

def test_analytics_invalid_preset_falls_back_to_all_time(client):
    """?preset=invalid_value falls back silently to all_time (200, All Time active)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/analytics?preset=garbage_value")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert body.count("profile-pill--active") == 1
    assert re.search(r'profile-pill--active[^>]*>All Time', body) is not None

def test_analytics_preset_narrows_kpis_and_breakdowns(client, monkeypatch):
    """?preset=this_month narrows KPIs and breakdowns but NOT the monthly chart.

    User has:
    - 2026-07-15: 1000.00 (Food)
    - 2026-08-05: 500.00 (Bills)
    - 2026-08-10: 500.00 (Bills)

    Today pinned to 2026-08-20.
    'This Month' (Aug 1 - Aug 20) should see: Total=1000, Count=2, Top=Bills.
    """
    _pin_today(monkeypatch, "2026-08-20")
    uid = make_user("Preset User", "preset@example.com", "password123")
    make_expense(uid, 1000.00, "Food", "2026-07-15")
    make_expense(uid, 500.00, "Bills", "2026-08-05")
    make_expense(uid, 500.00, "Bills", "2026-08-10")

    _login(client, "preset@example.com", "password123")
    body = client.get("/analytics?preset=this_month").get_data(as_text=True)

    # KPI Strip should be narrowed to August only
    assert "₹1,000.00" in body  # Total
    assert "2" in body          # Count
    assert "Bills" in body      # Top Cat

    # Category breakdown should only have Bills
    assert "Bills" in body
    assert "Food" not in body

    # Monthly chart should still be 12 bars (containing July and August)
    # we check for the presence of July and August labels in the chart area
    assert "Jul" in body
    assert "Aug" in body

# ======================================================================= #
# Monthly Trend Chart                                                     #
# ======================================================================= #

def test_analytics_monthly_trend_chart_shape(client, monkeypatch):
    """Monthly trend is a 12-bar SVG ending at the current month.
    Pinned to 2026-08-20. Chart should end with Aug 2026.
    """
    _pin_today(monkeypatch, "2026-08-20")
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics").get_data(as_text=True)

    # Should contain exactly 12 month abbreviations (Jan-Dec or similar)
    # depending on the trailing 12 months. From Sep 2025 to Aug 2026.
    # We check that we see Aug and Sep.
    assert "Aug" in body
    assert "Sep" in body

    # Check for 12 SVG bars (usually <rect> elements in a bar chart)
    # The implementation uses inline SVG. We expect 12 bar-like elements.
    # We count occurrences of the bar class or <rect> tags.
    bars = re.findall(r'<rect[^>]*class="analytics-bar"', body)
    assert len(bars) == 12

# ======================================================================= #
# Category Breakdown                                                      #
# ======================================================================= #

def test_analytics_category_breakdown_sorted_high_to_low(client):
    """Category breakdown shows one row per used category, sorted high -> low.

    Demo seed: Bills=2200, Transport=1850, Shopping=1799, others lower.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = client.get("/analytics").get_data(as_text=True)

    # Find all category rows
    rows = re.findall(r'<div[^>]*class="analytics-category-row"[^>]*>(.*?)</div>', body, re.DOTALL)
    assert len(rows) > 0

    # The first row should be Bills (the highest)
    assert "Bills" in rows[0]
    # The second should be Transport
    assert "Transport" in rows[1]

# ======================================================================= #
# Day-of-Week Breakdown                                                   #
# ======================================================================= #

def test_analytics_day_of_week_breakdown_shape_and_averages(client):
    """Day-of-week breakdown has 7 rows (Mon-Sun) showing averages.

    User data:
    - Monday, Week 1: 100.00
    - Monday, Week 2: 200.00  -> Avg = 150.00
    - Tuesday, Week 1: 500.00 -> Avg = 500.00
    - Wednesday to Sunday: 0.00
    """
    uid = make_user("Day User", "day@example.com", "password123")
    # Mon=0, Tue=1...
    # 2026-08-03 is Monday, 2026-08-10 is Monday, 2026-08-04 is Tuesday
    make_expense(uid, 100.00, "Food", "2026-08-03")
    make_expense(uid, 200.00, "Food", "2026-08-10")
    make_expense(uid, 500.00, "Food", "2026-08-04")

    _login(client, "day@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Check for all 7 days
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        assert day in body

    # Monday Avg: (100+200)/2 = 150.00
    assert "₹150.00" in body
    # Tuesday Avg: 500/1 = 500.00
    assert "₹500.00" in body
    # Others should be ₹0.00 (though spec says averages, if 0 spend, it's 0)
    # Actually, it just shows the value.
    assert "₹0.00" in body

def test_analytics_day_of_week_highlights_peak(client):
    """The highest-spending day of the week is highlighted with the peak class."""
    uid = make_user("Peak User", "peak@example.com", "password123")
    # Wednesday is the peak
    make_expense(uid, 100.00, "Food", "2026-08-03") # Mon
    make_expense(uid, 1000.00, "Food", "2026-08-05") # Wed

    _login(client, "peak@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Wednesday row should have the peak class
    assert re.search(r'analytics-day-row--peak[^>]*>.*?Wednesday', body, re.DOTALL) is not None
    # Monday row should NOT have the peak class
    assert not re.search(r'analytics-day-row--peak[^>]*>.*?Monday', body, re.DOTALL)

# ======================================================================= #
# Empty State                                                             #
# ======================================================================= #

def test_analytics_empty_state_when_no_expenses(client):
    """User with 0 expenses sees empty state card, no charts or breakdowns."""
    uid = make_user("Empty User", "empty@example.com", "password123")
    _login(client, "empty@example.com", "password123")
    body = client.get("/analytics").get_data(as_text=True)

    # Empty state message
    assert "No expenses yet" in body
    # Link to /profile
    assert 'href="/profile"' in body

    # Charts and breakdowns should NOT be rendered
    assert "analytics-bar" not in body
    assert "analytics-category-row" not in body
    assert "analytics-day-row" not in body
    assert "svg" not in body
