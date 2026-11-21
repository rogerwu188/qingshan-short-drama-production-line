#!/usr/bin/env python3
"""JA-01 anime E04 (device 1485, engine c05374a, 2026-11-21): the final fix round redid six other units while the two
defects both final reviews flagged shipped.  Offline: no provider, no credits.

* 0:11 VU-004: H3 burned 「素敵ですわ、セイン様！」 at y ~0.84; our subtitle stacked on it (two identical lines).
  Gemini filed it as QA-SUBTITLE-WRAP P2, the reviewer as a problem -> now BURNED_TEXT (paid redo), and an UNRESOLVED
  S6 burn in our subtitle band moves our caption above it in S7 and joins the round; Q2 OCR counts any >= 2-character
  text in the subtitle band.
* 0:20 VU-007: H3 drew the multi-view identity sheet as the picture; the S6 burn check called it CLEAN, Q2 passed it,
  Gemini filed it as CRAFT-SHOT-GRAMMAR P0 -> now REFERENCE_SHEET_LEAK (paid redo with the sheet sent as its
  front-view crop), the S6 sheet detector, the anime Q2 question, the Gemini class and the KB route.
* paid redos are ranked by severity first: the P0s are redone before P2 burned-text units.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, REPO / "tools", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import build_burnin_subtitles as bbs  # noqa: E402
import build_nalu_preproduction as bnp  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as grp  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import h3_reference_sheet_guard as sg  # noqa: E402
import nalu_knowledge_events as kbe  # noqa: E402
import nalu_pipeline as P  # noqa: E402
import nalu_qa_defect_checklist as qadc  # noqa: E402
import render_style as rs  # noqa: E402
import video_q2_builder as q2  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.tests.test_s6_burned_text_retry import CHAIN, _Harness  # noqa: E402

# the exact final-review texts of E04 (Gemini multi-pass + Codex reviewer)
G2 = {"id": "G2", "item": "QA-SUBTITLE-WRAP", "window": [11.0, 12.5], "severity": "P2", "status": "CONFIRMED",
      "note": "字幕行重复叠加显示", "evidence": "two identical lines"}
G3 = {"id": "G3", "item": "CRAFT-SHOT-GRAMMAR", "window": [18.5, 21.2], "severity": "P0", "status": "CONFIRMED",
      "note": "对白中突兀切入角色设定三视图静态立绘"}
G10 = {"id": "G10", "item": "CRAFT-SHOT-GRAMMAR", "window": [137.0, 139.5], "severity": "P0", "status": "CONFIRMED",
       "note": "setting card again"}
CODEX_P0 = {"severity": "P0", "at_seconds": 19.0, "issue": "shot5 重复人物叠影和设定卡式静态构图",
            "fix": "重生成该镜头"}
CODEX_P2 = {"severity": "P2", "at_seconds": 11.5, "issue": "shot3 同一句字幕在底部重复叠加", "fix": "去掉重复字幕"}

#: the E04 release timeline around the findings + the six units the old round redid instead
SEGMENTS = [{"unit_id": "E04-VU-003", "output_start": 7.0, "output_end": 10.0},
            {"unit_id": "E04-VU-004", "output_start": 10.0, "output_end": 13.5},
            {"unit_id": "E04-VU-007", "output_start": 18.0, "output_end": 22.0},
            {"unit_id": "E04-VU-011", "output_start": 40.0, "output_end": 46.0},
            {"unit_id": "E04-VU-021", "output_start": 70.0, "output_end": 76.0},
            {"unit_id": "E04-VU-024", "output_start": 80.0, "output_end": 86.0},
            {"unit_id": "E04-VU-031", "output_start": 100.0, "output_end": 106.0},
            {"unit_id": "E04-VU-033", "output_start": 110.0, "output_end": 116.0},
            {"unit_id": "E04-VU-038", "output_start": 136.0, "output_end": 140.0},
            {"unit_id": "E04-VU-041", "output_start": 150.0, "output_end": 156.0}]
#: P2 burned-text findings on the six units the old round chose (longer on screen than the P0s)
OTHER_BURNS = [{"id": f"G{20 + i}", "item": "QA-BURNED-TEXT", "window": [s + 0.5, s + 5.5], "severity": "P2",
                "status": "CONFIRMED", "note": "画面里多出一行乱码字"}
               for i, s in enumerate((40.0, 70.0, 80.0, 100.0, 110.0, 150.0))]


def e04_findings(s6_unresolved: bool = False) -> list[dict]:
    checklist = {"items": {}, "video_review": {"findings": [G2, G3, G10, *OTHER_BURNS]}}
    if s6_unresolved:  # E04: VU-004's S6 burn retries ended UNRESOLVED (8/18 -> 8/18 -> 2/18) in our subtitle band
        checklist["s6_burn_unresolved"] = [{"unit_id": "E04-VU-004", "retries": 2, "reason": "RETRY_MAX_REACHED",
                                            "residual_in_subtitle_band": True}]
    report = {"problems": [CODEX_P0, CODEX_P2]}
    return ffr.dedupe(ffr.map_findings(ffr.collect_findings(report, checklist), SEGMENTS))


class ClassifyByContentTest(unittest.TestCase):
    def test_exact_e04_texts(self):
        self.assertEqual(ffr.classify("QA-SUBTITLE-WRAP", "字幕行重复叠加显示 | two identical lines"), "BURNED_TEXT")
        self.assertEqual(ffr.classify("QA-SUBTITLE-WRAP", "字幕行重复叠加显示"), "BURNED_TEXT")
        self.assertEqual(ffr.classify("CRAFT-SHOT-GRAMMAR", "对白中突兀切入角色设定三视图静态立绘"), "REFERENCE_SHEET_LEAK")
        self.assertEqual(ffr.classify("CRAFT-SHOT-GRAMMAR", "setting card again"), "REFERENCE_SHEET_LEAK")
        self.assertEqual(ffr.classify(None, "shot5 重复人物叠影和设定卡式静态构图 | 重生成该镜头"), "REFERENCE_SHEET_LEAK")
        self.assertEqual(ffr.classify(None, "shot3 同一句字幕在底部重复叠加 | 去掉重复字幕"), "BURNED_TEXT")
        self.assertEqual(ffr.classify("QA-REFERENCE-SHEET-LEAK"), "REFERENCE_SHEET_LEAK")
        self.assertEqual(ffr.fix_class("REFERENCE_SHEET_LEAK"), ffr.PAID)

    def test_english_wording_and_no_false_positives(self):
        for text in ("the frame shows a character turnaround sheet with front, side and back views",
                     "model sheet of the heroine appears mid-dialogue", "three copies of the same character",
                     "a face close-up inset over three full-body views"):
            self.assertEqual(ffr.classify("OTHER", text), "REFERENCE_SHEET_LEAK", text)
        for text in ("stacked subtitles at the bottom", "duplicated caption under ours", "ghost subtitle",
                     "two identical lines at the bottom"):
            self.assertEqual(ffr.classify("QA-SUBTITLE-WRAP", text), "BURNED_TEXT", text)
        # comparisons with the card are identity / costume findings, a plain wrap stays a free re-cut
        self.assertEqual(ffr.classify("LOOK-DRIFT", "发型与设定图不符"), "COSTUME_IDENTITY")
        self.assertEqual(ffr.classify(None, "costume differs from the identity card"), "COSTUME_IDENTITY")
        self.assertEqual(ffr.classify("QA-SUBTITLE-WRAP", "「！」单独成行"), "SUBTITLE_WRAP")
        self.assertEqual(ffr.classify("CRAFT-SHOT-GRAMMAR", "对白时静止长镜头不切"), "SHOT_GRAMMAR")

    def test_sheet_redo_sentence_is_plain_english(self):
        text = ffr.redo_sentence(["REFERENCE_SHEET_LEAK"])
        self.assertIn("never shows a character sheet", text)
        self.assertNotRegex(text, r"\d|[A-Z]{3,}")


class E04RoutingTest(unittest.TestCase):
    def test_e04_findings_map_to_the_right_units_and_kinds(self):
        mapped = e04_findings()
        by_unit = {}
        for f in mapped:
            by_unit.setdefault(f.get("unit_id"), set()).add(f["kind"])
        self.assertEqual(by_unit["E04-VU-004"], {"BURNED_TEXT"})          # G2 + Codex P2 deduped into one
        self.assertEqual(by_unit["E04-VU-007"], {"REFERENCE_SHEET_LEAK"})  # G3 + Codex P0
        self.assertEqual(by_unit["E04-VU-038"], {"REFERENCE_SHEET_LEAK"})  # G10 137-139.5
        vu004 = [f for f in mapped if f.get("unit_id") == "E04-VU-004"]
        self.assertEqual(len(vu004), 1)
        vu007 = next(f for f in mapped if f.get("unit_id") == "E04-VU-007")
        self.assertEqual(vu007["severity"], "P0")
        self.assertTrue(ffr.needs_round(False, mapped))

    def test_p0_units_are_redone_first_within_the_budget(self):
        mapped = e04_findings()
        plan = ffr.plan_paid(mapped, budget=45, headroom=1000, unit_cost=lambda _u: 11,
                             unit_order=[s["unit_id"] for s in SEGMENTS])
        selected = [r["unit_id"] for r in plan["selected"]]
        self.assertEqual(selected[:2], ["E04-VU-007", "E04-VU-038"])       # P0 sheet leaks first
        self.assertEqual(len(selected), 4)
        # with the S6 UNRESOLVED record of E04 the stacked line is P1: right after the P0s, before every P2
        plan = ffr.plan_paid(e04_findings(s6_unresolved=True), budget=45, headroom=1000, unit_cost=lambda _u: 11,
                             unit_order=[s["unit_id"] for s in SEGMENTS])
        selected = [r["unit_id"] for r in plan["selected"]]
        self.assertEqual(selected[:3], ["E04-VU-007", "E04-VU-038", "E04-VU-004"])
        self.assertEqual(plan["selected"][0]["kinds"], ["REFERENCE_SHEET_LEAK"])
        skipped = {r["unit_id"]: r["reason"] for r in plan["skipped"]}
        self.assertTrue(all(v == "BUDGET_CAP" for v in skipped.values()))
        # a P0 that does not fit is still tried before any P2
        plan = ffr.plan_paid(mapped, budget=11, headroom=1000, unit_cost=lambda _u: 11)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["E04-VU-007"])

    def test_severity_words_and_default(self):
        self.assertEqual([ffr.severity_of(v) for v in ("P0", "p2", "critical", "Major", "low", None, "P1 严重")],
                         ["P0", "P2", "P0", "P1", "P3", "P1", "P1"])

    def test_s6_unresolved_units_join_the_round_but_never_trigger_it(self):
        checklist = {"items": {}, "s6_burn_unresolved": [
            {"unit_id": "E04-VU-004", "retries": 2, "reason": "RETRY_MAX_REACHED", "residual_in_subtitle_band": True},
            {"unit_id": "E04-VU-007", "retries": 2, "reason": "RETRY_MAX_REACHED", "sheet_leak": True},
            {"unit_id": "E04-VU-011", "retries": 2, "reason": "RETRY_MAX_REACHED"}]}
        mapped = ffr.map_findings(ffr.collect_findings({}, checklist), SEGMENTS)
        rows = {f["unit_id"]: f for f in mapped}
        self.assertEqual((rows["E04-VU-004"]["kind"], rows["E04-VU-004"]["severity"]), ("BURNED_TEXT", "P1"))
        self.assertEqual((rows["E04-VU-007"]["kind"], rows["E04-VU-007"]["severity"]),
                         ("REFERENCE_SHEET_LEAK", "P0"))
        self.assertEqual(rows["E04-VU-011"]["severity"], "P2")
        self.assertEqual(rows["E04-VU-004"]["window"], [10.0, 13.5])
        self.assertFalse(ffr.triggered(False, mapped))
        # with a confirmed review finding the S6 rows dedupe with it (same unit window)
        both = ffr.dedupe(e04_findings() + mapped)
        vu004 = [f for f in both if f.get("unit_id") == "E04-VU-004"]
        self.assertEqual(len(vu004), 1)
        self.assertIn(ffr.S6_SOURCE, vu004[0]["sources"])
        self.assertEqual(vu004[0]["severity"], "P1")

    def test_kb_ignores_s6_rows_and_routes_sheet_leak_global_model_constraint(self):
        self.assertEqual(kbe.FINAL_REVIEW_ROUTES["REFERENCE_SHEET_LEAK"], "MODEL_CONSTRAINT")
        self.assertEqual(kbe.final_review_scope({"item": "CRAFT-SHOT-GRAMMAR"}, "REFERENCE_SHEET_LEAK")["scope"],
                         "global")
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "c.json").write_text(json.dumps({"items": {}, "s6_burn_unresolved": [{"unit_id": "U1"}]}))
            (tmp / "r.json").write_text(json.dumps({"problems": []}))
            got = kbe.record_final_review_findings(tmp, episode="E04", report_path=str(tmp / "r.json"),
                                                   checklist_path=str(tmp / "c.json"))
            self.assertEqual(got["status"], "NO_FINDINGS")
        calls = []
        with mock.patch.object(kbe, "emit", lambda *a, **k: calls.append(k) or {"status": "RECORDED"}):
            out = kbe.record_s6_reference_sheet_leak(Path("."), episode="E04", unit_id="E04-VU-007",
                                                     detection={"leak_frames": 6, "best_score": 0.81},
                                                     clip_sha256="ab")
        self.assertEqual(out["status"], "OK")
        ev = calls[0]["evidence"]
        self.assertEqual((ev["lesson_route"], ev["kb_scope"], calls[0]["stage"]), ("MODEL_CONSTRAINT", "global", "S6"))
        self.assertEqual(calls[0]["failure_type"], "QA_DEFECT:QA-REFERENCE-SHEET-LEAK")


# ------------------------------------------------------------------------------------- sheet guard
def _sheet(w=600, h=900) -> Image.Image:
    """A synthetic multi-view sheet in the identity builder's layout: face panel on top, three bodies below."""
    img = Image.new("RGB", (w, h), (128, 128, 130))
    d = ImageDraw.Draw(img)
    d.ellipse((240, 30, 360, 170), fill=(230, 200, 180))           # face
    d.rectangle((180, 170, 420, 300), fill=(90, 60, 50))           # shoulders of the close-up
    for x in (60, 250, 440):
        d.ellipse((x + 20, 360, x + 80, 420), fill=(230, 200, 180))
        d.rectangle((x, 420, x + 100, 860), fill=(90, 60, 50))
    return img


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class SheetGuardTest(unittest.TestCase):
    def test_front_view_crop_is_the_face_panel(self):
        box, method = sg.front_view_box(_sheet())
        self.assertEqual(method, "CONTENT_GAP")
        x0, y0, x1, y1 = box
        self.assertLess(y0, 40)
        self.assertTrue(290 <= y1 <= 345, box)                         # stops in the gap above the bodies
        self.assertTrue(x0 <= 180 and x1 >= 420, box)
        data, note = sg.crop_front_view(_jpeg(_sheet()))
        self.assertEqual(note["status"], "CROPPED_FRONT_VIEW")
        with Image.open(io.BytesIO(data)) as crop:
            self.assertLess(crop.size[1], 360)
        self.assertEqual(sg.crop_front_view(b"not an image")[1]["status"], "SKIPPED_UNDECODABLE")

    def test_crop_requested_by_retry_flag_or_sheet_redo(self):
        self.assertTrue(sg.crop_requested({"h3_reference_sheet_crop": True}))
        self.assertTrue(sg.crop_requested({"h3_final_fix": {"kinds": ["REFERENCE_SHEET_LEAK"], "sentence": "x"}}))
        self.assertFalse(sg.crop_requested({"h3_final_fix": {"kinds": ["BURNED_TEXT"], "sentence": "x"}}))
        self.assertFalse(sg.crop_requested({}))
        self.assertTrue(sg.is_sheet_path("plates/E02_CHAR-SAIN-BAUER__MULTIVIEW_REFERENCE_SHEET_ab12.png"))
        self.assertEqual(sg.unit_sheets({"reference_images": ["a/kf.png", "p/X__MULTIVIEW_REFERENCE_SHEET_1.png"]}),
                         [Path("p/X__MULTIVIEW_REFERENCE_SHEET_1.png")])

    def test_detect_leak_on_a_drawn_sheet_and_not_on_a_performance_shot(self):
        import cv2
        sheet = cv2.cvtColor(np.array(_sheet()), cv2.COLOR_RGB2BGR)
        rng = np.random.default_rng(3)
        scene = cv2.GaussianBlur(rng.integers(0, 255, (1280, 720, 3), dtype=np.uint8), (31, 31), 9)
        cv2.rectangle(scene, (250, 500), (470, 1280), (60, 40, 30), -1)   # one person standing in a room
        cv2.circle(scene, (360, 430), 70, (180, 200, 230), -1)
        leak = scene.copy()
        pasted = cv2.convertScaleAbs(cv2.resize(sheet, (612, 918)), alpha=1.1, beta=10)
        leak[150:1068, 54:666] = cv2.GaussianBlur(pasted, (7, 7), 2)
        with tempfile.TemporaryDirectory() as d:
            plate = Path(d) / "X__MULTIVIEW_REFERENCE_SHEET_1.png"
            cv2.imwrite(str(plate), sheet)
            got = sg.detect_leak(Path(d) / "v.mp4", [plate], frames=lambda _v, _f: [(0.25, leak), (0.75, leak)])
            self.assertEqual(got["status"], "LEAK", got)
            self.assertEqual(got["leak_frames"], 2)
            got = sg.detect_leak(Path(d) / "v.mp4", [plate], frames=lambda _v, _f: [(0.25, scene), (0.75, scene)])
            self.assertEqual(got["status"], "CLEAN", got)
            self.assertEqual(sg.detect_leak(Path(d) / "v.mp4", [])["status"], "NO_SHEET")
            bad = sg.detect_leak(Path(d) / "v.mp4", [plate], frames=lambda _v, _f: (_ for _ in ()).throw(OSError()))
            self.assertEqual(bad["status"], "FAIL_OPEN")


