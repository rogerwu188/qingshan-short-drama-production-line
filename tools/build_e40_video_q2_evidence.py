#!/usr/bin/env python3
"""Persist exact-SHA registered Q2 evidence for admitted E40 remake videos."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from shot_media_admission_gate import DEFAULT_REGISTRY, VIDEO_REQUIRED_GATES, evaluate


ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa/e40_remake_20260820/video_q2_registered"
CANDIDATES = {
    "R02": "working_assets/e40_remake_20260820/video_qa_v2_retry2/R02/E40-R02-VIDEO-QA-V2-ATTEMPT2.mp4",
    "R03": "working_assets/e40_remake_20260820/video_qa_v2_retry2/R03/E40-R03-VIDEO-QA-V2-ATTEMPT2.mp4",
    "R04": "working_assets/e40_remake_20260820/video_qa_v2/R04/E40-R04-VIDEO-QA-V2-FIRST-PASS.mp4",
    "R06C": "working_assets/e40_remake_20260820/video_qa_v2/R06C/E40-R06C-VIDEO-QA-V2-FIRST-PASS.mp4",
    "R07": "working_assets/e40_remake_20260820/video_qa_v2/R07/E40-R07-VIDEO-QA-V2-FIRST-PASS.mp4",
    "R08": "working_assets/e40_remake_20260820/video_qa_v2_retry2/R08/E40-R08-VIDEO-QA-V2-ATTEMPT2.mp4",
}
FINDINGS = {
    "R02": "陈迹与白鲤身份连续；四枚霜印数量保持四并依次化为霜粉；长案、帘位和时代环境连续。",
    "R03": "陈迹身份连续；横抹后霜粉散尽并转向侧厢，动作起因、过程、结果清楚；无现代物件。",
    "R04": "陈迹抛出拓影、帘后云妃剪影承接和陈迹反应构成可读因果；身份、花厅空间与时代环境连续。",
    "R06C": "云羊与暗桩身份可区分；短刃攻防、卸腕和停势连续可读；柱廊轴线与时代物件稳定。",
    "R07": "皎兔身份稳定；正侧两箭轨迹和截断动作清楚，人物与箭的空间关系连续；无现代物件。",
    "R08": "白鲤与陈迹身份连续；抬手、衣领松动、单枚红玉显露及末段微亮顺序成立；帘侧空间稳定。",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    video = next(row for row in payload["streams"] if row.get("codec_type") == "video")
    if int(video.get("width") or 0) != 720 or int(video.get("height") or 0) != 1280:
        raise ValueError(f"unexpected dimensions for {path}: {video.get('width')}x{video.get('height')}")
    return payload


def main() -> int:
    raise SystemExit(
        "LEGACY_E40_Q2_EVIDENCE_BUILDER_DISABLED: hard-coded videos inherit invalid "
        "fresh-identity keyframes; Q2 must consume an exact-SHA Q1 admission whose "
        "source task passed native asset-library resolution"
    )
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    summary = []
    for unit, relative in CANDIDATES.items():
        asset = ROOT / relative
        asset_sha = sha256(asset)
        technical = probe(asset)
        technical_path = QA_DIR / unit / "technical_ffprobe.json"
        write_json(technical_path, {
            "schema": "qingshan.video_technical_q2.v1",
            "status": "TECHNICAL_PASS_CONTENT_UNREVIEWED",
            "reviewed_asset_path": relative,
            "reviewed_asset_sha256": asset_sha,
            "ffprobe": technical,
        })
        evidence = []
        for gate_id in VIDEO_REQUIRED_GATES:
            evidence_path = QA_DIR / unit / f"{gate_id}.json"
            write_json(evidence_path, {
                "schema": "qingshan.registered_video_visual_evidence.v1",
                "episode": "E40-REMAKE-QA-V2",
                "unit_id": unit,
                "gate_id": gate_id,
                "status": "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_path": relative,
                "reviewed_asset_sha256": asset_sha,
                "reviewer_type": "AI_VISUAL",
                "review_frames": [
                    f"qa/e40_remake_20260820/video_q2_registered/original_frames/{unit}_start.png",
                    f"qa/e40_remake_20260820/video_q2_registered/original_frames/{unit}_mid.png",
                    f"qa/e40_remake_20260820/video_q2_registered/original_frames/{unit}_end.png",
                ],
                "finding": FINDINGS[unit],
            })
            evidence.append({
                "gate_id": gate_id,
                "status": "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": str(evidence_path.relative_to(ROOT)),
                "evidence_sha256": sha256(evidence_path),
                "original_resolution_review": True,
                "reviewer_type": "AI_VISUAL",
            })
        request = {
            "schema": "qingshan.shot_media_admission_request.v2",
            "kind": "VIDEO_ASSEMBLY",
            "episode": "E40-REMAKE-QA-V2",
            "unit_id": unit,
            "asset_path": relative,
            "asset_sha256": asset_sha,
            "evidence": evidence,
            "technical_qa": {
                "status": "TECHNICAL_PASS_CONTENT_UNREVIEWED",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": str(technical_path.relative_to(ROOT)),
                "evidence_sha256": sha256(technical_path),
            },
        }
        request_path = QA_DIR / unit / "admission_request.json"
        write_json(request_path, request)
        result = evaluate(request, registry, ROOT)
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
    batch = {
        "schema": "qingshan.e40_video_q2_registered_batch.v1",
        "episode": "E40-REMAKE-QA-V2",
        "status": "PASS" if all(row["downstream_status"] == "ADMITTED_FOR_ASSEMBLY" for row in summary) else "FAIL",
        "results": summary,
        "excluded_units": {
            "R05": "PROVIDER_FAILED_FULLY_REFUNDED_NO_VIDEO",
            "R06B": "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF_FAIL_NOT_ADMITTED",
        },
        "paid_credits": 0,
    }
    batch_path = QA_DIR / "E40_VIDEO_Q2_REGISTERED_BATCH_V1.json"
    write_json(batch_path, batch)
    print(json.dumps({"status": batch["status"], "admitted": sum(row["downstream_status"] == "ADMITTED_FOR_ASSEMBLY" for row in summary), "batch": str(batch_path)}, ensure_ascii=False))
    return 0 if batch["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
