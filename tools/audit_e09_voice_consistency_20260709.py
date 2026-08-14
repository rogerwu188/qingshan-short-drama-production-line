#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import wave
from pathlib import Path

import numpy as np


BASE = Path("/Users/rogerwu/qingshan_short_drama")
FFMPEG = BASE / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
VIDEO = Path(os.environ.get(
    "E09_VOICE_VIDEO",
    str(BASE / "exports/e09/api_20260709/qingshan_E09_final_titled_subtitled_nalu_20260709.mp4"),
))
VOICE_LOCKED_MANIFEST = os.environ.get("E09_VOICE_LOCKED_MANIFEST")
RUN_DIR = BASE / "working_assets/e09_api_20260709/videos"
OUT_DIR = BASE / "qa/e09_api_package_20260709/voice_consistency"
REPORT_JSON = OUT_DIR / "e09_voice_consistency_report_20260709.json"
REPORT_MD = OUT_DIR / "e09_voice_consistency_report_20260709.md"

SHOT_VOICE_MAP = {
    "01": "VOICE-陈迹-古装",
    "02": "VOICE-陈迹-古装",
    "03": "VOICE-陈迹-古装",
    "04": "VOICE-陈迹-古装",
    "05": "VOICE-陈迹-古装",
    "06": "VOICE-陈迹-古装",
    "07": "VOICE-陈迹-古装",
    "08": "VOICE-陈迹-古装",
    "09": "VOICE-佘登科",
    "10": "VOICE-陈迹-古装",
    "11": "VOICE-陈迹-古装",
    "12": "VOICE-陈迹-古装",
    "13": "VOICE-陈迹-古装",
    "14": "VOICE-陈迹-古装",
    "15": "VOICE-陈迹-古装",
    "16": "VOICE-陈迹-古装",
    "17": "VOICE-陈迹-古装",
    "18": "VOICE-陈迹-古装",
    "19": "VOICE-陈迹-古装",
    "20": "VOICE-乌云-猫-final-hook-only",
}

VOICE_RULES = {
    "VOICE-陈迹-古装": "与现代陈迹同一灵魂，更沉稳冷静；少年感保留，不能变中年权臣嗓。",
    "VOICE-佘登科": "年轻男声，快、轻、带一点喜感。",
    "VOICE-乌云-猫-final-hook-only": "第20镜低声中文钩子；第20镜前只能猫声/动作，不能人声。",
}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=True)


def duration(path: Path) -> float:
    proc = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path)], text=True, capture_output=True)
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not match:
        return 0.0
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def extract_wav(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(dst),
    ])


def wav_samples(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        data = wf.readframes(wf.getnframes())
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return sr, arr


def dominant_pitch(samples: np.ndarray, sr: int) -> float:
    if len(samples) < sr // 2:
        return 0.0
    x = samples[: min(len(samples), sr * 5)]
    x = x - np.mean(x)
    frame = x[np.abs(x) > 0.012]
    if len(frame) < sr // 5:
        frame = x
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1 :]
    lo = max(1, int(sr / 280))
    hi = min(len(corr) - 1, int(sr / 70))
    if hi <= lo:
        return 0.0
    peak = lo + int(np.argmax(corr[lo:hi]))
    if corr[peak] <= 0:
        return 0.0
    return sr / peak


def spectral_centroid(samples: np.ndarray, sr: int) -> float:
    if len(samples) < 512:
        return 0.0
    x = samples[: min(len(samples), sr * 5)]
    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    denom = float(np.sum(spectrum))
    if denom <= 1e-8:
        return 0.0
    return float(np.sum(freqs * spectrum) / denom)


def features(path: Path) -> dict:
    sr, samples = wav_samples(path)
    voiced = samples[np.abs(samples) > 0.012]
    rms = float(math.sqrt(np.mean(samples * samples))) if len(samples) else 0.0
    voiced_ratio = float(len(voiced) / max(1, len(samples)))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(samples))).astype(np.float32))) if len(samples) > 1 else 0.0
    return {
        "rms": round(rms, 5),
        "voiced_ratio": round(voiced_ratio, 4),
        "zero_crossing_rate": round(zcr, 5),
        "dominant_pitch_hz": round(dominant_pitch(samples, sr), 1),
        "spectral_centroid_hz": round(spectral_centroid(samples, sr), 1),
    }


