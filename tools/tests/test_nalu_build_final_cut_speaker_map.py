"""build_final_cut_speaker_map: contract attribution of dialogue lines on the release timeline."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_final_cut_speaker_map",
                                              ROOT / "lines/nalu/runtime/tools/build_final_cut_speaker_map.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules["build_final_cut_speaker_map"] = mod
SPEC.loader.exec_module(mod)

CONTRACT = {"episode": "EXX", "shots": [
    {"shot_id": "EXX-S01-01", "scene_id": "EXX-S01", "target_seconds": 3.0},
    {"shot_id": "EXX-S01-02", "scene_id": "EXX-S01", "target_seconds": 4.0},
    {"shot_id": "EXX-S02-01", "scene_id": "EXX-S02", "target_seconds": 5.0}],
    "audio_contract": {"dialogue_units": [
        {"shot_id": "EXX-S01-02", "speaker_id": "CHAR-A", "emotion": "plead"},
        {"shot_id": "EXX-S02-01", "speaker_id": "CHAR-B"}]}}
GROUPING = {"units": [{"unit_id": "EXX-VU-001", "editorial_shot_ids": ["EXX-S01-01", "EXX-S01-02"]},
                      {"unit_id": "EXX-VU-002", "editorial_shot_ids": ["EXX-S02-01"]}]}
TIMELINE = {"segments": [{"unit_id": "EXX-VU-001", "output_start": 0.0}, {"unit_id": "EXX-VU-002", "output_start": 7.1}]}
MANIFEST = {"structure": [{"beat_id": "B1", "type": "action", "shot_ids": ["EXX-S01-01", "EXX-S01-02"]}]}


class SpeakerMap(unittest.TestCase):
    def test_lines_get_timeline_times_and_emotion(self):
        out = mod.build_map(CONTRACT, GROUPING, TIMELINE, MANIFEST)
        lines = {l["speaker"]: l for l in out["lines"]}
        self.assertAlmostEqual(lines["CHAR-A"]["time"], 3.0 + 1.0, places=3)     # unit start + earlier shot + lead
        self.assertAlmostEqual(lines["CHAR-B"]["time"], 7.1 + 1.0, places=3)
        self.assertEqual(lines["CHAR-A"]["emotion"], "plead")
        self.assertEqual(out["undeclared_emotion"], ["EXX-S02-01"])
        self.assertEqual(out["action_windows"], [[0.0, 7.0]])


if __name__ == "__main__":
    unittest.main()
