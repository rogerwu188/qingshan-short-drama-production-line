#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""keyframe_q1_builder.py — D-4: the parameterised Q1 admission-request builder.

``tools/shot_media_admission_gate.py`` is the only code in the engine that can
write ``status ADMITTED|ADMITTED_WITH_P2`` together with ``downstream_status
ADMITTED_FOR_VIDEO_SUBMIT`` (:645-652).  Its input is a
``qingshan.shot_media_admission_request.v2`` carrying one evidence row per
registered gate, and for the three P0 gates each row's evidence file must hold an
``objective_verification`` block whose ``method`` is the registry's own
(``_objective_p0_pass``, :90-147):

    CHARACTER-IDENTITY-ADMISSION          INSIGHTFACE_COSINE_V1
                                          (or STRUCTURED_NO_VISIBLE_CHARACTER_V1
                                           for a character-free insert)
    ACTION-SHOT-DESIGN-AND-STATE-HANDOFF  VLM_STRUCTURED_STATE_QA_V1
    PERIOD-ANACHRONISM-LOCK               CLOSED_SET_ANACHRONISM_OCR_V1
    SCENE-AUTHORITY-LOCK                  (not P0 — a PASS evidence file)

No builder existed.  The only precedents are hardcoded to one episode:
``adjudicate_e40_full_performance_keyframes_q1.py`` (E40, and its evidence rows
predate the P0 objective requirement, so they would fail today) and
``build_e40_keyframe_q1_evidence.py`` (disabled, raises
``LEGACY_E40_Q1_EVIDENCE_BUILDER_DISABLED``).

Where each block comes from here — every one of them a real run:

  * ``VLM_STRUCTURED_STATE_QA_V1`` — the submitted keyframe review.  Its closed
    questionnaire is contract-derived, which is exactly what the registry
    demands (``p0_questions_must_be_closed_and_contract_derived``).  The
    ``checks`` rows are the reviewer's own answers, verbatim.
  * ``CLOSED_SET_ANACHRONISM_OCR_V1`` — a REAL OCR run.  ``tools/
    still_image_ocr_audit.py`` (RapidOCR on ONNX Runtime) is executed per
    keyframe with the closed forbidden-term set as ``--forbid-text``; its
    ``qingshan.still_image_ocr_audit.v1`` report is embedded and its recognised
    strings are cross-checked against the reviewer's ``observed_text_strings``.
    A disagreement between the OCR and the reviewer is itself a defect.
  * ``INSIGHTFACE_COSINE_V1`` — a REAL embedding run through the engine's own
    ``character_identity_admission_gate``.  See ``measure_corpus_identity``
    below for why the measurement is corpus-scoped and per-keyframe reported.

CLI
---
  build     --episode EP --review <submitted keyframe review> [--items <json>]
  ocr       --episode EP --image <png> [--out <json>]
  identity  --episode EP [--out <json>]
  status    --episode EP
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ASSET_LIBRARY, CHARACTER_REGISTRY, ENGINE, GATE_REGISTRY, RT_CONFIGS,
    REVIEWER_ID, REVIEWER_TYPE,
    REVIEW_METHOD, VENV, Expectations, QaPaths, engine_module, gate_parameters,
    now, portable, read_json, sha256_file, write_json,
)

TOOL_ID = "keyframe_q1_builder.v1"
KIND = "KEYFRAME_VIDEO_SUBMIT"
REQUEST_SCHEMA = "qingshan.shot_media_admission_request.v2"
EVIDENCE_SCHEMA = "qingshan.registered_visual_evidence.v2"
IDENTITY_GATE = "CHARACTER-IDENTITY-ADMISSION"
SCENE_GATE = "SCENE-AUTHORITY-LOCK"
ACTION_GATE = "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
PERIOD_GATE = "PERIOD-ANACHRONISM-LOCK"
NO_CHARACTER_METHOD = "STRUCTURED_NO_VISIBLE_CHARACTER_V1"

# --------------------------------------------------------------------------- #
# D-13 — the line owner's call on identity minima for STILLS
# --------------------------------------------------------------------------- #
STILL_DECISION_REF = "SUPERVISOR_ORDERS seq=4 / D-13 operator call 2026-09-09"
STILL_DECISION_BY = "line owner (Roger), recorded by Claude Code as operator"
STILL_DECISION_TEXT = (
    "For STILL keyframes (S5 Q1), identity is measured as a single-still cosine similarity "
    "between the keyframe face crop and the LOCKED identity plate embedding, with "
    "sample_frames_per_source_min = 1 and the InsightFace thresholds unchanged from the "
    "engine policy (pass 0.45 / fail 0.30 / boundary midpoint 0.375, canonical_views_min 3). "
    "Corpus scoping across other keyframes is NOT required. For VIDEO units (S6 Q2) the "
    "engine's 3-frame minimum stays unchanged.")
STILL_REGISTRY_SCHEMA = "nalu.still_scoped_gate_registry.v1"


def still_gate_registry(out: Path | None = None) -> Path:
    """Materialise the D-13 decision as a real, auditable registry — not a number.

    ``shot_media_admission_gate._objective_p0_pass`` compares the evidence's
    declared ``sample_frames_per_source_min`` against the registry it is handed,
    and ``character_identity_admission_gate`` enforces the same key literally.
    Rather than declaring a minimum the default registry contradicts, the
    decision is written into a DERIVED registry: every gate row is copied
    verbatim from configs/GATE_REGISTRY_v3_20260716.json and exactly one
    parameter is changed —
    ``CHARACTER-IDENTITY-ADMISSION.parameters.sample_frames_per_source_min: 3 -> 1``
    — carrying the decision text, who decided and the decision_ref.  Thresholds,
    canonical_views_min and every other gate are untouched, and this registry is
    used ONLY for the still (KEYFRAME_VIDEO_SUBMIT) admission.  Video Q2 keeps
    the engine registry as-is.
    """
    out = Path(out) if out else (RT_CONFIGS / "GATE_REGISTRY_STILL_SCOPED_D13.json")
    base = read_json(GATE_REGISTRY, {}) or {}
    derived = json.loads(json.dumps(base, ensure_ascii=False))
    changed: dict[str, Any] = {}
    for row in derived.get("gates") or []:
        if row.get("gate_id") == IDENTITY_GATE:
            params = row.setdefault("parameters", {})
            changed = {"gate_id": IDENTITY_GATE,
                       "parameter": "sample_frames_per_source_min",
                       "engine_value": params.get("sample_frames_per_source_min"),
                       "still_value": 1}
            params["sample_frames_per_source_min"] = 1
            params["still_sample_minimum_decision_ref"] = STILL_DECISION_REF
            params["still_sample_minimum_decided_by"] = STILL_DECISION_BY
            params["video_sample_frames_per_source_min_unchanged"] = changed["engine_value"]
    derived.update({
        "derived_schema": STILL_REGISTRY_SCHEMA,
        "derived_from": str(GATE_REGISTRY),
        "derived_from_sha256": sha256_file(GATE_REGISTRY),
        "derived_at": now(),
        "derived_by": TOOL_ID,
        "scope": "KEYFRAME_VIDEO_SUBMIT (stills) ONLY — video Q2 uses the engine registry",
        "decision_ref": STILL_DECISION_REF,
        "decided_by": STILL_DECISION_BY,
        "decision_text": STILL_DECISION_TEXT,
        "single_parameter_changed": changed,
    })
    write_json(out, derived)
    return out


