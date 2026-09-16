import json
import tempfile
import unittest
from pathlib import Path

from tools import voice_cast_gate as vcg


def cast(**overrides) -> dict:
    characters = {
        "CHAR-A": {"voice_id": "V1", "f0_band_hz": [150, 200], "rate_cps_baseline": 4.5, "timbre_brief": "mid male"},
        "CHAR-B": {"voice_id": "V2", "f0_band_hz": [90, 125], "rate_cps_baseline": 3.8, "timbre_brief": "low male"},
        "CHAR-C": {"voice_id": "V3", "f0_band_hz": [240, 300], "rate_cps_baseline": 4.8, "timbre_brief": "female"},
    }
    characters.update(overrides)
    return {"schema": vcg.CAST_SCHEMA, "characters": characters}


class BandTests(unittest.TestCase):
    def test_build_f0_band_is_plus_minus_fifteen_percent(self):
        self.assertEqual(vcg.build_f0_band(200.0), [170.0, 230.0])

    def test_build_f0_band_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            vcg.build_f0_band(0)

    def test_overlap_ratio_relative_to_narrower_band(self):
        self.assertEqual(vcg.band_overlap_ratio([100, 200], [150, 170]), 1.0)
        self.assertEqual(vcg.band_overlap_ratio([100, 140], [130, 200]), 0.25)
        self.assertEqual(vcg.band_overlap_ratio([100, 140], [140, 200]), 0.0)


class PrecheckTests(unittest.TestCase):
    def test_pass_when_bands_distinct_and_voices_unique(self):
        result = vcg.precheck(cast(), [["CHAR-A", "CHAR-B", "CHAR-C"]])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])

    def test_shared_voice_id_in_scene_fails(self):
        result = vcg.precheck(cast(**{"CHAR-B": {"voice_id": "V1", "f0_band_hz": [90, 125]}}), [["CHAR-A", "CHAR-B"]])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("VOICE_ID_SHARED_IN_SCENE:CHAR-A:CHAR-B", result["failures"])

    def test_shared_voice_id_in_different_scenes_is_allowed(self):
        result = vcg.precheck(cast(**{"CHAR-B": {"voice_id": "V1", "f0_band_hz": [90, 125]}}), [["CHAR-A"], ["CHAR-B"]])
        self.assertEqual(result["status"], "PASS")

    def test_band_overlap_over_half_requires_human_not_fail(self):
        result = vcg.precheck(cast(**{"CHAR-B": {"voice_id": "V2", "f0_band_hz": [160, 210]}}), [["CHAR-A", "CHAR-B"]])
        self.assertEqual(result["status"], "REQUIRES_HUMAN")
        self.assertEqual(result["failures"], [])
        self.assertIn("F0_BAND_OVERLAP_REQUIRES_HUMAN:CHAR-A:CHAR-B", result["requires_human"])

    def test_small_overlap_passes(self):
        result = vcg.precheck(cast(**{"CHAR-B": {"voice_id": "V2", "f0_band_hz": [120, 160]}}), [["CHAR-A", "CHAR-B"]])
        self.assertEqual(result["status"], "PASS")

    def test_unknown_character_is_unverified(self):
        result = vcg.precheck(cast(), [["CHAR-A", "CHAR-ZZ"]])
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIn("CHARACTER_NOT_IN_CAST:CHAR-ZZ:scene0", result["unverified"])

    def test_invalid_cast_fails_loudly(self):
        result = vcg.precheck({"schema": "wrong"}, [["CHAR-A"]])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["failures"][0].startswith("CAST_SCHEMA_MISMATCH"))


class PostcheckTests(unittest.TestCase):
    def test_in_band_lines_pass(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "f0_median_hz": 180.0, "scene": "S1"},
            {"start": 3.0, "end": 4.0, "speaker": "CHAR-B", "f0_median_hz": 100.0, "scene": "S1"},
        ]
        result = vcg.postcheck(cast(), segments)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["measurements"]["lines_attributed"], 2)

    def test_out_of_band_line_fails_with_speaker_and_start(self):
        segments = [{"start": 12.34, "end": 13.0, "speaker": "CHAR-B", "f0_median_hz": 350.0}]
        result = vcg.postcheck(cast(), segments)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("VOICE_OUT_OF_BAND:CHAR-B:12.3", result["failures"])

    def test_collision_when_two_speakers_share_register_in_scene(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "f0_median_hz": 190.0, "scene": "S1"},
            {"start": 3.0, "end": 4.0, "speaker": "CHAR-A", "f0_median_hz": 200.0, "scene": "S1"},
            {"start": 5.0, "end": 6.0, "speaker": "CHAR-B", "f0_median_hz": 100.0, "scene": "S1"},
            # CHAR-C is planned at 240-300 Hz but the model voiced it like CHAR-A
            {"start": 7.0, "end": 8.0, "speaker": "CHAR-C", "f0_median_hz": 205.0, "scene": "S1"},
        ]
        result = vcg.postcheck(cast(), segments)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("VOICE_COLLISION:CHAR-A:CHAR-C", result["failures"])
        self.assertIn("VOICE_OUT_OF_BAND:CHAR-C:7.0", result["failures"])
        self.assertEqual(len(result["measurements"]["collisions"]), 1)

    def test_no_collision_across_scenes(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "f0_median_hz": 190.0, "scene": "S1"},
            {"start": 7.0, "end": 8.0, "speaker": "CHAR-C", "f0_median_hz": 260.0, "scene": "S2"},
        ]
        self.assertEqual(vcg.postcheck(cast(), segments)["status"], "PASS")

    def test_missing_f0_or_unknown_speaker_is_unverified_not_pass(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "f0_median_hz": None},
            {"start": 3.0, "end": 4.0, "speaker": "CHAR-X", "f0_median_hz": 150.0},
        ]
        result = vcg.postcheck(cast(), segments)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertIn("F0_UNAVAILABLE:CHAR-A:1.0", result["unverified"])
        self.assertIn("SPEAKER_NOT_IN_CAST:CHAR-X:3.0", result["unverified"])

    def test_no_speaker_attribution_is_unverified(self):
        result = vcg.postcheck(cast(), [{"start": 0, "end": 1, "f0_median_hz": 100.0}])
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["unverified"], ["NO_SPEAKER_ATTRIBUTION"])


