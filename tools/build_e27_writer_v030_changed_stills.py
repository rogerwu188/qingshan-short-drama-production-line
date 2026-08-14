#!/usr/bin/env python3
"""Build the exact six-shot E27 v0.3 grand-establishing migration batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
V030_ROOT = ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720"
FULL_CONFIG = V030_ROOT / "production/image_batch.json"
MIGRATION = V030_ROOT / "migration.json"
DEST = V030_ROOT / "production/grand_establishing_migration"

ROUNDS = [
    (
        ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/image_batch.json",
        ROOT / "workflow/tasks/E27_WRITER_AGENT_STILL_BATCH_V1_RECEIPT_20260720.json",
        ROOT / "qa/e27_writer_agent_stills_v1_ai_review_20260720/E27_WRITER_AGENT_24_STILL_AI_REVIEW_RESULT_V080_CODEX_VISION_V3.json",
    ),
    (
        ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r1/image_batch_failed_only_r1.json",
        ROOT / "workflow/tasks/E27_WRITER_AGENT_STILL_FAILED_ONLY_R1_RECEIPT_20260720.json",
        ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r1_ai_review_20260720/E27_WRITER_AGENT_9_STILL_R1_AI_REVIEW_RESULT.json",
    ),
    (
        ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r2/image_batch_failed_only_r2.json",
        ROOT / "workflow/tasks/E27_WRITER_AGENT_STILL_FAILED_ONLY_R2_RECEIPT_20260720.json",
        ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r2_ai_review_20260720/E27_WRITER_AGENT_5_STILL_R2_AI_REVIEW_RESULT.json",
    ),
    (
        ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r3/image_batch_failed_only_r3.json",
        ROOT / "workflow/tasks/E27_WRITER_AGENT_STILL_FAILED_ONLY_R3_RECEIPT_20260720.json",
        ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r3_ai_review_20260720/E27_WRITER_AGENT_2_STILL_R3_AI_REVIEW_RESULT.json",
    ),
]

N09_CAUSAL_LOCK = (
    "V030_N09_CAUSAL_LOCK: 保持剧本事件不变。第三层唯一空置矩形格占右侧清晰焦点，纯红无纹新封痕位于该空格右内壁；"
    "皎兔女性兔耳阴神的透明食指必须直接接触红色封痕，视线同步落在接触点。"
    "青铜锁孔、穿锁前臂、空格、指尖触封痕构成单一连续因果；移除一切竞争目标、文字、符号、标签和额外红点。"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def accepted_candidates() -> dict[str, dict]:
    accepted: dict[str, dict] = {}
    for config_path, receipt_path, review_path in ROUNDS:
        config = load(config_path)
        receipt = load(receipt_path)
        review = load(review_path)
        config_by_key = {task["task_key"]: task for task in config["tasks"]}
        receipt_by_key = {task["task_key"]: task for task in receipt["tasks"]}
        for passed in review.get("passed_items", []):
            name = Path(passed["path"]).name
            matches = [key for key in config_by_key if name.startswith(f"E27_{key}_")]
            if len(matches) != 1:
                raise ValueError(f"cannot bind passed candidate to task: {name}")
            key = matches[0]
            task = config_by_key[key]
            receipt_task = receipt_by_key[key]
            candidate = Path(receipt_task["output_path"])
            actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual_sha != receipt_task["sha256"]:
                raise ValueError(f"candidate SHA drift: {candidate}")
            prompt = ROOT / task["prompt_file"]
            prompt_sha = hashlib.sha256(prompt.read_bytes()).hexdigest()
            if prompt_sha != task["prompt_sha256"]:
                raise ValueError(f"prompt SHA drift: {prompt}")
            accepted[task["shot_id"]] = {
                "shot_id": task["shot_id"],
                "task_key": key,
                "scene_id": task["scene_id"],
                "candidate_path": str(candidate),
                "candidate_sha256": actual_sha,
                "prompt_file": task["prompt_file"],
                "prompt_sha256": prompt_sha,
                "review_report": str(review_path.relative_to(ROOT)),
                "review_id": passed["review_id"],
                "status": "PASS",
            }
    return accepted


def main() -> int:
    full = load(FULL_CONFIG)
    migration = load(MIGRATION)
    changed = migration["regenerate_shot_ids"]
    retained = migration["retained_exact_shot_ids"]
    if changed != ["E27-N01", "E27-N05", "E27-N09", "E27-N13", "E27-N17", "E27-N21"]:
        raise SystemExit(f"changed-shot drift: {changed}")
    if len(retained) != 18 or set(changed) & set(retained):
        raise SystemExit("unsafe migration partition")

    accepted = accepted_candidates()
    missing = sorted(set(retained) - set(accepted))
    if missing:
        raise SystemExit(f"retained shot lacks exact-SHA PASS evidence: {missing}")

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    source_tasks = {task["shot_id"]: task for task in full["tasks"]}
    tasks = []
    manifest = [
        "# E27 Writer Agent v0.3.0 grand-establishing migration prompts",
        "",
        "Only six Writer Agent-declared changed shots are regenerated. Eighteen exact-SHA PASS candidates are preserved.",
        "",
    ]
    for shot_id in changed:
        source = source_tasks[shot_id]
        text = (ROOT / source["prompt_file"]).read_text(encoding="utf-8").rstrip()
        if shot_id == "E27-N09":
            text += "\n" + N09_CAUSAL_LOCK
        text += "\n"
        prompt_path = prompt_dir / f"{shot_id}-V030-GRAND.txt"
        prompt_path.write_text(text, encoding="utf-8")
        task = dict(source)
        task["task_key"] = f"{shot_id}-WRITER-AGENT-STILL-V030-GRAND"
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        task["status"] = "READY_V030_GRAND_ESTABLISHING_PARALLEL_SUBMIT"
        task["retry_reason"] = "WRITER_AGENT_V030_CL2X440_MIGRATION"
        tasks.append(task)
        manifest.extend([f"## {shot_id}", "", text.rstrip(), ""])

    preserved = [accepted[shot_id] for shot_id in retained]
    config = dict(full)
    config.update({
        "status": "READY_V030_GRAND_ESTABLISHING_CONCURRENT_SUBMIT",
        "concurrency": 6,
        "output_dir": "working_assets/e27_writer_agent_v030_grand_establishing_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v030_grand_establishing_20260720",
        "base_batch_note": "Regenerate six v0.3.0 establishing shots; preserve eighteen exact-SHA AI-review passes.",
        "migration_manifest": str(MIGRATION.relative_to(ROOT)),
        "tasks": tasks,
        "preserved_prompt_professionalism_evidence": [
            {key: row[key] for key in ("task_key", "scene_id", "prompt_file", "prompt_sha256")}
            for row in preserved
        ],
        "preserved_candidate_manifest": str((DEST / "preserved_18_selection.json").relative_to(ROOT)),
    })
    (DEST / "IMAGE_GENERATION_PROMPTS_V030_CHANGED_6.md").write_text("\n".join(manifest), encoding="utf-8")
    config["prompt_manifest"] = str((DEST / "IMAGE_GENERATION_PROMPTS_V030_CHANGED_6.md").relative_to(ROOT))
    (DEST / "preserved_18_selection.json").write_text(json.dumps({
        "schema": "qingshan.failed_only.preserved_candidates.v1",
        "episode": "E27",
        "status": "PASS",
        "count": 18,
        "items": preserved,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path = DEST / "image_batch_changed_6.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "changed": changed, "preserved": len(preserved), "config": str(config_path.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
