#!/usr/bin/env python3
"""Tests for the cut-motivation gate.

Roger, 2026-07-18 (`ROGER-20260718-NO-UNMOTIVATED-CUTS`):
「不改切的地方就别切，不能为了指标拼命切，搞得整个片子碎片化感非常严重」

The rule under test is motivation, not proportion. A cut with a substantiated
reason always passes; a cut without one never does.
"""

import json
import unittest
from pathlib import Path

from tools.cut_motivation_gate import CUT_REASONS, evaluate

FIXTURES = Path(__file__).parent / "fixtures"

E19R_PROJECT = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "e19r_agentcut_project_v15_headroom_safe_continuous_ambience_nalu_release_candidate_20260718.json"
)


def clip(index, start, duration=2.0, *, dialogue=None, reason=None, **meta):
    metadata = {"shot_index": index, "dialogue_id": dialogue}
    # Continuity fields default to a single consistent scene so that tests
    # about motivation are not also testing continuity. Cases that exercise
    # G9E override them explicitly.
    metadata.setdefault("scene_id", "alley")
    metadata.setdefault("light_key", "night_lantern")
    metadata.setdefault("axis_line", "A1")
    metadata.setdefault("eyeline", "RIGHT" if index % 2 == 0 else "LEFT")
    if reason:
        metadata["cut_reason"] = reason
    metadata.update(meta)
    return {"id": f"c{index}", "start": start, "duration": duration, "source": f"s{index}.mp4", "metadata": metadata}


def project(clips):
    return {"timeline": {"videoTracks": [{"clips": clips}]}}


class MotivationRequiredTest(unittest.TestCase):
    def test_cut_without_declared_reason_blocks(self):
        p = project([clip(0, 0.0, dialogue="DIA-001"), clip(1, 2.0, dialogue="DIA-002")])
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        finding = next(f for f in result["findings"] if f["gate"] == "G9_CUT_MOTIVATION")
        self.assertEqual(finding["count"], 1)

    def test_substantiated_reason_passes(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, dialogue="DIA-002", reason="SPEAKER_CHANGE", speaker="佛子"),
            ]
        )
        self.assertEqual(evaluate(p)["gate_status"], "PASS")

    def test_reason_label_without_evidence_blocks(self):
        """A rubber stamp is not a reason."""
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, dialogue="DIA-002", reason="NEW_INFORMATION"),  # no new_information field
            ]
        )
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(
            any("evidence field is empty" in f["detail"] for f in result["findings"])
        )

    def test_unknown_reason_is_not_accepted(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, dialogue="DIA-002", reason="LOOKS_BETTER", speaker="佛子"),
            ]
        )
        self.assertEqual(evaluate(p)["gate_status"], "REJECT_RECUT")

    def test_reason_vocabulary_is_closed(self):
        self.assertEqual(
            set(CUT_REASONS),
            {
                # 剧情
                "SPEAKER_CHANGE",
                "NEW_INFORMATION",
                "NEW_SPACE",
                "ACTION_BEAT",
                "REACTION_NEW_EMOTION",
                "ESTABLISH_ONCE",
                # 画面 / 审美
                "SHOT_SIZE_CHANGE",
                "COMPOSITION_INTENT",
            },
        )


class AntiGoodhartTest(unittest.TestCase):
    """不能为了指标拼命切。"""

    def test_cut_justified_by_asl_blocks(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-002",
                    reason="SPEAKER_CHANGE",
                    speaker="佛子",
                    cut_reason_note="补一刀把 ASL 压到 2.5s 以内",
                ),
            ]
        )
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G9B_ANTI_GOODHART" for f in result["findings"]))

    def test_filler_to_pad_a_window_blocks(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(
                    1,
                    2.0,
                    reason="NEW_INFORMATION",
                    new_information="凑对白窗口时长",
                ),
            ]
        )
        result = evaluate(p)
        self.assertTrue(any(f["gate"] == "G9B_ANTI_GOODHART" for f in result["findings"]))

    def test_insert_share_is_reported_but_never_a_threshold(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, reason="NEW_INFORMATION", new_information="红坠子露出缺口"),
                clip(2, 4.0, reason="NEW_INFORMATION", new_information="巡兵灯火照到墙根"),
                clip(3, 6.0, reason="NEW_INFORMATION", new_information="药架上的空格"),
            ]
        )
        result = evaluate(p)
        # 75% inserts, yet every one of them adds something: allowed.
        self.assertEqual(result["gate_status"], "PASS")
        self.assertGreater(result["diagnostics"]["insert_runtime_pct"], 50.0)


