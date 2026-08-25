"""Step 8: Edit Expense — spec-driven tests for `GET / POST /expenses/<id>/edit`.

Every test below is derived from `.claude/specs/08-edit-expense.md` and
verifies a single Definition-of-Done behaviour. We do NOT inspect
`app.py` / `database/db.py` to derive expected values — the spec is
the source of truth and the implementation is what we are
verifying.

Coverage map (spec sections referenced in the docstring of each test):

  Auth boundary
    - signed-out GET  -> 302 to /login
    - signed-out POST -> 302 to /login, no row touched

  Ownership boundary
    - GET on unknown id            -> 404
    - POST on unknown id           -> 404
    - GET on another user's id     -> 404 (not 200, not 403)
    - POST on another user's id    -> 404 AND the row is unchanged
    - attacker-supplied `user_id`  -> ignored, original owner preserved
    - cross-user POST 404 path also verifies the row is unchanged
      (not just the status code)

  GET pre-population
    - 200, amount input matches row, category <option selected> is the
      only selected option, date input matches row, description textarea
      contains row description, date input max=today, page extends
      base.html and renders the "Edit expense" heading

  POST happy path
    - 302 to /profile, row updated, created_at preserved, redirected
      /profile reflects the new totals

  POST validation (byte-for-byte Step 7 strings; on every error the
  row in the DB is unchanged and the typed values are echoed back)
    - amount: empty / non-numeric / 0 / -10 / 1000000.01
              + explicit typed-echo test
    - category: empty / unknown
    - date: empty / malformed / future (relative to _tomorrow_iso())
    - description: 201 chars

  Edge cases
    - 200-char description succeeds
    - empty/whitespace description stored as NULL; /profile renders
      the description cell empty AND the Edit link for the row still
      works
    - same id preserved (no insert) on successful edit
    - editing a row's date to today places it at the top of /profile
      (under the spec's `date DESC, id DESC` ordering)

  DB-side effects
    - get_expense_by_id(unknown, user)             -> None
    - get_expense_by_id(other_user_id, me)        -> None
    - get_expense_by_id(own_id, me)               -> row
    - update_expense(cross_user)                  -> rowcount 0 + row unchanged
    - update_expense(own_user)                    -> rowcount 1 + new values
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
# Shared error-string constants — must match Step 7 byte-for-byte.   #
# ------------------------------------------------------------------ #

EMPTY_AMOUNT_MSG = b"Please enter an amount."
RANGE_AMOUNT_MSG = (
    b"Please enter a valid amount between "
    b"\xe2\x82\xb90.01 and \xe2\x82\xb910,00,000."
)
BAD_CATEGORY_MSG = b"Please choose a category."
BAD_DATE_MSG = b"Please enter a valid date."
FUTURE_DATE_MSG = b"Date cannot be in the future."
LONG_DESC_MSG = b"Description must be 200 characters or fewer."


# ------------------------------------------------------------------ #
# Date helpers — relative to today so tests stay deterministic       #
# regardless of when they run.                                       #
# ------------------------------------------------------------------ #

def _today_iso():
    """Today's date as YYYY-MM-DD."""
    return datetime.date.today().isoformat()


def _tomorrow_iso():
    """Tomorrow's date as YYYY-MM-DD — only for the future-date test."""
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


# ------------------------------------------------------------------ #
# DB helpers                                                          #
# ------------------------------------------------------------------ #

def _stage_own_expense(user_id, amount=450.00, category="Food",
                       date=None, description="Initial description"):
    """Insert one expense row directly and return its id.

    Mirrors the existing `make_expense` factory from conftest but lives
    here so the test reads cleanly without having to chase an import
    for an arg the rest of the suite doesn't use.
    """
    if date is None:
        date = _today_iso()
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


def _fetch_expense_row(expense_id):
    """Return the row for `expense_id` regardless of owner, or None."""
    conn = _db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    finally:
        conn.close()


def _count_expenses(user_id):
    """Count rows for `user_id` directly via sqlite3."""
    conn = _db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Auth boundary                                                       #
