"""T27: the cross-device demonstration of requirement section 14, asserted step by step.

Runs ``tools/collective_learning_demo.run_demo`` -- the same function the CLI runs -- on a
temp directory and checks every fact the transcript must carry.  Nothing here touches a
production runtime; the demo itself forbids any non-loopback socket and counts provider calls.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tools import collective_learning_demo as demo
from tools.collective_learning import contracts as c

HOME_PATH = re.compile(r"(/Us" r"ers/|/private/|/var/folders/)")


class E2EDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.out = Path(tempfile.mkdtemp(prefix="collective-e2e-"))
        cls.result = demo.run_demo(cls.out)
        cls.steps = {row["step"]: row for row in cls.result["steps"]}

    def test_zero_paid_posts_and_interception_named(self) -> None:
        self.assertEqual(self.result["paid_post_count"], 0)
        net = self.result["network_interception"]
        self.assertEqual((net["non_loopback_connect_attempts"], net["provider_client_calls"]), (0, 0))
        self.assertIn("socket.socket.connect", net["method"])
        self.assertIn("giggle_api_client._request", net["method"])

    def test_transcript_files_exist_and_carry_no_absolute_paths(self) -> None:
        text = (self.out / "transcript.json").read_text(encoding="utf-8")
        self.assertIsNone(HOME_PATH.search(text), "transcript must not leak local paths")
        self.assertTrue((self.out / "transcript.md").read_text(encoding="utf-8").startswith("# Collective"))
        self.assertEqual(len(self.result["steps"]), 9)

    def test_step1_fact_has_no_root_cause(self) -> None:
        s = self.steps[1]
        self.assertTrue(c.is_uuid(s["event_id"]))
        self.assertEqual(s["event_kind"], "FAILURE_OBSERVATION")
        self.assertFalse(s["has_root_cause_key"])
        self.assertIn("FORBIDDEN_KEY_ON_FACT:root_cause", s["root_cause_key_refused_with"])
        self.assertEqual(s["timecodes"][0]["timeline"], "FINAL_CUT")
        self.assertEqual(s["timecodes"][0]["video_sha256"], self.result["film_sha256_synthetic"])
        self.assertEqual(s["opportunity"], {"applicable_units": 6, "observed_units": 1})
        self.assertEqual(s["cloud_ack"], {"PENDING": 0, "DELIVERED": 1, "QUARANTINED": 0})
        self.assertEqual(s["cloud_unique_events"], 1)

    def test_step2_reproduced_attribution_and_honest_inconclusive(self) -> None:
        s = self.steps[2]
        self.assertEqual(s["review_attributed"]["basis"], "REPRODUCED")
        self.assertNotEqual(s["compile_without_rule_sha256"], s["compile_with_rule_sha256"])
        self.assertTrue(s["dialogue_byte_identical"])
        self.assertTrue(c.is_uuid(s["review_inconclusive"]["review_id"]))
        self.assertEqual(s["cloud_ack"]["QUARANTINED"], 0, "facts must be uploaded before the reviews citing them")
        self.assertEqual(s["cloud_attribution_chain_versions"], [1])

    def test_step3_candidate_scope_policy_refusal_and_signed_release(self) -> None:
        s = self.steps[3]
        self.assertEqual(s["scope"]["models"], [demo.SD2])
        self.assertEqual(s["scope"]["scene_types"], ["DIALOGUE"])
        self.assertEqual(s["scope"]["requires"], ["listener_offscreen"])
        self.assertEqual(s["states"], ["CANDIDATE", "VALIDATED", "CANARY"])
        self.assertTrue(any(b.startswith("VALIDATION_SCOPE_INSUFFICIENT") for b in
                            s["canary_refusal_on_deterministic_only"]["blockers"]))
        self.assertIn("REAL_MEDIA_REVIEW", s["canary_basis_caveat"])
        rp = s["renderer_positive_negative"]
        self.assertTrue(rp["clause_in_compile_with_rule"])
        self.assertFalse(rp["clause_in_compile_without_rule"])
        self.assertEqual(rp["visible_listener_unit_not_applicable"], "REQUIRED_CONDITION_ABSENT:listener_offscreen")
        self.assertTrue(s["bundle"]["signature_check"].startswith("SIGNATURE_VERIFIED"))
        self.assertTrue(c.is_sha256(s["bundle"]["bundle_digest"]))
        self.assertEqual(s["release"]["channel"], "CANARY")

    def test_step4_old_run_untouched_new_run_locks_release(self) -> None:
        s = self.steps[4]
        self.assertEqual(s["pull"]["fetched"][0]["status"], "FETCHED")
        self.assertEqual(s["lock_old"]["label"], "BUILTIN_BASELINE_NOT_CLOUD_SYNCED")
        self.assertEqual(s["lock_old"]["after_release_status"], "EXISTING_LOCK_KEPT")
        self.assertEqual(s["lock_old"]["after_release_sha256"], s["lock_old"]["lock_sha256"])
        self.assertTrue(s["lock_new_digest_equals_released_bundle"])
        self.assertEqual(s["lock_new"]["knowledge_bundle_digest"], self.steps[3]["bundle"]["bundle_digest"])
        self.assertEqual(s["lock_new"]["rules"], [{"rule_id": demo.RULE_ID, "rule_version": 1}])

    def test_step5_applied_and_verified_reach_the_cloud(self) -> None:
        s = self.steps[5]
        self.assertEqual(s["applied"]["evidence_scope"], "COMPILED_REQUEST")
        self.assertEqual(s["applied"]["entrypoint"], "compile_grouped_seedance_manifest.compile_final_prompts")
        self.assertEqual(s["applied"]["compiled_output_digest"], s["compiled_text_sha256"])
        self.assertEqual(s["applied"]["unit_ids"], ["EP02-VU-004"])
        self.assertTrue(s["clause_in_sent_text"])
        self.assertEqual(s["device_outbox"]["PENDING"], 0)
        self.assertEqual(s["cloud_adoption_states_for_dev_b"], ["APPLIED", "VERIFIED"])
        self.assertEqual(s["paid_post_count_so_far"], 0)

    def test_step6_outcome_pending_not_simulated(self) -> None:
        self.assertEqual(self.steps[6]["outcome"], "PENDING_REAL_FILM")
        self.assertEqual(self.steps[6]["outcome_observed_receipts"], 0)

    def test_step7_wrong_model_duplicate_and_outage(self) -> None:
        s = self.steps[7]
        self.assertEqual(s["wrong_model_device"]["resolved_bundles"], [])
        self.assertEqual(s["wrong_model_device"]["not_applicable"][0]["reasons"], ["OUT_OF_SCOPE:model=MiniMax-H3"])
        dup = s["duplicate_delivery"]
        self.assertEqual((dup["http_status"], dup["ack"]), (200, "DUPLICATE"))
        self.assertEqual(dup["unique_before"], dup["unique_after"])
        self.assertEqual(dup["duplicate_deliveries_logged"], 1)
        net = s["network_interruption"]
        self.assertLess(net["record_seconds_while_offline"], 1.0)
        self.assertEqual(net["offline_sync"], {"delivered": 0, "retry": 1})
        self.assertEqual(net["after_restart_outbox"]["PENDING"], 0)
        self.assertEqual(net["after_restart_outbox"]["QUARANTINED"], 0)
        self.assertEqual(net["unique_events_after"], dup["unique_after"] + 1)
        self.assertEqual(net["duplicate_deliveries_after"], 1)

    def test_step8_revocation_fallback_and_traceability(self) -> None:
        s = self.steps[8]
        self.assertTrue(s["revoke"]["revoked"])
        self.assertEqual(s["cloud_resolve_after"]["bundles"], [])
        self.assertEqual(s["cloud_resolve_after"]["revocations"][0]["version"], "2")
        self.assertEqual(s["lock_next"]["label"], "BUILTIN_BASELINE_NOT_CLOUD_SYNCED")
        self.assertEqual(s["lock_next"]["knowledge_bundle_digest"], self.steps[4]["lock_old"]["knowledge_bundle_digest"])
        self.assertEqual(s["lock_new_still_verifies_for_its_own_run"], "PASS")
        trace = s["trace"]
        self.assertEqual(trace["events"], [self.steps[1]["event_id"]])
        self.assertEqual(trace["reviews"], [self.steps[2]["review_attributed"]["review_id"]])
        self.assertIsNotNone(trace["bundles"][0]["revoked"])
        self.assertEqual(trace["adoption_receipts"], 2)
        self.assertEqual(trace["independent_sources"]["independent_sources"], 1)
        self.assertEqual(s["admin_page_mentions"], {"candidate": True, "event": True})


if __name__ == "__main__":
    unittest.main()
