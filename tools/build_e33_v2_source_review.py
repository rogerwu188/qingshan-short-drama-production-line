#!/usr/bin/env python3
"""Select E33 v2 source videos and build three-point visual/audio evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723"
CONFIG = PRODUCTION / "video_performance_v2/E33_VIDEO_FINAL_PERFORMANCE_V2.json"
R3 = ROOT / "workflow/tasks/E33_VIDEO_FINAL_PERFORMANCE_V2_SUPERVISOR_R3.json"
R6 = ROOT / "workflow/tasks/E33_VIDEO_FINAL_PERFORMANCE_V2_IDENTITY_TRANSPORT_PROBE_U01_R6.json"
R7 = ROOT / "workflow/tasks/E33_VIDEO_FINAL_PERFORMANCE_V2_IDENTITY_TRANSPORT_REPAIR_REMAINING_R7.json"
R8 = ROOT / "workflow/tasks/E33_VIDEO_FINAL_PERFORMANCE_V2_U16_NATIVE_CAPTION_REPAIR_R8.json"
U16_REPAIR = ROOT / "workflow/tasks/E33_U16_R8_NATIVE_CAPTION_PIXEL_INPAINT_REPAIR_20260723.json"
OUT_DIR = ROOT / "qa/e33_v2_final_video_source_review_20260723"
SELECTION = PRODUCTION / "video_performance_v2/E33_VIDEO_SOURCE_SELECTION_V2.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    proc = subprocess.run(
        [
            str(FFPROBE), "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    streams = payload.get("streams", [])
    return {
        "duration_seconds": float(payload["format"]["duration"]),
        "video_stream_count": sum(row.get("codec_type") == "video" for row in streams),
        "audio_stream_count": sum(row.get("codec_type") == "audio" for row in streams),
        "audio_codecs": [row.get("codec_name") for row in streams if row.get("codec_type") == "audio"],
        "audio_sample_rates": [row.get("sample_rate") for row in streams if row.get("codec_type") == "audio"],
    }


def extract_frame(video: Path, timestamp: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG), "-y", "-ss", f"{timestamp:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=270:480:force_original_aspect_ratio=decrease,"
            "pad=270:480:(ow-iw)/2:(oh-ih)/2:black", "-q:v", "2", str(out),
        ],
        check=True,
        capture_output=True,
    )


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def receipt_task(receipt: Path, unit_id: str) -> dict:
    matches = [row for row in load(receipt).get("tasks", []) if row.get("unit_id") == unit_id]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {unit_id} task in {receipt}")
    return matches[0]


def selected_task(unit_id: str) -> tuple[Path, dict]:
    if unit_id == "E33-CW-U01":
        return R6, receipt_task(R6, unit_id)
    if unit_id == "E33-CW-U09":
        return R3, receipt_task(R3, unit_id)
    if unit_id == "E33-CW-U16" and U16_REPAIR.is_file():
        repair = load(U16_REPAIR)
        if repair.get("status") == "PASS_LOCAL_CAPTION_REMOVAL_AUDIO_PRESERVED":
            remote = receipt_task(R8, unit_id)
            return U16_REPAIR, {
                "output_path": repair["output"]["path"],
                "sha256": repair["output"]["sha256"],
                "state": "qa_pass_local_caption_repair",
                "task_id": remote.get("task_id"),
                "qa": {
                    "status": "PASS_LOCAL_CAPTION_REMOVAL_AUDIO_PRESERVED",
                    "original_remote_qa": remote.get("qa"),
                    "repair_receipt": str(U16_REPAIR),
                    "post_repair_qa": repair.get("post_repair_qa"),
                },
            }
    return R7, receipt_task(R7, unit_id)


def build_sheet(rows: list[dict], page_index: int) -> Path:
    card_width = 860
    card_height = 530
    canvas = Image.new("RGB", (card_width, card_height * len(rows)), (20, 20, 22))
    draw = ImageDraw.Draw(canvas)
    title_font = font(24)
    body_font = font(17)
    for index, row in enumerate(rows):
        top = index * card_height
        status = row["source_state"]
        audio = row["media_probe"]["audio_stream_count"]
        draw.text((12, top + 8), f"{row['unit_id']} | {status} | audio={audio}", fill="white", font=title_font)
        draw.text((12, top + 42), f"SHA {row['sha256'][:16]} | {row['media_probe']['duration_seconds']:.3f}s", fill=(185, 190, 198), font=body_font)
        for frame_index, frame_path in enumerate(row["review_frames"]):
            image = Image.open(frame_path).convert("RGB")
            x = 12 + frame_index * 282
            canvas.paste(image, (x, top + 72))
    out = OUT_DIR / f"E33_V2_SOURCE_REVIEW_PAGE_{page_index:02d}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=92)
    return out


def main() -> int:
    config = load(CONFIG)
    rows = []
    for task in config["tasks"]:
        unit_id = task["unit_id"]
        receipt, source = selected_task(unit_id)
        video = Path(source["output_path"])
        expected_sha = source["sha256"]
        if not video.is_file() or sha256(video) != expected_sha:
            raise SystemExit(f"missing or SHA-mismatched source: {video}")
        media = probe(video)
        if media["video_stream_count"] != 1:
            raise SystemExit(f"invalid video stream count for {unit_id}")
        timestamps = [
            max(0.1, media["duration_seconds"] * 0.15),
            media["duration_seconds"] * 0.50,
            max(0.1, media["duration_seconds"] * 0.85),
        ]
        frame_paths = []
        for frame_index, timestamp in enumerate(timestamps, 1):
            frame_path = OUT_DIR / "frames" / f"{unit_id}_{frame_index}_{timestamp:.3f}.jpg"
            extract_frame(video, timestamp, frame_path)
            frame_paths.append(str(frame_path))
        rows.append({
            "unit_id": unit_id,
            "task_key": task["task_key"],
            "source_receipt": str(receipt),
            "source_state": source.get("state") or source.get("status"),
            "remote_task_id": source.get("task_id"),
            "output_path": str(video),
            "sha256": expected_sha,
            "original_qa": source.get("qa"),
            "media_probe": media,
            "review_timestamps_seconds": [round(value, 6) for value in timestamps],
            "review_frames": frame_paths,
            "dialogue": task.get("dialogue", []),
        })

    pages = []
    for start in range(0, len(rows), 6):
        pages.append(str(build_sheet(rows[start:start + 6], start // 6 + 1)))
    result = {
        "schema": "qingshan.e33.video_source_selection.v2",
        "episode": "E33",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "SOURCE_COVERAGE_COMPLETE_VISUAL_REVIEW_REQUIRED",
        "source_count": len(rows),
        "source_policy": "U01_R6_TRANSPORT_PROBE;U09_R3_REUSE;U16_R8_PIXEL_INPAINT_IF_QA_PASS;ALL_OTHERS_R7",
        "all_sources_have_audio_stream": all(row["media_probe"]["audio_stream_count"] > 0 for row in rows),
        "contact_sheets": pages,
        "rows": rows,
    }
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    SELECTION.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "source_count": result["source_count"],
        "all_sources_have_audio_stream": result["all_sources_have_audio_stream"],
        "selection": str(SELECTION),
        "contact_sheets": pages,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
