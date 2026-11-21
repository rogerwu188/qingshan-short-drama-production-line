#!/usr/bin/env python3
"""Reference-sheet leak guard for MiniMax-H3 clips (JA-01 E04 VU-007, device 1485, 2026-11-21).

CAMERA_GRAMMAR_V1 units send each character's multi-view reference sheet
(``lines/nalu/runtime/tools/character_reference_sheet.py``: a front face close-up on top, full-body front / side /
back views below, plain grey background) as that character's H3 identity reference.  On JA-01 E04 VU-007 H3 drew the
SHEET ITSELF as the picture (bust + big face close-up + three full bodies over the background); the S6 burned-text
check then called the take CLEAN (no text) and Q2 passed it.  The final review flagged it P0 twice.

Free, local pieces (no provider call):

* :func:`front_view_box` / :func:`crop_front_view` -- the sheet layout is known (the identity builder's prompt asks for
  the face close-up panel on top, the three full bodies below, separated by background), so the face panel is cut out
  of the sheet: the first band of non-background rows down to the first background gap.  Sent instead of the sheet on
  a retry / redo after a leak (``h3_reference_sheet_crop`` task field, submitter send-time transform; the compiled
  task, its prompt and the source reference shas are unchanged).
* :func:`detect_leak` -- does a landed clip show the sheet?  Coarse, blurred grey-level AND gradient template matching of every
  identity sheet the unit referenced against frames sampled at ~2 fps (TM_CCOEFF_NORMED over a few scales).  A copy of
  the sheet layout scores high; an ordinary performance shot of the same character does not, because the multi-panel
  layout (inset close-up over three standing figures on flat grey) does not occur in a shot.  ADVISORY: a hit makes the
  S6 burn check treat the take like burned text (retry with the cropped reference, best take, fix round, KB);
  it never blocks.  Fails open.
"""
from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = "qingshan.s6_reference_sheet_leak.v1"
SHEET_MARK = "__MULTIVIEW_REFERENCE_SHEET"
TASK_FIELD = "h3_reference_sheet_crop"
QA_ITEM = "QA-REFERENCE-SHEET-LEAK"
KIND = "REFERENCE_SHEET_LEAK"

SAMPLE_FPS = 2.0
MIN_CONSECUTIVE = 2
#: :func:`sheet_score` at or above this is the sheet in the picture (see sheet_score for the calibration)
LEAK_SCORE = 0.55
WORK_WIDTH = 144
SCALES = (1.0, 0.9, 0.8, 0.7, 0.6)

#: background distance (0-255 per channel, max over channels) above which a sheet pixel is "content"
_BG_DIST = 26
_ROW_CONTENT = 0.015
_GAP_ROWS = 0.012


def is_sheet_path(value: Any) -> bool:
    return SHEET_MARK in str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


