"""Advisory selection, adoption-state honesty, impact scope, real adjacency (T15, T18, T19, T23, T25).

Historical defect classes (half face, unmotivated repeated pans, talking to camera, wrong person,
missing dialogue, action restart) each come with a legitimate creative counterexample that must
NOT be flagged -- a rule fires on its declared conditions, never on a keyword.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import knowledge_consumption_ledger as kcl
from tools import knowledge_sync_core as ksc
from tools.collective_learning import adoption, contracts as c, impact, selection
from tools.collective_learning.device_store import DeviceStore
from tools.tests.test_collective_bundles import API, H3, SD2, STAGE, rule

IDENT = {"tenant_id": "tenant-a", "line_id": "line-a", "device_id": "dev-a", "run_id": "line-a.EP01.B1"}


def dialogue_unit(*, uid: str = "EP01-VU-001", model: str = H3, listener_visible: bool = False,
                  shot_intent: str | None = None, dialogue: str = "阿尔：你去过吗？", cast_ids=("CHAR-A",)) -> dict:
    visible = list(cast_ids) + (["CHAR-B"] if listener_visible else [])
    unit = {
        "unit_id": uid, "model": model, "aspect_ratio": "9:16",
        "provider_scope_projection": {"visible_character_ids": visible},
        "ordered_prompt_specs": [{
            "cast": [{"character_id": cid} for cid in visible],
            "dialogue": dialogue,
            "action": {"primary_action": "阿尔转头看向身边的人", "start_state": "站着", "completion_state": "转过头"},
            "role_semantic_disambiguation": {"dialogue_speaker_id": "CHAR-A", "dialogue_listener_id": "CHAR-B"},
        }],
        "h3_provider_english_contract": {"beats": [{"primary_action": "Alpha turns toward the person beside him"}],
                                         "negative_constraints": ["No extra people"]},
    }
    if shot_intent:
        unit["shot_intent"] = shot_intent
    return unit


EYELINE = rule("R-EYELINE-OFFSCREEN", models=[H3, SD2], scene_types=["DIALOGUE"],
               requires=["dialogue_present", "listener_offscreen"],
               clause={"en": "while speaking his eyes stay on the listener's off-screen side, never the lens",
                       "zh": "说话时视线始终落在画外听者一侧，不看镜头"},
               machine_exceptions={"shot_intents": ["DIRECT_ADDRESS"]}, evidence="REPRODUCED")


def _decide(unit: dict, rules: list[dict], **kwargs) -> dict:
    return selection.select_for_unit(unit, rules, stage=STAGE, engine_api_version=API, **kwargs)


class TalkingToCameraRegressionTest(unittest.TestCase):
    def test_offscreen_listener_gets_eyeline_clause(self) -> None:
        decision = _decide(dialogue_unit(), [EYELINE])
        self.assertEqual([r["rule_id"] for r in decision["clauses"]], ["R-EYELINE-OFFSCREEN"])
        applied = selection.apply_to_unit(dialogue_unit(), decision)
        self.assertIn("never the lens", applied["unit"]["h3_provider_english_contract"]["beats"][0]["primary_action"])

    def test_designed_direct_address_is_not_flagged(self) -> None:
        decision = _decide(dialogue_unit(shot_intent="DIRECT_ADDRESS"), [EYELINE])
        self.assertEqual(decision["clauses"], [])
        self.assertTrue(decision["decisions"][0]["reason"].startswith("SCENE_INTENT_PRECEDENCE"))

    def test_visible_listener_and_monologue_are_out_of_scope(self) -> None:
        self.assertEqual(_decide(dialogue_unit(listener_visible=True), [EYELINE])["clauses"], [])
        self.assertEqual(_decide(dialogue_unit(dialogue=""), [EYELINE])["clauses"], [])


class HalfFaceRegressionTest(unittest.TestCase):
    RULE = rule("R-WHOLE-FACE-MULTI", models=[SD2], requires=["multi_character"],
                clause={"zh": "主体的整张脸始终完整留在画内"},
                machine_exceptions={"shot_intents": ["DESIGNED_PARTIAL_FACE"]})

    def test_multi_character_unit_gets_whole_face_clause(self) -> None:
        unit = dialogue_unit(model=SD2, listener_visible=True)
        applied = selection.apply_to_unit(unit, _decide(unit, [self.RULE]))
        self.assertIn("整张脸", applied["unit"]["ordered_prompt_specs"][0]["action"]["primary_action"])

    def test_designed_partial_face_close_up_is_respected(self) -> None:
        unit = dialogue_unit(model=SD2, listener_visible=True, shot_intent="DESIGNED_PARTIAL_FACE")
        self.assertEqual(_decide(unit, [self.RULE])["clauses"], [])


class RepeatedPanRegressionTest(unittest.TestCase):
    """The check is the engine's own validate_camera_sequence over the existing K119 fixture."""

    @staticmethod
    def _sequence(**extra) -> list[dict]:
        from tools.tests.test_knowledge_loop_behavioral_regression import RepeatedPanRegressionTest as K119
        return K119()._sequence(**extra)

    def test_three_pans_in_five_units_are_flagged(self) -> None:
        findings = selection.run_checks(["CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT"], self._sequence())
        self.assertEqual(len(findings["CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT"]), 1)
        self.assertIn("repeats more than twice in five units", findings["CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT"][0])

    def test_story_motivated_sequence_under_camera_grammar_is_not_flagged(self) -> None:
        units = self._sequence(camera_grammar="CAMERA_GRAMMAR_V1")
        self.assertEqual(selection.run_checks(["CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT"], units)
                         ["CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT"], [])

    def test_unknown_check_is_reported_not_passed(self) -> None:
        self.assertEqual(selection.run_checks(["NOPE"], [])["NOPE"], ["CHECK_NOT_REGISTERED:NOPE"])


