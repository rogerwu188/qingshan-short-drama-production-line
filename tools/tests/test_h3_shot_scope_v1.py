"""Shot-scope upgrade for the shared H3 renderer (synthetic entities only).

Covers the renderer-side cases of the partial-visibility leak incident:
entity-scoped partial clauses, visible speakers keep face/mouth, offscreen
voice, missing visibility, LOCKED vs moving camera serialization, multi-shot
boundaries, the leak checker (incident reproduction) and gate-off byte identity.
"""

from __future__ import annotations

from copy import deepcopy
import unittest

from tools import h3_provider_prompt_renderer as renderer
from tools.h3_provider_english_contract import SCHEMA as ENGLISH_SCHEMA
from tools.h3_provider_prompt_renderer import (
    locked_camera_move_conflicts,
    partial_clause_leaks,
    render_h3_prompt,
    shot_scope_active,
)

LEAKY_GLOBAL_CLAUSE = (
    " Cropped body parts belong to the named identity; do not widen the frame to reveal its face or full body."
)
SHA = "0" * 64
ENTITIES = {
    "CHAR-TEST-ALPHA": ("阿尔", "Alpha"),
    "CHAR-TEST-BETA": ("贝塔", "Beta"),
    "CHAR-TEST-CAT": ("灰猫", "Gray the cat"),
}

LOCKED = {
    "shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
    "motion_family": "LOCKED", "motion_direction": "NONE",
    "start_framing": "Alpha seated at the table, waist up, window behind",
    "end_framing": "Alpha seated at the table, waist up, window behind",
}
TRACK = {
    "shot_scale": "MEDIUM", "camera_height": "LOW", "camera_side": "AXIS_B",
    "motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT",
    "start_framing": "Beta enters frame left at the doorway",
    "end_framing": "Beta stops at the counter, framed waist up on the right third",
    "follow_subject": "Beta",
    "subject_to_keep": "Beta's face",
}


def _beat(index: int, start: float, end: float, *, dialogue: str = "") -> dict:
    return {
        "source_index": index, "start_seconds": start, "end_seconds": end,
        "entry_state": "e", "primary_action": "a", "exit_state": "x",
        "interaction_mode": "NONE", "dialogue": dialogue, "dialogue_delivery": {},
        "secondary_feedback": [],
    }


def _translated(index: int) -> dict:
    return {
        "entry_state": f"entry state {index}",
        "primary_action": f"primary action {index}",
        "exit_state": f"exit state {index}",
        "secondary_feedback": [],
    }


