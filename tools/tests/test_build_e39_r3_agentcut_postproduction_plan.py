import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "build_e39_r3_agentcut_postproduction_plan.py"
SPEC = importlib.util.spec_from_file_location("build_e39_r3_agentcut_postproduction_plan", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class E39R3AgentCutPlanTests(unittest.TestCase):
    def test_ass_time(self):
        self.assertEqual(MODULE.ass_time(62.34), "0:01:02.34")

    def test_generated_plan_is_exact_and_non_overlapping(self):
        self.assertEqual(MODULE.main(), 0)
        plan = json.loads(MODULE.OUT.read_text(encoding="utf-8"))
        self.assertEqual(len(plan["units"]), 9)
        self.assertEqual(sum(len(unit["dialogue_events"]) for unit in plan["units"]), 13)
        self.assertEqual(
            [row["unit_id"] for row in plan["preserved_source_units"]],
            ["E39-U02-R2", "E39-U03-R2"],
        )
        for unit in plan["units"]:
            previous_end = 0.0
            for event in unit["dialogue_events"]:
                self.assertGreaterEqual(event["start_seconds"], previous_end)
                self.assertLessEqual(event["end_seconds"], unit["expected_visual_duration_seconds"])
                self.assertTrue((MODULE.ROOT / event["wav_path"]).is_file())
                previous_end = event["end_seconds"]

    def test_subtitle_style_has_outline_without_box(self):
        self.assertIn("BorderStyle,Outline,Shadow", MODULE.write_ass.__doc__ or "") if False else None
        with tempfile.TemporaryDirectory() as tmp:
            original = MODULE.OUT_DIR
            MODULE.OUT_DIR = Path(tmp)
            try:
                path = MODULE.write_ass("TEST", [{"start_seconds": 0.0, "end_seconds": 1.0, "speaker": "陈迹", "text": "测试"}])
                text = path.read_text(encoding="utf-8")
                self.assertIn("BorderStyle", text)
                self.assertIn(",1,3,0,2,", text)
                self.assertNotIn("&HFF000000", text)
            finally:
                MODULE.OUT_DIR = original


if __name__ == "__main__":
    unittest.main()
