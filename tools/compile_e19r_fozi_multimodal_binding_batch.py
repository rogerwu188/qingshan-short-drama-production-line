#!/usr/bin/env python3
"""Compile the registered Fozi voice into 15 guarded E19R multimodal tasks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "configs/e19r_audio_binding_work_queue_v1_not_final_20260717.json"
REGISTRY = ROOT / "configs/e19r_fozi_voice_asset_registry_v1_20260717.json"
OUT = ROOT / "configs/e19r_fozi_multimodal_binding_contracts_r1_not_final_20260717.json"
MANIFEST = ROOT / "configs/e19r_fozi_multimodal_binding_giggle_manifest_r1_not_final_20260717.json"
QA = ROOT / "qa/e19r_fozi_multimodal_binding_r1_20260717/E19R_FOZI_MULTIMODAL_BINDING_CONTRACTS_R1_QA.json"
GUARD = ROOT / "qa/e19r_fozi_multimodal_binding_r1_20260717/E19R_FOZI_MULTIMODAL_BINDING_VISUAL_TEXT_GUARD_R1.json"
PROMPT_DIR = ROOT / "workflow/prompts/e19r_fozi_multimodal_binding_r1_20260717"

READY_STATE = "READY_FOR_MULTIMODAL_AUDIO_BINDING_NOT_STANDALONE_TTS"
FOZI_REF = "assets/reference/e20_20260716/characters/CHAR-fozi-luozhuisajia-e19-continuity-v1-20260716.jpg"
VOICE_KEY = "VOICE-佛子-罗追萨迦"

SCENES = {
    "B01": "the rain-dark medicine courtyard below a low tiled wall before dawn",
    "B02": "the narrow service lane beside the medicine courtyard under one period lantern",
    "B03": "the wet moonlit alley where the mind-thief confrontation is underway",
    "B04": "the same wet alley during the restrained verbal counterattack",
    "B05": "the wall-foot escape beat beside the medicine courtyard",
    "B06": "the dark side-door route while distant patrol lanterns approach",
}

ACTIONS = (
    "raises one empty palm at waist height and lowers it after the line",
    "turns his eyes toward the listener, takes one grounded half-step, and settles",
    "briefly presses two fingers against his own sleeve before releasing them",
    "shifts his weight off the wet wall and steadies both feet",
    "indicates the safe route once with a low hand cue and returns the hand below the waist",
)

PERFORMANCES = {
    "B01": "young restrained male monk; dry physical comedy without clowning; complete the line cleanly",
    "B02": "young restrained male monk; observant and lightly ironic; natural pace, no sermon cadence",
    "B03": "young restrained male monk; precise psychological pressure; quiet confidence, no shouting",
    "B04": "young restrained male monk; self-aware vulnerability under control; preserve every clause",
    "B05": "young restrained male monk; awkward physical urgency with dignity; no exaggerated comedy",
    "B06": "young restrained male monk; low urgent warning; complete the sentence before the cut",
}

NEGATIVE = (
    "wrong face, identity drift, duplicate person, extra fingers, broken wrist, visible modern object, "
    "modern clothing, modern signage, logo, readable generated Chinese, English letters, Latin letters, "
    "subtitles, captions, on-screen text, text overlay, watermark, caption bar, letterbox text, 字幕, 文字, "
    "标题条, speech bubble, lower third, static puppet, static talking head, frozen pose, repeated movement, "
    "slow motion, dreamy pace, floating, weightless motion, rubber physics, standalone narration, "
    "off-character voice, old preacher voice, sermon cadence, sentence truncation"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    queue = load(QUEUE)
    registry = load(REGISTRY)
    asset = registry["assets"][VOICE_KEY]
    voice_asset_id = asset["remote_asset_id"]
    lines = [
        row for row in queue["lines"]
        if row["speaker"] == "佛子" and row["state"] == READY_STATE
    ]
    failures: list[str] = []
    if not asset.get("production_ready") or asset.get("qa_status") != "PASS":
        failures.append("fozi_voice_registry_not_production_ready")
    if len(lines) != 15:
        failures.append(f"fozi_ready_count:{len(lines)}!=15")
    if not (ROOT / FOZI_REF).is_file():
        failures.append("fozi_reference_missing")

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    QA.parent.mkdir(parents=True, exist_ok=True)
    contracts: list[dict] = []
    guard_rows: list[dict] = []
    for index, line in enumerate(lines):
        dia_id = line["dialogue_id"]
        scene = SCENES[line["beat_id"]]
        visual = (
            f"Vertical 9:16 cinematic period realism in {scene}. Match the supplied Fozi continuity reference exactly: "
            "young bald monk, clean white robe, precise calm eyes, physically grounded posture. Medium close narrative shot. "
            f"Fozi {ACTIONS[index % len(ACTIONS)]}, delivers one complete line with subtle natural mouth movement, then holds a restrained reaction. "
            "Native real-time motion with a clear beginning, change, and finish; cold rain-blue ambience with one warm period lantern."
        )
        if line["text"].replace(" ", "") in visual.replace(" ", ""):
            failures.append(f"dialogue_leak_in_visual:{dia_id}")
        audio = {
            "dia_id": dia_id,
            "speaker": "佛子",
            "voice_asset_id": voice_asset_id,
            "text": line["text"],
            "performance": PERFORMANCES[line["beat_id"]],
        }
        prompt = (
            "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
            f"{visual}\n\n"
            "NEGATIVE_PROMPT:\n"
            f"{NEGATIVE}\n\n"
            "AUDIO_PROMPT_DIALOGUE_ONLY:\n"
            f"{json.dumps(audio, ensure_ascii=False, separators=(',', ':'))}\n"
        )
        prompt_path = PROMPT_DIR / f"{dia_id}_佛子_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        contracts.append({
            "order": line["order"],
            "dialogue_id": dia_id,
            "beat_id": line["beat_id"],
            "speaker": "佛子",
            "text": line["text"],
            "timeline_in_frame": line["timeline_in_frame"],
            "timeline_out_frame_exclusive": line["timeline_out_frame_exclusive"],
            "voice_asset_id": voice_asset_id,
            "prompt_path": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [FOZI_REF],
            "state": "PROMPT_CONTRACT_READY_NOT_SUBMITTED",
            "standalone_final_audio_generation_allowed": False,
            "multimodal_source_submission_allowed_after_batch_preflight": True,
            "final_bind_allowed": False,
        })
        guard_rows.append({
            "dialogue_id": dia_id,
            "prompt_file": str(prompt_path),
            "status": "PASS" if line["text"] not in visual else "FAIL",
            "dialogue_text_absent_from_visual": line["text"] not in visual,
            "audio_payload_has_voice_asset_id": voice_asset_id in prompt,
        })

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "schema": "qingshan.e19r.fozi_multimodal_binding_prompt_contracts.v1",
        "episode": "E19R",
        "created_at": now,
        "status": "PASS_15_FOZI_PROMPT_CONTRACTS_READY_NOT_SUBMITTED" if not failures else "FAIL",
        "source_queue_ref": str(QUEUE.relative_to(ROOT)),
        "voice_registry_ref": str(REGISTRY.relative_to(ROOT)),
        "voice_asset_id": voice_asset_id,
        "contract_count": len(contracts),
        "contracts": contracts,
        "ordering_guard": {
            "final_bind_allowed": False,
            "edit_admission_allowed": False,
            "package_allowed": False,
            "platform_action_allowed": False,
            "reason": "The 15 Fozi sources may generate concurrently; final E19R lock remains ordered after E18R."
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    guard = {
        "schema": "qingshan.visual_text_guard.v1",
        "episode": "E19R",
        "created_at": now,
        "status": "PASS" if all(row["status"] == "PASS" for row in guard_rows) else "FAIL",
        "failure_count": sum(row["status"] != "PASS" for row in guard_rows),
        "results": guard_rows,
    }
    GUARD.write_text(json.dumps(guard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "qingshan.giggle_task_manifest.v1",
        "episode": "E19R",
        "authorization_ref": "ROGER-20260716-E19-REMAKE",
        "prompt_constitution_version": "v1",
        "episode_total_prompt_count": 40,
        "script_gate": {
            "beat_sheet": "configs/e19r_dialogue_beat_sheet_v3_machine_approved_20260717.json",
            "report": "qa/auto_human_timeout_fallback_20260717/E19R_V3_MACHINE_APPROVED_SCRIPT_READINESS_GATE_20260717.json"
        },
        "script_density_gate": {
            "episode": "E19R",
            "script": "configs/e19r_dialogue_beat_sheet_v3_machine_approved_20260717.json",
            "review": "workflow/script_review/reviews/E19R_剧情密度审核_20260717.md",
            "preflight_report": "qa/script_density_gate_20260717/E19R_SCRIPT_DENSITY_PREFLIGHT_20260717.json"
        },
        "preflight_evidence": {
            "prompt_contracts": str(OUT.relative_to(ROOT)),
            "prompt_contracts_qa": str(QA.relative_to(ROOT)),
            "visual_text_guard": str(GUARD.relative_to(ROOT)),
            "voice_registry": str(REGISTRY.relative_to(ROOT))
        },
        "pilot_policy": "Submit the 15 Fozi registered-voice lines concurrently. Final bind, edit, package and platform actions remain closed until download QA and ordered admission.",
        "tasks": [
            {
                "dialogue_id": item["dialogue_id"],
                "source_id": f"E19R-{item['dialogue_id']}-FOZI-MM-R1",
                "beat_id": item["beat_id"],
                "speaker": "佛子",
                "text": item["text"],
                "voice_asset_id": voice_asset_id,
                "status": "READY_TO_SUBMIT",
                "prompt_path": item["prompt_path"],
                "prompt_sha256": item["prompt_sha256"],
                "reference_images": item["reference_images"],
                "model": "seedance-2.0-pro",
                "duration": 4,
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "force_resubmit": False,
                "designated_static_beat": False,
            }
            for item in contracts
        ],
        "ordering_guard": payload["ordering_guard"],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = {
        "schema": "qingshan.e19r.fozi_multimodal_binding_prompt_contracts_qa.v1",
        "episode": "E19R",
        "created_at": now,
        "status": "PASS" if not failures and guard["status"] == "PASS" else "FAIL",
        "machine_confidence": "HIGH",
        "voice_asset_id": voice_asset_id,
        "expected_contract_count": 15,
        "actual_contract_count": len(contracts),
        "unique_dialogue_id_count": len({item["dialogue_id"] for item in contracts}),
        "checks": {
            "voice_registry_machine_qa_pass": asset.get("qa_status") == "PASS",
            "all_15_fozi_lines_compiled_once": len(contracts) == 15 and len({item["dialogue_id"] for item in contracts}) == 15,
            "dialogue_isolated_to_audio_section": guard["status"] == "PASS",
            "voice_asset_present_for_every_contract": all(item["voice_asset_id"] == voice_asset_id for item in contracts),
            "standalone_final_tts_forbidden": all(not item["standalone_final_audio_generation_allowed"] for item in contracts),
            "final_bind_and_platform_gates_closed": not payload["ordering_guard"]["final_bind_allowed"] and not payload["ordering_guard"]["platform_action_allowed"],
        },
        "failures": failures + ([] if guard["status"] == "PASS" else ["visual_text_guard_failed"]),
        "rollback": "Delete only this NOT_FINAL Fozi batch and stop its remote tasks; preserve the registered sample and approved E19R script."
    }
    QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "contracts": len(contracts), "manifest": str(MANIFEST), "qa": str(QA)}, ensure_ascii=False))
    return 0 if qa["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
