#!/usr/bin/env python3
"""Build E44's captioned 2K YouTube/Douyin release package."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_e41_release_package import render_subtitle_png, stamp

PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
GROUPED = PROD / "E44_V5_GROUPED_SEEDANCE_MANIFEST_COMPILED_V1.json"
MASTER = ROOT / "working_assets/e44_v5_final/E44_V5_SD2_STANDARD_9X16_MASTER_CANDIDATE_A2_REPAIRED_V1.mp4"
MEDIA_MAP = ROOT / "qa/e44_v5_final/E44_V5_ACCEPTED_MEDIA_MAP_25_OF_25_A2_REPAIRED_V1.json"
CONTENT_LOCK = ROOT / "qa/e44_v5_final/E44_V5_FINAL_CONTENT_LOCK_V1.json"
OUTRO = ROOT / "working_assets/e41_v17_final/E41_V17_NALU_OUTRO_V1.mp4"
OUT_DIR = ROOT / "deliverables/e44"
PNG_DIR = ROOT / "working_assets/e44_v5_final/subtitle_png_v1"
SRT = OUT_DIR / "E44_V5_SCRIPT_EQUIVALENT_SUBTITLES_V1.srt"
FINAL = OUT_DIR / "E44_V5_SD2_STANDARD_9X16_2K_YOUTUBE_DOUYIN_FINAL_V1.mp4"
TRIM_PLAN = ROOT / "qa/e44_v5_final/E44_V5_YOUTUBE_SHORTS_TRIM_PLAN_V1.json"
CAPTION_ALIGNMENT = ROOT / "qa/e44_v5_final/E44_V5_SCRIPT_CAPTION_ALIGNMENT_V1.json"
RELEASE_QA = ROOT / "qa/e44_v5_final/E44_V5_RELEASE_PACKAGE_QA_V1.json"
TAIL_TRIMS = {"E44-VU-009": 1.5, "E44-VU-019": 1.5}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def main() -> int:
    grouped, media_map, content_lock = load(GROUPED), load(MEDIA_MAP), load(CONTENT_LOCK)
    if not str(content_lock.get("status", "")).startswith("PASS_FINAL_CONTENT_LOCK"):
        raise RuntimeError("E44 content lock is not PASS")
    if media_map.get("selected_unit_count") != 25 or abs(float(media_map["planned_runtime_seconds"]) - 180.0) > 0.001:
        raise RuntimeError("E44 accepted media map is not exact 25/25/180")
    units = {row["unit_id"]: row for row in grouped["units"]}
    segments, source_cursor, output_cursor = [], 0.0, 0.0
    for row in media_map["rows"]:
        uid = row["unit_id"]
        source_duration = float(row["planned_duration_seconds"])
        trim = float(TAIL_TRIMS.get(uid, 0.0))
        if trim and any(spec.get("dialogue") for spec in units[uid]["ordered_prompt_specs"]):
            raise RuntimeError(f"tail trim is not dialogue-free: {uid}")
        kept = source_duration - trim
        segments.append({
            "unit_id": uid,
            "source_start": round(source_cursor, 6),
            "source_end": round(source_cursor + source_duration, 6),
            "source_duration": source_duration,
            "tail_trim_seconds": trim,
            "kept_duration": kept,
            "output_start": round(output_cursor, 6),
            "output_end": round(output_cursor + kept, 6),
            "dialogue_free_trim": bool(trim),
        })
        source_cursor += source_duration
        output_cursor += kept
    if abs(source_cursor - 180.0) > 0.001 or abs(output_cursor - 177.0) > 0.001:
        raise RuntimeError(f"release timeline mismatch: {source_cursor}/{output_cursor}")
    write(TRIM_PLAN, {
        "schema": "qingshan.e44.v5.youtube_shorts_trim_plan.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS_177S_CONTENT_PLUS_3S_NALU_OUTRO_NATIVE_AUDIO_SAFE",
        "policy": "Trim 1.5 seconds only from the dialogue-free tails of E44-VU-009 and E44-VU-019; never cut registered dialogue or change playback speed.",
        "source_runtime_seconds": 180.0,
        "content_runtime_seconds": 177.0,
        "outro_runtime_seconds": 3.0,
        "segments": segments,
    })

    segment_by_unit = {row["unit_id"]: row for row in segments}
    captions = []
    dialogue_index = 0
    for uid in [row["unit_id"] for row in media_map["rows"]]:
        unit = units[uid]
        specs = unit["ordered_prompt_specs"]
        unit_origin = float(specs[0]["action"]["t0_seconds"])
        authored_span = float(specs[-1]["action"]["t1_seconds"]) - unit_origin
        planned = float(segment_by_unit[uid]["source_duration"])
        kept = float(segment_by_unit[uid]["kept_duration"])
        scale = planned / authored_span
        for spec in specs:
            raw = str(spec.get("dialogue") or "").strip()
            if not raw:
                continue
            speaker, separator, spoken = raw.partition("：")
            if not separator:
                speaker, separator, spoken = raw.partition(":")
            if not separator:
                raise RuntimeError(f"dialogue lacks speaker separator: {uid}:{raw}")
            local_start = (float(spec["action"]["t0_seconds"]) - unit_origin) * scale
            local_end = (float(spec["action"]["t1_seconds"]) - unit_origin) * scale
            if local_start < -0.001 or local_end > kept + 0.001 or local_end <= local_start:
                raise RuntimeError(f"caption exceeds retained unit: {uid}")
            dialogue_index += 1
            captions.append({
                "dialogue_id": f"E44-DIA-{dialogue_index:03d}",
                "unit_id": uid,
                "speaker": speaker.strip(),
                "text": spoken.strip(),
                "start": round(float(segment_by_unit[uid]["output_start"]) + local_start, 6),
                "end": round(float(segment_by_unit[uid]["output_start"]) + local_end, 6),
                "timing_method": "AUTHORITATIVE_GROUPED_BEAT_WINDOW_REBASED_TO_ACCEPTED_UNIT_TIMELINE",
            })
    captions.sort(key=lambda row: row["start"])
    if len(captions) != 31:
        raise RuntimeError(f"caption coverage is not exact 31/31: {len(captions)}")
    for previous, current in zip(captions, captions[1:]):
        if current["start"] < previous["end"] - 0.001:
            raise RuntimeError(f"caption intervals overlap: {previous['dialogue_id']}->{current['dialogue_id']}")
    write(CAPTION_ALIGNMENT, {
        "schema": "qingshan.e44.v5.script_caption_alignment.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS_EXACT_31_OF_31_SCRIPT_EQUIVALENT",
        "caption_count": len(captions),
        "captions": captions,
        "source_grouped_manifest": {"ref": rel(GROUPED), "sha256": sha(GROUPED)},
        "accepted_media_map": {"ref": rel(MEDIA_MAP), "sha256": sha(MEDIA_MAP)},
    })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SRT.write_text("\n".join(
        f"{index}\n{stamp(row['start'])} --> {stamp(row['end'])}\n{row['text']}\n"
        for index, row in enumerate(captions, 1)
    ), encoding="utf-8")
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    pngs = []
    for index, caption in enumerate(captions, 1):
        png = PNG_DIR / f"subtitle_{index:02d}.png"
        render_subtitle_png(caption["text"], png)
        pngs.append(png)

    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(MASTER), "-i", str(OUTRO)]
    for png, caption in zip(pngs, captions):
        command += ["-loop", "1", "-framerate", "24", "-t", f"{caption['end'] - caption['start']:.6f}", "-i", str(png)]
    filters, concat_inputs = [], []
    for index, row in enumerate(segments, 1):
        end = row["source_start"] + row["kept_duration"]
        filters.append(f"[0:v]trim=start={row['source_start']:.6f}:end={end:.6f},setpts=PTS-STARTPTS,fps=24,format=yuv420p[v{index}]")
        filters.append(f"[0:a]atrim=start={row['source_start']:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]")
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + "concat=n=25:v=1:a=1[contentv0][contenta]")
    subtitle_pieces, subtitle_cursor = [], 0.0
    for piece_index, (input_index, row) in enumerate(zip(range(2, 2 + len(captions)), captions), 1):
        if row["start"] > subtitle_cursor + 0.0005:
            label = f"[gap{piece_index}]"
            filters.append(f"color=c=black:s=720x1280:r=24:d={row['start'] - subtitle_cursor:.6f},format=rgba,colorchannelmixer=aa=0{label}")
            subtitle_pieces.append(label)
        label = f"[cap{piece_index}]"
        filters.append(f"[{input_index}:v]trim=duration={row['end'] - row['start']:.6f},setpts=PTS-STARTPTS,format=rgba{label}")
        subtitle_pieces.append(label)
        subtitle_cursor = row["end"]
    if subtitle_cursor < 177.0 - 0.0005:
        label = "[gaptail]"
        filters.append(f"color=c=black:s=720x1280:r=24:d={177.0 - subtitle_cursor:.6f},format=rgba,colorchannelmixer=aa=0{label}")
        subtitle_pieces.append(label)
    filters.append("".join(subtitle_pieces) + f"concat=n={len(subtitle_pieces)}:v=1:a=0[subtitletrack]")
    filters.append("[contentv0][subtitletrack]overlay=0:0:shortest=1[captioned]")
    filters.append("[1:v]trim=duration=3,setpts=PTS-STARTPTS,fps=24,scale=720:1280,format=yuv420p[outrov]")
    filters.append("[1:a]atrim=duration=3,asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[outroa]")
    filters.append("[captioned][contenta][outrov][outroa]concat=n=2:v=1:a=1[joinedv][outa]")
    filters.append("[joinedv]scale=1440:2560:flags=lanczos,setsar=1[outv]")
    result = run(command + [
        "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
        "-map", "[outv]", "-map", "[outa]", "-t", "180",
        "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(FINAL),
    ])
    if result.returncode:
        raise RuntimeError(result.stderr[-12000:])
    info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(FINAL)]).stdout)
    video = next(row for row in info["streams"] if row.get("codec_type") == "video")
    audio = next(row for row in info["streams"] if row.get("codec_type") == "audio")
    duration = float(info["format"]["duration"])
    failures = []
    if (int(video["width"]), int(video["height"])) != (1440, 2560):
        failures.append("NOT_2K_1440X2560")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        failures.append("CODEC_CONTRACT_FAILED")
    if not 179.90 <= duration <= 180.05:
        failures.append("RUNTIME_NOT_180_SECONDS")
    visual = run(["ffmpeg", "-hide_banner", "-i", str(FINAL), "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=2", "-an", "-f", "null", "-"]).stderr
    audio_log = run(["ffmpeg", "-hide_banner", "-i", str(FINAL), "-af", "silencedetect=noise=-50dB:d=2,volumedetect", "-vn", "-f", "null", "-"]).stderr
    visual_events = [line for line in visual.splitlines() if "black_start" in line or "freeze_start" in line]
    unexpected = []
    registered_outro = []
    for event in visual_events:
        match = re.search(r"freeze_start:\s*([0-9.]+)", event)
        if match and float(match.group(1)) >= 177.0:
            registered_outro.append(event)
        else:
            unexpected.append(event)
    silence = [line for line in audio_log.splitlines() if "silence_start" in line]
    if unexpected or silence:
        failures.append("FINAL_PLAYBACK_DIAGNOSTIC_FAILED")
    qa = {
        "schema": "qingshan.e44.v5.release_package_qa.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS_RELEASE_PACKAGE_READY_FOR_ORDERED_PUBLICATION" if not failures else "FAIL",
        "title": "《青山》E44：金猪／上三位",
        "description": "十两买诗，密谍司金猪夜访；陈迹拿到的第一件差事，是盯住世子。#青山 #AI短剧 #古装悬疑",
        "release_master": rel(FINAL),
        "release_master_sha256": sha(FINAL),
        "duration_seconds": duration,
        "video": {"codec": video["codec_name"], "width": int(video["width"]), "height": int(video["height"]), "pixel_format": video.get("pix_fmt"), "delivery": "2K_LANCZOS_UPSCALE_FROM_PROVIDER_NATIVE_720P"},
        "audio": {"codec": audio["codec_name"], "native_same_task_audio_chain_preserved": True},
        "subtitle_track": rel(SRT),
        "subtitle_line_count": len(captions),
        "subtitle_policy": "31_OF_31_CANONICAL_SCRIPT_EQUIVALENT_GROUPED_BEAT_ALIGNED",
        "caption_alignment": {"ref": rel(CAPTION_ALIGNMENT), "sha256": sha(CAPTION_ALIGNMENT)},
        "trim_plan": {"ref": rel(TRIM_PLAN), "sha256": sha(TRIM_PLAN)},
        "content_lock": {"ref": rel(CONTENT_LOCK), "sha256": sha(CONTENT_LOCK)},
        "outro": {"brand": "NALU_MOTION", "duration_seconds": 3.0, "source": rel(OUTRO), "sha256": sha(OUTRO)},
        "diagnostics": {"unexpected_visual_events": unexpected, "registered_outro_events": registered_outro, "silence_events": silence},
        "failures": failures,
        "publication_order": ["YOUTUBE", "DOUYIN"],
    }
    write(RELEASE_QA, qa)
    print(json.dumps({"status": qa["status"], "release_master": rel(FINAL), "duration_seconds": duration, "resolution": "1440x2560"}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
