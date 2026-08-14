import json
import tempfile
import unittest
from pathlib import Path

from tools.build_e27_pro_script_image_batch import SCRIPT, build
from tools.scene_authority_lock import evaluate_batch


class BuildE27ProScriptImageBatchTest(unittest.TestCase):
    def test_builds_six_script_locked_parallel_tasks_with_explicit_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / SCRIPT
            script.parent.mkdir(parents=True)
            script.write_text("professional locked script", encoding="utf-8")
            result = build(root)
            config = json.loads(Path(result["config"]).read_text(encoding="utf-8"))
            scene_state = json.loads(Path(result["scene_state"]).read_text(encoding="utf-8"))

            self.assertEqual(result["scene_count"], 6)
            self.assertEqual(config["concurrency"], 6)
            self.assertTrue(config["parallel_submission"])
            self.assertEqual(len(config["tasks"]), 6)
            self.assertEqual(scene_state["scene_state"][0]["time_of_day"], "clear daytime")
            self.assertIn("night", scene_state["scene_state"][1]["time_of_day"])
            self.assertNotEqual(scene_state["scene_state"][0]["time_of_day"], scene_state["scene_state"][1]["time_of_day"])
            first_prompt = Path(root / config["tasks"][0]["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("NEGATIVE_PROMPT:", first_prompt)
            gate_config = dict(config)
            gate_config["tasks"] = [dict(task) for task in config["tasks"]]
            for task in gate_config["tasks"]:
                task["prompt_file"] = str(root / task["prompt_file"])
            gate = evaluate_batch(result["scene_state"], gate_config)
            self.assertEqual(gate["status"], "PASS", gate["failures"])
            for task in config["tasks"]:
                self.assertEqual(task["tool_type"], "image_generation")
                self.assertEqual(task["status"], "READY_FOR_PARALLEL_SUBMIT")


if __name__ == "__main__":
    unittest.main()
