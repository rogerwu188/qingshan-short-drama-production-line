#!/usr/bin/env python3
"""Fail final-package QA while any declared production blocker is unresolved."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


APPROVAL_REF = re.compile(r"^(?:SC2X|CL2X|ROGER)-[A-Za-z0-9_-]+$")
REQUIRED_RELEASE_BLOCKERS = {
    "DIALOGUE_AUDIO_AUDIBILITY": "scripted dialogue is present and audible in the final audio track",
    "SPEAKER_IDENTITY_AND_VOICE_BINDING": "the canonical face is the visible speaker and uses the canonical voice",
    "SUBTITLE_BURNIN": "burned Chinese subtitle coverage and pixel verification",
    "NALU_MOTION_OUTRO": "Nalu Motion branded outro render verification",
    "AUDIENCE_SCORE_PRE_RELEASE": "evidence-backed simulated-audience PASS with opening and tail hooks intact",
}
NON_WAIVABLE_BLOCKERS = {"AUDIENCE_SCORE_PRE_RELEASE"}


def evaluate(payload: dict) -> dict:
    failures = []
    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        failures.append("blocker_manifest_missing_rows")
        blockers = []
    blocker_ids = {
        str(blocker.get("id") or "").upper()
        for blocker in blockers
        if isinstance(blocker, dict)
    }
    for blocker_id in REQUIRED_RELEASE_BLOCKERS:
        if blocker_id not in blocker_ids:
            failures.append(f"required_final_package_blocker_missing:{blocker_id}")

    for index, blocker in enumerate(blockers, start=1):
        blocker_id = str(blocker.get("id") or f"ROW-{index}")
        status = str(blocker.get("status") or "UNRESOLVED").upper()
        if status == "RESOLVED":
            if blocker_id.upper() in REQUIRED_RELEASE_BLOCKERS:
                evidence = blocker.get("evidence")
                evidence_status = str(blocker.get("evidence_status") or "").upper()
                if not evidence:
                    failures.append(
                        f"required_final_package_evidence_missing:{blocker_id}"
                    )
                if evidence_status != "PASS":
                    failures.append(
                        f"required_final_package_evidence_not_pass:{blocker_id}:{evidence_status or 'MISSING'}"
                    )
            continue
        if blocker_id.upper() in NON_WAIVABLE_BLOCKERS and status == "WAIVED":
            failures.append(f"non_waivable_final_package_blocker:{blocker_id}")
            continue
        if status == "WAIVED" and APPROVAL_REF.fullmatch(str(blocker.get("approval_ref") or "")):
            continue
        failures.append(f"unresolved_final_package_blocker:{blocker_id}:{status}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "blocker_count": len(blockers),
        "required_blocker_ids": sorted(REQUIRED_RELEASE_BLOCKERS),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    manifest = Path(args.manifest).expanduser().resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    result = evaluate(payload)
    result["manifest"] = str(manifest)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
