#!/usr/bin/env python3
"""Compile the Giggle IMAGE manifest for one episode's per-shot keyframes.

This tool is generic over episodes.  It reads only locked stage-1/stage-2
preproduction artefacts plus the project asset library, applies the
`SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE` keyframe policy
(`tools/production_efficiency_contract.py`), and emits a manifest in the exact
schema `tools/submit_giggle_image_manifest.py` consumes.

Discipline enforced here (never relaxed):

* A keyframe represents ``entry_state`` only.  ``completion_state`` is stripped
  from ``source_shot_contract`` before it is written, is never rendered into a
  prompt, and the extend-words 持续/保持/连续 are rejected anywhere in the
  compiled prompt (`tools/keyframe_entry_state_gate.py`).
* ``resolution_order`` is written verbatim as
  ``["EPISODE_GLOBAL_SPACE_MAP","GLOBAL_SPACE_MAP","SHOT_SUBSPACE_LAYOUT","CHARACTER_PROP_BLOCKING"]``
  and ``reference_bindings`` are ordered
  episode map -> place map -> subspace -> scene -> character -> prop
  (`tools/global_space_layout_gate.py`).
* ``global_space_map_gate_required`` is always ``true`` for a shot-keyframe
  batch.
* Nothing is fabricated.  An identity/prop plate that does not exist yet is
  written as a PENDING binding with the exact awaited file path, and the report
  lists what is awaited per task.  Precheck then FAILS on those tasks, which is
  the honest state of the pipeline, not a tool bug.

The tool never POSTs.  It can invoke the submitter's ``--precheck-only`` mode,
which the submitter runs before its own API-key guard, so no key is needed and
no credit can be spent.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from role_semantic_prompt_gate import role_semantic_prompt_block
    from image_model_adapter import compile_labeled_flat_identity_transport
    from provider_scope_projection import build_provider_scope_projection
except ModuleNotFoundError:  # Imported as a package in tests
    from tools.role_semantic_prompt_gate import role_semantic_prompt_block
    from tools.image_model_adapter import compile_labeled_flat_identity_transport
    from tools.provider_scope_projection import build_provider_scope_projection

SCHEMA_MANIFEST = "qingshan.giggle_image_batch_manifest.v2"
SCHEMA_REPORT = "nalu.keyframe_manifest_build_report.v1"
RESOLUTION_ORDER = [
    "EPISODE_GLOBAL_SPACE_MAP",
    "GLOBAL_SPACE_MAP",
    "SHOT_SUBSPACE_LAYOUT",
    "CHARACTER_PROP_BLOCKING",
]
#: Roger 2026-09-18 (identity chain ②): the FACE reference leads the sequence — the front neutral
#: headshot plate is the only plate whose face is large enough to lock identity (a 1440x2560 full
#: body plate gives the model a ~150 px face).  The full-body plate follows as a wardrobe reference.
#: The engine's SCENE-AUTHORITY-LOCK gate (global_space_layout_gate.py:409-416) pins episode map < place map <
#: subspace layout and refuses any character/prop binding BEFORE the subspace layout, so the face plate takes
#: the first position the gate allows: 4th, ahead of the scene plate, the full-body plate and every prop.
BINDING_ROLE_ORDER = [
    "episode_global_space_map",
    "global_space_map",
    "subspace_layout",
    "character",
    "scene",
    "character_wardrobe",
    "prop",
]
CHARACTER_FACE_VIEW = "FRONT_NEUTRAL_HEADSHOT"
CHARACTER_WARDROBE_VIEW = "FULL_BODY_STANDING"
#: Roger 2026-09-18 (②): space maps + scene + props together <= 5 so the face signal is not diluted;
#: dropped in this order until the cap holds.  Total references <= 9 (provider limit).
NON_CHARACTER_REFERENCE_MAX = 5
#: The engine's SCENE-AUTHORITY-LOCK gate (global_space_layout_gate) demands exactly one episode map, one place
#: map and one subspace layout per task, so only props can be dropped to hold the cap (E06 precheck, 2026-09-18).
NON_CHARACTER_DROP_ORDER: list[str] = []   # nothing is dropped (see cap_non_character_bindings)
REFERENCE_TOTAL_MAX = 9
FORBIDDEN_EXTEND_WORDS = ("持续", "保持", "连续")
NOVELTY_CLASSES = (
    "NEW_CHARACTER_IDENTITY",
    "NEW_LOCATION_OR_SUBSPACE",
    "NEW_WARDROBE_STATE",
    "NON_INTERPOLABLE_PROP_OR_BODY_STATE",
    "TRANSITION_CRITICAL_TERMINAL_STATE",
    "ENTRY_STATE_DIFFERS_FROM_SETUP_OWNER",
)
# POSSESSION / CONTACT / INTEGRITY entry codes describe who holds what, what
# touches what, and whether an object is whole.  None of those can be reached by
# interpolating a reused still, so an entry state carrying them is by definition
# not interpolable from another shot's keyframe.
NON_INTERPOLABLE_DIMENSIONS = {"POSSESSION", "CONTACT", "INTEGRITY"}
PENDING_SHA_SENTINEL = "PENDING_SHA256_UNTIL_IDENTITY_CARD_EXISTS"
DEFAULT_ENGINE_ROOT = Path(f"{_np.ENGINE_ROOT}")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=f".{path.name}.", suffix=".part", delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def awaited_identity_path(awaited_asset_dir: Path, category: str, asset_id: str) -> str:
    """Return the deterministic stage-3(a) awaited artifact path.

    Pending bindings must name the exact JSON registration file that the
    identity/asset-library stage is expected to create; they are not media
    placeholders and must remain unresolved until a real locked artifact is
    registered.
    """
    return str((awaited_asset_dir / category / f"{asset_id}.json").resolve())


def engine_relative(path: Path, engine_root: Path) -> str:
    """Return an engine-relative path when possible.

    The engine's gates and the submitter resolve relative paths against the
    engine repository root, and the space-map authority stores its media that
    way.  Bindings must reproduce those strings byte for byte.
    """
    try:
        return str(path.resolve().relative_to(engine_root.resolve()))
    except ValueError:
        return str(path.resolve())


def episode_ordinal(value: str) -> int | None:
    match = re.match(r"E(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else None


def stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def join(values: list[str] | None, separator: str = "、", empty: str = "无") -> str:
    rows = [str(value).strip() for value in (values or []) if str(value).strip()]
    return separator.join(rows) if rows else empty


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #

class Inputs:
    """Locked preproduction artefacts for one episode."""

    def __init__(self, episode: str, preproduction_dir: Path, contract_path: Path,
                 asset_library_path: Path, engine_root: Path,
                 awaited_asset_dir: Path | None = None) -> None:
        self.episode = episode
        self.dir = preproduction_dir
        self.engine_root = engine_root
        self.contract_path = contract_path
        self.contract = load_json(contract_path)
        self.contract_sha256 = sha256_file(contract_path)
        self.asset_library_path = asset_library_path
        self.asset_library = load_json(asset_library_path)
        # Where stage 3(a) is expected to write the plates this batch is waiting
        # for.  Explicit, so a library compiled into a reports/ folder does not
        # silently relocate the awaited paths.
        self.awaited_asset_dir = (awaited_asset_dir or (asset_library_path.parent / "asset_library")).resolve()

        self.subspace_plan_path = self._require(f"{episode}_SUBSPACE_SHOT_PLAN_LOCKED_V1.json")
        self.authority_path = self._require(
            f"{episode}_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
        )
        self.seedance_path = self._require(f"{episode}_EDITORIAL_SEEDANCE_MANIFEST_V1.json")
        self.anchor_plan_path = self._require(f"{episode}_VIDEO_UNIT_ANCHOR_PLAN_V1.json")
        self.grouping_plan_path = self._require(f"{episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json")
        self.gate_bundle_path = self._require(f"{episode}_MACHINE_GATE_REPORTS_V1.json")

        self.subspace_plan = load_json(self.subspace_plan_path)
        self.authority = load_json(self.authority_path)
        self.seedance = load_json(self.seedance_path)
        self.anchor_plan = load_json(self.anchor_plan_path)
        self.grouping_plan = load_json(self.grouping_plan_path)
        self.gate_bundle = load_json(self.gate_bundle_path)

        self.visual_culture = self.contract.get("visual_culture_contract") or {}
        # v4 adapters encode the authored visual-culture lock by the complete
        # profile fields and do not repeat a redundant ``status`` key.  Accept
        # that canonical shape while still requiring every lock-bearing field;
        # incomplete/ambiguous contracts remain blocked.
        visual_v4_complete = all(self.visual_culture.get(key) for key in (
            "profile_id", "production_design", "forbidden_influences",
            "palette_system", "story_world", "image_texture",
        ))
        if self.visual_culture.get("status") != "LOCKED" and not visual_v4_complete:
            raise ValueError("visual_culture_contract is not LOCKED; refusing to compile prompts")
        if self.authority.get("status") != "LOCKED":
            raise ValueError("episode global space map authority is not LOCKED")

        self.shots: dict[str, dict[str, Any]] = {
            str(row["shot_id"]): row for row in self.seedance.get("shots") or []
        }
        self.subspace_tasks: dict[str, dict[str, Any]] = {
            str(row["unit_id"]): row for row in self.subspace_plan.get("tasks") or []
        }
        self.wardrobe_bible = self.seedance.get("wardrobe_bible") or {}
        self.wardrobe_by_character: dict[str, dict[str, Any]] = {
            str(row.get("character_id")): row
            for row in self.wardrobe_bible.get("characters") or []
            if row.get("character_id")
        }
        self.unit_by_shot: dict[str, dict[str, Any]] = {}
        for unit in self.grouping_plan.get("units") or []:
            for shot_id in unit.get("editorial_shot_ids") or []:
                self.unit_by_shot[str(shot_id)] = unit
        self.anchor_unit_by_shot: dict[str, dict[str, Any]] = {}
        for unit in self.anchor_plan.get("units") or []:
            keys = unit.get("reference_image_task_keys") or []
            if keys:
                self.anchor_unit_by_shot[str(keys[0])] = unit
        self.planned_anchor_shots: list[str] = [
            name.replace("-keyframe-v1.png", "")
            for name in self.anchor_plan.get("expected_keyframe_filenames_for_planned_anchors") or []
        ]
        self.place_maps: dict[str, dict[str, Any]] = {
            str(row.get("global_space_map_id")): row
            for row in self.authority.get("space_maps") or []
        }

    def _require(self, name: str) -> Path:
        path = self.dir / name
        if not path.is_file():
            raise FileNotFoundError(f"required preproduction artefact is missing: {path}")
        return path

    def gate_report_refs(self) -> list[str]:
        rows: list[str] = []
        for row in self.gate_bundle.get("reports") or []:
            value = str(row.get("path") or "")
            if not value:
                continue
            path = Path(value)
            resolved = path if path.is_absolute() else self.engine_root / path
            if not resolved.is_file():
                raise FileNotFoundError(f"machine gate report is missing: {resolved}")
            report = load_json(resolved)
            if report.get("status") != "PASS":
                raise ValueError(f"machine gate report is not PASS: {resolved}")
            rows.append(value)
        if not rows:
            raise ValueError("no PASS machine gate reports available for this batch")
        return rows

    def scene_authority_gate_ref(self) -> str:
        for row in self.gate_bundle.get("reports") or []:
            if row.get("gate_id") == "SCENE-AUTHORITY-LOCK":
                return str(row.get("path"))
        raise ValueError("SCENE-AUTHORITY-LOCK report is not registered in the gate bundle")


# --------------------------------------------------------------------------- #
# keyframe decision (semantic-novelty policy)
# --------------------------------------------------------------------------- #

def camera_setup_key(shot: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(shot.get("global_space_map_id")),
        str(shot.get("room_id")),
        str(shot.get("zone_id")),
        str(shot.get("angle_id")),
    )


def decide_keyframes(inputs: Inputs) -> list[dict[str, Any]]:
    """Return one decision row per editorial shot, in shot order.

    Policy source: production_efficiency_contract.keyframe_policy
    (`SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE`,
    `one_keyframe_per_editorial_shot_forbidden: true`).  A shot only earns a new
    paid image when it introduces at least one of the five declared novelty
    classes.  Everything else reuses admitted bytes.
    """
    planned = set(inputs.planned_anchor_shots)
    seen_characters: set[str] = set()
    seen_wardrobe: set[str] = set()
    setup_owner: dict[tuple[str, str, str, str], str] = {}
    setup_owner_signature: dict[str, tuple[str, tuple[str, ...]]] = {}
    rows: list[dict[str, Any]] = []

    for shot_id, shot in inputs.shots.items():
        spec = shot.get("prompt_spec") or {}
        unit = inputs.unit_by_shot.get(shot_id) or {}
        anchor_unit = inputs.anchor_unit_by_shot.get(shot_id)
        cast_ids = [str(row.get("character_id")) for row in spec.get("cast") or [] if row.get("character_id")]
        prop_ids = [str(row.get("prop_id")) for row in spec.get("props") or [] if row.get("prop_id")]
        wardrobe_keys = [
            str((inputs.wardrobe_by_character.get(cid) or {}).get("continuity_key") or f"WARDROBE-UNDECLARED:{cid}")
            for cid in cast_ids
        ]
        setup = camera_setup_key(shot)
        dimensions = list((spec.get("action") or {}).get("state_delta_dimensions") or [])

        row: dict[str, Any] = {
            "shot_id": shot_id,
            "scene_id": str(shot.get("scene_id")),
            "video_unit_id": str(unit.get("unit_id") or ""),
            "unit_editorial_shot_ids": list(unit.get("editorial_shot_ids") or []),
            "camera_setup": {
                "global_space_map_id": setup[0], "room_id": setup[1],
                "zone_id": setup[2], "angle_id": setup[3],
            },
            "subspace_id": str(shot.get("subspace_id")),
            "shot_size": str(shot.get("shot_size")),
            "cast": cast_ids,
            "props": prop_ids,
            "wardrobe_continuity_keys": wardrobe_keys,
            "state_delta_dimensions": dimensions,
            "entry_state": str(shot.get("entry_state") or ""),
        }

        if shot_id not in planned:
            # The video-unit anchor plan carries this shot inside a longer unit,
            # so its opening frame is produced by the unit's own continuous
            # video, not by an independent paid still.
            row.update({
                "decision": "REUSE_NO_NEW_KEYFRAME",
                "reuse_mode": "INTRA_UNIT_CONTINUOUS_VIDEO_NO_SEPARATE_ANCHOR",
                "reuse_source": str(unit.get("unit_id") or ""),
                "novelty_classes": [],
                "policy_basis": "video_unit_anchor_plan.expected_keyframe_filenames_for_planned_anchors",
            })
            rows.append(row)
            continue

        boundary = (anchor_unit or {}).get("event_boundary_decision") or {}
        criteria = ((anchor_unit or {}).get("anchor_count_decision") or {}).get("criteria") or {}
        novelty: list[str] = []
        evidence: dict[str, Any] = {}

        new_characters = [cid for cid in cast_ids if cid not in seen_characters]
        if new_characters:
            novelty.append("NEW_CHARACTER_IDENTITY")
            evidence["NEW_CHARACTER_IDENTITY"] = new_characters

        if setup not in setup_owner:
            novelty.append("NEW_LOCATION_OR_SUBSPACE")
            evidence["NEW_LOCATION_OR_SUBSPACE"] = {
                "first_use_of_camera_setup": list(setup),
                "identity_or_space_reanchor": bool(criteria.get("identity_or_space_reanchor")),
            }

        new_wardrobe = [key for key in wardrobe_keys if key not in seen_wardrobe]
        if new_wardrobe:
            novelty.append("NEW_WARDROBE_STATE")
            evidence["NEW_WARDROBE_STATE"] = new_wardrobe

        non_interpolable = sorted(set(dimensions) & NON_INTERPOLABLE_DIMENSIONS)
        if non_interpolable or criteria.get("prop_ownership_transition") or criteria.get("non_interpolable_terminal_state"):
            novelty.append("NON_INTERPOLABLE_PROP_OR_BODY_STATE")
            evidence["NON_INTERPOLABLE_PROP_OR_BODY_STATE"] = {
                "entry_state_dimensions": non_interpolable,
                "prop_ownership_transition": bool(criteria.get("prop_ownership_transition")),
                "non_interpolable_terminal_state": bool(criteria.get("non_interpolable_terminal_state")),
            }

        if str(boundary.get("boundary_class") or "") == "NEW_EVENT_ANCHOR":
            novelty.append("TRANSITION_CRITICAL_TERMINAL_STATE")
            evidence["TRANSITION_CRITICAL_TERMINAL_STATE"] = {
                "boundary_class": boundary.get("boundary_class"),
                "opening_source": boundary.get("opening_source"),
            }

        # E04 (2026-09-15): a keyframe IS the shot's entry state by contract; reusing the setup owner's
        # frame is only exact when the owner shows the same entry state with the same cast.  Same
        # camera angle alone produced byte-copies with the wrong people/state (S04-04, S08-03, S10-04, S11-02).
        owner_shot = setup_owner.get(setup)
        owner_sig = setup_owner_signature.get(setup)
        this_sig = (str(row.get("entry_state") or ""), tuple(sorted(cast_ids)))
        if not novelty and owner_shot and owner_sig != this_sig:
            novelty.append("ENTRY_STATE_DIFFERS_FROM_SETUP_OWNER")
            evidence["ENTRY_STATE_DIFFERS_FROM_SETUP_OWNER"] = {"setup_owner": owner_shot, "owner_entry_state": (owner_sig or ("", ()))[0][:80], "this_entry_state": this_sig[0][:80]}
        novelty = [name for name in NOVELTY_CLASSES if name in novelty]
        if novelty:
            row.update({
                "decision": "NEW_KEYFRAME",
                "reuse_mode": None,
                "reuse_source": None,
                "novelty_classes": novelty,
                "novelty_evidence": evidence,
                "policy_basis": "production_efficiency_contract.keyframe_policy.generate_new_only_for",
            })
            seen_characters.update(cast_ids)
            seen_wardrobe.update(wardrobe_keys)
            setup_owner.setdefault(setup, shot_id)
            setup_owner_signature.setdefault(setup, this_sig)
        else:
            source = setup_owner.get(setup)
            row.update({
                "decision": "REUSE_NO_NEW_KEYFRAME",
                "reuse_mode": "EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME",
                "reuse_source": source,
                "novelty_classes": [],
                "policy_basis": "production_efficiency_contract.keyframe_policy.reuse_by_exact_sha",
                "reuse_materialization": (
                    "COPY_EXACT_SHA_BYTES_FROM_SOURCE_KEYFRAME_INTO_"
                    f"{shot_id}-keyframe-v1.png"
                ),
            })
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# reference bindings
# --------------------------------------------------------------------------- #

def _verify_media(path_value: str, sha_value: str, engine_root: Path, label: str) -> None:
    path = Path(path_value)
    resolved = path if path.is_absolute() else engine_root / path
    if not resolved.is_file():
        raise FileNotFoundError(f"{label}: locked media file is missing: {resolved}")
    actual = sha256_file(resolved)
    if actual != sha_value:
        raise ValueError(f"{label}: SHA mismatch for {resolved} (locked {sha_value}, actual {actual})")


def map_bindings(inputs: Inputs, shot_id: str, sp_task: dict[str, Any], gate_ref: str) -> list[dict[str, Any]]:
    authority = inputs.authority
    map_image = authority.get("map_image") or {}
    place = inputs.place_maps.get(str(sp_task.get("global_space_map_id"))) or {}
    layout_image = place.get("layout_image") or {}
    subspace = sp_task.get("subspace_layout") or {}
    subspace_image = subspace.get("reference_image") or {}
    note = "本地渲染的俯视拓扑图，只作空间几何与相对位置依据，不作外观或光线参考。"
    rows = [
        {
            "role": "episode_global_space_map",
            "entity_id": str(authority.get("episode_global_space_map_id")),
            "path": str(map_image.get("path")),
            "sha256": str(map_image.get("sha256")),
            "qa_status": str(map_image.get("qa_status")),
            "kind": str(map_image.get("kind")),
            "qa_report": gate_ref,
            "asset_origin": "EPISODE_NEW_ASSET",
            "binding_status": "BOUND_EXACT_SHA",
            "transport_note": note,
        },
        {
            "role": "global_space_map",
            "entity_id": str(sp_task.get("global_space_map_id")),
            "path": str(layout_image.get("path")),
            "sha256": str(layout_image.get("sha256")),
            "qa_status": str(layout_image.get("qa_status")),
            "kind": str(layout_image.get("kind")),
            "qa_report": gate_ref,
            "asset_origin": "EPISODE_NEW_ASSET",
            "binding_status": "BOUND_EXACT_SHA",
            "transport_note": note,
        },
        {
            "role": "subspace_layout",
            "entity_id": str(subspace.get("subspace_id")),
            "path": str(subspace_image.get("path")),
            "sha256": str(subspace_image.get("sha256")),
            "qa_status": str(subspace_image.get("qa_status")),
            "kind": str(subspace_image.get("kind")),
            "qa_report": gate_ref,
            "asset_origin": "EPISODE_NEW_ASSET",
            "binding_status": "BOUND_EXACT_SHA",
            "transport_note": note,
        },
    ]
    for row in rows:
        if row["qa_status"] != "PASS":
            raise ValueError(f"{shot_id}: {row['role']} media is not QA PASS")
        _verify_media(row["path"], row["sha256"], inputs.engine_root, f"{shot_id}:{row['role']}")
    return rows


def library_artifact(library: dict[str, Any], category: str, asset_id: str,
                     view: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``view`` (e.g. FRONT_NEUTRAL_HEADSHOT) selects that plate by its artifact role/view; without it
    the historical choice (canonical, else the first artifact = full body) is kept."""
    asset = ((library.get("assets") or {}).get(category) or {}).get(asset_id)
    if not isinstance(asset, dict):
        return None, None
    artifacts = [row for row in asset.get("artifacts") or [] if isinstance(row, dict)]
    if not artifacts:
        return asset, None
    if view:
        wanted = [row for row in artifacts
                  if view in (str(row.get("role") or ""), str(row.get("view") or "")) or view in str(row.get("path") or "")]
        if wanted:
            return asset, wanted[0]
    canonical = [row for row in artifacts if str(row.get("role") or "").startswith("canonical")]
    return asset, (canonical[0] if canonical else artifacts[0])