class SubmitterSheetCropTest(unittest.TestCase):
    def test_sheet_refs_are_sent_as_front_view_crops_only_when_asked(self):
        from tools import submit_giggle_video_manifest_v2 as sub
        sent: list[tuple[str, bytes]] = []

        def upload(data, *, file_name, upload_path, mime):
            sent.append((file_name, data))
            return {"url": f"https://x/{file_name}", "sha256": "s"}

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            first = tmp / "kf.png"
            Image.new("RGB", (90, 160), (10, 20, 30)).save(first)
            sheet = tmp / "E02_CHAR-SAIN__MULTIVIEW_REFERENCE_SHEET_ab.png"
            _sheet().save(sheet)
            base = {"task_key": "E04-VU-007", "reference_images": [str(first), str(sheet)]}
            with mock.patch.object(sub.hopsapi, "upload_bytes", upload), \
                    mock.patch("tools.giggle_api_client._compressed_reference_bytes",
                               lambda p: (Path(p).read_bytes(), {})):
                _imgs, _aud, notes = sub._hopsapi_reference_uploads(dict(base))
                self.assertNotIn("reference_sheet_crop", notes[1])
                self.assertEqual(sent[1][1], sheet.read_bytes())
                sent.clear()
                _imgs, _aud, notes = sub._hopsapi_reference_uploads({**base, "h3_reference_sheet_crop": True,
                                                                    "h3_burn_retry": 1})
                self.assertEqual(notes[1]["reference_sheet_crop"]["status"], "CROPPED_FRONT_VIEW")
                with Image.open(io.BytesIO(sent[1][1])) as crop:
                    self.assertLess(crop.size[1], 360)
                self.assertNotIn("reference_sheet_crop", notes[0])          # @Image1 is never cropped


