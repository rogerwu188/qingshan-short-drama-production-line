from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import unittest

from tools.wuxia_combat_profile_selector import load_library, select_wuxia_combat_profiles
from tools.video_execution_plan_compiler import compile_video_execution_plan
from tools.tests.test_shared_video_execution_compiler import _unit


def stable_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


class WuxiaCombatProfileSelectorTest(unittest.TestCase):
    def test_library_contains_all_34_reference_profiles(self) -> None:
        library = load_library()
        self.assertEqual(len(library["profiles"]), 34)
        self.assertEqual(
            library["reference_lineage"]["status"],
            "INFERRED_RECONSTRUCTED_NOT_ORIGINAL",
        )
        self.assertIn("WXC-SWORD-01", library["by_id"])
        self.assertIn("WXC-GROUP-03", library["by_id"])
        self.assertIn("WXC-FX-04", library["by_id"])

    def test_explicit_selection_is_deterministic_and_does_not_mutate_sources(self) -> None:
        unit = _unit()
        before = stable_sha(unit)
        plan1 = compile_video_execution_plan(unit)
        plan2 = compile_video_execution_plan(unit)
        self.assertEqual(before, stable_sha(unit))
        self.assertEqual(
            plan1["wuxia_combat_profile_selection"]["selected_profile_ids"],
            ["WXC-SWORD-02", "WXC-ENV-01"],
        )
        self.assertEqual(
            plan1["wuxia_combat_profile_selection"],
            plan2["wuxia_combat_profile_selection"],
        )
        self.assertTrue(plan1["wuxia_combat_profile_selection"]["source_unchanged"])
        self.assertFalse(
            plan1["wuxia_combat_profile_selection"]["post_generation_dynamic_action_qa_required"]
        )

    def test_contact_profile_cannot_bind_to_evasion_action_ir(self) -> None:
        unit = _unit()
        unit["wuxia_combat_profile_signals"]["interaction_modes"] = ["EVASION"]
        action = unit["ordered_prompt_specs"][0]["action"]
        action["interaction_mode"] = "EVASION"
        action["contact_time_seconds"] = None
        action["contact_point"] = ""
        action["evasion_result"] = "短刀从陈迹衣襟外侧通过，双方没有接触"
        with self.assertRaisesRegex(ValueError, "WUXIA_PROFILE_EXPLICIT_CONFLICT.*INTERACTION_MISMATCH"):
            compile_video_execution_plan(unit)

    def test_fx_profile_requires_explicit_authorization(self) -> None:
        unit = _unit()
        unit["wuxia_combat_profile_signals"]["profile_ids"] = ["WXC-FX-03"]
        with self.assertRaisesRegex(ValueError, "WUXIA_PROFILE_FX_NOT_AUTHORIZED"):
            compile_video_execution_plan(unit)

    def test_fx_is_never_inferred(self) -> None:
        unit = _unit()
        unit["wuxia_combat_profile_signals"].pop("profile_ids")
        unit["ordered_prompt_specs"][0]["action"]["primary_action"] += "，护体屏障破裂"
        selection = compile_video_execution_plan(unit)["wuxia_combat_profile_selection"]
        self.assertFalse(any(pid.startswith("WXC-FX") for pid in selection["selected_profile_ids"]))

    def test_noncombat_is_not_applicable(self) -> None:
        unit = _unit()
        unit["wuxia_combat_profile_required"] = False
        unit["wuxia_combat_profile_signals"] = {}
        action = unit["ordered_prompt_specs"][0]["action"]
        action["action_kind"] = "PHYSICAL_ACTION"
        action["primary_action"] = "陈迹从桌后走到窗边"
        action["contact_time_seconds"] = None
        action["contact_point"] = ""
        action["force_feedback"] = "衣摆随脚步轻动"
        action["completion_state"] = "陈迹站在窗边"
        action["state_delta_dimensions"] = ["POSITION"]
        action["state_delta_evidence"] = {
            "POSITION": {"entry": "桌后", "exit": "窗边", "entry_code": "TABLE", "exit_code": "WINDOW"}
        }
        plan = compile_video_execution_plan(unit)
        self.assertEqual(plan["wuxia_combat_profile_selection"]["status"], "NOT_APPLICABLE")

    def test_direct_selector_reports_unresolved_shadow_without_inventing(self) -> None:
        unit = _unit()
        unit["wuxia_combat_profile_required"] = False
        unit["wuxia_combat_profile_signals"] = {"weapon_type": "UNKNOWN", "cast_count": 2}
        for spec in unit["ordered_prompt_specs"]:
            spec["props"] = []
            spec["action"]["primary_action"] = "甲快速逼近乙"
        action_ir = {"causal_chains": [{"interaction_mode": "CONTACT"}]}
        selection = select_wuxia_combat_profiles(
            unit, action_ir=deepcopy(action_ir), unit_class="COMBAT_IMPULSE"
        )
        self.assertEqual(selection["status"], "UNRESOLVED_SHADOW")
        self.assertEqual(selection["selected_profile_ids"], [])


if __name__ == "__main__":
    unittest.main()
