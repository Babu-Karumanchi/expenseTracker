# Spec: Analytics Page

## Overview
Promote the existing `/analytics` route from a "Coming soon" stub into a real, live analytics dashboard for the signed-in user. The page surfaces three visualisations of the user's existing expense data, each filterable by the same date presets already wired up on `/profile` (All Time / This Month / Last 3 Months / Last 6 Months) so the dashboard never shows "all of history" by surprise:

1. **Monthly trend** — total spent per month, displayed as a vertical bar chart (last 12 months, oldest → newest). Months with zero spend are rendered as empty bars so the cadence is preserved.
2. **Category breakdown** — share of spend by category, displayed as a horizontal bar list (high → low). Reuses the same percentage-bar visual already proven on `/profile` so users recognise it.
3. **Day-of-week breakdown** — average spend per weekday (Mon → Sun), displayed as a horizontal bar list. Highlights the user's biggest-spending day of the week.

A small KPI strip at the top echoes the user's lifetime **Total spent**, **Transactions**, **Average per transaction**, and **Top category** so the page reads at a glance even before the charts. Empty state (user has zero expenses) renders a friendly message and a link to `/profile` to add one — never an empty chart with no explanation.

The route reuses the existing `get_user_expenses(user_id, date_from, date_to)` and `get_user_stats(user_id, date_from, date_to)` helpers plus one new read helper (`get_user_expenses_for_analytics`) that returns the same rows with **no `date_to` upper bound** so the chart can bucket the trailing 12 months even when the user picks "All Time". Auth is required (signed-in only) — a signed-out GET 302s to `/login` before any DB call.

Charts are rendered with **inline SVG** (vanilla JS, no chart library). The project memory forbids new npm packages and CLAUDE.md forbids JS frameworks — Chart.js / D3 / Plotly / Recharts are all out. Inline SVG keeps the page dependency-free, server-renderable, and consistent with the rest of Spendly's vanilla stack.

## Depends on
- Step 1 — Database setup (`expenses` table; `expenses.user_id` is the FK scope for every read)
- Step 3 — Login + Logout (session guard; signed-in only)
- Step 4 — Profile Page Design (stat-card + bar-list visual language carried over)
- Step 5 — Backend Routes for Profile Page (`get_user_expenses`, `get_user_stats` are reused for the KPI strip)
- Step 6 — Date Filter on Profile (the same preset bounds (`this_month` / `last_3_months` / `last_6_months`) drive the chart filters; `_add_months` is reused for "Last 12 months" bucketing)

## Routes
- `GET /analytics` — auth guard (302 → `/login` if not signed in); parse `?preset=` against the same `PRESETS` list used by `/profile`; build the analytics payload via DB helpers; render `templates/analytics.html`. The page is **read-only** — no POST handler, no form, no modal. There is no JSON endpoint because the entire dashboard is server-rendered on every request.

No new routes beyond the existing stub being converted from a placeholder to a real dashboard.

## Database changes
No schema changes. The `expenses` table already carries every column this step needs (Step 1). **Two** new read helpers in `database/db.py`:

1. `get_user_expenses_for_analytics(user_id, date_from)` — returns all of the user's expenses with `date >= date_from`, sorted `date ASC, id ASC` so the chart can iterate oldest → newest without an in-Python resort. Mirrors `get_user_expenses(...)` but takes a single lower bound (no upper bound) so the trailing-12-month bucketing works for the "All Time" preset. Owner-scoped via `WHERE user_id = ?`.
2. (Optional) `get_monthly_totals(user_id, months=12)` — aggregates `strftime('%Y-%m', date) AS month, SUM(amount) AS total, COUNT(*) AS cnt` grouped by month, scoped to the last `months` months ending today. Implemented in `database/db.py` per CLAUDE.md ("DB queries belong in `database/db.py` only"). If this step defers the bucketing to Python (a `defaultdict` over the rows from helper 1), drop this entry — it is optional based on whichever path the implementation chooses.

The category and day-of-week breakdowns are derived in Python from the rows returned by helper 1 (the `category` and `date` columns are already on every row), matching the existing pattern on `/profile`. No additional SQL queries needed for those.

