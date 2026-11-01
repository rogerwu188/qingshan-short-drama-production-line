#!/usr/bin/env python3
"""Arc plan + hook/payoff ledger: the cross-episode writing sheet, validated.

Why this exists
---------------
The nalu line has no artefact that decides where an episode ENDS.  Each episode
was written one-chapter-one-episode by habit (P0_INVENTORY.md §2: no code ever
decided or refused a cross-chapter episode), and the only cross-episode
continuity was the previous episode's last shot's ``completion_state``.  Nothing
recorded which question an episode leaves open or when it is answered, so the
E11-E13 audit found hooks opened and never paid off ("种子扔进火坑"埋了没收,
见 PILOT_RESULT.md 「两版共同的漏洞」).

This module is the sheet the writer fills BEFORE an episode is written, and the
validator that refuses an arc that cannot be traced to source or that silently
drops a promise.

What it validates (and what it deliberately does not)
-----------------------------------------------------
* Every episode of the arc declares ``source_ref`` (which chapter paragraphs it
  really stands on), ``chosen_events``, ``delivered_experience``,
  ``end_question`` and ``payoff_plan``.  A MISSING key fails; a value of ``null``
  is allowed and is recorded as unknown (the line owner's 2026-11-01 decision:
  「Unknown values allowed as null, but a missing required field fails」).
* Every hook row has ``id``, a ``status`` in {OPEN, ADVANCED, PAID_OFF,
  DEFERRED} and a non-empty ``progress``; a PAID_OFF/ADVANCED hook also states
  its ``payoff``.  A DEFERRED hook states a ``deferred_reason`` and a
  ``planned_payoff_episode``.
* A hook still OPEN when the arc ends is allowed — but it must be listed in
  ``open_hooks_at_arc_end``.  An unlisted OPEN hook is the failure this exists
  to catch.
* Scene cards (want / obstacle / action / change / why_keep) and
  duplicated-function proposals are validated per row when present.

There are NO quotas here: no fixed hook count, no "a fight every N episodes",
no scores.  ``NO_DELIVERED_PAYOFF`` (an episode where nothing the plan promised
is delivered) and a consecutive run of such episodes are DIAGNOSTICS: the writer
must answer them (``no_payoff_answer``), and a quiet emotional episode is a valid
answer.  ``--strict-diagnostics`` turns an unanswered one into a failure for a
caller that wants that; it is off by default.

Schema: ``configs/schemas/writer_arc_ledger_v1.schema.json`` (the normative
shape).  Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.writer_arc_ledger.v1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "configs/schemas/writer_arc_ledger_v1.schema.json"
TOOL_ID = "writer_arc_ledger.v1"
POLICY_ID = "WRITER_CAPABILITY_V1"

#: Line owner 2026-11-01: 「Arc planning window of 3-6 episodes before writing any
#: episode」.  A window bound, not a content quota — it says how far the sheet must
#: look ahead, nothing about what happens inside.
ARC_WINDOW_MIN = 3
ARC_WINDOW_MAX = 6

EPISODE_REQUIRED = ("source_ref", "chosen_events", "delivered_experience",
                    "end_question", "payoff_plan", "scene_cards")
EPISODE_OPTIONAL = ("no_payoff_answer", "function_duplicates")

#: The line owner 2026-11-01: id, status, and non-empty progress/payoff.  ``kind`` is
#: part of the pairing vocabulary but may be null (unknown is allowed as null).
HOOK_REQUIRED = ("id", "status", "kind", "progress", "payoff")
HOOK_STATUSES = ("OPEN", "ADVANCED", "PAID_OFF", "DEFERRED")
#: Roger's pairing vocabulary (2026-11-01 item 6).  A hook is one of these five
#: KINDS of promise; counting question marks is explicitly not the measure.
HOOK_KINDS = ("danger", "choice", "relationship_change", "discovery", "open_question")

SCENE_CARD_FIELDS = ("want", "obstacle", "action", "change", "why_keep")
DUPLICATE_KINDS = ("character", "scene", "line")
DUPLICATE_PROPOSALS = ("MERGE", "CUT", "KEEP")

EPISODE_RE = re.compile(r"^E\d{2,3}$")

GUIDANCE = (
    "These diagnostics are questions, not quotas.  Answer each flagged episode in its "
    "no_payoff_answer field: why this stretch is deliberately quiet, or what it delivers "
    "that the payoff_plan does not name.  A quiet emotional episode is a valid answer.  "
    "Do not add fights, reversals or a twist to clear a flag."
)


# --------------------------------------------------------------------------- helpers


def _text(value: Any) -> str:
    return str(value or "").strip()


def _present(row: dict[str, Any], key: str) -> bool:
    return key in row


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def load(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- validation


def validate(ledger: dict[str, Any]) -> dict[str, Any]:
    """Return ``{status, failures, warnings, diagnostics, measurements}``.

    ``failures`` are the shape/traceability defects.  ``diagnostics`` are the
    "you must answer this" items and never fail the report unless the caller
    asks for ``strict_diagnostics`` (a separate, explicit switch).
    """
    failures: list[str] = []
    warnings: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    nulls: list[str] = []

    if not isinstance(ledger, dict):
        return {
            "schema": "qingshan.writer_arc_ledger_report.v1",
            "tool": TOOL_ID, "status": "FAIL", "failures": ["LEDGER_NOT_AN_OBJECT"],
            "warnings": [], "diagnostics": [], "measurements": {},
        }
    if ledger.get("schema") != SCHEMA:
        failures.append(f"SCHEMA_INVALID:{ledger.get('schema')!r}")
    if _text(ledger.get("policy")) and _text(ledger.get("policy")) != POLICY_ID:
        warnings.append(f"POLICY_NOT_THIS_CAPABILITY:{ledger.get('policy')}")
    if not _text(ledger.get("arc_id")):
        failures.append("ARC_ID_MISSING")

    window_raw = ledger.get("episode_window")
    window: list[str] = []
    if not isinstance(window_raw, list) or not window_raw:
        failures.append("EPISODE_WINDOW_MISSING")
    else:
        window = [_text(value) for value in window_raw]
        for value in window:
            if not EPISODE_RE.match(value):
                failures.append(f"EPISODE_WINDOW_ID_INVALID:{value!r}")
        if len(set(window)) != len(window):
            failures.append("EPISODE_WINDOW_DUPLICATE")
        if not ARC_WINDOW_MIN <= len(window) <= ARC_WINDOW_MAX:
            failures.append(
                f"EPISODE_WINDOW_LENGTH_OUT_OF_RANGE:{len(window)}:"
                f"{ARC_WINDOW_MIN}-{ARC_WINDOW_MAX}")

    episodes = _rows(ledger.get("episodes"))
    if not isinstance(ledger.get("episodes"), list) or not ledger.get("episodes"):
        failures.append("EPISODES_MISSING")
    episode_rows: dict[str, dict[str, Any]] = {}
    listed: list[str] = []
    for index, row in enumerate(episodes, 1):
        episode = _text(row.get("episode"))
        if not EPISODE_RE.match(episode):
            failures.append(f"EPISODE_ID_INVALID:{episode or index}")
            continue
        if episode in episode_rows:
            failures.append(f"EPISODE_DUPLICATE:{episode}")
            continue
        episode_rows[episode] = row
        listed.append(episode)
    if window and listed and listed != [value for value in window if value in episode_rows]:
        failures.append("EPISODE_ORDER_DIFFERS_FROM_WINDOW")
    if window and set(listed) != set(window):
        missing = sorted(set(window) - set(listed))
        extra = sorted(set(listed) - set(window))
        if missing:
            failures.append("EPISODE_WINDOW_MISSING_ROWS:" + ",".join(missing))
        if extra:
            failures.append("EPISODE_NOT_IN_WINDOW:" + ",".join(extra))

    for episode in window if window else listed:
        row = episode_rows.get(episode)
        if row is None:
            continue
        for key in EPISODE_REQUIRED:
            if not _present(row, key):
                failures.append(f"FIELD_MISSING:{episode}:{key}")
            elif row.get(key) is None:
                nulls.append(f"{episode}:{key}")
                warnings.append(f"FIELD_NULL:{episode}:{key}")
        _validate_episode_row(episode, row, failures, warnings)
        _validate_scene_cards(episode, row, failures)
        _validate_duplicates(episode, row, failures)

    _validate_hooks(ledger, window or listed, failures, warnings)
    _validate_open_hooks_at_arc_end(ledger, failures)
    _validate_payoff_plan_links(episode_rows, _rows(ledger.get("hooks")), failures)

    diagnostics = _payoff_diagnostics((window or listed), episode_rows)

    measurements = {
        "arc_id": ledger.get("arc_id"),
        "episode_count": len(listed),
        "hook_count": len(_rows(ledger.get("hooks"))),
        "hooks_by_status": _hooks_by_status(_rows(ledger.get("hooks"))),
        "null_fields": nulls,
        "unanswered_diagnostics": [d["code"] + ":" + str(d.get("episode"))
                                   for d in diagnostics if not d["answered"]],
    }
    status = "FAIL" if failures else "PASS"
    return {
        "schema": "qingshan.writer_arc_ledger_report.v1",
        "tool": TOOL_ID,
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "guidance": GUIDANCE,
        "measurements": measurements,
    }


def _validate_episode_row(episode: str, row: dict[str, Any], failures: list[str],
                          warnings: list[str]) -> None:
    source_ref = row.get("source_ref")
    if source_ref is not None:
        refs = source_ref if isinstance(source_ref, list) else [source_ref]
        if not refs or any(not _text(ref) for ref in refs):
            failures.append(f"SOURCE_REF_EMPTY:{episode}")
        for ref in refs:
            if _text(ref) and not re.match(r"^ch\d{2,4}(:[^:\s]+)?$", _text(ref)):
                warnings.append(f"SOURCE_REF_NOT_CHAPTER_PARAGRAPH:{episode}:{_text(ref)}")
    chosen = row.get("chosen_events")
    if chosen is not None:
        if not isinstance(chosen, list):
            failures.append(f"CHOSEN_EVENTS_NOT_A_LIST:{episode}")
        else:
            for index, event in enumerate(chosen, 1):
                if isinstance(event, dict):
                    if not _text(event.get("event_id")):
                        failures.append(f"CHOSEN_EVENT_ID_MISSING:{episode}:{index}")
                elif not _text(event):
                    failures.append(f"CHOSEN_EVENT_EMPTY:{episode}:{index}")
    for key in ("delivered_experience", "end_question"):
        value = row.get(key)
        if value is not None and not _text(value):
            warnings.append(f"FIELD_EMPTY_STRING:{episode}:{key}")
    answer = row.get("no_payoff_answer")
    if answer is not None and not _text(answer):
        warnings.append(f"FIELD_EMPTY_STRING:{episode}:no_payoff_answer")


def _validate_scene_cards(episode: str, row: dict[str, Any], failures: list[str]) -> None:
    cards = row.get("scene_cards")
    if cards is None or cards == []:
        return
    if not isinstance(cards, list):
        failures.append(f"SCENE_CARDS_NOT_A_LIST:{episode}")
        return
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            failures.append(f"SCENE_CARD_NOT_AN_OBJECT:{episode}:{index}")
            continue
        scene_id = _text(card.get("scene_id")) or str(index)
        for field in SCENE_CARD_FIELDS:
            if field not in card:
                failures.append(f"SCENE_CARD_FIELD_MISSING:{episode}:{scene_id}:{field}")
            elif not _text(card.get(field)):
                failures.append(f"SCENE_CARD_FIELD_EMPTY:{episode}:{scene_id}:{field}")


def _validate_duplicates(episode: str, row: dict[str, Any], failures: list[str]) -> None:
    rows = row.get("function_duplicates")
    if rows is None:
        return
    if not isinstance(rows, list):
        failures.append(f"FUNCTION_DUPLICATES_NOT_A_LIST:{episode}")
        return
    for index, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            failures.append(f"FUNCTION_DUPLICATE_NOT_AN_OBJECT:{episode}:{index}")
            continue
        if _text(item.get("kind")) not in DUPLICATE_KINDS:
            failures.append(f"FUNCTION_DUPLICATE_KIND_INVALID:{episode}:{index}:{item.get('kind')}")
        items = item.get("items")
        if not isinstance(items, list) or not [value for value in items if _text(value)]:
            failures.append(f"FUNCTION_DUPLICATE_ITEMS_EMPTY:{episode}:{index}")
        if _text(item.get("proposal")) not in DUPLICATE_PROPOSALS:
            failures.append(f"FUNCTION_DUPLICATE_PROPOSAL_INVALID:{episode}:{index}:{item.get('proposal')}")
        if not _text(item.get("reason")):
            failures.append(f"FUNCTION_DUPLICATE_REASON_MISSING:{episode}:{index}")


def _validate_hooks(ledger: dict[str, Any], window: list[str], failures: list[str],
                    warnings: list[str]) -> None:
    hooks = ledger.get("hooks")
    if not isinstance(hooks, list):
        failures.append("HOOKS_NOT_A_LIST")
        return
    seen: set[str] = set()
    for index, hook in enumerate(hooks, 1):
        if not isinstance(hook, dict):
            failures.append(f"HOOK_NOT_AN_OBJECT:{index}")
            continue
        hook_id = _text(hook.get("id"))
        if not hook_id:
            failures.append(f"HOOK_ID_MISSING:{index}")
        elif hook_id in seen:
            failures.append(f"HOOK_ID_DUPLICATE:{hook_id}")
        else:
            seen.add(hook_id)
        label = hook_id or str(index)
        for key in HOOK_REQUIRED:
            if key not in hook:
                failures.append(f"HOOK_FIELD_MISSING:{label}:{key}")
        status = _text(hook.get("status"))
        if status not in HOOK_STATUSES:
            failures.append(f"HOOK_STATUS_INVALID:{label}:{hook.get('status')}")
        if not _text(hook.get("progress")):
            failures.append(f"HOOK_PROGRESS_EMPTY:{label}")
        kind = hook.get("kind")
        if kind is not None and _text(kind) not in HOOK_KINDS:
            failures.append(f"HOOK_KIND_INVALID:{label}:{kind}")
        payoff = _text(hook.get("payoff"))
        if status in {"PAID_OFF", "ADVANCED"} and not payoff:
            failures.append(f"HOOK_PAYOFF_EMPTY:{label}:{status}")
        if status == "DEFERRED":
            if not _text(hook.get("deferred_reason")):
                failures.append(f"HOOK_DEFERRED_REASON_MISSING:{label}")
            if not _text(hook.get("planned_payoff_episode")):
                failures.append(f"HOOK_DEFERRED_PLANNED_EPISODE_MISSING:{label}")
        if status == "OPEN" and not payoff and not _text(hook.get("planned_payoff_episode")):
            warnings.append(f"HOOK_OPEN_WITHOUT_PLAN:{label}")
        opened_in = hook.get("opened_in")
        if opened_in is not None and window and _text(opened_in) not in window:
            warnings.append(f"HOOK_OPENED_OUTSIDE_THIS_ARC:{label}:{_text(opened_in)}")
        paid_in = hook.get("paid_off_in")
        if _text(paid_in) and window and _text(paid_in) not in window:
            warnings.append(f"HOOK_PAID_OFF_OUTSIDE_THIS_ARC:{label}:{_text(paid_in)}")


def _validate_open_hooks_at_arc_end(ledger: dict[str, Any], failures: list[str]) -> None:
    hooks = _rows(ledger.get("hooks"))
    open_ids = {_text(row.get("id")) for row in hooks
                if _text(row.get("status")) == "OPEN" and _text(row.get("id"))}
    declared = ledger.get("open_hooks_at_arc_end")
    if declared is None:
        if open_ids:
            failures.append("OPEN_HOOKS_NOT_LISTED_AT_ARC_END:" + ",".join(sorted(open_ids)))
        return
    if not isinstance(declared, list):
        failures.append("OPEN_HOOKS_AT_ARC_END_NOT_A_LIST")
        return
    declared_ids = {_text(value) for value in declared if _text(value)}
    for hook_id in sorted(open_ids - declared_ids):
        failures.append(f"OPEN_HOOK_NOT_LISTED_AT_ARC_END:{hook_id}")
    for hook_id in sorted(declared_ids - open_ids):
        failures.append(f"LISTED_HOOK_IS_NOT_OPEN:{hook_id}")


def _validate_payoff_plan_links(episode_rows: dict[str, dict[str, Any]],
                                hooks: list[dict[str, Any]], failures: list[str]) -> None:
    hook_ids = {_text(row.get("id")) for row in hooks}
    for episode, row in episode_rows.items():
        plan = row.get("payoff_plan")
        if plan is None:
            continue
        if not isinstance(plan, list):
            failures.append(f"PAYOFF_PLAN_NOT_A_LIST:{episode}")
            continue
        for index, item in enumerate(plan, 1):
            if not isinstance(item, dict):
                failures.append(f"PAYOFF_ROW_NOT_AN_OBJECT:{episode}:{index}")
                continue
            payoff_id = _text(item.get("payoff_id"))
            if not payoff_id:
                failures.append(f"PAYOFF_ID_MISSING:{episode}:{index}")
            if not _text(item.get("settles")) and not _text(item.get("what")):
                failures.append(f"PAYOFF_TARGET_MISSING:{episode}:{payoff_id or index}")
            settles = _text(item.get("settles"))
            if settles and settles.startswith("HOOK-") and hook_ids and settles not in hook_ids:
                failures.append(f"PAYOFF_REFERENCES_UNKNOWN_HOOK:{episode}:{settles}")


def _hooks_by_status(hooks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hook in hooks:
        status = _text(hook.get("status")) or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _payoff_diagnostics(window: list[str], episode_rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag episodes that deliver nothing the plan promised, and runs of them."""
    delivered: dict[str, list[str]] = {}
    for episode in window:
        row = episode_rows.get(episode) or {}
        rows = row.get("payoff_plan")
        hits = [item for item in (rows if isinstance(rows, list) else [])
                if isinstance(item, dict) and _text(item.get("delivered_in")) == episode]
        delivered[episode] = [str(item.get("payoff_id") or index)
                              for index, item in enumerate(hits, 1)]
    diagnostics: list[dict[str, Any]] = []
    for episode in window:
        if delivered.get(episode):
            continue
        row = episode_rows.get(episode) or {}
        diagnostics.append({
            "code": "NO_DELIVERED_PAYOFF",
            "episode": episode,
            "answer_field": "no_payoff_answer",
            "answered": bool(_text(row.get("no_payoff_answer"))),
        })
    run: list[str] = []
    for episode in window + [None]:
        if episode is not None and not delivered.get(episode):
            run.append(episode)
            continue
        if len(run) >= 2:
            rows = [episode_rows.get(item) or {} for item in run]
            diagnostics.append({
                "code": "CONSECUTIVE_NO_PAYOFF_RUN",
                "episode": f"{run[0]}..{run[-1]}",
                "episodes": list(run),
                "answer_field": "no_payoff_answer",
                "answered": all(_text(row.get("no_payoff_answer")) for row in rows),
            })
        run = []
    return diagnostics


def report_status(report: dict[str, Any], *, strict_diagnostics: bool = False) -> str:
    if report.get("failures"):
        return "FAIL"
    if strict_diagnostics and any(not row.get("answered") for row in report.get("diagnostics") or []):
        return "DIAGNOSTIC_UNANSWERED"
    return "PASS"


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="validate an arc plan + hook/payoff ledger")
    check.add_argument("--ledger", type=Path, required=True)
    check.add_argument("--out", type=Path)
    check.add_argument("--strict-diagnostics", action="store_true",
                       help="treat an unanswered diagnostic as a failure (default: report only)")
    args = parser.parse_args(argv)

    report = validate(load(args.ledger))
    report["strict_diagnostics"] = bool(args.strict_diagnostics)
    status = report_status(report, strict_diagnostics=args.strict_diagnostics)
    payload = {**report, "status": status}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"status": status, "failures": payload["failures"],
                      "diagnostics": len(payload["diagnostics"])}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
