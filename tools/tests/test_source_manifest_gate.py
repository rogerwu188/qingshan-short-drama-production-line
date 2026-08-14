import unittest

from tools.run_regression_ci import (
    manifest_shot_reconciliation,
    nonfight_short_shot_stats,
    source_manifest_stats,
)


class SourceManifestGateTests(unittest.TestCase):
    approval_audit = """## [CL2X-900] E20 shot reconciliation exemption approved

APPROVED_EXEMPTION: StoryClaw 批准 E20 一处叠化切点误检豁免。
"""

    def segment(self, **overrides):
        row = {
            "source_id": "SRC-01",
            "source_sequence_id": "SEQ-01",
            "beat_id": "BEAT-01",
            "source_duration_sec": 12.0,
            "source_in_sec": 1.0,
            "source_out_sec": 6.0,
            "declared_dramatic_reason": "evidence reveal",
            "motivated_flashback": False,
        }
        row.update(overrides)
        return row

    def test_required_manifest_rejects_missing_fields(self):
        result = source_manifest_stats({"segments": [{"source_id": "SRC-01"}]}, required=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["failures"][0].startswith("coverage_segment_missing_fields"))

    def test_untrimmed_long_source_requires_reason(self):
        row = self.segment(source_in_sec=0.0, source_out_sec=12.0, declared_dramatic_reason="")
        result = source_manifest_stats({"segments": [row]}, required=True)
        self.assertIn("untrimmed_source_missing_dramatic_reason:SRC-01:1.000", result["failures"])

    def test_cross_beat_reuse_requires_motivated_flashback(self):
        rows = [self.segment(), self.segment(beat_id="BEAT-02")]
        result = source_manifest_stats({"segments": rows}, required=True)
        self.assertTrue(any(item.startswith("cross_beat_source_reuse_unmotivated") for item in result["failures"]))

    def test_declared_flashback_cross_beat_reuse_passes(self):
        rows = [
            self.segment(motivated_flashback=True),
            self.segment(beat_id="BEAT-02", motivated_flashback=True),
        ]
        result = source_manifest_stats({"segments": rows}, required=True)
        self.assertEqual(result["status"], "PASS")

    def test_fight_interval_is_excluded_from_short_shot_ratio(self):
        result = nonfight_short_shot_stats(
            [0.5, 1.0, 2.0],
            3.0,
            {"fight_intervals": [{"start_sec": 0.0, "end_sec": 1.0}]},
        )
        self.assertEqual(result["nonfight_shot_count"], 2)
        self.assertEqual(result["short_shot_count"], 0)

    def test_manifest_shot_count_matches_detected_shots(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0], 3.0, {"segments": [{}, {}, {}]}, required=True
        )
        self.assertEqual(result["status"], "PASS")

    def test_manifest_shot_count_mismatch_fails(self):
        result = manifest_shot_reconciliation([1.0, 2.0], 3.0, {"segments": [{}, {}]}, required=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("manifest_shot_count_mismatch:detected=3:manifest=2", result["failures"])

    def test_manifest_shot_count_exemption_requires_reason_and_approver(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0],
            3.0,
            {
                "episode_id": "E20",
                "segments": [{}, {}],
                "shot_reconciliation_exemption": {
                    "reason": "A dissolve is detected as an extra cut.",
                    "approved_by": "StoryClaw",
                    "approval_ref": "CL2X-900",
                },
            },
            required=True,
            approval_audit_text=self.approval_audit,
        )
        self.assertEqual(result["status"], "PASS_WITH_EXEMPTION")
        self.assertFalse(result["failures"])

    def test_manifest_shot_count_exemption_rejects_self_approval(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0],
            3.0,
            {
                "episode_id": "E20",
                "segments": [{}, {}],
                "shot_reconciliation_exemption": {
                    "reason": "A dissolve is detected as an extra cut.",
                    "approved_by": "codex",
                    "approval_ref": "CL2X-900",
                },
            },
            required=True,
            approval_audit_text=self.approval_audit,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("shot_reconciliation_exemption_invalid_approver:codex", result["failures"])

    def test_manifest_shot_count_exemption_rejects_large_gap(self):
        result = manifest_shot_reconciliation(
            list(range(1, 20)),
            20.0,
            {
                "episode_id": "E20",
                "segments": [{} for _ in range(15)],
                "shot_reconciliation_exemption": {
                    "reason": "Several dissolves were detected as cuts.",
                    "approved_by": "Roger",
                    "approval_ref": "CL2X-900",
                },
            },
            required=True,
            approval_audit_text=self.approval_audit,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("shot_reconciliation_exemption_scope_exceeded:difference=5:max=1", result["failures"])

    def test_manifest_shot_count_exemption_rejects_unverified_reference(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0],
            3.0,
            {
                "episode_id": "E20",
                "segments": [{}, {}],
                "shot_reconciliation_exemption": {
                    "reason": "A dissolve is detected as an extra cut.",
                    "approved_by": "StoryClaw",
                    "approval_ref": "CL2X-901",
                },
            },
            required=True,
            approval_audit_text=self.approval_audit,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("shot_reconciliation_exemption_unverified_ref:CL2X-901:E20", result["failures"])

    def test_manifest_shot_count_exemption_accepts_single_hash_mailbox_heading(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0],
            3.0,
            {
                "episode_id": "E20",
                "segments": [{}, {}],
                "shot_reconciliation_exemption": {
                    "reason": "A dissolve is detected as an extra cut.",
                    "approved_by": "Roger",
                    "approval_ref": "ROGER-900",
                },
            },
            required=True,
            approval_audit_text="# [ROGER-900] E20 approval\n\n批准豁免: E20 叠化误检。\n",
        )
        self.assertEqual(result["status"], "PASS_WITH_EXEMPTION")

    def test_manifest_shot_count_exemption_rejects_negated_free_text(self):
        result = manifest_shot_reconciliation(
            [1.0, 2.0],
            3.0,
            {
                "episode_id": "E20",
                "segments": [{}, {}],
                "shot_reconciliation_exemption": {
                    "reason": "A dissolve is detected as an extra cut.",
                    "approved_by": "StoryClaw",
                    "approval_ref": "CL2X-902",
                },
            },
            required=True,
            approval_audit_text="## [CL2X-902] E20 exemption rejected\n\nStoryClaw 不批准 E20 豁免。\n",
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("shot_reconciliation_exemption_unverified_ref:CL2X-902:E20", result["failures"])


if __name__ == "__main__":
    unittest.main()
