#!/usr/bin/env python3
"""Every cut must have a reason. Cutting to hit a metric is not a reason.

Authorization: `ROGER-20260718-NO-UNMOTIVATED-CUTS` — Roger, 2026-07-18:
「不改切的地方就别切，不能为了指标拼命切，搞得整个片子碎片化感非常严重」

This gate sits on the EDIT PROJECT, before render. The defect is an editing
decision, so it is caught where the decision is made rather than inferred from
the finished file afterwards.

What E19R V15 looked like when measured (`CL2X-295`):
  - 72 clips carrying 40 dialogue lines; the extra 32 are picture-only inserts
  - those inserts occupy 82.4s of 178.7s runtime = 46%
  - 47 of 71 seams flip between a speaking shot and a wordless insert, so the
    picture changes after almost every line
  - 43% of the insert shots are recycled images (vs 20% of dialogue shots);
    60% of all near-duplicate shots in the episode live in the inserts
  - `new_information` present on 0 of 72 clips: the narrative gate
    (CL2X-282 / SM-004) existed on paper and was never bound to the cut

Deliberately NOT a quota. An earlier draft capped "filler share at 20%", which
would have been another invented threshold of the kind that produced this mess.
The rule is motivation, not proportion: a cut with a substantiated reason is
always allowed, and a cut without one never is. Filler share is reported as a
diagnostic only.

Outputs `qingshan.cut_motivation_gate_result.v1`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# A cut may only exist for one of these reasons. Each carries an evidence
# requirement so the label cannot be applied as a rubber stamp.
#
# Roger, 2026-07-18: cuts are made 为了剧情、为了画面、为了审美. Story is not the
# only legitimate reason — composition and shot-size changes are first-class.
# But "it looks better" is unfalsifiable, so the picture reasons carry evidence
# requirements too: a size change must actually change size, and a composition
# call must be articulated in words that are not metric language.
CUT_REASONS: dict[str, str] = {
    # 剧情
    "SPEAKER_CHANGE": "speaker",  # the person talking changed
    "NEW_INFORMATION": "new_information",  # the frame shows something not yet seen
    "NEW_SPACE": "space_id",  # we moved to a different place
    "ACTION_BEAT": "action",  # a physical beat lands on the cut
    "REACTION_NEW_EMOTION": "emotion_delta",  # a reaction that changes the read
    "ESTABLISH_ONCE": "establishes",  # one establishing shot per new location
    # 画面 / 审美
    "SHOT_SIZE_CHANGE": "shot_size",  # push in / pull out; must actually differ
    "COMPOSITION_INTENT": "composition_note",  # a stated visual intention
}

# Shot sizes, coarse to tight. Used to verify a declared size change is real.
SHOT_SIZES = ("EWS", "WS", "MS", "MCU", "CU", "ECU")

# Fields the house already uses for continuity (DIRECTOR_COVERAGE_SCHEMA.md):
# A/B coverage inherits one scene_id / light_key / axis_line, with opposing
# eyelines. None of it was carried into the E19R cut.
CONTINUITY_FIELDS = ("scene_id", "light_key", "axis_line", "eyeline")


def required_cut_metadata(
    row: dict[str, Any], *, label: str = "clip", diagnostic: bool = False
) -> dict[str, Any]:
    """Return the explicit cut contract; never synthesize editorial intent.

    Strict by default: a plan that cannot state why a cut exists is rejected
    rather than handed a fabricated default.

    `diagnostic=True` audits plans that predate the contract. It records the
    absence instead of raising, because on historical material the absence IS
    the finding — the 2026-07-18 scan (E16/E17/E18R/E19R, 279 cuts, not one
    carrying a reason) is only possible in this mode, and that scan is what
    exposed two bugs in this very file. Never use it to admit a new plan.
    """
    source_metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    row = {**source_metadata, **{key: value for key, value in row.items() if value is not None}}
    reason = row.get("cut_reason")
    if reason not in CUT_REASONS:
        if diagnostic:
            return {"cut_reason_absent": True}
        raise ValueError(f"{label} requires an explicit closed-vocabulary cut_reason")
    note = str(row.get("cut_reason_note", ""))
    if METRIC_LANGUAGE.search(note):
        if diagnostic:
            return {"cut_reason": reason, "metric_driven_note": note}
        raise ValueError(f"{label} uses metric-driven cut language")
    missing = [field for field in CONTINUITY_FIELDS if not row.get(field)]
    if missing:
        if diagnostic:
            return {"cut_reason": reason, "continuity_fields_absent": missing}
        raise ValueError(f"{label} missing continuity fields: {', '.join(missing)}")
    result = {"cut_reason": reason, **{field: row[field] for field in CONTINUITY_FIELDS}}
    if note:
        result["cut_reason_note"] = note
    return result

# Cross-check ceiling for luma jumps between adjacent shots in one scene,
# inherited from the frozen baseline (相邻镜亮度跳变 ≤25).
MAX_LUMA_JUMP_SAME_SCENE = 25.0

# Anti-Goodhart: these may never appear in a cut justification. Cutting to move
# a number is the banned behaviour, so naming the number is self-incriminating.
METRIC_LANGUAGE = re.compile(
    r"(asl|平均镜头|镜头数|shot[_ ]?count|节奏|运动量|motion[_ ]?score|"
    r"凑|填(窗|时长|坑)|pacing|cadence|指标|"
    # "reaction punctuation" / "标点式" — cutting to punctuate a rhythm is the
    # same banned move in English. `insert_agentcut_short_cuts.py` defaulted to
    # `cadence_reaction_cut`, i.e. the tool's own fallback reason was "for
    # cadence", and all 8 E19R insert_reason values were "... punctuation".
    r"punctuation|标点|rhythm)",
    re.IGNORECASE,
)


def _clips(project: dict) -> list[dict]:
    """Return the editorial track's clips, in order.

    Multi-track projects were flattening incorrectly: E18R v10 carries an
    underlay track of ten 12.0s clips with empty metadata beneath the real
    38-clip cut, and flattening counted those underlay clips as editorial cuts
    and as picture inserts. The editorial track is the one whose clips actually
    carry metadata; ties fall to the longest track.
    """
    tracks = [track.get("clips", []) for track in project.get("timeline", {}).get("videoTracks", [])]
    tracks = [clips for clips in tracks if clips]
    if not tracks:
        return []
    if len(tracks) > 1:
        tracks.sort(key=lambda clips: (sum(1 for c in clips if c.get("metadata")), len(clips)), reverse=True)
    return sorted(tracks[0], key=lambda clip: float(clip.get("start", 0.0)))


def _is_insert(clip: dict) -> bool:
    """A picture-only insert: no character speaking in it.

    Deliberately not keyed on a `DIA-` prefix. E19R names its dialogue clips
    `DIA-001`, but E16's ordered EDL names them `D01`, and a prefix test
    silently reclassified all 62 of E16's speaking shots as inserts. Absence of
    any dialogue id is the portable signal.
    """
    meta = clip.get("metadata") or {}
    dialogue_id = meta.get("dialogue_id")
    return not (isinstance(dialogue_id, str) and dialogue_id.strip())


def _gate_viewing_consistency(clips: list[dict], metrics: dict | None, findings: list[dict]) -> None:
    """G9E — 不能破坏观看一致性.

    A/B coverage is generated correctly (one scene_id / light_key / axis_line,
    opposing eyelines — DIRECTOR_COVERAGE_SCHEMA.md), and the coverage
    preflight checks it at the generation-plan stage. But none of those fields
    were carried into the E19R cut, so the editor could place any A next to any
    B and nothing would object. These checks move continuity to where the cut
    is actually made.
    """
    missing_continuity: list[Any] = []
    light_breaks: list[dict] = []
    axis_breaks: list[dict] = []
    jump_cuts: list[dict] = []

    for index in range(1, len(clips)):
        prev_meta = clips[index - 1].get("metadata") or {}
        meta = clips[index].get("metadata") or {}
        shot_id = clips[index].get("id") or meta.get("shot_index") or index

        missing = [field for field in CONTINUITY_FIELDS if not meta.get(field)]
        if missing:
            missing_continuity.append({"shot": shot_id, "fields": missing})
            continue

        same_scene = prev_meta.get("scene_id") and prev_meta.get("scene_id") == meta.get("scene_id")
        if same_scene:
            # Lighting may not change inside one scene without a stated cause.
            if prev_meta.get("light_key") != meta.get("light_key") and not meta.get("light_change_justified"):
                light_breaks.append(
                    {"shot": shot_id, "from": prev_meta.get("light_key"), "to": meta.get("light_key")}
                )
            # Crossing the 180° line flips screen direction; it must be earned.
            if (
                prev_meta.get("axis_line")
                and meta.get("axis_line")
                and prev_meta["axis_line"] != meta["axis_line"]
                and not meta.get("line_cross_justified")
            ):
                axis_breaks.append(
                    {"shot": shot_id, "from": prev_meta.get("axis_line"), "to": meta.get("axis_line")}
                )
            # Shot/reverse must actually reverse: same eyeline on both sides of
            # a cut between different speakers reads as a continuity error.
            if (
                prev_meta.get("eyeline")
                and prev_meta.get("eyeline") == meta.get("eyeline")
                and prev_meta.get("speaker")
                and meta.get("speaker")
                and prev_meta["speaker"] != meta["speaker"]
            ):
                axis_breaks.append({"shot": shot_id, "same_eyeline": meta.get("eyeline")})
            # Same angle + same size = jump cut, the classic A-to-A stutter.
            if (
                prev_meta.get("coverage_group")
                and prev_meta.get("coverage_group") == meta.get("coverage_group")
                and prev_meta.get("shot_size")
                and prev_meta.get("shot_size") == meta.get("shot_size")
            ):
                jump_cuts.append(
                    {
                        "shot": shot_id,
                        "coverage_group": meta.get("coverage_group"),
                        "shot_size": meta.get("shot_size"),
                    }
                )

        # A declared size change that does not change size is not a reason.
        if meta.get("cut_reason") == "SHOT_SIZE_CHANGE":
            before, after = prev_meta.get("shot_size"), meta.get("shot_size")
            if before and after and before == after:
                findings.append(
                    {
                        "severity": "BLOCKER",
                        "gate": "G9E_VIEWING_CONSISTENCY",
                        "detail": "SHOT_SIZE_CHANGE declared but the size did not change",
                        "shot": shot_id,
                        "shot_size": after,
                    }
                )

    if missing_continuity:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9E_VIEWING_CONSISTENCY",
                "detail": "cut carries no continuity fields (scene_id/light_key/axis_line/eyeline); "
                "consistency cannot be checked at all",
                "count": len(missing_continuity),
                "of_cuts": len(clips) - 1,
                "examples": missing_continuity[:15],
            }
        )
    if light_breaks:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9E_VIEWING_CONSISTENCY",
                "detail": "light_key changes inside one scene without justification",
                "count": len(light_breaks),
                "examples": light_breaks[:10],
            }
        )
    if axis_breaks:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9E_VIEWING_CONSISTENCY",
                "detail": "screen direction breaks: axis crossed or shot/reverse fails to reverse",
                "count": len(axis_breaks),
                "examples": axis_breaks[:10],
            }
        )
    if jump_cuts:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9E_VIEWING_CONSISTENCY",
                "detail": "jump cut: same coverage group and same shot size across the cut",
                "count": len(jump_cuts),
                "examples": jump_cuts[:10],
            }
        )

    # Machine cross-check: declared continuity is still only a declaration.
    if metrics:
        continuity = metrics.get("video_continuity")
        luma = continuity.get("shot_luma") if isinstance(continuity, dict) else None
        if isinstance(luma, list) and len(luma) > 1:
            jumps = [
                {"shot": i + 1, "delta": round(luma[i + 1] - luma[i], 1)}
                for i in range(len(luma) - 1)
                if abs(luma[i + 1] - luma[i]) > MAX_LUMA_JUMP_SAME_SCENE
            ]
            if jumps:
                findings.append(
                    {
                        "severity": "BLOCKER",
                        "gate": "G9E_VIEWING_CONSISTENCY",
                        "detail": "measured luma jump across a cut exceeds baseline ceiling",
                        "ceiling": MAX_LUMA_JUMP_SAME_SCENE,
                        "count": len(jumps),
                        "examples": jumps[:10],
                    }
                )


def evaluate(project: dict, metrics: dict | None = None) -> dict[str, Any]:
    clips = _clips(project)
    findings: list[dict] = []

    if not clips:
        return {
            "schema": "qingshan.cut_motivation_gate_result.v1",
            "gate_status": "INVALID",
            "release_allowed": False,
            "findings": [{"severity": "INVALID", "gate": "G9_CUT_MOTIVATION", "detail": "no clips in project"}],
        }

    total = sum(float(clip.get("duration", 0.0)) for clip in clips)
    cut_reason_list = [
        {
            "shot": clip.get("id") or (clip.get("metadata") or {}).get("shot_index") or index,
            "cut_reason": (clip.get("metadata") or {}).get("cut_reason"),
            "continuity": {field: (clip.get("metadata") or {}).get(field) for field in CONTINUITY_FIELDS},
        }
        for index, clip in enumerate(clips)
    ]
    unmotivated: list[dict] = []
    unsubstantiated: list[dict] = []
    metric_driven: list[dict] = []

    # Clip 0 opens the episode; every clip after it is preceded by a cut.
    for index, clip in enumerate(clips[1:], start=1):
        meta = clip.get("metadata") or {}
        reason = meta.get("cut_reason")
        shot_id = clip.get("id") or meta.get("shot_index") or index

        if not isinstance(reason, str) or reason not in CUT_REASONS:
            unmotivated.append({"shot": shot_id, "start": clip.get("start"), "declared": reason})
            continue

        evidence_field = CUT_REASONS[reason]
        evidence = meta.get(evidence_field)
        if evidence is None or (isinstance(evidence, str) and not evidence.strip()):
            unsubstantiated.append({"shot": shot_id, "reason": reason, "missing_field": evidence_field})

        justification = " ".join(
            str(meta.get(key, "")) for key in ("cut_reason_note", "note", "justification", "new_information")
        )
        if METRIC_LANGUAGE.search(justification):
            metric_driven.append({"shot": shot_id, "justification": justification.strip()[:120]})

    if unmotivated:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9_CUT_MOTIVATION",
                "detail": "cuts with no declared reason — 不改切的地方就别切",
                "count": len(unmotivated),
                "of_cuts": len(clips) - 1,
                "examples": unmotivated[:15],
            }
        )
    if unsubstantiated:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9_CUT_MOTIVATION",
                "detail": "cut reason declared but its evidence field is empty; label without substance",
                "count": len(unsubstantiated),
                "examples": unsubstantiated[:15],
            }
        )

    # Inserts carry the heaviest burden: they interrupt without speaking, so
    # they must show something new, and may not be an image already used.
    inserts = [clip for clip in clips if _is_insert(clip)]
    insert_seconds = sum(float(clip.get("duration", 0.0)) for clip in inserts)
    # `insert_reason` is the field 8 E19R clips already use; accept it as an
    # equivalent carrier so existing practice is not penalised for naming.
    def _insert_is_justified(clip: dict) -> bool:
        meta = clip.get("metadata") or {}
        new_info = str(meta.get("new_information") or "").strip()
        insert_reason = str(meta.get("insert_reason") or "").strip()
        # A rhythm justification does not count. All 8 E19R `insert_reason`
        # values were "... reaction punctuation", and the tool's own fallback
        # was `cadence_reaction_cut` — cutting to punctuate a beat is exactly
        # the banned move, so it cannot also be the thing that excuses it.
        for text in (new_info, insert_reason):
            if text and not METRIC_LANGUAGE.search(text):
                return True
        return False

    silent_no_new = [
        clip.get("id") or (clip.get("metadata") or {}).get("shot_index")
        for clip in inserts
        if not _insert_is_justified(clip)
    ]
    metric_inserts = [
        clip.get("id") or (clip.get("metadata") or {}).get("shot_index")
        for clip in inserts
        if METRIC_LANGUAGE.search(str((clip.get("metadata") or {}).get("insert_reason") or ""))
    ]
    if metric_inserts:
        metric_driven.extend({"shot": shot, "justification": "insert_reason is a rhythm/metric statement"} for shot in metric_inserts)
    if silent_no_new:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9C_INSERT_MUST_ADD",
                "detail": "picture-only insert that adds nothing; this is filler",
                "count": len(silent_no_new),
                "of_inserts": len(inserts),
                "examples": silent_no_new[:15],
            }
        )

    # Cross-check against measured repetition when available: a recycled image
    # is the worst possible filler, because it interrupts with something the
    # audience has already seen.
    recycled_inserts = None
    if metrics:
        duplicates: set[int] = set()
        for cluster in (metrics.get("picture_repetition") or {}).get("non_adjacent_clusters", []):
            duplicates.update(cluster)
        levels = (metrics.get("audio") or {}).get("shot_levels") or []
        starts = [row.get("start") for row in levels]
        hits = []
        for clip in inserts:
            start = float(clip.get("start", 0.0))
            nearest = min(range(len(starts)), key=lambda i: abs((starts[i] or 0) - start)) if starts else None
            if nearest is not None and nearest in duplicates:
                hits.append(clip.get("id") or (clip.get("metadata") or {}).get("shot_index"))
        recycled_inserts = len(hits)
        if hits:
            findings.append(
                {
                    "severity": "BLOCKER",
                    "gate": "G9D_NO_RECYCLED_FILLER",
                    "detail": "insert reuses an image already shown; interrupting with a repeat",
                    "count": len(hits),
                    "examples": hits[:15],
                }
            )

    if metric_driven:
        findings.append(
            {
                "severity": "BLOCKER",
                "gate": "G9B_ANTI_GOODHART",
                "detail": "cut justified by a metric/rhythm — 不能为了指标拼命切",
                "count": len(metric_driven),
                "examples": metric_driven[:10],
            }
        )

    _gate_viewing_consistency(clips, metrics, findings)

    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    status = "REJECT_RECUT" if blockers else "PASS"

    return {
        "schema": "qingshan.cut_motivation_gate_result.v1",
        "gate_status": status,
        "release_allowed": status == "PASS",
        "cut_count": len(clips) - 1,
        "diagnostics": {
            "insert_count": len(inserts),
            "insert_runtime_pct": round(insert_seconds / total * 100.0, 2) if total else 0.0,
            "recycled_inserts": recycled_inserts,
            "note": "insert share is a diagnostic, NOT a threshold; motivation is the rule",
        },
        "cut_reason_list": cut_reason_list,
        "findings": findings,
        "rule": (
            "不改切的地方就别切，不能为了指标拼命切。A cut needs a substantiated reason; "
            "ASL and shot count are diagnostics, never targets, and may not justify a cut."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--metrics", help="final_cut_objective_metrics json for repetition cross-check")
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-status")
    args = parser.parse_args()

    project = json.loads(Path(args.project).expanduser().resolve().read_text(encoding="utf-8"))
    metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8")) if args.metrics else None
    result = evaluate(project, metrics)

    exit_code = 0 if result["gate_status"] == "PASS" else 1
    if args.expect_status:
        matched = result["gate_status"] == args.expect_status
        result["backtest"] = {"expected": args.expect_status, "matched": matched}
        exit_code = 0 if matched else 2

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "findings"}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
