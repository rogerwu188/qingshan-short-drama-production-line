#!/usr/bin/env python3
"""Persist exact-SHA registered Q1 evidence for the selected E40 QA-v2 keyframes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from shot_media_admission_gate import DEFAULT_REGISTRY, evaluate


ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa/e40_remake_20260820/spatial_keyframes_qa_v2/q1_registered"
GATES = (
    "CHARACTER-IDENTITY-ADMISSION",
    "SCENE-AUTHORITY-LOCK",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
)
CANDIDATES = {
    "R02": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R02-KEYFRAME-QA-V2-R2.png",
    "R03": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R03-KEYFRAME-QA-V2-R3.png",
    "R04": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R04-KEYFRAME-QA-V2-R3.png",
    "R05": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R05-KEYFRAME-QA-V2.png",
    "R06B": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R06B-KEYFRAME-QA-V2-R2.png",
    "R06C": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R06C-KEYFRAME-QA-V2-R2.png",
    "R07": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R07-KEYFRAME-QA-V2-R2.png",
    "R08": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2/E40-R08-KEYFRAME-QA-V2.png",
}
FINDINGS = {
    "R02": "陈迹与白鲤身份成立；四枚霜印在长案起始态成立；地图轴线和时代场景成立。",
    "R03": "陈迹并指横抹的起始动势成立；四枚霜印仍完整且无终态霜粉；时代场景成立。",
    "R04": "陈迹投掷手势、空中拓影与帘后云妃剪影成立；云妃未露面；时代场景成立。",
    "R05": "白鲤帘侧抬眼望向陈迹；两人身份、帘侧子空间与时代场景成立。",
    "R06B": "云羊、两名暗桩和两张纸人数量准确；以分离站位保留后续可执行轨迹；时代场景成立。",
    "R06C": "云羊与一名暗桩身份成立；短刃朝下的动作前缘为卸腕留出物理轨迹；时代场景成立。",
    "R07": "皎兔身份成立；两支不同箭从正面与侧向进入且尚未碰撞，截断轨迹可执行；时代场景成立。",
    "R08": "白鲤、陈迹身份成立；抬手触领与单枚红玉起始态成立；帘侧空间和时代场景成立。",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    raise SystemExit(
        "LEGACY_E40_Q1_EVIDENCE_BUILDER_DISABLED: hard-coded candidates are not bound "
        "to the canonical asset-library resolution report; generate evidence from the "
        "native-registry manifest and exact harvested task lineage instead"
    )
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    summary = []
    for unit, relative in CANDIDATES.items():
        asset = ROOT / relative
        asset_sha = sha256(asset)
        rows = []
        for gate_id in GATES:
            evidence_path = QA_DIR / unit / f"{gate_id}.json"
            write_json(evidence_path, {
                "schema": "qingshan.registered_visual_evidence.v1",
                "episode": "E40-REMAKE-QA-V2",
                "unit_id": unit,
                "gate_id": gate_id,
                "status": "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_path": relative,
                "reviewed_asset_sha256": asset_sha,
                "reviewer_type": "AI_VISUAL",
                "finding": FINDINGS[unit],
            })
            rows.append({
                "gate_id": gate_id,
                "status": "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": str(evidence_path.relative_to(ROOT)),
                "evidence_sha256": sha256(evidence_path),
                "original_resolution_review": True,
                "reviewer_type": "AI_VISUAL",
            })
        admission = {
            "schema": "qingshan.shot_media_admission_request.v2",
            "kind": "KEYFRAME_VIDEO_SUBMIT",
            "episode": "E40-REMAKE-QA-V2",
            "unit_id": unit,
            "asset_path": relative,
            "asset_sha256": asset_sha,
            "evidence": rows,
            "technical_qa": {"status": "TECHNICAL_PASS_CONTENT_UNREVIEWED"},
        }
        admission_path = QA_DIR / unit / "admission_request.json"
        write_json(admission_path, admission)
        result = evaluate(admission, registry, ROOT)
        result_path = QA_DIR / unit / "admission_result.json"
        write_json(result_path, result)
        summary.append({
            "unit_id": unit,
            "asset_path": relative,
            "asset_sha256": asset_sha,
            "status": result["status"],
            "downstream_status": result["downstream_status"],
            "admission_result": str(result_path.relative_to(ROOT)),
            "admission_result_sha256": sha256(result_path),
        })
    report = {
        "schema": "qingshan.e40_keyframe_q1_registered_batch.v2",
        "episode": "E40-REMAKE-QA-V2",
        "status": "PASS" if all(row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT" for row in summary) else "FAIL",
        "results": summary,
        "paid_credits": 0,
    }
    write_json(QA_DIR / "E40_KEYFRAME_Q1_REGISTERED_BATCH_V2.json", report)
    print(json.dumps({"status": report["status"], "admitted": sum(row["downstream_status"] == "ADMITTED_FOR_VIDEO_SUBMIT" for row in summary)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
