#!/usr/bin/env python3
"""Build E30 preproduction inputs from the locked Claude Writer script."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E30剧本_ClaudeWriter_v1.md"
WRITER_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E30_manifest.json"
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shot(
    shot_id: str,
    scene_id: str,
    duration: int,
    scale: str,
    camera: str,
    action: str,
    sound: str,
    characters: list[str],
) -> dict[str, object]:
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "duration_seconds": duration,
        "scale": scale,
        "camera": camera,
        "action": action,
        "sound": sound,
        "visible_characters": characters,
        "production_action": "GENERATE_NEW",
    }


def build_subtitle_contract(script_sha: str, scene_ids: dict[str, str]) -> dict[str, object]:
    dialogue = []
    current_scene = None
    scene_pattern = re.compile(r"^\*\*(3-[1-5])．")
    dialogue_pattern = re.compile(r"^([^△〔>\-#][^：]{0,20})：(?:（[^）]*）)?(.*)$")
    for raw_line in SCRIPT.read_text(encoding="utf-8").splitlines():
        scene_match = scene_pattern.match(raw_line.strip())
        if scene_match:
            current_scene = scene_ids[scene_match.group(1)]
            continue
        match = dialogue_pattern.match(raw_line.strip())
        if not match or current_scene is None:
            continue
        speaker = match.group(1).strip()
        spoken_text = match.group(2).strip()
        if speaker == "人物" or not spoken_text:
            continue
        dialogue.append({
            "dia_id": f"E30-DIA-{len(dialogue) + 1:03d}",
            "scene_id": current_scene,
            "speaker": speaker,
            "spoken_text": spoken_text,
            "subtitle_segments": [spoken_text],
        })
    return {
        "schema": "qingshan.subtitle_contract.v1",
        "episode": "E30",
        "language": "zh-CN",
        "source_script": str(SCRIPT.relative_to(ROOT)),
        "source_script_sha256": script_sha,
        "status": "LOCKED_FOR_AGENTCUT",
        "burn_in_required": True,
        "pixel_verification_required": True,
        "safe_area_required": True,
        "dialogue_line_count": len(dialogue),
        "dialogue": dialogue,
        "final_evidence_contract": {
            "blocker_id": "SUBTITLE_BURNIN",
            "required_reports": ["subtitle_timeline_coverage", "burned_subtitle_pixel_verification"],
            "pass_condition": f"{len(dialogue)}/{len(dialogue)} dialogue lines covered and every burned event pixel-verified on the final render",
        },
    }


def main() -> int:
    writer = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
    script_sha = sha256(SCRIPT)
    if writer["sha256"] != script_sha:
        raise SystemExit("E30 Claude Writer script SHA does not match its manifest")

    scene_ids = {
        "3-1": "E30-CW-S01-MEDICAL-BACK-HALL-ATTACK",
        "3-2": "E30-CW-S02-MEDICAL-BACK-HALL-FALSE-LIST",
        "3-3": "E30-CW-S03-LUOCHENG-LONG-STREET-AMBUSH",
        "3-4": "E30-CW-S04-MEDICAL-BACK-HALL-WATERMARK",
        "3-5": "E30-CW-S05-MEDICAL-FRONT-HALL-HOOK",
    }

    shots = [
        shot("E30-CW-S01-SH01", scene_ids["3-1"], 8, "close handheld", "cold-open blade reveal from behind Chenji", "刺客短刃贴住陈迹咽喉，冷开场三秒内明确名单索命与死亡压力。", "刀锋出鞘、药戥轻响", ["chenji", "assassin"]),
        shot("E30-CW-S01-SH02", scene_ids["3-1"], 6, "macro xuanhuan", "locked macro on frost crossing the blade", "陈迹指尖冷雾爬满短刃，刀锋冻结在喉前，无法再进一寸。", "金铁结霜细裂", ["chenji"]),
        shot("E30-CW-S01-SH03", scene_ids["3-1"], 8, "medium action", "real-time lateral move through wrist lock and takedown", "陈迹扣腕错步把刺客按倒药柜前，乌云跃下压住刺客后颈。", "身体撞柜、猫爪落地", ["chenji", "assassin", "wuyun"]),
        shot("E30-CW-S01-SH04", scene_ids["3-1"], 10, "close-up", "measured push from the death list to Chenji's decision", "陈迹把写着自己名字的名单铺在灯下，不撕名单，决定反握落笔即死的规则。", "纸页铺开、烛火轻响", ["chenji"]),

        shot("E30-CW-S02-SH01", scene_ids["3-2"], 9, "top-down wide", "fixed overhead ritual composition", "陈迹在空白名册上写入已死者与假身份；纸面文字区保持干净，后期用真字体叠加。", "笔锋刮纸、更漏一滴", ["chenji"]),
        shot("E30-CW-S02-SH02", scene_ids["3-2"], 7, "medium close", "slow push from blank final slot to Jiaotu's realization", "陈迹把活诱饵周乙留在最后一格，纸面名字由后期真字体叠加；皎兔看懂诱敌逻辑。", "笔尖停顿、灯芯轻爆", ["chenji", "jiaotu"]),
        shot("E30-CW-S02-SH03", scene_ids["3-2"], 8, "tight xuanhuan close-up", "locked on shaking hand, spreading frost and falling brush", "陈迹右手骤颤，薄霜反向爬上握笔指节，笔落纸面晕开墨团。", "笔落、呼吸一滞", ["chenji"]),
        shot("E30-CW-S02-SH04", scene_ids["3-2"], 6, "macro insert", "short arc from Wuyun to the warm pearl touching Chenji's hand", "乌云跃上案头吐出温润人参珠，抵住陈迹手背压制冰流。", "猫跃案头、珠子轻触", ["chenji", "wuyun"]),
        shot("E30-CW-S02-SH05", scene_ids["3-2"], 6, "medium action", "follow Wuyun through the window into night", "乌云叼起卷好的假名单跃出窗外，皎兔留在案边注视墨团。", "纸卷轻响、衣窗破风", ["wuyun", "jiaotu"]),

        shot("E30-CW-S03-SH01", scene_ids["3-3"], 6, "ultra-wide establishing", "static grand view down the snowy lantern street", "风雪长街层檐覆雪，灯笼连成暖红河，街尾小药铺孤灯未熄。", "风雪、远处更鼓", []),
        shot("E30-CW-S03-SH02", scene_ids["3-3"], 6, "medium tracking action", "real-time lateral pursuit toward the pharmacy door", "黑影贴墙扑向药铺，云羊自檐上俯落抢在门前截住。", "踏雪疾奔、衣袂破风", ["yunyang", "killer"]),
        shot("E30-CW-S03-SH03", scene_ids["3-3"], 2, "tight action", "two-second blade beat at shoulder height", "杀手反手一刀劈向云羊肩窝，刀风裂开飞雪。", "刀风裂雪", ["yunyang", "killer"]),
        shot("E30-CW-S03-SH04", scene_ids["3-3"], 2, "close action", "two-second paper-figure counter", "云羊侧身点睛，剪影纸人扑上去缠住杀手持刀腕。", "纸帛猎猎", ["yunyang", "killer"]),
        shot("E30-CW-S03-SH05", scene_ids["3-3"], 2, "medium close action", "two-second break and body entry", "杀手挣断纸人欺身近战，云羊沉肩蓄出冲拳。", "纸帛撕裂、踏雪", ["yunyang", "killer"]),
        shot("E30-CW-S03-SH06", scene_ids["3-3"], 2, "wide impact action", "two-second punch impact through lantern rack", "云羊冲拳把杀手轰进灯架，火星四炸，雪地映出猩红。", "撞击闷响、灯笼爆裂", ["yunyang", "killer"]),
        shot("E30-CW-S03-SH07", scene_ids["3-3"], 14, "medium-to-close action", "real-time chase, slam and interrogation finish", "杀手翻身欲遁，云羊踏雪追上揪住后领掼回雪里，以膝抵背逼问名册来源。", "身体砸雪、急促喘息", ["yunyang", "killer"]),

        shot("E30-CW-S04-SH01", scene_ids["3-4"], 8, "medium fixed", "triangular composition around the bone token", "云羊押杀手回堂并拍下骨牌，皎兔翻看背面编号，确认能进内档房翻名册。", "骨牌拍案、衣袂落定", ["yunyang", "jiaotu", "chenji"]),
        shot("E30-CW-S04-SH02", scene_ids["3-4"], 8, "medium close", "slow push from token to Chenji's conclusion", "陈迹指出对方翻过内部名册才来抹周乙，内鬼范围收窄到能碰册子的自己人。", "压低对话、药堂底噪", ["chenji", "jiaotu"]),
        shot("E30-CW-S04-SH03", scene_ids["3-4"], 9, "macro xuanhuan", "locked macro on frost revealing a hidden wave mark", "冰霜漫过假名单末行，沈砚名字区域留白供真字体叠加，笔画凹痕浮出景朝水波暗纹。", "冰面漫纸、轻微冰裂", ["chenji"]),
        shot("E30-CW-S04-SH04", scene_ids["3-4"], 9, "three-person close", "rack focus across Yunyang, Jiaotu and Chenji", "云羊与皎兔确认假名撞上真人；陈迹承认名字是瞎编的，但落笔力道属于真人。", "倒吸气后满堂死寂", ["yunyang", "jiaotu", "chenji"]),

        shot("E30-CW-S05-SH01", scene_ids["3-5"], 7, "medium handheld", "slight handheld drift through medicine haze", "姚太医立在药柜前，梁上大乌鸦睁眼，王府方向喧哗与火光由远逼近。", "远处喧哗、器物碎裂", ["yao_taiyi", "chenji"]),
        shot("E30-CW-S05-SH02", scene_ids["3-5"], 6, "two-shot medium", "measured cross coverage between Yao and Chenji", "姚太医说明假名单半个时辰传遍三府；陈迹判断名单里有各方都怕的名字。", "压低对话、王府远响", ["yao_taiyi", "chenji"]),
        shot("E30-CW-S05-SH03", scene_ids["3-5"], 6, "close-up", "slow push from damp paper to Chenji's face", "陈迹低头看掌心名单末行，纸面留白供后期真字体叠加沈砚，霜纹已化成湿痕。", "纸页轻响、远处火声", ["chenji"]),
        shot("E30-CW-S05-SH04", scene_ids["3-5"], 5, "tight close-up", "hold on Chenji's eyes as the new question lands", "陈迹抬眼，意识到这笔可能不是自己落下，而是某种力量借他的手写下。", "声音压低、环境骤静", ["chenji"]),
        shot("E30-CW-S05-SH05", scene_ids["3-5"], 4, "eave insert", "one-second crow beat held into Yao's reaction", "梁上大乌鸦突然振翅尖鸣，姚太医凝神抬头。", "尖利鸦鸣", ["yao_taiyi"]),
        shot("E30-CW-S05-SH06", scene_ids["3-5"], 8, "black-screen audio hook", "hard cut to black after distant firelight", "王府喧哗轰然拔高后戛然而止，结束在谁借陈迹之手落笔的新问题上。", "喧哗拔高后骤停", []),
    ]

    if len(shots) != writer["shots"]:
        raise SystemExit(f"editorial shot count mismatch: {len(shots)} != {writer['shots']}")
    if sum(int(row["duration_seconds"]) for row in shots) != writer["total_seconds"]:
        raise SystemExit("editorial duration sum mismatch")

    action_shots = [
        "E30-CW-S01-SH01", "E30-CW-S01-SH02", "E30-CW-S01-SH03",
        "E30-CW-S02-SH03", "E30-CW-S02-SH05",
        "E30-CW-S03-SH02", "E30-CW-S03-SH03", "E30-CW-S03-SH04",
        "E30-CW-S03-SH05", "E30-CW-S03-SH06", "E30-CW-S03-SH07",
        "E30-CW-S04-SH03", "E30-CW-S05-SH05",
    ]
    core_shots = [row["shot_id"] for row in shots if row["shot_id"] not in {"E30-CW-S05-SH06"}]
    production = {
        "schema": "qingshan.production_manifest.v1",
        "episode": "E30",
        "title": writer["title"],
        "version": "claude-writer-v1-compiled-20260722",
        "status": "SCRIPT_LOCKED_PREPRODUCTION_ACTIVE",
        "source": {
            "script": str(SCRIPT.relative_to(ROOT)),
            "script_sha256": script_sha,
            "writer_manifest": str(WRITER_MANIFEST.relative_to(ROOT)),
            "directive": "ROGER_USE_CLAUDE_GENERATED_SCRIPT_20260722",
        },
        "runtime_seconds": writer["total_seconds"],
        "scene_count": writer["scenes"],
        "shot_count": writer["shots"],
        "production_policy": {
            "single_episode_debug_mode": True,
            "images_batch_concurrent": True,
            "videos_batch_concurrent": True,
            "failed_items_only_retry": True,
            "reuse_before_regenerate": True,
            "subtitle_burnin_required": True,
            "nalu_motion_outro_required": True,
            "video_unit_grouping_required_before_image_submit": True,
            "video_unit_grouping_method": "SCENE_LOCAL_CONTIGUOUS_NARRATIVE_GROUPING_FIRST",
            "video_unit_count_formula_forbidden": True,
            "full_state_batch_required_before_first_image_submit": True,
            "final_lock_requires_evidence": ["SUBTITLE_BURNIN", "NALU_MOTION_OUTRO"],
            "multi_state_reference_policy": {
                "minimum_states_per_video_unit": 2,
                "minimum_states_per_action_unit": 3,
                "one_still_per_video_unit_forbidden": True,
                "action_shot_ids": action_shots,
            },
            "image_validation": {
                "score_scale": 100,
                "core_min_score": 80,
                "non_core_min_score": 60,
                "hard_fact_gates": ["media_integrity", "canonical_identity_continuity", "scene_authority", "story_action_clarity", "no_text_or_pseudotext", "native_anatomy"],
                "core_shot_ids": core_shots,
            },
            "video_credit_limit_current_workflow": 6000,
            "video_generation_guard_required": True,
            "no_old_final_overwrite": True,
        },
        "shots": shots,
    }

    scene_state = {
        "schema": "qingshan.scene_authority_state.v1",
        "episode": "E30",
        "scene_state": [
            {"scene_id": scene_ids["3-1"], "location": "太平医馆后堂药柜与案头", "time_of_day": "night", "weather": "interior_clear", "event_summary": "刺客贴喉、冰流冻刀、陈迹决定反用名单规则", "palette": "药堂墨黑、烛火暖橙、冰霜幽蓝", "forbidden_prompt_tokens": ["daylight", "snow street", "readable Chinese text"]},
            {"scene_id": scene_ids["3-2"], "location": "太平医馆后堂灯下书案", "time_of_day": "night", "weather": "interior_clear", "event_summary": "陈迹编写假名单、布置周乙诱饵、乌云送单", "palette": "宣纸米白、墨黑、冰霜幽蓝", "forbidden_prompt_tokens": ["daylight", "outdoor snow", "readable Chinese text"]},
            {"scene_id": scene_ids["3-3"], "location": "洛城雪夜长街药铺前", "time_of_day": "night", "weather": "snow", "event_summary": "云羊当街截杀并逼问名册来源", "palette": "青蓝雪夜、灯笼暖红、火星猩红", "forbidden_prompt_tokens": ["daylight", "modern street", "readable shop sign"]},
            {"scene_id": scene_ids["3-4"], "location": "太平医馆后堂案前", "time_of_day": "night", "weather": "interior_clear", "event_summary": "骨牌锁定内部权限、冰霜显出沈砚与景朝水波暗纹", "palette": "暖灯、宣纸米白、冰霜幽蓝", "forbidden_prompt_tokens": ["daylight", "outdoor snow", "readable Chinese text"]},
            {"scene_id": scene_ids["3-5"], "location": "太平医馆前堂药柜与梁上乌鸦", "time_of_day": "night", "weather": "interior_clear", "event_summary": "假名单震动王府、陈迹追问谁借他的手落笔", "palette": "药堂暖褐、烛影摇红、窗外王府远橙", "forbidden_prompt_tokens": ["daylight", "snow street", "readable Chinese text"]},
        ],
    }

    masked_ref = "working_assets/e28_writer_agent_stills_v1/candidates/E28_E28-S03-SH03-WRITER-AGENT-STILL-V1_2c6a96bb-b4ea-4469-b9d5-195959d45f2e.png"
    hall_ref = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
    street_ref = "working_assets/e29_claude_writer_v1_stills_20260722/candidates/E29_E29-CW-S01-SH01-STILL-V1_4f6f7833-2bff-40e4-9a98-69b4d4054bc7.png"
    character_paths = {
        "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
        "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
        "yunyang": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
        "wuyun": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
        "yao_taiyi": "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg",
        "assassin": masked_ref,
        "killer": masked_ref,
    }
    for value in [*character_paths.values(), hall_ref, street_ref]:
        if not (ROOT / value).is_file():
            raise SystemExit(f"required reference missing: {value}")
    asset_map = {
        "schema": "qingshan.asset_map.v1",
        "episode": "E30",
        "source_script_sha256": script_sha,
        "characters": {
            key: {"entity_id": key, "path": value, "qa_status": "PASS", "qa_report": "configs/series_continuity_asset_registry_20260712.json"}
            for key, value in character_paths.items()
        },
        "scene_references": {
            scene_ids["3-1"]: hall_ref,
            scene_ids["3-2"]: hall_ref,
            scene_ids["3-3"]: street_ref,
            scene_ids["3-4"]: hall_ref,
            scene_ids["3-5"]: hall_ref,
        },
    }

    groups = [
        ("U01", ["S01-SH01", "S01-SH02"], True, "刺客贴喉与冰流冻刀形成同一冷开场攻防。"),
        ("U02", ["S01-SH03"], True, "陈迹反制刺客，乌云压住后颈。"),
        ("U03", ["S01-SH04"], False, "陈迹决定反握纸上杀人的规则。"),
        ("U04", ["S02-SH01"], False, "陈迹开始编写真假混杂的名单。"),
        ("U05", ["S02-SH02", "S02-SH03"], True, "周乙诱饵逻辑落地并紧接冰流反噬。"),
        ("U06", ["S02-SH04", "S02-SH05"], True, "乌云以人参珠压制冰流并把假名单送出。"),
        ("U07", ["S03-SH01", "S03-SH02"], True, "雪夜长街定场后黑影扑药铺、云羊截门。"),
        ("U08", ["S03-SH03", "S03-SH04", "S03-SH05", "S03-SH06"], True, "刀劈、纸人缠腕、近战与冲拳撞灯连续短打。"),
        ("U09", ["S03-SH07"], True, "云羊追上掼雪并逼问名册来源。"),
        ("U10", ["S04-SH01"], False, "骨牌拍案并确认内档房权限。"),
        ("U11", ["S04-SH02"], False, "陈迹把内鬼范围收窄到能碰名册的自己人。"),
        ("U12", ["S04-SH03"], True, "冰霜显出沈砚凹痕与景朝水波暗纹。"),
        ("U13", ["S04-SH04"], False, "三人确认假名撞上真人。"),
        ("U14", ["S05-SH01", "S05-SH02"], False, "姚太医说明假名单已震动三府，陈迹判断各方都怕名单。"),
        ("U15", ["S05-SH03", "S05-SH04"], False, "陈迹从沈砚湿痕追问谁借他的手落笔。"),
        ("U16", ["S05-SH05", "S05-SH06"], True, "乌鸦振翅示警并以王府喧哗骤停收尾。"),
    ]
    grouping_spec = {
        "schema": "qingshan.video_unit_grouping_spec.v1",
        "episode": "E30",
        "source_script_sha256": script_sha,
        "derivation_rule": "Group source shots only by scene boundary, contiguous narrative action and exact editorial seconds. Unit count is the length of the validated semantic groups and is never chosen in advance.",
        "duration_policy_seconds": {"minimum": 4, "maximum": 15, "authority": "CLAUDE_SCRIPT_EDITORIAL_TIMING"},
        "preferred_duration_seconds": {"minimum": 8, "maximum": 15, "exceptions": "Keep an atomic short beat unpadded when merging would exceed 15 seconds or break a narrative boundary."},
        "groups": [
            {
                "unit_id": f"E30-CW-{unit}",
                "editorial_shot_ids": [f"E30-CW-{suffix}" for suffix in suffixes],
                "action_unit": action,
                "narrative_beat": beat,
            }
            for unit, suffixes, action, beat in groups
        ],
    }

    outro = {
        "schema": "qingshan.nalu_motion_outro_contract.v1",
        "episode": "E30",
        "status": "LOCKED_FOR_AGENTCUT",
        "required": True,
        "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE",
        "logo_asset": {"path": "libraries/brand/nalu_motion_cat_logo_v1.png", "sha256": "92b23693f6bb8847359e4f95249d2e07a541c7563d50b7e41220ece223bd101c"},
        "chime_asset": {"path": "libraries/brand/nalu_motion_outro_chime_v1.wav", "sha256": "3d712c8c1fd018ce444180dedc54d343347673c30334e3679a85ba12b975afec"},
        "final_evidence_contract": {
            "blocker_id": "NALU_MOTION_OUTRO",
            "required_reports": ["outro_asset_sha_verification", "final_tail_frame_and_audio_verification"],
            "pass_condition": "logo and chime exact SHAs appear after all narrative dialogue and subtitles in the final render",
        },
    }

    write_json(PRODUCTION / "E30_PRODUCTION_MANIFEST.json", production)
    write_json(PRODUCTION / "E30_VIDEO_UNIT_GROUPING_SPEC_V1.json", grouping_spec)
    write_json(PRODUCTION / "E30_SCENE_AUTHORITY_STATE_V1.json", scene_state)
    write_json(ROOT / "configs/e30_claude_writer_v1_asset_map_20260722.json", asset_map)
    write_json(ROOT / "configs/e30_claude_writer_v1_scene_state_20260722.json", scene_state)
    write_json(PRODUCTION / "E30_SUBTITLE_CONTRACT_V1.json", build_subtitle_contract(script_sha, scene_ids))
    write_json(PRODUCTION / "E30_NALU_MOTION_OUTRO_CONTRACT_V1.json", outro)
    write_json(
        ROOT / "workflow/tasks/E30_CLAUDE_SCRIPT_PREPRODUCTION_INPUT_BUILD_20260722.json",
        {
            "schema": "qingshan.preproduction_input_build.v1",
            "episode": "E30",
            "recorded_at": datetime.now().astimezone().isoformat(),
            "status": "INPUTS_BUILT_NOT_YET_SUBMITTED",
            "script_authority": str(SCRIPT.relative_to(ROOT)),
            "script_sha256": script_sha,
            "editorial_shot_count": len(shots),
            "runtime_seconds": sum(int(row["duration_seconds"]) for row in shots),
            "semantic_group_count_declared_by_spec": len(groups),
            "state_count_policy": "2_PER_ORDINARY_EDITORIAL_SHOT_3_PER_ACTION_EDITORIAL_SHOT",
            "subtitle_contract": str((PRODUCTION / "E30_SUBTITLE_CONTRACT_V1.json").relative_to(ROOT)),
            "outro_contract": str((PRODUCTION / "E30_NALU_MOTION_OUTRO_CONTRACT_V1.json").relative_to(ROOT)),
            "remote_call_count": 0,
            "generation_call_count": 0,
            "new_credits": 0,
        },
    )
    print(json.dumps({"status": "PASS", "shots": len(shots), "runtime": writer["total_seconds"], "groups_in_spec": len(groups)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
