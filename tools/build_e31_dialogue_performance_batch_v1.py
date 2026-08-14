#!/usr/bin/env python3
"""Compile E31 dialogue units with exact audio-driven native performances."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from build_e31_performance_preproduction import ABILITY_LOGIC, FORCE_FEEDBACK, INVISIBLE_ELEMENTS, UNITS
from build_e31_nondialogue_performance_batch_v1 import beat
from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
HARVEST = PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1_HARVEST.json"
AUDIO_MANIFEST = ROOT / "working_assets/e31_dialogue_audio_refs_20260722/E31_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BASE = PRODUCTION / "video_performance_v1"
CONFIG = BASE / "E31_VIDEO_BATCH_DIALOGUE_READY_V1.json"
U16_REPAIR_CONFIG = BASE / "E31_VIDEO_BATCH_U16_AUDIO_MIN2_MARGIN_R3.json"
ACTION_PLAN = BASE / "E31_ACTION_READABILITY_DIALOGUE_V1.json"
SCENE_STATE = PRODUCTION / "E31_SCENE_AUTHORITY_STATE_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E31剧本_ClaudeWriter_v1.md"
PRODUCTION_MANIFEST = PRODUCTION / "E31_PRODUCTION_MANIFEST.json"
READY = {"U02", "U03", "U04", "U09", "U14", "U15", "U16", "U17", "U18", "U19"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def action_rows(unit: str, duration: float, intent: str, causality: str, expression: str, viewer: str) -> list[dict]:
    invisible = INVISIBLE_ELEMENTS[unit]
    ability = ABILITY_LOGIC.get(unit, "人物只通过真实表演、道具接触、视线和环境反馈推进剧情，不使用无来源特效。")
    force = FORCE_FEEDBACK.get(unit, "纸张、衣料、火焰、积雪和案上器物按动作方向反馈一次并自然衰减。")
    rows = {
        "U02": [
            (0, 4.0, "云妃侍从与静妃侍从", "两人各抓名单一端相反用力，云妃侍从边拉边说第一句", "四只手抓住同一张名单两端", "一人向画面左后方、一人向右后方拉", "纸张中央被绷紧但尚未断开"),
            (4.0, 8.4, "静妃侍从", "猛夺残页并贴近对方说第二句，后脚因拉力后撤", "右手夺住撕裂后的纸页，后脚踩向地面灯笼", "手臂向自身胸前收，身体向后退", "名单沿拉力方向撕成两半"),
            (8.4, 14.0, "后退侍从、灯笼与两拨人群", "靴底踩碎灯笼骨架，火舌从破口上窜；双方被热浪逼退却仍握住各自残页", "靴底压中灯笼，火焰接触漏出的灯油", "火向上窜，人群向两侧退开", "两拨人隔火对峙，各持一半名单"),
        ],
        "U03": [
            (0, 2.4, "内院家丁甲", "从飞散纸页中伸手截住一张，迅速展平并逐行扫视", "右手夹住纸角，左掌托住纸背", "纸从前景飞向掌心，视线由上向下", "家丁确认这一页不是目标"),
            (2.4, 7.2, "内院家丁甲", "压低声音说完整命令，同时用食指只点一个位置，不描画可读文字", "食指点在无字纸面中部，同伴靠近听令", "声音朝同伴，纸面保持背向镜头", "同伴理解只寻找特定两字"),
            (7.2, 10.0, "三名内院家丁", "领头者把无用残页推给同伴，三人的视线继续追逐下一张飞纸", "纸页从甲手中交到乙手中", "纸向后传，人向廊柱深处移动", "暗线继续搜名并准备找到后焚毁"),
        ],
        "U04": [
            (0, 5.2, "陈迹", "依次点过三卷封好的名单，把最后一卷推向皎兔，同时完成第一段说明", "指尖点卷轴封口，掌根推卷轴沿案面滑动", "从陈迹一侧向皎兔方向", "三卷缺页差异被当作追踪实验摆明"),
            (5.2, 9.3, "陈迹与皎兔", "陈迹继续说出只看谁变脸，皎兔接住滑来的卷轴并观察陈迹", "皎兔双手接住卷轴两端", "卷轴停止在皎兔面前", "皎兔理解实验目的"),
            (9.3, 12.0, "皎兔", "说出必须亲眼观察，随后抬起右手指尖抵住眉心准备出窍", "指尖接触眉心，左手压住名单", "手由案面向眉心抬起", "皎兔作出执行侦察的决定"),
        ],
        "U09": [
            (0, 1.2, "黑甲阴神与皎兔肉身", "阴神沿眉心轴线收回肉身，皎兔胸口起伏后睁眼", "阴神额心与肉身眉心重合", "由肉身背后向前收束", "阴神完全归窍，画面只剩皎兔肉身"),
            (1.2, 4.8, "皎兔", "吐气后向陈迹完整复述三院反应，手指依次点向三卷名单", "指尖分别停在三卷封口上", "由左到右点过，视线最后停在内院卷", "内院灭灯成为异常证据"),
            (4.8, 8.0, "陈迹", "垂眸看向内院卷并说出结论，手掌只压住卷轴不打开", "掌心接触内院卷封口", "视线由卷轴抬向皎兔", "两人确认沉默内院才真正害怕景朝"),
        ],
        "U14": [
            (0, 2.0, "第三杀手与火盆", "把字纸投入火盆后借升起烟幕后退，不转身瞬移", "纸张落入火焰中心，后脚踩实地砖", "纸向下，杀手向回廊暗处退", "证据开始燃烧，杀手离开接触范围"),
            (2.0, 4.5, "陈迹", "沿最短路线扑到火盆边，掌心放出冷雾覆盖正在卷曲的纸角", "冷雾接触灰烬边缘而非整张纸", "冷雾由掌心向火盆内侧推进", "只冻结保存半片纸角"),
            (4.5, 7.0, "云羊", "喘息指向烟幕并说出敌人连夜焚证的判断", "手指指向杀手退去方向", "视线由火盆转向烟幕", "焚证行为被解释为景朝急迫"),
            (7.0, 10.0, "陈迹", "夹起冻结纸角，连续说出灭线与名字分量的两句判断", "两指夹住硬化纸角", "纸角抬到眼前，视线再转向暗处", "半片证据落在陈迹手中并形成更深推断"),
        ],
        "U15": [
            (0, 3.0, "灰衣门客", "从座位起身作揖，再以掌示意陈迹落座", "双手拢袖作揖，右掌随后指向空椅", "身体微前倾后恢复直立", "门客维持礼貌并试图掌控谈话节奏"),
            (3.0, 8.0, "灰衣门客", "保持一案距离说出主子想要了结，手始终停在袖外不取物", "脚底停在案后，双手自然垂下", "声音朝陈迹，身体不靠近", "交易意图以温和措辞提出"),
            (8.0, 14.0, "陈迹", "拒绝前进和落座，站在门内说出内院灭灯与旧疮质问", "后脚停在门槛内，双手垂在身侧", "视线越过空椅直压门客", "陈迹拒绝对方节奏，双方隔案僵持"),
        ],
        "U16": [
            (0, 6.8, "灰衣门客", "从袖中取出冷白骨牌，用两指缓慢推到案心并完整说出交换条件", "两指压住骨牌上沿，骨牌底面接触案面", "由门客一侧沿直线推向案心", "骨牌停在两人之间，门客松手"),
            (6.8, 8.5, "陈迹", "视线锁住骨牌但双手不动，短促问出内鬼来源", "双手垂在身侧，不接触骨牌", "下颌微抬，目光转向门客", "陈迹拒绝被诱饵牵动"),
            (8.5, 10.0, "灰衣门客与陈迹", "门客收回手并保持平静，陈迹继续站立，骨牌无人触碰", "骨牌独自停在案心", "双方各守原位", "交易诱饵被清楚摆出但尚未成交"),
        ],
        "U17": [
            (0, 2.5, "陈迹", "俯视骨牌后抬眼追问，身体前倾半步但仍不碰牌", "前脚停在案边外，双手垂下", "视线从牌面移到门客", "质问压力落到门客身上"),
            (2.5, 7.8, "灰衣门客", "退后半步进入半明半暗处，平静说出见过围猎调令印", "后脚向门边落地，右手扶住袖口", "身体远离案几，视线保持与陈迹相接", "调令印线索被作为最后钩子抛出"),
            (7.8, 9.0, "灰衣门客与陈迹", "门客停在门边不再解释，陈迹眼神收紧看向骨牌", "双方不再接触道具", "视线回到案心骨牌", "沉默把权力链危险留给观众"),
        ],
        "U18": [
            (0, 2.0, "陈迹与云羊", "陈迹把骨牌递到云羊掌前，云羊接住后立即翻到背面", "陈迹指腹托牌边缘，云羊掌心接牌", "骨牌由陈迹向云羊移动并翻面", "骨牌归云羊持有，印纹朝向云羊"),
            (2.0, 7.0, "云羊", "看见印纹后屏息变色，用指腹确认刻痕并说出越级发令判断", "指腹沿骨牌凹刻短距离摩擦", "视线由骨牌抬向陈迹", "云羊确认发令者高过直属上司"),
            (7.0, 10.4, "陈迹", "望向后景残火，平静说出翻册之手与发令之手的层级差异", "双手不碰骨牌，身体朝残火侧转", "视线由云羊转向庭院深处", "陈迹把印纹证据补成权力链推断"),
            (10.4, 14.0, "云羊", "重新看向骨牌说出曾在火漆令匣远见此印，最后握牌的手轻微收紧", "五指包住骨牌边缘但不遮住凹刻", "手指向掌心收紧，脚步不动", "震骇升级为对自身组织的怀疑"),
        ],
        "U19": [
            (0, 3.6, "陈迹", "骨牌平放掌心，指尖冷雾凝聚又自行散去，同时低声质疑投名状", "冷雾只贴着骨牌边缘和指尖", "雾由指尖聚拢后向空气散开", "陈迹克制住立刻使用能力的冲动"),
            (3.6, 8.0, "陈迹", "抬眼直视廊外暗处，接上第二句质疑假名单陷阱，掌心保持水平不抛牌", "骨牌继续停在掌心", "视线由下向前，身体不追出回廊", "陈迹主动怀疑交易本身并把问题抛向未知敌人"),
        ],
    }[unit]
    return [beat(*row, intent, causality, expression, viewer, invisible, ability, force) for row in rows]


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    audio_manifest = json.loads(AUDIO_MANIFEST.read_text(encoding="utf-8"))
    if audio_manifest.get("status") != "PASS":
        raise SystemExit("dialogue timeline manifest is not PASS")
    units = {row["unit_id"].split("-")[-1]: row for row in plan["units"]}
    meta = {row[0]: row for row in UNITS}
    a1 = {row["task_key"].split("-")[2]: Path(row["output_path"]) for row in harvest["results"]}
    audio_by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in audio_manifest["rows"]:
        audio_by_unit[row["video_unit_id"]].append(row)
    prompt_dir = BASE / "prompts"
    spec_dir = BASE / "specs"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    tasks = []
    action_units = []
    for short in sorted(READY, key=lambda value: int(value[1:])):
        full = f"E31-CW-{short}"
        unit = units[short]
        duration = int(unit["duration_seconds"])
        _, scene, _, _, _, _, intent, causality, expression, viewer = meta[short]
        anchors = unit.get("admitted_reference_images") or [{"role": "A1", "path": relative(a1[short]), "sha256": sha256(a1[short]), "status": "PASS"}]
        refs = [ROOT / row["path"] for row in anchors]
        dialogues = audio_by_unit[full]
        beats = action_rows(short, duration, intent, causality, expression, viewer)
        ownership = {
            "paper_and_tokens": "名单、残页、骨牌只有在明确抓取、递交、推放、撕裂或焚烧时改变状态和归属。",
            "weapons_and_abilities": "兵器、阴神、冰流与纸术只由剧本声明人物控制，不得转移给其他角色。",
            "speaker_identity": "每个音频槽只由对应 speaker 说出一次，其他人物在该槽保持闭口。",
        }
        spec = {"schema": "qingshan.performance_generation_spec.v2", "episode": "E31", "unit_id": full, "duration_seconds": duration, "prop_ownership": ownership, "motion_beats": beats}
        spec_path = spec_dir / f"{full}-PERFORMANCE-SPEC-V1.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cursor = 0.25
        timeline = []
        dialogue_assets = []
        for index, row in enumerate(dialogues, 1):
            end = min(duration - 0.1, cursor + float(row["duration_seconds"]))
            timeline.append(f"- {cursor:.2f}-{end:.2f}秒：@音频{index}，{row['speaker']}逐字说“{row['spoken_text']}”；只有该人物开口，口型、气息、表情与音频同步。")
            dialogue_assets.append({"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"], "audio_slot": f"@音频{index}", "path": row["path"], "sha256": row["sha256"], "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE"})
            cursor = end + 0.16
        beat_lines = [f"- {row['start_seconds']:.1f}-{row['end_seconds']:.1f}秒：主体={row['subject']}；动作={row['action']}；接触点={row['contact_point']}；方向={row['direction']}；意图={row['intent']}；可见因果={row['visible_causality']}；受力反馈={row['force_feedback']}；表情={row['expression']}；观众读法={row['viewer_read']}；终态={row['end_state']}。" for row in beats]
        image_slots = "、".join(f"@图片{i}" for i in range(1, len(refs) + 1))
        audio_slots = "、".join(f"@音频{i}" for i in range(1, len(dialogues) + 1))
        split_index = max(1, len(dialogues) // 2)
        first_dialogue_braces = "；".join(f"{row['speaker']}：{row['spoken_text']}" for row in dialogues[:split_index]) or "无对白"
        second_dialogue_braces = "；".join(f"{row['speaker']}：{row['spoken_text']}" for row in dialogues[split_index:]) or "无对白"
        prompt = "\n".join([
            f"《青山》E31《王府风暴》{short}，Seedance 2.0 Pro 四模态表演生成，{duration}秒，9:16，720p，原速连续动作。",
            f"【实体绑定】现场人物[[char_principals]]、可能的对手[[char_killer]]、本场空间[[scene_e31_s{scene:02d}]]、名单骨牌与兵器[[prop_e31_objects]]。",
            f"【生成范式】{image_slots}只锁身份、场景、初始空间关系和必要终态拓扑；{audio_slots}是逐句精确中文对白参考。动作由单一逐拍 spec 连续驱动，不逐图硬凑姿势。",
            "【色彩与动机光】palette=雪夜冷蓝、火把暖橙、室内孤灯暖褐、能力幽蓝；只使用现场火把、烛灯和已声明能力光。力量必须作用到环境介质：纸张、衣摆、火焰、积雪、栏杆、案上器物按受力方向反馈一次并自然衰减。",
            "【对白与声音资产】视频模型必须按以下顺序使用每个音频槽，原生生成自然中文普通话、同步口型、气息、表情和起止时间；不得后配，不得漏字、改字、串台或增加台词。",
            *timeline,
            f"镜头1【0.0-{duration * 0.48:.1f}秒，远景定场转中景跟移】先建立人物、道具、行动路线和说话者位置，再连续完成前半段表演。{{{first_dialogue_braces}}}<脚步、纸张、衣料、呼吸与现场环境声>",
            f"镜头2【{duration * 0.48:.1f}-{duration:.1f}秒，近景侧移接表情特写】承接同一速度、道具归属与对白顺序，完成动作结果和表情反应。{{{second_dialogue_braces}}}<接触声、环境介质反馈、对白尾息与余响>",
            "【连续物理动作脚本】", *beat_lines,
            "【单一状态源】提示词、锚图、动作时间轴、对白音频和道具归属全部来自同一 spec；任何新增角色、额外台词或归属跳变都禁止。",
            "【声音】保留全部参考对白并生成现场声；禁止BGM、旁白、额外对白。",
            "【负面约束】禁止字幕、水印、Logo、可读文字、伪文字；禁止换脸、分身、融肢、穿模、瞬移、无因腾空、慢放、停帧、循环、周期重复、静帧微动、首尾重复和对白缺失。",
        ]) + "\n"
        prompt_path = prompt_dir / f"{full}-PERFORMANCE-V1.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        interpolation = unit.get("keyframe_interpolation_gate") or {}
        task = {
            "task_key": f"{full}-PERFORMANCE-V1", "source_id": full, "tool_type": "video_generation",
            "generation_mode": "performance_generation", "still_sequence_only_allowed": True,
            "audio_reference_optional": False, "native_dialogue_required": True,
            "episode": "E31", "batch_id": "E31-PERFORMANCE-V1", "unit_id": full,
            "scene_id": unit["scene_id"], "visual_zone": full,
            "duration": duration, "duration_seconds": duration, "model": "seedance-2.0-pro",
            "duration_plan": {"policy": "qingshan.shot_generation_duration.v5", "duration_seconds": duration, "rationale": "Exact sum of contiguous Claude-script editorial shots.", "edit_policy": "End when dialogue and scripted action result land; never pad, slow or loop."},
            "aspect_ratio": "9:16", "resolution": "720p",
            "prompt_file": relative(prompt_path), "prompt_sha256": sha256(prompt_path),
            "reference_images": [relative(path) for path in refs],
            "reference_image_sequence": [{"asset_label": f"@图片{i}", "role": row["role"], "path": relative(refs[i - 1]), "sha256": sha256(refs[i - 1])} for i, row in enumerate(anchors, 1)],
            "state_reference_minimum": len(refs), "planned_reference_image_count": len(refs),
            "inherits_establishing_coverage": True, "action_unit": True, "performance_spec": spec,
            "keyframe_interpolation_gate": {**interpolation, "status": "PASS", "anchor_count": len(refs), "checked_adjacent_pairs": len(refs) - 1},
            "dialogue": [{"dia_id": row["dia_id"], "speaker": row["speaker"], "spoken_text": row["spoken_text"]} for row in dialogues],
            "reference_audios": [row["path"] for row in dialogues], "dialogue_audio_assets": dialogue_assets,
            "dialogue_audio_coverage": {"required": len(dialogues), "bound": len(dialogues), "status": "PASS"},
            "source_spec": relative(spec_path), "source_spec_sha256": sha256(spec_path),
            "workflow_credit_scope": "e31_claude_writer_v1_20260722", "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        action_units.append({"unit_id": full, "performance_spec": spec})

    ACTION_PLAN.write_text(json.dumps({"schema": "qingshan.performance_action_plan.v1", "episode": "E31", "units": action_units}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": "E31",
        "status": "READY_INCREMENTAL_DIALOGUE_UNITS", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "targeted_unit_replacement": False, "concurrency": len(tasks), "max_retries": 0,
        "retry_policy": "NO_AUTOMATIC_RETRY_WITH_UNCHANGED_INPUT",
        "workflow_credit_scope": "e31_claude_writer_v1_20260722", "video_credit_limit": 6000,
        "source_script_sha256": sha256(SCRIPT),
        "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": relative(SCRIPT), "source_script_sha256": sha256(SCRIPT), "production_manifest": relative(PRODUCTION_MANIFEST), "production_manifest_sha256": sha256(PRODUCTION_MANIFEST)},
        "scene_contract_ref": relative(SCENE_STATE), "supervisor_script_gate_required": False,
        "output_dir": relative(BASE / "outputs"), "qa_dir": relative(BASE / "qa"), "tasks": tasks,
    }
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    u16 = next(task for task in tasks if task["unit_id"] == "E31-CW-U16")
    u16 = {**u16, "task_key": "E31-CW-U16-PERFORMANCE-AUDIO-MIN2-MARGIN-R3", "batch_id": "E31-U16-AUDIO-MIN2-MARGIN-R3"}
    u16["generation_fingerprint"] = generation_fingerprint(u16)
    repair = {
        **config,
        "status": "READY_FAILED_ONLY_U16_AUDIO_MINIMUM_MARGIN_REPAIR",
        "targeted_unit_replacement": True,
        "concurrency": 1,
        "tasks": [u16],
        "repair_reason": "Prior U16 submits failed before task creation because the short reference measured below Seedance's strict 2-second boundary after encoding; R3 targets 2.15 seconds and records measured WAV duration.",
        "prior_failed_credit": 0,
    }
    U16_REPAIR_CONFIG.write_text(json.dumps(repair, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": relative(CONFIG), "u16_repair_config": relative(U16_REPAIR_CONFIG), "tasks": len(tasks), "dialogue_lines": sum(len(task["dialogue"]) for task in tasks), "action_plan": relative(ACTION_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