class InsertDisciplineTest(unittest.TestCase):
    def test_insert_that_adds_nothing_is_filler(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, reason="ACTION_BEAT", action="转身"),  # insert, no new_information
            ]
        )
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G9C_INSERT_MUST_ADD" for f in result["findings"]))

    def test_recycled_image_may_not_serve_as_filler(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
                clip(1, 2.0, reason="NEW_INFORMATION", new_information="巷口灯火"),
            ]
        )
        metrics = {
            "picture_repetition": {"non_adjacent_clusters": [[1, 7]]},
            "audio": {"shot_levels": [{"start": 0.0}, {"start": 2.0}]},
        }
        result = evaluate(p, metrics)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G9D_NO_RECYCLED_FILLER" for f in result["findings"]))


class PictureAndAestheticReasonsTest(unittest.TestCase):
    """Roger: cuts are made 为了剧情、为了画面、为了审美 — picture reasons are first-class."""

    def test_shot_size_change_is_a_valid_reason(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", shot_size="WS", scene_id="alley"),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-001",
                    speaker="陈迹",
                    reason="SHOT_SIZE_CHANGE",
                    shot_size="CU",
                    scene_id="alley",
                ),
            ]
        )
        self.assertEqual(evaluate(p)["gate_status"], "PASS")

    def test_declared_size_change_that_does_not_change_size_blocks(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", shot_size="CU", scene_id="alley"),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-001",
                    speaker="陈迹",
                    reason="SHOT_SIZE_CHANGE",
                    shot_size="CU",
                    scene_id="alley",
                ),
            ]
        )
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any("did not change" in f["detail"] for f in result["findings"]))

    def test_composition_intent_is_a_valid_reason_when_articulated(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", scene_id="alley"),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-002",
                    speaker="佛子",
                    reason="COMPOSITION_INTENT",
                    composition_note="把佛子压到画面下三分之一，让墙头空出来",
                    scene_id="alley",
                ),
            ]
        )
        self.assertEqual(evaluate(p)["gate_status"], "PASS")

    def test_composition_intent_without_a_stated_intention_blocks(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", scene_id="alley"),
                clip(1, 2.0, dialogue="DIA-002", speaker="佛子", reason="COMPOSITION_INTENT", scene_id="alley"),
            ]
        )
        self.assertEqual(evaluate(p)["gate_status"], "REJECT_RECUT")


class ViewingConsistencyTest(unittest.TestCase):
    """不能破坏观看一致性 — A/B cuts must preserve continuity."""

    def test_cut_without_continuity_fields_blocks(self):
        bare = [
            {"id": "c0", "start": 0.0, "duration": 2.0, "source": "a.mp4",
             "metadata": {"dialogue_id": "DIA-001", "speaker": "陈迹"}},
            {"id": "c1", "start": 2.0, "duration": 2.0, "source": "b.mp4",
             "metadata": {"dialogue_id": "DIA-002", "speaker": "佛子", "cut_reason": "SPEAKER_CHANGE"}},
        ]
        p = project(bare)
        result = evaluate(p)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any(f["gate"] == "G9E_VIEWING_CONSISTENCY" for f in result["findings"]))

    def test_light_change_inside_one_scene_blocks(self):
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", scene_id="alley", light_key="night_lantern"),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-002",
                    speaker="佛子",
                    reason="SPEAKER_CHANGE",
                    scene_id="alley",
                    light_key="day_overcast",
                ),
            ]
        )
        result = evaluate(p)
        self.assertTrue(any("light_key changes" in f["detail"] for f in result["findings"]))

    def test_crossing_the_axis_blocks_unless_justified(self):
        base = dict(scene_id="alley", light_key="night_lantern")
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", axis_line="A1", **base),
                clip(1, 2.0, dialogue="DIA-002", speaker="佛子", reason="SPEAKER_CHANGE", axis_line="A2", **base),
            ]
        )
        self.assertTrue(any("screen direction" in f["detail"] for f in evaluate(p)["findings"]))

        p2 = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", axis_line="A1", **base),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-002",
                    speaker="佛子",
                    reason="SPEAKER_CHANGE",
                    axis_line="A2",
                    line_cross_justified="随陈迹绕到佛子另一侧，镜头跟走过轴",
                    **base,
                ),
            ]
        )
        self.assertEqual(evaluate(p2)["gate_status"], "PASS")

    def test_shot_reverse_that_fails_to_reverse_blocks(self):
        base = dict(scene_id="alley", light_key="night_lantern", axis_line="A1")
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", eyeline="left", **base),
                clip(1, 2.0, dialogue="DIA-002", speaker="佛子", reason="SPEAKER_CHANGE", eyeline="left", **base),
            ]
        )
        self.assertTrue(any("fails to reverse" in f["detail"] for f in evaluate(p)["findings"]))

    def test_same_group_same_size_is_a_jump_cut(self):
        base = dict(scene_id="alley", light_key="night_lantern", axis_line="A1")
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", coverage_group="A", shot_size="MS", **base),
                clip(
                    1,
                    2.0,
                    dialogue="DIA-001",
                    speaker="陈迹",
                    reason="COMPOSITION_INTENT",
                    composition_note="换个角度",
                    coverage_group="A",
                    shot_size="MS",
                    **base,
                ),
            ]
        )
        self.assertTrue(any("jump cut" in f["detail"] for f in evaluate(p)["findings"]))

    def test_measured_luma_jump_blocks_even_when_declarations_are_clean(self):
        """Declared continuity is still only a declaration."""
        base = dict(scene_id="alley", light_key="night_lantern", axis_line="A1")
        p = project(
            [
                clip(0, 0.0, dialogue="DIA-001", speaker="陈迹", eyeline="left", **base),
                clip(1, 2.0, dialogue="DIA-002", speaker="佛子", reason="SPEAKER_CHANGE", eyeline="right", **base),
            ]
        )
        metrics = {"video_continuity": {"shot_luma": [20.0, 60.0]}}
        result = evaluate(p, metrics)
        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        self.assertTrue(any("luma jump" in f["detail"] for f in result["findings"]))


