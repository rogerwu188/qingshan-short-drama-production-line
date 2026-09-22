#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent, media-bound final-audience review for CURRENT_PORTABLE.

This tool deliberately separates two roles:

``prepare``
    The production process measures the delivered MP4 with
    :mod:`tools.final_cut_objective_metrics`, extracts a labelled per-shot
    contact sheet, and writes a SHA-bound review request.  It cannot write an
    audience score report or event ledger.

``submit``
    A separate reviewer process records three real viewing passes, one
    independently written note for every measured shot, eight scored craft
    dimensions, and timestamped visible events.  Only this command can create
    ``*_AUDIENCE_SCORE_REPORT.json`` and ``*_FINAL_CUT_EVENT_LEDGER.json``.

The command always preserves an honest reviewer verdict.  A rejected film
still gets its report and ledger; the audience and final-cut gates are then
evaluated and the command exits non-zero so S7 remains blocked.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nalu_paths as _np  # noqa: E402
from nalu_qa_common import (  # noqa: E402
    ENGINE,
    RUNTIME,
    QaPaths,
    read_json,
    require_ffmpeg,
    sha256_file,
)


TOOL_ID = "final_audience_review.v1"
REQUEST_SCHEMA = "nalu.final_audience_review_request.v1"
ANSWERS_SCHEMA = "nalu.final_audience_review_answers.v1"
REPORT_SCHEMA = "nalu.final_audience_score_report.v1"
LEDGER_SCHEMA = "nalu.final_cut_event_ledger.v1"

REVIEWER_AGENT_ID = "storyclaw-final-audience-reviewer"
REVIEWER_ROLE = "independent_final_audience_reviewer"
ALLOWED_REVIEW_MODELS = {
    "storyclaw/gpt-6-astra",
    "storyclaw/claude-opus-5",
    "storyclaw/gpt-5.6-sol",
}

DIMENSIONS = (
    "story",
    "continuation",
    "pacing",
    "opening",
    "clarity",
    "visual",
    "anti_ai",
    "completeness",
)
VIEWING_PASSES = ("full_1x", "muted", "sound")
SUBJECTIVE_CHECKS = (
    "identity_color_consistent",
    "opening_10s_hook",
    "opening_3s_hook",
    "tail_5s_hook_intact",
    "narrative_stagnation",
)
MIN_NOTE_CHARS = 20
MIN_REASON_CHARS = 12
TEMPLATE_RE = re.compile(
    r"^(画面正常|无异常|正常|通过|同上|无问题|pass|ok|n/?a|待填写|template)[。.!！ ]*$",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(path: Path) -> str:
    value = sha256_file(path)
    if not value:
        raise ValueError(f"file missing or unreadable: {path}")
    return value


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_required(path: Path, label: str) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} missing or invalid JSON: {path}")
    return payload


def _default_paths(episode: str) -> dict[str, Path]:
    p = QaPaths(episode)
    final_qa = p.final_qa_dir
    return {
        "video": RUNTIME / "deliverables" / episode / f"{episode}_final_9x16.mp4",
        "metrics": final_qa / f"{episode}_FINAL_CUT_OBJECTIVE_METRICS.json",
        "contact_sheet": final_qa / f"{episode}_FINAL_AUDIENCE_CONTACT_SHEET.jpg",
        "request": p.reviews / "final_audience_request.json",
        "asr": p.assembly / f"{episode}_FINAL_CUT_ASR_WINDOWS.json",
        "detector": p.assembly / f"{episode}_FINAL_CUT_AUDIENCE_DETECTORS.json",
        "technical": p.assembly / f"{episode}_FINAL_CUT_AUDIENCE_GATE.json",
        "subtitles": p.assembly / f"{episode}_BURNIN_SUBTITLES.json",
        "report": final_qa / f"{episode}_AUDIENCE_SCORE_REPORT.json",
        "ledger": final_qa / f"{episode}_FINAL_CUT_EVENT_LEDGER.json",
        "audience_gate": final_qa / f"{episode}_AUDIENCE_SCORE_GATE_RESULT.json",
        "quality_gate": final_qa / f"{episode}_FINAL_CUT_QUALITY_GATE_RESULT.json",
    }


