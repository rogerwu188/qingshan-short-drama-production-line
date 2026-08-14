#!/usr/bin/env python3
"""Build four solo-speaker E36 changed-input tasks within the 408-credit cap."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = PROD / "autonomous_recovery_20260731/cap_close_changed_wave3"
ANCHORS = ROOT / "working_assets/e36_autonomous_recovery_20260731/cap_close_changed_wave3_anchors"
U14_LATER = ROOT / "working_assets/e36_recovery_10000_20260730/u14_a2_repair/E36-CW-U14-A2-STILL-V4-CHANGED-INPUT-TERMINAL-REPAIR_0bf2a864-81c1-4379-9745-d1e10a257a0b.png"
U14_LATER_SHA = "958f0320bc7e5315cebbda604b5a56ca0b09d8b62507b337c80d272df260e0dc"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "7e58fc13fa44ea8c6fc3e9cc0ceda115decb96daded61d1e3020f52ecd1c151c"
PAID_BEFORE = 9592

BASE = PROD / "autonomous_recovery_20260731"
SPECS = [
    {
        "slug": "u02_line02", "unit": "U02", "line": 2, "speaker_id": "chenji", "speaker": "陈迹",
        "text": "不能伤官差。", "start": 0.35, "end": 2.45,
        "expression": "十七岁少年克制而急促地立下行动底线",
        "source": BASE / "final_headroom_changed_wave2/u02_line02/E36_U02_CANONICAL_L02_CHANGED_W2_BATCH.json",
        "parent": "7773a2c9-960c-4ced-b6fb-dafdcdef80c1",
        "identity": ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png",
        "identity_sha": "e513b4e9b3a1caba1326e9511136550f94e2add111b3ad897f6f24642d07c4c0",
        "anchor": ANCHORS / "E36_U02_L02_CHANGED_W3_START_ANCHOR.png",
        "action": "陈迹左肩贴住刑台侧木柱借遮挡，左掌压住木柱，头脸向右急转并清楚说出底线",
        "contact": "左肩与左掌持续接触刑台侧木柱",
        "direction": "头脸由柱后向画面右侧转出，躯干保持在柱后",
        "terminal": "末字差落下后闭口吸气，左肩和左掌仍贴木柱，继续观察刑台",
        "environment": "远处官差与人群只作失焦环境层且看不见嘴；尘粒、布幡和衣摆持续轻动",
        "extra": "发音控制：不能／伤／官差三个词组逐字清楚；伤读shāng，官差读guān chāi。",
        "voice": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE",
    },
    {
        "slug": "u09_line10", "unit": "U09", "line": 10, "speaker_id": "messenger", "speaker": "递信人",
        "text": "从不许拆——小的连字都不识几个，拆了也白拆！", "start": 0.20, "end": 5.25,
        "expression": "被缚在木凳上的成年递信人畏缩急切地自证清白",
        "source": BASE / "u09_split_wave3/line10/E36_U09_CANONICAL_L10_WAVE3_BATCH.json",
        "parent": "c61998af-03c8-4ebc-a791-6acfef5a2ef4",
        "identity": ROOT / "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png",
        "identity_sha": "5d3f357346ebf72301abf08f54c9999c05fabcb8cde2856c64f096b8d9180cff",
        "anchor": ANCHORS / "E36_U09_L10_CHANGED_W3_START_ANCHOR.png",
        "action": "递信人被粗绳缚在木凳上，肩背受绳约束仍向前挣动，正脸与嘴全程清楚可见并急切辩解",
        "contact": "粗绳持续压住腰腹和椅背，双腕始终绑在椅背后",
        "direction": "上身仅向镜头左前方挣出后被绳索拉回，不触碰后方空信封",
        "terminal": "白拆完整落下后闭口喘息，躯干被绳拉回椅背，唯一空信封仍在左后桌面静止未触",
        "environment": "烛焰、呼气白雾、窗纸微光与后方布帘持续轻动；陈迹和其他人物彻底不入镜",
        "extra": "句首从不许拆必须完整可听；全句只说一次，不得省略、同义改写、加字或倒序。",
        "voice": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE",
    },
    {
        "slug": "u14_line25", "unit": "U14", "line": 25, "speaker_id": "chenji", "speaker": "陈迹",
        "text": "看各方溅起多大的浪。", "start": 0.30, "end": 3.45,
        "expression": "十七岁陈迹目光锐利地推演各方反应",
        "source": BASE / "final_headroom_changed_wave2/u14_line25/E36_U14_CANONICAL_L25_CHANGED_W2_BATCH.json",
        "parent": "10afbdaa-f3ee-4d23-ad0d-adfb2dd8812f",
        "identity": ROOT / "assets/reference/e36_20260729/characters/CHAR-chenji-age17-canonical-v1-20260729.png",
        "identity_sha": "e513b4e9b3a1caba1326e9511136550f94e2add111b3ad897f6f24642d07c4c0",
        "anchor": ANCHORS / "E36_U14_L25_CHANGED_W3_START_ANCHOR.png",
        "action": "陈迹独自俯身压住桌边，右食指已轻压唯一空信封中央折痕，抬眼清楚说出推演结论",
        "contact": "右食指仅接触空信封中央折痕，左掌持续压住近侧桌沿",
        "direction": "右指沿折痕向前滑不到一指宽后停止，信封始终平铺不位移",
        "terminal": "浪字落下后闭口，右指离开折痕停在一指上方，左掌仍压桌沿，信封完整留桌",
        "environment": "烛焰、药帘和纸角持续轻动；皎兔和其他人物彻底不入镜",
        "extra": "只有一个十七岁陈迹，禁止成年替身、黑衣替身或画外第二人说话。",
        "voice": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE",
    },
    {
        "slug": "u14_line27", "unit": "U14", "line": 27, "speaker_id": "jiaotu", "speaker": "皎兔",
        "text": "拿一条活人命，当量兵的尺。", "start": 0.35, "end": 4.60,
        "expression": "皎兔愤怒而克制地看清活人代价",
        "source": BASE / "ready_terminal_splits_wave1/u14_line27/E36_U14_CANONICAL_L27_SPLIT_W1_BATCH.json",
        "parent": "c9854ba0-7b6a-468d-a4a1-2f503f2bff48",
        "identity": ROOT / "working_assets/e32_reference_single_subject_20260723/jiaotu_front_single.jpg",
        "identity_sha": "267bbaa9f472ae9b42e1ea4ffc0607ad0f1bd823d4774aeb08b705bd640ebfa5",
        "anchor": ANCHORS / "E36_U14_L27_CHANGED_W3_START_ANCHOR.png",
        "action": "皎兔独自急转向左，右手抓住桌沿，左拳收在腰侧，正脸与嘴全程可见并克制地说出活人代价",
        "contact": "右手五指持续抓住近侧桌沿，左拳只贴自己腰带",
        "direction": "头肩由正前方转向画面左侧后稳定，双手不碰信封和纸张",
        "terminal": "尺字落下后闭口深吸气，右手仍抓桌沿，左拳松开一半，目光停在画外陈迹方向",
        "environment": "烛焰、散发和深色药帘持续轻动；陈迹和其他人物彻底不入镜",
        "extra": "仅使用模型原生、rights-cleared 的年轻女声，不模仿任何真实演员，不使用外部音频或克隆音色。",
        "voice": "RIGHTS_CLEARED_MODEL_NATIVE_NO_EXTERNAL_REFERENCE",
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prompt(spec: dict) -> str:
    weather = {
        "U02": "【天气硬合同】weather=HEAT_NOON_DRY_DUST",
        "U09": "【天气硬合同】weather=INTERIOR_CLEAR_HARSH_SUN",
        "U14": "【天气硬合同】weather=INTERIOR_CLEAR_DAY",
    }[spec["unit"]]
    later = "@图片3只作为同场后续状态连续性边界，不复制其中人物构图。" if spec["unit"] == "U14" else ""
    return (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        "【E36 cap-close materially changed solo-speaker wave3】9:16，720p，Seedance Fast 6秒，写实古装电影质感，"
        "严格延续 canonical 年龄、身份、时代、天气和场景；新生成的单人动作首帧为布局权威，禁止复刻父任务画面或音轨。\n"
        f"@图片1只锁定{spec['speaker']}身份；@图片2为本镜头第一帧并锁定单人构图、动作中姿态和场景。{later}"
        "画面从@图片2直接开始，不回到静止站姿，不切镜，不复制人物，不生成可读文字。\n"
        f"{weather}\n"
        f"[[char_{spec['speaker_id']}]] [[scene_{spec['unit'].lower()}_canonical]] [[prop_contact_contract]]\n"
        "【光影与色彩】低饱和灰黑棕 palette；窗光或日光为动机光，烛光只作暖色辅光，保持肤色与衣料纹理真实。\n"
        "【环境介质与力量反馈】角色动作带动衣料、尘粒、火焰或布幔产生连续微小反馈，不让背景冻结。\n"
        f"镜头1【中近景固定机位缓慢微推】0.00-6.00秒：{spec['speaker']}已经在动作中，先完成：{spec['action']}；"
        f"再完成：{spec['direction']}；动作结果：{spec['terminal']}。"
        f"{{对白：{spec['text']}}}<音效>衣料摩擦、木器受力、环境风声与呼吸</音效>\n"
        f"【主体与动作】{spec['action']}。\n"
        f"【接触点】{spec['contact']}。\n"
        f"【方向】{spec['direction']}。\n"
        f"【环境生命层】{spec['environment']}。\n"
        f"【原生对白】唯一可见说话人{spec['speaker']}在{spec['start']:.2f}-{spec['end']:.2f}秒只说一次："
        f"“{spec['text']}”必须自然中文普通话、逐字完整、同步口型、气息、表情和起止时序；不得后配音。\n"
        f"【终态】{spec['terminal']}。末字后保留至少{6-spec['end']:.2f}秒清晰闭口呼吸尾帧。\n"
        f"【专项硬锁】{spec['extra']}\n"
        "禁止：字幕、画面文字、乱码、logo、水印、现代物、年龄漂移、身份交换、画外人声、第二张嘴、静止首帧、重复帧、无因位移、动物。\n"
        "<音效>衣料与木器摩擦、烛焰轻爆、室内风声或远景人群低声；不盖过对白</音效>\n"
    )


def main() -> None:
    jobs = []
    for spec in SPECS:
        source = json.loads(spec["source"].read_text(encoding="utf-8"))
        batch = copy.deepcopy(source)
        task = batch["tasks"][0]
        out = OUT / spec["slug"]
        stem = f"E36_{spec['unit']}_CANONICAL_L{spec['line']:02d}_CHANGED_W3"
        prompt_path = out / f"{stem}_PROMPT.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt(spec), encoding="utf-8")
        prompt_sha = sha(prompt_path)

        dialogue = copy.deepcopy(task["dialogue"][0])
        dialogue.update({
            "dia_id": stem.replace("_", "-"), "speaker_id": spec["speaker_id"], "speaker": spec["speaker"],
            "spoken_text": spec["text"], "start_seconds": spec["start"], "end_seconds": spec["end"],
            "breath_after_seconds": round(6 - spec["end"], 2), "expression": spec["expression"],
            "audio_mode": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY" if spec["speaker_id"] == "jiaotu" else "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True, "external_voice_reference": False,
            "rights_cleared_model_native": spec["speaker_id"] == "jiaotu",
            "unverified_clone_prohibited": spec["speaker_id"] == "jiaotu",
            "path": "", "remote_asset_id": "", "language": "zh-CN", "native_video_audio": True,
            "lip_sync": True, "breath_expression_sync": True,
        })
        dialogue_path = out / f"{stem}_DIALOGUE_MANIFEST.json"
        dump(dialogue_path, {
            "schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS",
            "source_script_sha256": SCRIPT_SHA, "rows": [{k: v for k, v in dialogue.items() if k not in {"language", "native_video_audio", "lip_sync", "breath_expression_sync"}}],
        })

        complete = json.loads((ROOT / batch["complete_video_prompt_manifest_ref"]).read_text(encoding="utf-8"))
        for row in complete.get("rows", []):
            if row.get("unit_id") == spec["unit"]:
                row["prompt_path"] = rel(prompt_path)
                row["prompt_sha256"] = prompt_sha
        complete_path = out / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json"
        dump(complete_path, complete)

        media_rel = f"working_assets/e36_autonomous_recovery_20260731/cap_close_changed_wave3_{spec['slug']}"
        qa_rel = f"qa/e36_agentcut_20260730/cap_close_changed_wave3_{spec['slug']}_runtime"
        (ROOT / media_rel).mkdir(parents=True, exist_ok=True)
        (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)
        batch.update({
            "status": "ready", "source_cl2x": "CL2X-876", "source_cl2x_mailbox_sha256": MAILBOX_SHA,
            "source_mailbox_sha256": MAILBOX_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "episode_paid_credits_before": PAID_BEFORE, "video_credit_limit": 96,
            "output_dir": media_rel, "qa_dir": qa_rel,
            "complete_video_prompt_manifest_ref": rel(complete_path), "dialogue_manifest_ref": rel(dialogue_path),
            "changed_input_parent_task_id": spec["parent"], "changed_input_repair": True,
            "unchanged_retry": False, "max_retries": 0,
        })
        identity_rel = rel(spec["identity"])
        anchor_rel = rel(spec["anchor"])
        reference_images = [identity_rel, anchor_rel]
        reference_sequence = [
            {"asset_label": "@图片1", "role": "CANONICAL_CHARACTER_IDENTITY_REFERENCE", "entity_id": spec["speaker_id"],
             "path": identity_rel, "sha256": spec["identity_sha"], "identity_reference": True},
            {"asset_label": "@图片2", "role": "CHANGED_SOLO_SPEAKER_START_MOTION_AND_SCENE_ANCHOR", "state_id": f"{stem}-START",
             "path": anchor_rel, "sha256": sha(spec["anchor"]), "identity_reference": False},
        ]
        planned_reference_image_count = 1
        if spec["unit"] == "U14":
            reference_images.append(rel(U14_LATER))
            reference_sequence.append({
                "asset_label": "@图片3", "role": "ACCEPTED_LATER_STATE_CONTINUITY_BOUNDARY_NOT_THIS_UNIT_TERMINAL",
                "state_id": "U14-A2", "path": rel(U14_LATER), "sha256": U14_LATER_SHA, "identity_reference": False,
            })
            planned_reference_image_count = 2
        task.update({
            "task_key": stem.replace("_", "-"), "source_id": stem.replace("_", "-"),
            "batch_id": stem.replace("_", "-"), "status": "ready", "model": "seedance-2.0-fast",
            "duration_seconds": 6, "duration": 6, "edit_target_duration_seconds": 6,
            "prompt_path": rel(prompt_path), "prompt_file": rel(prompt_path), "prompt_sha256": prompt_sha,
            "reference_images": reference_images,
            "reference_image_sequence": reference_sequence,
            "planned_reference_image_count": planned_reference_image_count, "state_reference_minimum": planned_reference_image_count,
            "dialogue": [dialogue], "dialogue_audio_assets": [], "reference_audios": [],
            "reference_audio_asset_ids": [], "audio_reference_optional": True,
            "native_dialogue_required": True, "visible_speaker_required": True,
            "visual_entity_ids": [spec["speaker_id"]], "model_native_text_only_dialogue_ids": [dialogue["dia_id"]],
            "changed_input_parent_task_id": spec["parent"], "replaces_parent_task_id": spec["parent"],
            "changed_input_repair": True, "unchanged_retry": False, "max_retries": 0,
            "source_segment_id": spec["slug"], "anchor_image_qa_ref": "qa/e36_agentcut_20260730/E36_CAP_CLOSE_CHANGED_WAVE3_ANCHOR_IMAGE_QA_V1.json",
            "multimodal_entity_bindings": [{
                "entity_id": spec["speaker_id"], "character_name": spec["speaker"],
                "registry_id": {
                    "chenji": "CHAR-陈迹-古装",
                    "messenger": "CHAR-递信人-E36-古装",
                    "jiaotu": "CHAR-皎兔-古装",
                }[spec["speaker_id"]],
                "visual_reference": identity_rel, "visual_reference_sha256": spec["identity_sha"], "identity_image_slot": "@图片1",
                "visible_speaker": True, "lip_sync": True, "prop_owners": {}, "ability_owners": [], "voice_policy": spec["voice"],
            }],
            "performance_spec": {
                "schema": "qingshan.performance_generation_spec.v2", "episode": "E36", "unit_id": spec["unit"],
                "prop_ownership": {"本镜头接触物": spec["contact"]}, "motion_beats": [{
                    "start_seconds": 0.0, "end_seconds": 6.0, "subject": spec["speaker"], "action": spec["action"],
                    "contact_point": spec["contact"], "direction": spec["direction"], "end_state": spec["terminal"],
                    "intent": spec["expression"], "visible_causality": "前镜信息触发角色当场判断或辩解",
                    "expression": spec["expression"], "viewer_read": "主体、动作、接触点、方向、终态及唯一对白均清楚",
                }],
            },
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 6,
                "rationale": "New solo-speaker anchor removes visible-speaker ambiguity while isolating one canonical native-Mandarin line.",
                "edit_policy": "Preserve native Mandarin and lip sync; no post-dub, time stretch, filler or duplicate frames.",
            },
        })
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(
            task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        config_path = out / f"{stem}_BATCH.json"
        dump(config_path, batch)
        jobs.append({
            "unit": spec["unit"], "line": spec["line"], "speaker": spec["speaker"], "config": rel(config_path),
            "config_sha256": sha(config_path), "prompt": rel(prompt_path), "prompt_sha256": prompt_sha,
            "anchor": anchor_rel, "anchor_sha256": sha(spec["anchor"]), "qa_dir": qa_rel, "media_dir": media_rel,
            "projected_credits": 96, "parent_task_id": spec["parent"],
        })

    index_path = OUT / "E36_CAP_CLOSE_CHANGED_WAVE3_INDEX.json"
    dump(index_path, {
        "schema": "qingshan.e36.cap_close_changed_wave3.v1", "status": "READY_FOR_CONCURRENT_PRECHECK",
        "source_cl2x": "CL2X-876", "source_mailbox_sha256": MAILBOX_SHA,
        "source_script_sha256": SCRIPT_SHA, "source_manifest_sha256": MANIFEST_SHA,
        "episode_paid_credits_before": PAID_BEFORE, "projected_credits": 384,
        "projected_episode_total": 9976, "projected_headroom": 24, "jobs": jobs,
    })
    print(json.dumps({"index": rel(index_path), "index_sha256": sha(index_path), "jobs": jobs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
