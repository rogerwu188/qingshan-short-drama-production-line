#!/usr/bin/env python3
"""Generate the CL2X-857-authorized genuinely changed source take for E36 line 10."""

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
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
TRANSCRIPT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V7.json"
PRIOR_GATE = ROOT / "qa/e36_agentcut_20260730/E36_U09_R2_LINES9_10_ROBUST_SOURCE_GATE_AND_LINE9_CLASSIFICATION_V1.json"
OUT = ROOT / "working_assets/e36_dialogue_audio_refs_20260731/u09_line10_changed_take_r3"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/u09_line10_changed_take_r3_runtime"
TASK_DIR = ROOT / "workflow/tasks"
SUMMARY = QA_DIR / "E36_U09_LINE10_GENUINELY_CHANGED_R3_SOURCE_GATE_V1.json"
RECEIPT = TASK_DIR / "E36-U09-L10-D02-CHANGED-R3_MESSENGER_EXACT_DIALOGUE_AUDIO_GENERATION_V1.json"
CONTEXT_QA = QA_DIR / "E36-U09-L10-D02-CHANGED-R3_EXACT_DIALOGUE_AUDIO_QA_V1.json"
ROBUST_QA = QA_DIR / "E36-U09-L10-D02-CHANGED-R3_UNCONDITIONED_ASR_V1.json"

SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
PRIOR_GATE_SHA = "f0121eaa4d5b903821bbc46a9ee9be5a638000deb309d1df94468816bddd2017"
SOURCE_CL2X = "CL2X-857"
MAILBOX_SHA = "b89deabacede6c3868b20ca211c5f04facaa79b28459ba57978faae420677838"
VOICE_ID = "ttv-voice-2025092218535325-mrbtpNsP"
TEXT = "从不许拆——小的连字都不识几个，拆了也白拆！"
SYNTHESIS_TEXT = "从不许拆！小的连字，都不识几个；拆了也白拆！"
SPEED = "0.90"
EMOTION = "洛城普通递信人被缚后急着自证不识字，重新录制一条完整新 take；前三字短促，随后明显放慢并逐字清楚说出小的连字都不识几个，尤其把不识和几个连贯咬准，尾句带委屈和喘息；自然中文普通话，不喊麦，不做现代播音腔"
HAN = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
T2S = OpenCC("t2s")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def norm(value: str) -> str:
    return "".join(HAN.findall(T2S.convert(value))).lower()


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
        response = _get("/api/v1/payment/credit-statements", {
            "credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id,
        })
        rows = [
            row for row in ((response.get("data") or {}).get("list") or [])
            if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"
        ]
        if rows:
            total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            return {"status": "KNOWN_EXACT_TASK_STATEMENT", "task_id": task_id,
                    "charged_credits": int(total), "statement_rows": rows, "query_attempt": attempt}
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "task_id": task_id, "charged_credits": None, "statement_rows": []}


def canonical_gate() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    transcript = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_GATE.read_text(encoding="utf-8"))
    contract = {int(row["contract_line_number"]): row for row in transcript["line_results"]}
    prior_line = next(row for row in prior["line_results"] if row["canonical_line_number"] == 10)
    checks = {
        "script_exists": SCRIPT.is_file(), "manifest_exists": MANIFEST.is_file(),
        "script_sha_locked": sha(SCRIPT) == SCRIPT_SHA,
        "manifest_matches_script": manifest.get("sha256") == sha(SCRIPT),
        "transcript_line10_exact": contract[10]["text"] == TEXT,
        "transcript_line10_unproven": not contract[10]["covered_by_bound_accepted_transcripts"],
        "prior_gate_sha_locked": sha(PRIOR_GATE) == PRIOR_GATE_SHA,
        "prior_line10_not_ready": not prior_line["eligible_for_video"],
        "requested_lexical_text_exact": norm(SYNTHESIS_TEXT) == norm(TEXT),
        "genuinely_changed_take": SYNTHESIS_TEXT != prior_line["changed_source"].get("synthesis_text", TEXT),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "script_sha256": sha(SCRIPT), "manifest_sha256": sha(MANIFEST),
            "transcript_sha256": sha(TRANSCRIPT), "prior_gate_sha256": sha(PRIOR_GATE)}


