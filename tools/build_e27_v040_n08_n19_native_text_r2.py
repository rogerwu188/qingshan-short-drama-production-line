#!/usr/bin/env python3
"""Build a two-shot failed-only reroll that prevents generated native text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_visualfix_r1_failed_only/video_batch_visualfix_r1_failed_only.json"
FULL_BATCH = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_v1/video_batch_v1.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_native_text_r2_failed_only"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PROMPTS = {
    "E27-N08": """这是《青山》E27 E27-N08 的 Seedance 2.0 Pro 多模态分镜视频。
【唯一输入锚点】[[image_1]]是人物身份、人数、构图、服装、地点、晴朗夜间光线与空间轴线锚点。陈迹站在右前景，皎兔女性本体与白鲤留在巷道后景。不得增加、删除、替换人物。
【规格】6秒，竖屏9:16，720p，写实国漫古装武侠电影质感；禁止外部BGM、字幕、水印、Logo、可读文字与伪文字。
【远景定场关系】本场大远景定场已由同场 establishing 镜头完成；本镜保持其中确立的巷道纵深、轴线与人物尺度，不擅自重建地理。
【唯一剧情事件】陈迹只完成一次“系紧黑色夜行衣左腕口”。E26名册残页已经收进腰带，整镜保持藏好；只允许露出一个没有文字、没有符号、没有线条的窄小纸角，绝不取出、递出、展开或让纸面朝向镜头。
镜头1【0.0-4.2秒，中近景，横向平稳跟拍】：从输入图既定姿态连续起动，陈迹右手捏住左腕黑色绑带，拉紧并绕腕一次；镜头只跟随手腕横向移动，纸页始终藏在腰带，纸面不进入画面中心。{陈迹以@音频1锁定音色自然说一次“原证在档房。今夜取。”}<黑色布料摩擦、绑带收紧、巷道微弱风声>
镜头2【4.2-6.0秒，手腕近景，稳定停住】：陈迹把绑带末端压进袖口，左腕口完成收紧；构图中心只有黑色袖口、双手和布结，腰带纸角位于画面边缘且完全失焦。{无新增对白}<布结压紧、短促呼吸>
【纸张硬门】任何可见纸面只能是无墨、无印、无纹、无边框的纯旧纸背面；模型不得补写汉字、拉丁字母、数字、印章、账格或书法笔画。宁可让纸张完全被衣料遮住，也不得生成任何文字纹理。
【动作硬门】不接纸、不递纸、不看纸、不抽纸；只系腕口。皎兔与白鲤不得走近、开口或改变既定位置。
【色彩与光影】冷蓝巷道环境光与暖色檐灯动机光保持输入图方向，黑色衣料纹理与肤色清晰，黑位有层次；干燥晴夜，无月亮奇观、无雾。
【力量与环境介质】绑带力量只通过衣料绷紧、腕口褶皱和袖口摩擦反馈；巷道墙面与灯火保持自然稳定，不用尘雾或光效替代动作。
【连续性与声音】人物面容、服装、屏幕方向、场景地理和陈迹音色严格锁定；对白只继承@音频1的音色、年龄、共鸣、语速与气息，不照搬旧台词或背景声。非说话角色闭口。
【绝对禁止】纸张正面朝镜头、纸张出腰带、递纸动作、可读文字、伪文字、字幕、印章、Logo、分身、换脸、肢体增生、穿模、慢动作、循环动作、无动机推近、外部BGM。
""",
    "E27-N19": """这是《青山》E27 E27-N19 的 Seedance 2.0 Pro 多模态分镜视频。
