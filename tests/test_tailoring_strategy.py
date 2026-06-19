import unittest
from pathlib import Path
from unittest.mock import patch

from models.keyword_coverage import KeywordCoverageItem, KeywordCoverageReport
from models.tailored import SkillCategory, TailoredExperienceItem, TailoredResumeModel
from webapp import services as svc


class TailoringStrategyTests(unittest.TestCase):
    def test_tailoring_recommendation_uses_score_bands(self):
        self.assertEqual(svc.tailoring_recommendation(None)["status"], "needs_score")
        self.assertFalse(svc.tailoring_recommendation(None)["can_tailor"])

        low = svc.tailoring_recommendation(64)
        self.assertEqual(low["status"], "not_recommended")
        self.assertFalse(low["can_tailor"])
        self.assertIn("high chance of rejection", low["message"])

        stretch = svc.tailoring_recommendation(67)
        self.assertEqual(stretch["status"], "stretch")
        self.assertTrue(stretch["can_tailor"])

        optimize = svc.tailoring_recommendation(72)
        self.assertEqual(optimize["status"], "optimize")
        self.assertTrue(optimize["can_tailor"])
        self.assertEqual(optimize["target_score"], 85)

    def test_run_tailor_blocks_low_original_score_before_tailoring(self):
        resume = {"Id": 1, "Name": "Test Candidate", "Email": "test@example.com"}
        job = {"Id": 3, "CompanyName": "Acme", "Position": "AI Engineer"}
        application = {"Id": 9, "MatchScorePercent": 64}

        with (
            patch("webapp.services.get_resume_by_id", return_value=resume),
            patch("webapp.services.get_job_by_id", return_value=job),
            patch("webapp.services.get_application", return_value=application),
            patch(
                "webapp.services.tailor_resume_for_job",
                side_effect=AssertionError("tailoring should not run for low score"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "high chance of rejection"):
                svc.run_tailor(1, 3)

    def test_parse_confirmed_skills_normalizes_and_deduplicates_user_input(self):
        skills = svc.parse_confirmed_skills(
            " HTML, CSS\nJavaScript; Azure Service Bus, html "
        )

        self.assertEqual(
            skills,
            ["HTML", "CSS", "JavaScript", "Azure Service Bus"],
        )

    def test_ats_coverage_score_counts_direct_and_adjacent_keywords(self):
        from phase4_tailor.keyword_coverage import ats_coverage_score

        report = KeywordCoverageReport(
            direct_matches=[
                KeywordCoverageItem(
                    keyword="HTML",
                    jd_phrase="HTML",
                    bucket="direct",
                    importance="must_have",
                    resume_evidence="Confirmed by candidate.",
                    tailoring_instruction="Use in skills.",
                )
            ],
            adjacent_matches=[
                KeywordCoverageItem(
                    keyword="AWS SQS",
                    jd_phrase="AWS SQS",
                    bucket="adjacent",
                    importance="preferred",
                    resume_evidence="Azure Service Bus.",
                    tailoring_instruction="Bridge as message queue patterns.",
                )
            ],
            missing_keywords=[
                KeywordCoverageItem(
                    keyword="Kubernetes",
                    jd_phrase="Kubernetes",
                    bucket="missing",
                    importance="nice_to_have",
                    resume_evidence="",
                    tailoring_instruction="Do not claim it.",
                )
            ],
        )

        self.assertEqual(ats_coverage_score(report), 83)

    def test_run_tailor_uses_confirmed_skills_and_returns_ats_coverage(self):
        report = KeywordCoverageReport(
            direct_matches=[
                KeywordCoverageItem(
                    keyword="JavaScript",
                    jd_phrase="JavaScript",
                    bucket="direct",
                    importance="must_have",
                    resume_evidence="Candidate confirmed JavaScript.",
                    tailoring_instruction="Add to skills.",
                )
            ],
            adjacent_matches=[],
            missing_keywords=[],
        )
        tailored = TailoredResumeModel(
            tailored_summary="Senior engineer with **JavaScript**.",
            tailored_skills=[
                SkillCategory(
                    category="Languages & Frameworks",
                    skills=["**JavaScript**"],
                )
            ],
            tailored_experience=[
                TailoredExperienceItem(
                    company="Acme",
                    role_title="Engineer",
                    start_date="2020",
                    end_date=None,
                    bullets=["Delivered web features."],
                )
            ],
            skill_gaps=[],
            bridge_notes=[],
        )

        resume = {
            "Id": 1,
            "Name": "Test Candidate",
            "Email": "test@example.com",
            "Skills": "[]",
            "Experience": "[]",
        }
        job = {
            "Id": 3,
            "CompanyName": "Acme",
            "Position": "Frontend Engineer",
            "JobDescription": "JavaScript required",
        }
        application = {"Id": 9, "MatchScorePercent": 72}

        with (
            patch("webapp.services.get_resume_by_id", return_value=resume),
            patch("webapp.services.get_job_by_id", return_value=job),
            patch("webapp.services.get_application", return_value=application),
            patch(
                "webapp.services.analyze_keyword_coverage",
                return_value=report,
            ) as analyze,
            patch("webapp.services.tailor_resume_for_job", return_value=tailored) as tailor,
            patch("webapp.services.save_tailored_resume"),
            patch(
                "webapp.services.render_tailored_pdf",
                return_value=Path("data/tailored/Test_Candidate_Acme_Frontend_Engineer.pdf"),
            ),
            patch("webapp.services.save_tailored_resume_link"),
        ):
            result = svc.run_tailor(
                1,
                3,
                confirmed_skills_text="JavaScript, HTML",
            )

        analyze.assert_called_once()
        self.assertEqual(
            analyze.call_args.kwargs["confirmed_skills"],
            ["JavaScript", "HTML"],
        )
        tailor.assert_called_once()
        self.assertEqual(
            tailor.call_args.kwargs["confirmed_skills"],
            ["JavaScript", "HTML"],
        )
        self.assertEqual(result.ats_coverage_score, 100)
        self.assertEqual(result.keyword_report, report)


class TailoredArtifactNamingTests(unittest.TestCase):
    def test_tailored_artifact_filename_uses_name_company_position(self):
        from phase4_tailor.artifacts import compact_artifact_label, tailored_artifact_filename

        filename = tailored_artifact_filename(
            "Jane Candidate",
            "Example Company",
            "Senior Software Engineer: AI/I",
            "pdf",
        )

        self.assertEqual(
            filename,
            "Jane_Candidate_Example_Company_Senior_Software_Engineer_AI_I.pdf",
        )

        compact = compact_artifact_label(filename, max_chars=36)
        self.assertLessEqual(len(compact), 36)
        self.assertTrue(compact.endswith(".pdf"))
        self.assertIn("...", compact)

    def test_pair_state_returns_full_and_compact_pdf_filename(self):
        from api.main import AnonymousContext, _pair_state

        path = Path(
            "data/tailored/"
            "Jane_Candidate_Example_Company_Senior_Software_Engineer_AI_I.pdf"
        )
        application = {
            "Id": 9,
            "MatchScorePercent": 72,
            "MatchedSkills": [],
            "MissingSkills": [],
            "TailoredResumeId": 2,
        }
        ctx = AnonymousContext("session", None)

        with (
            patch("api.main.svc.get_application", return_value=application),
            patch("api.main.svc.get_tailored_pdf_path", return_value=path),
            patch("api.main.svc.get_existing_prep", return_value=None),
        ):
            state = _pair_state(1, 3, ctx)

        self.assertTrue(state["tailored_pdf_available"])
        self.assertEqual(state["tailored_pdf_filename"], path.name)
        self.assertLessEqual(len(state["tailored_pdf_display_name"]), 42)


if __name__ == "__main__":
    unittest.main()
