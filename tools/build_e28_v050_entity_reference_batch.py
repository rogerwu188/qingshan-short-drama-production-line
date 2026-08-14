#!/usr/bin/env python3
"""Build E28 Writer Agent v0.5 entity-reference video units.

The new Writer Agent timeline is authoritative. Previously generated E28 clips are
used only as temporal motion and voice-timbre evidence; selected Writer Agent
stills lock scene, identity, props, and composition.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflow/writer_agent/e28_agent_native_v050_20260721"
COMPILED = WORKFLOW / "E28_WRITER_AGENT_V050_COMPILED.json"
GENERATED = WORKFLOW / "E28_WRITER_AGENT_V050_GENERATED.json"
ADMISSION = WORKFLOW / "production/E28_IMAGE_CANDIDATE_ADMISSION.json"
SOURCE_PROJECT = ROOT / "configs/e28_agentcut_project_v2_cadence_tail_repair_20260721.json"
SCENE_STATE = WORKFLOW / "production/scene_state.json"
CONFIG_OUT = ROOT / "configs/E28_writer_agent_v050_entity_reference_sequence_20260721.json"
RECEIPT_OUT = ROOT / "workflow/tasks/E28_WRITER_AGENT_V050_ENTITY_REFERENCE_ASSET_BUILD_RECEIPT_20260721.json"
PROMPT_DIR = ROOT / "workflow/prompts/e28_writer_agent_v050_entity_reference_20260721"
ASSET_ROOT = ROOT / "working_assets/e28_writer_agent_v050_entity_reference_20260721"

# Old E28 clips retain useful motion, spatial blocking, and the established voices.
# They are not script authority. Each list is ordered as temporal evidence for the
# matching new Writer Agent unit.
REFERENCE_DIALOGUES = {
    "E28-S01::U01": ["DIA-003", "DIA-001", "DIA-002"],
    "E28-S01::U02": ["DIA-004", "DIA-006", "DIA-007", "DIA-009"],
    "E28-S01::U03": ["DIA-008", "DIA-009", "DIA-012"],
    "E28-S01::U04": ["DIA-007", "DIA-008", "DIA-009"],
    "E28-S02::U01": ["DIA-012", "DIA-010", "DIA-011"],
    "E28-S02::U02": ["DIA-013", "DIA-014", "DIA-015", "DIA-018"],
    "E28-S02::U03": ["DIA-019", "DIA-020", "DIA-021", "DIA-024"],
    "E28-S02::U04": ["DIA-025", "DIA-026", "DIA-027", "DIA-029"],
    "E28-S03::U01": ["DIA-025", "DIA-026", "DIA-029", "DIA-030"],
    "E28-S03::U02": ["DIA-028", "DIA-029", "DIA-030"],
    "E28-S03::U03": ["DIA-029", "DIA-031", "DIA-032", "DIA-034"],
    "E28-S03::U04": ["DIA-031", "DIA-032", "DIA-033", "DIA-034", "DIA-035", "DIA-036"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def old_clip_map(project: dict) -> dict[str, dict]:
    result = {}
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        dialogue_id = clip["id"].removeprefix("E28-").removesuffix("-VIDEO")
        path = Path(clip["source"])
        if not path.is_file():
            raise FileNotFoundError(path)
        result[dialogue_id] = {"path": path, "duration": float(clip["duration"]), "sha256": sha256(path)}
    return result


def selected_stills(admission: dict) -> dict[str, dict]:
    result = {}
    for row in admission["selections"]:
        path = Path(row["path"])
        if not path.is_file() or sha256(path) != row["sha256"]:
            raise RuntimeError(f"selected still mismatch: {row['shot_id']}")
        result[row["shot_id"]] = row
    return result


def allocate_segments(dialogue_ids: list[str], clips: dict[str, dict], target: float) -> list[dict]:
    available = [clips[item]["duration"] for item in dialogue_ids]
    total = sum(available)
    allocations = [target * value / total for value in available]
    allocations[-1] += target - sum(allocations)
    return [
        {
            "dialogue_id": dialogue_id,
            "path": clips[dialogue_id]["path"],
            "source_sha256": clips[dialogue_id]["sha256"],
            "source_start_seconds": 0.0,
            "source_end_seconds": round(min(clips[dialogue_id]["duration"], duration), 6),
            "duration_seconds": round(duration, 6),
        }
        for dialogue_id, duration in zip(dialogue_ids, allocations)
    ]


def build_temporal_assets(segments: list[dict], duration: int, video_out: Path, audio_out: Path) -> None:
    video_out.parent.mkdir(parents=True, exist_ok=True)
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for segment in segments:
        command.extend(["-i", str(segment["path"])])
    filters = []
    video_labels = []
    audio_labels = []
    for index, segment in enumerate(segments):
        end = segment["source_end_seconds"]
        filters.append(
            f"[{index}:v]trim=0:{end},setpts=PTS-STARTPTS,fps=24,"
            "scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black[v{index}]"
        )
        filters.append(
            f"[{index}:a]atrim=0:{end},asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=channel_layouts=stereo[a{index}]"
        )
        video_labels.append(f"[v{index}]")
        audio_labels.append(f"[a{index}]")
    filters.append("".join(video_labels) + f"concat=n={len(segments)}:v=1:a=0[vout]")
    filters.append("".join(audio_labels) + f"concat=n={len(segments)}:v=0:a=1[aout]")
    command.extend(
        [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", "[aout]",
            "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-b:a", "160k", str(video_out),
        ]
    )
    run(command)
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_out),
            "-vn", "-t", str(duration), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(audio_out),
        ]
    )


def render_prompt(contract: dict, shots: dict[str, dict], dialogues: dict[str, dict]) -> str:
    requirements = contract.get("asset_requirements", [])
    scene_slots = [item["slot_id"] for item in requirements if item["asset_type"] == "scene"]
    char_slots = [item["slot_id"] for item in requirements if item["asset_type"] == "character"]
    prop_slots = [item["slot_id"] for item in requirements if item["asset_type"] == "prop"]
    palette = "；".join(dict.fromkeys(shots[item["shot_id"]].get("palette", "") for item in contract["shot_plan"] if shots[item["shot_id"]].get("palette")))
    key_light = "；".join(dict.fromkeys(shots[item["shot_id"]].get("key_light", "") for item in contract["shot_plan"] if shots[item["shot_id"]].get("key_light")))
    lines = [
        f"这是《青山》E28 {contract['batch_id']} {contract['unit_id']} 的连续实体参考动作单元，时长{contract['duration_seconds']}秒。",
        f"实体绑定：[[scene_1]]={','.join(scene_slots)}；[[char_1]]={','.join(char_slots)}；[[prop_1]]={','.join(prop_slots)}。",
        "@图片按顺序锁定本单元各源镜头的场景、人物身份、服装、道具与构图；@视频1仅提供同剧集的动作节奏、空间阻挡与物理时序；@音频1仅提供既有角色声线与表演节奏参考。",
        "旧参考音频中的文字不是目标台词，严禁照抄；只保留对应角色的音色、年龄感、语气和口音，必须逐字说出下列新台词。",
        "必须重演新版 Writer Agent 锁定事件，不得退回逐对白镜头，不得退化为单张静图动画，不得重置跨镜动作轨迹。",
        "场景时段、天气、人物、道具和事件以本提示及@图片为唯一事实权威；旧@视频若有冲突，只借动作物理，不继承旧构图或旧文字。",
        f"时间与场景锁：{contract.get('time_of_day', '以Writer Agent场景合同为准')}，地点={contract.get('location_id')}。",
        f"palette与色彩：{palette or '沿用入选参考图的冷暖关系'}；动机光与光影：{key_light or '沿用入选参考图的真实方向性照明'}；黑位保留层次，高光受控。",
        "每个单元都继承本场大远景/远景定场建立的空间轴线和纵深；即使当前切入中近景，也不得改造地点或压扁前中后景。",
        "力量必须驱动环境介质产生对应反应：纸尘、衣摆、木屑、霜粒、雪粉或瓦片只在明确接触与受力时运动，方向、延迟和落点服从动作物理。",
        "",
    ]
    sound_by_shot: dict[str, list[str]] = {}
    for sound in contract.get("onsite_sound_plan", []):
        sound_by_shot.setdefault(sound["source_shot_id"], []).append(sound["cue"])
    for index, segment in enumerate(contract["shot_plan"], 1):
        shot = shots[segment["shot_id"]]
        dialogue_rows = [dialogues[item] for item in shot.get("dialogue_ids", [])]
        dialogue = " / ".join(f"{row['speaker_id']}：‘{row['text']}’" for row in dialogue_rows) or "无对白"
        sound = "；".join(sound_by_shot.get(segment["shot_id"], ["服装、地面与道具接触声随动作同步"]))
        lines.append(
            f"镜头{index}【{segment['unit_offset_start_seconds']}-{segment['unit_offset_end_seconds']}秒；"
            f"景别={segment['shot_scale']}；机位={segment['camera_height']}；运动={segment['camera_motion']}】："
            f"{shot['action']} {{对白：{dialogue}}} <现场声：{sound}>"
        )
    lines.extend(["", "动作物理必须按顺序成立："])
    for phase in contract["action_physics"]["phases"]:
        lines.append(f"- {phase['phase']}：{phase['description']}")
    lines.extend(
        [
            "",
            "人物轨迹、道具轨迹与剪辑边界必须连续；每次接触都要显示起势、接触、力量传导与结果，不用慢动作填充。",
            "写实国漫古装武侠质感，电影级景深与材质，构图稳定，人物脸部稳定，前中后景清楚。",
            "禁止：" + "；".join(contract["negative_constraints"]),
            "禁止字幕、水印、Logo、背景音乐、循环动作、可读生成文字、同款分身、双胞胎效果、月夜替代锁定白昼或黄昏。",
        ]
    )
    return "\n".join(lines) + "\n"


def evidence_segments(segments: list[dict], duration: int) -> list[dict]:
    cursor = 0.0
    result = []
    for index, row in enumerate(segments):
        end = duration if index == len(segments) - 1 else min(duration, cursor + row["duration_seconds"])
        result.append(
            {
                "segment_id": f"TEMPORAL::{row['dialogue_id']}::{index + 1}",
                "source_dialogue_id": row["dialogue_id"],
                "unit_offset_start_seconds": round(cursor, 6),
                "unit_offset_end_seconds": round(end, 6),
                "evidence_role": "motion_blocking_and_voice_timbre_only",
            }
        )
        cursor = end
    return result


def build_task(contract: dict, clips: dict[str, dict], stills: dict[str, dict], shots: dict, dialogues: dict) -> dict:
    unit_suffix = contract["unit_id"].split("::")[-1]
    task_key = f"{contract['batch_id']}-{unit_suffix}-ENTITY-REFERENCE-V050"
    duration = int(contract["duration_seconds"])
    dialogue_refs = REFERENCE_DIALOGUES[contract["unit_id"]]
    segments = allocate_segments(dialogue_refs, clips, duration)
    video_path = ASSET_ROOT / "video/unit_sequences" / f"{task_key}-motion-voice-sequence.mp4"
    audio_path = ASSET_ROOT / "audio/unit_voice_timbre" / f"{task_key}-voice-timbre-sequence.wav"
    build_temporal_assets(segments, duration, video_path, audio_path)
    prompt_path = PROMPT_DIR / f"{contract['batch_id']}-{unit_suffix}.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(render_prompt(contract, shots, dialogues), encoding="utf-8")
    video_sha = sha256(video_path)
    audio_sha = sha256(audio_path)
    image_rows = [stills[segment["shot_id"]] for segment in contract["shot_plan"]]
    image_paths = list(dict.fromkeys(str(Path(row["path"]).relative_to(ROOT)) for row in image_rows))
    image_by_slot = {row["shot_id"]: row for row in image_rows}
    reference_assets = []
    fallback_image = image_rows[0]
    for requirement in contract["asset_requirements"]:
        if requirement["asset_type"] in {"scene", "character", "prop"}:
            asset = fallback_image
        elif requirement["asset_type"] == "audio":
            asset = {"path": str(audio_path), "sha256": audio_sha}
        else:
            asset = {"path": str(video_path), "sha256": video_sha}
        reference_assets.append(
            {
                "slot_id": requirement["slot_id"],
                "path": str(Path(asset["path"]).relative_to(ROOT)),
                "sha256": asset["sha256"],
                "binding_note": "selected Writer still" if requirement["asset_type"] in {"scene", "character", "prop"} else "voice/performance reference",
            }
        )
    for row in image_rows:
        reference_assets.append(
            {
                "slot_id": f"COMPOSITION::{row['shot_id']}",
                "path": str(Path(row["path"]).relative_to(ROOT)),
                "sha256": row["sha256"],
                "admission": row["admission"],
            }
        )
    reference_assets.extend(
        [
            {"slot_id": f"VIDEO_SEQUENCE::{task_key}", "path": str(video_path.relative_to(ROOT)), "sha256": video_sha},
            {"slot_id": f"AUDIO_TIMBRE::{task_key}", "path": str(audio_path.relative_to(ROOT)), "sha256": audio_sha},
        ]
    )
    temporal = evidence_segments(segments, duration)
    return {
        "task_key": task_key,
        "tool_type": "video_generation",
        "generation_mode": "entity_reference_sequence",
        "batch_id": contract["batch_id"],
        "unit_id": contract["unit_id"],
        "source_id": task_key,
        "scene_id": contract["scene_id"],
        "visual_zone": contract["unit_id"],
        "variant_group": f"{contract['batch_id']}-CONTINUOUS-UNITS",
        "variant_label": unit_suffix,
        "duration": duration,
        "duration_seconds": duration,
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v4",
            "duration_seconds": duration,
            "rationale": "Writer Agent v0.5 continuous entity-reference unit duration; no fixed-duration normalization.",
            "edit_policy": "Generate the entire unit and preserve wind-up, contact, force transfer, result, and declared edit boundaries.",
        },
        "model": "seedance-2.0-pro",
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256(prompt_path),
        "action_reference_minimum": 1,
        "reference_images": image_paths,
        "reference_audios": [str(audio_path.relative_to(ROOT))],
        "reference_videos": [str(video_path.relative_to(ROOT))],
        "reference_audio_sequence": {"duration_seconds": duration, "sha256": audio_sha, "segments": temporal},
        "reference_video_sequence": {"duration_seconds": duration, "sha256": video_sha, "segments": temporal, "single_still_only": False},
        "required_slot_ids": [item["slot_id"] for item in contract["asset_requirements"]],
        "reference_assets": reference_assets,
        "source_shot_admissions": {shot_id: image_by_slot[shot_id]["admission"] for shot_id in image_by_slot},
        "status": "READY_FOR_NO_NETWORK_PREFLIGHT",
    }


def main() -> int:
    compiled = json.loads(COMPILED.read_text(encoding="utf-8"))
    generated = json.loads(GENERATED.read_text(encoding="utf-8"))
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    contracts = compiled["video_generation_contracts"]
    if set(REFERENCE_DIALOGUES) != {item["unit_id"] for item in contracts}:
        raise RuntimeError("reference map must cover every Writer Agent unit exactly once")
    clips = old_clip_map(project)
    stills = selected_stills(admission)
    shots = {item["shot_id"]: item for item in compiled["shot_contracts"]}
    dialogues = {item["dialogue_id"]: item for item in compiled["dialogue_contracts"]}
    tasks = [build_task(item, clips, stills, shots, dialogues) for item in contracts]
    payload = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E28",
        "status": "READY_FOR_ENTITY_REFERENCE_PREFLIGHT_ONLY",
        "concurrency": len(tasks),
        "max_retries": 1,
        "output_dir": str((ASSET_ROOT / "candidates").relative_to(ROOT)),
        "qa_dir": "qa/e28_writer_agent_v050_entity_reference_20260721",
        "scene_contract_ref": str(SCENE_STATE.relative_to(ROOT)),
        "writer_agent_provenance": {
            "status": "PASS",
            "agent_version": compiled["agent_version"],
            "schema_version": compiled["schema_version"],
            "generated_script": str(GENERATED),
            "generated_script_sha256": sha256(GENERATED),
            "compiled_script": str(COMPILED),
            "compiled_script_sha256": sha256(COMPILED),
            "fixture_used": bool((generated.get("generation_trace") or {}).get("fixture_used", False)),
        },
        "base_batch_note": "Submit all 12 units concurrently after full preflight; keep passed units and retry failed units only.",
        "tasks": tasks,
    }
    write_json(CONFIG_OUT, payload)
    write_json(
        RECEIPT_OUT,
        {
            "schema": "qingshan.entity_reference_asset_build_receipt.v1",
            "episode": "E28",
            "recorded_at": datetime.now().astimezone().isoformat(),
            "status": "ASSETS_BUILT_PENDING_NO_NETWORK_PREFLIGHT",
            "unit_count": len(tasks),
            "config": str(CONFIG_OUT),
            "config_sha256": sha256(CONFIG_OUT),
            "video_sequence_count": len(tasks),
            "audio_sequence_count": len(tasks),
            "selected_still_bindings": sum(len(task["reference_images"]) for task in tasks),
            "direct_pass_stills": admission["direct_pass_count"],
            "conditional_admission_stills": admission["conditional_admission_count"],
            "remote_credit": 0,
            "next_action": "Run preflight_entity_reference_batch.py; submit all 12 units concurrently only on full PASS.",
        },
    )
    print(json.dumps({"status": "PASS", "units": len(tasks), "config": str(CONFIG_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