def resolve_library_asset_id(
    library: dict[str, Any], category: str, requested_id: str, display_name: str,
    view: str | None = None,
) -> str:
    """Resolve v4 canonical IDs to the library's stable local IDs.

    The v4 contract legitimately uses IDs such as ``CHAR-E50-CHENJI`` while
    the migrated Qingshan asset library keys the same identity as ``chenji``.
    Match only on explicit library facts (asset_id/label/canonical name); never
    guess from prefixes or spelling.
    """
    rows = ((library.get("assets") or {}).get(category) or {})
    def has_usable_artifact(row: Any) -> bool:
        if not isinstance(row, dict):
            return False
        artifacts = [value for value in row.get("artifacts") or [] if isinstance(value, dict)]
        if not artifacts:
            return False
        if not view:
            return True
        return any(
            view in (
                str(value.get("role") or ""),
                str(value.get("view") or ""),
            ) or view in str(value.get("path") or "")
            for value in artifacts
        )
    if requested_id in rows and has_usable_artifact(rows[requested_id]):
        return requested_id
    wanted = str(display_name or "").strip()
    candidates: list[str] = []
    for key, row in rows.items():
        if not isinstance(row, dict):
            continue
        spec = row.get("specification") or {}
        explicit = {
            str(row.get("asset_id") or "").strip(),
            str(row.get("label") or "").strip(),
            str(spec.get("canonical_name") or "").strip(),
            str(spec.get("location_id") or "").strip(),
        }
        aliases = {str(value).strip() for value in (spec.get("aliases") or [])}
        if not has_usable_artifact(row):
            continue
        if requested_id in explicit or wanted in explicit or wanted in aliases:
            candidates.append(str(key))
        elif wanted and any(wanted in value or value in wanted for value in explicit | aliases if value):
            candidates.append(str(key))
    return candidates[0] if len(set(candidates)) == 1 else requested_id


