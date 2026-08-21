import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/canonical_writer_dispatcher.py"


class CanonicalWriterDispatcherTests(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_start_finish_writes_exact_receipt_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            authority = base / "E41_NARRATIVE_CANONICAL_v5.md"
            receipt = base / "receipt.json"
            locks = base / "locks"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("rule\n", encoding="utf-8")
            authority.write_text("story\n", encoding="utf-8")
            started = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-TEST",
                "--agent-id", "qingshan-claude-writer-agent",
                "--provider", "anthropic-cowork",
                "--model-id", "claude-opus-4-8-20260821",
                "--session-or-task-id", "session-e41-v5-test",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", receipt,
                "--lock-dir", locks,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            running = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("RUNNING", running["status"])
            self.assertTrue(Path(running["write_lease"]).is_file())

            duplicate = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-SECOND",
                "--agent-id", "qingshan-claude-writer",
                "--provider", "storyclaw",
                "--model-id", "storyclaw/claude-opus-4-8",
                "--session-or-task-id", "session-second",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", base / "second.json",
                "--lock-dir", locks,
            )
            self.assertNotEqual(0, duplicate.returncode)

            finished = self.run_tool("finish", "--receipt", receipt, "--authority", authority)
            self.assertEqual(0, finished.returncode, finished.stderr)
            completed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual("COMPLETED", completed["status"])
            self.assertEqual(64, len(completed["authority_output"]["sha256"]))
            self.assertFalse(Path(completed["write_lease"]).exists())

    def test_generic_model_alias_is_rejected_before_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_bundle = base / "input.json"
            rule = base / "rule.md"
            input_bundle.write_text("{}\n", encoding="utf-8")
            rule.write_text("rule\n", encoding="utf-8")
            result = self.run_tool(
                "start",
                "--episode", "E41",
                "--version", "5",
                "--writer-run-id", "WRITER-E41-V5-TEST",
                "--agent-id", "qingshan-claude-writer-agent",
                "--provider", "anthropic-cowork",
                "--model-id", "Claude",
                "--session-or-task-id", "session-test",
                "--input-bundle", input_bundle,
                "--rule", rule,
                "--receipt", base / "receipt.json",
                "--lock-dir", base / "locks",
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("WRITER_MODEL_ID_NOT_EXACT", result.stderr)


if __name__ == "__main__":
    unittest.main()
