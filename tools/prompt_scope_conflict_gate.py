#!/usr/bin/env python3
"""Submit-boundary conflict gate for the shot-scope upgrade (PROMPT_SHOT_SCOPE_POLICY_V1).

Checks the FINAL serialized provider prompt together with the task's machine contract,
right before a paid POST, for three classes of scope conflict:

(a) an entity is a visible-lip speaker and face/mouth-forbidden in the same beat;
(b) a partial-visibility clause ("only X's hands in frame", "do not reveal X's face",
    不露脸 / 只露手 / 脸出画 ...) appears outside the beat(s) where that entity is declared
    partial, attaches to a normal (non-partial) entity, or names no entity at all
    ("its face", "the face");
(c) a LOCKED/STATIC camera beat carries a move instruction in its own camera line
    ("execute the declared move once", 横移, 推近 ...).

The result is bound to the exact prompt bytes and the ordered reference SHA list
(``checked_sha256``); a changed request must be checked again.  Whether the gate applies is
decided by ``tools.prompt_shot_scope_policy.active_for`` -- this module only checks.

``loaded_module_audit`` records the file path and sha256 of the renderer/gate modules that
are actually loaded (``sys.modules[name].__file__``), so a local overlay is visible as a
different path or sha.  Paths outside the engine root are written as ``<external>``.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "qingshan.prompt_scope_conflict_gate.v1"
ENGINE_ROOT = Path(__file__).resolve().parents[1]

# Modules whose loaded file is audited when present in sys.modules (bare and tools.-prefixed).
AUDITED_MODULES = (
    "prompt_scope_conflict_gate",
    "prompt_shot_scope_policy",
    "submit_giggle_video_manifest_v2",
    "sd2_provider_prompt_renderer",
    "sd2_shot_camera_adapter",
    "h3_provider_prompt_renderer",
    "giggle_api_client",
)

_LOCKED_FAMILIES = {"LOCKED", "STATIC"}
_OFFSCREEN_VALUES = {"OFFSCREEN_VOICE_ONLY", "OFFSCREEN", "OFFSCREEN_VOICE"}
_BODY_PARTS = {
    "HAND", "HANDS", "PAW", "PAWS", "ARM", "ARMS", "LEG", "LEGS", "FOOT", "FEET",
    "TAIL", "BACK", "TORSO", "SHOULDER", "SHOULDERS",
}
_PART_ONLY = re.compile(r"([A-Z]+(?:_AND_[A-Z]+)*)_ONLY(?:_FACE_OUT_OF_FRAME)?")
_FACE_HIDDEN_MARKERS = ("FACE_OUT_OF_FRAME", "FACE_HIDDEN", "FACE_FORBIDDEN", "NO_FACE", "HIDDEN_BEHIND")
_VISIBILITY_FIELDS = ("visible_body_range", "visible_extent", "face_visibility")
_SILENT_PREFIXES = ("闭口", "全程闭口", "保持闭口", "不得张口", "不可张口", "不说话", "silent")

# Quoted dialogue literals never carry staging instructions.
_QUOTED = re.compile(r"“[^”]*”|「[^」]*」|<d>.*?</d>", re.DOTALL)
_FRAGMENT_SPLIT = re.compile(r"[。；;\n]|\.(?=\s|$)")

_PARTIAL_PATTERNS = [
    re.compile(
        r"不露脸|不露面|不露正脸|不得露脸|禁止露脸|不露出(?:脸|面部|正脸|五官)|不拍(?:到)?脸"
        r"|(?:脸|面部|正脸)(?:部)?(?:出画|在画外|不入画)"
        r"|(?:只|仅)(?:露|见|入画)(?:出)?(?:一只|一双|双|单)?(?:手臂|胳膊|手|爪|臂|腿|脚|足|尾|背影|背|肩)"
    ),
    re.compile(
        r"cropped body parts"
        r"|\bdo not (?:widen the frame to )?(?:reveal|show)\b[^.;。；]{0,60}?\b(?:face|full body)\b"
        r"|\bnever (?:reveal|show)\b[^.;。；]{0,60}?\bface\b"
        r"|\bface (?:stays |remains |is |kept )?(?:out of|outside(?: of)?|off)[ -](?:the )?(?:frame|shot|screen)"
        r"|\b(?:only|just)\b[^.;。；]{0,40}?\b(?:hands?|paws?|arms?|legs?|feet|foot|tail|back|torso|shoulders?)\b"
        r"[^.;。；]{0,20}?\b(?:in frame|in shot|visible|in view)"
        r"|\b(?:hands?|paws?|arms?|legs?)[- ]only\b",
        re.IGNORECASE,
    ),
]
_PRONOUN_FACE = re.compile(r"\b(?:its|their|his|her|the)\s+(?:face|full body)\b|(?:它|他|她|其)的?(?:脸|面部)", re.IGNORECASE)
_GENERIC_QUANTIFIER = re.compile(r"其余|其他|其它|所有|全部|\bother\b|\bothers\b|\beveryone\b|\ball\b", re.IGNORECASE)
_MOUTH_FORBID = re.compile(
    r"闭口|不开口|不张嘴|不说话|嘴(?:唇)?(?:紧闭|闭合)"
    r"|\bmouths? (?:stays? |remains? |kept )?closed\b|\bdoes not speak\b",
    re.IGNORECASE,
)

_NEGATION = [
    re.compile(r"(?:禁止|严禁|不得|不要|不可|不能|不会|避免|无|勿|不)[^，。；;,.\n]*"),
    re.compile(r"\b(?:no|not|never|without|avoid|forbid(?:den)?|don't|do not)\b[^,.;\n]*", re.IGNORECASE),
]
_MOVE_PATTERNS = [
    re.compile(
        r"仅?执行一次|移动|横移|推近|推进|推镜|拉远|拉开|拉镜|摇镜|横摇|纵摇|升降|跟拍|跟随|环绕"
        r"|推轨|移镜|慢推|甩镜|变焦|摇臂|旋转镜头"
    ),
    re.compile(
        r"execute the declared move|\bmove (?:once|lands)\b|\bone (?:short|motivated) \w+"
        r"|\b(?:dolly|dollies|pan|pans|panning|truck|trucking|track|tracking|tilt|tilts|crane|arc|orbit"
        r"|zoom|whip|push(?:es)?[- ]in|pull(?:s)?[- ](?:out|back))\b"
        r"|\bcamera (?:moves|follows|drifts)\b|\bfollows?\b",
        re.IGNORECASE,
    ),
]
_FRAMING_VALUE = re.compile(r"((?:hold the framing|start framing|end framing)\s*:)[^;\n]*", re.IGNORECASE)
_ZH_FRAMING_VALUE = re.compile(r"(起始)[^；;\n]*|(运镜动机：)[^；;。\n]*")
_CAMERA_FREE_TEXT_FIELDS = (
    "start_framing", "end_framing", "motivation", "axis_relation", "lens_intent",
    "follow_subject", "subject_to_keep", "start_framing_en", "end_framing_en",
)
_CAMERA_SECTION_START = re.compile(r"^\s*(?:【摄影】|camera\s*:)", re.IGNORECASE)
_SECTION_HEADER = re.compile(r"^\s*(?:【[^】]+】|[a-z_]+\s*:)", re.IGNORECASE)
_SHOT_ORDINAL = re.compile(r"^\s*SHOT\s+(\d+)\b")
_H3_BEAT_LINE = re.compile(r"^\s*\[(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s\]\s*Start from ")
_SD2_BEAT_LINE = re.compile(r"^\s*(\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)秒：从")
_WINDOWS = (
    re.compile(r"\[(\d+(?:\.\d+)?)s-(\d+(?:\.\d+)?)s\]"),
    re.compile(r"(\d+(?:\.\d+)?)[–-](\d+(?:\.\d+)?)秒"),
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _machine(task: dict[str, Any], key: str, default: Any = None) -> Any:
    machine = task.get("machine_contract") or {}
    value = machine.get(key)
    if value in (None, "", [], {}):
        value = task.get(key)
    return default if value in (None, "", [], {}) else value


def checked_sha256(prompt_bytes: bytes, reference_sha256: Iterable[str]) -> str:
    """The binding hash: exact prompt bytes + ordered reference SHA list."""
    digest = hashlib.sha256()
    digest.update(prompt_bytes)
    digest.update(b"\n--references--\n")
    digest.update(json.dumps([str(v) for v in reference_sha256], separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Machine contract projection
# ---------------------------------------------------------------------------

def _entity_names(task: dict[str, Any], specs: list[dict[str, Any]]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}

    def add(cid: Any, *labels: Any) -> None:
        cid = _clean(cid)
        if not cid:
            return
        bucket = names.setdefault(cid, {cid})
        for label in labels:
            if isinstance(label, (list, tuple)):
                for item in label:
                    add(cid, item)
            elif _clean(label):
                bucket.add(_clean(label))

    for row in _machine(task, "character_entities", []) or []:
        if isinstance(row, dict):
            add(row.get("character_id") or row.get("entity_id"), row.get("canonical_name"),
                row.get("provider_entity_label"), list(row.get("aliases") or []))
    for row in [
        *(((_machine(task, "provider_scope_projection", {}) or {}).get("reference_identity_bindings")) or []),
        *(task.get("reference_image_sequence") or []),
    ]:
        if isinstance(row, dict):
            add(row.get("entity_id") or row.get("character_id"), row.get("provider_entity_label"))
    token_map = task.get("provider_entity_token_map") or {}
    if isinstance(token_map, dict):
        for key, value in token_map.items():
            if isinstance(value, dict):
                add(key, value.get("token"), value.get("provider_entity_label"), value.get("label"))
            elif _clean(key) in names:
                add(key, value)
            elif _clean(value) in names:
                add(value, key)
    voice = _machine(task, "speaker_voice_contract", {}) or {}
    for row in voice.get("bindings") or []:
        if isinstance(row, dict) and row.get("character_id"):
            add(row["character_id"], row.get("speaker"), row.get("provider_entity_label"))
    for spec in specs:
        for cast in spec.get("cast") or []:
            if isinstance(cast, dict) and cast.get("character_id"):
                add(cast["character_id"], cast.get("character"))
        role = spec.get("role_semantic_disambiguation") or {}
        for name_field, id_field in (("dialogue_speaker", "dialogue_speaker_id"),
                                     ("primary_actor", "primary_actor_id"),
                                     ("dialogue_listener", "dialogue_listener_id")):
            if role.get(id_field):
                add(role[id_field], role.get(name_field))
    return names


def _resolve(name: Any, names: dict[str, set[str]]) -> str | None:
    value = _clean(name)
    if not value:
        return None
    for cid, labels in names.items():
        if value in labels:
            return cid
    return None


def _visibility_kind(value: Any) -> str | None:
    """PARTIAL / OFFSCREEN / None (normal or undeclared -- never read as face-forbidden)."""
    raw = _clean(value).upper()
    if not raw:
        return None
    if raw in _OFFSCREEN_VALUES:
        return "OFFSCREEN"
    match = _PART_ONLY.fullmatch(raw)
    if match and any(token in _BODY_PARTS for token in match.group(1).split("_AND_")):
        return "PARTIAL"
    if any(marker in raw for marker in _FACE_HIDDEN_MARKERS):
        return "PARTIAL"
    return None


def _beat_windows(specs: list[dict[str, Any]]) -> list[list[tuple[float, float]]]:
    raw: list[tuple[float, float] | None] = []
    for spec in specs:
        action = spec.get("action") or {}
        start = action.get("t0_seconds", spec.get("start_seconds"))
        end = action.get("t1_seconds", spec.get("end_seconds"))
        try:
            raw.append((float(start), float(end)))
        except (TypeError, ValueError):
            raw.append(None)
    origin = raw[0][0] if raw and raw[0] else 0.0
    result = []
    for window in raw:
        if window is None:
            result.append([])
        else:
            result.append(list(dict.fromkeys([window, (round(window[0] - origin, 6), round(window[1] - origin, 6))])))
    return result


def _beat_contracts(task: dict[str, Any], specs: list[dict[str, Any]], names: dict[str, set[str]]) -> list[dict[str, Any]]:
    voice = _machine(task, "speaker_voice_contract", {}) or {}
    bindings = [row for row in voice.get("bindings") or [] if isinstance(row, dict)]
    projection_beats = (_machine(task, "provider_scope_projection", {}) or {}).get("beats") or []
    if len(projection_beats) != len(specs):
        projection_beats = []
    unit_camera = _machine(task, "camera_plan")
    per_shot = _machine(task, "per_shot_camera_plans", []) or []
    per_shot_by_id = {
        _clean(row.get("shot_id")): row for row in per_shot if isinstance(row, dict) and row.get("shot_id")
    }
    beats = []
    for index, spec in enumerate(specs):
        role = spec.get("role_semantic_disambiguation") or {}
        declared: dict[str, str] = {}

        def declare(cid: Any, value: Any) -> None:
            cid = _resolve(cid, names) or _clean(cid)
            kind = _visibility_kind(value)
            if cid and kind and cid not in declared:
                declared[cid] = kind

        for cid, value in (role.get("entity_visible_extent") or {}).items():
            declare(cid, value)
        for cid, value in (role.get("entity_face_visibility") or {}).items():
            declare(cid, value)
        for cid, value in (role.get("entity_presence") or {}).items():
            declare(cid, value)
        for cast in spec.get("cast") or []:
            if not isinstance(cast, dict):
                continue
            cid = cast.get("character_id") or _resolve(cast.get("character"), names) or cast.get("character")
            for field in _VISIBILITY_FIELDS:
                if cast.get(field):
                    declare(cid, cast[field])
        if projection_beats:
            for row in projection_beats[index].get("entities") or []:
                if isinstance(row, dict) and row.get("entity_id"):
                    declare(row["entity_id"], row.get("visible_extent") or row.get("face_visibility"))

        speakers: set[str] = set()
        presence = role.get("entity_presence") or {}
        speaker_id = _clean(role.get("dialogue_speaker_id"))
        if speaker_id and _clean(presence.get(speaker_id)).upper() not in _OFFSCREEN_VALUES:
            speakers.add(speaker_id)
        if _clean(role.get("lip_owner_id")):
            speakers.add(_clean(role["lip_owner_id"]))
        dialogue = _clean(spec.get("dialogue"))
        if dialogue:
            speaker_name = dialogue.partition("：")[0].strip()
            cid = _resolve(speaker_name, names)
            binding = next((row for row in bindings if _clean(row.get("speaker")) == speaker_name
                            or (cid and _clean(row.get("character_id")) == cid)), None)
            if binding is not None and (binding.get("visible_speaker") or binding.get("lip_sync")):
                speakers.add(_clean(binding.get("character_id")) or cid or speaker_name)
        mouth_forbidden = {
            _resolve(cid, names) or _clean(cid)
            for cid, state in (role.get("entity_states") or {}).items()
            if any(_clean(state).lower().startswith(prefix) for prefix in _SILENT_PREFIXES)
        }
        camera = spec.get("camera_plan")
        if not isinstance(camera, dict):
            camera = per_shot_by_id.get(_clean(spec.get("shot_id")))
            if camera is None and len(per_shot) == len(specs) and isinstance(per_shot[index], dict):
                camera = per_shot[index]
            if isinstance(camera, dict) and isinstance(camera.get("camera_plan"), dict):
                camera = camera["camera_plan"]
        unit_scoped_camera = False
        if not isinstance(camera, dict) and isinstance(unit_camera, dict):
            camera, unit_scoped_camera = unit_camera, True
        beats.append({
            "beat_index": index + 1,
            "shot_id": _clean(spec.get("shot_id")),
            "declared": declared,
            "face_forbidden": set(declared),
            "speakers": {value for value in speakers if value},
            "mouth_forbidden": {value for value in mouth_forbidden if value},
            "camera_plan": camera if isinstance(camera, dict) else None,
            "unit_scoped_camera": unit_scoped_camera,
        })
    if not specs and isinstance(unit_camera, dict):
        beats.append({"beat_index": 1, "shot_id": "", "declared": {}, "face_forbidden": set(),
                      "speakers": set(), "mouth_forbidden": set(), "camera_plan": unit_camera,
                      "unit_scoped_camera": True})
    return beats


# ---------------------------------------------------------------------------
# Final-text attribution
# ---------------------------------------------------------------------------

def _line_beats(lines: list[str], beats: list[dict[str, Any]], windows: list[list[tuple[float, float]]]) -> list[list[int] | None]:
    """Per line, the beat indexes (0-based) it is scoped to, or None for unit-wide text."""
    shot_to_beats: dict[str, list[int]] = {}
    for index, beat in enumerate(beats):
        if beat["shot_id"]:
            shot_to_beats.setdefault(beat["shot_id"], []).append(index)
    beat_line_indexes = [i for i, line in enumerate(lines) if _H3_BEAT_LINE.match(line) or _SD2_BEAT_LINE.match(line)]
    ordinal = {line_index: [n] for n, line_index in enumerate(beat_line_indexes)} if len(beat_line_indexes) == len(beats) else {}
    result: list[list[int] | None] = []
    for i, line in enumerate(lines):
        mentioned = [shot for shot in shot_to_beats if shot and shot in line]
        if mentioned:
            # longest id wins when ids are prefixes of each other
            longest = max(mentioned, key=len)
            result.append(list(shot_to_beats[longest]))
            continue
        if i in ordinal:
            result.append(ordinal[i])
            continue
        hit: list[int] | None = None
        for pattern in _WINDOWS:
            match = pattern.search(line)
            if not match:
                continue
            window = (float(match.group(1)), float(match.group(2)))
            found = [n for n, options in enumerate(windows)
                     if any(abs(window[0] - a) < 0.011 and abs(window[1] - b) < 0.011 for a, b in options)]
            if len(found) == 1:
                hit = found
            break
        result.append(hit)
    return result


def _name_spans(text: str, names: dict[str, set[str]]) -> list[tuple[int, int, str]]:
    labels = sorted(((label, cid) for cid, values in names.items() for label in values if label),
                    key=lambda row: -len(row[0]))
    taken: list[tuple[int, int, str]] = []
    for label, cid in labels:
        ascii_label = label.isascii()
        pattern = re.compile((r"(?<![A-Za-z0-9_])" + re.escape(label) + r"(?![A-Za-z0-9_])") if ascii_label else re.escape(label))
        for match in pattern.finditer(text):
            if any(not (match.end() <= s or match.start() >= e) for s, e, _ in taken):
                continue
            taken.append((match.start(), match.end(), cid))
    return sorted(taken)


def _clause_entities(fragment: str, match: re.Match[str], names: dict[str, set[str]]) -> tuple[set[str], bool]:
    """Entities a forbid clause names, and whether it is generic (unnamed)."""
    if _PRONOUN_FACE.search(match.group(0)):
        return set(), True
    spans = _name_spans(fragment, names)
    inside = {cid for s, e, cid in spans if s >= match.start() and e <= match.end()}
    if inside:
        return inside, False
    before = [(s, e, cid) for s, e, cid in spans if e <= match.start()]
    if not before:
        return set(), True
    start, end, cid = before[-1]
    if _GENERIC_QUANTIFIER.search(fragment[end:match.start()]):
        return set(), True
    return {cid}, False


def _strip_negations(text: str) -> str:
    for pattern in _NEGATION:
        text = pattern.sub("", text)
    return text


def _camera_entries(lines: list[str], line_beats: list[list[int] | None], beats: list[dict[str, Any]]) -> tuple[dict[int, list[str]], list[str]]:
    """Per-beat camera entries and unit-wide camera text."""
    per_beat: dict[int, list[str]] = {}
    unit: list[str] = []
    in_section = False
    found_section = False
    for i, line in enumerate(lines):
        if _CAMERA_SECTION_START.match(line):
            in_section, found_section = True, True
        elif in_section and _SECTION_HEADER.match(line) and not _SHOT_ORDINAL.match(line):
            in_section = False
        if not in_section:
            continue
        ordinal = _SHOT_ORDINAL.match(line)
        targets = line_beats[i]
        if ordinal and int(ordinal.group(1)) <= len(beats):
            targets = [int(ordinal.group(1)) - 1]
        if targets:
            for target in targets:
                per_beat.setdefault(target, []).append(line)
        else:
            unit.append(line)
    if not found_section:
        for i, line in enumerate(lines):
            if "机位" in line or re.search(r"\bcamera\b", line, re.IGNORECASE):
                if line_beats[i]:
                    for target in line_beats[i]:
                        per_beat.setdefault(target, []).append(line)
                else:
                    unit.append(line)
    return per_beat, unit


def _move_terms(entry: str, plan: dict[str, Any]) -> list[str]:
    text = _QUOTED.sub("", entry)
    for field in _CAMERA_FREE_TEXT_FIELDS:
        value = _clean(plan.get(field))
        if value:
            text = text.replace(value, "")
    text = _FRAMING_VALUE.sub(r"\1", text)
    text = _ZH_FRAMING_VALUE.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _strip_negations(text)
    terms: list[str] = []
    for pattern in _MOVE_PATTERNS:
        terms.extend(match.group(0) for match in pattern.finditer(text))
    return list(dict.fromkeys(terms))


# ---------------------------------------------------------------------------
# External (renderer-owned) checker, optional
# ---------------------------------------------------------------------------

def _external_partial_clause_leaks(task: dict[str, Any], prompt_text: str) -> tuple[list[str], str]:
    model = _clean(task.get("model")).lower()
    if model not in {"minimax-h3", "h3"}:
        return [], "NOT_APPLICABLE_MODEL"
    module = sys.modules.get("tools.h3_provider_prompt_renderer") or sys.modules.get("h3_provider_prompt_renderer")
    if module is None:
        try:
            from tools import h3_provider_prompt_renderer as module  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001 -- optional collaborator
            try:
                import h3_provider_prompt_renderer as module  # type: ignore[no-redef]
            except Exception:  # noqa: BLE001
                return [], "UNAVAILABLE"
    checker = getattr(module, "partial_clause_leaks", None)
    if not callable(checker):
        return [], "UNAVAILABLE"
    unit = dict(task)
    unit.update({k: v for k, v in (task.get("machine_contract") or {}).items() if v not in (None, "", [], {})})
    plan = task.get("execution_plan") or task.get("provider_execution_plan")
    if not isinstance(plan, dict):
        try:
            try:
                from tools.video_execution_plan_compiler import compile_video_execution_plan
            except ModuleNotFoundError:
                from video_execution_plan_compiler import compile_video_execution_plan
            plan = compile_video_execution_plan(unit)
        except Exception as exc:  # noqa: BLE001 -- the plan is optional evidence here
            return [], f"SKIPPED_PLAN_UNAVAILABLE:{type(exc).__name__}"
    try:
        findings = checker(prompt_text, plan, unit)
    except TypeError:
        findings = checker(prompt_text, plan)
    return [f"H3_RENDERER:{value}" for value in findings or []], "RAN"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_task(task: dict[str, Any], prompt_text: str) -> dict[str, Any]:
    """Check the final serialized prompt against the task's machine contract."""
    prompt_bytes = prompt_text.encode("utf-8")
    reference_sha = [str(v) for v in task.get("reference_sha256") or []]
    specs = [row for row in (_machine(task, "ordered_prompt_specs", []) or []) if isinstance(row, dict)]
    names = _entity_names(task, specs)
    beats = _beat_contracts(task, specs, names)
    failures: list[str] = []

    # (a) contract-level: visible-lip speaker vs face/mouth forbidden in the same beat
    for beat in beats:
        label = f"BEAT.{beat['beat_index']}"
        for cid in sorted(beat["speakers"] & beat["face_forbidden"]):
            failures.append(f"VISIBLE_SPEAKER_FACE_FORBIDDEN:{label}:{cid}:{beat['declared'][cid]}")
        for cid in sorted(beat["speakers"] & beat["mouth_forbidden"]):
            failures.append(f"VISIBLE_SPEAKER_MOUTH_FORBIDDEN:{label}:{cid}")

    stripped = _QUOTED.sub("", prompt_text)
    lines = stripped.splitlines()
    windows = _beat_windows(specs)
    line_beats = _line_beats(lines, beats, windows)

    # (a) text-level + (b) partial-visibility clause scope
    for i, line in enumerate(lines):
        targets = line_beats[i]
        scope = [beats[n] for n in targets] if targets else beats
        where = ",".join(f"BEAT.{beats[n]['beat_index']}" for n in targets) if targets else "UNIT"
        for fragment in _FRAGMENT_SPLIT.split(line):
            if not fragment.strip():
                continue
            for pattern in _PARTIAL_PATTERNS:
                for match in pattern.finditer(fragment):
                    entities, generic = _clause_entities(fragment, match, names)
                    if generic:
                        failures.append(f"PARTIAL_CLAUSE_GENERIC_UNNAMED:{where}:{match.group(0)[:60]}")
                        continue
                    for cid in sorted(entities):
                        if not scope or any(cid not in beat["face_forbidden"] for beat in scope):
                            failures.append(f"PARTIAL_CLAUSE_NOT_DECLARED_PARTIAL:{where}:{cid}")
                        speaking = [beat for beat in scope if cid in beat["speakers"]]
                        if speaking:
                            failures.append(
                                f"PARTIAL_CLAUSE_ON_VISIBLE_SPEAKER:"
                                f"{','.join('BEAT.' + str(b['beat_index']) for b in speaking)}:{cid}"
                            )
            if targets:
                for match in _MOUTH_FORBID.finditer(fragment):
                    head = fragment[max(0, match.start() - 8):match.start()]
                    if _GENERIC_QUANTIFIER.search(head):
                        continue
                    spans = [span for span in _name_spans(fragment, names)
                             if span[1] <= match.start() and match.start() - span[1] <= 4]
                    for _, _, cid in spans[-1:]:
                        speaking = [beat for beat in scope if cid in beat["speakers"]]
                        if speaking:
                            failures.append(
                                f"VISIBLE_SPEAKER_MOUTH_FORBIDDEN_IN_TEXT:"
                                f"{','.join('BEAT.' + str(b['beat_index']) for b in speaking)}:{cid}"
                            )

    # (c) LOCKED/STATIC beat camera line carries no move instruction
    per_beat, unit_entries = _camera_entries(lines, line_beats, beats)
    for index, beat in enumerate(beats):
        plan = beat["camera_plan"]
        if not plan or _clean(plan.get("motion_family") or "STATIC").upper() not in _LOCKED_FAMILIES:
            continue
        # A beat's camera text = its own per-shot entry plus the unit-wide camera text
        # (which applies to every beat).  Another beat's per-shot entry never counts.
        entries = [*per_beat.get(index, []), *unit_entries]
        label = "UNIT" if beat["unit_scoped_camera"] else f"BEAT.{beat['beat_index']}"
        for entry in entries:
            for term in _move_terms(entry, plan):
                failures.append(f"LOCKED_CAMERA_MOVE_INSTRUCTION:{label}:{term}")

    external, external_status = _external_partial_clause_leaks(task, prompt_text)
    failures.extend(external)
    failures = list(dict.fromkeys(failures))
    return {
        "schema": SCHEMA,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "checked_sha256": checked_sha256(prompt_bytes, reference_sha),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "reference_sha256": reference_sha,
        "beat_count": len(beats),
        "external_partial_clause_checker": external_status,
    }


def _sha_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def loaded_module_audit(engine_root: Path | None = None, extra: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Path + sha256 of every audited module actually loaded in this process."""
    root = (engine_root or ENGINE_ROOT).resolve()
    wanted = []
    for base in (*AUDITED_MODULES, *extra):
        wanted.extend([base, f"tools.{base}"] if not base.startswith("tools.") and base != "__main__" else [base])
    rows = []
    seen = set()
    for name in dict.fromkeys(wanted):
        module = sys.modules.get(name)
        file = getattr(module, "__file__", None) if module is not None else None
        if not file:
            continue
        path = Path(file).resolve()
        key = (name, str(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            shown = path.relative_to(root).as_posix()
        except ValueError:
            shown = "<external>"
        rows.append({"module": name, "path": shown, "sha256": _sha_file(path)})
    return rows
