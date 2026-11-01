#!/usr/bin/env python3
"""Rule 8 as a MUST-RESPOND list: where the pressure is, where it turns, what it pays off.

Why this exists
---------------
Rule 8 (``nalu_writer_selfcheck_seq29.py`` §规则 8, :284-305) is the only rule in
the S1 stack that asks whether an episode is *watchable* rather than well formed.
It has always run with ``rule8_authorized: false``, so its three findings were
printed and discarded: E13 shipped with ``PRESSURE_SOURCE_LATE:112.0``,
``NOT_CONCRETE:THREAT`` and ``EPISODE_PAYOFF_MISSING``; E11 at 81.5 s and E12 at
236.5 s were the same.  Three episodes, three S1 PASSes.

Line owner 2026-11-01 changed what Rule 8 is for: for conflict, pressure, action,
turn and payoff the WRITER STATES WHERE IT HAPPENS and CITES SCRIPT EVIDENCE
(a scene/shot id or a line id), and NOT_APPLICABLE is allowed with a reason.  A
non-empty field is not an answer; the cited id has to exist in this episode's
own layers, otherwise the writer is describing an episode they did not write.

This tool turns a seq29 report into that list:

  ``open``       read the selfcheck report and the episode's narrative/contract,
                 and write one row per Rule 8 item (R8A pressure, R8B payoff,
                 R8C action chain) plus one row per residue code the selfcheck
                 actually reported.  Each row is OPEN until the writer answers.
  ``respond``    accept the writer's responses (``--responses``), check every
                 cited evidence id against the layers, and mark each row
                 ANSWERED, NOT_APPLICABLE (with a reason) or INVALID (a citation
                 that does not resolve).
  ``evaluate``   the one entry point a pipeline would call: read the report, read
                 the responses if given, and return the gate result.

Non-blocking by default
-----------------------
``configs/WRITER_RULE8_RESPONSE_V1.json`` carries ``blocking: false``.  The
default configuration can only report.  A deployment that wants S1 to refuse an
unanswered Rule 8 must turn that switch on explicitly (line owner decision); this
tool never treats the absence of the config as permission to block.

No quotas
---------
Nothing here asks for more conflict, an earlier fight or an extra turn.  A writer
may answer that the episode is a quiet one; what is not allowed is leaving the
item unanswered.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

TOOL_ID = "writer_rule8_response.v1"
SCHEMA = "qingshan.writer_rule8_response.v1"
RESPONSES_SCHEMA = "qingshan.writer_rule8_writer_responses.v1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/WRITER_RULE8_RESPONSE_V1.json"

ITEMS = (
    ("R8A", "pressure_source", "external pressure: where it enters and what makes it concrete"),
    ("R8B", "episode_payoff", "what this episode itself pays off"),
    ("R8C", "action_chain", "want → blocked → act"),
)

ANSWER_KINDS = ("CITED", "NOT_APPLICABLE")
MIN_REASON_CHARS = 12
SHOT_ID = re.compile(r"^E\d{2,3}-S\d{2}-\d{2,3}$")
SCENE_ID = re.compile(r"^E\d{2,3}-S\d{2}$")
LINE_ID = re.compile(r"^E\d{2,3}-L\d{2,3}$")


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    candidate = Path(path or CONFIG_PATH)
    if not candidate.is_file():
        # fail CLOSED on the only thing that matters: an absent config means
        # report-only, never blocking.
        return {"schema": "qingshan.writer_rule8_response_config.v1", "blocking": False,
                "missing_config": True}
    return json.loads(candidate.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- evidence


class Evidence:
    """The ids a citation may legally name, read from the episode's own layers."""

    def __init__(self, narrative_text: str = "", contract: dict[str, Any] | None = None):
        contract = contract or {}
        self.shots = {str(row.get("shot_id")) for row in contract.get("shots") or []
                      if isinstance(row, dict) and row.get("shot_id")}
        self.scenes = {str(row.get("scene_id")) for row in contract.get("scene_states") or []
                       if isinstance(row, dict) and row.get("scene_id")}
        self.scenes |= {str(row.get("scene_id")) for row in contract.get("shots") or []
                        if isinstance(row, dict) and row.get("scene_id")}
        # line ids: the narrative writes 「## E13-S01｜…」 headers and dialogue lines
        # as 「角色：台词」; a writer citing a line cites its shot id + the spoken text,
        # so the LINE- form is only accepted when the text also carries it.
        self.lines = set(re.findall(r"\bE\d{2,3}-L\d{2,3}\b", narrative_text))
        self.narrative_text = narrative_text

    def resolves(self, evidence_id: str) -> str | None:
        """Return the kind the id resolves to, or None."""
        value = str(evidence_id or "").strip()
        if value in self.shots:
            return "shot_id"
        if value in self.scenes:
            return "scene_id"
        if value in self.lines:
            return "line_id"
        return None

    def snapshot(self) -> dict[str, int]:
        return {"shots": len(self.shots), "scenes": len(self.scenes), "lines": len(self.lines)}


def load_evidence(contract_path: Path | str | None,
                  narrative_path: Path | str | None) -> Evidence:
    contract: dict[str, Any] = {}
    if contract_path and Path(contract_path).is_file():
        contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    narrative = ""
    if narrative_path and Path(narrative_path).is_file():
        narrative = Path(narrative_path).read_text(encoding="utf-8")
    return Evidence(narrative, contract)


# --------------------------------------------------------------------------- rows