def cap_non_character_bindings(rows: list[dict[str, Any]], *, limit: int = NON_CHARACTER_REFERENCE_MAX,
                               total_limit: int = REFERENCE_TOTAL_MAX) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Roger 2026-09-18 ②: space maps + scene + props <= ``limit``.  The engine gates make every one of those
    mandatory (SCENE-AUTHORITY-LOCK needs the three maps; the image submitter needs every prop the contract
    declares), so an over-cap shot is REPORTED (``dropped_reason`` OVER_CAP_NOT_DROPPED_GATE_MANDATORY) and the
    writer is expected to declare fewer props per shot.  Only full-body wardrobe plates are dropped, and only
    to hold the provider's total limit; face plates, maps, scene and declared props are never removed."""
    kept = list(rows)
    dropped: list[dict[str, Any]] = []
    non_char = [r for r in kept if str(r["role"]) not in ("character", "character_wardrobe")]
    if len(non_char) > limit:
        for r in non_char[limit:]:
            dropped.append({**r, "dropped_reason": f"OVER_CAP_NOT_DROPPED_GATE_MANDATORY_{limit}"})
    while len(kept) > total_limit:
        victims = [r for r in kept if str(r["role"]) == "character_wardrobe"]
        if not victims:
            break
        victim = victims[-1]
        kept.remove(victim); dropped.append({**victim, "dropped_reason": f"REFERENCE_TOTAL_MAX_{total_limit}"})
    return kept, dropped


def entity_binding(
    inputs: Inputs, role: str, category: str, asset_id: str, display_name: str, kind: str,
    view: str | None = None,
) -> dict[str, Any]:
    contract_asset_id = asset_id
    library_asset_id = resolve_library_asset_id(
        inputs.asset_library, category, contract_asset_id, display_name, view,
    )
    asset, artifact = library_artifact(inputs.asset_library, category, library_asset_id, view)
    if role == 'character' and asset:
        from tools.original_identity_authority import original_reference
        original = original_reference(asset)
        if original:
            artifact = original
            view = 'APPROVED_SOURCE_CARD'
    library_ref = engine_relative(inputs.asset_library_path, inputs.engine_root)
    qa_status = str(((asset or {}).get("qa") or {}).get("status") or "PENDING")
    if artifact:
        path_value = str(artifact.get("path") or "")
        resolved = Path(path_value)
        resolved = resolved if resolved.is_absolute() else inputs.engine_root / resolved
        declared = str(artifact.get("sha256") or "")
        if path_value and resolved.is_file() and declared and sha256_file(resolved) == declared:
            return {
                "role": role,
                "entity_id": contract_asset_id,
                "library_asset_id": library_asset_id,
                "entity_name": display_name,
                "path": path_value,
                "sha256": declared,
                "qa_status": qa_status,
                "kind": kind,
                "view": view or str(artifact.get("role") or artifact.get("view") or ""),
                "qa_report": library_ref,
                "asset_origin": "EPISODE_NEW_ASSET",
                "binding_status": "BOUND_EXACT_SHA",
                "asset_library_status": str((asset or {}).get("status") or ""),
            }
    return {
        "role": role,
        "entity_id": contract_asset_id,
        "library_asset_id": library_asset_id,
        "entity_name": display_name,
        "path": awaited_identity_path(inputs.awaited_asset_dir, category, contract_asset_id),
        "sha256": PENDING_SHA_SENTINEL,
        "qa_status": qa_status,
        "kind": kind,
        "qa_report": library_ref,
        "asset_origin": "EPISODE_NEW_ASSET",
        "binding_status": "PENDING_ASSET_LIBRARY_ARTIFACT",
        "asset_library_status": str((asset or {}).get("status") or "ABSENT_FROM_ASSET_LIBRARY"),
        "awaited": (
            f"stage 3(a) must produce {contract_asset_id} and register it in "
            f"{library_ref} with status LOCKED and qa.status PASS"
        ),
    }


def scene_binding(inputs: Inputs, shot: dict[str, Any], subspace_row: dict[str, Any]) -> dict[str, Any]:
    """The single provider-facing scene reference.

    `submit_giggle_image_manifest.validate_task` requires exactly one binding
    with role scene/destination_scene.  When the stage-3(a) location plate for
    this shot's LOC id is registered and byte-verifiable it is used.  Until then
    the shot's own rendered subspace topology plate carries the role, exactly as
    the already-passing stage-3(a) location tasks do; the fallback is labelled so
    it can never be mistaken for a look reference.
    """
    location_id = str(((shot.get("prompt_spec") or {}).get("space") or {}).get("location") or "")
    bound = entity_binding(
        inputs, "scene", "scenes", location_id, location_id, "SCENE_ESTABLISHING_PLATE",
    )
    if bound["binding_status"] == "BOUND_EXACT_SHA":
        return bound
    row = deepcopy(subspace_row)
    row.update({
        "role": "scene",
        "entity_id": location_id,
        "kind": "SHOT_SUBSPACE_LAYOUT_AS_SCENE_REFERENCE",
        "binding_status": "FALLBACK_LOCAL_TOPOLOGY_RENDER",
        "fallback_reason": "SCENE_PLATE_PENDING_STAGE_3A_ASSET_LIBRARY",
        "awaited": bound["awaited"],
        "awaited_path": bound["path"],
        "transport_note": (
            "俯视拓扑图承担唯一 scene 参考位，只提供空间布局与相对位置；"
            "输出必须是实拍质感画面，不得画成地图、示意图、平面图或带任何标注线条。"
        ),
    })
    return row


