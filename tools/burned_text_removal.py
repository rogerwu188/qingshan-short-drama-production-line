#!/usr/bin/env python3
"""Local, CPU-only removal of MiniMax-H3 burned-in caption text from one kept take (last resort, zero credits).

Line owner 2026-11-23 (烧字后期方案对比, option 2-E): when the S6 burn retries and the final-fix redo did not clear a
unit's burned line, and the strict burned-line check did not ACCEPT it as the correct line, S7 may clean the kept take
locally instead of shipping the burned line.  Blur boxes were rejected; this module repaints the text area:

* **mask** -- RapidOCR (the S6 detector's engine and false-positive filters, ``tail_frame_text_clean.find_text_boxes``:
  band y 0.55-0.95, >= 2 text chars, glyph >= 40 px at 720 w, centred, area cap) on every ``ocr_step``-th frame;
  each frame's boxes are the union of the boxes of frames t-3..t+3 (the burned line fades in/out and its glyph size
  jitters); inside each box a top-hat / black-hat picks the strokes, dilated 13 px to cover outline and drop shadow.
* **fill** -- LaMa (``lama_fp32.onnx``, onnxruntime, no torch) on the first, last and every ``lama_every``-th burned
  frame of each burned run (keyframes); the frames between two keyframes take their masked pixels through DIS optical
  flow chains from the nearest clean source (a neighbour where that point is not masked, or a LaMa keyframe); points
  no chain reaches get a small TELEA inpaint.  Only masked pixels change.
* **streaming** -- two sequential decodes (detect, then fill); the fill pass holds at most one keyframe segment
  (``lama_every`` + 1 strips of y 0.40-0.98) and writes every frame straight into an ffmpeg pipe, so memory does not
  grow with clip length (target peak <= 1 GB RSS with 2 threads).  Same frame count / fps; audio stream copied.

Guards (any one -> ``NOT_APPLIED``, the original take is used; never raises):
  opt-out (``NALU_TEXT_REMOVAL=0``), model missing / sha mismatch, no text found, text area over
  ``MAX_TEXT_AREA_FRACTION`` of the frame, text boxes on a detected face (InsightFace detection, else OpenCV Haar),
  estimated or actual runtime over the budget (``NALU_TEXT_REMOVAL_MAX_SECONDS``, default 240 per unit), and the
  post-check: the cleaned clip is re-read by the S6 detector (``h3_burn_retry.detect``) -- any text hit left, or a
  frame-count / duration change, rejects it.

Every result carries the measured ``seconds``, ``peak_rss_mb`` and ``frames_processed``.

Model delivery: ``lama_fp32.onnx`` (208 MB, Apache-2.0, Carve/LaMa-ONNX pinned to a commit, sha256 below) is NOT in
git.  ``setup_host.sh`` fetches it once into ``$NALU_MODEL_CACHE`` (default ``~/.cache/nalu/models``) with
``python -m tools.burned_text_removal --fetch-model`` (never fatal); ``NALU_LAMA_ONNX`` points at another copy.  A
missing model is ``NOT_APPLIED: MODEL_MISSING`` (fail-open), never a download in the middle of a run.

CLI::

    python -m tools.burned_text_removal CLIP --out CLEAN.mp4 [--report R.json] [--threads 2] [--max-seconds 240]
    python -m tools.burned_text_removal --benchmark CLIP [--threads 1]   # prints seconds / peak RSS per stage
    python -m tools.burned_text_removal --fetch-model | --check-model
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

SCHEMA = "qingshan.burned_text_removal.v1"
#: bump when the algorithm or its parameters change: S7 caches results by (source sha, this version)
ALGO_VERSION = "2e-v1"

ENV_FLAG = "NALU_TEXT_REMOVAL"
ENV_MAX_SECONDS = "NALU_TEXT_REMOVAL_MAX_SECONDS"
ENV_EPISODE_MAX_SECONDS = "NALU_TEXT_REMOVAL_EPISODE_MAX_SECONDS"
ENV_THREADS = "NALU_TEXT_REMOVAL_THREADS"
ENV_MODEL = "NALU_LAMA_ONNX"
ENV_MODEL_CACHE = "NALU_MODEL_CACHE"
ENV_MODEL_URL = "NALU_LAMA_ONNX_URL"
DEFAULT_MAX_SECONDS = 240.0
DEFAULT_EPISODE_MAX_SECONDS = 1200.0
DEFAULT_THREADS = 2

MODEL_NAME = "lama_fp32.onnx"
MODEL_URL = ("https://huggingface.co/Carve/LaMa-ONNX/resolve/c3c0c9e468934d62e79c329e35d82dd09ff8c444/"
             "lama_fp32.onnx")
MODEL_SHA256 = "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6"
MODEL_BYTES = 208044816
LAMA_SIDE = 512

APPLIED = "APPLIED"
NOT_APPLIED = "NOT_APPLIED"

# geometry (frame fractions): the work strip holds the burned band and is >= W tall for LaMa's square crop
STRIP_Y0, STRIP_Y1 = 0.40, 0.98
MASK_WINDOW = 3            # boxes of frames t-3..t+3 make frame t's mask
BOX_PAD_PX = 8
TOPHAT_KERNEL = 25
TOPHAT_THRESHOLD = 28
DILATE_PX = 13
MIN_STROKE_FILL = 0.03     # fewer stroke pixels than this share of the box: the strokes are not bright -> whole box
LAMA_EVERY = 8
OCR_STEP = 2
FLOW_SCALE = 0.5
PROP_MARGIN_PX = 96       # rows of context around the masked band for the flow
MAX_TEXT_AREA_FRACTION = 0.10
FACE_OVERLAP_MAX = 0.10    # overlap / min(text box, face box) area
FACE_SAMPLES = 8

# runtime estimate: measured on the 2026-11-23 Mac M4 Pro (CLS_NEW / T3, 4.5-6.6 s 480p H3 takes); a device slower
# than the Mac (its measured OCR seconds per frame above REF_OCR_S) scales every term up.  Only a pre-filter: the
# fill pass re-projects from the seconds it really spent after every keyframe and stops early.
REF_OCR_S = 0.055
REF_LAMA_S = {1: 2.4, 2: 1.6, 3: 1.4, 4: 1.25}
REF_FLOW_S = 0.08
REF_FRAME_S = 0.01


# ------------------------------------------------------------------------------------------------ settings
def _env(env: dict[str, str] | None) -> dict[str, str]:
    return dict(os.environ) if env is None else env


def enabled(env: dict[str, str] | None = None) -> bool:
    return str(_env(env).get(ENV_FLAG, "1")).strip().lower() not in {"0", "false", "no", "off"}


def _float_env(env: dict[str, str] | None, key: str, default: float) -> float:
    try:
        value = float(str(_env(env).get(key, "")).strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def max_seconds(env: dict[str, str] | None = None) -> float:
    return _float_env(env, ENV_MAX_SECONDS, DEFAULT_MAX_SECONDS)


def episode_max_seconds(env: dict[str, str] | None = None) -> float:
    return _float_env(env, ENV_EPISODE_MAX_SECONDS, DEFAULT_EPISODE_MAX_SECONDS)


def threads(env: dict[str, str] | None = None) -> int:
    return max(1, int(_float_env(env, ENV_THREADS, DEFAULT_THREADS)))


# ------------------------------------------------------------------------------------------------- model
def model_cache_dir(env: dict[str, str] | None = None) -> Path:
    root = str(_env(env).get(ENV_MODEL_CACHE) or "").strip()
    return Path(root).expanduser() if root else Path.home() / ".cache" / "nalu" / "models"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _verified(path: Path) -> bool:
    """sha256 of ``path`` is the pin; the verdict is remembered in ``<path>.sha256_ok`` (size + mtime) so a device
    does not hash 208 MB on every unit."""
    try:
        st = path.stat()
    except OSError:
        return False
    if st.st_size != MODEL_BYTES:
        return False
    marker = path.with_name(path.name + ".sha256_ok")
    stamp = f"{MODEL_SHA256} {st.st_size} {int(st.st_mtime)}"
    try:
        if marker.read_text(encoding="utf-8").strip() == stamp:
            return True
    except OSError:
        pass
    if _sha256(path) != MODEL_SHA256:
        return False
    try:
        marker.write_text(stamp + "\n", encoding="utf-8")
    except OSError:
        pass
    return True


def model_path(env: dict[str, str] | None = None) -> Path | None:
    """The verified LaMa model, or None (missing / wrong bytes): the caller fails open."""
    explicit = str(_env(env).get(ENV_MODEL) or "").strip()
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates.append(model_cache_dir(env) / MODEL_NAME)
    for path in candidates:
        if path.is_file() and _verified(path):
            return path
    return None


def fetch_model(env: dict[str, str] | None = None, *, opener: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Download the pinned model into the cache dir (setup time only).  Verifies sha256 before the atomic move."""
    if model_path(env) is not None:
        return {"status": "READY", "path": str(model_path(env))}
    dest = model_cache_dir(env) / MODEL_NAME
    url = str(_env(env).get(ENV_MODEL_URL) or "").strip() or MODEL_URL
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=MODEL_NAME + ".", suffix=".part", dir=str(dest.parent))
        tmp = Path(tmp_name)
        h = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, (opener or (lambda u: urllib.request.urlopen(u, timeout=60)))(url) as resp:
            for block in iter(lambda: resp.read(1 << 20), b""):
                out.write(block)
                h.update(block)
        if h.hexdigest() != MODEL_SHA256:
            tmp.unlink(missing_ok=True)
            return {"status": "SHA_MISMATCH", "url": url, "sha256": h.hexdigest()}
        os.replace(tmp, dest)
        _verified(dest)
        return {"status": "FETCHED", "path": str(dest)}
    except Exception as exc:  # noqa: BLE001 - setup never fails on this optional model
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        return {"status": "FETCH_FAILED", "url": url, "error": f"{type(exc).__name__}: {exc}"[:300]}


