from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "durable_exec_probe.py"


class DurableExecProbeTests(unittest.TestCase):
    def test_explicit_project_path_wins_and_quiet_probe_is_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            facts = project / "source/facts/chapter_facts.jsonl"
            facts.parent.mkdir(parents=True)
            facts.write_text(
                '{"n": 1}\n{"n": 2}\n',
                encoding="utf-8",
            )
            wrong_shared = root / "wrong-shared"
            receipt_dir = root / "receipts"
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "--shared-root",
                    str(wrong_shared),
                    "--project-root",
                    str(project),
                    "--nonce",
                    "delayed-echo",
                    "--receipt-dir",
                    str(receipt_dir),
                    "--quiet-stdout",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            receipt = json.loads(
                (receipt_dir / "delayed-echo.json").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["status"], "HEALTHY")
            self.assertEqual(receipt["facts"], 2)
            self.assertEqual(receipt["last_n"], 2)
            self.assertEqual(receipt["project_root"], str(project.resolve()))


if __name__ == "__main__":
    unittest.main()
