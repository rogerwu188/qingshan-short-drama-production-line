from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "tools/tests/TEST_MIGRATION_MAP.md"

# Requirement-bearing tests that replaced legacy serializer/string assertions.
# Removing or renaming one requires an explicit registry and migration-map change.
REQUIRED_REPLACEMENT_TESTS = {
    "tools/tests/test_video_prompt_compiler.py": {
        "test_router_keeps_seedance_grammar_independent",
        "test_h3_dialogue_is_the_only_cjk_outside_machine_metadata",
        "test_h3_dialogue_fails_closed_without_speaker_voice_contract",
        "test_h3_silent_unit_explicitly_closes_mouths",
        "test_h3_cjk_and_quoted_cjk_hard_checks",
        "test_h3_zero_text_frame_contract_is_fail_closed",
        "test_h3_contact_action_binds_limb_ownership_and_occlusion_topology",
        "test_h3_combat_uses_real_motion_contract_not_reference_tableaux",
        "test_h3_transition_contract_is_serialized_as_semantics_not_ids",
        "test_h3_internal_transition_rows_bind_in_exact_shot_order",
        "test_h3_strips_speakable_action_scaffolding_by_translation_boundary",
        "test_h3_profiles_preserve_existing_safety_constraints",
        "test_h3_adult_female_visual_is_explicitly_adult_and_model_specific",
        "test_h3_adult_female_visual_rejects_explicit_direction",
        "test_model_prompt_is_compact_and_does_not_leak_machine_contract",
    },
    "tools/tests/test_shared_video_execution_compiler.py": {
        "test_sd2_and_h3_share_execution_semantics_but_not_prompt_grammar",
        "test_identical_entry_and_exit_fails_closed",
        "test_combat_impulse_gates_are_deterministic",
    },
    "tools/tests/test_video_sequence_rhythm_gate.py": {
        "test_five_identical_short_combat_units_fail",
        "test_contrast_and_exchange_pass",
        "test_named_director_override_is_auditable",
    },
    "tools/tests/test_media_motion_energy_gate.py": {
        "test_absolute_score_is_advisory_until_calibrated",
        "test_ab_requires_1_8x_improvement_and_cut_is_excluded",
    },
}


class PromptTestMigrationMapGateTest(unittest.TestCase):
    def test_registered_replacement_tests_exist_and_are_mapped(self) -> None:
        migration_map = MAP_PATH.read_text(encoding="utf-8")
        for relative_path, required_names in REQUIRED_REPLACEMENT_TESTS.items():
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            discovered = set(re.findall(r"^\s*def\s+(test_[A-Za-z0-9_]+)\s*\(", source, re.MULTILINE))
            self.assertFalse(
                required_names - discovered,
                f"unmapped requirement-bearing test deletion in {relative_path}: "
                f"{sorted(required_names - discovered)}",
            )
            for name in required_names:
                self.assertIn(name, migration_map, f"replacement test missing from migration map: {name}")


if __name__ == "__main__":
    unittest.main()
