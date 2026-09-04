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

CREATE TABLE IF NOT EXISTS budgets (
    user_id INTEGER PRIMARY KEY,
    amount REAL NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL,
    category TEXT,
    date TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS savings_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    goal_name TEXT NOT NULL,
    target_amount REAL NOT NULL,
    current_amount REAL DEFAULT 0.0,
    deadline TEXT,
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


def create_expense(user_id, amount, category, date, description):
    """Insert a new expense for a user. Returns the new expense id.

    An empty/whitespace-only `description` is stored as NULL so the column's
    NULL semantics are preserved (Step 1 schema marks it nullable, not
    empty-string). The `created_at` column has `DEFAULT (datetime('now'))`,
    so it is intentionally not supplied here. Foreign-key enforcement is
    on (get_db), so inserting with an invalid `user_id` fails cleanly via
    sqlite3.IntegrityError.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description or None),
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


def get_user_expenses_for_analytics(user_id, date_from=None):
    """List expenses for a user, oldest first. Returns [] if none.

    Sort order is `date ASC, id ASC` so the chart can iterate oldest → newest
    without an in-Python resort. Single lower bound (no upper bound) — used
    by `/analytics` to read the trailing-12-month window even when the user
    picks the "All Time" preset.

    `date_from` is an inclusive ISO `YYYY-MM-DD` string. The route is
    responsible for any upper-bound filtering (e.g. narrowing by preset);
    this helper deliberately has no `date_to` so callers can't accidentally
    pass a sentinel like "9999-12-31" and trip an SQL-string concat bug.
    """
    conn = get_db()
    try:
        conditions = ["user_id = ?"]
        params = [user_id]
        if date_from:
            conditions.append("date >= ?")
            params.append(date_from)
        sql = (
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses "
            "WHERE " + " AND ".join(conditions) + " "
            "ORDER BY date ASC, id ASC"
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


def get_expense_by_id(expense_id, user_id):
    """Fetch a single expense row by id, owner-scoped. Returns None if not found.

    Scopes the query with `AND user_id = ?` so the row is only returned when
    BOTH the id exists AND it belongs to `user_id`. A miss covers both "doesn't exist"
    and "belongs to a different user" so the caller can
    `abort(404)` uniformly without leaking which ids are in use.

    Returns a `sqlite3.Row` keyed by column name so the route can index by
    `expense["amount"]`, `expense["date"]`, etc.
    """
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses "
            "WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_expense(expense_id, user_id, amount, category, date, description):
    """Update an existing expense row, owner-scoped. Returns rowcount.

    Parameterised UPDATE; the `AND user_id = ?` clause means an attempt to
    update another user's row silently affects 0 rows rather than raising.
    Empty / whitespace-only `description` is stored as `NULL` — same
    convention as `create_expense` so the `/profile` transactions cell can
    render NULL and "" uniformly via `description or ""`.

    `amount` is stored as the value passed in. The route casts the
    validated `Decimal` to `float` so the column type matches what
    `create_expense` writes; `SUM(amount)` on /profile then aggregates
    consistently across original and edited rows.

    `created_at` is intentionally NOT touched — the timestamp records
    when the row was first recorded, not when it was last corrected.

    The rowcount return value exists for testability (the suite asserts
    on it); route callers may safely ignore it.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE expenses "
            "SET amount = ?, category = ?, date = ?, description = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, category, date, description or None, expense_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_expense(expense_id, user_id):
    """Delete an expense row, owner-scoped. Returns rowcount.

    Parameterised DELETE; the `AND user_id = ?` clause means an attempt to
    delete another user's row silently affects 0 rows rather than raising.
    The same `get_expense_by_id(id, user_id)` lookup that the route runs
    before calling this helper will have already 404'd for ids that don't
    belong to the session user, so the rowcount return is mostly for
    testability — callers may safely ignore it.

    `created_at` is intentionally NOT preserved because the row itself is
    gone — there is no soft-delete column. The row vanishes from the
    profile page, the stats, and the by-category aggregate on the next
    `/profile` render.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def update_user(user_id, name, email):
    """Update user's name and email. Returns rowcount.

    Lets sqlite3.IntegrityError (duplicate email) propagate to the caller.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            (name, email, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_user(user_id):
    """Permanently delete a user and all their associated expenses.

    Since the schema doesn't use ON DELETE CASCADE, we manually clear
    expenses first to avoid foreign key violations.
    """
    conn = get_db()
    try:
        # Delete expenses first
        conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        # Delete the user
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_budget(user_id):
    """Fetch the monthly budget amount for a user. Returns None if not set."""
    conn = get_db()
    try:
        return conn.execute("SELECT amount FROM budgets WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def set_budget(user_id, amount):
    """Set or update the monthly budget for a user. Returns rowcount."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO budgets (user_id, amount) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET amount = ?, updated_at = datetime('now')",
            (user_id, amount, amount),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- Income Helpers ---

def create_income(user_id, amount, source, category, date):
    """Insert a new income record for a user. Returns the new income id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO income (user_id, amount, source, category, date) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, source, category, date),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_income(user_id, date_from=None, date_to=None):
    """List income for a user, newest first. Returns [] if none."""
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
            "SELECT id, user_id, amount, source, category, date "
            "FROM income "
            "WHERE " + " AND ".join(conditions) + " "
            "ORDER BY date DESC, id DESC"
        )
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def get_income_by_id(income_id, user_id):
    """Fetch a single income row by id, owner-scoped. Returns None if not found."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, amount, source, category, date "
            "FROM income "
            "WHERE id = ? AND user_id = ?",
            (income_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def update_income(income_id, user_id, amount, source, category, date):
    """Update an existing income row, owner-scoped. Returns rowcount."""
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE income SET amount = ?, source = ?, category = ?, date = ? "
            "WHERE id = ? AND user_id = ?",
            (amount, source, category, date, income_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_income(income_id, user_id):
    """Delete an income row, owner-scoped. Returns rowcount."""
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM income WHERE id = ? AND user_id = ?",
            (income_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- Savings Helpers ---

def create_savings_goal(user_id, goal_name, target_amount, deadline):
    """Create a new savings goal for a user. Returns the goal id."""
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO savings_goals (user_id, goal_name, target_amount, deadline) VALUES (?, ?, ?, ?)",
            (user_id, goal_name, target_amount, deadline),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_savings_goals(user_id):
    """List all savings goals for a user."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, goal_name, target_amount, current_amount, deadline "
            "FROM savings_goals WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def get_savings_goal_by_id(goal_id, user_id):
    """Fetch a single savings goal row by id, owner-scoped. Returns None if not found."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, goal_name, target_amount, current_amount, deadline "
            "FROM savings_goals WHERE id = ? AND user_id = ?",
            (goal_id, user_id),
        ).fetchone()
    finally:
        conn.close()


def add_funds_to_goal(goal_id, user_id, amount):
    """Add funds to a specific savings goal, owner-scoped. Returns rowcount."""
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE savings_goals SET current_amount = current_amount + ? "
            "WHERE id = ? AND user_id = ?",
            (amount, goal_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_savings_goal(goal_id, user_id):
    """Delete a savings goal, owner-scoped. Returns rowcount."""
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM savings_goals WHERE id = ? AND user_id = ?",
            (goal_id, user_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --- Aggregate Helpers ---

def get_user_financial_summary(user_id, date_from=None, date_to=None):
    """
    Calculate aggregated totals for income and expenses over a window.
    Returns a dict with:
      - total_income (float)
      - total_expenses (float)
      - total_savings_goals (float) - all-time sum of goal current_amounts
    """
    conn = get_db()
    try:
        # Windowed income
        inc_conditions = ["user_id = ?"]
        inc_params = [user_id]
        if date_from:
            inc_conditions.append("date >= ?")
            inc_params.append(date_from)
        if date_to:
            inc_conditions.append("date <= ?")
            inc_params.append(date_to)

        inc_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) AS total FROM income WHERE " + " AND ".join(inc_conditions),
            tuple(inc_params),
        ).fetchone()

        # Windowed expenses
        exp_conditions = ["user_id = ?"]
        exp_params = [user_id]
        if date_from:
            exp_conditions.append("date >= ?")
            exp_params.append(date_from)
        if date_to:
            exp_conditions.append("date <= ?")
            exp_params.append(date_to)

        exp_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0.0) AS total FROM expenses WHERE " + " AND ".join(exp_conditions),
            tuple(exp_params),
        ).fetchone()

        # All-time savings goals balance
        sav_row = conn.execute(
            "SELECT COALESCE(SUM(current_amount), 0.0) AS total FROM savings_goals WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        return {
            "total_income": float(inc_row["total"]),
            "total_expenses": float(exp_row["total"]),
            "total_savings_goals": float(sav_row["total"]),
        }
    finally:
        conn.close()