# ------------------------------------------------------------------------------------------ front-view crop
def _background(pixels: Any, w: int, h: int) -> tuple[int, int, int]:
    """Median colour of the four corner patches (the sheet's flat grey background)."""
    k = max(2, min(w, h) // 40)
    samples = []
    for x0, y0 in ((0, 0), (w - k, 0), (0, h - k), (w - k, h - k)):
        for y in range(y0, y0 + k):
            for x in range(x0, x0 + k):
                samples.append(pixels[x, y])
    return tuple(sorted(s[c] for s in samples)[len(samples) // 2] for c in range(3))  # type: ignore[return-value]


def front_view_box(image: Any) -> tuple[tuple[int, int, int, int], str]:
    """(box, method) of the face close-up panel of a multi-view sheet (PIL RGB image).

    ``CONTENT_GAP``: the first band of content rows from the top down to the first background gap (>= 1.2 % of the
    height) found between 18 % and 60 % of the height, columns trimmed to the content of that band (+ 4 % margin).
    ``LAYOUT_FALLBACK``: the builder's layout when no gap is found -- the top 36 %, middle 70 % of the width."""
    small = image.convert("RGB")
    w0, h0 = small.size
    scale = 256.0 / max(w0, h0)
    if scale < 1:
        small = small.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))))
    w, h = small.size
    px = small.load()
    bg = _background(px, w, h)

    def content(x: int, y: int) -> bool:
        p = px[x, y]
        return max(abs(p[0] - bg[0]), abs(p[1] - bg[1]), abs(p[2] - bg[2])) > _BG_DIST

    rows = [sum(1 for x in range(w) if content(x, y)) / float(w) for y in range(h)]
    top = next((y for y, r in enumerate(rows) if r > _ROW_CONTENT), None)
    gap_need = max(2, int(round(_GAP_ROWS * h)))
    bottom = None
    if top is not None:
        run = 0
        for y in range(top, int(0.60 * h)):
            run = run + 1 if rows[y] <= _ROW_CONTENT else 0
            if run >= gap_need and y - run + 1 >= int(0.18 * h):
                bottom = y - run + 1
                break
    sx, sy = w0 / float(w), h0 / float(h)
    if top is None or bottom is None or bottom - top < 0.12 * h:
        return (int(0.15 * w0), 0, int(0.85 * w0), int(0.36 * h0)), "LAYOUT_FALLBACK"
    cols = [x for x in range(w) if sum(1 for y in range(top, bottom) if content(x, y)) > 0.02 * (bottom - top)]
    x0, x1 = (min(cols), max(cols) + 1) if cols else (int(0.15 * w), int(0.85 * w))
    mx, my = int(0.04 * w), int(0.02 * h)
    box = (max(0, x0 - mx), max(0, top - my), min(w, x1 + mx), min(h, bottom + my))
    return (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy)), "CONTENT_GAP"


