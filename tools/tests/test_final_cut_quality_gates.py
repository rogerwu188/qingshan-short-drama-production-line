#!/usr/bin/env python3
"""Tests for the post-E19R final-cut quality gates.

The governing question for every test here: would this gate have stopped the
E19R V15 release? The shipped artifacts are used as the negative fixture, so
these tests fail if anyone loosens a threshold back to where it was.
"""

import json
import unittest
from pathlib import Path

from tools.final_cut_quality_gates import (
    MAX_DOMINANT_LOCATION_PCT,
    MAX_METAPHOR_LINE_PCT,
    MAX_NEAR_DUPLICATE_SHOT_PCT,
    MIN_CRAFT_DIMENSION,
    evaluate,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def good_metrics(**overrides) -> dict:
    metrics = {
        "schema": "qingshan.final_cut_objective_metrics.v1",
        "measured_from": "DECODED_FINAL_MP4",
        "duration_seconds": 180.0,
        "shot_count": 4,
        "sampled_shot_count": 4,
        "picture_repetition": {
            "near_duplicate_shot_pct": 0.0,
            "near_duplicate_shot_pct_non_adjacent": 0.0,
            "clusters": [],
            "non_adjacent_clusters": [],
        },
        "palette_uniformity_ADVISORY": {"dominant_cluster_pct": 30.0, "clusters": 5},
        "audio": {"digital_zero_shots": [], "level_jump_over_12db_count": 0},
    }
    metrics.update(overrides)
    return metrics


def good_report(**overrides) -> dict:
    report = {
        "episode": "E-TEST",
        "dimensions": {
            "story": 4.0,
            "continuation": 4.0,
            "pacing": 4.0,
            "opening": 4.0,
            "clarity": 4.0,
            "visual": 4.0,
            "anti_ai": 4.0,
            "completeness": 4.8,
        },
        "problems": [],
        "evidence": {
            "burned_subtitles": True,
            "identity_color_consistent": True,
            "opening_3s_hook": True,
            "shot_notes": [
                "陈迹推门进来，手里还攥着药包",
                "佛子转身，眼神落在红坠子上",
                "巡兵灯火从巷口扫过，两人贴墙",
                "药架被撞歪，陶罐滚到脚边",
            ],
        },
    }
    report.update(overrides)
    return report


def good_ledger() -> dict:
    return {"events": [{"t": t, "what": f"event at {t}"} for t in (3.0, 20.0, 38.0, 55.0, 72.0, 90.0, 108.0, 125.0, 142.0, 160.0, 176.0)]}


class WeakestLinkTest(unittest.TestCase):
    def test_zero_dialogue_cut_requires_complete_machine_evidence_for_subtitle_na(self):
        report = good_report()
        report["evidence"]["burned_subtitles"] = False
        report["evidence"]["subtitle_requirement"] = {
            "status": "NOT_APPLICABLE_ZERO_DIALOGUE",
            "adjusted_spoken_line_count": 0,
            "whole_track_asr_segment_count": 0,
            "script_adjustment_evidence_ref": "qa/script_adjustment.json",
            "whole_track_asr_evidence_ref": "qa/whole_track_asr.json",
        }

        result = evaluate(report, good_metrics(), event_ledger=good_ledger())

        self.assertEqual(result["gate_status"], "PASS")

    def test_zero_dialogue_subtitle_na_cannot_be_self_asserted_without_asr_ref(self):
        report = good_report()
        report["evidence"]["burned_subtitles"] = False
        report["evidence"]["subtitle_requirement"] = {
            "status": "NOT_APPLICABLE_ZERO_DIALOGUE",
            "adjusted_spoken_line_count": 0,
            "whole_track_asr_segment_count": 0,
            "script_adjustment_evidence_ref": "qa/script_adjustment.json",
        }

        result = evaluate(report, good_metrics(), event_ledger=good_ledger())

        self.assertEqual(result["gate_status"], "REJECT_RECUT")

    def test_compliance_score_cannot_lift_weak_craft_dimensions(self):
        """E19R R5: completeness 4.8 pulled visual 3.4 / anti_ai 3.3 to a passing 3.7."""
        report = good_report()
        report["dimensions"]["visual"] = 3.4
        report["dimensions"]["anti_ai"] = 3.3
        report["dimensions"]["completeness"] = 5.0

        result = evaluate(report, good_metrics(), event_ledger=good_ledger())

        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        floors = [f for f in result["findings"] if f["gate"] == "G4_WEAKEST_LINK"]
        self.assertEqual({f["dimension"] for f in floors}, {"visual", "anti_ai"})

    def test_mean_is_never_used(self):
        report = good_report()
        report["dimensions"].update({"visual": 1.0, "completeness": 5.0})
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["weakest_craft_dimension"], 1.0)
        self.assertFalse(result["release_allowed"])

    def test_dimension_exactly_at_floor_passes(self):
        report = good_report()
        report["dimensions"]["visual"] = MIN_CRAFT_DIMENSION
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "PASS")


