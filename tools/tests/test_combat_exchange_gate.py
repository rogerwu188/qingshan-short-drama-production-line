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

from tools.combat_exchange_gate import evaluate, load_policy, policy_active  # noqa: E402

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


def _plan(beats, *, episode="E15", scene="E15-S04"):
    return {"unit_id": "E15-VU-010", "episode": episode, "scene_id": scene,
            "unit_class": "COMBAT_EXCHANGE", "beats": beats}


class PolicyScopeTest(unittest.TestCase):
    def test_inactive_before_the_floor(self):
        self.assertFalse(policy_active("E14", None, POLICY))

    def test_active_from_the_floor_or_by_declaration(self):
        self.assertTrue(policy_active("E15", None, POLICY))
        self.assertTrue(policy_active("E14", "COMBAT_EXCHANGE_V1", POLICY))

    def test_inactive_plan_is_not_applicable(self):
        report = evaluate(_plan([_beat("秦铭", "巡山者")], episode="E14"))
        self.assertEqual(report["status"], "NOT_APPLICABLE")


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


if __name__ == "__main__":
    unittest.main()
