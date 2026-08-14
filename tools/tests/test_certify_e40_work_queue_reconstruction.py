import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.certify_e40_work_queue_reconstruction import (
    QUEUE_REL,
    build_certification,
    derive_paid_safety,
    field_result,
)


ROOT = Path(__file__).resolve().parents[2]
class E40WorkQueueReconstructionCertificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        queue_path = ROOT / QUEUE_REL
        cls.queue_before = queue_path.read_bytes()
        observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        cls.result = build_certification(ROOT, observed_at=observed_at)
        cls.queue_after = queue_path.read_bytes()

    def test_live_certification_is_strictly_read_only(self):
        self.assertEqual(self.queue_before, self.queue_after)
        self.assertEqual(
            self.result["inputs"]["work_queue"]["sha256"],
            hashlib.sha256(self.queue_before).hexdigest(),
        )
        self.assertFalse(self.result["work_queue_write_performed"])
        self.assertEqual(self.result["provider_calls"], 0)
        self.assertEqual(self.result["transactions_created"], 0)
        self.assertEqual(self.result["credits_changed"], 0)

    def test_dual_credit_recomputation_closes_exact_totals(self):
        credit = self.result["credit_recomputation"]
        self.assertTrue(credit["dual_method_agrees"])
        self.assertEqual(
            credit["baseline_plus_exact_post_transactions"],
            {"gross_pay": 1373, "refund": 128, "net": 1245, "cap": 10000, "remaining": 8755},
        )
        self.assertEqual(credit["media_class_recomputation"]["image_pay"], 379)
        self.assertEqual(credit["media_class_recomputation"]["video_pay"], 992)
        self.assertEqual(credit["media_class_recomputation"]["audio_pay"], 2)

    def test_all_post_baseline_transactions_are_task_bound_and_terminal(self):
        inventory = self.result["transaction_inventory"]
        self.assertEqual(inventory["file_count"], 74)
        self.assertEqual(inventory["task_bound_count"], 71)
        self.assertEqual(inventory["unbound_count"], 3)
        post = self.result["post_baseline_reconciliation"]
        self.assertEqual(post["transaction_count"], 7)
        self.assertEqual(post["failures"], [])
        self.assertTrue(post["all_terminal"])
        self.assertEqual(self.result["active_remote_handles"]["count"], 0)

    def test_stable_authority_state_matches_current_recovery_phase(self):
        failed_fields = {row["field"] for row in self.result["failed_critical_fields"]}
        self.assertNotIn("task_lane_scheduler.observed_sha256", failed_fields)
        stable_failures = self.result["stable_field_failures"]
        if stable_failures:
            self.assertEqual(self.result["status"], "FAIL_STABLE_OR_RUNTIME_PAID_SAFETY_GATES")
            self.assertFalse(self.result["all_critical_fields_closed"])
            self.assertFalse(self.result["paid_actions_allowed"])
        else:
            self.assertTrue(self.result["stable_fields_closed"])
            self.assertTrue(self.result["all_critical_fields_closed"])
            self.assertTrue(self.result["paid_safety_derivation"]["derived_value"])
            if self.result["work_queue_recovery_paid_flag"]:
                self.assertTrue(self.result["recovery_paid_flag_matches_derived"])
            else:
                self.assertEqual(
                    self.result["status"],
                    "PASS_DERIVED_PAID_SAFETY_PHASE2_RECOVERY_FLAG_PENDING",
                )
                self.assertFalse(self.result["recovery_paid_flag_matches_derived"])

    def test_scheduler_sha_drift_is_warning_but_runtime_gates_are_hard(self):
        observation = self.result["scheduler_dynamic_observation"]
        self.assertFalse(observation["sha_is_permanent_execution_critical_field"])
        self.assertTrue(observation["paid_preflight_revalidation_required"])
        self.assertTrue(observation["path_gate_pass"])
        self.assertTrue(observation["episode_terminal_gate_pass"])
        self.assertTrue(observation["hard_gates_pass"])
        self.assertEqual(observation["global_wait_gate"]["status"], "PASS")
        self.assertTrue(observation["global_wait_gate"]["heartbeat_return_allowed"])
        warning_codes = {row["code"] for row in self.result["dynamic_warnings"]}
        if observation["sha_drift"]:
            self.assertIn(
                "DYNAMIC_SCHEDULER_SHA_DRIFT_REQUIRES_PAID_PREFLIGHT_REOBSERVATION",
                warning_codes,
            )
        else:
            self.assertNotIn(
                "DYNAMIC_SCHEDULER_SHA_DRIFT_REQUIRES_PAID_PREFLIGHT_REOBSERVATION",
                warning_codes,
            )

    def test_unrelated_zero_cost_qa_does_not_enter_paid_safety_formula(self):
        self.assertTrue(self.result["current_blockers"])
        self.assertFalse(self.result["current_blockers_affect_paid_safety"])
        self.assertTrue(
            derive_paid_safety(
                stable_fields_closed=True,
                dual_credit_method_agrees=True,
                active_remote_handle_count=0,
                active_paid_authorization_count=0,
                transactions_closed=True,
                scheduler_hard_gates_pass=True,
            )
        )

    def test_two_phase_proposal_repairs_stable_authority_then_recertifies(self):
        proposal = self.result["root_review_patch_proposal"]
        phase1 = proposal["phase_1_stable_authority_repair"]
        repaired = phase1["set"]
        self.assertFalse(phase1["paid_actions_allowed_after_phase"])
        self.assertEqual(repaired["e40_credits"]["image_pay"], 379)
        self.assertEqual(repaired["e40_credits"]["video_pay"], 992)
        self.assertEqual(repaired["e40_credits"]["audio_pay"], 2)
        self.assertEqual(
            repaired["latest_e40_u29c_local_depth_layer_candidate"]["sha256"],
            "962bf54654a66e01ada6fe0924a28252a7d1114e44efe889360a427183c4aadd",
        )
        self.assertEqual(
            repaired["latest_e40_u29b_independent_material_admission_final_chain_hold"]["path"],
            "workflow/releases/E40_U29A_V4_U29B_FINAL_CHAIN_READINESS_NO_ASSEMBLY_RECEIPT_20260810.json",
        )
        self.assertFalse(
            repaired["work_queue_recovery"]["paid_actions_allowed"]
        )
        self.assertFalse(repaired["work_queue_recovery"]["release_actions_allowed"])
        self.assertIn("authoritative_certification_path", repaired["work_queue_recovery"])
        phase2 = proposal["phase_2_paid_flag_after_fresh_recertification"]
        self.assertTrue(phase2["candidate_allowed_by_current_non_queue_runtime_gates"])
        self.assertTrue(phase2["set"]["work_queue_recovery"]["paid_actions_allowed"])
        self.assertFalse(phase2["set"]["work_queue_recovery"]["release_actions_allowed"])

    def test_field_result_is_exact_and_machine_verifiable(self):
        self.assertEqual(field_result("x", 1, 1, ["a"])["status"], "PASS")
        mismatch = field_result("x", 1, 2, ["a"])
        self.assertEqual(mismatch["status"], "FAIL")
        self.assertEqual(mismatch["observed"], 1)
        self.assertEqual(mismatch["expected"], 2)


if __name__ == "__main__":
    unittest.main()
