#!/usr/bin/env python3
"""Lock the E35 v2 release only after every encoded-master gate passes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e35_v1_release_20260723"
SOURCE = ROOT / "exports/e35/v2_release_20260724/E35_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
MANIFEST = SOURCE.with_suffix(SOURCE.suffix + ".manifest.json")
PROJECT = ROOT / "configs/e35_agentcut_v2_release_20260724.json"
ASR = QA / "E35_FINAL_DIALOGUE_WINDOW_ASR_V3.json"
CADENCE = QA / "E35_FINAL_FRAME_CADENCE_V3.json"
OCR = QA / "E35_FINAL_OCR_SUBTITLE_EXCLUDED_V1.json"
OCR_ADMISSION = QA / "E35_FINAL_OCR_CONDITIONAL_MACHINE_ADMISSION_V1.json"
VISUAL = QA / "E35_FINAL_MACHINE_VISUAL_REVIEW_V1.json"
VISUAL_RELEASE = QA / "E35_FINAL_MACHINE_VISUAL_RELEASE_REVIEW_V1.json"
BGM = QA / "E35_FINAL_BGM_AUTHENTICITY_AND_MIX_GATE_RAW_V1.json"
SHORTS = QA / "E35_YOUTUBE_SHORTS_RUNTIME_GATE_V1.json"
AGENTCUT_RELEASE = QA / "E35_AGENTCUT_RELEASE_VALIDATE_RAW_V1.json"
VIDEO_CREDIT = ROOT / "workflow/credit_reports/E35_VIDEO_CREDIT_LIMIT_GATE.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E35_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
FINAL = ROOT / "exports/e35/final_v2_native_dialogue_bgm_subtitled_nalu_motion_20260724/QINGSHAN_E35_FINAL_V2_172_416S.mp4"
QA_FREEZE = QA / "E35_FINAL_QA_FREEZE_V2_172_416S.json"
LOCK = QA / "E35_FINAL_LOCK_V2_172_416S.json"
RECEIPT = ROOT / "workflow/tasks/E35_FINAL_V2_172_416S_LOCK_AND_DELIVERY_RECEIPT_20260724.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    return {
        "duration": float(payload["format"]["duration"]),
        "video": [row for row in streams if row.get("codec_type") == "video"],
        "audio": [row for row in streams if row.get("codec_type") == "audio"],
    }


def main() -> int:
    required = (SOURCE, MANIFEST, PROJECT, ASR, CADENCE, OCR, OCR_ADMISSION, VISUAL,
                VISUAL_RELEASE, BGM, SHORTS, AGENTCUT_RELEASE, VIDEO_CREDIT, BGM_CREDIT, FFPROBE)
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing E35 final-lock evidence: {path}")

    source_sha = sha256(SOURCE)
    manifest, project, asr = load(MANIFEST), load(PROJECT), load(ASR)
    cadence, ocr, ocr_admission = load(CADENCE), load(OCR), load(OCR_ADMISSION)
    visual, visual_release, bgm = load(VISUAL), load(VISUAL_RELEASE), load(BGM)
    shorts, agentcut_release = load(SHORTS), load(AGENTCUT_RELEASE)
    video_credit, bgm_credit, media = load(VIDEO_CREDIT), load(BGM_CREDIT), probe(SOURCE)

    if manifest.get("releaseGate", {}).get("finalSha256") != source_sha:
        raise SystemExit("render manifest is not bound to this encoded master")
    if agentcut_release.get("status") != "PASS" or agentcut_release.get("hardGatePassed") is not True:
        raise SystemExit("AgentCut release validation did not pass")
    if agentcut_release.get("finalSha256") != source_sha or agentcut_release.get("reviewFinalSha256") != source_sha:
        raise SystemExit("AgentCut release validation is bound to another master")
    if not media["video"] or not media["audio"] or media["video"][0].get("width") != 720 or media["video"][0].get("height") != 1280:
        raise SystemExit("encoded master is missing 720x1280 video or audio")
    if not 172.35 <= media["duration"] <= 172.50:
        raise SystemExit("encoded master runtime drifted")
    if asr.get("status") != "PASS" or asr.get("pass_count") != 47 or asr.get("line_count") != 47 or asr.get("video_sha256") != source_sha:
        raise SystemExit("final encoded dialogue is not 47/47 PASS")
    if cadence.get("status") != "PASS" or cadence.get("failures"):
        raise SystemExit("final cadence gate is not PASS")
    if visual.get("status") != "PASS" or visual.get("hardGatePassed") is not True or visual.get("media", {}).get("sha256") != source_sha:
        raise SystemExit("final visual gate is not PASS or is stale")
    if visual_release.get("status") != "PASS" or visual_release.get("media_sha256") != source_sha:
        raise SystemExit("final release review is not bound to this master")
    if ocr.get("status") != "FAIL" or ocr_admission.get("status") != "CONDITIONAL_MACHINE_ADMISSION":
        raise SystemExit("raw OCR failure or its admission evidence drifted")
    if ocr_admission.get("source_final_sha256") != source_sha or ocr_admission.get("original_failure_preserved") is not True:
        raise SystemExit("OCR admission is stale or mutates the raw failure")
    if bgm.get("status") != "PASS_LOCAL_SOURCE_AND_MIX" or bgm.get("release_eligible") is not True:
        raise SystemExit("BGM authenticity gate is not PASS")
    if bgm.get("mixed_video", {}).get("sha256") != source_sha:
        raise SystemExit("BGM gate is bound to another master")
    if shorts.get("status") != "PASS" or shorts.get("video_sha256") != source_sha or shorts.get("duration_seconds", 999) > 179:
        raise SystemExit("YouTube Shorts runtime gate is stale or failed")

    captions = [clip for track in project["timeline"]["subtitleTracks"] for clip in track.get("clips", [])]
    if len(captions) != 47 or len({row.get("dialogue_id") for row in captions}) != 47:
        raise SystemExit("burned subtitle contract is not exactly 47/47")
    outro = manifest.get("outro") or {}
    if not outro.get("present") or outro.get("brand") != "nalu_motion" or not outro.get("endsAtTimelineEnd") or abs(outro.get("duration", 0) - 3.0) > 0.01:
        raise SystemExit("NALU Motion outro is incomplete")
    audio = manifest.get("audioSafety", {}).get("metrics") or {}
    if audio.get("clippedSampleCount") != 0 or float(audio.get("truePeakDbtp", 99)) > -1.0:
        raise SystemExit("encoded audio safety gate failed")
    if video_credit.get("status") != "PASS" or video_credit.get("actual_charged_credits_known_total") != 5940.0:
        raise SystemExit("E35 video credit ledger is incomplete")
    if bgm_credit.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET" or bgm_credit.get("net_charged_credits") != 8:
        raise SystemExit("E35 BGM credit ledger is incomplete")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("final copy SHA mismatch")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    freeze = {
        "schema": "qingshan.e35.final_qa_freeze.v2", "episode": "E35", "version": "V2_172_416S",
        "recorded_at_utc": now, "status": "PASS_FINAL_LOCK", "final": str(FINAL), "final_sha256": final_sha,
        "runtime": "PASS_172_416S_YOUTUBE_SHORTS_READY", "dialogue": "PASS_47_OF_47_FINAL_ENCODED_ASR",
        "subtitles": "PASS_47_OF_47_BURNED", "audio": {"stream_present": True, **audio},
        "bgm": "PASS_AGENTCUT_ACCOUNT_GENERATED_AUTHENTIC_MIX", "cadence": "PASS_AFTER_U22_LOCAL_REPAIR",
        "visual": "PASS", "ocr": "CONDITIONAL_MACHINE_ADMISSION_RAW_FAIL_PRESERVED",
        "outro": "PASS_NALU_MOTION_FINAL_3_SECONDS",
        "evidence": [str(ASR), str(CADENCE), str(OCR), str(OCR_ADMISSION), str(VISUAL), str(VISUAL_RELEASE), str(BGM), str(SHORTS)],
    }
    QA_FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lock = {
        "schema": "qingshan.e35.final_lock.v2", "episode": "E35", "version": "V2_172_416S",
        "recorded_at_utc": now, "status": "FINAL_LOCKED_E35_V2_172_416S", "final": str(FINAL),
        "sha256": final_sha, "duration_seconds": media["duration"], "content_duration_seconds": 169.39,
        "youtube_shorts_eligible": True, "runtime_reason": "YOUTUBE_SHORTS_CATALOG_ELIGIBILITY_ONLY",
        "qa_freeze": str(QA_FREEZE), "generation_credits": {"video_exact": 5940, "bgm_exact": 8, "video_plus_bgm_exact": 5948},
        "release_state": "READY_FOR_IMMEDIATE_ASYNC_PLATFORM_SUBMISSION", "s3_state": "PENDING_REMOTE_DELIVERY_RECEIPT",
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e35.final_delivery_receipt.v2", "episode": "E35", "version": "V2_172_416S",
        "delivery_slug": "qingshan-e35-v2-172-416s-native-dialogue-bgm-subtitled-nalu-motion",
        "recorded_at_utc": now, "status": "FINAL_LOCKED_S3_AND_PLATFORM_ASYNC", "final": str(FINAL),
        "final_sha256": final_sha, "duration_seconds": media["duration"], "ci_status": lock["status"],
        "release_status": "PENDING_PLATFORM_SUBMISSION", "final_lock": str(LOCK), "qa_freeze": str(QA_FREEZE), "s3_complete": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