def run_objective_metrics(video: Path, metrics: Path, workdir: Path) -> dict[str, Any]:
    """Run the canonical measurement executable; never synthesize its output."""
    python = Path(str(_np.VENV_PYTHON))
    if not python.is_file():
        python = Path(sys.executable)
    tool = ENGINE / "tools/final_cut_objective_metrics.py"
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    completed = subprocess.run(
        [str(python), str(tool), "--video", str(video), "--out", str(metrics),
         "--workdir", str(workdir)],
        cwd=str(ENGINE),
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if completed.returncode != 0:
        tail = ((completed.stdout or "") + (completed.stderr or ""))[-1200:]
        raise RuntimeError(f"objective metrics failed exit={completed.returncode}: {tail}")
    payload = _load_required(metrics, "objective metrics")
    if payload.get("schema") != "qingshan.final_cut_objective_metrics.v1":
        raise ValueError(f"unexpected objective metrics schema: {payload.get('schema')}")
    if payload.get("measured_from") != "DECODED_FINAL_MP4":
        raise ValueError("objective metrics were not measured from the decoded final MP4")
    return payload


def shot_windows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover exact measured shot windows from the objective audio rows."""
    duration = float(metrics.get("duration_seconds") or 0.0)
    count = int(metrics.get("shot_count") or 0)
    levels = (metrics.get("audio") or {}).get("shot_levels") or []
    if duration <= 0 or count <= 0 or len(levels) != count:
        raise ValueError("objective metrics do not contain one timestamped row per measured shot")
    starts: list[float] = []
    for expected, row in enumerate(levels):
        if not isinstance(row, dict) or int(row.get("shot", -1)) != expected:
            raise ValueError("objective shot rows are missing or out of order")
        start = row.get("start")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            raise ValueError(f"objective shot {expected} has no numeric start")
        starts.append(float(start))
    if starts[0] < 0 or any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError("objective shot starts are not strictly increasing")
    if starts[-1] >= duration:
        raise ValueError("objective last shot starts outside the final video")
    rows = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else duration
        rows.append({
            "shot_index": index,
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "review_timestamp_seconds": round((start + end) / 2.0, 3),
        })
    return rows


def build_contact_sheet(video: Path, shots: list[dict[str, Any]], out: Path,
                        frames_dir: Path) -> None:
    """Extract an original-media frame from every measured shot and label it."""
    from PIL import Image, ImageDraw, ImageFont

    ffmpeg = require_ffmpeg()
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for row in shots:
        frame = frames_dir / f"shot_{row['shot_index']:04d}.jpg"
        completed = subprocess.run(
            [str(ffmpeg), "-v", "error", "-ss", str(row["review_timestamp_seconds"]),
             "-i", str(video), "-frames:v", "1", "-q:v", "2", "-y", str(frame)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0 or not frame.is_file():
            raise RuntimeError(
                f"contact-sheet frame extraction failed for shot {row['shot_index']}: "
                f"{(completed.stderr or '')[-400:]}"
            )
        frames.append(frame)

    columns = 4
    cell_w, image_h, label_h = 220, 391, 34
    rows_count = math.ceil(len(frames) / columns)
    sheet = Image.new("RGB", (columns * cell_w, rows_count * (image_h + label_h)), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (frame, window) in enumerate(zip(frames, shots)):
        with Image.open(frame) as source:
            picture = source.convert("RGB")
            picture.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
            x = (index % columns) * cell_w + (cell_w - picture.width) // 2
            y0 = (index // columns) * (image_h + label_h)
            sheet.paste(picture, (x, y0))
        label = (f"S{index:03d}  {window['start_seconds']:.2f}-"
                 f"{window['end_seconds']:.2f}s")
        draw.text(((index % columns) * cell_w + 6, y0 + image_h + 8), label,
                  fill="white", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.jpg")
    sheet.save(tmp, format="JPEG", quality=88)
    os.replace(tmp, out)


def _derive_burned_subtitles(report_path: Path) -> dict[str, Any]:
    report = read_json(report_path, {}) or {}
    captions = report.get("captions")
    ffmpeg_exit = report.get("ffmpeg_exit")
    present = ffmpeg_exit == 0 and isinstance(captions, int) and captions > 0
    return {
        "value": present,
        "source": str(report_path),
        "source_sha256": sha256_file(report_path),
        "captions": captions,
        "ffmpeg_exit": ffmpeg_exit,
        "asr_sha256": None,  # filled by prepare, kept explicit for provenance
        "note": ("machine burn-in receipt reports at least one caption"
                 if present else "no passing non-empty burn-in receipt; audience gate must fail closed"),
    }


def _existing_request_matches(request_path: Path, *, video_sha: str,
                              evidence_sha: dict[str, str | None]) -> dict[str, Any] | None:
    """Return an active request when re-entry sees exactly the same evidence.

    Production workers re-enter every few minutes.  Rewriting the request would
    change its SHA and invalidate an in-flight independent review, so prepare is
    byte-stable until the final media or an upstream evidence file changes.
    """
    request = read_json(request_path)
    if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
        return None
    if request.get("status") != "REVIEW_REQUIRED":
        return None
    if ((request.get("media") or {}).get("sha256")) != video_sha:
        return None
    evidence = request.get("evidence") or {}
    for key, current_sha in evidence_sha.items():
        if key == "subtitle_burnin":
            recorded = (evidence.get(key) or {}).get("source_sha256")
        else:
            recorded = (evidence.get(key) or {}).get("sha256")
        if recorded != current_sha:
            return None
    for key in ("objective_metrics", "contact_sheet"):
        row = evidence.get(key) or {}
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            return None
    return request


def prepare(*, episode: str, video: Path, metrics_path: Path, contact_sheet: Path,
            request_path: Path, asr_path: Path, detector_path: Path,
            technical_path: Path, subtitle_report_path: Path,
            producer_process_id: str) -> dict[str, Any]:
    video = video.resolve()
    metrics_path = metrics_path.resolve()
    contact_sheet = contact_sheet.resolve()
    request_path = request_path.resolve()
    asr_path = asr_path.resolve()
    detector_path = detector_path.resolve()
    technical_path = technical_path.resolve()
    subtitle_report_path = subtitle_report_path.resolve()
    if not video.is_file() or video.suffix.lower() != ".mp4":
        raise ValueError(f"final MP4 missing: {video}")
    if not producer_process_id.strip():
        raise ValueError("producer_process_id is required to enforce reviewer process separation")
    video_sha = _sha(video)

    _load_required(asr_path, "final-cut ASR")
    detector = _load_required(detector_path, "final-cut audience detector report")
    technical = _load_required(technical_path, "final-cut technical gate")
    if detector.get("schema") != "qingshan.final_cut_audience_detectors.v1":
        raise ValueError(f"unexpected detector schema: {detector.get('schema')}")
    if detector.get("media_sha256") != video_sha:
        raise ValueError("detector report is not bound to the current final MP4 SHA")
    if technical.get("gate_id") != "FINAL-CUT-AUDIENCE-DETECTORS":
        raise ValueError("technical report is not FINAL-CUT-AUDIENCE-DETECTORS")

    for entry in (str(ENGINE), str(ENGINE / "tools")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from tools.final_cut_audience_gate import evaluate as evaluate_technical_gate

    canonical_technical = evaluate_technical_gate(detector, video_sha256=video_sha)
    if technical.get("status") != canonical_technical.get("status"):
        raise ValueError("technical gate status disagrees with canonical detector evaluation")
    if list(technical.get("failures") or []) != list(canonical_technical.get("failures") or []):
        raise ValueError("technical gate failures disagree with canonical detector evaluation")
    technical_status = str(canonical_technical["status"])
    subtitle_evidence = _derive_burned_subtitles(subtitle_report_path)
    subtitle_evidence["asr_sha256"] = _sha(asr_path)
    current_evidence_sha = {
        "asr": _sha(asr_path),
        "detector_report": _sha(detector_path),
        "technical_gate": _sha(technical_path),
        "subtitle_burnin": sha256_file(subtitle_report_path),
    }
    existing = _existing_request_matches(
        request_path,
        video_sha=video_sha,
        evidence_sha=current_evidence_sha,
    )
    if existing is not None:
        return {
            "status": "REVIEW_REQUIRED",
            "episode": episode,
            "request": str(request_path),
            "request_sha256": _sha(request_path),
            "final_video_sha256": video_sha,
            "shot_count": len(existing.get("shots") or []),
            "metrics": str((existing.get("evidence") or {}).get("objective_metrics", {}).get("path")),
            "contact_sheet": str((existing.get("evidence") or {}).get("contact_sheet", {}).get("path")),
            "technical_gate_status": technical_status,
            "reused_existing_request": True,
        }

    workdir = metrics_path.parent / f".{episode}_objective_frames"
    metrics = run_objective_metrics(video, metrics_path, workdir)
    shots = shot_windows(metrics)
    build_contact_sheet(video, shots, contact_sheet,
                        contact_sheet.parent / f".{episode}_audience_frames")

    refs = {
        "final_video": {"path": str(video), "sha256": video_sha},
        "objective_metrics": {"path": str(metrics_path.resolve()), "sha256": _sha(metrics_path)},
        "contact_sheet": {"path": str(contact_sheet.resolve()), "sha256": _sha(contact_sheet)},
        "asr": {"path": str(asr_path.resolve()), "sha256": _sha(asr_path)},
        "detector_report": {"path": str(detector_path.resolve()), "sha256": _sha(detector_path)},
        "technical_gate": {
            "path": str(technical_path.resolve()),
            "sha256": _sha(technical_path),
            "status": technical_status,
        },
        "subtitle_burnin": subtitle_evidence,
    }
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": f"{episode}-FINAL-AUDIENCE-{video_sha[:16]}",
        "episode": episode,
        "status": "REVIEW_REQUIRED",
        "prepared_at": _now(),
        "prepared_by": TOOL_ID,
        "producer_process_id": producer_process_id,
        "reviewer_contract": {
            "agent_id": REVIEWER_AGENT_ID,
            "role": REVIEWER_ROLE,
            "allowed_models": sorted(ALLOWED_REVIEW_MODELS),
            "must_be_separate_process": True,
            "instruction": (
                "Open the SHA-bound final MP4. Watch it once at 1x with picture and sound, "
                "once muted, and once sound-only. Do not infer viewing from decoder exit codes. "
                "Write an independent observation for every measured shot and timestamp every "
                "externally visible story event. Never copy a production-agent verdict."
            ),
        },
        "media": refs["final_video"],
        "evidence": refs,
        "objective_summary": {
            "duration_seconds": metrics.get("duration_seconds"),
            "shot_count": metrics.get("shot_count"),
            "sampled_shot_count": metrics.get("sampled_shot_count"),
            "picture_repetition": metrics.get("picture_repetition"),
            "technical_gate_status": technical_status,
        },
        "viewing_passes_required": {
            "full_1x": "watch the complete film at 1x with picture and sound",
            "muted": "watch the complete film muted; judge visual continuity and readable action",
            "sound": "listen to the complete soundtrack without picture; judge speech, mix, and rhythm",
        },
        "shots": shots,
        "dimension_questions": {
            "story": "Does the finished cut tell a coherent and satisfying story?",
            "continuation": "Does it create a clear reason to continue to the next episode?",
            "pacing": "Does visible story progress occur without dead stretches?",
            "opening": "Do the first 3 and 10 seconds earn attention?",
            "clarity": "Can a first-time viewer follow who acts, why, and what changes?",
            "visual": "Are composition, continuity, diversity, and legibility release-ready?",
            "anti_ai": "Does the film avoid obvious AI drift, repetition, warping, and synthetic rhythm?",
            "completeness": "Are subtitles, sound, beginning, ending, and story handoff complete?",
        },
        "subjective_checks_required": list(SUBJECTIVE_CHECKS),
        "answer_contract": {
            "schema": ANSWERS_SCHEMA,
            "request_sha256": "sha256 of this exact request file",
            "final_video_sha256": video_sha,
            "reviewer": {
                "agent_id": REVIEWER_AGENT_ID,
                "role": REVIEWER_ROLE,
                "model": "one of reviewer_contract.allowed_models",
                "process_id": "must differ from producer_process_id",
                "reviewed_at": "ISO-8601 timestamp recorded by the reviewer",
            },
            "viewing_passes": {key: {"completed": "true only after the complete pass",
                                      "observation": "independent observation"}
                               for key in VIEWING_PASSES},
            "shots": [{"shot_index": row["shot_index"], "note": "what is actually visible"}
                      for row in shots],
            "dimensions": {key: {"score": "1..5", "reason": "evidence-based reason"}
                           for key in DIMENSIONS},
            "overall": {"score": "1..5 holistic score; do not average dimensions",
                        "reason": "independent whole-film judgment"},
            "checks": {key: {"value": "boolean", "observation": "what establishes it"}
                       for key in SUBJECTIVE_CHECKS},
            "events": [{"shot_index": 0, "t": 0.0,
                        "what": "externally visible event at this exact time"}],
            "problems": [{"severity": "P0|P1|P2|P3", "shot_index": 0,
                          "at_seconds": 0.0, "issue": "observed defect", "fix": "specific recut"}],
        },
        "producer_may_submit_answers": False,
        "timeout_autopass_allowed": False,
    }
    _atomic_json(request_path, request)
    return {
        "status": "REVIEW_REQUIRED",
        "episode": episode,
        "request": str(request_path),
        "request_sha256": _sha(request_path),
        "final_video_sha256": video_sha,
        "shot_count": len(shots),
        "metrics": str(metrics_path),
        "contact_sheet": str(contact_sheet),
        "technical_gate_status": technical_status,
    }


def _text(value: Any, *, minimum: int, label: str, failures: list[str]) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        failures.append(f"{label}:minimum_{minimum}_characters")
    if TEMPLATE_RE.match(text):
        failures.append(f"{label}:template_or_non_observation")
    return text


def _score(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if 1.0 <= number <= 5.0:
            return number
    return None


def _validate_answers(request: dict[str, Any], request_sha: str,
                      answers: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    if answers.get("schema") != ANSWERS_SCHEMA:
        failures.append(f"answers_schema:{answers.get('schema')}")
    if answers.get("request_sha256") != request_sha:
        failures.append("request_sha256_mismatch")
    video_sha = str((request.get("media") or {}).get("sha256") or "")
    if answers.get("final_video_sha256") != video_sha:
        failures.append("final_video_sha256_mismatch")

    reviewer = answers.get("reviewer") or {}
    if not isinstance(reviewer, dict):
        reviewer = {}
        failures.append("reviewer_must_be_object")
    if reviewer.get("agent_id") != REVIEWER_AGENT_ID:
        failures.append(f"reviewer_agent_id_must_be:{REVIEWER_AGENT_ID}")
    if reviewer.get("role") != REVIEWER_ROLE:
        failures.append(f"reviewer_role_must_be:{REVIEWER_ROLE}")
    if reviewer.get("model") not in ALLOWED_REVIEW_MODELS:
        failures.append(f"reviewer_model_not_allowed:{reviewer.get('model')}")
    process_id = str(reviewer.get("process_id") or "").strip()
    if not process_id:
        failures.append("reviewer_process_id_missing")
    if process_id == str(request.get("producer_process_id") or ""):
        failures.append("reviewer_process_must_differ_from_producer")
    _text(reviewer.get("reviewed_at"), minimum=10, label="reviewer.reviewed_at", failures=failures)

    viewing = answers.get("viewing_passes") or {}
    cleaned_viewing: dict[str, bool] = {}
    playback_evidence: dict[str, str] = {}
    for key in VIEWING_PASSES:
        row = viewing.get(key) or {}
        if not isinstance(row, dict) or row.get("completed") is not True:
            failures.append(f"viewing_pass_not_completed:{key}")
        observation = _text((row or {}).get("observation"), minimum=MIN_NOTE_CHARS,
                            label=f"viewing_pass.{key}.observation", failures=failures)
        cleaned_viewing[key] = (row or {}).get("completed") is True
        playback_evidence[key] = observation
    if len(set(playback_evidence.values())) < len(VIEWING_PASSES):
        failures.append("viewing_pass_observations_must_be_independent")

    expected_shots = request.get("shots") or []
    answers_shots = answers.get("shots") or []
    if not isinstance(answers_shots, list):
        answers_shots = []
        failures.append("shots_must_be_array")
    by_index: dict[int, dict[str, Any]] = {}
    for row in answers_shots:
        if not isinstance(row, dict) or not isinstance(row.get("shot_index"), int):
            failures.append("shot_row_missing_integer_shot_index")
            continue
        index = int(row["shot_index"])
        if index in by_index:
            failures.append(f"duplicate_shot_note:{index}")
        by_index[index] = row
    shot_notes: list[str] = []
    expected_indexes = [int(row["shot_index"]) for row in expected_shots]
    for index in expected_indexes:
        row = by_index.get(index)
        if row is None:
            failures.append(f"shot_note_missing:{index}")
            shot_notes.append("")
            continue
        shot_notes.append(_text(row.get("note"), minimum=MIN_NOTE_CHARS,
                                label=f"shot_note.{index}", failures=failures))
    extras = sorted(set(by_index) - set(expected_indexes))
    if extras:
        failures.append(f"unexpected_shot_notes:{extras}")
    distinct = {note for note in shot_notes if note}
    if shot_notes and len(distinct) < max(2, math.ceil(len(shot_notes) * 0.6)):
        failures.append("shot_notes_are_largely_duplicated_boilerplate")

    dimensions = answers.get("dimensions") or {}
    clean_dimensions: dict[str, float] = {}
    dimension_reasons: dict[str, str] = {}
    for key in DIMENSIONS:
        row = dimensions.get(key) or {}
        score = _score((row or {}).get("score") if isinstance(row, dict) else None)
        if score is None:
            failures.append(f"dimension_score_invalid:{key}")
        else:
            clean_dimensions[key] = score
        dimension_reasons[key] = _text(
            (row or {}).get("reason") if isinstance(row, dict) else None,
            minimum=MIN_REASON_CHARS,
            label=f"dimension.{key}.reason",
            failures=failures,
        )
    overall_row = answers.get("overall") or {}
    overall = _score((overall_row or {}).get("score") if isinstance(overall_row, dict) else None)
    if overall is None:
        failures.append("overall_score_invalid")
    overall_reason = _text(
        (overall_row or {}).get("reason") if isinstance(overall_row, dict) else None,
        minimum=MIN_NOTE_CHARS,
        label="overall.reason",
        failures=failures,
    )

    checks = answers.get("checks") or {}
    clean_checks: dict[str, bool] = {}
    check_observations: dict[str, str] = {}
    for key in SUBJECTIVE_CHECKS:
        row = checks.get(key) or {}
        value = (row or {}).get("value") if isinstance(row, dict) else None
        if not isinstance(value, bool):
            failures.append(f"subjective_check_not_boolean:{key}")
        else:
            clean_checks[key] = value
        check_observations[key] = _text(
            (row or {}).get("observation") if isinstance(row, dict) else None,
            minimum=MIN_REASON_CHARS,
            label=f"check.{key}.observation",
            failures=failures,
        )

    events = answers.get("events") or []
    clean_events: list[dict[str, Any]] = []
    if not isinstance(events, list) or not events:
        failures.append("at_least_one_visible_event_timestamp_required")
        events = []
    windows = {int(row["shot_index"]): row for row in expected_shots}
    seen_events: set[tuple[float, str]] = set()
    duration = float((request.get("objective_summary") or {}).get("duration_seconds") or 0.0)
    for pos, event in enumerate(events):
        if not isinstance(event, dict):
            failures.append(f"event.{pos}:must_be_object")
            continue
        index = event.get("shot_index")
        moment = event.get("t")
        if not isinstance(index, int) or index not in windows:
            failures.append(f"event.{pos}:invalid_shot_index")
            continue
        if not isinstance(moment, (int, float)) or isinstance(moment, bool):
            failures.append(f"event.{pos}:timestamp_must_be_numeric")
            continue
        moment = float(moment)
        window = windows[index]
        if moment < float(window["start_seconds"]) - 0.05 or moment > float(window["end_seconds"]) + 0.05:
            failures.append(f"event.{pos}:timestamp_outside_shot_window")
        if moment < 0 or moment > duration:
            failures.append(f"event.{pos}:timestamp_outside_final_video")
        what = _text(event.get("what"), minimum=8, label=f"event.{pos}.what", failures=failures)
        signature = (round(moment, 3), what)
        if signature in seen_events:
            failures.append(f"event.{pos}:duplicate")
        seen_events.add(signature)
        clean_events.append({"t": round(moment, 3), "what": what, "shot_index": index})
    clean_events.sort(key=lambda row: row["t"])

    problems = answers.get("problems") or []
    if not isinstance(problems, list):
        failures.append("problems_must_be_array")
        problems = []
    clean_problems: list[dict[str, Any]] = []
    for pos, problem in enumerate(problems):
        if not isinstance(problem, dict):
            failures.append(f"problem.{pos}:must_be_object")
            continue
        severity = str(problem.get("severity") or "")
        if severity not in {"P0", "P1", "P2", "P3"}:
            failures.append(f"problem.{pos}:invalid_severity")
        index = problem.get("shot_index")
        moment = problem.get("at_seconds")
        if index is not None and (not isinstance(index, int) or index not in windows):
            failures.append(f"problem.{pos}:invalid_shot_index")
        if moment is not None and (not isinstance(moment, (int, float)) or isinstance(moment, bool)
                                   or float(moment) < 0 or float(moment) > duration):
            failures.append(f"problem.{pos}:invalid_at_seconds")
        clean_problems.append({
            "severity": severity,
            "shot_index": index,
            "at_seconds": round(float(moment), 3) if isinstance(moment, (int, float)) else None,
            "issue": _text(problem.get("issue"), minimum=MIN_REASON_CHARS,
                           label=f"problem.{pos}.issue", failures=failures),
            "fix": _text(problem.get("fix"), minimum=MIN_REASON_CHARS,
                         label=f"problem.{pos}.fix", failures=failures),
        })

    hard_fail: list[str] = []
    if clean_checks.get("identity_color_consistent") is False:
        hard_fail.append("identity_color_mismatch")
    if clean_checks.get("opening_10s_hook") is False:
        hard_fail.append("opening_10s_no_hook")
    if clean_checks.get("tail_5s_hook_intact") is False:
        hard_fail.append("tail_5s_hook_broken")
    subtitle_value = bool((((request.get("evidence") or {}).get("subtitle_burnin") or {}).get("value")))
    if not subtitle_value:
        hard_fail.append("missing_burned_subtitles")
    needs_problem = bool(hard_fail or overall is None or overall < 3.0
                         or any(value < 3.5 for value in clean_dimensions.values()))
    if needs_problem and not clean_problems:
        failures.append("rejected_or_below_floor_review_requires_specific_problem_and_fix")

    return failures, {
        "reviewer": reviewer,
        "viewing_passes": cleaned_viewing,
        "playback_evidence": playback_evidence,
        "shot_notes": shot_notes,
        "dimensions": clean_dimensions,
        "dimension_reasons": dimension_reasons,
        "overall_reason": overall_reason,
        "checks": clean_checks,
        "check_observations": check_observations,
        "events": clean_events,
        "problems": clean_problems,
        "hard_fail": sorted(set(hard_fail)),
        "overall": overall,
    }


def _verify_bound_evidence(request: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    media = request.get("media") or {}
    video = Path(str(media.get("path") or ""))
    if not video.is_file() or sha256_file(video) != media.get("sha256"):
        failures.append("final_video_missing_or_sha_changed")
    for key, row in (request.get("evidence") or {}).items():
        if key in {"final_video", "subtitle_burnin"}:
            continue
        if not isinstance(row, dict):
            failures.append(f"evidence_binding_invalid:{key}")
            continue
        path = Path(str(row.get("path") or ""))
        if not path.is_file() or sha256_file(path) != row.get("sha256"):
            failures.append(f"evidence_missing_or_sha_changed:{key}")
    subtitle = ((request.get("evidence") or {}).get("subtitle_burnin") or {})
    subtitle_path = Path(str(subtitle.get("source") or ""))
    subtitle_sha = subtitle.get("source_sha256")
    if subtitle_sha and (not subtitle_path.is_file() or sha256_file(subtitle_path) != subtitle_sha):
        failures.append("evidence_missing_or_sha_changed:subtitle_burnin")
    return failures


def submit(*, request_path: Path, answers_path: Path, report_path: Path,
           ledger_path: Path, audience_gate_path: Path,
           quality_gate_path: Path) -> tuple[int, dict[str, Any]]:
    request = _load_required(request_path, "final audience request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("status") != "REVIEW_REQUIRED":
        raise ValueError(f"not an active {REQUEST_SCHEMA}: {request_path}")
    answers = _load_required(answers_path, "final audience answers")
    request_sha = _sha(request_path)
    failures = _verify_bound_evidence(request)
    answer_failures, clean = _validate_answers(request, request_sha, answers)
    failures.extend(answer_failures)
    if failures:
        return 2, {
            "status": "INVALID_SUBMISSION",
            "request": str(request_path),
            "request_sha256": request_sha,
            "answers": str(answers_path),
            "answers_sha256": _sha(answers_path),
            "failure_count": len(failures),
            "failures": failures,
            "reports_written": False,
        }

    evidence = request["evidence"]
    metrics = _load_required(Path(evidence["objective_metrics"]["path"]), "objective metrics")
    technical_status = str(evidence["technical_gate"].get("status") or "FAIL")
    subtitle = evidence["subtitle_burnin"]
    verdict = "REJECT_RECUT" if clean["hard_fail"] or float(clean["overall"]) < 3.0 else "PASS"
    report = {
        "schema": REPORT_SCHEMA,
        "episode": request["episode"],
        "media": request["media"]["path"],
        "media_sha256": request["media"]["sha256"],
        "request": str(request_path),
        "request_sha256": request_sha,
        "answers": str(answers_path),
        "answers_sha256": _sha(answers_path),
        "reviewer": clean["reviewer"],
        "reviewed_at": clean["reviewer"].get("reviewed_at"),
        "submitted_at": _now(),
        "submitted_by": TOOL_ID,
        "reviewer_process_separate_from_producer": True,
        "technical_gate_status": technical_status,
        "viewing_passes": clean["viewing_passes"],
        "overall": clean["overall"],
        "overall_method": "INDEPENDENT_HOLISTIC_REVIEWER_SCORE_NOT_ARITHMETIC_MEAN",
        "overall_reason": clean["overall_reason"],
        "verdict": verdict,
        "dimensions": clean["dimensions"],
        "dimension_reasons": clean["dimension_reasons"],
        "hard_fail": clean["hard_fail"],
        "problems": clean["problems"],
        "evidence": {
            "frame_grid": evidence["contact_sheet"]["path"],
            "frame_grid_sha256": evidence["contact_sheet"]["sha256"],
            "asr": evidence["asr"]["path"],
            "asr_sha256": evidence["asr"]["sha256"],
            "semantic_group_pct": {
                "decoded_non_adjacent_near_duplicate":
                    float((metrics.get("picture_repetition") or {}).get(
                        "near_duplicate_shot_pct_non_adjacent") or 0.0),
            },
            "semantic_group_basis": "decoded_frame_per_shot_midpoint_8x8_average_hash",
            "scene_rotation_table": evidence["objective_metrics"]["path"],
            "scene_rotation_table_sha256": evidence["objective_metrics"]["sha256"],
            "burned_subtitles": bool(subtitle.get("value")),
            "burned_subtitles_evidence": subtitle,
            "identity_color_consistent": clean["checks"]["identity_color_consistent"],
            "opening_10s_hook": clean["checks"]["opening_10s_hook"],
            "opening_3s_hook": clean["checks"]["opening_3s_hook"],
            "tail_5s_hook_intact": clean["checks"]["tail_5s_hook_intact"],
            "narrative_stagnation": clean["checks"]["narrative_stagnation"],
            "subjective_check_observations": clean["check_observations"],
            "shot_notes": clean["shot_notes"],
            "playback_evidence": clean["playback_evidence"],
            "detector_report": evidence["detector_report"]["path"],
            "detector_report_sha256": evidence["detector_report"]["sha256"],
            "technical_gate": evidence["technical_gate"]["path"],
            "technical_gate_sha256": evidence["technical_gate"]["sha256"],
        },
        "timeout_autopass_allowed": False,
    }
    ledger = {
        "schema": LEDGER_SCHEMA,
        "episode": request["episode"],
        "media": request["media"]["path"],
        "media_sha256": request["media"]["sha256"],
        "request": str(request_path),
        "request_sha256": request_sha,
        "reviewer": clean["reviewer"],
        "submitted_at": _now(),
        "submitted_by": TOOL_ID,
        "events": clean["events"],
    }

    # Materialise the two reviewer artifacts before evaluating gates.  A real
    # rejection is evidence and must not disappear merely because it blocks.
    _atomic_json(report_path, report)
    _atomic_json(ledger_path, ledger)

    for entry in (str(ENGINE), str(ENGINE / "tools")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from tools import audience_score_gate, final_cut_quality_gates

    audience_result = audience_score_gate.evaluate(report, base=ENGINE)
    quality_result = final_cut_quality_gates.evaluate(
        report,
        metrics,
        event_ledger=ledger,
        base=ENGINE,
    )
    gate_bindings = {
        "final_video_sha256": request["media"]["sha256"],
        "request_sha256": request_sha,
        "audience_report_sha256": _sha(report_path),
        "event_ledger_sha256": _sha(ledger_path),
        "objective_metrics_sha256": evidence["objective_metrics"]["sha256"],
    }
    audience_result["evidence_bindings"] = gate_bindings
    quality_result["evidence_bindings"] = gate_bindings
    _atomic_json(audience_gate_path, audience_result)
    _atomic_json(quality_gate_path, quality_result)
    passed = (audience_result.get("gate_status") == "PASS"
              and quality_result.get("gate_status") == "PASS")
    return (0 if passed else 3), {
        "status": "PASS" if passed else "BLOCKED_BY_FINAL_AUDIENCE_GATE",
        "episode": request["episode"],
        "request_sha256": request_sha,
        "final_video_sha256": request["media"]["sha256"],
        "report": str(report_path),
        "report_sha256": _sha(report_path),
        "event_ledger": str(ledger_path),
        "event_ledger_sha256": _sha(ledger_path),
        "audience_gate": str(audience_gate_path),
        "audience_gate_status": audience_result.get("gate_status"),
        "quality_gate": str(quality_gate_path),
        "quality_gate_status": quality_result.get("gate_status"),
        "verdict": verdict,
    }


def status(*, episode: str, video: Path, request_path: Path, report_path: Path,
           ledger_path: Path, audience_gate_path: Path,
           quality_gate_path: Path) -> tuple[int, dict[str, Any]]:
    """Return the re-entry state without creating or accepting evidence."""
    if not video.is_file():
        return 2, {"status": "BLOCKED_FINAL_VIDEO_MISSING", "video": str(video)}
    video_sha = _sha(video)
    request = read_json(request_path)
    if not isinstance(request, dict) or request.get("schema") != REQUEST_SCHEMA:
        return 4, {"status": "PREPARE_REQUIRED", "episode": episode,
                   "final_video_sha256": video_sha}
    request_sha = _sha(request_path)
    if ((request.get("media") or {}).get("sha256")) != video_sha:
        return 4, {"status": "PREPARE_REQUIRED_STALE_REQUEST", "episode": episode,
                   "final_video_sha256": video_sha, "request_sha256": request_sha}

    report = read_json(report_path)
    ledger = read_json(ledger_path)
    if not isinstance(report, dict) or not isinstance(ledger, dict):
        return 10, {"status": "REVIEW_REQUIRED", "episode": episode,
                    "request": str(request_path), "request_sha256": request_sha,
                    "final_video_sha256": video_sha,
                    "reviewer_contract": request.get("reviewer_contract")}
    common_binding_valid = all((
        report.get("media_sha256") == video_sha,
        ledger.get("media_sha256") == video_sha,
        report.get("request_sha256") == request_sha,
        ledger.get("request_sha256") == request_sha,
    ))
    if not common_binding_valid:
        return 10, {"status": "REVIEW_REQUIRED_STALE_SUBMISSION", "episode": episode,
                    "request": str(request_path), "request_sha256": request_sha,
                    "final_video_sha256": video_sha}

    audience = read_json(audience_gate_path)
    quality = read_json(quality_gate_path)
    if not isinstance(audience, dict) or not isinstance(quality, dict):
        return 2, {"status": "BLOCKED_GATE_RESULTS_MISSING", "episode": episode,
                   "report": str(report_path), "event_ledger": str(ledger_path)}
    expected_bindings = {
        "final_video_sha256": video_sha,
        "request_sha256": request_sha,
        "audience_report_sha256": _sha(report_path),
        "event_ledger_sha256": _sha(ledger_path),
        "objective_metrics_sha256":
            ((request.get("evidence") or {}).get("objective_metrics") or {}).get("sha256"),
    }
    if audience.get("evidence_bindings") != expected_bindings \
            or quality.get("evidence_bindings") != expected_bindings:
        return 2, {"status": "BLOCKED_STALE_GATE_RESULTS", "episode": episode,
                   "request_sha256": request_sha, "final_video_sha256": video_sha}
    passed = (audience.get("gate_status") == "PASS"
              and quality.get("gate_status") == "PASS")
    return (0 if passed else 3), {
        "status": "PASS" if passed else "BLOCKED_BY_FINAL_AUDIENCE_GATE",
        "episode": episode,
        "request_sha256": request_sha,
        "final_video_sha256": video_sha,
        "audience_gate_status": audience.get("gate_status"),
        "quality_gate_status": quality.get("gate_status"),
        "report": str(report_path),
        "event_ledger": str(ledger_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare", help="measure final MP4 and create review request")
    prepare_parser.add_argument("--episode", required=True)
    prepare_parser.add_argument("--video", type=Path)
    prepare_parser.add_argument("--metrics-out", type=Path)
    prepare_parser.add_argument("--contact-sheet-out", type=Path)
    prepare_parser.add_argument("--request-out", type=Path)
    prepare_parser.add_argument("--asr", type=Path)
    prepare_parser.add_argument("--detector-report", type=Path)
    prepare_parser.add_argument("--technical-gate", type=Path)
    prepare_parser.add_argument("--subtitle-report", type=Path)
    prepare_parser.add_argument("--producer-process-id", required=True)

    submit_parser = sub.add_parser("submit", help="validate independent review and materialise evidence")
    submit_parser.add_argument("--episode", required=True)
    submit_parser.add_argument("--request", type=Path)
    submit_parser.add_argument("--answers", type=Path, required=True)
    submit_parser.add_argument("--report-out", type=Path)
    submit_parser.add_argument("--event-ledger-out", type=Path)
    submit_parser.add_argument("--audience-gate-out", type=Path)
    submit_parser.add_argument("--quality-gate-out", type=Path)

    status_parser = sub.add_parser("status", help="inspect current review/gate state without writing")
    status_parser.add_argument("--episode", required=True)
    status_parser.add_argument("--video", type=Path)
    status_parser.add_argument("--request", type=Path)
    status_parser.add_argument("--report", type=Path)
    status_parser.add_argument("--event-ledger", type=Path)
    status_parser.add_argument("--audience-gate", type=Path)
    status_parser.add_argument("--quality-gate", type=Path)

    args = parser.parse_args()
    defaults = _default_paths(args.episode)
    try:
        if args.command == "prepare":
            result = prepare(
                episode=args.episode,
                video=args.video or defaults["video"],
                metrics_path=args.metrics_out or defaults["metrics"],
                contact_sheet=args.contact_sheet_out or defaults["contact_sheet"],
                request_path=args.request_out or defaults["request"],
                asr_path=args.asr or defaults["asr"],
                detector_path=args.detector_report or defaults["detector"],
                technical_path=args.technical_gate or defaults["technical"],
                subtitle_report_path=args.subtitle_report or defaults["subtitles"],
                producer_process_id=args.producer_process_id,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "status":
            code, result = status(
                episode=args.episode,
                video=args.video or defaults["video"],
                request_path=args.request or defaults["request"],
                report_path=args.report or defaults["report"],
                ledger_path=args.event_ledger or defaults["ledger"],
                audience_gate_path=args.audience_gate or defaults["audience_gate"],
                quality_gate_path=args.quality_gate or defaults["quality_gate"],
            )
        else:
            code, result = submit(
                request_path=args.request or defaults["request"],
                answers_path=args.answers,
                report_path=args.report_out or defaults["report"],
                ledger_path=args.event_ledger_out or defaults["ledger"],
                audience_gate_path=args.audience_gate_out or defaults["audience_gate"],
                quality_gate_path=args.quality_gate_out or defaults["quality_gate"],
            )
        print(json.dumps(result, ensure_ascii=False))
        return code
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
