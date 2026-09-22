#!/usr/bin/env python3
"""Episode-agnostic replacement for the two E01-hardcoded preproduction generators.

Replaces
--------
* ``preproduction/E01/tools/build_asset_requirements.py``  (no argv, E01 paths baked in)
* the prompt-writing half of ``preproduction/E01/tools/build_character_reference_image_manifest.py``

and resolves open decision **D-10**.

What it emits
-------------
``<out-dir>/asset_requirements.json``
    Schema ``ai_drama.production_asset_requirements.v1``, the same ten categories in
    the same order as E01's 67-item file:
    characters, wardrobe, scenes, props, voices, accents, music, ambience, sfx,
    reference_materials.

``<out-dir>/prompts/<EP>-{CHAR,LOC,PROP}-<suffix>.txt``
    One authored prompt per NEW image subject (characters + scenes + props), in the
    byte-exact E01 prompt format:  header block, authored body, the ``source_action``
    line that ``bootstrap_identity_cards.py`` / ``submit_giggle_*`` bind by SHA, and
    the shared 【视觉文化档案】/【严格禁止】 style block synthesised from
    ``visual_culture_contract``.  ``SET-*`` prop ids are written as ``<EP>-PROP-*``
    because ``bootstrap_identity_cards.prompt_path_for`` looks for that name.

``<out-dir>/asset_requirements_build_report.json``
    Per-subject NEW / REUSED decision, the prior SHA for every reused subject, every
    ``AUTHORING_REQUIRED_*`` sentinel that was emitted, and the prompt inventory.

Derived vs authored
-------------------
Everything that the sealed four-layer script set actually contains is derived:
ids, labels for contract entities, ``appearance_ch1``, ``physical_function`` from
``non_character_entities[].note``, per-scene ``scene_states`` / lighting variants,
ambience beds from ``audio_contract.ambient_by_scene``, dialogue line counts, the
NO-BGM music policy row, all three reference_materials rows, and every
``authority_refs`` SHA.

A short list of fields is genuine *prose authorship* that no script layer carries —
character priority / apparent age / sex, wardrobe state descriptions, per-location
spatial topology, the props that only the directing script names, voice timbre
briefs, the accent profile, and the SFX table.  Those come from an optional
``--overlay`` file (schema ``nalu.episode_asset_requirement_overlay.v1``).  Without
an overlay the tool **first tries the prior asset library** (a returning character
keeps the wardrobe/voice/accent prose that was already locked for the series) and
only then emits an explicit ``AUTHORING_REQUIRED_<FIELD>`` sentinel, which is
listed in the build report.  It never invents prose.

``--extract-overlay-from <asset_requirements.json>`` writes the overlay for an
episode that was authored by hand, which is how ``E01_asset_overlay.json`` was
produced; regenerating E01 with it is byte-identical to the committed file.

Reuse
-----
A subject already ``status`` ``LOCKED*`` with ``qa.status == PASS`` in
``--prior-library`` is marked reused: its requirement row gains a ``reuse`` block
carrying ``prior_status``, ``prior_version``, ``prior_artifact_sha256`` and the
library path, ``first_use_episode`` keeps the prior value, this episode is appended
to ``required_in_episodes``, and **no prompt is authored** for it.  A subject that
is not locked is NEW and gets a prompt.  No ``reuse`` key is added for NEW subjects,
so an episode whose library has nothing locked reproduces byte-for-byte.

CLI
---
    build_episode_asset_requirements.py \
      --episode E02 \
      --contract  $ENGINE_ROOT/workflow/claude_writer_agent/scripts/E02_GENERATION_CONTRACT_v1.json \
      --narrative $ENGINE_ROOT/workflow/claude_writer_agent/scripts/E02_NARRATIVE_CANONICAL_v1.md \
      --manifest  $ENGINE_ROOT/workflow/claude_writer_agent/scripts/E02_manifest_v1.json \
      --prior-library $RUNTIME_ROOT/runtime/asset_library.json \
      --out-dir   $RUNTIME_ROOT/preproduction/E02/ \
      [--directing <EP>_DIRECTING_SCRIPT_v1.md]  [--charter <series authority md>] \
      [--gsm <global_space_map.json>]  [--overlay <overlay.json>] \
      [--prompts-only | --requirements-only]  [--dry-run]

Exit codes: 0 PASS, 2 a required input is missing or malformed,
3 the build completed but emitted AUTHORING_REQUIRED sentinels (fail-loud).
Never touches the network and never writes outside ``--out-dir``.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "ai_drama.production_asset_requirements.v1"
OVERLAY_SCHEMA = "nalu.episode_asset_requirement_overlay.v1"
PROJECT_ID = "NALU-YEWUJIANG"   # default; --project-id (series scope) overrides — Roger 2026-09-18 E59
ENGINE_ROOT = Path(f"{_np.ENGINE_ROOT}")
SCRIPTS_DIR = ENGINE_ROOT / "workflow/claude_writer_agent/scripts"
DEFAULT_CHARTER = ENGINE_ROOT / "workflow/claude_writer_agent/宪章_ClaudeWriterAgent_v1.md"
RUNTIME_PREPRO = Path(f"{_np.RUNTIME_ROOT}/preproduction")

CN_NUM = "零一二三四五六七八九十"
AUTHORING = "AUTHORING_REQUIRED_"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def episode_number(episode: str) -> int:
    match = re.search(r"(\d+)", episode)
    if not match:
        raise SystemExit(f"cannot read an episode number out of {episode!r}")
    return int(match.group(1))


def cn_chapter(value: str) -> str:
    try:
        number = int(str(value).strip())
    except ValueError:
        return str(value)
    if 0 <= number <= 10:
        return CN_NUM[number]
    if 10 < number < 20:
        return "十" + CN_NUM[number - 10]
    return str(number)


def strip_prefix(asset_id: str) -> str:
    return re.sub(r"^(CHAR|PROP|SET|LOC|WARD|VOICE)-", "", asset_id)


def project_slug() -> str:
    return PROJECT_ID.split("-", 1)[1] if "-" in PROJECT_ID else PROJECT_ID


# --------------------------------------------------------------------------- #
# prior library
# --------------------------------------------------------------------------- #
class PriorLibrary:
    """Cross-episode reuse authority (runtime/asset_library.json)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.assets: dict[str, dict[str, Any]] = {}
        if path is None or not path.is_file():
            return
        library = load_json(path)
        assets = library.get("assets") or {}
        if isinstance(assets, list):
            category_rows = [("UNCLASSIFIED", assets)]
        elif isinstance(assets, dict):
            category_rows = list(assets.items())
        else:
            category_rows = []
        for category, rows in category_rows:
            iterator = rows.values() if isinstance(rows, dict) else rows
            for row in iterator:
                asset_id = str(row.get("asset_id") or "")
                if asset_id:
                    self.assets[asset_id] = {**row, "category": row.get("category") or category}

    def row(self, asset_id: str) -> dict[str, Any] | None:
        return self.assets.get(asset_id)

    def is_locked(self, asset_id: str) -> bool:
        row = self.assets.get(asset_id)
        if not row:
            return False
        status = str(row.get("status") or "")
        qa = str((row.get("qa") or {}).get("status") or "")
        return status.startswith("LOCKED") and qa == "PASS"

    def artifact_shas(self, asset_id: str) -> list[str]:
        row = self.assets.get(asset_id) or {}
        shas = []
        for artifact in row.get("artifacts") or []:
            value = artifact.get("sha256") or artifact.get("artifact_sha256")
            if value:
                shas.append(str(value))
        return shas

    def spec_field(self, asset_id: str, field: str) -> Any:
        row = self.assets.get(asset_id) or {}
        return ((row.get("specification") or {}).get(field))

    def full_row(self, asset_id: str) -> dict[str, Any] | None:
        return self.assets.get(asset_id)


