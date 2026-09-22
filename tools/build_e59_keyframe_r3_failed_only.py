#!/usr/bin/env python3
"""Build E59 R3 keyframes only for the current exact-SHA Q1 rejects.

The prompts are rendered afresh from structured contracts; no failed provider
prompt text is edited or reused.  Story, map, weather, camera, cast and wardrobe
remain authoritative while identity visibility and text-free composition are
made explicit.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

from build_e59_keyframe_r2_identity_repair import render_prompt
from image_model_adapter import compile_labeled_flat_identity_transport
from role_semantic_prompt_gate import role_semantic_prompt_block


ENGINE = Path(os.environ.get("NALU_ENGINE_ROOT", "/Users/rogerwu/nalu"))
WORK = Path(os.environ.get("NALU_WORK_ROOT", ENGINE / "workflow/nalu"))
PRE = WORK / "E59/preproduction"
SOURCE = PRE / "E59_KEYFRAME_IMAGE_MANIFEST_V2_DEDICATED_GPT_V2.json"
Q1 = PRE / "reports/qa/q1/E59_KEYFRAME_Q1_INDEX.json"
VERSION = os.environ.get("KEYFRAME_REPAIR_VERSION", "R3").upper()
OUT = PRE / f"E59_KEYFRAME_IMAGE_MANIFEST_{VERSION}_FAILED_ONLY.json"
PROMPT_DIR = PRE / f"prompts/keyframes_{VERSION.lower()}_failed_only"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def provider_asset_ref(row: dict) -> str:
    """Return exactly one provider @ prefix for an image binding label."""
    label = str(row.get("asset_label") or "").strip()
    return label if label.startswith("@") else f"@{label}"


def rebind_r7_references(task: dict) -> None:
    """Reduce provider-side reference competition without weakening contracts.

    R6 proved that authored blocking can coexist with visible faces, but the five-
    person shot still carried ten flat references: five identity plates plus three
    overlapping map/scene images, a prop and other context.  R7 keeps every
    structured map/scene field in the task and every machine gate unchanged while
    transmitting only identity plates, the three map levels required by the
    SCENE-AUTHORITY-LOCK gate, and its one required scene binding.  Wardrobe and
    generic-prop images are omitted from the flat provider reference list; their structured contracts
    and textual locks remain.  The three mandatory map levels stay first in the
    exact order required by SCENE-AUTHORITY-LOCK; within the character block,
    the repeatedly failing identities are placed first.  All provider labels and
    authority mappings are rebuilt atomically.
    """
    refs = list(task.get("reference_bindings") or [])
    keep_roles = {
        "character", "episode_global_space_map", "global_space_map", "subspace_layout", "scene", "prop"
    }
    selected = [row for row in refs if row.get("role") in keep_roles]
    # The legacy E59 scene binding reused the exact same top-down place-map file,
    # which consumes a second semantic label while the submitter de-duplicates the
    # byte path.  That makes later @图片 labels point at the wrong provider slot.
    # R7 uses the visually scene/action/wardrobe-approved R6 frame as a scene-only
    # composition reference; identity remains governed solely by the headshots and
    # is re-measured on the new exact output SHA.
    scene_base = PRE / "keyframes" / f"{task.get('shot_id')}-keyframe-v6.png"
    if scene_base.is_file():
        for row in selected:
            if row.get("role") == "scene":
                row["path"] = str(scene_base)
                row["sha256"] = sha(scene_base.read_bytes())
                row["qa_status"] = "PASS"
                row["kind"] = "SCENE_COMPOSITION_REFERENCE"
                row["asset_origin"] = "PRIOR_EXACT_SHA_SCENE_ACTION_QA_PASS"
                row["binding_status"] = "BOUND_EXACT_SHA"
                row["transport_note"] = (
                    "Only preserves the already-reviewed room composition, blocking, lighting and wardrobe; "
                    "never defines a face. Exact-output identity is re-measured after generation."
                )
    priority = {
        "episode_global_space_map": 0,
        "global_space_map": 1,
        "subspace_layout": 2,
        "character": 3,
        "scene": 4,
        "prop": 5,
    }
    focus_order: dict[str, int] = {}
    if task.get("shot_id") == "E59-S10-01":
        focus_order = {"CHAR-E41-BAILI-JUNZHU": 0}
    elif task.get("shot_id") == "E59-S10-04":
        focus_order = {"CHAR-E50-CHENJI": 0, "CHAR-E41-BAILI-JUNZHU": 1}
    selected.sort(key=lambda row: (
        priority.get(str(row.get("role")), 9),
        focus_order.get(str(row.get("entity_id") or ""), 10),
        str(row.get("entity_id") or ""),
    ))
    for index, row in enumerate(selected, 1):
        row["asset_label"] = f"@图片{index}"
    task["reference_bindings"] = selected
    authority = {
        str(row.get("entity_id")): provider_asset_ref(row)
        for row in selected if row.get("role") == "character"
    }
    token_payload = json.dumps(authority, ensure_ascii=False, sort_keys=True).encode("utf-8")
    transport = copy.deepcopy(task.get("identity_reference_transport") or {})
    transport["authority_map"] = authority
    transport["authority_prompt_token"] = "IDENTITY-AUTHORITY-" + sha(token_payload)[:16]
    task["identity_reference_transport"] = transport
    task["provider_reference_reduction"] = {
        "attempt": "R7",
        "reason": "REPEATED_MULTI_IDENTITY_FAILURE_REDUCE_REFERENCE_COMPETITION",
        "structured_map_contract_preserved": True,
        "provider_roles_retained": sorted(keep_roles),
        "original_reference_count": len(refs),
        "reduced_reference_count": len(selected),
    }


def rebind_r8_references(task: dict) -> None:
    """Keep R7's low-competition transport but map people in authored slot order.

    R7 retained five identities but ranked earlier cosine failures first.  In the
    five-person frame that put the provider labels in a different order than the
    screen blocking and the model turned the foreground-right adult man into a
    second woman.  R8 is a complete prompt rewrite and a deterministic remap:
    mandatory space references first, then cast in left-to-right/depth order,
    followed by the prior composition and the required prop.
    """
    rebind_r7_references(task)
    if task.get("shot_id") == "E59-S10-01":
        authored_order = {
            "CHAR-E41-SHIZI": 0,
            "CHAR-E41-BAILI-JUNZHU": 1,
            "CHAR-E50-CHENJI": 2,
        }
    else:
        authored_order = {
            "CHAR-E41-LIANGGOUER": 0,
            "CHAR-E41-LIANGMAOER": 1,
            "CHAR-E41-SHIZI": 2,
            "CHAR-E50-CHENJI": 3,
            "CHAR-E41-BAILI-JUNZHU": 4,
        }
    role_order = {
        "episode_global_space_map": 0,
        "global_space_map": 1,
        "subspace_layout": 2,
        "character": 3,
        "scene": 4,
        "prop": 5,
    }
    selected = list(task.get("reference_bindings") or [])
    # For the three-person shot R7 is the proven composition; for the five-
    # person shot R6 is the last version with the correct four-men/one-woman cast.
    scene_version = "v7" if task.get("shot_id") == "E59-S10-01" else "v6"
    scene_base = PRE / "keyframes" / f"{task.get('shot_id')}-keyframe-{scene_version}.png"
    if scene_base.is_file():
        for row in selected:
            if row.get("role") == "scene":
                row["path"] = str(scene_base)
                row["sha256"] = sha(scene_base.read_bytes())
                row["asset_origin"] = "PRIOR_EXACT_SHA_SCENE_ACTION_QA_PASS"
    selected.sort(key=lambda row: (
        role_order.get(str(row.get("role")), 9),
        authored_order.get(str(row.get("entity_id") or ""), 99),
    ))
    for index, row in enumerate(selected, 1):
        row["asset_label"] = f"@图片{index}"
    task["reference_bindings"] = selected
    task["provider_reference_reduction"]["attempt"] = "R8"
    task["provider_reference_reduction"]["reason"] = (
        "REPEATED_MULTI_IDENTITY_FAILURE_AUTHORED_SLOT_ORDER_AND_SINGLE_FEMALE_LOCK"
    )


def rebind_r10_references(task: dict) -> None:
    """Refine the identity-corrected scene without asking the model to redraw faces.

    R8 fixed cast, sex, wardrobe and blocking but still redrew several locked faces.
    A deterministic local alignment experiment proved the intended facial geometry,
    while leaving visible blend boundaries.  R10 uses that experiment only as a scene
    geometry reference and asks the provider to harmonise skin/lighting/boundaries.
    The original identity plates remain authoritative and the exact output is still
    required to pass Q1; the local composite itself is never admitted as a keyframe.
    """
    rebind_r8_references(task)
    shot_id = str(task.get("shot_id") or "")
    failed_order = {
        "E59-S10-01": {
            "CHAR-E50-CHENJI": 0,
            "CHAR-E41-SHIZI": 1,
            "CHAR-E41-BAILI-JUNZHU": 2,
        },
        "E59-S10-04": {
            "CHAR-E50-CHENJI": 0,
            "CHAR-E41-LIANGMAOER": 1,
            "CHAR-E41-BAILI-JUNZHU": 2,
            "CHAR-E41-LIANGGOUER": 3,
            "CHAR-E41-SHIZI": 4,
        },
    }.get(shot_id, {})
    selected = list(task.get("reference_bindings") or [])
    scene_base = PRE / "keyframes" / f"{shot_id}-keyframe-v9c.png"
    if not scene_base.is_file():
        raise SystemExit(f"R10 scene geometry reference missing: {scene_base}")
    for row in selected:
        if row.get("role") == "scene":
            row["path"] = str(scene_base)
            row["sha256"] = sha(scene_base.read_bytes())
            row["qa_status"] = "EXPERIMENTAL_GEOMETRY_ONLY_NOT_ADMITTED"
            row["kind"] = "FACE_GEOMETRY_AND_SCENE_REFERENCE"
            row["asset_origin"] = "LOCAL_ALIGNMENT_GEOMETRY_EXPERIMENT"
            row["binding_status"] = "BOUND_EXACT_SHA_GEOMETRY_ONLY"
            row["transport_note"] = (
                "Preserve exact face geometry, pose, framing, wardrobe and blocking; "
                "only harmonise skin tone, lighting and blend boundaries. Never redraw faces."
            )
    role_order = {
        "episode_global_space_map": 0,
        "global_space_map": 1,
        "subspace_layout": 2,
        "character": 3,
        "scene": 4,
        "prop": 5,
    }
    selected.sort(key=lambda row: (
        role_order.get(str(row.get("role")), 9),
        failed_order.get(str(row.get("entity_id") or ""), 99),
    ))
    for index, row in enumerate(selected, 1):
        row["asset_label"] = f"@图片{index}"
    task["reference_bindings"] = selected
    task["provider_reference_reduction"]["attempt"] = "R10"
    task["provider_reference_reduction"]["reason"] = (
        "IDENTITY_GEOMETRY_PRESERVING_SEAM_AND_LIGHTING_REFINEMENT"
    )


def rebind_r11_references(task: dict) -> None:
    """Final paid reroll: reduce character-reference competition to failed IDs.

    R10 demonstrated that asking the provider to preserve and reconcile every
    identity at once can re-cast the five-person shot.  R11 keeps the full cast in
    structured/prompt contracts but sends character plates only for the identities
    that still require repair. Passing faces remain pixels from the scene base.
    """
    rebind_r8_references(task)
    shot_id = str(task.get("shot_id") or "")
    focus = {
        "E59-S10-01": {"CHAR-E41-BAILI-JUNZHU": 0},
        "E59-S10-04": {
            "CHAR-E50-CHENJI": 0,
            "CHAR-E41-LIANGMAOER": 1,
            "CHAR-E41-BAILI-JUNZHU": 2,
        },
    }.get(shot_id, {})
    # The paid image adapter requires a primary native identity authority for
    # every canonical visible character.  Keep those mandatory plates, but rank
    # the failed identities first and reduce the requested visual operation to a
    # single static correction beat.
    selected = list(task.get("reference_bindings") or [])
    if shot_id == "E59-S10-01":
        scene_base = PRE / "keyframes_r10_harvest" / (
            "E59_E59-S10-01-KEYFRAME-R10_a426aad9-86fa-4525-8a9b-c75baf197b08.png"
        )
    else:
        scene_base = PRE / "keyframes" / f"{shot_id}-keyframe-v8.png"
    if not scene_base.is_file():
        raise SystemExit(f"R11 scene base missing: {scene_base}")
    for row in selected:
        if row.get("role") == "scene":
            row["path"] = str(scene_base)
            row["sha256"] = sha(scene_base.read_bytes())
            row["qa_status"] = "PASS_SCENE_CAST_BLOCKING_BASE"
            row["kind"] = "SCENE_COMPOSITION_AND_UNTARGETED_FACE_REFERENCE"
            row["asset_origin"] = "PRIOR_VISUAL_QA_SCENE_BASE"
            row["binding_status"] = "BOUND_EXACT_SHA"
    role_order = {
        "episode_global_space_map": 0,
        "global_space_map": 1,
        "subspace_layout": 2,
        "character": 3,
        "scene": 4,
        "prop": 5,
    }
    selected.sort(key=lambda row: (
        role_order.get(str(row.get("role")), 9),
        focus.get(str(row.get("entity_id") or ""), 99),
    ))
    for index, row in enumerate(selected, 1):
        row["asset_label"] = f"@图片{index}"
    task["reference_bindings"] = selected
    task["provider_reference_reduction"] = {
        "attempt": "R11",
        "reason": "SAME_FAILURE_TWICE_REDUCE_IDENTITY_REFERENCE_BUDGET",
        "structured_cast_contract_preserved": True,
        "provider_character_ids": list(focus),
        "all_visible_identity_authorities_retained": True,
        "reference_reduction_floor": "PAID_IMAGE_ADAPTER_REQUIRES_PRIMARY_NATIVE_AUTHORITY_FOR_EVERY_VISIBLE_CHARACTER",
        "action_budget_reduced_to_single_static_correction": True,
        "reduced_reference_count": len(selected),
    }


def render_compact_identity_prompt(task: dict) -> str:
    refs = task.get("reference_bindings") or []
    identities = [row for row in refs if row.get("role") == "character"]
    spaces = [row for row in refs if row.get("role") in {
        "episode_global_space_map", "global_space_map", "subspace_layout", "scene"
    }]
    wardrobes = [row for row in refs if row.get("role") == "character_wardrobe"]
    source = task.get("source_shot_contract") or {}
    role_lock = role_semantic_prompt_block(task.get("role_semantic_disambiguation") or {})
    identity_transport = task.get("identity_reference_transport") or {}
    culture = task.get("visual_culture_contract") or {}
    visible = task.get("visible_characters") or []
    id_by_entity = {str(row.get("entity_id")): row for row in identities}
    id_label = {str(row.get("entity_id")): provider_asset_ref(row) for row in identities}
    people = []
    for entity_id in visible:
        ref = id_by_entity.get(str(entity_id)) or {}
        people.append(
            f"{ref.get('entity_name') or entity_id}（{entity_id}）的脸严格复制 {provider_asset_ref(ref)}"
        )
    r5_identity_recovery = []
    if VERSION == "R5":
        r5_identity_recovery = [
            "【R5 失败降载】本轮不增加动作，不追求戏剧化表情；先保证参考人物的精确脸部几何。",
            "严禁把参考脸重新美化、平均化或改成相似演员；逐人保留眼距、眼形、鼻梁宽度、鼻尖、"
            "唇峰、下颌线、颧骨和脸长比例。所有脸正对镜头，表情中性，双眼完整可见。",
        ]
        if task.get("shot_id") == "E59-S10-01":
            r5_identity_recovery += [
                "三人横向并列半身构图：画面左世子、中央陈迹、画面右白鲤郡主；三张脸同等大小、同一焦平面。",
                "白鲤郡主必须精确复制 @图片6 的脸，不改变眼距、鼻头和下颌轮廓；她正脸看向镜头，"
                "只用眼神表达听见动静，不扭头。",
            ]
        elif task.get("shot_id") == "E59-S10-04":
            r5_identity_recovery += [
                "五人横向分层但不遮挡：画面最左梁狗儿端碗；其后从左到右梁猫儿、世子、陈迹、白鲤郡主。",
                "陈迹和白鲤郡主站在前排同一焦平面、正脸、脸部不小于画面高度的八分之一；"
                "陈迹精确复制 @图片7，白鲤郡主精确复制 @图片8。其余三人略后但仍正脸清楚。",
            ]
    r6_contract_recovery = []
    if VERSION == "R6":
        # R5 proved that all-front identity portraits improve face transport, but it
        # also overrode the authored screen slots, depth planes and wardrobe.  R6 is
        # a complete rewrite from the structured contract: preserve the identity
        # visibility win while restoring the exact blocking and readable entry beat.
        r6_contract_recovery = [
            "【R6 合同恢复】这不是人物合影或身份照。严格执行下列银幕槽位、深度平面和入场动作；"
            "不得为了露出正脸而交换人物位置，也不得把所有人排成同一平面。",
            "所有人物脸仍须清楚可测：正面或轻微三分之四侧面、双眼可见、无遮挡；"
            "景深不能虚化任何具名人物的脸。",
        ]
        if task.get("shot_id") == "E59-S10-01":
            r6_contract_recovery += [
                "固定三人中近景：世子在画面左侧主动作平面，身体刚开始猛转向画外，脸为可识别的"
                "三分之四侧面；白鲤郡主在画面中央稍后反应平面；陈迹在画面右侧主平面。",
                "白鲤郡主绝不能移到画右，陈迹绝不能移到中央。世子的转身起势必须一眼可读，"
                "但只拍起势，不拍扬声结果。",
                "世子穿绛紫锦缎宋制圆领袍、金线小面积纹缘、玉带与束发冠；不得生成黑袍。"
                "陈迹穿灰布交领短袍；白鲤郡主穿月白宋制大袖对襟褙子与交领长裙。",
            ]
        elif task.get("shot_id") == "E59-S10-04":
            r6_contract_recovery += [
                "固定五人中近景并压缩纵深但不改槽位：梁狗儿在前景画左举大碗；梁猫儿在前景画右；"
                "世子在画面中央中层；陈迹在背景画左；白鲤郡主在背景画右。",
                "陈迹和白鲤郡主虽在背景，脸部仍不小于画面高度八分之一、清楚对焦、无遮挡；"
                "陈迹精确复制 @图片7，白鲤郡主精确复制 @图片8。",
                "世子穿绛紫锦缎宋制圆领袍并保留金线小面积纹缘，绝不能变成黑袍；"
                "梁狗儿土褐粗布袍，梁猫儿蓝灰短褐，陈迹灰布交领短袍，白鲤月白宋制褙子。",
                "满桌狼藉碗碟位于前景下部，梁狗儿的大碗停在半空；只表现这一入场状态。",
            ]
    if VERSION == "R7":
        shot_id = str(task.get("shot_id") or "")
        common = [
            f"【E59 R7 多人物身份恢复｜{shot_id}】",
            "写实北宋中国电影单帧，竖屏9:16，2K；不是人物设定照，不是拼贴。",
            "本轮降低动作预算：只表现动作开始前一瞬，不增加第二动作，不追求夸张表情。",
            "每个具名人物只出现一次；脸部写实、清楚、无遮挡、双眼可见，不混脸、不换脸、不复制人。",
            "身份图权重最高，空间图只决定站位，服装图只决定服装，道具图只决定道具；各参考不得越权。",
        ]
        identity_lines = [
            f"{row.get('entity_name') or row.get('entity_id')} 的脸只复制 {provider_asset_ref(row)}；"
            "保持眼距、鼻梁鼻尖、唇形、颧骨、下颌与脸长。"
            for row in identities
        ]
        if shot_id == "E59-S10-01":
            body = [
                "构图固定：世子在画左前景，白鲤郡主在画面中央稍后，陈迹在画右前景；绝不交换。",
                "世子身体刚开始转向画外，脸保持清楚的三分之四侧面；白鲤与陈迹看向世子。只拍起势。",
                "世子绛紫金缘宋制锦袍；白鲤月白宋制褙子；陈迹灰布交领短袍。不得生成黑袍。",
                f"白鲤郡主尤其必须保持 {id_label.get('CHAR-E41-BAILI-JUNZHU')} 的原始脸部几何，不做网红化美化。",
            ]
        else:
            body = [
                "构图固定：梁狗儿前景画左举大碗；梁猫儿前景画右；世子中央中层；陈迹背景画左；白鲤郡主背景画右。",
                "五张脸全部清楚对焦；背景两人的脸仍不小于画面高度八分之一，无遮挡、不虚化。",
                f"陈迹尤其必须逐点复制 {id_label.get('CHAR-E50-CHENJI')}；白鲤郡主逐点复制 {id_label.get('CHAR-E41-BAILI-JUNZHU')}。",
                "世子绛紫金缘宋制锦袍；梁狗儿土褐粗布袍；梁猫儿蓝灰短褐；陈迹灰布交领短袍；白鲤月白宋制褙子。",
                "前景下部是满桌空碗碟，梁狗儿的大碗悬在半空；不要再增加动作。",
            ]
        refs_line = "；".join(
            f"{provider_asset_ref(row)}={row.get('role')}:{row.get('entity_name') or row.get('entity_id')}"
            for row in refs
        )
        return "\n".join([
            *common,
            *identity_lines,
            *body,
            f"入场态：{source.get('entry_state')}。禁止提前画出结果态。",
            f"机位与轴线：{source.get('camera')}；{source.get('axis')}。",
            "角色语义消歧硬锁：" + role_lock,
            "参考映射：" + refs_line + "。",
            "视觉文化档案：QINGSHAN_NORTHERN_SONG_EASTERN_CINEMATIC。东方色彩为低饱和黛青、月白、赭石、灰绿、烟墨；"
            "暖烛光与自然灰天；严格禁止欧洲中世纪骑士、西式板甲、哥特式建筑、黑金奇幻与蓝橙商业大片调色。",
            "禁止任何可读文字、字幕、logo、水印、地图标注、现代物、半截人、畸形手。",
        ])
    if VERSION == "R8":
        shot_id = str(task.get("shot_id") or "")
        refs_line = "；".join(
            f"{provider_asset_ref(row)}={row.get('role')}:{row.get('entity_name') or row.get('entity_id')}"
            for row in refs
        )
        if shot_id == "E59-S10-01":
            body = [
                "以 R7 三人构图为底，只纠正陈迹的脸；不改变机位、站位、服装、光线或动作。",
                f"画左世子保持绛紫宋袍与转身起势，脸只复制 {id_label.get('CHAR-E41-SHIZI')}。",
                f"中央白鲤郡主保持月白宋制褙子，脸只复制 {id_label.get('CHAR-E41-BAILI-JUNZHU')}。",
                f"画右成年男性陈迹保持灰布交领短袍；他的脸必须逐点复制 {id_label.get('CHAR-E50-CHENJI')}，尤其保持眼距、窄长脸、鼻梁鼻尖、唇形和下颌，不得换成相似演员。",
                "全画面恰好三人，三张脸清楚、无遮挡、不混脸、不复制人；只拍世子转身起势，不拍扬声结果。",
            ]
            title = f"【E59 R8 陈迹身份纠错｜{shot_id}】"
        else:
            body = [
                "以 R6 五人构图为底，只纠正人物身份、性别和服装；不改变机位、站位、光线或动作。",
                "全画面恰好五人：四名成年男性、一名成年女性。白鲤郡主是唯一女性；梁猫儿是成年男性，绝不能画成女性。",
                f"画面前景左：成年男性梁狗儿，粗壮宽肩、包巾、土褐粗麻袍，脸只复制 {id_label.get('CHAR-E41-LIANGGOUER')}，右手托住大碗。",
                f"画面前景右：成年男性梁猫儿，精瘦、包巾、蓝灰粗布短褐，脸只复制 {id_label.get('CHAR-E41-LIANGMAOER')}。不得女相、不得发髻、不得裙装。",
                f"画面中央中层：成年男性世子，绛紫金缘宋制锦袍，脸只复制 {id_label.get('CHAR-E41-SHIZI')}。",
                f"画面背景左：成年男性陈迹，灰布交领短袍，脸只复制 {id_label.get('CHAR-E50-CHENJI')}。",
                f"画面背景右：成年女性白鲤郡主，月白宋制褙子，脸只复制 {id_label.get('CHAR-E41-BAILI-JUNZHU')}。她是唯一女性。",
                "五人各出现一次，脸清楚、无遮挡、不混脸、不复制人；不要把男性变成年轻女子。",
                "桌面下部保留满桌空碗碟，梁狗儿的大碗停在半空；只表现这一入场状态，不增加第二动作。",
            ]
            title = f"【E59 R8 五人身份纠错｜{shot_id}】"
        return "\n".join([
            title,
            "写实北宋中国电影单帧，竖屏9:16，2K。",
            *body,
            f"入场态：{source.get('entry_state')}。禁止提前画出结果态。",
            f"机位与轴线：{source.get('camera')}；{source.get('axis')}。",
            "角色语义消歧硬锁：" + role_lock,
            "参考映射：" + refs_line + "。身份图只定义对应人物的脸；地图只定义空间；场景参考只定义构图；道具图只定义大碗。",
            "视觉文化档案：QINGSHAN_NORTHERN_SONG_EASTERN_CINEMATIC。低饱和黛青、月白、赭石、灰绿、烟墨；自然东方肤色。",
            "明确禁止：" + "、".join(str(value) for value in culture.get("forbidden_influences") or []) + "。",
            "禁止任何可读文字、字幕、logo、水印、地图标注、现代物、欧洲中世纪骑士、西式板甲、哥特式建筑、黑金蓝橙魔幻调色、半截人、畸形手。",
        ])
    if VERSION == "R10":
        shot_id = str(task.get("shot_id") or "")
        scene_ref = next((provider_asset_ref(row) for row in refs if row.get("role") == "scene"), "")
        refs_line = "；".join(
            f"{provider_asset_ref(row)}={row.get('role')}:{row.get('entity_name') or row.get('entity_id')}"
            for row in refs
        )
        if shot_id == "E59-S10-01":
            identity_rule = (
                f"尤其保持画右陈迹与 {id_label.get('CHAR-E50-CHENJI')} 完全相同的窄长脸、眼距、"
                "鼻梁鼻尖、唇形与下颌；画左世子和中央白鲤也不得重画。"
            )
        else:
            identity_rule = (
                f"尤其保持背景左陈迹与 {id_label.get('CHAR-E50-CHENJI')}、前景右梁猫儿与 "
                f"{id_label.get('CHAR-E41-LIANGMAOER')}、背景右白鲤郡主与 "
                f"{id_label.get('CHAR-E41-BAILI-JUNZHU')} 的精确脸部几何；其余两人也不得重画。"
            )
        return "\n".join([
            f"【E59 R10 面部几何保留精修｜{shot_id}】",
            "写实北宋中国电影单帧，竖屏9:16，2K。这是一项局部融合精修，不是重新创作画面。",
            f"以 {scene_ref} 为唯一画面底稿：像素级保持全部人物数量、性别、脸型几何、五官位置、表情、头部角度、身体姿势、站位、服装、器皿、机位、构图、背景和光线方向。",
            "只允许修复面部与周围皮肤之间不自然的拼接边界、肤色过渡、颗粒、锐度和受光一致性；让脸自然融入原画。",
            "绝对禁止重新生成、替换、美化、年轻化、平均化任何一张脸；不得移动五官、改变脸宽脸长、眼距、鼻形、嘴形、下颌或发际线。",
            identity_rule,
            "每个具名人物只出现一次；不得新增人物、删除人物、复制人、换性别、换服装、换站位或改变动作。",
            "角色动作归属硬锁：" + role_lock,
            "身份图只用于核对现有脸部几何，不能作为重新画一张相似演员脸的许可。地图只定义空间，场景底稿定义全部可见像素关系。",
            "参考映射：" + refs_line + "。",
            "视觉文化档案：QINGSHAN_NORTHERN_SONG_EASTERN_CINEMATIC；保持低饱和黛青、月白、赭石、灰绿、烟墨和自然东方肤色。",
            "明确禁止：" + "、".join(str(value) for value in culture.get("forbidden_influences") or []) + "。",
            "禁止任何可读文字、字幕、logo、水印、地图标注、现代物、欧洲中世纪骑士、西式板甲、哥特式建筑、西方魔幻、黑金蓝橙调色、半截人、畸形手。",
        ])
    if VERSION == "R11":
        shot_id = str(task.get("shot_id") or "")
        scene_ref = next((provider_asset_ref(row) for row in refs if row.get("role") == "scene"), "")
        refs_line = "；".join(
            f"{provider_asset_ref(row)}={row.get('role')}:{row.get('entity_name') or row.get('entity_id')}"
            for row in refs
        )
        if shot_id == "E59-S10-01":
            body = [
                f"以 {scene_ref} 为唯一画面底稿，严格保留画左世子、中央白鲤郡主、画右陈迹三人及全部构图像素关系。",
                f"只纠正中央白鲤郡主的身份：她的脸精确复制 {id_label.get('CHAR-E41-BAILI-JUNZHU')}，保留参考脸的眼距、眼形、鼻梁鼻尖、唇形、脸长与下颌。",
                "画左世子和画右陈迹的脸、服装、姿势与位置沿用底稿，禁止重画、替换或美化；陈迹现有身份已通过诊断，不得改变。",
                "全画面恰好三人；只拍世子转身起势，不改变任何动作、背景或光线。",
            ]
        else:
            body = [
                f"以 {scene_ref} 为唯一画面底稿，严格保留原有四名成年男性和一名成年女性、五人槽位、服装、桌面空碗、大碗、机位与背景。",
                "绝对不得把任何男性改成女性；白鲤郡主是唯一女性。不得新增、删除、复制或交换人物。",
                f"只纠正三张失败身份：背景画左陈迹复制 {id_label.get('CHAR-E50-CHENJI')}；前景画右成年男性梁猫儿复制 {id_label.get('CHAR-E41-LIANGMAOER')}；背景画右白鲤郡主复制 {id_label.get('CHAR-E41-BAILI-JUNZHU')}。",
                "前景画左梁狗儿和中央世子的脸已经通过，不提供新身份图，必须逐像素沿用底稿，禁止重画。",
                "梁猫儿必须保持成年男性、精瘦、包巾、蓝灰短褐；不得女相、发髻或裙装。只表现梁狗儿举碗入场状态，不增加第二动作。",
            ]
        return "\n".join([
            f"【E59 R11 身份参考降载纠错｜{shot_id}】",
            "写实北宋中国电影单帧，竖屏9:16，2K。这是失败两次后的单目标降载修复，不是重新创作。",
            *body,
            "角色动作归属硬锁：" + role_lock,
            "参考映射：" + refs_line + "。身份图只定义所标人物的脸；地图只定义空间；场景底稿定义构图、未修人物和全部非脸像素；道具只定义大碗。",
            "视觉文化档案：QINGSHAN_NORTHERN_SONG_EASTERN_CINEMATIC；保持低饱和黛青、月白、赭石、灰绿、烟墨和自然东方肤色。",
            "明确禁止：" + "、".join(str(value) for value in culture.get("forbidden_influences") or []) + "。",
            "禁止任何可读文字、字幕、logo、水印、地图标注、现代物、欧洲中世纪骑士、西式板甲、哥特式建筑、西方魔幻、黑金蓝橙调色、半截人、畸形手。",
        ])
    return "\n".join([
        f"【E59 {VERSION} 身份优先首帧｜{task.get('shot_id')}】",
        "写实北宋中国武侠电影单帧，竖屏9:16，2K。",
        f"只拍动作开始前的静止入场状态：{source.get('entry_state')}。不拍结果态。",
        "人物身份是最高优先级：" + "；".join(people) + "。",
        "身份权威传输令牌：" + str(identity_transport.get("authority_prompt_token") or "") + "。",
        "每个具名人物只出现一次，正面或轻微三分之四侧面，脸部清楚、无遮挡、占画面足够面积；"
        "多人横向拉开，不交叠、不背脸、不低头、不远小脸。",
        *r5_identity_recovery,
        *r6_contract_recovery,
        "角色动作归属硬锁：" + role_lock,
        "只允许这些具名人物入画：" + "、".join(
            str((id_by_entity.get(str(entity_id)) or {}).get("entity_name") or entity_id)
            for entity_id in visible
        ) + "。不得增加群众、侍从、倒影或复制人。",
        "身份参考：" + "；".join(
            f"{provider_asset_ref(row)} 只定义 {row.get('entity_name') or row.get('entity_id')} 的脸"
            for row in identities
        ) + "。不得混脸或平均脸。",
        "服装参考：" + "；".join(
            f"{provider_asset_ref(row)} 只定义 {row.get('entity_name') or row.get('entity_id')} 的服装"
            for row in wardrobes
        ) + "。服装参考不得改变脸。" if wardrobes else
        "服装依据结构化合同逐人锁定，不得自行换色、换款或把贵胄锦袍改成黑衣。",
        "空间参考：" + "；".join(
            f"{provider_asset_ref(row)} 只定义空间布局"
            for row in spaces
        ) + "。不得把地图文字、网格或俯视图带进画面。",
        f"保持原机位：{source.get('camera')}；保持原轴线：{source.get('axis')}。",
        "视觉文化档案：" + str(culture.get("profile_id") or "") + "。",
        "保持合同天气、光线和东方暖烛/冷灰云海色调；禁止西方魔幻、黑金蓝橙调色。",
        "明确禁止：" + "、".join(str(value) for value in culture.get("forbidden_influences") or []) + "。",
        "画面中任何纸张、钱币、旗帜、器皿和背景均不得出现可识别或类似文字的纹样；"
        "无字幕、logo、水印、现代物、畸形手、半截人、克隆脸。",
    ])


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    rejected = set(q1.get("rejected_unit_ids") or [])
    rejected_shots = {
        str(row.get("item_id")) for row in q1.get("results") or []
        if row.get("unit_id") in rejected and row.get("item_id")
    }
    if not rejected:
        raise SystemExit("Q1 has no rejected units")

    manifest = copy.deepcopy(source)
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for original in source.get("tasks") or []:
        if original.get("shot_id") not in rejected_shots:
            continue
        task = copy.deepcopy(original)
        if VERSION == "R7":
            rebind_r7_references(task)
        elif VERSION == "R8":
            rebind_r8_references(task)
        elif VERSION == "R10":
            rebind_r10_references(task)
        elif VERSION == "R11":
            rebind_r11_references(task)
        old_key = str(task["task_key"])
        task["task_key"] = old_key.replace("KEYFRAME-V2", f"KEYFRAME-{VERSION}")
        prompt_path = PROMPT_DIR / f"{task['shot_id']}-KEYFRAME-{VERSION}.txt"
        prompt_text = (render_compact_identity_prompt(task) if VERSION != "R3" else render_prompt(task).replace(
            "【E59 关键帧 R2｜身份一致性失败后的完整重写】",
            f"【E59 关键帧 {VERSION}｜Q1 失败后的全新构图与身份权威重写】",
        ).replace("R2 changed", f"{VERSION} changed"))
        if VERSION in {"R7", "R8", "R10", "R11"}:
            sequence, identity_transport, prompt_text = compile_labeled_flat_identity_transport(
                task["task_key"], task.get("reference_bindings") or [], prompt_text
            )
            task["reference_bindings"] = sequence
            task["reference_image_sequence"] = sequence
            task["identity_reference_transport"] = identity_transport
            task["reference_images"] = list(dict.fromkeys(
                str(row.get("path")) for row in sequence if row.get("path")
            ))
            prompt_contract = copy.deepcopy(task.get("prompt_contract") or {})
            prompt_contract["reference_bindings"] = copy.deepcopy(sequence)
            prompt_contract["visible_characters"] = [
                str(row.get("entity_id")) for row in sequence if row.get("role") == "character"
            ]
            prompt_contract["visible_character_names"] = [
                str(row.get("entity_name") or row.get("entity_id"))
                for row in sequence if row.get("role") == "character"
            ]
            task["prompt_contract"] = prompt_contract
        prompt_text += (
            f"\n\n【{VERSION} 可测身份与文字零容忍】\n"
            "所有具名角色面部必须达到可测尺寸并清楚露出，正面或轻微三分之四侧面；"
            "多人时拉开横向距离，严禁遮脸、低头、背脸、远小脸和相互重叠。"
            "纸张、钱币、旗帜、器皿和背景均不得出现任何可识别或类似文字的纹样。"
        )
        prompt = prompt_text.encode("utf-8")
        prompt_path.write_bytes(prompt)
        task["prompt_file"] = str(prompt_path)
        task["prompt_sha256"] = sha(prompt)
        task["provider_post_allowed"] = False
        task["maximum_new_submissions"] = 1
        task["status"] = "READY_FOR_PRECHECK_NO_PROVIDER_POST"
        task["output_contract"]["expected_output_path"] = str(
            PRE / "keyframes" / f"{task['shot_id']}-keyframe-v{VERSION[1:]}.png"
        )
        task["repair_contract"] = {
            "attempt": VERSION,
            "reason": "EXACT_SHA_Q1_NOT_ADMITTED",
            "prompt_strategy": "FULL_REWRITE_FROM_STRUCTURED_CONTRACT",
            "preserved": ["MAP", "WEATHER", "SHOT_TYPE", "AXIS", "ENTRY_STATE", "CAST", "WARDROBE"],
            "changed": (["FACE_BLEND_BOUNDARY", "SKIN_TONE", "LIGHTING_HARMONISATION"]
                        if VERSION == "R10" else
                        ["IDENTITY_PRIORITY", "FACE_VISIBILITY", "IN_FRAME_SPACING", "TEXT_FREE_COMPOSITION"]),
            "source_q1": str(Q1),
        }
        tasks.append(task)

    covered = {task.get("shot_id") for task in tasks}
    missing = sorted(rejected_shots - covered)
    if missing:
        raise SystemExit(f"rejected units have no source keyframe task: {missing}")

    manifest.pop("paid_authorization", None)
    manifest["schema"] = f"qingshan.keyframe_image_manifest.{VERSION.lower()}_failed_only"
    manifest["batch_id"] = f"E59-KEYFRAME-{VERSION}-FAILED-ONLY"
    manifest["purpose"] = "Exact-SHA Q1 failed-only full prompt rewrite"
    manifest["subset_mode"] = "FAILED_Q1_UNITS_ONLY"
    manifest["provider_post_allowed"] = False
    manifest["maximum_new_submissions"] = len(tasks)
    manifest["authorization_ref"] = ""
    manifest["task_count"] = len(tasks)
    manifest["tasks"] = tasks
    manifest["blocked_tasks"] = []
    manifest["generated_by"] = Path(__file__).name
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "manifest": str(OUT), "tasks": len(tasks),
                      "rejected_units": sorted(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
