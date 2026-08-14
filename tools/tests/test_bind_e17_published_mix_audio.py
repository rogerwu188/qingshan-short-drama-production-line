import unittest

from tools.bind_e17_published_mix_audio import (
    crossfade_trim_points,
    multi_cut_filter,
    normalized_cuts,
    parse_cut,
)


class CrossfadeTrimPointsTest(unittest.TestCase):
    def test_preserves_approved_cut_duration(self):
        left_end, right_start, effective_removed = crossfade_trim_points(
            9.725, 15.1, 0.08
        )
        self.assertAlmostEqual(left_end, 9.765)
        self.assertAlmostEqual(right_start, 15.06)
        self.assertAlmostEqual(effective_removed, 5.375)

    def test_rejects_invalid_interval(self):
        with self.assertRaises(ValueError):
            crossfade_trim_points(15.1, 9.725, 0.08)

    def test_rejects_crossfade_longer_than_cut(self):
        with self.assertRaises(ValueError):
            crossfade_trim_points(9.725, 15.1, 5.375)

    def test_two_cuts_keep_output_seams_aligned(self):
        cuts = normalized_cuts([(9.725, 15.1), (103.5, 109.2916666667)], 0.08)
        self.assertAlmostEqual(cuts[0]["output_seam_seconds"], 9.725)
        self.assertAlmostEqual(cuts[1]["output_seam_seconds"], 98.125)
        self.assertAlmostEqual(sum(row["effective_removed"] for row in cuts), 11.1666666667)

    def test_two_cut_filter_maps_final_audio(self):
        cuts = normalized_cuts([(9.725, 15.1), (103.5, 109.2916666667)], 0.08)
        value = multi_cut_filter(cuts, 0.08, 159.4583333333)
        self.assertIn("[1:a:0]atrim=start=15.060000:end=103.540000", value)
        self.assertIn("[xf1][a2]acrossfade", value)
        self.assertIn("[aout]", value)

    def test_parse_cut(self):
        self.assertEqual(parse_cut("103.5:109.2916667"), (103.5, 109.2916667))

    def test_rejects_overlapping_cuts(self):
        with self.assertRaises(ValueError):
            normalized_cuts([(9.0, 15.0), (14.0, 16.0)], 0.08)


if __name__ == "__main__":
    unittest.main()
