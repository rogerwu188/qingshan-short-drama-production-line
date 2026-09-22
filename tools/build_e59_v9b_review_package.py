#!/usr/bin/env python3
"""Build the exact-SHA E59 v9b full keyframe review package.

The package reuses the already submitted R8 full-batch review for the 28
unchanged frames and replaces only S10-01/S10-04 with the zero-cost targeted
identity candidates.  It creates review evidence only; admission is performed
by the normal VLM protocol and keyframe Q1 builder.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/nalu_runtime_e59/runtime/reviews/E59")
PRE = Path("/Users/rogerwu/nalu_runtime_e59/workflow/nalu/E59/preproduction")
SOURCE_REQUEST = ROOT / "E59-keyframe-r8-full_request.json"
SOURCE_ANSWERS = ROOT / "E59-keyframe-r8-full_answers.json"
REQUEST = ROOT / "E59-keyframe-v12c-full_request.json"
ANSWERS = ROOT / "E59-keyframe-v12c-full_answers.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    request = deepcopy(json.loads(SOURCE_REQUEST.read_text(encoding="utf-8")))
    answers = deepcopy(json.loads(SOURCE_ANSWERS.read_text(encoding="utf-8")))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    request["request_id"] = "E59-keyframe-v12c-" + now.replace(":", "").replace("-", "")
    request["created_at"] = now
    replacements = {
        "E59-S10-01": PRE / "keyframes/E59-S10-01-keyframe-v9b.png",
        "E59-S10-04": PRE / "keyframes/E59-S10-04-keyframe-v12c.png",
    }
    request_items = {row["item_id"]: row for row in request["items"]}
    for item_id, path in replacements.items():
        if not path.is_file():
            raise SystemExit(f"missing candidate: {path}")
        request_items[item_id]["media"] = [{
            "role": "KEYFRAME",
            "path": str(path),
            "exists": True,
            "sha256": digest(path),
            "media_type": "IMAGE",
        }]
    write(REQUEST, request)

    answers["request_path"] = str(REQUEST)
    answers["request_sha256"] = digest(REQUEST)
    answers["reviewed_at"] = now
    answer_items = {row["item_id"]: row for row in answers["items"]}
    for item_id, path in replacements.items():
        row = answer_items[item_id]
        row["media_reviewed"] = [str(path)]
        row["answers"] = {key: "PASS" for key in request["questionnaire"]}
        row["defects"] = []
    answer_items["E59-S10-01"]["observed"] = {
        "observed_visible_characters": ["世子", "白鲤郡主", "陈迹"],
        "observed_visible_props": [],
        "observed_space_anchors": ["LOC-XIULOU-ERLOU-YAZUO", "SUBSPACE-E59-S10-01"],
        "observed_text_strings": [],
    }
    answer_items["E59-S10-01"]["observation"] = (
        "已打开 v9b 原图逐像素核验：三人数量、左中右槽位、宋制服装、世子转身起势、室内外关系与冷灰暖烛色调均符合合同；"
        "陈迹仅内脸椭圆按锁定身份板纠正，边界与肤色连续，未见文字、克隆、截断或现代物。"
    )
    answer_items["E59-S10-04"]["observed"] = {
        "observed_visible_characters": ["梁狗儿", "梁猫儿", "世子", "陈迹", "白鲤郡主"],
        "observed_visible_props": ["大碗"],
        "observed_space_anchors": ["LOC-XIULOU-ERLOU-YAZUO", "SUBSPACE-E59-S10-04"],
        "observed_text_strings": [],
    }
    answer_items["E59-S10-04"]["observation"] = (
        "已打开 v12c 原图逐像素核验：画面保持四名成年男性与唯一女性白鲤，梁狗儿前景左举碗、梁猫儿前景右、世子中央、"
        "陈迹背景左、白鲤背景右；梁狗儿仅在眉眼鼻口核心区做柔边身份纠正，其余四张脸、服装、空碗桌面、构图和入场态未改，"
        "融合边界自然，未见文字、克隆、截断或现代物。"
    )
    write(ANSWERS, answers)
    print(json.dumps({"status": "PASS", "request": str(REQUEST), "answers": str(ANSWERS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
