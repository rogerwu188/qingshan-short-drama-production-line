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


def test_postable_manifest_without_combat_classification_fails_closed(tmp_path):
    task = {"task_key": "VU-010", "scene_id": "S06", "prompt_file": str(tmp_path / "x.txt")}
    staged = {"episode": "E15", "provider_post_allowed": False, "tasks": [dict(task)]}
    assert gate.evaluate_manifest(staged, root=tmp_path)["status"] == "PASS"
    postable = {"episode": "E15", "provider_post_allowed": True, "tasks": [dict(task)]}
    codes = [f["code"] for f in gate.evaluate_manifest(postable, root=tmp_path)["failures"]]
    assert codes == ["COMBAT_CLASSIFICATION_MISSING"]
