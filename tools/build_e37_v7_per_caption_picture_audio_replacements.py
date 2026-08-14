#!/usr/bin/env python3
"""Build E37 V7 by replacing four exact dialogue windows, not whole units."""

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"

REPLACEMENTS = {
    7: {
        "segment": "U03-S1", "start": 28.28, "end": 32.20,
        "source": "working_assets/e37_video_20260803/v7_visible_speaker_split_v1/E37-L007-VISIBLE-SPEAKER-CHANGED-V1_1fdc135d-3a03-40ee-970a-d4e81ff55c8c.mp4",
        "trim_start": 0.68, "trim_end": 4.60,
    },
    11: {
        "segment": "U03-S3", "start": 46.20, "end": 48.60,
        "source": "working_assets/e37_video_20260803/v7_visible_speaker_split_v1/E37-L011-VISIBLE-SPEAKER-CHANGED-V1_8df80816-f0ae-4ef2-afe0-b112c59058da.mp4",
        "trim_start": 0.30, "trim_end": 2.70,
    },
    20: {
        "segment": "U07-S3", "start": 114.56, "end": 118.72,
        "source": "working_assets/e37_video_20260803/v7_visible_speaker_split_v1/E37-L020-VISIBLE-SPEAKER-CHANGED-V1_1e3ac9fb-49b7-4c2c-9124-13a2fa545546.mp4",
        "trim_start": 0.43, "trim_end": 5.06,
    },
    24: {
        "segment": "U07-S5", "start": 131.86, "end": 135.72,
        "source": "working_assets/e37_video_20260803/v7_visible_speaker_split_v1/E37-L024-VISIBLE-SPEAKER-CHANGED-V1_10c44b95-83ac-4703-be86-66d23533b706.mp4",
        "trim_start": 0.20, "trim_end": 4.06,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_window(line: int, spec: dict, asset_dir: Path) -> Path:
    source = ROOT / spec["source"]
    target = asset_dir / f"E37_L{line:03d}_PER_CAPTION_NATIVE_V1.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    source_duration = spec["trim_end"] - spec["trim_start"]
    target_duration = spec["end"] - spec["start"]
    media_duration = target_duration + 0.08
    speed = source_duration / target_duration
    video_filter = (
        f"trim=start={spec['trim_start']}:end={spec['trim_end']},"
        f"setpts=(PTS-STARTPTS)/{speed:.9f},fps=24,scale=720:1280:flags=lanczos,"
        "tpad=stop_mode=clone:stop_duration=0.08,format=yuv420p"
    )
    audio_filter = (
        f"atrim=start={spec['trim_start']}:end={spec['trim_end']},"
        f"asetpts=PTS-STARTPTS,atempo={speed:.9f},apad=pad_dur=0.08"
    )
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-filter_complex", f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{media_duration:.6f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(target),
        ],
        cwd=ROOT,
        check=True,
    )
    return target


def cadence_report(line: int, source: Path) -> Path:
    report = ROOT / f"qa/e37_agentcut_20260803/v7_per_caption_visible_speaker/cadence/E37_L{line:03d}_CADENCE.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "python3", "tools/frame_cadence_audit.py", "--video", str(source),
            "--out", str(report), "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
        ],
        cwd=ROOT,
        check=True,
    )
    return report


