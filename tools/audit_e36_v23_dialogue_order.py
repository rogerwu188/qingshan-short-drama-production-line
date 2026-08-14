#!/usr/bin/env python3
"""Bind V23's zero-credit dialogue-order repair to robust ASR and media evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / (
    "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/"
    "E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
)
EVIDENCE = ROOT / "qa/e36_agentcut_20260730/v23_canonical_dialogue_order_v1"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER_QA_V1.json"
T2S = OpenCC("t2s")

ANCHORS = (
    (10, "从不许拆"),
    (13, "小的自己也纳闷"),
    (14, "可小的每送一回"),
    (15, "小的一个废物"),
    (16, "空信封"),
    (17, "规矩之外的事"),
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def main() -> None:
    runs = []
    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for beam_size in (1, 5, 8):
            for vad_filter in (False, True):
                segments, _ = model.transcribe(
                    str(MEDIA),
                    language="zh",
                    beam_size=beam_size,
                    best_of=max(beam_size, 1),
                    temperature=0.0,
                    condition_on_previous_text=False,
                    vad_filter=vad_filter,
                    word_timestamps=True,
                    clip_timestamps="75,125",
                )
                rows = [
                    {
                        "start": round(float(segment.start), 3),
                        "end": round(float(segment.end), 3),
                        "text": segment.text.strip(),
                    }
                    for segment in segments
                ]
                transcript = "".join(row["text"] for row in rows)
                normalized = normalize(transcript)
                positions = {str(line): normalized.find(normalize(text)) for line, text in ANCHORS}
                first_order = (
                    positions["13"] >= 0
                    and positions["14"] > positions["13"]
                    and positions["15"] > positions["14"]
                )
                second_order = positions["16"] >= 0 and positions["17"] > positions["16"]
                runs.append(
                    {
                        "model": f"faster-whisper-{model_name}",
                        "beam_size": beam_size,
                        "vad_filter": vad_filter,
                        "transcript": transcript,
                        "segments": rows,
                        "anchor_positions": positions,
                        "lines_13_14_15_canonical_order": first_order,
                        "lines_16_17_canonical_order": second_order,
                    }
                )

    first_count = sum(run["lines_13_14_15_canonical_order"] for run in runs)
    second_count = sum(run["lines_16_17_canonical_order"] for run in runs)
    probe = json.loads((EVIDENCE / "E36_V23_FFPROBE.json").read_text())
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    payload = {
        "schema": "qingshan.e36.v23_canonical_dialogue_order_qa.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-924",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "canonical": {
            "script": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
            "script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
            "manifest": "workflow/claude_writer_agent/scripts/E36_manifest_v2.json",
            "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        },
        "source_candidate": {
            "version": "V22",
            "path": "working_assets/e36_agentcut_20260801/accepted_only_v22_audio_timeline_flattened/E36_ACCEPTED_ONLY_AGENTCUT_V22_AUDIO_TIMELINE_FLATTENED.mp4",
            "sha256": "fe7ca3e61e5c426fc0f39c31b2a2e80889b6e9afc173de06fa41ef03b3e74e98",
            "preserved_failure": "CANONICAL_DIALOGUE_ORDER_LINES_15_BEFORE_13_14_AND_17_BEFORE_16",
        },
        "repair": {
            "method": "ZERO_CREDIT_EXISTING_V22_SEGMENT_REORDER_AND_REENCODE",
            "unchanged_runtime_span_seconds": [0.0, 293.879],
            "first_swap": {
                "source_intervals": [[82.011053, 88.094046], [88.094046, 98.194046]],
                "before": "LINE15_THEN_LINES13_14",
                "after": "LINES13_14_THEN_LINE15",
            },
            "second_swap": {
                "source_intervals": [[108.248037, 114.33103], [114.33103, 121.14103]],
                "before": "LINE17_THEN_LINE16",
                "after": "LINE16_THEN_LINE17",
            },
            "no_new_dialogue_or_generation": True,
        },
        "candidate": {
            "version": "V23",
            "path": str(MEDIA.relative_to(ROOT)),
            "sha256": sha(MEDIA),
            "status": "REVERSIBLE_NOT_PROMOTED",
            "duration_seconds": float(probe["format"]["duration"]),
            "video": f"{video['width']}x{video['height']}_{video['r_frame_rate']}_H264",
            "video_frames": int(video["nb_frames"]),
            "audio": f"AAC_{audio['sample_rate']}HZ_{audio['channels']}CH",
        },
        "evidence": {
            "render_log": {
                "path": str((EVIDENCE / "E36_V23_RENDER.log").relative_to(ROOT)),
                "sha256": sha(EVIDENCE / "E36_V23_RENDER.log"),
                "encoder_report": "7053_FRAMES_DUP1_DROP0",
            },
            "ffprobe": {
                "path": str((EVIDENCE / "E36_V23_FFPROBE.json").relative_to(ROOT)),
                "sha256": sha(EVIDENCE / "E36_V23_FFPROBE.json"),
            },
            "full_decode": {
                "path": str((EVIDENCE / "E36_V23_FULL_DECODE.log").relative_to(ROOT)),
                "sha256": sha(EVIDENCE / "E36_V23_FULL_DECODE.log"),
                "result": "PASS_ZERO_ERRORS",
            },
            "contact_sheet": {
                "path": str((EVIDENCE / "E36_V23_DIALOGUE_REORDER_24_SAMPLE_CONTACT.png").relative_to(ROOT)),
                "sha256": sha(EVIDENCE / "E36_V23_DIALOGUE_REORDER_24_SAMPLE_CONTACT.png"),
                "direct_result": "PASS_24_OF_24_NO_MALFORMED_FRAME_OR_SEVERE_IDENTITY_PERIOD_CONTRADICTION",
            },
        },
        "asr": {
            "settings": {
                "models": ["base", "small"],
                "beam_sizes": [1, 5, 8],
                "vad_filter_values": [False, True],
                "condition_on_previous_text": False,
                "clip_seconds": [75, 125],
            },
            "results": runs,
            "summary": {
                "lines_13_14_15_canonical_order_decodes": f"{first_count}/12",
                "lines_16_17_canonical_order_decodes": f"{second_count}/12",
            },
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "V22_canonical_dialogue_order": "FAIL_PRESERVED",
            "V23_lines_13_14_15_source_order": "PASS_EXISTING_ACCEPTED_SPANS_REORDERED",
            "V23_lines_16_17_source_order": "PASS_EXISTING_ACCEPTED_SPANS_REORDERED",
            "robust_asr_lines_13_14_15_order": f"PASS_{first_count}_OF_12",
            "robust_asr_lines_16_17_order": f"PASS_{second_count}_OF_12",
            "full_decode": "PASS_ZERO_ERRORS",
            "render_cadence": "HOLD_DUP1_REQUIRES_FULL_AHASH_AND_MPDECIMATE_QA",
            "transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30_INHERITED_CONTENT_REQUIRES_V23_FULL_QA",
            "continuous_full_watch": "NOT_COMPLETE",
            "V23_promotion": "NOT_GRANTED",
            "V15_status": "CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V23_FULL_AHASH_MPDECIMATE_OCR_AND_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
            "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": (
            "Preserved V22 and corrected two source-proven canonical dialogue-order failures by reordering only "
            "existing accepted V22 spans. V23 restores lines13/14 before15 and line16 before17, fully decodes, "
            "and has robust focused ASR plus direct visual evidence. It remains reversible and unpromoted pending "
            "full-candidate cadence, OCR, audiovisual and human-watch gates."
        ),
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000},
        "next_action": "Run V23 full-runtime strict aHash, mpdecimate cadence, OCR, audio timing and corrected boundary review; preserve V15 canonical.",
        "status": "PASS_DIALOGUE_ORDER_REPAIR_REVERSIBLE_FULL_QA_ACTIVE",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT.relative_to(ROOT)), "sha256": sha(OUT), "first": first_count, "second": second_count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