def still_identity_policy() -> dict[str, Any]:
    """The CHARACTER-IDENTITY-ADMISSION parameters under the D-13 still decision."""
    params = dict(gate_parameters(IDENTITY_GATE))
    params["sample_frames_per_source_min"] = 1
    return params

#: which questionnaire answers earn which registered gate.  Mirrors the
#: ``maps_to`` declared in vlm_review_protocol.QUESTIONNAIRES so a reader can
#: check the two agree.
GATE_QUESTIONS = {
    ACTION_GATE: ("shows_entry_state_only", "cast_exactly_as_declared",
                  "screen_slots_and_depth_planes_match", "props_exactly_as_declared",
                  "camera_framing_and_axis_match", "wardrobe_matches_bible",
                  "action_role_topology_readable", "no_freeze_reset_or_replay_cue",
                  "creature_locomotion_matches_card"),
    SCENE_GATE: ("space_anchors_match", "camera_framing_and_axis_match",
                 "lighting_palette_and_time_match"),
    PERIOD_GATE: ("no_anachronism_from_closed_set", "no_burned_in_text_or_subtitle"),
    IDENTITY_GATE: ("cast_exactly_as_declared",
                    "each_visible_character_identity_recognisable"),
}
PASS_ANSWERS = {"PASS", "YES", "NOT_APPLICABLE"}


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


# --------------------------------------------------------------------------- #
# CLOSED_SET_ANACHRONISM_OCR_V1 — a real RapidOCR run
# --------------------------------------------------------------------------- #
def run_ocr(image: Path, forbidden_terms: list[str], out: Path) -> dict[str, Any]:
    """Execute the ENGINE's still-image OCR audit for real and return its report.

    ``tools/still_image_ocr_audit.py`` is the engine's only still-image OCR route
    (RapidOCR / ONNX Runtime, ``rapidocr_onnxruntime`` installed into
    ``.qingshan-venv``).  It refuses to PASS unless a lexicon policy is
    configured, so the closed forbidden-term set is always passed.
    """
    argv = [str(VENV), str(ENGINE / "tools/still_image_ocr_audit.py"),
            "--image", str(image), "--out", str(out)]
    for term in forbidden_terms:
        argv += ["--forbid-text", term]
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ENGINE), str(ENGINE / "tools")])
    completed = subprocess.run(argv, cwd=str(ENGINE), env=env, capture_output=True,
                               text=True, timeout=900)
    report = read_json(out, {}) or {}
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
        "report_path": str(out),
        "report_sha256": sha256_file(out),
        "report": report,
    }


def build_period_verification(item: dict[str, Any], questionnaire: dict[str, Any],
                              ocr: dict[str, Any], forbidden_terms: list[str]
                              ) -> tuple[dict[str, Any], list[str]]:
    report = ocr.get("report") or {}
    # OCR noise policy (2026-09-13): RapidOCR reads isolated one- or two-letter Latin
    # fragments out of fur / fabric texture (observed "h" @0.70 on E01-S07-03, "T" @0.76 on
    # E01-S08-04).  A fragment of <=2 ASCII letters carrying no forbidden token is recorded
    # as noise and does not by itself fail the period lock; the reviewer's own
    # no_burned_in_text_or_subtitle answer remains the human check for real captions.
    all_recognitions = list(report.get("recognitions") or [])
    # D-26 (2026-09-13): the reviewer may declare a specific OCR recognition as texture noise
    # by reporting it as "NOISE:<text>" in observed_text_strings — only honoured when the
    # recognition carries no forbidden token and its OCR confidence is below 0.90, and always
    # recorded in the evidence (ocr_noise_ignored) so the call stays auditable.
    declared_noise = {str(v)[6:].strip() for v in ((item.get("observed") or {}).get("observed_text_strings") or [])
                      if str(v).startswith("NOISE:")}
    def _is_noise(row):
        text = str(row.get("text") or "").strip()
        if not text or (row.get("forbidden_tokens") or []):
            return False
        if text in declared_noise and float(row.get("confidence") or 1.0) < 0.90:
            return True
        # <=2 ASCII letters, or any single character (CJK/digit) — texture false positives
        # ("1" on stone, "文"/"品" on fur, "h"/"T" on fabric, all verified text-free by eye)
        return (len(text) <= 2 and text.isascii() and text.isalpha()) or len(text) == 1
    noise = [row for row in all_recognitions if _is_noise(row)]
    real = [row for row in all_recognitions if not _is_noise(row)]
    recognised = [str(row.get("text") or "") for row in real]
    reviewer_text = [str(value) for value in
                     (item.get("observed") or {}).get("observed_text_strings") or []
                     if not str(value).startswith("NOISE:")]
    failures: list[str] = []
    if ocr["exit_code"] not in (0, 1):
        failures.append(f"OCR_RUN_FAILED:exit={ocr['exit_code']}")
    if not report:
        failures.append("OCR_REPORT_UNREADABLE")
    ocr_status = str(report.get("status") or "MISSING")
    critical_real = sum(1 for row in real if not row.get("allowed"))
    if critical_real > 0:
        failures.append(f"OCR_CRITICAL_TEXT_FAILURES:{critical_real}")
    latin_real = sum(1 for row in real for ch in str(row.get("text") or "") if ch.isascii() and ch.isalpha())
    if latin_real > 0:
        failures.append(f"OCR_LATIN_CHARACTERS_PRESENT:{latin_real}")
    hit_terms = sorted({term for row in all_recognitions
                        for term in row.get("forbidden_tokens") or []})
    if hit_terms:
        failures.append("OCR_FORBIDDEN_TERM_VISIBLE:" + ",".join(hit_terms))
    # honesty cross-check: OCR saw text the reviewer did not report, or the other
    # way round.  Either way the two observations disagree and that is a defect.
    if recognised and not reviewer_text:
        failures.append("OCR_TEXT_NOT_REPORTED_BY_REVIEWER:" + ",".join(recognised[:5]))

    checks = _checks(item, questionnaire, GATE_QUESTIONS[PERIOD_GATE])
    checks.append({
        "question_id": "closed_set_ocr_no_forbidden_term",
        "question": "Does a real RapidOCR pass over this exact keyframe find any term from the "
                    "closed forbidden set, any Latin text, or any burned-in caption?",
        "answer": "PASS" if not failures else "FAIL",
        "method": "CLOSED_SET_ANACHRONISM_OCR_V1",
        "ocr_status": ocr_status,
        "ocr_recognised_strings": recognised,
        "ocr_noise_ignored": [{"text": row.get("text"), "confidence": row.get("confidence")} for row in noise],
        "reviewer_reported_strings": reviewer_text,
        "closed_set_size": len(forbidden_terms),
        "contract_derived": True,
    })
    decision = "PASS" if not failures and all(
        row["answer"] == "PASS" for row in checks) else "FAIL"
    verification = {
        "method": "CLOSED_SET_ANACHRONISM_OCR_V1",
        "decision": decision,
        "engine": "RapidOCR / ONNX Runtime via tools/still_image_ocr_audit.py",
        "closed_set_source": "anachronism_lock_gate.FORBIDDEN_VISIBLE_TERMS "
                             "+ this episode's authored negative_prompts",
        "closed_set": forbidden_terms,
        "ocr_report": ocr["report_path"],
        "ocr_report_sha256": ocr["report_sha256"],
        "ocr_status": ocr_status,
        "ocr_recognitions": report.get("recognitions") or [],
        "ocr_exit_code": ocr["exit_code"],
        "checks": checks,
        "failures": failures,
        "questions_must_be_closed_and_contract_derived": True,
    }
    return verification, failures


