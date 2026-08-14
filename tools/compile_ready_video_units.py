#!/usr/bin/env python3
"""Compile only video units whose complete planned still-state pool is admitted."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    from episode_video_generation_guard import generation_fingerprint
    from video_prompt_action_density_gate import validate_action_timeline
except ImportError:
    from tools.episode_video_generation_guard import generation_fingerprint
    from tools.video_prompt_action_density_gate import validate_action_timeline


ROOT = Path(__file__).resolve().parents[1]
MAX_OMNI_IMAGE_REFERENCES = 8
ACTION_VISUALIZATION_SYSTEM_PROMPT = ROOT / "codex_docs/教codex动作可视化_系统提示词_v1_20260722.md"
ACTION_VISUALIZATION_SYSTEM_PROMPT_SHA256 = "04f47991157e9a1ce3fcab7be6bf3b89ed76a2f34b52a27a0d4b393bca0c736f"
POST_PRODUCTION_DIRECTIVE = re.compile(
    r"后期|字幕|叠加|真字体|留白供|画外添加|本次画内不生成文字"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def action_visualization_system_prompt() -> str:
    if not ACTION_VISUALIZATION_SYSTEM_PROMPT.is_file():
        raise RuntimeError("CL2X-605 action-visualization system prompt is missing")
    if sha256(ACTION_VISUALIZATION_SYSTEM_PROMPT) != ACTION_VISUALIZATION_SYSTEM_PROMPT_SHA256:
        raise RuntimeError("CL2X-605 action-visualization system prompt SHA mismatch")
    return ACTION_VISUALIZATION_SYSTEM_PROMPT.read_text(encoding="utf-8").strip()


def split_even(start: float, duration: float, count: int) -> list[tuple[float, float]]:
    points = [start + duration * index / count for index in range(count + 1)]
    return [(round(points[index], 3), round(points[index + 1], 3)) for index in range(count)]


def clauses(action: str) -> list[str]:
    return [part.strip("。；， ") for part in re.split(r"[；，。]", action) if part.strip("。；， ")]


def playable_clauses(action: str) -> list[str]:
    """Return only actions the video model can visibly perform in-frame."""
    return [part for part in clauses(action) if not POST_PRODUCTION_DIRECTIVE.search(part)]


def monotonic_state_index(index: int, count: int, state_count: int) -> int:
    if state_count <= 1 or count <= 1:
        return 0
    return min(state_count - 1, index * (state_count - 1) // (count - 1))


REQUIRED_MOTION_BEAT_FIELDS = ("subject", "action", "contact_point", "direction", "end_state")


def validated_motion_beats(shot_id: str, shot: dict) -> list[dict]:
    """Require authored physical beats instead of inventing generic motion filler."""
    beats = shot.get("motion_beats")
    if not isinstance(beats, list) or not beats:
        raise RuntimeError(f"{shot_id} missing authored motion_beats")
    minimum = math.ceil(float(shot["duration_seconds"]) / 3.0)
    if len(beats) < minimum:
        raise RuntimeError(f"{shot_id} needs at least {minimum} motion_beats for {shot['duration_seconds']} seconds")
    for index, beat in enumerate(beats, 1):
        missing = [field for field in REQUIRED_MOTION_BEAT_FIELDS if not str(beat.get(field) or "").strip()]
        if missing:
            raise RuntimeError(f"{shot_id} motion beat {index} missing {','.join(missing)}")
    return beats


def native_dialogue_instruction(shot_id: str, shot: dict, audio_by_dia: dict[str, dict]) -> tuple[str, list[dict]]:
    """Render speech instructions from exact per-line audio references."""
    if "dialogue" not in shot:
        raise RuntimeError(f"{shot_id} missing explicit dialogue mapping")
    dialogue = shot["dialogue"]
    if not isinstance(dialogue, list):
        raise RuntimeError(f"{shot_id} dialogue must be a list")
    if not dialogue:
        return "{本镜头无对白；人物闭口，仅保留与动作同步的呼吸、受力声和环境声；画面不生成字幕}", []
    rendered = []
    for index, row in enumerate(dialogue, 1):
        speaker = str(row.get("speaker") or "").strip()
        spoken_text = str(row.get("spoken_text") or "").strip()
        dia_id = str(row.get("dia_id") or "").strip()
        if not speaker or not spoken_text or not dia_id:
            raise RuntimeError(f"{shot_id} dialogue {index} must include dia_id, speaker and spoken_text")
        audio = audio_by_dia.get(dia_id)
        if not audio:
            raise RuntimeError(f"{shot_id} dialogue {dia_id} missing exact target dialogue audio")
        rendered.append(
            f"{speaker}以{audio['audio_slot']}作为本句精确目标对白参考，完整复现\u201c{spoken_text}\u201d的"
            "台词内容、角色音色、语速、节奏、气息和情绪"
        )
    return (
        "{原生同步对白：" + "；".join(rendered)
        + "；视频模型必须以所绑定音频为对白生成参考，只说一次，不改词、不增词、不交换说话人；"
        "说话人口型、气息、表情和起止时间与参考音频同步；非说话角色闭口；画面不生成字幕}",
        dialogue,
    )


def bind_exact_dialogue_audio(unit: dict, shots: dict[str, dict]) -> tuple[list[dict], dict[str, dict]]:
    """Bind every scripted line to a local exact-dialogue audio file and immutable SHA."""
    assets: list[dict] = []
    by_dia: dict[str, dict] = {}
    seen_paths: dict[str, str] = {}
    for shot_id in unit["editorial_shot_ids"]:
        shot = shots[shot_id]
        if "dialogue" not in shot or not isinstance(shot["dialogue"], list):
            raise RuntimeError(f"{shot_id} missing explicit dialogue mapping")
        for row in shot["dialogue"]:
            dia_id = str(row.get("dia_id") or "").strip()
            speaker = str(row.get("speaker") or "").strip()
            spoken_text = str(row.get("spoken_text") or "").strip()
            path_value = str(row.get("reference_audio") or "").strip()
            if not dia_id or not speaker or not spoken_text:
                raise RuntimeError(f"{shot_id} dialogue must include dia_id, speaker and spoken_text")
            if not path_value:
                raise RuntimeError(f"{shot_id} dialogue {dia_id} missing reference_audio")
            path = resolve(path_value)
            if not path.is_file():
                raise RuntimeError(f"{shot_id} dialogue {dia_id} reference_audio not found: {path}")
            actual_sha = sha256(path)
            expected_sha = str(row.get("reference_audio_sha256") or "").strip()
            if expected_sha and expected_sha != actual_sha:
                raise RuntimeError(f"{shot_id} dialogue {dia_id} reference_audio SHA mismatch")
            canonical_path = rel(path)
            prior_text = seen_paths.get(canonical_path)
            if prior_text and prior_text != spoken_text:
                raise RuntimeError(f"{shot_id} dialogue {dia_id} reuses one audio file for different text")
            seen_paths[canonical_path] = spoken_text
            asset = {
                "dia_id": dia_id,
                "speaker": speaker,
                "spoken_text": spoken_text,
                "audio_slot": f"@音频{len(assets) + 1}",
                "path": canonical_path,
                "sha256": actual_sha,
                "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            }
            assets.append(asset)
            by_dia[dia_id] = asset
    if len(by_dia) != len(assets):
        raise RuntimeError(f"{unit['unit_id']} duplicate dialogue IDs in exact audio bindings")
    return assets, by_dia


def validate_compiled_timeline(timeline: list[dict]) -> None:
    by_shot: dict[str, list[dict]] = {}
    for row in timeline:
        by_shot.setdefault(row["source_shot_id"], []).append(row)
        if any(POST_PRODUCTION_DIRECTIVE.search(action) for action in row["actions"]):
            raise RuntimeError(f"post-production directive leaked into action timeline: {row}")
    for shot_id, rows in by_shot.items():
        state_numbers = []
        for row in rows:
            match = re.search(r"-C(\d+)$", row["reference_state_id"])
            if match:
                state_numbers.append(int(match.group(1)))
        if state_numbers != sorted(state_numbers):
            raise RuntimeError(f"{shot_id} reference states regress: {state_numbers}")


def selection_state_id(row: dict) -> str:
    return str(row.get("state_id") or row.get("shot_id") or "")


def cap_reference_states(states_by_shot: dict[str, list[dict]], max_references: int = MAX_OMNI_IMAGE_REFERENCES) -> tuple[dict[str, list[dict]], dict]:
    """Respect the provider's <9 image limit while keeping multiple states per editorial shot."""
    total = sum(len(rows) for rows in states_by_shot.values())
    if total <= max_references:
        return states_by_shot, {"applied": False, "before": total, "after": total, "max": max_references}
    nonempty = [shot_id for shot_id, rows in states_by_shot.items() if rows]
    if len(nonempty) * 2 > max_references:
        raise RuntimeError(
            f"video unit has {len(nonempty)} editorial shots; provider limit {max_references} cannot preserve two states per shot, so regroup the unit"
        )
    selected: dict[str, list[dict]] = {}
    for shot_id, rows in states_by_shot.items():
        selected[shot_id] = [rows[0], rows[-1]] if len(rows) > 1 else list(rows)
    remaining = max_references - sum(len(rows) for rows in selected.values())
    if remaining:
        for shot_id, rows in states_by_shot.items():
            for row in rows[1:-1]:
                if remaining <= 0:
                    break
                selected[shot_id].insert(-1, row)
                remaining -= 1
            if remaining <= 0:
                break
    return selected, {
        "applied": True,
        "before": total,
        "after": sum(len(rows) for rows in selected.values()),
        "max": max_references,
        "policy": "KEEP_AT_LEAST_START_AND_END_STATE_PER_EDITORIAL_SHOT_THEN_FILL_MIDDLE_STATES",
    }


