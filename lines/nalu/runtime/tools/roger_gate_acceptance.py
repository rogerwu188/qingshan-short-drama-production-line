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


# ---------------------------------------------------------------------------
# STANDING_RULE auto-acceptance (D-71, 2026-10-10)
#
# A GATE_FAIL_ACCEPTANCE order names each failing detector and binds the media sha it was
# issued against, so every regenerated keyframe needs a fresh signature.  Roger's
# 「同意，做吧」 to the redundancy plan asked for the other half: a policy signed ONCE,
# which the line applies itself and cites, instead of stopping per still.
#
# What he signed (seq=28, in his own words) was: 前景人物背对镜头、无脸可测；画内可见人物
# 余弦 0.64–0.87 全部通过.  That is a statement about a STILL and it is fully
# machine-derivable, so the rule re-derives it on every evaluation instead of binding a
# list of shas.  Three things must hold together:
#
#   1. an active, source-receipted STANDING_RULE from the line owner for this episode and
#      gate, carrying the NO_FACE_PIXELS_IN_STILL scope;
#   2. the still's ONLY failing registered gate is the identity gate — a still that also
#      fails scene / action / period is a different problem and stops the line;
#   3. every identity failure for the still is a NO-FACE-PIXELS code, AND every other
#      declared character measured a real PASS.  This is the part that keeps the rule from
#      becoming a way to wave through identity drift: a measured low cosine
#      (IDENTITY_BELOW_FAIL_THRESHOLD, BOUNDARY_REQUIRES_HUMAN, ...) is never a
#      no-face-pixels code, so a wrong face always stops the line for a human.
#
# Deliberately NOT part of the condition: parsing the contract's axis text.  Tested against
# the seven stills Roger actually accepted, a text rule recovered five — the contract words
# the same pose several ways (背对镜头 / 画右外 / 跟在身后).  A rule that covers five of
# seven is not a rule; the measurement is.
# ---------------------------------------------------------------------------

STANDING_KIND = "STANDING_RULE"
NO_FACE_PIXELS_SCOPE = "NO_FACE_PIXELS_IN_STILL"

#: Codes asserting the detector found no face pixels at all, which is the state this rule
#: covers.  A measured cosine that came back low is a different animal and is absent here
#: by design — never add a similarity code to this tuple.
NO_FACE_PIXELS_FAILURE_CODES = (
    "NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER",
    "DECLARED_CHARACTER_FACE_NOT_FOUND",
)


NO_FACE_PIXELS_RE = re.compile(
    r"(?:" + "|".join(NO_FACE_PIXELS_FAILURE_CODES) + r"):(?:[A-Z0-9-]+:)?([A-Za-z0-9][A-Za-z0-9-]*)")


def no_face_pixels_character(failure: str) -> str | None:
    """The character a no-face-pixels failure names, else None.

    ``NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:CHAR-QINMING``
    ``DECLARED_CHARACTER_FACE_NOT_FOUND:E11-S01-01:CHAR-QINMING``

    The optional middle group is the item id, present in the second form only, so one
    pattern reads both.
    """
    found = NO_FACE_PIXELS_RE.search(str(failure or ""))
    return found.group(1).upper() if found else None


def find_standing_rule(orders: list[dict[str, Any]], *, episode: str, gate_id: str,
                       expected_issuer: str, engine_root: Path | None = None,
                       scope_rule: str = NO_FACE_PIXELS_SCOPE) -> dict[str, Any] | None:
    """Newest active source-receipted STANDING_RULE carrying ``scope_rule`` for this episode+gate."""
    if not expected_issuer:
        return None
    match = None
    for row in orders:
        dec = row.get("decision") or {}
        scope = dec.get("auto_accept_scope") or {}
        if (str(row.get("issued_by") or "") != expected_issuer
                or str(row.get("status") or "") != "active"
                or not str(row.get("id") or "").strip()
                or not str(row.get("order") or "").strip()
                or dec.get("kind") != STANDING_KIND
                or str(dec.get("episode") or "") != episode
                or str(dec.get("gate_id") or "") != gate_id
                or str(scope.get("rule") or "") != scope_rule
                or not str(scope.get("criteria_verbatim") or "").strip()
                or not _receipt_valid(row, expected_issuer=expected_issuer, engine_root=engine_root)):
            continue
        if match is None or int(row.get("seq") or 0) > int(match.get("seq") or 0):
            match = row
    return match


