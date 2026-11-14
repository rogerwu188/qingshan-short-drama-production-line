#!/usr/bin/env python3
"""Is the MiniMax-H3 compile anchor plan older than the identity locks it needs?

S2 (preproduction) writes ``<EP>_VIDEO_UNIT_ANCHOR_PLAN_H3_COMPILE_V1.json``: the gated anchor plan
plus the locked identity plate of every visible character.  S2 runs before S3, so a character first
locked in THIS episode's S3 has no plate at that moment and the file records it under
``h3_identity_plates_missing`` (likewise ``h3_prop_reference_cards_missing``).  The whole-batch prompt
gate (prompt_batch_prepare.sh -> plan_compile.sh) compiles from that file before any keyframe exists
and nothing rebuilds it in between, so the planning compile stops with
``H3_SPEAKER_SUBJECT_BINDING_MISSING:<unit>:<name>`` however often it is retried (fleet devices 1144
E03 and 0069 E06, 2026-11-14).

This tool only answers the question; prompt_batch_prepare.sh then re-runs S2 (free, offline) so the
real builder rewrites the file.  It answers "stale" only while the keyframe directory holds no image:
once keyframes exist the S6 rebuild owns the anchor plan and a keyframe-less S2 must not replace it.

Exit code 0 = stale (reason on stdout), 1 = nothing to do.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MISSING_KEYS = ("h3_identity_plates_missing", "h3_prop_reference_cards_missing")


def compile_anchor_path(preproduction_dir: Path, episode: str) -> Path:
    return preproduction_dir / f"{episode}_VIDEO_UNIT_ANCHOR_PLAN_H3_COMPILE_V1.json"


def stale_reason(preproduction_dir: Path, episode: str) -> str | None:
    """Why the compile anchor plan should be rebuilt by S2 before the planning compile, else None."""
    path = compile_anchor_path(Path(preproduction_dir), episode)
    if not path.is_file():
        return None  # not an H3 episode, or S2 has not run: nothing to refresh
    try:
        plan: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # unreadable file: leave it to the compile, which fails closed on it
    if not isinstance(plan, dict):
        return None
    missing = {key: sorted(str(v) for v in (plan.get(key) or [])) for key in MISSING_KEYS}
    if not any(missing.values()):
        return None
    keyframes = Path(preproduction_dir) / "keyframes"
    if keyframes.is_dir() and any(keyframes.glob("*.png")):
        return None  # keyframes exist: the S6 rebuild (with keyframes) owns the anchor plan
    return "H3_COMPILE_ANCHOR_PLAN_PREDATES_LOCKS:" + ";".join(
        f"{key}={','.join(values)}" for key, values in missing.items() if values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--episode", required=True)
    parser.add_argument("--preproduction-dir", required=True, type=Path)
    args = parser.parse_args()
    reason = stale_reason(args.preproduction_dir, args.episode)
    if reason is None:
        return 1
    print(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
