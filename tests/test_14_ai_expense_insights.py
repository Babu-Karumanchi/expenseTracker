import pytest
import json
import os
from datetime import date
from unittest.mock import patch, MagicMock
from app import app
import database.db

# --- Fixtures ---

@pytest.fixture
def client():
    """
    Flask test client with an isolated temporary database.
    """
    # Use a temporary file for the database to ensure isolation
    # and compatibility with the current get_db() implementation.
    import tempfile
    db_fd, db_path = tempfile.mkstemp()
    database.db.DB_PATH = db_path

    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            database.db.init_db()
        yield client

    # Clean up temporary database
    os.close(db_fd)
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.fixture
def auth_user(client):
    """
    Creates a user and logs them in.
    """
    email = "test@example.com"
    password = "testpassword123"
    user_id = database.db.create_user("Test User", email, password)

    client.post('/login', data={'email': email, 'password': password})
    return user_id

def login(client, email, password):
    """Helper to log in a user."""
    return client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

# --- Tests ---

def test_insights_unauthenticated_redirects_to_login(client):
    """
    Spec: Route /insights is protected; signed-out users are redirected to /login.
    """
    response = client.get('/insights')
    assert response.status_code == 302
    assert response.location.endswith('/login')

def test_insights_happy_path(client, auth_user):
    """
    Spec: Navigating to /insights while logged in renders AI-generated insights
    based on real expense data.
    """
    # 1. Seed data within the last 3 months
    # Using a fixed date for determinism
    fixed_today = date(2026, 9, 18)
    database.db.create_expense(auth_user, 1500.0, "Food", "2026-08-15", "Dinner")
    database.db.create_expense(auth_user, 2000.0, "Shopping", "2026-07-10", "Clothes")

    # 2. Mock Environment and API
    with patch('os.environ.get') as mock_env, \
         patch('app._today') as mock_today, \
         patch('urllib.request.urlopen') as mock_urlopen:

        # Spec requires GROQ_API_KEY
        mock_env.side_effect = lambda k, default=None: "test-api-key" if k == "GROQ_API_KEY" else default
        mock_today.return_value = fixed_today

        # Mock AI API response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "You spend too much on food. Try cooking at home to save ₹500 per week."}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        response = client.get('/insights')

        assert response.status_code == 200
        assert b"You spend too much on food" in response.data
        assert "₹500".encode("utf-8") in response.data

def test_insights_no_expenses_fallback(client, auth_user):
    """
    Spec: If no expenses are found for the last 3 months, the page should
    display a message stating so.
    """
    fixed_today = date(2026, 9, 18)
    # Seed data older than 3 months
    database.db.create_expense(auth_user, 1000.0, "Food", "2025-01-01", "Old Expense")

    with patch('app._today') as mock_today:
        mock_today.return_value = fixed_today
        response = client.get('/insights')

        assert response.status_code == 200
        assert b"No expenses found for the last 3 months" in response.data

def test_insights_missing_api_key_fallback(client, auth_user):
    """
    Spec: If GROQ_API_KEY is unset, the page renders a graceful fallback message.
    """
    fixed_today = date(2026, 9, 18)
    database.db.create_expense(auth_user, 1500.0, "Food", "2026-08-15", "Dinner")

    with patch('os.environ.get') as mock_env, \
         patch('app._today') as mock_today:

        # Simulate missing GROQ_API_KEY
        mock_env.side_effect = lambda k, default=None: default if k == "GROQ_API_KEY" else "some-other-val"
        mock_today.return_value = fixed_today

        response = client.get('/insights')

        assert response.status_code == 200
        assert b"AI insights are currently unavailable" in response.data
        assert b"GROQ_API_KEY" in response.data

def test_insights_api_failure_fallback(client, auth_user):
    """
    Spec: If the API request fails, render a helpful message stating
    that AI insights are temporarily unavailable.
    """
    fixed_today = date(2026, 9, 18)
    database.db.create_expense(auth_user, 1500.0, "Food", "2026-08-15", "Dinner")

    with patch('os.environ.get') as mock_env, \
         patch('app._today') as mock_today, \
         patch('urllib.request.urlopen') as mock_urlopen:

        mock_env.side_effect = lambda k, default=None: "test-api-key" if k == "GROQ_API_KEY" else default
        mock_today.return_value = fixed_today

        # Simulate an API error (e.g. timeout or connection error)
        mock_urlopen.side_effect = Exception("API Connection Timeout")

        response = client.get('/insights')

        assert response.status_code == 200
        assert b"AI insights are currently unavailable" in response.data
        assert b"Error: API Connection Timeout" in response.data
