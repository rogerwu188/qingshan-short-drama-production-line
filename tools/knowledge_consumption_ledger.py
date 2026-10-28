#!/usr/bin/env python3
"""knowledge_consumption_ledger — durable evidence that a registry rule was
APPLIED to a real compile, and (separately) that its effect was VERIFIED.

Codex knowledge-loop audit 2026-10-27, gap 3: "READ" (``line_upgrade_gate``'s
briefing) currently means only that the briefing FILE exists -- a corrupted
or stale briefing still reports status=READ (verified directly against
``line_upgrade_gate.verify_briefing``, which checks file existence and
nothing else). "EXPORTED" (the briefing was written), "APPLIED" (a rule's
clause actually fired on a real shot) and "VERIFIED" (that firing's effect
was checked against the content a provider would actually receive) are three
different claims and must not collapse into one.

This module owns the APPLIED and VERIFIED claims.  EXPORTED is already owned
by ``line_upgrade_gate.knowledge_briefing`` / ``verify_briefing`` and is not
duplicated here (constraint: reuse the existing mechanism, don't build a
parallel one) -- :func:`status_for_rule` reads the existing briefing file
for that claim and reads this module's own ledger for the other two.

Two record kinds, one append-only JSONL ledger per line
(``<runtime_root>/reports/KNOWLEDGE_CONSUMPTION.jsonl``, mirroring
``knowledge_event_log``'s storage convention):

  record_application(...)  -- mechanical, safe to call automatically: a
                               builder already computes which rule tags fired
                               on which shots (``nalu_prompt_rules.apply``'s
                               own ``applied`` return value, reshaped by
                               ``nalu_prompt_rules.applied_summary``).
                               Recording that a trigger fired is not a
                               judgement call the way attributing a root
                               cause is, so -- unlike knowledge_event_log --
                               this is not gated behind a human/agent review
                               step.
  record_verification(...) -- a regression test calls this, after it has
                               actually asserted the rule's effect survives
                               into the real compiled/submitted text, never
                               before.  "a regression file is referenced in
                               the registry row" is not evidence by itself;
                               a passing assertion that ran and checked real
                               compiler output is.

Only ``KNOWLEDGE:<id>`` tags (and any tag a caller explicitly maps via
``tag_to_rule_id``) become registry-rule evidence; this module does not guess
which of ``nalu_prompt_rules``'s hardcoded tags (``SOLO_FACE``, ``NO_BLACK``,
...) correspond to a registry id.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.knowledge_consumption.v1"
DEFAULT_RELPATH = "reports/KNOWLEDGE_CONSUMPTION.jsonl"
KIND_APPLIED = "APPLIED"
KIND_VERIFIED = "VERIFIED"
KINDS = (KIND_APPLIED, KIND_VERIFIED)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean(text: Any, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def ledger_path(runtime_root: Path, relpath: str = DEFAULT_RELPATH) -> Path:
    return Path(runtime_root) / relpath


def _append(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


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
            raise ValueError(f"KNOWLEDGE_CONSUMPTION_LEDGER_CORRUPT:{path}:{line_no}:{exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"KNOWLEDGE_CONSUMPTION_LEDGER_CORRUPT:{path}:{line_no}:not_an_object")
        rows.append(row)
    return rows


def record_application(
    runtime_root: Path,
    *,
    episode: str,
    line: str,
    stage: str,
    npr_applied: dict[str, list[str]],
    source: str = "nalu_prompt_rules.apply",
    tag_to_rule_id: dict[str, str] | None = None,
    relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """Record one real compile's rule firings.  Mechanical, not a judgement call.

    ``npr_applied`` is the ``{shot_id: [tag, ...]}`` a builder already collects
    from ``nalu_prompt_rules.apply``.  Only tags recognised as a registry rule
    id (``KNOWLEDGE:<id>``, or a bare tag present in ``tag_to_rule_id``)
    produce evidence rows; everything else is kept in ``raw_tags`` for
    completeness but is not claimed as registry-rule evidence.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"))
    import nalu_prompt_rules as _npr  # noqa: E402  -- shared helper, see module docstring

    episode = str(episode or "").strip()
    stage = str(stage or "").strip()
    if not episode:
        raise ValueError("CONSUMPTION_EPISODE_REQUIRED")
    if not stage:
        raise ValueError("CONSUMPTION_STAGE_REQUIRED")
    if not isinstance(npr_applied, dict):
        raise ValueError("CONSUMPTION_NPR_APPLIED_MUST_BE_A_DICT")

    summary = _npr.applied_summary(npr_applied)
    tag_map = dict(tag_to_rule_id or {})
    rule_ids: dict[str, list[str]] = {}
    for tag, shot_ids in summary["shots_by_tag"].items():
        rule_id = tag.split(":", 1)[1] if tag.startswith("KNOWLEDGE:") else tag_map.get(tag)
        if rule_id:
            rule_ids.setdefault(rule_id, [])
            rule_ids[rule_id] = sorted(set(rule_ids[rule_id]) | set(shot_ids))

    row = {
        "schema": SCHEMA,
        "kind": KIND_APPLIED,
        "recorded_at": _now(),
        "line": str(line or "").strip() or "UNKNOWN",
        "episode": episode,
        "stage": stage,
        "source": str(source),
        "shot_count": summary["shot_count"],
        "rule_ids_applied": sorted(rule_ids),
        "shots_by_rule_id": rule_ids,
        "raw_tags_by_shot": summary["tags_by_shot"],
    }
    return _append(ledger_path(Path(runtime_root), relpath), row)


