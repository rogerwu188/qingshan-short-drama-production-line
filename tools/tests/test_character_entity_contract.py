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


def shot_payload(shots):
    """A contract shape that carries entry_state on the shot, the way the writer emits it."""
    value = payload()
    del value["ordered_prompt_specs"]
    value["non_character_entities"] = [{"entity_id": "PROP-PURPLE-EYED-CROW", "name": "紫眼乌鸦"}]
    value["character_entities"].append({"character_id": "CHAR-CROW", "canonical_name": "乌鸦", "aliases": []})
    value["shots"] = shots
    return value


def two_shot_contract(prev_entry, prev_exit, entry, cast, *, subject="CHAR-CHENJI",
                      actor="CHAR-CHENJI", actor_name="陈迹"):
    def shot(shot_id, entry, exit_text, cast_ids, subject, actor, actor_name):
        return {
            "shot_id": shot_id,
            "entry_state": entry,
            "completion_state": exit_text,
            "prompt_spec": {
                "cast": [{"character": c, "character_id": c} for c in cast_ids],
                "dialogue": "",
                "action": {"subject_id": subject, "primary_action": entry},
                "role_semantic_disambiguation": {
                    "primary_actor": actor_name, "primary_actor_id": actor,
                    "dialogue_speaker": "", "dialogue_speaker_id": "",
                    "dialogue_listener": "", "dialogue_listener_id": "",
                    "action_patient": "", "action_patient_id": "",
                    "entity_states": {},
                    "entity_presence": {c: "VISIBLE_AND_IDENTITY_LOCKED" for c in cast_ids},
                },
            },
        }
    return [
        shot("E54-S01-01", prev_entry, prev_exit, ["CHAR-XUANYUAN"], "CHAR-XUANYUAN", "CHAR-XUANYUAN", "轩辕"),
        shot("E54-S01-02", entry, "", cast, subject, actor, actor_name),
    ]


class EntryStateNamesAbsentCharacterTests(unittest.TestCase):
    """K084 — nalu E11 S03-01 / S08-01 (2026-10-07): both shipped a paid keyframe from a prompt
    whose entry line named somebody the shot's cast does not contain.  The manifest renderer binds
    the entry sentence to the visible cast by id, so the name had nowhere to bind and the prompt
    went out saying one person acts and nobody is on screen.  S08-01 came back with the wrong man;
    S03-01 came back as the shot's completion state."""

    def test_entry_naming_an_absent_character_fails(self):
        """E11 S08-01: entry '刘老头站着，木杖重重顿在地上' with cast=秦铭."""
        value = shot_payload(two_shot_contract(
            "轩辕跨出门槛", "轩辕站在门口", "轩辕站着，木杖重重顿在地上", ["CHAR-CHENJI"]))
        failures = validate_character_entity_contract(value)["failures"]
        self.assertIn("E54-S01-02_ENTRY_STATE_NAMES_ABSENT_CHARACTER:CHAR-XUANYUAN", failures)

    def test_entry_naming_only_cast_members_passes(self):
        value = shot_payload(two_shot_contract(
            "轩辕跨出门槛", "轩辕站在门口", "陈迹坐在长凳上，轩辕站在他身侧",
            ["CHAR-CHENJI", "CHAR-XUANYUAN"]))
        self.assertEqual(validate_character_entity_contract(value)["failures"], [])

    def test_a_gaze_target_in_the_cast_is_not_a_defect(self):
        """'陈迹坐着盯着轩辕' with 轩辕 in the cast but not first-frame visible is a relationship
        target, not a leak — E10's approved shots read this way."""
        value = shot_payload(two_shot_contract(
            "轩辕跨出门槛", "轩辕站在门口", "陈迹坐着盯着轩辕", ["CHAR-CHENJI"]))
        role = value["shots"][1]["prompt_spec"]["role_semantic_disambiguation"]
        role["action_patient"] = "轩辕"
        role["action_patient_id"] = "CHAR-XUANYUAN"
        self.assertEqual(validate_character_entity_contract(value)["failures"], [])

    def test_primary_actor_outside_the_visible_cast_fails(self):
        """E11 S03-01 declared 邻居甲 as the actor with an empty cast."""
        value = shot_payload(two_shot_contract(
            "轩辕跨出门槛", "轩辕站在门口", "轩辕转过身朝向门口", [],
            subject="CHAR-XUANYUAN", actor="CHAR-XUANYUAN", actor_name="轩辕"))
        failures = validate_character_entity_contract(value)["failures"]
        self.assertIn("E54-S01-02_PRIMARY_ACTOR_NOT_IN_VISIBLE_CAST:CHAR-XUANYUAN", failures)

    def test_a_declared_prop_subject_is_exempt(self):
        """A creature shot whose head leads with a declared non-character name is a legitimate
        prop/pet insert (nalu E05 乌鸦), not an entry-state leak."""
        value = shot_payload(two_shot_contract(
            "轩辕跨出门槛", "轩辕站在门口", "乌鸦收翅静立在荆棘上", []))
        spec = value["shots"][1]["prompt_spec"]
        spec["props"] = [{"prop_id": "PROP-PURPLE-EYED-CROW", "prop": "紫眼乌鸦"}]
        spec["role_semantic_disambiguation"].update({
            "primary_actor": "紫眼乌鸦", "primary_actor_kind": "CREATURE", "primary_actor_id": "",
            "entity_presence": {},
        })
        self.assertEqual(validate_character_entity_contract(value)["failures"], [])


if __name__ == "__main__":
    unittest.main()
