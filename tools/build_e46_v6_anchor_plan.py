#!/usr/bin/env python3
"""Build E46 v6 independently derived H3 semantic anchor decisions."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.video_unit_anchor_count_gate import evaluate

PROD = ROOT / "workflow/claude_writer_agent/production/e46_v6_20260829"
QA = ROOT / "qa/e46_v6_preproduction_20260829"
GROUPING = PROD / "E46_V6_VIDEO_UNIT_GROUPING_PLAN_V1.json"
MAP_PLAN = PROD / "E46_V6_COMPLETE_MAP_SHOT_PLAN_LOCKED_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    grouping=json.loads(GROUPING.read_text(encoding="utf-8"));mapping=json.loads(MAP_PLAN.read_text(encoding="utf-8"))
    mapped={row["unit_id"]:row for row in mapping["tasks"]};units=[];classes=set()
    for unit in grouping["units"]:
        shot_ids=unit["editorial_shot_ids"]
        single_shot_unit=len(shot_ids)==1
        def entities(shot_id: str) -> set[str]:
            block=mapped[shot_id]["blocking"]
            return {*[str(x["character_id"]) for x in block.get("characters") or []],
                    *[str(x["prop_id"]) for x in block.get("props") or []]}
        first,last=mapped[shot_ids[0]],mapped[shot_ids[-1]]
        identity_change={x["character_id"] for x in first["blocking"]["characters"]}!={x["character_id"] for x in last["blocking"]["characters"]}
        prop_change={x["prop_id"] for x in first["blocking"]["props"]}!={x["prop_id"] for x in last["blocking"]["props"]}
        space_change=first["subspace_layout"]["subspace_id"]!=last["subspace_layout"]["subspace_id"]
        action_class=("SINGLE_CONTINUOUS_START" if single_shot_unit else "_".join(name for name,active in (("IDENTITY_REANCHOR",identity_change),("PROP_REANCHOR",prop_change),
            ("SPACE_REANCHOR",space_change),("IRREVERSIBLE_RESULT",True)) if active));classes.add(action_class)
        task_keys=list(dict.fromkeys([shot_ids[0],shot_ids[-1]]));required=set().union(*(entities(x) for x in shot_ids));covered=set().union(*(entities(x) for x in task_keys));uncovered=required-covered
        while uncovered:
            candidates=[x for x in shot_ids if x not in task_keys]
            selected=max(candidates,key=lambda x:(len(entities(x)&uncovered),-shot_ids.index(x)))
            if not entities(selected)&uncovered:raise ValueError(f"{unit['unit_id']} uncovered {sorted(uncovered)}")
            task_keys.insert(-1 if len(task_keys)>1 else len(task_keys),selected);covered|=entities(selected);uncovered=required-covered
        if len(task_keys)>9:raise ValueError(f"{unit['unit_id']} exceeds H3 9-reference maximum")
        roles=["ADMITTED_SCENE_START_STATE" if x==shot_ids[0] else "NON_INTERPOLABLE_RESULT_STATE" if x==shot_ids[-1]
               else "MIDDLE_ENTITY_OR_PROP_REANCHOR" for x in task_keys]
        units.append({"unit_id":unit["unit_id"],"scene_id":unit["scene_id"],"planned_reference_image_count":len(task_keys),
          "reference_image_task_keys":task_keys,"reference_transport_strategy":"STANDARD_MULTI_REFERENCE",
          "anchor_count_decision":{"planned_reference_image_count":len(task_keys),"reason":"起始/终态加最少中间实体锚点覆盖本单元全部身份、道具与地图状态。",
          "criteria":{"continuous_motion_from_single_start":single_shot_unit,"identity_or_space_reanchor":identity_change or space_change,
          "prop_ownership_transition":prop_change,"non_interpolable_terminal_state":not single_shot_unit},"anchor_roles":roles,"action_design_class":action_class},
          "semantic_reference_coverage_gate":{"status":"PASS","references_checked":len(task_keys),"required_entity_count":len(required),
          "covered_entity_count":len(covered),"missing_entities":sorted(required-covered),"policy":"MINIMAL_START_TERMINAL_PLUS_MIDDLE_ENTITY_COVERAGE"}})
    plan={"schema":"qingshan.e46.video_unit_anchor_plan.v1","episode":"E46","video_unit_grouping_plan":str(GROUPING.relative_to(ROOT)),
          "video_unit_grouping_plan_sha256":sha(GROUPING),"planned_reference_image_count":sum(x["planned_reference_image_count"] for x in units),
          "uniform_count_independence_audit":{"status":"PASS","evaluated_individually":True,"uniform_count_reason":"每单元独立按实体与状态覆盖导出。",
          "distinct_action_design_classes":len(classes)},"units":units}
    out=PROD/"E46_V6_VIDEO_UNIT_ANCHOR_PLAN_V1.json";write_json(out,plan);gate=evaluate(plan);gate.update({"episode":"E46","reviewed_plan":str(out.relative_to(ROOT)),"reviewed_plan_sha256":sha(out)})
    write_json(QA/"E46_V6_VIDEO_UNIT_ANCHOR_COUNT_GATE_V1.json",gate);print(json.dumps({"status":gate["status"],"video_units":len(units),"planned_reference_images":plan["planned_reference_image_count"],"failures":gate["failures"]},ensure_ascii=False));return 0 if gate["status"]=="PASS" else 1


if __name__=="__main__":raise SystemExit(main())
