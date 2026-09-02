
# Spec: Budget Management

## Overview
Budget Management introduces the ability for users to set a monthly spending limit. This feature transforms Spendly from a passive tracker into an active financial tool, allowing users to plan their spending and receive visual feedback on their budget adherence for the current calendar month.

## Depends on
- 07-add-expense
- 10-analytics-page

## Routes
- `GET /budget` — View current budget and monthly spending progress — logged-in
- `POST /budget` — Set or update the monthly budget amount — logged-in

## Database changes
Create a `budgets` table to store the monthly limit for each user:
- `user_id` INTEGER PRIMARY KEY, FOREIGN KEY (user_id) REFERENCES users(id)
- `amount` REAL NOT NULL
- `updated_at` TEXT DEFAULT (datetime('now'))

## Templates
- **Create:** `templates/budget.html` — Budget management interface with progress visualization.
- **Modify:** `templates/base.html` — Add "Budget" link to the navigation bar.
- **Modify:** `templates/profile.html` — Add a high-level budget status indicator (e.g., "X% of budget spent") to the stats row.

## Files to change
- `app.py` — Implement budget routes and logic.
- `database/db.py` — Add helpers for creating, updating, and retrieving budgets.
- `templates/base.html`
- `templates/profile.html`

## Files to create
- `templates/budget.html`
- `static/css/budget.css`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`

## Definition of done
- [ ] User can access the `/budget` page while logged in.
- [ ] User can set a monthly budget amount via a form on the `/budget` page.
- [ ] Budget is persisted in the `budgets` table and linked to the current user.
- [ ] The `/budget` page calculates the total spending for the current calendar month.
- [ ] A visual progress bar on the `/budget` page correctly shows the ratio of current spending to the budget.
- [ ] The progress bar changes color based on the spending percentage:
    - Green: < 70%
    - Yellow: 70% - 90%
    - Red: > 90%
- [ ] The `/profile` page displays a summary of the budget status (e.g., "₹1,200 of ₹5,000 spent").
- [ ] Budget settings are private to the logged-in user.
---