def build(
    beats_spec: list[dict], *, episode: str = "E64", camera_plan: dict | None = None,
    per_shot: list[dict] | None = None, transitions: list[dict] | None = None,
) -> tuple[dict, dict]:
    """beats_spec rows: {cast: [cid...], extent: {cid: value}, face: {cid: value},
    speaker: cid|None, offscreen: bool, shot_id: str}."""
    uid = f"{episode}-VU-T01"
    used = []
    for row in beats_spec:
        for cid in row.get("cast") or []:
            if cid not in used:
                used.append(cid)
        if row.get("speaker") and row["speaker"] not in used:
            used.append(row["speaker"])
    bindings = [
        {"reference_index": i, "entity_id": cid, "provider_entity_label": ENTITIES[cid][1],
         "exclusive_identity_owner": True}
        for i, cid in enumerate(used, 1)
    ]
    speakers = []
    beats, specs, roles, translated = [], [], [], []
    t = 0.0
    for index, row in enumerate(beats_spec, 1):
        dialogue = ""
        if row.get("speaker"):
            dialogue = f"{ENTITIES[row['speaker']][0]}：你好。"
            if row["speaker"] not in [s["character_id"] for s in speakers]:
                slot = used.index(row["speaker"]) + 1
                speakers.append({
                    "speaker": ENTITIES[row["speaker"]][0], "character_id": row["speaker"],
                    "provider_entity_label": ENTITIES[row["speaker"]][1],
                    "subject_token": f"SUBJECT_{slot}", "image_slot": f"@Image{slot}",
                    "speaker_slot": f"SPEAKER_{len(speakers) + 1}", "audio_slot": f"@Audio{len(speakers) + 1}",
                    "visible_speaker": not row.get("offscreen"), "lip_sync": not row.get("offscreen"),
                })
        beats.append(_beat(index, t, t + 3.0, dialogue=dialogue))
        t += 3.0
        shot_id = row.get("shot_id") or f"T-S{index:02d}"
        cast = [
            {"character": ENTITIES[cid][0], "character_id": cid,
             **({"face_visibility": row["face"][cid]} if cid in (row.get("face") or {}) else {})}
            for cid in row.get("cast") or []
        ]
        specs.append({
            "shot_id": shot_id, "cast": cast,
            "role_semantic_disambiguation": {
                "shot_id": shot_id, "entity_visible_extent": dict(row.get("extent") or {}),
            },
        })
        roles.append({
            "shot_id": shot_id,
            "entity_face_visibility": {c["character_id"]: c.get("face_visibility", "") for c in cast},
        })
        translated.append(_translated(index))
    plan = {
        "unit_id": uid, "model_family": "MINIMAX_H3", "duration_seconds": t,
        "execution_semantics_sha256": SHA, "immutable_contract_sha256": SHA,
        "camera_language_selection": {}, "motion_density_gate": {"status": "PASS"},
        "camera_plan": camera_plan if camera_plan is not None else ({} if per_shot else deepcopy(LOCKED)),
        "beats": beats, "role_bindings": roles, "sounds": {}, "environment_motion": [],
        "voice_bindings": [{"speaker": s["speaker"]} for s in speakers],
        "h3_crossmodal_speaker_binding": {
            "status": "PASS" if speakers else "NOT_APPLICABLE", "bindings": speakers, "failures": [],
        },
        "transition": {},
    }
    unit = {
        "unit_id": uid, "model": "MiniMax-H3",
        "reference_images": [{"path": f"ref{i}.png", "role": "CHARACTER_REFERENCE"} for i in range(1, len(used) + 1)],
        "provider_scope_projection": {"reference_identity_bindings": bindings},
        "ordered_prompt_specs": specs,
        "visual_culture_contract": {"provider_scene_domain": "REALITY_NORTHERN_SONG"},
        "h3_provider_english_contract": {
            "schema": ENGLISH_SCHEMA, "source_execution_semantics_sha256": SHA,
            "identity_prop_fact": "Synthetic identities", "space_weather_fact": "A synthetic room in clear daylight",
            "beats": translated,
        },
    }
    if per_shot is not None:
        unit["per_shot_camera_plans"] = deepcopy(per_shot)
    if transitions is not None:
        unit["internal_transition_contracts"] = deepcopy(transitions)
    return unit, plan


def beat_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if renderer._BEAT_LINE.match(line)]


def camera_block(text: str) -> str:
    return text.split("\ncamera: ", 1)[1].split("\nphysical_continuity:", 1)[0]


A, B, CAT = "CHAR-TEST-ALPHA", "CHAR-TEST-BETA", "CHAR-TEST-CAT"


class GateTest(unittest.TestCase):
    def test_policy_switch(self):
        self.assertTrue(shot_scope_active({"unit_id": "E64-VU-1", "model": "MiniMax-H3"}))
        self.assertTrue(shot_scope_active({"unit_id": "E70-VU-1"}))
        self.assertFalse(shot_scope_active({"unit_id": "E63-VU-1", "model": "MiniMax-H3"}))
        self.assertFalse(shot_scope_active({"unit_id": "E10-VU-1", "model": "seedance-2.0"}))


