#!/usr/bin/env python3
"""Generate and context-check the two canonical messenger lines for E36 U09-R2."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from faster_whisper import WhisperModel
from giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
TRANSCRIPT_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V6.json"
REPAIR_MODE = os.environ.get("E36_U09_R2_PROSODY_REPAIR_MODE") == "1"
OUT = ROOT / (
    "working_assets/e36_dialogue_audio_refs_20260730/u09_r2_prosody_r2"
    if REPAIR_MODE else "working_assets/e36_dialogue_audio_refs_20260730/u09_r2"
)
QA_DIR = ROOT / "qa/e36_agentcut_20260730/u09_r2_video_runtime"
RECEIPT_DIR = ROOT / "workflow/tasks"
SUMMARY = QA_DIR / (
    "E36_U09_R2_MESSENGER_PROSODY_R2_SOURCE_GENERATION_SUMMARY_V1.json"
    if REPAIR_MODE else "E36_U09_R2_MESSENGER_EXACT_DIALOGUE_SOURCE_GENERATION_SUMMARY_V1.json"
)
VOICE_ID = "ttv-voice-2025092218535325-mrbtpNsP"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
EXPECTED_SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
SOURCE_CL2X = "CL2X-849"
SOURCE_MAILBOX_SHA = "c9c25b32b2a9af7c597fb026aacdf3a4fd6f3c20a7074ac64bd8028216173942"

LINES = [
    {
        "line_number": 9,
        "dia_id": "E36-U09-R2-D01",
        "text": "有人隔月塞给小的一只信封，叫送到茶棚、桥头，搁下就走。",
        "synthesis_text": "有人隔月塞给小的一只信封。叫送到茶棚、桥头，搁下——就走。" if REPAIR_MODE else "有人隔月塞给小的一只信封，叫送到茶棚、桥头，搁下就走。",
        "speed": "0.96" if REPAIR_MODE else "1.12",
        "emotion": "洛城普通递信人被缚初审，分两口气慢慢交代差事，在茶棚和搁下处咬字清楚，畏缩发紧，自然中文普通话，不喊麦，不做现代播音腔" if REPAIR_MODE else "洛城普通递信人被缚初审，哆嗦着交代差事，气息发紧但每字清楚，自然中文普通话，不喊麦，不做现代播音腔",
        "duration_min": 3.0,
        "duration_max": 8.0,
    },
    {
        "line_number": 10,
        "dia_id": "E36-U09-R2-D02",
        "text": "从不许拆——小的连字都不识几个，拆了也白拆！",
        "synthesis_text": "从不许拆。小的连字，都不识几个。拆了，也白拆！" if REPAIR_MODE else "从不许拆——小的连字都不识几个，拆了也白拆！",
        "speed": "0.98" if REPAIR_MODE else "1.10",
        "emotion": "洛城普通递信人分句自证不识字，在不识几个处放慢咬字，畏缩发紧、尾句急促，自然中文普通话，不喊麦，不做现代播音腔" if REPAIR_MODE else "洛城普通递信人慌忙自证不识字，畏缩发紧、尾句急促，自然中文普通话，每字清楚，不喊麦，不做现代播音腔",
        "duration_min": 2.5,
        "duration_max": 7.0,
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def last_json(value: str) -> dict:
    for line in reversed(value.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def exact_credit(task_id: str) -> dict:
    for attempt in range(1, 8):
        response = _get(
            "/api/v1/payment/credit-statements",
            {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id},
        )
        rows = [
            row
            for row in ((response.get("data") or {}).get("list") or [])
            if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"
        ]
        if rows:
            total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            return {
                "status": "KNOWN_EXACT_TASK_STATEMENT",
                "task_id": task_id,
                "charged_credits": int(total),
                "statement_rows": rows,
                "query_attempt": attempt,
            }
        time.sleep(2)
    return {
        "status": "UNKNOWN_NOT_ESTIMATED",
        "task_id": task_id,
        "charged_credits": None,
        "statement_rows": [],
    }


def canonical_gate() -> dict:
    script_sha = sha(SCRIPT)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(TRANSCRIPT_AUDIT.read_text(encoding="utf-8"))
    contract = {int(row["contract_line_number"]): row for row in audit["line_results"]}
    checks = {
        "script_exists": SCRIPT.is_file(),
        "manifest_exists": MANIFEST.is_file(),
        "script_sha_locked": script_sha == EXPECTED_SCRIPT_SHA,
        "manifest_field_matches_script": manifest.get("sha256") == script_sha,
        "line9_exact": contract[9]["text"] == LINES[0]["text"],
        "line10_exact": contract[10]["text"] == LINES[1]["text"],
        "line9_currently_unproven": not contract[9]["covered_by_bound_accepted_transcripts"],
        "line10_currently_unproven": not contract[10]["covered_by_bound_accepted_transcripts"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "script_sha256": script_sha,
        "manifest_sha256": sha(MANIFEST),
        "transcript_audit_sha256": sha(TRANSCRIPT_AUDIT),
    }


def generate(row: dict, model: WhisperModel) -> dict:
    stem = f'{row["dia_id"]}-PROSODY-R2' if REPAIR_MODE else row["dia_id"]
    mp3 = OUT / f"{stem}.mp3"
    wav = OUT / f"{stem}.wav"
    qa_path = QA_DIR / f"{stem}_EXACT_DIALOGUE_AUDIO_QA_V1.json"
    receipt_path = RECEIPT_DIR / f"{stem}_MESSENGER_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
    started = datetime.now(timezone.utc).isoformat()
    command = [
        str(AGENTCUT),
        "speech-generate",
        row["synthesis_text"],
        "--voice-id",
        VOICE_ID,
        "--emotion",
        row["emotion"],
        "--speed",
        row["speed"],
        "--output-dir",
        str(OUT),
        "--file-name",
        mp3.name,
        "--poll-interval",
        "2",
        "--timeout",
        "300",
        "--overwrite",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(completed.stdout or completed.stderr)
    if completed.returncode or payload.get("status") != "completed":
        result = {
            "schema": "qingshan.exact_dialogue_audio_generation.v1",
            "status": "FAIL",
            "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": SOURCE_MAILBOX_SHA,
            "started_at_utc": started,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "spoken_text": row["text"],
            "synthesis_text": row["synthesis_text"],
            "response": payload,
            "stderr": completed.stderr[-4000:],
            "credit": {"status": "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0},
        }
        receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    mp3 = Path(payload["file"]["path"])
    subprocess.run(
        [str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(probe.stdout.strip())
    segments, _ = model.transcribe(
        str(wav), language="zh", vad_filter=True, beam_size=5,
        initial_prompt="以下是简体中文普通话对白。", hotwords=row["text"],
    )
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(row["text"]), norm(transcript)).ratio()
    status = "PASS" if similarity >= 0.80 and row["duration_min"] <= duration <= row["duration_max"] else "FAIL"
    credit = exact_credit(payload["taskId"])
    qa = {
        "schema": "qingshan.dialogue_audio_reference_qa.v1",
        "episode": "E36",
        "unit_id": "U09-R2",
        "dia_id": stem,
        "canonical_line_number": row["line_number"],
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": SOURCE_MAILBOX_SHA,
        "status": status,
        "expected_text": row["text"],
        "synthesis_text": row["synthesis_text"],
        "asr_transcript": transcript,
        "asr_similarity": round(similarity, 4),
        "duration_seconds": duration,
        "wav_path": rel(wav),
        "wav_sha256": sha(wav),
        "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"],
    }
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema": "qingshan.exact_dialogue_audio_generation.v1",
        "status": status,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": SOURCE_MAILBOX_SHA,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": payload["taskId"],
        "voice_id": VOICE_ID,
        "spoken_text": row["text"],
        "synthesis_text": row["synthesis_text"],
        "mp3_path": rel(mp3),
        "mp3_sha256": sha(mp3),
        "wav_path": rel(wav),
        "wav_sha256": sha(wav),
        "qa_receipt": rel(qa_path),
        "qa_receipt_sha256": sha(qa_path),
        "credit": credit,
    }
    receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    OUT.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    gate = canonical_gate()
    if gate["status"] != "PASS":
        SUMMARY.write_text(json.dumps({"status": "FAIL_CANONICAL_GATE", "canonical_gate": gate}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    results = []
    for row in LINES:
        result = generate(row, model)
        results.append(result)
        if result["status"] != "PASS" or result["credit"]["status"] != "KNOWN_EXACT_TASK_STATEMENT":
            break
    charged = sum(int(row["credit"].get("charged_credits") or 0) for row in results)
    status = "PASS_CONTEXTUAL_SOURCE_READY_FOR_ROBUST_ASR" if len(results) == len(LINES) and all(row["status"] == "PASS" for row in results) else "FAIL_PRESERVED"
    summary = {
        "schema": "qingshan.e36.u09_r2.messenger_exact_dialogue_source_generation.v1",
        "episode": "E36",
        "unit_id": "U09-R2",
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": SOURCE_MAILBOX_SHA,
        "status": status,
        "canonical_gate": gate,
        "results": results,
        "exact_new_credits": charged,
        "episode_total_after_generation": (7843 if REPAIR_MODE else 7839) + charged,
        "episode_cap": 10000,
        "video_submission_allowed": False,
        "changed_input_mode": "PROSODY_SPLIT_R2" if REPAIR_MODE else "ORIGINAL_SOURCE_V1",
        "blocked_by": "ROBUST_OPENCC_NORMALIZED_UNCONDITIONED_ASR_REQUIRED_FOR_BOTH_LINES_BEFORE_VIDEO",
        "next_action": "Run independent unconditioned base+small x beam1/5/8 x VAD off/on QA for each WAV. Build no video package unless both return exact12/12.",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "exact_new_credits": charged, "summary": rel(SUMMARY), "summary_sha256": sha(SUMMARY)}, ensure_ascii=False))
    return 0 if status == "PASS_CONTEXTUAL_SOURCE_READY_FOR_ROBUST_ASR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
