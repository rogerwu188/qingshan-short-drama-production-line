#!/usr/bin/env python3
"""
Character anchor auditor for Qingshan-style short-drama episodes.

This tool is intentionally portable: Python 3.8+, ffmpeg, and Pillow only.
It does not pretend to be a perfect face-recognition model. Its job is to make
S-level character continuity auditable and release-blocking by producing a
reference-vs-shot evidence sheet for every shot where the character appears.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FFMPEG_CANDIDATES = [
    "ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    str(
        Path(
            os.environ.get(
                "QINGSHAN_FACTORY_ROOT",
                Path(__file__).resolve().parents[1],
            )
        )
        / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
    ),
]


def find_ffmpeg(explicit: Optional[str]) -> str:
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    env_ffmpeg = os.environ.get("FFMPEG")
    if env_ffmpeg:
        candidates.append(env_ffmpeg)
    candidates.extend(DEFAULT_FFMPEG_CANDIDATES)
    for item in candidates:
        found = shutil.which(item) if os.path.basename(item) == item else item
        if found and Path(found).exists() and os.access(found, os.X_OK):
            return found
    raise SystemExit("ffmpeg not found. Pass --ffmpeg /path/to/ffmpeg.")


def run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def load_config(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_timeline(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    cursor = 0.0
    timeline: List[Dict[str, Any]] = []
    for idx, shot in enumerate(config.get("shots") or []):
        item = dict(shot)
        item["shot_id"] = str(item.get("shot_id") or item.get("id") or f"{idx + 1:02d}")
        if "start" in item and "end" in item:
            start = float(item["start"])
            end = float(item["end"])
        else:
            duration = float(item.get("duration", item.get("seconds", 8)))
            start = cursor
            end = start + duration
            cursor = end
        item["start"] = start
        item["end"] = end
        item["midpoint"] = start + max(0.0, end - start) / 2.0
        timeline.append(item)
    return timeline


def target_visible_characters(shot: Dict[str, Any]) -> List[str]:
    visible = shot.get("anchor_visible_characters")
    if isinstance(visible, list):
        return [str(item) for item in visible]
    return [str(item) for item in (shot.get("characters") or [])]


def anchor_timestamp_for(shot: Dict[str, Any], character: str) -> float:
    times = shot.get("character_anchor_times") or {}
    if isinstance(times, dict) and character in times:
        value = times[character]
        if isinstance(value, str) and value.endswith("%"):
            try:
                ratio = float(value[:-1]) / 100.0
                return float(shot["start"]) + max(0.0, float(shot["end"]) - float(shot["start"])) * ratio
            except ValueError:
                pass
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return float(shot["midpoint"])


def extract_frame(ffmpeg: str, video: Path, timestamp: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-y",
            str(out_path),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", errors="ignore"))


def probe_duration(ffmpeg: str, video: Path) -> float:
    proc = run([ffmpeg, "-hide_banner", "-i", str(video)])
    text = (proc.stderr or b"").decode("utf-8", errors="ignore")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def fit_image(path: Path, size: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (16, 17, 20))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple, text: str) -> None:
    draw.text(xy, text, fill=(245, 245, 245))


def make_contact_sheet(reference: Path, frames: List[Dict[str, Any]], out_path: Path, title: str) -> None:
    tile = 220
    pad = 14
    label_h = 58
    columns = 4
    cards = [{"kind": "REFERENCE", "path": str(reference), "label": "REFERENCE"}] + frames
    rows = (len(cards) + columns - 1) // columns
    width = columns * tile + (columns + 1) * pad
    height = rows * (tile + label_h) + (rows + 1) * pad + 44
    sheet = Image.new("RGB", (width, height), (12, 13, 16))
    draw = ImageDraw.Draw(sheet)
    draw_label(draw, (pad, 12), title)
    for idx, card in enumerate(cards):
        col = idx % columns
        row = idx // columns
        x = pad + col * (tile + pad)
        y = 44 + pad + row * (tile + label_h + pad)
        img = fit_image(Path(card["path"]), tile)
        sheet.paste(img, (x, y))
        draw.rectangle((x, y, x + tile - 1, y + tile - 1), outline=(80, 82, 88))
        draw_label(draw, (x, y + tile + 8), str(card.get("label", ""))[:36])
        if card.get("note"):
            draw_label(draw, (x, y + tile + 28), str(card["note"])[:36])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Build release-blocking character anchor evidence.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--fail-on-review", action="store_true")
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    reference = Path(args.reference).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")
    if not reference.exists():
        raise SystemExit(f"Reference image not found: {reference}")

    ffmpeg = find_ffmpeg(args.ffmpeg)
    config = load_config(config_path)
    timeline = build_timeline(config)
    duration = probe_duration(ffmpeg, video)
    target_shots = [shot for shot in timeline if args.character in target_visible_characters(shot)]
    frames_dir = out_dir / "frames"
    evidence_frames: List[Dict[str, Any]] = []
    for shot in target_shots:
        midpoint = anchor_timestamp_for(shot, args.character)
        if duration > 0:
            midpoint = min(midpoint, max(0.0, duration - 0.10))
        frame_path = frames_dir / f"{args.character}_{shot['shot_id']}_{midpoint:07.2f}s.jpg"
        extract_frame(ffmpeg, video, midpoint, frame_path)
        evidence_frames.append(
            {
                "shot_id": shot["shot_id"],
                "path": str(frame_path),
                "label": f"{shot['shot_id']} {shot.get('title', '')}",
                "note": f"{shot['start']:.1f}-{shot['end']:.1f}s",
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / f"{args.character}_anchor_contact_sheet.jpg"
    make_contact_sheet(
        reference,
        evidence_frames,
        sheet_path,
        f"{args.character} anchor audit: reference vs {len(evidence_frames)} shots",
    )

    anchor = (config.get("character_anchors") or {}).get(args.character, {})
    report = {
        "episode_id": config.get("episode_id") or config.get("episode") or video.stem,
        "video": str(video),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "character": args.character,
        "reference": str(reference),
        "shot_count": len(evidence_frames),
        "contact_sheet": str(sheet_path),
        "expected": anchor.get("expected_face") or anchor.get("expected"),
        "expected_costume": anchor.get("expected_costume"),
        "forbidden": anchor.get("forbidden", []),
        "release_gate": "REVIEW_REQUIRED",
        "diagnosis": (
            "S/A-level character identity cannot pass only from scene hash. "
            "Review the contact sheet before release; if face, hair, or costume drifts, repair the material/storyboard row and regenerate video."
        ),
        "frames": evidence_frames,
    }
    (out_dir / f"{args.character}_anchor_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_lines = [
        f"# Character Anchor Audit: {args.character}",
        "",
        f"- Video: `{video}`",
        f"- Reference: `{reference}`",
        f"- Contact sheet: `{sheet_path}`",
        f"- Shots sampled: `{len(evidence_frames)}`",
        f"- Release gate: `{report['release_gate']}`",
        "",
        "## Expected",
        "",
        f"- Face: {report.get('expected') or 'See character library.'}",
        f"- Costume: {report.get('expected_costume') or 'See character library.'}",
        f"- Forbidden: {', '.join(report.get('forbidden') or [])}",
        "",
        "## Verdict",
        "",
        "This report is release-blocking for S/A-level roles. If the contact sheet does not visually match the reference, do not publish.",
        "",
    ]
    (out_dir / f"{args.character}_anchor_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(str(sheet_path))
    return 2 if args.fail_on_review else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
