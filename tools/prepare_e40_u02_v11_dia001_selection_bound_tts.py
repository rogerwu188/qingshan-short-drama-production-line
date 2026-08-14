#!/usr/bin/env python3
"""Compile the zero-submit E40 U02 DIA-001 voice-selection execution package."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
BLOCKER = ROOT / "qa/e40_preproduction_20260814/u02_v11_audio_subtitle_agentcut_assembly_v1/E40_U02_V11_YUNFEI_VOICE_SELECTION_RIGHTS_BLOCKER_V1.json"
SUBTITLE_QA = ROOT / "qa/e40_production_20260814/u02_v11_subtitle_bitmap_oracles_v1/E40_U02_V11_SUBTITLE_BITMAP_ORACLES_QA_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v11_dia001_selection_bound_tts_v1/E40_U02_V11_DIA001_SELECTION_BOUND_TTS_NO_SUBMIT_PACKAGE_V1.json"
TEXT = "阿栓，在本宫手上。"
SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
BLOCKER_SHA = "3dc4247a41aadc1f93176894353b0055929b9c93270627032af181b6a4c92b3e"
SUBTITLE_QA_SHA = "41912fe2953209f4c396269323f46c6a942e4cb870f77e91f20e9d736f0339c3"
EMOTION = "表层平静克制，柔声起句、尾音放缓，威胁藏在礼貌之下；自然宫廷口吻，不得播音腔、喊戏腔或现代客服腔；逐字准确，不增删重复"
SPEED = 0.95


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
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


def fingerprint(voice_id: str) -> str:
    payload = {
        "episode": "E40",
        "unit": "U02",
        "line_id": "E40-DIA-001",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "text": TEXT,
        "voice_id": voice_id,
        "emotion": EMOTION,
        "speed": SPEED,
        "output_mp3": "working_assets/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40-U02-DIA001.mp3",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    expected = {SCRIPT: SCRIPT_SHA, MANIFEST: MANIFEST_SHA, BLOCKER: BLOCKER_SHA, SUBTITLE_QA: SUBTITLE_QA_SHA}
    hashes = {
        str(path.relative_to(ROOT)): {"expected": value, "actual": sha(path), "pass": sha(path) == value}
        for path, value in expected.items()
    }
    blocker = json.loads(BLOCKER.read_text(encoding="utf-8"))
    candidates = []
    collisions = []
    transaction_root = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40"
    for row in blocker["recommended_candidates"]:
        voice_id = row["voice_id"]
        key = f"E40-U02-DIA001-{voice_id}-EXACTLY-ONE-TTS-V1"
        transaction = transaction_root / f"{key}.json"
        output = ROOT / "working_assets/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40-U02-DIA001.mp3"
        exists = transaction.exists() or output.exists()
        if exists:
            collisions.append(key)
        candidates.append({
            "choice": row["rank"],
            "voice_id": voice_id,
            "name": row["name"],
            "style": row["style"],
            "request": {
                "endpoint": "/api/v1/generation/text-to-audio",
                "engine": "AgentCut 0.9.22 / MinMax Speech-2.8-HD",
                "text": TEXT,
                "voice_id": voice_id,
                "emotion": EMOTION,
                "speed": SPEED,
                "output_mp3": str(output.relative_to(ROOT)),
            },
            "generation_fingerprint_sha256": fingerprint(voice_id),
            "future_transaction_path": str(transaction.relative_to(ROOT)),
            "collision_free": not exists,
        })
    failures = [key for key, value in hashes.items() if not value["pass"]]
    failures.extend(f"COLLISION:{value}" for value in collisions)
    result = {
        "schema": "qingshan.e40.u02.v11.dia001.selection_bound_tts_no_submit_package.v1",
        "episode": "E40",
        "unit": "U02",
        "line_id": "E40-DIA-001",
        "status": "PASS_READY_FOR_ONE_HUMAN_SELECTION_NO_SUBMIT" if not failures else "FAIL_CLOSED_NO_SUBMIT",
        "failures": failures,
        "canonical_text": TEXT,
        "source_hashes": hashes,
        "selection_state": {
            "selected_choice": None,
            "selected_voice_id": None,
            "emotion_confirmed": False,
            "required_user_reply": "1 / 2 / 3; optional replacement emotion direction",
        },
        "candidate_request_envelopes": candidates,
        "execution_order_after_selection": [
            "persist selection-bound authorization with selected voice_id and emotion",
            "recheck canonical hashes, exact text/voice fingerprint collision and current authoritative audio price",
            "persist transaction INTENT_PERSISTED_NO_PROVIDER_POST_YET",
            "consume maximum_new_submissions=1 before the one DIA-001 provider POST",
            "bind returned task_id immediately and set maximum_new_submissions=0",
            "query exact task to terminal and classify authoritative Pay/Refund before any retry decision",
            "require commercialUseMetadata.present=true and releaseBlocked=false",
            "download once, normalize 48 kHz mono PCM, run exact-text ASR, duration/loudness/peak and human-listen QA",
            "only after DIA-001 rights/cost/QA PASS may DIA-002 receive a separate transaction",
        ],
        "rights_gate": {
            "commercialUseMetadata_present": True,
            "releaseBlocked": False,
            "fail_closed_if_metadata_absent": True,
        },
        "retry_policy": "NO_AUTOMATIC_RETRY; terminal task plus authoritative cost/refund classification plus persisted failure memory plus materially changed prompt and new authorization are all required",
        "network_actions": {"provider_post": 0, "provider_query": 0, "voice_list_get": 0, "ledger_get": 0},
        "transactions": 0,
        "credits": 0,
        "release_allowed": False,
    }
    atomic_json(OUT, result)
    print(json.dumps({"status": result["status"], "out": str(OUT), "candidates": len(candidates), "collisions": len(collisions)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