class BurnRetrySheetTest(unittest.TestCase):
    def test_a_leak_is_never_clean(self):
        clean = {"status": "CLEAN", "burned_frames": 0, "frames_sampled": 18}
        got = br.combine_sheet_leak(clean, {"status": "LEAK", "leak_frames": 7, "best_score": 0.8})
        self.assertEqual((got["status"], got["burned_frames"], got[br.SHEET_LEAK_FLAG]), ("BURNED", 7, True))
        self.assertEqual(br.combine_sheet_leak(clean, {"status": "CLEAN", "leak_frames": 0})["status"], "CLEAN")
        self.assertEqual(br.combine_sheet_leak(clean, None), clean)
        self.assertEqual(br.combine_sheet_leak({"status": "FAIL_OPEN"}, {"status": "LEAK", "leak_frames": 3})["status"],
                         "BURNED")
        plan = br.plan({}, got, retry_max=2, headroom=100, cost=10)
        self.assertEqual(plan["action"], "RETRY")

    def test_sheet_retry_sentences_round_trip_and_stay_plain(self):
        base = "prompt body\n"
        for index in (1, 2):
            text = br.apply_retry_sentence(base, index, sheet=True)
            self.assertIn(br.SHEET_RETRY_SENTENCES[index], text)
            self.assertEqual(br.strip_retry_sentence(text), (base, index))
            self.assertNotRegex(br.SHEET_RETRY_SENTENCES[index], r"\d|[A-Z]{3,}")
        self.assertEqual(br.apply_retry_sentence(base, 1), base.rstrip("\n") + "\n" + br.RETRY_SENTENCES[1] + "\n")
        self.assertTrue(br.sheet_retry({"attempts": [{"retry": 1, br.SHEET_LEAK_FLAG: True}]}))
        self.assertFalse(br.sheet_retry({"attempts": [{"retry": 1}]}))

    def test_renderer_uses_the_sheet_sentence_on_a_sheet_retry(self):
        unit = {"h3_burn_retry": 1, "h3_reference_sheet_crop": True}
        with mock.patch.object(h3, "validate_provider_prompt_boundary", lambda *a, **k: {"failures": []}), \
                mock.patch.object(h3, "validate_h3_provider_text_boundary", lambda *a, **k: {"failures": []}), \
                mock.patch.object(h3, "measure_prompt", lambda *a, **k: {}):
            text, receipt = h3._with_burn_retry(unit, {"unit_id": "U"}, "body\n", {})
        self.assertIn(br.SHEET_RETRY_SENTENCES[1], text)
        self.assertTrue(receipt["h3_burn_retry"]["reference_sheet_crop"])

    def test_residual_band_only_in_the_subtitle_band(self):
        hits = [{"t": 1.0, "text": "素敵ですわ", "y_centre": 0.84, "glyph_px_at_720": 56}]
        band = br.residual_text_band(hits)
        self.assertTrue(band["y0"] < 0.84 < band["y1"])
        self.assertIsNone(br.residual_text_band([{"y_centre": 0.3, "glyph_px_at_720": 50}]))
        self.assertIsNone(br.residual_text_band([]))

    def test_compile_carries_the_sheet_crop_flag(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "reports").mkdir()
            (out / "reports" / "E04_S6_WAVE_STATE.json").write_text(json.dumps({"s6_burn_retry": {
                "E04-VU-007": {"attempts": [{"retry": 1, "reference_sheet_leak": True}]},
                "E04-VU-004": {"attempts": [{"retry": 1}]}}}))
            self.assertEqual(bnp.s6_sheet_retry_units(out, "E04"), {"E04-VU-007"})