class WrongPersonAndMissingDialogueTest(unittest.TestCase):
    def test_wrong_person_blocks_only_that_unit(self) -> None:
        good = dialogue_unit(uid="U-GOOD")
        bad = dialogue_unit(uid="U-BAD")
        bad["ordered_prompt_specs"][0]["cast"].append({"character_id": "CHAR-STRANGER"})
        blocked = selection.blocked_units([good, bad], ["VISIBLE_CAST_BOUND_TO_PROJECTION"])
        self.assertEqual(list(blocked), ["U-BAD"])

    def test_offscreen_voice_is_not_a_wrong_person(self) -> None:
        unit = dialogue_unit()  # CHAR-B speaks to / is addressed off-screen but is not cast
        self.assertEqual(selection.blocked_units([unit], ["VISIBLE_CAST_BOUND_TO_PROJECTION"]), {})

    def test_missing_dialogue_flagged_and_voice_only_line_exempt(self) -> None:
        unit = dialogue_unit()
        check = ["DIALOGUE_LINES_IN_COMPILED_PROMPT"]
        self.assertEqual(selection.blocked_units([unit], check, {"EP01-VU-001": "<d>你去过吗？</d>"}), {})
        self.assertIn("EP01-VU-001", selection.blocked_units([unit], check, {"EP01-VU-001": "no line here"}))
        unit["ordered_prompt_specs"][0]["voice_only_not_in_video"] = True
        self.assertEqual(selection.blocked_units([unit], check, {"EP01-VU-001": "no line here"}), {})


class RealAdjacencyTest(unittest.TestCase):
    """T19: neighbours come only from declared transition contracts and real first/last shots."""

    def _units(self) -> list[dict]:
        a = {"unit_id": "EP01-VU-010", "editorial_shot_ids": ["EP01-S02-01", "EP01-S02-02", "EP01-S02-03"],
             "internal_transition_contracts": [
                 {"from_shot_id": "EP01-S02-01", "to_shot_id": "EP01-S02-02"},
                 {"from_shot_id": "EP01-S02-02", "to_shot_id": "EP01-S02-03"}],
             "outgoing_transition_contract": {"from_unit_id": "EP01-VU-010", "to_unit_id": "EP01-VU-014",
                                              "boundary_id": "BND-10-14"},
             "ordered_prompt_specs": [{"action": {"start_state": "抬手", "completion_state": "刀已出鞘"}}]}
        b = {"unit_id": "EP01-VU-014", "editorial_shot_ids": ["EP01-S03-01"],
             "incoming_transition_contract": {"from_unit_id": "EP01-VU-010", "to_unit_id": "EP01-VU-014",
                                              "boundary_id": "BND-10-14"},
             "ordered_prompt_specs": [{"action": {"start_state": "刀已出鞘", "completion_state": "刀落"}}]}
        orphan = {"unit_id": "EP01-VU-011", "editorial_shot_ids": ["EP01-S02-04"],
                  "ordered_prompt_specs": [{"action": {"start_state": "抬手", "completion_state": "刀已出鞘"}}]}
        return [b, orphan, a]  # deliberately not in id or list order

    def test_pairs_follow_contracts_not_list_order_or_ids(self) -> None:
        pairs = selection.declared_adjacency(self._units())
        boundary = [p for p in pairs if p["kind"] == "UNIT_BOUNDARY"]
        self.assertEqual(len(boundary), 1)
        self.assertEqual((boundary[0]["from_shot_id"], boundary[0]["to_shot_id"]), ("EP01-S02-03", "EP01-S03-01"))
        internal = [(p["from_shot_id"], p["to_shot_id"]) for p in pairs if p["kind"] == "INTERNAL_SHOT_BOUNDARY"]
        self.assertEqual(internal, [("EP01-S02-01", "EP01-S02-02"), ("EP01-S02-02", "EP01-S02-03")])
        self.assertFalse(any("EP01-VU-011" in json.dumps(p) or "EP01-S02-04" in json.dumps(p) for p in pairs))

    def test_action_restart_across_real_boundary_and_intentional_repeat(self) -> None:
        units = self._units()
        self.assertEqual(selection.run_checks(["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"], units)
                         ["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"], [])
        restart = copy.deepcopy(units)
        restart[0]["ordered_prompt_specs"][0]["action"]["start_state"] = "抬手"  # VU-014 begins the draw again
        findings = selection.run_checks(["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"], restart)
        self.assertEqual(findings["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"],
                         ["ACTION_RESTART_ACROSS_BOUNDARY:EP01-S02-03->EP01-S03-01"])
        restart[0]["incoming_transition_contract"]["intentional_repeat"] = True  # designed replay beat
        self.assertEqual(selection.run_checks(["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"], restart)
                         ["NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY"], [])


