import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.action_video_prompt_compiler import compile_action_video_prompt, validate_action_contract


class ActionVideoPromptCompilerTest(unittest.TestCase):
    def fixture(self):
        return {
            "shot_type": "DIALOGUE",
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

    def combat_fixture(self):
        task = self.fixture()
        task.update({
            "shot_type": "COMBAT",
            "canonical_unit_text": "△【打斗·起·4s·冰壁护钥】双方立即接触。",
            "duration_seconds": 10,
            "cut_plan": [{"duration": 2.0} for _ in range(5)],
            "fight_scene_breathing_contract": {"rounds": [
                {"burst_seconds": 2.0, "buildup_seconds": 1.0, "burst_motion_per_second": 12}
                for _ in range(3)
            ]},
        })
        task["performance_tempo_contract"].update({
            "contact_by_seconds": 0.2,
            "primary_exchange_complete_by_seconds": 1.5,
            "aftermath_in_same_edit_shot": False,
            "exchange_plan": [
                {"action": "甲突入，乙格挡"},
                {"action": "乙反击，甲闪避"},
                {"action": "甲借柱转位再压制"},
            ],
        })
        return task

    def test_combat_compiles_multi_exchange_editorial_contract(self):
        task = self.combat_fixture()
        self.assertEqual(validate_action_contract(task), [])
        prompt = compile_action_video_prompt(task)
        self.assertIn("0.2秒内发生接触", prompt)
        self.assertIn("拆成4至6个短镜", prompt)

    def test_combat_rejects_old_slow_single_action_template(self):
        task = self.combat_fixture()
        task["duration_seconds"] = 4
        task["performance_tempo_contract"].update({
            "contact_by_seconds": 0.8,
            "primary_exchange_complete_by_seconds": 1.8,
            "aftermath_in_same_edit_shot": True,
            "exchange_plan": [{"action": "single slow strike"}],
        })
        task["cut_plan"] = [{"duration": 4.0}]
        failures = validate_action_contract(task)
        self.assertIn("COMBAT_CONTACT_MUST_BEGIN_BY_0P2_SECONDS", failures)
        self.assertIn("COMBAT_AFTERMATH_HOLD_FORBIDDEN_IN_SAME_EDIT_SHOT", failures)
        self.assertIn("COMBAT_GENERATION_REQUIRES_3_TO_4_EXCHANGES", failures)

    def test_dialogue_is_not_forced_through_combat_timing(self):
        task = self.fixture()
        task["shot_type"] = "DIALOGUE"
        task["duration_seconds"] = 4
        self.assertEqual(validate_action_contract(task), [])

    def test_missing_shot_type_on_canonical_combat_fails(self):
        task = self.combat_fixture()
        del task["shot_type"]
        failures = validate_action_contract(task)
        self.assertIn("SHOT_TYPE_NOT_DECLARED", failures)
        self.assertIn("SHOT_TYPE_MISMATCH_CANONICAL_COMBAT", failures)

    def test_declared_combat_matching_canonical_passes(self):
        self.assertEqual(validate_action_contract(self.combat_fixture()), [])

    def test_combat_declaration_on_noncombat_canonical_fails(self):
        task = self.combat_fixture()
        task["canonical_unit_text"] = "△【近景·4s·静水承注】人物抬眼听话。"
        self.assertIn("SHOT_TYPE_COMBAT_NOT_IN_CANONICAL", validate_action_contract(task))

    def test_reads_only_bound_canonical_unit(self):
        with TemporaryDirectory() as directory:
            script = Path(directory) / "E41.md"
            script.write_text(
                "**14-6．内库**（12s）\n△【特写】开锁。\n"
                "**14-7．内库**（20s｜FS-1 完整打斗 16s 起承转合）\n"
                "△【打斗·起·4s】护钥。\n"
                "**14-8．暗格前**（15s）\n△【近景】查看空格。\n",
                encoding="utf-8",
            )
            task = self.combat_fixture()
            task.pop("canonical_unit_text")
            task.update({"canonical_script_path": str(script), "canonical_unit_id": "14-7"})
            self.assertEqual(validate_action_contract(task), [])


if __name__ == "__main__":
    unittest.main()