def transcribe(video: Path) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        return {"status": "SKIP", "reason": f"faster_whisper unavailable: {exc}"}

    try:
        model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
            download_root=str(BASE / "working_assets/hf_cache/faster_whisper"),
            local_files_only=True,
        )
    except Exception as exc:
        return {"status": "FAIL", "reason": f"local ASR model unavailable: {exc}"}
    segments, info = model.transcribe(str(video), language="zh", vad_filter=True)
    rows = []
    cjk = latin = 0
    for seg in segments:
        text = seg.text.strip()
        cjk += len(re.findall(r"[\u4e00-\u9fff]", text))
        latin += len(re.findall(r"[A-Za-z]", text))
        rows.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
    return {
        "status": "PASS" if info.language == "zh" and cjk > 20 and latin == 0 else "REVIEW",
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "segment_count": len(rows),
        "cjk_chars": cjk,
        "latin_chars": latin,
        "segments": rows,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_dir = OUT_DIR / "shot_wavs"
    rows = []
    locked_rows = {}
    if VOICE_LOCKED_MANIFEST:
        manifest = json.loads(Path(VOICE_LOCKED_MANIFEST).read_text(encoding="utf-8"))
        locked_rows = {row["shot"]: row for row in manifest.get("dialogue_rows", [])}
    for shot in range(1, 21):
        shot_id = f"{shot:02d}"
        if shot_id in locked_rows:
            src = Path(locked_rows[shot_id]["tts"])
        else:
            src = RUN_DIR / f"shot_{shot_id}" / "result_01.mp4"
        wav = audio_dir / f"shot_{shot_id}.wav"
        extract_wav(src, wav)
        item = {
            "shot": shot_id,
            "voice_id": SHOT_VOICE_MAP[shot_id],
            "duration": round(duration(src), 2),
            "audio_features": features(wav),
        }
        rows.append(item)

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["voice_id"], []).append(row)

    voice_stats = {}
    warnings = []
    for voice_id, items in grouped.items():
        pitches = [i["audio_features"]["dominant_pitch_hz"] for i in items if i["audio_features"]["dominant_pitch_hz"] > 0]
        centroids = [i["audio_features"]["spectral_centroid_hz"] for i in items if i["audio_features"]["spectral_centroid_hz"] > 0]
        voice_stats[voice_id] = {
            "shot_count": len(items),
            "pitch_mean_hz": round(float(np.mean(pitches)), 1) if pitches else 0,
            "pitch_std_hz": round(float(np.std(pitches)), 1) if pitches else 0,
            "centroid_mean_hz": round(float(np.mean(centroids)), 1) if centroids else 0,
            "centroid_std_hz": round(float(np.std(centroids)), 1) if centroids else 0,
            "rule": VOICE_RULES.get(voice_id, ""),
        }
        if voice_id == "VOICE-陈迹-古装" and len(pitches) >= 4 and np.std(pitches) > 45:
            warnings.append("陈迹跨镜头基频波动偏大，需要人工听检或统一重配音。")
        if voice_id == "VOICE-乌云-猫-final-hook-only":
            if items[0]["shot"] != "20":
                warnings.append("乌云人声出现在第20镜之外。")

    asr = transcribe(VIDEO)
    if asr.get("status") != "PASS":
        warnings.append("ASR 未达到中文对白硬通过，需要人工听检或重配音。")

    report = {
        "video": str(VIDEO),
        "voice_id_policy": "Voice continuity is release-blocking. Generated platform voices are accepted only after ASR and same-VOICE-ID acoustic/manual review.",
        "shot_voice_map": SHOT_VOICE_MAP,
        "shots": rows,
        "voice_stats": voice_stats,
        "asr": asr,
        "warnings": warnings,
        "status": "REVIEW_REQUIRED_BLOCKING" if warnings else "PASS_WITH_MANUAL_SPOT_CHECK_RECOMMENDED",
        "next_action_if_blocked": "If manual listening confirms drift, mute platform dialogue and rebuild with unified VOICE-ID dubbing before publication.",
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# E09 Voice Consistency QA",
        "",
        f"- Video: `{VIDEO}`",
        f"- Status: `{report['status']}`",
        f"- Policy: {report['voice_id_policy']}",
        "",
        "## Voice Stats",
        "",
    ]
    for voice_id, stats in voice_stats.items():
        lines.append(
            f"- `{voice_id}`: shots `{stats['shot_count']}`, pitch mean `{stats['pitch_mean_hz']}` Hz, "
            f"pitch std `{stats['pitch_std_hz']}` Hz, centroid mean `{stats['centroid_mean_hz']}` Hz. {stats['rule']}"
        )
    lines.extend([
        "",
        "## ASR",
        "",
        f"- Status: `{asr.get('status')}`",
        f"- Language: `{asr.get('language')}` probability `{asr.get('language_probability')}`",
        f"- Segments: `{asr.get('segment_count')}`, CJK chars `{asr.get('cjk_chars')}`, Latin chars `{asr.get('latin_chars')}`",
        "",
        "## Warnings",
        "",
    ])
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No machine warning. Manual spot listening is still recommended for the main recurring voice before release.")
    lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(REPORT_JSON), "warnings": warnings}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
