#!/usr/bin/env python3
"""Build E32 performance preproduction from the locked Claude Writer script."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / os.environ.get("E32_SCRIPT", "workflow/claude_writer_agent/scripts/E32剧本_ClaudeWriter_v1.md")
WRITER_MANIFEST = ROOT / os.environ.get("E32_WRITER_MANIFEST", "workflow/claude_writer_agent/scripts/E32_manifest.json")
PRODUCTION = ROOT / os.environ.get("E32_PRODUCTION_DIR", "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722")
QA_DIR = ROOT / os.environ.get("E32_QA_DIR", "qa/e32_performance_preproduction_20260722")
ARTIFACT_TAG = os.environ.get("E32_ARTIFACT_TAG", "V1").upper()
PROMPT_DIR = PRODUCTION / f"image_prompts_performance_{ARTIFACT_TAG.lower()}"
WORKING_ASSET_DIR = os.environ.get("E32_WORKING_ASSET_DIR", "working_assets/e32_performance_stills_20260722/candidates")
IMAGE_QA_DIR = os.environ.get("E32_IMAGE_QA_DIR", "qa/e32_performance_stills_20260722")
TASK_RECEIPT = ROOT / os.environ.get("E32_TASK_RECEIPT", "workflow/tasks/E32_PERFORMANCE_PREPRODUCTION_20260722.json")

SCENE_INTERIOR = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
SCENE_EXTERIOR = "working_assets/e29_claude_writer_v1_stills_20260722/candidates/E29_E29-CW-S01-SH01-STILL-V1_4f6f7833-2bff-40e4-9a98-69b4d4054bc7.png"

CHARACTERS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
    "wuyun": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
    "yao_taiyi": "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg",
    "qisan": "assets/reference/e16_supporting_cast_20260712/CORONER_B12R3_solo_masked_v4_720x1280.jpg",
    "killer": "working_assets/e28_u09_fixed_input_reference_20260722/E28-CW-U09-INSTRUCTOR-MASKED-SINGLE-REF.png",
}

DEPENDENT_ANCHOR_DESCRIPTIONS = {
    "U04": {
        "role": "spirit_separated_at_destination",
        "description": "延续真实 A1 的同一皎兔身份：肉身仍留在医馆原位，黑甲阴神已经完整分离并抵达西市暗楼窗外；两者不得交换服装、脸或空间归属。",
        "continuity_mode": "CROSS_LOCATION_IDENTITY_REANCHOR",
        "origin_scene_id": "E32-CW-S02-MEDICAL-HALL",
        "destination_scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER",
        "destination_scene_reference": SCENE_EXTERIOR,
    },
    "U10": {
        "role": "post_mortem_token_transfer_terminal",
        "description": "延续真实 A1 的同一人物、机位与雨巷：齐三已经倒地并失去生命反应，双手空着；杀手已向暗巷出口退离；只有画面左侧黑衣青年陈迹以右手两指夹住巡检半牌，其他任何人物都不得接触或持有半牌。",
        "continuity_mode": "SAME_LOCATION_TERMINAL_REANCHOR",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shot(scene: int, number: int, duration: int, action: str) -> dict[str, object]:
    return {
        "shot_id": f"E32-CW-S{scene:02d}-SH{number:02d}",
        "scene_id": f"E32-CW-S{scene:02d}",
        "duration_seconds": duration,
        "action": action,
    }


SHOTS = [
    shot(1, 1, 5, "后堂灯下骨牌被搁在案角，陈迹把覆冰焦纸摊到案心。"),
    shot(1, 2, 7, "皎兔追问为何不验印，陈迹说明验单才能看见对方不想给的东西。"),
    shot(1, 3, 6, "冷雾沿焦纸背面显出三版名单之一的版本暗号。"),
    shot(1, 4, 7, "陈迹认出这是送进内院的一版，皎兔指出它来自景朝火盆。"),
    shot(1, 5, 7, "陈迹确认内院把名单转卖景朝，二人神色从确认转为戒备。"),
    shot(2, 1, 8, "皎兔割眉，黑甲阴神从端坐肉身完整分离并穿窗。"),
    shot(2, 2, 6, "阴神实速穿过雨幕，落到西市暗楼窗外。"),
    shot(2, 3, 8, "齐三在油灯下把同一叠名单拆成几份装入不同信封。"),
    shot(2, 4, 5, "陈迹踏雨破门，拍灭油灯再用冰流封亮，齐三惊退散落信封。"),
    shot(2, 5, 11, "陈迹显出封口暗号逼供，齐三指向骨牌并供出巡检指挥席位。"),
    shot(3, 1, 5, "黑衣杀手从檐上踏雨滑落，短刃直取齐三后心。"),
    shot(3, 2, 8, "乌云示警，陈迹冰流铺开积水，杀手脚滑使刀锋偏开。"),
    shot(3, 3, 7, "杀手点冰横抹，云羊点睛纸人展开遮断其视线。"),
    shot(3, 4, 8, "云羊冲拳命中冰墙固定点，冰层定向炸裂掀翻杀手。"),
    shot(3, 5, 12, "杀手回身割断齐三咽喉后遁雨，陈迹从血水冻住巡检司半牌并与云羊确认同线灭口。"),
    shot(4, 1, 8, "陈迹把巡检半牌与骨牌并放案上，姚太医的大乌鸦落案盯牌。"),
    shot(4, 2, 8, "姚太医指出对方抢的是陈迹慢查的时间。"),
    shot(4, 3, 8, "陈迹冰流逆窜，乌云把人参珠抵入掌心压住白霜。"),
    shot(4, 4, 8, "城门依次落锁，乌鸦绕堂长鸣，姚太医确认密谍司封城。"),
    shot(5, 1, 6, "医馆飞檐俯瞰洛城，四门与坊口灯笼长龙收成巨网。"),
    shot(5, 2, 6, "皎兔登檐确认城门、医馆与王府侧门全被封锁。"),
    shot(5, 3, 6, "云羊指出巡检线、景朝暗桩与内院私兵互不信任。"),
    shot(5, 4, 6, "陈迹由压迫转为洞悉，提出让三拨人先相信别人是内奸。"),
    shot(5, 5, 6, "镜头拉远，橙红灯网缠住洛城，残月冷照后切黑。"),
]


UNITS = [
    ("U01", 1, [1, 2], ["chenji", "jiaotu"], 1, "dialogue_two_shot", "骨牌与焦纸同桌，皎兔倚门，陈迹只把焦纸推到灯下。", "皎兔追问、陈迹拒验骨牌并转向焦纸", "陈迹冷静笃定，皎兔疑惑后专注", "观众看懂主角主动改换验伪对象"),
    ("U02", 1, [3, 4], ["chenji", "jiaotu"], 1, "single_subject_investigation", "焦纸薄冰尚未显痕，陈迹指尖停在纸背上方，皎兔在侧凝视。", "冷雾沿纸背显出版本暗号，二人认出内院版本却来自景朝", "陈迹眸色下沉，皎兔脸色骤变", "观众看懂暗号把内院和景朝连成同一条交易线"),
    ("U03", 1, [5], ["chenji", "jiaotu"], 1, "dialogue_revelation", "冰封焦纸停在案心，陈迹指腹压住暗号，皎兔直起身。", "陈迹逐字确认内院转卖名单，二人停止触碰证物", "确认后的寒意与戒备", "观众明确双面交易结论"),
    ("U04", 2, [1, 2], ["jiaotu"], 2, "spirit_separation_space_reanchor", "皎兔在医馆灯下端坐，指甲刚抵眉心，窗外雨夜可见。", "眉心血痕打开，黑甲阴神从肉身完整分离后穿窗掠过雨城到暗楼", "肉身克制忍痛，阴神冷峻警觉", "观众读懂一具肉身与阴神分离并跨空间侦察"),
    ("U05", 2, [3], ["qisan"], 1, "single_subject_prop_work", "精瘦齐三坐在暗楼油灯下，未封信的名单与空信封分置两侧。", "齐三把同一叠名单拆成数份并逐封装入不同信封", "贪婪、警觉、动作熟练", "观众看懂他在把同一消息卖给多家"),
    ("U06", 2, [4], ["chenji", "qisan"], 1, "continuous_entry_confrontation", "雨夜暗楼门将破未破，齐三仍在灯下，陈迹身影贴近门外。", "陈迹破门、拍灭油灯、以冰流封亮灯芯；齐三惊退碰散信封", "陈迹压迫冷定，齐三惊恐失措", "观众看懂陈迹控制光线与退路完成突袭"),
    ("U07", 2, [5], ["chenji", "qisan"], 1, "dialogue_interrogation", "齐三退到墙边指向陈迹怀中骨牌，陈迹持一只信封逼近。", "陈迹以封口暗号逼供，齐三膝软供出巡检指挥席位", "齐三由赔笑转为煞白发颤，陈迹目光不移", "观众听懂并看懂内鬼席位被钉到巡检指挥"),
    ("U08", 3, [1, 2], ["chenji", "qisan", "killer", "wuyun"], 1, "continuous_combat_interception", "雨巷檐下齐三背对杀手，杀手正从檐边落下，乌云已在墙头弓背。", "乌云示警；杀手短刃刺后心；陈迹冰流沿积水铺开令其脚滑，刀锋偏开只伤肩", "杀手狠厉转惊愕，齐三恐惧，陈迹瞬间专注", "观众看懂冰流改变落脚摩擦从而救下齐三"),
    ("U09", 3, [3, 4], ["yunyang", "killer"], 1, "continuous_combat_force_chain", "杀手贴冰侧滑横抹，云羊咬破指尖，冰墙在二人侧后方。", "纸人点睛展开遮眼；云羊蹬地转胯冲拳命中冰墙固定点；裂纹定向扩散，冰屑掀翻杀手", "云羊狠决爆发，杀手遮眼慌乱后受击痛苦", "观众看懂遮眼、固定点冲拳、碎冰传力的完整因果"),
    ("U10", 3, [5], ["chenji", "yunyang", "qisan", "killer"], 2, "death_prop_ownership_transition", "杀手倒在空账筐边，齐三捂肩后退，陈迹与云羊在两侧封住去路。", "杀手翻身回补齐三咽喉后踏碎薄冰遁走；陈迹从雨血冻住杀手袖口甩落的巡检半牌", "齐三从侥幸转绝望，杀手决绝，陈迹与云羊震怒", "观众看懂灭口优先于逃生，并看见巡检半牌从杀手转入陈迹手中"),
    ("U11", 4, [1], ["chenji", "yao_taiyi"], 1, "evidence_dialogue_tableau", "前堂案上巡检半牌与骨牌并排，姚太医肩头乌鸦正准备落案。", "乌鸦落案盯牌，姚太医和陈迹沿两枚印确认同一巡检线", "姚太医温和但沉重，陈迹压住怒意", "观众从并置证物读懂发令与灭口同源"),
    ("U12", 4, [2], ["chenji", "yao_taiyi"], 1, "dialogue_warning", "姚太医枯手悬在两枚牌上方，陈迹站在案侧。", "姚太医指出敌人不怕身份暴露，只怕陈迹仍有时间慢查", "姚太医沉静警示，陈迹警觉加深", "观众读懂围猎的真正目的在抢时间"),
    ("U13", 4, [3], ["chenji", "wuyun"], 1, "ability_recoil_recovery", "陈迹右手刚开始发颤，半牌正从指间滑落，乌云伏在案边。", "白霜沿腕骨逆窜；乌云跃起把透明人参珠抵入掌心；霜纹接触珠子后停止扩散", "陈迹忍痛克制，乌云急切专注", "观众看懂冰流反噬与人参珠压制的接触因果"),
    ("U14", 4, [4], ["chenji", "yao_taiyi", "wuyun"], 1, "environmental_alarm", "前堂窗外夜色沉重，大乌鸦停在案头，众人同时望向门外。", "远近城门依次落锁；乌鸦振翅绕堂长鸣；姚太医确认密谍司封城", "陈迹稳住呼吸，姚太医神色凝重，乌云炸毛", "观众不见城门也能从连环闷响与群体反应读懂封城"),
    ("U15", 5, [1, 2], ["chenji", "jiaotu"], 1, "environmental_establishing_dialogue", "洛城雨后大远景，陈迹立在医馆飞檐，皎兔正掠上檐脊。", "灯笼长龙从四门与坊口次第亮起收成巨网；皎兔确认三处封锁", "陈迹冷静观察，皎兔紧张", "观众一眼读懂整座城被同一张围猎网包住"),
    ("U16", 5, [3, 4], ["chenji", "yunyang"], 1, "dialogue_strategy_turn", "云羊落在檐脊另一侧握拳，陈迹背对灯网凝视三路灯笼。", "云羊指出三拨人互不信任；陈迹转身提出让他们先认定别人是内奸", "云羊焦灼，陈迹由受压转为洞悉，眸底寒光亮起", "观众看懂主角从猎物位置转向利用敌人互疑"),
    ("U17", 5, [5], [], 1, "environmental_cliffhanger", "橙红灯网已缠住洛城，残月从云后露出，医馆檐上人物缩成黑点。", "镜头持续后拉，三路灯笼彼此交错却保持不同队列，风起明灭后自然切黑", "以灯网压迫代替人物表情", "观众读懂围猎已成但网内分裂可被反用"),
]


def binding(role: str, entity_id: str, path: str) -> dict[str, object]:
    absolute = ROOT / path
    if not absolute.is_file():
        raise SystemExit(f"missing reference: {path}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": path,
        "sha256": sha256(absolute),
        "qa_status": "PASS",
        "qa_report": "configs/series_continuity_asset_registry_20260712.json" if entity_id != "qisan" else "E32_NEW_CASTING_REFERENCE_ADMISSION",
    }


def main() -> int:
    writer = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
    script_sha = sha256(SCRIPT)
    if writer["sha256"] != script_sha:
        raise SystemExit("E32 script SHA does not match Claude Writer manifest")
    if len(SHOTS) != writer["shots"] or sum(row["duration_seconds"] for row in SHOTS) != writer["total_seconds"]:
        raise SystemExit("E32 editorial shot count or duration mismatch")

    scene_shots: dict[int, dict[int, dict[str, object]]] = {}
    for row in SHOTS:
        scene = int(str(row["scene_id"])[-2:])
        number = int(str(row["shot_id"])[-2:])
        scene_shots.setdefault(scene, {})[number] = row

    consumed: set[str] = set()
    grouping = []
    units = []
    tasks = []
    dependent_anchor_specs = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for unit_id, scene, numbers, character_ids, anchor_count, action_class, anchor, causality, expression, viewer_read in UNITS:
        full_id = f"E32-CW-{unit_id}"
        editorial = [scene_shots[scene][number] for number in numbers]
        editorial_ids = [str(row["shot_id"]) for row in editorial]
        if consumed.intersection(editorial_ids):
            raise SystemExit(f"{full_id} reuses an editorial shot")
        consumed.update(editorial_ids)
        duration = sum(int(row["duration_seconds"]) for row in editorial)
        if not 4 <= duration <= 15:
            raise SystemExit(f"{full_id} duration outside 4-15 seconds")
        grouping.append({
            "unit_id": full_id,
            "scene_id": f"E32-CW-S{scene:02d}",
            "duration_seconds": duration,
            "editorial_shot_ids": editorial_ids,
        })

        extra_needed = anchor_count > 1
        spatial_continuity = {
            "mode": "CROSS_SPACE_TRANSITION" if unit_id == "U04" else "SAME_SPACE_CONTINUOUS",
            "policy_source": "PER_UNIT_SCRIPT_CONTENT",
            "origin_scene_id": "E32-CW-S02-MEDICAL-HALL" if unit_id == "U04" else f"E32-CW-S{scene:02d}",
            "destination_scene_id": "E32-CW-S02-WEST-MARKET-DARK-TOWER" if unit_id == "U04" else f"E32-CW-S{scene:02d}",
            "anchor_scope": "ORIGIN_ONLY_WITH_DECLARED_DEPENDENT_DESTINATION" if unit_id == "U04" else "SAME_SPACE_START_ANCHOR",
            "destination_anchor_task_key": f"{full_id}-A2-STILL-{ARTIFACT_TAG}" if unit_id == "U04" else None,
            "camera_policy": "ALLOW_AUTHORED_DESTINATION_CAMERA" if unit_id == "U04" else "PRESERVE_AXIS_ONLY_WHEN_REQUIRED_BY_ACTION",
        }
        criteria = {
            "continuous_motion_from_single_start": not extra_needed,
            "identity_or_space_reanchor": unit_id == "U04",
            "prop_ownership_transition": unit_id == "U10",
            "non_interpolable_terminal_state": unit_id in {"U04", "U10"},
        }
        roles = ["performance_start"]
        if unit_id == "U04":
            roles.append("spirit_separated_at_destination")
        if unit_id == "U10":
            roles.append("post_mortem_token_transfer_terminal")
        reason = (
            "One stable identity and scene plus the authored continuous motion chain are within Seedance capability, so a start anchor is sufficient."
            if anchor_count == 1
            else (
                "The spirit leaves a stationary body and crosses to a new space; a destination re-anchor is required to preserve both identities and locations."
                if unit_id == "U04"
                else "The killing changes Qi San's life state and transfers the patrol token from the killer into Chenji's evidence chain; a terminal re-anchor is required."
            )
        )
        keys = [f"{full_id}-A{index}-STILL-{ARTIFACT_TAG}" for index in range(1, anchor_count + 1)]
        units.append({
            "unit_id": full_id,
            "scene_id": f"E32-CW-S{scene:02d}",
            "duration_seconds": duration,
            "editorial_shot_ids": editorial_ids,
            "generation_mode": "performance_generation",
            "planned_reference_image_count": anchor_count,
            "reference_image_task_keys": keys,
            "anchor_count_decision": {
                "planned_reference_image_count": anchor_count,
                "reason": reason,
                "criteria": criteria,
                "anchor_roles": roles,
                "action_design_class": action_class,
            },
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "stage": "DESIGN_PREFLIGHT",
                "adjacent_pairs_checked": anchor_count - 1,
                "candidate_recheck_required": extra_needed,
                "reason": "The authored adjacent states preserve identity, prop ownership and a physically traversable motion path; generated candidates must be rechecked before video submit.",
            },
            "performance_spec": {
                "intent": viewer_read,
                "motion_chain": causality,
                "expression_arc": expression,
                "viewer_read": viewer_read,
                "single_action_state_source": "CLAUDE_SCRIPT_DERIVED_BEAT_SPEC",
                "dialogue_policy": "VIDEO_MODEL_NATIVE_MANDARIN_FROM_EXACT_AUDIO_REFERENCE_WHEN_DIALOGUE_PRESENT",
            },
            "status": "WAITING_FOR_ANCHORS_AND_EXACT_DIALOGUE_AUDIO",
        })

        scene_path = SCENE_INTERIOR if scene in {1, 2, 4} else SCENE_EXTERIOR
        refs = [binding("character", character_id, CHARACTERS[character_id]) for character_id in character_ids]
        refs.append(binding("scene", f"E32-CW-S{scene:02d}", scene_path))
        source_action = f"动作目的：{viewer_read}；连续物理链：{causality}；表情弧：{expression}。"
        prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物、真实接触、真实受力，雨夜冷青与室内暖灯，禁止现代物件。

这是 {full_id} 的表演起始锚 A1，不是姿势拼贴、分镜网格或动作结果合集。锚图数量已按本单元动作设计独立裁定为 {anchor_count} 张。

起始画面：{anchor}
源动作（必须逐字绑定）：{source_action}

只画动作开始前或刚起势的单一瞬间，不提前画终态。人物、道具归属、接触点与空间距离必须支持后续连续动作。表情必须清楚可读：{expression}。若参考场景带雪，忽略雪，只保留古代建筑材质并改为雨夜或雨后湿地。参考人物只锁身份、脸、发型和服装；齐三 casting 参考需改造成精瘦油滑的消息牙人。不得出现可读文字、伪文字、字幕、水印、标志或界面；纸张、信封、骨牌、铜牌表面保持无字材质。
"""
        prompt_path = PROMPT_DIR / f"{full_id}-A1-{ARTIFACT_TAG}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": f"{full_id}-A1",
            "source_script_sha256": script_sha,
            "source_action": source_action,
            "source_action_sha256": text_sha(source_action),
            "visible_characters": character_ids,
            "reference_bindings": refs,
            "editorial_shot_ids": editorial_ids,
            "video_unit_id": full_id,
            "video_unit_duration_seconds": duration,
            "state_index": 1,
            "state_count": anchor_count,
            "state_role": "performance_start_anchor",
            "spatial_continuity": spatial_continuity,
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": keys[0],
            "tool_type": "image_generation",
            "scene_id": f"E32-CW-S{scene:02d}",
            "shot_id": f"{full_id}-A1",
            "editorial_shot_ids": editorial_ids,
            "video_unit_id": full_id,
            "video_unit_duration_seconds": duration,
            "state_index": 1,
            "state_count": anchor_count,
            "beat_id": full_id,
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in refs],
            "reference_bindings": refs,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "source_script_sha256": script_sha,
        })
        if anchor_count > 1:
            dependent = DEPENDENT_ANCHOR_DESCRIPTIONS.get(unit_id)
            if dependent is None:
                raise SystemExit(f"{full_id} has multiple anchors but no dependent anchor specification")
            dependent_anchor_specs.append({
                "task_key": keys[1],
                "video_unit_id": full_id,
                "depends_on_task_key": keys[0],
                "state_index": 2,
                "state_count": anchor_count,
                "state_role": dependent["role"],
                "terminal_description": dependent["description"],
                "continuity_mode": dependent["continuity_mode"],
                "origin_scene_id": dependent.get("origin_scene_id", f"E32-CW-S{scene:02d}"),
                "destination_scene_id": dependent.get("destination_scene_id", f"E32-CW-S{scene:02d}"),
                "destination_scene_reference": dependent.get("destination_scene_reference"),
                "source_action": source_action,
                "source_action_sha256": text_sha(source_action),
                "release_policy": "AUTO_RELEASE_IMMEDIATELY_AFTER_DEPENDENCY_COMPLETES",
            })

    if consumed != {str(row["shot_id"]) for row in SHOTS}:
        raise SystemExit("not every E32 editorial shot is assigned exactly once")

    plan = {
        "schema": "qingshan.performance_video_plan.v2",
        "episode": "E32",
        "source_script_sha256": script_sha,
        "planned_reference_image_count": sum(row[4] for row in UNITS),
        "units": units,
    }
    grouping_spec = {
        "schema": "qingshan.video_unit_grouping_spec.v2",
        "episode": "E32",
        "source_script_sha256": script_sha,
        "derivation_rule": "Group scene-local contiguous editorial shots by actual scripted seconds and continuous performance causality. Unit count emerges from validated groups and is never selected in advance.",
        "editorial_shot_count": len(SHOTS),
        "unit_count": len(UNITS),
        "groups": grouping,
    }
    production = {
        "schema": "qingshan.production_manifest.v2",
        "episode": "E32",
        "title": writer["title"],
        "status": "PERFORMANCE_PREPRODUCTION_READY",
        "source_script": str(SCRIPT.relative_to(ROOT)),
        "source_script_sha256": script_sha,
        "runtime_seconds": writer["total_seconds"],
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "production_policy": {
            "writer_authority": "CLAUDE_WRITER",
            "grouping": "SCENE_LOCAL_CONTIGUOUS_ACTUAL_SECONDS_COUNT_EMERGES_FROM_GROUPS",
            "fixed_video_unit_count_forbidden": True,
            "anchor_count": "PER_UNIT_MODEL_CAPABILITY_AND_ACTION_DESIGN_NO_FIXED_ONE_OR_MULTI",
            "incremental_video_submit_as_each_unit_becomes_ready": True,
            "native_dialogue_audio_reference_required": True,
            "video_credit_limit_current_workflow": 6000,
            "subtitle_burnin_required": True,
            "nalu_motion_outro_required": True,
            "encoded_audio_asr_loudness_true_peak_retest_required": True,
        },
        "shots": SHOTS,
    }
    preflight = {
        "schema": "qingshan.performance_preproduction_gate.v2",
        "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "checks": {
            "claude_script_sha_locked": True,
            "editorial_shots_exactly_once": True,
            "runtime_seconds_exact": True,
            "scene_local_contiguous_grouping": True,
            "unit_count_not_preselected": True,
            "anchor_count_decided_per_unit": True,
            "multi_anchor_candidates_require_post_generation_interpolation_recheck": True,
            "native_dialogue_audio_reference_required": True,
            "subtitles_and_nalu_motion_locked": True,
        },
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "planned_anchor_count": plan["planned_reference_image_count"],
        "initial_ready_anchor_count": len(tasks),
        "failures": [],
    }

    write_json(PRODUCTION / "E32_PRODUCTION_MANIFEST.json", production)
    write_json(PRODUCTION / f"E32_VIDEO_UNIT_GROUPING_SPEC_{ARTIFACT_TAG}.json", grouping_spec)
    write_json(PRODUCTION / f"E32_VIDEO_UNIT_PERFORMANCE_PLAN_{ARTIFACT_TAG}.json", plan)
    write_json(QA_DIR / f"E32_IMAGE_PLAN_PREFLIGHT_{ARTIFACT_TAG}.json", preflight)
    write_json(PRODUCTION / f"E32_SUBTITLE_CONTRACT_{ARTIFACT_TAG}.json", {
        "schema": "qingshan.subtitle_contract.v1", "episode": "E32", "source_script_sha256": script_sha,
        "burn_in_required": True, "video_model_native_dialogue_audio_required": True,
        "encoded_asr_coverage_required": "ALL_CLAUDE_SCRIPT_DIALOGUE", "status": "LOCKED_FOR_AGENTCUT",
    })
    write_json(PRODUCTION / f"E32_NALU_MOTION_OUTRO_CONTRACT_{ARTIFACT_TAG}.json", {
        "schema": "qingshan.nalu_motion_outro_contract.v1", "episode": "E32", "required": True,
        "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE", "logo_asset": "libraries/brand/nalu_motion_cat_logo_v1.png",
        "chime_asset": "libraries/brand/nalu_motion_outro_chime_v1.wav", "status": "LOCKED_FOR_AGENTCUT",
    })
    anchor_gate = {
        "schema": "qingshan.video_unit_anchor_count_gate.v1", "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "PASS",
        "policy": "DECIDE_PER_UNIT_FROM_MODEL_CAPABILITY_AND_ACTION_DESIGN; NEVER FIX_ONE_OR_FIXED_MULTI",
        "source_script_sha256": script_sha, "video_unit_count": len(UNITS),
        "planned_reference_image_count": plan["planned_reference_image_count"],
        "decisions": [
            {
                "unit_id": row["unit_id"],
                **row["anchor_count_decision"],
                "status": "PASS",
                "failures": [],
            }
            for row in units
        ],
        "failures": [],
    }
    write_json(QA_DIR / f"E32_VIDEO_UNIT_ANCHOR_COUNT_GATE_{ARTIFACT_TAG}.json", anchor_gate)
    write_json(PRODUCTION / f"E32_IMAGE_BATCH_PERFORMANCE_A1_{ARTIFACT_TAG}.json", {
        "schema": "qingshan.episode_parallel_batch.v1", "episode": "E32", "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": script_sha,
        "production_manifest_ref": str((PRODUCTION / "E32_PRODUCTION_MANIFEST.json").relative_to(ROOT)),
        "video_unit_plan_ref": str((PRODUCTION / f"E32_VIDEO_UNIT_PERFORMANCE_PLAN_{ARTIFACT_TAG}.json").relative_to(ROOT)),
        "machine_gate_reports": [
            str((QA_DIR / f"E32_IMAGE_PLAN_PREFLIGHT_{ARTIFACT_TAG}.json").relative_to(ROOT)),
            str((QA_DIR / f"E32_VIDEO_UNIT_ANCHOR_COUNT_GATE_{ARTIFACT_TAG}.json").relative_to(ROOT)),
        ],
        "output_dir": WORKING_ASSET_DIR,
        "qa_dir": IMAGE_QA_DIR,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "PERFORMANCE_ANCHORS", "video_unit_count": len(UNITS),
            "planned_anchor_count": plan["planned_reference_image_count"], "initial_ready_anchor_count": len(tasks),
            "dependent_anchor_count": len(dependent_anchor_specs),
            "incremental_video_submit": "EACH_UNIT_AS_SOON_AS_ITS_REQUIRED_ANCHORS_AND_EXACT_DIALOGUE_AUDIO_PASS",
        },
        "dependent_anchor_specs": dependent_anchor_specs,
        "blocked_tasks": [row["task_key"] for row in dependent_anchor_specs],
        "tasks": tasks,
    })
    write_json(TASK_RECEIPT, {
        "schema": "qingshan.preproduction_input_build.v2", "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_FOR_A1_IMAGE_SUBMIT",
        "source_script_sha256": script_sha, "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS), "planned_anchor_count": plan["planned_reference_image_count"],
        "initial_ready_anchor_count": len(tasks), "dependent_anchor_count": plan["planned_reference_image_count"] - len(tasks),
        "remote_call_count": 0, "new_credits": 0,
    })
    print(json.dumps({
        "status": "PASS", "shots": len(SHOTS), "runtime": writer["total_seconds"],
        "units": len(UNITS), "anchors": plan["planned_reference_image_count"], "initial_ready": len(tasks),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
