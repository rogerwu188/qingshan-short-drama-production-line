#!/usr/bin/env python3
"""
Submit and poll Giggle omni-video fallback shots.

This is intentionally small and portable: Python 3 standard library only.
It reads the API key from GIGGLE_API_KEY and never writes it to disk.
"""

import argparse
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request


API_BASE = "https://giggle.pro/api/v1/generation"


STORYBOARD_URLS = {
    "02": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/l273e6jnl3r.jpg",
    "03": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/ci5hlh881tb.jpg",
    "04": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/xtm4lldu438.jpg",
    "05": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/zu5w3cne6i.jpg",
    "07": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/r6gohlcxvzc.jpg",
    "08": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/iftkb5dyyff.jpg",
    "09": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/7gzcn2vz14.jpg",
    "10": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/ujxr6abynq.jpg",
    "11": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/dfn8ibvytme.jpg",
    "12": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/tqnjb6qfhl.jpg",
    "14": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/9a75mm73xw9.jpg",
    "15": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/cmr3suir3a.jpg",
    "16": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/9dmo5nflle8.jpg",
    "17": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/53qabkp6xvo.jpg",
    "18": "https://assets.giggle.pro/public/ai_director/48848a03de8b954d64/p31q496yq7b.jpg",
}


ROOM_CHARACTER_RULES = (
    "人物必须是中国或东亚演员脸，禁止欧美人物，禁止英文对白，禁止英文字幕。"
    "陈迹是18岁清瘦中国少年，黑色短发，苍白疲惫，冷静克制。"
    "王龙是宽脸粗脖、粗壮中年中国男人，穿灰色病号服，半坐在金属病床上。"
    "李青鸟是年轻中国男性，冷静干净，像医院内部知情人。"
    "老人是瘦弱中国老人，病号服，动作慢但眼神清醒。"
)


ACTION_RULES = (
    "生成真人动态视频，不是静态故事板图。镜头内必须有清楚事件动作推进，"
    "每5到8秒出现新信息；不要慢动作，不要长时间停脸，不要心理氛围空镜。"
    "转场上使用声桥、动作接、方向接或道具接，避免硬切。"
)


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_prompt(config, shot):
    anchor = config["scene_anchors"]["ROOM-现代-青山医院-六楼三号病房-A"]
    parts = [
        "写实华语现代医院悬疑短剧，竖屏9:16，720p。",
        "使用参考图片作为本镜头故事板和构图参考，但必须生成真实运动视频和自然口型。",
        anchor,
        "镜头 {shot_id}：{title}".format(**shot),
        "场景锚点：{}".format(shot.get("scene_id", "")),
        "房间锚点：{}".format(shot.get("room_id", "")),
        "区域锚点：{}".format(shot.get("zone_id", "")),
        "机位锚点：{}".format(shot.get("angle_id", "")),
        "出场角色：{}".format("、".join(shot.get("characters", []))),
        "关键道具：{}".format("、".join(shot.get("props", []))),
        ROOM_CHARACTER_RULES,
        ACTION_RULES,
        "保持病床、床头柜、淡蓝半开床帘、床头监护仪、左后方病房门、灰蓝墙面、白被单、金属床栏的位置连续。",
        "环境声：医院空调低鸣、远处雨声、床栏或纸张轻响，音量自然，不铺满煽情BGM。",
    ]
    dialogue = shot.get("dialogue") or ""
    if dialogue:
        parts.append(
            "普通话对白必须完整说完，口型同步：{}。本镜头只说这一句，说完停顿半秒。".format(dialogue)
        )
    else:
        parts.append("本镜头无人物对白，只保留环境声和动作音效。")
    parts.append("最终画面必须是中国现代医院短剧质感，不能出现白画面、黑屏、纯字幕卡、欧美演员或英文声音。")
    return "\n".join(p for p in parts if p)


