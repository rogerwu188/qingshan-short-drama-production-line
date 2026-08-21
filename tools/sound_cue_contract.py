#!/usr/bin/env python3
"""Validate ambience, foley and SFX source/cause contracts.

The validator extends the registered FINAL-AUDIO-BED-CONTINUITY evidence
chain; it deliberately does not invent a new gate id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.audio_postproduction_contract import ROOT, validate_audio_profile
except ModuleNotFoundError:  # Direct execution from tools/.
    from audio_postproduction_contract import ROOT, validate_audio_profile  # type: ignore


LAYERS = {"AMBIENCE", "FOLEY", "SFX"}


def _resolve(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate(project: dict, *, root: Path = ROOT) -> dict:
    failures = validate_audio_profile(project)
    metadata = project.get("metadata") or {}
    contract = metadata.get("sound_design_contract") or {}
    mode = str(contract.get("mode") or "")
    required_layers = {str(value).upper() for value in contract.get("required_layers") or []}
    if not required_layers:
        failures.append("SOUND_REQUIRED_LAYERS_MISSING")
    unknown_layers = sorted(required_layers - (LAYERS | {"DIALOGUE"}))
    if unknown_layers:
        failures.append(f"SOUND_REQUIRED_LAYERS_UNKNOWN:{','.join(unknown_layers)}")

    evidence_rows: list[dict] = []
    if mode == "NATIVE_EMBEDDED":
        source_track_ids = {str(value) for value in contract.get("source_track_ids") or []}
        tracks = project.get("timeline", {}).get("audioTracks", [])
        actual_ids = {str(track.get("id") or "") for track in tracks}
        if not source_track_ids:
            failures.append("NATIVE_SOUND_SOURCE_TRACK_IDS_MISSING")
        if not source_track_ids.issubset(actual_ids):
            failures.append("NATIVE_SOUND_SOURCE_TRACK_MISSING")
        for track in tracks:
            if str(track.get("id") or "") not in source_track_ids:
                continue
            for clip in track.get("clips") or []:
                source = _resolve(str(clip.get("source") or ""), root)
                source_id = str((clip.get("metadata") or {}).get("source_id") or "")
                if not source_id:
                    failures.append("NATIVE_SOUND_CLIP_SOURCE_ID_MISSING")
                if not source.is_file() or source.stat().st_size == 0:
                    failures.append(f"NATIVE_SOUND_SOURCE_MISSING:{source_id or clip.get('id')}")
                evidence_rows.append({"source_id": source_id, "source": str(source), "mode": mode})
    elif mode == "LAYERED_CUES":
        cues = contract.get("cues") or []
        seen: set[str] = set()
        covered: set[str] = set()
        if not cues:
            failures.append("SOUND_CUES_MISSING")
        for index, cue in enumerate(cues, start=1):
            cue_id = str(cue.get("cue_id") or "")
            label = cue_id or f"ROW-{index}"
            if not cue_id:
                failures.append(f"SOUND_CUE_ID_MISSING:{label}")
            elif cue_id in seen:
                failures.append(f"SOUND_CUE_ID_DUPLICATE:{cue_id}")
            seen.add(cue_id)
            layer = str(cue.get("layer") or "").upper()
            if layer not in LAYERS:
                failures.append(f"SOUND_CUE_LAYER_INVALID:{label}")
            else:
                covered.add(layer)
            if not str(cue.get("visual_cause") or cue.get("subjective_intent") or "").strip():
                failures.append(f"SOUND_CUE_CAUSE_MISSING:{label}")
            for field in ("timeline_start", "duration", "gain_db"):
                value = cue.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    failures.append(f"SOUND_CUE_{field.upper()}_INVALID:{label}")
            if isinstance(cue.get("duration"), (int, float)) and cue.get("duration") <= 0:
                failures.append(f"SOUND_CUE_DURATION_NONPOSITIVE:{label}")
            if not str(cue.get("scene_id") or "").strip() or not str(cue.get("room_id") or "").strip():
                failures.append(f"SOUND_CUE_SPACE_BINDING_MISSING:{label}")
            if not str(cue.get("rights_evidence") or "").strip():
                failures.append(f"SOUND_CUE_RIGHTS_EVIDENCE_MISSING:{label}")
            source = _resolve(str(cue.get("source") or ""), root)
            if not source.is_file() or source.stat().st_size == 0:
                failures.append(f"SOUND_CUE_SOURCE_MISSING:{label}")
            elif str(cue.get("source_sha256") or "").lower() != _sha256(source):
                failures.append(f"SOUND_CUE_SOURCE_SHA_MISMATCH:{label}")
            evidence_rows.append({"cue_id": cue_id, "layer": layer, "source": str(source), "mode": mode})
        missing_layers = sorted((required_layers & LAYERS) - covered)
        omissions = contract.get("layer_omissions") or {}
        for layer in missing_layers:
            if len(str(omissions.get(layer) or "").strip()) < 12:
                failures.append(f"SOUND_REQUIRED_LAYER_UNCOVERED:{layer}")
    else:
        failures.append("SOUND_DESIGN_MODE_INVALID")

    return {
        "schema": "qingshan.sound_cue_contract_report.v1",
        "status": "PASS" if not failures else "FAIL",
        "mode": mode,
        "required_layers": sorted(required_layers),
        "evidence_count": len(evidence_rows),
        "evidence": evidence_rows,
        "failures": failures,
        "registered_gate_id": "FINAL-AUDIO-BED-CONTINUITY"
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    project_path = Path(args.project).expanduser().resolve()
    report = evaluate(
        json.loads(project_path.read_text(encoding="utf-8")),
        root=Path(args.root).expanduser().resolve(),
    )
    output = Path(args.out).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
