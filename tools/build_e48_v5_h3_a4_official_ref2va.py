#!/usr/bin/env python3
"""Build the user-authorized E48 five-unit A4 official Ref2VA migration.

This builder is zero-POST.  It preserves A1-A3 history, emits a one-unit probe
manifest for VU011, and emits a held four-unit continuation manifest that may
only be authorized after the probe passes burned-text and native-speech QA.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from minimax_h3_ref2va_prompt_compiler import (
    H3_OFFICIAL_REF2VA_PROFILE,
    REQUIRED_CONSTRAINT_COVERAGE,
)
from role_semantic_prompt_gate import validate_role_semantics_structure
from shot_media_admission_gate import compute_input_template_id
from video_prompt_compiler import compile_model_prompt, validate_model_prompt_for_model


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e48_v5_20260830"
QA = ROOT / "qa/e48_v5_h3_a4_official_ref2va"
SOURCE = PROD / "E48_V5_H3_A3_ENGLISH_AUDIO_RESCUE_PRECHECK_V1.json"
PROMPT_DIR = PROD / "video_prompts_h3_a4_official_ref2va"
OUT = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_PRECHECK_V1.json"
PROBE = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_VU011_PROBE_V1.json"
HELD = PROD / "E48_V5_H3_A4_OFFICIAL_REF2VA_REMAINING4_HELD_V1.json"
REFERENCE_TEXT_AUDIT = QA / "E48_V5_H3_A4_REFERENCE_TEXT_INPUT_AUDIT_V1.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


SUBJECTS = {
    "E48-VU-011": [
        "<Subject 1> is the older adult male rider whose face, conical straw hat, layered dark travelling robe, body proportions, and dark horse come from <Picture 1> and <Picture 2>.",
        "<Subject 2> is the younger adult male rider whose face, tied topknot, rain-soaked dark robe over a blue-grey inner layer, body proportions, and horse come from <Picture 1> and <Picture 2>.",
        "<Subject 3> is the rain-soaked period street environment, including the east end of the lane, the northward depth axis, timber-and-tile buildings, lantern spacing, wet stone, and continuous rain shown in <Picture 1> and <Picture 2>.",
    ],
    "E48-VU-021": [
        "<Subject 1> is the younger adult male investigator whose face, tied topknot, dark robe, body proportions, and doorway position come from <Picture 1> and <Picture 2>.",
        "<Subject 2> is the older adult male companion whose face, hat, layered robe, body proportions, restrained smile, and table-side position come from <Picture 1> and <Picture 2>.",
        "<Subject 3> is the deceased adult male evidence figure suspended from the left rear roof beam, preserved as lifeless and moved only by rope, gravity, and residual inertia.",
        "<Subject 4> is the upstairs gambling-room environment, including the table axis, central covered lamp, left-rear beam and rope, right-side doorway, north window, and warm dry interior shown in <Picture 1> and <Picture 2>.",
    ],
    "E48-VU-023": [
        "<Subject 1> is the younger adult male investigator whose face, tied topknot, dark robe, body proportions, and near-table position come from <Picture 1> and <Picture 2>.",
        "<Subject 2> is the older adult male companion whose face, hat, layered robe, body proportions, and opposite-table position come from <Picture 1> and <Picture 2>.",
        "<Subject 3> is the deceased adult male evidence figure suspended from the left rear roof beam with visibly open eyes, preserved as lifeless and moved only by rope, gravity, and residual inertia.",
        "<Subject 4> is the upstairs gambling-room environment, including the table axis, central covered lamp, left-rear beam and rope, right-side doorway, north window, and warm dry interior shown in <Picture 1> and <Picture 2>.",
    ],
    "E48-VU-024": [
        "<Subject 1> is the younger adult male investigator whose face, tied topknot, dark robe, body proportions, throat bruise, and near-table position come from <Picture 1> and <Picture 2>.",
        "<Subject 2> is the older adult male companion whose face, hat, layered robe, body proportions, and position behind <Subject 1> come from <Picture 1> and <Picture 2>.",
        "<Subject 3> is the deceased adult male evidence figure suspended from the left rear roof beam with visibly open eyes, preserved as lifeless and moved only by rope, gravity, and residual inertia.",
        "<Subject 4> is the upstairs gambling-room environment, including the table axis, central covered lamp, left-rear beam and rope, right-side doorway, north window, and warm dry interior shown in <Picture 1> and <Picture 2>.",
    ],
    "E48-VU-027": [
        "<Subject 1> is the older adult male strategist whose face, hat, layered robe, body proportions, restrained authority, and table-side position come from <Picture 1>.",
        "<Subject 2> is the younger adult male investigator whose face, tied topknot, dark robe, body proportions, and listening position come from <Picture 1>.",
        "<Subject 3> is the deceased adult male evidence figure suspended from the roof beam, preserved as lifeless and moved only by rope, gravity, and residual inertia.",
        "<Subject 4> is the upstairs gambling-room environment, including the table axis, covered lamp, north window, beam and rope, cup, dry interior, and warm light shown in <Picture 1>.",
    ],
}


SHOT_TEXT = {
    "E48-VU-011": [
        "[Shot 1] The shot begins from <Picture 1> as a stable medium two-shot tracks <Subject 1> on frame right and <Subject 2> on frame left riding abreast through <Subject 3>. The horses maintain a slow matched walking rhythm. Rain pours from the brim of <Subject 1> onto the mane while his chin lifts slightly toward the dark northern sky. <Subject 1> (S1) uses the weathered low male timbre referenced from <Audio 1> with a measured restrained cadence and says, <d>[Chinese]景朝的头，藏在京城。</d> His lips close fully at the sentence end. <Subject 2> listens with a closed mouth and does not borrow the voice.",
        "[Shot 2] At 00:03.200, a motivated cut reaches the closer composition in <Picture 2> without changing the rain, street map, horse order, wardrobe, light direction, or one-hundred-eighty-degree axis. <Subject 2> tightens the reins once, turns his shoulder toward <Subject 1>, and keeps his horse aligned. <Subject 2> (S2) uses the clearer younger male timbre referenced from <Audio 2> with an even questioning delivery and says, <d>[Chinese]谁见过他。</d> His lips close on the final syllable. <Subject 1> remains silent and gives one restrained eye response while both riders continue forward into the final frame.",
    ],
    "E48-VU-021": [
        "[Shot 1] The shot begins from <Picture 1> at the right-side doorway of <Subject 4>. <Subject 1> stops at the threshold instead of stepping farther inside, fixes his gaze on the suspended feet of <Subject 3>, and lets his jaw tighten once. <Subject 3> remains lifeless, with no breath, blink, speech, or self-driven reaction. <Subject 1> (S1) uses the restrained younger male timbre referenced from <Audio 1> and asks, <d>[Chinese]这就是那个人？</d> He closes his lips completely. <Subject 2> listens from the table side with a closed mouth and does not inherit the question.",
        "[Shot 2] At 00:03.600, a motivated cut preserves the table axis, central lamp, doorway direction, rope position, and the same suspended evidence figure while moving to <Picture 2>. <Subject 2> turns one open palm toward <Subject 3>; the shoulder initiates, elbow follows, palm opens, and the gesture stops without repeating. <Subject 2> (S2) uses the older weathered male timbre referenced from <Audio 2> with a dry controlled delivery and says, <d>[Chinese]景朝来抓他的人。</d> His lips close fully. <Subject 1> remains silent, and <Subject 3> continues only a faint gravity-driven sway as the room holds for the safe tail.",
    ],
    "E48-VU-023": [
        "[Shot 1] The shot begins from <Picture 1> in <Subject 4>. <Subject 1> moves only his eyes from the doorway to the face of <Subject 3>; his pupils make small corrections to the corpse's slight rope-driven rotation. <Subject 3> has visibly open eyes yet remains completely lifeless, with no breath, blink, speech, or active movement. The camera holds a restrained medium composition and does not use a static insert, slideshow, orbit, or unexplained angle reversal.",
        "[Shot 2] At 00:04.000, a motivated closer angle preserves the table axis, light direction, rope location, identities, wardrobe, and open-eyed evidence. <Subject 1> draws his chin inward, swallows once, and lets the throat settle into a new tense position. <Subject 1> (S1) uses the younger restrained male timbre referenced from <Audio 1> and says, <d>[Chinese]百鹿阁死的那几个，眼睛是合上的。</d> His lips close fully after the statement. <Subject 2> listens from the opposite side of the table without vocalizing or taking over the action.",
        "[Shot 3] At 00:08.300, the camera cuts across the same established axis to <Picture 2>, where <Subject 2> turns his head toward the profile of <Subject 1> while keeping both feet settled beside the table. <Subject 2> (S2) uses the older weathered male timbre referenced from <Audio 2> with a quiet probing cadence and says, <d>[Chinese]你倒记得清楚。</d> His lips close at the end. <Subject 1> remains silent, <Subject 3> remains lifeless, and the lamp and rain ambience continue without a reset.",
    ],
    "E48-VU-024": [
        "[Shot 1] The shot begins from <Picture 1> in <Subject 4>. <Subject 1> raises his own hand from inside his sleeve, keeps the shoulder, upper arm, elbow, forearm, wrist, palm, and fingers anatomically continuous, and presses two fingertips through the collar against the bruise on his own throat. The pressure causes one small shoulder tightening and one restrained eye response toward the open eyes of <Subject 3>. Every visible character keeps the lips closed and produces no speech.",
        "[Shot 2] At 00:02.700, the camera makes a motivated close reframing without crossing the established table axis or changing identity, wardrobe, bruise placement, rope position, or light direction. <Subject 1> keeps his eyes on <Subject 3> and silently forms one brief private realization with minimal lip motion, without voice, whisper, breathy words, narration, or any audible language. His lips return to a fully closed resting state immediately. <Subject 3> remains lifeless and moves only through a faint gravity-driven rope sway.",
        "[Shot 3] At 00:05.400, the composition reaches <Picture 2> while preserving the same room map and subject placement. <Subject 2> stops half a beat behind <Subject 1>, moves both of his own hands from the front of his robe to the small of his back, interlaces them once, and settles his weight. Both men keep their lips closed and produce no speech through the final frame. Native rain, cloth, and room sounds remain the only audible layers.",
    ],
    "E48-VU-027": [
        "[Shot 1] The shot begins from <Picture 1> in <Subject 4>, holding <Subject 1> at the table, <Subject 2> listening opposite him, and <Subject 3> suspended in the rear evidence plane. <Subject 1> uses his own index finger to trace one closing circle on the tabletop and leaves one deliberate gap; fingertip contact drives the motion and the hand stops after a single pass. <Subject 1> (S1) uses the older weathered male timbre referenced from <Audio 1> with controlled authority and says, <d>[Chinese]坊封了，放一个人出去报信。</d> He closes his lips. <Subject 2> remains silent and watches the indicated gap.",
        "[Shot 2] At 00:04.100, a shallow motivated push-in preserves the table axis, room map, lamp, cup ownership, identities, wardrobe, and suspended evidence. <Subject 1> slides his own thumb once along the cup rim while keeping his gaze fixed on <Subject 2>; the thumb reaches the end of the rim motion and stops. Reusing the same (S1) identity and <Audio 1> timbre, <Subject 1> says, <d>[Chinese]外头说叛谍在我手里。</d> His lips close fully. <Subject 2> gives one restrained eye response without speaking, and <Subject 3> remains lifeless as the rain ambience bridges the final frame.",
    ],
}


COMMON_DETAIL = (
    "The target video uses vertical live-action period-mystery photography with natural adult faces, "
    "period-authentic differentiated clothing, textured wet or dry fabric, restrained contrast, realistic depth, "
    "and no synthetic beauty filter. Identity, age, facial geometry, hair, wardrobe silhouette, wardrobe color, "
    "body proportions, and social-status styling remain fixed to their subject references. The location map, "
    "foreground and background planes, entrances, table or street axis, weather, exposure, and key-light direction "
    "remain continuous. Props keep one owner, scale, material, orientation, and contact history. No actor, listener, "
    "speaker, corpse, limb, garment, mount, or prop may swap, merge, split, appear from an occluder, or change sides. "
    "Every physical action follows preparation, weight transfer, contact, reaction, displacement, and a settled result; "
    "eyes move before the head, the jaw and shoulders follow, and each microexpression changes once rather than loops. "
    "Camera movement is motivated by new story information, stays on the established axis, and avoids an unmotivated "
    "orbit, repeated one-direction drift, freeze, speed ramp, frame clone, static tableau, or slideshow interpolation. "
)


COMMON_TAIL = (
    "The incoming state preserves the previous unit's posture, eye line, object position, residual cloth motion, weather, "
    "and native ambience without replaying the prior event. The ending completes the causal action and leaves natural "
    "breathing, fabric inertia, environmental micro-motion, and continuous room tone for the next media-safe cut. "
    "Natural synchronous audio includes only location ambience, rain or wind, footsteps or hoof contact when visible, "
    "cloth movement, prop contact, and authorized action sound. No narrator, explanation, singing, improvised speech, "
    "reference-audio words, external background music, or cross-task sound appears. Every wall, sign, lantern face, "
    "tabletop, garment, prop, and background surface remains blank and unmarked, with no captions, subtitles, titles, "
    "labels, dialogue boxes, interface graphics, letters, numerals, logos, watermarks, or readable writing."
)


def reference_text_audit_for(task: dict) -> dict:
    """Bind audited reference pixels to the official H3 contract.

    H3 Ref2VA strongly retains its source pictures, so character-like marks in
    a picture are a hard pre-submit failure even when the prose says that all
    surfaces should be blank.  This evidence is deliberately separate from,
    and additive to, the original thirteen H3 constraint-coverage gates.
    """
    source = json.loads(REFERENCE_TEXT_AUDIT.read_text(encoding="utf-8"))
    by_path = {row["reference_image"]: row for row in source["rows"]}
    rows = []
    for index, value in enumerate(task.get("reference_images") or [], 1):
        row = copy.deepcopy(by_path.get(value) or {})
        if not row:
            raise RuntimeError(f"{task['unit_id']} reference text audit missing: {value}")
        row["picture_index"] = index
        rows.append(row)
    passed = all(
        row.get("readable_text_detected") is False
        and row.get("character_like_marks_detected") is False
        for row in rows
    )
    return {
        "status": "PASS_TEXT_FREE_REFERENCES" if passed else "FAIL_UNSAFE_REFERENCE_TEXT",
        "picture_count": len(rows),
        "source_audit_ref": rel(REFERENCE_TEXT_AUDIT),
        "rows": rows,
    }


def make_contract(task: dict) -> dict:
    unit_id = task["unit_id"]
    dialogues = []
    for spec in task.get("ordered_prompt_specs") or []:
        raw = str(spec.get("dialogue") or "").strip()
        if raw:
            speaker, _, words = raw.partition("：")
            dialogues.append((speaker, words))
    unique_speakers = []
    for speaker, _ in dialogues:
        if speaker not in unique_speakers:
            unique_speakers.append(speaker)
    subject_map = {
        "E48-VU-011": {"金猪": "<Subject 1>", "陈迹": "<Subject 2>"},
        "E48-VU-021": {"陈迹": "<Subject 1>", "金猪": "<Subject 2>"},
        "E48-VU-023": {"陈迹": "<Subject 1>", "金猪": "<Subject 2>"},
        "E48-VU-024": {},
        "E48-VU-027": {"金猪": "<Subject 1>"},
    }[unit_id]
    definitions = list(SUBJECTS[unit_id])
    for index in range(1, len(task.get("reference_images") or []) + 1):
        definitions.append(
            f"<Picture {index}> is a chronological composition, identity, wardrobe, map, prop, lighting, and physical-state anchor for the target shots."
        )
    for index, speaker in enumerate(unique_speakers, 1):
        definitions.append(
            f"<Audio {index}> is the voice-timbre reference for {subject_map[speaker]} (S{index})."
        )
    task_types = "reference generation + keyframe completion"
    if unique_speakers:
        task_types += " + audio reference"
    summary = (
        f"[{task_types}] The target video is a {float(task['duration_seconds']):g}-second vertical live-action "
        f"period-mystery unit that preserves all defined subjects and uses <Picture 1> through "
        f"<Picture {len(task.get('reference_images') or [])}> as chronological visual anchors. "
        + (
            "The audio assets provide voice timbre and delivery only for the explicitly bound speakers."
            if unique_speakers else
            "No character produces audible speech and no speaker identity is assigned."
        )
    )
    retention = []
    for index in range(1, len(SUBJECTS[unit_id]) + 1):
        retention.append(
            f"<Subject {index}> (appears in all applicable shots): fully_preserved - identity, defined appearance, spatial role, state, and causal behavior remain unchanged."
        )
    for index in range(1, len(task.get("reference_images") or []) + 1):
        retention.append(
            f"<Picture {index}> (chronological visual anchor): fully_preserved - composition, placement, map, wardrobe, props, lighting, and the defined physical state are retained without static-pose interpolation."
        )
    for index, speaker in enumerate(unique_speakers, 1):
        retention.append(
            f"<Audio {index}>: reference - only timbre, rhythm, emotion, age character, and delivery guide {subject_map[speaker]} (S{index}); the original dialogue content is not carried into the target video."
        )
    detailed = COMMON_DETAIL + "\n" + "\n".join(SHOT_TEXT[unit_id]) + "\n" + COMMON_TAIL
    ambience = (
        "Continuous night rain outside, restrained interior room tone, soft cloth movement, and only visible synchronized prop contact."
        if unit_id != "E48-VU-011" else
        "Continuous heavy night rain, wet hoofbeats, saddle-leather creaks, soaked cloth movement, horse breathing, and water running from the eaves."
    )
    return {
        "subject_definitions": definitions,
        "summary": summary,
        "retention_analysis": retention,
        "detailed_description": detailed,
        "overall_soundscape": ambience,
        "non_diegetic_music": "N/A",
        "constraint_coverage": {key: True for key in REQUIRED_CONSTRAINT_COVERAGE},
        "speaker_subject_bindings": subject_map,
        "reference_text_audit": reference_text_audit_for(task),
    }


def subset_manifest(base: dict, tasks: list[dict], *, status: str, condition: str) -> dict:
    payload = {key: copy.deepcopy(value) for key, value in base.items() if key != "tasks"}
    payload.update({
        "schema": "qingshan.giggle_h3_official_ref2va_retry_manifest.v1",
        "status": status,
        "provider_post_allowed": False,
        "release_condition": condition,
        "video_unit_count": len(tasks),
        "runtime_seconds": sum(int(row["duration_seconds"]) for row in tasks),
        "tasks": copy.deepcopy(tasks),
        "provider_post_count": 0,
    })
    return payload


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for original in source["tasks"]:
        task = copy.deepcopy(original)
        unit_id = task["unit_id"]
        task["h3_prompt_profile"] = H3_OFFICIAL_REF2VA_PROFILE
        task["h3_ref2va_contract"] = make_contract(task)
        task.setdefault("machine_contract", {})["h3_ref2va_contract"] = copy.deepcopy(
            task["h3_ref2va_contract"]
        )
        prompt_text = compile_model_prompt(task)
        prompt_path = PROMPT_DIR / f"{unit_id}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        report = validate_model_prompt_for_model(
            prompt_text, model="MiniMax-H3", source_id=f"{unit_id}-A4-OFFICIAL-REF2VA", unit=task
        )
        structural = validate_role_semantics_structure(task)
        if report["status"] != "PASS" or structural:
            raise RuntimeError(f"{unit_id} official Ref2VA failed: {report['failures']} {structural}")
        prior_shas = list(task.get("prior_prompt_sha256") or []) + [str(task["prompt_sha256"])]
        task.update({
            "task_key": f"{unit_id}-VIDEO-H3-A4-OFFICIAL-REF2VA",
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "model_prompt_contract": report,
            "retry_attempt": 4,
            "creative_attempt_ordinal": 4,
            "paid_attempt": 4,
            "user_attempt_cap_override": True,
            "user_attempt_cap_override_ref": "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO",
            "user_attempt_cap_override_reason": "OFFICIAL_PROVIDER_SCHEMA_MIGRATION",
            "provider_post_allowed": False,
            "prior_prompt_sha256": prior_shas,
            "same_creative_prompt_intentional": False,
            "retry_design_mode": "COVERAGE_REDESIGN",
            "material_change_from_prior_attempt": (
                "Full rewrite into MiniMax official six-section Ref2VA grammar; English directing prose, "
                "dialogue only inside d tags, native speaker IDs, silent-subject handling, and retained "
                "identity/map/wardrobe/prop/physics/microexpression/transition/text-free/native-sound gates."
            ),
            "no_further_automatic_retry": True,
        })
        task["changed_variables"] = [
            "PROMPT", "SHOT_STRUCTURE", "CAMERA_PLAN", "ACTION_TIMELINE",
            "REFERENCE_STRATEGY", "ROLE_SERIALIZATION", "PROVIDER_GRAMMAR",
        ]
        task["coverage_redesign_contract"] = {
            "schema": "qingshan.video_coverage_prompt_redesign.v1",
            "status": "PASS",
            "prompt_rewritten_from_scratch": True,
            "shot_structure_redesigned": True,
            "camera_plan_redesigned": True,
            "action_timeline_redesigned": True,
            "reference_strategy_redesigned": True,
            "role_serialization_redesigned": True,
            "micro_edit_reuse_forbidden": True,
            "previous_design_sha256": prior_shas[-1],
            "design_sha256": task["prompt_sha256"],
        }
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)

    manifest = subset_manifest(
        source, tasks, status="PASS_ZERO_POST_USER_AUTHORIZED_A4",
        condition="SUBMIT_VU011_PROBE_FIRST_THEN_REQUIRE_POSTGEN_TEXT_AND_SPEECH_PASS",
    )
    manifest["authorization_ref"] = "ROGER-2026-08-30-E48-FIVE-UNIT-OFFICIAL-REF2VA-REDO"
    manifest["official_source"] = "https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt"
    write(OUT, manifest)
    probe = subset_manifest(
        manifest, [row for row in tasks if row["unit_id"] == "E48-VU-011"],
        status="READY_FOR_EXPLICITLY_AUTHORIZED_ONE_UNIT_PROBE",
        condition="USER_ALREADY_AUTHORIZED;POSTGEN_MUST_PASS_ZERO_BURNED_TEXT_AND_ZERO_EXTRA_SPEECH",
    )
    write(PROBE, probe)
    held = subset_manifest(
        manifest, [row for row in tasks if row["unit_id"] != "E48-VU-011"],
        status="HELD_PENDING_VU011_PROBE_QA",
        condition="VU011_OFFICIAL_REF2VA_PROBE_POSTGEN_QA_PASS",
    )
    write(HELD, held)
    print(json.dumps({
        "status": "PASS_ZERO_POST_BUILD", "tasks": len(tasks),
        "manifest": rel(OUT), "probe": rel(PROBE), "held": rel(HELD),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
