import json
import tempfile
import unittest
from pathlib import Path

from tools.build_e40_spatial_keyframe_batch import DEFAULT_PLAN, build


class BuildE40SpatialKeyframeBatchTest(unittest.TestCase):
    def test_compiles_independent_spatial_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build(
                DEFAULT_PLAN,
                root / "prompts",
                root / "manifest.json",
                {"R02", "R07"},
            )
            self.assertEqual([task["unit_id"] for task in manifest["tasks"]], ["R02", "R07"])
            self.assertTrue(manifest["global_space_map_gate_required"])
            identity_report = Path(manifest["machine_gate_reports"][1])
            self.assertTrue(identity_report.is_file())
            self.assertEqual(json.loads(identity_report.read_text())["gate_id"], "CHARACTER-IDENTITY-ADMISSION")
            for task in manifest["tasks"]:
                self.assertEqual(task["status"], "READY_FOR_PARALLEL_SUBMIT")
                self.assertEqual(task["prompt_contract"]["status"], "PASS")
                roles = [row["role"] for row in task["reference_bindings"]]
                self.assertIn("scene", roles)
                self.assertEqual(roles[:3], ["episode_global_space_map", "global_space_map", "subspace_layout"])
                returning = [
                    row for row in task["reference_bindings"]
                    if row["role"] == "character" and row["entity_id"] in {
                        "CHAR-陈迹-古装", "CHAR-云妃-古装", "CHAR-白鲤-古装",
                        "CHAR-皎兔-古装", "CHAR-云羊-古装", "CHAR-乌云-猫",
                    }
                ]
                self.assertTrue(returning)
                self.assertTrue(all(row["asset_origin"] == "CANONICAL_NATIVE_REGISTRY" for row in returning))
                self.assertFalse(any("fresh_identity_v2" in row["path"] for row in returning))
                expected_visible = {
                    row["character_id"]
                    for block in (task.get("blocking") or {}, task.get("action_end_blocking") or {})
                    for row in block.get("characters") or []
                }
                self.assertEqual(set(task["canonical_characters"]), expected_visible)
                prompt = Path(task["prompt_file"]).read_text(encoding="utf-8")
                self.assertIn(task["canonical_script_action"], prompt)
            persisted = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["tasks"]), 2)

    def test_episode_appearance_locks_and_existing_ashuan_evidence_are_compiled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build(
                DEFAULT_PLAN,
                root / "prompts",
                root / "manifest.json",
                {"R01", "R06A"},
            )
            tasks = {task["unit_id"]: task for task in manifest["tasks"]}
            r01_prompt = Path(tasks["R01"]["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("面纱必须覆面", r01_prompt)
            self.assertIn("不露脸微笑", r01_prompt)
            ashuan = next(
                row for row in tasks["R06A"]["reference_bindings"]
                if row.get("entity_id") == "CHAR-阿栓-古装"
            )
            self.assertEqual(
                ashuan["qa_report"],
                "qa/e38_replacement_v7_20260805/E38_V7_CHARACTER_ASSET_FINAL_ADMISSION.json",
            )
            self.assertTrue(Path(ashuan["qa_report"]).is_file())


if __name__ == "__main__":
    unittest.main()
