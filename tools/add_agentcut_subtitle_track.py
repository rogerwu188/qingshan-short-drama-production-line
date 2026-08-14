#!/usr/bin/env python3
"""Build a burn-in subtitle variant from AgentCut dialogue and ASR evidence."""

from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_STYLE = {
    "size": 42,
    "color": "#FFFFFF",
    "outline": 3,
    "outlineColor": "#000000",
    "alignment": "bottom-center",
    "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
    "wrap": 15,
}

FONT_CANDIDATES = (
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)


def resolve_subtitle_font(explicit: str | None = None) -> str:
    configured = explicit or os.environ.get("AGENTCUT_SUBTITLE_FONT")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise SystemExit(f"subtitle font missing: {candidate}")
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(
        "no CJK subtitle font found; set AGENTCUT_SUBTITLE_FONT or --font"
    )


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--sentence-report", type=Path, required=True)
    parser.add_argument("--out-project", type=Path, required=True)
    parser.add_argument("--output-media", type=Path, required=True)
    parser.add_argument("--track-id", default="ZH_CN_BURNIN_V1")
    parser.add_argument("--head-pad", type=float, default=0.08)
    parser.add_argument("--tail-pad", type=float, default=0.08)
    parser.add_argument("--font")
    args = parser.parse_args()

    project = deepcopy(load(args.project))
    report = load(args.sentence_report)
    sentences = {row["id"]: row for row in report.get("sentences", [])}
    video_tracks = project.get("timeline", {}).get("videoTracks", [])
    if not video_tracks:
        raise SystemExit("project has no video track")

    captions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for clip in video_tracks[0].get("clips", []):
        metadata = clip.get("metadata", {})
        dialogue_id = metadata.get("dialogue_id")
        if not dialogue_id or dialogue_id in seen:
            continue
        sentence = sentences.get(dialogue_id)
        if not sentence:
            raise SystemExit(f"missing sentence evidence for {dialogue_id}")
        seen.add(dialogue_id)
        timeline_start = float(clip["start"])
        timeline_duration = float(clip["duration"])
        source_in = float(sentence.get("source_in", clip.get("in", 0.0)))
        segments = sentence.get("segments", [])
        if segments:
            speech_start = min(float(row["start"]) for row in segments)
            speech_end = max(float(row["end"]) for row in segments)
            local_start = max(0.0, speech_start - source_in - args.head_pad)
            local_end = min(
                timeline_duration, speech_end - source_in + args.tail_pad
            )
        else:
            local_start = 0.0
            local_end = timeline_duration
        if local_end <= local_start:
            local_start = 0.0
            local_end = timeline_duration
        captions.append(
            {
                "id": f"{metadata.get('episode', 'EP')}-CAP-{len(captions) + 1:03d}",
                "dialogue_id": dialogue_id,
                "text": sentence["expected"],
                "start": round(timeline_start + local_start, 6),
                "duration": round(max(0.5, local_end - local_start), 6),
                "metadata": {
                    "episode": metadata.get("episode"),
                    "beat_id": metadata.get("beat_id"),
                    "speaker": metadata.get("speaker"),
                    "source": "sentence_audit_asr_window",
                },
            }
        )

    expected_ids = list(sentences)
    actual_ids = [caption["dialogue_id"] for caption in captions]
    expected = len(expected_ids)
    if actual_ids != expected_ids or len(actual_ids) != len(set(actual_ids)):
        raise SystemExit(
            "subtitle dialogue order/coverage mismatch: "
            f"actual={actual_ids!r} expected={expected_ids!r}"
        )
    project["expectedDialogueIds"] = expected_ids
    style = deepcopy(DEFAULT_STYLE)
    style["font"] = resolve_subtitle_font(args.font)
    project["timeline"]["subtitleTracks"] = [
        {
            "id": args.track_id,
            "enabled": True,
            "style": style,
            "clips": captions,
        }
    ]
    project["output"]["path"] = str(args.output_media.expanduser().resolve())
    project.setdefault("metadata", {})["subtitle_contract"] = {
        "coverage": f"{len(captions)}/{expected}",
        "ordered_dialogue_ids_match": True,
        "source": str(args.sentence_report.expanduser().resolve()),
        "burned_in": True,
    }
    args.out_project.parent.mkdir(parents=True, exist_ok=True)
    args.output_media.parent.mkdir(parents=True, exist_ok=True)
    args.out_project.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps({"project": str(args.out_project), "captions": len(captions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
