"""Adoption receipts: AVAILABLE -> SELECTED -> APPLIED -> VERIFIED -> OUTCOME_OBSERVED.

Each state is a separate, evidence-bearing receipt (contracts.validate_adoption):

* SELECTED  -- chosen into this run's plan; says nothing about execution.
* APPLIED   -- the rule's clause is present in the compiled output AND absent from a
               compile of the same unit without the rule (``change_evidence``), with the
               source contract and compiled output digests.  Scope COMPILED_REQUEST for an
               offline compile; PROVIDER_REQUEST only from the submitter's final payload.
* VERIFIED  -- a named assertion that ran over that actual output and passed.
* OUTCOME_OBSERVED -- only with a real generated media / final film sha256.  A test never
               produces it from synthetic video, and an accepted flaw is recorded as
               ACCEPTED_IMPERFECTION, never DEFECT_ABSENT.

READ (line_upgrade_gate) and EXPORTED (briefing contains the id) are not states here:
they cannot be turned into APPLIED by anything in this module.
"""
from __future__ import annotations

from typing import Any

from . import contracts as c

READ_SEMANTICS = "READ=BRIEFING_WRITTEN_NOT_APPLIED"


def _base(*, identity: dict[str, str], rule: dict[str, Any], stage: str, unit_ids: list[str], state: str,
          entrypoint: str, bundle_digest: str) -> dict[str, Any]:
    return {
        "schema": c.ADOPTION_SCHEMA, "schema_version": c.SCHEMA_VERSION, "receipt_id": c.new_uuid(),
        "tenant_id": identity["tenant_id"], "line_id": identity["line_id"], "device_id": identity["device_id"],
        "run_id": identity["run_id"], "rule_id": rule["rule_id"], "rule_version": rule["rule_version"],
        "bundle_digest": bundle_digest, "stage": stage, "unit_ids": sorted(unit_ids), "state": state,
        "entrypoint": entrypoint, "recorded_at": c.now_iso(),
    }


def selected(*, identity: dict[str, str], rule: dict[str, Any], stage: str, unit_ids: list[str],
             entrypoint: str, bundle_digest: str) -> dict[str, Any]:
    return c.validate_adoption(_base(identity=identity, rule=rule, stage=stage, unit_ids=unit_ids,
                                     state="SELECTED", entrypoint=entrypoint, bundle_digest=bundle_digest))


def not_adopted(*, identity: dict[str, str], rule: dict[str, Any], stage: str, unit_ids: list[str],
                entrypoint: str, bundle_digest: str, state: str, reason: str) -> dict[str, Any]:
    receipt = _base(identity=identity, rule=rule, stage=stage, unit_ids=unit_ids, state=state,
                    entrypoint=entrypoint, bundle_digest=bundle_digest)
    receipt["reason"] = reason
    return c.validate_adoption(receipt)


