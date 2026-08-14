import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.episode_video_generation_guard import (
    _approval_binding_valid,
    _episode_video_attempts,
    _singleton_video_task,
    evaluate_episode_credit_gate,
    evaluate_episode_submission_authority,
    find_existing_paid_candidate,
    generation_fingerprint,
)


def video_task(task_key="E9999-N01", prompt="locked prompt"):
    return {
        "task_key": task_key,
        "source_id": "E9999-N01",
        "tool_type": "video_generation",
        "prompt": prompt,
        "model": "seedance-2.0-pro",
        "duration": 10,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "reference_images": [],
    }


def attempt(task_id, credits, success=True):
    return {
        "attempt": 1,
        "task_id": task_id,
        "success": success,
        "actual_charged_credits": credits if success else 0,
        "charge_status": "SUCCESS_ACTUAL_CHARGE_RECORDED" if success else "FAILED_ZERO_CHARGE",
    }


class EpisodeVideoGenerationGuardTests(unittest.TestCase):
    def test_v2_approval_uses_stable_authority_and_scope_binding(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "standing.json"
            authority.write_text(json.dumps({
                "status": "APPROVED",
                "approved_by": "Roger",
                "approved_limit_credits_per_episode": 10000,
            }), encoding="utf-8")
            registry = root / "scope.json"
            registry.write_text(json.dumps({
                "episode": "E36",
                "status": "ACTIVE",
                "workflow_scope_id": "e36_current",
                "configured_limit_credits": 10000,
                "canonical_script_sha256": "script-sha",
                "canonical_manifest_sha256": "manifest-sha",
            }), encoding="utf-8")
            approval = {
                "schema": "qingshan.episode_video_credit_limit_approval.v2",
                "approved_limit_credits": 10000,
                "workflow_scope_id": "e36_current",
                "standing_authority": str(authority),
                "standing_authority_sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
                "scope_registry": str(registry),
                "scope_registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                "canonical_script_sha256": "script-sha",
                "canonical_manifest_sha256": "manifest-sha",
                "gate_report": str(root / "mutable-gate.json"),
                "gate_report_sha256": "stale-by-design",
            }

            with patch("tools.episode_video_generation_guard.ROOT", root):
                self.assertTrue(_approval_binding_valid("E36", approval))

    def test_explicit_episode_submission_hold_blocks_paid_video(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "E32_VIDEO_SUBMISSION_AUTHORITY.json"
            path.write_text(
                '{"status":"HOLD","video_submission_allowed":false,"reason":"script revision pending"}',
                encoding="utf-8",
            )

            report = evaluate_episode_submission_authority("E32", path)

        self.assertEqual(report["status"], "BLOCKED_EPISODE_VIDEO_SUBMISSION_AUTHORITY")
        self.assertFalse(report["video_submission_allowed"])

    def test_explicit_episode_submission_release_passes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "E32_VIDEO_SUBMISSION_AUTHORITY.json"
            path.write_text(
                '{"status":"AUTHORIZED","video_submission_allowed":true,"authorized_by":"Roger"}',
                encoding="utf-8",
            )

            report = evaluate_episode_submission_authority("E32", path)

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["video_submission_allowed"])

    def test_release_cannot_bypass_required_canonical_script_gate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            gate = root / "activation.json"
            gate.write_text(
                '{"status":"BLOCKED_CANONICAL_SCRIPT_ACTIVATION","canonical_activation_allowed":false}',
                encoding="utf-8",
            )
            authority = root / "E32_VIDEO_SUBMISSION_AUTHORITY.json"
            authority.write_text(
                json.dumps({
                    "status": "AUTHORIZED",
                    "video_submission_allowed": True,
                    "canonical_script_activation_gate": str(gate),
                }),
                encoding="utf-8",
            )

            report = evaluate_episode_submission_authority("E32", authority)

        self.assertEqual(report["status"], "BLOCKED_EPISODE_VIDEO_SUBMISSION_AUTHORITY")
        self.assertFalse(report["video_submission_allowed"])
        self.assertIn("CANONICAL_SCRIPT_ACTIVATION_GATE_NOT_PASS", report["failures"])

    def test_exact_successful_generation_is_reused_not_resubmitted(self):
        prior = video_task("E9999-N01-V1")
        prior["task_id"] = "paid-task"
        prior["state"] = "qa_pass"
        prior["output_path"] = "/tmp/existing.mp4"
        prior["generation_fingerprint"] = generation_fingerprint(prior)
        prior["credit_attempts"] = [
            {
                **attempt("paid-task", 135),
                "generation_fingerprint": prior["generation_fingerprint"],
            }
        ]
        candidate = video_task("E9999-N01-V2")
        receipt = {"episode": "E9999", "tasks": [prior, candidate]}

        existing = find_existing_paid_candidate("E9999", candidate, receipt)

        self.assertEqual(existing["task_id"], "paid-task")
        self.assertEqual(existing["generation_fingerprint"], generation_fingerprint(candidate))

    def test_changed_prompt_allows_failed_only_generation(self):
        prior = video_task("E9999-N01-V1")
        prior.update({
            "task_id": "paid-task",
            "state": "qa_failed_terminal",
            "generation_fingerprint": generation_fingerprint(prior),
        })
        candidate = video_task("E9999-N01-R1", prompt="corrected prompt")

        self.assertIsNone(
            find_existing_paid_candidate("E9999", candidate, {"episode": "E9999", "tasks": [prior, candidate]})
        )

    def test_over_configured_credits_blocks_without_roger_approval(self):
        task = video_task("E9998-N01")
        task["credit_attempts"] = [attempt("paid-task", 5001)]
        receipt = {"episode": "E9998", "tasks": [task]}

        report = evaluate_episode_credit_gate("E9998", receipt, limit=5000)

        self.assertEqual(report["status"], "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED")
        self.assertEqual(report["actual_charged_credits_known_total"], 5001)

    def test_failed_generation_is_zero_and_does_not_consume_budget(self):
        task = video_task("E9997-N01")
        task["credit_attempts"] = [attempt("failed-task", 0, success=False)]
        receipt = {"episode": "E9997", "tasks": [task]}

        report = evaluate_episode_credit_gate("E9997", receipt, limit=5000)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["actual_charged_credits_known_total"], 0)
        self.assertEqual(report["failed_zero_charge_count"], 1)

    def test_missing_success_credit_blocks_accounting(self):
        task = video_task("E9996-N01")
        task["credit_attempts"] = [attempt("unknown-task", None)]
        receipt = {"episode": "E9996", "tasks": [task]}

        report = evaluate_episode_credit_gate("E9996", receipt, limit=5000)

        self.assertEqual(report["status"], "BLOCKED_VIDEO_CREDIT_ACCOUNTING_INCOMPLETE")

    @patch("tools.episode_video_generation_guard._receipt_payloads")
    def test_reconciled_credit_wins_over_stale_unknown_duplicate(self, payloads):
        stale = video_task("E9994-N01-STALE")
        stale["credit_attempts"] = [attempt("same-task", None)]
        reconciled = video_task("E9994-N01-RECONCILED")
        reconciled["credit_attempts"] = [attempt("same-task", 260)]
        payloads.return_value = iter([
            ("reconciled.json", {"episode": "E9994", "tasks": [reconciled]}),
            ("stale.json", {"episode": "E9994", "tasks": [stale]}),
        ])

        rows = _episode_video_attempts("E9994")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actual_charged_credits"], 260)

    @patch("tools.episode_video_generation_guard._receipt_payloads")
    def test_completed_task_with_exact_credit_and_null_success_is_charged(self, payloads):
        completed = video_task("E9993-N01")
        completed.update({
            "task_id": "completed-task",
            "remote_status": "completed",
            "output_path": "/tmp/completed.mp4",
            "credit_attempts": [{
                "attempt": 1,
                "task_id": "completed-task",
                "success": None,
                "actual_charged_credits": 300,
                "charge_status": "EXACT_TASK_ID_STATEMENT_MATCH",
            }],
        })
        payloads.return_value = iter([
            ("completed.json", {"episode": "E9993", "tasks": [completed]}),
        ])

        rows = _episode_video_attempts("E9993")

        self.assertTrue(rows[0]["success"])
        self.assertEqual(rows[0]["actual_charged_credits"], 300)

    def test_single_video_receipt_is_normalized_for_credit_accounting(self):
        task = _singleton_video_task({
            "schema": "qingshan.unit.changed_input_video_submit.v1",
            "episode": "E9992",
            "unit_id": "E9992-U01",
            "task_id": "single-task",
            "model": "seedance-2.0-pro",
            "status": "COMPLETED_DOWNLOADED_SEMANTIC_HARD_FAIL",
            "completed_at": "2026-07-22T01:00:00Z",
            "output_path": "/tmp/single.mp4",
            "actual_charged_credits": 260,
        })

        self.assertEqual(task["tool_type"], "video_generation")
        self.assertTrue(task["credit_attempts"][0]["success"])
        self.assertEqual(task["credit_attempts"][0]["actual_charged_credits"], 260)

    @patch("tools.episode_video_generation_guard._approval")
    @patch("tools.episode_video_generation_guard._approval_binding_valid", return_value=True)
    def test_roger_can_approve_a_higher_explicit_limit(self, binding, approval):
        approval.return_value = (
            "/tmp/approval.json",
            {
                "status": "APPROVED",
                "approved_by": "Roger",
                "approved_at": "2026-07-21T15:00:00-0700",
                "approved_limit_credits": 7000,
                "gate_report_sha256": "abc123",
            },
        )
        task = video_task("E9995-N01")
        task["credit_attempts"] = [attempt("paid-task", 6000)]
        receipt = {"episode": "E9995", "tasks": [task]}

        report = evaluate_episode_credit_gate("E9995", receipt, limit=5000)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["effective_limit_credits"], 7000)

    @patch("tools.episode_video_generation_guard._account_window_credit_correction")
    def test_account_window_correction_is_audit_only(self, correction):
        correction.return_value = {
            "path": "/tmp/correction.json",
            "sha256": "abc123",
            "authoritative_total_at_reconciliation": 51024,
            "receipt_scan_baseline_credits": 18504,
            "account_window_correction_credits": 32520,
        }
        task = video_task("E9991-N01")
        task["credit_attempts"] = [attempt("paid-task", 18504)]

        report = evaluate_episode_credit_gate("E9991", {"episode": "E9991", "tasks": [task]}, limit=5000)

        self.assertEqual(report["receipt_scan_known_credits"], 18504)
        self.assertEqual(report["actual_charged_credits_known_total"], 18504)
        self.assertEqual(report["historical_account_window_audit"]["authoritative_total_at_reconciliation"], 51024)
        self.assertEqual(report["status"], "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED")

    @patch("tools.episode_video_generation_guard._workflow_scope_registry")
    @patch("tools.episode_video_generation_guard._receipt_payloads")
    def test_active_workflow_scope_excludes_historical_rounds(self, payloads, registry):
        registry.return_value = (
            "/tmp/scope.json",
            {"status": "ACTIVE", "workflow_scope_id": "e999_current"},
        )
        current = video_task("E999-N01")
        current["prompt_file"] = "tenants/test/projects/e999_current/prompts/u01.txt"
        current["credit_attempts"] = [attempt("current-task", 3960)]
        historical = video_task("E999-N02")
        historical["prompt_file"] = "tenants/test/projects/e999_old/prompts/u02.txt"
        historical["credit_attempts"] = [attempt("historical-task", 51024)]
        payloads.return_value = iter([
            ("current.json", {"episode": "E999", "tasks": [current]}),
            ("historical.json", {"episode": "E999", "tasks": [historical]}),
        ])

        report = evaluate_episode_credit_gate("E999", limit=6000)

        self.assertEqual(report["actual_charged_credits_known_total"], 3960)
        self.assertEqual(report["status"], "PASS")

    @patch.dict("os.environ", {}, clear=True)
    @patch("tools.episode_video_generation_guard._workflow_scope_registry")
    @patch("tools.episode_video_generation_guard._receipt_payloads", return_value=iter(()))
    def test_registered_scope_limit_is_default_authority(self, payloads, registry):
        registry.return_value = (
            "/tmp/scope.json",
            {
                "status": "ACTIVE",
                "workflow_scope_id": "e999_current",
                "configured_limit_credits": 10000,
            },
        )

        report = evaluate_episode_credit_gate("E999")

        self.assertEqual(report["configured_limit_credits"], 10000)
        self.assertEqual(report["effective_limit_credits"], 10000)
        self.assertIn("registered 10000-credit video limit", report["policy"])

    @patch.dict("os.environ", {}, clear=True)
    @patch("tools.episode_video_generation_guard._workflow_scope_registry")
    @patch("tools.episode_video_generation_guard._approval_binding_valid", return_value=True)
    @patch("tools.episode_video_generation_guard._approval")
    @patch("tools.episode_video_generation_guard._receipt_payloads", return_value=iter(()))
    def test_approval_equal_to_registered_limit_remains_valid(self, payloads, approval, binding, registry):
        registry.return_value = (
            "/tmp/scope.json",
            {
                "status": "ACTIVE",
                "workflow_scope_id": "e999_current",
                "configured_limit_credits": 10000,
            },
        )
        approval.return_value = (
            "/tmp/approval.json",
            {
                "status": "APPROVED",
                "approved_by": "Roger",
                "approved_at": "2026-07-30T13:52:41Z",
                "approved_limit_credits": 10000,
                "workflow_scope_id": "e999_current",
            },
        )

        report = evaluate_episode_credit_gate("E999")

        self.assertTrue(report["approval"]["valid"])
        self.assertTrue(report["approval"]["binding_valid"])
        self.assertEqual(report["effective_limit_credits"], 10000)

    @patch("tools.episode_video_generation_guard._approval")
    @patch("tools.episode_video_generation_guard._approval_binding_valid", return_value=False)
    def test_stale_gate_sha_does_not_raise_effective_limit(self, binding, approval):
        approval.return_value = (
            "/tmp/approval.json",
            {
                "status": "APPROVED",
                "approved_by": "Roger",
                "approved_at": "2026-07-21T15:00:00-0700",
                "approved_limit_credits": 7000,
                "gate_report": "/tmp/gate.json",
                "gate_report_sha256": "stale",
            },
        )
        task = video_task("E9990-N01")
        task["credit_attempts"] = [attempt("paid-task", 6000)]

        report = evaluate_episode_credit_gate("E9990", {"episode": "E9990", "tasks": [task]}, limit=5000)

        self.assertFalse(report["approval"]["valid"])
        self.assertEqual(report["effective_limit_credits"], 5000)
        self.assertEqual(report["status"], "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
