#!/usr/bin/env python3
"""Replace E40 DIA-001..003 with an eight-second non-dialogue visual beat."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "working_assets/e40_remake_20260822"
OUT_DIR = BASE / "full_performance_native_dialogue_v1/script_equivalent_v17"
OUT = OUT_DIR / "E40_R01_DIA001_003_SCRIPT_EQUIVALENT_VISUAL_V1.mp4"
V16 = BASE / "assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX.mp4"
V17 = BASE / "assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V17_R01_SCRIPT_EQUIVALENT.mp4"
QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/script_equivalent_v17/E40_R01_DIA001_003_SCRIPT_EQUIVALENT_QA_V1.json"
V17_QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V17_R01_SCRIPT_EQUIVALENT_QA.json"

ASHUAN = BASE / "full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R06-ASHUAN-A-V1-KF-QA-V2_c4eaf004-c4a2-4e70-9c40-0f1a72697983.png"
OFFER = BASE / "full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R01-CHENJI-B-V1-KF-QA-V2_2074b2a7-8514-4b9a-8aaa-2b7770c59cd5.png"
DECISION = BASE / "full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R08-CHENJI-B-V1-KF-QA-V2_5690f9aa-333c-4403-9351-6560ac877285.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    for path in (ASHUAN, OFFER, DECISION, V16):
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", "2", "-i", str(ASHUAN),
        "-loop", "1", "-t", "3", "-i", str(OFFER),
        "-loop", "1", "-t", "3", "-i", str(DECISION),
        "-f", "lavfi", "-t", "8", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        "[0:v]fps=24,scale=720:1280,zoompan=z='min(zoom+0.0003,1.018)':d=1:s=720x1280:fps=24,trim=duration=2,setpts=PTS-STARTPTS,setsar=1[v0];"
        "[1:v]fps=24,scale=720:1280,zoompan=z='min(zoom+0.0002,1.015)':d=1:s=720x1280:fps=24,trim=duration=3,setpts=PTS-STARTPTS,setsar=1[v1];"
        "[2:v]fps=24,scale=720:1280,zoompan=z='min(zoom+0.0002,1.015)':d=1:s=720x1280:fps=24,trim=duration=3,setpts=PTS-STARTPTS,setsar=1[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a", "-t", "8",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(OUT),
    ])

    # V16 begins with an 8s establishing shot followed by the obsolete 8s
    # subtitle-only R01 block. Replace that exact block and preserve the rest.
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(V16), "-i", str(OUT),
        "-filter_complex",
        "[0:v]trim=start=0:end=8,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=0:end=8,asetpts=PTS-STARTPTS[a0];"
        "[0:v]trim=start=16,setpts=PTS-STARTPTS[v2];"
        "[0:a]atrim=start=16,asetpts=PTS-STARTPTS[a2];"
        "[v0][a0][1:v][1:a][v2][a2]concat=n=3:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(V17),
    ])
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(V17), "-f", "null", "-"], check=True)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    qa = {
        "schema": "qingshan.e40.script_equivalent_visual_coverage.v1",
        "episode": "E40",
        "status": "PASS_ZERO_COST_SCRIPT_EQUIVALENT_NO_DIALOGUE",
        "recorded_at": now,
        "successor_task_id": "E40-MISSING12-SWITCH-COVERAGE-R01-DIA001-003-V1",
        "source_failure_disposition": "SWITCH_COVERAGE_NO_ATTEMPT4",
        "retired_spoken_dialogue_ids": ["E40-DIA-001", "E40-DIA-002", "E40-DIA-003"],
        "canonical_equivalence": [
            {"meaning": "阿栓受制", "visual_evidence": "阿栓独立受控轴线"},
            {"meaning": "云妃提出交换", "visual_evidence": "帘后权力轴与陈迹背面形成交易对峙"},
            {"meaning": "陈迹必须选择", "visual_evidence": "陈迹停步面对帘后并以无对白反应收束"},
        ],
        "audio_policy": "NO_DIALOGUE; AAC silence only because sources are Q1 stills, not Seedance video; no native source audio was removed; no TTS/BGM/cross-task audio.",
        "subtitle_policy": "DIA-001..003 are removed as spoken subtitles; do not burn the obsolete lines over this unit.",
        "visible_lips": "NONE_SPEAKING",
        "sources": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in (ASHUAN, OFFER, DECISION)],
        "output": {"path": str(OUT.relative_to(ROOT)), "sha256": sha(OUT), "duration_seconds": 8.0},
    }
    write(QA, qa)
    v17_probe = probe(V17)
    v17_qa = {
        "schema": "qingshan.e40.assembly_candidate.v17.script_equivalent.v1",
        "episode": "E40",
        "status": "TECHNICAL_PASS_CONTENT_QA_ACTIVE",
        "recorded_at": now,
        "baseline": {"path": str(V16.relative_to(ROOT)), "sha256": sha(V16)},
        "replacement": {"window_seconds": [8.0, 16.0], "task_id": qa["successor_task_id"], "evidence_ref": str(QA.relative_to(ROOT))},
        "asset_path": str(V17.relative_to(ROOT)),
        "asset_sha256": sha(V17),
        "probe": v17_probe,
        "decode_status": "PASS_ZERO_ERRORS",
        "release_allowed": False,
        "next_successor_task_id": "E40-MISSING12-SWITCH-COVERAGE-R02-DIA005-007-V1",
    }
    write(V17_QA, v17_qa)
    print(json.dumps({"coverage": qa["output"], "coverage_qa": str(QA.relative_to(ROOT)), "v17": v17_qa["asset_path"], "v17_sha256": v17_qa["asset_sha256"], "v17_qa": str(V17_QA.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
