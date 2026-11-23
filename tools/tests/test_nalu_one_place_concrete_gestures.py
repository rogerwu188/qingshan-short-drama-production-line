"""JA-01 E08 (device 1485, anime, 2026-11-22): one conversation = one place; concrete, varied gestures.

1) Location: one three-person conversation was split over scene_ids with different location_ids (council hall /
   market / courtyard) -- the first pacing check rewarded "scenes per 2 minutes".  Now: motivated scene changes,
   CONVERSATION_SPLIT_ACROSS_LOCATIONS / SCENE_SPLIT_SAME_LOCATION in the bounded free revision loop, a scene
   location receipt, and a "background / location only" reference on tail-rejected own-keyframe units.
2) Gestures: every line was "<Name> delivers the line with a clear anime gesture and visible posture change" and H3
   raised the same index finger each time -- PERFORMANCE_VARIETY_V1 now runs on every path (V1 renderer included),
   tracks gesture families across all characters, never defaults to pointing, and rebuilds placeholder actions.

Offline: no provider call, no paid call.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (str(ROOT), str(RT), str(ROOT / "tools"), str(ROOT / "skills" / "nalu-claude-code" / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_nalu_preproduction as bnp  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as grp  # noqa: E402
import scene_location_lock as sll  # noqa: E402
import script_pacing_check as sp  # noqa: E402
from tools import h3_english_contract_io as io  # noqa: E402
from tools import performance_variety as pv  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.tests.test_h3_shot_scope_v1 import build  # noqa: E402

TEMPLATE = "{n} delivers the line with a clear anime gesture and visible posture change."
ENTRY = "standing facing the immediate conflict"
EXIT = "gesture settles while the conflict remains visible"
CAST = [{"character": c, "character_id": f"CHAR-{c.upper()}"} for c in ("Claire", "Rei", "Ken")]


def _shot(sid, scene, speaker="", *, seconds=4.0, cast=None, silent_kind=None, action=""):
    spec = {"shot_id": sid, "cast": list(CAST if cast is None else cast),
            "camera_plan": {"motion_family": "LOCKED", "shot_scale": "MEDIUM"},
            "dialogue": f"{speaker}: line {sid}." if speaker else "",
            "action": {"primary_action": action or (TEMPLATE.format(n=speaker) if speaker else "")}}
    if silent_kind == "ESTABLISHING":
        spec["cast"], spec["camera_plan"]["shot_scale"] = [], "WIDE"
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds, "entry_state": ENTRY,
            "completion_state": EXIT, "prompt_spec": spec}


def e08_contract():
    """The device shape: S01 and S02 in the council hall, then the same Claire / Rei conversation goes on in the
    market (S03) and the courtyard (S04); locations live on scene_states, not on the shots."""
    shots = [_shot("E08-S01-01", "E08-S01", "Claire"), _shot("E08-S01-02", "E08-S01", "Ken"),
             _shot("E08-S02-01", "E08-S02", "Rei"), _shot("E08-S02-02", "E08-S02", "Claire"),
             _shot("E08-S02-03", "E08-S02", "Rei"),
             _shot("E08-S03-01", "E08-S03", "Claire"), _shot("E08-S03-02", "E08-S03", "Rei"),
             _shot("E08-S03-03", "E08-S03", "Claire"),
             _shot("E08-S04-01", "E08-S04", "Rei"), _shot("E08-S04-02", "E08-S04", "Claire")]
    return {"schema": "qingshan.generation_contract.v3", "episode": "E08", "dialogue_language": "en",
            "character_entities": [{"character_id": c["character_id"], "canonical_name": c["character"]} for c in CAST],
            "scene_states": [{"scene_id": "E08-S01", "location_id": "ACADEMY_COUNCIL", "time_id": "DAY"},
                             {"scene_id": "E08-S02", "location_id": "ACADEMY_COUNCIL", "time_id": "DAY"},
                             {"scene_id": "E08-S03", "location_id": "ROYAL_MARKET", "time_id": "DAY"},
                             {"scene_id": "E08-S04", "location_id": "ACADEMY_COURTYARD", "time_id": "DAY"}],
            "shots": shots}


class ConversationSplitTest(unittest.TestCase):
    def test_device_case_is_reported_and_revised(self):
        report = sp.evaluate(e08_contract())
        m = report["metrics"]
        kinds = [c["kind"] for c in m["scene_changes"]]
        self.assertEqual(kinds, ["SAME_PLACE_SPLIT", "CONVERSATION_SPLIT", "CONVERSATION_SPLIT"])
        self.assertIn("CONVERSATION_SPLIT_ACROSS_LOCATIONS:E08-S02>E08-S03", report["failures"])
        self.assertIn("CONVERSATION_SPLIT_ACROSS_LOCATIONS:E08-S03>E08-S04", report["failures"])
        self.assertIn("SCENE_SPLIT_SAME_LOCATION:E08-S01>E08-S02", report["failures"])
        self.assertEqual(m["motivated_scene_changes"], 0)          # relocations never count
        for code in ("CONVERSATION_SPLIT_ACROSS_LOCATIONS", "SCENE_SPLIT_SAME_LOCATION", "VISUAL_VARIETY_LOW"):
            self.assertIn(code, report["fixes"])
        # part of the bounded free revision loop
        with tempfile.TemporaryDirectory() as tmp:
            decision = sp.decide(report, sp.contract_sha(e08_contract()), Path(tmp) / "rounds.json")
        self.assertEqual(decision["decision"], "REVISE")
        self.assertTrue(any("CONVERSATION_SPLIT_ACROSS_LOCATIONS" in b for b in sp.blocker_codes(report, decision)))

    def test_motivated_changes(self):
        c = e08_contract()
        c["shots"].insert(5, _shot("E08-S03-00", "E08-S03", silent_kind="ESTABLISHING"))   # the arrival is shown
        self.assertEqual(sp.measure(c)["scene_changes"][1]["kind"], "MOTIVATED_SHOWN")
        c = e08_contract()
        c["scene_states"][2]["time_id"] = "NIGHT"                                           # a time skip
        self.assertEqual(sp.measure(c)["scene_changes"][1]["kind"], "MOTIVATED_TIME_CHANGE")
        c = e08_contract()
        c["pacing"] = {"scene_plan": [{"scene_id": "E08-S03", "change_reason": "TIME_SKIP"}]}  # told by a line
        self.assertEqual(sp.measure(c)["scene_changes"][1]["kind"], "MOTIVATED_TIME_CHANGE")
        c = e08_contract()                                    # one shared person, new partner: a new event (S-04)
        for s in c["shots"][5:8]:
            s["prompt_spec"]["dialogue"] = s["prompt_spec"]["dialogue"].replace("Rei:", "Ken:")
        self.assertEqual(sp.measure(c)["scene_changes"][1]["kind"], "MOTIVATED_NEW_EVENT")

    def test_relocating_a_conversation_is_not_rewarded(self):
        split = e08_contract()
        merged = deepcopy(split)
        for row in merged["scene_states"]:
            row["location_id"] = "ACADEMY_COUNCIL"
        for s in merged["shots"]:
            s["scene_id"] = "E08-S01"
        a, b = sp.measure(split), sp.measure(merged)
        self.assertEqual(a["visual_variety_count"], b["visual_variety_count"])   # the move added nothing
        self.assertEqual(b["scene_changes"], [])
        self.assertFalse(any(f.startswith(("CONVERSATION_SPLIT", "SCENE_SPLIT", "SCENE_STATIC"))
                             for f in sp.evaluate(merged)["failures"]))
        # in-place variety satisfies the visual-variety target without a new location
        for i, s in enumerate(merged["shots"]):
            s["prompt_spec"]["action"]["primary_action"] = "Claire grabs the ledger and shoves it at Rei."
            if i % 3 == 0:
                s["prompt_spec"]["space"] = {"location": "ACADEMY_COUNCIL", "subspace": f"SUB-{i}"}
        self.assertGreaterEqual(sp.measure(merged)["visual_variety_count"], sp.measure(merged)["required_visual_variety"])

    def test_placeholder_acting_is_revised(self):
        report = sp.evaluate(e08_contract())
        self.assertTrue(any(f.startswith("PERFORMANCE_PLACEHOLDER") for f in report["failures"]))
        self.assertIn("PERFORMANCE_PLACEHOLDER", report["fixes"])
        c = e08_contract()
        moves = ["tilts her head", "looks away, then back", "takes a half step closer", "crosses her arms",
                 "turns half away", "adjusts her sleeve", "touches the ledger", "squares his shoulders",
                 "lets out a breath", "glances at Ken"]
        for s, move in zip(c["shots"], moves):
            s["prompt_spec"]["action"]["primary_action"] = move
            s["completion_state"] = "the line lands"
        self.assertFalse(any(f.startswith("PERFORMANCE_PLACEHOLDER") for f in sp.evaluate(c)["failures"]))


class SceneLocationTest(unittest.TestCase):
    def _editorial(self):
        def shot(sid, scene, loc, cast):
            return {"shot_id": sid, "scene_id": scene,
                    "prompt_spec": {"space": {"location": loc}, "scene_state": {"time": "DAY", "lighting": "warm"},
                                    "cast": [{"character_id": c} for c in cast]}}
        return {"shots": [shot("E08-S02-01", "E08-S02", "ACADEMY_COUNCIL", []),
                          shot("E08-S02-02", "E08-S02", "ACADEMY_COUNCIL", ["CHAR-CLAIRE", "CHAR-REI", "CHAR-KEN"]),
                          shot("E08-S02-03", "E08-S02", "ACADEMY_COUNCIL", ["CHAR-REI"]),
                          shot("E08-S02-04", "E08-S02", "ACADEMY_COUNCIL", ["CHAR-CLAIRE"])],
                "scene_location_lock": {}}

    def test_units_of_one_scene_share_the_place(self):
        ed = self._editorial()
        self.assertEqual(sll.scene_location_receipt(ed["shots"])["violations"], [])
        bad = deepcopy(ed["shots"])
        bad[2]["prompt_spec"]["space"]["location"] = "ROYAL_MARKET"
        self.assertEqual(sll.scene_location_receipt(bad)["violations"],
                         ["SCENE_LOCATION_NOT_SHARED:E08-S02:E08-S02-03:ROYAL_MARKET!=ACADEMY_COUNCIL"])
        self.assertEqual(sll.scene_location_receipt(bad, {"E08-S02-03": {"location_id": "ROYAL_MARKET"}})["violations"],
                         [])   # a declared cross-cut keeps its own place

    def test_tail_rejected_unit_gets_a_location_only_reference(self):
        ed = self._editorial()
        with tempfile.TemporaryDirectory() as tmp:
            kf = Path(tmp)
            for sid in ("E08-S02-01", "E08-S02-02", "E08-S02-03", "E08-S02-04"):
                (kf / f"{sid}-keyframe-v1.png").write_bytes(b"png")
            unit = {"unit_id": "E08-VU-009", "reference_image_paths": [str(kf / "E08-S02-04-keyframe-v1.png")],
                    "opening_anchor_contract": {"start_frame_source": sll.TAIL_REJECTED_START_FRAME_SOURCE}}
            # no plate: the scene's own keyframe that shows nobody else (the empty establishing view), never the
            # three-person two-shot (another character's face -> #286 identity swap)
            ref = sll.location_reference_for_unit(unit, ["E08-S02-04"], ed)
            self.assertEqual((ref["source"], ref["source_shot_id"]), ("SCENE_KEYFRAME", "E08-S02-01"))
            plate = kf / "LOC_PLATE.png"
            plate.write_bytes(b"plate")
            ref = sll.location_reference_for_unit(unit, ["E08-S02-04"], ed, scene_plate=lambda loc: plate)
            self.assertEqual((ref["source"], ref["path"]), ("LOCKED_SCENE_PLATE", str(plate)))
            self.assertIsNone(sll.location_reference_for_unit({**unit, "opening_anchor_contract": {}},
                                                              ["E08-S02-04"], ed))
            # wired into the H3 compile anchor: aligned role / key / entity rows, under the reference cap
            anchor = {"units": [{**deepcopy(unit), "reference_image_task_keys": ["E08-S02-04"],
                                 "anchor_count_decision": {"anchor_roles": ["CONTINUITY_DERIVED_ENTRY_STATE"]},
                                 "reference_entity_bindings": [None]}]}
            plan = {"units": [{"unit_id": "E08-VU-009", "editorial_shot_ids": ["E08-S02-04"]}]}
            with mock.patch.object(bnp, "_locked_scene_plate", return_value=None):
                rows = bnp.append_h3_scene_location_references(anchor, plan, ed, episode="E08")
            u = anchor["units"][0]
            self.assertEqual(len(rows), 1)
            self.assertEqual(u["anchor_count_decision"]["anchor_roles"][-1], sll.LOCATION_REFERENCE_ROLE)
            self.assertEqual(len(u["reference_image_paths"]), len(u["reference_image_task_keys"]))
            self.assertEqual(len(u["reference_image_paths"]), len(u["reference_entity_bindings"]))
            self.assertEqual(u["planned_reference_image_count"], 2)
            # an episode built before the lock (no marker) keeps its reference set
            old = deepcopy(anchor)
            self.assertEqual(bnp.append_h3_scene_location_references(
                old, plan, {k: v for k, v in ed.items() if k != "scene_location_lock"}, episode="E08"), [])

    def test_renderer_names_the_location_reference(self):
        A = "CHAR-TEST-ALPHA"
        unit, plan = build([{"cast": [A], "speaker": A}])
        unit["reference_images"].append({"path": "scene.png", "role": sll.LOCATION_REFERENCE_ROLE})
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("@Image2: this scene's location, background only", text)


class GestureVarietyTest(unittest.TestCase):
    def test_template_phrases_are_generic(self):
        for text in (TEMPLATE.format(n="Claire"), EXIT, "raises one index finger", "gestures emphatically"):
            self.assertTrue(pv.is_generic_gesture(text), text)
        for text in ("tilts the head slightly", "folds the arms across the chest", "glances away for a beat"):
            self.assertFalse(pv.is_generic_gesture(text), text)
        texts = [TEMPLATE.format(n=n) for n in ("Claire", "Rei", "Ken", "Claire")]
        self.assertTrue(pv.placeholder_beat_texts(texts, ["Claire", "Rei", "Ken"]))

    def _shots(self, n=12, speakers=("CHAR-A", "CHAR-B", "CHAR-C"), body=""):
        return [{"shot_id": f"S{i:02d}", "scene_id": "SC1", "shot_size": "MEDIUM",
                 "prompt_spec": {"dialogue": "X: well.", "camera_plan": {"shot_scale": "MEDIUM"},
                                 "cast": [{"character_id": c} for c in speakers],
                                 "role_semantic_disambiguation": {"dialogue_speaker_id": speakers[i % len(speakers)]},
                                 "action": {"primary_action": TEMPLATE.format(n="X"),
                                            **({"performance": {"body_action": body}} if body else {})}}}
                for i in range(n)]

    def test_tracker_spans_characters_and_never_points_by_default(self):
        receipt = pv.assign_episode(self._shots(18))
        fams = [r["family"] for r in receipt["rows"]]
        self.assertEqual(len({r["speaker_id"] for r in receipt["rows"]}), 3)
        for i, fam in enumerate(fams):                       # whoever speaks, no family twice within the window
            self.assertNotIn(fam, fams[max(0, i - pv.WINDOW + 1):i])
        self.assertNotIn(pv.POINT_FAMILY, fams)
        self.assertEqual(receipt["violations"], [])
        authored = self._shots(1)
        authored[0]["prompt_spec"]["action"]["performance"] = {"business_en": "points at him with one finger"}
        row = pv.assign_episode(authored)["rows"][0]
        self.assertEqual(row["source"], "AUTHORED_POINTING_REPLACED")
        generic = self._shots(1)
        generic[0]["prompt_spec"]["action"]["performance"] = {"business_en": "makes a clear anime gesture"}
        self.assertEqual(pv.assign_episode(generic)["rows"][0]["source"], "AUTHORED_GENERIC_REPLACED")
        scripted = pv.assign_episode(self._shots(1, body="指着周默"))["rows"][0]
        self.assertEqual(scripted["family"], pv.POINT_FAMILY)          # the script asks for pointing

    def test_non_camera_grammar_performance_is_read(self):
        shots = self._shots(1)
        rows = pv.assign_episode(shots, performance_by_shot={"S00": {"business_en": "adjusts one cuff"}})["rows"]
        self.assertEqual((rows[0]["source"], rows[0]["family"]), ("AUTHORED_BUSINESS_EN", "cuff"))
        self.assertNotIn("performance", shots[0]["prompt_spec"]["action"])     # never copied into the spec

    def test_v1_renderer_replaces_the_template(self):
        A, B = "CHAR-TEST-ALPHA", "CHAR-TEST-BETA"
        unit, plan = build([{"cast": [A, B], "speaker": A}])
        before, _ = render_h3_prompt(unit, plan)
        beat = unit["h3_provider_english_contract"]["beats"][0]
        beat.update(primary_action=TEMPLATE.format(n="Alpha"), entry_state=ENTRY, exit_state=EXIT)
        unit["ordered_prompt_specs"][0]["action"] = {"performance_business_en": "tilts the head slightly",
                                                     "performance_business_family": "head_tilt",
                                                     "listener_business_en": {B: "nods once, slowly"}}
        text, _ = render_h3_prompt(unit, plan)
        self.assertNotIn("clear anime gesture", text)
        self.assertNotIn("gesture settles", text)
        self.assertIn("Alpha tilts the head slightly.", text)
        self.assertIn("Beta listens without speaking and nods once, slowly.", text)
        never = text.split("negative_constraints:", 1)[1]
        self.assertIn(pv.NEVER_POINTING, never)
        self.assertIn(pv.NEVER_STOCK, never)
        # authored, concrete action: kept, business added as its own sentence
        unit2, plan2 = build([{"cast": [A, B], "speaker": A}])
        unit2["ordered_prompt_specs"][0]["action"] = {"performance_business_en": "folds the arms",
                                                      "performance_business_family": "fold_arms"}
        text2, _ = render_h3_prompt(unit2, plan2)
        self.assertIn("While speaking, Alpha folds the arms.", text2)
        # no business on the spec (a grandfathered episode): bytes unchanged
        plain, _ = render_h3_prompt(*build([{"cast": [A, B], "speaker": A}]))
        self.assertEqual(plain, before)
        self.assertNotIn("index finger", plain)

    def test_variety_runs_on_every_new_episode_and_grandfathers_old_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "E08_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
            self.assertFalse(bnp.performance_variety_grandfathered(path))              # first build
            path.write_text(json.dumps({"shots": [{"shot_id": "a"}]}))
            self.assertTrue(bnp.performance_variety_grandfathered(path))               # built before the layer
            path.write_text(json.dumps({"shots": [{"shot_id": "a"}], "performance_variety": {"rows": []}}))
            self.assertFalse(bnp.performance_variety_grandfathered(path))
        src = (RT / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        self.assertNotIn("_pv.assign_episode(shots, entities) if camera_grammar else None", src)

    def test_english_request_carries_the_business_and_the_rule(self):
        self.assertIn("raised or pointing index finger", io.BEAT_TEXT_RULE)
        self.assertIn("same place", io.BEAT_TEXT_RULE)
        unit = {"ordered_prompt_specs": [{"action": {"performance_business_en": "tilts the head slightly"}}]}
        self.assertEqual(io._beat_business(unit, 1), "tilts the head slightly")
        self.assertEqual(io._beat_business(unit, 2), "")


class ReviewersSeeRepeatedGesturesTest(unittest.TestCase):
    def test_monotony_fires_on_the_e08_finding(self):
        self.assertIn("食指", grp.CLASS_TEXT["CRAFT-ACTING-MONOTONY"][1])
        self.assertIn("不同人物", grp.CLASS_TEXT["CRAFT-ACTING-MONOTONY"][1])
        self.assertIn("竖起食指", grp.build_pass_prompt("A", duration=60.0))      # pass A gives the lead
        self.assertIn("CRAFT-ACTING-MONOTONY", grp.build_pass_prompt("D", duration=60.0))
        for text in ("the same raised right index finger in many shots, by different characters",
                     "每个人说话都竖起食指"):
            self.assertEqual(ffr.classify(None, text), "ACTING_MONOTONY", text)
            self.assertEqual(ffr.classify("CRAFT-ACTING-MONOTONY", text), "ACTING_MONOTONY")
        codex = (ROOT / "skills" / "nalu-claude-code" / "scripts" / "codex_production.py").read_text(encoding="utf-8")
        self.assertIn("竖起食指", codex)
        self.assertIn("不同角色用同一个手势也算", codex)


if __name__ == "__main__":
    unittest.main()