## Templates
- **Replace:** `templates/analytics.html` — the stub markup (`.analytics-badge` / `.analytics-title` / `.analytics-subtitle` / `.analytics-meta`) is replaced with a real dashboard:
  1. KPI strip — 4 stat cards: Total spent / Transactions / Average per transaction / Top category.
  2. Preset pill row — same `profile-presets` / `profile-pill` markup already on `/profile`, so the date-filter pattern is consistent across pages. `?preset=all_time` is the default; explicit `?preset=this_month` / `last_3_months` / `last_6_months` narrow the KPI strip only (the trailing-12-month bar chart is **always** 12 months, regardless of the preset — see Rules for implementation below).
  3. Monthly trend — server-rendered inline-SVG bar chart, fixed to the trailing 12 months ending today. Months are bucketed oldest → newest; the highest month sets the y-axis; empty months render as 1px-wide markers.
  4. Category breakdown — horizontal bar list (high → low), same `.profile-category-list` / `.profile-category-row` / `.profile-category-fill` markup used on `/profile`. Each row has the category chip, total, count, and a thin percentage bar.
  5. Day-of-week breakdown — horizontal bar list (Mon → Sun) showing the average spend per weekday, with the highest day highlighted (the same `.profile-category-fill--food` accent colour or `--accent` works).
  6. Empty state — when the user has zero expenses (KPI count is 0), the three breakdown blocks are replaced by a single card with "No expenses yet — add your first one from /profile" and a link to `/profile`.

## Files to change
- `app.py` — convert `analytics()` from a stub into a real handler. Parse `?preset=` against the existing `PRESETS` list (same parse logic as `/profile`); compute the trailing-12-month window from `_today()`; build the monthly / category / day-of-week payloads via DB helpers; render `analytics.html` with all six sections (or the empty state).
- `database/db.py` — add `get_user_expenses_for_analytics(user_id, date_from)` (helper 1 above). Optionally add `get_monthly_totals(user_id, months=12)` (helper 2 above) — pick whichever the implementation finds cleaner.
- `static/css/analytics.css` — append KPI card grid, the inline-SVG bar chart container, the bar list rows for category + day-of-week breakdowns, and the empty-state card. All new rules reuse existing CSS variables — no new hex values.
- `.claude/specs/06-date-filter-profile.md` — add a brief note that the `?preset=...` query param is now also consumed by `/analytics`.

## Files to create
- `tests/test_10_analytics_page.py` — covers: signed-out redirect (302 → `/login`), signed-in GET (200 + dashboard markup), preset parsing (`?preset=last_3_months` narrows the KPI strip), empty state (no expenses → empty card, not the chart), monthly-bucket shape (12 buckets oldest → newest, zero-filled), category-bucket shape (one row per used category, sorted high → low), day-of-week-bucket shape (7 rows Mon → Sun, averages not totals), and currency formatting (₹ with two decimals, INR per project memory).
- `tests/test_db_helpers.py` — add a section for `get_user_expenses_for_analytics` (owner-scoped read, `date ASC` ordering, lower-bound filtering). If `get_monthly_totals` is added, cover the bucketing there too.

## New dependencies
No new dependencies. No pip packages, no JS libraries, no CSS frameworks, no chart libraries. The bar chart is **inline SVG**, server-rendered in the Jinja template — the same template renders the same SVG on every visit, no client-side JS to redraw. The day-of-week bars and category bars reuse the existing `.profile-category-fill` styling. The vanilla-JS `static/js/main.js` needs **no changes** — there are no modals, no AJAX, no fetch handlers on this page.

