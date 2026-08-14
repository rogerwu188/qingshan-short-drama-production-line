import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "submit_e20_static_visual_lock_batch.py"
SPEC = importlib.util.spec_from_file_location("submit_e20_static_visual_lock_batch", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class E20StaticVisualLockBatchTests(unittest.TestCase):
    def test_contract_builds_exactly_fifteen_static_tasks(self):
        base = Path(__file__).resolve().parents[2]
        contract = json.loads(
            (base / "configs" / "e20_visual_lock_prompt_drafts_v0_20260716.json").read_text(
                encoding="utf-8"
            )
        )
        tasks = MODULE.build_tasks(contract)
        self.assertEqual(len(tasks), 15)
        self.assertEqual(len({task["view_id"] for task in tasks}), 15)
        self.assertTrue(all("Hard exclusions:" in task["prompt"] for task in tasks))

    def test_closed_static_gate_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.build_tasks(
                {
                    "generation_allowed": False,
                    "static_candidate_generation_allowed": False,
                    "lock_prompts": [],
                }
            )

    def test_image_extension_uses_asset_url_suffix(self):
        self.assertEqual(MODULE.image_ext("https://assets.example/a.png?token=x"), ".png")
        self.assertEqual(MODULE.image_ext("https://short.example/id"), ".png")

    def test_atomic_json_write_replaces_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "status.json"
            MODULE.write_json_atomic(target, {"ok": True})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})