class S6SheetLeakWaveTest(unittest.TestCase):
    def test_sheet_leak_take_is_retried_with_the_crop_and_resolves(self):
        leaks = {"A1-take1"}

        def sheet_check(_ctx, _uid, clip):
            return {"status": "LEAK" if Path(clip).read_text() in leaks else "CLEAN", "leak_frames": 6,
                    "best_score": 0.8}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            with _Harness(Path(tmp), CHAIN, {}) as h, mock.patch.object(P, "s6_sheet_leak_check", sheet_check), \
                    mock.patch.object(P, "kb_events", lambda *_a, **_k: {"status": "OK"}):
                h.run()
                self.assertEqual(h.provider.posts, ["A1", "A1", "A2"])
                rec = h.state()["s6_burn_retry"]["A1"]
                self.assertEqual(rec["status"], "RESOLVED")
                self.assertTrue(rec["attempts"][0][br.SHEET_LEAK_FLAG])
                self.assertIn("reference_sheet_leak=1", "\n".join(h.said))
                self.assertEqual(bnp.s6_sheet_retry_units(h.preprod, "E99"), {"A1"})

    def test_unresolved_burn_in_the_subtitle_band_is_recorded_for_s7_and_the_round(self):
        def detect(clip, **_kw):
            content = Path(clip).read_text()
            frames = {"A1-take1": 8, "A1-take2": 8, "A1-take3": 2}.get(content, 0)
            return {"status": "BURNED" if frames else "CLEAN", "frames_sampled": 18, "burned_frames": frames,
                    "longest_run": frames, "elapsed_ms": 1.0,
                    "hits": [{"t": 0.5, "text": "素敵ですわ", "y_centre": 0.84, "glyph_px_at_720": 56}] if frames else []}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            with _Harness(Path(tmp), CHAIN, {}) as h, mock.patch.object(br, "detect", detect):
                h.ctx.p.assembly = Path(tmp) / "asm"
                h.ctx.p.assembly.mkdir()
                h.run(passes=8)
                rec = h.state()["s6_burn_retry"]["A1"]
                self.assertEqual(rec["status"], "UNRESOLVED")
                self.assertTrue(rec["residual_text_band"]["y0"] < 0.84)
                self.assertIn("subtitle_band_text=", "\n".join(h.said))
                path = P.s7_residual_burn_bands(h.ctx)
                self.assertEqual(list(json.loads(path.read_text())["units"]), ["A1"])
                measured = qadc.measure(shots=[], s6_wave_state_path=h.reports / "E99_S6_WAVE_STATE.json")
                row = measured["s6_burn_unresolved"]["units"][0]
                self.assertTrue(row["residual_in_subtitle_band"])
                record = qadc.build_record({}, measured, episode="E99")
                found = ffr.collect_findings({}, record)
                self.assertEqual([(f["unit_id"], f["kind_hint"], f["severity"]) for f in found],
                                 [("A1", "BURNED_TEXT", "P1")])