# ------------------------------------------------------------------------------------------- measurement
def peak_rss_mb() -> dict[str, float]:
    """Peak resident set size of this process and of its finished children (ffmpeg), MB."""
    try:
        import resource  # noqa: PLC0415 - POSIX only
    except ImportError:
        return {}
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # ru_maxrss: bytes on macOS, KiB on Linux
    own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit / 1e6
    kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * unit / 1e6
    return {"self": round(own, 1), "children_max": round(kids, 1)}


class BudgetExceeded(Exception):
    pass


class Clock:
    def __init__(self, budget_s: float) -> None:
        self.t0 = time.perf_counter()
        self.budget_s = float(budget_s)
        self.stages: dict[str, float] = {}
        self.rss: dict[str, float | None] = {}

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0

    def check(self, where: str) -> None:
        if self.elapsed() > self.budget_s:
            raise BudgetExceeded(where)

    def add(self, stage: str, seconds: float) -> None:
        self.stages[stage] = round(self.stages.get(stage, 0.0) + seconds, 3)
        # the process peak so far, right after each stage: shows which stage set the peak (device benchmarks)
        self.rss[stage] = peak_rss_mb().get("self")


# ------------------------------------------------------------------------------------------- pure helpers
def runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of consecutive True flags."""
    out, start = [], None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def keyframes(run: tuple[int, int], every: int) -> list[int]:
    """First, last and every ``every``-th frame of a burned run: LaMa runs only there."""
    a, b = run
    every = max(1, int(every))
    out = list(range(a, b + 1, every))
    if out[-1] != b:
        out.append(b)
    return out


def fill_skipped(boxes: list[list[tuple[float, float, float, float]] | None]) -> list[list[tuple[float, float, float, float]]]:
    """Frames that were not OCR'd (None) take the union of the nearest OCR'd frame before and after."""
    n = len(boxes)
    out: list[list[tuple[float, float, float, float]]] = []
    for i, row in enumerate(boxes):
        if row is not None:
            out.append(list(row))
            continue
        before = next((boxes[j] for j in range(i - 1, -1, -1) if boxes[j] is not None), None) or []
        after = next((boxes[j] for j in range(i + 1, n) if boxes[j] is not None), None) or []
        out.append(list(before) + list(after))
    return out


def window_boxes(boxes: list[list[tuple[float, float, float, float]]], i: int,
                 window: int = MASK_WINDOW) -> list[tuple[float, float, float, float]]:
    return [b for j in range(max(0, i - window), min(len(boxes), i + window + 1)) for b in boxes[j]]


def _pad(box: tuple[float, float, float, float], pad: float, w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(w, int(round(x1 + pad))), min(h, int(round(y1 + pad))))


def text_area_fraction(boxes: list[tuple[float, float, float, float]], w: int, h: int,
                       pad: float = BOX_PAD_PX + DILATE_PX / 2.0) -> float:
    """Share of the frame covered by the (padded) union of ``boxes``."""
    import numpy as np  # noqa: PLC0415
    if not boxes:
        return 0.0
    m = np.zeros((h, w), np.uint8)
    for b in boxes:
        x0, y0, x1, y1 = _pad(b, pad, w, h)
        m[y0:y1, x0:x1] = 1
    return float(m.sum()) / float(w * h)


def face_overlap(boxes: list[tuple[float, float, float, float]], faces: list[tuple[float, float, float, float]],
                 pad: float = BOX_PAD_PX + DILATE_PX / 2.0) -> float:
    """Largest intersection / min(text box, face box) area over every (text box, face) pair; 0 when none touch."""
    worst = 0.0
    for b in boxes:
        bx0, by0, bx1, by1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
        for f in faces:
            fx0, fy0, fx1, fy1 = f
            iw, ih = min(bx1, fx1) - max(bx0, fx0), min(by1, fy1) - max(by0, fy0)
            if iw <= 0 or ih <= 0:
                continue
            small = min((bx1 - bx0) * (by1 - by0), (fx1 - fx0) * (fy1 - fy0))
            if small > 0:
                worst = max(worst, iw * ih / small)
    return round(worst, 4)


def estimate_seconds(*, frames: int, burned: int, lama_calls: int, ocr_s_per_frame: float, n_threads: int,
                     fps: float) -> float:
    """Rough remaining wall time after the detect pass: the reference costs scaled by this device's measured OCR
    speed (``ocr_s_per_frame`` vs ``REF_OCR_S``; never below 1), plus the post-check OCR (4 samples per second)."""
    factor = max(1.0, float(ocr_s_per_frame) / REF_OCR_S) if ocr_s_per_frame > 0 else 1.0
    lama = REF_LAMA_S.get(max(1, min(4, int(n_threads))), REF_LAMA_S[4])
    work = lama_calls * lama + burned * REF_FLOW_S + frames * REF_FRAME_S
    post = (frames / max(fps, 1.0)) * 4.0 * REF_OCR_S
    return round(factor * (work + post), 1)


def stroke_mask(strip: Any, boxes: list[tuple[float, float, float, float]], *, dilate: int = DILATE_PX) -> Any:
    """Stroke mask (uint8 0/255) of ``boxes`` (strip coordinates) on ``strip`` (BGR)."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    h, w = strip.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (TOPHAT_KERNEL, TOPHAT_KERNEL))
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate))
    for b in boxes:
        x0, y0, x1, y1 = _pad(b, BOX_PAD_PX, w, h)
        if x1 <= x0 or y1 <= y0:
            continue
        grey = cv2.cvtColor(strip[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        # bright strokes (H3's white caption) and dark ones (its outline / drop shadow, or a dark caption)
        hat = np.maximum(cv2.morphologyEx(grey, cv2.MORPH_TOPHAT, kernel),
                         cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, kernel))
        m = (hat > TOPHAT_THRESHOLD).astype(np.uint8) * 255
        if float((m > 0).mean()) < MIN_STROKE_FILL:
            m[:] = 255  # no stroke contrast (OCR saw text the hats do not): take the padded box
        m = cv2.dilate(m, grow)
        mask[y0:y1, x0:x1] |= m
    return mask


# ------------------------------------------------------------------------------------------------- engines
def cv2_threads(n_threads: int) -> None:
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(key, str(n_threads))
    try:
        import cv2  # noqa: PLC0415
        cv2.setNumThreads(int(n_threads))
    except Exception:  # noqa: BLE001
        pass


def make_ocr(n_threads: int) -> Callable[[Any], list]:
    """RapidOCR with bounded threads (the same engine and models as the S6 detector)."""
    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    kw = {f"{p}_{k}": v for p in ("det", "cls", "rec")
          for k, v in (("intra_op_num_threads", int(n_threads)), ("inter_op_num_threads", 1))}
    try:
        engine = RapidOCR(**kw)
    except Exception:  # noqa: BLE001 - an older rapidocr without the thread keys
        engine = RapidOCR()
    return lambda image: engine(image)[0] or []


def _insightface_det_path() -> Path | None:
    root = Path(os.environ.get("INSIGHTFACE_HOME") or Path.home() / ".insightface").expanduser()
    path = root / "models" / "buffalo_l" / "det_10g.onnx"
    return path if path.is_file() else None


def make_face_detector(n_threads: int) -> Callable[[Any], list[tuple[float, float, float, float]]] | None:
    """InsightFace's face DETECTOR alone (buffalo_l/det_10g.onnx, already on every device for the identity QA; the
    full FaceAnalysis app would load all five buffalo_l models, ~1 GB), at 320 px; else OpenCV's Haar frontal face
    when this OpenCV build has it; else None (the caller treats an unchecked face as a reason not to repaint)."""
    import cv2  # noqa: PLC0415
    det = _insightface_det_path()
    if det is not None:
        try:
            from insightface.model_zoo import get_model  # type: ignore  # noqa: PLC0415
            model = get_model(str(det), providers=["CPUExecutionProvider"])
            model.prepare(ctx_id=-1, input_size=(320, 320), det_thresh=0.5)

            def detect(frame: Any) -> list[tuple[float, float, float, float]]:
                boxes, _ = model.detect(frame, input_size=(320, 320))
                return [tuple(float(v) for v in b[:4]) for b in boxes if float(b[4]) >= 0.5]
            return detect
        except Exception:  # noqa: BLE001
            pass
    if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def haar(frame: Any) -> list[tuple[float, float, float, float]]:
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return [(float(x), float(y), float(x + w), float(y + h)) for (x, y, w, h)
                    in cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))]
        return haar
    return None