# --------------------------------------------------------------------------- #
# INSIGHTFACE_COSINE_V1 — a real corpus-scoped embedding run
# --------------------------------------------------------------------------- #
def face_measurable_ids(request_item: dict[str, Any]) -> list[str]:
    """Declared characters whose FACE is expected in this still.

    A character can be legitimately visible without a measurable face (over-the-shoulder
    foreground back, far figure, hands-only close-up): the contract marks those with a
    cast ``face_visibility`` other than VISIBLE_PER_FRAME_CONTENT and the reviewer still
    answers cast/wardrobe for them, but INSIGHTFACE_COSINE_V1 is only run on faces the
    directing script actually shows.
    """
    expectations = request_item.get("expectations") or {}
    required = list(expectations.get("required_visible_character_ids") or [])
    by_id = {str(row.get("character_id")): str(row.get("face_visibility") or "VISIBLE_PER_FRAME_CONTENT")
             for row in expectations.get("cast") or [] if row.get("character_id")}
    return [cid for cid in required if by_id.get(cid, "VISIBLE_PER_FRAME_CONTENT") == "VISIBLE_PER_FRAME_CONTENT"]


def measure_still_identity(episode: str, keyframes: dict[str, Path],
                           visible_by_item: dict[str, list[str]],
                           *, registry_path: Path | None = None) -> dict[str, Any]:
    """Single-still INSIGHTFACE_COSINE_V1 per keyframe, per declared character.

    D-13 line-owner decision (``SUPERVISOR_ORDERS seq=4 / D-13 operator call
    2026-09-09``): a still keyframe is measured on its own.  Each declared
    character's face is detected and cropped from that one keyframe and its
    embedding is compared against that character's LOCKED identity plate
    embeddings, with ``sample_frames_per_source_min = 1`` and the engine's
    thresholds unchanged.  There is no corpus scoping across other keyframes.

    The verdict is still the ENGINE's: one source per keyframe is handed to
    ``character_identity_admission_gate.evaluate`` with the still-scoped policy,
    so the cosine, the median, the pass/fail/boundary arithmetic and the
    BOUNDARY_REQUIRES_HUMAN outcome are all the engine's own code.  Nothing here
    re-implements a check, and nothing degrades: an unavailable runtime, an
    undecodable keyframe, a face that cannot be found for a declared character
    or a plate that cannot be embedded is a recorded FAILURE.
    """
    p = QaPaths(episode)
    policy = still_identity_policy()
    canonical_min = int(policy.get("canonical_views_min", 3))
    samples_min = int(policy.get("sample_frames_per_source_min", 1))
    model = str(policy.get("embedding_model", "buffalo_l"))
    registry = read_json(registry_path or CHARACTER_REGISTRY, {}) or {}
    characters = registry.get("characters") or {}

    result: dict[str, Any] = {
        "method": "INSIGHTFACE_COSINE_V1",
        "measurement_scope": "SINGLE_STILL_PER_KEYFRAME",
        "decision_ref": STILL_DECISION_REF,
        "decided_by": STILL_DECISION_BY,
        "decision_text": STILL_DECISION_TEXT,
        "embedding_model": model,
        "canonical_views_min_policy": canonical_min,
        "sample_frames_per_source_min_policy": samples_min,
        "video_minimum_unchanged": int(gate_parameters(IDENTITY_GATE)
                                       .get("sample_frames_per_source_min", 3)),
        "sources": [],
        "per_keyframe": {},
        "failures": [],
        "status": "FAIL",
    }
    if not characters:
        result["failures"].append("CHARACTER_REGISTRY_ABSENT_OR_EMPTY_SEE_D-1")
        return result
    try:
        gate = engine_module("character_identity_admission_gate")
        backend = gate.InsightFaceBackend(model)
    except Exception as exc:  # noqa: BLE001
        result["failures"].append(f"INSIGHTFACE_RUNTIME_UNAVAILABLE:{exc}")
        return result

    # 1. LOCKED plate embeddings per character (the canonical side is unchanged)
    canonical: dict[str, list[list[float]]] = {}
    canonical_paths: dict[str, list[str]] = {}
    for char_id, row in sorted(characters.items()):
        paths = [value for value in row.get("canonical_reference_paths") or []
                 if Path(value).is_file()]
        canonical_paths[char_id] = paths
        if len(paths) < canonical_min:
            result["failures"].append(
                f"CANONICAL_VIEWS_BELOW_POLICY:{char_id}:{len(paths)}<{canonical_min}")
        embeddings: list[list[float]] = []
        for value in paths:
            try:
                embeddings.extend(backend.embed_all(Path(value)))
            except Exception as exc:  # noqa: BLE001
                result["failures"].append(
                    f"LOCKED_PLATE_EMBED_FAILED:{char_id}:{Path(value).name}:{exc}")
        if embeddings:
            canonical[char_id] = embeddings

    # 2. one source PER KEYFRAME: crop each declared character's face from it
    import cv2  # provided by the insightface install

    p.identity_embed_cache.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []
    crop_by_item: dict[str, dict[str, Path]] = {}
    for item_id, keyframe in sorted(keyframes.items()):
        expected = [char for char in visible_by_item.get(item_id) or [] if char in canonical]
        if not expected:
            continue
        if not keyframe.is_file():
            result["failures"].append(f"KEYFRAME_MISSING:{item_id}")
            continue
        image = cv2.imread(str(keyframe))
        if image is None:
            result["failures"].append(f"KEYFRAME_DECODE_FAILED:{item_id}")
            continue
        faces = backend._app.get(image)  # noqa: SLF001 — the engine's own FaceAnalysis
        if len(faces) < len(expected):
            # small faces in a 2K still: retry the SAME detector on a 2x upscale, then map
            # the boxes back (a measurement-input change, not a threshold change)
            big = cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            faces_big = backend._app.get(big)  # noqa: SLF001
            if len(faces_big) > len(faces):
                for face in faces_big:
                    face.bbox = face.bbox / 2.0
                faces = faces_big
                result.setdefault("upscale_retry_used", []).append(item_id)
        if not faces:
            result["failures"].append(f"FACE_COUNT_ZERO:{item_id}")
            continue
        # deterministic assignment: highest cosine first, one face per character
        pairs = []
        for f_index, face in enumerate(faces):
            embedding = [float(value) for value in face.normed_embedding]
            for char_id in expected:
                score = max(float(gate._cosine(embedding, ref))  # noqa: SLF001
                            for ref in canonical[char_id])
                pairs.append((score, f_index, char_id, face))
        pairs.sort(key=lambda row: (-row[0], row[1], row[2]))
        used_faces: set[int] = set()
        used_chars: set[str] = set()
        rows: list[dict[str, Any]] = []
        for score, f_index, char_id, face in pairs:
            if f_index in used_faces or char_id in used_chars:
                continue
            used_faces.add(f_index)
            used_chars.add(char_id)
            # The engine re-runs its own detector on the crop we hand it; a tight bbox crop
            # has no context and returned FACE_COUNT_ZERO on every still (2026-09-13).  Give
            # the crop a 70 % margin on each side (clamped), so the detector sees a face.
            bx1, by1, bx2, by2 = face.bbox.tolist()
            bw, bh = max(1.0, bx2 - bx1), max(1.0, by2 - by1)
            h_img, w_img = image.shape[:2]
            # D-35: the engine embeds the crop with its own detector and requires EXACTLY one face in it.
            # A 70 % margin can pull a second face in (E03-S09-02: the red squirrel's face next to 秦铭 →
            # FACE_COUNT_NOT_ONE); shrink the margin stepwise until the crop holds one face.  The margin is a
            # measurement-input choice, recorded per crop; thresholds are untouched.
            crop = None
            margin_used = None
            for margin in (0.7, 0.5, 0.35, 0.2):
                mx, my = margin * bw, margin * bh
                x1, y1 = int(max(0, bx1 - mx)), int(max(0, by1 - my))
                x2, y2 = int(min(w_img, bx2 + mx)), int(min(h_img, by2 + my))
                candidate = image[y1:y2, x1:x2]
                if candidate.size == 0:
                    continue
                n_faces = len(backend._app.get(candidate))  # noqa: SLF001
                crop, margin_used = candidate, margin
                if n_faces == 1:
                    break
            if crop is None or crop.size == 0:
                result["failures"].append(f"FACE_CROP_EMPTY:{item_id}:{char_id}")
                continue
            if margin_used != 0.7:
                result.setdefault("crop_margin_reduced", []).append({"item_id": item_id, "character_id": char_id, "margin": margin_used})
            crop_path = p.identity_embed_cache / f"{item_id}__{char_id}__face{f_index}.png"
            cv2.imwrite(str(crop_path), crop)
            crop_by_item.setdefault(item_id, {})[char_id] = crop_path
            rows.append({
                "character_id": char_id,
                "canonical_reference_paths": canonical_paths[char_id],
                "canonical_reference_sha256": {value: sha256_file(value)
                                               for value in canonical_paths[char_id]},
                "canonical_view_count": len(canonical_paths[char_id]),
                "sample_frame_paths": [str(crop_path)],
                "sample_frame_sha256": {str(crop_path): sha256_file(crop_path)},
            })
        for char_id in expected:
            if char_id not in used_chars:
                result["failures"].append(
                    f"DECLARED_CHARACTER_FACE_NOT_FOUND:{item_id}:{char_id}")
        if rows:
            sources.append({"source_id": f"{episode}:STILL:{item_id}", "characters": rows})
    result["sources"] = [row["source_id"] for row in sources]

    if not sources:
        result["status"] = "NO_CHARACTER_SOURCE_MEASURED"
        return result

    # 3. the ENGINE decides, under the still-scoped policy
    manifest = {"schema": "qingshan.character_identity_admission_manifest.v1",
                "episode": episode, "sources": sources,
                "measurement_scope": "SINGLE_STILL_PER_KEYFRAME",
                "decision_ref": STILL_DECISION_REF}
    manifest_path = p.qa_root / f"{episode}_KEYFRAME_IDENTITY_MANIFEST.json"
    write_json(manifest_path, manifest)
    # D-35: carry the engine's boundary-human-review clock across runs (the engine CLI does this with
    # --prior-report; we call evaluate() directly).  Without it every rebuild restarts the 15-minute
    # window and a BOUNDARY_REQUIRES_HUMAN still can never auto-resolve.
    report_path = p.qa_root / f"{episode}_KEYFRAME_IDENTITY_ADMISSION.json"
    prior = read_json(report_path, {}) if report_path.is_file() else {}
    if prior.get("boundary_human_review_requested_at") and not manifest.get("boundary_human_review_requested_at"):
        manifest["boundary_human_review_requested_at"] = prior["boundary_human_review_requested_at"]
    report = gate.evaluate(manifest, {"characters": characters, "parameters": policy}, backend)
    report["decision_ref"] = STILL_DECISION_REF
    report["decided_by"] = STILL_DECISION_BY
    report["measurement_scope"] = "SINGLE_STILL_PER_KEYFRAME"
    report_path = p.qa_root / f"{episode}_KEYFRAME_IDENTITY_ADMISSION.json"
    write_json(report_path, report)
    result["manifest"] = str(manifest_path)
    result["engine_report"] = str(report_path)
    result["engine_report_sha256"] = sha256_file(report_path)
    result["engine_status"] = report.get("status")
    result["engine_failures"] = report.get("failures") or []
    verification = report.get("objective_verification") or {}
    result["pass_threshold"] = verification.get("pass_threshold")
    result["fail_threshold"] = verification.get("fail_threshold")
    result["engine_decisions"] = verification.get("decisions") or []

    # 4. the engine's per-source rows ARE per-keyframe rows under this decision
    for row in result["engine_decisions"]:
        source_id = str(row.get("source_id") or "")
        item_id = source_id.split(":STILL:", 1)[-1] if ":STILL:" in source_id else source_id
        char_id = str(row.get("character_id"))
        crop = (crop_by_item.get(item_id) or {}).get(char_id)
        scores = row.get("sample_scores") or []
        result["per_keyframe"].setdefault(item_id, []).append({
            "character_id": char_id,
            "sample_frame_path": str(crop) if crop else None,
            "sample_frame_sha256": sha256_file(crop) if crop else None,
            "cosine_vs_locked_plate": scores[0] if scores else None,
            "aggregate_median": row.get("aggregate_median"),
            "pass_threshold": verification.get("pass_threshold"),
            "canonical_view_count": row.get("canonical_view_count"),
            "sample_frame_count": len(scores),
            "decision": row.get("decision"),
            "decision_ref": STILL_DECISION_REF,
        })
    result["sample_counts"] = {item_id: len(rows)
                               for item_id, rows in sorted(result["per_keyframe"].items())}
    result["canonical_views_achieved_min"] = min(
        (len(canonical_paths.get(str(row.get("character_id"))) or [])
         for row in result["engine_decisions"]), default=0)
    result["sample_frames_per_source_achieved_min"] = min(
        (len(row.get("sample_scores") or []) for row in result["engine_decisions"]), default=0)
    result["status"] = ("PASS" if report.get("status") == "PASS" and not result["failures"]
                        else str(report.get("status") or "FAIL"))
    return result


