"""Strict "is the H3-burned line correct?" check (owner 2026-11-23) + the E24 whole-frame text pass.

PR #299 suppressed our caption whenever the burned OCR read matched the cue >= 0.6 (fuzzy).  The lab
(~/Desktop/烧字后期方案对比/兜底_严格校验烧字是否正确/) showed it accepting T3 「…教习嬷媽…」 (0.962), a missing
character (1.0), 「…看上你妈」 (0.889) and a traditional copy (0.75): the viewer then reads a WRONG line and ours is
gone.  Now only ACCEPT_CORRECT (exact text, stable, confident, steady glyphs, at the spoken time) suppresses; every
other verdict keeps our cue and the unit is a BURNED_TEXT P1 trigger of the final fix round.

E24 review: the S6 detector missed garbled 「不姒伴」「揞哓」 and a mid-frame placard 「樸花美娇」 -- a whole-frame pass
now flags text that says the line or is garbled.  Offline: OCR is replaced by the prototype's per-frame JSON
(tools/tests/fixtures/strict_burn) or stubs; no paid call, no network (a real Japanese OCR run only when the pinned
model is already in the local cache)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import subtitle_text_match as stm  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import ocr_lang_models as olm  # noqa: E402
import tail_frame_text_clean as ttc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "strict_burn"
ZH = "你觉得我会看上你吗？"
T3 = "摄政王如今有二八了吧，如此不经人事，没有教习嬷嬷教过你吗？"
JA1 = "言わないでくださいまし！"
JA2 = "素敵ですわ、セイン様！"
SPOKEN = (0.8, 3.8)        # the synthetic clips burn the line at 1.0-3.5 s
SEGMENTS = [{"unit_id": f"E24-VU-{i:03d}", "output_start": (i - 1) * 4.0, "output_end": i * 4.0} for i in range(1, 30)]


def rows(name: str) -> list[dict]:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))["rows"]


def check(name: str, cue: str, lang: str = "zh", window=SPOKEN, **kw) -> dict:
    return stm.strict_burned_line_check(rows(name), cue, lang, spoken_window=window, **kw)


def frame(t, text, *, score=0.97, h=54.0, yc=0.69, w=720, H=1280):
    """One engine-shaped OCR frame (h3_burn_retry.band_frame_row) with a centred caption box."""
    if text is None:
        return {"t": t, "w": w, "h": H, "boxes": []}
    y0 = yc * H - h / 2
    return {"t": t, "w": w, "h": H, "boxes": [{"text": text, "score": score,
                                               "box": [160, round(y0, 1), 560, round(y0 + h, 1)]}]}


def clip(texts, *, fps=4.0, start=1.0, **kw):
    return [frame(round(start + i / fps, 3), tx, **kw) for i, tx in enumerate(texts)]


class LabFixtureTest(unittest.TestCase):
    """The prototype's per-frame OCR of the lab clips: every Chinese / Japanese case decided correctly."""

    def test_loose_match_accepted_the_wrong_lines(self):  # why the strict rule exists
        self.assertGreaterEqual(stm.similarity("没有教习嬷嬷教过你吗", "没有教习嬷媽教过你吗"), 0.6)
        self.assertGreaterEqual(stm.similarity(ZH, "你觉得我看上你吗"), 0.6)
        self.assertGreaterEqual(stm.similarity(ZH, "你觉得我会看上你妈"), 0.6)
        self.assertGreaterEqual(stm.similarity(ZH, "你覺得我會看上你"), 0.6)

    def test_correct_chinese_line_accepted(self):
        v = check("ZH_ok", ZH)
        self.assertEqual(v["verdict"], stm.ACCEPT_CORRECT, v)
        self.assertEqual(v["segments"], ["你觉得我会看上你吗"])
        self.assertGreaterEqual(v["mean_conf"], 0.9)
        r1 = check("R1", "陆王爷，还有事吗？", window=(0.0, 6.0))   # a real H3 line burned in two segments
        self.assertEqual(r1["verdict"], stm.ACCEPT_CORRECT, r1)

    def test_t3_wrong_character_rejected(self):
        v = check("T3", T3, window=(0.0, 7.0))
        self.assertEqual(v["verdict"], stm.REJECT_WRONG)
        self.assertTrue(v["reasons"][0].startswith("TEXT_MISMATCH"))

    def test_missing_wrong_and_traditional_characters_rejected(self):
        for name in ("ZH_bad_miss", "ZH_bad_near", "ZH_bad_trad"):
            with self.subTest(name):
                self.assertEqual(check(name, ZH)["verdict"], stm.REJECT_WRONG)

    def test_other_text_and_no_text(self):
        self.assertEqual(check("NOLINE_A", ZH)["verdict"], stm.REJECT_WRONG)       # garbled lines of its own
        self.assertEqual(check("MUTE", ZH)["verdict"], stm.NO_BURN)

    def test_japanese_with_the_ja_model(self):
        self.assertEqual(check("JA_ok1_jamodel", JA1, "ja")["verdict"], stm.ACCEPT_CORRECT)
        ok2 = check("JA_ok2_jamodel", JA2, "ja")                   # 、 read as ー: a punctuation look-alike
        self.assertEqual(ok2["verdict"], stm.ACCEPT_CORRECT, ok2)
        self.assertEqual(ok2["segments"], ["素敵ですわセイン様"])           # canonical piece of the cue
        self.assertIn("素敵ですわーセイン様", ok2["distinct_reads"])
        mixed = clip(["素敵ですわーセイン様", "素敵ですわセイン様"] * 5)      # two reads of one picture
        self.assertEqual(stm.strict_burned_line_check(mixed, JA2, "ja", spoken_window=SPOKEN)["verdict"],
                         stm.ACCEPT_CORRECT)
        self.assertEqual(check("JA_bad1_jamodel", JA1, "ja")["verdict"], stm.REJECT_WRONG)    # くだちい
        self.assertEqual(check("JA_bad2_jamodel", JA2, "ja")["verdict"], stm.REJECT_WRONG)    # 素寸

    def test_japanese_with_the_default_model_never_accepts(self):
        self.assertEqual(check("JA_ok1", JA1, "ja")["verdict"], stm.NO_BURN)      # kana not read at all
        self.assertNotEqual(check("JA_ok2", JA2, "ja")["verdict"], stm.ACCEPT_CORRECT)

    def test_lookalike_only_at_the_cues_punctuation(self):
        good = clip(["素敵ですわーセイン様"] * 8)
        self.assertEqual(stm.strict_burned_line_check(good, JA2, "ja", spoken_window=SPOKEN)["verdict"],
                         stm.ACCEPT_CORRECT)
        # the same ー where the cue has no punctuation, or in a Chinese line, is a wrong character
        bad = clip(["素敵ですわセイーン様"] * 8)
        self.assertEqual(stm.strict_burned_line_check(bad, JA2, "ja", spoken_window=SPOKEN)["verdict"],
                         stm.REJECT_WRONG)
        zh = clip(["你觉得一我会看上你吗"] * 8)
        self.assertEqual(stm.strict_burned_line_check(zh, "你觉得，我会看上你吗", "zh",
                                                      spoken_window=SPOKEN)["verdict"], stm.REJECT_WRONG)


