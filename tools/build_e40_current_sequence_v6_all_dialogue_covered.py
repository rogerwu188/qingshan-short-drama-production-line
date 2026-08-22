#!/usr/bin/env python3
"""Build the current E40 story-order assembly with terminal R02/R03/R04 coverage."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V6_ALL_DIALOGUE_COVERED.mp4"
QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V6_ALL_DIALOGUE_COVERED_QA.json"

SEGMENTS = [
    ("R01", "working_assets/e40_remake_20260822/terminal_switch_coverage_v1/E40_R01_FAN_SHADOW_EDITORIAL_INSERT_V1.mp4", False),
    ("R01-YUNFEI-A", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R01-YUNFEI-A_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R01-DIALOGUE", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/remaining_dialogue_terminal_coverage_v1/E40_R01_DIALOGUE_TERMINAL_COVERAGE_V1.mp4", False),
    ("R02", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_dialogue_coverage_v1/E40_R02_CHENJI_BACKVIEW_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R03", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_dialogue_coverage_v1/E40_R03_VEILED_REACTION_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R03-YUNFEI-B", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R03-YUNFEI-B_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R04-CHENJI-A", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R04-CHENJI-A_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R04", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_switch_coverage_v1/E40_R04_YUNFEI_OFFSCREEN_COVERAGE_V1.mp4", False),
    ("R04-YUNFEI-B", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R04-YUNFEI-B_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R05", "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R05-VIDEO-NATIVE-EXCEPTION-V1.mp4", True),
    ("R05-DIALOGUE", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/remaining_dialogue_terminal_coverage_v1/E40_R05_DIALOGUE_TERMINAL_COVERAGE_V1.mp4", False),
    ("R06A", "working_assets/e40_remake_20260821/switch_coverage_wave2_v1/editorial_coverage/E40_R06A_ARROW_CURTAIN_MACRO_SWITCH_COVERAGE_V1.mp4", False),
    ("R06-ASHUAN-A", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R06-ASHUAN-A_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R06B", "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R06B-VIDEO-NATIVE-EXCEPTION-V1.mp4", True),
    ("R06C", "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R06C-VIDEO-NATIVE-EXCEPTION-V1.mp4", True),
    ("R07", "working_assets/e40_remake_20260822/terminal_switch_coverage_v1/E40_R07_THREE_ARROW_EDITORIAL_INSERT_V1.mp4", False),
    ("R07-DIALOGUE", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/remaining_dialogue_terminal_coverage_v1/E40_R07_DIALOGUE_TERMINAL_COVERAGE_V1.mp4", False),
    ("R08", "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R08-VIDEO-NATIVE-EXCEPTION-V1.mp4", True),
    ("R08-YUNFEI-A", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R08-YUNFEI-A_DIALOGUE_COVERAGE_V1.mp4", False),
    ("R08-DIALOGUE", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/remaining_dialogue_terminal_coverage_v1/E40_R08_DIALOGUE_TERMINAL_COVERAGE_V1.mp4", False),
    ("R08-YUNFEI-C", "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_R08-YUNFEI-C_DIALOGUE_COVERAGE_V1.mp4", False),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path: Path) -> dict:
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path),
    ])
    return json.loads(raw)


def main() -> int:
    resolved = [(unit, ROOT / rel, native) for unit, rel, native in SEGMENTS]
    missing = [str(path) for _, path, _ in resolved if not path.is_file()]
    if missing:
        raise SystemExit("missing inputs: " + ", ".join(missing))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    QA.parent.mkdir(parents=True, exist_ok=True)

    command = ["ffmpeg", "-y", "-loglevel", "error"]
    durations: list[float] = []
    input_has_audio: list[bool] = []
    rows = []
    for unit, path, native in resolved:
        info = probe(path)
        duration = float(info["format"]["duration"])
        has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        command += ["-i", str(path)]
        durations.append(duration)
        input_has_audio.append(has_audio)
        rows.append({"unit_id": unit, "path": str(path.relative_to(ROOT)), "sha256": sha(path), "duration_seconds": duration, "native_provider_audio_required": native, "source_has_audio": has_audio})

    filters = []
    concat = []
    for index, duration in enumerate(durations):
        filters.append(f"[{index}:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{index}]")
        if input_has_audio[index]:
            filters.append(f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[a{index}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[a{index}]")
        concat.append(f"[v{index}][a{index}]")
    filters.append("".join(concat) + f"concat=n={len(resolved)}:v=1:a=1[vout][aout]")
    command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT)]
    subprocess.run(command, check=True)

    out_probe = probe(OUT)
    duration = float(out_probe["format"]["duration"])
    result = {
        "schema": "qingshan.e40.assembly_candidate_qa.v1",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "asset_path": str(OUT.relative_to(ROOT)),
        "asset_sha256": sha(OUT),
        "technical_status": "PASS",
        "technical": {"container": "MP4", "video": "H264_720X1280_24FPS", "audio": "AAC_48000HZ_STEREO", "duration_seconds": duration, "same_task_native_audio_retained_for_q2_segments": True, "external_tts_applied": False, "bgm_applied": False},
        "sequence": rows,
        "duration_diagnostic": {
            "class": "DIAGNOSTIC",
            "canonical_planning_seconds": 163,
            "assembled_seconds": duration,
            "delta_seconds": round(163 - duration, 3),
            "blocking": False,
            "reason": "Runtime delta is a planning diagnostic only; it cannot prove or disprove canonical shot coverage.",
        },
        "registered_content_gate": {
            "gate_id": "COMPLETE-VIDEO-PROMPT-MANIFEST",
            "status": "NOT_EVALUATED_BY_RUNTIME",
            "reason": "The registered gate validates complete unit compilation and SHA bindings; its registry parameters contain no runtime target.",
        },
        "admission_status": "NOT_ADMITTED_AS_FINAL_EPISODE",
        "release_allowed": False,
        "next_action": "Build an exact canonical-shot coverage matrix and run registered final QA; do not pad, loop, stretch, replace visible-lip audio, or publish this candidate.",
    }
    QA.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_TECHNICAL_NOT_FINAL", "output": result["asset_path"], "sha256": result["asset_sha256"], "duration_seconds": duration, "qa": str(QA.relative_to(ROOT)), "qa_sha256": sha(QA)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
