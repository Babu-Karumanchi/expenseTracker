# Spec: Income and Savings Tracking

## Overview
Income and Savings Tracking expands Spendly from a simple expense tracker into a comprehensive personal finance tool. By allowing users to track multiple income sources, the application can calculate total income and expenses to provide a complete view of their financial health. This makes analytics significantly more useful by enabling the calculation of net savings and the savings rate, while also tracking progress toward future goals.

## Depends on
- 12-budget-management

## Routes
- `GET /income` — List all income entries — logged-in
- `GET /income/add` — Form to add new income — logged-in
- `POST /income/add` — Process adding income — logged-in
- `GET /income/<id>/edit` — Form to edit income entry — logged-in
- `POST /income/<id>/edit` — Process editing income entry — logged-in
- `GET /income/<id>/delete` — Delete income entry — logged-in
- `GET /savings` — List savings goals and progress — logged-in
- `GET /savings/add` — Form to create a new savings goal — logged-in
- `POST /savings/add` — Process creating a savings goal — logged-in
- `POST /savings/<id>/add` — Add funds to a specific savings goal — logged-in
- `GET /savings/<id>/delete` — Delete a savings goal — logged-in

## Database changes
- **New Table `income`**:
  - `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
  - `user_id` (INTEGER, FOREIGN KEY to `users.id`)
  - `amount` (REAL, NOT NULL)
  - `source` (TEXT, NOT NULL)
  - `category` (TEXT)
  - `date` (TEXT, NOT NULL)
- **New Table `savings_goals`**:
  - `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
  - `user_id` (INTEGER, FOREIGN KEY to `users.id`)
  - `goal_name` (TEXT, NOT NULL)
  - `target_amount` (REAL, NOT NULL)
  - `current_amount` (REAL, DEFAULT 0.0)
  - `deadline` (TEXT)

## Templates
- **Create:**
  - `templates/income_list.html` — Dashboard for all income records.
  - `templates/income_form.html` — Form for adding and editing income.
  - `templates/savings_list.html` — View of all savings goals with progress bars.
  - `templates/savings_form.html` — Form for creating new savings goals.
- **Modify:**
  - `templates/analytics.html` — Add a financial summary dashboard displaying:
    - Total Income
    - Total Expenses
    - Total Savings (Income - Expenses)
    - Savings Rate ((Savings / Income) * 100)%
    - Comparison charts/summaries.
  - `templates/profile.html` — Display total net balance (Total Income - Total Expenses - Total Savings).

## Files to change
- `app.py`
- `database/db.py`
- `templates/analytics.html`
- `templates/profile.html`

## Files to create
- `templates/income_list.html`
- `templates/income_form.html`
- `templates/savings_list.html`
- `templates/savings_form.html`
- `static/css/income_savings.css`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Ensure `PRAGMA foreign_keys = ON` is used for the new tables.

## Definition of done
- [ ] User can add, edit, and delete income entries from multiple sources.
- [ ] User can create savings goals and add money to them.
- [ ] The savings list shows a progress percentage for each goal.
- [ ] The analytics dashboard correctly calculates and displays:
  - Total Income
  - Total Expenses
  - Total Savings
  - Savings Rate (%)
- [ ] The profile page correctly calculates and displays the total net balance.
- [ ] The analytics page reflects income and savings data alongside expenses.
- [ ] All new routes are protected by the `logged_in` requirement.