class SyntheticRuleTest(unittest.TestCase):
    def v(self, frames, cue=ZH, window=SPOKEN, **kw):
        return stm.strict_burned_line_check(frames, cue, "zh", spoken_window=window, **kw)

    def test_extra_character_and_extra_segment_rejected(self):
        self.assertEqual(self.v(clip(["你觉得我会看上你吗吗"] * 8))["verdict"], stm.REJECT_WRONG)
        frames = clip(["你觉得我会看上你吗"] * 8 + ["石"] * 4, score=0.95)
        self.assertEqual(self.v(frames)["verdict"], stm.REJECT_WRONG)

    def test_size_and_position_jitter_rejected(self):
        heights = [50, 54, 58, 51, 57, 50, 58, 54]
        frames = [frame(1.0 + i / 4, "你觉得我会看上你吗", h=hh) for i, hh in enumerate(heights)]
        v = self.v(frames)
        self.assertEqual(v["verdict"], stm.REJECT_UNSTABLE)
        self.assertTrue(any(r.startswith("SIZE_JITTER") for r in v["reasons"]))
        ys = [0.69, 0.70, 0.71, 0.69, 0.705, 0.69, 0.71, 0.70]
        v = self.v([frame(1.0 + i / 4, "你觉得我会看上你吗", yc=y) for i, y in enumerate(ys)])
        self.assertEqual(v["verdict"], stm.REJECT_UNSTABLE)
        self.assertTrue(any(r.startswith("POSITION_JITTER") for r in v["reasons"]))

    def test_time_window_mismatch_rejected(self):
        v = self.v(clip(["你觉得我会看上你吗"] * 8), window=(5.0, 6.5))
        self.assertEqual(v["verdict"], stm.REJECT_WRONG)
        self.assertTrue(v["reasons"][0].startswith("TIME_WINDOW_MISMATCH"))
        self.assertEqual(self.v(clip(["你觉得我会看上你吗"] * 8), window=None)["verdict"], stm.REJECT_UNSTABLE)

    def test_confidence_and_unstable_reads(self):
        self.assertEqual(self.v(clip(["你觉得我会看上你吗"] * 8, score=0.86))["verdict"], stm.REJECT_UNSTABLE)
        low = clip(["你觉得我会看上你吗"] * 8)
        low[3]["boxes"][0]["score"] = 0.75
        self.assertIn("LOW_OCR_CONF_BOX", " ".join(self.v(low)["reasons"]))
        flicker = clip(["你觉得我会看上你吗"] * 6 + ["你觉得我会看上", "觉得我会看上你吗", "你觉得我会"])
        v = self.v(flicker)
        self.assertEqual(v["verdict"], stm.REJECT_UNSTABLE)
        self.assertTrue(v["reasons"][0].startswith("UNSTABLE_READS"))
        self.assertEqual(self.v(clip(["你觉得我会看上你吗"]))["verdict"], stm.REJECT_UNSTABLE)  # one sample only

    def test_full_line_required_and_unit_lines(self):
        a, b = "陆王爷，还有事吗？", "我这就走。"
        half = clip(["陆王爷"] * 6)
        self.assertEqual(self.v(half, a, unit_lines=[a, b])["verdict"], stm.REJECT_WRONG)
        both = clip(["陆王爷"] * 4 + ["还有事吗"] * 4 + [None] * 2 + ["我这就走"] * 4)
        self.assertEqual(self.v(both, a, window=(0.9, 3.0), unit_lines=[a, b])["verdict"], stm.ACCEPT_CORRECT)
        self.assertEqual(self.v(both, b, window=(3.4, 4.6), unit_lines=[a, b])["verdict"], stm.ACCEPT_CORRECT)
        only_a = clip(["陆王爷"] * 4 + ["还有事吗"] * 4)
        self.assertEqual(self.v(only_a, b, window=(3.4, 4.6), unit_lines=[a, b])["verdict"], stm.NO_BURN)

    def test_no_frame_detail_never_accepts(self):
        self.assertEqual(stm.strict_burned_line_check(None, ZH)["verdict"], stm.REJECT_UNSTABLE)
        self.assertEqual(stm.strict_burned_line_check([], ZH)["verdict"], stm.REJECT_UNSTABLE)
        self.assertEqual(stm.strict_burned_line_check([{"t": "x"}], ZH)["verdict"], stm.REJECT_UNSTABLE)


