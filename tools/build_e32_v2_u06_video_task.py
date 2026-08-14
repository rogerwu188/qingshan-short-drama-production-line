#!/usr/bin/env python3
"""Compile independently ready E32 v2 U06 with separate temporal and identity anchors."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import evaluate_episode_credit_gate, find_existing_paid_candidate, generation_fingerprint
from episode_parallel_batch_supervisor import validate_dialogue_manifest_coverage, validate_duration_task, validate_entity_reference_task, validate_writer_agent_provenance
from multimodal_character_binding_guard import binding_digest, evaluate_task as evaluate_binding
from scene_authority_lock import evaluate_batch as evaluate_scene_authority
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v2.md"
MANIFEST = PROD / "E32_PRODUCTION_MANIFEST.json"
PLAN = PROD / "E32_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
SCENE = PROD / "E32_SCENE_AUTHORITY_STATE_V2.json"
DIALOGUE_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BASE = PROD / "video_performance_v2"
PROMPT = BASE / "prompts/E32-CW-U06-PERFORMANCE-V2.txt"
SPEC = BASE / "specs/E32-CW-U06-PERFORMANCE-SPEC-V2.json"
CONFIG = BASE / "E32_VIDEO_U06_ENTRY_CONFRONTATION_READY_V2.json"
PRECHECK = BASE / "qa/E32_VIDEO_U06_ENTRY_CONFRONTATION_PRECHECK_V2.json"

A1 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U06-A1-STILL-V2_7ffe38bb-427a-457f-8431-6b4039ccf981.png"
CHENJI_IDENTITY = ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
QISAN_IDENTITY = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U05-A1-STILL-V2_93e23a3a-87f4-43e5-8f19-c87ae983ee13.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    for path in (SCRIPT, MANIFEST, PLAN, SCENE, DIALOGUE_MANIFEST, A1, CHENJI_IDENTITY, QISAN_IDENTITY):
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")
    units = json.loads(PLAN.read_text(encoding="utf-8")).get("units", [])
    unit = next(row for row in units if row.get("unit_id") == "E32-CW-U06")
    if unit.get("planned_reference_image_count") != 1:
        raise SystemExit("U06 canonical action design no longer authorizes one temporal anchor")

    prompt_text = """《青山》E32 U06，Seedance 2.0 Pro 四模态表演生成，5秒，9:16，720p，原速连续动作。
