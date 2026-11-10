"""COMBAT_MOTION_V1 — the action ladder replaces the state template, and holds are blocked."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import combat_unit_compiler as compiler  # noqa: E402

POLICY = {"rules": {"max_contact_seconds": 0.4, "min_shot_seconds": 0.5, "max_shot_seconds": 1.5}}


def _beat(action: str, **extra):
    beat = {"start_seconds": 2.0, "end_seconds": 4.5, "primary_action": action}
    beat.update(extra)
    return beat


def test_ladder_splits_moves_and_marks_one_contact():
    out = compiler.compile_combat_unit(_beat(
        "傅恩涛的刀刃劈下来；秦铭的矛杆横着迎上去，刀刃砍在矛杆上；秦铭滚动矛杆把大刀往画右推开一臂；"
        "傅恩涛双臂被带向画右，上身转开"), policy=POLICY)
    shots = out["shots"]
    assert len(shots) == 4
    assert [s["contact"] for s in shots].count(True) == 1
    assert compiler.validate_ladder(out, policy=POLICY) == []


def test_rendered_text_has_shot_lines_and_no_state_template():
    out = compiler.compile_combat_unit(_beat(
        "刀刃劈下来；矛杆迎上去，刀刃砍在矛杆上；秦铭往画右推开一臂；傅恩涛上身转开"), policy=POLICY)
    text = out["text"]
    assert text.count("[Shot ") == 4
    for banned in ("Start from", "Force origin", "End at", "The only contact", "primary feedback"):
        assert banned not in text


def test_contact_shot_is_capped():
    out = compiler.compile_combat_unit(_beat("刀刃劈下来；矛杆迎上去，刀刃砍在矛杆上；往画右推开一臂"), policy=POLICY)
    contact = [s for s in out["shots"] if s["contact"]]
    assert contact and contact[0]["seconds"] <= 0.4 + 1e-6


def test_settled_result_is_blocked():
    out = compiler.compile_combat_unit(_beat(
        "刀刃劈下来；矛杆迎上去，刀刃砍在矛杆上；两人顶住不动，往画右推开一臂"), policy=POLICY)
    failures = compiler.validate_ladder(out, policy=POLICY)
    assert any(f.startswith("CM5_SETTLED_RESULT") for f in failures)


def test_no_distance_is_blocked():
    out = compiler.compile_combat_unit(_beat("刀刃劈下来；矛杆迎上去，刀刃砍在矛杆上；傅恩涛上身转开"), policy=POLICY)
    failures = compiler.validate_ladder(out, policy=POLICY)
    assert any(f.startswith("CM2_") for f in failures)


def test_authored_ladder_is_used_verbatim():
    out = compiler.compile_combat_unit(_beat("ignored", combat_shots=[
        {"move": "刀刃劈下来", "seconds": 0.6, "shot_scale": "MEDIUM_CLOSE_UP", "camera_side": "AXIS_A"},
        {"move": "矛杆迎上，刀刃砍在矛杆上", "seconds": 0.5, "shot_scale": "CLOSE_UP", "camera_side": "AXIS_B",
         "contact": True},
        {"move": "往画右推开一臂，傅恩涛上身转开", "seconds": 1.4, "shot_scale": "MEDIUM", "camera_side": "AXIS_B"},
    ]), policy=POLICY)
    assert [s["move"] for s in out["shots"]][0] == "刀刃劈下来"
    assert out["shots"][1]["scale"] == "CLOSE_UP"


def test_policy_inactive_keeps_callers_on_legacy_path():
    assert compiler.policy_active({}, episode="E15", policy={"enabled_from_episode": "E16"}) is False
    assert compiler.policy_active({"combat_motion_policy": "COMBAT_MOTION_V1"}, episode="E15",
                                  policy={"enabled_from_episode": "E16"}) is True


def test_longest_run_helper_shared_with_dialogue_gate():
    from tools import dialogue_register_gate as gate
    assert gate.longest_common_run("你是谁，为何针对我等？", "你是谁，为何针对我等？来者何人") == "你是谁为何针对我等"


def test_ladder_never_overruns_the_beat_window():
    # E15 VU-020 beat 3: five moves in a 2.0 s window used to run to 6.9 s inside a 4.5–6.5 s beat
    out = compiler.compile_combat_unit({"start_seconds": 4.5, "end_seconds": 6.5, "primary_action":
        "傅恩涛把刀收回来；矛杆拨在刀面上，刀往画右偏开半尺；秦铭前脚抢进半步；矛杆拦在刀面外侧；砍柴刀提上来"},
        policy=POLICY)
    shots = out["shots"]
    assert shots[0]["start"] == 4.5
    assert abs(shots[-1]["end"] - 6.5) < 1e-6
    assert abs(sum(s["seconds"] for s in shots) - 2.0) < 1e-3