class BurnInWiringTest(unittest.TestCase):
    def setUp(self):
        import build_burnin_subtitles as bbs
        self.bbs = bbs

    def rows(self, burned_line=ZH):
        events = [(10.0, 13.0, {"text": ZH}), (13.0, 15.0, {"text": "滚出去！"}), (20.0, 22.0, {"text": ZH})]
        report = [{"unit_id": "U4", "shot_id": "S1", "text": ZH, "start": 10.0, "end": 13.0,
                   "source_start": 0.9, "source_end": 3.6},
                  {"unit_id": "U4", "shot_id": "S2", "text": "滚出去！", "start": 13.0, "end": 15.0,
                   "source_start": 3.8, "source_end": 5.0},
                  {"unit_id": "U5", "shot_id": "S3", "text": ZH, "start": 20.0, "end": 22.0,
                   "source_start": 0.5, "source_end": 2.0}]
        ocr = {"source": "S6_KEPT_TAKE", "model": olm.DEFAULT_MODEL_ID, "sample_fps": 4.0,
               "frames": clip([burned_line] * 10)}
        return events, report, {"U4": ocr}

    def test_accept_correct_suppresses_only_that_line(self):
        events, report, burned = self.rows()
        ev, rep, gone, checks = self.bbs.suppress_already_burned(events, report, burned, "zh")
        self.assertEqual([r["shot_id"] for r in rep], ["S2", "S3"])
        self.assertEqual(len(ev), 2)
        self.assertEqual((gone[0]["shot_id"], gone[0]["verdict"]), ("S1", stm.ACCEPT_CORRECT))
        by_shot = {c["shot_id"]: c for c in checks}
        self.assertEqual(by_shot["S2"]["verdict"], stm.NO_BURN)
        self.assertFalse(by_shot["S2"]["suppressed"])

    def test_wrong_line_keeps_our_cue(self):
        for burned in ("你觉得我会看上你妈", "你覺得我會看上你", "你觉得我看上你吗"):
            events, report, ocr = self.rows(burned)
            ev, rep, gone, checks = self.bbs.suppress_already_burned(events, report, ocr, "zh")
            self.assertEqual((len(rep), gone), (3, []), burned)
            self.assertEqual(checks[0]["verdict"], stm.REJECT_WRONG)

    def test_old_bands_without_frames_and_ocr_errors_keep_our_cue(self):
        events, report, _ = self.rows()
        _e, rep, gone, checks = self.bbs.suppress_already_burned(events, report, {"U4": {}}, "zh")
        self.assertEqual((len(rep), gone, checks[0]["verdict"]), (3, [], stm.REJECT_UNSTABLE))
        bad = {"U4": {"source": "S7_REOCR", "error": "OcrModelUnavailable: missing"}}
        _e, rep, gone, checks = self.bbs.suppress_already_burned(events, report, bad, "ja")
        self.assertEqual((len(rep), gone), (3, []))
        self.assertIn("OCR_UNAVAILABLE", " ".join(checks[0]["reasons"]))

    def test_recut_unit_never_suppressed(self):
        events, report, burned = self.rows()
        report[0]["unit_recut"] = True
        _e, rep, gone, checks = self.bbs.suppress_already_burned(events, report, burned, "zh")
        self.assertEqual((len(rep), gone, checks[0]["reasons"]), (3, [], ["UNIT_RECUT_TIMEBASE"]))

    def test_split_line_is_suppressed_as_a_whole(self):
        events = [(1.0, 2.0, {"text": "言わないで"}), (2.0, 3.0, {"text": "くださいまし！"})]
        report = [{"unit_id": "U", "shot_id": "S", "text": "言わないで", "line_text": JA1, "source_start": 0.9,
                   "source_end": 3.6},
                  {"unit_id": "U", "shot_id": "S", "text": "くださいまし！", "line_text": JA1, "source_start": 0.9,
                   "source_end": 3.6}]
        ocr = {"U": {"frames": rows("JA_ok1_jamodel"), "model": olm.model_id("ja")}}
        _e, rep, gone, checks = self.bbs.suppress_already_burned(events, report, ocr, "ja")
        self.assertEqual((rep, len(gone), len(checks)), ([], 2, 1))

    def test_bands_file_and_main_wiring(self):
        tmp = Path(tempfile.mkdtemp()) / "bands.json"
        tmp.write_text(json.dumps({"units": {"A": {"y0": 0.8, "y1": 0.9, "ocr": {"frames": []}},
                                             "B": {"y0": 0.8, "y1": 0.9}}}), "utf-8")
        self.assertEqual(self.bbs.burned_band_ocr(tmp), {"A": {"frames": []}, "B": {}})
        src = (ROOT / "lines/nalu/runtime/tools/build_burnin_subtitles.py").read_text(encoding="utf-8")
        body = src[src.index("def main("):]
        self.assertIn("suppress_already_burned(events, report, burned_band_ocr(a.avoid_bands)", body)
        self.assertIn('"burned_line_checks": line_checks', body)


