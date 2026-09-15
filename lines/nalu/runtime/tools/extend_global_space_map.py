#!/usr/bin/env python3
"""Extend the series global space map for one episode (open decision D-10, GSM half).

Replaces the zero-argument, E01-hardcoded
``preproduction/E01/tools/build_global_space_map.py``.

What it does
------------
1. Deep-copies ``--base-gsm`` (E01's LOCKED
   ``qingshan.episode_global_space_map.v1`` authority).  Every existing
   ``global_space_map_id`` / ``room_id`` / ``zone_id`` / ``angle_id`` / ``axis_id`` /
   ``element_id`` and all existing geometry is carried through unchanged.
2. Reads ``--contract`` (and ``--manifest`` when given) and works out which
   ``scene_states[].location_id`` values the base map does **not** cover.  For each
   NEW location it authors a place map: one room bound to the ``location_id``, a
   three-band zone split with real polygons in the series coordinate system, fixed
   elements, an entrance, a movement axis, and **one camera position per shot in
   that location** whose ``name`` declares the shot id — the annotation
   ``build_nalu_preproduction.py`` reads in ``SpaceIndex.angle_shot_hints`` /
   ``choose_angle`` (``re.findall(r"S\\d+-\\d+", camera["name"])``, matched against
   the shot-id suffix), exactly the way E01's GSM writes
   ``"固定高机位俯瞰全村（E01-S01-01）"``.
3. For locations the base map already covers, appends this episode's
   ``scene_mappings`` (``build_nalu_preproduction`` hard-fails on an unmapped
   ``scene_id``) and re-annotates the existing camera positions with **this**
   episode's shot ids, stripping other episodes' shot-id annotations so
   ``choose_angle`` cannot alias E02's ``S01-01`` onto E01's camera.  ``angle_id``
   never changes — only the human-readable ``name``, which the renderer does not
   draw, so the place-map PNGs stay bit-identical.
4. Recomputes ``topology_sha256`` with the engine's own
   ``global_space_layout_gate.content_sha256``, sets ``inheritance`` to
   ``INHERITED_EXACT`` when nothing about the topology moved and ``COMPOSED``
   otherwise, then shells out to
   ``tools/render_global_space_map_assets.py`` (deterministic, offline, PIL only)
   to render the episode sheet + every place map and bind their real SHA256, and to
   ``tools/global_space_layout_gate.py`` to prove ``status: PASS``.

Identity case
-------------
``--episode`` equal to the base GSM's own ``episode`` is the identity operation:
no camera name is rewritten, no scene mapping is appended, and because
``render_global_space_map_assets.py`` is bit-deterministic the emitted authority is
**byte-identical** to ``--base-gsm``.

CLI
---
    extend_global_space_map.py \
      --episode E02 \
      --contract $ENGINE_ROOT/workflow/claude_writer_agent/scripts/E02_GENERATION_CONTRACT_v1.json \
      --base-gsm $RUNTIME_ROOT/preproduction/E01/global_space_map.json \
      --out      $RUNTIME_ROOT/preproduction/E02/global_space_map.json \
      [--manifest <EP>_manifest_v1.json]        # episode_global_space_map_id / axis_note
      [--asset-requirements <EP>/asset_requirements.json]  # authored key_fixed_elements
      [--place-spec <json>]                     # authored siting for new locations
      [--asset-dir  <dir>]      default <out dir>/space_map_assets
      [--reports-dir <dir>]     default <out dir>/reports
      [--engine-root $ENGINE_ROOT] [--python <venv python>]
      [--authority-ref REF] [--skip-render] [--skip-gate]

``--place-spec`` (optional, schema ``nalu.new_location_place_spec.v1``) is how a
human sites a new location instead of accepting the tool's deterministic
auto-siting::

    {"schema": "nalu.new_location_place_spec.v1",
     "locations": {"LOC-X-EXT": {"label": "…", "origin": [220, 0], "width": 60, "depth": 48,
                                 "zone_names": ["…","…","…"],
                                 "fixed_elements": ["…","…"]}}}

Auto-sited locations are reported as ``AUTO_SITED_REQUIRES_SPATIAL_REVIEW``: the
geometry is valid and gate-clean, but where the place sits relative to the rest of
the village is a directorial call the tool does not pretend to make.

Exit codes: 0 PASS, 2 bad input, 4 the render or the space gate did not PASS.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import copy
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_ENGINE_ROOT = Path(f"{_np.ENGINE_ROOT}")
DEFAULT_PYTHON = DEFAULT_ENGINE_ROOT / ".qingshan-venv/bin/python"
SHOT_TOKEN = re.compile(r"S\d+-\d+")
EPISODE_SHOT = re.compile(r"(E\d+)-(S\d+-\d+)")
PLACE_KIND = "PLACE_TOP_DOWN_COMPLETE_SPACE_MAP"
HEIGHT_BY_SHOT_SIZE = {
    "大远景": 18.0, "远景": 6.0, "全景": 2.2, "中景": 1.6,
    "中近景": 1.6, "近景": 1.6, "特写": 1.5, "大特写": 1.5,
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def content_sha256_fn(engine_root: Path):
    if str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))
    from tools.global_space_layout_gate import content_sha256  # noqa: PLC0415
    return content_sha256


def shot_suffix(shot_id: str) -> str:
    match = re.search(r"(S\d+-\d+)$", shot_id)
    return match.group(1) if match else shot_id


def slug(location_id: str) -> str:
    return re.sub(r"^LOC-", "", location_id)


# --------------------------------------------------------------------------- #
# base map index
# --------------------------------------------------------------------------- #
class BaseIndex:
    def __init__(self, gsm: dict[str, Any]) -> None:
        self.gsm = gsm
        self.location_place: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.ids: set[str] = set()
        self.max_x = 0.0
        self.max_y = 0.0
        for place in gsm.get("space_maps") or []:
            self.ids.add(str(place.get("global_space_map_id")))
            for room in place.get("rooms") or []:
                self.ids.add(str(room.get("room_id")))
                if room.get("location_id"):
                    self.location_place[str(room["location_id"])] = (place, room)
                for zone in room.get("zones") or []:
                    self.ids.add(str(zone.get("zone_id")))
                    for point in zone.get("polygon") or []:
                        self.max_x = max(self.max_x, float(point[0]))
                        self.max_y = max(self.max_y, float(point[1]))
                for element in room.get("fixed_elements") or []:
                    self.ids.add(str(element.get("element_id")))
                for entrance in room.get("entrances") or []:
                    self.ids.add(str(entrance.get("entrance_id")))
                for axis in room.get("axes") or []:
                    self.ids.add(str(axis.get("axis_id")))
                for camera in room.get("camera_positions") or []:
                    self.ids.add(str(camera.get("angle_id")))
            for mapping in place.get("scene_mappings") or []:
                rooms = {str(r.get("room_id")): r for r in place.get("rooms") or []}
                room = rooms.get(str(mapping.get("room_id")))
                if room is not None:
                    self.location_place.setdefault(str(mapping["location_id"]), (place, room))


# --------------------------------------------------------------------------- #
# new place map authoring
# --------------------------------------------------------------------------- #
def author_place_map(
    location_id: str,
    *,
    label: str,
    shots: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    coordinate_system: dict[str, Any],
    origin: tuple[float, float],
    width: float,
    depth: float,
    zone_names: list[str],
    element_names: list[str],
    project_slug: str,
) -> dict[str, Any]:
    key = slug(location_id)
    place_id = f"GSM-{project_slug}-{key}"
    room_id = f"ROOM-{key}"
    x0, y0 = origin
    band = depth / max(len(zone_names), 1)
    zones: list[dict[str, Any]] = []
    for index, name in enumerate(zone_names):
        low = round(y0 + band * index, 2)
        high = round(y0 + band * (index + 1), 2)
        zones.append({
            "zone_id": f"ZONE-{key}-{index + 1}",
            "name": name,
            "polygon": [
                [round(x0, 2), low], [round(x0 + width, 2), low],
                [round(x0 + width, 2), high], [round(x0, 2), high],
            ],
        })

    def centroid(zone: dict[str, Any]) -> list[float]:
        points = zone["polygon"]
        return [
            round(sum(p[0] for p in points) / len(points), 2),
            round(sum(p[1] for p in points) / len(points), 2),
        ]

    fixed_elements = []
    for index, name in enumerate(element_names):
        zone = zones[index % len(zones)]
        fixed_elements.append({
            "element_id": f"FIXED-{key}-{index + 1}",
            "name": name,
            "zone_id": zone["zone_id"],
            "position": centroid(zone),
        })
    entrances = [{
        "entrance_id": f"ENTRY-{key}-SOUTH",
        "zone_id": zones[0]["zone_id"],
        "position": [round(x0 + width / 2, 2), round(y0, 2)],
    }]
    axis_id = f"AXIS-{key}-SOUTH-NORTH"
    axes = [{
        "axis_id": axis_id,
        "name": f"{label}：自南进入，向北推进（不得折返）",
        "endpoint_a": [round(x0 + width / 2, 2), round(y0, 2)],
        "endpoint_b": [round(x0 + width / 2, 2), round(y0 + depth, 2)],
        "default_screen_direction": "A_BOTTOM_B_TOP",
        "crossing_policy": "NO_CROSS",
    }]
    cameras = []
    for index, shot in enumerate(shots):
        shot_id = str(shot["shot_id"])
        size = str(shot.get("shot_size") or "中景")
        zone = zones[min(index, len(zones) - 1)] if len(shots) <= len(zones) else zones[index % len(zones)]
        position = centroid(zone)
        cameras.append({
            "angle_id": f"ANGLE-{key}-{index + 1:02d}",
            "name": f"{size}／{shot.get('camera') or '固定机位'}（{shot_id}）",
            "zone_id": zone["zone_id"],
            "position": [position[0], round(position[1] - band / 3, 2)],
            "facing": "north",
            "axis_id": axis_id,
            "screen_direction": "A_BOTTOM_B_TOP",
            "height_m": HEIGHT_BY_SHOT_SIZE.get(size, 1.6),
        })
    if not cameras:  # a location with no shot still needs one declared angle
        cameras.append({
            "angle_id": f"ANGLE-{key}-01",
            "name": f"中景／固定机位（{location_id} 基准）",
            "zone_id": zones[0]["zone_id"],
            "position": centroid(zones[0]),
            "facing": "north",
            "axis_id": axis_id,
            "screen_direction": "A_BOTTOM_B_TOP",
            "height_m": 1.6,
        })
    return {
        "global_space_map_id": place_id,
        "map_version": 1,
        "name": label,
        "coordinate_system": coordinate_system,
        "overall_bounds": {
            "width": math.ceil(x0 + width + width * 0.1),
            "depth": math.ceil(y0 + depth + depth * 0.1),
        },
        "layout_image": {
            "kind": PLACE_KIND, "path": "PENDING_RENDER",
            "sha256": "PENDING_RENDER", "qa_status": "PENDING",
            "render_status": "NOT_YET_GENERATED",
        },
        "rooms": [{
            "room_id": room_id,
            "name": label,
            "location_id": location_id,
            "zones": zones,
            "fixed_elements": fixed_elements,
            "entrances": entrances,
            "axes": axes,
            "camera_positions": cameras,
        }],
        "scene_mappings": [
            {
                "scene_id": str(scene["scene_id"]), "location_id": location_id,
                "room_id": room_id, "zone_ids": [zone["zone_id"] for zone in zones],
            }
            for scene in scenes
        ],
        "subspaces": [],
    }


# --------------------------------------------------------------------------- #
# camera-name annotation for reused locations
# --------------------------------------------------------------------------- #
def annotate_existing_cameras(
    room: dict[str, Any], shots: list[dict[str, Any]], episode: str,
) -> list[dict[str, Any]]:
    """Bind this episode's shots to the room's declared angles, rewriting names."""
    cameras = room.get("camera_positions") or []
    if not cameras:
        return []
    order = sorted(cameras, key=lambda row: str(row.get("angle_id")))
    assigned: dict[str, list[str]] = {str(row["angle_id"]): [] for row in cameras}
    rewrites: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        target = order[index % len(order)]
        assigned[str(target["angle_id"])].append(str(shot["shot_id"]))
    for camera in cameras:
        angle_id = str(camera["angle_id"])
        before = str(camera.get("name") or "")
        # Drop every trailing parenthesised group that only holds shot ids, so a
        # prior episode's annotation cannot alias onto this episode's suffixes.
        core = re.sub(r"（[^（）]*S\d+-\d+[^（）]*）", "", before).strip()
        shot_ids = assigned[angle_id]
        # D-33: an inherited angle keeps its position, but its label must describe THIS episode's bound shot —
        # the label is copied into the keyframe prompt as 机位说明 (E02's "缓慢推近双眼" was landing on an E03 knife close-up).
        bound = [s for s in shots if str(s.get("shot_id")) in shot_ids]
        if bound:
            descs = []
            for s in bound:
                d = "／".join(str(x) for x in (s.get("shot_size"), s.get("camera")) if x)
                if d and d not in descs:
                    descs.append(d)
            core = "；".join(descs) or core
        after = f"{core}（{'、'.join(shot_ids)}）" if shot_ids else f"{core}（{episode} 未使用）"
        camera["name"] = after
        rewrites.append({
            "angle_id": angle_id, "name_before": before, "name_after": after,
            "bound_shot_ids": shot_ids,
        })
    return rewrites


# --------------------------------------------------------------------------- #
def build(args: argparse.Namespace) -> dict[str, Any]:
    episode = args.episode
    engine_root = Path(args.engine_root).resolve()
    base_path = Path(args.base_gsm).resolve()
    contract_path = Path(args.contract).resolve()
    out_path = Path(args.out).resolve()
    for label, path in (("--base-gsm", base_path), ("--contract", contract_path)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")

    base = load_json(base_path)
    if base.get("schema") != "qingshan.episode_global_space_map.v1":
        raise SystemExit("--base-gsm is not a qingshan.episode_global_space_map.v1 authority")
    contract = load_json(contract_path)
    manifest = load_json(Path(args.manifest).resolve()) if args.manifest else {}
    requirements = load_json(Path(args.asset_requirements).resolve()) if args.asset_requirements else {}
    place_spec = load_json(Path(args.place_spec).resolve()) if args.place_spec else {}

    base_episode = str(base.get("episode") or "")
    identity_mode = base_episode == episode
    index = BaseIndex(base)
    coordinate_system = (base.get("space_maps") or [{}])[0].get("coordinate_system") or {
        "origin": "series origin", "x_axis": "east", "y_axis": "north", "unit": "m",
    }
    project_slug = str(base.get("episode_global_space_map_id") or "GSM-X-Y").split("-")[1]

    scenes_by_location: dict[str, list[dict[str, Any]]] = {}
    for state in contract.get("scene_states") or []:
        scenes_by_location.setdefault(str(state["location_id"]), []).append(state)
    scene_location = {str(s["scene_id"]): str(s["location_id"]) for s in contract.get("scene_states") or []}
    shots_by_location: dict[str, list[dict[str, Any]]] = {}
    for shot in contract.get("shots") or []:
        location = scene_location.get(str(shot["scene_id"]))
        if location is None:
            raise SystemExit(f"{shot['shot_id']}: scene {shot['scene_id']} has no scene_state")
        shots_by_location.setdefault(location, []).append(shot)

    declared = list(manifest.get("distinct_locations") or sorted(scenes_by_location))
    new_locations = [loc for loc in declared if loc not in index.location_place]
    reused_locations = [loc for loc in declared if loc in index.location_place]

    template = copy.deepcopy(base)
    template["episode"] = episode
    if manifest.get("episode_global_space_map_id"):
        template["episode_global_space_map_id"] = manifest["episode_global_space_map_id"]
    if args.authority_ref:
        template["authority_ref"] = args.authority_ref
    refs = manifest.get("global_space_map_refs") or []
    manifest_axis = (refs[0].get("axis_note") if refs else None) or ""
    # The authored GSM axis_note is allowed to be a strict elaboration of the
    # manifest's (E01 appends "（+y 单调递增）"). Only replace it when the base note
    # is not already a superset, so re-running for the base episode is a no-op.
    if manifest_axis and not str(template.get("axis_note") or "").startswith(manifest_axis):
        template["axis_note"] = manifest_axis

    report: dict[str, Any] = {
        "schema": "nalu.global_space_map_extension_report.v1",
        "episode": episode,
        "base_gsm": str(base_path),
        "base_episode": base_episode,
        "mode": "IDENTITY_SAME_EPISODE_AS_BASE" if identity_mode else "EXTEND",
        "new_locations": new_locations,
        "reused_locations": reused_locations,
        "new_place_maps": [],
        "camera_name_rewrites": [],
        "scene_mappings_added": [],
        "auto_sited": [],
    }

    if not identity_mode:
        # --- reused locations: append this episode's scene mappings + annotate ---
        for loc in reused_locations:
            place, room = None, None
            for candidate in template.get("space_maps") or []:
                for candidate_room in candidate.get("rooms") or []:
                    if str(candidate_room.get("location_id")) == loc:
                        place, room = candidate, candidate_room
                if place is not None:
                    break
            if place is None:
                base_place, base_room = index.location_place[loc]
                place = next(
                    row for row in template["space_maps"]
                    if row["global_space_map_id"] == base_place["global_space_map_id"]
                )
                room = next(
                    row for row in place["rooms"]
                    if row["room_id"] == base_room["room_id"]
                )
            existing_scene_ids = {str(m.get("scene_id")) for m in place.get("scene_mappings") or []}
            zone_ids = [str(zone["zone_id"]) for zone in room.get("zones") or []]
            for state in scenes_by_location.get(loc, []):
                scene_id = str(state["scene_id"])
                if scene_id in existing_scene_ids:
                    continue
                place.setdefault("scene_mappings", []).append({
                    "scene_id": scene_id, "location_id": loc,
                    "room_id": str(room["room_id"]), "zone_ids": zone_ids,
                })
                report["scene_mappings_added"].append({
                    "scene_id": scene_id, "location_id": loc,
                    "global_space_map_id": place["global_space_map_id"],
                    "room_id": str(room["room_id"]),
                })
            rewrites = annotate_existing_cameras(room, shots_by_location.get(loc, []), episode)
            report["camera_name_rewrites"].extend(
                {"location_id": loc, **row} for row in rewrites
            )

        # ------------------------------ new locations: author a place map ------
        cursor_x = math.ceil(index.max_x / 20.0) * 20 + 40
        scene_labels = {
            row["asset_id"]: row for row in ((requirements.get("assets") or {}).get("scenes") or [])
        }
        for loc in new_locations:
            authored = (place_spec.get("locations") or {}).get(loc) or {}
            label = authored.get("label") or (scene_labels.get(loc) or {}).get("label") or loc
            zone_names = authored.get("zone_names") or [
                f"{label}｜南侧进路", f"{label}｜中心", f"{label}｜北侧纵深",
            ]
            elements = (
                authored.get("fixed_elements")
                or ((scene_labels.get(loc) or {}).get("specification") or {}).get("key_fixed_elements")
                or [f"{label}｜固定参照物"]
            )
            width = float(authored.get("width") or 48)
            depth = float(authored.get("depth") or 40)
            if authored.get("origin"):
                origin = (float(authored["origin"][0]), float(authored["origin"][1]))
                sited = "AUTHORED_IN_PLACE_SPEC"
            else:
                origin = (float(cursor_x), 0.0)
                cursor_x += width + 40
                sited = "AUTO_SITED_REQUIRES_SPATIAL_REVIEW"
                report["auto_sited"].append({
                    "location_id": loc, "origin": list(origin),
                    "width": width, "depth": depth,
                    "note": "Geometry is valid and gate-clean; where the place sits relative "
                            "to the rest of the village is a directorial call. Author it in "
                            "--place-spec to override.",
                })
            place = author_place_map(
                loc, label=label, shots=shots_by_location.get(loc, []),
                scenes=scenes_by_location.get(loc, []),
                coordinate_system=coordinate_system, origin=origin,
                width=width, depth=depth, zone_names=list(zone_names),
                element_names=list(elements), project_slug=project_slug,
            )
            collisions = sorted(
                {place["global_space_map_id"], place["rooms"][0]["room_id"]}
                | {z["zone_id"] for z in place["rooms"][0]["zones"]}
                | {c["angle_id"] for c in place["rooms"][0]["camera_positions"]}
                | {a["axis_id"] for a in place["rooms"][0]["axes"]}
                | {e["element_id"] for e in place["rooms"][0]["fixed_elements"]}
                | {e["entrance_id"] for e in place["rooms"][0]["entrances"]}
            )
            clash = [value for value in collisions if value in index.ids]
            if clash:
                raise SystemExit(
                    f"{loc}: derived ids collide with the base map: {', '.join(clash)}"
                )
            index.ids.update(collisions)
            template["space_maps"].append(place)
            report["new_place_maps"].append({
                "location_id": loc,
                "global_space_map_id": place["global_space_map_id"],
                "room_id": place["rooms"][0]["room_id"],
                "zone_ids": [z["zone_id"] for z in place["rooms"][0]["zones"]],
                "angle_ids": [
                    {"angle_id": c["angle_id"], "name": c["name"]}
                    for c in place["rooms"][0]["camera_positions"]
                ],
                "scene_ids": [m["scene_id"] for m in place["scene_mappings"]],
                "siting": sited,
            })

    content_sha256 = content_sha256_fn(engine_root)
    template["topology_sha256"] = content_sha256(template["space_maps"])
    topology_unchanged = template["topology_sha256"] == base.get("topology_sha256")
    if identity_mode:
        pass  # carry the base inheritance block through untouched
    elif topology_unchanged:
        template["inheritance"] = {
            "mode": "INHERITED_EXACT",
            "source_episode": base.get("episode"),
            "source_authority_path": str(base_path),
            "source_authority_sha256": __import__("hashlib").sha256(base_path.read_bytes()).hexdigest(),
            "source_episode_global_space_map_id": base.get("episode_global_space_map_id"),
            "source_map_version": base.get("map_version"),
            "source_topology_sha256": base.get("topology_sha256"),
            "source_map_image_sha256": (base.get("map_image") or {}).get("sha256"),
        }
    else:
        template["inheritance"] = {
            "mode": "COMPOSED",
            "composed_from": {
                "source_episode": base.get("episode"),
                "source_authority_path": str(base_path),
                "source_authority_sha256": __import__("hashlib").sha256(base_path.read_bytes()).hexdigest(),
                "source_topology_sha256": base.get("topology_sha256"),
                "added_place_maps": [row["global_space_map_id"] for row in report["new_place_maps"]],
                "added_scene_mappings": len(report["scene_mappings_added"]),
                "camera_names_reannotated": len(report["camera_name_rewrites"]),
            },
        }
    template["status"] = "DRAFT_PENDING_MAP_IMAGE_RENDER"
    report["topology_sha256_pre_render"] = template["topology_sha256"]
    report["inheritance_mode"] = template["inheritance"].get("mode")

    # ------------------------------------------------------------- render + gate
    out_dir = out_path.parent
    asset_dir = Path(args.asset_dir).resolve() if args.asset_dir else out_dir / "space_map_assets"
    reports_dir = Path(args.reports_dir).resolve() if args.reports_dir else out_dir / "reports"
    template_path = out_dir / f"{out_path.stem}.template.json"
    dump_json(template_path, template)
    shot_plan_path = reports_dir / f"gsm_shot_plan_empty_{episode}.json"
    dump_json(shot_plan_path, {
        "schema": "qingshan.global_space_map_shot_plan.v1",
        "episode": episode, "tasks": [],
        "note": ("Empty on purpose. Per-shot subspace rendering is stage 1.4 and needs each "
                 "shot's subspace polygon + blocking; build_nalu_preproduction.py authors those "
                 "downstream. Rendering with zero tasks still renders the episode sheet and "
                 "every place map and locks the authority."),
    })
    report["template"] = str(template_path)
    report["shot_plan"] = str(shot_plan_path)

    # Never resolve(): .qingshan-venv/bin/python is a symlink to the base
    # interpreter and resolving it silently leaves the virtualenv (no PIL).
    python = Path(args.python) if args.python else DEFAULT_PYTHON
    if args.skip_render:
        report["render"] = "SKIPPED"
        report["status"] = "TEMPLATE_ONLY"
        return report
    render_cmd = [
        str(python), str(engine_root / "tools/render_global_space_map_assets.py"),
        "--authority-template", str(template_path),
        "--shot-plan", str(shot_plan_path),
        "--asset-dir", str(asset_dir),
        "--authority-out", str(out_path),
        "--shot-plan-out", str(reports_dir / f"gsm_shot_plan_rendered_{episode}.json"),
        "--receipt", str(reports_dir / f"global_space_map_render_receipt_{episode}.json"),
    ]
    rendered = subprocess.run(render_cmd, cwd=str(engine_root), capture_output=True, text=True)
    report["render_argv"] = render_cmd
    report["render_stdout"] = rendered.stdout.strip()
    report["render_stderr"] = rendered.stderr.strip()[-2000:]
    if rendered.returncode != 0:
        report["status"] = "RENDER_FAILED"
        return report

    if args.skip_gate:
        report["gate"] = "SKIPPED"
        report["status"] = "RENDERED_GATE_SKIPPED"
        return report
    gate_config = reports_dir / f"gsm_gate_config_{episode}.json"
    dump_json(gate_config, {
        "episode": episode, "global_space_map_gate_required": True, "tasks": [],
        "note": ("Authority-only probe. global_space_map_gate_required=true forces evaluation "
                 "so the authored topology is validated now rather than at E40."),
    })
    gate_out = reports_dir / f"global_space_layout_gate_{episode}.json"
    gate_cmd = [
        str(python), str(engine_root / "tools/global_space_layout_gate.py"),
        "--authority", str(out_path), "--config", str(gate_config), "--out", str(gate_out),
    ]
    gated = subprocess.run(gate_cmd, cwd=str(engine_root), capture_output=True, text=True)
    report["gate_argv"] = gate_cmd
    report["gate_report"] = str(gate_out)
    report["gate_stdout"] = gated.stdout.strip()[-2000:]
    report["gate_stderr"] = gated.stderr.strip()[-2000:]
    verdict = load_json(gate_out) if gate_out.is_file() else {}
    report["gate_status"] = verdict.get("status")
    report["gate_authority_status"] = verdict.get("authority_status")
    report["gate_failures"] = verdict.get("failures") or []
    report["out"] = str(out_path)
    final = load_json(out_path) if out_path.is_file() else {}
    report["topology_sha256"] = final.get("topology_sha256")
    report["space_map_ids"] = [row.get("global_space_map_id") for row in final.get("space_maps") or []]
    report["status"] = "PASS" if verdict.get("status") == "PASS" else "GATE_FAILED"
    if identity_mode and out_path.is_file():
        report["byte_identical_to_base"] = out_path.read_bytes() == base_path.read_bytes()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--episode", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--base-gsm", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--asset-requirements")
    parser.add_argument("--place-spec")
    parser.add_argument("--asset-dir")
    parser.add_argument("--reports-dir")
    parser.add_argument("--engine-root", default=str(DEFAULT_ENGINE_ROOT))
    parser.add_argument("--python", default=str(DEFAULT_PYTHON))
    parser.add_argument("--authority-ref")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-gate", action="store_true")
    parser.add_argument("--report-out")
    args = parser.parse_args()

    report = build(args)
    report_path = (
        Path(args.report_out).resolve() if args.report_out
        else Path(args.out).resolve().parent / "reports" / f"global_space_map_extension_{args.episode}.json"
    )
    dump_json(report_path, report)
    print(json.dumps({
        "status": report["status"],
        "mode": report["mode"],
        "episode": report["episode"],
        "new_locations": report["new_locations"],
        "new_place_maps": [row["global_space_map_id"] for row in report["new_place_maps"]],
        "scene_mappings_added": len(report["scene_mappings_added"]),
        "camera_names_reannotated": len(report["camera_name_rewrites"]),
        "inheritance_mode": report.get("inheritance_mode"),
        "gate_status": report.get("gate_status"),
        "gate_failures": len(report.get("gate_failures") or []),
        "topology_sha256": report.get("topology_sha256"),
        "byte_identical_to_base": report.get("byte_identical_to_base"),
        "out": report.get("out"),
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"PASS", "TEMPLATE_ONLY", "RENDERED_GATE_SKIPPED"} else 4


if __name__ == "__main__":
    sys.exit(main())
