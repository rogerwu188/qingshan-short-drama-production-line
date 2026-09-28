#!/usr/bin/env python3
"""direction_policy_gate.py — free, offline S1 gate for Roger's 2026-09-25 "guarantee before
generation" direction policy (codex_docs/ROGER-20260925-NALU-LINE-OPTIMIZATION.md, effective E09).

Numbering: the doc calls its rules R1-R8/W1-W2. They are DP1-DP8/W1-W2 here because
static_design_gate.py already owns R1-R8 for a different (camera/pacing) rule set, and
nalu_writer_selfcheck_seq29.py already owns R5A-R9B for a third. ``doc_ref`` in every failure/
measurement below is the original R-number.

Only the genuinely new, episode-level/aggregate checks live here:

  DP1  shot_scale distribution: CU+MCU >= cu_mcu_min_episode_ratio, WS+FS <= ws_fs_max_episode_ratio,
       at most one WS per scene and it must be that scene's first shot, no WS/FS on a dialogue shot.
  DP2  reaction-shot floor: episode-level <1s-shot share >= under_1s_shot_min_episode_ratio.
       (Everything else in the doc's R2 — shot-length-tracks-dialogue, the HOLD_WORDS ban, and
       blocking_signature adjacency — is already enforced per-episode in build_e0N_layers.py /
       nalu_writer_selfcheck_seq29.py; this gate does not re-implement it.)
  DP3  dialogue continuity: any continuous no-dialogue run > continuous_no_dialogue_seconds_max
       must carry a ``silence_reason`` on its last shot, capped at
       silence_reason_exceptions_max_per_episode exceptions of <= silence_reason_seconds_max_each
       each; episode dialogue-time ratio (sum of dialogue-shot seconds / total seconds, from the
       shot table's own planned durations) must be >= dialogue_time_ratio_min.
  DP5  audit-only: exposes scan_for_literal_rate_figure() so a compiled prompt can be checked for
       a literal chars/sec figure. (DP4/DP6/DP7/DP8 already exist elsewhere; this gate only checks
       their markers are still present in the contract, it does not re-implement their logic.)

A contract without ``direction_policy.enforced: true`` gets a diagnostic-only report (mirrors
nalu_writer_selfcheck_seq29.py's own ``enforced`` gate — old/unmigrated episodes are unaffected).
A missing/unreadable DIRECTION_POLICY_V1.json makes every DPn check a no-op (load_policy() -> {}).

exit 0 PASS / not enforced, 2 unreadable contract, 3 enforced FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "nalu.direction_policy_gate.v1"

# ECU/CU/MCU/MS/FS/WS (Roger's doc) <-> the engine's actual shot_scale enum
# (tools/grouped_camera_contract.py SHOT_SCALES).
SCALE_ABBREV = {
    "EXTREME_CLOSE_UP": "ECU", "CLOSE_UP": "CU", "MEDIUM_CLOSE_UP": "MCU",
    "MEDIUM": "MS", "MEDIUM_WIDE": "FS", "WIDE": "WS",
}
CU_MCU = {"CLOSE_UP", "MEDIUM_CLOSE_UP"}
WS_FS = {"WIDE", "MEDIUM_WIDE"}

# A bare digit next to a rate unit — "4.8字/秒", "5 chars/sec", "5.2字每秒" — is exactly the
# literal number Roger's R5 says a model prompt must never contain.
_NUM = r"\d+(?:\.\d+)?"
_RATE_FIGURE_RE = re.compile(
    rf"每秒\s*{_NUM}\s*(?:个)?\s*(?:汉字|字|词)"                       # 每秒5个汉字 / 每秒5字
    rf"|{_NUM}\s*(?:个)?\s*(?:汉字|字|词)\s*(?:/|每)\s*秒"            # 5字/秒 / 5字每秒 / 5个汉字/秒
    rf"|{_NUM}\s*(?:chinese\s+)?(?:chars?|characters?|words?)\s*(?:/|per)\s*(?:sec(?:ond)?s?|s)\b",  # 5 chars/sec, 2.6 words per second
    re.IGNORECASE)


def load_policy(path: Path) -> dict[str, Any]:
    """Missing/unreadable file -> {} -> every DPn check below no-ops. Mirrors
    tools/reroll_cost_guard.py:load_json / nalu_tail_ad_opt_in.read_json."""
    if not path or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def scan_for_literal_rate_figure(text: str) -> list[str]:
    """DP5 audit primitive: every literal rate figure found in a compiled prompt string.
    Used by tools/tests/test_direction_policy_gate.py against a real compiled SD2 prompt."""
    return [m.group(0) for m in _RATE_FIGURE_RE.finditer(text or "")]


def _camera_plan(shot: dict[str, Any]) -> dict[str, Any]:
    return (shot.get("prompt_spec") or {}).get("camera_plan") or {}


def _has_dialogue(shot: dict[str, Any]) -> bool:
    d = (shot.get("prompt_spec") or {}).get("dialogue")
    if isinstance(d, list):
        return any(str(x.get("text") if isinstance(x, dict) else x).strip() for x in d)
    return bool(str(d or "").strip())


def _dp1_shot_scale_distribution(shots: list[dict[str, Any]], rule: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    scale_counts: dict[str, int] = {}
    scene_first_shot: dict[str, str] = {}
    for sh in shots:
        sid = shot_id = sh.get("shot_id")
        scale = str(_camera_plan(sh).get("shot_scale") or "").upper()
        scale_counts[scale] = scale_counts.get(scale, 0) + 1
        scene = sh.get("scene_id")
        if scene not in scene_first_shot:
            scene_first_shot[scene] = shot_id
        if scale == "WIDE" and shot_id != scene_first_shot[scene]:
            failures.append(f"DP1_WS_NOT_SCENE_OPENING_SHOT:{shot_id}")
        if scale in WS_FS and _has_dialogue(sh):
            failures.append(f"DP1_WS_FS_ON_DIALOGUE_SHOT:{shot_id}:{SCALE_ABBREV.get(scale, scale)}")
    total = len(shots)
    cu_mcu_n = sum(n for s, n in scale_counts.items() if s in CU_MCU)
    ws_fs_n = sum(n for s, n in scale_counts.items() if s in WS_FS)
    cu_mcu_ratio = round(cu_mcu_n / total, 4) if total else 0.0
    ws_fs_ratio = round(ws_fs_n / total, 4) if total else 0.0
    cu_mcu_min = float(rule.get("cu_mcu_min_episode_ratio", 0))
    ws_fs_max = float(rule.get("ws_fs_max_episode_ratio", 1))
    if total and cu_mcu_ratio < cu_mcu_min:
        failures.append(f"DP1_CU_MCU_RATIO_{cu_mcu_ratio}_BELOW_{cu_mcu_min}")
    if total and ws_fs_ratio > ws_fs_max:
        failures.append(f"DP1_WS_FS_RATIO_{ws_fs_ratio}_OVER_{ws_fs_max}")
    ws_per_scene: dict[str, int] = {}
    for sh in shots:
        if str(_camera_plan(sh).get("shot_scale") or "").upper() == "WIDE":
            ws_per_scene[sh.get("scene_id")] = ws_per_scene.get(sh.get("scene_id"), 0) + 1
    ws_max_per_scene = int(rule.get("ws_max_per_scene", 1))
    for scene, n in ws_per_scene.items():
        if n > ws_max_per_scene:
            failures.append(f"DP1_WS_OVER_{ws_max_per_scene}_PER_SCENE:{scene}:{n}")
    return failures, {"shot_scale_counts": scale_counts, "cu_mcu_ratio": cu_mcu_ratio, "ws_fs_ratio": ws_fs_ratio}


def _dp2_reaction_shot_floor(shots: list[dict[str, Any]], rule: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    total = len(shots)
    under_1s = sum(1 for sh in shots if float(sh.get("target_seconds") or 0) < 1.0)
    ratio = round(under_1s / total, 4) if total else 0.0
    floor = float(rule.get("under_1s_shot_min_episode_ratio", 0))
    failures = []
    if total and ratio < floor:
        failures.append(f"DP2_UNDER_1S_SHOT_RATIO_{ratio}_BELOW_{floor}")
    return failures, {"under_1s_shot_ratio": ratio, "under_1s_shot_count": under_1s}


def _dp3_dialogue_continuity(shots: list[dict[str, Any]], rule: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    max_run = float(rule.get("continuous_no_dialogue_seconds_max", 1e9))
    max_exceptions = int(rule.get("silence_reason_exceptions_max_per_episode", 0))
    max_exception_seconds = float(rule.get("silence_reason_seconds_max_each", 1e9))
    dialogue_ratio_min = float(rule.get("dialogue_time_ratio_min", 0))

    run_seconds, run_shots = 0.0, []
    exceptions_used = 0
    silence_runs: list[dict[str, Any]] = []

    def _close_run() -> None:
        nonlocal run_seconds, run_shots, exceptions_used
        if run_seconds <= max_run + 1e-9 or not run_shots:
            run_seconds, run_shots = 0.0, []
            return
        last = run_shots[-1]
        reason = str(last.get("silence_reason") or "").strip()
        silence_runs.append({"shots": [s.get("shot_id") for s in run_shots], "seconds": round(run_seconds, 3),
                             "silence_reason": reason or None})
        if not reason:
            failures.append(f"DP3_SILENCE_RUN_OVER_{max_run:g}S_NO_REASON:{last.get('shot_id')}:{run_seconds:g}")
        elif run_seconds > max_exception_seconds + 1e-9:
            failures.append(f"DP3_SILENCE_RUN_EXCEEDS_EXCEPTION_CAP_{max_exception_seconds:g}S:{last.get('shot_id')}:{run_seconds:g}")
        else:
            exceptions_used += 1
        run_seconds, run_shots = 0.0, []

    dialogue_seconds, total_seconds = 0.0, 0.0
    for sh in shots:
        secs = float(sh.get("target_seconds") or 0)
        total_seconds += secs
        if _has_dialogue(sh):
            dialogue_seconds += secs
            _close_run()
        else:
            run_seconds += secs
            run_shots.append(sh)
    _close_run()
    if exceptions_used > max_exceptions:
        failures.append(f"DP3_SILENCE_REASON_EXCEPTIONS_{exceptions_used}_OVER_{max_exceptions}")
    dialogue_ratio = round(dialogue_seconds / total_seconds, 4) if total_seconds else 0.0
    if total_seconds and dialogue_ratio < dialogue_ratio_min:
        failures.append(f"DP3_DIALOGUE_TIME_RATIO_{dialogue_ratio}_BELOW_{dialogue_ratio_min}")
    return failures, {"dialogue_time_ratio": dialogue_ratio, "silence_runs": silence_runs, "silence_reason_exceptions_used": exceptions_used}


def _still_wired(contract: dict[str, Any]) -> dict[str, Any]:
    """DP4/DP6/DP7 markers already enforced elsewhere — presence check only, never re-implements
    or blocks on their logic. DP8 (identity reference ordering) lives in S2/keyframe-binding
    artifacts, not the S1 contract, and is covered by tools/tests/test_nalu_identity_chain_fixes.py
    instead of here."""
    shots = contract.get("shots") or []
    dp4_present = any(bool(((sh.get("prompt_spec") or {}).get("action") or {}).get("performance")) for sh in shots if _has_dialogue(sh))
    dp6_present = any(sh.get("setup_id") or sh.get("payoff_of") or sh.get("result_of") for sh in shots)
    dp7_decl = contract.get("writer_selfcheck_seq29") if isinstance(contract.get("writer_selfcheck_seq29"), dict) else {}
    dp7_present = bool(contract.get("pressure_source") or contract.get("episode_payoff"))
    return {
        "DP4_performance_instruction_present": dp4_present,
        "DP6_setup_payoff_present": dp6_present,
        "DP7_pressure_source_fields_present": dp7_present,
        "DP7_rule8_authorized": bool(dp7_decl.get("rule8_authorized")),
    }


def evaluate(contract: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    rules = policy.get("rules") or {}
    shots = list(contract.get("shots") or [])
    failures: list[str] = []
    measurements: dict[str, Any] = {"shot_count": len(shots)}

    dp1 = rules.get("DP1_shot_scale_distribution") or {}
    if dp1.get("enabled") and shots:
        f, m = _dp1_shot_scale_distribution(shots, dp1)
        failures.extend(f); measurements["DP1"] = m

    dp2 = rules.get("DP2_reaction_shot_floor") or {}
    if dp2.get("enabled") and shots:
        f, m = _dp2_reaction_shot_floor(shots, dp2)
        failures.extend(f); measurements["DP2"] = m

    dp3 = rules.get("DP3_dialogue_continuity") or {}
    if dp3.get("enabled") and shots:
        f, m = _dp3_dialogue_continuity(shots, dp3)
        failures.extend(f); measurements["DP3"] = m

    measurements["still_wired"] = _still_wired(contract)

    decl = contract.get("direction_policy") if isinstance(contract.get("direction_policy"), dict) else {}
    enforced = bool(decl.get("enforced"))
    status = "PASS" if not failures else "FAIL"
    return {
        "schema": SCHEMA, "episode": contract.get("episode"),
        "authority": "Roger 2026-09-25, codex_docs/ROGER-20260925-NALU-LINE-OPTIMIZATION.md",
        "declared": bool(decl), "enforced": enforced,
        "status": status, "failures": failures, "warnings": [], "measurements": measurements,
        "note": "S1 self-check; enforced only when the contract declares direction_policy.enforced=true. "
                "A missing DIRECTION_POLICY_V1.json (empty `rules`) makes every DPn check a no-op.",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--policy", default=None, help="path to DIRECTION_POLICY_V1.json; default: none (all rules off)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    try:
        contract = json.loads(Path(a.contract).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"UNREADABLE_CONTRACT:{exc}", file=sys.stderr)
        return 2
    policy = load_policy(Path(a.policy)) if a.policy else {}
    report = evaluate(contract, policy)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "enforced": report["enforced"], "failures": len(report["failures"])}, ensure_ascii=False))
    return 3 if (report["enforced"] and report["status"] == "FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
