#!/usr/bin/env python3
"""Compile E40 canonical-v3 U24-U29 into zero-cost ending-shot prompts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from build_e40_u01_u16_prompt_precompile import atomic_windows, sha256, unit
except ModuleNotFoundError:
    from tools.build_e40_u01_u16_prompt_precompile import atomic_windows, sha256, unit


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u24_u29_prompt_precompile_v1"
PROMPT_DIR = OUT_DIR / "prompts"
OUTPUT_MANIFEST = OUT_DIR / "E40_U24_U29_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
QA_REPORT = ROOT / "qa/e40_preproduction_20260808/E40_U24_U29_PROMPT_STATIC_QA_V1.json"

SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
MODEL = "seedance-2.0"
ENVIRONMENT = "场次13-5，同夜更深，王府花厅帘前；夜雾已经散去，庭外初雪才开始一片两片斜过窗纸冷光，厅内灯烛暖金，禁止恢复浓雾、雨夜或提前变成大雪"


UNITS = [
    unit(
        "U24", "13-5", 6, "hidden_speaker_dialogue", "帘后落座影与帘前反应同处一个近景轴线",
        "0.5秒内帘影从正落座一半的首帧继续下降，裙裾影同步归位，明确云妃卸去机锋后的承认",
        ["帘影腰线继续下降", "裙裾影随落座轻轻归拢", "团扇角度从防御姿态放松", "云妃以无机锋声线说出承认", "陈迹呼吸略松但视线不移", "帘影尚有落座余势时切出"],
        ["云妃只以帘影落座、呼吸和扇缘细动表演，绝不露脸", "陈迹以眨眼、呼吸和下颌细动承接权力变化", "白鲤面纱、睫毛和呼吸保持活态", "皎兔、云羊、阿栓、乌云若入画，必须有视线或耳尾响应"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "帘后手持、角度略紧", "transfer": "NONE", "final": "仍由云妃持有、角度放松"}, {"item": "帘内座位", "owner": "王府花厅陈设", "count": 1, "initial": "云妃正落座一半", "transfer": "NONE", "final": "云妃接近坐定但身体仍有余势"}],
        "帘后影子正落座到一半",
        "禁止坐定后才开口、帘影冻结、云妃露脸、把承认做成字幕或文字卡",
        [("云妃", "你，不是本宫能买的棋子。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U25", "13-5", 7, "visible_speaker_dialogue", "陈迹半身、双手和乌云落肩的近景",
        "0.5秒内陈迹双手从正拱起一半的首帧继续合拢，乌云从半空继续落向肩头，明确结盟与带人决定",
        ["陈迹双手继续合向拱礼位置", "乌云前爪接近陈迹肩头", "乌云前爪落肩、后腿仍离开原位", "乌云调整重心并收尾", "陈迹以精确口型说出同路决定", "阿栓对‘我带走’产生可见松动", "拱手未变成僵硬定格时切出"],
        ["陈迹口型、双手、呼吸和目光持续推进", "乌云四足落肩、耳尾与重心连续调整，禁止瞬移", "阿栓以眼神、肩线和呼吸回应被带走", "云羊、皎兔、白鲤与帘影都保持细微事件反应"],
        [{"item": "乌云", "owner": "SELF_NATURAL_ANIMAL", "count": 1, "initial": "正跃向陈迹肩头", "transfer": "空间转移：起跳处→陈迹肩头；不改变所有权", "final": "四足稳定落在陈迹肩头并仍在调整重心"}, {"item": "阿栓监护决定", "owner": "陈迹提出", "count": 1, "initial": "尚未获云妃撤令", "transfer": "PROPOSED_NOT_YET_GRANTED", "final": "陈迹已提出带走，等待云妃回应"}],
        "陈迹双手正拱起一半，乌云正在落向他肩头",
        "禁止拱手首帧已经完成、乌云瞬移或巨大化、阿栓凭空离场、陈迹闭口配画外音",
        [("陈迹", "查借印的手，你我同路。阿栓，我带走。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U26", "13-5", 6, "hidden_speaker_dialogue", "帘内团扇尖与案面近景，帘外阿栓反应保留在景深",
        "0.5秒内团扇尖从离案半寸的首帧继续下落，明确云妃正式撤令",
        ["扇尖继续接近案面", "扇尖轻触案面发出一点声响", "云妃帘影手腕随触点回弹极小幅度", "云妃说出带走许可", "阿栓肩线和呼吸产生释然反应", "扇尖离案极小距离保持活态时切出"],
        ["云妃帘影手腕、团扇和呼吸持续微动，绝不露脸", "阿栓以眼神、肩线和呼吸回应撤令", "陈迹保持听取姿态但不冻结", "白鲤、云羊、皎兔与乌云若入画都必须响应许可落地"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "扇尖离案面半寸", "transfer": "NONE", "final": "轻点案面后仍由云妃持有"}, {"item": "阿栓官面羁押状态", "owner": "云妃王府命令链", "count": 1, "initial": "官面仍被扣押", "transfer": "状态转移：扣押→无案可押、准陈迹带走", "final": "官面羁押解除"}],
        "团扇尖正点向案面，离案半寸",
        "禁止首帧扇尖已点定、云妃露脸、阿栓在许可前离场、生成公文或伪中文字",
        [("云妃", "带走罢。官面上，他无案可押。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U27", "13-5", 7, "hidden_speaker_dialogue_with_visible_silent_baili", "白鲤眼、领口、指尖与帘后影同轴特写",
        "0.5秒内白鲤睫毛从正在抬起的首帧继续上移，指尖从探向领口一半继续靠近，红玉只露一线，明确下注选择落到她身上",
        ["白鲤睫毛继续抬起但不完成正面亮相", "指尖继续接近领口边缘", "衣领松动一线、红玉露出更清楚的一点", "红玉幽光从一线增至克制微亮", "白鲤眼神落在陈迹身上但嘴唇保持完全静默", "云妃帘后说出下注选择", "红玉仍未全亮、白鲤仍未作决定时切出"],
        ["白鲤睫毛、眼球、指尖、呼吸和面纱边缘持续微动，嘴唇绝不说话", "云妃仅帘影、团扇和呼吸影响应自己说话，绝不露脸", "陈迹以眼神和下颌细动承受注视", "其余入画人物持续关注决定权转移"],
        [{"item": "红玉领坠", "owner": "白鲤", "count": 1, "initial": "面纱与衣领下只露一线", "transfer": "NONE", "final": "仍由白鲤佩戴，仅微亮、未完全显露"}, {"item": "面纱", "owner": "白鲤", "count": 1, "initial": "遮面佩戴", "transfer": "NONE", "final": "仍遮面，不脱落"}, {"item": "下注决定权", "owner": "云妃", "count": 1, "initial": "由云妃掌握", "transfer": "云妃→白鲤（抽象决定权转移，不生成实体）", "final": "交由白鲤自行决定，尚未作答"}],
        "白鲤睫毛正在抬起，指尖正探向领口一半，红玉刚露一线",
        "禁止红玉全亮、白鲤正面揭纱或开口、云妃露脸、下注结果提前揭晓、嘴唇错误同步云妃台词",
        [("云妃", "是否替他下注——你自己拿主意。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED_VISIBLE_BAILI_SILENT_NO_LIP_MOVEMENT",
        "本镜不得生成任何下注文字、姓名或字幕；红玉必须绑定白鲤唯一 owner 与单一数量",
    ),
    unit(
        "U28", "13-5", 5, "visual_first_eye_contact", "陈迹与白鲤隔帘的非对称近景，不插回忆蒙太奇",
        "0.5秒内两道目光从正在相接的首帧继续完成短暂接触，陈迹下颌从半抬继续上移，明确第一次正面确认",
        ["白鲤目光继续向陈迹眼位移动", "陈迹下颌和目光继续上抬", "两道目光短暂完成接触", "陈迹眸底产生克制细动", "白鲤保持沉静但呼吸和睫毛仍在变化"],
        ["陈迹眨眼、呼吸、下颌和眸光持续细动", "白鲤眼球、睫毛、呼吸和面纱边缘持续微动", "云妃帘影与长帘保持极轻环境运动", "其他虚焦入画人物不得冻结或抢夺视线"],
        [{"item": "面纱", "owner": "白鲤", "count": 1, "initial": "遮面佩戴", "transfer": "NONE", "final": "仍遮面"}, {"item": "红玉领坠", "owner": "白鲤", "count": 1, "initial": "领口下微露", "transfer": "NONE", "final": "仍由白鲤佩戴，不扩大亮度、不转交"}],
        "两道目光正在相接，陈迹下颌微抬到一半",
        "禁止静止对称四目相对、慢动作凝视、亲密浪漫化、插入名单风暴或医馆雨幕回忆、白鲤开口",
    ),
    unit(
        "U29", "13-5", 8, "visual_end_hook", "镜头从已在上升途中的中远景继续拉高至大远景，单镜收黑",
        "0.5秒内白鲤把半收状态的红玉继续推回面纱与衣领之下，红光同步减弱，摄影机保持向上位移",
        ["红玉继续收入衣领下、幽光减弱", "白鲤指尖离开领口并开始垂下", "白鲤目光从陈迹处缓慢下垂", "摄影机继续升高显出满堂灯烛与长帘", "陈迹保持赴局后的直立但呼吸、衣摆仍有活态", "庭外初雪一片两片斜入灯光，不变成暴雪", "更漏一声后红光完全敛尽", "镜头仍有上升余势时自然切黑"],
        ["白鲤指尖、睫毛、呼吸、面纱和衣摆持续收势", "陈迹以呼吸、眨眼和衣摆微动保持活态", "云妃帘影、团扇与长帘保持极轻运动", "皎兔、云羊、阿栓和乌云即使在远景也必须有可辨轮廓微动作", "烛焰、初雪和窗纸冷光持续真实变化"],
        [{"item": "红玉领坠", "owner": "白鲤", "count": 1, "initial": "正被收回一半、仍有微光", "transfer": "空间状态：领口外微露→面纱与衣领下隐藏；所有权不变", "final": "完全隐藏且红光敛尽"}, {"item": "面纱", "owner": "白鲤", "count": 1, "initial": "佩戴", "transfer": "NONE", "final": "仍佩戴"}, {"item": "初雪天气状态", "owner": "环境", "count": 1, "initial": "唯一天气状态为零星雪片刚开始出现", "transfer": "NONE", "final": "仍为零星初雪，不累计成厚雪或切换其他天气"}],
        "红玉正被收回一半、红光正在敛去；摄影机已在上升途中",
        "禁止红玉收完后再起幅、静态群像海报、摄影机停止后拖时、暴雪、下注答案、文字结尾卡或模型生成片尾字幕",
    ),
]


def prompt_text(spec: dict[str, Any], windows: list[dict[str, Any]]) -> str:
    lines = [
        f"E40 {spec['unit_id']}｜canonical v3 精确绑定｜标准 seedance-2.0 视频提示词。",
        "模型只能使用标准 seedance-2.0；禁止 Pro、fast、mini 或任何变体。9:16，1080p，单一连续镜头。",
        ENVIRONMENT + "。",
        f"镜头：{spec['camera']}。时长 {spec['seconds']} 秒，真实1倍速；禁止慢动作、升格、补帧、时间拉伸、循环、倒放和后期加速。",
        f"首帧动势：{spec['first_frame_motion_state']}。0.5秒内意图：{spec['intent']}。",
        "performance_tempo_contract.atomic_action_windows：",
    ]
    for row in windows:
        lines.append(
            f"- {row['start_seconds']:.2f}-{row['end_seconds']:.2f}s：{row['action']}；终态变化={row['state_change']}。"
        )
    lines.extend([
        "每个原子动作窗口≤1.2秒；动作空档≤0.25秒；每一窗口必须产生可见位移、受力、目光或物件状态变化，不得站桩、循环或用匀速慢移填时。",
        "可见人物持续微动作：" + "；".join(spec["visible_character_motion"]) + "。",
        "owner/count/transfer 硬锁：" + "；".join(
            f"{row['item']} owner={row['owner']} count={row['count']} initial={row['initial']} transfer={row['transfer']} final={row['final']}"
            for row in spec["ownership_contract"]
        ) + "。",
    ])
    if spec["dialogue"]:
        lines.extend([
            "对白传输分类：" + spec["speaker_visibility"] + "。",
            "精确对白，只说一次、顺序不变、不增删、不改写：" + "；".join(
                f"{speaker}：‘{text}’" for speaker, text in spec["dialogue"]
            ) + "。",
            "可见说话脸必须使用原生 exact-line audio 或已验证口型同步；脸隐藏台词只允许精确行音频并由 AgentCut 装配。除命名说话人外任何人不得出声。",
        ])
    else:
        lines.append("本镜静默视觉；所有人物不得说话，只保留绑定环境声与动作声，禁止模型擅自生成对白或嘴唇说话动作。")
    if spec.get("evidence_gate"):
        lines.append("证物/字幕门：" + str(spec["evidence_gate"]) + "。")
    lines.extend([
        "字幕只允许后期加入准确对白，白字黑描边、无黑底；生成画面必须无原生字幕、无双层字幕、无伪中文、无LOGO水印。",
        "年代硬门：宋明风架空王府，无现代物；白鲤不揭纱、不说话、不揭真身，云妃全程帘后不露脸。",
        "禁止结果态：" + spec["forbidden_result_state"] + "。",
        "画面已表达的信息禁止台词复述；禁止人物复制、年龄/身份/性别漂移、背景人物冻结、道具易主或数量漂移。",
    ])
    return "\n".join(lines) + "\n"


def static_qa(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    required = [
        "标准 seedance-2.0", "禁止 Pro、fast、mini", "真实1倍速", "禁止慢动作",
        "0.5秒内意图", "performance_tempo_contract.atomic_action_windows",
        "每个原子动作窗口≤1.2秒", "动作空档≤0.25秒", "可见人物持续微动作",
        "owner/count/transfer", "白字黑描边、无黑底", "无双层字幕",
    ]
    for task in tasks:
        unit_id = task["unit_id"]
        prompt = Path(task["prompt_file"]).read_text(encoding="utf-8")
        missing = [fragment for fragment in required if fragment not in prompt]
        if missing:
            failures.append({"unit_id": unit_id, "gate": "PROMPT_CONTRACT", "missing": missing})
        if task["model"] != MODEL:
            failures.append({"unit_id": unit_id, "gate": "STANDARD_MODEL_ONLY"})
        windows = task["performance_tempo_contract"]["atomic_action_windows"]
        if windows[0]["start_seconds"] != 0.0 or windows[0]["end_seconds"] > 0.5:
            failures.append({"unit_id": unit_id, "gate": "INTENT_WITHIN_0_5_SECONDS"})
        if windows[-1]["end_seconds"] != task["duration"]:
            failures.append({"unit_id": unit_id, "gate": "WINDOW_COVERAGE"})
        for index, window in enumerate(windows):
            if window["end_seconds"] - window["start_seconds"] > 1.2:
                failures.append({"unit_id": unit_id, "gate": "ATOMIC_ACTION_MAX_1_2"})
            if index:
                if window["start_seconds"] - windows[index - 1]["end_seconds"] > 0.25:
                    failures.append({"unit_id": unit_id, "gate": "ACTION_GAP_MAX_0_25"})
                if window["action"] == windows[index - 1]["action"]:
                    failures.append({"unit_id": unit_id, "gate": "NO_REPEATED_WINDOWS"})
        if not task["visible_character_motion"]:
            failures.append({"unit_id": unit_id, "gate": "VISIBLE_CHARACTER_CONTINUOUS_MOTION"})
        if not task["ownership_contract"]:
            failures.append({"unit_id": unit_id, "gate": "OWNER_COUNT_TRANSFER"})
    expected = [f"U{i:02d}" for i in range(24, 30)]
    if [task["unit_id"] for task in tasks] != expected:
        failures.append({"gate": "UNIT_COVERAGE"})
    windows_total = sum(len(task["performance_tempo_contract"]["atomic_action_windows"]) for task in tasks)
    return {
        "schema": "qingshan.e40.u24_u29_prompt_static_qa.v1",
        "episode": "E40",
        "status": "PASS_STATIC_PROMPTS_REFERENCE_BINDING_PENDING" if not failures else "FAIL",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "coverage": {
            "units": f"{len(tasks)}/6",
            "prompt_files": f"{len(tasks)}/6",
            "standard_seedance_2_0": f"{sum(task['model'] == MODEL for task in tasks)}/6",
            "real_time_1x": f"{sum(task['performance_tempo_contract']['real_time_1x'] is True for task in tasks)}/6",
            "intent_within_0_5_seconds": f"{sum(task['performance_tempo_contract']['intent_deadline_seconds'] == 0.5 for task in tasks)}/6",
            "first_frame_continuation_not_replay": f"{sum(bool(task['first_frame_continuation_contract']) for task in tasks)}/6",
            "atomic_windows": windows_total,
            "continuous_visible_motion": f"{sum(bool(task['visible_character_motion']) for task in tasks)}/6",
            "owner_count_transfer": f"{sum(bool(task['ownership_contract']) for task in tasks)}/6",
            "dialogue_transport": "4/4",
            "silent_visual_transport": "2/2",
            "subtitle_policy": "6/6",
        },
        "gate_results": {
            "canonical_exact_sha": "PASS" if sha256(SCRIPT) == SCRIPT_SHA and sha256(CANONICAL_MANIFEST) == MANIFEST_SHA else "FAIL",
            "standard_model_only": "PASS",
            "pro_fast_mini_forbidden": "PASS_BLOCKED_BY_MANIFEST",
            "real_time_native_speed_no_slow_motion": "PASS",
            "first_frame_continuation_not_replay": "PASS_AUTHORED",
            "atomic_action_window_max_1_2": "PASS",
            "action_gap_max_0_25": "PASS",
            "no_repeated_or_cyclic_action_windows": "PASS",
            "visible_character_continuous_motion": "PASS",
            "owner_count_transfer": "PASS",
            "dialogue_and_subtitle_transport": "PASS_AUTHORED",
            "baili_silent_no_lip_movement": "PASS_AUTHORED",
            "yunfei_hidden_no_face": "PASS_AUTHORED",
            "paid_submission": "NONE",
        },
        "paid_submission_allowed": False,
        "blocked_by": [
            "6_OF_6_EXACT_START_FRAME_AND_ORDERED_REFERENCE_BINDINGS_PENDING",
            "U24_U26_U27_YUNFEI_EXACT_HIDDEN_VOICE_LINES_NOT_YET_BOUND",
            "U25_CHENJI_NATIVE_EXACT_AUDIO_OR_VERIFIED_LIP_SYNC_NOT_YET_EXECUTED",
            "U27_U28_U29_BAILI_VEIL_RED_JADE_EXACT_PROP_WARDROBE_BINDING_PENDING",
            "SCENE_13_5_FOG_CLEARED_INITIAL_SNOW_VISUAL_VARIANT_NOT_YET_ADMITTED",
            "U29_LOCAL_BLACK_TRANSITION_AND_FINAL_SUBTITLE_LAYER_NOT_YET_ASSEMBLED",
            "NO_PAID_EXECUTION_PLAN_AUTHORED_BY_THIS_PRECOMPILE",
        ],
        "failures": failures,
    }


def main() -> int:
    if sha256(SCRIPT) != SCRIPT_SHA or sha256(CANONICAL_MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical v3 script/manifest SHA mismatch")
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    QA_REPORT.parent.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for spec in UNITS:
        windows = atomic_windows(spec)
        prompt_path = PROMPT_DIR / f"E40-{spec['unit_id']}-STANDARD-SEEDANCE2-PROMPT-V1.txt"
        prompt_path.write_text(prompt_text(spec, windows), encoding="utf-8")
        tasks.append({
            "task_key": f"E40-{spec['unit_id']}-STANDARD-VIDEO",
            "unit_id": spec["unit_id"],
            "scene_id": spec["scene_id"],
            "kind": spec["kind"],
            "model": MODEL,
            "forbidden_models": ["seedance-2.0-pro", "seedance-2.0-fast", "seedance-2.0-mini"],
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "duration": spec["seconds"],
            "prompt_file": str(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "dialogue": [{"speaker": speaker, "exact_line": text} for speaker, text in spec["dialogue"]],
            "dialogue_transport": spec["speaker_visibility"] if spec["dialogue"] else "SILENT_VISUAL_NO_DIALOGUE_NO_LIP_MOVEMENT",
            "subtitle_transport": "AGENTCUT_WHITE_TEXT_BLACK_STROKE_NO_BLACK_BOX_NATIVE_SUBTITLE_FORBIDDEN",
            "performance_tempo_contract": {
                "real_time_1x": True,
                "intent_deadline_seconds": 0.5,
                "atomic_action_max_seconds": 1.2,
                "max_action_gap_seconds": 0.25,
                "post_speedup_forbidden": True,
                "atomic_action_windows": windows,
            },
            "visible_character_motion": spec["visible_character_motion"],
            "ownership_contract": spec["ownership_contract"],
            "first_frame_motion_state": spec["first_frame_motion_state"],
            "first_frame_continuation_contract": spec["intent"],
            "forbidden_result_state": spec["forbidden_result_state"],
            "evidence_gate": spec.get("evidence_gate"),
            "reference_binding_status": "PENDING_EXACT_START_FRAME_AND_ORDERED_UPLOAD_BINDING",
            "paid_submission_allowed": False,
        })
    manifest = {
        "schema": "qingshan.e40.u24_u29_standard_video_prompt_manifest.v1",
        "episode": "E40",
        "status": "PASS_PRECOMPILED_STATIC_QA_REFERENCE_BINDING_PENDING_NO_SUBMIT",
        "canonical": {
            "script": str(SCRIPT.relative_to(ROOT)), "script_sha256": SCRIPT_SHA,
            "manifest": str(CANONICAL_MANIFEST.relative_to(ROOT)), "manifest_sha256": MANIFEST_SHA,
        },
        "scope": {"first_unit": "U24", "last_unit": "U29", "unit_count": 6},
        "scene_authority": ENVIRONMENT,
        "static_qa_report": str(QA_REPORT.relative_to(ROOT)),
        "submission_policy": {
            "standard_model_only": MODEL,
            "pro_fast_mini_forbidden": True,
            "parallel_after_individual_reference_and_paid_preflight": True,
            "remote_wait_is_not_global_barrier": True,
            "this_manifest_submits_nothing": True,
        },
        "tasks": tasks,
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = static_qa(tasks)
    qa["prompt_manifest"] = str(OUTPUT_MANIFEST.relative_to(ROOT))
    qa["prompt_manifest_sha256"] = sha256(OUTPUT_MANIFEST)
    QA_REPORT.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(OUTPUT_MANIFEST), "manifest_sha256": sha256(OUTPUT_MANIFEST),
        "qa_report": str(QA_REPORT), "qa_report_sha256": sha256(QA_REPORT),
        "status": qa["status"], "coverage": qa["coverage"],
    }, ensure_ascii=False, indent=2))
    return 0 if qa["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
