"""A hard-continuation unit's start-frame contract binds the extracted real final frame (…1101 E04 S6)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "lines" / "nalu" / "runtime" / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_nalu_preproduction as bnp  # noqa: E402

SPEC = {"cast": [], "props": [], "space": {"location": "LOC-1", "subspace": "edge"}, "action": {"start_state": "x"}, "visual_design": {"still_prompt_contract": "x"},
        "camera": {}}


class TailStartFrameContractTest(unittest.TestCase):
    def test_full_plan_unit_binds_previous_real_final_frame(self):
        with tempfile.TemporaryDirectory() as d:
            tails = Path(d) / "real_final_frames"
            tails.mkdir()
            (tails / "E04-VU-011.png").write_bytes(b"\x89PNG tail")
            editorial = {"shots": [{"shot_id": "E04-S01-01", "prompt_spec": SPEC},
                                   {"shot_id": "E04-S03-04", "prompt_spec": SPEC}]}
            anchor = {"units": [{"unit_id": "E04-VU-012", "editorial_shot_ids": ["E04-S03-04"],
                                 "reference_image_task_keys": ["E04-VU-011:REAL_FINAL_FRAME"],
                                 "reference_image_paths": [""]}]}
            row = bnp.build_start_frame_contracts(anchor, editorial, Path(d), None, tails)[0]
            self.assertEqual(row["reference_path"], str(tails / "E04-VU-011.png"))
            self.assertTrue(row["reference_sha256"])
            without = bnp.build_start_frame_contracts(anchor, editorial, Path(d), None, None)[0]
            self.assertIsNone(without["reference_path"])


if __name__ == "__main__":
    unittest.main()
