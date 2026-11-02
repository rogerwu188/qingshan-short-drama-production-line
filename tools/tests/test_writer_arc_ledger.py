"""Arc plan + hook/payoff ledger: every required field present, every hook listed.

The fixtures invent their own place/chapter names.  No text from the novel and no
episode text is used anywhere in this file.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.writer_arc_ledger import (
    SCHEMA,
    SCHEMA_PATH,
    load,
    report_status,
    validate,
)

ROOT = Path(__file__).resolve().parents[2]


def beat(event_id: str, **extra) -> dict:
    return {"event_id": event_id, "summary": "the gate is shut and nobody says why", **extra}


def card(scene_id: str) -> dict:
    return {"scene_id": scene_id, "want": "get out before dark", "obstacle": "the gate is shut",
            "action": "she tries the side door", "change": "she is seen",
            "why_keep": "it is the first time anyone looks at her"}


def episode(name: str, **override) -> dict:
    """A clean episode.  ``hook`` names the hook its payoff settles, so a test that
    replaces the hook list must pass the same name here."""
    row = {
        "episode": name,
        "source_ref": [f"ch01{int(name[1:])}:p03"],
        "chosen_events": [beat(f"{name}-EV-01")],
        "delivered_experience": "she learns the gate is watched",
        "end_question": "who shut it",
        "payoff_plan": [{"payoff_id": f"PO-{name}-1", "settles": override.pop("hook", "HOOK-GATE"),
                         "delivered_in": name}],
        "scene_cards": [card(f"{name}-S01")],
    }
    row.update(override)
    return row


def ledger(**override) -> dict:
    payload = {
        "schema": SCHEMA,
        "policy": "WRITER_CAPABILITY_V1",
        "arc_id": "ARC-GATE-V1",
        "episode_window": ["E14", "E15", "E16"],
        "episodes": [episode("E14"), episode("E15"), episode("E16")],
        "hooks": [{"id": "HOOK-GATE", "status": "PAID_OFF", "kind": "discovery",
                   "opened_in": "E14", "progress": "she finds the watcher",
                   "payoff": "the watcher is her brother", "paid_off_in": "E16"}],
        "open_hooks_at_arc_end": [],
    }
    payload.update(override)
    return payload


class CleanLedgerTests(unittest.TestCase):
    def test_minimal_arc_passes(self):
        report = validate(ledger())
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["measurements"]["episode_count"], 3)

    def test_schema_file_is_json_and_matches_the_validator_constant(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], SCHEMA)
        self.assertEqual(sorted(schema["required"]),
                         sorted(["schema", "arc_id", "episode_window", "episodes", "hooks"]))

    def test_the_schema_enumerates_exactly_the_hook_statuses(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        status = schema["properties"]["hooks"]["items"]["properties"]["status"]["enum"]
        self.assertEqual(status, ["OPEN", "ADVANCED", "PAID_OFF", "DEFERRED"])

    def test_the_report_carries_no_quota_or_score(self):
        # a quota would show up as a key the report emits; the validator must never
        # publish a minimum, a per-episode count target or a score.
        report = validate(ledger())
        keys = set(json.dumps(report, ensure_ascii=False).lower().split('"'))
        for forbidden in ("min_hooks", "hooks_per_episode", "max_silent", "score",
                          "score_100", "minimum", "quota", "target_count"):
            self.assertNotIn(forbidden, keys)


class RequiredFieldTests(unittest.TestCase):
    def test_a_missing_required_key_fails(self):
        payload = ledger()
        del payload["episodes"][1]["end_question"]
        report = validate(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("FIELD_MISSING:E15:end_question", report["failures"])

    def test_null_is_allowed_and_recorded(self):
        payload = ledger()
        for row in payload["episodes"]:
            row["end_question"] = None
        report = validate(payload)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertIn("E14:end_question", report["measurements"]["null_fields"])
        self.assertTrue(any(code.startswith("FIELD_NULL:E14:end_question")
                            for code in report["warnings"]))

    def test_every_required_episode_field_is_checked(self):
        for field in ("source_ref", "chosen_events", "delivered_experience",
                      "end_question", "payoff_plan", "scene_cards"):
            payload = ledger()
            del payload["episodes"][0][field]
            report = validate(payload)
            self.assertIn(f"FIELD_MISSING:E14:{field}", report["failures"], field)

    def test_window_of_two_episodes_fails_the_planning_window(self):
        payload = ledger(episode_window=["E14", "E15"], episodes=[episode("E14"), episode("E15")])
        report = validate(payload)
        self.assertTrue(any(code.startswith("EPISODE_WINDOW_LENGTH_OUT_OF_RANGE")
                            for code in report["failures"]), report["failures"])

    def test_window_of_seven_episodes_fails(self):
        names = [f"E{n}" for n in range(14, 21)]
        payload = ledger(episode_window=names, episodes=[episode(name) for name in names])
        self.assertTrue(any(code.startswith("EPISODE_WINDOW_LENGTH_OUT_OF_RANGE")
                            for code in validate(payload)["failures"]))

    def test_an_episode_outside_the_window_fails(self):
        payload = ledger()
        payload["episodes"].append(episode("E20"))
        report = validate(payload)
        self.assertIn("EPISODE_NOT_IN_WINDOW:E20", report["failures"])

    def test_an_episode_missing_from_the_window_fails(self):
        payload = ledger()
        del payload["episodes"][2]
        self.assertIn("EPISODE_WINDOW_MISSING_ROWS:E16", validate(payload)["failures"])


class HookTests(unittest.TestCase):
    def test_hook_status_must_be_one_of_four(self):
        payload = ledger()
        payload["hooks"][0]["status"] = "RESOLVED"
        report = validate(payload)
        self.assertTrue(any(code.startswith("HOOK_STATUS_INVALID:HOOK-GATE")
                            for code in report["failures"]), report["failures"])

    def test_hook_requires_id_status_and_progress(self):
        for field in ("id", "status", "progress"):
            payload = ledger()
            del payload["hooks"][0][field]
            report = validate(payload)
            self.assertTrue(any(code.startswith("HOOK_FIELD_MISSING")
                                and field in code for code in report["failures"]), field)

    def test_empty_progress_fails_even_when_the_key_exists(self):
        payload = ledger()
        payload["hooks"][0]["progress"] = "   "
        self.assertTrue(any(code.startswith("HOOK_PROGRESS_EMPTY")
                            for code in validate(payload)["failures"]))

    def test_advanced_hook_needs_a_payoff(self):
        payload = ledger()
        payload["hooks"] = [{"id": "HOOK-A", "status": "ADVANCED", "kind": "danger",
                             "progress": "the water rises", "payoff": ""}]
        payload["open_hooks_at_arc_end"] = []
        report = validate(payload)
        self.assertIn("HOOK_PAYOFF_EMPTY:HOOK-A:ADVANCED", report["failures"])

    def test_deferred_hook_needs_a_reason_and_a_planned_episode(self):
        payload = ledger()
        payload["hooks"] = [{"id": "HOOK-D", "status": "DEFERRED", "kind": "choice",
                             "progress": "he refuses for now"}]
        report = validate(payload)
        self.assertIn("HOOK_DEFERRED_REASON_MISSING:HOOK-D", report["failures"])
        self.assertIn("HOOK_DEFERRED_PLANNED_EPISODE_MISSING:HOOK-D", report["failures"])

    def test_deferred_hook_with_reason_and_episode_passes(self):
        payload = ledger(episodes=[episode(name, hook="HOOK-D")
                                   for name in ("E14", "E15", "E16")])
        payload["hooks"] = [{"id": "HOOK-D", "status": "DEFERRED", "kind": "choice",
                             "progress": "he refuses for now", "payoff": None,
                             "deferred_reason": "the arc needs it answered after the gate",
                             "planned_payoff_episode": "E18"}]
        report = validate(payload)
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_unknown_hook_kind_fails(self):
        payload = ledger()
        payload["hooks"][0]["kind"] = "suspense"
        self.assertTrue(any(code.startswith("HOOK_KIND_INVALID")
                            for code in validate(payload)["failures"]))


class OpenHooksAtArcEndTests(unittest.TestCase):
    def test_open_hook_at_arc_end_is_allowed_when_listed(self):
        payload = ledger(episodes=[episode(name, hook="HOOK-X")
                                   for name in ("E14", "E15", "E16")])
        payload["hooks"] = [{"id": "HOOK-X", "status": "OPEN", "kind": "open_question",
                             "progress": "the gate stays shut",
                             "payoff": "", "planned_payoff_episode": "E19"}]
        payload["open_hooks_at_arc_end"] = ["HOOK-X"]
        report = validate(payload)
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_open_hook_at_arc_end_must_be_listed(self):
        payload = ledger()
        payload["hooks"] = [{"id": "HOOK-X", "status": "OPEN", "kind": "open_question",
                             "progress": "the gate stays shut", "payoff": ""}]
        payload["open_hooks_at_arc_end"] = []
        report = validate(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("OPEN_HOOK_NOT_LISTED_AT_ARC_END:HOOK-X", report["failures"])

    def test_an_omitted_open_hooks_field_still_catches_the_hook(self):
        payload = ledger()
        payload["hooks"] = [{"id": "HOOK-X", "status": "OPEN", "kind": "open_question",
                             "progress": "the gate stays shut", "payoff": ""}]
        del payload["open_hooks_at_arc_end"]
        self.assertIn("OPEN_HOOKS_NOT_LISTED_AT_ARC_END:HOOK-X", validate(payload)["failures"])

    def test_listing_a_paid_off_hook_as_open_fails(self):
        payload = ledger()
        payload["open_hooks_at_arc_end"] = ["HOOK-GATE"]
        self.assertIn("LISTED_HOOK_IS_NOT_OPEN:HOOK-GATE", validate(payload)["failures"])


class PayoffPlanTests(unittest.TestCase):
    def test_payoff_must_name_what_it_settles(self):
        payload = ledger()
        payload["episodes"][0]["payoff_plan"] = [{"payoff_id": "PO-1"}]
        report = validate(payload)
        self.assertIn("PAYOFF_TARGET_MISSING:E14:PO-1", report["failures"])

    def test_payoff_referencing_an_unknown_hook_fails(self):
        payload = ledger()
        payload["episodes"][0]["payoff_plan"] = [
            {"payoff_id": "PO-1", "settles": "HOOK-NOWHERE", "delivered_in": "E14"}]
        self.assertIn("PAYOFF_REFERENCES_UNKNOWN_HOOK:E14:HOOK-NOWHERE", validate(payload)["failures"])


class SceneCardTests(unittest.TestCase):
    def test_every_card_field_is_required(self):
        for field in ("want", "obstacle", "action", "change", "why_keep"):
            payload = ledger()
            del payload["episodes"][0]["scene_cards"][0][field]
            report = validate(payload)
            self.assertIn(f"SCENE_CARD_FIELD_MISSING:E14:E14-S01:{field}", report["failures"], field)

    def test_function_duplicates_need_a_kind_items_proposal_and_reason(self):
        payload = ledger()
        payload["episodes"][0]["function_duplicates"] = [
            {"kind": "character", "items": ["guard A", "guard B"],
             "proposal": "MERGE", "reason": "both only block the gate and say the same line"}]
        self.assertEqual(validate(payload)["status"], "PASS")
        payload["episodes"][0]["function_duplicates"][0]["proposal"] = "DELETE"
        self.assertTrue(any(code.startswith("FUNCTION_DUPLICATE_PROPOSAL_INVALID")
                            for code in validate(payload)["failures"]))


class PayoffDiagnosticTests(unittest.TestCase):
    def test_an_episode_delivering_nothing_is_flagged_not_failed(self):
        payload = ledger(episodes=[episode(name, hook="HOOK-LATER")
                                   for name in ("E14", "E15", "E16")])
        payload["episodes"][1]["payoff_plan"] = [
            {"payoff_id": "PO-15-1", "settles": "HOOK-LATER", "delivered_in": "E17"}]
        payload["hooks"].append({"id": "HOOK-LATER", "status": "OPEN", "kind": "choice",
                                 "progress": "planted", "payoff": "",
                                 "planned_payoff_episode": "E17"})
        payload["open_hooks_at_arc_end"] = ["HOOK-LATER"]
        report = validate(payload)
        self.assertEqual(report["status"], "PASS", report["failures"])
        codes = [row["code"] for row in report["diagnostics"]]
        self.assertIn("NO_DELIVERED_PAYOFF", codes)
        self.assertEqual(report_status(report), "PASS")
        self.assertEqual(report_status(report, strict_diagnostics=True), "DIAGNOSTIC_UNANSWERED")

    def test_an_answer_clears_the_diagnostic(self):
        payload = ledger()
        payload["episodes"][1]["payoff_plan"] = []
        payload["episodes"][1]["no_payoff_answer"] = (
            "deliberately quiet: the brother's silence is the point of the episode")
        report = validate(payload)
        self.assertEqual(report_status(report, strict_diagnostics=True), "PASS")

    def test_a_run_of_two_quiet_episodes_is_flagged(self):
        payload = ledger()
        payload["episodes"][1]["payoff_plan"] = []
        payload["episodes"][2]["payoff_plan"] = []
        rows = [row for row in validate(payload)["diagnostics"]
                if row["code"] == "CONSECUTIVE_NO_PAYOFF_RUN"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["episodes"], ["E15", "E16"])

    def test_the_guidance_never_asks_for_more_conflict(self):
        report = validate(ledger())
        guidance = report["guidance"].lower()
        self.assertIn("quiet emotional episode is a valid answer", guidance)
        self.assertIn("do not add fights", guidance)


class SchemaParityTests(unittest.TestCase):
    """The JSON schema and the validator must agree on what is required."""

    def test_episode_required_keys_match_the_validator(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = schema["properties"]["episodes"]["items"]["required"]
        from tools.writer_arc_ledger import EPISODE_REQUIRED
        # the schema additionally requires the episode id itself
        self.assertEqual(sorted(required), sorted((*EPISODE_REQUIRED, "episode")))

    def test_hook_required_keys_match_the_validator(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = schema["properties"]["hooks"]["items"]["required"]
        from tools.writer_arc_ledger import HOOK_REQUIRED
        self.assertEqual(sorted(required), sorted(HOOK_REQUIRED))

    def test_scene_card_required_keys_match_the_validator(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        card_schema = (schema["properties"]["episodes"]["items"]["properties"]
                       ["scene_cards"]["items"]["required"])
        from tools.writer_arc_ledger import SCENE_CARD_FIELDS
        # the schema additionally requires the card's own scene id
        self.assertEqual(sorted(card_schema), sorted((*SCENE_CARD_FIELDS, "scene_id")))


class RoundTripTests(unittest.TestCase):
    def test_load_reads_a_written_ledger(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arc.json"
            path.write_text(json.dumps(ledger(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(validate(load(path))["status"], "PASS")

    def test_validate_does_not_mutate_its_input(self):
        payload = ledger()
        before = copy.deepcopy(payload)
        validate(payload)
        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