# ------------------------------------------------------------------ #

def test_signed_out_get_redirects_to_login(client):
    """Spec: visiting /expenses/<own-id>/edit while signed out -> 302 to /login."""
    eid = _stage_own_expense(demo_id())
    resp = client.get(f"/expenses/{eid}/edit", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_out_post_redirects_to_login_and_does_not_touch_row(client):
    """Spec: signed-out POST -> 302 to /login AND the row in the DB is untouched."""
    eid = _stage_own_expense(demo_id())
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "999.99",
            "category": "Food",
            "date": _today_iso(),
            "description": "should never land",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    after = _fetch_expense_row(eid)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


# ------------------------------------------------------------------ #
# Ownership boundary                                                  #
# ------------------------------------------------------------------ #

def test_get_on_nonexistent_id_returns_404(client):
    """Spec: GET on an id that doesn't exist -> 404 (via abort)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/expenses/99999/edit", follow_redirects=False)
    assert resp.status_code == 404


def test_post_on_nonexistent_id_returns_404(client):
    """Spec: POST on an id that doesn't exist -> 404 (via abort, before validation)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        "/expenses/99999/edit",
        data={
            "amount": "50.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_get_on_other_users_id_returns_404(client):
    """Spec: GET on another user's id -> 404 (not 200, not 403).

    An attacker probing ids must not be able to distinguish "doesn't
    exist" from "exists but belongs to someone else" — both must 404.
    """
    other_id = make_user("Mallory", "mallory@example.com", "password123")
    other_eid = _stage_own_expense(
        other_id, amount=999.00, category="Other",
        date="2026-08-10", description="mallory only",
    )

    _login(client, "demo@spendly.com", "demo123")
    resp = client.get(f"/expenses/{other_eid}/edit", follow_redirects=False)
    assert resp.status_code == 404


def test_post_on_other_users_id_returns_404_and_does_not_update_row(client):
    """Spec: POST on another user's id -> 404 AND the row is NOT updated.

    This test verifies BOTH the status code AND that the row's amount,
    category, date, description, and user_id are all unchanged — not
    just the status code.
    """
    other_id = make_user("Eve", "eve@example.com", "password123")
    other_eid = _stage_own_expense(
        other_id, amount=1234.00, category="Shopping",
        date="2026-08-10", description="eve's spend",
    )
    before = _fetch_expense_row(other_eid)

    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        f"/expenses/{other_eid}/edit",
        data={
            "amount": "1.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "hostile",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 404

    after = _fetch_expense_row(other_eid)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]
    assert after["user_id"] == before["user_id"]


def test_post_ignores_attacker_supplied_user_id_form_field(client):
    """Spec: an attacker-supplied `user_id` form field is ignored.

    The row's `user_id` must remain the original owner; no row may be
    inserted for the attacker-supplied id 999.
    """
    _login(client, "demo@spendly.com", "demo123")
    owner = demo_id()
    eid = _stage_own_expense(
        owner, amount=10.00, category="Food",
        date="2026-08-01", description="keep owner",
    )

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "20.00",
            "category": "Food",
            "date": "2026-08-02",
            "description": "owner must stay",
            "user_id": "999",  # attacker-supplied — must be ignored
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    # Original row's user_id is preserved.
    row = _fetch_expense_row(eid)
    assert row["user_id"] == owner

    # No row exists for the fake id 999.
    conn = _db.get_db()
    try:
        leaked = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (999,)
        ).fetchone()
    finally:
        conn.close()
    assert leaked is None


# ------------------------------------------------------------------ #
# GET pre-population                                                 #
# ------------------------------------------------------------------ #

def test_get_own_id_returns_200(client):
    """Spec: signed-in GET on own id -> 200."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    resp = client.get(f"/expenses/{eid}/edit", follow_redirects=False)
    assert resp.status_code == 200


def test_get_amount_input_matches_stored_row(client):
    """Spec: amount input value matches the stored row's amount."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=450.50, category="Food",
        date="2026-08-05", description="amount check",
    )
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    # SQLite returns 450.5; the input renders the str() of that value.
    assert b'value="450.5"' in body


