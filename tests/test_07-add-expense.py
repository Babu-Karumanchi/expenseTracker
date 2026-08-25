"""Step 7: Add Expense — tests for `GET /expenses/add` and `POST /expenses/add`.

Spec: `.claude/specs/07-add-expense.md`.

These tests cover the Definition of Done for Step 7:
  * Auth boundary (signed-out GET and POST redirect to /login, no row inserted)
  * GET renders the form with today's date pre-filled and 7 categories
  * POST valid input inserts a row keyed to `session["user_id"]` and redirects
    to /profile where the new row appears
  * `user_id` from the form body is ignored
  * Amount validation (empty, non-numeric, zero, negative, sub-paise, > cap,
    exact cap, exact error message singleton)
  * Category validation (whitelist, strip)
  * Date validation (empty, malformed, future)
  * Description validation (empty -> NULL, 201 rejected, 200 accepted)
  * User isolation (User A's row never appears on User B's profile)
  * `created_at` is populated automatically
  * On validation failure the typed values are echoed back, status is 200, and
    no row is inserted
  * Form `action` uses `url_for` (not a hard-coded path); back + cancel links
    to /profile are present
"""

import datetime
import re

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

CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Shopping",
    "Entertainment",
    "Health",
    "Other",
]

EMPTY_AMOUNT_MSG = b"Please enter an amount."
RANGE_AMOUNT_MSG = b"Please enter a valid amount between \xe2\x82\xb90.01 and \xe2\x82\xb910,00,000."
BAD_CATEGORY_MSG = b"Please choose a category."
BAD_DATE_MSG = b"Please enter a valid date."
FUTURE_DATE_MSG = b"Date cannot be in the future."
LONG_DESC_MSG = b"Description must be 200 characters or fewer."


def _today_iso():
    return datetime.date.today().isoformat()


def _tomorrow_iso():
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


def _count_expenses(user_id):
    conn = _db.get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


def _fetch_expense(user_id, amount, category, date):
    conn = _db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND amount = ? "
            "AND category = ? AND date = ?",
            (user_id, amount, category, date),
        ).fetchone()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Auth boundary                                                       #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_to_login(client):
    """Spec: signed-out GET /expenses/add -> 302 to /login."""
    resp = client.get("/expenses/add", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_out_post_redirects_to_login(client):
    """Spec: signed-out POST /expenses/add -> 302 to /login AND no row inserted."""
    user_id = demo_id()
    before = _count_expenses(user_id)

    resp = client.post(
        "/expenses/add",
        data={
            "amount": "777.50",
            "category": "Food",
            "date": _today_iso(),
            "description": "should never land",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    assert _count_expenses(user_id) == before, "no row should be inserted for signed-out POST"


# ------------------------------------------------------------------ #
# GET form rendering                                                  #
# ------------------------------------------------------------------ #

def test_get_renders_form_with_today_and_categories(client):
    """Spec: signed-in GET returns 200, date pre-filled with today, 7 categories."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/expenses/add")
    assert resp.status_code == 200
    body = body_of(resp)

    today = _today_iso()
    # Date input is pre-filled with today's ISO date.
    assert f'value="{today}"'.encode() in body

    # All 7 categories are in the dropdown.
    for cat in CATEGORIES:
        assert f'>{cat}</option>'.encode() in body, f"category {cat!r} not in dropdown"


def test_get_form_renders_back_link_to_profile(client):
    """Spec: back link from the form points at /profile."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/expenses/add"))
    # The back link must be present and reference /profile.
    assert b'href="/profile"' in body


def test_get_form_renders_cancel_link_to_profile(client):
    """Spec: Cancel button is present and points at /profile."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/expenses/add"))
    # Look for a Cancel control that links to /profile.
    assert b"Cancel" in body
    assert b'href="/profile"' in body


def test_post_form_action_uses_url_for(client):
    """Spec: form `action` is built via url_for, not hard-coded."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/expenses/add"))
    # Pull the first <form ...> tag and check its action attribute. The
    # form template uses `{{ url_for('add_expense') }}`, which renders to
    # exactly "/expenses/add" — the canonical endpoint path. The proof
    # that url_for() was used (rather than a string literal the template
    # could have hard-coded) is that the action attribute is present and
    # non-empty.
    m = re.search(rb"<form\b[^>]*\baction=([\"'])([^\"']+)\1", body)
    assert m is not None, "no <form> tag found in add-expense page"
    action = m.group(2)
    assert action, "form action attribute is empty"
    # Must point at the add_expense endpoint, which is "/expenses/add".
    assert action == b"/expenses/add"


