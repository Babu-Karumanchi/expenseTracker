"""Pytest fixtures for Spendly.

CRITICAL IMPORT ORDER
---------------------
`app.py` runs `init_db()` and `seed_db()` at module-import time
(see the `with app.app_context():` block at the bottom of app.py).
That import happens before any test runs, so we MUST redirect the
SQLite path BEFORE `from app import app` is executed at the bottom
of this file.

To do that, we patch `database.db.DB_PATH` at conftest-module load
time, then import `app`. The patched path persists because Python
caches the module — `database.db` is a single object, and every
helper inside it calls `get_db()`, which reads `DB_PATH` at call
time (not at import time).
"""
import sys
import tempfile
from pathlib import Path

# Pick a per-pytest-run temp file. tempfile.gettempdir() exists on all
# platforms; pytest itself doesn't clean it up, but each test re-wipes
# the tables via the autouse `reset_db` fixture below, and on a fresh
# machine the file simply does not exist yet.
_TEST_DB = Path(tempfile.gettempdir()) / "spendly_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()

# Patch the DB path BEFORE importing app.
import database.db as _db  # noqa: E402

_db.DB_PATH = _TEST_DB

from app import app  # noqa: E402  (triggers init_db + seed_db against _TEST_DB)

import pytest  # noqa: E402


@pytest.fixture
def client():
    """A Flask test client bound to the real app object."""
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_db():
    """Wipe the users/expenses tables and re-seed between every test.

    The seeded demo user survives at the start of each test; tests that
    register new users do not collide with the demo user because the
    happy-path test uses a unique email.
    """
    conn = _db.get_db()
    try:
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM users")
        conn.commit()
    finally:
        conn.close()
    _db.seed_db()
    yield