class CapsConflictsDialogueTest(unittest.TestCase):
    """T23: scoped, capped, conflict-resolved, never touching dialogue."""

    def _rules(self, n: int) -> list[dict]:
        return [rule(f"R-ADV-{i}", models=[H3], scene_types=["DIALOGUE"], evidence=("MULTI_CASE" if i == 4 else "SINGLE_CASE"),
                     clause={"en": f"advice number {i} keeps the exchange readable"}) for i in range(n)]

    def test_per_unit_rule_cap_and_rank(self) -> None:
        decision = _decide(dialogue_unit(), self._rules(6))
        self.assertEqual(len(decision["clauses"]), 3)
        self.assertEqual(decision["clauses"][0]["rule_id"], "R-ADV-4")  # strongest evidence first
        self.assertEqual(sum(1 for d in decision["decisions"] if d.get("reason") == "UNIT_RULE_CAP:3"), 3)

    def test_added_text_cap(self) -> None:
        decision = _decide(dialogue_unit(), self._rules(6), max_rules=10, max_added_chars=90)
        self.assertLessEqual(decision["added_chars"], 90)
        self.assertTrue(any(d.get("reason") == "UNIT_ADDED_TEXT_CAP:90" for d in decision["decisions"]))

    def test_non_critical_conflict_resolved_by_rank_without_blocking(self) -> None:
        strong = rule("R-STRONG", models=[H3], scene_types=["DIALOGUE"], evidence="MULTI_CASE",
                      clause={"en": "hold the two-shot steady"})
        weak = rule("R-WEAK", models=[H3], scene_types=["DIALOGUE"], conflicts_with=["R-STRONG"],
                    clause={"en": "drift slowly toward the speaker"})
        decision = _decide(dialogue_unit(), [weak, strong])
        self.assertEqual([r["rule_id"] for r in decision["clauses"]], ["R-STRONG"])
        self.assertEqual(decision["conflicts"][0]["severity"], "NON_CRITICAL")

    def test_dialogue_is_byte_identical_and_tamper_is_caught(self) -> None:
        unit = dialogue_unit(model=SD2)
        before = copy.deepcopy(unit["ordered_prompt_specs"][0]["dialogue"])
        applied = selection.apply_to_unit(unit, _decide(unit, self._rules(3) + [EYELINE]))
        self.assertEqual(applied["unit"]["ordered_prompt_specs"][0]["dialogue"], before)
        bad = {"family": "sd2", "clauses": [{"rule_id": "X", "rule_version": 1, "carrier": "BEAT_DIRECTION",
                                             "clause": "ok"}]}
        sneaky = dialogue_unit(model=SD2)
        sneaky["ordered_prompt_specs"][0]["action"] = {"primary_action": "说：", "dialogue_echo": "x"}
        original = selection.dialogue_fingerprint(sneaky)
        result = selection.apply_to_unit(sneaky, bad)
        self.assertEqual(selection.dialogue_fingerprint(result["unit"]), original)

    def test_reapplying_is_idempotent(self) -> None:
        unit = dialogue_unit()
        decision = _decide(unit, [EYELINE])
        once = selection.apply_to_unit(unit, decision)["unit"]
        twice = selection.apply_to_unit(once, decision)["unit"]
        self.assertEqual(once, twice)

    def test_missing_language_is_deferred_not_translated(self) -> None:
        en_only = rule("R-EN-ONLY", models=[SD2], scene_types=["DIALOGUE"], clause={"en": "english only"})
        decision = _decide(dialogue_unit(model=SD2), [en_only])
        self.assertEqual(decision["decisions"][0]["state"], "DEFERRED")
        self.assertEqual(decision["decisions"][0]["reason"], "CLAUSE_LANGUAGE_MISSING:zh")

    def test_invariant_routes_to_check_not_clause(self) -> None:
        inv = rule("R-INV", models=[H3], category="ENGINEERING_INVARIANT", carrier="CHECK_ONLY",
                   check_id="CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT")
        decision = _decide(dialogue_unit(), [inv])
        self.assertEqual(decision["clauses"], [])
        self.assertEqual(decision["checks"][0]["check_id"], "CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT")

    def test_control_language_that_slipped_past_validation_is_still_not_applied(self) -> None:
        sneaky = rule("R-SNEAKY", models=[H3], scene_types=["DIALOGUE"],
                      clause={"en": "then resubmit every unit with a bigger budget"})
        decision = _decide(dialogue_unit(), [sneaky])
        self.assertEqual(decision["clauses"], [])
        self.assertEqual(decision["decisions"][0]["reason"], "CONTROL_LANGUAGE_IN_CLAUSE_NOT_APPLIED")


