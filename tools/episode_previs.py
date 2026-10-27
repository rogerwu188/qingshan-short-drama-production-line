#!/usr/bin/env python3
"""Zero-credit episode previs: see a scene's timing before anything is paid for.

Plan §4.  Built only from artefacts the line already has — the generation
contract, the video-unit grouping plan, keyframes that already exist, and
dialogue audio that already exists.  It never calls an image, video, voice or
VLM provider.

What it is NOT: a cut, or evidence that an action, an identity or a lip sync
works.  A previs PASS means "the plan is internally consistent enough to go on
to production", nothing more.

Two outputs, kept separate on purpose:
  * machine checks — objective contract conflicts.  These block.
  * director review — subjective questions for a human/agent reviewer.  These
    never block; after MAX_REVIEW_ROUNDS rounds anything left is ADVISORY.

Durations are labelled with their source.  A dialogue length computed from a
character count is ESTIMATED and is never reported as MEASURED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.episode_previs.v1"
MAX_REVIEW_ROUNDS = 2
DEFAULT_CHARS_PER_SECOND = 4.5
GAP_TOLERANCE_SECONDS = 0.05
_POLICY = Path(__file__).resolve().parents[1] / "configs" / "EPISODE_PREVIS_V1.json"
POLICY_PATH = _POLICY


def gate_active(episode: str, *, contract: dict[str, Any] | None = None) -> bool:
    """Whether the previs gate applies to this episode.

    Off unless the episode is listed in configs/EPISODE_PREVIS_V1.json (or
    reaches its enabled_from_episode) or the contract opts in by declaring
    previs_policy=EPISODE_PREVIS_V1.  Episodes already in production keep the
    locked behaviour byte-for-byte until someone lists them.
    """
    declared = str((contract or {}).get("previs_policy") or "").strip().upper()
    if declared == "EPISODE_PREVIS_V1":
        return True
    policy = policy_settings()
    match = re.match(r"(E\d+)", str(episode or "").upper())
    if not match:
        return False
    if match.group(1) in {str(v).upper() for v in policy.get("enabled_episodes") or []}:
        return True
    start = policy.get("enabled_from_episode")
    if isinstance(start, str) and re.fullmatch(r"E\d+", start.upper()):
        return int(match.group(1)[1:]) >= int(start[1:])
    return False


def policy_settings() -> dict[str, Any]:
    """The active policy body, or the in-code defaults when no file is present."""
    try:
        return json.loads(_POLICY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


#: Plan §3: the questions a scene's director intent answers.  Read when the
#: contract declares them; never invented when it does not.
SCENE_INTENT_FIELDS = (
    "scene_goal", "information_change", "character_goal_and_obstacle",
    "dramatic_beats", "attention_targets", "visible_audible_evidence", "scene_end_state",
)

DIRECTOR_QUESTIONS = (
    ("scene_readable", "观众能否理解这一场发生了什么？"),
    ("no_redundant_shots", "连续镜头是否在重复传递同一个信息？"),
    ("reactions_have_purpose", "反应镜头是否有明确的反应？"),
    ("cuts_preserve_meaning", "切点是否切断了理解所需的对白或动作？"),
    ("combat_readable", "打斗是否有可理解的攻防与结果，而不是只堆姿态？"),
    ("static_dialogue_attention", "连续静态对话是否缺乏合理的注意力变化？"),
)

REVIEW_SCHEMA = SCHEMA + ".director_review_receipt"


def sequence_digest(previs: dict[str, Any]) -> str:
    """Hash of exactly what a reviewer looked at: the shot timeline and the
    adjacent-boundary projection.  Excludes director_review, gate and advisories,
    which change on every run without the sequence itself changing — hashing
    those would fail a review that is still valid and never catch the case that
    matters (CC_H3 audit 2026-10-26 §四-缺口D: receipt_sha256 hashed the OUTPUT
    file, not an input snapshot, so nothing bound a review to the sequence
    version it actually read).
    """
    material = {"timeline": previs.get("timeline") or [], "boundaries": previs.get("boundaries") or []}
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def review_receipt_path(directory: Path, episode: str, stage: str) -> Path:
    return Path(directory) / f"{episode}_PREVIS_REVIEW_{stage}.json"


def submitted_review_count(directory: Path, episode: str, stage: str,
                           sequence_digest_value: str | None = None) -> int:
    """How many ACCEPTED director reviews exist for this episode's previs stage.

    A receipt only counts when it names a reviewer, answers every question of the
    round it claims, and (when ``sequence_digest_value`` is given) its own
    ``sequence_digest`` still equals the current one.  A stale receipt bound to a
    since-changed timeline or boundary set does not count — the sequence changed,
    so the review no longer describes it.
    """
    path = review_receipt_path(directory, episode, stage)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict) or payload.get("schema") != REVIEW_SCHEMA:
        return 0
    rounds = payload.get("rounds")
    if not isinstance(rounds, list):
        return 0
    accepted = 0
    for row in rounds:
        if not isinstance(row, dict) or not str(row.get("reviewer") or "").strip():
            continue
        if sequence_digest_value is not None and row.get("sequence_digest") != sequence_digest_value:
            continue
        answers = row.get("answers") or {}
        if not isinstance(answers, dict) or not answers:
            continue
        missing = [qid for qid, _ in DIRECTOR_QUESTIONS if qid not in answers]
        if missing:
            continue
        accepted += 1
    return accepted


def _spoken(text: str) -> str:
    value = re.sub(r"^[^：:]{1,12}[：:]", "", str(text or "").strip())
    return re.sub(r"[\s\W_]+", "", value)


def estimate_dialogue_seconds(text: str, chars_per_second: float) -> float:
    return round(len(_spoken(text)) / max(chars_per_second, 0.1), 3)


def probe_seconds(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return round(float(out), 3)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def build_previs(
    contract: dict[str, Any],
    grouping: dict[str, Any] | None = None,
    *,
    keyframe_dir: Path | None = None,
    dialogue_audio: dict[str, Path] | None = None,
    chars_per_second: float | None = None,
) -> dict[str, Any]:
    """Assemble the previs timeline and run every machine check.  Pure apart from probing audio."""
    cps = float(chars_per_second or (contract.get("pacing") or {}).get("chars_per_second")
                or DEFAULT_CHARS_PER_SECOND)
    shots = list(contract.get("shots") or [])
    scenes = {s.get("scene_id"): s for s in contract.get("scene_states") or []}
    registry = {str(e.get("character_id")) for e in contract.get("character_entities") or []}
    units = list((contract.get("audio_contract") or {}).get("dialogue_units") or [])
    try:
        from tools import voice_over_narration as _vo
    except ImportError:  # direct execution from tools/
        import voice_over_narration as _vo  # type: ignore
    voice_over_ids = _vo.voice_over_character_ids(contract.get("character_entities") or [])
    audio = dialogue_audio or {}
    failures: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []

    def fail(code: str, ref: str, detail: str = "") -> None:
        failures.append({"code": code, "ref": ref, "detail": detail})

    # dialogue per shot, in authored order
    by_shot: dict[str, list[dict[str, Any]]] = {}
    for index, unit in enumerate(units):
        by_shot.setdefault(str(unit.get("shot_id")), []).append({**unit, "_index": index})

    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    seen_ids: set[str] = set()
    for shot in shots:
        sid = str(shot.get("shot_id") or "")
        if not sid:
            fail("SHOT_ID_MISSING", f"index:{len(timeline)}")
            continue
        if sid in seen_ids:
            fail("SHOT_DUPLICATED", sid)
        seen_ids.add(sid)
        duration = float(shot.get("target_seconds") or 0)
        if duration <= 0:
            fail("SHOT_DURATION_MISSING", sid)
        image = None
        if keyframe_dir is not None:
            matches = sorted(keyframe_dir.glob(f"{sid}-keyframe-v*.png"))
            image = str(matches[-1]) if matches else None
        lines = []
        speech_total = 0.0
        for unit in by_shot.get(sid, []):
            key = f"{sid}#{unit['_index']}"
            measured = probe_seconds(audio[key]) if key in audio else None
            seconds = measured if measured is not None else estimate_dialogue_seconds(unit.get("text", ""), cps)
            speaker = str(unit.get("speaker_id") or "")
            if speaker and speaker not in registry:
                fail("DIALOGUE_SPEAKER_NOT_REGISTERED", sid, speaker)
            lines.append({
                "speaker_id": speaker,
                "chars": len(_spoken(unit.get("text", ""))),
                "seconds": seconds,
                "duration_source": "MEASURED" if measured is not None else "ESTIMATED",
                "duration_basis": (str(audio[key]) if measured is not None
                                   else f"{cps:g} chars/s from contract pacing or default"),
            })
            if speaker in voice_over_ids:
                # V.O. narration may run across the following silent shots; the S2 window rule
                # (VOICE_OVER_WINDOW_TOO_SHORT) is its fit check, not this shot's own length
                lines[-1]["voice_over"] = True
                continue
            speech_total += seconds
        if duration > 0 and speech_total > duration + GAP_TOLERANCE_SECONDS:
            # Plan §4.2.2: the dialogue cannot fit the shot it is assigned to.
            # Flag it; never trim speech or stretch the shot silently.
            fail("DIALOGUE_DOES_NOT_FIT_SHOT", sid,
                 f"speech {speech_total:.2f}s > shot {duration:.2f}s")
        for cast in (shot.get("prompt_spec") or {}).get("cast") or []:
            cid = str(cast.get("character_id") or "")
            if cid and registry and cid not in registry:
                fail("CAST_ID_NOT_REGISTERED", sid, cid)
        timeline.append({
            "shot_id": sid,
            "scene_id": shot.get("scene_id"),
            "start": round(cursor, 3),
            "duration": duration,
            "visual": image or "PLACEHOLDER_CARD",
            "visual_source": "EXISTING_KEYFRAME" if image else "PLACEHOLDER",
            "dialogue": lines,
        })
        cursor += duration

    # §4.2.1: every authored line appears once, unless a repeat is declared.
    spoken_seen: dict[str, str] = {}
    for unit in units:
        text = _spoken(unit.get("text", ""))
        if len(text) < 2:
            continue
        if text in spoken_seen and not unit.get("repeat_reason"):
            fail("DIALOGUE_REPEATED_WITHOUT_REASON", str(unit.get("shot_id")),
                 f"first in {spoken_seen[text]}")
        spoken_seen.setdefault(text, str(unit.get("shot_id")))
        if str(unit.get("shot_id")) not in seen_ids:
            fail("DIALOGUE_SHOT_MISSING", str(unit.get("shot_id")))

    # §4.2.3: grouping covers every shot exactly once, in order, with no gap.
    if grouping:
        order = [sid for unit in grouping.get("units") or [] for sid in unit.get("editorial_shot_ids") or []]
        dupes = sorted({sid for sid in order if order.count(sid) > 1})
        for sid in dupes:
            fail("SHOT_IN_TWO_UNITS", sid)
        missing = [sid for sid in seen_ids if sid not in set(order)]
        for sid in sorted(missing):
            fail("SHOT_NOT_IN_ANY_UNIT", sid)
        expected = [row["shot_id"] for row in timeline if row["shot_id"] in set(order)]
        compact = list(dict.fromkeys(order))
        if compact != expected:
            fail("UNIT_ORDER_DIFFERS_FROM_SHOT_ORDER", "grouping")

    # §3: director intent — reported, never invented, never blocking.
    for scene_id, scene in scenes.items():
        intent = scene.get("scene_intent") or {}
        absent = [field for field in SCENE_INTENT_FIELDS if not intent.get(field)]
        if absent:
            advisories.append({"code": "SCENE_INTENT_NOT_DECLARED", "ref": scene_id,
                               "detail": ",".join(absent)})

    dialogue_by_shot = {row["shot_id"]: row["dialogue"] for row in timeline if row["dialogue"]}
    boundaries = build_boundaries(grouping, timeline, dialogue_by_shot)

    result = {
        "schema": SCHEMA,
        "episode": contract.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "scope": "ZERO_CREDIT_PREVIS_NOT_A_CUT_NOT_IDENTITY_OR_LIPSYNC_EVIDENCE",
        "chars_per_second": cps,
        "total_seconds": round(cursor, 3),
        "shot_count": len(timeline),
        "estimated_dialogue_lines": sum(1 for r in timeline for l in r["dialogue"]
                                        if l["duration_source"] == "ESTIMATED"),
        "measured_dialogue_lines": sum(1 for r in timeline for l in r["dialogue"]
                                       if l["duration_source"] == "MEASURED"),
        "machine_failures": failures,
        "advisories": advisories,
        "timeline": timeline,
        "boundaries": boundaries,
    }
    result["sequence_digest"] = sequence_digest(result)
    return result


def _attempt(fn, **kwargs):
    """Run a validator previs only READS; its own PASS/FAIL stays load-bearing
    wherever it already runs (S2 grouping gate etc).  A raise here becomes a
    reported boundary problem, never a crash and never a second copy of the
    validator's rules."""
    try:
        return fn(**kwargs), None
    except Exception as exc:  # noqa: BLE001 — reported, not re-raised
        return None, str(exc)