def wardrobe_plate_excluded(spec: dict[str, Any], asset_id: str) -> bool:
    """Only explicitly reviewed conflicts may suppress an optional costume plate."""
    record = (spec.get("wardrobe_reference_exclusions") or {}).get(asset_id)
    if record is None:
        return False
    if not isinstance(record, dict) or not all(record.get(k) for k in ("reason", "evidence_ref")):
        raise ValueError(f"WARDROBE_EXCLUSION_EVIDENCE_REQUIRED:{asset_id}")
    if not (spec.get("wardrobe_state_overrides") or {}).get(asset_id):
        raise ValueError(f"WARDROBE_EXCLUSION_AUTHORED_STATE_REQUIRED:{asset_id}")
    return True


def build_bindings(inputs: Inputs, shot_id: str, gate_ref: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    shot = inputs.shots[shot_id]
    sp_task = inputs.subspace_tasks[shot_id]
    space_rows = map_bindings(inputs, shot_id, sp_task, gate_ref)
    scene_row = scene_binding(inputs, shot, space_rows[2])

    blocking = sp_task.get("blocking") or {}
    character_ids: list[str] = []
    prop_ids: list[str] = []
    face_rows: list[dict[str, Any]] = []
    wardrobe_rows: list[dict[str, Any]] = []
    prop_rows: list[dict[str, Any]] = []
    for entry in blocking.get("characters") or []:
        asset_id = str(entry.get("character_id") or "")
        if not asset_id or asset_id in character_ids:
            continue
        character_ids.append(asset_id)
        name = str(entry.get("character") or asset_id)
        # Roger 2026-09-18 ②: the front neutral headshot is the face reference and leads the
        # sequence; the full-body plate is demoted to a wardrobe reference.
        face_rows.append(entity_binding(inputs, "character", "characters", asset_id, name,
                                        "CHARACTER_IDENTITY_PLATE", view=CHARACTER_FACE_VIEW))
        if not wardrobe_plate_excluded(shot.get("prompt_spec") or {}, asset_id):
            wardrobe_rows.append(entity_binding(inputs, "character_wardrobe", "characters", asset_id, name,
                                                "CHARACTER_WARDROBE_PLATE", view=CHARACTER_WARDROBE_VIEW))
    for entry in blocking.get("props") or []:
        asset_id = str(entry.get("prop_id") or "")
        if not asset_id or asset_id in prop_ids:
            continue
        prop_ids.append(asset_id)
        prop_rows.append(entity_binding(
            inputs, "prop", "props", asset_id,
            str(entry.get("prop") or asset_id), "PROP_IDENTITY_PLATE",
        ))
    rows, dropped = cap_non_character_bindings(space_rows + face_rows + [scene_row] + wardrobe_rows + prop_rows)
    if dropped:
        report = getattr(inputs, "reference_cap_report", None)
        if report is None:
            report = {}
            setattr(inputs, "reference_cap_report", report)
        report[shot_id] = [{"role": r["role"], "entity_id": r.get("entity_id"), "reason": r["dropped_reason"]} for r in dropped]

    order = [BINDING_ROLE_ORDER.index(str(row["role"])) for row in rows]
    if order != sorted(order):
        raise ValueError(f"{shot_id}: reference binding order violates episode->place->subspace->character->scene->character_wardrobe->prop")
    return rows, character_ids, prop_ids


# --------------------------------------------------------------------------- #
# prompt
# --------------------------------------------------------------------------- #

def describe_blocking(rows: list[dict[str, Any]], id_field: str, name_field: str) -> str:
    parts = [
        f"{row.get(name_field) or row.get(id_field)}（{row.get(id_field)}）位于 {row.get('zone_id')}"
        f" 坐标 {row.get('position')} 朝向 {row.get('facing')}"
        for row in rows or []
    ]
    return "；".join(parts) if parts else "无"


def visual_culture_block(contract: dict[str, Any]) -> str:
    palette = contract.get("palette_system") or {}
    return "\n".join([
        f"【视觉文化档案】{contract.get('profile_id')}",
        f"世界：{contract.get('story_world')}",
        f"美术：{contract.get('production_design')}",
        f"色彩：底色{palette.get('base')}；点色{palette.get('accent')}；肤色{palette.get('skin')}",
        f"光线：{contract.get('lighting_language')}",
        f"质感：{contract.get('image_texture')}",
        "画幅：9:16 竖构图。画面内不得出现任何文字、字幕、水印、logo。禁欧洲、板甲、黑金。",
    ])


def has_forbidden_word(text: str) -> str | None:
    for word in FORBIDDEN_EXTEND_WORDS:
        if word in text:
            return word
    return None


def normalize_keyframe_role_semantics(
    role_value: dict[str, Any], *, shot_id: str, entry_state: str,
    visible_contract_ids: list[str],
) -> dict[str, Any]:
    """Normalize an authored role graph for an entry-frame image task.

    The v4 adapter may legitimately name an off-screen dialogue listener without
    adding that listener to the visible cast.  The role gate nevertheless
    requires every authored participant to have matching state/presence keys.
    Add only participants already named by the contract; never infer a role or
    promote an off-screen participant into the provider-visible cast.
    """
    role = deepcopy(role_value or {})
    if not role:
        return role
    role.setdefault("schema", "qingshan.role_semantic_disambiguation.v1")
    role.setdefault("status", "PASS")
    role.setdefault("shot_id", shot_id)
    role.setdefault("forbidden_role_swaps", True)
    if role.get("dialogue_speaker") and not role.get("dialogue_listener"):
        role.setdefault("dialogue_mode", "SELF_DIRECTED_SPEECH")

    states = dict(role.get("entity_states") or {})
    presence = dict(role.get("entity_presence") or {})
    visible = set(map(str, visible_contract_ids))
    participant_keys = []
    for id_key, name_key in (
        ("primary_actor_id", "primary_actor"),
        ("dialogue_speaker_id", "dialogue_speaker"),
        ("dialogue_listener_id", "dialogue_listener"),
        ("action_patient_id", "action_patient"),
    ):
        value = str(role.get(id_key) or role.get(name_key) or "").strip()
        if value:
            participant_keys.append(value)
    body_part_owner = str(role.get("body_part_owner") or "").strip()
    if body_part_owner:
        participant_keys.append(body_part_owner)

    entry_states = role.get("entity_entry_states") or {}
    if not isinstance(entry_states, dict):
        raise ValueError(f"{shot_id}: ENTITY_ENTRY_STATES_MUST_BE_MAPPING")
    participants = list(dict.fromkeys([*states, *presence, *participant_keys, *visible_contract_ids]))
    # A video trajectory is not a still-image entry pose. Never copy a shared
    # sentence to several people, or silently select an end-state from it.
    states = {}
    for entity_id in participants:
        presence.setdefault(
            entity_id,
            "VISIBLE_AND_IDENTITY_LOCKED" if entity_id in visible else "ABSENT_REFERENCE_ONLY",
        )
        explicit = str(entry_states.get(entity_id) or "").strip()
        if explicit:
            states[entity_id] = explicit
        elif entity_id not in visible:
            states[entity_id] = "本首帧不入画；不赋予画内人物的姿态或动作"
        elif len(visible) == 1:
            states[entity_id] = entry_state
        else:
            raise ValueError(f"{shot_id}: ENTITY_ENTRY_STATE_REQUIRED:{entity_id}")
    role["entity_states"] = states
    role["entity_presence"] = presence
    return role


def build_prompt(inputs: Inputs, shot_id: str, bindings: list[dict[str, Any]],
                 character_ids: list[str], decision: dict[str, Any],
                 dropped: list[dict[str, str]]) -> str:
    shot = inputs.shots[shot_id]
    spec = shot.get("prompt_spec") or {}
    sp_task = inputs.subspace_tasks[shot_id]
    subspace = sp_task.get("subspace_layout") or {}
    blocking = sp_task.get("blocking") or {}
    scene_state = spec.get("scene_state") or {}
    design = spec.get("visual_design") or {}
    entry_state = str(shot.get("entry_state") or "").strip()
    if not entry_state:
        raise ValueError(f"{shot_id}: entry_state is empty; keyframes have no fallback source")
    visible_contract_ids = [
        str(row.get("character_id") or "")
        for row in (blocking.get("characters") or [])
        if str(row.get("character_id") or "")
    ]
    role = normalize_keyframe_role_semantics(
        spec.get("role_semantic_disambiguation") or {},
        shot_id=shot_id,
        entry_state=entry_state,
        visible_contract_ids=visible_contract_ids,
    )

    reference_lines = []
    for index, row in enumerate(bindings, 1):
        purpose = {
            "episode_global_space_map": "仅提供全集空间拓扑与地点相对位置",
            "global_space_map": "仅提供本地点的房间/区域拓扑与坐标",
            "subspace_layout": "仅提供本镜机位、轴线、可见固定元素与站位几何",
            "scene": "唯一场景参考位",
            "character": "正面头像：锁定该人物的脸型、五官、发型与年龄（脸以此图为准）",
            "character_wardrobe": "全身像：仅锁定该人物的服装形制、体型比例与配饰；脸不以此图为准",
            "prop": "仅锁定该道具的形制、材质与尺度",
        }[str(row["role"])]
        # Binding bookkeeping stays out of the provider text so the prompt SHA is
        # stable across the stage-3(a) plate upgrade.
        reference_lines.append(
            f"- 参考图{index} {row['role']} / {row['entity_id']}：{purpose}。"
        )

    cast_names = [
        f"{row.get('entity_name')}（{row['entity_id']}）"
        for row in bindings if row["role"] == "character"
    ]
    prop_names = [
        f"{row.get('entity_name')}（{row['entity_id']}）"
        for row in bindings if row["role"] == "prop"
    ]
    # E05 (2026-09-17): a character-free frame whose props include a creature card (the talking crow)
    # is not an empty frame — the old "无动物；空镜" clause contradicted the prop line and risked an empty
    # thornbush.  Name the prop subjects instead; the pure empty-frame wording stays for prop-less frames.
    cast_clause = (
        f"本帧允许入画的人物（仅这些，且各只出现一次）：{join(cast_names, '、')}"
        if cast_names else (
            f"画面内无人物；主体只有上列道具/生物（{join(prop_names, '、')}），各只出现一次，不加任何人物"
            if prop_names else "画面内无人物、无动物；空镜。")
    )
    wardrobe_lines = []
    for asset_id in character_ids:
        row = inputs.wardrobe_by_character.get(asset_id) or {}
        if not row:
            continue
        # Authored text first; every null field is skipped (the bible leaves a field
        # null when the authored wardrobe description does not decide it).
        override = ((inputs.shots[shot_id].get("prompt_spec") or {}).get("wardrobe_state_overrides") or {}).get(asset_id)
        if override:
            # per-shot wardrobe STATE authored in the generation contract (e.g. 单衣 before S04)
            # This is the complete authored shot state, not an additive hint.
            # Appending the global condition can reintroduce another scene's
            # injuries or clothing after an explicit scoped replacement.
            parts = [f"【本镜服装状态】{str(override).strip()}"]
            keys = ()
        elif row.get("authored_description"):
            # the authored text already carries layers / fastening / accessory verbatim
            parts = [str(row["authored_description"]).strip()]
            keys = (("condition", ""),)
        else:
            parts = []
            keys = (("silhouette", ""), ("outer_layer", "外层"), ("inner_layer", "内层"),
                    ("primary_color", "主色"), ("secondary_color", "辅色"), ("material", ""),
                    ("belt_or_fastening", ""), ("footwear", ""), ("accessory", ""), ("condition", ""))
        for key, prefix in keys:
            value = row.get(key)
            if value:
                parts.append(f"{prefix}{value}")
        wardrobe_lines.append(f"- {row.get('character')}（{asset_id}）：" + "；".join(parts))

    forbidden = list(inputs.visual_culture.get("forbidden_influences") or [])
    # The shot's negative list already re-states the culture contract's
    # forbidden_influences; emit each constraint exactly once.
    negatives = [row for row in (spec.get("negative_prompts") or []) if row not in forbidden]

    place = inputs.place_maps.get(str(sp_task.get("global_space_map_id"))) or {}
    unit = str(((place.get("coordinate_system") or {}).get("unit")) or "meter")

    # Decorative/derived lines are optional: if an authored source string carries
    # an extend-word (持续/保持/连续) the line is dropped and recorded rather than
    # rewritten, because a keyframe prompt must never invite continuation.  Lines
    # that carry the shot's actual authority are required and must be clean.
    segments: list[tuple[str, str, bool]] = [
        ("header",
         f"用途：{inputs.episode} 逐镜关键帧（entry_state 首帧）。竖屏 9:16 实拍质感单帧电影画面，"
         "不是拼贴板、人物设定卡、分镜表、平面图或空间示意图。", True),
        ("slate", f"镜号：{shot_id}｜场：{shot.get('scene_id')}｜视频单元：{decision.get('video_unit_id')}", True),
        ("blank1", "", True),
        ("entry_head", "【entry_state（逐字绑定；本帧唯一允许表现的状态）】", True),
        ("entry_state", entry_state, True),
        ("blank2", "", True),
        ("space_head", "【空间解析顺序（不可跳级）】", True),
        ("space_chain",
         f"{sp_task.get('episode_global_space_map_id')} → {sp_task.get('global_space_map_id')}"
         f" → {subspace.get('subspace_id')} → 人物/道具站位", True),
        ("place",
         f"地点：{((spec.get('space') or {}).get('location'))}｜房间：{sp_task.get('room_id')}"
         f"｜区域：{join(subspace.get('zone_ids'), '、')}", True),
        ("camera_ids",
         f"机位：{sp_task.get('angle_id')}｜轴线：{subspace.get('axis_id')}"
         f"｜银幕方向：{subspace.get('screen_direction')}｜机位坐标：{subspace.get('camera_position')}"
         f"｜机位朝向：{subspace.get('camera_facing')}", True),
        ("fixed_elements",
         f"可见固定元素（必须全部出现且相对位置与拓扑图一致）：{join(subspace.get('visible_fixed_element_ids'), '；')}", True),
        ("blank3", "", True),
        ("size_head", "【景别与摄影】", True),
        ("shot_size", f"景别：{shot.get('shot_size')}", True),
        ("camera", f"摄影：{spec.get('camera')}", True),
        ("axis", f"轴线声明：{shot.get('axis')}", True),
        ("authored_camera_note", f"机位说明：{subspace.get('authored_camera_note')}", False),
        ("blank4", "", True),
        ("blocking_head", "【entry 时刻站位（本帧唯一站位依据）】", True),
        ("blocking_characters",
         f"人物：{describe_blocking(blocking.get('characters') or [], 'character_id', 'character')}", True),
        ("blocking_props",
         f"道具：{describe_blocking(blocking.get('props') or [], 'prop_id', 'prop')}", True),
        ("role_semantics", role_semantic_prompt_block(role), True),
        ("cast_clause", cast_clause, True),
        ("scale",
         f"比例基准：以已声明的可见固定元素与人物肩宽为真实比例基准；place map "
         f"{sp_task.get('global_space_map_id')} 的坐标单位为{unit}。", True),
        ("blank5", "", True),
        ("wardrobe_head", "【服装锁】" if wardrobe_lines else "【服装锁】无人物，无需服装锁。", True),
        *[(f"wardrobe_{index}", line, True) for index, line in enumerate(wardrobe_lines)],
        ("blank6", "", True),
        ("state_head", "【场景状态】", True),
        ("time_weather", f"时间：{scene_state.get('time')}｜天气：{scene_state.get('weather')}", True),
        ("lighting", f"光线：{scene_state.get('lighting')}", True),
        ("key_light", f"关键光：{design.get('key_light')}", False),
        ("palette", f"主色：{scene_state.get('palette')}", True),
        ("atmosphere", f"空气与质感：{design.get('atmosphere')}", False),
        ("material_detail", f"材质细节：{join(design.get('material_detail'), '、')}", False),
        ("depth_layers", f"纵深层次：{join(design.get('depth_layers'), '｜')}", False),
        ("blank7", "", True),
        ("reference_head", "【参考图用途（逐张，不得越权）】", True),
        *[(f"reference_{index}", line, True) for index, line in enumerate(reference_lines)],
        ("reference_note",
         "承担空间与 scene 位的都是本地渲染的俯视拓扑图，只作空间几何依据；"
         "不得把图中的线条、标注、网格、图例或任何文字画进正片。", True),
        ("blank8", "", True),
        ("visual_culture", visual_culture_block(inputs.visual_culture), True),
        ("blank9", "", True),
        ("hard_head", "【本帧硬约束】", True),
        ("hard_entry", f"画面只表现上面的 entry_state：{entry_state}", True),
        ("hard_no_completion",
         "不得画出本镜动作的结果态、动作进行中的瞬间，或任何在 entry_state 之后才成立的状态。", True),
        ("hard_cast", "未列入允许入画名单的人物、动物不得出现；不得增删、合并或复制人物。", True),
        ("hard_realism",
         "真实透视、人物脚底落地、可信人体解剖与真实材质；单帧静止画面，无运动模糊特效。", True),
        ("blank10", "", True),
        ("negative_head", "【严格禁止】", True),
        ("negatives", join(forbidden + negatives, "；"), True),
        ("blank11", "", True),
    ]

    completion = str(shot.get("completion_state") or "").strip()
    # A still may carry the entry state only.  The authored primary_action is the
    # motion between entry and completion, so quoting it into an image prompt
    # invites the model to render the action already under way.
    primary_action = str((spec.get("action") or {}).get("primary_action") or "").strip()
    lines: list[str] = []
    for name, text, required in segments:
        reason = ""
        # ``entry_state`` is a frozen source-frame description.  It may use
        # aspect words such as "持续悬着" to describe the pose at the cut;
        # those words are forbidden in motion/action clauses because they
        # flatten movement, but rejecting them here makes valid v4 contracts
        # impossible to compile.  Keep the verbatim entry state and continue
        # rejecting the same words everywhere else.
        word = None if name in {"entry_state", "role_semantics"} else has_forbidden_word(text)
        if word and entry_state and entry_state in text:
            # Hard-entry restatements intentionally quote the same frozen
            # source state; only inspect the wrapper text for motion leakage.
            word = has_forbidden_word(text.replace(entry_state, ""))
        if word:
            reason = f"FORBIDDEN_EXTEND_WORD:{word}"
        elif completion and completion in text:
            reason = "COMPLETION_STATE_LEAK"
        elif primary_action and primary_action in text:
            reason = "PRIMARY_ACTION_LEAK"
        if reason:
            if required:
                raise ValueError(
                    f"{shot_id}: required prompt segment '{name}' violates the entry-only "
                    f"contract ({reason}); the authored source must be corrected upstream"
                )
            dropped.append({"shot_id": shot_id, "segment": name, "reason": reason})
            continue
        lines.append(text)
    prompt = "\n".join(lines)
    # Role semantics is a static identity/lip-ownership contract.  Its state
    # values may quote the frozen entry state and its phrase "保持闭口" is not
    # an instruction to extend motion.  Exclude this exact machine block from
    # the motion-word scan while retaining the scan for every authored segment.
    prompt_without_entry = prompt.replace(entry_state, "").replace(
        role_semantic_prompt_block(role), ""
    ).replace("保持闭口", "")
    for word in FORBIDDEN_EXTEND_WORDS:
        if word in prompt_without_entry:
            pos = prompt_without_entry.find(word)
            raise ValueError(
                f"{shot_id}: compiled prompt contains the forbidden extend-word 「{word}」 "
                f"near={prompt_without_entry[max(0, pos-60):pos+100]}"
            )
    if completion and completion in prompt:
        raise ValueError(f"{shot_id}: compiled prompt leaks completion_state")
    if primary_action and primary_action in prompt:
        raise ValueError(f"{shot_id}: compiled prompt leaks primary_action")
    if entry_state not in prompt:
        raise ValueError(f"{shot_id}: compiled prompt does not carry entry_state verbatim")
    return prompt


# --------------------------------------------------------------------------- #
# task compilation
# --------------------------------------------------------------------------- #

def compile_task(inputs: Inputs, decision: dict[str, Any], prompt_dir: Path,
                 keyframe_dir: Path, gate_ref: str, model: str, resolution: str,
                 dropped: list[dict[str, str]], task_version: str = "V1") -> dict[str, Any]:
    shot_id = decision["shot_id"]
    shot = inputs.shots[shot_id]
    spec = shot.get("prompt_spec") or {}
    sp_task = inputs.subspace_tasks[shot_id]
    action = spec.get("action") or {}
    task_key = f"{shot_id}-KEYFRAME-{task_version}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", task_key):
        raise ValueError(f"{shot_id}: task_key is not a portable identifier")
    bindings, character_ids, prop_ids = build_bindings(inputs, shot_id, gate_ref)
    entry_state = str(shot.get("entry_state") or "").strip()
    role = normalize_keyframe_role_semantics(
        spec.get("role_semantic_disambiguation") or {},
        shot_id=shot_id,
        entry_state=entry_state,
        visible_contract_ids=character_ids,
    )
    prompt = build_prompt(inputs, shot_id, bindings, character_ids, decision, dropped)
    from tools.identity_pose_reference import supplement_pose_references
    bindings, pose_reference_report = supplement_pose_references(
        bindings, inputs.asset_library, entry_state, limit=REFERENCE_TOTAL_MAX
    )
    identity_sequence, identity_transport, prompt = compile_labeled_flat_identity_transport(
        task_key, bindings, prompt
    )
    bound_character_ids = [
        str(row.get("entity_id") or "") for row in bindings
        if row.get("role") == "character" and str(row.get("entity_id") or "")
    ]
    bound_prop_ids = [
        str(row.get("entity_id") or "") for row in bindings
        if row.get("role") == "prop" and str(row.get("entity_id") or "")
    ]
    library_assets = inputs.asset_library.get("assets") or {}
    character_catalog = [
        {"entity_id": key, **(value if isinstance(value, dict) else {})}
        for key, value in (library_assets.get("characters") or {}).items()
    ]
    prop_catalog = [
        {"entity_id": key, **(value if isinstance(value, dict) else {})}
        for key, value in (library_assets.get("props") or {}).items()
    ]
    provider_scope = build_provider_scope_projection(
        visible_character_ids=bound_character_ids, visible_prop_ids=bound_prop_ids,
        episode_character_catalog=character_catalog,
        episode_prop_catalog=prop_catalog,
        reference_images=[row for row in identity_sequence if str(row.get("role")) == "character"], scene_domain="QINGSHAN_E59",
        location_ids=[str(shot.get("scene_id") or "")],
    )
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{task_key}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    # entry_state is the authored action this still is allowed to represent.
    # completion_state is deliberately never used as the contract source.
    source_action = entry_state
    reference_images = stable_unique([str(row["path"]) for row in identity_sequence])

    spatial_continuity = {
        "mode": "SAME_SPACE_CONTINUOUS",
        "policy_source": "PER_UNIT_SCRIPT_CONTENT",
        "anchor_scope": "LOCKED_EPISODE_PLACE_SUBSPACE_ENTRY_STATE_KEYFRAME",
        "scene_id": str(shot.get("scene_id")),
    }
    prompt_contract = {
        "schema": "qingshan.image_prompt_contract.v2",
        "status": "PASS",
        "shot_id": shot_id,
        "source_script_sha256": inputs.contract_sha256,
        "source_action": source_action,
        "source_action_sha256": sha256_text(source_action),
        "keyframe_source": "entry_state",
        "completion_state_used": False,
        "visible_characters": list(character_ids),
        "visible_character_names": [
            str(row.get("entity_name")) for row in bindings if row["role"] == "character"
        ],
        "canonical_props": list(prop_ids),
        "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
        "reference_bindings": identity_sequence,
        "spatial_continuity": spatial_continuity,
        "failures": [],
    }

    source_shot_contract = {
        key: value
        for key, value in (sp_task.get("source_shot_contract") or {}).items()
        if key != "completion_state"
    }
    source_shot_contract["entry_state"] = entry_state
    source_shot_contract["keyframe_source"] = "entry_state"

    task: dict[str, Any] = {
        "task_key": task_key,
        "shot_id": shot_id,
        "scene_id": str(shot.get("scene_id")),
        "video_unit_id": decision.get("video_unit_id") or None,
        "episode": inputs.episode,
        "tool_type": "image_generation",
        "image_purpose": "SHOT_KEYFRAME",
        "spatial_layout_stage": "SHOT_KEYFRAME",
        "media_stage": "KEYFRAME",
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "source_script_sha256": inputs.contract_sha256,
        "prompt_file": str(prompt_path),
        "prompt_sha256": sha256_text(prompt),
        "prompt_contract": prompt_contract,
        "identity_reference_transport": identity_transport,
        "provider_scope_projection": provider_scope,
        "visual_culture_contract": {
            **deepcopy(inputs.visual_culture),
            "schema": "qingshan.visual_culture_contract.v1",
            "status": "LOCKED",
            "decision_owner": "WRITER_DIRECTOR",
            "source_ref": "E59_GENERATION_CONTRACT_v1.json#visual_culture_contract",
            "forbidden_influences": list(dict.fromkeys(
                list(inputs.visual_culture.get("forbidden_influences") or [])
                + ["欧洲中世纪骑士", "西式板甲", "黑金奇幻"]
            )),
        },
        "role_semantic_disambiguation": deepcopy(role),
        "spatial_continuity": spatial_continuity,
        # spatial authority chain, copied verbatim from the locked subspace plan
        "episode_global_space_map_id": sp_task.get("episode_global_space_map_id"),
        "global_space_map_id": sp_task.get("global_space_map_id"),
        "room_id": sp_task.get("room_id"),
        "zone_id": sp_task.get("zone_id"),
        "angle_id": sp_task.get("angle_id"),
        "resolution_order": list(RESOLUTION_ORDER),
        "subspace_layout": deepcopy(sp_task.get("subspace_layout")),
        "blocking": deepcopy(sp_task.get("blocking")),
        "space_chain_id": sp_task.get("space_chain_id"),
        # entry-only keyframe contract (tools/keyframe_entry_state_gate.py)
        "pipeline_rectification_version": "E51_V1",
        "source_shot_contract": source_shot_contract,
        "target_completion_state": {
            "state_delta_dimensions": list(action.get("state_delta_dimensions") or []),
            "state_delta_evidence": deepcopy(action.get("state_delta_evidence") or {}),
            "note": "Retained outside source_shot_contract purely for the entry/exit distinctness check; never sent to the provider.",
        },
        "reference_bindings": identity_sequence,
        "reference_image_sequence": identity_sequence,
        "identity_pose_reference_review": pose_reference_report,
        "reference_images": reference_images,
        "visible_characters": list(character_ids),
        "canonical_characters": list(character_ids),
        "canonical_props": list(prop_ids),
        "require_semantic_anchor_evidence": True,
        "keyframe_decision": {
            "decision": decision["decision"],
            "novelty_classes": decision.get("novelty_classes") or [],
            "policy": "SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE",
        },
        "output_contract": {
            "expected_output_path": str(keyframe_dir / f"{shot_id}-keyframe-{task_version.lower()}.png"),
            "naming_contract": "{shot_id}-keyframe-v{N}.png",
            "consumer": "build_video_unit_anchor_plan.py glob f'{shot_id}-keyframe-v*.png'",
        },
        "status": "READY_TO_SUBMIT",
        "provider_post_allowed": False,
        "maximum_new_submissions": 1,
    }

    def describe(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": row["role"], "entity_id": row["entity_id"],
            "binding_status": row["binding_status"],
            "awaited_path": row.get("awaited_path") or row["path"],
            "awaited": row.get("awaited"),
        }

    # A PENDING identity/prop plate blocks precheck.  A scene binding served by
    # the shot's own rendered topology plate does not block anything: the file
    # exists and its SHA verifies; it is only marked so the stage-3(a) LOC plate
    # can replace it later.
    pending = [row for row in bindings if row.get("binding_status") == "PENDING_ASSET_LIBRARY_ARTIFACT"]
    deferred = [row for row in bindings if row.get("binding_status") == "FALLBACK_LOCAL_TOPOLOGY_RENDER"]
    task["pending_bindings"] = [describe(row) for row in pending]
    task["deferred_binding_upgrades"] = [describe(row) for row in deferred]
    if pending:
        task["blocking_note"] = (
            "PENDING_ASSET_LIBRARY_ARTIFACTS: "
            + ", ".join(sorted({row["entity_id"] for row in pending}))
            + ". submit_giggle_image_manifest.validate_task will FAIL until stage 3(a) "
            "registers these plates (qa.status PASS + byte-verifiable file)."
        )
    return task


