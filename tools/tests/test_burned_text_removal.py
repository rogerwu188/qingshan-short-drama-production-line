#!/usr/bin/env python3
"""Local burned-text removal (line owner 2026-11-23, option 2-E; tools/burned_text_removal.py) and its S7 wiring.

Offline: small synthetic clips (ffmpeg), a mock OCR that reads bright strokes, a mock inpainter in place of LaMa,
no model download, no credits.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
RT = REPO / "lines" / "nalu" / "runtime" / "tools"
for _p in (RT, REPO / "tools", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import burned_text_removal as btr  # noqa: E402

try:
    import cv2  # noqa: E402
except ImportError:  # pragma: no cover
    cv2 = None

HAVE_MEDIA = cv2 is not None and shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
W, H, FPS = 240, 426, 24
TEXT_Y = int(H * 0.74)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _frames(n: int, *, text: range | None, big: bool = False):
    """A slowly panning textured set (values 30-170, never white) with a white caption line in ``text`` frames."""
    rng = np.random.default_rng(7)
    base = cv2.GaussianBlur((rng.random((H, W + 64)) * 140 + 30).astype(np.uint8), (7, 7), 0)
    for k in range(n):
        x = (k // 2) % 64
        frame = cv2.cvtColor(np.ascontiguousarray(base[:, x:x + W]), cv2.COLOR_GRAY2BGR)
        if text is not None and k in text:
            scale = 3.0 if big else 0.9
            cv2.putText(frame, "TEXT", (W // 2 - (140 if big else 40), TEXT_Y), cv2.FONT_HERSHEY_SIMPLEX, scale,
                        (255, 255, 255), 6 if big else 2, cv2.LINE_AA)
        yield frame


def _clip(path: Path, n: int = 36, *, text: range | None = range(6, 30), big: bool = False, audio: bool = True) -> Path:
    argv = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "-"]
    if audio:
        argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={n / FPS:.3f}"]
    argv += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p"]
    argv += (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE)
    for f in _frames(n, text=text, big=big):
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return path


def mock_ocr(image):
    """RapidOCR-shaped: one box around the bright (>= 235) strokes of the crop, read as a 4-character line."""
    grey = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(grey >= 235)
    if len(ys) < 20:
        return []
    x0, x1, y0, y1 = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
    return [([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "字幕测试", 0.95)]


class Inpaint:
    """Stand-in for LaMa: TELEA over the mask; counts calls; optional delay; ``noop`` leaves the text."""

    def __init__(self, delay: float = 0.0, noop: bool = False) -> None:
        self.calls, self.delay, self.noop = 0, delay, noop

    def __call__(self, strip, mask):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return strip.copy() if self.noop else cv2.inpaint(strip, mask, 3, cv2.INPAINT_TELEA)


def _run(src: Path, out: Path, **kw):
    kw.setdefault("ocr", mock_ocr)
    kw.setdefault("inpainter", Inpaint())
    kw.setdefault("face_detector", lambda frame: [])
    kw.setdefault("budget_s", 120.0)
    kw.setdefault("env", {btr.ENV_FLAG: "1"})
    return btr.remove(src, out, n_threads=1, **kw)


# ================================================================================================ pure helpers
class PureHelpersTest(unittest.TestCase):
    def test_runs_keyframes_and_window(self):
        self.assertEqual(btr.runs([False, True, True, False, True]), [(1, 2), (4, 4)])
        self.assertEqual(btr.keyframes((3, 20), 8), [3, 11, 19, 20])
        self.assertEqual(btr.keyframes((5, 5), 8), [5])
        boxes = btr.fill_skipped([[(1, 1, 2, 2)], None, [], None])
        self.assertEqual(boxes[1], [(1, 1, 2, 2)])     # union of the OCR'd neighbours
        self.assertEqual(boxes[3], [])
        rows = [[] for _ in range(10)]
        rows[5] = [(0, 0, 1, 1)]
        self.assertEqual([bool(btr.window_boxes(rows, i)) for i in range(10)],
                         [False, False, True, True, True, True, True, True, True, False])  # +-3 frames

    def test_area_and_face_overlap(self):
        self.assertEqual(btr.text_area_fraction([], 100, 100), 0.0)
        self.assertAlmostEqual(btr.text_area_fraction([(10, 10, 20, 20)], 100, 100, pad=0), 0.01)
        self.assertEqual(btr.face_overlap([(0, 80, 50, 100)], [(200, 0, 300, 100)]), 0.0)
        self.assertGreater(btr.face_overlap([(0, 80, 100, 100)], [(20, 0, 80, 90)], pad=0), 0.1)

    def test_estimate_scales_with_a_slower_device(self):
        fast = btr.estimate_seconds(frames=100, burned=60, lama_calls=10, ocr_s_per_frame=0.05, n_threads=2, fps=24)
        slow = btr.estimate_seconds(frames=100, burned=60, lama_calls=10, ocr_s_per_frame=0.15, n_threads=2, fps=24)
        self.assertGreater(slow, 2.5 * fast)

    @unittest.skipUnless(cv2 is not None, "OpenCV missing")
    def test_stroke_mask_covers_strokes_dilated_not_the_whole_box(self):
        strip = np.full((120, 240, 3), 60, np.uint8)
        cv2.putText(strip, "TEXT", (70, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        ys, xs = np.nonzero(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) > 200)
        box = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
        mask = btr.stroke_mask(strip, [box])
        self.assertTrue((mask[ys, xs] > 0).all())                       # every stroke pixel is masked
        grown = (mask > 0).sum()
        self.assertGreater(grown, len(ys) * 2)                           # dilated (outline / shadow)
        self.assertLess(grown, 240 * 120 * 0.5)
        self.assertEqual(int(mask[:5].sum()), 0)                         # nothing far from the box

    @unittest.skipUnless(cv2 is not None, "OpenCV missing")
    def test_dark_strokes_are_masked_and_flat_boxes_fall_back_to_the_box(self):
        strip = np.full((120, 240, 3), 200, np.uint8)
        cv2.putText(strip, "TEXT", (70, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
        ys, xs = np.nonzero(cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) < 60)
        mask = btr.stroke_mask(strip, [(float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))])
        self.assertTrue((mask[ys, xs] > 0).all())
        flat = np.full((120, 240, 3), 90, np.uint8)                      # OCR saw text the hats cannot
        mask = btr.stroke_mask(flat, [(70.0, 50.0, 140.0, 72.0)])
        self.assertTrue((mask[50:72, 70:140] > 0).all())


# ================================================================================================ model delivery
class ModelDeliveryTest(unittest.TestCase):
    def test_missing_model_fails_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {btr.ENV_MODEL_CACHE: tmp, btr.ENV_MODEL: str(Path(tmp) / "nope.onnx"), btr.ENV_FLAG: "1"}
            self.assertIsNone(btr.model_path(env))
            src = Path(tmp) / "in.mp4"
            src.write_bytes(b"x")
            rep = btr.remove(src, Path(tmp) / "out.mp4", env=env, budget_s=10)
            self.assertEqual((rep["status"], rep["reason"]), (btr.NOT_APPLIED, "MODEL_MISSING"))
            self.assertIn("--fetch-model", rep["model_hint"])
            self.assertFalse((Path(tmp) / "out.mp4").exists())

    def test_fetch_verifies_sha_before_the_atomic_move(self):
        class Resp:
            def __init__(self, data):
                self.data = data

            def read(self, n=-1):
                chunk, self.data = self.data[:n], self.data[n:]
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        payload = b"fake-lama-model" * 10
        with tempfile.TemporaryDirectory() as tmp:
            env = {btr.ENV_MODEL_CACHE: tmp}
            bad = btr.fetch_model(env, opener=lambda url: Resp(b"tampered"))
            self.assertEqual(bad["status"], "SHA_MISMATCH")
            self.assertEqual(list(Path(tmp).iterdir()), [])
            with mock.patch.object(btr, "MODEL_SHA256", hashlib.sha256(payload).hexdigest()), \
                    mock.patch.object(btr, "MODEL_BYTES", len(payload)):
                ok = btr.fetch_model(env, opener=lambda url: Resp(payload))
                self.assertEqual(ok["status"], "FETCHED")
                self.assertEqual(btr.model_path(env), Path(tmp) / btr.MODEL_NAME)
                self.assertTrue((Path(tmp) / (btr.MODEL_NAME + ".sha256_ok")).is_file())
                self.assertEqual(btr.fetch_model(env)["status"], "READY")
            # a file of the right size but other bytes is never accepted
            (Path(tmp) / btr.MODEL_NAME).write_bytes(b"x" * btr.MODEL_BYTES if btr.MODEL_BYTES < 10 else b"x")
            self.assertIsNone(btr.model_path(env))

    def test_pinned_model_is_not_vendored(self):
        self.assertFalse(list(REPO.glob("**/lama_fp32.onnx")))
        self.assertIn(btr.MODEL_SHA256, btr.MODEL_URL + btr.MODEL_SHA256)
        self.assertIn("/resolve/c3c0c9e", btr.MODEL_URL)   # pinned to a commit, not "main"


# ================================================================================================ end to end
@unittest.skipUnless(HAVE_MEDIA, "OpenCV / ffmpeg missing")
class RemoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="btr_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_applied_same_frames_fps_audio_and_post_check_clean(self):
        src = _clip(self.tmp / "in.mp4")
        before = _sha(src)
        out = self.tmp / "clean.mp4"
        paint = Inpaint()
        rep = _run(src, out, inpainter=paint)
        self.assertEqual(rep["status"], btr.APPLIED, rep)
        self.assertEqual(_sha(src), before)                          # the original is never touched
        self.assertTrue(out.is_file())
        self.assertEqual(rep["output_sha256"], _sha(out))
        a, b = btr.probe(src), btr.probe(out)
        self.assertEqual(a["nb_frames"], b["nb_frames"])
        self.assertEqual(a["rate"], b["rate"])
        self.assertTrue(b["has_audio"])
        self.assertLess(abs(a["duration"] - b["duration"]), 1.5 / FPS)
        self.assertEqual(rep["postcheck"]["status"], "CLEAN")
        self.assertEqual(rep["postcheck"]["burned_frames"], 0)
        # LaMa only on keyframes: first/last of the burned run + every 8th
        self.assertEqual(paint.calls, rep["lama_keyframes"])
        self.assertLess(paint.calls, rep["burned_frames"] / 3)
        self.assertEqual(rep["frames_processed"], rep["burned_frames"])
        for key in ("seconds", "peak_rss_mb", "frames_processed", "stage_seconds"):
            self.assertIn(key, rep)
        # nothing changed far above the caption band
        cap_a, cap_b = cv2.VideoCapture(str(src)), cv2.VideoCapture(str(out))
        for _ in range(15):
            fa, fb = cap_a.read()[1], cap_b.read()[1]
        self.assertLess(float(np.abs(fa[:100].astype(int) - fb[:100].astype(int)).mean()), 3.0)

    def test_streaming_memory_stays_bounded_on_a_long_clip(self):
        src = _clip(self.tmp / "long.mp4", n=240, text=range(4, 236), audio=False)
        seen = []
        real = btr.propagate_band

        def spy(strips, masks, **kw):
            seen.append(len(strips))
            return real(strips, masks, **kw)
        tracemalloc.start()
        try:
            with mock.patch.object(btr, "propagate_band", spy):
                rep = _run(src, self.tmp / "clean.mp4", lama_every=8)
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(rep["status"], btr.APPLIED, rep)
        self.assertLessEqual(max(seen), 8 + 1)                       # one keyframe segment at a time
        whole_clip = 240 * W * H * 3
        self.assertLess(peak, whole_clip / 3, f"traced peak {peak / 1e6:.1f} MB")

    def test_text_on_a_face_is_not_repainted(self):
        src = _clip(self.tmp / "in.mp4")
        face = lambda frame: [(W * 0.3, H * 0.55, W * 0.7, H * 0.80)]  # noqa: E731 - chin over the caption
        rep = _run(src, self.tmp / "clean.mp4", face_detector=face)
        self.assertEqual((rep["status"], rep["reason"]), (btr.NOT_APPLIED, "TEXT_ON_FACE"))
        self.assertFalse((self.tmp / "clean.mp4").exists())

    def test_unavailable_face_detector_is_a_skip(self):
        src = _clip(self.tmp / "in.mp4")
        with mock.patch.object(btr, "make_face_detector", lambda n: None):
            rep = _run(src, self.tmp / "clean.mp4", face_detector=None)
        self.assertEqual(rep["reason"], "FACE_CHECK_UNAVAILABLE")

    def test_large_text_area_is_a_skip(self):
        src = _clip(self.tmp / "in.mp4")
        with mock.patch.object(btr, "MAX_TEXT_AREA_FRACTION", 0.001):
            rep = _run(src, self.tmp / "clean.mp4")
        self.assertEqual(rep["reason"], "TEXT_AREA_TOO_LARGE")
        self.assertGreater(rep["text_area_fraction"], 0.001)

    def test_no_text_is_a_skip(self):
        src = _clip(self.tmp / "in.mp4", text=None)
        rep = _run(src, self.tmp / "clean.mp4")
        self.assertEqual(rep["reason"], "NO_TEXT_DETECTED")

    def test_estimate_over_budget_skips_before_any_inpaint(self):
        src = _clip(self.tmp / "in.mp4")
        paint = Inpaint()
        with mock.patch.object(btr, "estimate_seconds", lambda **kw: 999.0):
            rep = _run(src, self.tmp / "clean.mp4", inpainter=paint, budget_s=60)
        self.assertEqual(rep["reason"], "ESTIMATED_OVER_BUDGET")
        self.assertEqual(paint.calls, 0)

    def test_real_runtime_over_budget_stops_early_and_leaves_no_file(self):
        src = _clip(self.tmp / "in.mp4")
        with mock.patch.object(btr, "estimate_seconds", lambda **kw: 0.0):
            rep = _run(src, self.tmp / "clean.mp4", inpainter=Inpaint(delay=0.6), budget_s=2.0)
        self.assertEqual(rep["reason"], "BUDGET_EXCEEDED", rep)
        self.assertLess(rep["seconds"], 6.0)
        self.assertFalse((self.tmp / "clean.mp4").exists())
        self.assertFalse(list(self.tmp.glob("*.removing.*")))

    def test_post_check_rejects_a_clip_that_still_shows_text(self):
        src = _clip(self.tmp / "in.mp4")
        rep = _run(src, self.tmp / "clean.mp4", inpainter=Inpaint(noop=True))
        self.assertEqual((rep["status"], rep["reason"]), (btr.NOT_APPLIED, "POSTCHECK_TEXT_REMAINS"))
        self.assertGreater(rep["postcheck"]["burned_frames"], 0)
        self.assertFalse((self.tmp / "clean.mp4").exists())

    def test_opt_out(self):
        src = _clip(self.tmp / "in.mp4")
        paint = Inpaint()
        rep = _run(src, self.tmp / "clean.mp4", inpainter=paint, env={btr.ENV_FLAG: "0"})
        self.assertEqual(rep["reason"], "OPT_OUT")
        self.assertEqual(paint.calls, 0)


# ================================================================================================ S7 planning
class PlanTargetsTest(unittest.TestCase):
    S6 = {"burned_text_unresolved": True, "kept_take_sha256": "a" * 64, "kept_take_burned_frames": 9}

    def plan(self, s6=None, redo=None, status=None, enabled=True, pending=(), sha="a" * 64):
        return btr.plan_targets(s6_records=s6 or {}, redo_records=redo or {}, round_status=status,
                                rounds_enabled=enabled, pending=pending, clip_sha=lambda uid: sha)

    def test_s6_unresolved_waits_for_the_final_fix_round(self):
        targets, skipped = self.plan({"VU-1": self.S6})
        self.assertEqual(targets, [])
        self.assertEqual(skipped[0]["reason"], "AWAITING_FINAL_FIX_ROUND")
        for status in ("NOT_NEEDED", "DONE", "S7_RERUN", "NO_ACTIONABLE_FIX"):
            targets, _ = self.plan({"VU-1": self.S6}, status=status)
            self.assertEqual([(t["unit_id"], t["stage"]) for t in targets], [("VU-1", "S6_UNRESOLVED")], status)
        targets, _ = self.plan({"VU-1": self.S6}, enabled=False)
        self.assertEqual(len(targets), 1)                                    # rounds off: S6 was the last paid option

    def test_final_fix_unresolved_is_a_target_and_pending_is_not(self):
        redo = {"VU-2": {"burn_status": "UNRESOLVED", "kept_take_sha256": "a" * 64}}
        targets, _ = self.plan(redo=redo, status="S6_REDO_PENDING")
        self.assertEqual(targets[0]["stage"], "FINAL_FIX_UNRESOLVED")
        _t, skipped = self.plan(redo=redo, status="S6_REDO_PENDING", pending=["VU-2"])
        self.assertEqual(skipped[0]["reason"], "FINAL_FIX_REDO_PENDING")

    def test_strict_verdict_accept_correct_keeps_the_burned_line(self):
        rec = {**self.S6, "strict_burn": {"verdict": "ACCEPT_CORRECT", "take_sha256": "a" * 64}}
        targets, skipped = self.plan({"VU-1": rec}, status="DONE")
        self.assertEqual(targets, [])
        self.assertEqual(skipped[0]["reason"], "BURNED_LINE_ACCEPTED_CORRECT")
        # a verdict of another take does not count; absent = REJECT
        rec = {**self.S6, "strict_burn": {"verdict": "ACCEPT_CORRECT", "take_sha256": "b" * 64}}
        targets, _ = self.plan({"VU-1": rec}, status="DONE")
        self.assertEqual(targets[0]["strict_verdict"], "ABSENT_TREATED_AS_REJECT")
        for verdict in ("REJECT_WRONG", "REJECT_UNSTABLE"):
            rec = {**self.S6, "strict_burn_verdict": verdict}
            targets, _ = self.plan({"VU-1": rec}, status="DONE")
            self.assertEqual(targets[0]["strict_verdict"], verdict)
        rec = {**self.S6, "checks": {"a" * 64: {"strict_burn_check": {"verdict": "ACCEPT_CORRECT"}}}}
        self.assertEqual(self.plan({"VU-1": rec}, status="DONE")[0], [])

    def test_line_verdicts_of_the_strict_check(self):
        lines = btr.burnin_verdicts({"burned_line_checks": [
            {"unit_id": "VU-1", "verdict": "ACCEPT_CORRECT"}, {"unit_id": "VU-1", "verdict": "ACCEPT_CORRECT"},
            {"unit_id": "VU-2", "verdict": "ACCEPT_CORRECT"}, {"unit_id": "VU-2", "verdict": "REJECT_WRONG"}]})
        s6 = {"VU-1": self.S6, "VU-2": self.S6}
        targets, skipped = btr.plan_targets(s6_records=s6, redo_records={}, round_status="DONE", rounds_enabled=True,
                                            pending=(), clip_sha=lambda u: "a" * 64, line_verdicts=lines)
        self.assertEqual([(t["unit_id"], t["strict_verdict"]) for t in targets], [("VU-2", "REJECT_WRONG")])
        self.assertEqual(skipped[0]["reason"], "BURNED_LINE_ACCEPTED_CORRECT")

    def test_superseded_missing_and_sheet_only_takes_are_skipped(self):
        reasons = lambda r: [s["reason"] for s in r[1]]  # noqa: E731
        self.assertEqual(reasons(self.plan({"VU-1": self.S6}, status="DONE", sha="c" * 64)), ["KEPT_TAKE_SUPERSEDED"])
        self.assertEqual(reasons(self.plan({"VU-1": self.S6}, status="DONE", sha=None)), ["CLIP_MISSING"])
        sheet = {**self.S6, "kept_take_sheet_leak": True, "kept_take_burned_frames": 0}
        self.assertEqual(reasons(self.plan({"VU-1": sheet}, status="DONE")), ["SHEET_LEAK_WITHOUT_TEXT"])

    def test_cache_and_applied_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "VU-1.mp4"
            out.write_bytes(b"clean")
            row = {"status": btr.APPLIED, "source": "/x/VU-1.mp4", "source_sha256": "s", "output": str(out),
                   "output_sha256": _sha(out), "algo_version": btr.ALGO_VERSION}
            report = {"units": {"VU-1": row, "VU-2": {**row, "status": btr.NOT_APPLIED, "reason": "TEXT_ON_FACE"},
                                "VU-3": {**row, "status": btr.NOT_APPLIED, "reason": "BUDGET_EXCEEDED"}}}
            self.assertIs(btr.cached_row(report, "VU-1", "s"), row)
            self.assertIsNone(btr.cached_row(report, "VU-1", "other-input"))
            self.assertIsNotNone(btr.cached_row(report, "VU-2", "s"))            # a guard skip is final
            self.assertIsNone(btr.cached_row(report, "VU-3", "s"))               # a budget skip may retry
            self.assertEqual(sorted(btr.applied_sources(report)), ["VU-1"])
            out.write_bytes(b"changed")
            self.assertIsNone(btr.cached_row(report, "VU-1", "s"))               # output no longer intact


# ================================================================================================ S7 wiring
class S7WiringTest(unittest.TestCase):
    def setUp(self):
        import nalu_pipeline as P  # noqa: PLC0415
        self.P = P
        self.tmp = Path(tempfile.mkdtemp(prefix="btr_s7_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = SimpleNamespace(assembly=self.tmp / "assembly", video_media=self.tmp / "video",
                            preprod_reports=self.tmp / "reports")
        for d in (p.assembly, p.video_media, p.preprod_reports):
            d.mkdir()
        self.said, self.runs = [], []
        self.ctx = SimpleNamespace(p=p, episode="E09", dry=False, state={}, say=self.said.append, run=self.fake_run)
        self.clip = p.video_media / "VU-1.mp4"
        self.clip.write_bytes(b"burned take")
        self.state = {"s6_burn_retry": {"VU-1": {"burned_text_unresolved": True, "kept_take_sha256": _sha(self.clip),
                                                 "kept_take_burned_frames": 7}}}
        (p.preprod_reports / "E09_S6_WAVE_STATE.json").write_text(json.dumps(self.state))
        self.record = self.tmp / "final_fix.json"
        self.redo = self.tmp / "final_fix_redo.json"
        for patch in (mock.patch.object(P, "_wave_state_path", lambda c: p.preprod_reports / "E09_S6_WAVE_STATE.json"),
                      mock.patch.object(P, "final_fix_record_path", lambda c: self.record),
                      mock.patch.object(P, "final_fix_redo_path", lambda c: self.redo),
                      mock.patch.dict(os.environ, {btr.ENV_FLAG: "1"})):
            patch.start()
            self.addCleanup(patch.stop)
        self.result = btr.APPLIED

    def fake_run(self, argv, *, name, timeout=None, **_kw):
        argv = [str(a) for a in argv]
        self.runs.append((name, argv, timeout))
        out, rep = Path(argv[argv.index("--out") + 1]), Path(argv[argv.index("--report") + 1])
        row = {"status": self.result, "reason": "CLEANED" if self.result == btr.APPLIED else "TEXT_ON_FACE",
               "seconds": 42.0, "peak_rss_mb": 900.0, "frames_processed": 60}
        if self.result == btr.APPLIED:
            out.write_bytes(b"cleaned take")
            row.update(output=str(out), output_sha256=_sha(out))
        rep.write_text(json.dumps(row))
        return {"name": name, "exit_code": 0, "duration_s": 45.0}

    def removal(self):
        res = SimpleNamespace(details={"commands": {}}, steps=[], receipts=[])
        return self.P.s7_burned_text_removal(self.ctx, res, {}), res

    def test_waits_for_the_round_then_cleans_once_and_caches(self):
        path, res = self.removal()
        self.assertIsNone(path)
        self.assertEqual(res.details["text_removal"]["skipped"][0]["reason"], "AWAITING_FINAL_FIX_ROUND")
        self.assertEqual(self.runs, [])
        self.assertTrue(self.P.s7_text_removal_due_after_round(self.ctx, res) is False)
        self.record.write_text(json.dumps({"status": "NOT_NEEDED"}))
        self.assertTrue(self.P.s7_text_removal_due_after_round(self.ctx, res))   # the stage re-runs once
        path, res = self.removal()
        self.assertEqual(path, self.ctx.p.assembly / "E09_TEXT_REMOVAL.json")
        name, argv, timeout = self.runs[0]
        self.assertEqual(name, "s7_text_removal_VU-1")
        self.assertIn(str(self.clip), argv)
        self.assertEqual(argv[argv.index("--max-seconds") + 1], "240")
        self.assertLessEqual(timeout, 240 + 180)
        report = json.loads(path.read_text())
        row = report["units"]["VU-1"]
        self.assertEqual((row["status"], row["stage"], row["source_sha256"]), (btr.APPLIED, "S6_UNRESOLVED",
                                                                               _sha(self.clip)))
        self.assertEqual(row["strict_verdict"], "ABSENT_TREATED_AS_REJECT")
        self.assertEqual(report["spent_seconds"], 45.0)
        self.assertEqual(self.ctx.state["text_removal"]["applied"], ["VU-1"])
        self.assertEqual(res.details["text_removal"]["status"], "APPLIED")
        self.assertTrue(any(s.startswith("S7_TEXT_REMOVAL unit=VU-1 APPLIED") for s in self.said))
        self.assertEqual(self.clip.read_bytes(), b"burned take")                 # the original stays
        self.removal()                                                           # S7 re-run: cached
        self.assertEqual(len(self.runs), 1)

    def test_strict_check_report_newer_than_the_clip_counts(self):
        self.record.write_text(json.dumps({"status": "DONE"}))
        burnin = self.ctx.p.assembly / "E09_BURNIN_SUBTITLES.json"
        burnin.write_text(json.dumps({"burned_line_checks": [{"unit_id": "VU-1", "verdict": "ACCEPT_CORRECT"}]}))
        os.utime(self.clip, (time.time() - 100, time.time() - 100))
        self.assertEqual(self.P.s7_text_removal_plan(self.ctx)[0], [])
        os.utime(self.clip, (time.time() + 100, time.time() + 100))        # redone since: that verdict is stale
        self.assertEqual(len(self.P.s7_text_removal_plan(self.ctx)[0]), 1)

    def test_opt_out_and_accept_correct_never_run(self):
        self.record.write_text(json.dumps({"status": "DONE"}))
        with mock.patch.dict(os.environ, {btr.ENV_FLAG: "0"}):
            path, res = self.removal()
        self.assertEqual((path, res.details["text_removal"]["status"]), (None, "OPT_OUT"))
        self.state["s6_burn_retry"]["VU-1"]["strict_burn"] = {"verdict": "ACCEPT_CORRECT"}
        (self.ctx.p.preprod_reports / "E09_S6_WAVE_STATE.json").write_text(json.dumps(self.state))
        path, res = self.removal()
        self.assertIsNone(path)
        self.assertEqual(res.details["text_removal"]["skipped"][0]["reason"], "BURNED_LINE_ACCEPTED_CORRECT")
        self.assertEqual(self.runs, [])

    def test_episode_cap_and_not_applied(self):
        self.record.write_text(json.dumps({"status": "DONE"}))
        (self.ctx.p.assembly / "E09_TEXT_REMOVAL.json").write_text(json.dumps({"units": {}, "spent_seconds": 1190}))
        path, res = self.removal()
        self.assertIsNone(path)
        self.assertEqual(res.details["text_removal"]["units"]["VU-1"]["reason"], "EPISODE_BUDGET_SPENT")
        self.assertEqual(self.runs, [])
        (self.ctx.p.assembly / "E09_TEXT_REMOVAL.json").write_text(json.dumps({"units": {}, "spent_seconds": 1100}))
        self.result = btr.NOT_APPLIED
        path, res = self.removal()
        self.assertIsNone(path)
        argv = self.runs[0][1]
        self.assertEqual(argv[argv.index("--max-seconds") + 1], "100")          # what the episode has left
        self.assertFalse((self.ctx.p.video_media / "_text_removed" / "VU-1.mp4").exists())

    def test_cleaned_units_leave_the_residual_burn_bands(self):
        bands = self.ctx.p.assembly / "bands.json"
        bands.write_text(json.dumps({"units": {"VU-1": {"y0": 0.7, "y1": 0.8}, "VU-2": {"y0": 0.7, "y1": 0.8}}}))
        report = self.ctx.p.assembly / "removal.json"
        report.write_text(json.dumps({"units": {"VU-1": {"status": btr.APPLIED, "source": "s", "output": "o"}}}))
        self.assertEqual(self.P.s7_text_removal_drop_bands(bands, report), bands)
        self.assertEqual(sorted(json.loads(bands.read_text())["units"]), ["VU-2"])
        report.write_text(json.dumps({"units": {"VU-2": {"status": btr.APPLIED, "source": "s", "output": "o"}}}))
        self.assertIsNone(self.P.s7_text_removal_drop_bands(bands, report))
        self.assertIsNone(self.P.s7_text_removal_drop_bands(None, report))

    def test_picture_source_follows_the_builder_precedence(self):
        stab_out = self.ctx.p.video_media / "_stabilized" / "VU-1.mp4"
        stab_out.parent.mkdir()
        stab_out.write_bytes(b"stabilised")
        summary = self.ctx.p.assembly / "stab.json"
        summary.write_text("{}")
        with mock.patch("clip_lockoff_stabilize.applied_sources",
                        lambda s: {"VU-1": {"source": str(self.clip), "source_sha256": _sha(self.clip),
                                            "output": str(stab_out)}}):
            self.assertEqual(self.P.s7_text_removal_picture_source(self.ctx, "VU-1", {"stabilized": summary}),
                             stab_out)
        self.assertEqual(self.P.s7_text_removal_picture_source(self.ctx, "VU-1", {}), self.clip)

    def test_final_fix_round_is_not_reopened_by_the_removal_rerun(self):
        self.record.write_text(json.dumps({"status": "NOT_NEEDED", "findings": []}))
        self.ctx._text_removal_rerun = True
        self.ctx.p.final_candidate = self.tmp / "cand.mp4"
        out = self.P.s7_final_fix_round(self.ctx, SimpleNamespace(details={}),
                                        {"final_video_sha256": "new-cut", "report": ""}, False)
        self.assertEqual(out["action"], "PROCEED")
        self.assertEqual(json.loads(self.record.read_text())["status"], "NOT_NEEDED")


# ================================================================================================ builder
class BuilderTest(unittest.TestCase):
    def test_cleaned_picture_replaces_exactly_the_matching_source(self):
        from tools.build_agentcut_from_admitted_storyboard_sources import build  # noqa: PLC0415
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip, other, clean = root / "VU-1.mp4", root / "VU-2.mp4", root / "VU-1.clean.mp4"
            clip.write_bytes(b"burned")
            other.write_bytes(b"other")
            clean.write_bytes(b"cleaned")
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({"tasks": [
                {"source_id": "VU-1", "status": "qa_pass", "output_path": str(clip), "duration": 4},
                {"source_id": "VU-2", "status": "qa_pass", "output_path": str(other), "duration": 4}]}))
            review = root / "review.json"
            review.write_text(json.dumps({"passed_items": [{"path": str(clip)}, {"path": str(other)}]}))
            contract = root / "contract.json"
            contract.write_text(json.dumps({"episode": "E99", "audio_contract": {"bgm": "NONE_WHOLE_EPISODE",
                                                                                 "native_dialogue_only": True}}))
            removal = root / "removal.json"
            rows = {"VU-1": {"status": "APPLIED", "source": str(clip), "source_sha256": _sha(clip),
                             "output": str(clean), "output_sha256": _sha(clean), "stage": "S6_UNRESOLVED"},
                    "VU-2": {"status": "APPLIED", "source": str(other), "source_sha256": "stale",
                             "output": str(clean), "output_sha256": _sha(clean)}}
            removal.write_text(json.dumps({"units": rows}))
            project = root / "project.json"
            build("E99", [receipt], review, project, root / "admission.json", root / "out.mp4", 2, contract,
                  text_removal=removal)
            payload = json.loads(project.read_text())
            video = {c["id"]: c for c in payload["timeline"]["videoTracks"][0]["clips"]}
            audio = {c["id"]: c for c in payload["timeline"]["audioTracks"][0]["clips"]}
            self.assertEqual(video["E99-VU-1-VIDEO"]["source"], str(clean))
            self.assertEqual(audio["E99-VU-1-AUDIO"]["source"], str(clean))       # one source: audio copied
            self.assertEqual(video["E99-VU-1-VIDEO"]["metadata"]["burned_text_removal"]["picture_source"], str(clip))
            self.assertEqual(video["E99-VU-2-VIDEO"]["source"], str(other))       # stale sha: untouched
            admission = json.loads((root / "admission.json").read_text())
            self.assertIn("burned_text_removal", json.dumps(admission))


if __name__ == "__main__":
    unittest.main()
