#!/usr/bin/env python3
"""Compile the accepted E18R dialogue sources in frozen coverage order."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(relative: str) -> Path:
    return (BASE / relative).resolve()


def audio_stream_count(ffmpeg: str, media: Path) -> int:
    result = subprocess.run([ffmpeg, "-i", str(media)], capture_output=True, text=True)
    return len(re.findall(r"Stream #\d+:\d+.*Audio:", result.stderr + result.stdout))


def item(dialogue_id: str, beat_id: str, picture: str, audio: str, **extra: object) -> dict:
    picture_path = resolve(picture)
    audio_path = resolve(audio)
    return {
        "dialogue_id": dialogue_id,
        "beat_id": beat_id,
        "picture": picture,
        "picture_sha256": sha256(picture_path) if picture_path.is_file() else None,
        "audio": audio,
        "audio_sha256": sha256(audio_path) if audio_path.is_file() else None,
        "source_admission": "NOT_FINAL_CANDIDATE",
        **extra,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--b05-plan", required=True)
    parser.add_argument("--b06", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--qa-out", required=True)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()

    coverage = read_json(Path(args.coverage).resolve())
    b05_plan = read_json(Path(args.b05_plan).resolve())
    b06 = read_json(Path(args.b06).resolve())
    ordered_ids = [dialogue_id for beat in coverage["beats"] for dialogue_id in beat["dialogue_ids"]]
    beat_by_id = {
        dialogue_id: beat["beat_id"]
        for beat in coverage["beats"]
        for dialogue_id in beat["dialogue_ids"]
    }

    rows: list[dict] = []
    b01_b04_ids = [
        dialogue_id
        for dialogue_id in ordered_ids
        if beat_by_id[dialogue_id] in {"B01", "B02", "B03", "B04"}
    ]
    for dialogue_id in b01_b04_ids:
        rows.append(
            item(
                dialogue_id,
                beat_by_id[dialogue_id],
                f"assets/e18r_b01_b04_picture_candidates_20260717/{dialogue_id}_muted.mp4",
                f"assets/e18r_b01_b04_audio_candidates_20260717/{dialogue_id}.wav",
            )
        )

    b05_videos = {
        row["role"].removesuffix("_PRIMARY"): row
        for row in b05_plan["video_segments"]
        if row["role"].endswith("_PRIMARY")
    }
    b05_audios = {row["dialogue_id"]: row for row in b05_plan["audio_segments"]}
    for dialogue_id in next(beat["dialogue_ids"] for beat in coverage["beats"] if beat["beat_id"] == "B05"):
        video = b05_videos[dialogue_id]
        audio = b05_audios[dialogue_id]
        rows.append(
            item(
                dialogue_id,
                "B05",
                video["path"],
                audio["path"],
                picture_source_in_sec=video.get("source_in_sec", 0.0),
                picture_duration_sec=video["duration_sec"],
                accepted_plan_ref=str(Path(args.b05_plan).resolve().relative_to(BASE)),
            )
        )

    b06_by_id = {row["dialogue_id"]: row for row in b06["items"]}
    for dialogue_id in next(beat["dialogue_ids"] for beat in coverage["beats"] if beat["beat_id"] == "B06"):
        source = b06_by_id[dialogue_id]
        rows.append(
            item(
                dialogue_id,
                "B06",
                source["picture"],
                source["audio"],
                voice_asset_id=source["voice_asset_id"],
                expected_text=source["expected_text"],
            )
        )

    rows_by_id = {row["dialogue_id"]: row for row in rows}
    rows = [rows_by_id[dialogue_id] for dialogue_id in ordered_ids if dialogue_id in rows_by_id]
    counts = Counter(row["dialogue_id"] for row in rows)
    duplicates = sorted(dialogue_id for dialogue_id, count in counts.items() if count != 1)
    missing_ids = [dialogue_id for dialogue_id in ordered_ids if counts[dialogue_id] != 1]
    unexpected_ids = sorted(set(counts) - set(ordered_ids))
    missing_files: list[str] = []
    picture_audio_violations: list[str] = []
    for row in rows:
        for key in ("picture", "audio"):
            if not resolve(str(row[key])).is_file():
                missing_files.append(str(row[key]))
        picture_path = resolve(str(row["picture"]))
        if picture_path.is_file() and audio_stream_count(args.ffmpeg, picture_path) != 0:
            picture_audio_violations.append(str(row["picture"]))

    failures = []
    if rows and [row["dialogue_id"] for row in rows] != ordered_ids:
        failures.append("ordered_dialogue_ids_do_not_match_coverage")
    if duplicates:
        failures.append("duplicate_dialogue_ids")
    if missing_ids:
        failures.append("missing_dialogue_ids")
    if unexpected_ids:
        failures.append("unexpected_dialogue_ids")
    if missing_files:
        failures.append("missing_source_files")
    if picture_audio_violations:
        failures.append("picture_candidates_contain_audio")

    inventory = {
        "schema": "qingshan.e18r.ordered_source_inventory.v1",
        "episode": "E18R",
        "status": "PASS_41_ORDERED_NOT_FINAL_CANDIDATES" if not failures else "FAIL",
        "coverage_ref": str(Path(args.coverage).resolve().relative_to(BASE)),
        "dialogue_count": len(rows),
        "items": rows,
        "gates": {
            "final_source_lock_allowed": False,
            "exact_plan_compile_allowed": not failures,
            "package_allowed": False,
            "platform_action_allowed": False,
        },
    }
    qa = {
        "schema": "qingshan.e18r.ordered_source_inventory_qa.v1",
        "episode": "E18R",
        "status": "PASS" if not failures else "FAIL",
        "expected_dialogue_count": len(ordered_ids),
        "actual_dialogue_count": len(rows),
        "missing_dialogue_ids": missing_ids,
        "duplicate_dialogue_ids": duplicates,
        "unexpected_dialogue_ids": unexpected_ids,
        "missing_source_files": missing_files,
        "picture_audio_violations": picture_audio_violations,
        "failures": failures,
        "rollback": "Discard the inventory only; preserve all admitted sources and their QA evidence.",
    }

    out = Path(args.out).resolve()
    qa_out = Path(args.qa_out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    qa_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa_out.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "dialogue_count": len(rows), "out": str(out), "qa": str(qa_out)}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
