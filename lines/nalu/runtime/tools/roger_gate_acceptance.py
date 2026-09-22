#!/usr/bin/env python3
"""Fail-closed line-owner acceptance for a registered gate that remains FAIL.

An acceptance is not a waiver the producer can issue. The active line-owner
order must name the episode, gate and every failing detector, carry a confirmed
source receipt, and bind the current media by its exact SHA-256. Missing, null,
stale or item-mismatched media bindings are rejected.

The private order inbox is validated against the deployment-configured latest
sequence before candidates are considered. The gate result and its evidence
stay FAIL; the acceptance record explains why downstream work continued.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KIND = "GATE_FAIL_ACCEPTANCE"
ORDERS_SCHEMA = "supervisor_orders_v1"
RECEIPT_SCHEMA = "qingshan.line_owner_order_source_receipt.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _orders(path: Path, *, expected_latest_seq: int,
            engine_root: Path | None = None) -> list[dict[str, Any]]:
    """Read a current, uniquely sequenced private order inbox or return no authority."""
    try:
        resolved = Path(path).expanduser().resolve()
        if engine_root is not None:
            try:
                resolved.relative_to(Path(engine_root).expanduser().resolve())
            except ValueError:
                pass
            else:
                return []
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, dict) or payload.get("_schema") != ORDERS_SCHEMA:
        return []
    rows = payload.get("orders")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return []
    seqs = [row.get("seq") for row in rows]
    if any(isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 for seq in seqs):
        return []
    if len(seqs) != len(set(seqs)):
        return []
    latest = payload.get("latest_order_seq")
    if isinstance(latest, bool) or not isinstance(latest, int):
        return []
    if latest != expected_latest_seq or (max(seqs) if seqs else 0) != latest:
        return []
    return rows


def _receipt_valid(order: dict[str, Any], *, expected_issuer: str,
                   engine_root: Path | None = None) -> bool:
    binding = order.get("source_receipt")
    if not isinstance(binding, dict):
        return False
    try:
        path = Path(str(binding.get("path") or "")).expanduser()
        if not path.is_absolute():
            return False
        path = path.resolve()
        if engine_root is not None:
            try:
                path.relative_to(Path(engine_root).expanduser().resolve())
            except ValueError:
                pass
            else:
                return False
        expected_sha = str(binding.get("sha256") or "")
        if not SHA256_RE.fullmatch(expected_sha) or not path.is_file() or _sha256(path) != expected_sha:
            return False
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        isinstance(receipt, dict)
        and receipt.get("schema") == RECEIPT_SCHEMA
        and receipt.get("status") == "CONFIRMED"
        and str(receipt.get("issued_by") or "") == expected_issuer
        and receipt.get("order_seq") == order.get("seq")
        and str(receipt.get("order_id") or "") == str(order.get("id") or "")
        and str(receipt.get("verbatim") or "") == str(order.get("order") or "")
        and bool(str(receipt.get("recorded_at_utc") or "").strip())
    )


def _bound_sha(decision: dict[str, Any], media_item_id: str | None) -> str:
    if media_item_id is None:
        return str(decision.get("media_sha256") or "")
    by_item = decision.get("media_sha256_by_item")
    if not isinstance(by_item, dict):
        return ""
    return str(by_item.get(media_item_id) or "")


def find_acceptance(orders: list[dict[str, Any]], *, episode: str, gate_id: str,
                    failing: list[str], media_sha256: str | None,
                    expected_issuer: str, media_item_id: str | None = None,
                    engine_root: Path | None = None) -> dict[str, Any] | None:
    """Return the newest source-receipted order with an exact current-media binding."""
    current_sha = str(media_sha256 or "")
    required = {str(value) for value in failing if str(value)}
    if (not expected_issuer or not required or len(required) != len(failing)
            or not SHA256_RE.fullmatch(current_sha)):
        return None
    match = None
    for row in orders:
        dec = row.get("decision") or {}
        if (str(row.get("issued_by") or "") != expected_issuer
                or str(row.get("status") or "") != "active"
                or not str(row.get("id") or "").strip()
                or not str(row.get("order") or "").strip()
                or dec.get("kind") != KIND
                or str(dec.get("episode") or "") != episode
                or str(dec.get("gate_id") or "") != gate_id
                or not _receipt_valid(row, expected_issuer=expected_issuer,
                                      engine_root=engine_root)):
            continue
        allowed = {str(x) for x in dec.get("detectors") or [] if str(x)}
        if not required <= allowed:
            continue
        bound = _bound_sha(dec, media_item_id)
        if not SHA256_RE.fullmatch(bound) or bound != current_sha:
            continue
        if match is None or int(row.get("seq") or 0) > int(match.get("seq") or 0):
            match = row
    return match


def acceptance_record(order: dict[str, Any], *, episode: str, gate_id: str,
                      failing: list[str], media_sha256: str | None,
                      gate_result_path: str, media_item_id: str | None = None) -> dict[str, Any]:
    current_sha = str(media_sha256 or "")
    dec = order.get("decision") or {}
    bound_sha = _bound_sha(dec, media_item_id)
    if not SHA256_RE.fullmatch(current_sha) or bound_sha != current_sha:
        raise ValueError("acceptance record requires the exact current media sha256 bound by the order")
    return {
        "schema": "qingshan.line_owner_gate_acceptance.v2",
        "episode": episode, "gate_id": gate_id,
        "gate_status_kept": "FAIL",
        "accepted_detectors": sorted(failing),
        "order_seq": order.get("seq"), "order_id": order.get("id"),
        "issued_by": order.get("issued_by"), "order_verbatim": order.get("order"),
        "order_ts_utc": order.get("ts_utc"),
        "source_receipt": order.get("source_receipt"),
        "media_item_id": media_item_id,
        "media_sha256": current_sha,
        "media_sha256_bound_by_order": bound_sha,
        "gate_result": gate_result_path,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "self_issued": False,
        "note": "The gate row stays FAIL with its evidence; the stage continued on this explicit line-owner order only.",
    }


def failing_detectors(gate_result: dict[str, Any]) -> list[str]:
    """Detector names from a final-cut audience gate result."""
    names = [str(k) for k, v in (gate_result.get("detectors") or {}).items() if str(v) == "FAIL"]
    if names:
        return sorted(names)
    return sorted({str(f).split(":")[0] for f in gate_result.get("failures") or [] if str(f)})
