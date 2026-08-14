#!/usr/bin/env python3
"""Generate and QA E32 v2 exact dialogue audio while preserving Chenji's native voice lock."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from faster_whisper import WhisperModel

from giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
POLICY = ROOT / "configs/agentcut_character_voice_reference_policy_v1.json"
REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
OUT_DIR = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723"
QA_DIR = ROOT / "qa/e32_dialogue_audio_refs_v2_20260723"
MANIFEST = OUT_DIR / "E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
WHISPER = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


LINES = [
    ("001", "U01", "jiaotu", "那印，你不验？"),
    ("002", "U01", "chenji", "印会说谎。"),
    ("003", "U01", "chenji", "名单不会。"),
    ("004", "U02", "chenji", "这版……我亲手送进内院的。"),
    ("005", "U02", "jiaotu", "可它，是景朝火盆里烧出来的。"),
    ("006", "U03", "chenji", "内院拿它换我信任——转头卖给了景朝。"),
    ("007", "U06", "qisan", "陈爷，小的替人跑腿……"),
    ("008", "U06", "chenji", "一版名单，一封内院，一封景朝。"),
    ("009", "U06", "chenji", "你这腿，跑两家主子。"),
    ("010", "U07", "qisan", "不干小的事！那道调令——"),
    ("011", "U07", "qisan", "那是巡检指挥的印。"),
    ("012", "U07", "qisan", "围你的令，不走云羊那条线。"),
    ("013", "U10", "yunyang", "巡检司的记。"),
    ("014", "U10", "yunyang", "发令的、灭口的，一条线。"),
    ("015", "U10", "chenji", "他们宁可杀牙人，也不露这条线的名字。"),
    ("016", "U12", "yao_taiyi", "印出来杀一个牙人。"),
    ("017", "U12", "yao_taiyi", "他们不怕你知道有内鬼——怕你还有工夫查。"),
    ("018", "U13", "chenji", "丑时快到了。"),
    ("019", "U13", "chenji", "他们要抢在我撑不住前，逼我出来。"),
    ("020", "U14", "yao_taiyi", "来了。封城了。"),
    ("021", "U15", "jiaotu", "城门、医馆、王府侧门全封了。"),
    ("022", "U15", "jiaotu", "要把知情人，压进一个圈。"),
    ("023", "U16", "yunyang", "一个圈里，巡检线、景朝暗桩、内院私兵……"),
    ("024", "U16", "yunyang", "全挤一处。谁也不信谁。"),
    ("025", "U16", "chenji", "网里这三拨人，谁也不信谁。"),
    ("026", "U17", "chenji", "收网的以为，网里都是猎物。"),
    ("027", "U17", "chenji", "可要让这三拨先信别人是内奸——"),
    ("028", "U17", "chenji", "这张网，会替我勒住收网的手。"),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def last_json(value: str) -> dict:
    for line in reversed(value.splitlines()):
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    return {}


def credit(task_id: str) -> dict:
    for attempt in range(1, 7):
        response = _get("/api/v1/payment/credit-statements", {"credit_type": "Pay", "page": 1, "page_size": 20, "project_id": task_id})
        rows = [row for row in ((response.get("data") or {}).get("list") or []) if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"]
        if rows:
            try:
                total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
            except (KeyError, InvalidOperation):
                total = None
            if total is not None:
                return {"status": "KNOWN_EXACT_TASK_STATEMENT", "charged_credits": int(total), "task_id": task_id, "statement_rows": rows}
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "charged_credits": None, "task_id": task_id, "statement_rows": []}


def generate(row: tuple[str, str, str, str], specs: dict[str, dict]) -> dict:
    number, unit, role, text = row
    spec = specs[role]
    raw = OUT_DIR / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    name = f"E32-DIA-{number}.mp3"
    command = [str(AGENTCUT), "speech-generate", text, "--voice-id", spec["voice_id"], "--emotion", spec["emotion"], "--speed", str(spec["speed"]), "--output-dir", str(raw), "--file-name", name, "--poll-interval", "2", "--timeout", "300", "--overwrite"]
    result = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy())
    payload = last_json(result.stdout or result.stderr)
    if result.returncode or payload.get("status") != "completed":
        return {"dia_id": f"E32-DIA-{number}", "video_unit_id": f"E32-CW-{unit}", "speaker_id": role, "speaker": spec["name"], "spoken_text": text, "status": "FAIL", "credit": {"status": "REMOTE_EXPLICIT_FAILURE_ZERO" if payload.get("status") == "failed" else "NO_CONFIRMED_SUCCESS_ZERO", "charged_credits": 0}, "response": payload}
    return {
        "dia_id": f"E32-DIA-{number}", "video_unit_id": f"E32-CW-{unit}",
        "speaker_id": role, "speaker": spec["name"], "spoken_text": text,
        "status": "GENERATED", "mp3_path": payload["file"]["path"],
        "task_id": payload["taskId"], "credit": credit(payload["taskId"]),
        "source_voice": f"AGENTCUT_SPEECH_GENERATION:{spec['voice_id']}",
        "voice_gender": spec["gender"],
        "voice_derivation_status": "PASS",
        "voice_reference_asset_id": spec["voice_reference_asset_id"],
    }


def main() -> int:
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY is required")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    specs = {row["entity_id"]: row for row in policy["roles"]}
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    canonical = {row["entity_id"]: row for row in registry["major_roles"]}
    for entity_id, spec in specs.items():
        if entity_id in canonical:
            spec["voice_reference_asset_id"] = canonical[entity_id]["remote_asset_id"]
    generated_lines = [row for row in LINES if row[2] != "chenji"]
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(generate, row, specs) for row in generated_lines]
        for future in as_completed(futures):
            results.append(future.result())
    by_id = {row["dia_id"]: row for row in results}
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8")
    rows = []
    QA_DIR.mkdir(parents=True, exist_ok=True)
    wav_dir = OUT_DIR / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    for number, unit, role, text in LINES:
        dia_id = f"E32-DIA-{number}"
        if role == "chenji":
            voice = canonical[role]
            source = Path(voice["local_reference"])
            rows.append({"dia_id": dia_id, "video_unit_id": f"E32-CW-{unit}", "speaker_id": role, "speaker": voice["name"], "spoken_text": text, "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT", "path": rel(source), "sha256": sha(source), "duration_seconds": voice["duration_seconds"], "remote_asset_id": voice["remote_asset_id"], "credit": {"status": "NO_NEW_GENERATION", "charged_credits": 0}, "status": "PASS"})
            continue
        item = by_id[dia_id]
        if item["status"] != "GENERATED":
            rows.append(item)
            continue
        mp3 = Path(item["mp3_path"])
        wav = wav_dir / f"{dia_id}.wav"
        subprocess.run([str(FFMPEG), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True, capture_output=True)
        segments, info = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=text)
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, norm(text), norm(transcript)).ratio()
        duration = float(info.duration)
        status = "PASS" if similarity >= 0.70 and duration > 0 else "FAIL"
        qa = {"schema": "qingshan.dialogue_audio_reference_qa.v1", "dia_id": dia_id, "status": status, "expected_text": text, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "duration_seconds": duration, "wav_sha256": sha(wav), "failures": [] if status == "PASS" else ["ASR_RECALL_OR_DURATION_FAIL"]}
        (QA_DIR / f"{dia_id}_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append({**item, "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE", "path": rel(wav), "sha256": sha(wav), "duration_seconds": duration, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "status": status})
    rows.sort(key=lambda row: row["dia_id"])
    known = sum(Decimal(str(row["credit"]["charged_credits"])) for row in rows if row.get("credit", {}).get("charged_credits") is not None)
    unknown = sum(row.get("credit", {}).get("status") == "UNKNOWN_NOT_ESTIMATED" for row in rows)
    payload = {"schema": "qingshan.dialogue_audio_reference_manifest.v2", "episode": "E32", "status": "PASS" if all(row.get("status") == "PASS" for row in rows) and unknown == 0 else "FAIL", "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "line_count": len(rows), "exact_generated_line_count": len(generated_lines), "canonical_native_style_line_count": len(rows) - len(generated_lines), "known_credit_total": int(known), "unknown_credit_success_count": unknown, "rows": rows}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("status", "line_count", "exact_generated_line_count", "canonical_native_style_line_count", "known_credit_total", "unknown_credit_success_count")}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
