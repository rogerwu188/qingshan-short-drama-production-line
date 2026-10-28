"""tools/knowledge_event_log.py on synthetic fixtures (offline, no real episode touched).

Codex knowledge-loop audit 2026-10-27, gap 1: a review/fix event had no formal
producer that registered it before a human/agent decided to author a knowledge
candidate for it.  These tests prove: (a) recording an event never sets a root
cause -- attribution starts and stays UNATTRIBUTED until a separate call, (b)
attribution requires an explicit, non-empty root_cause and refuses to be a
silent no-op, (c) a reviewed-but-inconclusive event is distinguishable from a
never-reviewed one, (d) corrections are visible (attribution_history), and
(e) nothing here ever derives a cause from the symptom string itself.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import knowledge_event_log as kel


class RecordEventTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_record_requires_concrete_fields(self) -> None:
        base = dict(episode="E12", line="nalu", stage="S6", symptom="x",
                    evidence={"gate": "g"}, detected_by="claude-code-nalu-vlm")
        for missing, bad in (("episode", ""), ("stage", ""), ("symptom", "   "),
                             ("detected_by", "")):
            kwargs = dict(base)
            kwargs[missing] = bad
            with self.assertRaises(ValueError, msg=missing):
                kel.record_event(self.tmp, **kwargs)
        with self.assertRaises(ValueError):
            kel.record_event(self.tmp, **{**base, "evidence": {}})
        with self.assertRaises(ValueError):
            kel.record_event(self.tmp, **{**base, "evidence": None})

    def test_recorded_event_is_always_unattributed(self) -> None:
        row = kel.record_event(
            self.tmp, episode="E12", line="nalu", stage="S6",
            symptom="post_generation_qa basic_plot_qa FAIL: principal_character_presence",
            evidence={"gate": "POST-GENERATION-QA-ADMISSION", "media_sha256": "ab" * 32},
            detected_by="claude-code-nalu-vlm", unit_ids=["E12-VU-028"])
        self.assertEqual(row["attribution"], {"status": "UNATTRIBUTED"})
        self.assertEqual(row["attribution_history"], [])
        self.assertEqual(row["unit_ids"], ["E12-VU-028"])
        self.assertEqual(row["schema"], kel.SCHEMA)
        path = kel.events_path(self.tmp)
        self.assertTrue(path.is_file())
        self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_record_event_signature_has_no_root_cause_parameter(self) -> None:
        """Structural guard: recording a fact must never also be able to set a
        cause. If this ever starts passing because someone added the
        parameter, that is the regression this test exists to catch."""
        import inspect
        params = inspect.signature(kel.record_event).parameters
        self.assertNotIn("root_cause", params)
        self.assertNotIn("candidate_rule_id", params)

    def test_events_are_appended_not_overwritten(self) -> None:
        for i in range(3):
            kel.record_event(self.tmp, episode="E12", line="nalu", stage="S6",
                             symptom=f"symptom {i}", evidence={"i": i}, detected_by="x")
        rows = kel.events(self.tmp, episode="E12")
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["symptom"] for r in rows], ["symptom 0", "symptom 1", "symptom 2"])
        # event_id ordinal is per-episode and stable
        self.assertTrue(all(row["event_id"].startswith("EVT-E12-S6-") for row in rows))

    def test_separate_episodes_do_not_share_ordinals_or_leak(self) -> None:
        kel.record_event(self.tmp, episode="E12", line="nalu", stage="S6",
                         symptom="s", evidence={"a": 1}, detected_by="x")
        kel.record_event(self.tmp, episode="E13", line="nalu", stage="S6",
                         symptom="s", evidence={"a": 1}, detected_by="x")
        self.assertEqual(len(kel.events(self.tmp, episode="E12")), 1)
        self.assertEqual(len(kel.events(self.tmp, episode="E13")), 1)
        self.assertEqual(len(kel.events(self.tmp)), 2)


class AttributionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.row = kel.record_event(
            self.tmp, episode="E12", line="nalu", stage="S6", symptom="WRONG_CHARACTER_IN_FRAME",
            evidence={"gate": "POST-GENERATION-QA-ADMISSION"}, detected_by="claude-code-nalu-vlm")
        self.event_id = self.row["event_id"]

    def test_attribution_requires_nonempty_root_cause(self) -> None:
        with self.assertRaises(ValueError):
            kel.attribute_event(self.tmp, self.event_id, root_cause="   ", attributed_by="cc")
        with self.assertRaises(ValueError):
            kel.attribute_event(self.tmp, self.event_id, root_cause="", attributed_by="cc")
        # still unattributed after the refused calls
        rows = kel.events(self.tmp, episode="E12")
        self.assertEqual(rows[0]["attribution"]["status"], "UNATTRIBUTED")

    def test_attribution_requires_attributed_by_and_valid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            kel.attribute_event(self.tmp, self.event_id, root_cause="x", attributed_by="")
        with self.assertRaises(ValueError):
            kel.attribute_event(self.tmp, self.event_id, root_cause="x", attributed_by="cc",
                                confidence="VERY_SURE")

    def test_successful_attribution_is_recorded_and_queryable(self) -> None:
        updated = kel.attribute_event(
            self.tmp, self.event_id,
            root_cause="OTS reaction shot had no second-person exclusion clause; model hallucinated"
                       " a bearded extra in Qinming's declared slot",
            attributed_by="claude-code-nalu-vlm", candidate_rule_id="K-PENDING", confidence="HIGH")
        self.assertEqual(updated["attribution"]["status"], "ATTRIBUTED")
        self.assertEqual(updated["attribution"]["confidence"], "HIGH")
        self.assertEqual(updated["attribution"]["candidate_rule_id"], "K-PENDING")
        self.assertEqual(updated["attribution_history"], [{"status": "UNATTRIBUTED"}])
        attributed = kel.events(self.tmp, episode="E12", status="ATTRIBUTED")
        self.assertEqual(len(attributed), 1)
        self.assertEqual(kel.unattributed(self.tmp, episode="E12"), [])

    def test_attributing_unknown_event_id_fails(self) -> None:
        with self.assertRaises(ValueError):
            kel.attribute_event(self.tmp, "EVT-NOPE", root_cause="x", attributed_by="cc")

    def test_inconclusive_is_distinct_from_unattributed(self) -> None:
        kel.mark_inconclusive(self.tmp, self.event_id,
                              reason="checked wardrobe, lighting and identity plates; no single"
                                     " cause isolated before the reroll budget ran out",
                              attributed_by="claude-code-nalu-vlm")
        rows = kel.events(self.tmp, episode="E12")
        self.assertEqual(rows[0]["attribution"]["status"], "INCONCLUSIVE")
        self.assertEqual(kel.unattributed(self.tmp, episode="E12"), [])
        self.assertEqual(kel.events(self.tmp, episode="E12", status="INCONCLUSIVE"), rows)

    def test_inconclusive_requires_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            kel.mark_inconclusive(self.tmp, self.event_id, reason="", attributed_by="cc")

    def test_re_attribution_keeps_history_not_just_the_latest(self) -> None:
        kel.mark_inconclusive(self.tmp, self.event_id, reason="first pass unclear", attributed_by="cc")
        kel.attribute_event(self.tmp, self.event_id, root_cause="found it on second pass",
                            attributed_by="cc", confidence="MEDIUM")
        rows = kel.events(self.tmp, episode="E12")
        history = rows[0]["attribution_history"]
        self.assertEqual([h["status"] for h in history], ["UNATTRIBUTED", "INCONCLUSIVE"])
        self.assertEqual(rows[0]["attribution"]["root_cause"], "found it on second pass")


class NoAutomaticInferenceTest(unittest.TestCase):
    """The audit's central complaint: a failure must never be silently turned
    into a cause. These assert the module provides no path to do that."""

    def test_module_has_no_function_mapping_symptom_to_cause(self) -> None:
        import re as _re
        source = Path(kel.__file__).read_text(encoding="utf-8")
        # No FAIL-code -> rule/cause lookup table of the kind knowledge_sync_core.py
        # explicitly rejected building (candidates_from_evidence's docstring).
        self.assertNotRegex(source, r"CAUSE_(BY|FROM)_|SYMPTOM_TO_CAUSE|_INFER_ROOT_CAUSE")

    def test_attribute_event_never_reads_the_symptom_field(self) -> None:
        """record a symptom that LOOKS like a ready-made cause string, then
        attribute with an unrelated cause, and confirm the attribution is
        exactly what was passed -- nothing in the symptom leaked in."""
        tmp = Path(tempfile.mkdtemp())
        row = kel.record_event(tmp, episode="E12", line="nalu", stage="S6",
                               symptom="OBVIOUS_ROOT_CAUSE_LOOKING_STRING",
                               evidence={"g": 1}, detected_by="x")
        updated = kel.attribute_event(tmp, row["event_id"], root_cause="unrelated real cause",
                                      attributed_by="cc")
        self.assertEqual(updated["attribution"]["root_cause"], "unrelated real cause")
        self.assertNotIn("OBVIOUS_ROOT_CAUSE_LOOKING_STRING", json.dumps(updated["attribution"]))


class CorruptLogTest(unittest.TestCase):
    def test_corrupt_line_raises_instead_of_silently_dropping_rows(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        path = kel.events_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"event_id": "EVT-1"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            kel.events(tmp)


if __name__ == "__main__":
    unittest.main()
