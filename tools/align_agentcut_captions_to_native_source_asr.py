#!/usr/bin/env python3
"""Align AgentCut burn-in captions to speech already present in source videos."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel

from tools.portable_runtime import resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]


def chinese(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def flatten_timed_characters(segments: list) -> tuple[str, list[tuple[float, float]]]:
    chars = []
    times = []
    for segment in segments:
        words = list(segment.words or [])
        if not words:
            words = [type("Word", (), {"word": segment.text, "start": segment.start, "end": segment.end})()]
        for word in words:
            token = chinese(word.word or "")
            if not token:
                continue
            start = float(word.start if word.start is not None else segment.start)
            end = float(word.end if word.end is not None else segment.end)
            step = max(0.02, (end - start) / len(token))
            for index, char in enumerate(token):
                chars.append(char)
                times.append((start + step * index, min(end, start + step * (index + 1))))
    return "".join(chars), times


def map_expected_to_actual(expected: str, actual: str) -> dict[int, int]:
    mapping = {}
    for block in SequenceMatcher(None, expected, actual).get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    return mapping


def line_ranges(expected_rows: list[dict], actual: str, times: list[tuple[float, float]], source_duration: float) -> list[dict]:
    expected_all = "".join(chinese(row["spoken_text"]) for row in expected_rows)
    mapping = map_expected_to_actual(expected_all, actual)
    speech_start = times[0][0] if times else 0.25
    speech_end = times[-1][1] if times else max(0.5, source_duration - 0.25)
    total_chars = max(1, len(expected_all))
    rows = []
    expected_cursor = 0
    fallback_cursor = speech_start
    for row in expected_rows:
        line = chinese(row["spoken_text"])
        line_start_index = expected_cursor
        line_end_index = expected_cursor + len(line)
        actual_indices = [mapping[index] for index in range(line_start_index, line_end_index) if index in mapping]
        recall = len(actual_indices) / max(1, len(line))
        fallback_duration = max(0.45, (speech_end - speech_start) * len(line) / total_chars)
        if len(actual_indices) >= 2 and recall >= 0.35 and times:
            start = max(0.0, times[min(actual_indices)][0] - 0.08)
            end = min(source_duration, times[max(actual_indices)][1] + 0.12)
            method = "ASR_MATCHED_CHAR_TIMES"
        else:
            start = fallback_cursor
            end = min(source_duration, start + fallback_duration)
            method = "ASR_SPEECH_RANGE_PROPORTIONAL_FALLBACK"
        rows.append({
            "dialogue_id": row["dia_id"], "expected": row["spoken_text"],
            "source_start": start, "source_end": max(start + 0.25, end),
            "lexical_recall": round(recall, 3), "alignment_method": method,
        })
        expected_cursor = line_end_index
        fallback_cursor += fallback_duration

    # Split overlaps at their midpoint while preserving source order.
    for left, right in zip(rows, rows[1:]):
        if left["source_end"] <= right["source_start"]:
            continue
        midpoint = (left["source_end"] + right["source_start"]) / 2
        left["source_end"] = max(left["source_start"] + 0.25, midpoint - 0.02)
        right["source_start"] = min(right["source_end"] - 0.25, midpoint + 0.02)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--dialogue-manifest", type=Path, required=True)
    parser.add_argument("--out-project", type=Path, required=True)
    parser.add_argument("--out-report", type=Path, required=True)
    parser.add_argument("--output-media", type=Path, required=True)
    parser.add_argument("--audio-track-id", default="Audio.NativeDialogueSfxAmbience")
    parser.add_argument("--model")
    parser.add_argument("--verified-overrides", type=Path)
    args = parser.parse_args()

    source_project = json.loads(args.project.read_text(encoding="utf-8"))
    dialogue_manifest = json.loads(args.dialogue_manifest.read_text(encoding="utf-8"))
    override_payload = json.loads(args.verified_overrides.read_text(encoding="utf-8")) if args.verified_overrides else {"items": []}
    overrides = {row["dialogue_id"]: row for row in override_payload.get("items", [])}
    expected = {row["dia_id"]: row for row in dialogue_manifest["rows"]}
    project = deepcopy(source_project)
    project["output"]["path"] = str(args.output_media.resolve())
    captions = {
        clip["dialogue_id"]: clip
        for track in project["timeline"]["subtitleTracks"]
        for clip in track.get("clips", [])
    }
    native_track = next(
        (track for track in project["timeline"]["audioTracks"] if track["id"] == args.audio_track_id),
        None,
    )
    if native_track is None:
        available = [track.get("id") for track in project["timeline"]["audioTracks"]]
        raise SystemExit(f"audio track not found: {args.audio_track_id}; available={available}")
    model_ref, model_source = resolve_whisper_model(args.model)
    model = WhisperModel(model_ref, device="cpu", compute_type="int8")
    report_units = []
    aligned_ids = set()

    for clip in native_track["clips"]:
        dialogue_ids = list((clip.get("metadata") or {}).get("expected_dialogue_ids") or [])
        if not dialogue_ids:
            continue
        rows = [expected[dialogue_id] for dialogue_id in dialogue_ids]
        complete_override = all(dialogue_id in overrides for dialogue_id in dialogue_ids)
        if complete_override:
            segments = []
            actual = ""
            aligned = []
            for expected_row in rows:
                override = overrides[expected_row["dia_id"]]
                if override["source_id"] != clip["metadata"]["source_id"]:
                    raise SystemExit(f"verified override source mismatch: {expected_row['dia_id']}")
                aligned.append({
                    "dialogue_id": expected_row["dia_id"],
                    "expected": expected_row["spoken_text"],
                    "source_start": float(override["source_start"]),
                    "source_end": float(override["source_end"]),
                    "lexical_recall": float(override.get("lexical_recall", 1.0)),
                    "alignment_method": "TARGETED_NATIVE_SOURCE_ASR_VERIFIED_OVERRIDE",
                    "targeted_evidence": override["evidence"],
                })
        else:
            segments_iter, _ = model.transcribe(
                str(Path(clip["source"]).resolve()), language="zh", vad_filter=True,
                beam_size=5, word_timestamps=True,
                initial_prompt="".join(row["spoken_text"] for row in rows),
            )
            segments = list(segments_iter)
            actual, times = flatten_timed_characters(segments)
            aligned = line_ranges(rows, actual, times, float(clip["duration"]))
            for row in aligned:
                override = overrides.get(row["dialogue_id"])
                if not override:
                    continue
                if override["source_id"] != clip["metadata"]["source_id"]:
                    raise SystemExit(f"verified override source mismatch: {row['dialogue_id']}")
                row["source_start"] = float(override["source_start"])
                row["source_end"] = float(override["source_end"])
                row["alignment_method"] = "TARGETED_NATIVE_SOURCE_ASR_VERIFIED_OVERRIDE"
                row["targeted_evidence"] = override["evidence"]
        source_duration = float(clip["duration"])
        for row in aligned:
            row["source_start"] = max(0.0, min(float(row["source_start"]), source_duration - 0.25))
            row["source_end"] = max(
                row["source_start"] + 0.25,
                min(float(row["source_end"]), source_duration),
            )
        for left, right in zip(aligned, aligned[1:]):
            if left["source_end"] <= right["source_start"] - 0.04:
                continue
            boundary = (left["source_end"] + right["source_start"]) / 2
            left["source_end"] = max(left["source_start"] + 0.25, boundary - 0.02)
            right["source_start"] = min(right["source_end"] - 0.25, boundary + 0.02)
        timeline_start = float(clip["start"])
        for row in aligned:
            caption = captions[row["dialogue_id"]]
            caption["start"] = round(timeline_start + row["source_start"], 6)
            caption["duration"] = round(row["source_end"] - row["source_start"], 6)
            caption.setdefault("metadata", {})["source"] = "NATIVE_SOURCE_ASR_CHAR_ALIGNMENT"
            caption["metadata"]["source_asr_recall"] = row["lexical_recall"]
            aligned_ids.add(row["dialogue_id"])
        report_units.append({
            "source_id": clip["metadata"]["source_id"], "source": clip["source"],
            "timeline_start": timeline_start, "source_duration": float(clip["duration"]),
            "expected_dialogue_ids": dialogue_ids,
            "expected_text": "".join(row["spoken_text"] for row in rows),
            "asr_transcript": "".join(segment.text.strip() for segment in segments) if segments else
                              "".join(overrides[dialogue_id].get("asr_transcript", "") for dialogue_id in dialogue_ids),
            "asr_chinese": actual,
            "segments": [{"start": round(float(segment.start), 3), "end": round(float(segment.end), 3),
                          "text": segment.text.strip()} for segment in segments],
            "alignments": aligned,
        })

    expected_ids = set(expected)
    failures = []
    if aligned_ids != expected_ids:
        failures.append({"type": "DIALOGUE_COVERAGE_MISMATCH", "missing": sorted(expected_ids - aligned_ids),
                         "extra": sorted(aligned_ids - expected_ids)})
    low_recall = [
        row for unit in report_units for row in unit["alignments"]
        if row["lexical_recall"] < 0.35 and row["alignment_method"] != "TARGETED_NATIVE_SOURCE_ASR_VERIFIED_OVERRIDE"
    ]
    if low_recall:
        failures.append({"type": "SOURCE_NATIVE_DIALOGUE_LOW_ASR_RECALL", "dialogue_ids": [row["dialogue_id"] for row in low_recall]})

    report = {
        "schema": "qingshan.native_source_caption_alignment.v1",
        "episode": source_project.get("metadata", {}).get("episode") or dialogue_manifest.get("episode"),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failures else "FAIL", "dialogue_count": len(expected_ids),
        "aligned_count": len(aligned_ids), "low_recall_count": len(low_recall),
        "failures": failures, "units": report_units,
        "verified_overrides": str(args.verified_overrides.resolve()) if args.verified_overrides else None,
        "whisper_model_source": model_source,
        "policy": "Captions follow dialogue already generated in each source video; no reference or post-dub audio is inserted into the final timeline.",
    }
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not failures:
        project["metadata"]["status"] = "CORRECTED_RELEASE_V2_NATIVE_SOURCE_ASR_ALIGNED_PENDING_RENDER_AND_FINAL_GATES"
        project["metadata"]["native_source_caption_alignment"] = str(args.out_report.resolve())
        args.out_project.parent.mkdir(parents=True, exist_ok=True)
        args.out_project.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "aligned": len(aligned_ids),
                      "low_recall": [row["dialogue_id"] for row in low_recall],
                      "out_project": str(args.out_project.resolve())}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