def crop_front_view(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """The sheet's face close-up panel as JPEG bytes + a note.  Never raises; undecodable -> the bytes unchanged."""
    note: dict[str, Any] = {"sha256_before": hashlib.sha256(data).hexdigest()}
    try:
        from PIL import Image  # noqa: PLC0415
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            work = image.convert("RGB")
        box, method = front_view_box(work)
        crop = work.crop(box)
        out = io.BytesIO()
        crop.save(out, format="JPEG", quality=92)
        encoded = out.getvalue()
        return encoded, {**note, "status": "CROPPED_FRONT_VIEW", "method": method, "box": list(box),
                         "size": list(work.size), "sha256_after": hashlib.sha256(encoded).hexdigest()}
    except Exception as exc:  # noqa: BLE001 - the sheet is sent as before
        return data, {**note, "status": "SKIPPED_UNDECODABLE", "error": f"{type(exc).__name__}: {exc}"[:200]}


def crop_requested(task: dict[str, Any] | None) -> bool:
    """A task asks for front-view crops of its sheets: ``h3_reference_sheet_crop`` (S6 leak retry) or a final-fix
    redo whose kinds include REFERENCE_SHEET_LEAK."""
    task = task or {}
    machine = task.get("machine_contract") or {}
    if task.get(TASK_FIELD) or machine.get(TASK_FIELD):
        return True
    fix = task.get("h3_final_fix") or machine.get("h3_final_fix")
    return isinstance(fix, dict) and KIND in (fix.get("kinds") or [fix.get("kind")])


# ------------------------------------------------------------------------------------------------ detection
FrameReader = Callable[[Path, float], Iterable[tuple[float, Any]]]


def _work(image: Any, width: int, mode: str) -> Any:
    """Grey (``int``) or Sobel gradient magnitude (``edge``) at ``width``, blurred: the coarse layout only."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    out = cv2.resize(gray, (width, max(8, int(round(h * width / float(w))))),
                     interpolation=cv2.INTER_AREA).astype(np.float32)
    if mode == "edge":
        out = cv2.magnitude(cv2.Sobel(out, cv2.CV_32F, 1, 0), cv2.Sobel(out, cv2.CV_32F, 0, 1))
    return cv2.GaussianBlur(out, (5, 5), 1.5)


def _match(frame: Any, sheet: Any, mode: str) -> float:
    import cv2  # noqa: PLC0415
    f = _work(frame, WORK_WIDTH, mode)
    fh, fw = f.shape[:2]
    best = -1.0
    for s in SCALES:
        t = _work(sheet, max(8, int(round(fw * s))), mode)
        if t.shape[0] > fh:  # the sheet is taller than the frame at this width: fit its height instead
            t = cv2.resize(t, (max(8, int(round(t.shape[1] * fh / float(t.shape[0])))), fh))
        if t.shape[0] > fh or t.shape[1] > fw or float(t.std()) < 1e-3:
            continue
        best = max(best, float(cv2.matchTemplate(f, t, cv2.TM_CCOEFF_NORMED).max()))
    return best


def sheet_score(frame: Any, sheet: Any) -> float:
    """How strongly the frame shows the sheet's layout: the lower of the grey-level and the gradient-magnitude
    TM_CCOEFF_NORMED (blurred, over SCALES).  Calibrated on lab clips 2026-11-21 against 9 real sheets: ordinary
    shots max 0.48 (gradient) / 0.59 (grey); a sheet pasted, re-toned and blurred into a frame min 0.60 / 0.60."""
    return round(min(_match(frame, sheet, "int"), _match(frame, sheet, "edge")), 4)


def detect_leak(video: Path, sheets: list[Path], *, fps: float = SAMPLE_FPS, frames: FrameReader | None = None,
                threshold: float = LEAK_SCORE, min_consecutive: int = MIN_CONSECUTIVE) -> dict[str, Any]:
    """Does the clip show one of the unit's identity sheets as its picture?  Never raises.

    ``status``: LEAK (score >= threshold in >= min_consecutive consecutive samples), CLEAN, NO_SHEET (the unit sent
    no sheet) or FAIL_OPEN.  ``leak_frames`` counts the samples over the threshold (the best-take measure)."""
    started = time.perf_counter()
    out: dict[str, Any] = {"schema": SCHEMA, "video": str(video), "fps": fps, "threshold": threshold,
                           "min_consecutive": min_consecutive, "sheets": [str(p) for p in sheets]}
    sheets = [Path(p) for p in sheets if Path(p).is_file()]
    if not sheets:
        out.update(status="NO_SHEET", leak_frames=0)
        return out
    try:
        import cv2  # noqa: PLC0415
        plates = [(p, cv2.imread(str(p))) for p in sheets]
        plates = [(p, img) for p, img in plates if img is not None]
        if not plates:
            raise ValueError("no sheet decodable")
        if frames is None:
            import h3_burn_retry as _br  # noqa: PLC0415 - same directory
            frames = _br._cv2_frames
        flags: list[bool] = []
        hits: list[dict[str, Any]] = []
        best = -1.0
        for t, image in frames(Path(video), fps):
            score, which = max(((sheet_score(image, img), p.name) for p, img in plates), key=lambda r: r[0])
            best = max(best, score)
            flags.append(score >= threshold)
            if score >= threshold:
                hits.append({"t": t, "score": score, "sheet": which})
        run = longest = 0
        for flag in flags:
            run = run + 1 if flag else 0
            longest = max(longest, run)
        out.update(status="LEAK" if longest >= min_consecutive else "CLEAN", frames_sampled=len(flags),
                   leak_frames=sum(flags), longest_run=longest, best_score=round(best, 4), hits=hits[:20])
    except Exception as exc:  # noqa: BLE001 - advisory detector: never blocks
        out.update(status="FAIL_OPEN", error=f"{type(exc).__name__}: {exc}"[:300], leak_frames=0)
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return out


def unit_sheets(task: dict[str, Any] | None, resolve: Callable[[Any], Path] | None = None) -> list[Path]:
    """The identity sheets a compiled video task sent (``reference_images`` whose name carries the sheet mark)."""
    refs = list((task or {}).get("reference_images") or [])
    out = []
    for ref in refs:
        value = ref.get("path") if isinstance(ref, dict) else ref
        if is_sheet_path(value):
            out.append(resolve(value) if resolve else Path(str(value)))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    ap = argparse.ArgumentParser(description="S6 reference-sheet leak check on a raw H3 clip (local, free)")
    ap.add_argument("video", type=Path)
    ap.add_argument("sheets", nargs="+", type=Path)
    args = ap.parse_args(argv)
    result = detect_leak(args.video, args.sheets)
    print(json.dumps({k: result.get(k) for k in ("status", "frames_sampled", "leak_frames", "best_score",
                                                  "elapsed_ms", "error") if k in result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
