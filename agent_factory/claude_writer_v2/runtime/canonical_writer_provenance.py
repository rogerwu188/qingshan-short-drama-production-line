#!/usr/bin/env python3
"""Validate exact runtime provenance for a canonical Writer run."""

from __future__ import annotations

import hashlib
import re
from typing import Any


PROVENANCE_SCHEMA = "qingshan.canonical_writer_provenance.v1"
RECEIPT_SCHEMA = "qingshan.canonical_writer_run_receipt.v1"
ALLOWED_AGENT_IDS = {
    "qingshan-claude-writer-agent",
    "qingshan-claude-writer",
}
GENERIC_MODEL_ALIASES = {
    "claude",
    "fable",
    "fable 5",
    "opus",
    "claude opus",
    "default",
    "auto",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID = re.compile(r"^WRITER-E[0-9]+-V[0-9]+-[A-Z0-9][A-Z0-9_-]*$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def combined_rules_sha(rows: list[dict[str, Any]]) -> str:
    normalized = "\n".join(
        f"{str(row.get('path') or '')}\0{str(row.get('sha256') or '')}"
        for row in rows
    )
    return sha256_bytes(normalized.encode("utf-8"))


def _nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _exact_model(value: Any) -> bool:
    model = str(value or "").strip()
    return bool(model) and model.lower() not in GENERIC_MODEL_ALIASES


def validate_writer_provenance(
    manifest: dict[str, Any],
    *,
    receipt: dict[str, Any] | None,
    receipt_sha256: str | None,
    authority_sha256: str,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    provenance = manifest.get("writer_provenance")
    if not isinstance(provenance, dict):
        return ["WRITER_PROVENANCE_MISSING"], {"present": False}

    if provenance.get("schema") != PROVENANCE_SCHEMA:
        failures.append("WRITER_PROVENANCE_SCHEMA_INVALID")
    run_id = str(provenance.get("writer_run_id") or "")
    if not RUN_ID.fullmatch(run_id):
        failures.append("WRITER_RUN_ID_INVALID")
    agent_id = str(provenance.get("agent_id") or "")
    if agent_id not in ALLOWED_AGENT_IDS:
        failures.append("WRITER_AGENT_NOT_AUTHORIZED")
    if not _nonempty(provenance.get("provider")):
        failures.append("WRITER_PROVIDER_NOT_DECLARED")
    if not _exact_model(provenance.get("model_id")):
        failures.append("WRITER_MODEL_ID_NOT_EXACT")
    if not _nonempty(provenance.get("session_or_task_id")):
        failures.append("WRITER_SESSION_OR_TASK_ID_MISSING")

    sha_fields = (
        "input_bundle_sha256",
        "writer_rules_sha256",
        "authority_output_sha256",
        "receipt_sha256",
    )
    for field in sha_fields:
        if not SHA256.fullmatch(str(provenance.get(field) or "")):
            failures.append(f"WRITER_PROVENANCE_SHA_INVALID:{field}")
    if provenance.get("authority_output_sha256") != authority_sha256:
        failures.append("WRITER_AUTHORITY_OUTPUT_SHA_MISMATCH")
    if not _nonempty(provenance.get("receipt_path")):
        failures.append("WRITER_RECEIPT_PATH_MISSING")
    if not _nonempty(provenance.get("started_at")) or not _nonempty(provenance.get("completed_at")):
        failures.append("WRITER_RUN_TIMESTAMPS_MISSING")

    if not isinstance(receipt, dict):
        failures.append("WRITER_RUN_RECEIPT_UNAVAILABLE")
        return list(dict.fromkeys(failures)), {
            "present": True,
            "writer_run_id": run_id,
            "agent_id": agent_id,
            "provider": provenance.get("provider"),
            "model_id": provenance.get("model_id"),
            "receipt_verified": False,
        }

    if not SHA256.fullmatch(str(receipt_sha256 or "")):
        failures.append("WRITER_RUN_RECEIPT_SHA_UNAVAILABLE")
    elif provenance.get("receipt_sha256") != receipt_sha256:
        failures.append("WRITER_RUN_RECEIPT_SHA_MISMATCH")

    if receipt.get("schema") != RECEIPT_SCHEMA:
        failures.append("WRITER_RUN_RECEIPT_SCHEMA_INVALID")
    if receipt.get("status") != "COMPLETED":
        failures.append("WRITER_RUN_RECEIPT_NOT_COMPLETED")
    pairs = (
        ("writer_run_id", "writer_run_id"),
        ("agent_id", "agent_id"),
        ("provider", "provider"),
        ("model_id", "model_id"),
        ("session_or_task_id", "session_or_task_id"),
        ("started_at", "started_at"),
        ("completed_at", "completed_at"),
    )
    for manifest_key, receipt_key in pairs:
        if provenance.get(manifest_key) != receipt.get(receipt_key):
            failures.append(f"WRITER_RECEIPT_BINDING_MISMATCH:{manifest_key}")
    nested_pairs = (
        ("input_bundle_sha256", ("input_bundle", "sha256")),
        ("writer_rules_sha256", ("writer_rules", "combined_sha256")),
        ("authority_output_sha256", ("authority_output", "sha256")),
    )
    for manifest_key, (section, receipt_key) in nested_pairs:
        section_value = receipt.get(section) or {}
        if provenance.get(manifest_key) != section_value.get(receipt_key):
            failures.append(f"WRITER_RECEIPT_BINDING_MISMATCH:{manifest_key}")

    return list(dict.fromkeys(failures)), {
        "present": True,
        "writer_run_id": run_id,
        "agent_id": agent_id,
        "provider": provenance.get("provider"),
        "model_id": provenance.get("model_id"),
        "session_or_task_id_present": _nonempty(provenance.get("session_or_task_id")),
        "receipt_verified": not failures,
    }
