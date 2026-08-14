#!/usr/bin/env python3
"""Create a zero-credit V6 picture reframe for V5 dialogue mouth failures."""

import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
TARGETS = {"U02-S1", "U02-S2", "U03-S1", "U03-S3", "U07-S1", "U07-S2", "U07-S3", "U07-S4", "U07-S5"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-vf", "crop=504:896:108:0,scale=720:1280:flags=lanczos",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
            "-an", str(target),
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    args = parser.parse_args()

    project = json.loads(args.project.read_text())
    clips = project["timeline"]["videoTracks"][0]["clips"]
    jobs = []
    for clip in clips:
        segment = clip.get("metadata", {}).get("segment_id")
        if segment not in TARGETS:
            continue
        source = Path(clip["source"])
        target = args.asset_dir / f"{segment.replace('-', '_')}_VISIBLE_SPEAKER_REFRAme_V1.mp4"
        jobs.append((clip, segment, source, target))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: render(item[2], item[3]), jobs))

    for clip, segment, source, target in jobs:
        metadata = clip.setdefault("metadata", {})
        metadata["parent_accepted_source"] = str(source)
        metadata["parent_accepted_source_sha256"] = sha256(source)
        metadata["zero_credit_visual_repair"] = "TOP_CENTER_70_PERCENT_VISIBLE_SPEAKER_REFRAME"
        metadata["admission"] = "PASS_DERIVED_ZERO_CREDIT_VISIBLE_SPEAKER_REFRAME_FROM_ACCEPTED_SOURCE"
        metadata["source_sha256"] = sha256(target)
        metadata["visible_mouth_repair_lines"] = {
            "U02-S1": [3], "U02-S2": [5, 6], "U03-S1": [7], "U03-S3": [11],
            "U07-S1": [17, 18], "U07-S2": [19], "U07-S3": [20, 21],
            "U07-S4": [22, 23], "U07-S5": [24, 25],
        }[segment]
        clip["source"] = str(target.resolve())

    project["output"]["path"] = str((ROOT / "exports/e37/agentcut_v6_visible_speaker_reframe_20260803/E37_AGENTCUT_V6_VISIBLE_SPEAKER_REFRAME_NOT_FINAL.mp4").resolve())
    project.setdefault("metadata", {})["v6_visible_speaker_reframe"] = {
        "source_project": str(args.project.resolve()),
        "source_project_sha256": sha256(args.project),
        "reframed_segments": sorted(TARGETS),
        "crop_contract": "504x896 top-center crop from720x1280, scaled to720x1280; timeline and native audio unchanged",
        "release_status": "NOT_FINAL_REQUIRES_FULL_QA",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"project": str(args.out), "reframed": len(jobs), "sha256": sha256(args.out)}))


if __name__ == "__main__":
    main()
