import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from models.jobs import JobDetailsModel
from webapp import services as svc


class SecurityGuardrailTests(unittest.TestCase):
    def test_api_upload_rejects_non_pdf_before_parsing(self):
        from api.main import app

        client = TestClient(app)
        with patch("api.main.svc.parse_and_save_uploaded_resume") as parser:
            response = client.post(
                "/api/resumes/upload",
                files={"file": ("resume.txt", b"not a pdf", "text/plain")},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("PDF", response.json()["detail"])
        parser.assert_not_called()

    def test_api_upload_rejects_oversized_pdf_before_parsing(self):
        from api.main import MAX_PDF_UPLOAD_BYTES, app

        client = TestClient(app)
        with patch("api.main.svc.parse_and_save_uploaded_resume") as parser:
            response = client.post(
                "/api/resumes/upload",
                files={
                    "file": (
                        "resume.pdf",
                        b"x" * (MAX_PDF_UPLOAD_BYTES + 1),
                        "application/pdf",
                    )
                },
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("too large", response.json()["detail"])
        parser.assert_not_called()

    def test_service_rejects_spoofed_pdf_bytes_before_saving(self):
        with TemporaryDirectory() as tmpdir:
            with patch.object(svc, "RESUMES_DIR", Path(tmpdir)):
                with self.assertRaisesRegex(ValueError, "valid PDF"):
                    svc.parse_and_save_uploaded_resume(
                        b"MZ fake executable bytes", "resume.pdf"
                    )

            self.assertEqual(list(Path(tmpdir).iterdir()), [])

    def test_ingest_job_from_url_rejects_non_career_urls_before_fetch(self):
        with (
            patch(
                "phase2_search.career_page.validate_career_page_url",
                side_effect=ValueError("URL must look like a career or job posting."),
            ),
            patch("phase2_search.career_page.fetch_career_page_job") as fetcher,
        ):
            with self.assertRaisesRegex(ValueError, "career or job posting"):
                svc.ingest_job_from_url("https://example.com/about")

        fetcher.assert_not_called()

    def test_ingest_job_from_url_rejects_localhost_before_fetch(self):
        with patch("phase2_search.career_page.fetch_career_page_job") as fetcher:
            with self.assertRaisesRegex(ValueError, "public HTTPS"):
                svc.ingest_job_from_url("https://localhost/jobs/backend-developer")

        fetcher.assert_not_called()

    def test_ingest_job_from_url_accepts_real_workday_host_shape(self):
        job = JobDetailsModel(
            company_name="Acme",
            position="Engineer",
            job_description="Build services.",
            job_url="https://acme.wd5.myworkdayjobs.com/site/job/123",
        )

        with (
            patch("phase2_search.workday.fetch_workday_job", return_value=job) as fetcher,
            patch.object(svc, "save_job_to_db", return_value=42) as saver,
        ):
            job_id = svc.ingest_job_from_url(
                "https://acme.wd5.myworkdayjobs.com/en-US/site/job/123"
            )

        self.assertEqual(job_id, 42)
        fetcher.assert_called_once()
        saver.assert_called_once_with(job)

    def test_ingest_job_from_url_accepts_public_career_url(self):
        job = JobDetailsModel(
            company_name="Example Energy",
            position="Backend Developer",
            job_description="Build backend services with C# and Python.",
            job_url="https://careers.example.com/en_US/jobs/FolderDetail/Backend-Developer/286677",
        )

        with (
            patch(
                "phase2_search.career_page.validate_career_page_url",
                return_value=(
                    "https://careers.example.com/en_US/jobs/FolderDetail/"
                    "Backend-Developer/286677"
                ),
            ),
            patch("phase2_search.career_page.fetch_career_page_job", return_value=job) as fetcher,
            patch.object(svc, "save_job_to_db", return_value=43) as saver,
        ):
            job_id = svc.ingest_job_from_url(
                "https://careers.example.com/en_US/jobs/FolderDetail/Backend-Developer/286677"
            )

        self.assertEqual(job_id, 43)
        fetcher.assert_called_once()
        saver.assert_called_once_with(job)

    def test_coach_rejects_oversized_message_before_graph_call(self):
        with self.assertRaisesRegex(ValueError, "Coach message is too long"):
            svc.coach_reply(1, 3, "x" * (svc.MAX_COACH_MESSAGE_CHARS + 1))

    def test_default_coach_message_limit_is_conservative(self):
        self.assertLessEqual(svc.MAX_COACH_MESSAGE_CHARS, 1000)


if __name__ == "__main__":
    unittest.main()
