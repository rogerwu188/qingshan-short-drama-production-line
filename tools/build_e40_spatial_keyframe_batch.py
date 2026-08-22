#!/usr/bin/env python3
"""Compile E40 spatially bound composite-start-frame image tasks.

The compiler deliberately separates manifest creation from paid submission.  It
consumes the locked episode/place/subspace plan, binds admitted identity/scene
assets by exact SHA, and emits one independent image task per requested unit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

try:
    from human_realism_prompt_contract import (
        CONTRACT_VERSION as HUMAN_REALISM_CONTRACT_VERSION,
        build_keyframe_realism_block,
    )
except ModuleNotFoundError:  # package import in unit tests
    from tools.human_realism_prompt_contract import (
        CONTRACT_VERSION as HUMAN_REALISM_CONTRACT_VERSION,
        build_keyframe_realism_block,
    )


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_SHOT_PLAN_LOCKED_V1.json"
DEFAULT_PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_SHOT_PLAN_QA_V2.json"
DEFAULT_AUTHORITY = "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_EPISODE_GLOBAL_SPACE_MAP_AUTHORITY_LOCKED_V1.json"
DEFAULT_PROMPT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/prompts/spatial_keyframes_qa_v2"
DEFAULT_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_KEYFRAME_BATCH_QA_V2.json"
TRANSPORT_DIR = ROOT / "working_assets/e40_remake_20260821/native_registry_reference_transport_v1"

ASSET_QA = "qa/e40_remake_20260817/fresh_asset_harvest_v1/E40_REMAKE_FRESH_ASSET_ADMISSION_V1.json"
SPACE_QA = "qa/e40_remake_20260818/global_space_maps_v1/E40_GLOBAL_SPACE_LAYOUT_GATE_V1.json"
PROP_QA = "qa/e40_remake_20260820/qa_v2_anchor_library/E40_QA_V2_PROP_ANCHOR_ADMISSION.json"
CHARACTER_REGISTRY = ROOT / "configs/series_character_asset_registry_20260712.json"
PROP_REGISTRY = ROOT / "configs/series_prop_asset_registry_v1.json"
IDENTITY_QA = "configs/series_character_asset_registry_20260712.json"

ASSETS: dict[str, dict[str, str]] = {
    # Episode-only or previously admitted supporting assets live here.  Every
    # returning character must resolve from CHARACTER_REGISTRY first; a local
    # override is never allowed to shadow a canonical registry identity.
    "CHAR-阿栓-古装": {
        "path": "working_assets/e38_replacement_v7_20260805/character_assets/ashuan/CHAR-E38-ashuan.jpg",
        "qa_report": "qa/e38_replacement_v7_20260805/E38_V7_CHARACTER_ASSET_FINAL_ADMISSION.json",
        "asset_origin": "ADMITTED_PRIOR_EPISODE_NATIVE",
    },
    "CHAR-E40-AMBUSH-1": {
        "path": "working_assets/e40_remake_20260817/fresh_assets_v1/infiltrators.png",
        "qa_report": ASSET_QA,
        "asset_origin": "EPISODE_NEW_ASSET",
    },
    "CHAR-E40-AMBUSH-2": {
        "path": "working_assets/e40_remake_20260817/fresh_assets_v1/infiltrators.png",
        "qa_report": ASSET_QA,
        "asset_origin": "EPISODE_NEW_ASSET",
    },
}

SCENE_ASSET = {
    "role": "scene",
    "entity_id": "GSM-WANGFU-HALL-001",
    "path": "working_assets/e40_remake_20260817/fresh_assets_v1/wangfu_hall.png",
    "qa_status": "PASS",
    "qa_report": ASSET_QA,
}

# Episode appearance is narrower than series identity.  The registry locks who
# a character is; these locks define how that identity must appear in E40.
EPISODE_APPEARANCE_LOCKS = {
    "CHAR-陈迹-古装": "20岁年轻男性，素白细布直裰，清瘦挺拔，不得成熟化、老龄化或驼背。",
    "CHAR-白鲤-古装": "素白衣、面纱必须覆面、窄直静立轮廓，垂眼克制，不露脸微笑；红玉仅在授权的末场特写显露。",
    "CHAR-云妃-古装": "全程在长帘后，只见高髻、广袖、团扇剪影，禁止出帘、露脸或露手正面。",
    "CHAR-阿栓-古装": "15岁少年，圆脸稚气，靛蓝短褐，发散一缕且衣皱，不得生成成年体态。",
    "CHAR-乌云-猫": "资产库原图锁定的棕色虎斑长毛灵猫，毛色、条纹、体态不得改成黑猫或其他品种。",
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binding(
    role: str,
    entity_id: str,
    path: str,
    qa_report: str | None = None,
    *,
    asset_origin: str | None = None,
) -> dict[str, Any]:
    actual = resolve(path)
    if not actual.is_file():
        raise FileNotFoundError(actual)
    row: dict[str, Any] = {
        "role": role,
        "entity_id": entity_id,
        "path": path,
        "sha256": sha256_file(actual),
        "qa_status": "PASS",
    }
    if qa_report:
        row["qa_report"] = qa_report
    if asset_origin:
        row["asset_origin"] = asset_origin
    return row


def canonical_character_assets() -> dict[str, dict[str, Any]]:
    registry = json.loads(CHARACTER_REGISTRY.read_text(encoding="utf-8"))
    characters = registry.get("characters") or {}
    if not isinstance(characters, dict):
        raise ValueError("canonical character registry has no characters mapping")
    return characters


def canonical_prop_assets() -> dict[str, dict[str, Any]]:
    registry = json.loads(PROP_REGISTRY.read_text(encoding="utf-8"))
    props = registry.get("props") or {}
    if not isinstance(props, dict):
        raise ValueError("canonical prop registry has no props mapping")
    return props


def resolve_character_asset(character_id: str) -> dict[str, str]:
    canonical = canonical_character_assets().get(character_id)
    if canonical is not None:
        status = str(canonical.get("status") or "")
        if not status.startswith("LOCKED"):
            raise ValueError(f"canonical identity is not locked for {character_id}: {status}")
        path = str(
            canonical.get("generation_reference_image")
            or canonical.get("identity_reference_image")
            or canonical.get("reference_image")
            or ""
        )
        if not path:
            raise ValueError(f"canonical registry has no identity image for {character_id}")
        expected_sha = str(
            canonical.get("generation_reference_sha256")
            or canonical.get("identity_reference_sha256")
            or canonical.get("reference_sha256")
            or ""
        )
        actual = resolve(path)
        if not actual.is_file():
            raise FileNotFoundError(actual)
        actual_sha = sha256_file(actual)
        if expected_sha and expected_sha != actual_sha:
            raise ValueError(f"canonical registry SHA mismatch for {character_id}")
        return {
            "path": portable(actual),
            "qa_report": str(canonical.get("generation_reference_qa") or CHARACTER_REGISTRY),
            "asset_origin": "CANONICAL_NATIVE_REGISTRY",
        }
    if character_id not in ASSETS:
        raise ValueError(
            f"no asset-library identity for {character_id}; register a native or episode-new asset before keyframe compilation"
        )
    return ASSETS[character_id]


def character_bindings(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for character_id in task.get("canonical_characters") or []:
        character_id = str(character_id)
        asset = resolve_character_asset(character_id)
        rows.append(
            binding(
                "character",
                character_id,
                asset["path"],
                asset["qa_report"],
                asset_origin=asset["asset_origin"],
            )
        )
    return rows


def prop_bindings(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    registry = canonical_prop_assets()
    for prop_id in task.get("canonical_props") or []:
        prop_id = str(prop_id)
        asset = registry.get(prop_id)
        if not asset or not str(asset.get("status") or "").startswith("LOCKED"):
            raise ValueError(f"{task.get('unit_id')} has no locked prop-registry binding for {prop_id}")
        path = str(asset.get("generation_reference_image") or "")
        expected_sha = str(asset.get("generation_reference_sha256") or "")
        row = binding(
            "prop", prop_id, path,
            str(asset.get("generation_reference_qa") or PROP_REGISTRY),
            asset_origin="CANONICAL_PROP_REGISTRY",
        )
        if not expected_sha or row["sha256"] != expected_sha:
            raise ValueError(f"prop registry SHA mismatch for {prop_id}")
        row["semantic_lock"] = str(asset.get("semantic_lock") or "")
        rows.append(row)
    return rows


def upgrade_plan_v2(source_path: Path, output_path: Path) -> dict[str, Any]:
    plan = json.loads(source_path.read_text(encoding="utf-8"))
    script_path = resolve(plan["canonical_script_path"])
    plan["schema"] = "qingshan.spatial_shot_plan.v2"
    plan["episode"] = "E40-REMAKE-QA-V2"
    plan["canonical_script_sha256"] = sha256_file(script_path)
    plan["qa_target_revision"] = "CANONICAL_SCENE_CAST_AND_PROP_ANCHORS_ADDED_BEFORE_MEDIA_REGENERATION"
    for task in plan.get("tasks") or []:
        visible_character_ids: list[str] = []
        for block_name in ("blocking", "action_end_blocking"):
            for row in (task.get(block_name) or {}).get("characters") or []:
                character_id = str(row.get("character_id") or "")
                if character_id and character_id not in visible_character_ids:
                    visible_character_ids.append(character_id)
        task["canonical_characters"] = visible_character_ids
        prop_ids: list[str] = []
        for block_name in ("blocking", "action_end_blocking"):
            for row in (task.get(block_name) or {}).get("props") or []:
                prop_id = str(row.get("prop_id") or "")
                if prop_id and prop_id not in prop_ids:
                    prop_ids.append(prop_id)
        task["canonical_props"] = prop_ids
        task["visible_characters"] = visible_character_ids
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def map_bindings(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source in task.get("reference_bindings") or []:
        role = str(source.get("role") or "")
        entity_id = {
            "episode_global_space_map": str(task["episode_global_space_map_id"]),
            "global_space_map": str(task["global_space_map_id"]),
            "subspace_layout": str(task["subspace_layout"]["subspace_id"]),
        }.get(role)
        if not entity_id:
            continue
        row = binding(role, entity_id, str(source["path"]), SPACE_QA)
        if row["sha256"] != source.get("sha256"):
            raise ValueError(f"{task.get('unit_id')} locked {role} SHA mismatch")
        rows.append(row)
    if [row["role"] for row in rows] != [
        "episode_global_space_map", "global_space_map", "subspace_layout"
    ]:
        raise ValueError(f"{task.get('unit_id')} map binding chain is incomplete or misordered")
    return rows


def describe_rows(rows: list[dict[str, Any]], id_field: str) -> str:
    return "；".join(
        f"{row[id_field]}位于{row.get('zone_id')}坐标{row.get('position')}朝向{row.get('facing')}"
        for row in rows
    ) or "无"


def stable_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def make_transport_sheet(paths: list[str], output: Path, columns: int = 3) -> None:
    """Compose admitted anchors losslessly enough for a <=5 image transport.

    This is a mechanical contact sheet, not a new semantic asset.  Source
    component SHAs remain in every entity binding.
    """
    actual = [resolve(path) for path in stable_unique(paths)]
    if not actual:
        raise ValueError("Cannot build an empty reference transport sheet")
    cell = (512, 512)
    columns = min(columns, len(actual))
    rows = (len(actual) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell[0], rows * cell[1]), (32, 32, 32))
    for index, path in enumerate(actual):
        with Image.open(path) as image:
            tile = ImageOps.contain(image.convert("RGB"), cell)
            x = (index % columns) * cell[0] + (cell[0] - tile.width) // 2
            y = (index // columns) * cell[1] + (cell[1] - tile.height) // 2
            canvas.paste(tile, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def transport_bindings(task: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unit = str(task["unit_id"])
    visible = set(map(str, task.get("visible_characters") or []))
    character_rows = [row for row in rows if row["role"] == "character"]
    groups = {
        "space": [row for row in rows if row["role"] in {"episode_global_space_map", "global_space_map", "subspace_layout"}],
        "visible-characters": [row for row in character_rows if row["entity_id"] in visible],
        "off-camera-characters": [row for row in character_rows if row["entity_id"] not in visible],
    }
    replacements: dict[str, str] = {}
    for name, members in groups.items():
        if not members:
            continue
        output = TRANSPORT_DIR / f"E40-{unit}-{name.upper()}-TRANSPORT-QA-V2.png"
        make_transport_sheet([row["path"] for row in members], output)
        for row in members:
            replacements[f"{row['role']}::{row['entity_id']}"] = portable(output)
    transported = deepcopy(rows)
    for row in transported:
        key = f"{row['role']}::{row['entity_id']}"
        if key in replacements:
            row["source_component_path"] = row["path"]
            row["source_component_sha256"] = row["sha256"]
            row["path"] = replacements[key]
            row["sha256"] = sha256_file(resolve(row["path"]))
            row["transport_mode"] = "MECHANICAL_CONTACT_SHEET"
    return transported


def make_prompt(task: dict[str, Any], references: list[dict[str, Any]]) -> str:
    subspace = task["subspace_layout"]
    actors = (task.get("blocking") or {}).get("characters") or []
    props = (task.get("blocking") or {}).get("props") or []
    ends = task.get("action_end_blocking") or {}
    trajectories = task.get("trajectory_overlays") or []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in references:
        grouped.setdefault(row["path"], []).append(row)
    reference_lines = "\n".join(
        f"- 参考图{index}：" + "、".join(f"{row['role']} / {row['entity_id']}" for row in members)
        + "；仅承担所列角色、道具、场景或空间约束。"
        for index, members in enumerate(grouped.values(), 1)
    )
    appearance_lines = "\n".join(
        f"- {character_id}：{EPISODE_APPEARANCE_LOCKS[character_id]}"
        for character_id in task.get("visible_characters") or []
        if character_id in EPISODE_APPEARANCE_LOCKS
    ) or "- 本镜无需额外的集级人物外观锁。"
    realism = build_keyframe_realism_block(
        character_ids=list(task.get("visible_characters") or []),
        character_locks=canonical_character_assets(),
        shot_scale=str(task.get("shot_scale") or task.get("framing") or "中景"),
        lens_intent=str(task.get("lens_intent") or task.get("angle_id") or "真实电影镜头"),
        action=str(task.get("canonical_script_action") or ""),
        expression_arc=str(task.get("expression_arc") or "") or None,
        eyeline_target=str(task.get("eyeline_target") or "") or None,
    )
    return f"""用途：historical-scene；E40 竖屏短剧的单一连续电影首帧，不是拼贴板、角色卡或空间示意图。
