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

    def test_unit_asr_alignment_takes_timing_from_asr_and_speaker_from_contract(self):
        out = mod.build_map(CONTRACT, GROUPING, TIMELINE, MANIFEST)
        unit_asr = {"EXX-VU-001": [{"start": 3.6, "end": 5.2, "text": "x"}],            # inside S01-02 (3.0-7.0)
                    "EXX-VU-002": [{"start": 0.4, "end": 1.1, "text": "y"}, {"start": 2.0, "end": 3.0, "text": "z"}]}
        out = mod.align_with_unit_asr(out, unit_asr, CONTRACT, GROUPING, TIMELINE)
        lines = {l["speaker"]: l for l in out["lines"]}
        self.assertEqual(lines["CHAR-A"]["time_source"], "ASR")
        self.assertAlmostEqual(lines["CHAR-A"]["time"], 3.6, places=3)
        self.assertAlmostEqual(lines["CHAR-A"]["time_contract_expected"], 4.0, places=3)
        self.assertAlmostEqual(lines["CHAR-B"]["time"], 7.1 + 0.4, places=3)
        wins = out["asr_windows"]
        self.assertEqual([w["speaker"] for w in wins], ["CHAR-A", "CHAR-B", "CHAR-B"])   # single-line unit: every window
        self.assertEqual(wins[0]["emotion"], "plead")
        self.assertEqual(wins[0]["text"], "x")   # lexicon input; the detector report itself drops text
        self.assertEqual(out["speaker_map_time_source"], "UNIT_ASR")

    def test_unit_without_asr_keeps_contract_time(self):
        out = mod.build_map(CONTRACT, GROUPING, TIMELINE, MANIFEST)
        out = mod.align_with_unit_asr(out, {}, CONTRACT, GROUPING, TIMELINE)
        self.assertTrue(all(l["time_source"] == "CONTRACT_EXPECTED" for l in out["lines"]))
        self.assertEqual(out["asr_windows"], [])


if __name__ == "__main__":
    unittest.main()
