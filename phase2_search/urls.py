"""URL normalization shared across job-source adapters.

A job's identity is the part of its URL *before* the query string. Tracking
params (utm_*, the Adzuna app_id, session tokens, etc.) vary between fetches of
the same posting, so leaving them in would defeat the ``UNIQUE(JobUrl)`` dedup
constraint and would also leak our API credentials into stored data.
"""

from urllib.parse import urlsplit, urlunsplit


def normalize_job_url(url: str) -> str:
    """Return the canonical form of a job URL: scheme + host + path, no query/fragment.

    Also lowercases scheme/host and strips a trailing slash so trivially
    different spellings of the same posting collapse to one key.
    """
    if not url:
        return url

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")

    return urlunsplit((scheme, netloc, path, "", ""))
