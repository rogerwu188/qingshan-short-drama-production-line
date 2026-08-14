#!/usr/bin/env python3
import argparse
import json
import math
import re
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


HAN = re.compile(r"[\u3400-\u9fff]")


def rms_db(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -120.0
    value = float(np.sqrt(np.mean(np.square(samples.astype(np.float64) / 32768.0))))
    return 20.0 * math.log10(max(value, 1e-6))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    with wave.open(str(args.audio), "rb") as wav:
        rate = wav.getframerate()
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        frames = wav.getnframes()
        if channels != 1 or width != 2:
            raise SystemExit("expected mono 16-bit PCM WAV")
        samples = np.frombuffer(wav.readframes(frames), dtype=np.int16)
    duration = frames / rate

    model = WhisperModel(str(args.model), device="cpu", compute_type="int8")
    result, info = model.transcribe(
        str(args.audio),
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 250},
        word_timestamps=True,
        condition_on_previous_text=True,
    )

    rows = []
    previous_end = 0.0
    for segment in result:
        text = segment.text.strip()
        if not text:
            continue
        start, end = float(segment.start), float(segment.end)
        char_count = len(HAN.findall(text))
        segment_duration = max(end - start, 0.01)
        start_index = max(0, int(start * rate))
        end_index = min(len(samples), int(end * rate))
        rows.append({
            "start": start,
            "end": end,
            "duration": segment_duration,
            "gap_before": max(0.0, start - previous_end),
            "text": text,
            "han_char_count": char_count,
            "han_chars_per_second": char_count / segment_duration,
            "avg_logprob": float(segment.avg_logprob),
            "no_speech_prob": float(segment.no_speech_prob),
            "rms_dbfs": rms_db(samples[start_index:end_index]),
            "words": [
                {"start": float(word.start), "end": float(word.end), "word": word.word}
                for word in (segment.words or [])
            ],
        })
        previous_end = end

    speech_seconds = sum(row["duration"] for row in rows)
    gaps = np.array([row["gap_before"] for row in rows[1:]], dtype=np.float64)
    rates = np.array([row["han_chars_per_second"] for row in rows if row["han_char_count"]], dtype=np.float64)
    levels = np.array([row["rms_dbfs"] for row in rows], dtype=np.float64)
    summary = {
        "audio": str(args.audio),
        "model": str(args.model),
        "language": info.language,
        "language_probability": float(info.language_probability),
        "duration_seconds": duration,
        "segment_count": len(rows),
        "speech_coverage_ratio_asr_segments": speech_seconds / duration,
        "median_gap_seconds": float(np.median(gaps)) if gaps.size else None,
        "gap_p90_seconds": float(np.percentile(gaps, 90)) if gaps.size else None,
        "gaps_over_1s": int(np.sum(gaps > 1.0)) if gaps.size else 0,
        "median_han_chars_per_second": float(np.median(rates)) if rates.size else None,
        "han_chars_per_second_p10": float(np.percentile(rates, 10)) if rates.size else None,
        "han_chars_per_second_p90": float(np.percentile(rates, 90)) if rates.size else None,
        "speech_rms_dbfs_median": float(np.median(levels)) if levels.size else None,
        "speech_rms_dynamic_range_p10_p90_db": float(np.percentile(levels, 90) - np.percentile(levels, 10)) if levels.size else None,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "asr_first20min.json").write_text(
        json.dumps({"summary": summary, "segments": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [f"{row['start']:07.2f}-{row['end']:07.2f}\t{row['text']}" for row in rows]
    (args.output / "asr_first20min.txt").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
