#!/usr/bin/env python3
"""Does the writer-capability policy apply to this episode, and what is it still owed?

Why this exists
---------------
Arc planning, adaptation dispositions, the script review and the Rule 8 response are
only worth building if the per-episode write has to consume them.  The line owner
2026-11-01: 「arc plan + adaptation decisions must be inputs before the per-episode
layers are built」 and 「wire behind a policy profile/flag so already-sealed episodes
(E01-E13, LEGACY) are unaffected and E14+ use it」.

So every new check is switched by ONE decision, taken here and nowhere else:

  SELECTED      WRITER_CAPABILITY_V1 — E14 onwards, unless the config or the
                ``NALU_WRITER_CAPABILITY=off`` override says otherwise
  LEGACY        an episode at or below the switch, or a sealed episode, or the
                override — exactly the old behaviour, nothing new is required

This module also answers "what is still owed for this episode": which of the four
inputs exist, what their validators said, and whether the narrative that will be
sealed is the narrative the review read.  It is a REPORT.  Nothing in it refuses a
stage unless the config's ``blocking`` switch for that input is on, and every
switch ships off.

Wiring points (docs/knowledge/WRITER_CAPABILITY_PLAN_V1.md):
  * pre-S1, before the four layers are read: ``inputs()`` names what is missing, and
    a writer who is about to build layers gets that list before writing them.
  * S1: ``stage_summary()`` lands in ``StageResult.details`` next to the other S1
    evidence, so a receipt says which profile ran and what it recorded.
  * writer finalize: ``sealed_binding()`` compares the sealed narrative's sha256 with
    the sha the script review was bound to.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

#: nalu_pipeline puts ``<engine>/tools`` on sys.path and imports this module as
#: ``writer_capability``; the validators are imported as ``tools.<name>``, so the
#: engine root itself must be importable too.
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ENGINE_ROOT))

POLICY_ID = "WRITER_CAPABILITY_V1"
TOOL_ID = "writer_capability.v1"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/WRITER_CAPABILITY_V1.json"
ENV_OVERRIDE = "NALU_WRITER_CAPABILITY"
EPISODE_RE = re.compile(r"^E(\d{2,3})$")

LEGACY = "LEGACY"
SELECTED = POLICY_ID


class Ctx:
    """The two files a caller may hand in instead of letting this module guess."""

    def __init__(self, config: Path | str | None = None):
        self.config_path = Path(config) if config else CONFIG_PATH
        self.config = load_config(self.config_path)


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    candidate = Path(path or CONFIG_PATH)
    if not candidate.is_file():
        # no config means this capability does not exist yet: LEGACY for everyone.
        return {"schema": "qingshan.writer_capability.v1", "policy_id": POLICY_ID,
                "enabled": False, "missing_config": True, "blocking": {}}
    return json.loads(candidate.read_text(encoding="utf-8"))


def episode_number(episode: str) -> int:
    match = EPISODE_RE.match(str(episode or "").strip().upper())
    if not match:
        raise SystemExit(f"WRITER_CAPABILITY_EPISODE_INVALID:{episode!r}")
    return int(match.group(1))


def sealed_episodes(config: dict[str, Any]) -> set[str]:
    return {str(value) for value in
            ((config.get("profiles") or {}).get(LEGACY) or {}).get("sealed_episodes") or []}


def profile_for(episode: str, config: dict[str, Any] | None = None,
                environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Return ``{profile, reason, enabled_from_episode}``.  One decision, stated."""
    config = config if config is not None else load_config()
    env = os.environ if environ is None else environ
    switch = str(env.get(config.get("env_override") or ENV_OVERRIDE) or "").strip().lower()
    number = episode_number(episode)
    enabled = config.get("enabled") is True
    start = str(config.get("enabled_from_episode") or "").strip()
    base = {"enabled_from_episode": start or None}
    if str(episode).upper() in sealed_episodes(config):
        return {**base, "profile": LEGACY, "reason": "SEALED_BEFORE_THIS_CAPABILITY"}
    if switch == "off":
        return {**base, "profile": LEGACY, "reason": "ENV_OVERRIDE_OFF"}
    if switch == "on":
        return {**base, "profile": SELECTED, "reason": "ENV_OVERRIDE_ON"}
    if not enabled:
        return {**base, "profile": LEGACY, "reason": "CAPABILITY_DISABLED_IN_CONFIG"}
    if not start:
        return {**base, "profile": LEGACY, "reason": "NO_ENABLED_FROM_EPISODE"}
    if number < episode_number(start):
        return {**base, "profile": LEGACY, "reason": f"BEFORE_{start.upper()}"}
    return {**base, "profile": SELECTED, "reason": f"AT_OR_AFTER_{start.upper()}"}


