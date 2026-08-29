import unittest

from tools.performance_tempo_gate import evaluate_batch


def _windows():
    return [
        {"start_seconds": 0.0, "end_seconds": 1.0, "action": "exchange 1"},
        {"start_seconds": 1.1, "end_seconds": 2.1, "action": "exchange 2"},
        {"start_seconds": 2.2, "end_seconds": 3.2, "action": "exchange 3"},
    ]


class PerformanceTempoCombatContractTest(unittest.TestCase):
    def test_semantic_grouped_unit_allows_multiple_ordered_editorial_beats(self):
        task = {
            "task_key": "GROUPED-8S",
            "shot_type": "SEMANTIC_GROUPED_SCENE_PERFORMANCE",
            "semantic_video_unit": True,
            "action_unit": True,
            "duration_seconds": 8,
            "prompt": "ordered continuous action and dialogue beats",
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "grouped_editorial_beat_count": 4,
                "atomic_action_windows": [
                    {"start_seconds": 0.0, "end_seconds": 1.9, "action": "beat 1"},
                    {"start_seconds": 1.9, "end_seconds": 3.4, "action": "beat 2"},
                    {"start_seconds": 3.4, "end_seconds": 5.3, "action": "beat 3"},
                    {"start_seconds": 5.3, "end_seconds": 7.7, "action": "beat 4"},
                ],
            },
        }
        self.assertEqual(evaluate_batch([task])["status"], "PASS")

    def test_semantic_grouped_unit_rejects_a_stretched_editorial_beat(self):
        task = {
            "task_key": "GROUPED-STRETCHED",
            "shot_type": "SEMANTIC_GROUPED_SCENE_PERFORMANCE",
            "semantic_video_unit": True,
            "action_unit": True,
            "duration_seconds": 8,
            "prompt": "ordered continuous action",
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "grouped_editorial_beat_count": 2,
                "atomic_action_windows": [
                    {"start_seconds": 0.0, "end_seconds": 4.0, "action": "stretched beat"},
                    {"start_seconds": 4.0, "end_seconds": 8.0, "action": "stretched beat"},
                ],
            },
        }
        result = evaluate_batch([task])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GROUPED_EDITORIAL_BEAT_DURATION_INVALID", {row["code"] for row in result["failures"]})

    def test_dialogue_performance_is_not_misclassified_as_atomic_action(self):
        task = {
            "task_key": "DIALOGUE-8S",
            "shot_type": "DIALOGUE_PERFORMANCE",
            "action_unit": False,
            "duration_seconds": 8,
            "prompt": "Natural dialogue performance with breathing and micro-expression action.",
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "atomic_action_windows": [{"start_seconds": 0.0, "end_seconds": 1.0, "action": "begin speaking"}],
            },
        }
        self.assertEqual(evaluate_batch([task])["status"], "PASS")

    def test_structured_combat_accepts_registered_eight_second_generation_unit(self):
        task = {
        "task_key": "COMBAT-8S",
        "shot_type": "COMBAT",
        "action_unit": True,
        "duration_seconds": 8,
        "prompt": "fast combat exchange",
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X",
            "primary_exchange_complete_by_seconds": 1.5,
            "aftermath_in_same_edit_shot": False,
            "atomic_action_windows": _windows(),
        },
        }
        self.assertEqual(evaluate_batch([task])["status"], "PASS")


    def test_noncombat_atomic_action_still_rejects_duration_over_four_seconds(self):
        task = {
        "task_key": "NONCOMBAT-5S",
        "shot_type": "GENERAL",
        "action_unit": True,
        "duration_seconds": 5,
        "prompt": "a character opens the door",
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X",
            "primary_action_complete_by_seconds": 1.0,
            "result_hold_seconds": 0.5,
            "atomic_action_windows": [{"start_seconds": 0.0, "end_seconds": 1.0, "action": "open"}],
        },
        }
        result = evaluate_batch([task])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("ATOMIC_ACTION_DURATION_INVITES_SLOW_MOTION", {row["code"] for row in result["failures"]})


    def test_structured_combat_rejects_generation_unit_below_eight_seconds(self):
        task = {
        "task_key": "COMBAT-4S",
        "shot_type": "COMBAT",
        "action_unit": True,
        "duration_seconds": 4,
        "prompt": "fast combat exchange",
        "performance_tempo_contract": {
            "playback_speed": "REAL_TIME_1X",
            "primary_exchange_complete_by_seconds": 1.5,
            "aftermath_in_same_edit_shot": False,
            "atomic_action_windows": _windows(),
        },
        }
        result = evaluate_batch([task])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("COMBAT_GENERATION_DURATION_INVALID", {row["code"] for row in result["failures"]})


if __name__ == "__main__":
    unittest.main()
