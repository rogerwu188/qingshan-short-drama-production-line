import unittest

from tools.media_boundary_acceptance import (
    DECISION_DOMAINS,
    evaluate_boundary_decision,
    is_motivated_foreground_occlusion,
)
from tools.model_generated_media_integrity_policy import evaluate_accepted_media_row


class MediaBoundaryAcceptanceTest(unittest.TestCase):
    def test_missing_real_media_decision_fails_closed(self):
        self.assertEqual(evaluate_boundary_decision(None), ["REAL_MEDIA_VISUAL_DECISION_MISSING"])

    def test_all_continuity_domains_are_required(self):
        decision = {domain: "PASS" for domain in DECISION_DOMAINS}
        decision["reviewer"] = "codex-visual-review"
        self.assertEqual(evaluate_boundary_decision(decision), [])
        decision["pose_and_blocking_continuity"] = "FAIL"
        self.assertTrue(any("pose_and_blocking_continuity" in item for item in evaluate_boundary_decision(decision)))

    def test_visual_decision_is_bound_to_exact_contact_sheet(self):
        decision = {domain: "PASS" for domain in DECISION_DOMAINS}
        decision.update({"reviewer": "codex-visual-review", "contact_sheet_sha256": "abc"})
        self.assertEqual(
            evaluate_boundary_decision(decision, expected_contact_sheet_sha256="abc"),
            [],
        )
        self.assertIn(
            "REAL_MEDIA_CONTACT_SHEET_SHA256_MISMATCH",
            evaluate_boundary_decision(decision, expected_contact_sheet_sha256="def"),
        )

    def test_only_single_tail_edge_foreground_occlusion_can_be_admitted(self):
        decision = {"foreground_occlusion_transition": "PASS_MOTIVATED"}
        self.assertTrue(is_motivated_foreground_occlusion(
            decision,
            frame_mean_luma=[30.0, 1.8, 37.0, 36.0],
            tail_motion_delta=29.0,
        ))
        self.assertFalse(is_motivated_foreground_occlusion(
            decision,
            frame_mean_luma=[1.8, 1.7, 37.0, 36.0],
            tail_motion_delta=29.0,
        ))
        self.assertFalse(is_motivated_foreground_occlusion(
            decision,
            frame_mean_luma=[30.0, 1.8, 37.0, 36.0],
            tail_motion_delta=0.2,
        ))
    def test_model_defect_semantic_postrepair_is_not_admissible(self):
        report = evaluate_accepted_media_row({
            "unit_id": "E46-VU-001",
            "media_path": "working_assets/e46/native_audio_sanitized/E46-VU-001.mp4",
            "postprocess_operations": ["ROOM_TONE_REPLACEMENT"],
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("POSTREPAIR" in row for row in report["failures"]))

    def test_unmodified_provider_media_remains_admissible(self):
        report = evaluate_accepted_media_row({
            "unit_id": "E46-VU-001",
            "media_path": "working_assets/e46/provider_raw/E46-VU-001.mp4",
            "transformations_applied": [],
        })
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["failures"], [])


if __name__ == "__main__":
    unittest.main()
