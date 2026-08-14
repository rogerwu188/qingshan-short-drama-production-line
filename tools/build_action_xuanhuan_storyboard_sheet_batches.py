#!/usr/bin/env python3
"""Build E26/E27 episode and fight storyboard-sheet image batches."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260719"


EPISODE_COMPOSITIONS = {
    "E26": [
        ("B01", "大全景", "医馆外低机位缓推，火把队从画面两侧合围，陈迹在门心封门", "WIDE_LOW_FRONT"),
        ("B02", "中近景", "火箱侧面横移，陈迹越过燃烧箱笼抢出闭合布包册", "MEDIUM_SIDE_TRACK"),
        ("B03", "高位全景", "俯看前后门同时被封、油线包围医馆，众人边打边退", "OVERHEAD_WIDE_RETREAT"),
        ("B04", "贴地近景", "黑猫乌云从药架下穿出叼回残页，陈迹在后景擒腕", "GROUND_CLOSE_CAT"),
        ("B05", "俯拍特写", "冰线从残页沿药粉轨迹延伸到侧柜，人物只留手与脚", "TOPDOWN_MACRO_ICE_TRAIL"),
        ("B06", "群像中远景", "账柜堵门、众人组成传递链，冰线与烛火交汇后指向门外", "GROUP_WIDE_TABLEAU"),
    ],
    "E27": [
        ("B01", "中景过肩", "从送令兵肩后看陈迹翻桌夺令，姚太医压住药账", "OTS_MEDIUM_WARRANT"),
        ("B02", "大全景", "干燥夜巷与王府高墙同框，皎兔半透明阴神穿墙追踪", "WIDE_WALL_SPIRIT"),
        ("B03", "长焦走廊中景", "卷宗架形成纵深，陈迹与守卫在纸浪中争钥", "TELEPHOTO_AISLE_FIGHT"),
        ("B04", "微距俯拍", "乌云爪按无字叠纸，霜纹从纸背扩散成抽象轨迹", "MACRO_TOPDOWN_FROST"),
        ("B05", "低机位长廊全景", "陈迹追击夺回拓片，烛影与纸尘中命灯熄灭", "LOW_WIDE_CORRIDOR"),
        ("B06", "窗外大全景", "陈迹破窗闯入文书房，纸浪和干燥夜风同时炸开", "EXTERIOR_WIDE_WINDOW_BREAK"),
    ],
}


FIGHT_SEQUENCES = {
    "E26": {
        "beat_id": "B01",
        "mode": "B_WUXIA_XUANHUAN",
        "title": "冰流裂火·医馆守门战",
        "shots": [
            (1, "SETUP", "大全景", "医馆外低机位快速推近", "无旗号清洗者破窗举火突入，陈迹推药柜封门后转身迎敌", "<木窗炸裂><火把呼啸>", "火星与药粉被冲击卷入室内", "WIDE_LOW_BREACH"),
            (2, "SETUP", "极近特写", "火把尖与陈迹双指间冰流的对切特写", "火焰压向陈迹面门，冰流在指间凝成一道白色寒芒", "<火焰爆燃><冰晶轻鸣>", "火舌被寒芒劈成左右两股", "EXTREME_CLOSE_FIRE_ICE"),
            (3, "IMPACT", "中景侧拍", "横移跟拍", "陈迹侧身扣住持火者手腕，借药柜反蹬发力将其甩向同伴", "<扣腕闷响><踏地爆裂>", "地上药水被踏成半人高冰浪", "MEDIUM_SIDE_WRIST_THROW"),
            (4, "IMPACT", "特写转全景", "先贴冰浪碎裂再急拉到全屋", "敌人刀气撞上冰浪，如玻璃般碎成冷光，药架间多人错身定格", "<刀刃嗤响><冰浪哗啦碎裂>", "悬停火星与冰片凝滞一瞬", "CLOSE_TO_WIDE_QI_SHATTER"),
            (5, "IMPACT", "俯拍全景", "顶视旋转半圈", "陈迹沿结霜脚印穿过围攻，冰流扫倒火把，敌人阵形被切开", "<衣袂破风><火把落地>", "霜线像阵图沿脚印爆亮但不形成文字", "OVERHEAD_WIDE_ICE_PATH"),
            (6, "TABLEAU", "大全景", "固定收束", "陈迹立在被劈开的火光中央，乌云妖影贴地指向藏在柜后的内应，清洗者倒退", "<风火渐平><猫低吼>", "悬停冰片恢复坠落，蓝雾指向侧柜形成钩子", "FULL_WIDE_FINAL_TABLEAU"),
        ],
    },
    "E27": {
        "beat_id": "B06",
        "mode": "B_WUXIA_XUANHUAN",
        "title": "朱墨成冰·破窗救名",
        "shots": [
            (1, "SETUP", "窗外大全景", "干燥夜风中长焦缓推", "新名册被送入文书房，陈迹从档房屋脊跃向亮窗", "<夜风><瓦片疾响>", "纸尘被身法切出一条空隙", "EXTERIOR_WIDE_ROOF_APPROACH"),
            (2, "SETUP", "极近特写", "朱笔笔尖与冰霜的对切特写", "执笔人即将落下活人名字，冰霜先一步爬上朱笔尖", "<笔尖刮纸><冰晶细响>", "一滴朱墨悬停在半空", "EXTREME_CLOSE_BRUSH_FROST"),
            (3, "IMPACT", "中景低机位", "破窗冲入并横移跟拍", "陈迹撞碎窗格，侧身格开护卫短刀，掌风掀起整桌素面纸页", "<窗格爆裂><刀刃交鸣>", "纸页化作白色纸浪遮断追兵", "LOW_MEDIUM_WINDOW_CLASH"),
            (4, "IMPACT", "特写转全景", "先贴刀锋冰芒再急拉到文书房全貌", "冰流白芒一闪，护卫刀气如玻璃碎裂，陈迹与执笔人错身而立", "<剑气嗤响><碎裂哗啦>", "悬停纸页和烛尘凝滞一瞬", "CLOSE_TO_WIDE_QI_BREAK"),
            (5, "IMPACT", "俯拍全景", "顶视快速下压", "陈迹反手打飞朱笔，朱墨在空中冻结成黑冰碎片，护卫被纸浪逼退", "<朱笔脱手><黑冰炸裂>", "黑冰碎片沿命气方向飞散，不形成文字", "OVERHEAD_WIDE_INK_FREEZE"),
            (6, "TABLEAU", "室外大全景", "从干燥夜风外固定收束", "破窗内陈迹按住素面新册，执笔人后退，皎兔阴神在墙后显出下一目标命气", "<夜风渐平><远处命铃一响>", "纸浪与烛尘恢复流动，命气冷光指向城外形成钩子", "EXTERIOR_FULL_FINAL_TABLEAU"),
        ],
    },
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def build_plan(episode: str, sheet: dict) -> dict:
    beats = {row["beat_id"]: row for row in sheet["structure"]}
    cursor = 0
    rows = []
    for index, (beat_id, shot_size, camera, signature) in enumerate(EPISODE_COMPOSITIONS[episode], start=1):
        beat = beats[beat_id]
        duration = int(beat.get("target_seconds") or 0)
        rows.append({
            "shot_no": index,
            "beat_id": beat_id,
            "timecode": f"{cursor:03d}-{cursor + duration:03d}s",
            "visual": f"16:9 写实画面示意：{shot_size}，{camera}",
            "camera": camera,
            "dialogue_sfx": f"对白仅作声音参考；<动作音效>；剧情：{beat.get('new_information')}",
            "technique": f"{shot_size}；原生速度；动作/视线匹配切；禁止同款构图",
            "composition_signature": signature,
            "action_spine": beat.get("action_spine"),
            "xuanhuan_element": beat.get("xuanhuan_element"),
            "power_visualization": beat.get("power_visualization"),
        })
        cursor += duration
    fight = FIGHT_SEQUENCES[episode]
    fight_rows = [
        {
            "shot_no": shot_no,
            "phase": phase,
            "shot_size": shot_size,
            "camera": camera,
            "action": action,
            "sfx": sfx,
            "power_visualization": power,
            "composition_signature": signature,
        }
        for shot_no, phase, shot_size, camera, action, sfx, power, signature in fight["shots"]
    ]
    return {
        "schema": "qingshan.storyboard_sheet_plan.v1",
        "episode": episode,
        "title": sheet.get("title"),
        "directive_refs": ["CL2X-388", "CL2X-389"],
        "status": "PLAN_READY_IMAGE_AND_AI_REVIEW_REQUIRED",
        "episode_rows": rows,
        "fight_sequence": {**{key: value for key, value in fight.items() if key != "shots"}, "shots": fight_rows},
        "video_generation_allowed": False,
        "rollback": "Keep all existing V4 keyframes; regenerate only a failed episode or fight storyboard sheet.",
    }


def table_prompt(episode: str, plan: dict, kind: str) -> str:
    if kind == "episode_sheet":
        rows = plan["episode_rows"]
        title = f"《青山》{episode} 整集分镜表"
        lead = "每行对应一个剧情 beat，六格画面必须刻意使用不同景别、机位、方向和内容。"
    else:
        rows = plan["fight_sequence"]["shots"]
        title = f"《青山》{episode} {plan['fight_sequence']['title']} 打斗分镜表"
        lead = "武侠玄幻 B 模式，凝滞→一击→定格；必须体现极近特写到大全景的大幅景别拉开。"
    row_lines = []
    for row in rows:
        if kind == "episode_sheet":
            row_lines.append(
                f"{row['shot_no']} | {row['visual']} | {row['timecode']} | {row['camera']}；{row['action_spine']}；{row['xuanhuan_element']} | {row['dialogue_sfx']} | {row['technique']}"
            )
        else:
            row_lines.append(
                f"{row['shot_no']} | 16:9 写实画面示意：{row['shot_size']}，{row['action']} | 镜{row['shot_no']} | {row['camera']}；{row['action']} | {row['sfx']} | {row['shot_size']}；{row['phase']}；{row['power_visualization']}"
            )
    return "\n".join([
        f"生成一张专业影视 shot list 分镜表图片：{title}。Seedream 4.5 同级高精度，16:9 横幅，2K。",
        "白色背景、浅灰表头、灰色细表格线、六行，排版规整，无底部信息栏、无水印、无 Logo。",
        "六列从左到右固定为：序号 | 画面示意 | 时间码 | 画面内容·机位·运动 | 对白·音效 | 拍摄手法·景别·镜头运动。",
        "画面示意小图全部为 16:9 写实古装玄幻短剧，同一角色身份、同一场景连续性、自然电影光影。",
        lead,
        "不要把六格画面画成同款正面人物，不要六格相同景别，不要重复构图，不要额外人物，不要现代物件。",
        "表格文字只用于分镜规划；画面示意小图内不得出现字幕、文字、水印或 Logo。",
        "逐行内容：",
        *row_lines,
    ])


def build_episode(episode: str) -> tuple[Path, Path]:
    lower = episode.lower()
    sheet_path = ROOT / f"configs/{lower}_dialogue_beat_sheet_v4_action_xuanhuan_{DATE}.json"
    receipt_path = ROOT / f"workflow/tasks/{episode}_ACTION_XUANHUAN_V4_SIX_IMAGES_R1_RECEIPT_{DATE}.json"
    sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    references = [str(Path(task["output_path"])) for task in receipt["tasks"] if task.get("status") == "image_pass"]
    if len(references) != 6:
        raise SystemExit(f"{episode} requires six completed V4 keyframes, got {len(references)}")
    plan = build_plan(episode, sheet)
    plan_path = ROOT / f"configs/{episode}_storyboard_sheet_plan_v1_{DATE}.json"
    write_json(plan_path, plan)
    prompt_dir = ROOT / f"workflow/prompts/{lower}_storyboard_sheet_v1_{DATE}"
    tasks = []
    scene_id = {
        "E26": "E26-S01-TAIPING-CLINIC-SIEGE",
        "E27": "E27-S02-ROYAL-ARCHIVE-NIGHT",
    }[episode]
    location_token = {
        "E26": "Taiping clinic",
        "E27": "sealed royal archive room",
    }[episode]
    for kind in ("episode_sheet", "fight_sheet"):
        prompt_path = prompt_dir / f"{episode}_{kind.upper()}.txt"
        write_text(prompt_path, f"Scene authority: {location_token}.\n" + table_prompt(episode, plan, kind))
        task_refs = references if kind == "episode_sheet" else [references[int(plan["fight_sequence"]["beat_id"][1:]) - 1]]
        tasks.append({
            "task_key": f"{episode}-{kind.upper()}-V1",
            "tool_type": "image_generation",
            "sheet_kind": kind,
            "scene_id": scene_id,
            "visual_zone": f"STORYBOARD_{kind.upper()}",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "reference_images": task_refs,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "16:9",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "metadata": {
                "sheet_kind": kind,
                "plan": str(plan_path.relative_to(ROOT)),
                "fight_mode": plan["fight_sequence"]["mode"],
                "directive_refs": ["CL2X-388", "CL2X-389"],
            },
        })
    config_path = ROOT / f"configs/{episode}_storyboard_sheet_image_batch_v1_{DATE}.json"
    write_json(config_path, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "scene_contract_ref": f"configs/{lower}_scene_state_v1_script_locked_{DATE}.json",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": 2,
        "max_retries": 0,
        "output_dir": f"working_assets/{lower}_storyboard_sheet_v1_{DATE}/candidates",
        "qa_dir": f"qa/{lower}_storyboard_sheet_v1_{DATE}",
        "base_batch_note": "Generate the episode sheet and fight sheet concurrently; preserve a passed sheet and retry only a failed sheet.",
        "storyboard_sheet_plan": str(plan_path.relative_to(ROOT)),
        "tasks": tasks,
    })
    return plan_path, config_path


def main() -> int:
    outputs = []
    for episode in ("E26", "E27"):
        plan, config = build_episode(episode)
        outputs.extend([str(plan), str(config)])
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
