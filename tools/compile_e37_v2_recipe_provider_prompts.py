#!/usr/bin/env python3
"""Compile sequence-safe E37 prompts with fixed dialogue compositions by default."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802"
FIRST = PROD / "E37_FIRST_WAVE_VIDEO_GENERATION_MANIFEST_V1.json"
SECOND = PROD / "E37_SECOND_WAVE_VIDEO_GENERATION_MANIFEST_V1.json"
BINDINGS = PROD / "E37_COMPLETE_VIDEO_PROMPT_BINDING_REGISTRY_V1.json"
TIMELINE = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_SHOT_RECIPE_MATERIALIZED_TIMELINE_V2.json"
REMAP_GATE = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_RECIPE_REMAP_VALIDATION_V2.json"
PFM_DIR = ROOT / "working_assets/e37_preproduction_20260802/prompt_failure_memory_precompile_v1/compiled_prompts"
OUT_DIR = ROOT / "working_assets/e37_preproduction_20260802/v3_camera_sequence_safe_prompts"
OUT_MANIFEST = PROD / "E37_REMAINING_U03_U07_PFM_V3_CAMERA_SEQUENCE_SAFE_MANIFEST_V5.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
MANIFEST_SHA = "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e"
TARGET_UNITS = {"U03", "U07"}
CAMERA_PLAN = {
    "U03-S1": ("camera.locked_evidence_medium", "FIXED", "账页与说话人同框，固定中景"),
    "U03-S2": ("camera.overhead_reveal", "REVEAL", "假日期被指出时仅一次由账页切到说话人"),
    "U03-S3": ("camera.locked_speaker_medium", "FIXED", "说话人稳定中景，账页留在画面下缘"),
    "U03-S4": ("camera.locked_doorway_medium", "FIXED", "人物与里屋入口稳定同框"),
    "U07-S1": ("camera.locked_two_shot", "FIXED", "发言人与听者稳定双人构图"),
    "U07-S2": ("camera.locked_speaker_medium", "FIXED", "发言人稳定中景"),
    "U07-S3": ("camera.overhead_reveal", "REVEAL", "医馆去向被指出时仅一次由账页切到人物"),
    "U07-S4": ("camera.locked_reaction_two_shot", "FIXED", "质问者与被质问方向稳定同框"),
    "U07-S5": ("camera.locked_close_medium", "FIXED", "陈迹稳定近中景"),
    "U07-S6": ("camera.locked_close_medium", "FIXED", "陈迹稳定近中景，镜头不追随手势"),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def phase_text(entry: dict) -> str:
    labels = {
        "setup": "起势",
        "contact": "因果接触",
        "result": "结果可读",
    }
    rows = []
    for phase in entry["motionArc"]["phases"]:
        pid = phase["phaseId"]
        label = labels.get(pid, "节拍锚点")
        window = phase["clipTime"]
        rows.append(f"- {window['start']:.2f}-{window['end']:.2f}秒 {label}（{pid}）")
    return "\n".join(rows)


def main() -> int:
    if sha256(SCRIPT) != SCRIPT_SHA:
        raise SystemExit("canonical script SHA mismatch")

    first = load(FIRST)
    second = load(SECOND)
    bindings = load(BINDINGS)
    timeline = load(TIMELINE)
    remap = load(REMAP_GATE)
    if not str(remap.get("status", "")).startswith("PASS_10_OF_10"):
        raise SystemExit("historical recipe provenance is missing")

    tasks = [task for task in first["tasks"] + second["tasks"] if task["unit_id"] in TARGET_UNITS]
    binding_map = {row["segment_id"]: row for row in bindings["segment_bindings"]}
    recipe_map = {}
    for entry in timeline["materializedTimeline"]:
        segment = entry["clipId"].removeprefix("E37-").removesuffix("-PREVIS-REPLACEMENT-SLOT")
        if segment.startswith(("U03-", "U07-")):
            recipe_map[segment] = entry

    if len(tasks) != 10 or set(recipe_map) != {task["task_key"].split("-VIDEO-")[0].removeprefix("E37-CW-") for task in tasks}:
        raise SystemExit("remaining task/recipe coverage mismatch")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    compiled = []
    for task in tasks:
        segment = task["task_key"].split("-VIDEO-")[0].removeprefix("E37-CW-")
        recipe = recipe_map[segment]
        resolved = recipe["resolvedRecipe"]
        recipe_id, motion_mode, composition = CAMERA_PLAN[segment]

        source_prompt = PFM_DIR / f"E37-CW-{segment}_PFM_PRECOMPILED_V1.txt"
        body = source_prompt.read_text(encoding="utf-8").strip()
        action = resolved["action"]
        camera_clause = (
            f"固定机位：{composition}。从0.0秒到片尾不得摇镜、推拉、升降、环绕、漂移或改变焦段；人物动作和表演承担信息变化。"
            if motion_mode == "FIXED"
            else f"单次因果揭示：{composition}。运镜只在信息被指出的瞬间发生，必须在2.0秒内结束，随后锁定人物构图到片尾；不得在下一句重新俯拍或再次揭示。"
        )
        prefix = f"""[E37 V3相邻镜头运镜安全锁：本块优先于下方旧运镜措辞]
