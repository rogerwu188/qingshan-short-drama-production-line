import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FailedOnlyBatchTests(unittest.TestCase):
    def test_retained_passes_accumulate_across_waves(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "config.json"
            receipt = tmp_path / "receipt.json"
            output = tmp_path / "output.json"
            config.write_text(json.dumps({
                "episode": "E28",
                "status": "READY_FOR_PARALLEL_SUBMIT",
                "retained_pass_task_keys": ["E28-DIA-002"],
                "tasks": [
                    {"task_key": "E28-DIA-003", "status": "READY_FOR_PARALLEL_SUBMIT"},
                    {"task_key": "E28-DIA-004", "status": "READY_FOR_PARALLEL_SUBMIT"},
                ],
            }), encoding="utf-8")
            receipt.write_text(json.dumps({
                "tasks": [
                    {"task_key": "E28-DIA-003", "state": "qa_pass"},
                    {"task_key": "E28-DIA-004", "state": "remote_failed_terminal"},
                ],
            }), encoding="utf-8")

            subprocess.run([
                sys.executable,
                str(ROOT / "tools/build_failed_only_batch.py"),
                "--base-config", str(config),
                "--receipt", str(receipt),
                "--output", str(output),
            ], check=True, capture_output=True, text=True)
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result["retained_pass_task_keys"], ["E28-DIA-002", "E28-DIA-003"])
        self.assertEqual([task["task_key"] for task in result["tasks"]], ["E28-DIA-004"])

    def test_can_select_only_submit_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = tmp_path / "config.json"
            receipt = tmp_path / "receipt.json"
            output = tmp_path / "output.json"
            config.write_text(json.dumps({
                "tasks": [
                    {"task_key": "submit", "status": "READY_TO_SUBMIT"},
                    {"task_key": "qa", "status": "READY_TO_SUBMIT"},
                ],
            }), encoding="utf-8")
            receipt.write_text(json.dumps({
                "tasks": [
                    {"task_key": "submit", "state": "submit_failed_terminal"},
                    {"task_key": "qa", "state": "qa_failed_terminal"},
                ],
            }), encoding="utf-8")
            subprocess.run([
                sys.executable,
                str(ROOT / "tools/build_failed_only_batch.py"),
                "--base-config", str(config),
                "--receipt", str(receipt),
                "--output", str(output),
                "--states", "submit_failed_terminal",
            ], check=True, capture_output=True, text=True)
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual([task["task_key"] for task in result["tasks"]], ["submit"])
        self.assertEqual(result["retry_states"], ["submit_failed_terminal"])


if __name__ == "__main__":
    unittest.main()
