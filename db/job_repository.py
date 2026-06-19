"""Persistence for discovered jobs. Mirrors db/resume_repository.py.

Idempotent upsert keyed on the normalized JobUrl so re-ingesting the same
posting updates the row instead of creating a duplicate.
"""

import sqlite3
from pathlib import Path

from db.public_safety import ensure_public_safety_schema
from models.jobs import JobDetailsModel


def save_job_to_db(
    job: JobDetailsModel,
    anonymous_session_id: str | None = None,
) -> int:
    """Insert or update one job; return its JobDetails.Id."""
    conn = None
    try:
        HERE = Path(__file__).resolve().parent
        db_path = HERE / "job-tracker.db"

        posting_date = job.job_posting_date.isoformat() if job.job_posting_date else None
        is_open = None if job.is_open is None else (1 if job.is_open else 0)

        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO JobDetails (
                AnonymousSessionId, CompanyName, Position, YearsOfExperienceRequired, JobLocation,
                JobDescription, JobUrl, JobPostingDate, IsOpen,
                PointsOfContact, PointsOfContactEmail, Notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 1), ?, ?, ?)
            ON CONFLICT(JobUrl) DO UPDATE SET
                AnonymousSessionId=excluded.AnonymousSessionId,
                CompanyName=excluded.CompanyName,
                Position=excluded.Position,
                YearsOfExperienceRequired=excluded.YearsOfExperienceRequired,
                JobLocation=excluded.JobLocation,
                JobDescription=excluded.JobDescription,
                JobPostingDate=excluded.JobPostingDate,
                IsOpen=excluded.IsOpen,
                PointsOfContact=excluded.PointsOfContact,
                PointsOfContactEmail=excluded.PointsOfContactEmail,
                Notes=excluded.Notes
            RETURNING Id;
            """,
            (
                anonymous_session_id,
                job.company_name,
                job.position,
                job.years_of_experience_required,
                job.job_location,
                job.job_description,
                job.job_url,
                posting_date,
                is_open,
                job.point_of_contact,
                job.point_of_contact_email,
                job.notes,
            ),
        )

        job_id = cursor.fetchone()[0]
        conn.commit()
        return job_id

    except sqlite3.Error as e:
        print(f"An error occurred while saving the job to the database: {e}")
        raise

    finally:
        if conn:
            conn.close()


def get_job_by_id(
    job_id: int,
    anonymous_session_id: str | None = None,
) -> dict | None:
    """Fetch one job row as a dict (or None if not found)."""
    conn = None
    try:
        HERE = Path(__file__).resolve().parent
        db_path = HERE / "job-tracker.db"

        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if anonymous_session_id is None:
            cursor.execute("SELECT * FROM JobDetails WHERE Id = ?", (job_id,))
        else:
            cursor.execute(
                """
                SELECT * FROM JobDetails
                WHERE Id = ? AND AnonymousSessionId = ?;
                """,
                (job_id, anonymous_session_id),
            )
        row = cursor.fetchone()
        return dict(row) if row else None

    except sqlite3.Error as e:
        print(f"An error occurred while reading the job from the database: {e}")
        raise

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    pass