剧本原文（逐字绑定）：{task['canonical_script_action']}

空间解析顺序（不可跳级）：{task['episode_global_space_map_id']} → {task['global_space_map_id']} → {subspace['subspace_id']} → 人物/物品站位。
房间：{task['room_id']}；区域：{', '.join(subspace['zone_ids'])}；机位：{task['angle_id']}；轴线：{subspace['axis_id']}。
可见固定元素：{', '.join(subspace['visible_fixed_element_ids'])}。
起始人物站位：{describe_rows(actors, 'character_id')}。
起始物品站位：{describe_rows(props, 'prop_id')}。
动作终态人物：{describe_rows(ends.get('characters') or [], 'character_id')}。
动作终态物品：{describe_rows(ends.get('props') or [], 'prop_id')}。
轨迹权威：{json.dumps(trajectories, ensure_ascii=False, separators=(',', ':'))}。
本镜允许入画角色（仅这些）：{', '.join(task.get('visible_characters') or [])}。
其余 canonical 角色仅用于整场连续性身份传递，必须保持在镜外，不得生成入画。
首帧只画“起始人物站位”和“起始物品站位”；动作终态仅用于预留可执行轨迹，终态人物或物品不得提前出现。

输入参考：
{reference_lines}

E40 集级出镜外观硬锁（不可被通用“古装美感”改写）：
{appearance_lines}

