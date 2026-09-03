import unittest

from tools.character_entity_contract import validate_character_entity_contract


def payload():
    return {
        "episode": "E54",
        "character_entities": [
            {"character_id": "CHAR-CHENJI", "canonical_name": "陈迹", "aliases": []},
            {"character_id": "CHAR-XUANYUAN", "canonical_name": "轩辕", "aliases": ["金甲人"]},
        ],
        "ordered_prompt_specs": [{
            "shot_id": "E54-S07-02",
            "cast": [
                {"character": "陈迹", "character_id": "CHAR-CHENJI"},
                {"character": "轩辕", "character_id": "CHAR-XUANYUAN"},
            ],
            "dialogue": "金甲人：你还赶来这里？",
            "action": {"subject_id": "CHAR-XUANYUAN", "primary_action": "金甲人抬眼质问陈迹"},
            "role_semantic_disambiguation": {
                "primary_actor": "金甲人", "primary_actor_id": "CHAR-XUANYUAN",
                "dialogue_speaker": "金甲人", "dialogue_speaker_id": "CHAR-XUANYUAN",
                "dialogue_listener": "陈迹", "dialogue_listener_id": "CHAR-CHENJI",
                "action_patient": "陈迹", "action_patient_id": "CHAR-CHENJI",
                "lip_owner_id": "CHAR-XUANYUAN",
                "entity_states": {"CHAR-XUANYUAN": "说话并注视陈迹", "CHAR-CHENJI": "闭口听话"},
                "entity_presence": {
                    "CHAR-XUANYUAN": "VISIBLE_AND_IDENTITY_LOCKED",
                    "CHAR-CHENJI": "VISIBLE_AND_IDENTITY_LOCKED",
                },
            },
        }],
    }


class CharacterEntityContractTests(unittest.TestCase):
    def test_alias_resolves_to_same_character(self):
        self.assertEqual(validate_character_entity_contract(payload())["status"], "PASS")

    def test_old_bug_wrong_actor_fails(self):
        value = payload()
        role = value["ordered_prompt_specs"][0]["role_semantic_disambiguation"]
        role["primary_actor"] = "陈迹"
        role["primary_actor_id"] = "CHAR-CHENJI"
        self.assertIn("ACTION_SUBJECT_ROLE_ACTOR_MISMATCH", ";".join(validate_character_entity_contract(value)["failures"]))
        role["dialogue_speaker_id"] = "CHAR-CHENJI"
        self.assertIn("DIALOGUE_ROLE_SPEAKER_MISMATCH", ";".join(validate_character_entity_contract(value)["failures"]))

    def test_alias_and_canonical_cannot_be_two_state_entities(self):
        value = payload()
        role = value["ordered_prompt_specs"][0]["role_semantic_disambiguation"]
        role["entity_states"]["金甲人"] = "另一状态"
        self.assertIn("ENTITY_STATE_KEY_NOT_CHARACTER_ID", ";".join(validate_character_entity_contract(value)["failures"]))

    def test_dialogue_speaker_cannot_be_marked_silent(self):
        value = payload()
        value["ordered_prompt_specs"][0]["role_semantic_disambiguation"]["entity_states"]["CHAR-XUANYUAN"] = "全程闭口"
        self.assertIn("DIALOGUE_SPEAKER_MARKED_SILENT", ";".join(validate_character_entity_contract(value)["failures"]))

    def test_environment_actor_is_not_forced_into_character_registry(self):
        value = payload()
        spec = value["ordered_prompt_specs"][0]
        spec["dialogue"] = ""
        spec["cast"] = []
        spec["action"] = {"primary_action": "风吹动帘幕"}
        spec["role_semantic_disambiguation"] = {
            "primary_actor": "风", "primary_actor_kind": "ENVIRONMENT",
            "dialogue_speaker": "", "dialogue_listener": "", "action_patient": "帘幕",
            "entity_states": {"风": "由弱转强", "帘幕": "向右摆动"},
            "entity_presence": {"风": "VISIBLE_AND_IDENTITY_LOCKED", "帘幕": "VISIBLE_AND_IDENTITY_LOCKED"},
        }
        self.assertEqual(validate_character_entity_contract(value)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
