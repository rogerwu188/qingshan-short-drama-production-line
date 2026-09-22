#!/usr/bin/env python3
"""Build the exact-media E59 R7 keyframe review from the admitted R6 review.

This helper preserves the 28 unchanged, already-reviewed items and replaces only
the two R7 items after a fresh pixel inspection.  It is intentionally episode
specific so that no other runtime can consume these observations by accident.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/nalu_runtime_e59/runtime/reviews/E59")
REQUEST = ROOT / "E59-keyframe-r7-full_request.json"
PREVIOUS = ROOT / "E59-keyframe-r6-full_answers.json"
OUTPUT = ROOT / "E59-keyframe-r7-full_answers.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    request_items = {row["item_id"]: row for row in request["items"]}
    answers = deepcopy(previous)
    answers["request_path"] = str(REQUEST)
    answers["request_sha256"] = sha256(REQUEST)
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
                "已打开 R7 原图逐像素核验：画左绛紫宋袍世子正在转身，白鲤郡主居中，"
                "陈迹在画右；三人面部、站位、服装和入场动作清楚，没有字幕、水印、现代物或克隆人物。"
            )
            row["defects"] = []
        elif row["item_id"] == "E59-S10-04":
            row["answers"] = {key: "PASS" for key in request["questionnaire"]}
            for key in (
                "cast_exactly_as_declared",
                "wardrobe_matches_bible",
                "each_visible_character_identity_recognisable",
                "action_role_topology_readable",
                "no_p0_defect_present",
            ):
                row["answers"][key] = "FAIL"
            row["observed"] = {
                "observed_visible_characters": [
                    "UNDECLARED:前景左年轻清秀男子",
                    "UNDECLARED:前景右年轻女子",
                    "世子",
                    "陈迹",
                    "白鲤郡主",
                ],
                "observed_visible_props": ["大碗"],
                "observed_space_anchors": ["LOC-XIULOU-ERLOU-YAZUO", "SUBSPACE-E59-S10-04"],
                "observed_text_strings": [],
            }
            row["observation"] = (
                "已打开 R7 原图逐像素核验：五人构图、满桌空碗和悬空大碗均可见，但前景右本应为成年男性梁猫儿，"
                "实际生成成了年轻女子；前景左梁狗儿也变成清秀青年，缺少粗壮宽肩、包巾和锁定身份特征，属于阻断级换人。"
            )
            row["defects"] = [
                {
                    "code": "CAST_IDENTITY_SEX_DRIFT",
                    "severity": "P0",
                    "description": "前景右梁猫儿应为精瘦成年男性，实际生成成年轻女性，人物性别与锁定身份均错误。",
                },
                {
                    "code": "LIANGGOUER_IDENTITY_WARDROBE_DRIFT",
                    "severity": "P0",
                    "description": "前景左梁狗儿应为粗壮宽肩、包巾的成熟男性，实际是清秀青年且服装轮廓不符。",
                },
            ]

    OUTPUT.write_text(json.dumps(answers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", "output": str(OUTPUT), "request_sha256": answers["request_sha256"]}))


if __name__ == "__main__":
    main()
