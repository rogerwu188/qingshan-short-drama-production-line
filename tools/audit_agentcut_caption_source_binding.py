#!/usr/bin/env python3
"""Verify burned-caption timing against source-native dialogue evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.002)
    args = parser.parse_args()

    root = args.root.resolve()
    project = json.loads(args.project.read_text(encoding="utf-8"))
    alignment = json.loads(args.alignment.read_text(encoding="utf-8"))
    subtitles = {
        row["dialogue_id"]: row
        for track in project["timeline"]["subtitleTracks"]
        for row in track["clips"]
    }
    audio_rows = [
        row
        for track in project["timeline"]["audioTracks"]
        for row in track["clips"]
    ]
    audio = {
        str(row.get("metadata", {}).get("source_id") or row["id"]): row
        for row in audio_rows
    }

    failures: list[dict] = []
    rows: list[dict] = []
    seen: set[str] = set()
    if alignment.get("status") != "PASS":
        failures.append({"type": "SOURCE_ALIGNMENT_NOT_PASS"})

    for unit in alignment.get("units", []):
        source_id = str(unit["source_id"])
        clip = audio.get(source_id)
        if clip is None:
            failures.append({"type": "AUDIO_SOURCE_BINDING_MISSING", "source_id": source_id})
            continue
        timeline_start = float(unit["timeline_start"])
        if abs(float(clip["start"]) - timeline_start) > args.tolerance:
            failures.append({"type": "AUDIO_TIMELINE_START_MISMATCH", "source_id": source_id})
        expected_ids = set(clip.get("metadata", {}).get("expected_dialogue_ids", []))
        for item in unit.get("alignments", []):
            dialogue_id = str(item["dialogue_id"])
            seen.add(dialogue_id)
            caption = subtitles.get(dialogue_id)
            expected_start = timeline_start + float(item["source_start"])
            expected_end = timeline_start + float(item["source_end"])
            evidence_status = "ASR_DIRECT"
            evidence_path = item.get("targeted_evidence")
            if evidence_path:
                evidence = (root / evidence_path).resolve()
                if not evidence.is_file():
                    evidence_status = "MISSING"
                else:
                    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
                    evidence_status = str(evidence_payload.get("status") or "")
                if not evidence_status.startswith("PASS"):
                    failures.append({"type": "TARGETED_EVIDENCE_NOT_PASS", "dialogue_id": dialogue_id})
            item_failures: list[str] = []
            if caption is None:
                item_failures.append("CAPTION_MISSING")
            else:
                actual_start = float(caption["start"])
                actual_end = actual_start + float(caption["duration"])
                if abs(actual_start - expected_start) > args.tolerance:
                    item_failures.append("CAPTION_START_NOT_SOURCE_BOUND")
                if abs(actual_end - expected_end) > args.tolerance:
                    item_failures.append("CAPTION_END_NOT_SOURCE_BOUND")
                if caption.get("text") != item.get("expected"):
                    item_failures.append("CAPTION_TEXT_NOT_CANONICAL_EXPECTED")
            if dialogue_id not in expected_ids:
                item_failures.append("AUDIO_EXPECTED_DIALOGUE_BINDING_MISSING")
            if item_failures:
                failures.append({"type": "DIALOGUE_BINDING_FAIL", "dialogue_id": dialogue_id, "failures": item_failures})
            rows.append(
                {
                    "dialogue_id": dialogue_id,
                    "source_id": source_id,
                    "expected_timeline_start": round(expected_start, 6),
                    "expected_timeline_end": round(expected_end, 6),
                    "alignment_method": item.get("alignment_method"),
                    "lexical_recall": item.get("lexical_recall"),
                    "targeted_evidence_status": evidence_status,
                    "status": "PASS" if not item_failures else "FAIL",
                }
            )

    missing = sorted(set(subtitles) - seen)
    if missing:
        failures.append({"type": "CAPTIONS_WITHOUT_SOURCE_ALIGNMENT", "dialogue_ids": missing})
    report = {
        "schema": "qingshan.agentcut.caption_source_binding_audit.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failures else "FAIL",
        "project": str(args.project.resolve()),
        "project_sha256": sha256(args.project),
        "source_alignment": str(args.alignment.resolve()),
        "source_alignment_sha256": sha256(args.alignment),
        "caption_count": len(subtitles),
        "verified_caption_count": len(rows),
        "tolerance_seconds": args.tolerance,
        "failures": failures,
        "rows": rows,
        "interpretation": "Source-local native-ASR timing transformed through each admitted audio clip is authoritative for caption binding; coarse full-cut ASR segment timestamps remain a separate diagnostic.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "verified": len(rows), "failures": len(failures)}))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
