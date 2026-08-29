#!/usr/bin/env python3
"""Verify that a rendered candidate preserves published-mix audio provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audio_fingerprint(
    path: Path,
    ffmpeg: Path,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> str:
    command = [str(ffmpeg), "-v", "error", "-i", str(path)]
    # Seek after demuxing. Input-side seeking can land on different AAC packet
    # boundaries for an audio-only master and an MP4 candidate even when both
    # carry the exact same encoded audio stream, creating a false provenance
    # mismatch. Output-side seeking compares the decoded sample interval.
    if start_seconds is not None:
        command.extend(["-ss", f"{start_seconds:.6f}"])
    if start_seconds is not None and end_seconds is not None:
        command.extend(["-t", f"{end_seconds - start_seconds:.6f}"])
    command.extend(
        [
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ]
    )
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    match = re.search(r"SHA256=([0-9a-fA-F]{64})", proc.stdout)
    if not match:
        raise RuntimeError("audio fingerprint missing")
    return match.group(1).lower()


def evaluate(
    manifest: dict[str, Any],
    published_mix_file_sha256: str,
    candidate_file_sha256: str,
    candidate_audio_fingerprint: str,
    segment_results: list[dict[str, Any]],
) -> dict[str, Any]:
    failures: list[str] = []
    if (
        str(manifest.get("published_mix_file_sha256") or "").lower()
        != published_mix_file_sha256.lower()
    ):
        failures.append("published_mix_file_sha_mismatch")
    if not candidate_file_sha256:
        failures.append("candidate_file_sha_missing")
    if not candidate_audio_fingerprint:
        failures.append("candidate_audio_fingerprint_missing")

    processed = manifest.get("processed_intervals") or []
    unchanged = manifest.get("unchanged_intervals") or []
    if not processed:
        failures.append("processed_intervals_missing")
    if not unchanged:
        failures.append("unchanged_intervals_missing")
    for interval_type, intervals in (("processed", processed), ("unchanged", unchanged)):
        for index, row in enumerate(intervals, start=1):
            start = float(row.get("start_seconds", -1))
            end = float(row.get("end_seconds", -1))
            if start < 0 or end <= start:
                failures.append(f"invalid_{interval_type}_interval:{index}")
            if interval_type == "processed" and not str(row.get("reason") or "").strip():
                failures.append(f"processed_interval_reason_missing:{index}")

    expected_ids = {str(row.get("interval_id") or "") for row in unchanged}
    actual_ids = {str(row.get("interval_id") or "") for row in segment_results}
    missing_ids = expected_ids - actual_ids
    if missing_ids:
        failures.append("unchanged_segment_results_missing:" + ",".join(sorted(missing_ids)))
    for row in segment_results:
        interval_id = str(row.get("interval_id") or "UNKNOWN")
        if row.get("published_mix_fingerprint") != row.get("candidate_fingerprint"):
            failures.append(f"unchanged_segment_fingerprint_mismatch:{interval_id}")

    return {
        "schema": "qingshan.final_audio_provenance_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "published_mix_file_sha256": published_mix_file_sha256,
        "candidate_file_sha256": candidate_file_sha256,
        "candidate_audio_fingerprint": candidate_audio_fingerprint,
        "processed_interval_count": len(processed),
        "unchanged_interval_count": len(unchanged),
        "segment_results": segment_results,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--published-mix", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    published_mix = Path(args.published_mix).resolve()
    candidate = Path(args.candidate).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    segment_results = []
    for row in manifest.get("unchanged_intervals") or []:
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        segment_results.append(
            {
                "interval_id": row["interval_id"],
                "start_seconds": start,
                "end_seconds": end,
                "published_mix_fingerprint": audio_fingerprint(
                    published_mix, ffmpeg, start, end
                ),
                "candidate_fingerprint": audio_fingerprint(
                    candidate, ffmpeg, start, end
                ),
            }
        )
    report = evaluate(
        manifest,
        file_sha256(published_mix),
        file_sha256(candidate),
        audio_fingerprint(candidate, ffmpeg),
        segment_results,
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
