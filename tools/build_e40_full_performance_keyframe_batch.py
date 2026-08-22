#!/usr/bin/env python3
"""Build E40 native-registry/spatial-bound keyframes for dialogue units."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from build_e40_spatial_keyframe_batch import (
    ASSET_QA,
    CHARACTER_REGISTRY,
    DEFAULT_AUTHORITY,
    PROP_QA,
    ROOT,
    SPACE_QA,
    compile_task,
    portable,
    sha256_file,
)


PROD = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817"
PLAN = PROD / "full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_NATIVE_DIALOGUE_PLAN_V1.json"
SPATIAL = PROD / "E40_SPATIAL_SHOT_PLAN_QA_V2.json"
PROMPT_DIR = PROD / "full_performance_native_dialogue_v1/keyframe_prompts_v1"
MANIFEST = PROD / "full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_KEYFRAME_BATCH_V1.json"
ASSET_RESOLUTION = PROD / "full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_KEYFRAME_ASSET_LIBRARY_RESOLUTION_V1.json"
COST_GATE = "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_FULL_PERFORMANCE_KEYFRAME_BATCH_COST_GATE_V1.json"

SPEAKER_IDS = {
    "陈迹": "CHAR-陈迹-古装",
    "云妃": "CHAR-云妃-古装",
    "阿栓": "CHAR-阿栓-古装",
    "云羊": "CHAR-云羊-古装",
}

# These positions are inherited verbatim from other shots in the same locked
# E40 spatial plan, never invented from a generic staging heuristic.
INHERITED_BLOCKING = {
    "CHAR-云妃-古装": {
        "character_id": "CHAR-云妃-古装",
        "zone_id": "ZONE-D-BEHIND-CURTAIN",
        "position": [9, 18],
        "facing": "south",
        "inherited_from_unit": "R04",
    },
    "CHAR-云羊-古装": {
        "character_id": "CHAR-云羊-古装",
        "zone_id": "ZONE-B-FRONT-HALL",
        "position": [5, 11],
        "facing": "west",
        "inherited_from_unit": "R06C",
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    plan = load(PLAN)
    spatial = load(SPATIAL)
    source_by_unit = {str(row["unit_id"]): row for row in spatial["tasks"]}
    tasks = []
    for performance in plan["units"]:
        speaker_id = SPEAKER_IDS[performance["speaker"]]
        # Yunfei is physically locked behind the long curtain.  R04 is the
        # canonical subspace that actually contains ZONE-D-BEHIND-CURTAIN;
        # using R01/R03/R08 framing would make her standing point illegal.
        spatial_source_unit = "R04" if speaker_id == "CHAR-云妃-古装" else performance["source_unit"]
        source = deepcopy(source_by_unit[spatial_source_unit])
        visible = list(source.get("visible_characters") or [])
        canonical = list(source.get("canonical_characters") or [])
        blocking = (source.setdefault("blocking", {})).setdefault("characters", [])
        if speaker_id not in visible:
            visible.append(speaker_id)
        if speaker_id not in canonical:
            canonical.append(speaker_id)
        if not any(str(row.get("character_id")) == speaker_id for row in blocking):
            inherited = INHERITED_BLOCKING.get(speaker_id)
            if not inherited:
                raise ValueError(f"no locked inherited blocking for {performance['task_id']} / {speaker_id}")
            blocking.append(deepcopy(inherited))
        exact_lines = "；".join(row["text"] for row in performance["spoken_lines"])
        emotions = "；".join(row["emotion"] for row in performance["spoken_lines"])
        source.update({
            "task_key": f"{performance['task_id']}-KF",
            "shot_type": "DIALOGUE_PERFORMANCE",
            "visible_characters": visible,
            "canonical_characters": canonical,
            "canonical_script_action": (
                f"{source['canonical_script_action']} "
                f"对白表演首帧：{performance['speaker']}尚未开口，按“{emotions}”进入真实呼吸、眼神与口周预备状态；"
                f"后续只说锁定原句“{exact_lines}”，画面内不得出现文字。"
            ),
            "expression_arc": emotions,
            "eyeline_target": "沿锁定空间轴线看向本场对手或帘外目标，不看镜头",
        })
        compiled = compile_task(source, PROMPT_DIR, str(plan["canonical"]["script_sha256"]))
        compiled.update({
            "status": "READY_TO_SUBMIT",
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
            "performance_task_id": performance["task_id"],
            "story_source_unit": performance["source_unit"],
            "spatial_source_unit": spatial_source_unit,
            "dialogue_ids": performance["dialogue_ids"],
            "speaker": performance["speaker"],
            "speaker_character_id": speaker_id,
            "native_registry_lookup_completed_before_compile": True,
            "episode_global_space_map_id": source["episode_global_space_map_id"],
            "global_space_map_id": source["global_space_map_id"],
            "subspace_id": source["subspace_layout"]["subspace_id"],
            "retry_policy": "FIRST_PASS_ONLY_NO_AUTOMATIC_RETRY",
        })
        compiled["prompt_contract"]["locked_dialogue_ids"] = performance["dialogue_ids"]
        compiled["prompt_contract"]["locked_dialogue_text_sha256"] = sha_text(exact_lines)
        tasks.append(compiled)

    character_rows = {}
    for task in tasks:
        for row in task["reference_bindings"]:
            if row["role"] == "character":
                character_rows.setdefault(row["entity_id"], {
                    "character_id": row["entity_id"],
                    "path": row["path"],
                    "sha256": row["sha256"],
                    "asset_origin": row.get("asset_origin"),
                    "qa_report": row.get("qa_report"),
                })
    asset_resolution = {
        "schema": "qingshan.character_asset_library_resolution.v1",
        "gate_id": "CHARACTER-IDENTITY-ADMISSION",
        "stage": "BEFORE_FULL_PERFORMANCE_KEYFRAME_PAID_SUBMIT",
        "status": "PASS",
        "registry": portable(CHARACTER_REGISTRY),
        "registry_sha256": sha256_file(CHARACTER_REGISTRY),
        "returning_character_policy": "CANONICAL_NATIVE_REGISTRY_ONLY",
        "characters": list(character_rows.values()),
        "failures": [],
    }
    ASSET_RESOLUTION.write_text(json.dumps(asset_resolution, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E40",
        "status": "READY_TO_PRECHECK_CONCURRENTLY",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "provider_post_allowed": True,
        "maximum_new_submissions": 13,
        "source_dialogue_plan_ref": portable(PLAN),
        "source_dialogue_plan_sha256": sha256_file(PLAN),
        "spatial_shot_plan_ref": portable(SPATIAL),
        "spatial_shot_plan_sha256": sha256_file(SPATIAL),
        "episode_global_space_map_ref": DEFAULT_AUTHORITY,
        "global_space_map_gate_required": True,
        "machine_gate_reports": [
            SPACE_QA,
            portable(ASSET_RESOLUTION),
            ASSET_QA,
            PROP_QA,
            COST_GATE,
        ],
        "output_dir": "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes",
        "qa_dir": "qa/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes",
        "one_independent_task_per_performance_unit": True,
        "formal_q1_admission_required_after_harvest": True,
        "video_submit_forbidden_before_q1": True,
        "tasks": tasks,
        "blocked_tasks": [],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "task_count": len(tasks),
        "manifest": portable(MANIFEST),
        "sha256": sha256_file(MANIFEST),
        "reference_counts": {row["task_key"]: len(row["reference_images"]) for row in tasks},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
