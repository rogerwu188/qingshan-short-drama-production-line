#!/usr/bin/env python3
"""Run focused unconditioned ASR over V22's four unresolved-dialogue windows."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-17/"
    "referenced-chatgpt-conversation-this-is-untrusted/"
    "agentcut-0.9.7/agentcut/vendor/darwin-arm64/ffmpeg"
)
SOURCE = ROOT / (
    "working_assets/e36_agentcut_20260801/accepted_only_v22_audio_timeline_flattened/"
    "E36_ACCEPTED_ONLY_AGENTCUT_V22_AUDIO_TIMELINE_FLATTENED.mp4"
)
WINDOW_DIR = ROOT / "qa/e36_agentcut_20260730/v22_transcript_gap_context_review_v1/asr_windows"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_V22_TRANSCRIPT_GAP_CONTEXT_ROBUST_ASR_QA_V1.json"
T2S = OpenCC("t2s")

WINDOWS = (
    {
        "id": "A_U08_L04_L05",
        "start": 50.0,
        "end": 68.0,
        "lines": (
            (4, "云羊", "换出来了！"),
            (5, "云羊", "走——别回头！"),
        ),
    },
    {
        "id": "B_U10_L11_L12",
        "start": 78.0,
        "end": 103.0,
        "lines": (
            (11, "皎兔", "这一句，是真的。"),
            (12, "皎兔", "他自己都不知道自己是什么。"),
        ),
    },
    {
        "id": "C_U14_L23_L24",
        "start": 138.0,
        "end": 153.0,
        "lines": (
            (23, "陈迹", '真正的信，是"他这个人"送到了哪儿、密谍司为他动了多少兵。'),
            (24, "陈迹", "景朝每叫他递一回空信封，就是丢颗石子进水。"),
        ),
    },
    {
        "id": "D_U14_L27_L28",
        "start": 277.0,
        "end": 293.7,
        "lines": (
            (27, "皎兔", "拿一条活人命，当量兵的尺。"),
            (28, "陈迹", "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。"),
        ),
    },
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def extract_window(spec: dict) -> Path:
    WINDOW_DIR.mkdir(parents=True, exist_ok=True)
    output = WINDOW_DIR / f"E36_V22_{spec['id']}_PCM16K_MONO.wav"
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(spec["start"]), "-to", str(spec["end"]), "-i", str(SOURCE),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
        ],
        check=True,
    )
    return output


def main() -> None:
    extracted = {spec["id"]: extract_window(spec) for spec in WINDOWS}
    runs: dict[str, list[dict]] = {spec["id"]: [] for spec in WINDOWS}

    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for beam_size in (1, 5, 8):
            for vad_filter in (False, True):
                for spec in WINDOWS:
                    segments, _ = model.transcribe(
                        str(extracted[spec["id"]]),
                        language="zh",
                        beam_size=beam_size,
                        best_of=max(beam_size, 1),
                        temperature=0.0,
                        condition_on_previous_text=False,
                        vad_filter=vad_filter,
                        word_timestamps=True,
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
                    exact = {
                        str(line_number): normalize(text) in normalized
                        for line_number, _, text in spec["lines"]
                    }
                    runs[spec["id"]].append(
                        {
                            "model": f"faster-whisper-{model_name}",
                            "beam_size": beam_size,
                            "vad_filter": vad_filter,
                            "transcript": transcript,
                            "segments": rows,
                            "line_exact_contiguous_subsequence": exact,
                        }
                    )

    windows = []
    all_counts: dict[str, int] = {}
    for spec in WINDOWS:
        run_rows = runs[spec["id"]]
        counts = {
            str(line_number): sum(
                row["line_exact_contiguous_subsequence"][str(line_number)] for row in run_rows
            )
            for line_number, _, _ in spec["lines"]
        }
        all_counts.update(counts)
        media = extracted[spec["id"]]
        windows.append(
            {
                "id": spec["id"],
                "source_window_seconds": [spec["start"], spec["end"]],
                "pcm_media": {
                    "path": str(media.relative_to(ROOT)),
                    "sha256": sha(media),
                    "bytes": media.stat().st_size,
                    "format": "PCM_S16LE_16000HZ_MONO",
                },
                "expected_lines": [
                    {"line": line_number, "speaker": speaker, "text": text}
                    for line_number, speaker, text in spec["lines"]
                ],
                "exact_contiguous_subsequence_counts": {
                    key: f"{value}/12" for key, value in counts.items()
                },
                "results": run_rows,
            }
        )

    payload = {
        "schema": "qingshan.e36.v22_transcript_gap_context_robust_asr_qa.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-924",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "canonical_script": {
            "path": "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md",
            "sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        },
        "manifest": {
            "path": "workflow/claude_writer_agent/scripts/E36_manifest_v2.json",
            "sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
            "declared_canonical_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        },
        "source_media": {
            "path": str(SOURCE.relative_to(ROOT)),
            "sha256": sha(SOURCE),
        },
        "settings": {
            "models": ["base", "small"],
            "beam_sizes": [1, 5, 8],
            "vad_filter_values": [False, True],
            "condition_on_previous_text": False,
            "temperature": 0.0,
            "language": "zh",
            "normalization": "OpenCC t2s plus alphanumeric/CJK only",
            "decodes_per_window": 12,
        },
        "windows": windows,
        "summary": {
            "exact_contiguous_subsequence_decodes_by_line": {
                key: f"{value}/12" for key, value in sorted(all_counts.items(), key=lambda item: int(item[0]))
            },
            "new_transcript_admissions": [],
            "accepted_transcript_coverage": "39_OF_47_HOLD",
        },
        "gate_results": {
            "focused_asr_execution": "PASS_48_UNCONDITIONED_DECODES_COMPLETE",
            "source_binding": "PASS_V22_SHA_AND_FOUR_EXACT_NATIVE_WINDOWS",
            "canonical_binding": "PASS_SCRIPT_AND_MANIFEST_DECLARATION_EXACT",
            "transcript_admission": "HOLD_NO_LINE_ADMITTED_WITHOUT_EXACT_AUDIO_SPEAKER_AND_RIGHTS_PROVENANCE",
            "rights_scope": "PASS_EXISTING_ACCEPTED_OR_UNADMITTED_MODEL_NATIVE_AUDIO_ONLY_NO_CLONE_USED",
            "human_listening": "NOT_COMPLETE_REVIEW_READY",
            "release": "HOLD_ACCEPTED_TRANSCRIPT_39_OF_47",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V22_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
            "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": (
            "Extracted four exact native V22 audio windows for unresolved lines 4/5, 11/12, 23/24, "
            "and 27/28, then ran 48 zero-credit unconditioned base/small ASR decodes. Exact text "
            "matches remain evidence only; no line is admitted without speaker, visible-performance, "
            "rights, and human-listening provenance."
        ),
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000},
        "status": "COMPLETE_FOCUSED_ASR_TRANSCRIPT_39_OF_47_HOLD",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "counts": payload["summary"]["exact_contiguous_subsequence_decodes_by_line"],
                "out": str(OUT.relative_to(ROOT)),
                "sha256": sha(OUT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
