import unittest

from tools.transition_smoothness_gate import evaluate


CONTRACT = {
    "dialogue": {
        "jl_cut_ratio_min": 0.6,
        "same_frame_audio_visual_cut_ratio_max": 0.2,
        "j_cut_audio_lead_ms": {"min": 300, "max": 600},
        "l_cut_audio_tail_ms": {"min": 200, "max": 400},
        "speech_equal_power_crossfade_ms": {"min": 10, "max": 20},
    },
    "ambience_and_bgm": {
        "scene_prelap_ms": {"min": 500, "max": 1000},
        "equal_power_crossfade_ms": {"min": 40, "max": 80},
    },
    "picture": {
        "action_cut_offset_frames": {"min": 2, "max": 4},
        "reaction_hold_after_sentence_ms": {"min": 150, "max": 300},
    },
}


def transition(index, kind):
    return {
        "transition_id": f"T{index}",
        "cut_type": kind,
        "same_frame_audio_visual_cut": kind == "HARD",
        "audio_lead_ms": 400 if kind == "J" else 0,
        "audio_tail_ms": 300 if kind == "L" else 0,
        "speech_crossfade_ms": 15,
        "action_cut_offset_frames": 3,
        "reaction_hold_ms": 200,
    }


class TransitionSmoothnessGateTests(unittest.TestCase):
    def test_passes_professional_transition_mix(self):
        plan = {
            "dialogue_transitions": [
                transition(1, "J"),
                transition(2, "L"),
                transition(3, "J"),
                transition(4, "L"),
                transition(5, "HARD"),
            ],
            "scene_transitions": [
                {
                    "transition_id": "S1",
                    "ambience_prelap_ms": 750,
                    "ambience_crossfade_ms": 60,
                }
            ],
        }
        self.assertEqual(evaluate(plan, CONTRACT)["status"], "PASS")

    def test_rejects_same_frame_hard_cut_mix(self):
        plan = {
            "dialogue_transitions": [
                transition(1, "HARD"),
                transition(2, "HARD"),
                transition(3, "J"),
            ],
            "scene_transitions": [
                {
                    "transition_id": "S1",
                    "ambience_prelap_ms": 0,
                    "ambience_crossfade_ms": 0,
                }
            ],
        }
        report = evaluate(plan, CONTRACT)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("jl_cut_ratio_below_min", report["failures"])
        self.assertIn(
            "same_frame_audio_visual_cut_ratio_above_max",
            report["failures"],
        )

    def test_rejects_back_to_back_same_insert_source(self):
        plan = {
            "dialogue_transitions": [
                transition(1, "J"),
                transition(2, "L"),
                transition(3, "J"),
                transition(4, "L"),
                transition(5, "HARD"),
            ],
            "scene_transitions": [
                {
                    "transition_id": "S1",
                    "ambience_prelap_ms": 750,
                    "ambience_crossfade_ms": 60,
                }
            ],
            "same_insert_source_back_to_back_allowed": False,
            "picture_segments": [
                {"segment_id": "P1", "source_id": "INS-03"},
                {
                    "segment_id": "P2",
                    "source_id": "INS-03",
                    "requires_narrative_increment": True,
                    "narrative_increment": "",
                },
            ],
        }
        report = evaluate(plan, CONTRACT)
        self.assertIn("same_source_back_to_back:P1->P2", report["failures"])
        self.assertIn("required_narrative_increment_missing:P2", report["failures"])


if __name__ == "__main__":
    unittest.main()
