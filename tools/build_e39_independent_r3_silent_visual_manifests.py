#!/usr/bin/env python3
"""Compile E39 failed-only R3 visuals with dialogue deferred to AgentCut."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
SOURCE_DIR = BASE / "independent_video_r2_audio_driven"
OUT_DIR = BASE / "independent_video_r3_silent_visual"
SOURCE = SOURCE_DIR / "E39_INDEPENDENT_FAILED_ONLY_R2_MANIFEST_V1.json"
OUT = OUT_DIR / "E39_INDEPENDENT_FAILED_ONLY_R3_SILENT_VISUAL_MANIFEST_V2.json"
PROBE_OUT = OUT_DIR / "E39_U12_R3_SILENT_VISUAL_PROBE_MANIFEST_V1.json"
MANUAL_ADJUDICATION = ROOT / "qa/e39_video_v1/independent_r2_audio_driven/E39_R2_ROGER_COST_AWARE_MANUAL_ADJUDICATION_V1.json"

TEXT_PLATES = {
    "U04": "working_assets/e39_video_v1/deterministic_text_plates/E39-U04-LEDGER-PLATE-V1.png",
    "U10": "working_assets/e39_video_v1/deterministic_text_plates/E39-U10-TWO-PAGE-PLATE-V1.png",
    "U11": "working_assets/e39_video_v1/deterministic_text_plates/E39-U11-DATE-SEAL-PLATE-V1.png",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def silent_prompt(source: str, unit: str) -> str:
    value = re.sub(
        r"^声音与画面分轨：.*?非说话者闭口并持续做有动机的呼吸、视线和手部反应。",
        "",
        source,
        count=1,
        flags=re.S,
    )
    value = "。".join(
        sentence for sentence in value.split("。") if "@音频" not in sentence
    ).strip("。") + "。"
    value = value.replace("用同一", "以同一")
    if unit == "U04":
        value = value.replace(
            "@图片1是唯一首帧、身份、服装、账页和长街空间基准",
            "Roger人工裁决要求室内药房内堂；旧@图片1为室外参考，禁止用于本轮场景运输",
        )
        value = value.replace("乌云从檐脊一次掠落", "乌云从室内高柜顶一次跃落")
        value = value.replace("两个街向的夜色", "室内两侧廊门")
    text_policy = {
        "U04": (
            "本轮模型画面中的账页保持完整空白纸纤维和预留线框，不生成标题、日期、汉字、数字或印记；"
            "准确账页由后期确定性栅格文字板单独插入，人物手指不得遮挡预留区域。"
        ),
        "U10": (
            "本轮模型画面中的甲乙两页只保留空白纸纤维和矩形版心，不生成任何文字、数字或印记；"
            "两页证据由后期确定性栅格板单独插入，手指动作不得遮挡版心。"
        ),
        "U11": (
            "本轮模型画面中的日期格与旧印区域只保留空白纸纤维、三格轮廓和圆形印位，不生成任何文字、数字或印纹；"
            "准确日期和花瓣旧印由后期确定性栅格板单独插入。"
        ),
    }.get(unit, "")
    header = (
        "纯视觉无声生成：本轮不生成对白、旁白、歌声、字幕或任何语音。"
        "所有人物全程闭口，情绪只由眼神、呼吸、姿态和手部反应表达；不得模拟说话口型。"
        "后期AgentCut将按原时间轴加入已验收逐句对白音频与唯一白字描边字幕。"
        "模型不得根据剧情语义自行写字、烧录字幕或生成对白文字。"
    )
    return header + text_policy + value


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    adjudication = json.loads(MANUAL_ADJUDICATION.read_text(encoding="utf-8"))
    preserved = {
        row["unit_id"].split("-")[1]: row
        for row in adjudication["adjudications"]
        if row["decision"] == "MANUAL_ACCEPT_WITH_LEARNING_NO_RETRY"
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for original in source["tasks"]:
        unit = original["task_key"].split("-")[1]
        if unit in preserved:
            continue
        prompt_path = OUT_DIR / f"E39-{unit}-R3-SILENT.txt"
        prompt_path.write_text(
            silent_prompt((ROOT / original["prompt_file"]).read_text(encoding="utf-8"), unit),
            encoding="utf-8",
        )
        task = dict(original)
        dialogue_lines = list(original.get("dialogue_lines") or [])
        audio_ids = list(original.get("exact_dialogue_audio_asset_ids") or [])
        task.update(
            {
                "task_key": f"E39-{unit}-R3-SILENT",
                "prompt_file": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha(prompt_path),
                "native_dialogue_required": False,
                "dialogue_lines": [],
                "reference_audio_asset_ids": [],
                "exact_dialogue_audio_asset_ids": [],
                "dialogue_transport": "POST_AGENTCUT_EXACT_AUDIO",
                "postproduction_dialogue_lines": dialogue_lines,
                "postproduction_exact_audio_asset_ids": audio_ids,
                "source_subtitle_policy": "FORBID_ALL_SOURCE_TEXT",
                "text_policy": {"exact_allowed": [], "pseudo_text_forbidden": True},
            }
        )
        if unit in TEXT_PLATES:
            plate = ROOT / TEXT_PLATES[unit]
            if not plate.exists():
                raise FileNotFoundError(f"Missing deterministic plate: {plate}")
            task["postproduction_text_plate"] = TEXT_PLATES[unit]
            task["postproduction_text_plate_sha256"] = sha(plate)
        if unit == "U04":
            task["scene_space_override"] = "INTERIOR_BY_ROGER_MANUAL_VISUAL_ADJUDICATION"
            task["paid_submit_blocked_by"] = "NEW_ADMITTED_INTERIOR_KEYFRAME_REQUIRED"
            task["forbidden_reference_sha256"] = list(task.get("reference_sha256") or [])
            task["reference_images"] = []
            task["reference_sha256"] = []
        tasks.append(task)
    result = {
        "schema": "qingshan.e39_independent_failed_only_video_r3_silent_visual.v2",
        "episode": "E39",
        "status": "READY_FOR_ZERO_COST_PREFLIGHT_PAID_SUBMIT_FROZEN",
        "source_script_sha256": source["source_script_sha256"],
        "canonical_manifest_sha256": source["canonical_manifest_sha256"],
        "source_r2_manifest": str(SOURCE.relative_to(ROOT)),
        "source_r2_manifest_sha256": sha(SOURCE),
        "machine_gate_reports": source["machine_gate_reports"],
        "paid_submit_gate": "BLOCKED_PENDING_ROGER_E39_REPAIR_BATCH",
        "manual_adjudication": str(MANUAL_ADJUDICATION.relative_to(ROOT)),
        "preserved_source_units": list(preserved.values()),
        "tasks": tasks,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    probe = dict(result)
    probe["schema"] = "qingshan.e39_u12_r3_silent_visual_probe.v1"
    probe["status"] = "READY_FOR_ZERO_COST_PREFLIGHT_PAID_SUBMIT_FROZEN"
    probe["cost_reservation"] = {
        "model": "seedance-2.0-pro",
        "duration_seconds": 6,
        "credits_per_second": 48,
        "worst_case_credits": 288,
    }
    probe["tasks"] = [task for task in tasks if task["task_key"] == "E39-U12-R3-SILENT"]
    if len(probe["tasks"]) != 1:
        raise ValueError("U12 probe task missing or duplicated")
    PROBE_OUT.write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "tasks": len(tasks), "manifest": str(OUT), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
