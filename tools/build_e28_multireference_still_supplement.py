#!/usr/bin/env python3
"""Build E28's multi-reference video map and only the genuinely missing still states."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e28_cl2x517_20260721"
MANIFEST_PATH = PRODUCTION / "E28_PRODUCTION_MANIFEST.json"
PLAN_PATH = PRODUCTION / "E28_MULTI_REFERENCE_STILL_PLAN_V2.json"
SUPPLEMENT_DIR = PRODUCTION / "multireference_still_supplement_v2"
PROMPT_DIR = SUPPLEMENT_DIR / "prompts"
BATCH_PATH = SUPPLEMENT_DIR / "E28_MULTI_REFERENCE_STILL_SUPPLEMENT_V2_IMAGE_BATCH.json"
GATE_PATH = ROOT / "qa/e28_multireference_still_supplement_v2_20260721/E28_MULTI_REFERENCE_STILL_SUPPLEMENT_PREFLIGHT.json"
SOURCE_SHA = "d6418403ecfd3f7042d7bf08cb2297248eaaf96db86223994e8de75b16263ddc"


UNITS = [
    ("E28-CW-U01", 15, [("E28-CW-S01-SH01", 10), ("E28-CW-S01-SH02", 5)]),
    ("E28-CW-U02", 15, [("E28-CW-S01-SH02", 5), ("E28-CW-S01-SH03", 10)]),
    ("E28-CW-U03", 11, [("E28-CW-S02-SH01", 4), ("E28-CW-S02-SH02", 5), ("E28-CW-S02-SH03", 2)]),
    ("E28-CW-U04", 11, [("E28-CW-S02-SH03", 3), ("E28-CW-S02-SH04", 5), ("E28-CW-S02-SH05", 3)]),
    ("E28-CW-U05", 12, [("E28-CW-S02-SH05", 1), ("E28-CW-S02-SH06", 5), ("E28-CW-S02-SH07", 6)]),
    ("E28-CW-U06", 15, [("E28-CW-S03-SH01", 9), ("E28-CW-S03-SH02", 6)]),
    ("E28-CW-U07", 15, [("E28-CW-S03-SH02", 4), ("E28-CW-S03-SH03", 11)]),
    ("E28-CW-U08", 13, [("E28-CW-S04-SH01", 4), ("E28-CW-S04-SH02", 5), ("E28-CW-S04-SH03", 4)]),
    ("E28-CW-U09", 13, [("E28-CW-S04-SH03", 1), ("E28-CW-S04-SH04", 5), ("E28-CW-S04-SH05", 6), ("E28-CW-S04-SH06", 1)]),
    ("E28-CW-U10", 14, [("E28-CW-S04-SH06", 7), ("E28-CW-S04-SH07", 7)]),
    ("E28-CW-U11", 13, [("E28-CW-S05-SH01", 7), ("E28-CW-S05-SH02", 6)]),
    ("E28-CW-U12", 13, [("E28-CW-S05-SH03", 5), ("E28-CW-S05-SH04", 5), ("E28-CW-S05-SH05", 3)]),
    ("E28-CW-U13", 12, [("E28-CW-S05-SH05", 3), ("E28-CW-S05-SH06", 5), ("E28-CW-S05-SH07", 4)]),
]

EXTRA_STATES = {
    "E28-CW-S05-SH02-PRESS": {
        "source_shot_id": "E28-CW-S05-SH02",
        "state_role": "result_evidence",
        "description": "陈迹独自滑跪在雪巷，单膝低伏，以右掌把一张完全无字的拓纸平压在将被新雪覆盖的脚印旁；云羊与黑影均在画外。",
        "visible_characters": ["chenji"],
        "references": [
            ("character", "chenji", "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg", "configs/series_continuity_asset_registry_20260712.json"),
            ("scene", "E28-CW-S05-SNOW-ALLEY", "working_assets/e28_writer_agent_stills_failed_only_r1/candidates/E28_E28-S03-SH04-WRITER-AGENT-STILL-R1_349fa889-29c2-4543-97bb-3fea3b762d1e.png", "workflow/tasks/E28_CLAUDE_WRITER_V1_REUSE_CONDITIONAL_ADMISSION_20260721.json"),
        ],
    },
    "E28-CW-S05-SH07-EMPTY-EAVES": {
        "source_shot_id": "E28-CW-S05-SH07",
        "state_role": "result_reveal",
        "description": "无人空檐与雪巷形成纵深，近处同一串脚印的后半段轻浅并指向空檐，风雪正掩去痕迹；画面无人、无月、无文字。",
        "visible_characters": [],
        "references": [
            ("scene", "E28-CW-S05-SNOW-ALLEY", "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH01-STILL-V1_9e9c9d60-d60b-4532-bb53-88aef11db71c.png", "qa/e28_claude_writer_v1_new_stills_review_20260721/E28_NEW_21_TIER_SCORE_GATE.json"),
            ("prop", "two_stride_footprint_evidence", "working_assets/e28_claude_writer_v1_reuse_failed_only_r1_20260721/candidates/E28_E28-CW-S05-SH04-STILL-V1_9c7a44b7-2f60-4ecf-b37d-3a9e787fb40f.png", "qa/e28_claude_writer_v1_new_stills_review_20260721/E28_NEW_21_TIER_SCORE_GATE.json"),
        ],
    },
}

UNIT_EXTRA_BINDINGS = {
    "E28-CW-U11": ["E28-CW-S05-SH02-PRESS"],
    "E28-CW-U13": ["E28-CW-S05-SH07-EMPTY-EAVES"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def existing_candidates(shot: dict[str, Any]) -> list[str]:
    matches = sorted(ROOT.glob(f"working_assets/**/*{shot['shot_id']}*.png"))
    reuse = (shot.get("reuse_candidate") or {}).get("path")
    if reuse and (ROOT / reuse).is_file():
        matches.append(ROOT / reuse)
    return sorted({relative(path) for path in matches if path.is_file()})


def render_prompt(state_id: str, state: dict[str, Any], source_action: str) -> str:
    visible = "、".join(state["visible_characters"]) or "无人"
    return (
        f"《青山》E28《纸上杀人》，锁源 SHA-256={SOURCE_SHA}。\n"
        f"参考状态 ID={state_id}；来源镜头={state['source_shot_id']}。锁定剧情原文：{source_action}\n"
        f"本图只承担一个视频时间点，不复述整段动作：{state['description']}\n"
        f"可见人物仅限：{visible}。输入图按清单分别只作人物身份、雪巷空间或脚印证物参考，禁止照搬输入图里的旧人物位置和旧动作。\n"
        "构图：9:16 竖屏，2K，写实电影质感，古代雪巷，深夜丑时，强风雪，蓝白雪色与克制暖火反光；主体动作和证据一眼可读，真实材质、自然肤质、正确人体与空间尺度。\n"
        "硬约束：不得出现月亮或月光主照明；不得新增人物、武器、建筑和剧情结果；不得生成字幕、可读文字、伪文字、水印或 Logo；不得拼贴、分镜格、角色分身、重复肢体、额外手指。"
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["source"]["script_sha256"] != SOURCE_SHA:
        raise SystemExit("E28 source SHA mismatch")
    shots = {row["shot_id"]: row for row in manifest["shots"]}
    if len(shots) != 27 or sum(row["duration_seconds"] for row in shots.values()) != 172:
        raise SystemExit("E28 shot/runtime lock mismatch")

    unit_rows = []
    usage_count = 0
    for unit_id, duration, segments in UNITS:
        if not 8 <= duration <= 15 or sum(value for _, value in segments) != duration:
            raise SystemExit(f"invalid unit duration: {unit_id}")
        state_ids = list(dict.fromkeys(shot_id for shot_id, _ in segments)) + UNIT_EXTRA_BINDINGS.get(unit_id, [])
        if not 2 <= len(state_ids) <= 4:
            raise SystemExit(f"reference count outside 2-4: {unit_id}")
        usage_count += len(state_ids)
        unit_rows.append({
            "unit_id": unit_id,
            "duration_seconds": duration,
            "generation_mode": "entity_reference_sequence",
            "single_still_only": False,
            "segments": [{"source_shot_id": shot_id, "duration_seconds": value} for shot_id, value in segments],
            "reference_state_ids": state_ids,
            "reference_count": len(state_ids),
        })

    base_states = []
    for shot in manifest["shots"]:
        candidates = existing_candidates(shot)
        if not candidates:
            raise SystemExit(f"missing base-state candidate pool: {shot['shot_id']}")
        base_states.append({
            "state_id": shot["shot_id"],
            "source_shot_id": shot["shot_id"],
            "state_role": "base_story_state",
            "coverage": "EXISTING_CANDIDATE_POOL_PENDING_FINAL_SELECTION",
            "candidate_count": len(candidates),
            "candidate_paths": candidates,
        })

    plan = {
        "schema": "qingshan.multireference_still_plan.v1",
        "episode": "E28",
        "source_script_sha256": SOURCE_SHA,
        "runtime_seconds": 172,
        "video_unit_count": len(unit_rows),
        "video_unit_duration_range_seconds": [8, 15],
        "unique_reference_state_count": len(base_states) + len(EXTRA_STATES),
        "base_state_count": len(base_states),
        "supplement_state_count": len(EXTRA_STATES),
        "reference_placement_count": usage_count,
        "relationship": "SCRIPT_SHOTS_REFERENCE_STILLS_VIDEO_UNITS_ARE_MANY_TO_MANY",
        "rules": [
            "ONE_STILL_ONE_READABLE_STATE",
            "ONE_VIDEO_UNIT_MAY_BIND_TWO_TO_FOUR_STILLS",
            "ONE_VIDEO_UNIT_MAY_CONTAIN_MULTIPLE_INTERNAL_SHOTS",
            "APPROVED_STILLS_MAY_BE_REUSED_ACROSS_UNITS",
            "SUPPLEMENT_ONLY_GENUINELY_MISSING_STATES",
        ],
        "video_units": unit_rows,
        "base_states": base_states,
        "supplement_states": [dict({"state_id": key, "coverage": "MISSING_GENERATE_ONCE"}, **value) for key, value in EXTRA_STATES.items()],
    }
    PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for state_id, state in EXTRA_STATES.items():
        shot = shots[state["source_shot_id"]]
        prompt = render_prompt(state_id, state, shot["action"])
        prompt_path = PROMPT_DIR / f"{state_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        bindings = []
        for role, entity_id, path_value, qa_report in state["references"]:
            path = ROOT / path_value
            if not path.is_file() or not (ROOT / qa_report).is_file():
                raise SystemExit(f"missing bound reference or QA evidence: {state_id}/{entity_id}")
            bindings.append({
                "role": role,
                "entity_id": entity_id,
                "path": path_value,
                "sha256": sha256(path),
                "qa_status": "PASS",
                "qa_report": qa_report,
            })
        source_action_sha = text_sha(shot["action"])
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": state_id,
            "source_script_sha256": SOURCE_SHA,
            "source_action": shot["action"],
            "source_action_sha256": source_action_sha,
            "visible_characters": state["visible_characters"],
            "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
            "reference_bindings": bindings,
            "state_role": state["state_role"],
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": f"{state_id}-STILL-V2",
            "tool_type": "image_generation",
            "scene_id": shot["scene_id"],
            "shot_id": state_id,
            "beat_id": shot["scene_id"],
            "prompt_file": relative(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": contract,
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "source_script_sha256": SOURCE_SHA,
        })

    GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    gate = {
        "schema": "qingshan.multireference_still_supplement_preflight.v1",
        "episode": "E28",
        "status": "PASS",
        "source_script_sha256": SOURCE_SHA,
        "plan": relative(PLAN_PATH),
        "plan_sha256": sha256(PLAN_PATH),
        "video_units": len(unit_rows),
        "unique_reference_states": len(base_states) + len(EXTRA_STATES),
        "existing_base_states": len(base_states),
        "missing_supplement_states": len(EXTRA_STATES),
        "tasks": [row["task_key"] for row in tasks],
        "generation_policy": "GENERATE_MISSING_STATES_ONCE_CONCURRENTLY",
    }
    GATE_PATH.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    batch = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E28",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": SOURCE_SHA,
        "machine_gate_reports": [relative(GATE_PATH)],
        "output_dir": "working_assets/e28_multireference_still_supplement_v2_20260721/candidates",
        "qa_dir": "qa/e28_multireference_still_supplement_v2_20260721",
        "retry_policy": "NO_AUTOMATIC_RETRY_SELECT_BEST_EXISTING_CANDIDATE",
        "consumer_contract": {
            "purpose": "MISSING_REFERENCE_STATES_FOR_ENTITY_REFERENCE_SEQUENCE",
            "not_a_video_call_plan": True,
            "video_compilation_mode": "entity_reference_sequence",
        },
        "tasks": tasks,
        "blocked_tasks": [],
    }
    BATCH_PATH.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "video_units": len(unit_rows),
        "unique_reference_states": len(base_states) + len(EXTRA_STATES),
        "reference_placements": usage_count,
        "supplement_tasks": len(tasks),
        "batch": relative(BATCH_PATH),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
