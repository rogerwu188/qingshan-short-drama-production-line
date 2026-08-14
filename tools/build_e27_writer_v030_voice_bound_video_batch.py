#!/usr/bin/env python3
"""Build the E27 dialogue-only retry batch with immutable voice bindings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720/production/video_batch_v1"
SOURCE_CONFIG = BASE / "video_batch_v1.json"
COMPILED = ROOT / ".professional_writer_agent/current/examples/e27.agent-native.compiled.json"
VOICE_REGISTRY = ROOT / "configs/e27_voice_binding_registry_v1_20260720.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720/production/video_batch_v2_voice_bound"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = load(SOURCE_CONFIG)
    compiled = load(COMPILED)
    registry = load(VOICE_REGISTRY)
    speakers = registry["speakers"]
    dialogue_by_shot: dict[str, list[dict]] = {}
    for row in compiled["dialogue_contracts"]:
        dialogue_by_shot.setdefault(row["shot_id"], []).append(row)

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    held = []
    manifest = [
        "# E27 Voice-Bound Dialogue Video Retry Prompts",
        "",
        "Only dialogue shots whose speakers have immutable audio assets are resubmitted. Existing visual candidates remain immutable evidence.",
        "",
    ]
    for original in source["tasks"]:
        shot_id = original["shot_id"]
        dialogues = dialogue_by_shot.get(shot_id, [])
        if not dialogues:
            continue
        missing = [row["speaker_id"] for row in dialogues if not speakers.get(row["speaker_id"], {}).get("voice_asset_id")]
        if missing:
            held.append({
                "shot_id": shot_id,
                "dialogue_ids": [row["dialogue_id"] for row in dialogues],
                "missing_speaker_ids": missing,
                "policy": speakers[missing[0]]["current_episode_policy"],
            })
            continue

        ordered_speakers = []
        for row in dialogues:
            if row["speaker_id"] not in ordered_speakers:
                ordered_speakers.append(row["speaker_id"])
        asset_ids = [speakers[speaker_id]["voice_asset_id"] for speaker_id in ordered_speakers]
        audio_labels = {speaker_id: f"@音频{index + 1}" for index, speaker_id in enumerate(ordered_speakers)}
        binding_lines = []
        for row in dialogues:
            profile = speakers[row["speaker_id"]]
            binding_lines.append(
                f"{profile['name']}必须使用{audio_labels[row['speaker_id']]}的同一音色，以自然普通话只说一次：{{{row['text']}}}；"
                f"表演要求：{row['performance']}。"
            )
        original_prompt_path = ROOT / original["prompt_file"]
        original_prompt = original_prompt_path.read_text(encoding="utf-8").strip()
        voice_header = (
            "声音连续性硬绑定：输入音频只用于角色音色、年龄、共鸣位置、语速与气息身份参考，禁止照搬参考音频中的旧台词或背景声。"
            + "".join(binding_lines)
            + "非说话角色全程闭口；禁止换声、串声、旁白、额外对白和外部BGM。"
        )
        prompt = voice_header + "\n" + original_prompt
        prompt_path = prompt_dir / f"{shot_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        task = dict(original)
        task["task_key"] = f"{shot_id}-WRITER-AGENT-V030-VIDEO-V2-VOICE-BOUND"
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task["prompt_sha256"] = sha256(prompt_path)
        task["reference_audio_asset_ids"] = asset_ids
        task["audio_slot_bindings"] = [
            {
                "speaker_id": speaker_id,
                "speaker_name": speakers[speaker_id]["name"],
                "audio_slot": audio_labels[speaker_id],
                "voice_asset_id": speakers[speaker_id]["voice_asset_id"],
            }
            for speaker_id in ordered_speakers
        ]
        task["audio_binding_status"] = "PASS_IMMUTABLE_ASSET_BOUND"
        task["status"] = "READY_CONCURRENT_SUBMIT"
        tasks.append(task)
        manifest.extend([
            f"## {shot_id}",
            "",
            f"- Audio assets: `{', '.join(asset_ids)}`",
            f"- Bindings: `{json.dumps(task['audio_slot_bindings'], ensure_ascii=False)}`",
            "",
            "```text",
            prompt,
            "```",
            "",
        ])

    if len(tasks) != 13:
        raise SystemExit(f"expected 13 voice-bound dialogue shots, got {len(tasks)}")
    if {row["shot_id"] for row in held} != {"E27-N01", "E27-N02"}:
        raise SystemExit(f"unexpected held shots: {held}")

    config = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E27",
        "status": "READY_13_DIALOGUE_VIDEO_CONCURRENT_RESUBMIT",
        "concurrency": 13,
        "max_retries": 1,
        "output_dir": "working_assets/e27_writer_agent_v030_video_v2_voice_bound_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v030_video_v2_voice_bound_20260720",
        "scene_contract_ref": source["scene_contract_ref"],
        "script_readiness_report": source["script_readiness_report"],
        "writer_agent_provenance": source["writer_agent_provenance"],
        "voice_registry": str(VOICE_REGISTRY.relative_to(ROOT)),
        "base_batch_note": "Retry only dialogue shots with immutable voice assets; preserve all visual passes and keep unresolved singleton/one-line native candidates for voice-profile QA.",
        "tasks": tasks,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    config_path = DEST / "video_batch_v2_voice_bound.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    held_path = DEST / "unbound_single_line_shots.json"
    held_path.write_text(json.dumps({
        "schema": "qingshan.unbound_single_line_voice_hold.v1",
        "episode": "E27",
        "status": "VOICE_PROFILE_QA_REQUIRED_DO_NOT_CLAIM_LOCKED",
        "items": held,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = DEST / "E27_VOICE_BOUND_DIALOGUE_PROMPTS_13.md"
    manifest_path.write_text("\n".join(manifest), encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "voice_bound_tasks": len(tasks),
        "held_native_single_line_shots": len(held),
        "config": str(config_path.relative_to(ROOT)),
        "manifest": str(manifest_path.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