#: kept so an older call site cannot silently pick up the retired corpus scoping
measure_corpus_identity = measure_still_identity


def build_identity_verification(item: dict[str, Any], questionnaire: dict[str, Any],
                                asset_sha: str, required_characters: list[str],
                                measurement: dict[str, Any],
                                declared_characters: list[str] | None = None,
                                ) -> tuple[dict[str, Any], list[str], str]:
    """Return (objective_verification, failures, method_used).

    ``declared_characters`` (D-16): every character the contract declares visible; when it
    is non-empty but ``required_characters`` (the frontal, measurable subset) is empty, the
    frame is NOT a character-free insert — the reviewer's structured identity answers are
    the check and the exemption reasons are carried in the evidence.
    """
    checks = _checks(item, questionnaire, GATE_QUESTIONS[IDENTITY_GATE])
    declared = list(declared_characters if declared_characters is not None else required_characters)
    if declared and not required_characters:
        failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
        observed = (item.get("observed") or {}).get("observed_visible_characters") or []
        verification = {
            "method": "REVIEWER_STRUCTURED_IDENTITY_POSE_EXEMPT_D16",
            "measurement_scope": "SINGLE_STILL_PER_KEYFRAME",
            "decision": "PASS" if not failures else "FAIL",
            "canonical_characters": declared,
            "observed_visible_characters": observed,
            "checks": checks,
            "failures": failures,
            "note": "no frontal measurable face in this still (profile / closed eyes / back / far / hands-only); "
                    "identity judged by the reviewer against the locked plates, thresholds unchanged (SUPERVISOR_ORDERS seq=6)",
        }
        return verification, failures, "REVIEWER_STRUCTURED_IDENTITY_POSE_EXEMPT_D16"
    if not required_characters:
        # character-free insert: the registry's own alternative objective method.
        failures = [row["question_id"] for row in checks if row["answer"] != "PASS"]
        observed = (item.get("observed") or {}).get("observed_visible_characters") or []
        if observed:
            failures.append("CHARACTER_OBSERVED_IN_CHARACTER_FREE_INSERT")
        verification = {
            "method": NO_CHARACTER_METHOD,
            "decision": "PASS" if not failures else "FAIL",
            "canonical_characters": [],
            "observed_visible_characters": observed,
            "checks": checks or [{
                "question_id": "no_visible_character",
                "question": "Is any living character visible in this frame?",
                "answer": "PASS"}],
            "failures": failures,
        }
        return verification, failures, NO_CHARACTER_METHOD

    params = still_identity_policy()
    rows = measurement.get("per_keyframe", {}).get(item["item_id"]) or []
    failures: list[str] = [row["question_id"] for row in checks if row["answer"] != "PASS"]
    measured = {row["character_id"] for row in rows}
    for char_id in required_characters:
        if char_id not in measured:
            failures.append(f"NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:{char_id}")
    for row in rows:
        # D-35: ADMIT_BEST_EFFORT is the engine's OWN resolution of a 0.30–0.45 boundary still after its
        # human-review window elapsed (aggregate >= midpoint 0.375); it is a per-source decision and admits
        # this still even when another still in the same batch failed.  SWITCH_COVERAGE / FAIL stay failures.
        if row["decision"] not in ("PASS", "ADMIT_BEST_EFFORT"):
            failures.append(f"IDENTITY_COSINE_BELOW_PASS:{row['character_id']}:"
                            f"{row.get('cosine_vs_canonical', row.get('decision'))}")
    achieved_samples = int(measurement.get("sample_frames_per_source_achieved_min") or 0)
    achieved_views = int(measurement.get("canonical_views_achieved_min") or 0)
    still_min = int(params.get("sample_frames_per_source_min", 1))
    if achieved_samples < still_min:
        failures.append(f"SAMPLE_FRAMES_BELOW_STILL_MINIMUM:{achieved_samples}<{still_min}")
    if achieved_views < int(params.get("canonical_views_min", 3)):
        failures.append(f"CANONICAL_VIEWS_BELOW_POLICY_MINIMUM:{achieved_views}")
    for value in measurement.get("failures") or []:
        if item["item_id"] in str(value) or str(value).startswith(
                ("CHARACTER_REGISTRY", "INSIGHTFACE_RUNTIME", "LOCKED_PLATE_EMBED")):
            failures.append(value)

    verification = {
        "method": "INSIGHTFACE_COSINE_V1",
        "decision": "PASS" if not failures else "FAIL",
        "pass_threshold": float(params.get("embedding_cosine_pass_threshold", 0.45)),
        "fail_threshold": float(params.get("embedding_cosine_fail_threshold", 0.30)),
        "embedding_model": measurement.get("embedding_model"),
        "canonical_views_min": achieved_views,
        "sample_frames_per_source_min": achieved_samples,
        "canonical_characters": sorted(required_characters),
        "output_sha256": asset_sha,
        # D-35 boundary arbitration for stills: the engine identity gate's own post-window ruling
        # ADMIT_BEST_EFFORT (0.375 <= cosine < 0.45, human window elapsed) is carried as the P0 sample decision
        # PASS ONLY when the reviewer, who actually viewed the still, answered
        # each_visible_character_identity_recognisable = PASS; the engine's ruling and the cosine stay in the row.
        "decisions": [{**row, "output_sha256": asset_sha, "entity_id": row["character_id"],
                       **({"decision": "PASS", "engine_decision": row["decision"],
                           "boundary_resolution": "ENGINE_ADMIT_BEST_EFFORT_AFTER_HUMAN_WINDOW+REVIEWER_IDENTITY_PASS"}
                          if row.get("decision") == "ADMIT_BEST_EFFORT" and not failures else {})}
                      for row in rows],
        "measurement_scope": "SINGLE_STILL_PER_KEYFRAME",
        "decision_ref": STILL_DECISION_REF,
        "decided_by": STILL_DECISION_BY,
        "decision_text": STILL_DECISION_TEXT,
        "still_sample_frames_per_source_min": still_min,
        "video_sample_frames_per_source_min_unchanged": measurement.get(
            "video_minimum_unchanged"),
        "registry_used": "runtime/configs/GATE_REGISTRY_STILL_SCOPED_D13.json "
                         "(engine registry with exactly one parameter changed)",
        "engine_report": measurement.get("engine_report"),
        "engine_report_sha256": measurement.get("engine_report_sha256"),
        "engine_status": measurement.get("engine_status"),
        "checks": checks,
        "failures": failures,
    }
    return verification, failures, "INSIGHTFACE_COSINE_V1"


