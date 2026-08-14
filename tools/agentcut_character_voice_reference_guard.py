#!/usr/bin/env python3
"""Hard-gate canonical character voices to AgentCut speech receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "configs/agentcut_character_voice_reference_policy_v1.json"
DEFAULT_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
EXEMPT = {"chenji", "baili"}
READY = {"LOCKED_PRODUCTION_READY", "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def performance_brief_sha256(spec: dict) -> str:
    brief = {
        key: spec[key]
        for key in (
            "identity", "social_position", "temperament", "dramatic_function",
            "voice_id", "voice_name", "sample_text", "emotion", "speed",
        )
    }
    return hashlib.sha256(
        json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def evaluate(policy: dict, registry: dict) -> dict:
    authority = {row.get("entity_id"): row for row in registry.get("major_roles", [])}
    expected = {row["entity_id"]: row for row in policy.get("roles", [])}
    failures = []
    results = []
    voice_owners = {}
    for entity_id, spec in expected.items():
        row = authority.get(entity_id)
        row_failures = []
        voice_id = spec.get("voice_id")
        if not voice_id:
            row_failures.append("ROLE_SPECIFIC_VOICE_PRESET_MISSING")
        elif voice_id in voice_owners:
            row_failures.append("VOICE_PRESET_REUSED_ACROSS_CHARACTERS")
        else:
            voice_owners[voice_id] = entity_id
        for required in ("identity", "social_position", "temperament", "dramatic_function", "voice_name", "emotion"):
            if not spec.get(required):
                row_failures.append(f"ROLE_PERFORMANCE_FIELD_MISSING:{required}")
        if not row:
            row_failures.append("MISSING_REGISTRY_ENTRY")
        else:
            if row.get("status") not in READY:
                row_failures.append("VOICE_NOT_PRODUCTION_READY")
            if row.get("source_generator") != "AGENTCUT_SPEECH_GENERATION":
                row_failures.append("CANONICAL_SOURCE_NOT_AGENTCUT")
            if row.get("agentcut_capability") != "AGENTCUT-SPEECH-001":
                row_failures.append("AGENTCUT_CAPABILITY_RECEIPT_MISSING")
            if row.get("generation_voice_id") != spec.get("voice_id"):
                row_failures.append("ROLE_VOICE_PRESET_NOT_CURRENT_POLICY")
            if row.get("generation_voice_name") != spec.get("voice_name"):
                row_failures.append("ROLE_VOICE_NAME_NOT_CURRENT_POLICY")
            if row.get("performance_brief_sha256") != performance_brief_sha256(spec):
                row_failures.append("ROLE_PERFORMANCE_BRIEF_NOT_LOCKED")
            if not row.get("generation_task_id"):
                row_failures.append("GENERATION_TASK_ID_MISSING")
            if not row.get("remote_asset_id"):
                row_failures.append("REMOTE_ASSET_ID_MISSING")
            if not row.get("registration_receipt"):
                row_failures.append("REGISTRATION_RECEIPT_MISSING")
            if not row.get("qa_receipt"):
                row_failures.append("QA_RECEIPT_MISSING")
            local = row.get("local_reference")
            if not local or not resolve(local).is_file():
                row_failures.append("LOCAL_REFERENCE_MISSING")
            elif sha256(resolve(local)) != row.get("local_sha256"):
                row_failures.append("LOCAL_REFERENCE_SHA_MISMATCH")
            if row.get("credit_status") not in {"KNOWN_EXACT_TASK_STATEMENT", "UNKNOWN_NOT_ESTIMATED"}:
                row_failures.append("CREDIT_ACCOUNTING_MISSING")
        result = {
            "entity_id": entity_id,
            "name": spec["name"],
            "status": "PASS" if not row_failures else "FAIL",
            "failures": row_failures,
        }
        results.append(result)
        failures.extend({"entity_id": entity_id, "code": code} for code in row_failures)

    for entity_id in EXEMPT:
        row = authority.get(entity_id)
        if not row or row.get("status") not in READY or not row.get("remote_asset_id"):
            failures.append({"entity_id": entity_id, "code": "EXEMPT_NATIVE_VOICE_NOT_LOCKED"})

    return {
        "schema": "qingshan.agentcut_character_voice_reference_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "exempt_existing_native_voices": sorted(EXEMPT),
        "checked_agentcut_roles": len(expected),
        "results": results,
        "failures": failures,
        "policy": "Only Chenji and BaiLi may retain pre-AgentCut canonical voices. Every other current or future character must have an AgentCut generation receipt, QA receipt, exact registered asset ID, local SHA, and credit observation before speaking generation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--out")
    args = parser.parse_args()
    report = evaluate(load(resolve(args.policy)), load(resolve(args.registry)))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        output = resolve(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