## Rules for implementation
- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`
- All SQL must use parameterised queries (`?` placeholders) — never f-strings or `%` formatting in SQL
- Use CSS variables — never hardcode hex values in `analytics.css`; reuse the existing tokens from `style.css`
- All templates extend `base.html`
- DB logic stays in `database/db.py` — no `sqlite3` calls in route functions, period
- Route functions stay one-responsibility: parse inputs, fetch via `db.py` helpers, build the analytics payload in Python, render template, done
- The `user_id` always comes from `session["user_id"]` — never accept it from the form or query string
- **No JS frameworks, no npm packages.** Inline SVG only. `static/js/main.js` is untouched.
- **The monthly bar chart is always 12 months, regardless of the `?preset=` filter.** The preset narrows the KPI strip + the category/day-of-week breakdowns only. Rationale: a 12-month trend is the whole point of an analytics page; showing "this month" as a single bar would be a useless chart. The 12-month window ends at `_today()` so it stays current.
- **Empty state is a first-class outcome, not a fallback.** When the user has zero expenses, render the empty card instead of an empty chart with no explanation. The chart must NEVER render without context.
- **Currency formatting stays INR (₹)** per project memory. All totals use `f"₹{n:,.2f}"` exactly as on `/profile`. No ₹0.00 fallbacks for empty data — when count is 0, the empty state takes over.
- **Day-of-week bucketing uses Mon → Sun, not Sun → Sat.** Matches `calendar.weekday()` (Mon=0) so the order is the ISO standard and the labels render Monday / Tuesday / … / Sunday.
- **Categories render in the user's preferred language order** — high → low by total, with the percentage bar carrying the share (same convention as `/profile`). Empty categories are dropped (only categories with at least one expense appear).
- The app runs on **port 5001**, not the Flask default 5000
- FK enforcement is manual — `get_db()` runs `PRAGMA foreign_keys = ON` on every connection

## Definition of done
- Visiting `/analytics` while signed out returns 302 to `/login` (no DB call, no template render)
- Visiting `/analytics` while signed in with at least one expense returns 200 and renders all six sections: KPI strip, preset pill row, monthly trend, category breakdown, day-of-week breakdown
- The KPI strip echoes Total spent / Transactions / Average per transaction / Top category — values match the same user on `/profile` (same DB, same helpers)
- Average per transaction is `total / count`, formatted as `₹<n>:,.2f`; shows "—" when count is 0 (covered by the empty state, but the field stays present in the markup for the empty branch)
- Top category shows the category name and `₹<n>:,.2f` of its share; shows "—" when no expenses
- The preset pill row highlights the active preset (`?preset=last_3_months` highlights "Last 3 Months"); clicking a pill navigates to `/analytics?preset=<id>`
- `?preset=all_time` is the default when no param is supplied — the pill row highlights "All Time", KPI strip shows lifetime totals
- `?preset=last_3_months` narrows the KPI strip and the breakdowns to the trailing 3 months; the monthly chart still shows 12 months
- `?preset=invalid_value` falls back to `all_time` (no error envelope, no 4xx — bad input is dropped with the pill row highlighting "All Time")
- The monthly trend is a server-rendered inline SVG bar chart with exactly 12 bars, ordered oldest → newest, ending at the current month
- Months with zero spend render as a 1px-wide marker so the cadence is preserved; months with spend render as a bar whose height is `total / max_month_total * chart_height`
- Empty months never render as "0" labels — the chart has no per-month value labels to avoid clutter
- The category breakdown has one row per used category, sorted high → low by total, with the percentage bar showing each row's share of the total
- The day-of-week breakdown has exactly 7 rows, ordered Monday → Sunday, each showing the average spend on that weekday (total / number of weeks that weekday occurs in the window — never a raw sum)
- The highest-spending day of the week is highlighted (accent border or fill) so the user spots their biggest-spending day at a glance
- Visiting `/analytics` with zero expenses renders the empty-state card with the copy "No expenses yet — add your first one from /profile" and a link to `/profile`; the three breakdown blocks are NOT rendered
- The empty-state card NEVER renders the bar chart, even an empty one
- Currency is INR (₹) throughout — totals use `f"₹{n:,.2f}"`, no `$`, no `USD`
- All SQL strings in `database/db.py` use `?` placeholders
- `static/js/main.js` is UNCHANGED — no new file, no edits, no client-side rendering
- No new pip packages, no new JS libraries, no new CSS frameworks
- All existing tests (Step 1, 2, 3, 4, 5, 6, 7, 8, 9) still pass