def task_is_fully_bound(task: dict[str, Any]) -> bool:
    """True when every binding names a file that exists with a verified SHA."""
    return not task.get("pending_bindings")


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #

def build_manifest(inputs: Inputs, tasks: list[dict[str, Any]], keyframe_dir: Path,
                   model: str, resolution: str, subset_mode: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA_MANIFEST,
        "episode": inputs.episode,
        "batch_id": f"{inputs.episode}-SHOT-KEYFRAME-V1" + ("-SUBSET-EXISTING-BINDINGS" if subset_mode else ""),
        "purpose": (
            f"{inputs.episode} per-shot entry_state keyframes (stage 3(b)). "
            "Selected by the semantic-novelty keyframe policy, not one per editorial shot."
        ),
        "provider": "giggle",
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "machine_gate_reports": inputs.gate_report_refs(),
        "episode_global_space_map_ref": engine_relative(inputs.authority_path, inputs.engine_root),
        "global_space_map_gate_required": True,
        "global_space_map_gate_note": (
            "Shot-keyframe batch: every task carries the full "
            "episode-map -> place-map -> subspace -> blocking chain, so the gate is mandatory."
        ),
        "keyframe_policy": {
            "mode": "SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE",
            "one_keyframe_per_editorial_shot_forbidden": True,
            "policy_source": "tools/production_efficiency_contract.py keyframe_policy",
        },
        "keyframe_source_contract": {
            "source": "entry_state",
            "completion_state_forbidden": True,
            "forbidden_entry_words": list(FORBIDDEN_EXTEND_WORDS),
            "gate": "tools/keyframe_entry_state_gate.py",
        },
        "output_contract": {
            "keyframe_dir": str(keyframe_dir),
            "flat_dir": True,
            "naming_contract": "{shot_id}-keyframe-v{N}.png",
            "consumer": "build_video_unit_anchor_plan.py",
            "expected_filenames": [
                Path(str((task.get("output_contract") or {}).get("expected_output_path") or "")).name
                for task in tasks
            ],
        },
        "subset_mode": "EXISTING_BINDINGS_ONLY" if subset_mode else "FULL_EPISODE",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "authorization_ref": "",
        "paid_submission_prerequisites": [
            "Stage 3(a) character/prop plates LOCKED with qa.status PASS in the asset library.",
            "Set provider_post_allowed=true and maximum_new_submissions>=len(selected tasks).",
            "Materialize authorization_ref from the validated private line-owner order.",
            "Register exactly one GIGGLE-REROLL-COST-GUARD report whose reviewed_manifest_sha256 "
            "equals this manifest file's sha256 (submit_giggle_image_manifest.validate_submission_authority).",
            "Every task must be status READY_TO_SUBMIT with provider_post_allowed=true and maximum_new_submissions==1.",
        ],
        "consumer_contract": {
            "purpose": "EXACT_SHA_KEYFRAME_VIDEO_SUBMIT_ADMISSION",
            "one_independent_task_per_selected_shot": True,
            "q1_admission_required_after_harvest": (
                "ADMITTED or ADMITTED_WITH_P2 with downstream_status ADMITTED_FOR_VIDEO_SUBMIT"
            ),
        },
        "task_count": len(tasks),
        "tasks": tasks,
        "blocked_tasks": [],
        "reference_policy": {"authority": "ENGINE_REFERENCE_POLICY_FACE_FIRST_V1", "face_view_first": CHARACTER_FACE_VIEW,
                             "wardrobe_view": CHARACTER_WARDROBE_VIEW, "non_character_reference_max": NON_CHARACTER_REFERENCE_MAX,
                             "reference_total_max": REFERENCE_TOTAL_MAX, "drop_order": NON_CHARACTER_DROP_ORDER},
        "reference_cap_report": getattr(inputs, "reference_cap_report", {}) or {},
        "generated_by": "runtime/tools/build_keyframe_manifest.py",
        "generated_at": utc_now(),
    }