def _dialogue_crosses_cut(previous_shot_ids: list[str], current_shot_ids: list[str],
                          dialogue_by_shot: dict[str, list[dict[str, Any]]]) -> bool:
    """A line that starts in the outgoing shot and has no matching start in the
    incoming shot is understood to run across the cut (sound bridge territory)."""
    if not previous_shot_ids or not current_shot_ids:
        return False
    tail_has_line = bool(dialogue_by_shot.get(previous_shot_ids[-1]))
    head_has_line = bool(dialogue_by_shot.get(current_shot_ids[0]))
    return tail_has_line and not head_has_line


def build_boundaries(grouping: dict[str, Any] | None, timeline: list[dict[str, Any]],
                     dialogue_by_shot: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Project the existing camera / transition / action-continuity contracts onto
    the REAL clip-order adjacency, so a reviewer sees what actually joins to what.

    CC_H3 audit 2026-10-26 §四-缺口A: a previs timeline with only shot id, start,
    duration and a static image cannot show whether two shots cut together with
    any rhythm.  This reuses grouped_transition_contract, grouped_camera_contract
    and unit_action_continuity_contract exactly as written — no second camera or
    continuity rule set — and reports NOT_APPLICABLE wherever the unit itself
    never declared the optional structured fields (action_event_contract is
    opt-in; absence is legal, per that module's own contract).
    """
    units = list((grouping or {}).get("units") or [])
    if len(units) < 2:
        return []
    try:
        from tools import grouped_transition_contract as _gtc
        from tools import unit_action_continuity_contract as _uac
    except ImportError:
        from grouped_transition_contract import boundary_id as _bid  # type: ignore
        _gtc = None
        _uac = None
    shot_index = {row["shot_id"]: index for index, row in enumerate(timeline)}
    boundaries: list[dict[str, Any]] = []
    for index in range(1, len(units)):
        previous, current = units[index - 1], units[index]
        prev_id = str(previous.get("unit_id") or f"unit-{index}")
        curr_id = str(current.get("unit_id") or f"unit-{index + 1}")
        prev_shots = list(previous.get("editorial_shot_ids") or [])
        curr_shots = list(current.get("editorial_shot_ids") or [])
        row: dict[str, Any] = {
            "boundary_id": (_gtc.boundary_id(prev_id, curr_id) if _gtc else f"BND-{prev_id}-{curr_id}"),
            "from_unit_id": prev_id, "to_unit_id": curr_id,
            "from_shot_id": prev_shots[-1] if prev_shots else None,
            "to_shot_id": curr_shots[0] if curr_shots else None,
            "from_end_seconds": None, "to_start_seconds": None,
        }
        if row["from_shot_id"] in shot_index:
            tail = timeline[shot_index[row["from_shot_id"]]]
            row["from_end_seconds"] = round(tail["start"] + tail["duration"], 3)
        if row["to_shot_id"] in shot_index:
            row["to_start_seconds"] = timeline[shot_index[row["to_shot_id"]]]["start"]

        transition_contract = current.get("transition_contract")
        if transition_contract and _gtc is not None:
            normalized, error = _attempt(
                _gtc.validate_transition_contract, contract=transition_contract,
                previous=previous, current=current)
            if error:
                row["transition"] = {"status": "DECLARED_BUT_INVALID", "error": error}
            else:
                row["transition"] = {
                    "status": "DECLARED", "cut_reason": normalized["cut_reason"],
                    "space_relation": normalized["space_relation"],
                    "transition_device": normalized["transition_device"],
                    "plot_motivation": normalized["plot_motivation"],
                    "visual_bridge": normalized["visual_bridge"],
                    "action_bridge": normalized["action_bridge"],
                    "sound_bridge": normalized["sound_bridge"],
                    "axis_strategy": normalized["axis_strategy"],
                    "new_information_for_viewer": normalized["plot_motivation"],
                }
        else:
            row["transition"] = {"status": "NOT_DECLARED",
                                 "reason": "unit carries no transition_contract"}

        prev_camera = previous.get("camera_plan") or {}
        curr_camera = current.get("camera_plan") or {}
        row["camera"] = {
            "from_end_framing": prev_camera.get("end_framing"),
            "from_motion": f"{prev_camera.get('motion_family')}:{prev_camera.get('motion_direction')}"
                           if prev_camera else None,
            "to_start_framing": curr_camera.get("start_framing"),
            "to_motion": f"{curr_camera.get('motion_family')}:{curr_camera.get('motion_direction')}"
                        if curr_camera else None,
        }

        if _uac is not None:
            verdict = _uac.evaluate(previous, current)
            row["action_continuity"] = {
                "status": verdict["status"], "event_id": verdict.get("event_id") or None,
                "phase": verdict.get("phase") or None,
                "failures": verdict.get("failures") or [],
            }
        else:
            row["action_continuity"] = {"status": "NOT_APPLICABLE", "failures": []}

        row["dialogue_crosses_cut"] = _dialogue_crosses_cut(prev_shots, curr_shots, dialogue_by_shot)
        boundaries.append(row)
    return boundaries


def director_review_request(previs: dict[str, Any], *, round_number: int,
                            prior_open: list[str] | None = None,
                            submitted_reviews: int | None = None) -> dict[str, Any]:
    """Issue a subjective review round, or close the loop after MAX_REVIEW_ROUNDS.

    The round budget counts SUBMITTED reviews, never stage invocations.  A stage
    that was merely re-run has not been reviewed, so it stays NOT_VERIFIED; before
    2026-10-26 the call count itself advanced the round, and the third bare run
    returned "2 rounds done" with no reviewer and no answers (audit §四-C).

    Round limits cover subjective questions only.  They never waive a machine
    failure, a budget guard or a transaction check — those stay in
    previs["machine_failures"] regardless of the round.
    """
    done = max(0, int(submitted_reviews)) if submitted_reviews is not None else 0
    machine_failures = previs.get("machine_failures") or []
    if done >= MAX_REVIEW_ROUNDS:
        return {
            "schema": SCHEMA + ".director_review",
            "status": "CLOSED_ADVISORY",
            "round": round_number,
            "submitted_reviews": done,
            "advisory_carried": list(prior_open or []),
            "machine_failure_count": len(machine_failures),
            "note": f"{MAX_REVIEW_ROUNDS} submitted review(s) done; remaining subjective items are "
                    "ADVISORY. No further round, no automatic regeneration.",
        }
    return {
        "schema": SCHEMA + ".director_review",
        "status": "REVIEW_REQUESTED" if done else "NOT_VERIFIED",
        "round": round_number,
        "submitted_reviews": done,
        "max_rounds": MAX_REVIEW_ROUNDS,
        "blocking": False,
        "machine_failure_count": len(machine_failures),
        "questions": [{"id": qid, "question": text, "answer": None} for qid, text in DIRECTOR_QUESTIONS],
        "rule": "Edit only the shots a finding names and their dependants; re-run previs.",
    }


def render_previs(previs: dict[str, Any], out: Path, *, renderer: Path, width: int = 720,
                  height: int = 1280, fps: int = 24) -> Path:
    """Optional: stills/placeholder cards -> clips -> the existing portable timeline renderer."""
    work = Path(tempfile.mkdtemp(prefix="previs_"))
    video, audio = [], []
    for row in previs["timeline"]:
        clip = work / f"{row['shot_id']}.mp4"
        src = row["visual"]
        image_input = (["-loop", "1", "-i", src] if src != "PLACEHOLDER_CARD"
                       else ["-f", "lavfi", "-i", f"color=c=0x202020:s={width}x{height}"])
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", *image_input,
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", f"{row['duration']}", "-vf", f"scale={width}:{height},fps={fps},format=yuv420p",
            "-shortest", "-c:v", "libx264", "-c:a", "aac", str(clip),
        ], check=True)
        video.append({"source": str(clip), "start": row["start"], "duration": row["duration"]})
        audio.append({"source": str(clip), "start": row["start"], "duration": row["duration"]})
    project = work / "previs_timeline.json"
    # The shape tools/render_portable_timeline.py reads: one video track and
    # one matching native-audio track under timeline.
    project.write_text(json.dumps({
        "output": {"width": width, "height": height, "fps": fps},
        "timeline": {"videoTracks": [{"clips": video}], "audioTracks": [{"clips": audio}]},
    }), encoding="utf-8")
    subprocess.run(["python3", str(renderer), str(project), "--output", str(out)], check=True)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--grouping-plan", type=Path)
    parser.add_argument("--keyframe-dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-round", type=int, default=1)
    parser.add_argument("--render", type=Path, help="optional mp4 output via render_portable_timeline.py")
    args = parser.parse_args(argv)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    grouping = json.loads(args.grouping_plan.read_text(encoding="utf-8")) if args.grouping_plan else None
    previs = build_previs(contract, grouping, keyframe_dir=args.keyframe_dir)
    previs["director_review"] = director_review_request(previs, round_number=args.review_round)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(previs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.render:
        render_previs(previs, args.render, renderer=Path(__file__).with_name("render_portable_timeline.py"))
    print(json.dumps({k: previs[k] for k in ("status", "shot_count", "total_seconds",
                                             "estimated_dialogue_lines", "measured_dialogue_lines")}
                     | {"machine_failures": len(previs["machine_failures"]),
                        "advisories": len(previs["advisories"])}, ensure_ascii=False))
    return 0 if previs["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