class FixRoundTest(unittest.TestCase):
    def mapped(self, row):
        return ffr.dedupe(ffr.map_findings(ffr.collect_findings({"problems": []}, {
            "items": {}, "s6_burn_unresolved": [{"unit_id": "E24-VU-004", "retries": 2,
                                                 "residual_in_subtitle_band": True, **row}]}), SEGMENTS))

    def test_not_accept_correct_is_p1_trigger(self):
        for row in ({}, {"duplicate_suppressed": True},                       # no strict verdict recorded
                    {"duplicate_suppressed": True, "strict_burn_verdicts": ["REJECT_WRONG"]},
                    {"strict_burn_verdicts": ["REJECT_UNSTABLE"]},
                    {"duplicate_suppressed": True, "strict_burn_verdicts": ["ACCEPT_CORRECT", "REJECT_UNSTABLE"]}):
            with self.subTest(row):
                mapped = self.mapped(row)
                self.assertEqual((mapped[0]["severity"], mapped[0].get("trigger")), ("P1", True))
                self.assertTrue(ffr.triggered(False, mapped))

    def test_accept_correct_is_p2(self):
        mapped = self.mapped({"duplicate_suppressed": True, "strict_burn_verdicts": ["ACCEPT_CORRECT", "NO_BURN"]})
        self.assertEqual(mapped[0]["severity"], "P2")
        self.assertFalse(ffr.triggered(False, mapped))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        import nalu_pipeline as npl
        self.npl = npl
        tmp = Path(tempfile.mkdtemp())
        self.p = SimpleNamespace(preprod_reports=tmp / "reports", video_media=tmp / "video", assembly=tmp / "assembly",
                                 grouping_plan=tmp / "grouping.json", contract=tmp / "contract.json")
        for d in (self.p.preprod_reports, self.p.video_media, self.p.assembly):
            d.mkdir(parents=True)
        clip_path = self.p.video_media / "E24-VU-004.mp4"
        clip_path.write_bytes(b"kept take")
        self.sha = npl.sha256_file(clip_path)

    def state(self, check):
        state = {br.STATE_KEY: {"E24-VU-004": {br.UNRESOLVED_FLAG: True, "kept_take_sha256": self.sha,
                                               "unresolved_reason": "RETRY_MAX_REACHED", "attempts": [{}, {}],
                                               "residual_text_band": {"y0": 0.66, "y1": 0.72},
                                               "checks": {self.sha: check}}}}
        (self.p.preprod_reports / "E24_S6_WAVE_STATE.json").write_text(json.dumps(state, ensure_ascii=False), "utf-8")

    def test_s7_bands_fall_back_to_s6_frames_for_chinese(self):  # the fake clip cannot be re-read
        frames = clip([ZH] * 6)
        self.state({"hits": [], "ocr_frames": frames, "ocr_model": olm.DEFAULT_MODEL_ID})
        ctx = SimpleNamespace(p=self.p, episode="E24", language="zh")
        out = json.loads(self.npl.s7_residual_burn_bands(ctx).read_text(encoding="utf-8"))
        ocr = out["units"]["E24-VU-004"]["ocr"]
        self.assertEqual((ocr["source"], ocr["model"], ocr["frames"]), ("S6_KEPT_TAKE", olm.DEFAULT_MODEL_ID, frames))

    def test_s7_bands_reread_japanese_with_the_language_model(self):
        self.state({"hits": [], "ocr_frames": clip(["素樣"] * 6), "ocr_model": olm.DEFAULT_MODEL_ID})
        ctx = SimpleNamespace(p=self.p, episode="E24", language="ja")
        seen = {}

        def reread(path, lang, **_kw):
            seen.update(path=Path(path).name, lang=lang)
            return {"source": "S7_REOCR", "model": olm.model_id("ja"), "lang": lang, "frames": clip([JA2] * 6)}
        with mock.patch.object(br, "ocr_band_frames", reread):
            out = json.loads(self.npl.s7_residual_burn_bands(ctx).read_text(encoding="utf-8"))
        self.assertEqual(seen, {"path": "E24-VU-004.mp4", "lang": "ja"})
        self.assertEqual(out["units"]["E24-VU-004"]["ocr"]["model"], "japan_PP-OCRv4_rec_mobile")
        # the re-read fails and S6 read the take with the Chinese recogniser: no usable frames -> error (cue kept)
        with mock.patch.object(br, "ocr_band_frames", lambda *_a, **_k: {"error": "OcrModelUnavailable: x"}):
            out = json.loads(self.npl.s7_residual_burn_bands(ctx).read_text(encoding="utf-8"))
        self.assertEqual(out["units"]["E24-VU-004"]["ocr"]["error"], "OcrModelUnavailable: x")

    def test_fix_rows_mark_suppressed_only_on_accept(self):
        self.state({"hits": []})
        ctx = SimpleNamespace(p=self.p, episode="E24")
        report = self.p.assembly / "E24_BURNIN_SUBTITLES.json"
        report.write_text(json.dumps({"suppressed_duplicate_cues": [{"unit_id": "E24-VU-004",
                                                                     "verdict": "ACCEPT_CORRECT"}],
                                      "burned_line_checks": [{"unit_id": "E24-VU-004", "verdict": "ACCEPT_CORRECT"}]}),
                          "utf-8")
        row = self.npl.final_fix_s6_rows(ctx, {})["s6_burn_unresolved"][0]
        self.assertTrue(row["duplicate_suppressed"])
        self.assertEqual(ffr.s6_unresolved_findings([row])[0]["severity"], "P2")
        # a PR #299-era report (suppressed without a strict verdict) no longer counts
        report.write_text(json.dumps({"suppressed_duplicate_cues": [{"unit_id": "E24-VU-004"}]}), "utf-8")
        row = self.npl.final_fix_s6_rows(ctx, {})["s6_burn_unresolved"][0]
        self.assertNotIn("duplicate_suppressed", row)
        self.assertEqual(ffr.s6_unresolved_findings([row])[0]["severity"], "P1")

    def test_release_hold_reads_the_strict_verdict(self):
        """#302 x #303: an unresolved burn whose unit S7 strictly ACCEPT_CORRECT-ed does not hold the X2C release;
        a REJECT_WRONG one does (real BURNIN_SUBTITLES record -> final_fix_s6_rows -> finding -> release policy)."""
        self.state({"hits": []})
        ctx = SimpleNamespace(p=self.p, episode="E24")
        report = self.p.assembly / "E24_BURNIN_SUBTITLES.json"

        def policy(verdict, suppressed):
            report.write_text(json.dumps({
                "suppressed_duplicate_cues": ([{"unit_id": "E24-VU-004", "verdict": verdict}] if suppressed else []),
                "burned_line_checks": [{"unit_id": "E24-VU-004", "verdict": verdict}]}), "utf-8")
            row = self.npl.final_fix_s6_rows(ctx, {})["s6_burn_unresolved"][0]
            findings = ffr.map_findings(ffr.s6_unresolved_findings([row]), [])
            record = {"status": "DONE", "findings": findings,
                      "unresolved": [{"kind": "BURNED_TEXT", "unit_id": "E24-VU-004", "state": "PERSISTS"}]}
            return ffr.release_policy(ffr.objective_defects(record, runtime_s=100, target_s=110), env={})
        accepted = policy("ACCEPT_CORRECT", True)
        self.assertEqual((accepted["blocks"], accepted["classes"]), (False, ["BURN_UNRESOLVED"]))
        rejected = policy("REJECT_WRONG", False)
        self.assertEqual((rejected["blocks"], rejected["hold"]), (True, "RELEASE_HELD:BURN_UNRESOLVED"))
        # the verdict list itself decides: a REJECT next to the ACCEPT still holds; legacy suppression alone holds
        self.assertFalse(ffr.burn_accepted({"strict_burn_verdicts": ["ACCEPT_CORRECT", "REJECT_UNSTABLE"],
                                            "duplicate_suppressed": True}))
        self.assertFalse(ffr.burn_accepted({"duplicate_suppressed": True}))
        self.assertFalse(ffr.burn_accepted({"unit_id": "U", "verdict": "REJECT_WRONG"}))
        self.assertTrue(ffr.burn_accepted({"unit_id": "U", "verdict": "ACCEPT_CORRECT"}))

    def test_unit_lines_and_summary(self):
        self.p.grouping_plan.write_text(json.dumps({"units": [{"unit_id": "E24-VU-004",
                                                               "editorial_shot_ids": ["S1", "S2"]}]}), "utf-8")
        self.p.contract.write_text(json.dumps({"audio_contract": {"dialogue_units": [
            {"shot_id": "S1", "text": ZH}, {"shot_id": "S9", "text": "别的"}, {"shot_id": "S2", "text": "滚！"}]}},
            ensure_ascii=False), "utf-8")
        ctx = SimpleNamespace(p=self.p, episode="E24")
        self.assertEqual(self.npl.s6_unit_lines(ctx, "E24-VU-004"), [ZH, "滚！"])
        self.assertEqual(self.npl.s6_unit_lines(SimpleNamespace(), "x"), [])
        said = []
        report = self.p.assembly / "r.json"
        report.write_text(json.dumps({"burned_line_checks": [{"unit_id": "U", "verdict": "REJECT_WRONG",
                                                              "reasons": ["TEXT_MISMATCH"], "suppressed": False}]}),
                          "utf-8")
        rows_ = self.npl.s7_burned_line_summary(SimpleNamespace(say=said.append), report)
        self.assertEqual(rows_[0]["verdict"], "REJECT_WRONG")
        self.assertIn("S7_BURNED_LINE_CHECK unit=U", said[0])


