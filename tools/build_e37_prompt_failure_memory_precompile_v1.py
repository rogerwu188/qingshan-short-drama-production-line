#!/usr/bin/env python3
"""Materialize E37 provider prompts with the standing failure memory compiled in."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from generation_first_pass_policy_gate import evaluate


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DIR = Path(
    "workflow/claude_writer_agent/production/"
    "e37_claude_writer_v2_4a738459_20260802"
)
REGISTRY = PRODUCTION_DIR / "E37_COMPLETE_VIDEO_PROMPT_BINDING_REGISTRY_V1.json"
ANCHORS = PRODUCTION_DIR / "E37_ALL_12_ANCHOR_ACCEPTANCE_REGISTRY_V1.json"
POLICY = Path("workflow/approvals/ROGER_GENERATION_FIRST_PASS_AND_TIERED_REMAKE_POLICY_20260801.json")
MEMORY = Path("workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json")
SCRIPT = Path("workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md")
SCRIPT_MANIFEST = Path("workflow/claude_writer_agent/scripts/E37_manifest_v2.json")
DEFAULT_OUTPUT_DIR = Path(
    "working_assets/e37_preproduction_20260802/"
    "prompt_failure_memory_precompile_v1/compiled_prompts"
)
DEFAULT_CONFIG = PRODUCTION_DIR / "E37_GENERATION_FIRST_PASS_POLICY_CONFIG_V1.json"
DEFAULT_MANIFEST = PRODUCTION_DIR / "E37_PROMPT_FAILURE_MEMORY_PRECOMPILE_MANIFEST_V1.json"
DEFAULT_GATE = Path("qa/e37_preproduction_20260802/E37_PROMPT_FAILURE_MEMORY_PRECOMPILE_GATE_V1.json")
DEFAULT_SUMS = Path(
    "working_assets/e37_preproduction_20260802/"
    "prompt_failure_memory_precompile_v1/SHA256SUMS.txt"
)


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(repo_path(path).read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict) -> None:
    path = repo_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unit_thresholds(anchor_registry: dict) -> dict[str, int]:
    thresholds: dict[str, int] = {}
    for anchor in anchor_registry["accepted_anchors"]:
        unit_id = anchor["unit_id"]
        threshold = int(anchor["pass_score"])
        if unit_id in thresholds and thresholds[unit_id] != threshold:
            raise ValueError(f"conflicting pass scores for {unit_id}")
        if threshold not in {60, 80}:
            raise ValueError(f"unsupported pass score for {unit_id}: {threshold}")
        thresholds[unit_id] = threshold
    return thresholds


def compile_header(tier: str, threshold: int, jiaotu_applies: bool) -> str:
    jiaotu_rule = (
        "PF-006：皎兔仅用模型原生、rights-cleared 的年轻女性普通话；禁止克隆或未验证音色；"
        "锁定红色眉心印记与 canonical 面容，口型、气息、表情同步。"
        if jiaotu_applies
        else "PF-006：NOT_APPLICABLE_NO_JIAOTU（本段无皎兔）。"
    )
    return "\n".join(
        [
            "[E37 首次生成失败记忆预编译锁]",
            f"PF-007：分级 {tier}；验收线 {threshold}/100；普通瑕疵仅低于验收线才重做，达线保留；硬身份、安全、时代、OCR/伪文字失败覆盖分数；禁止原样付费重试。",
            "PF-001：每段默认仅一个可见说话者；如有交接，必须明确镜头边界、说话顺序、逐人开口/闭口状态，并给足对白与反应尾帧。",
            "PF-002：canonical 对白只保留原提示词中的唯一精确文本；禁止改写、近义替换、漏掉首句；明确自然普通话、起止窗口和闭口尾帧。",
            "PF-003：在动作与声音中锁定唯一可见说话者；其余人物闭口、仅反应、不得发声。",
            "PF-004：全时长连续真实微动作，每个阶段不超过 3 秒；逐段明确主体、动作、接触点、方向、终态、环境响应；禁止定格、循环、重放、慢动作、慢推、漂移和冻结尾帧。",
            "PF-005：所有时代物件表面保持空白或不可读；禁止字母、文字、符号、伪文字、字幕、水印、标志。",
            jiaotu_rule,
            "[原始专业视频提示词原文如下，内容与 canonical 对白不得改写]",
            "",
        ]
    )


def build(args: argparse.Namespace) -> dict:
    registry = load_json(REGISTRY)
    anchors = load_json(ANCHORS)
    memory = load_json(MEMORY)
    thresholds = unit_thresholds(anchors)
    known_ids = [row["id"] for row in memory["rules"]]
    recorded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    compiled_rows = []
    for binding in registry["segment_bindings"]:
        segment_id = binding["segment_id"]
        unit_id = segment_id.split("-", 1)[0]
        threshold = thresholds[unit_id]
        tier = "CORE" if threshold == 80 else "NON_CORE"
        source = repo_path(Path(binding["prompt_file"]))
        source_text = source.read_text(encoding="utf-8")
        jiaotu_applies = "皎兔" in source_text or "Jiaotu" in source_text
        applied = known_ids if jiaotu_applies else [value for value in known_ids if value != "PF-006"]
        not_applicable = [] if jiaotu_applies else ["PF-006"]

        compiled = output_dir / f"E37-CW-{segment_id}_PFM_PRECOMPILED_V1.txt"
        compiled.write_text(
            compile_header(tier, threshold, jiaotu_applies) + source_text,
            encoding="utf-8",
        )
        if not compiled.read_text(encoding="utf-8").endswith(source_text):
            raise RuntimeError(f"source prompt suffix was not preserved for {segment_id}")

        row = {
            "task_key": f"E37-CW-{segment_id}",
            "segment_id": segment_id,
            "unit_id": unit_id,
            "canonical_lines": binding["canonical_lines"],
            "tool_type": "video_generation",
            "visual_tier": tier,
            "minimum_score_100": threshold,
            "hard_fact_fail_overrides_score": True,
            "unchanged_paid_retry": "PROHIBITED",
            "prompt_failure_modes_applied": applied,
            "prompt_failure_modes_not_applicable": not_applicable,
            "source_prompt": relative(source),
            "source_prompt_sha256": sha256(source),
            "compiled_prompt": relative(compiled),
            "compiled_prompt_sha256": sha256(compiled),
        }
        tasks.append(row)
        compiled_rows.append(dict(row))

    policy_path = repo_path(POLICY)
    memory_path = repo_path(MEMORY)
    config = {
        "schema": "qingshan.generation_first_pass_policy_config.v1",
        "episode": "E37",
        "recorded_at": recorded_at,
        "status": "PRECOMPILED_READY_FOR_POLICY_GATE_NO_SUBMISSION",
        "generation_first_pass_policy_ref": relative(policy_path),
        "generation_first_pass_policy_sha256": sha256(policy_path),
        "generation_prompt_failure_memory_ref": relative(memory_path),
        "generation_prompt_failure_memory_sha256": sha256(memory_path),
        "canonical_script": relative(repo_path(SCRIPT)),
        "canonical_script_sha256": sha256(repo_path(SCRIPT)),
        "canonical_manifest": relative(repo_path(SCRIPT_MANIFEST)),
        "canonical_manifest_sha256": sha256(repo_path(SCRIPT_MANIFEST)),
        "tasks": tasks,
    }
    dump_json(args.config, config)

    gate = evaluate(config)
    gate.update(
        {
            "episode": "E37",
            "recorded_at": recorded_at,
            "config": relative(repo_path(args.config)),
            "config_sha256": sha256(repo_path(args.config)),
            "submission": "NOT_ATTEMPTED_ZERO_CREDIT_PREPRODUCTION",
        }
    )
    dump_json(args.gate, gate)
    if gate["status"] != "PASS" or len(gate["results"]) != len(tasks):
        raise RuntimeError("generation first-pass policy gate did not pass every task")

    tier_counts = {
        "CORE": sum(row["visual_tier"] == "CORE" for row in tasks),
        "NON_CORE": sum(row["visual_tier"] == "NON_CORE" for row in tasks),
    }
    manifest = {
        "schema": "qingshan.e37_prompt_failure_memory_precompile_manifest.v1",
        "episode": "E37",
        "recorded_at": recorded_at,
        "status": "PASS_22_OF_22_PROMPTS_MEMORY_PRECOMPILED_NO_SUBMISSION",
        "canonical": {
            "script": relative(repo_path(SCRIPT)),
            "script_sha256": sha256(repo_path(SCRIPT)),
            "manifest": relative(repo_path(SCRIPT_MANIFEST)),
            "manifest_sha256": sha256(repo_path(SCRIPT_MANIFEST)),
        },
        "source_registry": {
            "path": relative(repo_path(REGISTRY)),
            "sha256": sha256(repo_path(REGISTRY)),
        },
        "policy_config": {
            "path": relative(repo_path(args.config)),
            "sha256": sha256(repo_path(args.config)),
        },
        "gate_report": {
            "path": relative(repo_path(args.gate)),
            "sha256": sha256(repo_path(args.gate)),
            "status": gate["status"],
        },
        "counts": {
            "segments": len(tasks),
            "canonical_lines_bound": sum(len(row["canonical_lines"]) for row in tasks),
            "compiled_prompts": len(compiled_rows),
            "policy_gate_pass": sum(row["status"] == "PASS" for row in gate["results"]),
            "tiers": tier_counts,
        },
        "compiled_prompts": compiled_rows,
        "hard_gate_policy": "IDENTITY_SAFETY_ERA_OCR_FAILURE_OVERRIDES_SCORE",
        "remake_policy": "CORE_BELOW_80_NON_CORE_BELOW_60_AT_THRESHOLD_RETAIN",
        "unchanged_paid_retry": "PROHIBITED",
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "next_action": "USE_ONLY_THE_BOUND_COMPILED_PROMPT_AFTER_DEMONSTRABLE_PROVIDER_RECOVERY_OR_A_DISTINCT_COMPLIANT_ROUTE",
    }
    dump_json(args.manifest, manifest)

    checksum_paths = [repo_path(args.config), repo_path(args.gate), repo_path(args.manifest)]
    checksum_paths.extend(repo_path(Path(row["compiled_prompt"])) for row in compiled_rows)
    sums = repo_path(args.sums)
    sums.parent.mkdir(parents=True, exist_ok=True)
    sums.write_text(
        "".join(f"{sha256(path)}  {relative(path)}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    return {
        "status": manifest["status"],
        "compiled_prompts": len(compiled_rows),
        "tier_counts": tier_counts,
        "config": relative(repo_path(args.config)),
        "config_sha256": sha256(repo_path(args.config)),
        "gate": relative(repo_path(args.gate)),
        "gate_sha256": sha256(repo_path(args.gate)),
        "manifest": relative(repo_path(args.manifest)),
        "manifest_sha256": sha256(repo_path(args.manifest)),
        "sha256sums": relative(sums),
        "sha256sums_sha256": sha256(sums),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--sums", type=Path, default=DEFAULT_SUMS)
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
