"""Two field blockers of 2026-11-17.

1. Fleet device 1101 E15: a rolling wave rewrote the full grouping plan and the full gated anchor plan, but
   the full H3 compile copy still described the grouping S2 saw, so the planning compile failed with
   H3_SPEAKER_SUBJECT_BINDING_MISSING for a unit whose shots had moved.
2. Fleet devices 0899 E17/E18 and 1037 E16: S1 came back BLOCKED with ``blockers: []`` when only the
   dialogue register gate failed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (NALU_TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SPEAKER = "CHAR-DISCIPLE"


class WaveKeepsFullH3CompileAnchorCurrentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bnp = load("bnp_wave_full_h3_compile", NALU_TOOLS / "build_nalu_preproduction.py")
        except Exception as exc:  # noqa: BLE001 - the module needs the full engine tree
            raise unittest.SkipTest(f"build_nalu_preproduction not importable: {exc}")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pre = Path(self.tmp.name)
        self.plate = self.pre / "plate_disciple.png"
        self.plate.write_bytes(b"png")
        self.editorial = {"shots": [
            {"shot_id": "E15-S02-03", "prompt_spec": {"dialogue": "", "cast": []}},
            {"shot_id": "E15-S04-01", "prompt_spec": {"dialogue": "弟子：师父回来了。", "cast": [
                {"character": "弟子", "character_id": SPEAKER}]}}]}
        # the grouping moved after S5: the speaking shot now belongs to VU-008 (it was VU-007's)
        self.full_plan = self.pre / "E15_VIDEO_UNIT_GROUPING_PLAN_V1.json"
        self.full_plan.write_text(json.dumps({"units": [
            {"unit_id": "E15-VU-007", "editorial_shot_ids": ["E15-S02-03"]},
            {"unit_id": "E15-VU-008", "editorial_shot_ids": ["E15-S04-01"]}]}), encoding="utf-8")
        self.full_anchor = self.pre / "E15_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
        self.full_anchor.write_text(json.dumps({"units": [
            {"unit_id": "E15-VU-007", "reference_image_paths": [], "planned_reference_image_count": 0},
            {"unit_id": "E15-VU-008", "reference_image_paths": [], "planned_reference_image_count": 0}]}),
            encoding="utf-8")
        # what S2 left behind: the plate sits on the unit that used to hold the speaking shot
        self.compile_copy = self.pre / "E15_VIDEO_UNIT_ANCHOR_PLAN_H3_COMPILE_V1.json"
        self.compile_copy.write_text(json.dumps({"units": [
            {"unit_id": "E15-VU-007", "reference_image_paths": [str(self.plate)],
             "reference_entity_bindings": [{"entity_id": SPEAKER}]},
            {"unit_id": "E15-VU-008", "reference_image_paths": [], "reference_entity_bindings": []}]}),
            encoding="utf-8")

    def rewrite(self):
        with patch.object(self.bnp, "_h3_reference_plate", return_value=self.plate), \
                patch.object(self.bnp, "faceless_character_ids", return_value=set()), \
                patch.object(self.bnp, "append_h3_prop_plates", return_value=[]):
            return self.bnp.write_full_h3_compile_anchor(
                self.full_anchor, self.full_plan, self.editorial, episode="E15")

    def test_plate_follows_the_speaking_shot_to_its_new_unit(self):
        path = self.rewrite()
        self.assertEqual(Path(path), self.compile_copy)
        units = {u["unit_id"]: u for u in json.loads(self.compile_copy.read_text(encoding="utf-8"))["units"]}
        self.assertEqual(units["E15-VU-008"]["reference_image_paths"], [str(self.plate)])
        self.assertEqual([row["entity_id"] for row in units["E15-VU-008"]["reference_entity_bindings"] if row],
                         [SPEAKER])
        self.assertEqual(units["E15-VU-007"]["reference_image_paths"], [])

    def test_copy_records_its_gated_source_and_missing_lists(self):
        self.rewrite()
        copy = json.loads(self.compile_copy.read_text(encoding="utf-8"))
        self.assertEqual(copy["source_gated_anchor_plan_sha256"], self.bnp.sha256_file(self.full_anchor))
        self.assertEqual(copy["h3_identity_plates_missing"], [])
        self.assertEqual(copy["h3_prop_reference_cards_missing"], [])
        self.assertEqual(copy["planned_reference_image_count"], 1)

    def test_gated_full_anchor_plan_is_left_untouched(self):
        before = self.full_anchor.read_bytes()
        self.rewrite()
        self.assertEqual(self.full_anchor.read_bytes(), before)

    def test_wave_run_calls_the_rewrite(self):
        source = (NALU_TOOLS / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        self.assertIn("write_full_h3_compile_anchor(_full_anchor[1], full_plan_path, editorial, episode=episode)",
                      source)


class S1ShowsTheDialogueRegisterFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import nalu_pipeline as npl
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"nalu_pipeline not importable: {exc}")
        cls.npl = npl

    def test_rule_totals_become_blockers(self):
        report = {"status": "FAIL", "failures": ["DIALOGUE_SOURCE_VERBATIM:13", "DIALOGUE_ONE_VOICE:1"]}
        self.assertEqual(self.npl.dialogue_register_blockers(report),
                         ["DIALOGUE_REGISTER_FAIL:DIALOGUE_SOURCE_VERBATIM:13",
                          "DIALOGUE_REGISTER_FAIL:DIALOGUE_ONE_VOICE:1"])

    def test_failed_gate_without_a_rule_still_names_itself(self):
        self.assertEqual(self.npl.dialogue_register_blockers({"status": "FAIL", "failures": []}),
                         ["DIALOGUE_REGISTER_FAIL:FAIL"])
        self.assertEqual(self.npl.dialogue_register_blockers({}), ["DIALOGUE_REGISTER_FAIL:NO_REPORT"])

    def test_summary_carries_totals_and_report_path_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.json"
            path.write_text("{}", encoding="utf-8")
            summary = self.npl.dialogue_register_summary(
                {"status": "FAIL", "exit_code": 3, "failures": ["DIALOGUE_SOURCE_VERBATIM:13"],
                 "verbatim": [{"text": "不该出现在阶段结果里的台词"}]}, path)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["failures"], ["DIALOGUE_SOURCE_VERBATIM:13"])
        self.assertEqual(summary["report"], str(path))
        self.assertNotIn("不该出现", json.dumps(summary, ensure_ascii=False))

    def test_s1_adds_the_blocker_and_the_detail(self):
        source = (NALU_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('res.details["dialogue_register_gate"] = dialogue_register_summary(', source)
        self.assertIn("+ dialogue_register_blockers(dialogue_register)", source)


if __name__ == "__main__":
    unittest.main()
