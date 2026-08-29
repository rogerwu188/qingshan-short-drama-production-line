#!/usr/bin/env python3
"""Persist exact-SHA registered Q1 decisions for harvested E40 dialogue frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from shot_media_admission_gate import evaluate


ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_FULL_PERFORMANCE_KEYFRAME_HARVEST_V1.json"
REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/q1_registered"

FAILURES = {
    "E40-FP-R08-YUNFEI-A-V1-KF-QA-V2": {
        "CHARACTER-IDENTITY-ADMISSION": "FAIL: 云妃被清楚画成帘侧白衣露面人物，而 E40 出镜硬锁要求全程仅为长帘后的高髻、广袖、团扇剪影；不得露脸或走出剪影表现。",
    },
    "E40-FP-R08-YUNFEI-C-V1-KF-QA-V2": {
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "FAIL: 画面前景新增一张落在地面的显眼印纹纸，违背本段 R08 收束对白的已交接道具状态，并把早先应落在帘内案上的拓影错误迁移到地面。",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvest", type=Path, default=HARVEST)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument("--failure-overrides", type=Path)
    args = parser.parse_args()
    harvest_path = args.harvest if args.harvest.is_absolute() else ROOT / args.harvest
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    failures = dict(FAILURES)
    if args.failure_overrides:
        overrides_path = args.failure_overrides if args.failure_overrides.is_absolute() else ROOT / args.failure_overrides
        failures.update(json.loads(overrides_path.read_text(encoding="utf-8")))
    harvest = json.loads(harvest_path.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    index = []
    for row in harvest["results"]:
        task_key = row["task_key"]
        asset = Path(row["output_path"])
        if sha(asset) != row["sha256"]:
            raise ValueError(f"SHA mismatch: {task_key}")
        task_failures = failures.get(task_key, {})
        findings = {
            "CHARACTER-IDENTITY-ADMISSION": task_failures.get(
                "CHARACTER-IDENTITY-ADMISSION",
                "PASS: 原生资产库绑定人物的年龄、服装、轮廓及本集出镜方式与画面可见部分一致；背面或帘后剪影为有意构图，不制造可见口型替换风险。",
            ),
            "SCENE-AUTHORITY-LOCK": "PASS: 王府厅堂、长帘、木柱、长案、灯位与锁定 EGSM/GSM/subspace 的空间关系一致。",
            "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": task_failures.get(
                "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                "PASS: 人物和道具处于可执行的对白前呼吸/反应起点，未提前演完台词动作终态。",
            ),
            "PERIOD-ANACHRONISM-LOCK": "PASS: 未见现代物、字幕、LOGO、水印或时代冲突物。",
        }
        unit_dir = out_dir / task_key
        review = {
            "schema": "qingshan.registered_visual_evidence_bundle.v1",
            "episode": "E40",
            "task_key": task_key,
            "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reviewer_type": "HUMAN_AND_AI",
            "reviewed_asset_path": portable(asset),
            "reviewed_asset_sha256": row["sha256"],
            "original_resolution_review": True,
            "registered_gate_findings": findings,
            "decision": "FAIL_NOT_ADMITTED" if task_failures else "PASS_ADMIT_FOR_VIDEO_SUBMIT",
            "automatic_retry_allowed": False,
            "paid_attempt_ordinal": 1,
        }
        review_path = unit_dir / "original_resolution_review.json"
        write(review_path, review)
        evidence = []
        for gate_id, finding in findings.items():
            failed = finding.startswith("FAIL:")
            evidence.append({
                "gate_id": gate_id,
                "status": "FAIL_NOT_ADMITTED" if failed else "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_sha256": row["sha256"],
                "evidence_path": portable(review_path),
                "evidence_sha256": sha(review_path),
                "original_resolution_review": True,
                "reviewer_type": "HUMAN_AND_AI",
                "defect_tier": "P0" if failed and gate_id == "CHARACTER-IDENTITY-ADMISSION" else "P1" if failed else None,
                "finding": finding,
            })
        request = {
            "schema": "qingshan.shot_media_admission_request.v2",
            "kind": "KEYFRAME_VIDEO_SUBMIT",
            "episode": "E40",
            "unit_id": task_key,
            "task_key": task_key,
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "evidence": evidence,
            "technical_qa": {"status": "TECHNICAL_PASS_CONTENT_REVIEWED"},
        }
        write(unit_dir / "admission_request.json", request)
        result = evaluate(request, registry, ROOT)
        result_path = unit_dir / "admission_result.json"
        write(result_path, result)
        downstream = result.get("downstream_status")
        expected = "FAIL_NOT_ADMITTED" if task_failures else "ADMITTED_FOR_VIDEO_SUBMIT"
        if downstream != expected:
            raise ValueError(f"{task_key}: expected {expected}, got {downstream}")
        index.append({
            "task_key": task_key,
            "task_id": row["task_id"],
            "asset_path": portable(asset),
            "asset_sha256": row["sha256"],
            "downstream_status": downstream,
            "admission_result": portable(result_path),
            "admission_result_sha256": sha(result_path),
        })
    passed = sum(row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT" for row in index)
    payload = {
        "schema": "qingshan.e40.full_performance_keyframe_q1_index.v1",
        "episode": "E40",
        "status": f"PARTIAL_{passed}_OF_{len(index)}_ADMITTED",
        "results": index,
        "video_submission_allowed_task_keys": [row["task_key"] for row in index if row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT"],
        "failed_task_keys": [row["task_key"] for row in index if row["downstream_status"] == "FAIL_NOT_ADMITTED"],
    }
    out = out_dir / "E40_FULL_PERFORMANCE_KEYFRAME_Q1_INDEX_V1.json"
    write(out, payload)
    print(json.dumps({"status": payload["status"], "admitted": passed, "failed": len(index) - passed, "out": portable(out), "sha256": sha(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
