#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video_q2_builder.py — D-7: the Q2 ``VIDEO_ASSEMBLY`` admission-request builder.

``tools/shot_media_admission_gate.py`` is the only code in the engine that can
write ``status ADMITTED|ADMITTED_WITH_P2`` together with ``downstream_status
ADMITTED_FOR_ASSEMBLY`` (:648-661), and only for a request whose ``kind`` is
exactly ``VIDEO_ASSEMBLY`` (:543-548).  That branch differs from the keyframe
(Q1) branch in exactly two ways (:21-27, :639-646):

  * it requires a FIFTH registered gate — ``DEFECT-TIER-TOLERANCE``;
  * ``technical_qa.status`` must be exactly ``TECHNICAL_PASS_CONTENT_UNREVIEWED``
    (the keyframe branch REJECTS content-pass-looking statuses instead).

Everything else is identical to Q1: per-gate evidence rows bound to the asset's
exact sha256, real ``objective_verification`` blocks for the three P0 gates with
the registry's own method strings, and at least one row with
``original_resolution_review: true`` and a real ``reviewer_type``.

Why a new tool.  The only VIDEO_ASSEMBLY precedent in the clone,
``tools/build_e40_video_q2_evidence.py``, is hard-disabled
(``LEGACY_E40_Q2_EVIDENCE_BUILDER_DISABLED``) and its evidence rows predate the
P0 objective requirement entirely — re-enabled it would fail with
``p0_objective_method_invalid:MISSING`` on three gates.  E41 has no admission
artifacts at all.  So this is the parameterised builder, modelled one-to-one on
``keyframe_q1_builder.py``.

Where each block comes from — every one of them a real run:

  ``VLM_STRUCTURED_STATE_QA_V1``     the submitted ``video_q2`` review.  Its
      closed questionnaire is contract-derived from the unit's own editorial
      shots (entry state of the first shot, completion state of the last, the
      union of declared cast / props / space anchors / wardrobe).  Every question
      is inside ``post_generation_qa_scope_gate.py``'s allowed scope — none of
      its sixteen forbidden gesture / choreography / trajectory / optical-flow
      checks is asked.
  ``CLOSED_SET_ANACHRONISM_OCR_V1``  a REAL RapidOCR run.  ``prepare`` extracts
      ORIGINAL-RESOLUTION frames from the clip with ffmpeg and runs the engine's
      ``tools/still_image_ocr_audit.py`` over every one of them with the closed
      forbidden-term set; the reports are embedded and cross-checked against the
      reviewer's ``observed_text_strings``.
  ``INSIGHTFACE_COSINE_V1``          a REAL embedding run through the engine's
      own ``character_identity_admission_gate``.  A clip, unlike a still, can
      honestly supply the registered ``sample_frames_per_source_min: 3`` from ONE
      source: the samples are ``--frames`` distinct real frames of that clip.
      This is why D-13's corpus-scoping is NOT needed here and is not used.
  ``DEFECT-TIER-TOLERANCE``          a REAL ``tools/defect_tolerance_gate.py``
      run over a report built from the reviewer's own defect list (P0/P1 →
      ``BLOCKER``, P2 → ``MINOR`` at its declared ``shot_index``/``at_seconds``)
      plus the unit's real shot count and its ffprobe duration.  A P2 with no
      declared location is NOT guessed and NOT dropped: the unit is REJECTED
      with ``DEFECT_TIER_LOCATION_MISSING``.
  ``technical_qa``                   copied verbatim from
      ``post_generation_qa_runner.py``'s ``nalu.post_generation_unit_qa.v1``
      record (D-6), which already writes exactly
      ``TECHNICAL_PASS_CONTENT_UNREVIEWED`` and re-binds the media sha256.

This tool writes no verdict of its own.  Every ``ADMITTED_FOR_ASSEMBLY`` comes
out of the engine gate's own report, and every objective block comes out of a
real measurement or a real review.

CLI
---
  prepare   --episode EP [--frames 5] [--unit U]   extract frames + OCR + identity
  build     --episode EP --review <submitted video_q2 review>
  status    --episode EP
"""

from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import argparse
import json
import math
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ENGINE, GATE_REGISTRY, REVIEWER_ID, REVIEWER_TYPE,
    REVIEW_METHOD, VENV, Expectations, QaPaths, engine_module, gate_parameters,
    now, portable, read_json, require_ffmpeg, require_ffprobe, sha256_file, write_json,
)

TOOL_ID = "video_q2_builder.v1"
KIND = "VIDEO_ASSEMBLY"
REQUEST_SCHEMA = "qingshan.shot_media_admission_request.v2"
EVIDENCE_SCHEMA = "qingshan.registered_video_visual_evidence.v1"
IDENTITY_GATE = "CHARACTER-IDENTITY-ADMISSION"
SCENE_GATE = "SCENE-AUTHORITY-LOCK"
ACTION_GATE = "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
PERIOD_GATE = "PERIOD-ANACHRONISM-LOCK"
DEFECT_GATE = "DEFECT-TIER-TOLERANCE"
REQUIRED_GATES = (IDENTITY_GATE, SCENE_GATE, ACTION_GATE, PERIOD_GATE, DEFECT_GATE)
NO_CHARACTER_METHOD = "STRUCTURED_NO_VISIBLE_CHARACTER_V1"
TERMINAL_DOWNSTREAM = "ADMITTED_FOR_ASSEMBLY"

#: which video_q2 answers earn which registered gate.  Mirrors the ``maps_to``
#: declared in vlm_review_protocol.QUESTIONNAIRES["video_q2"] so a reader can
#: check the two agree.
GATE_QUESTIONS = {
    ACTION_GATE: ("cast_exactly_as_declared", "camera_axis_stable_and_declared",
                  "declared_state_handoff_completes",
                  "props_present_and_end_state_as_declared",
                  "wardrobe_matches_bible", "no_extra_scene_or_replayed_beat",
                  "perceived_life_state_matches_declared", "visible_group_count_matches_declared",
                  "creature_locomotion_matches_card"),
    SCENE_GATE: ("space_anchors_match", "camera_axis_stable_and_declared",
                 "lighting_palette_and_time_match"),
    PERIOD_GATE: ("no_anachronism_from_closed_set", "no_burned_in_text_or_subtitle"),
    IDENTITY_GATE: ("cast_exactly_as_declared",
                    "each_visible_character_identity_recognisable"),
    DEFECT_GATE: ("no_p0_or_p1_defect",),
}
PASS_ANSWERS = {"PASS", "YES", "NOT_APPLICABLE"}

#: how many original-resolution frames to extract per clip.  Must be >= the
#: registry's sample_frames_per_source_min (3) for the identity measurement to
#: be able to reach it from one source.
DEFAULT_FRAMES = 9  # 2026-09-18 (E06 Q2): 5 evenly spaced frames left characters of 2-shot units with <3 usable face samples (MISSING); 9 keeps the registered minimum reachable honestly, thresholds unchanged
#: bounded per-unit parallelism for `prepare` (ffmpeg frame seeks, the RapidOCR subprocess
#: per frame).  Units are independent and write only under <q2_dir>/<unit_id>/; the
#: InsightFace work is serialised under _INSIGHT_LOCK (one FaceAnalysis per process) and the
#: rows / index are assembled in the original unit order, so the output is unchanged.
#: measured on E01 (8 units): sequential 74-80 s, 1 worker 67 s (shared backend + cache),
#: 2 workers 49 s, 4 workers 66 s (onnxruntime oversubscription) -> 2.
DEFAULT_UNIT_WORKERS = 2


def unit_workers(default: int = DEFAULT_UNIT_WORKERS) -> int:
    """NALU_QA_WORKERS=1 restores strictly sequential execution."""
    try:
        return max(1, int(os.environ.get("NALU_QA_WORKERS") or default))
    except ValueError:
        return default


def parallel_map(fn, keys, workers: int | None = None) -> dict[Any, Any]:
    """fn(key) for every key on a bounded thread pool; results keyed so the caller emits
    them in its own order.  An exception in any unit propagates as it would sequentially."""
    keys = list(keys)
    workers = unit_workers() if workers is None else workers
    if workers <= 1 or len(keys) <= 1:
        return {key: fn(key) for key in keys}
    with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as pool:
        futures = {key: pool.submit(fn, key) for key in keys}
        return {key: future.result() for key, future in futures.items()}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)          # this tool never reaches a paid endpoint
    env["PYTHONPATH"] = os.pathsep.join([str(ENGINE), str(ENGINE / "tools")])
    return env


def _run(argv: list[Any], *, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run([str(item) for item in argv], cwd=str(ENGINE), env=_env(),
                          capture_output=True, text=True, timeout=timeout)


def _checks(item: dict[str, Any], questionnaire: dict[str, Any],
            keys: tuple[str, ...]) -> list[dict[str, Any]]:
    answers = item.get("answers") or {}
    rows = []
    for key in keys:
        if key not in answers:
            continue
        rows.append({
            "question_id": key,
            "question": (questionnaire.get(key) or {}).get("question"),
            "answer": "PASS" if str(answers[key]) in PASS_ANSWERS else str(answers[key]),
            "reviewer_answer": str(answers[key]),
            "closed_enum": (questionnaire.get(key) or {}).get("enum"),
            "contract_derived": True,
        })
    return rows


def unit_media(episode: str, unit_id: str) -> Path:
    return QaPaths(episode).video_media / f"{unit_id}.mp4"


def probe_duration(media: Path) -> float | None:
    """Real ffprobe duration.  Never a planned value — defect_tolerance_gate.py
    prices its zero-tolerance opening/tail windows against the real length."""
    if not media.is_file():
        return None
    completed = _run([require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                      "-of", "json", str(media)], timeout=300)
    if completed.returncode != 0:
        return None
    try:
        return float((json.loads(completed.stdout).get("format") or {})["duration"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# prepare — original-resolution frames, a real OCR pass, a real identity pass
# --------------------------------------------------------------------------- #
def extract_frames(unit_id: str, media: Path, out_dir: Path, count: int) -> dict[str, Any]:
    """Extract `count` evenly spaced frames at the clip's ORIGINAL resolution.

    No -vf scale: the frames the reviewer and the OCR see are the real 720x1280
    pixels, which is what shot_media_admission_gate.py's
    ``original_resolution_review`` claim has to be true of.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(media)
    if duration is None or duration <= 0:
        return {"status": "MEDIA_UNREADABLE", "media": str(media), "frames": [],
                "duration_seconds": duration}
    # sample strictly inside the clip so the last frame is never past EOF
    stamps = [round(duration * (index + 0.5) / count, 3) for index in range(count)]
    frames, argvs = [], []
    for index, stamp in enumerate(stamps, 1):
        frame = out_dir / f"{unit_id}_f{index:02d}_{stamp:.3f}s.png"
        argv = [require_ffmpeg(), "-y", "-ss", f"{stamp:.3f}", "-i", str(media),
                "-frames:v", "1", str(frame)]
        completed = _run(argv, timeout=600)
        argvs.append([str(value) for value in argv])
        if completed.returncode == 0 and frame.is_file():
            frames.append({"path": str(frame), "sha256": sha256_file(frame),
                           "at_seconds": stamp})
    return {
        "status": "OK" if len(frames) == count else f"PARTIAL_{len(frames)}_OF_{count}",
        "media": str(media), "media_sha256": sha256_file(media),
        "duration_seconds": round(duration, 3),
        "frame_count": len(frames), "frames": frames, "argv": argvs,
        "note": "extracted at original resolution — no scale filter",
    }


def park_stale_frames(unit_id: str, frame_dir: Path, frames: list[dict[str, Any]]) -> list[str]:
    """Move this unit's frames that are not part of the current measurement to frame_dir/_superseded/.

    vlm_review_protocol hands the reviewer every *.png in the folder, so a frame of an earlier take left
    beside the current ones is reviewed as if it were this clip.  Never deleted."""
    current = {Path(str(row.get("path"))).name for row in frames}
    stale = sorted(old for old in frame_dir.glob(f"{unit_id}_f*.png") if old.name not in current)
    if stale:
        parked = frame_dir / "_superseded"
        parked.mkdir(exist_ok=True)
        for old in stale:
            old.replace(parked / old.name)
    return [old.name for old in stale]


def run_ocr(image: Path, forbidden_terms: list[str], out: Path) -> dict[str, Any]:
    """Execute the ENGINE's still-image OCR audit for real on one frame."""
    argv = [str(VENV), str(ENGINE / "tools/still_image_ocr_audit.py"),
            "--image", str(image), "--out", str(out)]
    for term in forbidden_terms:
        argv += ["--forbid-text", term]
    completed = _run(argv, timeout=900)
    report = read_json(out, {}) or {}
    return {
        "argv": argv, "exit_code": completed.returncode,
        "frame": str(image), "frame_sha256": sha256_file(image),
        "report_path": str(out), "report_sha256": sha256_file(out), "report": report,
        "stderr_tail": (completed.stderr or "")[-1200:],
    }


#: one engine InsightFaceBackend per process (five ONNX sessions, ~4 s to build); every
#: FaceAnalysis / gate.evaluate call goes through _INSIGHT_LOCK so the shared session is
#: never used from two threads at once.  Same models, same det_size, no per-call state:
#: a shared instance returns exactly what a fresh one did.
_INSIGHT_LOCK = threading.RLock()
_BACKEND: Any = None
_BACKEND_MODEL: str | None = None
#: canonical reference plate -> embed_all() result, keyed by (path, mtime, size).  A failure
#: (FACE_COUNT_ZERO, decode error) is never cached, so it is re-raised for every unit.
_CANONICAL_CACHE: dict[tuple[str, int, int], list[list[float]]] = {}


def _insightface_backend(gate: Any, model: str) -> Any:
    """Call with _INSIGHT_LOCK held."""
    global _BACKEND, _BACKEND_MODEL
    if _BACKEND is None or _BACKEND_MODEL != model:
        _BACKEND = gate.InsightFaceBackend(model)
        _BACKEND_MODEL = model
    return _BACKEND


def _canonical_embeddings(backend: Any, path: str) -> list[list[float]]:
    """backend.embed_all(path), cached per process.  Call with _INSIGHT_LOCK held."""
    stat = Path(path).stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    hit = _CANONICAL_CACHE.get(key)
    if hit is None:
        hit = backend.embed_all(Path(path))
        _CANONICAL_CACHE[key] = hit
    return [list(row) for row in hit]