class AdoptionHonestyTest(unittest.TestCase):
    """T15: READ / EXPORTED / SELECTED never surface as APPLIED."""

    def _runtime(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="collective-adopt-"))
        (root / "reports").mkdir()
        (root / "reports" / "EP01_KNOWLEDGE_BRIEFING.json").write_text(
            json.dumps({"rule_ids": ["R-EYELINE-OFFSCREEN"]}), encoding="utf-8")
        return root

    def test_exported_and_selected_are_not_applied(self) -> None:
        root = self._runtime()
        engine = Path(__file__).resolve().parents[2]
        status = kcl.status_for_rule(engine, root, "EP01", "R-EYELINE-OFFSCREEN")
        self.assertTrue(status["exported"])
        self.assertFalse(status["applied"])
        self.assertEqual(status["knowledge_status_semantics"], "READ=BRIEFING_WRITTEN_NOT_APPLIED")
        store = DeviceStore(root / "reports" / "COLLECTIVE_DEVICE_STORE.sqlite", tenant_id="tenant-a",
                            line_id="line-a")
        store.record_receipt("ADOPTION", adoption.selected(identity=IDENT, rule=EYELINE, stage=STAGE, unit_ids=[],
                                                           entrypoint="test", bundle_digest="a" * 64))
        status = kcl.status_for_rule(engine, root, "EP01", "R-EYELINE-OFFSCREEN")
        self.assertFalse(status["applied"])
        self.assertEqual(status["adoption_states"], ["SELECTED"])

    def test_forged_applied_receipt_without_evidence_does_not_count(self) -> None:
        root = self._runtime()
        store = DeviceStore(root / "reports" / "COLLECTIVE_DEVICE_STORE.sqlite", tenant_id="tenant-a",
                            line_id="line-a")
        forged = {**adoption.selected(identity=IDENT, rule=EYELINE, stage=STAGE, unit_ids=[], entrypoint="test",
                                      bundle_digest="a" * 64), "state": "APPLIED"}
        with self.assertRaises(c.ContractError):
            store.record_receipt("ADOPTION", forged)
        self.assertEqual(adoption.strongest_state([forged], "R-EYELINE-OFFSCREEN"), "NONE")

    def test_applied_needs_real_change_and_verified_needs_same_output(self) -> None:
        clause = "eyes stay on the listener's side"
        with self.assertRaises(c.ContractError):
            adoption.applied(identity=IDENT, rule=EYELINE, stage=STAGE, unit_ids=["U1"], entrypoint="t",
                             bundle_digest="a" * 64, clause=clause, source_contract={"x": 1},
                             compiled_with="no clause here", compiled_without="no clause here")
        with self.assertRaises(c.ContractError):
            adoption.applied(identity=IDENT, rule=EYELINE, stage=STAGE, unit_ids=["U1"], entrypoint="t",
                             bundle_digest="a" * 64, clause=clause, source_contract={"x": 1},
                             compiled_with=f"A {clause}", compiled_without=f"B {clause}")
        receipt = adoption.applied(identity=IDENT, rule=EYELINE, stage=STAGE, unit_ids=["U1"], entrypoint="t",
                                   bundle_digest="a" * 64, clause=clause, source_contract={"x": 1},
                                   compiled_with=f"A {clause}", compiled_without="A")
        self.assertEqual(receipt["evidence_scope"], "COMPILED_REQUEST")
        self.assertFalse(receipt["outcome_observed"])
        with self.assertRaises(c.ContractError):
            adoption.verified(receipt, test_name="t", assertion="a", passed=True, checked_output_digest="0" * 64)
        ok = adoption.verified(receipt, test_name="t", assertion="clause present in compiled text", passed=True,
                               checked_output_digest=receipt["compiled_output_digest"])
        self.assertEqual(adoption.strongest_state([receipt, ok], "R-EYELINE-OFFSCREEN"), "VERIFIED")
        with self.assertRaises(c.ContractError):
            adoption.outcome_observed(ok, kind="DEFECT_ABSENT", media_sha256="not-a-sha", evidence_scope="FINAL_FILM",
                                      observed_by="reviewer")
        with self.assertRaises(c.ContractError):  # a compiled request is not a film
            adoption.outcome_observed(ok, kind="DEFECT_ABSENT", media_sha256="b" * 64,
                                      evidence_scope="COMPILED_REQUEST", observed_by="reviewer")


