#!/usr/bin/env python3
"""Build changed-input U17A/U17B replacements after Seedance's 15s audio gate."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from episode_video_generation_guard import generation_fingerprint
except ImportError:
    from tools.episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723"
BASE_CONFIG = PRODUCTION / "video_performance_v2/E34_VIDEO_STREAMING_PERFORMANCE_V2.json"
SCENE_AUTHORITY = PRODUCTION / "E34_SCENE_STATE_AUTHORITY_V2.json"
SOURCE_DIALOGUE_MANIFEST = ROOT / "working_assets/e34_dialogue_audio_refs_v2_20260723/E34_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
SCRIPT_SHA = "400ff6d238e176999ff4320203839581e2f0a9cfcb7532a13ef7d5f37367d594"
REPAIR = PRODUCTION / "video_performance_v2/u17_split_repair"
PROMPTS = REPAIR / "prompts"
PLAN = REPAIR / "E34_U17_SPLIT_SOURCE_PLAN.json"
REPAIR_SCENE_AUTHORITY = REPAIR / "E34_U17_SPLIT_SCENE_AUTHORITY.json"
PROMPT_MANIFEST = REPAIR / "E34_U17_SPLIT_COMPLETE_VIDEO_PROMPT_MANIFEST.json"
DIALOGUE_MANIFEST = REPAIR / "E34_U17_SPLIT_DIALOGUE_MANIFEST.json"
ANCHOR_PLAN = REPAIR / "E34_U17_SPLIT_ANCHOR_COUNT_PLAN.json"
CONFIG = REPAIR / "E34_U17_SPLIT_VIDEO_BATCH.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def beat(start: float, end: float, action: str) -> dict:
    return {
        "start_seconds": start,
        "end_seconds": end,
        "subject": "严敬",
        "action": action,
        "contact_point": "不新增身体或道具接触；严敬被绑在椅上，只以口型、呼吸、视线与肩背颤动完成供述",
        "direction": f"严敬从封纹移回陈迹视线，连续说完：{action}；禁止跳位、转身、腾空或无因道具移动",
        "end_state": f"严敬完整说完‘{action}’，口型闭合并保留紧张呼吸，陈迹与皎兔仍在原位观察",
        "intent": "撬出景朝只认死物以及旧案线头",
        "visible_causality": "观众从严敬逐步崩溃的供词明确理解死物接头规则与旧案钩子",
        "expression": "严敬由强撑转绝望发抖；陈迹冷厉凝住；皎兔敏锐捕捉尾音",
        "viewer_read": "每句供词都推进接头规则，具体死物仍被悬住",
    }


def prompt(unit_id: str, duration: int, audio_rows: list[dict], actions: list[str], continuation: bool) -> str:
    audio_lines = "\n".join(
        f"- {row['audio_slot']}={row['dia_id']}：严敬逐字说‘{row['spoken_text']}’；完整复现参考音频的音色、语速、气息、情绪与口型。"
        for row in audio_rows
    )
    beats = []
    cursor = 0.0
    lengths = [3.0] * len(actions) if duration == 9 else [4.0, 3.0]
    for index, (action, length) in enumerate(zip(actions, lengths), 1):
        end = cursor + length
        beats.append(
            f"- {cursor:.3f}-{end:.3f}秒：主体=严敬；动作={action}；接触点=不新增身体或道具接触，绑绳和椅背位置不变；"
            f"方向=严敬视线沿封纹到陈迹连续移动，口型只匹配本句；动作目的=交代接头规则与旧案线头；"
            f"表情=绝望发抖逐句加深；终态=本句完整落定后自然换气；观众读法=线索逐句推进。"
        )
        cursor = end
    shot_audio = "；".join(f"{row['audio_slot']}完整说‘{row['spoken_text']}’" for row in audio_rows)
    continuity = "承接U17A相同机位、人物站位、绑绳、名册封纹与晨光方向" if continuation else "承接U16审讯终态，先用中景确认严敬、陈迹、皎兔与名册封纹位置"
    return f"""竖屏9:16，中国古装玄幻真人短剧，SD2四模态表演生成。仅生成Claude Writer E34 v2的{unit_id}，时长{duration}秒。室外宿雨已停，室内晨光与残烛；禁止正在降雨、深夜和现代物件。
【天气硬合同】weather=室外宿雨初收_室内晨光与残烛

实体绑定：[[char_yanjing]] [[char_chenji]] [[char_jiaotu]] [[scene_e34_s04]]。只允许剧本声明实体出现，每个角色只有一个身体。
动作目的：撬出景朝只认死物以及旧案线头。
单一动作状态源/连续运动脚本：{'；'.join(actions)}。
表情表演：严敬由强撑转绝望发抖，陈迹冷厉凝住，皎兔敏锐捕捉尾音；三人的反应必须随每句供词递进。
观众必须看懂：景朝以死物确认自己人，供词正把线索推向多年旧案，但死物名称仍未揭晓。

