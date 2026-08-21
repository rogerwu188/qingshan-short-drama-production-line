#!/usr/bin/env python3
"""Block generic generation prompts before they can consume remote credits."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

try:
    from .human_realism_prompt_contract import CONTRACT_VERSION, validate_human_realism_prompt
except ImportError:
    from human_realism_prompt_contract import CONTRACT_VERSION, validate_human_realism_prompt


ROOT = Path(__file__).resolve().parents[1]
GATE_VERSION = "1.4.1"
GENERIC_VIDEO_PATTERNS = (
    r"animate\s+the\s+supplied\s+still",
    r"one\s+continuous\s+\d+(?:\.\d+)?[- ]second\s+shot",
)
ACTION_WORDS = re.compile(r"打|击|劈|刺|踢|撞|砸|抓|夺|追|跃|爆|碎|斩|冻结|穿墙|fight|strike|kick|slash", re.I)
PHYSICAL_VERBS = re.compile(
    r"拍|落|压|翻|停|挥|劈|错步|夹|爬|裂|弹|贴|分离|追|收刀|叠|系|潜|托|抵|击|松|接|穿|跃|冻结|合拢|切黑|"
    r"移|转|抬|放|掠|指|看|持|按|抽|迎|展|收|回|亮|灭|滑|伸|开|slam|press|turn|step|strike|move",
    re.I,
)
SHOT_SCALE_PATTERNS = {
    "wide": re.compile(r"大远景|超广角|航拍|远景定场|wide\s+establishing|extreme\s+wide|aerial\s+(?:establishing|shot)", re.I),
    "medium": re.compile(r"(?<!close[- ])\bmedium\b|中景", re.I),
    "close": re.compile(r"medium\s+close-up|close[- ]up|近景|特写", re.I),
}
GLYPH_REVEAL_PATTERNS = (
    re.compile(r"逐行.{0,4}(?:浮起|显现|出现|露出)", re.I),
    re.compile(r"(?:压痕|凹痕|纸面|卷宗|铭文|题字).{0,10}(?:成字|显字|浮字|露字|出现字|浮现文字)", re.I),
    re.compile(r"(?:字迹|字形|名字|真名|题字|铭文).{0,8}(?:显现|浮现|露出|出现|成形)", re.I),
    re.compile(r"(?:显现|浮现|露出|出现).{0,8}(?:字迹|字形|名字|真名|题字|铭文)", re.I),
)


def prompt_text(task: dict) -> str:
    if task.get("prompt_file"):
        path = Path(task["prompt_file"])
        if not path.is_absolute():
            path = ROOT / path
        return path.read_text(encoding="utf-8")
    return str(task.get("prompt") or "")


def _fail(code: str, detail: str) -> dict:
    return {"check": code, "detail": detail}


def visual_directive_text(text: str) -> str:
    """Exclude speech-only instructions while retaining every visual directive."""
    visual = text
    if "【对白与声音资产】" in visual:
        before, remainder = visual.split("【对白与声音资产】", 1)
        after = remainder.split("【现场声】", 1)[1] if "【现场声】" in remainder else ""
        visual = before + "\n【现场声】" + after
    # Current Seedance prompts bind exact speech inline. Speech must not be
    # mistaken for an instruction to draw glyphs, while unquoted visual prose
    # remains fully visible to the gate.
    visual = re.sub(r"‘[^’]*’", "‘[spoken dialogue redacted]’", visual, flags=re.S)
    visual = re.sub(r"\{[^{}]*\}", "{dialogue slot redacted}", visual, flags=re.S)
    visual = "\n".join(line for line in visual.splitlines() if "@音频" not in line)
    return visual


def detect_glyph_reveal_failures(text: str) -> list[dict]:
    """Block prompts that direct the video model to render emerging glyph shapes."""
    visual = visual_directive_text(text)
    failures = []
    for pattern in GLYPH_REVEAL_PATTERNS:
        match = pattern.search(visual)
        if match:
            failures.append(_fail(
                "glyph_reveal_visual_directive",
                f"BLOCKED_GLYPH_REVEAL visual directive: {match.group(0)}",
            ))
    return failures


def validate_image_prompt(text: str) -> list[dict]:
    failures: list[dict] = []
    requirements = {
        "entity_binding": r"\[\[[^\]]+\]\]",
        "scene_authority": r"剧本硬锁|scene\s*(?:authority|lock)",
        "identity_or_prop_lock": r"人物身份锁|角色锁|道具锁|identity\s*lock|prop\s*lock",
        "single_decisive_moment": r"(?:单一|一个).{0,12}决定性(?:瞬间|时刻)|决定性瞬间|single\s+decisive\s+moment",
        "framing_and_composition": r"画面设计|构图|景别|framing|composition",
        "palette_and_light": r"palette|光影|动机光|色彩|motivated\s+light",
        "negative_constraints": r"NEGATIVE_PROMPT|负面约束",
    }
    for code, pattern in requirements.items():
        if not re.search(pattern, text, re.I):
            failures.append(_fail(code, f"missing image prompt contract: {pattern}"))
    if len(text.strip()) < 300:
        failures.append(_fail("professional_detail", "image prompt is too short to carry the locked visual contract"))
    return failures


def _video_shots(text: str) -> list[str]:
    starts = list(re.finditer(r"镜头\s*\d+", text))
    return [text[m.start() : (starts[i + 1].start() if i + 1 < len(starts) else len(text))] for i, m in enumerate(starts)]


def validate_video_prompt(text: str, *, require_establishing: bool = True) -> list[dict]:
    failures: list[dict] = []
    failures.extend(detect_glyph_reveal_failures(text))
    for pattern in GENERIC_VIDEO_PATTERNS:
        if re.search(pattern, text, re.I):
            failures.append(_fail("generic_single_still_animation", f"blocked phrase: {pattern}"))
    if not re.search(r"\[\[[^\]]+\]\]", text):
        failures.append(_fail("entity_binding", "missing [[char/scene/prop]] binding"))
    if "教习" in text and "[[char_instructor]]" not in text:
        failures.append(_fail("instructor_identity_binding", "prompt contains the instructor but lacks [[char_instructor]]"))
    if "黑影" in text and not re.search(r"\[\[char_(?:instructor|killer)\]\]", text):
        failures.append(_fail(
            "shadow_identity_binding",
            "prompt contains a black-shadow alias but binds neither [[char_instructor]] nor [[char_killer]]",
        ))
    shots = _video_shots(text)
    if not shots:
        failures.append(_fail("seedance_storyboard", "missing 镜头1~N storyboard list"))
    for index, shot in enumerate(shots, 1):
        if not re.search(r"【[^】]*(?:景|机位|运动|推|拉|摇|移|跟)[^】]*】", shot):
            failures.append(_fail("shot_camera_design", f"镜头{index} missing bracketed framing/camera/motion"))
        if len(PHYSICAL_VERBS.findall(shot)) < 2:
            failures.append(_fail("physical_action_beats", f"镜头{index} lacks multiple concrete physical beats"))
        if not re.search(r"\{[^{}]+\}", shot):
            failures.append(_fail("dialogue_slot", f"镜头{index} missing {{对白}} or {{无对白}}"))
        if ACTION_WORDS.search(shot) and not re.search(r"<[^<>]+>", shot):
            failures.append(_fail("action_sfx", f"镜头{index} action has no <音效>"))
    action_rows = []
    for index, shot in enumerate(shots, 1):
        match = re.search(r"再完成：(.*?)；动作结果", shot, re.S)
        if match:
            action_rows.append((index, re.sub(r"\s+", "", match.group(1))))
    seen_actions: dict[str, int] = {}
    for index, action in action_rows:
        if action in seen_actions:
            failures.append(_fail(
                "duplicate_internal_action",
                f"镜头{index} repeats the decisive action from 镜头{seen_actions[action]}",
            ))
        else:
            seen_actions[action] = index
    requirements = {
        "palette_and_light": r"palette|光影|色彩|动机光",
        "environmental_power": r"力量.{0,8}环境|环境介质|木屑|尘|碎片|火焰|水面|布幔|瓦片",
    }
    if require_establishing:
        requirements["establishing_scale"] = r"大远景|远景定场|establishing"
    for code, pattern in requirements.items():
        if not re.search(pattern, text, re.I):
            failures.append(_fail(code, f"missing video professionalism field: {pattern}"))
    return failures


def validate_task(task: dict) -> dict:
    tool_type = task.get("tool_type")
    if tool_type not in {"image_generation", "video_generation"}:
        return {"task_key": task.get("task_key"), "tool_type": tool_type, "status": "NOT_APPLICABLE", "failures": []}
    try:
        text = prompt_text(task)
    except OSError as exc:
        failures = [_fail("prompt_load", str(exc))]
    else:
        failures = (
            validate_image_prompt(text)
            if tool_type == "image_generation"
            else validate_video_prompt(text, require_establishing=task.get("inherits_establishing_coverage") is not True)
        )
        if task.get("prompt_realism_contract_version"):
            if task.get("prompt_realism_contract_version") != CONTRACT_VERSION:
                failures.append(_fail("human_realism_contract_version", "unsupported human-realism prompt contract version"))
            else:
                failures.extend(validate_human_realism_prompt(text))
    return {
        "task_key": task.get("task_key"),
        "tool_type": tool_type,
        "status": "PASS" if not failures else "BLOCK_SUBMIT",
        "failures": failures,
    }


def _shot_scales(text: str) -> set[str]:
    return {name for name, pattern in SHOT_SCALE_PATTERNS.items() if pattern.search(text)}


def _coverage_rows(config: dict) -> tuple[list[dict], list[dict]]:
    """Return current media rows plus exact-SHA preserved prompt evidence."""
    rows: list[dict] = []
    failures: list[dict] = []
    for task in config.get("tasks", []):
        if task.get("tool_type") not in {"image_generation", "video_generation"}:
            continue
        try:
            text = prompt_text(task)
        except OSError as exc:
            failures.append(_fail("shot_scale_prompt_load", f"{task.get('task_key')}: {exc}"))
            continue
        rows.append({
            "task_key": task.get("task_key"),
            "scene_id": task.get("scene_id") or "__EPISODE__",
            "scales": sorted(_shot_scales(text)),
            "source": "current_batch",
        })

    for evidence in config.get("preserved_prompt_professionalism_evidence", []):
        path_value = evidence.get("prompt_file")
        expected_sha = evidence.get("prompt_sha256")
        if not path_value or not expected_sha:
            failures.append(_fail("preserved_scale_evidence_binding", "preserved prompt path or SHA-256 missing"))
            continue
        path = Path(path_value)
        if not path.is_absolute():
            path = ROOT / path
        try:
            data = path.read_bytes()
        except OSError as exc:
            failures.append(_fail("preserved_scale_evidence_load", f"{path}: {exc}"))
            continue
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha:
            failures.append(_fail("preserved_scale_evidence_sha256", f"{path}: expected {expected_sha}, got {actual_sha}"))
            continue
        text = data.decode("utf-8")
        rows.append({
            "task_key": evidence.get("task_key"),
            "scene_id": evidence.get("scene_id") or "__EPISODE__",
            "scales": sorted(_shot_scales(text)),
            "source": "preserved_exact_sha_evidence",
        })
    return rows, failures


def validate_batch_shot_scale_coverage(config: dict) -> tuple[list[dict], list[dict]]:
    rows, failures = _coverage_rows(config)
    if config.get("targeted_unit_replacement") is True:
        return rows, failures
    if not rows:
        return rows, failures
    episode_scales = {scale for row in rows for scale in row["scales"]}
    if "wide" not in episode_scales:
        failures.append(_fail("episode_grand_establishing", "episode prompt set has no grand wide/aerial establishing shot"))
    missing_range = sorted({"wide", "medium", "close"} - episode_scales)
    if missing_range:
        failures.append(_fail("episode_shot_size_range", f"episode prompt set lacks shot-size range: {', '.join(missing_range)}"))

    scene_scales: dict[str, set[str]] = {}
    for row in rows:
        scene_scales.setdefault(row["scene_id"], set()).update(row["scales"])
    for scene_id, scales in sorted(scene_scales.items()):
        if scene_id != "__EPISODE__" and "wide" not in scales:
            failures.append(_fail("scene_grand_establishing", f"{scene_id} has no grand wide/aerial establishing shot"))
    return rows, failures


def evaluate_batch(config: dict) -> dict:
    results = [validate_task(task) for task in config.get("tasks", [])]
    blocked = [row for row in results if row["status"] == "BLOCK_SUBMIT"]
    coverage, batch_failures = validate_batch_shot_scale_coverage(config)
    media_task_keys = [
        task.get("task_key")
        for task in config.get("tasks", [])
        if task.get("tool_type") in {"image_generation", "video_generation"}
    ]
    blocked_tasks = [row.get("task_key") for row in blocked]
    if batch_failures:
        blocked_tasks.extend(key for key in media_task_keys if key not in blocked_tasks)
    return {
        "schema": "qingshan.shot_prompt_professionalism_gate.v1",
        "gate_version": GATE_VERSION,
        "episode": config.get("episode"),
        "status": "PASS" if not blocked and not batch_failures else "BLOCK_SUBMIT",
        "results": results,
        "batch_shot_scale_coverage": coverage,
        "batch_failures": batch_failures,
        "blocked_task_count": len(blocked_tasks),
        "blocked_tasks": blocked_tasks,
        "rollback": "Revise only blocked prompts; retain every prompt and candidate that already passed.",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = evaluate_batch(config)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "blocked_tasks": report["blocked_tasks"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
