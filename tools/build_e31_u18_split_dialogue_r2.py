#!/usr/bin/env python3
"""Build a changed-input three-shot repair for E31 U18 dialogue blending."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/video_performance_v1"
SOURCE_CONFIG = BASE / "E31_VIDEO_BATCH_DIALOGUE_READY_V1.json"
CONFIG = BASE / "E31_VIDEO_BATCH_U18_SPLIT_DIALOGUE_R2.json"
PROMPT_DIR = BASE / "prompts"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_text(part: str, duration: int, speaker: str, line: str) -> str:
    shared = [
        f"《青山》E31《王府风暴》U18-{part}，Seedance 2.0 Pro 四模态表演生成，{duration}秒，9:16，720p，原速连续表演。",
        "【实体绑定】陈迹[[char_chenji]]、云羊[[char_yunyang]]、火后庭院[[scene_e31_s05]]、越级骨牌[[prop_e31_token]]。",
        "【生成范式】@图片1只锁人物身份、火后庭院、骨牌造型与空间方向；@音频1只驱动本镜唯一说话人。不得让另一人物串词、抢词或补说前后镜台词。",
        "【色彩与动机光】残火暖橙映面，雪夜环境冷蓝；人物动作的力量作用到环境介质，火苗、薄烟、衣摆只响应一次并自然衰减。",
        f"【唯一对白】0.45秒开始，{speaker}严格逐字说完@音频1对应台词；台词只在后续分镜大括号声明一次，口型、气息、停连、眼神和表情同步；本镜其他人物全程闭口。",
        "【声音】必须保留@音频1原生中文普通话口型对白及庭院残火、衣料、风雪现场声；禁止BGM、旁白、额外对白和重复台词。",
        "【负面约束】禁止字幕、水印、Logo、可读文字；禁止串台、吞句、改词、重复前后镜台词、换脸、分身、瞬移、道具换手、慢放、停帧、循环、周期重复和静帧微动。",
    ]
    if part == "A":
        action = [
            f"镜头1【双人中景缓慢推向云羊】陈迹右手托住骨牌边缘递出，云羊左掌从下方接住并翻面，骨牌归云羊持有；云羊看到凹刻后呼吸骤停，眉峰收紧，眼神从疑惑转为震骇。{{{speaker}：{line}}}<骨牌轻触掌心、衣料轻响、残火噼啪、风雪底噪>",
            "【连续物理链】0-1.2秒：陈迹托牌向前，云羊掌心接触并承重；1.2-2秒：陈迹松手，云羊翻面，归属完成且不再跳变；2-5.6秒：云羊指腹沿刻痕短距离摩擦，同时说完@音频1；5.6-6秒：他抬眼看陈迹，握牌手略收紧。",
            "【表演目的】观众必须从云羊的骤然变色和确认刻痕看懂：这枚印来自他无权接近的更高层级。",
        ]
    elif part == "B":
        action = [
            f"镜头1【陈迹近景反打，云羊持牌虚化在画面边缘】陈迹不碰骨牌，先看云羊手中印纹，再把视线移向后景残火；下颌微收，语气冷静，眼神像在把两条权力链拆开比较。{{{speaker}：{line}}}<衣料轻响、残火噼啪、压低呼吸、风雪底噪>",
            "【连续物理链】0-0.5秒：陈迹视线从骨牌移向残火；0.5-3.7秒：身体只作轻微侧转并完整说完@音频1，双手始终不碰道具；3.7-4秒：视线回到云羊，判断落定。",
            "【表演目的】观众必须看懂：翻名册的是内部执行者，发令者却高到直属上司无法触及，两只手属于不同权力层级。",
        ]
    else:
        action = [
            f"镜头1【云羊持牌近景，陈迹在反打边缘保持闭口】云羊把骨牌举到残火侧光中确认凹刻，瞳孔轻缩，震骇转为对自己组织的怀疑；他最后把骨牌压低到胸前，不遮住印纹。{{{speaker}：{line}}}<骨牌摩擦指腹、衣料轻响、残火噼啪、风雪底噪>",
            "【连续物理链】0-0.6秒：云羊举牌进入侧光；0.6-5.5秒：目光锁住印纹并完整说完@音频1，手腕稳定、骨牌归属不变；5.5-6秒：五指轻收，骨牌压低，停在胸前。",
            "【表演目的】观众必须从他的回忆、迟疑和握紧动作看懂：此印本应只出现在最高机密令匣，如今落在现场本身就不合常理。",
        ]
    return "\n".join(shared[:4] + [shared[4]] + action + shared[5:]) + "\n"


def main() -> int:
    source = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    parent = next(row for row in source["tasks"] if row["unit_id"] == "E31-CW-U18")
    dialogue = parent["dialogue"]
    audio = {row["dia_id"]: row for row in parent["dialogue_audio_assets"]}
    plan = [
        ("A", 6, dialogue[0]),
        ("B", 4, dialogue[1]),
        ("C", 6, dialogue[2]),
    ]
    tasks = []
    for part, duration, row in plan:
        source_id = f"E31-CW-U18-{part}"
        prompt = PROMPT_DIR / f"{source_id}-PERFORMANCE-R2.txt"
        prompt.write_text(prompt_text(part, duration, row["speaker"], row["spoken_text"]), encoding="utf-8")
        asset = dict(audio[row["dia_id"]])
        asset["audio_slot"] = "@音频1"
        asset["sha256"] = sha256(ROOT / asset["path"])
        task = {
            **parent,
            "task_key": f"{source_id}-PERFORMANCE-R2",
            "source_id": source_id,
            "unit_id": source_id,
            "visual_zone": source_id,
            "parent_unit_id": "E31-CW-U18",
            "batch_id": "E31-U18-SPLIT-DIALOGUE-R2",
            "duration": duration,
            "duration_seconds": duration,
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": duration,
                "rationale": "One natural speaker-performance beat with one exact reference audio; no cross-speaker compression.",
                "edit_policy": "End after the exact line and physical reaction land; never pad, slow or loop.",
            },
            "prompt_file": str(prompt.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt),
            "dialogue": [row],
            "reference_audios": [asset["path"]],
            "dialogue_audio_assets": [asset],
            "dialogue_audio_coverage": {"required": 1, "bound": 1, "status": "PASS"},
            "performance_spec": {
                **parent["performance_spec"],
                "unit_id": source_id,
                "duration_seconds": duration,
                "motion_beats": [{
                    "start_seconds": 0.0,
                    "end_seconds": float(duration),
                    "subject": row["speaker"],
                    "action": "One continuous role-bound speaking performance derived from the changed-input R2 prompt.",
                    "contact_point": "The declared bone-token hand contact remains stable for the whole shot.",
                    "direction": "Camera and body direction follow the R2 prompt without crossing the established axis.",
                    "end_state": "The exact line is complete and the character's conclusion is visibly readable.",
                    "intent": "Reveal the two-level command chain without cross-speaker dialogue blending.",
                    "visible_causality": "Token inspection changes expression, then spoken inference lands, then the reaction settles.",
                    "expression": "Speaker-specific suspicion, shock or cold deduction as declared in the R2 prompt.",
                    "viewer_read": "The audience understands who speaks, what evidence they inspect, and why the conclusion matters.",
                }],
            },
            "retry_reason": "Final encoded ASR proved cross-speaker blending and omissions in the prior three-audio 14-second unit; R2 changes the actual input to one speaker and one audio per natural reaction shot.",
            "status": "READY_CHANGED_INPUT_FAILED_ONLY_RETRY",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
    config = {
        **source,
        "status": "READY_FAILED_ONLY_U18_CHANGED_INPUT_SPLIT_R2",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "replaces_unit_id": "E31-CW-U18",
        "concurrency": 3,
        "tasks": tasks,
        "prior_generation_credits": 280,
        "prior_candidate_retained_as_rollback": True,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "config": str(CONFIG.relative_to(ROOT)),
        "tasks": [row["task_key"] for row in tasks],
        "fingerprints": [row["generation_fingerprint"] for row in tasks],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
