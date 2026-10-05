"""Test entity instance count gate."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.entity_instance_count_gate import evaluate, evaluate_unit


class EntityInstanceCountGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_declared_two_bound_one_blocks(self):
        """Case 3a: entity declares instance_count=2 but only one reference bound → BLOCK."""
        contract = {
            "non_character_entities": [
                {"entity_id": "CAT_01", "display_name": "狸花猫", "kind": "CREATURE", "instance_count": 2}
            ]
        }
        projection = {
            "reference_identity_bindings": [
                {"reference_index": 1, "entity_id": "CAT_01", "provider_entity_label": "cat", "exclusive_identity_owner": True}
            ]
        }
        prompt = "A cat sits in the frame."

        result = evaluate(contract=contract, unit_plan={}, provider_scope_projection=projection, prompt_text=prompt)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["entities_checked"], 1)
        failures = result["failures"]
        self.assertTrue(any("ENTITY_INSTANCE_COUNT_UNDERBOUND:CAT_01" in f for f in failures))

    def test_no_instance_count_declaration_skipped(self):
        """Case 3b: entity without instance_count field → skip, don't assume default."""
        contract = {
            "non_character_entities": [
                {"entity_id": "PROP_01", "display_name": "木盒", "kind": "PROP"}
                # No instance_count field
            ]
        }
        projection = {
            "reference_identity_bindings": [
                {"reference_index": 1, "entity_id": "PROP_01", "provider_entity_label": "wooden box", "exclusive_identity_owner": True}
            ]
        }
        prompt = "A wooden box on the table."

        result = evaluate(contract=contract, unit_plan={}, provider_scope_projection=projection, prompt_text=prompt)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["entities_checked"], 0)
        self.assertEqual(result["failures"], [])

    def test_declared_bound_but_absent_from_prompt_blocks(self):
        """Entity declared, bound, but not in final prompt → BLOCK."""
        contract = {
            "non_character_entities": [
                {"entity_id": "BIRD_01", "display_name": "鸟", "kind": "CREATURE", "instance_count": 1}
            ]
        }
        projection = {
            "reference_identity_bindings": [
                {"reference_index": 1, "entity_id": "BIRD_01", "provider_entity_label": "bird", "exclusive_identity_owner": True}
            ]
        }
        prompt = "An empty sky."

        result = evaluate(contract=contract, unit_plan={}, provider_scope_projection=projection, prompt_text=prompt)

        self.assertEqual(result["status"], "FAIL")
        failures = result["failures"]
        self.assertTrue(any("ENTITY_ABSENT_FROM_PROMPT:BIRD_01:bird" in f for f in failures))

    def test_valid_single_instance_passes(self):
        """Entity with instance_count=1, one binding, present in prompt → PASS."""
        contract = {
            "non_character_entities": [
                {"entity_id": "HORSE_01", "display_name": "马", "kind": "CREATURE", "instance_count": 1}
            ]
        }
        projection = {
            "reference_identity_bindings": [
                {"reference_index": 1, "entity_id": "HORSE_01", "provider_entity_label": "horse", "exclusive_identity_owner": True}
            ]
        }
        prompt = "A horse gallops across the field."

        result = evaluate(contract=contract, unit_plan={}, provider_scope_projection=projection, prompt_text=prompt)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["entities_checked"], 1)
        self.assertEqual(result["failures"], [])

    def test_invalid_instance_count_blocks(self):
        """instance_count is not a positive int → BLOCK."""
        contract = {
            "non_character_entities": [
                {"entity_id": "INVALID_01", "display_name": "测试", "kind": "PROP", "instance_count": 0}
            ]
        }
        projection = {"reference_identity_bindings": []}
        prompt = ""

        result = evaluate(contract=contract, unit_plan={}, provider_scope_projection=projection, prompt_text=prompt)

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("ENTITY_INSTANCE_COUNT_INVALID:INVALID_01:0" in f for f in result["failures"]))

    def test_evaluate_unit_wrapper(self):
        """evaluate_unit convenience wrapper extracts projection and prompt from unit dict."""
        contract = {
            "non_character_entities": [
                {"entity_id": "DOG_01", "display_name": "狗", "kind": "CREATURE", "instance_count": 1}
            ]
        }
        unit = {
            "provider_scope_projection": {
                "reference_identity_bindings": [
                    {"reference_index": 1, "entity_id": "DOG_01", "provider_entity_label": "dog", "exclusive_identity_owner": True}
                ]
            },
            "compiled_prompt": {
                "positive": "A dog barks loudly."
            }
        }

        result = evaluate_unit(contract, unit)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["entities_checked"], 1)


if __name__ == '__main__':
    unittest.main()
