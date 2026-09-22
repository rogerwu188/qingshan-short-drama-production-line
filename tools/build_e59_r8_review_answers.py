#!/usr/bin/env python3
"""Build exact-media E59 R8 keyframe answers after original-pixel review."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/nalu_runtime_e59/runtime/reviews/E59")
REQUEST = ROOT / "E59-keyframe-r8-full_request.json"
PREVIOUS = ROOT / "E59-keyframe-r7-full_answers.json"
OUTPUT = ROOT / "E59-keyframe-r8-full_answers.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    answers = deepcopy(json.loads(PREVIOUS.read_text(encoding="utf-8")))
    request_items = {row["item_id"]: row for row in request["items"]}
    answers["request_path"] = str(REQUEST)
    answers["request_sha256"] = digest(REQUEST)
    answers["reviewed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in answers["items"]:
        requested = request_items[row["item_id"]]
        row["media_reviewed"] = [media["path"] for media in requested["media"]]
        if row["item_id"] == "E59-S10-01":
            row["answers"] = {key: "PASS" for key in request["questionnaire"]}
            row["observed"] = {
                "observed_visible_characters": ["世子", "白鲤郡主", "陈迹"],
                "observed_visible_props": [],
                "observed_space_anchors": ["LOC-XIULOU-ERLOU-YAZUO", "SUBSPACE-E59-S10-01"],
                "observed_text_strings": [],
            }
            row["observation"] = (
                "已打开 R8 原图逐像素核验：画左绛紫宋袍世子做转身起势，白鲤郡主居中，陈迹画右；"
                "三人面部清楚可测，站位、服装、动作起点、空间与东方冷灰暖烛色调均符合合同，未见文字或现代物。"
            )
            row["defects"] = []
        elif row["item_id"] == "E59-S10-04":
            row["answers"] = {key: "PASS" for key in request["questionnaire"]}
            row["observed"] = {
                "observed_visible_characters": ["梁狗儿", "梁猫儿", "世子", "陈迹", "白鲤郡主"],
                "observed_visible_props": ["大碗"],
                "observed_space_anchors": ["LOC-XIULOU-ERLOU-YAZUO", "SUBSPACE-E59-S10-04"],
                "observed_text_strings": [],
            }
            row["observation"] = (
                "已打开 R8 原图逐像素核验：前景左粗壮成年男性梁狗儿举大碗，前景右精瘦成年男性梁猫儿，"
                "世子中央，陈迹背景左、白鲤郡主背景右；四男一女身份性别、屏幕槽位与服装均恢复，"
                "满桌空碗和悬碗入场态清楚，未见文字、克隆、截断或现代物。"
            )
            row["defects"] = []
    OUTPUT.write_text(json.dumps(answers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", "output": str(OUTPUT), "request_sha256": answers["request_sha256"]}))


if __name__ == "__main__":
    main()
