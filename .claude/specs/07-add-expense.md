# Spec: Add Expense

## Overview
Replace the `/expenses/add` stub (currently a raw string at `app.py:380-382`) with a real form that lets a signed-in user record a new expense. The form collects `amount`, `category`, `date`, and `description`, validates them server-side, and inserts a row into the `expenses` table linked to `session["user_id"]`. On success the user is redirected back to `/profile` and sees the new expense in the recent-transactions table. This is the first step that **writes** through the schema seeded in Step 1 and read in Step 5, so the route, the `db.py` helper, the form template, and the validation rules must all be cohesive — the edit/delete steps that follow (8 and 9) will reuse the same `expenses` columns and the same category vocabulary.

## Depends on
- Step 1 — Database setup (the `expenses` table with `user_id`, `amount`, `category`, `date`, `description` columns must exist)
- Step 2 — Registration (real user accounts must exist)
- Step 3 — Login + Logout (`session["user_id"]` must be set; the route must be a protected route)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses` / `get_user_stats` / `get_user_by_id` exist; the navbar already shows the signed-in user's name)
- Step 6 — Date Filter on Profile (the `?from=` / `?to=` filter on `/profile` is already wired so a fresh expense on today's date is visible immediately without a full page refresh)

## Routes
- `GET /expenses/add` — render the add-expense form, prefilling `date` with today's date in `YYYY-MM-DD` — logged-in only (redirect to `/login` if not authenticated)
- `POST /expenses/add` — validate the submitted form, insert a row into `expenses`, and redirect to `/profile` on success; on validation failure re-render the form with the user's typed values and an inline error message — logged-in only

The `/expenses/add` stub at `app.py:380-382` is replaced entirely. No other routes are touched.

## Database changes
No database changes. The `expenses` table (`database/db.py:19-28`) already carries every column the add form needs:

| Column | Used by form field |
| --- | --- |
| `user_id` | `session["user_id"]` — never accepted from the form |
| `amount` | `amount` input (decimal, > 0, ≤ 1,000,000) |
| `category` | `category` select (one of the 7 fixed categories from Step 1) |
| `date` | `date` input (`YYYY-MM-DD`, not in the future) |
| `description` | `description` input (optional, ≤ 200 chars) |

`PRAGMA foreign_keys = ON` is already enabled by `get_db()` (`database/db.py:36`), so inserting with an invalid `user_id` fails cleanly. The form never accepts a `user_id` from the user — it is always pulled from the session server-side.

## Templates
- **Create:** `templates/add_expense.html` — extends `base.html`. Layout:
  - **Heading:** "Add an expense" with a short subtitle ("Track every rupee. Record a new spend in under 10 seconds.")
  - **Back link:** a `<a href="{{ url_for('profile') }}">← Back to profile</a>` link above the form, so the user can bail without a 404 / hardcoded URL
  - **Form:** `<form method="post" action="{{ url_for('add_expense') }}" class="add-expense-form" novalidate>` containing four fields in this order:
    1. **Amount** — `<input type="number" name="amount" id="amount" step="0.01" min="0.01" max="1000000" required value="{{ amount or '' }}">` with a `₹` prefix label and a small hint "In Indian rupees. Up to ₹10,00,000."
    2. **Category** — `<select name="category" id="category" required>` with the 7 fixed categories from Step 1 (`Food`, `Transport`, `Bills`, `Health`, `Entertainment`, `Shopping`, `Other`) as `<option>`s. The placeholder option is `Select a category` with `value=""` and `disabled selected`. The submitted `category` is echoed back on validation failure.
    3. **Date** — `<input type="date" name="date" id="date" required value="{{ date or today }}" max="{{ today }}">` — prefilled with today's date on GET, capped at today so the browser blocks future dates client-side as a first line of defense (server still validates).
    4. **Description** — `<textarea name="description" id="description" maxlength="200" rows="2" placeholder="Optional. e.g. Lunch at office canteen">{{ description or '' }}</textarea>` with a small hint "Up to 200 characters."
  - **Inline error banner** at the top of the form, rendered only when `error` is truthy: `<div class="form-error" role="alert">{{ error }}</div>` — uses the existing `--color-danger` token. Replaces the form (the form is still rendered below it with the user's typed values echoed back).
  - **Submit row:** a primary submit button "Save expense" and a secondary `<a class="btn-ghost" href="{{ url_for('profile') }}">Cancel</a>` link. Both are full-width on the existing narrow-screen breakpoint.
  - **Required-field help line:** "* Required" muted text below the buttons.
  - **No JS** — the form is plain HTML; the only validation is server-side.

- **Modify:** `templates/profile.html` — add a single primary CTA to the user-info card so the new flow is discoverable. Specifically, add an `<a href="{{ url_for('add_expense') }}" class="btn btn-primary">+ Add expense</a>` button inside the existing `.profile-user-card` (next to the disabled "Edit profile" button), so the user always has a clear path to record a new expense from the profile page. No other markup changes.

## Files to change
- `database/db.py` — add one new helper:
  - `create_expense(user_id, amount, category, date, description)` — open its own `get_db()` connection, run `INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)` with parameterised `?` placeholders, commit, and return the new `expense.id` (the `lastrowid`). Description is stored as `None` when the user submitted an empty string so the column's `NULL` semantics are preserved. Mirrors the existing try/finally + `conn.close()` pattern used by `create_user` (`database/db.py:92-108`).
- `app.py` — replace the `/expenses/add` stub at `app.py:380-382` with a real view:
  - Import `create_expense` from `database.db` (extend the existing import block at `app.py:8-18`).
  - Add `CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]` as a module-level constant so the same list is reused in the route and the template.
  - **Auth guard:** if `session.get("user_id")` is missing, redirect to `/login` for both GET and POST — match the existing convention from `profile()` (`app.py:211-212`).
  - **GET branch:** render `add_expense.html` with `today = date.today().isoformat()`, `amount="", category="", date=today, description=""`. No `error` so the error banner is hidden.
  - **POST branch:** read `amount_raw`, `category`, `date_raw`, `description` from `request.form`. Strip whitespace on `category` and `description`; do not strip `amount` / `date` (those are mechanical fields, not free text). Validate in this order, returning the form with the user's typed values echoed back on the first failure:
    1. `amount` — must be a parseable `Decimal` (`from decimal import Decimal, InvalidOperation`) and `> 0` and `<= Decimal("1000000")`. Empty string → "Please enter an amount." Garbage / negative / zero / over the cap → "Please enter a valid amount between ₹0.01 and ₹10,00,000."
    2. `category` — must be in `CATEGORIES` after stripping. Empty or unknown → "Please choose a category."
    3. `date` — must match `^\d{4}-\d{2}-\d{2}$` (reuse the module-level `DATE_RE` at `app.py:24`) AND parse as a real `date` via `date.fromisoformat(...)` AND not be in the future (compare against `date.today()`). Invalid format → "Please enter a valid date." Future date → "Date cannot be in the future."
    4. `description` — strip, then len ≤ 200. Over 200 chars → "Description must be 200 characters or fewer." (The `<textarea maxlength="200">` enforces this client-side too; the server check is the source of truth.)
  - On success: call `create_expense(session["user_id"], amount_decimal, category, date_iso, description_or_None)`, then `redirect(url_for("profile"))` (HTTP 302). The user lands on `/profile` and sees the new expense at the top of the recent-transactions table because the page sorts `date DESC, id DESC` (Step 5).
  - Update the route docstring to describe the GET / POST split and the validation rules.
- `static/css/style.css` — add minimal classes for the new form page. **Use CSS variables already in the file** (`--color-*` / `--space-*` / `--radius-*`); no new hex values. Required classes:
  - `.add-expense-page` — outer wrapper, max-width same as the profile cards so the form aligns with the rest of the app
  - `.add-expense-form` — the `<form>` element, flex column on desktop, stacked on the existing narrow-screen breakpoint
  - `.form-field` — `<label>` + control + hint stack
  - `.form-field-label` — the label row (label text + optional required asterisk)
  - `.form-field-hint` — small muted text under the control (e.g. "Up to 200 characters.")
  - `.form-field-input` / `.form-field-select` / `.form-field-textarea` — input sizing and focus ring
  - `.form-error` — the error banner at the top of the form (uses `--color-danger` for background tint + text)
  - `.form-actions` — the submit + cancel row
  - `.btn-primary` — the primary save button (declared here even if a partial version exists, so the new CTA on the profile page can reuse it)
  - `.btn-ghost` — the secondary cancel link
- `tests/test_expenses.py` — new file. Cover the happy path and every validation rule:
  - Auth guard: GET and POST both 302 to `/login` when signed out
  - GET renders 200 with today's date prefilled and the category select populated with the 7 fixed categories
  - POST with valid `amount=499.00, category=Food, date=today, description="Lunch"` returns 302 to `/profile` and inserts a row in `expenses` with the right `user_id`
  - After the insert, visiting `/profile` shows the new expense in the transactions table (smoke check)
  - Empty `amount` re-renders the form with the error "Please enter an amount." and the typed values echoed back
  - Non-numeric / negative / zero `amount` each return the amount error
  - `amount` over the cap returns the amount error
  - Missing / unknown `category` returns "Please choose a category."
  - Missing `date` returns "Please enter a valid date."
  - `date` in the future returns "Date cannot be in the future."
  - `description` over 200 chars returns the description error
  - Two users: signed-in user A's POST inserts a row for user A (never user B); user A's session can't smuggle in a different `user_id` (verify the route ignores `request.form["user_id"]` even if provided)
  - The new row's `created_at` is non-null and is the current time (defensive — the column has a default)

## Files to create
- `templates/add_expense.html` — the add-expense form (see Templates above)
- `tests/test_expenses.py` — the test suite (see Files to change above)

## New dependencies
No new dependencies. The form uses native HTML5 input types (`<input type="number">`, `<input type="date">`, `<select>`, `<textarea>`) and vanilla JS-free submission. `Decimal` is in the standard library.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL, even for the `created_at` default
- Passwords hashed with werkzeug — no auth changes in this step
- Use CSS variables — never hardcode hex values in `style.css`; reuse the existing tokens
- All templates extend `base.html` (the new `add_expense.html` extends `base.html`, the new `+ Add expense` CTA in `profile.html` slots into the existing card)
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- Route functions stay one-responsibility: validate inputs, fetch / persist via `db.py` helpers, render template (or redirect), done — no inline SQL, no formatting logic that belongs in the template
- The new `create_expense` helper must open and close its own connection (mirror the existing pattern at `database/db.py:92-108`); never return a live `sqlite3.Connection` to the route
- The `user_id` always comes from `session["user_id"]` — never accept it from the form. The route must ignore any `user_id` field that an attacker submits.
- Currency formatting stays INR (₹) per project memory — the amount input uses `₹` only in the hint text and the validation message; the stored value is a plain `Decimal` converted to `float` for SQLite (matches the `REAL` column from Step 1)
- The category list is exactly the 7 categories from Step 1 (`Food`, `Transport`, `Bills`, `Health`, `Entertainment`, `Shopping`, `Other`) — never introduce a new category
- Echo submitted values back to the form on validation failure so the user doesn't lose their typing. Use the raw strings for the inputs (don't round-trip `amount` through `Decimal` and back — pass `amount_raw` through unchanged) and let the canonical valid value take effect only on the success path.
- POST-Redirect-GET: on success the route must `redirect(url_for("profile"))` (HTTP 302), never render the form again. Resubmission on refresh then submits to `/profile`, not `/expenses/add`.
- The `<input type="date" max="...">` `max` is a hint, not a security control — the server must still validate "date not in the future" because clients can override the `max` attribute
- The `+ Add expense` CTA in the profile page is the only meaningful change to `profile.html` — do not touch the transactions table, the categories table, the stats row, or the date filter
- Do not enable the disabled "Edit profile" button — that is still out of scope
- The page heading is "Add an expense" — Pascal-case per the rest of the app's headings ("Spendly", "Welcome back", "Recent transactions", "Spending by category")
- The route exposes a single canonical URL `/expenses/add`; do not introduce an `/expenses/new` alias

## Definition of done
- [ ] `GET /expenses/add` while signed out returns HTTP 302 to `/login`
- [ ] `GET /expenses/add` while signed in returns HTTP 200 and renders the form with `date` prefilled to today's date in `YYYY-MM-DD` format
- [ ] The category select contains exactly the 7 fixed categories from Step 1 (`Food`, `Transport`, `Bills`, `Health`, `Entertainment`, `Shopping`, `Other`)
- [ ] `POST /expenses/add` with valid form data returns HTTP 302 to `/profile`
- [ ] The same POST inserts exactly one row in `expenses` with the signed-in user's `user_id` and the submitted `amount` / `category` / `date` / `description`
- [ ] After the insert, the new expense appears at the top of the recent-transactions table on `/profile` (ordered by `date DESC, id DESC`)
- [ ] The new expense's `Total spent` / `Transactions` / `Top category` stats on `/profile` reflect the new row
- [ ] An empty `amount` re-renders the form with the error "Please enter an amount." and the typed values echoed back
- [ ] A negative, zero, non-numeric, or over-cap `amount` re-renders the form with the amount error
- [ ] A missing or unknown `category` re-renders the form with "Please choose a category."
- [ ] A missing or malformed `date` re-renders the form with "Please enter a valid date."
- [ ] A `date` in the future re-renders the form with "Date cannot be in the future."
- [ ] A `description` over 200 characters re-renders the form with "Description must be 200 characters or fewer."
- [ ] The route ignores any `user_id` field submitted in the form — the inserted row always reflects `session["user_id"]`
- [ ] Two users with non-overlapping expenses: when signed in as user A, only user A's insert lands in user A's data (no leak to user B)
- [ ] The `+ Add expense` CTA on `/profile` navigates to `/expenses/add` and is rendered inside the existing user-info card (no new card, no new layout break)
- [ ] All currency in the new form is rendered with the `₹` symbol in labels and validation messages; the stored amount is a number
- [ ] No hex colour values appear in `templates/add_expense.html` or `static/css/style.css` — only CSS variables
- [ ] Every new SQL string in `database/db.py` uses `?` placeholders — no f-strings or `%` formatting
- [ ] No `sqlite3` import is added to `app.py` outside the existing top-of-file import (DB logic is fully in `db.py`)
- [ ] The disabled "Edit profile" button on `/profile` stays disabled with its existing tooltip
- [ ] All existing tests in `tests/test_profile.py` (Steps 5 + 6) still pass
- [ ] `pytest` passes — the new `tests/test_expenses.py` tests all pass
- [ ] The `add_expense()` route docstring describes the GET / POST split and the validation rules
- [ ] The stub return value at `app.py:380-382` (`return "Add expense — coming in Step 7"`) is gone — the route renders a template on GET and redirects on POST