class LamaInpainter:
    """LaMa ONNX on a W x W square of the strip centred on the masked rows, resized to 512; only masked pixels are
    written back.  Memory (2026-11-23, Mac): weights ~300 MB + activations ~500 MB per 512 px call; no CPU arena, no
    memory pattern and no weight pre-packing keep the session at ~0.85 GB peak (pre-packing costs +100 MB for ~5 %
    speed)."""

    def __init__(self, path: Path, n_threads: int) -> None:
        import onnxruntime as ort  # noqa: PLC0415
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(n_threads)
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False
        so.enable_mem_pattern = False
        so.add_session_config_entry("session.disable_prepacking", "1")
        self.session = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.calls = 0
        self.seconds = 0.0

    def __call__(self, strip: Any, mask: Any) -> Any:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        started = time.perf_counter()
        ys = np.nonzero(mask.any(axis=1))[0]
        if not len(ys):
            return strip
        h, w = strip.shape[:2]
        side = min(w, h)
        cy = int((ys.min() + ys.max()) / 2)
        y0 = int(np.clip(cy - side // 2, 0, h - side))
        x0 = int((w - side) // 2)
        crop, mcrop = strip[y0:y0 + side, x0:x0 + side], mask[y0:y0 + side, x0:x0 + side]
        img = cv2.resize(crop, (LAMA_SIDE, LAMA_SIDE), interpolation=cv2.INTER_AREA)
        m = (cv2.resize(mcrop, (LAMA_SIDE, LAMA_SIDE), interpolation=cv2.INTER_NEAREST) > 0).astype(np.float32)
        x = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.session.run(None, {"image": x, "mask": m[None, None]})[0][0].transpose(1, 2, 0)
        if out.max() <= 1.5:
            out = out * 255.0
        out = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        out = cv2.resize(out, (side, side), interpolation=cv2.INTER_CUBIC)
        res = strip.copy()
        sel = mcrop > 0
        res[y0:y0 + side, x0:x0 + side][sel] = out[sel]
        # mask pixels outside the square (a very wide strip) fall back to TELEA
        rest = mask.copy()
        rest[y0:y0 + side, x0:x0 + side] = 0
        if rest.any():
            res = cv2.inpaint(res, rest, 5, cv2.INPAINT_TELEA)
        self.calls += 1
        self.seconds += time.perf_counter() - started
        return res


# ------------------------------------------------------------------------------------------ propagation
def propagate(strips: list[Any], masks: list[Any], *, scale: float = FLOW_SCALE) -> list[Any]:
    """Fill the masked pixels of ``strips[1:-1]`` from the clean anchors ``strips[0]`` / ``strips[-1]`` (their masks
    are empty: LaMa keyframes) and from unmasked points of the frames in between, through chained DIS flow (option
    2-E of the prototype, restricted to one keyframe segment).  Unreached points: TELEA.  Returns the filled strips."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    n = len(strips)
    if n <= 2:
        return list(strips)
    h, w = strips[0].shape[:2]
    small = [cv2.cvtColor(cv2.resize(s, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
             for s in strips]
    sh, sw = small[0].shape[:2]
    msmall = [cv2.resize(m, (sw, sh), interpolation=cv2.INTER_NEAREST) > 0 for m in masks]
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)

    def fill_flow(fl: Any, bad: Any) -> Any:
        if not bad.any():
            return fl
        bad = cv2.dilate(bad.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        valid = (~bad).astype(np.float32)
        num = cv2.GaussianBlur(fl * valid[..., None], (0, 0), 25)
        den = cv2.GaussianBlur(valid, (0, 0), 25)[..., None]
        out = fl.copy()
        out[bad] = (num / np.maximum(den, 1e-4))[bad]
        return out

    def flow(a: int, b: int) -> Any:
        fl = fill_flow(dis.calc(small[a], small[b], None), msmall[a] | msmall[b])
        return cv2.resize(fl, (w, h), interpolation=cv2.INTER_LINEAR) / scale

    # per direction: for each inner frame, (src index map, src x, src y); -1 = no source yet
    chains: dict[int, dict[int, tuple[Any, Any, Any]]] = {-1: {}, 1: {}}
    for direction in (-1, 1):
        order = range(1, n - 1) if direction == -1 else range(n - 2, 0, -1)
        prev: tuple[Any, Any, Any] | None = None
        for t in order:
            nb = t + direction
            m = masks[t] > 0
            fl = flow(t, nb)
            px, py = gx + fl[..., 0], gy + fl[..., 1]
            inside = (px >= 0) & (px <= w - 1) & (py >= 0) & (py <= h - 1)
            nb_masked = cv2.remap(masks[nb], px, py, cv2.INTER_NEAREST) > 0
            src = np.full((h, w), -1, np.int16)
            sx = np.zeros((h, w), np.float32)
            sy = np.zeros((h, w), np.float32)
            direct = m & inside & ~nb_masked
            src[direct] = nb
            sx[direct] = px[direct]
            sy[direct] = py[direct]
            if prev is not None and nb not in (0, n - 1):
                psrc, psx, psy = prev
                chain = m & inside & nb_masked
                csrc = cv2.remap(psrc.astype(np.float32), px, py, cv2.INTER_NEAREST).astype(np.int16)
                cvalid = cv2.remap((psrc >= 0).astype(np.float32), px, py, cv2.INTER_LINEAR)
                cx = cv2.remap(psx, px, py, cv2.INTER_LINEAR)
                cy = cv2.remap(psy, px, py, cv2.INTER_LINEAR)
                ok = chain & (csrc >= 0) & (cvalid > 0.999)
                src[ok] = csrc[ok]
                sx[ok] = cx[ok]
                sy[ok] = cy[ok]
            prev = (src, sx, sy)
            chains[direction][t] = prev
    out = [strips[0]]
    for t in range(1, n - 1):
        f = strips[t].copy()
        m = masks[t] > 0
        if not m.any():
            out.append(f)
            continue
        best = np.full((h, w), -1, np.int16)
        bx = np.zeros((h, w), np.float32)
        by = np.zeros((h, w), np.float32)
        bestd = np.full((h, w), 1e9, np.float32)
        for direction in (-1, 1):
            src, sx, sy = chains[direction][t]
            dist = np.where(src >= 0, np.abs(src.astype(np.float32) - t), 1e9).astype(np.float32)
            better = dist < bestd
            best[better] = src[better]
            bx[better] = sx[better]
            by[better] = sy[better]
            bestd[better] = dist[better]
        for k in np.unique(best[m]):
            if k < 0:
                continue
            sel = m & (best == k)
            sample = cv2.remap(strips[int(k)], bx, by, cv2.INTER_LINEAR)
            f[sel] = sample[sel]
        resid = (m & (best < 0)).astype(np.uint8) * 255
        if resid.any():
            f = cv2.inpaint(f, resid, 5, cv2.INPAINT_TELEA)
        out.append(f)
    out.append(strips[-1])
    return out


def propagate_band(strips: list[Any], masks: list[Any], *, margin: int = PROP_MARGIN_PX) -> list[Any]:
    """:func:`propagate` on the rows that hold the segment's masks (+ ``margin`` px of context) only: the burned
    line is a ~60-150 px band, so flow maps and source chains are ~4x smaller than on the whole strip.  A point whose
    flow leaves the band gets no chain (TELEA residual), so ``margin`` must exceed the per-frame motion."""
    import numpy as np  # noqa: PLC0415
    rows = np.zeros(strips[0].shape[0], bool)
    for m in masks:
        rows |= m.any(axis=1)
    ys = np.nonzero(rows)[0]
    if not len(ys):
        return list(strips)
    b0, b1 = max(0, int(ys.min()) - margin), min(len(rows), int(ys.max()) + margin + 1)
    band = propagate([np.ascontiguousarray(s[b0:b1]) for s in strips], [np.ascontiguousarray(m[b0:b1]) for m in masks])
    out = []
    for s, f in zip(strips, band):
        full = s.copy()
        full[b0:b1] = f
        out.append(full)
    return out


# -------------------------------------------------------------------------------------------- video I/O
def probe(video: Path) -> dict[str, Any]:
    """frame rate string, frame count, duration, size, has audio (ffprobe; cv2 fallback for the counts)."""
    info: dict[str, Any] = {}
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration",
                              "-show_entries", "format=duration", "-of", "json", str(video)],
                             capture_output=True, text=True, timeout=60, check=True).stdout
        data = json.loads(out)
        vs = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), {})
        info.update(rate=vs.get("avg_frame_rate") if vs.get("avg_frame_rate") not in (None, "0/0")
                    else vs.get("r_frame_rate"), width=vs.get("width"), height=vs.get("height"),
                    nb_frames=int(vs["nb_frames"]) if str(vs.get("nb_frames") or "").isdigit() else None,
                    duration=float((data.get("format") or {}).get("duration") or vs.get("duration") or 0) or None,
                    has_audio=any(s.get("codec_type") == "audio" for s in data.get("streams") or []))
    except Exception:  # noqa: BLE001 - ffprobe missing: cv2 numbers below
        pass
    return info


def _rate_value(rate: str | None, fallback: float) -> float:
    try:
        a, _, b = str(rate).partition("/")
        return float(a) / float(b or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return fallback


def read_frames(video: Path) -> Iterable[Any]:
    import cv2  # noqa: PLC0415
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open {video}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


class Encoder:
    """ffmpeg rawvideo pipe -> H.264 (CRF 16) with the source's audio stream copied; same frame rate."""

    def __init__(self, out: Path, source: Path, w: int, h: int, rate: str, n_threads: int) -> None:
        self.out = out
        argv = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                "-r", str(rate), "-i", "-", "-i", str(source), "-map", "0:v:0", "-map", "1:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                "-threads", str(max(1, n_threads)), "-c:a", "copy", "-movflags", "+faststart", str(out)]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.frames = 0

    def write(self, frame: Any) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(frame.tobytes())
        self.frames += 1

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else ""
        if self.proc.wait(timeout=600) != 0:
            raise RuntimeError(f"ffmpeg encode failed: {err[-300:]}")

    def kill(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=30)
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------------------------------------- core
def detect_pass(video: Path, *, ocr: Callable[[Any], list] | None, face_detector: Callable[[Any], list] | None,
                n_threads: int, ocr_step: int, budget_s: float) -> dict[str, Any]:
    """Pass 1: OCR boxes of every ``ocr_step``-th frame (None for the others) and face boxes of up to FACE_SAMPLES
    text-bearing frames.  JSON-shaped, so it can run in a child process.  Never raises."""
    started = time.perf_counter()
    out: dict[str, Any] = {"n": 0, "w": 0, "h": 0, "raw": [], "texts": [], "ocr_frames": 0, "ocr_seconds": 0.0,
                           "faces": [], "face_check": "NONE_NEEDED"}
    try:
        import tail_frame_text_clean as _ttc  # noqa: PLC0415 - the S6 detector's filters
        ocr = ocr or make_ocr(n_threads)
        texts: set[str] = set()
        face_frames: list[tuple[int, Any]] = []   # (index, frame) candidates, thinned to keep memory flat
        for i, frame in enumerate(read_frames(video)):
            out["h"], out["w"] = frame.shape[:2]
            if i % max(1, ocr_step):
                out["raw"].append(None)
                continue
            s = time.perf_counter()
            found = _ttc.find_text_boxes(frame, ocr)
            out["ocr_seconds"] += time.perf_counter() - s
            out["ocr_frames"] += 1
            out["raw"].append([[float(b["x0"]), float(b["y0"]), float(b["x1"]), float(b["y1"])] for b in found])
            texts.update(str(b.get("text") or "") for b in found)
            if found:
                face_frames.append((i, frame))
                if len(face_frames) > 2 * FACE_SAMPLES:
                    face_frames = face_frames[::2]
            if i % 24 == 0 and time.perf_counter() - started > budget_s:
                out["budget_exceeded"] = True
                return out
        out["n"] = len(out["raw"])
        out["texts"] = sorted(t for t in texts if t)
        if face_frames:
            sampled = face_frames[::max(1, len(face_frames) // FACE_SAMPLES)][:FACE_SAMPLES]
            detector = face_detector or make_face_detector(n_threads)
            if detector is None:
                out["face_check"] = "UNAVAILABLE"
            else:
                out["face_check"] = "OK"
                out["faces"] = [[i, [list(map(float, f)) for f in detector(frame)]] for i, frame in sampled]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _run_child(args: list[str], n_threads: int, timeout_s: float) -> dict[str, Any]:
    """Run one pass of this module in a child process (its memory goes back to the OS when it exits)."""
    argv = [sys.executable, str(Path(__file__).resolve()), *args, "--threads", str(n_threads),
            "--max-seconds", f"{max(1.0, timeout_s):.1f}"]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=max(10.0, timeout_s) + 30.0)
    except subprocess.TimeoutExpired:
        return {"budget_exceeded": True, "status": "FAIL_OPEN", "error": "child timeout"}
    lines = [ln for ln in (done.stdout or "").splitlines() if ln.strip().startswith("{")]
    if done.returncode != 0 or not lines:
        return {"status": "FAIL_OPEN", "error": f"child exit {done.returncode}: {(done.stderr or '')[-300:]}"}
    try:
        return json.loads(lines[-1])
    except ValueError as exc:
        return {"status": "FAIL_OPEN", "error": f"child output: {exc}"}


def _not_applied(report: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    report.update(status=NOT_APPLIED, reason=reason, **extra)
    return report


def remove(video: Path, out: Path, *, n_threads: int | None = None, budget_s: float | None = None,
           env: dict[str, str] | None = None, ocr: Callable[[Any], list] | None = None,
           inpainter: Callable[[Any, Any], Any] | None = None,
           face_detector: Callable[[Any], list] | None = None,
           postcheck: Callable[[Path], dict[str, Any]] | None = None,
           lama_every: int = LAMA_EVERY, ocr_step: int = OCR_STEP) -> dict[str, Any]:
    """Clean burned caption text off ``video`` into ``out``.  Never raises.  ``out`` exists only when APPLIED.

    Injectables (tests / benchmarks): ``ocr`` (RapidOCR-shaped callable), ``inpainter`` (strip, mask) -> strip,
    ``face_detector`` frame -> boxes, ``postcheck`` path -> h3_burn_retry.detect-shaped dict."""
    n_threads = int(n_threads or threads(env))
    budget = float(budget_s if budget_s is not None else max_seconds(env))
    clock = Clock(budget)
    video, out = Path(video), Path(out)
    report: dict[str, Any] = {"schema": SCHEMA, "algo_version": ALGO_VERSION, "source": str(video),
                              "output": str(out), "threads": n_threads, "budget_seconds": budget,
                              "lama_every": lama_every, "ocr_step": ocr_step}
    tmp = out.with_name(out.stem + ".removing" + out.suffix)

    def finish(rep: dict[str, Any]) -> dict[str, Any]:
        rep["seconds"] = round(clock.elapsed(), 2)
        rep["stage_seconds"] = dict(clock.stages)
        rep["peak_rss_mb_after_stage"] = dict(clock.rss)
        rss = peak_rss_mb()
        rep["peak_rss_mb"] = rss.get("self")
        rep["peak_rss_children_mb"] = rss.get("children_max")
        if rep.get("status") != APPLIED:
            tmp.unlink(missing_ok=True)
        return rep

    if not enabled(env):
        return finish(_not_applied(report, "OPT_OUT"))
    if inpainter is None:
        mpath = model_path(env)
        if mpath is None:
            return finish(_not_applied(report, "MODEL_MISSING",
                                       model_hint=f"python -m tools.burned_text_removal --fetch-model "
                                                  f"(into {model_cache_dir(env)})"))
        report["model"] = str(mpath)
    encoder: Encoder | None = None
    try:
        cv2_threads(n_threads)
        import numpy as np  # noqa: PLC0415
        meta = probe(video)
        report["source_sha256"] = _sha256(video)

        # ---------------------------------------------------------------- pass 1: detect (+ faces)
        # in a child process unless engines were injected: RapidOCR (~0.45 GB) and the face detector (~0.1 GB) do not
        # give their memory back to the OS when released, and LaMa (~0.8 GB) comes next
        t0 = time.perf_counter()
        isolate = ocr is None and face_detector is None
        if isolate:
            det = _run_child(["--detect-pass", str(video), "--ocr-step", str(ocr_step)], n_threads,
                             max(1.0, budget - clock.elapsed()))
        else:
            det = detect_pass(video, ocr=ocr, face_detector=face_detector, n_threads=n_threads, ocr_step=ocr_step,
                              budget_s=max(1.0, budget - clock.elapsed()))
        clock.add("detect", time.perf_counter() - t0)
        if det.get("budget_exceeded"):
            raise BudgetExceeded("detect")
        if det.get("error"):
            return finish(_not_applied(report, "ERROR", error=str(det["error"])[:400]))
        n, w, h = int(det.get("n") or 0), int(det.get("w") or 0), int(det.get("h") or 0)
        if not n or not w:
            return finish(_not_applied(report, "NO_FRAMES"))
        raw = [None if row is None else [tuple(b) for b in row] for row in det["raw"]]
        boxes = fill_skipped(raw)
        flags = [bool(window_boxes(boxes, i)) for i in range(n)]
        burned_runs = runs(flags)
        kfs = sorted({k for r in burned_runs for k in keyframes(r, lama_every)})
        fps = _rate_value(meta.get("rate"), 24.0)
        ocr_frames = int(det.get("ocr_frames") or 0)
        report.update(frames=n, width=w, height=h, rate=meta.get("rate") or "24/1",
                      burned_frames=sum(flags), burned_runs=[list(r) for r in burned_runs], lama_keyframes=len(kfs),
                      ocr_frames=ocr_frames,
                      ocr_s_per_frame=round(float(det.get("ocr_seconds") or 0.0) / max(1, ocr_frames), 3),
                      texts=list(det.get("texts") or [])[:12],
                      **({"detect_child_peak_rss_mb": det["peak_rss_mb"]} if det.get("peak_rss_mb") else {}))
        if not burned_runs:
            return finish(_not_applied(report, "NO_TEXT_DETECTED"))

        # ---------------------------------------------------------------- guards
        area = max(text_area_fraction(window_boxes(boxes, i), w, h) for i in range(n) if flags[i])
        report["text_area_fraction"] = round(area, 4)
        if area > MAX_TEXT_AREA_FRACTION:
            return finish(_not_applied(report, "TEXT_AREA_TOO_LARGE"))
        if det.get("face_check") == "UNAVAILABLE":
            return finish(_not_applied(report, "FACE_CHECK_UNAVAILABLE"))
        worst = 0.0
        for i, faces in det.get("faces") or []:
            worst = max(worst, face_overlap(window_boxes(boxes, int(i)), [tuple(f) for f in faces]))
        report["face_overlap"] = worst
        if worst > FACE_OVERLAP_MAX:
            return finish(_not_applied(report, "TEXT_ON_FACE"))
        est = estimate_seconds(frames=n, burned=sum(flags), lama_calls=len(kfs),
                               ocr_s_per_frame=report["ocr_s_per_frame"], n_threads=n_threads, fps=fps)
        report["estimated_seconds"] = round(clock.elapsed() + est, 1)
        if clock.elapsed() + est > budget:
            return finish(_not_applied(report, "ESTIMATED_OVER_BUDGET"))
        post_est = (n / max(fps, 1.0)) * 4.0 * float(report["ocr_s_per_frame"] or REF_OCR_S) + 1.0

        # ---------------------------------------------------------------- pass 2: fill, streamed
        t0 = time.perf_counter()
        inpaint = inpainter or LamaInpainter(model_path(env), n_threads)  # type: ignore[arg-type]
        clock.add("lama_load", time.perf_counter() - t0)
        sy0, sy1 = int(h * STRIP_Y0), int(h * STRIP_Y1)
        if sy1 - sy0 < w:
            sy0 = max(0, sy1 - w)
        kfset = set(kfs)
        run_of = {i: r for r in burned_runs for i in range(r[0], r[1] + 1)}
        out.parent.mkdir(parents=True, exist_ok=True)
        encoder = Encoder(tmp, video, w, h, report["rate"], n_threads)
        t_fill = time.perf_counter()
        pending: list[tuple[Any, Any, Any]] = []  # (full frame, strip, mask) since the last keyframe
        anchor: Any = None                         # filled strip of the last keyframe in this run
        lama_s = 0.0
        frames_processed = 0
        for i, frame in enumerate(read_frames(video)):
            if i >= n:
                break
            if not flags[i]:
                encoder.write(frame)
                continue
            strip = frame[sy0:sy1]
            local = [(b[0], b[1] - sy0, b[2], b[3] - sy0) for b in window_boxes(boxes, i)]
            mask = stroke_mask(strip, local)
            if i not in kfset:
                pending.append((frame, strip.copy(), mask))
                continue
            s = time.perf_counter()
            filled_kf = inpaint(strip.copy(), mask)
            lama_s += time.perf_counter() - s
            if pending:
                if anchor is None:  # cannot happen (a run starts on a keyframe); stay safe
                    raise RuntimeError("segment without a leading keyframe")
                s = time.perf_counter()
                filled = propagate_band([anchor] + [p[1] for p in pending] + [filled_kf],
                                        [np.zeros_like(mask)] + [p[2] for p in pending] + [np.zeros_like(mask)])
                clock.add("propagate", time.perf_counter() - s)
                for (full, _strip, m), f in zip(pending, filled[1:-1]):
                    sel = m > 0
                    full[sy0:sy1][sel] = f[sel]
                    encoder.write(full)
                    frames_processed += 1
                pending = []
            sel = mask > 0
            frame[sy0:sy1][sel] = filled_kf[sel]
            encoder.write(frame)
            frames_processed += 1
            anchor = filled_kf if i != run_of[i][1] else None
            clock.check("fill")
            # project the rest from what this device has really spent so far: stop early instead of at the deadline
            done_kf = sum(1 for k in kfs if k <= i)
            per_kf = (time.perf_counter() - t_fill) / max(1, done_kf)
            projected = clock.elapsed() + per_kf * (len(kfs) - done_kf) + post_est
            if projected > budget:
                raise BudgetExceeded(f"projected {projected:.0f}s after {done_kf}/{len(kfs)} keyframes")
        if pending:
            raise RuntimeError("burned run ended without its closing keyframe")
        encoder.close()
        encoder = None
        clock.add("lama", lama_s)
        clock.add("fill_total", time.perf_counter() - t_fill)
        report.update(frames_processed=frames_processed,
                      lama_calls=getattr(inpaint, "calls", len(kfs)))
        del inpaint
        gc.collect()

        # ---------------------------------------------------------------- post-check
        t0 = time.perf_counter()
        after = probe(tmp)
        if meta.get("nb_frames") and after.get("nb_frames") and int(meta["nb_frames"]) != int(after["nb_frames"]):
            return finish(_not_applied(report, "FRAME_COUNT_CHANGED", frames_after=after.get("nb_frames")))
        if meta.get("duration") and after.get("duration") \
                and abs(float(meta["duration"]) - float(after["duration"])) > 1.5 / max(fps, 1.0):
            return finish(_not_applied(report, "DURATION_CHANGED", duration_before=meta.get("duration"),
                                       duration_after=after.get("duration")))
        if bool(meta.get("has_audio")) != bool(after.get("has_audio", meta.get("has_audio"))):
            return finish(_not_applied(report, "AUDIO_STREAM_LOST"))
        if postcheck is not None:
            check = postcheck(tmp)
        elif ocr is not None:
            import h3_burn_retry as _br  # noqa: PLC0415
            check = _br.detect(tmp, ocr=ocr)
        else:  # the S6 detector in a child process, like the detect pass
            check = _run_child(["--postcheck-pass", str(tmp)], n_threads, max(30.0, budget - clock.elapsed() + 30.0))
        clock.add("postcheck", time.perf_counter() - t0)
        report["postcheck"] = {k: check.get(k) for k in ("status", "frames_sampled", "burned_frames", "longest_run",
                                                          "error") if check.get(k) is not None}
        report["postcheck"]["texts"] = sorted({str(x.get("text")) for x in check.get("hits") or []})[:8]
        if check.get("status") == "FAIL_OPEN":
            return finish(_not_applied(report, "POSTCHECK_UNAVAILABLE"))
        if check.get("status") != "CLEAN" or int(check.get("burned_frames") or 0) > 0:
            return finish(_not_applied(report, "POSTCHECK_TEXT_REMAINS"))
        clock.check("postcheck")
        os.replace(tmp, out)
        report.update(status=APPLIED, reason="CLEANED", output_sha256=_sha256(out))
        return finish(report)
    except BudgetExceeded as exc:
        if encoder is not None:
            encoder.kill()
        return finish(_not_applied(report, "BUDGET_EXCEEDED", at_stage=str(exc)))
    except Exception as exc:  # noqa: BLE001 - fail-open: the original take is used
        if encoder is not None:
            encoder.kill()
        return finish(_not_applied(report, "ERROR", error=f"{type(exc).__name__}: {exc}"[:400]))


# ------------------------------------------------------------------------------------------ S7 planning
#: strict burned-line verdicts (tools of the strict check, 2026-11-23); only ACCEPT_CORRECT keeps the burned line
ACCEPT_CORRECT = "ACCEPT_CORRECT"
#: final-fix round record statuses after which no further paid redo of an S6-unresolved unit is coming
ROUND_SETTLED = ("DONE", "NOT_NEEDED", "NO_ACTIONABLE_FIX", "DISABLED", "S7_RERUN", "S6_REDO_PENDING")
REPORT_SCHEMA = "nalu.s7_burned_text_removal.v1"


def strict_verdict(record: dict[str, Any] | None, take_sha256: str | None) -> str | None:
    """The strict burned-line verdict recorded for ``take_sha256`` in an S6 / final-fix record, or None.

    Accepted shapes: ``strict_burn_verdict`` (str), ``strict_burn`` / ``strict_burn_check`` ({verdict, take_sha256?}),
    and the same keys inside ``checks[<take sha>]``.  A verdict bound to another take is ignored."""
    if not isinstance(record, dict):
        return None
    places = [record, ((record.get("checks") or {}).get(take_sha256) or {}) if take_sha256 else {}]
    for place in places:
        if not isinstance(place, dict):
            continue
        for key in ("strict_burn", "strict_burn_check"):
            row = place.get(key)
            if isinstance(row, dict) and row.get("verdict"):
                bound = row.get("take_sha256") or row.get("clip_sha256")
                if bound and take_sha256 and bound != take_sha256:
                    continue
                return str(row["verdict"])
        if place.get("strict_burn_verdict"):
            bound = place.get("strict_burn_take_sha256")
            if bound and take_sha256 and bound != take_sha256:
                continue
            return str(place["strict_burn_verdict"])
    return None


def burnin_verdicts(report: dict[str, Any] | None) -> dict[str, list[str]]:
    """unit -> strict verdicts of its lines from a ``<EP>_BURNIN_SUBTITLES.json`` (``burned_line_checks``, written by
    build_burnin_subtitles' strict burned-line check)."""
    out: dict[str, list[str]] = {}
    for row in (report or {}).get("burned_line_checks") or []:
        if isinstance(row, dict) and row.get("unit_id") and row.get("verdict"):
            out.setdefault(str(row["unit_id"]), []).append(str(row["verdict"]))
    return out


def plan_targets(*, s6_records: dict[str, Any], redo_records: dict[str, Any], round_status: str | None,
                 rounds_enabled: bool, pending: Iterable[str], clip_sha: Callable[[str], str | None],
                 line_verdicts: dict[str, list[str]] | None = None
                 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Which units S7 may clean locally now (pure; I/O through ``clip_sha``).  Returns (targets, skipped).

    A unit is a target only when every paid option is spent and its kept take is still the unit's clip:
    * FINAL_FIX_UNRESOLVED -- its final-fix redo record ``burn_status`` is UNRESOLVED and kept the current clip; or
    * S6_UNRESOLVED -- the S6 record is ``burned_text_unresolved`` with the current clip kept, AND the final fix round
      is settled for the episode (record present) or switched off; before the round ran the unit waits for it
      (AWAITING_FINAL_FIX_ROUND: the round may still buy a redo);
    and its strict burned-line verdict is not ACCEPT_CORRECT (absent = REJECT).  The verdict comes from the unit's
    record (:func:`strict_verdict`) or from ``line_verdicts`` (unit -> verdict of each of its lines, the last S7
    pass's strict check; the unit counts as ACCEPT_CORRECT only when every line is).  A unit parked for a final-fix redo,
    a superseded take and a take that only leaked the reference sheet (no text) are skipped."""
    pending = set(map(str, pending or []))
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    units = sorted({str(u) for u, r in (s6_records or {}).items() if isinstance(r, dict) and r.get("burned_text_unresolved")}
                   | {str(u) for u, r in (redo_records or {}).items()
                      if isinstance(r, dict) and r.get("burn_status") == "UNRESOLVED"})
    for uid in units:
        s6 = (s6_records or {}).get(uid) if isinstance((s6_records or {}).get(uid), dict) else {}
        redo = (redo_records or {}).get(uid) if isinstance((redo_records or {}).get(uid), dict) else {}

        def skip(reason: str, **extra: Any) -> None:
            skipped.append({"unit_id": uid, "reason": reason, **extra})
        if uid in pending:
            skip("FINAL_FIX_REDO_PENDING")
            continue
        sha = clip_sha(uid)
        if not sha:
            skip("CLIP_MISSING")
            continue
        if redo.get("burn_status") == "UNRESOLVED" and redo.get("kept_take_sha256") == sha:
            stage, rec = "FINAL_FIX_UNRESOLVED", redo
        elif s6.get("burned_text_unresolved") and s6.get("kept_take_sha256") == sha:
            if s6.get("kept_take_sheet_leak") and not int(s6.get("kept_take_burned_frames") or 0):
                skip("SHEET_LEAK_WITHOUT_TEXT")
                continue
            if rounds_enabled and round_status not in ROUND_SETTLED:
                skip("AWAITING_FINAL_FIX_ROUND")
                continue
            stage, rec = "S6_UNRESOLVED", s6
        else:
            skip("KEPT_TAKE_SUPERSEDED")
            continue
        verdict = strict_verdict(rec, sha) or strict_verdict(s6, sha)
        lines = list((line_verdicts or {}).get(uid) or [])
        if not verdict and lines:
            verdict = ACCEPT_CORRECT if all(v == ACCEPT_CORRECT for v in lines) else \
                next(v for v in lines if v != ACCEPT_CORRECT)
        if verdict == ACCEPT_CORRECT:
            skip("BURNED_LINE_ACCEPTED_CORRECT", verdict=verdict)
            continue
        targets.append({"unit_id": uid, "stage": stage, "take_sha256": sha,
                        "strict_verdict": verdict or "ABSENT_TREATED_AS_REJECT"})
    return targets, skipped


def cached_row(report: dict[str, Any] | None, uid: str, source_sha256: str) -> dict[str, Any] | None:
    """The unit's earlier result for exactly this input + algorithm (an S7 re-run does not spend CPU twice).
    A budget skip is not cached (more budget may be left now); an APPLIED row needs its output intact."""
    row = ((report or {}).get("units") or {}).get(uid)
    if not isinstance(row, dict) or row.get("source_sha256") != source_sha256 or row.get("algo_version") != ALGO_VERSION:
        return None
    if row.get("reason") in ("BUDGET_EXCEEDED", "ESTIMATED_OVER_BUDGET", "EPISODE_BUDGET_SPENT", "MODEL_MISSING",
                             "OPT_OUT", "ERROR", "SUBPROCESS_FAILED"):
        return None
    if row.get("status") == APPLIED:
        out = Path(str(row.get("output") or ""))
        if not out.is_file() or _sha256(out) != row.get("output_sha256"):
            return None
    return row


def applied_sources(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """unit -> APPLIED row ({source, source_sha256, output, output_sha256}) for the AgentCut builder; the builder
    still checks both shas on disk before it uses a cleaned clip."""
    out = {}
    for uid, row in ((report or {}).get("units") or {}).items():
        if isinstance(row, dict) and row.get("status") == APPLIED and row.get("output") and row.get("source"):
            out[str(uid)] = row
    return out


# ------------------------------------------------------------------------------------------------- CLI
def benchmark(video: Path, n_threads: int, budget_s: float) -> dict[str, Any]:
    """One full removal into a temp dir (no budget skip unless it really runs past ``budget_s``)."""
    with tempfile.TemporaryDirectory(prefix="nalu_text_removal_bench_") as tmp:
        rep = remove(video, Path(tmp) / "clean.mp4", n_threads=n_threads, budget_s=budget_s,
                     env={**os.environ, ENV_FLAG: "1"})
    keys = ("status", "reason", "seconds", "stage_seconds", "peak_rss_mb", "peak_rss_children_mb", "frames",
            "burned_frames", "frames_processed", "lama_calls", "peak_rss_mb_after_stage", "ocr_s_per_frame", "estimated_seconds", "threads",
            "face_overlap", "text_area_fraction", "postcheck", "error")
    return {"benchmark": True, "cpu_count": os.cpu_count(), "platform": sys.platform,
            **{k: rep.get(k) for k in keys if rep.get(k) is not None}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clip", nargs="?", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--report", type=Path, help="write the JSON result here as well")
    ap.add_argument("--threads", type=int, default=None, help=f"CPU threads (default ${ENV_THREADS} or 2)")
    ap.add_argument("--max-seconds", type=float, default=None, help=f"budget (default ${ENV_MAX_SECONDS} or 240)")
    ap.add_argument("--benchmark", type=Path, metavar="CLIP", help="time one removal: seconds / peak RSS / frames")
    ap.add_argument("--fetch-model", action="store_true", help="download the pinned LaMa model into the cache")
    ap.add_argument("--check-model", action="store_true", help="print the verified model path or MISSING")
    ap.add_argument("--ocr-step", type=int, default=OCR_STEP, help=argparse.SUPPRESS)
    ap.add_argument("--detect-pass", type=Path, help=argparse.SUPPRESS)      # internal: pass 1 in a child process
    ap.add_argument("--postcheck-pass", type=Path, help=argparse.SUPPRESS)   # internal: post-check in a child process
    a = ap.parse_args(argv)
    if a.detect_pass or a.postcheck_pass:
        n = int(a.threads or threads())
        cv2_threads(n)
        if a.detect_pass:
            res = detect_pass(a.detect_pass, ocr=None, face_detector=None, n_threads=n, ocr_step=a.ocr_step,
                              budget_s=float(a.max_seconds or max_seconds()))
        else:
            import h3_burn_retry as _br  # noqa: PLC0415
            res = _br.detect(a.postcheck_pass, ocr=make_ocr(n))
        res["peak_rss_mb"] = peak_rss_mb().get("self")
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if a.fetch_model:
        res = fetch_model()
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["status"] in ("READY", "FETCHED") else 1
    if a.check_model:
        path = model_path()
        print(json.dumps({"status": "READY" if path else "MISSING", "path": str(path) if path else None,
                          "cache_dir": str(model_cache_dir())}))
        return 0 if path else 1
    if a.benchmark:
        res = benchmark(a.benchmark, int(a.threads or threads()),
                        float(a.max_seconds if a.max_seconds is not None else 3600.0))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("status") == APPLIED else 1
    if not a.clip or not a.out:
        ap.error("CLIP and --out are required (or --benchmark / --fetch-model / --check-model)")
    res = remove(a.clip, a.out, n_threads=a.threads, budget_s=a.max_seconds)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
