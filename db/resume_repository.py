import json
import sqlite3
from pathlib import Path

from db.public_safety import ensure_public_safety_schema
from models.resume import ResumeModel

def save_resume_to_db(
    resume: ResumeModel,
    resume_path: str,
    anonymous_session_id: str | None = None,
) -> int:
    
    # Implement the logic to save the resume data to the database
    try:
        conn = None
        
        HERE = Path(__file__).resolve().parent
        db_path = HERE / 'job-tracker.db'
        
        skills_json = json.dumps(resume.skills)  # Convert list to JSON string for storage
        
        experience_json = json.dumps(
            [item.model_dump() for item in resume.experience]
            if resume.experience else []  # Convert list of ExperienceItem to JSON string
        )

        urls_json = json.dumps(resume.urls or [])
        projects_json = json.dumps(
            [p.model_dump() for p in resume.projects] if resume.projects else []
        )
        
        resume_path = Path(resume_path).resolve()  # Ensure resume_path is a Path object and resolve it to an absolute path
        

        # Connect to the SQLite database (it will be created if it doesn't exist)
        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        
        # Create Cursor object to execute SQL commands
        cursor = conn.cursor()

        # Insert ResumeModel data into ResumeDetails table
        cursor.execute("""
            INSERT INTO ResumeDetails (
                AnonymousSessionId, Name, Email, Skills, Experience, Phone, Urls, Location,
                CurrentPosition, Summary, Projects, Education,
                OriginalFileName, OriginalFilePath
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(Email, OriginalFilePath) 
            DO UPDATE SET
                AnonymousSessionId=excluded.AnonymousSessionId,
                Name=excluded.Name,
                Skills=excluded.Skills,
                Experience=excluded.Experience,
                Phone=excluded.Phone,
                Urls=excluded.Urls,
                Location=excluded.Location,
                CurrentPosition=excluded.CurrentPosition,
                Summary=excluded.Summary,
                Projects=excluded.Projects,
                Education=excluded.Education
            RETURNING ID;
        """, (
            anonymous_session_id,
            resume.name,
            str(resume.email),
            skills_json,
            experience_json,
            resume.phone,
            urls_json,
            resume.location,
            resume.current_position,
            resume.summary,
            projects_json,
            resume.education,
            resume_path.name,
            str(resume_path)
        ))
        
        resume_id = cursor.fetchone()[0]  # Get the ID of the inserted or updated resume

        # Commit the changes and close the connection
        conn.commit()
        
        print(f"Resume data saved successfully to the database at {db_path}")
        
        return resume_id  # Return the ID of the inserted resume

    except sqlite3.Error as e:
        print(f"An error occurred while saving the resume to the database: {e}")
        raise 

    finally:
        if conn:
            conn.close()

def save_tailored_resume_link(
    original_resume_id: int,
    job_id: int,
    tailored,
    candidate_name: str,
    candidate_email: str,
    pdf_path,
    source_resume: dict | None = None,
    status: str = "Not Applied",
    anonymous_session_id: str | None = None,
) -> int:
    """Persist the generated tailored resume and link it to its application.

    Two writes in ONE transaction (atomic — both succeed or neither):
      1. Upsert a ResumeDetails row representing the tailored output. Its natural key
         is UNIQUE(Email, OriginalFilePath); we use the tailored PDF path as
         OriginalFilePath so it is distinct from the source resume row and idempotent
         on re-run (same job -> same row updated, never a duplicate).
      2. Upsert JobApplications for (original_resume_id, job_id) and set its
         TailoredResumeId to the tailored row's Id.

    `tailored` is a TailoredResumeModel; we store its tailored_summary /
    tailored_skills / tailored_experience. Source resume facts such as phone,
    location, projects, and education are carried over unchanged.

    Returns the tailored ResumeDetails.Id.
    """
    conn = None
    try:
        HERE = Path(__file__).resolve().parent
        db_path = HERE / "job-tracker.db"

        pdf_path = Path(pdf_path).resolve()
        source_resume = source_resume or {}
        skills_json = json.dumps([c.model_dump() for c in tailored.tailored_skills])
        experience_json = json.dumps([e.model_dump() for e in tailored.tailored_experience])

        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO ResumeDetails (
                AnonymousSessionId, Name, Email, Skills, Experience, Phone, Urls, Location,
                CurrentPosition, Summary, Projects, Education,
                OriginalFileName, OriginalFilePath
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(Email, OriginalFilePath) DO UPDATE SET
                AnonymousSessionId=excluded.AnonymousSessionId,
                Name=excluded.Name,
                Skills=excluded.Skills,
                Experience=excluded.Experience,
                Phone=excluded.Phone,
                Urls=excluded.Urls,
                Location=excluded.Location,
                CurrentPosition=excluded.CurrentPosition,
                Summary=excluded.Summary,
                Projects=excluded.Projects,
                Education=excluded.Education
            RETURNING Id;
            """,
            (
                anonymous_session_id,
                candidate_name,
                candidate_email,
                skills_json,
                experience_json,
                source_resume.get("Phone"),
                source_resume.get("Urls"),
                source_resume.get("Location"),
                source_resume.get("CurrentPosition"),
                tailored.tailored_summary,
                source_resume.get("Projects"),
                source_resume.get("Education"),
                pdf_path.name,
                str(pdf_path),
            ),
        )
        tailored_resume_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO JobApplications (
                AnonymousSessionId, ResumeId, JobId, Status, TailoredResumeId
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ResumeId, JobId) DO UPDATE SET
                AnonymousSessionId=excluded.AnonymousSessionId,
                TailoredResumeId=excluded.TailoredResumeId;
            """,
            (
                anonymous_session_id,
                original_resume_id,
                job_id,
                status,
                tailored_resume_id,
            ),
        )

        conn.commit()
        return tailored_resume_id

    except sqlite3.Error as e:
        print(f"An error occurred while linking the tailored resume: {e}")
        raise

    finally:
        if conn:
            conn.close()


def get_resume_by_id(
    resume_id: int,
    anonymous_session_id: str | None = None,
) -> dict | None:
    """Fetch one resume row as a dict (or None if not found)."""
    conn = None
    try:
        HERE = Path(__file__).resolve().parent
        db_path = HERE / "job-tracker.db"

        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if anonymous_session_id is None:
            cursor.execute("SELECT * FROM ResumeDetails WHERE Id = ?", (resume_id,))
        else:
            cursor.execute(
                """
                SELECT * FROM ResumeDetails
                WHERE Id = ? AND AnonymousSessionId = ?;
                """,
                (resume_id, anonymous_session_id),
            )
        row = cursor.fetchone()
        return dict(row) if row else None

    except sqlite3.Error as e:
        print(f"An error occurred while reading the resume from the database: {e}")
        raise

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    pass
    
    
