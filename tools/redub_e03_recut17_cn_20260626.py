#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import edge_tts


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
FINAL_IN = BASE / "exports/e03_rebuild_20260625/qingshan_E03_final_recut17_titled_subtitled_nalu_20260625.mp4"
SUBS = BASE / "exports/e03_rebuild_20260625/qingshan_E03_recut17_smallsubs_20260625.srt"
OUT_DIR = BASE / "exports/e03_rebuild_20260625/redub_cn_20260626"
TTS_DIR = OUT_DIR / "tts_lines"
FINAL_OUT = OUT_DIR / "qingshan_E03_final_recut17_cn_redub_v2_20260626.mp4"
ASR_OUT = BASE / "qa/e03_recut17_final_20260625/asr_transcript_cn_redub_20260626.txt"

TITLE_OFFSET = 4.20
VOICE_DEFAULT = "zh-CN-YunxiNeural"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(map(str, args)))
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def parse_timecode(value: str) -> float:
    hms, millis = value.split(",")
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(millis) / 1000.0


def parse_srt(path: Path) -> list[tuple[int, float, float, str]]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    cues: list[tuple[int, float, float, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        idx = int(lines[0])
        start_s, end_s = [part.strip() for part in lines[1].split("-->")]
        text = " ".join(lines[2:])
        cues.append((idx, parse_timecode(start_s), parse_timecode(end_s), text))
    return cues


async def synthesize_lines(cues: list[tuple[int, float, float, str]]) -> None:
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    for idx, _start, _end, text in cues:
        out = TTS_DIR / f"line_{idx:03d}.mp3"
        if out.exists() and out.stat().st_size > 1024:
            continue
        communicate = edge_tts.Communicate(text, VOICE_DEFAULT, rate="+18%", volume="+0%")
        await communicate.save(str(out))


def build_mix(cues: list[tuple[int, float, float, str]]) -> None:
    inputs = [str(FINAL_IN)]
    for idx, *_ in cues:
        inputs.extend(["-i", str(TTS_DIR / f"line_{idx:03d}.mp3")])

    filter_parts = [
        "[0:a]volume=0.0[muted]",
        # A low, quiet room/rain bed prevents dead air without turning the whole episode into BGM.
        "anoisesrc=color=pink:sample_rate=48000:duration=177.1,lowpass=f=900,volume=0.060[amb]",
    ]
    mix_inputs = ["[muted]", "[amb]"]
    for input_index, (_idx, start, _end, _text) in enumerate(cues, start=1):
        delay_ms = int((start + TITLE_OFFSET) * 1000)
        filter_parts.append(f"[{input_index}:a]aresample=48000,adelay={delay_ms}|{delay_ms},volume=1.45[v{input_index}]")
        mix_inputs.append(f"[v{input_index}]")
    filter_parts.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=first[aout]")
    filter_complex = ";".join(filter_parts)

    args = [str(FFMPEG), "-y", "-i", str(FINAL_IN)]
    for idx, *_ in cues:
        args.extend(["-i", str(TTS_DIR / f"line_{idx:03d}.mp3")])
    args.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(FINAL_OUT),
    ])
    run(args)


def main() -> None:
    for required in [FFMPEG, FINAL_IN, SUBS]:
        if not required.exists():
            raise FileNotFoundError(required)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cues = parse_srt(SUBS)
    asyncio.run(synthesize_lines(cues))
    build_mix(cues)
    print(f"FINAL={FINAL_OUT}")
    print(f"ASR_TARGET={ASR_OUT}")


if __name__ == "__main__":
    main()
