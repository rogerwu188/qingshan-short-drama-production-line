#!/usr/bin/env python3
"""Build repair instructions only from exact-SHA-bound review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from apply_image_tier_score_gate import bind_review_reports
except ModuleNotFoundError:  # Imported as tools.build_bound_image_repair_feedback in tests.
    from tools.apply_image_tier_score_gate import bind_review_reports


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def repair_instructions(shot: dict[str, Any], scene: dict[str, Any], failures: list[str], below_score: bool) -> list[str]:
    characters = ", ".join(shot.get("visible_characters") or shot.get("characters") or []) or "no foreground character"
    templates = {
        "story_action_clarity": f"只呈现原动作中的单一决定性瞬间：{shot['action']}",
        "scene_authority": f"场景必须严格保持地点={scene['location']}、时段={scene['time_of_day']}、天气={scene['weather']}",
        "canonical_identity_continuity": f"画面可见身份只允许：{characters}；保持其既定年龄、性别、面貌与服装",
        "no_text_or_pseudotext": "不得出现可读文字、伪文字、字符状纹理、字幕、标牌、水印或 Logo",
        "no_extra_or_duplicated_bodies": f"只允许这些可见身份且各出现一次：{characters}；不得新增人物、分身或重复身体",
        "native_anatomy": "保持自然人体结构，不得出现融合肢体、额外手指或错误关节",
    }
    instructions = [templates[name] for name in failures if name in templates]
    if below_score and not instructions:
        instructions.append(f"不改变任何剧情事实，仅改善构图和清晰度；原动作仍为：{shot['action']}")
    return instructions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-request", required=True)
    parser.add_argument("--review-result", required=True)
    parser.add_argument("--score-gate", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scene-state", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    request_path = resolve(args.review_request)
    result_path = resolve(args.review_result)
    gate_path = resolve(args.score_gate)
    manifest_path = resolve(args.manifest)
    scene_path = resolve(args.scene_state)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenes = json.loads(scene_path.read_text(encoding="utf-8"))

    bound = bind_review_reports(result.get("items") or [], request.get("items") or [])
    request_by_sha = {expected["metadata"]["candidate_sha256"]: expected for expected, _ in bound}
    report_by_sha = {
        report["capabilities"]["image_analysis"]["candidate_sha256"]: report
        for _, report in bound
    }
    shots = {shot["shot_id"]: shot for shot in manifest["shots"]}
    scene_by_id = {scene["scene_id"]: scene for scene in scenes["scene_state"]}
    output: dict[str, Any] = {}
    for row in gate.get("items") or []:
        if row.get("decision") != "FAIL":
            continue
        shot_id = row["shot_id"]
        source_shot_id = row.get("source_shot_id") or shot_id
        candidate_sha = row["candidate_sha256"]
        expected = request_by_sha.get(candidate_sha)
        report = report_by_sha.get(candidate_sha)
        if expected is None or report is None or expected.get("clip_id") != shot_id:
            raise ValueError(f"exact candidate SHA/shot binding failed for {shot_id}")
        shot = shots[source_shot_id]
        scene = scene_by_id[shot["scene_id"]]
        failures = list(row.get("hard_fact_failures") or [])
        instructions = repair_instructions(
            shot,
            scene,
            failures,
            float(row["score_100"]) < float(row["minimum_score_100"]),
        )
        output[shot_id] = {
            "schema": "qingshan.bound_image_repair_feedback.v2",
            "shot_id": shot_id,
            "source_shot_id": source_shot_id,
            "source_script_sha256": manifest["source"]["script_sha256"],
            "source_action_sha256": text_sha(shot["action"]),
            "candidate_sha256": candidate_sha,
            "review_request_sha256": file_sha(request_path),
            "review_result_sha256": file_sha(result_path),
            "score_gate_sha256": file_sha(gate_path),
            "binding_method": "EXACT_CANDIDATE_SHA_AND_SHOT_ID",
            "failed_checks": failures,
            "visible_characters": shot.get("visible_characters") or shot.get("characters") or [],
            "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS" if "visible_characters" in shot else "LEGACY_CHARACTERS_FIELD",
            "instructions": instructions,
            "instructions_sha256": text_sha("\n".join(instructions)),
        }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "failed_only_count": len(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