# ------------------------------------------------------------------------------- S6 detector: frames + E24 pass
W, H = 720, 1280


def _frames(n):
    import numpy as np

    def reader(_video, fps):
        for i in range(n):
            yield round((i + 0.5) / fps, 3), np.zeros((H, W, 3), dtype=np.uint8)
    return reader


def _band_ocr(flags, text=ZH):
    seq = iter(flags)

    def ocr(_crop):
        if not next(seq):
            return []
        y = 0.74 * H - 0.55 * H - 28
        return [([[160, y], [560, y], [560, y + 56], [160, y + 56]], text, 0.95)]
    return ocr


def _whole(boxes_per_frame):
    seq = iter(boxes_per_frame)

    def ocr(_img):
        return next(seq)
    return ocr


def quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class DetectorTest(unittest.TestCase):
    def test_burned_take_keeps_per_frame_ocr(self):
        res = br.detect(Path("c.mp4"), frames=_frames(4), ocr=_band_ocr([False, True, True, True]))
        self.assertEqual(res["status"], "BURNED")
        self.assertEqual(len(res["ocr_frames"]), 4)
        f = res["ocr_frames"][1]
        self.assertEqual((f["w"], f["h"], f["boxes"][0]["text"]), (W, H, ZH))
        self.assertAlmostEqual((f["boxes"][0]["box"][1] + f["boxes"][0]["box"][3]) / 2 / H, 0.74, places=2)
        v = stm.strict_burned_line_check(res["ocr_frames"], ZH, "zh", spoken_window=(0, 2))
        self.assertEqual(v["verdict"], stm.ACCEPT_CORRECT, v)

    def test_whole_frame_pass_flags_garbled_placard_and_line(self):
        n = 3
        garbled = [[(quad(300, 900, 420, 950), "不姒伴", 0.52)]] * n                 # off the band rules: low score
        res = br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n), suspect_ocr=_whole(garbled))
        self.assertEqual(res["status"], "BURNED")
        self.assertEqual({h["kind"] for h in res["hits"]}, {"GARBLED"})
        placard = [[(quad(260, 400, 458, 1000), "樸花美娇", 0.81)]] * n              # vertical, mid-frame, 198 px
        res = br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n), suspect_ocr=_whole(placard))
        self.assertEqual((res["status"], res["hits"][0].get("vertical")), ("BURNED", True))
        line = [[(quad(40, 300, 300, 340), "看上你吗", 0.93)]] * n                     # off-centre copy of the line
        res = br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n), suspect_ocr=_whole(line),
                        lines=[ZH])
        self.assertEqual(res["hits"][0]["kind"], "LINE_MATCH")

    def test_whole_frame_pass_keeps_false_positives_out(self):
        n = 4
        sign = [[(quad(300, 200, 420, 260), "茶楼", 0.95), (quad(500, 600, 540, 640), "川", 0.45)]] * n
        res = br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n), suspect_ocr=_whole(sign),
                        lines=[ZH])
        self.assertEqual(res["status"], "CLEAN")                       # common-character sign, 1-char texture
        huge = [[(quad(0, 0, 720, 900), "不姒伴", 0.9)]] * n                       # > 25 % of the frame
        self.assertEqual(br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n),
                                   suspect_ocr=_whole(huge))["status"], "CLEAN")
        flicker = [[(quad(300, 900, 420, 950), "揞哓", 0.7)], [], [(quad(300, 900, 420, 950), "揞哓", 0.7)], []]
        self.assertEqual(br.detect(Path("c.mp4"), frames=_frames(n), ocr=_band_ocr([False] * n),
                                   suspect_ocr=_whole(flicker))["status"], "CLEAN")   # never 2 samples in a row
        ours = [(quad(160, 1010, 560, 1060), "揞哓", 0.7)]                          # e.g. our own caption / card
        image = __import__("numpy").zeros((H, W, 3), dtype="uint8")
        self.assertEqual(ttc.find_suspect_text_boxes(image, lambda _i: ours, exclude=[(0.0, 0.75, 1.0, 0.9)]), [])
        self.assertEqual(len(ttc.find_suspect_text_boxes(image, lambda _i: ours)), 1)
        # Japanese / Korean kanji are not "rare Chinese"; only a low-score read or the line counts there
        self.assertIsNone(ttc.suspect_kind("樸花美娇", 0.9, lang="ja"))
        self.assertEqual(ttc.suspect_kind("樸花美娇", 0.5, lang="ja"), "LOW_SCORE")

    def test_injected_band_ocr_skips_the_pass_and_env_off(self):
        res = br.detect(Path("c.mp4"), frames=_frames(3), ocr=_band_ocr([False] * 3))
        self.assertEqual((res["status"], res["ocr_model"]), ("CLEAN", "injected"))
        with mock.patch.dict(os.environ, {br.ENV_SUSPECT: "off"}):
            self.assertFalse(br.suspect_pass_enabled())

    def test_s7_reread_helper(self):
        res = br.ocr_band_frames(Path("c.mp4"), "ja", frames=_frames(2), ocr=_band_ocr([True, True], JA1),
                                 model="japan_PP-OCRv4_rec_mobile")
        self.assertEqual((res["model"], len(res["frames"]), res["frames"][0]["boxes"][0]["text"]),
                         ("japan_PP-OCRv4_rec_mobile", 2, JA1))
        with mock.patch.object(olm, "engine", side_effect=olm.OcrModelUnavailable("missing")):
            self.assertIn("missing", br.ocr_band_frames(Path("c.mp4"), "ja", frames=_frames(1))["error"])


