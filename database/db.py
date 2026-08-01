import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

# database/db.py → spendly/ → repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "expense_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def get_db():
    """Return a SQLite connection with Row factory and FK enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create both tables. Safe to call multiple times via IF NOT EXISTS."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def seed_db():
    """Insert demo user + 8 sample expenses. Skips entirely if a user already exists."""
    conn = get_db()
    try:
        # Idempotency: if any user row exists, assume seed already ran.
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return

        # Demo user — password "demo123" hashed via werkzeug
        password_hash = generate_password_hash("demo123")
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash),
        )
        user_id = cur.lastrowid

        # 8 expenses across the 7 spec categories. Food appears twice so every
        # category is covered at least once while keeping the count at exactly 8.
        # Amounts in INR; dates spread across August 2026.
        expenses = [
            (user_id, 450.00,  "Food",          "2026-08-01", "Lunch at office canteen"),
            (user_id, 1850.00, "Transport",     "2026-08-02", "Rapido auto to airport"),
            (user_id, 2200.00, "Bills",         "2026-08-03", "Electricity bill — August"),
            (user_id, 650.00,  "Health",        "2026-08-05", "Pharmacy — vitamins"),
            (user_id, 499.00,  "Entertainment", "2026-08-08", "BookMyShow movie ticket"),
            (user_id, 1799.00, "Shopping",      "2026-08-12", "T-shirt from Decathlon"),
            (user_id, 320.00,  "Other",         "2026-08-15", "Household supplies"),
            (user_id, 380.00,  "Food",          "2026-08-22", "Sunday breakfast"),
        ]
        conn.executemany(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            expenses,
        )
        conn.commit()
    finally:
        conn.close()
