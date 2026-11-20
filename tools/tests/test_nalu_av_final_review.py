"""Video-native final review + local A/V evidence pack + S6 letterbox redo (line owner 2026-11-19, benchmark
《摄政王她又来找茬了》 E17-E19).

Offline: no network (Gemini is a fake ``post``), OCR / InsightFace replaced by fakes, synthetic frames and audio."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT), str(ROOT / "skills/nalu-claude-code/scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import av_evidence_pack as avp  # noqa: E402
import gemini_video_review as gvr  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
import q2_auto_redo as redo  # noqa: E402

W, H = 72, 128


def frame(*, letterbox: float = 0.0, value: int = 120) -> np.ndarray:
    img = np.random.default_rng(1).integers(value - 40, value + 40, size=(H, W, 3)).astype(np.uint8)
    band = int(letterbox * H)
    if band:
        img[:band] = 0
        img[H - band:] = 0
    return img


class LetterboxTest(unittest.TestCase):
    def test_bands_and_verdict(self):
        boxed = avp.letterbox_bands(frame(letterbox=0.34).mean(2))
        self.assertGreater(boxed["top"], 0.3)
        self.assertEqual(avp.letterbox_frame(boxed), "LETTERBOX")
        clean = avp.letterbox_bands(frame().mean(2))
        self.assertIsNone(avp.letterbox_frame(clean))
        verdict = avp.letterbox_verdict([boxed] * 5 + [clean], W, H)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertAlmostEqual(verdict["content_aspect"], W / (H * (1 - 2 * 0.336)), delta=0.1)
        self.assertEqual(avp.letterbox_verdict([clean] * 6, W, H)["status"], "PASS")

    def test_a_caption_inside_the_bottom_band_is_tolerated(self):
        img = frame(letterbox=0.34)
        img[int(0.80 * H):int(0.84 * H), 20:50] = 255   # our caption on the black band
        self.assertEqual(avp.letterbox_frame(avp.letterbox_bands(img.mean(2))), "LETTERBOX")

    def test_a_dark_scene_with_unsteady_bands_passes(self):
        samples = [avp.letterbox_bands(frame(letterbox=f).mean(2)) for f in (0.05, 0.15, 0.25, 0.1, 0.2)]
        self.assertEqual(avp.letterbox_verdict(samples, W, H)["status"], "PASS")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
    def test_clip_check_on_decoded_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            portrait = Path(tmp) / "p.mp4"
            boxed = Path(tmp) / "b.mp4"
            landscape = Path(tmp) / "l.mp4"
            base = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
            subprocess.run(base + ["testsrc2=size=144x256:rate=8:duration=2", "-pix_fmt", "yuv420p", str(portrait)],
                           check=True)
            subprocess.run(base + ["testsrc2=size=144x81:rate=8:duration=2", "-vf",
                                   "pad=144:256:0:(oh-ih)/2:black", "-pix_fmt", "yuv420p", str(boxed)], check=True)
            subprocess.run(base + ["testsrc2=size=256x144:rate=8:duration=2", "-pix_fmt", "yuv420p", str(landscape)],
                           check=True)
            self.assertEqual(avp.clip_letterbox(portrait)["status"], "PASS")
            out = avp.clip_letterbox(boxed)
            self.assertEqual(out["status"], "FAIL")
            self.assertIn("LETTERBOX_BANDS", out["failure"])
            self.assertIn("DECODED_ASPECT_NOT_9_16", avp.clip_letterbox(landscape)["failure"])
        self.assertEqual(avp.clip_letterbox(Path("/nonexistent.mp4"))["status"], "ERROR")


class TextTest(unittest.TestCase):
    def test_caption_vs_burned_classification(self):
        ours = (0.06, 0.778, 0.94, 0.813)          # 45 px of 1280 in our band
        burned = (0.13, 0.68, 0.86, 0.73)          # 64 px glyphs above it
        self.assertEqual(avp.classify_box(10, "这是哪儿来的", 0.98, ours, 100), "OURS")
        self.assertEqual(avp.classify_box(10, "这是哪儿来的", 0.98, burned, 100), "BURNED")
        self.assertEqual(avp.classify_box(10, "这昪忢", 0.70, burned, 100), "BURNED_LOW_CONFIDENCE")
        self.assertEqual(avp.classify_box(1.0, "剧名", 0.99, (0.2, 0.3, 0.8, 0.38), 100), "TITLE_CARD")
        self.assertEqual(avp.classify_box(98.0, "下集", 0.99, burned, 100), "END_CARD")
        self.assertEqual(avp.classify_box(10, "店", 0.99, (0.1, 0.1, 0.12, 0.12), 100), "SCENE_TEXT")

    def test_runs_and_garbled(self):
        hits = [(5.0, "快来啊姑娘们", 0.7, 0.05), (5.25, "快来啊姑娘们", 0.7, 0.05),
                (9.0, "手枆他道", 0.7, 0.05), (9.25, "手枆他道", 0.7, 0.05)]
        runs = avp.burned_runs(hits, "快来啊姑娘们，替荣妈妈好生照顾着这位小郎君")
        self.assertEqual(len(runs), 2)
        self.assertNotIn("garbled", runs[0])
        self.assertTrue(runs[1]["garbled"])
        self.assertEqual(runs[1]["garbled_window"], [9.0, 9.5])
        low = avp.burned_runs([(3.0, avp.LOWCONF_MARK + "这是悬的", 0.7, 0.05)], "这是的")
        self.assertTrue(low[0]["garbled"])

    def test_lone_short_row_under_a_one_row_caption(self):
        gray = np.full((1280, 720), 90, np.float64)
        gray[1058:1090, 356:364] = 255          # the lone 「！」 stroke
        gray[1054:1094, 352:368][gray[1054:1094, 352:368] < 255] = 0   # its black outline
        row = (46 / 720, 996 / 1280, 674 / 720, 1041 / 1280)
        self.assertIsNotNone(avp.lone_row_pixels(gray, [row]))
        self.assertIsNone(avp.lone_row_pixels(gray, [row, row]))
        bright = np.full((1280, 720), 230, np.float64)   # a bright robe, no outline: not a caption row
        self.assertIsNone(avp.lone_row_pixels(bright, [row]))


class AudioTest(unittest.TestCase):
    def test_tail_gap_rule(self):
        sr, n = avp.SR, avp.SR * 6
        t = np.arange(n) / sr
        x = 0.002 * np.random.default_rng(0).standard_normal(n).astype(np.float32)
        voice = (np.sin(2 * np.pi * 220 * t) + 0.5 * np.sin(2 * np.pi * 660 * t)).astype(np.float32) * 0.3
        x[int(1.0 * sr):int(3.0 * sr)] += voice[int(1.0 * sr):int(3.0 * sr)]   # line runs into the cut at 3.0
        x[int(3.2 * sr):int(4.5 * sr)] += voice[int(3.2 * sr):int(4.5 * sr)]   # line ends 0.5 s before the cut at 5.0
        rows = [{"start": 1.0, "end": 3.0, "text": "", "words": []}, {"start": 3.2, "end": 4.5, "text": "", "words": []}]
        out = avp.tail_gaps(x, [3.0, 5.0], rows)
        cuts = {r["cut"]: r for r in out["suspects"]}
        self.assertIn(3.0, cuts)
        self.assertNotIn(5.0, cuts)

    def test_music_fragment_heuristic(self):
        sr = avp.SR
        rng = np.random.default_rng(2)
        x = 0.05 * rng.standard_normal(sr * 20).astype(np.float32)
        t = np.arange(sr * 4) / sr
        chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 440.0, 880.0)).astype(np.float32) * 0.3
        x[8 * sr:12 * sr] += chord          # one shot of music, hard in / hard out on cuts
        power, freqs = avp.stft_power(x)
        out = avp.bgm_heuristic(power, freqs, [4.0, 8.0, 12.0, 16.0], 20.0)
        self.assertEqual([(s["start"], s["end"]) for s in out["suspects"]], [(8.0, 12.0)])
        self.assertEqual(out["suspects"][0]["reasons"], ["MUSIC_STARTS_AND_STOPS_ON_CUTS"])


class FacesTest(unittest.TestCase):
    def test_clusters_and_same_frame_lookalike(self):
        a, b, c = [1.0, 0.0, 0.0], [0.85, 0.53, 0.0], [0.0, 0.0, 1.0]
        faces = [{"t": float(i), "bbox": [0, 0, 50, 50], "emb": a} for i in range(4)]
        faces += [{"t": 10.0 + i, "bbox": [0, 0, 50, 50], "emb": c} for i in range(3)]
        faces += [{"t": 20.0 + i * 0.5, "bbox": [60, 0, 110, 50], "emb": e} for i in range(3) for e in (a, b)]
        out = avp.lookalike_analysis(faces)
        kinds = [s["kind"] for s in out["suspects"]]
        self.assertIn("TWO_SIMILAR_FACES_IN_ONE_FRAME", kinds)
        same = [s for s in out["suspects"] if s["kind"] == "TWO_SIMILAR_FACES_IN_ONE_FRAME"][0]
        self.assertEqual((same["start"], same["end"]), (20.0, 21.0))
        self.assertGreaterEqual(len(out["clusters"]), 2)


class BuildTest(unittest.TestCase):
    def test_build_with_injected_media(self):
        frames = [(i / 4.0, frame(letterbox=0.34 if 8 <= i < 16 else 0.0)) for i in range(24)]

        def ocr(img):
            return [([[10, 85], [60, 85], [60, 93], [10, 93]], "快来啊姑娘们", 0.95)]

        audio = 0.01 * np.random.default_rng(3).standard_normal(avp.SR * 6).astype(np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            pack = avp.build(Path(tmp) / "x.mp4", shots=[{"end_seconds": 2.0}, {"end_seconds": 4.0},
                                                          {"end_seconds": 20.0}],
                             asr=[{"start": 0.5, "end": 1.9, "text": "快来啊姑娘们"}], ocr_fn=ocr, face_fn=None,
                             render_style="anime", audio=audio, frames=frames,
                             info={"width": W, "height": H, "duration": 20.0}, episode="E05", out_dir=Path(tmp))
        self.assertEqual(pack["schema"], avp.SCHEMA)
        self.assertEqual(pack["letterbox"]["shots"][0]["start"], 2.0)
        self.assertTrue(pack["burned_text"]["runs"])
        self.assertEqual(pack["lookalike_cast"]["status"], "NOT_APPLICABLE")
        self.assertIn("letterbox_shots", pack["summary"])
        self.assertNotIn("errors", pack)

    def test_build_refuses_undecodable_media(self):
        with self.assertRaises(ValueError):
            avp.build(Path("/x.mp4"), info={"width": 0, "height": 0, "duration": 0.0})


def _fake_request(root: Path, *, duration: float = 85.0) -> Path:
    video = root / "E19_final_9x16.mp4"
    video.write_bytes(b"final-video")
    import hashlib
    sha = hashlib.sha256(b"final-video").hexdigest()
    pack = root / "E19_AV_EVIDENCE_PACK.json"
    pack.write_text(json.dumps({"summary": {"tail_cut_suspects": [{"cut": 22.71, "gap_s": 0.0, "level_db": 16.5}],
                                            "bgm_suspects": [{"window": [10.75, 13.75], "reasons": ["X"]}],
                                            "letterbox_shots": [], "burned_text_runs": []}}), encoding="utf-8")
    req = root / "final_audience_request.json"
    req.write_text(json.dumps({"episode": "E19", "media": {"path": str(video), "sha256": sha},
                               "objective_summary": {"duration_seconds": duration},
                               "evidence": {"av_evidence_pack": {"path": str(pack),
                                                                 "sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}},
                               "qa_defect_checklist_request": {"measurements": {}}}), encoding="utf-8")
    return req


ANSWER = {"findings": [{"class": "QA-BURNED-TEXT", "start": 21.0, "end": 22.7, "severity": "P1",
                        "description": "大号烧字『毕竟我们不熟』", "evidence": "字幕上方多一行大字"},
                       {"class": "LETTERBOX", "start": 70.2, "end": 74.6, "severity": "P0", "description": "横版"},
                       {"class": "C2", "start": "x"}],
          "suspect_checks": [{"id": "S1", "decision": "CONFIRMED", "reason": "『熟』被切"},
                             {"id": "S9", "decision": "CONFIRMED"}],
          "verdict": "REJECT_RECUT"}


def _post_ok(captured: dict):
    def post(url, body, headers, timeout):
        captured.update(url=url, body=json.loads(body), headers=headers)
        payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER, ensure_ascii=False)}]}}],
                   "usageMetadata": {"promptTokenCount": 15000, "candidatesTokenCount": 500,
                                     "thoughtsTokenCount": 1200, "totalTokenCount": 16700}}
        return 200, json.dumps(payload).encode()
    return post


def _fake_transcode(video: Path, out: Path) -> Path:
    out.write_bytes(b"small-video")
    return out


class GeminiReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {"HOPSAPI_API_KEY": "sk-test-SECRET", "NALU_ENGINE_ROOT": str(self.root),
                    "NALU_RUNTIME_ROOT": str(self.root), "NALU_GEMINI_REVIEW_MODE": "single"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok_run_records_findings_usage_and_cost_without_the_key(self):
        req = _fake_request(self.root)
        out = self.root / "final_reviewer" / "gemini_review.json"
        captured: dict = {}
        record = gvr.run(request_path=req, out=out, post=_post_ok(captured), transcoder=_fake_transcode,
                         environ=self.env)
        self.assertEqual(record["status"], "OK")
        self.assertTrue(captured["url"].endswith("/models/gemini-3.8-flash:generateContent"))
        part = captured["body"]["contents"][0]["parts"][0]
        self.assertEqual(part["video_metadata"], {"fps": 2.0})
        self.assertEqual(part["inline_data"]["mime_type"], "video/mp4")
        prompt = captured["body"]["contents"][0]["parts"][1]["text"]
        for item in qa.ITEM_IDS + ("LETTERBOX", "LOOK-DRIFT", "OTHER"):
            self.assertIn(item, prompt)
        self.assertIn("22.71", prompt)            # the measured C2 suspect to confirm or dismiss
        self.assertIn("S2", prompt)               # the C6 suspect id
        self.assertEqual([f["id"] for f in record["findings"]], ["G1", "G2"])
        self.assertEqual(record["findings"][1]["item"], "LETTERBOX")
        self.assertEqual(record["cost_credits"], round(15000 * 50.25e-6 + 1700 * 251.25e-6, 3))
        decisions = {c["id"]: c["decision"] for c in record["suspect_checks"]}
        self.assertEqual(decisions, {"S1": "CONFIRMED", "S2": "NOT_ANSWERED"})
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("sk-test-SECRET", text)
        self.assertEqual(json.loads(text)["request_sha256"], gvr._sha(req))

    def test_failures_skip_and_never_raise(self):
        req = _fake_request(self.root)
        out = self.root / "g.json"
        no_key = gvr.run(request_path=req, out=out, post=_post_ok({}), transcoder=_fake_transcode,
                         environ={"NALU_ENGINE_ROOT": str(self.root), "NALU_RUNTIME_ROOT": str(self.root)})
        self.assertEqual((no_key["status"], no_key["reason"]), ("SKIPPED", "NO_HOPSAPI_KEY"))

        def post_500(url, body, headers, timeout):
            return 500, b'{"error": "upstream sk-test-SECRET"}'
        err = gvr.run(request_path=req, out=out, post=post_500, transcoder=_fake_transcode, environ=self.env)
        self.assertEqual((err["status"], err["reason"]), ("ERROR", "HTTP_500"))
        self.assertNotIn("sk-test-SECRET", out.read_text(encoding="utf-8"))

        def post_garbage(url, body, headers, timeout):
            return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}).encode()
        bad = gvr.run(request_path=req, out=out, post=post_garbage, transcoder=_fake_transcode, environ=self.env)
        self.assertTrue(bad["reason"].startswith("UNPARSABLE_ANSWER"))

        def boom(video, out_path):
            raise RuntimeError("ffmpeg died")
        broken = gvr.run(request_path=req, out=out, post=_post_ok({}), transcoder=boom, environ=self.env)
        self.assertEqual(broken["status"], "ERROR")
        off = gvr.run(request_path=req, out=out, environ={**self.env, "NALU_GEMINI_REVIEW": "off"})
        self.assertEqual(off["reason"], "DISABLED_BY_NALU_GEMINI_REVIEW")

    def test_budget_lowers_fps_then_skips(self):
        self.assertEqual(gvr.choose_fps("gemini-3.8-flash", 85, 3000, 1.5), 2.0)
        self.assertLessEqual(gvr.estimate_credits("gemini-3.8-flash", 100, 3000, 2.0), 1.5)
        self.assertEqual(gvr.choose_fps("gemini-3.8-flash", 140, 3000, 1.5), 1.5)
        self.assertIsNone(gvr.choose_fps("gemini-3.8-flash", 400, 3000, 1.5))
        req = _fake_request(self.root, duration=400)
        record = gvr.run(request_path=req, out=self.root / "g.json", post=_post_ok({}), transcoder=_fake_transcode,
                         environ=self.env)
        self.assertEqual(record["reason"], "ESTIMATE_OVER_BUDGET")

    def test_key_resolution_order(self):
        (self.root / ".env").write_text("export HOPSAPI_API_KEY='sk-dotenv'\n")
        key, source = gvr.resolve_key({"NALU_ENGINE_ROOT": str(self.root), "NALU_RUNTIME_ROOT": str(self.root)})
        self.assertEqual((key, source), ("sk-dotenv", "ENGINE_DOTENV:HOPSAPI_API_KEY"))
        (self.root / ".env").unlink()
        cred = self.root / "credentials"
        cred.mkdir()
        (cred / "llm_provider.json").write_text(json.dumps({"base_url": "https://hopsapi.com/v1", "api_key": "sk-p"}))
        self.assertEqual(gvr.resolve_key({"NALU_ENGINE_ROOT": str(self.root), "NALU_RUNTIME_ROOT": str(self.root)})[0],
                         "sk-p")


class ChecklistFlowTest(unittest.TestCase):
    def test_pack_flags_and_gemini_verification_reach_the_record_and_s8(self):
        measurements = {"av_evidence_pack": {
            "burned_text_runs": [{"window": [21.0, 22.75], "text": "毕竟", "garbled": False}],
            "tail_cut_suspects": [{"cut": 22.71, "gap_s": 0.0, "level_db": 16.5}],
            "bgm_suspects": [{"window": [10.75, 13.75], "reasons": ["MUSIC_STARTS_AND_STOPS_ON_CUTS"]}],
            "bgm_source": "HEURISTIC_CHROMA_PEAKINESS",
            "wrap_suspects": [{"window": [4.25, 5.5], "reasons": ["PIXEL_LONE_SHORT_ROW"]}],
            "letterbox_shots": [{"window": [70.17, 74.62], "kind": "LETTERBOX"}],
            "lookalike": {"suspects": [{"kind": "TWO_SIMILAR_FACES_IN_ONE_FRAME", "start": 74.5, "end": 76.0,
                                        "cosine": 0.52}]}}}
        gemini = {"status": "OK", "model": "gemini-3.8-flash", "cost_credits": 1.2, "findings": [
            {"id": "G1", "item": "QA-BURNED-TEXT", "start": 21.0, "end": 22.7, "severity": "P1", "description": "烧字"},
            {"id": "G2", "item": "QA-OVERSIZED-MASK", "start": 40.0, "end": 41.0, "severity": "P2",
             "description": "遮罩"},
            {"id": "G3", "item": "LETTERBOX", "start": 70.2, "end": 74.6, "severity": "P0", "description": "横版"}],
            "suspect_checks": [{"id": "S1", "decision": "CONFIRMED", "suspect": {"at": 22.71}}]}
        block = {"items": {"QA-BURNED-TEXT": {"verdict": "DEFECT", "findings": [{"window": [21, 22.7], "note": "x"}]},
                           "QA-OVERSIZED-MASK": {"verdict": "PASS", "findings": []}},
                 "gemini_verification": [{"id": "G2", "decision": "DISMISSED", "reason": "那是景深虚化"},
                                         {"id": "G3", "decision": "CONFIRMED", "reason": "上下黑边"},
                                         {"id": "bogus"}]}
        parsed = qa.parse_block(block)
        self.assertEqual(parsed["status"], "OK")
        self.assertEqual(parsed["gemini_verification"]["G2"]["decision"], "DISMISSED")
        record = qa.build_record(parsed, measurements, episode="E19", gemini=gemini)
        items = record["items"]
        self.assertEqual(items["QA-DIALOGUE-TAIL-CUT"]["status"], "MEASURED_FLAG_UNREVIEWED")
        self.assertEqual(items["QA-BGM-DISCONTINUOUS"]["measured_flags"][0]["source"], "AV_PACK_AUDIO")
        self.assertEqual(items["QA-LOOKALIKE-CAST"]["measured_flags"][0]["window"], [74.5, 76.0])
        self.assertEqual(items["QA-BURNED-TEXT"]["gemini_findings"][0]["status"], "CONFIRMED")   # matched by time
        self.assertEqual(items["QA-OVERSIZED-MASK"]["gemini_findings"][0]["status"], "DISMISSED")
        self.assertEqual(record["video_review"]["counts"], {"CONFIRMED": 2, "DISMISSED": 1, "UNVERIFIED": 0})
        lines = "\n".join(qa.checkpoint_lines(record))
        self.assertIn("Video-native pass (gemini-3.8-flash", lines)
        self.assertIn("`G3` LETTERBOX", lines)
        self.assertNotIn("`G2`", lines)
        self.assertIn("Letterboxed / pillarboxed shots measured", lines)
        specs = {s["item_id"]: s for s in qa.event_specs(record)}
        self.assertEqual(specs["QA-BURNED-TEXT"]["evidence"]["detail"]["gemini_confirmed"], 1)

    def test_submit_reads_the_gemini_review_bound_to_the_request(self):
        from lines.nalu.runtime.tools import final_audience_review as review
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "claude_code" / "E05" / "final_reviewer" / "gemini_review.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"request_sha256": "b" * 64, "status": "OK", "model": "m", "findings": [
                {"id": "G1", "item": "QA-SUBTITLE-WRAP", "start": 5.0, "end": 5.5, "description": "孤立！"}]}))
            request = {"episode": "E05", "media": {"sha256": "a" * 64}, "objective_summary": {"duration_seconds": 30},
                       "qa_defect_checklist_request": {"measurements": {}}}
            with mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(root)}):
                out = review._record_qa_defects(request, "b" * 64, {"qa_defect_checklist": {"items": {}}},
                                                root / "final_qa" / "E05_REPORT.json")
                stale = review.gemini_review_for(request, "c" * 64)
            record = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
            self.assertEqual(record["video_review"]["findings"][0]["status"], "UNVERIFIED")
            self.assertIn("gemini_review_sha256", record["bindings"])
            self.assertEqual(stale, {})


class PrepareEvidenceTest(unittest.TestCase):
    def test_pack_is_sha_bound_and_handed_to_the_checklist(self):
        from lines.nalu.runtime.tools import final_audience_review as review
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "v.mp4"
            video.write_bytes(b"v")
            sheet = root / "E05_CAST_LINEUP.jpg"
            sheet.write_bytes(b"jpg")
            fake = {"schema": avp.SCHEMA, "summary": {"tail_cut_suspects": []},
                    "lookalike_cast": {"lineup_sheet": str(sheet)}}
            defect = {"measurements": {"bgm": {"runs": []}}}
            with mock.patch.object(avp, "probe", return_value={"width": 720, "height": 1280, "duration": 9.0}), \
                 mock.patch.object(avp, "build", return_value=fake) as build:
                rows = review.build_av_evidence_pack("E05", video=video, video_sha="a" * 64, shots=[], asr=[],
                                                     subtitle_report_path=None, out_dir=root, render_style=None,
                                                     defect_request=defect)
            self.assertEqual(build.call_args.kwargs["media_sha256"], "a" * 64)
            self.assertEqual(rows["av_evidence_pack"]["sha256"], review._sha(root / "E05_AV_EVIDENCE_PACK.json"))
            self.assertEqual(rows["cast_lineup_sheet"]["sha256"], review._sha(sheet))
            self.assertEqual(defect["measurements"]["av_evidence_pack"], {"tail_cut_suspects": []})
            request = {"media": {"path": str(video), "sha256": review._sha(video)}, "evidence": rows}
            self.assertEqual(review._verify_bound_evidence(request), [])
            (root / "E05_AV_EVIDENCE_PACK.json").write_text("{}")
            self.assertIn("evidence_missing_or_sha_changed:av_evidence_pack", review._verify_bound_evidence(request))
            with mock.patch.object(avp, "probe", return_value={"width": 0, "height": 0, "duration": 0.0}):
                self.assertEqual(review.build_av_evidence_pack("E05", video=video, video_sha="a", shots=[], asr=[],
                                                               subtitle_report_path=None, out_dir=root,
                                                               render_style=None, defect_request=None), {})
            with mock.patch.dict(os.environ, {"NALU_AV_EVIDENCE_PACK": "off"}):
                self.assertEqual(review.build_av_evidence_pack("E05", video=video, video_sha="a", shots=[], asr=[],
                                                               subtitle_report_path=None, out_dir=root,
                                                               render_style=None, defect_request=None), {})


class LauncherTest(unittest.TestCase):
    def test_prompt_version_and_gemini_step(self):
        import codex_production as cp
        self.assertEqual(cp.REVIEWER_PROMPT_VERSION.split()[0], "4")
        plain = cp.reviewer_prompt("E05", Path("/r.json"), Path("/a.json"), "pid", "submit")
        self.assertNotIn("gemini_verification", plain)
        self.assertIn("av_evidence_pack", plain)
        with_g = cp.reviewer_prompt("E05", Path("/r.json"), Path("/a.json"), "pid", "submit",
                                    gemini=Path("/d/gemini_review.json"))
        self.assertIn("/d/gemini_review.json", with_g)
        self.assertIn('"id": "G1"', with_g)
        self.assertIn("DISMISSED", with_g)
        from lines.nalu.runtime.tools import final_audience_review as review
        self.assertIn(cp.REVIEWER_MODEL_ID, review.ALLOWED_REVIEW_MODELS)

    def test_gemini_runs_once_per_request_and_never_blocks(self):
        import codex_production as cp
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "req.json"
            request.write_text("{}")
            d = root / "final_reviewer"
            d.mkdir()
            calls = []

            def fake_run(argv, **kwargs):
                calls.append(kwargs["env"].get("HOPSAPI_API_KEY"))
                out = Path(argv[argv.index("--out") + 1])
                out.write_text(json.dumps({"request_sha256": cp._file_sha(request), "status": "OK",
                                           "cost_credits": 1.2}))
                return subprocess.CompletedProcess(argv, 0)
            with mock.patch.object(cp, "roots", return_value=(root, root)), \
                 mock.patch.object(cp, "provider", return_value={"base_url": "https://hopsapi.com/v1",
                                                                 "api_key": "sk-line"}), \
                 mock.patch.object(cp.subprocess, "run", side_effect=fake_run):
                first = cp.run_gemini_review("E05", request, d, {"PATH": "/bin", cp.KEY_ENV: "sk-codex"})
                again = cp.run_gemini_review("E05", request, d, {"PATH": "/bin"})
            self.assertEqual(first["status"], "OK")
            self.assertTrue(again["reused"])
            self.assertEqual(calls, ["sk-line"])
            with mock.patch.object(cp, "roots", return_value=(root, root)), \
                 mock.patch.object(cp, "provider", return_value=None), \
                 mock.patch.object(cp.subprocess, "run", side_effect=OSError("no python")):
                request.write_text('{"x": 1}')
                self.assertEqual(cp.run_gemini_review("E05", request, d, {})["status"], "ERROR")


class LetterboxRedoTest(unittest.TestCase):
    def test_letterbox_is_redo_eligible_once_in_every_style(self):
        fail = {"status": "FAIL", "failure": "LETTERBOX:LETTERBOX_BANDS"}
        live = {"letterbox": fail, "face_count": {"status": "FAIL"}}
        anime = {"render_style": "anime", "letterbox": fail, "face_count": {"status": "FAIL"}}
        self.assertEqual(redo.objective_failures(live), ["letterbox", "face_count"])
        self.assertEqual(redo.objective_failures(anime), ["letterbox"])
        self.assertEqual(redo.objective_failures(live, technical_only=True), ["letterbox"])
        self.assertFalse(redo.needs_own_keyframe(["letterbox"]))
        decision = redo.plan({"VU-1": anime, "VU-2": {"letterbox": {"status": "PASS"}}}, {}, headroom=100,
                             unit_cost=lambda uid: 30, technical_only=True)
        self.assertEqual([r["unit_id"] for r in decision["selected"]], ["VU-1"])
        again = redo.plan({"VU-1": anime}, {"VU-1": {}}, headroom=100, unit_cost=lambda uid: 30)
        self.assertEqual(again["skipped"][0]["reason"], "ALREADY_REDONE_ONCE")

    def test_video_q2_prepare_hook_switch(self):
        import video_q2_builder as vq
        with mock.patch.dict(os.environ, {"NALU_LETTERBOX_CHECK": "off"}):
            self.assertIsNone(vq.clip_letterbox_check(Path("/x.mp4")))
        with mock.patch.object(avp, "clip_letterbox", return_value={"status": "FAIL"}):
            self.assertEqual(vq.clip_letterbox_check(Path("/x.mp4")), {"status": "FAIL"})


class StartFrameAspectTest(unittest.TestCase):
    def _png(self, size):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", size, (120, 80, 40)).save(buf, format="PNG")
        return buf.getvalue()

    def test_send_time_normalisation(self):
        import hopsapi_image_client as hic
        from PIL import Image
        data, note = hic.portrait_9_16_bytes(self._png((1024, 1536)))
        self.assertEqual(note["status"], "CROPPED")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (864, 1536))
        same, note = hic.portrait_9_16_bytes(self._png((864, 1536)))
        self.assertEqual(note["status"], "UNCHANGED")
        wide, note = hic.portrait_9_16_bytes(self._png((1536, 864)))
        self.assertEqual(note["status"], "NOT_PORTRAIT_SENT_AS_IS")

    def test_only_the_bound_start_frame_is_normalised(self):
        import tools.submit_giggle_video_manifest_v2 as submitter
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp) / "kf.png"
            sheet = Path(tmp) / "sheet.png"
            start.write_bytes(self._png((1024, 1536)))
            sheet.write_bytes(self._png((1024, 1536)))
            task = {"task_key": "E05-VU-001", "reference_images": [str(start), str(sheet)],
                    "start_frame_semantic_contract": {"reference_path": str(start)}}
            sent = []

            def upload(data, **kwargs):
                sent.append(data)
                return {"url": f"https://x/{len(sent)}", "sha256": "s"}
            with mock.patch.object(submitter.hopsapi, "upload_bytes", side_effect=upload):
                images, _audios, notes = submitter._hopsapi_reference_uploads(task)
        from PIL import Image
        self.assertEqual(Image.open(io.BytesIO(sent[0])).size, (864, 1536))
        self.assertEqual(Image.open(io.BytesIO(sent[1])).size, (1024, 1536))
        self.assertEqual(notes[0]["start_frame_aspect"]["status"], "CROPPED")
        self.assertNotIn("start_frame_aspect", notes[1])


if __name__ == "__main__":
    unittest.main()
