import unittest

from tools.frame_cadence_audit import (
    cadence_signatures,
    evaluate_cadence,
    periodic_duplicate_stats,
    verify_periodic_duplicates_with_mpdecimate,
)


class FrameCadenceAuditTests(unittest.TestCase):
    def test_matching_source_and_output_fps_pass(self):
        result = evaluate_cadence(
            24.0,
            [{"source_id": "A", "path": "/tmp/a.mp4", "fps": 24.0}],
            {"frozen_runs": [], "freeze_ratio": 0.0},
        )
        self.assertEqual(result["status"], "PASS")

    def test_cfr_conversion_is_rejected(self):
        result = evaluate_cadence(
            30.0,
            [{"source_id": "A", "path": "/tmp/a.mp4", "fps": 24.0}],
            {"frozen_runs": [], "freeze_ratio": 0.0},
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["failures"][0].startswith("output_source_fps_mismatch:"))

    def test_declared_static_source_fps_mismatch_is_exempted(self):
        result = evaluate_cadence(
            24.0,
            [
                {
                    "source_id": "NALU_tail",
                    "path": "/tmp/tail.mp4",
                    "fps": 25.0,
                    "cadence_exempt_reason": "AUTHORIZED_STATIC_END_CARD",
                }
            ],
            {"frozen_runs": [], "freeze_ratio": 0.0},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["mismatched_source_count"], 0)
        self.assertEqual(result["exempted_mismatch_count"], 1)

    def test_half_second_freeze_is_rejected(self):
        result = evaluate_cadence(
            24.0,
            [],
            {
                "frozen_runs": [{"start_seconds": 3.0, "duration_seconds": 0.5}],
                "freeze_ratio": 0.05,
            },
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("short_freeze_detected:3.000+0.500", result["failures"])

    def test_declared_static_tail_is_allowed(self):
        result = evaluate_cadence(
            24.0,
            [],
            {
                "frozen_runs": [{"start_seconds": 10.0, "duration_seconds": 2.0}],
                "freeze_ratio": 0.1,
            },
            motivated_static_ranges=[
                {"start_seconds": 9.5, "end_seconds": 12.5, "reason": "NALU tail"}
            ],
        )
        self.assertEqual(result["status"], "PASS")

    def test_periodic_near_duplicates_are_rejected(self):
        values = [4.0] * 80
        for frame in (11, 15, 19, 23, 27, 31):
            values[frame - 1] = 0.3
        periodic = periodic_duplicate_stats(values, 24.0)
        periodic = verify_periodic_duplicates_with_mpdecimate(
            periodic, [11, 15, 19, 23, 27, 31]
        )
        result = evaluate_cadence(
            24.0,
            [],
            {"frozen_runs": [], "freeze_ratio": 0.0},
            periodic_duplicates=periodic,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(periodic["periodic_chain_count"], 1)
        self.assertTrue(
            result["failures"][0].startswith("periodic_duplicate_cadence_detected:")
        )

    def test_sparse_near_duplicates_do_not_form_periodic_chain(self):
        values = [4.0] * 80
        for frame in (11, 21, 42, 70):
            values[frame - 1] = 0.3
        periodic = periodic_duplicate_stats(values, 24.0)
        self.assertEqual(periodic["periodic_chain_count"], 0)

    def test_yavg_periodic_candidate_without_mpdecimate_confirmation_passes(self):
        values = [4.0] * 80
        for frame in (11, 15, 19, 23, 27, 31):
            values[frame - 1] = 0.3
        periodic = verify_periodic_duplicates_with_mpdecimate(
            periodic_duplicate_stats(values, 24.0), [15, 23]
        )
        result = evaluate_cadence(
            24.0,
            [],
            {"frozen_runs": [], "freeze_ratio": 0.0},
            periodic_duplicates=periodic,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(periodic["rejected_yavg_candidates"]), 1)

    def test_interval_four_chain_reports_suspected_18_to_24_signature(self):
        periodic = periodic_duplicate_stats(
            [0.3 if index in {10, 14, 18, 22, 26, 30} else 4.0 for index in range(80)],
            24.0,
        )
        periodic = verify_periodic_duplicates_with_mpdecimate(
            periodic, [11, 15, 19, 23, 27, 31]
        )
        signatures = cadence_signatures(periodic)
        self.assertEqual(signatures[0]["signature"], "SUSPECTED_18_TO_24_FRAME_DUPLICATION")
        self.assertEqual(signatures[0]["causal_scope"], "GENERATION_OR_DELIVERY_PATH_UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
