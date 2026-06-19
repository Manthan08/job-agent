"""Persistence (AI-owned plumbing): save an InterviewPrepPack to PreparationMaterials.

One PreparationMaterials row holds the generated prep pack for one
JobApplications row (the resume x job join). Re-running generation is made
idempotent by DELETE-then-INSERT keyed on (JobApplicationId, MaterialType) in a
single transaction — the table has no UNIQUE constraint, so we enforce
"one prep pack per application per type" here.

Column mapping (the schema predates this model, so we map pragmatically):
  * MaterialType       = "interview_prep"
  * MaterialContent    = full pack as JSON (canonical record, incl. overview)
  * InterviewQuestions = JSON list of the question strings (queryable)
  * STARResponses      = JSON list of the full Q&A objects (question + answer +
                         grounded_in + topic + is_gap)
  * STARQuestions      = JSON list of study_topics (the gaps to revise)
"""
import json
import sqlite3
from pathlib import Path

from db.public_safety import ensure_public_safety_schema
from models.preparation import InterviewPrepPack

MATERIAL_TYPE = "interview_prep"


def get_application_id(
    resume_id: int,
    job_id: int,
    anonymous_session_id: str | None = None,
) -> int | None:
    """Look up the JobApplications.Id for a (resume, job) pair, if it exists."""
    conn = None
    try:
        db_path = Path(__file__).resolve().parent / "job-tracker.db"
        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        if anonymous_session_id is None:
            row = conn.execute(
                "SELECT Id FROM JobApplications WHERE ResumeId = ? AND JobId = ?;",
                (resume_id, job_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT Id FROM JobApplications
                WHERE ResumeId = ? AND JobId = ? AND AnonymousSessionId = ?;
                """,
                (resume_id, job_id, anonymous_session_id),
            ).fetchone()
        return row[0] if row else None
    finally:
        if conn:
            conn.close()


def save_prep_to_db(
    job_application_id: int,
    pack: InterviewPrepPack,
    anonymous_session_id: str | None = None,
) -> int:
    """Insert (replacing any prior pack) the prep pack; return its row Id."""
    conn = None
    try:
        db_path = Path(__file__).resolve().parent / "job-tracker.db"
        conn = sqlite3.connect(db_path)
        ensure_public_safety_schema(conn)
        cursor = conn.cursor()

        questions = [q.question for q in pack.questions]
        responses = [q.model_dump() for q in pack.questions]

        # Idempotent: clear any existing pack for this application+type first.
        cursor.execute(
            "DELETE FROM PreparationMaterials "
            "WHERE JobApplicationId = ? AND MaterialType = ?;",
            (job_application_id, MATERIAL_TYPE),
        )
        cursor.execute(
            """
            INSERT INTO PreparationMaterials
                (AnonymousSessionId, JobApplicationId, MaterialType, MaterialContent,
                 InterviewQuestions, STARResponses, STARQuestions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING Id;
            """,
            (
                anonymous_session_id,
                job_application_id,
                MATERIAL_TYPE,
                pack.model_dump_json(),
                json.dumps(questions),
                json.dumps(responses),
                json.dumps(pack.study_topics),
            ),
        )
        prep_id = cursor.fetchone()[0]
        conn.commit()
        return prep_id

    except sqlite3.Error as e:
        print(f"An error occurred while saving prep materials: {e}")
        raise
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    pass