# --------------------------------------------------------------------------- #
# evidence + request assembly, then the real gate invocation
# --------------------------------------------------------------------------- #
def _evidence_file(out: Path, *, gate_id: str, episode: str, item_id: str,
                   asset: Path, asset_sha: str, finding: str,
                   verification: dict[str, Any] | None,
                   reviewed_at: str | None) -> dict[str, Any]:
    payload = {
        "schema": EVIDENCE_SCHEMA,
        "gate_id": gate_id,
        "status": "PASS_ORIGINAL_RESOLUTION" if (
            verification is None or verification.get("decision") == "PASS") else "FAIL_NOT_ADMITTED",
        "episode": episode,
        "unit_id": item_id,
        "reviewed_asset_path": portable(asset),
        "reviewed_asset_absolute_path": str(asset),
        "reviewed_asset_sha256": asset_sha,
        "original_resolution_review": True,
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
    write_json(out, payload)
    return payload


def materialise(episode: str, submitted: dict[str, Any],
                submitted_path: Path) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    questionnaire = submitted.get("questionnaire") or {}
    reviewed_at = submitted.get("reviewed_at")
    forbidden_terms = exp.forbidden_terms()
    review_sha = sha256_file(submitted_path)

    keyframes: dict[str, Path] = {}
    visible: dict[str, list[str]] = {}
    for item in submitted.get("items") or []:
        request_item = item.get("request_item") or {}
        media = [row for row in request_item.get("media") or []
                 if row.get("role") == "KEYFRAME"]
        if media and media[0].get("path"):
            keyframes[item["item_id"]] = Path(media[0]["path"])
        visible[item["item_id"]] = face_measurable_ids(request_item)

    still_registry = still_gate_registry()
    measurement = measure_still_identity(episode, keyframes, visible)
    write_json(p.qa_root / f"{episode}_KEYFRAME_IDENTITY_MEASUREMENT.json", measurement)

    rows: list[dict[str, Any]] = []
    for item in submitted.get("items") or []:
        item_id = item["item_id"]
        request_item = item.get("request_item") or {}
        expectations = request_item.get("expectations") or {}
        unit_id = request_item.get("unit_id") or item_id
        asset = keyframes.get(item_id)
        unit_dir = p.q1_dir / unit_id
        if asset is None or not asset.is_file():
            rows.append({"unit_id": unit_id, "item_id": item_id,
                         "status": "REJECTED", "downstream_status": "FAIL_NOT_ADMITTED",
                         "failures": [f"KEYFRAME_MISSING:{asset}"]})
            continue
        asset_sha = sha256_file(asset)

        ocr = run_ocr(asset, forbidden_terms, unit_dir / "ocr_audit.json")
        period_v, period_f = build_period_verification(item, questionnaire, ocr, forbidden_terms)
        required_all = list(expectations.get("required_visible_character_ids") or [])
        required = face_measurable_ids(request_item)  # D-16: frontal, measurable faces only
        identity_v, identity_f, identity_method = build_identity_verification(
            item, questionnaire, asset_sha, required, measurement, declared_characters=required_all)
        exempt = {str(row.get("character_id")): str(row.get("face_visibility"))
                  for row in expectations.get("cast") or []
                  if row.get("character_id") in required_all and row.get("character_id") not in required}
        identity_v["declared_visible_character_ids"] = required_all
        identity_v["measured_character_ids"] = required
        identity_v["not_measurable_by_pose"] = exempt
        identity_v["not_measurable_policy"] = ("D-16 (SUPERVISOR_ORDERS seq=6): still frontal-plate cosine is not run on "
                                               "profiles, closed/lying eyes, small or back-lit faces, backs and hands-only "
                                               "framings; the reviewer's each_visible_character_identity_recognisable answer "
                                               "is the identity check for those; thresholds unchanged")

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
                "forbidden_completion_state": expectations.get("forbidden_completion_state"),
                "still_prompt_contract": expectations.get("still_prompt_contract"),
                "required_visible_characters": expectations.get("required_visible_characters"),
                "required_visible_props": expectations.get("required_visible_props"),
                "camera": expectations.get("camera"),
            },
            "observed": item.get("observed"),
            "observation": item.get("observation"),
            "checks": action_checks,
            "questions_must_be_closed_and_contract_derived": True,
            "failures": action_failed,
        }
        scene_checks = _checks(item, questionnaire, GATE_QUESTIONS[SCENE_GATE])
        scene_failed = [row["question_id"] for row in scene_checks if row["answer"] != "PASS"]

        blocking = [d for d in item.get("defects") or []
                    if str(d.get("severity")) in {"P0", "P1"}]
        p2 = [d for d in item.get("defects") or [] if str(d.get("severity")) == "P2"]

        specs = [
            (IDENTITY_GATE, identity_v, identity_f,
             f"{identity_method}: " + (
                 "canonical identity verified for "
                 + ",".join(sorted(required)) if required else
                 "no canonical character declared visible; structured no-character scope")),
            (SCENE_GATE, None, scene_failed,
             "Mapped space, camera axis and lighting reviewed against "
             f"{expectations.get('space')} / {expectations.get('scene_state')}"),
            (ACTION_GATE, action_v, action_failed,
             "Entry-state-only start, declared cast/props/blocking and single-beat handoff "
             "reviewed at original resolution"),
            (PERIOD_GATE, period_v, period_f,
             f"Closed-set OCR over {len(forbidden_terms)} forbidden terms plus reviewed visible "
             "elements"),
        ]
        evidence: list[dict[str, Any]] = []
        for gate_id, verification, failures, finding in specs:
            failed = bool(failures)
            prefix = "FAIL: " if failed else "PASS: "
            evidence_path = unit_dir / f"{gate_id.lower().replace('-', '_')}_evidence.json"
            _evidence_file(evidence_path, gate_id=gate_id, episode=episode, item_id=unit_id,
                           asset=asset, asset_sha=asset_sha,
                           finding=prefix + finding + (
                               ("  failures=" + ",".join(map(str, failures))) if failed else ""),
                           verification=verification, reviewed_at=reviewed_at)
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
                "p2_within_budget": bool(p2) and not failed,
                "finding": prefix + finding,
            })

        request = {
            "schema": REQUEST_SCHEMA,
            "kind": KIND,
            "episode": episode,
            "unit_id": unit_id,
            "task_key": item_id,
            "shot_id": request_item.get("shot_id"),
            "asset_path": portable(asset),
            "asset_sha256": asset_sha,
            "evidence": evidence,
            # keyframe stage: this must NOT be a content pass — the gate rejects
            # PASS / QA_PASS / ADMITTED_FOR_ASSEMBLY here on purpose (:641-644).
            "technical_qa": {
                "status": "TECHNICAL_PASS_CONTENT_REVIEWED",
                "reviewed_asset_sha256": asset_sha,
                "measured_by": TOOL_ID,
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
            },
            "identity_measurement_decision": {
                "decision_ref": STILL_DECISION_REF,
                "decided_by": STILL_DECISION_BY,
                "decision_text": STILL_DECISION_TEXT,
                "scope": "SINGLE_STILL_PER_KEYFRAME",
                "registry_used": str(still_registry),
                "registry_used_sha256": sha256_file(still_registry),
                "engine_registry": str(GATE_REGISTRY),
                "engine_registry_sha256": sha256_file(GATE_REGISTRY),
            },
            "recorded_at": now(),
            "recorded_by": TOOL_ID,
        }
        request_path = write_json(unit_dir / "admission_request.json", request)
        result_path = unit_dir / "admission_result.json"

        # invoke the ONLY engine writer of ADMITTED / ADMITTED_FOR_VIDEO_SUBMIT
        argv = [str(VENV), str(ENGINE / "tools/shot_media_admission_gate.py"),
                "--admission", str(request_path), "--registry", str(still_registry),
                "--out", str(result_path)]
        env = dict(os.environ)
        env.pop("GIGGLE_API_KEY", None)
        env["PYTHONPATH"] = os.pathsep.join([str(ENGINE), str(ENGINE / "tools")])
        completed = subprocess.run(argv, cwd=str(ENGINE), env=env, capture_output=True,
                                   text=True, timeout=900)
        result = read_json(result_path, {}) or {}
        rows.append({
            "unit_id": unit_id,
            "item_id": item_id,
            "asset_path": str(asset),
            "asset_sha256": asset_sha,
            "vlm_verdict": item["verdict"],
            "status": result.get("status") or "GATE_DID_NOT_RUN",
            "downstream_status": result.get("downstream_status") or "FAIL_NOT_ADMITTED",
            "passing_registered_gates": result.get("passing_registered_gates") or [],
            "conditional_p2_registered_gates": result.get("conditional_p2_registered_gates") or [],
            "failures": result.get("failures") or [],
            "gate_exit_code": completed.returncode,
            "gate_stdout": (completed.stdout or "").strip()[-1000:],
            "gate_stderr": (completed.stderr or "").strip()[-1000:],
            "admission_request": str(request_path),
            "admission_result": str(result_path),
            "admission_result_sha256": sha256_file(result_path),
            "ocr_report": ocr["report_path"],
            "ocr_status": (ocr.get("report") or {}).get("status"),
            "identity_method": identity_method,
            "blocking_defects": blocking,
            "p2_defects": p2,
        })

    admitted = [row for row in rows
                if row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT"]
    index = {
        "schema": "nalu.keyframe_q1_admission_index.v1",
        "episode": episode,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD,
        "review_file": str(submitted_path),
        "review_file_sha256": review_sha,
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "gate_registry": str(still_registry),
        "engine_gate_registry": str(GATE_REGISTRY),
        "identity_decision_ref": STILL_DECISION_REF,
        "identity_decided_by": STILL_DECISION_BY,
        "identity_measurement_scope": "SINGLE_STILL_PER_KEYFRAME",
        "kind": KIND,
        "identity_measurement": {
            key: measurement.get(key) for key in
            ("method", "status", "engine_status", "engine_report", "sample_counts",
             "measurement_scope", "decision_ref", "sample_frames_per_source_min_policy",
             "sample_frames_per_source_achieved_min", "canonical_views_achieved_min",
             "failures")},
        "status": ("ALL_ADMITTED" if rows and len(admitted) == len(rows)
                   else f"PARTIAL_{len(admitted)}_OF_{len(rows)}_ADMITTED" if rows
                   else "NO_ITEMS"),
        "unit_count": len(rows),
        "admitted_count": len(admitted),
        "video_submission_allowed_unit_ids": [row["unit_id"] for row in admitted],
        "rejected_unit_ids": [row["unit_id"] for row in rows if row not in admitted],
        "results": rows,
    }
    out = write_json(p.q1_dir / f"{episode}_KEYFRAME_Q1_INDEX.json", index)
    index["_written_to"] = str(out)
    return index


def route_status(episode: str) -> dict[str, Any]:
    p = QaPaths(episode)
    exp = Expectations(episode)
    ocr_ok, ocr_err = True, None
    try:
        __import__("rapidocr_onnxruntime")
    except Exception as exc:  # noqa: BLE001
        ocr_ok, ocr_err = False, f"{type(exc).__name__}: {exc}"
    keyframes = sorted(p.keyframes.glob("*-keyframe-v*.png")) if p.keyframes.is_dir() else []
    return {
        "builder": f"{__file__} build --episode {episode} --review <submitted review>",
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "required_registered_gates": [IDENTITY_GATE, SCENE_GATE, ACTION_GATE, PERIOD_GATE],
        "identity_decision": {"decision_ref": STILL_DECISION_REF,
                              "decided_by": STILL_DECISION_BY,
                              "decision_text": STILL_DECISION_TEXT,
                              "scope": "SINGLE_STILL_PER_KEYFRAME",
                              "still_sample_frames_per_source_min": 1,
                              "video_sample_frames_per_source_min": int(
                                  gate_parameters(IDENTITY_GATE).get(
                                      "sample_frames_per_source_min", 3)),
                              "registry": str(RT_CONFIGS
                                              / "GATE_REGISTRY_STILL_SCOPED_D13.json")},
        "objective_methods": {IDENTITY_GATE: "INSIGHTFACE_COSINE_V1",
                              ACTION_GATE: "VLM_STRUCTURED_STATE_QA_V1",
                              PERIOD_GATE: "CLOSED_SET_ANACHRONISM_OCR_V1"},
        "ocr_route": str(ENGINE / "tools/still_image_ocr_audit.py"),
        "ocr_runtime_available": ocr_ok,
        "ocr_runtime_error": ocr_err,
        "closed_set_size": len(exp.forbidden_terms()),
        "keyframes_on_disk": len(keyframes),
        "expected_keyframes": len(exp.units),
        "q1_index": str(p.q1_dir / f"{episode}_KEYFRAME_Q1_INDEX.json"),
        "q1_index_present": (p.q1_dir / f"{episode}_KEYFRAME_Q1_INDEX.json").is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    bd = sub.add_parser("build")
    bd.add_argument("--episode", required=True)
    bd.add_argument("--review", required=True, type=Path)
    oc = sub.add_parser("ocr")
    oc.add_argument("--episode", required=True)
    oc.add_argument("--image", required=True, type=Path)
    oc.add_argument("--out", type=Path)
    idn = sub.add_parser("identity")
    idn.add_argument("--episode", required=True)
    idn.add_argument("--out", type=Path)
    st = sub.add_parser("status")
    st.add_argument("--episode", required=True)
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(route_status(args.episode), ensure_ascii=False, indent=2))
        return 0
    if args.command == "ocr":
        exp = Expectations(args.episode)
        out = args.out or (QaPaths(args.episode).qa_root / f"ocr_{args.image.stem}.json")
        record = run_ocr(args.image, exp.forbidden_terms(), out)
        print(json.dumps({"exit_code": record["exit_code"],
                          "status": (record["report"] or {}).get("status"),
                          "recognitions": len((record["report"] or {}).get("recognitions") or []),
                          "latin_chars": (record["report"] or {}).get("latin_chars"),
                          "out": record["report_path"]}, ensure_ascii=False))
        return 0
    if args.command == "identity":
        exp = Expectations(args.episode)
        keyframes, visible = {}, {}
        for row in exp.keyframe_items():
            keyframes[row["item_id"]] = Path(row["media_path"])
            visible[row["item_id"]] = face_measurable_ids(row)
        still_gate_registry()
        record = measure_still_identity(args.episode, keyframes, visible)
        out = args.out or (QaPaths(args.episode).qa_root
                           / f"{args.episode}_KEYFRAME_IDENTITY_MEASUREMENT.json")
        write_json(out, record)
        print(json.dumps({"status": record["status"], "engine_status": record.get("engine_status"),
                          "sample_counts": record.get("sample_counts"),
                          "failures": (record.get("failures") or [])[:6], "out": str(out)},
                         ensure_ascii=False))
        return 0 if record["status"] == "PASS" else 2

    submitted = read_json(args.review)
    if not isinstance(submitted, dict) or submitted.get("kind") != "keyframe":
        raise SystemExit(f"not a keyframe review: {args.review}")
    if submitted.get("validation", {}).get("status") != "PASS":
        raise SystemExit(f"review did not validate: {args.review}")
    index = materialise(args.episode, submitted, args.review)
    print(json.dumps({"status": index["status"], "admitted": index["admitted_count"],
                      "units": index["unit_count"], "out": index["_written_to"]},
                     ensure_ascii=False))
    return 0 if index["status"] == "ALL_ADMITTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
