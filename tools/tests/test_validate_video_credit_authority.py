import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_video_credit_authority import evaluate


class VideoCreditAuthorityValidationTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> dict:
        runtime_path = root / "runtime.json"
        corrected_path = root / "corrected.json"
        final_path = root / "final.json"
        runtime_path.write_text(
            json.dumps(
                {
                    "status": "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED",
                    "actual_charged_credits_known_total": 51024,
                    "actual_total_complete": True,
                    "pending_attempt_count": 0,
                    "approval": {"valid": False, "binding_valid": False},
                    "recorded_at": "changes-every-run",
                }
            ),
            encoding="utf-8",
        )
        corrected_path.write_text(
            json.dumps({"actual_charged_video_credits": 51024}), encoding="utf-8"
        )
        final_path.write_text(
            json.dumps({"episode_exact_video_credits": {"E28": 51024}}), encoding="utf-8"
        )
        corrected_sha = hashlib.sha256(corrected_path.read_bytes()).hexdigest()
        final_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
        return {
            "episode": "E28",
            "status": "BLOCKED_VIDEO_CREDIT_LIMIT_AND_CREATIVE_CHOICE",
            "current_authoritative_values": {"actual_charged_video_credits": 51024},
            "u09": {
                "option_a": {
                    "new_generation_credits_if_successful": 260,
                    "minimum_new_limit_credits": 51284,
                    "required_gate_sha256": corrected_sha,
                }
            },
            "active_authority_chain": [
                {
                    "role": "runtime_enforcement",
                    "path": "runtime.json",
                    "integrity_policy": "MUTABLE_RUNTIME_REPORT_NOT_APPROVAL_TARGET",
                    "expected_facts": {
                        "status": "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED",
                        "actual_charged_credits_known_total": 51024,
                        "actual_total_complete": True,
                        "pending_attempt_count": 0,
                        "approval_valid": False,
                        "approval_binding_valid": False,
                    },
                },
                {
                    "role": "account_window_correction_and_human_approval_target",
                    "path": "corrected.json",
                    "sha256": corrected_sha,
                },
                {
                    "role": "final_evidence_boundary_reconciliation",
                    "path": "final.json",
                    "sha256": final_sha,
                },
            ],
        }

    def test_passes_with_mutable_runtime_report_and_immutable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = self.build_fixture(root)
            result = evaluate(authority, root)
            self.assertEqual(result["status"], "PASS", result["failures"])

    def test_rejects_fixed_runtime_sha_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = self.build_fixture(root)
            authority["active_authority_chain"][0]["sha256"] = "stale"
            result = evaluate(authority, root)
            self.assertIn("runtime_report_must_not_bind_fixed_sha256", result["failures"])

    def test_rejects_cross_document_credit_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = self.build_fixture(root)
            runtime = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
            runtime["actual_charged_credits_known_total"] = 51025
            (root / "runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
            result = evaluate(authority, root)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("authority_runtime_actual_credit_mismatch", result["failures"])

    def test_rejects_immutable_gate_sha_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = copy.deepcopy(self.build_fixture(root))
            (root / "corrected.json").write_text(
                json.dumps({"actual_charged_video_credits": 51024, "mutated": True}),
                encoding="utf-8",
            )
            result = evaluate(authority, root)
            self.assertIn("corrected_gate_sha256_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
