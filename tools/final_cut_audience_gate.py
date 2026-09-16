#!/usr/bin/env python3
"""final_cut_audience_gate.py — registered gate FINAL-CUT-AUDIENCE-DETECTORS (seq=19, E04 review).

Consumes the report written by tools/final_cut_audience_detectors.py for the final cut and turns
it into the registry's gate verdict.  It never re-measures: the detector report (sha-bound to
the media) is the evidence; this wrapper only decides and lists what was NOT verified so that a
release audit can see it.  A missing report is a FAIL (not N/A); a report whose media sha no
longer matches --video is a FAIL (stale evidence).

Verdict  PASS  every detector PASS (NOT_IMPLEMENTED/UNVERIFIED are listed, never hidden)
         FAIL  any detector FAIL, report missing, or stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

GATE_ID = "FINAL-CUT-AUDIENCE-DETECTORS"
REPORT_SCHEMA = "qingshan.final_cut_audience_detectors.v1"
HUMAN_REVIEW_DETECTORS = ("state_machine", "count_consistency", "creature_locomotion")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate(report: dict[str, Any] | None, *, video_sha256: str | None = None) -> dict[str, Any]:
    failures: list[str] = []
    unverified: list[str] = []
    if not report:
        return {"gate_id": GATE_ID, "status": "FAIL", "failures": ["AUDIENCE_DETECTOR_REPORT_MISSING"],
                "unverified": [], "detectors": {}}
    if report.get("schema") != REPORT_SCHEMA:
        failures.append(f"AUDIENCE_DETECTOR_REPORT_SCHEMA:{report.get('schema')}")
    if video_sha256 and report.get("media_sha256") and report["media_sha256"] != video_sha256:
        failures.append("AUDIENCE_DETECTOR_REPORT_STALE_MEDIA_SHA")
    detectors = report.get("detectors") or {}
    for name, row in detectors.items():
        status = str((row or {}).get("status") or "MISSING")
        if status == "FAIL":
            evidence = (row or {}).get("evidence") or {}
            codes = (row or {}).get("failures") or (evidence.get("failures") if isinstance(evidence, dict) else None)
            failures.append(f"{name}:FAIL" + (":" + ",".join(str(c) for c in codes[:6]) if codes else ""))
        elif status in ("NOT_IMPLEMENTED", "UNVERIFIED"):
            unverified.append(f"{name}:{status}:{(row or {}).get('reason') or ''}".rstrip(":"))
        elif status != "PASS":
            failures.append(f"{name}:{status}")
    for name in HUMAN_REVIEW_DETECTORS:
        if name not in detectors:
            unverified.append(f"{name}:NOT_IMPLEMENTED:not in report")
    return {"gate_id": GATE_ID, "status": "FAIL" if failures else "PASS", "failures": failures,
            "unverified": unverified, "detectors": {k: (v or {}).get("status") for k, v in detectors.items()},
            "report_overall": report.get("status")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", type=Path, required=True, help="final_cut_audience_detectors.py output")
    ap.add_argument("--video", type=Path, help="final cut; when given the report's media sha must match")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    report = None
    if args.report.is_file():
        try:
            report = json.loads(args.report.read_text(encoding="utf-8"))
        except ValueError:
            report = None
    sha = sha256_file(args.video) if args.video and args.video.is_file() else None
    result = evaluate(report, video_sha256=sha)
    result["report_path"] = str(args.report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
