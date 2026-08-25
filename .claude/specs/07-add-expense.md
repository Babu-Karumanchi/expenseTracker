# Spec: Add Expense

## Overview
The `/expenses/add` route is currently a stub (`return "Add expense — coming in Step 7"`). This step replaces it with a real GET / POST form so a signed-in user can record a new spend (amount, category, date, description), the server validates the submission, and a row lands in the `expenses` table linked to `session["user_id"]`. On success the user is redirected to `/profile` where the new row appears at the top of the recent-transactions table (sorted `date DESC, id DESC` per Step 5) and the stats row reflects the new totals. A `+ Add expense` CTA is added to the user-info card on `/profile` so the form is one click away from the natural "I just spent money" starting point.

This is the first step that **writes** through the schema seeded in Step 1 and read in Step 5 — every later expense feature (Step 8 edit, Step 9 delete) reuses the same `expenses` columns and the same 7-category vocabulary, so the validation rules and category whitelist established here carry forward.

## Depends on
- Step 1 — Database setup (the `expenses` table with `user_id`, `amount`, `category`, `date`, `description`, `created_at` columns must exist; `get_db()` enforces FKs)
- Step 2 — Registration (user accounts must exist)
- Step 3 — Login + Logout (session must be set; `/profile` is the authenticated landing page)
- Step 4 — Profile Page Design (`templates/profile.html` exists with the user-info card on the right side, ready for an action button)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses(...)` and `get_user_stats(...)` are the read helpers that immediately reflect the new row)
- Step 6 — Date Filter on Profile (the filter's defaults keep today's expense visible immediately after a redirect)

## Routes
- `GET /expenses/add` — render the empty add-expense form with the date field pre-filled with today's ISO date and the category dropdown populated with the 7 fixed categories — logged-in only (redirect to `/login` if not authenticated)
- `POST /expenses/add` — validate `amount`, `category`, `date`, `description`; on success insert a row into `expenses`. The response is branched on the `X-Requested-With` request header:
  * AJAX (`XMLHttpRequest`) → JSON `{"ok": true, "expense": {id, date, description, category, category_class, amount}, "total": "₹...", "count": N}` (status 200). The modal's JS handler then renders the new row in place on `/profile` and overwrites the `#profile-grand-total` and `#profile-txn-count` stat tiles from the envelope (so a filtered `/profile?preset=last_3_months` keeps showing filtered stats after the Add).
  * Direct nav (no header) → HTTP 302 to `/profile` (POST-Redirect-GET; preserves the existing no-JS fallback).
  On validation failure the same split applies: JSON `{"ok": false, "error": "...", "values": {amount, category, date, description}}` for AJAX, or re-render the standalone page with typed values echoed for direct nav. Logged-in only.
- **CSRF check** — runs on POST only (not GET). POST carries a hidden `csrf_token` form field bound to `session["csrf_token"]`. The check is a constant-time `hmac.compare_digest`; on mismatch it returns 403 (JSON for AJAX, HTML via `abort(403)` for direct nav). The login + register routes stamp a fresh `session["csrf_token"]` via `secrets.token_urlsafe(32)` so the post-redirect `/profile` GET already has a valid token. Order in the POST handler: AUTH → CSRF → ownership (no-op for add) → validation.

No new routes beyond the existing stub being promoted.

## Database changes
No schema changes. The `expenses` table already carries every column this step needs. The single new helper `create_expense(user_id, amount, category, date, description)` in `database/db.py` issues a parameterised `INSERT INTO expenses ... VALUES (?, ?, ?, ?, ?)` and returns the new row id. Empty / whitespace-only `description` is stored as `NULL` to preserve the column's NULL semantics. The `created_at` column has `DEFAULT (datetime('now'))`, so it is intentionally not supplied.

## Templates
- **Create:** `templates/add_expense.html` — extends `base.html`; renders the form with a `form-error` banner on validation failure, four fields (amount, category, date, description), a primary "Save expense" submit button, and a ghost "Cancel" link back to `/profile`
- **Modify:** `templates/profile.html` — wrap the existing disabled "Edit profile" button in a new `.profile-info-actions` flex container and prepend a `+ Add expense` link (uses `.btn-primary`) pointing at `url_for('add_expense')`. The link carries `data-open-modal="add-expense-modal"` so clicking it opens a styled modal containing a real `<form method="post" action="{{ url_for('add_expense') }}" data-ajax-form>` — see the "Inline form modal" appendix below. The form's URL and POST flow are unchanged from the route's perspective.

## Files to change
- `app.py` — replace the `/expenses/add` stub with the real GET/POST view; add `from decimal import Decimal, InvalidOperation`; add `CATEGORIES`, `AMOUNT_MIN`, `AMOUNT_MAX`, `AMOUNT_RANGE_ERROR` module-level constants; add `_render_add_expense_error` helper
- `database/db.py` — add `create_expense(user_id, amount, category, date, description)` helper
- `templates/profile.html` — add `+ Add expense` CTA inside `.profile-info-actions`
- `static/css/style.css` — add minimal styles for `.profile-info-actions`, `.add-expense-page`, `.add-expense-back`, `.add-expense-card`, `.add-expense-form`, `.add-expense-form .form-field-label`, `.add-expense-prefix`, `.add-expense-hint`, `.add-expense-form-actions`, `.add-expense-form-actions .btn-ghost`, `.add-expense-required`, `.form-error` (all using existing CSS variables; no new hex values)

