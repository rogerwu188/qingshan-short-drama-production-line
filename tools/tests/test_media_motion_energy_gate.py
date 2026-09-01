import unittest

from tools.media_motion_energy_gate import evaluate_energy_series


class MediaMotionEnergyGateTest(unittest.TestCase):
    def test_absolute_score_is_advisory_until_calibrated(self) -> None:
        advisory = evaluate_energy_series(
            [1, 1, 1, 2.4], unit_class="COMBAT_IMPULSE", no_cut=True, source_id="VU1"
        )
        self.assertEqual(advisory["status"], "ADVISORY")
        self.assertEqual(advisory["retry_policy"], "NONE")
        failed = evaluate_energy_series(
            [1, 1, 1, 2.4], unit_class="COMBAT_IMPULSE", no_cut=True,
            source_id="VU1", calibrated_fail_floor=2.5,
        )
        self.assertEqual(failed["status"], "FAIL")
        self.assertEqual(failed["retry_policy"], "REDESIGN_PROMPT_NEW_SHA_NO_SAME_PROMPT_TWEAK_RETRY")

    def test_ab_requires_1_8x_improvement_and_cut_is_excluded(self) -> None:
        failed = evaluate_energy_series(
            [1, 1, 1, 3.2], unit_class="COMBAT_IMPULSE", no_cut=True,
            source_id="VU1", previous_ratio=2.0,
        )
        self.assertEqual(failed["status"], "FAIL")
        excluded = evaluate_energy_series(
            [0, 100], unit_class="COMBAT_IMPULSE", no_cut=False, source_id="VU1"
        )
        self.assertEqual(excluded["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
