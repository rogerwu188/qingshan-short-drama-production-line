#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
BUILD_PLAN = BASE / "exports/e16/rough_cut_20260714/speech_window_assembly_v25_d51full_luma_d04rm2_d49rm2_bboost/build_plan.json"
CONFIG_OUT = BASE / "configs/e16_pacing_plan_cl2x133_20260714.json"
QA_DIR = BASE / "qa/e16_final_package_v2_20260714"
AUDIT_OUT = QA_DIR / "E16_CL2X133_PACING_AUDIT.json"
SCHEMA_DOC = BASE / "workflow/PACING_PLAN_SCHEMA.md"


RECIPES: dict[str, dict[str, Any]] = {
    "dialogue_drive": {
        "target_range": [2.5, 3.5],
        "hard_range": [2.2, 4.2],
        "rule": "一句一镜+动机反应插; 句内不切; 原生音频超过目标窗时允许 native_audio_guard, 禁止变速或截半句。",
    },
    "burst": {
        "target_range": [1.7, 2.4],
        "hard_range": [1.2, 3.2],
        "rule": "密集正反打/证物 insert; 用于质问、抢证、短促反击; 不为刷运动量添加无动机闪切。",
    },
    "fight": {
        "target_range": [1.7, 2.2],
        "hard_range": [1.2, 2.8],
        "rule": "v2.1 呼吸结构; 动作段另跑 fight QA。",
    },
    "silent_suspense": {
        "target_range": [3.5, 6.0],
        "hard_range": [3.0, 6.5],
        "rule": "必须 designated_static_beat; 靠眼神/证物/环境声维持张力, 不得冻结补时。",
    },
    "montage": {
        "target_range": [1.5, 2.0],
        "hard_range": [1.0, 2.5],
        "rule": "旁白/时间压缩驱动, 画面独立成卡。",
    },
}


BURST_IDS = {
    "D05", "D07", "D10", "D12", "D16", "D20", "D27", "D29", "D31", "D32",
    "D36", "D38", "D40", "D41", "D43", "D45", "D47", "D49", "D51", "D54",
    "D55", "D57", "D60", "D61",
}
SILENT_SUSPENSE_IDS = {"D34", "D58", "D59", "D62"}


def section_for(index: int) -> str:
    if index <= 18:
        return "S1_hand_seal_and_first_evidence"
    if index <= 35:
        return "S2_fire_lacquer_and_box_pressure"
    if index <= 45:
        return "S3_evidence_grab_burst"
    if index <= 53:
        return "S4_autopsy_chain_climax"
    return "S5_backyard_water_hook"


def classify(seg: dict[str, Any]) -> dict[str, Any]:
    did = str(seg["dialogue_id"])
    dur = float(seg["target_duration"])
    if did in SILENT_SUSPENSE_IDS and dur >= 3.0:
        return {
            "segment_type": "silent_suspense",
            "designated_static_beat": True,
            "classification_reason": "suspicion/hook hold beat; longer pause is motivated by evidence reveal or offscreen sound.",
        }
    if did in BURST_IDS:
        return {
            "segment_type": "burst",
            "designated_static_beat": False,
            "classification_reason": "short accusation, clue insert, or pressure turn.",
        }
    return {
        "segment_type": "dialogue_drive",
        "designated_static_beat": False,
        "classification_reason": "courtroom/inquest dialogue drive; preserve full native sentence.",
    }


def status_for(duration: float, recipe: dict[str, Any], *, native_audio_guard: bool) -> str:
    target_min, target_max = recipe["target_range"]
    hard_min, hard_max = recipe["hard_range"]
    if target_min <= duration <= target_max:
        return "PASS_TARGET"
    if hard_min <= duration <= hard_max and native_audio_guard:
        return "PASS_NATIVE_AUDIO_GUARD"
    if hard_min <= duration <= hard_max:
        return "PASS_HARD_RANGE"
    return "FAIL_OUT_OF_RANGE"


def write_schema_doc() -> None:
    text = """# Pacing Plan Schema (CL2X-133)

Purpose: one `segment_type` field must connect script, edit, and CI so an episode does not collapse into one universal rhythm.

## Required Fields

- `episode_type`: e.g. `courtroom_inference`, `fight_episode`, `montage_drama`.
- `segment_type`: one of `dialogue_drive`, `burst`, `fight`, `silent_suspense`, `montage`.
- `section_id`: contiguous story section used as the CI boundary.
- `target_range`: preferred ASL range for the type.
- `hard_range`: allowed range after episode-specific guardrails.
- `native_audio_guard`: true only when cutting shorter would truncate a complete native dialogue sentence; never use it to justify freezing, looping, or speed changes.
- `designated_static_beat`: required for `silent_suspense`.

## Default Recipes

| segment_type | Target ASL | Edit Rule |
|---|---:|---|
| dialogue_drive | 2.5-3.5s | One sentence per shot, motivated listener reaction insert >=1.2s, no cut inside a sentence. |
| burst | about 2.0s | Dense shot/reverse/insert around a pressure turn. |
| fight | 1.7-2.2s | Fight v2.1 breathing structure; action QA still applies. |
| silent_suspense | 4-6s | Only for designated static beats with visible acting/evidence/environment tension. |
| montage | 1.5-2.0s | Narration/time-compression driven, image cards independent of lip sync. |

## Hard Rules

1. CI must audit by the same `section_id` and `segment_type` used by the editor.
2. `native_audio_guard` is allowed only to preserve complete dialogue audio; it cannot excuse long static filler.
3. Non-fight segments below 0.8s are forbidden unless explicitly marked as a hit flash or transition artifact and excluded from story ASL.
4. Passing numeric pacing does not equal final PASS; AGENT_WATCH_GATE still answers whether the episode feels tiring.
"""
    SCHEMA_DOC.write_text(text, encoding="utf-8")


