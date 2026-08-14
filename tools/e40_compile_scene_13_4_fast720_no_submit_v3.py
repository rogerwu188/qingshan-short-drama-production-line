#!/usr/bin/env python3
"""Compile the E40 scene 13-4 preproduction manifest for current Fast720 policy.

This compiler is deliberately no-submit: it changes only local planning metadata and
keeps every paid/provider gate closed until the exact start frame/tail dependencies
and a fresh exactly-one authorization exist.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/action_precompile/E40_SCENE_13_4_CAUSAL_ATOMIC_VIDEO_MANIFEST_V2.json"
OUTPUT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/action_precompile/E40_SCENE_13_4_CAUSAL_ATOMIC_VIDEO_MANIFEST_V3_FAST720_NO_SUBMIT.json"

RATIONALE_BY_TASK = {
    "E40-U13-4-A01-ICE-CURTAIN": (
        "The cold arrow is visibly stopped in the raised ice curtain and Chenji reaches the protective end state by 2.6 seconds; "
        "the four-second request is only the provider floor, with residual ice-crack micro-motion excluded from the timeline."
    ),
    "E40-U13-4-A02-PAPER-BIND": (
        "Both attackers are visibly paper-bound to separate pillars with their blades diverted by 2.9 seconds; "
        "the four-second request is only the provider floor, with paper-fiber tension micro-motion excluded from the timeline."
    ),
    "E40-U13-4-A03-CONTROLLED-DISARM": (
        "The short blade lands on the carpet and the right attacker is controlled empty-handed by 2.35 seconds; "
        "the four-second request is only the provider floor, with restrained breathing and sleeve-settle micro-motion excluded from the timeline."
    ),
    "E40-U13-4-A04-ARROW-CUT-OFF": (
        "The interception breaks the execution arrow, both fragments land, and the trail points to an empty dark position by 2.35 seconds; "
        "the four-second request is only the provider floor, with fragment-settle micro-motion excluded from the timeline."
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads(SOURCE.read_text(encoding="utf-8"))
    manifest["manifest_revision"] = "V3_FAST720_NO_SUBMIT"
    manifest["supersedes"] = str(SOURCE.relative_to(ROOT))
    manifest["supersedes_sha256"] = sha256(SOURCE)
    manifest["current_model_policy"] = {
        "allowed_model": "seedance-2.0-fast",
        "allowed_resolution": "720p",
        "forbidden_models": ["seedance-2.0", "seedance-2.0-pro", "seedance-2.0-mini"],
        "status": "PASS_LOCAL_PRECOMPILE_ONLY",
    }
    manifest["paid_submission_status"] = (
        "BLOCKED_NO_SUBMIT_PENDING_ADMITTED_U18_START_KEYFRAME_THREE_SERIAL_EXACT_TAIL_BINDINGS_AND_FRESH_EXACTLY_ONE_AUTHORIZATION"
    )
    manifest["provider_post_allowed"] = False
    manifest["transaction_creation_allowed"] = False
    manifest["maximum_new_submissions"] = 0
    manifest["retry_allowed"] = False
    manifest["no_submit_reason"] = (
        "Local policy migration does not create source admission, predecessor-tail authority, or paid execution authority."
    )

    for task in manifest["tasks"]:
        task["source_id"] = task["task_key"]
        task["model"] = "seedance-2.0-fast"
        task["resolution"] = "720p"
        task["duration_plan"] = {
            "policy": "qingshan.shot_generation_duration.v5",
            "duration_seconds": task["duration"],
            "rationale": RATIONALE_BY_TASK[task["task_key"]],
            "edit_policy": (
                "At native 1x speed, trim only after the declared exit_state_token; discard the unauthored safety tail so the four units total about 12 seconds."
            ),
        }
        task["paid_submission_allowed"] = False
        task["provider_post_allowed"] = False
        task["transaction_creation_allowed"] = False
        task["maximum_new_submissions"] = 0

    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT.relative_to(ROOT)), "sha256": sha256(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
