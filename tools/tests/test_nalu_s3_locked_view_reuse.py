"""stage_s3 reuse: a LOCKED character's per-view plan rows are skipped, not re-rendered (2026-09-21)."""
from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lines/nalu/runtime/tools"))


class LockedViewReuse(unittest.TestCase):
    def test_view_rows_registered_for_locked_subject(self):
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            arts = []
            for role in ("FULL_BODY_STANDING", "FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST"):
                f = Path(tmp) / f"{role}.png"; f.write_bytes(role.encode())
                arts.append({"role": role, "path": str(f), "sha256": hashlib.sha256(role.encode()).hexdigest()})
            library = {"assets": {"characters": {
                "CHAR-A": {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": arts},
                "CHAR-B": {"status": "REQUIRED_UNCREATED", "qa": {"status": "FAIL"}, "artifacts": arts},
            }}}
            already = pipeline.locked_subjects(library)
        self.assertIn("CHAR-A", already)
        self.assertIn("CHAR-A__FRONT_NEUTRAL_HEADSHOT", already)
        self.assertIn("CHAR-A__THREE_QUARTER_BUST", already)
        self.assertEqual(already["CHAR-A__THREE_QUARTER_BUST"]["via"], "CHAR-A")
        self.assertNotIn("CHAR-B", already)
        self.assertNotIn("CHAR-B__FRONT_NEUTRAL_HEADSHOT", already)


if __name__ == "__main__":
    unittest.main()
