#!/usr/bin/env python3
"""Compile E32 v2 U04 as the first independently ready video unit."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import (
    evaluate_episode_credit_gate,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from episode_parallel_batch_supervisor import (
    validate_complete_video_prompt_manifest,
    validate_dialogue_manifest_coverage,
    validate_duration_task,
    validate_entity_reference_task,
    validate_writer_agent_provenance,
)
from multimodal_character_binding_guard import binding_digest, evaluate_task as evaluate_binding
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"
MANIFEST = PROD / "E32_PRODUCTION_MANIFEST.json"
PLAN = PROD / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
BASE = PROD / "video_performance_v2"
PROMPT_PATH = BASE / "prompts/E32-CW-U04-PERFORMANCE-V2.txt"
SPEC_PATH = BASE / "specs/E32-CW-U04-PERFORMANCE-SPEC-V2.json"
SCENE_PATH = PROD / "E32_SCENE_AUTHORITY_STATE_V2.json"
DIALOGUE_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
COMPLETE_PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V2.json"
CONFIG_PATH = BASE / "E32_VIDEO_U04_CROSS_SPACE_READY_V2.json"
PRECHECK_PATH = BASE / "qa/E32_VIDEO_U04_CROSS_SPACE_PRECHECK_V2.json"

A1 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U04-A1-STILL-V2_477a078d-d050-4d92-b3b0-6e8b1385819a.png"
A2 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32_E32-CW-U04-A2-STILL-R2_5e820c83-4b36-4b8c-96c2-023d4e8c3f50.png"
IDENTITY = ROOT / "ref_images/female_jiaotu_ref_20260703.jpg"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_u04() -> dict:
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    for row in payload.get("units", payload.get("video_units", [])):
        if row.get("unit_id") == "E32-CW-U04":
            return row
    raise SystemExit("E32-CW-U04 is missing from the canonical v2 performance plan")


def build_prompt() -> str:
    return """《青山》E32 U04，Seedance 2.0 Pro 四模态表演生成，14秒，9:16，720p，原速连续动作。
