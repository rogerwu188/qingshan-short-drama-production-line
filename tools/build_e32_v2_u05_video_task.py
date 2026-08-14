#!/usr/bin/env python3
"""Compile independently ready E32 v2 U05 without duplicating its sole image."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import evaluate_episode_credit_gate, find_existing_paid_candidate, generation_fingerprint
from episode_parallel_batch_supervisor import validate_complete_video_prompt_manifest, validate_dialogue_manifest_coverage, validate_duration_task, validate_entity_reference_task, validate_writer_agent_provenance
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
COMPLETE_PROMPT_MANIFEST = BASE / "E32_ALL_17_VIDEO_PROMPT_MANIFEST_V2.json"
PROMPT = BASE / "prompts/E32-CW-U05-PERFORMANCE-V2.txt"
SPEC = BASE / "specs/E32-CW-U05-PERFORMANCE-SPEC-V2.json"
CONFIG = BASE / "E32_VIDEO_U05_SINGLE_ANCHOR_READY_V2.json"
PRECHECK = BASE / "qa/E32_VIDEO_U05_SINGLE_ANCHOR_PRECHECK_V2.json"
A1 = ROOT / "working_assets/e32_remake_v2_stills_20260723/candidates/E32-CW-U05-A1-STILL-V2_93e23a3a-87f4-43e5-8f19-c87ae983ee13.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    for path in (SCRIPT, MANIFEST, PLAN, SCENE, DIALOGUE_MANIFEST, A1):
        if not path.is_file():
            raise SystemExit(f"required input missing: {path}")
    units = json.loads(PLAN.read_text(encoding="utf-8")).get("units", [])
    unit = next(row for row in units if row.get("unit_id") == "E32-CW-U05")
    if unit.get("planned_reference_image_count") != 1:
        raise SystemExit("U05 canonical action design no longer authorizes one temporal anchor")

    prompt_text = """《青山》E32 U05，Seedance 2.0 Pro 四模态表演生成，8秒，9:16，720p，原速连续动作。
