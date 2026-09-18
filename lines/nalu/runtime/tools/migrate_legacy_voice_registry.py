#!/usr/bin/env python3
"""Offline migration of legacy Qingshan voice registrations into one episode scope.

This is deliberately an import, not a generator: it copies only rows whose
legacy registration is already production-ready and whose local reference file
still exists.  Missing roles remain absent/pending so no provider id is ever
invented and no paid request is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--legacy-registry", required=True)
    ap.add_argument("--registry-out", required=True)
    ap.add_argument("--catalog-out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    legacy = json.loads(Path(args.legacy_registry).read_text(encoding="utf-8"))
    old = {str(r.get("entity_id")): r for r in legacy.get("major_roles", [])}
    speaking = {}
    for shot in contract.get("shots", []):
        raw = str(shot.get("dialogue") or (shot.get("prompt_spec") or {}).get("dialogue") or "")
        for line in raw.splitlines():
            speaker, sep, _ = line.partition("：")
            if sep:
                for row in contract.get("character_entities", []):
                    names = {str(row.get("canonical_name"))} | {str(a) for a in row.get("aliases") or []}
                    if speaker.strip() in names:
                        speaking[str(row["character_id"])] = row
    rows = []
    imported, pending = [], []
    for entity_id, character in speaking.items():
        row = old.get(entity_id)
        ref = Path(str((row or {}).get("local_reference") or ""))
        if row and row.get("remote_asset_id") and ref.is_file() and row.get("status", "").endswith("PRODUCTION_READY"):
            copied = dict(row)
            # The nalu orchestrator intentionally has one terminal lock value;
            # normalize the legacy AgentCut-qualified status to that value
            # while retaining the original in provenance.
            copied["legacy_status"] = row.get("status")
            copied["status"] = "LOCKED_PRODUCTION_READY"
            copied["character_id"] = entity_id
            copied["episode_scope"] = str(contract.get("episode", "E59"))
            copied["legacy_source_registry"] = str(Path(args.legacy_registry).resolve())
            copied["local_sha256"] = sha(ref)
            rows.append(copied)
            imported.append({"entity_id": entity_id, "remote_asset_id": row["remote_asset_id"], "local_reference": str(ref), "local_sha256": copied["local_sha256"]})
        else:
            pending.append({"entity_id": entity_id, "canonical_name": character.get("canonical_name"), "reason": "NO_VERIFIED_LEGACY_PRODUCTION_READY_REFERENCE"})

    out = {
        "schema": "qingshan.voice_reference_registry.v1",
        "status": "PARTIAL_LEGACY_IMPORT_PENDING_REMAINDER",
        "line": "qingshan",
        "work": "青山",
        "project_id": "QINGSHAN-E59",
        "episode_scope": "E59",
        "recorded_at_utc": now(),
        "read_via": "QINGSHAN_VOICE_REGISTRY",
        "policy": {
            "language": "zh-CN",
            "max_audio_references_per_provider_task": 1,
            "h3_speaking_identities_per_task": 1,
            "tts_substitution_on_native_speaking_shots": "FORBIDDEN",
            "canonical_generator_for_nonexempt_characters": "AgentCut AGENTCUT-SPEECH-001",
            "missing_reference_action": "KEEP_PENDING_UNTIL_PROVIDER_ASSET_AND_QA_RECEIPTS_EXIST",
            "only_legacy_native_voice_exemptions": ["chenji", "baili"],
        },
        "no_fabrication_contract": "Only verified legacy rows with existing local reference and remote asset id are imported; all other speaking roles remain pending.",
        "major_roles": rows,
    }
    catalog = {"schema": "nalu.voice_catalog.v1", "recorded_at_utc": now(), "source": "legacy qingshan registry import", "voices": {}}
    for row in rows:
        catalog["voices"][row["entity_id"]] = {
            "voice_id": row["remote_asset_id"],
            "voice_name": row.get("generation_voice_name") or row.get("name"),
            "reference_audio": row.get("local_reference"),
            "source": "LEGACY_VERIFIED_IMPORT",
        }
    for path, data in ((args.registry_out, out), (args.catalog_out, catalog)):
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"schema": "qingshan.legacy_voice_migration_report.v1", "episode": "E59", "paid": False, "imported": imported, "pending": pending, "legacy_registry": str(Path(args.legacy_registry).resolve())}
    p = Path(args.report); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_OFFLINE", "imported": len(imported), "pending": len(pending), "paid": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
