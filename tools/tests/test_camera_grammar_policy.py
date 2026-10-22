"""CAMERA_GRAMMAR_V1 (line owner 2026-10-22): motivated motion, no mechanical
direction alternation, real cuts at scripted cuts, shot-scale grammar.

Every rule is zero-credit and pre-POST.  Contracts sealed before the policy
(no ``camera_grammar_policy`` field) must keep their verdicts byte for byte.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "lines" / "nalu" / "runtime" / "tools", _ROOT / "tools", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import camera_grammar_policy as cg  # noqa: E402
import static_design_gate as sdg  # noqa: E402
from tools.grouped_camera_contract import validate_camera_plan, validate_camera_sequence  # noqa: E402

GRAMMAR = {"camera_grammar_policy": "CAMERA_GRAMMAR_V1"}


def _plan(family="LOCKED", direction="NONE", scale="MEDIUM", motivation=None, side="AXIS_A"):
    plan = {
        "shot_scale": scale, "camera_height": "EYE_LEVEL", "camera_side": side,
        "motion_family": family, "motion_direction": direction,
        "lens_intent": "35mm human eye", "axis_relation": "stays on the A side of the axis",
        "start_framing": "the hall from the door" if family == "LOCKED" else "the hall from the door, left",
        "end_framing": "the hall from the door",
        "motivation": "keeps the subject and the room readable together",
    }
    if motivation:
        plan["motion_motivation"] = motivation
    return plan


def _shot(sid, scene="SC1", seconds=4.0, action="", dialogue=None, listener=None, cast=("CHAR-A",), **plan):
    rsd = {"dialogue_listener_id": listener} if listener else {}
    return {
        "shot_id": sid, "scene_id": scene, "target_seconds": seconds,
        "prompt_spec": {
            "camera_plan": _plan(**plan),
            "dialogue": dialogue,
            "action": {"primary_action": action},
            "cast": [{"character_id": c} for c in cast],
            "role_semantic_disambiguation": rsd,
        },
    }


def _contract(shots, grammar=True, scenes=None, **extra):
    contract = {"episode": "E07", "shots": shots,
                "scene_states": scenes or [{"scene_id": "SC1", "location_id": "LOC-HALL"}]}
    if grammar:
        contract.update(GRAMMAR)
    contract.update(extra)
    return contract


def _codes(result):
    return [f.split(":", 1)[-1] for f in result["failures"]]


def _notes(result):
    return [f.split(":", 1)[-1] for f in result.get("advisories") or []]


class SwitchTest(unittest.TestCase):
    def test_only_a_declaration_or_a_listing_activates(self):
        self.assertTrue(cg.active({"episode": "E07", **GRAMMAR}))
        self.assertFalse(cg.active({"episode": "E07"}))
        self.assertFalse(cg.active({"episode": "E07", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}))
        with mock.patch.object(cg, "policy_settings", lambda: {"enabled_episodes": ["E07"]}):
            self.assertTrue(cg.active({"episode": "E07"}))
            self.assertFalse(cg.active({"episode": "E07", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}))

    def test_shipped_config_lists_no_episode(self):
        self.assertEqual(cg.policy_settings().get("enabled_episodes"), [])

    def test_stamp_adds_the_field_after_episode_and_never_overwrites(self):
        contract = {"schema": "qingshan.generation_contract.v3", "episode": "E02", "shots": []}
        self.assertTrue(cg.stamp_contract(contract))
        self.assertEqual(list(contract)[:3], ["schema", "episode", "camera_grammar_policy"])
        self.assertEqual(contract["camera_grammar_policy"], "CAMERA_GRAMMAR_V1")
        opted_out = {"episode": "E02", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}
        self.assertFalse(cg.stamp_contract(opted_out))
        self.assertEqual(opted_out["camera_grammar_policy"], "LEGACY_FORCED_MOTION")

    def test_writer_finalize_stamps_the_contract_file(self):
        from tools import storyclaw_writer_workflow as workflow
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "E02_GENERATION_CONTRACT_v1.json"
            path.write_text(json.dumps({"schema": "x", "episode": "E02"}), encoding="utf-8")
            self.assertTrue(workflow._stamp_camera_grammar_policy(path))
            self.assertEqual(json.loads(path.read_text())["camera_grammar_policy"], "CAMERA_GRAMMAR_V1")
            self.assertFalse(workflow._stamp_camera_grammar_policy(path))  # idempotent
            path.write_text("not json", encoding="utf-8")
            self.assertFalse(workflow._stamp_camera_grammar_policy(path))

    def test_english_body_verbs_count_as_body_motion(self):
        self.assertTrue(cg.has_body_motion("Mara walks to the window and kneels"))
        self.assertTrue(cg.has_body_motion("陆九转身"))
        self.assertFalse(cg.has_body_motion("candle light flickers on the wall"))
        self.assertFalse(cg.has_body_motion("he turns his head slightly"))


class OldEpisodesUnchangedTest(unittest.TestCase):
    def test_contract_without_the_field_keeps_the_forced_motion_verdict(self):
        shots = [_shot("S1", action="Mara walks to the window", seconds=2.0),
                 _shot("S2", family="PAN", direction="LEFT_TO_RIGHT")]
        old = sdg.evaluate(_contract(copy.deepcopy(shots), grammar=False), sdg.POLICY)
        self.assertNotIn("camera_grammar_policy", old)
        self.assertNotIn("fix_hints", old)
        # the blanket R3 and R6 of the old rules still fire for a locked no-dialogue opener
        self.assertIn("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION", _codes(old))
        self.assertIn("R6_OPENING_SHOT_LOCKED", _codes(old))
        # and an unmotivated PAN is fine under the old rules
        self.assertFalse(any(c.startswith("R9_") for c in _codes(old)))

    def test_grouped_sequence_without_motivation_keeps_both_direction_caps(self):
        units = [{"unit_id": "U1", "camera_plan": _plan("PAN", "LEFT_TO_RIGHT")},
                 {"unit_id": "U2", "camera_plan": _plan("TRACK", "LEFT_TO_RIGHT")}]
        with self.assertRaisesRegex(ValueError, "repeat camera direction"):
            validate_camera_sequence(copy.deepcopy(units))
        window = [{"unit_id": f"U{i}", "camera_plan": _plan(fam, dirn)} for i, (fam, dirn) in enumerate(
            [("PAN", "LEFT_TO_RIGHT"), ("CRANE", "RISE"), ("TRACK", "LEFT_TO_RIGHT"),
             ("CRANE", "FALL"), ("PAN", "LEFT_TO_RIGHT")], 1)]
        with self.assertRaisesRegex(ValueError, "more than twice in five units"):
            validate_camera_sequence(window)


class MotivatedMotionTest(unittest.TestCase):
    """No new blocking check: forced-motion rules and grammar notes are advisories only."""

    def _eval(self, shots, **extra):
        return sdg.evaluate(_contract(shots, **extra), sdg.POLICY)

    def test_locked_no_dialogue_shot_with_english_body_action_is_clean(self):
        r = self._eval([_shot("S1", scale="WIDE", action="Mara walks across the hall and kneels")])
        self.assertEqual(r["failures"], [])
        self.assertEqual(r["advisories"], [])
        self.assertEqual(r["camera_grammar_policy"], "CAMERA_GRAMMAR_V1")

    def test_static_holds_never_block(self):
        r = self._eval([_shot("S1", scale="WIDE", seconds=5.0, action="the empty hall"),
                        _shot("S2", scale="MEDIUM", seconds=5.0, action="the empty hall again"),
                        _shot("S3", scale="CLOSE_UP", seconds=6.0, dialogue="Mara: Who sent you?")])
        self.assertEqual(r["failures"], [])
        notes = _notes(r)
        for code in ("R6_OPENING_SHOT_LOCKED", "R2_CONSECUTIVE_LOCKED", "R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION",
                     "R4_LOCKED_DIALOGUE_SHOT_OVER_5S"):
            self.assertIn(code, notes)
        self.assertIn("R3", r["fix_hints"])

    def test_short_insert_hold_is_clean(self):
        r = self._eval([_shot("S1", scale="WIDE", seconds=3.0, action="rain on the glass"),
                        _shot("S2", scale="CLOSE_UP", seconds=2.5, family="DOLLY", direction="PUSH_IN",
                              action="the seal on the letter")])
        self.assertEqual(r["failures"], [])
        self.assertFalse(any(n.startswith("R3_") for n in _notes(r)))

    def test_unstated_motivation_and_repeated_move_are_notes(self):
        r = self._eval([
            _shot("S1", scale="WIDE", family="TRACK", direction="LEFT_TO_RIGHT", action="Mara walks"),
            _shot("S2", scale="MEDIUM", family="TRACK", direction="LEFT_TO_RIGHT", action="Mara walks on")])
        self.assertEqual(r["failures"], [])
        self.assertIn("R9_CAMERA_MOVE_WITHOUT_MOTIVATION:TRACK", _notes(r))
        self.assertIn("R13_REPEATED_IDENTICAL_MOVE:TRACK:LEFT_TO_RIGHT", _notes(r))
        ok = self._eval([_shot("S1", scale="WIDE", family="PAN", direction="LEFT_TO_RIGHT",
                               motivation="FOLLOW_SUBJECT", action="Mara walks to the door")])
        self.assertEqual(ok["advisories"], [])

    def test_r5_and_r8_still_block(self):
        r = self._eval([_shot("S1", scale="WIDE", action="Mara walks in"),
                        _shot("S2", scale="MEDIUM", action="Mara sits down"),
                        _shot("S3", scale="MEDIUM", action="Mara stands up"),
                        _shot("S4", scale="MEDIUM", seconds=1.0, dialogue="Mara：这是一句非常长的台词需要时间")])
        self.assertIn("R5_SAME_AXIS_SCALE_RUN", _codes(r))
        self.assertTrue(any(c.startswith("R8_") for c in _codes(r)))

    def test_unknown_motivation_is_not_a_new_failure(self):
        validate_camera_plan(_plan("PAN", "LEFT_TO_RIGHT", motivation="BECAUSE"), source_id="U1")

    def test_stamped_or_motivated_moves_are_free_of_direction_alternation(self):
        for extra in ({"camera_grammar": "CAMERA_GRAMMAR_V1"}, {"motion_motivation": "FOLLOW_SUBJECT"}):
            units = [{"unit_id": f"U{i}", "camera_plan": {**_plan(fam, "LEFT_TO_RIGHT"), **extra}}
                     for i, fam in enumerate(["PAN", "TRACK", "PAN", "TRACK", "PAN"], 1)]
            validate_camera_sequence(units)  # same direction five times, alternating family: allowed
            units[1]["camera_plan"] = {**_plan("PAN", "LEFT_TO_RIGHT"), **extra}
            with self.assertRaisesRegex(ValueError, "repeat camera motion PAN:LEFT_TO_RIGHT"):
                validate_camera_sequence(units)  # the pre-existing identical-move check stays

    def test_grouping_builder_does_not_balance_stamped_directions(self):
        from tools.build_video_unit_grouping_spec import _group_camera_direction
        stamped = [{"prompt_spec": {"camera_plan": {**_plan("PAN", "LEFT_TO_RIGHT"),
                                                    "camera_grammar": "CAMERA_GRAMMAR_V1"}}}]
        plain = [{"prompt_spec": {"camera_plan": _plan("PAN", "LEFT_TO_RIGHT")}}]
        self.assertIsNone(_group_camera_direction(stamped))
        self.assertEqual(_group_camera_direction(plain), "LEFT_TO_RIGHT")


class H3PromptTest(unittest.TestCase):
    def test_grammar_clause_only_for_stamped_plans(self):
        from tools import h3_provider_prompt_renderer as h3
        plain_locked, plain_move = _plan(), _plan("PAN", "LEFT_TO_RIGHT")
        self.assertEqual(h3._camera_grammar_clause(plain_locked), "")
        self.assertEqual(h3._camera_grammar_clause(plain_move), "")
        stamped_locked = {**plain_locked, "camera_grammar": "CAMERA_GRAMMAR_V1"}
        stamped_move = {**plain_move, "camera_grammar": "CAMERA_GRAMMAR_V1", "motion_motivation": "REVEAL"}
        locked_text = h3._camera_scoped(stamped_locked, {"start_framing": "the hall"})
        self.assertIn("a still, composed frame", locked_text)
        self.assertNotIn("composed frame", h3._camera_scoped(plain_locked, {"start_framing": "the hall"}))
        text = "camera: " + locked_text + "\nphysical_continuity: x"
        self.assertEqual(h3.locked_camera_move_conflicts(text), [])
        self.assertIn("a motivated move to reveal", h3._camera_scoped(stamped_move, {}))
        self.assertIn("a motivated move", h3._camera(stamped_move))


class ShotScaleGrammarTest(unittest.TestCase):
    def _eval(self, shots, scenes=None):
        return sdg.evaluate(_contract(shots, scenes=scenes), sdg.POLICY)

    def test_new_location_needs_an_establishing_framing_in_its_first_two_shots(self):
        scenes = [{"scene_id": "SC1", "location_id": "LOC-HALL"}, {"scene_id": "SC2", "location_id": "LOC-YARD"}]
        r = self._eval([
            _shot("S1", scale="CLOSE_UP", seconds=2.0, action="a hand on the latch"),
            _shot("S2", scale="WIDE", action="Mara steps into the hall"),
            _shot("S3", scene="SC2", scale="MEDIUM", action="Mara walks into the yard"),
            _shot("S4", scene="SC2", scale="CLOSE_UP", seconds=2.0, action="her eyes"),
        ], scenes=scenes)
        self.assertEqual(r["failures"], [])
        codes = _notes(r)
        self.assertNotIn("R10_NEW_LOCATION_WITHOUT_ESTABLISHING_FRAMING:SC1", codes)  # hook close-up then wide
        self.assertIn("R10_NEW_LOCATION_WITHOUT_ESTABLISHING_FRAMING:SC2", codes)
        self.assertIn("R10", r["fix_hints"])

    def test_same_location_next_scene_needs_no_new_establishing_shot(self):
        scenes = [{"scene_id": "SC1", "location_id": "LOC-HALL"}, {"scene_id": "SC2", "location_id": "LOC-HALL"}]
        r = self._eval([_shot("S1", scale="WIDE", action="Mara walks in"),
                        _shot("S2", scene="SC2", scale="MEDIUM", action="Mara sits down")], scenes=scenes)
        self.assertEqual(r["failures"], [])

    def test_three_shots_at_one_scale_is_a_note(self):
        r = self._eval([_shot("S1", scale="WIDE", action="Mara walks in"),
                        _shot("S2", scale="MEDIUM", action="Mara sits down", side="AXIS_A"),
                        _shot("S3", scale="MEDIUM", action="Mara stands up", side="AXIS_B"),
                        _shot("S4", scale="MEDIUM", action="Mara turns around", side="NEUTRAL")])
        self.assertEqual(r["failures"], [])
        self.assertIn("R11_SAME_SHOT_SCALE_RUN:MEDIUMx3", _notes(r))
        self.assertIn("R11", r["fix_hints"])

    def test_missing_listener_reaction_is_advisory_only(self):
        r = self._eval([
            _shot("S1", scale="WIDE", dialogue="Mara: Who sent you?", listener="CHAR-B", cast=("CHAR-A", "CHAR-B")),
            _shot("S2", scale="MEDIUM", action="Mara walks to the door", cast=("CHAR-A",)),
        ])
        self.assertEqual(r["failures"], [])
        self.assertIn("S1:R12_DIALOGUE_LISTENER_WITHOUT_REACTION_COVERAGE:CHAR-B", r["advisories"])
        covered = self._eval([
            _shot("S1", scale="WIDE", dialogue="Mara: Who sent you?", listener="CHAR-B", cast=("CHAR-A", "CHAR-B")),
            _shot("S2", scale="CLOSE_UP", seconds=2.0, action="the stranger flinches", cast=("CHAR-B",)),
        ])
        self.assertEqual(covered["advisories"], [])

    def test_english_dialogue_is_timed_in_words(self):
        line = "Mara: The bell rang twelve times and nobody came."
        shots = [_shot("S1", scale="WIDE", seconds=4.0, dialogue=line)]
        r = sdg.evaluate(_contract(copy.deepcopy(shots), dialogue_language="en"), sdg.POLICY)
        self.assertFalse(any(c.startswith("R8_") for c in _codes(r)))  # 8 words / 2.7 wps + 0.5 s = 3.5 s
        letters = sdg.evaluate(_contract(copy.deepcopy(shots)), sdg.POLICY)  # no language: letter count
        self.assertTrue(any(c.startswith("R8_") for c in _codes(letters)))


class CutOpenerTest(unittest.TestCase):
    def _contract(self, mode, scene2="SC1", grammar=True):
        contract = _contract([
            _shot("S1", action="Mara walks in"), _shot("S2", action="Mara sits"),
            _shot("S3", scene=scene2, action="Mara stands"), _shot("S4", scene=scene2, action="Mara stands")],
            grammar=grammar,
            scenes=[{"scene_id": "SC1", "location_id": "LOC-HALL"}, {"scene_id": "SC2", "location_id": "LOC-HALL"}],
            internal_transition_authoring=[{"from_shot_id": "S2", "to_shot_id": "S3", "transition_mode": mode}])
        return contract

    def test_reason_follows_the_authored_transition(self):
        self.assertEqual(cg.opener_cut_reason(self._contract("HARD_CUT"), "S2", "S3"), "AUTHORED_HARD_CUT")
        self.assertIsNone(cg.opener_cut_reason(self._contract("CONTINUOUS_ACTION"), "S2", "S3"))
        self.assertEqual(cg.opener_cut_reason(self._contract("CONTINUOUS_ACTION", scene2="SC2"), "S2", "S3"),
                         "SCENE_CHANGE")

    def _inputs(self, tmp, contract):
        grouping = Path(tmp) / "grouping.json"
        grouping.write_text(json.dumps({"units": [
            {"unit_id": "U1", "editorial_shot_ids": ["S1", "S2"]},
            {"unit_id": "U2", "editorial_shot_ids": ["S3", "S4"]}]}), encoding="utf-8")
        anchors = {"units": [
            {"unit_id": "U1", "opening_anchor_contract": {"source": "NEW_EVENT_GENERATED_KEYFRAME"}},
            {"unit_id": "U2", "opening_anchor_contract": {"source": "CONTINUITY_DERIVED_KEYFRAME"}}]}
        return SimpleNamespace(contract=contract, episode="E07", grouping_plan_path=grouping, anchor_plan=anchors)

    def test_authored_cut_keeps_its_own_keyframe_continuous_keeps_the_tail(self):
        import build_keyframe_manifest as bkm
        with tempfile.TemporaryDirectory() as tmp:
            cut = self._inputs(tmp, self._contract("REACTION_CUT"))
            self.assertEqual(bkm.derived_opener_shot_ids(cut), set())
            self.assertEqual(bkm.derived_opener_shot_ids(cut, apply_camera_grammar=False), {"S3"})
            self.assertEqual(bkm.camera_grammar_cut_openers(cut)["U2"]["reason"], "AUTHORED_REACTION_CUT")
            continuous = self._inputs(tmp, self._contract("CAMERA_REFRAME"))
            self.assertEqual(bkm.derived_opener_shot_ids(continuous), {"S3"})

    def test_old_episode_keeps_the_tail_chain_at_an_authored_cut(self):
        import build_keyframe_manifest as bkm
        with tempfile.TemporaryDirectory() as tmp:
            old = self._inputs(tmp, self._contract("HARD_CUT", grammar=False))
            self.assertEqual(bkm.derived_opener_shot_ids(old), {"S3"})
            self.assertEqual(bkm.camera_grammar_cut_openers(old), {})


class AdvisoryPrevisTest(unittest.TestCase):
    def test_camera_grammar_episode_gets_an_advisory_previs_that_never_blocks(self):
        import episode_previs
        import nalu_pipeline
        from tools.tests.test_previs_gate_wiring import _Ctx, _Paths, _contract as previs_contract, _grouping
        contract = previs_contract(**GRAMMAR)
        contract["audio_contract"]["dialogue_units"].append(  # a machine failure under the BLOCK gate
            {"shot_id": "S2", "speaker_id": "CHAR-A", "text": "甲：走 吧"})
        policy = {"enabled_episodes": [], "enabled_from_episode": None, "gate_on_machine_failures": True}
        with tempfile.TemporaryDirectory() as tmp:
            for grouping in (_grouping(), None):
                paths = _Paths(Path(tmp), contract, grouping)
                if grouping is None:
                    paths.grouping_plan.unlink(missing_ok=True)
                with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: policy), \
                     mock.patch.object(episode_previs, "policy_settings", lambda: policy):
                    row = nalu_pipeline.previs_gate(_Ctx(paths), "S5")
                self.assertFalse(row["blocked"])
                self.assertEqual(row["mode"], "CAMERA_GRAMMAR_V1_ADVISORY")
            # with the grouping plan: findings recorded, mode ADVISORY, review questions issued
            paths = _Paths(Path(tmp), contract, _grouping())
            with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: policy), \
                 mock.patch.object(episode_previs, "policy_settings", lambda: policy):
                row = nalu_pipeline.previs_gate(_Ctx(paths), "S5")
            self.assertEqual(row["status"], "ADVISORY_FINDINGS")
            self.assertEqual(row["machine_failure_mode"], "ADVISORY")
            self.assertFalse(row["director_review"]["blocking"])
            # an episode outside both policies is untouched
            paths = _Paths(Path(tmp), previs_contract(), _grouping())
            with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: policy), \
                 mock.patch.object(episode_previs, "policy_settings", lambda: policy):
                self.assertEqual(nalu_pipeline.previs_gate(_Ctx(paths), "S5")["status"], "NOT_ENABLED")


if __name__ == "__main__":
    unittest.main()
