#!/usr/bin/env python3
"""Engine-triggered controlled redo after an objective Q2 FAIL (CAMERA_GRAMMAR_V1, line owner 2026-10-26).

Lab Holmes E04: the dispatch asked Codex for the §5 redo of units whose objective Q2 measurement failed and
Codex skipped it.  The pipeline now decides it itself, right after ``video_q2_builder prepare`` measured the
clips and before the video_q2 review is requested:

* candidates: units whose ``prepare.json`` records ``face_count`` (duplicates / extra people),
  ``speaker_framing`` or ``push_in`` (locked camera, face width +50 %; line owner 2026-10-29, lab E08) FAIL —
  duplicates first, then speaker framing, then push-in, then the §5 viewer order (earlier units first);
* a unit whose current clip the line owner already accepted (an active GATE_FAIL_ACCEPTANCE order bound to
  that clip's sha) is not redone: the owner kept it, a redo would spend credits against the order (field
  device …1324 E01, 2026-11-06: 6 of 8 auto-redos were units the owner had just accepted);
* each unit at most once (``<EP>_S6_WAVE_STATE.json`` ``q2_auto_redo``, keyed by unit, with the failed clip
  sha); a unit already redone, or one the budget headroom cannot cover, goes to the review and the §5
  default accept exactly as before;
* cost per unit = the unit's video price (HopsAPI per-second estimate on the router) + one own keyframe
  (~11 credits) when the failure needs a new start frame (face count / speaker framing; a push-in redo keeps
  its start frame and only states the measured problem in the prompt, ``PROMPT_NOTES``); units are taken while
  the cumulative cost stays within the episode headroom (stop at the first unit that does not fit);
* the redo itself is the existing machinery: the clip is parked to ``video/_superseded_<run>_q2_auto_redo``;
  the S6 wave loop then parks the start frame (``redo_switch_start_frames``), generates the unit's own
  keyframe through S5 and submits the single unit in its own wave.  Reviews that this produces (keyframe Q1,
  start-frame evidence, the new Q2) are requested as usual and answered by the operator agent.
"""

from __future__ import annotations

from typing import Any, Callable

FAILURE_PRIORITY = ("face_count", "speaker_framing", "push_in")  # duplicates > speaker framing > push-in
#: failures whose redo parks the start frame and generates the unit's own keyframe (nalu_pipeline.redo_switch_start_frames)
NEW_START_FRAME_FAILURES = ("speaker_framing", "face_count")
OWN_KEYFRAME_CREDITS = 11  # Giggle price; nalu_pipeline costs it per image provider (image_batch_credits)
STATE_KEY = "q2_auto_redo"
#: failure -> the task/unit field value the redo's H3 prompt carries (``h3_redo_findings``); the renderer states
#: the measured problem in plain words (h3_provider_english_contract.REDO_FINDING_SENTENCES)
REDO_FINDINGS_FIELD = "h3_redo_findings"
PROMPT_NOTES = {"push_in": "push_in"}


def needs_own_keyframe(failures: list[str]) -> bool:
    return any(f in NEW_START_FRAME_FAILURES for f in failures)


def redo_findings(state: dict[str, Any] | None, unit_id: str) -> list[str]:
    """The prompt findings of a unit the engine redid (wave-state ``q2_auto_redo`` record), [] otherwise.  Kept
    for good once recorded, so a later recompile keeps the prompt the redo was submitted with."""
    row = ((state or {}).get(STATE_KEY) or {}).get(unit_id) or {}
    return [PROMPT_NOTES[f] for f in row.get("failures") or [] if f in PROMPT_NOTES]


def objective_failures(prepare_row: dict[str, Any]) -> list[str]:
    return [key for key in FAILURE_PRIORITY if ((prepare_row or {}).get(key) or {}).get("status") == "FAIL"]


def plan(prepare_rows: dict[str, dict[str, Any]], attempted: dict[str, Any], *, headroom: int | None,
         unit_cost: Callable[[str], int], unit_order: list[str] | None = None,
         owner_accepted: dict[str, Any] | None = None) -> dict[str, Any]:
    """Which units the engine redoes now.  Pure: no I/O.

    ``prepare_rows`` unit -> prepare.json row; ``attempted`` the wave-state ``q2_auto_redo`` map;
    ``headroom`` credits left under the episode cap (None = unknown -> nothing is redone);
    ``owner_accepted`` unit -> order seq of a line-owner acceptance bound to the unit's current clip sha."""
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
        if uid in (owner_accepted or {}):
            skipped.append({"unit_id": uid, "failures": failed, "reason": "LINE_OWNER_ACCEPTED_THIS_CLIP",
                            "order_seq": (owner_accepted or {})[uid]})
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