class ModelAssetTest(unittest.TestCase):
    def test_model_ids(self):
        self.assertEqual(olm.model_id("zh"), olm.DEFAULT_MODEL_ID)
        self.assertEqual(olm.model_id("en"), olm.DEFAULT_MODEL_ID)
        self.assertEqual(olm.model_id("ja"), "japan_PP-OCRv4_rec_mobile")
        self.assertEqual(olm.model_id("ko-KR"), "korean_PP-OCRv5_rec_mobile")
        self.assertIsNone(olm.ensure("zh"))
        for row in olm.MODELS.values():
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("/resolve/v3.10.0/", row["url"])        # a pinned tag, never master

    def test_download_verifies_sha256_offline(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "src.onnx"
        src.write_bytes(b"fake weights")
        import hashlib
        good = {"id": "t_model", "file": "t.onnx", "url": src.as_uri(), "bytes": 12,
                "sha256": hashlib.sha256(b"fake weights").hexdigest()}
        with mock.patch.dict(os.environ, {olm.ENV_DIR: str(tmp / "cache")}), \
                mock.patch.dict(olm.MODELS, {"xx": good}), mock.patch.dict(olm._VERIFIED, {}, clear=True):
            path = olm.ensure("xx")
            self.assertEqual(path.read_bytes(), b"fake weights")
            olm._VERIFIED.clear()
            self.assertEqual(olm.ensure("xx", download=False), path)          # cached + verified
            path.write_bytes(b"tampered")
            olm._VERIFIED.clear()
            with self.assertRaises(olm.OcrModelUnavailable):
                olm.ensure("xx")
            path.unlink()
            with self.assertRaises(olm.OcrModelUnavailable):
                olm.ensure("xx", download=False)
            with mock.patch.dict(olm.MODELS, {"xx": {**good, "sha256": "0" * 64}}):
                with self.assertRaises(olm.OcrModelUnavailable):
                    olm.ensure("xx")
                self.assertFalse(path.exists())                               # a bad download never lands

    def test_setup_host_prefetches(self):
        src = (ROOT / "skills/nalu-claude-code/scripts/setup_host.sh").read_text(encoding="utf-8")
        self.assertIn("tools/ocr_lang_models.py prefetch ja ko", src)

    @unittest.skipUnless((olm.model_dir() / olm.MODELS["ja"]["file"]).is_file(), "ja OCR model not cached")
    def test_real_japanese_read(self):  # pragma: no cover - only where the model is already present
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont
            font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 56)
        except Exception:  # noqa: BLE001
            self.skipTest("no Japanese font / PIL")
        im = Image.new("RGB", (720, 300), (40, 50, 60))
        ImageDraw.Draw(im).text((60, 120), JA1, font=font, fill=(250, 250, 250))
        engine, mid = olm.engine("ja")
        text = "".join(r[1] for r in engine(np.array(im)[:, :, ::-1].copy())[0] or [])
        self.assertEqual(stm.strict_normalise(text), stm.strict_normalise(JA1))


if __name__ == "__main__":
    unittest.main()