def reuse_block(library: PriorLibrary, asset_id: str) -> dict[str, Any]:
    row = library.row(asset_id) or {}
    return {
        "status": "REUSED_FROM_PRIOR_LIBRARY",
        "prior_library": str(library.path),
        "prior_status": row.get("status"),
        "prior_version": row.get("version"),
        "prior_qa_status": (row.get("qa") or {}).get("status"),
        "prior_artifact_sha256": library.artifact_shas(asset_id),
        "prior_requirement_sha256": row.get("requirement_sha256"),
        "regeneration_forbidden_reason": "SUBJECT_ALREADY_LOCKED_WITH_QA_PASS_IN_CROSS_EPISODE_LIBRARY",
    }


def episode_scope_fields(library: PriorLibrary, asset_id: str, number: int, reused: bool) -> dict[str, Any]:
    if not reused:
        return {"first_use_episode": number, "required_in_episodes": [number]}
    row = library.row(asset_id) or {}
    first = row.get("first_use_episode")
    required = list(row.get("required_in_episodes") or [])
    if number not in required:
        required.append(number)
    return {
        "first_use_episode": first if isinstance(first, int) else number,
        "required_in_episodes": sorted({int(value) for value in required if isinstance(value, int)}) or [number],
    }


# --------------------------------------------------------------------------- #
# overlay
# --------------------------------------------------------------------------- #
def overlay_get(overlay: dict[str, Any], section: str, key: str, field: str) -> Any:
    return ((overlay.get(section) or {}).get(key) or {}).get(field)


def authored(
    value: Any,
    *,
    sentinel: str,
    fallback: Any = None,
    missing: list[dict[str, Any]],
    asset_id: str,
    field: str,
    fallback_source: str | None = None,
) -> Any:
    """Overlay value, else prior-library fallback, else a loud sentinel."""
    if value not in (None, ""):
        return value
    if fallback not in (None, ""):
        missing.append({
            "asset_id": asset_id, "field": field,
            "resolution": "INHERITED_FROM_PRIOR_LIBRARY", "source": fallback_source,
        })
        return fallback
    missing.append({
        "asset_id": asset_id, "field": field,
        "resolution": "AUTHORING_REQUIRED", "sentinel": AUTHORING + sentinel,
    })
    return AUTHORING + sentinel


# --------------------------------------------------------------------------- #
# GSM-derived spatial topology (used when the overlay does not author it)
# --------------------------------------------------------------------------- #
def gsm_index(gsm: dict[str, Any] | None) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """location_id -> (place_map, room).  Mirrors the E01 prompt builder's lookup."""
    index: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    if not gsm:
        return index
    for place in gsm.get("space_maps") or []:
        for room in place.get("rooms") or []:
            if room.get("location_id"):
                index[str(room["location_id"])] = (place, room)
        for mapping in place.get("scene_mappings") or []:
            rooms = place.get("rooms") or []
            if not rooms:
                continue
            room_by_id = {str(r.get("room_id")): r for r in rooms}
            room = room_by_id.get(str(mapping.get("room_id"))) or rooms[0]
            index.setdefault(str(mapping["location_id"]), (place, room))
    return index


def gsm_topology(place: dict[str, Any], room: dict[str, Any]) -> str:
    zones = "；".join(str(z.get("name") or z.get("zone_id")) for z in room.get("zones") or [])
    return f"{place.get('name') or place.get('global_space_map_id')}／{room.get('name') or room.get('room_id')}：{zones}"


def gsm_elements(room: dict[str, Any]) -> list[str]:
    return [str(e.get("name") or e.get("element_id")) for e in room.get("fixed_elements") or []]


# --------------------------------------------------------------------------- #
# prompt bodies — byte-exact E01 format
# --------------------------------------------------------------------------- #
def style_block(vcc: dict[str, Any]) -> str:
    palette = vcc["palette_system"]
    return "\n".join([
        f"【视觉文化档案】{vcc['profile_id']}",
        f"世界：{vcc['story_world']}",
        f"美术：{vcc['production_design']}",
        f"色彩：底色{palette['base']}；点色{palette['accent']}；肤色{palette['skin']}",
        f"光线：{vcc['lighting_language']}",
        f"质感：{vcc['image_texture']}",
        "画幅：9:16 竖构图。画面内不得出现任何文字、字幕、水印、logo。",
        "【严格禁止】" + "；".join(vcc["forbidden_influences"]),
    ])


