#!/usr/bin/env python3
"""Provider reference exclusion: stop TRANSMITTING one non-identity reference, keep its authority.

Field blocker (device ...1324, E01 S5, 2026-11-06): HopsAPI gpt-image-2 refuses, deterministically and
at zero cost (424 "Provider error" at execution), one engine-rendered reference -- the place map
``GSM-NALU-HUT_V1.png`` (1600x2200 top-down topology diagram with Chinese labels).  Img2Img with only
that image failed every time; with only the headshot or only the episode global map it succeeded.  Every
S5 task binds the place map, so the whole episode was 0/35.

An exclusion is declared, never inferred:

    $NALU_RUNTIME_ROOT/preproduction/<EP>/provider_reference_exclusions.json
    {"schema": "nalu.provider_reference_exclusions.v1",
     "episode": "E01",                      (optional; must match when present)
     "exclusions": [{
        "asset_id": "GSM-NALU-HUT" | "sha256": "<64 hex>" | "path": "<file path>",
        "role": "global_space_map",         (optional narrowing for asset_id matches)
        "reason": "HOPSAPI_DETERMINISTIC_424_SINGLE_REFERENCE",
        "evidence": {"provider": "hopsapi", "provider_code": 424, "request_ids": ["aitk-..."],
                     "single_reference_probe": true},
        "declared_by": "...", "declared_at": "2026-11-06T..Z"}]}

Semantics (file level): every binding whose file matches a declaration keeps its place in
``reference_bindings`` (the spatial authority -- ids, coordinates -- is unchanged) but is marked
``transmitted: false`` with ``transport_excluded_reason``; the provider array, the ``@图片N`` labels and the
prompt's reference-use block are compiled from the transmitted bindings only.  Character identity plates
(face / supplemental face views) can never be excluded: that is refused with
``PROVIDER_REFERENCE_EXCLUSION_IDENTITY_REFUSED``.  Without a declaration file nothing changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "nalu.provider_reference_exclusions.v1"
FILE_NAME = "provider_reference_exclusions.json"
IDENTITY_ROLES = {"character", "character_reference", "identity"}
IDENTITY_KINDS = {"CHARACTER_IDENTITY_PLATE"}
PLACE_MAP_ADVISORY = "PLACE_MAP_TRANSPORT_EXCLUDED"
SHA_RE = re.compile(r"[0-9a-f]{64}")


class ExclusionError(ValueError):
    """A declaration that cannot be applied (malformed, or it would drop an identity plate)."""


def is_identity_binding(row: dict[str, Any]) -> bool:
    role = str(row.get("role") or "").lower()
    return role in IDENTITY_ROLES or str(row.get("kind") or "") in IDENTITY_KINDS


def is_transmitted(row: dict[str, Any]) -> bool:
    """Legacy bindings carry no flag and are transmitted."""
    return row.get("transmitted") is not False


def transmitted_bindings(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in rows or [] if isinstance(row, dict) and is_transmitted(row)]


def _entry_failures(index: int, entry: Any) -> list[str]:
    tag = f"exclusions[{index}]"
    if not isinstance(entry, dict):
        return [f"{tag}:NOT_AN_OBJECT"]
    failures = []
    selectors = [key for key in ("asset_id", "sha256", "path") if str(entry.get(key) or "").strip()]
    if not selectors:
        failures.append(f"{tag}:SELECTOR_REQUIRED(asset_id|sha256|path)")
    if entry.get("sha256") and not SHA_RE.fullmatch(str(entry["sha256"]).strip().lower()):
        failures.append(f"{tag}:SHA256_INVALID")
    for key in ("reason", "declared_by", "declared_at"):
        if not str(entry.get(key) or "").strip():
            failures.append(f"{tag}:{key.upper()}_REQUIRED")
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        failures.append(f"{tag}:EVIDENCE_REQUIRED")
    else:
        if not str(evidence.get("provider") or "").strip():
            failures.append(f"{tag}:EVIDENCE_PROVIDER_REQUIRED")
        if evidence.get("provider_code") in (None, ""):
            failures.append(f"{tag}:EVIDENCE_PROVIDER_CODE_REQUIRED")
        if evidence.get("single_reference_probe") is not True:
            failures.append(f"{tag}:EVIDENCE_SINGLE_REFERENCE_PROBE_REQUIRED")
        if not (evidence.get("request_ids") or evidence.get("probe_transactions")):
            failures.append(f"{tag}:EVIDENCE_REQUEST_IDS_REQUIRED")
    return failures


def validate_declaration(doc: Any, *, episode: str | None = None) -> list[str]:
    if not isinstance(doc, dict):
        return ["DECLARATION_NOT_AN_OBJECT"]
    failures = []
    if doc.get("schema") != SCHEMA:
        failures.append(f"SCHEMA_MISMATCH:{doc.get('schema')}!={SCHEMA}")
    declared_episode = str(doc.get("episode") or "").strip().upper()
    if episode and declared_episode and declared_episode != str(episode).strip().upper():
        failures.append(f"EPISODE_MISMATCH:{declared_episode}!={episode}")
    rows = doc.get("exclusions")
    if not isinstance(rows, list):
        failures.append("EXCLUSIONS_MUST_BE_A_LIST")
        rows = []
    for index, entry in enumerate(rows):
        failures.extend(_entry_failures(index, entry))
    return failures


def load_declaration(path: str | Path | None, *, episode: str | None = None) -> dict[str, Any] | None:
    """The validated declaration, or None when ``path`` is unset / absent (legacy: nothing changes)."""
    if not path:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExclusionError(f"PROVIDER_REFERENCE_EXCLUSIONS_UNREADABLE:{path}:{exc}") from None
    failures = validate_declaration(doc, episode=episode)
    if failures:
        raise ExclusionError(f"PROVIDER_REFERENCE_EXCLUSIONS_INVALID:{path}:" + ";".join(failures))
    doc = dict(doc)
    doc["_source_path"] = str(path)
    doc["_source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return doc


def _norm_path(value: Any) -> str:
    text = str(value or "").strip()
    return str(Path(text).expanduser()) if text else ""


def _entry_matches(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    sha = str(entry.get("sha256") or "").strip().lower()
    if sha and sha == str(row.get("sha256") or "").strip().lower():
        return True
    path = _norm_path(entry.get("path"))
    if path:
        row_path = _norm_path(row.get("path"))
        if row_path and (row_path == path or Path(row_path).name == path and "/" not in path):
            return True
    asset_id = str(entry.get("asset_id") or "").strip()
    if asset_id and asset_id in {str(row.get("entity_id") or ""), str(row.get("library_asset_id") or "")}:
        role = str(entry.get("role") or "").strip()
        return not role or role == str(row.get("role") or "")
    return False


def apply_exclusions(bindings: list[dict[str, Any]], declaration: dict[str, Any] | None,
                     *, task_key: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (bindings with excluded rows marked, applied records).  ``bindings`` is not mutated.

    File level: a declaration that selects one binding excludes the FILE, so every binding sharing that
    path is marked too (otherwise the file would still be sent).  Any identity binding on an excluded
    file raises ``ExclusionError`` (PROVIDER_REFERENCE_EXCLUSION_IDENTITY_REFUSED)."""
    rows = [dict(row) for row in bindings]
    if not declaration:
        return rows, []
    entries = [entry for entry in declaration.get("exclusions") or [] if isinstance(entry, dict)]
    excluded_paths: dict[str, dict[str, Any]] = {}
    for entry in entries:
        for row in rows:
            if _entry_matches(entry, row):
                excluded_paths.setdefault(str(row.get("path") or ""), entry)
    if not excluded_paths:
        return rows, []
    source = declaration.get("_source_path") or FILE_NAME
    applied: list[dict[str, Any]] = []
    for row in rows:
        entry = excluded_paths.get(str(row.get("path") or ""))
        if entry is None:
            continue
        if is_identity_binding(row):
            raise ExclusionError(
                f"PROVIDER_REFERENCE_EXCLUSION_IDENTITY_REFUSED:{task_key}:{row.get('role')}/{row.get('entity_id')}: "
                "a character identity plate can never be withheld from the provider; remove this entry from "
                f"{source} (only place/subspace/global maps, scene, wardrobe and prop plates may be excluded)")
        row["transmitted"] = False
        row["transport_excluded_reason"] = str(entry.get("reason"))
        row["transport_exclusion_ref"] = str(source)
        applied.append({
            "role": row.get("role"), "entity_id": row.get("entity_id"), "path": row.get("path"),
            "sha256": row.get("sha256"), "reason": entry.get("reason"),
            "declared_by": entry.get("declared_by"), "declared_at": entry.get("declared_at"),
            "evidence": entry.get("evidence"), "declaration_ref": str(source),
            "declaration_sha256": declaration.get("_source_sha256"),
            "authority_retained": True,
        })
    if not transmitted_bindings(rows):
        raise ExclusionError(f"PROVIDER_REFERENCE_EXCLUSION_LEAVES_NO_REFERENCE:{task_key}")
    return rows, applied


def merge_declaration(existing: dict[str, Any] | None, entries: list[dict[str, Any]], *,
                      episode: str) -> dict[str, Any]:
    """Append ``entries`` (deduplicated by sha256/path/asset_id) to a declaration document."""
    doc = dict(existing or {})
    doc.pop("_source_path", None)
    doc.pop("_source_sha256", None)
    doc.setdefault("schema", SCHEMA)
    doc.setdefault("episode", episode)
    rows = [row for row in doc.get("exclusions") or [] if isinstance(row, dict)]
    seen = {(row.get("sha256"), row.get("path"), row.get("asset_id")) for row in rows}
    for entry in entries:
        key = (entry.get("sha256"), entry.get("path"), entry.get("asset_id"))
        if key not in seen:
            rows.append(entry)
            seen.add(key)
    doc["exclusions"] = rows
    failures = validate_declaration(doc, episode=episode)
    if failures:
        raise ExclusionError("PROVIDER_REFERENCE_EXCLUSIONS_INVALID:" + ";".join(failures))
    return doc
