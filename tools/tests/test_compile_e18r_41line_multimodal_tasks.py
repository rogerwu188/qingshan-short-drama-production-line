import tempfile
import unittest
from pathlib import Path

from tools.compile_e18r_41line_multimodal_tasks import compile_tasks


class CompileE18R41LineTasksTests(unittest.TestCase):
    def fixtures(self):
        lines = []
        beats = []
        for beat_index in range(1, 7):
            beat_id = f"B{beat_index:02d}"
            dialogue_ids = []
            count = 7 if beat_index != 3 else 6
            if beat_index == 4:
                count = 8
            if beat_index == 5:
                count = 6
            for _ in range(count):
                special_ids = ["DIA-A7", "DIA-A9", "DIA-A11"]
                dia_id = special_ids[len(lines)] if len(lines) < len(special_ids) else f"DIA-{len(lines) + 1:03d}"
                dialogue_ids.append(dia_id)
                lines.append({"dia_id": dia_id, "speaker": "陈迹", "text": "测试台词", "voice_asset_id": "voice"})
            beats.append({"beat_id": beat_id, "name": beat_id, "dialogue_ids": dialogue_ids})
        self.assertEqual(len(lines), 41)
        return {"lines": lines}, {"beats": beats, "silence_windows": [{"duration_seconds": 12}]}

    def test_compiles_41_tasks_and_only_b01_is_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            tasks, metrics = compile_tasks(*self.fixtures(), Path(temp))
        self.assertEqual(len(tasks), 41)
        self.assertEqual(metrics["pilot_task_count"], 7)
        self.assertTrue(all(row["status"] == "READY_TO_SUBMIT" for row in tasks[:7]))
        self.assertTrue(all(row["status"] != "READY_TO_SUBMIT" for row in tasks[7:]))

    def test_coverage_mismatch_fails(self):
        binding, coverage = self.fixtures()
        coverage["beats"][0]["dialogue_ids"].pop()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                compile_tasks(binding, coverage, Path(temp))


if __name__ == "__main__":
    unittest.main()
