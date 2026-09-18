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
    # Timing basis (2026-09-18, first E06 data): whisper SEGMENT bounds are padded to the VAD chunk
    # (a 4-character line measured over a 7.6 s wind segment; short lines land on 1.00 / 2.00 s), which
    # under-measures cps and would trigger rerolls on measurement noise.  When the ASR rows carry
    # per-word timestamps the realised speech time is the sum of the word spans (authored pauses such as
    # 「……」 and silence inside the chunk are then excluded); otherwise fall back to the segment spans and
    # say so in the record.
    word_rows = [w for s in rows for w in (s.get("words") or []) if isinstance(w, dict)]
    if word_rows:
        seconds = sum(max(0.05, float(w.get("end") or 0) - float(w.get("start") or 0)) for w in word_rows)
        timing_basis = "WORD_TIMESTAMPS_SUM"
    else:
        seconds = sum(max(0.0, float(s.get("end") or 0) - float(s.get("start") or 0)) for s in rows)
        timing_basis = "SEGMENT_BOUNDS_PADDED"
    shot_ids = [str(r.get("shot_id")) for r in expected_dialogue or [] if r.get("shot_id")]
    known = [targets[s] for s in shot_ids if s in targets]
    target = (sum(t["cps"] for t in known) / len(known)) if known else (DEFAULT_TARGET_CPS if shot_ids else None)
    hook_or_conflict = any(t["hook"] or t["conflict"] for t in known)
    result: dict[str, Any] = {"check": "speech_rate_vs_director_target", "authority": "SUPERVISOR_ORDERS seq=29 规则 6",
                              "unit_id": unit_id, "spoken_chars": chars, "speech_seconds": round(seconds, 3),
                              "timing_basis": timing_basis,
                              "measured_cps": round(chars / seconds, 3) if seconds > 0 and chars else None,
                              "target_cps": round(target, 3) if target else None, "shot_ids": shot_ids,
                              "hook_or_conflict_line": hook_or_conflict, "tier": "N/A", "code": None, "status": "PASS"}
    if not expected_dialogue or not target or result["measured_cps"] is None:
        result["tier"] = "NOT_APPLICABLE" if not expected_dialogue else "UNMEASURED"
        return result
    ratio = result["measured_cps"] / target
    result["ratio"] = round(ratio, 3)
    # Authored trailing-off (SUPERVISOR_ORDERS seq=31 standing rule C, applied 2026-09-18 seq=33): a line the
    # writer ends with 「……」 is directed to break off (愣住 / 哽咽), so a slow realised rate is the performance,
    # not a dragged delivery.  Recorded as a note, never as a reroll — unless the line is a hook/conflict line.
    authored_trailing_off = any(str(r.get("spoken_text") or "").rstrip("」”\"' ").endswith(("……", "…"))
                                for r in expected_dialogue or [])
    result["authored_trailing_off"] = authored_trailing_off
    hook_line = any(t["hook"] for t in known)
    # the exemption never covers an episode hook line; a conflict-flagged line that is authored to break
    # off (陆泽 愣住「小秦，你这是……」) is still the directed performance
    if ratio < BLOCKER_RATIO and authored_trailing_off and not hook_line:
        result.update(tier="MINOR", code="SPEECH_RATE_UNDER_TARGET_AUTHORED_TRAILING_OFF", status="PASS_WITH_NOTE",
                      note="line authored to trail off (……); slow rate is the directed performance (seq=31 rule C)")
    elif ratio < BLOCKER_RATIO or (ratio < MINOR_RATIO and hook_or_conflict):
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
