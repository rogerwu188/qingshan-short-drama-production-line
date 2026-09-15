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
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ENGINE, FFMPEG, FFPROBE, GATE_REGISTRY, REVIEWER_ID, REVIEWER_TYPE,
    REVIEW_METHOD, VENV, Expectations, QaPaths, engine_module, gate_parameters,
    now, portable, read_json, sha256_file, write_json,
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
                  "wardrobe_matches_bible", "no_extra_scene_or_replayed_beat"),
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
DEFAULT_FRAMES = 5
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
    completed = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
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
        argv = [FFMPEG, "-y", "-ss", f"{stamp:.3f}", "-i", str(media),
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
    registry_path = Path(f"{_np.RUNTIME_ROOT}/runtime/nalu_character_asset_registry.json")
    characters = (read_json(registry_path, {}) or {}).get("characters") or {}

    result: dict[str, Any] = {
        "method": "INSIGHTFACE_COSINE_V1",
        "unit_id": unit_id,
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
        paths = [value for value in (characters[char_id].get("canonical_reference_paths") or [])
                 if Path(value).is_file()]
        canonical_paths[char_id] = paths
        if len(paths) < canonical_min:
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

    sources = []
    for char_id in sorted(canonical):
        rows = crops.get(char_id) or []
        paths = [str(path) for _frame, path, _score in rows]
        result["sample_counts"][char_id] = len(paths)
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
    for char_id, rows in sorted(crops.items()):
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
    def _is_noise(entry: dict[str, Any]) -> bool:
        text = str(entry.get("text") or "").strip()
        if not text or (entry.get("forbidden_tokens") or []):
            return False
        # <=2 ASCII letters, or any single character (CJK/digit): texture false positives on
        # fur / stone / fabric (same policy as keyframe_q1_builder, verified text-free by eye)
        return (len(text) <= 2 and text.isascii() and text.isalpha()) or len(text) == 1
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
                     (item.get("observed") or {}).get("observed_text_strings") or []]
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
    reviewer_exempt = (item.get("observed") or {}).get("identity_pose_exemptions") or {}
    if isinstance(reviewer_exempt, dict):
        for cid, reason in reviewer_exempt.items():
            if cid in declared_ids and str(reason or "").strip():
                exempt[cid] = f"REVIEWER:{reason}"
    measurable_ids = [cid for cid in declared_ids if cid not in exempt]
    if declared_ids and not measurable_ids:
        failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
        observed = (item.get("observed") or {}).get("observed_visible_characters") or []
        verification = {
            "method": "REVIEWER_STRUCTURED_IDENTITY_POSE_EXEMPT_D16",
            "measurement_scope": "VIDEO_UNIT_ALL_DECLARED_NOT_MEASURABLE_BY_POSE_D16",
            "decision": "PASS" if not failures else "FAIL",
            "canonical_characters": sorted(declared_ids),
            "not_measurable_by_pose": exempt,
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
        "not_measurable_by_pose": exempt,
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
        if technical.get("status") != "TECHNICAL_PASS_CONTENT_UNREVIEWED":
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
            # VIDEO_ASSEMBLY: the gate demands EXACTLY this string (:639-642).
            # It is copied from the D-6 runner's record, not declared here.
            "technical_qa": {
                "status": technical.get("status"),
                "reviewed_asset_sha256": technical.get("reviewed_asset_sha256"),
                "measured_by": technical.get("measured_by"),
                "allowed_scope": technical.get("allowed_scope"),
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

    args = parser.parse_args()
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
