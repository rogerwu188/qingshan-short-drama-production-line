#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Any


SYMBOLIC_TERMS = (
    "化身",
    "幻象",
    "梦境",
    "异象",
    "意象",
    "隐喻",
    "metaphor",
    "avatar",
    "illusion",
    "dream",
    "vision",
)


def portable_bound_path(path: Path, project_root: Path) -> tuple[str, str]:
    path = path.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    try:
        return str(path.relative_to(project_root)), "PROJECT_RELATIVE"
    except ValueError:
        return str(path), "ABSOLUTE_EXTERNAL"


def resolve_bound_path(
    value: str,
    report_path: Path,
    project_root: Path,
) -> Path:
    bound = Path(value).expanduser()
    if bound.is_absolute():
        return bound
    project_candidate = (project_root / bound).resolve()
    if project_candidate.exists():
        return project_candidate
    return (report_path.parent / bound).resolve()


def validate_blind_tests_report(
    report_path: Path | None,
    beat_sheet_sha256: str,
    episode: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if report_path is None:
        return {
            "status": "FAIL",
            "report": None,
            "report_sha256": None,
            "failures": ["blind_tests_report_missing"],
        }
    report_path = report_path.expanduser().resolve()
    project_root = project_root or Path(__file__).resolve().parents[1]
    if not report_path.is_file():
        return {
            "status": "FAIL",
            "report": str(report_path),
            "report_sha256": None,
            "failures": [f"blind_tests_report_missing:{report_path}"],
        }
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    status = str(report.get("status") or "")
    if not status.startswith("PASS"):
        failures.append(f"blind_tests_report_not_pass:{status or 'MISSING'}")
    report_episode = str(report.get("episode") or "")
    if report_episode.rstrip("R") != episode.rstrip("R"):
        failures.append(f"blind_tests_episode_mismatch:{report_episode}:{episode}")
    if report.get("beat_sheet_sha256") != beat_sheet_sha256:
        failures.append("blind_tests_beat_sheet_sha256_mismatch")
    return {
        "status": "PASS" if not failures else "FAIL",
        "report": portable_bound_path(report_path, project_root)[0],
        "report_path_kind": portable_bound_path(report_path, project_root)[1],
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_status": status,
        "failures": failures,
    }


def verify_script_readiness_report(
    source: Path,
    report_path: Path,
    project_root: Path | None = None,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    report_path = report_path.expanduser().resolve()
    project_root = project_root or Path(__file__).resolve().parents[1]
    failures: list[str] = []
    if not source.is_file():
        failures.append(f"beat_sheet_missing:{source}")
        source_sha256 = None
    else:
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    if not report_path.is_file():
        failures.append(f"report_missing:{report_path}")
        report: dict[str, Any] = {}
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        failures.append(f"report_not_pass:{report.get('status')}")
    if source_sha256 and report.get("beat_sheet_sha256") != source_sha256:
        failures.append("beat_sheet_sha256_mismatch")
    blind_path = report.get("blind_tests_report")
    blind_sha = report.get("blind_tests_report_sha256")
    if not blind_path:
        failures.append("blind_tests_report_binding_missing")
    else:
        blind = resolve_bound_path(str(blind_path), report_path, project_root)
        if not blind.is_file():
            failures.append("blind_tests_report_bound_file_missing")
        elif hashlib.sha256(blind.read_bytes()).hexdigest() != blind_sha:
            failures.append("blind_tests_report_sha256_mismatch")
    return {
        "status": "PASS" if not failures else "FAIL",
        "beat_sheet": str(source),
        "beat_sheet_sha256": source_sha256,
        "report": str(report_path),
        "failures": failures,
    }


def evaluate_script_readiness(
    payload: dict[str, Any],
    blind_tests_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    runtime = payload.get("runtime_target_seconds") or {}
    runtime_min = float(runtime.get("min", runtime.get("target", 0)) or 0)
    runtime_target = float(runtime.get("target", runtime_min) or runtime_min)
    dialogue = payload.get("dialogue_draft") or []
    # The former 13-lines/minute quota is retired. It rewarded padded dialogue
    # and is superseded by payload, anti-padding, and true-event-density gates.
    spoken_lengths = [
        len(re.sub(r"[\s，。？！、；：,.!?;:]", "", str(row.get("text") or "")))
        for row in dialogue
        if str(row.get("text") or "").strip()
    ]
    median_spoken_characters = statistics.median(spoken_lengths) if spoken_lengths else 0
    if not 6 <= median_spoken_characters <= 9:
        failures.append(f"dialogue_median_characters_out_of_range:{median_spoken_characters:g}")

    review_status = str(payload.get("review_status") or "").upper()
    if review_status != "APPROVED":
        failures.append(f"script_review_not_approved:{review_status or 'MISSING'}")

    beats = payload.get("structure") or []
    structure_target_seconds = sum(
        float(beat.get("target_seconds", 0) or 0) for beat in beats
    )
    if abs(structure_target_seconds - runtime_target) > 0.001:
        failures.append(
            f"structure_runtime_target_mismatch:structure={structure_target_seconds:g}:target={runtime_target:g}"
        )
    consecutive_without_new_information = 0
    max_consecutive_without_new_information = 0
    beats_missing_new_information: list[str] = []
    beats_missing_power_shift: list[str] = []
    symbolic_failures: list[str] = []
    for index, beat in enumerate(beats, start=1):
        value = beat.get("new_information")
        has_new_information = bool(value and str(value).strip())
        if has_new_information:
            consecutive_without_new_information = 0
        else:
            beat_id = str(beat.get("beat_id") or index)
            beats_missing_new_information.append(beat_id)
            consecutive_without_new_information += 1
            max_consecutive_without_new_information = max(
                max_consecutive_without_new_information,
                consecutive_without_new_information,
            )
        if not str(beat.get("power_shift") or "").strip():
            beats_missing_power_shift.append(str(beat.get("beat_id") or index))
        beat_id = str(beat.get("beat_id") or index)
        searchable = json.dumps(beat, ensure_ascii=False).lower()
        keyword_hit = any(term.lower() in searchable for term in SYMBOLIC_TERMS)
        declarations = []
        if beat.get("symbolic_shot"):
            declarations.append(beat)
        declarations.extend(
            shot for shot in (beat.get("shots") or []) if shot.get("symbolic_shot")
        )
        if keyword_hit and not declarations:
            symbolic_failures.append(f"symbolic_declaration_missing:{beat_id}")
        for declaration in declarations:
            if not str(declaration.get("intended_read") or "").strip():
                symbolic_failures.append(f"symbolic_intended_read_missing:{beat_id}")
            dimensions = (
                declaration.get("differentiation_spec", {}).get("dimensions", [])
            )
            if len(set(dimensions)) < 3:
                symbolic_failures.append(
                    f"symbolic_differentiation_dimensions_below_3:{beat_id}"
                )
    if beats_missing_new_information:
        failures.append(
            "beats_missing_new_information:" + ",".join(beats_missing_new_information)
        )
    if max_consecutive_without_new_information >= 2:
        failures.append(
            f"consecutive_beats_without_new_information:{max_consecutive_without_new_information}"
        )
    if beats_missing_power_shift:
        failures.append("beats_missing_power_shift:" + ",".join(beats_missing_power_shift))
    failures.extend(symbolic_failures)

    blind_tests_gate = blind_tests_gate or {
        "status": "FAIL",
        "failures": ["blind_tests_report_missing"],
    }
    failures.extend(blind_tests_gate.get("failures", []))

    opening_hook = payload.get("opening_hook") or {}
    if float(opening_hook.get("within_seconds", 999) or 999) > 3:
        failures.append("opening_hook_after_3_seconds")
    if not str(opening_hook.get("conflict") or "").strip():
        failures.append("opening_hook_conflict_missing")

    if not str(payload.get("narrative_engine") or "").strip():
        failures.append("narrative_engine_missing")

    burst_segments = payload.get("burst_segments") or []
    valid_bursts = [
        row for row in burst_segments
        if 20 <= float(row.get("duration_seconds", 0) or 0) <= 40
        and float(row.get("max_asl_seconds", 999) or 999) <= 2
    ]
    if not valid_bursts:
        failures.append("burst_segment_missing_or_invalid")

    relief_beats = payload.get("relief_beats") or []
    if not 1 <= len(relief_beats) <= 2:
        failures.append(f"relief_beat_count_invalid:{len(relief_beats)}")

    end_hook = payload.get("end_hook") or {}
    if not any(str(end_hook.get(key) or "").strip() for key in ("line", "action", "question")):
        failures.append("concrete_suspense_end_hook_missing")

    silence_windows = payload.get("silence_windows")
    if not isinstance(silence_windows, list):
        failures.append("silence_windows_missing")
        silence_windows = []
    long_windows = []
    for index, window in enumerate(silence_windows, start=1):
        duration = float(window.get("duration_seconds", 0) or 0)
        if duration <= 8.0:
            continue
        row = {
            "index": index,
            "duration_seconds": duration,
            "reason": window.get("reason"),
        }
        long_windows.append(row)
        if not row["reason"]:
            failures.append(f"long_silence_missing_reason:{index}:{duration:.3f}")
    if len(long_windows) > 3:
        failures.append(f"too_many_long_silence_windows:{len(long_windows)}")

    return {
        "schema": "qingshan.script_readiness_gate.v1",
        "episode": payload.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "review_status": review_status or "MISSING",
        "runtime_min_seconds": runtime_min,
        "runtime_target_seconds": runtime_target,
        "dialogue_line_count": len(dialogue),
        "dialogue_median_spoken_characters": median_spoken_characters,
        "minimum_dialogue_line_count": None,
        "structure_target_seconds": structure_target_seconds,
        "dialogue_budget_formula": "CLOSED_SUPERSEDED_BY_TRUE_EVENT_DENSITY_AND_ANTI_PADDING",
        "beats_missing_new_information": beats_missing_new_information,
        "beats_missing_power_shift": beats_missing_power_shift,
        "symbolic_failures": symbolic_failures,
        "blind_tests_gate": blind_tests_gate,
        "max_consecutive_beats_without_new_information": max_consecutive_without_new_information,
        "long_silence_windows": long_windows,
        "failures": failures,
        "rule": (
            "Coverage or generation may start only after APPROVED review and excitement gate 8+ passes: "
            "cold open, per-beat payload and power shifts, anti-padding, true-event density, burst, relief, "
            "concrete hook, narrative engine and silence limits. Dialogue count is not a pacing proxy."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate script beat sheets before coverage or generation.")
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--out")
    parser.add_argument("--blind-tests-report")
    parser.add_argument(
        "--verify-report",
        help="Verify that an existing PASS report matches the current beat-sheet SHA256.",
    )
    args = parser.parse_args()

    source = Path(args.beat_sheet).expanduser().resolve()
    if args.verify_report:
        report_path = Path(args.verify_report).expanduser().resolve()
        result = verify_script_readiness_report(source, report_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1
    if not source.is_file():
        raise SystemExit(f"Missing beat sheet: {source}")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    if not args.out:
        raise SystemExit("--out is required unless --verify-report is used")
    out = Path(args.out).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    blind_tests_gate = validate_blind_tests_report(
        Path(args.blind_tests_report) if args.blind_tests_report else None,
        source_sha256,
        str(payload.get("episode") or ""),
        Path(__file__).resolve().parents[1],
    )
    report = evaluate_script_readiness(payload, blind_tests_gate)
    report["beat_sheet"] = str(source)
    report["beat_sheet_sha256"] = source_sha256
    report["blind_tests_report"] = blind_tests_gate.get("report")
    report["blind_tests_report_path_kind"] = blind_tests_gate.get("report_path_kind")
    report["blind_tests_report_sha256"] = blind_tests_gate.get("report_sha256")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
