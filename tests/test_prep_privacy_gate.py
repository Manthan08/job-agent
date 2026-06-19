import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from models.preparation import InterviewPrepPack
from webapp import services as svc


@contextmanager
def prep_flag(value: str | None):
    original = os.environ.get("PREP_PACK_ENABLED")
    if value is None:
        os.environ.pop("PREP_PACK_ENABLED", None)
    else:
        os.environ["PREP_PACK_ENABLED"] = value

    try:
        yield
    finally:
        if original is None:
            os.environ.pop("PREP_PACK_ENABLED", None)
        else:
            os.environ["PREP_PACK_ENABLED"] = original


class PrepPrivacyGateTests(unittest.TestCase):
    def test_prep_pack_is_disabled_by_default_before_any_db_or_llm_work(self):
        with prep_flag(None):
            self.assertFalse(svc.prep_pack_enabled())

            with (
                patch.object(svc, "get_application_id") as get_application_id,
                patch.object(svc, "generate_prep_for_job") as generate_prep,
            ):
                with self.assertRaisesRegex(ValueError, "disabled"):
                    svc.run_prep(1, 3)

            get_application_id.assert_not_called()
            generate_prep.assert_not_called()

    def test_saved_prep_is_hidden_when_prep_pack_is_disabled(self):
        with prep_flag("false"):
            with patch.object(
                svc,
                "_connect",
                side_effect=AssertionError("disabled prep must not read saved packs"),
            ):
                self.assertIsNone(svc.get_existing_prep(42))

    def test_run_prep_continues_to_work_when_explicitly_enabled(self):
        pack = InterviewPrepPack(
            overview="Use project stories for the interview.",
            questions=[],
            study_topics=[],
        )

        with prep_flag("true"):
            with (
                patch.object(svc, "get_application_id", return_value=42),
                patch.object(svc, "get_job_by_id", return_value={"Id": 9}),
                patch.object(svc, "job_to_text", return_value="job text"),
                patch.object(svc, "generate_prep_for_job", return_value=pack) as generate_prep,
                patch.object(svc, "save_prep_to_db") as save_prep,
            ):
                result_pack, application_id = svc.run_prep(7, 9)

        self.assertIs(result_pack, pack)
        self.assertEqual(application_id, 42)
        generate_prep.assert_called_once_with("job text")
        save_prep.assert_called_once_with(42, pack)


if __name__ == "__main__":
    unittest.main()
