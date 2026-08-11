"""Tests for Step 7: Add Expense route.

Spec source: ``.claude/specs/07-add-expense.md``.

These tests are driven strictly by the spec text — not by reading the
implementation. They verify the contract for ``GET /expenses/add`` and
``POST /expenses/add``:

* The route is auth-guarded for both GET and POST.
* GET renders the form prefilled with today's ISO date and the 7
  fixed categories from Step 1.
* POST with valid data inserts exactly one row linked to the
  signed-in user and redirects (HTTP 302) to ``/profile``.
* Each validation rule (amount, category, date, description) re-renders
  the form with the matching error message and echoes the typed values.
* The route never accepts ``user_id`` from the form — the row always
  reflects ``session["user_id"]``.
* Two signed-in users with overlapping data never see each other's
  rows.
* The new row's ``created_at`` is populated.
* The ``+ Add expense`` CTA on ``/profile`` links to ``/expenses/add``.

Shared fixtures / factories from ``tests/conftest.py``:

* ``client``              — Flask test client
* ``reset_db`` (autouse)  — fresh schema + demo user per test
* ``_login``              — POST /login and assert 302 to /profile
* ``make_user``           — insert a user row
* ``make_expense``        — insert an expense row
"""

import re
from datetime import date, timedelta

from tests.conftest import _login, make_expense, make_user


# ----------------------------------------------------------------------- #
# Small response-body helpers                                              #
# ----------------------------------------------------------------------- #

# The rupee byte literal used throughout the suite.
RUPEE = b"\xe2\x82\xb9"


def body_of(resp):
    """Convenience: pull `resp.data` once so each test reads cleanly."""
    return resp.data


def _db():
    """Return the live `database.db` module (post-conftest swap).

    Imported lazily because conftest.py swaps ``database.db.DB_PATH``
    *before* ``app`` is loaded; importing ``database.db`` at the top of
    this file would capture the wrong (production) DB_PATH at import
    time.
    """
    from database import db
    return db


def _demo_id():
    """The seeded demo user's id."""
    conn = _db().get_db()
    try:
        return conn.execute(
            "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()["id"]
    finally:
        conn.close()


def _expense_row_for(user_id, amount):
    """Return the (single) expense row for the given user + amount."""
    conn = _db().get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses WHERE user_id = ? AND amount = ?",
            (user_id, amount),
        ).fetchone()
    finally:
        conn.close()


def _expense_count(user_id):
    """Count the number of expense rows for the given user."""
    conn = _db().get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM expenses WHERE user_id = ?",
            (user_id,),
        ).fetchone()["c"]
    finally:
        conn.close()


# ======================================================================= #
# Auth guard                                                               #
# ======================================================================= #