def build_rows(report: dict[str, Any], evidence: Evidence,
               responses: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One row per Rule 8 item, plus one per residue code the report carries."""
    failures = [str(code) for code in report.get("failures") or []]
    warnings = [str(code) for code in report.get("warnings") or []]
    # the selfcheck reports Rule 8 findings either as failures (when the line
    # owner authorised rule8) or as ``RULE8_NOT_AUTHORISED_INFO:``-prefixed
    # warnings.  Either way the item is one the writer must answer.
    residue = []
    for code in failures + warnings:
        stripped = code.split(":", 1)[-1] if code.startswith("RULE8_NOT_AUTHORISED_INFO:") else code
        if stripped.startswith("R8"):
            residue.append(stripped)
    answered = _responses_by_item(responses)

    rows: list[dict[str, Any]] = []
    for item, field, question in ITEMS:
        codes = sorted({code for code in residue if code.startswith(item)})
        row = {
            "item_id": item,
            "contract_field": field,
            "required_question": question,
            "selfcheck_codes": codes,
            "status": "OPEN",
            "answer": None,
            "evidence_ids": [],
            "resolved_evidence": [],
        }
        if not codes:
            row["note"] = ("the selfcheck reported nothing for this item; the writer still "
                           "states where it happens")
        _apply_response(row, answered.get(item))
        rows.append(row)
    return rows


def _responses_by_item(responses: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(responses, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in responses.get("items") or []:
        if isinstance(row, dict) and str(row.get("item_id") or "").strip():
            out[str(row["item_id"]).strip()] = row
    return out


def _apply_response(row: dict[str, Any], response: dict[str, Any] | None) -> None:
    if not response:
        return
    kind = str(response.get("answer") or "").strip()
    reason = str(response.get("reason") or "").strip()
    ids = [str(value).strip() for value in (response.get("evidence_ids") or []) if str(value).strip()]
    if kind not in ANSWER_KINDS:
        row.update({"status": "INVALID", "reason": f"ANSWER_KIND_INVALID:{kind!r}"})
        return
    if len(reason) < MIN_REASON_CHARS:
        row.update({"status": "INVALID", "reason": f"REASON_TOO_SHORT:{len(reason)}"})
        return
    if kind == "NOT_APPLICABLE":
        row.update({"status": "NOT_APPLICABLE", "answer": kind, "reason": reason})
        return
    if not ids:
        row.update({"status": "INVALID", "reason": "CITED_WITHOUT_EVIDENCE_IDS"})
        return
    row.update({"status": "ANSWERED", "answer": kind, "reason": reason, "evidence_ids": ids})


def resolve_rows(rows: list[dict[str, Any]], evidence: Evidence) -> list[str]:
    """Resolve every cited id; rewrite a row to INVALID when one does not exist."""
    failures: list[str] = []
    for row in rows:
        if row["status"] != "ANSWERED":
            continue
        resolved: list[str] = []
        unresolved: list[str] = []
        for evidence_id in row["evidence_ids"]:
            kind = evidence.resolves(evidence_id)
            if kind is None:
                unresolved.append(evidence_id)
            else:
                resolved.append(f"{kind}:{evidence_id}")
        row["resolved_evidence"] = resolved
        if unresolved:
            row["status"] = "INVALID"
            row["reason"] = "EVIDENCE_ID_NOT_IN_LAYERS:" + ",".join(unresolved)
            failures.append(f"RULE8_EVIDENCE_UNRESOLVED:{row['item_id']}:" + ",".join(unresolved))
    return failures


def evaluate(report: dict[str, Any], evidence: Evidence, responses: dict[str, Any] | None = None,
             *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if config is not None else load_config()
    rows = build_rows(report, evidence, responses)
    failures = resolve_rows(rows, evidence)
    blocking = bool(config.get("blocking") is True)
    unresolved = [row["item_id"] for row in rows if row["status"] == "OPEN"]
    invalid = [row["item_id"] for row in rows if row["status"] == "INVALID"]
    return {
        "schema": SCHEMA,
        "tool": TOOL_ID,
        "episode": report.get("episode"),
        "policy": config.get("policy"),
        "blocking_enabled": blocking,
        "status": ("BLOCKED" if (blocking and (unresolved or invalid))
                   else "FAIL" if invalid
                   else "PENDING_WRITER_RESPONSE" if unresolved
                   else "ANSWERED"),
        "rows": rows,
        "open_items": unresolved,
        "invalid_items": invalid,
        "failures": failures,
        "evidence_space": evidence.snapshot(),
        "note": "Non-blocking by default.  An unanswered item is recorded, never silently "
                "cleared; nothing here asks for more conflict or an earlier fight.",
    }


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("open", "list the Rule 8 items still waiting for the writer"),
        ("respond", "apply the writer's responses and resolve their citations"),
        ("evaluate", "read report + optional responses and print the result"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--report", type=Path, required=True,
                         help="the nalu_writer_selfcheck_seq29.py output")
        cmd.add_argument("--contract", type=Path, help="the episode's generation contract")
        cmd.add_argument("--narrative", type=Path, help="the episode's narrative canonical")
        cmd.add_argument("--responses", type=Path)
        cmd.add_argument("--config", type=Path, default=CONFIG_PATH)
        cmd.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    evidence = load_evidence(args.contract, args.narrative)
    responses = (json.loads(args.responses.read_text(encoding="utf-8"))
                 if args.responses else None)
    config = load_config(args.config)
    result = evaluate(report, evidence, responses, config=config)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"status": result["status"], "open": result["open_items"],
                      "invalid": result["invalid_items"],
                      "blocking_enabled": result["blocking_enabled"]}, ensure_ascii=False))
    return 1 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
