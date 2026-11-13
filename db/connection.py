"""Shared SQLite connection helper.

Every repository opens its own short-lived connection. Centralizing the open
here lets us apply the pragmas that make concurrent access safe under the
multi-user web server (several requests writing at once):

  - journal_mode=WAL: readers no longer block writers and vice-versa. The default
    rollback journal serializes all access and is the source of "database is
    locked" stalls under load. WAL persists in the DB file header once set; we
    still set it on every connect so a freshly created file gets it too.
  - busy_timeout: if a write lock is briefly held, wait up to N ms for it to clear
    instead of failing instantly with "database is locked".
  - synchronous=NORMAL: safe with WAL and noticeably faster on commit.
"""

import os
import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 5000
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "job-tracker.db"


def database_path() -> Path:
    """Resolve the SQLite path for the current runtime.

    Local development keeps the historical db/job-tracker.db location. Containers
    can set JOB_AGENT_DB_PATH so persistent storage lives in a mounted runtime
    directory instead of inside the image layer.
    """
    configured = os.getenv("JOB_AGENT_DB_PATH") or os.getenv("DB_PATH")
    if not configured:
        return DEFAULT_DB_PATH
    return Path(configured).expanduser().resolve()


def connect(db_path=None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + a write-lock wait timeout.

    Called with a single positional arg so it stays compatible with test doubles
    that monkeypatch ``sqlite3.connect`` with a one-arg signature. The write-lock
    wait is set via PRAGMA busy_timeout (sqlite3.connect already defaults its own
    ``timeout`` to 5s as well).
    """
    path = Path(db_path).expanduser().resolve() if db_path else database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS};")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn
