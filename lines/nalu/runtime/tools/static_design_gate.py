#!/usr/bin/env python3
"""static_design_gate — Roger 2026-09-13: "编剧层设计了太多固定机位的静止段落，修改这个问题".

Free, offline.  Reads <EP>_GENERATION_CONTRACT_v1.json and checks the authored camera plans:

  R1  LOCKED motion_family share of all shots        <= locked_share_max (0.35)
  R2  no two consecutive LOCKED shots
  R3  every no-dialogue shot has camera motion (motion_family != LOCKED)
  R4  a LOCKED shot must carry dialogue and be <= locked_dialogue_seconds_max (5 s)
  R5  no more than same_axis_run_max (2) consecutive shots on the same axis + scale inside a scene
  R6  the first shot of the episode is not LOCKED
  R7  (seq=10) a no-dialogue shot >= 3 s must carry body-level motion in its action text or a moving camera
      family (ARC/TRACK/CRANE/HANDHELD): micro-motion under PUSH_IN/LOCKED measured as an unmotivated
      static hold (E02-VU-010)
  R8  (seq=10) a dialogue shot must last >= spoken_chars/cps + 1.0 s lead + 0.5 s tail (E02-VU-029's last
      syllable was cut)

CAMERA_GRAMMAR_V1 (line owner 2026-10-22; tools/camera_grammar_policy.py; only for contracts that declare
camera_grammar_policy=CAMERA_GRAMMAR_V1 or episodes listed in configs/CAMERA_GRAMMAR_V1.json — never retroactive):
  the forced-motion rules R1/R2/R3/R4/R6/R7 become REPORT_ONLY advisories (a LOCKED or slow DOLLY PUSH_IN
  no-dialogue shot is fine; the advisory only names an empty hold: no body-level action and longer than 3 s),
  and film-grammar notes are added, all REPORT_ONLY:
  R9  a moving camera without a stated motion_motivation (optional field FOLLOW_SUBJECT|REVEAL|EMPHASIS|SUBJECTIVE)
  R10 a new location whose first 2 shots have no establishing framing (WIDE / MEDIUM_WIDE)
  R11 more than 2 consecutive shots at the same shot_scale inside a scene
  R12 a dialogue shot whose listener gets no reaction shot next
  R13 consecutive shots repeat the identical motion_family+motion_direction (the grouped compile still blocks this)
  Only R5 and R8 still block.  Every finding carries a fix hint (fix_hints).

E01 (delivered under the old rules) is REPORT_ONLY; E02+ BLOCK on any failure of R1-R6.  R7/R8 are REPORT_ONLY
for E01/E02 (already generated; the E02 reroll shots were restaged by hand) and BLOCK from E03.
exit 0 PASS / REPORT_ONLY, 3 BLOCK, 2 unreadable.
"""
from __future__ import annotations
import argparse, json, sys, datetime
from pathlib import Path

import nalu_policy_profile as _policy_profile
if str(Path(__file__).resolve().parents[4] / "tools") not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parents[4] / "tools"))
import voice_over_narration as _vo  # V.O. lines are not in the video: R3/R4/R7/R8 judge in-video dialogue
try:
    import camera_grammar_policy as _cg
except Exception:  # noqa: BLE001 — without the policy module every episode keeps the old rules
    _cg = None

POLICY = {"locked_share_max": 0.35, "locked_dialogue_seconds_max": 5.0, "same_axis_run_max": 2,
          "authority": "Roger 2026-09-13 + SUPERVISOR_ORDERS seq=7 PACING_E02_PLUS"}
REPORT_ONLY_EPISODES = {"E01"}
R7R8_REPORT_ONLY_EPISODES = {"E01", "E02"}   # seq=10 rules; BLOCK from E03


def _cp(shot: dict) -> dict:
    return ((shot.get("prompt_spec") or {}).get("camera_plan") or {})