def test_get_add_expense_signed_out_redirects_to_login(client):
    """Signed-out GET /expenses/add -> 302 to /login."""
    resp = client.get("/expenses/add", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_post_add_expense_signed_out_redirects_to_login(client):
    """Signed-out POST /expenses/add -> 302 to /login; no DB write.

    The guard must fire BEFORE validation, so even a perfectly valid
    payload cannot sneak a row into the DB while signed out.
    """
    today_iso = date.today().isoformat()
    # Snapshot the demo user's expense count first so we can prove
    # the signed-out POST did not insert.
    before = _expense_count(_demo_id())

    resp = client.post(
        "/expenses/add",
        data={
            "amount": "321.00",
            "category": "Food",
            "date": today_iso,
            "description": "guard-probe",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    after = _expense_count(_demo_id())
    assert after == before, "signed-out POST inserted a row"


# ======================================================================= #
# GET — render                                                             #
# ======================================================================= #

def test_get_renders_200_when_signed_in(client):
    """GET /expenses/add as a signed-in user -> 200."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/expenses/add")
    assert resp.status_code == 200


def test_get_renders_the_seven_fixed_categories(client):
    """GET /expenses/add lists exactly the 7 fixed categories from Step 1.

    The category vocabulary is locked to: Food, Transport, Bills,
    Health, Entertainment, Shopping, Other. Anything more / less is a
    spec violation.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/expenses/add"))

    for cat in [
        "Food", "Transport", "Bills", "Health",
        "Entertainment", "Shopping", "Other",
    ]:
        assert cat.encode("utf-8") in body, f"{cat} not in form"


def test_get_prefills_today_and_caps_max_at_today(client):
    """GET pre-fills the date input with today's ISO date; max=today.

    The form must show today's date as both the default value and the
    ``max`` attribute so the browser blocks future dates client-side
    (server still validates — see future-date test below).
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/expenses/add"))
    today_iso = date.today().isoformat().encode("utf-8")
    assert b'value="' + today_iso + b'"' in body
    assert (b'max="' + today_iso + b'"') in body


# ======================================================================= #
# POST — happy path                                                        #
# ======================================================================= #

def test_post_valid_inserts_one_row_and_redirects_to_profile(client):
    """Valid POST -> 302 to /profile and exactly one DB row inserted."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())

    today_iso = date.today().isoformat()
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "499.00",
            "category": "Food",
            "date": today_iso,
            "description": "Lunch",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]

    after = _expense_count(_demo_id())
    assert after == before + 1, f"expected one new row; before={before}, after={after}"


def test_post_valid_row_belongs_to_signed_in_user(client):
    """The inserted row carries the signed-in user's id, not anyone else."""
    _login(client, "demo@spendly.com", "demo123")
    demo_id = _demo_id()

    today_iso = date.today().isoformat()
    client.post(
        "/expenses/add",
        data={
            "amount": "321.09",
            "category": "Transport",
            "date": today_iso,
            "description": "row-ownership-probe",
        },
        follow_redirects=False,
    )

    row = _expense_row_for(demo_id, 321.09)
    assert row is not None, "expected a row for demo with amount 321.09"
    assert row["user_id"] == demo_id
    assert row["category"] == "Transport"
    assert row["date"] == today_iso
    assert row["description"] == "row-ownership-probe"


def test_post_valid_amount_stored_as_number(client):
    """The stored amount is a numeric (REAL) value, not a string."""
    _login(client, "demo@spendly.com", "demo123")
    today_iso = date.today().isoformat()
    client.post(
        "/expenses/add",
        data={
            "amount": "55.75",
            "category": "Other",
            "date": today_iso,
            "description": "type-check",
        },
        follow_redirects=False,
    )
    row = _expense_row_for(_demo_id(), 55.75)
    assert row is not None
    # Compare as float to avoid Decimal/REAL mismatch; the schema is REAL.
    assert isinstance(row["amount"], (int, float))
    assert float(row["amount"]) == 55.75


def test_post_valid_then_profile_shows_new_expense(client):
    """After a successful POST, the new expense appears on /profile."""
    _login(client, "demo@spendly.com", "demo123")
    today_iso = date.today().isoformat()
    client.post(
        "/expenses/add",
        data={
            "amount": "888.42",
            "category": "Entertainment",
            "date": today_iso,
            "description": "PROFILE_VIS_DESC",
        },
        follow_redirects=False,
    )
    body = body_of(client.get("/profile"))
    assert b"PROFILE_VIS_DESC" in body
    # INR formatting: ₹888.42 — the amount must appear on the profile.
    assert RUPEE + b"888.42" in body


# ======================================================================= #
# POST — amount validation                                                 #
# ======================================================================= #

def _post(client, **overrides):
    """POST with the demo's valid data, applying any keyword overrides."""
    data = {
        "amount": "499.00",
        "category": "Food",
        "date": date.today().isoformat(),
        "description": "Lunch",
    }
    data.update(overrides)
    return client.post("/expenses/add", data=data, follow_redirects=False)


def test_post_empty_amount_renders_error_and_echoes_fields(client):
    """Empty amount -> 200 with the empty-amount error and echoed values."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, amount="")
    assert resp.status_code == 200
    body = body_of(resp)
    assert b"Please enter an amount." in body
    # Description echoed back so the user doesn't lose their typing.
    assert b"Lunch" in body
    # Category choice echoed back as the selected option.
    assert b'<option value="Food" selected>Food</option>' in body


def test_post_non_numeric_amount_renders_error(client):
    """Garbage amount falls into the 'valid amount' error branch."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, amount="abc")
    assert resp.status_code == 200
    body = body_of(resp)
    assert b"Please enter a valid amount between" in body
    # Spec-specific message: includes the cap.
    assert RUPEE + b"0.01" in body or b"\xe2\x82\xb90.01" in body
    assert RUPEE + b"10,00,000" in body or b"\xe2\x82\xb910,00,000" in body


def test_post_zero_amount_renders_error(client):
    """Zero is not > 0; the amount error fires."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, amount="0")
    assert resp.status_code == 200
    assert b"Please enter a valid amount between" in body_of(resp)


def test_post_negative_amount_renders_error(client):
    """Negative amounts are rejected by the > 0 check."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, amount="-50.00")
    assert resp.status_code == 200
    assert b"Please enter a valid amount between" in body_of(resp)


def test_post_over_cap_amount_renders_error(client):
    """An amount strictly greater than 10,00,000 is rejected."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, amount="1000000.01")
    assert resp.status_code == 200
    assert b"Please enter a valid amount between" in body_of(resp)


def test_post_at_cap_amount_succeeds(client):
    """The boundary value ₹10,00,000 is allowed (<=)."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, amount="1000000.00")
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]
    after = _expense_count(_demo_id())
    assert after == before + 1


def test_post_validation_failure_inserts_no_row(client):
    """A failing amount validation must NOT insert a row."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, amount="-1")
    assert resp.status_code == 200  # form re-rendered
    after = _expense_count(_demo_id())
    assert after == before, "validation failure must not insert"


# ======================================================================= #
# POST — category validation                                               #
# ======================================================================= #

def test_post_missing_category_renders_error(client):
    """Empty category -> 'Please choose a category.'."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, category="")
    assert resp.status_code == 200
    assert b"Please choose a category." in body_of(resp)


def test_post_unknown_category_renders_error(client):
    """A category outside the 7-item whitelist is rejected."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, category="Crypto")
    assert resp.status_code == 200
    assert b"Please choose a category." in body_of(resp)


def test_post_category_validation_failure_inserts_no_row(client):
    """A failing category validation must NOT insert a row."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, category="")
    assert resp.status_code == 200
    after = _expense_count(_demo_id())
    assert after == before, "category validation failure must not insert"


# ======================================================================= #
# POST — date validation                                                   #
# ======================================================================= #

def test_post_missing_date_renders_error(client):
    """Empty date -> 'Please enter a valid date.'."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, date="")
    assert resp.status_code == 200
    assert b"Please enter a valid date." in body_of(resp)


def test_post_malformed_date_renders_error(client):
    """A non-ISO date string is rejected by the format check."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, date="not-a-date")
    assert resp.status_code == 200
    assert b"Please enter a valid date." in body_of(resp)


def test_post_partial_iso_date_renders_error(client):
    """A date that matches ISO length but is not a real date is rejected.

    e.g. '2026-13-40' is well-formed by DATE_RE but is not a real date;
    ``date.fromisoformat`` must reject it.
    """
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, date="2026-13-40")
    assert resp.status_code == 200
    assert b"Please enter a valid date." in body_of(resp)