class EmotionDynamicsTests(unittest.TestCase):
    def test_plead_six_db_above_calm_passes(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "emotion": "calm", "rms_dbfs": -20.0},
            {"start": 3.0, "end": 4.0, "speaker": "CHAR-A", "emotion": "calm", "rms_dbfs": -19.0},
            {"start": 5.0, "end": 6.0, "speaker": "CHAR-A", "emotion": "plead", "rms_dbfs": -13.0},
        ]
        result = vcg.emotion_dynamics(segments)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["measurements"]["calm_baseline_dbfs"]["CHAR-A"], -19.5)

    def test_flat_plead_fails(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "emotion": "calm", "rms_dbfs": -16.8},
            {"start": 151.7, "end": 152.3, "speaker": "CHAR-A", "emotion": "plead", "rms_dbfs": -16.3},
        ]
        result = vcg.emotion_dynamics(segments)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"], ["FLAT_EMOTION:CHAR-A:151.7"])

    def test_fear_and_threat_are_checked_but_joy_and_mock_are_not(self):
        segments = [
            {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "emotion": "calm", "rms_dbfs": -20.0},
            {"start": 2.0, "end": 3.0, "speaker": "CHAR-A", "emotion": "fear", "rms_dbfs": -19.0},
            {"start": 3.0, "end": 4.0, "speaker": "CHAR-A", "emotion": "threat", "rms_dbfs": -19.0},
            {"start": 4.0, "end": 5.0, "speaker": "CHAR-A", "emotion": "joy", "rms_dbfs": -19.0},
            {"start": 5.0, "end": 6.0, "speaker": "CHAR-A", "emotion": "mock", "rms_dbfs": -19.0},
        ]
        result = vcg.emotion_dynamics(segments)
        self.assertEqual(result["failures"], ["FLAT_EMOTION:CHAR-A:2.0", "FLAT_EMOTION:CHAR-A:3.0"])

    def test_speaker_without_calm_baseline_is_unverified_never_pass(self):
        segments = [{"start": 9.0, "end": 10.0, "speaker": "CHAR-B", "emotion": "plead", "rms_dbfs": -10.0}]
        result = vcg.emotion_dynamics(segments)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["failures"], [])
        self.assertIn("NO_CALM_BASELINE:CHAR-B", result["unverified"])

    def test_no_annotation_is_unverified(self):
        result = vcg.emotion_dynamics([{"start": 0, "end": 1, "rms_dbfs": -10.0}])
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(result["unverified"], ["NO_EMOTION_ANNOTATION"])


class CliTests(unittest.TestCase):
    def test_cli_writes_report_schema_and_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="vcg_test_") as tmp:
            root = Path(tmp)
            (root / "cast.json").write_text(json.dumps(cast()), encoding="utf-8")
            (root / "scenes.json").write_text(json.dumps([["CHAR-A", "CHAR-B"]]), encoding="utf-8")
            (root / "segments.json").write_text(json.dumps({"segments": [
                {"start": 1.0, "end": 2.0, "speaker": "CHAR-A", "emotion": "calm", "f0_median_hz": 180.0, "rms_dbfs": -20.0},
                {"start": 3.0, "end": 4.0, "speaker": "CHAR-B", "emotion": "plead", "f0_median_hz": 300.0, "rms_dbfs": -20.0},
            ]}), encoding="utf-8")
            out = root / "gate.json"
            rc = vcg.main(["--cast", str(root / "cast.json"), "--copresence-json", str(root / "scenes.json"),
                           "--segments-json", str(root / "segments.json"), "--out", str(out)])
            self.assertEqual(rc, 1)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], vcg.OUTPUT_SCHEMA)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("VOICE_OUT_OF_BAND:CHAR-B:3.0", report["failures"])
            self.assertIn("NO_CALM_BASELINE:CHAR-B", report["unverified"])
            self.assertIn("postcheck", report["measurements"])


if __name__ == "__main__":
    unittest.main()
