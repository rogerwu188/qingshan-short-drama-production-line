#!/usr/bin/env python3
"""One rule for "does this line follow the writer's own world or the East-Asian period lock?".

The engine was built for Chinese period dramas: an anachronism ban (phone, car, zipper ...) and
a Latin-text OCR fail are P0 gates.  An English, near-future line (Twelve Gazes, 2026-10-21) needs
field jackets with zippers and archive screens with English labels.

Rule (PR #108, generalized here):

* ``visual_culture_contract.era_lock`` decides when the writer set it:
  ``"AUTHORED_WORLD"`` -> authored world, ``"EAST_ASIAN_PERIOD"`` -> period behaviour;
* otherwise an English-dialogue line is an authored world and every Chinese line keeps the
  period behaviour exactly as before.

The dialogue language follows ``nalu_pipeline.resolve_dialogue_language``: generation contract
``dialogue_language`` -> runtime config ``project.language`` -> ``"zh"``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ERA_LOCK_AUTHORED_WORLD = "AUTHORED_WORLD"
ERA_LOCK_EAST_ASIAN_PERIOD = "EAST_ASIAN_PERIOD"
DIALOGUE_LANGUAGES = ("zh", "en")


def dialogue_language_code(value: Any) -> str | None:
    """"zh" / "zh-CN" -> "zh"; "en" / "en-US" -> "en"; anything else -> None (as nalu_pipeline)."""
    text = str(value or "").strip().lower().replace("_", "-")
    for code in DIALOGUE_LANGUAGES:
        if text == code or text.startswith(code + "-"):
            return code
    return None


def resolve_dialogue_language(contract: Any, config: Any = None) -> str:
    """contract ``dialogue_language`` -> runtime config ``project.language`` -> "zh"."""
    from_contract = dialogue_language_code(
        contract.get("dialogue_language") if isinstance(contract, dict) else None)
    if from_contract:
        return from_contract
    project = config.get("project") if isinstance(config, dict) else None
    from_config = dialogue_language_code(project.get("language") if isinstance(project, dict) else None)
    return from_config or "zh"


def era_lock(visual_culture_contract: Any) -> str:
    vcc = visual_culture_contract if isinstance(visual_culture_contract, dict) else {}
    return str(vcc.get("era_lock") or "").strip().upper()


def authored_world_from(visual_culture_contract: dict[str, Any] | None,
                        dialogue_language: str | None) -> bool:
    """True when the line follows the writer's own world instead of the East-Asian period lock."""
    mode = era_lock(visual_culture_contract)
    if mode in {ERA_LOCK_AUTHORED_WORLD, ERA_LOCK_EAST_ASIAN_PERIOD}:
        return mode == ERA_LOCK_AUTHORED_WORLD
    return str(dialogue_language or "zh").strip().lower().startswith("en")


def is_english(dialogue_language: str | None) -> bool:
    return str(dialogue_language or "zh").strip().lower().startswith("en")


def load_runtime_config(runtime_root: Any) -> dict[str, Any]:
    """``<runtime_root>/qingshan.json`` (the nalu runtime config), or {} when absent/unreadable."""
    try:
        payload = json.loads((Path(str(runtime_root)) / "qingshan.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def authored_world_for(contract: Any, config: Any = None) -> bool:
    """The rule applied to a generation contract (+ optional runtime config)."""
    vcc = contract.get("visual_culture_contract") if isinstance(contract, dict) else None
    return authored_world_from(vcc, resolve_dialogue_language(contract, config))
