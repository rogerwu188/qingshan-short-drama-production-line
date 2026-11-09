"""COMBAT_UNIT_DIRECTION_V1 (Roger 2026-11-06, E15 打斗像静态 PPT)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import combat_unit_direction_gate as gate  # noqa: E402
import h3_provider_prompt_renderer as renderer  # noqa: E402

E15_STYLE_PROMPT = (
    "[0s-1.5s] Start from A. Fu Entao presses the blade down. Microexpression: gaze changes, then holds 'x'.\n"
    "[1.5s-4s] Start from B. Force origin: Fu Entao presses down. Qin Ming blocks Interaction mode: physical "
    "contact; the interaction point is reached at 2.3s. Microexpression: his gaze changes once, then holds 'y'.\n"
)
GOOD_PROMPT = (
    "[0s-1s] Start from A. Fu Entao steps in. Body synchronization: weight first.\n"
    "[1s-4s] Start from B. Force origin: Fu Entao drives down. Qin Ming blocks Interaction mode: physical "
    "contact; the interaction point is reached at 1.6s; primary feedback: "
    + renderer.COMBAT_CONDENSED_FEEDBACK + ".\n"
)


def _task(tmp: Path, key: str, *, scene="S12", combat=True, family="LOCKED", lines=None, prompt=E15_STYLE_PROMPT,
          seconds=4.0, axis=""):
    path = tmp / f"{key}.txt"
    path.write_text(prompt, encoding="utf-8")
    return {"task_key": key, "unit_id": key, "scene_id": scene, "combat_or_chase": combat,
            "camera_plan": {"motion_family": family, "axis_relation": axis},
            "dialogue_lines": list(lines or []), "authorized_content_seconds": seconds, "prompt_file": str(path)}


def test_e15_style_fight_unit_blocks_on_every_rule(tmp_path):
    manifest = {"episode": "E15", "tasks": [
        _task(tmp_path, "VU-020", lines=["压下去。"], axis="两人都侧身相对、脸都转向镜头"),
        _task(tmp_path, "VU-022", combat=False, prompt="[0s-4s] Start from C.", seconds=5.0, lines=["这力不对。"]),
    ]}
    report = gate.evaluate_manifest(manifest, root=tmp_path)
    codes = {f["code"] for f in report["failures"]}
    assert report["status"] == "BLOCK"
    assert codes == {"COMBAT_UNIT_CAMERA_LOCKED", "COMBAT_UNIT_CARRIES_DIALOGUE", "COMBAT_UNIT_PROMPT_HOLD_LANGUAGE",
                     "FIGHT_TWO_SHOT_FACING_CAMERA", "FIGHT_SCENE_NARRATED"}


def test_silent_moving_combat_units_with_real_time_wording_pass(tmp_path):
    manifest = {"episode": "E16", "tasks": [
        _task(tmp_path, "VU-001", family="TRACK", prompt=GOOD_PROMPT, seconds=5.0, axis="秦铭在画左，傅恩涛在画右，侧面对峙"),
        _task(tmp_path, "VU-002", combat=False, prompt="[0s-4s] Start from C.", seconds=4.0, lines=["贴上去打。"]),
    ]}
    report = gate.evaluate_manifest(manifest, root=tmp_path)
    assert report["status"] == "PASS", report["failures"]


def test_hold_wording_on_a_non_combat_beat_is_not_blamed(tmp_path):
    prompt = "[0s-1s] Start from A. Gaze changes, then holds 'x'.\n" + GOOD_PROMPT.split("\n", 1)[1]
    assert gate.combat_beat_hold_phrases(prompt) == []


def test_delivered_episodes_are_not_retroactive(tmp_path):
    manifest = {"episode": "E14", "tasks": [_task(tmp_path, "VU-020", lines=["压下去。"])]}
    assert gate.evaluate_manifest(manifest, root=tmp_path)["status"] == "NOT_ACTIVE"
    manifest["combat_unit_direction_policy"] = gate.POLICY_ID
    assert gate.evaluate_manifest(manifest, root=tmp_path)["status"] == "BLOCK"


def test_renderer_condensed_feedback_never_settles_a_combat_beat():
    action = "Qin Ming lays the iron spear flat against the blade face and holds it across firmly"
    exit_state = "The blade is held out beside Qin Ming's body"
    translated = {"primary_action": action, "exit_state": exit_state}
    feedback = f"{action}; {exit_state}"
    assert renderer._condense_feedback(feedback, translated, combat=True) == renderer.COMBAT_CONDENSED_FEEDBACK
    assert "settles" in renderer._condense_feedback(feedback, translated)
    assert renderer._combat_beat({"force_origin": "x"}) and not renderer._combat_beat({})


# ---- Roger 2026-11-07 E15 重投复审: CU3 covers the camera and handoff lines, CU6 limits no-contact beats ----
CAMERA_HOLD_PROMPT = (
    GOOD_PROMPT
    + "End by completing this handoff: Qinming's front foot planted. Keep natural micro-motion and the sound tail.\n"
    + "camera: shot scale=MEDIUM; one short lateral track; direction=LEFT_TO_RIGHT; execute the declared move once, "
      "in one direction only, then hold; the camera never reverses, oscillates or drifts back.\n"
)
CLEAN_CAMERA_PROMPT = (
    GOOD_PROMPT
    + "End by completing this handoff: Qinming's front foot planted. Keep the sound tail.\n"
    + "camera: shot scale=MEDIUM; one short lateral track; direction=LEFT_TO_RIGHT; execute the declared move once, "
      "in one direction only; the camera never reverses, oscillates or drifts back.\n"
)
WALK_IN_PROMPT = (
    "[0s-2s] Start from A. Force origin: Fu Entao presses the sabre down. Interaction mode: no contact in this beat; "
    "No contact in this beat: the sabre presses to within an inch.\n"
    "[2s-4.5s] Start from B. Force origin: Fu Entao presses down. Qinming braces Interaction mode: physical contact; "
    "the interaction point is reached at 2.3s; primary feedback: " + renderer.COMBAT_CONDENSED_FEEDBACK + ".\n"
    "[4.5s-6.5s] Start from C. Force origin: Qinming drives his front foot in. Interaction mode: no contact in this "
    "beat; No contact in this beat: he closes the distance.\n"
)


def test_cu3_catches_hold_wording_on_camera_and_handoff_lines(tmp_path):
    manifest = {"episode": "E15", "tasks": [
        _task(tmp_path, "VU-020", family="TRACK", prompt=CAMERA_HOLD_PROMPT, seconds=6.5, axis="侧身相对"),
    ]}
    report = gate.evaluate_manifest(manifest, root=tmp_path)
    hold = [f for f in report["failures"] if f["code"] == "COMBAT_UNIT_PROMPT_HOLD_LANGUAGE"]
    assert hold and set(hold[0]["phrases"]) == {"then hold", "Keep natural micro-motion"}


def test_combat_camera_and_handoff_lines_without_hold_wording_pass(tmp_path):
    manifest = {"episode": "E15", "tasks": [
        _task(tmp_path, "VU-020", family="TRACK", prompt=CLEAN_CAMERA_PROMPT, seconds=6.5, axis="侧身相对"),
    ]}
    assert gate.evaluate_manifest(manifest, root=tmp_path)["status"] == "PASS"


def test_cu6_blocks_a_unit_staged_as_walk_in_beats(tmp_path):
    manifest = {"episode": "E15", "tasks": [
        _task(tmp_path, "VU-020", family="TRACK", prompt=WALK_IN_PROMPT, seconds=6.5, axis="侧身相对"),
    ]}
    report = gate.evaluate_manifest(manifest, root=tmp_path)
    rows = [f for f in report["failures"] if f["code"] == "COMBAT_UNIT_NO_CONTACT_BEATS"]
    assert rows and rows[0]["no_contact_beats"] == 2 and rows[0]["beats"] == 3
    assert gate.no_contact_beat_counts(WALK_IN_PROMPT) == (2, 3)


def test_cu6_allows_one_setup_beat_in_three(tmp_path):
    one_setup = WALK_IN_PROMPT.rsplit("\n", 2)[0] + "\n[4.5s-6.5s] Start from C. Force origin: Qinming drives in. " \
        "Interaction mode: physical contact; the interaction point is reached at 5s.\n"
    assert gate.no_contact_beat_counts(one_setup) == (1, 3)
    manifest = {"episode": "E15", "tasks": [
        _task(tmp_path, "VU-020", family="TRACK", prompt=one_setup, seconds=6.5, axis="侧身相对"),
    ]}
    codes = {f["code"] for f in gate.evaluate_manifest(manifest, root=tmp_path)["failures"]}
    assert "COMBAT_UNIT_NO_CONTACT_BEATS" not in codes


def test_renderer_combat_camera_clause_has_no_hold():
    assert "then hold" in renderer.SINGLE_DIRECTION_CLAUSE
    assert "hold" not in renderer.SINGLE_DIRECTION_CLAUSE_COMBAT
    assert renderer._camera({"motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT", "shot_scale": "MEDIUM",
                             "camera_grammar": "LOCKED_DIALOGUE_CAMERA_V1"}, combat=True).count("hold") == 0


def test_renderer_weapon_lock_joins_the_look_line():
    unit = {
        "character_entities": [
            {"character_id": "CHAR-FUENTAO", "canonical_name": "傅恩涛", "appearance_anchor_en": "very tall broad man",
             "weapon_lock_en": "a long-handled broad sabre with a curved back"},
        ],
        "reference_image_sequence": [{"entity_id": "CHAR-FUENTAO", "provider_entity_label": "Fuentao"}],
    }
    line = renderer.appearance_anchor_line(unit, {})
    assert line == ("Same look in every frame: Fuentao = very tall broad man, weapon: a long-handled broad sabre "
                    "with a curved back.")
    compact = renderer.appearance_anchor_line(unit, {}, compact=True)
    assert "weapon: a long-handled broad sabre with a curved back" in compact
def test_postable_manifest_without_combat_classification_fails_closed(tmp_path):
    task = {"task_key": "VU-010", "scene_id": "S06", "prompt_file": str(tmp_path / "x.txt")}
    staged = {"episode": "E15", "provider_post_allowed": False, "tasks": [dict(task)]}
    assert gate.evaluate_manifest(staged, root=tmp_path)["status"] == "PASS"
    postable = {"episode": "E15", "provider_post_allowed": True, "tasks": [dict(task)]}
    codes = [f["code"] for f in gate.evaluate_manifest(postable, root=tmp_path)["failures"]]
    assert codes == ["COMBAT_CLASSIFICATION_MISSING"]


def test_scene_share_acceptance_binds_to_measured_seconds():
        g = gate
        assert g._scene_share_acceptance("E15", "E15-S06", {"seconds": 10.5, "combat_seconds": 5.0}) is not None
        assert g._scene_share_acceptance("E15", "E15-S06", {"seconds": 11.0, "combat_seconds": 5.0}) is None
        assert g._scene_share_acceptance("E16", "E15-S06", {"seconds": 10.5, "combat_seconds": 5.0}) is None
