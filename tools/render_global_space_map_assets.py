#!/usr/bin/env python3
"""Render deterministic episode/place/subspace maps and lock their SHA chain.

The renderer never invents topology. It consumes an authority template plus a
shot-layout plan, rasterizes those coordinates, and emits a locked authority
and per-shot plan whose media references can be checked by
``global_space_layout_gate.py`` before paid image or video submission.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

try:
    from global_space_layout_gate import content_sha256
except ModuleNotFoundError:
    from tools.global_space_layout_gate import content_sha256


ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1600, 2200)
MARGIN = (170, 230, 170, 180)
ZONE_COLORS = (
    (166, 204, 229, 82), (244, 196, 128, 82), (182, 221, 162, 82),
    (202, 177, 224, 82), (239, 170, 170, 82), (132, 199, 187, 82),
    (217, 217, 217, 82),
)


def abs_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size, index=1 if bold and candidate.endswith(".ttc") else 0)
            except OSError:
                continue
    return ImageFont.load_default()


def transform(point: list[float], width: float, depth: float) -> tuple[int, int]:
    left, top, right, bottom = MARGIN
    usable_w = CANVAS[0] - left - right
    usable_h = CANVAS[1] - top - bottom
    x = left + point[0] / width * usable_w
    y = CANVAS[1] - bottom - point[1] / depth * usable_h
    return round(x), round(y)


def polygon(points: list[list[float]], width: float, depth: float) -> list[tuple[int, int]]:
    return [transform(point, width, depth) for point in points]


def draw_arrow(draw: ImageDraw.ImageDraw, points: list[list[float]], width: float, depth: float, color: tuple[int, ...], line_width: int = 9) -> None:
    if len(points) < 2:
        return
    mapped = polygon(points, width, depth)
    draw.line(mapped, fill=color, width=line_width, joint="curve")
    end = mapped[-1]
    previous = mapped[-2]
    dx, dy = end[0] - previous[0], end[1] - previous[1]
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    left = (round(end[0] - ux * 30 - uy * 15), round(end[1] - uy * 30 + ux * 15))
    right = (round(end[0] - ux * 30 + uy * 15), round(end[1] - uy * 30 - ux * 15))
    draw.polygon([end, left, right], fill=color)


def render_map(
    space_map: dict[str, Any], destination: Path, *, title: str,
    subspace: dict[str, Any] | None = None, blocking: dict[str, Any] | None = None,
    end_blocking: dict[str, Any] | None = None, trajectories: list[dict[str, Any]] | None = None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", CANVAS, (242, 239, 230))
    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    layer = ImageDraw.Draw(overlay, "RGBA")
    width = float((space_map.get("overall_bounds") or {})["width"])
    depth = float((space_map.get("overall_bounds") or {})["depth"])
    title_font, body_font, small_font = font(48, True), font(27), font(21)
    draw.text((80, 60), title, font=title_font, fill=(34, 39, 45))
    draw.text((80, 130), f"GLOBAL-SPACE-MAP-ID: {space_map.get('global_space_map_id')}  v{space_map.get('map_version')}", font=body_font, fill=(63, 70, 78))
    bounds = polygon([[0, 0], [width, 0], [width, depth], [0, depth]], width, depth)
    draw.line(bounds + [bounds[0]], fill=(41, 47, 53), width=7)

    rooms = space_map.get("rooms") or []
    for room in rooms:
        for index, zone in enumerate(room.get("zones") or []):
            points = polygon(zone["polygon"], width, depth)
            layer.polygon(points, fill=ZONE_COLORS[index % len(ZONE_COLORS)], outline=(70, 75, 80, 210), width=3)
            centroid = (
                sum(point[0] for point in points) // len(points),
                sum(point[1] for point in points) // len(points),
            )
            draw.text((centroid[0] - 85, centroid[1] - 22), zone.get("name") or zone["zone_id"], font=small_font, fill=(41, 47, 53))
        for element in room.get("fixed_elements") or []:
            x, y = transform(element["position"], width, depth)
            color = (122, 56, 46) if not element.get("traversable") else (43, 112, 89)
            draw.rectangle((x - 14, y - 14, x + 14, y + 14), fill=color, outline=(255, 255, 255), width=2)
            draw.text((x + 20, y - 14), element.get("type") or element["element_id"], font=small_font, fill=(56, 47, 42))
        for entrance in room.get("entrances") or []:
            x, y = transform(entrance["position"], width, depth)
            draw.ellipse((x - 17, y - 17, x + 17, y + 17), fill=(36, 123, 160), outline=(255, 255, 255), width=3)
            draw.text((x + 22, y - 14), entrance["entrance_id"], font=small_font, fill=(36, 75, 95))
        for axis in room.get("axes") or []:
            draw_arrow(draw, [axis["endpoint_a"], axis["endpoint_b"]], width, depth, (96, 69, 145), 5)
            x, y = transform(axis["endpoint_b"], width, depth)
            draw.text((x - 240, y - 42), axis["axis_id"], font=small_font, fill=(96, 69, 145))
        for camera in room.get("camera_positions") or []:
            x, y = transform(camera["position"], width, depth)
            draw.polygon([(x, y - 20), (x - 18, y + 18), (x + 18, y + 18)], fill=(35, 84, 132))
            draw.text((x + 22, y - 14), camera["angle_id"], font=small_font, fill=(35, 84, 132))

    if subspace:
        selected = polygon(subspace["polygon"], width, depth)
        layer.polygon(selected, fill=(255, 214, 74, 65), outline=(215, 124, 0, 255), width=10)
        draw.text((80, 178), f"SUBSPACE-ID: {subspace.get('subspace_id')}", font=body_font, fill=(145, 76, 0))

    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image, "RGBA")
    start_rows = [*((blocking or {}).get("characters") or []), *((blocking or {}).get("props") or [])]
    end_rows = [*((end_blocking or {}).get("characters") or []), *((end_blocking or {}).get("props") or [])]
    for row in start_rows:
        entity = row.get("character_id") or row.get("prop_id")
        x, y = transform(row["position"], width, depth)
        draw.ellipse((x - 20, y - 20, x + 20, y + 20), fill=(20, 101, 153, 235), outline=(255, 255, 255, 255), width=3)
        draw.text((x + 25, y - 17), f"S:{entity}", font=small_font, fill=(20, 70, 110, 255))
    for row in end_rows:
        entity = row.get("character_id") or row.get("prop_id")
        x, y = transform(row["position"], width, depth)
        draw.rectangle((x - 17, y - 17, x + 17, y + 17), fill=(31, 138, 91, 225), outline=(255, 255, 255, 255), width=3)
        draw.text((x + 22, y - 16), f"E:{entity}", font=small_font, fill=(20, 91, 59, 255))
    for index, row in enumerate(trajectories or []):
        points = [row["start"], *(row.get("waypoints") or []), row["end"]]
        draw_arrow(draw, points, width, depth, ((207, 53, 46, 245) if index % 2 == 0 else (120, 65, 170, 245)), 10)

    footer = "蓝圆=起点  绿方=终点  红/紫线=动作轨迹  黄框=镜头可运动子空间  三角=机位"
    draw.text((80, CANVAS[1] - 90), footer, font=body_font, fill=(54, 58, 62, 255))
    image.convert("RGB").save(destination, format="PNG", optimize=True)


def media(path: Path, kind: str, **extra: Any) -> dict[str, Any]:
    try:
        stored_path = str(path.relative_to(ROOT))
    except ValueError:
        stored_path = str(path)
    return {"kind": kind, "path": stored_path, "sha256": sha256_file(path), "qa_status": "PASS", **extra}


def build(template: dict[str, Any], plan: dict[str, Any], asset_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = copy.deepcopy(template)
    tasks = copy.deepcopy(plan)
    places = authority.get("space_maps") or []
    if not places:
        raise ValueError("renderer requires at least one concrete place map")
    episode = str(authority.get("episode") or tasks.get("episode") or "EPISODE")
    version = int(authority.get("map_version") or 1)
    place_by_id: dict[str, dict[str, Any]] = {}
    for place in places:
        map_id = str(place.get("global_space_map_id") or "")
        if not map_id or map_id in place_by_id:
            raise ValueError(f"missing or duplicate global_space_map_id: {map_id!r}")
        place_by_id[map_id] = place
    # The episode image is a deterministic overview sheet.  Render every
    # concrete place independently and tile the results into one top-down
    # authority image so the episode asset covers all declared locations.
    overview_tiles: list[Image.Image] = []
    for place in places:
        temporary = asset_dir / ".overview" / f"{place['global_space_map_id']}.png"
        render_map(place, temporary, title=f"{episode} {place.get('name') or place['global_space_map_id']}")
        overview_tiles.append(Image.open(temporary).convert("RGB"))
    episode_path = asset_dir / f"{episode}_EPISODE_GLOBAL_SPACE_MAP_V{version}.png"
    overview = Image.new("RGB", (CANVAS[0] * len(overview_tiles), CANVAS[1]), (242, 239, 230))
    for index, tile in enumerate(overview_tiles):
        overview.paste(tile, (CANVAS[0] * index, 0))
    episode_path.parent.mkdir(parents=True, exist_ok=True)
    overview.save(episode_path, format="PNG", optimize=True)
    authority["map_image"] = media(episode_path, "EPISODE_TOP_DOWN_COMPLETE_SPACE_MAP")
    for place in places:
        place_version = int(place.get("map_version") or 1)
        place_path = asset_dir / "places" / f"{place['global_space_map_id']}_V{place_version}.png"
        render_map(place, place_path, title=f"{episode} {place.get('name') or place['global_space_map_id']} 俯视拓扑图")
        place["layout_image"] = media(place_path, "PLACE_TOP_DOWN_COMPLETE_SPACE_MAP")
        place["status"] = "LOCKED"
    subspaces = []
    task_by_id = {}
    for task in tasks.get("tasks") or []:
        task_by_id[task["task_key"]] = task
        place = place_by_id.get(str(task.get("global_space_map_id") or ""))
        if not place:
            raise ValueError(f"{task['task_key']} references an unknown global_space_map_id")
        subspace = task["subspace_layout"]
        shot_path = asset_dir / "subspaces" / f"{subspace['subspace_id']}.png"
        render_map(
            place, shot_path, title=f"{episode} {task.get('unit_id')} 镜头子空间与动作路径",
            subspace=subspace, blocking=task.get("blocking"),
            end_blocking=task.get("action_end_blocking"), trajectories=task.get("trajectory_overlays"),
        )
        reference = media(
            shot_path, "SHOT_SUBSPACE_LAYOUT",
            derived_from_place_map_sha256=place["layout_image"]["sha256"],
        )
        subspace["reference_image"] = reference
        task["reference_bindings"] = [
            {"role": "episode_global_space_map", "path": authority["map_image"]["path"], "sha256": authority["map_image"]["sha256"]},
            {"role": "global_space_map", "path": place["layout_image"]["path"], "sha256": place["layout_image"]["sha256"]},
            {"role": "subspace_layout", "path": reference["path"], "sha256": reference["sha256"]},
            *(task.get("entity_reference_bindings") or []),
        ]
        subspaces.append({
            "task_key": task["task_key"],
            "subspace_id": subspace["subspace_id"], "unit_id": task.get("unit_id"),
            "polygon": subspace["polygon"], "zone_ids": subspace["zone_ids"],
            "angle_id": subspace["angle_id"], "axis_id": subspace["axis_id"],
            "reference_image": reference,
        })
    for place in places:
        place["subspaces"] = [
            row for row in subspaces
            if task_by_id[row["task_key"]].get("global_space_map_id") == place.get("global_space_map_id")
        ]
    authority["shot_bindings"] = [
        {"task_key": row["task_key"], "unit_id": row.get("unit_id"), "subspace_id": row["subspace_layout"]["subspace_id"]}
        for row in tasks.get("tasks") or []
    ]
    authority["topology_sha256"] = content_sha256(authority["space_maps"])
    authority["status"] = "LOCKED"
    authority["generation_hold"] = {
        "gate_id": "SCENE-AUTHORITY-LOCK", "status": "PASS_SPATIAL_ASSETS_LOCKED",
        "blocked_scope": [],
        "release_condition": "Every new shot task must bind this exact authority and pass the registered gate.",
    }
    receipt = {
        "schema": "qingshan.global_space_map_render_receipt.v1",
        "episode": authority.get("episode"), "status": "PASS",
        "episode_global_space_map_id": authority.get("episode_global_space_map_id"),
        "global_space_map_ids": [row.get("global_space_map_id") for row in authority["space_maps"]],
        "topology_sha256": authority["topology_sha256"],
        "episode_map": authority["map_image"], "place_maps": [place["layout_image"] for place in places],
        "subspace_count": len(subspaces), "subspaces": subspaces,
    }
    return authority, tasks, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority-template", required=True)
    parser.add_argument("--shot-plan", required=True)
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--authority-out", required=True)
    parser.add_argument("--shot-plan-out", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    authority, plan, receipt = build(
        json.loads(abs_path(args.authority_template).read_text(encoding="utf-8")),
        json.loads(abs_path(args.shot_plan).read_text(encoding="utf-8")),
        abs_path(args.asset_dir),
    )
    authority_out = abs_path(args.authority_out)
    plan_out = abs_path(args.shot_plan_out)
    write_json(authority_out, authority)
    write_json(plan_out, plan)
    receipt["authority_path"] = str(authority_out.relative_to(ROOT)) if authority_out.is_relative_to(ROOT) else str(authority_out)
    receipt["authority_sha256"] = sha256_file(authority_out)
    receipt["shot_plan_path"] = str(plan_out.relative_to(ROOT)) if plan_out.is_relative_to(ROOT) else str(plan_out)
    receipt["shot_plan_sha256"] = sha256_file(plan_out)
    write_json(abs_path(args.receipt), receipt)
    print(json.dumps({"status": "PASS", "subspaces": receipt["subspace_count"], "topology_sha256": receipt["topology_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
