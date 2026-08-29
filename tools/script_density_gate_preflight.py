#!/usr/bin/env python3
"""Bind generation admission to a PASS density review for the exact script SHA."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


PASS_MARKER = re.compile(r"SCRIPT_DENSITY_GATE_RESULT\s*=\s*PASS", re.I)
REVISE_MARKER = re.compile(r"SCRIPT_DENSITY_GATE_RESULT\s*=\s*REVISE", re.I)
SHA_MARKER = re.compile(r"script_sha256\s*=\s*([0-9a-f]{64})", re.I)
METRIC_PATTERNS = {
    "duration_seconds": re.compile(r"duration_seconds\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.I),
    "true_event_count": re.compile(r"true_event_count\s*=\s*([0-9]+)", re.I),
    "event_rate_per_minute": re.compile(r"event_rate_per_minute\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.I),
    "max_event_gap_seconds": re.compile(r"max_event_gap_seconds\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.I),
    "non_progress_atmosphere_shot_count": re.compile(r"non_progress_atmosphere_shot_count\s*=\s*([0-9]+)", re.I),
    "total_shot_count": re.compile(r"total_shot_count\s*=\s*([0-9]+)", re.I),
    "non_progress_atmosphere_pct": re.compile(r"non_progress_atmosphere_pct\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.I),
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_reviews(review_dir: Path, episode: str) -> list[Path]:
    return sorted(
        review_dir.glob(f"{episode}_剧情密度审核_*.md"),
        key=lambda path: (path.name, path.stat().st_mtime_ns),
        reverse=True,
    )


def parse_review(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("schema") == "qingshan.us_drama_event_density_gate.v3":
        observed = payload.get("observed") or {}
        narrative = observed.get("narrative_causal_v3") or {}
        duration = observed.get("structure_target_seconds") or observed.get("runtime_target_seconds")
        event_count = narrative.get("story_move_count") or observed.get("planned_event_count")
        event_rate = narrative.get("story_moves_per_minute") or observed.get("events_per_minute")
        max_gap = observed.get("max_information_gap_seconds")
        total_shots = observed.get("planned_event_count")
        non_progress_pct = observed.get("non_advancing_percentage")
        non_progress_count = None
        if total_shots is not None and non_progress_pct is not None:
            non_progress_count = round(float(total_shots) * float(non_progress_pct) / 100.0)
        return {
            "path": str(path),
            "status": str(payload.get("status") or "UNKNOWN").upper(),
            "script_sha256": str(payload.get("manifest_sha256") or "").lower() or None,
            "metrics": {
                "duration_seconds": float(duration) if duration is not None else None,
                "true_event_count": int(event_count) if event_count is not None else None,
                "event_rate_per_minute": float(event_rate) if event_rate is not None else None,
                "max_event_gap_seconds": float(max_gap) if max_gap is not None else None,
                "non_progress_atmosphere_shot_count": int(non_progress_count) if non_progress_count is not None else None,
                "total_shot_count": int(total_shots) if total_shots is not None else None,
                "non_progress_atmosphere_pct": float(non_progress_pct) if non_progress_pct is not None else None,
            },
            "review_schema": payload.get("schema"),
        }
    hashes = SHA_MARKER.findall(text)
    if REVISE_MARKER.search(text):
        status = "REVISE"
    elif PASS_MARKER.search(text):
        status = "PASS"
    else:
        status = "UNKNOWN"
    metrics: dict[str, float | int | None] = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(text)
        metrics[key] = float(match.group(1)) if match else None
    for key in ("true_event_count", "non_progress_atmosphere_shot_count", "total_shot_count"):
        if metrics[key] is not None:
            metrics[key] = int(metrics[key])
    return {
        "path": str(path),
        "status": status,
        "script_sha256": hashes[-1].lower() if hashes else None,
        "metrics": metrics,
    }


def validate_numeric_density(metrics: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    missing = sorted(key for key in METRIC_PATTERNS if metrics.get(key) is None)
    failures.extend(f"density_metric_missing:{key}" for key in missing)
    if missing:
        return failures
    duration = float(metrics["duration_seconds"])
    events = int(metrics["true_event_count"])
    atmosphere = int(metrics["non_progress_atmosphere_shot_count"])
    shots = int(metrics["total_shot_count"])
    if duration <= 0 or shots <= 0 or events < 0 or atmosphere < 0 or atmosphere > shots:
        return ["density_metric_counts_invalid"]
    computed_rate = events * 60.0 / duration
    computed_atmosphere_pct = atmosphere * 100.0 / shots
    if abs(float(metrics["event_rate_per_minute"]) - computed_rate) > 0.05:
        failures.append("event_rate_not_derived_from_counts_and_duration")
    if abs(float(metrics["non_progress_atmosphere_pct"]) - computed_atmosphere_pct) > 0.05:
        failures.append("atmosphere_pct_not_derived_from_shot_counts")
    if computed_rate < 4.0:
        failures.append("true_event_rate_below_4_per_minute")
    if float(metrics["max_event_gap_seconds"]) > 20.0:
        failures.append("max_event_gap_exceeds_20_seconds")
    if computed_atmosphere_pct > 15.0:
        failures.append("non_progress_atmosphere_exceeds_15_percent")
    return failures


def evaluate_density_gate(
    episode: str,
    script: Path,
    review_dir: Path,
    review_path: Path | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    actual_sha = file_sha256(script) if script.is_file() else None
    if not script.is_file():
        failures.append("script_missing")

    candidates = [review_path] if review_path else find_reviews(review_dir, episode)
    candidates = [path for path in candidates if path and path.is_file()]
    parsed = [parse_review(path) for path in candidates]
    matched = next(
        (
            item
            for item in parsed
            if item["status"] == "PASS" and item["script_sha256"] == actual_sha
        ),
        None,
    )
    if not parsed:
        failures.append("density_review_missing")
    elif matched is None:
        if any(item["status"] == "REVISE" for item in parsed):
            failures.append("density_review_requires_revision")
        if not any(item["status"] == "PASS" for item in parsed):
            failures.append("density_review_pass_missing")
        elif not any(item["script_sha256"] == actual_sha for item in parsed):
            failures.append("density_review_script_sha256_mismatch")
    if matched is not None:
        failures.extend(validate_numeric_density(matched.get("metrics") or {}))

    return {
        "schema": "qingshan.script_density_generation_preflight.v1",
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "blocked_by": "NONE" if not failures else "SCRIPT_DENSITY_GATE",
        "script": str(script),
        "script_sha256": actual_sha,
        "matched_review": matched,
        "numeric_thresholds": {
            "minimum_true_events_per_minute": 4.0,
            "target_true_events_per_minute": 6.0,
            "maximum_event_gap_seconds": 20.0,
            "maximum_non_progress_atmosphere_pct": 15.0,
        },
        "reviews_checked": parsed,
        "failures": failures,
        "machine_decision": True,
        "rollback": "Remove only this preflight report; script and reviews are never modified.",
    }


def update_time_ledger(path: Path, result: dict[str, Any]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if result["status"] == "PASS":
        if payload.get("blocked_by") == "SCRIPT_DENSITY_GATE":
            payload["blocked_by"] = "NONE"
    else:
        payload["blocked_by"] = "SCRIPT_DENSITY_GATE"
    payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["script_density_gate"] = {
        "status": result["status"],
        "script_sha256": result["script_sha256"],
        "review": (result.get("matched_review") or {}).get("path"),
        "failures": result["failures"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def write_review_request(path: Path, result: dict[str, Any]) -> None:
    if result["status"] == "PASS":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# [需求] {result['episode']} 待剧情密度审核\n\n"
        f"- script: `{result['script']}`\n"
        f"- script_sha: `{result['script_sha256']}`\n"
        f"- blocked_by: `SCRIPT_DENSITY_GATE`\n"
        f"- failures: `{','.join(result['failures'])}`\n"
    )
    path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--review-dir", default="workflow/script_review/reviews", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--time-ledger", type=Path)
    parser.add_argument("--request-out", type=Path)
    args = parser.parse_args()
    result = evaluate_density_gate(args.episode, args.script, args.review_dir, args.review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.time_ledger:
        update_time_ledger(args.time_ledger, result)
    if args.request_out:
        write_review_request(args.request_out, result)
    print(json.dumps({"status": result["status"], "failures": result["failures"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