class ViewingEvidenceTest(unittest.TestCase):
    def test_decode_receipt_is_not_a_viewing(self):
        """E19R R1: three 'viewing passes' evidenced by ffmpeg exit codes."""
        report = good_report()
        report["evidence"]["playback_evidence"] = {
            "full_1x": "ffmpeg_realtime_decode_session_25103_exit_0",
            "muted": "ffmpeg_realtime_decode_session_94869_exit_0",
            "sound": "ffmpeg_realtime_decode_session_44685_exit_0",
        }
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")
        self.assertTrue(any(f["gate"] == "G1_VIEWING_EVIDENCE" for f in result["findings"]))

    def test_missing_shot_notes_cannot_constitute_the_gate(self):
        report = good_report()
        report["evidence"].pop("shot_notes")
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")

    def test_notes_must_cover_every_shot(self):
        result = evaluate(
            good_report(), good_metrics(shot_count=40, sampled_shot_count=40), event_ledger=good_ledger()
        )
        self.assertEqual(result["gate_status"], "INVALID")

    def test_boilerplate_notes_rejected(self):
        report = good_report()
        report["evidence"]["shot_notes"] = ["画面正常，无异常" for _ in range(4)]
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")


class PictureRepetitionTest(unittest.TestCase):
    def test_e19r_repetition_blocks(self):
        metrics = good_metrics(
            shot_count=68,
            sampled_shot_count=68,
            picture_repetition={
            "near_duplicate_shot_pct": 29.412,
            "near_duplicate_shot_pct_non_adjacent": 29.412,
            "clusters": [[20, 23, 59]],
            "non_adjacent_clusters": [[20, 23, 59]],
        },
        )
        report = good_report()
        report["evidence"]["shot_notes"] = [f"第{i}镜，具体内容描述" for i in range(68)]
        result = evaluate(report, metrics, event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G2_PICTURE_REPETITION" for f in result["findings"]))

    def test_sampling_sparser_than_cut_is_invalid(self):
        """E19R R3: 23 samples for 69 shots cannot see repetition."""
        metrics = good_metrics(shot_count=69, sampled_shot_count=23)
        report = good_report()
        report["evidence"]["shot_notes"] = [f"第{i}镜，具体内容描述" for i in range(69)]
        result = evaluate(report, metrics, event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")

    def test_source_identity_dedup_basis_banned(self):
        """E19R R2: 40 distinct source files rendering one picture."""
        report = good_report()
        report["evidence"]["semantic_group_basis"] = "agentcut_source_identity"
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")
        self.assertTrue(any(f["gate"] == "G2B_DEDUP_BASIS" for f in result["findings"]))

    def test_threshold_not_silently_loosened(self):
        self.assertEqual(MAX_NEAR_DUPLICATE_SHOT_PCT, 10.0)


class FingerprintNamingTest(unittest.TestCase):
    def test_fingerprint_masquerading_as_repetition_gate(self):
        """E19R R3: no hamming/duplicate field anywhere in the 'aHash gate'."""
        adjudication = {
            "schema": "qingshan.supervisor_ahash_timeout_machine_adjudication.v2",
            "status": "PASS_MACHINE_SUPERVISOR_AHASH",
            "confidence": 0.96,
            "ahash": {
                "algorithm": "8x8-grayscale-average-hash",
                "sample_interval_seconds": 8.0,
                "sample_count": 23,
                "aggregate_sha256": "d9effc94",
            },
        }
        result = evaluate(good_report(), good_metrics(), adjudication=adjudication, event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")
        gates = [f["gate"] for f in result["findings"]]
        self.assertIn("G3_GATE_NAMING", gates)

    def test_real_repetition_gate_accepted(self):
        adjudication = {
            "schema": "qingshan.shot_repetition_gate.v1",
            "status": "PASS_SHOT_REPETITION",
            "hamming_threshold": 5,
            "near_duplicate_shot_pct": 4.2,
            "duplicate_clusters": [],
        }
        result = evaluate(good_report(), good_metrics(), adjudication=adjudication, event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "PASS")


class SelfWaiverTest(unittest.TestCase):
    def test_gate_cannot_waive_its_own_finding(self):
        """E19R R4: found '夜巷持续较久', fixed it with '不构成重剪硬项'."""
        report = good_report(
            problems=[{"t": "B03-B04", "issue": "夜巷主色调和场景持续较久", "fix": "本集镜头源轮换充分，不构成重剪硬项"}]
        )
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "INVALID")
        self.assertTrue(any(f["gate"] == "G5_NO_SELF_WAIVER" for f in result["findings"]))

    def test_problems_without_waiver_escalate_rather_than_pass(self):
        report = good_report(problems=[{"t": "B02", "issue": "人物近景密度偏高", "fix": "提交监制复检"}])
        result = evaluate(report, good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "ESCALATE_TO_SUPERVISOR")
        self.assertFalse(result["release_allowed"])


class WithdrawnLocationGateTest(unittest.TestCase):
    """G6 was withdrawn as a blocker on 2026-07-18 after E16 falsified it.

    Measured with identical code:

        E19R  86.5%  genuinely one alley (verified by eye)   -> true positive
        E16   88.8%  clinic + courtyard + street (verified)  -> FALSE POSITIVE

    E16 scores *higher* while being visibly more varied, because the whole
    episode shares one dark-blue candlelit grade. A structural signature was
    tried and inverted the ranking further (E16 32.2% near pairs vs E19R
    21.0%). The metric measures palette uniformity, not location count.

    These tests exist so nobody re-promotes it to a blocker without first
    producing a signal that separates E16 from E19R.
    """

    def test_palette_uniformity_never_blocks(self):
        metrics = good_metrics(
            palette_uniformity_ADVISORY={"dominant_cluster_pct": 86.471, "status": "NOT_VALIDATED_DO_NOT_GATE_ON_THIS"}
        )
        result = evaluate(good_report(), metrics, event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "PASS")
        finding = next(f for f in result["findings"] if f["gate"] == "G6_PALETTE_UNIFORMITY_ADVISORY")
        self.assertEqual(finding["severity"], "OBSERVE")

    def test_e16_would_have_been_a_false_positive_under_the_old_blocker(self):
        e16 = _load("e16_falsifier_objective_metrics.json")
        e19r = _load("e19r_v15_objective_metrics.json")

        e16_pct = e16["palette_uniformity_ADVISORY"]["dominant_cluster_pct"]
        e19r_pct = e19r["palette_uniformity_ADVISORY"]["dominant_cluster_pct"]

        # The falsifying fact: the visibly-varied episode scores higher than
        # the genuinely single-location one. Any future replacement metric
        # must invert this relationship before it may block.
        self.assertGreater(e16_pct, e19r_pct)
        self.assertGreater(e16_pct, MAX_DOMINANT_LOCATION_PCT)

    def test_result_records_the_withdrawal(self):
        result = evaluate(good_report(), good_metrics(), event_ledger=good_ledger())
        self.assertIn("G6_LOCATION_DIVERSITY", result["withdrawn_gates"])


class EventLedgerTest(unittest.TestCase):
    def test_dialogue_density_does_not_substitute_for_events(self):
        """E19R: 13 lines/min passed while ~150s carried no external event."""
        ledger = {"events": [{"t": 2.0, "what": "和尚卡在墙上"}, {"t": 155.0, "what": "巡兵出现"}]}
        result = evaluate(good_report(), good_metrics(), event_ledger=ledger)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        gap = next(f for f in result["findings"] if f["gate"] == "G7_EVENT_LEDGER")
        self.assertGreater(gap["gaps"][0]["gap"], 20.0)

    def test_absent_ledger_is_invalid_not_pass(self):
        result = evaluate(good_report(), good_metrics(), event_ledger=None)
        self.assertEqual(result["gate_status"], "INVALID")


class DialogueLegibilityTest(unittest.TestCase):
    def test_all_riddles_blocks(self):
        script = {"lines": [{"text": f"line {i}", "metaphor": i < 8} for i in range(10)]}
        result = evaluate(good_report(), good_metrics(), event_ledger=good_ledger(), script=script)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G8_DIALOGUE_LEGIBILITY" for f in result["findings"]))

    def test_mixed_dialogue_passes(self):
        script = {"lines": [{"text": f"line {i}", "metaphor": i < 3} for i in range(10)]}
        result = evaluate(good_report(), good_metrics(), event_ledger=good_ledger(), script=script)
        self.assertEqual(result["gate_status"], "PASS")

    def test_ceiling_not_loosened(self):
        self.assertEqual(MAX_METAPHOR_LINE_PCT, 40.0)


class HappyPathTest(unittest.TestCase):
    def test_clean_episode_still_passes(self):
        """Guard against a gate that rejects everything."""
        result = evaluate(good_report(), good_metrics(), event_ledger=good_ledger())
        self.assertEqual(result["gate_status"], "PASS")
        self.assertTrue(result["release_allowed"])

    def test_timeout_autopass_is_never_offered(self):
        result = evaluate(good_report(), good_metrics(), event_ledger=good_ledger())
        self.assertFalse(result["timeout_autopass_allowed"])


class E19RShippedArtifactBacktest(unittest.TestCase):
    """The decisive test: replay the real shipped artifacts through the new gates."""

    def test_shipped_e19r_v15_would_have_been_stopped(self):
        report = _load("e19r_v15_audience_report.json")
        metrics = _load("e19r_v15_objective_metrics.json")
        adjudication = _load("e19r_v15_supervisor_adjudication.json")

        result = evaluate(report, metrics, adjudication=adjudication)

        self.assertNotEqual(result["gate_status"], "PASS")
        self.assertFalse(result["release_allowed"])
        gates = {f["gate"] for f in result["findings"]}
        # Every documented root cause must be independently caught.
        self.assertIn("G1_VIEWING_EVIDENCE", gates)  # R1 decode receipts
        self.assertIn("G2B_DEDUP_BASIS", gates)  # R2 filename dedup
        self.assertIn("G2_PICTURE_REPETITION", gates)  # 29.4% repeats
        self.assertIn("G3_GATE_NAMING", gates)  # R3 fingerprint-as-gate
        self.assertIn("G4_WEAKEST_LINK", gates)  # R5 visual 3.4 / anti_ai 3.3
        self.assertIn("G5_NO_SELF_WAIVER", gates)  # R4 self-issued waiver
        self.assertIn("G7_EVENT_LEDGER", gates)  # no ledger was ever produced
        # G6 is deliberately absent: withdrawn as a blocker, see
        # WithdrawnLocationGateTest. E19R is still stopped four times over
        # without it.


class CalibrationControlTest(unittest.TestCase):
    """Guard against a gate calibrated so tight it condemns every episode.

    E14 is a published episode that was never flagged for repetition or for
    single-location monotony. Measured with the same code as E19R:

        E19R V15  68 shots  non-adjacent repetition 29.4%
        E14       29 shots  non-adjacent repetition  6.9%

    The 10% threshold sits between the two, not below both.
    """

    def test_control_episode_clears_the_measured_thresholds(self):
        metrics = _load("e14_control_objective_metrics.json")
        repetition = metrics["picture_repetition"]["near_duplicate_shot_pct_non_adjacent"]
        self.assertLess(repetition, MAX_NEAR_DUPLICATE_SHOT_PCT)

    def test_control_episode_is_not_blocked_by_measured_gates(self):
        metrics = _load("e14_control_objective_metrics.json")
        report = good_report()
        report["evidence"]["shot_notes"] = [f"第{i}镜，具体可辨内容" for i in range(metrics["shot_count"])]

        result = evaluate(report, metrics, event_ledger=good_ledger())

        measured_gates = {"G2_PICTURE_REPETITION"}
        fired = {f["gate"] for f in result["findings"]} & measured_gates
        self.assertEqual(fired, set())
        self.assertEqual(result["gate_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