def build_timeline(unit: dict, shots: dict[str, dict], states_by_shot: dict[str, list[dict]]) -> list[dict]:
    timeline: list[dict] = []
    cursor = 0.0
    for shot_id in unit["editorial_shot_ids"]:
        shot = shots[shot_id]
        duration = float(shot["duration_seconds"])
        states = states_by_shot[shot_id]
        beats = validated_motion_beats(shot_id, shot)
        count = len(beats)
        for index, (start, end) in enumerate(split_even(cursor, duration, count)):
            state = states[monotonic_state_index(index, count, len(states))]
            beat = beats[index]
            timeline.append({
                "start_seconds": start,
                "end_seconds": end,
                "source_shot_id": shot_id,
                "reference_state_id": selection_state_id(state),
                "actions": [
                    f"主体={beat['subject']}；动作={beat['action']}",
                    f"接触点={beat['contact_point']}；方向={beat['direction']}",
                    f"终态={beat['end_state']}",
                ],
                "state_change": str(beat["end_state"]),
                "action_budget_seconds": round(end - start, 3),
            })
        cursor += duration
    validate_compiled_timeline(timeline)
    return timeline


def build_sequence(unit: dict, shots: dict[str, dict], states_by_shot: dict[str, list[dict]]) -> list[dict]:
    sequence: list[dict] = []
    cursor = 0.0
    label = 1
    for shot_id in unit["editorial_shot_ids"]:
        states = states_by_shot[shot_id]
        duration = float(shots[shot_id]["duration_seconds"])
        for state, (start, end) in zip(states, split_even(cursor, duration, len(states))):
            sequence.append({
                "asset_label": f"@图片{label}",
                "state_id": selection_state_id(state),
                "source_shot_id": shot_id,
                "path": state["path"],
                "sha256": state["sha256"],
                "start_seconds": start,
                "end_seconds": end,
                "qa_decision": state.get("admission") or state.get("raw_status"),
                "raw_failure_checks": state.get("blocking_checks") or state.get("raw_failure_checks") or [],
            })
            label += 1
        cursor += duration
    return sequence


