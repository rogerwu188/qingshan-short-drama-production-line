#!/usr/bin/env python3
"""Integrate zero-cost U15/U25 preproduction receipts into shared handoff state."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

R = Path(__file__).resolve().parents[1]
W = R / "workflow/work_queue.json"
X = R / "workflow/CODEX_TO_CLAUDE.md"
U15R = R / "qa/e40_preproduction_20260814/u15_parallel_chenji_raising_gaze_curtain_unsettled_v1/E40_U15_PARALLEL_PREPRODUCTION_SHA_RECEIPT_V1.json"
U25Q = R / "qa/e40_preproduction_20260814/u25_parallel_kokoro_exact_audio_candidates_v1/E40_U25_PARALLEL_FAST_ONLY_SPLIT_PROMPT_PRECOMPILE_QA_V1.json"
U25A = R / "working_assets/e40_production_20260814/u25_parallel_kokoro_exact_audio_candidates_v1/E40-DIA018_zm_009_speed0p92_normalized48k.wav"
U25AQ = R / "qa/e40_production_20260814/u25_parallel_kokoro_exact_audio_candidates_v1/E40_U25_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
U25S = R / "qa/e40_production_20260814/u25_parallel_kokoro_exact_audio_candidates_v1/E40_U25_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(R))


def atomic_json(path: Path, payload: dict) -> None:
    blob = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    for path in (W, X, U15R, U25Q, U25A, U25AQ, U25S):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    u15 = json.loads(U15R.read_text())
    u25q = json.loads(U25Q.read_text())
    u25aq = json.loads(U25AQ.read_text())
    u25s = json.loads(U25S.read_text())
    if not u15.get("status", "").startswith("PASS_U15"):
        raise SystemExit("FAIL_U15_GATE")
    if not u25q.get("status", "").startswith("PASS_") or u25aq.get("status") != "PASS_MACHINE_SELECTION":
        raise SystemExit("FAIL_U25_GATE")
    selected = u25aq.get("selected") or {}
    if selected.get("normalized_sha256") != sha(U25A) or selected.get("asr_similarity") != 1.0:
        raise SystemExit("FAIL_U25_AUDIO_BINDING")
    if u25s.get("selected", {}).get("normalized_sha256") != sha(U25A):
        raise SystemExit("FAIL_U25_SELECTION_RECEIPT")
    work = json.loads(W.read_text())
    frame = u15["admitted_candidate"]["exact_start_frame_720p"]
    work["latest_e40_u15_parallel_preproduction"] = {
        "status": u15["status"],
        "frame": frame["path"],
        "frame_sha256": frame["sha256"],
        "human_score": u15["admitted_candidate"]["human_qa"]["score"],
        "ocr_visible_text_count": u15["admitted_candidate"]["ocr_qa"]["recognitions"],
        "preproduction_receipt": rel(U15R),
        "preproduction_receipt_sha256": sha(U15R),
        "dialogue_audio": {
            key: {"text": value["text"], "path": value["path"], "sha256": value["sha256"]}
            for key, value in u15["ordered_exact_audio"].items() if key.startswith("E40-DIA-")
        },
        "provider_posts": 0,
        "credits": 0,
        "next_action": "Hold for U14 accepted tail; then continuity-bind and render U15 without bypassing exact dialogue gates."
    }
    work["latest_e40_u25_parallel_preproduction"] = {
        "status": u25q["status"],
        "canonical_line": u25s["exact_text"],
        "selected_reference_audio": rel(U25A),
        "selected_reference_audio_sha256": sha(U25A),
        "audio_asr_similarity": selected["asr_similarity"],
        "audio_duration_seconds": selected["audio_metrics"]["duration_seconds"],
        "audio_qa": rel(U25AQ),
        "audio_qa_sha256": sha(U25AQ),
        "selected_audio_receipt": rel(U25S),
        "selected_audio_receipt_sha256": sha(U25S),
        "prompt_precompile_qa": rel(U25Q),
        "prompt_precompile_qa_sha256": sha(U25Q),
        "u25a_start_frame": u25q["u25a"]["start_frame"],
        "u25a_prompt": u25q["u25a"]["prompt_path"],
        "u25a_prompt_sha256": u25q["u25a"]["prompt_sha256"],
        "u25b_prompt": u25q["u25b"]["prompt_path"],
        "u25b_prompt_sha256": u25q["u25b"]["prompt_sha256"],
        "blocked_by": ["U25A_ACCEPTED_NATIVE_EXACT_LINE_VIDEO", "U25B_START_FRAME"],
        "provider_posts": 0,
        "credits": 0,
        "next_action": "Resolve U25B start frame locally; do not submit U25A until predecessor chain and durable transaction gates authorize it."
    }
    atomic_json(W, work)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with X.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n\n## E40 checkpoint {now} — parallel U15 and U25 preproduction integrated\n\n"
            f"- U15 exact start frame SHA=`{frame['sha256']}` is HUMAN92/OCR0 and binds both ordered exact dialogue references; receipt SHA=`{sha(U15R)}`. U15 remains dependency-held behind an accepted U14 tail.\n"
            f"- U25 reference audio `{rel(U25A)}` SHA=`{sha(U25A)}` is exact ASR=1.0 and exactly 4.500s. Fast-only U25A/U25B split prompts passed policy QA SHA=`{sha(U25Q)}`; U25A has an admitted HUMAN88/OCR0 start frame, while U25B remains fail-closed on its missing start frame.\n"
            "- These were zero-credit local preparations only: provider posts=0, credits=0, no release.\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"status": "PASS_U15_U25_PARALLEL_PREPRODUCTION_INTEGRATED", "u15_receipt_sha256": sha(U15R), "u25_prompt_qa_sha256": sha(U25Q)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
