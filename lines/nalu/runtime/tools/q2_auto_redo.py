#!/usr/bin/env python3
"""Engine-triggered controlled redo after an objective Q2 FAIL (CAMERA_GRAMMAR_V1, line owner 2026-10-26).

Device 1101 E24 review (2026-11-23): the submitted video_q2 VLM answers that compare the clip with the plan -- a
reversed role, a person outside the declared cast, the wrong location, a modern object in a pre-modern world -- are
objective failures too (``with_vlm_failures``); they are classified once the review is in, under the same
one-redo-per-unit rule and episode headroom (no new budget).

Lab Holmes E04: the dispatch asked Codex for the §5 redo of units whose objective Q2 measurement failed and
Codex skipped it.  The pipeline now decides it itself, right after ``video_q2_builder prepare`` measured the
clips and before the video_q2 review is requested:

* candidates: units whose ``prepare.json`` records ``letterbox`` (the decoded clip is not ~9:16 or carries
  letterbox / pillarbox bands -- a technical defect, every render style, line owner 2026-11-19), ``face_count`` (duplicates / extra people), ``wrong_face``
  (a declared character rendered with another character's face, line owner 2026-11-19),
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

#: video_q2 VLM answers compared with the plan (device 1101 E24 review, 2026-11-23): a reversed role (the blade at the
#: heroine's own throat), an invented principal (a stranger's hand, a kneeling armoured figure), the wrong place (a
#: paddy field for a teahouse) and an anachronistic object (eyeglasses in a xianxia world).  Question -> failure key
#: mirrors vlm_review_protocol.VLM_OBJECTIVE_FAILURES.
VLM_QUESTION_FAILURES = {
    "action_roles_as_planned": "role_reversed",
    "no_person_outside_declared_cast": "invented_person",
    "location_matches_scene": "wrong_location",
    "no_modern_object_in_period_world": "anachronism",
}
VLM_FAILURES = tuple(VLM_QUESTION_FAILURES.values())
#: letterbox / non-9:16 clip (technical, 2026-11-19, av_evidence_pack.clip_letterbox) > duplicates > wrong character
#: face (2026-11-19, video_q2_builder.wrong_face_verdict) > the VLM plan failures (2026-11-23) > speaker framing >
#: push-in
FAILURE_PRIORITY = ("letterbox", "face_count", "wrong_face", "invented_person", "role_reversed", "wrong_location",
                    "anachronism", "speaker_framing", "push_in")
#: technical failures measured on the decoded clip itself: redo-eligible in every render style and also when
#: CAMERA_GRAMMAR_V1 is off (the InsightFace failures are not)
TECHNICAL_FAILURES = ("letterbox",)
#: failures that are not InsightFace measurements: eligible in every render style and without CAMERA_GRAMMAR_V1
STYLE_INDEPENDENT_FAILURES = TECHNICAL_FAILURES + VLM_FAILURES
#: failures whose redo parks the start frame and generates the unit's own keyframe (nalu_pipeline.redo_switch_start_frames);
#: a wrong face is usually inherited from the start frame, so it gets its own keyframe too -- and so are an invented
#: person, a reversed role, the wrong place or a modern object (all visible in the opening frame H3 continues)
NEW_START_FRAME_FAILURES = ("speaker_framing", "face_count", "wrong_face", *VLM_FAILURES)
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


def vlm_objective_failures(answers: dict[str, Any] | None) -> list[str]:
    """The failure keys a submitted video_q2 item's answers earn (FAIL on a VLM_QUESTION_FAILURES question)."""
    return [key for question, key in VLM_QUESTION_FAILURES.items()
            if str((answers or {}).get(question) or "").upper() == "FAIL"]


def with_vlm_failures(prepare_rows: dict[str, dict[str, Any]], review: dict[str, Any] | None
                      ) -> dict[str, dict[str, Any]]:
    """``prepare_rows`` with each unit's VLM objective failures from the submitted video_q2 ``review`` added as
    ``{<key>: {"status": "FAIL", "source": "VIDEO_Q2_VLM", ...}}``.  Pure; a unit the review does not cover, or a
    review item whose clip sha differs from the prepared one, adds nothing."""
    out = {uid: dict(row or {}) for uid, row in (prepare_rows or {}).items()}
    for item in (review or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        request_item = item.get("request_item") or {}
        uid = str(request_item.get("unit_id") or item.get("item_id") or "")
        if uid not in out:
            continue
        reviewed = {str(m.get("sha256") or "") for m in request_item.get("media") or []
                    if isinstance(m, dict) and str(m.get("role") or "") == "UNIT_VIDEO"}
        current = str(out[uid].get("media_sha256") or "")
        if current and reviewed and current not in reviewed:
            continue
        for question, key in VLM_QUESTION_FAILURES.items():
            if str((item.get("answers") or {}).get(question) or "").upper() == "FAIL":
                out[uid][key] = {"status": "FAIL", "source": "VIDEO_Q2_VLM", "question": question,
                                 "observation": str(item.get("observation") or "")[:300]}
    return out


def objective_failures(prepare_row: dict[str, Any], *, technical_only: bool = False) -> list[str]:
    # render_style=anime: the InsightFace measurements are NOT_APPLICABLE to anime faces -- never a paid redo; the
    # technical letterbox check and the VLM plan answers apply to every style
    if technical_only or str((prepare_row or {}).get("render_style") or "").lower() == "anime":
        keys: tuple[str, ...] = tuple(k for k in FAILURE_PRIORITY if k in STYLE_INDEPENDENT_FAILURES)
    else:
        keys = FAILURE_PRIORITY
    return [key for key in keys if ((prepare_row or {}).get(key) or {}).get("status") == "FAIL"]


def plan(prepare_rows: dict[str, dict[str, Any]], attempted: dict[str, Any], *, headroom: int | None,
         unit_cost: Callable[[str], int], unit_order: list[str] | None = None,
         owner_accepted: dict[str, Any] | None = None, technical_only: bool = False) -> dict[str, Any]:
    """Which units the engine redoes now.  Pure: no I/O.

    ``prepare_rows`` unit -> prepare.json row; ``attempted`` the wave-state ``q2_auto_redo`` map;
    ``headroom`` credits left under the episode cap (None = unknown -> nothing is redone);
    ``owner_accepted`` unit -> order seq of a line-owner acceptance bound to the unit's current clip sha."""
    order = {uid: index for index, uid in enumerate(unit_order or sorted(prepare_rows))}
    candidates = []
    for uid, row in prepare_rows.items():
        failed = objective_failures(row, technical_only=technical_only)
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
