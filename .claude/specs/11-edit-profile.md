# Spec: Profile Management

## Overview
This feature allows signed-in users to manage their account, specifically updating their profile information (name and email) and deleting their entire account. This provides users with full control over their personal data.

## Depends on
- 03-login-and-logout
- 04-profile-page-design
- 05-backend-routes-for-profile-page

## Routes
- `GET /profile/edit` — Renders the profile edit form with current user data — logged-in
- `POST /profile/edit` — Processes the profile update and redirects back to profile — logged-in
- `GET /profile/delete` — Renders a confirmation page for account deletion — logged-in
- `POST /profile/delete` — Deletes the user and all associated expenses, then redirects to landing — logged-in

## Database changes
No new tables or columns.
New helper functions in `database/db.py`:
- `update_user(user_id, name, email)` — Updates the name and email for the specified user. Returns rowcount.
- `delete_user(user_id)` — Deletes the user row. Since foreign keys are enabled, this should also remove associated expenses if CASCADE is configured, or handled manually.

## Templates
- **Create:**
    - `templates/edit_profile.html` — Standalone page for editing profile info.
    - `templates/delete_profile.html` — Standalone confirmation page for account deletion.
- **Modify:**
    - `templates/profile.html` — Add "Edit Profile" and "Delete Profile" buttons/links to the user info card.

## Files to change
- `app.py` — Add routes for GET/POST `/profile/edit` and GET/POST `/profile/delete`.
- `database/db.py` — Add `update_user` and `delete_user` helpers.
- `templates/profile.html` — Add management links to the user card.

## Files to create
- `templates/edit_profile.html`
- `templates/delete_profile.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `_verify_csrf()` for all POST requests.
- Validate that the name is not empty and email format is valid during edit.
- Handle `sqlite3.IntegrityError` if the new email is already taken.
- Ensure that deleting a user also removes all their expenses to avoid orphaned records.

## Definition of done
- [ ] Clicking "Edit Profile" on the profile page navigates to `/profile/edit`.
- [ ] The edit form is pre-populated with the user's current name and email.
- [ ] Successfully updating the name and email reflects the changes on the profile page.
- [ ] Attempting to save an empty name or invalid email results in a validation error.
- [ ] Attempting to save an existing email results in an "Email already exists" error.
- [ ] Clicking "Delete Profile" on the profile page navigates to `/profile/delete`.
- [ ] Confirming deletion removes the user and all their expenses from the database.
- [ ] After deletion, the user is redirected to the landing page and the session is cleared.
- [ ] POST requests to `/profile/edit` or `/profile/delete` without a valid CSRF token return a 403 error.
