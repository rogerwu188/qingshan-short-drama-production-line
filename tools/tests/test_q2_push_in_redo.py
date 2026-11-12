"""Objective Q2 push-in -> engine redo + writer line-length rules (line owner 2026-10-29, lab E08; synthetic fixtures).

1. video Q2 measures the push-in of stamped locked-camera units with S7's own rule (push_in_compensation.analyze
   over the Q2 frames' largest face): > 50 % face-width growth = ``objective_push_in`` FAIL, which fails
   ``camera_axis_stable_and_declared``;
2. q2_auto_redo redoes it once (after duplicates and speaker framing), keeps its start frame (no keyframe cost) and
   the redo prompt states the measured problem (``h3_redo_findings``), on top of the strict camera lock;
3. a spoken line estimated under 2.8 s warns (speaking_unit_duration row, writer self-check R11), never blocks.
Unstamped episodes/units are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402
import q2_auto_redo  # noqa: E402
import video_q2_builder as vq  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.h3_provider_english_contract import (  # noqa: E402
    CAMERA_LOCK_TRIPOD, REDO_FINDING_SENTENCES, redo_finding_sentences,
    validate_h3_provider_text_boundary)
from tools.speaking_unit_duration import SHORT_LINE_WARNING, speaking_duration  # noqa: E402
from tools.tests.test_h3_director_performance import unit_plan  # noqa: E402
from tools.tests.test_h3_director_prompt import vu011  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import STYLE, fixture  # noqa: E402

render = h3.render_h3_prompt
PUSH_SENTENCE = REDO_FINDING_SENTENCES["push_in"]
LOCKED = {"unit_id": "U1", "camera_plan": {"motion_family": "LOCKED"}}
MOVING = {"unit_id": "U1", "camera_plan": {"motion_family": "DOLLY"}}
PUSH = [0.40, 0.43, 0.47, 0.53, 0.60, 0.68, 0.74, 0.78, 0.80]  # +100 %, monotonic
STEADY = [0.40, 0.41, 0.40, 0.42, 0.41, 0.42, 0.43, 0.42, 0.43]


def frames(widths):
    return [{"frame_index": i + 1, "at_seconds": round(0.25 + 0.5 * i, 3), "width": w, "cx": 0.5, "cy": 0.35}
            for i, w in enumerate(widths)]


class PushInVerdictTest(unittest.TestCase):
    def test_locked_push_in_fails_with_s7_rule(self):
        result = vq.push_in_verdict(LOCKED, frames(PUSH))
        self.assertEqual((result["status"], result["analysis_status"]), ("FAIL", "COMPENSATE"))
        self.assertEqual(result["failure"], "OBJECTIVE_PUSH_IN:face_width_growth=1.00>0.50")
        self.assertEqual(result["method"], vq.PUSH_IN_METHOD)

    def test_pass_and_not_applicable(self):
        self.assertEqual(vq.push_in_verdict(LOCKED, frames(STEADY))["status"], "PASS")
        self.assertEqual(vq.push_in_verdict(MOVING, frames(PUSH))["reason"], "MOVING_CAMERA")
        self.assertEqual(vq.push_in_verdict(None, frames(PUSH))["status"], "NOT_APPLICABLE")
        cut = [0.40, 0.40, 0.41, 0.41, 0.80, 0.80, 0.81, 0.81, 0.82]  # a 95 % jump between samples = a cut
        self.assertEqual(vq.push_in_verdict(LOCKED, frames(cut))["reason"], "SKIPPED_INTERNAL_CUT")
        few = [None, None, None, None, 0.4, 0.5, 0.6, 0.7, 0.8]
        self.assertEqual(vq.push_in_verdict(LOCKED, frames(few))["reason"], "SKIPPED_FEW_FACES")
        just = [0.40, 0.42, 0.44, 0.46, 0.48, 0.52, 0.55, 0.58, 0.60]  # exactly +50 %: S7 does not compensate either
        self.assertEqual(vq.push_in_verdict(LOCKED, frames(just))["status"], "PASS")

    def test_measure_uses_the_largest_kept_face(self):
        def face(x1, x2):
            return SimpleNamespace(bbox=[x1, 100.0, x2, 300.0], det_score=0.9)
        dets = {"status": "OK", "frames": [
            {"row": {"at_seconds": 0.25 + 0.5 * i}, "frame_index": i + 1, "height": 1280, "width": 720,
             "faces": [face(10, 40), face(300, 300 + 720 * w)]} for i, w in enumerate(PUSH)]}
        result = vq.measure_push_in(LOCKED, dets)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["start_width"], 0.4)
        self.assertEqual(vq.measure_push_in(LOCKED, {"status": "NOT_MEASURED", "reason": "X"})["status"], "NOT_MEASURED")

    def test_apply_fails_camera_axis_and_keeps_reviewer_answer(self):
        checks = [{"question_id": "camera_axis_stable_and_declared", "answer": "PASS"}]
        failures: list = []
        self.assertTrue(vq.apply_push_in(vq.push_in_verdict(LOCKED, frames(PUSH)), checks, failures))
        self.assertEqual(checks[0]["answer"], "FAIL")
        self.assertEqual(checks[0]["objective_overrides"][0]["method"], vq.PUSH_IN_METHOD)
        self.assertEqual(checks[1]["question_id"], "objective_push_in")
        self.assertEqual(failures[0], "camera_axis_stable_and_declared")
        self.assertFalse(vq.apply_push_in(vq.push_in_verdict(LOCKED, frames(STEADY)), [], []))
        self.assertFalse(vq.apply_push_in(None, [], []))

    def test_prepare_measures_only_under_the_policy(self):
        source = Path(vq.__file__).read_text()
        hook = source.index('row["push_in"] = measure_push_in(unit_plan, detections, media=media if locked else None, '
                            'window=window)')
        self.assertLess(source.index("        if face_count_on:\n"), hook)
        self.assertIn("apply_push_in(push_in, scene_checks, scene_failed)", source)


def _words(start, text, step=0.3):
    out = []
    for i, word in enumerate(text.split()):
        out.append({"start": round(start + step * i, 3), "end": round(start + step * i + 0.25, 3), "word": " " + word})
    return {"start": out[0]["start"], "end": out[-1]["end"], "text": text, "words": out}


LINE = "I told you the door was locked from inside."
KEPT_CONTRACT = {"episode": "E99", "dialogue_language": "en", "shots": [{"shot_id": "S1", "target_seconds": 6.0}],
                 "audio_contract": {"dialogue_units": [{"shot_id": "S1", "speaker_id": "holmes", "text": LINE}]}}
KEPT_UNIT = {"unit_id": "U1", "editorial_shot_ids": ["S1"], "camera_plan": {"motion_family": "LOCKED"}}
#: filler "Well um so then" (0.0-1.15), the line (1.5-4.15), babble from 4.4
KEPT_ASR = [_words(0.0, "Well um so then"), _words(1.5, LINE), _words(4.4, "and the other one was")]


ENGINE_NPL = vq.engine_module("nalu_pipeline")  # the module Q2 itself calls


class PushInKeptWindowTest(unittest.TestCase):
    """Owner 2026-10-29 (lab E08 VU-006/009/015): measure only what S7's dialogue head/tail trims keep."""

    def window(self, asr=KEPT_ASR, unit=KEPT_UNIT, contract=KEPT_CONTRACT, **kw):
        with mock.patch.object(vq, "_untrimmed_unit_asr", return_value=(asr, "Q2_CACHE"), **kw) as asr_mock, \
                mock.patch.object(ENGINE_NPL, "_unit_energy_db", return_value=None), \
                mock.patch.object(vq, "sha256_file", return_value="sha"):
            return vq.push_in_window("E99", unit, Path("/nonexistent.mp4"), 6.0, contract, Path("/x.json")), asr_mock

    @unittest.skipUnless(__import__("importlib").util.find_spec("numpy"), "S7 trim planning needs numpy (media extra)")
    def test_window_is_s7_head_and_tail_trim(self):
        win, _ = self.window()
        self.assertEqual(win["source"], "S7_DIALOGUE_TRIMS")
        self.assertEqual((win["start_seconds"], win["end_seconds"]), (1.35, 4.4))
        self.assertTrue(win["head_trimmed"] and win["tail_trimmed"])
        self.assertEqual(win["clip_seconds"], 6.0)

    def test_silent_unit_is_the_whole_clip_without_asr(self):
        silent = {**KEPT_CONTRACT, "audio_contract": {"dialogue_units": []}}
        win, asr_mock = self.window(contract=silent)
        self.assertEqual((win["source"], win["start_seconds"], win["end_seconds"]), ("WHOLE_CLIP_SILENT", 0.0, 6.0))
        asr_mock.assert_not_called()

    def test_asr_failure_falls_back_to_the_whole_clip(self):
        win, _ = self.window(side_effect=RuntimeError("no whisper"))
        self.assertEqual((win["source"], win["start_seconds"], win["end_seconds"]), ("WHOLE_CLIP_FALLBACK", 0.0, 6.0))
        self.assertIn("WINDOW_ERROR:RuntimeError", win["reason"])
        win, _ = self.window(asr=[])  # nothing heard: S7 trims nothing -> whole clip, still the S7 rule
        self.assertEqual((win["start_seconds"], win["end_seconds"]), (0.0, 6.0))

    def test_measures_nine_frames_inside_the_window_only(self):
        pic = vq.engine_module("push_in_compensation")
        window = {"start_seconds": 1.35, "end_seconds": 4.4, "source": "S7_DIALOGUE_TRIMS"}
        # the face grows only before 1.35 s (in the filler): inside the kept window it is steady
        width_at = lambda t: 0.40 if t < 1.35 else 0.80  # noqa: E731
        dets = {"status": "OK", "backend": SimpleNamespace(_app=object()), "frames": []}
        with mock.patch.object(pic, "frame_at", side_effect=lambda _m, t, _f: t), \
                mock.patch.object(pic, "largest_face", side_effect=lambda _a, t: {"width": width_at(t), "cx": 0.5,
                                                                                  "cy": 0.4}), \
                mock.patch.object(vq, "require_ffmpeg", return_value="ffmpeg"):
            result = vq.measure_push_in(LOCKED, dets, media=Path("/u.mp4"), window=window)
            whole = vq.measure_push_in(LOCKED, dets, media=Path("/u.mp4"),
                                       window={"start_seconds": 0.0, "end_seconds": 4.4})
        times = [row["at_seconds"] for row in result["per_frame"]]
        self.assertEqual(len(times), 9)
        self.assertTrue(all(1.35 <= t <= 4.4 for t in times))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["window"], window)
        self.assertNotEqual(whole["status"], "PASS")  # the whole clip would have seen the filler-time jump

    def test_asr_source_order(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            media = d / "E99-VU-001.mp4"
            media.write_bytes(b"x")
            cache = d / "cache.json"
            s7 = d / "assembly" / "E99_unit_asr_untrimmed.json"
            s7.parent.mkdir()
            s7.write_text(json.dumps({"E99-VU-001": KEPT_ASR}))
            paths = SimpleNamespace(assembly=s7.parent)
            with mock.patch.object(vq, "QaPaths", return_value=paths), \
                    mock.patch.object(vq.engine_module("nalu_pipeline"), "transcribe_clip",
                                      return_value=[{"start": 0, "end": 1, "text": "x", "words": []}]) as whisper, \
                    mock.patch.object(vq, "_whisper_model", return_value="model"):
                segs, src = vq._untrimmed_unit_asr("E99", "E99-VU-001", media, "sha1", "en", cache)
                self.assertEqual((src, segs), ("S7_UNTRIMMED_ASR", KEPT_ASR))
                self.assertEqual(vq._untrimmed_unit_asr("E99", "E99-VU-001", media, "sha1", "en", cache)[1],
                                 "Q2_CACHE")
                # a redone clip (new sha, newer than S7's ASR) -> S7's whisper pass on the clip
                import os
                os.utime(s7, (1, 1))
                segs, src = vq._untrimmed_unit_asr("E99", "E99-VU-001", media, "sha2", "en", cache)
                self.assertEqual(src, "S7_WHISPER_PASS")
                whisper.assert_called_once_with("model", media, "en", words=True)
                self.assertEqual(json.loads(cache.read_text())["media_sha256"], "sha2")


class AutoRedoTest(unittest.TestCase):
    ROWS = {"U1": {"push_in": {"status": "FAIL"}}, "U2": {"speaker_framing": {"status": "FAIL"}},
            "U3": {"face_count": {"status": "FAIL"}, "push_in": {"status": "FAIL"}}, "U4": {"push_in": {"status": "PASS"}}}

    def test_priority_after_duplicates_and_speaker_framing(self):
        plan = q2_auto_redo.plan(self.ROWS, {}, headroom=1000, unit_cost=lambda _u: 10,
                                 unit_order=["U1", "U2", "U3", "U4"])
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U3", "U2", "U1"])
        self.assertEqual(plan["selected"][0]["failures"], ["face_count", "push_in"])

    def test_keyframe_and_prompt_findings(self):
        self.assertFalse(q2_auto_redo.needs_own_keyframe(["push_in"]))
        self.assertTrue(q2_auto_redo.needs_own_keyframe(["speaker_framing", "push_in"]))
        state = {"q2_auto_redo": {"U1": {"failures": ["push_in"]}, "U2": {"failures": ["face_count"]}}}
        self.assertEqual(q2_auto_redo.redo_findings(state, "U1"), ["push_in"])
        self.assertEqual(q2_auto_redo.redo_findings(state, "U2"), [])
        self.assertEqual(q2_auto_redo.redo_findings({}, "U1"), [])

    def test_pipeline_costs_a_push_in_redo_as_video_only(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            preprod = tmp / "pre"; (preprod / "reports").mkdir(parents=True); (tmp / "video").mkdir()
            (tmp / "contract.json").write_text(json.dumps({"episode": "E08", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}))
            (preprod / "E08_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(
                {"units": [{"unit_id": "E08-VU-002"}, {"unit_id": "E08-VU-017"}]}))
            (tmp / "tx.json").write_text(json.dumps({"tasks": [{"unit_id": "E08-VU-002", "duration_seconds": 4},
                                                               {"unit_id": "E08-VU-017", "duration_seconds": 5}]}))
            q2_dir = preprod / "reports" / "qa" / "q2"
            for uid, row in (("E08-VU-002", {"push_in": {"status": "FAIL"}, "media_sha256": "a"}),
                             ("E08-VU-017", {"speaker_framing": {"status": "FAIL"}, "push_in": {"status": "FAIL"}})):
                (q2_dir / uid).mkdir(parents=True); (q2_dir / uid / "prepare.json").write_text(json.dumps(row))
                (tmp / "video" / f"{uid}.mp4").write_bytes(b"mp4")
            ctx = SimpleNamespace(
                episode="E08", dry=False, run_id="R1", say=lambda *_a, **_k: None,
                budget_check=lambda planned, label: {"budget_verdict": {"headroom_credits": 500}},
                p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", contract=tmp / "contract.json",
                                  video_media=tmp / "video", q2_dir=q2_dir, video_transaction=tmp / "tx.json"))
            with mock.patch.object(npl, "episode_video_model", lambda _e: "MiniMax-H3"), \
                    mock.patch.object(npl, "episode_video_resolution", lambda _e: "480p"), \
                    mock.patch.object(npl, "video_task_credits", lambda _m, s, _t, _r: int(s * 2)):
                result = npl.s6_q2_auto_redo(ctx)
            costs = {r["unit_id"]: r["cost"] for r in result["selected"]}
            self.assertEqual(costs, {"E08-VU-017": 10 + q2_auto_redo.OWN_KEYFRAME_CREDITS, "E08-VU-002": 8})
            self.assertEqual([r["unit_id"] for r in result["selected"]], ["E08-VU-017", "E08-VU-002"])
            state = json.loads((preprod / "reports" / "E08_S6_WAVE_STATE.json").read_text())
            self.assertEqual(state["q2_auto_redo"]["E08-VU-002"]["failures"], ["push_in"])
            import build_nalu_preproduction as bnp
            self.assertEqual(bnp.q2_redo_prompt_findings(preprod, "E08", {"camera_grammar_policy": "CAMERA_GRAMMAR_V1"}),
                             {"E08-VU-002": ["push_in"], "E08-VU-017": ["push_in"]})
            self.assertEqual(bnp.q2_redo_prompt_findings(preprod, "E08", {"camera_grammar_policy": "LEGACY_FORCED_MOTION"}), {})

    def test_push_in_redo_keeps_its_start_frame(self):
        self.assertNotIn("push_in", npl.REDO_START_FRAME_FAILURES)


