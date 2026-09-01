#!/usr/bin/env python3
"""Compile and fail-close every E46 H3 prompt before any paid media POST."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.minimax_h3_prompt_compiler import compile_h3_prompt, validate_h3_prompt
from tools.dialogue_cut_safety import minimum_dialogue_safe_integer_duration
from tools.wardrobe_identity_contract import SCHEMA as WARDROBE_SCHEMA, wardrobe_rows_for_cast
from tools.speaker_voice_contract import attach_speaker_voice_contract

PROD=ROOT/"workflow/claude_writer_agent/production/e46_v6_20260829"
QA=ROOT/"qa/e46_v6_preproduction_20260829"
EDITORIAL=PROD/"E46_V6_EDITORIAL_H3_MANIFEST_V1.json"
GROUPING=PROD/"E46_V6_VIDEO_UNIT_GROUPING_PLAN_V1.json"
ANCHORS=PROD/"E46_V6_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
OUT=PROD/"E46_V6_H3_PROMPT_PRECHECK_MANIFEST_V1.json"
PROMPTS=PROD/"video_prompts_h3_dialogue_isolated_v2"
WARDROBE_BIBLE=PROD/"E46_V6_WARDROBE_IDENTITY_BIBLE_V1.json"

def sha(path: Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path:Path,value:Any)->None:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main()->int:
    editorial=json.loads(EDITORIAL.read_text(encoding="utf-8"));grouping=json.loads(GROUPING.read_text(encoding="utf-8"));anchors=json.loads(ANCHORS.read_text(encoding="utf-8"))
    wardrobe_bible=json.loads(WARDROBE_BIBLE.read_text(encoding="utf-8")) if WARDROBE_BIBLE.is_file() else None
    shots={x["shot_id"]:x for x in editorial["shots"]};anchor_by={x["unit_id"]:x for x in anchors["units"]};PROMPTS.mkdir(parents=True,exist_ok=True)
    results=[];compiled=[]
    for unit in grouping["units"]:
        ordered=[shots[x]["prompt_spec"] for x in unit["editorial_shot_ids"]]
        wardrobe=[];seen=set();animals=set()
        for sid in unit["editorial_shot_ids"]:
            contract=shots[sid].get("wardrobe_contract") or {};animals.update(contract.get("animal_characters") or [])
            for row in contract.get("characters") or []:
                if row["character"] not in seen:seen.add(row["character"]);wardrobe.append(row)
        anchor=anchor_by[unit["unit_id"]];roles=anchor["anchor_count_decision"]["anchor_roles"]
        payload={**unit,"episode":editorial.get("episode") or grouping.get("episode"),"model":"MiniMax-H3","resolution":"768p","aspect_ratio":"9:16","ordered_prompt_specs":ordered,
                 "reference_images":[{"path":f"PLANNED_KEYFRAME:{sid}","role":role} for sid,role in zip(anchor["reference_image_task_keys"],roles)],
                 "wardrobe_contract":{"schema":WARDROBE_SCHEMA,"animal_characters":sorted(animals),"characters":wardrobe}}
        if wardrobe_bible is not None:
            payload["wardrobe_contract"]=wardrobe_rows_for_cast(payload,wardrobe_bible)
        provider_duration=max(
            math.ceil(float(unit["duration_seconds"])),
            minimum_dialogue_safe_integer_duration(payload, minimum=4, maximum=15),
        )
        payload["authored_duration_seconds"]=unit["duration_seconds"]
        payload["duration_seconds"]=provider_duration
        attach_speaker_voice_contract(payload)
        prompt=compile_h3_prompt(payload);report=validate_h3_prompt(prompt,source_id=unit["unit_id"],unit=payload)
        prompt_path=PROMPTS/f"{unit['unit_id']}.txt";prompt_path.write_text(prompt,encoding="utf-8")
        meta_markers=[x for x in ("说这句时","保持为本镜头结果","本节拍") if x in prompt]
        row={"unit_id":unit["unit_id"],"status":report["status"],"prompt_file":str(prompt_path.relative_to(ROOT)),"prompt_sha256":sha(prompt_path),
             "dialogue_tag_count":report["dialogue_tag_count"],"reference_count":len(payload["reference_images"]),"forbidden_speakable_meta_hits":meta_markers,
             "authored_duration_seconds":unit["duration_seconds"],"provider_duration_seconds":provider_duration,
             "h3_native_audio_dialogue_whitelist_required_post_generation":True,"failures":report["failures"]}
        results.append(row);compiled.append({"unit":payload,"prompt_file":row["prompt_file"],"prompt_sha256":row["prompt_sha256"]})
    failures=[f"{x['unit_id']}:{y}" for x in results for y in x["failures"]]+[f"{x['unit_id']}:META:{y}" for x in results for y in x["forbidden_speakable_meta_hits"]]
    manifest={"schema":"qingshan.e46.h3_prompt_precheck.v1_dialogue_isolation","episode":"E46","status":"PASS" if not failures else "FAIL",
              "policy":"qingshan.minimax_h3_prompt.v2_dialogue_isolation","unit_count":len(results),"pass_count":sum(x["status"]=="PASS" and not x["forbidden_speakable_meta_hits"] for x in results),
              "authored_runtime_seconds":grouping["runtime_seconds"],"provider_planned_runtime_seconds":sum(x["provider_duration_seconds"] for x in results),
              "paid_post_allowed":False,"post_generation_required_gate":"qingshan.h3_native_audio_dialogue_whitelist.v1","results":results,"compiled_units":compiled,"failures":failures}
    write(OUT,manifest);write(QA/"E46_V6_H3_PROMPT_PREPAID_QA_V1.json",{k:v for k,v in manifest.items() if k!="compiled_units"})
    print(json.dumps({"status":manifest["status"],"units":len(results),"failures":len(failures),"manifest":str(OUT.relative_to(ROOT))},ensure_ascii=False));return 0 if not failures else 2

if __name__=="__main__":raise SystemExit(main())
