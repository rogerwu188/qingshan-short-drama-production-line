"""Knowledge-loop case tests: a rule that changed nothing can never read APPLIED, and removing a
rule restores the earlier output.

Line owner 2026-11-01, item 5: prove the loop once on a REAL production problem, with demo
fixtures kept separate from the real record.  So this file has two clearly separated halves:

* ``FixtureTests``      -- synthetic hits/captions.  These prove the MECHANISM (no case can
                           round an unused rule up to APPLIED; a disabled rule restores the
                           earlier verdict).  They are fixtures, not evidence.
* ``RealCase001Test``   -- the E13 case, driven from ``configs/knowledge_loop_cases/
                           CASE_001_BURNED_TEXT_SCOPE.json`` and the real recorded artefacts.
                           It skips (never passes) when those artefacts are not on the machine,
                           because a real case cannot be proven from a fixture.

The "without the rule" arm is the last real revision before the rule (git 7ed3399), which is why
the fixtures below are only ever used to test the mechanism, never inside the case record.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import burned_text_cover as btc  # noqa: E402
from tools import knowledge_loop_case as klc  # noqa: E402
from tools.collective_learning import adoption, contracts as c  # noqa: E402

CASE_SPEC = ROOT / "configs/knowledge_loop_cases" / "CASE_001_BURNED_TEXT_SCOPE.json"


def real_roots() -> dict[str, Path] | None:
    """The roots the episode actually wrote to, from the line's own variables (nalu_paths).

    ``NALU_ENGINE_ROOT`` is the DEPLOYED engine checkout that owns ``workflow/`` (not this
    worktree); ``NALU_RUNTIME_ROOT`` is the runtime root.  Unset -> None -> the real case skips.
    """
    engine, runtime = os.environ.get("NALU_ENGINE_ROOT"), os.environ.get("NALU_RUNTIME_ROOT")
    if not (engine and runtime and CASE_SPEC.is_file()):
        return None
    roots = {"ENGINE": ROOT, "WORKFLOW": Path(engine) / "workflow", "RUNTIME": Path(runtime) / "runtime"}
    if not (roots["WORKFLOW"] / "nalu" / "E13" / "assembly").is_dir():
        return None
    if not (roots["RUNTIME"] / "pipeline_logs" / "E13").is_dir():
        return None
    return roots


# --------------------------------------------------------------------------- mechanism, on fixtures
class FixtureGateTests(unittest.TestCase):
    """Synthetic input only.  Establishes the mechanism the real case then uses."""

    CFG = {"band": {"y0": 0.66, "y1": 0.81, "x0": 0.06, "x1": 0.94},
           "verify": {"fps": 2, "min_cjk_chars": 2, "min_confidence": 0.7,
                      "inside_bar_min_similarity": 0.5, "dialogue_band_pad": 0.10}}
    CAPTIONS = [{"text": "多谢邵兄好意", "start": 1.0, "end": 2.0}]

    def test_scene_signage_away_from_the_band_passes_only_under_the_rule(self) -> None:
        """A plaque hit is ignored by the current module and fails under the pre-rule revision."""
        hits = [(1.2, "猿明", 0.9, 0.15, 0.01, 0.82, 0.14)]
        self.assertEqual(btc.verify(hits, self.CAPTIONS, self.CFG)["status"], "PASS")
        try:
            old = klc.load_gate(
                {"replay": {"gate": {"module": "tools/burned_text_cover.py",
                                     "disabled_variant": {"kind": "git_revision", "commit": "7ed3399"}}}},
                {"ENGINE": ROOT}, with_rule=False)
        except klc.CaseError as exc:  # an extracted source archive has no git history
            self.skipTest(f"pre-rule revision unavailable: {exc}")
        self.assertEqual(old.verify(hits, self.CAPTIONS, self.CFG)["status"], "FAIL")

    def test_the_rule_does_not_weaken_the_real_defect_it_exists_for(self) -> None:
        """Disabling the rule is a control, not a licence: a burned caption is still caught."""
        burned = [(1.2, "多谢邵兄好意", 0.9, 0.20, 0.02, 0.80, 0.10)]
        self.assertEqual(btc.verify(burned, self.CAPTIONS, self.CFG)["status"], "FAIL")
        near_band = [(1.2, "多谢邵兄好意", 0.9, 0.20, 0.84, 0.80, 0.90)]
        self.assertEqual(btc.verify(near_band, self.CAPTIONS, self.CFG)["status"], "FAIL")


# --------------------------------------------------------------------------- never APPLIED unused
class UnusedRuleNeverReadsAppliedTest(unittest.TestCase):
    """The states above APPLIED must stay unreachable for a rule that changed nothing."""

    IDENT = {"tenant_id": "t", "line_id": "l", "device_id": "d", "run_id": "t.l.E01"}
    RULE = {"rule_id": "R-UNUSED", "rule_version": 1}

    def _selected(self) -> dict:
        return adoption.selected(identity=self.IDENT, rule=self.RULE, stage="S7", unit_ids=["U1"],
                                 entrypoint="test", bundle_digest="a" * 64)

    def test_a_rule_whose_clause_never_appears_cannot_be_applied(self) -> None:
        with self.assertRaises(c.ContractError) as caught:
            adoption.applied(identity=self.IDENT, rule=self.RULE, stage="S7", unit_ids=["U1"], entrypoint="t",
                             bundle_digest="a" * 64, clause="the clause", source_contract={"x": 1},
                             compiled_with="nothing here", compiled_without="nothing here")
        self.assertIn("APPLIED_CLAUSE_ABSENT_FROM_COMPILED_OUTPUT", caught.exception.codes)
        self.assertEqual(adoption.strongest_state([self._selected()], "R-UNUSED"), "SELECTED")

    def test_a_rule_already_present_without_it_proves_nothing(self) -> None:
        """The clause being in both outputs means the rule changed nothing -- not APPLIED."""
        with self.assertRaises(c.ContractError) as caught:
            adoption.applied(identity=self.IDENT, rule=self.RULE, stage="S7", unit_ids=["U1"], entrypoint="t",
                             bundle_digest="a" * 64, clause="the clause", source_contract={"x": 1},
                             compiled_with="A the clause", compiled_without="B the clause")
        self.assertIn("APPLIED_CLAUSE_ALREADY_PRESENT_WITHOUT_RULE", caught.exception.codes)

    def test_a_hand_built_applied_receipt_without_evidence_is_not_evidence(self) -> None:
        forged = {**self._selected(), "state": "APPLIED"}
        with self.assertRaises(c.ContractError):
            c.validate_adoption(forged)
        self.assertEqual(adoption.strongest_state([forged], "R-UNUSED"), "NONE")

    def test_verified_cannot_skip_applied_or_change_output(self) -> None:
        applied = adoption.applied(identity=self.IDENT, rule=self.RULE, stage="S7", unit_ids=["U1"],
                                   entrypoint="t", bundle_digest="a" * 64, clause="the clause",
                                   source_contract={"x": 1}, compiled_with="A the clause",
                                   compiled_without="A")
        with self.assertRaises(c.ContractError):
            adoption.verified(self._selected(), test_name="t", assertion="a", passed=True,
                              checked_output_digest="0" * 64)
        with self.assertRaises(c.ContractError):
            adoption.verified(applied, test_name="t", assertion="a", passed=True,
                              checked_output_digest="0" * 64)


# --------------------------------------------------------------------------- provenance contract
class CaseProvenanceContractTest(unittest.TestCase):
    def _block(self) -> dict:
        loc = {"root": "ENGINE", "path": "tools/burned_text_cover.py"}
        return {
            "fact": {"statement": "x", "artefact": loc, "artefact_sha256": "a" * 64, "measured": {"v": 1}},
            "cause": {"statement": "y", "evidence": [{"statement": "z", "artefact": loc,
                                                      "artefact_sha256": "b" * 64}]},
            "rule_source": {"file": "tools/burned_text_cover.py", "line": 139, "clause": "c"},
            "verification": {"measurement": "m",
                             "before": {"value": "FAIL", "artefact": loc, "artefact_sha256": "c" * 64},
                             "after": {"value": "PASS", "artefact": loc, "artefact_sha256": "d" * 64}},
        }

    def test_complete_provenance_passes(self) -> None:
        c.validate_case_provenance(self._block())

    def test_each_missing_part_is_named(self) -> None:
        for part in c.PROVENANCE_PARTS:
            block = self._block()
            block.pop(part)
            with self.assertRaises(c.ContractError) as caught:
                c.validate_case_provenance(block)
            self.assertIn(f"CASE_PROVENANCE_PART_MISSING:{part}", caught.exception.codes)

    def test_a_cause_without_evidence_is_refused(self) -> None:
        block = self._block()
        block["cause"]["evidence"] = []
        with self.assertRaises(c.ContractError) as caught:
            c.validate_case_provenance(block)
        self.assertIn("CASE_PROVENANCE_CAUSE_NEEDS_EVIDENCE", caught.exception.codes)

    def test_an_absolute_path_locator_is_refused(self) -> None:
        block = self._block()
        block["fact"]["artefact"] = {"root": "ENGINE", "path": str(ROOT / "tools/burned_text_cover.py")}
        with self.assertRaises(c.ContractError) as caught:
            c.validate_case_provenance(block)
        self.assertIn("CASE_PROVENANCE_LOCATOR_PATH_INVALID:fact.artefact", caught.exception.codes)

    def test_provenance_rides_on_the_existing_receipt(self) -> None:
        receipt = adoption.selected(identity={"tenant_id": "t", "line_id": "l", "device_id": "d",
                                              "run_id": "t.l.E01"},
                                    rule={"rule_id": "R-X", "rule_version": 1}, stage="S7", unit_ids=[],
                                    entrypoint="t", bundle_digest="a" * 64)
        receipt["provenance"] = self._block()
        c.validate_adoption(receipt)
        receipt["provenance"]["cause"]["evidence"] = []
        with self.assertRaises(c.ContractError):
            c.validate_adoption(receipt)


class ConsumptionHonestyTest(unittest.TestCase):
    def test_replay_only_cannot_list_a_consumer_run(self) -> None:
        block = {"status": "CONSUMED_BY_REPLAY_ONLY", "reason": "free replay", "consumer_runs": [
            {"run_id": "E14.S7", "output_sha256": "a" * 64, "clause_present": True,
             "after_rule_recorded": True}]}
        with self.assertRaises(c.ContractError) as caught:
            c.validate_adoption(self._receipt(block))
        self.assertIn("CONSUMER_RUNS_LISTED_UNDER:CONSUMED_BY_REPLAY_ONLY", caught.exception.codes)

    def test_not_yet_consumed_needs_a_reason_and_is_accepted(self) -> None:
        c.validate_adoption(self._receipt({"status": "NOT_YET_CONSUMED_BY_REAL_RUN", "reason": "no later run"}))
        with self.assertRaises(c.ContractError) as caught:
            c.validate_adoption(self._receipt({"status": "NOT_YET_CONSUMED_BY_REAL_RUN"}))
        self.assertIn("CONSUMPTION_REASON_REQUIRED:NOT_YET_CONSUMED_BY_REAL_RUN", caught.exception.codes)

    def test_a_consumer_run_must_postdate_the_rule_and_carry_the_clause(self) -> None:
        good = {"run_id": "E14.S7", "output_sha256": "a" * 64, "clause_present": True,
                "after_rule_recorded": True}
        c.validate_adoption(self._receipt({"status": "CONSUMED_BY_REAL_RUN", "consumer_runs": [good]}))
        for field, code in (("clause_present", "CONSUMER_RUN_CLAUSE_NOT_PRESENT:0"),
                            ("after_rule_recorded", "CONSUMER_RUN_PREDATES_RULE_RECORD:0")):
            bad = {**good, field: False}
            with self.assertRaises(c.ContractError) as caught:
                c.validate_adoption(self._receipt({"status": "CONSUMED_BY_REAL_RUN", "consumer_runs": [bad]}))
            self.assertIn(code, caught.exception.codes)

    @staticmethod
    def _receipt(block: dict) -> dict:
        receipt = adoption.selected(identity={"tenant_id": "t", "line_id": "l", "device_id": "d",
                                              "run_id": "t.l.E01"},
                                    rule={"rule_id": "R-X", "rule_version": 1}, stage="S7", unit_ids=[],
                                    entrypoint="t", bundle_digest="a" * 64)
        receipt["real_run_consumption"] = block
        return receipt


# --------------------------------------------------------------------------- the real case
class RealCase001Test(unittest.TestCase):
    """E13's real artefacts.  Skips where they do not exist; never passes on a fixture."""

    def setUp(self) -> None:
        roots = real_roots()
        if roots is None:
            self.skipTest("E13 artefacts are not on this machine: a real case cannot be proven here")
        self.roots = roots
        self.spec = json.loads(CASE_SPEC.read_text(encoding="utf-8"))

    def test_spec_artefacts_still_hash_to_what_it_claims(self) -> None:
        check = klc.check_spec(self.spec, self.roots)
        self.assertEqual(check["drift"], [], "a cited artefact changed; the case record must be re-measured")
        self.assertTrue(check["rule_clause_at_declared_line"])

    def test_recorded_artifacts_replay_with_and_without_the_rule(self) -> None:
        """The named assertion in the case: PASS with the rule, FAIL on the same rows without it."""
        with_rule = klc.run_gate(self.spec, self.roots, with_rule=True)
        without = klc.run_gate(self.spec, self.roots, with_rule=False)

        self.assertEqual(with_rule["status"], "PASS")
        self.assertEqual(with_rule["text_outside_bar"], [])
        self.assertEqual(with_rule["text_inside_bar_not_the_caption"], [])
        self.assertEqual(len(with_rule["ignored_non_dialogue_text"]), 8)
        self.assertEqual({row["text"] for row in with_rule["ignored_non_dialogue_text"]},
                         {"猿明", "核志明", "裱走明游"})

        self.assertEqual(without["status"], "FAIL")
        self.assertEqual(sorted(row["text"] for row in without["text_outside_bar"]),
                         sorted(self.spec["provenance"]["verification"]["before"]["expected_failing_rows"]))
        # the plaque rows that fail are the SAME rows the rule ignores -- not a different set
        self.assertEqual(sorted(row["text"] for row in without["text_outside_bar"]),
                         sorted(row["text"] for row in with_rule["ignored_non_dialogue_text"]))

        clause = self.spec["provenance"]["rule_source"]["clause"]
        self.assertIn(clause, klc.canonical(with_rule))
        self.assertNotIn(clause, klc.canonical(without))

    def test_case_states_reach_verified_but_never_claim_production_adoption(self) -> None:
        state_dir = Path(tempfile.mkdtemp())
        klc.record_states(self.spec, self.roots, state_dir)
        receipt = klc.verify(self.spec, self.roots, state_dir)
        consumer = klc.consumer_receipt(self.spec, self.roots, state_dir)

        self.assertEqual(receipt["state"], "VERIFIED")
        self.assertFalse(receipt["outcome_observed"])  # no generated media, so no OUTCOME_OBSERVED
        self.assertFalse(consumer["production_adoption"])
        self.assertEqual(consumer["real_run_consumption"]["status"], "NOT_YET_CONSUMED_BY_REAL_RUN")
        self.assertEqual(consumer["real_run_consumption"]["consumer_runs"], [])
        self.assertTrue(consumer["with_rule"]["clause_present"])
        self.assertFalse(consumer["without_rule"]["clause_present"])
        states = json.loads((state_dir / klc.STATE_FILE).read_text(encoding="utf-8"))["receipts"]
        self.assertNotIn("OUTCOME_OBSERVED", [row["state"] for row in states])
        self.assertEqual(adoption.strongest_state(states, self.spec["rule"]["rule_id"]), "VERIFIED")

    def test_a_case_spec_may_not_carry_demo_fixtures(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["demo_fixtures"] = {"note": "fixtures belong in the report's demo section, not in the record"}
        with self.assertRaises(klc.CaseError):
            klc.check_spec(spec, self.roots)

    def test_the_without_rule_arm_must_reproduce_the_recorded_failing_rows(self) -> None:
        """The control is not "it failed somehow": it must fail on those exact rows.

        (An earlier draft read the wrong key here and skipped the check entirely, so this test
        exists to keep the row comparison load-bearing.)
        """
        without = klc.run_gate(self.spec, self.roots, with_rule=False)
        klc.assert_restores_earlier_output(self.spec, self.roots, without)
        wrong = copy.deepcopy(self.spec)
        wrong["provenance"]["verification"]["before"]["expected_failing_rows"] = ["猿明"]
        with self.assertRaises(klc.CaseError) as caught:
            klc.assert_restores_earlier_output(wrong, self.roots, without)
        self.assertIn("CASE_WITHOUT_RULE_ROWS_MISMATCH", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
