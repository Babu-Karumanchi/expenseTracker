import sqlite3
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# database/db.py → spendly/ → repo root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "spendly.db"

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


def create_user(name, email, password):
    """Insert a new user, hashing the password. Returns the new user id.

    Lets sqlite3.IntegrityError (duplicate email) propagate to the caller
    so the route can translate it into a user-facing message.
    """
    conn = get_db()
    try:
        password_hash = generate_password_hash(password)
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    """Fetch a user row by email. Returns None if not found."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def verify_password(user, password):
    """Check a plaintext password against the user's stored hash.

    Returns True on match, False otherwise. Safe to call with user=None.
    """
    if user is None:
        return False
    return check_password_hash(user["password_hash"], password)


def get_user_by_id(user_id):
    """Fetch a user row by id. Returns None if not found."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def get_user_expenses(user_id, date_from=None, date_to=None):
    """List expenses for a user, newest first. Returns [] if none.

    Sort order is `date DESC, id DESC` so ties on the same date stay stable
    (insertion order), matching the visual order of the profile page.

    Optional `date_from` / `date_to` are inclusive ISO `YYYY-MM-DD` bounds
    (strings). When a bound is supplied the corresponding `date >= ?` /
    `date <= ?` predicate is added to the WHERE clause; when both are None
    the original `WHERE user_id = ?` query is used unchanged.
    """
    conn = get_db()
    try:
        conditions = ["user_id = ?"]
        params = [user_id]
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)
        sql = (
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses "
            "WHERE " + " AND ".join(conditions) + " "
            "ORDER BY date DESC, id DESC"
        )
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def get_user_stats(user_id, date_from=None, date_to=None):
    """Aggregate stats for a user's profile page.

    Returns a dict with: total (float), count (int), top_category (str | None),
    top_category_total (float). When the user has no expenses, total is 0.0,
    count is 0, and top_category/top_category_total are None.

    Optional `date_from` / `date_to` are inclusive ISO `YYYY-MM-DD` bounds
    applied to BOTH the SUM/COUNT query and the top-category subquery so the
    stats reflect the same filtered window as `get_user_expenses(...)`.
    """
    conn = get_db()
    try:
        conditions = ["user_id = ?"]
        params = [user_id]
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("date <= ?")
            params.append(date_to)
        where_sql = " AND ".join(conditions)

        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) AS total, COUNT(*) AS cnt "
            "FROM expenses WHERE " + where_sql,
            tuple(params),
        ).fetchone()
        top = conn.execute(
            "SELECT category, SUM(amount) AS cat_total "
            "FROM expenses WHERE " + where_sql + " "
            "GROUP BY category "
            "ORDER BY cat_total DESC "
            "LIMIT 1",
            tuple(params),
        ).fetchone()
        return {
            "total": float(row["total"]),
            "count": int(row["cnt"]),
            "top_category": top["category"] if top is not None else None,
            "top_category_total": float(top["cat_total"]) if top is not None else None,
        }
    finally:
        conn.close()
