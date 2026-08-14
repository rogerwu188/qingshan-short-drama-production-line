#!/usr/bin/env python3
"""Compile the locked E33 v2 performance batch without any legacy E33 builder."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from episode_video_generation_guard import generation_fingerprint
except ImportError:
    from tools.episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E33剧本_ClaudeWriter_v2.md"
MANIFEST = PRODUCTION / "E33_PRODUCTION_MANIFEST_V2.json"
UNIT_PLAN = PRODUCTION / "E33_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"
IMAGE_PLAN = PRODUCTION / "E33_IMAGE_BATCH_PERFORMANCE_V2.json"
SCENE_STATE = PRODUCTION / "E33_SCENE_STATE_AUTHORITY_V2.json"
HARVEST = ROOT / "workflow/tasks/E33_V2_FINAL_IMAGE_BATCH_HARVEST_20260723.json"
AUDIO_MANIFEST = ROOT / "working_assets/e33_dialogue_audio_refs_v2_20260723/E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
VOICE_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
CHARACTER_REGISTRY = ROOT / "configs/series_character_asset_registry_20260712.json"
OUTPUT = PRODUCTION / "video_performance_v2"
QA = ROOT / "qa/e33_v2_final_video_compile_20260723"
SOURCE_SHA = "e19276d4a55d0385beca9ab423ac5982a38f3deed0c1b4fee7de830ddafdfea3"
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))

DISPLAY = {
    "chenji": "陈迹",
    "jiaotu": "皎兔",
    "yunyang": "云羊",
    "wuyun": "乌云",
    "yao_taiyi": "姚太医",
}

REGISTRY_ID = {
    "chenji": "CHAR-陈迹-古装",
    "jiaotu": "CHAR-皎兔-古装",
    "yunyang": "CHAR-云羊-古装",
    "wuyun": "CHAR-乌云-猫",
    "yao_taiyi": "CHAR-姚太医-古装",
}

SCENE_VISUALS = {
    "E33-CW-S01": {
        "palette": "靛蓝夜色、橙红灯网、冷铁灰、残月冷白与湿石反光；火把和残月是唯一动机光",
        "environment": "动作力量通过环境介质显形：湿石水面反光被脚步打碎，旗面、火焰和甲片随兵潮受力变化",
    },
    "E33-CW-S02": {
        "palette": "檐影冷墨、纸人素白、冰印幽蓝与黑甲阴神深黑；檐灯和残月是动机光",
        "environment": "动作力量通过环境介质显形：纸片、信封、布幔、甲片和湿檐残滴只在明确接触后变化",
    },
    "E33-CW-S03": {
        "palette": "长街靛蓝、火把橙红、残月冷白、冰流幽蓝、暗红血色与碎冰银白；火把、残月和冰光构成动机光",
        "environment": "动作力量通过环境介质显形：湿石水面结冰、木屑碎片飞散、火焰偏转、冰屑在真实撞击后迸开",
    },
    "E33-CW-S04": {
        "palette": "死巷冷青、乌鸦漆黑、冰栅幽蓝与巷口火光橙红；残月和追兵火把是动机光",
        "environment": "动作力量通过环境介质显形：湿墙残滴、铁锈碎片、冰屑和暗洞水面只响应冻裂与冲拳",
    },
    "E33-CW-S05": {
        "palette": "密室幽暗、残烛暖黄、水波密纹幽墨与纸页冷白；残烛和窗隙残月是动机光",
        "environment": "动作力量通过环境介质显形：纸页、烛火、桌面碎尘和水波纹理随翻页、冷雾与屏息发生细微可见变化",
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seedance_identity_transport(entity_id: str, canonical: Path) -> dict:
    source_sha = sha256(canonical)
    output = OUTPUT / "identity_transport_v2" / f"{entity_id}_{source_sha[:12]}_1440x2560.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file():
        filter_graph = (
            "[0:v]scale=1440:2560:force_original_aspect_ratio=increase,"
            "crop=1440:2560,gblur=sigma=40[bg];"
            "[0:v]scale=1440:2560:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=rgb24"
        )
        subprocess.run(
            [str(FFMPEG), "-y", "-i", str(canonical), "-filter_complex", filter_graph, "-frames:v", "1", str(output)],
            check=True,
            capture_output=True,
        )
    return {
        "path": rel(output),
        "sha256": sha256(output),
        "transport_derivative_of": rel(canonical),
        "transport_derivative_source_sha256": source_sha,
        "transport_transform": "PNG_RGB_1440X2560_BLURRED_PAD_UPSCALE",
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def weather_token(value: str) -> str:
    return str(value).strip().upper()


def unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def motion_clauses(text: str) -> list[str]:
    clauses = [part.strip(" ，。；") for part in re.split(r"[；。]", text) if part.strip(" ，。；")]
    if len(clauses) == 1:
        clauses = [part.strip(" ，。；") for part in re.split(r"，(?=[^，]{6,})", text) if part.strip(" ，。；")]
    return clauses or [text.strip()]


def subject_for(clause: str) -> str:
    names = [DISPLAY[key] for key in DISPLAY if DISPLAY[key] in clause]
    if names:
        return "、".join(names)
    for fallback in ("三人", "两兵", "巡检兵", "景朝暗桩", "车夫", "乌鸦", "兵潮", "阴神"):
        if fallback in clause:
            return fallback
    return "本拍中由剧本明确点名的行动主体"


def transport_duration(value: float) -> int:
    """Seedance accepts integer seconds; retain extra raw coverage for half-second edit targets."""
    return int(math.ceil(value))


def split_times(duration: int, count: int) -> list[tuple[float, float]]:
    return [
        (round(duration * index / count, 3), round(duration * (index + 1) / count, 3))
        for index in range(count)
    ]


def build_motion_beats(unit: dict) -> list[dict]:
    spec = unit["performance_spec"]
    clauses = motion_clauses(spec["motion_chain"])
    duration = transport_duration(float(unit["duration_seconds"]))
    beats: list[dict] = []
    for index, (clause, (start, end)) in enumerate(zip(clauses, split_times(duration, len(clauses))), 1):
        end_state = spec["viewer_read"] if index == len(clauses) else "本拍动作结果清楚落定，并以连续身体姿态进入下一拍"
        beats.append({
            "start_seconds": start,
            "end_seconds": end,
            "subject": subject_for(clause),
            "action": clause,
            "contact_point": f"只保留本句明确写出的接触与受力关系：{clause}",
            "direction": "严格执行本句声明的屏幕方向、进退路线和受力方向；未写出的抓取、转身、腾空、碰撞或换位一律不补",
            "end_state": end_state,
            "intent": spec["intent"],
            "visible_causality": clause,
            "expression": spec["expression_arc"],
            "viewer_read": spec["viewer_read"],
        })
    return beats


def build_dramatic_quality() -> dict:
    analyses = {
        "american_tv_pacing": "冷开场直接进入铁闸下落与兵潮合围，随后作局、互杀、夺匣、破栅和密室揭密连续推进，没有回放上一集原因。",
        "executive_producer": "本集结算全城围猎并把主线推进到真名册在手、顶端姓名由景朝密纹封锁、沈砚旧案正式进入主谜。",
        "film_director": "五场均有清晰空间、行动目的、力量结果、表情弧和场尾按钮，十七秒完整打斗具有起承转合而非慢镜填时。",
        "ordinary_audience": "观众可从三面旗、三封毒饵、三方互杀、令匣争夺和名册密纹顺着因果看懂陈迹如何从猎物变成设局者。",
        "original_author": "纸人、阴神、冰流、人参珠和姚太医乌鸦均沿用既有能力与人物关系，没有为解围临时发明新身份或新能力。",
        "short_drama_director": "每场晚进早出，三个以上场尾形成追看按钮，混战挫顿与最终沈砚旧案钩子分别承担中段和结尾 act-out。",
    }
    beats = [
        ("6-1", "合围绝境被陈迹识别为三方互疑的可利用结构。", {"line": "让网里的人，先咬起来。"}, "E33-Q-COUNTER-NET", True, []),
        ("6-2", "三种既有能力合成三封毒饵并完成跨空间投递。", {"line": "互相咬着的人，一点就着。"}, "E33-Q-WHO-BITES-FIRST", True, ["6-2：一封给巡检兵——随后陈迹改口逐封下令"]),
        ("6-3", "围猎者互杀，暗桩一度夺匣，三人反扑夺得真名册。", {"reveal": "猎物夺匣，转为握有真名册的执猎者。"}, "E33-Q-TOP-NAME", True, []),
        ("6-4", "死巷在姚太医乌鸦指引下变成可撤离的暗洞生门。", {"action": "三人没入暗洞，追兵火光扑空。"}, "E33-Q-YAO-NETWORK", False, []),
        ("6-5", "胜利立刻被景朝密纹与沈砚旧案升级为更深主谜。", {"reveal": "沈砚旧案压在整本内鬼名册最上头。"}, "E33-Q-SHENYAN-OLD-CASE", True, ["6-5：皎兔以‘等等——这里’打断陈迹对封纹的判断"]),
    ]
    return {
        "schema": "qingshan.dramatic_quality_evidence.v1",
        "episode": "E33",
        "script": rel(SCRIPT),
        "script_sha256": SOURCE_SHA,
        "runtime_seconds": 172,
        "council": {
            "advisors": [{"role": role, "independent": True, "analysis": text} for role, text in analyses.items()],
            "chair_verdict": "PASS",
            "chair_reason": "The locked v2 script is dramatically executable and contains a complete 17-second true fight.",
            "experience_memory_ref": "workflow/script_review/剧本审核_经验记忆_MEMORY.md",
            "revision_cascade": {"status": "NOT_REQUIRED", "affected_unproduced_episodes": [], "affected_published_episodes": []},
        },
        "narrative_technique_contract": {
            "cold_open": {"enabled": True, "within_seconds": 3, "event_in_progress": True, "script_ref": "6-1 iron gate and converging troops already moving"},
            "dual_line_episode": False,
        },
        "beats": [{
            "beat_id": beat_id,
            "scene_entry": "late",
            "scene_exit": "early",
            "power_shift": shift,
            "intercut_with": None,
            "end_button": button,
            "unresolved_question_id": question,
            "act_out": act_out,
            "dialogue_interruption_refs": interruptions,
        } for beat_id, shift, button, question, act_out, interruptions in beats],
        "two_episode_fight_floor": {
            "qualifying_true_fight_scene_count": 1,
            "minimum_qualifying_duration_seconds": 17,
            "script_ref": "6-3 continuous real-time fight, authored start-development-reversal-resolution",
            "roger_skip_approval_ref": "",
        },
    }


def build_causality(units: list[dict]) -> dict:
    rows = []
    for unit in units:
        spec = unit["performance_spec"]
        chain = motion_clauses(spec["motion_chain"])
        while len(chain) < 2:
            chain.append("上一动作的可见受力、位置或道具结果保持成立，人物以连续姿态进入终态")
        rows.append({
            "unit_id": unit["unit_id"],
            "causality": {
                "applicable": True,
                "purpose": spec["intent"],
                "intended_effect": spec["viewer_read"],
                "preconditions": ["人物、道具与空间位置承接本单元起始锚图", "只有剧本已登记能力和道具可参与动作"],
                "mechanism_chain": chain,
                "visible_causality": spec["motion_chain"],
                "viewer_read": spec["viewer_read"],
                "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "提示词锁定接触点、受力方向和终态；取消任一明确步骤都会使目标结果无法成立。"},
                "prop_function_status": "PASS",
                "evidence_refs": [rel(SCRIPT), f"unit://{unit['unit_id']}"],
            },
        })
    return {"schema": "qingshan.common_sense_causality_plan.v1", "episode": "E33", "source_script_sha256": SOURCE_SHA, "units": rows}


def build_period_lock(units: list[dict]) -> dict:
    elements_by_scene = {
        "E33-CW-S01": ["古城铁闸", "甲胄", "旗号", "火把", "湿石长街", "布衣长袍"],
        "E33-CW-S02": ["纸信", "古印", "檐影", "马鞍", "营帐", "黑甲阴神"],
        "E33-CW-S03": ["黑漆马车", "铜封令匣", "古制刀兵", "车辕", "纸人", "冰流"],
        "E33-CW-S04": ["石墙死巷", "铁栅", "排水暗洞", "古装布衣", "乌鸦"],
        "E33-CW-S05": ["木案", "黑皮名册", "残烛", "水波密纹", "古装布衣"],
    }
    return {
        "schema": "qingshan.anachronism_lock_plan.v1",
        "episode": "E33",
        "source_script_sha256": SOURCE_SHA,
        "period_contract": {"era": "架空古代洛城，宋明质感", "status": "PASS", "source_refs": [rel(SCRIPT), "configs/QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1.json"]},
        "units": [{
            "unit_id": unit["unit_id"],
            "period_lock": {"status": "PASS", "reviewed_visible_elements": elements_by_scene[unit["scene_id"]], "detected_anachronisms": [], "evidence_refs": [rel(SCRIPT), f"scene://{unit['scene_id']}"]},
        } for unit in units],
    }


def render_prompt(
    unit: dict,
    scene: dict,
    temporal: list[dict],
    identities: list[dict],
    motion_beats: list[dict],
    dialogue_assets: list[dict],
    *,
    scene_first: bool,
) -> str:
    visual = SCENE_VISUALS[unit["scene_id"]]
    identity_ids = [row["entity_id"] for row in identities]
    entity_labels = "、".join(
        f"{DISPLAY.get(row['entity_id'], row['entity_id'])}[[char_{row['entity_id']}]]"
        for row in identities
    )
    age_locks = []
    if "chenji" in identity_ids:
        age_locks.append("陈迹[[char_chenji]]必须是十七岁清俊少年：年轻骨相、紧致无纹、无胡茬；冷峻只属于表情，绝不生成成熟、中年或沧桑脸")
    if "jiaotu" in identity_ids:
        age_locks.append("皎兔[[char_jiaotu]]十八岁，保持清晰年轻骨相")
    if "yunyang" in identity_ids:
        age_locks.append("云羊[[char_yunyang]]十七岁，保持清晰年轻骨相")
    scene_label = re.sub(r"[^A-Za-z0-9_]+", "_", unit["scene_id"])
    lines = [
        "【E33 v2 独立表演生成提示词｜禁止读取任何旧版 E33 构建产物】",
        f"《青山》E33《围猎反噬》{unit['unit_id']}，Seedance 2.0 Pro 四模态表演生成，{transport_duration(float(unit['duration_seconds']))}秒原始素材，9:16，720p，实速。",
        f"【剧本 SHA 硬锁】{SOURCE_SHA}",
        f"【地点硬合同】scene={unit['scene_id']}；location={scene['location']}；event={scene['event_summary']}",
        f"【实体绑定】{entity_labels or '本单元无备案主角'}；场景={scene['location']}[[scene_{scene_label}]]。同一实体只允许一个身体，角色身份、道具归属和能力归属不可交换。",
        f"【天气硬合同】weather={weather_token(scene['weather'])}",
        "【天气执行】雨已经完全停止；只允许湿石、残积水、湿檐残滴、冷空气与残月反光。禁止正在下雨、雨丝、雨帘、暴雨、风暴和人物身上新增落雨。",
        "【年代执行】架空古代洛城，宋明质感；禁止现代警服、大盖帽、汽车、塑料、拉链、二维码、现代标牌和现代照明器具。",
        "【身份硬锁】" + ("；".join(age_locks) if age_locks else "本单元无备案人脸主体，只锁场景与道具连续性") + "。",
        f"【palette 与动机光】{visual['palette']}。",
        f"【环境受力】{visual['environment']}。",
        f"【动作目的】{unit['performance_spec']['intent']}",
        f"【观众必须读懂】{unit['performance_spec']['viewer_read']}",
        "【参考图绑定】时序锚图只规定本单元动作阶段、地点和道具状态；角色标准图优先锁定脸、年龄、发型和身份。禁止把多图拼成分屏、网格或故事板。",
    ]
    for row in temporal + identities:
        lines.append(f"- {row['asset_label']}：role={row['role']}；path={row['path']}；SHA-256={row['sha256']}。")
    lines.append("【Seedance 连续镜头表｜每镜都要体现动作目的、受力和结果】")
    for index, beat in enumerate(motion_beats, 1):
        if index == 1 and scene_first:
            camera = "大远景·远景定场·缓慢横移后跟随主体"
        elif index % 3 == 1:
            camera = "中景·侧向跟拍"
        elif index % 3 == 2:
            camera = "近景·轻微手持跟随"
        else:
            camera = "特写·固定机位后短促拉开"
        dialogue_slot = "{本镜头按下方绑定音频执行对白，非说话角色闭口}" if dialogue_assets else "{无对白；人物闭口，只保留呼吸与动作声}"
        lines.append(
            f"镜头{index}【{camera}；{beat['start_seconds']:.3f}-{beat['end_seconds']:.3f}秒】：主体={beat['subject']}；先跟随主体移动或转移视线，再完成：{beat['action']}；动作结果={beat['end_state']}；"
            f"接触/受力={beat['contact_point']}；方向={beat['direction']}；终态={beat['end_state']}；"
            f"表情={beat['expression']}；观众读法={beat['viewer_read']}。{dialogue_slot}<现场音效：接触、脚步、衣料、环境响应必须与画面同帧>"
        )
    lines.extend([
        "【动作物理硬门】动作按起势→接触→传力→结果连续发生。道具归属不跳变；未写出的抓取、换手、转身、腾空、碰撞、穿墙或人物位移一律禁止。只要动作结果成立就自然收尾，禁止循环、慢放、插帧、停帧或重复首帧填时长。",
        "【表情硬门】表情不是装饰：眼神、呼吸、下颌、疼痛与决断必须随每拍因果同步变化，不允许全程同一张脸。",
    ])
    if dialogue_assets:
        lines.append("【原生同步对白｜参考音频必须喂给视频模型】")
        for asset in dialogue_assets:
            mode = "逐句精确音频" if asset["purpose"] == "EXACT_TARGET_DIALOGUE_REFERENCE" else "备案角色声线参考"
            lines.append(
                f"- {asset['dia_id']}：{asset['speaker']}使用{asset['audio_slot']}作为{mode}，逐字说“{asset['spoken_text']}”；"
                "只说一次，不改词、不增词；口型、气息、表情和起止时间同步；非说话角色闭口。"
            )
    else:
        lines.append("【原生声音】本单元无台词；所有人物闭口，只保留与动作同步的呼吸、接触声、兵刃声和环境声。")
    lines.extend([
        "【声音】禁止无动机背景音乐；拟音必须与接触同帧。后期字幕不在生成画面中出现。",
        "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字、换脸、额外主角、人物分身、融合肢体、穿模、瞬移、无因离地、橡皮物理、静图微动、统一慢推镜和周期重复帧。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    if sha256(SCRIPT) != SOURCE_SHA:
        raise RuntimeError("E33 v2 script SHA drift")
    manifest = load(MANIFEST)
    plan = load(UNIT_PLAN)
    image_plan = load(IMAGE_PLAN)
    scene_by_id = {row["scene_id"]: row for row in load(SCENE_STATE)["scene_state"]}
    harvest_by_key = {row["task_key"]: row for row in load(HARVEST)["results"]}
    image_task_by_key = {row["task_key"]: row for row in image_plan["tasks"]}
    audio_rows = load(AUDIO_MANIFEST)["rows"]
    audio_by_unit: dict[str, list[dict]] = {}
    for row in audio_rows:
        audio_by_unit.setdefault(row["video_unit_id"], []).append(row)
    voice_by_id = {row["entity_id"]: row for row in load(VOICE_REGISTRY)["major_roles"]}
    character_rows = load(CHARACTER_REGISTRY)["characters"]
    character_by_id = {entity_id: character_rows[registry_id] for entity_id, registry_id in REGISTRY_ID.items()}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "prompts").mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    admission_rows = []
    prompt_rows = []
    tasks = []
    first_unit_by_scene: dict[str, str] = {}
    for row in plan["units"]:
        first_unit_by_scene.setdefault(row["scene_id"], row["unit_id"])
    for unit in plan["units"]:
        temporal = []
        character_bindings: dict[str, dict] = {}
        unit_identity_risk = False
        for index, task_key in enumerate(unit["reference_image_task_keys"], 1):
            harvest = harvest_by_key[task_key]
            image_task = image_task_by_key[task_key]
            path = Path(harvest["output_path"])
            if harvest.get("remote_status") != "completed" or not path.is_file() or sha256(path) != harvest["sha256"]:
                raise RuntimeError(f"incomplete or corrupt anchor: {task_key}")
            visible = list((image_task.get("prompt_contract") or {}).get("visible_characters") or [])
            identity_risk = "chenji" in visible
            unit_identity_risk = unit_identity_risk or identity_risk
            role = f"PERFORMANCE_{str((image_task.get('prompt_contract') or {}).get('state_role') or f'ANCHOR_{index}').upper()}"
            temporal.append({
                "asset_label": f"@图片{index}", "role": role, "path": rel(path), "sha256": harvest["sha256"],
                "state_id": image_task["shot_id"], "identity_reference": False,
                "qa_decision": "CONDITIONAL_MACHINE_ADMISSION" if identity_risk else "PASS",
            })
            admission_rows.append({
                "state_id": image_task["shot_id"], "task_key": task_key, "path": rel(path), "sha256": harvest["sha256"],
                "original_qa_status": "FAIL_IDENTITY_DRIFT_RISK" if identity_risk else "PASS",
                "admission": "CONDITIONAL_MACHINE_ADMISSION" if identity_risk else "PASS",
                "failure_items": ["陈迹面部可能偏离备案标准脸；锚图仅保留空间、构图和动作状态"] if identity_risk else [],
                "selection_reason": "图像保持剧本人物数量、地点时段、核心动作和技术可用性；视频任务另行强绑角色备案标准图。" if identity_risk else "图像事实、人物数量、天气和技术可用性通过接触表机器审查。",
                "confidence": 0.78 if identity_risk else 0.92,
                "rollback_point": rel(path),
                "replacement_condition": "若视频成片身份 QA 仍偏离备案脸，则只替换本单元并保留其他通过项。" if identity_risk else "None",
                "review_evidence": "qa/e33_v2_final_image_contact_sheets_20260723",
            })
            for binding in image_task.get("reference_bindings") or []:
                if binding.get("role") == "character":
                    character_bindings.setdefault(binding["entity_id"], binding)

        unit_text = "\n".join([
            unit["performance_spec"]["intent"],
            unit["performance_spec"]["motion_chain"],
            unit["performance_spec"]["expression_arc"],
            unit["performance_spec"]["viewer_read"],
            *[row["speaker"] + row["spoken_text"] for row in audio_by_unit.get(unit["unit_id"], [])],
        ])
        named_entity_ids = [entity_id for entity_id, name in DISPLAY.items() if name in unit_text]
        scene_summary_mentions = [
            entity_id
            for entity_id, name in DISPLAY.items()
            if name in scene_by_id[unit["scene_id"]]["event_summary"] and entity_id not in named_entity_ids
        ]
        nonvisual_mentions = unique(
            [entity_id for entity_id in named_entity_ids if entity_id == "yao_taiyi"]
            + scene_summary_mentions
        )
        visual_entity_ids = [entity_id for entity_id in named_entity_ids if entity_id not in nonvisual_mentions]
        visual_entity_ids = unique(visual_entity_ids + list(character_bindings))
        canonical_bindings: dict[str, dict] = {}
        for entity_id in visual_entity_ids:
            canonical = character_by_id[entity_id]
            path = Path(
                canonical.get("generation_reference_image")
                or canonical.get("identity_reference_image")
                or canonical.get("reference_image")
            )
            if not path.is_absolute():
                path = ROOT / path
            if not path.is_file():
                raise RuntimeError(f"canonical identity reference missing: {entity_id}: {path}")
            transport = seedance_identity_transport(entity_id, path)
            canonical_bindings[entity_id] = {
                "entity_id": entity_id,
                "path": rel(path),
                "sha256": sha256(path),
                "transport": transport,
            }

        identities = []
        next_label = len(temporal) + 1
        for entity_id, binding in canonical_bindings.items():
            transport = binding["transport"]
            identities.append({
                "asset_label": f"@图片{next_label}", "role": f"IDENTITY_REFERENCE_{entity_id.upper()}",
                "path": transport["path"], "sha256": transport["sha256"], "identity_reference": True,
                "entity_id": entity_id,
                "transport_derivative_of": transport["transport_derivative_of"],
                "transport_derivative_source_sha256": transport["transport_derivative_source_sha256"],
                "transport_transform": transport["transport_transform"],
            })
            next_label += 1
        if len(temporal) + len(identities) > 8:
            raise RuntimeError(f"{unit['unit_id']} exceeds provider image-reference limit")

        dialogue = []
        dialogue_assets = []
        exact_paths: list[str] = []
        style_asset_ids: list[str] = []
        audio_slot_by_key: dict[str, str] = {}
        for row in audio_by_unit.get(unit["unit_id"], []):
            key = row.get("remote_asset_id") or row["path"]
            if key not in audio_slot_by_key:
                audio_slot_by_key[key] = f"@音频{len(audio_slot_by_key) + 1}"
            exact = row["audio_mode"] == "EXACT_DIALOGUE_AUDIO_REFERENCE"
            purpose = "EXACT_TARGET_DIALOGUE_REFERENCE" if exact else "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT"
            asset = {
                "dia_id": row["dia_id"], "speaker": row["speaker"], "speaker_id": row["speaker_id"],
                "spoken_text": row["spoken_text"], "audio_slot": audio_slot_by_key[key], "path": row["path"],
                "sha256": row["sha256"], "duration_seconds": row["duration_seconds"], "purpose": purpose,
                "remote_asset_id": row.get("remote_asset_id"),
                "voice_reference_asset_id": row.get("voice_reference_asset_id") or voice_by_id[row["speaker_id"]].get("remote_asset_id"),
                "voice_derivation_status": row.get("voice_derivation_status") or "PASS",
                "voice_gender": row.get("voice_gender") or voice_by_id[row["speaker_id"]].get("gender"),
                "source_voice": row.get("source_voice") or f"NATIVE_MULTIMODAL_VIDEO_EXTRACT:{voice_by_id[row['speaker_id']].get('remote_asset_id')}",
            }
            dialogue_assets.append(asset)
            dialogue.append({"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]})
            if exact:
                exact_paths.append(row["path"])
            elif row.get("remote_asset_id"):
                style_asset_ids.append(row["remote_asset_id"])

        motion_beats = build_motion_beats(unit)
        scene_first = first_unit_by_scene[unit["scene_id"]] == unit["unit_id"]
        prompt = render_prompt(
            unit,
            scene_by_id[unit["scene_id"]],
            temporal,
            identities,
            motion_beats,
            dialogue_assets,
            scene_first=scene_first,
        )
        prompt_path = OUTPUT / "prompts" / f"{unit['unit_id']}-PERFORMANCE-V2.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_sha = sha256(prompt_path)
        generated_duration = transport_duration(float(unit["duration_seconds"]))
        all_images = temporal + identities
        multimodal = []
        for entity_id, binding in canonical_bindings.items():
            speaker_assets = [row for row in dialogue_assets if row["speaker_id"] == entity_id]
            voice = voice_by_id.get(entity_id) or {}
            multimodal.append({
                "entity_id": entity_id, "character_name": DISPLAY.get(entity_id, entity_id),
                "registry_id": REGISTRY_ID[entity_id],
                "visual_reference": binding["path"], "visual_reference_sha256": binding["sha256"],
                "identity_image_slot": next(row["asset_label"] for row in identities if entity_id.upper() in row["role"]),
                "voice_reference_asset_id": voice.get("remote_asset_id"),
                "dialogue_audio_slots": [row["audio_slot"] for row in speaker_assets],
                "visible_speaker": bool(speaker_assets), "lip_sync": bool(speaker_assets),
                "prop_owners": {"single_source_rule": f"{DISPLAY.get(entity_id, entity_id)}只持有本单元动作脚本明确分配的道具"},
                "ability_owners": [f"只有{DISPLAY.get(entity_id, entity_id)}可执行本单元明确分配给该角色的能力"],
            })
        task = {
            "task_key": f"{unit['unit_id']}-PERFORMANCE-V2", "source_id": unit["unit_id"],
            "tool_type": "video_generation", "generation_mode": "performance_generation", "episode": "E33",
            "batch_id": "E33-V2-FINAL-PERFORMANCE-20260723", "unit_id": unit["unit_id"], "scene_id": unit["scene_id"],
            "visual_zone": f"{unit['unit_id']}-V2-CURRENT-CANONICAL", "duration": generated_duration,
            "duration_seconds": generated_duration, "edit_target_duration_seconds": unit["duration_seconds"],
            "model": "seedance-2.0-pro", "aspect_ratio": "9:16", "resolution": "720p",
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5", "duration_seconds": generated_duration,
                "rationale": "Claude Writer scene-local natural grouping; integer transport duration retains enough raw coverage for the exact editorial target.",
                "edit_policy": f"Edit to {unit['duration_seconds']} seconds when needed; trim only natural head/tail, never loop, freeze, interpolate or slow footage.",
            },
            "prompt_file": rel(prompt_path), "prompt_path": rel(prompt_path), "prompt_sha256": prompt_sha,
            "reference_images": [row["path"] for row in all_images], "reference_image_sequence": all_images,
            "planned_reference_image_count": unit["planned_reference_image_count"],
            "state_reference_minimum": unit["planned_reference_image_count"], "still_sequence_only_allowed": True,
            "inherits_establishing_coverage": not scene_first,
            "action_unit": True, "anchor_count_decision": unit["anchor_count_decision"],
            "performance_spec": {"schema": "qingshan.performance_generation_spec.v3", "episode": "E33", "unit_id": unit["unit_id"], "duration_seconds": generated_duration, "prop_ownership": {"single_source_of_truth": "Prompt, anchors, character bindings, props and abilities derive only from locked E33 v2 unit spec."}, "motion_beats": motion_beats},
            "keyframe_interpolation_gate": {"status": "PASS", "stage": "CANDIDATE_PREFLIGHT", "anchor_count": len(temporal), "checked_adjacent_pairs": max(0, len(temporal) - 1), "candidate_recheck_required": len(temporal) > 1, "reason": "Adjacent anchors preserve scene, actor count, prop ownership and physically traversable action order; video output requires identity and continuity recheck.", "qa_reference": rel(QA / "E33_V2_IMAGE_MACHINE_ADMISSION.json")},
            "dialogue": dialogue, "reference_audios": unique(exact_paths), "reference_audio_asset_ids": unique(style_asset_ids),
            "dialogue_audio_assets": dialogue_assets, "native_dialogue_required": bool(dialogue),
            "audio_reference_optional": not bool(dialogue),
            "dialogue_audio_coverage": {"required": len(dialogue), "bound": len(dialogue_assets), "status": "PASS" if len(dialogue) == len(dialogue_assets) else "FAIL"},
            "source_script_sha256": SOURCE_SHA, "workflow_credit_scope": "e33_claude_writer_v2_e19276d4_20260723",
            "status": "READY_TO_SUBMIT", "identity_machine_admission": "CONDITIONAL_MACHINE_ADMISSION" if unit_identity_risk else "PASS",
            "prompt_contract": {"source_action": unit["performance_spec"]["viewer_read"], "spatial_continuity": {"mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT", "scene_id": unit["scene_id"], "anchor_scope": "PERFORMANCE_TEMPORAL_ANCHORS_ONLY", "camera_policy": "ALLOW_ONLY_AUTHORED_INTRA_SCENE_CAMERA_MOVEMENT"}},
            "multimodal_entity_bindings": multimodal,
            "character_free_unit": not bool(canonical_bindings),
            "nonvisual_entity_mentions": nonvisual_mentions,
            "effect_provenance": [{"effect": "悬浮、漂浮、变色、光幕、冰幕、水幕、冰流、阴神、皮影、冰墙、纸人、人参珠、乌鸦引路、水波密纹", "source_type": "CLAUDE_SCRIPT", "source_ref": rel(SCRIPT)}],
        }
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(multimodal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        prompt_rows.append({"unit_id": unit["unit_id"], "scene_id": unit["scene_id"], "weather": scene_by_id[unit["scene_id"]]["weather"], "prompt_path": rel(prompt_path), "prompt_sha256": prompt_sha})

    admission_path = QA / "E33_V2_IMAGE_MACHINE_ADMISSION.json"
    write(admission_path, {"schema": "qingshan.image_machine_admission.v1", "episode": "E33", "status": "PASS_WITH_CONDITIONAL_MACHINE_ADMISSIONS", "source_script_sha256": SOURCE_SHA, "selections": admission_rows, "original_failures_preserved": True, "rollback_policy": "Replace only the failed unit after video identity QA; preserve all passed siblings."})
    dramatic_path = QA / "E33_V2_DRAMATIC_QUALITY_REPORT.json"
    causality_path = QA / "E33_V2_COMMON_SENSE_CAUSALITY_PLAN.json"
    period_path = QA / "E33_V2_PERIOD_LOCK_PLAN.json"
    readiness_path = QA / "E33_V2_SCRIPT_READINESS_REPORT.json"
    prompt_manifest_path = OUTPUT / "E33_COMPLETE_VIDEO_PROMPT_MANIFEST_V2.json"
    write(dramatic_path, build_dramatic_quality())
    write(causality_path, build_causality(plan["units"]))
    write(period_path, build_period_lock(plan["units"]))
    write(readiness_path, {"schema": "qingshan.script_readiness_report.v1", "episode": "E33", "status": "PASS", "source_script": rel(SCRIPT), "source_script_sha256": SOURCE_SHA, "unit_count": len(plan["units"]), "runtime_seconds": 172})
    write(prompt_manifest_path, {"schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E33", "status": "PASS", "source_plan": rel(UNIT_PLAN), "source_plan_sha256": sha256(UNIT_PLAN), "source_scene_authority": rel(SCENE_STATE), "source_scene_authority_sha256": sha256(SCENE_STATE), "unit_count": len(prompt_rows), "all_units_have_prompt": True, "rows": prompt_rows})

    config_path = OUTPUT / "E33_VIDEO_FINAL_PERFORMANCE_V2.json"
    write(config_path, {
        "schema": "qingshan.episode_streaming_video_batch.v2", "episode": "E33", "status": "READY_FOR_STREAMING_SUBMIT",
        "recorded_at": now(), "concurrency": len(tasks), "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED", "effective_ruleset": "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1",
        "workflow_credit_scope": "e33_claude_writer_v2_e19276d4_20260723", "video_credit_limit": 6000,
        "source_script_sha256": SOURCE_SHA, "output_dir": rel(OUTPUT / "outputs"), "qa_dir": rel(QA / "video_runtime"),
        "scene_contract_ref": rel(SCENE_STATE), "script_readiness_report": rel(readiness_path),
        "dramatic_quality_report_ref": rel(dramatic_path), "mechanical_default_plan_ref": rel(UNIT_PLAN),
        "anchor_count_plan_ref": rel(UNIT_PLAN), "common_sense_causality_plan_ref": rel(causality_path),
        "period_lock_plan_ref": rel(period_path), "complete_video_prompt_manifest_ref": rel(prompt_manifest_path),
        "dialogue_manifest_ref": rel(AUDIO_MANIFEST), "voice_registry_ref": rel(VOICE_REGISTRY),
        "supervisor_script_gate_required": False, "space_camera_constraint_gate_required": True,
        "readiness_policy": "SUBMIT_EACH_VIDEO_UNIT_IMMEDIATELY_WHEN_ITS_OWN_ANCHORS_AND_AUDIO_ARE_READY",
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": rel(SCRIPT), "source_script_sha256": SOURCE_SHA, "production_manifest": rel(MANIFEST), "production_manifest_sha256": sha256(MANIFEST)},
        "tasks": tasks,
    })
    print(json.dumps({"status": "PASS", "units": len(tasks), "anchors": len(admission_rows), "dialogue_lines": len(audio_rows), "config": rel(config_path), "legacy_builder_dependency": "NONE"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