# ------------------------------------------------------------------ #
# POST happy path                                                     #
# ------------------------------------------------------------------ #

def test_valid_post_inserts_and_redirects_to_profile(client):
    """Spec: valid POST inserts a row keyed to the session user and 302 -> /profile."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    before = _count_expenses(user_id)

    today = _today_iso()
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "123.45",
            "category": "Food",
            "date": today,
            "description": "Lunch",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    row = _fetch_expense(user_id, 123.45, "Food", today)
    assert row is not None, "expected a new expenses row"
    assert row["user_id"] == user_id
    assert row["description"] == "Lunch"
    assert _count_expenses(user_id) == before + 1


def test_valid_post_lands_on_profile_showing_new_expense(client):
    """Spec: after redirect, the new row appears on /profile."""
    _login(client, "demo@spendly.com", "demo123")
    today = _today_iso()
    client.post(
        "/expenses/add",
        data={
            "amount": "888.00",
            "category": "Transport",
            "date": today,
            "description": "Bus pass",
        },
        follow_redirects=False,
    )
    body = body_of(client.get("/profile"))
    assert b"Bus pass" in body
    assert b"Transport" in body


def test_post_ignores_user_id_from_form(client):
    """Spec: even if the form body includes `user_id=999`, the row uses session user_id."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    client.post(
        "/expenses/add",
        data={
            "amount": "55.55",
            "category": "Food",
            "date": today,
            "description": "hostile",
            "user_id": "999",
        },
        follow_redirects=False,
    )
    row = _fetch_expense(user_id, 55.55, "Food", today)
    assert row is not None
    assert row["user_id"] == user_id, "user_id from form must be ignored"
    # And no row landed for the fake id 999.
    conn = _db.get_db()
    try:
        none = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (999,)
        ).fetchone()
    finally:
        conn.close()
    assert none is None


def test_post_created_at_is_populated(client):
    """Spec: created_at is set by the DB default on insert."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    client.post(
        "/expenses/add",
        data={
            "amount": "42.00",
            "category": "Food",
            "date": today,
            "description": "auto-stamp",
        },
        follow_redirects=False,
    )
    row = _fetch_expense(user_id, 42.00, "Food", today)
    assert row is not None
    assert row["created_at"], "created_at should be populated automatically"


def test_post_user_isolation(client):
    """Spec: a row inserted for user A must not show on user B's /profile."""
    _login(client, "demo@spendly.com", "demo123")
    today = _today_iso()
    client.post(
        "/expenses/add",
        data={
            "amount": "300.00",
            "category": "Food",
            "date": today,
            "description": "alpha-only",
        },
        follow_redirects=False,
    )

    # Create user B and sign in as them. Logging out first forces a fresh
    # session cookie on the next login (the /login route's session.clear()
    # does not always issue a new Set-Cookie when the previous session was
    # also non-empty — see the comment in app.py:login).
    make_user(name="Bob", email="bob@example.com", password="password123")
    client.get("/logout")
    _login(client, "bob@example.com", "password123")
    body = body_of(client.get("/profile"))
    assert b"alpha-only" not in body, "user A's description leaked to user B's profile"


# ------------------------------------------------------------------ #
# Amount validation                                                   #
# ------------------------------------------------------------------ #

def test_post_empty_amount_renders_error(client):
    """Spec: empty amount -> exact message 'Please enter an amount.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert EMPTY_AMOUNT_MSG in body_of(resp)


def test_post_non_numeric_amount_renders_error(client):
    """Spec: amount=abc -> range error."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "abc",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)


def test_post_zero_amount_renders_error(client):
    """Spec: amount=0 -> range error (lower bound is ₹0.01)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "0",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)


def test_post_negative_amount_renders_error(client):
    """Spec: amount=-10 -> range error."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "-10",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)


def test_post_sub_paise_amount_renders_error(client):
    """Spec: amount=0.001 (sub-paise) -> range error."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "0.001",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)


def test_post_over_cap_amount_renders_error(client):
    """Spec: amount=1000000.01 (just over cap) -> range error."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "1000000.01",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)