def applies(episode: str, config: dict[str, Any] | None = None,
            environ: dict[str, str] | None = None) -> bool:
    return profile_for(episode, config, environ)["profile"] == SELECTED


# --------------------------------------------------------------------------- inputs


def _load(path: Path | str | None) -> Any:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_unreadable": str(candidate)}


def inputs(episode: str, *, arc_ledger: Path | str | None = None,
           adaptation_disposition: Path | str | None = None,
           script_review_report: Path | str | None = None,
           rule8_report: Path | str | None = None,
           config: dict[str, Any] | None = None) -> dict[str, Any]:
    """What each input says for this episode, and what is still owed."""
    config = config if config is not None else load_config()
    blocking = config.get("blocking") or {}
    rows: dict[str, Any] = {}

    ledger = _load(arc_ledger)
    if ledger is None:
        rows["arc_ledger"] = {"present": False, "status": "MISSING"}
    else:
        from tools.writer_arc_ledger import validate
        report = validate(ledger)
        covered = episode.upper() in {str(row.get("episode")).upper()
                                      for row in ledger.get("episodes") or []
                                      if isinstance(row, dict)}
        rows["arc_ledger"] = {
            "present": True,
            "status": report["status"],
            "covers_this_episode": covered,
            "failures": report["failures"][:12],
            "diagnostics": len(report["diagnostics"]),
            "path": str(arc_ledger),
        }

    disposition = _load(adaptation_disposition)
    if disposition is None:
        rows["adaptation_disposition"] = {"present": False, "status": "MISSING"}
    else:
        from tools.adaptation_policy import validate_disposition
        report = validate_disposition(disposition)
        rows["adaptation_disposition"] = {
            "present": True,
            "status": report["status"],
            "matches_episode": str(disposition.get("episode")).upper() == episode.upper(),
            "failures": report["failures"][:12],
            "path": str(adaptation_disposition),
        }

    review = _load(script_review_report)
    if review is None:
        rows["script_review"] = {"present": False, "status": "MISSING"}
    else:
        rows["script_review"] = {
            "present": True,
            "status": review.get("review_state") or review.get("status"),
            "answered": not review.get("unanswered"),
            "escalations": len(review.get("escalations") or []),
            "narrative_sha256": review.get("narrative_sha256"),
            "path": str(script_review_report),
        }

    rule8 = _load(rule8_report)
    if rule8 is None:
        rows["rule8_response"] = {"present": False, "status": "MISSING"}
    else:
        rows["rule8_response"] = {
            "present": True,
            "status": rule8.get("status"),
            "open_items": rule8.get("open_items") or [],
            "invalid_items": rule8.get("invalid_items") or [],
            "path": str(rule8_report),
        }

    owed = [name for name, row in rows.items() if not row["present"]]
    return {
        "schema": "qingshan.writer_capability_inputs.v1",
        "tool": TOOL_ID,
        "episode": episode.upper(),
        "policy": POLICY_ID,
        "inputs": rows,
        "owed": owed,
        "blocking": {name: bool(blocking.get(name)) for name in blocking if name != "note"},
        "blocks_stage": blocking_policy(rows, blocking),
    }


def blocking_policy(rows: dict[str, Any], blocking: dict[str, Any]) -> list[str]:
    """Only a switch that is explicitly true turns a recorded state into a block.

    Line owner 2026-11-01 follow-up: the PROCEDURE is required — a script cannot be marked complete for paid
    preparation without an arc ledger, its adaptation disposition, a completed script review the writer has
    answered, and a grounded Rule 8 answer (or a NOT_APPLICABLE reason).  A MISSING input is therefore as much a
    block as an incomplete one.  Creative judgement never blocks here: a review's opinion that a hook is weak or
    the pace slow is a revision note the writer answers; only an unanswered or missing step stops the stage.
    """
    blocks: list[str] = []
    if blocking.get("missing_inputs") is True:
        if not rows["arc_ledger"].get("present"):
            blocks.append("ARC_LEDGER_MISSING")
        if not rows["adaptation_disposition"].get("present"):
            blocks.append("ADAPTATION_DISPOSITION_MISSING")
        if not rows["script_review"].get("present"):
            blocks.append("SCRIPT_REVIEW_MISSING")
        if not rows["rule8_response"].get("present"):
            blocks.append("RULE8_RESPONSE_MISSING")
    if rows["arc_ledger"].get("present") and rows["arc_ledger"]["status"] != "PASS" \
            and blocking.get("ledger_failures") is True:
        blocks.append("ARC_LEDGER")
    if rows["adaptation_disposition"].get("present") and rows["adaptation_disposition"]["status"] != "PASS" \
            and blocking.get("ledger_failures") is True:
        blocks.append("ADAPTATION_DISPOSITION")
    if rows["script_review"].get("present") and (
            rows["script_review"].get("status") == "INCOMPLETE"
            and blocking.get("unanswered_script_review") is True):
        blocks.append("SCRIPT_REVIEW_UNANSWERED")
    if rows["rule8_response"].get("present") and (
            (rows["rule8_response"].get("open_items")
             or rows["rule8_response"].get("invalid_items"))
            and blocking.get("open_rule8_items") is True):
        blocks.append("RULE8_OPEN")
    return blocks


