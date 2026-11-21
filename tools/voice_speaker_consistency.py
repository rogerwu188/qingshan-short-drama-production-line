#!/usr/bin/env python3
"""Free pre-submit voice / speaker consistency check of one H3 video task (advisory, never blocks).

Line owner 2026-11-20 (JA-01 E02 ~1:13, 摄政王 E18 ~40 s): a woman on screen spoke with a man's voice.  The JA case
was casting (lines/nalu/runtime/tools/voice_gender.py + the S4 casting check); this check covers the other ways the
same symptom can be produced, from the task alone, before any credit is spent:

* AUDIO_SLOT_ORDER_MISMATCH        the H3 audio URLs are not the speaker_voice_contract bindings in slot order
* PROMPT_AUDIO_SLOT_UNBOUND        the prompt names an @AudioN no binding owns (or misses one that is sent)
* VOICE_REF_OF_ANOTHER_CHARACTER   the bound reference belongs to another character in the voice registry
* VOICE_GENDER_CONTRADICTS_SPEAKER the bound voice's gender (voice_gender.py) differs from the speaker's
* OFFSCREEN_SPEAKER_NOT_MARKED     a line whose speaker is not on screen in its shot, with no offscreen wording in
                                   the prompt (H3 would lip-sync whoever is visible)

Status: PASS / ADVISORY (issues listed) / NOT_APPLICABLE (no dialogue).  The submitter prints one
``VOICE_SPEAKER_CHECK`` line per task with issues; nothing here raises.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.voice_speaker_consistency.v1"
_AUDIO_REF = re.compile(r"@Audio(\d+)\b")


def _voice_gender_module():
    try:
        import voice_gender as module  # type: ignore
        return module
    except ModuleNotFoundError:
        runtime_tools = Path(__file__).resolve().parents[1] / "lines/nalu/runtime/tools"
        if runtime_tools.is_dir() and str(runtime_tools) not in sys.path:
            sys.path.append(str(runtime_tools))
        try:
            import voice_gender as module  # type: ignore
            return module
        except ModuleNotFoundError:  # pragma: no cover
            return None


def _registry_rows(registry_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if registry_rows is not None:
        return [r for r in registry_rows if isinstance(r, dict)]
    path = os.environ.get("QINGSHAN_VOICE_REGISTRY", "").strip()
    if not path or not Path(path).is_file():
        return []
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8")).get("major_roles") or []
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _visible_ids(spec: dict[str, Any]) -> set[str]:
    return {str(m.get("character_id") or "") for m in spec.get("cast") or []
            if isinstance(m, dict) and str(m.get("face_visibility") or "").upper() != "OFFSCREEN_VOICE_ONLY"}


def check_task(task: dict[str, Any], prompt_text: str, *, registry_rows: list[dict[str, Any]] | None = None
               ) -> dict[str, Any]:
    machine = task.get("machine_contract") or {}
    contract = task.get("speaker_voice_contract") or machine.get("speaker_voice_contract") or {}
    bindings = [b for b in contract.get("bindings") or [] if isinstance(b, dict)]
    base = {"schema": SCHEMA, "task_key": task.get("task_key"), "unit_id": task.get("unit_id")}
    if not bindings:
        return {**base, "status": "NOT_APPLICABLE", "issues": []}
    issues: list[str] = []
    is_h3 = str(task.get("model") or "").lower() in {"minimax-h3", "h3"}
    if is_h3:
        urls = list(task.get("reference_audio_urls") or [])
        expected = [str(b.get("voice_reference_url") or "") for b in bindings]
        slots = [str(b.get("audio_slot") or "") for b in bindings]
        if urls != expected or slots != [f"@音频{i}" for i in range(1, len(bindings) + 1)]:
            issues.append("AUDIO_SLOT_ORDER_MISMATCH")
        named = {int(n) for n in _AUDIO_REF.findall(prompt_text or "")}
        sent = set(range(1, len(urls) + 1))
        if named - sent or (named and sent - named):
            issues.append(f"PROMPT_AUDIO_SLOT_UNBOUND:named={sorted(named)}:sent={sorted(sent)}")
    rows = _registry_rows(registry_rows)
    by_url = {str(r.get("remote_url")): r for r in rows if r.get("remote_url")}
    by_asset = {str(r.get("remote_asset_id")): r for r in rows if r.get("remote_asset_id")}
    entities = {str(r.get("character_id") or ""): r for r in machine.get("character_entities")
                or task.get("character_entities") or [] if isinstance(r, dict)}
    vg = _voice_gender_module()
    for b in bindings:
        cid = str(b.get("character_id") or "")
        row = by_url.get(str(b.get("voice_reference_url") or "")) or by_asset.get(str(b.get("voice_reference_asset_id") or ""))
        if not row:
            continue
        owner = str(row.get("character_id") or "")
        if owner and cid and owner.lower() != cid.lower() and owner.lower() not in (vg.entity_keys(cid) if vg else []):
            issues.append(f"VOICE_REF_OF_ANOTHER_CHARACTER:{b.get('speaker')}:{owner}")
        if vg is not None and cid in entities:
            ch = vg.character_gender(entities[cid])
            voice = vg.voice_gender(row.get("voice_id") or row.get("generation_voice_id"),
                                    voice_name=row.get("voice_name"), row=row, f0=row.get("reference_f0_hz"))
            if vg.casting_check(ch, voice)["status"] == vg.MISMATCH:
                issues.append(f"VOICE_GENDER_CONTRADICTS_SPEAKER:{b.get('speaker')}:{ch['gender']}:"
                              f"{voice['gender']}:{voice.get('voice_id')}")
    offscreen_marked = "offscreen" in (prompt_text or "").lower() or "画外" in (prompt_text or "")
    for spec in machine.get("ordered_prompt_specs") or []:
        if not isinstance(spec, dict) or not str(spec.get("dialogue") or "").strip():
            continue
        role = spec.get("role_semantic_disambiguation") or {}
        speaker = str(role.get("dialogue_speaker_id") or "")
        if speaker and speaker not in _visible_ids(spec) and not offscreen_marked:
            issues.append(f"OFFSCREEN_SPEAKER_NOT_MARKED:{spec.get('shot_id') or '?'}:{speaker}")
    return {**base, "status": "ADVISORY" if issues else "PASS", "issues": issues}


def advise(task: dict[str, Any], prompt_text: str, *, stream=None) -> dict[str, Any]:
    """check_task, printing one VOICE_SPEAKER_CHECK line when it finds anything; never raises."""
    try:
        report = check_task(task, prompt_text)
    except Exception as exc:  # noqa: BLE001 - advisory
        return {"schema": SCHEMA, "status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if report.get("issues"):
        print(f"VOICE_SPEAKER_CHECK {report.get('task_key')} {report['status']} " + ";".join(report["issues"]),
              file=stream or sys.stderr)
    return report
