#!/usr/bin/env python3
"""Build a Chinese-constraint A/B variant of one MiniMax-H3 video task (owner-approved A/B, 2026-10-26).

The variant is the same task (same references, durations, contracts) with ``h3_constraint_language: "zh"``:
only the provider-expert constraint sentences (one take / fixed camera, no other voice, anti-duplicate) are
rendered in Chinese; every description, dialogue tag and delivery line stays English.  It gets its own task
key ``<UNIT>-ZH`` (so its transaction, receipt and clip never collide with the original unit) and is written
as a one-task transaction manifest with ``provider_post_allowed: false``.  The variant only renders on
CAMERA_GRAMMAR_V1 units; elsewhere the renderer ignores the flag and the command refuses.

Paid submission goes through the normal single-task path and budget (CLAUDE_CODE_PRODUCTION §5, "A/B"):
check headroom with ``paid_stage.sh <EP> --check`` for ``estimated_credits``, register the variant prompt in
the prompt batch like any other prompt, then submit the one-task manifest with the usual submitter.

    python3 tools/h3_constraint_ab_variant.py --manifest <EP>_VIDEO_TRANSACTION_MANIFEST_V1.json \
        --unit E04-VU-008 --prompt-dir <preproduction>/video_prompts --out <preproduction>/E04_VU-008_ZH_AB.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ENGINE_ROOT), str(ENGINE_ROOT / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from tools.h3_provider_english_contract import H3_CONSTRAINT_LANGUAGE_FIELD  # noqa: E402

SCHEMA = "qingshan.h3_constraint_language_ab_variant.v1"


def variant_task(task: dict[str, Any], language: str = "zh") -> dict[str, Any]:
    """The A/B copy of ``task``: own task key, the constraint-language flag, no submission state."""
    variant = copy.deepcopy(task)
    base_key = str(task.get("task_key") or task.get("unit_id"))
    variant["task_key"] = f"{base_key}-{language.upper()}"
    variant[H3_CONSTRAINT_LANGUAGE_FIELD] = language
    variant["ab_variant_of"] = base_key
    for key in ("submission_status", "task_id", "receipt", "prompt_status"):
        variant.pop(key, None)
    return variant


def render_variant(task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from tools.submit_giggle_video_manifest_v2 import estimated_video_credits, provider_prompt_unit
    from tools.video_prompt_compiler import COMPILE_RECEIPTS, compile_model_prompt
    text = compile_model_prompt(provider_prompt_unit(task))
    receipt = COMPILE_RECEIPTS.get(str(task.get("unit_id") or task.get("task_key"))) or {}
    if receipt.get("h3_constraint_language") != "zh":
        raise ValueError(f"{task['task_key']}:H3_CONSTRAINT_AB_NOT_APPLICABLE (only CAMERA_GRAMMAR_V1 H3 units)")
    return text, {"estimated_credits": estimated_video_credits(task)}


def build(manifest: dict[str, Any], unit: str, prompt_dir: Path, language: str = "zh") -> dict[str, Any]:
    source = next((t for t in manifest.get("tasks") or [] if str(t.get("task_key")) == unit), None)
    if source is None:
        raise ValueError(f"H3_CONSTRAINT_AB_UNIT_NOT_FOUND:{unit}")
    task = variant_task(source, language)
    text, cost = render_variant(task)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{task['task_key']}.txt"
    prompt_path.write_text(text, encoding="utf-8")
    try:
        task["prompt_file"] = os.path.relpath(prompt_path.resolve(), ENGINE_ROOT)
    except ValueError:  # pragma: no cover - other drive
        task["prompt_file"] = str(prompt_path)
    task["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    out = {key: value for key, value in manifest.items() if key != "tasks"}
    out.update({
        "ab_variant_schema": SCHEMA, "ab_variant_of": unit, "h3_constraint_language": language,
        "provider_post_allowed": False, "maximum_new_submissions": 1, "video_unit_count": 1,
        "estimated_credits": cost["estimated_credits"], "tasks": [task],
    })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--unit", required=True, help="task key of the original unit, e.g. E04-VU-008")
    parser.add_argument("--prompt-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--language", default="zh", choices=["zh"])
    args = parser.parse_args(argv)
    result = build(json.loads(args.manifest.read_text(encoding="utf-8")), args.unit, args.prompt_dir, args.language)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task = result["tasks"][0]
    print(json.dumps({"status": "PASS", "task_key": task["task_key"], "prompt_file": task["prompt_file"],
                      "estimated_credits": result["estimated_credits"], "manifest": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