## Files to create
- `templates/add_expense.html` — the new form page

## New dependencies
No new dependencies. The `decimal` module is in the Python standard library.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (no change here, but the user-facing auth boundary stays put)
- Use CSS variables — never hardcode hex values in `style.css`; reuse the existing tokens (`--accent`, `--ink`, `--ink-muted`, `--paper-card`, `--paper`, `--border`, `--border-soft`, `--danger`, `--danger-light`, `--radius-sm`, `--radius-md`, `--font-display`, `--font-body`)
- All templates extend `base.html`
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- Route functions stay one-responsibility: validate inputs, fetch / persist via `db.py` helpers, render template (or redirect), done
- The `user_id` always comes from `session["user_id"]` — never accept it from the form
- Currency formatting stays INR (₹) per project memory
- POST-Redirect-GET: on success the route must `redirect(url_for("profile"))` (HTTP 302)
- Server-side validation is the source of truth — `step="0.01"`, `min`, `max`, and `maxlength` on the inputs are UX hints, not guards
- Amount validation uses `Decimal` (not `float`) so the comparison is exact and NaN / sNaN cannot slip through `SUM(amount)` on the profile page
- The lower bound is `AMOUNT_MIN` (₹0.01), not `0`, so sub-paise values like `0.001` don't pass and round to "₹0.00" on the profile page
- The app runs on **port 5001**, not the Flask default 5000
- FK enforcement is manual — `get_db()` runs `PRAGMA foreign_keys = ON` on every connection, so inserting with an invalid `user_id` fails cleanly via `sqlite3.IntegrityError`

## Validation rules (POST `/expenses/add`)

Validation runs in this fixed order, returning the form with the typed values echoed back on the first failure:

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

## Definition of done
- Visiting `/expenses/add` while signed out returns 302 to `/login` (both GET and POST)
- After signing in, GET `/expenses/add` returns 200 with the form, the date field pre-filled with today's ISO date, the `max` attribute set to today, and the category dropdown showing all 7 categories
- Submitting a valid form inserts a row in `expenses` with `user_id` from `session["user_id"]` (NOT from any form field) and redirects 302 to `/profile`
- After the redirect, the new row appears at the top of the recent-transactions table on `/profile` and the stats row reflects the new totals
- Submitting an empty amount shows `"Please enter an amount."` and re-renders the form with the typed values preserved
- Submitting `amount=abc`, `amount=0`, `amount=-10`, or `amount=1000000.01` shows the range error
- Submitting an unknown category (e.g. `Crypto`) shows `"Please choose a category."`
- Submitting an empty, malformed, or future date shows the appropriate error
- Submitting a 201-character description shows the length error
- Submitting a 200-character description succeeds
- An attacker submitting a `user_id` field is ignored; the inserted row's `user_id` is always the session user's id
- The `+ Add expense` CTA is visible on `/profile` next to the disabled "Edit profile" button, inside the user-info card, and opens an inline form modal (see appendix) instead of navigating
- All existing tests (41 tests across `test_profile.py` and `test_06-date-filter-profile.py`) still pass
- No new hex values in `style.css`; every new CSS rule uses existing variables
- Every SQL string in `database/db.py` uses `?` placeholders
- No new pip packages added

## Inline form modal (replaces the pre-navigation gate)

The `+ Add expense` CTA on `/profile` opens a styled modal that contains a real `<form method="post" action="{{ url_for('add_expense') }}">` — there is **no navigation**. Submitting the form posts via `fetch()` to `/expenses/add` with the header `X-Requested-With: XMLHttpRequest`. On success the modal's JS handler renders the new row at the top of the recent-transactions table on `/profile` and closes the modal. On validation failure the error renders inside the modal and the typed values are echoed back into the inputs.

The modal is part of the wider `/profile` modal scheme documented in full in `.claude/specs/09-delete-expense.md` (which covers the `data-open-modal` / `data-close-modal` / `data-ajax-form` infrastructure, the CSS variables, and the JS submit handler). The contract specific to the Add expense modal is:

- **Trigger:** the `+ Add expense` link carries `data-open-modal="add-expense-modal"` (the `href` is preserved for no-JS fallback and a11y).
- **Heading:** "Add expense".
- **Body:** "Record a new spend. You can cancel any time before saving."
- **Form:** a `<form method="post" action="/expenses/add" data-ajax-form novalidate>` carrying the same four fields (`amount`, `category`, `date`, `description`) with the same input attributes (`step="0.01"`, `min="0.01"`, `max="1000000"`, `maxlength="200"`) as `add_expense.html`. The date input is pre-filled with today's ISO date. The form also carries three hidden inputs (in this order, immediately after the opening tag):
  - `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` — bound to `session["csrf_token"]`, validated server-side on POST.
  - `<input type="hidden" name="from" value="{{ filter.from }}">` and `<input type="hidden" name="to" value="{{ filter.to }}">` — the page's current date-filter bounds, so the success envelope's `total`/`count` reflect the same filter the user is looking at. Empty strings on the default unfiltered view.
- **Actions:** a primary "Save expense" submit button and a ghost "Cancel" button (carries `data-close-modal`).
- **Width:** `.modal-window--wide` (~600px) so the four fields fit comfortably.

This spec is the authority on the add form itself; the modal is the form's primary UX surface. The form, validation, ownership check, and redirect (for the no-JS fallback) are unchanged.
