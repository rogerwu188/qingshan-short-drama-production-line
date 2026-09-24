#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""identity_qa_lock.py — D-3 identity QA/LOCK + D-1 character asset registry.

D-3 (what was missing)
----------------------
``tools/initial_asset_library.py`` has only ``compile`` (writes
``REQUIRED_UNCREATED``) and ``gate`` (demands ``status == "LOCKED"`` by exact
equality, ``initial_asset_library.gate_asset:323``).  Nothing in the engine
writes the LOCK.  The only engine writer, ``bootstrap_identity_cards.py
--accept-source-qa``, is an OPERATOR DECLARATION, not a verdict.

Roger's recorded decision is that identity QA is a MACHINE review.  So the lock
is written here, and only from a real review:

  * the closed VLM questionnaire (``vlm_review_protocol.py --kind identity``),
    which a Claude reviewer answered while looking at the plates, becomes
    ``qa.checks`` — one row per question, carrying the answer and the reviewer's
    own observation;
  * for a character subject, the plates are additionally measured for real with
    the ENGINE's own ``character_identity_admission_gate.InsightFaceBackend``
    (method ``INSIGHTFACE_COSINE_V1``, thresholds from
    ``configs/GATE_REGISTRY_v3_20260716.json``) against the operator source
    reference in ``runtime/character_sources/`` — a deterministic cosine, not an
    opinion.  A face that cannot be embedded is a FAIL, never a skip.
  * ``qa.status`` becomes PASS only when every questionnaire answer passed and
    every deterministic measurement passed.  ``status`` becomes ``LOCKED`` only
    on ``qa.status == PASS``.
  * provenance records the review file sha256, the reviewer id and both
    timestamps, so the lock is traceable to the review that earned it.

What this tool deliberately does NOT do: it does not touch ``rights``.
``gate_asset`` also demands ``rights.status == "PASS"`` with a named basis, and
a rights basis is a legal declaration Roger makes (R-2 adaptation rights, R-5
voice copyright), not something a reviewer can observe.  Pass
``--rights-basis "<named basis>"`` to record one; without it the library keeps
``rights.status PENDING`` and the tool reports
``RIGHTS_BASIS_NOT_DECLARED_BY_LINE_OWNER`` as the remaining gate blocker.

D-1
---
``registry`` builds ``runtime/nalu_character_asset_registry.json`` for
``QINGSHAN_CHARACTER_REGISTRY``, in the shape
``multimodal_character_binding_guard._character_authority`` reads
(``characters[<registry_id>].generation_reference_image``, guard lines 204-206
and 430-436) and ``character_identity_admission_gate.evaluate`` membership-tests
(``registry["characters"]``).  Only LOCKED + qa PASS subjects are written; an
unlocked character is absent, which makes the guard report
``CANONICAL_VISUAL_REFERENCE_MISMATCH`` rather than silently binding nothing.

CLI
---
  lock     --episode EP --review <submitted review json> [--rights-basis "..."]
  registry --episode EP [--out <path>]
  status   --episode EP
