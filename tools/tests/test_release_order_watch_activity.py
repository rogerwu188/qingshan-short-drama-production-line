import json
import tempfile
import unittest
from pathlib import Path

from tools.release_order_watch import release_schedule_hold, update_activity_snapshot


class ReleaseOrderWatchActivityTest(unittest.TestCase):
    def test_schedule_hold_blocks_exact_and_versioned_episode_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "work_queue.json"
            path.write_text(
                json.dumps(
                    {
                        "schedule_gate": {
                            "directive": "CL2X-349",
                            "release_blocked_episodes": ["E21", "E23_CURRENT_V12"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(release_schedule_hold("E21", path), (True, "CL2X-349"))
            self.assertEqual(release_schedule_hold("E23", path), (True, "CL2X-349"))
            self.assertEqual(release_schedule_hold("E24", path), (False, None))

    def test_watcher_counts_as_real_local_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "active.json"
            path.write_text(
                json.dumps(
                    {
                        "target": 3,
                        "active_count": 2,
                        "state": "UNDER_TARGET",
                        "parallel_lines": [
                            {"episode": "E21", "task_count": 1, "local_pid": 11},
                            {"episode": "E22", "task_count": 1, "local_pid": 12},
                            {"episode": "E23", "task_count": 0, "local_pid": None},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            update_activity_snapshot(
                {
                    "episode": "E23",
                    "status": "ACTIVE_ORDERED_RELEASE_WATCH",
                    "local_pid": 5148,
                    "receipt_path": str(Path(tmp) / "receipt.json"),
                },
                path,
            )
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["active_count"], 3)
            self.assertEqual(result["state"], "ACTIVE")
            self.assertEqual(result["parallel_lines"][2]["local_pid"], 5148)


if __name__ == "__main__":
    unittest.main()
