#!/usr/bin/env python3
"""Build the current voice inventory and deduplicated AgentCut speech credit audit."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
INVENTORY = ROOT / "configs/series_voice_archive_inventory_current_20260723.json"
CREDIT_AUDIT = ROOT / "workflow/credit_reports/AGENTCUT_CHARACTER_VOICE_CREDIT_AUDIT_20260723.json"
BATCH_GLOB = "AGENTCUT_CHARACTER_VOICE_REFERENCE_BATCH_V1_20260723*.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(registry: dict) -> dict:
    canonical = []
    legacy = []
    for row in registry.get("major_roles", []):
        local = Path(str(row.get("local_reference") or ""))
        canonical.append({
            "entity_id": row["entity_id"],
            "name": row["name"],
            "status": row["status"],
            "canonical_generator": row.get("source_generator") or row.get("source_type"),
            "agentcut_voice_preset": row.get("generation_voice_name"),
            "asset_id": row.get("remote_asset_id"),
            "remote_url": row.get("remote_url"),
            "local_file": row.get("local_reference"),
            "sha256": row.get("local_sha256"),
            "local_sha_verified": sha256(local) == row.get("local_sha256") if row.get("local_reference") else False,
            "duration_seconds": row.get("duration_seconds"),
            "qa_receipt": row.get("qa_receipt"),
            "registration_receipt": row.get("registration_receipt"),
            "generation_task_id": row.get("generation_task_id"),
            "actual_charged_credits": row.get("actual_charged_credits"),
            "performance_brief_sha256": row.get("performance_brief_sha256"),
        })
        for item in row.get("legacy_references") or []:
            legacy.append({"entity_id": row["entity_id"], "name": row["name"], **item})
    return {
        "schema": "qingshan.series_voice_archive_inventory.v2",
        "recorded_at_utc": utc_now(),
        "status": "CURRENT_AGENTCUT_POLICY_AUTHORITY",
        "policy": "Chenji and BaiLi retain their locked native references. Every other current or future character uses a role-specific AgentCut speech preset, QA, registration receipt, immutable SHA, and current performance-brief digest.",
        "summary": {
            "canonical_character_voices": len(canonical),
            "locked_native_exemptions": sum(row["entity_id"] in {"chenji", "baili"} for row in canonical),
            "agentcut_generated_canonical_voices": sum(row["status"] == "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY" for row in canonical),
            "legacy_noncanonical_archives": len(legacy),
        },
        "canonical_voices": canonical,
        "legacy_noncanonical_archives": legacy,
    }


def build_credit_audit() -> dict:
    tasks: dict[str, dict] = {}
    source_files = []
    for path in sorted((ROOT / "workflow/tasks").glob(BATCH_GLOB)):
        payload = load(path)
        source_files.append(str(path))
        for row in payload.get("registration_results") or []:
            task_id = str(row.get("generation_task_id") or "")
            credit = row.get("credit") or {}
            if not task_id:
                continue
            candidate = {
                "task_id": task_id,
                "entity_id": row.get("entity_id"),
                "registration_status": row.get("status"),
                "credit_status": credit.get("status"),
                "charged_credits": credit.get("charged_credits"),
                "statement_rows": credit.get("statement_rows") or [],
                "source_batch_receipt": str(path),
            }
            existing = tasks.get(task_id)
            if not existing or candidate["registration_status"] == "REGISTERED":
                tasks[task_id] = candidate
    known = [row for row in tasks.values() if row["charged_credits"] is not None]
    total = sum(Decimal(str(row["charged_credits"])) for row in known)
    return {
        "schema": "qingshan.agentcut_character_voice_credit_audit.v1",
        "recorded_at_utc": utc_now(),
        "status": "PASS" if len(known) == len(tasks) else "INCOMPLETE_UNKNOWN_PRESENT",
        "accounting_rule": "Deduplicate by immutable remote generation task_id. Use only explicit credit-statement rows; never estimate.",
        "unique_remote_generation_calls": len(tasks),
        "known_credit_calls": len(known),
        "unknown_credit_calls": len(tasks) - len(known),
        "exact_total_credits": int(total) if total == total.to_integral() else str(total),
        "tasks": sorted(tasks.values(), key=lambda row: (str(row["entity_id"]), row["task_id"])),
        "source_batch_receipts": source_files,
    }


def main() -> int:
    registry = load(REGISTRY)
    inventory = build_inventory(registry)
    credit_audit = build_credit_audit()
    write_json(INVENTORY, inventory)
    write_json(CREDIT_AUDIT, credit_audit)
    print(json.dumps({
        "inventory_status": inventory["status"],
        "canonical_character_voices": inventory["summary"]["canonical_character_voices"],
        "agentcut_generated_canonical_voices": inventory["summary"]["agentcut_generated_canonical_voices"],
        "credit_status": credit_audit["status"],
        "unique_remote_generation_calls": credit_audit["unique_remote_generation_calls"],
        "exact_total_credits": credit_audit["exact_total_credits"],
    }, ensure_ascii=False))
    return 0 if credit_audit["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
