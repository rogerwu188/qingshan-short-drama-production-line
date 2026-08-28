#!/usr/bin/env python3
"""Build the zero-POST E44 v5 A2 repair batch for burned-in text only."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from compile_grouped_seedance_manifest import validate_model_prompt
from shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
QA = ROOT / "qa/e44_v5_a2_burned_text_repairs"
SOURCE = PROD / "E44_V5_TRANSACTIONAL_VIDEO_MANIFEST_AUTHORIZED_V1.json"
PROMPT_DIR = PROD / "video_prompts_a2_burned_text_repairs"
OUT = PROD / "E44_V5_A2_BURNED_TEXT_REPAIRS_PRECHECK_V1.json"
TARGETS = {
    "E44-VU-003": "qa/e44_v5_video_units/burned_text_evidence/E44-VU-003_6p0s.png",
    "E44-VU-010": "qa/e44_v5_video_units/burned_text_evidence/E44-VU-010_2p0s.png",
    "E44-VU-022": "qa/e44_v5_video_units/burned_text_evidence/E44-VU-022_1p0s.png",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def isolate_visible_text(prompt: str) -> str:
    marker = "【节拍内连续性硬合同】"
    if marker not in prompt:
        raise ValueError("compiled prompt lacks internal continuity section")
    contract = (
        "【像素文字隔离硬合同】对白只存在于人物现场发声和同任务原生音轨，绝不转写到画面。"
        "从第一帧到最后一帧，画面每个像素都不得出现汉字、字母、数字、标点、字幕、对白转写、"
        "标题卡、匾额、招牌、纸面书写、墙面书写、LOGO或水印；背景木牌、门额、纸张和墙面只能是"
        "无字自然材质。说话仅用同步口型、呼吸、眼神与身体反应表达。镜头下方和画面中央必须始终"
        "保持干净，不得生成任何白字、描边字或悬浮文字。\n"
    )
    return (
        prompt.replace(marker, contract + marker, 1)
        + "\n【本次技术修复防复犯】上一候选因把对白烧录成中文字幕而被拒绝。"
        "本次必须听见原对白但绝不可看见任何字符；任一帧出现可读字符即失败。"
    )


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_unit = {row["unit_id"]: row for row in source["tasks"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    audit = []
    for uid, evidence_ref in TARGETS.items():
        original = by_unit[uid]
        old_prompt = ROOT / original["prompt_file"]
        media = ROOT / f"working_assets/e44_v5_video_units_a1/{uid}.mp4"
        evidence = ROOT / evidence_ref
        for required in (old_prompt, media, evidence):
            if not required.is_file():
                raise FileNotFoundError(required)
        rewritten = isolate_visible_text(old_prompt.read_text(encoding="utf-8"))
        prompt_path = PROMPT_DIR / f"{uid}.txt"
        prompt_path.write_text(rewritten, encoding="utf-8")
        report = validate_model_prompt(rewritten, source_id=f"{uid}-A2-BURNED-TEXT")
        if report["status"] != "PASS":
            raise ValueError(f"{uid} repaired prompt invalid: {report['failures']}")
        task = copy.deepcopy(original)
        task.update({
            "task_key": f"{uid}-VIDEO-A2-BURNED-TEXT-REPAIR",
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "model_prompt_contract": report,
            "retry_attempt": 2,
            "creative_attempt_ordinal": 2,
            "paid_attempt": 2,
            "provider_post_allowed": False,
            "remote_task_id": None,
            "prior_prompt_sha256": [original["prompt_sha256"]],
            "same_creative_prompt_intentional": False,
            "content_attempt_consumed_by_prior_failure": True,
            "prior_failure_classifications": ["PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT"],
            "material_change_from_prior_attempt": "Added a dedicated pixel-level text-isolation contract, explicitly keeping dialogue only in native audio and forbidding visible characters in every image region and material surface.",
            "do_not_repeat": [
                "Do not render dialogue as captions, subtitles, signs, title cards, overlays, or any visible characters.",
                "Do not reuse the A1 prompt SHA.",
            ],
        })
        failure = {
            "schema": "qingshan.video_content_failure_memory.v1",
            "episode": "E44",
            "version": "v5",
            "unit_id": uid,
            "recorded_at": now(),
            "status": "RECORDED_CONTENT_FAILURE_RETRY_ALLOWED",
            "failure_classification": "PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT",
            "prior_task_key": original["task_key"],
            "prior_prompt_sha256": original["prompt_sha256"],
            "candidate": rel(media),
            "candidate_sha256": sha(media),
            "evidence_ref": evidence_ref,
            "evidence_sha256": sha(evidence),
            "do_not_repeat": task["do_not_repeat"],
            "creative_attempt_consumed": 1,
            "next_creative_attempt": 2,
            "maximum_creative_attempts": 3,
        }
        failure_path = QA / f"{uid}_A1_FAILURE_MEMORY_V1.json"
        write(failure_path, failure)
        task["failure_memory"] = {"ref": rel(failure_path), "sha256": sha(failure_path)}
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)
        audit.append({
            "unit_id": uid,
            "status": "PASS",
            "prior_prompt_sha256": original["prompt_sha256"],
            "repair_prompt_sha256": task["prompt_sha256"],
            "materially_changed": original["prompt_sha256"] != task["prompt_sha256"],
            "evidence_ref": evidence_ref,
        })

    gate = {
        "schema": "qingshan.e44.v5.a2_burned_text_prompt_gate.v1",
        "episode": "E44",
        "recorded_at": now(),
        "status": "PASS",
        "task_count": len(tasks),
        "all_materially_changed": all(row["materially_changed"] for row in audit),
        "pre_submit_scope": "FULL_ORIGINAL_CREATIVE_CONTINUITY_PLUS_PIXEL_TEXT_ISOLATION",
        "rows": audit,
        "provider_post_count": 0,
    }
    gate_path = QA / "E44_V5_A2_BURNED_TEXT_PROMPT_GATE_V1.json"
    write(gate_path, gate)
    manifest = {key: copy.deepcopy(value) for key, value in source.items() if key not in {"tasks", "authorization_binding"}}
    manifest.update({
        "schema": "qingshan.giggle_video_content_retry_manifest.v2_burned_text",
        "authorization_ref": "ROGER-E44-DIRECT-PRODUCTION-REPAIR-TECHNICAL-FAILURES",
        "provider_post_allowed": False,
        "video_unit_count": len(tasks),
        "reference_image_count": sum(len(task["reference_images"]) for task in tasks),
        "runtime_seconds": sum(int(task["duration_seconds"]) for task in tasks),
        "tasks": tasks,
        "repair_scope": list(TARGETS),
        "partial_repair_scope": True,
        "provider_post_count": 0,
        "machine_gate_reports": [*(source.get("machine_gate_reports") or []), rel(gate_path)],
    })
    write(OUT, manifest)
    print(json.dumps({"status": "PASS_ZERO_POST_BUILD", "tasks": len(tasks), "runtime_seconds": manifest["runtime_seconds"], "manifest": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
