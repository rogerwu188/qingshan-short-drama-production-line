"""unit_recut.py pure functions (Roger 2026-10-30 E12 item 3: free editorial re-cuts of generated units)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import unit_recut as ur  # noqa: E402


def seg(vu, vi, vo, au=None, ai=None, ao=None, label=""):
    return {"video": [vu, vi, vo], "audio": [au or vu, vi if ai is None else ai, vo if ao is None else ao], "label": label}


class SegmentValidationTests(unittest.TestCase):
    def test_equal_length_picture_and_sound_is_valid(self):
        self.assertEqual(ur.validate_segments("U", [seg("U", 0.0, 1.4), seg("V", 1.0, 1.52, "U", 4.65, 5.17)]), [])

    def test_length_mismatch_and_bad_order_are_reported(self):
        problems = ur.validate_segments("U", [seg("U", 0.0, 1.0, "U", 0.0, 1.5), seg("U", 2.0, 1.0)])
        self.assertEqual(len(problems), 2)
        self.assertIn("differ in length", problems[0])
        self.assertIn("in < out", problems[1])

    def test_empty_plan_is_invalid(self):
        self.assertEqual(ur.validate_segments("U", []), ["U: no segments"])


class InternalCutTests(unittest.TestCase):
    def test_cut_positions_are_where_the_picture_source_jumps(self):
        segs = [seg("U", 0.0, 1.4), seg("U", 1.4, 2.0), seg("V", 1.0, 1.5), seg("U", 3.0, 4.0)]
        # U 0–1.4 then U 1.4–2.0 is continuous (no cut); V at 2.0; back to U (non-contiguous) at 2.5
        self.assertEqual(ur.internal_cuts(segs), [2.0, 2.5])

    def test_digest_is_order_sensitive(self):
        a = [seg("U", 0.0, 1.0), seg("V", 0.0, 1.0)]
        b = [seg("V", 0.0, 1.0), seg("U", 0.0, 1.0)]
        self.assertNotEqual(ur.plan_digest(a), ur.plan_digest(b))
        self.assertEqual(ur.plan_digest(a), ur.plan_digest(json.loads(json.dumps(a))))


class AppliedSourcesTests(unittest.TestCase):
    def test_only_applied_rows_with_matching_output_sha_are_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "A.mp4"
            good.write_bytes(b"derived-a")
            sha = hashlib.sha256(b"derived-a").hexdigest()
            report = {"units": {
                "A": {"status": "APPLIED", "output": str(good), "output_sha256": sha},
                "B": {"status": "APPLIED", "output": str(Path(tmp) / "B.mp4"), "output_sha256": "00"},
                "C": {"status": "INVALID", "output": str(good), "output_sha256": sha},
                "D": {"status": "APPLIED", "output": str(good), "output_sha256": "ff"},
            }}
            self.assertEqual(sorted(ur.applied_sources(report)), ["A"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_validates_and_records_without_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "E99-VU-001.mp4").write_bytes(b"clip-1")
            (src / "E99-VU-002.mp4").write_bytes(b"clip-2")
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"schema": ur.PLAN_SCHEMA, "episode": "E99", "units": {
                "E99-VU-001": {"reason": "drop babble", "segments": [seg("E99-VU-001", 0.0, 1.0),
                                                                     seg("E99-VU-002", 0.5, 1.0, "E99-VU-001", 2.0, 2.5)]},
                "E99-VU-003": {"segments": [seg("E99-VU-003", 0.0, 1.0)]},
            }}), encoding="utf-8")
            report = ur.run(plan, src, Path(tmp) / "out", Path(tmp) / "report.json", dry_run=True)
            self.assertEqual(report["status"], "FAIL")       # VU-003 source missing is a problem
            row = report["units"]["E99-VU-001"]
            self.assertEqual(row["status"], "DRY_RUN")
            self.assertEqual(row["duration"], 1.5)
            self.assertEqual(row["internal_cuts_s"], [1.0])
            self.assertEqual(row["frames_borrowed_from"], ["E99-VU-002"])
            self.assertEqual(set(row["sources_sha256"]), {"E99-VU-001", "E99-VU-002"})
            self.assertEqual(report["units"]["E99-VU-003"]["status"], "SOURCE_MISSING")
            self.assertFalse((Path(tmp) / "out").exists())

    def test_wrong_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"schema": "other", "units": {}}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                ur.run(plan, Path(tmp), Path(tmp) / "out", Path(tmp) / "r.json", dry_run=True)


if __name__ == "__main__":
    unittest.main()
