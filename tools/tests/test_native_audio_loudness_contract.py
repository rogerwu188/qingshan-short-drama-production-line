import unittest

from tools.native_audio_loudness_contract import (
    evaluate_release_loudness,
    evaluate_unit_loudness,
    infer_loudness_role,
    plan_static_gain,
)


class NativeAudioLoudnessContractTests(unittest.TestCase):
    def test_infers_dialogue_action_ambience_and_music(self):
        self.assertEqual(infer_loudness_role({"dialogue_classification": "SPEAKING"}), "DIALOGUE")
        self.assertEqual(infer_loudness_role({"action_classification": "COMBAT"}), "ACTION")
        self.assertEqual(infer_loudness_role({"dialogue_classification": "NON_SPEAKING"}), "AMBIENCE")
        self.assertEqual(infer_loudness_role({}, track_id="Audio.BGM"), "MUSIC")

    def test_gain_is_bounded_by_maximum_and_true_peak(self):
        quiet = plan_static_gain(-37.7, -22.7, "AMBIENCE")
        self.assertEqual(quiet["gain_db"], 12.0)
        hot = plan_static_gain(-20.0, -0.5, "ACTION")
        self.assertEqual(hot["gain_db"], -1.0)
        self.assertLessEqual(float(hot["predicted_true_peak_dbtp"]), -1.5)

    def test_unit_gate_rejects_inaudible_and_large_boundary_jump(self):
        failures = evaluate_unit_loudness([
            {"unit_id": "U1", "role": "AMBIENCE", "integrated_loudness_lufs": -26.0},
            {"unit_id": "U2", "role": "DIALOGUE", "integrated_loudness_lufs": -15.0},
            {"unit_id": "U3", "role": "AMBIENCE", "integrated_loudness_lufs": -31.0},
        ])
        self.assertTrue(any(row.startswith("ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED") for row in failures))
        self.assertTrue(any(row.startswith("UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:U3") for row in failures))

    def test_unit_gate_honors_profile_adjacent_delta(self):
        rows = [
            {"unit_id": "U1", "role": "AMBIENCE", "integrated_loudness_lufs": -22.0},
            {"unit_id": "U2", "role": "DIALOGUE", "integrated_loudness_lufs": -15.0},
        ]
        self.assertEqual(evaluate_unit_loudness(rows, max_adjacent_delta_lu=8.0), [])
        self.assertTrue(any(
            row.startswith("ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED")
            for row in evaluate_unit_loudness(rows, max_adjacent_delta_lu=6.0)
        ))

    def test_release_gate_enforces_lufs_lra_and_peak(self):
        self.assertEqual(evaluate_release_loudness({
            "integrated_loudness_lufs": -16.0,
            "loudness_range_lu": 10.0,
            "true_peak_dbtp": -1.2,
        }), [])
        failures = evaluate_release_loudness({
            "integrated_loudness_lufs": -20.0,
            "loudness_range_lu": 15.0,
            "true_peak_dbtp": -0.2,
        })
        self.assertEqual(len(failures), 3)


if __name__ == "__main__":
    unittest.main()
