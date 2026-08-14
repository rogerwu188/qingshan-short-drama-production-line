#!/usr/bin/env python3
"""Persist U01-U07 assembly prefix and U09 parallel preproduction state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WQ = ROOT / "workflow/work_queue.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
PREFIX = ROOT / "working_assets/e40_assembly_20260814/u01_u07_parallel_prefix_v1/E40_U01_U07_LOCAL_PREVIEW_HARDCUT_720X1280_V1.mp4"
PREFIX_QA = ROOT / "qa/e40_assembly_20260814/u01_u07_parallel_prefix_v1/E40_U01_U07_LOCAL_PREFIX_MACHINE_AND_HUMAN_QA_V1.json"
U09_FRAME = ROOT / "working_assets/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_EXACT_START_FRAME_720X1280.png"
U09_HUMAN = ROOT / "qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_ORIGINAL_RES_HUMAN_QA_V1.json"
U09_OCR = ROOT / "qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_CANDIDATE_V2_OCR_AUDIT_V2.json"
U09_RECEIPT = ROOT / "qa/e40_preproduction_20260814/u09_parallel_four_mark_wipe_candidate_v1/E40_U09_PARALLEL_PREPRODUCTION_SHA_RECEIPT_V1.json"
U09_AUDIO = ROOT / "working_assets/e40_production_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40-DIA008_zm_009_speed1p08_normalized48k.wav"
U09_AUDIO_QA = ROOT / "qa/e40_production_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40_U09_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
U09_RIGHTS = ROOT / "qa/e40_preproduction_20260814/u09_parallel_kokoro_exact_audio_candidates_v1/E40_U09_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atomic_json(path: Path, payload: dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True); raise


def main() -> int:
    files = (PREFIX, PREFIX_QA, U09_FRAME, U09_HUMAN, U09_OCR, U09_RECEIPT, U09_AUDIO, U09_AUDIO_QA, U09_RIGHTS)
    for path in files:
        if not path.is_file(): raise SystemExit(f"FAIL_MISSING:{path}")
    audio_qa = json.loads(U09_AUDIO_QA.read_text(encoding="utf-8")); rights = json.loads(U09_RIGHTS.read_text(encoding="utf-8"))
    if not audio_qa.get("status", "").startswith("PASS") or rights.get("releaseBlocked") is not False: raise SystemExit("FAIL_CLOSED_U09_AUDIO")
    work = json.loads(WQ.read_text(encoding="utf-8"))
    work["latest_e40_u01_u07_assembly_prefix"] = {"status": "PASS_IMMUTABLE_PREFIX_U01_U07", "preview": rel(PREFIX), "preview_sha256": sha(PREFIX), "duration_seconds": 35.166667, "qa": rel(PREFIX_QA), "qa_sha256": sha(PREFIX_QA), "provider_posts": 0, "credits": 0, "next_action": "Append U08 only after U08 unit admission."}
    work["latest_e40_u09_parallel_preproduction"] = {"status": "PASS_FRAME_HUMAN90_OCR0_AUDIO_EXACT_RIGHTS_CLEAR_U08_TAIL_BINDING_PENDING", "canonical_line": "我一换，两个一并抹掉，线断死。", "frame": rel(U09_FRAME), "frame_sha256": sha(U09_FRAME), "human_qa": rel(U09_HUMAN), "human_qa_sha256": sha(U09_HUMAN), "ocr_qa": rel(U09_OCR), "ocr_qa_sha256": sha(U09_OCR), "asset_receipt": rel(U09_RECEIPT), "asset_receipt_sha256": sha(U09_RECEIPT), "selected_audio": rel(U09_AUDIO), "selected_audio_sha256": sha(U09_AUDIO), "audio_qa": rel(U09_AUDIO_QA), "audio_qa_sha256": sha(U09_AUDIO_QA), "rights_evidence": rel(U09_RIGHTS), "rights_evidence_sha256": sha(U09_RIGHTS), "provider_posts": 0, "credits": 0, "blocked_by": "U08_ADMITTED_TAIL_TO_U09_FRAME_CONTINUITY_COMPARISON_PENDING", "next_action": "After U08 unit admission, bind decoded tail and admit U09 frame only on continuity PASS."}
    atomic_json(WQ, work)
    moment = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(f"\n\n## E40 checkpoint {moment} — U01-U07 prefix and U09 parallel assets persisted\n\n- U01-U07 local prefix `{rel(PREFIX)}` SHA=`{sha(PREFIX)}` is 35.166667s, 720x1280/24fps with 48kHz stereo AAC, full decode PASS and admitted order unchanged.\n- U09 frame `{rel(U09_FRAME)}` SHA=`{sha(U09_FRAME)}` passed HUMAN90/OCR0 after V1 frost-topology failure memory and material rewrite. Exact DIA008 audio `{rel(U09_AUDIO)}` SHA=`{sha(U09_AUDIO)}` passed ASR=1.0, duration/loudness/peak and release-clear rights; provider posts/credits=0. Only U08 admitted-tail continuity binding remains.\n- Active chain remains U08 local render/QA; no provider submit or release.\n")
        stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_U01_U07_PREFIX_AND_U09_PREPRODUCTION_PERSISTED", "prefix_sha256": sha(PREFIX), "u09_frame_sha256": sha(U09_FRAME), "u09_audio_sha256": sha(U09_AUDIO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
