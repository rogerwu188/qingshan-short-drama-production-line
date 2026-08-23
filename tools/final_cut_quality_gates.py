#!/usr/bin/env python3
"""Pre-release quality gates that grade the FILM, not the paperwork.

Authorization: ROGER-20260718-GATE-REPAIR (approved in session 2026-07-18).
Post-mortem: E19R V15 shipped with 30.4% near-duplicate shots and ~95% of its
runtime in one alley while every gate reported PASS. Root causes, all verified
against the shipped artifacts:

  R1  "Watched" was implemented as an ffmpeg exit code. The audience report
      carried `playback_evidence: ffmpeg_realtime_decode_session_25103_exit_0`
      for each of full_1x / muted / sound. No frame was ever looked at.
  R2  Duplicate detection compared source filenames, not pixels
      (`semantic_group_basis: agentcut_source_identity`).
  R3  The "supervisor aHash gate" contained no duplicate/threshold/hamming
      field at all. It sampled one frame per 8s (23 samples for 69 shots, a
      third of the shot rate) and hashed them into an aggregate SHA. That is a
      file fingerprint wearing the name of a repetition check, with a
      hard-coded confidence of 0.96.
  R4  The gate found the defect and waived it in the same breath: problem
      "夜巷主色调和场景持续较久" with fix "不构成重剪硬项".
  R5  Compliance dimensions inflated the mean. completeness 4.8 (subtitles
      present, outro present) lifted visual 3.4 / anti_ai 3.3 to an overall
      3.7 against a "reject below 3.0" line.
  R6  The 15-minute human-timeout takeover handed adjudication to R3's shell.

Design rule that follows: a gate may not consume a judgment the producing
agent asserted about itself. Every blocking input here is either measured from
the decoded mp4 (`final_cut_objective_metrics.py`) or is a per-shot artifact
that cannot be produced without looking at the picture.

Outputs `qingshan.final_cut_quality_gate_result.v2`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# --- G2 picture repetition ------------------------------------------------
MAX_NEAR_DUPLICATE_SHOT_PCT = 10.0

# --- G6 location diversity ------------------------------------------------
MAX_DOMINANT_LOCATION_PCT = 60.0

# --- G4 weakest-link scoring ---------------------------------------------
# Craft dimensions are scored. `completeness` is deliberately absent: it is a
# compliance checklist (G4b), not a measure of whether the episode is good, and
# including it in a mean is what let 3.4/3.3 pass as 3.7.
CRAFT_DIMENSIONS = ("story", "continuation", "pacing", "opening", "clarity", "visual", "anti_ai")
MIN_CRAFT_DIMENSION = 3.5
COMPLIANCE_PREREQUISITES = ("identity_color_consistent", "opening_3s_hook")

# --- G1 viewing evidence --------------------------------------------------
MIN_SHOT_NOTE_CHARS = 8
# Receipts that prove a decoder ran, not that a picture was seen.
DECODE_RECEIPT_PATTERN = re.compile(
    r"(exit_?0|exit_code|decode_session|ffmpeg_realtime|returncode)", re.IGNORECASE
)

# --- G7 event ledger ------------------------------------------------------
MAX_EVENT_GAP_SECONDS = 20.0

# --- G8 dialogue legibility ----------------------------------------------
MAX_METAPHOR_LINE_PCT = 40.0


def _score(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        score = float(value)
        if 1.0 <= score <= 5.0:
            return score
    return None


def _blocker(findings: list[dict], gate: str, detail: str, **extra: Any) -> None:
    findings.append({"severity": "BLOCKER", "gate": gate, "detail": detail, **extra})


def _invalid(findings: list[dict], gate: str, detail: str, **extra: Any) -> None:
    findings.append({"severity": "INVALID", "gate": gate, "detail": detail, **extra})


def gate_viewing_evidence(report: dict, metrics: dict, findings: list[dict]) -> None:
    """G1 — a decode receipt is not a viewing. Require per-shot notes."""
    evidence = report.get("evidence") or {}
    playback = evidence.get("playback_evidence") or {}
    if isinstance(playback, dict):
        for key, value in playback.items():
            if isinstance(value, str) and DECODE_RECEIPT_PATTERN.search(value):
                _invalid(
                    findings,
                    "G1_VIEWING_EVIDENCE",
                    "decode receipt offered as viewing evidence",
                    channel=key,
                    value=value,
                )

    notes = evidence.get("shot_notes")
    shot_count = int(metrics.get("shot_count") or 0)
    if not isinstance(notes, list) or not notes:
        _invalid(findings, "G1_VIEWING_EVIDENCE", "shot_notes missing; gate cannot be constituted")
        return
    if len(notes) != shot_count:
        _invalid(
            findings,
            "G1_VIEWING_EVIDENCE",
            "shot_notes must cover every measured shot",
            expected=shot_count,
            actual=len(notes),
        )
    thin = [
        index
        for index, note in enumerate(notes)
        if not isinstance(note, str) or len(note.strip()) < MIN_SHOT_NOTE_CHARS
    ]
    if thin:
        _invalid(
            findings,
            "G1_VIEWING_EVIDENCE",
            "shot notes too thin to have come from looking at the picture",
            shots=thin[:20],
        )
    # Identical boilerplate across shots is the obvious way to fake this.
    distinct = {note.strip() for note in notes if isinstance(note, str)}
    if notes and len(distinct) < max(2, int(len(notes) * 0.6)):
        _invalid(
            findings,
            "G1_VIEWING_EVIDENCE",
            "shot notes are largely duplicated boilerplate",
            distinct=len(distinct),
            total=len(notes),
        )


def gate_picture_repetition(metrics: dict, findings: list[dict]) -> None:
    """G2 — pixels, not filenames. Sampling must not be sparser than the cut."""
    repetition = (metrics.get("picture_repetition") or {})
    # Block on non-adjacent reuse only; adjacent near-duplicates are scene-detect
    # fragmentation of one continuous take, not repetition the audience sees.
    pct = repetition.get("near_duplicate_shot_pct_non_adjacent")
    if pct is None:
        pct = repetition.get("near_duplicate_shot_pct")
    if not isinstance(pct, (int, float)):
        _invalid(findings, "G2_PICTURE_REPETITION", "near_duplicate_shot_pct missing")
        return
    sampled = int(metrics.get("sampled_shot_count") or 0)
    shot_count = int(metrics.get("shot_count") or 0)
    if sampled < shot_count:
        _invalid(
            findings,
            "G2_PICTURE_REPETITION",
            "sampling sparser than the cut cannot see repetition",
            sampled=sampled,
            shots=shot_count,
        )
    if float(pct) > MAX_NEAR_DUPLICATE_SHOT_PCT:
        _blocker(
            findings,
            "G2_PICTURE_REPETITION",
            "near-duplicate shots over ceiling",
            value=float(pct),
            ceiling=MAX_NEAR_DUPLICATE_SHOT_PCT,
            clusters=repetition.get("non_adjacent_clusters", repetition.get("clusters", []))[:12],
        )


PIXEL_DEDUP_BASES = ("decoded_frame", "per_shot_midpoint", "pixel", "ahash_shot")


def gate_no_provenance_dedup(report: dict, base: Path | None, findings: list[dict]) -> None:
    """G2b — source-identity dedup is banned as a repetition basis.

    The basis string may live in the report or in a linked evidence file (on
    E19R it sat in the linked objective-evidence json, not in the report), so
    both are inspected. A repetition figure carried with *no* declared pixel
    basis is equally inadmissible: unlabelled numbers are how the filename
    grouping passed for a picture measurement in the first place.
    """
    evidence = report.get("evidence") or {}
    basis = evidence.get("semantic_group_basis")

    if basis is None:
        linked = evidence.get("scene_rotation_table")
        if isinstance(linked, str) and linked.strip():
            for candidate in ([base / linked] if base else []) + [Path(linked)]:
                try:
                    if candidate.is_file():
                        basis = json.loads(candidate.read_text(encoding="utf-8")).get("semantic_group_basis")
                        break
                except (OSError, json.JSONDecodeError):
                    continue

    if isinstance(basis, str) and "source_identity" in basis:
        _invalid(
            findings,
            "G2B_DEDUP_BASIS",
            "source-identity grouping may not stand in for picture repetition",
            basis=basis,
        )
        return

    if evidence.get("semantic_group_pct") is not None:
        if not isinstance(basis, str) or not any(token in basis for token in PIXEL_DEDUP_BASES):
            _invalid(
                findings,
                "G2B_DEDUP_BASIS",
                "repetition figures carried without a declared pixel basis",
                basis=basis,
            )


def gate_fingerprint_naming(adjudication: dict | None, findings: list[dict]) -> None:
    """G3 — a fingerprint may not be filed under a repetition-check name."""
    if adjudication is None:
        return
    ahash = adjudication.get("ahash") or {}
    text = json.dumps(adjudication, ensure_ascii=False).lower()
    claims_repetition_name = "ahash" in json.dumps(adjudication.get("status", ""), ensure_ascii=False).lower() or "ahash" in str(
        adjudication.get("schema", "")
    ).lower()
    does_repetition_work = any(key in text for key in ("hamming", "near_duplicate", "duplicate_clusters"))
    if claims_repetition_name and not does_repetition_work:
        _invalid(
            findings,
            "G3_GATE_NAMING",
            "artifact named as an aHash repetition gate performs only fingerprinting",
            hint="rename to file_fingerprint, or implement shot_repetition_gate",
        )
    interval = ahash.get("sample_interval_seconds")
    if isinstance(interval, (int, float)) and interval > 0:
        _invalid(
            findings,
            "G3_GATE_NAMING",
            "fixed-interval sampling is not shot-aware and cannot detect repetition",
            sample_interval_seconds=interval,
        )
    if isinstance(adjudication.get("confidence"), (int, float)) and not does_repetition_work:
        _invalid(
            findings,
            "G3_GATE_NAMING",
            "confidence reported without a computation that could produce it",
            confidence=adjudication.get("confidence"),
        )


def gate_weakest_link(report: dict, findings: list[dict]) -> float | None:
    """G4 — the worst craft dimension decides; compliance is a prerequisite."""
    dimensions = report.get("dimensions") or {}
    scores: dict[str, float] = {}
    for name in CRAFT_DIMENSIONS:
        value = _score(dimensions.get(name))
        if value is None:
            _invalid(findings, "G4_WEAKEST_LINK", f"craft dimension missing or invalid: {name}")
        else:
            scores[name] = value
    for name, value in sorted(scores.items()):
        if value < MIN_CRAFT_DIMENSION:
            _blocker(
                findings,
                "G4_WEAKEST_LINK",
                "craft dimension below floor",
                dimension=name,
                value=value,
                floor=MIN_CRAFT_DIMENSION,
            )
    evidence = report.get("evidence") or {}
    # Subtitles are mandatory when the final cut contains spoken dialogue.  A
    # deliberately silent/script-equivalent cut may mark them N/A, but only
    # with machine-readable evidence that makes a producer's self-waiver
    # impossible: the adjusted spoken-line count must be zero, whole-track ASR
    # must have found zero segments, and both evidence artifacts must be named.
    subtitles_satisfied = evidence.get("burned_subtitles") is True
    if not subtitles_satisfied:
        subtitle_requirement = evidence.get("subtitle_requirement") or {}
        subtitles_satisfied = (
            subtitle_requirement.get("status") == "NOT_APPLICABLE_ZERO_DIALOGUE"
            and subtitle_requirement.get("adjusted_spoken_line_count") == 0
            and subtitle_requirement.get("whole_track_asr_segment_count") == 0
            and isinstance(subtitle_requirement.get("script_adjustment_evidence_ref"), str)
            and bool(subtitle_requirement.get("script_adjustment_evidence_ref", "").strip())
            and isinstance(subtitle_requirement.get("whole_track_asr_evidence_ref"), str)
            and bool(subtitle_requirement.get("whole_track_asr_evidence_ref", "").strip())
        )
    if not subtitles_satisfied:
        _blocker(findings, "G4B_COMPLIANCE_PREREQ", "compliance prerequisite not met: burned_subtitles")
    for name in COMPLIANCE_PREREQUISITES:
        if evidence.get(name) is not True:
            _blocker(findings, "G4B_COMPLIANCE_PREREQ", f"compliance prerequisite not met: {name}")
    return min(scores.values()) if scores else None


def gate_no_self_waiver(report: dict, findings: list[dict]) -> None:
    """G5 — a gate that finds a problem may not clear itself."""
    problems = report.get("problems") or []
    if not problems:
        return
    waiver = re.compile(r"(不构成|无需|不作硬项|不影响发行|后续集|可接受|not\s+a\s+blocker)", re.IGNORECASE)
    for problem in problems:
        fix = str((problem or {}).get("fix", ""))
        if waiver.search(fix):
            _invalid(
                findings,
                "G5_NO_SELF_WAIVER",
                "self-issued waiver on a self-reported defect; must escalate",
                issue=(problem or {}).get("issue"),
                fix=fix,
            )
    findings.append(
        {
            "severity": "ESCALATE",
            "gate": "G5_NO_SELF_WAIVER",
            "detail": "problems reported; adjudication belongs to supervisor/Roger, not the gate",
            "count": len(problems),
        }
    )


def gate_location_diversity(metrics: dict, findings: list[dict]) -> None:
    """G6 — WITHDRAWN AS A BLOCKER. Falsified on E16, 2026-07-18.

    The intent stands: one room for the whole runtime is a defect the audience
    feels, and E19R is 95% one alley. But the implementation measured palette
    and lighting uniformity, which is a different claim:

        E19R  86.5%  genuinely one alley          -> true positive
        E16   88.8%  clinic + courtyard + street  -> FALSE POSITIVE

    E16 scores higher than E19R while being visibly more varied, because the
    whole episode shares one dark-blue candlelit grade. A structural signature
    was tried as a discriminator and made it worse (E16 32.2% near pairs vs
    E19R 21.0%, i.e. inverted against the visual truth).

    Shipping it as a blocker anyway would repeat exactly the E19R R3 sin: a
    check that does not check what its name claims. It is therefore emitted as
    an observation with no blocking power, and "is this episode stuck in one
    place" stays a supervisor looking-at-frames judgement until a signal that
    survives E16 exists.
    """
    advisory = metrics.get("palette_uniformity_ADVISORY") or {}
    pct = advisory.get("dominant_cluster_pct")
    if isinstance(pct, (int, float)):
        findings.append(
            {
                "severity": "OBSERVE",
                "gate": "G6_PALETTE_UNIFORMITY_ADVISORY",
                "detail": "palette/lighting uniformity; NOT a location measurement, no blocking power",
                "value": float(pct),
                "supervisor_action": "eyeball the contact sheet and judge location variety manually",
            }
        )


def gate_event_ledger(ledger: dict | None, metrics: dict, findings: list[dict]) -> None:
    """G7 — script density passed while nothing happened on screen for 150s.

    The beat sheet cleared 13 lines/min. Lines are not events. This ledger is
    about the finished cut: externally visible events, and the gap between them.
    """
    if ledger is None:
        _invalid(findings, "G7_EVENT_LEDGER", "final-cut event ledger absent; gate cannot be constituted")
        return
    events = ledger.get("events") or []
    if not isinstance(events, list) or not events:
        _invalid(findings, "G7_EVENT_LEDGER", "event ledger empty")
        return
    times = sorted(
        float(event["t"]) for event in events if isinstance(event, dict) and isinstance(event.get("t"), (int, float))
    )
    if len(times) != len(events):
        _invalid(findings, "G7_EVENT_LEDGER", "every event needs a numeric timestamp")
        return
    duration = float(metrics.get("duration_seconds") or 0.0)
    gaps: list[dict[str, float]] = []
    previous = 0.0
    for moment in times + [duration]:
        if moment - previous > MAX_EVENT_GAP_SECONDS:
            gaps.append({"from": round(previous, 2), "to": round(moment, 2), "gap": round(moment - previous, 2)})
        previous = moment
    if gaps:
        _blocker(
            findings,
            "G7_EVENT_LEDGER",
            "runtime stretches with no externally visible event",
            max_gap_seconds=MAX_EVENT_GAP_SECONDS,
            gaps=gaps[:10],
        )


def gate_dialogue_legibility(script: dict | None, findings: list[dict]) -> None:
    """G8 — an episode entirely of riddles gives the audience nothing to hold."""
    if script is None:
        return
    lines = script.get("lines") or []
    if not lines:
        return
    metaphor = [line for line in lines if isinstance(line, dict) and line.get("metaphor") is True]
    pct = round(len(metaphor) / len(lines) * 100.0, 2)
    if pct > MAX_METAPHOR_LINE_PCT:
        _blocker(
            findings,
            "G8_DIALOGUE_LEGIBILITY",
            "metaphor/riddle lines exceed ceiling; no plain-information line to anchor the viewer",
            value=pct,
            ceiling=MAX_METAPHOR_LINE_PCT,
            total_lines=len(lines),
        )


def evaluate(
    report: dict,
    metrics: dict,
    *,
    adjudication: dict | None = None,
    event_ledger: dict | None = None,
    script: dict | None = None,
    base: Path | None = None,
) -> dict[str, Any]:
    findings: list[dict] = []

    gate_viewing_evidence(report, metrics, findings)
    gate_picture_repetition(metrics, findings)
    gate_no_provenance_dedup(report, base, findings)
    gate_fingerprint_naming(adjudication, findings)
    weakest = gate_weakest_link(report, findings)
    gate_no_self_waiver(report, findings)
    gate_location_diversity(metrics, findings)
    gate_event_ledger(event_ledger, metrics, findings)
    gate_dialogue_legibility(script, findings)

    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    observations = [f for f in findings if f["severity"] == "OBSERVE"]
    invalid = [f for f in findings if f["severity"] == "INVALID"]
    escalations = [f for f in findings if f["severity"] == "ESCALATE"]

    if invalid:
        status = "INVALID"
    elif blockers:
        status = "REJECT_RECUT"
    elif escalations:
        status = "ESCALATE_TO_SUPERVISOR"
    else:
        status = "PASS"

    return {
        "schema": "qingshan.final_cut_quality_gate_result.v2",
        "episode": report.get("episode"),
        "gate_status": status,
        "release_allowed": status == "PASS",
        "weakest_craft_dimension": weakest,
        "measured_from": metrics.get("measured_from"),
        "counts": {
            "blocker": len(blockers),
            "invalid": len(invalid),
            "escalate": len(escalations),
            "observe": len(observations),
        },
        "withdrawn_gates": {
            "G6_LOCATION_DIVERSITY": "falsified on E16 2026-07-18; emitted as observation only"
        },
        "findings": findings,
        "rule": (
            "No gate may consume a judgment the producing agent asserted about itself. "
            "Blocking inputs are measured from the decoded final mp4 or from per-shot "
            "artifacts that cannot be produced without looking at the picture."
        ),
        "timeout_autopass_allowed": False,
    }


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade the film, not the paperwork.")
    parser.add_argument("--report", required=True, help="audience score report json")
    parser.add_argument("--metrics", required=True, help="final_cut_objective_metrics json")
    parser.add_argument("--adjudication", help="supervisor/machine adjudication json to audit")
    parser.add_argument("--event-ledger", help="final-cut event ledger json")
    parser.add_argument("--script", help="dialogue script json with metaphor flags")
    parser.add_argument("--base", help="repo root for resolving linked evidence paths")
    parser.add_argument("--out", required=True)
    parser.add_argument("--expect-status", help="backtest assertion")
    args = parser.parse_args()

    result = evaluate(
        _load(args.report) or {},
        _load(args.metrics) or {},
        adjudication=_load(args.adjudication),
        event_ledger=_load(args.event_ledger),
        script=_load(args.script),
        base=Path(args.base).resolve() if args.base else None,
    )

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
