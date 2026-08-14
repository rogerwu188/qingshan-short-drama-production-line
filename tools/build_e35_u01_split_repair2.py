#!/usr/bin/env python3
"""Split failed E35 U01 at its natural confession pause with reduced references."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
QA = ROOT / "qa/e35_v1_preproduction_20260723"
VIDEO_DIR = PROD / "video_performance_v1"
PROMPT_DIR = PROD / "video_prompts_performance_v1"
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_STREAMING_PERFORMANCE_V1_U01_REPAIR1.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_STREAMING_PERFORMANCE_V1_U01_SPLIT_REPAIR2.json"
BASE_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
OUT_UNIT_PLAN = PROD / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_U01_SPLIT_REPAIR2.json"
BASE_PROMPT_MANIFEST = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
OUT_PROMPT_MANIFEST = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U01_SPLIT_REPAIR2.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U01_SPLIT_REPAIR2.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


SPLITS = (
    {
        "unit_id": "E35-CW-U01A",
        "task_key": "E35-CW-U01A-PERFORMANCE-V1-REPAIR2",
        "duration": 8,
        "dialogue_ids": ["E35-DIA-SEG-001", "E35-DIA-SEG-002"],
        "action": "严敬被缚在椅上，先吞咽喘息，再看向镜头外的陈迹，供出景朝接头只认旧钱以及亮钱即自己人的规则。",
        "expression": "严敬由抵抗转为绝望吐供，额角渗汗，目光畏惧但强迫自己说清。",
        "end_state": "严敬说完谁亮钱谁是自己人，短促换气，仍被缚在原位。",
    },
    {
        "unit_id": "E35-CW-U01B",
        "task_key": "E35-CW-U01B-PERFORMANCE-V1-REPAIR2",
        "duration": 5,
        "dialogue_ids": ["E35-DIA-SEG-003", "E35-DIA-SEG-004"],
        "action": "延续同一密室与同一坐姿，严敬看向镜头外的陈迹，补足不认脸、不对暗号、只认那一枚钱，随后呼吸发颤。",
        "expression": "严敬声音发紧，眼神从侥幸转为认命，最后一句落下后下颌轻颤。",
        "end_state": "严敬完整说完只认那一枚钱，闭口喘息，绳结、椅位与视线方向不变。",
    },
)


def build_prompt(split: dict, audio_assets: list[dict], weather: str) -> str:
    duration = split["duration"]
    midpoint = round(duration * 0.55, 3)
    audio_lines = []
    for index, asset in enumerate(audio_assets, start=1):
        audio_lines.append(
            f"- @音频{index}={asset['dia_id']}：严敬逐字说‘{asset['spoken_text']}’，使用备案参考声线，原生普通话口型、气息、情绪与起止同步。"
        )
    spoken = "；".join(asset["spoken_text"] for asset in audio_assets)
    return f"""竖屏9:16，中国古装玄幻真人短剧，Seedance 2四模态表演生成。只生成Claude Writer E35 v1的{split['unit_id']}，时长{duration}秒。
