"""Tests for the two new defences the unified code review surfaced:

  * CSRF tokens on every state-changing POST (security review CSRF-001).
    Verified end-to-end: signed-out → 302 to /login, missing token →
    403, wrong token → 403, correct token → success. Both the AJAX
    branch (returns JSON 403) and the direct-nav branch (returns HTML
    403 via Flask default) are checked.

  * Total Spent + Transactions in the AJAX success envelope
    (quality review Q-1, "grand-total drift"). Verified for Add,
    Edit, and Delete: payload["total"] matches the formatted rupee
    string, payload["count"] is an int, and the post-delete total
    decreases by the deleted row's amount.

These tests live in a single file because they share fixtures (the
auto-CSRF client wrapper in conftest.py disables itself when the test
explicitly wants the missing-token 403 path — see _post_without_csrf
below for the trick).
"""

import json

from tests.conftest import (
    _db,
    _login,
    csrf_token_of,
    demo_id,
    make_expense,
)


# ------------------------------------------------------------------ #
# Local helpers                                                       #
# ------------------------------------------------------------------ #

_AJAX = {"X-Requested-With": "XMLHttpRequest"}

# A present-but-incorrect csrf_token. The auto-CSRF wrapper in
# conftest.py only injects when "csrf_token" is NOT in the caller's
# data — sending this sentinel overrides the wrapper so the route's
# `_verify_csrf` sees the bogus token and returns 403. Both the
# missing-token and wrong-token tests use the same helper because
# the route treats empty-session-token and mismatched-token
# identically: 403.
_BAD_TOKEN = "not-the-real-csrf-token"


def _post_without_csrf(client, url, *, ajax=False):
    """POST with a csrf_token the route will reject -> 403.

    The auto-CSRF wrapper sees the key is already present in `data` and
    skips injection, so the bogus value reaches the route unchanged.
    """
    headers = _AJAX if ajax else {}
    return client.post(
        url, data={"csrf_token": _BAD_TOKEN},
        headers=headers, follow_redirects=False,
    )


_post_with_wrong_csrf = _post_without_csrf  # alias for readability


def _stage_own_expense(user_id, amount=450.00, category="Food",
                       date="2026-08-15", description="seed"):
    """Insert one expense row directly and return its id."""
    return make_expense(user_id, amount, category, date, description)


def _fetch_row(eid):
    """Return the row for `eid` regardless of owner, or None."""
    conn = _db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (eid,)
        ).fetchone()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Session stamping                                                    #
# ------------------------------------------------------------------ #

def test_login_stamps_csrf_token(client):
    """Spec: login stamps a fresh CSRF token in the session."""
    _login(client, "demo@spendly.com", "demo123")
    token = csrf_token_of(client)
    assert isinstance(token, str)
    assert len(token) >= 32


def test_register_stamps_csrf_token(client):
    """Spec: register stamps a fresh CSRF token in the session."""
    resp = client.post(
        "/register",
        data={
            "name": "CSRF Test",
            "email": "csrf-test@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/profile" in resp.headers["Location"]
    token = csrf_token_of(client)
    assert isinstance(token, str)
    assert len(token) >= 32


def test_session_token_changes_across_logins(client):
    """Two logins in a row yield two distinct tokens (rotation works)."""
    _login(client, "demo@spendly.com", "demo123")
    t1 = csrf_token_of(client)

    client.get("/logout", follow_redirects=False)
    _login(client, "demo@spendly.com", "demo123")
    t2 = csrf_token_of(client)

    assert t1 != t2


# ------------------------------------------------------------------ #
# CSRF — Add                                                          #
# ------------------------------------------------------------------ #

def test_add_post_without_csrf_returns_403(client):
    """POST to /expenses/add without csrf_token -> 403, no row inserted."""
    _login(client, "demo@spendly.com", "demo123")
    before = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]

    resp = _post_without_csrf(client, "/expenses/add")

    assert resp.status_code == 403
    after = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]
    assert after == before, "no row should have been inserted"


def test_add_post_with_wrong_csrf_returns_403(client):
    """POST with csrf_token set to garbage -> 403, no row inserted."""
    _login(client, "demo@spendly.com", "demo123")
    before = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]

    resp = _post_with_wrong_csrf(client, "/expenses/add")

    assert resp.status_code == 403
    after = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]
    assert after == before


# ------------------------------------------------------------------ #
# CSRF — Edit                                                         #
# ------------------------------------------------------------------ #

