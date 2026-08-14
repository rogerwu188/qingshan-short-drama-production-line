#!/usr/bin/env python3
"""Build the 144-second E18R narrative recut AgentCut project."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

try:
    from tools.cut_motivation_gate import required_cut_metadata
except ModuleNotFoundError:  # direct `python tools/build_e18r_narrative_recut_agentcut_project.py`
    from cut_motivation_gate import required_cut_metadata


ROOT = Path(__file__).resolve().parents[1]
BEAT_BUDGETS = {"B01": 22.0, "B02": 24.0, "B03": 24.0, "B04": 28.0, "B05": 28.0, "B06": 18.0}
SHORT_CLIP_INDEX_BY_BEAT = {"B01": 1, "B04": 2, "B06": 1}
PICTURE_OVERRIDES_V12 = {
    "DIA-014": "working_assets/e18r_b03_dia014_r2_clean_crop_v2_20260716/DIA-014.mp4",
}
SEMANTIC_GROUPS = {
    "B01": ["night_delivery", "pastry_box", "wax_seal", "chenji_reaction", "black_cat"],
    "B02": ["stretcher", "wrist_red_knot", "chenji_comparison", "night_road_space"],
    "B03": ["messenger_demand", "pastry_box_conflict", "chenji_refusal", "night_watch_block"],
    "B04": ["carriage_speaker", "wax_seal_gap", "chenji_question", "slip_reaction", "black_cat"],
    "B05": ["red_jade_pendant", "knot_recognition", "concealment_action", "chenji_reaction", "courtyard_space"],
    "B06": ["poison_test", "box_ash", "black_cat_scent", "chenji_decision", "end_hook"],
}
B05_EXTRAS = [
    {
        "id": "E18R-B05-EXTRA-REACTION",
        "source": "assets/e18r_b05_dynamic_coverage_reaction_r4_20260717/B05-COV-REACTION-R4_muted.mp4",
        "after": "DIA-A10",
        "semantic_group": "recognition_reaction_delta",
        "new_information": "白鲤认结后的即时反应",
        "narrative_function": "reaction_delta",
        "emotion_before": "uncertain_attention",
        "emotion_after": "recognized_knot_alarm",
    },
    {
        "id": "E18R-B05-EXTRA-EVIDENCE",
        "source": "assets/e18r_b05_dynamic_coverage_r3_20260717/B05-COV-EVIDENCE.mp4",
        "after": "DIA-022",
        "semantic_group": "red_jade_pendant",
        "new_information": "红玉与线结证据关系",
        "narrative_function": "evidence_insert",
    },
    {
        "id": "E18R-B05-EXTRA-SPACE",
        "source": "assets/e18r_b05_dynamic_coverage_r3_20260717/B05-COV-SPACE.mp4",
        "after": "DIA-025",
        "semantic_group": "courtyard_space",
        "new_information": "人物位置与退路关系",
        "narrative_function": "motivated_space_bridge",
    },
]


def media_duration(path: Path) -> float:
    output = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    ).strip()
    return float(output)


def distribute_video_duration(items: list[dict], budget: float, short_index: int | None = None) -> None:
    short_duration = 0.8 if short_index is not None else 0.0
    scalable_items = [item for index, item in enumerate(items) if index != short_index]
    available = sum(item["available_duration"] for item in scalable_items)
    if short_index is not None and items[short_index]["available_duration"] + 1e-6 < short_duration:
        raise ValueError("short-cut source is shorter than 0.8 seconds")
    scalable_budget = budget - short_duration
    if available + 1e-6 < scalable_budget:
        raise ValueError(f"insufficient unique picture duration: {available:.3f} < {scalable_budget:.3f}")
    scale = scalable_budget / available
    cursor = 0.0
    for index, item in enumerate(items):
        duration = short_duration if index == short_index else item["available_duration"] * scale
        if index == len(items) - 1:
            duration = budget - cursor
        item["start"] = cursor
        item["duration"] = duration
        cursor += duration


def build_project(root: Path, repair_v12: bool = False) -> dict:
    inventory = json.loads((root / "configs/e18r_41line_ordered_source_inventory_v1_not_final_20260717.json").read_text())
    prior = json.loads((root / "configs/e18r_41line_agentcut_project_v10_frame_overlap_fix_not_final_20260717.json").read_text())
    sentence = json.loads((root / "qa/e18r_agentcut_v5_audio_repair_20260717/E18R_AGENTCUT_TRIAL_V10_SENTENCE_COMPLETENESS_20260717.json").read_text())

    sentence_by_id = {item["id"]: item for item in sentence["sentences"]}
    audio_clips = prior["timeline"]["audioTracks"][0]["clips"]
    audio_by_id = {clip["metadata"]["dialogue_id"]: clip for clip in audio_clips}
    expected_ids = [item["dialogue_id"] for item in inventory["items"]]
    if set(expected_ids) != set(sentence_by_id) or set(expected_ids) != set(audio_by_id):
        raise ValueError("inventory, sentence evidence, and repaired audio IDs must match 41/41")

    inventory_by_beat: dict[str, list[dict]] = defaultdict(list)
    for item in inventory["items"]:
        inventory_by_beat[item["beat_id"]].append(item)

    video_clips: list[dict] = []
    audio_out: list[dict] = []
    subtitles: list[dict] = []
    timeline_cursor = 0.0

    for beat_id, budget in BEAT_BUDGETS.items():
        beat = next((row for row in json.loads((root / "configs/e18r_coverage_manifest_v1_20260716.json").read_text())["beats"] if row["beat_id"] == beat_id), {})
        beat_items: list[dict] = []
        group_cycle = SEMANTIC_GROUPS[beat_id]
        for index, source_item in enumerate(inventory_by_beat[beat_id]):
            picture_ref = PICTURE_OVERRIDES_V12.get(source_item["dialogue_id"], source_item["picture"]) if repair_v12 else source_item["picture"]
            picture = (root / picture_ref).resolve()
            beat_items.append({
                "id": f"E18R-RECUT-{source_item['dialogue_id']}",
                "dialogue_id": source_item["dialogue_id"],
                "source": str(picture),
                "available_duration": media_duration(picture),
                "semantic_group": group_cycle[index % len(group_cycle)],
                "new_information": sentence_by_id[source_item["dialogue_id"]]["expected"],
                "narrative_function": "dialogue_action_or_reaction",
                **required_cut_metadata(
                    {**beat, **source_item},
                    label=f"E18R {source_item['dialogue_id']}",
                ),
            })
            if beat_id == "B05":
                for extra in B05_EXTRAS:
                    if extra["after"] == source_item["dialogue_id"]:
                        extra_path = (root / extra["source"]).resolve()
                        beat_items.append({
                            **extra,
                            "dialogue_id": None,
                            "source": str(extra_path),
                            "available_duration": media_duration(extra_path),
                            **required_cut_metadata(extra, label=f"E18R {extra['id']}"),
                        })

        distribute_video_duration(
            beat_items,
            budget,
            SHORT_CLIP_INDEX_BY_BEAT.get(beat_id) if repair_v12 else None,
        )
        for item in beat_items:
            video_clips.append({
                "id": item["id"],
                "source": item["source"],
                "start": round(timeline_cursor + item["start"], 6),
                "in": 0.0,
                "duration": round(item["duration"], 6),
                "metadata": {
                    "episode": "E18R",
                    "beat_id": beat_id,
                    "dialogue_id": item["dialogue_id"],
                    "narrative_function": item["narrative_function"],
                    "new_information": item["new_information"],
                    "semantic_id": item["id"],
                    "semantic_group": item["semantic_group"],
                    "fallback_only": False,
                    "recut_authorization_ref": "CL2X-283",
                    "cut_reason": item["cut_reason"],
                    "cut_reason_note": item.get("cut_reason_note", ""),
                    "scene_id": item["scene_id"],
                    "light_key": item["light_key"],
                    "axis_line": item["axis_line"],
                    "eyeline": item["eyeline"],
                    **({
                        "emotion_before": item["emotion_before"],
                        "emotion_after": item["emotion_after"],
                    } if item["narrative_function"] == "reaction_delta" else {}),
                },
            })

        trimmed_audio: list[dict] = []
        for source_item in inventory_by_beat[beat_id]:
            dialogue_id = source_item["dialogue_id"]
            evidence = sentence_by_id[dialogue_id]
            prior_audio = audio_by_id[dialogue_id]
            segment_starts = [segment["start"] for segment in evidence["segments"]]
            segment_ends = [segment["end"] for segment in evidence["segments"]]
            source_in = max(float(prior_audio.get("in", 0.0)), min(segment_starts) - 0.15)
            source_out = min(float(evidence["source_out"]), max(segment_ends) + 0.15)
            duration = max(0.5, source_out - source_in)
            trimmed_audio.append({
                "dialogue_id": dialogue_id,
                "source": prior_audio["source"],
                "in": source_in,
                "duration": duration,
                "text": evidence["expected"],
                "speaker": prior_audio.get("metadata", {}).get("speaker"),
            })
        speech_duration = sum(item["duration"] for item in trimmed_audio)
        gap = (budget - speech_duration) / (len(trimmed_audio) + 1)
        if gap < 0:
            raise ValueError(f"trimmed {beat_id} dialogue exceeds beat budget")
        audio_cursor = timeline_cursor + gap
        for item in trimmed_audio:
            duration = round(item["duration"], 6)
            audio_out.append({
                "id": f"E18R-RECUT-A-{item['dialogue_id']}",
                "source": item["source"],
                "start": round(audio_cursor, 6),
                "in": round(item["in"], 6),
                "duration": duration,
                "volume": 1.0,
                "transitionIn": {"type": "fade", "duration": 0.02},
                "transitionOut": {"type": "fade", "duration": 0.02},
                "metadata": {"episode": "E18R", "beat_id": beat_id, "dialogue_id": item["dialogue_id"], "speaker": item["speaker"], "silence_trimmed": True},
            })
            subtitles.append({
                "id": f"E18R-RECUT-CAP-{item['dialogue_id']}",
                "dialogue_id": item["dialogue_id"],
                "text": item["text"],
                "start": round(audio_cursor, 6),
                "duration": duration,
                "metadata": {"episode": "E18R", "beat_id": beat_id, "speaker": item["speaker"]},
            })
            audio_cursor += item["duration"] + gap
        timeline_cursor += budget

    # AgentCut's post-render gate requires the encoded audio stream to reach the
    # project end. Move the last complete line into the legal source tail instead
    # of adding digital zero or a synthetic padding bed.
    last_audio = audio_out[-1]
    last_source_duration = media_duration(Path(last_audio["source"]))
    last_duration = last_source_duration - float(last_audio["in"])
    last_start = timeline_cursor - last_duration
    previous_end = audio_out[-2]["start"] + audio_out[-2]["duration"]
    if last_start < previous_end:
        raise ValueError("final dialogue tail would overlap the preceding line")
    last_audio["start"] = round(last_start, 6)
    last_audio["duration"] = round(last_duration, 6)
    subtitles[-1]["start"] = round(last_start, 6)
    subtitles[-1]["duration"] = round(last_duration, 6)

    ambience_tracks: list[dict] = []
    if repair_v12:
        ambience_source = (root / "assets/e18r_b05_same_scene_ambience_repair_20260717/B05_SPACE_AMBIENCE_NO_SPEECH.wav").resolve()
        ambience_cursor = 0.0
        ambience_index = 1
        while ambience_cursor < timeline_cursor - 1e-6:
            duration = min(4.0, timeline_cursor - ambience_cursor)
            ambience_tracks.append({
                "id": f"E18R-RECUT-AMB-{ambience_index:03d}",
                "source": str(ambience_source),
                "start": round(ambience_cursor, 6),
                "in": 0.0,
                "duration": round(duration, 6),
                "volume": 3.025,
                "transitionIn": {"type": "fade", "duration": 0.04},
                "transitionOut": {"type": "fade", "duration": 0.04},
                "metadata": {
                    "episode": "E18R",
                    "kind": "NIGHT_COURTYARD_AMBIENCE",
                    "speech_free": True,
                    "source_qa": "PASS_EXISTING_PRODUCTION_USE",
                    "rollback_allowed": True,
                },
            })
            ambience_cursor += duration
            ambience_index += 1

    revision = "v12" if repair_v12 else "v11"
    output = root / f"exports/e18r/agentcut_narrative_recut_{revision}_subtitled_20260717/E18R_AGENTCUT_NARRATIVE_RECUT_{revision.upper()}_SUBTITLED_NOT_FINAL.mp4"
    return {
        "version": "1.0",
        "background": "black",
        "output": {
            "path": str(output), "width": 720, "height": 1280, "fps": 24,
            "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
            "pixelFormat": "yuv420p", "threads": 4,
        },
        "timeline": {
            "videoTracks": [{"id": f"E18R_NARRATIVE_RECUT_{revision.upper()}", "clips": video_clips}],
            "audioTracks": [
                {"id": "E18R_DIALOGUE_TRIMMED_COMPLETE_41", "clips": audio_out},
                *([{"id": "E18R_NIGHT_COURTYARD_AMBIENCE_V12", "clips": ambience_tracks}] if repair_v12 else []),
            ],
            "subtitleTracks": [{
                "id": f"E18R_ZH_CN_BURNIN_{revision.upper()}", "enabled": True,
                "style": {
                    "font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                    "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                    "alignment": "bottom-center", "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15,
                },
                "clips": subtitles,
            }],
        },
        "requireBurnedSubtitles": True,
        "expectedDialogueIds": expected_ids,
        "runtimePolicy": {"allowShorter": True, "paddingForbidden": True, "onCoverageGap": "fail"},
        "metadata": {
            "episode": "E18R", "authorization_ref": "CL2X-283", "audience_gate_ref": "CL2X-284",
            "target_runtime_seconds": 144.0, "narrative_gate_ref": "CL2X-282", "revision": revision.upper(), "final": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--repair-v12", action="store_true")
    args = parser.parse_args()
    project = build_project(ROOT, repair_v12=args.repair_v12)
    if args.out is None:
        revision = "v12" if args.repair_v12 else "v11"
        args.out = ROOT / f"configs/e18r_agentcut_narrative_recut_{revision}_subtitled_not_final_20260717.json"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out), "runtime": 144.0,
        "video_clips": len(project["timeline"]["videoTracks"][0]["clips"]),
        "audio_clips": len(project["timeline"]["audioTracks"][0]["clips"]),
        "subtitles": len(project["timeline"]["subtitleTracks"][0]["clips"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
