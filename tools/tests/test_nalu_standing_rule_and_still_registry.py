#!/usr/bin/env python3
"""Portable checks for the nalu line's standing-rule acceptance and still registry.

These live engine-side (and are named in PORTABLE_CORE_MANIFEST.portable_test_modules)
because that manifest is what a clean clone runs; the line's own tests directory is not
collected by it.  Both subjects are pure functions over paths and measurements, so they run
from a clone with no runtime, no network and no credentials.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import keyframe_q1_builder as kqb  # noqa: E402
import roger_gate_acceptance as rga  # noqa: E402

GATE = "CHARACTER-IDENTITY-ADMISSION"


class StandingRuleConditionTest(unittest.TestCase):
    """The rule covers Roger's by-design case, and refuses the four adjacent ones."""

    def _cond(self, failures, decisions, declared, gates=(GATE,)):
        return rga.standing_rule_condition(
            failed_gates=list(gates), identity_failures=list(failures), identity_gate_id=GATE,
            decisions=[{"character_id": c, "decision": d} for c, d in decisions.items()],
            declared_characters=list(declared))

    def test_covered(self):
        got = self._cond(["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING",
                          "DECLARED_CHARACTER_FACE_NOT_FOUND:E11-S01-01:CHAR-QINMING"],
                         {"CHAR-FENGYIAN": "PASS", "CHAR-QINMING": "FAIL"},
                         ["CHAR-FENGYIAN", "CHAR-QINMING"])
        self.assertTrue(got["covered"])
        self.assertEqual(got["excused_characters"], ["CHAR-QINMING"])

    def test_measured_low_similarity_is_never_covered(self):
        # the load-bearing refusal: a face that WAS measured and came back wrong
        got = self._cond(["IDENTITY_BELOW_FAIL_THRESHOLD:CHAR-QINMING"], {"CHAR-QINMING": "FAIL"},
                         ["CHAR-QINMING"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "NO_NO_FACE_PIXELS_FAILURE")

    def test_second_failing_gate_is_not_covered(self):
        got = self._cond(["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"],
                         {"CHAR-QINMING": "FAIL"}, ["CHAR-QINMING"],
                         gates=(GATE, "PERIOD-ANACHRONISM-LOCK"))
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "OTHER_REGISTERED_GATE_ALSO_FAILED")

    def test_unmeasured_declared_character_is_not_a_pass(self):
        got = self._cond(["NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING"],
                         {"CHAR-QINMING": "FAIL"}, ["CHAR-QINMING", "CHAR-FENGYIAN"])
        self.assertFalse(got["covered"])
        self.assertEqual(got["reason"], "OTHER_DECLARED_CHARACTER_NOT_MEASURED_PASS")

    def test_only_the_no_face_pixels_codes_are_readable(self):
        self.assertEqual(rga.no_face_pixels_character(
            "DECLARED_CHARACTER_FACE_NOT_FOUND:E11-S17-03:CHAR-XUYUEPING"), "CHAR-XUYUEPING")
        for code in ("IDENTITY_BELOW_FAIL_THRESHOLD:CHAR-Q",
                     "BOUNDARY_REQUIRES_HUMAN:CHAR-Q", "FACE_COUNT_NOT_ONE:CHAR-Q"):
            self.assertIsNone(rga.no_face_pixels_character(code), code)


class StandingRuleOrderTest(unittest.TestCase):
    """A rule only counts with a live receipt, the right scope, and the owner's own words."""

    def _order(self, tmp: Path, seq=40, **over):
        import hashlib
        receipt = tmp / f"r{seq}.json"
        receipt.write_text(json.dumps({
            "schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "Roger",
            "order_seq": seq, "order_id": f"O{seq}", "verbatim": "同意", "recorded_at_utc": "z"}),
            encoding="utf-8")
        row = {"seq": seq, "id": f"O{seq}", "issued_by": "Roger", "status": "active", "order": "同意",
               "decision": {"kind": "STANDING_RULE", "episode": "E11", "gate_id": GATE,
                            "auto_accept_scope": {"rule": rga.NO_FACE_PIXELS_SCOPE,
                                                  "criteria_verbatim": "前景人物背对镜头、无脸可测"}},
               "source_receipt": {"path": str(receipt),
                                  "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}}
        for key, value in over.items():
            row["decision"].update(value) if key == "decision" else row.update({key: value})
        return row

    def test_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNotNone(rga.find_standing_rule([self._order(Path(tmp))], episode="E11",
                                                        gate_id=GATE, expected_issuer="Roger"))

    def test_wrong_kind_scope_or_issuer_is_not_the_rule(self):
        cases = [{"decision": {"kind": "GATE_FAIL_ACCEPTANCE"}},
                 {"decision": {"auto_accept_scope": {"rule": "OTHER"}}},
                 {"decision": {"auto_accept_scope": {"criteria_verbatim": ""}}},
                 {"status": "revoked"}, {"issued_by": "someone-else"}, {"decision": {"episode": "E12"}}]
        for over in cases:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertIsNone(rga.find_standing_rule([self._order(Path(tmp), **over)], episode="E11",
                                                         gate_id=GATE, expected_issuer="Roger"), over)

    def test_record_is_not_the_per_item_schema_and_keeps_the_fail(self):
        order = {"seq": 41, "id": "O41", "issued_by": "Roger", "order": "同意",
                 "decision": {"auto_accept_scope": {"rule": rga.NO_FACE_PIXELS_SCOPE,
                                                    "criteria_verbatim": "背影无脸"}}}
        rec = rga.standing_rule_acceptance(order, episode="E11", gate_id=GATE,
                                           excused_detectors=["E11-S01-01:CHAR-QINMING"],
                                           condition={"covered": True}, media_sha256="a" * 64,
                                           gate_result_path="/tmp/r.json")
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertFalse(rec["self_issued"])
        self.assertIn("NOT_A_SHA_BINDING", rec["media_sha256_binding"])
        self.assertNotEqual(rec["schema"], "qingshan.line_owner_gate_acceptance.v2")


class StillRegistryTimestampTest(unittest.TestCase):
    """The committed registry must not churn on every Q1 run (D-13)."""

    def test_stable_when_unchanged_and_moves_on_real_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "reg.json"
            kqb.still_gate_registry(out=out)
            first = json.loads(out.read_text(encoding="utf-8"))
            time.sleep(1.1)
            kqb.still_gate_registry(out=out)
            self.assertEqual(first["derived_at"], json.loads(out.read_text(encoding="utf-8"))["derived_at"])
            payload = json.loads(out.read_text(encoding="utf-8"))
            payload["single_parameter_changed"] = {"different": True}
            out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            time.sleep(1.1)
            kqb.still_gate_registry(out=out)
            self.assertNotEqual(payload["derived_at"],
                                json.loads(out.read_text(encoding="utf-8"))["derived_at"])


if __name__ == "__main__":
    unittest.main()
