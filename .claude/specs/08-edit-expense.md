# Spec: Edit Expense

## Overview
The `GET /expenses/<id>/edit` route is currently a stub (`return "Edit expense — coming in Step 8"`). This step promotes it to a real `GET / POST` view so a signed-in user can correct a previously-recorded spend (amount, category, date, description) and the row in the `expenses` table is updated in place. The form is pre-populated from the existing row on `GET`, validates on `POST` using the same four-rule pipeline established in Step 7 (add-expense), and on success redirects (HTTP 302) back to `/profile` so the corrected row appears at its new position in the recent-transactions table. An "Edit" link is added next to each row in the recent-transactions table on `/profile` so the page is the natural starting point for a correction, mirroring the `+ Add expense` CTA on the user-info card.

This step **reuses** the Step 7 validation pipeline verbatim — same `CATEGORIES` whitelist, same `DATE_RE`, same `AMOUNT_MIN`/`AMOUNT_MAX` bounds, same `AMOUNT_RANGE_ERROR` wording — so the add and edit forms never disagree about what counts as a valid expense. Ownership is enforced server-side via `WHERE user_id = ?` on every read and write, and an `id` that doesn't belong to the session user returns 404 rather than leaking that the row exists.

## Depends on
- Step 1 — Database setup (`expenses` table with `id`, `user_id`, `amount`, `category`, `date`, `description`, `created_at`)
- Step 3 — Login + Logout (session guard; signed-in only)
- Step 4 — Profile Page Design (`/profile` renders the recent-transactions table)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses`, `get_user_stats` are the read paths; the updated row must reflect immediately on the next profile render)
- Step 7 — Add Expense (the validation pipeline — `CATEGORIES`, `DATE_RE`, `AMOUNT_MIN`, `AMOUNT_MAX`, `AMOUNT_RANGE_ERROR`, the `Decimal`-based amount check, future-date guard, 200-char description cap — is the source of truth for both add and edit; this step reuses it verbatim)

## Routes
- `GET /expenses/<int:id>/edit` — fetch the expense row (scoped to `session["user_id"]`); if missing return 404, otherwise render `edit_expense.html` pre-populated with the row's current values and the date input's `max` set to today — logged-in only (redirect to `/login` if not authenticated)
- `POST /expenses/<int:id>/edit` — re-validate the form using the same four-rule pipeline as `/expenses/add`; on success update the row (scoped to `session["user_id"]`); on failure re-render the form with the typed values echoed back and an inline error message — logged-in only
- `GET /expenses/<int:id>/edit` for an `id` that doesn't exist OR doesn't belong to the session user returns **404** (via `abort(404)`), not a generic error page — this prevents an attacker from probing which ids are in use

No new routes beyond the existing stub being promoted.

## Database changes
No schema changes. The `expenses` table already carries every column this step needs (Step 1). Two new helpers in `database/db.py`:

1. `get_expense_by_id(expense_id, user_id)` — return the row matching `id = ? AND user_id = ?`, or `None` if not found. Used by both `GET` (to pre-populate) and `POST` (to confirm ownership before update). Returns `None` for both "doesn't exist" and "belongs to a different user" so the route can `abort(404)` uniformly.
2. `update_expense(expense_id, user_id, amount, category, date, description)` — issue a parameterised `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? WHERE id = ? AND user_id = ?`. Empty / whitespace-only `description` is stored as `NULL` (same convention as `create_expense`). Returns the number of rows affected (`0` if the row vanished between the read and the write — caller may treat as 404; in practice this is unreachable because the same route just read it).

## Templates
- **Create:** `templates/edit_expense.html` — extends `base.html`; near-clone of `add_expense.html` with three differences: (a) heading reads "Edit expense", subtitle reflects the row's date/amount for context; (b) every input is pre-filled from the row (the `<select>` marks the row's category as `selected`); (c) submit button reads "Save changes" instead of "Save expense". Same `.form-error` banner, same `.add-expense-form-actions` row with a ghost "Cancel" link back to `/profile`, same `* Required` footer.
- **Modify:** `templates/profile.html` — add an `Actions` column (or, to avoid widening the table, a trailing cell on each row containing an "Edit" link → `url_for('edit_expense', id=txn.id)`) to the recent-transactions table. The link uses the existing `.btn-ghost` token so it sits flush with the rest of the page chrome.

## Files to change
- `app.py` — replace the `/expenses/<int:id>/edit` stub with a real `GET / POST` view; add a route-scoped `Decimal` amount parser mirroring the Step 7 branches; add a small `_render_edit_expense_error(expense_id, today, amount, category, date_str, description)` helper that re-uses the same template; update the import block to include `update_expense` and `get_expense_by_id`
- `database/db.py` — add `get_expense_by_id(expense_id, user_id)` and `update_expense(expense_id, user_id, amount, category, date, description)` helpers
- `templates/profile.html` — add the per-row Edit link in the recent-transactions table
- `static/css/style.css` — add minimal styles for `.profile-table-actions` (the trailing cell), `.profile-table-edit-link` (the ghost-style link inside it). All rules reuse existing CSS variables — no new hex values

## Files to create
- `templates/edit_expense.html` — the edit form page

## New dependencies
No new dependencies. `Decimal` and `abort` are in the Python standard library / Flask itself.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (no change here, but the user-facing auth boundary stays put)
- Use CSS variables — never hardcode hex values in `style.css`; reuse the existing tokens (`--accent`, `--ink`, `--ink-muted`, `--paper-card`, `--paper`, `--border`, `--border-soft`, `--danger`, `--danger-light`, `--radius-sm`, `--radius-md`, `--font-display`, `--font-body`)
- All templates extend `base.html`
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- Route functions stay one-responsibility: validate inputs, fetch / persist via `db.py` helpers, render template (or redirect), done
- The `user_id` always comes from `session["user_id"]` — never accept it from the form, and never interpolate it into a URL
- Ownership is enforced by **scoping every query with `AND user_id = ?`** — the route NEVER fetches by `id` alone. `get_expense_by_id(id, session_user_id)` returns `None` for ids that don't exist OR that belong to another user; the route then calls `abort(404)`. This is the same defense-in-depth pattern as `get_user_expenses(user_id, ...)` already used on `/profile`.
- Currency formatting stays INR (₹) per project memory
- POST-Redirect-GET: on success the route must `redirect(url_for("profile"))` (HTTP 302)
- Server-side validation is the source of truth — `step="0.01"`, `min`, `max`, and `maxlength` on the inputs are UX hints, not guards
- Amount validation uses `Decimal` (not `float`) so the comparison is exact and NaN / sNaN cannot slip through `SUM(amount)` on the profile page
- The lower bound is `AMOUNT_MIN` (₹0.01), not `0`, so sub-paise values like `0.001` don't pass and round to "₹0.00" on the profile page
- The four validation rules (amount, category, date, description) are **byte-for-byte the same** as Step 7 — same error strings, same branch order, same Decimal bounds. The only difference is what happens on success: `update_expense(...)` instead of `create_expense(...)`
- The app runs on **port 5001**, not the Flask default 5000
- FK enforcement is manual — `get_db()` runs `PRAGMA foreign_keys = ON` on every connection

## Validation rules (POST `/expenses/<id>/edit`)

Validation runs in the same fixed order as Step 7's add-expense, returning the form with the typed values echoed back on the first failure. Error strings are identical so users learn one set of messages:

1. **amount** — must be a parseable `Decimal`, finite, `>= AMOUNT_MIN` (₹0.01), `<= AMOUNT_MAX` (₹1,000,000).
   - Empty → `"Please enter an amount."`
   - Non-numeric, NaN, out-of-range → `"Please enter a valid amount between ₹0.01 and ₹10,00,000."`
2. **category** — must be in `CATEGORIES` after stripping whitespace.
   - Missing or unknown → `"Please choose a category."`
3. **date** — must match `DATE_RE` (`^\d{4}-\d{2}-\d{2}$`) AND parse via `date.fromisoformat()` AND not be in the future.
   - Bad format / unparseable → `"Please enter a valid date."`
   - Future date → `"Date cannot be in the future."`
4. **description** — `len(description) <= 200` after stripping.
   - Too long → `"Description must be 200 characters or fewer."`

If the form fails validation, the template re-renders with the user's typed values — **not** the original row's values. This matches the add-expense contract and keeps the "type → see your typing" mental model intact.

If the row id is missing or doesn't belong to the session user, the route `abort(404)` regardless of whether the request was `GET` or `POST`. A POST whose id fails ownership returns 404 **before** validation runs.

## Definition of done
- Visiting `/expenses/1/edit` while signed out returns 302 to `/login` (both GET and POST)
- Visiting `/expenses/99999/edit` for an id that doesn't exist returns 404
- Visiting another user's expense id returns 404 (verified by signing in as user A, fetching user B's id, and confirming the response)
- After signing in, `GET /expenses/<own-id>/edit` returns 200 with the form pre-populated: the amount input matches the stored row, the category `<select>` shows the row's category as `selected`, the date input shows the row's date, the description textarea shows the row's description, and the date input's `max` attribute is set to today
- Submitting a valid form updates the row (verified by `SELECT` directly via `sqlite3` or by re-rendering `/profile` and confirming the new values appear) and redirects 302 to `/profile`
- After the redirect, the updated row reflects the new amount / category / date / description on `/profile` in the recent-transactions table and the stats row reflects the new totals
- Submitting an empty amount shows `"Please enter an amount."` and re-renders the form with the typed values preserved (NOT the original row's values)
- Submitting `amount=abc`, `amount=0`, `amount=-10`, or `amount=1000000.01` shows the range error
- Submitting an unknown category (e.g. `Crypto`) shows `"Please choose a category."`
- Submitting an empty, malformed, or future date shows the appropriate error
- Submitting a 201-character description shows the length error
- Submitting a 200-character description succeeds
- Submitting an empty/whitespace-only description stores NULL in the column (matches the add-expense convention; the description cell on `/profile` renders as empty)
- An attacker submitting a `user_id` field is ignored; the updated row's `user_id` remains the original owner
- An attacker submitting a POST to `/expenses/<other-user-id>/edit` returns 404, not 200, and no row is updated
- The Edit link is visible on every row of the recent-transactions table on `/profile` and links to the matching `/expenses/<id>/edit`
- All existing tests (43 tests across `test_profile.py`, `test_06-date-filter-profile.py`, `test_07_add_expense.py`) still pass
- No new hex values in `style.css`; every new CSS rule uses existing variables
- Every SQL string in `database/db.py` uses `?` placeholders
- No new pip packages added
