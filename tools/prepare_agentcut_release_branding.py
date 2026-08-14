#!/usr/bin/env python3
"""Add canonical burned subtitles and the Nalu Motion outro to AgentCut."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOGO = ROOT / "libraries/brand/nalu_motion_cat_logo_v1.png"
DEFAULT_CHIME = ROOT / "libraries/brand/nalu_motion_outro_chime_v1.wav"
DEFAULT_FONT = Path("/System/Library/Fonts/STHeiti Medium.ttc")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def line_id(episode: str, value: object) -> str:
    return f"{episode}-L{int(value):03d}"


def allocate_caption_windows(
    project: dict, dialogue_contract: dict
) -> tuple[list[str], list[dict]]:
    episode = str(dialogue_contract.get("episode") or "").upper()
    rows = dialogue_contract.get("dialogue") or []
    by_line = {int(row["line_id"]): row for row in rows}
    expected_ids = [line_id(episode, row["line_id"]) for row in rows]
    captions: list[dict] = []
    covered: list[int] = []

    tracks = project.get("timeline", {}).get("videoTracks", [])
    if not tracks:
        raise ValueError("project has no video track")
    clips = sorted(tracks[0].get("clips", []), key=lambda row: float(row["start"]))
    for clip in clips:
        metadata = clip.get("metadata", {})
        canonical_lines = [int(value) for value in metadata.get("canonical_lines", [])]
        if not canonical_lines:
            continue
        missing = [value for value in canonical_lines if value not in by_line]
        if missing:
            raise ValueError(f"canonical dialogue rows missing: {missing}")
        covered.extend(canonical_lines)
        start = float(clip["start"])
        duration = float(clip["duration"])
        head_pad = min(0.24, duration * 0.04)
        tail_pad = min(0.18, duration * 0.03)
        gap = 0.08 if len(canonical_lines) > 1 else 0.0
        available = duration - head_pad - tail_pad - gap * (len(canonical_lines) - 1)
        if available <= 0:
            raise ValueError(f"caption window is not positive for {clip.get('id')}")
        weights = [max(4, len(str(by_line[value]["spoken_text"]))) for value in canonical_lines]
        total_weight = sum(weights)
        cursor = start + head_pad
        for value, weight in zip(canonical_lines, weights):
            row = by_line[value]
            line_duration = available * weight / total_weight
            dialogue_id = line_id(episode, value)
            captions.append(
                {
                    "id": f"{dialogue_id}-CAP",
                    "dialogue_id": dialogue_id,
                    "text": row["spoken_text"],
                    "start": round(cursor, 6),
                    "duration": round(line_duration, 6),
                    "metadata": {
                        "episode": episode,
                        "line_id": value,
                        "speaker": row.get("speaker"),
                        "source_clip": clip.get("id"),
                        "source": "CANONICAL_LINE_WITHIN_NATIVE_VIDEO_UNIT_WINDOW",
                        "timing_qa_required": True,
                    },
                }
            )
            cursor += line_duration + gap

    expected_lines = [int(row["line_id"]) for row in rows]
    if covered != expected_lines:
        raise ValueError(
            f"canonical subtitle coverage mismatch: actual={covered!r} expected={expected_lines!r}"
        )
    return expected_ids, captions


def build(
    project: dict,
    dialogue_contract: dict,
    *,
    output_media: Path,
    logo: Path = DEFAULT_LOGO,
    chime: Path = DEFAULT_CHIME,
    font: Path = DEFAULT_FONT,
) -> dict:
    if not logo.is_file() or not chime.is_file() or not font.is_file():
        raise ValueError("release branding assets or CJK font are missing")
    result = deepcopy(project)
    episode = str(dialogue_contract.get("episode") or "").upper()
    expected_ids, captions = allocate_caption_windows(result, dialogue_contract)
    result["requireBurnedSubtitles"] = True
    result["requireBrandedOutro"] = True
    result["expectedDialogueIds"] = expected_ids
    result.setdefault("timeline", {})["subtitleTracks"] = [
        {
            "id": f"{episode}_ZH_CN_BURNIN",
            "enabled": True,
            "style": {
                "font": str(font.resolve()),
                "size": 42,
                "color": "#FFFFFF",
                "outline": 3,
                "outlineColor": "#000000",
                "alignment": "bottom-center",
                "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
                "wrap": 15,
            },
            "clips": captions,
        }
    ]
    result["outro"] = {
        "enabled": True,
        "brand": "nalu_motion",
        "template": "nalu-motion-v1",
        "templateVersion": "1.0",
        "assetPath": str(logo.resolve()),
        "audioPath": str(chime.resolve()),
        "duration": 3.0,
        "fit": "contain",
        "audioPolicy": "asset",
        "transitionIn": 0.25,
        "transitionOut": 0.25,
        "titleText": "青山",
        "nextText": "敬请期待",
        "brandText": "NALU MOTION",
        "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
        "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
        "includeInTotalDuration": True,
    }
    result["releaseGate"] = {"required": True}
    result.setdefault("metadata", {})["subtitle_contract"] = {
        "coverage": f"{len(captions)}/{len(expected_ids)}",
        "burned_in": True,
        "canonical_dialogue_contract": dialogue_contract.get("schema"),
        "timing_qa_required": True,
    }
    result["metadata"]["branding_contract"] = {
        "brand": "nalu_motion",
        "required": True,
        "duration_seconds": 3.0,
        "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE",
    }
    result.setdefault("output", {})["path"] = str(output_media.expanduser().resolve())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--dialogue-contract", required=True)
    parser.add_argument("--out-project", required=True)
    parser.add_argument("--output-media", required=True)
    parser.add_argument("--logo", default=str(DEFAULT_LOGO))
    parser.add_argument("--chime", default=str(DEFAULT_CHIME))
    parser.add_argument("--font", default=str(DEFAULT_FONT))
    args = parser.parse_args()

    out_project = Path(args.out_project).expanduser().resolve()
    output_media = Path(args.output_media).expanduser().resolve()
    branded = build(
        load(Path(args.project).expanduser().resolve()),
        load(Path(args.dialogue_contract).expanduser().resolve()),
        output_media=output_media,
        logo=Path(args.logo).expanduser().resolve(),
        chime=Path(args.chime).expanduser().resolve(),
        font=Path(args.font).expanduser().resolve(),
    )
    out_project.parent.mkdir(parents=True, exist_ok=True)
    output_media.parent.mkdir(parents=True, exist_ok=True)
    out_project.write_text(json.dumps(branded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "READY_FOR_TIMING_QA_VALIDATE_RENDER",
                "project": str(out_project),
                "output_media": str(output_media),
                "subtitle_count": len(branded["expectedDialogueIds"]),
                "outro": "NALU_MOTION_3_SECONDS",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
