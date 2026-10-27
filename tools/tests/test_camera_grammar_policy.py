"""CAMERA_GRAMMAR_V1 (line owner 2026-10-22): no forced motion, no direction alternation, real cuts.

Adds no blocking check.  Contracts without ``camera_grammar_policy`` keep their verdicts and prompts.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "lines" / "nalu" / "runtime" / "tools", _ROOT / "tools", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import camera_grammar_policy as cg  # noqa: E402
import static_design_gate as sdg  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.grouped_camera_contract import validate_camera_sequence  # noqa: E402

MARK = {"camera_grammar": "CAMERA_GRAMMAR_V1"}


def _plan(family="LOCKED", direction="NONE", scale="MEDIUM"):
    return {"shot_scale": scale, "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
            "motion_family": family, "motion_direction": direction, "lens_intent": "35mm human eye",
            "axis_relation": "stays on the A side", "start_framing": "the hall from the door" + (
                "" if family == "LOCKED" else ", left"),
            "end_framing": "the hall from the door", "motivation": "keeps the room readable"}


def _shot(sid, seconds=5.0, dialogue=None, scene="SC1"):
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds,
            "prompt_spec": {"camera_plan": _plan(), "dialogue": dialogue, "action": {"primary_action": "x"}}}


class SwitchTest(unittest.TestCase):
    def test_declaration_listing_and_opt_out(self):
        self.assertTrue(cg.active({"episode": "E07", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}))
        self.assertFalse(cg.active({"episode": "E07"}))
        self.assertFalse(cg.active({"episode": "E07", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}))

    def test_finalize_stamp_is_idempotent_and_respects_a_declared_value(self):
        from tools import storyclaw_writer_workflow as workflow
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"schema": "x", "episode": "E02", "shots": []}), encoding="utf-8")
            self.assertTrue(workflow._stamp_camera_grammar_policy(path))
            self.assertEqual(list(json.loads(path.read_text()))[:3], ["schema", "episode", "camera_grammar_policy"])
            self.assertFalse(workflow._stamp_camera_grammar_policy(path))
        opted = {"episode": "E02", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}
        self.assertFalse(cg.stamp_contract(opted))


class StaticDesignGateTest(unittest.TestCase):
    SHOTS = [_shot("S1"), _shot("S2"), _shot("S3", seconds=6.0, dialogue="Mara：你是谁派来的")]

    def _eval(self, **extra):
        return sdg.evaluate({"episode": "E07", "shots": json.loads(json.dumps(self.SHOTS)), **extra}, sdg.POLICY)

    def test_old_contract_still_blocks_static_shots(self):
        result = self._eval()
        self.assertNotIn("advisories", result)
        self.assertTrue(any("R3_" in f for f in result["failures"]))
        self.assertTrue(any("R6_" in f for f in result["failures"]))

    def test_marked_contract_only_advises_on_static_shots(self):
        result = self._eval(camera_grammar_policy="CAMERA_GRAMMAR_V1")
        self.assertEqual(result["failures"], ["S3:R5_SAME_AXIS_SCALE_RUN"])  # R5/R8 still block
        codes = " ".join(result["advisories"])
        for code in ("R1_", "R2_", "R3_", "R4_", "R6_", "R7_"):
            self.assertIn(code, codes)

    def test_english_dialogue_is_timed_in_words(self):
        shots = [{**_shot("S1", seconds=4.0, dialogue="Mara: The bell rang twelve times and nobody came.")}]
        marked = sdg.evaluate({"episode": "E07", "shots": shots, "dialogue_language": "en",
                               "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}, sdg.POLICY)
        self.assertFalse(any("R8_" in f for f in marked["failures"]))
        old = sdg.evaluate({"episode": "E07", "shots": shots, "dialogue_language": "en"}, sdg.POLICY)
        self.assertTrue(any("R8_" in f for f in old["failures"]))


class DirectionCapsTest(unittest.TestCase):
    def _units(self, extra):
        return [{"unit_id": f"U{i}", "camera_plan": {**_plan(fam, "LEFT_TO_RIGHT"), **extra}}
                for i, fam in enumerate(["PAN", "TRACK", "PAN", "TRACK", "PAN"], 1)]

    def test_marked_plans_skip_direction_caps_but_not_identical_moves(self):
        with self.assertRaisesRegex(ValueError, "repeat camera direction"):
            validate_camera_sequence(self._units({}))
        units = self._units(MARK)
        validate_camera_sequence(units)
        units[1]["camera_plan"] = {**_plan("PAN", "LEFT_TO_RIGHT"), **MARK}
        with self.assertRaisesRegex(ValueError, "repeat camera motion PAN:LEFT_TO_RIGHT"):
            validate_camera_sequence(units)

    def test_grouping_builder_ignores_marked_directions(self):
        from tools.build_video_unit_grouping_spec import _group_camera_direction
        self.assertIsNone(_group_camera_direction([{"prompt_spec": {"camera_plan": {**_plan("PAN", "LEFT_TO_RIGHT"), **MARK}}}]))
        self.assertEqual(_group_camera_direction([{"prompt_spec": {"camera_plan": _plan("PAN", "LEFT_TO_RIGHT")}}]),
                         "LEFT_TO_RIGHT")


class H3PromptTest(unittest.TestCase):
    def test_clause_only_for_marked_plans_and_no_locked_move_conflict(self):
        self.assertEqual(h3._camera_grammar_clause(_plan()), "")
        locked = h3._camera_scoped({**_plan(), **MARK}, {"start_framing": "the hall"})
        # provider-expert wording (2026-10-26) replaced "a still, composed frame ... no drift"
        self.assertIn("locked camera; fixed camera position: no push in, no pull out, no pan, no tilt, no tracking",
                      locked)
        self.assertIn("the action plays inside the frame", locked)
        self.assertEqual(h3.locked_camera_move_conflicts("camera: " + locked + "\nphysical_continuity: x"), [])
        self.assertIn("a motivated move", h3._camera({**_plan("PAN", "LEFT_TO_RIGHT"), **MARK}))


class CutOpenerTest(unittest.TestCase):
    def _inputs(self, tmp, mode, grammar=True, scene2="SC1"):
        grouping = Path(tmp) / "grouping.json"
        grouping.write_text(json.dumps({"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1", "S2"]},
                                                  {"unit_id": "U2", "editorial_shot_ids": ["S3", "S4"]}]}))
        contract = {"episode": "E07", "shots": [_shot("S1"), _shot("S2"), _shot("S3", scene=scene2),
                                                _shot("S4", scene=scene2)],
                    "internal_transition_authoring": [{"from_shot_id": "S2", "to_shot_id": "S3",
                                                       "transition_mode": mode}]}
        if grammar:
            contract["camera_grammar_policy"] = "CAMERA_GRAMMAR_V1"
        anchors = {"units": [{"unit_id": "U2", "opening_anchor_contract": {"source": "CONTINUITY_DERIVED_KEYFRAME"}}]}
        return SimpleNamespace(contract=contract, episode="E07", grouping_plan_path=grouping, anchor_plan=anchors)

    def test_authored_cut_or_scene_change_keeps_own_keyframe(self):
        import build_keyframe_manifest as bkm
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bkm.derived_opener_shot_ids(self._inputs(tmp, "REACTION_CUT")), set())
            self.assertEqual(bkm.derived_opener_shot_ids(self._inputs(tmp, "CONTINUOUS_ACTION", scene2="SC2")), set())
            self.assertEqual(bkm.derived_opener_shot_ids(self._inputs(tmp, "CAMERA_REFRAME")), {"S3"})
            self.assertEqual(bkm.derived_opener_shot_ids(self._inputs(tmp, "HARD_CUT", grammar=False)), {"S3"})


if __name__ == "__main__":
    unittest.main()