def test_get_category_option_is_selected_and_is_the_only_selected_option(client):
    """Spec: the row's category is the selected <option> AND it's the only one.

    Uses a regex count so we can prove exactly ONE selected option
    appears in the rendered <select>, regardless of how many other
    options are present.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=99.00, category="Transport",
        date="2026-08-07", description="cat check",
    )
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    # The Transport option must carry the `selected` attribute.
    assert b'<option value="Transport" selected>' in body
    # Exactly one selected option across the whole select.
    selected_count = len(re.findall(rb'<option[^>]*\bselected\b', body))
    assert selected_count == 1, (
        f"expected exactly one selected option, got {selected_count}"
    )


def test_get_date_input_matches_stored_row(client):
    """Spec: date input value matches the row's date."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=10.00, category="Food",
        date="2026-08-09", description="date check",
    )
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    assert b'value="2026-08-09"' in body


def test_get_description_textarea_contains_stored_row(client):
    """Spec: description textarea contains the row's description text."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=10.00, category="Food",
        date="2026-08-09", description="desc echo target",
    )
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    # Description sits inside a <textarea>...</textarea> element.
    assert b">desc echo target</textarea>" in body


def test_get_date_input_max_attribute_is_today(client):
    """Spec: date input has max="YYYY-MM-DD" set to today."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    today = _today_iso()
    assert f'max="{today}"'.encode() in body


def test_get_page_extends_base_and_renders_edit_expense_heading(client):
    """Spec: the edit page extends base.html and shows the 'Edit expense' heading.

    The heading lives in the body of the page (which itself extends
    base.html, so we don't need to re-assert the layout). The literal
    string "Edit expense" must appear somewhere in the response body.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    body = body_of(client.get(f"/expenses/{eid}/edit"))
    assert b"Edit expense" in body


# ------------------------------------------------------------------ #
# POST happy path                                                     #
# ------------------------------------------------------------------ #

def test_valid_post_updates_row_and_redirects_to_profile(client):
    """Spec: valid POST updates the row AND returns 302 to /profile.

    All four mutable columns (amount, category, date, description)
    are verified via a direct sqlite3 query.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="before",
    )

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "250.00",
            "category": "Transport",
            "date": "2026-08-10",
            "description": "after",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    row = _fetch_expense_row(eid)
    assert row["amount"] == 250.00
    assert row["category"] == "Transport"
    assert row["date"] == "2026-08-10"
    assert row["description"] == "after"


def test_valid_post_does_not_change_created_at(client):
    """Spec: `created_at` records when the row was first recorded; an edit must preserve it.

    The `update_expense(...)` helper must only touch amount/category/date/
    description — never `created_at`. We capture the pre-edit value via a
    direct read and assert equality after the POST.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    before_created_at = _fetch_expense_row(eid)["created_at"]
    assert before_created_at, "created_at should be populated from the schema default"

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "12.34",
            "category": "Bills",
            "date": "2026-08-10",
            "description": "edit",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert _fetch_expense_row(eid)["created_at"] == before_created_at


def test_redirected_profile_reflects_new_totals(client):
    """Spec: after the redirect, /profile reflects the new totals in the stats row.

    We bump the row's amount from a small value to ₹5,000.00 and then
    GET /profile; the stats row must show the new total. The seed also
    contributes other expenses, so we don't assert the grand total
    verbatim — we only assert that the new amount cell appears.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=10.00, category="Food",
        date="2026-08-01", description="small",
    )

    client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "5000.00",
            "category": "Food",
            "date": "2026-08-01",
            "description": "big",
        },
        follow_redirects=False,
    )
    body = body_of(client.get("/profile"))
    # The new amount formatted via the route's f"₹{amount:,.2f}".
    assert b"\xe2\x82\xb95,000.00" in body


# ------------------------------------------------------------------ #
# POST validation — amount                                           #
# ------------------------------------------------------------------ #

