#!/usr/bin/env python3
"""Materialize the E59-only runtime and reject cross-line path leakage.

This is an offline migration.  It copies already-authorized E59 assets from the
Qingshan source package and the existing Qingshan episode scope; it never calls
Giggle and never touches the night-border (NALU-YEWUJIANG) runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ENGINE = Path("/Users/rogerwu/nalu")
QINGSHAN = Path("/Users/rogerwu/qingshan_short_drama")
LEGACY_SCOPE = Path("/Users/rogerwu/nalu_runtime/runtime/series_scopes/qingshan_e59")
RUNTIME = Path("/Users/rogerwu/nalu_runtime_e59")
PREPRO = RUNTIME / "preproduction/E59"
SOURCE_PREPRO = QINGSHAN / "workflow/claude_writer_agent/production/e59_v4_sd2_20260915/preproduction"
LEGACY_WORK = ENGINE / "workflow/nalu/E59"
E59_WORK = RUNTIME / "workflow/nalu/E59"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def rewrite(value: Any, old_scope: str, new_scope: str) -> Any:
    if isinstance(value, str):
        # Normalize both the historical runtime and the accidental duplicated
        # dedicated-root spelling produced by an earlier bootstrap invocation.
        return (value.replace(old_scope, new_scope)
                     .replace("/Users/rogerwu/nalu_runtime_e59_e59", str(RUNTIME))
                     .replace("/Users/rogerwu/nalu/workflow/nalu/E59/identity",
                              str(E59_WORK / "identity")))
    if isinstance(value, list):
        return [rewrite(item, old_scope, new_scope) for item in value]
    if isinstance(value, dict):
        return {key: rewrite(item, old_scope, new_scope) for key, item in value.items()}
    return value


def migrate_registries() -> None:
    runtime = RUNTIME / "runtime"
    for name in (
        "asset_library.json", "character_registry.json", "entity_registry.json",
        "voice_registry.json", "voice_catalog.json", "voice_cast.json",
        "agentcut_voice_policy.json", "asset_library_seed.json",
    ):
        src = LEGACY_SCOPE / name
        if not src.is_file():
            raise SystemExit(f"E59_SCOPE_SOURCE_MISSING:{src}")
        data = json.loads(src.read_text(encoding="utf-8"))
        data = rewrite(data, str(LEGACY_SCOPE), str(runtime))
        # Keep the runtime self-describing after migration.
        if isinstance(data, dict):
            data.setdefault("project_id", "QINGSHAN-E59")
            data["episode_scope"] = "E59"
        (runtime / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # The scope contract uses the historical runtime key
    # ``character_asset_registry`` while the imported Qingshan file is named
    # ``character_registry``.  Keep both names as identical, E59-local copies.
    copy_file(runtime / "character_registry.json", runtime / "character_asset_registry.json")

    for folder in ("character_sources", "voice_refs"):
        src_dir = LEGACY_SCOPE / folder
        for src in src_dir.rglob("*"):
            if src.is_file():
                copy_file(src, runtime / folder / src.relative_to(src_dir))


def migrate_maps() -> list[str]:
    source_assets = SOURCE_PREPRO / "space_map_assets"
    target_assets = PREPRO / "space_map_assets"
    if not source_assets.is_dir():
        raise SystemExit(f"E59_SPACE_MAP_SOURCE_MISSING:{source_assets}")
    # E59's authored package is authoritative for its maps.  The inherited E52/E57
    # subspace references are copied from the same Qingshan artifact package.
    for src in source_assets.rglob("*"):
        if src.is_file():
            copy_file(src, target_assets / src.relative_to(source_assets))
    inherited = QINGSHAN / "artifacts/e57_v4/shot_maps_v1"
    for src in inherited.glob("*.png"):
        copy_file(src, target_assets / src.name)
    for subdir in ("places", "subspaces"):
        src_dir = inherited / subdir
        for src in src_dir.glob("*.png"):
            dst = target_assets / subdir / src.name
            if not dst.exists():
                copy_file(src, dst)

    gsm_src = SOURCE_PREPRO / "global_space_map.json"
    gsm = json.loads(gsm_src.read_text(encoding="utf-8"))
    missing: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("path"), str):
                old = node["path"]
                name = Path(old).name
                candidates = [target_assets / "places" / name, target_assets / "subspaces" / name, target_assets / name]
                # The authored E59 package renamed the Xiulou place image while
                # retaining the older GSM reference in the JSON contract.
                if name == "GSM-E59-YAZUO-EMBROIDERY-HOUSE-V1_V1.png":
                    candidates += sorted((target_assets / "places").glob("GSM-E59-*YAZUO*.png"))
                if name == "E57_EPISODE_GLOBAL_SPACE_MAP_V1.png":
                    candidates += [target_assets / name]
                found = next((p for p in candidates if p.is_file()), None)
                if found is None:
                    missing.append(name)
                else:
                    node["path"] = str(found)
                    if "sha256" in node:
                        node["sha256"] = sha256(found)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(gsm)
    (PREPRO / "global_space_map.json").write_text(json.dumps(gsm, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sorted(set(missing))


def migrate_legacy_state_plan() -> None:
    """Keep authored state-chain evidence inside the E59 runtime.

    It is semantic migration evidence only; it is never treated as a paid
    result or as a keyframe/video asset.
    """
    src = ENGINE / "workflow/nalu/E59/preproduction/E59_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    if not src.is_file():
        return
    dst = RUNTIME / "runtime/adapter/E59/E59_LEGACY_GROUPING_PLAN.json"
    copy_file(src, dst)


def migrate_identity_outputs() -> None:
    """Move existing E59 identity plates into the dedicated work root.

    The old keyframe manifests are intentionally not copied: they contain
    YEWUJIANG map bindings.  Only identity/prop/scene plate evidence is moved,
    with JSON references rewritten to the E59 runtime root.
    """
    src = LEGACY_WORK / "identity"
    dst = E59_WORK / "identity"
    if not src.is_dir():
        return
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        target = dst / item.relative_to(src)
        if item.suffix.lower() == ".json":
            data = json.loads(item.read_text(encoding="utf-8"))
            data = rewrite(data, str(LEGACY_WORK), str(E59_WORK))
            data = rewrite(data, "/Users/rogerwu/nalu_runtime", str(RUNTIME))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            copy_file(item, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    args = parser.parse_args()
    if args.runtime != RUNTIME:
        raise SystemExit("E59_RUNTIME_ROOT_IS_FIXED_TO_DEDICATED_PATH")
    migrate_registries()
    missing = migrate_maps()
    migrate_legacy_state_plan()
    migrate_identity_outputs()
    forbidden = ("/Users/rogerwu/nalu_runtime/", "/Users/rogerwu/nalu_runtime_e59_e59",
                 "NALU-YEWUJIANG", "YEWUJIANG")
    scanned = [RUNTIME / "runtime/series_scopes.json", RUNTIME / "runtime/entity_registry.json",
               RUNTIME / "runtime/asset_library.json", RUNTIME / "runtime/character_registry.json",
               RUNTIME / "runtime/voice_registry.json", PREPRO / "global_space_map.json"]
    leaks = []
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            # The scope config may name the historical default scope as a
            # negative boundary; no E59 registry, map, or output may do so.
            if token in text and path.name != "series_scopes.json":
                leaks.append(f"{path}:{token}")
    if leaks:
        raise SystemExit("E59_PATH_ISOLATION_FAILED\n" + "\n".join(leaks))
    report = {
        "schema": "qingshan.e59.runtime_migration.v1",
        "runtime_root": str(RUNTIME),
        "source_package": str(SOURCE_PREPRO),
        "legacy_scope_source": str(LEGACY_SCOPE),
        "paid_posts": 0,
        "missing_map_assets": missing,
        "status": "PASS" if not missing else "PASS_WITH_MISSING_AUTHORED_MAP_ASSETS",
    }
    out = RUNTIME / "adapter/E59/reports/E59_RUNTIME_MIGRATION_20260919.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