{realism}

生成要求：把前三类空间图只当作几何/机位蓝图，不把图中的线条、标注、网格或文字画进正片。以场景参考建立真实王府花厅，以人物参考锁定年龄、脸型、发型、服饰与性别；同一人物只能出现一次。首帧必须呈现剧本动作的真实起始瞬间，并让后续动作轨迹在锁定子空间内物理可执行。保持古装时代、9:16 电影写实、真实透视、人物脚底落地、固定廊柱/长案/帘幕关系清楚。
禁止：身份漂移、增删或合并人物、现代物件、错误武器、错误动作因果、穿墙、穿柱、瞬移、镜像翻转、分屏、拼贴、角色设定板、俯视平面图、任何文字/字幕/LOGO/水印。
"""


def compile_task(task: dict[str, Any], prompt_dir: Path, source_script_sha: str) -> dict[str, Any]:
    # The transport order is itself authoritative: episode map -> place map ->
    # shot subspace -> people/props.  This prevents identity references from
    # becoming an accidental substitute for spatial planning.
    references = map_bindings(task)
    references.extend(character_bindings(task))
    references.extend(prop_bindings(task))
    scene = binding(
        str(SCENE_ASSET["role"]), str(SCENE_ASSET["entity_id"]),
        str(SCENE_ASSET["path"]), str(SCENE_ASSET["qa_report"]),
    )
    references.append(scene)
    transported_references = transport_bindings(task, references)
    prompt = make_prompt(task, transported_references)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{task['task_key']}-QA-V2.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    source_action = str(task["canonical_script_action"])
    prompt_contract = {
        "schema": "qingshan.image_prompt_contract.v2",
        "shot_id": task["task_key"],
        "source_script_sha256": source_script_sha,
        "source_action": source_action,
        "source_action_sha256": hashlib.sha256(source_action.encode("utf-8")).hexdigest(),
        "visible_characters": list(task.get("visible_characters") or []),
        "canonical_characters": list(task.get("canonical_characters") or []),
        "canonical_props": list(task.get("canonical_props") or []),
        "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
        "reference_bindings": references,
        "spatial_continuity": {
            "mode": "SAME_SPACE_CONTINUOUS",
            "policy_source": "PER_UNIT_SCRIPT_CONTENT",
            "anchor_scope": "LOCKED_EPISODE_PLACE_SUBSPACE_START_FRAME",
            "scene_id": task["scene_id"],
        },
        "status": "PASS",
        "failures": [],
        "human_realism_contract_version": HUMAN_REALISM_CONTRACT_VERSION,
        "semantic_anchor_policy_version": "1.0.0",
    }
    compiled = deepcopy(task)
    compiled.update({
        "task_key": f"{task['task_key']}-QA-V2",
        "shot_id": task["task_key"],
        "prompt_file": portable(prompt_path),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "reference_images": stable_unique([row["path"] for row in transported_references]),
        "reference_image_sequence": transported_references,
        "reference_bindings": references,
        "prompt_contract": prompt_contract,
        "media_stage": "KEYFRAME",
        "require_semantic_anchor_evidence": True,
        "semantic_anchor_policy_version": "1.0.0",
        "prompt_realism_contract_version": HUMAN_REALISM_CONTRACT_VERSION,
        "spatial_continuity": prompt_contract["spatial_continuity"],
        "model": "gpt-image-2-pro",
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "status": "READY_FOR_PARALLEL_SUBMIT",
        "source_script_sha256": source_script_sha,
    })
    return compiled


def build(plan_path: Path, prompt_dir: Path, manifest_path: Path, units: set[str]) -> dict[str, Any]:
    if plan_path == DEFAULT_PLAN:
        upgrade_plan_v2(SOURCE_PLAN, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    source_sha = str(plan["canonical_script_sha256"])
    available = {str(task["unit_id"]): task for task in plan.get("tasks") or []}
    unknown = sorted(units - set(available))
    if unknown:
        raise ValueError(f"Unknown units: {', '.join(unknown)}")
    selected = [available[unit] for unit in available if unit in units]
    tasks = [compile_task(task, prompt_dir, source_sha) for task in selected]
    identity_rows: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for row in task["reference_bindings"]:
            if row["role"] != "character":
                continue
            identity_rows.setdefault(row["entity_id"], {
                "character_id": row["entity_id"],
                "path": row["path"],
                "sha256": row["sha256"],
                "asset_origin": row["asset_origin"],
                "qa_report": row.get("qa_report"),
            })
    identity_report_path = manifest_path.with_name(
        manifest_path.stem + "_ASSET_LIBRARY_RESOLUTION.json"
    )
    identity_report = {
        "schema": "qingshan.character_asset_library_resolution.v1",
        "gate_id": "CHARACTER-IDENTITY-ADMISSION",
        "stage": "BEFORE_KEYFRAME_PROMPT_COMPILE_AND_PAID_SUBMIT",
        "status": "PASS",
        "registry": portable(CHARACTER_REGISTRY),
        "registry_sha256": sha256_file(CHARACTER_REGISTRY),
        "returning_character_policy": "CANONICAL_NATIVE_REGISTRY_ONLY",
        "episode_new_character_policy": "EXPLICIT_EPISODE_NEW_ASSET_WITH_ADMISSION",
        "characters": list(identity_rows.values()),
        "failures": [],
    }
    identity_report_path.parent.mkdir(parents=True, exist_ok=True)
    identity_report_path.write_text(
        json.dumps(identity_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E40-REMAKE-SPATIAL-KEYFRAMES-QA-V2",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "authorization_ref": "ROGER-20260817-E40-FULL-REMAKE",
        "source_script_sha256": source_sha,
        "spatial_shot_plan_ref": portable(plan_path),
        "spatial_shot_plan_sha256": sha256_file(plan_path),
        "episode_global_space_map_ref": DEFAULT_AUTHORITY,
        "global_space_map_gate_required": True,
        "machine_gate_reports": [SPACE_QA, portable(identity_report_path), ASSET_QA, PROP_QA],
        "output_dir": "working_assets/e40_remake_20260820/spatial_keyframes_qa_v2",
        "qa_dir": "qa/e40_remake_20260820/spatial_keyframes_qa_v2",
        "retry_policy": "NO_AUTOMATIC_RETRY; FAILED_UNIT_ONLY_CHANGED_PROMPT_AND_CAP_GATE",
        "consumer_contract": {
            "purpose": "EXACT_SHA_KEYFRAME_VIDEO_SUBMIT_ADMISSION",
            "one_independent_task_per_unit": True,
            "formal_q1_admission_required_after_harvest": True,
        },
        "excluded_retry_cap_units": ["R01", "R06A"],
        "tasks": tasks,
        "blocked_tasks": [],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--prompt-dir", default=str(DEFAULT_PROMPT_DIR))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--units", default="R02,R03,R04,R05,R06B,R06C,R07,R08",
        help="Comma-separated independent units; default excludes retry-cap R01/R06A",
    )
    args = parser.parse_args()
    plan_path = resolve(args.plan)
    if plan_path == DEFAULT_PLAN:
        upgrade_plan_v2(SOURCE_PLAN, plan_path)
    units = {value.strip() for value in args.units.split(",") if value.strip()}
    manifest = build(plan_path, resolve(args.prompt_dir), resolve(args.manifest), units)
    print(json.dumps({"status": manifest["status"], "task_count": len(manifest["tasks"]), "units": [t["unit_id"] for t in manifest["tasks"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
