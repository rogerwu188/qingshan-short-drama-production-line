"""tools/direction_policy_gate.py tests: pure-function unit tests, offline, synthetic contracts.
No ffmpeg/provider calls, mirroring tools/tests/test_ad_tail_package.py's structure.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import direction_policy_gate as dpg  # noqa: E402


POLICY = {
    "rules": {
        "DP1_shot_scale_distribution": {
            "enabled": True, "cu_mcu_min_episode_ratio": 0.55, "ws_fs_max_episode_ratio": 0.20,
            "ws_max_per_scene": 1,
        },
        "DP2_reaction_shot_floor": {"enabled": True, "under_1s_shot_min_episode_ratio": 0.10},
        "DP3_dialogue_continuity": {
            "enabled": True, "continuous_no_dialogue_seconds_max": 3.0,
            "silence_reason_exceptions_max_per_episode": 2, "silence_reason_seconds_max_each": 6.0,
            "dialogue_time_ratio_min": 0.75,
        },
    }
}


def _shot(shot_id, scene_id, seconds, scale="MEDIUM_CLOSE_UP", dialogue="", silence_reason=None):
    sh = {
        "shot_id": shot_id, "scene_id": scene_id, "target_seconds": seconds,
        "prompt_spec": {"camera_plan": {"shot_scale": scale}, "dialogue": dialogue},
    }
    if silence_reason:
        sh["silence_reason"] = silence_reason
    return sh


class DP1ShotScaleDistributionTests(unittest.TestCase):
    def test_cu_mcu_ratio_below_floor_fails(self) -> None:
        shots = ([_shot(f"S{i}", "SC1", 2.0, "WIDE") for i in range(6)]
                 + [_shot(f"S{i+6}", "SC1", 2.0, "MEDIUM_CLOSE_UP") for i in range(4)])
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP1_CU_MCU_RATIO_") for f in report["failures"]))

    def test_ws_fs_ratio_over_ceiling_fails(self) -> None:
        shots = [_shot(f"S{i}", f"SC{i}", 2.0, "WIDE") for i in range(5)]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP1_WS_FS_RATIO_") for f in report["failures"]))

    def test_balanced_distribution_passes_dp1(self) -> None:
        shots = ([_shot("S1", "SC1", 2.0, "WIDE")]
                 + [_shot(f"S{i+2}", "SC1", 2.0, "MEDIUM_CLOSE_UP") for i in range(6)]
                 + [_shot(f"S{i+8}", "SC1", 2.0, "MEDIUM") for i in range(3)])
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertFalse(any(f.startswith("DP1_") for f in report["failures"]))

    def test_ws_not_scene_opening_shot_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, "MEDIUM_CLOSE_UP"), _shot("S2", "SC1", 2.0, "WIDE")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertIn("DP1_WS_NOT_SCENE_OPENING_SHOT:S2", report["failures"])

    def test_ws_on_dialogue_shot_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, "WIDE", dialogue="台词")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP1_WS_FS_ON_DIALOGUE_SHOT:S1") for f in report["failures"]))

    def test_over_one_ws_per_scene_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, "WIDE"), _shot("S2", "SC1", 2.0, "MEDIUM_CLOSE_UP"),
                 _shot("S3", "SC1", 2.0, "WIDE")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP1_WS_OVER_1_PER_SCENE:SC1") for f in report["failures"]))


class DP2ReactionShotFloorTests(unittest.TestCase):
    def test_under_1s_floor_not_met_fails(self) -> None:
        shots = [_shot(f"S{i}", "SC1", 3.0) for i in range(10)]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP2_UNDER_1S_SHOT_RATIO_") for f in report["failures"]))

    def test_under_1s_floor_met_passes(self) -> None:
        shots = ([_shot(f"S{i}", "SC1", 0.5) for i in range(2)]
                 + [_shot(f"S{i+2}", "SC1", 3.0) for i in range(8)])
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertFalse(any(f.startswith("DP2_") for f in report["failures"]))


class DP3DialogueContinuityTests(unittest.TestCase):
    def test_silence_run_over_cap_without_reason_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, dialogue="台词"),
                 _shot("S2", "SC1", 4.0),  # 4s silence, no reason
                 _shot("S3", "SC1", 2.0, dialogue="台词")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP3_SILENCE_RUN_OVER_3S_NO_REASON:S2") for f in report["failures"]))

    def test_silence_run_with_reason_within_cap_passes(self) -> None:
        shots = ([_shot("S1", "SC1", 2.0, dialogue="台词")]
                 + [_shot("S2", "SC1", 4.0, silence_reason="悬念镜头，蓄势")]
                 + [_shot(f"S{i+3}", "SC1", 3.0, dialogue="台词多一点台词") for i in range(6)])
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertFalse(any(f.startswith("DP3_SILENCE_RUN") for f in report["failures"]))

    def test_silence_run_with_reason_but_over_exception_seconds_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, dialogue="台词"),
                 _shot("S2", "SC1", 7.0, silence_reason="超过 6s 上限"),
                 _shot("S3", "SC1", 2.0, dialogue="台词")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP3_SILENCE_RUN_EXCEEDS_EXCEPTION_CAP_6S:S2") for f in report["failures"]))

    def test_too_many_silence_exceptions_fails(self) -> None:
        shots = []
        for i in range(3):
            shots.append(_shot(f"D{i}", "SC1", 2.0, dialogue="台词"))
            shots.append(_shot(f"S{i}", "SC1", 4.0, silence_reason="蓄势"))
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP3_SILENCE_REASON_EXCEPTIONS_3_OVER_2") for f in report["failures"]))

    def test_dialogue_time_ratio_below_floor_fails(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, dialogue="台词")] + [_shot(f"S{i+2}", "SC1", 2.0, silence_reason="蓄势" if i == 0 else None) for i in range(1)]
        # 2s dialogue / (2+2)s total = 0.5 < 0.75
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(any(f.startswith("DP3_DIALOGUE_TIME_RATIO_") for f in report["failures"]))

    def test_dialogue_time_ratio_at_floor_passes(self) -> None:
        shots = [_shot("S1", "SC1", 6.0, dialogue="台词"), _shot("S2", "SC1", 2.0, silence_reason="蓄势")]
        # 6 / 8 = 0.75
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, POLICY)
        self.assertFalse(any(f.startswith("DP3_DIALOGUE_TIME_RATIO_") for f in report["failures"]))


class EnforcementGateTests(unittest.TestCase):
    def test_missing_policy_file_means_every_rule_is_a_no_op(self) -> None:
        empty_policy = dpg.load_policy(Path("/nonexistent/DIRECTION_POLICY_V1.json"))
        self.assertEqual(empty_policy, {})
        shots = [_shot(f"S{i}", "SC1", 2.0, "WIDE") for i in range(5)]  # would fail DP1 if enabled
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, empty_policy)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["status"], "PASS")

    def test_real_policy_file_loads(self) -> None:
        policy = dpg.load_policy(ROOT / "configs" / "DIRECTION_POLICY_V1.json")
        self.assertIn("rules", policy)
        self.assertTrue(policy["rules"]["DP1_shot_scale_distribution"]["enabled"])

    def test_unenforced_contract_reports_but_never_blocks_exit_code(self) -> None:
        # main()'s exit code path: status FAIL but enforced=False -> the caller (main) returns 0.
        shots = [_shot(f"S{i}", "SC1", 2.0, "WIDE") for i in range(5)]
        contract = {"episode": "E09", "shots": shots}  # no direction_policy.enforced key
        report = dpg.evaluate(contract, POLICY)
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["enforced"])

    def test_enforced_contract_flag_is_read(self) -> None:
        shots = [_shot(f"S{i}", "SC1", 2.0, "WIDE") for i in range(5)]
        contract = {"episode": "E09", "shots": shots, "direction_policy": {"enforced": True}}
        report = dpg.evaluate(contract, POLICY)
        self.assertTrue(report["enforced"])
        self.assertEqual(report["status"], "FAIL")


class StillWiredTests(unittest.TestCase):
    def test_dp4_dp6_dp7_markers_detected_when_present(self) -> None:
        shots = [{
            "shot_id": "S1", "scene_id": "SC1", "target_seconds": 2.0, "setup_id": "SETUP-1",
            "prompt_spec": {"camera_plan": {"shot_scale": "CLOSE_UP"}, "dialogue": "台词",
                            "action": {"performance": {"emotion": "焦虑", "body_action": "攥紧",
                                                       "delivery": "低声"}}},
        }]
        contract = {"episode": "E09", "shots": shots, "pressure_source": {"description": "x"}}
        report = dpg.evaluate(contract, {})
        wired = report["measurements"]["still_wired"]
        self.assertTrue(wired["DP4_performance_instruction_present"])
        self.assertTrue(wired["DP6_setup_payoff_present"])
        self.assertTrue(wired["DP7_pressure_source_fields_present"])

    def test_still_wired_false_when_absent(self) -> None:
        shots = [_shot("S1", "SC1", 2.0, dialogue="台词")]
        contract = {"episode": "E09", "shots": shots}
        report = dpg.evaluate(contract, {})
        wired = report["measurements"]["still_wired"]
        self.assertFalse(wired["DP4_performance_instruction_present"])
        self.assertFalse(wired["DP6_setup_payoff_present"])
        self.assertFalse(wired["DP7_pressure_source_fields_present"])


class LiteralRateFigureScanTests(unittest.TestCase):
    def test_finds_chinese_rate_figure(self) -> None:
        hits = dpg.scan_for_literal_rate_figure("台词语速 5.2字/秒，语气急促")
        self.assertEqual(hits, ["5.2字/秒"])

    def test_finds_english_rate_figure(self) -> None:
        hits = dpg.scan_for_literal_rate_figure("speak at 5 chars/sec, urgent tone")
        self.assertEqual(len(hits), 1)

    def test_clean_prompt_has_no_hits(self) -> None:
        hits = dpg.scan_for_literal_rate_figure("镜头中近景，人物急促地抢话，说完立即转身")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
