import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.refresh_production_work_queue as refresh
from tools.refresh_production_work_queue import episode_process_map, is_release_active_status


class ReleaseActivityTests(unittest.TestCase):
    def test_platform_review_is_real_release_activity(self):
        self.assertTrue(is_release_active_status("DOUYIN_PLATFORM_REVIEW_PENDING"))
        self.assertTrue(is_release_active_status("PLATFORM_REVIEWING"))

    def test_completed_local_batch_is_not_release_activity(self):
        self.assertFalse(is_release_active_status("BATCH_COMPLETE"))

    def test_agentcut_render_batch_maps_one_pid_to_each_episode(self):
        processes = episode_process_map(
            " 34306 agentcut render-batch configs/e26_agentcut_v6.json configs/e27_agentcut_v7.json\n"
            " 33690 python tools/episode_parallel_batch_supervisor.py --config configs/E28_video.json\n"
            " 33701 .ai_review_env/bin/qingshan-review review-many qa/e29_video_review.json\n"
            " 99999 python tools/refresh_production_work_queue.py\n"
        )
        self.assertEqual(processes, {"E26": [34306], "E27": [34306], "E28": [33690], "E29": [33701]})


class SafeRefreshTests(unittest.TestCase):
    def projection(self, episode="E40"):
        return {
            "schema": "qingshan.producer.work_queue.v2",
            "real_active_handle_count": 0,
            "lines": {"SLOT_1": {"episode": episode, "real_activity": False}},
            "released_auto_dequeue_assertion": {"excluded_episodes": []},
        }

    def test_help_exits_before_projection_or_write(self):
        with mock.patch.object(refresh, "build_projection", side_effect=AssertionError("must not run")):
            with self.assertRaises(SystemExit) as raised:
                refresh.main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_default_is_dry_run_and_does_not_change_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "work_queue.json"
            original = b'{"active_episode":"E40","sentinel":1}\n'
            target.write_bytes(original)
            with mock.patch.object(refresh, "OUT", target), mock.patch.object(
                refresh, "build_projection", return_value=self.projection()
            ):
                self.assertEqual(refresh.main([]), 0)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse((target.parent / ".work_queue.backups").exists())

    def test_write_requires_expected_sha(self):
        with self.assertRaisesRegex(RuntimeError, "requires"):
            refresh.main(["--write"])

    def test_expected_sha_without_write_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "only with"):
            refresh.main(["--expected-current-sha256", "0" * 64])

    def test_cas_mismatch_creates_no_backup_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "work_queue.json"
            original = b'{"active_episode":"E40"}\n'
            target.write_bytes(original)
            with mock.patch.object(refresh, "OUT", target):
                with self.assertRaisesRegex(RuntimeError, "CAS mismatch"):
                    refresh._atomic_cas_write(self.projection(), "0" * 64)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse((target.parent / ".work_queue.backups").exists())

    def test_e40_rejects_projection_that_omits_e40(self):
        current = {"active_episode": "E40", "status": "KEEP", "e40_credits": {"net": 1}}
        with self.assertRaisesRegex(RuntimeError, "omits active E40"):
            refresh.merge_runtime_projection(current, self.projection("E37"))

    def test_atomic_write_backs_up_and_preserves_e40_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "work_queue.json"
            current = {
                "active_episode": "E40",
                "status": "KEEP",
                "mode": "KEEP_MODE",
                "blocked_by": "KEEP_BLOCKER",
                "next_action": "KEEP_NEXT",
                "e40_credits": {"gross_pay": 10, "refund": 2, "net": 8, "cap": 100},
                "latest_e40_asset": {"sha256": "abc"},
            }
            original = (json.dumps(current, indent=2) + "\n").encode()
            target.write_bytes(original)
            expected = hashlib.sha256(original).hexdigest()
            with mock.patch.object(refresh, "OUT", target):
                new_sha, backup = refresh._atomic_cas_write(self.projection(), expected)
            self.assertEqual(Path(backup).read_bytes(), original)
            result = json.loads(target.read_text())
            for key in ("active_episode", "status", "mode", "blocked_by", "next_action", "e40_credits", "latest_e40_asset"):
                self.assertEqual(result[key], current[key])
            self.assertEqual(result["latest_runtime_refresh"]["projection"]["lines"]["SLOT_1"]["episode"], "E40")
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), new_sha)


if __name__ == "__main__":
    unittest.main()
