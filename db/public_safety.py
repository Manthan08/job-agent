"""Public-deploy safety schema helpers.

Anonymous sessions are the no-login ownership boundary for the public MVP.
The helpers here are intentionally small and idempotent so older local SQLite
files can be upgraded as soon as the API touches them.
"""
from __future__ import annotations

import sqlite3

SESSION_COLUMN = "AnonymousSessionId"
SESSION_SCOPED_TABLES = (
    "ResumeDetails",
    "JobDetails",
    "JobApplications",
    "PreparationMaterials",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table,),
    ).fetchone()
    return row is not None


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    if not _table_exists(conn, table):
        return
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")


def ensure_public_safety_schema(conn: sqlite3.Connection) -> None:
    """Create/upgrade anonymous-session and usage-tracking structures."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS AnonymousSessions(
            Id Text PRIMARY KEY,
            CreatedAt Text DEFAULT(datetime('now')),
            LastSeenAt Text DEFAULT(datetime('now'))
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS UsageEvents(
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            AnonymousSessionId Text NOT NULL,
            EventType Text NOT NULL,
            IpHash Text NULL,
            EstimatedCostUsd REAL NOT NULL DEFAULT 0,
            Metadata Text NULL CHECK(Metadata IS NULL OR json_valid(Metadata)),
            CreatedAt Text DEFAULT(datetime('now'))
        );
        """
    )

    for table in SESSION_SCOPED_TABLES:
        _add_column_if_missing(conn, table, SESSION_COLUMN, "Text NULL")

    # Public reads can join through the tailored output link; older local DBs
    # from before Phase 4.1 need this column before session-scoped API routes run.
    _add_column_if_missing(conn, "JobApplications", "TailoredResumeId", "Integer NULL")

    if _table_exists(conn, "UsageEvents"):
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS IX_UsageEvents_Session_Event_Created
            ON UsageEvents(AnonymousSessionId, EventType, CreatedAt);
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS IX_UsageEvents_Ip_Created
            ON UsageEvents(IpHash, CreatedAt);
            """
        )

    for table in SESSION_SCOPED_TABLES:
        if _table_exists(conn, table) and SESSION_COLUMN in _columns(conn, table):
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS IX_{table}_AnonymousSessionId
                ON {table}(AnonymousSessionId);
                """
            )
