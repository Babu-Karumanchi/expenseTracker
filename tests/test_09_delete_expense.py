"""Step 9: Delete Expense — spec-driven tests for the Delete modal on /profile
plus the POST-only `/expenses/<id>/delete` endpoint that powers it.

Every test below is derived from `.claude/specs/09-delete-expense.md` and
verifies a single Definition-of-Done behaviour. We do NOT inspect
`app.py` / `database/db.py` to derive expected values — the spec is
the source of truth and the implementation is what we are verifying.

Coverage map (spec sections referenced in the docstring of each test):

  Auth boundary
    - signed-out POST -> 302 to /login, no row touched

  Ownership boundary
    - POST on unknown id           -> 404
    - POST on another user's id    -> 404 AND the row is unchanged
    - attacker-supplied `user_id`  -> ignored, original row preserved

  Delete modal on /profile
    - profile renders a delete-modal-<id> for every transaction row
    - each delete modal contains: a <form method="post" action=...> with
      a submit button, a Cancel button (data-close-modal), a summary
      line with the row's date / category / amount
    - the danger button carries data-close-modal-and-submit
    - the Delete trigger on the row carries data-open-modal=<id>

  Edit modal on /profile
    - profile renders an edit-modal-<id> for every transaction row
    - the Edit trigger on the row carries data-open-modal=<id>

  POST happy path (driven by the modal's form)
    - 302 to /profile, row deleted from DB, /profile reflects the
      decrement (one fewer transaction in the table)

  POST endpoint is POST-only
    - GET /expenses/<id>/delete -> 405 Method Not Allowed
    - GET /expenses/<other-user-id>/delete -> 405 (uniform error)
    - GET /expenses/99999/delete -> 405

  DB-side effects
    - delete_expense(other_user_id, me)        -> rowcount 0, row unchanged
    - delete_expense(own_id, me)               -> rowcount 1, row gone
    - delete_expense(unknown_id, any_user)     -> rowcount 0
"""

import re

from tests.conftest import (
    _db,
    _login,
    body_of,
    csrf_token_of,
    demo_id,
    make_user,
)


# ------------------------------------------------------------------ #
# DB helpers — local to this test file.                               #
# ------------------------------------------------------------------ #

def _stage_own_expense(user_id, amount=450.00, category="Food",
                       date="2026-08-15", description="Initial description"):
    """Insert one expense row directly and return its id."""
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