class VisibilityScopeTest(unittest.TestCase):
    def test_single_character_dialogue_keeps_face_and_mouth(self):
        unit, plan = build([{"cast": [A], "speaker": A}])
        text, receipt = render_h3_prompt(unit, plan)
        line = beat_lines(text)[0]
        self.assertIn("Alpha (SUBJECT_1, identity @Image1, lip owner SPEAKER_1", line)
        self.assertIn("opens the mouth in sync", line)
        self.assertIn("Alpha's face and mouth stay readable in frame while speaking", line)
        self.assertNotIn("do not reveal", text)
        self.assertNotIn("Visibility for this beat only", text)
        self.assertEqual(partial_clause_leaks(text, plan, unit), [])
        self.assertEqual(receipt["shot_scope"]["partial_visibility_rules"], [])

    def test_hands_only_insert_names_only_that_entity(self):
        unit, plan = build([{"cast": [A], "extent": {A: "HANDS_ONLY"}}])
        text, receipt = render_h3_prompt(unit, plan)
        line = beat_lines(text)[0]
        self.assertIn(
            "Visibility for this beat only: Alpha: only Alpha's hands in frame during this beat, "
            "do not reveal Alpha's face or full body.", line)
        self.assertNotIn("its face", text)
        self.assertEqual(text.count("do not reveal"), 1)
        rules = receipt["shot_scope"]["partial_visibility_rules"]
        self.assertEqual([(r["entity_id"], r["beat_index"], r["part"]) for r in rules], [(A, 1, "hands")])
        self.assertEqual(partial_clause_leaks(text, plan, unit), [])

    def test_same_beat_hands_only_and_normal_dialogue_are_independent(self):
        unit, plan = build([{"cast": [A, B], "extent": {A: "HANDS_ONLY"}, "speaker": B}])
        text, _ = render_h3_prompt(unit, plan)
        line = beat_lines(text)[0]
        self.assertIn("do not reveal Alpha's face or full body", line)
        self.assertNotIn("reveal Beta", text)
        self.assertIn("Beta's face and mouth stay readable in frame while speaking", line)
        self.assertIn("Beta (SUBJECT_2, identity @Image2, lip owner SPEAKER_1", line)
        self.assertEqual(partial_clause_leaks(text, plan, unit), [])

    def test_face_visibility_family_on_cast_is_read(self):
        unit, plan = build([{"cast": [A, B], "face": {A: "FOOT_ONLY_FACE_OUT_OF_FRAME"}}])
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Alpha: only Alpha's foot in frame during this beat", text)
        self.assertNotIn("reveal Beta", text)
        unit, plan = build([{"cast": [CAT], "face": {CAT: "FACE_OUT_OF_FRAME_CREATURE_ONLY"}}])
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Gray the cat: do not reveal Gray the cat's face during this beat", text)

    def test_offscreen_voice_not_forced_into_frame(self):
        unit, plan = build([{"cast": [A], "speaker": B, "offscreen": True}])
        text, _ = render_h3_prompt(unit, plan)
        line = beat_lines(text)[0]
        self.assertIn("Offscreen Beta", line)
        self.assertIn("do not show the offscreen speaker", line)
        self.assertNotIn("Beta's face and mouth stay readable", text)
        self.assertNotIn("opens the mouth", line)
        self.assertIn("this reference alone does not put Beta in frame", text)
        self.assertNotIn("render exactly one visible instance of Beta", text)
        self.assertEqual(partial_clause_leaks(text, plan, unit), [])

    def test_missing_visibility_is_not_a_face_prohibition(self):
        for extent in ({}, {A: ""}, {A: "AUTHORED_CAMERA_CROP"}, {A: "FULL_BODY"}):
            unit, plan = build([{"cast": [A, B], "extent": extent}])
            text, receipt = render_h3_prompt(unit, plan)
            self.assertNotIn("do not reveal", text)
            self.assertNotIn("out of frame", text)
            self.assertEqual(receipt["shot_scope"]["partial_visibility_rules"], [])
        for face in ("BACK_TO_CAMERA", "VISIBLE_PER_FRAME_CONTENT", "OFFSCREEN_VOICE_ONLY", "FULL_FACE_VISIBLE"):
            self.assertIsNone(renderer.partial_visibility_part(face))

    def test_visible_speaker_declared_partial_fails_closed(self):
        unit, plan = build([{"cast": [A], "extent": {A: "HANDS_ONLY"}, "speaker": A}])
        with self.assertRaisesRegex(ValueError, "H3_SHOT_SCOPE_CONFLICT:BEAT.1:CHAR-TEST-ALPHA"):
            render_h3_prompt(unit, plan)

    def test_partial_entity_without_english_label_fails_closed(self):
        unit, plan = build([{"cast": [A], "extent": {A: "HANDS_ONLY"}}])
        unit["provider_scope_projection"]["reference_identity_bindings"][0]["provider_entity_label"] = "阿尔"
        with self.assertRaisesRegex(ValueError, "H3_PARTIAL_VISIBILITY_ENGLISH_LABEL_MISSING"):
            render_h3_prompt(unit, plan)

    def test_multi_beat_rules_are_independent(self):
        unit, plan = build([
            {"cast": [A, CAT], "extent": {CAT: "PAWS_ONLY"}, "shot_id": "T-S01"},
            {"cast": [A], "speaker": A, "shot_id": "T-S02"},
            {"cast": [A, B], "extent": {B: "ARM_ONLY"}, "shot_id": "T-S03"},
        ], per_shot=[LOCKED, LOCKED, LOCKED])
        text, _ = render_h3_prompt(unit, plan)
        first, second, third = beat_lines(text)
        self.assertIn("only Gray the cat's paws in frame", first)
        self.assertNotIn("Beta", first)
        self.assertNotIn("do not reveal", second)
        self.assertIn("Alpha's face and mouth stay readable", second)
        self.assertIn("only Beta's arm in frame", third)
        self.assertNotIn("Gray the cat", third)
        self.assertNotIn("reveal Alpha", text)
        self.assertEqual(partial_clause_leaks(text, plan, unit), [])


