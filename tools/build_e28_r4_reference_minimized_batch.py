#!/usr/bin/env python3
"""Build E28 failed-only R4 with the provider-safe maximum of three references."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r3_20260720.json"
OUT = ROOT / "configs/E28_standard_storyboard_v1_sheetbound_failed_only_r4_refcap3_20260720.json"


def reference_role(path: str) -> str:
    lowered = path.lower()
    if "keyframe" in lowered:
        return "scene"
    if "chenji" in lowered:
        return "陈迹"
    if "jiaotu" in lowered:
        return "皎兔"
    if "yunyang" in lowered:
        return "云羊"
    if "protected-clerk" in lowered or "protected_clerk" in lowered:
        return "活口"
    return "other"


def select_references(task: dict) -> list[str]:
    refs = list(task.get("reference_images") or [])
    if len(refs) <= 3:
        return refs
    scene = [path for path in refs if reference_role(path) == "scene"]
    speaker = str(task.get("speaker") or "")
    speaker_refs = [path for path in refs if reference_role(path) == speaker]
    selected = (scene[:1] + speaker_refs[:1])
    for path in refs:
        if path not in selected and len(selected) < 3:
            selected.append(path)
    return selected


def main() -> None:
    payload = json.loads(BASE.read_text(encoding="utf-8"))
    payload.update({
        "status": "READY_FOR_PARALLEL_SUBMIT",
        "retry_of": str(BASE.relative_to(ROOT)),
        "output_dir": "working_assets/e28_standard_storyboard_v1_sheetbound_failed_only_r4_refcap3_20260720",
        "qa_dir": "qa/e28_standard_storyboard_v1_sheetbound_failed_only_r4_refcap3_20260720",
        "max_retries": 0,
        "base_batch_note": "R4 retries only the 30 unresolved R3 tasks. R3 failed before generation while uploading 4-5 references. Cap each task at three references, preserving the scene keyframe and speaker identity when available. Keep all six admitted passes unchanged.",
    })
    for task in payload["tasks"]:
        before = list(task.get("reference_images") or [])
        after = select_references(task)
        task["reference_images"] = after
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        task["reference_repair"] = {
            "reason": "R3_REMOTE_UPLOAD_REFERENCE_FAILED_ALL_PROVIDERS",
            "before_count": len(before),
            "after_count": len(after),
            "provider_safe_cap": 3,
            "preserved_pass_siblings": True,
        }
        if len(after) > 3 or not after:
            raise SystemExit(f"unsafe reference set for {task.get('task_key')}: {after}")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
