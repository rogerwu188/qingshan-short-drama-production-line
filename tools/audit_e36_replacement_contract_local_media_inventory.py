#!/usr/bin/env python3
"""Audit untouched local E36 production videos for the remaining dialogue contracts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_REPLACEMENT_CONTRACT_LOCAL_MEDIA_INVENTORY_QA_V1.json"
FFMPEG = Path("/Users/rogerwu/Documents/Codex/2026-07-17/referenced-chatgpt-conversation-this-is-untrusted/agentcut-0.9.7/agentcut/vendor/darwin-arm64/ffmpeg")
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
TARGETS = {
    11: "这一句，是真的。",
    12: "他自己都不知道自己是什么。",
    23: "真正的信，是他这个人送到了哪儿、密谍司为他动了多少兵。",
    24: "景朝每叫他递一回空信封，就是丢颗石子进水。",
    27: "拿一条活人命，当量兵的尺。",
    28: "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text).lower()


def coverage(expected: str, actual: str) -> float:
    expected_n, actual_n = normalize(expected), normalize(actual)
    if not expected_n:
        return 0.0
    matched = sum(block.size for block in SequenceMatcher(None, expected_n, actual_n, autojunk=False).get_matching_blocks())
    return round(matched / len(expected_n), 3)


def inspect_media(path: Path) -> dict:
    probe = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration,size", "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    decode = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(path), "-map", "0:v?", "-map", "0:a?", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "media": str(path.relative_to(ROOT)),
        "media_sha256": digest(path),
        "probe_exit": probe.returncode,
        "probe": json.loads(probe.stdout) if probe.returncode == 0 and probe.stdout else None,
        "full_av_decode_exit": decode.returncode,
        "full_av_decode_error": decode.stderr.strip(),
    }


def main() -> None:
    all_videos = sorted(SOURCE_ROOT.glob("*.mp4"))
    by_sha: dict[str, Path] = {}
    aliases: dict[str, list[str]] = {}
    for video in all_videos:
        sha = digest(video)
        by_sha.setdefault(sha, video)
        aliases.setdefault(sha, []).append(str(video.relative_to(ROOT)))

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(inspect_media, by_sha.values()))

    model = WhisperModel("base", device="cpu", compute_type="int8")
    for index, record in enumerate(records, 1):
        path = ROOT / record["media"]
        segments, info = model.transcribe(
            str(path), language="zh", beam_size=5, vad_filter=True,
            condition_on_previous_text=False, temperature=0.0,
        )
        rows = [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()} for s in segments]
        transcript = "".join(row["text"] for row in rows)
        matches = []
        for line, canonical in TARGETS.items():
            score = coverage(canonical, transcript)
            matches.append({
                "line": line,
                "coverage": score,
                "normalized_exact": normalize(canonical) == normalize(transcript),
            })
        matches.sort(key=lambda row: (-row["coverage"], row["line"]))
        record.update({
            "aliases": aliases[record["media_sha256"]],
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 4),
            "asr_transcript": transcript,
            "asr_segments": rows,
            "target_matches": matches,
            "classification": "NO_EXACT_REPLACEMENT_DIALOGUE",
        })
        if any(row["normalized_exact"] for row in matches):
            record["classification"] = "EXACT_TEXT_CANDIDATE_REQUIRES_IDENTITY_RIGHTS_LIPSYNC_REVIEW"
        print(f"[{index}/{len(records)}] {path.name}: {transcript}", flush=True)

    exact = [r for r in records if r["classification"].startswith("EXACT_TEXT")]
    decode_failures = [r["media"] for r in records if r["full_av_decode_exit"] != 0]
    payload = {
        "schema": "qingshan.e36.replacement_contract_local_media_inventory.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-924",
        "source_mailbox_sha256": "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest_file_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "scope": "Previously unscanned original video_repair_v2_outputs corpus; SHA-deduplicated. Recovery-root leaders and the eleven ambient assets already reviewed by prior audits are excluded.",
        "replacement_contracts": {
            "JiaoTu11_12": "rights-cleared model-native female JiaoTu, visible native Mandarin lips/breath/expression, canonical lines11/12",
            "Chenji23_24": "age17 Chenji, visible native Mandarin lips/breath/expression, canonical lines23/24",
            "JiaoTu27_Chenji28": "rights-cleared model-native female JiaoTu line27 plus age17 Chenji line28, visible native Mandarin lips/breath/expression",
        },
        "method": "SHA inventory, ffprobe, full A/V decode, and unprompted faster-whisper-base beam5 VAD over each distinct original production MP4. ASR exactness is triage only and cannot waive identity, rights, lipsync, timing, or direct visual gates.",
        "files_seen": len(all_videos),
        "distinct_media": len(records),
        "decode_failures": decode_failures,
        "exact_text_candidates": [{"media": r["media"], "sha256": r["media_sha256"]} for r in exact],
        "records": records,
        "gate_results": {
            "media_inventory": "PASS_SHA_DEDUPLICATED",
            "full_av_decode": "PASS_ZERO_FAILURES" if not decode_failures else "FAIL_PRESERVED",
            "exact_native_dialogue_candidate": "PASS_CANDIDATES_REQUIRE_REVIEW" if exact else "FAIL_ZERO_CANDIDATES",
            "rights_cleared_JiaoTu": "FAIL_ZERO_LOCAL_EXACT_CANDIDATES" if not exact else "HOLD_REVIEW_REQUIRED",
            "transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30",
            "promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "limit": 10000, "headroom": 24},
        "status": "PASS_NEW_LOCAL_CORPUS_EXHAUSTED_NO_ADMISSION" if not exact and not decode_failures else "REVIEW_REQUIRED",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