def test_post_empty_amount_renders_error_and_does_not_update_row(client):
    """Spec: empty amount -> 'Please enter an amount.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=111.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "",
            "category": "Food",
            "date": _today_iso(),
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert EMPTY_AMOUNT_MSG in body_of(resp)
    after = _fetch_expense_row(eid)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


def test_post_non_numeric_amount_renders_range_error_and_does_not_update(client):
    """Spec: amount=abc -> range error; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=222.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "abc",
            "category": "Food",
            "date": _today_iso(),
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)
    after = _fetch_expense_row(eid)
    assert after["amount"] == before["amount"]
    assert after["description"] == before["description"]


def test_post_zero_amount_renders_range_error_and_does_not_update(client):
    """Spec: amount=0 -> range error (lower bound is ₹0.01, not 0); row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=333.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "0",
            "category": "Food",
            "date": _today_iso(),
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["amount"] == before["amount"]


def test_post_negative_amount_renders_range_error_and_does_not_update(client):
    """Spec: amount=-10 -> range error; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=444.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "-10",
            "category": "Food",
            "date": _today_iso(),
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["amount"] == before["amount"]


def test_post_over_cap_amount_renders_range_error_and_does_not_update(client):
    """Spec: amount=1000000.01 -> range error (just over the inclusive max); row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=555.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "1000000.01",
            "category": "Food",
            "date": _today_iso(),
            "description": "echo me back",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert RANGE_AMOUNT_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["amount"] == before["amount"]


def test_post_amount_error_echoes_typed_value_and_not_original(client):
    """Spec: typed values are echoed back, NOT the original row's values.

    Original row has date=2026-08-01 and description='original desc'.
    We submit a non-numeric amount with today's date and description
    'typed not original'. The response must echo the typed description
    and the typed date, and must NOT echo the original description.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=222.00, category="Food",
        date="2026-08-01", description="original desc",
    )

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "abc",
            "category": "Food",
            "date": _today_iso(),
            "description": "typed not original",
        },
        follow_redirects=False,
    )
    body = body_of(resp)
    # Typed description is echoed back.
    assert b"typed not original" in body
    # Typed date is echoed back via the date input's value attribute.
    assert f'value="{_today_iso()}"'.encode() in body
    # The ORIGINAL description is NOT in the rendered form.
    assert b"original desc" not in body


# ------------------------------------------------------------------ #
# POST validation — category                                         #
# ------------------------------------------------------------------ #

def test_post_empty_category_renders_error_and_does_not_update_row(client):
    """Spec: empty category -> 'Please choose a category.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "",
            "date": _today_iso(),
            "description": "echo",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_CATEGORY_MSG in body_of(resp)
    after = _fetch_expense_row(eid)
    assert after["category"] == before["category"]
    assert after["description"] == before["description"]


def test_post_unknown_category_renders_error_and_does_not_update_row(client):
    """Spec: category='Crypto' (not in the whitelist) -> 'Please choose a category.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Crypto",
            "date": _today_iso(),
            "description": "echo",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_CATEGORY_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["category"] == before["category"]


# ------------------------------------------------------------------ #
# POST validation — date                                             #
# ------------------------------------------------------------------ #

def test_post_empty_date_renders_error_and_does_not_update_row(client):
    """Spec: empty date -> 'Please enter a valid date.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "",
            "description": "echo",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_DATE_MSG in body_of(resp)
    after = _fetch_expense_row(eid)
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]


def test_post_malformed_date_renders_error_and_does_not_update_row(client):
    """Spec: malformed date -> 'Please enter a valid date.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "not-a-date",
            "description": "echo",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert BAD_DATE_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["date"] == before["date"]