# --------------------------------------------------------------------------- #
# credits
# --------------------------------------------------------------------------- #

def credit_estimate(engine_root: Path, task_count: int) -> dict[str, Any]:
    """Report how per-image credits are knowable, without inventing a number.

    Searched: configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json,
    configs/reroll_cost_guard_policy_v1_20260716.json, tools/giggle_api_client.py,
    tools/giggle_credit_statements.py and every tools/*credit* module.  None of
    them carries a per-image price.  Credits are only observable after the fact
    from the provider ledger.
    """
    probes = {
        "configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json": "no price/credit field; capability + provider limits only",
        "configs/reroll_cost_guard_policy_v1_20260716.json": "attempt caps and fractions only; no unit price",
        "tools/giggle_api_client.py": "transport only; no price table",
        "tools/giggle_credit_statements.py": (
            "reads /api/v1/payment/credit-statements after submission and divides the "
            "batch total by the successful item count (per_item is derived, never declared)"
        ),
    }
    missing = [name for name in probes if not (engine_root / name).is_file()]
    return {
        "planned_credits": "unknown_not_in_registry",
        "planned_image_task_count": task_count,
        "reason": (
            "No per-image credit constant exists in any engine registry or tool. "
            "Giggle credits for an image task are only knowable post-hoc from "
            "/api/v1/payment/credit-statements (giggle_credit_statements.reconcile_rows), "
            "which requires a real paid POST and GIGGLE_API_KEY. No number is invented here."
        ),
        "sources_probed": probes,
        "sources_missing": missing,
        "credit_discovery_route": (
            "after an authorized paid submit, submit_giggle_image_manifest writes "
            "<out>_credit_statement.json; charged_credits / successful_count yields the per-image rate"
        ),
    }


