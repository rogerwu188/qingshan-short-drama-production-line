#!/usr/bin/env python3
"""Package E32 failed video units for ordered manual Seedance submission."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/E32_VIDEO_MINIMAL_REFERENCE_REPAIR_V7.json"
OUTPUT = ROOT / "exports/e32/manual_seedance_failed_units_20260723"


def absolute(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_numbered(source: Path, target_dir: Path, index: int, label: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{index:02d}_{label}{source.suffix.lower()}"
    shutil.copy2(source, target)
    return target


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for task in config["tasks"]:
        unit = task["unit_id"]
        unit_dir = OUTPUT / unit
        unit_dir.mkdir(parents=True, exist_ok=True)
        prompt_source = absolute(task["prompt_file"])
        prompt_target = unit_dir / "PROMPT_FULL.txt"
        shutil.copy2(prompt_source, prompt_target)
        images = []
        for index, value in enumerate(task.get("reference_images") or [], 1):
            source = absolute(value)
            target = copy_numbered(source, unit_dir / "images", index, source.stem)
            images.append({"slot": f"@图片{index}", "path": str(target), "sha256": sha(target)})
        audios = []
        ordered_audio = sorted(
            task.get("dialogue_audio_assets") or [],
            key=lambda row: int(str(row.get("audio_slot") or "@音频999").replace("@音频", "")),
        )
        for index, row in enumerate(ordered_audio, 1):
            source = absolute(row["path"])
            target = copy_numbered(source, unit_dir / "audio", index, f"{row['dia_id']}_{row['speaker']}")
            audios.append({
                "slot": row["audio_slot"],
                "dia_id": row["dia_id"],
                "speaker": row["speaker"],
                "spoken_text": row["spoken_text"],
                "purpose": row["purpose"],
                "path": str(target),
                "sha256": sha(target),
            })
        manifest = {
            "episode": "E32",
            "unit_id": unit,
            "duration_seconds": task["duration_seconds"],
            "model": task["model"],
            "aspect_ratio": task["aspect_ratio"],
            "resolution": task["resolution"],
            "prompt": str(prompt_target),
            "prompt_sha256": sha(prompt_target),
            "images_in_upload_order": images,
            "audios_in_upload_order": audios,
            "manual_policy": "Upload each numbered file to the matching prompt slot. Voice-style references lock timbre; the exact spoken line remains the quoted prompt text.",
        }
        manifest_path = unit_dir / "UPLOAD_ORDER.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        index_rows.append({"unit_id": unit, "directory": str(unit_dir), "manifest": str(manifest_path)})
    readme = [
        "# E32 failed video units - manual Seedance package",
        "",
        "Upload images and audios in numeric order, then paste PROMPT_FULL.txt unchanged.",
        "Each unit is independent; submit it as soon as its own files are uploaded.",
        "",
    ]
    readme.extend(f"- {row['unit_id']}: {row['directory']}" for row in index_rows)
    (OUTPUT / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    (OUTPUT / "PACKAGE_INDEX.json").write_text(json.dumps(index_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = shutil.make_archive(str(OUTPUT), "zip", root_dir=OUTPUT.parent, base_dir=OUTPUT.name)
    print(json.dumps({"status": "PASS", "directory": str(OUTPUT), "archive": archive, "unit_count": len(index_rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