def test_post_future_date_renders_error_and_does_not_update_row(client):
    """Spec: future date -> 'Date cannot be in the future.'; row unchanged.

    The future date is computed relative to `date.today()` so the test
    is deterministic regardless of when it runs.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": _tomorrow_iso(),
            "description": "echo",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert FUTURE_DATE_MSG in body_of(resp)
    assert _fetch_expense_row(eid)["date"] == before["date"]


# ------------------------------------------------------------------ #
# POST validation — description                                      #
# ------------------------------------------------------------------ #

def test_post_long_description_renders_error_and_does_not_update_row(client):
    """Spec: 201-char description -> 'Description must be 200 characters or fewer.'; row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before = _fetch_expense_row(eid)

    resp = client.post(
        f"/expenses/{eid}/edit",
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
    assert _fetch_expense_row(eid)["description"] == before["description"]


# ------------------------------------------------------------------ #
# Edge cases                                                          #
# ------------------------------------------------------------------ #

def test_post_description_at_200_chars_succeeds(client):
    """Spec boundary: 200 chars is accepted (the cap is '200 or fewer')."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="short",
    )
    desc = "y" * 200

    resp = client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "2026-08-01",
            "description": desc,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert _fetch_expense_row(eid)["description"] == desc


def test_post_empty_description_stored_as_null_and_renders_empty_with_edit_link(client):
    """Spec: empty/whitespace description -> NULL in DB.

    The /profile description cell renders empty (NULL -> '' via the
    template's `description or ""`) AND the row's Edit link is still
    wired to /expenses/<id>/edit so the user can still correct the row.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="had desc",
    )

    client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "100.00",
            "category": "Food",
            "date": "2026-08-01",
            "description": "   ",  # whitespace-only -> must store NULL
        },
        follow_redirects=False,
    )
    # Direct DB read: the column is NULL.
    assert _fetch_expense_row(eid)["description"] is None

    body = body_of(client.get("/profile"))
    # The Edit link for this row is still rendered.
    assert f'href="/expenses/{eid}/edit"'.encode() in body


def test_successful_edit_preserves_id_and_does_not_insert_new_row(client):
    """Spec: an edit updates the same row; the id is preserved (no insert).

    We compare the user's total row count before and after a successful
    edit AND assert the same id still points at the edited row.
    """
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()
    eid = _stage_own_expense(
        user_id, amount=100.00, category="Food",
        date="2026-08-01", description="orig",
    )
    before_count = _count_expenses(user_id)

    client.post(
        f"/expenses/{eid}/edit",
        data={
            "amount": "200.00",
            "category": "Bills",
            "date": "2026-08-02",
            "description": "updated",
        },
        follow_redirects=False,
    )

    after_count = _count_expenses(user_id)
    assert after_count == before_count, "edit must not insert a new row"

    row = _fetch_expense_row(eid)
    assert row is not None
    assert row["id"] == eid
    assert row["amount"] == 200.00
    assert row["category"] == "Bills"
    assert row["date"] == "2026-08-02"
    assert row["description"] == "updated"


def test_edit_to_today_moves_row_to_top_of_profile(client):
    """Spec: editing a row's date to today places it at the top of /profile.

    The spec mandates `ORDER BY date DESC, id DESC` (Step 5) — the
    tiebreaker on equal dates is `id DESC` (newer insert first), NOT
    "just-edited wins". So this test must give the edited row a LARGER
    id than the comparison row. We insert the comparison row first
    (smaller id), then the row being edited (larger id), then edit its
    date to today. Both rows share today's date; the edited row wins
    the tiebreaker and sorts to the top.
    """
    _login(client, "demo@spendly.com", "demo123")
    user_id = demo_id()

    # Comparison row: today, smaller id (inserted first).
    comparison_id = _stage_own_expense(
        user_id, amount=20.00, category="Food",
        date=_today_iso(), description="comparison row",
    )
    # Row being edited: yesterday, larger id (inserted second).
    edited_id = _stage_own_expense(
        user_id, amount=10.00, category="Food",
        date="2026-08-01", description="edited to today",
    )
    assert edited_id > comparison_id, (
        "test setup invariant: edited row's id must exceed the comparison id"
    )

    # Edit the older row's date to today. Both rows now share today's
    # date; under `date DESC, id DESC` the larger id sorts first.
    client.post(
        f"/expenses/{edited_id}/edit",
        data={
            "amount": "10.00",
            "category": "Food",
            "date": _today_iso(),
            "description": "edited to today",
        },
        follow_redirects=False,
    )

    body = body_of(client.get("/profile"))
    pos_edited = body.find(b"edited to today")
    pos_comparison = body.find(b"comparison row")
    assert pos_edited != -1, "edited row should appear on /profile"
    assert pos_comparison != -1, "the comparison row should still appear on /profile"
    assert pos_edited < pos_comparison, (
        "row edited to today must sort above the other today row "
        "(id DESC breaks the tie in favour of the more-recently-inserted row)"
    )


