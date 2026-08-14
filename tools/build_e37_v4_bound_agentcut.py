#!/usr/bin/env python3
import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v3_repair_subtitled_outro_staging_20260803.json"
OUTPUT = ROOT / "configs/e37_agentcut_v4_canonical_replacements_subtitled_outro_20260803.json"
MEDIA_DIR = ROOT / "working_assets/e37_agentcut_replacement_v4_20260803/bound_canonical_segments"
ACTION = ROOT / "working_assets/e37_action_replacement_v5_20260803/accepted_action_sequence_v2/E37_ACCEPTED_ACTION_SEQUENCE_V5_TRIMMED_V2.mp4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replacement_clip(source: Path, start: float, duration: float, segment_id: str, cut_reason: str) -> dict:
    return {
        "id": f"E37-{segment_id}-CANONICAL-REPLACEMENT-V4",
        "source": str(source),
        "start": start,
        "in": 0.0,
        "duration": duration,
        "metadata": {
            "episode": "E37",
            "segment_id": segment_id,
            "admission": "PASS_ACCEPTED_CANONICAL_REPLACEMENT_V4",
            "source_sha256": sha(source),
            "cut_reason": cut_reason,
            "camera_policy": "MOTIVATED_HARD_COMPOSITION_CHANGE_NO_OPTICAL_SWAY",
        },
    }


def replacement_audio(source: Path, start: float, duration: float, segment_id: str) -> dict:
    return {
        "id": f"E37-{segment_id}-CANONICAL-REPLACEMENT-V4-AUDIO",
        "source": str(source),
        "start": start,
        "in": 0.0,
        "duration": duration,
        "volume": 1.0,
        "transitionIn": {"type": "fade", "duration": 0.01},
        "transitionOut": {"type": "fade", "duration": 0.01},
        "metadata": {
            "episode": "E37",
            "segment_id": segment_id,
            "audio_source": "MODEL_NATIVE_FROM_ACCEPTED_CANONICAL_REPLACEMENT_V4",
            "source_sha256": sha(source),
        },
    }


def main() -> None:
    project = json.loads(SOURCE.read_text())
    project = copy.deepcopy(project)
    u02 = MEDIA_DIR / "E37_U02_S1_CANONICAL_REPLACEMENT_V4.mp4"
    u03 = MEDIA_DIR / "E37_U03_S1_CANONICAL_REPLACEMENT_V4.mp4"
    u03s4 = MEDIA_DIR / "E37_U03_S4_CANONICAL_REPLACEMENT_V4.mp4"
    for path in (u02, u03, u03s4, ACTION):
        if not path.is_file():
            raise SystemExit(f"missing bound source: {path}")

    video = project["timeline"]["videoTracks"][0]["clips"]
    by_id = {c["metadata"]["segment_id"]: c for c in video}
    replacements = {
        "U02-S1": replacement_clip(u02, 10.04, 8.04, "U02-S1", "CANONICAL_LINE3_OBJECT_BRIDGE_LINE4"),
        "U03-S1": replacement_clip(u03, 28.12, 8.04, "U03-S1", "CANONICAL_LINE7_TO_LINE8_HANDOFF"),
        "U03-S4": replacement_clip(u03s4, 55.24, 7.04, "U03-S4", "CANONICAL_JIAOTU_LINE13_LINE14_RESPONSE"),
    }
    action_ids = {"U04-S1", "U05-S1", "U05-S2", "U06-S1"}
    action_clip = replacement_clip(ACTION, 62.28, 31.16, "U04-U06-S1-ACTION", "ATOMIC_ACTION_CAUSAL_CHAIN_8_OF_8")
    rebound_video = []
    for clip in video:
        segment_id = clip["metadata"]["segment_id"]
        if segment_id in replacements:
            rebound_video.append(replacements[segment_id])
        elif segment_id == "U04-S1":
            rebound_video.append(action_clip)
        elif segment_id not in action_ids:
            rebound_video.append(clip)
    project["timeline"]["videoTracks"][0]["clips"] = rebound_video

    audio = project["timeline"]["audioTracks"][0]["clips"]
    audio_replacements = {
        "U02-S1": replacement_audio(u02, 10.04, 8.04, "U02-S1"),
        "U03-S1": replacement_audio(u03, 28.12, 8.04, "U03-S1"),
        "U03-S4": replacement_audio(u03s4, 55.24, 7.04, "U03-S4"),
    }
    action_audio = replacement_audio(ACTION, 62.28, 31.16, "U04-U06-S1-ACTION")
    rebound_audio = []
    for clip in audio:
        segment_id = clip["metadata"]["segment_id"]
        if segment_id in audio_replacements:
            rebound_audio.append(audio_replacements[segment_id])
        elif segment_id == "U04-S1":
            rebound_audio.append(action_audio)
        elif segment_id not in action_ids:
            rebound_audio.append(clip)
    project["timeline"]["audioTracks"][0]["clips"] = rebound_audio

    timing = {
        "E37-L004": (14.09, 3.71),
        "E37-L007": (28.57, 2.95),
        "E37-L013": (55.69, 2.95),
        "E37-L014": (58.79, 2.95),
    }
    subtitles = project["timeline"]["subtitleTracks"][0]["clips"]
    for subtitle in subtitles:
        if subtitle["dialogue_id"] in timing:
            subtitle["start"], subtitle["duration"] = timing[subtitle["dialogue_id"]]

    project["metadata"]["status"] = "E37_CANONICAL_REPLACEMENT_V4_BOUND_RENDER_PENDING"
    project["metadata"]["agentcut_required_version"] = "0.9.18"
    project["metadata"]["replacement_v4"] = {
        "canonical_segment_count": 3,
        "action_atomic_unit_count": 8,
        "action_timeline_window": [62.28, 93.44],
        "dialogue_preservation": "U06-S2_AND_ALL_OTHER_CANONICAL_NATIVE_DIALOGUE_UNCHANGED",
        "opening_analysis_reel_binding": "PROHIBITED_NONCHRONOLOGICAL_ANALYSIS_REEL_ONLY",
        "sources": [
            {"segment_id": key, "path": clip["source"], "sha256": clip["metadata"]["source_sha256"]}
            for key, clip in replacements.items()
        ] + [{"segment_id": "U04-U06-S1-ACTION", "path": str(ACTION), "sha256": sha(ACTION)}],
    }
    project["qingshanAudit"]["releaseEligible"] = False
    project["qingshanAudit"]["releaseBlock"] = "V4 canonical replacements are bound; render and full-cut direct-watch QA remain required."
    project["qingshanAudit"]["status"] = "PASS_CANONICAL_REPLACEMENTS_BOUND_RENDER_PENDING"
    project["output"]["path"] = str(ROOT / "exports/e37/agentcut_v4_canonical_replacements_subtitled_outro_20260803/E37_AGENTCUT_V4_CANONICAL_REPLACEMENTS_SUBTITLED_OUTRO_NOT_FINAL.mp4")
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "out": str(OUTPUT), "video_clips": len(rebound_video), "audio_clips": len(rebound_audio), "subtitles": len(subtitles)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