# --------------------------------------------------------------------------- #
# precheck
# --------------------------------------------------------------------------- #

def run_precheck(python: Path, engine_root: Path, manifest_path: Path, out_path: Path,
                 task_keys: list[str] | None = None) -> dict[str, Any]:
    submitter = engine_root / "tools/submit_giggle_image_manifest.py"
    if not submitter.is_file():
        return {"status": "SKIPPED", "reason": f"submitter not found: {submitter}"}
    command = [
        str(python), str(submitter),
        "--manifest", str(manifest_path),
        "--out", str(out_path),
        "--precheck-only",
    ]
    for key in task_keys or []:
        command += ["--task-key", key]
    environment = dict(os.environ)
    environment.pop("GIGGLE_API_KEY", None)
    completed = subprocess.run(
        command, cwd=str(engine_root), env=environment,
        capture_output=True, text=True, check=False,
    )
    report: dict[str, Any] = {
        "command": command,
        "cwd": str(engine_root),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr_tail": completed.stderr.strip().splitlines()[-4:] if completed.stderr.strip() else [],
        "report_path": str(out_path),
    }
    if out_path.is_file():
        try:
            written = load_json(out_path)
            report["summary"] = {
                key: written.get(key)
                for key in ("status", "submitted", "precheck_pass", "failed")
            }
        except json.JSONDecodeError:
            report["summary"] = None
    report["status"] = "PASS" if completed.returncode == 0 else "FAIL"
    return report


