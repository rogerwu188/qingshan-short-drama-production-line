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

    return {
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
    }


def director_review_request(previs: dict[str, Any], *, round_number: int,
                            prior_open: list[str] | None = None) -> dict[str, Any]:
    """Issue a subjective review round, or close the loop after MAX_REVIEW_ROUNDS.

    Round limits cover subjective questions only.  They never waive a machine
    failure, a budget guard or a transaction check — those stay in
    previs["machine_failures"] regardless of the round.
    """
    if round_number > MAX_REVIEW_ROUNDS:
        return {
            "schema": SCHEMA + ".director_review",
            "status": "CLOSED_ADVISORY",
            "round": round_number,
            "advisory_carried": list(prior_open or []),
            "note": f"{MAX_REVIEW_ROUNDS} rounds done; remaining subjective items are ADVISORY. "
                    "No further round, no automatic regeneration.",
        }
    return {
        "schema": SCHEMA + ".director_review",
        "status": "REVIEW_REQUESTED",
        "round": round_number,
        "max_rounds": MAX_REVIEW_ROUNDS,
        "blocking": False,
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
