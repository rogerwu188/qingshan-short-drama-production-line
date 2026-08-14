#!/usr/bin/env python3
"""Pad exact E38 audio references to Seedance's two-second minimum without regeneration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import wave

from upload_giggle_asset import upload as upload_giggle_asset


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E38_V6_EXACT_EXPRESSIVE_AUDIO_ASSETS_20260805.json"
MIN_SECONDS = 2.2


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / source.getframerate()


def pad(source_path: Path, output_path: Path) -> tuple[float, float]:
    with wave.open(str(source_path), "rb") as source:
        params = source.getparams()
        frames = source.readframes(source.getnframes())
    original = params.nframes / params.framerate
    target_frames = max(params.nframes, round(MIN_SECONDS * params.framerate))
    silence_frames = target_frames - params.nframes
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as output:
        output.setparams(params)
        output.writeframes(frames)
        output.writeframes(b"\x00" * silence_frames * params.nchannels * params.sampwidth)
    return original, duration(output_path)


def main() -> int:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    updates = []
    for row in payload["results"]:
        source = Path(row["wav_path"])
        original = duration(source)
        if original >= 2.0:
            continue
        output = source.with_name(source.stem + "-seedance-min2s.wav")
        before, after = pad(source, output)
        registration = upload_giggle_asset(output, True)
        asset_id = (registration.get("data") or {}).get("asset_id")
        if registration.get("code") != 200 or not asset_id:
            raise SystemExit(f"asset registration failed for {row['line_id']}: {registration}")
        row["original_registered_asset_id"] = row["registered_asset_id"]
        row["registered_asset_id"] = asset_id
        row["seedance_audio_path"] = str(output)
        row["seedance_audio_sha256"] = sha(output)
        row["seedance_duration_seconds"] = round(after, 3)
        row["padding_transform"] = "TRAILING_DIGITAL_SILENCE_ONLY_NO_REGENERATION"
        updates.append({"line_id": row["line_id"], "before": round(before, 3), "after": round(after, 3), "asset_id": asset_id})
    payload["seedance_minimum_duration_gate"] = {
        "status": "PASS",
        "minimum_seconds": 2.0,
        "target_seconds": MIN_SECONDS,
        "updated": updates,
        "credit": {"pay": 0, "refund": 0, "net": 0},
    }
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "updated": updates, "credits": payload["credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
