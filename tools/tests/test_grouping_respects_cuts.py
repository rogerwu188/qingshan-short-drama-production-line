"""CAMERA_GRAMMAR_V1 grouping (line owner 2026-10-22): a unit boundary at every authored cut where the
visible cast changes, never more than two distinct visible subjects per unit, units inside the provider
window.  No new gate; the old 1:1 / short-unit rules do not block stamped plans.  Unstamped manifests
group byte-identically."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "lines" / "nalu" / "runtime" / "tools", _ROOT / "tools", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import build_video_unit_grouping_spec as grouping  # noqa: E402
from tools import compile_video_unit_plan as cvp  # noqa: E402
from tools.video_unit_grouping_gate import evaluate  # noqa: E402

CAMERA = {"shot_scale": "MEDIUM", "lens_intent": "50mm", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
          "axis_relation": "不越轴", "motion_family": "LOCKED", "motion_direction": "NONE",
          "start_framing": "人物中景", "end_framing": "人物中景", "motivation": "让表演在稳定构图内发生"}


def _shot(sid, seconds, cast, mode="MOTIVATED_CUT", scene="S01", dialogue="", stamped=True, extra=()):
    camera = {**CAMERA, **({"camera_grammar": "CAMERA_GRAMMAR_V1"} if stamped else {})}
    shot = {"shot_id": f"E09-{scene}-{sid}", "scene_id": scene, "duration_seconds": seconds,
            "prompt_spec": {"cast": [{"character": c, "character_id": f"CHAR-{c}",
                                      "face_visibility": "FRONT_FACE_VISIBLE"} for c in cast],
                            "dialogue": dialogue, "action": {"primary_action": f"{sid} 动作"},
                            "camera_plan": camera}}
    if stamped:
        shot["incoming_transition_mode"] = mode
        shot["visible_subject_ids"] = [f"CHAR-{c}" for c in cast] + list(extra)
    return shot


def _manifest(shots, stamped=True):
    return {"episode": "E09", "model": "MiniMax-H3", "shots": shots,
            **({"camera_grammar_policy": "CAMERA_GRAMMAR_V1"} if stamped else {})}


def _units(manifest):
    _production, spec = grouping.build(manifest, "sha")
    return [[sid.split("-", 1)[1] for sid in g["editorial_shot_ids"]] for g in spec["groups"]], spec


# The lab E01 shape (writer 2026-10-22): single-subject shot/reverse coverage, every shot an authored cut.
LAB = [("01", 4.5, ["LA", "AG"]), ("02", 4, ["AG"], "REACTION_CUT"), ("03", 7, ["LA"])]
CLASSROOM = [("01", 4, ["LB", "HU"]), ("02", 4, ["WU"]), ("03", 3, ["WU"], "CONTINUOUS_ACTION"),
             ("04", 4, ["LB"], "REACTION_CUT"), ("05", 3.5, ["WU"])]


def _scene(rows, scene, stamped=True):
    return [_shot(r[0], r[1], r[2], *(r[3:] or ["MOTIVATED_CUT"]), scene=scene, stamped=stamped) for r in rows]


class CutRespectingGroupingTest(unittest.TestCase):
    def test_cast_changing_cuts_are_boundaries_and_same_cast_shots_share_a_unit(self):
        units, spec = _units(_manifest(_scene(LAB, "S01") + _scene(CLASSROOM, "S02")))
        self.assertEqual(units, [["S01-01"], ["S01-02"], ["S01-03"],
                                 ["S02-01"], ["S02-02", "S02-03"], ["S02-04"], ["S02-05"]])
        self.assertEqual(spec["grouping_policy"], "CAMERA_GRAMMAR_V1")
        self.assertEqual(spec["duration_policy_seconds"]["minimum"], 3.0)
        self.assertEqual(spec["duration_policy_seconds"]["maximum"], 15.0)

    def test_same_pair_shot_reverse_stays_in_one_unit(self):
        rows = [("01", 3, ["A", "B"]), ("02", 3, ["A", "B"], "REACTION_CUT")]
        units, _ = _units(_manifest(_scene(rows, "S01")))
        self.assertEqual(units, [["S01-01", "S01-02"]])

    def test_never_more_than_two_visible_subjects_even_without_a_cut(self):
        rows = [("01", 2.5, ["A"]), ("02", 2.5, ["B"], "CONTINUOUS_ACTION"), ("03", 2.5, ["C"], "CONTINUOUS_ACTION")]
        units, _ = _units(_manifest(_scene(rows, "S01")))
        self.assertEqual(units, [["S01-01", "S01-02"], ["S01-03"]])
        # a creature entity counts as a visible subject
        shots = _scene([("01", 3, ["A"]), ("02", 3, ["A"], "CONTINUOUS_ACTION")], "S01")
        shots[1]["visible_subject_ids"].extend(["PROP-WOLF", "CHAR-B"])
        units, _ = _units(_manifest(shots))
        self.assertEqual(units, [["S01-01"], ["S01-02"]])

    def test_window_long_single_shot_allowed_multi_shot_units_capped(self):
        rows = [("01", 12, ["A"]), ("02", 5, ["A"], "CONTINUOUS_ACTION"), ("03", 5, ["A"], "CONTINUOUS_ACTION")]
        units, spec = _units(_manifest(_scene(rows, "S01")))
        self.assertEqual(units, [["S01-01"], ["S01-02"], ["S01-03"]])
        self.assertEqual(spec["groups"][0]["duration_exception_reason"], "AUTHORED_SINGLE_SHOT")
        self.assertTrue(all(g["duration_seconds"] <= 8 for g in spec["groups"][1:]))

    def test_sub_minimum_shot_merges_with_its_cast_or_is_padded(self):
        rows = [("01", 5, ["A"]), ("02", 2, ["B"]), ("03", 2, ["B"], "CONTINUOUS_ACTION"), ("04", 5, ["C"])]
        units, _ = _units(_manifest(_scene(rows, "S01")))
        self.assertEqual(units, [["S01-01"], ["S01-02", "S01-03"], ["S01-04"]])
        rows = [("01", 5, ["A"]), ("02", 2, ["B"]), ("03", 5, ["C"])]
        units, spec = _units(_manifest(_scene(rows, "S01")))
        self.assertEqual(units, [["S01-01"], ["S01-02"], ["S01-03"]])
        self.assertEqual(spec["groups"][1]["duration_exception_reason"], "PROVIDER_MINIMUM_PADDED")
        production, spec = grouping.build(_manifest(_scene(rows, "S01")), "sha")
        with patch.object(cvp, "validate_transition_sequence", lambda units: None):
            plan = cvp.compile_grouping_spec(production, spec)
            cvp.validate_compiled_plan(production, plan)
        self.assertEqual(evaluate(plan)["status"], "PASS")
        try:
            import build_nalu_preproduction as bnp
        except Exception as exc:  # noqa: BLE001 - the engine module needs the full engine tree
            self.skipTest(f"build_nalu_preproduction not importable here: {exc}")
        projected = bnp.project_provider_slots(copy.deepcopy(plan))
        self.assertEqual([u["duration_seconds"] for u in projected["units"]], [5, 3, 5])

    def test_old_one_to_one_and_short_unit_rules_do_not_block_stamped_plans(self):
        rows = [(f"{i:02d}", 3.5, ["A"] if i % 2 else ["B"]) for i in range(1, 15)]
        production, spec = grouping.build(_manifest(_scene(rows, "S01")), "sha")
        self.assertEqual(len(spec["groups"]), 14)
        with patch.object(cvp, "validate_transition_sequence", lambda units: None):
            plan = cvp.compile_grouping_spec(production, spec)
            cvp.validate_compiled_plan(production, plan)
        self.assertEqual(evaluate(plan), {**evaluate(plan), "status": "PASS", "failures": []})
        unstamped = {k: v for k, v in plan.items() if k != "grouping_policy"}
        failures = evaluate(unstamped)["failures"]
        self.assertIn("editorial_shot_to_video_unit_one_to_one_forbidden", failures)
        self.assertIn("excessive_short_video_units", failures)


class UnstampedUnchangedTest(unittest.TestCase):
    # Expected groups computed with the pre-change grouping (origin/main df6e19b).
    EXPECTED = [["S01-01", "S01-02"], ["S01-03"], ["S02-01", "S02-02"], ["S02-03", "S02-04", "S02-05"]]

    def test_unstamped_manifest_groups_as_before(self):
        manifest = _manifest(_scene(LAB, "S01", stamped=False) + _scene(CLASSROOM, "S02", stamped=False),
                             stamped=False)
        units, spec = _units(manifest)
        self.assertEqual(units, self.EXPECTED)
        self.assertNotIn("grouping_policy", spec)
        self.assertEqual(spec["duration_policy_seconds"]["maximum"], 12)
        # the new per-shot fields alone never switch the policy on
        decorated = copy.deepcopy(manifest)
        for shot in decorated["shots"]:
            shot["incoming_transition_mode"] = "MOTIVATED_CUT"
            shot["visible_subject_ids"] = ["CHAR-X"]
        self.assertEqual(json.dumps(grouping.build(decorated, "sha")[1], sort_keys=True),
                         json.dumps(spec, sort_keys=True))


class EditorialFieldsTest(unittest.TestCase):
    def _build(self, stamped):
        try:
            import build_nalu_preproduction as bnp
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"build_nalu_preproduction not importable here: {exc}")
        shots = [{"shot_id": f"E01-S01-0{i}", "scene_id": "S1", "target_seconds": 3, "entry_state": "a",
                  "completion_state": "b",
                  "internal_transition_authoring": {"transition_mode": mode},
                  "prompt_spec": {"action": {"primary_action": "抬手"},
                                  "cast": [{"character": name, "character_id": f"CHAR-{name}"}]}}
                 for i, (mode, name) in enumerate((("MOTIVATED_CUT", "甲"), ("REACTION_CUT", "乙")), start=1)]
        contract = {"episode": "E01", "scene_states": [{"scene_id": "S1"}],
                    "character_entities": [{"character_id": "CHAR-甲", "canonical_name": "甲"},
                                           {"character_id": "CHAR-乙", "canonical_name": "乙"}],
                    "non_character_entities": [{"entity_id": "PROP-WOLF", "name": "狼", "kind": "CREATURE"}],
                    "shots": shots,
                    **({"camera_grammar_policy": "CAMERA_GRAMMAR_V1"} if stamped
                       else {"camera_grammar_policy": "LEGACY_FORCED_MOTION"})}
        plan_rows = [{"shot_id": s["shot_id"], "room_id": "R", "zone_id": "Z", "zone_ids": ["Z"], "angle_id": "A",
                      "axis_id": "X", "subspace_id": "SS", "global_space_map_id": "G",
                      "prop_ids": ["PROP-WOLF"] if s["shot_id"].endswith("2") else []} for s in shots]
        index = SimpleNamespace(episode_map_id="EGSM", rooms={"R": {"name": "屋"}}, zones={"Z": {"name": "区"}},
                                elements=lambda _r: [])
        engine = SimpleNamespace(dialogue_limit=50, dialogue_length=len)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "NALU_POLICY_PROFILE": "LEGACY_EPISODE_COMPAT"}, clear=False):
            root = Path(tmp)
            (root / "c.json").write_text("{}\n")
            (root / "g.json").write_text("{}\n")
            manifest, _ = bnp.build_editorial(contract, plan_rows, index, engine, "E01",
                                              root / "c.json", root / "g.json", root)
        return manifest

    def test_stamped_editorial_carries_cut_and_subject_inputs(self):
        manifest = self._build(True)
        self.assertEqual(manifest["camera_grammar_policy"], "CAMERA_GRAMMAR_V1")
        self.assertEqual([s["incoming_transition_mode"] for s in manifest["shots"]], ["MOTIVATED_CUT", "REACTION_CUT"])
        self.assertEqual(manifest["shots"][1]["visible_subject_ids"], ["CHAR-乙", "PROP-WOLF"])
        self.assertTrue(grouping.cut_grammar_active(manifest))

    def test_unstamped_editorial_has_no_new_fields(self):
        manifest = self._build(False)
        self.assertNotIn("camera_grammar_policy", manifest)
        self.assertFalse(any("incoming_transition_mode" in s or "visible_subject_ids" in s for s in manifest["shots"]))


if __name__ == "__main__":
    unittest.main()
