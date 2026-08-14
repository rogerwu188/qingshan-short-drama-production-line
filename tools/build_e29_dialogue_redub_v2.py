#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import edge_tts


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = BASE / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
PROJECT = BASE / "configs/e29_agentcut_v1_subtitled_outro_20260722.json"
CONTRACT = BASE / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722/E29_SUBTITLE_CONTRACT_V1.json"
SOURCE = BASE / "exports/e29/final_v1_subtitled_nalu_motion_20260722/QINGSHAN_E29_FINAL_V1.mp4"
WORK = BASE / "working_assets/e29_dialogue_v2_20260722"
OUT_DIR = BASE / "exports/e29/final_v2_dialogue_subtitled_nalu_motion_20260722"
QA_DIR = BASE / "qa/e29_final_v2_dialogue_20260722"
FINAL = OUT_DIR / "QINGSHAN_E29_FINAL_V2.mp4"
DIALOGUE_MIX = WORK / "E29_DIALOGUE_ONLY_V2.wav"
MANIFEST = QA_DIR / "E29_DIALOGUE_AUDIO_MANIFEST_V2.json"
QA_REPORT = QA_DIR / "E29_DIALOGUE_RELEASE_GATE_V2.json"

VOICE = {
    "陈迹": ("zh-CN-YunxiNeural", "+10%", "-4Hz"),
    "云羊": ("zh-CN-YunxiaNeural", "+13%", "+2Hz"),
    "皎兔": ("zh-CN-XiaoyiNeural", "+12%", "+4Hz"),
    "乌云": ("zh-CN-YunyangNeural", "-6%", "-18Hz"),
}

PRONUNCIATION_TEXT = {
    "E29-DIA-001": "备用的道路……他熟得像自家后院。",
    "E29-DIA-012": "教习是刀。攥刀的手，在景朝。",
}


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def probe(path: Path) -> dict:
    proc = run([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(path),
    ], capture=True)
    return json.loads(proc.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atempo_chain(factor: float) -> str:
    factors: list[float] = []
    while factor > 2.0:
        factors.append(2.0)
        factor /= 2.0
    while factor < 0.5:
        factors.append(0.5)
        factor /= 0.5
    factors.append(factor)
    return ",".join(f"atempo={value:.6f}" for value in factors)


def load_rows() -> list[dict]:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract_by_id = {row["dia_id"]: row for row in contract["dialogue"]}
    clips = project["timeline"]["subtitleTracks"][0]["clips"]
    if len(clips) != 15 or set(contract_by_id) != {clip["dialogue_id"] for clip in clips}:
        raise SystemExit("E29 dialogue contract/timeline is not exactly 15/15")
    rows = []
    for clip in clips:
        source = contract_by_id[clip["dialogue_id"]]
        if source["spoken_text"] != clip["text"]:
            raise SystemExit(f"Dialogue text mismatch: {clip['dialogue_id']}")
        voice, rate, pitch = VOICE[source["speaker"]]
        rows.append({
            "dialogue_id": source["dia_id"],
            "speaker": source["speaker"],
            "text": source["spoken_text"],
            "tts_text": PRONUNCIATION_TEXT.get(source["dia_id"], source["spoken_text"]),
            "start": float(clip["start"]),
            "window_duration": float(clip["duration"]),
            "audio_window_duration": 2.80 if source["dia_id"] == "E29-DIA-012" else float(clip["duration"]),
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
        })
    return rows


async def generate(rows: list[dict]) -> None:
    raw_dir = WORK / "raw"
    fit_dir = WORK / "fitted"
    raw_dir.mkdir(parents=True, exist_ok=True)
    fit_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(*[
        edge_tts.Communicate(
            text=row["tts_text"], voice=row["voice"], rate=row["rate"], pitch=row["pitch"]
        ).save(str(raw_dir / f"{row['dialogue_id']}.mp3"))
        for row in rows
    ])
    for row in rows:
        raw = raw_dir / f"{row['dialogue_id']}.mp3"
        fitted = fit_dir / f"{row['dialogue_id']}.wav"
        raw_duration = duration(raw)
        target = max(0.8, row["audio_window_duration"] - 0.16)
        factor = max(1.0, raw_duration / target)
        audio_filter = (
            f"{atempo_chain(factor)},"
            "highpass=f=75,lowpass=f=12500,"
            "loudnorm=I=-18:LRA=7:TP=-2"
        )
        run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw), "-af", audio_filter,
            "-ac", "2", "-ar", "48000", str(fitted),
        ])
        fitted_duration = duration(fitted)
        if fitted_duration > row["audio_window_duration"] + 0.04:
            raise SystemExit(f"Dialogue exceeds window: {row['dialogue_id']}")
        row.update({
            "raw_file": str(raw),
            "raw_sha256": sha256(raw),
            "raw_duration": round(raw_duration, 6),
            "fitted_file": str(fitted),
            "fitted_sha256": sha256(fitted),
            "fitted_duration": round(fitted_duration, 6),
            "speed_factor": round(factor, 6),
            "post_subtitle_tail": round(max(0.0, fitted_duration - row["window_duration"]), 6),
        })