片段：{segment}；生产配方：{recipe_id}；验收等级：CORE 80/100。
{camera_clause}
全局禁止 smooth_roam、slow_push、周期性裁切、左右/上下往复、无剧情触发的持续运镜。不同运镜名称属于同一连续运动家族，不能连续使用；本镜模式={motion_mode}。

四阶段精确时间窗：
{phase_text(recipe)}

动作弧硬锁：
- setup：{action['setup']}
- contact：{action['contact']}
- result：{action['result']} 结果阶段保持真实呼吸、眼神、衣摆、灯火或纸页微动，禁止冻结尾帧。

失败记忆追加：长 canonical 台词若标准 ASR 疑似漏首句或漏短语，先对同一原生音轨执行独立 beam8、VAD=false/true 双路听审；仅双路仍不覆盖 canonical 才允许 materially changed paid retry。禁止把单路 ASR 假阴性直接转成付费重做。
账本、纸张、牌匾和器物不得出现任何可读文字、数字、字母、符号或伪文字；硬身份、安全、时代、OCR失败覆盖分数。

[原 PFM 预编译提示词，除上述运镜覆盖外保持 canonical 对白和身份约束]
"""
        out_prompt = OUT_DIR / f"E37-CW-{segment}_PFM_V3_CAMERA_SEQUENCE_SAFE.txt"
        out_prompt.write_text(prefix + body + "\n", encoding="utf-8")

        compiled.append({
            "task_key": f"E37-CW-{segment}-PFM-V3-CAMERA-SEQUENCE-SAFE-V5",
            "unit_id": task["unit_id"],
            "scene_id": task.get("scene_id") or f"E37-{task['unit_id']}",
            "segment_id": segment,
            "duration_seconds": task["duration_seconds"],
            "prompt_file": rel(out_prompt),
            "prompt_sha256": sha256(out_prompt),
            "source_pfm_prompt": rel(source_prompt),
            "source_pfm_prompt_sha256": sha256(source_prompt),
            "canonical_lines": binding_map[segment]["canonical_lines"],
            "reference_images": task["reference_images"],
            "shot_recipe": {
                "recipe_id": recipe_id,
                "camera_motion": {"type": motion_mode.lower(), "composition": composition},
                "motion_arc": recipe["motionArc"],
                "action": action,
            },
            "camera_motion_contract": (
                {
                    "family": "reveal",
                    "narrative_trigger": composition,
                    "start_composition": "evidence insert",
                    "end_composition": "locked speaker medium",
                    "max_motion_seconds": 2.0,
                    "settle_to_fixed_composition": True,
                }
                if motion_mode == "REVEAL"
                else {"family": "fixed", "composition": composition}
            ),
            "qa_threshold": 80,
            "hard_overrides": ["identity", "safety", "era", "ocr_pseudotext"],
        })

    manifest = {
        "schema": "qingshan.e37.remaining_u03_u07.pfm_v3_camera_sequence_safe_manifest.v5",
        "episode": "E37",
        "recorded_at": utc_now(),
        "status": "PASS_CAMERA_SEQUENCE_SAFE_READY_FOR_CONCURRENT_PROVIDER_SUBMISSION",
        "source_script": rel(SCRIPT),
        "source_script_sha256": SCRIPT_SHA,
        "source_manifest_sha256": MANIFEST_SHA,
        "source_recipe_timeline": rel(TIMELINE),
        "source_recipe_timeline_sha256": sha256(TIMELINE),
        "source_recipe_remap_gate": rel(REMAP_GATE),
        "source_recipe_remap_gate_sha256": sha256(REMAP_GATE),
        "model": "seedance-2.0-pro",
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "workflow_credit_scope": second["workflow_credit_scope"],
        "counts": {"tasks": len(compiled), "u03": 4, "u07": 6, "canonical_lines": 20},
        "credits_before_submission": {"pay": 3673, "refund": 1433, "net": 2240, "cap": 10000, "headroom": 7760},
        "retry_policy": "NO_UNCHANGED_PAID_RETRY; PRESERVE_PASS; INDEPENDENT_DUAL_VAD_BEFORE_LONG_DIALOGUE_RETRY",
        "camera_sequence_policy": "DIALOGUE_FIXED_BY_DEFAULT_ONE_MOTIVATED_REVEAL_REQUIRES_FIXED_COOLDOWN_NO_OSCILLATION",
        "submission_gate": "OPEN_10_OF_10_SEQUENCE_SAFE_PROMPTS_CORE80_HARD_OVERRIDES_ACTIVE",
        "tasks": compiled,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "manifest": rel(OUT_MANIFEST),
        "manifest_sha256": sha256(OUT_MANIFEST),
        "tasks": len(compiled),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
