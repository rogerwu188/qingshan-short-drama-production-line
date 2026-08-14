#!/usr/bin/env python3
"""Admit the zero-credit U08 V6 source and rebuild accepted-only timeline metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V11.json"
MEDIA = ROOT / "working_assets/e36_autonomous_recovery_20260731/u08_zero_credit_vfx_bridge_v6/E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_BRIDGE_V6.mp4"
QA = ROOT / "qa/e36_agentcut_20260730/E36_U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_DIRECT_QA_V1.json"
PROBE = ROOT / "qa/e36_agentcut_20260730/u08_zero_credit_rotoscope_probe_20260801/E36_U08_V6_FFPROBE.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    if qa.get("status") != "PASS_ACCEPTED_U08_MOTION_30_OF_30":
        raise RuntimeError("U08 QA is not admission-ready")
    row = {
        "source_id": "U08_ZERO_CREDIT_PAPER_CHAOS_TERMINAL_V6",
        "canonical_units": ["U08"],
        "admission": "PASS_ACCEPTED_ONLY_ZERO_CREDIT_SOURCE_NATIVE_RECOMPOSITION",
        "media": str(MEDIA.relative_to(ROOT)),
        "media_sha256": sha256(MEDIA),
        "qa_authority": str(QA.relative_to(ROOT)),
        "qa_sha256": sha256(QA),
        "duration_seconds": 5.0,
        "probe": {
            "streams": [
                {key: stream.get(key) for key in ("codec_name", "codec_type", "width", "height", "r_frame_rate", "sample_rate", "channels")}
                for stream in probe["streams"]
            ],
            "format": {"duration": probe["format"]["duration"]},
        },
    }
    rows = []
    inserted = False
    for existing in data["sources"]:
        rows.append(existing)
        if existing["source_id"] == "U07":
            rows.append(row)
            inserted = True
    if not inserted:
        raise RuntimeError("U07 insertion point missing")
    timeline = 0.0
    for existing in rows:
        duration = float(existing["duration_seconds"])
        existing["accepted_only_timeline_seconds"] = [round(timeline, 6), round(timeline + duration, 6)]
        timeline += duration
    data.update({
        "schema": "qingshan.e36.agentcut_accepted_only_source_map.v11",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-923",
        "source_mailbox_sha256": "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7",
        "status": "PASS_MOTION_30_OF_30_TRANSCRIPT_39_OF_47_AGENTCUT_REBUILD_READY",
        "accepted_source_count": len(rows),
        "accepted_canonical_unit_count": 30,
        "accepted_only_runtime_seconds": round(timeline, 6),
        "sources": rows,
        "unresolved_canonical_units": [],
        "assembly_gate": "PASS",
        "all_admitted_files_and_qa_exist": all((ROOT / item["media"]).is_file() and (ROOT / item["qa_authority"]).is_file() for item in rows),
        "blocked_by": "ACCEPTED_TRANSCRIPT_INCOMPLETE:39/47;PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24",
        "next_action": "Rebuild AgentCut with U08 V6 inserted between U07 and U09, then rerun full-film aHash, cadence, OCR, audiovisual sync, identity, causality, and continuous-watch gates while zero-credit transcript recovery continues."
    })
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT), "sources": len(rows), "units": 30, "runtime": round(timeline, 6)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