【实体绑定】现场人物[[char_jiaotu]]、太平医馆与西市暗楼跨空间路径[[scene_e32_cw_s02]]、皎兔阴神能力[[prop_jiaotu_spirit]]；只允许剧本声明实体出现。
【参考图职责】@图片1只定义分离前肉身起态；@图片2只定义阴神抵达西市暗楼的终态；@图片3只锁皎兔同一张脸、发型和服装身份，不是第三个动作状态。中间离体与跨城运动必须由逐拍物理脚本连续生成。
【跨空间摄影合同】这是剧本明确的跨空间连续镜头。摄影从太平医馆室内起步，随阴神穿出窗口并连续飞越雨城，最后抵达西市暗楼二层窗外；允许并要求随地点改变机位和背景，不得把终态锁回医馆。
【色彩与动机光】palette=雨夜冷蓝、医馆油灯暖橙、眉心血光暗红、西市窗灯微暖；光影只来自现场灯火、雨夜天光和剧本声明的阴神能力。
【力量作用环境】力量必须通过环境介质显形：眉心血痕受指腹压力渗出新血；阴神脱离时衣摆与灯焰只向离体方向反馈一次；飞行气流压开迎面雨线；抵达时前冲惯性经右掌传到湿木窗框，窗框只颤动一次后停止。
【声音】无对白，只生成符合动作的现场声、呼吸、雨声、穿窗气流和窗框受力声；禁止旁白与BGM。
镜头1【0.0-6.2秒，中景近景跟移】皎兔肉身右手抬起并按住眉心旧血痕，压出新血；肩背绷紧、咬紧后槽牙。暗红血光亮起后，黑甲阴神沿同一张脸的眉心依次脱出头肩、躯干和双腿，肉身始终留在原位。{无对白}<指腹摩擦、压抑呼吸、衣料绷紧、低沉灵力震鸣>
镜头2【6.2-10.5秒，大远景定场转高速跟拍】阴神转眼锁定西市暗楼，俯身穿出医馆窗口；镜头随她实速越过雨夜屋脊，医馆在身后连续缩小，暗楼在前方连续放大，路线不折返、不闪切。{无对白}<穿窗气流、密集雨声、黑甲破风声>
镜头3【10.5-14.0秒，中景侧移接近景表情特写】阴神接近暗楼后侧身减速，抬起右手抓住湿木窗框；前冲惯性沿右臂传入窗框，雨水甩向前方，窗框轻颤一次。她稳在二层窗外，左手收于身侧，屏息冷峻地转眼观察黑暗室内。{无对白}<掌心抓住湿木、窗框单次轻颤、雨水落甲、克制呼吸>
【连续物理动作脚本】
- 0.0-3.0秒：主体=皎兔肉身；动作=右手食指按住眉心旧血痕，指腹向下压出一线新血，肩背因疼痛绷紧但双脚不移动；接触点=指腹与眉心血痕；方向=压力由指尖向眉心内收；动作目的=观众读懂阴神分离由皎兔主动开启；可见因果=新血和暗红血光从真实接触点出现；表情=克制忍痛，咬紧后槽牙；终态=血痕亮起暗红微光，肉身仍在医馆原位站稳。
- 3.0-6.2秒：主体=皎兔阴神；动作=黑甲阴神沿眉心血光从肉身正面完整脱出，先头肩、再躯干、最后双腿依次分离；接触点=血光与阴神眉心、阴神背部与肉身胸前之间的分离界面；方向=阴神沿正前方斜上方向连续离体；动作目的=观众读懂同一皎兔的肉身与阴神完成分离；可见因果=有先后次序的离体过程消除复制与瞬移歧义；表情=肉身痛楚压抑，阴神冷峻苏醒；终态=阴神与肉身完全分开一臂距离，肉身闭眼承受，阴神睁眼转向窗口。
- 6.2-10.5秒：主体=皎兔阴神；动作=阴神俯身穿出打开的窗，沿雨幕上方朝西市暗楼高速直线飞掠，双臂收于身侧避开屋檐；接触点=脚下气流与窗沿、雨幕与黑甲表面；方向=由医馆窗口向远处暗楼连续前进；动作目的=观众读懂她跨空间赶往暗楼侦察；可见因果=连续变化的屋脊、医馆和暗楼地标证明真实位移；表情=目光锁定暗楼，警觉而果断；终态=医馆在身后缩小，暗楼窗格在前方持续放大。
- 10.5-14.0秒：主体=皎兔阴神；动作=接近暗楼后侧身减速，右手抓住湿木窗框吸收前冲惯性，左手收在身侧，转眼观察窗内；接触点=右掌与湿木窗框、雨水与黑甲；方向=身体由前冲转为窗外稳定，惯性经右臂传到窗框；动作目的=观众读懂她已经抵达并开始隐蔽侦察；可见因果=雨水前甩与窗框单次颤动表现制动，随后完全停止；表情=屏息冷峻，眼神快速确认室内；终态=阴神单独稳在二层窗外，窗内保持黑暗无人。
【单一状态源】人物身份、空间变换、动作时间轴、锚图和能力归属全部服从本任务 spec；禁止新增人物、额外动作、额外台词或道具跳变。
【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、第二个皎兔、把肉身带到暗楼、把阴神留在医馆、融肢、穿模、闪切瞬移、无因腾空、无接触受力、慢放、停帧、循环、周期重复、静帧微动和首尾重复。
"""


def main() -> int:
    for path in (SCRIPT, MANIFEST, PLAN, DIALOGUE_MANIFEST, A1, A2, IDENTITY):
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")
    unit = find_u04()
    if unit.get("planned_reference_image_count") != 2:
        raise SystemExit("U04 canonical anchor decision is not exactly two temporal anchors")

    prompt = build_prompt()
    PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_PATH.write_text(prompt, encoding="utf-8")

    motion_beats = [
        {
            "start_seconds": 0.0, "end_seconds": 3.0, "subject": "皎兔肉身",
            "action": "右手食指按住眉心旧血痕，指腹向下压出一线新血，肩背因疼痛绷紧但双脚不移动",
            "contact_point": "指腹与眉心血痕", "direction": "压力由指尖向眉心内收",
            "end_state": "血痕亮起暗红微光，肉身仍在医馆原位站稳",
            "intent": "观众读懂阴神分离由皎兔主动开启",
            "visible_causality": "新血和暗红血光从真实接触点出现",
            "expression": "克制忍痛，咬紧后槽牙", "viewer_read": "阴神分离由皎兔主动开启而非凭空复制",
        },
        {
            "start_seconds": 3.0, "end_seconds": 6.2, "subject": "皎兔阴神",
            "action": "黑甲阴神沿眉心血光从肉身正面完整脱出，先头肩、再躯干、最后双腿依次分离",
            "contact_point": "血光与阴神眉心、阴神背部与肉身胸前之间的分离界面",
            "direction": "阴神沿正前方斜上方向连续离体",
            "end_state": "阴神与肉身完全分开一臂距离，肉身闭眼承受，阴神睁眼转向窗口",
            "intent": "观众读懂同一皎兔的肉身与阴神完成分离",
            "visible_causality": "有先后次序的离体过程消除复制与瞬移歧义",
            "expression": "肉身痛楚压抑，阴神冷峻苏醒", "viewer_read": "同一身份完成有顺序的肉身与阴神分离",
        },
        {
            "start_seconds": 6.2, "end_seconds": 10.5, "subject": "皎兔阴神",
            "action": "阴神俯身穿出打开的窗，沿雨幕上方朝西市暗楼高速直线飞掠，双臂收于身侧避开屋檐",
            "contact_point": "脚下气流与窗沿、雨幕与黑甲表面", "direction": "由医馆窗口向远处暗楼连续前进",
            "end_state": "医馆在身后缩小，暗楼窗格在前方持续放大",
            "intent": "观众读懂她跨空间赶往暗楼侦察",
            "visible_causality": "连续变化的屋脊、医馆和暗楼地标证明真实位移",
            "expression": "目光锁定暗楼，警觉而果断", "viewer_read": "跨空间路径连续可读而非闪切瞬移",
        },
        {
            "start_seconds": 10.5, "end_seconds": 14.0, "subject": "皎兔阴神",
            "action": "接近暗楼后侧身减速，右手抓住湿木窗框吸收前冲惯性，左手收在身侧，转眼观察窗内",
            "contact_point": "右掌与湿木窗框、雨水与黑甲", "direction": "身体由前冲转为窗外稳定，惯性经右臂传到窗框",
            "end_state": "阴神单独稳在二层窗外，窗内保持黑暗无人",
            "intent": "观众读懂她已经抵达并开始隐蔽侦察",
            "visible_causality": "雨水前甩与窗框单次颤动表现制动，随后完全停止",
            "expression": "屏息冷峻，眼神快速确认室内", "viewer_read": "抵达、制动和侦察目的清楚落地",
        },
    ]
    spec = {
        "schema": "qingshan.performance_generation_spec.v2", "episode": "E32", "unit_id": "E32-CW-U04",
        "duration_seconds": 14,
        "prop_ownership": {
            "眉心血痕": "始终属于皎兔肉身，只由皎兔右手食指触发",
            "黑甲阴神": "始终是皎兔的阴神形态，不是第二个角色",
            "湿木窗框": "属于西市暗楼，只在阴神抵达后由右掌接触",
        },
        "motion_beats": motion_beats,
    }
    write_json(SPEC_PATH, spec)

    bindings = [{
        "entity_id": "jiaotu", "character_name": "皎兔", "registry_id": "CHAR-皎兔-古装",
        "visual_reference": rel(IDENTITY), "visual_reference_sha256": sha(IDENTITY),
        "identity_image_slot": "@图片3", "voice_reference_asset_id": "x2ucerh9xoo",
        "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False,
        "prop_owners": {"眉心血痕": "皎兔肉身", "湿木窗框": "西市暗楼"},
        "ability_owners": ["阴神出窍"],
    }]
    task = {
        "task_key": "E32-CW-U04-PERFORMANCE-V2", "source_id": "E32-CW-U04", "tool_type": "video_generation",
        "generation_mode": "performance_generation", "episode": "E32", "batch_id": "E32-PERFORMANCE-V2",
        "unit_id": "E32-CW-U04", "scene_id": "E32-CW-S02", "visual_zone": "E32-CW-U04-CROSS-SPACE",
        "duration": 14, "duration_seconds": 14, "model": "seedance-2.0-pro",
        "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 14,
                          "rationale": "Exact contiguous Claude v2 script duration.",
                          "edit_policy": "End when scripted result lands; never pad, slow or loop."},
        "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(PROMPT_PATH),
        "prompt_sha256": sha(PROMPT_PATH),
        "reference_images": [rel(A1), rel(A2), rel(IDENTITY)],
        "reference_image_sequence": [
            {"asset_label": "@图片1", "role": "PERFORMANCE_START", "path": rel(A1), "sha256": sha(A1)},
            {"asset_label": "@图片2", "role": "PERFORMANCE_DESTINATION", "path": rel(A2), "sha256": sha(A2)},
            {"asset_label": "@图片3", "role": "IDENTITY_REFERENCE_JIAOTU", "path": rel(IDENTITY), "sha256": sha(IDENTITY)},
        ],
        "state_reference_minimum": 2, "planned_reference_image_count": 2,
        "still_sequence_only_allowed": True, "inherits_establishing_coverage": True, "action_unit": True,
        "performance_spec": spec,
        "keyframe_interpolation_gate": {
            "status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 2,
            "checked_adjacent_pairs": 1, "candidate_recheck_required": False,
            "reason": "A1 and repaired A2 preserve Jiaotu identity and declare a physically traversable medical-hall-to-dark-tower path.",
            "qa_report": "qa/e32_remake_preproduction_20260723/E32_U04_U10_A2_R2_MACHINE_VISUAL_QA_CL2X613.json",
        },
        "dialogue": [], "reference_audios": [], "dialogue_audio_assets": [],
        "native_dialogue_required": False, "audio_reference_optional": True,
        "dialogue_audio_coverage": {"required": 0, "bound": 0, "status": "NOT_APPLICABLE_NO_DIALOGUE"},
        "source_spec": rel(SPEC_PATH), "source_spec_sha256": sha(SPEC_PATH),
        "workflow_credit_scope": "e32_claude_writer_v2_20260723", "status": "READY_TO_SUBMIT",
        "prompt_contract": {
            "source_action": "皎兔阴神从太平医馆完整分离，穿窗掠过雨城并抵达西市暗楼窗外侦察",
            "spatial_continuity": {
                "mode": "CROSS_SPACE_TRANSITION", "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                "origin_scene_id": "E32-CW-S02-MEDICAL-HALL", "destination_scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER",
                "anchor_scope": "VIDEO_WITH_ORIGIN_AND_DESTINATION_ANCHORS", "camera_policy": "ALLOW_AUTHORED_DESTINATION_CAMERA",
            },
        },
        "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings),
        "effect_provenance": [{"effect": "阴神", "source_type": "CANONICAL_ABILITY", "source_ref": "E32剧本_ClaudeWriter_v2.md#5-2"}],
    }
    task["generation_fingerprint"] = generation_fingerprint(task)

    manifest_sha = sha(MANIFEST)
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E32", "status": "READY_INCREMENTAL_UNITS",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "targeted_unit_replacement": True,
        "concurrency": 1, "max_retries": 0, "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e32_claude_writer_v2_20260723", "video_credit_limit": 6000,
        "source_script_sha256": sha(SCRIPT),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "complete_video_prompt_manifest_ref": rel(COMPLETE_PROMPT_MANIFEST),
        "writer_agent_provenance": {
            "status": "PASS", "provenance_type": "claude_writer_script", "source_script": rel(SCRIPT),
            "source_script_sha256": sha(SCRIPT), "production_manifest": rel(MANIFEST),
            "production_manifest_sha256": manifest_sha,
        },
        "scene_contract_ref": rel(SCENE_PATH), "supervisor_script_gate_required": False,
        "space_camera_constraint_gate_required": True,
        "output_dir": rel(BASE / "outputs"), "qa_dir": rel(BASE / "qa"), "tasks": [task],
    }

    v1_scene = json.loads((ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722/E32_SCENE_AUTHORITY_STATE_V1.json").read_text(encoding="utf-8"))
    v1_scene.update({"schema": "qingshan.scene_authority_state.v2", "source_script": rel(SCRIPT), "source_script_sha256": sha(SCRIPT)})
    write_json(SCENE_PATH, v1_scene)
    write_json(CONFIG_PATH, config)

    complete_prompt_gate = validate_complete_video_prompt_manifest(config)
    prompt_gate = evaluate_prompt_professionalism(config)
    dialogue_gate = validate_dialogue_manifest_coverage(config)
    space_gate = evaluate_space_camera(config["tasks"], {task["task_key"]: prompt})
    binding_gate = evaluate_binding(task)
    scene_gate = evaluate_scene_authority(SCENE_PATH, config)
    entity_failures = validate_entity_reference_task(task)
    duration_failures = validate_duration_task(task)
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    credit_gate = evaluate_episode_credit_gate("E32", limit=6000)
    existing = find_existing_paid_candidate("E32", task)
    precheck = {
        "schema": "qingshan.e32_u04_cross_space_video_precheck.v2", "episode": "E32", "unit_id": "E32-CW-U04",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "writer_provenance": {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures},
            "complete_video_prompt_manifest": complete_prompt_gate,
            "dialogue_manifest_coverage": dialogue_gate,
            "prompt_professionalism": prompt_gate, "space_camera_constraint": space_gate,
            "multimodal_character_binding": binding_gate, "scene_authority": scene_gate,
            "entity_reference_sequence": {"status": "PASS" if not entity_failures else "FAIL", "failures": entity_failures},
            "duration_policy": {"status": "PASS" if not duration_failures else "FAIL", "failures": duration_failures},
            "generation_deduplication": {"status": "PASS" if existing is None else "FAIL", "existing_candidate": existing,
                                             "generation_fingerprint": task["generation_fingerprint"]},
            "current_workflow_credit_gate": credit_gate,
        },
    }
    statuses = [
        "PASS" if writer_ok else "FAIL", complete_prompt_gate.get("status"), dialogue_gate.get("status"), prompt_gate.get("status"), space_gate.get("status"),
        binding_gate.get("status"), scene_gate.get("status"), "PASS" if not entity_failures else "FAIL",
        "PASS" if not duration_failures else "FAIL", "PASS" if existing is None else "FAIL", credit_gate.get("status"),
    ]
    precheck["status"] = "PASS" if all(value == "PASS" for value in statuses) else "FAIL"
    precheck["config"] = rel(CONFIG_PATH)
    write_json(PRECHECK_PATH, precheck)
    print(json.dumps({"status": precheck["status"], "config": rel(CONFIG_PATH), "precheck": rel(PRECHECK_PATH),
                      "generation_fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0 if precheck["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