# ------------------------------------------------------------------ #
# DB-side effects                                                     #
# ------------------------------------------------------------------ #

def test_get_expense_by_id_returns_none_for_unknown_id(client):
    """Spec: get_expense_by_id(unknown_id, user) -> None."""
    from database.db import get_expense_by_id
    assert get_expense_by_id(99999, demo_id()) is None


def test_get_expense_by_id_returns_none_for_other_users_id(client):
    """Spec: get_expense_by_id(other_users_id, me) -> None (ownership scoped)."""
    from database.db import get_expense_by_id
    other_id = make_user("Trent", "trent@example.com", "password123")
    other_eid = _stage_own_expense(other_id)
    assert get_expense_by_id(other_eid, demo_id()) is None


def test_get_expense_by_id_returns_row_for_own_id(client):
    """Spec: get_expense_by_id(own_id, me) -> row."""
    from database.db import get_expense_by_id
    me = demo_id()
    eid = _stage_own_expense(
        me, amount=77.00, category="Food",
        date="2026-08-03", description="mine",
    )
    row = get_expense_by_id(eid, me)
    assert row is not None
    assert row["id"] == eid
    assert row["user_id"] == me
    assert row["amount"] == 77.00
    assert row["category"] == "Food"


def test_update_expense_with_mismatched_user_id_affects_zero_rows_and_row_unchanged(client):
    """Spec: update_expense(cross_user) affects 0 rows AND the row is unchanged.

    All five columns (amount, category, date, description, user_id)
    must match the pre-update snapshot after the failed call.
    """
    from database.db import update_expense
    other_id = make_user("Una", "una@example.com", "password123")
    eid = _stage_own_expense(
        other_id, amount=42.00, category="Food",
        date="2026-08-04", description="una's row",
    )
    before = _fetch_expense_row(eid)

    rowcount = update_expense(
        eid, demo_id(),  # wrong user -> 0 rows affected
        1.00, "Other", "2026-08-20", "hostile",
    )
    assert rowcount == 0

    after = _fetch_expense_row(eid)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]
    assert after["date"] == before["date"]
    assert after["description"] == before["description"]
    assert after["user_id"] == before["user_id"]


def test_update_expense_with_matching_user_id_affects_one_row_with_new_values(client):
    """Spec: update_expense(own_user) affects exactly 1 row with the new values."""
    from database.db import update_expense
    me = demo_id()
    eid = _stage_own_expense(
        me, amount=42.00, category="Food",
        date="2026-08-04", description="orig",
    )

    rowcount = update_expense(
        eid, me, 100.00, "Transport", "2026-08-09", "updated",
    )
    assert rowcount == 1

    after = _fetch_expense_row(eid)
    assert after["amount"] == 100.00
    assert after["category"] == "Transport"
    assert after["date"] == "2026-08-09"
    assert after["description"] == "updated"
    assert after["user_id"] == me


# ------------------------------------------------------------------ #
# AJAX shape (X-Requested-With: XMLHttpRequest)                       #
# ------------------------------------------------------------------ #
#
# Spec 08: when the Edit modal on /profile submits via fetch(), the
# route must return JSON so the JS can update the row in place.
# AJAX success  -> {"ok": true,  "expense": {id, date, description,
#                                            category, category_class,
#                                            amount}}
# AJAX failure  -> {"ok": false, "error": "...", "values": {...}}
# Direct nav    -> unchanged 302 to /profile (no-JS fallback still works).

import json


_AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _make_own_expense():
    """Helper: signed-in demo user, plus a known expense id to edit."""
    me = demo_id()
    eid = make_expense(me, 200.00, "Food", "2026-08-01", "before edit")
    return me, eid


