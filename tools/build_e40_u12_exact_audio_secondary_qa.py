#!/usr/bin/env python3
"""Build secondary ASR evidence and the human-listen packet for E40 U12."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
WAV = ROOT / "working_assets/e40_production_20260809/u12_dia010_exact_audio_v1/E40-U12-DIA010.wav"
OUT = ROOT / "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_SECONDARY_ASR_AND_HUMAN_LISTEN_PACKET_V1.json"
TEXT = "调令上的印，是您的旧印。"
EXPECTED_SHA = "36e1ab9a6955d1b821346b572f5b5a731253b406bb72d920bb8c98708d07e842"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def decode(model: WhisperModel, **options: object) -> dict[str, object]:
    segments, _ = model.transcribe(str(WAV), language="zh", **options)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    return {"options": options, "transcript": transcript, "similarity": round(similarity, 4), "pass_exact": similarity == 1.0}


def main() -> int:
    if sha(WAV) != EXPECTED_SHA:
        raise SystemExit("BOUND_WAV_SHA_MISMATCH")
    model = WhisperModel("small", device="cpu", compute_type="int8", download_root="/Users/rogerwu/.cache/faster-whisper", local_files_only=True)
    rows = [
        decode(model, vad_filter=True, beam_size=5),
        decode(model, vad_filter=False, beam_size=5),
        decode(model, vad_filter=True, beam_size=1),
    ]
    machine_pass = all(row["pass_exact"] for row in rows)
    result = {
        "schema": "qingshan.e40.exact_audio_secondary_asr_human_listen_packet.v1",
        "status": "PASS_SECONDARY_MACHINE_QA_HUMAN_LISTEN_PACKET_READY" if machine_pass else "FAIL_SECONDARY_ASR_NO_RETRY",
        "episode": "E40",
        "unit": "U12",
        "line_id": "E40-DIA-010",
        "speaker": "陈迹",
        "expected_text": TEXT,
        "audio_absolute_path": str(WAV),
        "audio_sha256": EXPECTED_SHA,
        "secondary_unconditioned_asr": rows,
        "primary_qa": "qa/e40_production_20260809/u12_dia010_exact_audio_v1/E40_U12_DIA010_EXACT_AUDIO_QA_V1.json",
        "primary_qa_sha256": "22da9086ed789f4d4e97e56265b7ae58ed1be45546745718852fdb60b0920205",
        "human_listen_checklist": [
            "逐字听到：调令上的印，是您的旧印。不得增删、重复或吞字。",
            "听感应为20岁青年陈迹，不得漂成中年权威或播音员。",
            "声沉但克制，是证据落定的笃定，不是旁白解说或喊麦。",
            "普通话自然，旧印二字边界清楚，不得出现近音替换。",
            "源中不得有音乐、环境声、第二人声、爆音或明显合成断裂。",
            "只试听本 SHA；若不通过，保留失败且禁止重放本次 TTS 指纹。"
        ],
        "human_listen_status": "PENDING_ROGER_OR_DELEGATED_HUMAN_LISTENER",
        "agentcut_admission": "CLOSED_UNTIL_HUMAN_LISTEN_PASS_AND_FULL_LINE_MOUTH_NONVISIBLE_VIDEO_QA_PASS",
        "provider_posts": 0,
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "decodes": [{"transcript": row["transcript"], "similarity": row["similarity"]} for row in rows], "human_listen_status": result["human_listen_status"]}, ensure_ascii=False))
    return 0 if machine_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
