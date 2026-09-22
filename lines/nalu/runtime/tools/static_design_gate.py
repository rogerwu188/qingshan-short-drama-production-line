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

E01 (delivered under the old rules) is REPORT_ONLY; E02+ BLOCK on any failure of R1-R6.  R7/R8 are REPORT_ONLY
for E01/E02 (already generated; the E02 reroll shots were restaged by hand) and BLOCK from E03.
exit 0 PASS / REPORT_ONLY, 3 BLOCK, 2 unreadable.
"""
from __future__ import annotations
import argparse, json, sys, datetime
from pathlib import Path

import nalu_policy_profile as _policy_profile

POLICY = {"locked_share_max": 0.35, "locked_dialogue_seconds_max": 5.0, "same_axis_run_max": 2,
          "authority": "Roger 2026-09-13 + SUPERVISOR_ORDERS seq=7 PACING_E02_PLUS"}
REPORT_ONLY_EPISODES = {"E01"}
R7R8_REPORT_ONLY_EPISODES = {"E01", "E02"}   # seq=10 rules; BLOCK from E03


def _cp(shot: dict) -> dict:
    return ((shot.get("prompt_spec") or {}).get("camera_plan") or {})


def _dialogue(shot: dict) -> bool:
    d = (shot.get("prompt_spec") or {}).get("dialogue")
    if isinstance(d, list):
        return any(str(x.get("text") if isinstance(x, dict) else x).strip() for x in d)
    return bool(str(d or "").strip())


def evaluate(contract: dict, policy: dict, *, current_policy: bool = False) -> dict:
    shots = list(contract.get("shots") or [])
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
            row["flags"].append("R6_OPENING_SHOT_LOCKED")
        if locked and prev_locked:
            row["flags"].append("R2_CONSECUTIVE_LOCKED")
        if locked and not dlg:
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
    print(json.dumps({"status": status, "locked_share": ev["locked_share"], "failures": len(ev["failures"])}))
    return 0 if status in ("PASS", "REPORT_ONLY_FAIL") else 3


if __name__ == "__main__":
    sys.exit(main())
