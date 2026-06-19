import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from db import application_repository as repo
from models.match import MatchResult
from webapp import services as svc


OLD_APPLICATION_SCHEMA = """
CREATE TABLE JobApplications(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ResumeId Integer NOT NULL,
    JobId Integer NOT NULL,
    MatchScorePercent Integer NULL CHECK(MatchScorePercent >= 0 AND MatchScorePercent <= 100),
    Status Text NULL,
    TailoredResumeId Integer NULL,
    CreatedAt  Text DEFAULT(datetime('now')),
    UNIQUE(ResumeId, JobId)
);
"""


class MatchSnapshotPersistenceTests(unittest.TestCase):
    def test_get_application_migrates_old_db_and_returns_empty_score_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "job-tracker.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(OLD_APPLICATION_SCHEMA)
                conn.execute(
                    """
                    INSERT INTO JobApplications
                        (ResumeId, JobId, MatchScorePercent, Status)
                    VALUES (?, ?, ?, ?);
                    """,
                    (1, 3, 72, "Not Applied"),
                )
                conn.commit()

            with patch.object(svc, "DB_PATH", db_path):
                application = svc.get_application(1, 3)

            self.assertIsNotNone(application)
            self.assertEqual(application["MatchScorePercent"], 72)
            self.assertIsNone(application["MatchReasoning"])
            self.assertEqual(application["MatchedSkills"], [])
            self.assertEqual(application["MissingSkills"], [])

    def test_save_application_persists_match_snapshot_details(self):
        match = MatchResult(
            match_score=81,
            reasoning="Strong .NET and distributed systems fit.",
            matched_skills=[".NET", "Azure Service Bus"],
            missing_skills=["Semantic Kernel"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "job-tracker.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(OLD_APPLICATION_SCHEMA)
                conn.commit()

            real_connect = sqlite3.connect
            with patch.object(
                repo.sqlite3,
                "connect",
                side_effect=lambda _ignored_path: real_connect(db_path),
            ):
                application_id = repo.save_application_to_db(1, 3, match)

            with closing(real_connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT Id, MatchScorePercent, MatchReasoning,
                           MatchedSkills, MissingSkills
                    FROM JobApplications
                    WHERE Id = ?;
                    """,
                    (application_id,),
                ).fetchone()

        self.assertEqual(row["MatchScorePercent"], 81)
        self.assertEqual(row["MatchReasoning"], match.reasoning)
        self.assertEqual(json.loads(row["MatchedSkills"]), match.matched_skills)
        self.assertEqual(json.loads(row["MissingSkills"]), match.missing_skills)


if __name__ == "__main__":
    unittest.main()
