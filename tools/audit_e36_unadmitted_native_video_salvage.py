#!/usr/bin/env python3
"""Exhaustively score local unadmitted E36 video dialogue against transcript gaps."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa/e36_agentcut_20260730/E36_UNADMITTED_NATIVE_VIDEO_SALVAGE_AUDIT_V1.json"
SEARCH_ROOTS = [
    ROOT / "working_assets/e36_recovery_10000_20260730",
    ROOT / "working_assets/e36_autonomous_recovery_20260731",
]
TARGETS = {
    4: "换出来了！",
    5: "走——别回头！",
    10: "从不许拆——小的连字都不识几个，拆了也白拆！",
    11: "这一句，是真的。",
    12: "他自己都不知道自己是什么。",
    23: '真正的信，是"他这个人"送到了哪儿、密谍司为他动了多少兵。',
    24: "景朝每叫他递一回空信封，就是丢颗石子进水。",
    27: "拿一条活人命，当量兵的尺。",
    28: "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text).lower()


def coverage(expected: str, actual: str) -> float:
    expected_n = normalize(expected)
    actual_n = normalize(actual)
    if not expected_n:
        return 0.0
    matcher = SequenceMatcher(None, expected_n, actual_n, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return round(matched / len(expected_n), 3)


def main() -> None:
    videos = sorted({path for base in SEARCH_ROOTS for path in base.rglob("*.mp4")})
    model = WhisperModel("small", device="cpu", compute_type="int8")
    records = []
    for index, video in enumerate(videos, start=1):
        segments, info = model.transcribe(
            str(video),
            language="zh",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )
        segment_rows = [
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()}
            for seg in segments
        ]
        transcript = "".join(row["text"] for row in segment_rows)
        scores = [
            {
                "line": line,
                "canonical": canonical,
                "coverage": coverage(canonical, transcript),
                "normalized_exact": normalize(canonical) == normalize(transcript),
            }
            for line, canonical in TARGETS.items()
        ]
        scores.sort(key=lambda item: (-item["coverage"], item["line"]))
        records.append(
            {
                "index": index,
                "media": str(video.relative_to(ROOT)),
                "media_sha256": sha256(video),
                "detected_language": info.language,
                "language_probability": round(info.language_probability, 4),
                "duration": round(info.duration, 3),
                "transcript": transcript,
                "segments": segment_rows,
                "top_matches": scores[:3],
            }
        )
        print(f"[{index}/{len(videos)}] {video.name}: {transcript}", flush=True)

    hits = []
    for record in records:
        for match in record["top_matches"]:
            if match["coverage"] >= 0.35:
                hits.append(
                    {
                        "line": match["line"],
                        "coverage": match["coverage"],
                        "normalized_exact": match["normalized_exact"],
                        "media": record["media"],
                        "media_sha256": record["media_sha256"],
                        "transcript": record["transcript"],
                    }
                )
    hits.sort(key=lambda item: (item["line"], -item["coverage"], item["media"]))
    exact_lines = sorted({hit["line"] for hit in hits if hit["normalized_exact"]})
    payload = {
        "schema": "qingshan.e36.unadmitted_native_video_salvage_audit.v1",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-908",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "method": "faster-whisper-small beam5 VAD source-native audio scan over every local MP4 in the two unadmitted E36 recovery roots; normalized sequence coverage is triage only and does not waive direct visual gates",
        "candidate_count": len(records),
        "target_lines": TARGETS,
        "hits_at_or_above_0p35": hits,
        "normalized_exact_lines": exact_lines,
        "records": records,
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "status": "PASS_EXHAUSTIVE_LOCAL_SCAN" if records else "FAIL_NO_CANDIDATES",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)


if __name__ == "__main__":
    main()
