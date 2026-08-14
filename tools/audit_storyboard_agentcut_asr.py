#!/usr/bin/env python3
"""Audit multi-dialogue storyboard source clips without assuming one line per clip."""

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel

try:
    from tools.audit_e18r_agentcut_final_asr import (
        DEFAULT_FFMPEG, DEFAULT_MODEL, chinese_only, media_duration,
        recall_score, source_range_cuts_sentence, transcribe,
    )
except ModuleNotFoundError:
    from audit_e18r_agentcut_final_asr import (
        DEFAULT_FFMPEG, DEFAULT_MODEL, chinese_only, media_duration,
        recall_score, source_range_cuts_sentence, transcribe,
    )


ROOT = Path(__file__).resolve().parents[1]
def storyboard_audio_clips(project):
    clips = []
    for track in project["timeline"].get("audioTracks", []):
        for clip in track.get("clips", []):
            metadata = clip.get("metadata") or {}
            if metadata.get("source_id") and metadata.get("expected_text") is not None:
                clips.append(clip)
    return sorted(clips, key=lambda row: (float(row.get("start", 0.0)), row.get("id", "")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--ffmpeg", default=str(DEFAULT_FFMPEG))
    parser.add_argument("--out-asr", required=True)
    parser.add_argument("--out-sentences", required=True)
    args = parser.parse_args()

    video = Path(args.video).resolve()
    project_path = Path(args.project).resolve()
    beat_sheet_path = Path(args.beat_sheet).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    project = json.loads(project_path.read_text())
    clips = storyboard_audio_clips(project)
    if not clips:
        raise SystemExit("AgentCut project contains no storyboard dialogue-group audio clips")

    model = WhisperModel(str(Path(args.model).resolve()), device="cpu", compute_type="int8")
    full_segments = transcribe(model, video, vad_filter=False)
    asr_payload = {
        "schema": "qingshan.storyboard_agentcut_final_asr.v1",
        "status": "PASS" if chinese_only("".join(row["text"] for row in full_segments)) else "FAIL",
        "video": str(video),
        "project": str(project_path),
        "beat_sheet": str(beat_sheet_path),
        "segments": full_segments,
        "transcript": "".join(row["text"] for row in full_segments),
    }
    out_asr = Path(args.out_asr).resolve()
    out_asr.parent.mkdir(parents=True, exist_ok=True)
    out_asr.write_text(json.dumps(asr_payload, ensure_ascii=False, indent=2) + "\n")

    rows = []
    for clip in clips:
        source = Path(clip["source"]).resolve()
        metadata = clip.get("metadata") or {}
        expected = str(metadata.get("expected_text") or "")
        segments = transcribe(model, source, vad_filter=False)
        transcript = "".join(row["text"] for row in segments)
        source_duration = media_duration(source, ffmpeg)
        source_in = float(clip.get("in", 0.0))
        duration = float(clip["duration"])
        cut_inside = source_range_cuts_sentence(segments, source_in, duration, source_duration)
        speech_present = bool(chinese_only(transcript))
        complete = speech_present and not cut_inside
        rows.append({
            "source_id": metadata.get("source_id"),
            "beat_id": metadata.get("beat_id"),
            "expected": expected,
            "transcript": transcript,
            "recall_score": round(recall_score(expected, transcript), 3),
            "speech_present": speech_present,
            "cut_inside_sentence": cut_inside,
            "complete": complete,
            "failures": ([] if speech_present else ["NO_RECOGNIZED_CHINESE_SPEECH"]) + (["AGENTCUT_SOURCE_RANGE_TRUNCATES_SENTENCE"] if cut_inside else []),
        })
    failures = [row["source_id"] for row in rows if not row["complete"]]
    sentence_payload = {
        "schema": "qingshan.storyboard_agentcut_sentence_groups.v1",
        "status": "PASS" if not failures else "FAIL",
        "policy": "Each storyboard source may contain multiple dialogue lines; missing speech or an admitted range cutting active speech blocks. Lexical ASR variation is retained as evidence but is non-blocking.",
        "source_group_count": len(rows),
        "complete_count": len(rows) - len(failures),
        "failure_count": len(failures),
        "groups": rows,
        "failures": failures,
    }
    out_sentences = Path(args.out_sentences).resolve()
    out_sentences.parent.mkdir(parents=True, exist_ok=True)
    out_sentences.write_text(json.dumps(sentence_payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": sentence_payload["status"], "groups": len(rows), "failures": failures}, ensure_ascii=False))
    return 1 if failures or asr_payload["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
