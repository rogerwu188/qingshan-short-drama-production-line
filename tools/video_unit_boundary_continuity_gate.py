#!/usr/bin/env python3
"""Block episode assembly until every generated unit boundary is visually adjudicated.

This gate binds a human or vision-review decision to the exact predecessor and
successor media SHAs plus the authored transition contract.  Prompt preflight
cannot prove that the provider actually respected a match cut or actor-bearing
start frame; this is the post-generation half of the contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = {
    "visual_bridge_match",
    "action_bridge_match",
    "sound_bridge_match",
    "axis_strategy_match",
    "target_subject_present_at_required_start",
    "no_uncontracted_space_jump",
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transition_sha(contract: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_boundary_decision(
    decision: Any,
    *,
    previous_unit: dict[str, Any],
    current_unit: dict[str, Any],
    previous_media: Path,
    current_media: Path,
) -> dict[str, Any]:
    previous_id = str(previous_unit["unit_id"])
    current_id = str(current_unit["unit_id"])
    label = f"{previous_id}->{current_id} boundary decision"
    if not isinstance(decision, dict) or decision.get("status") != "PASS":
        raise ValueError(f"{label} is missing or not PASS")
    if decision.get("from_unit_id") != previous_id or decision.get("to_unit_id") != current_id:
        raise ValueError(f"{label} unit binding mismatch")
    if decision.get("from_media_sha256") != sha256(previous_media):
        raise ValueError(f"{label} predecessor media SHA mismatch")
    if decision.get("to_media_sha256") != sha256(current_media):
        raise ValueError(f"{label} successor media SHA mismatch")
    contract = current_unit.get("incoming_transition_contract") or current_unit.get("transition_contract")
    if not isinstance(contract, dict):
        raise ValueError(f"{label} has no authored incoming transition contract")
    if decision.get("transition_contract_sha256") != transition_sha(contract):
        raise ValueError(f"{label} transition contract SHA mismatch")
    checks = decision.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS:
        raise ValueError(f"{label} checks must contain exactly {sorted(REQUIRED_CHECKS)}")
    failed = sorted(key for key, value in checks.items() if value is not True)
    if failed:
        raise ValueError(f"{label} failed checks: {failed}")
    reviewer = str(decision.get("reviewer") or "").strip()
    evidence_ref = str(decision.get("evidence_ref") or "").strip()
    if len(reviewer) < 3 or not evidence_ref:
        raise ValueError(f"{label} reviewer and evidence_ref are required")
    return {
        "from_unit_id": previous_id,
        "to_unit_id": current_id,
        "status": "PASS",
        "decision_ref": evidence_ref,
        "reviewer": reviewer,
    }


def _media_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("units") or payload.get("rows") or payload.get("tasks") or []
    result = []
    for row in rows:
        path = row.get("video_path") or row.get("media_path") or row.get("path")
        if row.get("unit_id") and path:
            result.append({"unit_id": row["unit_id"], "path": path})
    return result


def evaluate(manifest: dict[str, Any], media_map: dict[str, Any], decision_dir: Path) -> dict[str, Any]:
    units = manifest.get("units") or []
    media_by_unit = {row["unit_id"]: resolve(row["path"]) for row in _media_rows(media_map)}
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    for index in range(1, len(units)):
        previous, current = units[index - 1], units[index]
        previous_id, current_id = str(previous["unit_id"]), str(current["unit_id"])
        previous_media = media_by_unit.get(previous_id)
        current_media = media_by_unit.get(current_id)
        if not previous_media or not previous_media.is_file() or not current_media or not current_media.is_file():
            failures.append(f"{previous_id}->{current_id} exact media is missing")
            continue
        decision_path = decision_dir / f"{previous_id}__{current_id}.json"
        if not decision_path.is_file():
            failures.append(f"{previous_id}->{current_id} boundary decision is missing")
            continue
        try:
            result = validate_boundary_decision(
                json.loads(decision_path.read_text(encoding="utf-8")),
                previous_unit=previous,
                current_unit=current,
                previous_media=previous_media,
                current_media=current_media,
            )
            result["decision_path"] = str(decision_path)
            results.append(result)
        except (ValueError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
    return {
        "schema": "qingshan.video_unit_boundary_continuity_gate.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "unit_count": len(units),
        "boundary_count": max(0, len(units) - 1),
        "passed_boundary_count": len(results),
        "results": results,
        "failures": failures,
        "assembly_allowed": not failures,
        "policy": "NO_ASSEMBLY_WITHOUT_EXACT_MEDIA_SHA_BOUND_END_TO_START_VISUAL_ACTION_SOUND_AXIS_AND_SUBJECT_CONTINUITY_PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouped-manifest", required=True)
    parser.add_argument("--media-map", required=True)
    parser.add_argument("--decision-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest = json.loads(resolve(args.grouped_manifest).read_text(encoding="utf-8"))
    media_map = json.loads(resolve(args.media_map).read_text(encoding="utf-8"))
    report = evaluate(manifest, media_map, resolve(args.decision_dir))
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "assembly_allowed": report["assembly_allowed"], "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