"""

from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    GATE_REGISTRY, REVIEWER_ID, REVIEW_METHOD, Expectations, QaPaths,
    engine_module, find_scoped_operator_source, gate_parameters, now,
    read_json, sha256_file, write_json,
)

TOOL_ID = "identity_qa_lock.v1"
GATE_ID = "CHARACTER-IDENTITY-ADMISSION"
LIBRARY_SCHEMA = "ai_drama.production_asset_library.v1"

#: initial_asset_library.CATEGORY_LOCK_FIELDS — the lock this tool must fill.
LOCK_BUILDERS = {
    "characters": ("identity_lock",),
    "wardrobe": ("owner_character_id", "appearance_lock"),
    "props": ("physical_function", "appearance_lock"),
    "scenes": ("spatial_topology",),
    "reference_materials": ("usage_scope",),
}


# --------------------------------------------------------------------------- #
# deterministic measurement: insightface cosine, plate vs operator source
# --------------------------------------------------------------------------- #
def find_operator_source(asset_id: str, folder: Path | None = None) -> Path | None:
    """The operator's source photo for a character (Roger 2026-09-18, identity chain ①).

    The old lookup was ``<id>.png`` then ``<id>.*`` — it never matched the suffixed sources the
    line actually uses (``CHAR-QINMING__SOURCE_V2_TANG.png``), so every lock silently recorded
    ``NO_OPERATOR_SOURCE_REFERENCE`` and ``source_cosine: []``.  Order: exact ``<id>.png``,
    ``<id>__SOURCE*``, ``<id>.*``, ``<id>__*``, ``<id>_*`` — always anchored on the full asset id,
    never on a prefix that another character could share.
    """
    if folder is None:
        raise ValueError("folder is required; resolve it from QaPaths.character_sources")
    return find_scoped_operator_source(asset_id, folder)


def source_likeness_failures(source_scores: list[dict[str, Any]], pass_threshold: float) -> list[str]:
    """Roger 2026-09-18 (identity chain ①): every plate is scored against the operator source and
    ANY plate below the PASS threshold (0.45) fails the lock — the plate must be re-issued.  The
    old rule only failed below the 0.30 FAIL threshold, which let a 0.35 headshot through."""
    out = []
    for row in source_scores:
        score = float(row.get("cosine_vs_source", 0.0))
        if score < pass_threshold:
            out.append(f"SOURCE_LIKENESS_BELOW_PASS_THRESHOLD:{Path(str(row.get('plate'))).name}:{score:.6f}")
    return out


def measure_plate_identity(asset_id: str, plates: list[Path],
                           source: Path | None) -> dict[str, Any]:
    """Real INSIGHTFACE_COSINE_V1 measurement across the plates.

    Two independent facts are measured and both are reported honestly:
      * cross-view self-consistency — every plate must be the same face as the
        first plate (this is what ``identity_consistent_across_views`` claims,
        and unlike the reviewer's eye it is a number);
      * source likeness — when an operator source reference exists, the plates
        are scored against it.

    No fallback and no degradation: an unavailable runtime, an undecodable image
    or a frame with no single face is a recorded FAILURE, so a lock can never be
    written on an unmeasured plate.
    """
    params = gate_parameters(GATE_ID)
    pass_threshold = float(params.get("embedding_cosine_pass_threshold", 0.45))
    fail_threshold = float(params.get("embedding_cosine_fail_threshold", 0.30))
    model = str(params.get("embedding_model", "buffalo_l"))
    result: dict[str, Any] = {
        "method": "INSIGHTFACE_COSINE_V1",
        "embedding_model": model,
        "pass_threshold": pass_threshold,
        "fail_threshold": fail_threshold,
        "plate_count": len(plates),
        "cross_view_scores": [],
        "source_scores": [],
        "decision": "FAIL",
        "failures": [],
    }
    if not plates:
        result["failures"].append("NO_PLATE_ON_DISK")
        return result
    try:
        gate = engine_module("character_identity_admission_gate")
        backend = gate.InsightFaceBackend(model)
    except Exception as exc:  # noqa: BLE001
        result["failures"].append(f"INSIGHTFACE_RUNTIME_UNAVAILABLE:{exc}")
        return result

    embeddings: dict[str, list[float]] = {}
    for plate in plates:
        try:
            embeddings[str(plate)] = backend.embed(plate)
        except Exception as exc:  # noqa: BLE001
            result["failures"].append(f"PLATE_EMBEDDING_FAILED:{plate.name}:{exc}")
    if not embeddings:
        return result

    anchor_key = sorted(embeddings)[0]
    anchor = embeddings[anchor_key]
    result["anchor_plate"] = anchor_key
    for key in sorted(embeddings):
        if key == anchor_key:
            continue
        score = float(gate._cosine(embeddings[key], anchor))  # noqa: SLF001 — engine's own metric
        result["cross_view_scores"].append({"plate": key, "cosine_vs_anchor": round(score, 6)})
        if score < pass_threshold:
            result["failures"].append(
                f"CROSS_VIEW_IDENTITY_BELOW_PASS_THRESHOLD:{Path(key).name}:{score:.6f}")

    if source is not None and source.is_file():
        try:
            source_embeddings = backend.embed_all(source)
        except Exception as exc:  # noqa: BLE001
            result["failures"].append(f"SOURCE_EMBEDDING_FAILED:{source.name}:{exc}")
            source_embeddings = []
        result["source_reference"] = str(source)
        result["source_reference_sha256"] = sha256_file(source)
        for key in sorted(embeddings):
            if not source_embeddings:
                break
            score = max(float(gate._cosine(embeddings[key], ref))  # noqa: SLF001
                        for ref in source_embeddings)
            result["source_scores"].append({"plate": key, "cosine_vs_source": round(score, 6)})
        result["failures"].extend(source_likeness_failures(result["source_scores"], pass_threshold))
        result["source_likeness_rule"] = f"every plate >= {pass_threshold} vs operator source (Roger 2026-09-18 ①)"
    else:
        result["source_reference"] = None
        result["source_likeness"] = "NO_OPERATOR_SOURCE_REFERENCE_FOR_THIS_SUBJECT"

    result["decision"] = "PASS" if not result["failures"] else "FAIL"
    return result


# --------------------------------------------------------------------------- #
# the lock writer
# --------------------------------------------------------------------------- #
BASE_VIEW = "FULL_BODY_STANDING"


def plate_view(plate: Path, deliverables: list[str]) -> str:
    """The view a harvested plate carries, read from its file name.

    bootstrap_identity_cards.py names a view row ``<ASSET>__<VIEW>`` and the
    harvester keeps that task key in the file name
    (``E01_CHAR-LUZE__FRONT_NEUTRAL_HEADSHOT_<task id>.png``).  A plate whose
    name carries no ``__<VIEW>`` token is the base full-body plate.
    """
    name = plate.name
    for view in sorted(set(deliverables) | {BASE_VIEW}, key=len, reverse=True):
        if f"__{view}" in name:
            return view
    return BASE_VIEW if BASE_VIEW in deliverables or not deliverables else "IDENTITY_PLATE"


def _artifacts(plates: list[Path], deliverables: list[str]) -> list[dict[str, Any]]:
    """One artifact per plate, role = its view; the base full-body plate first.

    artifacts[0] is what identity_qa_lock.py registry publishes as
    generation_reference_image, and what build_keyframe_manifest.py binds when
    no artifact carries a ``canonical*`` role — so the full-body plate (build +
    wardrobe + face) leads, and the headshot / bust follow as extra canonical
    views for the identity corpus.
    """
    order = {BASE_VIEW: 0}
    for index, view in enumerate(deliverables, 1):
        order.setdefault(view, index)
    rows: list[dict[str, Any]] = []
    for plate in plates:
        view = plate_view(plate, deliverables)
        rows.append({
            "role": view,
            "canonical_identity_reference": view == BASE_VIEW,
            "media_type": "image/png" if plate.suffix.lower() == ".png" else "image/jpeg",
            "path": str(plate),
            "sha256": sha256_file(plate),
            "aspect_ratio": "9:16",
        })
    rows.sort(key=lambda row: (order.get(row["role"], 99), row["path"]))
    return rows


def _lock(category: str, asset: dict[str, Any], item: dict[str, Any],
          measurement: dict[str, Any], plates: list[Path]) -> dict[str, Any]:
    spec = asset.get("specification") or {}
    expectations = (item.get("request_item") or {}).get("expectations") or {}
    lock: dict[str, Any] = {}
    if category == "characters":
        lock["identity_lock"] = {
            "locked_fields": spec.get("identity_lock_required_fields") or [],
            "canonical_name": spec.get("canonical_name"),
            "apparent_age_range": spec.get("apparent_age_range"),
            "sex": spec.get("sex"),
            "appearance": expectations.get("appearance"),
            "canonical_view_paths": [str(plate) for plate in plates],
            "canonical_view_sha256": {str(plate): sha256_file(plate) for plate in plates},
            "canonical_view_count": len(plates),
            "embedding_method": measurement.get("method"),
            "embedding_model": measurement.get("embedding_model"),
            "cross_view_cosine": measurement.get("cross_view_scores"),
            "source_cosine": measurement.get("source_scores"),
        }
    elif category == "wardrobe":
        lock["owner_character_id"] = spec.get("owner_character_id") or (
            expectations.get("wardrobe") or {}).get("character_id")
        lock["appearance_lock"] = {
            key: value for key, value in (expectations.get("wardrobe") or {}).items()
            if key != "character_id"} or {"appearance": expectations.get("appearance")}
    elif category == "props":
        lock["physical_function"] = spec.get("physical_function") or expectations.get("appearance")
        lock["appearance_lock"] = {
            "appearance": expectations.get("appearance"),
            "palette": expectations.get("visual_culture_palette"),
            "plate_paths": [str(plate) for plate in plates],
        }
    elif category == "scenes":
        lock["spatial_topology"] = spec.get("spatial_topology") or {
            "declared_in": "global_space_map", "plate_paths": [str(plate) for plate in plates]}
    else:
        for field in LOCK_BUILDERS.get(category, ()):  # pragma: no cover
            lock[field] = spec.get(field)
    return lock


def _qa_checks(item: dict[str, Any], questionnaire: dict[str, Any],
               measurement: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for key, answer in (item.get("answers") or {}).items():
        spec = questionnaire.get(key) or {}
        checks.append({
            "check_id": key,
            "question": spec.get("question"),
            "answer": answer,
            "status": "PASS" if str(answer) in {"PASS", "YES", "NOT_APPLICABLE"} else str(answer),
            "method": REVIEW_METHOD,
            "reviewer": REVIEWER_ID,
            "reviewer_type": "AI_VISUAL",
        })
    checks.append({
        "check_id": "INSIGHTFACE_COSINE_V1",
        "question": "Do the plates embed to one identity, and (when an operator source "
                    "reference exists) to that source, at the registry thresholds?",
        "answer": measurement.get("decision"),
        "status": measurement.get("decision"),
        "method": "INSIGHTFACE_COSINE_V1",
        "reviewer": TOOL_ID,
        "reviewer_type": "MACHINE_DETERMINISTIC",
        "measurement": measurement,
    })
    for defect in item.get("defects") or []:
        checks.append({
            "check_id": f"DEFECT:{defect.get('code')}",
            "answer": defect.get("severity"),
            "status": "FAIL" if str(defect.get("severity")) in {"P0", "P1"} else "P2_WITHIN_BUDGET",
            "method": REVIEW_METHOD,
            "reviewer": REVIEWER_ID,
            "description": defect.get("description"),
        })
    return checks


def materialise(episode: str, submitted: dict[str, Any],
                submitted_path: Path, *, rights_basis: str | None = None) -> dict[str, Any]:
    """Write qa.status + status LOCKED into both library copies, then the registry."""
    p = QaPaths(episode)
    exp = Expectations(episode)
    review_sha = sha256_file(submitted_path)
    questionnaire = submitted.get("questionnaire") or {}
    rights_basis = rights_basis or submitted.get("rights_basis")

    targets = [path for path in (p.identity_library, p.asset_library) if path.is_file()]
    if not targets:
        return {"status": "MATERIALISATION_BLOCKED",
                "failures": [f"asset_library_absent:{p.identity_library}"]}

    rows: list[dict[str, Any]] = []
    libraries = {path: read_json(path, {}) or {} for path in targets}
    for path, library in libraries.items():
        if library.get("schema") != LIBRARY_SCHEMA:
            return {"status": "MATERIALISATION_BLOCKED",
                    "failures": [f"library_schema_mismatch:{path}"]}
        if str(library.get("project_id") or "") != p.series_id:
            return {"status": "MATERIALISATION_BLOCKED",
                    "failures": [f"library_project_mismatch:{path}:"
                                 f"{library.get('project_id')}!={p.series_id}"]}

    for item in submitted.get("items") or []:
        asset_id = item["item_id"]
        request_item = item.get("request_item") or {}
        category = request_item.get("category") or "characters"
        deliverables = (request_item.get("expectations") or {}).get("card_deliverables") or []
        plates = [Path(media["path"]) for media in request_item.get("media") or []
                  if media.get("role") == "IDENTITY_PLATE" and media.get("path")
                  and Path(media["path"]).is_file()]
        # Prefer the exact source bound into this review request (episode scopes keep their
        # sources out of the global folder); fall back to the scoped folder lookup.
        source = None
        for media in request_item.get("media") or []:
            if media.get("role") == "OPERATOR_SOURCE_REFERENCE" and media.get("path"):
                candidate = Path(str(media["path"]))
                if candidate.is_file():
                    source = candidate
                    break
        if source is None:
            source = find_operator_source(asset_id, p.character_sources)

        measurement = ({"method": "INSIGHTFACE_COSINE_V1", "decision": "NOT_APPLICABLE",
                        "reason": "non-character subject has no face to embed",
                        "failures": []}
                       if category != "characters"
                       else measure_plate_identity(asset_id, plates, source))

        review_pass = item["verdict"] in {"PASS", "PASS_WITH_P2"}
        measure_pass = str(measurement.get("decision")) in {"PASS", "NOT_APPLICABLE"}
        plate_present = bool(plates)
        qa_status = "PASS" if (review_pass and measure_pass and plate_present) else "FAIL"

        blockers: list[str] = []
        if not plate_present:
            blockers.append("IDENTITY_PLATE_NOT_ON_DISK")
        if not review_pass:
            blockers.append(f"VLM_REVIEW_{item['verdict']}")
        if not measure_pass:
            blockers.extend(measurement.get("failures") or ["INSIGHTFACE_MEASUREMENT_FAILED"])

        qa_block = {
            "status": qa_status,
            "checks": _qa_checks(item, questionnaire, measurement),
            "reviewer": REVIEWER_ID,
            "reviewer_type": "AI_VISUAL",
            "review_method": REVIEW_METHOD,
            "review_file": str(submitted_path),
            "review_file_sha256": review_sha,
            "reviewed_at": submitted.get("reviewed_at"),
            "recorded_at": now(),
            "recorded_by": TOOL_ID,
            "observation": item.get("observation"),
            "defects": item.get("defects") or [],
            "objective_verification": measurement,
            "blockers": blockers,
        }

        applied: list[str] = []
        for path, library in libraries.items():
            asset = ((library.get("assets") or {}).get(category) or {}).get(asset_id)
            if asset is None:
                continue
            asset["qa"] = qa_block
            if qa_status == "PASS":
                asset["lock"] = _lock(category, asset, item, measurement, plates)
                asset["artifacts"] = _artifacts(plates, deliverables)
                asset["status"] = "LOCKED"
            else:
                asset["status"] = "QA_FAILED_NOT_LOCKED"
            if rights_basis:
                asset["rights"] = {"status": "PASS", "basis": rights_basis,
                                   "declared_by": "LINE_OWNER", "recorded_at": now()}
            provenance = asset.setdefault("provenance", [])
            provenance.append({
                "event": "IDENTITY_QA_MACHINE_REVIEW",
                "at": now(),
                "by": TOOL_ID,
                "reviewer": REVIEWER_ID,
                "review_method": REVIEW_METHOD,
                "review_file": str(submitted_path),
                "review_file_sha256": review_sha,
                "reviewed_at": submitted.get("reviewed_at"),
                "request_file": submitted.get("request_path"),
                "request_file_sha256": submitted.get("request_sha256"),
                "qa_status": qa_status,
                "resulting_status": asset["status"],
                "objective_method": measurement.get("method"),
                "objective_decision": measurement.get("decision"),
                "artifact_sha256": [row["sha256"] for row in asset.get("artifacts") or []],
            })
            history = asset.setdefault("history", [])
            history.append({"at": now(), "by": TOOL_ID, "status": asset["status"],
                            "qa_status": qa_status})
            asset["updated_at"] = now()
            applied.append(str(path))

        rows.append({
            "asset_id": asset_id, "category": category, "qa_status": qa_status,
            "status": "LOCKED" if qa_status == "PASS" else "QA_FAILED_NOT_LOCKED",
            "verdict": item["verdict"], "plate_count": len(plates),
            "objective_decision": measurement.get("decision"),
            "blockers": blockers, "libraries_updated": applied,
        })

    for path, library in libraries.items():
        library["updated_at"] = now()
        library.setdefault("maintained_by", []) if isinstance(
            library.get("maintained_by"), list) else None
        write_json(path, library)

    locked = [row for row in rows if row["qa_status"] == "PASS"]
    registry = build_registry(episode, out=p.character_registry) if locked else {
        "status": "NOT_WRITTEN_NO_LOCKED_SUBJECT"}

    record = {
        "schema": "nalu.identity_qa_lock.v1",
        "episode": episode,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "reviewer": REVIEWER_ID,
        "review_method": REVIEW_METHOD,
        "review_file": str(submitted_path),
        "review_file_sha256": review_sha,
        "libraries": [str(path) for path in targets],
        "rights_basis": rights_basis,
        "status": ("PASS" if rows and all(row["qa_status"] == "PASS" for row in rows)
                   else "FAIL" if rows else "NO_ITEMS"),
        "locked_count": len(locked),
        "failed_count": len(rows) - len(locked),
        "subjects": rows,
        "character_registry": registry,
        "remaining_gate_blockers": (
            [] if rights_basis else ["RIGHTS_BASIS_NOT_DECLARED_BY_LINE_OWNER"]),
        "gate_command": " ".join([
            str(sys.executable), str(Path(f"{_np.ENGINE_ROOT}/tools/initial_asset_library.py")),
            "gate", "--requirements", str(p.asset_requirements),
            "--library", str(p.identity_library), "--episode", episode,
            "--report", str(p.identity / f"{episode}_asset_library_gate.json")]),
    }
    write_json(p.identity_qa, record)
    record["_written_to"] = str(p.identity_qa)
    return record


# --------------------------------------------------------------------------- #
# D-1 registry
# --------------------------------------------------------------------------- #
def build_registry(episode: str, *, out: Path | None = None) -> dict[str, Any]:
    """Emit QINGSHAN_CHARACTER_REGISTRY from LOCKED plates only."""
    exp = Expectations(episode)
    out = Path(out) if out is not None else exp.p.character_registry
    source_library = (exp.p.identity_library if exp.p.identity_library.is_file()
                      else exp.p.reusable_asset_library())
    library = read_json(source_library, {}) or {}
    entity_registry = read_json(exp.p.entity_registry, {}) or {}
    aliases = entity_registry.get("entity_aliases") or {}
    by_registry_id = {str(value[1]): (entity_id, str(value[0]))
                      for entity_id, value in aliases.items()
                      if isinstance(value, list) and len(value) == 2}

    assets = ((library.get("assets") or {}).get("characters") or {})
    # an imported source registry (legacy-line migration) sits beside the scope's character registry
    runtime_dir = Path(exp.p.character_registry).parent
    source_registry = read_json(runtime_dir / "character_asset_registry.json", {}) or {}
    source_rows = source_registry.get("characters") or []
    canonical_to_local = {
        str(row.get("source_registry_id")): str(row.get("character_id"))
        for row in source_rows
        if isinstance(row, dict) and row.get("source_registry_id") and row.get("character_id")
    }
    local_by_label = {
        str(row.get("label")): row
        for key, row in assets.items()
        if isinstance(row, dict) and not str(key).startswith("CHAR-")
        and row.get("label") and len(row.get("artifacts") or []) >= 3
    }
    # The authored contract may use a canonical cross-episode CHAR-* id whose
    # imported source registry has a different historical id.  Bind that id by
    # the contract's canonical character name to the already LOCKED local
    # three-view asset; do not duplicate or regenerate media.
    for canonical_id, wardrobe_row in exp.wardrobe_by_id.items():
        name = str(wardrobe_row.get("character") or "")
        current = assets.get(canonical_id)
        # A migrated v4 library may contain a canonical CHAR-* row whose
        # provenance/artifacts still point at another local subject.  Treat
        # that as unusable even when its status/QA flags say LOCKED/PASS;
        # otherwise the registry builder silently aliases every canonical
        # character to the first imported plate (the E59 identity failure).
        current_label = str((current or {}).get("label") or "") if isinstance(current, dict) else ""
        current_usable = (
            isinstance(current, dict)
            and current.get("status") == "LOCKED"
            and (current.get("qa") or {}).get("status") == "PASS"
            and len(current.get("artifacts") or []) >= 3
            and current_label == name
        )
        if not current_usable and name in local_by_label:
            assets[canonical_id] = local_by_label[name]

    characters: dict[str, Any] = {}
    skipped: list[dict[str, Any]] = []
    for asset_id, asset in sorted(assets.items()):
        qa = asset.get("qa") or {}
        if asset.get("status") != "LOCKED" or qa.get("status") != "PASS":
            skipped.append({"asset_id": asset_id, "status": asset.get("status"),
                            "qa_status": qa.get("status"),
                            "reason": "NOT_LOCKED_OR_QA_NOT_PASS"})
            continue
        artifact_source = asset
        local_id = canonical_to_local.get(asset_id)
        local_asset = assets.get(local_id) if local_id else None
        if not isinstance(local_asset, dict):
            local_asset = local_by_label.get(str(asset.get("label") or ""))
        if isinstance(local_asset, dict) and len(local_asset.get("artifacts") or []) > len(asset.get("artifacts") or []):
            artifact_source = local_asset
        artifacts = [row for row in artifact_source.get("artifacts") or [] if row.get("path")]
        if not artifacts:
            skipped.append({"asset_id": asset_id, "reason": "NO_ARTIFACT_PATH"})
            continue
        primary = artifacts[0]
        entity_id, display = by_registry_id.get(asset_id, (None, asset.get("label")))
        raw_lock = (artifact_source.get("lock") or {}).get("identity_lock") or {}
        # Imported v4 rows may carry the legacy prose identity lock as a
        # string, while locally bootstrapped rows carry the structured lock
        # object.  The prose is still provenance, but it is not a mapping and
        # must not crash registry materialisation.
        lock = raw_lock if isinstance(raw_lock, dict) else {}
        characters[asset_id] = {
            "registry_id": asset_id,
            "character_id": asset_id,
            "entity_id": entity_id,
            "display_name": display,
            "canonical_name": lock.get("canonical_name") or asset.get("label"),
            # the three keys multimodal_character_binding_guard:430-436 reads, in
            # its own precedence order.  All three point at the same plate so the
            # guard's CANONICAL_VISUAL_SHA_MISMATCH check is exact.
            "generation_reference_image": primary["path"],
            "identity_reference_image": primary["path"],
            "reference_image": primary["path"],
            "generation_reference_image_sha256": primary.get("sha256"),
            "canonical_reference_paths": [row["path"] for row in artifacts],
            "canonical_reference_sha256": {row["path"]: row.get("sha256") for row in artifacts},
            "canonical_view_count": len(artifacts),
            "identity_lock": lock,
            "status": "LOCKED",
            "qa_status": "PASS",
            "qa_review_file": qa.get("review_file"),
            "qa_review_file_sha256": qa.get("review_file_sha256"),
            "reviewer": qa.get("reviewer"),
            "review_method": qa.get("review_method"),
            "locked_at": asset.get("updated_at"),
            "first_use_episode": asset.get("first_use_episode"),
        }

    payload = {
        "schema": "nalu.character_asset_registry.v1",
        "line": "nalu",
        "series_scope_id": exp.p.scope_id,
        "series_id": exp.p.series_id,
        "work": (library.get("work") or
                 ("夜无疆" if exp.p.scope["is_default"] else None) or
                 library.get("project_id") or exp.p.series_id),
        "author": (library.get("author") or
                   ("辰东" if exp.p.scope["is_default"] else None)),
        "purpose": "QINGSHAN_CHARACTER_REGISTRY for tools/multimodal_character_binding_guard.py "
                   "(characters[<registry_id>].generation_reference_image, guard:204-206 and "
                   "430-436) and for tools/character_identity_admission_gate.py --registry "
                   "membership.  Resolves open decision D-1.",
        "authority": "Only subjects whose asset-library row is status LOCKED with qa.status PASS "
                     "appear here.  An unlocked character is absent on purpose: the guard then "
                     "reports CANONICAL_VISUAL_REFERENCE_MISMATCH instead of binding nothing.",
        "generated_at": now(),
        "generated_by": TOOL_ID,
        "source_library": str(source_library),
        "source_library_sha256": sha256_file(source_library),
        "episode": episode,
        "character_count": len(characters),
        "characters": characters,
        "not_registered": skipped,
    }
    if characters:
        write_json(out, payload)
        payload["_written_to"] = str(out)
        payload["status"] = "WRITTEN"
    else:
        payload["status"] = "NOT_WRITTEN_NO_LOCKED_CHARACTER"
        payload["_written_to"] = None
    return payload


# --------------------------------------------------------------------------- #
def route_status(episode: str) -> dict[str, Any]:
    """What S3.qa can say without a review: is the route runnable at all?"""
    p = QaPaths(episode)
    try:
        engine_module("character_identity_admission_gate").InsightFaceBackend(
            str(gate_parameters(GATE_ID).get("embedding_model", "buffalo_l")))
        insight = {"available": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        insight = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    plates = sorted(p.plates.glob("*")) if p.plates.is_dir() else []
    return {
        "route": f"{__file__} lock --episode {episode} --review <submitted review>",
        "gate_registry": str(GATE_REGISTRY),
        "objective_method": "INSIGHTFACE_COSINE_V1",
        "insightface_runtime": insight,
        "series_scope_id": p.scope_id,
        "series_id": p.series_id,
        "asset_library": str(p.reusable_asset_library()),
        "character_sources": str(p.character_sources),
        "character_registry": str(p.character_registry),
        "character_registry_present": p.character_registry.is_file(),
        "plates_on_disk": len(plates),
        "identity_qa_record": str(p.identity_qa),
        "identity_qa_record_present": p.identity_qa.is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lk = sub.add_parser("lock")
    lk.add_argument("--episode", required=True)
    lk.add_argument("--review", required=True, type=Path)
    lk.add_argument("--rights-basis")
    rg = sub.add_parser("registry")
    rg.add_argument("--episode", required=True)
    rg.add_argument("--out", type=Path)
    st = sub.add_parser("status")
    st.add_argument("--episode", required=True)
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(route_status(args.episode), ensure_ascii=False, indent=2))
        return 0
    if args.command == "registry":
        payload = build_registry(args.episode, out=args.out)
        print(json.dumps({"status": payload["status"], "out": payload.get("_written_to"),
                          "characters": payload["character_count"],
                          "not_registered": len(payload["not_registered"])},
                         ensure_ascii=False))
        return 0 if payload["status"] == "WRITTEN" else 2

    submitted = read_json(args.review)
    if not isinstance(submitted, dict) or submitted.get("kind") != "identity":
        raise SystemExit(f"not an identity review: {args.review}")
    if submitted.get("validation", {}).get("status") != "PASS":
        raise SystemExit(f"review did not validate: {args.review}")
    record = materialise(args.episode, submitted, args.review, rights_basis=args.rights_basis)
    print(json.dumps({"status": record["status"], "locked": record.get("locked_count"),
                      "failed": record.get("failed_count"),
                      "registry": (record.get("character_registry") or {}).get("status"),
                      "remaining": record.get("remaining_gate_blockers"),
                      "out": record.get("_written_to")}, ensure_ascii=False))
    return 0 if record["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
