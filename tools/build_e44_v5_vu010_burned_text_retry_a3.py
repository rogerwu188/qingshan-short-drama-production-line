#!/usr/bin/env python3
"""Build E44 VU010's final A3 retry without provider POST."""

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
QA = ROOT / "qa/e44_v5_a3_vu010_burned_text"
SOURCE = PROD / "E44_V5_A2_BURNED_TEXT_REPAIRS_AUTHORIZED_V1.json"
HARVEST = ROOT / "qa/e44_v5_a2_burned_text_repairs/E44_V5_A2_BURNED_TEXT_HARVEST_LATEST.json"
PROMPT = PROD / "video_prompts_a3_burned_text_final/E44-VU-010.txt"
OUT = PROD / "E44_V5_VU010_A3_BURNED_TEXT_PRECHECK_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    manifest, harvest = json.loads(SOURCE.read_text(encoding="utf-8")), json.loads(HARVEST.read_text(encoding="utf-8"))
    task = copy.deepcopy(next(row for row in manifest["tasks"] if row["unit_id"] == "E44-VU-010"))
    remote = next(row for row in harvest["results"] if row["unit_id"] == "E44-VU-010")
    if remote.get("status") != "completed":
        raise RuntimeError("VU010 A2 is not one completed bound candidate")
    candidate, prior_prompt = ROOT / remote["video_path"], ROOT / task["prompt_file"]
    evidence = ROOT / "qa/e44_v5_a2_burned_text_repairs/E44-VU-010_A2_1p2s.png"
    if sha(candidate) != remote["video_sha256"] or sha(prior_prompt) != task["prompt_sha256"] or not evidence.is_file():
        raise RuntimeError("VU010 A2 evidence SHA mismatch")
    failure = {
        "schema": "qingshan.video_content_failure_memory.v1",
        "episode": "E44",
        "version": "v5",
        "unit_id": "E44-VU-010",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "RECORDED_CONTENT_FAILURE_FINAL_RETRY_ALLOWED",
        "failure_classification": "PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT",
        "prior_task_key": task["task_key"],
        "prior_task_id": remote["task_id"],
        "prior_prompt_sha256": sha(prior_prompt),
        "candidate": rel(candidate),
        "candidate_sha256": sha(candidate),
        "evidence_ref": rel(evidence),
        "evidence_sha256": sha(evidence),
        "reason": "A2 still rendered the spoken word 今晚 as a white outlined subtitle despite the pixel-isolation clause.",
        "do_not_repeat": [
            "Do not reuse A1 or A2 prompt SHA.",
            "Do not use a dialogue-centered push-in composition.",
            "Do not use quoted dialogue syntax or any program-master/subtitle framing.",
            "Do not crop, mask, erase, or repair rejected A2 pixels.",
        ],
        "creative_attempt_consumed": 2,
        "next_creative_attempt": 3,
        "maximum_creative_attempts": 3,
    }
    failure_path = QA / "E44-VU-010_A2_FAILURE_MEMORY_V1.json"
    write(failure_path, failure)

    lines = []
    for line in prior_prompt.read_text(encoding="utf-8").splitlines():
        if line.startswith("【像素文字隔离硬合同】") or line.startswith("【本次技术修复防复犯】"):
            continue
        lines.append(line)
    rewritten = "\n".join(lines)
    rewritten = rewritten.replace(
        "【视频任务】6秒，竖屏9:16，720p，seedance-2.0-pro（SD2 标准版）；写实古装悬疑电影质感。",
        "【视频任务】6秒，竖屏9:16，720p，seedance-2.0-pro（SD2 标准版）；写实古装悬疑电影质感。\n"
        "CLEAN-PLATE LIVE-ACTION CAMERA DAILIES. DIEGETIC SPEECH IS AUDIO-ONLY. ZERO GRAPHIC LAYERS FROM THE FIRST FRAME THROUGH THE FINAL FRAME. The image contains only the photographed courtyard, actor, cat, bamboo tube, moonlight and air.",
    )
    rewritten = rewritten.replace("陈迹说：“今晚了。”", "陈迹同期声自然说出指定声音内容：今晚了。")
    rewritten = rewritten.replace(
        "仅执行一次轨道推拉，向主体推进，禁止反向复位或重复运动；运镜动机：纵深变化只用于把观众注意力从话语表面移到眼神、手部或道具结果；",
        "固定35mm竖屏环境中景，摄影机不推近、不摇移、不追随对白；运镜动机：用墙面、井台、月光和猫的真实纵深承载同期声，不把一句话做成视觉标题；",
    )
    rewritten = rewritten.replace(
        "【关键限制】无字幕、水印、可读文字、人物身份漂移、静态帧、数字推拉、循环动作、冻结或变速补时；不得漏拍或重排节拍。",
        "【关键限制】保持纯现场原片，不附加任何图形层；禁止人物身份漂移、静态帧、数字推拉、循环动作、冻结或变速补时；不得漏拍或重排节拍。",
    )
    rewritten += "\nFINAL DELIVERY IS A CLEAN CAMERA FEED WITH SYNCHRONOUS LOCATION AUDIO; it is not a subtitled, captioned, titled, designed or post-produced program master."
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(rewritten + "\n", encoding="utf-8")
    report = validate_model_prompt(rewritten, source_id="E44-VU-010-A3-BURNED-TEXT-FINAL")
    if report["status"] != "PASS":
        raise ValueError(report["failures"])

    prior_shas = [*(task.get("prior_prompt_sha256") or []), sha(prior_prompt)]
    task.update({
        "task_key": "E44-VU-010-VIDEO-A3-BURNED-TEXT-FINAL-REPAIR",
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "model_prompt_contract": report,
        "provider_post_allowed": False,
        "remote_task_id": None,
        "retry_attempt": 3,
        "creative_attempt_ordinal": 3,
        "paid_attempt": 3,
        "prior_failure_classifications": [
            "PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT",
            "PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT",
        ],
        "prior_prompt_sha256": prior_shas,
        "failure_memory": {"ref": rel(failure_path), "sha256": sha(failure_path)},
        "material_change_from_prior_attempt": "Changed dialogue-centered dolly push-in to a fixed 35mm environmental clean-camera-dailies composition, removed quoted dialogue syntax, and specified audio-only synchronous location speech without any graphics pipeline.",
        "do_not_repeat": failure["do_not_repeat"],
        "content_attempt_consumed_by_prior_failure": True,
        "same_creative_prompt_intentional": False,
        "no_further_automatic_retry": True,
    })
    camera = task["machine_contract"]["camera_plan"]
    camera.update({
        "shot_scale": "MEDIUM_WIDE",
        "lens_intent": "35mm环境中景，墙面、井台、月光与猫保持真实纵深",
        "motion_family": "LOCKED",
        "motion_direction": "NONE",
        "start_framing": "固定35mm竖屏环境中景：陈迹、墙面、井台、月光与猫的动作区域同处既定轴线B侧构图",
        "end_framing": "固定35mm竖屏环境中景：陈迹、墙面、井台、月光与猫的动作区域同处既定轴线B侧构图",
        "motivation": "固定现场机位承载同期声与刮墙动作，随后让抬头与猫落地在同一真实空间内完成，不把对白视觉化。",
        "signature": "LOCKED:NONE",
    })
    task["input_template_id"] = compute_input_template_id(task)
    gate = {
        "schema": "qingshan.e44.v5.vu010_a3_content_retry_gate.v1",
        "episode": "E44",
        "unit_id": "E44-VU-010",
        "status": "PASS",
        "failure_memory": {"ref": rel(failure_path), "sha256": sha(failure_path)},
        "prior_prompt_sha256": sha(prior_prompt),
        "retry_prompt_sha256": sha(PROMPT),
        "materially_changed": sha(prior_prompt) != sha(PROMPT),
        "creative_attempt": 3,
        "maximum_creative_attempts": 3,
        "provider_post_count": 0,
    }
    gate_path = QA / "E44-VU-010_A3_CONTENT_RETRY_GATE_V1.json"
    write(gate_path, gate)
    out = {key: copy.deepcopy(value) for key, value in manifest.items() if key not in {"tasks", "authorization_binding"}}
    out.update({
        "schema": "qingshan.giggle_video_content_retry_manifest.v1",
        "authorization_ref": "ROGER-E44-DIRECT-PRODUCTION-REPAIR-TECHNICAL-FAILURES",
        "provider_post_allowed": False,
        "video_unit_count": 1,
        "runtime_seconds": int(task["duration_seconds"]),
        "tasks": [task],
        "partial_repair_scope": True,
        "repair_scope": ["E44-VU-010"],
        "machine_gate_reports": [*(manifest.get("machine_gate_reports") or []), rel(gate_path)],
    })
    write(OUT, out)
    print(json.dumps({"status": "PASS_ZERO_POST_BUILD", "manifest": rel(OUT), "prompt_sha256": sha(PROMPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
