#!/usr/bin/env python3
"""Build the exact 24-shot E27 Writer Agent v0.3 image-to-video batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720"
COMPILED = BASE / "task2_compiled.json"
IMAGE_CONFIG = BASE / "production/image_batch.json"
PRESERVED = BASE / "production/grand_establishing_migration/preserved_18_selection.json"
DEST = BASE / "production/video_batch_v1"

NEW_SOURCES = {
    "E27-N01": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_20260720/candidates/E27_E27-N01-WRITER-AGENT-STILL-V030-GRAND_1f418900-17a6-4b1d-b395-89f33c1e8cb7.png",
        "REV-B26AE30C2FD3474E",
        "PASS",
    ),
    "E27-N05": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_20260720/candidates/E27_E27-N05-WRITER-AGENT-STILL-V030-GRAND_85d0fe08-ca48-4453-9054-73fd22896d2e.png",
        "REV-D52670ACEEF1DA14",
        "PASS",
    ),
    "E27-N09": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_fix2_20260720/candidates/E27_E27-N09-WRITER-AGENT-STILL-V030-FIX2-CAUSAL.png",
        "REV-5D7563833DA88670",
        "CONDITIONAL_MACHINE_ADMISSION",
    ),
    "E27-N13": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_fix2_20260720/candidates/E27_E27-N13-WRITER-AGENT-STILL-V030-FIX2.png",
        "REV-30C56C30E482CA23",
        "PASS",
    ),
    "E27-N17": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_fix1_20260720/candidates/E27_E27-N17-WRITER-AGENT-STILL-V030-FIX1.png",
        "REV-B6BA6D237B824525",
        "PASS",
    ),
    "E27-N21": (
        ROOT / "working_assets/e27_writer_agent_v030_grand_establishing_20260720/candidates/E27_E27-N21-WRITER-AGENT-STILL-V030-GRAND_3fa85e36-71ca-468e-8f38-c6d87c22e705.png",
        "REV-3886068365DBB786",
        "PASS",
    ),
}

SPEAKERS = {
    "c_chenji": "陈迹",
    "c_jiaotu": "皎兔",
    "c_yao": "姚太医",
    "c_spy_leader": "密探头领",
    "c_baili": "百里",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scale_label(value: str) -> str:
    lowered = value.lower()
    if "ultra" in lowered or "extreme" in lowered:
        return "超广角大远景定场"
    if "wide" in lowered:
        return "大远景定场"
    if "close" in lowered or "detail" in lowered:
        return "近景特写"
    return "中景"


def dialogue_slot(shot: dict, dialogue_by_id: dict[str, dict]) -> str:
    rows = [dialogue_by_id[item] for item in shot.get("dialogue_ids", [])]
    if not rows:
        return "{无对白；人物仅以呼吸、目光和动作反应，禁止生成额外台词}"
    parts = []
    for row in rows:
        speaker = SPEAKERS.get(row["speaker_id"], row["speaker_id"])
        parts.append(f"{speaker}以自然普通话只说一次：‘{row['text']}’")
    return "{" + "；".join(parts) + "；其他人物保持沉默，禁止改词或增加对白}"


def build_prompt(shot: dict, video: dict, dialogue_by_id: dict[str, dict]) -> str:
    duration = int(video["duration_seconds"])
    scale = scale_label(video.get("shot_scale", "medium"))
    action = video["primary_action"]
    dialogue = dialogue_slot(shot, dialogue_by_id)
    special = ""
    if shot["shot_id"] == "E27-N09":
        special = (
            " 动作因果硬锁：皎兔拇指与食指已经捏合纯色无字红封签，并从第三层唯一空格右内壁半抽出；"
            "先显示窄缝，再让封签短边离开内壁，背景陈迹只静默观察，不得抢焦。"
        )
    return (
        f"这是《青山》E27 {shot['shot_id']} 的 Seedance 2.0 多模态分镜视频。"
        "以输入画面[[image_1]]为唯一人物身份、服装、道具、地点、时段、光线、构图和空间轴线锚点；剧本硬锁，不得改场景。"
        "本场的大远景定场由该场首个 grand-establishing 镜头承担；本镜必须服从已建立的空间地理，并严格使用下述合同景别，不得擅自全部改成近景。"
        f"目标时长{duration}s，竖屏9:16，电影级写实质感，无外部BGM，只保留符合现场的环境声、动作声与合同对白。"
        f"镜头1：【{scale}，{video.get('camera_height', 'eye level')}机位，{video.get('camera_motion') or video.get('camera')}运动】"
        f"从参考图既定姿态起动，镜头按{video.get('camera') or video.get('camera_motion')}缓慢推进；主体完成剧情动作：{action}；"
        f"动作落定后停在明确结果位，保持前景遮挡、行动中景和地点真实后景三层纵深。{special}"
        f"{dialogue} <衣料、脚步、金属、纸张或环境介质的现场动作声，力量作用必须让尘、火焰、布幔、木屑或阴影产生符合地点的次级反应>。"
        "色彩与光影：三角色控制色板，动机光严格来自剧本时段与现场光源，黑位有层次，肤色自然，材质精细；禁止擅自改成月光夜景。"
        "NEGATIVE_PROMPT：禁止改地点、时段、天气、人物、性别、年龄、服装、道具归属和剧情事件；禁止慢动作、补帧感、循环动作、无动机漂移、"
        "额外人物、分身、肢体融合、可读文字、伪文字、字幕、水印、Logo、拼贴、分屏、外部背景音乐；禁止用月亮、夜色、雾气或纯奇观替代剧情。"
    )


def main() -> int:
    compiled = load(COMPILED)
    image_config = load(IMAGE_CONFIG)
    preserved = load(PRESERVED)
    source_rows: dict[str, dict] = {}
    for row in preserved["items"]:
        path = Path(row["candidate_path"])
        if sha256(path) != row["candidate_sha256"]:
            raise SystemExit(f"preserved candidate SHA drift: {row['shot_id']}")
        source_rows[row["shot_id"]] = {
            "shot_id": row["shot_id"],
            "path": str(path),
            "sha256": row["candidate_sha256"],
            "review_id": row["review_id"],
            "admission": "PASS",
        }
    for shot_id, (path, review_id, admission) in NEW_SOURCES.items():
        source_rows[shot_id] = {
            "shot_id": shot_id,
            "path": str(path),
            "sha256": sha256(path),
            "review_id": review_id,
            "admission": admission,
        }
    shot_by_id = {row["shot_id"]: row for row in compiled["shot_contracts"]}
    dialogue_by_id = {row["dialogue_id"]: row for row in compiled["dialogue_contracts"]}
    expected = set(shot_by_id)
    if set(source_rows) != expected or len(source_rows) != 24:
        raise SystemExit(f"source selection mismatch: missing={sorted(expected-set(source_rows))} extra={sorted(set(source_rows)-expected)}")

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    manifest = [
        "# E27 Writer Agent v0.3.0 - 24 Video Generation Prompts",
        "",
        "Each prompt is bound to one exact source-image SHA. Durations come from the Writer Agent contract, not a fixed four-second template.",
        "",
    ]
    video_by_id = {row["shot_id"]: row for row in compiled["video_generation_contracts"]}
    for shot in sorted(compiled["shot_contracts"], key=lambda row: row["global_order"]):
        shot_id = shot["shot_id"]
        video = video_by_id[shot_id]
        prompt = build_prompt(shot, video, dialogue_by_id)
        prompt_path = prompt_dir / f"{shot_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        duration = int(video["duration_seconds"])
        tasks.append({
            "task_key": f"{shot_id}-WRITER-AGENT-V030-VIDEO-V1",
            "tool_type": "video_generation",
            "source_id": shot_id,
            "shot_id": shot_id,
            "scene_id": shot["scene_id"],
            "visual_zone": f"{shot['scene_id']}::{shot_id}",
            "duration": duration,
            "duration_seconds": duration,
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v4",
                "duration_seconds": duration,
                "rationale": f"Writer Agent v0.3 contract sets {duration}s from dialogue, physical action and reaction coverage for {shot_id}; no mechanical 4s normalization.",
                "edit_policy": "Generate the complete contract performance, then trim only to real speech and action boundaries in AgentCut.",
            },
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [source_rows[shot_id]["path"]],
            "source_image_sha256": source_rows[shot_id]["sha256"],
            "source_admission": source_rows[shot_id]["admission"],
            "source_review_id": source_rows[shot_id]["review_id"],
            "status": "READY_CONCURRENT_SUBMIT",
        })
        manifest.extend([
            f"## {shot_id} - {duration}s",
            "",
            f"- Source image: `{source_rows[shot_id]['path']}`",
            f"- Source SHA-256: `{source_rows[shot_id]['sha256']}`",
            f"- Admission: `{source_rows[shot_id]['admission']}`",
            f"- Review ID: `{source_rows[shot_id]['review_id']}`",
            "",
            "```text",
            prompt,
            "```",
            "",
        ])

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E27",
        "status": "READY_24_VIDEO_CONCURRENT_SUBMIT",
        "concurrency": 24,
        "max_retries": 1,
        "output_dir": "working_assets/e27_writer_agent_v030_video_v1_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v030_video_v1_20260720",
        "scene_contract_ref": "workflow/writer_agent/e27_agent_native_v030_20260720/production/scene_state.json",
        "script_readiness_report": "workflow/writer_agent/e27_agent_native_v030_20260720/production/script_readiness.json",
        "writer_agent_provenance": image_config["writer_agent_provenance"],
        "still_gate": "workflow/tasks/E27_WRITER_AGENT_V030_FINAL_STILL_GATE_STATUS_20260720.json",
        "conditional_admission": "workflow/tasks/E27_N09_CONDITIONAL_MACHINE_ADMISSION_20260720.json",
        "base_batch_note": "All 24 Writer Agent video contracts submitted concurrently; preserve passes and retry only failed items.",
        "tasks": tasks,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "source_selection_24.json").write_text(json.dumps({
        "schema": "qingshan.writer_agent_video_source_selection.v1",
        "episode": "E27",
        "status": "PASS_23_EXACT_PLUS_1_CONDITIONAL_MACHINE_ADMISSION",
        "count": 24,
        "items": [source_rows[row["shot_id"]] for row in sorted(compiled["shot_contracts"], key=lambda x: x["global_order"])],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path = DEST / "video_batch_v1.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = DEST / "E27_VIDEO_GENERATION_PROMPTS_24.md"
    manifest_path.write_text("\n".join(manifest), encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "tasks": len(tasks),
        "config": str(config_path.relative_to(ROOT)),
        "prompt_manifest": str(manifest_path.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
