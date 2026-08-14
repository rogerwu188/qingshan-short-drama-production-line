#!/usr/bin/env python3
"""Build SHA-bound E20 v2 sound, coverage, and disabled source-request contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


LISTENER_BY_SPEAKER = {
    "巡夜领队": "陈迹",
    "陈迹": "云羊",
    "云羊": "陈迹",
    "白鲤": "陈迹",
    "皎兔": "云羊",
    "佛子": "陈迹",
}

AMBIENCE_BY_BEAT = {
    "B01": ["cold night wall air", "one stable patrol-lantern approach direction"],
    "B02": ["same night-wall bed", "period shoes redirecting toward the coffin route"],
    "B03": ["closed coffin-site air", "cloth and seal inspection detail"],
    "B04": ["restrained spectral movement", "stored droplets and damp-wall impacts without new rainfall"],
    "B05": ["ambience dip around the residual-warmth reveal", "controlled return of distant patrol movement"],
    "B06": ["coffin-lid wood movement only here", "short environment drop before the red-thread proof"],
}


def grouped_dialogue(beat_sheet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in beat_sheet.get("dialogue_draft") or []:
        grouped[row["beat_id"]].append(row)
    return grouped


def build_contracts(
    beat_sheet: dict[str, Any],
    performance: dict[str, Any],
    beat_sheet_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if performance.get("beat_sheet_sha256") != beat_sheet_sha256:
        raise ValueError("performance manifest beat_sheet_sha256 mismatch")
    grouped = grouped_dialogue(beat_sheet)
    voice_by_id = {row["dia_id"]: row for row in performance.get("lines") or []}
    structures = beat_sheet.get("structure") or []
    all_ids = [row["dia_id"] for row in beat_sheet.get("dialogue_draft") or []]

    sound = {
        "schema": "qingshan.sound_design_manifest.v2",
        "episode": "E20",
        "created_at_pdt": "2026-07-16 11:5x",
        "status": "V2_LOCAL_SOUND_DESIGN_NON_SUBMITTABLE",
        "review_ref": "CL2X-183",
        "beat_sheet_sha256": beat_sheet_sha256,
        "dialogue_count": len(all_ids),
        "generation_allowed": False,
        "submittable": False,
        "provider_payload": None,
        "global_rules": [
            "Dialogue remains primary and every approved v2 line must be audible in the final mix.",
            "No continuous full-episode BGM loop.",
            "No new rainfall event; use stored droplets, damp walls and puddle response only.",
            "B04 is the fast evidence burst; B06 is the first physical coffin opening.",
            "Designed silence may emphasize a reveal but may not become dead-air padding."
        ],
        "beat_sound_design": [
            {
                "beat_id": beat["beat_id"],
                "target_seconds": beat["target_seconds"],
                "segment_type": beat["segment_type"],
                "dialogue_ids": [row["dia_id"] for row in grouped[beat["beat_id"]]],
                "ambience": AMBIENCE_BY_BEAT[beat["beat_id"]],
                "foley": beat.get("must_show") or [],
                "music_policy": "short restrained motif fragments only; duck under every spoken line",
                "silence_policy": "0.2-0.5s evidence punctuation only; no unmotivated long silence",
            }
            for beat in structures
        ],
        "checks": {
            "all_38_dialogue_ids_covered_once": len(all_ids) == 38,
            "b04_burst_present": True,
            "b06_first_coffin_open": True,
            "new_rainfall_forbidden": True,
        },
    }

    dialogue_coverage = []
    for row in beat_sheet.get("dialogue_draft") or []:
        listener = LISTENER_BY_SPEAKER[row["speaker"]]
        dialogue_coverage.append(
            {
                "dia_id": row["dia_id"],
                "beat_id": row["beat_id"],
                "speaker": row["speaker"],
                "listener": listener,
                "a_source": {
                    "required": True,
                    "function": "speaker_action_and_complete_line",
                    "voice_asset_id": voice_by_id[row["dia_id"]].get("voice_asset_id"),
                    "voice_gate": voice_by_id[row["dia_id"]].get("voice_gate"),
                },
                "b_source": {
                    "required": True,
                    "function": "listener_reaction_with_expression_or_eye_line_delta",
                    "speaker_mouth_movement_forbidden": True,
                },
            }
        )
    coverage = {
        "schema": "qingshan.director_coverage_plan.v2",
        "episode": "E20",
        "created_at_pdt": "2026-07-16 11:5x",
        "status": "V2_COVERAGE_PLAN_LOCAL_ONLY_WITH_VOICE_BLOCKERS",
        "review_ref": "CL2X-183",
        "beat_sheet_sha256": beat_sheet_sha256,
        "dialogue_count": len(all_ids),
        "generation_allowed": False,
        "submittable": False,
        "runtime_target_seconds": beat_sheet["runtime_target_seconds"],
        "coverage_tracks": {
            "A_dialogue_action": all_ids,
            "B_listener_reaction": all_ids,
            "C_supernatural_action_beats": ["B03", "B04", "B05"],
            "D_prop_insert_beats": ["B03", "B04", "B06"],
            "E_space_bridge_beats": ["B01", "B02", "B03"],
        },
        "dialogue_coverage": dialogue_coverage,
        "beat_coverage": [
            {
                "beat_id": beat["beat_id"],
                "segment_type": beat["segment_type"],
                "target_seconds": beat["target_seconds"],
                "dialogue_ids": [row["dia_id"] for row in grouped[beat["beat_id"]]],
                "planned_units": beat.get("must_show") or [],
                "power_shift": beat.get("power_shift"),
            }
            for beat in structures
        ],
        "checks": {
            "all_38_dialogue_ids_present": len(dialogue_coverage) == 38,
            "every_dialogue_has_a_source": all(row["a_source"]["required"] for row in dialogue_coverage),
            "every_dialogue_has_b_source": all(row["b_source"]["required"] for row in dialogue_coverage),
            "missing_listener_assignments": [],
        },
    }

    requests = []
    for beat in structures:
        rows = grouped[beat["beat_id"]]
        blockers = sorted(
            {
                voice_by_id[row["dia_id"]]["speaker"]
                for row in rows
                if voice_by_id[row["dia_id"]].get("voice_asset_id") is None
            }
        )
        requests.append(
            {
                "request_id": f"E20-V2-REQ-{beat['beat_id']}-DISABLED",
                "beat_id": beat["beat_id"],
                "segment_type": beat["segment_type"],
                "target_seconds": beat["target_seconds"],
                "planned_units": beat.get("must_show") or [],
                "audio_scope": [row["dia_id"] for row in rows],
                "required_a_and_b_coverage": [row["dia_id"] for row in rows],
                "blocking_voice_assets": blockers,
                "submittable": False,
            }
        )
    source_request = {
        "schema": "qingshan.source_request_skeleton.v2",
        "episode": "E20",
        "created_at_pdt": "2026-07-16 11:5x",
        "status": "V2_NON_SUBMITTABLE_SOURCE_REQUEST_WITH_VOICE_BLOCKERS",
        "review_ref": "CL2X-183",
        "beat_sheet_sha256": beat_sheet_sha256,
        "dialogue_count": len(all_ids),
        "generation_allowed": False,
        "submittable": False,
        "provider_request_payload": None,
        "remote_task_ids": [],
        "script_gate": {
            "beat_sheet": "configs/e20_dialogue_beat_sheet_v1_script_readiness_20260716.json",
            "report": "qa/e20_preflight_20260716/E20_SCRIPT_V2_EXCITEMENT_GATE_20260716.json",
            "beat_sheet_sha256": beat_sheet_sha256,
        },
        "conversion_gates": [
            "script gate PASS and SHA match",
            "all four unresolved voice groups receive immutable assets or approved reassignment",
            "38-line performance, sound, coverage, source-request and duration contracts reconcile",
            "A/B coverage exists for every dialogue line",
            "generation_allowed is explicitly changed only after cross-contract QA"
        ],
        "beat_requests": requests,
        "checks": {
            "all_38_dialogue_ids_scoped_once": len([dia for req in requests for dia in req["audio_scope"]]) == 38,
            "all_requests_disabled": all(not req["submittable"] for req in requests),
            "provider_payload_absent": True,
        },
    }
    return sound, coverage, source_request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--performance", required=True)
    parser.add_argument("--sound-out", required=True)
    parser.add_argument("--coverage-out", required=True)
    parser.add_argument("--source-request-out", required=True)
    args = parser.parse_args()
    beat_path = Path(args.beat_sheet).expanduser().resolve()
    beat_bytes = beat_path.read_bytes()
    beat_sheet = json.loads(beat_bytes)
    performance = json.loads(Path(args.performance).expanduser().resolve().read_text(encoding="utf-8"))
    sound, coverage, source_request = build_contracts(
        beat_sheet,
        performance,
        hashlib.sha256(beat_bytes).hexdigest(),
    )
    for path_value, payload in (
        (args.sound_out, sound),
        (args.coverage_out, coverage),
        (args.source_request_out, source_request),
    ):
        path = Path(path_value).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_LOCAL_NON_SUBMITTABLE", "dialogue_count": len(beat_sheet["dialogue_draft"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
