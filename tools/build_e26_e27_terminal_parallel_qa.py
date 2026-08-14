#!/usr/bin/env python3
"""Build full parallel QA batches for the terminal E26/E27 AgentCut repairs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_tree(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: replace_tree(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_tree(item, replacements) for item in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(episode: str, old_slug: str, new_slug: str, old_project: str, new_project: str,
          old_video: str, new_video: str, old_config: str, new_config: str) -> None:
    replacements = {
        old_slug: new_slug,
        old_project: new_project,
        old_video: new_video,
    }
    old_qa = ROOT / "qa" / old_slug
    new_qa = ROOT / "qa" / new_slug
    new_qa.mkdir(parents=True, exist_ok=True)

    for name in (
        f"{episode}_FULL_CUT_MULTI_SCENE_AUTHORITY.json",
        f"{episode}_FULL_CUT_MULTI_SCENE_QA_PROMPT.txt",
    ):
        text = (old_qa / name).read_text(encoding="utf-8")
        for old, new in replacements.items():
            text = text.replace(old, new)
        (new_qa / name).write_text(text, encoding="utf-8")

    request_name = f"{episode}_FULL_CUT_AI_REVIEW_REQUEST.json"
    request = replace_tree(json.loads((old_qa / request_name).read_text(encoding="utf-8")), replacements)
    video_path = ROOT / new_video
    request["items"][0]["metadata"]["candidate_sha256"] = sha256(video_path)
    (new_qa / request_name).write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    config = replace_tree(json.loads((ROOT / old_config).read_text(encoding="utf-8")), replacements)
    (ROOT / new_config).write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(ROOT / new_config)


def main() -> None:
    build(
        "E26",
        "e26_agentcut_v4_fight_tail_audio_repair_20260720",
        "e26_agentcut_v5_b06_blackframe_repair_20260720",
        "configs/e26_agentcut_project_v4_fight_tail_audio_repair_20260720.json",
        "configs/e26_agentcut_project_v5_b06_blackframe_repair_20260720.json",
        "exports/e26/agentcut_v4_fight_tail_audio_repair_20260720/E26_AGENTCUT_V4_FIGHT_TAIL_AUDIO_REPAIR_NOT_FINAL.mp4",
        "exports/e26/agentcut_v5_b06_blackframe_repair_20260720/E26_AGENTCUT_V5_B06_BLACKFRAME_REPAIR_NOT_FINAL.mp4",
        "configs/E26_agentcut_v4_fight_tail_audio_repair_parallel_qa_20260720.json",
        "configs/E26_agentcut_v5_b06_blackframe_repair_parallel_qa_20260720.json",
    )
    build(
        "E27",
        "e27_agentcut_v5_b02_b05_brightness_only_20260720",
        "e27_agentcut_v6_b02_textsafe_bridge_20260720",
        "configs/e27_agentcut_project_v5_b02_b05_brightness_only_20260720.json",
        "configs/e27_agentcut_project_v6_b02_textsafe_bridge_20260720.json",
        "exports/e27/agentcut_v5_b02_b05_brightness_only_20260720/E27_AGENTCUT_V5_B02_B05_BRIGHTNESS_ONLY_NOT_FINAL.mp4",
        "exports/e27/agentcut_v6_b02_textsafe_bridge_20260720/E27_AGENTCUT_V6_B02_TEXTSAFE_BRIDGE_NOT_FINAL.mp4",
        "configs/E27_agentcut_v5_b02_b05_brightness_only_parallel_qa_20260720.json",
        "configs/E27_agentcut_v6_b02_textsafe_bridge_parallel_qa_20260720.json",
    )
    build(
        "E26",
        "e26_agentcut_v5_b06_blackframe_repair_20260720",
        "e26_agentcut_v6_human_gate_source_repair_20260720",
        "configs/e26_agentcut_project_v5_b06_blackframe_repair_20260720.json",
        "configs/e26_agentcut_project_v6_human_gate_source_repair_20260720.json",
        "exports/e26/agentcut_v5_b06_blackframe_repair_20260720/E26_AGENTCUT_V5_B06_BLACKFRAME_REPAIR_NOT_FINAL.mp4",
        "exports/e26/agentcut_v6_human_gate_source_repair_20260720/E26_AGENTCUT_V6_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL.mp4",
        "configs/E26_agentcut_v5_b06_blackframe_repair_parallel_qa_20260720.json",
        "configs/E26_agentcut_v6_human_gate_source_repair_parallel_qa_20260720.json",
    )
    build(
        "E27",
        "e27_agentcut_v6_b02_textsafe_bridge_20260720",
        "e27_agentcut_v7_human_gate_source_repair_20260720",
        "configs/e27_agentcut_project_v6_b02_textsafe_bridge_20260720.json",
        "configs/e27_agentcut_project_v7_human_gate_source_repair_20260720.json",
        "exports/e27/agentcut_v6_b02_textsafe_bridge_20260720/E27_AGENTCUT_V6_B02_TEXTSAFE_BRIDGE_NOT_FINAL.mp4",
        "exports/e27/agentcut_v7_human_gate_source_repair_20260720/E27_AGENTCUT_V7_HUMAN_GATE_SOURCE_REPAIR_NOT_FINAL.mp4",
        "configs/E27_agentcut_v6_b02_textsafe_bridge_parallel_qa_20260720.json",
        "configs/E27_agentcut_v7_human_gate_source_repair_parallel_qa_20260720.json",
    )


if __name__ == "__main__":
    main()
