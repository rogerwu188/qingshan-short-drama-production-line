import unittest

from tools.action_video_prompt_compiler import compile_action_video_prompt, validate_action_contract


class ActionVideoPromptCompilerTest(unittest.TestCase):
    def fixture(self):
        return {
            "canonical_characters": ["CHAR-A"],
            "canonical_props": ["PROP-X"],
            "space_chain_id": "EGSM-1->GSM-1->SUBSPACE-1",
            "blocking": {
                "characters": [{"character_id": "CHAR-A", "position": "right"}],
                "props": [{"prop_id": "PROP-X", "position": "left"}],
            },
            "action_end_blocking": {
                "characters": [{"character_id": "CHAR-A", "position": "center"}],
                "props": [{"prop_id": "PROP-X", "position": "center"}],
            },
            "trajectory_overlays": [{
                "entity_id": "PROP-X", "from": "left", "to": "center",
                "action": "slides", "visible_consequence": "stops at the hand",
            }],
            "performance_tempo_contract": {"atomic_action_windows": [
                {"start_seconds": 0.0, "end_seconds": 1.0, "action": "完成接触"}
            ]},
        }

    def test_compiles_from_structured_fact_source(self):
        prompt = compile_action_video_prompt(self.fixture())
        self.assertIn("PROP-X从left到center", prompt)
        self.assertIn("EGSM-1->GSM-1->SUBSPACE-1", prompt)

    def test_rejects_canonical_entity_missing_from_state(self):
        task = self.fixture()
        task["blocking"]["props"] = []
        task["action_end_blocking"]["props"] = []
        self.assertTrue(any("CANONICAL_ENTITY_ABSENT" in row for row in validate_action_contract(task)))

    def test_rejects_trajectory_without_visible_consequence(self):
        task = self.fixture()
        del task["trajectory_overlays"][0]["visible_consequence"]
        self.assertIn("TRAJECTORY_FIELD_MISSING:0:visible_consequence", validate_action_contract(task))


if __name__ == "__main__":
    unittest.main()
