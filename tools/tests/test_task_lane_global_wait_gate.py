import unittest
from datetime import datetime, timezone

from tools.task_lane_global_wait_gate import audit_scheduler_state


OBSERVED_AT = datetime(2026, 8, 10, 3, 0, 0, tzinfo=timezone.utc)


def state(tasks, *, global_wait=False, heartbeat=None):
    tasks = [dict(task) for task in tasks]
    for task in tasks:
        if task.get("state") in {"RUNNING", "QA", "REMOTE_WAIT"}:
            task.setdefault("deliverable_type", "VIDEO")
            task.setdefault("lease_owner", "test-worker")
            task.setdefault("last_progress_at", "2026-08-10T02:59:00Z")
            task.setdefault("next_due_at", "2026-08-10T03:10:00Z")
            task.setdefault("lease_expires_at", "2026-08-10T04:00:00Z")
    payload = {
        "schema": "backlotos.task_lane_scheduler_state.v1",
        "scheduler_decision": {"global_wait": global_wait},
        "tasks": tasks,
    }
    if heartbeat is not None:
        payload["heartbeat_integration"] = heartbeat
    return payload


class TaskLaneGlobalWaitGateTests(unittest.TestCase):
    def audit(self, payload):
        return audit_scheduler_state(payload, observed_at=OBSERVED_AT)

    def test_ready_zero_cost_task_makes_global_wait_fail(self):
        result = self.audit(
            state([{"task_id": "PRECOMPILE", "lane_id": "PROMPTS", "state": "READY", "zero_cost": True}], global_wait=True)
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("GLOBAL_WAIT_MASKS_READY_ZERO_COST_TASKS", {row["code"] for row in result["failures"]})

    def test_waiting_dependency_requires_exact_predecessor_id(self):
        result = self.audit(
            state([{"task_id": "U19", "lane_id": "ACTION", "state": "WAITING_DEPENDENCY", "zero_cost": False}])
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("WAITING_DEPENDENCY_EXACT_PREDECESSOR_MISSING", {row["code"] for row in result["failures"]})

    def test_compacted_current_state_resolves_predecessors_through_terminal_ledger(self):
        payload = state([{
            "task_id": "U19",
            "lane_id": "ACTION",
            "state": "WAITING_DEPENDENCY",
            "zero_cost": False,
            "exact_predecessor_task_id": "ARCHIVED-U18",
            "blocked_by": "U18_RETURN_MISSING",
        }])
        payload["terminal_task_ledger"] = "workflow/ledger/E40_task_history.ndjson"
        result = self.audit(payload)
        self.assertNotIn(
            "WAITING_DEPENDENCY_EXACT_PREDECESSOR_UNKNOWN",
            {row["code"] for row in result["failures"]},
        )

    def test_remote_wait_does_not_mask_ready_other_lane(self):
        result = self.audit(
            state([
                {"task_id": "REMOTE", "lane_id": "ACTION", "state": "REMOTE_WAIT", "zero_cost": False, "wait_scope": "TASK_LOCAL"},
                {"task_id": "QA-PREP", "lane_id": "QA", "state": "READY", "zero_cost": True},
            ])
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["remote_wait_isolated_from_ready_lanes"])
        self.assertEqual(result["dispatchable_ready_task_ids"], ["QA-PREP"])

    def test_qingshan_production_schema_uses_same_gate(self):
        payload = state([{"task_id": "QA", "lane_id": "QA", "state": "READY", "zero_cost": True}])
        payload["schema"] = "qingshan.task_lane_scheduler_state.v1"
        payload["episode"] = "E40"
        result = self.audit(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["episode"], "E40")

    def test_remote_wait_global_wait_fails(self):
        result = self.audit(
            state([
                {"task_id": "REMOTE", "lane_id": "ACTION", "state": "REMOTE_WAIT", "zero_cost": False, "wait_scope": "TASK_LOCAL"},
                {"task_id": "QA-PREP", "lane_id": "QA", "state": "READY", "zero_cost": True},
            ], global_wait=True)
        )
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("REMOTE_WAIT_MASKS_READY_OTHER_LANES", codes)
        self.assertIn("GLOBAL_WAIT_MASKS_READY_ZERO_COST_TASKS", codes)

    def test_idle_unfinished_work_requires_legal_blocker_evidence(self):
        payload = state([
            {
                "task_id": "U19",
                "lane_id": "ACTION",
                "state": "WAITING_DEPENDENCY",
                "zero_cost": False,
                "exact_predecessor_task_id": "U18",
            },
            {
                "task_id": "U18",
                "lane_id": "ACTION",
                "state": "TERMINAL",
                "zero_cost": False,
            },
        ])
        result = self.audit(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["liveness_state"], "FALSE_IDLE")
        self.assertIn(
            "IDLE_WITH_UNFINISHED_WORK_AND_NO_LEGAL_BLOCKER",
            {row["code"] for row in result["failures"]},
        )

    def test_evidenced_legal_blocker_is_not_false_idle(self):
        payload = state([
            {
                "task_id": "U18",
                "lane_id": "ACTION",
                "state": "TERMINAL",
                "zero_cost": False,
            },
            {
                "task_id": "U19",
                "lane_id": "ACTION",
                "state": "WAITING_DEPENDENCY",
                "zero_cost": False,
                "exact_predecessor_task_id": "U18",
            },
        ])
        payload["scheduler_decision"]["legal_blocker"] = {
            "code": "PREDECESSOR_QA_FAILED",
            "evidence_ref": "qa/u18.json",
            "next_recheck_at": "2026-08-09T00:00:00Z",
        }
        result = self.audit(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["liveness_state"], "LEGALLY_BLOCKED")

    def test_heartbeat_return_is_idle_legal_without_active_successor(self):
        result = self.audit(
            state(
                [{"task_id": "DONE", "lane_id": "ACTION", "state": "TERMINAL", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": False,
                },
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertEqual(result["heartbeat_verdict"], "IDLE_LEGAL")

    def test_terminal_task_with_historical_blocked_by_is_not_current_input_blocker(self):
        result = self.audit(
            state(
                [
                    {
                        "task_id": "DONE-WITH-HISTORY",
                        "lane_id": "ACTION",
                        "state": "TERMINAL",
                        "zero_cost": False,
                        "blocked_by": ["HISTORICAL_PROVIDER_FAILURE"],
                    }
                ]
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["liveness_state"], "COMPLETE")
        self.assertEqual(result["heartbeat_verdict"], "IDLE_LEGAL")

    def test_heartbeat_return_passes_with_running_successor(self):
        result = self.audit(
            state(
                [{"task_id": "NEXT", "lane_id": "ACTION", "state": "RUNNING", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": False,
                },
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertEqual(result["active_successor_task_ids"], ["NEXT"])

    def test_expired_active_task_cannot_authorize_heartbeat_return(self):
        payload = state(
            [{
                "task_id": "STALE",
                "lane_id": "QA",
                "state": "QA",
                "zero_cost": True,
                "next_due_at": "2026-08-10T02:59:00Z",
                "lease_expires_at": "2026-08-10T02:59:30Z",
            }],
            heartbeat={
                "require_active_successor_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        codes = {row["code"] for row in result["failures"]}
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertIn("ACTIVE_TASK_NEXT_DUE_EXPIRED", codes)
        self.assertIn("ACTIVE_TASK_LEASE_EXPIRED", codes)
        self.assertEqual(result["heartbeat_verdict"], "ACTIVE")
        self.assertEqual(result["stale_or_invalid_active_task_ids"], ["STALE"])

    def test_active_task_requires_lease_owner_and_timestamps(self):
        payload = state(
            [{"task_id": "NEXT", "lane_id": "QA", "state": "QA", "zero_cost": True}],
            heartbeat={
                "require_active_successor_before_return": True,
                "episode_terminal": False,
            },
        )
        task = payload["tasks"][0]
        task["lease_owner"] = ""
        task["last_progress_at"] = "not-a-time"
        result = self.audit(payload)
        codes = {row["code"] for row in result["failures"]}
        self.assertIn("ACTIVE_TASK_LEASE_OWNER_MISSING", codes)
        self.assertIn("ACTIVE_TASK_TIMESTAMP_MISSING_OR_INVALID", codes)
        self.assertTrue(result["heartbeat_return_allowed"])

    def test_terminal_episode_may_return_without_successor(self):
        result = self.audit(
            state(
                [{"task_id": "DONE", "lane_id": "ACTION", "state": "TERMINAL", "zero_cost": True}],
                heartbeat={
                    "require_active_successor_before_return": True,
                    "episode_terminal": True,
                },
            )
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])

    def test_continuous_executor_ack_is_required_when_configured(self):
        payload = state(
            [{"task_id": "NEXT", "lane_id": "QA", "state": "QA", "zero_cost": True}],
            heartbeat={
                "require_active_successor_before_return": True,
                "require_continuous_executor_ack_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        codes = {row["code"] for row in result["failures"]}
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertIn("HEARTBEAT_RETURN_WITHOUT_CONTINUOUS_EXECUTOR_ACK", codes)

    def test_bound_continuous_executor_allows_heartbeat_return(self):
        payload = state(
            [{
                "task_id": "NEXT",
                "lane_id": "QA",
                "state": "QA",
                "zero_cost": True,
                "execution_mode": "CONTINUOUS",
                "executor_handle": "agent:/root/qa-worker",
                "executor_task_id": "NEXT",
                "executor_acknowledged_at": "2026-08-10T02:59:30Z",
                "executor_next_wakeup_at": "2026-08-10T03:05:00Z",
            }],
            heartbeat={
                "require_active_successor_before_return": True,
                "require_continuous_executor_ack_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["heartbeat_return_allowed"])
        self.assertEqual(result["continuous_executor_task_ids"], ["NEXT"])

    def test_executor_ack_cannot_precede_progress_or_wakeup_exceed_due(self):
        payload = state(
            [{
                "task_id": "NEXT",
                "lane_id": "QA",
                "state": "QA",
                "zero_cost": True,
                "execution_mode": "CONTINUOUS",
                "executor_handle": "agent:/root/qa-worker",
                "executor_task_id": "NEXT",
                "executor_acknowledged_at": "2026-08-10T02:58:59Z",
                "executor_next_wakeup_at": "2026-08-10T03:11:00Z",
            }],
            heartbeat={
                "require_active_successor_before_return": True,
                "require_continuous_executor_ack_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        codes = {row["code"] for row in result["failures"]}
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("ACTIVE_TASK_EXECUTOR_ACK_MISSING_OR_INVALID", codes)
        self.assertIn("ACTIVE_TASK_EXECUTOR_NEXT_WAKEUP_MISSING_OR_INVALID", codes)

    def test_remote_wait_also_requires_continuous_guardian(self):
        payload = state(
            [{
                "task_id": "REMOTE",
                "lane_id": "QA",
                "state": "REMOTE_WAIT",
                "zero_cost": True,
                "wait_scope": "TASK_LOCAL",
            }],
            heartbeat={
                "require_active_successor_before_return": True,
                "require_continuous_executor_ack_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "HEARTBEAT_RETURN_WITHOUT_CONTINUOUS_EXECUTOR_ACK",
            {row["code"] for row in result["failures"]},
        )
        self.assertTrue(result["heartbeat_return_allowed"])

    def test_fabricated_audit_successor_forbids_heartbeat_return(self):
        payload = state(
            [{
                "task_id": "E40-PARITY-WATCHDOG",
                "lane_id": "QA",
                "state": "REMOTE_WAIT",
                "zero_cost": True,
                "wait_scope": "TASK_LOCAL",
                "deliverable_type": "QA_RECEIPT",
            }],
            heartbeat={
                "require_active_successor_before_return": True,
                "episode_terminal": False,
            },
        )
        result = self.audit(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["heartbeat_return_allowed"])
        self.assertEqual(result["heartbeat_verdict"], "FABRICATED_SUCCESSOR")
        self.assertIn("FABRICATED_SUCCESSOR", {row["code"] for row in result["failures"]})


if __name__ == "__main__":
    unittest.main()
