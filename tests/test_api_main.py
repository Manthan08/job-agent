import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from models.match import MatchResult


RESUME = {
    "Id": 1,
    "Name": "Test Candidate",
    "CurrentPosition": "Senior Engineer",
    "Email": "test@example.com",
    "OriginalFileName": "resume.pdf",
}

JOB = {
    "Id": 3,
    "CompanyName": "Acme",
    "Position": "AI Engineer",
    "JobLocation": "Remote",
}

APPLICATION = {
    "Id": 9,
    "MatchScorePercent": 72,
    "MatchReasoning": "Strong .NET fit.",
    "MatchedSkills": [".NET", "Azure"],
    "MissingSkills": ["RAG"],
    "Status": None,
    "TailoredResumeId": None,
}


class ApiMainTests(unittest.TestCase):
    def setUp(self):
        from api.main import app

        self.client = TestClient(app)

    def test_bootstrap_returns_selector_data_and_feature_flags(self):
        with (
            patch("api.main.svc.list_resumes", return_value=[RESUME]),
            patch("api.main.svc.list_jobs", return_value=[JOB]),
            patch("api.main.svc.prep_pack_enabled", return_value=False),
            patch("api.main.svc.coach_is_ready", return_value=True),
        ):
            response = self.client.get("/api/bootstrap")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resumes"], [RESUME])
        self.assertEqual(response.json()["jobs"], [JOB])
        self.assertEqual(response.json()["features"]["prep_pack_enabled"], False)
        self.assertEqual(response.json()["features"]["coach_ready"], True)

    def test_get_pair_state_includes_application_and_tailored_pdf_flag(self):
        with (
            patch("api.main.svc.get_application", return_value=APPLICATION),
            patch("api.main.svc.get_tailored_pdf_path", return_value=None),
            patch("api.main.svc.get_existing_prep", return_value=None),
        ):
            response = self.client.get("/api/pairs/1/3")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["application"]["Id"], 9)
        self.assertEqual(body["tailored_pdf_available"], False)
        self.assertIsNone(body["prep_pack"])

    def test_score_returns_match_result_and_application_state(self):
        match = MatchResult(
            match_score=82,
            reasoning="Strong overlap.",
            matched_skills=[".NET"],
            missing_skills=["RAG"],
        )

        with (
            patch("api.main.svc.run_score", return_value=(match, 12)),
            patch("api.main.svc.get_application", return_value=APPLICATION),
            patch("api.main.svc.get_tailored_pdf_path", return_value=None),
            patch("api.main.svc.get_existing_prep", return_value=None),
        ):
            response = self.client.post(
                "/api/score", json={"resume_id": 1, "job_id": 3}
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["application_id"], 12)
        self.assertEqual(body["match"]["match_score"], 82)
        self.assertEqual(body["pair_state"]["application"]["Id"], 9)

    def test_coach_returns_reply(self):
        with patch("api.main.svc.coach_reply", return_value="Use your .NET evidence."):
            response = self.client.post(
                "/api/coach",
                json={"resume_id": 1, "job_id": 3, "message": "How do I answer?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "Use your .NET evidence.")


if __name__ == "__main__":
    unittest.main()
