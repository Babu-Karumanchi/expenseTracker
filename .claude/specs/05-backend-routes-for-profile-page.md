# Spec: Backend Routes for Profile Page

## Overview
Step 5 wires the existing `/profile` route to live data. The UI was built in Step 4 with hardcoded Python dicts/lists inside the route body; this step replaces those with real queries against the `users` and `expenses` tables so the page reflects the signed-in user's actual account. The route count, URL, auth guard, and `templates/profile.html` layout stay exactly the same — only the data source changes. This unblocks every later expense feature (Step 7 add, Step 8 edit, Step 9 delete) by proving the read path end-to-end against the schema seeded in Step 1.

## Depends on
- Step 1 — Database setup (the `users` and `expenses` tables must exist; `get_db()` and `init_db()`/`seed_db()` must already be wired)
- Step 2 — Registration (the `users` table must be populated by real signups, not only the seed)
- Step 3 — Login + Logout (`session["user_id"]` must be set on protected pages; `/profile` must already redirect to `/login` when signed out)
- Step 4 — Profile Page Design (`templates/profile.html` already exists and consumes `user`, `stats`, `transactions`, `categories`)

## Routes
- `GET /profile` — render the profile page with live DB data for the signed-in user — logged-in only (redirect to `/login` if no session)

No new routes. The endpoint, method, path, and auth behaviour stay exactly as they are after Step 4; only the route body's data source changes.

## Database changes
No database changes. The existing `users` and `expenses` tables (`database/db.py:10-29`) already expose every column the profile page needs:

- `users.id`, `users.name`, `users.email`, `users.created_at` → user-info card
- `expenses.user_id`, `expenses.amount`, `expenses.category`, `expenses.date`, `expenses.description` → stats row, transactions table, category breakdown

`get_db()` already runs `PRAGMA foreign_keys = ON` and sets `row_factory = sqlite3.Row`, so row access via `row["column"]` works out of the box.

## Templates
- **Modify:** `templates/profile.html` — the markup already iterates `stats`, `transactions`, and `categories` and reads `user.name`, `user.email`, `user.member_since`, `user.initial`. No structural change is required. Remove the TODO comment at the top of the file (currently `templates/profile.html:3-5`) that flags the hardcoded data. The "Edit profile" button stays **disabled with its Step 5 tooltip** — wiring it is out of scope for this step.

## Files to change
- `database/db.py` — add three new helper functions, each opening its own `get_db()` connection and returning primitive Python types (dicts, lists, strings, numbers) so the route stays one-responsibility:
  - `get_user_by_id(user_id)` — return a row with `id`, `name`, `email`, `created_at`, or `None` if missing
  - `get_user_expenses(user_id)` — return a list of `expenses` rows for that user, ordered by `date DESC, id DESC` (newest first, stable tiebreaker)
  - `get_user_stats(user_id)` — return a single dict with `total`, `count`, `top_category`, `top_category_total`; return zeros / `None` when the user has no expenses
- `app.py` — rewrite the body of the existing `profile()` view (`app.py:151-215`):
  - Keep the existing auth guard (`app.py:160-161`) exactly as it is
  - Fetch the user row via `get_user_by_id(session["user_id"])`; if it returns `None` (e.g. account deleted between requests), clear the session and redirect to `/login`
  - Fetch expenses via `get_user_expenses(...)` and compute the stats, transactions, and categories lists in pure Python from that result
  - Replace the four hardcoded blocks (`user`, `stats`, `transactions`, `categories` at `app.py:166-207`) with the computed values
  - Update the route docstring (currently `app.py:153-159`) to reflect that the route now reads from the DB
- `tests/test_profile.py` — extend the existing test suite (currently asserts only UI structure on hardcoded data) to cover the DB-backed behaviour:
  - Auth guard still redirects to `/login` when signed out
  - Page renders 200 when signed in
  - User-info card reflects the **actual signed-in user's name and email** (not "Demo User"), including the `Hi, <name>` greeting in the navbar
  - Stats `Total spent` equals the sum of the signed-in user's expenses formatted in INR (e.g. `₹8,148.00` for the seeded demo user)
  - Stats `Transactions` equals the count of that user's expenses
  - Stats `Top category` matches the highest-spend category
  - Transactions table rows match the signed-in user's expenses (count, ordering, dates, amounts)
  - Categories table rows match the per-category totals computed from the user's expenses, sorted high→low
  - **Isolation:** when a second user with their own expenses is added, signed-in as user B the page does **not** leak user A's data
  - **Empty state:** a user with zero expenses still gets a 200, a `₹0.00` total, a `0` transactions count, a `—` top category, and an empty-but-present tables
