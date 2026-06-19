import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from db import resume_repository as repo
from models.tailored import SkillCategory, TailoredExperienceItem, TailoredResumeModel


SCHEMA = """
CREATE TABLE ResumeDetails(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    Name Text NOT NULL,
    Email Text NOT NULL,
    Skills Text CHECK(json_valid(Skills)) NOT NULL,
    Experience Text CHECK(json_valid(Experience)) NOT NULL,
    Phone Text NULL,
    Urls Text NULL CHECK(Urls IS NULL OR json_valid(Urls)),
    Location Text NULL,
    CurrentPosition Text NULL,
    Summary Text NULL,
    Projects Text NULL CHECK(Projects IS NULL OR json_valid(Projects)),
    Education Text NULL,
    OriginalFileName Text NOT NULL,
    OriginalFilePath Text NOT NULL,
    UNIQUE(Email, OriginalFilePath)
);

CREATE TABLE JobApplications(
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    ResumeId Integer NOT NULL,
    JobId Integer NOT NULL,
    MatchScorePercent Integer NULL,
    Status Text NULL,
    TailoredResumeId Integer NULL,
    UNIQUE(ResumeId, JobId)
);
"""


class TailoredResumeLinkTests(unittest.TestCase):
    def test_save_tailored_resume_link_carries_source_facts_and_tailored_summary(self):
        tailored = TailoredResumeModel(
            tailored_summary="Tailored senior .NET summary.",
            tailored_skills=[
                SkillCategory(category="Backend", skills=["C#", ".NET"])
            ],
            tailored_experience=[
                TailoredExperienceItem(
                    company="Example Company",
                    role_title="Senior Software Engineer",
                    start_date="2023",
                    end_date=None,
                    bullets=["Built Azure Service Bus workflows."],
                )
            ],
        )
        source_resume = {
            "Phone": "+1 555 0100",
            "Urls": json.dumps(["https://example.com"]),
            "Location": "Toronto, Canada",
            "CurrentPosition": "Senior Software Engineer",
            "Projects": json.dumps([{"name": "Resume Workbench"}]),
            "Education": "B.Tech Computer Science",
        }

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "job-tracker.db"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(SCHEMA)
                conn.commit()

            real_connect = sqlite3.connect
            with patch.object(
                repo.sqlite3,
                "connect",
                side_effect=lambda _ignored_path: real_connect(db_path),
            ):
                tailored_id = repo.save_tailored_resume_link(
                    original_resume_id=1,
                    job_id=3,
                    tailored=tailored,
                    candidate_name="Jane Candidate",
                    candidate_email="jane@example.com",
                    pdf_path=Path(tmp) / "tailored.pdf",
                    source_resume=source_resume,
                )

            with closing(real_connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT Phone, Urls, Location, CurrentPosition, Summary,
                           Projects, Education, Skills, Experience
                    FROM ResumeDetails
                    WHERE Id = ?;
                    """,
                    (tailored_id,),
                ).fetchone()

        self.assertEqual(row["Phone"], source_resume["Phone"])
        self.assertEqual(row["Urls"], source_resume["Urls"])
        self.assertEqual(row["Location"], source_resume["Location"])
        self.assertEqual(row["CurrentPosition"], source_resume["CurrentPosition"])
        self.assertEqual(row["Summary"], tailored.tailored_summary)
        self.assertEqual(row["Projects"], source_resume["Projects"])
        self.assertEqual(row["Education"], source_resume["Education"])
        self.assertEqual(json.loads(row["Skills"])[0]["category"], "Backend")
        self.assertEqual(json.loads(row["Experience"])[0]["company"], "Example Company")


if __name__ == "__main__":
    unittest.main()
