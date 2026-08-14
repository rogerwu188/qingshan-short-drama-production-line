#!/usr/bin/env python3
"""Apply reversible, shot-local native-text cleanup to E27 N08 and N19."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
OUTPUT_DIR = ROOT / "working_assets/e27_agentcut_v15_native_text_repair_20260720"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V15_NATIVE_TEXT_REPAIR_RECEIPT_20260720.json"

REPAIRS = [
    {
        "shot_id": "E27-N08",
        "source": ROOT
        / "working_assets/e27_writer_agent_v040_video_v1_20260720/candidates/"
        "E27_E27-N08-WRITER-AGENT-V040-VIDEO-V1_0888aecc-656b-41c8-b155-308d9fe7b568.mp4",
        "output": OUTPUT_DIR / "E27-N08_NATIVE_TEXT_CLEAN_V1.mp4",
        "box": {"x": 480, "y": 650, "w": 500, "h": 300},
        "enable": "between(t,2.70,6.00)",
        "reason": "Blur only the generated glyph band on the register fragment while preserving the wrist-tying action.",
    },
    {
        "shot_id": "E27-N19",
        "source": ROOT
        / "working_assets/e27_writer_agent_v040_video_visualfix_r1_20260720/candidates/"
        "E27_E27-N19-WRITER-AGENT-V040-VIDEO-VISUALFIX-R1_cca67c5c-0c9a-42fe-ba7d-f5bbca99a2ea.mp4",
        "output": OUTPUT_DIR / "E27-N19_NATIVE_TEXT_CLEAN_V1.mp4",
        "box": {"x": 370, "y": 600, "w": 430, "h": 520},
        "enable": "between(t,1.70,6.00)",
        "reason": "Blur the generated glyphs on the time tag while preserving the tag, hand, body and placement action.",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)["format"]
    return {"duration_seconds": float(payload["duration"]), "size_bytes": int(payload["size"])}


def repair(item: dict[str, object]) -> dict[str, object]:
    source = Path(item["source"])
    output = Path(item["output"])
    box = item["box"]
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        "[0:v]split=2[base][region];"
        f"[region]crop={box['w']}:{box['h']}:{box['x']}:{box['y']},boxblur=24:2[blurred];"
        f"[base][blurred]overlay={box['x']}:{box['y']}:enable='{item['enable']}'[video]"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-filter_complex",
            filter_graph,
            "-map",
            "[video]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(output),
        ],
        check=True,
    )
    source_probe = probe(source)
    output_probe = probe(output)
    if abs(float(source_probe["duration_seconds"]) - float(output_probe["duration_seconds"])) > 0.05:
        raise RuntimeError(f"Duration drift for {item['shot_id']}")
    return {
        "shot_id": item["shot_id"],
        "status": "REPAIRED_PENDING_OCR_QA",
        "source_path": str(source),
        "source_sha256": sha256(source),
        "output_path": str(output),
        "output_sha256": sha256(output),
        "source_probe": source_probe,
        "output_probe": output_probe,
        "repair_box": box,
        "repair_enable": item["enable"],
        "repair_reason": item["reason"],
        "rollback_point": str(source),
        "credit": 0,
        "credit_reason": "Local deterministic media repair; no remote generation call.",
    }


def main() -> None:
    results = [repair(item) for item in REPAIRS]
    receipt = {
        "schema": "qingshan.native_text_repair_receipt.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "REPAIRED_PENDING_OCR_QA",
        "policy": "Repair only the two failed shots; preserve the other 22 exact sources.",
        "items": results,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
