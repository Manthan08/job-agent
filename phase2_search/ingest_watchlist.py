"""Ingest a hand-curated job watchlist (data/job_watchlist.csv) into the DB.

This is the manual counterpart to an API search: you paste job URLs + the JD
text you copied from the posting, and this loads them as JobDetailsModel rows so
the later AI phases (match scoring, RAG resume tailoring) have real input.

Run:  python -m phase2_search.ingest_watchlist
"""

import csv
from pathlib import Path

from db.job_repository import save_job_to_db
from models.jobs import JobDetailsModel
from phase2_search.urls import normalize_job_url

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_CSV = REPO_ROOT / "data" / "job_watchlist.csv"


def _clean(value: str | None) -> str | None:
    """Trim whitespace; turn empty strings into None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_years(value: str | None) -> int | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def row_to_job(row: dict) -> JobDetailsModel | None:
    """Map one CSV row to a JobDetailsModel, or None if it's unusable."""
    job_url = _clean(row.get("job_url"))
    job_description = _clean(row.get("job_description"))
    company_name = _clean(row.get("company_name"))
    position = _clean(row.get("position"))

    # Required by the schema / model — skip incomplete rows loudly.
    if not (job_url and job_description and company_name and position):
        print(f"  SKIP (missing required field): {job_url or '<no url>'}")
        return None

    return JobDetailsModel(
        company_name=company_name,
        position=position,
        years_of_experience_required=_parse_years(row.get("years_of_experience_required")),
        job_location=_clean(row.get("job_location")),
        job_description=job_description,
        job_url=normalize_job_url(job_url),
        notes=_clean(row.get("notes")),
    )


def ingest_watchlist(csv_path: Path = WATCHLIST_CSV) -> int:
    """Load every row of the watchlist CSV into the DB. Return count saved."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Watchlist not found: {csv_path}")

    saved = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            job = row_to_job(row)
            if job is None:
                continue
            job_id = save_job_to_db(job)
            print(f"  saved Id={job_id}: {job.company_name} — {job.position}")
            saved += 1

    print(f"Ingested {saved} job(s) from {csv_path}")
    return saved


if __name__ == "__main__":
    ingest_watchlist()