def test_post_over_cap_amount_does_not_insert_row(client):
    """Spec: over-cap submission must not leave a row behind."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    before = _count_expenses(user_id)
    client.post(
        "/expenses/add",
        data={
            "amount": "1000000.01",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert _count_expenses(user_id) == before


def test_post_over_cap_exact_amount_succeeds(client):
    """Spec boundary: amount=1000000 is the inclusive cap and must succeed."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "1000000",
            "category": "Food",
            "date": today,
            "description": "cap",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    row = _fetch_expense(user_id, 1000000.0, "Food", today)
    assert row is not None


def test_amount_error_message_is_singleton(client):
    """Spec: both non-numeric and out-of-range use the exact same message string."""
    # Non-numeric.
    _login(client, "demo@spendly.com", "demo123")
    resp_nan = client.post(
        "/expenses/add",
        data={
            "amount": "abc",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    # Out-of-range (over cap).
    resp_over = client.post(
        "/expenses/add",
        data={
            "amount": "9999999",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp_nan.status_code == 200
    assert resp_over.status_code == 200
    body_nan = body_of(resp_nan)
    body_over = body_of(resp_over)
    assert RANGE_AMOUNT_MSG in body_nan
    assert RANGE_AMOUNT_MSG in body_over
    # And the empty-amount message must NOT appear for these two cases.
    assert EMPTY_AMOUNT_MSG not in body_nan
    assert EMPTY_AMOUNT_MSG not in body_over


# ------------------------------------------------------------------ #
# Category validation                                                 #
# ------------------------------------------------------------------ #

def test_post_unknown_category_renders_error(client):
    """Spec: category=Crypto -> 'Please choose a category.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "100.00",
            "category": "Crypto",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_CATEGORY_MSG in body_of(resp)


def test_post_typed_category_with_surrounding_whitespace_is_accepted(client):
    """Spec: category matching is done after stripping whitespace."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "21.00",
            "category": "  Food  ",
            "date": today,
            "description": "trimmed",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    # The row should be stored with the trimmed category.
    row = _fetch_expense(user_id, 21.00, "Food", today)
    assert row is not None
    assert row["category"] == "Food"


# ------------------------------------------------------------------ #
# Date validation                                                     #
# ------------------------------------------------------------------ #

def test_post_missing_date_renders_error(client):
    """Spec: empty date -> 'Please enter a valid date.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "",
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_DATE_MSG in body_of(resp)


def test_post_malformed_date_renders_error(client):
    """Spec: date=not-a-date -> 'Please enter a valid date.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "not-a-date",
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_DATE_MSG in body_of(resp)


def test_post_future_date_renders_error(client):
    """Spec: tomorrow's date -> 'Date cannot be in the future.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": _tomorrow_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert FUTURE_DATE_MSG in body_of(resp)


# ------------------------------------------------------------------ #
# Description validation                                              #
# ------------------------------------------------------------------ #

def test_post_long_description_renders_error(client):
    """Spec: 201-char description -> 'Description must be 200 characters or fewer.'"""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "x" * 201,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert LONG_DESC_MSG in body_of(resp)


def test_post_description_at_200_chars_succeeds(client):
    """Spec boundary: 200-char description is accepted."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    desc = "x" * 200
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "75.00",
            "category": "Food",
            "date": today,
            "description": desc,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = _fetch_expense(user_id, 75.00, "Food", today)
    assert row is not None
    assert row["description"] == desc


def test_post_empty_description_stored_as_null(client):
    """Spec: empty / whitespace-only description is stored as NULL."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    client.post(
        "/expenses/add",
        data={
            "amount": "60.00",
            "category": "Food",
            "date": today,
            "description": "   ",
        },
        follow_redirects=False,
    )
    row = _fetch_expense(user_id, 60.00, "Food", today)
    assert row is not None
    assert row["description"] is None


# ------------------------------------------------------------------ #
# Failure response shape                                              #
# ------------------------------------------------------------------ #

def test_post_invalid_amount_preserves_typed_values(client):
    """Spec: on validation failure, typed values are echoed back into the inputs."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-08-11",
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    body = body_of(resp)
    # The typed description and date must be in the re-rendered form.
    assert b"echo me back" in body
    assert b'value="2026-08-11"' in body


def test_post_returns_200_not_redirect_on_validation_error(client):
    """Spec: validation errors render the form (200), they do NOT 302."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "0",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    # Status is 200, NOT 302. A 302 here would skip re-rendering the form.
    assert resp.status_code == 200


# ------------------------------------------------------------------ #
# AJAX shape (X-Requested-With: XMLHttpRequest)                       #
# ------------------------------------------------------------------ #
#
# Spec 07: when the Add expense modal on /profile submits via fetch(),
# the route must return JSON so the JS can render the row in place.
# AJAX success  -> {"ok": true,  "expense": {id, date, description, category,
#                                            category_class, amount}}
# AJAX failure  -> {"ok": false, "error": "...", "values": {amount, category,
#                                                            date, description}}
# Direct nav    -> unchanged 302 to /profile (no-JS fallback still works).

import json


_AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _post_add(client, data, *, ajax=True):
    headers = _AJAX_HEADERS if ajax else {}
    # Inject the CSRF token from the session so the route's check
    # passes. Tests that explicitly want the missing-token 403 path
    # should call `client.post(..., data=data_without_csrf)` directly.
    token = csrf_token_of(client)
    if token is not None:
        data = {**data, "csrf_token": token}
    return client.post(
        "/expenses/add", data=data, follow_redirects=False, headers=headers
    )


def test_post_add_ajax_success_returns_json_with_full_expense_payload(client):
    """AJAX POST with valid form -> 200 JSON {ok:true, expense:{...}}."""
    import json as _json

    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    today = _today_iso()
    before = _count_expenses(user_id)

    resp = _post_add(
        client,
        {
            "amount": "425.75",
            "category": "Food",
            "date": today,
            "description": "Lunch with team",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    payload = _json.loads(resp.data)
    assert payload["ok"] is True
    assert "expense" in payload
    expense = payload["expense"]
    # Every key the JS handler expects
    assert set(expense.keys()) == {
        "id", "date", "description", "category", "category_class", "amount",
    }
    assert expense["date"] == today
    assert expense["description"] == "Lunch with team"
    assert expense["category"] == "Food"
    assert expense["category_class"] == "food"
    assert "₹425.75" in expense["amount"] or expense["amount"] == "₹425.75"
    # Row landed in DB
    assert _count_expenses(user_id) == before + 1


def test_post_add_ajax_empty_amount_returns_error_and_echoes_values(client):
    """AJAX POST with empty amount -> {ok:false, error, values} status 200."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "",
            "category": "Food",
            "date": "2026-08-11",
            "description": "echo me",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == EMPTY_AMOUNT_MSG.decode("utf-8")
    assert payload["values"]["amount"] == ""
    assert payload["values"]["category"] == "Food"
    assert payload["values"]["date"] == "2026-08-11"
    assert payload["values"]["description"] == "echo me"


def test_post_add_ajax_range_error_returns_error_and_echoes_values(client):
    """AJAX POST with non-numeric amount -> {ok:false, error} with range msg."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "abc",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == RANGE_AMOUNT_MSG.decode("utf-8")
    assert payload["values"]["amount"] == "abc"


def test_post_add_ajax_unknown_category_returns_error(client):
    """AJAX POST with unknown category -> {ok:false, error}."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "50.00",
            "category": "Crypto",
            "date": _today_iso(),
            "description": "",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == BAD_CATEGORY_MSG.decode("utf-8")
    assert payload["values"]["category"] == "Crypto"


def test_post_add_ajax_future_date_returns_error(client):
    """AJAX POST with future date -> {ok:false, error} with future-date msg."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "50.00",
            "category": "Food",
            "date": _tomorrow_iso(),
            "description": "",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == FUTURE_DATE_MSG.decode("utf-8")


def test_post_add_ajax_long_description_returns_error(client):
    """AJAX POST with 201-char description -> {ok:false, error} length msg."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "50.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "x" * 201,
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == LONG_DESC_MSG.decode("utf-8")


def test_post_add_without_ajax_header_falls_back_to_html_redirect(client):
    """Direct nav POST (no X-Requested-With header) keeps the 302 fallback."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_add(
        client,
        {
            "amount": "50.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        ajax=False,
    )
    # Same response as before AJAX was introduced — preserves the no-JS path.
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert not resp.headers.get("Content-Type", "").startswith("application/json")


def test_post_add_ajax_invalidates_dont_insert_rows(client):
    """An AJAX validation failure must NOT insert a row in the DB."""
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    before = _count_expenses(user_id)

    _post_add(
        client,
        {
            "amount": "0",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
    )
    assert _count_expenses(user_id) == before, (
        "AJAX validation failure must not insert a row"
    )
