import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp import services as svc

SESSION_A = "a" * 32
SESSION_B = "b" * 32
IP_HASH = "c" * 64


OLD_PUBLIC_SCHEMA = """
CREATE TABLE ResumeDetails(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Name Text NOT NULL,
    Email Text NOT NULL,
    Skills Text CHECK(json_valid(Skills)) NOT NULL,
    Experience Text NOT NULL,
    CurrentPosition Text NULL,
    OriginalFileName Text NOT NULL,
    OriginalFilePath Text NOT NULL,
    UNIQUE(Email, OriginalFilePath)
);

CREATE TABLE JobDetails(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    CompanyName Text NOT NULL,
    Position Text NOT NULL,
    JobLocation Text NULL,
    JobDescription Text NOT NULL,
    JobUrl Text NOT NULL,
    IsOpen INTEGER NOT NULL DEFAULT 0 CHECK (IsOpen IN (0, 1)),
    UNIQUE(JobUrl)
);

CREATE TABLE JobApplications(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ResumeId Integer NOT NULL,
    JobId Integer NOT NULL,
    MatchScorePercent Integer NULL,
    Status Text NULL,
    CreatedAt Text DEFAULT(datetime('now')),
    UNIQUE(ResumeId, JobId)
);

CREATE TABLE PreparationMaterials(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    JobApplicationId Integer NOT NULL,
    MaterialType Text NOT NULL,
    MaterialContent Text NOT NULL
);
"""


def make_temp_db() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "job-tracker.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(OLD_PUBLIC_SCHEMA)
        conn.commit()
    return tmp, db_path


