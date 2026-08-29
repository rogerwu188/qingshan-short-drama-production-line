import unittest

from tools.submit_giggle_task_manifest import validate_corrected_pipeline_reports


class SubmitCorrectedPipelineGateTests(unittest.TestCase):
    def test_e28_plus_direct_submit_requires_all_corrected_reports(self):
        failures = validate_corrected_pipeline_reports(
            {"episode": "E28"},
            [{"status": "READY_TO_SUBMIT", "source_id": "U01"}],
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:dramatic_quality_report_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:mechanical_default_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:anchor_count_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:video_unit_grouping_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:common_sense_causality_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:action_shot_design_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_REPORT_MISSING:period_lock_plan_ref",
            failures,
        )
        self.assertIn(
            "FAIL_CORRECTED_PIPELINE_DIRECT_SUBMIT_FORBIDDEN:USE_EPISODE_PARALLEL_BATCH_SUPERVISOR",
            failures,
        )

    def test_e27_is_outside_corrected_pipeline_activation(self):
        self.assertEqual(
            validate_corrected_pipeline_reports(
                {"episode": "E27"},
                [{"status": "READY_TO_SUBMIT", "source_id": "U01"}],
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
