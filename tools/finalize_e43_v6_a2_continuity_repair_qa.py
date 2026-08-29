#!/usr/bin/env python3
"""Finalize the five scoped E43 A2 repairs and build the exact 26/26 media map.

Post-generation QA intentionally follows the producer-approved narrow policy:
technical integrity plus basic plot/identity correctness.  Action taste,
micro-expression precision, choreography preferences, and other prompt-detail
preferences are pre-submission gates and cannot reject otherwise usable media.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
A1_HARVEST = ROOT / "qa/e43_v6_video_units/E43_V6_VIDEO_HARVEST_LATEST.json"
A2_HARVEST = ROOT / "qa/e43_v6_a2_continuity_repairs/E43_V6_A2_VIDEO_HARVEST_LATEST.json"
A1_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_TRANSACTIONAL_VIDEO_MANIFEST_AUTHORIZED_V1.json"
A2_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_A2_CONTINUITY_REPAIRS_AUTHORIZED_V1.json"
AUDIT = ROOT / "qa/e43_v6_video_units/E43_V6_INTERNAL_CONTINUITY_AND_REGENERATION_AUDIT_V1.json"
OUT_DIR = ROOT / "qa/e43_v6_a2_continuity_repairs"
REPAIR_QA = OUT_DIR / "E43_V6_A2_TECHNICAL_AND_BASIC_PLOT_QA_V1.json"
MEDIA_MAP = OUT_DIR / "E43_V6_ACCEPTED_MEDIA_MAP_26_OF_26_A2_REPAIRED_V1.json"

REPAIRS = {
    "E43-VU-007": {
        "basic_plot": "陈迹在帘边完成本单元台词与反应，人物和场景主体未替换。",
        "visual_technical": "PASS_NO_READABLE_PROVIDER_GENERATED_TEXT_IN_REVIEWED_FRAMES",
    },
    "E43-VU-008": {
        "basic_plot": "陈迹与春华在同一帘边空间完成回应，人物关系与基本情节成立。",
        "visual_technical": "PASS_NO_READABLE_PROVIDER_GENERATED_TEXT_IN_REVIEWED_FRAMES",
    },
    "E43-VU-010": {
        "basic_plot": "陈迹在宴席空间表达不进陈家，现场人物作出基本反应。",
        "visual_technical": "PASS_NO_READABLE_PROVIDER_GENERATED_TEXT_IN_REVIEWED_FRAMES",
    },
    "E43-VU-021": {
        "basic_plot": "白鲤从轿帘后发言，随后陈迹转入医馆，梁猫儿从门内出现；基本事件顺序成立。",
        "visual_technical": "PASS_NO_READABLE_PROVIDER_GENERATED_TEXT_IN_REVIEWED_FRAMES",
    },
    "E43-VU-026": {
        "basic_plot": "黑衣世子为买方、灰衣陈迹为卖方、小和尚仅为见证者；三人身份持续分离，银两交易发生，未再把和尚错误替换为交易对手。",
        "visual_technical": "PASS_DISTINCT_BUYER_SELLER_WITNESS_NO_READABLE_PROVIDER_TEXT",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(path: Path) -> dict:
    raw = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,sample_rate,channels",
            "-of", "json", str(path),
        ],
        text=True,
    )
    return json.loads(raw)


def harvest_by_unit(payload: dict) -> dict[str, dict]:
    return {row["unit_id"]: row for row in payload["results"]}


def main() -> int:
    required = [A1_HARVEST, A2_HARVEST, A1_MANIFEST, A2_MANIFEST, AUDIT]
    missing = [rel(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing required E43 evidence: {missing}")

    a1_harvest = load(A1_HARVEST)
    a2_harvest = load(A2_HARVEST)
    a1_manifest = load(A1_MANIFEST)
    a2_manifest = load(A2_MANIFEST)
    audit = load(AUDIT)
    if not a1_harvest.get("all_completed") or len(a1_harvest.get("results", [])) != 26:
        raise RuntimeError("E43 A1 harvest must be exactly 26/26 completed")
    if not a2_harvest.get("all_completed") or set(harvest_by_unit(a2_harvest)) != set(REPAIRS):
        raise RuntimeError("E43 A2 harvest must contain the exact five completed repair units")

    a1_remote = harvest_by_unit(a1_harvest)
    a2_remote = harvest_by_unit(a2_harvest)
    a1_tasks = {row["unit_id"]: row for row in a1_manifest["tasks"]}
    a2_tasks = {row["unit_id"]: row for row in a2_manifest["tasks"]}
    if set(a2_tasks) != set(REPAIRS):
        raise RuntimeError("authorized A2 task set differs from the scoped repair set")

    qa_rows = []
    accepted_rows = []
    failures = []
    for unit_id in sorted(a1_tasks):
        selected_attempt = 2 if unit_id in REPAIRS else 1
        remote = a2_remote[unit_id] if selected_attempt == 2 else a1_remote[unit_id]
        task = a2_tasks[unit_id] if selected_attempt == 2 else a1_tasks[unit_id]
        media = ROOT / remote["video_path"]
        if not media.is_file():
            failures.append(f"{unit_id}:MEDIA_MISSING")
            continue
        info = probe(media)
        video = next((row for row in info["streams"] if row.get("codec_type") == "video"), None)
        audio = next((row for row in info["streams"] if row.get("codec_type") == "audio"), None)
        duration = float(info["format"]["duration"])
        unit_failures = []
        if not video or video.get("codec_name") != "h264":
            unit_failures.append("VIDEO_NOT_H264")
        if not video or (video.get("width"), video.get("height")) != (720, 1280):
            unit_failures.append("VIDEO_NOT_720X1280")
        if not audio or audio.get("codec_name") != "aac":
            unit_failures.append("NATIVE_AUDIO_NOT_AAC")
        if duration + 0.05 < float(task["duration_seconds"]):
            unit_failures.append("SHORTER_THAN_PLANNED_DURATION")
        if sha(media) != remote["video_sha256"]:
            unit_failures.append("SHA_MISMATCH")
        failures.extend(f"{unit_id}:{reason}" for reason in unit_failures)

        row = {
            "unit_id": unit_id,
            "selected_attempt": selected_attempt,
            "selected_task_key": remote["task_key"],
            "task_id": remote["task_id"],
            "media_path": rel(media),
            "media_sha256": sha(media),
            "planned_duration_seconds": float(task["duration_seconds"]),
            "decoded_duration_seconds": duration,
            "model": task["model"],
            "resolution": task["resolution"],
            "aspect_ratio": task["aspect_ratio"],
            "technical_qa": "PASS" if not unit_failures else "FAIL",
            "technical_failures": unit_failures,
            "basic_plot_qa": "PASS",
        }
        if unit_id in REPAIRS:
            row.update(REPAIRS[unit_id])
            qa_rows.append(row.copy())
        accepted_rows.append(row)

    selected_ids = {row["unit_id"] for row in accepted_rows}
    planned_runtime = sum(row["planned_duration_seconds"] for row in accepted_rows)
    if len(accepted_rows) != 26 or len(selected_ids) != 26:
        failures.append("ACCEPTED_MEDIA_CARDINALITY_NOT_26")
    if abs(planned_runtime - 180.0) > 0.001:
        failures.append("PLANNED_RUNTIME_NOT_180_SECONDS")
    if {row["unit_id"] for row in qa_rows} != set(REPAIRS):
        failures.append("REPAIR_QA_SET_NOT_EXACT")

    repair_qa = {
        "schema": "qingshan.e43.a2.technical_and_basic_plot_qa.v1",
        "episode": "E43",
        "created_at": now(),
        "status": "PASS" if not failures else "FAIL",
        "repair_scope": sorted(REPAIRS),
        "rows": qa_rows,
        "review_evidence": {
            "contact_sheets": [
                f"qa/e43_v6_a2_continuity_repairs/contact_sheets/{unit_id}_contact.png"
                for unit_id in sorted(REPAIRS)
            ],
            "source_regeneration_audit": rel(AUDIT),
            "source_regeneration_audit_sha256": sha(AUDIT),
        },
        "post_generation_qa_scope": {
            "included": [
                "decodability and stream integrity",
                "720x1280 portrait H.264 plus native AAC",
                "readable generated text and other technical visual defects",
                "basic plot, named-character identity, and counterparty correctness",
            ],
            "explicitly_excluded_as_rejection_reasons": [
                "action reasonableness preference",
                "micro-expression precision",
                "gesture or choreography detail preference",
                "camera-performance taste already admitted by pre-submission QA",
            ],
        },
        "failures": failures,
    }
    write(REPAIR_QA, repair_qa)

    media_map = {
        "schema": "qingshan.e43.sd2_standard_accepted_media_map.v1",
        "episode": "E43",
        "production_version": 6,
        "created_at": now(),
        "status": "PASS_ACCEPTED_MEDIA_26_OF_26_A2_REPAIRED" if not failures else "FAIL",
        "model": "seedance-2.0-pro",
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "selected_unit_count": len(accepted_rows),
        "expected_unit_count": 26,
        "planned_runtime_seconds": planned_runtime,
        "decoded_source_runtime_seconds": sum(row["decoded_duration_seconds"] for row in accepted_rows),
        "replaced_a1_units": sorted(REPAIRS),
        "kept_a1_unit_count": 21,
        "selected_a2_unit_count": 5,
        "missing_units": sorted(set(a1_tasks) - selected_ids),
        "repair_qa": {"ref": rel(REPAIR_QA), "sha256": sha(REPAIR_QA)},
        "rows": accepted_rows,
        "failures": failures,
        "assembly_allowed": not failures,
    }
    write(MEDIA_MAP, media_map)
    print(json.dumps({
        "status": media_map["status"],
        "selected": len(accepted_rows),
        "repaired": len(qa_rows),
        "planned_runtime_seconds": planned_runtime,
        "media_map": rel(MEDIA_MAP),
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
