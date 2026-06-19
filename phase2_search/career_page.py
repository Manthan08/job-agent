"""Safe static career-page importer for non-Workday job URLs.

This adapter intentionally does not execute JavaScript. It fetches public HTTPS
HTML, strips active markup, extracts readable text and common JobPosting
metadata, then maps the result to JobDetailsModel.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
from datetime import date
from email.message import Message
from urllib.parse import urljoin, urlsplit

import requests
import truststore
from dotenv import load_dotenv

from models.jobs import JobDetailsModel
from phase2_search.urls import normalize_job_url

truststore.inject_into_ssl()
load_dotenv()

MAX_CAREER_PAGE_BYTES = int(os.getenv("MAX_CAREER_PAGE_BYTES", "750000"))
MAX_CAREER_PAGE_TEXT_CHARS = int(os.getenv("MAX_CAREER_PAGE_TEXT_CHARS", "30000"))
CAREER_PAGE_TIMEOUT_SECONDS = int(os.getenv("CAREER_PAGE_TIMEOUT_SECONDS", "15"))
CAREER_PAGE_MAX_REDIRECTS = int(os.getenv("CAREER_PAGE_MAX_REDIRECTS", "3"))

_CAREER_TERMS = {
    "career",
    "careers",
    "job",
    "jobs",
    "position",
    "posting",
    "requisition",
    "opening",
    "folderdetail",
}
_UNSAFE_TAG_RE = re.compile(
    r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_JSON_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
_META_RE = re.compile(
    r"<meta\s+[^>]*(?:property|name)=[\"']([^\"']+)[\"'][^>]*content=[\"']([^\"']*)[\"'][^>]*>",
    flags=re.IGNORECASE | re.DOTALL,
)


def validate_career_page_url(page_url: str) -> str:
    """Validate that a user-supplied URL is safe enough for server-side fetch."""
    url = (page_url or "").strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()

    if (
        parts.scheme.lower() != "https"
        or not host
        or parts.username
        or parts.password
        or (parts.port is not None and parts.port != 443)
    ):
        raise ValueError("Use a public HTTPS career or job posting URL.")

    _validate_public_host(host)

    career_hint = f"{host} {parts.path}".lower()
    if not any(term in career_hint for term in _CAREER_TERMS):
        raise ValueError(
            "URL must look like a career or job posting. Please paste the JD "
            "for unsupported sites."
        )

    return url


def fetch_career_page_job(page_url: str) -> JobDetailsModel:
    """Fetch a static public career page and map it to JobDetailsModel."""
    final_url, raw_html = _fetch_html(validate_career_page_url(page_url))
    metadata = _extract_meta(raw_html)
    jobposting = _extract_jobposting(raw_html) or {}
    text = _html_to_text(raw_html)
    lines = [line for line in text.splitlines() if line.strip()]

    title = _extract_title(jobposting, metadata, raw_html, final_url)
    company = _extract_company(jobposting, metadata, final_url)
    location = _extract_location(jobposting, lines)
    description = _extract_description(lines, title, metadata)

    if len(description) < 120:
        raise ValueError(
            "Could not extract enough job description text from this page. "
            "Please paste the JD instead."
        )

    return JobDetailsModel(
        company_name=company,
        position=title,
        job_location=location,
        job_description=description[:MAX_CAREER_PAGE_TEXT_CHARS],
        job_url=normalize_job_url(final_url),
        job_posting_date=_parse_date(jobposting.get("datePosted")),
        is_open=True,
    )


def _fetch_html(page_url: str) -> tuple[str, str]:
    url = page_url
    for _ in range(CAREER_PAGE_MAX_REDIRECTS + 1):
        validate_career_page_url(url)
        response = requests.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "ResumeBuddyJobImporter/1.0",
            },
            timeout=CAREER_PAGE_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
        try:
            if 300 <= response.status_code < 400 and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue

            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if content_type and "html" not in content_type:
                raise ValueError("URL did not return an HTML job posting.")

            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_CAREER_PAGE_BYTES:
                    raise ValueError(
                        "Career page is too large to import safely. Please paste the JD."
                    )

            return url, _decode_response_body(bytes(content), content_type)
        finally:
            response.close()

    raise ValueError("Career page redirected too many times. Please paste the JD.")


def _decode_response_body(content: bytes, content_type: str) -> str:
    message = Message()
    message["content-type"] = content_type
    charset = message.get_content_charset() or "utf-8"
    try:
        return content.decode(charset, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def _validate_public_host(host: str) -> None:
    blocked_names = {"localhost", "metadata.google.internal"}
    if host in blocked_names or host.endswith(".localhost"):
        raise ValueError("Use a public HTTPS career or job posting URL.")

    for ip in _resolve_public_ips(host):
        address = ipaddress.ip_address(ip)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("Use a public HTTPS career or job posting URL.")


def _resolve_public_ips(host: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass

    results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({item[4][0] for item in results})


def _extract_meta(raw_html: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for name, content in _META_RE.findall(raw_html):
        metadata[name.lower()] = html.unescape(content).strip()
    return metadata


def _extract_jobposting(raw_html: str) -> dict | None:
    for raw_json in _SCRIPT_JSON_RE.findall(raw_html):
        try:
            parsed = json.loads(html.unescape(raw_json).strip())
        except json.JSONDecodeError:
            continue
        found = _find_jobposting(parsed)
        if found:
            return found
    return None


def _find_jobposting(value) -> dict | None:
    if isinstance(value, list):
        for item in value:
            found = _find_jobposting(item)
            if found:
                return found
    if isinstance(value, dict):
        raw_type = value.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(item).lower() == "jobposting" for item in types):
            return value
        for child in value.values():
            found = _find_jobposting(child)
            if found:
                return found
    return None


def _html_to_text(raw_html: str) -> str:
    body = re.search(r"<body\b[^>]*>(.*?)</body>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    source = body.group(1) if body else raw_html
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    source = _UNSAFE_TAG_RE.sub("", source)
    source = re.sub(r"<li\b[^>]*>", "\n- ", source, flags=re.IGNORECASE)
    source = re.sub(
        r"</(p|div|section|article|li|ul|ol|h\d|br|tr|table)\s*>",
        "\n",
        source,
        flags=re.IGNORECASE,
    )
    source = _TAG_RE.sub("", source)
    source = html.unescape(source)
    lines = [re.sub(r"\s+", " ", line).strip() for line in source.splitlines()]
    return "\n".join(_dedupe_adjacent([line for line in lines if line]))


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return deduped


def _extract_title(
    jobposting: dict,
    metadata: dict[str, str],
    raw_html: str,
    final_url: str,
) -> str:
    title = (
        _clean_value(jobposting.get("title"))
        or metadata.get("og:title")
        or metadata.get("title")
        or _title_tag(raw_html)
        or _title_from_path(final_url)
    )
    return _clean_title(title)


def _title_tag(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(match.group(1)).strip() if match else ""


def _title_from_path(final_url: str) -> str:
    segments = [segment for segment in urlsplit(final_url).path.split("/") if segment]
    for segment in reversed(segments):
        if not segment.isdigit():
            return _title_case_slug(segment)
    return "Imported role"


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0].strip()
    return cleaned[:200] or "Imported role"


def _extract_company(
    jobposting: dict,
    metadata: dict[str, str],
    final_url: str,
) -> str:
    organization = jobposting.get("hiringOrganization")
    if isinstance(organization, dict):
        name = _clean_value(organization.get("name"))
        if name:
            return name[:160]
    if metadata.get("og:site_name"):
        return metadata["og:site_name"][:160]
    return _company_from_host(urlsplit(final_url).hostname or "")


def _company_from_host(host: str) -> str:
    host = host.lower()
    labels = [label for label in host.split(".") if label not in {"www", "jobs", "job", "careers", "career"}]
    if not labels:
        return "Imported Company"
    return _title_case_slug(labels[0])[:160]


def _title_case_slug(value: str) -> str:
    words = re.split(r"[-_\s]+", value)
    return " ".join(word.capitalize() for word in words if word) or "Imported Company"


def _extract_location(jobposting: dict, lines: list[str]) -> str | None:
    location = jobposting.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            parts = [
                _clean_value(address.get(key))
                for key in ("addressLocality", "addressRegion", "addressCountry")
                if _clean_value(address.get(key))
            ]
            if parts:
                return ", ".join(parts)
        if _clean_value(location.get("name")):
            return _clean_value(location.get("name"))

    for index, line in enumerate(lines):
        match = re.match(r"^(job\s+location|location)\s*[:\-–]\s*(.+)$", line, re.I)
        if match:
            return match.group(2).strip()[:160]
        if line.lower().rstrip(":") in {"job location", "location"}:
            for candidate in lines[index + 1 : index + 4]:
                if candidate.lower().rstrip(":") not in {"job location", "location"}:
                    return candidate[:160]
    return None


def _extract_description(
    lines: list[str],
    title: str,
    metadata: dict[str, str],
) -> str:
    description_lines = lines
    normalized_title = title.lower()
    for index, line in enumerate(lines):
        if line.lower() == normalized_title:
            description_lines = lines[index:]
            break

    description = "\n".join(description_lines).strip()
    if len(description) < 120 and metadata.get("og:description"):
        description = f"{metadata['og:description']}\n\n{description}".strip()
    return re.sub(r"\n{3,}", "\n\n", description)


def _clean_value(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
