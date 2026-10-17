#!/usr/bin/env python3
"""Stateful-prop ownership and visibility rules for generated video beats."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


REQUIRED_FIELDS = ("owner", "hand", "position", "disposition")


def compile_prop_states(spec: dict[str, Any], *, source_id: str, preproduction_only: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    states: list[dict[str, Any]] = []
    action_kind = str((spec.get("action") or {}).get("action_kind") or "").upper()
    for index, prop in enumerate(spec.get("props") or [], 1):
        prop_id = str(prop.get("prop_id") or prop.get("prop") or f"PROP_{index}")
        state = prop.get("state") or prop.get("prop_state") or {}
        entry = deepcopy(state.get("entry") or prop.get("entry_state") or {})
        exit_state = deepcopy(state.get("exit") or prop.get("exit_state") or {})
        # v4 contracts authored recurring props as a binding plus the beat's
        # action.start_state/end_state.  Materialise the same structured state
        # here instead of treating that valid v4 form as missing data.  Values
        # are intentionally opaque authored text; no new story event is inferred.
        #
        # Ownership and authorization are bound to the source field only when
        # explicitly present; do not fabricate writer_authored or visual PASS
        # from the compiler's own inference.
        action = spec.get("action") or {}
        if not entry and not exit_state and (prop.get("binding") or prop.get("note") or action.get("start_state")):
            # Bind owner to source field only; do not invent it from subject_id
            owner_field = prop.get("owner") or action.get("prop_owner")
            if not owner_field:
                # Leave owner empty if not explicitly authored; downstream will report MISSING
                owner_field = ""
            anchor = str(prop.get("anchor") or "PRIMARY_ACTION_PLANE")
            entry = {"owner": owner_field, "hand": "按动作合同声明的手部/持有关系",
                     "position": anchor, "disposition": str(action.get("start_state") or prop.get("binding"))}
            exit_state = {"owner": owner_field, "hand": "按动作合同声明的手部/持有关系",
                          "position": anchor, "disposition": str(action.get("end_state") or action.get("primary_action") or prop.get("binding"))}
            # Only set state fields that are actually bound to source; do not
            # modify the input dict or fabricate authorization/visual status.
            # Authorization and visual confirmation must come from the source
            # contract; the compiler does not grant them.
        if not entry or not exit_state:
            failures.append(f"PROP_STATE_MISSING:{source_id}:{prop_id}")
            continue
        for endpoint, values in (("ENTRY", entry), ("EXIT", exit_state)):
            missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
            if missing:
                failures.append(f"PROP_STATE_FIELDS_MISSING:{source_id}:{prop_id}:{endpoint}:{','.join(missing)}")
        ownership_changed = any(entry.get(field) != exit_state.get(field) for field in ("owner", "hand", "disposition"))
        authorization = prop.get("transition_authorization") or state.get("transition_authorization") or {}
        if ownership_changed and authorization.get("writer_authored") is not True:
            failures.append(f"PROP_OWNERSHIP_CHANGE_NOT_WRITER_AUTHORED:{source_id}:{prop_id}")
        if action_kind == "DIALOGUE" and ownership_changed and authorization.get("writer_authored") is not True:
            failures.append(f"DIALOGUE_PROP_OWNERSHIP_CHANGE_FORBIDDEN:{source_id}:{prop_id}")
        visual = prop.get("start_frame_visual_confirmation") or state.get("start_frame_visual_confirmation") or {}
        # Time-scope check: only require visual confirmation at the beat where
        # the prop first enters the action plane. If the prop is declared hidden
        # or appears later, defer to the source contract's visibility scope.
        visibility = prop.get("visibility_scope") or state.get("visibility_scope") or "VISIBLE_AT_START"
        if not preproduction_only and visibility == "VISIBLE_AT_START":
            if visual.get("status") != "PASS" or not visual.get("evidence_ref"):
                failures.append(f"START_FRAME_PROP_STATE_NOT_VISUALLY_CONFIRMED:{source_id}:{prop_id}")
        elif visibility in ("HIDDEN_UNTIL_ACTION", "APPEARS_LATER"):
            # These scopes defer visual confirmation to the action/beat where the
            # prop enters the frame; do not require it at the segment start frame.
            pass
        states.append({
            "prop_id": prop_id,
            "entry": entry,
            "exit": exit_state,
            "ownership_changed": ownership_changed,
            "transition_authorization": deepcopy(authorization),
            "start_frame_visual_confirmation": deepcopy(visual),
        })
    return states, failures
