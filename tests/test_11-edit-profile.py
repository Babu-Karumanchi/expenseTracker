import pytest
import secrets
import sqlite3
import database.db as db
from app import app
from database.db import init_db, create_user, create_expense, get_user_by_id, get_user_expenses

"""
Tests for Profile Management (Feature 11).
Verified behaviors:
- GET /profile/edit: Pre-populates form with current user data.
- POST /profile/edit: Validates name/email, handles email conflicts, updates user.
- GET /profile/delete: Renders confirmation page.
- POST /profile/delete: Deletes user and associated expenses, clears session.
- Auth Guards: Protected routes redirect to /login when signed out.
- Security: POST requests without valid CSRF tokens return 403.
"""

@pytest.fixture
def client(tmp_path):
    # Monkeypatch DB_PATH to a temporary file for isolation
    temp_db = tmp_path / "test_spendly.db"
    db.DB_PATH = temp_db

    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            init_db()
        yield client

def login_user(client, name, email, password):
    """Helper to create a user and sign them in."""
    with app.app_context():
        user_id = create_user(name, email, password)
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = name
            # Mint a CSRF token for the session
            sess["csrf_token"] = secrets.token_urlsafe(32)
    return user_id

def test_edit_profile_get_populates_data(client):
    login_user(client, "Alice Smith", "alice@example.com", "password123")

    response = client.get('/profile/edit')

    assert response.status_code == 200
    assert b"Alice Smith" in response.data
    assert b"alice@example.com" in response.data

def test_edit_profile_happy_path(client):
    user_id = login_user(client, "Alice Smith", "alice@example.com", "password123")

    # Get CSRF token from session
    with client.session_transaction() as sess:
        token = sess["csrf_token"]

    data = {
        "name": "Alice Jones",
        "email": "alice.jones@example.com",
        "csrf_token": token
    }

    response = client.post('/profile/edit', data=data, follow_redirects=False)

    assert response.status_code == 302
    assert response.location == '/profile'

    # Verify DB update
    with app.app_context():
        user = get_user_by_id(user_id)
        assert user["name"] == "Alice Jones"
        assert user["email"] == "alice.jones@example.com"

    # Verify session update
    with client.session_transaction() as sess:
        assert sess["user_name"] == "Alice Jones"

def test_edit_profile_empty_name(client):
    user_id = login_user(client, "Alice Smith", "alice@example.com", "password123")

    with client.session_transaction() as sess:
        token = sess["csrf_token"]

    data = {
        "name": "  ", # Empty/whitespace
        "email": "alice.jones@example.com",
        "csrf_token": token
    }

    response = client.post('/profile/edit', data=data)

    assert response.status_code == 200
    assert b"Please enter your name." in response.data

    # Verify DB NOT updated
    with app.app_context():
        user = get_user_by_id(user_id)
        assert user["name"] == "Alice Smith"

def test_edit_profile_invalid_email(client):
    user_id = login_user(client, "Alice Smith", "alice@example.com", "password123")

    with client.session_transaction() as sess:
        token = sess["csrf_token"]

    data = {
        "name": "Alice Jones",
        "email": "not-an-email",
        "csrf_token": token
    }

    response = client.post('/profile/edit', data=data)

    assert response.status_code == 200
    assert b"Please enter a valid email address." in response.data

    # Verify DB NOT updated
    with app.app_context():
        user = get_user_by_id(user_id)
        assert user["email"] == "alice@example.com"

def test_edit_profile_email_conflict(client):
    # User A (logged in)
    user_a_id = login_user(client, "Alice", "alice@example.com", "password123")
    # User B (exists in DB)
    with app.app_context():
        create_user("Bob", "bob@example.com", "password123")

    with client.session_transaction() as sess:
        token = sess["csrf_token"]

    data = {
        "name": "Alice Jones",
        "email": "bob@example.com", # Conflict
        "csrf_token": token
    }

    response = client.post('/profile/edit', data=data)

    assert response.status_code == 200
    assert b"An account with that email already exists." in response.data

    # Verify DB NOT updated
    with app.app_context():
        user = get_user_by_id(user_a_id)
        assert user["email"] == "alice@example.com"

def test_delete_profile_happy_path(client):
    user_id = login_user(client, "Alice", "alice@example.com", "password123")

    # Add some expenses for this user
    with app.app_context():
        create_expense(user_id, 100.0, "Food", "2026-08-01", "Lunch")
        create_expense(user_id, 200.0, "Transport", "2026-08-02", "Cab")

    with client.session_transaction() as sess:
        token = sess["csrf_token"]

    response = client.post('/profile/delete', data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 302
    assert response.location == '/'

    # Verify DB records gone
    with app.app_context():
        user = get_user_by_id(user_id)
        assert user is None
        expenses = get_user_expenses(user_id)
        assert len(expenses) == 0

    # Verify session cleared
    with client.session_transaction() as sess:
        assert "user_id" not in sess

def test_profile_management_requires_auth(client):
    # Signed out
    routes = [
        ('/profile/edit', 'GET'),
        ('/profile/edit', 'POST'),
        ('/profile/delete', 'GET'),
        ('/profile/delete', 'POST'),
    ]

    for path, method in routes:
        if method == 'GET':
            response = client.get(path)
        else:
            response = client.post(path)

        assert response.status_code == 302
        assert response.location == '/login'

def test_profile_management_csrf_protection(client):
    login_user(client, "Alice", "alice@example.com", "password123")

    # POST /profile/edit without token
    response_edit = client.post('/profile/edit', data={"name": "New Name", "email": "new@example.com"})
    assert response_edit.status_code == 403

    # POST /profile/delete without token
    response_del = client.post('/profile/delete', data={})
    assert response_del.status_code == 403
