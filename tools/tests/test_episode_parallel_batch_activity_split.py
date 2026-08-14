import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.episode_parallel_batch_supervisor import split_receipt_by_episode


class ActivitySplitTests(unittest.TestCase):
    def test_cross_episode_receipt_splits_remote_ids(self):
        receipt = {
            "episode": "E26_E27",
            "local_pid": 123,
            "tasks": [
                {"task_key": "E26-B06-P1-R1", "state": "remote_running", "task_id": "e26-a"},
                {"task_key": "E26-B06-P2-R1", "state": "qa_pass", "task_id": "e26-b"},
                {"task_key": "E27-B02-P1-R1", "state": "remote_running", "task_id": "e27-a"},
            ],
        }
        views = split_receipt_by_episode(receipt)
        self.assertEqual([view["episode"] for view in views], ["E26", "E27"])
        self.assertEqual(views[0]["active_task_ids"], ["e26-a"])
        self.assertEqual(views[1]["active_task_ids"], ["e27-a"])

    def test_single_episode_receipt_is_unchanged(self):
        receipt = {
            "episode": "E28",
            "tasks": [{"task_key": "E28-DIA-001", "state": "remote_running", "task_id": "x"}],
        }
        self.assertEqual(split_receipt_by_episode(receipt), [receipt])


if __name__ == "__main__":
    unittest.main()
