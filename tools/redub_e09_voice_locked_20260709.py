#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

import edge_tts


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
VIDEO = BASE / "exports/e09/api_20260709/qingshan_E09_final_titled_subtitled_nalu_20260709.mp4"
RUN_DIR = BASE / "working_assets/e09_api_20260709/videos"
OUT_DIR = BASE / "exports/e09/api_20260709"
WORK_DIR = BASE / "working_assets/e09_voice_locked_20260709"
QA_DIR = BASE / "qa/e09_api_package_20260709/voice_locked"
FINAL = OUT_DIR / "qingshan_E09_final_voice_locked_titled_subtitled_nalu_20260709.mp4"
MIXED_DIALOGUE = WORK_DIR / "e09_voice_locked_dialogue_mix.wav"
MANIFEST = QA_DIR / "e09_voice_locked_manifest_20260709.json"

TITLE_DURATION = 4.0
DIALOGUE = {
    1: ("陈迹：手机没了……我真在这里", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    2: ("陈迹：先活下去", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    3: ("陈迹：你又跟来了？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    4: ("陈迹：喵喵？丧彪？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+4%", "-2Hz"),
    5: ("陈迹：想要这个？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    6: ("陈迹：来，自己拿", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    7: ("陈迹：这珠子在防你？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    8: ("陈迹：师父那边出事了", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+4%", "-2Hz"),
    9: ("佘登科：刘家死人了，密谍司干的", "VOICE-佘登科", "zh-CN-YunxiaNeural", "+10%", "+0Hz"),
    10: ("陈迹：你也没地方去？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    11: ("陈迹：来一个包子", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    12: ("陈迹：给你，吃完别再跟着我", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+4%", "-2Hz"),
    13: ("陈迹：按方抓药，诊脉等师父回来", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+8%", "-2Hz"),
    14: ("陈迹：又输了？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    15: ("陈迹：别动，我给你止血", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    16: ("陈迹：疼也忍着点", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    17: ("陈迹：我在这边，好像也没什么人能信", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+6%", "-2Hz"),
    18: ("陈迹：跟我走吧，聘礼就这颗珠子", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+5%", "-2Hz"),
    19: ("陈迹：你真听得懂？", "VOICE-陈迹-古装", "zh-CN-YunxiNeural", "+2%", "-2Hz"),
    20: ("乌云：哪不正常？", "VOICE-乌云-猫-final-hook-only", "zh-CN-YunyangNeural", "-8%", "-24Hz"),
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def duration(path: Path) -> float:
    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path)], text=True, capture_output=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        raise SystemExit(f"Cannot read duration: {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def clean_text(text: str) -> str:
    return text.split("：", 1)[1] if "：" in text else text


async def make_tts() -> list[dict]:
    tts_dir = WORK_DIR / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    cursor = TITLE_DURATION
    for shot in range(1, 21):
        source = RUN_DIR / f"shot_{shot:02d}" / "result_01.mp4"
        shot_duration = duration(source)
        text, voice_id, voice, rate, pitch = DIALOGUE[shot]
        out = tts_dir / f"shot_{shot:02d}_{voice_id}.mp3"
        communicate = edge_tts.Communicate(text=clean_text(text), voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(out))
        rows.append({
            "shot": f"{shot:02d}",
            "start": round(cursor + 0.32, 2),
            "duration": round(shot_duration, 2),
            "text": text,
            "voice_id": voice_id,
            "edge_voice": voice,
            "rate": rate,
            "pitch": pitch,
            "tts": str(out),
        })
        cursor += shot_duration
    return rows


def mix_dialogue(rows: list[dict], total_duration: float) -> None:
    inputs = [
        str(FFMPEG), "-y",
        "-f", "lavfi", "-t", f"{total_duration:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]
    for row in rows:
        inputs.extend(["-i", row["tts"]])

    filters = ["[0:a]volume=0.0[base]"]
    mix_inputs = ["[base]"]
    for idx, row in enumerate(rows, 1):
        delay = int(row["start"] * 1000)
        filters.append(f"[{idx}:a]adelay={delay}|{delay},volume=2.05[a{idx}]")
        mix_inputs.append(f"[a{idx}]")
    filters.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]")

    run(inputs + [
        "-filter_complex", ";".join(filters),
        "-map", "[aout]",
        "-t", f"{total_duration:.2f}",
        "-ac", "2", "-ar", "48000",
        str(MIXED_DIALOGUE),
    ])


def mux(rows: list[dict], total_duration: float) -> None:
    # Keep the original visuals and subtitles, replace unsafe API speech with unified VOICE-ID dialogue.
    filter_complex = (
        f"[1:a]volume=1.0[dialogue];"
        f"anoisesrc=color=brown:duration={total_duration:.2f}:sample_rate=48000,volume=0.010[amb];"
        "[dialogue][amb]amix=inputs=2:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(VIDEO),
        "-i", str(MIXED_DIALOGUE),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(FINAL),
    ])
    MANIFEST.write_text(json.dumps({
        "source_video": str(VIDEO),
        "final_video": str(FINAL),
        "policy": "Original API dialogue muted/replaced. One stable VOICE-ID voice per recurring speaker.",
        "dialogue_rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(make_tts())
    total_duration = duration(VIDEO)
    mix_dialogue(rows, total_duration)
    mux(rows, total_duration)
    print(FINAL)
    print(MANIFEST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