class CameraSerializationTest(unittest.TestCase):
    def test_locked_camera_has_no_move_instruction(self):
        unit, plan = build([{"cast": [A]}])
        text, _ = render_h3_prompt(unit, plan)
        camera = camera_block(text)
        self.assertIn("locked camera with no camera movement", camera)
        self.assertIn("camera height=EYE_LEVEL; camera side=AXIS_A", camera)
        self.assertIn("hold the framing: Alpha seated at the table, waist up, window behind", camera)
        self.assertNotIn("execute the declared move", text)
        self.assertEqual(locked_camera_move_conflicts(text), [])

    def test_tracking_keeps_subject_and_start_end_framing(self):
        unit, plan = build([{"cast": [B]}], camera_plan=deepcopy(TRACK))
        text, receipt = render_h3_prompt(unit, plan)
        camera = camera_block(text)
        self.assertIn("one short lateral track; direction=LEFT_TO_RIGHT", camera)
        self.assertIn("the camera follows Beta", camera)
        self.assertIn("keep Beta's face in frame throughout the move", camera)
        self.assertIn("start framing: Beta enters frame left at the doorway", camera)
        self.assertIn(
            "the move lands on and holds the end framing: Beta stops at the counter, framed waist up on the right third",
            camera)
        self.assertNotIn("locked camera", camera)
        self.assertNotIn("execute the declared move", text)
        self.assertEqual(receipt["shot_scope"]["camera_shots"][0]["fields"],
                         ["end_framing", "follow_subject", "start_framing", "subject_to_keep"])

    def test_no_framing_invented_when_absent(self):
        bare = {"shot_scale": "WIDE", "motion_family": "DOLLY", "motion_direction": "PUSH_IN"}
        unit, plan = build([{"cast": [A]}], camera_plan=bare)
        camera = camera_block(render_h3_prompt(unit, plan)[0])
        self.assertEqual(camera, "shot scale=WIDE; one short dolly move; direction=PUSH_IN.")

    def test_cjk_only_framing_is_not_leaked_and_is_reported(self):
        unit, plan = build([{"cast": [A]}], camera_plan={**LOCKED, "start_framing": "中景", "end_framing": "中景"})
        text, receipt = render_h3_prompt(unit, plan)
        self.assertNotIn("hold the framing", text)
        self.assertEqual(receipt["shot_scope"]["camera_shots"][0]["untranslated_fields"], [
            "E64-VU-T01:H3_CAMERA_FIELD_ENGLISH_MISSING:UNIT:start_framing",
            "E64-VU-T01:H3_CAMERA_FIELD_ENGLISH_MISSING:UNIT:end_framing",
        ])
        unit["h3_provider_english_contract"]["camera_plan"] = {
            "start_framing": "medium shot", "end_framing": "medium shot"}
        text, receipt = render_h3_prompt(unit, plan)
        self.assertIn("hold the framing: medium shot", text)
        self.assertEqual(receipt["shot_scope"]["camera_shots"][0]["untranslated_fields"], [])
        unit, plan = build([{"cast": [A]}, {"cast": [B]}], per_shot=[
            {**LOCKED, "start_framing": "中景", "start_framing_en": "medium two-shot", "end_framing": "中景",
             "end_framing_en": "medium two-shot"}, TRACK])
        self.assertIn("SHOT 1 [0s-3s] (opening shot): shot scale=MEDIUM; camera height=EYE_LEVEL; camera side=AXIS_A; "
                      "locked camera with no camera movement; hold the framing: medium two-shot",
                      render_h3_prompt(unit, plan)[0])

    def test_multi_shot_unit_states_cut_or_continuous_move(self):
        rows = [
            {"cast": [A], "shot_id": "T-S01"},
            {"cast": [B], "shot_id": "T-S02"},
            {"cast": [B], "shot_id": "T-S02"},
        ]
        unit, plan = build(rows, per_shot=[LOCKED, TRACK, TRACK])
        text, _ = render_h3_prompt(unit, plan)
        camera = camera_block(text)
        lines = camera.splitlines()
        self.assertEqual(lines[0], "per-shot camera; each line applies only to its own time window")
        self.assertTrue(lines[1].startswith("SHOT 1 [0s-3s] (opening shot): shot scale=MEDIUM"))
        self.assertIn("locked camera with no camera movement", lines[1])
        self.assertTrue(lines[2].startswith("SHOT 2 [3s-6s] (hard cut to a new framing): "))
        self.assertIn("the camera follows Beta", lines[2])
        self.assertTrue(lines[3].startswith("SHOT 3 [6s-9s] (no cut; one continuous camera move into this framing): "))
        self.assertEqual(locked_camera_move_conflicts(text), [])
        unit, plan = build(rows[:2], per_shot=[LOCKED, TRACK],
                           transitions=[{"transition_mode": "CAMERA_REFRAME"}])
        camera = camera_block(render_h3_prompt(unit, plan)[0])
        self.assertIn("SHOT 2 [3s-6s] (no cut; one continuous camera move into this framing)", camera)

    def test_locked_checker_flags_legacy_move_instruction(self):
        unit, plan = build([{"cast": [A]}], episode="E63")
        legacy_text, _ = render_h3_prompt(unit, plan)
        self.assertIn("locked camera; direction=NONE; execute the declared move once", legacy_text)
        self.assertTrue(locked_camera_move_conflicts(legacy_text))


