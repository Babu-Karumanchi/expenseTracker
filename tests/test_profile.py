"""Tests for the /profile page.

Covers Step 5 (live-data behaviour, auth guard, user isolation, empty
state, INR formatting) and Step 6 (date-range filter with From / To
query parameters, validation, swap-on-reversal).
"""

import re

import pytest

from tests.conftest import _login, body_of, make_expense, make_user


# Currency cells must match this exact shape — Indian formatting via the
# route's f"₹{amount:,.2f}" format string.
INR_RE = re.compile(r"₹\d{1,3}(?:,\d{3})*\.\d{2}".encode("utf-8"))


# ------------------------------------------------------------------ #
# Step 5 — live-data regression                                       #
# ------------------------------------------------------------------ #

def test_profile_auth_guard_redirects_to_login(client):
    """Signed-out GET /profile -> 302 to /login."""
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_renders_live_data_for_demo(client):
    """The seeded demo user's real data is rendered, not hardcoded placeholders."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data
    # User-info card
    assert b"Demo User" in body
    assert b"demo@spendly.com" in body
    # Navbar greeting uses session["user_name"]
    assert b"Hi, Demo User" in body
    # One of the seeded descriptions (proves Step 5 wiring is intact)
    assert b"Sunday breakfast" in body
    # Grand total for the seeded 8 expenses
    assert b"\xe2\x82\xb98,148.00" in body  # ₹8,148.00


def test_profile_isolates_expenses_between_users(client):
    """A second user does not see the demo user's data."""
    # Register a brand-new user via the public route, then log in as them.
    client.post(
        "/register",
        data={
            "name": "Other User",
            "email": "other@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=False,
    )
    # Register route logs us straight in -> /profile. Sign out, then log
    # back in via the canonical login flow used by every other test.
    client.get("/logout")
    _login(client, "other@example.com", "password123")

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data
    assert b"Other User" in body
    assert b"other@example.com" in body
    # Demo's data must NOT be present
    assert b"Demo User" not in body
    assert b"demo@spendly.com" not in body
    assert b"Sunday breakfast" not in body


def test_profile_empty_user_renders_cleanly(client):
    """A user with zero expenses still gets 200 + zeroed stats."""
    # Register a fresh user — demo is seeded with 8 expenses, so we
    # need a brand-new account to exercise the empty-state branch.
    client.post(
        "/register",
        data={
            "name": "Empty User",
            "email": "empty@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=False,
    )
    client.get("/logout")
    _login(client, "empty@example.com", "password123")

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data
    assert b"\xe2\x82\xb90.00" in body  # ₹0.00
    # The em-dash placeholder for the top-category stat
    assert b"\xe2\x80\x94" in body  # —
    # Transactions stat should be 0 (the count span now carries an id so
    # the modal JS handler can update it in place after add/delete).
    assert b'<span id="profile-txn-count" class="profile-stat-value">0</span>' in body


def test_profile_inr_formatting(client):
    """Every monetary cell on the page matches the canonical INR regex."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/profile")
    assert resp.status_code == 200
    matches = INR_RE.findall(resp.data)
    # Demo has 8 expenses -> 1 grand total + 8 amount cells + 8 balance
    # cells + 1 top-category meta = 18 INR cells, plus any meta text.
    assert len(matches) >= 10, f"unexpectedly few INR cells: {matches!r}"


# ------------------------------------------------------------------ #
# Step 6 — date-range filter                                          #
# ------------------------------------------------------------------ #

def test_filter_from_and_to_returns_window_only(client, seeded_user):
    """?from=2026-04-01&to=2026-08-31 returns only the in-window rows."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01&to=2026-08-31")
    assert resp.status_code == 200
    body = resp.data
    assert b"April commute" in body
    assert b"August electricity" in body
    # The January row must be filtered out
    assert b"January groceries" not in body
    # Status line reflects the filtered count (2 rows, pluralised)
    assert b"Showing 2 transactions from 2026-04-01 to 2026-08-31" in body


def test_filter_from_only_is_open_ended_upper(client, seeded_user):
    """?from=2026-04-01 (no `to`) is open-ended on the upper side."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01")
    assert resp.status_code == 200
    body = resp.data
    assert b"April commute" in body
    assert b"August electricity" in body
    assert b"January groceries" not in body
    assert b"Showing 2 transactions from 2026-04-01" in body


def test_filter_to_only_is_open_ended_lower(client, seeded_user):
    """?to=2026-04-30 (no `from`) is open-ended on the lower side."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?to=2026-04-30")
    assert resp.status_code == 200
    body = resp.data
    assert b"January groceries" in body
    assert b"April commute" in body
    assert b"August electricity" not in body
    assert b"Showing 2 transactions up to 2026-04-30" in body


