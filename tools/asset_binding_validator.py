#!/usr/bin/env python3
"""
Pre-generation asset binding validator for Qingshan short-drama episodes.

This is a source-gate, not a post-review tool. It verifies that every shot has
explicit reusable anchors for characters, scenes, props, voices, ambience, and
music before any Giggle/AI Director video generation starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_file(path_value: str) -> bool:
    return bool(path_value) and Path(path_value).expanduser().exists()


def anchor_has_source(anchor: Dict[str, Any]) -> bool:
    for key in ("reference_image", "body_reference", "library_file", "text_asset"):
        value = anchor.get(key)
        if value and existing_file(str(value)):
            return True
    return bool(anchor.get("platform_material_card") or anchor.get("library_id"))


def normalized_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def sha256_file(path_value: str) -> str:
    digest = hashlib.sha256()
    with normalized_path(path_value).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_declared_sha(
    *,
    label: str,
    path_value: Any,
    expected_sha256: Any,
    errors: List[str],
) -> None:
    if not expected_sha256:
        return
    if not path_value or not existing_file(str(path_value)):
        errors.append(f"{label} path is missing for declared SHA")
        return
    actual = sha256_file(str(path_value))
    if actual != str(expected_sha256):
        errors.append(f"{label} SHA mismatch: expected {expected_sha256}, got {actual}")


def validate_state_bible_wardrobe_selection(
    config: Dict[str, Any], manifest: Dict[str, Any], errors: List[str]
) -> None:
    """Keep an episode State Bible selection identical to its production binding."""
    for char_id, state in (config.get("character_state") or {}).items():
        wardrobe_variant_id = state.get("wardrobe_variant_id")
        if not wardrobe_variant_id:
            continue
        anchor = (manifest.get("characters") or {}).get(char_id)
        if not anchor:
            errors.append(
                f"State Bible wardrobe selection lacks production character binding: "
                f"{char_id}/{wardrobe_variant_id}"
            )
            continue
        bound_variant_id = anchor.get("wardrobe_variant_id")
        if bound_variant_id != wardrobe_variant_id:
            errors.append(
                f"State Bible wardrobe variant does not match production binding: "
                f"{char_id}/{wardrobe_variant_id} != {bound_variant_id or 'MISSING'}"
            )
        state_ref = state.get("wardrobe_reference_image")
        bound_ref = anchor.get("reference_image")
        if state_ref and bound_ref and normalized_path(str(state_ref)) != normalized_path(str(bound_ref)):
            errors.append(
                f"State Bible wardrobe reference does not match production binding: "
                f"{char_id}/{wardrobe_variant_id}"
            )


def validate_historical_inheritance(manifest: Dict[str, Any], errors: List[str]) -> None:
    if not manifest.get("historical_asset_inheritance_required"):
        return
    registry_value = manifest.get("series_character_registry")
    if not registry_value or not existing_file(str(registry_value)):
        errors.append("historical inheritance registry is required and must exist")
        return
    registry = load_json(normalized_path(str(registry_value)))
    historical = registry.get("characters") or (registry.get("assets") or {}).get("characters") or {}
    for char_id, anchor in (manifest.get("characters") or {}).items():
        history_status = anchor.get("history_status")
        if history_status not in ("RETURNING", "NEW", "BACKGROUND_GROUP"):
            errors.append(f"character must declare history_status: {char_id}")
            continue
        registered = historical.get(char_id)
        if history_status == "BACKGROUND_GROUP":
            continue
        if history_status == "NEW":
            if registered and str(registered.get("status", "")).startswith("LOCKED"):
                errors.append(f"registered returning character cannot be declared NEW: {char_id}")
            continue
        if not registered:
            errors.append(f"returning character missing from series registry: {char_id}")
            continue
        canonical_identity = registered.get("identity_reference_image") or registered.get("reference_image")
        current_identity = anchor.get("identity_reference_image") or anchor.get("reference_image")
        if canonical_identity:
            if not current_identity:
                errors.append(f"returning character missing inherited identity reference: {char_id}")
            elif normalized_path(str(current_identity)) != normalized_path(str(canonical_identity)):
                errors.append(f"returning character identity drift/change-face detected: {char_id}")

        wardrobe_variant_id = anchor.get("wardrobe_variant_id")
        wardrobe_variant_required = bool(
            anchor.get("wardrobe_variant_required")
            or anchor.get("wardrobe_reference_image")
        )
        registered_variants = registered.get("wardrobe_variants") or registered.get("variants") or {}
        if wardrobe_variant_required and not wardrobe_variant_id:
            errors.append(f"returning character requires registered wardrobe variant: {char_id}")
        if wardrobe_variant_id:
            variant = registered_variants.get(wardrobe_variant_id)
            if not variant:
                errors.append(f"wardrobe variant is not registered for returning character: {char_id}/{wardrobe_variant_id}")
            else:
                variant_ref = variant.get("reference_image")
                current_ref = anchor.get("reference_image")
                if variant.get("identity_verification") != "PASS":
                    errors.append(f"wardrobe variant lacks same-face/same-body PASS: {char_id}/{wardrobe_variant_id}")
                if variant.get("verification_status") != "PASS":
                    errors.append(f"wardrobe variant is not production verified: {char_id}/{wardrobe_variant_id}")
                if not variant_ref or not existing_file(str(variant_ref)):
                    errors.append(f"wardrobe variant reference is missing: {char_id}/{wardrobe_variant_id}")
                if variant_ref and current_ref and normalized_path(str(current_ref)) != normalized_path(str(variant_ref)):
                    errors.append(f"episode reference does not match registered wardrobe variant: {char_id}/{wardrobe_variant_id}")
                validate_declared_sha(
                    label=f"wardrobe variant {char_id}/{wardrobe_variant_id}",
                    path_value=variant_ref,
                    expected_sha256=variant.get("reference_sha256"),
                    errors=errors,
                )
                validate_declared_sha(
                    label=f"wardrobe asset manifest {char_id}/{wardrobe_variant_id}",
                    path_value=variant.get("asset_manifest"),
                    expected_sha256=variant.get("asset_manifest_sha256"),
                    errors=errors,
                )
                validate_declared_sha(
                    label=f"wardrobe identity parent {char_id}/{wardrobe_variant_id}",
                    path_value=variant.get("identity_parent_reference_image"),
                    expected_sha256=variant.get("identity_parent_sha256"),
                    errors=errors,
                )
                validate_declared_sha(
                    label=f"wardrobe identity QA report {char_id}/{wardrobe_variant_id}",
                    path_value=variant.get("identity_qa_report"),
                    expected_sha256=variant.get("identity_qa_report_sha256"),
                    errors=errors,
                )

        for field in ("body_reference",):
            canonical = registered.get(field)
            if not canonical:
                continue
            current = anchor.get(field)
            if not current:
                errors.append(f"returning character missing inherited {field}: {char_id}")
                continue
            if normalized_path(str(current)) != normalized_path(str(canonical)):
                if not anchor.get("approved_asset_upgrade"):
                    errors.append(f"returning character changed canonical {field} without approved upgrade: {char_id}")
                elif not anchor.get("upgrade_reason") or not anchor.get("supersedes_reference"):
                    errors.append(f"approved asset upgrade lacks reason/superseded reference: {char_id}")
        canonical_voice = registered.get("voice_asset_id")
        if canonical_voice and anchor.get("voice_asset_id") != canonical_voice:
            errors.append(f"returning character voice asset drift: {char_id}")


def validate_entity_inheritance(manifest: Dict[str, Any], errors: List[str]) -> None:
    """Validate portable scene/prop identity plus approved angle/state variants."""
    if not manifest.get("historical_scene_prop_inheritance_required"):
        return
    registry_value = manifest.get("series_continuity_registry")
    if not registry_value or not existing_file(str(registry_value)):
        errors.append("scene/prop continuity registry is required and must exist")
        return
    registry = load_json(normalized_path(str(registry_value)))
    assets = registry.get("assets") or {}
    for collection_name in ("scenes", "props"):
        registered_assets = assets.get(collection_name) or {}
        for asset_id, anchor in (manifest.get(collection_name) or {}).items():
            history_status = anchor.get("history_status")
            if history_status not in ("RETURNING", "NEW"):
                errors.append(f"{collection_name} asset must declare history_status: {asset_id}")
                continue
            registered = registered_assets.get(asset_id)
            if history_status == "NEW":
                if registered and registered.get("status") == "LOCKED_RETURNING":
                    errors.append(f"registered returning {collection_name} asset cannot be declared NEW: {asset_id}")
                continue
            if not registered:
                errors.append(f"returning {collection_name} asset missing from continuity registry: {asset_id}")
                continue
            if registered.get("status") == "RETIRED":
                errors.append(f"returning {collection_name} asset is retired: {asset_id}")
            variant_ids = anchor.get("variant_ids_used") or []
            if isinstance(variant_ids, str):
                variant_ids = [variant_ids]
            if not variant_ids:
                errors.append(f"returning {collection_name} asset must select registered variant: {asset_id}")
                continue
            registered_variants = registered.get("variants") or {}
            for variant_id in variant_ids:
                variant = registered_variants.get(variant_id)
                if not variant:
                    errors.append(f"unregistered {collection_name} variant: {asset_id}/{variant_id}")
                    continue
                if variant.get("verification_status") == "FAIL":
                    errors.append(f"{collection_name} variant is not QA locked: {asset_id}/{variant_id}")
                ref = variant.get("reference_image")
                if not ref or not existing_file(str(ref)):
                    errors.append(f"{collection_name} variant lacks reusable reference image: {asset_id}/{variant_id}")


def build_errors(config: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    characters = manifest.get("characters") or {}
    scenes = manifest.get("scenes") or {}
    props = manifest.get("props") or {}
    voices = manifest.get("voices") or {}
    ambience = manifest.get("ambience") or {}
    music = manifest.get("music") or {}
    shot_overrides = manifest.get("shot_bindings") or {}
    default_music = manifest.get("episode_music")

    validate_historical_inheritance(manifest, errors)
    validate_entity_inheritance(manifest, errors)
    validate_state_bible_wardrobe_selection(config, manifest, errors)

    for char_id, anchor in characters.items():
        if not anchor_has_source(anchor):
            errors.append(f"character anchor missing reusable source: {char_id}")
        if anchor.get("level") in ("S", "A", "A+") and not anchor.get("upload_required"):
            errors.append(f"S/A character must require upload/binding before video generation: {char_id}")

    for scene_id, anchor in scenes.items():
        if not anchor_has_source(anchor):
            errors.append(f"scene anchor missing reusable source: {scene_id}")
    for prop_id, anchor in props.items():
        if not anchor_has_source(anchor):
            errors.append(f"prop anchor missing reusable source: {prop_id}")

    for idx, shot in enumerate(config.get("shots") or []):
        shot_id = str(shot.get("shot_id") or shot.get("id") or f"{idx + 1:02d}")
        overrides = shot_overrides.get(shot_id) or {}

        for char_id in shot.get("characters") or []:
            anchor = characters.get(char_id)
            if not anchor:
                errors.append(f"shot {shot_id}: missing character binding for {char_id}")
                continue
            if anchor.get("level") in ("S", "A", "A+"):
                required_slot = anchor.get("required_upload_slot")
                uploaded = (overrides.get("characters") or {}).get(char_id, {})
                if not required_slot:
                    errors.append(f"shot {shot_id}: {char_id} has no required upload slot")
                if not uploaded.get("slot"):
                    errors.append(f"shot {shot_id}: {char_id} must be explicitly uploaded/bound in video modal")

        scene_id = shot.get("scene_id")
        room_id = shot.get("room_id")
        zone_id = shot.get("zone_id")
        if scene_id and scene_id not in scenes:
            errors.append(f"shot {shot_id}: missing scene binding for {scene_id}")
        if room_id and room_id not in scenes:
            errors.append(f"shot {shot_id}: missing room binding for {room_id}")
        if zone_id and zone_id not in scenes:
            errors.append(f"shot {shot_id}: missing zone binding for {zone_id}")

        for prop_id in shot.get("props") or []:
            if prop_id not in props:
                errors.append(f"shot {shot_id}: missing prop binding for {prop_id}")

        for char_id in shot.get("characters") or []:
            voice_id = (characters.get(char_id) or {}).get("voice_id")
            if voice_id and voice_id not in voices:
                errors.append(f"shot {shot_id}: missing voice binding {voice_id} for {char_id}")

        amb_id = (overrides.get("audio") or {}).get("ambience") or manifest.get("default_ambience")
        if amb_id and amb_id not in ambience:
            errors.append(f"shot {shot_id}: missing ambience binding {amb_id}")
        if default_music and default_music not in music:
            errors.append(f"shot {shot_id}: missing episode music binding {default_music}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate reusable asset bindings before video generation.")
    parser.add_argument("--config", required=True, help="Episode continuity config JSON.")
    parser.add_argument("--manifest", required=True, help="Episode asset binding manifest JSON.")
    parser.add_argument("--out", help="Optional JSON report path.")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    config = load_json(config_path)
    manifest = load_json(manifest_path)
    errors = build_errors(config, manifest)
    report = {
        "episode": config.get("episode") or manifest.get("episode"),
        "config": str(config_path),
        "manifest": str(manifest_path),
        "status": "PASS" if not errors else "FAIL",
        "error_count": len(errors),
        "errors": errors,
    }
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
