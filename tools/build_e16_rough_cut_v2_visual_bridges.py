#!/usr/bin/env python3
"""Build E16 rough cut v2 with A/B dialogue assembly plus standalone visual bridges."""

from __future__ import annotations

import json
import argparse
import subprocess
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
EDL = BASE / "configs/e16_ordered_edit_decision_list_20260713.json"
OUT_DIR = BASE / "exports/e16/rough_cut_20260713/ab_reaction_assembly_v3_luma_normalized"
SEG_DIR = OUT_DIR / "segments"
OUT_MP4 = OUT_DIR / "qingshan_E16_ab_reaction_assembly_v3_luma_normalized_20260713.mp4"

# Same-scene source exposure compensation only. Keep this surgical: these
# values target CI-measured same-scene luma jumps, not a global grade.
SHOT_BRIGHTNESS_BIAS = {
    # Same-scene source exposure compensation only. Values are applied in the
    # v21/v22 rebuild path to remove measured same-scene luma discontinuities,
    # not to fake motion or change timing.
    "D09": -0.10,
    "D11": 0.10,
    "D20": 0.10,
    "D50": -0.02,
    "D51": 0.06,
    "D52": -0.04,
    "D57": -0.08,
    "D61": 0.12,
}

SELECTIVE_B_DIALOGUE_IDS = {
    "D08",
    "D11",
    "D24",
    "D28",
    "D36",
    "D39",
    "D42",
    "D44",
    "D51",
    "D58",
}


def shot_scale_filter(dialogue_id: str, *, subtle_motion: bool = False) -> str:
    bias = SHOT_BRIGHTNESS_BIAS.get(dialogue_id)
    base = SCALE_FILTER
    if bias is None:
        return base
    return f"eq=brightness={bias:.3f},{base}"


SCALE_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30,format=yuv420p"
)

VISUAL_BRIDGES: dict[str, list[dict[str, Any]]] = {
    "D24": [
        {
            "bridge_id": "VB01_box_pressure",
            "source": BASE
            / "working_assets/e16_api_20260711/ui_fallback/b_coverage_backfill_20260713/E16-B39/result_01_muted.mp4",
            "start": 0.35,
            "duration": 2.0,
            "reason": "物证箱动作桥：观众看清箱体/手部动作，承接对白指认。",
        }
    ],
    "D44": [
        {
            "bridge_id": "VB02_official_pressure",
            "source": BASE
            / "working_assets/e16_api_20260711/ui_fallback/b_coverage_backfill_20260713/E16-B40/result_01_muted.mp4",
            "start": 0.3,
            "duration": 1.4,
            "reason": "官差反应桥：给质疑后的压迫反应，不重复对白。",
        },
        {
            "bridge_id": "VB03_coroner_departure",
            "source": BASE
            / "working_assets/e16_api_20260711/ui_fallback/b_coverage_backfill_20260713/E16-B41/result_01_muted.mp4",
            "start": 0.2,
            "duration": 3.2,
            "reason": "后段行动桥：验尸官携箱/包袱离开，提示权力压力转入下一阶段。",
        },
    ],
}


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


def segment_plan(seg: dict[str, Any], *, all_b_inserts: bool = False) -> dict[str, float]:
    dialogue_id = seg["dialogue_id"]
    duration = float(seg["target_duration"])
    b_insert = seg.get("b_insert") or {}
    requested_b = float(b_insert.get("duration") or 0.0)
    if (
        requested_b <= 0
        or duration < 1.2
        or (not all_b_inserts and dialogue_id not in SELECTIVE_B_DIALOGUE_IDS)
    ):
        return {"before": duration, "b": 0.0, "after": 0.0}

    b_max = float(b_insert.get("max_insert_duration") or 0.75)
    b_fraction = float(b_insert.get("max_fraction") or 0.35)
    b_dur = min(requested_b, max(0.35, duration * b_fraction), b_max)
    before = max(0.45, duration - b_dur - 0.15)
    if before + b_dur > duration:
        before = max(0.25, duration - b_dur)
    after = max(0.0, duration - before - b_dur)
    return {"before": round(before, 3), "b": round(b_dur, 3), "after": round(after, 3)}


def build_dialogue_segment(index: int, seg: dict[str, Any], *, all_b_inserts: bool = False) -> dict[str, Any]:
    dialogue_id = seg["dialogue_id"]
    a_id = seg["a_source_id"]
    a_path = Path(seg["a_video_path"])
    if not a_path.is_absolute():
        a_path = BASE / a_path
    b = seg.get("b_insert") or {}
    b_path = Path(b.get("video_path") or "")
    if not b_path.is_absolute():
        b_path = BASE / b_path
    out = SEG_DIR / f"{index:03d}_{dialogue_id}_{a_id}_ab.mp4"
    a_in = float(seg["a_in"])
    duration = float(seg["target_duration"])
    plan = segment_plan(seg, all_b_inserts=all_b_inserts)

    if plan["b"] <= 0 or not b_path.exists():
        filters = (
            f"[0:v]trim=start={a_in}:duration={duration},setpts=PTS-STARTPTS,{shot_scale_filter(dialogue_id, subtle_motion=True)}[v];"
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
            f"[0:v]trim=start={a_in}:duration={before},setpts=PTS-STARTPTS,{shot_scale_filter(dialogue_id, subtle_motion=True)}[av1]",
            f"[1:v]trim=start=0.15:duration={b_dur},setpts=PTS-STARTPTS,{SCALE_FILTER}[bv]",
        ]
        concat_inputs = "[av1][bv]"
        concat_n = 2
        if after > 0.05:
            labels.append(
                f"[0:v]trim=start={a_in + before + b_dur}:duration={after},"
                f"setpts=PTS-STARTPTS,{shot_scale_filter(dialogue_id, subtle_motion=True)}[av2]"
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
        "kind": "dialogue",
        "index": index,
        "dialogue_id": dialogue_id,
        "a_source_id": a_id,
        "b_source_id": b.get("source_id"),
        "segment_path": str(out),
        "target_duration": duration,
        "visual_plan": plan,
        "audio_policy": "A_NATIVE_DIALOGUE_AUDIO_ONLY_B_VISUAL_MUTED",
    }