参考状态序列：@图片1。它只锁身份、密室空间、绑绳、椅背与供述起态；连续表演由运动脚本驱动，禁止定格、拼贴和姿势跳切。

对白与口型音频绑定：
{audio_lines}
必须由对应音频驱动严敬原生自然中文普通话、口型、气息、表情和起止时间；只说一次，禁止改字、漏字、串角色。陈迹与皎兔全程闭口，只做同步表情反应。

镜头1【0.000-{duration:.3f}秒；中景连续缓推至近景表情特写】：{continuity}；依序完成：{'；'.join(actions)}；每句之间只保留自然换气，不插入空镜，不重复动作。{{{shot_audio}}}<绑绳轻响、衣料、呼吸、纸张与密室晨间环境声>

逐拍物理表演脚本：
{chr(10).join(beats)}

物理硬门：严敬始终被绑在同一把椅上，陈迹与皎兔不换位；每段明确主体、动作、视线方向和终态。禁止新增抓取、转身、腾空、碰撞、慢镜、插帧、周期重复、静帧填时。
力量作用环境：本单元没有施术；只有呼吸、绑绳轻颤、衣料和纸张随真实身体动作反馈并自然停止。
palette与光影：室内晨光冷白与残烛暖黄形成冷暖层次，人物脸部清楚可辨，不得雨夜化。
身份硬门：严敬、陈迹、皎兔脸、年龄、发型、服装和声线与绑定参考一致；陈迹始终十七岁少年。禁止新增人物、字幕、水印和可读伪文字。
摄影：服务供词递进与表情转折，连续缓推，不跨轴，不用无动机大全景。片尾不在单元内生成；禁止BGM与旁白。
"""


def main() -> int:
    base = load(BASE_CONFIG)
    source = next(row for row in base["tasks"] if row["unit_id"] == "E34-CW-U17")
    source_dialogue_by_id = {row["dia_id"]: row for row in load(SOURCE_DIALOGUE_MANIFEST)["rows"]}
    splits = [
        ("E34-CW-U17A", 9, source["dialogue_audio_assets"][:3], [
            "严敬吸气后说景朝从不认活人",
            "严敬看向名册封纹说他们接头只认一样死物",
            "严敬盯住陈迹说谁亮出那东西谁就是自己人",
        ]),
        ("E34-CW-U17B", 7, source["dialogue_audio_assets"][3:], [
            "严敬声音降下，说那东西牵着景朝一桩多年前旧案",
            "严敬停在未说完的称呼前，只说我听底下人叫它",
        ]),
    ]
    tasks = []
    prompt_rows = []
    dialogue_rows = []
    plan_units = []
    for unit_id, duration, audio_rows, actions in splits:
        path = PROMPTS / f"{unit_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt(unit_id, duration, audio_rows, actions, unit_id.endswith("B")), encoding="utf-8")
        task = copy.deepcopy(source)
        task.update({
            "task_key": f"{unit_id}-PERFORMANCE-V2-REPAIR1",
            "source_id": unit_id,
            "unit_id": unit_id,
            "batch_id": "E34-V2-U17-SPLIT-REPAIR1-20260723",
            "visual_zone": f"{unit_id}-V2-REPAIR1",
            "duration": duration,
            "duration_seconds": duration,
            "edit_target_duration_seconds": duration,
            "prompt_file": rel(path),
            "prompt_path": rel(path),
            "prompt_sha256": sha(path),
            "dialogue": [{"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]} for row in audio_rows],
            "reference_audios": [row["path"] for row in audio_rows],
            "reference_audio_asset_ids": [],
            "dialogue_audio_assets": audio_rows,
            "dialogue_audio_coverage": {"required": len(audio_rows), "bound": len(audio_rows), "status": "PASS"},
            "replacement_for": "E34-CW-U17-PERFORMANCE-V2",
            "changed_input_reason": "Split at natural dialogue boundary because exact audio references totaled 15.075563s, above Seedance's 15s per-task limit and above the original 9s performance duration.",
            "inherits_establishing_coverage": True,
            "status": "READY_TO_SUBMIT",
            "state": "pending",
        })
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": duration,
            "rationale": "Natural dialogue boundary; generated duration covers the exact bound speech without compression.",
            "edit_policy": "Trim only natural head/tail pauses in the final edit; never loop, freeze, interpolate or slow footage.",
        }
        task["performance_spec"] = {
            "schema": "qingshan.performance_generation_spec.v3",
            "episode": "E34",
            "unit_id": unit_id,
            "duration_seconds": duration,
            "prop_ownership": {"single_source_of_truth": "U17 split repair keeps the same locked cast, chair, binding rope, ledger and dialogue source."},
            "motion_beats": [beat(sum(([3.0] * len(actions) if duration == 9 else [4.0, 3.0])[:i]), sum(([3.0] * len(actions) if duration == 9 else [4.0, 3.0])[:i + 1]), action) for i, action in enumerate(actions)],
        }
        for binding in task["multimodal_entity_bindings"]:
            binding["dialogue_audio_slots"] = [row["audio_slot"] for row in audio_rows if row["speaker_id"] == binding["entity_id"]]
            binding["visible_speaker"] = bool(binding["dialogue_audio_slots"])
            binding["lip_sync"] = bool(binding["dialogue_audio_slots"])
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        task.pop("task_id", None)
        task.pop("submit_response", None)
        task.pop("credit_attempts", None)
        task.pop("retry_count", None)
        task.pop("resolved_reference_image_asset_ids", None)
        task.pop("resolved_reference_audio_asset_ids", None)
        task.pop("resolved_reference_video_asset_ids", None)
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        prompt_rows.append({
            "unit_id": unit_id, "scene_id": "E34-CW-S04", "weather": "室外宿雨初收_室内晨光与残烛",
            "duration_seconds": duration, "prompt_path": rel(path), "prompt_sha256": sha(path),
            "dialogue_ids": [row["dia_id"] for row in audio_rows], "anchor_task_keys": ["E34-CW-U17-A1-STILL-V2"], "status": "PASS_COMPLETE",
        })
        plan_units.append({"unit_id": unit_id, "scene_id": "E34-CW-S04", "duration_seconds": duration})
        for row in audio_rows:
            copied = copy.deepcopy(source_dialogue_by_id[row["dia_id"]])
            copied["video_unit_id"] = unit_id
            dialogue_rows.append(copied)

    write(PLAN, {"schema": "qingshan.targeted_split_source_plan.v1", "episode": "E34", "units": plan_units})
    scene_source = load(SCENE_AUTHORITY)
    write(REPAIR_SCENE_AUTHORITY, {
        **{key: value for key, value in scene_source.items() if key != "scene_state"},
        "scene_state": [row for row in scene_source["scene_state"] if row["scene_id"] == "E34-CW-S04"],
    })
    write(PROMPT_MANIFEST, {
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E34", "status": "PASS",
        "unit_count": 2, "all_units_have_prompt": True, "source_script_sha256": SCRIPT_SHA,
        "source_plan": rel(PLAN), "source_plan_sha256": sha(PLAN),
        "source_scene_authority": rel(REPAIR_SCENE_AUTHORITY), "source_scene_authority_sha256": sha(REPAIR_SCENE_AUTHORITY),
        "rows": prompt_rows,
    })
    write(DIALOGUE_MANIFEST, {"schema": "qingshan.dialogue_audio_reference_manifest.v2", "episode": "E34", "status": "PASS", "source_script_sha256": SCRIPT_SHA, "rows": dialogue_rows})
    write(ANCHOR_PLAN, {
        "schema": "qingshan.video_unit_anchor_count_plan.v1",
        "episode": "E34",
        "source_script_sha256": SCRIPT_SHA,
        "planned_reference_image_count": 2,
        "units": [{
            "unit_id": unit_id,
            "planned_reference_image_count": 1,
            "reference_image_task_keys": ["E34-CW-U17-A1-STILL-V2"],
            "anchor_count_decision": {
                "planned_reference_image_count": 1,
                "reason": "The split changes only dialogue timing; one previously admitted continuous interrogation anchor remains sufficient.",
                "criteria": {"continuous_motion_from_single_start": True, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": False},
                "anchor_roles": ["dead_object_confession"],
                "action_design_class": "SINGLE_START_CONTINUOUS_MOTION",
            },
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 0, "basis": "Single start anchor; no adjacent pair is required."},
        } for unit_id, *_ in splits],
    })
    config = copy.deepcopy(base)
    config.update({
        "recorded_at": datetime.now(timezone.utc).isoformat(), "concurrency": 2,
        "batch_id": "E34-V2-U17-SPLIT-REPAIR1-20260723", "targeted_unit_replacement": True,
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST), "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "scene_contract_ref": rel(REPAIR_SCENE_AUTHORITY),
        "anchor_count_plan_ref": rel(ANCHOR_PLAN),
        "qa_dir": rel(REPAIR / "qa"), "tasks": tasks, "reused_video_units": [], "waiting_unit_ids": [],
    })
    write(CONFIG, config)
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "audio_seconds": [round(sum(float(row["duration_seconds"]) for row in task["dialogue_audio_assets"]), 6) for task in tasks], "config": rel(CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
