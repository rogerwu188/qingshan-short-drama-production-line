import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/build_episode_failed_only_retry.py"


class FailedOnlyRetryTests(unittest.TestCase):
    def test_extracts_only_terminal_failures(self):
        config = {"episode": "E26", "tasks": [{"task_key": "A"}, {"task_key": "B"}]}
        receipt = {"tasks": [{"task_key": "A", "status": "remote_running"}, {"task_key": "B", "status": "submit_failed_terminal"}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); source = tmp / "config.json"; status = tmp / "receipt.json"; out = tmp / "retry.json"
            source.write_text(json.dumps(config)); status.write_text(json.dumps(receipt))
            proc = subprocess.run(["python3", str(TOOL), "--config", str(source), "--receipt", str(status), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            retry = json.loads(out.read_text())
            self.assertEqual(retry["concurrency"], 1)
            self.assertEqual(retry["tasks"][0]["metadata"]["retry_of_task_key"], "B")

    def test_excludes_failures_already_in_an_active_retry(self):
        config = {"episode": "E26", "tasks": [{"task_key": "A"}, {"task_key": "B"}]}
        receipt = {"tasks": [{"task_key": "A", "status": "qa_failed_terminal"}, {"task_key": "B", "status": "qa_failed_terminal"}]}
        active_retry = {"tasks": [{"task_key": "A-R1", "metadata": {"retry_of_task_key": "A"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); source = tmp / "config.json"; status = tmp / "receipt.json"; active = tmp / "active.json"; out = tmp / "retry.json"
            source.write_text(json.dumps(config)); status.write_text(json.dumps(receipt)); active.write_text(json.dumps(active_retry))
            proc = subprocess.run(["python3", str(TOOL), "--config", str(source), "--receipt", str(status), "--exclude-receipt", str(active), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            retry = json.loads(out.read_text())
            self.assertEqual([task["metadata"]["retry_of_task_key"] for task in retry["tasks"]], ["B"])


if __name__ == "__main__":
    unittest.main()
