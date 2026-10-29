"""tools/knowledge_sync_core.py on synthetic fixtures (offline).

Knowledge-loop audit 2026-10-27, constraint 4: new knowledge may point at the
FREE checks it affects, but must never auto-resubmit a paid task or add a
paid-redo condition.  free_recheck_targets() is the detection/reporting side
of that: a pure function over an already-loaded pipeline_state dict and the
registry's own rows, matched by the exact argv nalu_pipeline.py already
recorded for each step it ran -- never a guessed import graph, and never a
write of any kind.

tools/tests/test_line_upgrade_gate.py already covers sync()'s pre-existing
behaviour (idempotence, gap reporting, the nalu CLI wrapper) end to end
through the git-backed line_upgrade_gate harness; this file is scoped to the
new free_recheck_targets() function and its wiring into sync()'s SYNCED
return only, at the lighter direct-import level the other knowledge-loop
modules (test_knowledge_event_log.py, test_knowledge_consumption_ledger.py)
already use.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import knowledge_sync_core as core  # noqa: E402


def _rule(rule_id: str, **extra) -> dict:
    row = {"id": rule_id, "stage": "pipeline", "rule": f"rule {rule_id}", "lesson": "l", "recovery": "r",
           "implementation": ["tools/sample_free_gate.py"], "status": "REFERENCE_IMPLEMENTATION",
           "owner": "o", "authority": "a", "decision_record": "docs/decisions/DECISION_RECORDS.md",
           "regression": "tools/tests/test_sample_free_gate.py", "runtime_gate_added": False}
    row.update(extra)
    return row


def _step(name: str, script: str, paid: bool, exit_code: int = 0) -> dict:
    return {"name": name, "argv": ["/usr/bin/python3", script], "paid": paid,
            "exit_code": exit_code, "finished_at": "2026-10-28T00:00:00Z"}


class FreeRecheckTargetsTest(unittest.TestCase):
    def test_matches_free_step_and_excludes_paid_step(self) -> None:
        state = {"stages": {
            "S1": {"status": "PASS", "steps": [_step("s1_sample_gate", "/repo/tools/sample_free_gate.py", False)]},
            "S6": {"status": "PASS", "steps": [_step("s6_submit", "/repo/tools/sample_paid_submit.py", True)]},
        }}
        rows = [_rule("K900"), _rule("K901", implementation=["tools/sample_paid_submit.py"])]
        out = core.free_recheck_targets(state, rows, ["K900", "K901"])
        k900, k901 = out
        self.assertTrue(k900["found"])
        self.assertEqual(len(k900["free_matches"]), 1)
        self.assertEqual(k900["free_matches"][0]["stage"], "S1")
        self.assertEqual(k900["free_matches"][0]["stage_status"], "PASS")
        self.assertEqual(k900["paid_matches_excluded"], [])
        self.assertIsNone(k900["fallback_verification"])

        self.assertEqual(k901["free_matches"], [])
        self.assertEqual(len(k901["paid_matches_excluded"]), 1)
        self.assertEqual(k901["paid_matches_excluded"][0]["stage"], "S6")
        # a paid-only match is still not "free": the fallback must still point at
        # the regression suite, never at the paid step that happened to match.
        self.assertEqual(k901["fallback_verification"], "tools/tests/test_sample_free_gate.py")

    def test_rule_with_no_matching_step_reports_fallback_regression(self) -> None:
        state = {"stages": {"S1": {"status": "PASS",
                                   "steps": [_step("s1_other", "/repo/tools/unrelated.py", False)]}}}
        rows = [_rule("K900")]
        out = core.free_recheck_targets(state, rows, ["K900"])
        self.assertFalse(out[0]["direct_match_found"])
        self.assertEqual(out[0]["free_matches"], [])
        self.assertEqual(out[0]["fallback_verification"], "tools/tests/test_sample_free_gate.py")

    def test_unknown_rule_id_reported_as_not_found(self) -> None:
        out = core.free_recheck_targets({}, [_rule("K900")], ["K999"])
        self.assertEqual(out, [{"rule_id": "K999", "found": False}])

    def test_empty_state_is_handled(self) -> None:
        out = core.free_recheck_targets({}, [_rule("K900")], ["K900"])
        self.assertFalse(out[0]["direct_match_found"])

    def test_malformed_step_entries_are_skipped_not_raised(self) -> None:
        state = {"stages": {"S1": {"status": "PASS", "steps": ["not_a_dict", {"name": "short_argv", "argv": []}]},
                            "S2": "not_a_dict_either"}}
        out = core.free_recheck_targets(state, [_rule("K900")], ["K900"])
        self.assertFalse(out[0]["direct_match_found"])

    def test_never_mutates_its_inputs(self) -> None:
        state = {"stages": {"S1": {"status": "PASS",
                                   "steps": [_step("s1", "/repo/tools/sample_free_gate.py", False)]}}}
        rows = [_rule("K900")]
        before_state, before_rows = json.dumps(state, sort_keys=True), json.dumps(rows, sort_keys=True)
        core.free_recheck_targets(state, rows, ["K900"])
        self.assertEqual(json.dumps(state, sort_keys=True), before_state)
        self.assertEqual(json.dumps(rows, sort_keys=True), before_rows)


class SyncWiringTest(unittest.TestCase):
    """sync() itself, at the direct-import level: free_recheck only appears on
    the SYNCED branch and is wired to the exact pipeline_state file sync()
    already loads -- no second read, no new file."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "engine"
        self.runtime = self.tmp / "runtime"
        (self.root / "configs").mkdir(parents=True)
        (self.root / "docs/knowledge").mkdir(parents=True)
        (self.root / "knowledge").mkdir(parents=True)
        (self.root / "tools").mkdir(parents=True)
        (self.root / "docs/decisions").mkdir(parents=True)
        (self.root / "docs/decisions/DECISION_RECORDS.md").write_text("# decisions\n")
        (self.root / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md").write_text("# kb\n")
        (self.root / "tools" / "knowledge_registry.py").write_bytes(
            (Path(__file__).resolve().parents[1] / "knowledge_registry.py").read_bytes())
        registry = {"schema": "qingshan.knowledge_registry.v1", "version": "1.0.0",
                    "scope": "PORTABLE_KNOWLEDGE_NOT_PRODUCTION_AUTHORIZATION", "license": "x", "rules": []}
        (self.root / "configs/ENGINEERING_KNOWLEDGE_V1.json").write_text(json.dumps(registry))
        (self.root / "knowledge/failure_memory.jsonl").write_text("")
        (self.root / "tools/tests").mkdir(parents=True)
        (self.root / "tools/tests/test_knowledge_registry.py").write_text("# stub\n")
        (self.runtime / "reports").mkdir(parents=True)
        (self.runtime / "pipeline_state").mkdir(parents=True)

    def _candidate_file(self, episode: str, rows: list[dict]) -> None:
        (self.runtime / "reports" / f"{episode}_knowledge_candidates.json").write_text(json.dumps(rows))

    def test_synced_result_carries_free_recheck_for_the_new_rule(self) -> None:
        self._candidate_file("E01", [
            {"key": "x", "stage": "pipeline", "rule": "r", "lesson": "l", "recovery": "rec",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"}])
        (self.runtime / "pipeline_state" / "E01.json").write_text(json.dumps({"stages": {
            "S1": {"status": "PASS", "steps": [_step("s1_x", "/repo/tools/x.py", False)]}}}))
        out = core.sync(self.root, self.runtime, "E01")
        self.assertEqual(out["status"], "SYNCED")
        self.assertEqual(out["new_ids"], ["K001"])
        self.assertIn("free_recheck", out)
        self.assertEqual(out["free_recheck"][0]["rule_id"], "K001")
        self.assertFalse(out["free_recheck"][0]["direct_match_found"])  # implementation=[] matches nothing

    def test_dry_run_and_no_new_knowledge_do_not_carry_free_recheck(self) -> None:
        out = core.sync(self.root, self.runtime, "E02")
        self.assertEqual(out["status"], "NO_NEW_KNOWLEDGE")
        self.assertNotIn("free_recheck", out)
        self._candidate_file("E02", [
            {"key": "x", "stage": "pipeline", "rule": "r", "lesson": "l", "recovery": "rec",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"}])
        out = core.sync(self.root, self.runtime, "E02", dry_run=True)
        self.assertEqual(out["status"], "DRY_RUN")
        self.assertNotIn("free_recheck", out)

    def test_missing_pipeline_state_file_does_not_raise(self) -> None:
        self._candidate_file("E03", [
            {"key": "x", "stage": "pipeline", "rule": "r", "lesson": "l", "recovery": "rec",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"}])
        out = core.sync(self.root, self.runtime, "E03")  # no E03.json written at all
        self.assertEqual(out["status"], "SYNCED")
        self.assertEqual(out["free_recheck"][0]["found"], True)
        self.assertFalse(out["free_recheck"][0]["direct_match_found"])


if __name__ == "__main__":
    unittest.main()