class RedoPromptTest(unittest.TestCase):
    def test_v2_states_the_problem_once_after_the_strict_lock(self):
        base, _ = render(*fixture())
        unit, plan = fixture()
        unit["h3_redo_findings"] = ["push_in"]
        text, _ = render(unit, plan)
        camera = text.split("Camera:\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(camera.endswith(CAMERA_LOCK_TRIPOD + "\n" + PUSH_SENTENCE), camera)
        self.assertEqual(text.count(PUSH_SENTENCE), 1)
        self.assertEqual(text.replace("\n" + PUSH_SENTENCE, "", 1), base)
        self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")

    def test_v1_stamped_locked_gets_the_clause(self):
        base, _ = render(*unit_plan(stamped=True, performance=None))
        unit, plan = unit_plan(stamped=True, performance=None)
        unit["h3_redo_findings"] = ["push_in"]
        text, _ = render(unit, plan)
        clause = "; " + PUSH_SENTENCE[0].lower() + PUSH_SENTENCE[1:].rstrip(".")
        self.assertIn(clause, text)
        self.assertEqual(text.replace(clause, "", 1), base)
        self.assertEqual(h3.locked_camera_move_conflicts(text), [])

    def test_unstamped_and_moving_ignore_the_field(self):
        for make in (lambda: fixture(style=True, director=False), lambda: unit_plan(stamped=False, performance=None),
                     lambda: vu011(stamped=True)):
            base, _ = render(*make())
            unit, plan = make()
            unit["h3_redo_findings"] = ["push_in"]
            self.assertEqual(hashlib.sha256(render(unit, plan)[0].encode()).digest(),
                             hashlib.sha256(base.encode()).digest())

    def test_field_parsing_and_transport(self):
        self.assertEqual(redo_finding_sentences({"h3_redo_findings": ["push_in", "PUSH_IN", "other"]}), [PUSH_SENTENCE])
        self.assertEqual(redo_finding_sentences({}), [])
        from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit
        with mock.patch("tools.submit_giggle_video_manifest_v2.grouped_sequence_unit", lambda _t: {}):
            self.assertEqual(provider_prompt_unit({"h3_redo_findings": ["push_in"]}).get("h3_redo_findings"), ["push_in"])
            self.assertNotIn("h3_redo_findings", provider_prompt_unit({}))
        self.assertIn('task["h3_redo_findings"] = list(redo_findings[uid])',
                      (TOOLS / "build_nalu_preproduction.py").read_text())


class ShortLineWarningTest(unittest.TestCase):
    def test_speaking_duration_warns_under_2_8_s(self):
        short = speaking_duration(4, ["A: Which of you is Holmes?"], "en")  # ~2.0 s
        self.assertEqual((short["action"], short["advisory"]), ("UNCHANGED", SHORT_LINE_WARNING))
        full = speaking_duration(4, ["A: I have been watching this house since the early morning."], "en")
        self.assertNotIn("advisory", full)
        self.assertNotIn("advisory", speaking_duration(4, ["甲：我从今天清早起就一直守在这座房子外面。"], "zh"))
        self.assertEqual(speaking_duration(4, ["甲：你好。"], "zh")["advisory"], SHORT_LINE_WARNING)

    def test_bnp_reports_an_unchanged_short_line(self):
        import build_nalu_preproduction as bnp
        shot = {"shot_id": "S1", "target_seconds": 4, "prompt_spec": {
            "dialogue": "Holmes: Which of you is Holmes?",
            "role_semantic_disambiguation": {"lip_owner_id": "CHAR-H", "dialogue_speaker_id": "CHAR-H"},
            "cast": [{"character_id": "CHAR-H"}]}}
        report: list = []
        self.assertEqual(bnp._speaking_shot_duration(shot, None, "en", 4.0, report), 4.0)
        self.assertEqual((report[0]["action"], report[0]["advisory"]), ("UNCHANGED", SHORT_LINE_WARNING))

    def test_writer_selfcheck_r11_warns_on_stamped_only(self):
        import nalu_writer_selfcheck_seq29 as wsc
        contract = {"episode": "E09", "camera_grammar_policy": "CAMERA_GRAMMAR_V1", "dialogue_language": "en",
                    "shots": [{"shot_id": "S1", "target_seconds": 4, "prompt_spec": {"dialogue": "A: Yes, sir."}},
                              {"shot_id": "S2", "target_seconds": 4, "prompt_spec": {
                                  "dialogue": "A: I have been watching this house since the early morning."}}]}
        self.assertEqual([r["shot_id"] for r in wsc.short_speaking_line_warnings(contract)], ["S1"])
        report = wsc.evaluate(contract)
        # owner 2026-11-02: advisory only (keep the short line; S7 cuts to the performance)
        self.assertTrue(any(w.startswith("R11_SHORT_LINE_OK_S7_CUTS:S1:") for w in report["advisories"]))
        self.assertFalse(any(w.startswith("R11") for w in report["warnings"]))
        self.assertFalse(any(f.startswith("R11") for f in report["failures"]))
        legacy = {**contract, "camera_grammar_policy": "LEGACY_FORCED_MOTION"}
        self.assertEqual(wsc.short_speaking_line_warnings(legacy), [])
        self.assertFalse(any(w.startswith("R11") for w in wsc.evaluate(legacy)["warnings"]))


if __name__ == "__main__":
    unittest.main()
