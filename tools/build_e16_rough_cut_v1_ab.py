#!/usr/bin/env python3
"""Build E16 rough cut v1 with A dialogue audio and muted B reaction visuals."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
EDL = BASE / "configs/e16_ordered_edit_decision_list_20260713.json"
OUT_DIR = BASE / "exports/e16/rough_cut_20260713/ab_reaction_assembly_v1"
SEG_DIR = OUT_DIR / "segments"
OUT_MP4 = OUT_DIR / "qingshan_E16_ab_reaction_assembly_v1_20260713.mp4"


SCALE_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p"
)


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(
            "Command failed:\n"
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + proc.stdout[-2000:]
            + "\nSTDERR:\n"
            + proc.stderr[-4000:]
        )


def segment_plan(seg: dict[str, Any]) -> dict[str, float]:
    duration = float(seg["target_duration"])
    requested_b = float((seg.get("b_insert") or {}).get("duration") or 0.0)
    if requested_b <= 0 or duration < 1.2:
        return {"before": duration, "b": 0.0, "after": 0.0}

    b_dur = min(requested_b, max(0.35, duration * 0.35), 0.75)
    before = max(0.45, duration - b_dur - 0.15)
    if before + b_dur > duration:
        before = max(0.25, duration - b_dur)
    after = max(0.0, duration - before - b_dur)
    return {"before": round(before, 3), "b": round(b_dur, 3), "after": round(after, 3)}


def build_segment(index: int, seg: dict[str, Any]) -> dict[str, Any]:
    dialogue_id = seg["dialogue_id"]
    a_id = seg["a_source_id"]
    a_path = Path(seg["a_video_path"])
    b = seg.get("b_insert") or {}
    b_path = Path(b.get("video_path") or "")
    out = SEG_DIR / f"{index:03d}_{dialogue_id}_{a_id}_ab.mp4"
    a_in = float(seg["a_in"])
    duration = float(seg["target_duration"])
    plan = segment_plan(seg)

    if plan["b"] <= 0 or not b_path.exists():
        filters = (
            f"[0:v]trim=start={a_in}:duration={duration},setpts=PTS-STARTPTS,{SCALE_FILTER}[v];"
            f"[0:a]atrim=start={a_in}:duration={duration},asetpts=PTS-STARTPTS,"
            "aresample=48000,aformat=channel_layouts=stereo[a]"
        )
        cmd = [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(a_path),
            "-filter_complex",
            filters,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    else:
        before = plan["before"]
        b_dur = plan["b"]
        after = plan["after"]
        labels = [
            f"[0:v]trim=start={a_in}:duration={before},setpts=PTS-STARTPTS,{SCALE_FILTER}[av1]",
            f"[1:v]trim=start=0.15:duration={b_dur},setpts=PTS-STARTPTS,{SCALE_FILTER}[bv]",
        ]
        concat_inputs = "[av1][bv]"
        concat_n = 2
        if after > 0.05:
            labels.append(
                f"[0:v]trim=start={a_in + before + b_dur}:duration={after},"
                f"setpts=PTS-STARTPTS,{SCALE_FILTER}[av2]"
            )
            concat_inputs += "[av2]"
            concat_n = 3
        labels.append(f"{concat_inputs}concat=n={concat_n}:v=1:a=0[v]")
        labels.append(
            f"[0:a]atrim=start={a_in}:duration={duration},asetpts=PTS-STARTPTS,"
            "aresample=48000,aformat=channel_layouts=stereo[a]"
        )
        cmd = [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(a_path),
            "-i",
            str(b_path),
            "-filter_complex",
            ";".join(labels),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(out),
        ]
    run(cmd)
    return {
        "index": index,
        "dialogue_id": dialogue_id,
        "a_source_id": a_id,
        "b_source_id": b.get("source_id"),
        "segment_path": str(out),
        "target_duration": duration,
        "visual_plan": plan,
        "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_ONLY_B_VISUAL_MUTED",
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(EDL.read_text(encoding="utf-8"))
    segments = data["segments"]
    built = [build_segment(i, seg) for i, seg in enumerate(segments, start=1)]

    concat_file = OUT_DIR / "concat.txt"
    concat_file.write_text("".join(f"file '{item['segment_path']}'\n" for item in built), encoding="utf-8")
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(OUT_MP4),
        ]
    )

    plan = {
        "schema": "qingshan.e16.rough_cut_v1_ab_build_plan.v1",
        "episode": "E16",
        "status": "BUILT_PENDING_QA",
        "edl": str(EDL),
        "output": str(OUT_MP4),
        "segment_count": len(built),
        "b_visual_insert_count": sum(1 for item in built if item.get("b_source_id")),
        "audio_policy": "A source native dialogue audio retained; B sources visual-only/muted under J/L-cut.",
        "asr_policy": "Homophone ASR mishears are non-blocking; gate empty audio, foreign/Latin pollution, missing voice, repeated dialogue and hard sentence cuts only.",
        "segments": built,
    }
    (OUT_DIR / "build_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "BUILT_PENDING_QA", "output": str(OUT_MP4), "segments": len(built)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
