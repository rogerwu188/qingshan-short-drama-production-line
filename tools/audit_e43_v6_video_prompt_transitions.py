#!/usr/bin/env python3
"""Audit every E43 video prompt for transition, performance and AV completeness."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(manifest: dict[str, Any], prompt_manifest: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    boundary_prompt_counts: Counter[str] = Counter()
    prompt_by_unit = {str(row["unit_id"]): row for row in prompt_manifest.get("rows") or []}
    units = manifest.get("units") or []
    required_phrases = (
        "竖屏9:16", "720p", "seedance-2.0-pro（SD2 标准版）",
        "【镜头硬合同】", "【转场硬合同】", "入场边界=", "入场预留=",
        "出场边界=", "片尾转场预留=", "出场交棒=", "片尾剧情动作=",
        "末态必须保持=", "声尾=", "剧情动机=", "【视觉与现场声硬合同】",
        "【节拍】", "物理动作链：", "表演硬锁：", "表情弧=", "微动作=",
        "事件反应=", "身体同步=", "【同任务原生声音】",
    )
    forbidden_phrases = (
        "seedance-2.0-fast", "16:9", "镜头随主要动作平稳调整景别",
        "缓慢推镜", "缓慢推进", "静止等待", "保持站位", "保持不动",
    )
    for index, unit in enumerate(units):
        unit_id = str(unit.get("unit_id"))
        prompt_row = prompt_by_unit.get(unit_id)
        unit_failures: list[str] = []
        if not prompt_row:
            unit_failures.append("PROMPT_MANIFEST_ROW_MISSING")
            rows.append({"unit_id": unit_id, "status": "FAIL", "failures": unit_failures})
            failures.extend(f"{unit_id}:{item}" for item in unit_failures)
            continue
        prompt_path = resolve(str(prompt_row["prompt_path"]))
        if not prompt_path.is_file():
            unit_failures.append("PROMPT_FILE_MISSING")
            text = ""
        else:
            text = prompt_path.read_text(encoding="utf-8")
            if sha256(prompt_path) != prompt_row.get("prompt_sha256"):
                unit_failures.append("PROMPT_SHA_MISMATCH")
        for phrase in required_phrases:
            if phrase not in text:
                unit_failures.append(f"REQUIRED_PROMPT_FIELD_MISSING:{phrase}")
        for phrase in forbidden_phrases:
            if phrase in text:
                unit_failures.append(f"FORBIDDEN_PROMPT_LANGUAGE:{phrase}")
        for marker in ("【镜头硬合同】", "【转场硬合同】", "入场边界=", "出场边界=", "片尾转场预留="):
            if text.count(marker) != 1:
                unit_failures.append(f"PROMPT_MARKER_COUNT:{marker}:{text.count(marker)}")

        incoming = unit.get("incoming_transition_contract")
        outgoing = unit.get("outgoing_transition_contract")
        incoming_id = str(incoming["boundary_id"]) if incoming else "SEQUENCE_START"
        outgoing_id = str(outgoing["boundary_id"]) if outgoing else "SEQUENCE_END"
        for boundary_id in (incoming_id, outgoing_id):
            if text.count(boundary_id) != 1:
                unit_failures.append(f"BOUNDARY_BINDING_COUNT:{boundary_id}:{text.count(boundary_id)}")
            if boundary_id.startswith("BND-"):
                boundary_prompt_counts[boundary_id] += text.count(boundary_id)
        if index == 0 and incoming is not None:
            unit_failures.append("FIRST_UNIT_MUST_USE_SEQUENCE_START")
        if index > 0 and incoming is None:
            unit_failures.append("INTERIOR_UNIT_INCOMING_CONTRACT_MISSING")
        if index == len(units) - 1 and outgoing is not None:
            unit_failures.append("LAST_UNIT_MUST_USE_SEQUENCE_END")
        if index < len(units) - 1 and outgoing is None:
            unit_failures.append("INTERIOR_UNIT_OUTGOING_CONTRACT_MISSING")
        for direction, contract in (("incoming", incoming), ("outgoing", outgoing)):
            if not contract:
                continue
            handle_key = "incoming_handle_seconds" if direction == "incoming" else "outgoing_handle_seconds"
            handle = float(contract.get(handle_key, -1))
            if not 0.6 <= handle <= 1.5:
                unit_failures.append(f"TRANSITION_HANDLE_OUT_OF_RANGE:{direction}:{handle}")
            for key in ("plot_motivation", "visual_bridge", "action_bridge", "sound_bridge", "axis_strategy"):
                if not str(contract.get(key) or "").strip():
                    unit_failures.append(f"TRANSITION_CONTRACT_FIELD_MISSING:{direction}:{key}")
        if outgoing and index + 1 < len(units):
            next_incoming = units[index + 1].get("incoming_transition_contract") or {}
            if outgoing.get("boundary_id") != next_incoming.get("boundary_id"):
                unit_failures.append("ADJACENT_BOUNDARY_ID_MISMATCH")
            if outgoing != next_incoming:
                unit_failures.append("ADJACENT_TRANSITION_CONTRACT_NOT_IDENTICAL")

        failures.extend(f"{unit_id}:{item}" for item in unit_failures)
        rows.append({
            "unit_id": unit_id,
            "status": "PASS" if not unit_failures else "FAIL",
            "prompt_path": str(prompt_path.resolve().relative_to(ROOT)) if prompt_path.exists() else str(prompt_path),
            "prompt_sha256": sha256(prompt_path) if prompt_path.is_file() else None,
            "incoming_boundary_id": incoming_id,
            "outgoing_boundary_id": outgoing_id,
            "transition_prompt_present": "【转场硬合同】" in text,
            "outgoing_plot_transition_present": "片尾剧情动作=" in text,
            "camera_contract_present": "【镜头硬合同】" in text,
            "physical_action_design_present": "物理动作链：" in text,
            "microexpression_design_present": all(x in text for x in ("表情弧=", "微动作=", "事件反应=")),
            "native_av_contract_present": "【同任务原生声音】" in text,
            "failures": unit_failures,
        })

    expected_boundaries = max(0, len(units) - 1)
    if len(boundary_prompt_counts) != expected_boundaries:
        failures.append(f"BOUNDARY_UNIQUE_COUNT:{len(boundary_prompt_counts)}!={expected_boundaries}")
    for boundary_id, count in sorted(boundary_prompt_counts.items()):
        if count != 2:
            failures.append(f"BOUNDARY_PROMPT_OCCURRENCE_COUNT:{boundary_id}:{count}!=2")
    if len(rows) != 26:
        failures.append(f"E43_VIDEO_UNIT_COUNT:{len(rows)}!=26")
    return {
        "schema": "qingshan.e43_v6_video_prompt_transition_audit.v1",
        "episode": "E43",
        "status": "PASS" if not failures else "FAIL",
        "video_unit_count": len(rows),
        "transition_boundary_count": len(boundary_prompt_counts),
        "all_video_prompts_have_incoming_and_outgoing_transition_information": not failures,
        "policy": {
            "outgoing_plot_transition_required_per_video": True,
            "transition_handle_seconds": {"minimum": 0.6, "maximum": 1.5},
            "camera_action_microexpression_native_av_required": True,
            "model": "seedance-2.0-pro",
            "resolution": "720p",
            "aspect_ratio": "9:16",
        },
        "rows": rows,
        "boundary_prompt_counts": dict(sorted(boundary_prompt_counts.items())),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prompt-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(load(args.manifest), load(args.prompt_manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "video_unit_count": result["video_unit_count"],
        "transition_boundary_count": result["transition_boundary_count"],
        "failure_count": len(result["failures"]),
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
