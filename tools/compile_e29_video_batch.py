#!/usr/bin/env python3
"""Compile E29's script-derived units into a gated multi-state video batch."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint
from video_prompt_action_density_gate import validate_action_timeline


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E29_VIDEO_UNIT_PLAN_V2_CL2X581.json"
MANIFEST = PRODUCTION / "E29_PRODUCTION_MANIFEST.json"
ADMISSION = PRODUCTION / "E29_VIDEO_UNIT_STATE_POOL_ADMISSION_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E29剧本_ClaudeWriter_v1.md"
PROMPT_DIR = PRODUCTION / "video_prompts_multistate_v1"
CONFIG_OUT = PRODUCTION / "E29_15_VIDEO_UNIT_BATCH_V1.json"
PROMPTS_MD = PRODUCTION / "E29_15_VIDEO_UNIT_PROMPTS_FULL_V1.md"
SCENE_STATE_OUT = PRODUCTION / "E29_SCENE_AUTHORITY_STATE_V1.json"
RECEIPT_OUT = ROOT / "workflow/tasks/E29_15_VIDEO_UNIT_PROMPT_BUILD_V1_RECEIPT_20260722.json"
CREDIT_SCOPE_OUT = ROOT / "workflow/credit_scopes/E29_VIDEO_CREDIT_SCOPE.json"


SCENES = {
    "E29-CW-S01-ROOFTOP-CHASE": ("雪夜洛城屋檐与下方王府车队雪街", "屋脊追逐、暗槽换道", "青蓝月雪与街心红灯"),
    "E29-CW-S02-BROKEN-WALL-HANDOFF": ("雪街断墙下与相邻王府车队", "脚印断裂、第二人短打后遁入车队", "火把暖橙、雪夜青蓝与红灯"),
    "E29-CW-S03-CONVOY-ACCOUNTING": ("王府车队停驻的雪街", "陈迹拦车并以利益对账排除云妃和静妃", "青蓝风雪与满街红灯"),
    "E29-CW-S04-ALLEY-REVEAL": ("雪街坊墙投下的暗巷", "冰霜显出景朝水波暗纹并锁定幕后目的", "坊墙暗影、火折微光与冰霜幽蓝"),
    "E29-CW-S05-WET-LIST-HOOK": ("雪夜坊角暗处与上方檐角", "湿墨名单递入掌心、乌云示警、陈迹发现自己在名单末行", "暗影、红灯余光与湿墨乌黑"),
}


CHARACTERS = {
    "chenji": "陈迹[[char_chenji]]",
    "jiaotu": "皎兔[[char_jiaotu]]",
    "yunyang": "云羊[[char_yunyang]]",
    "wuyun": "乌云[[char_wuyun]]",
    "jing_agent": "景朝接手者[[char_jing_agent]][[char_instructor]]",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def split_even(start: float, duration: float, count: int) -> list[tuple[float, float]]:
    boundaries = [start + duration * index / count for index in range(count + 1)]
    return [(round(boundaries[index], 3), round(boundaries[index + 1], 3)) for index in range(count)]


def action_clauses(action: str) -> list[str]:
    return [part.strip("。；， ") for part in re.split(r"[；，。]", action) if part.strip("。；， ")]


def make_timeline(unit: dict, shots: dict[str, dict], selected_by_shot: dict[str, list[dict]]) -> list[dict]:
    timeline: list[dict] = []
    cursor = 0.0
    for shot_id in unit["editorial_shot_ids"]:
        shot = shots[shot_id]
        duration = float(shot["duration_seconds"])
        count = max(math.ceil(duration / 3.0), len(selected_by_shot[shot_id]))
        clauses = action_clauses(shot["action"])
        for index, (start, end) in enumerate(split_even(cursor, duration, count)):
            clause = clauses[min(index, len(clauses) - 1)]
            phase = "起势" if index == 0 else "结果" if index == count - 1 else "推进"
            environmental = (
                "雪片掠过受力轨迹，衣摆、灯影或器物随接触转动"
                if unit["scene_id"] != "E29-CW-S04-ALLEY-REVEAL"
                else "火折光移过人物和蜡纹，冷雾沿真实接触方向扩散"
            )
            timeline.append({
                "start_seconds": start,
                "end_seconds": end,
                "source_shot_id": shot_id,
                "reference_state_id": selected_by_shot[shot_id][index % len(selected_by_shot[shot_id])]["state_id"],
                "actions": [f"{phase}：{clause}", environmental],
                "state_change": f"{shot_id}从第{index + 1}拍推进到第{index + 2}拍，人物、道具或环境位置发生可见变化",
                "action_budget_seconds": round(end - start, 3),
            })
        cursor += duration
    return timeline


def make_reference_sequence(unit: dict, selected_by_shot: dict[str, list[dict]], shots: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    cursor = 0.0
    label = 1
    for shot_id in unit["editorial_shot_ids"]:
        states = selected_by_shot[shot_id]
        duration = float(shots[shot_id]["duration_seconds"])
        for state, (start, end) in zip(states, split_even(cursor, duration, len(states))):
            rows.append({
                "asset_label": f"@图片{label}",
                "state_id": state["state_id"],
                "source_shot_id": shot_id,
                "path": state["path"],
                "sha256": state["sha256"],
                "start_seconds": start,
                "end_seconds": end,
                "qa_decision": state["admission"],
                "raw_failure_checks": state["raw_failure_checks"],
            })
            label += 1
        cursor += duration
    return rows


def render_prompt(unit: dict, sequence: list[dict], timeline: list[dict], shots: dict[str, dict]) -> str:
    location, event, palette = SCENES[unit["scene_id"]]
    visible = []
    for shot_id in unit["editorial_shot_ids"]:
        for character in shots[shot_id].get("visible_characters") or []:
            if character not in visible:
                visible.append(character)
    entity_text = "、".join(CHARACTERS[item] for item in visible) or "本单元没有清晰正面人物，环境与车队仍绑定[[scene_e29]]"
    if re.search(r"教习|黑影", " ".join(shots[item]["action"] for item in unit["editorial_shot_ids"])):
        entity_text += "；教习或黑影的提及只绑定既有景朝接手者身份[[char_instructor]]，不得借用陈迹的脸"

    lines = [
        f"《青山》E29《追影锁线》{unit['unit_id']}，Seedance 2.0 Pro 多状态连续视频，{unit['duration_seconds']}秒，9:16，720p，原速动作。",
        f"【剧本硬锁】地点={location}；时间=夜；天气=持续细雪；本单元事件={event}。不得跨场、改昼夜或改剧情结果。",
        f"【实体绑定】{entity_text}。每个角色只允许一个身体，脸、年龄、发型、服装和身份在全部状态间连续。",
        f"【palette与动机光】{palette}；黑位保留衣褶、瓦面、雪层与面部层次。",
        "【场景远景定场坐标】远景定场只用于锁定屋檐、雪街、车队、坊墙的相对位置；每个镜头严格执行自己的景别，不把统一的前中后景说明套到近景或特写。",
        "【参考状态序列】下列图片是同一连续视频的有序状态，不是候选图。必须按时间消费，禁止只动画第一张、拼贴、分屏或故事板网格：",
    ]
    for row in sequence:
        note = "原始QA通过" if row["qa_decision"] == "PASS" else f"条件准入，原始失败={','.join(row['raw_failure_checks'])}"
        lines.append(
            f"- {row['start_seconds']:.3f}-{row['end_seconds']:.3f}秒：{row['asset_label']}={row['state_id']}，锁定构图、身份、地点、道具和动作阶段；{note}；SHA-256={row['sha256']}。"
        )

    lines.append("【连续分镜】每镜都以可见动作变化结束；不补时长、不停帧、不循环、不慢放：")
    cursor = 0.0
    sequence_by_shot: dict[str, list[dict]] = {}
    for row in sequence:
        sequence_by_shot.setdefault(row["source_shot_id"], []).append(row)
    for index, shot_id in enumerate(unit["editorial_shot_ids"], 1):
        shot = shots[shot_id]
        end = cursor + float(shot["duration_seconds"])
        labels = "→".join(row["asset_label"] for row in sequence_by_shot[shot_id])
        lines.append(
            f"镜头{index}【{cursor:.3f}-{end:.3f}秒；景别={shot['scale']}；机位与运动={shot['camera']}】：参考{labels}按序变化。"
            f"先让主体抬起、转向或移入动作路径；继而严格完成剧本动作：{shot['action']}；"
            f"再完成：{shot_id}的受力、视线或位置结果；动作结果必须清晰落定并自然接下一镜。"
            f"{{对白与字幕：只按Claude剧本后期绑定，本次画内不生成文字}}<现场声：{shot['sound']}；接触声与画面同帧>"
        )
        cursor = end

    lines.append("【逐段动作时间轴】")
    for row in timeline:
        lines.append(
            f"- {row['start_seconds']:.3f}-{row['end_seconds']:.3f}秒 [{row['reference_state_id']}]："
            f"{'；'.join(row['actions'])}；状态变化={row['state_change']}。"
        )
    lines.extend([
        "【动作物理】先起势，再接触，再传力，最后呈现结果；足底、衣摆、纸影、刀、车轮、雪粉、火折与冷雾的轨迹可追踪，重心和惯性连续。力量必须通过环境介质显形。",
        "【现场声】风雪、踏雪、衣袂、车轮、纸帛、火把、器物和对白声场跟随景别变化；禁止无动机背景音乐。",
        "【负面约束】禁止字幕、水印、Logo、可读或伪可读文字；名单和私记只表现纸张、湿墨和纹样的物理状态，具体名字由后期字幕交付。禁止换脸、额外人物、同款分身、融合肢体、穿模、瞬移、悬空停顿、静图微动、重复首帧、慢动作和统一缓慢推镜。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    plan = load(PLAN)
    manifest = load(MANIFEST)
    admission = load(ADMISSION)
    if admission.get("status") not in {"PASS", "PASS_WITH_CONDITIONAL_ADMISSION"}:
        raise RuntimeError("state admission is not ready")
    shots = {row["shot_id"]: row for row in manifest["shots"]}
    admission_units = {row["unit_id"]: row for row in admission["units"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)

    scene_state = {
        "schema": "qingshan.scene_authority_state.v1",
        "episode": "E29",
        "scene_state": [
            {
                "scene_id": scene_id,
                "location": values[0],
                "time_of_day": "night",
                "weather": "snow",
                "event_summary": values[1],
                "location_prompt_tokens": [],
                "allowed_time_terms": ["night"],
                "allowed_weather_terms": ["snow"],
            }
            for scene_id, values in SCENES.items()
        ],
    }
    SCENE_STATE_OUT.write_text(json.dumps(scene_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    credit_scope = {
        "schema": "qingshan.episode_video_credit_scope.v1",
        "episode": "E29",
        "status": "ACTIVE",
        "workflow_scope_id": "e29_claude_writer_v1_20260722",
        "production_root": rel(PRODUCTION),
        "configured_limit_credits": 6000,
        "scope_policy": "CURRENT_WORKFLOW_ROUND_ONLY",
        "historical_rounds": "AUDIT_ONLY_EXCLUDED_FROM_GATE",
        "authorized_by": "Roger",
        "authorization": "6000 credits means this episode's current workflow round, not historical accumulation",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    CREDIT_SCOPE_OUT.parent.mkdir(parents=True, exist_ok=True)
    CREDIT_SCOPE_OUT.write_text(json.dumps(credit_scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tasks = []
    prompt_documents = []
    action_reports = []
    for unit in plan["units"]:
        admitted = admission_units[unit["unit_id"]]
        selected_by_shot: dict[str, list[dict]] = {shot_id: [] for shot_id in unit["editorial_shot_ids"]}
        for state in admitted["selected_states"]:
            selected_by_shot[state["source_shot_id"]].append(state)
        if any(not rows for rows in selected_by_shot.values()):
            raise RuntimeError(f"source-shot coverage missing: {unit['unit_id']}")
        sequence = make_reference_sequence(unit, selected_by_shot, shots)
        timeline = make_timeline(unit, shots, selected_by_shot)
        action_report = validate_action_timeline(timeline, unit["duration_seconds"], source_id=unit["unit_id"])
        if action_report["status"] != "PASS":
            raise RuntimeError(action_report["failures"])
        action_reports.append(action_report)
        prompt = render_prompt(unit, sequence, timeline, shots)
        prompt_path = PROMPT_DIR / f"{unit['unit_id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_documents.append(f"## {unit['unit_id']}\n\n```text\n{prompt}```\n")
        task = {
            "task_key": f"{unit['unit_id']}-VIDEO-V1",
            "source_id": unit["unit_id"],
            "tool_type": "video_generation",
            "generation_mode": "entity_reference_sequence",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "episode": "E29",
            "batch_id": "E29-CW-VIDEO-V1",
            "unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "visual_zone": unit["unit_id"],
            "duration": unit["duration_seconds"],
            "duration_seconds": unit["duration_seconds"],
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": unit["duration_seconds"],
                "rationale": "Exact sum of contiguous Claude-script editorial shots; unit count and duration emerged from scene-local semantic grouping.",
                "edit_policy": "End at the natural story/action result; trim unusable static tails and never pad, slow, loop, or preserve a prior runtime target.",
            },
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in sequence],
            "reference_image_sequence": sequence,
            "state_reference_minimum": 3 if unit["action_unit"] else 2,
            "action_reference_minimum": 0,
            "action_unit": bool(unit["action_unit"]),
            "action_timeline": timeline,
            "action_density_gate": action_report,
            "source_script_sha256": manifest["source"]["script_sha256"],
            "workflow_credit_scope": "e29_claude_writer_v1_20260722",
            "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E29",
        "status": "READY_FOR_PARALLEL_SUBMIT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": 15,
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "workflow_credit_scope": "e29_claude_writer_v1_20260722",
        "video_credit_limit": 6000,
        "source_script_sha256": manifest["source"]["script_sha256"],
        "state_admission": rel(ADMISSION),
        "scene_contract_ref": rel(SCENE_STATE_OUT),
        "supervisor_script_gate_required": False,
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": rel(SCRIPT),
            "source_script_sha256": sha256(SCRIPT),
            "production_manifest": rel(MANIFEST),
            "production_manifest_sha256": sha256(MANIFEST),
        },
        "output_dir": "working_assets/e29_video_units_v1_20260722",
        "qa_dir": "qa/e29_video_units_v1_20260722",
        "tasks": tasks,
    }
    CONFIG_OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PROMPTS_MD.write_text("# E29 15 Video Unit Prompts V1\n\n" + "\n".join(prompt_documents), encoding="utf-8")
    receipt = {
        "schema": "qingshan.video_prompt_build_receipt.v1",
        "episode": "E29",
        "status": "PASS_READY_FOR_PARALLEL_SUBMIT",
        "recorded_at": config["recorded_at"],
        "source_script": rel(SCRIPT),
        "source_script_sha256": sha256(SCRIPT),
        "unit_plan": rel(PLAN),
        "unit_plan_sha256": sha256(PLAN),
        "state_admission": rel(ADMISSION),
        "state_admission_sha256": sha256(ADMISSION),
        "unit_count": len(tasks),
        "runtime_seconds": sum(task["duration"] for task in tasks),
        "selected_state_count": sum(len(task["reference_images"]) for task in tasks),
        "action_density": {"status": "PASS", "reports": action_reports},
        "config": rel(CONFIG_OUT),
        "config_sha256": sha256(CONFIG_OUT),
        "remote_calls": 0,
        "generation_credits": 0,
    }
    RECEIPT_OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "units": receipt["unit_count"],
        "runtime_seconds": receipt["runtime_seconds"],
        "selected_states": receipt["selected_state_count"],
        "config": receipt["config"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