def request_json(url, api_key, method="GET", payload=None):
    data = None
    headers = {
        # Giggle docs currently say "Bearer <key>", but the live API accepts
        # the raw key value in x-auth. Bearer returns "api key not found".
        "x-auth": api_key,
        "accept": "application/json, text/plain, */*",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "origin": "https://giggle.pro",
        "referer": "https://giggle.pro/",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError("HTTP {}: {}".format(e.code, body))


def download(url, path):
    req = urllib.request.Request(url, headers={"user-agent": "qingshan-e04-repair/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        path.write_bytes(resp.read())


def submit_shot(config, shot, api_key, model):
    payload = {
        "model": model,
        "prompt": make_prompt(config, shot),
        "duration": int(shot.get("duration", 7)),
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generating_count": 1,
        "images": [{"url": STORYBOARD_URLS[shot["shot_id"]]}],
        "audios": [],
    }
    result = request_json(API_BASE + "/omni-video", api_key, method="POST", payload=payload)
    return payload, result


def poll_task(task_id, api_key, interval, max_wait):
    deadline = time.time() + max_wait
    last = None
    while time.time() < deadline:
        query = urllib.parse.urlencode({"task_id": task_id})
        result = request_json(API_BASE + "/task/query?" + query, api_key)
        last = result
        data = result.get("data") or {}
        status = data.get("status") or result.get("status")
        if status in ("completed", "succeeded", "success", "failed", "error"):
            return result
        time.sleep(interval)
    return last or {"error": "timeout"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/Users/rogerwu/qingshan_short_drama/configs/e04_v5_continuity_config.json")
    parser.add_argument("--out", default="/Users/rogerwu/qingshan_short_drama/working_assets/e04_v5_api_fallback")
    parser.add_argument("--shots", required=True, help="comma-separated shot ids, e.g. 02,03,04")
    parser.add_argument("--model", default="seedance-2.0-pro")
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--poll-existing", help="JSON manifest to resume polling")
    parser.add_argument("--poll-interval", type=int, default=20)
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()

    api_key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GIGGLE_API_KEY is required")

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config)
    by_id = {shot["shot_id"]: shot for shot in config["shots"]}

    manifest_path = out_dir / "manifest.json"
    manifest = {"model": args.model, "shots": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    shot_ids = [s.strip().zfill(2) for s in args.shots.split(",") if s.strip()]
    for shot_id in shot_ids:
        if shot_id not in by_id:
            raise SystemExit("unknown shot {}".format(shot_id))
        if shot_id not in STORYBOARD_URLS:
            raise SystemExit("missing storyboard URL for shot {}".format(shot_id))
        entry = manifest["shots"].setdefault(shot_id, {})
        if not entry.get("task_id"):
            payload, submit_result = submit_shot(config, by_id[shot_id], api_key, args.model)
            data = submit_result.get("data") or {}
            task_id = data.get("task_id") or submit_result.get("task_id")
            if not task_id:
                entry.update({"submit_result": submit_result, "error": "missing task_id"})
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                print("{} submit failed: {}".format(shot_id, json.dumps(submit_result, ensure_ascii=False)))
                continue
            entry.update({
                "task_id": task_id,
                "payload": payload,
                "submit_result": submit_result,
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            print("{} submitted {}".format(shot_id, task_id))
        if args.submit_only:
            continue

        task_id = entry["task_id"]
        poll_result = poll_task(task_id, api_key, args.poll_interval, args.max_wait)
        entry["poll_result"] = poll_result
        data = poll_result.get("data") or {}
        status = data.get("status") or poll_result.get("status")
        entry["status"] = status
        urls = data.get("urls") or poll_result.get("urls") or []
        if status in ("completed", "succeeded", "success") and urls:
            clip_path = out_dir / "e04_shot{}_{}_{}.mp4".format(shot_id, args.model.replace("-", ""), task_id[-8:])
            download(urls[0], clip_path)
            entry["downloaded_file"] = str(clip_path)
            entry["result_url"] = urls[0]
            print("{} downloaded {}".format(shot_id, clip_path))
        else:
            print("{} status {} err {}".format(shot_id, status, data.get("err_msg") or poll_result.get("err_msg")))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("manifest: {}".format(manifest_path))


if __name__ == "__main__":
    main()