class MultiTrackTest(unittest.TestCase):
    """Found by the cross-episode scan: E18R v10 has an underlay track.

    Ten 12.0s clips with empty metadata sit beneath the real 38-clip cut.
    Flattening all tracks counted those as editorial cuts and as picture
    inserts, reporting 47 cuts / 15 inserts / 52.8% insert runtime instead of
    the true 37 / 5 / 14%.
    """

    def test_underlay_track_is_not_mistaken_for_cuts(self):
        underlay = [
            {"id": f"u{i}", "start": i * 12.0, "duration": 12.0, "source": "bed.mp4", "metadata": {}}
            for i in range(3)
        ]
        editorial = [
            clip(0, 0.0, dialogue="DIA-001", speaker="陈迹"),
            clip(1, 2.0, dialogue="DIA-002", speaker="佛子", reason="SPEAKER_CHANGE"),
            clip(2, 4.0, dialogue="DIA-003", speaker="陈迹", reason="SPEAKER_CHANGE"),
        ]
        project_multi = {"timeline": {"videoTracks": [{"clips": underlay}, {"clips": editorial}]}}

        result = evaluate(project_multi)

        self.assertEqual(result["cut_count"], 2)
        self.assertEqual(result["diagnostics"]["insert_count"], 0)
        self.assertEqual(result["gate_status"], "PASS")


class E19RShippedProjectBacktest(unittest.TestCase):
    """The real edit project that produced the episode Roger called 碎片化."""

    def setUp(self):
        if not E19R_PROJECT.is_file():
            self.skipTest("E19R agentcut project not available")
        self.project = json.loads(E19R_PROJECT.read_text(encoding="utf-8"))

    def test_every_single_cut_is_unmotivated(self):
        result = evaluate(self.project)

        self.assertEqual(result["gate_status"], "REJECT_RECUT")
        finding = next(f for f in result["findings"] if f["gate"] == "G9_CUT_MOTIVATION")
        # 71 cuts, none of them carrying a reason.
        self.assertEqual(finding["count"], finding["of_cuts"])
        self.assertEqual(finding["of_cuts"], 71)

    def test_almost_every_insert_adds_nothing(self):
        """30 of 32 inserts are filler.

        8 carried `insert_reason`, the only stated purposes in the episode —
        but 6 of those 8 read "... reaction punctuation", i.e. cut to punctuate
        a rhythm, which is the banned move and therefore cannot also excuse
        itself. Only 2 inserts survive on a real reason (the patrol-light
        cutaway that motivates the approaching-patrol dialogue).
        """
        result = evaluate(self.project)
        finding = next(f for f in result["findings"] if f["gate"] == "G9C_INSERT_MUST_ADD")
        self.assertEqual(finding["count"], 30)
        self.assertEqual(finding["of_inserts"], 32)

    def test_rhythm_justifications_are_caught(self):
        """The compiler's own fallback reason was `cadence_reaction_cut`."""
        result = evaluate(self.project)
        finding = next(f for f in result["findings"] if f["gate"] == "G9B_ANTI_GOODHART")
        self.assertEqual(finding["count"], 6)

    def test_no_cut_carries_continuity_fields(self):
        """A/B continuity is defined in the coverage schema and never reached the cut."""
        result = evaluate(self.project)
        finding = next(
            f for f in result["findings"]
            if f["gate"] == "G9E_VIEWING_CONSISTENCY" and "no continuity fields" in f["detail"]
        )
        self.assertEqual(finding["count"], 71)
        self.assertEqual(finding["of_cuts"], 71)

    def test_measured_luma_breaks_exist_in_the_shipped_film(self):
        metrics = json.loads((FIXTURES / "e19r_v15_objective_metrics.json").read_text(encoding="utf-8"))
        result = evaluate(self.project, metrics)
        finding = next(f for f in result["findings"] if "luma jump" in f["detail"])
        self.assertEqual(finding["count"], 6)

    def test_inserts_eat_46_percent_of_runtime(self):
        result = evaluate(self.project)
        self.assertAlmostEqual(result["diagnostics"]["insert_runtime_pct"], 46.14, places=1)


if __name__ == "__main__":
    unittest.main()
