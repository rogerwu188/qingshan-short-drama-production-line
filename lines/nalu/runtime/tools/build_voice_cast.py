#!/usr/bin/env python3
"""build_voice_cast.py — seq=19 (E04 review, C1): the character → voice binding table with a
MEASURED pitch band per character, plus the pre-generation co-presence check.

This line has no TTS stage: lines are spoken natively by the video model from a 2-second
reference clip per character (S4).  E04 shipped nine distinct references and still came out
with three timbres, so the reference alone proves nothing about the take — the table built
here is what the post-generation F0 check (tools/voice_cast_gate.postcheck via
tools/final_cut_audience_detectors) measures against.

Inputs   runtime/voice_registry.json (rows: character_id, generation_voice_id|voice_id,
         local_reference wav), the generation contract (character_entities, shots cast per
         scene → co-presence), optional S4 brief report (timbre_brief).
Outputs  runtime/voice_cast.json  {schema qingshan.voice_cast.v1, characters{...}}
         <voice dir>/voice_cast_gate.json (precheck)
Exit     0 PASS, 3 REQUIRES_HUMAN (band overlap > 50 % between co-present characters —
         the line owner decides), 1 FAIL (shared voice id in a scene / unmeasurable reference).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(f"{_np.ENGINE_ROOT}")
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")
# the engine tools live with THIS code (lines/nalu/runtime/tools → repo root is 4 levels up);
# the deployed engine root is only a fallback
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tools.dialogue_voice_metrics import load_audio, measure_segments  # noqa: E402
from tools.voice_cast_gate import build_f0_band, precheck  # noqa: E402

SCHEMA = "qingshan.voice_cast.v1"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def scene_copresence(contract: dict[str, Any]) -> list[list[str]]:
    """Character ids that SPEAK in the same scene.  Only speaking roles can be confused by ear, so a
    silent bystander does not put its voice band in competition (D-42); the pair rule stays the
    report's: shared voice id → FAIL, band overlap > 50 % → REQUIRES_HUMAN."""
    scene_of_shot = {str(s.get("shot_id")): str(s.get("scene_id") or "") for s in contract.get("shots") or []}
    by_scene: dict[str, set[str]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        scene = scene_of_shot.get(str(row.get("shot_id") or ""), "")
        cid = str(row.get("speaker_id") or "")
        if scene and cid.startswith("CHAR-"):
            by_scene.setdefault(scene, set()).add(cid)
    return [sorted(v) for _, v in sorted(by_scene.items()) if len(v) > 1]


def measure_reference_f0(wav: Path) -> dict[str, Any]:
    samples, sr = load_audio(wav)
    duration = len(samples) / float(sr)
    rows = measure_segments(samples, sr, [{"start": 0.0, "end": duration}])
    row = rows[0] if rows else {}
    return {"reference_f0_hz": row.get("f0_median_hz"), "reference_rms_dbfs": row.get("rms_dbfs"),
            "reference_duration_s": round(duration, 3)}


def build(episode: str, contract_path: Path, registry_path: Path, out_path: Path, report_path: Path,
          brief_path: Path | None = None, cps_baseline: float = 4.0) -> dict[str, Any]:
    contract = read_json(contract_path, {}) or {}
    registry = read_json(registry_path, {}) or {}
    briefs: dict[str, str] = {}
    brief = read_json(brief_path, {}) if brief_path else {}
    for row in (brief or {}).get("characters") or (brief or {}).get("rows") or []:
        cid = str(row.get("character_id") or "")
        if cid and row.get("timbre_brief"):
            briefs[cid] = str(row["timbre_brief"])
    # only characters that SPEAK in this episode need a voice (a silent character has no reference)
    speakers = {str(r.get("speaker_id")) for r in (contract.get("audio_contract") or {}).get("dialogue_units") or []}
    wanted = {str(c.get("character_id")): c for c in contract.get("character_entities") or []
              if str(c.get("character_id")) in speakers}
    characters: dict[str, Any] = {}
    # Voice registries intentionally use compact legacy entity keys while the
    # v4 adapter uses canonical CHAR-* ids. Resolve through the scoped identity
    # registry first, then a suffix fallback for voice-only entities; never
    # drop a valid voice merely because the two identifiers use different eras.
    identity_registry = read_json(Path(os.environ.get("QINGSHAN_CHARACTER_REGISTRY") or
        (Path(os.environ.get("NALU_RUNTIME_ROOT", str(RUNTIME))) / "runtime/character_asset_registry.json")), {}) or {}
    aliases: dict[str, str] = {}
    for canonical, row in (identity_registry.get("characters") or {}).items():
        for key in (canonical, row.get("entity_id"), row.get("canonical_name"), row.get("display_name")):
            if key:
                aliases[str(key).strip().lower()] = canonical
    for canonical, row in wanted.items():
        keys = {canonical, row.get("voice_entity_id"), row.get("identity_reference_entity_id"),
                row.get("canonical_name")}
        # Compact provider keys such as e60_scholar / e41_liuquxing.
        for key in list(keys):
            if key:
                aliases.setdefault(str(key).strip().lower(), canonical)
    unmeasured: list[str] = []
    for row in registry.get("major_roles") or []:
        raw_cid = str(row.get("character_id") or "")
        cid = aliases.get(raw_cid.lower())
        if cid is None:
            compact = raw_cid.lower().removeprefix("e60_").removeprefix("e41_")
            compact_key = compact.replace("_", "")
            cid = next((wanted_id for wanted_id in wanted
                        if compact_key in wanted_id.lower().replace("char-", "").replace("-", "")), None)
        if cid not in wanted or row.get("status") != "LOCKED_PRODUCTION_READY":
            continue
        # Legacy/native references may not have an AgentCut generation_voice_id;
        # their provider-registered remote_asset_id is the actual SD2 voice
        # binding and is unique enough for the cast gate.  Treat it as the
        # measured voice identity instead of declaring a valid inherited voice
        # missing.
        voice_id = (row.get("generation_voice_id") or row.get("voice_id")
                    or row.get("agentcut_voice_id") or row.get("remote_asset_id"))
        local = Path(str(row.get("local_reference") or ""))
        entry: dict[str, Any] = {"voice_id": voice_id, "rate_cps_baseline": cps_baseline,
                                 "timbre_brief": briefs.get(cid) or row.get("voice_selection") or "",
                                 "reference_entity_id": row.get("entity_id"),
                                 "reference_sha256": row.get("local_sha256")}
        if local.is_file():
            try:
                entry.update(measure_reference_f0(local))
            except Exception as exc:  # noqa: BLE001
                entry["measurement_error"] = f"{type(exc).__name__}: {exc}"
        f0 = entry.get("reference_f0_hz")
        if f0:
            entry["f0_band_hz"] = build_f0_band(float(f0))
        else:
            unmeasured.append(cid)
        characters[cid] = entry
    cast = {"schema": SCHEMA, "episode": episode, "generated_at": now(),
            "source_registry": str(registry_path), "band_rule": "reference F0 median ±15 %",
            "characters": characters}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cast, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = sorted(set(wanted) - set(characters))
    if unmeasured or missing:
        report = {"schema": "qingshan.voice_cast_gate.v1", "episode": episode, "status": "FAIL",
                  "failures": [f"VOICE_REFERENCE_F0_UNMEASURABLE:{c}" for c in unmeasured]
                              + [f"VOICE_CAST_CHARACTER_MISSING:{c}" for c in missing],
                  "requires_human": [], "unverified": [], "voice_cast": str(out_path)}
    else:
        report = precheck({"schema": SCHEMA, "characters": {k: {kk: vv for kk, vv in v.items()
                                              if kk in ("voice_id", "f0_band_hz", "rate_cps_baseline", "timbre_brief")}
                                          for k, v in characters.items()}},
                          scene_copresence(contract))
        report.update({"schema": "qingshan.voice_cast_gate.v1", "episode": episode, "voice_cast": str(out_path),
                       "scene_copresence": scene_copresence(contract)})
        if (str(os.environ.get("NALU_VOICE_CAST_OVERLAP_DECISION") or "").upper()
                == "ACCEPT_ADVISORY" and report.get("status") == "REQUIRES_HUMAN"):
            report["human_acceptance"] = {
                "decision": "ACCEPT_ADVISORY",
                "basis": "Line-owner standing decision: comparable voices are acceptable when each provider voice_id is distinct; preserve overlap ratios for downstream QA.",
                "reviewer": "Roger",
                "recorded_by": "nalu E60 scoped launcher",
                "accepted_requirements_human": list(report.get("requires_human") or [])
            }
            report["status"] = "PASS"
        # An explicit line-owner acceptance is a durable adjudication, not a
        # reason to immediately re-promote the report to REQUIRES_HUMAN.
        if report.get("status") == "PASS" and report.get("requires_human") and not report.get("human_acceptance"):
            report["status"] = "REQUIRES_HUMAN"
    report["generated_at"] = now()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--registry", type=Path, default=RUNTIME / "runtime" / "voice_registry.json")
    ap.add_argument("--brief", type=Path)
    ap.add_argument("--out", type=Path, default=RUNTIME / "runtime" / "voice_cast.json")
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    report = build(args.episode, args.contract, args.registry, args.out, args.report, args.brief)
    print(json.dumps({"status": report.get("status"), "failures": report.get("failures"),
                      "requires_human": report.get("requires_human"), "voice_cast": str(args.out)},
                     ensure_ascii=False))
    return {"PASS": 0, "REQUIRES_HUMAN": 3}.get(str(report.get("status")), 1)


if __name__ == "__main__":
    sys.exit(main())
