import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = {"api", "config", "db", "models", "phase5_coach", "webapp"}


class StreamlitRemovalTests(unittest.TestCase):
    def test_streamlit_dependency_and_entrypoint_are_removed(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertNotRegex(requirements, r"(?im)^\s*streamlit\b")
        self.assertFalse((ROOT / "webapp" / "app.py").exists())
        self.assertFalse((ROOT / "tests" / "test_webapp_app.py").exists())

    def test_runtime_code_has_no_streamlit_contract(self):
        violations = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if rel.parts[0] not in RUNTIME_DIRS:
                continue
            text = path.read_text(encoding="utf-8")
            if "streamlit" in text.lower():
                violations.append(str(rel))

        self.assertEqual(violations, [])

    def test_current_guidance_points_to_react_fastapi_only(self):
        handoff = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
        current_handoff = handoff.split("## ✅ Last completed", maxsplit=1)[0]
        current_guidance = "\n".join(
            (
                (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
                (ROOT / ".github" / "copilot-instructions.md").read_text(
                    encoding="utf-8"
                ),
                current_handoff,
            )
        )

        for stale_phrase in [
            "streamlit run",
            "webapp/app.py",
            "Streamlit fallback",
            "Phase 7 adds evals and Streamlit",
            "evals + a Streamlit UI",
        ]:
            self.assertNotIn(stale_phrase, current_guidance)


if __name__ == "__main__":
    unittest.main()
