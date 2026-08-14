#!/usr/bin/env python3
"""Finalize accepted zero-credit E36 U06/U07 local fight fallbacks."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e36_v2_stills_repair_20260729/local_fight_runtime"
OUT = ROOT / "working_assets/e36_v2_stills_20260728/local_fight_fallbacks"
QUEUE = ROOT / "workflow/work_queue.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

U06 = OUT / "E36-CW-U06-LOCAL-ACTION-DETAIL-V6.mp4"
U07 = OUT / "E36-CW-U07-LOCAL-ACTION-DETAIL-V2.mp4"
EXPECTED = {
    U06: "aa8a20da0d61a15a99740d72ef5e793885d52fe0710425fd81a0248c29156961",
    U07: "649774e22ff18fed6ea0c59199cc1837d178482154d01f8938b5396a16b2e903",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe(video: Path, out: Path) -> dict:
    result = subprocess.run([
        str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)
    ], check=True, capture_output=True, text=True)
    raw = json.loads(result.stdout)
    video_stream = next(stream for stream in raw["streams"] if stream.get("codec_type") == "video")
    audio_stream = next(stream for stream in raw["streams"] if stream.get("codec_type") == "audio")
    payload = {
        "schema": "qingshan.local_source_media_probe.v1",
        "status": "PASS",
        "source": rel(video),
        "source_sha256": sha(video),
        "duration_seconds": float(raw["format"]["duration"]),
        "video": {
            "codec": video_stream["codec_name"],
            "width": video_stream["width"],
            "height": video_stream["height"],
            "frame_rate": video_stream["r_frame_rate"],
            "pixel_format": video_stream["pix_fmt"],
        },
        "audio": {
            "codec": audio_stream["codec_name"],
            "sample_rate": int(audio_stream["sample_rate"]),
            "channels": audio_stream["channels"],
        },
    }
    if not (4.95 <= payload["duration_seconds"] <= 5.05):
        raise SystemExit(f"duration failed for {video}")
    if (payload["video"]["width"], payload["video"]["height"]) != (720, 1280):
        raise SystemExit(f"resolution failed for {video}")
    if payload["audio"]["sample_rate"] != 48000 or payload["audio"]["channels"] != 1:
        raise SystemExit(f"audio failed for {video}")
    write(out, payload)
    return payload


for video, expected in EXPECTED.items():
    if not video.exists() or sha(video) != expected:
        raise SystemExit(f"accepted video SHA mismatch: {video}")

u06_cadence = read(QA / "E36_U06_LOCAL_ACTION_DETAIL_FRAME_CADENCE_V6.json")
u07_cadence = read(QA / "E36_U07_LOCAL_ACTION_DETAIL_FRAME_CADENCE_V2.json")
u06_ocr = read(QA / "E36_U06_LOCAL_ACTION_DETAIL_OCR_V7.json")
u07_ocr = read(QA / "E36_U07_LOCAL_ACTION_DETAIL_OCR_V3.json")
for unit, cadence, ocr in (("U06", u06_cadence, u06_ocr), ("U07", u07_cadence, u07_ocr)):
    if cadence.get("status") != "PASS" or ocr.get("status") != "PASS":
        raise SystemExit(f"machine QA failed for {unit}")
    if float(cadence.get("motion_mean", 0)) < 6.0:
        raise SystemExit(f"fight motion floor failed for {unit}")
    if cadence.get("periodic_duplicates", {}).get("periodic_chain_count") != 0:
        raise SystemExit(f"periodic cadence failed for {unit}")
    if ocr.get("critical_text_failures") != 0:
        raise SystemExit(f"critical OCR failed for {unit}")

u06_probe_path = QA / "E36_U06_LOCAL_ACTION_DETAIL_MEDIA_PROBE_V1.json"
u07_probe_path = QA / "E36_U07_LOCAL_ACTION_DETAIL_MEDIA_PROBE_V1.json"
probe(U06, u06_probe_path)
probe(U07, u07_probe_path)

lineage_path = QA / "E36_U06_U07_LOCAL_ACTION_DETAIL_FAILURE_LINEAGE_V1.json"
lineage = {
    "schema": "qingshan.local_fight_fallback_failure_lineage.v1",
    "episode": "E36",
    "status": "PASS_FAILURES_PRESERVED",
    "generation_credits": 0,
    "U06": [
        {"version": "V1", "sha256": "c6a6247b68f6d4ed5eeddc9d07f7c748c73eec11fbaa77d72b3768acd930c0d1", "status": "FAIL_MANUAL_NO_VISIBLE_DEFLECTION_OR_PULL_TERMINAL"},
        {"version": "V2", "sha256": "e9370436755575a0b83217953792aed4129f6b8ee1ac3cf2e399b3659ead3ec1", "status": "FAIL_MANUAL_SYNTHETIC_RECTANGULAR_BLADE_PROP"},
        {"version": "V3", "sha256": "8a2444146f0fed796256d76f5a0d7dfaf2bd65e641445e2cc5b8bc7af58ea2b9", "status": "FAIL_MANUAL_NO_EXPLICIT_COLLAR_GRIP"},
        {"version": "V4", "sha256": "d9112fa71e83d2d5fcf282abb21582215b2c2cd50d4f71490b9b2547db13e831", "status": "FAIL_MANUAL_MESSENGER_REMAP_WITHOUT_EXPLICIT_GRIP"},
        {"version": "V5", "sha256": "c45eaf4d72c7ee823f53afdbac5e26cfa198cc55a8dc39e14a6c05d79a1bd593", "status": "FAIL_MANUAL_U07_PAPER_DECOY_VISIBLE_BEFORE_U07"},
    ],
    "U07": [
        {"version": "V1", "sha256": "0363c3a509fc9d45b6165d521bcfb8df9446c29d502430912d9e7046a22be8c9", "status": "FAIL_MANUAL_REFLECTED_EDGE_DUPLICATES_DURING_FOOT_DETAIL"},
    ],
    "ocr_precheck_failures": [
        "The first U06/U07 OCR reports failed closed because allow/forbid lexicons were omitted; the reports remain preserved and the corrected strict no-text runs use configured sentinel lexicons.",
    ],
}
write(lineage_path, lineage)

manuals = {
    "U06": {
        "video": U06,
        "cadence": u06_cadence,
        "ocr": u06_ocr,
        "contact": QA / "E36_U06_LOCAL_ACTION_DETAIL_CONTACT_SHEET_V6.jpg",
        "checks": {
            "first_frame_motion": "PASS_BLADE_ALREADY_AT_OUTER_ROBE_CONTACT",
            "robe_contact": "PASS_CLOTH_ONLY_SKIN_UNINJURED",
            "counterforce_attachment": "PASS_JIAOTU_ARM_TO_WEAPON_CONTACT_ARC",
            "force_direction": "PASS_ATTACK_LEFT_TO_RIGHT_BLOCK_AND_RECOIL_LEFT_UP",
            "blade_terminal": "PASS_BLADE_CLEARS_MESSENGER_BODY_LINE",
            "collar_contact": "PASS_TIGHT_ACCEPTED_CONTINUATION_DETAIL_FIVE_FINGERS_ON_REAR_COLLAR",
            "pull_direction": "PASS_RIGHT_REAR",
            "terminal_state": "PASS_MESSENGER_UPRIGHT_UNINJURED_BEHIND_JIAOTU",
            "identity_and_period": "PASS_E36_JIAOTU_MESSENGER_EXECUTION_SQUARE",
            "environment_life": "PASS_CROWD_DUST_CLOTH_AND_IMPACT_AUDIO",
            "dialogue": "PASS_NOT_REQUIRED_NONE_GENERATED",
        },
        "limitations": [
            "The block uses a deterministic local shadow-force/weapon prop repair rather than a newly generated performance.",
            "The final collar contact is a tight crop from the accepted immediately following U07 anchor; U07 paper/frost contacts are excluded from the U06 crop.",
        ],
    },
    "U07": {
        "video": U07,
        "cadence": u07_cadence,
        "ocr": u07_ocr,
        "contact": QA / "E36_U07_LOCAL_ACTION_DETAIL_CONTACT_SHEET_V2.jpg",
        "checks": {
            "first_frame_motion": "PASS_DRY_RIME_ALREADY_SPREADING_AT_BOTH_BOOTS",
            "frost_contact": "PASS_ATTACHED_TO_SOLES_AND_PLANK_SEAMS_NO_LIQUID",
            "paper_substitute_action": "PASS_TIPS_DOWN_INTO_EXPOSED_LINE",
            "paper_contact_and_direction": "PASS_UPPER_RIGHT_TO_LOWER_LEFT_DOWN",
            "collar_contact": "PASS_FIVE_FINGERS_VISIBLE_ON_REAR_COLLAR",
            "pull_direction": "PASS_RIGHT_REAR",
            "terminal_state": "PASS_FROZEN_STAKE_PAPER_DOUBLE_AND_SAFE_MESSENGER_READ_TOGETHER",
            "identity_and_period": "PASS_ADULT_MALE_STAKE_JIAOTU_MESSENGER_EXECUTION_PLATFORM",
            "environment_life": "PASS_CROWD_DUST_FROST_GRAIN_AND_IMPACT_AUDIO",
            "dialogue": "PASS_NOT_REQUIRED_NONE_GENERATED",
        },
        "limitations": [
            "This is a four-beat action-detail edit from the sole accepted U07 anchor, not a continuous newly generated body performance.",
            "Admission rests on motivated causal details and the final complete tableau, not camera motion alone.",
        ],
    },
}

manual_paths = {}
for unit, item in manuals.items():
    path = QA / f"E36_{unit}_LOCAL_ACTION_DETAIL_MANUAL_QA_V1.json"
    payload = {
        "schema": "qingshan.manual_source_video_qa.v1",
        "episode": "E36",
        "unit_id": unit,
        "status": f"PASS_ACCEPTED_{unit}_LOCAL_FALLBACK_ONLY",
        "accepted_video": rel(item["video"]),
        "accepted_video_sha256": sha(item["video"]),
        "generation_credits": 0,
        "review_evidence": {
            "contact_sheet_2fps": rel(item["contact"]),
            "contact_sheet_sha256": sha(item["contact"]),
            "direct_temporal_contact_review": "PASS",
        },
        "fight_motion_floor_v2_1": {
            "status": "PASS",
            "motion_mean": item["cadence"]["motion_mean"],
            "required_motion_mean_min": 6.0,
            "action_detail_beats": 4,
            "average_shot_length_seconds": 1.25,
            "required_average_shot_length_max": 2.2,
            "burst_count": 4,
            "required_burst_count_min": 3,
            "freeze_runs": item["cadence"].get("frozen_runs", []),
            "periodic_chain_count": item["cadence"]["periodic_duplicates"]["periodic_chain_count"],
        },
        "checks": item["checks"],
        "ocr": {
            "status": item["ocr"]["status"],
            "critical_text_failures": item["ocr"]["critical_text_failures"],
            "recognitions": item["ocr"]["recognitions"],
        },
        "limitations_not_greenwash": item["limitations"],
    }
    write(path, payload)
    manual_paths[unit] = path

cap_path = ROOT / "qa/e36_v2_stills_repair_20260729/E36_CAP_STATE_5863_AFTER_LOCAL_FIGHTS_V12.json"
cap = {
    "schema": "qingshan.episode_cap_state.v1",
    "episode": "E36",
    "status": "PASS_ALL_SOURCE_UNITS_ACCEPTED_AGENTCUT_PREPRODUCTION_PENDING",
    "actual_credits": 5863,
    "actual_breakdown": {"image": 561, "video": 5292, "audio": 10},
    "budget_cap": 6000,
    "headroom": 137,
    "approval_required": False,
    "unknown_success_credits": 0,
    "active_remote_tasks": 0,
    "zero_credit_fallbacks": {
        "U06": {"status": "PASS", "video": rel(U06), "sha256": sha(U06)},
        "U07": {"status": "PASS", "video": rel(U07), "sha256": sha(U07)},
        "U17": {"status": "PASS", "video": "working_assets/e36_v2_stills_20260728/u17_local_fallback/E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V3.mp4", "sha256": "a72b589b77b85e07e399de7636cd0b19df766bfd5f302b020d80eecf8d6cf6cc"},
    },
    "release_gate": "All canonical source units are now available, but AgentCut assembly, full-cut QA and Roger human release review remain mandatory before release.",
    "blocked_by": None,
    "next_action": "Compile the E36 AgentCut source map from accepted-only assets, assemble the full episode locally, then run full-cut cadence, OCR, dialogue coverage, identity/period continuity and human watch QA.",
}
write(cap_path, cap)

queue = read(QUEUE)
now = datetime.now().astimezone().isoformat(timespec="seconds")
summary = "U06 local V1-V5 and U07 V1 manual failures are preserved. U06 V6 and U07 V2 pass the fight motion floor, cadence, strict no-text OCR, media and direct causal-contact review at zero new credits. U17 V3 was already accepted. All E36 source units are now available at5863/6000; AgentCut preproduction and full-cut QA remain. E37 stays closed."
queue["updated_at"] = now
queue["updated_note_latest"] = summary
queue["status"] = "E36_PRODUCTION_ACTIVE_AGENTCUT_PREPRODUCTION_CAP_5863"
queue["real_active_handle_count"] = 0
e36 = queue["lines"]["E36"]
e36["status"] = "ACTIVE_CAP_5863_U06_U07_U17_LOCAL_ACCEPTED_AGENTCUT_PREPRODUCTION"
e36["current_phase"] = summary
e36["blocked_by"] = None
e36["running_or_pending_task_ids"] = []
e36["latest_u06_evidence"] = f"Zero-credit U06 V1-V5 manual failures preserved. V6 accepted sha{sha(U06)[:10]} with exact robe contact, attached counterforce, blade clear terminal and tight accepted continuation collar grip; motion{u06_cadence['motion_mean']:.3f}, cadence/OCR/manual PASS."
e36["latest_u07_evidence"] = f"Zero-credit U07 V1 reflected-edge FAIL preserved. V2 accepted sha{sha(U07)[:10]} with dry-rime boot lock, paper substitute fall, five-finger collar pull and complete terminal tableau; motion{u07_cadence['motion_mean']:.3f}, cadence/OCR/manual PASS."
e36["next_action"] = "Compile an accepted-only E36 AgentCut source map and assemble the full episode locally. Run full-cut cadence, OCR, exact dialogue coverage, identity/age/period continuity, transition and human watch QA before any release. Keep E37 closed."
write(QUEUE, queue)

print(json.dumps({
    "status": cap["status"],
    "accepted": {"U06": sha(U06), "U07": sha(U07)},
    "actual_credits": 5863,
    "manual_qa": {unit: rel(path) for unit, path in manual_paths.items()},
    "next_action": cap["next_action"],
}, ensure_ascii=False))