def _motion_purpose_active(contract: dict) -> bool:
    """Whether the narrow (purposeful-motion) R3 applies to this episode.

    Same switch as the previs gate: an episode is affected only once it is
    listed in configs/EPISODE_PREVIS_V1.json or reaches enabled_from_episode,
    or the contract opts in itself.  Episodes already produced keep R3 as it
    was — the plan forbids retroactive rework, and a changed verdict on a paid
    episode would be exactly that.
    """
    try:
        import episode_previs
        return episode_previs.gate_active(
            str(contract.get("episode") or contract.get("episode_id") or ""), contract=contract)
    except Exception:  # noqa: BLE001 — no policy module means the locked behaviour
        return False


def _camera_grammar_active(contract: dict) -> bool:
    """CAMERA_GRAMMAR_V1 (2026-10-22): contract opt-in or config listing only, never retroactive."""
    try:
        return bool(_cg is not None and _cg.active(contract))
    except Exception:  # noqa: BLE001
        return False


BLOCKING_UNDER_GRAMMAR = {"R5", "R8"}

FIX_HINTS = {
    "R1": "Too many unjustified camera-at-rest shots: apply the R3 fix to the shots flagged R3.",
    "R2": "Two unjustified camera-at-rest shots in a row: give one of them body-level action, cut it to <= 3 s, "
          "or a motivated move (see R3).",
    "R3": "No dialogue, camera at rest (LOCKED or slow DOLLY PUSH_IN) and no body-level action: (a) write the body "
          "action into prompt_spec.action.primary_action (walks / turns around / kneels / 走 / 转身 / 跪下), or (b) cut "
          "target_seconds to <= 3 s as an atmosphere/insert hold, or (c) only if the story motivates it, a moving "
          "camera with camera_plan.motion_motivation. Never add a move just to pass.",
    "R4": "A LOCKED dialogue shot longer than 5 s: split the line across two shots or give the shot a motivated "
          "move (DOLLY PUSH_IN with motion_motivation EMPHASIS).",
    "R5": "Three shots on the same camera_side + shot_scale in a scene: change the side or scale of the middle shot.",
    "R6": "The episode opens on an unjustified static hold: open on body-level action, a <= 3 s insert, or a "
          "motivated move (REVEAL).",
    "R7": "No dialogue, >= 3 s, no body-level action, camera neither at rest nor a motivated move: add the body "
          "action, shorten the shot, or declare camera_plan.motion_motivation.",
    "R8": "Dialogue shot shorter than the spoken line: raise target_seconds to the minimum given in the flag.",
    "R9": "Advisory: say why the camera moves, optionally as camera_plan.motion_motivation = "
          "FOLLOW_SUBJECT (follows a moving subject) | REVEAL (discloses new information) | EMPHASIS (underlines a "
          "beat; a slow DOLLY PUSH_IN usually) | SUBJECTIVE (a character's point of view). If none is true, make the "
          "shot LOCKED (start_framing == end_framing).",
    "R10": "A new location opens without an establishing framing: make one of its first 2 shots camera_plan."
           "shot_scale WIDE or MEDIUM_WIDE (shot_size 远景/全景/中全景, start_framing showing the space and where "
           "everyone stands); a hook close-up may stay first.",
    "R11": "More than 2 consecutive shots at the same shot_scale in a scene: change the scale of the flagged shot "
           "(e.g. MEDIUM -> CLOSE_UP or WIDE) and rewrite its shot_size / start_framing / end_framing to match.",
    "R12": "Advisory only: the listener of this line gets no reaction shot; consider a REACTION_CUT shot on the "
           "listener next.",
    "R13": "Two consecutive shots repeat the identical camera move (motion_family + motion_direction): change the "
           "second shot's direction or family, or make it LOCKED.",
}


