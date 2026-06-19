"""Adapter for generic Workday job postings.

Workday career pages are JS-rendered, but every posting has a clean JSON twin
behind the "CXS" API. We convert a human page URL into its CXS URL, fetch the
JSON, strip the HTML out of the description, and map to JobDetailsModel.

Page URL:
  https://<tenant>.wdN.myworkdayjobs.com/en-US/<site>/job/<path>?<tracking>
CXS URL:
  https://<tenant>.wdN.myworkdayjobs.com/wday/cxs/<tenant>/<site>/job/<path>

Run:  python -m phase2_search.workday
"""

import html
import re
from urllib.parse import urlsplit

import requests
import truststore
from dotenv import load_dotenv

from models.jobs import JobDetailsModel
from phase2_search.urls import normalize_job_url

truststore.inject_into_ssl()
load_dotenv()

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n\s*\n\s*\n+")


def _strip_html(raw: str) -> str:
    """Turn Workday's HTML description into readable plain text."""
    if not raw:
        return ""
    # Preserve block structure as line breaks before stripping tags.
    text = re.sub(r"</(p|div|li|ul|ol|h\d|br)\s*>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub("\n\n", text)
    return text.strip()


def page_url_to_cxs_url(page_url: str) -> str:
    """Derive the CXS JSON endpoint from a Workday page URL."""
    parts = urlsplit(page_url)
    tenant = parts.netloc.split(".")[0]

    segments = [s for s in parts.path.split("/") if s]
    # Drop a leading locale like 'en-US' if present.
    if segments and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", segments[0]):
        segments = segments[1:]

    site = segments[0]
    job_path = "/".join(segments[2:])  # everything after '<site>/job/'

    return f"{parts.scheme}://{parts.netloc}/wday/cxs/{tenant}/{site}/job/{job_path}"


def fetch_workday_job(page_url: str) -> JobDetailsModel:
    """Fetch one Workday posting and map it to JobDetailsModel."""
    cxs_url = page_url_to_cxs_url(page_url)
    resp = requests.get(cxs_url, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()

    info = resp.json().get("jobPostingInfo", {})

    hiring_organization = info.get("hiringOrganization") or {}
    if isinstance(hiring_organization, dict):
        hiring_organization_name = hiring_organization.get("name")
    else:
        hiring_organization_name = str(hiring_organization)

    company = (
        info.get("company")
        or hiring_organization_name
        or urlsplit(page_url).netloc.split(".")[0].replace("-", " ").title()
    )

    return JobDetailsModel(
        company_name=company,
        position=info.get("title") or "Unknown",
        job_location=info.get("location"),
        job_description=_strip_html(info.get("jobDescription", "")),
        job_url=normalize_job_url(info.get("externalUrl") or page_url),
        job_posting_date=_parse_date(info.get("startDate")),
        is_open=True,
        notes=f"Req {info.get('jobReqId')}" if info.get("jobReqId") else None,
    )


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


if __name__ == "__main__":
    from db.job_repository import save_job_to_db

    urls = [
        "https://example.wd1.myworkdayjobs.com/en-US/External/job/Example-Role_REQ123",
    ]
    for u in urls:
        job = fetch_workday_job(u)
        job_id = save_job_to_db(job)
        print(f"saved Id={job_id}: {job.company_name} — {job.position} ({job.job_location})")