- `tests/conftest.py` — likely no change needed; the existing autouse `reset_db` fixture already wipes both tables per test. Verify and only add fixtures if the new tests need them (e.g. a factory-style helper to insert a user + expenses in one call).

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug — no auth changes in this step
- Use CSS variables — never hardcode hex values; `style.css` already has the profile-page tokens
- All templates extend `base.html`
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- The new `db.py` helpers must open and close their own connection (mirror the existing pattern at `database/db.py:92-130`); never return a live `sqlite3.Connection` to the route
- Route functions stay one-responsibility: fetch data via `db.py` helpers, render template, done — no inline aggregation, no inline SQL, no formatting logic that belongs in the template
- Currency formatting stays INR (₹) per project memory — use the same `f"₹{amount:,.2f}"` formatting the Step 4 hardcoded strings used so the rendered output is byte-identical for the seeded demo user
- Dates on the profile page stay ISO `YYYY-MM-DD` strings (the `expenses.date` column is already ISO); only convert to a human "Member since" string for the user-info card — `users.created_at` is `YYYY-MM-DD HH:MM:SS` so parse just the year + month
- Per-category percentage in the categories table is `(category_total / grand_total) * 100`, rounded to one decimal place; when `grand_total == 0` (empty-state user) percentages are `0.0`
- The "Edit profile" button stays disabled in this step — wiring it is explicitly out of scope; do not enable it
- Hardcoded blocks in `app.py:166-207` must be removed entirely once the live-data path is in place — no dead-code fallback to the old dicts
- Keep the existing `category_class` mapping used by `templates/profile.html` (e.g. `food`, `transport`, `bills`) — derive it from the expense category with a `.lower()` lookup; do not introduce a new category vocabulary
- The `/profile` route's docstring at `app.py:153-159` must be updated to drop the "hardcoded data (Step 4 — UI only)" wording and the "Step 5 will replace these" promise — this step delivers that promise

## Definition of done
- [ ] Visiting `/profile` while signed in returns HTTP 200 and renders the signed-in user's **actual** name, email, and joined date in the user-info card (not "Demo User")
- [ ] Visiting `/profile` while signed out redirects to `/login`
- [ ] The `Total spent` stat equals the sum of the signed-in user's `expenses.amount` formatted as INR with two decimals (e.g. `₹8,148.00` for the seeded demo user)
- [ ] The `Transactions` stat equals the count of the signed-in user's expenses
- [ ] The `Top category` stat is the category with the highest total spend, with that total in the `meta` slot
- [ ] The recent-transactions table renders one row per expense for the signed-in user, ordered by `date DESC, id DESC`
- [ ] The spending-by-category table renders one row per distinct category with totals, counts, and percentages summing to 100% (or 0% on empty-state), sorted high→low
- [ ] A user with zero expenses still gets HTTP 200, `₹0.00` total, `0` transactions, `—` top category, and empty transactions/categories tables
- [ ] Two users with non-overlapping expenses exist; signed in as user B, the page shows only user B's data — no leak from user A
- [ ] The navbar greeting `Hi, <name>` matches the signed-in user's actual name (not the seeded "Demo User" string when a freshly registered user is signed in)
- [ ] No `sqlite3` import remains in `app.py` outside the existing top-of-file import (DB logic is fully in `db.py`)
- [ ] The four hardcoded blocks (`user`, `stats`, `transactions`, `categories` at the previous `app.py:166-207`) are gone — no dead code
- [ ] Every new SQL string in `database/db.py` uses `?` placeholders — no f-strings or `%` formatting
- [ ] `pytest` passes — existing `test_profile.py` tests still pass and the new DB-backed tests above all pass
- [ ] The TODO Jinja comment at `templates/profile.html:3-5` is removed
- [ ] The `profile()` route docstring at `app.py:153-159` is updated to describe live-data behaviour
- [ ] The "Edit profile" button in `templates/profile.html` remains disabled with its existing Step 5 tooltip (intentionally out of scope)