class CaptionAboveBurnedLineTest(unittest.TestCase):
    def test_caption_moves_above_the_burned_line_of_its_unit_only(self):
        clips = [{"start": 10.0, "duration": 3.5, "metadata": {"source_id": "E04-VU-004"}},
                 {"start": 13.5, "duration": 3.0, "metadata": {"source_id": "E04-VU-005"}}]
        rects = bbs.avoid_rects({"E04-VU-004": {"y0": 0.81, "y1": 0.87}}, clips, 720, 1280)
        self.assertEqual(len(rects), 1)
        default_y = 1280 - 170 - 78
        y = bbs.caption_y_above(default_y, 78, 11.0, 12.5, rects, 1280)
        self.assertLessEqual(y + 78, rects[0][2][1])            # entirely above the burned line
        self.assertGreaterEqual(y, 640)                          # never above mid-frame
        self.assertEqual(bbs.caption_y_above(default_y, 78, 14.0, 15.0, rects, 1280), default_y)
        far = bbs.avoid_rects({"E04-VU-004": {"y0": 0.60, "y1": 0.64}}, clips, 720, 1280)
        self.assertEqual(bbs.caption_y_above(default_y, 78, 11.0, 12.5, far, 1280), default_y)


class Q2SubtitleBandTest(unittest.TestCase):
    def test_band_text_counts_whatever_the_forbidden_list(self):
        self.assertTrue(q2.subtitle_band_text({"text": "素，！", "confidence": 0.887, "y_centre": 0.84}))
        self.assertFalse(q2.subtitle_band_text({"text": "素", "y_centre": 0.84}))
        self.assertFalse(q2.subtitle_band_text({"text": "素敵", "y_centre": 0.30}))
        self.assertFalse(q2.subtitle_band_text({"text": "素敵"}))            # an old report without positions
        self.assertFalse(q2.subtitle_band_text({"text": "，！", "y_centre": 0.84}))

    def test_period_verification_fails_on_band_text(self):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / "ocr.json"
            report.write_text(json.dumps({"recognitions": [
                {"text": "素，！", "confidence": 0.887, "forbidden_tokens": [], "y_centre": 0.84}],
                "critical_text_failures": 0, "latin_chars": 0, "status": "PASS"}))
            item = {"answers": {}, "observed": {"observed_text_strings": ["素，！"]}}
            ver, failures = q2.build_period_verification(item, {}, [{"report_path": str(report), "exit_code": 0,
                                                                     "frame": "f1.png"}], [])
            self.assertTrue(any("OCR_BURNED_TEXT_IN_SUBTITLE_BAND:素，！" in f for f in failures), failures)
            self.assertEqual(ver["decision"], "FAIL")

    def test_ocr_audit_records_the_box_position(self):
        import still_image_ocr_audit as ocr
        got = ocr._box_fields([[100, 1050], [620, 1050], [620, 1100], [100, 1100]], 720, 1280)
        self.assertEqual(got["y_centre"], round(1075 / 1280, 4))
        self.assertEqual(ocr._box_fields(None, 720, 1280), {})


