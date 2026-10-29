"""Record contracts shared by the device, the service and the bundle tools.

Every record here is validated in code (this module is the authority); the
JSON Schema files under ``configs/schemas/collective_learning/`` describe the
same shapes for other languages and are checked against these constants by
``tools/tests/test_collective_learning_contracts.py``.

Semantics carried from the requirement (sections 5.1-5.5):

* An ObservationEvent is a FACT.  It cannot carry a root cause, a release
  decision or any paid/publication authority -- those keys are rejected, not
  ignored, so a caller cannot believe it set them.
* Event identity is a global UUID chosen by the producer.  Re-sending the same
  id with the same content is idempotent; the same id with different content
  is a conflict that is recorded, never a silent overwrite.
* Attribution, correction and retraction are separate immutable revisions.
* Time codes name the exact video version (sha256) and timeline they belong to.
* Success and failure observations both carry an opportunity count so a rate
  can be computed; reporting only failures makes rates impossible.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"

OBSERVATION_SCHEMA = "qingshan.collective.observation_event.v1"
ATTRIBUTION_SCHEMA = "qingshan.collective.attribution_review.v1"
CANDIDATE_SCHEMA = "qingshan.collective.knowledge_candidate.v1"
ADOPTION_SCHEMA = "qingshan.collective.adoption_receipt.v1"
EVALUATION_SCHEMA = "qingshan.collective.director_evaluation.v1"
RUN_LOCK_SCHEMA = "qingshan.collective.run_knowledge_lock.v1"
BUNDLE_SCHEMA = "qingshan.collective.knowledge_bundle.v1"

UNKNOWN = "UNKNOWN"

EVENT_KINDS = (
    "FAILURE_OBSERVATION",
    "SUCCESS_OBSERVATION",
    "USER_CORRECTION",
    "FIX_RESULT",
    "RUN_ANOMALY",
)
# Kinds that describe how often something happened in a population of units,
# so a rate needs a denominator.
RATE_KINDS = ("FAILURE_OBSERVATION", "SUCCESS_OBSERVATION")

VISIBILITIES = (
    "PRIVATE_LOCAL",   # never leaves the device
    "LINE",            # shared with devices of the same line only
    "TENANT",          # shared within the tenant (all lines of one organisation)
)

TIMELINES = ("GENERATED_SOURCE", "FINAL_CUT", "KEYFRAME_STILL")

ATTRIBUTION_STATUSES = ("UNATTRIBUTED", "ATTRIBUTED", "INCONCLUSIVE")
ATTRIBUTION_BASIS = (
    "MODEL_HYPOTHESIS",         # a model proposed it; not reproduced
    "REPRODUCED",               # a minimal reproduction exists
    "BEHAVIORAL_REGRESSION",    # a deterministic test shows before/after
    "HUMAN_JUDGEMENT",          # a human reviewer's call on the evidence
)
CONFIDENCES = ("LOW", "MEDIUM", "HIGH")

CANDIDATE_CATEGORIES = (
    "DIRECTING_HEURISTIC",      # creative advice: needs real cases + independent review
    "ENGINEERING_INVARIANT",    # deterministic fix: minimal repro + behavioural regression suffices
    "MODEL_CONSTRAINT",         # provider/model-specific behaviour
    "EXECUTION_POLICY",         # how to schedule/run, never money or authority
)
EVIDENCE_LEVELS = ("NEEDS_EVIDENCE", "SINGLE_CASE", "REPRODUCED", "MULTI_CASE", "CROSS_LINE")
COST_CLASSES = ("FREE_LOCAL", "FREE_COMPILE_REPLAY", "PAID_REVIEW", "PAID_GENERATION")

RELEASE_STATES = ("CANDIDATE", "NEEDS_EVIDENCE", "REJECTED", "VALIDATED", "CANARY",
                  "RELEASED", "DEPRECATED", "REVOKED")
RELEASE_TRANSITIONS = {
    "CANDIDATE": {"VALIDATED", "REJECTED", "NEEDS_EVIDENCE"},
    "NEEDS_EVIDENCE": {"CANDIDATE", "REJECTED"},
    "VALIDATED": {"CANARY", "REJECTED"},
    "CANARY": {"RELEASED", "REVOKED", "DEPRECATED"},
    "RELEASED": {"DEPRECATED", "REVOKED"},
    "DEPRECATED": {"REVOKED"},
    "REJECTED": set(),
    "REVOKED": set(),
}
VALIDATION_SCOPES = (
    "STRUCTURE_VALID",
    "DETERMINISTIC_REGRESSION",
    "REAL_MEDIA_REVIEW",
    "CROSS_CASE_EFFECT",
)

ADOPTION_STATES = ("AVAILABLE", "SELECTED", "APPLIED", "VERIFIED", "OUTCOME_OBSERVED",
                   "NOT_APPLICABLE", "DEFERRED", "FAILED")
ADOPTION_NEEDS_REASON = ("NOT_APPLICABLE", "DEFERRED", "FAILED")
EVIDENCE_SCOPES = ("SOURCE_CONTRACT", "COMPILED_REQUEST", "PROVIDER_REQUEST", "GENERATED_MEDIA", "FINAL_FILM")
OUTCOME_KINDS = ("DEFECT_ABSENT", "DEFECT_RECURRED", "ACCEPTED_IMPERFECTION", "NO_CHANGE_OBSERVED")

# Keys an observation must never carry.  Rejected with an explicit error so a
# caller cannot believe the key took effect.
FORBIDDEN_OBSERVATION_KEYS = frozenset({
    "root_cause", "attribution", "release", "release_state", "publish", "publication_authorized",
    "paid_retry_authorized", "budget", "budget_increase", "authorization", "promote", "scope_global",
})
# Keys a knowledge candidate may carry only with the value False.  A candidate
# is data; it can never grant money, publication or execution authority.
AUTHORITY_FLAGS = ("paid_retry_authorized", "publication_authorized", "budget_change_authorized",
                   "execution_authorized")

# Sensitive content that must never leave a device in a shareable record.
_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ABSOLUTE_HOME_PATH", re.compile(r"(?:/Us" r"ers/|/home/|/private/var/|/var/folders/|[A-Za-z]:\\\\Users\\\\)")),
    ("PRESIGNED_URL", re.compile(r"(?i)(?:x-amz-signature|x-goog-signature|[?&]signature=|[?&]token=|[?&]sig=)")),
    ("BEARER_TOKEN", re.compile(r"(?i)bearer\s+[a-z0-9._\-]{8,}")),
    ("API_KEY", re.compile(r"(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|(?i:api[_-]?key)\s*[:=]\s*\S{8,})")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """A record violates its contract.  ``codes`` lists every failure, not just the first."""

    def __init__(self, codes: Iterable[str]):
        self.codes = list(codes)
        super().__init__(";".join(self.codes))


# --------------------------------------------------------------------------- primitives
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_uuid() -> str:
    return str(uuid.uuid4())


def canonical_json(payload: Any) -> bytes:
    """Byte-stable JSON: sorted keys, no whitespace, UTF-8.  Digests are over these bytes."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.match(value))


