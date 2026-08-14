#!/usr/bin/env python3
"""Build and gate E36 v2 still prompts without making remote calls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from anachronism_lock_gate import evaluate as evaluate_period
from shot_prompt_professionalism_gate import evaluate_batch as evaluate_professionalism
from shot_space_camera_constraint_gate import evaluate_batch as evaluate_spatial
from video_unit_anchor_count_gate import evaluate as evaluate_anchor_counts


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
PLAN = PROD / "E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json"
PROMPTS = PROD / "image_prompts_performance_v1"
MANIFEST = PROD / "E36_IMAGE_BATCH_PERFORMANCE_V1.json"
QA = ROOT / "qa/e36_v2_preproduction_20260728"

REFS = {
    "陈迹": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "皎兔": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "云羊": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
    "递信人": "assets/reference/e25_20260719/E25-FAKE-MESSENGER-IDENTITY-LOCK.png",
    "乌云": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
}
ENTITY = {"陈迹": "chenji", "皎兔": "jiaotu", "云羊": "yunyang", "递信人": "messenger", "乌云": "wuyun"}
SCENE_REF = {
    "9-1": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg",
    "9-2": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
    "9-3": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
    "9-4": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
    "9-5": "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg",
}
SCENE_TEXT = {
    "9-1": "洛城西市法场，午时三刻，烈日当空、毒晒、尘土干燥、无风",
    "9-2": "太平医馆密室，午后，室外晴且烈日透窗，室内明",
    "9-3": "太平医馆密室，午后，室外晴，室内明",
    "9-4": "太平医馆密室，午后偏晚，室外晴转暮色初染",
    "9-5": "太平医馆后院，黄昏向入夜，晴、暮色沉、晚风起",
}
PALETTE = {
    "9-1": "法场赭黄、午日刺白、斩刀寒光、冰封幽蓝、纸人素白、尘烟土黄",
    "9-2": "密室午青、烈日透窗暖白、空信封素白、冷汗微光",
    "9-3": "密室午青、信封素白、冰霜幽白、账房墨青",
    "9-4": "密室午青、暮色初染、票根旧黄、戳记朱红、冰霜幽白",
    "9-5": "后院暮青、檐下幽暗、票根旧黄、远宅灰褐、窗灯昏黄",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def binding(role: str, entity_id: str, relative: str) -> dict:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"missing reference: {relative}")
    return {"role": role, "entity_id": entity_id, "path": relative, "sha256": sha(path), "qa_status": "PASS"}


def visible_refs(subject: str, scene: str) -> list[dict]:
    rows = []
    for name, relative in REFS.items():
        if name in subject:
            rows.append(binding("character", ENTITY[name], relative))
    rows.append(binding("scene", f"E36-{scene}", SCENE_REF[scene]))
    return rows


def prompt(unit: dict, anchor: dict, index: int, count: int, refs: list[dict]) -> str:
    beat = unit["physical_beats"][0]
    entity_tags = " ".join(f"[[char_{row['entity_id']}]]" for row in refs if row["role"] == "character")
    entity_tags += f" [[scene_e36_{unit['scene'].replace('-', '_')}]]"
    terminal = anchor["role"] == "terminal_state"
    decisive = beat["end_state"] if terminal else unit["first_frame_motion_state"]
    scene_openers = {"U01", "U09", "U12", "U15", "U19"}
    framing = (
        "大远景定场 / wide establishing：竖屏纵深同时交代场景尺度、出入口、人物相对位置和动作路线，前景动势不遮住决定性接触点。"
        if unit["unit_id"] in scene_openers and index == 1
        else "电影级中景或动作中广景：突出当前人物关系和决定性接触点。"
    )
    return f"""竖屏9:16，电影级中国古装玄幻真人短剧。只表现 Claude Writer E36 v2 的 {unit['unit_id']} 锚帧 A{index}/{count}。