def measure_unit_identity(episode: str, unit_id: str, frames: list[dict[str, Any]],
                          declared_ids: list[str], out_dir: Path) -> dict[str, Any]:
    """Run the ENGINE identity gate for real over this ONE clip's frames.

    Unlike a keyframe (see D-13), a clip can honestly reach the registered
    ``sample_frames_per_source_min`` from a single source: the samples are the
    real, distinct extracted frames of this very asset.  A declared character
    whose face is found in fewer than the registered minimum of frames is
    REPORTED as ``SAMPLE_MINIMUM_UNREACHABLE`` and its unit is REJECTED — never
    waved through, and never topped up from another asset.
    """
    params = gate_parameters(IDENTITY_GATE)
    samples_min = int(params.get("sample_frames_per_source_min", 3))
    canonical_min = int(params.get("canonical_views_min", 3))
    model = str(params.get("embedding_model", "buffalo_l"))
    qa_paths = QaPaths(episode)
    registry_path = qa_paths.character_registry
    registry = read_json(registry_path, {}) or {}
    characters = registry.get("characters") or {}

    result: dict[str, Any] = {
        "method": "INSIGHTFACE_COSINE_V1",
        "unit_id": unit_id,
        "series_scope_id": qa_paths.scope_id,
        "series_id": qa_paths.series_id,
        "character_registry": str(registry_path),
        "character_registry_series_id": registry.get("series_id"),
        "embedding_model": model,
        "canonical_views_min_registry": canonical_min,
        "sample_frames_per_source_min_registry": samples_min,
        "declared_character_ids": sorted(declared_ids),
        "per_character": [],
        "sample_counts": {},
        "failures": [],
        "status": "FAIL",
        "scope": "one source per declared character over this unit's own extracted "
                 "original-resolution frames",
    }
    if not declared_ids:
        result["status"] = "NO_DECLARED_CHARACTER"
        return result
    if (not qa_paths.scope["is_default"]
            and str(registry.get("series_id") or "") != qa_paths.series_id):
        result["failures"].append(
            f"CHARACTER_REGISTRY_SERIES_MISMATCH:"
            f"{registry.get('series_id')}!={qa_paths.series_id}")
        return result
    if not characters:
        result["failures"].append("CHARACTER_REGISTRY_ABSENT_OR_EMPTY_SEE_D-1")
        return result
    missing_registry = [value for value in declared_ids if value not in characters]
    if missing_registry:
        result["failures"].append("CHARACTER_NOT_IN_REGISTRY:" + ",".join(sorted(missing_registry)))
    try:
        gate = engine_module("character_identity_admission_gate")
        with _INSIGHT_LOCK:
            backend = _insightface_backend(gate, model)
    except Exception as exc:  # noqa: BLE001
        result["failures"].append(f"INSIGHTFACE_RUNTIME_UNAVAILABLE:{exc}")
        return result

    canonical: dict[str, list[list[float]]] = {}
    canonical_paths: dict[str, list[str]] = {}
    for char_id in sorted(set(declared_ids) & set(characters)):
        from tools.original_identity_authority import measurement_paths, original_reference
        paths = [value for value in measurement_paths(characters[char_id])
                 if Path(value).is_file()]
        canonical_paths[char_id] = paths
        if len(paths) < canonical_min and not original_reference(characters[char_id]):
            result["failures"].append(
                f"CANONICAL_VIEWS_BELOW_REGISTRY:{char_id}:{len(paths)}<{canonical_min}")
        embeddings: list[list[float]] = []
        for value in paths:
            try:
                with _INSIGHT_LOCK:
                    embeddings.extend(_canonical_embeddings(backend, value))
            except Exception as exc:  # noqa: BLE001
                result["failures"].append(f"CANONICAL_EMBED_FAILED:{char_id}:{exc}")
        if embeddings:
            canonical[char_id] = embeddings
    if not canonical:
        result["failures"].append("NO_CANONICAL_EMBEDDING_FOR_ANY_DECLARED_CHARACTER")
        return result

    import cv2  # provided by the insightface install

    crop_dir = out_dir / "face_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    crops: dict[str, list[tuple[str, Path, float]]] = {}
    for row in frames:
        frame_path = Path(row["path"])
        image = cv2.imread(str(frame_path))
        if image is None:
            result["failures"].append(f"FRAME_DECODE_FAILED:{frame_path.name}")
            continue
        with _INSIGHT_LOCK:
            faces = backend._app.get(image)  # noqa: SLF001 — engine's own FaceAnalysis instance
        if len(faces) < len(canonical):
            # small / dim faces in a 720p frame: retry the SAME detector on a 2x upscale and
            # map the boxes back (measurement-input change, thresholds untouched; as Q1)
            big = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            with _INSIGHT_LOCK:
                faces_big = backend._app.get(big)  # noqa: SLF001
            if len(faces_big) > len(faces):
                for face in faces_big:
                    face.bbox = face.bbox / 2.0
                faces = faces_big
                result.setdefault("upscale_retry_used", []).append(frame_path.name)
        if not faces:
            continue
        pairs = []
        for f_index, face in enumerate(faces):
            embedding = [float(value) for value in face.normed_embedding]
            for char_id in canonical:
                score = max(float(gate._cosine(embedding, ref))  # noqa: SLF001
                            for ref in canonical[char_id])
                pairs.append((score, f_index, char_id, face))
        pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
        used_faces: set[int] = set()
        used_chars: set[str] = set()
        for score, f_index, char_id, face in pairs:
            if f_index in used_faces or char_id in used_chars:
                continue
            used_faces.add(f_index)
            used_chars.add(char_id)
            # the engine re-runs its own detector on the crop; a tight bbox crop returned
            # FACE_COUNT_ZERO on every unit (2026-09-13) -> 70 % margin each side, clamped
            bx1, by1, bx2, by2 = face.bbox.tolist()
            bw, bh = max(1.0, bx2 - bx1), max(1.0, by2 - by1)
            mx, my = 0.7 * bw, 0.7 * bh
            h_img, w_img = image.shape[:2]
            x1, y1 = int(max(0, bx1 - mx)), int(max(0, by1 - my))
            x2, y2 = int(min(w_img, bx2 + mx)), int(min(h_img, by2 + my))
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                result["failures"].append(f"FACE_CROP_EMPTY:{frame_path.name}:{char_id}")
                continue
            crop_path = crop_dir / f"{frame_path.stem}__{char_id}__face{f_index}.png"
            cv2.imwrite(str(crop_path), crop)
            crops.setdefault(char_id, []).append((str(frame_path), crop_path, score))

    # A video unit may contain several editorial shots where a declared
    # character enters only part-way through the clip.  The face assignment
    # above is deliberately closed-set per frame, so an absent character can
    # otherwise be paired with another visible face and poison its identity
    # aggregate (for example: Chenji in the opening frames, Shizi in the
    # closing frames).  Keep those crops for audit, but only feed measurable
    # candidates (at or above the registered fail threshold) to the identity
    # gate.  This does not lower either pass or fail thresholds; it prevents an
    # absent-in-this-frame character from being treated as an observed wrong
    # identity.  A character still needs the registered minimum number of
    # measurable samples and the engine gate remains authoritative.
    measurable_floor = float(
        params.get("embedding_cosine_fail_threshold", 0.30)
    )
    result["frame_local_identity_filter"] = {
        "method": "SCORE_AT_OR_ABOVE_REGISTERED_FAIL_THRESHOLD",
        "threshold": measurable_floor,
        "excluded_rows_are_audited": True,
    }

    sources = []
    # Rows that cannot produce one unambiguous face embedding are measurement
    # failures, not identity observations.  Keep them in the audit trail but
    # do not let one multi-face/undetectable crop poison the whole character's
    # aggregate when other measurable samples exist.
    embedding_excluded: dict[str, list[dict[str, Any]]] = {}
    for char_id in sorted(canonical):
        all_rows = crops.get(char_id) or []
        rows = [row for row in all_rows if float(row[2]) >= measurable_floor]
        excluded = [
            {"frame": frame, "crop": str(path), "cosine": round(float(score), 6)}
            for frame, path, score in all_rows
            if float(score) < measurable_floor
        ]
        if excluded:
            result.setdefault("excluded_non_measurable_samples", {})[char_id] = excluded
        measurable_rows: list[tuple[str, Path, float]] = []
        for frame, path, score in rows:
            try:
                # Use the same backend and crop policy as the downstream gate;
                # this is only a measurability probe, not a second decision.
                with _INSIGHT_LOCK:
                    probe_faces = backend._app.get(cv2.imread(str(path)))  # noqa: SLF001
                if len(probe_faces) != 1:
                    embedding_excluded.setdefault(char_id, []).append({
                        "frame": frame, "crop": str(path),
                        "cosine": round(float(score), 6),
                        "reason": "FACE_COUNT_NOT_ONE",
                        "face_count": len(probe_faces),
                    })
                    continue
            except Exception as exc:  # noqa: BLE001
                embedding_excluded.setdefault(char_id, []).append({
                    "frame": frame, "crop": str(path),
                    "cosine": round(float(score), 6),
                    "reason": "EMBEDDING_PROBE_FAILED",
                    "error": str(exc),
                })
                continue
            measurable_rows.append((frame, path, score))
        if embedding_excluded.get(char_id):
            result.setdefault("excluded_unmeasurable_samples", {})[char_id] = embedding_excluded[char_id]
        paths = [str(path) for _frame, path, _score in measurable_rows]
        result["sample_counts"][char_id] = len(paths)
        # A declared character with no measurable face in this unit/segment is
        # not an observed identity mismatch.  Omit it from the gate manifest,
        # while retaining the exclusion audit.  If 1..N measurable samples
        # exist, the registered minimum still applies unchanged.
        if len(paths) == 0:
            result.setdefault("non_measurable_declared_characters", []).append(char_id)
            continue
        if len(paths) < samples_min:
            result["failures"].append(
                f"SAMPLE_MINIMUM_UNREACHABLE:{char_id}:{len(paths)}<{samples_min}")
        sources.append({
            "source_id": f"{episode}:{unit_id}:{char_id}",
            "characters": [{
                "character_id": char_id,
                "canonical_reference_paths": canonical_paths.get(char_id) or [],
                "canonical_reference_sha256": {value: sha256_file(value)
                                               for value in canonical_paths.get(char_id) or []},
                "canonical_view_count": len(canonical_paths.get(char_id) or []),
                "sample_frame_paths": paths,
                "sample_frame_sha256": {value: sha256_file(value) for value in paths},
            }],
        })

    manifest = {"schema": "qingshan.character_identity_admission_manifest.v1",
                "episode": episode, "unit_id": unit_id, "sources": sources}
    manifest_path = out_dir / "identity_manifest.json"
    write_json(manifest_path, manifest)
    policy = gate_parameters(IDENTITY_GATE)
    with _INSIGHT_LOCK:
        report = gate.evaluate(manifest, {"characters": characters, "parameters": policy}, backend)
    report_path = out_dir / "identity_admission.json"
    write_json(report_path, report)
    verification = report.get("objective_verification") or {}
    threshold = float(verification.get("pass_threshold")
                      or policy.get("embedding_cosine_pass_threshold", 0.45))
    decisions = {str(row.get("character_id")): str(row.get("decision"))
                 for row in verification.get("decisions") or []}
    per_character = []
    for char_id, all_rows in sorted(crops.items()):
        rows = [row for row in all_rows if float(row[2]) >= measurable_floor]
        best = max((score for _frame, _path, score in rows), default=0.0)
        worst = min((score for _frame, _path, score in rows), default=0.0)
        engine_row = next((row for row in verification.get("decisions") or []
                           if str(row.get("character_id")) == char_id), {})
        median_score = engine_row.get("aggregate_median")
        per_character.append({
            "character_id": char_id,
            "entity_id": char_id,
            "sample_count": len(rows),
            "cosine_vs_canonical": (round(float(median_score), 6) if median_score is not None
                                    else round(worst, 6)),
            "cosine_worst_frame": round(worst, 6),
            "cosine_best": round(best, 6),
            "aggregate": "ENGINE_MEDIAN_OF_PER_FRAME_MAX_COSINE" if median_score is not None else "WORST_FRAME",
            "pass_threshold": threshold,
            # the engine's own decision is the authority (character_identity_admission_gate:
            # median >= pass -> PASS, < fail -> FAIL, otherwise BOUNDARY_REQUIRES_HUMAN)
            "decision": decisions.get(char_id, "MISSING"),
            "engine_decision": decisions.get(char_id, "MISSING"),
            "samples": [{"frame": frame, "crop": str(path), "cosine": round(score, 6)}
                        for frame, path, score in rows],
        })
    result.update({
        "manifest": str(manifest_path),
        "engine_report": str(report_path),
        "engine_report_sha256": sha256_file(report_path),
        "engine_status": report.get("status"),
        "engine_failures": report.get("failures") or [],
        "engine_decisions": verification.get("decisions") or [],
        "pass_threshold": threshold,
        "fail_threshold": float(verification.get("fail_threshold")
                                or policy.get("embedding_cosine_fail_threshold", 0.30)),
        "per_character": per_character,
        "canonical_views_achieved_min": min(
            (len(value) for value in canonical_paths.values()), default=0),
        "sample_frames_per_source_achieved_min": min(
            result["sample_counts"].values(), default=0),
        "status": ("PASS" if report.get("status") == "PASS" and not result["failures"]
                   else str(report.get("status") or "FAIL")),
    })
    return result



