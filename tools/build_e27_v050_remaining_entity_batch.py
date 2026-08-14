#!/usr/bin/env python3
"""Build E27 Writer Agent v0.5 entity-reference units after the B01 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPILED = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-20/"
    "qingshan-professional-writer-agent/outputs/qingshan-writer-agent/"
    "examples/e27.agent-native.compiled.json"
)
GENERATED = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-20/"
    "qingshan-professional-writer-agent/outputs/qingshan-writer-agent/"
    "examples/e27.agent-native.generated.json"
)
SOURCE_PROJECT = ROOT / "configs/e27_agentcut_project_v17_n01_baseline_repair_20260720.json"
KEYFRAME_RECEIPT = ROOT / "workflow/tasks/E27_PRO_SCRIPT_KEYFRAME_IMAGE_BATCH_V1_RECEIPT_20260720.json"
CONFIG_OUT = ROOT / "configs/E27_remaining_11_entity_reference_sequence_v050_20260720.json"
SCENE_STATE_OUT = ROOT / "configs/e27_writer_agent_v050_scene_state_20260720.json"
RECEIPT_OUT = ROOT / "workflow/tasks/E27_REMAINING_11_ENTITY_REFERENCE_ASSET_BUILD_RECEIPT_20260720.json"
PROMPT_DIR = ROOT / "workflow/prompts/e27_remaining_entity_reference_v050_20260720"
ASSET_ROOT = ROOT / "working_assets/e27_remaining_entity_reference_v050_20260720"


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


def source_map(project: dict) -> dict[str, dict]:
    clips = project["timeline"]["videoTracks"][0]["clips"]
    mapped: dict[str, dict] = {}
    for clip in clips:
        metadata = clip.get("metadata", {})
        shot_id = metadata.get("shot_id") or metadata.get("source_id") or clip.get("id", "").removesuffix("-VIDEO")
        if not shot_id:
            continue
        path = Path(clip["source"])
        mapped[shot_id] = {
            "path": path,
            "sha256": metadata.get("source_sha256") or sha256(path),
        }
    return mapped


def keyframe_map(contracts: list[dict], receipt: dict) -> dict[str, dict]:
    scene_ids = list(dict.fromkeys(item["scene_id"] for item in contracts))
    rows = receipt["tasks"]
    if len(scene_ids) != len(rows):
        raise RuntimeError(f"scene/keyframe mismatch: {len(scene_ids)} != {len(rows)}")
    result: dict[str, dict] = {}
    for scene_id, row in zip(scene_ids, rows):
        path = Path(row.get("output_path") or row.get("downloaded_path") or row["output"])
        result[scene_id] = {
            "path": path,
            "sha256": row.get("sha256") or row.get("output_sha256") or sha256(path),
        }
    return result


def build_video(segments: list[dict], sources: dict[str, dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for segment in segments:
        command.extend(["-i", str(sources[segment["shot_id"]]["path"])])
    filters = []
    labels = []
    for index, segment in enumerate(segments):
        start = segment["shot_offset_start_seconds"]
        end = segment["shot_offset_end_seconds"]
        filters.append(
            f"[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            "fps=24,scale=720:1280:force_original_aspect_ratio=decrease,"
            f"pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black[v{index}]"
        )
        labels.append(f"[v{index}]")
    filters.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=0[vout]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            str(output),
        ]
    )
    run(command)


def build_audio(segments: list[dict], sources: dict[str, dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for segment in segments:
        command.extend(["-i", str(sources[segment["shot_id"]]["path"])])
    filters = []
    labels = []
    for index, segment in enumerate(segments):
        start = segment["shot_offset_start_seconds"]
        end = segment["shot_offset_end_seconds"]
        filters.append(
            f"[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=channel_layouts=stereo[a{index}]"
        )
        labels.append(f"[a{index}]")
    filters.append("".join(labels) + f"concat=n={len(segments)}:v=0:a=1[aout]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[aout]",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    run(command)


def sanitize_visual_text(text: str) -> str:
    """Keep the story fact while removing instructions to synthesize readable glyphs."""
    replacements = (
        (r"逐行\s*(?:浮起|显现|出现|露出)", "以不可读压痕的先后明暗变化表现"),
        (r"(?:字迹|字形|名字|真名|题字|铭文)\s*(?:显现|浮现|露出|出现|成形)", "不可读痕迹发生明暗变化"),
        (r"(?:显现|浮现|露出|出现)\s*(?:字迹|字形|名字|真名|题字|铭文)", "不可读痕迹发生明暗变化"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def render_prompt(contract: dict, shots: dict[str, dict], dialogues: dict[str, dict]) -> str:
    palette = "；".join(dict.fromkeys(shots[item["shot_id"]]["palette"] for item in contract["shot_plan"]))
    key_light = "；".join(dict.fromkeys(shots[item["shot_id"]]["key_light"] for item in contract["shot_plan"]))
    sound_by_shot: dict[str, list[str]] = {}
    for sound in contract.get("onsite_sound_plan", []):
        sound_by_shot.setdefault(sound["source_shot_id"], []).append(sound["cue"])
    lines = [
        f"这是《青山》E27 {contract['batch_id']} 的连续实体参考动作单元，时长{contract['duration_seconds']}秒。",
        f"锁定场景[[scene_1]]=@图片1，时间={contract['time_of_day']}；@视频1是本单元完整动作时序参考，@音频1是等长对白、现场声与环境声参考。",
        "必须重演同一剧情事实、人物身份、道具和空间，不得退化为单张静图动画，不得重置跨镜动作轨迹。",
        f"palette与色彩：{palette}。动机光与光影：{key_light}。黑位保留层次，高光受控。",
        "空间尺度沿用本场超广角大远景 establishing 定场，前景遮挡、中景动作、背景建筑保持可读纵深。",
        "力量推动环境介质：衣摆、尘粒、纸角、火焰或碎片只在人物发力和道具接触时产生符合地点与天气的响应。",
        "",
    ]
    for index, segment in enumerate(contract["shot_plan"], 1):
        shot = shots[segment["shot_id"]]
        event = sanitize_visual_text(shot["action"])
        dialogue_rows = [dialogues[item] for item in shot.get("dialogue_ids", [])]
        if dialogue_rows:
            dialogue_slot = " / ".join(
                f"{row['speaker_id']}：‘{row['text']}’" for row in dialogue_rows
            )
            dialogue_slot = "{对白：" + dialogue_slot + "}"
        else:
            dialogue_slot = "{无对白}"
        sound_cues = sound_by_shot.get(segment["shot_id"], [])
        sound_slot = "<现场声：" + "；".join(sound_cues or ["服装与地面接触声随动作起止同步"]) + ">"
        lines.append(
            f"镜头{index}【景别：{segment['shot_scale']}；机位：{segment['camera_height']}；"
            f"镜头运动：{segment['camera_motion']}；时间：{segment['unit_offset_start_seconds']}-"
            f"{segment['unit_offset_end_seconds']}秒】：{event} "
            "动作从起势开始，沿既定方向移动，在明确接触点发力并把结果停定；镜头只随主体动作改变，不漂移、不跳过因果。"
            f" {dialogue_slot} {sound_slot}"
        )
    lines.extend(["", "动作物理必须依次成立："])
    for phase in contract["action_physics"]["phases"]:
        lines.append(f"- {phase['phase']}：{sanitize_visual_text(phase['description'])}")
    lines.extend(["", "人物与道具轨迹："])
    for trajectory_type, trajectories in contract.get("trajectories", {}).items():
        for trajectory in trajectories:
            lines.append(f"- {trajectory_type}：" + json.dumps(trajectory, ensure_ascii=False, sort_keys=True))
    lines.extend(["", "现场声必须与接触点同步："])
    for sound in contract.get("onsite_sound_plan", []):
        lines.append(f"- {sound['segment_id']}：{sound['cue']}；同步点={sound['sync_to']}")
    lines.extend(
        [
            "",
            "写实国漫古装武侠质感，构图稳定、人物脸部稳定、材质受力真实、空间前中后景清楚。",
            "禁止：" + "；".join(contract["negative_constraints"]),
            "禁止字幕、水印、Logo、背景音乐、慢动作填充、循环动作、可读生成文字、同款分身或双胞胎效果。",
        ]
    )
    return "\n".join(lines) + "\n"


def temporal_evidence_segments(segments: list[dict]) -> list[dict]:
    if len(segments) > 1:
        return segments
    segment = segments[0]
    start = segment["shot_offset_start_seconds"]
    end = segment["shot_offset_end_seconds"]
    unit_start = segment["unit_offset_start_seconds"]
    unit_end = segment["unit_offset_end_seconds"]
    source_mid = (start + end) / 2
    unit_mid = (unit_start + unit_end) / 2
    first = dict(segment)
    first.update(
        {
            "segment_id": f"{segment['segment_id']}::INITIATION_TO_CONTACT",
            "shot_offset_end_seconds": source_mid,
            "unit_offset_end_seconds": unit_mid,
        }
    )
    second = dict(segment)
    second.update(
        {
            "segment_id": f"{segment['segment_id']}::FORCE_TRANSFER_TO_RESULT",
            "shot_offset_start_seconds": source_mid,
            "unit_offset_start_seconds": unit_mid,
        }
    )
    return [first, second]


def build_scene_state(compiled: dict) -> dict:
    shots_by_scene: dict[str, list[dict]] = {}
    for shot in compiled["shot_contracts"]:
        shots_by_scene.setdefault(shot["scene_id"], []).append(shot)
    rows = []
    for scene in compiled["scene_contracts"]:
        scene_id = scene["scene_id"]
        continuity = scene.get("continuity_in") or scene.get("continuity_out") or {}
        weather = continuity.get("weather") or "locked script weather"
        time_of_day = scene["time_of_day"]
        rows.append(
            {
                "scene_id": scene_id,
                "location": scene["location_id"],
                "time_of_day": time_of_day,
                "weather": weather,
                "event_summary": " ".join(item["action"] for item in shots_by_scene[scene_id]),
                "allowed_time_terms": ["night"] if "night" in time_of_day else ["daylight", "daytime"],
                "allowed_weather_terms": (
                    ["clear weather"] if "clear" in weather else []
                ),
                "forbidden": list(scene["negative_constraints"]),
            }
        )
    return {
        "schema": "qingshan.scene_state.v1",
        "episode": "E27",
        "source_script": str(COMPILED),
        "source_script_sha256": sha256(COMPILED),
        "status": "WRITER_AGENT_V050_ALL_SCENES_LOCKED",
        "scene_state": rows,
    }


def build_task(
    contract: dict,
    sources: dict[str, dict],
    keyframes: dict[str, dict],
    shots: dict[str, dict],
    dialogues: dict[str, dict],
) -> dict:
    batch_id = contract["batch_id"]
    unit_suffix = contract["unit_id"].split("::")[-1]
    task_key = f"{batch_id}-{unit_suffix}-ENTITY-REFERENCE-V050"
    video_path = ASSET_ROOT / "video/unit_sequences" / f"{task_key}-action-sequence.mp4"
    audio_path = ASSET_ROOT / "audio/unit_beds" / f"{task_key}-audio-sequence.wav"
    prompt_path = PROMPT_DIR / f"{batch_id}-{unit_suffix}.txt"
    build_video(contract["shot_plan"], sources, video_path)
    build_audio(contract["shot_plan"], sources, audio_path)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(render_prompt(contract, shots, dialogues), encoding="utf-8")
    video_sha = sha256(video_path)
    audio_sha = sha256(audio_path)
    evidence_segments = temporal_evidence_segments(contract["shot_plan"])
    scene = keyframes[contract["scene_id"]]
    reference_assets = []
    for requirement in contract["asset_requirements"]:
        asset = scene if requirement["asset_type"] == "scene" else {"path": video_path, "sha256": video_sha}
        if requirement["asset_type"] == "audio":
            asset = {"path": audio_path, "sha256": audio_sha}
        reference_assets.append(
            {
                "slot_id": requirement["slot_id"],
                "path": str(Path(asset["path"]).relative_to(ROOT)),
                "sha256": asset["sha256"],
            }
        )
    reference_assets.extend(
        [
            {"slot_id": f"AUDIO_SEQUENCE::{batch_id}-{unit_suffix}", "path": str(audio_path.relative_to(ROOT)), "sha256": audio_sha},
            {"slot_id": f"VIDEO_SEQUENCE::{batch_id}-{unit_suffix}", "path": str(video_path.relative_to(ROOT)), "sha256": video_sha},
        ]
    )
    return {
        "task_key": task_key,
        "tool_type": "video_generation",
        "generation_mode": "entity_reference_sequence",
        "batch_id": batch_id,
        "unit_id": contract["unit_id"],
        "source_id": f"{batch_id}::{unit_suffix}",
        "scene_id": contract["scene_id"],
        "visual_zone": contract["unit_id"],
        "variant_group": f"{batch_id}-CONTINUOUS-UNITS",
        "variant_label": unit_suffix,
        "duration": contract["duration_seconds"],
        "duration_seconds": contract["duration_seconds"],
        "duration_plan": {
            "policy": "qingshan.shot_generation_duration.v4",
            "duration_seconds": contract["duration_seconds"],
            "rationale": (
                f"Writer Agent v0.5 entity-reference sequence assigns {contract['duration_seconds']}s "
                f"to {contract['unit_id']} from its continuous source-shot timeline, dialogue, action "
                "physics and result boundary; no fixed-duration normalization."
            ),
            "edit_policy": (
                "Generate the full continuous action unit; AgentCut may trim only at the Writer Agent "
                "edit boundary while preserving wind-up, contact, force transfer and result."
            ),
        },
        "model": "seedance-2.0-pro",
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256(prompt_path),
        "action_reference_minimum": 1,
        "reference_images": [str(Path(scene["path"]).relative_to(ROOT))],
        "reference_audios": [str(audio_path.relative_to(ROOT))],
        "reference_videos": [str(video_path.relative_to(ROOT))],
        "reference_audio_sequence": {
            "duration_seconds": contract["duration_seconds"],
            "sha256": audio_sha,
            "segments": evidence_segments,
        },
        "reference_video_sequence": {
            "duration_seconds": contract["duration_seconds"],
            "sha256": video_sha,
            "segments": evidence_segments,
            "single_still_only": False,
        },
        "required_slot_ids": [item["slot_id"] for item in contract["asset_requirements"]],
        "reference_assets": reference_assets,
        "status": "READY_FOR_NO_NETWORK_PREFLIGHT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-b01", action="store_true")
    args = parser.parse_args()
    compiled = json.loads(COMPILED.read_text(encoding="utf-8"))
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    keyframe_receipt = json.loads(KEYFRAME_RECEIPT.read_text(encoding="utf-8"))
    contracts = compiled["video_generation_contracts"]
    sources = source_map(project)
    keyframes = keyframe_map(contracts, keyframe_receipt)
    shots = {item["shot_id"]: item for item in compiled["shot_contracts"]}
    dialogues = {item["dialogue_id"]: item for item in compiled["dialogue_contracts"]}
    selected = contracts if args.include_b01 else [item for item in contracts if item["batch_id"] != "E27-B01"]
    missing = sorted({shot["shot_id"] for item in selected for shot in item["shot_plan"] if shot["shot_id"] not in sources})
    if missing:
        raise RuntimeError(f"missing source shots: {missing}")
    tasks = [build_task(item, sources, keyframes, shots, dialogues) for item in selected]
    write_json(SCENE_STATE_OUT, build_scene_state(compiled))
    payload = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E27",
        "status": "READY_FOR_ENTITY_REFERENCE_PREFLIGHT_ONLY",
        "concurrency": len(tasks),
        "max_retries": 1,
        "output_dir": str((ASSET_ROOT / "candidates").relative_to(ROOT)),
        "qa_dir": "qa/e27_remaining_entity_reference_v050_20260720",
        "scene_contract_ref": "configs/e27_writer_agent_v050_scene_state_20260720.json",
        "writer_agent_provenance": {
            "status": "PASS",
            "agent_version": "0.5.0",
            "schema_version": "1.4.0",
            "generated_script": str(GENERATED),
            "generated_script_sha256": sha256(GENERATED),
            "compiled_script": str(COMPILED),
            "compiled_script_sha256": sha256(COMPILED),
        },
        "base_batch_note": "Submit all remaining units together only after 11/11 no-network preflight; retain passed items and retry failed units only.",
        "tasks": tasks,
    }
    write_json(CONFIG_OUT, payload)
    write_json(
        RECEIPT_OUT,
        {
            "schema": "qingshan.entity_reference_asset_build_receipt.v1",
            "episode": "E27",
            "recorded_at": datetime.now().astimezone().isoformat(),
            "status": "ASSETS_BUILT_PENDING_NO_NETWORK_PREFLIGHT",
            "unit_count": len(tasks),
            "batch_ids": sorted({item["batch_id"] for item in tasks}),
            "config": str(CONFIG_OUT),
            "config_sha256": sha256(CONFIG_OUT),
            "video_sequence_count": len(tasks),
            "audio_sequence_count": len(tasks),
            "prompt_count": len(tasks),
            "remote_credit": 0,
            "next_action": "Run preflight_entity_reference_batch.py; submit all units concurrently only on full PASS.",
        },
    )
    print(json.dumps({"status": "PASS", "units": len(tasks), "config": str(CONFIG_OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
