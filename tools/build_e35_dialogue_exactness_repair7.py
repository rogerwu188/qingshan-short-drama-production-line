#!/usr/bin/env python3
"""Rebuild E35 U05A and U21B with corrected exact-dialogue inputs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
VIDEO_DIR = PROD / "video_performance_v1"
PROMPT_DIR = PROD / "video_prompts_performance_v1"
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_EXACTNESS_REPAIR5.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR5.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR5.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_EXACTNESS_REPAIR7.json"
OUT_CONFIG_U21B_ONLY = VIDEO_DIR / "E35_VIDEO_U21B_DIALOGUE_EXACTNESS_REPAIR7_R3.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR7.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR7.json"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_DIALOGUE_REPAIR5_EXACTNESS_FAILURE_REPAIR7.json"
U21_AUDIO_A = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045A.wav"
U21_AUDIO_A_PADDED = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045A_MIN2S.wav"
U21_AUDIO_B = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045B.wav"
U21_AUDIO_QA = ROOT / "qa/e35_v1_release_20260723/E35_U21B_SPLIT_AUDIO_REPAIR7_QA.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    audio_qa = load(U21_AUDIO_QA)
    component_rows = {
        row["dialogue_id"]: row for row in audio_qa["rows"]
        if row["dialogue_id"] in {"E35-DIA-SEG-045A", "E35-DIA-SEG-045B"}
    }
    if audio_qa.get("status") != "PASS_COMPONENTS" or set(component_rows) != {"E35-DIA-SEG-045A", "E35-DIA-SEG-045B"}:
        raise SystemExit("U21B split reference components have not passed fail-closed QA")
    for dialogue_id, path in (("E35-DIA-SEG-045A", U21_AUDIO_A), ("E35-DIA-SEG-045B", U21_AUDIO_B)):
        row = component_rows[dialogue_id]
        if row.get("normalized_exact_match") is not True or row.get("sha256") != sha(path):
            raise SystemExit(f"U21B component mismatch: {dialogue_id}")
    if not U21_AUDIO_A_PADDED.is_file():
        raise SystemExit("U21B first exact component has not been padded to Seedance's two-second minimum")

    config = load(BASE_CONFIG)
    task_by_unit = {row["unit_id"]: row for row in config["tasks"]}
    prompt_manifest = load(BASE_PROMPTS)
    prompt_rows = {row["unit_id"]: copy.deepcopy(row) for row in prompt_manifest["rows"]}
    dialogue = load(BASE_DIALOGUE)
    dialogue_by_unit = {row["video_unit_id"]: copy.deepcopy(row) for row in dialogue["rows"]}
    tasks = []

    for unit_id in ("E35-CW-U05A", "E35-CW-U21B"):
        task = copy.deepcopy(task_by_unit[unit_id])
        task["task_key"] = f"{unit_id}-PERFORMANCE-V1-DIALOGUE-EXACTNESS-REPAIR7"
        task["batch_id"] = "E35-V1-DIALOGUE-EXACTNESS-REPAIR7-20260724"
        task["visual_zone"] = f"{unit_id}-V1-DIALOGUE-EXACTNESS-REPAIR7"
        prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
        if unit_id == "E35-CW-U05A":
            prompt = prompt.replace(
                "必须在第0.2秒开始，",
                "必须在第0.2秒开始；开口第一个音节必须是第四声 shì（汉字‘是’），绝不能说 ruò（‘若’）或任何替代字；",
                1,
            )
            prompt += "\n首字硬门：首帧开口只形成汉字‘是’的 shì 口型与声音；完整台词第一字不是‘是’即判失败。\n"
        else:
            task["duration"] = 6
            task["duration_seconds"] = 6
            task["edit_target_duration_seconds"] = 6
            task["duration_plan"] = {
                "policy": "qingshan.shot_generation_duration.v5",
                "duration_seconds": 6,
                "rationale": "Use a newly generated exact reference whose normalized ASR is 100% for the locked line.",
                "edit_policy": "Use all six seconds at native speed; never truncate the audio-driven sentence.",
            }
            task["performance_spec"]["duration_seconds"] = 6
            task["performance_spec"]["motion_beats"][0]["end_seconds"] = 6.0
            base_asset = task["dialogue_audio_assets"][0]
            assets = []
            for slot, dialogue_id, text, path in (
                ("@音频1", "E35-DIA-SEG-045A", "照他们的规矩，", U21_AUDIO_A_PADDED),
                ("@音频2", "E35-DIA-SEG-045B", "假谍探是要当街处决的！", U21_AUDIO_B),
            ):
                row = component_rows[dialogue_id]
                asset = copy.deepcopy(base_asset)
                asset.update({
                    "dia_id": dialogue_id,
                    "spoken_text": text,
                    "path": rel(path),
                    "sha256": sha(path),
                    "duration_seconds": 2.2 if dialogue_id == "E35-DIA-SEG-045A" else float(row["duration_seconds"]),
                    "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
                    "remote_asset_id": None,
                    "voice_reference_asset_id": "v0udrgrojud",
                    "audio_slot": slot,
                    "source_voice": "AGENTCUT_SPEECH_GENERATION_EXACT_SPLIT_COMPONENT_MINIMUM_DURATION_PADDED" if dialogue_id == "E35-DIA-SEG-045A" else "AGENTCUT_SPEECH_GENERATION_EXACT_SPLIT_COMPONENT",
                })
                assets.append(asset)
            task["dialogue_audio_assets"] = assets
            task["dialogue"] = [
                {"dia_id": asset["dia_id"], "speaker": asset["speaker"], "speaker_id": asset["speaker_id"], "spoken_text": asset["spoken_text"]}
                for asset in assets
            ]
            task["reference_audios"] = [rel(U21_AUDIO_A_PADDED), rel(U21_AUDIO_B)]
            task["reference_audio_asset_ids"] = []
            task.pop("resolved_reference_audio_asset_ids", None)
            task["dialogue_audio_coverage"] = {"required": 2, "bound": 2, "status": "PASS"}
            for binding in task["multimodal_entity_bindings"]:
                if binding["entity_id"] == "yunyang":
                    binding["dialogue_audio_slots"] = ["@音频1", "@音频2"]
            prompt = re.sub(r"时长5秒。", "时长6秒。", prompt, count=1)
            prompt = prompt.replace("最迟第4.4秒完整说完", "最迟第5.2秒完整说完")
            prompt = prompt.replace("0.000-4.400秒", "0.000-5.200秒")
            prompt = prompt.replace("4.400-5.000秒", "5.200-6.000秒")
            prompt = re.sub(
                r"对白音频绑定：\n- @音频1=[^\n]+",
                "对白音频绑定：\n- @音频1=E35-DIA-SEG-045A：云羊逐字说‘照他们的规矩，’，用本条精确音频驱动原生普通话。\n- @音频2=E35-DIA-SEG-045B：紧接音频1，云羊逐字说‘假谍探是要当街处决的！’，用本条精确音频驱动原生普通话。",
                prompt,
                count=1,
            )
            prompt += "\n音频顺序硬门：先完整同步@音频1，再无缝同步@音频2；不得跳过@音频1，不得把两段重叠、倒序或改写。\n"
        out_prompt = PROMPT_DIR / f"{unit_id}-DIALOGUE-EXACTNESS-REPAIR7.txt"
        out_prompt.write_text(prompt, encoding="utf-8")
        task["prompt_file"] = rel(out_prompt)
        task["prompt_path"] = rel(out_prompt)
        task["prompt_sha256"] = sha(out_prompt)
        task["repair_evidence"] = rel(EVIDENCE)
        task["multimodal_binding_sha256"] = hashlib.sha256(
            json.dumps(task["multimodal_entity_bindings"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        task.pop("generation_fingerprint", None)
        task["generation_fingerprint"] = generation_fingerprint(task)
        tasks.append(task)
        prompt_rows[unit_id].update({
            "duration_seconds": task["duration_seconds"],
            "prompt_path": rel(out_prompt),
            "prompt_sha256": task["prompt_sha256"],
            "status": "PASS_COMPLETE_CHANGED_INPUT_DIALOGUE_EXACTNESS_REPAIR7",
        })

    prompt_manifest["rows"] = [prompt_rows[row["unit_id"]] for row in prompt_manifest["rows"]]
    prompt_manifest["scope"] = "FAILED_ONLY_DIALOGUE_EXACTNESS_REPAIR7"
    write(OUT_PROMPTS, prompt_manifest)

    u21_rows = []
    base_u21 = dialogue_by_unit["E35-CW-U21B"]
    for asset in next(task for task in tasks if task["unit_id"] == "E35-CW-U21B")["dialogue_audio_assets"]:
        row = copy.deepcopy(base_u21)
        row.update({
            "dia_id": asset["dia_id"],
            "spoken_text": asset["spoken_text"],
            "path": asset["path"],
            "sha256": asset["sha256"],
            "duration_seconds": asset["duration_seconds"],
            "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
            "asr_transcript": asset["spoken_text"],
            "asr_similarity": 1.0,
            "status": "PASS",
        })
        u21_rows.append(row)
    dialogue["rows"] = [dialogue_by_unit["E35-CW-U05A"], *u21_rows]
    dialogue["line_count"] = 3
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_DIALOGUE_EXACTNESS_REPAIR7"
    write(OUT_DIALOGUE, dialogue)

    config["tasks"] = tasks
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPTS)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["runtime_seconds"] = 13
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [
        {"task_key": task["task_key"], "scene_id": task["scene_id"], "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]}
        for task in tasks
    ]
    write(OUT_CONFIG, config)
    u21b_only = copy.deepcopy(config)
    u21b_only["tasks"] = [task for task in tasks if task["unit_id"] == "E35-CW-U21B"]
    u21b_only["runtime_seconds"] = 6
    u21b_only["preserved_prompt_professionalism_evidence"] = [
        row for row in config["preserved_prompt_professionalism_evidence"]
        if "U21B" in row["task_key"]
    ]
    write(OUT_CONFIG_U21B_ONLY, u21b_only)
    write(EVIDENCE, {
        "schema": "qingshan.e35.dialogue_exactness_repair7.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR7_CHANGED_INPUT_READY",
        "source_video_asr": "qa/e35_v1_release_20260723/E35_DIALOGUE_REPAIR5_TARGETED_ASR_V1.json",
        "u21b_audio_qa": rel(U21_AUDIO_QA),
        "items": [
            {"unit_id": "E35-CW-U05A", "failure": "First character changed from 是 to 若.", "changed_input": "First phoneme and character hard-lock added."},
            {"unit_id": "E35-CW-U21B", "failure": "Old reference audio itself omitted the opening phrase.", "changed_input": "Replaced with a new exact 100%-ASR reference assembled from two independently verified AgentCut generations."},
        ],
        "planned_additional_video_seconds": 13,
        "planned_additional_video_credits": 260,
        "projected_episode_video_credit_total": 5560,
        "credit_limit": 6000,
        "rollback": "Preserve repair5 outputs and ASR report; replace only after repair7 exact native-dialogue PASS.",
    })
    print(json.dumps({"status": "PASS", "tasks": [task["task_key"] for task in tasks], "projected_episode_video_credits": 5560}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
