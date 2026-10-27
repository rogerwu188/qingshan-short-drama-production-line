#!/usr/bin/env python3
"""Engine-triggered controlled redo after an objective Q2 FAIL (CAMERA_GRAMMAR_V1, line owner 2026-10-26).

Lab Holmes E04: the dispatch asked Codex for the §5 redo of units whose objective Q2 measurement failed and
Codex skipped it.  The pipeline now decides it itself, right after ``video_q2_builder prepare`` measured the
clips and before the video_q2 review is requested:

* candidates: units whose ``prepare.json`` records ``face_count`` (duplicates / extra people) or
  ``speaker_framing`` FAIL — duplicates first, then speaker framing, then the §5 viewer order (earlier
  units first);
* each unit at most once (``<EP>_S6_WAVE_STATE.json`` ``q2_auto_redo``, keyed by unit, with the failed clip
  sha); a unit already redone, or one the budget headroom cannot cover, goes to the review and the §5
  default accept exactly as before;
* cost per unit = the unit's video price + one own keyframe (~11 credits); units are taken while the
  cumulative cost stays within the episode headroom (stop at the first unit that does not fit);
* the redo itself is the existing machinery: the clip is parked to ``video/_superseded_<run>_q2_auto_redo``;
  the S6 wave loop then parks the start frame (``redo_switch_start_frames``), generates the unit's own
  keyframe through S5 and submits the single unit in its own wave.  Reviews that this produces (keyframe Q1,
  start-frame evidence, the new Q2) are requested as usual and answered by the operator agent.
"""

from __future__ import annotations

from typing import Any, Callable

FAILURE_PRIORITY = ("face_count", "speaker_framing")  # duplicates > speaker framing
OWN_KEYFRAME_CREDITS = 11
STATE_KEY = "q2_auto_redo"


def objective_failures(prepare_row: dict[str, Any]) -> list[str]:
    return [key for key in FAILURE_PRIORITY if ((prepare_row or {}).get(key) or {}).get("status") == "FAIL"]


def plan(prepare_rows: dict[str, dict[str, Any]], attempted: dict[str, Any], *, headroom: int | None,
         unit_cost: Callable[[str], int], unit_order: list[str] | None = None) -> dict[str, Any]:
    """Which units the engine redoes now.  Pure: no I/O.

    ``prepare_rows`` unit -> prepare.json row; ``attempted`` the wave-state ``q2_auto_redo`` map;
    ``headroom`` credits left under the episode cap (None = unknown -> nothing is redone)."""
    order = {uid: index for index, uid in enumerate(unit_order or sorted(prepare_rows))}
    candidates = []
    for uid, row in prepare_rows.items():
        failed = objective_failures(row)
        if failed:
            candidates.append((FAILURE_PRIORITY.index(failed[0]), order.get(uid, len(order)), uid, failed))
    candidates.sort()
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    spent = 0
    budget_stop = False
    for _, _, uid, failed in candidates:
        if uid in (attempted or {}):
            skipped.append({"unit_id": uid, "failures": failed, "reason": "ALREADY_REDONE_ONCE"})
            continue
        cost = int(unit_cost(uid))
        if headroom is None:
            skipped.append({"unit_id": uid, "failures": failed, "reason": "BUDGET_HEADROOM_UNKNOWN", "cost": cost})
            continue
        if budget_stop or spent + cost > int(headroom):
            budget_stop = True
            skipped.append({"unit_id": uid, "failures": failed, "reason": "BUDGET_HEADROOM_SHORT", "cost": cost})
            continue
        spent += cost
        selected.append({"unit_id": uid, "failures": failed, "cost": cost,
                         "failed_clip_sha256": (prepare_rows.get(uid) or {}).get("media_sha256")})
    return {"selected": selected, "skipped": skipped, "planned_credits": spent, "headroom": headroom}
