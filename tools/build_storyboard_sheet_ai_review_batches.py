#!/usr/bin/env python3
"""Build E26/E27 AI review batches for approved storyboard-sheet images."""

from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260719"


RECEIPTS = {
    "E26": ["workflow/tasks/E26_STORYBOARD_SHEET_IMAGE_BATCH_V1_RECEIPT_20260719.json"],
    "E27": [
        "workflow/tasks/E27_STORYBOARD_SHEET_IMAGE_BATCH_V1_RECEIPT_20260719.json",
        "workflow/tasks/E27_STORYBOARD_SHEET_EPISODE_ONLY_RETRY_V1_RECEIPT_20260719.json",
    ],
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def passed_sheets(episode: str) -> dict[str, dict]:
    sheets: dict[str, dict] = {}
    for receipt_ref in RECEIPTS[episode]:
        receipt_path = ROOT / receipt_ref
        if not receipt_path.is_file():
            continue
        for task in read(receipt_path).get("tasks") or []:
            if str(task.get("status") or task.get("state") or "").lower() != "image_pass":
                continue
            kind = str(task.get("sheet_kind") or (task.get("metadata") or {}).get("sheet_kind") or "")
            output = Path(str(task.get("output_path") or ""))
            if kind and output.is_file():
                sheets[kind] = {**task, "output_path": str(output), "source_receipt": receipt_ref}
    return sheets


def build(episode: str) -> Path:
    lower = episode.lower()
    sheets = passed_sheets(episode)
    missing = sorted({"episode_sheet", "fight_sheet"} - set(sheets))
    if missing:
        raise SystemExit(f"{episode} missing passed sheets: {','.join(missing)}")
    qa_dir = ROOT / f"qa/{lower}_storyboard_sheet_v1_{DATE}"
    items = []
    for kind in ("episode_sheet", "fight_sheet"):
        task = sheets[kind]
        path = Path(task["output_path"])
        focus = [
            "professional six-column shot-list layout with exactly six visual rows",
            "all six visual panels intentionally differ in shot size, camera position, direction and dramatic content",
            "canonical character identity, wardrobe and script-locked location continuity",
            "no duplicated bodies, extra people, modern objects, watermark, logo or text inside visual panels",
        ]
        if kind == "fight_sheet":
            focus.extend([
                "visible SETUP to IMPACT to TABLEAU choreography",
                "clear scale jump from extreme close or close shot to wide or full shot",
                "wuxia-xuanhuan power is visualized through environmental media rather than abstract glow",
            ])
        items.append({
            "path": str(path),
            "scope": "sequence",
            "kind": "image",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": f"{episode}-{kind.upper()}",
            "metadata": {
                "episode": episode,
                "sheet_kind": kind,
                "candidate_sha256": sha256(path),
                "source_receipt": task["source_receipt"],
                "review_focus": focus,
                "directive_refs": ["CL2X-388", "CL2X-389"],
            },
            "required_capabilities": ["image_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        })
    request = qa_dir / f"{episode}_STORYBOARD_SHEET_AI_REVIEW_REQUEST.json"
    wrapper = qa_dir / f"{episode}_STORYBOARD_SHEET_AI_REVIEW_WRAPPER.json"
    write(request, {"items": items})
    config = ROOT / f"configs/{episode}_storyboard_sheet_ai_review_batch_v1_{DATE}.json"
    first = Path(items[0]["path"])
    write(config, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "scene_contract_ref": f"configs/{lower}_scene_state_v1_script_locked_{DATE}.json",
        "qa_dir": str(qa_dir.relative_to(ROOT)),
        "output_dir": str(qa_dir.relative_to(ROOT)),
        "max_retries": 0,
        "base_batch_note": "Review the episode and fight storyboard sheets together; preserve a passed sheet and regenerate only the failed kind.",
        "tasks": [{
            "task_key": f"{episode}-STORYBOARD-SHEET-AI-REVIEW-V1",
            "tool_type": "ai_review",
            "scene_id": sheets["episode_sheet"]["scene_id"],
            "visual_zone": "STORYBOARD_SHEET_VISUAL_GATE",
            "prompt_file": sheets["episode_sheet"]["prompt_file"],
            "video": str(first.relative_to(ROOT)),
            "command": [
                ".ai_review_env/bin/qingshan-review",
                "review-many",
                str(request.relative_to(ROOT)),
            ],
            "report": str(wrapper.relative_to(ROOT)),
            "metadata": {"directive_refs": ["CL2X-388", "CL2X-389"]},
        }],
    })
    return config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", action="append", choices=("E26", "E27"))
    args = parser.parse_args()
    outputs = [str(build(episode)) for episode in (args.episode or ["E26", "E27"])]
    print(json.dumps({"status": "PASS", "outputs": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
