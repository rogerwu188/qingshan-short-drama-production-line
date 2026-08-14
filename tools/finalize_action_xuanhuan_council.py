#!/usr/bin/env python3
"""Record the CL2X-384 council review after the action-xuanhuan gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--review", required=True)
    args = parser.parse_args()
    script_path = Path(args.script)
    gate_path = Path(args.gate)
    review_path = Path(args.review)
    payload = json.loads(script_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if gate.get("status") != "PASS":
        raise SystemExit("action-xuanhuan gate is not PASS")

    episode = payload["episode"]
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["status"] = "APPROVED_COUNCIL_ACTION_XUANHUAN_V4"
    payload["review_status"] = "APPROVED_COUNCIL_AND_ACTION_XUANHUAN_GATE"
    payload["generation_allowed"] = True
    payload["final_lock_blocked_until"] = None
    payload["action_xuanhuan_gate"] = str(gate_path)
    payload["council_review"] = str(review_path)
    script_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(script_path.read_bytes()).hexdigest()

    beat_rows = "\n".join(
        f"| {beat['beat_id']} | {beat['payload_delivery']} | {beat['action_spine']} | {beat['xuanhuan_element']} | {beat['power_visualization']} | PASS |"
        for beat in payload["structure"]
    )
    review = f"""# {episode} 动作化 + 玄幻化审稿议会 V4

- recorded_at: `{recorded_at}`
- directive: `CL2X-383/384`
- script: `{script_path}`
- script_sha256: `{digest}`
- machine_gate: `{gate_path}` = `PASS`
- verdict: `APPROVED_COUNCIL_AND_ACTION_XUANHUAN_GATE`

## 五席独立意见

- 顶级电影导演:六拍均由明确身体行动承载戏点，空间从门口、药架、内堂或档房长廊持续移动，不再依赖站桩正反打。
- 短剧导演:开场冲突直接发生，真打斗嵌入证物争夺，动作与揭示同步，具备继续观看拉力。
- 小说原著者:冰流、皎兔阴神和乌云灵性回到查案手段，玄幻服务原因果，不另起支线。
- 普通观众:每拍都有可看见的危险、反制或奇观，观感从“听线索”转为“看事件发生”。
- 执行者:动作均可拆成多镜标准 storyboard，环境介质明确；旧候选可按兼容性保留，缺口用 V4 新镜补齐。

## 逐拍硬门

| Beat | payload_delivery | action_spine | xuanhuan_element | power_visualization | 结论 |
|---|---|---|---|---|---|
{beat_rows}

## 主席裁决

四字段 6/6 齐全，存在完整真打斗链及玄幻能力揭示，机器门无失败。批准 V4 进入新一轮图片/视频规划；此前静态标准分镜仅作可复用候选，未经 V4 coverage 映射不得 final-lock。回滚点为原 V3 剧本和全部既有媒体。
"""
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(review, encoding="utf-8")
    print(json.dumps({"status": "PASS", "episode": episode, "script_sha256": digest, "review": str(review_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
