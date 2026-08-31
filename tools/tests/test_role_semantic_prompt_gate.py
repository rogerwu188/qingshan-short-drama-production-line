import unittest

from tools.role_semantic_prompt_gate import (
    SCHEMA,
    role_semantic_compact_prompt_block,
    role_semantic_prompt_block,
    validate_role_semantics,
)
from tools.video_physical_continuity_contract import is_combat_unit


def role_row(**overrides):
    row = {
        "schema": SCHEMA,
        "status": "PASS",
        "shot_id": "E48-S01-01",
        "primary_actor": "陈迹",
        "primary_actor_kind": "CHARACTER",
        "dialogue_speaker": "陈迹",
        "dialogue_listener": "金猪",
        "action_patient": "",
        "first_person_pronoun": "陈迹",
        "second_person_pronoun": "金猪",
        "action_pronoun_referent": "陈迹",
        "action_counterparty_referent": "金猪",
        "dialogue_third_person_referent": "军情司叛谍",
        "body_part_owner": "",
        "entity_states": {
            "陈迹": "唯一说话人与动作执行者",
            "金猪": "唯一听者，闭口",
            "军情司叛谍": "仅为对白指代对象，不出现",
        },
        "entity_presence": {
            "陈迹": "VISIBLE_AND_IDENTITY_LOCKED",
            "金猪": "VISIBLE_AND_IDENTITY_LOCKED",
            "军情司叛谍": "ABSENT_REFERENCE_ONLY",
        },
        "forbidden_role_swaps": True,
        "unresolved": [],
    }
    row.update(overrides)
    return row


class RoleSemanticPromptGateTest(unittest.TestCase):
    def test_exact_registered_role_block_passes(self):
        row = role_row()
        task = {"episode": "E48", "role_semantic_disambiguation": row}
        prompt = role_semantic_prompt_block(row)
        self.assertEqual(validate_role_semantics(task, prompt), [])

    def test_compact_speech_isolation_role_block_passes(self):
        row = role_row()
        task = {"episode": "E48", "role_semantic_disambiguation": row}
        prompt = role_semantic_compact_prompt_block(row)
        self.assertEqual(validate_role_semantics(task, prompt), [])

    def test_body_part_without_named_owner_fails(self):
        row = role_row(
            primary_actor="右手",
            primary_actor_kind="BODY_PART",
            dialogue_speaker="",
            dialogue_listener="",
            first_person_pronoun="",
            second_person_pronoun="",
            action_pronoun_referent="右手",
            action_counterparty_referent="窗纸缝隙",
            dialogue_third_person_referent="",
            entity_states={"右手": "推动窗纸", "窗纸缝隙": "被推动"},
            entity_presence={
                "右手": "VISIBLE_AND_IDENTITY_LOCKED",
                "窗纸缝隙": "VISIBLE_AND_IDENTITY_LOCKED",
            },
        )
        failures = validate_role_semantics(
            {"episode": "E48", "role_semantic_disambiguation": row},
            role_semantic_prompt_block(row),
        )
        self.assertIn("ROLE_1_BODY_PART_OWNER_MISSING", failures)

    def test_unregistered_pronoun_referent_fails(self):
        row = role_row(action_counterparty_referent="另一个男人")
        failures = validate_role_semantics(
            {"episode": "E48", "role_semantic_disambiguation": row},
            role_semantic_prompt_block(row),
        )
        self.assertIn(
            "ROLE_1_ACTION_COUNTERPARTY_REFERENT_NOT_REGISTERED:另一个男人",
            failures,
        )

    def test_duplicate_shot_ids_fail_closed(self):
        first = role_row()
        second = role_row()
        task = {
            "episode": "E48",
            "machine_contract": {
                "ordered_prompt_specs": [
                    {"role_semantic_disambiguation": first},
                    {"role_semantic_disambiguation": second},
                ]
            },
        }
        prompt = role_semantic_prompt_block(first) + role_semantic_prompt_block(second)
        failures = validate_role_semantics(task, prompt)
        self.assertIn("ROLE_2_DUPLICATE_SHOT_ID:E48-S01-01", failures)

    def test_source_authority_prevents_evidence_knife_false_combat(self):
        unit = {
            "combat_classification_override": "NON_COMBAT_SOURCE_AUTHORITY",
            "action_classification": "GENERAL_PERFORMANCE",
            "prompt": "门槛旁留下短刀证据，没有打斗",
        }
        self.assertFalse(is_combat_unit(unit))


if __name__ == "__main__":
    unittest.main()
