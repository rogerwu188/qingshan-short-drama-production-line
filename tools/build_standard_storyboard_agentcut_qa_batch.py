#!/usr/bin/env python3
"""Build one concurrent whole-cut QA batch for a storyboard AgentCut render."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _abs(path):
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _portable(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build(episode, video, project, beat_sheet, scene_state, out_dir, out_config):
    video = _abs(video)
    project = _abs(project)
    beat_sheet = _abs(beat_sheet)
    scene_state = _abs(scene_state)
    out_dir = _abs(out_dir)
    out_config = _abs(out_config)
    for path in (video, project, beat_sheet, scene_state):
        if not path.is_file():
            raise FileNotFoundError(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_config.parent.mkdir(parents=True, exist_ok=True)

    source_contract = json.loads(scene_state.read_text())
    source_scenes = source_contract.get("scene_state") or []
    if not source_scenes:
        raise ValueError("scene_state is empty")
    authority_contract = out_dir / f"{episode}_FULL_CUT_MULTI_SCENE_AUTHORITY.json"
    authority_prompt = out_dir / f"{episode}_FULL_CUT_MULTI_SCENE_QA_PROMPT.txt"
    locations = [str(row.get("location") or "") for row in source_scenes]
    location_tokens = [token for row in source_scenes for token in row.get("location_prompt_tokens", [])]
    composite_scene = {
        "scene_id": f"{episode}-FULL-CUT",
        "location": " / ".join(filter(None, locations)),
        "time_of_day": "deep night" if any("night" in str(row.get("time_of_day", "")).lower() for row in source_scenes) else str(source_scenes[0].get("time_of_day")),
        "weather": "indoor dry air",
        "event_summary": "Full-cut post-render QA across all script-authorized scenes.",
        "location_prompt_tokens": location_tokens,
    }
    authority_contract.write_text(json.dumps({"episode": episode, "scene_state": [composite_scene]}, ensure_ascii=False, indent=2) + "\n")
    authority_prompt.write_text(f"Post-render whole-cut QA for {', '.join(location_tokens)}.\n")

    request = out_dir / f"{episode}_FULL_CUT_AI_REVIEW_REQUEST.json"
    review_report = out_dir / f"{episode}_FULL_CUT_AI_REVIEW_WRAPPER.json"
    request.write_text(json.dumps({"items": [{
        "path": str(video),
        "scope": "full_cut",
        "kind": "video",
        "importance": "critical",
        "pass_score": 4.5,
        "clip_id": f"{episode}-AGENTCUT-STANDARD-STORYBOARD-FULL-CUT",
        "metadata": {
            "episode": episode,
            "candidate_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "agentcut_project": str(project),
            "scene_state": str(scene_state),
            "review_focus": [
                "ordinary human viewing experience",
                "story clarity and pacing",
                "character identity continuity",
                "motivated cuts and native-speed action",
                "dialogue intelligibility and sentence completeness",
                "no readable or pseudo-readable text",
            ],
        },
        "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
        "run_regression_ci": True,
        "use_existing_tools": True,
    }]}, ensure_ascii=False, indent=2) + "\n")

    common = {
        "tool_type": "ai_review",
        "scene_id": f"{episode}-FULL-CUT",
        "prompt_file": _portable(authority_prompt),
        "video": _portable(video),
    }
    tasks = [
        {**common, "task_key": f"{episode}-ACTION-REALTIME", "visual_zone": "WHOLE_FILM_ACTION_REALTIME",
         "report": _portable(out_dir / f"{episode}_ACTION_REALTIME_WRAPPER.json"),
         "command": ["python3", "tools/generate_agentcut_action_realtime_audit.py", "--project", _portable(project), "--video", "{video}", "--out", _portable(out_dir / f"{episode}_ACTION_REALTIME_AUDIT.json")]},
        {**common, "task_key": f"{episode}-FRAME-CADENCE", "visual_zone": "WHOLE_FILM_FRAME_CADENCE",
         "report": _portable(out_dir / f"{episode}_FRAME_CADENCE_WRAPPER.json"),
         "command": ["python3", "tools/frame_cadence_audit.py", "--video", "{video}", "--out", _portable(out_dir / f"{episode}_FRAME_CADENCE_AUDIT.json")]},
        {**common, "task_key": f"{episode}-ASR-SENTENCE", "visual_zone": "WHOLE_FILM_ASR_SENTENCE",
         "report": _portable(out_dir / f"{episode}_ASR_SENTENCE_WRAPPER.json"),
         "command": ["python3", "tools/audit_storyboard_agentcut_asr.py", "--video", "{video}", "--project", _portable(project), "--beat-sheet", _portable(beat_sheet), "--out-asr", _portable(out_dir / f"{episode}_FINAL_ASR_AUDIT.json"), "--out-sentences", _portable(out_dir / f"{episode}_FINAL_SENTENCE_COMPLETENESS.json")]},
        {**common, "task_key": f"{episode}-FULL-DURATION-OCR", "visual_zone": "WHOLE_FILM_FULL_DURATION_OCR",
         "report": _portable(out_dir / f"{episode}_FULL_DURATION_OCR_WRAPPER.json"),
         "command": ["python3", "tools/final_video_ocr_audit.py", "--video", "{video}", "--out", _portable(out_dir / f"{episode}_FINAL_VIDEO_OCR_AUDIT.json"), "--interval", "0.5", "--subtitle-band", "0.30", "--exclude-final-seconds", "0", "--allow-text", "青山", "--forbid-text", "__FORBIDDEN_TEXT__"]},
        {**common, "task_key": f"{episode}-FULL-CUT-AI-REVIEW", "visual_zone": "WHOLE_FILM_HUMAN_EXPERIENCE",
         "report": _portable(review_report),
         "command": [".ai_review_env/bin/qingshan-review", "review-many", _portable(request)]},
    ]
    config = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "scene_contract_ref": _portable(authority_contract),
        "multi_scene_contract_ref": _portable(scene_state),
        "scene_authority_mode": "MULTI_SCENE_POST_RENDER_QA",
        "qa_dir": _portable(out_dir),
        "output_dir": _portable(out_dir),
        "max_retries": 0,
        "parallel_submission": True,
        "concurrency": len(tasks),
        "base_batch_note": f"Run all {len(tasks)} independent whole-film gates concurrently after AgentCut render.",
        "tasks": tasks,
    }
    out_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return {"status": "PASS", "episode": episode, "tasks": len(tasks), "config": str(out_config)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--scene-state", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--out-config", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.episode, args.video, args.project, args.beat_sheet, args.scene_state, args.out_dir, args.out_config), ensure_ascii=False))


if __name__ == "__main__":
    main()
