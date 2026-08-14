from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOL = Path(__file__).resolve().parents[1] / "writer_checkpoint_guard.py"


class WriterCheckpointGuardTests(unittest.TestCase):
    def test_secondary_checkpoint_cannot_override_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            corpus = project / "source/corpus"
            raw_dir = corpus / "raw"
            raw_dir.mkdir(parents=True)
            raw = raw_dir / "chapter-469.html"
            raw.write_text("canonical chapter", encoding="utf-8")
            expected = hashlib.sha256(raw.read_bytes()).hexdigest()
            (corpus / "checkpoint.tsv").write_text(
                f"469\tchapter-469.html\t{expected}\n",
                encoding="utf-8",
            )
            (corpus / "checkpoint_443_763.tsv").write_text(
                f"469\tchapter-469.html\t{'0' * 64}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    "--project-root",
                    str(project),
                    "--start",
                    "469",
                    "--end",
                    "469",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["verified_count"], 1)
            self.assertEqual(len(receipt["secondary_checkpoints_ignored"]), 1)
            self.assertEqual(
                receipt["merge_policy"],
                "EXACT_CANONICAL_ONLY_NEVER_GLOB_MERGE",
            )


if __name__ == "__main__":
    unittest.main()