def test_edit_post_without_csrf_returns_403(client):
    """POST to /expenses/<id>/edit without csrf_token -> 403, row unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=100.00, category="Food")
    before = _fetch_row(eid)

    resp = _post_without_csrf(client, f"/expenses/{eid}/edit")

    assert resp.status_code == 403
    after = _fetch_row(eid)
    assert after["amount"] == before["amount"]
    assert after["category"] == before["category"]


def test_edit_post_with_wrong_csrf_returns_403(client):
    """POST to /expenses/<id>/edit with wrong token -> 403."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=100.00, category="Food")
    before = _fetch_row(eid)

    resp = _post_with_wrong_csrf(client, f"/expenses/{eid}/edit")

    assert resp.status_code == 403
    after = _fetch_row(eid)
    assert after["amount"] == before["amount"]


# ------------------------------------------------------------------ #
# CSRF — Delete                                                       #
# ------------------------------------------------------------------ #

def test_delete_post_without_csrf_returns_403(client):
    """POST to /expenses/<id>/delete without csrf_token -> 403, row kept."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=100.00, category="Food")
    assert _fetch_row(eid) is not None, "pre-condition: row must exist"

    resp = _post_without_csrf(client, f"/expenses/{eid}/delete")

    assert resp.status_code == 403
    assert _fetch_row(eid) is not None, "row must still exist after 403"


def test_delete_post_with_wrong_csrf_returns_403(client):
    """POST to /expenses/<id>/delete with wrong token -> 403, row kept."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=100.00, category="Food")
    assert _fetch_row(eid) is not None

    resp = _post_with_wrong_csrf(client, f"/expenses/{eid}/delete")

    assert resp.status_code == 403
    assert _fetch_row(eid) is not None


# ------------------------------------------------------------------ #
# CSRF — response shape (AJAX vs direct nav)                          #
# ------------------------------------------------------------------ #

def test_csrf_ajax_403_is_json(client):
    """AJAX POST (X-Requested-With) with missing token -> JSON 403."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_without_csrf(client, "/expenses/add", ajax=True)

    assert resp.status_code == 403
    assert resp.headers["Content-Type"].startswith("application/json")
    payload = json.loads(resp.data)
    assert payload["ok"] is False
    assert "token" in payload["error"].lower()


def test_csrf_direct_nav_403_is_html(client):
    """Direct-nav POST (no header) with missing token -> HTML 403 (Flask default)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_without_csrf(client, "/expenses/add", ajax=False)

    assert resp.status_code == 403
    assert not resp.headers.get("Content-Type", "").startswith("application/json")


# ------------------------------------------------------------------ #
# Signed-out POSTs still 302 (CSRF check does not shadow the auth guard) #
# ------------------------------------------------------------------ #