def is_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.match(value))


def sensitive_findings(payload: Any, *, path: str = "$") -> list[str]:
    """Every sensitive token in any string anywhere in ``payload`` (keys included)."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(sensitive_findings(str(key), path=f"{path}.<key>"))
            found.extend(sensitive_findings(value, path=f"{path}.{key}"))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            found.extend(sensitive_findings(value, path=f"{path}[{index}]"))
    elif isinstance(payload, str):
        for code, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(payload):
                found.append(f"SENSITIVE_CONTENT:{code}:{path}")
    return found


# --------------------------------------------------------------------------- observation
def _require(record: dict[str, Any], keys: Iterable[str], failures: list[str]) -> None:
    for key in keys:
        if key not in record or record[key] in (None, ""):
            failures.append(f"MISSING:{key}")


def validate_timecode(row: Any, index: int, failures: list[str]) -> None:
    if not isinstance(row, dict):
        failures.append(f"TIMECODE_NOT_OBJECT:{index}")
        return
    if not is_sha256(row.get("video_sha256")):
        failures.append(f"TIMECODE_VIDEO_VERSION_REQUIRED:{index}")
    if row.get("timeline") not in TIMELINES:
        failures.append(f"TIMECODE_TIMELINE_INVALID:{index}:{row.get('timeline')}")
    start, end = row.get("start_ms"), row.get("end_ms")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start:
        failures.append(f"TIMECODE_MS_INVALID:{index}")


def validate_observation(event: dict[str, Any]) -> dict[str, Any]:
    """Return ``event`` unchanged if it satisfies the ObservationEvent contract, else raise."""
    failures: list[str] = []
    if not isinstance(event, dict):
        raise ContractError(["OBSERVATION_NOT_OBJECT"])
    forbidden = sorted(FORBIDDEN_OBSERVATION_KEYS & set(event))
    failures.extend(f"FORBIDDEN_KEY_ON_FACT:{key}" for key in forbidden)
    _require(event, ("schema_version", "event_id", "tenant_id", "line_id", "device_id", "run_id",
                     "episode_id", "stage", "event_kind", "occurred_at", "producer_sequence",
                     "engine_version", "provider_model_version", "knowledge_bundle_digest",
                     "detected_by", "evidence", "symptom", "visibility"), failures)
    if event.get("schema_version") not in (None, "", SCHEMA_VERSION):
        failures.append(f"SCHEMA_VERSION_UNSUPPORTED:{event.get('schema_version')}")
    if event.get("event_id") and not is_uuid(event["event_id"]):
        failures.append("EVENT_ID_MUST_BE_UUID")
    for key in ("tenant_id", "line_id", "device_id", "run_id", "episode_id", "stage"):
        if event.get(key) and not is_identifier(event[key]):
            failures.append(f"IDENTIFIER_INVALID:{key}")
    if event.get("event_kind") and event["event_kind"] not in EVENT_KINDS:
        failures.append(f"EVENT_KIND_INVALID:{event['event_kind']}")
    if event.get("visibility") and event["visibility"] not in VISIBILITIES:
        failures.append(f"VISIBILITY_INVALID:{event['visibility']}")
    seq = event.get("producer_sequence")
    if seq is not None and (not isinstance(seq, int) or isinstance(seq, bool) or seq < 1):
        failures.append("PRODUCER_SEQUENCE_MUST_BE_POSITIVE_INT")
    units = event.get("unit_ids", [])
    if not isinstance(units, list) or not all(is_identifier(u) for u in units):
        failures.append("UNIT_IDS_INVALID")
    digest_value = event.get("artifact_digest")
    if digest_value not in (None, UNKNOWN) and not is_sha256(digest_value):
        failures.append("ARTIFACT_DIGEST_INVALID")
    bundle = event.get("knowledge_bundle_digest")
    if bundle not in (None, "", UNKNOWN, "NONE") and not is_sha256(bundle):
        failures.append("KNOWLEDGE_BUNDLE_DIGEST_INVALID")
    evidence = event.get("evidence")
    if evidence is not None and (not isinstance(evidence, dict) or not evidence):
        failures.append("EVIDENCE_MUST_BE_NONEMPTY_OBJECT")
    if isinstance(evidence, dict):
        for index, row in enumerate(evidence.get("timecodes") or []):
            validate_timecode(row, index, failures)
    symptom = event.get("symptom")
    if symptom is not None and (not isinstance(symptom, str) or not symptom.strip()):
        failures.append("SYMPTOM_MUST_BE_TEXT")
    if event.get("event_kind") in RATE_KINDS:
        opp = event.get("opportunity")
        if not isinstance(opp, dict):
            failures.append("OPPORTUNITY_REQUIRED_FOR_RATE_KIND")
        else:
            applicable, observed = opp.get("applicable_units"), opp.get("observed_units")
            if not isinstance(applicable, int) or applicable < 1:
                failures.append("OPPORTUNITY_APPLICABLE_UNITS_INVALID")
            if not isinstance(observed, int) or observed < 0 or (
                    isinstance(applicable, int) and observed > applicable):
                failures.append("OPPORTUNITY_OBSERVED_UNITS_INVALID")
    if event.get("visibility") in ("LINE", "TENANT"):
        failures.extend(sensitive_findings({k: v for k, v in event.items() if k != "received_at"}))
    if failures:
        raise ContractError(failures)
    return event


def observation_content(event: dict[str, Any]) -> dict[str, Any]:
    """The part of an event that defines its identity for idempotency.

    ``received_at`` is assigned by whoever stores the event and ``producer_sequence``
    re-numbering on a replay must not make a byte-identical fact look different, so
    neither is part of the content digest.
    """
    return {k: v for k, v in event.items() if k not in ("received_at",)}


def observation_digest(event: dict[str, Any]) -> str:
    return digest(observation_content(event))


def make_observation(*, tenant_id: str, line_id: str, device_id: str, run_id: str, episode_id: str,
                     stage: str, event_kind: str, symptom: str, evidence: dict[str, Any],
                     detected_by: str, producer_sequence: int, unit_ids: list[str] | None = None,
                     artifact_digest: str | None = None, engine_version: str = UNKNOWN,
                     provider_model_version: str = UNKNOWN, knowledge_bundle_digest: str = "NONE",
                     visibility: str = "PRIVATE_LOCAL", opportunity: dict[str, int] | None = None,
                     occurred_at: str | None = None, event_id: str | None = None,
                     source_event_id: str | None = None) -> dict[str, Any]:
    """Build (not store) a valid ObservationEvent.  Unknown versions stay UNKNOWN."""
    event: dict[str, Any] = {
        "schema": OBSERVATION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or new_uuid(),
        "tenant_id": tenant_id,
        "line_id": line_id,
        "device_id": device_id,
        "run_id": run_id,
        "episode_id": episode_id,
        "unit_ids": sorted(set(unit_ids or [])),
        "stage": stage,
        "event_kind": event_kind,
        "occurred_at": occurred_at or now_iso(),
        "producer_sequence": producer_sequence,
        "artifact_digest": artifact_digest or UNKNOWN,
        "engine_version": engine_version or UNKNOWN,
        "provider_model_version": provider_model_version or UNKNOWN,
        "knowledge_bundle_digest": knowledge_bundle_digest or "NONE",
        "detected_by": detected_by,
        "evidence": evidence,
        "symptom": re.sub(r"\s+", " ", symptom or "").strip(),
        "visibility": visibility,
    }
    if opportunity is not None:
        event["opportunity"] = dict(opportunity)
    if source_event_id:
        # A copy of an event observed elsewhere (e.g. a cloned device replaying a log):
        # the provenance link keeps it from counting as an independent observation.
        event["source_event_id"] = source_event_id
    return validate_observation(event)


# --------------------------------------------------------------------------- attribution
def validate_attribution(review: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    _require(review, ("review_id", "event_id", "reviewer_id", "status", "review_version"), failures)
    if review.get("review_id") and not is_uuid(review["review_id"]):
        failures.append("REVIEW_ID_MUST_BE_UUID")
    if review.get("event_id") and not is_uuid(review["event_id"]):
        failures.append("EVENT_ID_MUST_BE_UUID")
    status = review.get("status")
    if status and status not in ("ATTRIBUTED", "INCONCLUSIVE"):
        # UNATTRIBUTED is the absence of a review, never something a review asserts.
        failures.append(f"REVIEW_STATUS_INVALID:{status}")
    if status == "ATTRIBUTED":
        _require(review, ("root_cause_hypothesis", "basis", "confidence"), failures)
        if review.get("basis") and review["basis"] not in ATTRIBUTION_BASIS:
            failures.append(f"ATTRIBUTION_BASIS_INVALID:{review['basis']}")
        if review.get("confidence") and review["confidence"] not in CONFIDENCES:
            failures.append(f"CONFIDENCE_INVALID:{review['confidence']}")
        if review.get("basis") == "MODEL_HYPOTHESIS" and review.get("confidence") == "HIGH":
            failures.append("MODEL_HYPOTHESIS_CANNOT_BE_HIGH_CONFIDENCE")
        if not isinstance(review.get("supporting_evidence"), list) or not review.get("supporting_evidence"):
            failures.append("SUPPORTING_EVIDENCE_REQUIRED")
        if not isinstance(review.get("counter_evidence", []), list):
            failures.append("COUNTER_EVIDENCE_MUST_BE_LIST")
    if status == "INCONCLUSIVE":
        _require(review, ("reason",), failures)
    if not isinstance(review.get("review_version"), int) or review.get("review_version", 0) < 1:
        failures.append("REVIEW_VERSION_MUST_BE_POSITIVE_INT")
    if failures:
        raise ContractError(failures)
    return review


# --------------------------------------------------------------------------- candidate
SCOPE_KEYS = ("models", "model_modes", "engine_compat", "stages", "scene_types", "aspect_ratios",
              "languages", "shot_intents", "requires", "privacy")


def validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    _require(candidate, ("candidate_id", "revision", "category", "scope", "trigger", "recommendation",
                         "verification", "cost_class", "evidence_level"), failures)
    if candidate.get("candidate_id") and not is_identifier(candidate["candidate_id"]):
        failures.append("CANDIDATE_ID_INVALID")
    if not isinstance(candidate.get("revision"), int) or candidate.get("revision", 0) < 1:
        failures.append("REVISION_MUST_BE_POSITIVE_INT")
    if candidate.get("category") and candidate["category"] not in CANDIDATE_CATEGORIES:
        failures.append(f"CATEGORY_INVALID:{candidate['category']}")
    if candidate.get("cost_class") and candidate["cost_class"] not in COST_CLASSES:
        failures.append(f"COST_CLASS_INVALID:{candidate['cost_class']}")
    if candidate.get("evidence_level") and candidate["evidence_level"] not in EVIDENCE_LEVELS:
        failures.append(f"EVIDENCE_LEVEL_INVALID:{candidate['evidence_level']}")
    status = candidate.get("status", "CANDIDATE")
    if status not in ("CANDIDATE", "NEEDS_EVIDENCE"):
        # Release states are owned by the service's release policy, never by candidate text.
        failures.append(f"CANDIDATE_CANNOT_SELF_DECLARE_STATE:{status}")
    for flag in AUTHORITY_FLAGS:
        if candidate.get(flag) not in (None, False):
            failures.append(f"CANDIDATE_CANNOT_GRANT_AUTHORITY:{flag}")
    scope = candidate.get("scope")
    if not isinstance(scope, dict):
        failures.append("SCOPE_MUST_BE_OBJECT")
    else:
        unknown = sorted(set(scope) - set(SCOPE_KEYS))
        failures.extend(f"SCOPE_KEY_UNKNOWN:{key}" for key in unknown)
        for key in SCOPE_KEYS:
            if key in scope and key != "privacy" and not (
                    isinstance(scope[key], list) and all(isinstance(x, str) and x for x in scope[key])):
                failures.append(f"SCOPE_VALUE_MUST_BE_STRING_LIST:{key}")
        if not scope.get("models"):
            # An unscoped model list would match every device, which the requirement forbids.
            failures.append("SCOPE_MODELS_REQUIRED")
        if not scope.get("stages"):
            failures.append("SCOPE_STAGES_REQUIRED")
    for key in ("exceptions", "known_counterexamples", "event_ids", "implementation_refs"):
        if key in candidate and not isinstance(candidate[key], list):
            failures.append(f"{key.upper()}_MUST_BE_LIST")
    for event_id in candidate.get("event_ids") or []:
        if not is_uuid(event_id):
            failures.append(f"CANDIDATE_EVENT_ID_NOT_UUID:{event_id}")
    if candidate.get("category") == "DIRECTING_HEURISTIC" and not candidate.get("exceptions"):
        failures.append("DIRECTING_HEURISTIC_NEEDS_EXCEPTIONS")
    # Executable content never travels as knowledge data.
    for key in ("code", "python", "shell", "script", "exec"):
        if key in candidate:
            failures.append(f"KNOWLEDGE_CANNOT_CARRY_EXECUTABLE:{key}")
    failures.extend(sensitive_findings(candidate))
    if failures:
        raise ContractError(failures)
    return candidate


# --------------------------------------------------------------------------- adoption
def validate_adoption(receipt: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    _require(receipt, ("receipt_id", "tenant_id", "line_id", "device_id", "run_id", "rule_id",
                       "rule_version", "bundle_digest", "stage", "state", "entrypoint"), failures)
    state = receipt.get("state")
    if state and state not in ADOPTION_STATES:
        failures.append(f"ADOPTION_STATE_INVALID:{state}")
    if state in ADOPTION_NEEDS_REASON and not str(receipt.get("reason") or "").strip():
        failures.append(f"ADOPTION_REASON_REQUIRED:{state}")
    if state in ("APPLIED", "VERIFIED", "OUTCOME_OBSERVED"):
        # APPLIED needs evidence that the real contract/compile/request changed.
        if not is_sha256(receipt.get("source_contract_digest")):
            failures.append("APPLIED_NEEDS_SOURCE_CONTRACT_DIGEST")
        if not is_sha256(receipt.get("compiled_output_digest")):
            failures.append("APPLIED_NEEDS_COMPILED_OUTPUT_DIGEST")
        if not receipt.get("change_evidence"):
            failures.append("APPLIED_NEEDS_CHANGE_EVIDENCE")
        if receipt.get("evidence_scope") not in EVIDENCE_SCOPES:
            failures.append(f"EVIDENCE_SCOPE_INVALID:{receipt.get('evidence_scope')}")
    if state in ("VERIFIED", "OUTCOME_OBSERVED"):
        tests = receipt.get("verification") or {}
        if not tests.get("test_name") or tests.get("result") != "PASS" or not tests.get("assertion"):
            failures.append("VERIFIED_NEEDS_PASSING_NAMED_ASSERTION")
    if state == "OUTCOME_OBSERVED":
        outcome = receipt.get("outcome") or {}
        if outcome.get("kind") not in OUTCOME_KINDS:
            failures.append("OUTCOME_KIND_INVALID")
        if receipt.get("evidence_scope") not in ("GENERATED_MEDIA", "FINAL_FILM"):
            failures.append("OUTCOME_NEEDS_MEDIA_OR_FILM_SCOPE")
        if not is_sha256(outcome.get("media_sha256")):
            failures.append("OUTCOME_NEEDS_MEDIA_SHA256")
    if receipt.get("evidence_scope") == "FINAL_FILM" and not is_sha256(
            (receipt.get("outcome") or {}).get("media_sha256")):
        failures.append("FINAL_FILM_SCOPE_NEEDS_FILM_SHA256")
    if failures:
        raise ContractError(failures)
    return receipt


# --------------------------------------------------------------------------- scope matching
# scope key -> the capability key a device/run reports for it.  ``requires`` is a set
# test against ``capabilities["flags"]``; every other key is single-valued membership.
SCOPE_TO_CAPABILITY = {
    "models": "model",
    "model_modes": "model_mode",
    "engine_compat": "engine_api_version",
    "stages": "stage",
    "scene_types": "scene_type",
    "aspect_ratios": "aspect_ratio",
    "languages": "language",
    "shot_intents": "shot_intent",
}


def scope_matches(scope: dict[str, Any], capabilities: dict[str, Any]) -> tuple[bool, list[str]]:
    """Deterministic applicability filter.  Returns (matches, reasons-for-mismatch).

    * A scope key that is present and non-empty restricts; an absent key does not.
    * A capability the device does not know (missing, empty or UNKNOWN) never
      satisfies a restricting key: unknown conditions do not match everything.
    * ``models`` and ``stages`` are mandatory on every candidate (see
      :func:`validate_candidate`), so no rule is ever model- or stage-agnostic.
    * ``privacy == ["WORK_PRIVATE"]`` limits a rule to the tenant/line that owns it;
      the caller passes ``capabilities["owner_match"]``.
    """
    reasons: list[str] = []
    for key, cap_key in SCOPE_TO_CAPABILITY.items():
        allowed = scope.get(key) or []
        if not allowed:
            continue
        value = capabilities.get(cap_key)
        if value in (None, "", UNKNOWN):
            reasons.append(f"CAPABILITY_UNKNOWN:{cap_key}")
        elif value not in allowed:
            reasons.append(f"OUT_OF_SCOPE:{cap_key}={value}")
    flags = set(capabilities.get("flags") or [])
    missing = sorted(set(scope.get("requires") or []) - flags)
    reasons.extend(f"REQUIRED_CONDITION_ABSENT:{flag}" for flag in missing)
    if "WORK_PRIVATE" in (scope.get("privacy") or []) and not capabilities.get("owner_match"):
        reasons.append("WORK_PRIVATE_RULE_OTHER_OWNER")
    return (not reasons), reasons