【实体绑定】现场人物[[char_chenji]]、[[char_qisan]]、西市暗楼油灯内室[[scene_e32_cw_s02_dark_tower]]、油灯与三封信[[prop_e32_u06_lamp_letters]]、陈迹冰流能力[[ability_chenji_iceflow]]；只允许剧本声明实体出现。
【参考图职责】@图片1只锁定暗楼门口、案桌、油灯、信封和两人表演起态，是唯一时间锚；@图片2只锁陈迹年轻面貌、灰色学徒袍与挺直体态；@图片3只锁齐三备案面貌与灰袍身份。身份图不是额外动作状态，连续突袭完全由下列逐拍物理脚本驱动。
【色彩与动机光】palette=雨夜冷蓝、室内油灯暗金、湿木深褐、灰袍低饱和；先由油灯照亮案面，灯灭后只保留门外冷蓝雨光和冰流沿地面的蓝白反光。
【力量作用环境】门板受陈迹左肩和前臂推力向内撞开一次；金属灯罩受右掌向下压力盖住灯芯；冰流从陈迹左掌接触的门槛雨水向案桌下方连续延伸并封住齐三退路；齐三后腰撞到案沿后，三封信受碰撞惯性向外滑散一次并停止。
【声音】无对白，只生成破门、脚步、灯罩压下、火焰熄灭、冰流冻结、案桌受撞、信封滑动、急促呼吸和雨声；禁止旁白与BGM。
镜头1【0.0-1.5秒，中景门内侧低机位快速后移】陈迹左肩与前臂抵住半闭湿木门，向室内连续施力把门撞开；他跨过门槛后双脚落稳，年轻面容冷定、下颌微收、目光始终压住齐三。齐三被响声惊动，双肩骤抬，抓信封的手停在案面。{无对白}<木门撞开一次、湿鞋踏地、雨声灌入、齐三吸气>
镜头2【1.5-3.0秒，中近景横移跟随陈迹右手】陈迹不转身，右掌准确压下油灯的小金属灯罩；灯罩盖住灯芯，暗金火焰立刻熄灭，室内由暖暗转成门外冷蓝轮廓光。齐三瞳孔收紧，身体开始向案桌后方退。{无对白}<金属灯罩落下、火焰噗灭、衣袖破风>
镜头3【3.0-5.0秒，贴地近景跟冰流抬升至双人中景】陈迹左掌按住门槛积水，蓝白冰流从真实接触点贴地向前，绕过陈迹双脚并在齐三身后合拢成半圆冰脊，清楚封住唯一退路；冰光反亮被盖住的灯罩和案面。齐三惊恐后退，后腰撞到案沿，三封信向外滑散一次后停住；陈迹留在门口挺直站立，以冷定眼神完成封门压迫。{无对白}<冰面连续冻结、案桌闷响、三封信滑动一次、齐三急促呼吸>
【连续物理动作脚本】
- 0.0-1.5秒：主体=陈迹；动作=左肩和前臂抵住半闭湿木门，向室内连续推开并跨过门槛；接触点=左肩前臂与门板、鞋底与湿门槛；方向=门板向室内打开，陈迹身体由门外向室内前进；动作目的=观众看懂陈迹主动突袭并占住出口；可见因果=门板随肩臂推力撞开一次，雨声与冷光同时灌入；表情=年轻面容冷定，下颌微收，目光锁住齐三；终态=陈迹双脚落稳在门口，门完全打开，齐三受惊停手。
- 1.5-3.0秒：主体=陈迹；动作=右掌向下压住油灯小金属灯罩，使灯罩完全覆盖灯芯；接触点=右掌与金属灯罩顶部、灯罩边缘与灯座；方向=压力垂直向下；动作目的=观众看懂陈迹主动夺走齐三对室内光线的控制；可见因果=灯罩落下后火焰立即熄灭，暖光消失而冷蓝门光接管画面；表情=陈迹动作短促果断，齐三瞳孔收紧并露出惊惧；终态=油灯熄灭，陈迹仍封住门口，齐三向后退。
- 3.0-5.0秒：主体=陈迹与齐三；动作=陈迹左掌按住门槛积水，冰流由接触点贴地延伸并在齐三身后合拢成半圆冰脊；齐三后退撞上案沿并碰散三封信；接触点=陈迹左掌与积水、冰流与地面、齐三后腰与案沿、信封与案面；方向=冰流由门槛向齐三身后前进并合拢，信封由案心向外滑动；动作目的=观众看懂陈迹用冰流封死齐三退路并逼出证据；可见因果=冰脊在齐三身后形成明确障碍，齐三因退路被封撞桌，三封信随单次碰撞显露；表情=陈迹冷定压迫，齐三眉眼张大、嘴角绷紧、呼吸急促；终态=半圆冰脊封路，三封信分散可见并停止，齐三被困在案桌与冰脊之间。
【单一状态源】陈迹与齐三身份、油灯和信封归属、冰流能力、动作时间轴与唯一时间锚全部服从本任务 spec；禁止新增人物、额外动作、额外台词、无接触灭灯、无来源冰流或信封自行移动。
【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、人物增殖、陈迹变老、陈迹黑袍、现代服装、融肢、穿模、徒手触碰火焰、灯芯自行熄灭、冰流悬空、冰脊瞬移、信封复制、慢放、停帧、循环、周期重复、静帧微动和首尾重复。
"""
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt_text, encoding="utf-8")

    beats = [
        {"start_seconds": 0.0, "end_seconds": 1.5, "subject": "陈迹",
         "action": "左肩和前臂抵住半闭湿木门，向室内连续推开并跨过门槛",
         "contact_point": "左肩前臂与门板、鞋底与湿门槛", "direction": "门板向室内打开，陈迹由门外向室内前进",
         "end_state": "陈迹双脚落稳在门口，门完全打开，齐三受惊停手", "intent": "观众看懂陈迹主动突袭并占住出口",
         "visible_causality": "门板随肩臂推力撞开一次，雨声与冷光同时灌入",
         "expression": "年轻面容冷定，下颌微收，目光锁住齐三", "viewer_read": "陈迹破门并控制唯一出口"},
        {"start_seconds": 1.5, "end_seconds": 3.0, "subject": "陈迹",
         "action": "右掌向下压住油灯小金属灯罩，使灯罩完全覆盖灯芯",
         "contact_point": "右掌与金属灯罩顶部、灯罩边缘与灯座", "direction": "压力垂直向下",
         "end_state": "油灯熄灭，陈迹仍封住门口，齐三向后退", "intent": "观众看懂陈迹主动夺走齐三对室内光线的控制",
         "visible_causality": "灯罩落下后火焰立即熄灭，暖光消失而冷蓝门光接管画面",
         "expression": "陈迹动作短促果断，齐三瞳孔收紧并露出惊惧", "viewer_read": "陈迹用真实接触动作灭灯并控制光线"},
        {"start_seconds": 3.0, "end_seconds": 5.0, "subject": "陈迹与齐三",
         "action": "陈迹左掌按住门槛积水，冰流贴地延伸并在齐三身后合拢；齐三后退撞上案沿并碰散三封信",
         "contact_point": "陈迹左掌与积水、冰流与地面、齐三后腰与案沿、信封与案面",
         "direction": "冰流由门槛向齐三身后前进并合拢，信封由案心向外滑动",
         "end_state": "半圆冰脊封路，三封信分散可见并停止，齐三被困在案桌与冰脊之间",
         "intent": "观众看懂陈迹用冰流封死齐三退路并逼出证据",
         "visible_causality": "冰脊形成障碍，齐三因退路被封撞桌，三封信随单次碰撞显露",
         "expression": "陈迹冷定压迫，齐三眉眼张大、嘴角绷紧、呼吸急促", "viewer_read": "冰流封路导致齐三撞桌并暴露信封"},
    ]
    spec = {
        "schema": "qingshan.performance_generation_spec.v2", "episode": "E32", "unit_id": "E32-CW-U06",
        "duration_seconds": 5,
        "prop_ownership": {"油灯与金属灯罩": "始终位于齐三案桌，只由陈迹右掌压下灯罩灭火", "三封信": "始终属于齐三并位于案面，只因齐三撞桌滑散", "冰流": "始终由陈迹左掌接触门槛积水后发动"},
        "motion_beats": beats,
    }
    write_json(SPEC, spec)

    bindings = [
        {"entity_id": "chenji", "character_name": "陈迹", "registry_id": "CHAR-陈迹-古装",
         "visual_reference": rel(CHENJI_IDENTITY), "visual_reference_sha256": sha(CHENJI_IDENTITY), "identity_image_slot": "@图片2",
         "voice_reference_asset_id": "cypqud0bu7t", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False,
         "prop_owners": {"油灯金属灯罩": "陈迹右掌控制", "门板": "陈迹左肩前臂推动"}, "ability_owners": ["冰流"]},
        {"entity_id": "qisan", "character_name": "齐三", "registry_id": "CHAR-齐三-古装",
         "visual_reference": rel(QISAN_IDENTITY), "visual_reference_sha256": sha(QISAN_IDENTITY), "identity_image_slot": "@图片3",
         "voice_reference_asset_id": "ubepnv100tm", "dialogue_audio_slots": [], "visible_speaker": False, "lip_sync": False,
         "prop_owners": {"三封信": "齐三", "案桌": "齐三所在案桌"}, "ability_owners": []},
    ]
    task = {
        "task_key": "E32-CW-U06-PERFORMANCE-V2", "source_id": "E32-CW-U06", "tool_type": "video_generation",
        "generation_mode": "performance_generation", "episode": "E32", "batch_id": "E32-PERFORMANCE-V2",
        "unit_id": "E32-CW-U06", "scene_id": "E32-CW-S02", "visual_zone": "E32-CW-U06-DARK-TOWER-ENTRY",
        "duration": 5, "duration_seconds": 5, "model": "seedance-2.0-pro",
        "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 5,
                          "rationale": "Exact contiguous Claude v2 script duration.", "edit_policy": "End on the sealed retreat and exposed letters; never pad, slow or loop."},
        "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(PROMPT), "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(A1), rel(CHENJI_IDENTITY), rel(QISAN_IDENTITY)],
        "reference_image_sequence": [
            {"asset_label": "@图片1", "role": "PERFORMANCE_START", "path": rel(A1), "sha256": sha(A1)},
            {"asset_label": "@图片2", "role": "IDENTITY_REFERENCE_CHENJI", "path": rel(CHENJI_IDENTITY), "sha256": sha(CHENJI_IDENTITY), "identity_reference": True},
            {"asset_label": "@图片3", "role": "IDENTITY_REFERENCE_QISAN", "path": rel(QISAN_IDENTITY), "sha256": sha(QISAN_IDENTITY), "identity_reference": True},
        ],
        "state_reference_minimum": 1, "planned_reference_image_count": 1, "still_sequence_only_allowed": True,
        "inherits_establishing_coverage": True, "action_unit": True, "performance_spec": spec,
        "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1,
                                         "checked_adjacent_pairs": 0, "candidate_recheck_required": False,
                                         "reason": "One scene start anchor plus independent canonical identity locks are sufficient for the authored continuous entry action."},
        "dialogue": [], "reference_audios": [], "dialogue_audio_assets": [], "native_dialogue_required": False,
        "audio_reference_optional": True, "dialogue_audio_coverage": {"required": 0, "bound": 0, "status": "NOT_APPLICABLE_NO_DIALOGUE"},
        "source_spec": rel(SPEC), "source_spec_sha256": sha(SPEC), "workflow_credit_scope": "e32_claude_writer_v2_20260723",
        "status": "READY_TO_SUBMIT",
        "prompt_contract": {"source_action": "陈迹破门压灭油灯，以冰流封住齐三退路；齐三撞桌使三封信滑散",
                            "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                                                   "scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER", "anchor_scope": "ORIGIN_ONLY",
                                                   "camera_policy": "ALLOW_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT"}},
        "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings),
        "effect_provenance": [{"effect": "冰流", "source_type": "CANONICAL_ABILITY", "source_ref": "E32剧本_ClaudeWriter_v2.md#5-3"}],
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E32", "status": "READY_INCREMENTAL_UNITS",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "targeted_unit_replacement": True, "concurrency": 1,
        "max_retries": 0, "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e32_claude_writer_v2_20260723", "video_credit_limit": 6000, "source_script_sha256": sha(SCRIPT),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": rel(SCRIPT),
                                    "source_script_sha256": sha(SCRIPT), "production_manifest": rel(MANIFEST),
                                    "production_manifest_sha256": sha(MANIFEST)},
        "scene_contract_ref": rel(SCENE), "supervisor_script_gate_required": False, "space_camera_constraint_gate_required": True,
        "output_dir": rel(BASE / "outputs"), "qa_dir": rel(BASE / "qa"), "tasks": [task],
    }
    write_json(CONFIG, config)
    checks = {
        "dialogue_manifest_coverage": validate_dialogue_manifest_coverage(config),
        "prompt_professionalism": evaluate_prompt_professionalism(config),
        "space_camera_constraint": evaluate_space_camera(config["tasks"], {task["task_key"]: prompt_text}),
        "multimodal_character_binding": evaluate_binding(task), "scene_authority": evaluate_scene_authority(SCENE, config),
        "entity_reference_sequence": {"status": "PASS" if not (e := validate_entity_reference_task(task)) else "FAIL", "failures": e},
        "duration_policy": {"status": "PASS" if not (d := validate_duration_task(task)) else "FAIL", "failures": d},
        "generation_deduplication": {"status": "PASS" if (existing := find_existing_paid_candidate("E32", task)) is None else "FAIL",
                                     "existing_candidate": existing, "generation_fingerprint": task["generation_fingerprint"]},
        "current_workflow_credit_gate": evaluate_episode_credit_gate("E32", limit=6000),
    }
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    checks["writer_provenance"] = {"status": "PASS" if writer_ok else "FAIL", "failures": writer_failures}
    statuses = [row.get("status") for row in checks.values()]
    report = {"schema": "qingshan.e32_u06_entry_confrontation_video_precheck.v2", "episode": "E32", "unit_id": "E32-CW-U06",
              "status": "PASS" if all(value == "PASS" for value in statuses) else "FAIL", "checks": checks,
              "config": rel(CONFIG), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK),
                      "generation_fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