【实体绑定】现场人物[[char_qisan]]、西市暗楼油灯内室[[scene_e32_cw_s02_dark_tower]]、名单与信封[[prop_e32_u05_letters]]；只允许剧本声明实体出现。
【参考图职责】@图片1同时锁定齐三的备案身份、西市暗楼起始空间和表演起态；它只计一个时间锚。Seedance 按连续动作脚本生成拆分、装信和排列全过程，不要求不存在的第二状态图。
【色彩与动机光】palette=雨夜冷蓝、室内油灯暗金、湿木深褐、灰袍低饱和；光影只来自油灯和窗外雨夜天光，始终保持同一间暗楼内室。
【力量作用环境】力量通过环境介质显形：指腹摩擦纸张，名单在案面受推力分成三叠，信封口被拇指撑开，装入时纸边只弯曲一次并回弹，油灯火焰只因手臂掠过轻偏一次。
【声音】无对白，只生成纸张、信封、衣袖、油灯和压低呼吸的现场声；禁止旁白与BGM。
镜头1【0.0-3.0秒，中景俯侧机位缓慢推近】齐三坐在油灯案前，左掌压住同一叠名单，右手拇指从上到下连续数页；他抬眼快速扫向紧闭木门，确认无人后把名单向左、中、右推成三叠。{无对白}<纸张摩擦、衣袖擦案、雨打窗纸、克制呼吸>
镜头2【3.0-6.3秒，近景横移跟手】齐三左手依次撑开三个不同封色的信封，右手把左、中、右三叠名单逐份装入对应信封；每张纸只能从齐三手中进入一次，不复制、不瞬移，空信封随装入逐个变厚。{无对白}<信封撑开、纸边滑入、油灯轻响>
镜头3【6.3-8.0秒，中近景抬升至表情特写】齐三把三封信横向排开，右指逐封压平封口，最后将手停在中央信封上；他嘴角浮出短暂贪意，又因门外雨声骤密收住笑意并警觉侧听。{无对白}<封口压平、指节敲案一次、雨声加密>
【连续物理动作脚本】
- 0.0-3.0秒：主体=齐三；动作=左掌压住名单，右手拇指数页后将同一叠名单推分为左中右三叠；接触点=左掌与纸面、右拇指与纸边；方向=纸张从案心向左中右分开；动作目的=观众看懂这些名单来自同一批消息；可见因果=每一叠都由同一原叠经齐三双手连续分出；表情=贪婪中保持警觉，先看门再低头；终态=三叠名单彼此分开并保持在案面。
- 3.0-6.3秒：主体=齐三；动作=左手逐个撑开三只信封，右手把三叠名单逐份装入；接触点=左拇指与信封口、右指与纸叠边缘；方向=纸叠从案面向各自信封内前进；动作目的=观众看懂他准备把同一消息卖给多家；可见因果=每只信封随纸张进入逐个变厚，已装入的纸不再回到案面；表情=动作熟练，眼底贪意加深；终态=三只信封都装有名单，案面不再有散纸。
- 6.3-8.0秒：主体=齐三；动作=双手把三封信横向排开并逐封压平封口，右手停在中央信封上；接触点=掌缘与信封封口、指腹与案面；方向=信封由身体前方横向排成一列；动作目的=观众确认这是三条不同交易去向；可见因果=三个封色不同且位置分离，齐三逐封完成封口；表情=嘴角短暂贪笑后因门外雨声收紧；终态=三封信整齐分列，齐三侧耳警觉。
【单一状态源】齐三身份、名单与信封归属、动作时间轴和唯一锚图全部服从本任务 spec；禁止新增人物、额外台词、复制纸张或无接触装信。
【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、第二个齐三、现代服装、尸检官身份、融肢、穿模、纸张复制、信封跳位、慢放、停帧、循环、周期重复、静帧微动和首尾重复。
"""
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt_text, encoding="utf-8")

    beats = [
        {"start_seconds": 0.0, "end_seconds": 3.0, "subject": "齐三",
         "action": "左掌压住名单，右手拇指数页后将同一叠名单推分为左中右三叠",
         "contact_point": "左掌与纸面、右拇指与纸边", "direction": "纸张从案心向左中右分开",
         "end_state": "三叠名单彼此分开并保持在案面", "intent": "观众看懂这些名单来自同一批消息",
         "visible_causality": "每一叠都由同一原叠经齐三双手连续分出", "expression": "贪婪中保持警觉，先看门再低头",
         "viewer_read": "齐三正在把同一批名单拆成多份"},
        {"start_seconds": 3.0, "end_seconds": 6.3, "subject": "齐三",
         "action": "左手逐个撑开三只信封，右手把三叠名单逐份装入",
         "contact_point": "左拇指与信封口、右指与纸叠边缘", "direction": "纸叠从案面向各自信封内前进",
         "end_state": "三只信封都装有名单，案面不再有散纸", "intent": "观众看懂他准备把同一消息卖给多家",
         "visible_causality": "每只信封随纸张进入逐个变厚，已装入的纸不再回到案面", "expression": "动作熟练，眼底贪意加深",
         "viewer_read": "同一消息正被装入多封不同去向的信"},
        {"start_seconds": 6.3, "end_seconds": 8.0, "subject": "齐三",
         "action": "双手把三封信横向排开并逐封压平封口，右手停在中央信封上",
         "contact_point": "掌缘与信封封口、指腹与案面", "direction": "信封由身体前方横向排成一列",
         "end_state": "三封信整齐分列，齐三侧耳警觉", "intent": "观众确认这是三条不同交易去向",
         "visible_causality": "三个封色不同且位置分离，齐三逐封完成封口", "expression": "嘴角短暂贪笑后因门外雨声收紧",
         "viewer_read": "齐三熟练完成多方交易准备"},
    ]
    spec = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E32", "unit_id": "E32-CW-U05",
            "duration_seconds": 8, "prop_ownership": {"名单": "始终由齐三双手拆分并装入信封", "三只信封": "始终位于齐三案面"},
            "motion_beats": beats}
    write_json(SPEC, spec)

    bindings = [{"entity_id": "qisan", "character_name": "齐三", "registry_id": "CHAR-齐三-古装",
                 "visual_reference": rel(A1), "visual_reference_sha256": sha(A1), "identity_image_slot": "@图片1",
                 "voice_reference_asset_id": "ubepnv100tm", "dialogue_audio_slots": [], "visible_speaker": False,
                 "lip_sync": False, "prop_owners": {"名单": "齐三", "信封": "齐三"}, "ability_owners": []}]
    task = {
        "task_key": "E32-CW-U05-PERFORMANCE-V2", "source_id": "E32-CW-U05", "tool_type": "video_generation",
        "generation_mode": "performance_generation", "episode": "E32", "batch_id": "E32-PERFORMANCE-V2",
        "unit_id": "E32-CW-U05", "scene_id": "E32-CW-S02", "visual_zone": "E32-CW-U05-DARK-TOWER-INTERIOR",
        "duration": 8, "duration_seconds": 8, "model": "seedance-2.0-pro",
        "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": 8,
                          "rationale": "Exact contiguous Claude v2 script duration.", "edit_policy": "End on the sealed-envelope and alert-listening result; never pad, slow or loop."},
        "aspect_ratio": "9:16", "resolution": "720p", "prompt_file": rel(PROMPT), "prompt_sha256": sha(PROMPT),
        "reference_images": [rel(A1)],
        "reference_image_sequence": [{"asset_label": "@图片1", "role": "PERFORMANCE_START", "path": rel(A1),
                                      "sha256": sha(A1), "identity_reference": True}],
        "state_reference_minimum": 1, "planned_reference_image_count": 1, "still_sequence_only_allowed": True,
        "inherits_establishing_coverage": True, "action_unit": True, "performance_spec": spec,
        "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": 1,
                                        "checked_adjacent_pairs": 0, "candidate_recheck_required": False,
                                        "reason": "One canonical Qisan start image and the continuous paper-handling script are sufficient for this same-space action."},
        "dialogue": [], "reference_audios": [], "dialogue_audio_assets": [], "native_dialogue_required": False,
        "audio_reference_optional": True, "dialogue_audio_coverage": {"required": 0, "bound": 0, "status": "NOT_APPLICABLE_NO_DIALOGUE"},
        "source_spec": rel(SPEC), "source_spec_sha256": sha(SPEC), "workflow_credit_scope": "e32_claude_writer_v2_20260723",
        "status": "READY_TO_SUBMIT",
        "prompt_contract": {"source_action": "齐三在西市暗楼同一间油灯内室把同一叠名单拆成多份并装入不同信封",
                            "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                                                   "scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER", "anchor_scope": "ORIGIN_ONLY",
                                                   "camera_policy": "ALLOW_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT"}},
        "multimodal_entity_bindings": bindings, "multimodal_binding_sha256": binding_digest(bindings), "effect_provenance": [],
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E32", "status": "READY_INCREMENTAL_UNITS",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "targeted_unit_replacement": True, "concurrency": 1,
        "max_retries": 0, "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e32_claude_writer_v2_20260723", "video_credit_limit": 6000,
        "source_script_sha256": sha(SCRIPT),
        "dialogue_manifest_ref": rel(DIALOGUE_MANIFEST),
        "complete_video_prompt_manifest_ref": rel(COMPLETE_PROMPT_MANIFEST),
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": rel(SCRIPT),
                                    "source_script_sha256": sha(SCRIPT), "production_manifest": rel(MANIFEST),
                                    "production_manifest_sha256": sha(MANIFEST)},
        "scene_contract_ref": rel(SCENE), "supervisor_script_gate_required": False, "space_camera_constraint_gate_required": True,
        "output_dir": rel(BASE / "outputs"), "qa_dir": rel(BASE / "qa"), "tasks": [task],
    }
    write_json(CONFIG, config)
    checks = {
        "complete_video_prompt_manifest": validate_complete_video_prompt_manifest(config),
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
    report = {"schema": "qingshan.e32_u05_single_anchor_video_precheck.v2", "episode": "E32", "unit_id": "E32-CW-U05",
              "status": "PASS" if all(value == "PASS" for value in statuses) else "FAIL", "checks": checks,
              "config": rel(CONFIG), "recorded_at": datetime.now(timezone.utc).isoformat()}
    write_json(PRECHECK, report)
    print(json.dumps({"status": report["status"], "config": rel(CONFIG), "precheck": rel(PRECHECK),
                      "generation_fingerprint": task["generation_fingerprint"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
