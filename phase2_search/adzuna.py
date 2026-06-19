import os
import json
from datetime import datetime

import requests
import truststore
from dotenv import load_dotenv

from models.jobs import JobDetailsModel
from phase2_search.urls import normalize_job_url

# Trust the OS (Windows) certificate store so the corporate proxy's root CA is
# recognized. Must run before any HTTPS call is made.
truststore.inject_into_ssl()

# Load environment variables from .env file
load_dotenv()

# Adzuna API credentials
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
ADZUNA_BASE_URL = os.getenv("ADZUNA_BASE_URL", "https://api.adzuna.com/v1/api")

# Function to fetch job listings from Adzuna API
def fetch_adzuna_jobs(what: str, where: str, country: str = "in", page: int = 1, results_per_page: int = 20, max_days_old: int = 5) -> dict:
    # country: The country code for the job search (e.g., "in" for India, "us" for USA) 
    # page: The page number of results to fetch (pagination)
    # results_per_page: The number of job listings to return per page (max 50 for Adzuna)
    # max_days_old: Filter jobs posted within the last N days (e.g., 5 for jobs posted in the last 5 days)
    
    url = f"{ADZUNA_BASE_URL}/jobs/{country}/search/{page}"
    
    params = {
        "app_id": ADZUNA_APP_ID,    
        "app_key": ADZUNA_APP_KEY,
        "what": what,
        "where": where,
        "results_per_page": results_per_page,
        "max_days_old": max_days_old,
        "sort_by": "date"  # Sort results by date (most recent first)   
    }
    
    response = requests.get(url, params=params)
    response.raise_for_status()  # Raise an exception for HTTP errors
    
    print(f"GET {url}  what={what!r} where={where!r}")
    
    return response.json()


def _parse_created(created: str | None):
    """Adzuna 'created' is ISO-8601 with a trailing 'Z'. Return a date or None."""
    if not created:
        return None
    # Python's fromisoformat accepts '+00:00' but not 'Z' before 3.11; be safe.
    return datetime.fromisoformat(created.replace("Z", "+00:00")).date()


def map_adzuna_result(result: dict) -> JobDetailsModel:
    """Map one element of jobs['results'] to a JobDetailsModel."""
    company = result.get("company") or {}
    location = result.get("location") or {}

    return JobDetailsModel(
        company_name=company.get("display_name") or "Unknown",
        position=result.get("title") or "Unknown",
        job_location=location.get("display_name"),
        job_description=result.get("description") or "",
        job_url=normalize_job_url(result.get("redirect_url") or ""),
        job_posting_date=_parse_created(result.get("created")),
        is_open=True,  # a job returned by a fresh search is assumed open
    )


if __name__ == "__main__":
    # Example usage
    try:
        jobs = fetch_adzuna_jobs(what="software engineer", where="Bangalore", country="in")

        if len(jobs["results"]) > 0:
            model = map_adzuna_result(jobs["results"][0])
            print(model.model_dump_json(indent=2))
        else:
            print("No jobs found for the given criteria.")

    except requests.HTTPError as e:
        print(f"HTTP error occurred: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")