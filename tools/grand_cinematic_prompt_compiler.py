#!/usr/bin/env python3
"""Compile one validated cinematic contract into still and video prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.grand_cinematic_visual_contract_gate import validate
except ModuleNotFoundError:  # Direct script execution from tools/.
    from grand_cinematic_visual_contract_gate import validate


def _join(value) -> str:
    return " / ".join(str(item) for item in value)


def compile_prompts(payload: dict) -> dict:
    report = validate(payload)
    if report["status"] != "PASS":
        raise ValueError(f"visual contract failed with {report['error_count']} errors")
    scene = payload["scene_lock"]
    locked = (
        f"剧本硬锁：地点{scene['location']}，时段{scene['time_of_day']}，天气{scene['weather']}，"
        f"事件{scene['event']}；不得改写地点、时段、天气或事件。"
    )
    compiled = []
    for index, shot in enumerate(payload["shots"], 1):
        palette = shot["palette"]
        shared = (
            f"{locked} {shot['shot_scale']}，{shot['lens_intent']}，机位{shot['camera_height']}；"
            f"前中后景：{_join(shot['depth_layers'])}；尺度锚点：{shot['scale_anchor']}；"
            f"主色{palette['dominant']}，对比色{palette['contrast']}，点睛色{palette['accent']}；"
            f"动机光：{shot['key_light']}；空气透视：{shot['atmosphere']}；"
            f"环境运动：{_join(shot['environmental_motion'])}；材质：{_join(shot['material_detail'])}。"
        )
        negative = _join(shot["negative_constraints"])
        still = f"{shared} 静帧执行：{shot['still_prompt_contract']}。禁止：{negative}。"
        video = (
            f"{shared} 生成{shot['duration_seconds']}秒真实连续视频；运镜：{shot['camera_motion']}；"
            f"运动执行：{shot['video_motion_contract']}。禁止：{negative}；禁止静态图电子变焦冒充镜头运动。"
        )
        compiled.append({
            "shot_index": index,
            "duration_seconds": shot["duration_seconds"],
            "still_prompt": still,
            "still_prompt_sha256": hashlib.sha256(still.encode()).hexdigest(),
            "video_prompt": video,
            "video_prompt_sha256": hashlib.sha256(video.encode()).hexdigest(),
        })
    return {
        "schema": "qingshan.grand_cinematic_prompt_compilation.v1",
        "visual_contract_input_sha256": report["input_sha256"],
        "script_state_locked": True,
        "shot_count": len(compiled),
        "shots": compiled,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    compiled = compile_prompts(payload)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: compiled[key] for key in ("schema", "shot_count", "visual_contract_input_sha256")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
