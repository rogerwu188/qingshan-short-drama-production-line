#!/usr/bin/env python3
"""Replace E30 U01 with the admitted native-dialogue performance R2 candidate."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
SOURCE_PROJECT = ROOT / "configs/e30_agentcut_v9_subtitled_outro_20260722.json"
PROJECT = ROOT / "configs/e30_agentcut_v11_u01_performance_r2_20260722.json"
U01_RAW = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/u01_performance_r2/outputs/E30_E30-CW-U01-PERFORMANCE-R2_5e29999f-853a-4cd5-9f73-dd4c5e197059.mp4"
U01_CLEAN = ROOT / "working_assets/e30_u01_performance_r2_cleanup_20260722/E30_U01_PERFORMANCE_R2_OCR_CLEAN.mp4"
U01_ADJUDICATION = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/u01_performance_r2/qa/E30_U01_PERFORMANCE_R2_MACHINE_ADJUDICATION.json"
U01_ASR = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722/u01_performance_r2/qa/E30_U01_DIALOGUE_ASR_QA.json"
BASE = ROOT / "exports/e30/agentcut_v11_u01_performance_r2_20260722/E30_AGENTCUT_V11_SUBTITLED_OUTRO_NOT_FINAL.mp4"
DIALOGUE_V10 = ROOT / "working_assets/e30_dialogue_v10_20260722/E30_DIALOGUE_ONLY_V10.wav"
FINAL = ROOT / "exports/e30/final_v11_u01_native_dialogue_20260722/QINGSHAN_E30_FINAL_V11.mp4"
QA = ROOT / "qa/e30_final_v11_u01_native_dialogue_20260722/E30_V11_TECHNICAL_GATE.json"
RECEIPT = ROOT / "workflow/tasks/E30_FINAL_V11_U01_NATIVE_DIALOGUE_BUILD_RECEIPT_20260722.json"
U01_DURATION = 14.0


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = run([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(path),
    ], capture=True)
    return json.loads(result.stdout)


def loudness(path: Path) -> dict:
    result = run([
        str(FFMPEG), "-hide_banner", "-i", str(path), "-af",
        "loudnorm=I=-17:TP=-2.5:LRA=11:print_format=json", "-f", "null", "-",
    ], capture=True)
    payloads = re.findall(r'\{\s*"input_i".*?\}', result.stderr, flags=re.DOTALL)
    if not payloads:
        raise SystemExit("encoded loudness metrics missing")
    payload = json.loads(payloads[-1])
    return {
        "integrated_loudness_lufs": float(payload["input_i"]),
        "true_peak_dbtp": float(payload["input_tp"]),
        "loudness_range_lu": float(payload["input_lra"]),
    }


def normalize_final_audio() -> None:
    measurement = run([
        str(FFMPEG), "-hide_banner", "-i", str(FINAL), "-af",
        "loudnorm=I=-17:TP=-2.5:LRA=11:print_format=json", "-f", "null", "-",
    ], capture=True)
    payloads = re.findall(r'\{\s*"input_i".*?\}', measurement.stderr, flags=re.DOTALL)
    if not payloads:
        raise SystemExit("audio normalization measurement missing")
    measured = json.loads(payloads[-1])
    normalized = FINAL.with_name(FINAL.stem + ".normalized.mp4")
    audio_filter = (
        "loudnorm=I=-17:TP=-2.5:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true:print_format=summary,"
        "alimiter=limit=0.80:level=false"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(FINAL),
        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", audio_filter,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(normalized),
    ])
    normalized.replace(FINAL)


def clean_u01() -> None:
    U01_CLEAN.parent.mkdir(parents=True, exist_ok=True)
    # The isolated OCR hit sits on a background cabinet label, not on a story prop.
    filter_graph = (
        "[0:v]split=2[base][detail];"
        "[detail]crop=80:240:190:205,boxblur=12:2[blur];"
        "[base][blur]overlay=190:205:enable='between(t,3.35,5.65)'[v]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(U01_RAW),
        "-filter_complex", filter_graph, "-map", "[v]", "-map", "0:a:0", "-t", f"{U01_DURATION:.3f}",
        "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(U01_CLEAN),
    ])


def build_project() -> None:
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    project["metadata"].update({
        "version": "V11",
        "status": "AGENTCUT_BASE_U01_PERFORMANCE_R2_NATIVE_DIALOGUE",
        "u01_policy": "PERFORMANCE_R2_NATIVE_DIALOGUE_NO_SYNTHETIC_DIA001",
    })
    project["output"]["path"] = str(BASE)
    clean_sha = sha256(U01_CLEAN)
    for track_name in ("videoTracks", "audioTracks"):
        for track in project["timeline"].get(track_name, []):
            for clip in track.get("clips", []):
                if clip.get("metadata", {}).get("source_id") == "E30-CW-U01":
                    clip["source"] = str(U01_CLEAN)
                    clip["duration"] = U01_DURATION
                    clip["metadata"].update({
                        "source_sha256": clean_sha,
                        "source_admission": "CONDITIONAL_MACHINE_ADMISSION_R2_OCR_CLEANED",
                        "dialogue_policy": "SEEDANCE_NATIVE_AUDIO_REFERENCE_LIPSYNC",
                    })
    project["qingshanAudit"].update({
        "pipelineStage": "E30_AGENTCUT_V11_U01_PERFORMANCE_R2_NATIVE_DIALOGUE",
        "u01_source": str(U01_CLEAN),
        "u01_source_sha256": clean_sha,
        "u01_adjudication": str(U01_ADJUDICATION),
        "u01_asr": str(U01_ASR),
    })
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_base() -> None:
    # Preserve the already-released V9 timing. Two repaired legacy clips have
    # sub-frame container/video-stream tail deltas and are audited after render.
    run([str(AGENTCUT), "validate", str(PROJECT)])
    run([str(AGENTCUT), "render", "--overwrite", str(PROJECT)])


def build_final() -> None:
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    total = float(probe(BASE)["format"]["duration"])
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    dialogue_windows = []
    for track in project["timeline"].get("subtitleTracks", []):
        for clip in track.get("clips", []):
            if clip.get("dialogue_id") == "E30-DIA-001":
                continue
            start = max(U01_DURATION, float(clip["start"]) - 0.12)
            end = float(clip["start"]) + float(clip["duration"]) + 0.12
            dialogue_windows.append(f"between(t,{start:.6f},{end:.6f})")
    native_mute = "+".join(dialogue_windows)
    filter_graph = (
        f"[0:a]volume='if(gt({native_mute},0),0,if(lt(t,{U01_DURATION}),1.0,0.42))':eval=frame[amb];"
        f"[1:a]volume=0:enable='between(t,0,{U01_DURATION})',volume=1.30[vox];"
        "[amb][vox]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "loudnorm=I=-18:LRA=11:TP=-3.0,alimiter=limit=0.80:level=false[aout]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(BASE), "-i", str(DIALOGUE_V10),
        "-filter_complex", filter_graph, "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.6f}",
        "-movflags", "+faststart", str(FINAL),
    ])


def write_reports() -> None:
    info = probe(FINAL)
    metrics = loudness(FINAL)
    streams = info.get("streams", [])
    failures = []
    if not any(row.get("codec_type") == "video" for row in streams):
        failures.append("video_stream_missing")
    if not any(row.get("codec_type") == "audio" for row in streams):
        failures.append("audio_stream_missing")
    if metrics["true_peak_dbtp"] > -1.0:
        failures.append("encoded_true_peak_exceeds_minus_1_dbtp")
    if not -19.0 <= metrics["integrated_loudness_lufs"] <= -15.0:
        failures.append("encoded_integrated_loudness_out_of_release_range")
    payload = {
        "schema": "qingshan.e30.final_v11_technical_gate.v1",
        "episode": "E30",
        "version": "V11",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "final": str(FINAL),
        "final_sha256": sha256(FINAL),
        "probe": info,
        "encoded_audio_metrics": metrics,
        "dialogue_policy": {
            "E30-DIA-001": "SEEDANCE_NATIVE_REFERENCE_AUDIO_AND_LIPSYNC",
            "E30-DIA-002..020": "PREVIOUSLY_ACCEPTED_ROLE_BOUND_AUDIO",
            "synthetic_E30-DIA-001_muted": True,
        },
        "subtitle_coverage": "20/20_BURNED_IN",
        "nalu_motion_outro": "PRESERVED_FROM_AGENTCUT_PROJECT",
        "failures": failures,
        "remaining_gates": ["FINAL_WINDOWED_ASR", "FINAL_FRAME_CADENCE", "FINAL_OCR"],
        "new_generation_calls": 0,
        "new_generation_credits": 0,
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RECEIPT.write_text(json.dumps({
        **payload,
        "status": "BUILT_QA_PENDING" if not failures else "BUILD_TECHNICAL_FAIL",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "u01_raw": str(U01_RAW),
        "u01_raw_sha256": sha256(U01_RAW),
        "u01_clean": str(U01_CLEAN),
        "u01_clean_sha256": sha256(U01_CLEAN),
        "rollback": "/Users/rogerwu/qingshan_short_drama/exports/e30/final_v10_dialogue_subtitled_nalu_motion_20260722/QINGSHAN_E30_FINAL_V10.mp4",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(json.dumps(failures, ensure_ascii=False))
    print(json.dumps({"status": "BUILT_QA_PENDING", "final": str(FINAL), "sha256": payload["final_sha256"]}, ensure_ascii=False))


def main() -> int:
    for required in (SOURCE_PROJECT, U01_RAW, U01_ADJUDICATION, U01_ASR, DIALOGUE_V10):
        if not required.is_file():
            raise SystemExit(f"required input missing: {required}")
    clean_u01()
    build_project()
    render_base()
    build_final()
    normalize_final_audio()
    write_reports()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
