import unittest

from tools.storyboard_sheet_gate import requires_storyboard_sheet_gate, validate_plan


def valid_plan():
    episode_rows = [{
        "shot_no": index,
        "beat_id": f"B{index:02d}",
        "timecode": f"{index * 10:03d}s",
        "visual": f"visual-{index}",
        "camera": f"camera-{index}",
        "dialogue_sfx": f"sfx-{index}",
        "technique": f"technique-{index}",
        "composition_signature": f"signature-{index}",
    } for index in range(1, 7)]
    sizes = ["wide", "close-up", "medium", "macro", "overhead wide", "full wide"]
    phases = ["SETUP", "SETUP", "IMPACT", "IMPACT", "IMPACT", "TABLEAU"]
    fight_rows = [{
        "shot_no": index,
        "phase": phases[index - 1],
        "shot_size": sizes[index - 1],
        "camera": f"fight-camera-{index}",
        "action": f"action-{index}",
        "sfx": f"sfx-{index}",
        "power_visualization": f"power-{index}",
        "composition_signature": f"fight-signature-{index}",
    } for index in range(1, 7)]
    return {
        "episode": "E26",
        "episode_rows": episode_rows,
        "fight_sequence": {"mode": "B_WUXIA_XUANHUAN", "shots": fight_rows},
    }


class StoryboardSheetGateTests(unittest.TestCase):
    def test_e26_and_later_require_gate(self):
        self.assertFalse(requires_storyboard_sheet_gate("E25"))
        self.assertTrue(requires_storyboard_sheet_gate("E26"))
        self.assertTrue(requires_storyboard_sheet_gate("E99"))

    def test_valid_plan_passes(self):
        self.assertEqual("PASS", validate_plan(valid_plan())["status"])

    def test_duplicate_composition_and_missing_wide_fail(self):
        plan = valid_plan()
        for row in plan["episode_rows"]:
            row["composition_signature"] = "same"
        for row in plan["fight_sequence"]["shots"]:
            row["shot_size"] = "medium"
        result = validate_plan(plan)
        self.assertEqual("FAIL", result["status"])
        checks = {row["check"] for row in result["failures"]}
        self.assertIn("episode_sheet_compositions_unique", checks)
        self.assertIn("fight_requires_wide_or_full", checks)


if __name__ == "__main__":
    unittest.main()
