#!/usr/bin/env python3
"""speech_rate_check.py — SUPERVISOR_ORDERS seq=29 规则 6 (Roger 2026-09-18): 语速要了就要查.

Per unit, the realised characters-per-second is computed from the existing ASR segments (no new
capture) and compared with the director's per-shot ``dialogue_delivery.chinese_characters_per_second``:

  ratio = measured / target
  ratio < 0.8                       → SPEECH_RATE_UNDER_TARGET       (MINOR: recorded, counts in the defect budget)
  ratio < 0.7 or a hook/conflict line → SPEECH_RATE_UNDER_TARGET_BLOCKER (BLOCKER: existing reroll flow; the reroll
                                        prompt MUST change the performance instruction, not just the number)
Episode level: mean realised cps < 4.5 is written to CHECKPOINT.md for the S8 screening.
"""
from __future__ import annotations

import re
from typing import Any

MINOR_RATIO = 0.8
BLOCKER_RATIO = 0.7
EPISODE_MEAN_MIN_CPS = 4.5
DEFAULT_TARGET_CPS = 4.9
CONFLICT_EMOTIONS = {"急", "怒", "惧", "慌", "狠", "惊"}
_CJK = re.compile(r"[一-鿿]")


def cjk_count(text: str) -> int:
    return len(_CJK.findall(str(text or "")))


def shot_targets(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """shot_id → {cps, hook, conflict} from the generation contract."""
    out: dict[str, dict[str, Any]] = {}
    for shot in contract.get("shots") or []:
        spec = shot.get("prompt_spec") or {}
        if not str(spec.get("dialogue") or "").strip():
            continue
        perf = ((spec.get("action") or {}).get("performance") or {}) if isinstance((spec.get("action") or {}).get("performance"), dict) else {}
        flags = shot.get("pacing_flags") or {}
        out[str(shot.get("shot_id"))] = {
            "cps": float((shot.get("dialogue_delivery") or {}).get("chinese_characters_per_second") or DEFAULT_TARGET_CPS),
            "hook": bool(flags.get("hook")),
            "conflict": bool(flags.get("conflict_line")) or str(perf.get("emotion") or "") in CONFLICT_EMOTIONS,
        }
    return out


def measure_unit(unit_id: str, segments: list[dict[str, Any]], expected_dialogue: list[dict[str, Any]],
                 targets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Realised cps over the unit's real speech segments vs the mean director target of its lines."""
    rows = [s for s in segments or [] if isinstance(s, dict)]
    chars = sum(cjk_count(s.get("text")) for s in rows)
    seconds = sum(max(0.0, float(s.get("end") or 0) - float(s.get("start") or 0)) for s in rows)
    shot_ids = [str(r.get("shot_id")) for r in expected_dialogue or [] if r.get("shot_id")]
    known = [targets[s] for s in shot_ids if s in targets]
    target = (sum(t["cps"] for t in known) / len(known)) if known else (DEFAULT_TARGET_CPS if shot_ids else None)
    hook_or_conflict = any(t["hook"] or t["conflict"] for t in known)
    result: dict[str, Any] = {"check": "speech_rate_vs_director_target", "authority": "SUPERVISOR_ORDERS seq=29 规则 6",
                              "unit_id": unit_id, "spoken_chars": chars, "speech_seconds": round(seconds, 3),
                              "measured_cps": round(chars / seconds, 3) if seconds > 0 and chars else None,
                              "target_cps": round(target, 3) if target else None, "shot_ids": shot_ids,
                              "hook_or_conflict_line": hook_or_conflict, "tier": "N/A", "code": None, "status": "PASS"}
    if not expected_dialogue or not target or result["measured_cps"] is None:
        result["tier"] = "NOT_APPLICABLE" if not expected_dialogue else "UNMEASURED"
        return result
    ratio = result["measured_cps"] / target
    result["ratio"] = round(ratio, 3)
    if ratio < BLOCKER_RATIO or (ratio < MINOR_RATIO and hook_or_conflict):
        result.update(tier="BLOCKER", code="SPEECH_RATE_UNDER_TARGET_BLOCKER", status="FAIL",
                      required_reroll_change="PERFORMANCE_INSTRUCTION_CHANGE (规则 6: 不许只改字/秒数字)")
    elif ratio < MINOR_RATIO:
        result.update(tier="MINOR", code="SPEECH_RATE_UNDER_TARGET", status="PASS_WITH_NOTE")
    else:
        result["tier"] = "OK"
    return result


def episode_summary(unit_results: list[dict[str, Any]]) -> dict[str, Any]:
    chars = sum(int(r.get("spoken_chars") or 0) for r in unit_results)
    seconds = sum(float(r.get("speech_seconds") or 0) for r in unit_results)
    mean = round(chars / seconds, 3) if seconds > 0 else None
    return {"authority": "SUPERVISOR_ORDERS seq=29 规则 6", "units_measured": sum(1 for r in unit_results if r.get("measured_cps") is not None),
            "mean_measured_cps": mean, "episode_mean_min_cps": EPISODE_MEAN_MIN_CPS,
            "below_episode_min": (mean is not None and mean < EPISODE_MEAN_MIN_CPS),
            "minor": [r["unit_id"] for r in unit_results if r.get("tier") == "MINOR"],
            "blocker": [r["unit_id"] for r in unit_results if r.get("tier") == "BLOCKER"],
            "checkpoint_line": (f"- 规则 6 语速：全片实测均值 {mean} 字/秒（< {EPISODE_MEAN_MIN_CPS}，S8 看片对照）" if mean is not None and mean < EPISODE_MEAN_MIN_CPS
                                else (f"- 规则 6 语速：全片实测均值 {mean} 字/秒" if mean is not None else "- 规则 6 语速：无实测"))}