# --------------------------------------------------------------------------- sealed binding


def sealed_binding(review: dict[str, Any] | None, narrative: Path | str | None) -> dict[str, Any]:
    """Was the sealed narrative the one the review read?

    The review binds the narrative by sha256 at request time; the seal hashes the
    real file.  A revision the writer made after the review must therefore show up
    here rather than passing silently.
    """
    import hashlib

    if not review:
        return {"status": "NO_SCRIPT_REVIEW", "matches": None}
    expected = str(review.get("narrative_sha256") or "").strip()
    if not expected:
        return {"status": "REVIEW_NOT_BOUND_TO_A_NARRATIVE", "matches": None}
    if not narrative or not Path(narrative).is_file():
        return {"status": "SEALED_NARRATIVE_MISSING", "matches": False,
                "reviewed_sha256": expected}
    actual = hashlib.sha256(Path(narrative).read_bytes()).hexdigest()
    return {"status": "MATCH" if actual == expected else "SEALED_NARRATIVE_CHANGED_SINCE_REVIEW",
            "matches": actual == expected,
            "reviewed_sha256": expected, "sealed_sha256": actual,
            "sealed_path": str(narrative)}


# --------------------------------------------------------------------------- S1 summary


def stage_summary(episode: str, *, arc_ledger: Path | str | None = None,
                  adaptation_disposition: Path | str | None = None,
                  script_review_report: Path | str | None = None,
                  rule8_report: Path | str | None = None,
                  narrative: Path | str | None = None,
                  config: dict[str, Any] | None = None,
                  environ: dict[str, str] | None = None) -> dict[str, Any]:
    """The block S1 records in its state and receipt.  Never raises."""
    config = config if config is not None else load_config()
    try:
        selected = profile_for(episode, config, environ)
    except SystemExit as exc:  # an invalid episode name must not crash a stage
        return {"schema": "qingshan.writer_capability_stage.v1", "status": "INVALID",
                "reason": str(exc)}
    if selected["profile"] == LEGACY:
        return {"schema": "qingshan.writer_capability_stage.v1",
                "status": "NOT_APPLICABLE_LEGACY_PROFILE",
                "profile": LEGACY, "reason": selected["reason"]}
    try:
        recorded = inputs(episode, arc_ledger=arc_ledger,
                          adaptation_disposition=adaptation_disposition,
                          script_review_report=script_review_report,
                          rule8_report=rule8_report, config=config)
    except Exception as exc:  # noqa: BLE001 — an input must never crash S1
        return {"schema": "qingshan.writer_capability_stage.v1", "status": "INPUT_ERROR",
                "profile": SELECTED, "reason": f"{type(exc).__name__}: {exc}"}
    review = _load(script_review_report)
    recorded["sealed_binding"] = sealed_binding(review, narrative)
    recorded["profile"] = SELECTED
    recorded["reason"] = selected["reason"]
    recorded["status"] = ("BLOCKED" if recorded["blocks_stage"]
                          else "OWED" if recorded["owed"]
                          else "RECORDED")
    return recorded


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    prof = sub.add_parser("profile", help="which profile runs this episode, and why")
    prof.add_argument("--episode", required=True)
    prof.add_argument("--config", type=Path, default=CONFIG_PATH)

    check = sub.add_parser("check", help="what each input says and what is still owed")
    check.add_argument("--episode", required=True)
    check.add_argument("--arc-ledger", type=Path)
    check.add_argument("--adaptation-disposition", type=Path)
    check.add_argument("--script-review-report", type=Path)
    check.add_argument("--rule8-report", type=Path)
    check.add_argument("--narrative", type=Path)
    check.add_argument("--config", type=Path, default=CONFIG_PATH)
    check.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "profile":
        print(json.dumps(profile_for(args.episode, config), ensure_ascii=False))
        return 0
    summary = stage_summary(args.episode,
                            arc_ledger=args.arc_ledger,
                            adaptation_disposition=args.adaptation_disposition,
                            script_review_report=args.script_review_report,
                            rule8_report=args.rule8_report,
                            narrative=args.narrative, config=config)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"status": summary.get("status"), "profile": summary.get("profile"),
                      "owed": summary.get("owed", [])}, ensure_ascii=False))
    return 0 if summary.get("status") != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
