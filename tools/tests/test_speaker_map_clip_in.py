"""Unit-ASR windows are in source-clip seconds; the S7 performance cut's in-point must be subtracted (lab 化神 E02)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(ROOT / "tools"))

import build_final_cut_speaker_map as m  # noqa: E402


class ClipInTests(unittest.TestCase):
    def _result(self):
        return {"lines": [{"unit_id": "U2", "shot_id": "S2", "speaker": "CHAR-B", "time": 10.0, "end": 12.0}]}

    def test_window_is_shifted_by_clip_in_and_kept_inside_the_unit(self):
        contract = {"shots": [{"shot_id": "S2", "target_seconds": 2.0}]}
        grouping = {"units": [{"unit_id": "U2", "editorial_shot_ids": ["S2"]}]}
        timeline = {"segments": [{"unit_id": "U2", "output_start": 18.035, "output_end": 19.983},
                                 {"unit_id": "U3", "output_start": 19.983, "output_end": 24.0}]}
        unit_asr = {"U2": [{"start": 0.3, "end": 0.9, "text": "cut"}, {"start": 2.51, "end": 4.15, "text": "line"}]}
        res = m.align_with_unit_asr(self._result(), unit_asr, contract, grouping, timeline, clip_in={"U2": 2.51})
        wins = [(w["start"], w["end"]) for w in res["asr_windows"]]
        self.assertEqual(wins, [(18.035, 19.675)])  # removed head speech dropped; window not in U3


if __name__ == "__main__":
    unittest.main()
