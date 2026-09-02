#!/usr/bin/env python3
"""Activate a revised episode script only after exact-SHA local supervision."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUPERVISION_SCHEMA = "qingshan.canonical_script_supervision.v1"
REQUIRED_CHECKS = (
    "dialogue_length",
    "slow_motion",
    "shot_treatment",
    "expression_layer",
    "mainline_continuity",
)


def _path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _episode(value: Any) -> str:
    match = re.search(r"(\d+)", str(value or ""))
    return f"E{int(match.group(1)):02d}" if match else str(value or "").upper()


def verify_canonical_script_activation(
    episode: Any,
    baseline_script: str | Path,
    revised_script: str | Path,
    change_log: str | Path,
    supervision_report: str | Path,
    expected_revised_sha256: str | None = None,
) -> dict[str, Any]:
    """Require a distinct revised script, change evidence, and exact-SHA PASS."""
    expected_episode = _episode(episode)
    paths = {
        "baseline_script": _path(baseline_script),
        "revised_script": _path(revised_script),
        "change_log": _path(change_log),
        "supervision_report": _path(supervision_report),
    }
    failures: list[dict[str, Any]] = []
    for name, path in paths.items():
        if not path.is_file():
            failures.append({"check": f"{name}_exists", "path": str(path)})

    baseline_sha = _sha256(paths["baseline_script"]) if paths["baseline_script"].is_file() else None
    revised_sha = _sha256(paths["revised_script"]) if paths["revised_script"].is_file() else None
    if baseline_sha and revised_sha and baseline_sha == revised_sha:
        failures.append({"check": "revision_changes_sha", "error": "revised script equals baseline"})
    if expected_revised_sha256 and revised_sha != expected_revised_sha256:
        failures.append({
            "check": "expected_revised_sha256",
            "expected": expected_revised_sha256,
            "actual": revised_sha or "MISSING",
        })

    if paths["change_log"].is_file() and not paths["change_log"].read_text(encoding="utf-8").strip():
        failures.append({"check": "change_log_nonempty"})

    report: dict[str, Any] = {}
    if paths["supervision_report"].is_file():
        try:
            report = json.loads(paths["supervision_report"].read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append({"check": "supervision_report_json", "error": str(exc)})

    if report:
        if report.get("schema") != SUPERVISION_SCHEMA:
            failures.append({"check": "supervision_schema", "expected": SUPERVISION_SCHEMA, "actual": report.get("schema")})
        if _episode(report.get("episode")) != expected_episode:
            failures.append({"check": "supervision_episode", "expected": expected_episode, "actual": report.get("episode")})
        if str(report.get("reviewer_role") or "").upper() != "LOCAL_CLAUDE_SUPERVISOR":
            failures.append({"check": "reviewer_role", "expected": "LOCAL_CLAUDE_SUPERVISOR", "actual": report.get("reviewer_role")})
        if str(report.get("status") or "").upper() != "PASS":
            failures.append({"check": "supervision_status", "expected": "PASS", "actual": report.get("status")})
        if report.get("canonical_activation_allowed") is not True:
            failures.append({"check": "canonical_activation_allowed", "expected": True, "actual": report.get("canonical_activation_allowed")})
        if report.get("script_sha256") != revised_sha:
            failures.append({"check": "supervision_script_sha256", "expected": revised_sha, "actual": report.get("script_sha256")})
        checks = report.get("required_checks") or {}
        for name in REQUIRED_CHECKS:
            if checks.get(name) is not True:
                failures.append({"check": f"required_check_{name}", "expected": True, "actual": checks.get(name)})

    return {
        "schema": "qingshan.canonical_script_activation_gate_result.v1",
        "episode": expected_episode,
        "status": "PASS" if not failures else "BLOCKED_CANONICAL_SCRIPT_ACTIVATION",
        "canonical_activation_allowed": not failures,
        "baseline_script_sha256": baseline_sha,
        "revised_script_sha256": revised_sha,
        "supervision_report_sha256": _sha256(paths["supervision_report"]) if report else None,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--baseline-script", required=True)
    parser.add_argument("--revised-script", required=True)
    parser.add_argument("--change-log", required=True)
    parser.add_argument("--supervision-report", required=True)
    parser.add_argument("--expected-revised-sha256")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = verify_canonical_script_activation(
        args.episode,
        args.baseline_script,
        args.revised_script,
        args.change_log,
        args.supervision_report,
        args.expected_revised_sha256,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        output = _path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
