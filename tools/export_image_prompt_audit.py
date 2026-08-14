#!/usr/bin/env python3
"""Export exact image-generation prompts and reference bindings for human audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()

    manifest_path = resolve(args.batch_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = manifest.get("tasks") or []
    lines = [
        f"# {manifest.get('episode', 'UNKNOWN')} 首次图片生成原始提示词审计",
        "",
        f"批次清单：`{manifest_path}`",
        "",
        f"实际提交任务数：**{len(tasks)}**。以下提示词、模型参数和参考图均直接读取提交清单；未改写、未优化。",
        "",
    ]
    rows: list[dict[str, Any]] = []
    all_pass = True
    for index, task in enumerate(tasks, 1):
        prompt_path = resolve(task["prompt_file"])
        actual_prompt_sha = sha256(prompt_path)
        expected_prompt_sha = task.get("prompt_sha256")
        prompt_sha_pass = actual_prompt_sha == expected_prompt_sha
        references = []
        for value in task.get("reference_images") or []:
            path = resolve(value)
            references.append({
                "path": str(path),
                "exists": path.is_file(),
                "sha256": sha256(path) if path.is_file() else None,
            })
        row_pass = prompt_sha_pass and all(item["exists"] for item in references)
        all_pass = all_pass and row_pass
        rows.append({
            "task_key": task["task_key"],
            "prompt_path": str(prompt_path),
            "expected_prompt_sha256": expected_prompt_sha,
            "actual_prompt_sha256": actual_prompt_sha,
            "prompt_sha_match": prompt_sha_pass,
            "references": references,
            "status": "BOUND" if row_pass else "BINDING_FAIL",
        })
        lines.extend([
            f"## {index}. {task['task_key']}",
            "",
            f"- 模型：`{task.get('model')}`",
            f"- 画幅：`{task.get('aspect_ratio')}`",
            f"- 分辨率：`{task.get('resolution')}`",
            f"- 提示词 SHA-256：`{actual_prompt_sha}` ({'MATCH' if prompt_sha_pass else 'MISMATCH'})",
            "- 实际参考图：",
        ])
        for reference in references:
            lines.append(f"  - `{reference['path']}` | SHA-256 `{reference['sha256']}`")
        lines.extend([
            "",
            "```text",
            prompt_path.read_text(encoding="utf-8").rstrip("\n"),
            "```",
            "",
        ])

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.image_prompt_human_audit_export.v1",
        "episode": manifest.get("episode"),
        "batch_manifest": str(manifest_path),
        "batch_manifest_sha256": sha256(manifest_path),
        "task_count": len(tasks),
        "status": "PASS" if all_pass else "FAIL",
        "markdown": str(out),
        "markdown_sha256": sha256(out),
        "tasks": rows,
    }
    receipt_path = resolve(args.receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "task_count": len(tasks), "markdown_sha256": receipt["markdown_sha256"]}, ensure_ascii=False))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
