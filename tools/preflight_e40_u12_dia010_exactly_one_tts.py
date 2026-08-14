#!/usr/bin/env python3
"""Fail-closed preflight for E40 U12 DIA010's one authorized TTS call."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
NO_SUBMIT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_dia010_exact_audio_preflight_v1/E40_U12_DIA010_EXACT_AUDIO_SOURCE_AND_VOICE_BINDING_NO_SUBMIT_MANIFEST_V1.json"
VOICE_REF = ROOT / "libraries/audio/voice_refs/native_multimodal_20260709/VOICE-陈迹-古装/e09_shot01_chenji_native_voice_ref.wav"
WORK_QUEUE = ROOT / "workflow/work_queue.json"
OUT = ROOT / "qa/e40_preproduction_20260808/E40_U12_DIA010_EXACTLY_ONE_TTS_AUTHORIZED_PREFLIGHT_V1.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
TRANSACTION = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U12-DIA010-EXACTLY-ONE-TTS-V1.json"
OUTPUT_MP3 = ROOT / "working_assets/e40_production_20260809/u12_dia010_exact_audio_v1/E40-U12-DIA010.mp3"
TEXT = "调令上的印，是您的旧印。"
VOICE_ID = "clone_20251022_092746_158444"
EMOTION = "20岁陈迹隔帘掷出旧印拓影后声沉，冷静克制、证据落定的笃定；自然普通话，非旁白腔；逐字准确，不增删重复"
SPEED = 1.0
EXPECTED = {
    SCRIPT: "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
    CANONICAL_MANIFEST: "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    NO_SUBMIT: "aa7ea88ff99dcde43cf23699499d04620fb8ae2fdf272a69a9ad83e042417c2b",
    VOICE_REF: "c63b69430a0fe29af41529759846fb3645935668b1a3aaa0ba237c6dae916eb5",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def recursive_rows(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        rows.append(value)
        for child in value.values():
            rows.extend(recursive_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(recursive_rows(child))
    return rows


def main() -> int:
    ensure_giggle_api_key()
    failures: list[str] = []
    hashes = {}
    for path, expected in EXPECTED.items():
        actual = sha(path) if path.is_file() else None
        hashes[str(path.relative_to(ROOT))] = {"expected": expected, "actual": actual, "pass": actual == expected}
        if actual != expected:
            failures.append(f"SHA_MISMATCH:{path.relative_to(ROOT)}")

    canonical = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    canonical_text_pass = TEXT in SCRIPT.read_text(encoding="utf-8")
    if canonical.get("episode") != "E40" or canonical.get("sha256") != EXPECTED[SCRIPT] or not canonical_text_pass:
        failures.append("CANONICAL_EXACT_LINE_OR_MANIFEST_BINDING_FAIL")

    voices_result = subprocess.run(
        [str(AGENTCUT), "speech-voices"], capture_output=True, text=True, check=True
    )
    voices_payload = json.loads(voices_result.stdout.splitlines()[-1])
    voice_matches = [row for row in voices_payload.get("voices", []) if row.get("voiceId") == VOICE_ID]
    if len(voice_matches) != 1 or voice_matches[0].get("age") != "youth" or voice_matches[0].get("gender") != "male":
        failures.append("CURRENT_PROVIDER_VOICE_BINDING_FAIL")

    response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": 1, "page_size": 100, "project_id": ""},
    )
    rows = (response.get("data") or {}).get("list") or []
    recent_audio = [
        row for row in rows
        if row.get("event_type") == "Pay"
        and row.get("event_description") == "SingleGenerateAudio"
        and row.get("model_name") == "MinMax-Speech-2.8-hd"
    ]
    recent_audio.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    price = None
    if recent_audio:
        try:
            price = abs(Decimal(str(recent_audio[0].get("credit"))))
        except InvalidOperation:
            price = None
    if price is None or price > Decimal("2"):
        failures.append("CURRENT_AUTHORITATIVE_AUDIO_PRICE_ABOVE_2_OR_UNKNOWN")

    work_queue = json.loads(WORK_QUEUE.read_text(encoding="utf-8"))
    credits = work_queue.get("e40_credits") or {}
    current_net = int(credits.get("net") or 0)
    cap = int(credits.get("cap") or 0)
    projected_net = current_net + int(price or 0)
    if cap <= 0 or projected_net > cap:
        failures.append("E40_STANDING_CAP_FAIL")

    collisions = []
    for path in (ROOT / "workflow/tasks").rglob("*.json"):
        if path == TRANSACTION:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in recursive_rows(payload):
            candidate_text = row.get("spoken_text") or row.get("text")
            candidate_voice = row.get("voice_id") or row.get("voiceId")
            if candidate_text == TEXT and candidate_voice == VOICE_ID:
                collisions.append(str(path.relative_to(ROOT)))
                break
    if collisions or TRANSACTION.exists() or OUTPUT_MP3.exists():
        failures.append("LOCAL_EXACT_TEXT_VOICE_FINGERPRINT_COLLISION_OR_OUTPUT_EXISTS")

    fingerprint_payload = {
        "episode": "E40",
        "unit": "U12",
        "line_id": "E40-DIA-010",
        "canonical_script_sha256": EXPECTED[SCRIPT],
        "canonical_manifest_sha256": EXPECTED[CANONICAL_MANIFEST],
        "no_submit_manifest_sha256": EXPECTED[NO_SUBMIT],
        "text": TEXT,
        "voice_id": VOICE_ID,
        "emotion": EMOTION,
        "speed": SPEED,
        "output_mp3": str(OUTPUT_MP3.relative_to(ROOT)),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    result = {
        "schema": "qingshan.e40.u12.dia010.exactly_one_tts.authorized_preflight.v1",
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": failures,
        "canonical_exact_line_pass": canonical_text_pass,
        "hashes": hashes,
        "current_provider_voice": voice_matches,
        "current_authoritative_price": {
            "event_description": "SingleGenerateAudio",
            "model_name": "MinMax-Speech-2.8-hd",
            "credits": int(price) if price is not None else None,
            "latest_statement": recent_audio[0] if recent_audio else None,
            "pass_le_2": price is not None and price <= Decimal("2"),
        },
        "e40_credits_before": credits,
        "projected_net_after": projected_net,
        "collision_scan": {
            "exact_text_voice_matches": sorted(set(collisions)),
            "transaction_exists": TRANSACTION.exists(),
            "output_exists": OUTPUT_MP3.exists(),
            "pass_zero": not collisions and not TRANSACTION.exists() and not OUTPUT_MP3.exists(),
        },
        "generation_fingerprint_payload": fingerprint_payload,
        "generation_fingerprint_sha256": fingerprint,
        "network_actions": {"voice_list_get": 1, "ledger_get": 1, "provider_post": 0},
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    atomic_json(OUT, result)
    print(json.dumps({"status": result["status"], "fingerprint": fingerprint, "price": result["current_authoritative_price"]["credits"], "collisions": len(collisions)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
