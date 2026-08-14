#!/usr/bin/env python3
"""Validate machine evidence that the canonical face spoke with the canonical voice."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.multimodal_character_binding_guard import ROOT, _character_authority, _voice_authority


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _absolute(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def evaluate(payload: dict) -> dict:
    failures: list[str] = []
    rows = payload.get("dialogue_evidence") or []
    required_ids = {str(value) for value in payload.get("required_dialogue_ids") or []}
    actual_ids = {str(row.get("dia_id") or "") for row in rows}
    if not required_ids:
        failures.append("required_dialogue_ids_missing")
    if required_ids != actual_ids:
        failures.append("dialogue_evidence_coverage_mismatch")

    characters = _character_authority()
    voices = _voice_authority()
    for row in rows:
        dia_id = str(row.get("dia_id") or "MISSING")
        entity_id = str(row.get("entity_id") or "")
        if row.get("visible_speaker_verification") != "PASS":
            failures.append(f"visible_speaker_not_pass:{dia_id}")
        if row.get("canonical_face_verification") != "PASS":
            failures.append(f"canonical_face_not_pass:{dia_id}")
        if row.get("canonical_voice_verification") != "PASS":
            failures.append(f"canonical_voice_not_pass:{dia_id}")
        if not row.get("machine_verifier") or not isinstance(row.get("confidence"), (int, float)):
            failures.append(f"machine_verifier_evidence_missing:{dia_id}")

        frame_path = _absolute(str(row.get("speaking_frame") or ""))
        ref_path = _absolute(str(row.get("canonical_face_reference") or ""))
        if not frame_path.is_file() or _sha(frame_path) != row.get("speaking_frame_sha256"):
            failures.append(f"speaking_frame_sha_mismatch:{dia_id}")
        canonical = characters.get(entity_id) or {}
        expected_ref = str(canonical.get("identity_reference_image") or canonical.get("reference_image") or "")
        if not expected_ref or ref_path.resolve() != _absolute(expected_ref).resolve():
            failures.append(f"canonical_face_reference_mismatch:{dia_id}")
        elif _sha(ref_path) != row.get("canonical_face_reference_sha256"):
            failures.append(f"canonical_face_reference_sha_mismatch:{dia_id}")

        expected_voice = (voices.get(entity_id) or {}).get("remote_asset_id")
        if not expected_voice or row.get("canonical_voice_asset_id") != expected_voice:
            failures.append(f"canonical_voice_asset_mismatch:{dia_id}")

    return {
        "schema": "qingshan.speaker_identity_voice_release_gate.v1",
        "episode": payload.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "required_dialogue_count": len(required_ids),
        "evidence_count": len(rows),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(_absolute(args.evidence).read_text(encoding="utf-8")))
    out = _absolute(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
