#!/usr/bin/env python3
"""Build an exact-review-bound failed-only Writer Agent still retry batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def correction(report: dict) -> str:
    focus = (report.get("agentcut") or {}).get("metadata", {}).get("review_focus") or []
    location = focus[0] if len(focus) > 0 else "use the locked location"
    time = focus[1] if len(focus) > 1 else "use the locked time of day"
    weather = focus[2] if len(focus) > 2 else "use the locked weather"
    action = focus[3] if len(focus) > 3 else "make the locked action unmistakable"
    moment = focus[4] if len(focus) > 4 else "show one decisive moment"
    failed_checks = {
        issue.get("details", {}).get("check")
        for issue in report.get("issues", [])
        if issue.get("blocking")
    }
    directives = [
        "这是 failed-only 定向修复，不得改变原镜头事实、人物身份、道具或构图功能。",
    ]
    if "scene_authority" in failed_checks:
        directives.append(f"场景必须一眼符合：{location}；{time}；{weather}。不得借门窗、背景或装饰引入相邻场景。")
    if "story_action_clarity" in failed_checks:
        directives.append(f"剧情动作必须一眼读出：{action}。画面只锁定动作因果最清楚的接触或结果节点，不能用静态站姿替代。")
        directives.append(f"决定性瞬间必须符合：{moment}")
    if "canonical_identity_continuity" in failed_checks:
        directives.append("严格使用已绑定角色参考，保持年龄、性别、脸型、服装和皎兔女性兔耳母题，不得换人。")
    if "native_anatomy" in failed_checks or "no_extra_or_duplicated_bodies" in failed_checks:
        directives.append("人物数量与肢体必须精确；双手和接触点自然，不得多肢、融合、复制或漂浮。")
    if "no_text_or_pseudotext" in failed_checks:
        directives.append("所有纸张、书脊、门牌、器物表面保持纯材质，无可读文字、伪字、符号、水印或 Logo。")
    directives.append("只生成一个连续单帧，不得拼贴、分屏、故事板格或重复人物。")
    return "\nFAILED_ONLY_R1_CORRECTION:\n- " + "\n- ".join(directives) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    config = load((ROOT / args.base_config).resolve())
    review_path = (ROOT / args.review).resolve()
    review = load(review_path)
    out_dir = (ROOT / args.out_dir).resolve()
    prompt_dir = out_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    failed_reports = {
        (row.get("agentcut") or {}).get("clip_id"): row
        for row in review.get("items", [])
        if row.get("status") == "FAIL"
    }
    passed_ids = [
        (row.get("agentcut") or {}).get("clip_id")
        for row in review.get("items", [])
        if row.get("status") == "PASS"
    ]
    tasks = []
    manifest = [
        f"# {config['episode']} Writer Agent 图片 failed-only R1 提示词",
        "",
        f"保留 {len(passed_ids)} 个通过项，仅重生成 {len(failed_reports)} 个真实内容失败项。",
        "",
    ]
    for source in config.get("tasks", []):
        shot_id = source.get("shot_id")
        report = failed_reports.get(shot_id)
        if not report:
            continue
        original = (ROOT / source["prompt_file"]).read_text(encoding="utf-8").rstrip()
        text = original + correction(report)
        prompt_path = prompt_dir / f"{shot_id}-R1.txt"
        prompt_path.write_text(text, encoding="utf-8")
        task = dict(source)
        task.update({
            "task_key": f"{shot_id}-WRITER-AGENT-STILL-R1",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": digest(text),
            "status": "READY_FAILED_ONLY_PARALLEL_SUBMIT",
            "retry_reason": "AI_REVIEW_0P9P1_CONTENT_FAIL",
            "prior_candidate_sha256": report.get("media_sha256"),
            "source_review_id": report.get("review_id"),
        })
        tasks.append(task)
        manifest.extend([f"## {shot_id}", "", text.rstrip(), ""])

    if not tasks:
        raise SystemExit("No failed image items found")
    episode = str(config["episode"]).lower()
    output = dict(config)
    output.update({
        "status": "READY_FAILED_ONLY_R1_CONCURRENT_SUBMIT",
        "concurrency": len(tasks),
        "max_retries": 1,
        "output_dir": f"working_assets/{episode}_writer_agent_stills_failed_only_r1/candidates",
        "qa_dir": f"qa/{episode}_writer_agent_stills_failed_only_r1",
        "base_batch_note": f"Retry only {len(tasks)} content-failed stills; retain {len(passed_ids)} exact-SHA passes.",
        "source_ai_review": str(review_path.relative_to(ROOT)),
        "retained_pass_shot_ids": passed_ids,
        "tasks": tasks,
    })
    manifest_path = out_dir / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R1.md"
    manifest_path.write_text("\n".join(manifest).rstrip() + "\n", encoding="utf-8")
    output["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    config_path = out_dir / "image_batch_failed_only_r1.json"
    config_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": len(tasks), "retained_pass_count": len(passed_ids), "config": str(config_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
