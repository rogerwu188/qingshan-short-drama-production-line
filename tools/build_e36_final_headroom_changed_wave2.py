#!/usr/bin/env python3
"""Build six materially changed E36 repairs that fit the final credit headroom."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
OUT = PROD / "autonomous_recovery_20260731/final_headroom_changed_wave2"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MAILBOX_SHA = "8f2e27e387e37e607c5ab3d4b8d61bbfaef5a78744a64faca488f05b4b5f1ecd"
PAID_BEFORE = 9240

W1 = OUT.parent / "u02_u11_changed_repairs_wave1"
TERMINAL = OUT.parent / "ready_terminal_splits_wave1"

SPECS = [
    {"slug": "u02_line02", "unit": "U02", "line": 2, "model": "seedance-2.0-fast", "duration": 6,
     "credits": 96, "start": 0.45, "end": 2.35, "speaker": "陈迹", "text": "不能伤官差。",
     "parent": "2e0df768-ab03-4c9c-a7f7-9f6cc9a17ea4",
     "source": W1 / "u02_line02/E36_U02_CANONICAL_L02_PRO_CHANGED_W1_BATCH.json"},
    {"slug": "u02_line03", "unit": "U02", "line": 3, "model": "seedance-2.0-fast", "duration": 8,
     "credits": 128, "start": 0.40, "end": 6.10, "speaker": "陈迹", "text": "伤一个，咱们就是劫法场的钦犯。人，只能从刀下换走。",
     "parent": "542e18eb-a8b6-4136-bf43-a41f9c122034",
     "source": W1 / "u02_line03/E36_U02_CANONICAL_L03_PRO_CHANGED_W1_BATCH.json"},
    {"slug": "u11_line16", "unit": "U11", "line": 16, "model": "seedance-2.0-fast", "duration": 8,
     "credits": 128, "start": 0.40, "end": 6.10, "speaker": "云羊", "text": "空信封……可他每露一次面，咱们就倾巢而动。这不合规矩。",
     "parent": "ce147f4d-9c95-48a5-8f6d-09541ba3bb01",
     "source": W1 / "u11_line16/E36_U11_CANONICAL_L16_PRO_CHANGED_W1_BATCH.json"},
    {"slug": "u14_line25", "unit": "U14", "line": 25, "model": "seedance-2.0-pro", "duration": 6,
     "credits": 120, "start": 0.40, "end": 4.80, "speaker": "陈迹", "text": "看各方溅起多大的浪。",
     "parent": "76d9c91b-1369-4e45-951c-2927e63eeb1d",
     "source": TERMINAL / "u14_line25/E36_U14_CANONICAL_L25_SPLIT_W1_BATCH.json"},
    {"slug": "u14_line26", "unit": "U14", "line": 26, "model": "seedance-2.0-fast", "duration": 8,
     "credits": 128, "start": 0.40, "end": 6.50, "speaker": "陈迹", "text": "他不是废子，是景朝拿来试各方反应的活棋子。",
     "parent": "b9727c7e-0a09-4c42-aca3-ccb6418ea44d",
     "source": TERMINAL / "u14_line26/E36_U14_CANONICAL_L26_SPLIT_W1_BATCH.json"},
    {"slug": "u14_line28", "unit": "U14", "line": 28, "model": "seedance-2.0-fast", "duration": 8,
     "credits": 128, "start": 0.30, "end": 6.90, "speaker": "陈迹", "text": "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。",
     "parent": "81dda971-ce7d-4266-9b50-339450942b5d",
     "source": TERMINAL / "u14_line28/E36_U14_CANONICAL_L28_SPLIT_W1_BATCH.json"},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def prompt_for(spec: dict, old_prompt: str) -> str:
    duration = spec["duration"]
    tail = round(duration - spec["end"], 2)
    route = "Fast" if spec["model"].endswith("fast") else "Pro"
    header = (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        f"【materially changed wave2】改用 Seedance {route}{duration}s，父任务={spec['parent']}；"
        "本次改变模型路由、时长/节奏与参考实体约束，禁止复制父任务画面或音轨。\n"
    )
    body = old_prompt.split("\n", 1)[1] if "\n" in old_prompt else old_prompt
    body = body.replace("0.00-6.00秒", f"0.00-{duration:.2f}秒")
    body = body.replace("0.35-5.45秒", f"{spec['start']:.2f}-{spec['end']:.2f}秒")
    body = body.replace("0.25-5.55秒", f"{spec['start']:.2f}-{spec['end']:.2f}秒")
    body = body.replace("0.20-5.55秒", f"{spec['start']:.2f}-{spec['end']:.2f}秒")
    body += (
        f"\n【逐字发音与收尾硬锁】唯一可见说话人{spec['speaker']}在{spec['start']:.2f}-{spec['end']:.2f}秒"
        f"只说一次 canonical 原句：“{spec['text']}”不得同义改写、吞字或加字；"
        f"末字后保留至少{tail:.2f}秒清晰闭口呼吸尾帧，眼神和身体动作自然收束。"
    )
    if spec["line"] == 2:
        body += " 发音提示仅供模型控制且不得作为额外台词：伤=shāng，官差=guān chāi；按‘不能／伤／官差’三词组清楚发声。"
    if spec["line"] == 16:
        body += (
            " 全片只出现一个无字空信封，固定在画面左后方桌面；云羊双手始终抓住自己腰带两端，"
            "离信封至少两掌宽，猫和其他动物完全不存在，任何手指不得进入信封周围禁区。"
            " <音效>衣料轻响、腰带摩擦、烛焰轻爆与药帘风声</音效>"
        )
    if spec["unit"] == "U14":
        body += " 皎兔和其他人物彻底不入镜且闭口；只保留十七岁陈迹单人表演，避免身份和口型归属歧义。"
    return header + body.strip() + "\n"


def main() -> None:
    jobs = []
    for spec in SPECS:
        src = json.loads(spec["source"].read_text(encoding="utf-8"))
        old_task = src["tasks"][0]
        old_prompt = (ROOT / old_task["prompt_path"]).read_text(encoding="utf-8")
        out = OUT / spec["slug"]
        out.mkdir(parents=True, exist_ok=True)
        stem = f"E36_{spec['unit']}_CANONICAL_L{spec['line']:02d}_CHANGED_W2"
        prompt_path = out / f"{stem}_PROMPT.txt"
        prompt_path.write_text(prompt_for(spec, old_prompt), encoding="utf-8")
        prompt_sha = sha(prompt_path)

        qa_rel = f"qa/e36_agentcut_20260730/final_headroom_changed_wave2_{spec['slug']}_runtime"
        media_rel = f"working_assets/e36_autonomous_recovery_20260731/final_headroom_changed_wave2_{spec['slug']}"
        (ROOT / qa_rel).mkdir(parents=True, exist_ok=True)
        (ROOT / media_rel).mkdir(parents=True, exist_ok=True)

        dialogue = copy.deepcopy(old_task["dialogue"][0])
        dialogue.update({
            "dia_id": stem.replace("_", "-"), "spoken_text": spec["text"],
            "start_seconds": spec["start"], "end_seconds": spec["end"],
            "breath_after_seconds": round(spec["duration"] - spec["end"], 2),
            "audio_mode": "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION",
            "human_listening_exception": True, "external_voice_reference": False,
            "path": "", "remote_asset_id": "", "language": "zh-CN",
            "native_video_audio": True, "lip_sync": True, "breath_expression_sync": True,
        })
        dialogue_path = out / f"{stem}_DIALOGUE_MANIFEST.json"
        dump(dialogue_path, {"schema": "qingshan.video_dialogue_manifest.v1", "episode": "E36", "status": "PASS",
                             "source_script_sha256": SCRIPT_SHA, "rows": [{k: v for k, v in dialogue.items() if k not in {"language", "native_video_audio", "lip_sync", "breath_expression_sync"}}]})

        complete = json.loads((ROOT / src["complete_video_prompt_manifest_ref"]).read_text(encoding="utf-8"))
        for row in complete.get("rows", []):
            if row.get("unit_id") == spec["unit"]:
                row["prompt_path"] = rel(prompt_path)
                row["prompt_sha256"] = prompt_sha
        complete_path = out / f"{stem}_COMPLETE_VIDEO_PROMPT_MANIFEST.json"
        dump(complete_path, complete)

        batch = copy.deepcopy(src)
        batch.update({
            "status": "ready", "source_cl2x": "CL2X-875", "source_cl2x_mailbox_sha256": MAILBOX_SHA,
            "source_mailbox_sha256": MAILBOX_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "episode_paid_credits_before": PAID_BEFORE, "video_credit_limit": spec["credits"],
            "output_dir": media_rel, "qa_dir": qa_rel,
            "complete_video_prompt_manifest_ref": rel(complete_path), "dialogue_manifest_ref": rel(dialogue_path),
            "changed_input_parent_task_id": spec["parent"], "changed_input_repair": True,
            "unchanged_retry": False, "max_retries": 0,
        })
        task = batch["tasks"][0]
        task.update({
            "task_key": stem.replace("_", "-"), "source_id": stem.replace("_", "-"),
            "batch_id": stem.replace("_", "-"), "status": "ready", "model": spec["model"],
            "duration_seconds": spec["duration"], "duration": spec["duration"],
            "edit_target_duration_seconds": spec["duration"], "prompt_path": rel(prompt_path),
            "prompt_file": rel(prompt_path), "prompt_sha256": prompt_sha, "dialogue": [dialogue],
            "changed_input_parent_task_id": spec["parent"], "replaces_parent_task_id": spec["parent"],
            "changed_input_repair": True, "unchanged_retry": False, "max_retries": 0,
            "source_segment_id": spec["slug"], "dialogue_audio_assets": [], "reference_audios": [],
            "reference_audio_asset_ids": [], "audio_reference_optional": True,
            "model_native_text_only_dialogue_ids": [dialogue["dia_id"]], "native_dialogue_required": True,
            "visible_speaker_required": True,
        })
        if spec["line"] == 16:
            anchor = "working_assets/e36_autonomous_recovery_20260731/final_headroom_changed_wave2_anchors/E36_U11_L16_CHANGED_W2_START_ANCHOR.png"
            task["reference_images"] = [task["reference_images"][0], anchor]
            task["reference_image_sequence"] = [task["reference_image_sequence"][0], {
                "asset_label": "@图片2", "role": "CHANGED_START_MOTION_AND_CONTACT_SAFETY_ANCHOR",
                "state_id": "E36-U11-L16-CHANGED-W2-START", "path": anchor,
                "sha256": "54281f73618c286f13b90a744806261594a035a0d4395b882a6613b2087a93dc",
                "identity_reference": False,
            }]
            task["planned_reference_image_count"] = 1
        if spec["unit"] == "U14":
            task["planned_reference_image_count"] = 2
            for binding in task.get("multimodal_entity_bindings", []):
                if binding.get("entity_id") == "jiaotu":
                    binding["visible_speaker"] = False
                    binding["lip_sync"] = False
        for beat in task.get("performance_spec", {}).get("motion_beats", []):
            beat["end_seconds"] = float(spec["duration"])
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5", "duration_seconds": spec["duration"],
            "rationale": "Materially changed route/timing isolates one canonical native-Mandarin line and reserves a closed-mouth tail.",
            "edit_policy": "Preserve native Mandarin and lip sync; no post-dub, time stretch, filler or duplicate frames.",
        }
        task["multimodal_binding_sha256"] = hashlib.sha256(json.dumps(
            task.get("multimodal_entity_bindings") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        config_path = out / f"{stem}_BATCH.json"
        dump(config_path, batch)
        jobs.append({"unit": spec["unit"], "line": spec["line"], "model": spec["model"],
                     "duration_seconds": spec["duration"], "config": rel(config_path), "config_sha256": sha(config_path),
                     "prompt": rel(prompt_path), "prompt_sha256": prompt_sha, "qa_dir": qa_rel,
                     "media_dir": media_rel, "projected_credits": spec["credits"], "parent_task_id": spec["parent"]})

    projected = sum(j["projected_credits"] for j in jobs)
    index = {"schema": "qingshan.e36.final_headroom_changed_wave2.v1", "status": "READY_FOR_CONCURRENT_PRECHECK",
             "source_cl2x": "CL2X-875", "source_mailbox_sha256": MAILBOX_SHA,
             "source_script_sha256": SCRIPT_SHA, "source_manifest_sha256": MANIFEST_SHA,
             "episode_paid_credits_before": PAID_BEFORE, "projected_credits": projected,
             "projected_episode_total": PAID_BEFORE + projected, "jobs": jobs}
    index_path = OUT / "E36_FINAL_HEADROOM_CHANGED_WAVE2_INDEX.json"
    dump(index_path, index)
    print(json.dumps({"index": rel(index_path), "index_sha256": sha(index_path), "projected": projected,
                      "projected_total": PAID_BEFORE + projected, "jobs": jobs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
