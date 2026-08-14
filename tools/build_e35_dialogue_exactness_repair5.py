#!/usr/bin/env python3
"""Rebuild only E35 dialogue units whose native speech is missing or inexact."""

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
BASE_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_FAILED_ONLY_REPAIR3.json"
BASE_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_REPAIR3.json"
BASE_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_REPAIR3.json"
OUT_CONFIG = VIDEO_DIR / "E35_VIDEO_DIALOGUE_EXACTNESS_REPAIR5.json"
OUT_PROMPTS = PROD / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR5.json"
OUT_DIALOGUE = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_DIALOGUE_EXACTNESS_REPAIR5.json"
EVIDENCE = ROOT / "qa/e35_v1_release_20260723/E35_DIALOGUE_REPAIR3_EXACTNESS_FAILURE_REPAIR5.json"


SPECS = {
    "E35-CW-U05A": {
        "duration": 7,
        "speaker": "chenji",
        "visual_entities": ["chenji", "yanjing"],
        "expression": "陈迹冷厉而清醒，逐字拆穿教词；严敬由强撑转为惊惧，皎兔在镜头外。",
        "action": "陈迹盯住被缚严敬，完整说出有人在严敬被捕前逐字教词；严敬听到后下颌绷紧、目光闪躲，脸色由强撑转惊惧。",
        "speech_end": 6.2,
        "reason": "The 24-character line was compressed into five seconds and replaced by unrelated speech; seven seconds restores a physically viable native-dialogue window.",
    },
    "E35-CW-U19B": {
        "duration": 4,
        "speaker": "chenji",
        "visual_entities": ["chenji"],
        "expression": "陈迹短促决断，轻微摇头后只吐出单音节“不”，随后完全闭口。",
        "action": "陈迹面对镜头外的皎兔轻微摇头，只说一个单音节“不”，绝不追加“好”或任何第二个字；说完把右手压在账底边缘并闭口。",
        "speech_end": 1.2,
        "reason": "The prior candidate added a second syllable; the changed prompt hard-locks one syllable and moves every listener off camera.",
    },
    "E35-CW-U21B": {
        "duration": 5,
        "speaker": "yunyang",
        "visual_entities": ["yunyang", "chenji"],
        "expression": "云羊焦急但吐字完整；陈迹压住立即出手的冲动，递信人与巡检在镜头外继续移动。",
        "action": "云羊看向陈迹，完整说出按密谍司规矩假谍探会被当街处决；陈迹听后目光骤紧但没有冲出檐影。",
        "speech_end": 4.4,
        "reason": "The exact reference audio is 3.993854 seconds but the prior unit was only four seconds, so the model dropped the opening phrase; five seconds preserves the whole reference plus breathing room.",
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def relabel_images(task: dict, entities: list[str]) -> None:
    state = copy.deepcopy(next(row for row in task["reference_image_sequence"] if not row.get("identity_reference")))
    selected = [state]
    for entity in entities:
        selected.append(copy.deepcopy(next(
            row for row in task["reference_image_sequence"]
            if row.get("identity_reference") and row.get("entity_id") == entity
        )))
    for index, row in enumerate(selected, start=1):
        row["asset_label"] = f"@图片{index}"
    task["reference_image_sequence"] = selected
    task["reference_images"] = [row["path"] for row in selected]
    slot_by_entity = {row.get("entity_id"): row["asset_label"] for row in selected if row.get("entity_id")}
    bindings = []
    for binding in task["multimodal_entity_bindings"]:
        if binding["entity_id"] not in entities:
            continue
        binding = copy.deepcopy(binding)
        binding["identity_image_slot"] = slot_by_entity[binding["entity_id"]]
        binding["visible_speaker"] = binding["entity_id"] == task["dialogue_audio_assets"][0]["speaker_id"]
        binding["lip_sync"] = binding["visible_speaker"]
        binding["dialogue_audio_slots"] = ["@音频1"] if binding["visible_speaker"] else []
        bindings.append(binding)
    task["multimodal_entity_bindings"] = bindings
    task["visual_entity_ids"] = entities
    task["nonvisual_entity_mentions"] = [f"{entity}_off_camera" for entity in {"chenji", "yanjing", "jiaotu", "yunyang"} - set(entities)]
    task.pop("resolved_reference_image_asset_ids", None)


def rewrite_prompt(task: dict, spec: dict, out_path: Path) -> None:
    prompt = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
    duration = spec["duration"]
    speech_end = spec["speech_end"]
    entity_names = {"chenji": "陈迹", "yanjing": "严敬", "jiaotu": "皎兔", "yunyang": "云羊"}
    entity_tokens = {"chenji": "[[char_chenji]]", "yanjing": "[[char_yanjing]]", "jiaotu": "[[char_jiaotu]]", "yunyang": "[[char_yunyang]]"}
    scene_tokens = {
        "E35-CW-S01": "[[scene_e35_s01]]",
        "E35-CW-S04": "[[scene_e35_s04]]",
        "E35-CW-S05": "[[scene_e35_s05]]",
    }
    visible = "、".join(entity_names[x] for x in spec["visual_entities"])
    visible_tokens = " ".join(entity_tokens[x] for x in spec["visual_entities"])
    hidden = "、".join(entity_names[x] for x in {"chenji", "yanjing", "jiaotu", "yunyang"} - set(spec["visual_entities"])) or "无"
    text = task["dialogue_audio_assets"][0]["spoken_text"]
    prompt = re.sub(r"时长\d+秒。", f"时长{duration}秒。", prompt, count=1)
    prompt = re.sub(
        r"实体绑定：[^\n]+",
        f"实体绑定：{visible_tokens} {scene_tokens[task['scene_id']]}。画面只出现{visible}；{hidden}位于镜头外，不出现身体、脸、倒影或复制人。每个可见角色只有一个身体。",
        prompt,
    )
    prompt = re.sub(r"单一动作状态源：[^\n]+", f"单一动作状态源：{spec['action']}", prompt)
    prompt = re.sub(r"表情表演：[^\n]+", f"表情表演：{spec['expression']}", prompt)
    prompt = re.sub(
        r"必须从本单元第0\.4秒后开始完整说出以上全部台词[^\n]+",
        f"必须在第0.2秒开始，最迟第{speech_end:.1f}秒完整说完，逐字只说一次：{text}。不得省略句首、不得替换或添加任何字；说话人始终可见清晰口型。",
        prompt,
    )
    prompt = re.sub(
        r"- 0\.000-[\d.]+秒：[^\n]+",
        f"- 0.000-{speech_end:.3f}秒：主体={entity_names[spec['speaker']]}；动作={spec['action']}；接触点=只保留明示接触；方向=沿原场景视线轴连续推进；终态=全文逐字说完且口型清晰；表情={spec['expression']}；观众读法=对白含义通过动作结果与听者反应被读懂。",
        prompt,
        count=1,
    )
    prompt = re.sub(
        r"- [\d.]+-[\d.]+秒：主体=同场角色；[^\n]+",
        f"- {speech_end:.3f}-{duration:.3f}秒：主体=可见角色；动作=最后一字结束后说话人闭口换气，动作停在前一拍终态；接触点=保持既有接触；方向=镜头轴不变；终态=信息落定；表情={spec['expression']}；观众读法=确认全文没有被截断。",
        prompt,
        count=1,
    )
    prompt = re.sub(
        r"镜头1【[^\n]+\n",
        f"镜头1【短促大远景建立方位后立即连续推至中景，再落到中近景·说话人口型与必要听者反应同框；0.000-{speech_end:.3f}秒】：动作={spec['action']}；终态=全文完整结束；表情={spec['expression']}。{{对白}}<现场音效：衣料、呼吸与道具接触只在真实动作同帧出现>\n",
        prompt,
        count=1,
    )
    prompt = re.sub(
        r"镜头2【[^\n]+\n",
        f"镜头2【近景短促收束·固定机位；{speech_end:.3f}-{duration:.3f}秒】：动作=最后一字后闭口换气；终态=信息落定；禁止再次说台词。{{无对白}}<现场音效：自然呼吸与环境底噪>\n",
        prompt,
        count=1,
    )
    prompt = prompt.replace("本单元是原视频漏句后的定向修复", "本单元是逐句ASR验收失败后的 changed-input 定向修复")
    if task["unit_id"] == "E35-CW-U19B":
        prompt += "\n单音节硬门：声音轨只允许一个汉字‘不’的一个音节；严禁说‘不好’、‘不行’或任何第二个音节。\n"
    out_path.write_text(prompt, encoding="utf-8")


def main() -> int:
    config = load(BASE_CONFIG)
    base_prompts = load(BASE_PROMPTS)
    prompt_rows = {row["unit_id"]: copy.deepcopy(row) for row in base_prompts["rows"]}
    tasks = []
    evidence_rows = []
    for unit_id, spec in SPECS.items():
        task = copy.deepcopy(next(row for row in config["tasks"] if row["unit_id"] == unit_id))
        task["duration_seconds"] = spec["duration"]
        task["edit_target_duration_seconds"] = spec["duration"]
        task["task_key"] = f"{unit_id}-PERFORMANCE-V1-DIALOGUE-EXACTNESS-REPAIR5"
        task["batch_id"] = "E35-V1-DIALOGUE-EXACTNESS-REPAIR5-20260724"
        task["visual_zone"] = f"{unit_id}-V1-DIALOGUE-EXACTNESS-REPAIR5"
        task["performance_spec"]["duration_seconds"] = spec["duration"]
        task["performance_spec"]["motion_beats"] = [{
            "start_seconds": 0.0,
            "end_seconds": spec["duration"],
            "subject": spec["speaker"],
            "action": spec["action"],
            "contact_point": "Only explicitly stated body, prop and surface contact is allowed.",
            "direction": "Preserve the locked eyeline, positions and prop ownership without jumps.",
            "end_state": "The exact line is complete, the speaker closes their mouth, and all props remain in the declared terminal state.",
            "intent": task["performance_spec"]["motion_beats"][0].get("intent"),
            "visible_causality": task["performance_spec"]["motion_beats"][0].get("visible_causality"),
            "expression": spec["expression"],
            "viewer_read": task["performance_spec"]["motion_beats"][0].get("viewer_read"),
        }]
        task["prompt_contract"]["source_action"] = spec["action"]
        relabel_images(task, spec["visual_entities"])
        out_prompt = PROMPT_DIR / f"{unit_id}-DIALOGUE-EXACTNESS-REPAIR5.txt"
        rewrite_prompt(task, spec, out_prompt)
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
            "prompt_path": rel(out_prompt),
            "prompt_sha256": task["prompt_sha256"],
            "status": "PASS_COMPLETE_CHANGED_INPUT_DIALOGUE_EXACTNESS_REPAIR5",
        })
        evidence_rows.append({"unit_id": unit_id, "reason": spec["reason"], "duration_seconds": spec["duration"]})

    prompt_manifest = copy.deepcopy(base_prompts)
    prompt_manifest["rows"] = [prompt_rows[row["unit_id"]] for row in base_prompts["rows"]]
    prompt_manifest["scope"] = "FAILED_ONLY_DIALOGUE_EXACTNESS_REPAIR5"
    prompt_manifest["unit_count"] = len(prompt_manifest["rows"])
    write(OUT_PROMPTS, prompt_manifest)

    dialogue = load(BASE_DIALOGUE)
    dialogue["rows"] = [row for row in dialogue["rows"] if row["video_unit_id"] in SPECS]
    dialogue["line_count"] = len(dialogue["rows"])
    dialogue["status"] = "PASS"
    dialogue["scope"] = "FAILED_ONLY_DIALOGUE_EXACTNESS_REPAIR5"
    write(OUT_DIALOGUE, dialogue)

    config["tasks"] = tasks
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPTS)
    config["dialogue_manifest_ref"] = rel(OUT_DIALOGUE)
    config["runtime_seconds"] = sum(spec["duration"] for spec in SPECS.values())
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["preserved_prompt_professionalism_evidence"] = [
        {"task_key": task["task_key"], "scene_id": task["scene_id"], "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]}
        for task in tasks
    ]
    write(OUT_CONFIG, config)
    write(EVIDENCE, {
        "schema": "qingshan.e35.dialogue_exactness_repair.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIR5_CHANGED_INPUT_READY",
        "source_asr_report": "qa/e35_v1_release_20260723/E35_DIALOGUE_REPAIR3_TARGETED_ASR_V1.json",
        "items": evidence_rows,
        "projected_additional_credits": 320,
        "projected_episode_video_credit_total": 5040,
        "rollback": "Use repair3 task outputs and targeted ASR report; replace only repair5 units after exact native-dialogue PASS.",
    })
    print(json.dumps({"status": "PASS", "tasks": [task["task_key"] for task in tasks], "runtime_seconds": config["runtime_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
