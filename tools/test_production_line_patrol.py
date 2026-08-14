#!/usr/bin/env python3

import unittest

from tools.production_line_patrol import episode_summary, queue_next_safe_action


class ProductionLinePatrolTest(unittest.TestCase):
    def test_release_gate_overrides_stale_package_manifest(self):
        manifest = {"status": "NOT_RELEASED", "final_video": "/tmp/e18.mp4"}
        release = {
            "status": "YOUTUBE_PUBLISHED_PUBLIC__DOUYIN_PUBLISHED_PUBLIC",
            "release_gate": "PASS",
            "final_video": "/tmp/e18.mp4",
            "youtube": {"status": "PUBLISHED_PUBLIC"},
            "douyin": {"status": "PUBLISHED_PUBLIC"},
            "blocker": "NONE",
        }

        summary = episode_summary(manifest, release)

        self.assertEqual(summary["status"], release["status"])
        self.assertEqual(summary["blocker"], "NONE")

    def test_all_public_queue_moves_to_monitoring(self):
        queue = {
            "queue": [
                {"status": "PUBLISHED_PUBLIC"},
                {"status": "YOUTUBE_PUBLISHED_PUBLIC__DOUYIN_PUBLISHED_PUBLIC"},
            ]
        }

        self.assertIn("post-publish monitoring", queue_next_safe_action(queue))


if __name__ == "__main__":
    unittest.main()
