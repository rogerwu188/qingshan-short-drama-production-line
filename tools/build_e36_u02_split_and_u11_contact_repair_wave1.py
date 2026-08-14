#!/usr/bin/env python3
"""Build three materially changed E36 Seedance Pro repair tasks."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT_ROOT = PROD / "autonomous_recovery_20260731/u02_u11_changed_repairs_wave1"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "8419fc7adda313b879459e993881334c5018c6076627114508d56037bc34918b"
EPISODE_BEFORE = 8880

U02_SOURCE = PROD / "autonomous_recovery_20260731/u02_lines02_03"
U11_SOURCE = PROD / "recovery_10000_20260730/u11_r1a_video"

SPECS = [
    {
        "slug": "u02_line02",
        "unit": "U02",
        "line": 2,
        "speaker": "陈迹",
        "speaker_id": "chenji",
        "text": "不能伤官差。",
        "start": 0.35,
        "end": 2.20,
        "weather": "HEAT_NOON_DRY_DUST",
        "parent": "df5150a2-d82b-4f30-a1dc-435de331d61c",
        "action": "十七岁陈迹左肩正贴向木柱借人群遮挡，右手掌心向下压住同伴冲出的势头",
        "contact": "左肩与刑台侧木柱、左脚与尘土地面，右手不触官差",
        "direction": "身体由画面右后向左前探，右掌由胸前向下压止",
        "end_state": "差字落下后陈迹闭口，右掌停在胸前下方，官差与囚犯均未被碰触",
        "expression": "十七岁少年克制而急促地立下行动底线",
    },
    {
        "slug": "u02_line03",
        "unit": "U02",
        "line": 3,
        "speaker": "陈迹",
        "speaker_id": "chenji",
        "text": "伤一个，咱们就是劫法场的钦犯。人，只能从刀下换走。",
        "start": 0.25,
        "end": 5.55,
        "weather": "HEAT_NOON_DRY_DUST",
        "parent": "df5150a2-d82b-4f30-a1dc-435de331d61c",
        "action": "十七岁陈迹右手正沿刑台木栏向下划出避开官差、只换囚犯的撤离路线",
        "contact": "左肩与木柱、右指腹与木栏、左脚与尘土地面",
        "direction": "右指由画面左上沿木栏向右下划到刑台侧后方",
        "end_state": "走字完整落下后陈迹闭口，右指停在撤离路线终点，身体仍藏在木柱后",
        "expression": "十七岁少年冷静压低声线说明不能伤人及换囚方案",
    },
    {
        "slug": "u11_line16",
        "unit": "U11",
        "line": 16,
        "speaker": "云羊",
        "speaker_id": "yunyang",
        "text": "空信封……可他每露一次面，咱们就倾巢而动。这不合规矩。",
        "start": 0.20,
        "end": 5.55,
        "weather": "INTERIOR_CLEAR_HARSH_SUN",
        "parent": "ced5c13a-d572-4ab1-a978-4c677cfdead6",
        "action": "十七岁云羊上身正在向桌沿前倾，右掌压住桌沿，视线从唯一空信封抬向画外陈迹",
        "contact": "云羊右掌与旧木桌沿、唯一空信封与桌面；人物双手始终离信封至少一掌宽",
        "direction": "云羊重心由画面右后向左前压近，视线由下向左上抬起",
        "end_state": "矩字完整落下后云羊闭口并微退半寸，双手仍压桌沿且离信封至少一掌宽，信封原位静止未触",
        "expression": "十七岁云羊克制警觉地指出行动反常",
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def u02_refs() -> tuple[list[str], list[dict]]:
    refs = [
        "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png",
        "working_assets/e36_v2_stills_20260728/u02_repair_v2_candidates/E36-CW-U02-A1-STILL-V2-IDENTITY-REPAIR_7dba2363-a59d-430f-bf21-3663442dcc7c.png",
    ]
    seq = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "chenji", "path": refs[0], "sha256": "e513b4e9b3a1caba1326e9511136550f94e2add111b3ad897f6f24642d07c4c0", "identity_reference": True},
        {"asset_label": "@图片2", "role": "START_MOTION_SCENE_AND_AXIS_ANCHOR", "state_id": "E36-CW-U02-A1-STILL-V2-IDENTITY-REPAIR", "path": refs[1], "sha256": "66a2202a9ef95dabd414ae1c5a2212010a54e32e310267e16a3df4d4abc8c8f0", "identity_reference": False},
    ]
    return refs, seq


def u11_refs() -> tuple[list[str], list[dict]]:
    refs = [
        "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png",
        "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U11-A1-STILL-V2_e3678bd0-6888-41ab-8d4f-4a68bbe2aea9.png",
    ]
    seq = [
        {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": "yunyang", "path": refs[0], "sha256": "a475190fd667a28e1850ff10706724a5759938bba61e1f3ef87941536950bd17", "identity_reference": True},
        {"asset_label": "@图片2", "role": "SCENE_LIGHTING_AND_TABLE_AXIS_ONLY_IGNORE_CHARACTER_POSES", "state_id": "E36-CW-U11-A1-SCENE-ONLY", "path": refs[1], "sha256": "d10be1902a23f6b546d0daff7ff9ec2a7cb1f98680dc8359df1c1e34efe0d5c2", "identity_reference": False},
    ]
    return refs, seq


def prompt_for(spec: dict) -> str:
    if spec["unit"] == "U02":
        setting = "古代景朝洛城西市刑台，酷热正午，十七岁陈迹单人中近景；云羊、官差、囚犯只在画外且闭口。"
        binding = "[[scene_e36_u02_execution_square]]；[[char_chenji_age17]]；[[prop_execution_platform_woodwork]]"
        life = "刑台旗幡受热风持续摆动，脚步卷起干尘，远处役卒和百姓保持低幅移动，热浪令背景轻微抖动"
        medium = "陈迹的手臂和躯干动作只带动自己的袖褶、木柱表面浮尘与脚边干尘；不得隔空推动官差、囚犯或刑具"
        extra = "陈迹脸型、发型、眉眼与@图片1完全一致，明确是十七岁少年：面颊年轻、无胡须、无成年化骨相。@图片2只提供刑台空间、轴线和首帧动作关系，不得覆盖@图片1身份。"
    else:
        setting = "古代景朝太平医馆密室午后，十七岁云羊单人胸上中近景；陈迹完全在画外并闭口。旧木案上只有一个无字空信封。"
        binding = "[[scene_e36_u11_clinic_room]]；[[char_yunyang_age17]]；[[prop_single_blank_envelope]]；[[prop_old_wood_table]]"
        life = "古式烛焰持续微颤，直棂窗硬日光缓慢移动，药帘与悬草受穿堂风轻摆，纸角只受气流轻颤而不位移"
        medium = "云羊前倾和按桌只带动自己的袖褶、桌沿轻微受力和近身气流；所有人物的手不得进入信封周围一掌宽禁区，不得推动、吸附、拿起、复制或翻转信封"
        extra = "@图片1只锁定十七岁云羊身份。@图片2只借用医馆木构、窗光和桌面轴线，必须忽略其中人物、猫与手部姿势。首帧画面必须明确看见云羊双手在桌沿、信封在桌面中央，两者相距至少一掌宽；全片陈迹不入镜，彻底消除前次指尖触信封失败。"
    return f'''VISUAL_PROMPT_NO_DIALOGUE_TEXT:
【剧本硬锁】E36 canonical SHA={SCRIPT_SHA}；本镜只覆盖 canonical 编译对白第{spec["line"]}行，禁止增删、改写、重复或混入相邻台词。
【天气硬合同】weather={spec["weather"]}
【人物、场景与道具绑定】{binding}
【身份与时代连续性】{setting}{extra}古装、妆发、木构与器物保持架空古代景朝连续，无现代物件。
【色彩与动机光】低饱和灰青布衣、旧木深褐与尘土灰黄；只使用日光、热反光或古式烛焰的动机光，无现代灯具与霓虹。
【环境生命层】{life}；背景不得冻结。
镜头1【单一连续中近景，肩高机位，极缓横移，0.00-6.00秒】首帧已在动作中：{spec["action"]}，嘴正要开。主体={spec["speaker"]}；动作={spec["action"]}；接触点={spec["contact"]}；方向={spec["direction"]}；终态={spec["end_state"]}。{{对白：{spec["speaker"]}仅说 canonical 第{spec["line"]}行}}
【力量作用于环境介质】{medium}。
【原生对白硬合同】视频模型原生生成自然中文普通话。{spec["speaker"]}{spec["start"]:.2f}-{spec["end"]:.2f}秒逐字只说一次：“{spec["text"]}”可见嘴部口型、气息、眉眼、表情与发声起止同步；末字完整落下后闭口。不得旁白、后配、画外代说、字幕或现代播音腔。
【负面约束】无现代物件、字幕、水印、Logo、可读文字或伪文字；无身份漂移、成年化、胡须、同脸复制、肢体融合、静止起手、瞬移、循环填时、口型错配、非本镜相邻台词。
'''


def main() -> None:
    u02_batch = json.loads((U02_SOURCE / "E36_U02_LINES02_03_BATCH.json").read_text(encoding="utf-8"))
    u02_complete = json.loads((U02_SOURCE / "E36_U02_LINES02_03_COMPLETE_VIDEO_PROMPT_MANIFEST.json").read_text(encoding="utf-8"))
    u11_batch = json.loads((U11_SOURCE / "E36_U11_R1A_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json").read_text(encoding="utf-8"))
    u11_complete = json.loads((U11_SOURCE / "E36_U11_R1A_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json").read_text(encoding="utf-8"))
    jobs = []
    for spec in SPECS:
        out = OUT_ROOT / spec["slug"]
        out.mkdir(parents=True, exist_ok=True)
        qa_rel = f'qa/e36_agentcut_20260730/u02_u11_changed_repairs_wave1_{spec["slug"]}_runtime'
        media_rel = f'working_assets/e36_autonomous_recovery_20260731/u02_u11_changed_repairs_wave1_{spec["slug"]}'
        (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)
        (ROOT / media_rel).mkdir(parents=True, exist_ok=True)
        stem = f'E36_{spec["unit"]}_CANONICAL_L{spec["line"]:02d}_PRO_CHANGED_W1'
        prompt_rel = str((out / f"{stem}_PROMPT.txt").relative_to(ROOT))
        config_rel = str((out / f"{stem}_BATCH.json").relative_to(ROOT))
        complete_rel = str((out / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json").relative_to(ROOT))
        dialogue_rel = str((out / f"{stem}_DIALOGUE_MANIFEST.json").relative_to(ROOT))
        prompt_path = ROOT / prompt_rel
        prompt_path.write_text(prompt_for(spec), encoding="utf-8")
        prompt_sha = sha(prompt_path)
        dia = {
            "dia_id": f'E36-{spec["unit"]}-CANONICAL-L{spec["line"]:02d}-PRO-CHANGED-W1',
            "video_unit_id": spec["unit"], "speaker_id": spec["speaker_id"], "speaker": spec["speaker"],
            "spoken_text": spec["text"], "status": "PASS", "start_seconds": spec["start"], "end_seconds": spec["end"],
            "breath_after_seconds": round(6.0 - spec["end"], 2), "expression": spec["expression"],
            "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION", "human_listening_exception": True,
            "external_voice_reference": False, "path": "", "remote_asset_id": "",
        }
        dump(ROOT / dialogue_rel, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS", "source_script_sha256": SCRIPT_SHA, "rows": [dia]})
        complete = copy.deepcopy(u02_complete if spec["unit"] == "U02" else u11_complete)
        for row in complete["rows"]:
            if row["unit_id"] == spec["unit"]:
                row["prompt_path"] = prompt_rel
                row["prompt_sha256"] = prompt_sha
        dump(ROOT / complete_rel, complete)
        batch = copy.deepcopy(u02_batch if spec["unit"] == "U02" else u11_batch)
        batch.update({
            "status": "ready", "source_cl2x": "CL2X-874", "source_cl2x_mailbox_sha256": MAILBOX_SHA,
            "source_mailbox_sha256": MAILBOX_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "episode_paid_credits_before": EPISODE_BEFORE, "video_credit_limit": 120,
            "output_dir": media_rel, "qa_dir": qa_rel, "complete_video_prompt_manifest_ref": complete_rel,
            "dialogue_manifest_ref": dialogue_rel, "changed_input_parent_task_id": spec["parent"],
            "changed_input_repair": True, "unchanged_retry": False, "max_retries": 0,
        })
        task = batch["tasks"][0]
        refs, seq = u02_refs() if spec["unit"] == "U02" else u11_refs()
        task.update({
            "task_key": stem.replace("_", "-"), "source_id": stem.replace("_", "-"), "batch_id": stem.replace("_", "-"),
            "duration_seconds": 6, "duration": 6, "edit_target_duration_seconds": 6, "model": "seedance-2.0-pro",
            "status": "ready", "prompt_path": prompt_rel, "prompt_file": prompt_rel, "prompt_sha256": prompt_sha,
            "reference_images": refs, "reference_image_sequence": seq, "planned_reference_image_count": 1,
            "dialogue": [{**dia, "language": "zh-CN", "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True}],
            "dialogue_audio_assets": [], "reference_audios": [], "reference_audio_asset_ids": [], "audio_reference_optional": True,
            "model_native_text_only_dialogue_ids": [dia["dia_id"]], "native_dialogue_required": True,
            "visible_speaker_required": True, "visual_entity_ids": [spec["speaker_id"]],
            "source_segment_id": spec["slug"], "changed_input_parent_task_id": spec["parent"],
            "replaces_parent_task_id": spec["parent"], "changed_input_repair": True, "unchanged_retry": False,
            "reference_image_asset_ids": [], "max_retries": 0,
        })
        task["duration_plan"] = {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6,
            "rationale": f'Canonical line {spec["line"]} isolated as a materially changed Pro-route native Mandarin performance.',
            "edit_policy": "Preserve native Mandarin and lip sync; no post-dub, time stretch, filler or duplicate frames."}
        task["performance_spec"] = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": spec["unit"],
            "prop_ownership": {"唯一无字空信封": "全段留在桌面原位且无人触碰"} if spec["unit"] == "U11" else {"刑台侧木柱": "场景固定承力物，只由陈迹左肩短暂接触"},
            "motion_beats": [{"start_seconds": 0.0, "end_seconds": 6.0, "subject": spec["speaker"],
                "action": spec["action"], "contact_point": spec["contact"], "direction": spec["direction"],
                "end_state": spec["end_state"], "intent": "以单一自然呼吸组完成 canonical 推理台词",
                "visible_causality": "前镜风险或证物触发现场判断", "expression": spec["expression"],
                "viewer_read": "主体、动作、接触点、方向、终态和唯一对白均清楚"}]}
        if spec["unit"] == "U11":
            task["multimodal_entity_bindings"] = [{"entity_id": "yunyang", "character_name": "云羊", "registry_id": "CHAR-云羊-古装",
                "visual_reference": refs[0], "visual_reference_sha256": seq[0]["sha256"], "identity_image_slot": "@图片1",
                "visible_speaker": True, "lip_sync": True, "prop_owners": {"旧木案": "双手只压桌沿，离信封至少一掌宽"},
                "ability_owners": [], "voice_policy": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE"}]
        else:
            task["multimodal_entity_bindings"] = [{"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装",
                "visual_reference": refs[0], "visual_reference_sha256": seq[0]["sha256"], "identity_image_slot": "@图片1",
                "visible_speaker": True, "lip_sync": True, "prop_owners": {"刑台侧木柱": "左肩短暂接触以借遮挡"},
                "ability_owners": [], "voice_policy": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE"}]
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(
            task.get("multimodal_entity_bindings") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        dump(ROOT / config_rel, batch)
        jobs.append({"unit": spec["unit"], "line": spec["line"], "config": config_rel, "config_sha256": sha(ROOT / config_rel),
            "prompt": prompt_rel, "prompt_sha256": prompt_sha, "qa_dir": qa_rel, "media_dir": media_rel, "projected_credits": 120})
    index = {"schema": "qingshan.e36.u02_u11_changed_repairs_wave1.v1", "status": "READY_FOR_CONCURRENT_PRECHECK",
        "source_cl2x": "CL2X-874", "source_mailbox_sha256": MAILBOX_SHA, "source_script_sha256": SCRIPT_SHA,
        "source_manifest_sha256": MANIFEST_SHA, "episode_paid_credits_before": EPISODE_BEFORE,
        "projected_credits": 360, "projected_episode_total": 9240, "jobs": jobs}
    index_path = OUT_ROOT / "E36_U02_U11_CHANGED_REPAIRS_WAVE1_INDEX.json"
    dump(index_path, index)
    print(json.dumps({"index": str(index_path.relative_to(ROOT)), "index_sha256": sha(index_path), "jobs": jobs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
