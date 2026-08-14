import json
import tempfile
import unittest
from pathlib import Path

from tools.build_ocr_safe_failed_only_retry import build_retry


class OcrSafeRetryTests(unittest.TestCase):
    def test_preserves_passes_and_rewrites_only_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompt = root / "base.txt"
            prompt.write_text("locked story and dialogue")
            config = root / "config.json"
            config.write_text(json.dumps({"episode": "E26", "tasks": [
                {"task_key": "PASS", "prompt_file": str(prompt), "metadata": {}},
                {"task_key": "FAIL", "prompt_file": str(prompt), "metadata": {"dialogue": "unchanged"}},
            ]}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [
                {"task_key": "PASS", "status": "qa_pass"},
                {"task_key": "FAIL", "status": "qa_failed_terminal"},
            ]}))
            output = root / "out.json"
            result = build_retry(config, receipt, output, root / "prompts", "R3")
            payload = json.loads(output.read_text())
            self.assertEqual(result["retry_task_count"], 1)
            self.assertEqual(len(payload["tasks"]), 1)
            self.assertEqual(payload["tasks"][0]["metadata"]["dialogue"], "unchanged")
            amended = Path(payload["tasks"][0]["prompt_file"]).read_text()
            self.assertIn("locked story and dialogue", amended)
            self.assertIn("无刺绣", amended)
            self.assertIn("合拢并以无字纯色封皮背向镜头", amended)

    def test_silent_visual_removes_spoken_lines_and_marks_audio_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompt = root / "base.txt"
            prompt.write_text("角色陈迹清楚说：{台词。}。只有该角色口型运动。\n其他动作保持。")
            config = root / "config.json"
            config.write_text(json.dumps({"episode": "E27", "tasks": [
                {"task_key": "FAIL", "prompt_file": str(prompt), "reference_images": ["bad.png"], "metadata": {}},
            ]}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [{"task_key": "FAIL", "status": "qa_failed_terminal"}]}))
            output = root / "out.json"
            build_retry(config, receipt, output, root / "prompts", "R4", silent_visual=True, drop_references=True)
            task = json.loads(output.read_text())["tasks"][0]
            amended = Path(task["prompt_file"]).read_text()
            self.assertNotIn("角色陈迹清楚说", amended)
            self.assertIn("无对白纯视觉替换源", amended)
            self.assertEqual(task["reference_images"], [])
            self.assertTrue(task["metadata"]["reuse_admitted_dialogue_audio_in_agentcut"])

    def test_silent_visual_rewrites_text_bearing_plot_props(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompt = root / "base.txt"
            prompt.write_text("送令兵拍令并展示搜查令，陈迹夺令，官印与药账在药柜、账柜前入镜，普通话口型清晰。")
            config = root / "config.json"
            config.write_text(json.dumps({"episode": "E27", "tasks": [
                {"task_key": "FAIL", "prompt_file": str(prompt), "metadata": {}},
            ]}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [{"task_key": "FAIL", "status": "qa_failed_terminal"}]}))
            output = root / "out.json"
            build_retry(config, receipt, output, root / "prompts", "R5", silent_visual=True)
            amended = Path(json.loads(output.read_text())["tasks"][0]["prompt_file"]).read_text()
            for risky_term in ("送令兵", "搜查令", "官印", "药账", "药柜", "账柜", "普通话口型清晰"):
                self.assertNotIn(risky_term, amended)
            self.assertIn("纯黑无纹金属块", amended)
            self.assertIn("无纹样暗红蜡块", amended)
            self.assertIn("无抽屉无标签的素面封闭木柜", amended)

    def test_selected_tasks_add_motion_and_no_moon_repairs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompt = root / "base.txt"
            prompt.write_text("Taiping clinic with moonlight.")
            config = root / "config.json"
            config.write_text(json.dumps({"episode": "E99", "tasks": [
                {"task_key": "A", "prompt_file": str(prompt), "reference_images": ["a.png"], "metadata": {}},
                {"task_key": "B", "prompt_file": str(prompt), "reference_images": ["b.png"], "metadata": {}},
            ]}))
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": []}))
            output = root / "out.json"
            build_retry(config, receipt, output, root / "prompts", "R1", True, True, ["B"], True, True)
            task = json.loads(output.read_text())["tasks"][0]
            amended = Path(task["prompt_file"]).read_text()
            self.assertEqual(task["task_key"], "B-R1")
            self.assertIn("短冻结失败项定点修复", amended)
            self.assertIn("剧本时空硬约束", amended)
            self.assertEqual(task["reference_images"], [])


if __name__ == "__main__":
    unittest.main()