def test_filter_absent_matches_step5_behaviour(client, seeded_user):
    """No filter params -> all rows, "Showing all N transactions" status."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data
    assert b"January groceries" in body
    assert b"April commute" in body
    assert b"August electricity" in body
    assert b"Showing all 3 transactions." in body


def test_filter_invalid_date_renders_200_with_error(client, seeded_user):
    """Malformed `from` is dropped; valid `to` still applies; inline error shown."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=not-a-date&to=2026-04-30")
    assert resp.status_code == 200
    body = resp.data
    # Inline error renders with the danger modifier class
    assert b"Please enter valid dates (YYYY-MM-DD)." in body
    assert b"profile-filter-status--danger" in body
    # The valid `to` bound survives: rows on/before 2026-04-30 are still
    # in the page, and the August row is filtered out.
    assert b"January groceries" in body
    assert b"April commute" in body
    assert b"August electricity" not in body


def test_filter_from_greater_than_to_swaps_and_renders_200(client, seeded_user):
    """Reversed bounds are swapped so the query still returns useful data."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-08-31&to=2026-08-01")
    assert resp.status_code == 200
    body = resp.data
    # Swap message in the danger state
    assert b"From date cannot be after To date." in body
    assert b"profile-filter-status--danger" in body
    # The swapped window [2026-08-01, 2026-08-31] contains the August row
    # but not the April or January ones.
    assert b"August electricity" in body
    assert b"April commute" not in body
    assert b"January groceries" not in body


def test_filter_does_not_affect_navbar_greeting(client, seeded_user):
    """The navbar greeting ignores the filter — it always reflects session name."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-08-01&to=2026-08-31")
    assert resp.status_code == 200
    assert b"Hi, Filter User" in resp.data


def test_filter_does_not_leak_across_users(client, seeded_user):
    """With a filter active, demo's view still does not show other users' rows."""
    # Add a single expense to the demo user (already seeded with 8) at a
    # date well inside the filter window. Then register a second user
    # with one expense at the same date — sign back in as demo and
    # confirm the second user's description is filtered out.
    other_id = make_user("Leaky Other", "leaky@example.com", "password123")
    make_expense(other_id, 999.00, "Food", "2026-08-10", "SECRET_LEAK_DESC")

    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/profile?from=2026-08-01&to=2026-08-31")
    assert resp.status_code == 200
    assert b"SECRET_LEAK_DESC" not in resp.data
    # And the second user's identity / email should not appear either
    assert b"Leaky Other" not in resp.data
    assert b"leaky@example.com" not in resp.data


# ------------------------------------------------------------------ #
# Pill presets                                                       #
# ------------------------------------------------------------------ #

def _pin_today(monkeypatch, iso):
    """Pin app._today to a fixed date so preset ranges are deterministic."""
    from datetime import date
    fixed = date.fromisoformat(iso)
    monkeypatch.setattr("app._today", lambda: fixed)


def test_pill_all_time_is_active_by_default(client, seeded_user):
    """No query string -> All Time pill has the active class."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Active pill count must be exactly 1 (All Time).
    assert body.count("profile-pill--active") == 1
    # All four labels render
    assert "All Time" in body
    assert "This Month" in body
    assert "Last 3 Months" in body
    assert "Last 6 Months" in body


def test_pill_this_month_applies_correct_range(client, seeded_user, monkeypatch):
    """?preset=this_month -> from=1st-of-month, to=today; pill is active."""
    # Pin today to Aug 20 so the seeded Aug 15 row falls inside every
    # preset's window (this_month = Aug 1..20, last_3 = May 20..Aug 20).
    _pin_today(monkeypatch, "2026-08-20")
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?preset=this_month")
    assert resp.status_code == 200
    body = resp.data
    assert b"August electricity" in body
    assert b"April commute" not in body
    assert b"January groceries" not in body
    assert b'value="2026-08-01"' in body
    assert b'value="2026-08-20"' in body


def test_pill_last_3_months_applies_correct_range(client, seeded_user, monkeypatch):
    """?preset=last_3_months -> from=today-3mo, to=today; covers Aug only."""
    _pin_today(monkeypatch, "2026-08-20")
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?preset=last_3_months")
    assert resp.status_code == 200
    body = resp.data
    # Window is [2026-05-20, 2026-08-20] -> only August (Aug 15) survives.
    assert b"August electricity" in body
    assert b"April commute" not in body
    assert b"January groceries" not in body


def test_pill_last_6_months_applies_correct_range(client, seeded_user, monkeypatch):
    """?preset=last_6_months -> from=today-6mo, to=today; covers Apr+Aug."""
    _pin_today(monkeypatch, "2026-08-20")
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?preset=last_6_months")
    assert resp.status_code == 200
    body = resp.data
    # Window is [2026-02-20, 2026-08-20] -> April + August survive.
    assert b"August electricity" in body
    assert b"April commute" in body
    assert b"January groceries" not in body


def test_pill_active_state_highlights_only_the_matching_pill(client, seeded_user):
    """?preset=this_month -> only the This Month pill has the active class."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?preset=this_month")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert body.count("profile-pill--active") == 1
    assert 'profile-pill--active' in body and '>This Month<' in body
    # The All Time pill href should NOT have the active class on it.
    assert 'href="/profile?preset=all_time"' in body


