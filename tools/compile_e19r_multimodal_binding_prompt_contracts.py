#!/usr/bin/env python3
"""Compile the 22 ready E19R lines into guarded multimodal prompt contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "configs/e19r_audio_binding_work_queue_v1_not_final_20260717.json"
OUT = ROOT / "configs/e19r_multimodal_binding_prompt_contracts_v1_not_final_20260717.json"
GEN_MANIFEST = ROOT / "configs/e19r_multimodal_binding_giggle_task_manifest_v1_not_final_20260717.json"
QA = ROOT / "qa/auto_human_timeout_fallback_20260717/E19R_MULTIMODAL_BINDING_PROMPT_CONTRACTS_V1_QA_20260717.json"
VISUAL_GUARD = ROOT / "qa/auto_human_timeout_fallback_20260717/E19R_MULTIMODAL_BINDING_PROMPT_CONTRACTS_V1_VISUAL_TEXT_GUARD_20260717.json"
PROMPT_DIR = ROOT / "workflow/prompts/e19r_multimodal_binding_contracts_v1_not_final_20260717"

READY_STATE = "READY_FOR_MULTIMODAL_AUDIO_BINDING_NOT_STANDALONE_TTS"
CHENJI_REF = "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg"
BAILI_REF = "working_assets/e18r_b05_picture_r2_refs_20260716/BAILI-MALE-DISGUISE-E19R-B02-T0500.png"

SCENES = {
    "B01": "the rain-dark medicine courtyard below a low tiled wall before dawn",
    "B02": "the narrow service lane beside the medicine courtyard under one period lantern",
    "B03": "the wet moonlit alley where the mind-thief confrontation is already underway",
    "B04": "the same wet alley during the restrained verbal counterattack",
    "B05": "the wall-foot escape beat beside the medicine courtyard",
    "B06": "the dark side-door route while distant patrol lanterns approach",
}

NEGATIVE = (
    "wrong face, identity drift, duplicate person, extra fingers, broken wrist, visible modern object, "
    "modern clothing, modern signage, logo, readable generated Chinese, English letters, Latin letters, "
    "subtitles, captions, on-screen text, text overlay, watermark, caption bar, letterbox text, "
    "\u5b57\u5e55, \u6587\u5b57, \u6807\u9898\u6761, speech bubble, lower third, static talking head, frozen pose, "
    "repeated movement, slow motion, dreamy pace, floating, weightless motion, rubber physics, "
    "standalone narration, off-character voice, sentence truncation"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def speaker_contract(line: dict) -> tuple[str, list[str], str]:
    speaker = line["speaker"]
    beat = line["beat_id"]
    scene = SCENES[beat]
    order = int(line["order"])
    if speaker == "\u9648\u8ff9":
        actions = [
            "holds one open empty hand at waist level, then lowers it",
            "tracks the other speaker with a restrained eye movement and one grounded half-step",
            "briefly indicates the safe route with two fingers kept below the chest",
        ]
        visual = (
            f"Vertical 9:16 cinematic period realism in {scene}. Match canonical young Chenji exactly: "
            "upright grey apprentice robe, youthful face, restrained alertness. Medium close speaking shot. "
            f"Chenji {actions[order % len(actions)]}, delivers one complete line with natural restrained mouth movement, "
            "then settles. Native real-time motion, clear beginning, change, and finish; one warm period lantern against cold rain-blue ambience."
        )
        return visual, [CHENJI_REF], "restrained, dry, alert; one complete sentence without rushing"
    if speaker == "\u767d\u9ca4":
        actions = [
            "keeps the shoulders angled away, makes one low practical hand cue, and returns the hand below the waist",
            "checks the approaching route with one small eye-line shift while the body remains grounded",
            "suppresses a brief reaction, then gives one economical forward half-step",
        ]
        visual = (
            f"Vertical 9:16 cinematic period realism in {scene}. Match the supplied Baili male-disguise reference: "
            "plain practical male attendant clothing, closed collar, hair fully concealed, flat masculine silhouette, pendant hidden. "
            f"Medium close speaking shot. Baili {actions[order % len(actions)]}, delivers one complete line with subtle natural mouth movement, "
            "and never touches the neck or collar. No identity reveal. Native real-time motion with a clear beginning, change, and finish."
        )
        return visual, [BAILI_REF], "quiet, practical, guarded; complete the line cleanly"
    if speaker == "\u8fdc\u5904\u5de1\u591c\u58f0":
        visual = (
            f"Vertical 9:16 cinematic period realism in {scene}. No visible speaking face. Two distant period patrol lanterns "
            "move behind a rain-dark wall from left to right while wet leaves tremble once in the foreground. The patrol command comes from "
            "offscreen distance only. Native real-time motion, no modern objects, no identifiable new character."
        )
        return visual, [], "distant firm patrol call, clearly intelligible, no close-mic intimacy"
    raise ValueError(f"unexpected ready speaker: {speaker}")


def main() -> int:
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    ready = [line for line in queue["lines"] if line["state"] == READY_STATE]
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    contracts: list[dict] = []
    seen: set[str] = set()

    for line in ready:
        dia_id = line["dialogue_id"]
        if dia_id in seen:
            failures.append(f"duplicate_dialogue_id:{dia_id}")
        seen.add(dia_id)
        if line.get("standalone_final_audio_generation_allowed") is not False:
            failures.append(f"standalone_final_audio_not_false:{dia_id}")
        if line.get("multimodal_source_preparation_allowed") is not True:
            failures.append(f"multimodal_preparation_not_true:{dia_id}")
        if line.get("final_bind_allowed") is not False:
            failures.append(f"final_bind_not_false:{dia_id}")
        if not line.get("voice_asset_id"):
            failures.append(f"missing_voice_asset_id:{dia_id}")

        visual, refs, performance = speaker_contract(line)
        if line["text"].replace(" ", "") in visual.replace(" ", ""):
            failures.append(f"dialogue_leak_in_visual:{dia_id}")
        audio_payload = {
            "dia_id": dia_id,
            "speaker": line["speaker"],
            "voice_asset_id": line["voice_asset_id"],
            "text": line["text"],
            "performance": performance,
        }
        prompt_text = (
            "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
            f"{visual}\n\n"
            "NEGATIVE_PROMPT:\n"
            f"{NEGATIVE}\n\n"
            "AUDIO_PROMPT_DIALOGUE_ONLY:\n"
            f"{json.dumps(audio_payload, ensure_ascii=False, separators=(',', ':'))}\n"
        )
        prompt_path = PROMPT_DIR / f"{dia_id}_{line['speaker']}_prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        for ref in refs:
            if not (ROOT / ref).is_file():
                failures.append(f"missing_reference:{dia_id}:{ref}")

        contracts.append({
            "order": line["order"],
            "dialogue_id": dia_id,
            "beat_id": line["beat_id"],
            "speaker": line["speaker"],
            "text": line["text"],
            "timeline_in_frame": line["timeline_in_frame"],
            "timeline_out_frame_exclusive": line["timeline_out_frame_exclusive"],
            "voice_asset_id": line["voice_asset_id"],
            "prompt_path": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": refs,
            "state": "PROMPT_CONTRACT_READY_NOT_SUBMITTED",
            "standalone_final_audio_generation_allowed": False,
            "multimodal_source_submission_allowed_after_batch_preflight": True,
            "final_bind_allowed": False,
        })

    expected = 22
    if len(ready) != expected:
        failures.append(f"ready_count:{len(ready)}!=22")
    if len(contracts) != expected:
        failures.append(f"contract_count:{len(contracts)}!=22")
    if queue.get("approved_script_sha256") != "adef01ca8a888f01c8e5b85d79e42b60232eaf14b47e20cde7354d954f34ce44":
        failures.append("approved_script_sha_mismatch")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "schema": "qingshan.e19r.multimodal_binding_prompt_contracts.v1",
        "episode": "E19R",
        "created_at": now,
        "status": "PASS_22_PROMPT_CONTRACTS_READY_NOT_SUBMITTED" if not failures else "FAIL",
        "approved_script_sha256": queue["approved_script_sha256"],
        "source_queue_ref": str(QUEUE.relative_to(ROOT)),
        "policy": "Each ready line stays inside one multimodal video request. Standalone final TTS, final binding, edit admission, packaging, and platform action remain forbidden.",
        "contract_count": len(contracts),
        "contracts": contracts,
        "ordering_guard": {
            "final_bind_allowed": False,
            "edit_admission_allowed": False,
            "package_allowed": False,
            "platform_action_allowed": False,
            "reason": "Source preparation may run concurrently; final E19R admission remains after E17 and E18R.",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not VISUAL_GUARD.is_file():
        failures.append("visual_text_guard_missing")
    else:
        guard = json.loads(VISUAL_GUARD.read_text(encoding="utf-8"))
        if guard.get("status") != "PASS" or guard.get("failure_count") != 0:
            failures.append("visual_text_guard_not_pass")
    generation_manifest = {
        "schema": "qingshan.giggle_task_manifest.v1",
        "episode": "E19R",
        "authorization_ref": "ROGER-20260716-E19-REMAKE",
        "prompt_constitution_version": "v1",
        "episode_total_prompt_count": 40,
        "script_gate": {
            "beat_sheet": "configs/e19r_dialogue_beat_sheet_v3_machine_approved_20260717.json",
            "report": "qa/auto_human_timeout_fallback_20260717/E19R_V3_MACHINE_APPROVED_SCRIPT_READINESS_GATE_20260717.json",
        },
        "preflight_evidence": {
            "prompt_contracts": str(OUT.relative_to(ROOT)),
            "prompt_contracts_qa": str(QA.relative_to(ROOT)),
            "visual_text_guard": str(VISUAL_GUARD.relative_to(ROOT)),
        },
        "pilot_policy": "Submit only the 22 registered-voice lines as multimodal sources. Fozi and Shizi lines remain excluded. Final bind, edit, package, and platform actions remain closed.",
        "tasks": [
            {
                "dialogue_id": item["dialogue_id"],
                "source_id": f"E19R-{item['dialogue_id']}-MM-R1",
                "beat_id": item["beat_id"],
                "speaker": item["speaker"],
                "text": item["text"],
                "voice_asset_id": item["voice_asset_id"],
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
    GEN_MANIFEST.write_text(json.dumps(generation_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = {
        "schema": "qingshan.e19r.multimodal_binding_prompt_contracts_qa.v1",
        "created_at": now,
        "status": "PASS" if not failures else "FAIL",
        "source_queue_sha256": sha256(QUEUE),
        "output_sha256": sha256(OUT),
        "generation_manifest_sha256": sha256(GEN_MANIFEST),
        "expected_contract_count": expected,
        "actual_contract_count": len(contracts),
        "unique_dialogue_id_count": len(seen),
        "speaker_counts": {
            speaker: sum(1 for item in contracts if item["speaker"] == speaker)
            for speaker in sorted({item["speaker"] for item in contracts})
        },
        "checks": {
            "all_ready_queue_lines_compiled_once": "PASS" if len(contracts) == expected and len(seen) == expected else "FAIL",
            "voice_asset_present_for_every_contract": "PASS" if all(item["voice_asset_id"] for item in contracts) else "FAIL",
            "dialogue_isolated_to_audio_section": "PASS" if not any(item.startswith("dialogue_leak") for item in failures) else "FAIL",
            "standalone_final_tts_forbidden": "PASS" if all(not item["standalone_final_audio_generation_allowed"] for item in contracts) else "FAIL",
            "final_bind_and_ordering_gates_closed": "PASS",
            "reference_files_exist": "PASS" if not any(item.startswith("missing_reference") for item in failures) else "FAIL",
        },
        "failures": failures,
        "rollback": "Delete only this NOT_FINAL prompt-contract package; preserve the approved script, timing skeleton, audio queue, admitted picture candidates, and platform state.",
    }
    QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": qa["status"], "contracts": len(contracts), "out": str(OUT), "manifest": str(GEN_MANIFEST), "qa": str(QA)}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
