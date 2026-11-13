"""Tests for the ATS coverage improvements (no network; LLM calls are mocked)."""
import unittest
from pathlib import Path
from unittest.mock import patch

from models.keyword_coverage import KeywordCoverageItem, KeywordCoverageReport
from models.match import MatchResult
from models.tailored import SkillCategory, TailoredExperienceItem, TailoredResumeModel
from phase4_tailor.keyword_coverage import measure_resume_coverage
from webapp import services as svc


def _item(kw, bucket, importance="must_have"):
    return KeywordCoverageItem(
        keyword=kw, jd_phrase=kw, bucket=bucket, importance=importance,
        resume_evidence="x" if bucket != "missing" else "",
        tailoring_instruction="use it" if bucket != "missing" else "do not add",
    )


class MeasureCoverageTests(unittest.TestCase):
    def test_counts_only_keywords_present_in_text(self):
        report = KeywordCoverageReport(
            direct_matches=[_item("C#", "direct"), _item("Azure", "direct")],
            adjacent_matches=[_item("Docker", "adjacent")],
            missing_keywords=[_item("Kubernetes", "missing")],
        )
        text = "Skills: C#, Azure App Service, SQL"
        m = measure_resume_coverage(text, report)
        self.assertLess(m["score"], 100)
        self.assertIn("Docker", [i.keyword for i in m["uncovered"]])
        self.assertNotIn("Kubernetes", [i.keyword for i in m["uncovered"]])

    def test_full_coverage_when_all_coverable_present(self):
        report = KeywordCoverageReport(
            direct_matches=[_item("C#", "direct")],
            adjacent_matches=[_item("Docker", "adjacent")],
            missing_keywords=[],
        )
        text = "Built C# microservices deployed with Docker."
        self.assertEqual(measure_resume_coverage(text, report)["score"], 100)


class RunTailorLoopTests(unittest.TestCase):
    def _tailored(self, skills):
        return TailoredResumeModel(
            tailored_summary="Senior .NET engineer.",
            tailored_skills=[SkillCategory(category="Tech", skills=skills)],
            tailored_experience=[TailoredExperienceItem(
                company="Acme", role_title="Engineer", start_date="2019",
                end_date=None, bullets=["Shipped services."])],
            skill_gaps=[], bridge_notes=[],
        )

    def test_loop_retailors_until_target_then_reports_scores(self):
        report = KeywordCoverageReport(
            direct_matches=[_item("C#", "direct"), _item("Azure", "direct")],
            adjacent_matches=[_item("Docker", "adjacent")],
            missing_keywords=[],
        )
        outputs = [self._tailored(["C#", "Azure"]), self._tailored(["C#", "Azure", "Docker"])]
        calls = {"n": 0}
        def fake_tailor(*a, **k):
            out = outputs[min(calls["n"], len(outputs) - 1)]; calls["n"] += 1; return out

        resume = {"Id": 1, "Name": "M", "Email": "m@e.com", "Skills": "[]", "Experience": "[]"}
        job = {"Id": 3, "CompanyName": "Acme", "Position": "Senior .NET", "JobDescription": "C#, Azure, Docker"}
        application = {"Id": 9, "MatchScorePercent": 70}

        with (
            patch("webapp.services.get_resume_by_id", return_value=resume),
            patch("webapp.services.get_job_by_id", return_value=job),
            patch("webapp.services.get_application", return_value=application),
            patch("webapp.services.analyze_keyword_coverage", return_value=report),
            patch("webapp.services.tailor_resume_for_job", side_effect=fake_tailor),
            patch("webapp.services.score_resume_against_job",
                  return_value=MatchResult(match_score=86, reasoning="ok")),
            patch("webapp.services.save_tailored_resume"),
            patch("webapp.services.render_tailored_pdf", return_value=Path("data/tailored/x.pdf")),
            patch("webapp.services.save_tailored_resume_link"),
        ):
            result = svc.run_tailor(1, 3)

        self.assertEqual(result.iterations, 2)
        self.assertEqual(result.ats_coverage_score, 100)
        self.assertEqual(result.original_match_score, 70)
        self.assertEqual(result.tailored_match_score, 86)


if __name__ == "__main__":
    unittest.main()
