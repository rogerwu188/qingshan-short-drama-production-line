#!/usr/bin/env python3
"""One-time, idempotent import of historical reference originals into the studio library.

Read-only inventory first (``run(..., apply=False)`` is a PREVIEW and writes nothing), then, on
request, copy-with-verification.  Nothing in the old runtime is ever modified, moved or deleted:

* history evidence (contracts, submit payloads, review receipts, transaction files, asset-library
  JSON) is only READ; the compatibility map lives in the studio library
  (``catalog/legacy/<2>/<sha>.json``: old path + sha -> asset version);
* a file is imported only when its bytes hash to the sha recorded for it; a path whose bytes differ
  from the recorded sha is reported as a SHA conflict and is NOT imported;
* running it twice adds no object and no version (same bytes => same object; same content set =>
  same version);
* the preview reports disk headroom, so a shortfall is a stated number instead of a half-finished copy;
* originals that are only referenced by a missing path are listed as missing / recoverable, never
  fabricated.

It works on whatever registration data it is pointed at (any project_id); nothing here is specific to
one production.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable

try:
    from tools import studio_asset_library as core
except ImportError:  # pragma: no cover - flat tools/ on sys.path
    import studio_asset_library as core  # type: ignore[no-redef]

IMAGE_EXTS = {"." + ext for ext in core.MEDIA_TYPES}
KIND_OF_CATEGORY = {"characters": "character", "props": "prop", "scenes": "scene", "creatures": "creature"}
REGISTER_CATEGORIES = ("characters", "props", "scenes", "creatures")
HEADROOM_MARGIN = 1.10


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def inventory_libraries(library_files: Iterable[str | Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(refs, rows).  ``rows`` carry one entry per asset-library row with its artifact refs."""
    refs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for file in library_files:
        file = Path(file)
        data = json.loads(file.read_text(encoding="utf-8"))
        project_id = str(data.get("project_id") or "")
        for category, by_id in (data.get("assets") or {}).items():
            if not isinstance(by_id, dict):
                continue
            for asset_id, row in by_id.items():
                if not isinstance(row, dict):
                    continue
                qa = (row.get("qa") or {})
                approved = str(row.get("status") or "") == "LOCKED" and str(qa.get("status") or "") == "PASS"
                group = {"project_id": project_id, "category": category, "asset_id": asset_id,
                         "label": row.get("label") or asset_id, "status": row.get("status"),
                         "qa_status": qa.get("status"), "approved": approved, "qa_block": qa,
                         "library_file_name": file.name, "refs": []}
                for artifact in row.get("artifacts") or []:
                    if isinstance(artifact, dict) and artifact.get("path") and _is_image(str(artifact["path"])):
                        ref = {"path": str(artifact["path"]), "sha": artifact.get("sha256"), "usage": artifact.get("role") or "ARTIFACT",
                               "source": "LIBRARY_ARTIFACT", **{k: group[k] for k in ("project_id", "category", "asset_id", "approved", "status")}}
                        group["refs"].append(ref)
                        refs.append(ref)
                authority = row.get("original_identity_authority")
                if isinstance(authority, dict) and authority.get("path") and _is_image(str(authority["path"])):
                    ref = {"path": str(authority["path"]), "sha": authority.get("sha256"), "usage": "APPROVED_ORIGINAL_SOURCE",
                           "source": "ORIGINAL_IDENTITY_AUTHORITY", **{k: group[k] for k in ("project_id", "category", "asset_id", "approved", "status")}}
                    group["refs"].append(ref)
                    refs.append(ref)
                if group["refs"]:
                    rows.append(group)
    return refs, rows


