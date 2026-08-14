#!/usr/bin/env python3
"""Build a fail-closed recovery/cost gate for E36 AgentCut source gaps."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V1.json"
PLAN = PROD / "E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V2.json"
OCR = ROOT / "qa/e36_agentcut_20260730/E36_MISSING_UNIT_ANCHOR_OCR_AUDIT_V1.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_MISSING_SOURCE_RECOVERY_CREDIT_GATE_V1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    source_map = load(SOURCE_MAP)
    plan = load(PLAN)
    ocr = load(OCR)
    unresolved = source_map["unresolved_canonical_units"]
    missing = [row["unit_id"] if isinstance(row, dict) else row for row in unresolved]
    units = {row["unit_id"]: row for row in plan["units"]}
    missing_duration = sum(float(units[unit]["duration_seconds"]) for unit in missing)

    # E36's paid U18D Fast source is an exact observed 6 s / 96 credit charge.
    # Use that lowest demonstrated rate as a conservative floor, not a quote.
    observed_fast_rate = 16
    video_floor = int(missing_duration * observed_fast_rate)
    paid_before = int(source_map["credits"]["episode_total"])
    cap = int(source_map["credits"]["cap"])
    headroom = cap - paid_before
    projected_floor = paid_before + video_floor

    warnings = {}
    for item in ocr.get("unlisted_chinese_warnings", []):
        name = Path(item["file"]).name
        unit = next((candidate for candidate in missing if f"-{candidate}-" in name), None)
        if unit is None and "-U20-" in name:
            unit = "U20A"
        warnings.setdefault(unit or "UNKNOWN", []).append(item["text"])

    dialogue_units = {"U09", "U10", "U14", "U20A"}
    rows = []
    for unit in missing:
        duration = float(units[unit]["duration_seconds"])
        rows.append(
            {
                "unit_id": unit,
                "duration_seconds": duration,
                "dialogue_required": unit in dialogue_units,
                "native_video_model_audio_required": unit in dialogue_units,
                "accepted_motion_source_exists": False,
                "zero_credit_local_assembly_admissible": False,
                "conservative_video_credit_floor": int(duration * observed_fast_rate),
                "anchor_ocr_warnings": warnings.get(unit, []),
            }
        )

    payload = {
        "schema": "qingshan.e36_missing_source_recovery_credit_gate.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-786",
        "source_mailbox_sha256": "5f3e8503f69ff55a1fde635e53a392a7afb4c9746672f9696b31176375becd9e",
        "inputs": {
            "accepted_only_source_map": {"path": str(SOURCE_MAP.relative_to(ROOT)), "sha256": sha256(SOURCE_MAP)},
            "natural_unit_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": sha256(PLAN)},
            "anchor_ocr_audit": {"path": str(OCR.relative_to(ROOT)), "sha256": sha256(OCR)},
        },
        "missing_units": rows,
        "missing_unit_count": len(missing),
        "missing_runtime_seconds": missing_duration,
        "dialogue_missing_units": sorted(dialogue_units.intersection(missing)),
        "credit_gate": {
            "episode_paid_credits": paid_before,
            "episode_limit_credits": cap,
            "headroom_credits": headroom,
            "observed_lowest_video_rate_credits_per_second": observed_fast_rate,
            "observed_rate_evidence": "E36 U18D Fast: 6 seconds, exact Pay96",
            "video_only_conservative_floor_credits": video_floor,
            "projected_episode_floor_credits": projected_floor,
            "minimum_shortfall_credits": max(0, projected_floor - cap),
            "image_repairs_excluded_from_floor": True,
            "status": "FAIL_EXCEEDS_6000_WITHOUT_APPROVAL" if projected_floor > cap else "PASS_WITHIN_CAP",
        },
        "gate_results": {
            "canonical_source_coverage": "FAIL_24_OF_30",
            "native_dialogue_coverage": "FAIL_MISSING_U09_U10_U14_U20A",
            "anchor_ocr_runtime": "PASS_AVAILABLE",
            "anchor_text_continuity": "FAIL_U09_U14_VARIANT_SIGN_TEXT",
            "credit_cap": "FAIL_MINIMUM_VIDEO_ONLY_FLOOR_EXCEEDS_CAP",
            "agentcut_render": "BLOCKED_DO_NOT_RENDER_INCOMPLETE_EPISODE",
        },
        "blocked_by": "CREDIT_CAP_INSUFFICIENT_FOR_SIX_MISSING_CANONICAL_VIDEO_SOURCES",
        "next_action": "Hold remote submission and full-cut render. A revised cap or an explicitly approved above-cap ceiling is required before producing U04,U08,U09,U10,U14,U20A; then rerun source-map and full-cut QA.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "status": payload["credit_gate"]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
