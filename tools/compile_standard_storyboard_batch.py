#!/usr/bin/env python3
"""Compile one approved beat sheet into a concurrent Seedance storyboard batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

try:
    from action_xuanhuan_script_gate import validate as validate_action_xuanhuan
    from storyboard_sheet_gate import requires_storyboard_sheet_gate, validate_gate_report, validate_plan
except ModuleNotFoundError:
    from tools.action_xuanhuan_script_gate import validate as validate_action_xuanhuan
    from tools.storyboard_sheet_gate import requires_storyboard_sheet_gate, validate_gate_report, validate_plan


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_references(payload: dict) -> dict[str, list[str]]:
    if isinstance(payload.get("beats"), dict):
        result = {}
        for key, value in payload["beats"].items():
            if isinstance(value, str):
                result[str(key)] = [value]
            elif isinstance(value, list):
                result[str(key)] = [str(item) for item in value]
            else:
                raise ValueError(f"Unsupported reference value for {key}: {type(value).__name__}")
        return result
    rows = payload.get("video_tasks") or payload.get("tasks") or []
    result: dict[str, list[str]] = {}
    for row in rows:
        beat_id = row.get("beat_id") or (row.get("metadata") or {}).get("beat_id")
        if not beat_id:
            continue
        bucket = result.setdefault(str(beat_id), [])
        for reference in row.get("reference_images") or []:
            value = str(reference)
            if value not in bucket:
                bucket.append(value)
    return result


def map_scenes(scene_contract: dict) -> dict[str, dict]:
    result = {}
    for scene in scene_contract.get("scene_state") or []:
        for beat_id in scene.get("beats") or []:
            result[str(beat_id)] = scene
    return result


def choose_duration(beat: dict) -> int:
    must_show_count = len(beat.get("must_show") or [])
    segment_type = str(beat.get("segment_type") or "").lower()
    if any(token in segment_type for token in ("burst", "action", "fight")) or must_show_count >= 5:
        return 15
    if must_show_count == 4:
        return 12
    return 10


def dialogue_chunks_for_beat(beat_id: str, draft: list[dict]) -> list[list[dict]]:
    rows = [row for row in draft if str(row.get("beat_id")) == beat_id]
    selected: list[dict] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        selected.append({"speaker": str(row.get("speaker") or "角色"), "text": text})
    return [selected[index:index + 3] for index in range(0, len(selected), 3)] or [[]]


def prompt_for(
    episode: str,
    title: str,
    beat: dict,
    scene: dict,
    dialogue: list[dict],
    duration: int,
    part_index: int = 1,
    part_count: int = 1,
    storyboard_row: Optional[dict] = None,
    fight_sequence: Optional[dict] = None,
) -> str:
    beat_id = str(beat["beat_id"])
    must_show = [str(item) for item in beat.get("must_show") or []]
    while len(must_show) < 5:
        must_show.append(str(beat.get("new_information") or beat.get("name") or beat_id))
    location = scene.get("location") or "剧本锁定场景"
    time_of_day = scene.get("time_of_day") or "剧本锁定时间"
    weather = scene.get("weather") or "剧本锁定天气"
    location_token = (scene.get("location_prompt_tokens") or [location])[0]
    lines = [
        f"这是《青山》{episode}《{title}》{beat_id} 第{part_index}/{part_count}段的标准 Seedance 2.0 分镜生成。以场景参考[[scene_1]]中的人物身份、脸、发型、服装、左右轴线和陈设为唯一视觉锚点。",
        f"场景 authority：{location}（{location_token}）；时间严格为 {time_of_day}；天气严格为 {weather}。以上条件逐字执行；除明确写出的环境外，禁止新增月亮、月光、雨雪、雾、雷电、日照或改换地点。",
        f"本段唯一剧情信息：{beat.get('new_information') or beat.get('name')}。整体为同一时空内一次 {duration} 秒多分镜表演，所有动作使用写实原生速度。",
        f"动作骨架：{beat.get('action_spine')}。玄幻揭示：{beat.get('xuanhuan_element')}。力量可视化：{beat.get('power_visualization')}。信息必须由动作与奇观交付。",
        "构图必须避开牌匾、门楣、招幌、书页正面和其他文字载体；官文、账册、腰牌只允许背面朝镜头、封闭或景深虚化，画面中所有平面保持素面。",
        "对白只作为同步语音与口型指令：画面上方、中部、下方均不得把对白显示成字幕、标题、气泡或任何字形。",
        "",
        f"镜头1：【远景定场，稳定缓慢推近】{must_show[0]}。建立清楚空间关系和人物站位，不停顿、不空镜补时。",
        f"镜头2：【中景侧移】{must_show[1]}。动作连续并产生新的信息变化。",
    ]
    if storyboard_row:
        lines.insert(4, (
            "分镜表硬绑定："
            f"画面={storyboard_row.get('visual')}；机位与运动={storyboard_row.get('camera')}；"
            f"拍法={storyboard_row.get('technique')}；构图签名={storyboard_row.get('composition_signature')}。"
            "不得退化为通用正面中景或复制其他 beat 构图。"
        ))
    if fight_sequence and str(fight_sequence.get("beat_id")) == beat_id:
        fight_lines = [
            f"打斗模式：{fight_sequence.get('mode')}；六镜必须按以下顺序完整执行，不得合并成同款挥舞："
        ]
        for shot in fight_sequence.get("shots") or []:
            fight_lines.append(
                f"镜{shot.get('shot_no')} [{shot.get('phase')}] {shot.get('shot_size')}；"
                f"{shot.get('camera')}；{shot.get('action')}；音效{shot.get('sfx')}；"
                f"力量介质{shot.get('power_visualization')}。"
            )
        lines[5:5] = fight_lines
    if dialogue:
        lines.append(f"角色{dialogue[0]['speaker']}清楚说：{{{dialogue[0]['text']}}}。只有该角色口型运动。")
    lines.extend([
        f"镜头3：【近景反打，固定机位】{must_show[2]}。表情随剧情因果改变，不循环同一表情。",
    ])
    if len(dialogue) > 1:
        lines.append(f"角色{dialogue[1]['speaker']}清楚说：{{{dialogue[1]['text']}}}。只有该角色口型运动。")
    lines.extend([
        f"镜头4：【道具或动作特写，快速稳定转场】{must_show[3]}。特写不超过2秒，画面无任何可读文字或伪文字。",
        f"镜头5：【双人或群像中景，小幅环绕】{must_show[4]}。人物发生不可逆动作或权力变化，禁止近静止长停。",
        f"镜头6：【收束近景，动作或视线匹配切换】{beat.get('button') or must_show[-1]}。以明确反应按钮结束，不重复前镜动作。",
    ])
    if len(dialogue) > 2:
        lines.append(f"角色{dialogue[2]['speaker']}清楚说：{{{dialogue[2]['text']}}}。只有该角色口型运动。")
    lines.extend([
        "",
        "写实美剧式古装玄幻/武打短剧，悬疑只服务于行动与奇观；高清细节、稳定构图、自然色彩。六个镜头的机位、景别和运动必须明确不同，切换必须由动作、视线或新信息驱动。",
        "人物面部稳定，普通话口型清晰，动作连贯、写实速度、重心和碰撞真实；禁止慢动作、近静止长停、循环动作、重复表情、梦幻漂浮、橡皮物理、穿模、身份漂移。",
        "禁止新人物、分身、双胞胎、额外肢体；禁止字幕、可读文字、伪文字、数字、字母、书法、水印、Logo和背景音乐。禁止出现建筑正立面牌匾或带字招牌。文字类证物只可表现为不可读材质、颜色、印痕或封闭素面容器，绝不生成字形。",
    ])
    return "\n".join(lines) + "\n"


def compile_batch(
    episode: str,
    beat_sheet: dict,
    scene_contract: dict,
    references: dict[str, list[str]],
    prompt_dir: Path,
    output_dir: str,
    qa_dir: str,
    scene_contract_ref: str,
    script_readiness_report: Optional[str] = None,
    storyboard_plan: Optional[dict] = None,
    storyboard_gate_report: Optional[dict] = None,
    storyboard_plan_ref: Optional[str] = None,
    storyboard_gate_report_ref: Optional[str] = None,
) -> dict:
    action_xuanhuan_gate = validate_action_xuanhuan(beat_sheet)
    if action_xuanhuan_gate["status"] != "PASS":
        failed = ",".join(row["check"] for row in action_xuanhuan_gate["failures"])
        raise ValueError(f"action-xuanhuan script gate failed: {failed}")
    if requires_storyboard_sheet_gate(episode):
        if not storyboard_plan or not storyboard_gate_report:
            raise ValueError("storyboard-sheet plan and final gate report are required for E26+")
        plan_gate = validate_plan(storyboard_plan)
        report_gate = validate_gate_report(storyboard_gate_report, episode)
        failures = plan_gate["failures"] + report_gate["failures"]
        if failures:
            failed = ",".join(str(row.get("check")) for row in failures)
            raise ValueError(f"storyboard-sheet gate failed: {failed}")
    storyboard_by_beat = {
        str(row.get("beat_id")): row for row in (storyboard_plan or {}).get("episode_rows") or []
    }
    fight_sequence = (storyboard_plan or {}).get("fight_sequence") or None
    prompt_dir.mkdir(parents=True, exist_ok=True)
    scenes = map_scenes(scene_contract)
    tasks = []
    for beat in beat_sheet.get("structure") or []:
        beat_id = str(beat["beat_id"])
        scene = scenes.get(beat_id)
        if not scene:
            raise ValueError(f"No scene authority mapping for {episode} {beat_id}")
        refs = references.get(beat_id) or []
        if not refs:
            raise ValueError(f"No reference image for {episode} {beat_id}")
        duration = choose_duration(beat)
        dialogue_chunks = dialogue_chunks_for_beat(beat_id, beat_sheet.get("dialogue_draft") or [])
        for part_index, dialogue in enumerate(dialogue_chunks, start=1):
            suffix = f"-P{part_index}" if len(dialogue_chunks) > 1 else ""
            prompt_path = prompt_dir / f"{episode}-{beat_id}{suffix}-STANDARD-STORYBOARD-V1.txt"
            prompt_path.write_text(
                prompt_for(
                    episode,
                    str(beat_sheet.get("title") or episode),
                    beat,
                    scene,
                    dialogue,
                    duration,
                    part_index,
                    len(dialogue_chunks),
                    storyboard_by_beat.get(beat_id),
                    fight_sequence,
                ),
                encoding="utf-8",
            )
            try:
                prompt_file = str(prompt_path.relative_to(ROOT))
            except ValueError:
                prompt_file = str(prompt_path)

            tasks.append({
                "task_key": f"{episode}-{beat_id}{suffix}-STANDARD-STORYBOARD-V1",
                "tool_type": "video_generation",
                "source_id": f"{beat_id}{suffix}",
                "dialogue_id": f"{beat_id}{suffix}",
                "scene_id": scene["scene_id"],
                "visual_zone": f"{beat_id}{suffix}_STANDARD_STORYBOARD_REWORK",
                "prompt_mode": "seedance2_standard_storyboard_v1",
                "prompt_file": prompt_file,
                "reference_images": refs,
                "model": "seedance-2.0-pro",
                "duration": duration,
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "duration_plan": {
                    "policy": "qingshan.shot_generation_duration.v2",
                    "duration_seconds": duration,
                    "speech_seconds_estimate": round(sum(len(row["text"]) for row in dialogue) / 3.6, 3),
                    "action_seconds": 4.0 if duration >= 12 else 3.0,
                    "reaction_or_button_seconds": 1.0,
                    "raw_seconds": float(duration),
                    "tool_minimum_floor_applied": False,
                    "edit_policy": "Use the full story-driven beat segment; preserve passes and retry only this failed part.",
                    "rationale": f"Story-driven {duration}s standard storyboard for {beat_id} part {part_index}/{len(dialogue_chunks)}; duration follows action and dialogue payload, not a fixed per-line default.",
                },
                "metadata": {
                    "beat_id": beat_id,
                    "part_index": part_index,
                    "part_count": len(dialogue_chunks),
                    "name": beat.get("name"),
                    "new_information": beat.get("new_information"),
                    "payload_delivery": beat.get("payload_delivery"),
                    "action_spine": beat.get("action_spine"),
                    "xuanhuan_element": beat.get("xuanhuan_element"),
                    "power_visualization": beat.get("power_visualization"),
                    "selected_dialogue": dialogue,
                },
            })
    payload = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "directive_refs": ["CL2X-349", "CL2X-356", "CL2X-363", "CL2X-364"],
        "scene_contract_ref": scene_contract_ref,
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": len(tasks),
        "max_retries": 0,
        "output_dir": output_dir,
        "qa_dir": qa_dir,
        "base_batch_note": "Standard-storyboard rework after Roger audience hold. Preserve passed sources; submit all six beat masters concurrently and isolate failures.",
        "action_xuanhuan_gate": action_xuanhuan_gate,
        "storyboard_sheet_plan": storyboard_plan_ref,
        "storyboard_sheet_gate_report": storyboard_gate_report_ref,
        "tasks": tasks,
    }
    if script_readiness_report:
        payload["script_readiness_report"] = script_readiness_report
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--scene-contract", required=True)
    parser.add_argument("--reference-source", required=True)
    parser.add_argument("--prompt-dir", required=True)
    parser.add_argument("--output-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--qa-dir", required=True)
    parser.add_argument("--script-readiness-report")
    parser.add_argument("--storyboard-plan")
    parser.add_argument("--storyboard-sheet-gate-report")
    args = parser.parse_args()

    beat_sheet_path = Path(args.beat_sheet).expanduser().resolve()
    scene_path = Path(args.scene_contract).expanduser().resolve()
    reference_path = Path(args.reference_source).expanduser().resolve()
    prompt_dir = Path(args.prompt_dir).expanduser().resolve()
    output_config = Path(args.output_config).expanduser().resolve()
    storyboard_plan_path = Path(args.storyboard_plan).expanduser().resolve() if args.storyboard_plan else None
    storyboard_gate_path = Path(args.storyboard_sheet_gate_report).expanduser().resolve() if args.storyboard_sheet_gate_report else None
    batch = compile_batch(
        args.episode.upper(),
        read_json(beat_sheet_path),
        read_json(scene_path),
        collect_references(read_json(reference_path)),
        prompt_dir,
        args.output_dir,
        args.qa_dir,
        str(scene_path.relative_to(ROOT)),
        args.script_readiness_report,
        read_json(storyboard_plan_path) if storyboard_plan_path else None,
        read_json(storyboard_gate_path) if storyboard_gate_path else None,
        str(storyboard_plan_path.relative_to(ROOT)) if storyboard_plan_path else None,
        str(storyboard_gate_path.relative_to(ROOT)) if storyboard_gate_path else None,
    )
    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "episode": batch["episode"], "task_count": len(batch["tasks"]), "output_config": str(output_config)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
