import argparse
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from tools.run_regression_ci import (
    FROZEN_THRESHOLDS,
    build_parser,
    evaluate_audio_bed_rows,
    resolve_audio_cut_times,
    static_hold_stats,
    source_video_fps,
    threshold_override_audit,
)


class RegressionCIThresholdProfileTests(unittest.TestCase):
    def parse(self, *extra):
        return build_parser().parse_args(
            ["--video", "/tmp/test.mp4", "--out", "/tmp/report.json", *extra]
        )

    def test_cli_defaults_match_frozen_profile(self):
        args = self.parse()
        self.assertIsNone(args.fps)
        for key, expected in FROZEN_THRESHOLDS.items():
            self.assertEqual(getattr(args, key), expected)

    def test_source_fps_is_read_instead_of_assuming_30(self):
        probe = CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="Stream #0:0: Video: h264, yuv420p, 720x1280, 24 fps, 24 tbr\n",
        )
        with patch("tools.run_regression_ci.run", return_value=probe):
            self.assertEqual(source_video_fps(Path("/tmp/source.mp4"), "/tmp/ffmpeg"), 24.0)

    def test_report_only_metrics_do_not_change_frozen_thresholds(self):
        args = self.parse(
            "--report-only-metric",
            "motion",
            "--report-only-metric",
            "asl",
            "--report-only-metric",
            "under1",
            "--report-only-metric",
            "nonfight_under08",
        )
        self.assertEqual(args.report_only_metric, ["motion", "asl", "under1", "nonfight_under08"])
        for key, expected in FROZEN_THRESHOLDS.items():
            self.assertEqual(getattr(args, key), expected)

    def test_relaxed_override_without_authorization_fails(self):
        args = self.parse("--episode-id", "E17", "--max-asl", "9.0")
        audit = threshold_override_audit(args, "")
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("threshold_override_missing_authorization_ref", audit["failures"])

    def test_verified_override_is_auditable(self):
        args = self.parse(
            "--episode-id",
            "E17",
            "--max-asl",
            "9.0",
            "--threshold-authorization-ref",
            "ROGER-901",
        )
        audit = threshold_override_audit(
            args,
            "# [ROGER-901] E17 threshold exception\n\n"
            "APPROVED_EXEMPTION: Roger approved E17 max ASL 9.0.\n",
        )
        self.assertEqual(audit["status"], "PASS_WITH_AUTHORIZED_OVERRIDE")
        self.assertEqual(audit["overrides"]["max_asl"]["actual"], 9.0)

    def test_audio_bed_rejects_digital_zero_and_large_jump(self):
        result = evaluate_audio_bed_rows(
            [
                {"shot_index": 1, "start_sec": 0.0, "end_sec": 2.0, "mean_volume_db": -24.0},
                {"shot_index": 2, "start_sec": 2.0, "end_sec": 4.0, "mean_volume_db": -120.0},
            ],
            [{"start_sec": 2.0, "end_sec": 4.0, "duration_sec": 2.0}],
            [],
            -90.0,
            12.0,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("audio_digital_zero_shot:2", result["failures"])
        self.assertTrue(any(item.startswith("audio_adjacent_rms_jump:1-2") for item in result["failures"]))

    def test_audio_bed_allows_declared_motivated_silence(self):
        result = evaluate_audio_bed_rows(
            [{"shot_index": 1, "start_sec": 0.0, "end_sec": 2.0, "mean_volume_db": -120.0}],
            [{"start_sec": 0.0, "end_sec": 2.0, "duration_sec": 2.0}],
            [{"start_sec": 0.0, "end_sec": 2.0, "reason": "designed silence"}],
            -90.0,
            12.0,
        )
        self.assertEqual(result["status"], "PASS")

    def test_declared_audio_boundaries_override_picture_only_cuts(self):
        cuts, source = resolve_audio_cut_times(
            {"boundaries": [4.0, 8.0, 8.0, 12.0]},
            [2.0, 4.0, 6.0, 8.0, 10.0],
            12.5,
        )
        self.assertEqual(cuts, [4.0, 8.0, 12.0])
        self.assertEqual(source, "declared_audio_edit_boundaries")

    def test_visual_cuts_remain_explicit_fallback(self):
        cuts, source = resolve_audio_cut_times(None, [2.0, 4.0], 6.0)
        self.assertEqual(cuts, [2.0, 4.0])
        self.assertEqual(source, "detected_visual_cuts_fallback")

    def test_no_dialogue_static_hold_over_four_seconds_fails(self):
        result = static_hold_stats(
            [1.0] * 150,
            30.0,
            [],
            5.0,
            {"segments": []},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["failures"][0].startswith("unmotivated_static_hold:"))

    def test_dialogue_or_visible_motion_prevents_static_hold_failure(self):
        with_dialogue = static_hold_stats(
            [1.0] * 150,
            30.0,
            [],
            5.0,
            {"segments": [{"start": 1.0, "end": 2.0, "text": "说话"}]},
        )
        with_motion = static_hold_stats(
            [2.0] * 150,
            30.0,
            [],
            5.0,
            {"segments": []},
        )
        self.assertEqual(with_dialogue["status"], "PASS")
        self.assertEqual(with_motion["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
