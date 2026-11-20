#!/usr/bin/env python3
"""Tail-frame burned-text clean (2026-11-19): H3 burns the spoken line into the clip and it lasts to the
last frame, which the engine reuses as the next unit's start-frame anchor.  Both tail extraction points
inpaint it before the frame is finalised.  No network, no provider, no credits (OCR mocked; one optional
real-RapidOCR check runs only when the engine is installed)."""
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

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "tools", REPO / "lines" / "nalu" / "runtime" / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - engine venv always has OpenCV
    cv2 = None

import tail_frame_text_clean as ttc  # noqa: E402

W, H = 720, 1280
TEXT_BOX = (200, 1000, 520, 1060)  # x0, y0, x1, y1 -> y 0.78-0.83, 60 px glyphs, centred


def _frame(path: Path, *, text: bool) -> None:
    img = np.full((H, W, 3), 90, dtype=np.uint8)
    img[:, :, 1] = np.linspace(40, 200, W, dtype=np.uint8)[None, :]
    if text:
        x0, y0, x1, y1 = TEXT_BOX
        cv2.putText(img, "HELLO", (x0 + 4, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 255), 6)
    cv2.imwrite(str(path), img)


def _mock_ocr(hits):
    """RapidOCR-shaped result; coordinates are given in full-frame pixels and shifted into the band crop."""
    band_top = int(round(H * ttc.BAND_Y0))

    def ocr(crop):
        assert crop.shape[0] == int(round(H * ttc.BAND_Y1)) - band_top
        out = []
        for (x0, y0, x1, y1), text, score in hits:
            out.append(([[x0, y0 - band_top], [x1, y0 - band_top], [x1, y1 - band_top], [x0, y1 - band_top]],
                        text, score))
        return out
    return ocr


BURN = _mock_ocr([(TEXT_BOX, "HELLO", 0.93)])


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class CleanHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.frame = self.dir / "E01-VU-002.png"
        self.orig, self.side = ttc.companion_paths(self.frame)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_in_band_is_inpainted_and_original_kept(self):
        _frame(self.frame, text=True)
        before = self.frame.read_bytes()
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, sidecar=self.side, ocr=BURN, env={})
        self.assertEqual(rep["status"], "CLEANED")
        self.assertTrue(rep["tail_text_cleaned"])
        self.assertEqual(len(rep["boxes"]), 1)
        self.assertEqual(self.orig.read_bytes(), before)
        self.assertNotEqual(self.frame.read_bytes(), before)
        side = json.loads(self.side.read_text(encoding="utf-8"))
        self.assertTrue(side["tail_text_cleaned"])
        self.assertEqual(side["boxes"][0]["text"], "HELLO")
        x0, y0, x1, y1 = TEXT_BOX
        cleaned = cv2.imread(str(self.frame))[y0:y1, x0:x1]
        self.assertLess(int(cleaned.max(axis=2).max()), 240, "white glyphs must be gone")
        top = cv2.imread(str(self.frame))[:600]
        self.assertTrue(np.array_equal(top, cv2.imread(str(self.orig))[:600]), "outside the mask untouched")

    def test_clean_frame_untouched(self):
        _frame(self.frame, text=False)
        before = self.frame.read_bytes()
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, sidecar=self.side,
                                   ocr=_mock_ocr([]), env={})
        self.assertEqual(rep["status"], "CLEAN")
        self.assertFalse(rep["tail_text_cleaned"])
        self.assertEqual(self.frame.read_bytes(), before)
        self.assertFalse(self.orig.exists())

    def test_false_positives_filtered(self):
        _frame(self.frame, text=False)
        before = self.frame.read_bytes()
        hits = [
            ((200, 1000, 520, 1020), "HELLO", 0.95),   # 20 px glyphs: set dressing, not an H3 burn
            ((200, 1000, 520, 1060), "HELLO", 0.40),   # low confidence
            ((200, 1000, 260, 1060), "A", 0.95),       # one character
            ((10, 1000, 200, 1060), "SHOP", 0.95),     # far off centre
            ((330, 800, 390, 1100), "对联文字", 0.95),   # vertical column
        ]
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, ocr=_mock_ocr(hits), env={})
        self.assertEqual(rep["status"], "CLEAN")
        self.assertEqual(self.frame.read_bytes(), before)

    def test_cjk_kana_hangul_count(self):
        _frame(self.frame, text=True)
        for text in ("山中凶禽", "こんにちは", "안녕하세요"):
            rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig,
                                       ocr=_mock_ocr([(TEXT_BOX, text, 0.9)]), env={})
            self.assertEqual(rep["status"], "CLEANED", text)

    def test_ocr_failure_fails_open(self):
        _frame(self.frame, text=True)
        before = self.frame.read_bytes()

        def boom(_img):
            raise RuntimeError("onnxruntime missing")
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, sidecar=self.side, ocr=boom, env={})
        self.assertEqual(rep["status"], "FAIL_OPEN")
        self.assertFalse(rep["tail_text_cleaned"])
        self.assertEqual(self.frame.read_bytes(), before)
        self.assertFalse(self.orig.exists())

    def test_unloadable_ocr_engine_fails_open(self):
        _frame(self.frame, text=True)
        before = self.frame.read_bytes()
        with mock.patch.dict(sys.modules, {"rapidocr_onnxruntime": None}), mock.patch.object(ttc, "_ENGINE", None):
            rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, env={})
        self.assertEqual(rep["status"], "FAIL_OPEN")
        self.assertEqual(self.frame.read_bytes(), before)

    def test_env_opt_out(self):
        _frame(self.frame, text=True)
        before = self.frame.read_bytes()
        ocr = mock.Mock(side_effect=AssertionError("OCR must not run when opted out"))
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, ocr=ocr, env={"NALU_TAIL_TEXT_CLEAN": "0"})
        self.assertEqual(rep["status"], "SKIPPED_OPT_OUT")
        self.assertEqual(self.frame.read_bytes(), before)
        ocr.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec("rapidocr_onnxruntime"), "RapidOCR not installed")
    def test_real_ocr_cleans_drawn_text(self):
        _frame(self.frame, text=True)
        rep = ttc.clean_tail_frame(self.frame, original_copy=self.orig, env={})
        self.assertEqual(rep["status"], "CLEANED", rep)
        rep2 = ttc.clean_tail_frame(self.frame, original_copy=self.dir / "again.orig.png", env={})
        self.assertEqual(rep2["status"], "CLEAN", rep2)