class IncidentReproductionTest(unittest.TestCase):
    """Old local overlay appended one generic clause to every beat line."""

    def _leaky(self, text: str) -> str:
        out = []
        for line in text.splitlines():
            out.append(line + LEAKY_GLOBAL_CLAUSE if renderer._BEAT_LINE.match(line) else line)
        return "\n".join(out) + "\n"

    def test_checker_flags_leak_and_fixed_renderer_passes(self):
        unit, plan = build([
            {"cast": [A, B], "extent": {A: "HANDS_ONLY"}, "speaker": B},
            {"cast": [B], "speaker": B},
        ])
        fixed, _ = render_h3_prompt(unit, plan)
        self.assertEqual(partial_clause_leaks(fixed, plan, unit), [])
        leaky = self._leaky(fixed)
        findings = partial_clause_leaks(leaky, plan, unit)
        self.assertIn("PARTIAL_CLAUSE_GENERIC_UNNAMED:BEAT.1:" + LEAKY_GLOBAL_CLAUSE.strip().split("; ")[1][:80],
                      findings)
        self.assertTrue(any(f.startswith("PARTIAL_CLAUSE_GENERIC_UNNAMED:BEAT.2:") for f in findings))

    def test_checker_flags_named_clause_on_wrong_entity_or_beat_or_speaker(self):
        unit, plan = build([
            {"cast": [A, B], "extent": {A: "HANDS_ONLY"}, "speaker": B},
            {"cast": [A, B]},
        ])
        fixed, _ = render_h3_prompt(unit, plan)
        lines = fixed.splitlines()
        second = [i for i, line in enumerate(lines) if renderer._BEAT_LINE.match(line)][1]
        lines[second] += " " + renderer.partial_clause("Alpha", "hands") + "."
        findings = partial_clause_leaks("\n".join(lines), plan, unit)
        self.assertIn("PARTIAL_CLAUSE_LEAK:BEAT.2:Alpha", findings)
        lines = fixed.splitlines()
        first = [i for i, line in enumerate(lines) if renderer._BEAT_LINE.match(line)][0]
        lines[first] += " " + renderer.partial_clause("Beta", "hands") + "."
        findings = partial_clause_leaks("\n".join(lines), plan, unit)
        self.assertIn("PARTIAL_CLAUSE_LEAK:BEAT.1:Beta", findings)
        self.assertIn("PARTIAL_CLAUSE_VISIBLE_SPEAKER_CONFLICT:BEAT.1:Beta", findings)
        global_line = fixed.replace("negative_constraints: ", "negative_constraints: do not reveal Alpha's face; ")
        self.assertTrue(any(f.startswith("PARTIAL_CLAUSE_OUTSIDE_BEAT_SCOPE:")
                            for f in partial_clause_leaks(global_line, plan, unit)))

    def test_checker_reports_missing_declared_partial_clause(self):
        unit, plan = build([{"cast": [A], "extent": {A: "HANDS_ONLY"}}], episode="E63")
        legacy, _ = render_h3_prompt(unit, plan)
        self.assertEqual(partial_clause_leaks(legacy, plan, unit), ["PARTIAL_CLAUSE_MISSING:BEAT.1:Alpha"])