def character_prompt(row: dict[str, Any], wardrobe_desc: str, style: str) -> tuple[str, str]:
    spec = row["specification"]
    cid = row["asset_id"]
    source_action = (
        f"建立 {spec['canonical_name']}（{cid}）的身份基准卡："
        "正面中性表情、无动作、直立、目视镜头"
    )
    body = "\n".join([
        f"【人物身份基准卡】{spec['canonical_name']}（{cid}）",
        f"表观年龄 {spec['apparent_age_range']}；性别 {spec['sex']}",
        f"外貌（原著第一章）：{spec['appearance_ch1']}",
        f"服装：{wardrobe_desc}",
        "",
        source_action,
        "",
        "构图：单人，纯净中性灰底，无环境、无道具、无其他人物、无动物。"
        "均匀柔和的正面照明，仅为记录五官与形体，不做戏剧化打光。"
        "全身直立，双手自然垂放，面部无遮挡，发际线与耳廓可见。",
        "身份锁定要素必须清晰可辨：脸型骨骼、发型、眼型、肤色、体型。",
        "",
        style,
    ])
    return body, source_action


def location_prompt(row: dict[str, Any], place: dict[str, Any], room: dict[str, Any], style: str) -> tuple[str, str]:
    spec = row["specification"]
    loc = row["asset_id"]
    lighting = spec["lighting_variants_required"][0]
    state = spec["scene_states"][0]
    source_action = f"建立 {loc} 的空间基准帧：{spec['spatial_topology']}"
    body = "\n".join([
        f"【场景基准参考图】{row['label']}（{loc}）",
        f"所属空间图：{place['global_space_map_id']} / 房间 {room['room_id']}",
        "第一张参考图是本地渲染的俯视拓扑图，只作为空间布局与相对位置的依据；"
        "输出必须是实拍质感的场景照片，不得画成地图、示意图、平面图或带任何标注线条。",
        "",
        source_action,
        "",
        f"固定要素（必须全部出现且相对位置与拓扑图一致）：{'；'.join(spec['key_fixed_elements'])}",
        f"时间：{state['time_id']}｜天气：{state['weather']}",
        f"光线：{lighting}",
        "画面内无人物、无动物。空镜。",
        "",
        style,
    ])
    return body, source_action


def prop_prompt(row: dict[str, Any], style: str) -> tuple[str, str]:
    spec = row["specification"]
    pid = row["asset_id"]
    source_action = f"建立 {spec['canonical_name']}（{pid}）的道具基准卡：静置、单体、完整可见"
    body = "\n".join([
        f"【道具身份基准卡】{spec['canonical_name']}（{pid}）",
        f"形制与功能：{spec['physical_function']}",
        "",
        source_action,
        "",
        ("构图：单一主体，纯净中性灰底，无人物、无环境、无其他道具。"
         if not spec.get("is_set_piece") else
         "构图：该项为场景构筑物，取其局部完整形制，纯净中性背景，无人物。"),
        "均匀柔和照明以记录材质、比例与磨损痕迹；若主体自身发光，其光晕必须真实溢出到背景。",
        "",
        style,
    ])
    return body, source_action


