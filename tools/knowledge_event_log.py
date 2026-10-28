#!/usr/bin/env python3
"""knowledge_event_log — durable, line-agnostic registration of review/fix events.

Codex knowledge-loop audit 2026-10-27 (`reports/knowledge_loop_audit_20261027/`),
gap 1: a QA failure, a user correction, or a fix "has no formal producer that
registers it, has the agent attribute it, and tracks what happened to it."
`tools/knowledge_sync_core.py` already refuses to invent a root cause from
pipeline state (`candidates_from_evidence`'s own docstring explains why two
earlier attempts at that failed) -- that refusal is correct and this module
does not relitigate it.  What was actually missing is the step BEFORE
candidate-authoring: a durable record that something was observed at all, so
an unattributed observation cannot just evaporate when no one writes a
candidate for it that day.

Two calls, deliberately separate, line-agnostic (parameterised by
``runtime_root`` the same way ``knowledge_sync_core.sync`` is):

  record_event(...)      -- append an OBJECTIVE fact: episode, unit(s), stage,
                             symptom, evidence (sha / gate / detector).  Always
                             written with attribution.status=UNATTRIBUTED.  No
                             argument here can set a root cause -- the function
                             signature has no such parameter.
  attribute_event(...)    -- a SEPARATE, explicit call a human or reviewing
                             agent makes after looking at the evidence, giving
                             a root_cause in its own words and a confidence.
                             mark_inconclusive(...) is the honest alternative
                             when the review happened and the cause is still
                             unclear -- distinct from "not reviewed yet".

Storage: one JSONL file per line (``<runtime_root>/reports/KNOWLEDGE_EVENTS.jsonl``
by default), append-only for new events; attribution updates are a read-all /
rewrite-all with the previous attribution kept in ``attribution_history`` so a
correction is visible, not silently overwritten.

This module never calls a provider, never touches a paid task, transaction or
budget ledger file, and never writes into ``configs/ENGINEERING_KNOWLEDGE_V1.json``
or the markdown knowledge base -- that remains ``knowledge_sync_core.sync``'s job,
fed by a candidate a human/agent authors from one or more ATTRIBUTED events here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.knowledge_event.v1"
DEFAULT_RELPATH = "reports/KNOWLEDGE_EVENTS.jsonl"

STATUS_UNATTRIBUTED = "UNATTRIBUTED"
STATUS_ATTRIBUTED = "ATTRIBUTED"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"
ATTRIBUTION_STATUSES = (STATUS_UNATTRIBUTED, STATUS_ATTRIBUTED, STATUS_INCONCLUSIVE)
CONFIDENCES = ("LOW", "MEDIUM", "HIGH")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(text: Any, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def events_path(runtime_root: Path, relpath: str = DEFAULT_RELPATH) -> Path:
    return Path(runtime_root) / relpath


def _read_all(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"KNOWLEDGE_EVENT_LOG_CORRUPT:{path}:{line_no}:{exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"KNOWLEDGE_EVENT_LOG_CORRUPT:{path}:{line_no}:not_an_object")
        rows.append(row)
    return rows


def _write_all(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n" for row in rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _event_id(episode: str, stage: str, ordinal: int, fingerprint: str) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]
    return f"EVT-{episode}-{stage}-{ordinal:04d}-{digest}"


def record_event(
    runtime_root: Path,
    *,
    episode: str,
    line: str,
    stage: str,
    symptom: str,
    evidence: dict[str, Any],
    detected_by: str,
    unit_ids: list[str] | None = None,
    relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """Append one objective observation.  Returns the written row.

    ``symptom`` and ``evidence`` must be concrete (a gate name, a detector
    code, a measured value, a media/prompt sha) -- this is the fact a
    reviewer later attributes, not yet an opinion about why it happened.
    There is deliberately no ``root_cause`` parameter here: a cause can only
    be set by :func:`attribute_event`, as its own explicit call.
    """
    episode = str(episode or "").strip()
    stage = str(stage or "").strip()
    symptom_clean = _clean(symptom)
    if not episode:
        raise ValueError("EVENT_EPISODE_REQUIRED")
    if not stage:
        raise ValueError("EVENT_STAGE_REQUIRED")
    if not symptom_clean:
        raise ValueError("EVENT_SYMPTOM_REQUIRED")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("EVENT_EVIDENCE_REQUIRED_NONEMPTY_OBJECT")
    if not str(detected_by or "").strip():
        raise ValueError("EVENT_DETECTED_BY_REQUIRED")

    path = events_path(Path(runtime_root), relpath)
    rows = _read_all(path)
    ordinal = sum(1 for row in rows if row.get("episode") == episode) + 1
    fingerprint = json.dumps(
        {"episode": episode, "stage": stage, "symptom": symptom_clean, "evidence": evidence,
         "unit_ids": sorted(unit_ids or [])},
        ensure_ascii=False, sort_keys=True)
    row = {
        "schema": SCHEMA,
        "event_id": _event_id(episode, stage, ordinal, fingerprint),
        "recorded_at": _now(),
        "line": str(line or "").strip() or "UNKNOWN",
        "episode": episode,
        "stage": stage,
        "unit_ids": sorted(set(str(u) for u in (unit_ids or []))),
        "symptom": symptom_clean,
        "evidence": evidence,
        "detected_by": str(detected_by).strip(),
        "attribution": {"status": STATUS_UNATTRIBUTED},
        "attribution_history": [],
    }
    rows.append(row)
    _write_all(path, rows)
    return row


def _update_attribution(
    runtime_root: Path, event_id: str, new_attribution: dict[str, Any], *, relpath: str,
) -> dict[str, Any]:
    path = events_path(Path(runtime_root), relpath)
    rows = _read_all(path)
    for row in rows:
        if row.get("event_id") != event_id:
            continue
        previous = row.get("attribution") or {"status": STATUS_UNATTRIBUTED}
        row.setdefault("attribution_history", [])
        row["attribution_history"].append(previous)
        row["attribution"] = new_attribution
        _write_all(path, rows)
        return row
    raise ValueError(f"EVENT_NOT_FOUND:{event_id}")


def attribute_event(
    runtime_root: Path,
    event_id: str,
    *,
    root_cause: str,
    attributed_by: str,
    candidate_rule_id: str | None = None,
    confidence: str = "MEDIUM",
    relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """Record a reviewer's judgement of WHY the event happened.

    ``root_cause`` is the reviewer's own abstraction (same bar as a knowledge
    candidate's ``rule`` field), never derived here from ``symptom`` text --
    this function does no pattern matching of its own.  Raises if the cause
    is empty: an attribution with nothing in it is a no-op dressed up as
    progress.
    """
    root_cause_clean = _clean(root_cause, limit=2000)
    if not root_cause_clean:
        raise ValueError("ATTRIBUTION_ROOT_CAUSE_REQUIRED")
    if confidence not in CONFIDENCES:
        raise ValueError(f"ATTRIBUTION_CONFIDENCE_INVALID:{confidence}")
    if not str(attributed_by or "").strip():
        raise ValueError("ATTRIBUTION_ATTRIBUTED_BY_REQUIRED")
    attribution = {
        "status": STATUS_ATTRIBUTED,
        "root_cause": root_cause_clean,
        "attributed_by": str(attributed_by).strip(),
        "attributed_at": _now(),
        "confidence": confidence,
    }
    if candidate_rule_id:
        attribution["candidate_rule_id"] = str(candidate_rule_id).strip()
    return _update_attribution(runtime_root, event_id, attribution, relpath=relpath)


def mark_inconclusive(
    runtime_root: Path,
    event_id: str,
    *,
    reason: str,
    attributed_by: str,
    relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """The honest terminal state when a review happened but the cause stays unclear.

    Distinct from the default UNATTRIBUTED (not reviewed yet): this says
    someone looked and could not pin down a cause, with ``reason`` saying
    what was ruled out or why the evidence was insufficient.
    """
    reason_clean = _clean(reason, limit=2000)
    if not reason_clean:
        raise ValueError("INCONCLUSIVE_REASON_REQUIRED")
    if not str(attributed_by or "").strip():
        raise ValueError("ATTRIBUTION_ATTRIBUTED_BY_REQUIRED")
    attribution = {
        "status": STATUS_INCONCLUSIVE,
        "reason": reason_clean,
        "attributed_by": str(attributed_by).strip(),
        "attributed_at": _now(),
    }
    return _update_attribution(runtime_root, event_id, attribution, relpath=relpath)


def events(
    runtime_root: Path, *, episode: str | None = None, status: str | None = None,
    relpath: str = DEFAULT_RELPATH,
) -> list[dict[str, Any]]:
    rows = _read_all(events_path(Path(runtime_root), relpath))
    if episode is not None:
        rows = [r for r in rows if r.get("episode") == episode]
    if status is not None:
        rows = [r for r in rows if (r.get("attribution") or {}).get("status") == status]
    return rows


def unattributed(runtime_root: Path, *, episode: str | None = None,
                 relpath: str = DEFAULT_RELPATH) -> list[dict[str, Any]]:
    return events(runtime_root, episode=episode, status=STATUS_UNATTRIBUTED, relpath=relpath)


def main() -> int:  # pragma: no cover -- thin CLI for manual/agent use
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--runtime-root", type=Path, required=True)
    rec.add_argument("--episode", required=True)
    rec.add_argument("--line", required=True)
    rec.add_argument("--stage", required=True)
    rec.add_argument("--symptom", required=True)
    rec.add_argument("--evidence", required=True, help="JSON object")
    rec.add_argument("--detected-by", required=True)
    rec.add_argument("--unit", action="append", default=[], dest="unit_ids")

    attr = sub.add_parser("attribute")
    attr.add_argument("--runtime-root", type=Path, required=True)
    attr.add_argument("--event-id", required=True)
    attr.add_argument("--root-cause", required=True)
    attr.add_argument("--attributed-by", required=True)
    attr.add_argument("--candidate-rule-id")
    attr.add_argument("--confidence", default="MEDIUM", choices=CONFIDENCES)

    inc = sub.add_parser("inconclusive")
    inc.add_argument("--runtime-root", type=Path, required=True)
    inc.add_argument("--event-id", required=True)
    inc.add_argument("--reason", required=True)
    inc.add_argument("--attributed-by", required=True)

    lst = sub.add_parser("list")
    lst.add_argument("--runtime-root", type=Path, required=True)
    lst.add_argument("--episode")
    lst.add_argument("--status", choices=ATTRIBUTION_STATUSES)

    args = parser.parse_args()
    try:
        if args.cmd == "record":
            row = record_event(args.runtime_root, episode=args.episode, line=args.line,
                               stage=args.stage, symptom=args.symptom,
                               evidence=json.loads(args.evidence), detected_by=args.detected_by,
                               unit_ids=args.unit_ids)
        elif args.cmd == "attribute":
            row = attribute_event(args.runtime_root, args.event_id, root_cause=args.root_cause,
                                  attributed_by=args.attributed_by,
                                  candidate_rule_id=args.candidate_rule_id, confidence=args.confidence)
        elif args.cmd == "inconclusive":
            row = mark_inconclusive(args.runtime_root, args.event_id, reason=args.reason,
                                    attributed_by=args.attributed_by)
        else:
            row = {"rows": events(args.runtime_root, episode=args.episode, status=args.status)}
    except ValueError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
