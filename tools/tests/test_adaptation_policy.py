"""Per-episode adaptation disposition: categories, verbatim quotes, omission vs deferral.

The source chapter files here are INVENTED for the test.  No text from the novel
is used; the chapter layout mirrors what the line's source intake writes
(``sources/<work>/<reading_script>/chNNNN.md`` + ``SOURCE_INDEX.json``) because
that layout is what the verbatim check reads.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.adaptation_policy import (
    CATEGORIES,
    POLICY_PATH,
    default_decision,
    load_later_dependencies,
    load_policy,
    validate_disposition,
)

CHAPTER_ONE = """# 第一章 关门

她走到门口时，门已经关了。

守卫把手按在门上，没有让开的意思。

「天黑之前不开。」守卫说。

她没有回头，只是站着。
"""

CHAPTER_TWO = """# 第二章 侧门

侧门虚掩着。

她推了一下，门动了。

里面有人。
"""


def write_source(root: Path) -> Path:
    work = root / "sources" / "Fixture Work"
    (work / "zh-CN").mkdir(parents=True)
    (work / "zh-CN" / "ch0001.md").write_text(CHAPTER_ONE, encoding="utf-8")
    (work / "zh-CN" / "ch0002.md").write_text(CHAPTER_TWO, encoding="utf-8")
    (work / "SOURCE_INDEX.json").write_text(json.dumps({
        "schema": "nalu.source_index.v1",
        "work": "Fixture Work",
        "canonical_reading_script": "zh-CN (OpenCC t2s of the delivered text)",
    }), encoding="utf-8")
    return root / "sources"


def beat(beat_id: str, category: str, **extra) -> dict:
    row = {"beat_id": beat_id, "category": category, "source_ref": "ch0001",
           "reason": "kept the causal step that forces her into the side door"}
    row.update(extra)
    return row


def disposition(*beats, **override) -> dict:
    payload = {"schema": "qingshan.adaptation_disposition.v1", "episode": "E14",
               "chapter": "ch0001", "beats": list(beats) or [beat("B01", "condensed")]}
    payload.update(override)
    return payload


class PolicyDefaultTests(unittest.TestCase):
    def test_policy_file_is_the_committed_v1(self):
        policy = load_policy()
        self.assertEqual(policy["policy_id"], "ADAPTATION_POLICY_V1")
        self.assertEqual(policy["schema"], "qingshan.adaptation_policy.v1")

    def test_adapted_new_is_allowed_with_a_source_trace(self):
        # line owner 2026-11-01 replaced the draft's REQUIRES_LINE_OWNER default
        policy = load_policy()
        self.assertEqual(default_decision(policy, "adapted_new"), "ALLOWED_WITH_SOURCE_TRACE")

    def test_every_other_category_is_allowed(self):
        policy = load_policy()
        for name in ("verbatim", "condensed", "reorganized", "omitted", "deferred"):
            self.assertEqual(default_decision(policy, name), "ALLOWED", name)

    def test_major_change_escalates_to_the_line_owner(self):
        policy = load_policy()
        self.assertEqual(policy["major_change"]["escalation"], "LINE_OWNER")
        self.assertEqual(sorted(policy["major_change"]["change_kinds"]),
                         ["key_fact", "motive", "plot_outcome", "relationship"])

    def test_the_policy_carries_no_per_episode_line_cap(self):
        text = POLICY_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("max_new_lines", "max_lines", "line_cap", "per_episode_cap",
                          "max_adapted_new"):
            self.assertNotIn(forbidden, text)

    def test_bridging_work_is_named_as_not_major(self):
        policy = load_policy()
        joined = " ".join(policy["major_change"]["not_major"]).lower()
        self.assertIn("bridging dialogue", joined)
        self.assertIn("inner monologue", joined)


class CategoryTests(unittest.TestCase):
    def test_unknown_category_fails(self):
        report = validate_disposition(disposition(beat("B01", "rewritten")))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(code.startswith("CATEGORY_INVALID") for code in report["failures"]))

    def test_all_six_categories_are_accepted(self):
        rows = [beat(f"B{n:02d}", name, quote="「天黑之前不开。」" if name == "verbatim" else None,
                     trace="bridges the guard's refusal to her going round the side" if name == "adapted_new" else None,
                     planned_payoff_episode="E16" if name == "deferred" else None)
                for n, name in enumerate(CATEGORIES, 1)]
        report = validate_disposition(disposition(*rows))
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_missing_source_ref_fails(self):
        row = beat("B01", "condensed")
        del row["source_ref"]
        report = validate_disposition(disposition(row))
        self.assertIn("FIELD_MISSING:B01:source_ref", report["failures"])

    def test_missing_reason_fails(self):
        row = beat("B01", "condensed")
        del row["reason"]
        self.assertIn("FIELD_MISSING:B01:reason", validate_disposition(disposition(row))["failures"])

    def test_adapted_new_without_a_trace_fails(self):
        report = validate_disposition(disposition(beat("B01", "adapted_new")))
        self.assertIn("ADAPTED_NEW_TRACE_MISSING:B01", report["failures"])

    def test_adapted_new_with_a_trace_passes_without_escalation(self):
        report = validate_disposition(disposition(
            beat("B01", "adapted_new", trace="bridges the shut gate to the side door she tries")))
        self.assertEqual(report["status"], "PASS", report["failures"])


class VerbatimTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sources = write_source(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_exact_quote_passes(self):
        report = validate_disposition(
            disposition(beat("B01", "verbatim", quote="「天黑之前不开。」守卫说。")),
            sources_root=self.sources)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["measurements"]["verbatim_checked"], 1)

    def test_a_quote_that_is_not_in_the_chapter_fails(self):
        report = validate_disposition(
            disposition(beat("B01", "verbatim", quote="「天亮再开。」")),
            sources_root=self.sources)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(code.startswith("VERBATIM_QUOTE_NOT_IN_CHAPTER")
                            for code in report["failures"]), report["failures"])

    def test_a_quote_from_another_chapter_fails(self):
        report = validate_disposition(
            disposition(beat("B01", "verbatim", quote="侧门虚掩着。", source_ref="ch0001")),
            sources_root=self.sources)
        self.assertTrue(any(code.startswith("VERBATIM_QUOTE_NOT_IN_CHAPTER")
                            for code in report["failures"]))

    def test_a_wrapping_difference_is_a_warning_not_a_pass(self):
        # the intake writes one paragraph per line; the writer's quote may carry a
        # line break where the source has none.  Matched, but reported.
        report = validate_disposition(
            disposition(beat("B01", "verbatim", quote="「天黑之前不开。」\n守卫说。")),
            sources_root=self.sources)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertTrue(any("WHITESPACE_NORMALISATION" in code for code in report["warnings"]))
        self.assertEqual(report["rows"][0]["quote_match"], "WHITESPACE_NORMALISED")

    def test_verbatim_without_a_sources_root_is_reported_not_passed_silently(self):
        report = validate_disposition(disposition(beat("B01", "verbatim", quote="「天黑之前不开。」")))
        self.assertTrue(any(code.startswith("VERBATIM_NOT_CHECKED_NO_SOURCES_ROOT")
                            for code in report["warnings"]))

    def test_reading_script_comes_from_source_index(self):
        report = validate_disposition(
            disposition(beat("B01", "verbatim", quote="她把门推了一下")),
            sources_root=self.sources)
        # the quote does not exist in either chapter -> the checker really read zh-CN
        self.assertTrue(any(code.startswith("VERBATIM_QUOTE_NOT_IN_CHAPTER")
                            for code in report["failures"]))

    def test_a_missing_chapter_is_an_error_not_a_pass(self):
        with self.assertRaises(SystemExit):
            validate_disposition(
                disposition(beat("B01", "verbatim", quote="x", source_ref="ch0009")),
                sources_root=self.sources)


class OmissionTests(unittest.TestCase):
    def test_omitted_with_reason_passes_when_nothing_depends_on_it(self):
        report = validate_disposition(disposition(beat("B01", "omitted")))
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_omitting_a_beat_a_later_episode_depends_on_fails(self):
        report = validate_disposition(
            disposition(beat("B01", "omitted")),
            later_dependencies={"B01": ["E16"]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(code.startswith("OMITTED_BEAT_DEPENDED_ON_LATER:B01:E16")
                            for code in report["failures"]), report["failures"])

    def test_deferring_the_same_beat_instead_is_accepted(self):
        report = validate_disposition(
            disposition(beat("B01", "deferred", planned_payoff_episode="E16")),
            later_dependencies={"B01": ["E16"]})
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_deferred_needs_a_planned_episode_after_this_one(self):
        report = validate_disposition(disposition(beat("B01", "deferred")))
        self.assertIn("DEFERRED_PLANNED_EPISODE_MISSING:B01", report["failures"])
        report = validate_disposition(disposition(beat("B01", "deferred",
                                                       planned_payoff_episode="E14")))
        self.assertIn("DEFERRED_PLANNED_EPISODE_NOT_LATER:B01:E14", report["failures"])

    def test_later_dependencies_can_be_read_from_an_arc_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arc.json"
            path.write_text(json.dumps({"episodes": [
                {"episode": "E15", "chosen_events": [
                    {"event_id": "E15-EV-01", "depends_on": ["B01", "B02"]}]}]}),
                encoding="utf-8")
            deps = load_later_dependencies(path)
            self.assertEqual(deps, {"B01": ["E15"], "B02": ["E15"]})


class MajorChangeTests(unittest.TestCase):
    def test_a_major_change_needs_a_kind_description_and_escalation(self):
        report = validate_disposition(disposition(beat("B01", "adapted_new", trace="bridges",
                                                       major_change={})))
        self.assertIn("MAJOR_CHANGE_KIND_INVALID:B01:None", report["failures"])
        self.assertIn("MAJOR_CHANGE_DESCRIPTION_MISSING:B01", report["failures"])
        self.assertIn("MAJOR_CHANGE_NOT_ESCALATED:B01", report["failures"])

    def test_a_pending_escalation_naming_the_order_is_accepted(self):
        report = validate_disposition(disposition(beat(
            "B01", "adapted_new", trace="bridges the refusal to the side door",
            major_change={"change_kind": "motive",
                          "description": "the guard lets her through because he is her brother",
                          "escalation": {"authorization_order": "ORDER-2026-11-01-ARC14",
                                         "status": "PENDING"}})))
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["measurements"]["major_change_rows"], 1)

    def test_an_approved_escalation_needs_the_order_receipt(self):
        report = validate_disposition(disposition(beat(
            "B01", "adapted_new", trace="bridges",
            major_change={"change_kind": "plot_outcome",
                          "description": "the gate opens earlier than in the source",
                          "escalation": {"authorization_order": "ORDER-1",
                                         "status": "APPROVED"}})))
        self.assertIn("MAJOR_CHANGE_APPROVED_WITHOUT_RECEIPT:B01", report["failures"])

    def test_an_unknown_escalation_status_fails(self):
        report = validate_disposition(disposition(beat(
            "B01", "condensed",
            major_change={"change_kind": "relationship", "description": "they are siblings now",
                          "escalation": {"authorization_order": "O-1", "status": "PROBABLY"}})))
        self.assertTrue(any(code.startswith("MAJOR_CHANGE_ESCALATION_STATUS_INVALID")
                            for code in report["failures"]))


class ShapeTests(unittest.TestCase):
    def test_wrong_schema_fails(self):
        self.assertTrue(any(code.startswith("SCHEMA_INVALID")
                            for code in validate_disposition(disposition(schema="x"))["failures"]))

    def test_bad_episode_id_fails(self):
        self.assertTrue(any(code.startswith("EPISODE_INVALID")
                            for code in validate_disposition(disposition(episode="14"))["failures"]))

    def test_duplicate_beat_ids_fail(self):
        report = validate_disposition(disposition(beat("B01", "condensed"), beat("B01", "omitted")))
        self.assertIn("BEAT_ID_DUPLICATE:B01", report["failures"])

    def test_empty_beats_fails(self):
        self.assertIn("BEATS_MISSING", validate_disposition(disposition(beats=[]))["failures"])

    def test_no_verbatim_quote_text_is_required_to_live_in_the_repo(self):
        # the tool carries no source text; only a caller-supplied sources root has any.
        text = Path(__file__).resolve().parents[2].joinpath("tools/adaptation_policy.py").read_text(
            encoding="utf-8")
        self.assertNotIn("天黑之前不开", text)


if __name__ == "__main__":
    unittest.main()
