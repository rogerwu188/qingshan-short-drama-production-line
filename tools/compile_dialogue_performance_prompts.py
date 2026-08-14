#!/usr/bin/env python3
"""Compile dialogue text and acting direction into multimodal prompt payloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED = ("acting_verb", "subtext", "tone", "pace", "volume", "pause_before_ms", "pause_after_ms", "stress", "breath", "physical_delivery")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialogue", required=True)
    parser.add_argument("--performance-bible", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    dialogue = json.loads(Path(args.dialogue).read_text(encoding="utf-8"))
    bible = json.loads(Path(args.performance_bible).read_text(encoding="utf-8"))
    characters = bible.get("characters") or {}
    errors: list[str] = []
    compiled: list[dict[str, Any]] = []
    for line in dialogue.get("lines") or []:
        line_id = line.get("id", "UNKNOWN")
        speaker = line.get("speaker")
        profile = characters.get(speaker)
        delivery = line.get("delivery") or {}
        if not profile:
            errors.append(f"{line_id}: missing speaker performance profile: {speaker}")
            continue
        missing = [key for key in REQUIRED if delivery.get(key) in (None, "", [])]
        if missing:
            errors.append(f"{line_id}: missing delivery fields: {','.join(missing)}")
            continue
        stress = "、".join(delivery["stress"])
        prompt = (
            f"Speaker {speaker}, bind voice asset {profile.get('voice_asset_id') or 'registered native voice for this role'}. "
            f"Speak the exact Mandarin line without changing words: ‘{line['text']}’. "
            f"Acting objective: {delivery['acting_verb']}; subtext: {delivery['subtext']}. "
            f"Tone: {delivery['tone']}; pace: {delivery['pace']}; volume: {delivery['volume']}. "
            f"Pause {delivery['pause_before_ms']}ms before and {delivery['pause_after_ms']}ms after; stress: {stress}. "
            f"Breath: {delivery['breath']}. Physical delivery: {delivery['physical_delivery']}. "
            f"Character baseline: {profile['baseline']}; signature: {profile['signature']}; forbidden performance: {profile['forbidden']}. "
            f"Listener reaction: {line.get('listener_reaction', '')}. Natural conversational Mandarin, no announcer voice, no theatrical recitation."
        )
        compiled.append({"id": line_id, "speaker": speaker, "text": line["text"], "voice_asset_id": profile.get("voice_asset_id"), "performance_prompt": prompt})
    report = {"schema": "ai_drama.dialogue_performance_prompt_package.v1", "episode": dialogue.get("episode"), "status": "PASS" if not errors else "FAIL", "errors": errors, "lines": compiled}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "line_count": len(compiled), "error_count": len(errors)}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
