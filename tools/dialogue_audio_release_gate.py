#!/usr/bin/env python3
"""Block release when scripted dialogue is absent from the final audio track."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


BLOCKER_ID = "DIALOGUE_AUDIO_AUDIBILITY"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_repo_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "tools").is_dir() and (parent / "workflow").is_dir():
            return parent
    raise ValueError(f"repo_root_not_found:{path}")


def resolve_evidence_path(value: str, manifest: Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    root_candidate = (root / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest.parent / path).resolve()


def probe_audio_stream_count(video: Path, root: Path | None = None) -> int:
    ffprobe = os.environ.get("FFPROBE") or shutil.which("ffprobe")
    if not ffprobe:
        ffmpeg = os.environ.get("FFMPEG")
        if ffmpeg:
            sibling = Path(ffmpeg).with_name("ffprobe")
            if sibling.exists():
                ffprobe = str(sibling)
    if ffprobe:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                str(video),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return len(json.loads(result.stdout).get("streams", []))

    ffmpeg = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg and root:
        finder = root / "tools" / "find_ffmpeg.sh"
        if finder.is_file():
            ffmpeg = subprocess.run(
                [str(finder), str(root)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
    if not ffmpeg:
        raise RuntimeError("ffprobe_and_ffmpeg_not_found")
    result = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(video),
            "-map",
            "0:a:0",
            "-frames:a",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return 1 if result.returncode == 0 else 0


def evaluate(
    evidence: dict,
    audio_manifest: dict | None,
    asr_report: dict | None,
    *,
    audio_stream_count: int,
    actual_video_sha256: str,
    verify_audio_files: bool = True,
) -> dict:
    failures: list[str] = []
    expected = evidence.get("expected_dialogue_count")
    verified = evidence.get("verified_dialogue_count")
    role_bound = evidence.get("role_bound_count")

    if evidence.get("status") != "PASS":
        failures.append("dialogue_release_evidence_not_pass")
    if expected is None or not isinstance(expected, int) or expected < 0:
        failures.append("expected_dialogue_count_invalid")
        expected = -1
    if audio_stream_count < 1:
        failures.append("final_video_has_no_audio_stream")
    if evidence.get("final_sha256") != actual_video_sha256:
        failures.append("final_video_sha256_mismatch")

    if expected > 0:
        if evidence.get("dialogue_audio_claimed") is not True:
            failures.append("dialogue_audio_not_claimed")
        if verified != expected:
            failures.append(f"verified_dialogue_count_mismatch:{verified}:{expected}")
        if role_bound != expected:
            failures.append(f"role_bound_count_mismatch:{role_bound}:{expected}")
        if not isinstance(audio_manifest, dict):
            failures.append("dialogue_audio_manifest_missing")
        if not isinstance(asr_report, dict):
            failures.append("dialogue_asr_report_missing")

    rows = audio_manifest.get("rows", []) if isinstance(audio_manifest, dict) else []
    row_ids = [str(row.get("dialogue_id") or "") for row in rows if isinstance(row, dict)]
    if expected >= 0 and len(rows) != expected:
        failures.append(f"dialogue_audio_manifest_count_mismatch:{len(rows)}:{expected}")
    if any(not value for value in row_ids) or len(set(row_ids)) != len(row_ids):
        failures.append("dialogue_audio_manifest_ids_missing_or_duplicate")
    for row in rows:
        if not str(row.get("speaker") or "").strip():
            failures.append(f"dialogue_speaker_missing:{row.get('dialogue_id')}")
        if not str(row.get("text") or "").strip():
            failures.append(f"dialogue_text_missing:{row.get('dialogue_id')}")
        audio_path = Path(str(row.get("fitted_file") or "")).expanduser()
        expected_sha = str(row.get("fitted_sha256") or "")
        if verify_audio_files:
            if not audio_path.is_file():
                failures.append(f"dialogue_audio_file_missing:{row.get('dialogue_id')}")
            elif len(expected_sha) != 64 or sha256_file(audio_path) != expected_sha:
                failures.append(f"dialogue_audio_file_sha_mismatch:{row.get('dialogue_id')}")

    asr_rows = asr_report.get("rows", []) if isinstance(asr_report, dict) else []
    asr_ids = [str(row.get("dialogue_id") or "") for row in asr_rows if isinstance(row, dict)]
    if expected >= 0 and len(asr_rows) != expected:
        failures.append(f"dialogue_asr_count_mismatch:{len(asr_rows)}:{expected}")
    if isinstance(asr_report, dict) and asr_report.get("status") != "PASS":
        failures.append("dialogue_asr_not_pass")
    if set(asr_ids) != set(row_ids):
        failures.append("dialogue_asr_ids_do_not_match_audio_manifest")
    for row in asr_rows:
        if row.get("status") != "PASS" or row.get("speech_present") is not True:
            failures.append(f"dialogue_not_audible:{row.get('dialogue_id')}")

    return {
        "schema": "qingshan.dialogue_audio_release_gate_result.v1",
        "status": "PASS" if not failures else "FAIL",
        "expected_dialogue_count": expected,
        "verified_dialogue_count": verified,
        "role_bound_count": role_bound,
        "audio_stream_count": audio_stream_count,
        "failures": failures,
        "rule": "Subtitles never substitute for scripted dialogue in the final audio track.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--blocker-manifest", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()

    video = Path(args.video).expanduser().resolve()
    blocker_manifest = Path(args.blocker_manifest).expanduser().resolve()
    root = find_repo_root(blocker_manifest)
    blocker_payload = json.loads(blocker_manifest.read_text(encoding="utf-8"))
    rows = [
        row
        for row in blocker_payload.get("blockers", [])
        if str(row.get("id") or "").upper() == BLOCKER_ID
    ]
    preflight_failures = []
    if len(rows) != 1:
        preflight_failures.append(f"dialogue_audio_blocker_row_count:{len(rows)}")
        row = {}
    else:
        row = rows[0]
    if str(row.get("status") or "").upper() != "RESOLVED":
        preflight_failures.append("dialogue_audio_blocker_not_resolved")
    if str(row.get("evidence_status") or "").upper() != "PASS":
        preflight_failures.append("dialogue_audio_blocker_evidence_not_pass")
    evidence_value = str(row.get("evidence") or "")
    evidence_path = resolve_evidence_path(evidence_value, blocker_manifest, root) if evidence_value else None
    if not evidence_path or not evidence_path.is_file():
        preflight_failures.append("dialogue_audio_blocker_evidence_missing")

    if preflight_failures:
        result = {
            "schema": "qingshan.dialogue_audio_release_gate_result.v1",
            "status": "FAIL",
            "failures": preflight_failures,
        }
    else:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        audio_manifest_path = resolve_evidence_path(
            str(evidence.get("audio_manifest") or ""), evidence_path, root
        )
        asr_report_path = resolve_evidence_path(
            str(evidence.get("asr_report") or ""), evidence_path, root
        )
        audio_manifest = (
            json.loads(audio_manifest_path.read_text(encoding="utf-8"))
            if audio_manifest_path.is_file()
            else None
        )
        asr_report = (
            json.loads(asr_report_path.read_text(encoding="utf-8"))
            if asr_report_path.is_file()
            else None
        )
        result = evaluate(
            evidence,
            audio_manifest,
            asr_report,
            audio_stream_count=probe_audio_stream_count(video, root),
            actual_video_sha256=sha256_file(video),
        )
        result.update(
            {
                "video": str(video),
                "blocker_manifest": str(blocker_manifest),
                "evidence": str(evidence_path),
            }
        )

    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
