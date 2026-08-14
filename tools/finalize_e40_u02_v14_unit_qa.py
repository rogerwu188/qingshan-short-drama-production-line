#!/usr/bin/env python3
"""Finalize E40 U02 V14 local audiovisual QA with exact ASR."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v14_agentcut_rights_cleared_assembly_v1/E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_NOT_FINAL.mp4"
RENDER = ROOT / "workflow/tasks/E40_U02_V14_AGENTCUT_BITMAP_FALLBACK_RENDER_20260814.json"
QA_DIR = ROOT / "qa/e40_production_20260814/u02_v14_agentcut_rights_cleared_assembly_v1"
OUT = QA_DIR / "E40_U02_V14_FINAL_UNIT_AUDIOVISUAL_QA_V1.json"
ACCEPT = ROOT / "workflow/releases/E40_U02_V14_RIGHTS_CLEARED_AUDIOVISUAL_UNIT_ADMISSION_20260814.json"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
EXPECTED = "阿栓，在本宫手上。拿他，换景朝一个接头人。"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def norm(text: str) -> str:
    return "".join(HAN.findall(text)).lower()


def main() -> int:
    render = json.loads(RENDER.read_text(encoding="utf-8"))
    receipts = {
        "cadence": QA_DIR / "E40_U02_V14_FRAME_CADENCE_AUDIT_V1.json",
        "first_frame": QA_DIR / "E40_U02_V14_EXACT_FIRST_FRAME_GATE_V1.json",
        "full_ocr": QA_DIR / "E40_U02_V14_FULL_DURATION_OCR_AUDIT_V1.json",
        "subtitle_ocr": QA_DIR / "E40_U02_V14_SUBTITLE_SAMPLE_FRAME_OCR_AUDIT_V1.json",
        "rights": ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json",
        "audio_qa": ROOT / "qa/e40_production_20260814/u02_v13_kokoro_pace_repair_audio_candidates_v1/E40_U02_V13_KOKORO_PACE_REPAIR_MACHINE_QA_V1.json",
    }
    loaded = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in receipts.items()}
    if render.get("status") != "PASS_RENDERED_UNIT_QA_PENDING" or sha256(VIDEO) != render.get("output_sha256"):
        raise SystemExit("FAIL_CLOSED_RENDER_BINDING")
    if any(loaded[name].get("status") != "PASS" for name in ("cadence", "first_frame", "full_ocr", "subtitle_ocr")):
        raise SystemExit("FAIL_CLOSED_VISUAL_QA")
    if loaded["rights"].get("releaseBlocked") is not False or loaded["audio_qa"].get("status") != "PASS_SELECTED_RIGHTS_CLEARED_VOICE":
        raise SystemExit("FAIL_CLOSED_RIGHTS_OR_AUDIO_SELECTION")
    subtitle_texts = [row["text"] for row in loaded["subtitle_ocr"].get("recognitions", [])]
    if subtitle_texts != ["阿栓，在本宫手上。", "拿他，换景朝一个接头人。"]:
        raise SystemExit("FAIL_CLOSED_SUBTITLE_EXACT_COVERAGE")

    asr = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = asr.transcribe(
        str(VIDEO), language="zh", vad_filter=True, beam_size=5,
        initial_prompt="以下是简体中文普通话古装短剧对白。",
        hotwords=EXPECTED,
    )
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(EXPECTED), norm(transcript)).ratio()
    loud = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(VIDEO), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated_match = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    peak_match = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    integrated = float(integrated_match.group(1)) if integrated_match else None
    peak = float(peak_match.group(1)) if peak_match else None
    failures = []
    if similarity != 1.0:
        failures.append("FULL_UNIT_ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
    if integrated is None or not -22.0 <= integrated <= -14.0:
        failures.append("UNIT_LOUDNESS_OUTSIDE_MINUS22_TO_MINUS14_LUFS")
    if peak is None or peak > -1.0:
        failures.append("UNIT_TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
    status = "PASS_UNIT_AUDIOVISUAL_QA_AND_RIGHTS_ADMITTED" if not failures else "FAIL_UNIT_NOT_ADMITTED"
    payload = {
        "schema": "qingshan.e40.u02.v14.final_unit_audiovisual_qa.v1",
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha256(VIDEO),
        "expected_text": EXPECTED, "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "audio_metrics": {"integrated_lufs": integrated, "true_peak_dbfs": peak},
        "subtitle_exact_coverage": "2/2",
        "selected_voice": "zf_001",
        "voice_selection_authorization": "workflow/approvals/ROGER_E40_AUTONOMOUS_VOICE_EMOTION_SELECTION_20260814.json",
        "voice_selection_authorization_sha256": "41b78d54152998d892d72db731bc2a18ef4f2f544138e6eb46fc7a5c6e6ce05d",
        "rights_evidence": str(receipts["rights"].relative_to(ROOT)), "rights_evidence_sha256": sha256(receipts["rights"]),
        "qa_receipts": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "status": loaded[name].get("status")} for name, path in receipts.items()},
        "provider_post_count": 0, "credits": 0, "failures": failures,
        "release_scope": "U02_SOURCE_ADMISSION_ONLY_NOT_FULL_EPISODE_RELEASE",
    }
    atomic_json(OUT, payload)
    if not failures:
        atomic_json(ACCEPT, {
            "schema": "qingshan.e40.u02.v14.rights_cleared_audiovisual_unit_admission.v1",
            "status": "PASS_U02_ADMITTED_FOR_EPISODE_ASSEMBLY",
            "created_at": payload["created_at"],
            "video": payload["video"], "video_sha256": payload["video_sha256"],
            "final_unit_qa": str(OUT.relative_to(ROOT)), "final_unit_qa_sha256": sha256(OUT),
            "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
            "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
            "dialogue_coverage": "2/2", "rights_clear": True,
            "next_action": "Bind admitted U02 SHA into the episode-level assembly inventory and run the remaining-unit coverage gap audit.",
        })
    print(json.dumps({"status": status, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "lufs": integrated, "peak": peak, "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