#: D-16 (SUPERVISOR_ORDERS seq=6) extended to video units (2026-09-13): a character whose face
#: is declared non-frontal in EVERY shot of the unit (over-the-shoulder back, hands-only, far
#: figure, profile, eyes closed) has no measurable face in this clip; the reviewer's structured
#: identity answers are its check and the reason is carried into the evidence.
def pose_scoped_ids(item: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    expectations = item.get("expectations") or {}
    declared = list(expectations.get("required_visible_character_ids") or [])
    visibility: dict[str, list[str]] = {}
    for row in expectations.get("cast") or []:
        cid = str(row.get("character_id") or "")
        if cid:
            visibility.setdefault(cid, []).append(str(row.get("face_visibility") or "VISIBLE_PER_FRAME_CONTENT"))
    measurable, exempt = [], {}
    for cid in declared:
        codes = visibility.get(cid) or ["VISIBLE_PER_FRAME_CONTENT"]
        if any(code == "VISIBLE_PER_FRAME_CONTENT" for code in codes):
            measurable.append(cid)
        else:
            exempt[cid] = "+".join(dict.fromkeys(codes))
    return measurable, exempt

#: CAMERA_GRAMMAR_V1 objective face count (line owner 2026-10-23, lab urban E03: two identical Lin Qiao
#: side by side in VU-003/VU-010 while the reviewer answered cast_exactly_as_declared PASS).  It is not a
#: new gate: a FAIL only makes ``cast_exactly_as_declared`` fail, which is what the existing
#: CLAUDE_CODE_PRODUCTION §5 one-redo rule keys on.  Lenient by construction: every declared human cast
#: member who can show a face (back / over-the-shoulder included) is allowed one face; creatures and
#: offscreen / hands-only roles add none; a unit that declares a group/crowd is not counted.
FACE_COUNT_METHOD = "INSIGHTFACE_FACE_COUNT_V1"
FACE_COUNT_FRAMES = DEFAULT_FRAMES  # 6 of 9 missed E03-VU-003 (duplicate on f2/f8/f9); the 9 frames are already extracted
FACE_COUNT_MIN_DET_SCORE = 0.6
FACE_COUNT_MIN_HEIGHT_RATIO = 0.04
FACE_COUNT_MIN_FRAMES_OVER = 2
NO_FACE_VISIBILITY = ("OFFSCREEN", "HIDDEN", "HANDS", "FACE_OUT_OF_FRAME", "VOICE_ONLY")
CREATURE_KINDS = {"CREATURE", "ANIMAL"}


def declared_face_budget(expectations: dict[str, Any]) -> tuple[int, list[str]]:
    """(max faces allowed, the human cast ids that may show one)."""
    creatures = set(map(str, (expectations.get("creature_cards") or {}).keys()))
    ids: list[str] = []
    for row in expectations.get("cast") or []:
        cid = str(row.get("character_id") or "")
        fv = str(row.get("face_visibility") or "VISIBLE_PER_FRAME_CONTENT").upper()
        if (not cid or cid in ids or cid in creatures or str(row.get("kind") or "").upper() in CREATURE_KINDS
                or any(token in fv for token in NO_FACE_VISIBILITY)):
            continue
        ids.append(cid)
    return len(ids), ids


def sample_rows(rows: list[dict[str, Any]], count: int = FACE_COUNT_FRAMES) -> list[dict[str, Any]]:
    if len(rows) <= count:
        return list(rows)
    return [rows[round(i * (len(rows) - 1) / (count - 1))] for i in range(count)]


def face_count_verdict(expectations: dict[str, Any], per_frame: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure verdict over per-frame counts [{frame_index, frame, at_seconds, faces}]."""
    allowed, ids = declared_face_budget(expectations)
    result: dict[str, Any] = {"method": FACE_COUNT_METHOD, "declared_face_budget": allowed,
                              "declared_face_character_ids": ids, "min_det_score": FACE_COUNT_MIN_DET_SCORE,
                              "min_face_height_ratio": FACE_COUNT_MIN_HEIGHT_RATIO,
                              "min_frames_over": FACE_COUNT_MIN_FRAMES_OVER, "per_frame": per_frame}
    if expectations.get("group_counts"):
        return {**result, "status": "NOT_APPLICABLE", "reason": "GROUP_OR_CROWD_DECLARED"}
    over = [row for row in per_frame if int(row["faces"]) > allowed]
    result["frames_over"] = [{"frame_index": row["frame_index"], "at_seconds": row.get("at_seconds"),
                              "faces": row["faces"]} for row in over]
    result["status"] = "FAIL" if len(over) >= FACE_COUNT_MIN_FRAMES_OVER else "PASS"
    if result["status"] == "FAIL":
        result["failure"] = ("OBJECTIVE_FACE_COUNT_EXCEEDS_DECLARED:" + ",".join(
            f"f{row['frame_index']}={row['faces']}>{allowed}" for row in over))
    return result


def detect_unit_faces(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """One InsightFace pass over the unit's sampled frames (shared by the face count and the speaker
    framing measurement): [{row, frame_index, height, width, faces}] with the kept faces only."""
    try:
        import cv2
        gate = engine_module("character_identity_admission_gate")
        model = str(gate_parameters(IDENTITY_GATE).get("embedding_model", "buffalo_l"))
        with _INSIGHT_LOCK:
            backend = _insightface_backend(gate, model)
    except Exception as exc:  # noqa: BLE001
        return {"status": "NOT_MEASURED", "reason": f"INSIGHTFACE_UNAVAILABLE:{exc}"}
    rows = []
    for row in sample_rows([r for r in frames if r.get("path")]):
        image = cv2.imread(str(row["path"]))
        if image is None:
            continue
        with _INSIGHT_LOCK:
            faces = backend._app.get(image)  # noqa: SLF001 — engine's own FaceAnalysis instance
        min_h = FACE_COUNT_MIN_HEIGHT_RATIO * image.shape[0]
        kept = [f for f in faces if float(getattr(f, "det_score", 0.0)) >= FACE_COUNT_MIN_DET_SCORE
                and float(f.bbox[3] - f.bbox[1]) >= min_h]
        rows.append({"row": row, "frame_index": frames.index(row) + 1, "height": int(image.shape[0]),
                     "width": int(image.shape[1]), "faces": kept})
    return {"status": "OK", "backend": backend, "frames": rows}


def measure_face_count(expectations: dict[str, Any], frames: list[dict[str, Any]],
                       detections: dict[str, Any] | None = None) -> dict[str, Any]:
    """Count detected faces on the unit's extracted frames with the engine's own FaceAnalysis."""
    detections = detections if detections is not None else detect_unit_faces(frames)
    if detections.get("status") != "OK":
        return {"method": FACE_COUNT_METHOD, "status": "NOT_MEASURED", "reason": detections.get("reason")}
    per_frame = []
    for det in detections["frames"]:
        row, kept = det["row"], det["faces"]
        per_frame.append({"frame_index": det["frame_index"], "frame": str(row["path"]),
                          "at_seconds": row.get("at_seconds"), "faces": len(kept),
                          "boxes": [[round(float(v), 1) for v in f.bbox.tolist()] + [round(float(f.det_score), 3)]
                                    for f in kept]})
    if not per_frame:
        return {"method": FACE_COUNT_METHOD, "status": "NOT_MEASURED", "reason": "NO_READABLE_FRAME"}
    return face_count_verdict(expectations, per_frame)


#: CAMERA_GRAMMAR_V1 objective speaker framing (line owner 2026-10-24, lab Holmes E02: Helen speaking
#: half-cropped at the left frame edge / cut out of frame in VU-001/005/007/008 while the reviewer
#: answered PASS).  Not a new gate: a FAIL only makes ``cast_exactly_as_declared`` fail (the declared
#: speaker is not visibly in frame), which the existing CLAUDE_CODE_PRODUCTION §5 one-redo rule keys
#: on.  Only units whose dialogue is spoken by a declared on-screen cast member (never V.O. / offscreen /
#: back-only); only the speaker's face is judged.  Thresholds tuned on lab Holmes E02 + urban E03.
SPEAKER_FRAMING_METHOD = "INSIGHTFACE_SPEAKER_FRAMING_V1"
SPEAKER_EDGE_TOUCH_RATIO = 0.02      # bbox x within 2% of the left/right edge ...
SPEAKER_CLOSEUP_WIDTH_RATIO = 0.25   # ... unless the face is a close-up (>= 25% of frame width)
SPEAKER_CUT_FRACTION = 0.15          # >= 15% of the face box outside the frame = cut (any size)
SPEAKER_OUTER_BAND = 0.12            # face centre in the outer 12% horizontal band
SPEAKER_ID_MIN_SIMILARITY = 0.30     # a face is "character X" when cosine >= 0.30 ...
SPEAKER_ID_MIN_MARGIN = 0.10         # ... and >= 0.10 above every other declared character
SPEAKER_NOT_ID_MAX = 0.20          # below 0.20 to every speaker plate a face is not the speaker
SPEAKER_SIDE_AMBIGUITY = 0.10        # two candidate faces within 10% of width of the declared side
SPEAKER_MIN_FRAMES = 3
NO_SPEAKER_VISIBILITY = NO_FACE_VISIBILITY + ("BACK", "VOICE_OVER", "V.O.")


def _speaker_name(line: str) -> str:
    head = line[:24]
    for sep in ("：", ":"):
        if sep in head:
            return head.split(sep, 1)[0].strip()
    return ""


def declared_speakers(expectations: dict[str, Any]) -> dict[str, Any]:
    """{speaker character ids, their declared screen side, the other face cast ids} from the
    unit's dialogue + cast; a speaker who is not a face-visible cast member of that shot is skipped."""
    _, face_ids = declared_face_budget(expectations)
    speakers: list[str] = []
    for line_row in expectations.get("expected_dialogue") or []:
        shot = str(line_row.get("shot_id") or "")
        for line in str(line_row.get("spoken_text") or "").splitlines():
            name = _speaker_name(line.strip())
            if not name:
                continue
            for row in expectations.get("cast") or []:
                cid = str(row.get("character_id") or "")
                if (str(row.get("shot_id") or "") != shot or cid not in face_ids
                        or name not in {str(row.get("character") or ""), cid}):
                    continue
                fv = str(row.get("face_visibility") or "VISIBLE_PER_FRAME_CONTENT").upper()
                if not any(token in fv for token in NO_SPEAKER_VISIBILITY) and cid not in speakers:
                    speakers.append(cid)
    slots = {}
    for row in expectations.get("cast") or []:
        cid = str(row.get("character_id") or "")
        if cid in face_ids and cid not in slots:
            slots[cid] = str(row.get("screen_slot") or "").upper()
    ordinal = sorted((int(m.group(1)), cid) for cid, slot in slots.items()
                     if (m := re.fullmatch(r"SLOT_(\d+)", slot)))
    sides = {}
    for cid in speakers:
        slot = slots.get(cid, "")
        if "LEFT" in slot:
            sides[cid] = "LEFT"
        elif "RIGHT" in slot:
            sides[cid] = "RIGHT"
        elif len(ordinal) >= 2 and ordinal[0][1] == cid:
            sides[cid] = "LEFT"
        elif len(ordinal) >= 2 and ordinal[-1][1] == cid:
            sides[cid] = "RIGHT"
    return {"speaker_ids": speakers, "speaker_sides": sides, "face_cast_ids": face_ids}


def _identify(face: dict[str, Any], ids: list[str]) -> str | None:
    sims = face.get("similarity") or {}
    scored = sorted(((float(sims[c]), c) for c in ids if c in sims), reverse=True)
    if not scored or scored[0][0] < SPEAKER_ID_MIN_SIMILARITY:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < SPEAKER_ID_MIN_MARGIN:
        return None
    return scored[0][1]


def _frame_framing(declared: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    """Pure: which face is the speaker in this frame, and is it cramped / cut at the edge."""
    width = float(frame["width"])
    faces = frame.get("faces") or []
    speakers, cast = declared["speaker_ids"], declared["face_cast_ids"]
    out: dict[str, Any] = {"frame_index": frame["frame_index"], "at_seconds": frame.get("at_seconds"),
                           "faces": len(faces)}
    if not faces:
        return {**out, "flag": "NO_FACE_DETECTED"}
    have_ids = any(face.get("similarity") for face in faces)
    ident = [_identify(face, cast) if have_ids else None for face in faces]
    mine = [i for i, cid in enumerate(ident) if cid in speakers]
    # with embeddings, an unidentified face that is clearly NOT the speaker (an undeclared extra) is no
    # speaker candidate either
    unknown = [i for i, cid in enumerate(ident) if cid is None and not (have_ids and max(
        float((faces[i].get("similarity") or {}).get(c, 0.0)) for c in speakers) < SPEAKER_NOT_ID_MAX)]
    pick, basis = None, None
    if mine:
        pick = max(mine, key=lambda i: max(float((faces[i].get("similarity") or {}).get(c, 0)) for c in speakers))
        basis = "IDENTITY_MATCH"
    elif not unknown:
        return {**out, "flag": "SPEAKER_NOT_IN_FRAME", "identified": ident}
    elif len(cast) <= 1:
        pick = max(unknown, key=lambda i: (faces[i]["bbox"][2] - faces[i]["bbox"][0])
                   * (faces[i]["bbox"][3] - faces[i]["bbox"][1]))
        basis = "LARGEST_FACE"
    else:
        sides = {declared["speaker_sides"].get(c) for c in speakers}
        if len(sides) != 1 or None in sides:
            return {**out, "flag": None, "basis": "AMBIGUOUS_NO_FLAG"}
        side = sides.pop()

        def dist(i: int) -> float:
            x1, _, x2, _ = faces[i]["bbox"]
            return (x1 + x2) / 2 if side == "LEFT" else width - (x1 + x2) / 2
        ranked = sorted(unknown, key=dist)
        if len(ranked) > 1 and dist(ranked[1]) - dist(ranked[0]) < SPEAKER_SIDE_AMBIGUITY * width:
            return {**out, "flag": None, "basis": "AMBIGUOUS_NO_FLAG"}
        if len(ranked) == 1 and len(cast) - sum(1 for c in ident if c) > 1:
            return {**out, "flag": None, "basis": "AMBIGUOUS_NO_FLAG"}
        pick, basis = ranked[0], f"DECLARED_SIDE_{side}"
    x1, _, x2, _ = (float(v) for v in faces[pick]["bbox"])
    face_w = max(x2 - x1, 1.0)
    centre = (x1 + x2) / 2 / width
    cut = (max(0.0, -x1) + max(0.0, x2 - width)) / face_w
    touches = x1 <= SPEAKER_EDGE_TOUCH_RATIO * width or x2 >= (1 - SPEAKER_EDGE_TOUCH_RATIO) * width
    flag = ("FACE_CUT_AT_EDGE" if cut >= SPEAKER_CUT_FRACTION
            else "FACE_CENTRE_IN_OUTER_BAND" if centre < SPEAKER_OUTER_BAND or centre > 1 - SPEAKER_OUTER_BAND
            else "FACE_TOUCHES_EDGE" if touches and face_w < SPEAKER_CLOSEUP_WIDTH_RATIO * width
            else None)
    return {**out, "flag": flag, "basis": basis, "speaker_bbox": [round(v, 1) for v in (x1, x2)],
            "centre_x_ratio": round(centre, 3), "cut_fraction": round(cut, 3),
            **({"speaker_similarity": faces[pick].get("similarity")} if have_ids else {})}


def speaker_framing_verdict(expectations: dict[str, Any], per_frame: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure verdict over [{frame_index, at_seconds, width, faces: [{bbox, similarity?}]}]."""
    declared = declared_speakers(expectations)
    result: dict[str, Any] = {"method": SPEAKER_FRAMING_METHOD, "speaker_ids": declared["speaker_ids"],
                              "speaker_sides": declared["speaker_sides"],
                              "thresholds": {"edge_touch_ratio": SPEAKER_EDGE_TOUCH_RATIO,
                                             "closeup_width_ratio": SPEAKER_CLOSEUP_WIDTH_RATIO,
                                             "cut_fraction": SPEAKER_CUT_FRACTION,
                                             "outer_band": SPEAKER_OUTER_BAND,
                                             "id_min_similarity": SPEAKER_ID_MIN_SIMILARITY,
                                             "id_min_margin": SPEAKER_ID_MIN_MARGIN,
                                             "not_speaker_max_similarity": SPEAKER_NOT_ID_MAX,
                                             "min_frames_fraction": f"1/{SPEAKER_MIN_FRAMES}"}}
    if not declared["speaker_ids"]:
        return {**result, "status": "NOT_APPLICABLE", "reason": "NO_ON_SCREEN_SPEAKER_DECLARED"}
    if expectations.get("group_counts"):
        return {**result, "status": "NOT_APPLICABLE", "reason": "GROUP_OR_CROWD_DECLARED"}
    if not per_frame:
        return {**result, "status": "NOT_MEASURED", "reason": "NO_READABLE_FRAME"}
    frames = [_frame_framing(declared, frame) for frame in per_frame]
    flagged = [row for row in frames if row.get("flag")]
    need = max(2, math.ceil(len(frames) / SPEAKER_MIN_FRAMES))
    result.update({"per_frame": frames, "frames_flagged": len(flagged), "frames_sampled": len(frames),
                   "min_frames_flagged": need,
                   "status": "FAIL" if len(flagged) >= need else "PASS"})
    if result["status"] == "FAIL":
        result["failure"] = ("OBJECTIVE_SPEAKER_FRAMING_CRAMPED_OR_CUT:" + ",".join(
            f"f{row['frame_index']}={row['flag']}" for row in flagged))
    return result


def _speaker_canonicals(episode: str, char_ids: list[str], backend: Any) -> dict[str, list[list[float]]]:
    """Canonical face embeddings of the cast (cached per process); {} when not available."""
    try:
        from tools.original_identity_authority import measurement_paths
        characters = (read_json(QaPaths(episode).character_registry, {}) or {}).get("characters") or {}
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, list[list[float]]] = {}
    for cid in char_ids:
        embeddings: list[list[float]] = []
        for value in (measurement_paths(characters[cid]) if cid in characters else []):
            if Path(value).is_file():
                try:
                    with _INSIGHT_LOCK:
                        embeddings.extend(_canonical_embeddings(backend, value))
                except Exception:  # noqa: BLE001
                    continue
        if embeddings:
            out[cid] = embeddings
    return out


def _framing_frames(episode: str, declared: dict[str, Any],
                    detections: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Detections -> the pure verdict's per-frame rows (with canonical similarities when every speaker has a
    canonical plate) and whether identities were used."""
    canon = _speaker_canonicals(episode, declared["face_cast_ids"], detections["backend"])
    use_ids = all(cid in canon for cid in declared["speaker_ids"])
    per_frame = []
    for det in detections["frames"]:
        faces = []
        for face in det["faces"]:
            row: dict[str, Any] = {"bbox": [round(float(v), 1) for v in face.bbox.tolist()]}
            if use_ids:
                emb = [float(v) for v in face.normed_embedding]
                row["similarity"] = {cid: round(max(sum(a * b for a, b in zip(ref, emb)) for ref in refs), 3)
                                     for cid, refs in canon.items()}
            faces.append(row)
        per_frame.append({"frame_index": det["frame_index"], "at_seconds": det["row"].get("at_seconds"),
                          "frame": str(det["row"]["path"]), "width": det["width"], "faces": faces})
    return per_frame, use_ids


def measure_speaker_framing(episode: str, expectations: dict[str, Any], frames: list[dict[str, Any]],
                            detections: dict[str, Any] | None = None) -> dict[str, Any]:
    declared = declared_speakers(expectations)
    if not declared["speaker_ids"]:
        return speaker_framing_verdict(expectations, [])
    detections = detections if detections is not None else detect_unit_faces(frames)
    if detections.get("status") != "OK":
        return {"method": SPEAKER_FRAMING_METHOD, "status": "NOT_MEASURED", "reason": detections.get("reason")}
    per_frame, use_ids = _framing_frames(episode, declared, detections)
    result = speaker_framing_verdict(expectations, per_frame)
    result["speaker_identity"] = "CANONICAL_EMBEDDING" if use_ids else "GEOMETRY_ONLY"
    return result


#: CAMERA_GRAMMAR_V1 derived (tail-frame) start frames (line owner 2026-10-24, lab Holmes E03 VU-002: the
#: previous unit's last frame had Helen out of frame, and VU-002 opened on the empty room).  The same
#: objective speaker-framing measurement, on ONE candidate still: a unit whose first shot has a declared
#: on-screen speaker does not start from a tail where the speaker is missing / at the edge / cut, or where
#: more faces show than the shot declares.  Not a gate: the unit then starts from its own keyframe.
START_FRAME_CHECK_METHOD = "INSIGHTFACE_TAIL_START_FRAME_SPEAKER_V1"
#: one still decides the whole clip's opening composition (H3 holds it), so on top of the per-frame Q2 flags a
#: start frame is "at the edge" when the speaker's face centre lies in the outer 20% band, or the face box
#: touches the left/right edge (within 2%) at any face size (lab E03: VU-002/VU-005 tails, Helen's face centre
#: at 0.155 / 0.136 of the width, pass the per-frame Q2 flags yet open the next clip on an empty room).
START_FRAME_OUTER_BAND = 0.20


def first_shot_expectations(expectations: dict[str, Any]) -> dict[str, Any]:
    """The unit's expectations scoped to its FIRST editorial shot (a start frame is that shot's entry)."""
    shots = [str(v) for v in expectations.get("editorial_shot_ids") or []]
    if not shots:
        return dict(expectations)
    first = shots[0]
    return {**expectations,
            "cast": [r for r in expectations.get("cast") or [] if str(r.get("shot_id") or first) == first],
            "expected_dialogue": [r for r in expectations.get("expected_dialogue") or []
                                  if str(r.get("shot_id") or first) == first],
            "group_counts": {k: v for k, v in (expectations.get("group_counts") or {}).items() if str(k) == first}}


def start_frame_speaker_verdict(expectations: dict[str, Any], frame: dict[str, Any] | None) -> dict[str, Any]:
    """Pure: ACCEPT / REJECT / NOT_APPLICABLE for one candidate start frame {width, faces: [{bbox, similarity?}]}."""
    declared = declared_speakers(expectations)
    allowed, _ = declared_face_budget(expectations)
    result: dict[str, Any] = {"method": START_FRAME_CHECK_METHOD, "speaker_ids": declared["speaker_ids"],
                              "declared_face_budget": allowed,
                              "thresholds": {"edge_touch_ratio": SPEAKER_EDGE_TOUCH_RATIO,
                                             "closeup_width_ratio": SPEAKER_CLOSEUP_WIDTH_RATIO,
                                             "cut_fraction": SPEAKER_CUT_FRACTION,
                                             "outer_band": SPEAKER_OUTER_BAND}}
    if not declared["speaker_ids"]:
        return {**result, "status": "NOT_APPLICABLE", "verdict": "ACCEPT", "reason": "NO_ON_SCREEN_SPEAKER_DECLARED"}
    if expectations.get("group_counts"):
        return {**result, "status": "NOT_APPLICABLE", "verdict": "ACCEPT", "reason": "GROUP_OR_CROWD_DECLARED"}
    if frame is None:
        return {**result, "status": "NOT_MEASURED", "verdict": "ACCEPT", "reason": "NO_READABLE_FRAME"}
    row = _frame_framing(declared, {"frame_index": 1, **frame})
    faces = len(frame.get("faces") or [])
    flag = row.get("flag")
    if not flag and row.get("speaker_bbox"):
        width = float(frame["width"])
        x1, x2 = (float(v) for v in row["speaker_bbox"])
        centre = float(row.get("centre_x_ratio") or 0.5)
        if x1 <= SPEAKER_EDGE_TOUCH_RATIO * width or x2 >= (1 - SPEAKER_EDGE_TOUCH_RATIO) * width:
            flag = "START_FRAME_FACE_TOUCHES_EDGE"
        elif centre < START_FRAME_OUTER_BAND or centre > 1 - START_FRAME_OUTER_BAND:
            flag = "START_FRAME_FACE_CENTRE_AT_EDGE"
    reasons = ([str(flag)] if flag else []) + (
        [f"FACE_COUNT_EXCEEDS_DECLARED:{faces}>{allowed}"] if faces > allowed else [])
    result["thresholds"]["start_frame_outer_band"] = START_FRAME_OUTER_BAND
    return {**result, "status": "MEASURED", "verdict": "REJECT" if reasons else "ACCEPT",
            "reasons": reasons, "faces": faces,
            "measurement": {k: v for k, v in row.items() if k != "speaker_similarity"}}


def check_start_frame(episode: str, unit_id: str, image: Path,
                      expectations: dict[str, Any] | None = None) -> dict[str, Any]:
    """Measure one candidate start frame (a previous unit's tail) for ``unit_id``."""
    if expectations is None:
        item = next((row for row in Expectations(episode).video_unit_items() if row["unit_id"] == unit_id), None)
        if item is None:
            return {"method": START_FRAME_CHECK_METHOD, "status": "NOT_MEASURED", "verdict": "ACCEPT",
                    "reason": f"UNIT_NOT_IN_PLAN:{unit_id}"}
        expectations = item["expectations"]
    scoped = first_shot_expectations(expectations)
    declared = declared_speakers(scoped)
    base = {"unit_id": unit_id, "image": str(image),
            "image_sha256": sha256_file(image) if Path(image).is_file() else None}
    if not declared["speaker_ids"] or scoped.get("group_counts"):
        return {**base, **start_frame_speaker_verdict(scoped, None)}
    detections = detect_unit_faces([{"path": str(image), "at_seconds": None}])
    if detections.get("status") != "OK":
        return {**base, "method": START_FRAME_CHECK_METHOD, "status": "NOT_MEASURED", "verdict": "ACCEPT",
                "reason": detections.get("reason")}
    per_frame, use_ids = _framing_frames(episode, declared, detections)
    result = start_frame_speaker_verdict(scoped, per_frame[0] if per_frame else None)
    return {**base, **result, "speaker_identity": "CANONICAL_EMBEDDING" if use_ids else "GEOMETRY_ONLY"}


def apply_face_count(face_count: dict[str, Any] | None, checks: list[dict[str, Any]],
                     failures: list[Any]) -> bool:
    """An objective count FAIL forces ``cast_exactly_as_declared`` to FAIL (the reviewer's answer is kept
    as ``reviewer_answer``; a PASS cannot override the count).  Returns True when applied."""
    if not face_count or face_count.get("status") != "FAIL":
        return False
    row = next((r for r in checks if r.get("question_id") == "cast_exactly_as_declared"), None)
    if row is None:
        row = {"question_id": "cast_exactly_as_declared", "reviewer_answer": None, "contract_derived": True}
        checks.append(row)
    row.update({"answer": "FAIL", "objective_override": {"method": FACE_COUNT_METHOD,
                                                         "failure": face_count.get("failure")}})
    checks.append({"question_id": "objective_face_count", "method": FACE_COUNT_METHOD, "answer": "FAIL",
                   "declared_face_budget": face_count.get("declared_face_budget"),
                   "frames_over": face_count.get("frames_over"), "contract_derived": True})
    if "cast_exactly_as_declared" not in failures:
        failures.append("cast_exactly_as_declared")
    failures.append(str(face_count.get("failure")))
    return True


def apply_speaker_framing(framing: dict[str, Any] | None, checks: list[dict[str, Any]],
                          failures: list[Any]) -> bool:
    """An objective speaker-framing FAIL forces ``cast_exactly_as_declared`` to FAIL (the declared speaker
    is not visibly in frame); the reviewer's answer is kept as ``reviewer_answer``.  True when applied."""
    if not framing or framing.get("status") != "FAIL":
        return False
    row = next((r for r in checks if r.get("question_id") == "cast_exactly_as_declared"), None)
    if row is None:
        row = {"question_id": "cast_exactly_as_declared", "reviewer_answer": None, "contract_derived": True}
        checks.append(row)
    overrides = row.get("objective_overrides") or ([row["objective_override"]] if row.get("objective_override") else [])
    row.update({"answer": "FAIL", "objective_overrides": overrides + [
        {"method": SPEAKER_FRAMING_METHOD, "failure": framing.get("failure")}]})
    checks.append({"question_id": "objective_speaker_framing", "method": SPEAKER_FRAMING_METHOD, "answer": "FAIL",
                   "speaker_ids": framing.get("speaker_ids"), "frames_flagged": framing.get("frames_flagged"),
                   "contract_derived": True})
    if "cast_exactly_as_declared" not in failures:
        failures.append("cast_exactly_as_declared")
    failures.append(str(framing.get("failure")))
    return True


def prepare(episode: str, *, frames: int = DEFAULT_FRAMES,
            units: list[str] | None = None) -> dict[str, Any]:
    """Extract frames, run OCR over every one, and measure identity per unit.

    Runs BEFORE the review request is written, because the request has to show
    the reviewer the original-resolution frames (and because the OCR / identity
    measurements are the objective half of the evidence, independent of any
    answer).
    """
    p = QaPaths(episode)
    exp = Expectations(episode)
    forbidden = exp.forbidden_terms()
    if frames < int(gate_parameters(IDENTITY_GATE).get("sample_frames_per_source_min", 3)):
        raise SystemExit(
            f"--frames {frames} is below the registered sample_frames_per_source_min; "
            "the identity measurement could not reach the minimum from one source")
    items = [item for item in exp.video_unit_items()
             if not units or item["unit_id"] in set(units)]
    # CAMERA_GRAMMAR_V1 only: objective face count (see FACE_COUNT_METHOD); other episodes unchanged.
    face_count_on = engine_module("camera_grammar_policy").active(exp.contract, episode=episode)

    def prepare_unit(index: int) -> dict[str, Any]:
        """Frames + OCR + identity of ONE unit — independent of every other unit."""
        item = items[index]
        unit_id = item["unit_id"]
        media = unit_media(episode, unit_id)
        out_dir = p.q2_dir / unit_id
        out_dir.mkdir(parents=True, exist_ok=True)
        if not media.is_file():
            return {"unit_id": unit_id, "status": "MEDIA_MISSING", "media": str(media),
                    "blocker": f"UNIT_VIDEO_NOT_DOWNLOADED:{media}"}
        extraction = extract_frames(unit_id, media, out_dir / "frames", frames)
        # A character who is on screen for only part of a clip (E11-VU-014's 刘老头, VU-025's
        # 秦铭 — each present in one of the unit's shots) may land on fewer than the registered
        # sample_frames_per_source_min frames at the default density: the same 9 evenly spaced
        # frames that give a fully-present character 9 samples gave these two.  Those two
        # samples scored 0.90 / 0.86 — the identity is not in doubt, only the sample count — so
        # the honest fix is MORE REAL FRAMES of the same clip, never a waiver and never a lower
        # minimum.  An operator may therefore raise --frames for a single unit, and a later
        # whole-episode run at the default density must not silently undo it: the frames that
        # are already on disk stay part of this unit's measurement.  Only real extractions are
        # merged (never a synthesised frame), and they are the same ffmpeg seek on the same
        # byte-identical asset, so the measurement-scope claim stays true.
        if frames > DEFAULT_FRAMES:
            pass  # this run is the denser one; nothing to merge
        elif extraction.get("frames"):
            # Only frames of THIS take (E12 2026-10-31: a new take inherited the previous take's frames
            # through this merge, and both the identity measurement and the reviewer saw clips that no
            # longer existed).
            prior = read_json(out_dir / "prepare.json", {}) or {}
            same_take = (prior.get("media_sha256") or (prior.get("frames") or {}).get("media_sha256")) \
                == extraction.get("media_sha256")
            previous = [row for row in (prior.get("frames", {}).get("frames", []) if same_take else [])
                        if isinstance(row, dict) and Path(str(row.get("path"))).is_file()]
            have = {round(float(row.get("at_seconds") or 0), 3): row for row in previous}
            have.update({round(float(row.get("at_seconds") or 0), 3): row
                         for row in extraction["frames"]})
            if len(have) > len(extraction["frames"]):
                merged = [have[key] for key in sorted(have)]
                extraction = {**extraction,
                              "frames": merged, "frame_count": len(merged),
                              "sampled_at_seconds": [row.get("at_seconds") for row in merged],
                              "note": extraction.get("note", "") +
                                      " | includes frames from an earlier denser sampling of this "
                                      "same clip (identity sample count only; every frame is a "
                                      "real ffmpeg extraction of this asset)"}
        extraction = {**extraction, "stale_frames_parked": park_stale_frames(
            unit_id, out_dir / "frames", extraction.get("frames") or [])}
        ocr_rows = [run_ocr(Path(frame["path"]), forbidden,
                            out_dir / "ocr" / f"{Path(frame['path']).stem}_ocr.json")
                    for frame in extraction.get("frames") or []]
        declared_all = list(item["expectations"].get("required_visible_character_ids") or [])
        measurable, exempt = pose_scoped_ids(item)
        identity = measure_unit_identity(
            episode, unit_id, extraction.get("frames") or [], measurable, out_dir)
        identity["declared_character_ids_all"] = sorted(declared_all)
        identity["not_measurable_by_pose"] = exempt
        if not measurable and declared_all:
            identity["status"] = "ALL_DECLARED_NOT_MEASURABLE_BY_POSE"
        row = {
            "unit_id": unit_id,
            "status": "OK" if extraction["status"] == "OK" else extraction["status"],
            "media": str(media), "media_sha256": sha256_file(media),
            "duration_seconds": extraction.get("duration_seconds"),
            "shot_count": item["expectations"].get("shot_count"),
            "frames": extraction,
            "ocr": [{key: value for key, value in ocr.items() if key != "report"}
                    for ocr in ocr_rows],
            "ocr_reports": [ocr["report_path"] for ocr in ocr_rows],
            "identity": identity,
            "closed_set_size": len(forbidden),
        }
        if face_count_on:
            unit_frames = extraction.get("frames") or []
            detections = detect_unit_faces(unit_frames)
            row["face_count"] = measure_face_count(item["expectations"], unit_frames, detections)
            row["speaker_framing"] = measure_speaker_framing(episode, item["expectations"], unit_frames,
                                                             detections)
        return row

    prepared = parallel_map(prepare_unit, range(len(items)))
    rows = []
    for index, item in enumerate(items):
        row = prepared[index]
        write_json(p.q2_dir / item["unit_id"] / "prepare.json", row)
        rows.append(row)
    summary = {
        "schema": "nalu.video_q2_prepare_index.v1",
        "episode": episode, "recorded_at": now(), "recorded_by": TOOL_ID,
        "frames_per_unit": frames,
        "unit_count": len(rows),
        "ready_unit_ids": [row["unit_id"] for row in rows if row.get("status") == "OK"],
        "blocked": [{"unit_id": row["unit_id"], "status": row.get("status"),
                     "blocker": row.get("blocker")} for row in rows
                    if row.get("status") != "OK"],
        "status": ("READY" if rows and all(row.get("status") == "OK" for row in rows)
                   else "BLOCKED" if rows else "NO_UNITS"),
        "next": f"vlm_review_protocol.py request --kind video_q2 --episode {episode}",
        "units": [{"unit_id": row["unit_id"], "status": row.get("status"),
                   "frame_count": (row.get("frames") or {}).get("frame_count"),
                   "identity_status": (row.get("identity") or {}).get("status"),
                   "prepare": str(p.q2_dir / row["unit_id"] / "prepare.json")}
                  for row in rows],
    }
    out = write_json(p.q2_dir / f"{episode}_VIDEO_Q2_PREPARE.json", summary)
    summary["_written_to"] = str(out)
    return summary


# --------------------------------------------------------------------------- #
# objective blocks
# --------------------------------------------------------------------------- #
def build_period_verification(item: dict[str, Any], questionnaire: dict[str, Any],
                              ocr_rows: list[dict[str, Any]], forbidden_terms: list[str]
                              ) -> tuple[dict[str, Any], list[str]]:
    """CLOSED_SET_ANACHRONISM_OCR_V1 over EVERY extracted frame of the clip."""
    failures: list[str] = []
    recognised: list[str] = []
    per_frame = []
    if not ocr_rows:
        failures.append("OCR_NOT_RUN_RUN_prepare_FIRST")
    noise_ignored: list[dict[str, Any]] = []
    # D-26 (video, 2026-09-16 E04 VU-021 "YANTTC" on donkey mane): the reviewer may declare a specific
    # OCR recognition as texture noise with "NOISE:<text>" in observed_text_strings — honoured only when
    # the recognition carries no forbidden token and its OCR confidence is below 0.90, and always
    # recorded in ocr_noise_ignored so the call stays auditable (same rule as keyframe_q1_builder).
    declared_noise = {str(v)[6:].strip() for v in ((item.get("observed") or {}).get("observed_text_strings") or [])
                      if str(v).startswith("NOISE:")}
    def _is_noise(entry: dict[str, Any]) -> bool:
        text = str(entry.get("text") or "").strip()
        if not text or (entry.get("forbidden_tokens") or []):
            return False
        if text in declared_noise and float(entry.get("confidence") or 1.0) < 0.90:
            return True
        # <=2 ASCII letters, or any single character (CJK/digit): texture false positives on
        # fur / stone / fabric (same policy as keyframe_q1_builder, verified text-free by eye)
        if (len(text) <= 2 and text.isascii() and text.isalpha()) or len(text) == 1:
            return True
        # Long streaks of flame, embers, fur and fabric weave also produce 3-4 character
        # letter clusters — sometimes with a stray punctuation mark — at confidence just over
        # the audit's 0.50 floor: E11-VU-006 frame 5.824 s read "SO!" at 0.54 out of the
        # oil-lamp flame in the lower-left corner of an interior with no text anywhere in it.
        # A 1-4 letter ASCII core (edge punctuation stripped, no digit anywhere) below 0.60 is
        # that same texture noise, so it is dropped from the failure set — and recorded in
        # ocr_noise_ignored exactly like the declared-noise and <=2-letter cases, so the call
        # stays auditable.  Anything longer, anything carrying a digit ("SO2", "4K", a channel
        # watermark) and anything at or above 0.60 still fails the unit.
        core = text.strip().strip(".,!?;:\"'`~*_-=\\/|()[]{}<>")
        return (1 <= len(core) <= 4 and core.isascii() and core.isalpha()
                and float(entry.get("confidence") or 1.0) < 0.60)
    for row in ocr_rows:
        report = read_json(row.get("report_path"), {}) or {}
        entries = report.get("recognitions") or []
        noise_ignored.extend({"frame": row.get("frame"), "text": e.get("text"), "confidence": e.get("confidence")}
                             for e in entries if _is_noise(e))
        strings = [str(entry.get("text") or "") for entry in entries if not _is_noise(entry)]
        recognised.extend(strings)
        hits = sorted({term for entry in report.get("recognitions") or []
                       for term in entry.get("forbidden_tokens") or []})
        frame_failures: list[str] = []
        if row.get("exit_code") not in (0, 1):
            frame_failures.append(f"OCR_RUN_FAILED:exit={row.get('exit_code')}")
        if not report:
            frame_failures.append("OCR_REPORT_UNREADABLE")
        all_noise = bool(entries) and all(_is_noise(e) for e in entries)
        if int(report.get("critical_text_failures") or 0) > 0 and not all_noise:
            frame_failures.append(
                f"OCR_CRITICAL_TEXT_FAILURES:{report.get('critical_text_failures')}")
        if int(report.get("latin_chars") or 0) > 0 and not all_noise:
            frame_failures.append(f"OCR_LATIN_CHARACTERS_PRESENT:{report.get('latin_chars')}")
        if hits:
            frame_failures.append("OCR_FORBIDDEN_TERM_VISIBLE:" + ",".join(hits))
        per_frame.append({
            "frame": row.get("frame"), "frame_sha256": row.get("frame_sha256"),
            "ocr_report": row.get("report_path"),
            "ocr_report_sha256": row.get("report_sha256"),
            "ocr_status": report.get("status"),
            "recognised_strings": strings,
            "failures": frame_failures,
        })
        failures.extend(f"{Path(str(row.get('frame'))).name}:{value}" for value in frame_failures)

    reviewer_text = [str(value) for value in
                     (item.get("observed") or {}).get("observed_text_strings") or []
                     if not str(value).startswith("NOISE:")]
    if recognised and not reviewer_text:
        # honesty cross-check: the OCR saw text the reviewer did not report.
        failures.append("OCR_TEXT_NOT_REPORTED_BY_REVIEWER:" + ",".join(recognised[:5]))

    checks = _checks(item, questionnaire, GATE_QUESTIONS[PERIOD_GATE])
    checks.append({
        "question_id": "closed_set_ocr_no_forbidden_term",
        "question": "Does a real RapidOCR pass over every extracted original-resolution frame "
                    "of this exact clip find any term from the closed forbidden set, any Latin "
                    "text, or any burned-in caption?",
        "answer": "PASS" if not failures else "FAIL",
        "method": "CLOSED_SET_ANACHRONISM_OCR_V1",
        "frames_scanned": len(ocr_rows),
        "ocr_recognised_strings": recognised,
        "reviewer_reported_strings": reviewer_text,
        "closed_set_size": len(forbidden_terms),
        "contract_derived": True,
    })
    decision = "PASS" if not failures and all(row["answer"] == "PASS" for row in checks) else "FAIL"
    verification = {
        "method": "CLOSED_SET_ANACHRONISM_OCR_V1",
        "decision": decision,
        "engine": "RapidOCR / ONNX Runtime via tools/still_image_ocr_audit.py",
        "closed_set_source": "anachronism_lock_gate.FORBIDDEN_VISIBLE_TERMS + this episode's "
                             "authored negative_prompts",
        "closed_set": forbidden_terms,
        "frames_scanned": len(ocr_rows),
        "per_frame": per_frame,
        "checks": checks,
        "failures": failures,
        "questions_must_be_closed_and_contract_derived": True,
    }
    return verification, failures


def build_identity_verification(item: dict[str, Any], questionnaire: dict[str, Any],
                                asset_sha: str, declared_ids: list[str],
                                measurement: dict[str, Any]
                                ) -> tuple[dict[str, Any], list[str], str]:
    """INSIGHTFACE_COSINE_V1 per unit, or the registry's no-character method."""
    checks = _checks(item, questionnaire, GATE_QUESTIONS[IDENTITY_GATE])
    if not declared_ids:
        failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
        observed = (item.get("observed") or {}).get("observed_visible_characters") or []
        if observed:
            failures.append("CHARACTER_OBSERVED_IN_CHARACTER_FREE_UNIT")
        verification = {
            "method": NO_CHARACTER_METHOD,
            "decision": "PASS" if not failures else "FAIL",
            "canonical_characters": [],
            "observed_visible_characters": observed,
            "checks": checks or [{
                "question_id": "no_visible_character",
                "question": "Is any living character visible anywhere in this clip?",
                "answer": "PASS"}],
            "failures": failures,
        }
        return verification, failures, NO_CHARACTER_METHOD

    params = gate_parameters(IDENTITY_GATE)
    exempt = dict(measurement.get("not_measurable_by_pose") or {})
    # A character whose face is declared in THIS unit to be back / hands-only / out of frame /
    # profile / distant may hold a sample whose cosine against its own canonical plate falls
    # under the registered fail threshold (Qin Ming seated back-to-camera in E11-VU-039: 0.028
    # and 0.073).  That is a statement about the pose, not about who the person is, and it was
    # already excluded from the measurement above (``excluded_non_measurable_samples`` /
    # ``excluded_unmeasurable_samples``); it must not become an identity failure further down
    # either.  ``measure_unit_identity`` reaches the same set through the generation contract's
    # own face_visibility codes (``pose_scoped_ids``); here the reviewer's structured exemption
    # covers what the contract does not spell out per frame.  Cosine thresholds, the sample
    # minimum and every real mismatch stay exactly as they are — a wrong face is still caught,
    # because its own samples pass the measurability floor and land on the aggregate.
    reviewer_exempt = (item.get("observed") or {}).get("identity_pose_exemptions") or {}
    if isinstance(reviewer_exempt, list):
        # The submitted reviews carry the list shape written by the reviewer template
        # ([{character_id, reason, frames, note}]); the dict shape is kept for older files.
        # Only the reason is needed downstream, and only for a declared character: an
        # exempted character is dropped from ``measurable_ids``, so it contributes no
        # aggregate and no sample-count failure, and the reason is recorded verbatim in
        # ``not_measurable_by_pose`` next to the frames the reviewer named.
        for row in reviewer_exempt:
            if not isinstance(row, dict):
                continue
            cid = str(row.get("character_id") or "")
            reason = str(row.get("reason") or "").strip()
            if cid in declared_ids and reason:
                frames = [value for value in (row.get("frames") or [])
                          if isinstance(value, (int, float))]
                exempt[cid] = f"REVIEWER:{reason}" + (f"@{frames[0]:g}s" if frames else "")
    elif isinstance(reviewer_exempt, dict):
        for cid, reason in reviewer_exempt.items():
            if cid in declared_ids and str(reason or "").strip():
                exempt[cid] = f"REVIEWER:{reason}"
    # ``measure_unit_identity`` records declared roles with no measurable face
    # separately.  They are absent-in-the-observed-frame roles, not failed
    # identity observations; keep the exclusion auditable while preventing the
    # downstream structured gate from resurrecting them as required samples.
    non_measurable = {
        str(cid) for cid in (measurement.get("non_measurable_declared_characters") or [])
    }
    measurable_ids = [cid for cid in declared_ids if cid not in exempt and cid not in non_measurable]
    if declared_ids and not measurable_ids:
        failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
        observed = (item.get("observed") or {}).get("observed_visible_characters") or []
        verification = {
            "method": "REVIEWER_STRUCTURED_IDENTITY_POSE_EXEMPT_D16",
            "measurement_scope": "VIDEO_UNIT_ALL_DECLARED_NOT_MEASURABLE_BY_POSE_D16",
            "decision": "PASS" if not failures else "FAIL",
            "canonical_characters": sorted(declared_ids),
            "not_measurable_by_pose": {**exempt, **{cid: "ENGINE_NO_MEASURABLE_FACE" for cid in sorted(non_measurable)}},
            "observed_visible_characters": observed,
            "output_sha256": asset_sha,
            "checks": checks,
            "failures": failures,
            "note": "every declared character is non-frontal in every shot of this unit (back / hands-only / "
                    "far / profile / eyes closed); identity judged by the reviewer against the locked plates over "
                    "the original-resolution frames, cosine thresholds unchanged (D-16 extended to video 2026-09-13)",
        }
        return verification, failures, "REVIEWER_STRUCTURED_IDENTITY_POSE_EXEMPT_D16"
    engine_rows = {str(d.get("character_id")): d for d in measurement.get("engine_decisions") or []}
    identity_answer = str((item.get("answers") or {}).get("each_visible_character_identity_recognisable") or "")
    rows = []
    for row in (measurement.get("per_character") or []):
        cid = row.get("character_id")
        if cid not in measurable_ids:
            continue
        row = dict(row)
        eng = engine_rows.get(cid) or {}
        if eng:
            row["cosine_vs_canonical"] = round(float(eng.get("aggregate_median")), 6)
            row["aggregate"] = "ENGINE_MEDIAN_OF_PER_FRAME_MAX_COSINE"
            row["engine_decision"] = str(eng.get("decision") or "MISSING")
            row["decision"] = row["engine_decision"]
            if row["engine_decision"] == "BOUNDARY_REQUIRES_HUMAN":
                # character_identity_admission_gate: 0.30 <= median < 0.45 requires human
                # arbitration.  The reviewer's structured identity answer over the face crops
                # vs the locked plates IS that arbitration (machine-QA policy, SUPERVISOR_ORDERS
                # seq=4); recorded, never silent.
                row["human_arbitration"] = {
                    "decision": "PASS" if identity_answer == "PASS" else "FAIL",
                    "arbiter": REVIEWER_ID, "review_method": REVIEW_METHOD,
                    "basis": "face crops of the sampled frames compared with the locked plates",
                }
                row["decision"] = row["human_arbitration"]["decision"]
        rows.append(row)
    failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
    measured = {row["character_id"] for row in rows}
    for char_id in measurable_ids:
        if char_id not in measured:
            failures.append(f"NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:{char_id}")
    for row in rows:
        if row["decision"] != "PASS":
            failures.append(f"IDENTITY_COSINE_BELOW_PASS:{row['character_id']}:"
                            f"{row['cosine_vs_canonical']}")
    counts = measurement.get("sample_counts") or {}
    achieved_samples = min((int(counts.get(cid) or 0) for cid in measurable_ids), default=0) if measurable_ids \
        else int(measurement.get("sample_frames_per_source_achieved_min") or 0)
    achieved_views = int(measurement.get("canonical_views_achieved_min") or 0)
    samples_min = int(params.get("sample_frames_per_source_min", 3))
    canonical_min = int(params.get("canonical_views_min", 3))
    if achieved_samples < samples_min:
        failures.append(f"SAMPLE_FRAMES_BELOW_REGISTRY_MINIMUM:{achieved_samples}<{samples_min}")
    if achieved_views < canonical_min:
        failures.append(f"CANONICAL_VIEWS_BELOW_REGISTRY_MINIMUM:{achieved_views}<{canonical_min}")
    failures.extend(str(value) for value in measurement.get("failures") or []
                    if not any(cid in str(value) for cid in exempt))

    verification = {
        "method": "INSIGHTFACE_COSINE_V1",
        "decision": "PASS" if not failures else "FAIL",
        "pass_threshold": float(params.get("embedding_cosine_pass_threshold", 0.45)),
        "fail_threshold": float(params.get("embedding_cosine_fail_threshold", 0.30)),
        "embedding_model": measurement.get("embedding_model"),
        "canonical_views_min": achieved_views,
        "sample_frames_per_source_min": achieved_samples,
        "canonical_characters": sorted(measurable_ids),
        "declared_characters_all": sorted(declared_ids),
        "not_measurable_by_pose": {**exempt, **{cid: "ENGINE_NO_MEASURABLE_FACE" for cid in sorted(non_measurable)}},
        "output_sha256": asset_sha,
        "decisions": [{**{key: value for key, value in row.items() if key != "samples"},
                       "output_sha256": asset_sha} for row in rows],
        "sample_scope": "this unit's own extracted original-resolution frames — a clip, unlike "
                        "a still, reaches sample_frames_per_source_min from ONE source",
        "engine_report": measurement.get("engine_report"),
        "engine_report_sha256": measurement.get("engine_report_sha256"),
        "engine_status": measurement.get("engine_status"),
        "checks": checks,
        "failures": failures,
    }
    return verification, failures, "INSIGHTFACE_COSINE_V1"



#: episode-scope context for defect_tolerance_gate (set once per materialise run)
_EPISODE_DEFECT_CONTEXT: dict[str, dict[str, Any]] = {}


def _episode_defect_context(episode: str, submitted: dict[str, Any], exp: "Expectations") -> dict[str, Any]:
    """Unit start offsets on the episode timeline, episode-global shot bases, episode shot
    count / duration, and every located P2 (MINOR) of the review, so the engine gate prices
    the real episode rather than a lone 4-10 s unit."""
    order = [str(u.get("unit_id")) for u in (exp.grouping.get("units") or [])]
    durations = {str(u.get("unit_id")): float(u.get("duration_seconds") or 0) for u in (exp.grouping.get("units") or [])}
    shots = {str(u.get("unit_id")): [str(x) for x in (u.get("editorial_shot_ids") or [])] for u in (exp.grouping.get("units") or [])}
    offsets, bases = {}, {}
    t, n = 0.0, 0
    for uid in order:
        offsets[uid] = t; bases[uid] = n
        t += durations.get(uid, 0.0); n += len(shots.get(uid) or [])
    minors = []
    for it in submitted.get("items") or []:
        uid = it["item_id"]
        for defect in it.get("defects") or []:
            if str(defect.get("severity")) != "P2":
                continue
            si, at = defect.get("shot_index"), defect.get("at_seconds")
            if not isinstance(si, int) or not isinstance(at, (int, float)):
                continue
            minors.append({"severity": "MINOR", "scope": "SHOT", "category": str(defect.get("code") or "UNCODED"),
                           "shot_index": int(si) + bases.get(uid, 0), "unit_shot_index": int(si), "unit_id": uid,
                           "start_seconds": float(at) + offsets.get(uid, 0.0),
                           "end_seconds": float(defect.get("to_seconds") or at) + offsets.get(uid, 0.0),
                           "reviewer_severity": "P2", "description": defect.get("description")})
    return {"unit_offsets": offsets, "shot_base": bases, "shot_count": n, "duration_seconds": t,
            "episode_minors": minors, "unit_order": order}

def build_defect_tolerance(episode: str, item: dict[str, Any], expectations: dict[str, Any],
                          prepared: dict[str, Any], out_dir: Path
                          ) -> tuple[dict[str, Any], list[str]]:
    """Build the defect_tolerance_gate.py input from the reviewer's own defects
    and RUN the engine gate for real.

    Severity mapping is the reviewer's, never this tool's: P0/P1 -> BLOCKER,
    P2 -> MINOR.  A MINOR needs a location (``shot_index`` 1-based inside the
    unit's editorial_shot_ids, and ``at_seconds``) because
    defect_tolerance_gate.py prices the opening-10s / tail-5s zero-tolerance
    windows and the three-consecutive escalation from it.  A P2 with no declared
    location is NOT guessed and NOT dropped — the unit is REJECTED with
    DEFECT_TIER_LOCATION_MISSING and the reviewer is asked to locate it.
    """
    failures: list[str] = []
    shot_ids = [str(value) for value in expectations.get("editorial_shot_ids") or []]
    shot_count = len(shot_ids)
    duration = prepared.get("duration_seconds")
    if not shot_count:
        failures.append("UNIT_HAS_NO_EDITORIAL_SHOT_IDS")
    if not duration:
        failures.append("UNIT_DURATION_UNMEASURED")
    ctx = _EPISODE_DEFECT_CONTEXT.get(episode) or {}
    unit_offset = float((ctx.get("unit_offsets") or {}).get(item["item_id"], 0.0))
    shot_base = int((ctx.get("shot_base") or {}).get(item["item_id"], 0))
    defects_out: list[dict[str, Any]] = []
    for index, defect in enumerate(item.get("defects") or [], 1):
        severity = str(defect.get("severity") or "")
        code = str(defect.get("code") or f"UNCODED_{index}")
        if severity in {"P0", "P1"}:
            defects_out.append({
                "severity": "BLOCKER", "scope": "EPISODE", "category": code,
                "reviewer_severity": severity,
                "description": defect.get("description")})
            continue
        if severity != "P2":
            failures.append(f"DEFECT_SEVERITY_UNMAPPABLE:{code}:{severity or 'MISSING'}")
            continue
        shot_index = defect.get("shot_index")
        at_seconds = defect.get("at_seconds")
        if not isinstance(shot_index, int) or shot_index < 1 or shot_index > max(shot_count, 1):
            failures.append(f"DEFECT_TIER_LOCATION_MISSING:{code}:shot_index={shot_index!r}")
            continue
        if not isinstance(at_seconds, (int, float)):
            failures.append(f"DEFECT_TIER_LOCATION_MISSING:{code}:at_seconds={at_seconds!r}")
            continue
        defects_out.append({
            "severity": "MINOR", "scope": "SHOT", "category": code,
            "shot_index": int(shot_index) + shot_base,            # episode-global shot index
            "unit_shot_index": int(shot_index),
            "unit_id": item["item_id"],
            "start_seconds": float(at_seconds) + unit_offset,      # episode timeline seconds
            "end_seconds": float(defect.get("to_seconds") or at_seconds) + unit_offset,
            "unit_at_seconds": float(at_seconds),
            "reviewer_severity": severity,
            "description": defect.get("description")})

    # episode-wide evaluation: this unit's rows plus every other unit's located minors
    other_minors = [row for row in (ctx.get("episode_minors") or []) if row.get("unit_id") != item["item_id"]]
    report_in = {
        "schema": "qingshan.defect_tolerance_report_input.v1",
        "episode": episode,
        "unit_id": item["item_id"],
        "evaluation_scope": "EPISODE" if ctx else "UNIT",
        "shot_count": int(ctx.get("shot_count") or shot_count),
        "duration_seconds": float(ctx.get("duration_seconds") or duration or 0),
        "unit_offset_seconds": unit_offset,
        "unit_shot_count": shot_count,
        "defects": defects_out + other_minors,
        "this_unit_defects": defects_out,
        "conditional_admission_overrides": [],
        "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD,
        "source": "the video_q2 reviewer's own defect list, severity unchanged",
        "recorded_at": now(), "recorded_by": TOOL_ID,
    }
    input_path = write_json(out_dir / "defect_tolerance_input.json", report_in)
    gate_out = out_dir / "defect_tolerance_gate.json"
    completed = _run([str(VENV), str(ENGINE / "tools/defect_tolerance_gate.py"),
                      "--report", str(input_path), "--out", str(gate_out)], timeout=600)
    report = read_json(gate_out, {}) or {}
    if completed.returncode not in (0, 2):
        failures.append(f"DEFECT_TOLERANCE_GATE_RUN_FAILED:exit={completed.returncode}")
    if not report:
        failures.append("DEFECT_TOLERANCE_GATE_REPORT_UNREADABLE")
    override_note = None
    if report.get("status") != "PASS":
        gate_failures = list(report.get("failures") or [])
        # operator override (nalu_runtime/preproduction/<EP>/qa_overrides.json): a delegated
        # human decision may accept the episode minor-shot budget overrun; recorded verbatim,
        # only that one failure code, only up to the authorised percentage.
        ov_path = Path(f"{_np.RUNTIME_ROOT}/preproduction") / episode / "qa_overrides.json"
        ov = ((json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.is_file() else {})
              .get("defect_tolerance_minor_budget_override") or {})
        allowed = set(ov.get("overrides") or [])
        pct = float(report.get("minor_shot_pct") or 0)
        if gate_failures and all(f in allowed for f in gate_failures) and pct <= float(ov.get("max_minor_shot_pct") or 0):
            override_note = {"operator_override": True, "overridden_failures": gate_failures,
                             "minor_shot_pct": pct, "authorized_by": ov.get("authorized_by"),
                             "reason": ov.get("reason"), "config": str(ov_path)}
        else:
            failures.extend(f"DEFECT_TIER:{value}" for value in gate_failures)
    block = {
        **({"operator_override": override_note} if override_note else {}),
        "gate_id": DEFECT_GATE,
        "engine_tool": str(ENGINE / "tools/defect_tolerance_gate.py"),
        "gate_argv": [str(VENV), str(ENGINE / "tools/defect_tolerance_gate.py"),
                      "--report", str(input_path), "--out", str(gate_out)],
        "gate_exit_code": completed.returncode,
        "input_report": str(input_path),
        "input_report_sha256": sha256_file(input_path),
        "defect_tolerance_report": report,
        "defect_tolerance_report_path": str(gate_out),
        "defect_tolerance_report_sha256": sha256_file(gate_out),
        "thresholds_source": "tools/defect_tolerance_gate.py, mirroring "
                             "GATE_REGISTRY DEFECT-TIER-TOLERANCE.parameters",
        "reviewer_defects": item.get("defects") or [],
        "failures": failures,
    }
    return block, failures


# --------------------------------------------------------------------------- #
# evidence + request assembly, then the real gate invocation
# --------------------------------------------------------------------------- #
def _evidence_file(out: Path, *, gate_id: str, episode: str, unit_id: str,
                   asset: Path, asset_sha: str, finding: str,
                   verification: dict[str, Any] | None,
                   extra: dict[str, Any] | None,
                   reviewed_at: str | None, review_frames: list[str]) -> dict[str, Any]:
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "gate_id": gate_id,
        "status": "PASS_ORIGINAL_RESOLUTION" if (
            verification is None or verification.get("decision") == "PASS") else "FAIL_NOT_ADMITTED",
        "episode": episode,
        "unit_id": unit_id,
        "reviewed_asset_path": portable(asset),
        "reviewed_asset_absolute_path": str(asset),
        "reviewed_asset_sha256": asset_sha,
        "original_resolution_review": True,
        "review_frames": review_frames,
        "reviewer_type": REVIEWER_TYPE,
        "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD,
        "reviewed_at": reviewed_at,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "finding": finding,
    }
    if verification is not None:
        payload["objective_verification"] = verification
    for key, value in (extra or {}).items():
        payload[key] = value
    write_json(out, payload)
    return payload


Q2_ACCEPTANCE_GATE_ID = "VIDEO-Q2-ASSEMBLY-ADMISSION"


def _q2_acceptance_detectors(unit_id: str, failures: list[Any]) -> list[str]:
    """"<unit>:<registered gate id>" for every gate the engine reported not passing.

    The order names gates, not measured values (a P2 list or an OCR string changes with
    every take); the media sha binding is what pins the take."""
    gates = set()
    for failure in failures:
        text = str(failure)
        match = re.search(r"([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+)", text)
        gates.add(match.group(1) if match else text)
    return sorted(f"{unit_id}:{gate}" for gate in gates)


def _line_owner_q2_acceptance(episode: str, unit_id: str, asset_sha: str,
                              result: dict[str, Any], result_path: Path) -> dict[str, Any] | None:
    """Admit a Q2-rejected unit only on an explicit, media-bound line-owner order.

    Same contract as the S5 Q1 overlay (nalu_pipeline.apply_line_owner_q1_acceptance) and the
    S6 post-generation overlay (post_generation_qa_runner.apply_roger_postgen_acceptance): an
    active GATE_FAIL_ACCEPTANCE order for this episode and gate VIDEO-Q2-ASSEMBLY-ADMISSION whose
    detectors cover EVERY failing gate of this unit and whose media_sha256_by_item[<unit>] equals
    this exact take.  Q2 had no such channel (E09 seq=15 had to be resolved by the reviewer
    withdrawing a P2 instead); added 2026-10-01 so a reviewer's honest defect list never has to be
    rewritten to pass.  The engine's own admission_result stays on disk next to the acceptance."""
    failures = list(result.get("failures") or [])
    if not failures:
        return None
    try:
        import roger_gate_acceptance as _rga
    except ImportError:
        return None
    orders_path = os.environ.get("NALU_SUPERVISOR_ORDERS_PATH")
    if not orders_path:
        return None
    try:
        expected_latest_seq = int(os.environ.get("NALU_LATEST_ORDER_SEQ") or 0)
    except ValueError:
        expected_latest_seq = 0
    orders = _rga._orders(Path(orders_path), expected_latest_seq=expected_latest_seq, engine_root=ENGINE)
    detectors = _q2_acceptance_detectors(unit_id, failures)
    order = _rga.find_acceptance(
        orders, episode=episode, gate_id=Q2_ACCEPTANCE_GATE_ID, failing=detectors,
        media_sha256=asset_sha, media_item_id=unit_id,
        expected_issuer=str(os.environ.get("NALU_LINE_OWNER_ID") or "Roger"), engine_root=ENGINE)
    bound = str(((order or {}).get("decision") or {}).get("media_sha256_by_item", {}).get(unit_id) or "")
    if order is None or bound != asset_sha:
        return None
    record = _rga.acceptance_record(order, episode=episode, gate_id=Q2_ACCEPTANCE_GATE_ID,
                                    failing=detectors, media_sha256=asset_sha, media_item_id=unit_id,
                                    gate_result_path=str(result_path))
    record.update({"unit_id": unit_id, "engine_status": result.get("status"),
                   "engine_downstream_status": result.get("downstream_status"),
                   "engine_failures": failures})
    engine_copy = result_path.with_suffix(".engine.json")
    if result_path.is_file():
        write_json(engine_copy, result)
    write_json(result_path, {**result, "engine_status": result.get("status"),
                             "engine_downstream_status": result.get("downstream_status"),
                             "engine_failures": failures, "engine_result_copy": str(engine_copy),
                             "status": "ADMITTED_BY_LINE_OWNER_ORDER",
                             "downstream_status": TERMINAL_DOWNSTREAM, "failures": [],
                             "line_owner_acceptance": record})
    return record


def materialise(episode: str, submitted: dict[str, Any],
                submitted_path: Path) -> dict[str, Any]:
    """Build one VIDEO_ASSEMBLY admission request per unit and run the ENGINE gate."""
    p = QaPaths(episode)
    exp = Expectations(episode)
    _EPISODE_DEFECT_CONTEXT[episode] = _episode_defect_context(episode, submitted, exp)
    questionnaire = submitted.get("questionnaire") or {}
    reviewed_at = submitted.get("reviewed_at")
    forbidden_terms = exp.forbidden_terms()
    review_sha = sha256_file(submitted_path)
    postgen = {row["unit_id"]: row for row in [
        read_json(path, {}) or {} for path in
        sorted(p.postgen_dir.glob("*/*_POST_GENERATION_QA.json"))] if row.get("unit_id")}

    rows: list[dict[str, Any]] = []
    for item in submitted.get("items") or []:
        unit_id = item["item_id"]
        request_item = item.get("request_item") or {}
        expectations = request_item.get("expectations") or {}
        unit_dir = p.q2_dir / unit_id
        unit_dir.mkdir(parents=True, exist_ok=True)
        prepared = read_json(unit_dir / "prepare.json", {}) or {}
        asset = unit_media(episode, unit_id)
        if not asset.is_file():
            rows.append({"unit_id": unit_id, "status": "REJECTED",
                         "downstream_status": "FAIL_NOT_ADMITTED",
                         "failures": [f"UNIT_VIDEO_NOT_DOWNLOADED:{asset}"]})
            continue
        asset_sha = sha256_file(asset)
        blockers: list[str] = []
        if prepared.get("media_sha256") and prepared["media_sha256"] != asset_sha:
            blockers.append("PREPARE_STALE_MEDIA_CHANGED_RERUN_prepare")
        frame_rows = (prepared.get("frames") or {}).get("frames") or []
        review_frames = [str(row.get("path")) for row in frame_rows]

        # -- technical_qa: verbatim from the D-6 runner, never re-declared here
        record = postgen.get(unit_id) or {}
        technical = record.get("technical_qa") or {}
        roger_acceptance = record.get("roger_acceptance")
        if technical.get("status") != "TECHNICAL_PASS_CONTENT_UNREVIEWED" and not roger_acceptance:
            blockers.append("POST_GENERATION_TECHNICAL_QA_NOT_"
                            f"TECHNICAL_PASS_CONTENT_UNREVIEWED:{technical.get('status')}")
        if technical.get("reviewed_asset_sha256") != asset_sha:
            blockers.append("POST_GENERATION_TECHNICAL_QA_SHA_STALE")
        if record.get("verdict") != "ADMIT":
            blockers.append(f"POST_GENERATION_QA_VERDICT_{record.get('verdict') or 'MISSING'}")

        declared = list(expectations.get("required_visible_character_ids") or [])
        ocr_rows = prepared.get("ocr") or []
        identity_measurement = prepared.get("identity") or {}

        period_v, period_f = build_period_verification(
            item, questionnaire, ocr_rows, forbidden_terms)
        identity_v, identity_f, identity_method = build_identity_verification(
            item, questionnaire, asset_sha, declared, identity_measurement)
        action_checks = _checks(item, questionnaire, GATE_QUESTIONS[ACTION_GATE])
        action_failed = [row["question_id"] for row in action_checks if row["answer"] != "PASS"]
        # CAMERA_GRAMMAR_V1 objective face count (absent from prepare.json otherwise): a count FAIL makes
        # cast_exactly_as_declared fail in both gates that ask it, whatever the reviewer answered.
        face_count = prepared.get("face_count")
        if apply_face_count(face_count, action_checks, action_failed):
            if identity_f is not identity_v.get("failures"):
                identity_f = list(identity_f)
            apply_face_count(face_count, identity_v.setdefault("checks", []), identity_f)
            identity_v["failures"] = identity_f
            identity_v["decision"] = "FAIL"
            identity_v["face_count"] = face_count
        # CAMERA_GRAMMAR_V1 objective speaker framing (absent otherwise): the declared on-screen speaker
        # cramped / cut at the frame edge / out of frame in >= 1/3 of the frames fails the same question.
        speaker_framing = prepared.get("speaker_framing")
        if apply_speaker_framing(speaker_framing, action_checks, action_failed):
            if identity_f is not identity_v.get("failures"):
                identity_f = list(identity_f)
            apply_speaker_framing(speaker_framing, identity_v.setdefault("checks", []), identity_f)
            identity_v["failures"] = identity_f
            identity_v["decision"] = "FAIL"
            identity_v["speaker_framing"] = speaker_framing
        action_v = {
            "method": "VLM_STRUCTURED_STATE_QA_V1",
            "decision": "PASS" if not action_failed else "FAIL",
            "reviewer": REVIEWER_ID,
            "review_method": REVIEW_METHOD,
            "review_file": str(submitted_path),
            "review_file_sha256": review_sha,
            "contract_derived_from": {
                "entry_state": expectations.get("entry_state"),
                "required_completion_state": expectations.get("required_completion_state"),
                "ordered_beats": expectations.get("ordered_beats"),
                "required_visible_characters": expectations.get("required_visible_characters"),
                "required_visible_props": expectations.get("required_visible_props"),
                "camera": expectations.get("camera"),
                "wardrobe": expectations.get("wardrobe"),
            },
            "observed": item.get("observed"),
            "observation": item.get("observation"),
            "checks": action_checks,
            "questions_must_be_closed_and_contract_derived": True,
            "scope_note": "no forbidden post-generation check (gesture / microexpression / "
                          "choreography / trajectory / optical-flow / motion-energy) is asked; "
                          "see post_generation_qa_scope_gate.FORBIDDEN_POST_GENERATION_CHECKS",
            "failures": action_failed,
            **({"objective_face_count": face_count} if face_count else {}),
            **({"objective_speaker_framing": speaker_framing} if speaker_framing else {}),
        }
        scene_checks = _checks(item, questionnaire, GATE_QUESTIONS[SCENE_GATE])
        scene_failed = [row["question_id"] for row in scene_checks if row["answer"] != "PASS"]
        defect_block, defect_failed = build_defect_tolerance(
            episode, item, expectations, prepared, unit_dir)
        defect_answers = _checks(item, questionnaire, GATE_QUESTIONS[DEFECT_GATE])
        defect_failed = list(defect_failed) + [row["question_id"] for row in defect_answers
                                               if row["answer"] != "PASS"]

        blocking = [d for d in item.get("defects") or []
                    if str(d.get("severity")) in {"P0", "P1"}]
        p2 = [d for d in item.get("defects") or [] if str(d.get("severity")) == "P2"]

        specs = [
            (IDENTITY_GATE, identity_v, identity_f, None,
             f"{identity_method}: " + ("canonical identity measured over "
                                       f"{len(frame_rows)} original-resolution frames for "
                                       + ",".join(sorted(declared)) if declared else
                                       "no canonical character declared visible; structured "
                                       "no-character scope")),
            (SCENE_GATE, None, scene_failed,
             {"checks": scene_checks, "reviewer": REVIEWER_ID,
              "review_method": REVIEW_METHOD, "review_file": str(submitted_path),
              "review_file_sha256": review_sha,
              "contract_derived_from": {
                  "required_space_anchors": expectations.get("required_space_anchors"),
                  "space": expectations.get("space"),
                  "scene_state": expectations.get("scene_state"),
                  "key_light": expectations.get("key_light"),
                  "palette": expectations.get("palette")},
              "failures": scene_failed},
             "Mapped space, camera axis, lighting and time reviewed over the whole clip "
             f"against {expectations.get('space')} / {expectations.get('scene_state')}"),
            (ACTION_GATE, action_v, action_failed, None,
             "Declared entry state -> completion state handoff, cast, props, wardrobe and "
             "beat set reviewed at original resolution"),
            (PERIOD_GATE, period_v, period_f, None,
             f"Closed-set OCR over {len(forbidden_terms)} forbidden terms on "
             f"{len(ocr_rows)} original-resolution frames plus reviewed visible elements"),
            (DEFECT_GATE, None, defect_failed, defect_block,
             "Real tools/defect_tolerance_gate.py run over the reviewer's own defect list "
             f"({len(blocking)} blocking, {len(p2)} P2) at the unit's measured duration"),
        ]
        evidence: list[dict[str, Any]] = []
        for gate_id, verification, gate_failures, extra, finding in specs:
            failed = bool(gate_failures)
            prefix = "FAIL: " if failed else "PASS: "
            evidence_path = unit_dir / f"{gate_id.lower().replace('-', '_')}_evidence.json"
            payload = _evidence_file(
                evidence_path, gate_id=gate_id, episode=episode, unit_id=unit_id,
                asset=asset, asset_sha=asset_sha,
                finding=prefix + finding + (
                    ("  failures=" + ",".join(map(str, gate_failures))) if failed else ""),
                verification=verification, extra=extra, reviewed_at=reviewed_at,
                review_frames=review_frames)
            if failed and payload["status"] == "PASS_ORIGINAL_RESOLUTION":
                # a non-P0 gate has no objective_verification to carry the verdict,
                # so the file's own status has to say FAIL — the gate cross-checks it.
                payload["status"] = "FAIL_NOT_ADMITTED"
                write_json(evidence_path, payload)
            defect_tier = None
            if failed:
                defect_tier = "P0" if gate_id in {IDENTITY_GATE, ACTION_GATE, PERIOD_GATE} else "P1"
            elif p2:
                defect_tier = "P2"
            evidence.append({
                "gate_id": gate_id,
                "status": "FAIL_NOT_ADMITTED" if failed else "PASS_ORIGINAL_RESOLUTION",
                "reviewed_asset_sha256": asset_sha,
                "evidence_path": portable(evidence_path),
                "evidence_sha256": sha256_file(evidence_path),
                "original_resolution_review": True,
                "reviewer_type": REVIEWER_TYPE,
                "defect_tier": defect_tier,
                "p2_within_budget": bool(p2) and not failed
                                   and (defect_block.get("defect_tolerance_report") or {}
                                        ).get("status") == "PASS",
                "finding": prefix + finding,
            })

        request = {
            "schema": REQUEST_SCHEMA,
            "kind": KIND,
            "episode": episode,
            "unit_id": unit_id,
            "task_key": unit_id,
            "asset_path": portable(asset),
            "asset_sha256": asset_sha,
            "evidence": evidence,
            # VIDEO_ASSEMBLY: the gate demands EXACTLY this string (:639-642), UNLESS
            # line_owner_acceptance is a genuine, sha-bound, non-self-issued Roger
            # order (verified independently by the gate itself, never trusted blind).
            "technical_qa": {
                "status": technical.get("status"),
                "reviewed_asset_sha256": technical.get("reviewed_asset_sha256"),
                "measured_by": technical.get("measured_by"),
                "allowed_scope": technical.get("allowed_scope"),
                "line_owner_acceptance": roger_acceptance,
                "evidence_path": portable(p.postgen_dir / unit_id
                                          / f"{unit_id}_POST_GENERATION_QA.json"),
                "evidence_sha256": sha256_file(p.postgen_dir / unit_id
                                               / f"{unit_id}_POST_GENERATION_QA.json"),
            },
            "review_provenance": {
                "reviewer": REVIEWER_ID,
                "review_method": REVIEW_METHOD,
                "review_file": str(submitted_path),
                "review_file_sha256": review_sha,
                "request_file": submitted.get("request_path"),
                "request_file_sha256": submitted.get("request_sha256"),
                "reviewed_at": reviewed_at,
                "vlm_verdict": item["verdict"],
                "defects": item.get("defects") or [],
                "original_resolution_frames": review_frames,
                "contact_sheet": str(p.postgen_dir / unit_id / "contact_sheet_2fps.png"),
            },
            "orchestration_blockers": blockers,
            "recorded_at": now(),
            "recorded_by": TOOL_ID,
        }
        request_path = write_json(unit_dir / "admission_request.json", request)
        result_path = unit_dir / "admission_result.json"
        argv = [str(VENV), str(ENGINE / "tools/shot_media_admission_gate.py"),
                "--admission", str(request_path), "--registry", str(GATE_REGISTRY),
                "--out", str(result_path)]
        completed = _run(argv, timeout=900)
        result = read_json(result_path, {}) or {}
        downstream = result.get("downstream_status") or "FAIL_NOT_ADMITTED"
        if blockers and downstream == TERMINAL_DOWNSTREAM:
            # the gate cannot see an orchestration precondition (a stale prepare,
            # a missing D-6 record).  Never report an admission we do not have.
            downstream = "FAIL_NOT_ADMITTED"
        acceptance = None
        if downstream != TERMINAL_DOWNSTREAM and not blockers:
            acceptance = _line_owner_q2_acceptance(episode, unit_id, asset_sha, result, result_path)
            if acceptance:
                downstream = TERMINAL_DOWNSTREAM
        rows.append({
            "unit_id": unit_id,
            "asset_path": str(asset),
            "asset_sha256": asset_sha,
            "vlm_verdict": item["verdict"],
            "status": result.get("status") or "GATE_DID_NOT_RUN",
            "downstream_status": downstream,
            "gate_downstream_status": result.get("downstream_status"),
            "passing_registered_gates": result.get("passing_registered_gates") or [],
            "conditional_p2_registered_gates": result.get("conditional_p2_registered_gates") or [],
            "failures": (result.get("failures") or []) + blockers,
            "orchestration_blockers": blockers,
            "line_owner_acceptance": acceptance,
            "gate_exit_code": completed.returncode,
            "gate_argv": argv,
            "gate_stdout": (completed.stdout or "").strip()[-1000:],
            "gate_stderr": (completed.stderr or "").strip()[-1000:],
            "admission_request": str(request_path),
            "admission_result": str(result_path),
            "admission_result_sha256": sha256_file(result_path),
            "ai_review_result": str(write_json(unit_dir / "ai_review.json", {
                # the shape tools/build_agentcut_from_admitted_storyboard_sources.py
                # reads: passed_items[].path, unioned across --review-result files.
                "schema": "nalu.video_q2_ai_review_result.v1",
                "episode": episode, "unit_id": unit_id,
                "reviewer": REVIEWER_ID, "review_method": REVIEW_METHOD,
                "reviewed_at": reviewed_at,
                "review_file": str(submitted_path), "review_file_sha256": review_sha,
                "admission_result": str(result_path),
                "admission_status": result.get("status"),
                "downstream_status": downstream,
                "passed_items": ([{"path": str(asset), "sha256": asset_sha,
                                   "unit_id": unit_id,
                                   "admission_result": str(result_path)}]
                                 if downstream == TERMINAL_DOWNSTREAM else []),
                "content_failed_items": ([] if downstream == TERMINAL_DOWNSTREAM else
                                         [{"path": str(asset), "unit_id": unit_id,
                                           "failures": (result.get("failures") or []) + blockers}]),
                "recorded_at": now(), "recorded_by": TOOL_ID,
            })),
            # the RECEIPT shape tools/build_agentcut_from_admitted_storyboard_sources.py reads:
            # tasks[].source_id / output_path / status qa_pass / duration / metadata.selected_dialogue
            "assembly_receipt": str(write_json(unit_dir / "assembly_receipt.json", {
                "schema": "nalu.video_assembly_receipt.v1",
                "episode": episode, "unit_id": unit_id,
                "admission_result": str(result_path), "downstream_status": downstream,
                "tasks": ([{
                    "source_id": unit_id, "task_id": unit_id,
                    "output_path": str(asset), "sha256": asset_sha,
                    "status": "qa_pass",
                    "duration": float(prepared.get("duration_seconds") or 0) or None,
                    "metadata": {
                        "beat_id": unit_id,
                        "selected_dialogue": [
                            {"text": (str(row.get("spoken_text") or "").split("：", 1)[1]
                                      if "：" in str(row.get("spoken_text") or "")[:8]
                                      else str(row.get("spoken_text") or "")),
                             "shot_id": row.get("shot_id")}
                            for row in (expectations.get("expected_dialogue") or [])],
                        "silent_visual_replacement": False,
                        "q2_admission": str(result_path),
                    },
                }] if downstream == TERMINAL_DOWNSTREAM else []),
                "recorded_at": now(), "recorded_by": TOOL_ID,
            })),
            "identity_status": identity_measurement.get("status"),
            "identity_method": identity_method,
            **({"objective_face_count": {k: face_count.get(k) for k in
                                         ("status", "declared_face_budget", "frames_over", "failure", "reason")
                                         if k in face_count}} if face_count else {}),
            **({"objective_speaker_framing": {
                **{k: speaker_framing.get(k) for k in ("status", "speaker_ids", "speaker_identity", "frames_flagged",
                                                       "frames_sampled", "failure", "reason")
                   if k in speaker_framing},
                "per_frame": [{k: v for k, v in r.items() if k != "speaker_similarity"}
                              for r in speaker_framing.get("per_frame") or []]}} if speaker_framing else {}),
            "defect_tolerance_status": (defect_block.get("defect_tolerance_report") or {}
                                        ).get("status"),
            "frames_reviewed": len(review_frames),
            "blocking_defects": blocking,
            "p2_defects": p2,
        })

    admitted = [row for row in rows if row.get("downstream_status") == TERMINAL_DOWNSTREAM]
    index = {
        "schema": "nalu.video_q2_admission_index.v1",
        "episode": episode,
        "recorded_at": now(), "recorded_by": TOOL_ID,
        "reviewer": REVIEWER_ID, "review_method": REVIEW_METHOD,
        "review_file": str(submitted_path), "review_file_sha256": review_sha,
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "gate_registry": str(GATE_REGISTRY),
        "kind": KIND,
        "required_registered_gates": list(REQUIRED_GATES),
        "terminal_state_required": f"status ADMITTED|ADMITTED_WITH_P2 + "
                                  f"downstream_status {TERMINAL_DOWNSTREAM}",
        "status": ("ALL_ADMITTED" if rows and len(admitted) == len(rows)
                   else f"PARTIAL_{len(admitted)}_OF_{len(rows)}_ADMITTED" if rows
                   else "NO_ITEMS"),
        "unit_count": len(rows),
        "admitted_count": len(admitted),
        "assembly_allowed_unit_ids": [row["unit_id"] for row in admitted],
        "rejected_unit_ids": [row["unit_id"] for row in rows if row not in admitted],
        "receipts": [row["assembly_receipt"] for row in admitted if row.get("assembly_receipt")],
        "admission_results": [row["admission_result"] for row in rows if row.get("admission_result")],
        "review_results": [row["ai_review_result"] for row in rows if row.get("ai_review_result")],
        "results": rows,
    }
    out = write_json(p.q2_dir / f"{episode}_VIDEO_Q2_INDEX.json", index)
    index["_written_to"] = str(out)
    return index


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def route_status(episode: str) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    units = [row["unit_id"] for row in exp.video_unit_items()]
    media = [uid for uid in units if unit_media(episode, uid).is_file()]
    postgen = sorted(p.postgen_dir.glob("*/*_POST_GENERATION_QA.json"))
    index_path = p.q2_dir / f"{episode}_VIDEO_Q2_INDEX.json"
    index = read_json(index_path, {}) or {}
    prepare_path = p.q2_dir / f"{episode}_VIDEO_Q2_PREPARE.json"
    prepared = read_json(prepare_path, {}) or {}
    ocr_ok, ocr_err = True, None
    try:
        __import__("rapidocr_onnxruntime")
    except Exception as exc:  # noqa: BLE001
        ocr_ok, ocr_err = False, f"{type(exc).__name__}: {exc}"
    insight_ok, insight_err = True, None
    try:
        __import__("insightface")
    except Exception as exc:  # noqa: BLE001
        insight_ok, insight_err = False, f"{type(exc).__name__}: {exc}"
    stale = []
    for row in index.get("results") or []:
        asset = Path(str(row.get("asset_path") or ""))
        if row.get("asset_sha256") and sha256_file(asset) != row.get("asset_sha256"):
            stale.append(row.get("unit_id"))
    blockers = []
    if not units:
        blockers.append("UNIT_PLAN_ABSENT_RUN_S2")
    if len(media) < len(units):
        blockers.append(f"UNIT_VIDEO_NOT_DOWNLOADED:{len(media)}/{len(units)}")
    if not postgen:
        blockers.append("POST_GENERATION_QA_RECORDS_ABSENT_RUN_S6_QA")
    if prepared.get("status") not in (None, "READY") and media:
        blockers.append(f"PREPARE_{prepared.get('status')}")
    if stale:
        blockers.append("Q2_RECEIPTS_STALE_MEDIA_CHANGED:" + ",".join(map(str, stale)))
    if index.get("status") not in (None, "ALL_ADMITTED") and media:
        blockers.append(f"Q2_{index.get('status')}")
    return {
        "builder": f"{__file__} build --episode {episode} --review <submitted video_q2 review>",
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "kind": KIND,
        "required_registered_gates": list(REQUIRED_GATES),
        "objective_methods": {IDENTITY_GATE: "INSIGHTFACE_COSINE_V1",
                              ACTION_GATE: "VLM_STRUCTURED_STATE_QA_V1",
                              PERIOD_GATE: "CLOSED_SET_ANACHRONISM_OCR_V1",
                              DEFECT_GATE: "tools/defect_tolerance_gate.py (real run)"},
        "terminal_state_required": f"status ADMITTED|ADMITTED_WITH_P2 + "
                                  f"downstream_status {TERMINAL_DOWNSTREAM}",
        "unit_count": len(units),
        "unit_media_on_disk": len(media),
        "post_generation_qa_records": len(postgen),
        "ocr_runtime_available": ocr_ok, "ocr_runtime_error": ocr_err,
        "insightface_runtime_available": insight_ok, "insightface_runtime_error": insight_err,
        "closed_set_size": len(exp.forbidden_terms()),
        "prepare_index": str(prepare_path), "prepare_status": prepared.get("status"),
        "q2_index": str(index_path), "q2_index_present": index_path.is_file(),
        "q2_status": index.get("status"),
        "admitted_count": index.get("admitted_count"),
        "assembly_allowed_unit_ids": index.get("assembly_allowed_unit_ids") or [],
        "receipts": index.get("receipts") or [],
        "review_results": index.get("review_results") or [],
        "stale_receipts": stale,
        "blockers": blockers,
        "status": "READY" if (index.get("status") == "ALL_ADMITTED" and not blockers)
                  else "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("prepare", help="extract original-resolution frames, run OCR + identity")
    pre.add_argument("--episode", required=True)
    pre.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    pre.add_argument("--unit", action="append", default=[])

    build = sub.add_parser("build", help="build the VIDEO_ASSEMBLY admission and run the gate")
    build.add_argument("--episode", required=True)
    build.add_argument("--review", required=True, type=Path)

    stat = sub.add_parser("status", help="route readiness")
    stat.add_argument("--episode", required=True)

    sfc = sub.add_parser("start-frame-check",
                         help="CAMERA_GRAMMAR_V1: speaker framing + face count of one candidate (tail) start frame")
    sfc.add_argument("--episode", required=True)
    sfc.add_argument("--unit", required=True)
    sfc.add_argument("--image", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "start-frame-check":
        print(json.dumps(check_start_frame(args.episode, args.unit, args.image), ensure_ascii=False))
        return 0
    if args.command == "prepare":
        summary = prepare(args.episode, frames=args.frames, units=args.unit or None)
        print(json.dumps({key: value for key, value in summary.items() if key != "units"},
                         ensure_ascii=False))
        return 0 if summary["status"] == "READY" else 2
    if args.command == "build":
        submitted = read_json(args.review)
        if not isinstance(submitted, dict) or submitted.get("kind") != "video_q2":
            raise SystemExit(f"not a video_q2 submitted review: {args.review}")
        if (submitted.get("validation") or {}).get("status") != "PASS":
            raise SystemExit(f"review did not validate: {args.review}")
        index = materialise(args.episode, submitted, Path(args.review))
        print(json.dumps({
            "status": index["status"], "units": index["unit_count"],
            "admitted": index["admitted_count"],
            "out": index.get("_written_to"),
            "receipts": len(index.get("receipts") or []),
        }, ensure_ascii=False))
        return 0 if index["status"] == "ALL_ADMITTED" else 2
    payload = route_status(args.episode)
    print(json.dumps(payload, ensure_ascii=False))
    # compact last line for nalu_pipeline.qa_json (stdout capture is truncated at 4 KB and the
    # full payload lists every receipt path; 2026-09-13 S7 read status=None because of it)
    print(json.dumps({key: payload.get(key) for key in (
        "status", "q2_status", "admitted_count", "assembly_allowed_unit_ids", "stale_receipts",
        "blockers", "prepare_status")}, ensure_ascii=False))
    return 0 if payload["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
