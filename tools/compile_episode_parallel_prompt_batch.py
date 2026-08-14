#!/usr/bin/env python3
"""Compile a reviewed beat sheet into batch image and multimodal-video prompt contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from shot_duration_policy import plan_dialogue_duration
    from action_xuanhuan_script_gate import validate as validate_action_xuanhuan
    from giggle_api_client import STANDARD_VIDEO_MODEL
    from storyboard_sheet_gate import requires_storyboard_sheet_gate, validate_gate_report, validate_plan
    from video_prompt_action_density_gate import require_action_timeline
except ModuleNotFoundError:  # Imported as tools.compile_episode_parallel_prompt_batch in tests.
    from tools.shot_duration_policy import plan_dialogue_duration
    from tools.action_xuanhuan_script_gate import validate as validate_action_xuanhuan
    from tools.giggle_api_client import STANDARD_VIDEO_MODEL
    from tools.storyboard_sheet_gate import requires_storyboard_sheet_gate, validate_gate_report, validate_plan
    from tools.video_prompt_action_density_gate import require_action_timeline


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}={item}" for key, item in value.items())
    return str(value or "")


def dialogue_duration_seconds(text: str) -> int:
    """Compatibility wrapper around the production shot-duration policy."""
    return int(plan_dialogue_duration(text, "medium", "dialogue")["duration_seconds"])


def build_dialogue_action_timeline(
    *,
    duration_seconds: int,
    speaker: str,
    exact_dialogue: str,
    action_spine: object,
    new_information: object,
    payload: object,
) -> list[dict]:
    """Build <=3s playable phases from script facts, without static padding."""
    segment_count = max(2, (duration_seconds + 2) // 3)
    segment_length = duration_seconds / segment_count
    action = compact(action_spine) or "the named speaker turns toward the script-locked target"
    info = compact(new_information) or compact(payload) or "the scripted evidence changes the listener's understanding"
    rows = []
    for index in range(segment_count):
        start = round(index * segment_length, 3)
        end = duration_seconds if index == segment_count - 1 else round((index + 1) * segment_length, 3)
        if index == 0:
            actions = [f"{speaker} initiates the physical beat: {action}", f"{speaker} begins the exact line: {exact_dialogue}"]
            state_change = "The speaker's body and gaze commit to the action target before the line advances."
        elif index == segment_count - 1:
            actions = [f"{speaker} completes the exact line without paraphrase", f"The physical beat reaches its scripted result: {action}"]
            state_change = f"The shot ends immediately after this new information lands: {info}"
        else:
            actions = [f"{speaker} continues the exact line at native pace", f"The listener changes gaze, hand position, or distance in causal response to: {info}"]
            state_change = "The listener's visible response advances while the speaker continues, with no held pose."
        rows.append({
            "start_seconds": start,
            "end_seconds": end,
            "actions": actions,
            "state_change": state_change,
            "action_budget_seconds": round(end - start, 3),
        })
    return rows


def scene_authorities(sheet: dict, state: dict) -> dict[str, dict]:
    variety = sheet.get("scene_variety") or {}
    authorities: dict[str, dict] = {}
    for locked_scene in state.get("scene_state") or []:
        authority = {
            "scene_id": locked_scene.get("scene_id"),
            "location": locked_scene.get("location") or variety.get("location") or variety.get("primary_location") or "SCRIPT_LOCKED_LOCATION",
            "time_of_day": locked_scene.get("time_of_day") or variety.get("time_of_day") or "SCRIPT_LOCKED_TIME",
            "weather": locked_scene.get("weather") or variety.get("weather") or "SCRIPT_LOCKED_WEATHER",
            "palette": locked_scene.get("palette") or variety.get("palette") or "SCRIPT_LOCKED_PALETTE",
            "location_prompt_tokens": locked_scene.get("location_prompt_tokens") or [],
        }
        for beat_id in locked_scene.get("beats") or []:
            authorities[beat_id] = authority
    return authorities


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True, type=Path)
    parser.add_argument("--scene-state", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--reference-map", type=Path)
    parser.add_argument("--batch-output-dir")
    parser.add_argument("--qa-dir")
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--storyboard-plan", type=Path)
    parser.add_argument("--storyboard-sheet-gate-report", type=Path)
    args = parser.parse_args()

    sheet = json.loads(args.sheet.read_text(encoding="utf-8"))
    state = json.loads(args.scene_state.read_text(encoding="utf-8"))
    episode = sheet.get("episode")
    lines = sheet.get("dialogue_draft") or []
    beats = sheet.get("structure") or []
    if not episode or not lines or not beats:
        raise SystemExit("sheet requires episode, dialogue_draft, and structure")
    missing_payload = [
        line.get("dia_id", "UNKNOWN")
        for line in lines
        if not (line.get("payload") or line.get("function"))
    ]
    if missing_payload:
        raise SystemExit(f"anti-padding payload missing: {','.join(missing_payload)}")
    action_xuanhuan_gate = validate_action_xuanhuan(sheet)
    if action_xuanhuan_gate["status"] != "PASS":
        failed = ",".join(row["check"] for row in action_xuanhuan_gate["failures"])
        raise SystemExit(f"action-xuanhuan script gate failed: {failed}")
    storyboard_plan = {}
    storyboard_gate = {"status": "NOT_REQUIRED", "failures": []}
    if requires_storyboard_sheet_gate(episode):
        if not args.storyboard_plan or not args.storyboard_sheet_gate_report:
            raise SystemExit("storyboard-sheet plan and final gate report are required for E26+")
        storyboard_plan = json.loads(args.storyboard_plan.read_text(encoding="utf-8"))
        report = json.loads(args.storyboard_sheet_gate_report.read_text(encoding="utf-8"))
        plan_gate = validate_plan(storyboard_plan)
        report_gate = validate_gate_report(report, episode)
        failures = plan_gate["failures"] + report_gate["failures"]
        storyboard_gate = {"status": "PASS" if not failures else "FAIL", "failures": failures}
        if failures:
            failed = ",".join(str(row.get("check")) for row in failures)
            raise SystemExit(f"storyboard-sheet gate failed: {failed}")
    storyboard_by_beat = {
        str(row.get("beat_id")): row for row in storyboard_plan.get("episode_rows") or []
    }
    fight_sequence = storyboard_plan.get("fight_sequence") or {}

    authority_by_beat = scene_authorities(sheet, state)
    missing_scene_beats = [beat["beat_id"] for beat in beats if beat["beat_id"] not in authority_by_beat]
    if missing_scene_beats:
        raise SystemExit(f"scene authority missing beats: {','.join(missing_scene_beats)}")
    reference_map = {}
    if args.reference_map:
        reference_map = json.loads(args.reference_map.read_text(encoding="utf-8")).get("beats") or {}
        missing_beats = [beat["beat_id"] for beat in beats if beat["beat_id"] not in reference_map]
        if missing_beats:
            raise SystemExit(f"reference binding missing beats: {','.join(missing_beats)}")
        missing_files = [
            str(path)
            for paths in reference_map.values()
            for path in (paths if isinstance(paths, list) else [paths])
            if not Path(path).expanduser().is_file()
        ]
        if missing_files:
            raise SystemExit(f"reference files missing: {','.join(missing_files)}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = args.out_dir / "images"
    video_dir = args.out_dir / "videos"
    image_dir.mkdir(exist_ok=True)
    video_dir.mkdir(exist_ok=True)
    image_tasks = []
    video_tasks = []

    for beat in beats:
        beat_id = beat["beat_id"]
        authority = authority_by_beat[beat_id]
        storyboard_row = storyboard_by_beat.get(beat_id) or {}
        storyboard_binding = (
            f"Storyboard binding: visual={compact(storyboard_row.get('visual'))}; "
            f"camera={compact(storyboard_row.get('camera'))}; technique={compact(storyboard_row.get('technique'))}; "
            f"composition={compact(storyboard_row.get('composition_signature'))}. "
        ) if storyboard_row else ""
        prompt = (
            f"{episode} {beat_id} script-locked cinematic keyframe, vertical 9:16. "
            "Create exactly one continuous photographic frame with one camera position and one decisive dramatic moment; no collage, panels, split screen, storyboard sheet, contact sheet, or inset image. "
            f"Location: {authority['location']}; time: {authority['time_of_day']}; weather: {authority['weather']}; "
            f"palette: {authority['palette']}. Beat: {beat.get('name', '')}. "
            f"Location binding: {compact(authority['location_prompt_tokens'])}. "
            f"Must show: {compact(beat.get('must_show'))}. New information: {compact(beat.get('new_information'))}. "
            f"Action spine: {compact(beat.get('action_spine'))}. Xuanhuan element: {compact(beat.get('xuanhuan_element'))}. "
            f"Power visualization: {compact(beat.get('power_visualization'))}. Payload delivery: {beat.get('payload_delivery')}. "
            f"{storyboard_binding}"
            "Preserve canonical identity, wardrobe, props, geography and script event. "
            "NEGATIVE_PROMPT: invented time, invented weather, rain, storm, readable text, subtitle, logo, watermark, extra character, unmotivated spectacle."
        )
        path = image_dir / f"{beat_id}.txt"
        path.write_text(prompt + "\n", encoding="utf-8")
        refs = reference_map.get(beat_id) or []
        if not isinstance(refs, list):
            refs = [refs]
        image_tasks.append({
            "task_key": f"{episode}-{beat_id}-IMAGE",
            "beat_id": beat_id,
            "scene_id": authority["scene_id"],
            "visual_zone": f"{beat_id}_KEYFRAME",
            "prompt_file": str(path),
            "reference_images": refs,
            "status": "REFERENCE_BOUND_REUSE_OR_REROLL" if refs else "PENDING_REFERENCE_BINDING",
        })

    beat_map = {beat["beat_id"]: beat for beat in beats}
    for line in lines:
        dia_id = line["dia_id"]
        beat = beat_map.get(line.get("beat_id"), {})
        authority = authority_by_beat[line.get("beat_id")]
        storyboard_row = storyboard_by_beat.get(str(line.get("beat_id"))) or {}
        duration_plan = plan_dialogue_duration(
            line["text"],
            str(line.get("pace") or "medium"),
            str(line.get("function") or line.get("payload") or "dialogue"),
            performance_context=" ".join(
                compact(value)
                for value in (
                    beat.get("action_spine"),
                    beat.get("xuanhuan_element"),
                    beat.get("power_visualization"),
                    storyboard_row.get("camera"),
                    storyboard_row.get("technique"),
                    storyboard_row.get("dialogue_sfx"),
                    fight_sequence.get("shots") if str(fight_sequence.get("beat_id")) == str(line.get("beat_id")) else None,
                )
                if value
            ),
        )
        duration = int(duration_plan["duration_seconds"])
        payload = line.get("payload") or line.get("function")
        action_timeline = line.get("action_timeline") or build_dialogue_action_timeline(
            duration_seconds=duration,
            speaker=str(line["speaker"]),
            exact_dialogue=str(line["text"]),
            action_spine=beat.get("action_spine"),
            new_information=beat.get("new_information"),
            payload=payload,
        )
        action_density_gate = require_action_timeline(
            action_timeline,
            duration,
            source_id=dia_id,
        )
        refs = reference_map.get(line.get("beat_id")) or []
        if not isinstance(refs, list):
            refs = [refs]
        storyboard_binding = (
            f"Follow the approved storyboard blueprint exactly: visual={compact(storyboard_row.get('visual'))}; "
            f"camera={compact(storyboard_row.get('camera'))}; technique={compact(storyboard_row.get('technique'))}; "
            f"composition={compact(storyboard_row.get('composition_signature'))}. "
        ) if storyboard_row else ""
        fight_binding = ""
        if str(fight_sequence.get("beat_id")) == str(line.get("beat_id")):
            fight_binding = "Fight sequence: " + " ".join(
                f"Shot {shot.get('shot_no')} [{shot.get('phase')}] {shot.get('shot_size')}, {shot.get('camera')}, "
                f"{shot.get('action')}, SFX {shot.get('sfx')}, power {shot.get('power_visualization')}."
                for shot in fight_sequence.get("shots") or []
            ) + " "
        action_timeline_prompt = "Action timeline (every interval is playable and changes state): " + " ".join(
            f"{float(row['start_seconds']):.1f}-{float(row['end_seconds']):.1f}s: "
            f"{' / '.join(str(item) for item in row['actions'])}; result={row['state_change']}."
            for row in action_timeline
        ) + " "
        prompt = (
            f"Animate the supplied script-locked {episode} {line.get('beat_id')} still as a vertical 9:16 multimodal source. "
            f"Keep location {authority['location']}, time {authority['time_of_day']}, weather {authority['weather']}, and palette {authority['palette']} unchanged. "
            f"Location binding: {compact(authority['location_prompt_tokens'])}. "
            f"{line['speaker']} speaks exactly once in natural Mandarin: “{line['text']}” Only the named speaker talks; listeners react causally without dialogue. "
            f"Narrative function: {line.get('function', '')}; payload: {compact(payload)}; beat event: {compact(beat.get('new_information'))}. "
            f"Action spine: {compact(beat.get('action_spine'))}. Xuanhuan element: {compact(beat.get('xuanhuan_element'))}. "
            f"Power visualization: {compact(beat.get('power_visualization'))}. "
            f"{storyboard_binding}{fight_binding}{action_timeline_prompt}"
            f"Target one continuous {duration}-second shot; finish the exact line naturally without rushing or filler. "
            "Use native-speed human motion and native dialogue, practical sound effects, and scene ambience. "
            "NEGATIVE_PROMPT: No external BGM; do not invent moonlight, night, rain, weather, location, or events; no paraphrase, extra dialogue, slow motion, cyclic gesture, readable text, subtitle, caption, logo, or watermark."
        )
        path = video_dir / f"{dia_id}.txt"
        path.write_text(prompt + "\n", encoding="utf-8")
        video_tasks.append({
            "task_key": f"{episode}-{dia_id}-VIDEO",
            "tool_type": "video_generation",
            "source_id": dia_id,
            "dialogue_id": dia_id,
            "dia_id": dia_id,
            "beat_id": line.get("beat_id"),
            "scene_id": authority["scene_id"],
            "visual_zone": f"{line.get('beat_id')}_{dia_id}_DIALOGUE",
            "speaker": line["speaker"],
            "exact_dialogue": line["text"],
            "payload": payload,
            "payload_source": "payload" if line.get("payload") else "function",
            "duration_seconds": duration,
            "duration": duration,
            "duration_plan": duration_plan,
            "action_timeline": action_timeline,
            "action_density_gate": action_density_gate,
            "model": STANDARD_VIDEO_MODEL,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": str(path),
            "reference_images": refs,
            "status": "READY_FOR_PARALLEL_SUBMIT" if refs else "PENDING_REFERENCE_BINDING",
        })

    reviewed = str(sheet.get("review_status", "")).startswith("APPROVED")
    generation_allowed = bool(sheet.get("generation_allowed")) and reviewed
    manifest = {
        "schema": "qingshan.episode_parallel_prompt_batch.v1",
        "episode": episode,
        "source_sheet": str(args.sheet),
        "source_sheet_sha256": sha256(args.sheet),
        "scene_state": str(args.scene_state),
        "scene_state_sha256": sha256(args.scene_state),
        "scene_authority_by_beat": authority_by_beat,
        "status": (
            "READY_FOR_PARALLEL_SUBMIT"
            if generation_allowed and reference_map
            else "READY_FOR_REFERENCE_BINDING"
            if generation_allowed
            else "DRAFT_SUPERVISOR_REVIEW_PENDING"
        ),
        "submit_allowed": generation_allowed,
        "reference_map": str(args.reference_map) if args.reference_map else None,
        "submission_policy": {
            "images": "bind all ready beat references, then submit one concurrent batch",
            "videos": "bind all admitted stills, then submit all dialogue videos concurrently",
            "retry": "preserve passes and resubmit failed items only",
            "agentcut": "compile all admitted clips in one project and render once",
            "qa": "run all available machine reviews concurrently",
        },
        "anti_padding": {"payload_coverage": f"{len(lines)}/{len(lines)}", "padding_forbidden": True},
        "action_xuanhuan_gate": action_xuanhuan_gate,
        "storyboard_sheet_gate": storyboard_gate,
        "storyboard_sheet_plan": str(args.storyboard_plan) if args.storyboard_plan else None,
        "storyboard_sheet_gate_report": str(args.storyboard_sheet_gate_report) if args.storyboard_sheet_gate_report else None,
        "image_tasks": image_tasks,
        "video_tasks": video_tasks,
        "tasks": video_tasks if args.batch_output_dir and args.qa_dir else [],
        "scene_contract_ref": str(args.scene_state),
        "output_dir": args.batch_output_dir,
        "qa_dir": args.qa_dir,
        "max_retries": args.max_retries,
        "base_batch_note": "Submit every dialogue video for this episode in one fan-out; preserve passes and retry failed items only.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"episode": episode, "status": manifest["status"], "images": len(image_tasks), "videos": len(video_tasks), "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
