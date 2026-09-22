#!/usr/bin/env python3
"""Build E59 keyframe R2 identity-repair subset without changing story contracts.

The source manifest remains immutable.  Every rejected unit receives a fresh task key,
output filename and a fully rewritten provider prompt.  Spatial maps, authored camera,
weather, cast membership, wardrobe and entry state are copied from the approved V1 task.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from role_semantic_prompt_gate import role_semantic_prompt_block


ROOT = Path("/Users/rogerwu/nalu")
PRE = ROOT / "workflow/nalu/E59/preproduction"
SOURCE = PRE / "E59_KEYFRAME_IMAGE_MANIFEST_V1.json"
OUT = PRE / "E59_KEYFRAME_IMAGE_MANIFEST_R2_IDENTITY_REPAIR.json"
PROMPT_DIR = PRE / "prompts/keyframes_r2_identity_repair"

REJECTED_UNITS = {
    "E59-VU-002", "E59-VU-003", "E59-VU-006", "E59-VU-007",
    "E59-VU-011", "E59-VU-012", "E59-VU-013", "E59-VU-014",
    "E59-VU-016", "E59-VU-017", "E59-VU-020", "E59-VU-021",
    "E59-VU-025", "E59-VU-026", "E59-VU-027", "E59-VU-028",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_prompt(task: dict) -> str:
    refs = task.get("reference_bindings") or []
    identities = [r for r in refs if r.get("role") == "character"]
    spaces = [r for r in refs if r.get("role") in {
        "episode_global_space_map", "global_space_map", "subspace_layout", "scene"
    }]
    wardrobes = [r for r in refs if r.get("role") == "character_wardrobe"]
    source = task.get("source_shot_contract") or {}
    blocking = task.get("blocking") or {}
    culture = task.get("visual_culture_contract") or {}
    role = task.get("role_semantic_disambiguation") or {}
    role_lock = role_semantic_prompt_block(role)

    identity_lines = []
    for ref in identities:
        identity_lines.append(
            f"- {ref.get('entity_name') or ref.get('entity_id')}（{ref.get('entity_id')}）："
            f"脸部只能复制 {ref.get('asset_label')} 的脸型、五官比例、年龄、肤色和发型；"
            "不得平均脸、换脸或借用其他人物特征。"
        )
    authority_lines = [
        f"@{ref.get('asset_label')} 是 {ref.get('entity_id')} 的唯一人物身份权威；"
        "只定义该人物脸型、五官比例、年龄、肤色和稳定身份，不得与其他参考平均或混脸。"
        for ref in identities
    ]
    space_lines = [
        f"- {r.get('asset_label')} 仅锁定 {r.get('role')} / {r.get('entity_id')} 的空间关系，"
        "不得把地图文字、网格、图例或俯视画法带进成片。"
        for r in spaces
    ]
    wardrobe_lines = [
        f"- {r.get('entity_name') or r.get('entity_id')} 的服装与体型只参考 {r.get('asset_label')}，"
        "脸仍以对应正面身份图为唯一权威。"
        for r in wardrobes
    ]
    positions = []
    for row in blocking.get("characters") or []:
        positions.append(
            f"{row.get('character')}（{row.get('character_id')}）在 {row.get('zone_id')} "
            f"坐标 {row.get('position')}，朝向 {row.get('facing')}"
        )
    visible = task.get("visible_characters") or []
    names = {r.get("entity_id"): r.get("entity_name") or r.get("entity_id") for r in identities}
    visible_text = "、".join(f"{names.get(cid, cid)}（{cid}）" for cid in visible)
    palette = culture.get("palette_system") or {}

    return "\n".join([
        "【E59 关键帧 R2｜身份一致性失败后的完整重写】",
        f"镜号：{task.get('shot_id')}｜视频单元：{task.get('video_unit_id')}｜9:16｜2K｜写实电影单帧。",
        "",
        "【唯一画面任务】",
        f"只表现入场状态：{source.get('entry_state')}。这是动作发生前的自然起始瞬间，不表现结果态，"
        "不使用运动模糊、慢动作、定格特效或重复人物。",
        "",
        f"【身份权威参考映射 {((task.get('identity_reference_transport') or {}).get('authority_prompt_token') or 'IDENTITY-AUTHORITY-UNRESOLVED')}】",
        *authority_lines,
        "空间图与服装图不得定义任何人物脸；最终输出必须通过 exact-SHA InsightFace 身份比对。",
        "",
        "【人物身份优先级最高】",
        *identity_lines,
        f"允许入画的人物严格只有：{visible_text}；每人只出现一次，不增加群众、侍从、倒影或镜中复制人。",
        "所有被声明可见的人脸必须清楚、自然、无遮挡：正面或轻微三分之四侧面，眼鼻嘴完整，"
        "不低头遮脸、不背对镜头、不被手、兵器、头发或前景挡住。保持原镜头类型与机位，"
        "在该构图内部调整人物间距和景深，让身份可辨；多人镜头不得牺牲任何具名角色的脸。",
        "",
        "【角色和动作不可互换】",
        role_lock,
        f"主动作执行者：{role.get('primary_actor')}（{role.get('primary_actor_id')}）；"
        f"对白说话人：{role.get('dialogue_speaker') or '无'}（{role.get('dialogue_speaker_id') or 'NONE'}）；"
        f"听者：{role.get('dialogue_listener') or '无'}。只有具名说话人可张口，其他人闭口自然反应。",
        "不得根据画面中心、服装、年龄或参考图顺序交换身份、动作或口型。",
        "",
        "【空间、机位与站位保持原合同】",
        *space_lines,
        f"地点链：{task.get('episode_global_space_map_id')} → {task.get('global_space_map_id')} → "
        f"{(task.get('subspace_layout') or {}).get('subspace_id')}。",
        f"摄影机：{source.get('camera')}；轴线：{source.get('axis')}；"
        f"固定元素：{', '.join((task.get('subspace_layout') or {}).get('visible_fixed_element_ids') or [])}。",
        "人物站位：" + "；".join(positions) + "。",
        "",
        "【服装与东方色调】",
        *wardrobe_lines,
        f"视觉档案：{culture.get('profile_id')}。{culture.get('production_design')}；"
        f"光线保持 {culture.get('lighting_language')}；主色保持 {palette.get('base')}；"
        f"肤色保持 {palette.get('skin')}。禁止欧洲中世纪骑士、板甲、霓虹、塑料磨皮和黑金奇幻调色。",
        "",
        "【输出禁令】",
        "无任何文字、字幕、标牌、logo、水印；无现代物件；无多余肢体、畸形手、克隆脸、半截人物；"
        "所有脚底与地面关系可信，北宋中国古装材质真实。"
    ])


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    manifest = copy.deepcopy(source)
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for original in source.get("tasks") or []:
        if original.get("video_unit_id") not in REJECTED_UNITS:
            continue
        task = copy.deepcopy(original)
        task["task_key"] = str(task["task_key"]).replace("KEYFRAME-V1", "KEYFRAME-R2")
        prompt_path = PROMPT_DIR / f"{task['shot_id']}-KEYFRAME-R2.txt"
        prompt = render_prompt(task).encode("utf-8")
        prompt_path.write_bytes(prompt)
        task["prompt_file"] = str(prompt_path)
        task["prompt_sha256"] = sha(prompt)
        task["provider_post_allowed"] = False
        task["maximum_new_submissions"] = 1
        task["output_contract"]["expected_output_path"] = str(
            PRE / "keyframes" / f"{task['shot_id']}-keyframe-r2.png"
        )
        task["repair_contract"] = {
            "attempt": "R2",
            "reason": "Q1_CHARACTER_IDENTITY_NOT_ADMITTED",
            "prompt_strategy": "FULL_REWRITE_NOT_INCREMENTAL_TUNING",
            "preserved": ["MAP", "WEATHER", "SHOT_TYPE", "AXIS", "ENTRY_STATE", "CAST", "WARDROBE"],
            "changed": ["IDENTITY_PRIORITY", "FACE_VISIBILITY", "IN_FRAME_SPACING"],
        }
        tasks.append(task)

    missing = sorted(REJECTED_UNITS - {t["video_unit_id"] for t in tasks})
    if missing:
        raise SystemExit(f"missing rejected units: {missing}")
    manifest.pop("paid_authorization", None)
    manifest["schema"] = "qingshan.keyframe_image_manifest.r2_identity_repair"
    manifest["batch_id"] = "E59-KEYFRAME-R2-IDENTITY-REPAIR"
    manifest["purpose"] = "Q1 identity repair; full prompt rewrite after V1 rejection"
    manifest["subset_mode"] = "FAILED_Q1_UNITS_ONLY"
    manifest["provider_post_allowed"] = False
    manifest["maximum_new_submissions"] = len(tasks)
    manifest["authorization_ref"] = ""
    manifest["task_count"] = len(tasks)
    manifest["tasks"] = tasks
    manifest["blocked_tasks"] = []
    manifest["generated_by"] = Path(__file__).name
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(OUT), "tasks": len(tasks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