def _fix_hints(flags: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for flag in flags:
        code = flag.split(":", 1)[-1].split("_", 1)[0]
        if code in FIX_HINTS:
            out.setdefault(code, FIX_HINTS[code])
    return out


def _evaluate_camera_grammar(shots: list[dict], contract: dict, policy: dict) -> tuple[list[dict], list[str], list[str], int]:
    """CAMERA_GRAMMAR_V1 rules over in-video shots; returns rows, failures, advisories, unjustified-rest count."""
    import nalu_prompt_rules as npr
    limits = _cg.thresholds()
    hold_max = float(limits["hold_insert_max_seconds"])
    scale_run_max = int(limits["same_scale_run_max"])
    first_n = int(limits["establishing_within_first_shots"])
    locations = {str(s.get("scene_id")): str(s.get("location_id") or "") for s in contract.get("scene_states") or []}
    language = _vo.contract_language(contract)
    rows, failures, advisories = [], [], []
    prev_unjustified = False
    axis_run, prev_key, prev_scene = 0, None, None
    scale_run, prev_scale = 0, None
    prev_move = None
    unjustified_n = 0
    # R10: index every new-location opening (first shot of the episode, or a scene whose location differs)
    location_runs: list[tuple[int, str]] = []
    prev_loc_key = None
    for i, sh in enumerate(shots):
        scene = str(sh.get("scene_id") or "")
        loc = locations.get(scene) or f"SCENE:{scene}"
        if i == 0 or (scene != str(shots[i - 1].get("scene_id") or "") and loc != prev_loc_key):
            location_runs.append((i, scene))
        prev_loc_key = loc
    for i, sh in enumerate(shots):
        cp = _cp(sh)
        ps = sh.get("prompt_spec") or {}
        fam = str(cp.get("motion_family") or "").upper()
        direction = str(cp.get("motion_direction") or "").upper()
        locked = fam in ("", "LOCKED", "STATIC")
        rest = _cg.is_rest(cp)
        dlg = _dialogue(sh)
        secs = float(sh.get("target_seconds") or 0)
        sid = sh.get("shot_id")
        act = (ps.get("action") or {})
        body = _cg.has_body_motion(str(act.get("primary_action") or ""),
                                   str((act.get("performance") or {}).get("body_action") or ""))
        short_hold = (not dlg) and 0 < secs <= hold_max
        justified = dlg or body or short_hold
        unjustified_rest = rest and not justified
        scale = _cg.shot_scale(sh)
        row = {"shot_id": sid, "scene_id": sh.get("scene_id"), "motion_family": fam or "MISSING", "dialogue": dlg,
               "seconds": secs, "axis": cp.get("camera_side"), "scale": cp.get("shot_scale"),
               "camera_rest": rest, "body_motion": body, "motion_motivation": cp.get("motion_motivation"),
               "flags": []}
        if i == 0 and locked and unjustified_rest:
            row["flags"].append("R6_OPENING_SHOT_LOCKED")
        if locked and unjustified_rest and prev_unjustified:
            row["flags"].append("R2_CONSECUTIVE_LOCKED")
        if unjustified_rest:
            unjustified_n += 1
            row["flags"].append("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION")
        if locked and dlg and secs > policy["locked_dialogue_seconds_max"]:
            row["flags"].append(f"R4_LOCKED_DIALOGUE_SHOT_OVER_{policy['locked_dialogue_seconds_max']:g}S")
        if not dlg and secs >= 3.0 and not rest and not body and _cg.declared_motivation(cp) is None:
            row["flags"].append("R7_NO_DIALOGUE_HOLD_WITHOUT_BODY_MOTION")
        if dlg:
            dtxt = ps.get("dialogue")
            dtxt = dtxt if isinstance(dtxt, str) else " ".join(
                str(x.get("text") if isinstance(x, dict) else x) for x in (dtxt or []))
            dtxt = dtxt.split("：", 1)[1] if "：" in dtxt[:8] else dtxt
            if language == "en":
                # English lines are timed in words (the legacy path counted letters at 4 cps and
                # stretched every English dialogue shot); the speaker prefix "Name:" is dropped
                dtxt = dtxt.split(":", 1)[1] if ":" in dtxt[:24] else dtxt
                rate = (sh.get("dialogue_delivery") or {}).get("english_words_per_second")
            else:
                rate = (sh.get("dialogue_delivery") or {}).get("chinese_characters_per_second")
            need = npr.min_dialogue_seconds(dtxt, rate, language)
            if secs < need:
                row["flags"].append(f"R8_DIALOGUE_SHOT_SHORTER_THAN_{need:g}S")
        if not locked and _cg.declared_motivation(cp) is None:
            row["flags"].append(f"R9_CAMERA_MOVE_WITHOUT_MOTIVATION:{fam}")
        move = None if locked else (fam, direction)
        if move is not None and move == prev_move:  # mirrors validate_camera_sequence (also across scenes)
            row["flags"].append(f"R13_REPEATED_IDENTICAL_MOVE:{fam}:{direction}")
        key = (sh.get("scene_id"), cp.get("camera_side"), cp.get("shot_scale"))
        axis_run = axis_run + 1 if (sh.get("scene_id") == prev_scene and key == prev_key) else 1
        if axis_run > policy["same_axis_run_max"]:
            row["flags"].append("R5_SAME_AXIS_SCALE_RUN")
        scale_run = scale_run + 1 if (sh.get("scene_id") == prev_scene and scale and scale == prev_scale) else 1
        if scale_run > scale_run_max:
            row["flags"].append(f"R11_SAME_SHOT_SCALE_RUN:{scale}x{scale_run}")
        prev_key, prev_scene, prev_scale, prev_move = key, sh.get("scene_id"), scale, move
        prev_unjustified = locked and unjustified_rest
        rows.append(row)
    # R10 establishing framing per new location
    for start, scene in location_runs:
        window = [k for k in range(start, min(start + first_n, len(shots)))
                  if str(shots[k].get("scene_id") or "") == scene]
        if not any(_cg.shot_scale(shots[k]) in _cg.ESTABLISHING_SCALES for k in window):
            rows[start]["flags"].append(f"R10_NEW_LOCATION_WITHOUT_ESTABLISHING_FRAMING:{scene}")
    # R12 advisory: listener reaction coverage
    for i, sh in enumerate(shots):
        if not _dialogue(sh):
            continue
        rsd = (sh.get("prompt_spec") or {}).get("role_semantic_disambiguation") or {}
        listener = str(rsd.get("dialogue_listener_id") or "").strip()
        if not listener:
            continue
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        if nxt is None or nxt.get("scene_id") != sh.get("scene_id"):
            continue
        nxt_cast = {str(c.get("character_id") or "") for c in ((nxt.get("prompt_spec") or {}).get("cast") or [])
                    if str(c.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"}
        if listener not in nxt_cast:
            advisories.append(f"{sh.get('shot_id')}:R12_DIALOGUE_LISTENER_WITHOUT_REACTION_COVERAGE:{listener}")
    # Line owner 2026-10-22: quality comes from the writer/director guidance and the prompt, not from more
    # gates that can stop an unattended run.  Under the policy only the two pre-existing rules that are
    # not anti-static rules still block (R5 same axis+scale run, R8 dialogue too short for its line);
    # every forced-motion rule (R1-R4, R6, R7) and every film-grammar note (R9-R13) is REPORT_ONLY.
    for row in rows:
        for flag in row["flags"]:
            (failures if flag.split("_", 1)[0] in BLOCKING_UNDER_GRAMMAR else advisories).append(
                f"{row['shot_id']}:{flag}")
    return rows, failures, advisories, unjustified_n


def _dialogue(shot: dict) -> bool:
    d = (shot.get("prompt_spec") or {}).get("dialogue")
    if isinstance(d, list):
        return any(str(x.get("text") if isinstance(x, dict) else x).strip() for x in d)
    return bool(str(d or "").strip())


def evaluate(contract: dict, policy: dict, *, current_policy: bool = False) -> dict:
    shots = list(contract.get("shots") or [])
    vo_entities = contract.get("character_entities") or []
    if _vo.voice_over_character_ids(vo_entities):
        # a VOICE_ONLY_NO_PLATE narrator's line never reaches the video model; its timing is the
        # S2 window rule (VOICE_OVER_WINDOW_TOO_SHORT), so these rules see in-video dialogue only
        language = _vo.contract_language(contract)
        shots = [
            {**sh, "prompt_spec": {**(sh.get("prompt_spec") or {}), "dialogue": _vo.in_video_dialogue(
                (sh.get("prompt_spec") or {}).get("dialogue"), vo_entities, language)}}
            if isinstance((sh.get("prompt_spec") or {}).get("dialogue"), str) else sh
            for sh in shots
        ]
    if _camera_grammar_active(contract):
        rows, failures, advisories, unjustified_n = _evaluate_camera_grammar(shots, contract, policy)
        locked_n = sum(1 for r in rows if r["motion_family"] in ("LOCKED", "STATIC", "MISSING"))
        share = round(locked_n / len(rows), 3) if rows else 0.0
        unjustified_share = round(unjustified_n / len(rows), 3) if rows else 0.0
        if rows and unjustified_share > policy["locked_share_max"]:
            advisories.insert(0, f"R1_UNJUSTIFIED_REST_SHARE_{unjustified_share}_OVER_{policy['locked_share_max']}")
        return {"shot_count": len(rows), "locked_count": locked_n, "locked_share": share,
                "camera_grammar_policy": "CAMERA_GRAMMAR_V1", "unjustified_rest_count": unjustified_n,
                "rows": rows, "failures": failures, "advisories": advisories,
                "fix_hints": _fix_hints(failures + advisories)}
    rows, failures = [], []
    prev_locked = False
    axis_run, prev_key, prev_scene = 0, None, None
    for i, sh in enumerate(shots):
        cp = _cp(sh)
        fam = str(cp.get("motion_family") or "").upper()
        locked = fam in ("", "LOCKED", "STATIC")
        dlg = _dialogue(sh)
        secs = float(sh.get("target_seconds") or 0)
        sid = sh.get("shot_id")
        row = {"shot_id": sid, "scene_id": sh.get("scene_id"), "motion_family": fam or "MISSING", "dialogue": dlg,
               "seconds": secs, "axis": cp.get("camera_side"), "scale": cp.get("shot_scale"), "flags": []}
        if i == 0 and locked:
            # P1.3 TODO (codex §2.5): when motion-purpose is active, check if opening
            # shot has clear motivation + body action, not just "it's locked".
            row["flags"].append("R6_OPENING_SHOT_LOCKED")
        if locked and prev_locked:
            # P1.3 TODO (codex §2.5): when motion-purpose is active, check if each
            # locked shot has motivation + body action, not just "two in a row".
            row["flags"].append("R2_CONSECUTIVE_LOCKED")
        if locked and not dlg:
            # R3 was originally "every no-dialogue shot must have camera motion".  The
            # production-line optimisation plan (2026-10-17) makes the intent more precise:
            # a locked camera on a no-dialogue shot is acceptable when a character is visibly
            # performing, but a shot with no dialogue AND no body-level motion AND a locked
            # camera has nothing to show for itself.  R7 (seq=10) already fires when
            # primary_action lacks body-level verbs for a no-dialogue shot >= 3 s.
            #
            # The narrower rule is gated on the previs policy so an episode already paid for
            # keeps its locked behaviour byte-for-byte: the plan is explicit that nothing is
            # reworked retroactively.  Episodes below the switch keep the original R3.
            if _motion_purpose_active(contract):
                ps_act = str(((sh.get("prompt_spec") or {}).get("action") or {}).get("primary_action") or "")
                try:
                    import nalu_prompt_rules as _npr_r3
                    has_body = any(v in ps_act for v in _npr_r3.BODY_VERBS)
                    is_moving = fam in _npr_r3.MOVING_CAMERA
                except Exception:  # noqa: BLE001
                    has_body, is_moving = False, False
                if not is_moving and not has_body:
                    row["flags"].append("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION")
            else:
                row["flags"].append("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION")
        if locked and dlg and secs > policy["locked_dialogue_seconds_max"]:
            row["flags"].append(f"R4_LOCKED_DIALOGUE_SHOT_OVER_{policy['locked_dialogue_seconds_max']:g}S")
        # seq=10 root-cause rules (nalu_prompt_rules): R7 body motion for no-dialogue holds, R8 dialogue length
        try:
            import nalu_prompt_rules as npr
            ps = sh.get("prompt_spec") or {}
            act = str(((ps.get("action") or {}).get("primary_action")) or "")
            if not dlg and secs >= 3.0 and not any(v in act for v in npr.BODY_VERBS) \
                    and fam not in npr.MOVING_CAMERA:
                row["flags"].append("R7_NO_DIALOGUE_HOLD_WITHOUT_BODY_MOTION")
            if dlg:
                dtxt = ps.get("dialogue")
                dtxt = dtxt if isinstance(dtxt, str) else " ".join(
                    str(x.get("text") if isinstance(x, dict) else x) for x in (dtxt or []))
                dtxt = dtxt.split("：", 1)[1] if "：" in dtxt[:8] else dtxt
                cps = (sh.get("dialogue_delivery") or {}).get("chinese_characters_per_second")
                need = npr.min_dialogue_seconds(dtxt, cps)
                if secs < need:
                    row["flags"].append(f"R8_DIALOGUE_SHOT_SHORTER_THAN_{need:g}S")
        except Exception as exc:  # noqa: BLE001 - the rule module is optional for old contracts
            row["flags"].append(f"R7R8_UNAVAILABLE:{type(exc).__name__}")
        key = (sh.get("scene_id"), cp.get("camera_side"), cp.get("shot_scale"))
        if sh.get("scene_id") == prev_scene and key == prev_key:
            axis_run += 1
        else:
            axis_run = 1
        if axis_run > policy["same_axis_run_max"]:
            row["flags"].append("R5_SAME_AXIS_SCALE_RUN")
        prev_key, prev_scene, prev_locked = key, sh.get("scene_id"), locked
        rows.append(row)
        report_only = (
            not current_policy
            and str(contract.get("episode") or contract.get("episode_id") or "")
            in R7R8_REPORT_ONLY_EPISODES
        )
        failures.extend(f"{sid}:{f}" for f in row["flags"]
                        if not (report_only and (f.startswith("R7_") or f.startswith("R8_"))))
    locked_n = sum(1 for r in rows if r["motion_family"] in ("LOCKED", "STATIC", "MISSING"))
    share = round(locked_n / len(rows), 3) if rows else 0.0
    if rows and share > policy["locked_share_max"]:
        # P1.3 TODO (codex §2.5): when motion-purpose is active, R1 should count
        # locked shots WITHOUT valid motivation + body action, not all locked shots.
        failures.insert(0, f"R1_LOCKED_SHARE_{share}_OVER_{policy['locked_share_max']}")
    return {"shot_count": len(rows), "locked_count": locked_n, "locked_share": share, "rows": rows, "failures": failures}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--policy-json", default=None, help="override thresholds (JSON object)")
    a = ap.parse_args()
    policy = dict(POLICY)
    if a.policy_json:
        policy.update(json.loads(a.policy_json))
    try:
        contract = json.loads(Path(a.contract).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"UNREADABLE_CONTRACT:{exc}", file=sys.stderr)
        return 2
    current_policy = _policy_profile.is_current()
    ev = evaluate(contract, policy, current_policy=current_policy)
    mode = (
        "REPORT_ONLY"
        if not current_policy and a.episode in REPORT_ONLY_EPISODES
        else "BLOCKING"
    )
    status = "PASS" if not ev["failures"] else ("REPORT_ONLY_FAIL" if mode == "REPORT_ONLY" else "BLOCK")
    report = {"schema": "nalu.static_design_gate.v1", "gate_id": "NALU-STATIC-DESIGN-GATE", "episode": a.episode,
              "contract": str(Path(a.contract).resolve()), "mode": mode, "status": status,
              "policy_profile": _policy_profile.selected(), "policy": policy,
              **ev, "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"status": status, "locked_share": ev["locked_share"], "failures": len(ev["failures"])}
    if ev.get("camera_grammar_policy"):
        # CAMERA_GRAMMAR_V1: the first failures and their fix hints on stdout so the agent can fix the
        # contract without opening the report (zero credit, pre-POST)
        summary.update({"camera_grammar_policy": ev["camera_grammar_policy"],
                        "first_failures": ev["failures"][:8], "advisories": len(ev.get("advisories") or []),
                        "fix_hints": ev.get("fix_hints") or {}})
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if status in ("PASS", "REPORT_ONLY_FAIL") else 3


if __name__ == "__main__":
    sys.exit(main())