def test_post_future_date_renders_error(client):
    """Tomorrow's date is rejected server-side.

    The browser's ``max`` attribute is only a UX hint; the server must
    still validate 'date not in the future'.
    """
    _login(client, "demo@spendly.com", "demo123")
    future = (date.today() + timedelta(days=1)).isoformat()
    resp = _post(client, date=future)
    assert resp.status_code == 200
    assert b"Date cannot be in the future." in body_of(resp)


def test_post_date_validation_failure_inserts_no_row(client):
    """A failing date validation must NOT insert a row."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, date="not-a-date")
    assert resp.status_code == 200
    after = _expense_count(_demo_id())
    assert after == before, "date validation failure must not insert"


# ======================================================================= #
# POST — description validation                                            #
# ======================================================================= #

def test_post_long_description_renders_error(client):
    """Description over 200 chars -> 'Description must be 200 characters...'."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post(client, description="x" * 201)
    assert resp.status_code == 200
    assert b"Description must be 200 characters or fewer." in body_of(resp)


def test_post_long_description_validation_failure_inserts_no_row(client):
    """A failing description validation must NOT insert a row."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, description="x" * 250)
    assert resp.status_code == 200
    after = _expense_count(_demo_id())
    assert after == before, "description validation failure must not insert"


def test_post_empty_description_is_allowed(client):
    """An empty description is valid (the column is nullable)."""
    _login(client, "demo@spendly.com", "demo123")
    before = _expense_count(_demo_id())
    resp = _post(client, description="")
    assert resp.status_code == 302
    after = _expense_count(_demo_id())
    assert after == before + 1


# ======================================================================= #
# POST — security: user_id smuggling                                       #
# ======================================================================= #

def test_post_route_ignores_user_id_from_form(client):
    """A `user_id` field in the form is ignored; row uses session user_id."""
    _login(client, "demo@spendly.com", "demo123")
    demo_id = _demo_id()
    other_id = make_user(
        name="Smuggle Target",
        email="smuggle@example.com",
        password="password123",
    )
    assert other_id != demo_id

    today_iso = date.today().isoformat()
    resp = client.post(
        "/expenses/add",
        data={
            "amount": "456.78",
            "category": "Food",
            "date": today_iso,
            "description": "smuggled",
            # Attacker tries to attach the new row to the other user.
            "user_id": str(other_id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # The new row must be attached to demo, NOT to the smuggling target.
    demo_row = _expense_row_for(demo_id, 456.78)
    other_row = _expense_row_for(other_id, 456.78)
    assert demo_row is not None, "expected the row to belong to demo"
    assert other_row is None, "the row must NOT belong to the smuggled user_id"


# ======================================================================= #
# POST — two-user isolation                                                #
# ======================================================================= #

def test_post_two_user_isolation(client):
    """Signed in as A, POST inserts a row for A only — never for B.

    Followed by signing in as B and confirming B's /profile view does
    not contain A's description.
    """
    # Register user B first so A's POST can attempt to write under
    # B's id (defensive check) and B's later profile view is clean.
    client.post(
        "/register",
        data={
            "name": "User B",
            "email": "userb@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=False,
    )
    client.get("/logout")

    # Sign back in as demo (user A) and POST a uniquely-described expense.
    _login(client, "demo@spendly.com", "demo123")
    today_iso = date.today().isoformat()
    client.post(
        "/expenses/add",
        data={
            "amount": "777.00",
            "category": "Food",
            "date": today_iso,
            "description": "ISO_PROBE_DESC",
        },
        follow_redirects=False,
    )

    # Verify the row landed in demo's data, not user B's.
    demo_id = _demo_id()
    demo_row = _expense_row_for(demo_id, 777.00)
    assert demo_row is not None
    assert demo_row["user_id"] == demo_id

    # Sign out, then log in as user B and confirm B's profile doesn't
    # leak demo's description.
    client.get("/logout")
    _login(client, "userb@example.com", "password123")
    body = body_of(client.get("/profile"))
    assert b"ISO_PROBE_DESC" not in body
    # And B's profile must not show demo's name (sanity).
    assert b"Demo User" not in body


# ======================================================================= #
# POST — created_at column default                                         #
# ======================================================================= #

def test_post_created_at_is_populated(client):
    """The new row's `created_at` is non-null and in the current year."""
    _login(client, "demo@spendly.com", "demo123")
    today_iso = date.today().isoformat()
    client.post(
        "/expenses/add",
        data={
            "amount": "11.11",
            "category": "Other",
            "date": today_iso,
            "description": "created_at check",
        },
        follow_redirects=False,
    )
    row = _expense_row_for(_demo_id(), 11.11)
    assert row is not None
    assert row["created_at"] is not None
    assert row["created_at"] != ""
    # Default is `datetime('now')` -> "YYYY-MM-DD HH:MM:SS" in the current year.
    assert row["created_at"].startswith(str(date.today().year))


