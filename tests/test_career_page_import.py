import unittest
from unittest.mock import patch

import requests

from phase2_search.urls import normalize_job_url
from phase2_search.career_page import (
    fetch_career_page_job,
    validate_career_page_url,
)


CAREER_PAGE_HTML = """
<!doctype html>
<html>
  <head>
    <meta property="og:title" content="Backend Developer" />
    <script type="application/ld+json">
      {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "Backend Developer",
        "datePosted": "2025-12-08",
        "jobLocation": {
          "@type": "Place",
          "address": {
            "@type": "PostalAddress",
            "addressCountry": "India"
          }
        }
      }
    </script>
  </head>
  <body>
    <h1>Backend Developer</h1>
    <div><strong>Location</strong></div>
    <div>India</div>
    <h2>A Snapshot of Your Day</h2>
    <p>We are seeking a highly skilled Senior Software Developer.</p>
    <h2>What You Bring</h2>
    <ul>
      <li>5+ years of experience in backend development</li>
      <li>Strong proficiency in either C# .NET or Python</li>
      <li>Experience with RESTful APIs and microservices architecture</li>
    </ul>
    <script>alert("do not keep me")</script>
  </body>
</html>
"""


class FakeResponse:
    def __init__(self, content: bytes, url: str):
        self.status_code = 200
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.url = url
        self._content = content

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield self._content

    def close(self):
        return None


class CareerPageImportTests(unittest.TestCase):
    def test_validate_rejects_http(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            validate_career_page_url("http://jobs.example.com/jobs/123")

    def test_validate_rejects_private_ip(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            validate_career_page_url("https://127.0.0.1/jobs/123")

    def test_validate_rejects_non_career_path(self):
        with patch(
            "phase2_search.career_page._resolve_public_ips",
            return_value=["93.184.216.34"],
        ):
            with self.assertRaisesRegex(ValueError, "career or job posting"):
                validate_career_page_url("https://example.com/about")

    def test_fetch_maps_static_career_page_to_job_model(self):
        page_url = (
            "https://careers.example.com/en_US/jobs/FolderDetail/"
            "Backend-Developer/286677"
        )

        def fake_get(url, **kwargs):
            return FakeResponse(CAREER_PAGE_HTML.encode("utf-8"), url)

        with (
            patch(
                "phase2_search.career_page._resolve_public_ips",
                return_value=["93.184.216.34"],
            ),
            patch.object(requests, "get", side_effect=fake_get),
        ):
            job = fetch_career_page_job(page_url)

        self.assertEqual(job.company_name, "Example Energy")
        self.assertEqual(job.position, "Backend Developer")
        self.assertEqual(job.job_location, "India")
        self.assertIn("Strong proficiency in either C# .NET or Python", job.job_description)
        self.assertNotIn("alert", job.job_description)
        self.assertEqual(job.job_url, normalize_job_url(page_url))


if __name__ == "__main__":
    unittest.main()
