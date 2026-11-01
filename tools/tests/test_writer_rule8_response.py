"""Rule 8 must-respond list, and the honest S1 handoff status under LEGACY.

Rule 8's own findings are read from a seq29-shaped report (the real selfcheck's
schema).  The episode evidence (shot/scene ids) is invented here; no episode text
from any production is used.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.writer_rule8_response import (
    CONFIG_PATH,
    Evidence,
    evaluate,
    load_config,
)

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"

CONTRACT = {
    "episode": "E14",
    "scene_states": [{"scene_id": "E14-S01"}, {"scene_id": "E14-S02"}],
    "shots": [
        {"shot_id": "E14-S01-01", "scene_id": "E14-S01"},
        {"shot_id": "E14-S02-01", "scene_id": "E14-S02"},
    ],
}

NARRATIVE = """## E14-S01｜LOC-GATE｜TIME-NIGHT｜线A

她走到门口，门已经关了。

## E14-S02｜LOC-SIDE-DOOR｜TIME-NIGHT｜线A

侧门虚掩着。
"""


def report(**override) -> dict:
    payload = {
        "schema": "nalu.writer_selfcheck_seq29.v1",
        "episode": "E14",
        "enforced": True,
        "rule8_authorized": False,
        "status": "PASS",
        "failures": [],
        "warnings": [
            "RULE8_NOT_AUTHORISED_INFO:R8A_PRESSURE_SOURCE_LATE:112.0",
            "RULE8_NOT_AUTHORISED_INFO:R8A_PRESSURE_SOURCE_NOT_CONCRETE:THREAT",
            "RULE8_NOT_AUTHORISED_INFO:R8B_EPISODE_PAYOFF_MISSING",
        ],
        "measurements": {},
    }
    payload.update(override)
    return payload


def evidence() -> Evidence:
    return Evidence(NARRATIVE, CONTRACT)


def cited(item: str, ids: list[str], reason: str = "the guard blocks her at the gate") -> dict:
    return {"item_id": item, "answer": "CITED", "reason": reason, "evidence_ids": ids}


class ConfigTests(unittest.TestCase):
    def test_blocking_is_off_in_the_committed_config(self):
        self.assertFalse(load_config()["blocking"])

    def test_a_missing_config_reports_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(Path(tmp) / "absent.json")
        self.assertIs(config["blocking"], False)
        self.assertTrue(config["missing_config"])

    def test_the_config_lists_the_three_rule8_items(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(sorted(config["items"]), ["R8A", "R8B", "R8C"])


class PendingReportTests(unittest.TestCase):
    def test_every_rule8_item_is_listed_and_open(self):
        result = evaluate(report(), evidence())
        self.assertEqual([row["item_id"] for row in result["rows"]], ["R8A", "R8B", "R8C"])
        self.assertEqual(result["open_items"], ["R8A", "R8B", "R8C"])
        self.assertEqual(result["status"], "PENDING_WRITER_RESPONSE")

    def test_the_residue_codes_of_the_report_are_attached_to_their_item(self):
        result = evaluate(report(), evidence())
        r8a = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertIn("R8A_PRESSURE_SOURCE_LATE:112.0", r8a["selfcheck_codes"])
        self.assertIn("R8A_PRESSURE_SOURCE_NOT_CONCRETE:THREAT", r8a["selfcheck_codes"])

    def test_an_authorised_rule8_failure_is_read_too(self):
        result = evaluate(report(failures=["R8C_ACTION_CHAIN_MISSING"], warnings=[]), evidence())
        r8c = next(row for row in result["rows"] if row["item_id"] == "R8C")
        self.assertIn("R8C_ACTION_CHAIN_MISSING", r8c["selfcheck_codes"])

    def test_a_clean_report_still_asks_for_the_three_items(self):
        # line owner 2026-11-01: Rule 8 is MUST-RESPOND, not "respond if flagged".
        result = evaluate(report(failures=[], warnings=[]), evidence())
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["open_items"], ["R8A", "R8B", "R8C"])
        self.assertEqual(result["status"], "PENDING_WRITER_RESPONSE")

    def test_nothing_is_blocked_by_default(self):
        result = evaluate(report(), evidence())
        self.assertFalse(result["blocking_enabled"])
        self.assertNotEqual(result["status"], "BLOCKED")


class CitationTests(unittest.TestCase):
    def test_a_cited_shot_id_resolves(self):
        result = evaluate(report(), evidence(), {"items": [cited("R8A", ["E14-S01-01"])]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertEqual(row["status"], "ANSWERED")
        self.assertEqual(row["resolved_evidence"], ["shot_id:E14-S01-01"])

    def test_a_cited_scene_id_resolves(self):
        result = evaluate(report(), evidence(), {"items": [cited("R8B", ["E14-S02"])]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8B")
        self.assertEqual(row["status"], "ANSWERED")
        self.assertEqual(row["resolved_evidence"], ["scene_id:E14-S02"])

    def test_a_made_up_id_fails(self):
        result = evaluate(report(), evidence(), {"items": [cited("R8A", ["E14-S09-99"])]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertEqual(row["status"], "INVALID")
        self.assertTrue(any(code.startswith("RULE8_EVIDENCE_UNRESOLVED:R8A")
                            for code in result["failures"]))
        self.assertIn("R8A", result["invalid_items"])

    def test_citing_without_any_id_is_invalid(self):
        result = evaluate(report(), evidence(),
                          {"items": [{"item_id": "R8A", "answer": "CITED",
                                      "reason": "it is obvious from the scene"}]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertEqual(row["status"], "INVALID")
        self.assertEqual(row["reason"], "CITED_WITHOUT_EVIDENCE_IDS")

    def test_one_good_and_one_bad_id_still_fails(self):
        result = evaluate(report(), evidence(),
                          {"items": [cited("R8A", ["E14-S01-01", "E14-S01-77"])]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertEqual(row["status"], "INVALID")

    def test_not_applicable_needs_a_reason(self):
        result = evaluate(report(), evidence(), {"items": [
            {"item_id": "R8C", "answer": "NOT_APPLICABLE",
             "reason": "a single-scene episode with no opposing side"}]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8C")
        self.assertEqual(row["status"], "NOT_APPLICABLE")
        self.assertIsNone(row["answer"] if row["status"] != "NOT_APPLICABLE" else None)

    def test_not_applicable_without_a_reason_is_invalid(self):
        result = evaluate(report(), evidence(),
                          {"items": [{"item_id": "R8C", "answer": "NOT_APPLICABLE",
                                      "reason": "n/a"}]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8C")
        self.assertEqual(row["status"], "INVALID")

    def test_an_unknown_answer_kind_is_invalid(self):
        result = evaluate(report(), evidence(),
                          {"items": [{"item_id": "R8A", "answer": "MAYBE",
                                      "reason": "the pressure arrives from the weather"}]})
        row = next(row for row in result["rows"] if row["item_id"] == "R8A")
        self.assertEqual(row["status"], "INVALID")

    def test_answering_everything_clears_the_list(self):
        responses = {"items": [cited("R8A", ["E14-S01-01"]),
                               cited("R8B", ["E14-S02"]),
                               cited("R8C", ["E14-S01-01", "E14-S02"])]}
        result = evaluate(report(), evidence(), responses)
        self.assertEqual(result["status"], "ANSWERED")
        self.assertEqual(result["open_items"], [])


class BlockingTests(unittest.TestCase):
    def test_the_switch_blocks_only_when_it_is_on(self):
        off = evaluate(report(), evidence(), {"items": []}, config={"blocking": False})
        self.assertEqual(off["status"], "PENDING_WRITER_RESPONSE")
        on = evaluate(report(), evidence(), {"items": []}, config={"blocking": True})
        self.assertEqual(on["status"], "BLOCKED")

    def test_a_non_boolean_switch_does_not_block(self):
        result = evaluate(report(), evidence(), {"items": []},
                          config={"blocking": "yes"})
        self.assertNotEqual(result["status"], "BLOCKED")

    def test_a_fully_answered_episode_is_not_blocked_even_with_the_switch_on(self):
        responses = {"items": [cited("R8A", ["E14-S01-01"]), cited("R8B", ["E14-S02"]),
                               cited("R8C", ["E14-S01-01"])]}
        result = evaluate(report(), evidence(), responses, config={"blocking": True})
        self.assertEqual(result["status"], "ANSWERED")

    def test_the_note_refuses_to_ask_for_more_conflict(self):
        result = evaluate(report(), evidence())
        self.assertIn("nothing here asks for more conflict", result["note"])


def _load_pipeline():
    tmp = tempfile.mkdtemp(prefix="nalu-capability-wiring-")
    with patch.dict(os.environ, {"NALU_ENGINE_ROOT": str(ROOT), "NALU_RUNTIME_ROOT": tmp}):
        for name in ("nalu_paths", "nalu_policy_profile", "nalu_pipeline"):
            sys.modules.pop(name, None)
        sys.path.insert(0, str(TOOLS))
        return importlib.import_module("nalu_pipeline")


class S1WiringTests(unittest.TestCase):
    """The capability record is wired next to the S1 evidence; it never decides."""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = _load_pipeline()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_s1_records_the_writer_capability_profile_without_raising(self):
        class _P:
            def __init__(self, work, narrative):
                self.work = work
                self.narrative = narrative

        class _Ctx:
            def __init__(self, episode):
                self.episode = episode

        work = self.tmp / "work" / "E12"
        legacy = self.pipeline.writer_capability_record(_Ctx("E12"), _P(work, None))
        self.assertEqual(legacy["status"], "NOT_APPLICABLE_LEGACY_PROFILE")
        work = self.tmp / "work" / "E14"
        selected = self.pipeline.writer_capability_record(_Ctx("E14"), _P(work, None))
        self.assertEqual(selected["profile"], "WRITER_CAPABILITY_V1")
        self.assertEqual(selected["status"], "OWED")
        self.assertEqual(selected["blocks_stage"], [])

    def test_s1_receipt_carries_the_writer_capability_block(self):
        source = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"writer_capability": {', source)
        self.assertIn('res.details["writer_capability"] = writer_capability', source)

    def test_the_writer_capability_record_never_changes_the_stage_status(self):
        source = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        status_line = next(line for line in source.splitlines()
                           if line.strip().startswith("status = PASS if (writer_handoff_ok"))
        self.assertNotIn("writer_capability", status_line)

if __name__ == "__main__":
    unittest.main()