def inventory_source_maps(map_files: Iterable[str | Path]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for file in map_files:
        file = Path(file)
        data = json.loads(file.read_text(encoding="utf-8"))
        folders = [Path(str(data.get("source_folder") or "")), file.parent / "character_sources"]
        for binding in data.get("bindings") or []:
            name = binding.get("file")
            if not name:
                continue
            chosen = next((str(f / name) for f in folders if str(f) and (f / name).is_file()), str(folders[-1] / name))
            refs.append({"path": chosen, "sha": binding.get("sha256"), "usage": binding.get("usage") or "SOURCE_PHOTO",
                         "source": "CHARACTER_SOURCE_MAP", "project_id": None, "category": "characters",
                         "asset_id": binding.get("character_id"), "approved": False, "status": "SOURCE_PHOTO_REGISTERED"})
    return refs


def inventory_harvest_statuses(status_files: Iterable[str | Path]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for file in status_files:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        for row in data.get("results") or []:
            if row.get("output_path") and row.get("sha256"):
                refs.append({"path": str(row["output_path"]), "sha": row["sha256"], "usage": "HARVESTED_ORIGINAL",
                             "source": "HARVEST_RECEIPT", "project_id": None, "category": "reference_materials",
                             "asset_id": None, "approved": False, "status": "UNREVIEWED_HARVEST",
                             "task_key": row.get("task_key"), "task_id": row.get("task_id"),
                             "episode": data.get("episode")})
    return refs


def _headroom(root: Path) -> dict[str, Any]:
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return {"free_bytes": usage.free, "total_bytes": usage.total}


def analyse(root: Path, refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Facts only; touches no file except to read and hash the referenced ones."""
    actual: dict[str, tuple[str | None, int]] = {}
    for ref in refs:
        if ref["path"] not in actual:
            p = Path(ref["path"])
            actual[ref["path"]] = ((core.sha256_file(p), p.stat().st_size) if p.is_file() and not p.is_symlink() else (None, 0))
    existing = core.Library(root, create=False) if (root / "library.json").is_file() else None
    sha_by_path: dict[str, set[str]] = {}
    for ref in refs:
        if ref.get("sha"):
            sha_by_path.setdefault(ref["path"], set()).add(ref["sha"])
    missing, conflicts, importable = [], [], {}
    for path, shas in sorted(sha_by_path.items()):
        got, size = actual[path]
        if got is None:
            missing.append({"path_name": Path(path).name, "recorded_sha256": sorted(shas)})
        elif got not in shas:
            conflicts.append({"path_name": Path(path).name, "recorded_sha256": sorted(shas), "actual_sha256": got,
                              "reason": "FILE_BYTES_DIFFER_FROM_RECORDED_SHA"})
        else:
            importable[got] = {"bytes": size, "path": path}
    for path, shas in sha_by_path.items():
        if len(shas) > 1:
            conflicts.append({"path_name": Path(path).name, "recorded_sha256": sorted(shas),
                              "reason": "SAME_PATH_RECORDED_WITH_DIFFERENT_SHA"})
    recoverable = []
    for item in missing:
        for sha in item["recorded_sha256"]:
            if sha in importable or (existing is not None and existing.find_object(sha)):
                recoverable.append({"path_name": item["path_name"], "sha256": sha,
                                    "from": "OTHER_PRESENT_PATH_OR_LIBRARY_OBJECT"})
    new_objects = {sha: info for sha, info in importable.items() if existing is None or existing.find_object(sha) is None}
    status_counts: dict[str, int] = {}
    seen = set()
    for ref in refs:
        if ref["approved"]:
            continue
        key = (ref["project_id"], ref["category"], ref["asset_id"], ref["path"])
        if key not in seen:
            seen.add(key)
            status_counts[str(ref["status"])] = status_counts.get(str(ref["status"]), 0) + 1
    head = _headroom(root)
    need = int(sum(i["bytes"] for i in new_objects.values()) * HEADROOM_MARGIN)
    return {"references": len(refs), "unique_paths": len(sha_by_path),
            "unique_objects_present": len(importable), "unique_objects_new": len(new_objects),
            "unique_objects_already_in_library": len(importable) - len(new_objects),
            "bytes_unique_present": sum(i["bytes"] for i in importable.values()),
            "bytes_to_add": sum(i["bytes"] for i in new_objects.values()),
            "missing_files": len(missing), "missing_sample": missing[:20],
            "sha_conflicts": len(conflicts), "sha_conflict_sample": conflicts[:20],
            "recoverable_missing": len(recoverable),
            "unapproved_references": sum(status_counts.values()), "unapproved_by_status": status_counts,
            "disk": {**head, "required_with_margin_bytes": need,
                     "enough_space": head["free_bytes"] >= need, "shortfall_bytes": max(0, need - head["free_bytes"])},
            "_importable": importable, "_new": new_objects}


def run(root: str | Path, *, libraries: Iterable[str] = (), source_maps: Iterable[str] = (),
        harvest_statuses: Iterable[str] = (), apply: bool = False, limit: int | None = None) -> dict[str, Any]:
    root = Path(root)
    refs, rows = inventory_libraries(libraries)
    refs += inventory_source_maps(source_maps)
    refs += inventory_harvest_statuses(harvest_statuses)
    facts = analyse(root, refs)
    importable, new = facts.pop("_importable"), facts.pop("_new")
    report: dict[str, Any] = {"schema": "qingshan.studio_asset_migration_report.v1",
                              "mode": "APPLY" if apply else "PREVIEW", "status": "PREVIEW", **facts,
                              "asset_library_rows_with_images": len(rows),
                              "old_files_modified": 0, "old_files_deleted": 0,
                              "history_files_rewritten": 0,
                              "note": "old files are kept; clean-up is a separate, explicit decision"}
    if not apply:
        return report
    if not facts["disk"]["enough_space"]:
        report["status"] = "BLOCKED_INSUFFICIENT_DISK_SPACE"
        return report
    lib = core.Library(root)
    ingested, skipped_batch = 0, 0
    sha_origin: dict[str, dict[str, Any]] = {}
    for ref in refs:
        got = importable.get(ref.get("sha") or "")
        if got is not None and got["path"] == ref["path"]:
            sha_origin.setdefault(ref["sha"], {"kind": "LEGACY_IMPORT", "project_id": ref.get("project_id"),
                                               "source": ref["source"], "library_asset_id": ref.get("asset_id"),
                                               "task_key": ref.get("task_key"), "task_id": ref.get("task_id"),
                                               "episode": ref.get("episode")})
    batch = sorted(importable)
    if limit is not None:
        new_first = [s for s in batch if s in new][:limit]
        batch = new_first + [s for s in batch if s not in new]
        skipped_batch = max(0, len([s for s in new]) - len(new_first))
    for sha in batch:
        info = importable[sha]
        record = lib.ingest_file(info["path"], origin={k: v for k, v in sha_origin.get(sha, {}).items() if v})
        ingested += 1 if record["created"] else 0
    registered = bound = reused = 0
    binding_conflicts: list[str] = []
    for group in rows:
        if group["category"] not in REGISTER_CATEGORIES:
            for ref in group["refs"]:
                if ref.get("sha") in importable:
                    lib.add_legacy_entry(ref["sha"], ref["path"], project_id=group["project_id"], asset_id=None,
                                         version=None, artifact_id=None, source="LEGACY_LIBRARY_ROW_NOT_REGISTERED_CATEGORY")
            continue
        present = [r for r in group["refs"] if r.get("sha") in importable and importable[r["sha"]]["path"] == r["path"]
                   and lib.find_object(r["sha"]) is not None]
        usage_seen: set[tuple[str, str]] = set()
        artifacts = []
        for r in present:
            key = (r["usage"], r["sha"])
            if key not in usage_seen:
                usage_seen.add(key)
                artifacts.append({"usage": r["usage"], "sha256": r["sha"]})
        if not artifacts:
            continue
        result = lib.register_version(
            category=group["category"], label=str(group["label"]), artifacts=artifacts, tags=[group["category"]],
            origin={"kind": "LEGACY_IMPORT", "project_id": group["project_id"], "library_asset_id": group["asset_id"],
                    "legacy_artifacts_missing": len(group["refs"]) - len(present)})
        registered += 1 if result["created"] else 0
        reused += 0 if result["created"] else 1
        qa = group["qa_block"]
        ref = {"kind": "LEGACY_LIBRARY_ROW_LOCKED_QA_PASS",
               "sha256": qa.get("review_file_sha256") if core.is_sha256(qa.get("review_file_sha256"))
               else core.sha256_bytes(core.canonical({"status": group["status"], "qa": qa.get("status"),
                                                      "checks": qa.get("checks")}).encode("utf-8")),
               "label": "existing review conclusion carried over; no new review was made",
               "reviewer": qa.get("reviewer")}
        if group["approved"]:
            lib.set_review(result["asset_id"], result["version"], "APPROVED", ref, reviewer=qa.get("reviewer"),
                           note="LEGACY_IMPORT_PRESERVES_EXISTING_VERDICT")
        elif str(group["qa_status"] or "") == "FAIL" or "FAILED" in str(group["status"] or ""):
            lib.set_review(result["asset_id"], result["version"], "REJECTED", None, reviewer=qa.get("reviewer"),
                           note="LEGACY_IMPORT_PRESERVES_EXISTING_VERDICT")
        for r in present:
            lib.add_legacy_entry(r["sha"], r["path"], project_id=group["project_id"], asset_id=result["asset_id"],
                                 version=result["version"], artifact_id=None, source="LEGACY_IMPORT")
        if group["approved"] and group["project_id"]:
            try:
                lib.bind(group["project_id"], KIND_OF_CATEGORY[group["category"]], group["asset_id"],
                         result["asset_id"], result["version"], project_fields={"label": str(group["label"])})
                bound += 1
            except core.StudioError as exc:
                binding_conflicts.append(f"{group['asset_id']}:{exc.code}")
    for ref in refs:  # sources / harvest receipts that belong to no library row still get a compat entry
        if ref["source"] in {"CHARACTER_SOURCE_MAP", "HARVEST_RECEIPT"} and ref.get("sha") in importable \
                and importable[ref["sha"]]["path"] == ref["path"]:
            lib.add_legacy_entry(ref["sha"], ref["path"], project_id=ref.get("project_id"), asset_id=None,
                                 version=None, artifact_id=None, source=ref["source"])
    report.update({"status": "APPLIED", "objects_ingested_new": ingested, "versions_registered_new": registered,
                   "versions_already_present": reused, "bindings_written_or_confirmed": bound,
                   "binding_conflicts": binding_conflicts, "deferred_by_batch_limit": skipped_batch})
    return report
