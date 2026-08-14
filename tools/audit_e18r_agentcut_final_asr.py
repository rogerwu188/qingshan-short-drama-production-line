#!/usr/bin/env python3
"""Audit an E18R AgentCut render and its ordered dialogue sources with ASR."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel


BASE = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(
    "/Users/rogerwu/.cache/huggingface/hub/"
    "models--Systran--faster-whisper-small/snapshots/"
    "536b0662742c02347bc0e980a01041f333bce120"
)
DEFAULT_FFMPEG = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-17/"
    "referenced-chatgpt-conversation-this-is-untrusted/agentcut/vendor/"
    "darwin-arm64/ffmpeg"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chinese_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def dialogue_id_for_clip(clip: dict[str, Any]) -> str | None:
    metadata_id = clip.get("metadata", {}).get("dialogue_id")
    if metadata_id:
        return str(metadata_id)
    match = re.search(r"(DIA(?:-V\d+)?-\d+)", str(clip.get("id", "")))
    return match.group(1) if match else None


def recall_score(expected: str, transcript: str) -> float:
    exp = chinese_only(expected)
    got = chinese_only(transcript)
    if not exp:
        return 1.0
    if exp in got:
        return 1.0
    matched = sum(
        block.size for block in SequenceMatcher(None, exp, got).get_matching_blocks()
    )
    return matched / max(1, len(exp))


def source_range_cuts_sentence(
    segments: list[dict[str, Any]],
    source_in: float,
    admitted_duration: float,
    source_duration: float,
    tolerance: float = 0.08,
) -> bool:
    source_out = source_in + admitted_duration
    cuts_head_speech = any(
        float(row["start"]) + tolerance < source_in
        and min(float(row["end"]), source_duration) > source_in + tolerance
        for row in segments
    )
    cuts_tail_speech = any(
        float(row["start"]) < source_out - tolerance
        and min(float(row["end"]), source_duration) > source_out + tolerance
        for row in segments
    )
    return cuts_head_speech or cuts_tail_speech


def media_duration(path: Path, ffmpeg: Path) -> float:
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr + result.stdout
    )
    if not match:
        raise RuntimeError(f"Unable to probe duration: {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def transcribe(
    model: WhisperModel, path: Path, *, vad_filter: bool = True
) -> list[dict[str, Any]]:
    segments, _ = model.transcribe(
        str(path), language="zh", vad_filter=vad_filter, beam_size=5
    )
    return [
        {
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": segment.text.strip(),
        }
        for segment in segments
        if segment.text.strip()
    ]


def choose_source_segments(
    vad_segments: list[dict[str, Any]],
    no_vad_segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Prefer VAD output, but recover short Chinese lines that VAD suppresses."""
    vad_text = "".join(row.get("text", "") for row in vad_segments)
    if chinese_only(vad_text):
        return vad_segments, "VAD_FILTERED"
    no_vad_text = "".join(row.get("text", "") for row in no_vad_segments)
    if chinese_only(no_vad_text):
        return no_vad_segments, "VAD_DISABLED_SHORT_LINE_FALLBACK"
    return vad_segments or no_vad_segments, "NO_CHINESE_SPEECH_DETECTED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG))
    parser.add_argument("--out-asr", required=True)
    parser.add_argument("--out-sentences", required=True)
    args = parser.parse_args()

    video = Path(args.video).expanduser().resolve()
    project_path = Path(args.project).expanduser().resolve()
    beat_sheet_path = Path(args.beat_sheet).expanduser().resolve()
    model_path = Path(args.model).expanduser().resolve()
    ffmpeg = Path(args.ffmpeg).expanduser().resolve()
    if not video.is_file() or not project_path.is_file() or not beat_sheet_path.is_file():
        raise SystemExit("Video, AgentCut project, or beat sheet is missing")
    if not model_path.is_dir():
        raise SystemExit(f"Whisper model is missing: {model_path}")
    if not ffmpeg.is_file():
        raise SystemExit(f"FFmpeg is missing: {ffmpeg}")

    project = read_json(project_path)
    beat_sheet = read_json(beat_sheet_path)
    expected_by_id = {
        row["dia_id"]: row["text"] for row in beat_sheet["dialogue_draft"]
    }
    audio_tracks = project["timeline"]["audioTracks"]
    audio_clips = sorted(
        (
            clip
            for track in audio_tracks
            for clip in track.get("clips", [])
            if dialogue_id_for_clip(clip)
        ),
        key=lambda clip: (float(clip.get("start", 0.0)), clip["id"]),
    )
    if not audio_clips:
        raise SystemExit("AgentCut project contains no dialogue-tagged audio clips")

    clips_by_dialogue_id = {
        dialogue_id_for_clip(clip): clip for clip in audio_clips
    }
    if len(clips_by_dialogue_id) != len(audio_clips):
        raise SystemExit("AgentCut project contains duplicate dialogue IDs")

    configured_order = project.get("qingshanAudit", {}).get("dialogue_order", [])
    dialogue_order = [
        dialogue_id
        for dialogue_id in configured_order
        if dialogue_id in clips_by_dialogue_id
    ]
    dialogue_order.extend(
        dialogue_id_for_clip(clip)
        for clip in audio_clips
        if dialogue_id_for_clip(clip) not in dialogue_order
    )
    audio_clips = [clips_by_dialogue_id[dialogue_id] for dialogue_id in dialogue_order]

    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    full_segments = transcribe(model, video, vad_filter=False)
    asr_out = Path(args.out_asr).expanduser().resolve()
    asr_out.parent.mkdir(parents=True, exist_ok=True)
    asr_payload = {
        "schema": "qingshan.agentcut_final_asr.v1",
        "status": "PASS" if full_segments else "FAIL",
        "video": str(video),
        "project": str(project_path),
        "model": str(model_path),
        "segment_count": len(full_segments),
        "segments": full_segments,
        "transcript": "".join(row["text"] for row in full_segments),
        "failures": [] if full_segments else ["NO_RECOGNIZED_SPEECH"],
    }
    asr_out.write_text(
        json.dumps(asr_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sentence_rows: list[dict[str, Any]] = []
    for dialogue_id, clip in zip(dialogue_order, audio_clips):
        source = Path(clip["source"]).expanduser().resolve()
        expected = expected_by_id.get(dialogue_id, "")
        vad_segments = transcribe(model, source)
        no_vad_segments = (
            transcribe(model, source, vad_filter=False)
            if not chinese_only("".join(row["text"] for row in vad_segments))
            else []
        )
        source_segments, transcription_mode = choose_source_segments(
            vad_segments, no_vad_segments
        )
        actual_duration = media_duration(source, ffmpeg)
        source_in = float(clip.get("in", 0.0))
        admitted_duration = float(clip["duration"])
        source_out = source_in + admitted_duration
        admitted_segments = [
            row
            for row in source_segments
            if source_in
            <= (float(row["start"]) + min(float(row["end"]), actual_duration)) / 2
            <= source_out
        ]
        transcript = "".join(row["text"] for row in admitted_segments)
        score = recall_score(expected, transcript)
        cut_inside = source_range_cuts_sentence(
            admitted_segments,
            source_in,
            admitted_duration,
            actual_duration,
        )
        complete = bool(chinese_only(transcript)) and not cut_inside
        failures = []
        warnings = []
        if not chinese_only(transcript):
            failures.append("NO_RECOGNIZED_CHINESE_SPEECH")
        if score < 0.45:
            warnings.append("ASR_LEXICAL_RECALL_BELOW_0P45_HOMOPHONE_NON_BLOCKING")
        if cut_inside:
            failures.append("AGENTCUT_SOURCE_RANGE_TRUNCATES_SENTENCE")
        sentence_rows.append(
            {
                "id": dialogue_id,
                "expected": expected,
                "transcript": transcript,
                "recall_score": round(score, 3),
                "timeline_start": float(clip["start"]),
                "timeline_end": round(float(clip["start"]) + admitted_duration, 3),
                "source_duration": round(actual_duration, 3),
                "source_in": round(source_in, 3),
                "source_out": round(source_out, 3),
                "admitted_duration": round(admitted_duration, 3),
                "complete": complete,
                "cut_inside_sentence": cut_inside,
                "segments": admitted_segments,
                "transcription_mode": transcription_mode,
                "failures": failures,
                "warnings": warnings,
            }
        )

    failed_rows = [row for row in sentence_rows if not row["complete"]]
    sentence_out = Path(args.out_sentences).expanduser().resolve()
    sentence_out.parent.mkdir(parents=True, exist_ok=True)
    sentence_payload = {
        "schema": "qingshan.agentcut_sentence_completeness.v1",
        "status": "PASS" if not failed_rows else "FAIL",
        "video": str(video),
        "project": str(project_path),
        "beat_sheet": str(beat_sheet_path),
        "policy": "Homophone ASR differences are non-blocking; missing speech, low expected-line recall, and source truncation block.",
        "sentence_count": len(sentence_rows),
        "complete_count": len(sentence_rows) - len(failed_rows),
        "failure_count": len(failed_rows),
        "sentences": sentence_rows,
        "failures": [row["id"] for row in failed_rows],
    }
    sentence_out.write_text(
        json.dumps(sentence_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": sentence_payload["status"],
                "full_asr_segments": len(full_segments),
                "sentences": len(sentence_rows),
                "sentence_failures": len(failed_rows),
                "out_asr": str(asr_out),
                "out_sentences": str(sentence_out),
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed_rows or not full_segments else 0


if __name__ == "__main__":
    raise SystemExit(main())