class GateOffByteIdentityTest(unittest.TestCase):
    CASES = [
        [{"cast": [A], "speaker": A}],
        [{"cast": [A, B], "extent": {A: "HANDS_ONLY"}, "speaker": B}],
        [{"cast": [A], "speaker": B, "offscreen": True}],
        [{"cast": [A, CAT], "extent": {CAT: "PAWS_ONLY"}}, {"cast": [A], "speaker": A}],
    ]

    def _legacy_render(self, unit: dict, plan: dict) -> str:
        """Reference implementation: the pre-upgrade renderer, loaded from git HEAD."""
        import importlib.util
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        root = Path(renderer.__file__).resolve().parents[1]
        source = subprocess.run(
            ["git", "-C", str(root), "show", "HEAD:tools/h3_provider_prompt_renderer.py"],
            check=True, capture_output=True, text=True,
        ).stdout
        if "shot_scope_active" in source:
            self.skipTest("HEAD already contains the shot-scope renderer; byte identity is covered elsewhere")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy_h3_renderer.py"
            path.write_text(source, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("legacy_h3_renderer", path)
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(root))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.remove(str(root))
            return module.render_h3_prompt(unit, plan)

    def test_gate_off_is_byte_identical_to_legacy(self):
        for rows in self.CASES:
            for camera in (LOCKED, TRACK):
                unit, plan = build(rows, episode="E63", camera_plan=deepcopy(camera))
                self.assertFalse(shot_scope_active(unit, plan))
                text, receipt = render_h3_prompt(deepcopy(unit), deepcopy(plan))
                legacy_text, legacy_receipt = self._legacy_render(deepcopy(unit), deepcopy(plan))
                self.assertEqual(text, legacy_text)
                self.assertEqual(receipt, legacy_receipt)
                self.assertNotIn("shot_scope", receipt)


if __name__ == "__main__":
    unittest.main()
