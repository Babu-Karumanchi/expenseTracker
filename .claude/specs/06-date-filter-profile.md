# Spec: Date Filter on Profile

## Overview
The profile page currently shows every expense the signed-in user has ever recorded ($n$ transactions, $n$ categories). With any real usage the table quickly becomes unwieldy, and the "Total spent" / "Transactions" / "Top category" stats lose meaning when they span months of activity. This step adds a **date-range filter** (From / To) above the recent-transactions table so the user can narrow both the table and the summary stats to a chosen window. The filter is driven by query-string parameters on `GET /profile`, so any range is bookmarkable and shareable. The spending-by-category table always reflects the **same** filtered window as the transactions table, so the two views stay consistent.

## Depends on
- Step 1 — Database setup (the `expenses` table with `user_id`, `date`, `amount`, `category` columns must exist)
- Step 2 — Registration (user accounts must exist)
- Step 3 — Login + Logout (session must be set; `/profile` must be a protected route)
- Step 4 — Profile Page Design (`templates/profile.html` exists with the four sections)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses(...)` and `get_user_stats(...)` exist; the route already reads from the DB)

## Routes
- `GET /profile?from=YYYY-MM-DD&to=YYYY-MM-DD` — render the profile page filtered to expenses whose `date` falls in `[from, to]` (inclusive), open-ended on either side when only one bound is supplied — logged-in only (redirect to `/login` if not authenticated)

No new routes. The endpoint, method, auth guard, and template stay exactly as they are after Step 5; only the query behaviour and the data passed to the template change.

## Database changes
No database changes. The existing `expenses` table (`database/db.py:19-28`) already carries the `date TEXT` column (`YYYY-MM-DD`) this filter needs. The `BETWEEN` predicate is added to the existing `SELECT` in `get_user_expenses(...)` and the `SUM` / `COUNT` aggregates in `get_user_stats(...)`; both already use parameterised `?` placeholders.

## Templates
- **Modify:** `templates/profile.html`
  - Add a **filter bar** directly above the `.profile-tables-row` div (i.e. between the `.profile-stats` row and the two-card row). The bar contains:
    - A `<form method="get" action="{{ url_for('profile') }}">` with two `<input type="date">` fields (`from`, `to`) and two buttons (`Apply`, `Clear`)
    - The `Apply` button submits the form; the `Clear` button is a plain link styled as a button that points to `url_for('profile')` (no query string) — no JS required
    - Both inputs are pre-filled with the current `filter.from` / `filter.to` values from the route context (empty string when not set)
    - A short inline status line below the form: `"Showing N transactions from {from} to {to}"` when a filter is active; `"Showing all N transactions"` when no filter is active
  - No other markup changes. The four existing sections (user-info card, stats, transactions table, categories table) keep their IDs and classes; the route only changes the data list passed to `transactions` and the four values in `stats`, plus a new `filter` dict and the `filtered_count` it needs to show in the status line.

## Files to change
- `database/db.py` — extend two existing helpers and add one coordinator:
  - `get_user_expenses(user_id, date_from=None, date_to=None)` — accept two optional ISO date strings. When given, filter `WHERE user_id = ? AND date BETWEEN ? AND ?` (or a single bound on either side). When both are `None`, the existing `WHERE user_id = ?` query is used. Final `ORDER BY date DESC, id DESC` is unchanged. Always returns a list of rows.
  - `get_user_stats(user_id, date_from=None, date_to=None)` — same optional bounds; the `SUM` / `COUNT` aggregates and the "top category" subquery both gain the same `BETWEEN` clause (or single bound) so the stats reflect the filtered subset only.
  - Add one new helper (kept in `db.py` per the "no DB logic in routes" rule):
    - `filter_user_expenses(user_id, date_from=None, date_to=None)` — a thin coordinator that calls `get_user_expenses` with the bounds and returns the list. (Optional — implementations may call `get_user_expenses` directly from the route instead. Either is acceptable; the helper is preferred when the route would otherwise reproduce the same argument plumbing.)
  - **Backwards compatibility:** every existing call site of `get_user_expenses` / `get_user_stats` is called with no extra arguments, so the spec'd default of `None` keeps Step 5 unbroken.
- `app.py` — rewrite the body of the `profile()` view (`app.py:155-256`):
  - Read `request.args.get("from", "").strip()` and `request.args.get("to", "").strip()` into local strings. Empty string → `None` for the DB helper.
  - **Validate** the inputs (cheap, route-level — not DB level):
    - Both must be either empty or match `^\d{4}-\d{2}-\d{2}$`. Anything else is rejected with a flash-style inline error: re-render the page with `filter_error="Please enter valid dates (YYYY-MM-DD)."` and ignore the offending value(s). The non-offending bound (if any) is still applied.
    - If both are present and `from > to`, set `filter_error="From date cannot be after To date."` and swap them so the query still returns useful data — the page shows the swap, not an empty result.
  - Pass the validated bounds to `get_user_expenses(...)` and `get_user_stats(...)` so the transactions table, the stats row, and the categories table all reflect the same window.
  - Compute a new `filter` dict passed to the template: `{"from": from_str, "to": to_str, "is_active": from_str or to_str}`. The `transactions` list and the `stats` row `Total spent` / `Transactions` / `Top category` are computed from the **filtered** result, exactly as today but over the filtered rows.
  - The `filtered_count` is `len(expense_rows)` (the filtered count, not the unfiltered total). It is rendered in the status line.
  - Update the route docstring (`app.py:157-164`) to describe the filter behaviour and the `from` / `to` query parameters.
- `static/css/style.css` — add minimal classes for the new filter bar. **Use CSS variables already in the file** (the existing `--color-*` / `--space-*` / `--radius-*` tokens); no new hex values. Required classes:
  - `.profile-filter` — wrapper form, flex row on desktop, stacked on the existing narrow-screen breakpoint
  - `.profile-filter-field` — label + input group
  - `.profile-filter-input` — the date input itself
  - `.profile-filter-actions` — buttons row
  - `.profile-filter-status` — the status / error line (uses the existing `--color-text-muted` for the default state and `--color-danger` for the error variant via a `--danger` modifier)
- `tests/test_profile.py` — extend the existing suite (which currently asserts Step 5 live-data behaviour) to cover the filter:
  - Helper: a factory-style fixture (or test-local helper) that seeds a user with expenses spread across at least three distinct dates (e.g. 2026-01-15, 2026-04-15, 2026-08-15) so a window can isolate one of them.
  - `?from=2026-04-01&to=2026-08-31` returns only the rows in that window; stats reflect the filtered subset, not the unfiltered total.
  - `?from=2026-04-01` (no `to`) returns the row on 2026-04-15 **and** the row on 2026-08-15 (open-ended upper bound).
  - `?to=2026-04-30` (no `from`) returns the row on 2026-01-15 **and** the row on 2026-04-15 (open-ended lower bound).
  - No filter parameters → behaviour is identical to Step 5 (existing tests continue to pass).
  - Invalid date (`?from=not-a-date`) renders HTTP 200, ignores the bad value, and shows the inline error but does **not** crash.
  - `from > to` renders HTTP 200, swaps the bounds, and shows the swap message in the status line.
  - The navbar greeting and the signed-in user's identity are unaffected by the filter (smoke check).
  - Two users with non-overlapping expenses still do not leak across users when a filter is active.

## Files to create
None. All changes are modifications to existing files.

## New dependencies
No new dependencies. The plain `<input type="date">` ships with all modern browsers — no JS, no polyfill, no extra CSS framework.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL, even when building the `BETWEEN` clause dynamically
- Passwords hashed with werkzeug — no auth changes in this step
- Use CSS variables — never hardcode hex values; reuse the tokens already in `static/css/style.css`
- All templates extend `base.html` (unchanged)
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- The `BETWEEN` predicate (or its single-bound variant) is built with a small list of conditions that are joined with `AND`; the placeholders are derived from the length of that list so adding/removing a bound doesn't drift from the value tuple
- Route functions stay one-responsibility: validate inputs, fetch data via `db.py` helpers, build the template context, render template, done — no inline SQL, no formatting logic that belongs in the template
- Currency formatting stays INR (₹) per project memory — use the same `f"₹{amount:,.2f}"` formatting the Step 5 route already uses
- Dates stay ISO `YYYY-MM-DD` strings (the `expenses.date` column is already ISO); the filter inputs are `<input type="date">` so the browser handles the ISO conversion for free
- The status line must read in plain English ("Showing N transactions from 2026-04-01 to 2026-08-31", "Showing all 8 transactions", "Showing 2 transactions from 2026-04-01") — no jargon, no internal field names
- The two `<input type="date">` values submitted are the **raw** strings from the form; the route does not add `:00` suffixes or timezone shifts
- The "Edit profile" button stays disabled in this step — wiring it is explicitly out of scope; do not enable it
- The filter form uses `method="get"` and the canonical `action="{{ url_for('profile') }}"` so the resulting URL is always `/profile?from=...&to=...` with no surprises
- The `Clear` control is a plain `<a class="btn-ghost" href="{{ url_for('profile') }}">` — not a button that submits the form, so it doesn't accidentally carry the current values along

## Definition of done
- [ ] `GET /profile` (no query string) shows every transaction and the stats reflect the full history — identical to Step 5 behaviour
- [ ] `GET /profile?from=2026-08-01&to=2026-08-31` shows only expenses whose `date` is in that range (inclusive), and the stats row across the page reflects the **filtered** subset
- [ ] `GET /profile?from=2026-08-01` (no `to`) is open-ended on the upper side and includes every expense on or after 2026-08-01
- [ ] `GET /profile?to=2026-08-31` (no `from`) is open-ended on the lower side and includes every expense on or before 2026-08-31
- [ ] `GET /profile?from=2026-08-31&to=2026-08-01` (from > to) renders HTTP 200, swaps the bounds, and shows the swap message in the status line
- [ ] `GET /profile?from=not-a-date` renders HTTP 200, ignores the bad value, and shows the inline error
- [ ] Both `<input type="date">` fields are pre-filled with the current `from` / `to` query values when present
- [ ] The `Clear` link returns to `/profile` with no query string and restores the full-history view
- [ ] The transactions table and the spending-by-category table always reflect the **same** filtered window — they never disagree
- [ ] The "Edit profile" button remains disabled with its existing Step 5 tooltip
- [ ] All currency is formatted as INR (₹) with two decimals, matching the rest of the app
- [ ] No hex colour values appear in `templates/profile.html` or `static/css/style.css` — only CSS variables
- [ ] Every new SQL string in `database/db.py` uses `?` placeholders — no f-strings or `%` formatting
- [ ] `pytest` passes — existing Step 5 tests continue to pass and the new filter tests above all pass
- [ ] The `profile()` route docstring at `app.py:157-164` is updated to describe the filter behaviour
