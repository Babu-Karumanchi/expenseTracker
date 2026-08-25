# Spec: Delete Expense

## Overview
The `POST /expenses/<id>/delete` route replaces the previous stub. This step promotes destructive removal from a stub to a real owner-scoped DELETE flow, gated by a styled modal on `/profile` that matches the Spendly palette. The modal is the **only** UI gate — there is no separate GET confirmation page, no native `window.confirm()` dialog, no JavaScript framework. Clicking Delete on a row opens a modal showing the row's date / category / amount, with Cancel and a red Delete button. Cancel closes the modal; Delete submits a POST form (via `fetch()`) that targets the same `/expenses/<id>/delete` endpoint, which deletes the row. The modal's JS handler then removes the row from `/profile` in place — there is **no page reload**.

The destructive verb is **POST-only** — direct GET to `/expenses/<id>/delete` returns 405 Method Not Allowed (Flask's default; there is no GET resource to render). Ownership is enforced server-side via `WHERE user_id = ?` on every read and write, and an `id` that doesn't belong to the session user returns 404 rather than leaking that the row exists. Server-side ownership is the actual security gate; the modal is purely a UX wrapper.

The modal infrastructure (`<div class="modal" hidden>`, `[data-open-modal]`, `[data-close-modal]`, `[data-ajax-form]`, Escape key, backdrop click, body scroll lock, `aria-modal`) is the existing pattern already in use by the landing-page demo video modal in `templates/landing.html` and `static/js/main.js`. This step **reuses** that infrastructure — no new JS framework, no new modal CSS framework, only minimal CSS additions for the body / actions / summary rows.

## Depends on
- Step 1 — Database setup (`expenses` table with `id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`)
- Step 3 — Login + Logout (session guard; signed-in only)
- Step 4 — Profile Page Design (`/profile` renders the recent-transactions table)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses`, `get_user_stats` are the read paths; the deleted row must disappear immediately from the next profile render)
- Step 7 — Add Expense (the "+ Add expense" CTA on `/profile` opens an inline form modal; see spec 07)
- Step 8 — Edit Expense (the per-row Edit link opens an inline form modal; see spec 08 — also reuses `get_expense_by_id(id, user_id)` for the ownership-scoped read in the POST handler)

## Routes
- `POST /expenses/<int:id>/delete` — auth guard (302 → `/login` if not signed in); ownership check (`get_expense_by_id(id, session_user_id)` → `abort(404)` if missing or owned by another user); `delete_expense_row(id, session_user_id)`. The response is branched on the `X-Requested-With` request header:
  * AJAX (`XMLHttpRequest`) → JSON `{"ok": true, "id": <int>}` (status 200). The modal's JS handler then removes the row + the now-orphaned per-row modals from `/profile` in place.
  * Direct nav (no header) → HTTP 302 to `/profile` (preserves the existing no-JS fallback).
- `GET /expenses/<int:id>/delete` — returns **405 Method Not Allowed**. There is no GET resource to render; the user-facing gate is the modal on `/profile`. The 405 fires before the auth and ownership guards, so a signed-out GET to `/expenses/<id>/delete` returns 405, NOT 302.

No new routes beyond the existing stub being converted to POST-only.

## Database changes
No schema changes. The `expenses` table already carries every column this step needs (Step 1). One new helper in `database/db.py`:

1. `delete_expense(expense_id, user_id)` — issue a parameterised `DELETE FROM expenses WHERE id = ? AND user_id = ?`. The `AND user_id = ?` clause means an attempt to delete another user's row silently affects 0 rows rather than raising. Returns the number of rows affected (`0` if the row vanished between the read and the write — caller may treat as 404). The route uses the same `get_expense_by_id(id, session_user_id)` from Step 8 for the ownership-scoped read on POST, so no additional read helper is needed.

## Templates
- **Modify:** `templates/profile.html` —
  - The per-row Delete trigger becomes `<a class="profile-table-delete-link" href="{{ url_for('delete_expense', id=txn.id) }}" data-open-modal="delete-modal-{{ txn.id }}">` (the `href` is kept for no-JS fallback and a11y; the modal is the primary UX).
  - The per-row Edit trigger gains `data-open-modal="edit-modal-{{ txn.id }}"`.
  - The page-level "+ Add expense" CTA gains `data-open-modal="add-expense-modal"`.
  - Three modal blocks are appended at the end of the `{% block content %}` (outside the `<section>` so they overlay the full page): one page-global `add-expense-modal`, and per-row `edit-modal-<id>` / `delete-modal-<id>` blocks inside a `{% for txn in transactions %}` loop.
- **Delete:** `templates/delete_expense.html` — REMOVED. The modal replaces the GET confirmation page entirely.

## Files to change
- `app.py` — change `@app.route("/expenses/<int:id>/delete", methods=["GET", "POST"])` to `methods=["POST"]` and drop the GET branch. The route becomes a single-purpose POST handler.
- `templates/profile.html` — wire up the three `data-open-modal` triggers and append the three modal blocks.
- `static/js/main.js` — add a delegated `submit` event listener that intercepts any `<form>` carrying `data-ajax-form` inside a `.modal:not([hidden])`, posts via `fetch()` with `X-Requested-With: XMLHttpRequest`, and updates the DOM in place on success. Replaces the old `[data-close-modal-and-submit]` click branch. Everything else (modal open/close, Escape handler, backdrop click) stays exactly as it is.
- `static/css/style.css` — append `.modal-window--narrow` (440px max width), `.modal-body`, `.modal-actions`, `.modal-actions .btn-ghost` (text-align override), `.modal-summary`, `.modal-summary strong`, `.modal-delete-form`, `.modal-window--wide` (600px max width for Add/Edit modals), `.modal-form-error`, `.modal-form-error[hidden]`. All reuse existing CSS variables — no new hex values.
- `database/db.py` — add `delete_expense(expense_id, user_id)` helper (unchanged from the prior step).
- `.claude/specs/08-edit-expense.md` — add a brief note that the Edit link on `/profile` opens a modal first.
- `.claude/specs/07-add-expense.md` — add a brief note that the "+ Add expense" CTA on `/profile` opens a modal first.
- `tests/test_09_delete_expense.py` — replace the GET confirmation page tests with modal markup tests + 405 endpoint tests.
- `tests/test_profile.py` — add a test for the Add expense modal markup.

## Files to delete
- `templates/delete_expense.html` — no longer referenced after the GET branch is removed.

## Files to create
(none — modal markup lives at the bottom of `templates/profile.html`)

## New dependencies
No new dependencies. `window.confirm` is NOT used. The modal markup uses `hidden`, `aria-hidden`, `aria-modal`, `aria-labelledby`, `role="dialog"` — all standard HTML attributes. No pip packages, no JS libraries, no CSS frameworks.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (no change here, but the user-facing auth boundary stays put)
- Use CSS variables — never hardcode hex values in `style.css`; reuse the existing tokens
- All templates extend `base.html`
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- Route functions stay one-responsibility: validate inputs, fetch / persist via `db.py` helpers, render template (or redirect), done
- The `user_id` always comes from `session["user_id"]` — never accept it from the form, and never interpolate it into a URL
- Ownership is enforced by **scoping every query with `AND user_id = ?`** — the route NEVER fetches by `id` alone. `get_expense_by_id(id, session_user_id)` returns `None` for ids that don't exist OR that belong to another user; the route then calls `abort(404)`. This is the same defense-in-depth pattern as `get_expense_by_id(id, user_id)` already used on `/expenses/<id>/edit`.
- The destructive verb is **POST-only**. A direct GET to `/expenses/<id>/delete` returns 405 (no GET resource). The modal is the only UI gate — it renders a `<form method="post" action="…" data-ajax-form>` whose submit button carries `data-ajax-submit` so the JS intercepts the submit and POSTs via fetch.
- The modal is **not** the security gate. The server-side ownership check is the security gate. If a malicious user POSTs directly to `/expenses/<other-user-id>/delete`, the ownership check returns 404 BEFORE the DELETE runs. The modal is purely UX.
- **No** `window.confirm()` — the user explicitly asked for a styled modal that matches Spendly's palette, not a browser-native dialog.
- **No** new JS framework, **no** new pip package. The modal uses the existing `data-open-modal` / `data-close-modal` infrastructure already in `static/js/main.js`. The new `data-ajax-form` attribute is an opt-in marker for forms that should submit via fetch instead of native navigation.
- Currency formatting stays INR (₹) per project memory
- POST-Redirect-GET: on success the route must `redirect(url_for("profile"))` (HTTP 302)
- The app runs on **port 5001**, not the Flask default 5000
- FK enforcement is manual — `get_db()` runs `PRAGMA foreign_keys = ON` on every connection

## Delete modal contract (on `/profile`)

The per-row Delete trigger on `/profile` opens a styled modal. One modal per row (keyed by `txn.id`) — Jinja renders the markup inside the existing `{% for txn in transactions %}` loop.

**Trigger on the row:**
```html
<a class="profile-table-delete-link"
   href="{{ url_for('delete_expense', id=txn.id) }}"
   data-open-modal="delete-modal-{{ txn.id }}"
   aria-label="Delete transaction from {{ txn.date }}">Delete</a>
```

**Modal markup:**
```html
<div id="delete-modal-{{ txn.id }}" class="modal" hidden aria-hidden="true"
     role="dialog" aria-modal="true" aria-labelledby="delete-modal-title-{{ txn.id }}">
    <div class="modal-backdrop" data-close-modal></div>
    <div class="modal-window modal-window--narrow" role="document">
        <button type="button" class="modal-close" data-close-modal aria-label="Close">&times;</button>
        <h2 id="delete-modal-title-{{ txn.id }}" class="modal-title">Delete this expense?</h2>
        <p class="modal-body">This will permanently remove the row from your history. This can't be undone.</p>
        <p class="modal-summary">
            <span>{{ txn.date }}</span>
            <span>&middot;</span>
            <span class="category-badge category-badge--{{ txn.category_class }}">{{ txn.category }}</span>
            <span>&middot;</span>
            <strong>{{ txn.amount }}</strong>
        </p>
        <div class="modal-form-error" hidden role="alert"></div>
        <div class="modal-actions">
            <button type="button" class="btn-ghost" data-close-modal>Cancel</button>
            <form method="post" action="{{ url_for('delete_expense', id=txn.id) }}" class="modal-delete-form" data-ajax-form>
                <button type="submit" class="btn-danger" data-ajax-submit>Delete</button>
            </form>
        </div>
    </div>
</div>
```

**Contract:**
- **Heading:** "Delete this expense?"
- **Body:** "This will permanently remove the row from your history. This can't be undone."
- **Summary row** (`.modal-summary`): the row's `date`, a category chip matching the existing `.category-badge` style, and the formatted `amount` (`₹<amount>:,.2f`). Lets the user verify what they're about to remove.
- **Action row** (`.modal-actions`): two siblings —
  1. A `<button class="btn-ghost" data-close-modal>Cancel</button>` that ONLY closes the modal — does NOT submit any form.
  2. A `<form method="post" action="{{ url_for('delete_expense', id=txn.id) }}" data-ajax-form>` wrapping a `<button class="btn-danger" data-ajax-submit>Delete</button>` that the JS submit listener intercepts and POSTs via fetch.

The form carries `data-ajax-form` (the opt-in marker for fetch-based submission); the danger button carries `data-ajax-submit` (a semantic marker — the JS dispatches purely on the form's `data-ajax-form`, not on the button attribute). The Cancel button carries `data-close-modal` only — it never submits the form. This split is what guarantees Cancel does nothing destructive even if the user double-clicks.

**Success / failure JSON shapes (modal submission):**
- Success: `{"ok": true, "id": <int>, "total": "₹...", "count": N}` (status 200). The JS handler removes `tr[data-expense-id="<id>"]`, removes the now-orphaned `delete-modal-<id>` and `edit-modal-<id>` blocks, and overwrites `#profile-grand-total` and `#profile-txn-count` from the envelope (so the stat tiles stay in sync with the deletion without a page reload). `total` is formatted via `f"₹{n:,.2f}"` and `count` is an int. The values reflect the page's current date filter (`from`/`to` carried via hidden inputs on the modal form).
- Failure (404 from `abort(404)` — Flask default HTML): the JS catch surfaces a generic "Could not save" message inside the modal.
- Failure (403 — CSRF mismatch on POST): `{"ok": false, "error": "Security token missing or invalid."}` (status 403) for AJAX; HTML via `abort(403)` for direct nav. The CSRF check runs only on POST and only for state-changing requests — signed-out POSTs keep 302 to /login because AUTH runs before CSRF.

The modal matches Spendly's palette via existing CSS variables: `--paper-card` for the window surface, `--ink` for the heading, `--ink-soft` for body text, `--ink-muted` for the summary, `--paper-warm` + `--border-soft` for the summary background, `--danger` for the Delete button, `--accent` / `--ink-soft` for the ghost Cancel button. No new hex values are introduced.

## Definition of done
- Visiting `/expenses/<id>/delete` via GET (any id, signed in or not) returns **405 Method Not Allowed** — there is no GET resource
- Visiting `/expenses/<id>/delete` via POST while signed out returns 302 to `/login`, AND the row in the DB is untouched
- Visiting `/expenses/99999/delete` via POST while signed in returns 404, no row touched
- Visiting `/expenses/<other-user-id>/delete` via POST while signed in returns 404, AND the row in the DB is unchanged
- Submitting the Delete modal's form (POST `/expenses/<id>/delete`) deletes the row. The response is branched on `X-Requested-With`: with the header, JSON `{"ok": true, "id": <int>, "total": "₹...", "count": N}` so the modal's JS can remove the row in place and update the stat tiles; without the header, HTTP 302 to `/profile` (no-JS fallback). In both cases the row vanishes from the DB and the row's `total` / `count` echo is computed against the page's current `from`/`to` filter.
- POSTing with `X-Requested-With: XMLHttpRequest` returns JSON `{"ok": true, "id": <int>, "total": "₹...", "count": N}` for the demo user's own row; the modal's JS handler removes the row from `/profile` in place without a page reload.
- POSTing with `X-Requested-With: XMLHttpRequest` for an unknown / cross-user id returns 404 (Flask default HTML); the JS catch surfaces a generic error message inside the modal.
- POSTing with a missing or wrong `csrf_token` returns 403 (JSON for AJAX, HTML via `abort(403)` for direct nav); the row is untouched. The CSRF check runs after the auth guard so signed-out POSTs keep 302 to /login.
- An attacker submitting a `user_id` field on the POST is ignored; only the session's `user_id` is used
- `/profile` renders a `delete-modal-<id>` block for every transaction row
- Each delete modal contains a `<form method="post" action="/expenses/<id>/delete" data-ajax-form>` with hidden `csrf_token` / `from` / `to` inputs and a danger submit button labelled "Delete" carrying `data-ajax-submit`
- Each delete modal contains a Cancel button carrying `data-close-modal` (NOT `data-ajax-submit`)
- Each delete modal's summary line shows the row's date, category chip, and formatted amount
- `/profile` renders an `edit-modal-<id>` block for every transaction row (the per-row Edit modal — see spec 08)
- `/profile` renders exactly one `add-expense-modal` block (the page-global Add expense modal — see spec 07)
- The Add expense modal contains a `<form method="post" action="/expenses/add" data-ajax-form>` with the four fields and a primary submit button labelled "Save expense"
- The Edit modal contains a `<form method="post" action="/expenses/<id>/edit" data-ajax-form>` pre-populated from the row, with a primary submit button labelled "Save changes"
- The Delete modal is the ONLY UI gate for delete — there is no separate GET confirmation page
- `window.confirm()` is **not** used anywhere on `/profile`
- All existing tests (Step 1, 2, 3, 4, 5, 6, 7, 8) still pass
- No new hex values in `style.css`; every new CSS rule uses existing variables
- Every SQL string in `database/db.py` uses `?` placeholders
- No new pip packages added