def test_manual_date_edit_clears_active_preset(client, seeded_user):
    """A bare ?from=/?to= with no ?preset -> no pill is highlighted."""
    _login(client, "filter@example.com", "password123")
    resp = client.get("/profile?from=2026-04-01&to=2026-04-30")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "profile-pill--active" not in body


# ------------------------------------------------------------------ #
# Add expense modal — inline form modal for the + Add expense CTA.   #
# ------------------------------------------------------------------ #

def test_profile_renders_add_expense_modal(client):
    """The + Add expense CTA on /profile opens a styled modal containing
    a real form (no navigation). Verified by finding the modal block,
    the trigger, the heading, the form, and the Cancel button.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # The CTA on the user-info card carries the trigger.
    assert b'data-open-modal="add-expense-modal"' in body

    # The modal div is present, hidden by default, with the right a11y attributes.
    modal_match = re.search(
        rb'<div\s+id="add-expense-modal"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match is not None, "add-expense-modal block not found"
    modal_html = modal_match.group(1)

    # Heading
    assert b"Add expense" in modal_html

    # Real form, posting to /expenses/add, marked for AJAX submission.
    form_match = re.search(
        rb'<form\b[^>]*action="/expenses/add"[^>]*data-ajax-form',
        modal_html,
    )
    assert form_match is not None, "add-expense-modal missing POST form with data-ajax-form"
    form_html = form_match.group(0)

    # Four inputs by name.
    for name in (b'amount', b'category', b'date', b'description'):
        assert (b'name="' + name + b'"') in modal_html, (
            f"add-expense-modal missing input name={name!r}"
        )

    # Submit button labelled "Save expense".
    assert re.search(
        rb'<button[^>]*type="submit"[^>]*>\s*Save expense\s*</button>',
        modal_html,
    ) is not None, "add-expense-modal missing 'Save expense' submit button"

    # Cancel button (closes only, does NOT submit the form).
    assert re.search(
        rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>\s*Cancel\s*</button>',
        modal_html,
    ) is not None, "add-expense-modal missing Cancel button"


def test_profile_edit_modal_contains_form_pre_populated_from_row(client):
    """Each row's edit modal on /profile contains a real <form method=post
    action=/expenses/<id>/edit data-ajax-form> pre-populated from the
    row's current values. Submitting via fetch updates the row in place.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # Find the FIRST edit-modal block (the seeded demo user has at least
    # one row, so the loop renders at least one block).
    modal_match = re.search(
        rb'<div\s+id="edit-modal-(\d+)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match is not None, "no edit-modal-<id> block found on /profile"
    eid = modal_match.group(1)
    modal_html = modal_match.group(2)

    # Form posts to /expenses/<id>/edit with data-ajax-form.
    expected_action = b'/expenses/' + eid + b'/edit'
    form_match = re.search(
        rb'<form\b[^>]*action="' + re.escape(expected_action) + rb'"[^>]*data-ajax-form',
        modal_html,
    )
    assert form_match is not None, (
        f"edit-modal-{eid.decode()} missing POST form with action "
        f"{expected_action!r} and data-ajax-form"
    )

    # Four inputs by name.
    for name in (b'amount', b'category', b'date', b'description'):
        assert (b'name="' + name + b'"') in modal_html, (
            f"edit-modal-{eid.decode()} missing input name={name!r}"
        )

    # Submit button labelled "Save changes".
    assert re.search(
        rb'<button[^>]*type="submit"[^>]*>\s*Save changes\s*</button>',
        modal_html,
    ) is not None, f"edit-modal-{eid.decode()} missing 'Save changes' submit button"

    # Cancel button (closes only).
    assert re.search(
        rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>\s*Cancel\s*</button>',
        modal_html,
    ) is not None, f"edit-modal-{eid.decode()} missing Cancel button"


def test_profile_delete_modal_contains_form_with_ajax_submit_button(client):
    """Each row's delete modal on /profile contains a <form data-ajax-form>
    whose submit button carries data-ajax-submit (replaces the old
    data-close-modal-and-submit attribute). Cancel button stays as a
    pure data-close-modal marker.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # Each delete modal must have at least one Cancel button (data-close-modal,
    # NOT data-ajax-submit).
    cancel_buttons = re.findall(
        rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>\s*Cancel\s*</button>',
        body,
    )
    assert len(cancel_buttons) >= 1, "expected at least one Cancel button on /profile"

    # Each delete modal must contain a Delete submit button carrying
    # data-ajax-submit AND class btn-danger.
    delete_buttons = re.findall(
        rb'<button[^>]*data-ajax-submit[^>]*>',
        body,
    )
    assert len(delete_buttons) >= 1, "expected at least one Delete submit button"

    for btn in delete_buttons:
        assert b"btn-danger" in btn, f"Delete button missing btn-danger class: {btn!r}"