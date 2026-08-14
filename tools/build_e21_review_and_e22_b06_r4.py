#!/usr/bin/env python3
"""Start E21 six-source review and the isolated E22 B06 reference-source fix."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

E21_SOURCES = {
    "B01": ("working_assets/e21_standard_storyboard_rework_r4_b01_object_free_20260719/candidates/E21_E21-B01-STANDARD-STORYBOARD-V1-R4-OBJECT-FREE_19943dd4-0678-4f5a-a505-efd08a94057d.mp4", "ed287dfa1389e87263e888de366019d4ac5ebc544aaacc91a1b93bd061b6653a"),
    "B02": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B02-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_8d9be0be-6c89-41a4-9297-8b68632207e3.mp4", "ffa012b41a244ede7e852708a9a2ea6959b4808d008acc08cc10412b7860f1af"),
    "B03": ("working_assets/e21_standard_storyboard_rework_r2_textsafe_20260719/candidates/E21_E21-B03-STANDARD-STORYBOARD-V1-R2-TEXTSAFE_50c5f8d9-05fe-452c-89ed-443520fae581.mp4", "d4f6181b4be623e8e93bb4fd70b9333a587595dab80fe960e7ea81d3637a3944"),
    "B04": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B04-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_f37786dc-2c00-4285-a58e-c1710a0a9da2.mp4", "1f719aa6818d51d8e6e22c272465f669581580a471f571abfcef217d42bd08c6"),
    "B05": ("working_assets/e21_standard_storyboard_rework_r3_visual_only_20260719/candidates/E21_E21-B05-STANDARD-STORYBOARD-V1-R3-VISUAL-ONLY_b612bfc5-b1c1-41c5-b41a-145b0bf19e5e.mp4", "04832a29828ef78907fe4967e774fee9dd5f8d77aa73136c7a017b2752237fe5"),
    "B06": ("working_assets/e21_standard_storyboard_rework_v1_20260719/candidates/E21_E21-B06-STANDARD-STORYBOARD-V1_8e5e6737-2dec-4180-80df-5c321fead9a0.mp4", "329734a073bc12c01b305b266fba81f242f664a6a376f7a33f11c0383bcd0be6"),
}


def build_e21() -> tuple[Path, Path]:
    qa_dir = ROOT / "qa/e21_standard_storyboard_rework_ai_review_20260719"
    request = qa_dir / "E21_AI_REVIEW_REQUEST.json"
    config_path = ROOT / "configs/E21_standard_storyboard_ai_review_batch_20260719.json"
    qa_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for beat, (relative, digest) in E21_SOURCES.items():
        items.append({
            "path": str(ROOT / relative),
            "scope": "shot",
            "kind": "video",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": f"E21-STANDARD-STORYBOARD-{beat}",
            "metadata": {
                "episode": "E21",
                "beat_id": beat,
                "candidate_sha256": digest,
                "acceptance_mode": "CL2X356_STANDARD_STORYBOARD_SOURCE_GATE",
                "review_focus": ["intentional shot diversity", "natural motivated cuts", "character identity continuity", "story action clarity", "no readable or pseudo-readable text", "scene authority"],
            },
            "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    request.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": "E21",
        "scene_contract_ref": "configs/e21_scene_state_v1_20260718.json",
        "output_dir": str(qa_dir.relative_to(ROOT)),
        "qa_dir": str(qa_dir.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Review all six admitted E21 standard-storyboard sources in one batch.",
        "tasks": [{
            "task_key": "E21-STANDARD-STORYBOARD-SIX-SOURCE-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": "E21-S01-MEDICAL-HALL-THRESHOLD",
            "visual_zone": "STANDARD_STORYBOARD_SOURCE_GATE",
            "prompt_file": "workflow/prompts/e21_standard_storyboard_rework_r4_b01_object_free_20260719/E21-B01-STANDARD-STORYBOARD-V1-R4-OBJECT-FREE.txt",
            "video": E21_SOURCES["B01"][0],
            "command": [".ai_review_env/bin/qingshan-review", "review-many", str(request.relative_to(ROOT))],
            "report": str((qa_dir / "E21_AI_REVIEW_WRAPPER.json").relative_to(ROOT)),
        }],
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return request, config_path


def build_e22() -> tuple[Path, Path, Path]:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    adjudication = ROOT / "qa/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/E22_B05_OCR_MACHINE_ADJUDICATION.json"
    adjudication.write_text(json.dumps({
        "schema": "qingshan.machine_qa_adjudication.v1",
        "episode": "E22",
        "source_id": "B05",
        "decision": "PASS_MACHINE_ADJUDICATION",
        "confidence": 0.98,
        "raw_ocr_status": "FAIL",
        "raw_failure": "One isolated two-letter recognition 'OD' at 9.0s.",
        "visual_finding": "Exact 9.0s frame contains a woman's face, hair ornament, clothing embroidery and candle bokeh; no readable text or text-bearing object is visible.",
        "evidence_frame": str(ROOT / "qa/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/evidence_frames/B05_09s.jpg"),
        "contact_sheet": str(ROOT / "qa/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/E22_B05_B06_OCR_EVIDENCE_CONTACT.jpg"),
        "failed_items": [],
        "rollback": "Restore raw OCR FAIL and exclude B05 if any later full-cut OCR detects persistent text at this source range.",
        "recorded_at": now,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = json.loads((ROOT / "configs/E22_standard_storyboard_rework_r3_b05_b06_object_free_20260719.json").read_text(encoding="utf-8"))
    task = dict(next(row for row in base["tasks"] if row.get("source_id") == "B06"))
    prompt = ROOT / "workflow/prompts/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN.txt"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("""这是《青山》E22 B06 的 Seedance 2.0 纯视觉动作母版。场景严格为 Buddhist hall 室内，clear afternoon，暖色自然日光从格窗侧面进入。参考图只用于四名人物的身份、脸、服装和站位；忽略并禁止参考图中的猫、桌面、纸张和证物。禁止夜景、月亮、月光、雨、雾和改换地点。

