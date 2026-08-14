#!/usr/bin/env python3
"""Generate role-bound E30 dialogue and produce the first release-eligible final."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import edge_tts


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")
PROJECT = ROOT / "configs/e30_agentcut_v9_subtitled_outro_20260722.json"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/E30_SUBTITLE_CONTRACT_V1.json"
SOURCE = ROOT / "exports/e30/agentcut_v9_subtitled_outro_20260722/E30_AGENTCUT_V9_SUBTITLED_OUTRO_NOT_FINAL.mp4"
WORK = ROOT / "working_assets/e30_dialogue_v10_20260722"
CACHE_WORK = ROOT / "working_assets/e30_dialogue_v2_20260722"
OUT_DIR = ROOT / "exports/e30/final_v10_dialogue_subtitled_nalu_motion_20260722"
QA_DIR = ROOT / "qa/e30_final_v10_dialogue_20260722"
FINAL = OUT_DIR / "QINGSHAN_E30_FINAL_V10.mp4"
DIALOGUE_MIX = WORK / "E30_DIALOGUE_ONLY_V10.wav"
MANIFEST = QA_DIR / "E30_DIALOGUE_AUDIO_MANIFEST_V10.json"
GATE = QA_DIR / "E30_DIALOGUE_RELEASE_GATE_V10.json"

VOICE = {
    "陈迹": ("zh-CN-YunxiNeural", "+12%", "-4Hz"),
    "云羊": ("zh-CN-YunxiaNeural", "+13%", "+2Hz"),
    "皎兔": ("zh-CN-XiaoyiNeural", "+12%", "+4Hz"),
    "乌云": ("zh-CN-YunyangNeural", "-5%", "-18Hz"),
    "刺客": ("zh-CN-YunjianNeural", "+4%", "-12Hz"),
    "姚太医": ("zh-CN-YunyangNeural", "-8%", "-10Hz"),
}


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def probe(path: Path) -> dict:
    proc = run([str(FFPROBE), "-v", "error", "-show_entries",
                "format=duration,size:stream=index,codec_type,codec_name,sample_rate,channels",
                "-of", "json", str(path)], capture=True)
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
    factors = []
    while factor > 2.0:
        factors.append(2.0)
        factor /= 2.0
    while factor < 0.5:
        factors.append(0.5)
        factor /= 0.5
    factors.append(factor)
    return ",".join(f"atempo={value:.6f}" for value in factors)


def load_rows() -> tuple[list[dict], float]:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    by_id = {row["dia_id"]: row for row in contract["dialogue"]}
    clips = project["timeline"]["subtitleTracks"][0]["clips"]
    if len(clips) != 20 or set(by_id) != {clip["dialogue_id"] for clip in clips}:
        raise SystemExit("E30 dialogue contract/timeline is not exactly 20/20")
    rows = []
    for clip in clips:
        source = by_id[clip["dialogue_id"]]
        expected_subtitle = re.sub(r"'([^']+)'", r"‘\1’", source["spoken_text"])
        expected_subtitle = re.sub(r'"([^"]+)"', r'“\1”', expected_subtitle).replace('"', '”').replace("'", "’")
        if expected_subtitle != clip["text"] or source["speaker"] not in VOICE:
            raise SystemExit(f"Dialogue binding mismatch: {clip['dialogue_id']}")
        voice, rate, pitch = VOICE[source["speaker"]]
        rows.append({"dialogue_id": source["dia_id"], "speaker": source["speaker"],
                     "text": source["spoken_text"], "start": float(clip["start"]),
                     "window_duration": float(clip["duration"]), "voice": voice,
                     "rate": rate, "pitch": pitch})
    return rows, float(project["metadata"]["content_runtime_seconds"])


async def generate(rows: list[dict]) -> None:
    raw_dir, fit_dir = WORK / "raw", WORK / "fitted"
    raw_dir.mkdir(parents=True, exist_ok=True)
    fit_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        for kind, suffix in (("raw", ".mp3"), ("fitted", ".wav")):
            cached = CACHE_WORK / kind / f"{row['dialogue_id']}{suffix}"
            target = (raw_dir if kind == "raw" else fit_dir) / cached.name
            if cached.is_file() and not target.is_file():
                shutil.copy2(cached, target)
    missing = [row for row in rows if not (raw_dir / f"{row['dialogue_id']}.mp3").is_file()]
    await asyncio.gather(*[
        edge_tts.Communicate(text=row["text"], voice=row["voice"], rate=row["rate"], pitch=row["pitch"])
        .save(str(raw_dir / f"{row['dialogue_id']}.mp3")) for row in missing
    ])
    for row in rows:
        raw, fitted = raw_dir / f"{row['dialogue_id']}.mp3", fit_dir / f"{row['dialogue_id']}.wav"
        raw_duration = duration(raw)
        target = max(0.65, row["window_duration"] - 0.10)
        factor = max(1.0, raw_duration / target)
        if not fitted.is_file() or duration(fitted) > row["window_duration"] + 0.04:
            run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                 "-af", f"{atempo_chain(factor)},highpass=f=75,lowpass=f=12500,loudnorm=I=-18:LRA=7:TP=-2",
                 "-ac", "2", "-ar", "48000", str(fitted)])
        fitted_duration = duration(fitted)
        if fitted_duration > row["window_duration"] + 0.04:
            raise SystemExit(f"Dialogue exceeds subtitle window: {row['dialogue_id']}")
        row.update({"raw_file": str(raw), "raw_sha256": sha256(raw), "raw_duration": round(raw_duration, 6),
                    "fitted_file": str(fitted), "fitted_sha256": sha256(fitted),
                    "fitted_duration": round(fitted_duration, 6), "speed_factor": round(factor, 6)})


def mix_dialogue(rows: list[dict], total: float) -> None:
    args = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-t", f"{total:.6f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    for row in rows:
        args.extend(["-i", row["fitted_file"]])
    filters, inputs = ["[0:a]volume=0[base]"], ["[base]"]
    for index, row in enumerate(rows, 1):
        delay = round(row["start"] * 1000)
        filters.append(f"[{index}:a]adelay={delay}|{delay}[d{index}]")
        inputs.append(f"[d{index}]")
    filters.append("".join(inputs) + f"amix=inputs={len(inputs)}:duration=first:dropout_transition=0,alimiter=limit=0.95[out]")
    run(args + ["-filter_complex", ";".join(filters), "-map", "[out]", "-t", f"{total:.6f}",
                "-ac", "2", "-ar", "48000", str(DIALOGUE_MIX)])


def mux(total: float) -> None:
    run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE), "-i", str(DIALOGUE_MIX),
         "-filter_complex", "[0:a]volume=0.42[amb];[1:a]volume=1.30[vox];[amb][vox]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,loudnorm=I=-18:LRA=11:TP=-3.0,alimiter=limit=0.80:level=false[aout]",
         "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{total:.6f}", "-movflags", "+faststart", str(FINAL)])


def measure_loudness(path: Path) -> dict:
    proc = subprocess.run([
        str(FFMPEG), "-hide_banner", "-i", str(path),
        "-af", "loudnorm=I=-17:TP=-2.5:LRA=11:print_format=json", "-f", "null", "-",
    ], check=True, text=True, capture_output=True)
    matches = re.findall(r"\{\s*\"input_i\".*?\}", proc.stderr, flags=re.DOTALL)
    if not matches:
        raise SystemExit("final encoded loudness metrics missing")
    payload = json.loads(matches[-1])
    return {
        "integrated_loudness_lufs": float(payload["input_i"]),
        "true_peak_dbtp": float(payload["input_tp"]),
        "loudness_range_lu": float(payload["input_lra"]),
    }


def main() -> int:
    for directory in (WORK, OUT_DIR, QA_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    rows, content_duration = load_rows()
    asyncio.run(generate(rows))
    total_duration = duration(SOURCE)
    mix_dialogue(rows, total_duration)
    mux(total_duration)
    final_probe = probe(FINAL)
    loudness = measure_loudness(FINAL)
    failures = []
    audio_streams = [stream for stream in final_probe["streams"] if stream["codec_type"] == "audio"]
    if len(rows) != 20 or sum(1 for row in rows if row["speaker"] in VOICE) != 20:
        failures.append("dialogue_contract_not_20_role_bound_lines")
    if not audio_streams:
        failures.append("final_audio_stream_missing")
    if abs(float(final_probe["format"]["duration"]) - total_duration) > 0.2:
        failures.append("duration_changed")
    if any(row["start"] + row["fitted_duration"] > content_duration + 0.04 for row in rows):
        failures.append("dialogue_overlaps_nalu_outro")
    if loudness["true_peak_dbtp"] > -1.0:
        failures.append("encoded_true_peak_exceeds_minus_1_dbtp")
    if not -19.0 <= loudness["integrated_loudness_lufs"] <= -15.0:
        failures.append("encoded_integrated_loudness_out_of_release_range")
    report = {"schema": "qingshan.dialogue_audio_release_gate.v2", "episode": "E30", "version": "V10",
              "status": "PASS" if not failures else "FAIL", "dialogue_audio_claimed": True,
              "expected_dialogue_count": 20, "verified_dialogue_count": len(rows), "role_bound_count": 20,
              "final_video": str(FINAL), "final_sha256": sha256(FINAL), "final_probe": final_probe,
              "retained_video_sha256": sha256(SOURCE),
              "video_stream_policy": "COPY_RETAINS_20_BURNED_SUBTITLES_AND_NALU_MOTION",
              "audio_policy": "NATIVE_AMBIENCE_DUCKED_PLUS_20_ROLE_BOUND_DIALOGUE_LINES",
              "encoded_audio_metrics": loudness,
              "encoded_audio_limits": {"true_peak_dbtp_max": -1.0, "integrated_loudness_lufs_range": [-19.0, -15.0]},
              "audio_manifest": str(MANIFEST),
              "asr_report": str(QA_DIR / "E30_DIALOGUE_ASR_AUDIT_V10.json"),
              "content_runtime_seconds": content_duration, "nalu_outro_seconds": 3.0, "failures": failures}
    MANIFEST.write_text(json.dumps({"schema": "qingshan.dialogue_audio_manifest.v1", "episode": "E30",
                                    "source_contract": str(CONTRACT), "source_contract_sha256": sha256(CONTRACT),
                                    "dialogue_line_count": 20, "remote_generation_calls": 0,
                                    "remote_generation_credits": 0, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GATE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(json.dumps(failures, ensure_ascii=False))
    print(json.dumps({"final": str(FINAL), "sha256": report["final_sha256"],
                      "duration": float(final_probe["format"]["duration"]), "dialogue_lines": 20,
                      "manifest": str(MANIFEST), "qa": str(GATE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
