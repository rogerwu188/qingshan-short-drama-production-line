#!/usr/bin/env python3
"""Level provider-native release audio per unit without changing picture."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.native_audio_loudness_contract import (
        evaluate_release_loudness,
        evaluate_unit_loudness,
        measure_loudness,
        plan_static_gain,
    )
except ModuleNotFoundError:
    from native_audio_loudness_contract import (
        evaluate_release_loudness,
        evaluate_unit_loudness,
        measure_loudness,
        plan_static_gain,
    )


PREMIX_LIMITER_INPUT_CEILING_DBTP = 6.0
FINAL_LOUDNORM_TRUE_PEAK_DBTP = -3.0
FINAL_LIMITER_LINEAR = 0.668344


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def stream_hash(path: Path, stream: str) -> str:
    result = run([
        "ffmpeg", "-v", "error", "-i", str(path), "-map", stream,
        "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
    ])
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result.stdout.strip().split("=", 1)[1]


def unit_role(unit: dict) -> str:
    if any(str(row.get("dialogue") or "").strip() for row in unit["ordered_prompt_specs"]):
        return "DIALOGUE"
    if str(unit.get("action_classification") or "").upper() == "COMBAT":
        return "ACTION"
    acoustic_text = " ".join(
        [str(unit.get("narrative_beat") or "")]
        + [str(row.get("action") or "") for row in unit["ordered_prompt_specs"]]
    )
    if any(token in acoustic_text for token in ("哨响", "爆裂", "撞击", "破碎", "兵刃", "刀剑")):
        return "ACTION"
    return "AMBIENCE"


def level_release(
    *, source: Path, timeline_path: Path, grouped_path: Path,
    output: Path, qa_path: Path, episode: str, version: str,
    expected_sha256: str | None = None,
) -> dict:
    if expected_sha256 and sha256(source) != expected_sha256:
        raise RuntimeError(f"{episode} source changed or is not the declared authority")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    grouped = json.loads(grouped_path.read_text(encoding="utf-8"))
    units = {row["unit_id"]: row for row in grouped["units"]}
    segments = timeline["segments"]
    content_runtime = float(timeline["content_runtime_seconds"])
    release_runtime = float(timeline["release_runtime_seconds"])

    plans, filters, labels = [], [], []
    for index, segment in enumerate(segments):
        uid = segment["unit_id"]
        start, end = float(segment["output_start"]), float(segment["output_end"])
        role = unit_role(units[uid])
        measured = measure_loudness(source, start_seconds=start, duration_seconds=end - start)
        plan = plan_static_gain(
            measured["integrated_loudness_lufs"], measured["true_peak_dbtp"], role,
            true_peak_ceiling_dbtp=PREMIX_LIMITER_INPUT_CEILING_DBTP,
        )
        gain, label = float(plan["gain_db"]), f"a{index}"
        filters.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={gain:.3f}dB,alimiter=limit=0.841395:attack=5:release=50:level=false[{label}]"
        )
        labels.append(f"[{label}]")
        plans.append({
            "unit_id": uid, "role": role, "start_seconds": start, "end_seconds": end,
            "input": measured, "gain_plan": plan,
        })

    outro_measured = measure_loudness(
        source, start_seconds=content_runtime, duration_seconds=release_runtime - content_runtime,
    )
    outro_plan = plan_static_gain(
        outro_measured["integrated_loudness_lufs"], outro_measured["true_peak_dbtp"], "MUSIC",
        true_peak_ceiling_dbtp=PREMIX_LIMITER_INPUT_CEILING_DBTP,
    )
    filters.append(
        f"[0:a]atrim=start={content_runtime:.6f}:end={release_runtime:.6f},asetpts=PTS-STARTPTS,"
        "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"volume={float(outro_plan['gain_db']):.3f}dB,"
        "alimiter=limit=0.841395:attack=5:release=50:level=false[aoutro]"
    )
    labels.append("[aoutro]")
    filters.append(
        "".join(labels) + f"concat=n={len(labels)}:v=0:a=1,"
        + f"loudnorm=I=-16:TP={FINAL_LOUDNORM_TRUE_PEAK_DBTP}:LRA=11,"
        + f"alimiter=limit={FINAL_LIMITER_LINEAR}:attack=5:release=50:level=false,"
        + f"aresample=48000,apad=whole_dur={release_runtime:.6f},"
        + f"atrim=duration={release_runtime:.6f},asetpts=N/SR/TB[aout]"
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    result = run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(source),
        "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
        "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(output),
    ])
    if result.returncode:
        output.unlink(missing_ok=True)
        raise RuntimeError(result.stderr[-12000:])

    output_units = []
    for row in plans:
        measured = measure_loudness(
            output, start_seconds=row["start_seconds"],
            duration_seconds=row["end_seconds"] - row["start_seconds"],
        )
        output_units.append({"unit_id": row["unit_id"], "role": row["role"], **measured})
    release_metrics = measure_loudness(output)
    failures = evaluate_unit_loudness(output_units) + evaluate_release_loudness(release_metrics)
    source_video_hash = stream_hash(source, "0:v:0")
    output_video_hash = stream_hash(output, "0:v:0")
    if source_video_hash != output_video_hash:
        failures.append("VIDEO_ELEMENTARY_STREAM_CHANGED")
    probe = json.loads(run([
        "ffprobe", "-v", "error", "-show_format", "-of", "json", str(output)
    ]).stdout)
    decoded_duration = float(probe["format"]["duration"])
    if abs(decoded_duration - release_runtime) > 0.1:
        failures.append("RELEASE_DURATION_CHANGED")
    payload = {
        "schema": f"qingshan.{episode.lower()}.{version}.native_audio_loudness_qa.v1",
        "episode": episode, "created_at": now(),
        "status": "PASS_AUDIO_LEVEL_CORRECTED_PICTURE_BIT_EXACT" if not failures else "FAIL",
        "source_release": {"ref": str(source), "sha256": sha256(source)},
        "output_release": {"ref": str(output), "sha256": sha256(output)},
        "processing_scope": "LEVEL_ONLY_NATIVE_AUDIO_NO_DIALOGUE_REPLACEMENT_NO_PICTURE_CHANGE",
        "source_video_stream_sha256": source_video_hash,
        "output_video_stream_sha256": output_video_hash,
        "video_stream_bit_exact": source_video_hash == output_video_hash,
        "duration_seconds": decoded_duration,
        "unit_gain_plans": plans,
        "outro_gain_plan": {"input": outro_measured, "gain_plan": outro_plan},
        "output_unit_loudness": output_units, "release_loudness": release_metrics,
        "failures": failures,
    }
    qa_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--grouped", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qa", type=Path, required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    payload = level_release(
        source=args.source.resolve(), timeline_path=args.timeline.resolve(),
        grouped_path=args.grouped.resolve(), output=args.output.resolve(),
        qa_path=args.qa.resolve(), episode=args.episode, version=args.version,
        expected_sha256=args.expected_sha256,
    )
    print(json.dumps({
        "status": payload["status"], "output": payload["output_release"],
        "release_loudness": payload["release_loudness"], "failures": payload["failures"],
    }, ensure_ascii=False))
    return 0 if payload["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