class AnonymousPublicSafetyTests(unittest.TestCase):
    def test_bootstrap_sets_anonymous_cookie_and_filters_lists_by_session(self):
        from api.main import app

        client = TestClient(app)
        with (
            patch("api.main.svc.ensure_anonymous_session") as ensure_session,
            patch("api.main.svc.list_resumes", return_value=[]) as list_resumes,
            patch("api.main.svc.list_jobs", return_value=[]) as list_jobs,
            patch("api.main.svc.prep_pack_enabled", return_value=False),
            patch("api.main.svc.coach_is_ready", return_value=True),
        ):
            response = client.get("/api/bootstrap")

        self.assertEqual(response.status_code, 200)
        session_id = response.cookies.get(svc.ANONYMOUS_SESSION_COOKIE)
        self.assertIsNotNone(session_id)
        self.assertTrue(svc.is_valid_anonymous_session_id(session_id))
        ensure_session.assert_called_once_with(session_id)
        list_resumes.assert_called_once_with(session_id)
        list_jobs.assert_called_once_with(session_id)

    def test_score_quota_blocks_before_llm_work(self):
        from api.main import app

        client = TestClient(app)
        with (
            patch("api.main.svc.ensure_anonymous_session"),
            patch(
                "api.main.svc.record_guarded_usage",
                side_effect=ValueError("Daily free limit reached for score."),
            ) as usage,
            patch("api.main.svc.run_score") as run_score,
        ):
            response = client.post("/api/score", json={"resume_id": 1, "job_id": 3})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Daily free limit", response.json()["detail"])
        usage.assert_called_once()
        run_score.assert_not_called()

    def test_list_resumes_and_jobs_are_scoped_to_anonymous_session(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO ResumeDetails
                        (Name, Email, Skills, Experience, OriginalFileName,
                         OriginalFilePath, AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("Alice", "a@example.com", "[]", "[]", "a.pdf", "a.pdf", SESSION_A),
                )
                conn.execute(
                    """
                    INSERT INTO ResumeDetails
                        (Name, Email, Skills, Experience, OriginalFileName,
                         OriginalFilePath, AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("Bob", "b@example.com", "[]", "[]", "b.pdf", "b.pdf", SESSION_B),
                )
                conn.execute(
                    """
                    INSERT INTO JobDetails
                        (CompanyName, Position, JobDescription, JobUrl, IsOpen,
                         AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("Acme", "Engineer", "Build things", "manual://a", 1, SESSION_A),
                )
                conn.execute(
                    """
                    INSERT INTO JobDetails
                        (CompanyName, Position, JobDescription, JobUrl, IsOpen,
                         AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("Other", "Engineer", "Build things", "manual://b", 1, SESSION_B),
                )
                conn.commit()

            resumes = svc.list_resumes(SESSION_A)
            jobs = svc.list_jobs(SESSION_A)

        self.assertEqual([row["Name"] for row in resumes], ["Alice"])
        self.assertEqual([row["CompanyName"] for row in jobs], ["Acme"])

    def test_guarded_usage_records_event_and_enforces_daily_limit(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            svc.record_guarded_usage(
                SESSION_A,
                "score",
                IP_HASH,
                daily_limit=2,
                session_rate_limit=99,
                ip_rate_limit=99,
            )
            svc.record_guarded_usage(
                SESSION_A,
                "score",
                IP_HASH,
                daily_limit=2,
                session_rate_limit=99,
                ip_rate_limit=99,
            )

            with self.assertRaisesRegex(ValueError, "Daily free limit"):
                svc.record_guarded_usage(
                    SESSION_A,
                    "score",
                    IP_HASH,
                    daily_limit=2,
                    session_rate_limit=99,
                    ip_rate_limit=99,
                )

            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM UsageEvents WHERE EventType = 'score';"
                ).fetchone()[0]

        self.assertEqual(count, 2)

    def test_guarded_usage_enforces_ip_rate_limit(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            svc.record_guarded_usage(
                SESSION_A,
                "coach",
                IP_HASH,
                daily_limit=99,
                session_rate_limit=99,
                ip_rate_limit=1,
            )

            with self.assertRaisesRegex(ValueError, "Too many requests"):
                svc.record_guarded_usage(
                    SESSION_B,
                    "coach",
                    IP_HASH,
                    daily_limit=99,
                    session_rate_limit=99,
                    ip_rate_limit=1,
                )

    def test_cleanup_removes_expired_anonymous_rows_and_files(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        old_resume_file = Path(tmp.name) / "old.pdf"
        old_resume_file.write_bytes(b"%PDF-old")

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO AnonymousSessions (Id, CreatedAt, LastSeenAt)
                    VALUES ('old-session', datetime('now', '-20 days'), datetime('now', '-20 days'));
                    """
                )
                conn.execute(
                    """
                    INSERT INTO ResumeDetails
                        (Name, Email, Skills, Experience, OriginalFileName,
                         OriginalFilePath, AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "Old",
                        "old@example.com",
                        "[]",
                        "[]",
                        old_resume_file.name,
                        str(old_resume_file),
                        "old-session",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO UsageEvents (AnonymousSessionId, EventType, IpHash, CreatedAt)
                    VALUES ('old-session', 'score', 'ip', datetime('now', '-20 days'));
                    """
                )
                conn.commit()

            deleted = svc.cleanup_expired_anonymous_data(retention_days=14)

            with closing(sqlite3.connect(db_path)) as conn:
                resumes = conn.execute("SELECT COUNT(*) FROM ResumeDetails;").fetchone()[0]
                events = conn.execute("SELECT COUNT(*) FROM UsageEvents;").fetchone()[0]

        self.assertGreaterEqual(deleted, 1)
        self.assertEqual(resumes, 0)
        self.assertEqual(events, 0)
        self.assertFalse(old_resume_file.exists())

    def test_tailored_pdf_lookup_is_scoped_to_anonymous_session(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        tailored_pdf = Path(tmp.name) / "tailored.pdf"
        tailored_pdf.write_bytes(b"%PDF-tailored")

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO ResumeDetails
                        (Name, Email, Skills, Experience, OriginalFileName,
                         OriginalFilePath, AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("Alice", "a@example.com", "[]", "[]", "a.pdf", "a.pdf", SESSION_A),
                )
                source_resume_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO ResumeDetails
                        (Name, Email, Skills, Experience, OriginalFileName,
                         OriginalFilePath, AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "Alice",
                        "a@example.com",
                        "[]",
                        "[]",
                        tailored_pdf.name,
                        str(tailored_pdf),
                        SESSION_A,
                    ),
                )
                tailored_resume_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO JobDetails
                        (CompanyName, Position, JobDescription, JobUrl, IsOpen,
                         AnonymousSessionId)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("Acme", "Engineer", "Build things", "manual://a", 1, SESSION_A),
                )
                job_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
                conn.execute(
                    """
                    INSERT INTO JobApplications
                        (ResumeId, JobId, TailoredResumeId, AnonymousSessionId)
                    VALUES (?, ?, ?, ?);
                    """,
                    (source_resume_id, job_id, tailored_resume_id, SESSION_A),
                )
                application_id = conn.execute("SELECT last_insert_rowid();").fetchone()[0]
                conn.commit()

            owner_path = svc.get_tailored_pdf_path(application_id, SESSION_A)
            other_path = svc.get_tailored_pdf_path(application_id, SESSION_B)

        self.assertEqual(owner_path, tailored_pdf)
        self.assertIsNone(other_path)

    def test_usage_summary_counts_sessions_and_feature_events(self):
        tmp, db_path = make_temp_db()
        self.addCleanup(tmp.cleanup)

        with patch.object(svc, "DB_PATH", db_path):
            svc.ensure_public_safety_schema()
            svc.record_guarded_usage(
                SESSION_A,
                "score",
                IP_HASH,
                daily_limit=99,
                session_rate_limit=99,
                ip_rate_limit=99,
            )
            svc.record_guarded_usage(
                SESSION_A,
                "coach",
                IP_HASH,
                daily_limit=99,
                session_rate_limit=99,
                ip_rate_limit=99,
            )
            svc.record_guarded_usage(
                SESSION_B,
                "score",
                "d" * 64,
                daily_limit=99,
                session_rate_limit=99,
                ip_rate_limit=99,
            )

            summary = svc.usage_summary(days=7)

        self.assertEqual(summary["active_sessions"], 2)
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["events_by_type"], {"coach": 1, "score": 2})


if __name__ == "__main__":
    unittest.main()
