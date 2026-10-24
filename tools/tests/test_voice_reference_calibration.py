"""CAMERA_GRAMMAR_V1: the voice reference sample text is never a line of the script (lab Holmes E01:
Helen's reference line "Sir, I can stand this strain no longer..." leaked garbled into units 009-011).
Unstamped contracts keep the verbatim-line sample."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.voice_reference_sample import CALIBRATION_SENTENCES, calibration_sample

REPO = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO / "lines/nalu/runtime/tools/bootstrap_voice_references.py"
HELEN = "Sir, I can stand this strain no longer; I shall go mad if it continues."
HOLMES = "We shall soon set matters right, I have no doubt."


def authored(text, speed=1.2):
    return {"sample_text": text, "sample_text_rule": "AUTHORED_REFERENCE_ONLY_CALIBRATION", "speed": speed,
            "emotion": "fearful", "risk_flags": []}


class CalibrationSampleTests(unittest.TestCase):
    def test_script_line_sample_becomes_the_calibration_sentence(self):
        brief = {"sample_text": HELEN, "sample_text_rule": "LONGEST_SINGLE_IN_RANGE_LINE", "speed": 1.0,
                 "emotion": "fearful", "risk_flags": ["SAMPLE_TEXT_ABOVE_CEILING_MAY_EXCEED_10S"]}
        out = calibration_sample(brief, [HELEN, HOLMES], "en")
        self.assertEqual(out["sample_text"], CALIBRATION_SENTENCES["en"][0])
        self.assertEqual(out["sample_text_rule"], "CALIBRATION_SENTENCE_NOT_IN_SCRIPT")
        self.assertEqual(out["emotion"], "fearful")  # still read with the character's emotion
        self.assertTrue(3 <= out["estimated_duration_seconds"] <= 10)
        self.assertEqual(out["reference_sample_replaced"]["previous_sample_text"], HELEN)
        self.assertEqual(out["risk_flags"], [])
        self.assertEqual(brief["sample_text"], HELEN)  # input untouched

    def test_authored_sample_wins_unless_it_is_a_script_line(self):
        own = authored("A quiet voice, steady and low, reading this sentence for the timbre only.")
        self.assertIs(calibration_sample(own, [HELEN], "en"), own)
        out = calibration_sample(authored(HELEN.upper()), [HELEN], "en")
        self.assertEqual(out["sample_text"], CALIBRATION_SENTENCES["en"][0])
        self.assertEqual(out["reference_sample_replaced"]["reason"], "AUTHORED_REFERENCE_SAMPLE_TEXT_IS_A_SCRIPT_LINE")

    def test_falls_back_when_the_episode_speaks_the_calibration_sentence(self):
        out = calibration_sample({"sample_text": "x", "speed": 1.0}, [CALIBRATION_SENTENCES["zh"][0]], "zh")
        self.assertEqual(out["sample_text"], CALIBRATION_SENTENCES["zh"][1])

    def test_fast_read_is_slowed_into_the_3_to_10_s_window(self):
        for language, speed in (("zh", 1.5), ("en", 1.5), ("zh", 2.0)):
            out = calibration_sample({"sample_text": "x", "speed": speed}, ["x"], language)
            self.assertTrue(3 <= out["estimated_duration_seconds"] <= 10, out)
        self.assertLess(out["speed"], 2.0)


def run_bootstrap(root: Path, stamped: bool) -> dict:
    shots = [{"shot_id": f"E01-S01-0{i}", "scene_id": "E01-S01", "prompt_spec": {"dialogue": f"{who}: {line}"}}
             for i, (who, line) in enumerate((("Helen", HELEN), ("Holmes", HOLMES)), 1)]
    contract = {"episode": "E01", "dialogue_language": "en", "shots": shots,
                "character_entities": [{"character_id": "CHAR-HELEN", "canonical_name": "Helen"},
                                       {"character_id": "CHAR-HOLMES", "canonical_name": "Holmes"}]}
    if stamped:
        contract["camera_grammar_policy"] = "CAMERA_GRAMMAR_V1"
    else:
        contract["camera_grammar_policy"] = "LEGACY_FORCED_MOTION"
    (root / "c.json").write_text(json.dumps(contract), encoding="utf-8")
    (root / "r.json").write_text(json.dumps({"assets": {"voices": []}}), encoding="utf-8")
    subprocess.run([sys.executable, str(BOOTSTRAP), "--episode", "E01", "--language", "en",
                    "--generation-contract", str(root / "c.json"), "--asset-requirements", str(root / "r.json"),
                    "--registry-out", str(root / "reg.json"), "--policy-out", str(root / "pol.json"),
                    "--task-payloads-out", str(root / "tasks.json"), "--report", str(root / "rep.json"),
                    "--audio-output-root", str(root / "voices")],
                   check=True, capture_output=True, text=True, env={"QINGSHAN_ENGINE_ROOT": str(REPO), "PATH": ""})
    return {row["name"]: row["sample_text"] for row in json.loads((root / "pol.json").read_text())["roles"]}


class BootstrapCalibrationTests(unittest.TestCase):
    def test_stamped_contract_never_uses_a_script_line(self):
        with tempfile.TemporaryDirectory() as td:
            samples = run_bootstrap(Path(td), stamped=True)
        self.assertEqual(set(samples.values()), {CALIBRATION_SENTENCES["en"][0]})

    def test_unstamped_contract_keeps_the_verbatim_line(self):
        with tempfile.TemporaryDirectory() as td:
            samples = run_bootstrap(Path(td), stamped=False)
        self.assertEqual(samples, {"Helen": HELEN, "Holmes": HOLMES})


if __name__ == "__main__":
    unittest.main()