def test_signed_out_post_redirects_to_login_and_does_not_touch_row(client):
    """Spec: signed-out POST -> 302 to /login AND the row in the DB is untouched.

    The destructive verb is gated by the auth guard — a signed-out POST
    must not be enough to remove a row.
    """
    eid = _stage_own_expense(demo_id())
    before = _fetch_expense_row(eid)
    assert before is not None, "pre-condition: row must exist before the POST"

    resp = client.post(
        f"/expenses/{eid}/delete",
        data={},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    after = _fetch_expense_row(eid)
    assert after is not None, "row must still exist after a signed-out POST"
    assert after["id"] == before["id"]


# ------------------------------------------------------------------ #
# Ownership boundary                                                  #
# ------------------------------------------------------------------ #

def test_post_on_unknown_id_returns_404(client):
    """Spec: POST on an id that doesn't exist -> 404 (via abort, before DELETE)."""
    _login(client, "demo@spendly.com", "demo123")
    resp = client.post("/expenses/99999/delete", data={}, follow_redirects=False)
    assert resp.status_code == 404


def test_post_on_other_users_id_returns_404_and_does_not_delete_row(client):
    """Spec: POST on another user's id -> 404 AND the row is NOT deleted.

    This test verifies BOTH the status code AND that the row is still
    present in the DB after the failed call — not just the status code.
    """
    other_id = make_user("Eve", "eve@example.com", "password123")
    other_eid = _stage_own_expense(
        other_id, amount=1234.00, category="Shopping",
        date="2026-08-10", description="eve's spend",
    )

    _login(client, "demo@spendly.com", "demo123")
    resp = client.post(
        f"/expenses/{other_eid}/delete",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 404

    after = _fetch_expense_row(other_eid)
    assert after is not None, "row must still exist after a cross-user POST"
    assert after["id"] == other_eid
    assert after["user_id"] == other_id


def test_post_ignores_attacker_supplied_user_id_form_field(client):
    """Spec: an attacker-supplied `user_id` form field is ignored.

    The route never reads user_id from the form — it always uses
    session["user_id"]. So the POST must succeed against the session
    user's row, and no row may land for the fake id 999.
    """
    _login(client, "demo@spendly.com", "demo123")
    owner = demo_id()
    eid = _stage_own_expense(
        owner, amount=10.00, category="Food",
        date="2026-08-01", description="keep me",
    )

    resp = client.post(
        f"/expenses/{eid}/delete",
        data={"user_id": "999"},  # attacker-supplied — must be ignored
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    # The original row must have been deleted (legitimate delete succeeded
    # because the route used the session user_id, not the attacker value).
    assert _fetch_expense_row(eid) is None

    # No row exists for the fake user id 999.
    conn = _db.get_db()
    try:
        leaked = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (999,)
        ).fetchone()
    finally:
        conn.close()
    assert leaked is None


# ------------------------------------------------------------------ #
# POST happy path — what the Delete modal's form submits             #
# ------------------------------------------------------------------ #

def test_valid_post_deletes_row_and_redirects_to_profile(client):
    """Spec: POST deletes the row AND returns 302 to /profile.

    Verified via direct sqlite3 — the row must be gone after the POST.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=100.00, category="Food",
        date="2026-08-01", description="to be removed",
    )
    assert _fetch_expense_row(eid) is not None, "pre-condition: row must exist"

    resp = client.post(
        f"/expenses/{eid}/delete",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert _fetch_expense_row(eid) is None, "row must be gone after POST"


def test_valid_post_decrements_user_expense_count(client):
    """Spec: the user's expense count drops by exactly 1 after the delete.

    The seeded demo user has 8 rows; staging one extra and then deleting
    it must bring the count back to 8.
    """
    _login(client, "demo@spendly.com", "demo123")
    user = demo_id()
    before = _count_expenses(user)
    eid = _stage_own_expense(
        user, amount=10.00, category="Food",
        date="2026-08-15", description="extra",
    )
    assert _count_expenses(user) == before + 1, "pre-condition: row was added"

    client.post(f"/expenses/{eid}/delete", data={}, follow_redirects=False)

    assert _count_expenses(user) == before


def test_valid_post_does_not_touch_other_users_rows(client):
    """Spec: deleting row X does NOT delete any other user's rows."""
    _login(client, "demo@spendly.com", "demo123")
    other_id = make_user("Walter", "walter@example.com", "password123")
    other_eid = _stage_own_expense(
        other_id, amount=200.00, category="Other",
        date="2026-08-12", description="walter's row",
    )

    my_eid = _stage_own_expense(
        demo_id(), amount=300.00, category="Food",
        date="2026-08-13", description="my row",
    )

    client.post(f"/expenses/{my_eid}/delete", data={}, follow_redirects=False)

    assert _fetch_expense_row(my_eid) is None
    assert _fetch_expense_row(other_eid) is not None


def test_redirected_profile_reflects_deletion(client):
    """Spec: after the redirect, /profile shows one fewer transaction.

    Stage an extra row with a unique amount / description, delete it,
    then GET /profile and confirm the row's distinctive markers are
    gone from the rendered HTML.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=7777.77, category="Shopping",
        date="2026-08-20", description="UNIQUE_DELETE_TARGET",
    )

    client.post(f"/expenses/{eid}/delete", data={}, follow_redirects=False)

    body = body_of(client.get("/profile"))
    assert b"UNIQUE_DELETE_TARGET" not in body, "description should be gone"
    assert b"\xe2\x82\xb97,777.77" not in body, "amount should be gone"


# ------------------------------------------------------------------ #
# POST endpoint is POST-only                                           #
# ------------------------------------------------------------------ #

def test_get_on_existing_id_returns_405(client):
    """Spec: GET /expenses/<id>/delete -> 405 Method Not Allowed.

    The modal is the only UI gate — there is no GET resource to render
    on this URL anymore. A direct GET (e.g. address-bar paste) must
    return 405, not 200 and not 302.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    resp = client.get(f"/expenses/{eid}/delete", follow_redirects=False)
    assert resp.status_code == 405


def test_get_on_unknown_id_returns_405(client):
    """Spec: GET /expenses/99999/delete -> 405 (uniform error).

    A 405 (not 404) is correct here — the URL pattern is registered
    with the router (just not for GET), so Flask reports the method
    problem before the ownership check. The attacker gains no useful
    information either way.
    """
    _login(client, "demo@spendly.com", "demo123")
    resp = client.get("/expenses/99999/delete", follow_redirects=False)
    assert resp.status_code == 405


def test_get_on_other_users_id_returns_405(client):
    """Spec: GET /expenses/<other-user-id>/delete -> 405 (uniform error)."""
    _login(client, "demo@spendly.com", "demo123")
    other_id = make_user("Trent", "trent@example.com", "password123")
    other_eid = _stage_own_expense(other_id)
    resp = client.get(f"/expenses/{other_eid}/delete", follow_redirects=False)
    assert resp.status_code == 405


def test_signed_out_get_returns_405_not_login_redirect(client):
    """Spec: signed-out GET also returns 405, NOT 302 to /login.

    The route registers methods=["POST"], so a GET bypasses the auth
    guard entirely and Flask's router returns 405 directly. The auth
    guard only fires when the request actually reaches the view
    function (i.e. on POST).
    """
    eid = _stage_own_expense(demo_id())
    resp = client.get(f"/expenses/{eid}/delete", follow_redirects=False)
    assert resp.status_code == 405
    # And explicitly NOT 302 (the auth guard never fired).
    assert not (300 <= resp.status_code < 400)


# ------------------------------------------------------------------ #
# Delete modal markup on /profile                                     #
# ------------------------------------------------------------------ #

def test_profile_renders_delete_modal_for_every_transaction(client):
    """Spec: /profile renders a delete-modal-<id> for every transaction row.

    The seed has 8 expenses; we assert count parity between the row
    triggers and the modals so the seed can grow without breaking.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    triggers = re.findall(rb'data-open-modal="delete-modal-\d+"', body)
    modals = re.findall(rb'id="delete-modal-\d+"', body)
    assert len(triggers) == len(modals) >= 1, (
        f"expected at least one delete modal pair (trigger + modal div); "
        f"got {len(triggers)} triggers, {len(modals)} modal divs"
    )


def test_profile_delete_modal_contains_post_form_with_action(client):
    """Spec: each delete modal contains a <form method="post" action="/expenses/<id>/delete">."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # Find every delete modal block, then locate the form inside it.
    modals = re.findall(
        rb'<div\s+id="delete-modal-\d+"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modals, "expected at least one delete-modal block"

    for modal_html in modals:
        forms = re.findall(
            rb'<form\b[^>]*method=[\"\']post[\"\'][^>]*action=([\"\'])([^\"\'>]+)\1',
            modal_html,
        )
        assert forms, f"delete modal missing a POST form: {modal_html[:200]!r}"
        for _quote, action in forms:
            assert re.fullmatch(rb"/expenses/\d+/delete", action), (
                f"unexpected form action: {action!r}"
            )


def test_profile_delete_modal_contains_danger_submit_button(client):
    """Spec: each delete modal contains a danger submit button labelled 'Delete'."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # The danger button carries data-ajax-submit AND class btn-danger.
    submit_buttons = re.findall(
        rb'<button[^>]*data-ajax-submit[^>]*>',
        body,
    )
    assert submit_buttons, "expected at least one danger submit button with data-ajax-submit"

    for btn in submit_buttons:
        assert b"btn-danger" in btn, f"button missing btn-danger class: {btn!r}"
        # The button text appears between the open and close tags — find
        # the matching </button> and check the content.
        idx = body.find(btn)
        close_idx = body.find(b"</button>", idx)
        assert close_idx > 0
        text = body[idx + len(btn):close_idx].strip()
        assert text == b"Delete", f"danger button text must be 'Delete', got {text!r}"


def test_profile_delete_modal_contains_cancel_button(client):
    """Spec: each delete modal contains a Cancel button that closes the modal."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    # Pull all delete-modal blocks and assert each contains a Cancel
    # button that carries the data-close-modal attribute (NOT
    # data-ajax-submit, which would submit the form).
    modals = re.findall(
        rb'<div\s+id="delete-modal-\d+"[^>]*>(.*?)(?=<div\s+id="(?:delete|edit)-modal)',
        body,
        re.DOTALL,
    )
    assert modals, "expected at least one delete-modal block"

    for modal_html in modals:
        cancel_buttons = re.findall(
            rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>',
            modal_html,
        )
        assert cancel_buttons, f"delete modal missing Cancel button: {modal_html[:200]!r}"


def test_profile_delete_modal_summary_shows_row_data(client):
    """Spec: each delete modal's summary line shows the row's date / category / amount.

    The summary sits in a .modal-summary block between the body
    paragraph and the action row.
    """
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(
        demo_id(), amount=1850.00, category="Transport",
        date="2026-08-09", description="modal summary",
    )
    body = body_of(client.get("/profile"))

    # The summary for THIS row's modal must contain the date, the
    # category chip, and the formatted amount.
    modal_match = re.search(
        rb'<div\s+id="delete-modal-' + str(eid).encode() + rb'"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match, f"delete-modal-{eid} block not found"
    modal_html = modal_match.group(1)

    assert b">2026-08-09</span>" in modal_html, "date missing from modal summary"
    assert b"category-badge--transport" in modal_html, "category badge missing"
    assert b">Transport</span>" in modal_html, "category text missing"
    assert b"\xe2\x82\xb91,850.00" in modal_html, "formatted amount missing"


def test_profile_delete_modal_contains_hidden_csrf_from_to_inputs(client):
    """Each delete modal's <form> carries the three hidden inputs.

    Spec 09 §"Success / failure JSON shapes": the envelope's total/count
    reflect the page's current date filter, carried via hidden `from` /
    `to`. And CSRF: the modal posts a `csrf_token` hidden field. The
    existing markup test asserts the form's `method` and `action` but
    not the hidden inputs — this test locks the rest of the contract.
    """
    _login(client, "demo@spendly.com", "demo123")
    _stage_own_expense(demo_id())
    body = client.get("/profile").data

    # Every delete modal renders a <form class="modal-delete-form">.
    # Find ALL of them and assert each one carries the three hidden
    # inputs — the spec contract is per-modal, so a regression that
    # drops the inputs from even one modal would otherwise pass.
    delete_forms = re.findall(
        rb'<form[^>]*class="modal-delete-form"[^>]*>(.*?)</form>',
        body,
        re.DOTALL,
    )
    assert len(delete_forms) >= 1, "no delete modal form found in /profile"

    for form_html in delete_forms:
        assert re.search(
            rb'<input\s+type="hidden"\s+name="csrf_token"\s+value="[^"]+"',
            form_html,
        ), "csrf_token hidden input missing from a delete modal"
        assert re.search(
            rb'<input\s+type="hidden"\s+name="from"\s+value="[^"]*"',
            form_html,
        ), "from hidden input missing from a delete modal"
        assert re.search(
            rb'<input\s+type="hidden"\s+name="to"\s+value="[^"]*"',
            form_html,
        ), "to hidden input missing from a delete modal"


# ------------------------------------------------------------------ #
# Edit modal markup on /profile                                        #
# ------------------------------------------------------------------ #

def test_profile_renders_edit_modal_for_every_transaction(client):
    """Spec: /profile renders an edit-modal-<id> for every transaction row."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    triggers = re.findall(rb'data-open-modal="edit-modal-\d+"', body)
    modals = re.findall(rb'id="edit-modal-\d+"', body)
    assert len(triggers) == len(modals) >= 1, (
        f"expected at least one edit modal pair (trigger + modal div); "
        f"got {len(triggers)} triggers, {len(modals)} modal divs"
    )


def test_profile_edit_modal_contains_form_with_action(client):
    """Spec: each edit modal contains a real <form action=/expenses/<id>/edit data-ajax-form>."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())
    body = body_of(client.get("/profile"))

    modal_match = re.search(
        rb'<div\s+id="edit-modal-' + str(eid).encode() + rb'"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match, f"edit-modal-{eid} block not found"
    modal_html = modal_match.group(1)

    # Form posts to /expenses/<id>/edit and carries data-ajax-form.
    expected_action = b'/expenses/' + str(eid).encode() + b'/edit'
    assert re.search(
        rb'<form\b[^>]*action="' + re.escape(expected_action) + rb'"[^>]*data-ajax-form',
        modal_html,
    ), f"edit modal missing POST form with action={expected_action!r} and data-ajax-form"


def test_profile_edit_modal_contains_cancel_button(client):
    """Spec: each edit modal contains a Cancel button that closes the modal."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    cancel_buttons = re.findall(
        rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>\s*Cancel\s*</button>',
        body,
    )
    # 1 add modal + 8 edit modals + 8 delete modals = at least 17 Cancel
    # buttons (the seeded demo user has 8 expenses).
    assert len(cancel_buttons) >= 17, (
        f"expected at least 17 Cancel buttons (1 add + 8 edit + 8 delete), "
        f"got {len(cancel_buttons)}"
    )


# ------------------------------------------------------------------ #
# Profile structure sanity                                            #
# ------------------------------------------------------------------ #

def test_profile_renders_add_expense_modal_once(client):
    """Spec: /profile renders exactly one add-expense-modal (page-global)."""
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))
    modals = re.findall(rb'id="add-expense-modal"', body)
    triggers = re.findall(rb'data-open-modal="add-expense-modal"', body)
    assert len(modals) == 1, f"expected exactly 1 add-expense-modal, got {len(modals)}"
    assert len(triggers) == 1, f"expected exactly 1 add-expense-modal trigger, got {len(triggers)}"


def test_profile_add_expense_modal_contains_form_with_action(client):
    """Spec: the add-expense-modal contains a real POST <form data-ajax-form>
    targeting /expenses/add (no Continue link — the modal itself submits).
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    modal_match = re.search(
        rb'<div\s+id="add-expense-modal"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match, "add-expense-modal block not found"
    modal_html = modal_match.group(1)

    # Real POST form, marked for AJAX submission.
    form_match = re.search(
        rb'<form\b[^>]*action="/expenses/add"[^>]*data-ajax-form',
        modal_html,
    )
    assert form_match is not None, (
        "add-expense-modal missing POST form with action=/expenses/add and data-ajax-form"
    )

    # The old "Continue → /expenses/add" link must NOT be present anymore.
    assert b'href="/expenses/add"' not in modal_html, (
        "add-expense-modal still contains a Continue link to /expenses/add"
    )


def test_profile_add_expense_modal_contains_cancel_button(client):
    """Spec: the add-expense-modal contains a Cancel button (data-close-modal only)
    and the form carries data-ajax-form so JS handles the submit.
    """
    _login(client, "demo@spendly.com", "demo123")
    body = body_of(client.get("/profile"))

    modal_match = re.search(
        rb'<div\s+id="add-expense-modal"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert modal_match, "add-expense-modal block not found"
    modal_html = modal_match.group(1)

    # Cancel button carries data-close-modal (NOT data-ajax-submit).
    cancel = re.search(
        rb'<button[^>]*data-close-modal(?![a-z\-])[^>]*>\s*Cancel\s*</button>',
        modal_html,
    )
    assert cancel is not None, "add-expense-modal missing Cancel button"

    # The modal DOES carry a form (the new inline form behaviour).
    assert re.search(
        rb'<form\b[^>]*action="/expenses/add"[^>]*data-ajax-form',
        modal_html,
    ) is not None, "add-expense-modal must contain a <form data-ajax-form>"


# ------------------------------------------------------------------ #
# DB-side effects                                                     #
# ------------------------------------------------------------------ #

def test_delete_expense_with_mismatched_user_id_affects_zero_rows_and_row_unchanged(client):
    """Spec: delete_expense(cross_user) affects 0 rows AND the row is unchanged.

    The helper's `WHERE id = ? AND user_id = ?` clause must silently
    affect 0 rows when the user_id doesn't match.
    """
    from database.db import delete_expense

    other_id = make_user("Una", "una@example.com", "password123")
    eid = _stage_own_expense(
        other_id, amount=42.00, category="Food",
        date="2026-08-04", description="una's row",
    )

    rowcount = delete_expense(eid, demo_id())  # wrong user -> 0 rows
    assert rowcount == 0

    after = _fetch_expense_row(eid)
    assert after is not None, "row must still exist after a mismatched delete"
    assert after["id"] == eid
    assert after["user_id"] == other_id


def test_delete_expense_with_matching_user_id_affects_one_row_and_row_gone(client):
    """Spec: delete_expense(own_user) affects exactly 1 row AND the row is gone."""
    from database.db import delete_expense

    me = demo_id()
    eid = _stage_own_expense(
        me, amount=42.00, category="Food",
        date="2026-08-04", description="mine",
    )

    rowcount = delete_expense(eid, me)
    assert rowcount == 1

    after = _fetch_expense_row(eid)
    assert after is None, "row must be gone after a matching delete"


def test_delete_expense_with_unknown_id_affects_zero_rows(client):
    """Spec: delete_expense(unknown_id, any_user) -> rowcount 0, no error."""
    from database.db import delete_expense

    rowcount = delete_expense(99999, demo_id())
    assert rowcount == 0


# ------------------------------------------------------------------ #
# AJAX shape (X-Requested-With: XMLHttpRequest)                       #
# ------------------------------------------------------------------ #
#
# Spec 09: when the Delete modal on /profile submits via fetch(), the
# route must return JSON {ok: true, id: <int>} so the JS can remove the
# row + orphan modals in place.

import json


_AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _post_delete(client, eid, *, ajax=True):
    headers = _AJAX_HEADERS if ajax else {}
    # Inject the CSRF token from the session so the route's check
    # passes. Tests that explicitly want the missing-token 403 path
    # should call `client.post(..., data={})` directly.
    token = csrf_token_of(client)
    data = {"csrf_token": token} if token is not None else {}
    return client.post(
        f"/expenses/{eid}/delete", data=data, follow_redirects=False,
        headers=headers,
    )


def test_post_delete_ajax_success_returns_json_with_id(client):
    """AJAX POST on own row -> 200 JSON {ok:true, id:<int>} and row deleted."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())

    resp = _post_delete(client, eid)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/json")
    payload = json.loads(resp.data)
    # Subset assertions so the envelope can grow new fields (e.g.
    # `total` / `count`) without breaking this test.
    assert payload["ok"] is True
    assert payload["id"] == eid
    # Row really gone.
    assert _fetch_expense_row(eid) is None


def test_post_delete_without_ajax_header_falls_back_to_html_redirect(client):
    """Direct nav POST (no X-Requested-With header) keeps the 302 fallback."""
    _login(client, "demo@spendly.com", "demo123")
    eid = _stage_own_expense(demo_id())

    resp = _post_delete(client, eid, ajax=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    assert not resp.headers.get("Content-Type", "").startswith("application/json")
    # Row really gone.
    assert _fetch_expense_row(eid) is None


def test_post_delete_ajax_cross_user_returns_404_and_row_unchanged(client):
    """AJAX POST on another user's id -> 404, row NOT touched."""
    _login(client, "demo@spendly.com", "demo123")
    other_id = make_user("Eve 9", "eve9@example.com", "password123")
    other_eid = _stage_own_expense(other_id, amount=42.00,
                                  description="theirs")

    resp = _post_delete(client, other_eid)
    assert resp.status_code == 404
    # Row is unchanged
    row = _fetch_expense_row(other_eid)
    assert row is not None
    assert row["amount"] == 42.00
    assert row["description"] == "theirs"


def test_post_delete_ajax_unknown_id_returns_404(client):
    """AJAX POST on an id that doesn't exist -> 404."""
    _login(client, "demo@spendly.com", "demo123")
    resp = _post_delete(client, 99999)
    assert resp.status_code == 404