def precheck_each_task(python: Path, engine_root: Path, manifest_path: Path,
                       out_dir: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precheck one task at a time so every failure is attributed to its shot."""
    rows: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        key = str(task["task_key"])
        result = run_precheck(
            python, engine_root, manifest_path, out_dir / f"precheck_{key}.json", [key],
        )
        error = ""
        for line in reversed(result.get("stderr_tail") or []):
            if "Error" in line or "error" in line:
                error = line.strip()
                break
        rows.append({
            "task_key": key,
            "shot_id": task["shot_id"],
            "status": "PASS" if result["status"] == "PASS" else "FAIL",
            "error": error,
            "pending_bindings": [row["entity_id"] for row in task.get("pending_bindings") or []],
        })
    return rows


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def derived_opener_shot_ids(inputs: "Inputs") -> set[str]:
    """First shots of units whose opening_anchor_contract.source is CONTINUITY_DERIVED_KEYFRAME (D-68)."""
    try:
        plan = load_json(inputs.grouping_plan_path)
        anchors = inputs.anchor_plan
    except Exception:  # noqa: BLE001
        return set()
    first = {str(u.get("unit_id")): str((u.get("editorial_shot_ids") or [""])[0]) for u in plan.get("units") or []}
    out = set()
    for row in anchors.get("units") or []:
        oac = row.get("opening_anchor_contract") or {}
        if str(oac.get("source") or "") == "CONTINUITY_DERIVED_KEYFRAME" and first.get(str(row.get("unit_id"))):
            out.add(first[str(row.get("unit_id"))])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Giggle IMAGE manifest for one episode's per-shot keyframes.",
    )
    parser.add_argument("--episode", required=True, help="Episode id, e.g. E01")
    parser.add_argument("--preproduction-dir", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path,
                        help="Episode generation contract JSON (visual_culture_contract authority)")
    parser.add_argument("--asset-library", required=True, type=Path,
                        help="ai_drama.production_asset_library.v1 JSON; PENDING entries are allowed")
    parser.add_argument("--out", required=True, type=Path, help="Manifest output path")
    parser.add_argument("--precheck-only", action="store_true",
                        help="Run submit_giggle_image_manifest.py --precheck-only after writing the manifest")
    parser.add_argument("--locations-only", "--subset-existing-bindings-only", dest="locations_only",
                        action="store_true",
                        help="Emit only tasks whose every binding already exists (environment-only shots)")
    parser.add_argument("--report", type=Path, default=None,
                        help="Build report path; defaults to <out stem>_report.json")
    parser.add_argument("--prompt-dir", type=Path, default=None,
                        help="Prompt output dir; defaults to <out parent>/prompts/keyframes")
    parser.add_argument("--keyframe-dir", type=Path, default=None,
                        help="Flat keyframe destination; defaults to <preproduction-dir>/keyframes")
    parser.add_argument("--awaited-asset-dir", type=Path, default=None,
                        help="Directory where stage 3(a) will write identity/prop/scene plates; "
                             "defaults to <asset-library parent>/asset_library")
    parser.add_argument("--engine-root", type=Path, default=DEFAULT_ENGINE_ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--model", default="gpt-image-2-pro")
    parser.add_argument("--image-resolution", default="2K", choices=["1K", "2K"])
    parser.add_argument("--task-version", default="V1",
                        help="Portable task/output version such as V1 or V2; use a new value after a rejected attempt")
    args = parser.parse_args(argv)

    task_version = str(args.task_version).strip().upper()
    if not re.fullmatch(r"V[1-9][0-9]*", task_version):
        raise SystemExit("--task-version must match V1, V2, ...")

    episode = str(args.episode).strip().upper()
    engine_root = args.engine_root.resolve()
    out_path = args.out.resolve()
    report_path = (args.report or out_path.with_name(out_path.stem + "_report.json")).resolve()
    prompt_dir = (args.prompt_dir or out_path.parent / "prompts" / "keyframes").resolve()
    keyframe_dir = (args.keyframe_dir or args.preproduction_dir / "keyframes").resolve()

    inputs = Inputs(
        episode, args.preproduction_dir.resolve(), args.contract.resolve(),
        args.asset_library.resolve(), engine_root,
        args.awaited_asset_dir.resolve() if args.awaited_asset_dir else None,
    )
    gate_ref = inputs.scene_authority_gate_ref()

    decisions = decide_keyframes(inputs)
    # D-68 (Roger seq=36, 2026-09-18): a unit whose opening anchor is CONTINUITY_DERIVED_KEYFRAME starts
    # from the PREVIOUS unit's real final frame (materialised by the wave scheduler, reviewed by Q1 then),
    # so its opener is NOT generated here from text — E06's same-scene jump cuts came from exactly that
    # (text-generated openers that ignored the tail).  Secondary keyframes inside such units stay.
    derived_openers = derived_opener_shot_ids(inputs)
    deferred = [row for row in decisions if row["decision"] == "NEW_KEYFRAME" and str(row.get("shot_id")) in derived_openers]
    for row in deferred:
        row["decision"] = "DEFERRED_TO_PREVIOUS_UNIT_REAL_FINAL_FRAME"
        row["decision_basis"] = "D-68 continuity-derived opener: start frame = previous unit real tail"
    new_shots = [row for row in decisions if row["decision"] == "NEW_KEYFRAME"]
    reuse_shots = [row for row in decisions if row["decision"] != "NEW_KEYFRAME"]

    dropped_prompt_segments: list[dict[str, str]] = []
    all_tasks = [
        compile_task(inputs, row, prompt_dir, keyframe_dir, gate_ref,
                     args.model, args.image_resolution, dropped_prompt_segments, task_version)
        for row in new_shots
    ]
    selected = [task for task in all_tasks if task_is_fully_bound(task)] if args.locations_only else all_tasks
    if not selected:
        raise SystemExit("no tasks selected; nothing to write")

    manifest = build_manifest(inputs, selected, keyframe_dir, args.model,
                              args.image_resolution, args.locations_only)
    atomic_json(out_path, manifest)

    awaited: dict[str, list[str]] = {}
    deferred: dict[str, list[str]] = {}
    for task in all_tasks:
        rows = task.get("pending_bindings") or []
        if rows:
            awaited[str(task["task_key"])] = sorted({str(row["awaited_path"]) for row in rows})
        upgrades = task.get("deferred_binding_upgrades") or []
        if upgrades:
            deferred[str(task["task_key"])] = sorted({str(row["awaited_path"]) for row in upgrades})

    report: dict[str, Any] = {
        "schema": SCHEMA_REPORT,
        "episode": episode,
        "generated_at": utc_now(),
        "manifest": str(out_path),
        "manifest_sha256": sha256_file(out_path),
        "prompt_dir": str(prompt_dir),
        "keyframe_dir": str(keyframe_dir),
        "keyframe_naming_contract": "{shot_id}-keyframe-v{N}.png (flat dir)",
        "inputs": {
            "generation_contract": str(inputs.contract_path),
            "generation_contract_sha256": inputs.contract_sha256,
            "subspace_shot_plan": str(inputs.subspace_plan_path),
            "episode_global_space_map_authority": str(inputs.authority_path),
            "editorial_seedance_manifest": str(inputs.seedance_path),
            "video_unit_anchor_plan": str(inputs.anchor_plan_path),
            "video_unit_grouping_plan": str(inputs.grouping_plan_path),
            "asset_library": str(inputs.asset_library_path),
            "awaited_asset_dir": str(inputs.awaited_asset_dir),
            "asset_library_schema": inputs.asset_library.get("schema"),
        },
        "keyframe_policy": {
            "mode": "SEMANTIC_NOVELTY_ONLY_WITH_CROSS_EPISODE_REUSE",
            "one_keyframe_per_editorial_shot_forbidden": True,
            "generate_new_only_for": list(NOVELTY_CLASSES),
            "cross_episode_reuse": (
                "NONE_AVAILABLE: this is the first episode, so no earlier episode has admitted keyframes"
                if episode_ordinal(episode) == 1
                else "CHECK_EARLIER_EPISODE_KEYFRAME_LIBRARY_FOR_EXACT_SHA_REUSE_BEFORE_PAID_SUBMIT"
            ),
            "non_interpolable_dimension_rule": sorted(NON_INTERPOLABLE_DIMENSIONS),
        },
        "decision_summary": {
            "editorial_shot_count": len(decisions),
            "new_keyframes": len(new_shots),
            "reuse_no_new_keyframe": len(reuse_shots),
            "reuse_modes": {
                mode: sum(1 for row in reuse_shots if row.get("reuse_mode") == mode)
                for mode in sorted({str(row.get("reuse_mode")) for row in reuse_shots})
            },
            "novelty_class_counts": {
                name: sum(1 for row in new_shots if name in (row.get("novelty_classes") or []))
                for name in NOVELTY_CLASSES
            },
            "one_keyframe_per_editorial_shot": len(new_shots) == len(decisions),
        },
        "decision_table": decisions,
        "tasks_emitted": [task["task_key"] for task in selected],
        "tasks_withheld_from_this_manifest": [
            task["task_key"] for task in all_tasks if task not in selected
        ],
        "awaited_identity_files_by_task": awaited,
        "awaited_identity_files_unique": sorted({p for rows in awaited.values() for p in rows}),
        "deferred_scene_plate_upgrades_by_task": deferred,
        "deferred_scene_plate_upgrades_unique": sorted({p for rows in deferred.values() for p in rows}),
        "deferred_scene_plate_note": (
            "These tasks currently satisfy the exactly-one-scene-reference rule with the shot's "
            "own rendered subspace topology plate (file exists, SHA verifies, QA PASS). They do "
            "not block precheck; rebuild after stage 3(a) to bind the real LOC plate."
        ),
        "scene_reference_policy": (
            "submit_giggle_image_manifest.validate_task requires exactly one scene/destination_scene "
            "binding. Until the stage-3(a) LOC plate is registered, the shot's own rendered subspace "
            "topology plate carries the role, labelled FALLBACK_LOCAL_TOPOLOGY_RENDER, matching the "
            "already-passing stage-3(a) location tasks."
        ),
        "dropped_prompt_segments": dropped_prompt_segments,
        "dropped_prompt_segments_note": (
            "Optional decorative lines whose authored source text carried an extend-word "
            "(持续/保持/连续) or a completion_state / primary_action substring are dropped from the still "
            "prompt rather than rewritten. "
            "Required authority lines are never dropped; they hard-fail the build instead."
        ),
        "credits": credit_estimate(engine_root, len(selected)),
    }

    if args.precheck_only:
        batch_out = report_path.parent / f"{out_path.stem}_precheck.json"
        report["precheck_batch"] = run_precheck(
            args.python.resolve(), engine_root, out_path, batch_out,
        )
        report["precheck_per_task"] = precheck_each_task(
            args.python.resolve(), engine_root, out_path,
            report_path.parent / f"{out_path.stem}_precheck_per_task", selected,
        )
        rows = report["precheck_per_task"]
        report["precheck_summary"] = {
            "tasks_checked": len(rows),
            "pass": sorted(row["task_key"] for row in rows if row["status"] == "PASS"),
            "fail": [
                {"task_key": row["task_key"], "error": row["error"],
                 "pending_bindings": row["pending_bindings"]}
                for row in rows if row["status"] == "FAIL"
            ],
            "pass_count": sum(1 for row in rows if row["status"] == "PASS"),
            "fail_count": sum(1 for row in rows if row["status"] == "FAIL"),
        }

    atomic_json(report_path, report)
    print(json.dumps({
        "manifest": str(out_path),
        "report": str(report_path),
        "editorial_shots": len(decisions),
        "new_keyframes": len(new_shots),
        "reuse": len(reuse_shots),
        "tasks_emitted": len(selected),
        "precheck": (report.get("precheck_summary") or {}).get("pass_count")
        if args.precheck_only else None,
        "planned_credits": report["credits"]["planned_credits"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
