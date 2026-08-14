import unittest

from tools.final_video_ocr_audit import choose_media_duration, resolve_sampling_policy


class FinalVideoOcrAuditTests(unittest.TestCase):
    def test_container_duration_prevents_tail_coverage_gap(self):
        self.assertEqual(choose_media_duration(5.06195, 5.041667), 5.06195)

    def test_frame_duration_is_fallback(self):
        self.assertEqual(choose_media_duration(None, 4.0), 4.0)

    def test_source_mode_scans_full_duration_at_half_second_or_better(self):
        interval, exclusion, mode = resolve_sampling_policy(
            interval=2.0,
            exclude_final_seconds=4.0,
            source_mode=True,
        )
        self.assertEqual(interval, 0.5)
        self.assertEqual(exclusion, 0.0)
        self.assertEqual(mode, "SOURCE_FULL_DURATION")

    def test_final_mode_preserves_requested_end_card_exclusion(self):
        interval, exclusion, mode = resolve_sampling_policy(
            interval=1.0,
            exclude_final_seconds=4.0,
            source_mode=False,
        )
        self.assertEqual((interval, exclusion), (1.0, 4.0))
        self.assertEqual(mode, "FINAL_AUDIENCE_FACING")


if __name__ == "__main__":
    unittest.main()
