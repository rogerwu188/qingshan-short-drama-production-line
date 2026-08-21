#!/usr/bin/env python3
"""Tests for the fight cut_plan gate (B7-ADV-01).

The cases that matter are the ones where a plan looks compliant and is not:
a plan that sums wrong, a plan whose reasons are one sentence copy-pasted,
a plan that hits ASL by declaring three bursts in a row.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fight_cut_plan_gate import (  # noqa: E402
    NET_BASIS_DECLARED,
    NET_BASIS_DERIVED_FULL_SCENE,
    NET_BASIS_UNDETERMINED,
    diagnose_unplanned,
    resolve_net_fight_seconds,
    run,
)

CONTINUITY = {
    "scene_id": "30-1",
    "light_key": "torch_low_left",
    "axis_line": "A_to_B_180",
    "eyeline": "screen_left",
}


def sub(duration, phase, note, reason="ACTION_BEAT", **extra):
    return {
        "duration": duration,
        "phase": phase,
        "cut_reason": reason,
        "action": note,
        "cut_reason_note": note,
        **extra,
    }


def unit(unit_id, generated, subs):
    return {"unit_id": unit_id, "generated_duration": generated, "cut_plan": subs, **CONTINUITY}


def good_plan():
    """Four 5s units -> 16 shots, ASL 1.25s, 25% under 1s, 4 rounds."""
    units = []
    for i in range(4):
        units.append(
            unit(
                f"30-1-U{i + 1}",
                5.0,
                [
                    sub(1.5, "windup", f"U{i+1} 沉肩收势，霜纹在刃口聚起"),
                    sub(0.8, "burst", f"U{i+1} 掌风撞上灯杆，火星横扫"),
                    sub(1.2, "result", f"U{i+1} 灯杆震颤，来者重心外偏"),
                    sub(1.5, "burst", f"U{i+1} 借偏势转腕，把短刃压离中线"),
                ],
            )
        )
    return {"episode": "E57", "fight_scenes": [{"scene_id": "30-1", "units": units}]}


class TestFightCutPlanGate(unittest.TestCase):
    def test_well_formed_plan_passes(self):
        result = run(good_plan())
        self.assertEqual(result["gate_status"], "PASS", result["findings"])
        metrics = result["scenes"][0]["metrics"]
        self.assertEqual(metrics["shot_count"], 16)
        self.assertLessEqual(metrics["asl"], 2.2)
        self.assertGreaterEqual(metrics["sub_second_share"], 0.15)
        self.assertGreaterEqual(metrics["phase_rounds"], 3)

    def test_missing_cut_plan_blocks(self):
        plan = good_plan()
        plan["fight_scenes"][0]["units"][0].pop("cut_plan")
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F1_PLAN_PRESENT" for f in result["findings"]))

    def test_one_cut_per_unit_cannot_pass(self):
        """The status quo: 13 units, one cut each. Must fail on both counts."""
        units = [
            unit(f"30-1-U{i+1}", 5.0, [sub(5.0, "burst", f"U{i+1} 一镜到底的交手 {i}")])
            for i in range(13)
        ]
        result = run({"episode": "E57", "fight_scenes": [{"scene_id": "30-1", "units": units}]})
        self.assertEqual(result["gate_status"], "BLOCK")
        gates = {f["gate"] for f in result["findings"]}
        self.assertIn("F5_BASELINE_V21", gates)
        metrics = result["scenes"][0]["metrics"]
        self.assertEqual(metrics["sub_second_share"], 0.0)

    def test_single_12_second_generation_used_as_one_edit_shot_blocks(self):
        plan = {
            "episode": "E41",
            "fight_scenes": [{
                "scene_id": "14-7",
                "units": [unit("14-7-U1", 12.0, [sub(12.0, "burst", "整段生成片未拆分")])],
            }],
        }
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F1_PLAN_PRESENT" for f in result["findings"]))

    def test_durations_must_sum_to_the_generated_unit(self):
        plan = good_plan()
        plan["fight_scenes"][0]["units"][0]["cut_plan"][0]["duration"] = 3.9
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F2_SUM_MATCH" for f in result["findings"]))

    def test_copy_pasted_justification_is_rejected(self):
        """A form filled in is not a cutting decision (573(4) lesson)."""
        plan = good_plan()
        scene = plan["fight_scenes"][0]
        for u in scene["units"]:
            for s in u["cut_plan"]:
                s["action"] = s["cut_reason_note"] = "打斗动作节点"
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F4_UNIQUE_ACTION" for f in result["findings"]))

    def test_metric_language_is_rejected(self):
        plan = good_plan()
        plan["fight_scenes"][0]["units"][0]["cut_plan"][1]["cut_reason_note"] = "切一刀把 ASL 压下来"
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F3_REASON" for f in result["findings"]))

    def test_all_burst_no_windup_fails_breathing_structure(self):
        units = []
        for i in range(4):
            units.append(
                unit(
                    f"U{i+1}",
                    5.0,
                    [
                        sub(2.2, "burst", f"U{i+1} 连击一 {i}"),
                        sub(0.9, "burst", f"U{i+1} 连击二 {i}"),
                        sub(1.9, "burst", f"U{i+1} 连击三 {i}"),
                    ],
                )
            )
        result = run({"episode": "E57", "fight_scenes": [{"scene_id": "30-1", "units": units}]})
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F6_PHASE" for f in result["findings"]))

    def test_declared_retime_blocks(self):
        plan = good_plan()
        plan["fight_scenes"][0]["units"][0]["speed_ramp"] = 0.5
        result = run(plan)
        self.assertEqual(result["gate_status"], "BLOCK")
        self.assertTrue(any(f["gate"] == "F7_NO_RETIME" for f in result["findings"]))

    def test_sub_cut_floor(self):
        plan = good_plan()
        u = plan["fight_scenes"][0]["units"][0]
        u["cut_plan"] = [sub(0.1, "windup", "闪一下"), sub(4.9, "burst", "接住")]
        result = run(plan)
        self.assertTrue(any("floor" in f["detail"] for f in result["findings"]))

    def test_diagnosis_reproduces_e57_numbers(self):
        """B7-ADV-01's published figures must come out of the code, not prose.

        This test corrected the prose, not the other way round: CL2X-1024
        published "needs >=28 cuts" for E57's 62s, but 62/2.2 = 28.18, so the
        floor is 29. Same off-by-one in E58 (16, published 15) and E51 (10,
        published 9). Writing the arithmetic down as code found it; the
        conclusion (the shortfall is structural) is unchanged.
        """
        scene = {
            "scene_id": "30-1+30-2",
            "net_fight_seconds": 62.0,
            "units": [{"generated_duration": 4.8} for _ in range(13)],
        }
        d = diagnose_unplanned(scene)
        self.assertEqual(d["units"], 13)
        self.assertAlmostEqual(d["one_cut_per_unit_asl"], 4.77, places=2)
        self.assertEqual(d["cuts_needed_for_baseline"], 29)
        self.assertEqual(d["shortfall"], 16)
        self.assertFalse(d["sub_second_share_reachable"])

    def test_diagnosis_e58_and_e51(self):
        e58 = diagnose_unplanned(
            {"scene_id": "31-3", "net_fight_seconds": 34.0, "units": [{}] * 10}
        )
        self.assertEqual(e58["cuts_needed_for_baseline"], 16)
        self.assertEqual(e58["shortfall"], 6)
        e51 = diagnose_unplanned(
            {"scene_id": "24-3", "net_fight_seconds": 20.0, "units": [{}] * 8}
        )
        self.assertEqual(e51["cuts_needed_for_baseline"], 10)
        self.assertEqual(e51["shortfall"], 2)

    def test_empty_input_is_invalid_not_pass(self):
        result = run({"episode": "E57", "fight_scenes": []})
        self.assertEqual(result["gate_status"], "INVALID")

    def test_explicit_no_fight_passes_only_with_canonical_no_fight_proof(self):
        plan = {"episode": "E50", "applicable": False, "fight_scenes": []}
        result = run(plan, canonical_text="△【近景·对白】人物在灯下交谈。")
        self.assertEqual(result["gate_status"], "PASS")
        self.assertEqual(result["applicability"], "NOT_APPLICABLE")
        mismatch = run(plan, canonical_text="△【打斗·起·4s】双方立即交手。")
        self.assertEqual(mismatch["gate_status"], "INVALID")


class TestNetFightSecondsSingleImplementation(unittest.TestCase):
    """CL2X-1039. Every case below passes silently on the pre-1039 version.

    The old `net_fight_seconds or sum(units)` never lied about a verdict — it
    returned a plausible number under an unchanged field name, which is the
    failure mode that leaves no trace to notice.
    """

    E62_35_4 = {
        "scene_id": "35-4",
        "net_fight_seconds": 35.0,           # script layer: 净打斗 35s
        "units": [{"generated_duration": 5.0} for _ in range(9)],  # scene sums to 45s
    }

    def test_declared_and_derived_are_both_reported(self):
        d = diagnose_unplanned(self.E62_35_4)
        self.assertEqual(d["net_fight_basis"], NET_BASIS_DECLARED)
        self.assertEqual(d["net_fight_seconds"], 35.0)
        # The ruler that was NOT used still has to be visible.
        self.assertEqual(d["net_fight_derived_full_scene"], 45.0)

    def test_absent_key_switches_ruler_and_must_say_so(self):
        """The 5-cut swing that started this: same scene, key removed."""
        without = {k: v for k, v in self.E62_35_4.items() if k != "net_fight_seconds"}
        d = diagnose_unplanned(without)
        self.assertEqual(d["net_fight_basis"], NET_BASIS_DERIVED_FULL_SCENE)
        self.assertEqual(d["net_fight_seconds"], 45.0)
        self.assertIsNone(d["net_fight_declared"])
        # 21 cuts demanded instead of 16, on the key alone.
        self.assertEqual(d["cuts_needed_for_baseline"], 21)
        self.assertEqual(diagnose_unplanned(self.E62_35_4)["cuts_needed_for_baseline"], 16)

    def test_undetermined_is_not_a_confident_zero(self):
        """Old behaviour: net=0.0, shortfall=0 — reads as 'nothing to cut'."""
        d = diagnose_unplanned({"scene_id": "X", "units": [{}, {}]})
        self.assertEqual(d["net_fight_basis"], NET_BASIS_UNDETERMINED)
        self.assertIsNone(d["net_fight_seconds"])
        self.assertNotIn("shortfall", d)

    def test_resolver_rejects_bool_and_nonpositive(self):
        r = resolve_net_fight_seconds({"net_fight_seconds": True, "units": [{"generated_duration": 4.0}]})
        self.assertEqual(r["basis"], NET_BASIS_DERIVED_FULL_SCENE)
        r0 = resolve_net_fight_seconds({"net_fight_seconds": 0, "units": []})
        self.assertEqual(r0["basis"], NET_BASIS_UNDETERMINED)

    def test_divergence_is_advised_not_blocked(self):
        """A conforming plan whose scene carries non-fight seconds still ships."""
        plan = good_plan()
        scene = plan["fight_scenes"][0]
        scene["net_fight_seconds"] = 15.0      # scene itself sums to 20.0
        result = run(plan)
        self.assertEqual(result["gate_status"], "ADVISE")
        f8 = [f for f in result["findings"] if f["gate"] == "F8_NET_BASIS"]
        self.assertEqual(len(f8), 1)
        self.assertEqual(f8[0]["severity"], "ADVISE")
        self.assertEqual(f8[0]["declared"], 15.0)
        self.assertEqual(f8[0]["derived_full_scene"], 20.0)

    def test_no_divergence_finding_when_scene_is_all_fight(self):
        plan = good_plan()
        plan["fight_scenes"][0]["net_fight_seconds"] = 20.0
        result = run(plan)
        self.assertEqual(result["gate_status"], "PASS")

    def test_asl_says_which_seconds_it_divided_by(self):
        result = run(good_plan())
        m = result["scenes"][0]["metrics"]
        self.assertEqual(m["asl_basis"], "PLANNED_SECONDS_WHOLE_SCENE")
        self.assertEqual(m["planned_seconds"], 20.0)
        self.assertNotIn("net_seconds", m)  # the colliding name is gone


if __name__ == "__main__":
    unittest.main()
