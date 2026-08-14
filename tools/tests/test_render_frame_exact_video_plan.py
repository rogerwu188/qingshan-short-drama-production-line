import unittest

from tools.render_frame_exact_video_plan import apply_transform_overrides, build_frame_filter


class FrameExactVideoPlanFilterTests(unittest.TestCase):
    def test_default_filter_has_no_transform_record(self):
        value, transforms = build_frame_filter(
            {"source_id": "A"},
            {"start_frame": 5, "end_frame": 10},
            24,
        )
        self.assertIn("select=between(n\\,5\\,9)", value)
        self.assertIn("force_original_aspect_ratio=decrease", value)
        self.assertEqual(transforms, {})

    def test_crop_and_brightness_are_applied_and_recorded(self):
        value, transforms = build_frame_filter(
            {
                "source_id": "A",
                "crop_bottom_fraction": 0.32,
                "eq_brightness": -0.105,
            },
            {"start_frame": 5, "end_frame": 10},
            24,
        )
        self.assertIn("crop=iw:ih*(1-0.3200):0:0", value)
        self.assertIn("force_original_aspect_ratio=increase", value)
        self.assertIn("eq=brightness=-0.1050:contrast=1.0", value)
        self.assertEqual(
            transforms,
            {"crop_bottom_fraction": 0.32, "eq_brightness": -0.105},
        )

    def test_invalid_transform_values_are_rejected(self):
        with self.assertRaises(ValueError):
            build_frame_filter(
                {"source_id": "A", "crop_bottom_fraction": 0.5},
                {"start_frame": 0, "end_frame": 1},
                24,
            )
        with self.assertRaises(ValueError):
            build_frame_filter(
                {"source_id": "A", "eq_brightness": 0.36},
                {"start_frame": 0, "end_frame": 1},
                24,
            )
        with self.assertRaises(ValueError):
            build_frame_filter(
                {"source_id": "A", "day_for_night_strength": 1.1},
                {"start_frame": 0, "end_frame": 1},
                24,
            )

    def test_day_for_night_is_applied_and_recorded(self):
        value, transforms = build_frame_filter(
            {"source_id": "A", "day_for_night_strength": 0.75},
            {"start_frame": 0, "end_frame": 24},
            24,
        )
        self.assertIn("eq=brightness=-0.1200:contrast=1.0600:saturation=0.7750", value)
        self.assertIn("colorbalance=bs=0.1050:bm=0.0675:bh=0.0300", value)
        self.assertEqual(transforms, {"day_for_night_strength": 0.75})

    def test_transform_overrides_require_known_sources_and_fields(self):
        segments = [{"source_id": "A", "eq_brightness": 0.1}]
        result = apply_transform_overrides(segments, {"A": {"day_for_night_strength": 0.8}})
        self.assertEqual(result[0]["eq_brightness"], 0.1)
        self.assertEqual(result[0]["day_for_night_strength"], 0.8)
        self.assertNotIn("day_for_night_strength", segments[0])
        with self.assertRaises(ValueError):
            apply_transform_overrides(segments, {"B": {"day_for_night_strength": 0.8}})
        with self.assertRaises(ValueError):
            apply_transform_overrides(segments, {"A": {"speed": 0.5}})


if __name__ == "__main__":
    unittest.main()
