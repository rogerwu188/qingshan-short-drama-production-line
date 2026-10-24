"""CAMERA_GRAMMAR_V1 start frames (line owner 2026-10-24, lab Holmes E03 VU-001/002/007).

1. keyframe framing vs required fixed elements (scale-aware prompt line + Q1 question);
2. speaking units keep the speaker's eyes on the listener (renderer clause);
3. a speaking unit only takes the previous tail as start frame when the objective speaker check accepts it;
4. a controlled redo after an objective speaker-framing / face-count FAIL switches to an own keyframe.
Unstamped contracts are unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_keyframe_manifest as bkm  # noqa: E402
import camera_grammar_policy as cg  # noqa: E402
import nalu_pipeline as npl  # noqa: E402
import video_q2_builder as q2  # noqa: E402
import vlm_review_protocol as vrp  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402

STAMPED = {"episode": "E03", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}
LEGACY = {"episode": "E03", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}
IDS = "FIXED-1；FIXED-2；FIXED-3；FIXED-4；FIXED-5"
W = 768.0


class FixedElementRuleTests(unittest.TestCase):
    def test_modes_by_scale(self):
        for scale in ("CLOSE_UP", "EXTREME_CLOSE_UP", "MEDIUM_CLOSE_UP", "medium close-up"):
            self.assertEqual(cg.fixed_element_rule(scale)["mode"], "NONE_REQUIRED", scale)
        self.assertEqual(cg.fixed_element_rule("MEDIUM")["mode"], "AT_MOST_TWO")
        self.assertEqual(cg.fixed_element_rule("MEDIUM")["max_required"], 2)
        for scale in ("WIDE", "MEDIUM_WIDE", "FULL", "", None):
            self.assertEqual(cg.fixed_element_rule(scale)["mode"], "ALL_MAPPED", scale)
        self.assertIn("mid-chest up", cg.fixed_element_rule("MEDIUM_CLOSE_UP")["picture_range_zh"])

    def test_prompt_line_is_legacy_when_unstamped(self):
        self.assertEqual(bkm.fixed_elements_prompt_line(None, IDS),
                         f"可见固定元素（必须全部出现且相对位置与拓扑图一致）：{IDS}")
        wide = bkm.fixed_elements_prompt_line(cg.fixed_element_rule("WIDE"), IDS)
        self.assertEqual(wide, bkm.fixed_elements_prompt_line(None, IDS))
        close = bkm.fixed_elements_prompt_line(cg.fixed_element_rule("MEDIUM_CLOSE_UP"), IDS)
        self.assertIn("不要求出现", close)
        self.assertNotIn("必须全部出现", close)
        self.assertIn("最多出现其中 2 件", bkm.fixed_elements_prompt_line(cg.fixed_element_rule("MEDIUM"), IDS))

    def test_framing_rule_only_for_stamped_contracts(self):
        shot = {"shot_size": "MEDIUM_CLOSE_UP"}
        stamped = SimpleNamespace(contract=STAMPED, episode="E03")
        legacy = SimpleNamespace(contract=LEGACY, episode="E03")
        self.assertEqual(bkm.keyframe_framing_rule(stamped, shot, {})["mode"], "NONE_REQUIRED")
        self.assertIsNone(bkm.keyframe_framing_rule(legacy, shot, {}))

    def test_q1_question_is_scale_aware_only_for_rule_carrying_items(self):
        legacy_q = vrp.QUESTIONNAIRES["keyframe"]["space_anchors_match"]["question"]
        self.assertIn("mapped fixed elements in their", legacy_q)
        self.assertIn("require NO mapped fixed element", vrp.SCALE_AWARE_SPACE_ANCHORS_QUESTION)

        class Exp:
            def __init__(self, _ep, rule):
                self.shots, self.library, self.rule = {}, {}, rule
            def character_ids(self): return []
            def character_name_to_id(self): return {}
            def forbidden_terms(self): return []
            def identity_subjects(self): return []
            def keyframe_items(self):
                exp = {"shot_size": "MEDIUM_CLOSE_UP"}
                if self.rule:
                    exp["fixed_element_rule"] = cg.fixed_element_rule("MEDIUM_CLOSE_UP")
                return [{"item_id": "S1", "unit_id": "U1", "media_path": "/nonexistent.png", "expectations": exp}]

        with tempfile.TemporaryDirectory() as d:
            for rule, expected in ((True, vrp.SCALE_AWARE_SPACE_ANCHORS_QUESTION), (False, legacy_q)):
                with mock.patch.object(vrp, "Expectations", lambda ep, r=rule: Exp(ep, r)), \
                        mock.patch.object(vrp, "QaPaths", lambda ep: SimpleNamespace()):
                    req = vrp.build_request("keyframe", "E03", out=Path(d) / f"{rule}.json")
                self.assertEqual(req["questionnaire"]["space_anchors_match"]["question"], expected)
            self.assertEqual(vrp.QUESTIONNAIRES["keyframe"]["space_anchors_match"]["question"], legacy_q)


class SpeakerGazeClauseTests(unittest.TestCase):
    def unit(self, appearance="An English woman of thirty."):
        return {"character_entities": [{"character_id": "CHAR-H", "appearance_ch1": appearance}]}

    def test_clause_uses_name_and_pronoun(self):
        binding = {"character_id": "CHAR-H", "provider_entity_label": "Helen", "visible_speaker": True}
        self.assertEqual(h3.speaker_gaze_clause(self.unit(), binding),
                         "While speaking Helen keeps her eyes on the listener; the camera does not follow her gaze.")
        self.assertIn("keeps his eyes", h3.speaker_gaze_clause(self.unit("A lean English man."), binding))
        self.assertIn("keeps their eyes", h3.speaker_gaze_clause(self.unit("A figure."), binding))
        self.assertEqual(h3.speaker_gaze_clause(self.unit(), {**binding, "visible_speaker": False}), "")

    def test_v2_renders_clause_only_for_stamped_units(self):
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        import test_h3_director_prompt_v2 as v2t
        text, _ = v2t.render()
        self.assertIn("keeps their eyes on the listener; the camera does not follow their gaze.", text)
        legacy, _ = v2t.render(style=False, director=False)
        self.assertNotIn("does not follow", legacy)


def solo(fv="FRONT_VISIBLE", line="Helen：My name is Helen Stoner.", shot="S1"):
    return {"editorial_shot_ids": [shot],
            "cast": [{"shot_id": shot, "character": "Helen", "character_id": "CHAR-HELEN",
                      "screen_slot": "SLOT_1", "face_visibility": fv}],
            "expected_dialogue": [{"shot_id": shot, "spoken_text": line}] if line else []}


def frame(*boxes):
    return {"width": W, "faces": [{"bbox": [x1, 400.0, x2, 560.0]} for x1, x2 in boxes]}


class StartFrameVerdictTests(unittest.TestCase):
    def test_centred_speaker_accepted(self):
        v = q2.start_frame_speaker_verdict(solo(), frame((300.0, 470.0)))
        self.assertEqual((v["status"], v["verdict"], v["reasons"]), ("MEASURED", "ACCEPT", []))

    def test_missing_edge_cut_or_extra_face_rejected(self):
        cases = {"NO_FACE_DETECTED": frame(),
                 "FACE_CUT_AT_EDGE": frame((-60.0, 100.0)),
                 "START_FRAME_FACE_TOUCHES_EDGE": frame((-4.8, 213.5)),     # E03 VU-005 tail
                 "START_FRAME_FACE_CENTRE_AT_EDGE": frame((26.7, 211.1))}   # E03 VU-002 tail
        for reason, f in cases.items():
            v = q2.start_frame_speaker_verdict(solo(), f)
            self.assertEqual(v["verdict"], "REJECT", reason)
            self.assertIn(reason, v["reasons"])
        v = q2.start_frame_speaker_verdict(solo(), {"width": W, "faces": [
            {"bbox": [300.0, 400.0, 470.0, 560.0], "similarity": {"CHAR-HELEN": 0.8}},
            {"bbox": [500.0, 400.0, 600.0, 560.0], "similarity": {"CHAR-HELEN": 0.05}}]})
        self.assertIn("FACE_COUNT_EXCEEDS_DECLARED:2>1", v["reasons"])

    def test_non_speaking_units_keep_the_tail(self):
        for exp in (solo(line=None), solo(fv="OFFSCREEN_VOICE_ONLY"), solo(fv="BACK_TO_CAMERA")):
            v = q2.start_frame_speaker_verdict(exp, frame())
            self.assertEqual((v["status"], v["verdict"]), ("NOT_APPLICABLE", "ACCEPT"))

    def test_scoped_to_first_shot(self):
        exp = {"editorial_shot_ids": ["S1", "S2"],
               "cast": solo(shot="S1", line=None)["cast"] + solo(shot="S2")["cast"],
               "expected_dialogue": solo(shot="S2")["expected_dialogue"]}
        scoped = q2.first_shot_expectations(exp)
        self.assertEqual(q2.start_frame_speaker_verdict(scoped, frame())["status"], "NOT_APPLICABLE")
        with mock.patch.object(q2, "detect_unit_faces") as detect:
            row = q2.check_start_frame("E03", "U2", Path("/nonexistent.png"), expectations=exp)
        detect.assert_not_called()
        self.assertEqual(row["verdict"], "ACCEPT")


class PipelineFixture:
    def __init__(self, tmp: Path, contract: dict, derived: bool = True):
        self.tmp = tmp
        preprod = tmp / "preproduction"
        for sub in ("keyframes", "real_final_frames", "reports", "prompts/keyframes"):
            (preprod / sub).mkdir(parents=True, exist_ok=True)
        (tmp / "video").mkdir()
        (tmp / "contract.json").write_text(json.dumps(contract))
        (preprod / "E03_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": [
            {"unit_id": "E03-VU-001", "editorial_shot_ids": ["E03-S01-01"]},
            {"unit_id": "E03-VU-002", "editorial_shot_ids": ["E03-S01-02"]}]}))
        self.tail = preprod / "real_final_frames" / "E03-VU-001.png"
        self.tail.write_bytes(b"tail of VU-001")
        self.kf2 = preprod / "keyframes" / "E03-S01-02-keyframe-v1.png"
        self.ctx = SimpleNamespace(
            episode="E03", dry=False, run_id="RUN1", say=lambda *_a, **_k: None,
            p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", contract=tmp / "contract.json",
                              video_media=tmp / "video", keyframes=preprod / "keyframes",
                              q2_dir=preprod / "reports" / "qa" / "q2"))
        info = {"E03-VU-002": {"previous_unit_id": "E03-VU-001", "first_shot_id": "E03-S01-02",
                               "keyframe_path": self.kf2}} if derived else {}
        self.patches = [mock.patch.object(npl, "continuity_derived_units", lambda _ctx: dict(info)),
                        mock.patch.object(npl, "ENGINE", tmp / "engine")]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()

    def decisions(self):
        return npl.start_frame_source_decisions(self.ctx)


class TailStartFrameTests(unittest.TestCase):
    def test_rejected_tail_is_not_copied_and_recorded(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            reject = {"verdict": "REJECT", "status": "MEASURED", "reasons": ["NO_FACE_DETECTED"], "faces": 0}
            with mock.patch.object(npl, "check_tail_start_frame", return_value=reject) as check:
                rows = npl.materialise_derived_keyframes(fx.ctx)
                self.assertEqual(rows[0]["status"], "OWN_KEYFRAME_REQUIRED")
                self.assertFalse(fx.kf2.exists())
                row = fx.decisions()["E03-VU-002"]
                self.assertEqual(row["start_frame_source"], "OWN_KEYFRAME_TAIL_REJECTED")
                self.assertEqual(row["measurement"]["reasons"], ["NO_FACE_DETECTED"])
                # the same tail is not re-measured; the own keyframe is what the unit needs now
                npl.materialise_derived_keyframes(fx.ctx)
                self.assertEqual(check.call_count, 1)
            self.assertEqual(npl.own_keyframes_needed(fx.ctx), ["E03-VU-002"])
            self.assertIn("E03-S01-02-KEYFRAME-V1.txt", npl.s5_keyframes_missing(fx.ctx))
            # the keyframe builder now compiles the opener instead of deferring it to the tail
            self.assertEqual(bkm.own_start_frame_units(SimpleNamespace(dir=fx.ctx.p.preprod, episode="E03")),
                             {"E03-VU-002"})

    def test_accepted_tail_is_copied_with_its_measurement(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            ok = {"verdict": "ACCEPT", "status": "MEASURED", "reasons": [], "faces": 1}
            with mock.patch.object(npl, "check_tail_start_frame", return_value=ok):
                rows = npl.materialise_derived_keyframes(fx.ctx)
            self.assertEqual(rows[0]["status"], "MATERIALISED")
            self.assertEqual(fx.kf2.read_bytes(), fx.tail.read_bytes())
            side = json.loads(fx.kf2.with_suffix(".derived.json").read_text())
            self.assertEqual(side["start_frame_source"], "TAIL_FRAME")
            self.assertEqual(fx.decisions()["E03-VU-002"]["start_frame_source"], "TAIL_FRAME")
            self.assertEqual(npl.own_keyframes_needed(fx.ctx), [])

    def test_unstamped_copies_the_tail_unchanged(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), LEGACY) as fx:
            with mock.patch.object(npl, "check_tail_start_frame") as check:
                rows = npl.materialise_derived_keyframes(fx.ctx)
            check.assert_not_called()
            self.assertEqual(rows[0]["status"], "MATERIALISED")
            side = json.loads(fx.kf2.with_suffix(".derived.json").read_text())
            self.assertNotIn("start_frame_source", side)
            self.assertEqual(fx.decisions(), {})
            self.assertFalse((fx.ctx.p.preprod_reports / "E03_S6_WAVE_STATE.json").exists())


class RedoSwitchTests(unittest.TestCase):
    def _failed_q2(self, fx, uid, kind="speaker_framing"):
        d = fx.ctx.p.q2_dir / uid; d.mkdir(parents=True, exist_ok=True)
        (d / "prepare.json").write_text(json.dumps({kind: {"status": "FAIL", "failure": "X"},
                                                    "media_sha256": "abc"}))

    def test_redo_parks_the_failed_start_frame_and_switches_to_own(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            kf1 = fx.ctx.p.keyframes / "E03-S01-01-keyframe-v1.png"; kf1.write_bytes(b"wide room")
            (fx.ctx.p.preprod / "prompts/keyframes/E03-S01-01-KEYFRAME-V1.txt").write_text("prompt")
            fx.kf2.write_bytes(b"tail copy"); fx.kf2.with_suffix(".derived.json").write_text("{}")
            old = time.time() - 60
            for path in (kf1, fx.kf2):
                os.utime(path, (old, old))
            self._failed_q2(fx, "E03-VU-001")
            self._failed_q2(fx, "E03-VU-002", "face_count")
            rows = npl.redo_switch_start_frames(fx.ctx)
            self.assertEqual({r["unit_id"]: r["reason"] for r in rows},
                             {"E03-VU-001": "Q2_REDO_SPEAKER_FRAMING", "E03-VU-002": "Q2_REDO_FACE_COUNT"})
            self.assertFalse(kf1.exists()); self.assertFalse(fx.kf2.exists())
            self.assertEqual(fx.decisions()["E03-VU-002"]["start_frame_source"], "OWN_KEYFRAME_TAIL_REJECTED")
            # the tail is not copied back even though it was never measured as bad
            with mock.patch.object(npl, "check_tail_start_frame") as check:
                self.assertEqual(npl.materialise_derived_keyframes(fx.ctx)[0]["status"], "OWN_KEYFRAME_REQUIRED")
            check.assert_not_called()
            self.assertEqual(npl.own_keyframes_needed(fx.ctx), ["E03-VU-001", "E03-VU-002"])
            # once regenerated (newer than the failed measurement) nothing is parked again
            kf1.write_bytes(b"new mcu"); fx.kf2.write_bytes(b"new own")
            self.assertEqual(npl.redo_switch_start_frames(fx.ctx), [])

    def test_no_switch_while_clip_on_disk_or_unstamped(self):
        for contract, clip in ((STAMPED, True), (LEGACY, False)):
            with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), contract) as fx:
                kf1 = fx.ctx.p.keyframes / "E03-S01-01-keyframe-v1.png"; kf1.write_bytes(b"x")
                old = time.time() - 60
                os.utime(kf1, (old, old))
                self._failed_q2(fx, "E03-VU-001")
                if clip:
                    (fx.ctx.p.video_media / "E03-VU-001.mp4").write_bytes(b"mp4")
                self.assertEqual(npl.redo_switch_start_frames(fx.ctx), [])
                self.assertTrue(kf1.exists())


class StageS6OwnKeyframeTests(unittest.TestCase):
    def test_s6_generates_own_keyframe_through_s5_and_surfaces_its_review(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            r5 = npl.StageResult(npl.REVIEW_REQUIRED); r5.blockers = ["S5.q1:REVIEW_REQUIRED"]
            with mock.patch.object(npl, "previs_gate", lambda *_a: {}), \
                    mock.patch.object(npl, "release_unposted_waves", lambda *_a: []), \
                    mock.patch.object(npl, "unit_dependency_order",
                                      lambda _c: [("E03-VU-001", None, False), ("E03-VU-002", "E03-VU-001", True)]), \
                    mock.patch.object(npl, "redo_switch_start_frames", lambda _c: []), \
                    mock.patch.object(npl, "materialise_derived_keyframes", lambda _c: []), \
                    mock.patch.object(npl, "own_keyframes_needed", lambda _c: ["E03-VU-002"]), \
                    mock.patch.object(npl, "stage_s5", return_value=r5) as s5:
                res = npl.stage_s6(fx.ctx)
            s5.assert_called_once()
            self.assertEqual(res.status, npl.REVIEW_REQUIRED)
            self.assertEqual(res.blockers, ["S6.own_keyframe:S5.q1:REVIEW_REQUIRED"])
            self.assertEqual(res.details["own_keyframe_units"], ["E03-VU-002"])


if __name__ == "__main__":
    unittest.main()
