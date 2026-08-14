#!/usr/bin/env python3
"""Lock the 175-second E33 v2 release after every encoded-master gate passes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e33_v2_release_20260723"
SOURCE = ROOT / "exports/e33/v2_release_20260723/E33_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
MANIFEST = SOURCE.with_suffix(SOURCE.suffix + ".manifest.json")
PROJECT = ROOT / "configs/e33_agentcut_v2_release_asr_aligned_20260723.json"
ALIGNMENT = QA / "E33_NATIVE_SOURCE_CAPTION_ALIGNMENT_V4_VERIFIED.json"
ASR = QA / "E33_FINAL_DIALOGUE_WINDOW_ASR_V2.json"
CADENCE = QA / "E33_FINAL_FRAME_CADENCE_V1.json"
OCR = QA / "E33_FINAL_OCR_SUBTITLE_EXCLUDED_V1.json"
OCR_ADMISSION = QA / "E33_FINAL_OCR_CONDITIONAL_MACHINE_ADMISSION_V1.json"
VISUAL = QA / "E33_FINAL_MACHINE_VISUAL_REVIEW_V1.json"
BGM = QA / "E33_BGM_AUTHENTICITY_GATE_V1.json"
SHORTS = QA / "E33_YOUTUBE_SHORTS_RUNTIME_GATE_V1.json"
VIDEO_CREDIT = ROOT / "workflow/credit_reports/E33_VIDEO_CREDIT_LIMIT_GATE.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E33_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
FINAL = ROOT / "exports/e33/final_v2_native_dialogue_bgm_subtitled_nalu_motion_20260723/QINGSHAN_E33_FINAL_V2_175S.mp4"
QA_FREEZE = QA / "E33_FINAL_QA_FREEZE_V2_175S.json"
LOCK = QA / "E33_FINAL_LOCK_V2_175S.json"
RECEIPT = ROOT / "workflow/tasks/E33_FINAL_V2_175S_LOCK_AND_DELIVERY_RECEIPT_20260723.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_probe(path: Path) -> dict:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    return {
        "duration_seconds": float(payload["format"]["duration"]),
        "video_stream_count": sum(row.get("codec_type") == "video" for row in streams),
        "audio_stream_count": sum(row.get("codec_type") == "audio" for row in streams),
        "streams": streams,
    }


def main() -> int:
    required = (
        SOURCE, MANIFEST, PROJECT, ALIGNMENT, ASR, CADENCE, OCR, OCR_ADMISSION,
        VISUAL, BGM, SHORTS, VIDEO_CREDIT, BGM_CREDIT, FFPROBE,
    )
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing E33 v2 final-lock evidence: {path}")

    source_sha = sha256(SOURCE)
    manifest = load(MANIFEST)
    project = load(PROJECT)
    alignment = load(ALIGNMENT)
    asr = load(ASR)
    cadence = load(CADENCE)
    ocr = load(OCR)
    ocr_admission = load(OCR_ADMISSION)
    visual = load(VISUAL)
    bgm = load(BGM)
    shorts = load(SHORTS)
    video_credit = load(VIDEO_CREDIT)
    bgm_credit = load(BGM_CREDIT)
    probe = media_probe(SOURCE)

    if manifest.get("releaseGate", {}).get("finalSha256") != source_sha:
        raise SystemExit("render manifest SHA does not match the encoded master")
    if abs(float(manifest.get("duration", 0)) - 175.0) > 0.02 or abs(probe["duration_seconds"] - 175.0) > 0.02:
        raise SystemExit("encoded master is not the locked 175-second cut")
    if probe["video_stream_count"] != 1 or probe["audio_stream_count"] < 1:
        raise SystemExit("encoded master is missing its video or audio stream")
    if alignment.get("status") != "PASS" or alignment.get("aligned_count") != 25:
        raise SystemExit("native-source caption alignment is not 25/25 PASS")
    if asr.get("status") != "PASS" or asr.get("pass_count") != 25 or asr.get("line_count") != 25:
        raise SystemExit("final encoded dialogue is not 25/25 PASS")
    if cadence.get("status") != "PASS" or cadence.get("failures"):
        raise SystemExit("final cadence gate is not PASS")
    if visual.get("status") != "PASS" or visual.get("hardGatePassed") is not True:
        raise SystemExit("final visual review is not PASS")
    if ocr.get("status") != "FAIL" or ocr.get("critical_text_failures") != 1:
        raise SystemExit("preserved raw OCR result changed; review it again")
    if ocr_admission.get("status") != "CONDITIONAL_MACHINE_ADMISSION" or ocr_admission.get("candidate_sha256") != source_sha:
        raise SystemExit("story-prop OCR admission is missing or bound to another candidate")
    if ocr_admission.get("original_qa_mutated") is not False:
        raise SystemExit("original OCR QA must remain immutable")
    if bgm.get("status") != "PASS_LOCAL_SOURCE_AND_MIX" or bgm.get("release_eligible") is not True:
        raise SystemExit("BGM authenticity gate is not PASS")
    if bgm.get("mixed_video", {}).get("sha256") != source_sha:
        raise SystemExit("BGM gate is bound to another master")
    if shorts.get("status") != "PASS" or shorts.get("youtube_shorts_runtime_eligible") is not True:
        raise SystemExit("YouTube Shorts runtime gate is not PASS")
    if shorts.get("video_sha256") != source_sha or float(shorts.get("duration_seconds", 999)) > 179.0:
        raise SystemExit("Shorts gate is stale or over the target runtime")

    captions = [clip for track in project["timeline"]["subtitleTracks"] for clip in track.get("clips", [])]
    if len(captions) != 25 or len({row.get("dialogue_id") for row in captions}) != 25:
        raise SystemExit("burned subtitle contract is not exactly 25/25")
    outro = manifest.get("outro") or {}
    if not outro.get("present") or outro.get("brand") != "nalu_motion" or not outro.get("endsAtTimelineEnd"):
        raise SystemExit("NALU Motion outro is incomplete")
    audio = manifest.get("audioSafety", {}).get("metrics") or {}
    if audio.get("clippedSampleCount") != 0 or float(audio.get("truePeakDbtp", 99)) > -1.0:
        raise SystemExit("encoded audio safety gate failed")
    if video_credit.get("status") != "PASS" or video_credit.get("actual_charged_credits_known_total") != 3700.0:
        raise SystemExit("E33 video credit ledger is incomplete")
    if bgm_credit.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET" or bgm_credit.get("net_charged_credits") != 8:
        raise SystemExit("E33 BGM credit ledger is incomplete")

    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, FINAL)
    final_sha = sha256(FINAL)
    if final_sha != source_sha:
        raise SystemExit("final copy SHA mismatch")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    qa_freeze = {
        "schema": "qingshan.e33.final_qa_freeze.v2",
        "episode": "E33",
        "version": "V2_175S",
        "recorded_at_utc": now,
        "status": "PASS_FINAL_LOCK",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "runtime": "PASS_175S_YOUTUBE_SHORTS_READY",
        "dialogue": "PASS_25_OF_25_FINAL_ENCODED_ASR",
        "subtitles": "PASS_25_OF_25_NATIVE_SOURCE_ALIGNED_AND_BURNED",
        "audio": {"stream_present": True, **audio},
        "bgm": "PASS_ACCOUNT_GENERATED_AUTHENTIC_MIX",
        "cadence": "PASS",
        "visual": "PASS",
        "ocr": "CONDITIONAL_MACHINE_ADMISSION_INTENTIONAL_STORY_PROP_RAW_FAIL_PRESERVED",
        "outro": "PASS_NALU_MOTION_172_TO_175_SECONDS",
        "evidence": [str(ALIGNMENT), str(ASR), str(CADENCE), str(OCR), str(OCR_ADMISSION), str(VISUAL), str(BGM), str(SHORTS)],
    }
    QA_FREEZE.write_text(json.dumps(qa_freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lock = {
        "schema": "qingshan.e33.final_lock.v2",
        "episode": "E33",
        "version": "V2_175S",
        "recorded_at_utc": now,
        "status": "FINAL_LOCKED_E33_V2_175S",
        "final": str(FINAL),
        "sha256": final_sha,
        "duration_seconds": 175.0,
        "content_duration_seconds": 172.0,
        "youtube_shorts_eligible": True,
        "runtime_reason": "YOUTUBE_SHORTS_CATALOG_ELIGIBILITY_ONLY",
        "qa_freeze": str(QA_FREEZE),
        "generation_credits": {
            "video_exact": 3700,
            "bgm_exact": 8,
            "total_known_exact": 3708,
            "image": "NOT_INCLUDED_IN_THIS_VIDEO_PLUS_BGM_LEDGER"
        },
        "release_state": "READY_FOR_IMMEDIATE_ASYNC_PLATFORM_SUBMISSION",
        "s3_state": "PENDING_REMOTE_DELIVERY_RECEIPT"
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema": "qingshan.e33.final_delivery_receipt.v2",
        "episode": "E33",
        "version": "V2_175S",
        "delivery_slug": "qingshan-e33-v2-175s-native-dialogue-bgm-subtitled-nalu-motion",
        "recorded_at_utc": now,
        "status": "FINAL_LOCKED_S3_AND_PLATFORM_ASYNC",
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": 175.0,
        "ci_status": lock["status"],
        "release_status": "PENDING_PLATFORM_SUBMISSION",
        "final_lock": str(LOCK),
        "qa_freeze": str(QA_FREEZE),
        "s3_complete": False
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