class AnimeQ2AndGeminiGuidanceTest(unittest.TestCase):
    def test_anime_q2_asks_the_sheet_question_and_a_fail_fails_identity(self):
        questionnaire = rs.style_questionnaire("video_q2", {}, "anime")
        self.assertIn(rs.SHEET_LEAK_QUESTION, questionnaire)
        self.assertNotIn(rs.SHEET_LEAK_QUESTION, rs.style_questionnaire("keyframe", {}, "anime"))
        self.assertNotIn(rs.SHEET_LEAK_QUESTION, rs.style_questionnaire("video_q2", {}, "live_action"))
        item = {"answers": {rs.VLM_IDENTITY_QUESTION: "PASS", rs.SHEET_LEAK_QUESTION: "FAIL"}, "observed": {}}
        ver, failures, _ = q2.anime_identity_verification(item, questionnaire, "sha", ["CHAR-SAIN"])
        self.assertIn(rs.SHEET_LEAK_QUESTION, failures)
        item["answers"].pop(rs.SHEET_LEAK_QUESTION)              # a request built before the question: not counted
        ver, failures, _ = q2.anime_identity_verification(item, questionnaire, "sha", ["CHAR-SAIN"])
        self.assertNotIn(rs.SHEET_LEAK_QUESTION, failures)

    def test_gemini_pass_a_names_the_sheet_leak_and_stacked_lines(self):
        self.assertEqual(grp.CLASS_TEXT["QA-REFERENCE-SHEET-LEAK"][0], "A")
        prompt = grp.build_pass_prompt("A", duration=180.0, anime=True)
        self.assertIn("QA-REFERENCE-SHEET-LEAK", prompt)
        self.assertIn("三视图", prompt)
        self.assertIn("P0", grp.CLASS_TEXT["QA-REFERENCE-SHEET-LEAK"][1])
        self.assertIn("上下两行相同", grp.CLASS_TEXT["QA-BURNED-TEXT"][1])
        self.assertIn("QA-BURNED-TEXT", grp.CLASS_TEXT["QA-SUBTITLE-WRAP"][1])
        self.assertNotIn("QA-REFERENCE-SHEET-LEAK", grp.build_pass_prompt("D", duration=180.0))

    def test_identity_sheet_clause_forbids_showing_the_sheet(self):
        clause = h3.reference_sheet_clause("Sain")
        self.assertIn("never show the sheet, its turnaround views, a face close-up inset or extra copies of Sain",
                      clause)
        self.assertNotRegex(clause, r"\d")


if __name__ == "__main__":
    unittest.main()