def standing_rule_condition(*, failed_gates: list[str], identity_failures: list[str],
                            identity_gate_id: str, decisions: list[dict[str, Any]],
                            declared_characters: list[str]) -> dict[str, Any]:
    """Re-derive the NO_FACE_PIXELS_IN_STILL condition from one still's own measurements.

    ``identity_failures`` are the identity gate's raw failure codes, not "<item>:<char>"
    detector names.  The returned record carries both ``covered`` and the evidence the
    decision rested on, so the acceptance stays auditable without re-reading the media.
    """
    no_face = [str(f) for f in identity_failures if no_face_pixels_character(f)]
    measured = [str(f) for f in identity_failures if not no_face_pixels_character(f)]
    excused = sorted({no_face_pixels_character(f) for f in no_face} - {None})
    decided = {str(d.get("character_id")): str(d.get("decision")) for d in decisions if d.get("character_id")}
    others = {cid: decided.get(cid, "NO_DECISION") for cid in declared_characters if cid not in excused}
    other_gates = sorted({str(g) for g in failed_gates if str(g) != identity_gate_id})
    condition = {
        "rule": NO_FACE_PIXELS_SCOPE,
        "identity_gate_failures": sorted(str(f) for f in identity_failures),
        "no_face_pixels_failures": no_face,
        "excused_characters": excused,
        "other_declared_character_decisions": others,
        "other_failing_gates": other_gates,
        "declared_characters": sorted(declared_characters),
    }
    if not no_face:
        return {**condition, "covered": False, "reason": "NO_NO_FACE_PIXELS_FAILURE"}
    if measured:
        # a face was found and did not measure up — a human decides, never this rule
        return {**condition, "covered": False, "reason": "MEASURED_IDENTITY_FAILURE_PRESENT",
                "measured_failures": sorted(set(measured))}
    if other_gates:
        return {**condition, "covered": False, "reason": "OTHER_REGISTERED_GATE_ALSO_FAILED"}
    if not others or sorted(set(others.values())) != ["PASS"]:
        # every other declared character must have been measured and passed.  A missing
        # decision is NOT a pass: it is an unmeasured declared face.
        return {**condition, "covered": False, "reason": "OTHER_DECLARED_CHARACTER_NOT_MEASURED_PASS"}
    return {**condition, "covered": True,
            "reason": "NO_FACE_PIXELS_AND_ALL_OTHER_DECLARED_CHARACTERS_PASSED"}


def standing_rule_acceptance(order: dict[str, Any], *, episode: str, gate_id: str,
                             excused_detectors: list[str], condition: dict[str, Any],
                             media_sha256: str, gate_result_path: str,
                             media_item_id: str | None = None) -> dict[str, Any]:
    """The record written when a STANDING_RULE — not a per-item signature — admits a still.

    ``media_sha256_admitted`` records which still was admitted; it is NOT what authorises the
    acceptance, because a regenerated frame is admissible under the same rule and is
    re-checked then.
    """
    scope = (order.get("decision") or {}).get("auto_accept_scope") or {}
    return {
        "schema": "qingshan.line_owner_standing_rule_acceptance.v1",
        "episode": episode, "gate_id": gate_id,
        "gate_status_kept": "FAIL",
        "accepted_detectors": sorted(excused_detectors),
        "order_seq": order.get("seq"), "order_id": order.get("id"),
        "issued_by": order.get("issued_by"), "order_verbatim": order.get("order"),
        "order_ts_utc": order.get("ts_utc"),
        "source_receipt": order.get("source_receipt"),
        "applied_rule": scope.get("rule"),
        "rule_criteria_verbatim": scope.get("criteria_verbatim"),
        "condition_verified": condition,
        "condition_source": "the still's own gate measurements, re-derived at evaluation time",
        "media_item_id": media_item_id,
        "media_sha256_admitted": str(media_sha256 or ""),
        "media_sha256_binding": ("NOT_A_SHA_BINDING: the rule covers a condition, so a regenerated still "
                                 "is re-checked rather than inherited"),
        "gate_result": gate_result_path,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "self_issued": False,
        "note": ("Standing line-owner rule, not a per-frame signature: the gate row keeps its FAIL and its "
                 "evidence. A measured low-similarity identity failure, or any second failing gate, is "
                 "outside this rule and still stops the line."),
    }
