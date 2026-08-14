#!/usr/bin/env python3
"""Compile the locked E27 professional script into six concurrent keyframe tasks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("codex_docs/E27剧本_专业版_LOCKED_20260720.md")
DATE = "20260720"

CHENJI = "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
YAO = "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
JIAOTU = "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg"
BAILI = "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg"

SCENES = [
    {
        "scene_id": "E27-PRO-S01-TAIPING-CLINIC-DAY",
        "scene_no": "1-1",
        "location": "太平医馆内堂",
        "time_of_day": "clear daytime",
        "weather": "dry protected interior",
        "palette": "neutral daylight, dark timber, restrained cold-blue ice",
        "characters": ["陈迹", "姚太医", "密谍司兵"],
        "refs": [CHENJI, YAO],
        "action": "十余名铁甲兵冲入医馆，假搜查令拍在诊案上；陈迹双指挟住刀刃，寒气封冻官印，假令崩碎。",
        "camera": "low wide confrontation moving into a tight three-quarter view of Chenji catching the blade",
        "forbidden": ["night", "moon", "moonlight", "rain", "snow", "readable text"],
    },
    {
        "scene_id": "E27-PRO-S02-CLINIC-ALLEY-NIGHT",
        "scene_no": "1-2",
        "location": "医馆外侧巷",
        "time_of_day": "night",
        "weather": "dry clear alley",
        "palette": "cold moonlight with deep neutral shadows",
        "characters": ["陈迹", "白鲤", "皎兔"],
        "refs": [CHENJI, BAILI, JIAOTU],
        "action": "皎兔贴墙闭目，半透明淡蓝阴神自头顶升起追踪送令兵；白鲤迎月辨纸面暗纹，陈迹换上夜行衣。",
        "camera": "side-on medium-wide layered composition with the spirit rising above Jiaotu and Chenji entering shadow",
        "forbidden": ["rain", "snow", "modern street", "readable text", "extra duplicate people"],
    },
    {
        "scene_id": "E27-PRO-S03-ROYAL-ARCHIVE-NIGHT",
        "scene_no": "1-3",
        "location": "靖王府档房",
        "time_of_day": "night interior",
        "weather": "dry protected interior",
        "palette": "narrow moon shaft, one weak candle, charcoal timber",
        "characters": ["陈迹", "皎兔", "守卫"],
        "refs": [CHENJI, JIAOTU],
        "action": "陈迹伏在卷宗架阴影里，皎兔阴神穿过铜锁铁柜；两名守卫转角出现，陈迹凝冰点穴夺匙。",
        "camera": "deep corridor perspective, low tracking angle, crisp action silhouette between tall archive racks",
        "forbidden": ["outdoor palace panorama", "rain", "snow indoors", "readable text", "floating subtitles"],
    },
    {
        "scene_id": "E27-PRO-S04-ARCHIVE-INNER-CORNER-NIGHT",
        "scene_no": "1-4",
        "location": "王府档房内角",
        "time_of_day": "night interior",
        "weather": "dry protected interior",
        "palette": "torch glow leaking under door, blue-white frost tracing pressure marks",
        "characters": ["陈迹", "皎兔", "乌云", "追兵"],
        "refs": [CHENJI, JIAOTU],
        "action": "走廊甲胄逼近，黑猫跃下按住叠纸；陈迹翻身避开扫堂腿，冰霜令纸张压痕显出幽蓝命气。",
        "camera": "dynamic low diagonal action frame with the black cat in foreground and pursuit light cutting through the door",
        "forbidden": ["full readable names", "subtitles", "watermark", "rain", "snow indoors", "duplicate cat"],
    },
    {
        "scene_id": "E27-PRO-S05-SCRIPTORIUM-CORRIDOR-NIGHT",
        "scene_no": "1-5",
        "location": "文书房长廊",
        "time_of_day": "night interior",
        "weather": "dry protected interior",
        "palette": "warm torch streaks against cold spectral blue",
        "characters": ["陈迹", "皎兔", "守卫"],
        "refs": [CHENJI, JIAOTU],
        "action": "守卫破门抢走拓片，陈迹贴身肘击碎甲、锁喉砸墙夺回；皎兔阴神显出文书官背后的死亡残影。",
        "camera": "handheld-feel close combat with a clean foreground elbow strike and spectral tableau opening behind",
        "forbidden": ["static posing", "readable paper text", "subtitles", "modern armor", "rain", "snow"],
    },
    {
        "scene_id": "E27-PRO-S06-SCRIPTORIUM-WINDOW-CLIMAX",
        "scene_no": "1-6",
        "location": "文书房窗外与窗内",
        "time_of_day": "night",
        "weather": "dry",
        "palette": "bright interior lamp, dark exterior, blood-red ink frozen in blue ice",
        "characters": ["陈迹", "皎兔", "执笔人", "护卫"],
        "refs": [CHENJI, JIAOTU],
        "action": "陈迹飞身侧踢撞碎雕花木窗，木屑飞溅；冰流冻结空中朱红墨滴，护卫刀光从黑暗涌来。",
        "camera": "heroic exterior-to-interior impact frame, true airborne action, shattered wood and frozen red droplets readable as motion",
        "forbidden": ["extended freeze frame", "looped debris", "readable name", "subtitles", "watermark", "rain", "snow"],
    },
]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(root: Path = ROOT) -> dict:
    script_path = root / SCRIPT
    script_text = script_path.read_text(encoding="utf-8")
    script_sha = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    prompt_dir = root / f"workflow/prompts/e27_pro_script_keyframes_v1_{DATE}"
    output_dir = f"working_assets/e27_pro_script_keyframes_v1_{DATE}/candidates"
    qa_dir = f"qa/e27_pro_script_keyframes_v1_{DATE}"

    scene_state_rows = []
    tasks = []
    for index, scene in enumerate(SCENES, start=1):
        prompt = (
            f"《青山》E27专业锁定稿场景 {scene['scene_no']}。剧本权威地点：{scene['location']}；"
            f"时段：{scene['time_of_day']}；天气：{scene['weather']}。"
            f"人物必须沿用参考图身份：{'、'.join(scene['characters'])}。"
            f"关键动作：{scene['action']} 镜头：{scene['camera']}。"
            "写实古装悬疑动作剧，美剧式高压节奏，电影级真实光影，人物脸和服装稳定，动作瞬间清晰可读，9:16竖屏构图。"
            f"NEGATIVE_PROMPT: {', '.join(scene['forbidden'])}, subtitles, captions, title, logo, watermark, "
            "readable Chinese characters, duplicate identities, fused arms, extra people."
        )
        prompt_path = prompt_dir / f"S{index:02d}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        task_key = f"E27-PRO-S{index:02d}-KEYFRAME-V1"
        tasks.append(
            {
                "task_key": task_key,
                "tool_type": "image_generation",
                "scene_id": scene["scene_id"],
                "scene_no": scene["scene_no"],
                "visual_zone": f"PRO_SCENE_{index:02d}_KEYFRAME",
                "prompt_file": str(prompt_path.relative_to(root)),
                "reference_images": [str((root / ref).resolve()) for ref in scene["refs"]],
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_FOR_PARALLEL_SUBMIT",
            }
        )
        scene_state_rows.append(
            {
                "scene_id": scene["scene_id"],
                "scene_no": scene["scene_no"],
                "location": scene["location"],
                "time_of_day": scene["time_of_day"],
                "weather": scene["weather"],
                "palette": scene["palette"],
                "event_summary": scene["action"],
                "forbidden_prompt_tokens": scene["forbidden"],
            }
        )

    scene_state_path = root / f"configs/e27_pro_script_scene_state_v1_{DATE}.json"
    config_path = root / f"configs/E27_pro_script_keyframe_image_batch_v1_{DATE}.json"
    scene_state = {
        "schema": "qingshan.scene_state.v1",
        "episode": "E27",
        "source_script": str(SCRIPT),
        "source_script_sha256": script_sha,
        "decision_ref": "ROGER-CHOICE-2-20260720",
        "status": "PRO_SCRIPT_LOCKED",
        "scene_state": scene_state_rows,
    }
    config = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E27",
        "source_script": str(SCRIPT),
        "source_script_sha256": script_sha,
        "decision_ref": "ROGER-CHOICE-2-20260720",
        "scene_contract_ref": str(scene_state_path.relative_to(root)),
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": 6,
        "max_retries": 0,
        "output_dir": output_dir,
        "qa_dir": qa_dir,
        "base_batch_note": "Professional-script baseline. Submit all six scene keyframes concurrently; preserve every pass and retry only failed scenes.",
        "tasks": tasks,
    }
    write_json(scene_state_path, scene_state)
    write_json(config_path, config)
    return {
        "status": "PASS",
        "script_sha256": script_sha,
        "scene_count": len(SCENES),
        "scene_state": str(scene_state_path),
        "config": str(config_path),
        "prompt_dir": str(prompt_dir),
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
