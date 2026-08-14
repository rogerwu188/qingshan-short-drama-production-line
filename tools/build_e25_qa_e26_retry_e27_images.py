#!/usr/bin/env python3
"""Build the current E25 QA, E26 failed-only retry, and E27 image batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_e25_qa() -> Path:
    video = ROOT / "exports/e25/agentcut_v2_standard_storyboard_coverage_20260719/E25_AGENTCUT_V2_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
    project = "configs/e25_agentcut_project_v2_standard_storyboard_coverage_20260719.json"
    beat_sheet = "configs/e25_dialogue_beat_sheet_v3_us_drama_cl2x307_20260719.json"
    qa_dir = ROOT / "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719"
    request = qa_dir / "E25_FULL_CUT_AI_REVIEW_REQUEST.json"
    write_json(request, {"items": [{
        "path": str(video),
        "scope": "full_cut",
        "kind": "video",
        "importance": "critical",
        "pass_score": 4.5,
        "clip_id": "E25-AGENTCUT-V2-STANDARD-STORYBOARD-FULL-CUT",
        "metadata": {
            "episode": "E25",
            "candidate_sha256": sha(video),
            "review_focus": [
                "ordinary human viewing experience",
                "story clarity and pacing",
                "US drama visual grammar",
                "character identity continuity",
                "motivated cuts and native-speed action",
                "no readable or pseudo-readable text"
            ]
        },
        "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
        "run_regression_ci": True,
        "use_existing_tools": True
    }]})
    common = {
        "tool_type": "ai_review",
        "scene_id": "E25-S01-SNOW-ROAD-INN",
        "prompt_file": "workflow/prompts/e25_parallel_video_v1_locked_refs_20260719/DIA-001.txt",
        "video": str(video.relative_to(ROOT)),
    }
    tasks = [
        {**common, "task_key": "E25-V2-ACTION-REALTIME", "visual_zone": "WHOLE_FILM_ACTION_REALTIME", "report": "workflow/tasks/E25_V2_ACTION_REALTIME_WRAPPER_20260719.json", "command": ["python3", "tools/generate_agentcut_action_realtime_audit.py", "--project", project, "--video", "{video}", "--out", "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_ACTION_REALTIME_AUDIT_V2.json"]},
        {**common, "task_key": "E25-V2-FRAME-CADENCE", "visual_zone": "WHOLE_FILM_FRAME_CADENCE", "report": "workflow/tasks/E25_V2_FRAME_CADENCE_WRAPPER_20260719.json", "command": ["python3", "tools/frame_cadence_audit.py", "--video", "{video}", "--out", "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_FRAME_CADENCE_AUDIT_V2.json"]},
        {**common, "task_key": "E25-V2-ASR-SENTENCE", "visual_zone": "WHOLE_FILM_ASR_SENTENCE", "report": "workflow/tasks/E25_V2_ASR_SENTENCE_WRAPPER_20260719.json", "command": ["python3", "tools/audit_e18r_agentcut_final_asr.py", "--video", "{video}", "--project", project, "--beat-sheet", beat_sheet, "--out-asr", "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_FINAL_ASR_AUDIT_V2.json", "--out-sentences", "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_FINAL_SENTENCE_COMPLETENESS_V2.json"]},
        {**common, "task_key": "E25-V2-FULL-DURATION-OCR", "visual_zone": "WHOLE_FILM_FULL_DURATION_OCR", "report": "workflow/tasks/E25_V2_FULL_DURATION_OCR_WRAPPER_20260719.json", "command": ["python3", "tools/final_video_ocr_audit.py", "--video", "{video}", "--out", "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_FINAL_VIDEO_OCR_AUDIT_V2.json", "--interval", "0.5", "--subtitle-band", "0.30", "--exclude-final-seconds", "0", "--allow-text", "青山", "--forbid-text", "__FORBIDDEN_TEXT__"]},
        {**common, "task_key": "E25-V2-FULL-CUT-AI-REVIEW", "visual_zone": "WHOLE_FILM_HUMAN_EXPERIENCE", "report": "qa/e25_agentcut_v2_standard_storyboard_coverage_20260719/E25_AI_REVIEW_WRAPPER.json", "command": [".ai_review_env/bin/qingshan-review", "review-many", str(request.relative_to(ROOT))]},
    ]
    out = ROOT / "configs/E25_agentcut_v2_standard_storyboard_parallel_qa_20260719.json"
    write_json(out, {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E25",
        "scene_contract_ref": "configs/e25_scene_state_v3_us_drama_cl2x307_20260719.json",
        "qa_dir": str(qa_dir.relative_to(ROOT)),
        "output_dir": str(qa_dir.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Run all independent whole-film gates concurrently after E25 AgentCut V2 render.",
        "tasks": tasks,
    })
    return out


def build_e26_retry() -> Path:
    source = json.loads((ROOT / "configs/E26_standard_storyboard_rework_v1_20260719.json").read_text(encoding="utf-8"))
    failed_beats = {"B01", "B02", "B03", "B04"}
    prompt_dir = ROOT / "workflow/prompts/e26_standard_storyboard_failed_only_r1_textsafe_20260719"
    tasks = []
    for original in source["tasks"]:
        beat = original["source_id"]
        if beat not in failed_beats:
            continue
        task = json.loads(json.dumps(original, ensure_ascii=False))
        task["task_key"] = f"E26-{beat}-STANDARD-STORYBOARD-R1-TEXTSAFE"
        base_prompt = (ROOT / original["prompt_file"]).read_text(encoding="utf-8").rstrip()
        repair = (
            "\n\n本次只修复画面文字污染：所有纸张、账册、封皮、木牌、墙面、布幡和器物表面必须保持完全素面，"
            "不得出现任何笔画状、字母状、数字状或书法状纹理。镜头避开牌匾正面和纸页正面；"
            "剧情证物只用烧焦轮廓、空白纸色、封闭素面册和人物动作表达。不要新增任何文字载体，"
            "不要改变人物、地点、时段、天气、对白、事件和镜头顺序。"
        )
        prompt_path = prompt_dir / f"{task['task_key']}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(base_prompt + repair + "\n", encoding="utf-8")
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task["metadata"]["retry_reason"] = "OCR_TEXT_CONTAMINATION_ONLY"
        tasks.append(task)
    out = ROOT / "configs/E26_standard_storyboard_failed_only_r1_textsafe_20260719.json"
    write_json(out, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E26",
        "directive_refs": ["CL2X-376", "CL2X-378", "FAILED_ONLY_RETRY_POLICY"],
        "scene_contract_ref": source["scene_contract_ref"],
        "script_readiness_report": source["script_readiness_report"],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": 4,
        "max_retries": 0,
        "output_dir": "working_assets/e26_standard_storyboard_failed_only_r1_textsafe_20260719/candidates",
        "qa_dir": "qa/e26_standard_storyboard_failed_only_r1_textsafe_20260719",
        "base_batch_note": "Retry only B01-B04 OCR failures concurrently; preserve B05-B06 passes.",
        "preserved_passes": ["E26-B05-STANDARD-STORYBOARD-V1", "E26-B06-STANDARD-STORYBOARD-V1"],
        "tasks": tasks,
    })
    return out


def build_e27_images() -> Path:
    manifest_path = ROOT / "configs/E27_parallel_prompt_manifest_v3_20260719.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = []
    for source in manifest["image_tasks"]:
        task = dict(source)
        task.update({
            "tool_type": "image_generation",
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "1K",
        })
        tasks.append(task)
    out = ROOT / "configs/E27_v1_six_images_bound_parallel_20260719.json"
    write_json(out, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E27",
        "source_sheet": manifest["source_sheet"],
        "scene_contract_ref": manifest["scene_state"],
        "script_readiness_report": "qa/e27_preproduction_20260719/E27_SCRIPT_READINESS_GATE_V3.json",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": 6,
        "max_retries": 0,
        "output_dir": "working_assets/e27_v1_six_images_20260719/candidates",
        "qa_dir": "qa/e27_v1_six_images_20260719",
        "base_batch_note": "Submit all six E27 script-locked keyframes concurrently after readiness PASS.",
        "tasks": tasks,
    })
    return out


def main() -> int:
    outputs = [build_e25_qa(), build_e26_retry(), build_e27_images()]
    print(json.dumps({"status": "PASS", "outputs": [str(path) for path in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