def applied(*, identity: dict[str, str], rule: dict[str, Any], stage: str, unit_ids: list[str], entrypoint: str,
            bundle_digest: str, clause: str, source_contract: Any, compiled_with: str, compiled_without: str,
            evidence_scope: str = "COMPILED_REQUEST", provider_request_digest: str | None = None,
            carrier_fields: list[str] | None = None) -> dict[str, Any]:
    """APPLIED only when the clause is in ``compiled_with`` and not in ``compiled_without``.

    Raises (no receipt) otherwise: a rule that changed nothing was not applied.
    """
    if evidence_scope == "PROVIDER_REQUEST" and not c.is_sha256(provider_request_digest):
        raise c.ContractError(["PROVIDER_REQUEST_SCOPE_NEEDS_PAYLOAD_DIGEST"])
    if evidence_scope not in ("COMPILED_REQUEST", "PROVIDER_REQUEST"):
        raise c.ContractError([f"APPLIED_SCOPE_MUST_BE_COMPILE_OR_REQUEST:{evidence_scope}"])
    if clause not in compiled_with:
        raise c.ContractError(["APPLIED_CLAUSE_ABSENT_FROM_COMPILED_OUTPUT"])
    if clause in compiled_without:
        raise c.ContractError(["APPLIED_CLAUSE_ALREADY_PRESENT_WITHOUT_RULE"])
    receipt = _base(identity=identity, rule=rule, stage=stage, unit_ids=unit_ids, state="APPLIED",
                    entrypoint=entrypoint, bundle_digest=bundle_digest)
    receipt.update(
        source_contract_digest=c.digest(source_contract),
        compiled_output_digest=c.sha256_bytes(compiled_with.encode("utf-8")),
        baseline_output_digest=c.sha256_bytes(compiled_without.encode("utf-8")),
        change_evidence={"clause_sha256": c.sha256_bytes(clause.encode("utf-8")),
                         "present_in_compiled_output": True, "absent_without_rule": True,
                         "carrier_fields": sorted(carrier_fields or [])},
        evidence_scope=evidence_scope,
        outcome_observed=False,
    )
    if provider_request_digest:
        receipt["provider_request_digest"] = provider_request_digest
    return c.validate_adoption(receipt)


def verified(applied_receipt: dict[str, Any], *, test_name: str, assertion: str, passed: bool,
             checked_output_digest: str) -> dict[str, Any]:
    """Promote an APPLIED receipt after a named assertion over the SAME output passed."""
    if applied_receipt.get("state") != "APPLIED":
        raise c.ContractError(["VERIFIED_REQUIRES_APPLIED_RECEIPT"])
    if not passed:
        raise c.ContractError(["VERIFIED_REQUIRES_PASSING_ASSERTION"])
    if checked_output_digest not in (applied_receipt.get("compiled_output_digest"),
                                     applied_receipt.get("provider_request_digest")):
        raise c.ContractError(["VERIFIED_ASSERTION_NOT_OVER_APPLIED_OUTPUT"])
    receipt = {**applied_receipt, "receipt_id": c.new_uuid(), "state": "VERIFIED", "recorded_at": c.now_iso(),
               "supersedes_receipt_id": applied_receipt["receipt_id"],
               "verification": {"test_name": test_name, "assertion": assertion, "result": "PASS",
                                "checked_output_digest": checked_output_digest}}
    return c.validate_adoption(receipt)


def outcome_observed(verified_receipt: dict[str, Any], *, kind: str, media_sha256: str, evidence_scope: str,
                     observed_by: str, note: str = "") -> dict[str, Any]:
    """Only with a real media sha.  Never asserts causation: ``causal_claim`` is always False."""
    if verified_receipt.get("state") != "VERIFIED":
        raise c.ContractError(["OUTCOME_REQUIRES_VERIFIED_RECEIPT"])
    receipt = {**verified_receipt, "receipt_id": c.new_uuid(), "state": "OUTCOME_OBSERVED",
               "recorded_at": c.now_iso(), "supersedes_receipt_id": verified_receipt["receipt_id"],
               "evidence_scope": evidence_scope, "outcome_observed": True,
               "outcome": {"kind": kind, "media_sha256": media_sha256, "observed_by": observed_by,
                           "note": note, "causal_claim": False}}
    return c.validate_adoption(receipt)


def strongest_state(receipts: list[dict[str, Any]], rule_id: str) -> str:
    """The furthest evidence-backed state for a rule.  READ/EXPORTED never appear here."""
    order = ("AVAILABLE", "SELECTED", "APPLIED", "VERIFIED", "OUTCOME_OBSERVED")
    best = -1
    for row in receipts:
        if row.get("rule_id") != rule_id or row.get("state") not in order:
            continue
        try:
            c.validate_adoption(row)
        except c.ContractError:
            continue  # a receipt that does not carry its evidence does not count
        best = max(best, order.index(row["state"]))
    return order[best] if best >= 0 else "NONE"
