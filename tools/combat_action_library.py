#!/usr/bin/env python3
"""Versioned, source-faithful combat action recipes.

The library is a serializer aid, never an authority source.  A binding may
only select a move already authorized by the canonical script and must retain
the episode-specific roles, props, contact point and outcome.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = ROOT / "configs/COMBAT_ACTION_LIBRARY_V1.json"
REQUIRED_PHASES = (
    "preparation_and_weight_shift",
    "displacement_and_action_path",
    "single_contact_or_visible_evasion",
    "force_transfer_and_reaction",
    "new_stable_end_state",
)


def _text(value: object) -> str:
    return str(value or "").strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=4)
def load_library(path: str = str(DEFAULT_LIBRARY)) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    failures: list[str] = []
    if payload.get("schema") != "qingshan.combat_action_library.v1":
        failures.append("COMBAT_LIBRARY_SCHEMA_INVALID")
    if (payload.get("reference_lineage") or {}).get("status") != "INFERRED_RECONSTRUCTED_NOT_ORIGINAL":
        failures.append("COMBAT_LIBRARY_INFERRED_REFERENCE_DISCLOSURE_MISSING")
    formula = tuple((payload.get("global_contract") or {}).get("physical_formula") or [])
    if formula != REQUIRED_PHASES:
        failures.append("COMBAT_LIBRARY_PHYSICAL_FORMULA_INVALID")
    ids: set[str] = set()
    for index, row in enumerate(payload.get("moves") or [], 1):
        move_id = _text(row.get("id"))
        if not move_id or move_id in ids:
            failures.append(f"COMBAT_LIBRARY_MOVE_ID_INVALID:{index}")
        ids.add(move_id)
        phases = row.get("physical_phases") or []
        if len(phases) != 5 or any(not _text(value) for value in phases):
            failures.append(f"COMBAT_LIBRARY_MOVE_PHASES_INVALID:{move_id or index}")
        for field in ("name_zh", "style_class", "camera_recipe", "sound_recipe"):
            if not _text(row.get(field)):
                failures.append(f"COMBAT_LIBRARY_MOVE_FIELD_MISSING:{move_id or index}:{field}")
        if row.get("source_authorization_required") is not True:
            failures.append(f"COMBAT_LIBRARY_SOURCE_AUTHORIZATION_NOT_REQUIRED:{move_id or index}")
    if not ids:
        failures.append("COMBAT_LIBRARY_EMPTY")
    if failures:
        raise ValueError(";".join(failures))
    payload["path"] = str(source)
    payload["sha256"] = sha256(source)
    payload["by_id"] = {row["id"]: row for row in payload["moves"]}
    return payload


def validate_binding(unit: dict[str, Any]) -> dict[str, Any]:
    binding = unit.get("combat_action_library_binding")
    if not binding:
        return {
            "schema": "qingshan.combat_action_library_binding_gate.v1",
            "status": "NOT_BOUND",
            "failures": [],
        }
    failures: list[str] = []
    library = load_library()
    if binding.get("schema") != "qingshan.combat_action_library_binding.v1":
        failures.append("COMBAT_ACTION_LIBRARY_BINDING_SCHEMA_INVALID")
    if binding.get("canonical_match") is not True:
        failures.append("COMBAT_ACTION_LIBRARY_CANONICAL_MATCH_REQUIRED")
    canonical_sha = _text(binding.get("canonical_action_source_sha256"))
    if len(canonical_sha) != 64 or any(ch not in "0123456789abcdef" for ch in canonical_sha.lower()):
        failures.append("COMBAT_ACTION_LIBRARY_CANONICAL_SHA_INVALID")
    move_ids = binding.get("move_ids") or []
    if not isinstance(move_ids, list) or not move_ids:
        failures.append("COMBAT_ACTION_LIBRARY_MOVE_IDS_MISSING")
        move_ids = []
    unknown = [move_id for move_id in move_ids if move_id not in library["by_id"]]
    if unknown:
        failures.append("COMBAT_ACTION_LIBRARY_UNKNOWN_MOVE:" + ",".join(unknown))
    roles = binding.get("role_bindings") or {}
    for field in ("initiator", "target", "weapon_or_prop_owner", "winner", "loser"):
        if not _text(roles.get(field)):
            failures.append(f"COMBAT_ACTION_LIBRARY_ROLE_MISSING:{field}")
    if binding.get("library_may_invent_story_action") is not False:
        failures.append("COMBAT_ACTION_LIBRARY_STORY_INVENTION_MUST_BE_FORBIDDEN")
    return {
        "schema": "qingshan.combat_action_library_binding_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "library_ref": library["path"],
        "library_sha256": library["sha256"],
        "move_ids": move_ids,
        "failures": failures,
    }


def compile_binding_prompt(unit: dict[str, Any], *, model_family: str) -> str:
    report = validate_binding(unit)
    if report["status"] == "NOT_BOUND":
        return ""
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    binding = unit["combat_action_library_binding"]
    roles = binding["role_bindings"]
    library = load_library()
    rows = []
    for index, move_id in enumerate(binding["move_ids"], 1):
        move = library["by_id"][move_id]
        phases = "→".join(move["physical_phases"])
        rows.append(
            f"动作库第{index}拍[{move['name_zh']}/{move_id}]：{phases}；"
            f"镜头={move['camera_recipe']}；同期声={move['sound_recipe']}"
        )
    model_note = (
        "H3按播放顺序连续执行可观察状态变化，优先写清正向物理过程，关键限制放在动作结果之后"
        if model_family == "minimax-h3"
        else "Seedance沿现有标准版打斗语法执行，不改变既有SD2镜头提示词规则"
    )
    return (
        "版本化打斗动作库绑定[INFERRED_RECONSTRUCTED_NOT_ORIGINAL]："
        f"发起者={roles['initiator']}；目标={roles['target']}；"
        f"武器或道具主人={roles['weapon_or_prop_owner']}；胜者={roles['winner']}；败者={roles['loser']}。"
        + "。".join(rows)
        + f"。{model_note}；动作库只翻译已授权剧情，不新增招式、能力、破坏、伤势、命中或胜负；"
        "禁止字幕、UI、来源身份、IP名称和文字拟声；无明确音频合同时不得推断对白、音乐或音效。"
    )


if __name__ == "__main__":
    data = load_library()
    print(json.dumps({
        "schema": data["schema"],
        "version": data["version"],
        "moves": len(data["moves"]),
        "sha256": data["sha256"],
    }, ensure_ascii=False))
