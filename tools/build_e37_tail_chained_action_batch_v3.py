#!/usr/bin/env python3
"""Compile E37 fight repair as a tail-frame chained series of short real-time shots."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "workflow/cloud_factory_migration_v1_20260724/dist_pipeline_parity/qingshan-ai-drama-pipeline"
sys.path.insert(0, str(PIPELINE))

from tools.action_sequence_continuity_gate import evaluate_batch as continuity_gate  # noqa: E402
from tools.action_direction_contract_gate import evaluate_batch as direction_gate  # noqa: E402
from tools.action_actor_ownership_gate import evaluate_batch as actor_ownership_gate  # noqa: E402
from tools.action_spatial_feasibility_gate import evaluate_batch as spatial_feasibility_gate  # noqa: E402
from tools.action_shot_design_gate import (  # noqa: E402
    contract_sha256 as action_contract_sha256,
    prompt_marker as action_prompt_marker,
    validate_task_bindings as action_binding_gate,
)
from tools.camera_motion_sequence_gate import evaluate_sequence as camera_gate  # noqa: E402
from tools.generation_dependency_topology_gate import evaluate_batch as topology_gate  # noqa: E402
from tools.performance_tempo_gate import evaluate_batch as tempo_gate  # noqa: E402
from tools.generation_prompt_optimizer import optimize_prompt, validate_batch as prompt_optimizer_gate  # noqa: E402


BASE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v2/E37_ATOMIC_ACTION_REPLACEMENT_BATCH_V2.json"
ACTION_PLAN = ROOT / "qa/e37_agentcut_20260803/direct_motion_audit_20260803/E37_V3_ATOMIC_ACTION_AND_OPENING_REPAIR_PLAN_V1.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v4"
PROMPT_DIR = ROOT / "working_assets/e37_action_replacement_v4_20260803/prompts"
QA_DIR = ROOT / "qa/e37_action_replacement_v4_20260803/pre_submit"


BEATS = [
    ("E37-R-A01", "火把撞上门内灯油，火线瞬间封住正门", "FIRE_00_GUARD_LUNGING_LEDGER_HELD_TORCH_AIRBORNE", "FIRE_01_OIL_IGNITED_GUARD_ONE_STEP_FROM_CHENJI", "火把由右上落向左下撞上灯油", "火把弹停，灯油轰燃，正门退路被火线封住"),
    ("E37-R-A02", "守宅人扑空后撞上陈迹升起的薄冰屏并明确撞退", "FIRE_01_OIL_IGNITED_GUARD_ONE_STEP_FROM_CHENJI", "FIRE_02_GUARD_RECOILED_ICE_SCREEN_UP_BEAM_CRACKING", "守宅人从画面右侧向左扑，陈迹侧身避开；守宅人扑空，本能抬起的前臂撞中陈迹掌前的小型透明冰盾", "小冰盾在前臂撞击点震裂冒白汽，守宅人沿来路明确退回画面右侧半步"),
    ("E37-R-A03", "云羊点睛唤出的纸人立即以双掌承住正在下坠的燃梁", "FIRE_02_GUARD_RECOILED_ICE_SCREEN_UP_BEAM_CRACKING", "FIRE_03_BEAM_SUPPORTED_PAPER_BURNING_WALL_VISIBLE", "云羊指尖点中纸片；纸片展开成纸人，纸人直接抬臂接住已经下坠的燃梁", "燃梁停止下坠，纸人肘部受力下沉且掌缘开始燃烧"),
    ("E37-R-A04", "云羊一拳击穿右后方酥墙，露出逃生洞", "FIRE_03_BEAM_SUPPORTED_PAPER_BURNING_WALL_VISIBLE", "FIRE_04_WALL_OPEN_EXIT_VISIBLE_BEAM_STILL_SUPPORTED", "云羊正拳由左向右击中酥墙中心", "砖土向屋外飞散，墙洞完整打开且方向清楚"),
    ("E37-R-A05", "陈迹把账册沿完整可见轨迹抛给皎兔阴神，阴神双手接稳", "FIRE_04_WALL_OPEN_EXIT_VISIBLE_BEAM_STILL_SUPPORTED", "FIRE_05_LEDGER_IN_SPIRIT_HANDS_CHENJI_TURNS_TO_FLOOR", "陈迹右手低弧抛账，账册飞行到皎兔阴神双手", "账册稳定贴在阴神胸前，陈迹双手已经腾空"),
    ("E37-R-A06", "火烧地板刚在众人脚前崩裂，陈迹立即以冰流覆盖裂口", "FIRE_05_LEDGER_IN_SPIRIT_HANDS_CHENJI_TURNS_TO_FLOOR", "FIRE_06_FLOOR_FROZEN_EXIT_LANE_STABLE_GROUP_READY", "地板沿木缝向下断裂的同时，陈迹掌心冰流由近向远紧追裂口铺开", "冰层扣住两侧地板并稳定成一条窄路，碎木已落到冰层下方"),
    ("E37-R-A07", "三人沿冰封通道依次穿过墙洞落到雨地，房屋保持站立", "FIRE_06_FLOOR_FROZEN_EXIT_LANE_STABLE_GROUP_READY", "FIRE_07_GROUP_OUTSIDE_LEDGER_SAFE_HOUSE_STILL_UP", "陈迹领头、云羊居中、皎兔阴神护账依次穿洞落地", "三人全部在屋外落稳，账册仍由阴神护在胸前，房屋尚未坍塌"),
    ("E37-R-A08", "三人落稳后，烧断的刘宅屋架才向内总塌", "FIRE_07_GROUP_OUTSIDE_LEDGER_SAFE_HOUSE_STILL_UP", "FIRE_08_HOUSE_COLLAPSED_GROUP_SAFE_GUARD_LOST", "背景燃梁砸断立柱，刘宅屋架整体向内坍塌", "三人在安全距离外面对废墟，守宅人未能逃出，账册安全"),
]


SHOT_PROMPT_LOCKS = {
    2: (
        "【特效尺寸硬约束】不要生成墙、门、整幅玻璃或贯穿画面的冰面。陈迹仅在自己掌前形成一块"
        "宽度不超过一个成人胸廓、边缘四周都能看见的小型透明冰盾；守宅人的头、双肩、腰和双脚全程无遮挡。\n"
        "【接触构图】守宅人位于画面右半侧，小冰盾位于其扑空路径前方，画面中央和左半侧保留火场背景；"
        "陈迹侧避、守宅人扑空、前臂撞盾、冰裂、右脚后撤必须按因果顺序留在画内。"
        "双手不得抓住或穿过冰盾，拳头不得成为接触点；前臂撞盾后才出现裂纹、白汽和反向后退。\n"
        "【正向空间布局】开放碰撞通道位于画面宽度42%至62%、高度30%至70%；账册和桌沿必须留在通道左侧。"
        "小冰盾斜向镜头约30度，夹在两人之间，盾宽不超过画幅16%、盾高不超过画幅32%，四边都可见；"
        "守宅人前臂沿通道进入，先接触盾面，随后才出现裂纹和白汽，任何人物被遮挡面积不得超过20%。\n"
    ),
    3: (
        "【能力所有权硬锁】只有画面后方穿黑色窄袖短打、十七岁少年云羊能够点纸成兵。"
        "前景灰衣二十岁陈迹只负责护住账册并侧身让开，陈迹的手不得触碰纸片、不得施法、不得成为纸人生成源。"
        "纸片必须从云羊清楚可见的指尖接触点展开；云羊、纸片、纸人三者的因果归属不可被前景人物遮挡或替换。\n"
        "【严格两拍】第一拍只做纸片展开、纸人落地；第二拍只做纸人抬掌接住已经在下坠的同一根梁。"
        "两拍连续发生，不插入第三件事，不省略双掌与梁下沿的接触。\n"
    ),
    7: ("【事件边界硬锁】本镜只完成三人穿洞落地；房屋全程保持站立，不得提前坍塌。\n"),
    8: ("【事件边界硬锁】首帧三人已经在屋外落稳；本镜只表现屋架向内总塌，不得重复穿洞逃生。\n"),
}


ACTION_DIRECTIONS = {
    1: ("SCREEN_RIGHT", "RIGHT_TO_LEFT", "", "SCREEN_LEFT", "TORCH_HEAD", "SPILLED_LAMP_OIL"),
    2: ("SCREEN_RIGHT", "RIGHT_TO_LEFT", "LEFT_TO_RIGHT", "SCREEN_RIGHT", "FOREARMS", "PALM_FRONT_CHEST_WIDTH_ICE_BUCKLER"),
    3: ("SCREEN_CENTER", "DOWN_TO_UP", "", "SCREEN_CENTER", "BOTH_PALMS", "FALLING_BEAM_UNDERSIDE"),
    4: ("SCREEN_LEFT", "LEFT_TO_RIGHT", "", "SCREEN_RIGHT", "RIGHT_FIST", "WEAK_WALL_CENTER"),
    5: ("SCREEN_LEFT", "LEFT_TO_RIGHT", "", "SCREEN_RIGHT", "LEDGER", "SPIRIT_BOTH_HANDS"),
    6: ("SCREEN_NEAR", "NEAR_TO_FAR", "", "SCREEN_FAR", "ICE_FLOW_FRONT", "FLOOR_RIFT"),
    7: ("SCREEN_NEAR", "NEAR_TO_FAR", "", "SCREEN_FAR", "THREE_PAIRS_OF_FEET", "OUTSIDE_RAIN_GROUND"),
    8: ("SCREEN_BACKGROUND", "TOP_TO_BOTTOM_INWARD", "", "SCREEN_BACKGROUND", "ROOF_FRAME", "HOUSE_INTERIOR"),
}

ACTOR_BY_SHOT = {
    1: "火把与灯油",
    2: "守宅人与陈迹",
    3: "云羊与纸人",
    4: "云羊",
    5: "陈迹与皎兔阴神",
    6: "陈迹",
    7: "陈迹、云羊与皎兔阴神",
    8: "烧断的刘宅主屋架",
}

SPATIAL_GEOMETRY = {
    1: (0.30, 0.70, 0.20, 0.75, "火把与火线", 0.28, 0.35, "TORCH_HEAD_TO_OIL", "FOREGROUND_CONTACT"),
    2: (0.42, 0.62, 0.30, 0.70, "盾", 0.16, 0.32, "30_DEGREES_OBLIQUE", "BETWEEN_GUARD_AND_CHENJI"),
    3: (0.25, 0.75, 0.15, 0.85, "纸人与燃梁", 0.42, 0.62, "PALMS_UNDER_BEAM", "MIDGROUND_SUPPORT"),
    4: (0.35, 0.78, 0.20, 0.82, "墙洞与碎砖", 0.38, 0.55, "FIST_NORMAL_TO_WALL", "BACKGROUND_WALL"),
    5: (0.20, 0.80, 0.25, 0.72, "账册轨迹", 0.22, 0.24, "LOW_ARC_PARALLEL_TO_FLOOR", "BETWEEN_HANDS"),
    6: (0.12, 0.88, 0.38, 0.88, "冰封窄路", 0.68, 0.42, "FLOOR_PLANE_NEAR_TO_FAR", "GROUND_PLANE"),
    7: (0.10, 0.90, 0.12, 0.92, "三人逃生队列", 0.72, 0.72, "THROUGH_WALL_OPENING", "MIDGROUND_TO_EXTERIOR"),
    8: (0.08, 0.92, 0.08, 0.92, "向内坍塌屋架", 0.78, 0.78, "TOP_DOWN_INWARD", "BACKGROUND_ONLY"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    action_plan = json.loads(ACTION_PLAN.read_text(encoding="utf-8"))
    action_shots = {
        shot["shot_id"]: shot for shot in action_plan["shots"] if shot.get("action_unit") is True
    }
    templates = base["tasks"]
    tasks = []
    prompts = {}
    optimizer_receipts = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (design_shot_id, purpose, entry, exit_state, action, result) in enumerate(BEATS, start=1):
        design_shot = action_shots[design_shot_id]
        task = copy.deepcopy(templates[min(index - 1, len(templates) - 1)])
        shot_id = f"E37-R-B{index:02d}"
        task_key = f"{shot_id}-TAIL-CHAINED-V4"
        predecessor = f"E37-R-B{index - 1:02d}-TAIL-CHAINED-V4" if index > 1 else None
        tail_ref = f"working_assets/e37_action_replacement_v4_20260803/predecessor_tails/E37-R-B{index - 1:02d}_TAIL.png" if index > 1 else None
        # Giggle accepts 4-15 second generations. Author the contact inside 1.5s,
        # then admit only the useful 2-3s edit window; never slow the action to fill 4s.
        duration = 4.0
        prompt = (
            "架空古代中国雨夜，刘宅火场，竖屏9:16，港式武侠动作片的高速清晰剪辑语法。\n"
            f"【本镜唯一叙事任务】{purpose}。\n"
            f"【首帧状态】严格继承前镜验收尾帧：{entry}。首帧已在动作中，不摆预备姿势。\n"
            f"【单一动作】{action}，必须在1.5秒内以现实速度完成。\n"
            f"【接触反馈与终态】{result}；终态清楚保持0.55秒，作为后镜唯一首帧依据。\n"
            "【机位】固定机位，轴线、人物屏幕方向和空间地理不变；冲击力仅由身体、道具、火焰、碎屑和受力反馈表达。\n"
            "【速度】REAL_TIME_1X，自然重力和正常人物步频；禁止慢动作、延长起手、重复动作、动作复位、定格摆拍。\n"
            "【剪辑余量】生成时长4秒仅供选择入点和出点；核心动作完成后只保持终态，不得新增动作。最终剪辑仅取2至3秒有效动作窗口。\n"
            "【运镜禁令】禁止smooth_roam、slow_push、overhead_reveal、摇镜、环绕、推拉、变焦、周期摆动；不得用运镜填满时长。\n"
            "【连续性】不可提前生成下一镜事件，不可省略本镜接触，不可改变账册归属、人物位置、火势方向或天气。\n"
            "无对白，仅保留与接触同步的火焰、雨、撞击、碎木和落地同期声。无字幕、无水印、无可读文字、无现代物件。\n"
        )
        prompt += SHOT_PROMPT_LOCKS.get(index, "")
        prompt += action_prompt_marker(design_shot) + "\n"
        prompt_path = PROMPT_DIR / f"{shot_id}.txt"

        task.update({
            "task_key": task_key,
            "source_id": shot_id,
            "unit_id": shot_id,
            "batch_id": "E37-TAIL-CHAINED-ACTION-V4-20260803",
            "duration": duration,
            "duration_seconds": duration,
            "resolution": "1080p",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_path": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": None,
            "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
            "prompt_optimizer_required": True,
            "camera_motion_contract": {"family": "fixed"},
            "camera_policy": "FIXED_COMPOSITION_ACTION_GEOGRAPHY_LOCK",
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "entry_action_already_in_progress": True,
                "primary_action_complete_by_seconds": 1.5,
                "result_hold_seconds": 0.55,
                "forbid_duration_filling": ["slow_motion", "replay", "reset", "extended_windup", "camera_motion"],
            },
            "edit_window_contract": {
                "provider_duration_seconds": 4.0,
                "admitted_window_seconds_min": 2.0,
                "admitted_window_seconds_max": 3.0,
                "time_stretch_forbidden": True,
                "trim_only": True,
            },
            "action_sequence_contract": {
                "chain_id": "E37_FIRE_ESCAPE_V4",
                "sequence_index": index,
                "entry_state_token": entry,
                "exit_state_token": exit_state,
                "predecessor_tail_frame_ref": tail_ref,
                "tail_to_head_identity_required": index > 1,
                "hidden_inter_shot_events_forbidden": True,
            },
            "action_direction_contract": dict(zip(
                ("entry_screen_side", "travel_direction", "recoil_direction", "terminal_screen_side", "contact_body_part", "contact_target"),
                ACTION_DIRECTIONS[index],
            )),
            "action_design_shot_id": design_shot_id,
            "action_design_contract_sha256": action_contract_sha256(design_shot),
            "status": "READY_TO_SUBMIT" if index == 1 else "WAITING_PREDECESSOR_QA_AND_TAIL",
            "dependencies_ready": index == 1,
        })
        if index == 3:
            task["requires_actor_ownership_lock"] = True
            task["action_actor_ownership_contract"] = {
                "ability_owner": "云羊",
                "inherited_foreground_actor": "陈迹",
                "forbidden_foreground_actions": ["触碰纸片", "施法", "成为纸人生成源"],
                "visible_origin_required": True,
                "required_prompt_clauses": ["只有画面后方穿黑色窄袖短打、十七岁少年云羊", "陈迹的手不得触碰纸片"],
            }
        x_min, x_max, y_min, y_max, effect_label, effect_width, effect_height, plane, depth = SPATIAL_GEOMETRY[index]
        task["requires_spatial_feasibility_gate"] = True
        task["action_spatial_feasibility_contract"] = {
                "entry_geometry_derived_from_start_frame": True,
                "entry_pose_compatible": True,
                "exit_geometry_planned": True,
                "exit_pose_compatible_with_next_shot": True,
                "exit_preserves_protected_props": True,
                "collision_corridor": {
                    "x_min": x_min,
                    "x_max": x_max,
                    "y_min": y_min,
                    "y_max": y_max,
                    "clear_of_protected_props": True,
                    "limb_path_clear": True,
                },
                "effect_geometry": {
                    "label": effect_label,
                    "max_width_ratio": effect_width,
                    "max_height_ratio": effect_height,
                    "plane_orientation": plane,
                    "depth_order": depth,
                },
                "maximum_subject_occlusion_ratio": 0.20,
                "first_contact_before_effect_feedback": True,
                "required_prompt_clauses": ["开放碰撞通道", "尾帧保留保护道具"],
        }
        if index == 2:
            task["action_spatial_feasibility_contract"]["required_prompt_clauses"].append("盾宽不超过画幅16%")
        task.pop("depends_on_task", None)
        if predecessor:
            task["depends_on_task"] = predecessor
        task["performance_spec"]["duration_seconds"] = duration
        task["performance_spec"]["motion_beats"] = [{
            "subject": ACTOR_BY_SHOT[index],
            "action": action,
            "contact_point": "提示词声明的唯一接触点",
            "direction": "保持前镜轴线与屏幕方向",
            "end_state": exit_state,
            "intent": purpose,
            "visible_causality": result,
            "expression": "正常速度受力反应，不延长、不重复",
            "viewer_read": "动作、接触、反馈和终态均在固定机位中可见",
        }]
        prompt, optimizer_receipt = optimize_prompt(task, prompt, tasks)
        prompt_path.write_text(prompt, encoding="utf-8")
        task["prompt_sha256"] = sha(prompt_path)
        task["prompt_optimizer_receipt"] = optimizer_receipt
        prompts[task_key] = prompt
        optimizer_receipts.append(optimizer_receipt)
        tasks.append(task)

    config = copy.deepcopy(base)
    config.update({
        "schema": "qingshan.episode_streaming_video_batch.v3",
        "status": "READY_FOR_TAIL_CHAINED_ACTION_SUBMIT",
        "batch_id": "E37-TAIL-CHAINED-ACTION-V4-20260803",
        "concurrency": 8,
        "output_dir": "working_assets/e37_action_replacement_v4_20260803/outputs",
        "qa_dir": "qa/e37_action_replacement_v4_20260803",
        "generation_scheduling_policy": {
            "default": "INDEPENDENT_PARALLEL",
            "continuity_critical": "TAIL_CHAINED_SERIAL",
            "episode_batch_barrier": False,
            "rule": "Only shots in the same tail-frame chain wait; all unrelated ready tasks remain concurrent.",
        },
        "minimum_native_generation_height": 1080,
        "formal_release_resolution": "1080x1920",
        "allowed_generation_models": ["seedance-2.0-pro", "seedance-2.0-normal"],
        "tasks": tasks,
    })
    config_path = OUT_DIR / "E37_TAIL_CHAINED_ACTION_REPLACEMENT_BATCH_V4.json"
    write_json(config_path, config)

    reports = {
        "camera": camera_gate(tasks, prompts),
        "tempo": tempo_gate(tasks),
        "continuity": continuity_gate(tasks),
        "direction": direction_gate(tasks),
        "actor_ownership": actor_ownership_gate(tasks, prompts),
        "spatial_feasibility": spatial_feasibility_gate(tasks, prompts),
        "prompt_optimizer": prompt_optimizer_gate(tasks, prompts),
        "action_design_binding": {
            "status": "PASS" if not action_binding_gate(action_plan, tasks, ROOT) else "FAIL",
            "failures": action_binding_gate(action_plan, tasks, ROOT),
        },
        "topology": topology_gate(tasks),
    }
    QA_DIR.mkdir(parents=True, exist_ok=True)
    for name, report in reports.items():
        write_json(QA_DIR / f"E37_V4_{name.upper()}_GATE.json", report)
    status = "PASS" if all(report["status"] == "PASS" for report in reports.values()) else "FAIL"
    summary = {
        "schema": "qingshan.e37_tail_chained_action_pre_submit.v1",
        "status": status,
        "short_shot_count": len(tasks),
        "total_authored_seconds": sum(float(task["duration_seconds"]) for task in tasks),
        "serial_scope": "E37_FIRE_ESCAPE_V4_ONLY",
        "global_parallelism_preserved": True,
        "gates": {name: report["status"] for name, report in reports.items()},
        "prompt_optimizer": {
            "status": "PASS" if len(optimizer_receipts) == len(tasks) else "FAIL",
            "receipts": optimizer_receipts,
        },
        "config": str(config_path.relative_to(ROOT)),
        "config_sha256": sha(config_path),
    }
    write_json(QA_DIR / "E37_V4_PRE_SUBMIT_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
