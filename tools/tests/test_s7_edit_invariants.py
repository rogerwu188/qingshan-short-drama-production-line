#!/usr/bin/env python3
"""S7 hard edit invariants (owner 2026-11-21, device 1101 E21: "characters are often cut off before finishing their
line; there are even shots of 1-2 seconds where the character doesn't say anything before it cuts away; cuts
between shots are far too fast").  Offline, synthetic timelines only."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(ROOT), str(ROOT / "tools"), str(NALU_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dialogue_tail_guard as tg  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as gmp  # noqa: E402
import gemini_video_review as gvr  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
import performance_cut as pc  # noqa: E402
import s7_edit_invariants as inv  # noqa: E402
import unit_recut  # noqa: E402


def line(start: float, text: str, step: float = 0.2) -> dict:
    """One ASR segment with one word per character (zh), ``step`` s per character."""
    words = [{"start": round(start + step * i, 3), "end": round(start + step * (i + 1), 3), "word": ch}
             for i, ch in enumerate(text)]
    return {"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words}


def seg(vu, vi, vo, au=None, ai=None, ao=None, **kw):
    return {"video": [vu, vi, vo], "audio": [au or vu, vi if ai is None else ai, vo if ao is None else ao], **kw}


class CutPointTests(unittest.TestCase):
    WORDS = inv.speech_words([line(0.5, "我从今天清早起"), line(2.6, "就一直守在这里")])   # 0.5-1.9, 2.6-4.0

    def test_no_cut_inside_a_word_or_a_line_tail(self):
        self.assertIsNotNone(inv.cut_violation(1.0, self.WORDS))                    # mid-word
        self.assertTrue(inv.cut_violation(1.05, self.WORDS)["mid_word"])
        self.assertIsNotNone(inv.cut_violation(2.1, self.WORDS))                    # 0.2 s after the line: too soon
        self.assertIsNone(inv.cut_violation(1.9 + inv.SENTENCE_TAIL_SECONDS, self.WORDS))
        self.assertIsNotNone(inv.cut_violation(2.55, self.WORDS))                   # starts the next shot mid-lead
        self.assertIsNone(inv.cut_violation(0.3, self.WORDS))

    def test_safe_intervals_and_snap_land_on_the_line_boundary(self):
        safe = inv.safe_intervals(self.WORDS, 0.0, 6.0)
        self.assertEqual(safe, [(0.0, 0.4), (2.3, 2.5), (4.4, 6.0)])
        self.assertEqual(inv.snap(1.5, self.WORDS, 0.0, 6.0), 2.3)
        self.assertIsNone(inv.snap(1.0, self.WORDS, 0.0, 6.0, max_shift=0.3))

    def test_tail_guard_keeps_0_4_s_after_a_line_unless_speech_follows(self):
        self.assertAlmostEqual(tg.tail_cut(2.0, 6.0, beat=0.0)["cut"], 2.0 + tg.SENTENCE_END_GUARD_SECONDS)
        self.assertAlmostEqual(tg.tail_cut(2.0, 6.0, beat=0.3)["cut"], 2.4)          # the reaction beat is not less
        # babble right after: never below the plain guard, never into the babble beyond it
        self.assertAlmostEqual(tg.tail_cut(2.0, 6.0, beat=0.5, next_speech_start=2.05)["cut"],
                               2.0 + tg.TAIL_GUARD_SECONDS)
        self.assertAlmostEqual(tg.tail_cut(2.0, 6.0, beat=0.5, next_speech_start=2.4)["cut"], 2.35)

    def test_speaking_unit_never_cut_before_word_end_plus_tail(self):
        c = {"dialogue_language": "zh", "audio_contract": {"dialogue_units": [
            {"shot_id": "S1", "speaker_id": "A", "text": "我从今天清早起就一直守在这里。"}]}}
        g = {"units": [{"unit_id": "U", "editorial_shot_ids": ["S1"]}]}
        text = "我从今天清早起就一直守在这里"
        words = line(0.5, text)["words"] + line(3.45, "还有一件事")["words"]
        rep = pc.plan(c, g, {"U": [{"start": 0.5, "end": 4.45, "text": text + "还有一件事", "words": words}]},
                      {"U": 6.0})
        r = rep["units"][0]
        self.assertGreaterEqual(r["after_out"], r["line_end_seconds"] + tg.TAIL_GUARD_SECONDS - 1e-6)
        self.assertLessEqual(r["after_in"], 0.5)


class RecutSanitizerTests(unittest.TestCase):
    CLIPS = {"A": 8.0, "B": 6.0}

    def test_visible_cut_inside_speech_moves_to_the_line_boundary(self):
        words = {"A": inv.speech_words([line(0.4, "我从今天清早起"), line(2.6, "就一直守在这里")])}
        segs = [seg("A", 0.0, 1.2), seg("A", 1.2, 5.0, reframe=[0.1, 0.1, 0.8, 0.8])]   # cut at 1.2: mid-word
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, min_s=1.2)
        cut = got["segments"][0]["audio"][2]
        self.assertIsNone(inv.cut_violation(cut, words["A"]), cut)
        self.assertEqual(got["actions"][0]["action"], "MOVE_CUT_TO_LINE_BOUNDARY")
        # the sound is one continuous run: nothing heard moves
        self.assertEqual([got["segments"][0]["audio"][1], got["segments"][-1]["audio"][2]], [0.0, 5.0])
        self.assertEqual(unit_recut.validate_segments("A", got["segments"]), [])

    def test_fragment_cutaway_is_merged_into_the_speaker_picture(self):
        # a 0.6 s flash between two lines (both cuts are clean): merged by the minimum-shot rule
        words = {"A": inv.speech_words([line(0.4, "我从今天"), line(3.2, "就一直守")]), "B": []}
        segs = [seg("A", 0.0, 2.0), seg("B", 3.0, 3.6, "A", 2.0, 2.6), seg("A", 2.6, 5.0)]
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, min_s=1.2)
        self.assertEqual(len(inv.visible_shots(got["segments"])), 1, got)
        self.assertTrue(all(s["video"][0] == "A" for s in got["segments"]))
        self.assertEqual([a["action"] for a in got["actions"]], ["MERGE_FRAGMENT"])
        self.assertEqual([s["audio"] for s in got["segments"]], [s["audio"] for s in segs])   # sound untouched
        # the same flash over the middle of a line: its cut is inside speech -> merged as well
        words = {"A": inv.speech_words([line(0.4, "我从今天清早起就一直守在这里")]), "B": []}
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, min_s=1.2)
        self.assertEqual(len(inv.visible_shots(got["segments"])), 1, got)
        self.assertTrue(all(a["action"].startswith("MERGE_") for a in got["actions"]))

    def test_speaker_on_screen_who_does_not_speak_is_merged(self):
        # B is a SPEAKING unit: 1.3 s of its unused frames over A's line shows a speaker who says nothing
        words = {"A": inv.speech_words([line(0.4, "我从今天"), line(3.6, "就一直守")]),
                 "B": inv.speech_words([line(0.2, "你说什么")])}
        segs = [seg("A", 0.0, 1.8), seg("B", 4.0, 5.3, "A", 1.8, 3.1), seg("A", 3.1, 5.0)]
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, speaking_units={"A", "B"},
                                 min_s=1.2)
        self.assertTrue(any(a["action"] == "MERGE_SPEAKER_NOT_SPEAKING" for a in got["actions"]), got)
        self.assertNotIn("B", {s["video"][0] for s in got["segments"]})
        # a silent listener's 1.6 s reaction is a motivated reaction and stays
        segs = [seg("A", 0.0, 1.8), seg("B", 4.0, 5.6, "A", 1.8, 3.4), seg("A", 3.4, 5.0)]
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, speaking_units={"A"},
                                 min_s=1.2)
        self.assertIn("B", {s["video"][0] for s in got["segments"]})

    def test_authored_sound_cut_inside_a_word_is_extended(self):
        words = {"A": inv.speech_words([line(0.4, "我从今天清早起")])}   # ends 1.8
        segs = [seg("A", 0.0, 1.7), seg("A", 4.0, 6.0)]                 # dropped middle; sound cut mid-word
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, min_s=1.2)
        self.assertGreaterEqual(got["segments"][0]["audio"][2], 1.8 + inv.SENTENCE_TAIL_SECONDS - 1e-6)
        self.assertEqual(got["actions"][0]["action"], "EXTEND_SOUND_CUT_TO_WORD_END")

    def test_clean_plan_is_unchanged(self):
        words = {"A": inv.speech_words([line(0.4, "我从今天")]), "B": []}
        segs = [seg("A", 0.0, 2.0), seg("B", 1.0, 3.0, "A", 2.0, 4.0), seg("A", 4.0, 6.0)]
        got = inv.sanitize_recut("A", segs, words_by_unit=words, clip_seconds=self.CLIPS, min_s=1.2)
        self.assertFalse(got["changed"])
        self.assertEqual(got["actions"], [])


class StaticShotSplitTests(unittest.TestCase):
    SPEECH = [line(0.5, "我从今天清早起"), line(3.6, "就一直守在这里")]   # 0.5-1.9, 3.6-5.0

    def test_punch_in_splits_at_a_line_boundary_with_both_pieces_speaking(self):
        got = ffr.static_shot_segments("A", (0.0, 6.5), neighbours=[], speech=self.SPEECH, speaking=True)
        self.assertEqual(got["method"], "PUNCH_IN")
        m = got["cuts"][0]
        self.assertIsNone(inv.cut_violation(m, inv.speech_words(self.SPEECH)))
        self.assertTrue(1.9 + inv.SENTENCE_TAIL_SECONDS - 1e-6 <= m <= 3.6 - inv.HEAD_LEAD_SECONDS + 1e-6)
        self.assertEqual(unit_recut.validate_segments("A", got["segments"]), [])

    def test_speaking_neighbour_is_never_a_cutaway_and_silent_neighbour_speech_is_skipped(self):
        speaking_nb = {"unit_id": "B", "unused": [(0.0, 3.0)], "speaking": True}
        got = ffr.static_shot_segments("A", (0.0, 6.5), neighbours=[speaking_nb], speech=self.SPEECH, speaking=True)
        self.assertEqual(got["method"], "PUNCH_IN")
        busy_nb = {"unit_id": "C", "unused": [(0.0, 2.0)], "speech": [line(0.3, "嗯嗯嗯嗯嗯")]}
        got = ffr.static_shot_segments("A", (0.0, 6.5), neighbours=[busy_nb], speech=self.SPEECH, speaking=True)
        self.assertEqual(got["method"], "PUNCH_IN")                    # its only free frames hold speech
        quiet_nb = {"unit_id": "D", "unused": [(4.0, 6.0)], "speaking": False}
        # 6.5 s: no 1.5-2 s cutaway fits between line boundaries with both own pieces >= the minimum -> punch-in
        got = ffr.static_shot_segments("A", (0.0, 6.5), neighbours=[quiet_nb], speech=self.SPEECH, speaking=True)
        self.assertEqual(got["method"], "PUNCH_IN")
        got = ffr.static_shot_segments("A", (0.0, 7.5), neighbours=[quiet_nb], speech=self.SPEECH, speaking=True)
        self.assertEqual((got["method"], got["borrowed_from"]), ("CUTAWAY", "D"))
        words = inv.speech_words(self.SPEECH)
        for c in got["cuts"]:
            self.assertIsNone(inv.cut_violation(c, words), c)
        lengths = [s["video"][2] - s["video"][1] for s in got["segments"]]
        self.assertTrue(all(x >= inv.MIN_SHOT_SECONDS - 1e-6 for x in lengths), lengths)
        self.assertGreaterEqual(lengths[1], ffr.CUTAWAY_MIN_SECONDS - 1e-6)

    def test_no_line_boundary_means_no_split(self):
        one_long_line = [line(0.2, "我" * 30)]                            # speech from 0.2 to 6.2
        got = ffr.static_shot_segments("A", (0.0, 6.5), neighbours=[], speech=one_long_line, speaking=True)
        self.assertEqual(got["status"], "NO_LINE_BOUNDARY_SPLIT")

    def test_never_produces_pieces_under_the_minimum(self):
        got = ffr.static_shot_segments("A", (0.0, 4.2), neighbours=[{"unit_id": "B", "unused": [(0.0, 2.0)]}],
                                       speech=[], speaking=False, min_seconds=1.5)
        lengths = [s["video"][2] - s["video"][1] for s in got["segments"]]
        self.assertTrue(all(x >= 1.5 - 1e-6 for x in lengths), lengths)


class PacingFloorTests(unittest.TestCase):
    def episode(self):
        units = [("U1", ["S1"]), ("U2", ["S2"]), ("U3", ["S3"]), ("U4", ["S4"]), ("U5", ["S5"])]
        lines = {"S1": "走", "S2": "站住", "S4": "滚"}
        shots = [{"shot_id": "S1"}, {"shot_id": "S2", "prompt_spec": {"beat_role": "PAYOFF"}},
                 {"shot_id": "S3", "target_seconds": 1.5}, {"shot_id": "S4"}, {"shot_id": "S5"}]
        contract = {"dialogue_language": "zh", "shots": shots, "audio_contract": {"dialogue_units": [
            {"shot_id": s, "speaker_id": "A", "text": t} for s, t in lines.items()]}}
        grouping = {"units": [{"unit_id": u, "editorial_shot_ids": s} for u, s in units]}
        asr = {u: [line(0.5, lines[s[0]])] for u, s in units if s[0] in lines}
        return contract, grouping, pc.plan(contract, grouping, asr, {u: 4.458 for u, _ in units})

    def test_trims_under_the_floor_are_skipped_while_the_median_is_below_it(self):
        contract, grouping, report = self.episode()
        out = pc.apply_peak_windows(report, contract, grouping, {}, runtime_floor_seconds=0.0)
        kept = [r["after_out"] - r["after_in"] for r in report["units"]]
        self.assertIn("skipped_median_floor", out)
        # the 1.5 s reaction after the payoff would sit under the 2.0 s floor while the median is under it
        self.assertEqual(out["skipped_median_floor"]["units"], ["U3"])
        self.assertLess(inv.median(kept), inv.MEDIAN_FLOOR_SECONDS)
        self.assertEqual(kept[2], 4.458)
        with mock.patch.dict(os.environ, {inv.MEDIAN_FLOOR_ENV: "0"}):
            contract, grouping, report = self.episode()
            out = pc.apply_peak_windows(report, contract, grouping, {}, runtime_floor_seconds=0.0)
            self.assertNotIn("skipped_median_floor", out)
            self.assertEqual([u["unit_id"] for u in out["units"]], ["U3"])

    def test_min_shot_env_raises_the_unit_hold(self):
        with mock.patch.dict(os.environ, {inv.MIN_SHOT_ENV: "1.5"}):
            self.assertEqual(pc.min_keep_seconds(), 1.5)
            self.assertEqual(inv.reaction_min_seconds(), 1.5)
        with mock.patch.dict(os.environ, {inv.MIN_SHOT_ENV: "9"}):
            self.assertEqual(inv.min_shot_seconds(), 3.0)


class MeasurementTests(unittest.TestCase):
    SHOTS = [{"start_seconds": 0.0, "end_seconds": 3.0}, {"start_seconds": 3.0, "end_seconds": 3.7},
             {"start_seconds": 3.7, "end_seconds": 5.0}, {"start_seconds": 5.0, "end_seconds": 9.0},
             {"start_seconds": 9.0, "end_seconds": 12.0}]
    LINES = [{"start": 0.4, "end": 2.92, "unit_id": "U1"}, {"start": 5.2, "end": 7.0, "unit_id": "U3"},
             {"start": 8.5, "end": 9.6, "unit_id": "U3"}, {"start": 10.0, "end": 11.0, "presence": "VOICE_OVER"}]
    TIMELINE = {"content_runtime_seconds": 12.0, "segments": [
        {"unit_id": "U1", "output_start": 0.0, "output_end": 3.0},
        {"unit_id": "U2", "output_start": 3.0, "output_end": 5.0},
        {"unit_id": "U3", "output_start": 5.0, "output_end": 12.0}]}

    def test_flags(self):
        got = inv.measure_cut(shots=self.SHOTS, lines=self.LINES, unit_windows=self.TIMELINE["segments"],
                              speaking_units={"U1", "U2", "U3"}, s7_cuts=[3.0, 5.0])
        self.assertEqual([(r["start"], r["s7_cut"]) for r in got["fragments"]], [(3.0, True)])
        self.assertEqual([r["start"] for r in got["speaker_not_speaking"]], [3.0, 3.7])  # U2 says nothing
        self.assertEqual([(r["next_cut"], r["gap_seconds"], r["s7_cut"]) for r in got["tail_gaps"]],
                         [(3.0, 0.08, True)])
        self.assertEqual([(r["at"], r["s7_cut"]) for r in got["mid_line_cuts"]], [(9.0, False)])  # in H3's own take
        self.assertEqual(got["counts"], {"fragments": 1, "speaker_not_speaking": 2, "tail_gaps": 1,
                                         "mid_line_cuts": 1, "s7_attributable": 4})
        self.assertEqual(got["pacing"]["median_shot_seconds"], 3.0)

    def test_checklist_measurement_record_and_fix_round(self):
        recut = {"units": {"U3": {"status": "APPLIED", "internal_cuts_s": [4.0]}}}
        got = qa.measure_s7_edit(self.LINES, self.SHOTS, self.TIMELINE, {"units": [
            {"unit_id": "U1", "kind": "SPEAKING"}, {"unit_id": "U2", "kind": "SPEAKING"},
            {"unit_id": "U3", "kind": "SPEAKING"}]}, recut)
        self.assertEqual([r["s7_cut"] for r in got["mid_line_cuts"]], [True])     # 5.0 + 4.0: a re-cut cut
        record = qa.build_record(qa.parse_block({}), {"s7_edit": got}, episode="E21")
        self.assertIn("s7_edit_measure", record)
        self.assertEqual(record["items"]["QA-EDIT-FRAGMENT"]["status"], "MEASURED_FLAG_UNREVIEWED")
        found = ffr.collect_findings({}, record)
        edit = [f for f in found if f["source"] == ffr.EDIT_SOURCE]
        self.assertEqual({f["kind_hint"] for f in edit}, {"EDIT_FRAGMENT", "DIALOGUE_TAIL_GUARD"})
        mapped = ffr.dedupe(ffr.map_findings(found, [{"unit_id": r["unit_id"], "output_start": r["output_start"],
                                                       "output_end": r["output_end"]}
                                                      for r in self.TIMELINE["segments"]]))
        self.assertTrue(all(f["class"] == ffr.FREE for f in mapped))
        self.assertTrue(ffr.triggered(False, mapped))                               # S7's own cuts: a trigger
        self.assertTrue(ffr.needs_round(False, mapped))
        h3_only = [dict(f, s7_cut=False) for f in mapped]
        self.assertFalse(ffr.triggered(False, h3_only))                             # the model's own take: recorded
        settings = ffr.free_settings({f["kind"] for f in mapped}, {})
        self.assertEqual(settings["env"]["NALU_S7_MIN_SHOT_SECONDS"], "1.5")
        self.assertEqual(settings["env"]["NALU_S7_MEDIAN_SHOT_FLOOR_SECONDS"], "2.5")

    def test_reviewer_wording_routes_to_the_free_re_edit(self):
        self.assertEqual(ffr.classify(None, "镜头切得太快，角色还没说话就切走了"), "EDIT_FRAGMENT")
        self.assertEqual(ffr.classify("QA-EDIT-FRAGMENT", ""), "EDIT_FRAGMENT")
        self.assertEqual(ffr.classify(None, "last syllable clipped at the cut"), "DIALOGUE_TAIL_GUARD")

    def test_gemini_suspects(self):
        got = inv.measure_cut(shots=self.SHOTS, lines=self.LINES, unit_windows=self.TIMELINE["segments"],
                              speaking_units={"U1", "U2", "U3"}, s7_cuts=[3.0, 5.0])
        prompt, suspects = gvr.build_prompt(duration=12.0, pack_summary={}, measurements={"s7_edit": got})
        self.assertIn("QA-EDIT-FRAGMENT", prompt)
        self.assertTrue(suspects["fragment"] and suspects["tail"])
        ids = [r["id"] for rows in suspects.values() for r in rows]
        self.assertEqual(len(ids), len(set(ids)))
        per_pass = gmp.split_suspects(suspects)
        self.assertEqual(per_pass["D"]["fragment"], suspects["fragment"])
        self.assertEqual(per_pass["C"]["tail"], suspects["tail"])
        self.assertIn("QA-EDIT-FRAGMENT", gmp.CLASSES)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("nalu_pipeline_s7_inv", NALU_TOOLS / "nalu_pipeline.py")
        cls.P = importlib.util.module_from_spec(spec)
        sys.modules["nalu_pipeline_s7_inv"] = cls.P
        spec.loader.exec_module(cls.P)

    def ctx(self, tmp: Path):
        p = SimpleNamespace(assembly=tmp / "assembly", video_media=tmp / "video", contract=tmp / "contract.json",
                            grouping_plan=tmp / "grouping.json")
        p.assembly.mkdir()
        p.video_media.mkdir()
        return SimpleNamespace(episode="E21", p=p, say=lambda *_a, **_k: None)

    def test_recut_plan_is_sanitized_beside_the_authored_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.ctx(Path(tmp))
            for uid in ("E21-VU-001", "E21-VU-002"):
                (ctx.p.video_media / f"{uid}.mp4").write_bytes(b"x")
            plan = ctx.p.assembly / "E21_UNIT_RECUT_PLAN.json"
            authored = {"schema": unit_recut.PLAN_SCHEMA, "episode": "E21", "units": {"E21-VU-001": {"segments": [
                seg("E21-VU-001", 0.0, 2.0), seg("E21-VU-002", 3.0, 3.6, "E21-VU-001", 2.0, 2.6),
                seg("E21-VU-001", 2.6, 5.0)]}}}
            plan.write_text(json.dumps(authored))
            asr = {"E21-VU-001": [line(0.4, "我从今天清早起就一直守在这里")]}
            (ctx.p.assembly / "E21_unit_asr_untrimmed.json").write_text(json.dumps(asr))
            (ctx.p.assembly / "E21_PERFORMANCE_CUT.json").write_text(json.dumps({"units": [
                {"unit_id": "E21-VU-001", "kind": "SPEAKING"}, {"unit_id": "E21-VU-002", "kind": "SILENT"}]}))
            res = SimpleNamespace(details={"dialogue_tail_trim": {"report": "x"}})
            with mock.patch.object(self.P, "_probe_seconds", return_value=8.0):
                out, summary = self.P.s7_recut_plan_invariants(ctx, res, plan)
            self.assertEqual(summary["status"], "APPLIED")
            self.assertNotEqual(out, plan)
            self.assertEqual(json.loads(plan.read_text()), authored)               # the authored plan is untouched
            segs = json.loads(out.read_text())["units"]["E21-VU-001"]["segments"]
            self.assertEqual(len(inv.visible_shots(segs)), 1)

    def test_static_recut_passes_speech_and_speaking(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.ctx(Path(tmp))
            (ctx.p.assembly / "E21_unit_asr.json").write_text(json.dumps(
                {"U1": [line(0.5, "我从今天清早起"), line(3.6, "就一直守在这里")], "U2": [line(0.2, "你说什么")]}))
            (ctx.p.assembly / "E21_PERFORMANCE_CUT.json").write_text(json.dumps({"units": [
                {"unit_id": "U1", "kind": "SPEAKING"}, {"unit_id": "U2", "kind": "SPEAKING"}]}))
            (ctx.p.video_media / "U2.mp4").write_bytes(b"x")
            windows = {"U1": {"in": 0.0, "duration": 6.5, "start": 0.0}, "U2": {"in": 0.0, "duration": 2.0, "start": 6.5}}
            with mock.patch.object(self.P, "_final_fix_cut_windows", return_value=windows), \
                    mock.patch.object(self.P, "_probe_seconds", return_value=6.0):
                actions = self.P.final_fix_static_recut(ctx, ["U1"], ["U1", "U2"])
            self.assertEqual(actions[0]["method"], "PUNCH_IN")                      # U2 speaks: no cutaway from it
            plan = json.loads((ctx.p.assembly / "E21_UNIT_RECUT_PLAN.json").read_text())
            cut = plan["units"]["U1"]["segments"][0]["video"][2]
            self.assertIsNone(inv.cut_violation(cut, inv.speech_words([line(0.5, "我从今天清早起"),
                                                                        line(3.6, "就一直守在这里")])))

    def test_measured_edit_tail_is_never_shorter_than_the_sentence_tail(self):
        src = (NALU_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('max(float(params.get("trail_seconds", 0.12)), _s7_inv.SENTENCE_TAIL_SECONDS)', src)
        self.assertIn("plan, invariants = s7_recut_plan_invariants(ctx, res, plan)", src)


if __name__ == "__main__":
    unittest.main()
