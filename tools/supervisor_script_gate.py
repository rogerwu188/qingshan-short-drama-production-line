#!/usr/bin/env python3
"""Verify the CL2X-499 local-Claude script supervision hard gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "qingshan.local_claude_script_supervision.v1"
PREGATE_SCHEMA = "qingshan.supervisor_script_pregate.v1"


def _path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _episode_number(value: Any) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def _shot_ids(payload: dict[str, Any]) -> list[str]:
    locked = payload.get("locked_script") or {}
    result: list[str] = []
    for scene in locked.get("scenes") or []:
        for shot in scene.get("shots") or []:
            shot_id = str(shot.get("id") or shot.get("shot_id") or "").strip()
            if shot_id:
                result.append(shot_id)
    return result


def _is_pass(value: Any) -> bool:
    """Allow a PASS verdict with an attached reason, but no conditional aliases."""
    return re.match(r"^PASS(?:\s*[—:\-]\s+.+)?$", str(value or "").strip(), re.IGNORECASE) is not None


def _verify_pregate_report(
    episode: Any,
    generated_script: str | Path | None,
    compiled_script: str | Path | None,
    report_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    """Verify a newer SHA-bound CL2X-499 pregate receipt."""
    failures: list[dict[str, Any]] = []
    expected_episode = _episode_number(episode)
    if _episode_number(report.get("episode")) != expected_episode:
        failures.append({"check": "review_episode", "expected": expected_episode, "actual": report.get("episode")})
    if report.get("gate_ref") != "CL2X-499":
        failures.append({"check": "gate_ref", "expected": "CL2X-499", "actual": report.get("gate_ref")})
    if str(report.get("verdict") or "").upper() != "PASS":
        failures.append({"check": "review_status", "expected": "PASS", "actual": report.get("verdict")})
    if "CLAUDE" not in str(report.get("ruled_by") or "").upper():
        failures.append({"check": "reviewer_role", "expected": "LOCAL_CLAUDE_SUPERVISOR", "actual": report.get("ruled_by")})

    gates = report.get("registered_gates") or {}
    if not (
        int(gates.get("count", -1)) > 0
        and gates.get("count") == gates.get("pass")
        and int(gates.get("fail", -1)) == 0
        and int(gates.get("failures_total", -1)) == 0
    ):
        failures.append({"check": "registered_gate_coverage", "actual": gates})

    bindings = report.get("sha_recompute") or {}
    actual_shas: dict[str, str | None] = {"generated_script": None, "compiled_script": None}
    for name, value, report_key in (
        ("generated_script", generated_script, "directing_script"),
        ("compiled_script", compiled_script, "generation_contract"),
    ):
        if not value:
            failures.append({"check": f"{name}_binding", "error": "missing"})
            continue
        path = _path(value)
        if not path.is_file():
            failures.append({"check": f"{name}_exists", "path": str(path)})
            continue
        actual_sha = _sha256(path)
        actual_shas[name] = actual_sha
        binding = bindings.get(report_key) or {}
        if binding.get("sha256") != actual_sha:
            failures.append({
                "check": f"{name}_sha256_binding",
                "expected": actual_sha,
                "actual": binding.get("sha256") or "MISSING",
            })
        bound_path = binding.get("path")
        if not bound_path or _path(bound_path).resolve() != path.resolve():
            failures.append({"check": f"{name}_path_binding", "expected": str(path), "actual": bound_path or "MISSING"})

    structure = report.get("structure_cross_check") or {}
    path_a = structure.get("path_a_manifest") or {}
    path_b = structure.get("path_b_contract_recompute") or {}
    expected_shots = int(path_a.get("shots", 0) or 0)
    reviewed_shots = int(path_b.get("units", 0) or 0)
    if structure.get("consistent") is not True or expected_shots <= 0 or reviewed_shots != expected_shots:
        failures.append({
            "check": "shot_review_coverage",
            "expected": expected_shots,
            "actual": reviewed_shots,
            "consistent": structure.get("consistent"),
        })

    return {
        "schema": "qingshan.supervisor_script_gate_result.v1",
        "episode": f"E{expected_episode:02d}" if expected_episode else str(episode),
        "status": "PASS" if not failures else "FAIL",
        "generation_allowed": not failures,
        "generated_script_sha256": actual_shas["generated_script"],
        "compiled_script_sha256": actual_shas["compiled_script"],
        "expected_shot_count": expected_shots,
        "reviewed_shot_count": reviewed_shots,
        "review_report": str(report_path),
        "review_schema": PREGATE_SCHEMA,
        "failures": failures,
    }


def verify_supervisor_script_gate(
    episode: Any,
    generated_script: str | Path | None,
    compiled_script: str | Path | None,
    review_report: str | Path | None,
) -> dict[str, Any]:
    """Return PASS only for an exact-SHA, complete per-shot local-Claude PASS."""
    if review_report:
        candidate = _path(review_report)
        if candidate.is_file():
            try:
                candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                candidate_payload = {}
            if candidate_payload.get("schema") == PREGATE_SCHEMA:
                return _verify_pregate_report(
                    episode,
                    generated_script,
                    compiled_script,
                    candidate,
                    candidate_payload,
                )
    failures: list[dict[str, Any]] = []
    expected_episode = _episode_number(episode)
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}

    for name, value in (
        ("generated_script", generated_script),
        ("compiled_script", compiled_script),
        ("review_report", review_report),
    ):
        if not value:
            failures.append({"check": f"{name}_binding", "error": "missing"})
            continue
        path = _path(value)
        paths[name] = path
        if not path.is_file():
            failures.append({"check": f"{name}_exists", "path": str(path)})
            continue
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"check": f"{name}_json", "error": str(exc)})

    generated = payloads.get("generated_script") or {}
    compiled = payloads.get("compiled_script") or {}
    report = payloads.get("review_report") or {}
    generated_sha = _sha256(paths["generated_script"]) if "generated_script" in payloads else None
    compiled_sha = _sha256(paths["compiled_script"]) if "compiled_script" in payloads else None

    if report:
        if report.get("schema") != SCHEMA:
            failures.append({"check": "review_schema", "expected": SCHEMA, "actual": report.get("schema")})
        if _episode_number(report.get("episode")) != expected_episode:
            failures.append({"check": "review_episode", "expected": expected_episode, "actual": report.get("episode")})
        if str(report.get("reviewer_role") or "").upper() != "LOCAL_CLAUDE_SUPERVISOR":
            failures.append({"check": "reviewer_role", "expected": "LOCAL_CLAUDE_SUPERVISOR", "actual": report.get("reviewer_role")})
        if str(report.get("status") or "").upper() != "PASS":
            failures.append({"check": "review_status", "expected": "PASS", "actual": report.get("status")})
        if report.get("generation_allowed") is not True:
            failures.append({"check": "generation_allowed", "expected": True, "actual": report.get("generation_allowed")})

        bindings = report.get("script_bindings") or {}
        for name, actual_sha in (("generated_script", generated_sha), ("compiled_script", compiled_sha)):
            expected_sha = bindings.get(f"{name}_sha256")
            if not expected_sha or expected_sha != actual_sha:
                failures.append({
                    "check": f"{name}_sha256_binding",
                    "expected": actual_sha,
                    "actual": expected_sha or "MISSING",
                })

        expected_shots = _shot_ids(generated)
        rows = report.get("shot_reviews") or []
        by_id = {str(row.get("shot_id") or ""): row for row in rows if isinstance(row, dict)}
        if len(by_id) != len(rows):
            failures.append({"check": "shot_review_unique_ids", "expected": len(rows), "actual": len(by_id)})
        if set(by_id) != set(expected_shots):
            failures.append({
                "check": "shot_review_coverage",
                "missing": sorted(set(expected_shots) - set(by_id)),
                "unexpected": sorted(set(by_id) - set(expected_shots)),
            })
        for shot_id in expected_shots:
            row = by_id.get(shot_id) or {}
            for field in ("status", "source_basis", "script_alignment", "treatment_alignment"):
                if not _is_pass(row.get(field)):
                    failures.append({"check": f"shot_review_{field}", "shot_id": shot_id, "expected": "PASS", "actual": row.get(field) or "MISSING"})

    for name, payload in (("generated_script", generated), ("compiled_script", compiled)):
        if payload and _episode_number(payload.get("episode")) != expected_episode:
            failures.append({"check": f"{name}_episode", "expected": expected_episode, "actual": payload.get("episode")})

    return {
        "schema": "qingshan.supervisor_script_gate_result.v1",
        "episode": f"E{expected_episode:02d}" if expected_episode else str(episode),
        "status": "PASS" if not failures else "FAIL",
        "generation_allowed": not failures,
        "generated_script_sha256": generated_sha,
        "compiled_script_sha256": compiled_sha,
        "expected_shot_count": len(_shot_ids(generated)),
        "reviewed_shot_count": len(report.get("shot_reviews") or []) if report else 0,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--generated-script", required=True)
    parser.add_argument("--compiled-script", required=True)
    parser.add_argument("--review-report", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = verify_supervisor_script_gate(
        args.episode,
        args.generated_script,
        args.compiled_script,
        args.review_report,
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
