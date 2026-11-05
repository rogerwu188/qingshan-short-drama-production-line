"""COMBAT_EXCHANGE_V1: a fight is several exchanges with initiative changing hands.

Roger 2026-11-05: 「打斗至少要有几个回合才有感觉，没有你来我往的打斗场面」. E14's fights were one
swing each because nothing in the engine required the other side to act; these tests lock the
three repairs: both sides act in every beat, initiative alternates, and a scene carries enough
exchanges to read as a fight.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.combat_exchange_gate import (  # noqa: E402
    evaluate, evaluate_fight, load_policy, policy_active,
)

POLICY = load_policy()


def _beat(initiator, responder, *, answer="格开", attack="横斩", feedback="力被卸到雪面",
          entry="两人对峙", exit_="攻方刀被格开、退半步"):
    return {
        "source_action_kind": "COMBAT",
        "action_subject": initiator,
        "action_patient": responder,
        "primary_action": f"{initiator}出手",
        "defender_answer": answer,
        "attack_kind": attack,
        "force_origin": f"{initiator}前脚蹬地",
        "contact_point": "刀身中段",
        "primary_feedback": feedback,
        "entry_state": entry,
        "exit_state": exit_,
        "interaction_mode": "CONTACT",
    }


def _plan(beats, *, episode="E15", scene="E15-S04", declared="COMBAT_EXCHANGE_V1"):
    return {"unit_id": "E15-VU-010", "episode": episode, "scene_id": scene,
            "unit_class": "COMBAT_EXCHANGE", "combat_exchange_policy": declared, "beats": beats}


class PolicyScopeTest(unittest.TestCase):
    def test_inactive_without_a_declaration(self):
        self.assertFalse(policy_active("E14", None, POLICY))

    def test_active_by_declaration_only(self):
        """The policy is shared by every line, so it cannot carry an episode floor: episode numbers
        mean different things per line. A unit opts in by declaring the policy."""
        self.assertTrue(policy_active("E15", "COMBAT_EXCHANGE_V1", POLICY))
        self.assertFalse(policy_active("E15", None, POLICY))

    def test_inactive_plan_is_not_applicable(self):
        report = evaluate(_plan([_beat("秦铭", "巡山者")], declared=None))
        self.assertEqual(report["status"], "NOT_APPLICABLE")

    def test_a_single_authored_blow_is_out_of_scope(self):
        """A beat the writer declares an IMPULSE is one blow with one outcome (ch15's spear
        through the mastiff's skull). It owes no defender answer and is not counted as a round —
        the fight total is what keeps an episode from being all impulses."""
        beat = _beat("秦铭", "金獒", answer="")
        beat["exchange_role"] = "IMPULSE"
        report = evaluate(_plan([beat]))
        self.assertEqual(report["status"], "NOT_APPLICABLE")
        self.assertEqual(report["reason"], "IMPULSE_ONLY_UNIT")
        self.assertEqual(report["impulses"], 1)


class ExchangeShapeTest(unittest.TestCase):
    def test_a_real_exchange_passes(self):
        report = evaluate(_plan([_beat("秦铭", "巡山者"), _beat("巡山者", "秦铭", attack="直刺")]))
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["exchanges"], 2)
        self.assertTrue(report["initiative_alternates"])

    def test_a_beat_with_no_defender_answer_fails(self):
        beat = _beat("秦铭", "巡山者", answer="", attack="横斩A")
        beat["primary_action"] = "秦铭一刀劈下"
        beat["contact_point"] = "刀身中段"
        report = evaluate(_plan([beat, _beat("巡山者", "秦铭", attack="直刺")]))
        self.assertTrue(any("DEFENDER_ANSWER_MISSING" in f for f in report["failures"]), report["failures"])
        self.assertTrue(any("DEFENDER_ANSWER_MISSING" in f for f in report["failures"]), report["failures"])

    def test_one_side_acting_throughout_fails(self):
        """The E14 shape: the protagonist swings, the other side only reacts externally."""
        beats = [_beat("秦铭", "巡山者", exit_=f"那人退开第{i}步") for i in (1, 2, 3)]
        report = evaluate(_plan(beats))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("INITIATIVE_NEVER_CHANGES" in f for f in report["failures"]), report["failures"])

    def test_repeating_the_same_attack_against_the_same_answer_fails(self):
        beats = [
            _beat("秦铭", "巡山者", attack="横斩", answer="格开", exit_="第一回合结束"),
            _beat("秦铭", "巡山者", attack="横斩", answer="格开", exit_="第二回合结束"),
        ]
        report = evaluate(_plan(beats))
        self.assertTrue(any("REPEATS_PREVIOUS_ATTACK_ANSWER" in f for f in report["failures"]), report["failures"])

    def test_a_beat_without_a_new_position_fails(self):
        beat = _beat("秦铭", "巡山者", exit_="两人对峙")
        report = evaluate(_plan([beat, _beat("巡山者", "秦铭", attack="直刺")]))
        self.assertTrue(any("NEW_POSITION_MISSING" in f for f in report["failures"]), report["failures"])

    def test_a_fight_needs_three_exchanges_in_the_scene(self):
        report = evaluate(_plan([_beat("秦铭", "巡山者"), _beat("巡山者", "秦铭", attack="直刺")]),
                          scene_exchange_counts={"E15-S04": 2})
        self.assertTrue(any("TOO_FEW_IN_FIGHT" in f for f in report["failures"]), report["failures"])
        report = evaluate(_plan([_beat("秦铭", "巡山者"), _beat("巡山者", "秦铭", attack="直刺")]),
                          scene_exchange_counts={"E15-S04": 3})
        self.assertEqual(report["status"], "PASS", report["failures"])


class FightTotalTest(unittest.TestCase):
    """A fight's rounds are counted across its units: Roger asked for several rounds, and per-unit
    judging cannot see a fight made of one-exchange units."""

    def test_two_one_exchange_units_are_only_two_rounds(self):
        first = _plan([_beat("傅恩涛", "秦铭", attack="立劈")], scene="E15-S11")
        second = _plan([_beat("秦铭", "傅恩涛", attack="压刀")], scene="E15-S11")
        second["unit_id"] = "E15-VU-031"
        self.assertEqual(evaluate(first)["status"], "PASS")  # alone, each unit passes
        report = evaluate_fight([first, second])
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("TOO_FEW_IN_FIGHT" in f for f in report["failures"]), report["failures"])
        self.assertEqual(report["exchanges"], 2)

    def test_three_rounds_with_both_sides_pressing_pass(self):
        fight = [_plan([_beat("傅恩涛", "秦铭", attack="立劈")], scene="E15-S11"),
                 _plan([_beat("秦铭", "傅恩涛", attack="压刀")], scene="E15-S12"),
                 _plan([_beat("傅恩涛", "秦铭", attack="横扫", answer="贴地钻过")], scene="E15-S12")]
        for index, plan in enumerate(fight):
            plan["unit_id"] = f"E15-VU-{30 + index:03d}"
        report = evaluate_fight(fight)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["exchanges"], 3)
        self.assertTrue(report["initiative_alternates"])

    def test_a_fight_whose_rounds_never_change_hands_fails_as_a_whole(self):
        fight = [_plan([_beat("傅恩涛", "秦铭", attack="立劈")], scene="E15-S11"),
                 _plan([_beat("傅恩涛", "秦铭", attack="横扫", answer="退开两步")], scene="E15-S12"),
                 _plan([_beat("傅恩涛", "秦铭", attack="横斩", answer="架开")], scene="E15-S13")]
        for index, plan in enumerate(fight):
            plan["unit_id"] = f"E15-VU-{40 + index:03d}"
        report = evaluate_fight(fight)
        self.assertTrue(any("INITIATIVE_NEVER_CHANGES" in f for f in report["failures"]), report["failures"])

    def test_the_same_answer_to_the_same_attack_across_units_fails(self):
        fight = [_plan([_beat("傅恩涛", "秦铭", attack="立劈", answer="侧移闪开")], scene="E15-S11"),
                 _plan([_beat("傅恩涛", "秦铭", attack="立劈", answer="侧移闪开")], scene="E15-S12")]
        for index, plan in enumerate(fight):
            plan["unit_id"] = f"E15-VU-{50 + index:03d}"
        report = evaluate_fight(fight)
        self.assertTrue(any("REPEATS_PREVIOUS_ATTACK_ANSWER" in f for f in report["failures"]),
                        report["failures"])


class FightScopeTest(unittest.TestCase):
    """One bout routinely spans several scenes: ch15's 傅恩涛 fight is engage → break → re-engage.
    Counting rounds per scene would judge the same fight three times and fail it three times."""

    def test_a_bout_spanning_scenes_is_counted_once_by_fight_id(self):
        def round_(initiator, responder, attack, scene, fid="E15-FIGHT-FET"):
            plan = _plan([dict(_beat(initiator, responder, attack=attack), fight_id=fid)], scene=scene)
            return plan
        plans = [round_("傅恩涛", "秦铭", "立劈", "E15-S11"),
                 round_("秦铭", "傅恩涛", "压刀反突进", "E15-S12"),
                 round_("秦铭", "傅恩涛", "贴身砍护臂", "E15-S12")]
        for index, plan in enumerate(plans):
            plan["unit_id"] = f"E15-VU-{60 + index:03d}"
        report = evaluate_fight(plans)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["exchanges"], 3)
        self.assertEqual(report["fight"], "E15-FIGHT-FET")

    def test_a_declared_single_exchange_is_not_a_fight(self):
        """ch15's thrown spear parried by a long sabre: one attack, one answer, no bout after."""
        beat = dict(_beat("秦铭", "冯易安", attack="掷矛", answer="横移抡刀斩矛"),
                    exchange_role="SINGLE_EXCHANGE")
        report = evaluate_fight([_plan([beat], scene="E15-S08")])
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["single_exchanges"], 1)

    def test_a_lone_round_with_no_declaration_still_fails(self):
        report = evaluate_fight([_plan([_beat("傅恩涛", "秦铭")], scene="E15-S11")])
        self.assertTrue(any("TOO_FEW_IN_FIGHT" in f for f in report["failures"]), report["failures"])


if __name__ == "__main__":
    unittest.main()
