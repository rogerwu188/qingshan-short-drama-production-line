import unittest

from tools.build_bound_image_repair_feedback import repair_instructions


class BoundRepairFeedbackTests(unittest.TestCase):
    def test_instructions_use_exact_shot_action_and_scene(self):
        shot = {"action": "原动作。", "characters": ["chenji"]}
        scene = {"location": "密室", "time_of_day": "night", "weather": "dry"}
        result = repair_instructions(shot, scene, ["story_action_clarity", "scene_authority"], True)
        self.assertIn("原动作。", result[0])
        self.assertIn("地点=密室", result[1])

    def test_identity_instruction_cannot_invent_another_shot_character(self):
        shot = {"action": "枯手落笔。", "characters": ["unknown_scribe_hand"]}
        scene = {"location": "文书房", "time_of_day": "night", "weather": "dry"}
        result = repair_instructions(shot, scene, ["canonical_identity_continuity"], False)
        self.assertIn("unknown_scribe_hand", result[0])
        self.assertNotIn("皎兔", result[0])


if __name__ == "__main__":
    unittest.main()
