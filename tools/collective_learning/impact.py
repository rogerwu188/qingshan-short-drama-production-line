"""Explicit rule impact scope -> which FREE cached checks of a run are now stale.

``knowledge_sync_core.free_recheck_targets`` matches a rule's implementation file
against each step's own script (argv[1]); a rule whose implementation is a library
imported by other steps therefore matched nothing.  A rule can now declare its
impact explicitly:

    impact_scope: {free_checks: [step name or script basename, ...],
                   modules:     [engine module path, ...],   # matched against step argv
                   stages:      [stage id, ...]}              # restricts the above

Guarantees (requirement §2.2 item 3, T18):
  * only steps recorded as ``paid is False`` can be marked stale;
  * a matching paid step is listed under ``paid_never_resubmitted`` and nothing else
    happens to it -- this function returns data, it re-runs nothing and posts nothing;
  * a step outside the declared scope is untouched (no blanket invalidation).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _step_matches(step: dict[str, Any], scope: dict[str, Any]) -> list[str]:
    argv = [str(a) for a in step.get("argv") or []]
    script = Path(argv[1]).name if len(argv) > 1 else ""
    name = str(step.get("name") or "")
    reasons = []
    for item in scope.get("free_checks") or []:
        if item in (name, script):
            reasons.append(f"free_check:{item}")
    for module in scope.get("modules") or []:
        base = Path(module).name
        stem = Path(module).with_suffix("").as_posix().replace("/", ".")
        if any(Path(a).name == base or a.endswith(module) or stem in a for a in argv):
            reasons.append(f"module:{module}")
    return reasons


def stale_checks(state: dict[str, Any], rule_id: str, impact_scope: dict[str, Any] | None) -> dict[str, Any]:
    scope = impact_scope or {}
    stages = set(scope.get("stages") or [])
    stale: list[dict[str, Any]] = []
    paid: list[dict[str, Any]] = []
    for stage_id, stage in (state.get("stages") or {}).items():
        if not isinstance(stage, dict) or (stages and stage_id not in stages):
            continue
        for step in stage.get("steps") or []:
            if not isinstance(step, dict):
                continue
            reasons = _step_matches(step, scope)
            if not reasons:
                continue
            entry = {"stage": stage_id, "step_name": step.get("name"), "reasons": reasons,
                     "finished_at": step.get("finished_at")}
            (stale if step.get("paid") is False else paid).append(entry)
    return {"rule_id": rule_id, "declared": bool(impact_scope), "stale_free_checks": stale,
            "paid_never_resubmitted": paid, "action": "REPORT_ONLY_NOTHING_RE_RUN"}
