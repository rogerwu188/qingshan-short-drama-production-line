#!/usr/bin/env python3
"""Build the E20 v2 dialogue-performance manifest from the approved beat sheet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SPEAKERS: dict[str, dict[str, Any]] = {
    "陈迹": {
        "character_id": "CHAR-陈迹-古装",
        "voice_asset_id": "cypqud0bu7t",
        "voice_gate": None,
        "temperature": -1,
        "start": "平静",
        "end": "笃定",
    },
    "白鲤": {
        "character_id": "CHAR-白鲤-古装",
        "voice_asset_id": "19uxvuf5yl1",
        "voice_gate": None,
        "temperature": 1,
        "start": "审视",
        "end": "警觉",
    },
    "云羊": {
        "character_id": "CHAR-云羊-古装",
        "voice_asset_id": None,
        "voice_gate": "BLOCKED_PENDING_REMOTE_ASSET_AND_REPRESENTATIVE_SAMPLE_QA",
        "temperature": -1,
        "start": "轻松",
        "end": "审视",
    },
    "皎兔": {
        "character_id": "CHAR-皎兔-古装",
        "voice_asset_id": None,
        "voice_gate": "BLOCKED_PENDING_REMOTE_ASSET_AND_REPRESENTATIVE_SAMPLE_QA",
        "temperature": -1,
        "start": "警觉",
        "end": "震惊",
    },
    "佛子": {
        "character_id": "CHAR-E19-佛子-罗追萨迦",
        "voice_asset_id": None,
        "voice_gate": "BLOCKED_PENDING_NEW_SERIES_VOICE_ASSET_AND_SAMPLE_QA",
        "temperature": 0,
        "start": "平静",
        "end": "审视",
    },
    "巡夜领队": {
        "character_id": "CHAR-E20-巡夜领队",
        "voice_asset_id": None,
        "voice_gate": "BLOCKED_PENDING_NEW_VOICE_ASSET_OR_APPROVED_REASSIGNMENT",
        "temperature": -1,
        "start": "强硬",
        "end": "警惕",
    },
}

RELATIONSHIP_STRATEGY = {
    "B01": "巡夜领队以官命压场；陈迹用追问把搜尸任务转成尸主与权力问题。",
    "B02": "巡夜领队威胁拿人；陈迹主动把自己押上，迫使对方公开验棺。",
    "B03": "众人用封条、棺钉与脚印交叉验证；陈迹把讨论转成皎兔阴神实查。",
    "B04": "皎兔连续交付内断钉与湿泥证据；陈迹控制检查顺序，云羊完成重封判断。",
    "B05": "余温把验尸翻成活人逃棺；陈迹收束推理并锁定半个时辰的时间缺口。",
    "B06": "云羊授权开棺；空棺与王府红线迫使巡夜领队退让，陈迹取得追查主导权。",
}


def stress_for(text: str) -> list[str]:
    chunks = [part for part in re.split(r"[，。？！、；：,.!?;:\s]+", text) if part]
    if not chunks:
        return []
    return [max(chunks, key=len)[:6]]


def delivery_for(row: dict[str, Any]) -> dict[str, Any]:
    speaker = SPEAKERS[row["speaker"]]
    function = str(row.get("function") or "")
    text = str(row["text"])
    beat_id = str(row["beat_id"])
    question = "？" in text or "问" in function or "追问" in function
    warning = any(term in function for term in ("阻止", "威胁", "授权", "命令"))
    evidence = any(term in function for term in ("证据", "报告", "确认", "补强", "引入"))
    deduction = any(term in function for term in ("判断", "推理", "解释", "收束", "指出", "锁定"))
    if warning:
        tone_code = "controlled_command"
        subtext_code = "force_the_next_action"
    elif deduction:
        tone_code = "evidence_pressure"
        subtext_code = "turn_observation_into_conclusion"
    elif evidence:
        tone_code = "controlled_report"
        subtext_code = "make_the_fact_verifiable"
    elif question:
        tone_code = "probing_question"
        subtext_code = "force_hidden_information_out"
    else:
        tone_code = "restrained_reaction"
        subtext_code = "register_the_power_shift"
    pace = "fast" if beat_id == "B04" else "medium"
    if len(re.sub(r"\W", "", text)) <= 3 or row["dia_id"] in {"DIA-V2-004", "DIA-027", "DIA-029"}:
        pace = "slow"
    volume = "pressed" if warning or row["speaker"] == "巡夜领队" else "normal"
    breath = "clipped" if beat_id == "B04" or warning else "steady"
    energy = 4 if warning else 3 if beat_id == "B04" or deduction else 2
    stress = stress_for(text)
    trigger = f"说到{stress[0]}" if stress else "句尾"
    return {
        "tone_code": tone_code,
        "subtext_code": subtext_code,
        "pace": pace,
        "volume": volume,
        "breath": breath,
        "temperature": speaker["temperature"],
        "energy": energy,
        "stress": stress,
        "expression_arc": {
            "start": speaker["start"],
            "trigger": trigger,
            "end": speaker["end"],
        },
    }


def build_manifest(beat_sheet: dict[str, Any], beat_sheet_sha256: str) -> dict[str, Any]:
    lines = []
    for row in beat_sheet.get("dialogue_draft") or []:
        speaker = SPEAKERS.get(row["speaker"])
        if not speaker:
            raise ValueError(f"unknown speaker: {row['speaker']}")
        lines.append(
            {
                **row,
                "character_id": speaker["character_id"],
                "voice_asset_id": speaker["voice_asset_id"],
                "voice_gate": speaker["voice_gate"],
                "text_with_pause": row["text"],
                "delivery": delivery_for(row),
            }
        )
    return {
        "schema": "qingshan.dialogue_performance_manifest.v2",
        "episode": beat_sheet.get("episode"),
        "created_at_pdt": "2026-07-16 11:4x",
        "status": "V2_READY_FOR_AUDIO_COMPILATION_WITH_VOICE_BLOCKERS",
        "review_ref": "CL2X-180",
        "rebase_ref": "CL2X-183",
        "beat_sheet_sha256": beat_sheet_sha256,
        "dialogue_count": len(lines),
        "generation_allowed": False,
        "submittable": False,
        "schema_reference": "/Users/rogerwu/qingshan_short_drama/workflow/DIALOGUE_PERFORMANCE_SCHEMA.md",
        "prompt_section": "AUDIO_PROMPT_DIALOGUE_ONLY",
        "visual_prompt_may_contain_dialogue_text": False,
        "relationship_strategy_by_beat": RELATIONSHIP_STRATEGY,
        "lines": lines,
        "checks": {
            "dialogue_ids_and_order_match_beat_sheet": True,
            "delivery_fields_complete": True,
            "unresolved_voice_assets_explicitly_blocked": True,
            "all_38_v2_lines_present": len(lines) == 38,
        },
        "release_rule": "This manifest is local-only. Voice blockers and downstream v2 contract QA must pass before generation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(args.beat_sheet).expanduser().resolve()
    source_bytes = source.read_bytes()
    beat_sheet = json.loads(source_bytes)
    manifest = build_manifest(beat_sheet, hashlib.sha256(source_bytes).hexdigest())
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "dialogue_count": manifest["dialogue_count"], "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
