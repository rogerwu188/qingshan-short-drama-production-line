#!/usr/bin/env python3
"""Build a fresh AgentCut project from admitted storyboard source slots."""

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.measured_edit_constraints import load_constraints, resolve_source_interval
    from tools.audio_postproduction_contract import PROFILE_CONFIG, validate_audio_profile
    from tools.audio_profile_binding import apply_audio_profile_binding, validate_audio_profile_binding
    from tools.sound_cue_contract import evaluate as evaluate_sound_cues
    from tools.editorial_pacing_contract import editorial_duration
except ModuleNotFoundError:  # Direct execution from tools/.
    from measured_edit_constraints import load_constraints, resolve_source_interval
    from audio_postproduction_contract import PROFILE_CONFIG, validate_audio_profile  # type: ignore
    from audio_profile_binding import apply_audio_profile_binding, validate_audio_profile_binding  # type: ignore
    from sound_cue_contract import evaluate as evaluate_sound_cues  # type: ignore
    from editorial_pacing_contract import editorial_duration  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


def _abs(path):
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(
    episode,
    receipts,
    review_results,
    out_project,
    out_admission,
    output_video,
    expected_slots,
    generation_contract=None,
    measured_edit_constraints=None,
    weak_admission=None,
    dialogue_tail_trim=None,
    dialogue_sound_bridge=None,
    dialogue_head_trim=None,
):
    if generation_contract is None:
        raise ValueError("generation_contract is required for automatic audio-profile binding")
    generation_contract_path = _abs(generation_contract)
    generation_contract_payload = json.loads(generation_contract_path.read_text(encoding="utf-8"))
    if generation_contract_payload.get("episode") != episode:
        raise ValueError(
            f"generation contract episode mismatch: {generation_contract_payload.get('episode')} vs {episode}"
        )
    if isinstance(review_results, (str, Path)):
        review_results = [review_results]
    passed_paths = set()
    weak_rows = {}
    if weak_admission:
        try:
            from tools.weak_media_admission import load_admission
        except ModuleNotFoundError:
            from weak_media_admission import load_admission
        weak_rows = load_admission(_abs(weak_admission), episode)
    for review_result in review_results:
        review = json.loads(_abs(review_result).read_text())
        passed_paths.update(str(Path(row["path"]).resolve()) for row in review.get("passed_items", []))
    admitted = {}
    latest_non_silent_audio = {}
    for receipt_path in receipts:
        receipt = json.loads(_abs(receipt_path).read_text())
        for task in receipt.get("tasks", []):
            source_id = task.get("source_id") or task.get("dialogue_id")
            output_path = task.get("output_path")
            if not source_id or not output_path or not _abs(output_path).is_file():
                continue
            metadata = task.get("metadata") or {}
            if weak_admission:
                proof = weak_rows.get(source_id)
                if (not proof or Path(proof['media_path']).resolve() != _abs(output_path).resolve()
                        or proof['media_sha256'] != sha256(_abs(output_path))):
                    raise ValueError(f"weak admission does not bind source: {source_id}")
                passed_paths.add(str(_abs(output_path).resolve()))
            if not metadata.get("silent_visual_replacement"):
                latest_non_silent_audio[source_id] = task
            if task.get("status") == "qa_pass" or str(_abs(output_path).resolve()) in passed_paths:
                admitted[source_id] = task

    if len(admitted) != expected_slots:
        raise ValueError(f"expected {expected_slots} admitted slots, found {len(admitted)}: {sorted(admitted)}")
    missing_review = [source_id for source_id, task in admitted.items() if str(_abs(task["output_path"]).resolve()) not in passed_paths]
    if missing_review:
        raise ValueError(f"admitted sources missing AI-review PASS: {missing_review}")

    edit_constraints = load_constraints(_abs(measured_edit_constraints) if measured_edit_constraints else None)
    if set(edit_constraints) - set(admitted):
        raise ValueError("MEASURED_EDIT_UNKNOWN_SOURCE: " + str(sorted(set(edit_constraints) - set(admitted))))

    # CAMERA_GRAMMAR_V1 dialogue tail trim (S7 report, tools/dialogue_tail_trim.py): unit -> kept source end.
    tail_keep = {}
    if dialogue_tail_trim:
        tail_report = json.loads(_abs(dialogue_tail_trim).read_text(encoding="utf-8"))
        tail_keep = {str(row["unit_id"]): float(row["kept_seconds"])
                     for row in tail_report.get("units") or [] if row.get("trimmed")}

    # CAMERA_GRAMMAR_V1 dialogue head trim (S7 report, tools/dialogue_head_trim.py): unit -> new source in-point
    # (extra speech before the scripted line is cut; picture and sound move together).
    head_cut = {}
    if dialogue_head_trim:
        head_report = json.loads(_abs(dialogue_head_trim).read_text(encoding="utf-8"))
        head_cut = {str(row["unit_id"]): float(row["head_cut_seconds"])
                    for row in head_report.get("units") or [] if row.get("trimmed")}

    video_clips = []
    audio_clips = []
    admissions = []
    cursor = 0.0
    for source_id, task in sorted(admitted.items()):
        source = _abs(task["output_path"])
        duration = float(task.get("duration") or 4.0)
        metadata = task.get("metadata") or {}
        dialogue_lines = metadata.get("selected_dialogue") or []
        expected_text = "".join(str(row.get("text") or "") for row in dialogue_lines)
        silent = bool(metadata.get("silent_visual_replacement"))
        audio_task = latest_non_silent_audio.get(source_id) if silent else task
        if not audio_task or not _abs(audio_task["output_path"]).is_file():
            raise ValueError(f"missing admitted dialogue audio source for {source_id}")
        audio_source = _abs(audio_task["output_path"])
        source_in = 0.0
        measured_edit = None
        if source_id in edit_constraints:
            if audio_source.resolve() != source.resolve():
                raise ValueError("MEASURED_EDIT_REQUIRES_SAME_NATIVE_AV_SOURCE")
            source_in, duration, measured_edit = resolve_source_interval(
                edit_constraints[source_id], source, duration)
        # Whole-scene cut margin (editorial_keep_seconds).  The provider slot is a
        # ceiling, not a required length: when the admitted task declares a
        # keep target, the clip ends there instead of holding the full slot.
        # A dialogue-bearing task may shorten only with a verified speech end;
        # a duration target alone is never evidence of where speech ends.
        editorial_keep = float(metadata.get("editorial_keep_seconds") or 0) or None
        if editorial_keep is not None:
            verified_end = metadata.get("verified_speech_end_seconds")
            kept = editorial_duration(
                {"duration_seconds": duration, "editorial_keep_seconds": editorial_keep},
                duration,
                contains_dialogue=bool(dialogue_lines),
                verified_end=float(verified_end) if verified_end is not None else None,
            )
            if abs(kept - duration) > 1e-6:
                clip_metadata_editorial = {
                    "requested_keep_seconds": editorial_keep,
                    "applied_keep_seconds": kept,
                    "provider_slot_seconds": duration,
                    "verified_speech_end_seconds": float(verified_end) if verified_end is not None else None,
                }
                duration = kept
            else:
                clip_metadata_editorial = None
        else:
            clip_metadata_editorial = None
        tail_trim = None
        if source_id in tail_keep and 0 < tail_keep[source_id] - source_in < duration:
            tail_trim = {"provider_slot_seconds": duration,
                         "kept_seconds": round(tail_keep[source_id] - source_in, 6),
                         "report": str(_abs(dialogue_tail_trim))}
            duration = tail_trim["kept_seconds"]
        head_trim = None
        if source_id in head_cut and source_in == 0.0 and 0 < head_cut[source_id] < duration:
            head_trim = {"head_cut_seconds": round(head_cut[source_id], 6),
                         "kept_seconds": round(duration - head_cut[source_id], 6),
                         "report": str(_abs(dialogue_head_trim))}
            source_in = head_trim["head_cut_seconds"]
            duration = head_trim["kept_seconds"]
        audio_metadata = audio_task.get("metadata") or {}
        audio_dialogue_lines = audio_metadata.get("selected_dialogue") or []
        audio_expected_text = "".join(str(row.get("text") or "") for row in audio_dialogue_lines)
        if silent and audio_expected_text.strip():
            raise ValueError(
                f"speaking silent-visual replacement for {source_id} cannot reuse dialogue audio "
                "from another multimodal candidate"
            )
        clip_metadata = {
            "episode": episode,
            "source_id": source_id,
            "multimodal_task_id": task.get("task_id"),
            "beat_id": metadata.get("beat_id"),
            "source_qa": "ALLOW_WEAK_POSTCHECK_NOT_FULL_VISUAL_PASS" if weak_admission else "PASS_OBJECTIVE_AND_AI_REVIEW",
            "visual_replacement_only": silent,
            "audio_source_preserved": silent,
            "source_review_batches": [str(_abs(path)) for path in review_results],
        }
        if weak_admission:
            clip_metadata['policy_admission'] = weak_rows[source_id]
            clip_metadata['policy_admission_path'] = str(_abs(weak_admission))
            clip_metadata['policy_admission_sha256'] = sha256(_abs(weak_admission))
        if measured_edit is not None:
            measured_edit["applied_to_project"] = True
            clip_metadata["measured_edit"] = measured_edit
        if clip_metadata_editorial is not None:
            clip_metadata["editorial_keep"] = clip_metadata_editorial
        if tail_trim is not None:
            clip_metadata["dialogue_tail_trim"] = tail_trim
        if head_trim is not None:
            clip_metadata["dialogue_head_trim"] = head_trim
        video_clips.append({
            "id": f"{episode}-{source_id}-VIDEO",
            "source": str(source),
            "start": round(cursor, 6),
            "in": source_in,
            "duration": duration,
            "metadata": clip_metadata,
        })
        audio_clips.append({
            "id": f"{episode}-{source_id}-AUDIO",
            "source": str(audio_source),
            "start": round(cursor, 6),
            "in": source_in,
            "duration": duration,
            "volume": 0.78,
            "metadata": {
                "source_id": source_id,
                "multimodal_task_id": audio_task.get("task_id"),
                "beat_id": metadata.get("beat_id"),
                "dialogue_lines": dialogue_lines,
                "expected_text": expected_text,
                "audio_origin": "NATIVE_MULTIMODAL_SOURCE",
                "dialogue_classification": "SPEAKING" if expected_text.strip() else "NON_SPEAKING",
                "reused_for_silent_visual": silent,
            },
        })
        admissions.append({
            "source_id": source_id,
            "video_path": str(source),
            "video_sha256": task.get("sha256") or sha256(source),
            "audio_path": str(audio_source),
            "audio_sha256": audio_task.get("sha256") or sha256(audio_source),
            "silent_visual_replacement": silent,
            "status": "PASS",
            **({"measured_edit": measured_edit} if measured_edit is not None else {}),
        })
        cursor += duration

    # CAMERA_GRAMMAR_V1 dialogue sound bridge / L-cut (S7 report, tools/dialogue_sound_bridge.py): the
    # speaker clip ends early, its audio is mixed back over the reaction picture after the render.
    bridges = None
    if dialogue_sound_bridge:
        try:
            from tools import dialogue_sound_bridge as _bridge
        except ModuleNotFoundError:
            import dialogue_sound_bridge as _bridge  # type: ignore
        bridges = _bridge.apply(video_clips, audio_clips,
                                json.loads(_abs(dialogue_sound_bridge).read_text(encoding="utf-8")))
        cursor = sum(float(clip["duration"]) for clip in video_clips)

    project_path = _abs(out_project)
    admission_path = _abs(out_admission)
    output_path = _abs(output_video)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    admission_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {
            "episode": episode,
            "status": "STANDARD_STORYBOARD_AGENTCUT_NOT_FINAL",
            "source_review_batches": [str(_abs(path)) for path in review_results],
            "sound_design_contract": {
                "required_layers": ["DIALOGUE", "FOLEY", "AMBIENCE", "SFX"],
                "source_track_ids": [f"{episode}_NATIVE_AUDIO"],
            },
            "no_padding": True,
            "runtime_seconds": round(cursor, 6),
            "change_scope": "Assemble all admitted storyboard slots; silent visual repairs reuse the latest non-silent source audio for the same slot.",
        },
        "output": {
            "path": str(output_path),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "audioSampleRate": 48000,
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True,
            "limiter": True,
            "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 3.0,
            "loudnessTargetLufs": -16,
            "loudnessRangeLu": 11,
            "maxClippedSamples": 0,
            "sampleRateHz": 48000,
        },
        "timeline": {
            "videoTracks": [{"id": f"{episode}_STANDARD_STORYBOARD_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": f"{episode}_NATIVE_AUDIO", "clips": audio_clips}],
            "subtitleTracks": [],
        },
    }
    if bridges is not None:
        project["metadata"]["dialogue_sound_bridge"] = {"report": str(_abs(dialogue_sound_bridge)),
                                                        "bridges": bridges}
    binding = apply_audio_profile_binding(
        project,
        generation_contract_payload,
        contract_path=generation_contract_path,
    )
    binding_failures = validate_audio_profile_binding(project)
    if binding_failures:
        raise ValueError(f"audio profile automatic binding failed: {binding_failures}")
    profile_failures = validate_audio_profile(project)
    if profile_failures:
        raise ValueError(f"audio profile contract failed: {profile_failures}")
    sound_report = evaluate_sound_cues(project, root=ROOT)
    if sound_report["status"] != "PASS":
        raise ValueError(f"sound cue contract failed: {sound_report['failures']}")
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    admission_path.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_agentcut_admission.v1",
        "episode": episode,
        "status": "PASS",
        "review_results": [str(_abs(path)) for path in review_results],
        **({"weak_admission": str(_abs(weak_admission)),
            "weak_admission_sha256": sha256(_abs(weak_admission))} if weak_admission else {}),
        "project": str(project_path),
        "output": str(output_path),
        "runtime_seconds": round(cursor, 6),
        "audio_profile_binding": binding,
        "sources": admissions,
    }, ensure_ascii=False, indent=2) + "\n")
    return {"status": "PASS", "episode": episode, "slots": len(admissions), "runtime_seconds": round(cursor, 6), "project": str(project_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--receipt", action="append", required=True)
    parser.add_argument("--review-result", action="append", default=[])
    parser.add_argument("--weak-admission", help="Explicit hash-bound weak policy admission; does not fabricate AI review PASS")
    parser.add_argument("--out-project", required=True)
    parser.add_argument("--out-admission", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--expected-slots", type=int, required=True)
    parser.add_argument("--generation-contract", required=True)
    parser.add_argument("--measured-edit-constraints", help="Optional SHA-bound observed-dialogue source intervals; explicitly rebases following clips")
    parser.add_argument("--dialogue-tail-trim", help="Optional S7 dialogue tail-trim report (CAMERA_GRAMMAR_V1): cut each trimmed unit at its kept_seconds")
    parser.add_argument("--dialogue-head-trim", help="Optional S7 dialogue head-trim report (CAMERA_GRAMMAR_V1): start each trimmed unit at its head_cut_seconds")
    parser.add_argument("--dialogue-sound-bridge", help="Optional S7 dialogue sound-bridge report (CAMERA_GRAMMAR_V1): L-cut the speaker picture before a silent reaction unit")
    args = parser.parse_args()
    print(json.dumps(build(
        args.episode,
        args.receipt,
        args.review_result,
        args.out_project,
        args.out_admission,
        args.output_video,
        args.expected_slots,
        args.generation_contract,
        args.measured_edit_constraints,
        args.weak_admission,
        args.dialogue_tail_trim,
        args.dialogue_sound_bridge,
        dialogue_head_trim=args.dialogue_head_trim,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