def contextual(model: WhisperModel, wav: Path, duration: float) -> dict:
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5,
                                   initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    status = "PASS" if similarity >= 0.80 and 2.5 <= duration <= 8.0 else "FAIL"
    return {"schema": "qingshan.dialogue_audio_reference_qa.v1", "episode": "E36",
            "canonical_line_number": 10, "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA, "status": status, "expected_text": TEXT,
            "synthesis_text": SYNTHESIS_TEXT, "asr_transcript": transcript,
            "asr_similarity": round(similarity, 4), "duration_seconds": duration,
            "wav_path": rel(wav), "wav_sha256": sha(wav),
            "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"]}


def robust(models: dict[str, WhisperModel], wav: Path) -> dict:
    rows = []
    for model_name, model in models.items():
        for beam in (1, 5, 8):
            for vad in (False, True):
                segments, _ = model.transcribe(str(wav), language="zh", beam_size=beam,
                                               best_of=max(beam, 1), temperature=0.0,
                                               condition_on_previous_text=False, vad_filter=vad)
                transcript = "".join(segment.text.strip() for segment in segments)
                rows.append({"model": model_name, "beam_size": beam, "vad_filter": vad,
                             "transcript": transcript, "normalized_exact": norm(transcript) == norm(TEXT)})
    exact = sum(row["normalized_exact"] for row in rows)
    return {"schema": "qingshan.dialogue_audio_unconditioned_asr.v1", "episode": "E36",
            "canonical_line_number": 10, "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA, "expected_text": TEXT,
            "han_script_normalization": "OpenCC t2s", "wav_path": rel(wav),
            "wav_sha256": sha(wav), "exact_count": exact, "decode_count": len(rows),
            "status": "PASS_ROBUST_EXACT_12_OF_12" if exact == 12 else "FAIL_ROBUST_NOT_EXACT_PRESERVED",
            "eligible_as_exact_pronunciation_reference": exact == 12,
            "unique_transcripts": sorted({row["transcript"] for row in rows}), "results": rows,
            "new_qa_credits": 0}


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    OUT.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    gate = canonical_gate()
    if gate["status"] != "PASS":
        SUMMARY.write_text(json.dumps({"status": "FAIL_CANONICAL_PREFLIGHT_ZERO_CHARGE",
                                       "canonical_gate": gate, "charged_credits": 0},
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2

    mp3 = OUT / "E36-U09-L10-D02-CHANGED-R3.mp3"
    wav = OUT / "E36-U09-L10-D02-CHANGED-R3.wav"
    started = datetime.now(timezone.utc).isoformat()
    command = [str(AGENTCUT), "speech-generate", SYNTHESIS_TEXT, "--voice-id", VOICE_ID,
               "--emotion", EMOTION, "--speed", SPEED, "--output-dir", str(OUT),
               "--file-name", mp3.name, "--poll-interval", "2", "--timeout", "300", "--overwrite"]
    completed = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    provider = last_json(completed.stdout or completed.stderr)
    if completed.returncode or provider.get("status") != "completed":
        payload = {"schema": "qingshan.exact_dialogue_audio_generation.v1", "status": "FAIL",
                   "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA,
                   "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                   "spoken_text": TEXT, "synthesis_text": SYNTHESIS_TEXT, "response": provider,
                   "stderr": completed.stderr[-4000:],
                   "credit": {"status": "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0}}
        RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2

    mp3 = Path(provider["file"]["path"])
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                    "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
    probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
                           check=True, capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    models = {name: WhisperModel(name, device="cpu", compute_type="int8") for name in ("base", "small")}
    context = contextual(models["small"], wav, duration)
    CONTEXT_QA.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    robust_result = robust(models, wav)
    ROBUST_QA.write_text(json.dumps(robust_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    credit = exact_credit(provider["taskId"])
    receipt = {"schema": "qingshan.exact_dialogue_audio_generation.v1", "status": context["status"],
               "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA,
               "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
               "task_id": provider["taskId"], "voice_id": VOICE_ID, "spoken_text": TEXT,
               "synthesis_text": SYNTHESIS_TEXT, "speed": SPEED, "emotion": EMOTION,
               "material_change": "NEW_PROVIDER_TASK_PLUS_NEW_PUNCTUATION_PROSODY_SPEED_TAKE_NOT_LOCAL_RECUT",
               "mp3_path": rel(mp3), "mp3_sha256": sha(mp3), "wav_path": rel(wav),
               "wav_sha256": sha(wav), "contextual_qa_path": rel(CONTEXT_QA),
               "contextual_qa_sha256": sha(CONTEXT_QA), "robust_qa_path": rel(ROBUST_QA),
               "robust_qa_sha256": sha(ROBUST_QA), "credit": credit}
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    charged = int(credit.get("charged_credits") or 0)
    summary = {"schema": "qingshan.e36.u09_line10_genuinely_changed_source_gate.v1",
               "episode": "E36", "canonical_line_number": 10, "source_cl2x": SOURCE_CL2X,
               "source_mailbox_sha256": MAILBOX_SHA,
               "status": "PASS_ROBUST_SOURCE_READY_FOR_VIDEO_PREPRODUCTION" if robust_result["exact_count"] == 12 else "FAIL_ROBUST_SOURCE_NOT_EXACT_PRESERVED_NO_VIDEO",
               "canonical_gate": gate, "generation_receipt_path": rel(RECEIPT),
               "generation_receipt_sha256": sha(RECEIPT), "task_id": provider["taskId"],
               "wav_path": rel(wav), "wav_sha256": sha(wav), "duration_seconds": duration,
               "contextual_qa_path": rel(CONTEXT_QA), "contextual_qa_sha256": sha(CONTEXT_QA),
               "contextual_similarity": context["asr_similarity"], "robust_qa_path": rel(ROBUST_QA),
               "robust_qa_sha256": sha(ROBUST_QA), "robust_exact_count": robust_result["exact_count"],
               "robust_decode_count": robust_result["decode_count"],
               "video_submission_allowed": robust_result["exact_count"] == 12,
               "video_tasks_submitted": 0, "exact_new_credits": charged,
               "episode_exact_source_attributable_total": 7966 + charged, "episode_cap": 10000,
               "generation_calls_after": 102, "active_remote_tasks": 0,
               "gate_results": {"canonical_script_manifest": "PASS_EXACT", "normalized_paid_text": "PASS_CANONICAL_EQUIVALENT",
                                "genuinely_changed_take": "PASS_NEW_PROVIDER_TASK_NOT_LOCAL_RECUT",
                                "exact_credit": credit["status"], "contextual_source": context["status"],
                                "robust_source": robust_result["status"], "video": "BLOCKED_ZERO_TASKS" if robust_result["exact_count"] != 12 else "READY_FOR_PREPRODUCTION_ONLY"},
               "blocked_by": None if robust_result["exact_count"] == 12 else "Line10 genuinely changed source remains below robust12/12; preserve FAIL and submit no video.",
               "next_action": "If robust12/12, build line10 split-video preproduction immediately; otherwise preserve FAIL and apply CL2X-857 terminal disposition without unchanged replay."}
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "task_id": provider["taskId"],
                      "charged_credits": charged, "robust_exact_count": robust_result["exact_count"],
                      "summary": rel(SUMMARY), "summary_sha256": sha(SUMMARY)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