本段完全不出现桌子、证物、地图、纸张、书页、账册、牌匾、佛幡、经文、墙字、印章、数字或任何文字载体。四个人始终站在空旷的素面室内地面上，背景只允许木墙、格窗和没有图案的柔焦陈设。

15 秒六镜头只用人物动作表现发现幕后者：陈迹从三人之间走向画面中心；白鲤和云妃分别从不同方向注视他；陈迹用三个方向的手势表示三方被操纵；三人的视线被引向同一画外高处；云妃从镇定转为警觉；四人最终共同转向同一画外方向，明确意识到更高层幕后者存在。无对白、无人声、无口型台词，只保留脚步、衣料和室内环境声，后续 AgentCut 复用已通过对白音轨。

写实美剧式古装悬疑短剧，动作原生速度，六个镜头由动作、视线和新信息驱动。禁止慢动作、静止补时、循环、分身、额外肢体、穿模和身份漂移。画面上中下全程禁止字幕、标题、可读文字、伪文字、数字、字母、水印、Logo和背景音乐；所有背景必须为无图案素面材质。
""", encoding="utf-8")
    task.update({
        "task_key": "E22-B06-STANDARD-STORYBOARD-V1-R4-REFERENCE-CLEAN",
        "prompt_file": str(prompt.relative_to(ROOT)),
        "reference_images": [str(ROOT / "working_assets/e22_full_dialogue_parallel_20260719/reference_stills/B05.png")],
        "metadata": dict(task.get("metadata") or {}, retry_reason="B06 reference image contained a readable map; replace the reference and ban all table/evidence shots"),
    })
    config_path = ROOT / "configs/E22_standard_storyboard_rework_r4_b06_reference_clean_20260719.json"
    base.update({
        "max_retries": 0,
        "base_batch_note": "Failed-only B06 reference-source repair; preserve B01/B02/B03/B04 and machine-adjudicated B05.",
        "output_dir": "working_assets/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719/candidates",
        "qa_dir": "qa/e22_standard_storyboard_rework_r4_b06_reference_clean_20260719",
        "tasks": [task],
    })
    config_path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return adjudication, prompt, config_path


def main() -> int:
    e21_request, e21_config = build_e21()
    adjudication, prompt, e22_config = build_e22()
    print(json.dumps({"status": "PASS", "e21_request": str(e21_request), "e21_config": str(e21_config), "e22_adjudication": str(adjudication), "e22_prompt": str(prompt), "e22_config": str(e22_config)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
