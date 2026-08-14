import unittest

from tools.final_package_blocker_gate import evaluate


def required_rows():
    return [
        {
            "id": "DIALOGUE_AUDIO_AUDIBILITY",
            "status": "RESOLVED",
            "evidence": "qa/dialogue_audio.json",
            "evidence_status": "PASS",
        },
        {
            "id": "SPEAKER_IDENTITY_AND_VOICE_BINDING",
            "status": "RESOLVED",
            "evidence": "qa/speaker_identity_voice.json",
            "evidence_status": "PASS",
        },
        {
            "id": "SUBTITLE_BURNIN",
            "status": "RESOLVED",
            "evidence": "qa/subtitle.json",
            "evidence_status": "PASS",
        },
        {
            "id": "NALU_MOTION_OUTRO",
            "status": "RESOLVED",
            "evidence": "qa/outro.json",
            "evidence_status": "PASS",
        },
        {
            "id": "AUDIENCE_SCORE_PRE_RELEASE",
            "status": "RESOLVED",
            "evidence": "qa/audience.json",
            "evidence_status": "PASS",
        },
    ]


class FinalPackageBlockerGateTests(unittest.TestCase):
    def test_unresolved_blocker_fails(self):
        result = evaluate(
            {"blockers": required_rows() + [{"id": "MIX", "status": "PENDING"}]}
        )
        self.assertEqual(result["status"], "FAIL")

    def test_resolved_and_authorized_waiver_pass(self):
        result = evaluate(
            {
                "blockers": required_rows() + [
                    {"id": "MIX", "status": "RESOLVED"},
                    {"id": "EXCEPTION", "status": "WAIVED", "approval_ref": "ROGER-901"},
                ]
            }
        )
        self.assertEqual(result["status"], "PASS")

    def test_waiver_without_trace_fails(self):
        result = evaluate(
            {"blockers": required_rows() + [{"id": "MIX", "status": "WAIVED"}]}
        )
        self.assertEqual(result["status"], "FAIL")

    def test_missing_subtitle_and_outro_rows_fail(self):
        result = evaluate({"blockers": [{"id": "MIX", "status": "RESOLVED"}]})
        self.assertIn(
            "required_final_package_blocker_missing:SUBTITLE_BURNIN",
            result["failures"],
        )
        self.assertIn(
            "required_final_package_blocker_missing:NALU_MOTION_OUTRO",
            result["failures"],
        )
        self.assertIn(
            "required_final_package_blocker_missing:DIALOGUE_AUDIO_AUDIBILITY",
            result["failures"],
        )
        self.assertIn(
            "required_final_package_blocker_missing:SPEAKER_IDENTITY_AND_VOICE_BINDING",
            result["failures"],
        )

    def test_required_row_needs_pass_evidence(self):
        rows = required_rows()
        next(row for row in rows if row["id"] == "SUBTITLE_BURNIN")[
            "evidence_status"
        ] = "FAIL"
        result = evaluate({"blockers": rows})
        self.assertIn(
            "required_final_package_evidence_not_pass:SUBTITLE_BURNIN:FAIL",
            result["failures"],
        )

    def test_audience_gate_cannot_be_waived(self):
        rows = required_rows()
        audience = next(row for row in rows if row["id"] == "AUDIENCE_SCORE_PRE_RELEASE")
        audience.update({"status": "WAIVED", "approval_ref": "ROGER-901"})
        result = evaluate({"blockers": rows})
        self.assertIn(
            "non_waivable_final_package_blocker:AUDIENCE_SCORE_PRE_RELEASE",
            result["failures"],
        )


if __name__ == "__main__":
    unittest.main()
