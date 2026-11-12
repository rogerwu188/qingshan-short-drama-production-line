"""The canonical (full-plan) start-frame contract of an own-start unit binds the same as-submitted image as the
wave contract, not the predecessor's new tail (fleet device 1284 E06 VU-006, 2026-11-12: full contract bound
the new VU-005 tail 627b…, wave bound the submitted 67f78…, so no receipt could satisfy both)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WithholdOwnStartTailTests(unittest.TestCase):

    def _dirs(self, tmp: str):
        out, kf, tails = Path(tmp, "pre"), Path(tmp, "kf"), Path(tmp, "tails")
        for d in (out / "reports", kf, tails):
            d.mkdir(parents=True)
        own = kf / "S04-05-keyframe-v1.png"
        own.write_bytes(b"submitted first image")
        (tails / "E06-VU-005.png").write_bytes(b"new tail after redo")
        (out / "reports" / "E06_S6_WAVE_STATE.json").write_text(json.dumps({"start_frame_as_submitted": {
            "E06-VU-006": {"predecessor_tail_submitted": False, "reference_sha256": [_sha(own)]}}}))
        return out, kf, tails, own

    def test_submitted_without_tail_records_the_as_submitted_image(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as tmp:
            out, kf, tails, own = self._dirs(tmp)
            unit = {"unit_id": "E06-VU-006"}
            bnp.withhold_own_start_tail(unit, "E06-VU-005", tails, out, "E06", kf, set())
            self.assertNotIn("previous_unit_final_frame", unit)
            row = unit["withheld_previous_unit_final_frame"]
            self.assertEqual(row["reason"], "SUBMITTED_WITHOUT_PREDECESSOR_TAIL")
            self.assertEqual(row["as_submitted_start_frame"]["path"], str(own))
            self.assertEqual(row["as_submitted_start_frame"]["sha256"], _sha(own))

    def test_tail_rejected_has_no_as_submitted_image(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as tmp:
            out, kf, tails, _own = self._dirs(tmp)
            unit = {"unit_id": "E06-VU-006"}
            bnp.withhold_own_start_tail(unit, "E06-VU-005", tails, out, "E06", kf, {"E06-VU-006"})
            row = unit["withheld_previous_unit_final_frame"]
            self.assertEqual(row["reason"], "TAIL_REJECTED")
            self.assertNotIn("as_submitted_start_frame", row)

    def test_missing_tail_leaves_unit_unchanged(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as tmp:
            out, kf, tails, _own = self._dirs(tmp)
            unit = {"unit_id": "E06-VU-006"}
            bnp.withhold_own_start_tail(unit, "E06-VU-004", tails, out, "E06", kf, set())
            self.assertEqual(unit, {"unit_id": "E06-VU-006"})

    def test_full_plan_anchor_outputs_withhold_the_tail(self):
        src = (TOOLS / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        body = src[src.index("def build_anchor_outputs("):src.index("anchor_plan = engine.anchor_build(")]
        self.assertIn("withhold_own_start_tail(", body)


if __name__ == "__main__":
    unittest.main()
