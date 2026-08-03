# Spec: Login and Logout

## Overview

Close out the authentication loop by turning the remaining stub
`GET /logout` route into a real signed-out flow that clears the
Flask session and redirects the user back to the landing page,
and by surfacing a signed-in header on every page so users always
have a visible way to sign out. The login side of the flow
(`GET/POST /login`, password verification, session creation) is
already implemented and out of scope for this step — only the
**logout** half plus the nav/state changes that make logout
discoverable need new work. This step unblocks every later
authenticated feature (profile, expenses) by ensuring users have a
working way to end their session.

## Depends on

- Step 2 — Registration (the `users` table is populated, `session`
  carries `user_id` and `user_name`, `app.secret_key` is set, and
  `verify_password` plus `get_user_by_email` exist in
  `database/db.py`).

## Routes

- `POST /logout` — clear the session and redirect to the landing
  page — public (no auth required to log out)
- `GET /logout` — redirect to the landing page (GET-based logout
  is unsafe; degrade gracefully) — public

No new routes beyond the `logout` endpoint. `GET/POST /login` are
already implemented and stay as-is.

## Database changes

No database changes. All required columns (`id`, `name`,
`password_hash`) already exist in the `users` table.

## Templates

- **Modify:** `templates/base.html` — the navbar must reflect the
  signed-in state. When `session.user_id` is present, show the
  user's name plus a `Sign out` link that points to
  `url_for('logout')`. When it is absent, keep the current
  `Sign in` and `Get started` links. All links must use
  `url_for()` — no hardcoded paths.
- **Modify:** `templates/login.html` — already correct, no
  functional change required. If anything, ensure the post-logout
  message can be displayed if a `?logged_out=1` query string is
  passed (see Rules).

## Files to change

- `app.py` — replace the `logout()` stub with a real handler.
  Accept both `GET` and `POST` (the navbar uses a link, not a
  form, so `GET` is necessary for usability — but document the
  CSRF caveat in a comment). Clear the session and redirect to
  `url_for('landing')`.
- `templates/base.html` — branch the navbar links on
  `session.user_id`.

## Files to create

None.

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs — keep using `sqlite3` directly via
  `get_db()`.
- All SQL must use parameterized queries (`?` placeholders). Never
  build queries with f-strings or `%` formatting.
- `logout` must call `session.clear()` before redirecting — do not
  just pop individual keys, in case future fields are added.
- The redirect target for successful logout is `url_for('landing')`,
  not `/`. Use the helper, never a hardcoded path.
- Accepting `GET /logout` is a deliberate usability choice for a
  single-user personal tracker. Add a one-line comment in `app.py`
  acknowledging the CSRF trade-off so it is not silently copied
  into a multi-user context.
- The navbar in `base.html` must use a Jinja `{% if %}` /
  `{% else %}` block to render signed-in vs signed-out links. Do
  not duplicate the `<nav>` element per template.
- All sample/placeholder text uses ₹ (INR) per project memory.
- Page-specific styles go in `static/css/style.css` — no inline
  `<style>` blocks in templates, and no hardcoded hex values in
  CSS — use the existing CSS variables.
- DB logic stays in `database/db.py`. Do not call `sqlite3` from
  the new `logout()` body; it needs no DB access.
- All templates extend `base.html`. Internal links use `url_for()`.

## Definition of done

- [ ] `GET /logout` clears the session and redirects to
      `url_for('landing')` — verify by visiting any page first to
      establish a session, then clicking the new `Sign out` link in
      the navbar.
- [ ] `POST /logout` behaves identically to `GET /logout` (both
      clear the session and redirect to the landing page).
- [ ] After logout, visiting `/profile` either redirects to
      `/login` or returns a 401-style message — the protected page
      must not render with stale session data. (Profile is still a
      stub; this is a manual smoke check, not a route contract.)
- [ ] When signed in (`session.user_id` set), the navbar shows the
      user's name and a `Sign out` link; when signed out, it shows
      `Sign in` and `Get started` as today.
- [ ] The `Sign out` link uses `url_for('logout')` — grep the
      codebase for hardcoded `/logout` and confirm there are none
      in templates.
- [ ] `logout` in `app.py` calls `session.clear()` exactly once and
      does not query the database.
- [ ] No SQL string in the touched files contains an f-string or
      `%` — every query uses `?` placeholders (none expected in
      this step, but the rule still applies).
- [ ] `base.html` extends no inline `<style>` tags and uses only
      CSS variables for any new colours.
- [ ] `pytest` passes — add at least one new test covering the
      happy-path logout (clear session, redirect to landing).