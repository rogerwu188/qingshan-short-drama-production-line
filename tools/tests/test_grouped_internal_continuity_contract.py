import unittest

from tools.grouped_internal_continuity_contract import (
    find_same_slot_character_replacements,
    validate_internal_transition_sequence,
)
from tools.tests.test_compile_grouped_seedance_manifest import internal_contract


def spec(character, *, subspace="SUB-A", prop=None, dialogue=""):
    result = {
        "space": {"global": "GLOBAL-A", "location": "LOC-A", "subspace": subspace},
        "cast": [{"character": character}],
        "props": [{"prop": prop}] if prop else [],
        "action": {
            "start_state": f"{character}保持起始姿态",
            "primary_action": f"{character}完成当前动作",
            "completion_state": f"{character}停在结果态",
        },
        "dialogue": dialogue,
        "sound_design": {"ambience": "同一街声", "foley": "衣料声", "action_sound": "当前接触声"},
    }
    return result


class GroupedInternalContinuityContractTest(unittest.TestCase):
    def test_multibeat_unit_fails_without_authored_internal_contract(self):
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [spec("世子"), spec("陈迹")],
        }
        with self.assertRaisesRegex(ValueError, "requires 1 authored internal transition contracts"):
            validate_internal_transition_sequence(unit)

    def test_cast_scene_prop_sound_and_dialogue_are_bound(self):
        previous = spec("世子", prop="银子", dialogue="世子：十两。")
        current = spec("陈迹", prop="药方", dialogue="陈迹：成交。")
        contract = internal_contract("VU-1", "S1", "S2", previous, current, mode="MOTIVATED_CUT")
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [previous, current],
            "internal_transition_contracts": [contract],
        }
        normalized = validate_internal_transition_sequence(unit)
        self.assertEqual(normalized[0]["from_dialogue_speaker"], "世子")
        self.assertEqual(normalized[0]["to_dialogue_speaker"], "陈迹")
        self.assertFalse(normalized[0]["reference_bridge"]["same_slot_reuse_allowed"])

    def test_dialogue_speaker_must_exist_in_beat_cast(self):
        previous = spec("世子", dialogue="陈迹：十两。")
        current = spec("陈迹")
        contract = internal_contract("VU-1", "S1", "S2", previous, current, mode="MOTIVATED_CUT")
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [previous, current],
            "internal_transition_contracts": [contract],
        }
        with self.assertRaisesRegex(ValueError, "dialogue speaker is absent"):
            validate_internal_transition_sequence(unit)

    def test_scene_bridge_must_match_both_authored_map_spaces(self):
        previous = spec("世子", subspace="SUB-A")
        current = spec("陈迹", subspace="SUB-B")
        contract = internal_contract("VU-1", "S1", "S2", previous, current, mode="MOTIVATED_CUT")
        contract["scene_bridge"]["to_space"]["subspace"] = "SUB-WRONG"
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [previous, current],
            "internal_transition_contracts": [contract],
        }
        with self.assertRaisesRegex(ValueError, "scene_bridge is not exactly bound"):
            validate_internal_transition_sequence(unit)

    def test_prop_bridge_must_match_both_authored_beat_states(self):
        previous = spec("世子", prop="银子")
        current = spec("陈迹", prop="药方")
        contract = internal_contract("VU-1", "S1", "S2", previous, current, mode="MOTIVATED_CUT")
        contract["prop_bridge"]["to_props"] = ["银子"]
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [previous, current],
            "internal_transition_contracts": [contract],
        }
        with self.assertRaisesRegex(ValueError, "to_props must exactly match"):
            validate_internal_transition_sequence(unit)

    def test_sound_bridge_must_match_ambience_foley_and_action_sound(self):
        previous = spec("世子")
        current = spec("陈迹")
        current["sound_design"]["ambience"] = "雨夜街声"
        contract = internal_contract("VU-1", "S1", "S2", previous, current, mode="MOTIVATED_CUT")
        contract["sound_bridge"]["to_sound"]["ambience"] = "错误宴席声"
        unit = {
            "unit_id": "VU-1",
            "editorial_shot_ids": ["S1", "S2"],
            "ordered_prompt_specs": [previous, current],
            "internal_transition_contracts": [contract],
        }
        with self.assertRaisesRegex(ValueError, "sound_bridge is not exactly bound"):
            validate_internal_transition_sequence(unit)

    def test_map_slot_replacement_is_reported(self):
        unit = {"editorial_shot_ids": ["S1", "S2"]}
        maps = {
            "S1": {"blocking": {"characters": [{"character_id": "CHAR-SHIZI", "zone_id": "ZONE-A", "position": [1, 2]}]}},
            "S2": {"blocking": {"characters": [{"character_id": "CHAR-CHENJI", "zone_id": "ZONE-A", "position": [1, 2]}]}},
        }
        findings = find_same_slot_character_replacements(unit, maps)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["from_character_id"], "CHAR-SHIZI")
        self.assertEqual(findings[0]["to_character_id"], "CHAR-CHENJI")


if __name__ == "__main__":
    unittest.main()