【唯一输入锚点】[[image_1]]是陈迹、密谍司文书残影、构图、服装、王府档房长廊、夜间室内光线、拓片与纯空白时辰签的唯一锚点。不得增加、删除、替换人物或道具。
【规格】6秒，竖屏9:16，720p，写实国漫古装武侠电影质感；禁止外部BGM、字幕、水印、Logo、可读文字与伪文字。
【远景定场关系】本场大远景定场已由同场 establishing 镜头完成；本镜继承长廊木柱、卷架、门洞纵深与既定轴线。
【唯一剧情事件】陈迹接住下落的无字拓片，将一张纯空白、无墨、无印、无纹的旧纸时辰签贴到文书残影胸前。证据含义只由贴放位置和对白表达，绝不通过纸面文字表达。
镜头1【0.0-4.2秒，中近景，轻微下降跟随动作】：保持输入图人物关系，陈迹左手接住从上方落下的空白拓片，右手持输入图同一张纯空白窄纸签向残影胸前移动；纸签正反两面始终纯空白。{无对白}<薄纸落入掌心、衣袖摩擦、长廊木构轻响>
镜头2【4.2-6.0秒，胸口近景，下降后稳定】：陈迹把纯空白纸签平贴在残影胸前并停稳，镜头看清纸张材质与贴放关系，但纸面没有任何墨迹、符号、刻度、边框或伪文字；陈迹视线由纸签移向残影。{陈迹以@音频1锁定音色自然说一次“最早死的，是密谍司自己的文书。”}<纸面轻触布料、残影低频空气感>
【空白纸面硬门】输入图里的时辰签本来就是纯空白纸片，视频每一帧都必须保持完全空白。不得自动补字，不得生成“时间标签”、汉字、拉丁字母、数字、印章、账格、符号或类似文字的笔画。纸面宁可略微失焦，也不得出现墨迹。
【动作硬门】只完成“接住拓片→贴空白签→停稳”这一条因果；不得把纸签变成吊牌，不得悬挂在颈部，不得新增人物、第二张纸签或额外手臂。
【色彩与光影】长廊暖色灯笼形成纵深，残影保留冷色透明边缘，肤色与旧纸材质自然；无月亮奇观、无雾气遮挡剧情。
【力量与环境介质】贴放力量只通过纸面触衣、指尖停顿与残影表面极轻空气反馈呈现；木廊灯火稳定，不用碎片、尘雾或光效替代剧情。
【连续性与声音】陈迹面容、文书残影身份、服装、道具数量、屏幕方向和陈迹音色严格锁定；对白只继承@音频1的音色、年龄、共鸣、语速与气息，不照搬旧台词或背景声。非说话角色闭口。
【绝对禁止】纸面文字、伪文字、吊牌文字、字幕、水印、Logo、换脸、分身、双胞胎、肢体增生、穿模、慢动作、循环动作、无动机推近、外部BGM。
""",
}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    full_batch = json.loads(FULL_BATCH.read_text(encoding="utf-8"))
    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for shot_id in ("E27-N08", "E27-N19"):
        source = next(row for row in base["tasks"] if row["shot_id"] == shot_id)
        prompt_path = prompt_dir / f"{shot_id}.txt"
        prompt_path.write_text(PROMPTS[shot_id], encoding="utf-8")
        task = dict(source)
        task.update(
            {
                "task_key": f"{shot_id}-WRITER-AGENT-V040-VIDEO-NATIVE-TEXT-R2",
                "prompt_file": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha256(prompt_path),
                "retry_reason": "FINAL_CUT_OCR_CONFIRMED_GENERATED_NATIVE_TEXT",
                "repair_checks": ["no_text_or_pseudotext", "preserve_exact_story_action"],
                "status": "READY_FAILED_ONLY_CONCURRENT_SUBMIT",
            }
        )
        tasks.append(task)
    manifest = dict(base)
    preserved = []
    for task in full_batch["tasks"]:
        prompt_path = ROOT / task["prompt_file"]
        preserved.append(
            {
                "task_key": task["task_key"],
                "scene_id": task["scene_id"],
                "prompt_file": task["prompt_file"],
                "prompt_sha256": sha256(prompt_path),
            }
        )
    manifest.update(
        {
            "status": "READY_NATIVE_TEXT_R2_FAILED_ONLY_SUBMIT",
            "concurrency": 2,
            "max_retries": 0,
            "output_dir": "working_assets/e27_writer_agent_v040_video_native_text_r2_20260720/candidates",
            "qa_dir": "qa/e27_writer_agent_v040_video_native_text_r2_20260720",
            "base_batch_note": "Second and final targeted reroll for the two exact shots that failed full-cut OCR. Preserve all other 22 sources.",
            "preserved_prompt_professionalism_evidence": preserved,
            "tasks": tasks,
        }
    )
    DEST.mkdir(parents=True, exist_ok=True)
    manifest_path = DEST / "video_batch_native_text_r2_failed_only.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "manifest": str(manifest_path.relative_to(ROOT)),
                "manifest_sha256": sha256(manifest_path),
                "prompts": [
                    {
                        "shot_id": shot_id,
                        "path": str((prompt_dir / f"{shot_id}.txt").relative_to(ROOT)),
                        "sha256": sha256(prompt_dir / f"{shot_id}.txt"),
                    }
                    for shot_id in ("E27-N08", "E27-N19")
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
