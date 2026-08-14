#!/usr/bin/env python3
"""Build deterministic E39 R3 dialogue/subtitle insertion plans for AgentCut."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
R3 = BASE / "independent_video_r3_silent_visual/E39_INDEPENDENT_FAILED_ONLY_R3_SILENT_VISUAL_MANIFEST_V2.json"
AUDIO = ROOT / "workflow/tasks/E39_INDEPENDENT_R2_EXACT_DIALOGUE_AUDIO_ASSETS_20260806.json"
OUT_DIR = ROOT / "workflow/agentcut/e39_r3_postproduction"
OUT = OUT_DIR / "E39_R3_EXACT_DIALOGUE_SUBTITLE_TEXT_PLATE_PLAN_V2.json"

STARTS = {
    "U01": [5.70, 9.40],
    "U02": [0.80, 6.20],
    "U03": [7.00],
    "U04": [1.00],
    "U05": [6.50],
    "U10": [5.50, 8.20],
    "U11": [1.00, 7.00],
    "U12": [0.20, 2.90],
    "U13": [8.00],
    "U14": [0.60],
    "U15": [1.00],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return round(float(result.stdout.strip()), 6)


def ass_time(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def write_ass(unit: str, events: list[dict]) -> Path:
    path = OUT_DIR / f"E39-{unit}-R3-WHITE-OUTLINE-NO-BOX.ass"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Qingshan,Heiti SC,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,2,70,70,180,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [
        f"Dialogue: 0,{ass_time(row['start_seconds'])},{ass_time(row['end_seconds'])},Qingshan,{row['speaker']},0,0,0,,{row['text']}"
        for row in events
    ]
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    r3 = json.loads(R3.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO.read_text(encoding="utf-8"))
    by_unit: dict[str, list[dict]] = {}
    for row in audio["results"]:
        by_unit.setdefault(row["unit_id"], []).append(row)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    units = []
    for task in r3["tasks"]:
        unit = task["task_key"].split("-")[1]
        rows = by_unit[unit]
        starts = STARTS[unit]
        if len(rows) != len(starts):
            raise ValueError(f"{unit} timing/audio count mismatch")
        events = []
        for index, (row, start) in enumerate(zip(rows, starts), 1):
            wav = Path(row["wav_path"])
            if not wav.exists():
                raise FileNotFoundError(wav)
            audio_duration = duration(wav)
            end = round(start + audio_duration, 3)
            if end > float(task["duration_seconds"]):
                raise ValueError(f"{unit} line {index} exceeds clip duration")
            events.append(
                {
                    "line_index": index,
                    "source_line_id": row["source_line_id"],
                    "speaker": row["speaker"],
                    "text": row["text"],
                    "start_seconds": start,
                    "end_seconds": end,
                    "wav_path": str(wav.relative_to(ROOT)),
                    "wav_sha256": row["wav_sha256"],
                    "registered_asset_id": row["registered_asset_id"],
                    "mix": {"gain_db": 0.0, "fade_in_ms": 20, "fade_out_ms": 35, "duck_bgm_db": -7.0},
                }
            )
        ass = write_ass(unit, events)
        units.append(
            {
                "unit_id": unit,
                "expected_visual_duration_seconds": task["duration_seconds"],
                "dialogue_events": events,
                "subtitle_ass": str(ass.relative_to(ROOT)),
                "subtitle_ass_sha256": sha(ass),
                "text_plate": task.get("postproduction_text_plate"),
                "text_plate_sha256": task.get("postproduction_text_plate_sha256"),
            }
        )
    result = {
        "schema": "qingshan.e39.r3_agentcut_postproduction_plan.v2",
        "episode": "E39",
        "status": "PASS_9_REPAIR_UNITS_13_DIALOGUE_EVENTS_PLUS_2_PRESERVED_SOURCE_UNITS",
        "source_script_sha256": r3["source_script_sha256"],
        "canonical_manifest_sha256": r3["canonical_manifest_sha256"],
        "r3_manifest": str(R3.relative_to(ROOT)),
        "r3_manifest_sha256": sha(R3),
        "audio_receipt": str(AUDIO.relative_to(ROOT)),
        "audio_receipt_sha256": sha(AUDIO),
        "subtitle_style": "WHITE_HEITI_54_BLACK_OUTLINE_3_NO_BACKGROUND_BOX_BOTTOM_CENTER",
        "source_audio_policy": "REMOVE_GENERATED_AUDIO_TRACK_USE_EXACT_AGENTCUT_DIALOGUE_ONLY",
        "source_subtitle_policy": "NO_MODEL_SOURCE_SUBTITLES",
        "preserved_source_units": r3["preserved_source_units"],
        "units": units,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "plan": str(OUT), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