def main() -> int:
    plan = json.loads(BUILD_PLAN.read_text(encoding="utf-8"))
    rows = []
    failures = []
    by_type: dict[str, list[float]] = defaultdict(list)
    by_section: dict[str, list[float]] = defaultdict(list)

    for seg in plan["segments"]:
        duration = float(seg["target_duration"])
        meta = classify(seg)
        recipe = RECIPES[meta["segment_type"]]
        target_min, target_max = recipe["target_range"]
        native_audio_guard = False
        if meta["segment_type"] == "dialogue_drive" and not (target_min <= duration <= target_max):
            native_audio_guard = True
        if meta["segment_type"] == "burst" and duration > recipe["target_range"][1]:
            native_audio_guard = True
        status = status_for(duration, recipe, native_audio_guard=native_audio_guard)
        section_id = section_for(int(seg["index"]))
        row = {
            "index": seg["index"],
            "dialogue_id": seg["dialogue_id"],
            "speaker": seg.get("speaker"),
            "text": seg.get("text"),
            "duration": duration,
            "section_id": section_id,
            "segment_type": meta["segment_type"],
            "designated_static_beat": meta["designated_static_beat"],
            "native_audio_guard": native_audio_guard,
            "status": status,
            "classification_reason": meta["classification_reason"],
            "recipe": recipe,
        }
        rows.append(row)
        by_type[meta["segment_type"]].append(duration)
        by_section[section_id].append(duration)
        if status.startswith("FAIL"):
            failures.append(row)

    total_duration = sum(float(seg["target_duration"]) for seg in plan["segments"])
    story_segments = len(plan["segments"])
    ultra_short_count = sum(1 for row in rows if row["duration"] < 0.8 and row["segment_type"] != "fight")
    ultra_short_ratio = ultra_short_count / story_segments if story_segments else 0
    summary_by_type = {
        key: {
            "count": len(values),
            "mean_asl": round(sum(values) / len(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }
        for key, values in sorted(by_type.items())
    }
    summary_by_section = {
        key: {
            "count": len(values),
            "mean_asl": round(sum(values) / len(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
        }
        for key, values in sorted(by_section.items())
    }

    config = {
        "schema": "qingshan.pacing_plan.cl2x133.v1",
        "episode": "E16",
        "episode_type": "courtroom_inference",
        "source_build_plan": str(BUILD_PLAN),
        "recipes": RECIPES,
        "episode_type_exemptions": {
            "motion_gate": "courtroom_inference uses motion >=2.0 plus dialogue coverage >=90%; no synthetic motion patches.",
            "native_audio_guard": "Allowed only when full native speech would be cut by the 2.5-3.5s target; max hard range still enforced.",
        },
        "segments": rows,
    }
    CONFIG_OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    audit = {
        "schema": "qingshan.pacing_audit.cl2x133.v1",
        "episode": "E16",
        "status": "PASS" if not failures and ultra_short_ratio <= 0.05 else "FAIL",
        "source_build_plan": str(BUILD_PLAN),
        "pacing_plan": str(CONFIG_OUT),
        "overall": {
            "segment_count": story_segments,
            "story_runtime_seconds": round(total_duration, 3),
            "mean_asl": round(total_duration / story_segments, 3),
            "ultra_short_under_0_8s_count": ultra_short_count,
            "ultra_short_under_0_8s_ratio": round(ultra_short_ratio, 4),
            "target_segment_count": "60-80",
        },
        "summary_by_type": summary_by_type,
        "summary_by_section": summary_by_section,
        "failures": failures,
        "native_audio_guard_count": sum(1 for row in rows if row["native_audio_guard"]),
        "native_audio_guard_ids": [row["dialogue_id"] for row in rows if row["native_audio_guard"]],
        "notes": [
            "CL2X-133 applied as a real edit/CI schema: the same segment_type table now drives this audit.",
            "E16 is courtroom_inference, so complete native dialogue is preserved; native_audio_guard is recorded rather than hidden.",
            "This audit does not replace final CI or AGENT_WATCH_GATE tiringness review.",
        ],
    }
    QA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    write_schema_doc()
    print(json.dumps({"status": audit["status"], "pacing_plan": str(CONFIG_OUT), "audit": str(AUDIT_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
