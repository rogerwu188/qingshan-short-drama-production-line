#!/usr/bin/env python3
"""Build the immutable 20-line E40 exact-dialogue audio reference plan."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_REMAKE_DIALOGUE_SUBTITLE_CONTRACT_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_20_V2.json"

VOICES = {
    "陈迹": ("clone_20251011_081924_812352", "寒玉孤音(蓝忘机)", "中低冷稳、气息克制、自然普通话、非旁白腔"),
    "云妃": ("clone_20251022_101843_460135", "御姐语录", "成熟从容、尾音缓、藏威、自然普通话、非旁白腔"),
    "云羊": ("clone_20251215_082253_725049", "不羁青年", "少年警觉、克制讥刺、自然普通话、非旁白腔"),
    "阿栓": ("clone_20251030_080949_242818", "急语风声", "童声未褪、急切发颤、自然普通话、非旁白腔"),
}

UNIT_KEYS = {
    "E40-DIA-001": "E40-FP-R01-YUNFEI-A-V1", "E40-DIA-002": "E40-FP-R01-YUNFEI-A-V1", "E40-DIA-003": "E40-FP-R01-YUNFEI-A-V1",
    "E40-DIA-004": "E40-FP-R01-CHENJI-B-V1", "E40-DIA-005": "E40-FP-R02-CHENJI-A-V1", "E40-DIA-006": "E40-FP-R02-CHENJI-A-V1",
    "E40-DIA-007": "E40-FP-R02-CHENJI-A-V1", "E40-DIA-008": "E40-FP-R03-CHENJI-A-V1", "E40-DIA-009": "E40-FP-R03-YUNFEI-B-V1",
    "E40-DIA-010": "E40-FP-R04-CHENJI-A-V1", "E40-DIA-011": "E40-FP-R04-YUNFEI-B-V1", "E40-DIA-012": "E40-FP-R04-YUNFEI-B-V1",
    "E40-DIA-013": "E40-FP-R05-CHENJI-A-V1", "E40-DIA-014": "E40-FP-R05-CHENJI-A-V1", "E40-DIA-015": "E40-FP-R06-ASHUAN-A-V1",
    "E40-DIA-016": "E40-FP-R07-YUNYANG-A-V1", "E40-DIA-017": "E40-FP-R08-YUNFEI-A-V1", "E40-DIA-018": "E40-FP-R08-CHENJI-B-V1",
    "E40-DIA-019": "E40-FP-R08-YUNFEI-C-V1", "E40-DIA-020": "E40-FP-R08-YUNFEI-C-V1",
}


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    items = []
    for row in contract["rows"]:
        dialogue_id = row["dialogue_id"]
        unit_id = UNIT_KEYS[dialogue_id]
        voice_id, voice_name, voice_style = VOICES[row["speaker"]]
        emotion = f"{row['emotion']}；{voice_style}；逐字准确，不增删重复"
        if dialogue_id == "E40-DIA-005":
            emotion = "沉，随四霜印逐一落定；说完‘火场’后明确停顿，再把‘活口’作为独立重音词组清楚说出，‘活’读 huó 第二声并略微扬调，禁止与前一个‘火场’连读，禁止读成 huǒ；冷静克制、锋利、自然普通话、非旁白腔；逐字准确，不增删重复"
        items.append({
            "audio_key": f"{unit_id}-{dialogue_id}-EXACT-AUDIO-V1",
            "unit_id": unit_id,
            "dialogue_id": dialogue_id,
            "speaker": row["speaker"],
            "text": row["spoken_text"],
            "voice_id": voice_id,
            "voice_name": voice_name,
            "emotion": emotion,
            "speed": 1.0,
            "purpose": "SEEDANCE_SAME_TASK_EXACT_DIALOGUE_REFERENCE_ONLY_NOT_POST_DUB",
            "state": "INTENT_REQUIRED_TRANSACTION_NOT_YET_POSTED",
            "provider_post_allowed": False,
        })
    payload = {
        "schema": "qingshan.e40.full_performance_exact_dialogue_audio_reference_plan.v2",
        "episode": "E40",
        "status": "COMPLETE_20_LINE_TRANSACTION_FIRST_AUDIO_REFERENCE_PLAN",
        "purpose": "INPUT_REFERENCE_FOR_SAME_SEEDANCE_TASK_NOT_POST_DUB",
        "postproduction_replacement_forbidden": True,
        "authorization_refs": ["ROGER_AUTONOMOUS_ROUTINE_PRODUCTION_CHOICES_20260814", "ROGER-20260821-E40-REBUILD-BUDGET-5000"],
        "audio_count": len(items),
        "items": items,
    }
    if len(items) != 20 or [row["dialogue_id"] for row in items] != [f"E40-DIA-{index:03d}" for index in range(1, 21)]:
        raise SystemExit("CANONICAL_DIALOGUE_20_OF_20_ORDER_FAIL")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "audio_count": 20, "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
