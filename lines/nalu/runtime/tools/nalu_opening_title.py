"""Free opening-title overlay for the S7 release picture (line owner 2026-10-22: every episode needs a
proper opening and ending).

The series title (brief ``title``) is drawn large and the episode line (``EPISODE 01 · <episode title>`` /
``第一集 · <集名>``) small, centred in the upper third, over the first ``TITLE_SECONDS`` of the
picture with a fade in/out.  Faces in those seconds are detected (InsightFace, the engine's own backend; device 1101
E24 2026-11-23: the title sat on the heroine's eyes) and the title block moves to the first band that clears them:
upper third, then the top band, then the lower band above the subtitle band (:func:`choose_title_band`).  It never changes the duration: the video is re-encoded, the audio stream
is copied.  Nothing here is paid; a missing brief title or font only skips the overlay (the caller
records the reason) and never blocks S7.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import nalu_media_tools as _media

TITLE_SECONDS = 2.5
FADE_SECONDS = 0.5
MAX_WIDTH_RATIO = 0.88
#: candidate centres of the title block (fraction of the frame height), in order of preference
TITLE_BANDS = (("UPPER_THIRD", 1.0 / 3.0), ("TOP", 0.14), ("LOWER", 0.64))
#: the burned-in subtitles sit bottom-centre with a 170/1280 px margin: the title block stays above this line
SUBTITLE_BAND_TOP = 0.76
TOP_MARGIN = 0.04
FACE_MARGIN = 0.03          # a face box is grown by this much (fraction of the height) on each side
FACE_SAMPLE_TIMES = (0.25, 0.75, 1.25, 1.75, 2.25)
ZH_NUMERALS = "零一二三四五六七八九"


def brief_path(runtime_root: Path, episode: str) -> Path:
    return Path(runtime_root) / "briefs" / f"{episode}_PRODUCTION_BRIEF.json"


def load_brief(runtime_root: Path, episode: str) -> dict[str, Any]:
    try:
        payload = json.loads(brief_path(runtime_root, episode).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def episode_number(episode: str) -> int | None:
    match = re.search(r"(\d+)\s*$", str(episode or ""))
    return int(match.group(1)) if match else None


def zh_number(n: int) -> str:
    if n < 10:
        return ZH_NUMERALS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return (("" if tens == 1 else ZH_NUMERALS[tens]) + "十" + (ZH_NUMERALS[ones] if ones else ""))
    return str(n)


def display_number(brief: dict[str, Any], episode: str) -> int | None:
    """Brief ``episode_display_number`` (the series' own count, e.g. E03 = 第2集) else the EP number."""
    try:
        value = int(brief.get("episode_display_number"))
    except (TypeError, ValueError):
        return episode_number(episode)
    return value if value > 0 else episode_number(episode)


def title_lines(brief: dict[str, Any], episode: str, language: str) -> tuple[str, str]:
    """(series title, episode line); the series title is '' when the brief has none."""
    series = str(brief.get("title") or "").strip()
    ep_title = str(brief.get("episode_title") or "").strip()
    number = display_number(brief, episode)
    if language == "en":
        head = f"EPISODE {number:02d}" if number is not None else str(episode)
    elif language in ("ja", "ko"):  # 第N話 / 제N화 (lang_profile.episode_label)
        head = {"ja": f"第{number}話", "ko": f"제{number}화"}[language] if number is not None else str(episode)
    else:
        head = f"第{zh_number(number)}集" if number is not None else str(episode)
    return series, (f"{head} · {ep_title}" if ep_title else head)


def resolve_font(language: str) -> tuple[str, str]:
    if language == "en":
        return _media.resolve_latin_font()
    if language in ("ja", "ko"):  # a face that carries kana / Hangul (Noto Sans CJK JP / KR, Hiragino, SD Gothic)
        return _media.resolve_language_font(language)
    return _media.resolve_cjk_font()


def _fit(draw: Any, text: str, font_file: str, size: int, min_size: int, max_width: float) -> tuple[Any, int, list[str]]:
    from PIL import ImageFont

    for size_try in range(size, min_size - 1, -2):
        font = ImageFont.truetype(font_file, size_try)
        if draw.textlength(text, font=font) <= max_width:
            return font, size_try, [text]
    if " · " in text:
        lines = [part.strip() for part in text.split(" · ", 1)]
    elif " " in text.strip():
        words = text.split()
        cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    else:
        mid = (len(text) + 1) // 2
        lines = [text[:mid], text[mid:]]
    for size_try in range(size, 7, -2):
        font = ImageFont.truetype(font_file, size_try)
        if max(draw.textlength(line, font=font) for line in lines) <= max_width:
            return font, size_try, lines
    return ImageFont.truetype(font_file, 8), 8, lines


def choose_title_band(height: int, block_height: float, faces: list[list[float]] | None) -> dict[str, Any]:
    """The title block's top y: the first of ``TITLE_BANDS`` whose block (clamped between the top margin and the
    subtitle band) overlaps no face box (``[x1, y1, x2, y2]`` px, grown by FACE_MARGIN); none clear -> the band with
    the least overlap.  Pure."""
    grow = FACE_MARGIN * height
    boxes = [(float(b[1]) - grow, float(b[3]) + grow) for b in faces or [] if len(b) >= 4]
    lo_limit, hi_limit = TOP_MARGIN * height, SUBTITLE_BAND_TOP * height - block_height
    rows = []
    for name, centre in TITLE_BANDS:
        top = min(max(centre * height - block_height / 2.0, lo_limit), max(lo_limit, hi_limit))
        overlap = sum(max(0.0, min(top + block_height, y2) - max(top, y1)) for y1, y2 in boxes)
        rows.append({"band": name, "top": int(round(top)), "face_overlap_px": round(overlap, 1)})
    clear = next((r for r in rows if r["face_overlap_px"] <= 0.0), None)
    best = clear or min(rows, key=lambda r: r["face_overlap_px"])
    return {**best, "faces": len(boxes), "candidates": rows, "clear_of_faces": clear is not None}


def detect_faces(source: Path, *, times: tuple[float, ...] = FACE_SAMPLE_TIMES) -> list[list[float]]:
    """Face boxes ([x1, y1, x2, y2] px) on a few frames of the title seconds (InsightFace, CPU)."""
    try:
        import push_in_compensation as _pic
    except ModuleNotFoundError:  # pragma: no cover - engine root on sys.path instead of tools/
        from tools import push_in_compensation as _pic  # type: ignore
    app = _pic.face_backend()
    ffmpeg = _media.require_ffmpeg()
    boxes = []
    for t in times:
        image = _pic.frame_at(Path(source), t, ffmpeg)
        if image is None:
            continue
        for face in app.get(image):
            if float(getattr(face, "det_score", 0.0)) >= 0.5:
                boxes.append([round(float(v), 1) for v in face.bbox[:4]])
    return boxes


def render_overlay_png(series: str, episode_line: str, font_file: str, width: int, height: int, out: Path,
                       faces: list[list[float]] | None = None) -> dict[str, Any]:
    """Transparent full-frame PNG with the two title lines centred horizontally, in the band that clears ``faces``
    (upper third when there are none)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    max_width = width * MAX_WIDTH_RATIO
    scale = width / 720.0
    big, big_size, big_lines = _fit(draw, series, font_file, int(84 * scale), int(44 * scale), max_width)
    small, small_size, small_lines = _fit(draw, episode_line, font_file, int(38 * scale), int(26 * scale), max_width)
    rows = [(line, big, big_size, (240, 214, 150, 255)) for line in big_lines]
    rows += [(line, small, small_size, (236, 230, 220, 255)) for line in small_lines]
    gap = int(18 * scale)
    total = sum(int(size * 1.25) for _, _, size, _ in rows) + gap
    placement = choose_title_band(height, total, faces)
    y = placement["top"]
    widest = 0.0
    for index, (line, font, size, colour) in enumerate(rows):
        if index == len(big_lines):
            y += gap
        line_width = draw.textlength(line, font=font)
        widest = max(widest, line_width)
        draw.text(((width - line_width) / 2, y), line, font=font, fill=colour,
                  stroke_width=max(2, size // 18), stroke_fill=(0, 0, 0, 200))
        y += int(size * 1.25)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return {"png": str(out), "title_font_px": big_size, "episode_font_px": small_size,
            "widest_line_px": round(widest, 1), "max_width_px": round(max_width, 1),
            "placement": {k: placement[k] for k in ("band", "top", "faces", "clear_of_faces", "candidates")}}


def probe_size(source: Path) -> tuple[int, int]:
    probe = subprocess.run([_media.require_ffprobe(), "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source)],
                           capture_output=True, text=True, check=False)
    width, height = (int(v) for v in probe.stdout.strip().split("x")[:2])
    return width, height


def overlay_argv(source: Path, png: Path, out: Path) -> list[str]:
    fade_out = TITLE_SECONDS - FADE_SECONDS
    graph = (f"[1:v]format=rgba,fade=t=in:st=0:d={FADE_SECONDS}:alpha=1,"
             f"fade=t=out:st={fade_out}:d={FADE_SECONDS}:alpha=1[title];"
             f"[0:v][title]overlay=0:0:eof_action=pass:enable='between(t,0,{TITLE_SECONDS})',format=yuv420p[v]")
    return [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-loop", "1", "-t", str(TITLE_SECONDS), "-i", str(png),
            "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(out)]


def apply_opening_title(*, runtime_root: Path, episode: str, language: str, source: Path, out: Path) -> dict[str, Any]:
    """Overlay the opening title.  Returns {"status": APPLIED|SKIPPED|FAILED, ...}; never raises."""
    try:
        brief = load_brief(runtime_root, episode)
        series, episode_line = title_lines(brief, episode, language)
        if not series:
            return {"status": "SKIPPED", "reason": f"NO_BRIEF_TITLE:{brief_path(runtime_root, episode)}"}
        try:
            font_file, font_source = resolve_font(language)
        except _media.MediaToolBlocked as exc:
            return {"status": "SKIPPED", "reason": f"NO_TITLE_FONT:{exc}"}
        width, height = probe_size(source)
        png = out.with_suffix(".title.png")
        try:
            faces, face_note = detect_faces(source), None
        except Exception as exc:  # noqa: BLE001 -- no face backend: the upper third, as before
            faces, face_note = [], f"FACE_DETECTION_UNAVAILABLE:{type(exc).__name__}"
        layout = render_overlay_png(series, episode_line, font_file, width, height, png, faces=faces)
        if face_note:
            layout["face_detection"] = face_note
        run = subprocess.run(overlay_argv(source, png, out), capture_output=True, text=True, check=False)
        if run.returncode != 0 or not out.is_file():
            return {"status": "FAILED", "reason": f"OPENING_TITLE_FFMPEG_FAILED:{(run.stderr or '')[-300:]}"}
        return {"status": "APPLIED", "picture": str(out), "source": str(source), "series_title": series,
                "episode_line": episode_line, "language": language, "font": font_file,
                "font_source": font_source, "seconds": TITLE_SECONDS, "fade_seconds": FADE_SECONDS,
                "adds_duration": False, "audio": "stream copy", **layout}
    except Exception as exc:  # noqa: BLE001 -- packaging must never block S7
        return {"status": "FAILED", "reason": f"OPENING_TITLE_ERROR:{type(exc).__name__}:{exc}"}
