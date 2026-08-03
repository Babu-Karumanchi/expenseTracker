# Spec: Registration

## Overview

Replace the stub `GET /register` route with a working registration flow that
lets a new user create a Spendly account. The route must accept `POST` with
`name`, `email`, and `password`, validate the input, hash the password with
`werkzeug`, insert a new row into the `users` table, and establish a logged-in
session. On success, the user is redirected to the (currently stubbed) profile
page. This is the entry point for authentication and unblocks every later
authenticated feature (expenses, profile, logout).

## Depends on

- Step 1 — Database setup (`users` table exists, `get_db()` is wired with FK
  enforcement and `Row` factory, `werkzeug` is installed).

## Routes

- `GET /register` — render the registration form — public
- `POST /register` — validate input, create the user, log them in — public

If the existing `GET /register` stub in `app.py` currently returns the rendered
template, keep that behaviour and add the `POST` handler. There is no separate
JSON API — this is form-encoded submission only.

## Database changes

No database changes. The `users` table from Step 1 already has the required
columns (`id`, `name`, `email`, `password_hash`, `created_at`) and a `UNIQUE`
constraint on `email`. The only new code is the query that uses it.

## Templates

- **Modify:** `templates/register.html` — convert the static page into a
  real form. Must `extend base.html`, post to `url_for('register')`, render
  the three fields (`name`, `email`, `password`) with `name` attributes that
  match what `request.form` will return, and display an error message block
  when validation fails. Keep existing copy and layout.

## Files to change

- `app.py` — convert the `register()` view into a dual `GET`/`POST` handler;
  add session handling (see Rules); import `request`, `redirect`, `url_for`,
  `session` from `flask`, `generate_password_hash` from `werkzeug.security`,
  and `get_db` from `database.db`. Set a `SECRET_KEY` on the Flask app so
  `session` works.
- `templates/register.html` — wire the form to the new `POST` handler.

## Files to create

- None.

## New dependencies

No new dependencies. `werkzeug.security.generate_password_hash` is already
available via the installed `werkzeug` package, and `flask.session` is part
of Flask core.

## Rules for implementation

- No SQLAlchemy or ORMs — keep using `sqlite3` directly via `get_db()`.
- All SQL must use parameterized queries (`?` placeholders). Never build
  queries with f-strings or `%` formatting.
- Hash passwords with `werkzeug.security.generate_password_hash` only. Never
  store plaintext passwords, even in logs or flash messages.
- Treat duplicate-email insertion as a validation error, not a 500. Catch
  `sqlite3.IntegrityError` from the `UNIQUE` constraint and re-render the
  form with a user-facing message like "An account with that email already
  exists."
- Validate input on the server: `name` non-empty, `email` matches a basic
  email pattern and is non-empty, `password` is at least 6 characters. On
  failure, re-render the form with the previously entered values and a
  single error message — do not silently redirect.
- On successful registration: insert the user, then log them in by setting
  `session['user_id']` to the new row's `id` and `session['user_name']` to
  their name, then `redirect(url_for('profile'))`.
- Set `app.secret_key` to a stable value in `app.py` (e.g. read from an env
  var with a hard-coded fallback for development). Do not check in a real
  production secret.
- All templates `extend base.html`. Use `url_for('register')` for the form
  action — no hardcoded `/register` paths.
- All sample/placeholder text and totals use ₹ (INR) per project memory.
- Page-specific styles go in `static/css/style.css` (or a new dedicated
  file) — no inline `<style>` blocks in templates, and no hardcoded hex
  values in CSS — use the existing CSS variables.
- DB logic stays in `database/db.py`. If a new helper is needed (e.g.
  `create_user`), add it there; do not call `sqlite3` from route bodies.

## Definition of done

- [ ] `GET /register` renders the form with `name`, `email`, and `password`
      fields, all inside a `<form method="post" action="{{ url_for('register') }}">`.
- [ ] Submitting the form with all three fields valid creates a new row in
      `users`, with a `password_hash` produced by `generate_password_hash`
      (verify by reading the row — the stored value must not equal the
      submitted password).
- [ ] After successful registration, the browser is redirected to `/profile`
      and `flask.session` contains the new `user_id`.
- [ ] Submitting the form with an empty `name`, invalid `email`, or a
      `password` shorter than 6 characters re-renders the form with an
      error message and the previously entered values still populated.
- [ ] Submitting a second registration for an email that already exists
      re-renders the form with a duplicate-email error and does not crash
      with a 500.
- [ ] No SQL string contains an f-string or `%` — every query uses `?`
      placeholders.
- [ ] `app.secret_key` is set and the app starts without `RuntimeError`
      about the secret key.
- [ ] `register.html` extends `base.html` and contains no inline `<style>`
      tags.
- [ ] `pytest` passes (any pre-existing tests still green; add at least one
      new test covering the happy-path registration).