def prompt_filename(episode: str, asset_id: str) -> str:
    if asset_id.startswith("CHAR-"):
        return f"{episode}-CHAR-{strip_prefix(asset_id)}.txt"
    if asset_id.startswith("LOC-"):
        return f"{episode}-LOC-{strip_prefix(asset_id)}.txt"
    # SET-* is written as PROP-* : bootstrap_identity_cards.prompt_path_for looks
    # for f"{episode}-PROP-{re.sub(r'^(PROP|SET)-', '', stem)}.txt".
    return f"{episode}-PROP-{strip_prefix(asset_id)}.txt"


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #
def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    episode = args.episode
    number = episode_number(episode)
    contract_path = Path(args.contract).resolve()
    narrative_path = Path(args.narrative).resolve()
    manifest_path = Path(args.manifest).resolve()
    directing_path = (
        Path(args.directing).resolve() if args.directing
        else SCRIPTS_DIR / f"{episode}_DIRECTING_SCRIPT_v1.md"
    )
    charter_path = Path(args.charter).resolve() if args.charter else DEFAULT_CHARTER
    for label, path in (
        ("--contract", contract_path), ("--narrative", narrative_path),
        ("--manifest", manifest_path), ("directing script", directing_path),
        ("series authority", charter_path),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")

    contract = load_json(contract_path)
    manifest = load_json(manifest_path)
    vcc = contract["visual_culture_contract"]
    overlay = load_json(Path(args.overlay).resolve()) if args.overlay else {}
    if overlay and overlay.get("schema") != OVERLAY_SCHEMA:
        raise SystemExit(f"--overlay schema must be {OVERLAY_SCHEMA}")
    if overlay and str(overlay.get("episode") or episode) != episode:
        raise SystemExit(f"--overlay is for episode {overlay.get('episode')}, not {episode}")

    gsm_path = Path(args.gsm).resolve() if args.gsm else RUNTIME_PREPRO / episode / "global_space_map.json"
    gsm = load_json(gsm_path) if gsm_path.is_file() else None
    places = gsm_index(gsm)

    library = PriorLibrary(Path(args.prior_library).resolve() if args.prior_library else None)
    missing: list[dict[str, Any]] = []

    a_narr = {"source_id": narrative_path.name, "sha256": sha256_file(narrative_path)}
    a_dire = {"source_id": directing_path.name, "sha256": sha256_file(directing_path)}
    a_cont = {"source_id": contract_path.name, "sha256": sha256_file(contract_path)}
    a_mani = {"source_id": manifest_path.name, "sha256": sha256_file(manifest_path)}

    visual_culture = {
        "visual_culture_profile_id": vcc["profile_id"],
        "palette_base": vcc["palette_system"]["base"],
        "palette_accent": vcc["palette_system"]["accent"],
        "palette_skin": vcc["palette_system"]["skin"],
        "lighting_language": vcc["lighting_language"],
        "image_texture": vcc["image_texture"],
        "forbidden_influences": vcc["forbidden_influences"],
    }

    chars = {str(row["character_id"]): row for row in contract.get("character_entities") or []}
    # E05 (seq=26): VOICE_ONLY_NO_PLATE characters (a speaking creature whose picture is a
    # PROP card) get a voices row only — no identity card, no wardrobe state.
    plate_chars = {cid: row for cid, row in chars.items()
                   if str((row.get("identity_source") or {}).get("mode") or "") != "VOICE_ONLY_NO_PLATE"}
    speaking = {str(u["speaker_id"]) for u in contract["audio_contract"]["dialogue_units"]}
    line_counts: dict[str, int] = {}
    for unit in contract["audio_contract"]["dialogue_units"]:
        key = str(unit["speaker_id"])
        line_counts[key] = line_counts.get(key, 0) + 1

    reuse_decisions: list[dict[str, Any]] = []

    def scoped(asset_id: str) -> dict[str, Any]:
        reused = library.is_locked(asset_id)
        reuse_decisions.append({
            "asset_id": asset_id,
            "decision": "REUSED" if reused else "NEW",
            "prior_status": (library.row(asset_id) or {}).get("status"),
            "prior_artifact_sha256": library.artifact_shas(asset_id) if reused else [],
        })
        block = episode_scope_fields(library, asset_id, number, reused)
        if reused:
            block["reuse"] = reuse_block(library, asset_id)
        return block

    def order(base: dict[str, Any], scope: dict[str, Any], specification: dict[str, Any],
              refs: list[dict[str, Any]]) -> dict[str, Any]:
        """Assemble a requirement row with E01's exact key order."""
        # Older Qingshan registries used AUTHORING_REQUIRED_* sentinels for
        # fields that were later filled from local source assets.  The
        # portable asset contract only admits SERIES_CORE/EPISODE_REQUIRED/
        # OPTIONAL; normalize the legacy marker after migration rather than
        # making the new line discard an otherwise valid returning asset.
        priority = str(base.get("priority") or "")
        if priority.startswith("AUTHORING_REQUIRED") or priority not in {"SERIES_CORE", "EPISODE_REQUIRED", "OPTIONAL"}:
            priority = "EPISODE_REQUIRED"
        row = {
            "asset_id": base["asset_id"],
            "label": base["label"],
            "priority": priority,
            "first_use_episode": scope["first_use_episode"],
            "required_in_episodes": scope["required_in_episodes"],
            "authority_refs": refs,
            "specification": specification,
        }
        if "reuse" in scope:
            row["reuse"] = scope["reuse"]
        return row

    # ------------------------------------------------------------- characters
    characters: list[dict[str, Any]] = []
    wardrobe_desc_by_char: dict[str, str] = {}
    for cid, row in plate_chars.items():
        suffix = strip_prefix(cid)
        ward_id = f"WARD-{suffix}-{episode}"
        prior = library.full_row(cid) or {}
        priority = authored(
            overlay_get(overlay, "characters", cid, "priority"),
            sentinel="CHARACTER_PRIORITY", fallback=prior.get("priority"),
            missing=missing, asset_id=cid, field="priority",
            fallback_source="prior_library.priority",
        )
        age = authored(
            overlay_get(overlay, "characters", cid, "apparent_age_range"),
            sentinel="APPARENT_AGE_RANGE", fallback=library.spec_field(cid, "apparent_age_range"),
            missing=missing, asset_id=cid, field="apparent_age_range",
            fallback_source="prior_library.specification.apparent_age_range",
        )
        sex = authored(
            overlay_get(overlay, "characters", cid, "sex"),
            sentinel="SEX", fallback=library.spec_field(cid, "sex"),
            missing=missing, asset_id=cid, field="sex",
            fallback_source="prior_library.specification.sex",
        )
        scope = scoped(cid)
        characters.append(order(
            {"asset_id": cid, "label": row["canonical_name"], "priority": priority},
            scope,
            {
                "asset_kind": "CHARACTER_IDENTITY_REFERENCE_CARD",
                "canonical_name": row["canonical_name"],
                "aliases": row.get("aliases") or [],
                "appearance_ch1": row.get("appearance_ch1") or "",
                "apparent_age_range": age,
                "sex": sex,
                "identity_lock_required_fields": [
                    "face_geometry", "hair", "eye", "skin_tone", "build",
                ],
                "card_deliverables": [
                    "FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST", "FULL_BODY_STANDING",
                ],
                "aspect_ratio": "9:16",
                "visual_culture": visual_culture,
                "speaking_in_episode": cid in speaking,
                "voice_asset_id": f"VOICE-{suffix}",
                "wardrobe_asset_ids": [ward_id],
            },
            [a_narr, a_cont],
        ))

    # --------------------------------------------------------------- wardrobe
    wardrobe: list[dict[str, Any]] = []
    for cid, row in plate_chars.items():
        suffix = strip_prefix(cid)
        ward_id = f"WARD-{suffix}-{episode}"
        prior_ward = None
        for candidate in (ward_id, *[
            key for key in library.assets
            if key.startswith(f"WARD-{suffix}-")
        ]):
            if library.spec_field(candidate, "description"):
                prior_ward = library.spec_field(candidate, "description")
                break
        description = authored(
            overlay_get(overlay, "wardrobe", cid, "description"),
            sentinel="WARDROBE_STATE_DESCRIPTION", fallback=prior_ward,
            missing=missing, asset_id=ward_id, field="specification.description",
            fallback_source="prior_library WARD-* specification.description",
        )
        wardrobe_desc_by_char[cid] = description
        scope = scoped(ward_id)
        wardrobe.append(order(
            {
                "asset_id": ward_id,
                "label": f"{row['canonical_name']}｜{episode} 服装状态",
                "priority": overlay_get(overlay, "wardrobe", cid, "priority") or "EPISODE_REQUIRED",
            },
            scope,
            {
                "asset_kind": "WARDROBE_STATE_REFERENCE",
                "owner_character_id": cid,
                "description": description,
                "period_constraints": vcc["production_design"],
                "forbidden": vcc["forbidden_influences"],
                "visual_culture": visual_culture,
            },
            [a_dire, a_cont],
        ))

    # ----------------------------------------------------------------- scenes
    scene_by_loc: dict[str, list[dict[str, Any]]] = {}
    for state in contract.get("scene_states") or []:
        scene_by_loc.setdefault(str(state["location_id"]), []).append(state)
    locations = list(manifest.get("distinct_locations") or sorted(scene_by_loc))
    scenes: list[dict[str, Any]] = []
    for loc in locations:
        states = scene_by_loc.get(loc) or []
        if not states:
            raise SystemExit(f"{loc} is in manifest.distinct_locations but has no scene_states")
        place_room = places.get(loc)
        label = authored(
            overlay_get(overlay, "scenes", loc, "label"),
            sentinel="SCENE_LABEL",
            fallback=(place_room[1].get("name") if place_room else None)
            or (library.row(loc) or {}).get("label"),
            missing=missing, asset_id=loc, field="label",
            fallback_source="global_space_map room.name / prior_library.label",
        )
        topology = authored(
            overlay_get(overlay, "scenes", loc, "spatial_topology"),
            sentinel="SPATIAL_TOPOLOGY",
            fallback=(gsm_topology(*place_room) if place_room else None)
            or library.spec_field(loc, "spatial_topology"),
            missing=missing, asset_id=loc, field="specification.spatial_topology",
            fallback_source="global_space_map place/room/zone names",
        )
        elements = (
            overlay_get(overlay, "scenes", loc, "key_fixed_elements")
            or (gsm_elements(place_room[1]) if place_room else None)
            or library.spec_field(loc, "key_fixed_elements")
        )
        if not elements:
            missing.append({"asset_id": loc, "field": "specification.key_fixed_elements",
                            "resolution": "AUTHORING_REQUIRED",
                            "sentinel": AUTHORING + "KEY_FIXED_ELEMENTS"})
            elements = [AUTHORING + "KEY_FIXED_ELEMENTS"]
        scope = scoped(loc)
        scenes.append(order(
            {
                "asset_id": loc, "label": label,
                "priority": overlay_get(overlay, "scenes", loc, "priority") or "SERIES_CORE",
            },
            scope,
            {
                "asset_kind": "SCENE_ESTABLISHING_REFERENCE",
                "location_id": loc,
                "spatial_topology": topology,
                "key_fixed_elements": list(elements),
                "episode_global_space_map_id": manifest["episode_global_space_map_id"],
                "scene_states": [
                    {
                        "scene_id": state["scene_id"], "time_id": state["time_id"],
                        "weather": state["weather"], "lighting": state["lighting"],
                        "target_seconds": state["target_seconds"],
                    }
                    for state in states
                ],
                "lighting_variants_required": sorted({state["lighting"] for state in states}),
                "aspect_ratio": "9:16",
                "visual_culture": visual_culture,
            },
            [a_narr, a_cont, a_mani],
        ))

    # ------------------------------------------------------------------ props
    props: list[dict[str, Any]] = []
    for row in contract.get("non_character_entities") or []:
        pid = str(row["entity_id"])
        priority = overlay_get(overlay, "props", pid, "priority") \
            or (library.row(pid) or {}).get("priority") or "EPISODE_REQUIRED"
        scope = scoped(pid)
        props.append(order(
            {"asset_id": pid, "label": row["name"], "priority": priority},
            scope,
            {
                "asset_kind": "PROP_IDENTITY_REFERENCE",
                "physical_function": row["note"],
                "canonical_name": row["name"],
                "aspect_ratio": "9:16",
                "visual_culture": visual_culture,
                "is_set_piece": pid.startswith("SET-"),
            },
            [a_narr, a_cont],
        ))
    # Props that only the directing script names.  Authored ids come from the
    # overlay; directing_script_mentions is taken verbatim when authored and
    # otherwise counted over the directing-script bytes for the given terms.
    directing_text = directing_path.read_text(encoding="utf-8")
    for pid, spec in (overlay.get("props_directing_only") or {}).items():
        mentions = spec.get("directing_script_mentions")
        if mentions is None:
            terms = spec.get("mention_terms") or [spec.get("canonical_name") or ""]
            mentions = sum(directing_text.count(term) for term in terms if term)
        scope = scoped(pid)
        props.append(order(
            {"asset_id": pid, "label": spec["canonical_name"],
             "priority": spec.get("priority") or "EPISODE_REQUIRED"},
            scope,
            {
                "asset_kind": "PROP_IDENTITY_REFERENCE",
                "physical_function": spec["physical_function"],
                "canonical_name": spec["canonical_name"],
                "directing_script_mentions": mentions,
                "aspect_ratio": "9:16",
                "visual_culture": visual_culture,
                "is_set_piece": bool(spec.get("is_set_piece")),
            },
            [a_dire],
        ))

    # ----------------------------------------------------------------- voices
    voices: list[dict[str, Any]] = []
    for cid, row in chars.items():
        # E06 (2026-09-18, K055 corollary): a voice is required once per SPEAKING character.  A character
        # with no dialogue unit this episode (周阿婆, dead on the kang) gets no voices row — the library
        # gate would otherwise demand a provider voice id nobody will use.
        if cid not in speaking:
            continue
        suffix = strip_prefix(cid)
        voice_id = f"VOICE-{suffix}"
        timbre = authored(
            overlay_get(overlay, "voices", cid, "timbre_brief"),
            sentinel="VOICE_TIMBRE_BRIEF", fallback=library.spec_field(voice_id, "timbre_brief"),
            missing=missing, asset_id=voice_id, field="specification.timbre_brief",
            fallback_source="prior_library.specification.timbre_brief",
        )
        priority = overlay_get(overlay, "voices", cid, "priority") \
            or (library.row(voice_id) or {}).get("priority") or "EPISODE_REQUIRED"
        accent_id = (overlay.get("accent_id")
                     or library.spec_field(voice_id, "accent_id")
                     or "ACCENT-ZH-CN-NORTHERN-VILLAGE-V1")
        scope = scoped(voice_id)
        voices.append(order(
            {"asset_id": voice_id, "label": f"{row['canonical_name']}｜配音", "priority": priority},
            scope,
            {
                "asset_kind": "SPEAKER_VOICE_REFERENCE",
                "owner_character_id": cid,
                "language": overlay.get("language") or "zh-CN",
                "accent_id": accent_id,
                "timbre_brief": timbre,
                f"dialogue_line_count_{episode.lower()}": line_counts.get(cid, 0),
                "native_dialogue_eligible": "TODO_ROGER_MODEL_DECISION",
                "provider_voice_id": "TODO_ROGER_PROVIDER_VOICE_ID",
                "reference_audio": "TODO_ROGER_REFERENCE_AUDIO",
                "rights_basis": "TODO_ROGER_VOICE_RIGHTS_BASIS",
            },
            [a_cont],
        ))

    # ---------------------------------------------------------------- accents
    accents: list[dict[str, Any]] = []
    for accent_id, spec in (overlay.get("accents") or {}).items():
        scope = scoped(accent_id)
        accents.append(order(
            {"asset_id": accent_id, "label": spec["label"],
             "priority": spec.get("priority") or "SERIES_CORE"},
            scope, spec["specification"], [a_cont],
        ))
    if not accents:
        accent_id = "ACCENT-ZH-CN-NORTHERN-VILLAGE-V1"
        prior = library.full_row(accent_id)
        if prior:
            scope = scoped(accent_id)
            accents.append(order(
                {"asset_id": accent_id, "label": prior.get("label") or accent_id,
                 "priority": prior.get("priority") or "SERIES_CORE"},
                scope, prior.get("specification") or {}, [a_cont],
            ))
            missing.append({"asset_id": accent_id, "field": "specification",
                            "resolution": "INHERITED_FROM_PRIOR_LIBRARY",
                            "source": "prior_library.specification"})
        else:
            missing.append({"asset_id": accent_id, "field": "specification",
                            "resolution": "AUTHORING_REQUIRED",
                            "sentinel": AUTHORING + "ACCENT_PROFILE"})

    # ------------------------------------------------------------------ music
    music_id = f"MUSIC-{episode}-NO-EXTERNAL-BGM"
    music_scope = scoped(music_id)
    music = [order(
        {"asset_id": music_id, "label": f"{episode} 无外置配乐（声景即配乐）",
         "priority": "EPISODE_REQUIRED"},
        music_scope,
        {
            "asset_kind": "MUSIC_POLICY_DECLARATION",
            "usage_scope": f"EPISODE_{episode}_FULL",
            "musical_identity": contract["audio_contract"]["bgm"],
            "external_bgm_allowed": False,
            "note": (
                "This is a declared NO-BGM contract. It still occupies a library slot so the "
                "release gate can prove the decision was authored, not forgotten."
            ),
        },
        [a_cont],
    )]

    # --------------------------------------------------------------- ambience
    states_by_id = {str(s["scene_id"]): s for s in contract.get("scene_states") or []}
    ambience: list[dict[str, Any]] = []
    for scene_id, sound in contract["audio_contract"]["ambient_by_scene"].items():
        state = states_by_id.get(str(scene_id))
        if state is None:
            raise SystemExit(f"ambient_by_scene names {scene_id}, which has no scene_state")
        amb_id = f"AMB-{scene_id}"
        scope = scoped(amb_id)
        ambience.append(order(
            {"asset_id": amb_id, "label": f"{scene_id} 环境声", "priority": "EPISODE_REQUIRED"},
            scope,
            {
                "asset_kind": "AMBIENCE_BED",
                "scene_scope": scene_id,
                "sound_field": sound,
                "location_id": state["location_id"],
                "time_id": state["time_id"],
                "target_seconds": state["target_seconds"],
                "loudness_target_lufs": -23,
            },
            [a_cont],
        ))

    # -------------------------------------------------------------------- sfx
    sfx: list[dict[str, Any]] = []
    for sfx_id, spec in (overlay.get("sfx") or {}).items():
        scope = scoped(sfx_id)
        sfx.append(order(
            {"asset_id": sfx_id, "label": spec["label"],
             "priority": spec.get("priority") or "EPISODE_REQUIRED"},
            scope,
            {
                "asset_kind": "SFX_ELEMENT",
                "physical_source": spec["physical_source"],
                "sync_event": spec["sync_event"],
                "sample_rate_hz": spec.get("sample_rate_hz", 48000),
                "channels": spec.get("channels", 2),
            },
            [a_cont],
        ))
    if not sfx:
        missing.append({"asset_id": f"SFX-*-{episode}", "field": "overlay.sfx",
                        "resolution": "AUTHORING_REQUIRED",
                        "sentinel": AUTHORING + "SFX_TABLE"})

    # ---------------------------------------------------- reference_materials
    binding = manifest["source_binding"]
    slug = project_slug()
    chapter_stem = Path(binding["source_file"]).stem
    source_ref_id = f"REF-SOURCE-{slug}-{chapter_stem.upper()}"
    vc_ref_id = f"REF-VISUAL-CULTURE-{slug}-V1"
    gsm_ref_id = "REF-EPISODE-GLOBAL-SPACE-MAP-V1"
    ref_scope_a = scoped(source_ref_id)
    ref_scope_b = scoped(vc_ref_id)
    ref_scope_c = scoped(gsm_ref_id)
    reference_materials = [
        order(
            {
                "asset_id": source_ref_id,
                "label": f"《{binding['work']}》原著第{cn_chapter(binding['primary_source_chapter'])}章 {Path(binding['source_file']).name}",
                "priority": "SERIES_CORE",
            },
            ref_scope_a,
            {
                "asset_kind": "SOURCE_CHAPTER",
                "usage_scope": f"FACT_AUTHORITY_FOR_{episode}",
                "work": binding["work"], "author": binding["author"],
                "chapter": binding["primary_source_chapter"],
                "path": binding["source_file"],
                "rights_note": "TODO_ROGER_ADAPTATION_RIGHTS_BASIS",
            },
            [{"source_id": binding["source_file"], "sha256": binding["source_sha256"]}],
        ),
        order(
            {"asset_id": vc_ref_id, "label": vcc["profile_id"], "priority": "SERIES_CORE"},
            ref_scope_b,
            {
                "asset_kind": "VISUAL_CULTURE_PROFILE",
                "usage_scope": "ALL_IMAGE_AND_VIDEO_PROMPTS",
                **visual_culture,
                "story_world": vcc["story_world"],
                "production_design": vcc["production_design"],
                "armor_tradition": vcc["armor_tradition"],
                "decision_basis": vcc["decision_basis"],
            },
            [a_cont],
        ),
        order(
            {"asset_id": gsm_ref_id, "label": manifest["episode_global_space_map_id"],
             "priority": "SERIES_CORE"},
            ref_scope_c,
            {
                "asset_kind": "EPISODE_GLOBAL_SPACE_MAP",
                "usage_scope": f"SPATIAL_AUTHORITY_FOR_ALL_{episode}_SHOTS",
                "episode_global_space_map_id": manifest["episode_global_space_map_id"],
                "anchors": manifest["global_space_map_refs"][0]["anchors"],
                "axis_note": manifest["global_space_map_refs"][0]["axis_note"],
                "authority_file": str(gsm_path),
            },
            [a_mani],
        ),
    ]

    requirements = {
        "schema": SCHEMA,
        "project_id": PROJECT_ID,
        "canonical_sha256": sha256_file(narrative_path),
        "series_bible_sha256": sha256_file(charter_path),
        "series_bible_note": (
            "No series bible file exists for the nalu line yet. The Claude writer charter "
            "(宪章_ClaudeWriterAgent_v1.md) is bound here as the standing series authority. "
            "Replace with the real bible SHA once Roger authors one; changing it forces a "
            "library recompile."
        ),
        "episode_scope": episode,
        "assets": {
            "characters": characters, "wardrobe": wardrobe, "scenes": scenes,
            "props": props, "voices": voices, "accents": accents, "music": music,
            "ambience": ambience, "sfx": sfx, "reference_materials": reference_materials,
        },
    }

    # ---------------------------------------------------------------- prompts
    style = style_block(vcc)
    prompts: dict[str, str] = {}
    prompt_rows: list[dict[str, Any]] = []
    reused_ids = {row["asset_id"] for row in reuse_decisions if row["decision"] == "REUSED"}
    for row in characters:
        cid = row["asset_id"]
        if cid in reused_ids:
            continue
        body, action = character_prompt(row, wardrobe_desc_by_char[cid], style)
        name = prompt_filename(episode, cid)
        prompts[name] = body
        prompt_rows.append({"asset_id": cid, "kind": "CHARACTER", "file": name,
                            "source_action": action})
    for row in scenes:
        loc = row["asset_id"]
        if loc in reused_ids:
            continue
        place_room = places.get(loc)
        if not place_room:
            missing.append({"asset_id": loc, "field": "prompt",
                            "resolution": "PROMPT_SKIPPED_NO_GLOBAL_SPACE_MAP_ENTRY",
                            "sentinel": AUTHORING + "GLOBAL_SPACE_MAP_PLACE_FOR_LOCATION"})
            continue
        body, action = location_prompt(row, place_room[0], place_room[1], style)
        name = prompt_filename(episode, loc)
        prompts[name] = body
        prompt_rows.append({"asset_id": loc, "kind": "LOCATION", "file": name,
                            "source_action": action})
    for row in props:
        pid = row["asset_id"]
        if pid in reused_ids:
            continue
        body, action = prop_prompt(row, style)
        name = prompt_filename(episode, pid)
        prompts[name] = body
        prompt_rows.append({"asset_id": pid, "kind": "PROP", "file": name,
                            "source_action": action})

    counts = {key: len(value) for key, value in requirements["assets"].items()}
    report = {
        "schema": "nalu.episode_asset_requirements_build_report.v1",
        "episode": episode,
        "status": "PASS" if not [row for row in missing if row["resolution"] == "AUTHORING_REQUIRED"] else "AUTHORING_REQUIRED",
        "inputs": {
            "contract": str(contract_path), "narrative": str(narrative_path),
            "manifest": str(manifest_path), "directing": str(directing_path),
            "series_authority": str(charter_path),
            "global_space_map": str(gsm_path) if gsm else None,
            "overlay": str(Path(args.overlay).resolve()) if args.overlay else None,
            "prior_library": str(library.path) if library.path else None,
        },
        "counts": counts,
        "total_subjects": sum(counts.values()),
        "image_subject_ids": sorted(
            [row["asset_id"] for row in characters]
            + [row["asset_id"] for row in scenes]
            + [row["asset_id"] for row in props]
        ),
        "reuse": {
            "new": sorted(row["asset_id"] for row in reuse_decisions if row["decision"] == "NEW"),
            "reused": sorted(reused_ids),
            "decisions": reuse_decisions,
        },
        "prompts": prompt_rows,
        "authoring_gaps": missing,
    }
    return requirements, prompts, report


# --------------------------------------------------------------------------- #
# overlay extraction
# --------------------------------------------------------------------------- #
def extract_overlay(existing_path: Path, episode: str) -> dict[str, Any]:
    """Lift the authored-prose fields out of a hand-authored asset_requirements.json."""
    existing = load_json(existing_path)
    assets = existing["assets"]
    by_id = {row["asset_id"]: row for group in assets.values() for row in group}
    overlay: dict[str, Any] = {
        "schema": OVERLAY_SCHEMA,
        "episode": episode,
        "_purpose": (
            "Authored prose that no sealed script layer carries. Everything else in "
            "asset_requirements.json is derived by build_episode_asset_requirements.py."
        ),
        "_extracted_from": {"path": str(existing_path), "sha256": sha256_file(existing_path)},
        "characters": {}, "wardrobe": {}, "scenes": {}, "props": {},
        "props_directing_only": {}, "voices": {}, "accents": {}, "sfx": {},
    }
    for row in assets.get("characters", []):
        overlay["characters"][row["asset_id"]] = {
            "priority": row["priority"],
            "apparent_age_range": row["specification"]["apparent_age_range"],
            "sex": row["specification"]["sex"],
        }
    for row in assets.get("wardrobe", []):
        overlay["wardrobe"][row["specification"]["owner_character_id"]] = {
            "priority": row["priority"],
            "description": row["specification"]["description"],
        }
    for row in assets.get("scenes", []):
        overlay["scenes"][row["asset_id"]] = {
            "priority": row["priority"], "label": row["label"],
            "spatial_topology": row["specification"]["spatial_topology"],
            "key_fixed_elements": row["specification"]["key_fixed_elements"],
        }
    for row in assets.get("props", []):
        spec = row["specification"]
        if "directing_script_mentions" in spec:
            overlay["props_directing_only"][row["asset_id"]] = {
                "priority": row["priority"],
                "canonical_name": spec["canonical_name"],
                "physical_function": spec["physical_function"],
                "directing_script_mentions": spec["directing_script_mentions"],
                "is_set_piece": spec.get("is_set_piece", False),
            }
        else:
            overlay["props"][row["asset_id"]] = {"priority": row["priority"]}
    for row in assets.get("voices", []):
        overlay["voices"][row["specification"]["owner_character_id"]] = {
            "priority": row["priority"],
            "timbre_brief": row["specification"]["timbre_brief"],
        }
        overlay.setdefault("accent_id", row["specification"]["accent_id"])
        overlay.setdefault("language", row["specification"]["language"])
    for row in assets.get("accents", []):
        overlay["accents"][row["asset_id"]] = {
            "priority": row["priority"], "label": row["label"],
            "specification": row["specification"],
        }
    for row in assets.get("sfx", []):
        overlay["sfx"][row["asset_id"]] = {
            "priority": row["priority"], "label": row["label"],
            "physical_source": row["specification"]["physical_source"],
            "sync_event": row["specification"]["sync_event"],
            "sample_rate_hz": row["specification"]["sample_rate_hz"],
            "channels": row["specification"]["channels"],
        }
    _ = by_id
    return overlay


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--episode", required=True)
    parser.add_argument("--project-id", default=None, help="asset library project id (series scope); default NALU-YEWUJIANG")
    parser.add_argument("--contract")
    parser.add_argument("--narrative")
    parser.add_argument("--manifest")
    parser.add_argument("--directing", help="default: scripts/<EP>_DIRECTING_SCRIPT_v1.md")
    parser.add_argument("--charter", help="series authority md; default the writer charter")
    parser.add_argument("--gsm", help="default: preproduction/<EP>/global_space_map.json")
    parser.add_argument("--overlay", help="authored-prose overlay (nalu.episode_asset_requirement_overlay.v1)")
    parser.add_argument("--prior-library", help="runtime/asset_library.json (cross-episode reuse authority)")
    parser.add_argument("--out-dir")
    parser.add_argument("--prompts-only", action="store_true")
    parser.add_argument("--requirements-only", action="store_true")
    parser.add_argument("--rewrite-prompts", action="store_true", help="overwrite existing derived prompt files")
    parser.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    parser.add_argument("--extract-overlay-from", help="lift the overlay out of an authored asset_requirements.json")
    parser.add_argument("--overlay-out")
    args = parser.parse_args()

    if args.extract_overlay_from:
        if not args.overlay_out:
            raise SystemExit("--extract-overlay-from requires --overlay-out")
        overlay = extract_overlay(Path(args.extract_overlay_from).resolve(), args.episode)
        dump_json(Path(args.overlay_out).resolve(), overlay)
        print(json.dumps({
            "status": "PASS", "mode": "EXTRACT_OVERLAY",
            "out": str(Path(args.overlay_out).resolve()),
            "sections": {key: len(value) for key, value in overlay.items() if isinstance(value, dict)},
        }, ensure_ascii=False))
        return 0

    prompts_kept: list[str] = []
    for flag in ("contract", "narrative", "manifest", "out_dir"):
        if not getattr(args, flag):
            raise SystemExit(f"--{flag.replace('_', '-')} is required")

    global PROJECT_ID
    if getattr(args, "project_id", None):
        PROJECT_ID = str(args.project_id)
    requirements, prompts, report = build(args)
    out_dir = Path(args.out_dir).resolve()
    written: list[str] = []
    if not args.dry_run:
        if not args.prompts_only:
            target = out_dir / "asset_requirements.json"
            dump_json(target, requirements)
            written.append(str(target))
        if not args.requirements_only:
            prompt_dir = out_dir / "prompts"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            for name, body in prompts.items():
                # 2026-09-13 (E02 identity round): derived prompts are WRITE-IF-MISSING — an operator
                # correction inside an existing prompt (e.g. 【双树颜色·硬性】) is part of a paid
                # row's fingerprint and must survive a requirements rebuild.  --rewrite-prompts forces.
                if (prompt_dir / name).is_file() and not getattr(args, "rewrite_prompts", False):
                    prompts_kept.append(name)
                    continue
                (prompt_dir / name).write_text(body, encoding="utf-8")
                written.append(str(prompt_dir / name))
        report["written"] = written
        dump_json(out_dir / "asset_requirements_build_report.json", report)
    print(json.dumps({
        "status": report["status"],
        "episode": report["episode"],
        "counts": report["counts"],
        "total_subjects": report["total_subjects"],
        "prompts_written": len(prompts) - len(prompts_kept),
        "prompts_kept_existing": prompts_kept,
        "new_subjects": len(report["reuse"]["new"]),
        "reused_subjects": len(report["reuse"]["reused"]),
        "authoring_required": [
            f"{row['asset_id']}:{row['field']}" for row in report["authoring_gaps"]
            if row["resolution"] == "AUTHORING_REQUIRED"
        ],
        "out_dir": str(out_dir),
        "dry_run": bool(args.dry_run),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