def render_prompt(episode: str, title: str, unit: dict, scene: dict, shots: dict[str, dict], sequence: list[dict], timeline: list[dict], audio_by_dia: dict[str, dict]) -> str:
    visible: list[str] = []
    for shot_id in unit["editorial_shot_ids"]:
        for character in shots[shot_id].get("visible_characters") or []:
            if character not in visible:
                visible.append(character)
    entity_text = "、".join(f"{item}[[char_{item}]]" for item in visible) or "本单元无人脸主体，以场景、道具和动作结果为连续性主体"
    lines = [
        "【设计动作镜前置系统指令｜CL2X-605｜必须先执行，禁止套通用特效】",
        action_visualization_system_prompt(),
        "【本视频单元编译结果】",
        f"《青山》{episode}《{title}》{unit['unit_id']}，Seedance 2.0 Pro 多状态连续视频，{unit['duration_seconds']}秒，9:16，720p，原速动作。",
        f"【剧本硬锁】地点={scene['location']}；时间={scene.get('time_of_day', 'night')}；天气={scene.get('weather', 'interior_clear')}；事件={unit.get('narrative_beat') or scene.get('event_summary')}。不得跨场、改时段或改剧情结果。",
        f"【实体绑定】{entity_text}。每个角色只允许一个身体，脸、年龄、发型、服装和身份在全部状态间连续。",
        f"【色彩与动机光】{scene.get('palette', '场景既有动机光')}；黑位保留衣褶、环境材质与面部层次。",
        "【场景远景定场坐标】先以大远景/远景定场锁定建筑、门窗、案头、街道和人物相对方位；随后每个编辑镜头仍严格执行自己的景别，不把远景构图套到近景或特写。",
        "【参考状态序列】下列图片是同一连续视频的有序状态，必须按时间消费；禁止只动画第一张、拼贴、分屏或故事板网格：",
    ]
    for row in sequence:
        raw = ",".join(row["raw_failure_checks"])
        note = "原始QA通过" if row["qa_decision"] == "PASS" else f"条件机器准入，原始失败保留={raw}"
        lines.append(f"- {row['start_seconds']:.3f}-{row['end_seconds']:.3f}秒：{row['asset_label']}={row['state_id']}；锁定构图、身份、地点、道具和动作阶段；{note}；SHA-256={row['sha256']}。")
    lines.append("【连续分镜】每镜以可见动作结果结束；剧情结果成立即可自然收尾，不补时长、不停帧、不循环、不慢放：")
    by_shot: dict[str, list[dict]] = {}
    for row in sequence:
        by_shot.setdefault(row["source_shot_id"], []).append(row)
    cursor = 0.0
    for index, shot_id in enumerate(unit["editorial_shot_ids"], 1):
        shot = shots[shot_id]
        end = cursor + float(shot["duration_seconds"])
        labels = "→".join(row["asset_label"] for row in by_shot[shot_id])
        dialogue_instruction, _ = native_dialogue_instruction(shot_id, shot, audio_by_dia)
        lines.append(
            f"镜头{index}【{cursor:.3f}-{end:.3f}秒；景别={shot['scale']}；机位与运动={shot['camera']}】：参考{labels}按序变化。"
            f"严格完成：{shot['action']}；受力、视线或位置结果必须清晰落定。"
            f"{dialogue_instruction}<现场声：{shot['sound']}；接触声与画面同帧>"
        )
        cursor = end
    lines.append("【逐段动作时间轴】")
    for row in timeline:
        lines.append(f"- {row['start_seconds']:.3f}-{row['end_seconds']:.3f}秒 [{row['reference_state_id']}]：{'；'.join(row['actions'])}；状态变化={row['state_change']}。")
    lines.extend([
        "【动作物理】只执行逐段时间轴中明确写出的主体、接触点、方向和终态；不补写未声明的抓取、转身、腾空、碰撞或人物位移。动作按起势、接触、传力、结果连续发生，刀具与人体保持剧本规定的接触关系。",
        "【现场声】对白、呼吸、接触声、拟音和环境声随景别变化并与画面同帧；对白优先且清晰，禁止无动机背景音乐。",
        "【负面约束】禁止字幕、水印、Logo、可读或伪可读文字；禁止换脸、额外人物、同款分身、融合肢体、穿模、瞬移、悬空停顿、静图微动、重复首帧、慢动作和统一缓慢推镜。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--unit-plan", required=True)
    parser.add_argument("--full-state-plan", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--scene-state", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--exclude-source-id", action="append", default=[])
    args = parser.parse_args()

    manifest_path = resolve(args.manifest)
    plan_path = resolve(args.unit_plan)
    full_state_path = resolve(args.full_state_plan)
    admission_path = resolve(args.admission)
    scene_path = resolve(args.scene_state)
    output_dir = resolve(args.output_dir)
    out_path = resolve(args.out)
    manifest = load(manifest_path)
    plan = load(plan_path)
    full_state = load(full_state_path)
    admission = load(admission_path)
    scenes = {row["scene_id"]: row for row in load(scene_path)["scene_state"]}
    shots = {row["shot_id"]: row for row in manifest["shots"]}
    admitted = {selection_state_id(row): row for row in admission.get("selections", [])}
    required_by_unit: dict[str, list[dict]] = {}
    for task in full_state["tasks"]:
        required_by_unit.setdefault(task["video_unit_id"], []).append(task)

    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir = output_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    excluded = set(args.exclude_source_id)
    workflow_scope_id = f"{manifest['episode'].lower()}_claude_writer_v1_20260722"
    credit_scope_path = ROOT / "workflow/credit_scopes" / f"{manifest['episode']}_VIDEO_CREDIT_SCOPE.json"
    credit_scope_path.parent.mkdir(parents=True, exist_ok=True)
    credit_scope_path.write_text(json.dumps({
        "schema": "qingshan.episode_video_credit_scope.v1",
        "episode": manifest["episode"],
        "status": "ACTIVE",
        "workflow_scope_id": workflow_scope_id,
        "production_root": rel(manifest_path.parent),
        "configured_limit_credits": 6000,
        "scope_policy": "CURRENT_WORKFLOW_ROUND_ONLY",
        "historical_rounds": "AUDIT_ONLY_EXCLUDED_FROM_GATE",
        "authorized_by": "Roger",
        "authorization": "6000 credits means this episode's current workflow round, not historical accumulation",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tasks: list[dict] = []
    waiting: list[dict] = []
    for unit in plan["units"]:
        required = required_by_unit.get(unit["unit_id"], [])
        missing = [task["shot_id"] for task in required if task["shot_id"] not in admitted]
        if unit["unit_id"] in excluded:
            waiting.append({"unit_id": unit["unit_id"], "status": "ALREADY_SUBMITTED_EXCLUDED", "missing_state_ids": []})
            continue
        if missing:
            waiting.append({"unit_id": unit["unit_id"], "status": "WAITING_FOR_ADMITTED_STATES", "missing_state_ids": missing})
            continue
        states_by_shot = {shot_id: [] for shot_id in unit["editorial_shot_ids"]}
        for state_task in required:
            state = admitted[state_task["shot_id"]]
            states_by_shot[state_task["editorial_shot_id"]].append(state)
        for rows in states_by_shot.values():
            rows.sort(key=lambda row: int(re.search(r"-C(\d+)$", selection_state_id(row)).group(1)))
        states_by_shot, reference_cap = cap_reference_states(states_by_shot)
        sequence = build_sequence(unit, shots, states_by_shot)
        timeline = build_timeline(unit, shots, states_by_shot)
        dialogue_audio_assets, audio_by_dia = bind_exact_dialogue_audio(unit, shots)
        action_gate = validate_action_timeline(timeline, unit["duration_seconds"], source_id=unit["unit_id"])
        if action_gate["status"] != "PASS":
            raise RuntimeError(f"{unit['unit_id']} action density failed: {action_gate['failures']}")
        prompt = render_prompt(
            manifest["episode"], manifest["title"], unit, scenes[unit["scene_id"]],
            shots, sequence, timeline, audio_by_dia,
        )
        prompt_path = prompt_dir / f"{unit['unit_id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        task = {
            "task_key": f"{unit['unit_id']}-VIDEO-V1",
            "source_id": unit["unit_id"],
            "tool_type": "video_generation",
            "generation_mode": "entity_reference_sequence",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": not bool(dialogue_audio_assets),
            "native_dialogue_required": bool(dialogue_audio_assets),
            "episode": manifest["episode"],
            "batch_id": f"{manifest['episode']}-CW-VIDEO-INCREMENTAL-V1",
            "unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "visual_zone": unit["unit_id"],
            "duration": unit["duration_seconds"],
            "duration_seconds": unit["duration_seconds"],
            "duration_plan": {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": unit["duration_seconds"],
                "rationale": "Exact sum of contiguous Claude-script editorial shots; unit count and duration emerged naturally from scene-local grouping.",
                "edit_policy": "End when the story/action result lands; trim static tails and never pad, slow or loop.",
            },
            "model": "seedance-2.0-pro",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "prompt_file": rel(prompt_path),
            "prompt_path": rel(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in sequence],
            "reference_image_sequence": sequence,
            "reference_image_limit_gate": reference_cap,
            "state_reference_minimum": int(unit.get("planned_reference_image_count") or len(sequence)),
            "planned_reference_image_count": int(unit.get("planned_reference_image_count") or len(sequence)),
            "anchor_count_decision": unit.get("anchor_count_decision") or {
                "decision": "LEGACY_ADMITTED_STATE_POOL",
                "reason": "Reference count is inherited from the explicitly admitted unit state pool, not from an action/non-action fixed minimum.",
            },
            "action_unit": bool(unit["action_unit"]),
            "action_timeline": timeline,
            "action_density_gate": action_gate,
            "dialogue": [
                row
                for shot_id in unit["editorial_shot_ids"]
                for row in native_dialogue_instruction(shot_id, shots[shot_id], audio_by_dia)[1]
            ],
            "reference_audios": [row["path"] for row in dialogue_audio_assets],
            "dialogue_audio_assets": dialogue_audio_assets,
            "dialogue_audio_coverage": {
                "required": len(dialogue_audio_assets),
                "bound": len(dialogue_audio_assets),
                "status": "PASS" if dialogue_audio_assets else "NOT_APPLICABLE_NO_DIALOGUE",
                "policy": "ONE_EXACT_TARGET_DIALOGUE_AUDIO_REFERENCE_PER_SCRIPTED_DIALOGUE_ID",
            },
            "source_script_sha256": manifest["source"]["script_sha256"],
            "workflow_credit_scope": workflow_scope_id,
            "status": "READY_TO_SUBMIT",
        }
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)

    config = {
        "schema": "qingshan.episode_incremental_ready_video_batch.v1",
        "episode": manifest["episode"],
        "status": "READY_FOR_INCREMENTAL_SUBMIT" if tasks else "NO_NEW_READY_UNITS",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": len(tasks),
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "workflow_credit_scope": workflow_scope_id,
        "video_credit_limit": 6000,
        "source_script_sha256": manifest["source"]["script_sha256"],
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": manifest["source"]["script"],
            "source_script_sha256": manifest["source"]["script_sha256"],
            "production_manifest": rel(manifest_path),
            "production_manifest_sha256": sha256(manifest_path),
            "action_visualization_system_prompt": rel(ACTION_VISUALIZATION_SYSTEM_PROMPT),
            "action_visualization_system_prompt_sha256": ACTION_VISUALIZATION_SYSTEM_PROMPT_SHA256,
        },
        "state_admission": rel(admission_path),
        "scene_contract_ref": rel(scene_path),
        "supervisor_script_gate_required": False,
        "readiness_policy": "SUBMIT_EACH_VIDEO_UNIT_AS_SOON_AS_ITS_COMPLETE_PLANNED_STATE_POOL_IS_ADMITTED",
        "output_dir": rel(output_dir / "outputs"),
        "qa_dir": rel(output_dir / "qa"),
        "ready_unit_count": len(tasks),
        "waiting_unit_count": sum(1 for row in waiting if row["status"] == "WAITING_FOR_ADMITTED_STATES"),
        "waiting_units": waiting,
        "tasks": tasks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": config["status"],
        "ready_units": [task["unit_id"] for task in tasks],
        "waiting_units": waiting,
        "out": rel(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