def _fake_ffmpeg(text: bool):
    def run(cmd, *args, **kwargs):
        _frame(Path(cmd[-1]), text=text)
        return SimpleNamespace(returncode=0)
    return run


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class CallSiteTests(unittest.TestCase):
    def test_pipeline_extract_real_final_frame_cleans_before_finalising(self):
        import nalu_pipeline as P
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "media").mkdir()
            (tmp / "media" / "E01-VU-001.mp4").write_bytes(b"fake mp4")
            ctx = SimpleNamespace(run_id="r1", p=SimpleNamespace(video_media=tmp / "media", preprod=tmp / "pre"))
            with mock.patch.object(P.subprocess, "run", _fake_ffmpeg(True)), \
                    mock.patch.object(P._media, "require_ffmpeg", lambda: "ffmpeg"), \
                    mock.patch.object(ttc, "_default_ocr", BURN), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_TEXT_CLEAN": "1"}):
                out = P.extract_real_final_frame(ctx, "E01-VU-001")
            dst = tmp / "pre" / "real_final_frames" / "E01-VU-001.png"
            self.assertEqual(out["status"], "EXTRACTED")
            self.assertTrue(out["tail_text_cleaned"])
            self.assertTrue((dst.parent / "E01-VU-001.orig.png").is_file())
            self.assertTrue(json.loads((dst.parent / "E01-VU-001.tail_text_clean.json").read_text())["tail_text_cleaned"])
            self.assertEqual(out["sha256"], P.sha256_file(dst))
            self.assertEqual(list(dst.parent.glob("*.part.png")), [])

    def test_pipeline_opt_out_keeps_frame(self):
        import nalu_pipeline as P
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "media").mkdir()
            (tmp / "media" / "E01-VU-001.mp4").write_bytes(b"fake mp4")
            ctx = SimpleNamespace(run_id="r1", p=SimpleNamespace(video_media=tmp / "media", preprod=tmp / "pre"))
            with mock.patch.object(P.subprocess, "run", _fake_ffmpeg(True)), \
                    mock.patch.object(P._media, "require_ffmpeg", lambda: "ffmpeg"), \
                    mock.patch.object(ttc, "_default_ocr", BURN), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_TEXT_CLEAN": "0"}):
                out = P.extract_real_final_frame(ctx, "E01-VU-001")
            self.assertEqual(out["status"], "EXTRACTED")
            self.assertFalse(out["tail_text_cleaned"])
            self.assertFalse((tmp / "pre" / "real_final_frames" / "E01-VU-001.orig.png").exists())

    def test_supervisor_bind_predecessor_tail_frame_cleans_before_binding(self):
        from tools import episode_parallel_batch_supervisor as S
        from tools import tail_frame_text_clean as tttc
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "E01-VU-001.mp4"
            src.write_bytes(b"fake mp4")
            dst = tmp / "tails" / "E01-VU-001_tail.png"
            task = {"action_sequence_contract": {"predecessor_tail_frame_ref": str(dst)},
                    "reference_image_sequence": [{"role": "START_FRAME", "path": "/x/kf.png"}]}
            with mock.patch.object(S.subprocess, "run", _fake_ffmpeg(True)), \
                    mock.patch.object(S, "resolve_media_binary", lambda _n: "ffmpeg"), \
                    mock.patch.object(tttc, "_default_ocr", BURN), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_TEXT_CLEAN": "1"}):
                self.assertTrue(S.bind_predecessor_tail_frame(task, {"output_path": str(src), "sha256": "s"}))
            self.assertTrue(task["predecessor_tail_text_clean"]["tail_text_cleaned"])
            self.assertTrue((dst.parent / "E01-VU-001_tail.orig.png").is_file())
            self.assertEqual(task["predecessor_tail_frame_sha256"], S.sha256_file(dst))
            self.assertEqual(task["reference_image_sequence"][0]["path"], str(dst))
            self.assertFalse((dst.parent / "E01-VU-001_tail.part.png").exists())

    def test_supervisor_ocr_failure_still_binds(self):
        from tools import episode_parallel_batch_supervisor as S
        from tools import tail_frame_text_clean as tttc
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "u.mp4"
            src.write_bytes(b"fake mp4")
            dst = tmp / "u_tail.png"
            task = {"action_sequence_contract": {"predecessor_tail_frame_ref": str(dst)}}

            def boom(_img):
                raise RuntimeError("no ocr")
            with mock.patch.object(S.subprocess, "run", _fake_ffmpeg(True)), \
                    mock.patch.object(S, "resolve_media_binary", lambda _n: "ffmpeg"), \
                    mock.patch.object(tttc, "_default_ocr", boom), \
                    mock.patch.dict(os.environ, {"NALU_TAIL_TEXT_CLEAN": "1"}):
                self.assertTrue(S.bind_predecessor_tail_frame(task, {"output_path": str(src), "sha256": "s"}))
            self.assertEqual(task["predecessor_tail_text_clean"]["status"], "FAIL_OPEN")
            self.assertTrue(dst.is_file())


if __name__ == "__main__":
    unittest.main()
