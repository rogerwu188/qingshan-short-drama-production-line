#!/usr/bin/env python3
"""Compile and gate a durable, project-level production asset library."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_REQUIREMENTS = "ai_drama.production_asset_requirements.v1"
SCHEMA_LIBRARY = "ai_drama.production_asset_library.v1"
CATEGORIES = (
    "characters",
    "wardrobe",
    "scenes",
    "props",
    "voices",
    "accents",
    "music",
    "ambience",
    "sfx",
    "reference_materials",
)
PRIORITIES = {"SERIES_CORE", "EPISODE_REQUIRED", "OPTIONAL"}
SHA256_LENGTH = 64
CATEGORY_LOCK_FIELDS = {
    "characters": ("identity_lock",),
    "wardrobe": ("owner_character_id", "appearance_lock"),
    "scenes": ("spatial_topology",),
    "props": ("physical_function", "appearance_lock"),
    "voices": (
        "owner_character_id",
        "language",
        "accent_id",
        "provider_voice_id",
        "native_dialogue_eligible",
    ),
    "accents": ("locale", "pronunciation_profile"),
    "music": ("usage_scope", "musical_identity"),
    "ambience": ("scene_scope", "sound_field"),
    "sfx": ("physical_source", "sync_event"),
    "reference_materials": ("usage_scope",),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in text
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def requirement_errors(requirements: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if requirements.get("schema") != SCHEMA_REQUIREMENTS:
        errors.append("requirements_schema_mismatch")
    for field in ("project_id", "canonical_sha256", "series_bible_sha256"):
        if not requirements.get(field):
            errors.append(f"requirements_missing:{field}")
    for field in ("canonical_sha256", "series_bible_sha256"):
        if requirements.get(field) and not is_sha256(requirements[field]):
            errors.append(f"requirements_invalid_sha256:{field}")
    assets = requirements.get("assets")
    if not isinstance(assets, dict):
        return errors + ["requirements_assets_not_object"]
    seen: set[str] = set()
    for category in CATEGORIES:
        items = assets.get(category)
        if not isinstance(items, list):
            errors.append(f"requirements_category_not_array:{category}")
            continue
        for index, item in enumerate(items):
            prefix = f"requirements:{category}:{index}"
            if not isinstance(item, dict):
                errors.append(f"{prefix}:not_object")
                continue
            asset_id = str(item.get("asset_id", ""))
            if not asset_id:
                errors.append(f"{prefix}:missing_asset_id")
            elif asset_id in seen:
                errors.append(f"duplicate_asset_id:{asset_id}")
            else:
                seen.add(asset_id)
            if not str(item.get("label", "")).strip():
                errors.append(f"{prefix}:missing_label")
            if item.get("priority") not in PRIORITIES:
                errors.append(f"{prefix}:invalid_priority")
            if not isinstance(item.get("first_use_episode"), int):
                errors.append(f"{prefix}:invalid_first_use_episode")
            episode_list = item.get("required_in_episodes")
            if not isinstance(episode_list, list) or any(
                not isinstance(episode, int) or episode < 1
                for episode in episode_list
            ):
                errors.append(f"{prefix}:invalid_required_in_episodes")
            authority_refs = item.get("authority_refs")
            if not isinstance(authority_refs, list) or not authority_refs:
                errors.append(f"{prefix}:missing_authority_refs")
            else:
                for authority in authority_refs:
                    if not isinstance(authority, dict):
                        errors.append(f"{prefix}:invalid_authority_ref")
                        continue
                    if not authority.get("source_id") or not is_sha256(
                        authority.get("sha256")
                    ):
                        errors.append(f"{prefix}:invalid_authority_ref")
            if not isinstance(item.get("specification"), dict) or not item.get(
                "specification"
            ):
                errors.append(f"{prefix}:missing_specification")
    unknown = sorted(set(assets) - set(CATEGORIES))
    errors.extend(f"requirements_unknown_category:{item}" for item in unknown)
    return errors


def new_asset(category: str, requirement: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": requirement["asset_id"],
        "category": category,
        "label": requirement["label"],
        "status": "REQUIRED_UNCREATED",
        "version": 1,
        "priority": requirement["priority"],
        "first_use_episode": requirement["first_use_episode"],
        "required_in_episodes": sorted(set(requirement["required_in_episodes"])),
        "requirement_sha256": canonical_sha256(requirement),
        "authority_refs": deepcopy(requirement["authority_refs"]),
        "specification": deepcopy(requirement["specification"]),
        "lock": {},
        "artifacts": [],
        "provenance": [],
        "rights": {"status": "PENDING", "basis": ""},
        "qa": {"status": "PENDING", "checks": []},
        "supersedes": None,
        "history": [],
        "updated_at": utc_now(),
    }


def compile_library(
    requirements: dict[str, Any], existing: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    errors = requirement_errors(requirements)
    if errors:
        raise ValueError(";".join(errors))
    if existing is None:
        library: dict[str, Any] = {
            "schema": SCHEMA_LIBRARY,
            "project_id": requirements["project_id"],
            "canonical_sha256": requirements["canonical_sha256"],
            "series_bible_sha256": requirements["series_bible_sha256"],
            "library_version": 1,
            "updated_at": utc_now(),
            "assets": {category: {} for category in CATEGORIES},
        }
    else:
        library = deepcopy(existing)
        if library.get("schema") != SCHEMA_LIBRARY:
            raise ValueError("existing_library_schema_mismatch")
        if library.get("project_id") != requirements.get("project_id"):
            raise ValueError("existing_library_project_mismatch")
        library["library_version"] = int(library.get("library_version", 0)) + 1
        library["updated_at"] = utc_now()
        library.setdefault("assets", {})
        for category in CATEGORIES:
            library["assets"].setdefault(category, {})

    summary = {
        "created": [],
        "reused_locked": [],
        "needs_revalidation": [],
        "retained_history": [],
    }
    required_ids: set[str] = set()
    for category in CATEGORIES:
        category_assets = library["assets"][category]
        for requirement in requirements["assets"][category]:
            asset_id = requirement["asset_id"]
            required_ids.add(asset_id)
            requirement_sha = canonical_sha256(requirement)
            current = category_assets.get(asset_id)
            if current is None:
                category_assets[asset_id] = new_asset(category, requirement)
                summary["created"].append(asset_id)
                continue
            if current.get("category") != category:
                raise ValueError(f"asset_category_mismatch:{asset_id}")
            current.setdefault("history", [])
            if current.get("requirement_sha256") == requirement_sha:
                if current.get("status") == "LOCKED":
                    summary["reused_locked"].append(asset_id)
                continue
            previous_version = int(current.get("version", 0))
            current.setdefault("history", []).append(
                {
                    "version": previous_version,
                    "status": current.get("status"),
                    "requirement_sha256": current.get("requirement_sha256"),
                    "specification": deepcopy(current.get("specification") or {}),
                    "lock": deepcopy(current.get("lock") or {}),
                    "artifacts": deepcopy(current.get("artifacts") or []),
                    "provenance": deepcopy(current.get("provenance") or []),
                    "rights": deepcopy(current.get("rights") or {}),
                    "qa": deepcopy(current.get("qa") or {}),
                    "archived_at": utc_now(),
                }
            )
            current["supersedes"] = f"{asset_id}@v{previous_version}"
            current["version"] = previous_version + 1
            current["status"] = "NEEDS_REVALIDATION"
            current["requirement_sha256"] = requirement_sha
            current["priority"] = requirement["priority"]
            current["first_use_episode"] = requirement["first_use_episode"]
            current["required_in_episodes"] = sorted(
                set(requirement["required_in_episodes"])
            )
            current["authority_refs"] = deepcopy(requirement["authority_refs"])
            current["specification"] = deepcopy(requirement["specification"])
            current["qa"] = {"status": "PENDING", "checks": []}
            current["updated_at"] = utc_now()
            summary["needs_revalidation"].append(asset_id)

    for category in CATEGORIES:
        for asset_id in library["assets"][category]:
            if asset_id not in required_ids:
                summary["retained_history"].append(asset_id)

    library["canonical_sha256"] = requirements["canonical_sha256"]
    library["series_bible_sha256"] = requirements["series_bible_sha256"]
    summary["status"] = "COMPILED"
    summary["library_version"] = library["library_version"]
    summary["requirement_count"] = len(required_ids)
    return library, summary


def episode_number(value: int | str) -> int:
    if isinstance(value, int):
        if value < 1:
            raise ValueError("episode_must_be_positive")
        return value
    match = re.fullmatch(r"(?:EP|E)?0*([1-9][0-9]*)", str(value).strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"invalid_episode:{value}")
    return int(match.group(1))


def selected_for_episode(asset: dict[str, Any], episode: int | str) -> bool:
    episode = episode_number(episode)
    if asset.get("priority") == "SERIES_CORE":
        return True
    return episode in set(asset.get("required_in_episodes") or [])


def artifact_errors(asset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artifacts = asset.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return ["artifacts_missing"]
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            errors.append(f"artifact_{index}_invalid")
            continue
        if not artifact.get("role") or not artifact.get("media_type"):
            errors.append(f"artifact_{index}_identity_missing")
        if not artifact.get("path") and not artifact.get("provider_asset_id"):
            errors.append(f"artifact_{index}_location_missing")
        if not is_sha256(artifact.get("sha256")):
            errors.append(f"artifact_{index}_sha256_invalid")
    return errors


def gate_asset(category: str, asset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if asset.get("status") != "LOCKED":
        errors.append(f"status_not_locked:{asset.get('status')}")
    if not is_sha256(asset.get("requirement_sha256")):
        errors.append("requirement_sha256_invalid")
    lock = asset.get("lock")
    if not isinstance(lock, dict):
        errors.append("lock_not_object")
    else:
        for field in CATEGORY_LOCK_FIELDS[category]:
            if lock.get(field) in (None, "", [], {}, False):
                errors.append(f"lock_missing:{field}")
    if category == "voices" and (asset.get("lock") or {}).get("language") != "zh-CN":
        errors.append("voice_language_not_zh-CN")
    errors.extend(artifact_errors(asset))
    provenance = asset.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        errors.append("provenance_missing")
    rights = asset.get("rights") or {}
    if rights.get("status") != "PASS" or not str(rights.get("basis", "")).strip():
        errors.append("rights_not_pass")
    qa = asset.get("qa") or {}
    if qa.get("status") != "PASS" or not qa.get("checks"):
        errors.append("qa_not_pass")
    return errors


def gate_library(
    library: dict[str, Any], requirements: dict[str, Any], episode: int | str
) -> dict[str, Any]:
    episode = episode_number(episode)
    failures: list[dict[str, Any]] = []
    if library.get("schema") != SCHEMA_LIBRARY:
        failures.append({"asset_id": None, "errors": ["library_schema_mismatch"]})
    for field in ("project_id", "canonical_sha256", "series_bible_sha256"):
        if library.get(field) != requirements.get(field):
            failures.append(
                {"asset_id": None, "errors": [f"library_authority_mismatch:{field}"]}
            )
    library_assets = library.get("assets") or {}
    checked = 0
    for category in CATEGORIES:
        by_id = library_assets.get(category) or {}
        for requirement in requirements.get("assets", {}).get(category, []):
            candidate = by_id.get(requirement.get("asset_id"))
            expected = new_asset(category, requirement)
            if not selected_for_episode(expected, episode):
                continue
            checked += 1
            asset_id = requirement["asset_id"]
            if candidate is None:
                failures.append(
                    {"category": category, "asset_id": asset_id, "errors": ["missing"]}
                )
                continue
            errors = gate_asset(category, candidate)
            if candidate.get("requirement_sha256") != canonical_sha256(requirement):
                errors.append("requirement_changed")
            if errors:
                failures.append(
                    {"category": category, "asset_id": asset_id, "errors": errors}
                )
    return {
        "schema": "ai_drama.production_asset_library_gate.v1",
        "project_id": requirements.get("project_id"),
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "checked_asset_count": checked,
        "failure_count": len(failures),
        "failures": failures,
        "completed_at": utc_now(),
    }


def command_compile(args: argparse.Namespace) -> int:
    requirements_path = Path(args.requirements).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    requirements = load_json(requirements_path)
    existing = load_json(out_path) if out_path.is_file() else None
    try:
        library, summary = compile_library(requirements, existing)
    except ValueError as exc:
        print(json.dumps({"status": "FAIL", "errors": str(exc).split(";")}, indent=2))
        return 2
    atomic_write_json(out_path, library)
    if args.report:
        atomic_write_json(Path(args.report).expanduser().resolve(), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_gate(args: argparse.Namespace) -> int:
    requirements = load_json(Path(args.requirements).expanduser().resolve())
    errors = requirement_errors(requirements)
    if errors:
        report = {"status": "FAIL", "failures": errors}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    library = load_json(Path(args.library).expanduser().resolve())
    report = gate_library(library, requirements, args.episode)
    if args.report:
        atomic_write_json(Path(args.report).expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile and gate the initial reusable production asset library."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--requirements", required=True)
    compile_parser.add_argument("--out", required=True)
    compile_parser.add_argument("--report")
    compile_parser.set_defaults(handler=command_compile)
    gate_parser = subparsers.add_parser("gate")
    gate_parser.add_argument("--requirements", required=True)
    gate_parser.add_argument("--library", required=True)
    gate_parser.add_argument("--episode", required=True)
    gate_parser.add_argument("--report", "--out", dest="report")
    gate_parser.set_defaults(handler=command_gate)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
