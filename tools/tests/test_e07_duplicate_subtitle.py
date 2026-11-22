"""JA-01 E07 on device 1485 (engine 496bb8f, 2026-11-22): the same line twice on screen at 0:13 (E07-VU-004).

H3 burned 「言わないでくださいまし！」 into VU-004; the S6 burn retries ran 2 rounds and stayed UNRESOLVED with the residual
band y 0.8431-0.9095; S7 (--avoid-bands, PR #294) drew OUR caption of the same line just above it; the final review
flagged only another burn (93-94.2 s) and the final fix round (DONE, 18.45 credits) did not redo VU-004.

Covers: the fuzzy cue / OCR match; S6 records what the burned line says; S7 suppresses our cue when the burned line IS
the cue (free) and keeps avoid-bands otherwise; the round gets the S6 rows even without the must-check list (wave-state
fallback), an in-band stacking row is P1 and a trigger, a suppressed one P2; the post-S7 OCR of the final cut finds two
stacked near-identical caption rows -> QA-BURNED-TEXT finding (and trigger).  Offline, no paid call."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import subtitle_text_match as stm  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import final_fix_round as ffr  # noqa: E402

LINE = "言わないでくださいまし！"
SEGMENTS = [{"unit_id": f"E07-VU-{i:03d}", "output_start": (i - 1) * 4.0, "output_end": i * 4.0} for i in range(1, 36)]


class MatchTest(unittest.TestCase):
    def test_same_line_matches_after_normalisation(self):
        self.assertEqual(stm.similarity(LINE, "言わないでくださいまし"), 1.0)
        self.assertEqual(stm.similarity("お嬢様：" + LINE, "「言わないでくださいまし!」"), 1.0)
        self.assertGreaterEqual(stm.similarity(LINE, "言わないでくだきいまし"), 0.6)     # one OCR misread
        self.assertGreaterEqual(stm.similarity(LINE, "言わないでください"), 0.6)          # a partial read
        self.assertGreaterEqual(stm.similarity("Don't you dare say it!", "dont you dare say it"), 0.6)
        self.assertGreaterEqual(stm.similarity("你今天踏出这道门，以后就别回来！", "你今天踏出这道门"), 0.6)

    def test_garbled_or_other_text_does_not_match(self):
        self.assertLess(stm.similarity(LINE, "囗亅彡乂"), 0.6)
        self.assertLess(stm.similarity(LINE, "ありがとう"), 0.6)
        self.assertEqual(stm.similarity(LINE, "！"), 0.0)
        self.assertFalse(stm.is_duplicate(LINE, ["乱码文字", "ABC"]))

    def test_best_match_joins_a_line_split_in_two_boxes(self):
        score, _read = stm.best_match(LINE, ["言わな", "いでくだ"])          # neither box alone reaches it
        self.assertLess(max(stm.similarity(LINE, "言わな"), stm.similarity(LINE, "いでくだ")), 0.6)
        self.assertGreaterEqual(score, 0.6)

    def test_stacked_duplicate_rows(self):
        hit = stm.stacked_duplicate([(0.80, LINE), (0.876, "言わないでくださいまし")])
        self.assertEqual(hit["ys"], [0.8, 0.876])
        # our own two-row caption is two different halves; one row split into two boxes is not two rows
        self.assertIsNone(stm.stacked_duplicate([(0.80, "你今天踏出这道门，"), (0.842, "以后就别回来！")]))
        self.assertIsNone(stm.stacked_duplicate([(0.80, LINE), (0.805, LINE)]))


class S6RecordTest(unittest.TestCase):
    def test_residual_band_texts(self):
        hits = [{"t": 0.5, "text": LINE, "y_centre": 0.876, "glyph_px_at_720": 52},
                {"t": 1.0, "text": LINE, "y_centre": 0.876},
                {"t": 1.0, "text": "看板", "y_centre": 0.30}]
        self.assertEqual(br.residual_band_texts(hits), [LINE])
        self.assertEqual(br.residual_band_texts(None), [])

    def test_s7_bands_carry_the_burned_text_from_the_kept_take(self):
        import nalu_pipeline as npl
        tmp = Path(tempfile.mkdtemp())
        p = SimpleNamespace(preprod_reports=tmp / "reports", video_media=tmp / "video", assembly=tmp / "assembly")
        for d in (p.preprod_reports, p.video_media, p.assembly):
            d.mkdir(parents=True)
        clip = p.video_media / "E07-VU-004.mp4"
        clip.write_bytes(b"kept take")
        sha = npl.sha256_file(clip)
        # an E07-era record: band without texts -> read from the kept take's check hits
        state = {br.STATE_KEY: {"E07-VU-004": {
            br.UNRESOLVED_FLAG: True, "kept_take_sha256": sha,
            "residual_text_band": {"y0": 0.8431, "y1": 0.9095, "hits": 3},
            "checks": {sha: {"hits": [{"t": 0.5, "text": LINE, "y_centre": 0.876}]}}}}}
        (p.preprod_reports / "E07_S6_WAVE_STATE.json").write_text(json.dumps(state, ensure_ascii=False), "utf-8")
        ctx = SimpleNamespace(p=p, episode="E07")
        out = json.loads(npl.s7_residual_burn_bands(ctx).read_text(encoding="utf-8"))
        self.assertEqual(out["units"]["E07-VU-004"], {"y0": 0.8431, "y1": 0.9095, "texts": [LINE]})

    def test_unresolved_record_writes_texts_next_to_the_band(self):
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('band = {**band, "texts": _br.residual_band_texts(kept_check.get("hits"))}', src)


class BurnInSuppressionTest(unittest.TestCase):
    def setUp(self):
        import build_burnin_subtitles as bbs
        self.bbs = bbs

    def rows(self):
        lines = [("E07-VU-004", LINE, 12.6, 14.0), ("E07-VU-004", "でも、もう遅いのです。", 14.1, 15.6),
                 ("E07-VU-005", LINE, 16.0, 17.2)]
        events = [(a, b, {"text": t}) for _u, t, a, b in lines]
        report = [{"unit_id": u, "shot_id": "s", "text": t, "start": a, "end": b} for u, t, a, b in lines]
        return events, report

    def test_matching_cue_is_suppressed_other_cues_kept(self):
        events, report = self.rows()
        ev, rep, gone = self.bbs.suppress_already_burned(events, report, {"E07-VU-004": ["言わないでくださいまし"]})
        self.assertEqual([r["text"] for r in rep], ["でも、もう遅いのです。", LINE])        # VU-005 has no burn
        self.assertEqual(len(ev), 2)
        self.assertEqual((gone[0]["unit_id"], gone[0]["reason"]), ("E07-VU-004", "LINE_ALREADY_BURNED_IN_PICTURE"))
        self.assertEqual(gone[0]["similarity"], 1.0)

    def test_garbled_burn_keeps_the_cue(self):
        events, report = self.rows()
        ev, rep, gone = self.bbs.suppress_already_burned(events, report, {"E07-VU-004": ["囗亅彡乂"]})
        self.assertEqual((len(rep), gone), (3, []))

    def test_a_split_line_is_suppressed_by_its_whole_line(self):
        events = [(1.0, 2.0, {"text": "言わないで"}), (2.0, 3.0, {"text": "くださいまし！"})]
        report = [{"unit_id": "U", "text": "言わないで", "line_text": LINE}, {"unit_id": "U", "text": "くださいまし！",
                                                                              "line_text": LINE}]
        _ev, rep, gone = self.bbs.suppress_already_burned(events, report, {"U": [LINE]})
        self.assertEqual((rep, len(gone)), ([], 2))

    def test_bands_file_texts(self):
        tmp = Path(tempfile.mkdtemp()) / "bands.json"
        tmp.write_text(json.dumps({"units": {"A": {"y0": 0.8, "y1": 0.9, "texts": [LINE]},
                                             "B": {"y0": 0.8, "y1": 0.9}}}, ensure_ascii=False), "utf-8")
        self.assertEqual(self.bbs.burned_band_texts(tmp), {"A": [LINE]})
        self.assertEqual(self.bbs.burned_band_texts(None), {})

    def test_main_wires_the_suppression(self):
        src = (ROOT / "lines/nalu/runtime/tools/build_burnin_subtitles.py").read_text(encoding="utf-8")
        body = src[src.index("def main("):]
        self.assertLess(body.index("suppress_already_burned(events, report"), body.index("events.sort("))
        self.assertIn('"suppressed_duplicate_cues": suppressed', body)


class FixRoundTest(unittest.TestCase):
    def mapped(self, checklist, report=None):
        return ffr.dedupe(ffr.map_findings(ffr.collect_findings(report or {"problems": []}, checklist), SEGMENTS))

    def test_e07_vu004_is_redone_even_when_the_review_only_names_another_burn(self):
        checklist = {"items": {}, "s6_burn_unresolved": [{"unit_id": "E07-VU-004", "retries": 2,
                                                         "reason": "RETRY_MAX_REACHED",
                                                         "residual_in_subtitle_band": True}],
                     "video_review": {"findings": [{"status": "CONFIRMED", "item": "QA-BURNED-TEXT", "start": 93.0,
                                                    "end": 94.2, "severity": "P0", "note": "burned text"}]}}
        mapped = self.mapped(checklist)
        row = next(f for f in mapped if f.get("unit_id") == "E07-VU-004")
        self.assertEqual((row["kind"], row["severity"], row.get("trigger")), ("BURNED_TEXT", "P1", True))
        plan = ffr.plan_paid(mapped, budget=45, headroom=100, unit_cost=lambda _u: 10)
        self.assertIn("E07-VU-004", [r["unit_id"] for r in plan["selected"]])
        # on its own (a review PASS without findings) it still starts the round
        alone = self.mapped({"items": {}, "s6_burn_unresolved": checklist["s6_burn_unresolved"]})
        self.assertTrue(ffr.needs_round(False, alone))

    def test_suppressed_duplicate_is_p2_and_no_trigger(self):
        mapped = self.mapped({"items": {}, "s6_burn_unresolved": [
            {"unit_id": "E07-VU-004", "retries": 2, "residual_in_subtitle_band": True, "duplicate_suppressed": True}]})
        self.assertEqual(mapped[0]["severity"], "P2")
        self.assertIn("suppressed", mapped[0]["text"])
        self.assertFalse(ffr.triggered(False, mapped))

    def test_stacked_subtitle_measurement_is_a_burned_text_trigger(self):
        mapped = self.mapped({"items": {}, "stacked_subtitles": [
            {"window": [12.6, 14.0], "texts": [LINE, "言わないでくださいまし"], "similarity": 1.0}]})
        self.assertEqual(len(mapped), 1)
        f = mapped[0]
        self.assertEqual((f["source"], f["kind"], f["class"], f["unit_id"], f["severity"]),
                         (ffr.STACKED_SOURCE, "BURNED_TEXT", ffr.PAID, "E07-VU-004", "P1"))
        self.assertTrue(ffr.needs_round(False, mapped))
        self.assertEqual(ffr.stacked_subtitle_findings([{"texts": ["a"]}, "x"]), [])


class PipelineFallbackTest(unittest.TestCase):
    def setUp(self):
        import nalu_pipeline as npl
        self.npl = npl
        tmp = Path(tempfile.mkdtemp())
        self.p = SimpleNamespace(preprod_reports=tmp / "reports", video_media=tmp / "video", assembly=tmp / "assembly")
        for d in (self.p.preprod_reports, self.p.video_media, self.p.assembly):
            d.mkdir(parents=True)
        self.ctx = SimpleNamespace(p=self.p, episode="E07")
        clip = self.p.video_media / "E07-VU-004.mp4"
        clip.write_bytes(b"kept")
        self.sha = npl.sha256_file(clip)
        state = {br.STATE_KEY: {"E07-VU-004": {br.UNRESOLVED_FLAG: True, "kept_take_sha256": self.sha,
                                               "unresolved_reason": "RETRY_MAX_REACHED", "attempts": [{}, {}],
                                               "residual_text_band": {"y0": 0.8431, "y1": 0.9095}}}}
        (self.p.preprod_reports / "E07_S6_WAVE_STATE.json").write_text(json.dumps(state), "utf-8")

    def test_rows_come_from_the_wave_state_without_a_checklist(self):
        out = self.npl.final_fix_s6_rows(self.ctx, {})
        row = out["s6_burn_unresolved"][0]
        self.assertEqual((row["unit_id"], row["source_fallback"], row["residual_in_subtitle_band"]),
                         ("E07-VU-004", "S6_WAVE_STATE", True))
        mapped = ffr.map_findings(ffr.collect_findings({}, out), SEGMENTS)
        self.assertTrue(ffr.triggered(False, mapped))

    def test_suppressed_marker_and_superseded_take(self):
        (self.p.assembly / "E07_BURNIN_SUBTITLES.json").write_text(json.dumps(
            {"suppressed_duplicate_cues": [{"unit_id": "E07-VU-004"}]}), "utf-8")
        row = self.npl.final_fix_s6_rows(self.ctx, {})["s6_burn_unresolved"][0]
        self.assertTrue(row["duplicate_suppressed"])
        (self.p.video_media / "E07-VU-004.mp4").write_bytes(b"redone take")       # the unit was redone since
        listed = {"s6_burn_unresolved": [{"unit_id": "E07-VU-004", "kept_take_sha256": self.sha}]}
        self.assertEqual(self.npl.final_fix_s6_rows(self.ctx, listed)["s6_burn_unresolved"], [])
        self.assertNotIn("s6_burn_unresolved", self.npl.final_fix_s6_rows(self.ctx, {}))

    def test_review_findings_use_the_fallback(self):
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def final_fix_review_findings("):src.index("def s7_final_fix_round(")]
        self.assertIn("checklist = final_fix_s6_rows(ctx,", body)


class PostS7MeasurementTest(unittest.TestCase):
    def test_stacked_rows_from_ocr_boxes(self):
        import av_evidence_pack as av
        w, h = 720, 1280

        def box(y, x0=150, x1=570, gh=50):
            return [[x0, y], [x1, y], [x1, y + gh], [x0, y + gh]]
        frame = [(box(1000), LINE, 0.93), (box(1100), "言わないでくださいまし", 0.88), (box(300), "看板", 0.95)]
        hit = av.stacked_rows(frame, w, h)
        self.assertEqual(hit["similarity"], 1.0)
        self.assertIsNone(av.stacked_rows([(box(1000), "你今天踏出这道门，", 0.9), (box(1054), "以后就别回来！", 0.9)],
                                          w, h))
        self.assertIsNone(av.stacked_rows([(box(1000), LINE, 0.9), (box(1100), LINE, 0.3)], w, h))  # low score
        runs = av.stacked_runs([(12.5, hit), (12.75, hit), (13.0, hit), (40.0, hit)])
        self.assertEqual(len(runs), 1)                                  # a single read is not a run
        self.assertEqual((runs[0]["start"], runs[0]["end"], runs[0]["reads"]), (12.5, 13.25, 3))
        summary = av.summary({"stacked_subtitles": {"runs": runs}})
        self.assertEqual(summary["stacked_subtitle_runs"][0]["window"], [12.5, 13.25])

    def test_checklist_carries_it_to_the_reviewer_and_the_round(self):
        import nalu_qa_defect_checklist as qa
        pack = {"stacked_subtitle_runs": [{"window": [12.5, 13.25], "texts": [LINE, LINE], "similarity": 1.0}]}
        flags = qa._measured_findings({"av_evidence_pack": pack})
        self.assertTrue(any(f.get("item_id") == "QA-BURNED-TEXT" and "STACKED_DUPLICATE_SUBTITLE" in f["detail"]
                            for f in flags))
        record = qa.build_record({"items": {}}, {"av_evidence_pack": pack}, episode="E07")
        self.assertTrue(record["items"]["QA-BURNED-TEXT"]["measured_flags"])
        self.assertEqual(record["stacked_subtitles"], pack["stacked_subtitle_runs"])
        self.assertEqual(ffr.collect_findings({}, record)[0]["source"], ffr.STACKED_SOURCE)


if __name__ == "__main__":
    unittest.main()
