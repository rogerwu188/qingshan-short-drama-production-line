#!/usr/bin/env python3
"""Build A03 V5 from the accepted image-edited pre-contact gap anchor."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v4/E37_A03_TWO_ANCHOR_CONTACT_RETRY_BATCH_V4.json"
BASE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v5"
OUT = BASE / "E37_A03_VISIBLE_GAP_TWO_ANCHOR_RETRY_BATCH_V5.json"
PRE = "working_assets/e37_action_replacement_v4_20260803/anchors/E37-R-A03-PRECONTACT-GAP-V6.png"
END = "working_assets/e37_action_replacement_v4_20260803/anchors/E37-R-A03-CONTACT-END-V4.png"
PROMPT = ROOT / "working_assets/e37_prompt_repair_20260803/compiled_prompts_v5/E37-R-A03.txt"


def sha(path: str | Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    return hashlib.sha256(target.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = copy.deepcopy(config["tasks"][0])
    old = (ROOT / task["prompt_path"]).read_text(encoding="utf-8")
    changed = (
        old.splitlines()[0]
        + "\n【V5可见空隙锚点】@图片1已通过图片直观看审：无脸白纸巨人双掌与下坠燃梁之间存在清楚空隙。"
        + "开场必须逐像素继承该空隙至少0.6秒；随后燃梁向下、白纸双掌向上，在中央首次接触；"
        + "接触后才允许肘部下沉、脚后滑并到达@图片2。严禁把@图片2用作起手，严禁把纸巨人变成人。\n"
        + "\n".join(old.splitlines()[1:])
        + "\n"
    )
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(changed, encoding="utf-8")
    task["reference_images"][0] = PRE
    task["reference_image_sequence"][0].update({"path": PRE, "sha256": sha(PRE), "role": "VISIBLE_GAP_PRE_CONTACT_TEMPORAL_ANCHOR"})
    task["reference_images"][1] = END
    task["task_key"] = "E37-R-A03-VISIBLE-GAP-TWO-ANCHOR-RETRY-V5"
    task["batch_id"] = "E37-A03-VISIBLE-GAP-TWO-ANCHOR-RETRY-V5-20260803"
    task["prompt_path"] = str(PROMPT.relative_to(ROOT))
    task["prompt_file"] = task["prompt_path"]
    task["prompt_sha256"] = sha(PROMPT)
    task["status"] = "READY_TO_SUBMIT"
    task["material_change"] = {
        "type": "NEW_IMAGE_EDITED_PRE_CONTACT_ANCHOR_WITH_30CM_VISIBLE_GAP",
        "source_failure": "qa/e37_action_replacement_v4_20260803/E37_A03_V4_DIRECT_WATCH_AND_OCR_ADJUDICATION.json",
        "pre_contact_anchor_sha256": sha(PRE),
        "contact_end_anchor_sha256": sha(END),
    }

    anchor_path = BASE / "E37_A03_VISIBLE_GAP_TWO_ANCHOR_PLAN_V5.json"
    old_anchor = json.loads((ROOT / config["anchor_count_plan_ref"]).read_text(encoding="utf-8"))
    old_anchor["units"][0]["reference_image_task_keys"] = ["E37-R-A03-VISIBLE-GAP-PRE-CONTACT-REF", "E37-R-A03-CONTACT-END-REF"]
    old_anchor["units"][0]["anchor_count_decision"]["reason"] = "V4 provider output began at contact; V5 uses an image-QA-passed anchor with a measured visible air gap."
    write(anchor_path, old_anchor)
    manifest_path = BASE / "E37_A03_COMPLETE_PROMPT_MANIFEST_V5.json"
    write(manifest_path, {
        "schema": "qingshan.complete_video_prompt_manifest.v1",
        "episode": "E37",
        "all_units_have_prompt": True,
        "unit_count": 1,
        "source_plan": str(anchor_path.relative_to(ROOT)),
        "source_plan_sha256": sha(anchor_path),
        "source_scene_authority": config["scene_contract_ref"],
        "source_scene_authority_sha256": sha(config["scene_contract_ref"]),
        "rows": [{"unit_id": "E37-R-A03", "scene_id": task["scene_id"], "weather": "RAIN_NIGHT", "prompt_path": task["prompt_path"], "prompt_sha256": task["prompt_sha256"]}],
    })
    config["status"] = "READY_FOR_A03_VISIBLE_GAP_FAILED_ONLY_RETRY"
    config["output_dir"] = "working_assets/e37_action_replacement_v5_20260803/outputs"
    config["qa_dir"] = "qa/e37_action_replacement_v5_20260803"
    config["retry_policy"] = "DIRECT_WATCH_FAILED_A03_ONLY_NEW_IMAGE_EDITED_GAP_ANCHOR"
    config["anchor_count_plan_ref"] = str(anchor_path.relative_to(ROOT))
    config["complete_video_prompt_manifest_ref"] = str(manifest_path.relative_to(ROOT))
    config["tasks"] = [task]
    write(OUT, config)
    print(json.dumps({"status": "BUILT", "config": str(OUT.relative_to(ROOT)), "pre_sha256": sha(PRE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
