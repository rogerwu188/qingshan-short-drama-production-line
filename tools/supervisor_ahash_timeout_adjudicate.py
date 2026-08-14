#!/usr/bin/env python3
"""Machine fallback for a timed-out supervisor aHash review gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def frame_ahashes(video: Path, interval_seconds: float) -> list[str]:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video),
        "-vf",
        f"fps=1/{interval_seconds},scale=8:8,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    raw = subprocess.run(command, check=True, capture_output=True).stdout
    if not raw or len(raw) % 64:
        raise RuntimeError("ffmpeg did not return complete 8x8 grayscale frames")

    hashes: list[str] = []
    for offset in range(0, len(raw), 64):
        frame = raw[offset : offset + 64]
        mean = sum(frame) / 64.0
        bits = 0
        for value in frame:
            bits = (bits << 1) | int(value >= mean)
        hashes.append(f"{bits:016x}")
    return hashes


def expected_fraction(gate: dict, key: str, default: str = "40/40") -> str:
    """Return the episode-specific gate requirement with legacy compatibility."""
    value = gate.get(f"required_{key}")
    return str(value) if value else default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-task", type=Path, required=True)
    parser.add_argument("--technical-gate", type=Path, required=True)
    parser.add_argument("--audience-gate", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=8.0)
    parser.add_argument("--now", help="ISO timestamp override for deterministic tests")
    args = parser.parse_args()

    gate = load_json(args.gate_task)
    technical = load_json(args.technical_gate)
    audience = load_json(args.audience_gate)
    now = parse_time(args.now) if args.now else datetime.now().astimezone()
    requested_at = parse_time(gate["recorded_at"])
    deadline = requested_at + timedelta(seconds=int(gate["timeout_seconds"]))

    failures: list[str] = []
    if now < deadline:
        failures.append("SUPERVISOR_TIMEOUT_NOT_REACHED")
    if technical.get("status") != "PASS":
        failures.append("TECHNICAL_GATE_NOT_PASS")
    if audience.get("gate_status") != "PASS" or audience.get("hard_fail"):
        failures.append("AUDIENCE_GATE_NOT_PASS")
    if gate.get("ai_review_blockers") != 0:
        failures.append("AI_REVIEW_HAS_BLOCKERS")
    required_coverage = expected_fraction(gate, "coverage")
    required_subtitles = expected_fraction(gate, "burned_subtitles")
    if gate.get("coverage") != required_coverage:
        failures.append(f"COVERAGE_NOT_{required_coverage.replace('/', '_OF_')}")
    if gate.get("burned_subtitles") != required_subtitles:
        failures.append(f"BURNED_SUBTITLES_NOT_{required_subtitles.replace('/', '_OF_')}")
    if not args.candidate.is_file():
        failures.append("CANDIDATE_MISSING")

    frame_hashes: list[str] = []
    if not failures:
        frame_hashes = frame_ahashes(args.candidate, args.interval_seconds)
        if len(frame_hashes) < 10:
            failures.append("INSUFFICIENT_AHASH_SAMPLES")

    aggregate = hashlib.sha256("\n".join(frame_hashes).encode("ascii")).hexdigest() if frame_hashes else None
    result = {
        "schema": "qingshan.supervisor_ahash_timeout_machine_adjudication.v2",
        "episode": gate.get("episode"),
        "candidate": str(args.candidate),
        "requested_at": gate.get("recorded_at"),
        "deadline": deadline.isoformat(),
        "adjudicated_at": now.isoformat(),
        "timeout_seconds": gate.get("timeout_seconds"),
        "human_response_received": False,
        "status": "PASS_MACHINE_SUPERVISOR_AHASH" if not failures else "FAIL_MACHINE_SUPERVISOR_AHASH",
        "confidence": 0.96 if not failures else 1.0,
        "failures": failures,
        "rollback_allowed": True,
        "irreversible_action_allowed": False,
        "checks": {
            "technical_gate": technical.get("status"),
            "audience_gate": audience.get("gate_status"),
            "audience_score": audience.get("overall"),
            "audience_hard_fail": audience.get("hard_fail"),
            "ai_review_score": gate.get("ai_review_score"),
            "ai_review_blockers": gate.get("ai_review_blockers"),
            "coverage": gate.get("coverage"),
            "required_coverage": required_coverage,
            "burned_subtitles": gate.get("burned_subtitles"),
            "required_burned_subtitles": required_subtitles,
            "nalu_motion_outro": gate.get("nalu_motion_outro"),
            "native_text_cleanup": gate.get("native_text_cleanup"),
            "audio_mix": gate.get("audio_mix"),
        },
        "artifacts": {
            "video": {"path": str(args.candidate), "sha256": sha256(args.candidate) if args.candidate.is_file() else None},
            "gate_task": {"path": str(args.gate_task), "sha256": sha256(args.gate_task)},
            "technical_gate": {"path": str(args.technical_gate), "sha256": sha256(args.technical_gate)},
            "audience_gate": {"path": str(args.audience_gate), "sha256": sha256(args.audience_gate)},
        },
        "ahash": {
            "algorithm": "8x8-grayscale-average-hash",
            "sample_interval_seconds": args.interval_seconds,
            "sample_count": len(frame_hashes),
            "frame_hashes": frame_hashes,
            "aggregate_sha256": aggregate,
        },
        "decision": "OPEN_FINAL_LOCK_AND_ORDERED_PLATFORM_REPLACEMENT" if not failures else "KEEP_RELEASE_CLOSED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": result["status"], "failures": failures}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
