#!/usr/bin/env python3
"""Build E31 U18-B R3 with an explicit Chen Ji identity anchor."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/video_performance_v1"
SOURCE = BASE / "E31_VIDEO_BATCH_U18_SPLIT_DIALOGUE_R2.json"
PROMPT = BASE / "prompts/E31-CW-U18-B-PERFORMANCE-R3.txt"
CONFIG = BASE / "E31_VIDEO_BATCH_U18_B_IDENTITY_R3.json"
CHENJI = ROOT / "working_assets/api_reference_images_20260704/male_lead_chenji_ancient_face_ref_20260621_api.jpg"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = next(row for row in source["tasks"] if row["unit_id"] == "E31-CW-U18-B")
    row = task["dialogue"][0]
    line = row["spoken_text"]
    prompt = "\n".join([
        "《青山》E31《王府风暴》U18-B R3，Seedance 2.0 Pro 四模态表演生成，4秒，9:16，720p，原速连续表演。",
        "【实体绑定】陈迹[[char_chenji]]、云羊[[char_yunyang]]、火后庭院[[scene_e31_s05]]、越级骨牌[[prop_e31_token]]。",
        "【身份硬锁】@图片1锁火后庭院、双人站位与骨牌；@图片2只锁陈迹本人：成熟窄长脸、束冠、灰黑交领长袍。@图片1里的黑衣年轻人是云羊，绝对不是陈迹；本镜云羊退到画外，只保留一只持牌手作为反打前景，不露脸、不说话。",
        "【生成范式】@音频1只驱动@图片2身份的陈迹，逐字生成自然中文普通话、原生口型、气息和冷静推断表情；不得把声音交给黑衣年轻云羊。",
        "【色彩与动机光】残火暖橙照亮陈迹侧脸，雪夜环境冷蓝；人物侧转的力量作用到环境介质，衣领、薄烟与火苗响应一次并自然衰减。",
        "【唯一对白】0.15秒陈迹立即开口，台词只在后续分镜大括号声明一次；云羊全程闭口。",
        f"镜头1【0.0-4.0秒，陈迹近景反打并轻微推近】@图片2身份的陈迹先看画外云羊手中骨牌，再把视线移向后景残火；下颌微收，语气冷静，眼神像在把内部翻册者与更高发令者拆开比较，最后回看云羊。{{陈迹：{line}}}<衣料轻响、残火噼啪、压低呼吸、风雪底噪>",
        "【连续物理链】0-0.15秒：陈迹视线落在画外骨牌；0.15-3.55秒：侧转望向残火并完整说完@音频1，双手不碰骨牌；3.55-4秒：视线回到云羊，判断落定。",
        "【表演目的】观众必须看懂：翻名册的是内部执行者，发令者却高到直属上司无法触及，两只手属于不同权力层级。",
        "【声音】必须保留@音频1从第一个字到最后一个字的陈迹原生口型对白，以及残火、衣料、风雪现场声；禁止BGM、旁白、额外对白和重复台词。",
        "【负面约束】禁止字幕、水印、Logo、可读文字；禁止把黑衣青年当陈迹、禁止云羊开口、串台、吞句、改词、换脸、分身、瞬移、道具换手、慢放、停帧、循环、周期重复和静帧微动。",
    ]) + "\n"
    PROMPT.write_text(prompt, encoding="utf-8")
    scene_ref = task["reference_image_sequence"][0]
    chenji_ref = {
        "asset_label": "@图片2",
        "role": "CHENJI_IDENTITY",
        "path": str(CHENJI.relative_to(ROOT)),
        "sha256": sha256(CHENJI),
    }
    task = {
        **task,
        "task_key": "E31-CW-U18-B-PERFORMANCE-R3",
        "batch_id": "E31-U18-B-IDENTITY-R3",
        "reference_images": [scene_ref["path"], chenji_ref["path"]],
        "reference_image_sequence": [scene_ref, chenji_ref],
        "state_reference_minimum": 2,
        "planned_reference_image_count": 2,
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "retry_reason": "R2 final visual evidence showed the Yun Yang actor speaking Chen Ji's line; R3 adds a dedicated Chen Ji identity anchor and removes Yun Yang's face from the shot.",
        "status": "READY_CHANGED_INPUT_FAILED_ONLY_RETRY",
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        **source,
        "status": "READY_FAILED_ONLY_U18_B_IDENTITY_R3",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": True,
        "replaces_task_key": "E31-CW-U18-B-PERFORMANCE-R2",
        "concurrency": 1,
        "tasks": [task],
        "prior_candidate_retained_as_rollback": True,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(CONFIG.relative_to(ROOT)), "prompt": str(PROMPT.relative_to(ROOT)), "reference_count": 2, "fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