def build_visual_bridge(index: int, after_dialogue_id: str, bridge: dict[str, Any]) -> dict[str, Any]:
    out = SEG_DIR / f"{index:03d}_{bridge['bridge_id']}.mp4"
    duration = float(bridge["duration"])
    source = Path(bridge["source"])
    filters = (
        f"[0:v]trim=start={float(bridge['start'])}:duration={duration},setpts=PTS-STARTPTS,{SCALE_FILTER}[v];"
        f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={duration},asetpts=PTS-STARTPTS[a]"
    )
    run(
        [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
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
    )
    return {
        "kind": "visual_bridge",
        "index": index,
        "after_dialogue_id": after_dialogue_id,
        "bridge_id": bridge["bridge_id"],
        "segment_path": str(out),
        "source": str(source),
        "source_in": float(bridge["start"]),
        "duration": duration,
        "reason": bridge["reason"],
        "audio_policy": "TEMP_SILENT_BRIDGE_PENDING_AMBIENCE_FOLEY_BGM_MIX",
    }


def main() -> int:
    global EDL, OUT_DIR, SEG_DIR, OUT_MP4
    parser = argparse.ArgumentParser()
    parser.add_argument("--edl", default=str(EDL))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--no-standalone-bridges", action="store_true")
    parser.add_argument("--all-b-inserts", action="store_true")
    args = parser.parse_args()
    EDL = Path(args.edl)
    OUT_DIR = Path(args.out_dir)
    SEG_DIR = OUT_DIR / "segments"
    OUT_MP4 = OUT_DIR / "qingshan_E16_speech_window_assembly_20260713.mp4"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SEG_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(EDL.read_text(encoding="utf-8"))
    built: list[dict[str, Any]] = []
    ordinal = 1
    for seg in data["segments"]:
        built.append(build_dialogue_segment(ordinal, seg, all_b_inserts=args.all_b_inserts))
        ordinal += 1
        for bridge in ([] if args.no_standalone_bridges else VISUAL_BRIDGES.get(seg["dialogue_id"], [])):
            built.append(build_visual_bridge(ordinal, seg["dialogue_id"], bridge))
            ordinal += 1

    concat_file = OUT_DIR / "concat.txt"
    # ffmpeg resolves concat entries relative to concat.txt, so emit absolute
    # paths; relative paths duplicate OUT_DIR and break rebuilds outside the
    # original assembly directory.
    concat_file.write_text(
        "".join(f"file '{Path(item['segment_path']).resolve()}'\n" for item in built),
        encoding="utf-8",
    )
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
        "schema": "qingshan.e16.rough_cut_v3_luma_normalized_ab_visual_bridges_build_plan.v1",
        "episode": "E16",
        "status": "BUILT_PENDING_QA",
        "edl": str(EDL),
        "output": str(OUT_MP4),
        "segment_count": len(built),
        "dialogue_segment_count": sum(1 for item in built if item["kind"] == "dialogue"),
        "visual_bridge_count": sum(1 for item in built if item["kind"] == "visual_bridge"),
        "audio_policy": (
            "A source native dialogue audio retained. B sources and standalone visual bridges are "
            "visual-only; final ambience/foley/BGM must be mixed later."
        ),
        "coverage_policy": {
            "mode": "all_b_inserts" if args.all_b_inserts else "selective_b_inserts",
            "selected_dialogue_ids": sorted(SELECTIVE_B_DIALOGUE_IDS),
            "reason": (
                "E16 is a dialogue/evidence episode, not a fight montage. Selective B inserts keep "
                "listener reactions at turn points without turning every line into fragment stacking."
            ),
        },
        "asr_policy": "Homophone ASR mishears are non-blocking; gate empty audio, foreign/Latin pollution, missing voice, repeated dialogue and hard sentence cuts only.",
        "luma_normalization": {
            "policy": "same_scene_source_exposure_compensation_only",
            "shot_bias": SHOT_BRIGHTNESS_BIAS,
            "reason": "D09 end to D10 start and D10 end to D11 start exceeded the 25-point same-scene boundary threshold in v2 final evidence CI.",
        },
        "segments": built,
    }
    (OUT_DIR / "build_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "BUILT_PENDING_QA", "output": str(OUT_MP4), "segments": len(built)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
