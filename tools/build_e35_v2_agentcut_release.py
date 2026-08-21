#!/usr/bin/env python3
"""Build the final E35 recut from exact native-dialogue replacement windows."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.episode_stage_gate_runner import require_release_builder_gate_admission
except ModuleNotFoundError:
    from episode_stage_gate_runner import require_release_builder_gate_admission


ROOT = Path(__file__).resolve().parents[1]
BASE_PROJECT = ROOT / "configs/e35_agentcut_v1_release_20260723.json"
FINAL_ASR = ROOT / "qa/e35_v1_release_20260723/E35_REPAIRED_SOURCE_ASR_FINAL_V1.json"
ORIGINAL_ALIGNMENT = ROOT / "qa/e35_v1_release_20260723/E35_NATIVE_SOURCE_CAPTION_ALIGNMENT_V1.json"
AUDIO_MANIFEST = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U01_SPLIT_REPAIR2.json"
ADMISSION = ROOT / "qa/e35_v1_release_20260723/E35_REPAIRED_SOURCE_CONDITIONAL_ADMISSION_V1.json"
PROJECT = ROOT / "configs/e35_agentcut_v2_release_20260724.json"
SOURCE_LOCK = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723/video_performance_v1/E35_V2_LOCKED_SOURCE_MANIFEST.json"
OUTPUT = ROOT / "exports/e35/v2_release_20260724/E35_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
EDIT_GATE_EVIDENCE = ROOT / "workflow/agentcut/release_gate_evidence/E35_V2_RELEASE_EDIT_GATE_EVIDENCE_BUNDLE.json"
EDIT_GATE_OUT = ROOT / "qa/e35_v2_release_20260724/unified_edit_gates"
RECEIPT = ROOT / "workflow/tasks/E35_AGENTCUT_V2_RELEASE_BUILD_RECEIPT_20260724.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
U22_CADENCE_REPAIR = ROOT / "working_assets/e35_agentcut_repairs_20260724/E35_CW_U22_PERIODIC_DUPLICATE_INTERPOLATED.mp4"
U22_CADENCE_EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_U22_PERIODIC_DUPLICATE_INTERPOLATED_FRAME_CADENCE_V1.json"

AFFECTED = {"E35-CW-U05", "E35-CW-U07", "E35-CW-U14", "E35-CW-U18", "E35-CW-U19", "E35-CW-U21"}
REPLACEMENTS = {
    "E35-CW-U05": ["E35-CW-U05A1", "E35-CW-U05A2", "E35-CW-U05B"],
    "E35-CW-U07": ["E35-CW-U07A", "E35-CW-U07B"],
    "E35-CW-U14": ["E35-CW-U14A", "E35-CW-U14B"],
    "E35-CW-U18": ["E35-CW-U18A", "E35-CW-U18B"],
    "E35-CW-U19": ["E35-CW-U19A", "E35-CW-U19B", "E35-CW-U19C1", "E35-CW-U19C2", "E35-CW-U19C3"],
    "E35-CW-U21": ["E35-CW-U21A", "E35-CW-U21B"],
}
EXPECTED_IDS = {
    "E35-CW-U05A1": ["E35-DIA-SEG-013"], "E35-CW-U05A2": ["E35-DIA-SEG-013"], "E35-CW-U05B": ["E35-DIA-SEG-014"],
    "E35-CW-U07A": ["E35-DIA-SEG-017"], "E35-CW-U07B": ["E35-DIA-SEG-018", "E35-DIA-SEG-019", "E35-DIA-SEG-020"],
    "E35-CW-U14A": ["E35-DIA-SEG-027"], "E35-CW-U14B": ["E35-DIA-SEG-028"],
    "E35-CW-U18A": ["E35-DIA-SEG-036"], "E35-CW-U18B": ["E35-DIA-SEG-037", "E35-DIA-SEG-038"],
    "E35-CW-U19A": ["E35-DIA-SEG-039"], "E35-CW-U19B": ["E35-DIA-SEG-040"],
    "E35-CW-U19C1": ["E35-DIA-SEG-041"],
    "E35-CW-U19C2": ["E35-DIA-SEG-042"], "E35-CW-U19C3": ["E35-DIA-SEG-043"],
    "E35-CW-U21A": ["E35-DIA-SEG-044"], "E35-CW-U21B": ["E35-DIA-SEG-045"],
}
# Preserve the beginning, middle and terminal state of dialogue-free action units.
ACTION_CUTS = {
    "E35-CW-U10": [(0.2, 1.7), (2.2, 3.7), (4.2, 5.8)],
    "E35-CW-U11": [(0.2, 1.8), (2.5, 4.2), (4.8, 6.7)],
    "E35-CW-U12": [(0.2, 1.8), (2.9, 5.0), (5.5, 7.8)],
    "E35-CW-U13": [(0.2, 1.7), (2.2, 3.7), (4.2, 5.8)],
    "E35-CW-U20": [(0.2, 1.9), (2.8, 4.8)],
    "E35-CW-U23": [(0.2, 2.2), (2.7, 4.8)],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run([
        str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,duration",
        "-of", "json", str(path),
    ], check=True, text=True, capture_output=True)
    streams = json.loads(result.stdout).get("streams", [])
    values = [float(row["duration"]) for row in streams if row.get("codec_type") in {"video", "audio"} and row.get("duration")]
    if len(values) < 2:
        raise SystemExit(f"source lacks timed native audio and video: {path}")
    return min(values) - (1.0 / 24.0)


def zh_len(text: str) -> int:
    return max(1, len(re.findall(r"[\u3400-\u9fff]", text)))


def split_caption_span(ids: list[str], start: float, end: float, dialogue: dict[str, dict]) -> list[dict]:
    if len(ids) == 1:
        return [{"id": ids[0], "start": start, "end": end}]
    gap = 0.08
    weights = [zh_len(dialogue[item]["spoken_text"]) for item in ids]
    budget = max(0.2, end - start - gap * (len(ids) - 1))
    cursor = start
    rows = []
    for item, weight in zip(ids, weights):
        item_duration = budget * weight / sum(weights)
        rows.append({"id": item, "start": cursor, "end": cursor + item_duration})
        cursor += item_duration + gap
    rows[-1]["end"] = end
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-gate-evidence-bundle", type=Path, default=EDIT_GATE_EVIDENCE)
    parser.add_argument("--edit-gate-out-dir", type=Path, default=EDIT_GATE_OUT)
    args = parser.parse_args()
    require_release_builder_gate_admission(
        episode="E35",
        evidence_bundle=args.edit_gate_evidence_bundle,
        out_dir=args.edit_gate_out_dir,
    )
    for path in (BASE_PROJECT, FINAL_ASR, ORIGINAL_ALIGNMENT, AUDIO_MANIFEST, ADMISSION, FFPROBE):
        if not path.is_file():
            raise SystemExit(f"missing E35 v2 input: {path}")
    project = load(BASE_PROJECT)
    asr = load(FINAL_ASR)
    alignment = load(ORIGINAL_ALIGNMENT)
    audio_manifest = load(AUDIO_MANIFEST)
    admission = load(ADMISSION)
    if asr.get("status") != "PASS" or asr.get("exact_window_count") != 16:
        raise SystemExit("repaired-source exact native-dialogue ASR is incomplete")
    if admission.get("status") != "PASS_CONDITIONAL_MACHINE_ADMISSION":
        raise SystemExit("repaired-source visual/OCR conditional admission is incomplete")

    original_video = {row["metadata"]["source_id"]: row for row in project["timeline"]["videoTracks"][0]["clips"]}
    original_audio = {row["metadata"]["source_id"]: row for row in project["timeline"]["audioTracks"][0]["clips"]}
    asr_rows = {row["unit_id"]: row for row in asr["rows"]}
    dialogue = {row["dia_id"]: row for row in audio_manifest["rows"]}
    original_alignment = {row["source_id"]: row for row in alignment["units"]}

    specs = []
    for base_id, original in original_video.items():
        if base_id in AFFECTED:
            for unit_id in REPLACEMENTS[base_id]:
                row = asr_rows[unit_id]
                media = Path(row["source"])
                available = duration(media)
                source_in = float(row["source_in_seconds"])
                source_out = min(available - 0.01, float(row["source_out_seconds"]))
                if unit_id == "E35-CW-U19B":
                    source_out = min(available - 0.01, max(source_out, 1.0))
                specs.append({
                    "source_id": unit_id, "base_id": base_id, "scene_id": original["metadata"]["scene_id"],
                    "source": media, "in": source_in, "duration": source_out - source_in,
                    "expected_ids": EXPECTED_IDS[unit_id], "asr": row,
                    "admission": "QA_PASS" if unit_id not in set(admission.get("conditionally_admitted_units", [])) else "CONDITIONAL_MACHINE_ADMISSION",
                    "admission_evidence": str(ADMISSION),
                })
        elif base_id in ACTION_CUTS:
            for index, (source_in, source_out) in enumerate(ACTION_CUTS[base_id], 1):
                specs.append({
                    "source_id": f"{base_id}-PART{index}", "base_id": base_id,
                    "scene_id": original["metadata"]["scene_id"], "source": Path(original["source"]),
                    "in": source_in, "duration": source_out - source_in, "expected_ids": [], "asr": None,
                    "admission": original["metadata"]["source_admission"],
                    "admission_evidence": original["metadata"]["admission_evidence"],
                })
        else:
            source = U22_CADENCE_REPAIR if base_id == "E35-CW-U22" else Path(original["source"])
            admission_evidence = str(U22_CADENCE_EVIDENCE) if base_id == "E35-CW-U22" else original["metadata"]["admission_evidence"]
            specs.append({
                "source_id": base_id, "base_id": base_id, "scene_id": original["metadata"]["scene_id"],
                "source": source, "in": float(original.get("in", 0.0)),
                "duration": float(original["duration"]),
                "expected_ids": list(original["metadata"].get("expected_dialogue_ids", [])), "asr": None,
                "admission": original["metadata"]["source_admission"],
                "admission_evidence": admission_evidence,
            })

    video_clips, audio_clips, source_rows, timeline_windows = [], [], [], {}
    cursor = 0.0
    for spec in specs:
        if not spec["source"].is_file():
            raise SystemExit(f"missing selected source: {spec['source']}")
        clip_duration = round(float(spec["duration"]), 6)
        metadata = {
            "episode": "E35", "source_id": spec["source_id"], "base_unit_id": spec["base_id"],
            "scene_id": spec["scene_id"], "source_sha256": sha256(spec["source"]),
            "source_admission": spec["admission"], "admission_evidence": spec["admission_evidence"],
            "expected_dialogue_ids": spec["expected_ids"],
            "expected_text": "".join(dialogue[item]["spoken_text"] for item in dict.fromkeys(spec["expected_ids"])),
            "duration_policy": "NATIVE_SPEED_EXACT_ASR_WINDOW_OR_AUTHORED_ACTION_SUBCUT",
            "cut_reason": "LOCKED_DIALOGUE_WINDOW" if spec["expected_ids"] else "DIALOGUE_FREE_ACTION_BEGIN_MIDDLE_END_PRESERVATION",
            "cutReason": "LOCKED_DIALOGUE_WINDOW" if spec["expected_ids"] else "DIALOGUE_FREE_ACTION_BEGIN_MIDDLE_END_PRESERVATION",
            "light_key": f"{spec['scene_id']}::SCENE_AUTHORITY_LOCK",
            "axis_line": f"{spec['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{spec['source_id']}::PRIMARY_ACTION_TARGET",
        }
        common = {"source": str(spec["source"]), "start": round(cursor, 6), "in": round(spec["in"], 6), "duration": clip_duration, "metadata": metadata}
        video_clips.append({"id": f"{spec['source_id']}-VIDEO", **common})
        audio_clips.append({"id": f"{spec['source_id']}-AUDIO", **common, "volume": 0.82})
        timeline_windows[spec["source_id"]] = {"start": cursor, "in": spec["in"], "duration": clip_duration, "asr": spec["asr"]}
        source_rows.append({"source_id": spec["source_id"], "base_unit_id": spec["base_id"], "path": str(spec["source"]), "sha256": sha256(spec["source"]), "source_in_seconds": spec["in"], "duration_seconds": clip_duration, "admission": spec["admission"], "dialogue_ids": spec["expected_ids"]})
        cursor += clip_duration

    content_duration = round(cursor, 6)
    total_duration = round(content_duration + 3.0, 6)
    if total_duration > 179.0:
        raise SystemExit(f"E35 v2 exceeds YouTube Shorts target: {total_duration}")

    caption_spans = {}
    for source_id, row in original_alignment.items():
        if source_id in AFFECTED or source_id not in timeline_windows:
            continue
        window = timeline_windows[source_id]
        for item in row["alignments"]:
            caption_spans[item["dialogue_id"]] = {
                "start": window["start"] + item["source_start"] - window["in"],
                "end": window["start"] + item["source_end"] - window["in"],
            }

    def speech_span(unit_id: str) -> tuple[float, float]:
        window = timeline_windows[unit_id]
        row = asr_rows[unit_id]
        first, last = row["exact_window_segment_indices"]
        return (
            window["start"] + row["segments"][first]["start"] - window["in"],
            window["start"] + row["segments"][last]["end"] - window["in"],
        )

    custom = {
        "E35-DIA-SEG-013": (speech_span("E35-CW-U05A1")[0], speech_span("E35-CW-U05A2")[1]),
        "E35-DIA-SEG-014": speech_span("E35-CW-U05B"),
        "E35-DIA-SEG-017": speech_span("E35-CW-U07A"),
        "E35-DIA-SEG-027": speech_span("E35-CW-U14A"),
        "E35-DIA-SEG-028": speech_span("E35-CW-U14B"),
        "E35-DIA-SEG-036": speech_span("E35-CW-U18A"),
        "E35-DIA-SEG-039": speech_span("E35-CW-U19A"),
        "E35-DIA-SEG-040": speech_span("E35-CW-U19B"),
        "E35-DIA-SEG-041": speech_span("E35-CW-U19C1"),
        "E35-DIA-SEG-042": speech_span("E35-CW-U19C2"),
        "E35-DIA-SEG-043": speech_span("E35-CW-U19C3"),
        "E35-DIA-SEG-044": speech_span("E35-CW-U21A"),
        "E35-DIA-SEG-045": speech_span("E35-CW-U21B"),
    }
    for item, span in custom.items():
        caption_spans[item] = {"start": span[0], "end": span[1]}
    for unit_id, ids in (("E35-CW-U07B", ["E35-DIA-SEG-018", "E35-DIA-SEG-019", "E35-DIA-SEG-020"]), ("E35-CW-U18B", ["E35-DIA-SEG-037", "E35-DIA-SEG-038"])):
        start, end = speech_span(unit_id)
        for item in split_caption_span(ids, start, end, dialogue):
            caption_spans[item["id"]] = {"start": item["start"], "end": item["end"]}

    expected_ids = {row["dia_id"] for row in audio_manifest["rows"]}
    if set(caption_spans) != expected_ids or len(caption_spans) != 47:
        raise SystemExit(f"caption coverage mismatch: missing={sorted(expected_ids-set(caption_spans))}")
    captions = []
    for item in audio_manifest["rows"]:
        span = caption_spans[item["dia_id"]]
        captions.append({
            "id": item["dia_id"], "dialogue_id": item["dia_id"], "text": item["spoken_text"],
            "start": round(span["start"], 6), "duration": round(max(0.45, span["end"] - span["start"]), 6),
            "metadata": {"episode": "E35", "speaker": item["speaker"], "source": "EXACT_NATIVE_SOURCE_ASR_ALIGNMENT_V2"},
        })

    bgm_source = Path(project["timeline"]["audioTracks"][1]["clips"][0]["source"])
    bgm_sha = sha256(bgm_source)
    bgm_start = 4.0
    bgm_clips = []
    for spec, clip in zip(specs, video_clips):
        start = max(float(clip["start"]), bgm_start)
        end = float(clip["start"]) + float(clip["duration"])
        if end <= start:
            continue
        has_dialogue = bool(spec["expected_ids"])
        bgm_clips.append({
            "id": f"E35-V2-BGM-{clip['id']}", "source": str(bgm_source), "start": round(start, 6),
            "in": round(start - bgm_start, 6), "duration": round(end - start, 6),
            "volume": 0.06 if has_dialogue else 0.15,
            "metadata": {"dialogue_duck_db": -8.52 if has_dialogue else 0.0, "source_sha256": bgm_sha, "timeline_policy": "CONTINUOUS_NO_LOOP_NO_STRETCH"},
        })
    bgm_clips[0]["transitionIn"] = {"type": "fade", "duration": 0.5}
    bgm_clips[-1]["transitionOut"] = {"type": "fade", "duration": 1.0}

    project["metadata"].update({
        "status": "V2_RELEASE_EXACT_NATIVE_DIALOGUE_PENDING_RENDER_AND_FINAL_GATES",
        "runtime_seconds": total_duration, "content_runtime_seconds": content_duration,
        "source_lock_manifest": str(SOURCE_LOCK),
        "subtitle_contract": {"coverage": "47/47", "burned_in": True, "alignment": "EXACT_NATIVE_SOURCE_ASR_V2"},
        "duration_policy": "YOUTUBE_SHORTS_TARGET_MAX_179_DIALOGUE_AND_PLOT_INTEGRITY_PRESERVED",
    })
    project["output"]["path"] = str(OUTPUT)
    project["timeline"]["videoTracks"][0]["clips"] = video_clips
    project["timeline"]["audioTracks"][0]["clips"] = audio_clips
    project["timeline"]["audioTracks"][1]["clips"] = bgm_clips
    project["timeline"]["subtitleTracks"][0]["clips"] = sorted(captions, key=lambda row: row["start"])
    project["expectedDialogueIds"] = sorted(expected_ids)
    project["qingshanAudit"].update({"pipelineStage": "E35_V2_RELEASE_EXACT_NATIVE_DIALOGUE", "sourceCount": len(source_rows), "subtitleDialogueCoverage": "47/47", "repairedSourceAsr": str(FINAL_ASR), "repairedSourceAdmission": str(ADMISSION)})

    SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "schema": "qingshan.e35.v2.locked_source_manifest.v1", "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "LOCKED_FOR_AGENTCUT", "source_count": len(source_rows), "dialogue_line_count": 47,
        "content_duration_seconds": content_duration, "sources": source_rows,
    }
    SOURCE_LOCK.write_text(json.dumps(source_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e35.agentcut_v2_release_build.v1", "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_STRICT_VALIDATE_RENDER_AND_FINAL_GATES", "project": str(PROJECT),
        "project_sha256": sha256(PROJECT), "output": str(OUTPUT), "source_lock": str(SOURCE_LOCK),
        "source_lock_sha256": sha256(SOURCE_LOCK), "source_count": len(source_rows),
        "content_seconds": content_duration, "outro_seconds": 3.0, "total_seconds": total_duration,
        "subtitle_dialogue_coverage": "47/47", "bgm_source_sha256": bgm_sha,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
