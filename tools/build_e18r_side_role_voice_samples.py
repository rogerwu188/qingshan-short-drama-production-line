#!/usr/bin/env python3
"""Generate dry local Mandarin voice samples for E18R side-role registration."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_slug(value: str) -> str:
    mapping = {
        "王府仆从": "wangfu_servant",
        "巡夜人": "night_watch",
        "路人低声": "passerby_hushed",
        "王府传话人": "wangfu_messenger",
        "车中人": "carriage_voice",
        "远处声音": "distant_voice",
    }
    if value not in mapping:
        raise ValueError(f"Unknown E18R side role: {value}")
    return mapping[value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--speaker")
    args = parser.parse_args()

    contract_path = Path(args.contract).resolve()
    out_dir = Path(args.out_dir).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    all_rows = contract.get("side_role_candidates") or []
    if len(all_rows) != 6:
        raise SystemExit(f"Expected 6 side-role candidates, found {len(all_rows)}")
    rows = [row for row in all_rows if not args.speaker or row["speaker"] == args.speaker]
    if not rows:
        raise SystemExit(f"Speaker not found in contract: {args.speaker}")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "E18R_SIDE_ROLE_VOICE_SAMPLES_MANIFEST_20260716.json"
    existing = {}
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing = {row["speaker"]: row for row in prior.get("samples") or []}
    for row in rows:
        slug = safe_slug(row["speaker"])
        aiff = out_dir / f"E18R_VOICE_{slug}.aiff"
        wav = out_dir / f"E18R_VOICE_{slug}.wav"
        subprocess.run(
            [
                "say",
                "-v",
                row["macos_voice"],
                "-r",
                str(row["rate_wpm"]),
                "-o",
                str(aiff),
                row["sample_text"],
            ],
            check=True,
        )
        subprocess.run(
            [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(aiff),
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            check=True,
        )
        aiff.unlink()
        existing[row["speaker"]] = {
            **row,
            "sample_path": str(wav),
            "sample_sha256": sha256(wav),
            "registration_status": "PENDING_REMOTE_REGISTRATION",
        }
    generated = [existing[row["speaker"]] for row in all_rows if row["speaker"] in existing]
    manifest = {
        "schema": "qingshan.e18r_side_role_voice_samples.v1",
        "episode": "E18R",
        "status": "PASS_LOCAL_SAMPLES_READY_FOR_REGISTRATION",
        "contract": str(contract_path),
        "sample_count": len(generated),
        "samples": generated,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": manifest["status"], "samples": len(generated)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
