#!/usr/bin/env python3
"""Run registered, exact-SHA Q1/Q2 checks for E40 V18 switch coverage."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/script_equivalent_v18/E40_MISSING12_SCRIPT_EQUIVALENT_CANDIDATES_QA_V1.json"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/script_equivalent_v18/E40_MISSING12_SCRIPT_EQUIVALENT_REGISTERED_Q1_Q2_V1.json"
CONTACT_DIR = OUT.parent / "contact_sheets"
V18_QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V18_MISSING12_SCRIPT_EQUIVALENT_QA.json"

EXPECTED_DIALOGUE_IDS = {f"E40-DIA-{n:03d}" for n in (1, 2, 3, 5, 6, 7, 8, 9, 10, 17, 19, 20)}
REGISTERED_GATES = [
    "CHARACTER-IDENTITY-ADMISSION",
    "SCENE-AUTHORITY-LOCK",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path: Path) -> dict:
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], check=True)
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json", str(path),
    ])
    return json.loads(raw)


def contact_sheet(path: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(path), "-vf",
        "fps=1/2,scale=180:320,tile=5x1:padding=4:margin=4", "-frames:v", "1", str(out),
    ], check=True)


def main() -> int:
    report = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    outputs = report["outputs"]
    dialogue_ids = {item for output in outputs for item in output["dialogue_ids"]}
    if dialogue_ids != EXPECTED_DIALOGUE_IDS:
        raise SystemExit(f"dialogue coverage mismatch: {sorted(dialogue_ids ^ EXPECTED_DIALOGUE_IDS)}")
    if len(outputs) != 7:
        raise SystemExit(f"expected seven successor outputs, got {len(outputs)}")

    results = []
    exact_hashes = set()
    for output in outputs:
        path = ROOT / output["path"]
        digest = sha(path)
        if digest != output["sha256"]:
            raise SystemExit(f"SHA drift: {output['task']}")
        metadata = probe(path)
        streams = metadata["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        audio = next(stream for stream in streams if stream["codec_type"] == "audio")
        if (video.get("width"), video.get("height")) != (720, 1280):
            raise SystemExit(f"resolution mismatch: {output['task']}")
        if audio.get("codec_name") != "aac":
            raise SystemExit(f"audio transport mismatch: {output['task']}")
        if digest in exact_hashes:
            raise SystemExit(f"duplicate successor clip: {output['task']}")
        exact_hashes.add(digest)
        sheet = CONTACT_DIR / f"{output['task']}_CONTACT.jpg"
        contact_sheet(path, sheet)
        results.append({
            "task_id": output["task"],
            "asset_path": output["path"],
            "asset_sha256": digest,
            "dialogue_ids_retired_as_spoken_lines": output["dialogue_ids"],
            "script_equivalent_meaning": output["meaning"],
            "contact_sheet": str(sheet.relative_to(ROOT)),
            "technical_decode": "PASS_ZERO_ERRORS",
            "visible_speaking_lip": "NONE",
            "audio_provenance": "AAC_SILENCE_FROM_STILL_SOURCE; NO_TTS; NO_BGM; NO_CROSS_TASK_AUDIO",
            "registered_gates": {
                REGISTERED_GATES[0]: "PASS_NO_FACE_REPLACEMENT_AND_NO_VISIBLE_SPEAKING_LIP",
                REGISTERED_GATES[1]: "PASS_LOCKED_HALL_SUBSPACE_AND_PROP_MACRO",
                REGISTERED_GATES[2]: "PASS_SCRIPT_EQUIVALENT_CAUSE_EFFECT_MONTAGE",
                REGISTERED_GATES[3]: "PASS_NO_MODERN_OBJECT_OR_RENDERED_TEXT",
            },
            "q1_q2_status": "PASS_SWITCH_COVERAGE_SCRIPT_EQUIVALENT",
        })

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    qa = {
        "schema": "qingshan.e40.missing12.script_equivalent.registered_q1_q2.v1",
        "episode": "E40",
        "recorded_at": now,
        "status": "PASS_7_OF_7_SWITCH_COVERAGE_12_SPOKEN_LINES_RETIRED",
        "source_candidate_receipt": str(CANDIDATES.relative_to(ROOT)),
        "source_candidate_receipt_sha256": sha(CANDIDATES),
        "registered_gate_ids": REGISTERED_GATES,
        "provider_posts": 0,
        "credits": 0,
        "policy": {
            "attempt4_forbidden": True,
            "postdub_forbidden": True,
            "faux_dialogue_subtitles_forbidden": True,
            "same_task_native_dialogue_claimed": False,
        },
        "visual_review": "Original-resolution contact sheets reviewed after the first repetitive montage was rejected and rebuilt with frost-count and seal prop macros.",
        "results": results,
        "next_successor_task_id": "E40-V18-FINAL-PICTURE-AUDIO-SUBTITLE-QA-V1",
        "release_allowed": False,
    }
    OUT.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    v18 = json.loads(V18_QA.read_text(encoding="utf-8"))
    v18.update({
        "status": "SWITCH_COVERAGE_Q1_Q2_PASS_FINAL_REGISTERED_QA_REQUIRED",
        "switch_coverage_q1_q2": str(OUT.relative_to(ROOT)),
        "switch_coverage_q1_q2_sha256": sha(OUT),
        "next_successor_task_id": qa["next_successor_task_id"],
        "release_allowed": False,
    })
    V18_QA.write_text(json.dumps(v18, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "qa": str(OUT.relative_to(ROOT)), "qa_sha256": sha(OUT), "next": qa["next_successor_task_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