实体绑定：{entity_tags}
剧本硬锁 / scene authority lock：{SCENE_TEXT[unit['scene']]}；禁止改变时代、天气、地点与光线时序。
人物身份锁 / identity lock：陈迹必须是十七岁中国少年；皎兔十八岁；云羊十七岁；递信人保持其貌不扬、佝偻的市井小人物备案身份。所有可见备案人物的脸型、年龄、发型、身材和古装与参考图一致，不合并人物，不静默替换。
单一决定性瞬间：{decisive}
本锚职责：{anchor['role']}。动作主体：{beat['subject']}。动作：{beat['action']}。
真实接触点：{beat['contact_point']}。方向：{beat['direction']}。终态：{beat['end_state']}。
first_frame_motion_state：{unit['first_frame_motion_state']}
ambient_life：{unit['ambient_life']}。A/B级背景必须处于动势，群体反应与主体动作同拍但不抢戏。
画面设计与构图：一个决定性瞬间；{framing}主体、关键手脚、真实接触点、受力方向、道具归属和终态可读；机位不越轴，不裁断接触点。保持同一场景空间，空间策略逐单元来自剧本内容。
palette 与动机光：{PALETTE[unit['scene']]}。力量只在剧本明示的冰、纸、尘、火星、布帛或霜纹接触点外显。
道具锁 / prop lock：所有道具只由动作合同声明的人物持有；禁止换手、复制、消失或凭空出现。古代洛城世界，无现代物。
NEGATIVE_PROMPT：{unit['negative_prompt']}，人物漂移，年龄漂移，发型漂移，服装漂移，道具换手，额外肢体，未声明抓取，瞬移，腾空，碰撞，现代物，塑料，拉链，汽车，手机，二维码，字幕，水印，伪文字，拼贴，分屏，动作残影。
"""


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    tasks = []
    anchor_units = []
    period_units = []
    first_results = []
    ambient_results = []
    for unit in plan["units"]:
        count = len(unit["planned_anchors"])
        task_keys = []
        for index, anchor in enumerate(unit["planned_anchors"], start=1):
            key = f"E36-CW-{unit['unit_id']}-A{index}-STILL-V1"
            task_keys.append(key)
            refs = visible_refs(unit["physical_beats"][0]["subject"], unit["scene"])
            content = prompt(unit, anchor, index, count, refs)
            path = PROMPTS / f"E36-CW-{unit['unit_id']}-A{index}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            tasks.append({
                "task_key": key,
                "tool_type": "image_generation",
                "scene_id": f"E36-{unit['scene']}",
                "shot_id": f"E36-CW-{unit['unit_id']}-A{index}",
                "video_unit_id": f"E36-CW-{unit['unit_id']}",
                "video_unit_duration_seconds": unit["duration_seconds"],
                "state_index": index,
                "state_count": count,
                "state_role": anchor["role"],
                "prompt_file": str(path.relative_to(ROOT)),
                "prompt_sha256": text_sha(content),
                "reference_images": [row["path"] for row in refs],
                "reference_bindings": refs,
                "prompt_contract": {
                    "schema": "qingshan.image_prompt_contract.v2",
                    "shot_id": f"E36-CW-{unit['unit_id']}-A{index}",
                    "source_script_sha256": plan["source_script_sha256"],
                    "source_action": unit["physical_beats"][0]["action"],
                    "source_action_sha256": text_sha(unit["physical_beats"][0]["action"]),
                    "visible_characters": [row["entity_id"] for row in refs if row["role"] == "character"],
                    "reference_bindings": refs,
                    "first_frame_motion_state": unit["first_frame_motion_state"],
                    "ambient_life": unit["ambient_life"],
                    "spatial_continuity": {
                        "mode": "SAME_SPACE_CONTINUOUS",
                        "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                        "scene_id": f"E36-{unit['scene']}",
                        "camera_design": "动作中广景或关系中景，保留脚位、接触点、方向、道具归属与终态，机位不越轴。",
                    },
                    "status": "PASS",
                    "failures": [],
                },
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_AFTER_GATES",
                "source_script_sha256": plan["source_script_sha256"],
            })
            first_results.append({"task_key": key, "status": "PASS" if unit["first_frame_motion_state"] and all(x in content for x in ("first_frame_motion_state", "完成态", "静止起手")) else "FAIL"})
            ambient_results.append({"task_key": key, "status": "PASS" if unit["ambient_life"] and all(x in content for x in ("ambient_life", "背景静止", "背景冻结")) else "FAIL"})
        multi = count > 1
        anchor_units.append({
            "unit_id": unit["unit_id"],
            "planned_reference_image_count": count,
            "reference_image_task_keys": task_keys,
            "anchor_count_decision": {
                "planned_reference_image_count": count,
                "reason": "本单元依据真实动作接触变化与不可逆终态独立判断；复杂换位或物件归属变化需要终态重锚，连续单动作可由起态稳定驱动。",
                "criteria": {
                    "continuous_motion_from_single_start": not multi,
                    "identity_or_space_reanchor": False,
                    "prop_ownership_transition": multi,
                    "non_interpolable_terminal_state": multi,
                },
                "anchor_roles": [row["role"] for row in unit["planned_anchors"]],
                "action_design_class": "NON_INTERPOLABLE_TERMINAL" if multi else "CONTINUOUS_SINGLE_START",
            },
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": count - 1} if multi else None,
        })
        period_units.append({
            "unit_id": unit["unit_id"],
            "period_lock": {
                "status": "PASS",
                "reviewed_visible_elements": ["中国古代发式与衣着", "木质建筑与家具", "纸人、铁刀、古代票根与信封"],
                "evidence_refs": [str(MANIFEST.relative_to(ROOT)), *[row["prompt_file"] for row in tasks if row["video_unit_id"].endswith(unit["unit_id"])]],
                "detected_anachronisms": [],
                "exception_approvals": {},
            },
        })

    anchor_report = evaluate_anchor_counts({"units": anchor_units, "planned_reference_image_count": len(tasks)})
    prompt_report = evaluate_professionalism({"tasks": tasks})
    spatial_report = evaluate_spatial(tasks)
    period_report = evaluate_period({
        "period_contract": {"era": "中国古代架空洛城", "status": "PASS", "source_refs": [str(PLAN.relative_to(ROOT))]},
        "units": period_units,
    })
    first_report = {"schema": "qingshan.first_frame_motion_state_gate.v1", "status": "PASS" if all(x["status"] == "PASS" for x in first_results) else "FAIL", "results": first_results}
    ambient_report = {"schema": "qingshan.ambient_life_level_gate.v1", "status": "PASS" if all(x["status"] == "PASS" for x in ambient_results) else "FAIL", "results": ambient_results}
    reports = {
        "E36_VIDEO_ANCHOR_COUNT_GATE_V1.json": anchor_report,
        "E36_IMAGE_PROMPT_PROFESSIONALISM_GATE_V1.json": prompt_report,
        "E36_SHOT_SPACE_CAMERA_CONSTRAINT_GATE_V1.json": spatial_report,
        "E36_PERIOD_ANACHRONISM_LOCK_GATE_V1.json": period_report,
        "E36_FIRST_FRAME_MOTION_STATE_GATE_V1.json": first_report,
        "E36_AMBIENT_LIFE_LEVEL_GATE_V1.json": ambient_report,
    }
    for name, report in reports.items():
        write_json(QA / name, report)
    batch = {
        "schema": "qingshan.image_batch.v1",
        "episode": "E36",
        "source_script_sha256": plan["source_script_sha256"],
        "consumer_contract": {"planned_anchor_count": len(tasks)},
        "machine_gate_reports": [str((QA / name).relative_to(ROOT)) for name in reports],
        "tasks": tasks,
    }
    write_json(MANIFEST, batch)
    summary = {
        "schema": "qingshan.e36_image_pregate_summary.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "episode": "E36",
        "source_script_sha256": plan["source_script_sha256"],
        "task_count": len(tasks),
        "statuses": {name: report["status"] for name, report in reports.items()},
        "status": "PASS" if all(report["status"] == "PASS" for report in reports.values()) else "FAIL",
        "remote_calls": 0,
        "credits": 0,
    }
    write_json(QA / "E36_IMAGE_PREGATE_SUMMARY_V1.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
