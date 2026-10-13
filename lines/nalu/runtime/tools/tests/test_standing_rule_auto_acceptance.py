#!/usr/bin/env python3
"""STANDING_RULE auto-acceptance (D-71): what it covers, and the four things it must not.

The point of the feature is that the line stops asking Roger to re-sign the same class of
by-design identity failure on every regenerated still.  The point of these tests is that it
did not become a way to wave identity problems through: the condition is re-derived from the
still's own measurements, and a measured low cosine, an unmeasured declared face, or a second
failing gate each still stops the line.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import roger_gate_acceptance as rga  # noqa: E402

GATE = "CHARACTER-IDENTITY-ADMISSION"


class NoFacePixelsCodeTest(unittest.TestCase):
    def test_both_shapes_read_the_character(self):
        self.assertEqual(rga.no_face_pixels_character(
            "NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"), "CHAR-QINMING")
        self.assertEqual(rga.no_face_pixels_character(
            "DECLARED_CHARACTER_FACE_NOT_FOUND:E11-S01-01:CHAR-XUYUEPING"), "CHAR-XUYUEPING")

    def test_a_measured_low_cosine_is_not_a_no_face_pixels_code(self):
        # The single most important line in the feature: a face that WAS measured and came back
        # wrong must never be readable as "no face here".  If this ever passes, the rule can
        # auto-accept identity drift and every other guard below is decoration.
        for code in ("IDENTITY_BELOW_FAIL_THRESHOLD:CHAR-QINMING",
                     "BOUNDARY_REQUIRES_HUMAN:CHAR-QINMING",
                     "COSINE_0.21_BELOW_0.30:CHAR-QINMING",
                     "FACE_COUNT_NOT_ONE:CHAR-QINMING"):
            self.assertIsNone(rga.no_face_pixels_character(code), code)

    def test_other_text_yields_nothing(self):
        self.assertIsNone(rga.no_face_pixels_character("SCENE-AUTHORITY-LOCK:FAIL"))
        self.assertIsNone(rga.no_face_pixels_character(""))


class ConditionTest(unittest.TestCase):
    """The four requirements, one test each, plus the covered case."""

    def _decisions(self, **by_char):
        return [{"character_id": cid, "decision": d} for cid, d in by_char.items()]

    def test_covered_when_only_no_face_failures_and_others_pass(self):
        got = rga.standing_rule_condition(
            failed_gates=[GATE],
            identity_failures=["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING",
                               "DECLARED_CHARACTER_FACE_NOT_FOUND:E11-S01-01:CHAR-QINMING"],
            identity_gate_id=GATE,
            decisions=self._decisions(**{"CHAR-FENGYIAN": "PASS", "CHAR-QINMING": "FAIL"}),
            declared_characters=["CHAR-FENGYIAN", "CHAR-QINMING"])
        self.assertTrue(got["covered"], got)
        self.assertEqual(got["excused_characters"], ["CHAR-QINMING"])
        self.assertEqual(got["other_declared_character_decisions"], {"CHAR-FENGYIAN": "PASS"})

    def test_measured_identity_failure_is_never_covered(self):
        got = rga.standing_rule_condition(
            failed_gates=[GATE], identity_failures=["BOUNDARY_REQUIRES_HUMAN:CHAR-QINMING"],
            identity_gate_id=GATE, decisions=self._decisions(**{"CHAR-QINMING": "FAIL"}),
            declared_characters=["CHAR-QINMING"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "NO_NO_FACE_PIXELS_FAILURE")

    def test_mixture_of_no_face_and_measured_failure_is_refused(self):
        # one character's face is genuinely absent, another's was measured wrong — the second
        # is a real identity problem, so the whole still goes to a human.
        got = rga.standing_rule_condition(
            failed_gates=[GATE],
            identity_failures=["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING",
                               "IDENTITY_BELOW_FAIL_THRESHOLD:CHAR-XUYUEPING"],
            identity_gate_id=GATE,
            decisions=self._decisions(**{"CHAR-QINMING": "FAIL", "CHAR-XUYUEPING": "FAIL"}),
            declared_characters=["CHAR-QINMING", "CHAR-XUYUEPING"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "MEASURED_IDENTITY_FAILURE_PRESENT")

    def test_a_second_failing_gate_stops_the_rule(self):
        got = rga.standing_rule_condition(
            failed_gates=[GATE, "PERIOD-ANACHRONISM-LOCK"],
            identity_failures=["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"],
            identity_gate_id=GATE, decisions=self._decisions(**{"CHAR-QINMING": "FAIL"}),
            declared_characters=["CHAR-QINMING"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "OTHER_REGISTERED_GATE_ALSO_FAILED")

    def test_unmeasured_other_character_is_not_a_pass(self):
        # "no decision" must not read as "fine": a declared face nobody measured is exactly the
        # gap the identity chain exists to catch.
        got = rga.standing_rule_condition(
            failed_gates=[GATE],
            identity_failures=["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"],
            identity_gate_id=GATE, decisions=self._decisions(**{"CHAR-QINMING": "FAIL"}),
            declared_characters=["CHAR-QINMING", "CHAR-FENGYIAN"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "OTHER_DECLARED_CHARACTER_NOT_MEASURED_PASS")
        self.assertEqual(got["other_declared_character_decisions"]["CHAR-FENGYIAN"], "NO_DECISION")

    def test_admit_best_effort_is_not_a_pass(self):
        got = rga.standing_rule_condition(
            failed_gates=[GATE],
            identity_failures=["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"],
            identity_gate_id=GATE,
            decisions=self._decisions(**{"CHAR-QINMING": "FAIL", "CHAR-FENGYIAN": "ADMIT_BEST_EFFORT"}),
            declared_characters=["CHAR-QINMING", "CHAR-FENGYIAN"])
        self.assertFalse(got["covered"])


class OrderSelectionTest(unittest.TestCase):
    """A rule only counts when the owner actually signed it, with a live receipt, for this scope."""

    def _order(self, tmp: Path, seq=40, **over):
        receipt = tmp / f"r{seq}.json"
        receipt.write_text(json.dumps({
            "schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "Roger",
            "order_seq": seq, "order_id": f"O{seq}", "verbatim": "同意", "recorded_at_utc": "z"}),
            encoding="utf-8")
        import hashlib
        row = {
            "seq": seq, "id": f"O{seq}", "issued_by": "Roger", "status": "active", "order": "同意",
            "decision": {"kind": "STANDING_RULE", "episode": "E11", "gate_id": GATE,
                         "auto_accept_scope": {"rule": rga.NO_FACE_PIXELS_SCOPE,
                                               "criteria_verbatim": "前景人物背对镜头、无脸可测"}},
            "source_receipt": {"path": str(receipt),
                               "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()},
        }
        for key, value in over.items():
            if key == "decision":
                row["decision"].update(value)
            elif key == "scope":
                row["decision"]["auto_accept_scope"].update(value)
            else:
                row[key] = value
        return row

    def test_finds_the_active_receipted_rule(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp))]
            got = rga.find_standing_rule(rows, episode="E11", gate_id=GATE, expected_issuer="Roger")
            self.assertIsNotNone(got)

    def test_wrong_scope_name_is_not_the_rule(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp), scope={"rule": "SOMETHING_ELSE"})]
            self.assertIsNone(rga.find_standing_rule(rows, episode="E11", gate_id=GATE,
                                                     expected_issuer="Roger"))

    def test_missing_criteria_is_not_the_rule(self):
        # the order must say what was authorised; a bare scope name is not a decision
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp), scope={"criteria_verbatim": ""})]
            self.assertIsNone(rga.find_standing_rule(rows, episode="E11", gate_id=GATE,
                                                     expected_issuer="Roger"))

    def test_not_a_standing_rule_kind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp), decision={"kind": "GATE_FAIL_ACCEPTANCE"})]
            self.assertIsNone(rga.find_standing_rule(rows, episode="E11", gate_id=GATE,
                                                     expected_issuer="Roger"))

    def test_revoked_or_foreign_order_does_not_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for over in ({"status": "revoked"}, {"issued_by": "someone-else"}):
                rows = [self._order(Path(tmp), **over)]
                self.assertIsNone(rga.find_standing_rule(rows, episode="E11", gate_id=GATE,
                                                         expected_issuer="Roger"), over)

    def test_other_episode_does_not_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp), decision={"episode": "E12"})]
            self.assertIsNone(rga.find_standing_rule(rows, episode="E11", gate_id=GATE,
                                                     expected_issuer="Roger"))

    def test_newest_rule_wins(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rows = [self._order(Path(tmp), seq=40), self._order(Path(tmp), seq=41)]
            got = rga.find_standing_rule(rows, episode="E11", gate_id=GATE, expected_issuer="Roger")
            self.assertEqual(got["seq"], 41)


class AcceptanceRecordTest(unittest.TestCase):
    def test_record_keeps_the_fail_and_says_the_sha_is_not_the_binding(self):
        order = {"seq": 41, "id": "O41", "issued_by": "Roger", "order": "同意",
                 "decision": {"auto_accept_scope": {"rule": rga.NO_FACE_PIXELS_SCOPE,
                                                    "criteria_verbatim": "前景人物背对镜头、无脸可测"}}}
        rec = rga.standing_rule_acceptance(order, episode="E11", gate_id=GATE,
                                           excused_detectors=["E11-S01-01:CHAR-QINMING"],
                                           condition={"covered": True}, media_sha256="a" * 64,
                                           gate_result_path="/tmp/r.json", media_item_id="E11-S01-01")
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertFalse(rec["self_issued"])
        self.assertEqual(rec["order_seq"], 41)
        self.assertEqual(rec["rule_criteria_verbatim"], "前景人物背对镜头、无脸可测")
        self.assertIn("NOT_A_SHA_BINDING", rec["media_sha256_binding"])
        # and it must not masquerade as the per-item acceptance schema
        self.assertNotEqual(rec["schema"], "qingshan.line_owner_gate_acceptance.v2")


if __name__ == "__main__":
    unittest.main()