def mix_dialogue(rows: list[dict], total_duration: float) -> None:
    args = [
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-t", f"{total_duration:.6f}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]
    for row in rows:
        args.extend(["-i", row["fitted_file"]])
    filters = ["[0:a]volume=0[base]"]
    inputs = ["[base]"]
    for index, row in enumerate(rows, 1):
        delay = round(row["start"] * 1000)
        filters.append(f"[{index}:a]adelay={delay}|{delay}[d{index}]")
        inputs.append(f"[d{index}]")
    filters.append(
        "".join(inputs)
        + f"amix=inputs={len(inputs)}:duration=first:dropout_transition=0,alimiter=limit=0.95[out]"
    )
    run(args + [
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-t", f"{total_duration:.6f}", "-ac", "2", "-ar", "48000", str(DIALOGUE_MIX),
    ])


def mux(total_duration: float) -> None:
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(SOURCE), "-i", str(DIALOGUE_MIX),
        "-filter_complex",
        "[0:a]volume=0.45[amb];[1:a]volume=1.30[vox];"
        "[amb][vox]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "loudnorm=I=-18:LRA=11:TP=-1.5,alimiter=limit=0.95[aout]",
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total_duration:.6f}", "-movflags", "+faststart", str(FINAL),
    ])


def verify(rows: list[dict], total_duration: float) -> dict:
    final_probe = probe(FINAL)
    audio_streams = [s for s in final_probe["streams"] if s["codec_type"] == "audio"]
    failures = []
    if len(rows) != 15:
        failures.append("dialogue_count_not_15")
    if not audio_streams:
        failures.append("final_audio_stream_missing")
    if abs(float(final_probe["format"]["duration"]) - total_duration) > 0.2:
        failures.append("duration_changed")
    for row in rows:
        if not Path(row["fitted_file"]).exists() or row["fitted_duration"] <= 0.1:
            failures.append(f"missing_audio:{row['dialogue_id']}")
        if row["fitted_duration"] > row["audio_window_duration"] + 0.04:
            failures.append(f"window_overrun:{row['dialogue_id']}")
    return {
        "schema": "qingshan.dialogue_audio_release_gate.v1",
        "episode": "E29",
        "version": "V2",
        "status": "PASS" if not failures else "FAIL",
        "dialogue_audio_claimed": True,
        "expected_dialogue_count": 15,
        "verified_dialogue_count": len(rows),
        "role_bound_count": sum(1 for row in rows if row["speaker"] in VOICE),
        "final_video": str(FINAL),
        "final_sha256": sha256(FINAL),
        "final_probe": final_probe,
        "retained_video_sha256": sha256(SOURCE),
        "video_stream_policy": "COPY_FROM_V1_RETAINS_BURNED_SUBTITLES_AND_NALU_MOTION",
        "audio_policy": "V1_NATIVE_AMBIENCE_DUCKED_PLUS_15_ROLE_BOUND_DIALOGUE_LINES",
        "failures": failures,
    }


def main() -> int:
    for directory in (WORK, OUT_DIR, QA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    asyncio.run(generate(rows))
    total_duration = duration(SOURCE)
    mix_dialogue(rows, total_duration)
    mux(total_duration)
    report = verify(rows, total_duration)
    manifest = {
        "schema": "qingshan.dialogue_audio_manifest.v2",
        "episode": "E29",
        "version": "V2",
        "source_contract": str(CONTRACT),
        "source_contract_sha256": sha256(CONTRACT),
        "dialogue_line_count": len(rows),
        "remote_generation_calls": 0,
        "remote_generation_credits": 0,
        "rows": rows,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QA_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        raise SystemExit(json.dumps(report["failures"], ensure_ascii=False))
    print(json.dumps({
        "final": str(FINAL),
        "sha256": report["final_sha256"],
        "duration": float(report["final_probe"]["format"]["duration"]),
        "dialogue_lines": len(rows),
        "manifest": str(MANIFEST),
        "qa": str(QA_REPORT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
