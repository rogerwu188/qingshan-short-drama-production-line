import unittest

from tools.dialogue_cut_safety import (
    adapt_outgoing_handles_for_provider_limit,
    allocate_dialogue_safe_integer_durations,
    compile_dialogue_windows,
    evaluate_cut,
)


class DialogueCutSafetyTest(unittest.TestCase):
    def test_floating_runtime_can_expand_and_tail_handle_can_reduce_to_contract_floor(self):
        unit = {
            "unit_id": "VU-LONG", "duration_seconds": 8.7,
            "ordered_prompt_specs": [{
                "dialogue": "甲：这是一句很长很长并且绝对不能在结尾被剪断的完整对白。",
                "action": {"t0_seconds": 0, "t1_seconds": 8.7},
            }],
            "outgoing_transition_contract": {
                "boundary_id": "B1", "outgoing_handle_seconds": 1.0,
            },
        }
        rows = adapt_outgoing_handles_for_provider_limit(
            [unit], maximum_duration=15, minimum_tail_handle=0.6
        )
        result = allocate_dialogue_safe_integer_durations(rows)
        self.assertGreaterEqual(result["VU-LONG"], 9)
        self.assertGreaterEqual(rows[0]["outgoing_transition_contract"]["outgoing_handle_seconds"], 0.6)

    def test_allocator_reserves_speech_and_bridge_handle(self):
        units = [
            {
                "unit_id": "VU001", "duration_seconds": 5.1,
                "ordered_prompt_specs": [{
                    "dialogue": "甲：这是一句需要完整说完的话。",
                    "action": {"t0_seconds": 0, "t1_seconds": 5.1},
                }],
                "outgoing_transition_contract": {"outgoing_handle_seconds": 0.8},
            },
            {
                "unit_id": "VU002", "duration_seconds": 4.9,
                "ordered_prompt_specs": [{
                    "dialogue": "", "action": {"t0_seconds": 0, "t1_seconds": 4.9},
                }],
            },
        ]
        result = allocate_dialogue_safe_integer_durations(units, total_seconds=12)
        self.assertEqual(sum(result.values()), 12)
        probe = dict(units[0], duration_seconds=result["VU001"])
        self.assertTrue(compile_dialogue_windows(probe))

    def test_rejects_e44_style_active_audio_tail_trim(self):
        report = evaluate_cut(
            planned_cut_seconds=6.6,
            actual_duration_seconds=7.058866,
            dialogue_end_seconds=7.0,
            trimmed_tail_max_volume_db=-10.1,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CUT_BEFORE_DIALOGUE_END_SAFETY_PAD", report["failures"])
        self.assertIn("TRIMMED_TAIL_CONTAINS_ACTIVE_AUDIO", report["failures"])

    def test_dialogue_is_scheduled_before_transition_handle(self):
        unit = {
            "unit_id": "U1", "duration_seconds": 6,
            "ordered_prompt_specs": [{
                "dialogue": "甲：慢走。", "action": {"t0_seconds": 0, "t1_seconds": 6},
            }],
            "outgoing_transition_contract": {"outgoing_handle_seconds": 1.0},
        }
        rows = compile_dialogue_windows(unit)
        self.assertLess(rows[0]["end_seconds"] + rows[0]["safety_pad_seconds"], 5.01)


if __name__ == "__main__":
    unittest.main()