def test_signed_out_post_add_redirects_to_login_not_403(client):
    """Auth check runs BEFORE CSRF — signed-out POSTs keep 302 to /login."""
    resp = client.post(
        "/expenses/add",
        data={"amount": "10", "category": "Food", "date": "2026-08-15"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_out_post_edit_redirects_to_login_not_403(client):
    """Same ordering for edit."""
    resp = client.post(
        "/expenses/1/edit",
        data={"amount": "10"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_signed_out_post_delete_redirects_to_login_not_403(client):
    """Same ordering for delete."""
    resp = client.post(
        "/expenses/1/delete",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ #
# JSON envelope — total + count on every success path                #
# ------------------------------------------------------------------ #

def _ajax_post_add(client, data):
    return client.post(
        "/expenses/add",
        data={**data, "csrf_token": csrf_token_of(client)},
        headers=_AJAX,
        follow_redirects=False,
    )


def _ajax_post_edit(client, eid, data):
    return client.post(
        f"/expenses/{eid}/edit",
        data={**data, "csrf_token": csrf_token_of(client)},
        headers=_AJAX,
        follow_redirects=False,
    )


def _ajax_post_delete(client, eid):
    return client.post(
        f"/expenses/{eid}/delete",
        data={"csrf_token": csrf_token_of(client)},
        headers=_AJAX,
        follow_redirects=False,
    )


def test_add_envelope_contains_total_and_count(client):
    """AJAX Add success envelope carries `total` (₹-formatted) and `count` (int)."""
    _login(client, "demo@spendly.com", "demo123")
    # Pre-existing seeded rows already exist for the demo user.
    before_count = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]
    before_total = _db.get_db().execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["s"]

    resp = _ajax_post_add(client, {
        "amount": "123.45",
        "category": "Food",
        "date": "2026-08-17",
        "description": "envelope test",
    })

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    assert payload["total"] == f"₹{before_total + 123.45:,.2f}"
    assert payload["count"] == before_count + 1


def test_edit_envelope_contains_total_and_count(client):
    """AJAX Edit success envelope carries total + count; count unchanged."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=100.00, category="Food")

    before_count = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]
    before_total = _db.get_db().execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["s"]

    resp = _ajax_post_edit(client, eid, {
        "amount": "500.00",
        "category": "Transport",
        "date": "2026-08-17",
        "description": "edited",
    })

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    # Total = (before_total - 100 + 500)
    expected_total = before_total - 100.00 + 500.00
    assert payload["total"] == f"₹{expected_total:,.2f}"
    assert payload["count"] == before_count, "count should not change on Edit"


def test_delete_envelope_contains_total_and_count(client):
    """AJAX Delete success envelope carries total + count."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=250.00, category="Food")

    before_count = _db.get_db().execute(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["n"]
    before_total = _db.get_db().execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["s"]

    resp = _ajax_post_delete(client, eid)

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    assert payload["id"] == eid
    # Total drops by the deleted row's amount; count drops by 1.
    assert payload["total"] == f"₹{before_total - 250.00:,.2f}"
    assert payload["count"] == before_count - 1


def test_delete_envelope_total_decreases_by_amount(client):
    """Snapshot test: post-delete total = pre-delete total - deleted amount."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id(), amount=777.77, category="Bills")

    before_total = _db.get_db().execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM expenses WHERE user_id = ?",
        (demo_id(),),
    ).fetchone()["s"]

    resp = _ajax_post_delete(client, eid)
    payload = json.loads(resp.data)

    assert payload["total"] == f"₹{before_total - 777.77:,.2f}"


# ------------------------------------------------------------------ #
# Filter-aware envelope (T-1)                                         #
# ------------------------------------------------------------------ #
# Spec 09 §"Success / failure JSON shapes": the envelope's total/count
# reflect the page's current date filter, carried via hidden `from` /
# `to` form inputs. Without these tests, a regression that ignores the
# inputs would silently let unfiltered totals leak onto filtered pages.

def test_delete_ajax_with_from_to_filter_returns_filtered_envelope(client):
    """Hidden from/to on the modal constrain the envelope's stats to the
    filtered window — NOT the unfiltered DB total.

    Snapshot the filtered count + total before deleting; after deletion
    both should drop by exactly one row's worth. This locks the contract
    that the encoded window is honoured server-side.
    """
    _login(client, "demo@spendly.com", "demo123")
    # Stage a row inside the [2026-05-01, 2026-08-31] window.
    inside_id = make_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-06-01", description="in-window",
    )

    # Snapshot the filtered totals directly via SQL — same source of
    # truth as `_stats_payload`.
    conn = _db.get_db()
    try:
        before = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s, COUNT(*) AS n "
            "FROM expenses WHERE user_id = ? "
            "AND date BETWEEN ? AND ?",
            (demo_id(), "2026-05-01", "2026-08-31"),
        ).fetchone()
    finally:
        conn.close()

    token = csrf_token_of(client)
    resp = client.post(
        f"/expenses/{inside_id}/delete",
        data={
            "csrf_token": token,
            "from": "2026-05-01",
            "to": "2026-08-31",
        },
        headers=_AJAX,
        follow_redirects=False,
    )

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    # The envelope's filtered stats must reflect the post-delete state:
    # count drops by 1, total drops by the deleted amount.
    assert payload["count"] == before["n"] - 1
    assert payload["total"] == f"₹{before['s'] - 100.00:,.2f}"


def test_delete_ajax_with_malformed_from_falls_back_to_unfiltered(client):
    """A non-ISO `from` / `to` is dropped — envelope reflects the
    unfiltered window. Spec: 'Bad inputs fall back to no bounds rather
    than than returning an error envelope.'"""
    _login(client, "demo@spendly.com", "demo123")
    eid = make_expense(
        demo_id(), amount=50.00, category="Food",
        date="2026-08-15", description="seed",
    )

    # Snapshot the unfiltered totals.
    conn = _db.get_db()
    try:
        before = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s, COUNT(*) AS n "
            "FROM expenses WHERE user_id = ?",
            (demo_id(),),
        ).fetchone()
    finally:
        conn.close()

    token = csrf_token_of(client)
    resp = client.post(
        f"/expenses/{eid}/delete",
        data={
            "csrf_token": token,
            "from": "not-a-date",
            "to": "garbage",
        },
        headers=_AJAX,
        follow_redirects=False,
    )

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    # Both fields must be present (the envelope always carries them).
    assert "total" in payload
    assert "count" in payload
    # The malformed bounds were dropped — the envelope is unfiltered.
    assert payload["count"] == before["n"] - 1
    assert payload["total"] == f"₹{before['s'] - 50.00:,.2f}"