class ImpactScopeTest(unittest.TestCase):
    """T18: only the declared free checks go stale; paid steps are listed and never re-run."""

    STATE = {"stages": {
        "S2": {"steps": [
            {"name": "s2_build_nalu_preproduction", "argv": ["py", "tools/build_nalu_preproduction.py"], "paid": False},
            {"name": "s2_unrelated_layout_gate", "argv": ["py", "tools/layout_gate.py"], "paid": False}]},
        "S6": {"steps": [
            {"name": "s6_video_submit", "argv": ["py", "tools/submit_giggle_video_manifest_v2.py",
                                                  "--uses", "tools/video_prompt_compiler.py"], "paid": True},
            {"name": "s6_prompt_finalization_diff", "argv": ["py", "tools/prompt_batch_finalize.py",
                                                              "--uses", "tools/video_prompt_compiler.py"],
             "paid": False}]}}}

    def test_explicit_scope_marks_only_free_matches(self) -> None:
        result = impact.stale_checks(self.STATE, "R-X", {"modules": ["tools/video_prompt_compiler.py"],
                                                         "free_checks": ["s2_build_nalu_preproduction"]})
        stale = sorted(row["step_name"] for row in result["stale_free_checks"])
        self.assertEqual(stale, ["s2_build_nalu_preproduction", "s6_prompt_finalization_diff"])
        self.assertEqual([row["step_name"] for row in result["paid_never_resubmitted"]], ["s6_video_submit"])
        self.assertEqual(result["action"], "REPORT_ONLY_NOTHING_RE_RUN")

    def test_stage_restriction_and_backward_compatible_sync_output(self) -> None:
        result = impact.stale_checks(self.STATE, "R-X", {"modules": ["tools/video_prompt_compiler.py"],
                                                         "stages": ["S6"]})
        self.assertEqual([r["step_name"] for r in result["stale_free_checks"]], ["s6_prompt_finalization_diff"])
        rows = [{"id": "K900", "implementation": ["tools/video_prompt_compiler.py"], "regression": "t.py",
                 "impact_scope": {"modules": ["tools/video_prompt_compiler.py"]}},
                {"id": "K901", "implementation": ["tools/layout_gate.py"], "regression": "t2.py"}]
        state_before = json.dumps(self.STATE, sort_keys=True)
        out = {row["rule_id"]: row for row in ksc.free_recheck_targets(self.STATE, rows, ["K900", "K901"])}
        self.assertEqual(json.dumps(self.STATE, sort_keys=True), state_before)
        self.assertEqual(out["K900"]["free_matches"], [])  # the argv[1] match alone found nothing
        self.assertEqual(len(out["K900"]["explicit_impact"]["stale_free_checks"]), 1)
        self.assertIsNone(out["K900"]["fallback_verification"])
        self.assertNotIn("explicit_impact", out["K901"])  # rows without a scope keep the old shape
        self.assertEqual(out["K901"]["free_matches"][0]["step_name"], "s2_unrelated_layout_gate")


if __name__ == "__main__":
    unittest.main()
