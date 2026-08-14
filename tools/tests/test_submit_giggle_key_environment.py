import os
import stat
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

from tools import submit_giggle_task_manifest as submitter

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from tools import poll_giggle_submit_report as poller


class GiggleKeyEnvironmentTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("GIGGLE_API_KEY", None)

    def test_prefers_inherited_environment(self) -> None:
        os.environ["GIGGLE_API_KEY"] = "inherited-test-value"
        with patch.object(submitter, "PROTECTED_GIGGLE_ENV", Path("/missing")):
            self.assertEqual(submitter.ensure_giggle_api_key(), "INHERITED_ENV")

    def test_loads_protected_local_file_without_exposing_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "giggle_api_key.env"
            env_file.write_text("GIGGLE_API_KEY=protected-test-value\n", encoding="utf-8")
            env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            with patch.object(submitter, "PROTECTED_GIGGLE_ENV", env_file):
                self.assertEqual(submitter.ensure_giggle_api_key(), "PROTECTED_LOCAL_FILE")
            self.assertEqual(os.environ["GIGGLE_API_KEY"], "protected-test-value")

    def test_rejects_group_or_world_readable_key_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "giggle_api_key.env"
            env_file.write_text("GIGGLE_API_KEY=unsafe-test-value\n", encoding="utf-8")
            env_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
            with patch.object(submitter, "PROTECTED_GIGGLE_ENV", env_file):
                self.assertEqual(submitter.ensure_giggle_api_key(), "UNSAFE_FILE_PERMISSIONS")
            self.assertNotIn("GIGGLE_API_KEY", os.environ)

    def test_poller_uses_shared_protected_key_loader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submit_report = root / "submit.json"
            status_report = root / "status.json"
            submit_report.write_text('{"results": []}\n', encoding="utf-8")
            with patch.object(
                poller,
                "ensure_giggle_api_key",
                side_effect=lambda: os.environ.setdefault(
                    "GIGGLE_API_KEY", "poller-test-value"
                ) and "PROTECTED_LOCAL_FILE",
            ):
                result = poller.poll(
                    submit_report,
                    root / "downloads",
                    status_report,
                    False,
                )
            self.assertEqual(result["giggle_key_environment"], "PROTECTED_LOCAL_FILE")
            self.assertTrue(status_report.is_file())


if __name__ == "__main__":
    unittest.main()