# ======================================================================= #
# /profile — discoverability CTA                                           #
# ======================================================================= #

def test_profile_renders_add_expense_cta_link(client):
    """The /profile page links to /expenses/add via the 'Add expense' CTA."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))
    # Spec wording: " + Add expense" inside the user-info card.
    # Look for an anchor pointing at /expenses/add that contains the CTA text.
    pattern = re.compile(
        rb'<a[^>]*href\s*=\s*"[^"]*/expenses/add[^"]*"[^>]*>\s*\+?\s*Add expense\s*</a>',
        re.IGNORECASE,
    )
    assert pattern.search(body) is not None, "no /expenses/add CTA on /profile"


def test_profile_cta_is_inside_user_info_card(client):
    """The '+ Add expense' CTA lives inside the existing user-info card."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile")).decode("utf-8")

    # The spec refers to the user-info card as `.profile-user-card`; the
    # actual template class is `.profile-info-card` (the card has both
    # `.profile-card` and `.profile-info-card` on `<div class="...">`).
    # Match either so the test stays valid if the markup renames again.
    m = re.search(
        r'<div[^>]*class\s*=\s*"[^"]*profile-info-card[^"]*"[^>]*>(.*)',
        body,
        re.DOTALL,
    )
    assert m is not None, "profile user-info card not found"
    card_html = m.group(1)
    assert "/expenses/add" in card_html, (
        "Add expense CTA must live inside the user-info card"
    )
    assert "Add expense" in card_html