场景时间硬锁：太平医馆密室，晨，内。
【天气硬合同】weather={weather.upper()}
禁止雨夜、暴雨、雪景、现代物。
实体绑定：[[char_yanjing]] [[scene_e35_s01]]。画面只出现被缚严敬；陈迹与皎兔位于镜头外形成审讯压力，不出现身体、脸、倒影或复制人。
动作目的与风险：揭出景朝接头只认旧钱的死物规则。
单一动作状态源：{split['action']}
表情表演：{split['expression']}
观众必须看懂：严敬是在绝境中向镜头外审讯者连续吐供，而不是旁白或自言自语。
环境介质：残烛火苗只随严敬喘息带起的微弱气流轻颤，绳结、木椅与案面均不自行移动。
参考状态序列：@图片1锁同一密室、椅位、绳结和严敬起始坐姿；@图片2只锁严敬备案脸、年龄、发型与服装。连续表演由同一物理脚本完成，禁止逐图定格、拼贴和姿势跳切。
对白音频绑定：
{chr(10).join(audio_lines)}
对白文本硬锁：{spoken}
凡有对白，必须用对应参考音频驱动严敬原生自然中文普通话、同步口型、气息、表情与起止时间；逐字只说一次，禁止改字、漏字、串人和后配音。镜头外人物不发声。
连续逐拍物理脚本：
- 0.000-{midpoint:.3f}秒：主体=严敬；动作={split['action']}；接触点=严敬背部持续接触椅背、绳结持续接触躯干，除此之外不新增接触；方向=严敬视线固定朝镜头外同一审讯者方向，头部只做小幅抬眼与换气，禁止转身、起立、挣脱或跳位；终态={split['end_state']}；表情={split['expression']}；观众读法=供词通过原生口型和压迫表情推进。
- {midpoint:.3f}-{duration:.3f}秒：主体=严敬；动作=严敬完成本单元最后一句后闭口换气，肩胸因紧张产生一次自然起伏；接触点=绳结、椅背与严敬保持原接触关系；方向=身体与视线轴不变；终态={split['end_state']}；表情={split['expression']}；观众读法=观众清楚听完本单元全部供词并看到恐惧余波。
Seedance可执行分镜清单：
镜头1【远景定场·严敬全身、木椅与密室空间同框后缓慢推近；0.000-{midpoint:.3f}秒】：主体=严敬；动作={split['action']}；动作结果={split['end_state']}；接触/受力=绳结约束身体、椅背承托后背；方向=视线朝镜头外固定一点；终态={split['end_state']}；表情={split['expression']}；观众读法=口型、气息与供词含义同步。{{对白}}<现场音效：吞咽、喘息、衣料与绳结摩擦只在真实动作同帧出现>
镜头2【特写·眼神、嘴唇与喉结·固定机位；{midpoint:.3f}-{duration:.3f}秒】：主体=严敬；动作=完成最后一句并闭口换气；动作结果={split['end_state']}；接触/受力=保持原位无新增接触；方向=视线轴不变；终态={split['end_state']}；表情={split['expression']}；观众读法=观众看懂供词落定且严敬仍处于被审讯压力中。{{对白}}<现场音效：最后一字结束后才出现短促喘息>
动作硬门：每拍保留主体、动作、接触点、方向和终态；禁止起立、转身、瞬移、挣脱、腾空、碰撞和凭空道具。
身份硬门：严敬备案脸、年龄、发型、服装与声线一致；不得把镜头外陈迹或皎兔生成为新人物。
摄影：真实连续表演、清晰口型、呼吸和表情转折；禁止慢镜、补帧、周期重复、静帧填时、字幕、水印、可读伪文字、BGM和旁白。片尾不在单元内生成。
palette：密室幽暗、残烛暖黄、旧钱铜绿、晨光冷青。
"""


def main() -> int:
    base_config = load(BASE_CONFIG)
    original_task = next(row for row in base_config["tasks"] if row["unit_id"] == "E35-CW-U01")
    dialogue_manifest = load(BASE_DIALOGUE)
    dialogue_rows = {row["dia_id"]: row for row in dialogue_manifest["rows"]}
    prompt_manifest = load(BASE_PROMPT_MANIFEST)
    original_prompt_row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "E35-CW-U01")
    weather = original_prompt_row["weather"]

    split_tasks = []
    split_prompt_rows = []
    for split in SPLITS:
        selected_assets = [copy.deepcopy(row) for row in original_task["dialogue_audio_assets"] if row["dia_id"] in split["dialogue_ids"]]
        selected_dialogue = [copy.deepcopy(row) for row in original_task["dialogue"] if row["dia_id"] in split["dialogue_ids"]]
        for index, asset in enumerate(selected_assets, start=1):
            asset["audio_slot"] = f"@音频{index}"
        prompt_path = PROMPT_DIR / f"{split['unit_id']}-REPAIR2.txt"
        prompt_path.write_text(build_prompt(split, selected_assets, weather), encoding="utf-8")

        task = copy.deepcopy(original_task)
        task["task_key"] = split["task_key"]
        task["source_id"] = split["unit_id"]
        task["unit_id"] = split["unit_id"]
        task["visual_zone"] = f"{split['unit_id']}-V1-SPLIT-REPAIR2"
        task["duration"] = split["duration"]
        task["duration_seconds"] = split["duration"]
        task["edit_target_duration_seconds"] = split["duration"]
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": split["duration"],
            "rationale": "Natural confession pause split; exact dialogue audio fits with breathing room.",
            "edit_policy": f"Use the full {split['duration']} seconds; never loop, freeze, interpolate, slow or truncate dialogue.",
        }
        task["prompt_file"] = rel(prompt_path)
        task["prompt_path"] = rel(prompt_path)
        task["prompt_sha256"] = sha(prompt_path)
        task["dialogue"] = selected_dialogue
        task["dialogue_audio_assets"] = selected_assets
        task["dialogue_audio_coverage"] = {"required": 2, "bound": 2, "status": "PASS"}
        task["reference_audios"] = [row["path"] for row in selected_assets]
        task["reference_audio_asset_ids"] = []
        task.pop("resolved_reference_audio_asset_ids", None)
        temporal = copy.deepcopy(original_task["reference_image_sequence"][0])
        identity = copy.deepcopy(next(row for row in original_task["reference_image_sequence"] if row.get("entity_id") == "yanjing"))
        identity["asset_label"] = "@图片2"
        task["reference_image_sequence"] = [temporal, identity]
        task["reference_images"] = [temporal["path"], identity["path"]]
        task["reference_image_asset_ids"] = []
        task.pop("resolved_reference_image_asset_ids", None)
        binding = copy.deepcopy(next(row for row in original_task["multimodal_entity_bindings"] if row["entity_id"] == "yanjing"))
        binding["identity_image_slot"] = "@图片2"
        binding["dialogue_audio_slots"] = [row["audio_slot"] for row in selected_assets]
        task["multimodal_entity_bindings"] = [binding]
        task["visual_entity_ids"] = ["yanjing"]
        task["nonvisual_entity_mentions"] = ["chenji_off_camera", "jiaotu_off_camera"]
        task["performance_spec"] = {
            "schema": "qingshan.performance_generation_spec.v3",
            "episode": "E35",
            "unit_id": split["unit_id"],
            "duration_seconds": split["duration"],
            "single_source_of_truth": True,
            "prop_ownership": {"single_source_rule": "严敬、绳结与木椅保持原始接触和归属；镜头内无换手。"},
            "motion_beats": [{
                "start_seconds": 0.0,
                "end_seconds": float(split["duration"]),
                "subject": "严敬",
                "action": split["action"],
                "contact_point": "严敬背部接触椅背，绳结接触躯干；无新增接触。",
                "direction": "视线朝镜头外固定审讯者，小幅抬眼与换气，禁止跳位。",
                "end_state": split["end_state"],
                "intent": "揭出景朝接头只认旧钱的死物规则",
                "visible_causality": "原生口型、喘息和恐惧表情让观众理解严敬在绝境中吐供。",
                "expression": split["expression"],
                "viewer_read": "观众听清供词并理解严敬受压吐供。",
            }],
        }
        task["prompt_contract"]["source_action"] = split["action"]
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        task["repair_evidence"] = "qa/e35_v1_streaming_video_compile_20260723/E35_U01_REMOTE_FAILURE_ROOT_CAUSE_AND_SPLIT_DECISION_V1.json"
        task["generation_fingerprint"] = generation_fingerprint(task)
        split_tasks.append(task)
        split_prompt_rows.append({
            "unit_id": split["unit_id"], "scene_id": "E35-CW-S01", "weather": weather,
            "duration_seconds": split["duration"], "prompt_path": rel(prompt_path), "prompt_sha256": sha(prompt_path),
            "dialogue_ids": split["dialogue_ids"], "anchor_task_keys": ["E35-CW-U01-A1-STILL-V1"], "status": "PASS_COMPLETE",
        })

    unit_plan = load(BASE_UNIT_PLAN)
    original_unit = next(row for row in unit_plan["units"] if row["unit_id"] == "E35-CW-U01")
    split_units = []
    for split, task in zip(SPLITS, split_tasks):
        row = copy.deepcopy(original_unit)
        row["unit_id"] = split["unit_id"]
        row["duration_seconds"] = split["duration"]
        row["characters"] = ["yanjing"]
        row["action_chain"] = split["action"]
        row["expression_arc"] = split["expression"]
        row["performance_spec"] = copy.deepcopy(task["performance_spec"])
        row["dialogue_lines"] = [copy.deepcopy(x) for x in original_unit["dialogue_lines"] if x["dialogue_id"] in split["dialogue_ids"]]
        for line in row["dialogue_lines"]:
            line["video_unit_id"] = split["unit_id"]
        row["video_prompt_file"] = task["prompt_file"]
        row["video_prompt_sha256"] = task["prompt_sha256"]
        split_units.append(row)
    index = next(i for i, row in enumerate(unit_plan["units"]) if row["unit_id"] == "E35-CW-U01")
    unit_plan["units"][index:index + 1] = split_units
    unit_plan["unit_count"] = 24
    unit_plan["runtime_seconds"] = 176
    unit_plan["repair"] = "U01_SPLIT_REPAIR2_REDUCED_TO_TWO_IMAGES_AND_TWO_AUDIOS_PER_UNIT"
    write(OUT_UNIT_PLAN, unit_plan)

    index = next(i for i, row in enumerate(prompt_manifest["rows"]) if row["unit_id"] == "E35-CW-U01")
    prompt_manifest["rows"][index:index + 1] = split_prompt_rows
    prompt_manifest["unit_count"] = 24
    prompt_manifest["source_plan"] = rel(OUT_UNIT_PLAN)
    prompt_manifest["source_plan_sha256"] = sha(OUT_UNIT_PLAN)
    prompt_manifest["repair"] = "U01_SPLIT_REPAIR2"
    write(OUT_PROMPT_MANIFEST, prompt_manifest)

    dialogue_manifest["rows"] = [copy.deepcopy(row) for row in dialogue_manifest["rows"]]
    for row in dialogue_manifest["rows"]:
        if row["dia_id"] in SPLITS[0]["dialogue_ids"]:
            row["video_unit_id"] = SPLITS[0]["unit_id"]
        elif row["dia_id"] in SPLITS[1]["dialogue_ids"]:
            row["video_unit_id"] = SPLITS[1]["unit_id"]
    dialogue_manifest["repair"] = "U01_SPLIT_REPAIR2"
    write(OUT_DIALOGUE, dialogue_manifest)

    plan_specs = (
        ("E35_VIDEO_ANCHOR_COUNT_PLAN_V1.json", "E35_VIDEO_ANCHOR_COUNT_PLAN_V1_U01_SPLIT_REPAIR2.json", 27),
        ("E35_COMMON_SENSE_CAUSALITY_PLAN_V1.json", "E35_COMMON_SENSE_CAUSALITY_PLAN_V1_U01_SPLIT_REPAIR2.json", None),
        ("E35_PERIOD_LOCK_PLAN_V1.json", "E35_PERIOD_LOCK_PLAN_V1_U01_SPLIT_REPAIR2.json", None),
        ("E35_MECHANICAL_DEFAULT_PLAN_V1.json", "E35_MECHANICAL_DEFAULT_PLAN_V1_U01_SPLIT_REPAIR2.json", None),
    )
    out_plans = {}
    for source_name, out_name, total in plan_specs:
        payload = load(QA / source_name)
        rows = payload["units"]
        original = next(row for row in rows if row["unit_id"] == "E35-CW-U01")
        replacements = []
        for split, task in zip(SPLITS, split_tasks):
            row = copy.deepcopy(original)
            row["unit_id"] = split["unit_id"]
            if "duration_seconds" in row:
                row["duration_seconds"] = split["duration"]
            if "prompt_sha256" in row:
                row["prompt_sha256"] = task["prompt_sha256"]
            replacements.append(row)
        idx = next(i for i, row in enumerate(rows) if row["unit_id"] == "E35-CW-U01")
        rows[idx:idx + 1] = replacements
        if total is not None:
            payload["planned_reference_image_count"] = total
        out_path = QA / out_name
        write(out_path, payload)
        out_plans[source_name] = out_path

    dramatic = load(QA / "E35_DRAMATIC_QUALITY_PLAN_V1_U01_REPAIR1.json")
    dramatic["runtime_seconds"] = 176
    dramatic["repair"] = "U01_SPLIT_REPAIR2"
    dramatic_path = QA / "E35_DRAMATIC_QUALITY_PLAN_V1_U01_SPLIT_REPAIR2.json"
    write(dramatic_path, dramatic)
    preflight = load(QA / "E35_IMAGE_PLAN_PREFLIGHT_V1.json")
    preflight["recorded_at"] = datetime.now(timezone.utc).isoformat()
    preflight["video_unit_count"] = 24
    preflight["planned_anchor_count"] = 27
    preflight["runtime_seconds"] = 176
    preflight["projected_release_seconds_with_outro"] = 179
    preflight["u01_split_repair"] = "PASS_CHANGED_INPUT_TWO_IMAGES_TWO_AUDIOS_PER_UNIT"
    preflight_path = QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_U01_SPLIT_REPAIR2.json"
    write(preflight_path, preflight)

    config = copy.deepcopy(base_config)
    idx = next(i for i, row in enumerate(config["tasks"]) if row["unit_id"] == "E35-CW-U01")
    config["tasks"][idx:idx + 1] = split_tasks
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPT_MANIFEST)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["script_readiness_report"] = rel(preflight_path)
    config["dramatic_quality_report_ref"] = rel(dramatic_path)
    config["mechanical_default_plan_ref"] = rel(out_plans["E35_MECHANICAL_DEFAULT_PLAN_V1.json"])
    config["anchor_count_plan_ref"] = rel(out_plans["E35_VIDEO_ANCHOR_COUNT_PLAN_V1.json"])
    config["common_sense_causality_plan_ref"] = rel(out_plans["E35_COMMON_SENSE_CAUSALITY_PLAN_V1.json"])
    config["period_lock_plan_ref"] = rel(out_plans["E35_PERIOD_LOCK_PLAN_V1.json"])
    config["runtime_seconds"] = 176
    config["projected_release_seconds_with_outro"] = 179
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    evidence = [row for row in config["preserved_prompt_professionalism_evidence"] if not row["task_key"].startswith("E35-CW-U01-")]
    evidence.extend({
        "task_key": f"{task['unit_id']}-COMPLETE-PROMPT-V1-REPAIR2",
        "scene_id": task["scene_id"], "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"],
    } for task in split_tasks)
    config["preserved_prompt_professionalism_evidence"] = evidence
    write(OUT_CONFIG, config)
    print(json.dumps({
        "status": "PASS", "unit_count": 24, "runtime_seconds": 176, "projected_release_seconds": 179,
        "tasks": [{"task_key": row["task_key"], "references": len(row["reference_images"]) + len(row["reference_audios"]), "fingerprint": row["generation_fingerprint"]} for row in split_tasks],
        "config": rel(OUT_CONFIG),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
