#!/usr/bin/env python3
"""Build a Chinese-constraint A/B variant of one MiniMax-H3 video task (owner-approved A/B, 2026-10-26).

The variant is the same task (same references, durations, contracts) with ``h3_constraint_language: "zh"``:
only the provider-expert constraint sentences (one take / fixed camera, no other voice, anti-duplicate) are
rendered in Chinese; every description, dialogue tag and delivery line stays English.  It gets its own task
key ``<UNIT>-ZH`` (so its transaction, receipt and clip never collide with the original unit) and is written
as a one-task transaction manifest with ``provider_post_allowed: false``.  The variant only renders on
CAMERA_GRAMMAR_V1 units; elsewhere the renderer ignores the flag and the command refuses.

Paid submission has exactly one entry (skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md §2, "H3 约束语言 A/B"):

    lines/nalu/runtime/tools/paid_stage.sh <EP> --ab-variant <out.json>

It runs the same guarded machinery as a normal S6 submit: provenance checks (this schema, a unit of the
episode, CAMERA_GRAMMAR_V1, the source unit in the episode's authority, ``--verify`` below), the
whole-batch prompt registration (the variant's exact text needs its own INCREMENTAL_EXACT_MATERIALIZATION_QA
receipt; the run stops with REVIEW_REQUIRED and the exact receipt command when it is missing), D-11
materialisation from the active order for this one task key, the budget check + reservation against the
episode cap, the submitter with its durable fingerprint store, and the credit statement + ledger entry.
The clip is harvested to ``workflow/nalu/<EP>/video_ab/<TASK>.mp4`` and never enters assembly.  A free
rehearsal of the same path: ``nalu_pipeline.py ab-variant --episode <EP> --variant <out.json>`` (no --paid).

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
    # prompt_batch_finalization / reviewed_request_sha256 bind the ORIGINAL prompt; the variant's text
    # needs its own review, so carrying them over would only produce a mismatch at the gate.
    for key in ("submission_status", "task_id", "receipt", "prompt_status",
                "prompt_batch_finalization", "reviewed_request_sha256"):
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


def verify(variant: dict[str, Any]) -> list[str]:
    """Failures when ``variant`` is not exactly what :func:`build` writes: schema, one task, and the
    prompt file re-rendered from that task reproducing its bytes and credit estimate."""
    failures: list[str] = []
    if variant.get("ab_variant_schema") != SCHEMA:
        failures.append("AB_VARIANT_SCHEMA_MISMATCH")
    tasks = variant.get("tasks") or []
    if len(tasks) != 1:
        return failures + [f"AB_VARIANT_TASK_COUNT:{len(tasks)}"]
    task = tasks[0]
    try:
        text, cost = render_variant(copy.deepcopy(task))
    except Exception as exc:  # noqa: BLE001 - reported, never raised past the verifier
        return failures + [f"AB_VARIANT_RERENDER_FAILED:{type(exc).__name__}:{exc}"]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    prompt = Path(task.get("prompt_file") or "")
    prompt = prompt if prompt.is_absolute() else ENGINE_ROOT / prompt
    if digest != task.get("prompt_sha256"):
        failures.append("AB_VARIANT_PROMPT_NOT_RENDERER_OUTPUT")
    if not prompt.is_file() or hashlib.sha256(prompt.read_bytes()).hexdigest() != digest:
        failures.append("AB_VARIANT_PROMPT_FILE_MISMATCH")
    if variant.get("estimated_credits") != cost["estimated_credits"]:
        failures.append("AB_VARIANT_ESTIMATE_MISMATCH")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verify", type=Path, help="check an existing variant manifest instead of building one")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--unit", help="task key of the original unit, e.g. E04-VU-008")
    parser.add_argument("--prompt-dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--language", default="zh", choices=["zh"])
    args = parser.parse_args(argv)
    if args.verify:
        failures = verify(json.loads(args.verify.read_text(encoding="utf-8")))
        print(json.dumps({"status": "FAIL" if failures else "PASS", "failures": failures}))
        return 2 if failures else 0
    if not (args.manifest and args.unit and args.prompt_dir and args.out):
        parser.error("--manifest, --unit, --prompt-dir and --out are required to build a variant")
    result = build(json.loads(args.manifest.read_text(encoding="utf-8")), args.unit, args.prompt_dir, args.language)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task = result["tasks"][0]
    print(json.dumps({"status": "PASS", "task_key": task["task_key"], "prompt_file": task["prompt_file"],
                      "estimated_credits": result["estimated_credits"], "manifest": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