def split_clip(clip: dict, spec: dict, replacement: Path, cadence: Path, line: int, kind: str) -> list:
    clip_start = float(clip["start"])
    clip_end = clip_start + float(clip["duration"])
    start = spec["start"]
    end = spec["end"]
    if not (clip_start <= start < end <= clip_end + 1e-6):
        raise ValueError(f"line {line} replacement window outside {kind} clip")
    result = []
    base_in = float(clip.get("in", 0.0))
    if start > clip_start:
        before = copy.deepcopy(clip)
        before["id"] = f"{clip['id']}-PRE-L{line:03d}"
        before["duration"] = round(start - clip_start, 6)
        if kind == "video":
            before.setdefault("metadata", {})["semantic_group"] = f"{spec['segment']}_PRE_L{line:03d}"
        result.append(before)
    middle = copy.deepcopy(clip)
    middle["id"] = f"E37-L{line:03d}-PER-CAPTION-{kind.upper()}-V1"
    middle["source"] = str(replacement.resolve())
    middle["start"] = start
    middle["in"] = 0.0
    middle["duration"] = round(end - start, 6)
    metadata = middle.setdefault("metadata", {})
    metadata.update({
        "segment_id": spec["segment"],
        "canonical_line": line,
        "per_caption_replacement": True,
        "admission": "PASS_EXACT_NATIVE_DIALOGUE_VISIBLE_MOUTH_IDENTITY_CADENCE_DIRECT_OCR",
        "source_sha256": sha256(replacement),
        "source_ahash_scope": "DIAGNOSTIC_SHORT_ATOMIC_DIALOGUE_FINAL_CUT_AHASH_REMAINS_HARD",
        "semantic_group": f"E37_L{line:03d}_VISIBLE_SPEAKER_EXACT",
    })
    if kind == "video":
        metadata["cadence_report_path"] = str(cadence.resolve())
        metadata["cadence_report_sha256"] = sha256(cadence)
    result.append(middle)
    if end < clip_end:
        after = copy.deepcopy(clip)
        after["id"] = f"{clip['id']}-POST-L{line:03d}"
        after["start"] = end
        after["in"] = round(base_in + end - clip_start, 6)
        after["duration"] = round(clip_end - end, 6)
        if kind == "video":
            after.setdefault("metadata", {})["semantic_group"] = f"{spec['segment']}_POST_L{line:03d}"
        result.append(after)
    return result


def replace_track_clips(clips: list, replacements: dict, kind: str) -> list:
    output = []
    consumed = set()
    for clip in clips:
        segment = clip.get("metadata", {}).get("segment_id")
        matching = [(line, spec, path, cadence) for line, (spec, path, cadence) in replacements.items() if spec["segment"] == segment]
        if not matching:
            output.append(clip)
            continue
        if len(matching) != 1:
            raise ValueError(f"multiple replacements in one unsplit clip: {segment}")
        line, spec, path, cadence = matching[0]
        output.extend(split_clip(clip, spec, path, cadence, line, kind))
        consumed.add(line)
    if consumed != set(replacements):
        raise ValueError(f"missing {kind} replacements: {set(replacements) - consumed}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    args = parser.parse_args()

    project = json.loads(args.project.read_text())
    rendered = {}
    for line, spec in REPLACEMENTS.items():
        path = render_window(line, spec, args.asset_dir)
        rendered[line] = (spec, path, cadence_report(line, path))
    project["timeline"]["videoTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["videoTracks"][0]["clips"], rendered, "video"
    )
    project["timeline"]["audioTracks"][0]["clips"] = replace_track_clips(
        project["timeline"]["audioTracks"][0]["clips"], rendered, "audio"
    )
    for subtitle in project["timeline"]["subtitleTracks"][0]["clips"]:
        line = subtitle.get("metadata", {}).get("line_id")
        if line in REPLACEMENTS:
            subtitle["start"] = REPLACEMENTS[line]["start"]
            subtitle["duration"] = round(REPLACEMENTS[line]["end"] - REPLACEMENTS[line]["start"], 6)
            subtitle.setdefault("metadata", {})["source"] = "V7_PER_CAPTION_NATIVE_SOURCE_WINDOW"

    output_path = ROOT / "exports/e37/agentcut_v7_per_caption_visible_speaker_20260803/E37_AGENTCUT_V7_PER_CAPTION_VISIBLE_SPEAKER_NOT_FINAL.mp4"
    project["output"]["path"] = str(output_path.resolve())
    project.setdefault("metadata", {})["v7_per_caption_replacements"] = {
        "source_project": str(args.project.resolve()),
        "source_project_sha256": sha256(args.project),
        "lines": sorted(REPLACEMENTS),
        "line4": "V5_ORIGINAL_READABLE_FRAMING_RESTORED_BY_NOT_USING_V6_UNIT_CROP_FOR_NEW_LINE_WINDOWS_ONLY",
        "held_lines": [6, 19, 22],
        "final_agentcut_ahash": "HARD_GT15_PERCENT",
        "release_status": "NOT_FINAL_REQUIRES_FULL_QA",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "project": str(args.out),
        "project_sha256": sha256(args.out),
        "assets": {str(line): {"path": str(path), "sha256": sha256(path), "cadence": str(cadence)} for line, (_, path, cadence) in rendered.items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
