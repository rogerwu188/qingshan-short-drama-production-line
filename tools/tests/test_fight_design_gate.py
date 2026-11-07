"""FIGHT_DESIGN_V1 (Roger 2026-11-07): the writing-time fight gate learns E14/E15's mistakes."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "tools", ROOT / "lines" / "nalu" / "runtime" / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import fight_design_gate as gate  # noqa: E402


def shot(sid, scene, secs, *, combat=False, family="TRACK", line="", axis="", action="", props=()):
    act = {"primary_action": action}
    if combat:
        act.update({"action_kind": "COMBAT", "combat_choreography": {"attack_defense_chain": action}})
    return {"shot_id": sid, "scene_id": scene, "target_seconds": secs,
            "prompt_spec": {"dialogue": line, "action": act, "props": [{"prop": p} for p in props],
                            "camera_plan": {"motion_family": family, "axis_relation": axis}}}


CARDS = {"reference_cards": [{"name": "弯背长柄大刀"}, {"name": "铁矛"}, {"name": "砍柴刀"}]}

# E15 S12 as first written: line / hit / line / hit, all on a locked camera, both faces to the lens
OLD_S12 = [
    shot("S12-01", "S12", 1.5, family="LOCKED", line="傅恩涛：压下去。", axis="两人都侧身相对、脸都转向镜头"),
    shot("S12-02", "S12", 2.5, combat=True, family="LOCKED", action="长刀压在铁矛上"),
    shot("S12-03", "S12", 2.0, family="LOCKED", line="秦铭：再进半步。"),
    shot("S12-04", "S12", 2.0, combat=True, family="LOCKED", action="砍柴刀砍在护臂上"),
    shot("S12-05", "S12", 2.0, family="LOCKED", line="傅恩涛：这力不对。"),
    shot("S12-08", "S12", 3.5, family="LOCKED", line="秦铭：我的力气比他大，速度比他慢。"),
]
# E15 S12 as rewritten: one silent 10.5 s exchange on moving cameras, lines after it
NEW_S12 = [
    shot("S12-01", "S12", 2.0, combat=True, family="TRACK", action="傅恩涛举弯背长柄大刀压向铁矛"),
    shot("S12-02", "S12", 2.5, combat=True, family="DOLLY", action="铁矛贴刀面横顶"),
    shot("S12-03", "S12", 2.0, combat=True, family="TRACK", action="秦铭进半步"),
    shot("S12-04", "S12", 2.5, combat=True, family="DOLLY", action="砍柴刀砍在护臂上"),
    shot("S12-05", "S12", 1.5, combat=True, family="TRACK", action="傅恩涛退三步"),
    shot("S12-06", "S12", 2.0, family="LOCKED", line="傅恩涛：这力不对。"),
]


def _codes(report):
    return {row["code"] for row in report["failures"]}


def test_first_draft_shape_blocks_on_every_rule():
    contract = {"episode": "E16", "props": {"reference_cards": [{"name": "砍柴刀"}]}, "shots": OLD_S12}
    report = gate.evaluate(contract)
    assert report["status"] == "BLOCK"
    assert _codes(report) == {"COMBAT_SHOT_CAMERA_LOCKED", "FIGHT_SCENE_NARRATED", "COMBAT_RUN_SHORTER_THAN_UNIT",
                              "FIGHTERS_FACE_CAMERA", "COMBAT_WEAPON_WITHOUT_CARD"}


def test_rewritten_exchange_passes():
    report = gate.evaluate({"episode": "E16", "props": CARDS, "shots": NEW_S12})
    assert report["status"] == "PASS", report["failures"]


def test_tactical_line_inside_a_combat_shot_blocks():
    shots = [dict(NEW_S12[0], prompt_spec={**NEW_S12[0]["prompt_spec"], "dialogue": "傅恩涛：压下去。"})] + NEW_S12[1:]
    assert "COMBAT_SHOT_WITH_DIALOGUE" in _codes(gate.evaluate({"episode": "E16", "props": CARDS, "shots": shots}))


def test_weapon_nouns_not_verbs():
    assert gate._weapons(shot("x", "s", 1, combat=True, action="傅恩涛挥刀，把矛震开，长刀压在铁矛上")) == {"长刀", "铁矛"}


def test_not_retroactive_before_e16_unless_declared():
    contract = {"episode": "E15", "props": {}, "shots": OLD_S12}
    assert gate.evaluate(contract)["status"] == "NOT_ACTIVE"
    contract["fight_design_policy"] = gate.POLICY_ID
    assert gate.evaluate(contract)["status"] == "BLOCK"


def test_static_design_gate_blocks_on_fight_design():
    import static_design_gate as sdg
    ev = sdg.evaluate({"episode": "E16", "props": {}, "shots": OLD_S12}, dict(sdg.POLICY), current_policy=True)
    assert any(f.startswith("FD_COMBAT_SHOT_CAMERA_LOCKED") for f in ev["failures"])
    assert ev["fight_design"]["status"] == "BLOCK"


def test_review_question_carries_the_four_combat_conditions():
    import vlm_review_protocol as vrp
    text = repr(vars(vrp))
    assert "action_kind COMBAT happens only if" in text