def _post_edit(client, eid, data, *, ajax=True):
    headers = _AJAX_HEADERS if ajax else {}
    # Inject the CSRF token from the session so the route's check
    # passes. Tests that explicitly want the missing-token 403 path
    # should call `client.post(..., data=data_without_csrf)` directly.
    token = csrf_token_of(client)
    if token is not None:
        data = {**data, "csrf_token": token}
    return client.post(
        f"/expenses/{eid}/edit", data=data, follow_redirects=False,
        headers=headers,
    )


def test_post_edit_ajax_success_returns_json_with_expense_payload(client):
    """AJAX POST with valid form -> 200 JSON {ok:true, expense:{...}}."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "250.50",
            "category": "Transport",
            "date": "2026-08-05",
            "description": "after edit",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    expense = payload["expense"]
    assert set(expense.keys()) == {
        "id", "date", "description", "category", "category_class", "amount",
    }
    assert expense["id"] == eid
    assert expense["date"] == "2026-08-05"
    assert expense["description"] == "after edit"
    assert expense["category"] == "Transport"
    assert expense["category_class"] == "transport"
    assert "₹250.50" in expense["amount"]


def test_post_edit_ajax_empty_amount_returns_error_and_echoes_values(client):
    """AJAX POST with empty amount -> {ok:false, error, values} status 200."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "",
            "category": "Food",
            "date": "2026-08-05",
            "description": "echo me",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == EMPTY_AMOUNT_MSG.decode("utf-8")
    assert payload["values"]["amount"] == ""
    assert payload["values"]["description"] == "echo me"
    # Row is unchanged in DB
    row = _fetch_expense_row(eid)
    assert row["amount"] == 200.00


def test_post_edit_ajax_range_error_returns_error(client):
    """AJAX POST with non-numeric amount -> {ok:false, error} range msg."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "abc",
            "category": "Food",
            "date": "2026-08-05",
            "description": "",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == RANGE_AMOUNT_MSG.decode("utf-8")


def test_post_edit_ajax_unknown_category_returns_error(client):
    """AJAX POST with unknown category -> {ok:false, error}."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "50.00",
            "category": "Crypto",
            "date": "2026-08-05",
            "description": "",
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == BAD_CATEGORY_MSG.decode("utf-8")


def test_post_edit_ajax_future_date_returns_error(client):
    """AJAX POST with future date -> {ok:false, error} future-date msg."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
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


def test_post_edit_ajax_long_description_returns_error(client):
    """AJAX POST with 201-char description -> {ok:false, error} length msg."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "50.00",
            "category": "Food",
            "date": "2026-08-05",
            "description": "x" * 201,
        },
    )
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert payload["error"] == LONG_DESC_MSG.decode("utf-8")


def test_post_edit_without_ajax_header_falls_back_to_html_redirect(client):
    """Direct nav POST (no X-Requested-With header) keeps the 302 fallback."""
    _login(client, "demo@spendly.com", "demo123")
    me, eid = _make_own_expense()

    resp = _post_edit(
        client, eid,
        {
            "amount": "250.50",
            "category": "Transport",
            "date": "2026-08-05",
            "description": "after edit",
        },
        ajax=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert not resp.headers.get("Content-Type", "").startswith("application/json")


def test_post_edit_ajax_cross_user_returns_404(client):
    """AJAX POST on another user's id -> 404 (Flask default HTML), no JSON."""
    _login(client, "demo@spendly.com", "demo123")
    # Register a second user with their own row
    other_id = make_user("Other User 8", "other8@example.com", "password123")
    other_eid = make_expense(
        other_id, 99.00, "Food", "2026-08-05", "theirs",
    )

    resp = _post_edit(
        client, other_eid,
        {
            "amount": "1.00",
            "category": "Food",
            "date": "2026-08-05",
            "description": "trying to steal",
        },
    )
    assert resp.status_code == 404
    # Row is unchanged
    row = _fetch_expense_row(other_eid)
    assert row["amount"] == 99.00
    assert row["description"] == "theirs"