def record_verification(
    runtime_root: Path,
    *,
    rule_id: str,
    test_name: str,
    assertion: str,
    checked_output: str,
    verified_by: str = "regression_test",
    episode: str | None = None,
    relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """A regression test calls this AFTER it has actually asserted the rule's
    effect on real compiled/submitted content -- never speculatively, never
    for a test that merely exists.

    ``assertion`` is a short description of what was checked (e.g. "SOLO_FACE
    clause present in final H3 prompt text for a historical half-face-edge
    fixture"); ``checked_output`` names what was inspected (a function's
    return value, a compiled prompt string, a gate verdict) so the evidence
    is falsifiable, not just a claim.
    """
    rule_id = str(rule_id or "").strip()
    if not rule_id:
        raise ValueError("VERIFICATION_RULE_ID_REQUIRED")
    if not str(test_name or "").strip():
        raise ValueError("VERIFICATION_TEST_NAME_REQUIRED")
    assertion_clean = _clean(assertion)
    if not assertion_clean:
        raise ValueError("VERIFICATION_ASSERTION_REQUIRED")
    if not str(checked_output or "").strip():
        raise ValueError("VERIFICATION_CHECKED_OUTPUT_REQUIRED")

    row = {
        "schema": SCHEMA,
        "kind": KIND_VERIFIED,
        "recorded_at": _now(),
        "rule_id": rule_id,
        "test_name": str(test_name).strip(),
        "assertion": assertion_clean,
        "checked_output": str(checked_output).strip(),
        "verified_by": str(verified_by).strip() or "regression_test",
        "episode": str(episode).strip() if episode else None,
    }
    return _append(ledger_path(Path(runtime_root), relpath), row)


def applications(runtime_root: Path, *, episode: str | None = None,
                 relpath: str = DEFAULT_RELPATH) -> list[dict[str, Any]]:
    rows = [r for r in _read_all(ledger_path(Path(runtime_root), relpath)) if r.get("kind") == KIND_APPLIED]
    if episode is not None:
        rows = [r for r in rows if r.get("episode") == episode]
    return rows


def verifications(runtime_root: Path, *, rule_id: str | None = None,
                  relpath: str = DEFAULT_RELPATH) -> list[dict[str, Any]]:
    rows = [r for r in _read_all(ledger_path(Path(runtime_root), relpath)) if r.get("kind") == KIND_VERIFIED]
    if rule_id is not None:
        rows = [r for r in rows if r.get("rule_id") == rule_id]
    return rows


def applied_rule_ids(runtime_root: Path, *, episode: str | None = None,
                     relpath: str = DEFAULT_RELPATH) -> set[str]:
    out: set[str] = set()
    for row in applications(runtime_root, episode=episode, relpath=relpath):
        out.update(row.get("rule_ids_applied") or [])
    return out


def status_for_rule(
    engine_root: Path, runtime_root: Path, episode: str, rule_id: str,
    *, relpath: str = DEFAULT_RELPATH,
) -> dict[str, Any]:
    """Compose the three-way status the audit asked for: a rule's id must not
    be reported as "applied" just because it was exported, and not reported
    as "verified" just because it was applied.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(engine_root) / "tools"))
    import line_upgrade_gate as _lug  # noqa: E402

    briefing_path = _lug._reports(Path(runtime_root)) / f"{episode}_KNOWLEDGE_BRIEFING.json"
    exported = False
    if briefing_path.is_file():
        try:
            brief = json.loads(briefing_path.read_text(encoding="utf-8"))
            exported = rule_id in (brief.get("rule_ids") or [])
        except (OSError, ValueError):
            exported = False

    applied_evidence = [
        {"episode": row["episode"], "stage": row["stage"], "recorded_at": row["recorded_at"],
         "shot_ids": row["shots_by_rule_id"].get(rule_id, [])}
        for row in applications(runtime_root, episode=episode, relpath=relpath)
        if rule_id in (row.get("rule_ids_applied") or [])
    ]
    verified_evidence = [
        {"test_name": row["test_name"], "assertion": row["assertion"], "recorded_at": row["recorded_at"]}
        for row in verifications(runtime_root, rule_id=rule_id, relpath=relpath)
    ]
    return {
        "rule_id": rule_id,
        "episode": episode,
        "exported": exported,
        "applied": bool(applied_evidence),
        "applied_evidence": applied_evidence,
        "verified": bool(verified_evidence),
        "verified_evidence": verified_evidence,
    }


def main() -> int:  # pragma: no cover -- thin CLI for manual/agent use
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status")
    status.add_argument("--engine-root", type=Path, required=True)
    status.add_argument("--runtime-root", type=Path, required=True)
    status.add_argument("--episode", required=True)
    status.add_argument("--rule-id", required=True)

    app = sub.add_parser("record-application")
    app.add_argument("--runtime-root", type=Path, required=True)
    app.add_argument("--episode", required=True)
    app.add_argument("--line", required=True)
    app.add_argument("--stage", required=True)
    app.add_argument("--npr-applied", required=True, help="JSON object {shot_id: [tag, ...]}")
    app.add_argument("--source", default="nalu_prompt_rules.apply")

    ver = sub.add_parser("record-verification")
    ver.add_argument("--runtime-root", type=Path, required=True)
    ver.add_argument("--rule-id", required=True)
    ver.add_argument("--test-name", required=True)
    ver.add_argument("--assertion", required=True)
    ver.add_argument("--checked-output", required=True)
    ver.add_argument("--verified-by", default="regression_test")
    ver.add_argument("--episode")

    args = parser.parse_args()
    try:
        if args.cmd == "status":
            result = status_for_rule(args.engine_root, args.runtime_root, args.episode, args.rule_id)
        elif args.cmd == "record-application":
            result = record_application(args.runtime_root, episode=args.episode, line=args.line,
                                        stage=args.stage, npr_applied=json.loads(args.npr_applied),
                                        source=args.source)
        else:
            result = record_verification(args.runtime_root, rule_id=args.rule_id, test_name=args.test_name,
                                         assertion=args.assertion, checked_output=args.checked_output,
                                         verified_by=args.verified_by, episode=args.episode)
    except ValueError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
