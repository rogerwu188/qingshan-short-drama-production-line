#!/usr/bin/env python3
"""BILI_V1 craft ledger (CHANGE_SPEC WP6, from the Bilibili ep3 benchmark): setups / payoffs across episodes,
who-knows-what (dramatic irony), signature business per main character, mirrored scenes, object-first entrances
and at most three dedicated insert units per episode.

Owner 2026-11-23: ep3 was better than ep2 because of *structure* details -- a misunderstanding chain the audience
sees through, >= 7 setup -> payoff threads (two of them calling back to ep2, one hook for ep4), a hero whose turn is
played in silence, recurring business (摸后颈 x3), mirrored compositions (two arrivals, two finger-counts) and props /
feet / wheels shown before faces.  This module encodes those as contract fields and free, deterministic checks.

Everything here is BILI_V1-only: the pipeline (S1 ``s1_script_pacing``) and the Codex start prompt call it only when
``craft_profile.is_bili_v1`` is true, so a LEGACY series is byte-identical.

Contract fields (``generation_contract.schema.json``, additive; the WP2 screenplay compiler emits the same fields
from YAML blocks -- :func:`screenplay_fields` / :func:`apply_fields`):

* ``ledger: [{id, kind: SETUP|PAYOFF|CALLBACK|HOOK, thread, shot_id, pays_off, from_episode, prop?}]``
  (a row may give ``scene_id`` + ``anchor`` -- a fragment of the line / action text -- instead of ``shot_id``);
* ``knowledge: [{scene_id, who, knows|believes|unaware: fact}]`` (or ``{who, type, fact, hidden_from}``);
* ``series_card: {characters: [{character_id, name, signature_business, signature_prop, cues, main}]}`` (or the
  runtime ``qingshan.json`` ``series_card`` block, or ``SERIES_CARD.yaml|json`` beside the scripts / the ledger);
* ``pacing.scene_plan[].mirror_of``, ``.time_of_day``, ``.light`` / ``.weather``, ``.set_pieces``, ``.turn_shot_id``,
  ``.turn_owner``;
* shot ``prompt_spec.beat_role`` (enum :data:`BEAT_ROLES`), ``prompt_spec.object_first {subject, of, then}``,
  ``prompt_spec.signature_business`` (character id / list), ``prompt_spec.double_meaning``.

Checks (codes; tiers):

* GRADUATED -- advisory for the first :data:`ADVISORY_EPISODES` episodes of a series (counted in the series
  ledger), then taste failures in the SHORT_DRAMA_PACING_V1 revision loop (bounded rounds, then admitted -- never
  stalls the line): ``LEDGER_THIN``, ``LEDGER_PAYOFF_UNRESOLVED``, ``LEDGER_SHOT_UNKNOWN``,
  ``SIGNATURE_CARD_MISSING``, ``SIGNATURE_BUSINESS_UNUSED``, ``SIGNATURE_BUSINESS_OVERUSED``;
* TASTE (from the first BILI_V1 episode; cost control): ``INSERT_OVER``, ``INSERT_WITHOUT_LEDGER_PROP``;
* ADVISORY (warnings only): ``NO_IRONY``, ``KNOWLEDGE_UNKNOWN_SCENE``, ``TURN_TALKED``, ``NO_TIME_PLACE``,
  ``MIRROR_UNRESOLVED``, ``MIRROR_SETUP_DIFFERS``, ``OBJECT_FIRST_NONE``, ``OBJECT_FIRST_FACE_SHOWN``.

Series ledger: ``<runtime>/sources/<series>/LEDGER.json`` (``<runtime>/series/LEDGER.json`` when the series has no
sources folder), appended when S1 admits the script (like ``SOURCE_COVERAGE.json``).

Cost: 0 credits; each dedicated insert unit is one ~4 s H3 unit (~4.4 credits), at most 3 (~+13) and only if used.

Stdlib only; never raises from the pipeline entry points.  Docs: ``docs/knowledge/CRAFT_LEDGER.md``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

SCHEMA = "nalu.craft_ledger_check.v1"
LEDGER_SCHEMA = "nalu.series_ledger.v1"
#: owner 2026-11-23: the ledger is advisory for the first three episodes of a series, then required
ADVISORY_EPISODES = 3
LEDGER_KINDS = ("SETUP", "PAYOFF", "CALLBACK", "HOOK")
KNOWLEDGE_TYPES = ("KNOWS", "BELIEVES", "UNAWARE")
AUDIENCE = "AUDIENCE"
#: shot ``prompt_spec.beat_role`` values (shared with WP1 / WP3; the historical three come first)
BEAT_ROLES = ("SETUP", "PAYOFF", "REACTION", "LINE", "REVEAL", "TURN", "ATTACK", "PUNCHLINE", "ENDING",
              "MUSIC_PASSAGE", "SILENCE", "INSERT", "TRANSITION")
OBJECT_FIRST_SUBJECTS = ("HANDS", "FEET", "PROP", "WHEELS", "VEHICLE", "SCREEN")
#: camera continuations of an object-first entrance: INSERT = the whole unit stays on the detail (faceless)
OBJECT_FIRST_THEN = ("INSERT", "TILT_UP", "PUSH_IN", "PAN", "RACK_FOCUS")
MIN_SETUPS = 2
MIN_PAYOFFS = 2
MIN_CALLBACKS = 1
MIN_HOOKS = 1
HOOK_WINDOW_SECONDS = 10.0
SIGNATURE_MIN_USES = 1
SIGNATURE_MAX_USES = 3
TURN_OWNER_MAX_LINES = 2
INSERT_MAX = 3
UNIT_FLOOR_SECONDS = 4.0
H3_CREDITS_PER_SECOND = 1.09
#: the zero-cost alternative to a dedicated insert unit (L4 hook, WP3 director pass)
INSERT_ALTERNATIVE_EN = "foreground hands / object in sharp focus, the face soft behind"

GRADUATED_CODES = frozenset({"LEDGER_THIN", "LEDGER_PAYOFF_UNRESOLVED", "LEDGER_SHOT_UNKNOWN",
                             "SIGNATURE_CARD_MISSING", "SIGNATURE_BUSINESS_UNUSED", "SIGNATURE_BUSINESS_OVERUSED"})
TASTE_CODES = frozenset({"INSERT_OVER", "INSERT_WITHOUT_LEDGER_PROP"})
ADVISORY_CODES = frozenset({"NO_IRONY", "KNOWLEDGE_UNKNOWN_SCENE", "TURN_TALKED", "NO_TIME_PLACE",
                            "MIRROR_UNRESOLVED", "MIRROR_SETUP_DIFFERS", "OBJECT_FIRST_NONE",
                            "OBJECT_FIRST_FACE_SHOWN"})

FIXES = {
    "LEDGER_THIN": "write the episode's ledger: >= 2 SETUP and >= 2 PAYOFF rows (id, kind, thread, shot_id), >= 1 "
                   "CALLBACK to an earlier episode (from_episode) and one HOOK on a shot in the last 10 s; plant a "
                   "prop / line / gesture early and pay it off later on screen",
    "LEDGER_PAYOFF_UNRESOLVED": "every PAYOFF's pays_off must name a SETUP (or an earlier HOOK) of this episode or of "
                                "the series ledger (`craft_ledger.py open` lists the open ones); qualify old ids as "
                                "E02:<id>",
    "LEDGER_SHOT_UNKNOWN": "a ledger row points at a shot that does not exist: use the shot_id, or scene_id + an "
                           "anchor fragment of the line / action text",
    "SIGNATURE_CARD_MISSING": "write the series card once (series_card / SERIES_CARD.yaml): per main character one "
                              "signature_business (a recurring tic: rubs the back of the neck) and one signature_prop",
    "SIGNATURE_BUSINESS_UNUSED": "let each main character do their signature business 1-3 times this episode, with "
                                 "the same meaning each time (in the action text, or prompt_spec.signature_business)",
    "SIGNATURE_BUSINESS_OVERUSED": "use the signature business at most 3 times per episode -- it is a tell, not a tic "
                                   "on every line",
    "INSERT_OVER": "at most 3 dedicated insert units per episode (each costs a ~4 s unit); for the rest use a unit "
                   "with the hands / object sharp in the foreground and the face soft behind",
    "INSERT_WITHOUT_LEDGER_PROP": "a dedicated insert shows only a prop that is planted or paid off in the ledger "
                                  "(give the row a prop, or the insert the ledger prop)",
    "NO_IRONY": "give the audience one thing a character does not know: a knowledge row with believes (a false "
                "belief) / unaware, or a line that means two things (double_meaning: true)",
    "KNOWLEDGE_UNKNOWN_SCENE": "knowledge rows name a scene_id of this episode",
    "TURN_TALKED": "the character who owns the scene's turn speaks <= 2 lines in that scene and the turn shot is "
                   "played with an action or a reaction, not explained",
    "NO_TIME_PLACE": "each scene card gives time of day, weather / light and >= 1 usable set piece",
    "MIRROR_UNRESOLVED": "mirror_of names an earlier scene of this episode or E<nn>-S<nn> of an earlier episode",
    "MIRROR_SETUP_DIFFERS": "a mirrored scene reuses the mirrored scene's camera setup (scale / height / side) so "
                            "the audience reads the contrast",
    "OBJECT_FIRST_NONE": "open one important entrance on hands / feet / the prop / wheels before the face "
                         "(prompt_spec.object_first, cast visible_body_range HANDS_ONLY / FEET_ONLY)",
    "OBJECT_FIRST_FACE_SHOWN": "an object-first insert shows no face: declare each cast member's visible_body_range "
                               "(HANDS_ONLY / FEET_ONLY), or set object_first.then to TILT_UP / PUSH_IN with a "
                               "start_framing on the detail",
}

_KIND_ALIASES = {
    "SETUP": "SETUP", "PLANT": "SETUP", "埋": "SETUP", "伏笔": "SETUP", "埋点": "SETUP", "铺垫": "SETUP",
    "PAYOFF": "PAYOFF", "PAY_OFF": "PAYOFF", "收": "PAYOFF", "回收": "PAYOFF",
    "CALLBACK": "CALLBACK", "CALL_BACK": "CALLBACK", "回扣": "CALLBACK",
    "HOOK": "HOOK", "CLIFFHANGER": "HOOK", "钩": "HOOK", "挂钩": "HOOK", "钩子": "HOOK",
}
_CUE_SPLIT = re.compile(r"[、，,;；/|]+")
_EP_NUM = re.compile(r"E(\d+)", re.IGNORECASE)
_SCENE_EP = re.compile(r"^(E\d+)[-:/]", re.IGNORECASE)
_PARTIAL = re.compile(r"_ONLY\b|FACE_OUT_OF_FRAME|OFFSCREEN|BACK_OF_(?:THE_)?HEAD|OTS", re.IGNORECASE)


# --------------------------------------------------------------------------- siblings
def _sibling(name: str) -> Any:
    """A module of this tools directory, imported by name or (when only loaded by path) from the file."""
    try:
        if str(_HERE) not in sys.path:
            sys.path.insert(0, str(_HERE))
        return __import__(name)
    except ImportError:
        spec = importlib.util.spec_from_file_location(f"_craft_ledger_{name}", _HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module


def _pace() -> Any:
    return _sibling("script_pacing_check")


def _cp() -> Any:
    try:
        from tools import craft_profile as module  # type: ignore
        return module
    except ModuleNotFoundError:
        return _sibling("craft_profile")


# --------------------------------------------------------------------------- small helpers
def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _key(value: Any) -> str:
    return re.sub(r"\s+", "", _clean(value)).lower()


def _upper(value: Any) -> str:
    return _clean(value).upper().replace("-", "_").replace(" ", "_")


def episode_number(value: Any) -> int | None:
    m = _EP_NUM.search(_clean(value))
    return int(m.group(1)) if m else None


def _list(value: Any) -> list[Any]:
    if value in (None, "", {}):
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _spec(shot: dict[str, Any]) -> dict[str, Any]:
    return shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}


def _camera_plan(shot: dict[str, Any]) -> dict[str, Any]:
    spec = _spec(shot)
    for plan in (spec.get("camera_plan"), shot.get("camera_plan")):
        if isinstance(plan, dict):
            return plan
    return {}


# --------------------------------------------------------------------------- light YAML (screenplay blocks)
class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _split_key(text: str) -> tuple[str, str] | None:
    """``key: value`` / ``key:`` outside quotes and brackets -> (key, value); None when not a mapping line."""
    depth, quote = 0, ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch in ":：" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t"):
            key = text[:i].strip().strip("\"'")
            return (key, text[i + 1:].strip()) if key else None
    return None


def _scalar(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    if text[0] in "[{":
        value, rest = _flow(text, 0)
        if text[rest:].strip():
            raise YamlError(f"trailing text after flow value: {text[:40]}")
        return value
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    low = text.lower()
    if low in ("null", "~", "none"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d*", text):
        return float(text)
    return text


def _flow(text: str, i: int) -> tuple[Any, int]:
    """One flow value at ``text[i]`` -> (value, next index)."""
    while i < len(text) and text[i] in " \t":
        i += 1
    if i >= len(text):
        return None, i
    ch = text[i]
    if ch in "[{":
        close = "]" if ch == "[" else "}"
        out: Any = [] if ch == "[" else {}
        i += 1
        while True:
            while i < len(text) and text[i] in " \t,":
                i += 1
            if i >= len(text):
                raise YamlError("unclosed flow collection")
            if text[i] == close:
                return out, i + 1
            if ch == "[":
                value, i = _flow(text, i)
                out.append(value)
            else:
                key, i = _flow_plain(text, i, ":：")
                if i < len(text) and text[i] in ":：":
                    value, i = _flow(text, i + 1)
                else:
                    value = None
                out[_clean(key).strip("\"'")] = value
    if ch in "\"'":
        end = text.find(ch, i + 1)
        if end < 0:
            raise YamlError("unclosed quote")
        return text[i + 1:end], end + 1
    raw, i = _flow_plain(text, i, "")
    return _scalar(raw), i


def _flow_plain(text: str, i: int, extra_stops: str) -> tuple[str, int]:
    start = i
    if i < len(text) and text[i] in "\"'":
        end = text.find(text[i], i + 1)
        if end < 0:
            raise YamlError("unclosed quote")
        return text[i + 1:end], end + 1
    while i < len(text) and text[i] not in ",]}" + extra_stops:
        i += 1
    return text[start:i].strip(), i


def load_light_yaml(text: str) -> Any:
    """A small YAML subset (enough for the screenplay's ledger / knowledge / series-card blocks): block mappings
    and sequences by indentation, flow ``{a: b}`` / ``[a, b]``, quoted / plain scalars, ints, floats, booleans,
    null and ``#`` comments.  A full-width colon ``：`` also separates a key.  Raises YamlError on bad input."""
    lines: list[list[Any]] = []
    for raw in str(text or "").replace("\t", "  ").splitlines():
        line = _strip_comment(raw)
        if not line.strip() or line.strip() in ("---", "..."):
            continue
        lines.append([len(line) - len(line.lstrip(" ")), line.strip()])
    if not lines:
        return None
    value, index = _block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError(f"unexpected indentation at: {lines[index][1][:40]}")
    return value


def _is_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _block(lines: list[list[Any]], i: int, indent: int) -> tuple[Any, int]:
    if _is_item(lines[i][1]):
        return _sequence(lines, i, indent)
    if _split_key(lines[i][1]) is None:
        return _scalar(lines[i][1]), i + 1
    return _mapping(lines, i, indent)


def _sequence(lines: list[list[Any]], i: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while i < len(lines) and lines[i][0] == indent and _is_item(lines[i][1]):
        content = lines[i][1]
        rest = content[1:].lstrip(" ")
        if not rest:
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _block(lines, i + 1, lines[i + 1][0])
            else:
                value, i = None, i + 1
            out.append(value)
            continue
        if rest[0] not in "[{\"'" and _split_key(rest) is not None:
            lines[i] = [indent + (len(content) - len(rest)), rest]   # "- key: v" -> a mapping one level in
            value, i = _mapping(lines, i, lines[i][0])
        else:
            value, i = _scalar(rest), i + 1
        out.append(value)
    return out, i


def _mapping(lines: list[list[Any]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while i < len(lines) and lines[i][0] == indent and not _is_item(lines[i][1]):
        pair = _split_key(lines[i][1])
        if pair is None:
            raise YamlError(f"expected 'key: value': {lines[i][1][:40]}")
        key, value = pair
        i += 1
        if value:
            out[key] = _scalar(value)
        elif i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and _is_item(lines[i][1]))):
            out[key], i = _block(lines, i, lines[i][0])
        else:
            out[key] = None
    return out, i


_FENCE = re.compile(r"^```[ \t]*(?:yaml|yml)\b[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL | re.IGNORECASE)
FIELD_KEYS = ("ledger", "knowledge", "series_card")


def extract_yaml_blocks(markdown: str) -> dict[str, Any]:
    """Every fenced ```yaml block of a screenplay / outline, merged (lists concatenated, dicts updated).  A block
    that fails to parse is skipped (reported under ``_errors``)."""
    merged: dict[str, Any] = {}
    errors: list[str] = []
    for body in _FENCE.findall(str(markdown or "")):
        try:
            data = load_light_yaml(body)
        except YamlError as exc:
            errors.append(str(exc))
            continue
        _merge(merged, data)
    if errors:
        merged["_errors"] = errors
    return merged


def _merge(into: dict[str, Any], data: Any) -> None:
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if isinstance(value, list) and isinstance(into.get(key), list):
            into[key] = into[key] + value
        elif isinstance(value, dict) and isinstance(into.get(key), dict):
            into[key] = {**into[key], **value}
        else:
            into[key] = value


def screenplay_fields(*sources: Any) -> dict[str, Any]:
    """The WP6 contract fields from the writer's screenplay artefacts (SCREENPLAY_V1, for the WP2 compiler):
    each source is a markdown text with fenced ```yaml blocks (``<EP>_OUTLINE.md`` knowledge, ``<EP>_SCREENPLAY.md``),
    a whole YAML text (``<EP>_CAST_PROPS.yaml`` ``ledger``, ``SERIES_CARD.yaml``) or an already parsed dict.
    Returns ``{ledger: [...], knowledge: [...], series_card: {...}}`` (only the keys found), normalised.
    A SERIES_CARD file without a ``series_card`` key (top-level ``characters``) is read as the card itself."""
    merged: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, dict):
            data = source
        elif isinstance(source, str) and "```" in source:
            data = extract_yaml_blocks(source)
        else:
            try:
                data = load_light_yaml(str(source or ""))
            except YamlError:
                data = None
        if isinstance(data, dict) and "series_card" not in data and "characters" in data:
            data = {**{k: v for k, v in data.items() if k != "characters"}, "series_card": data}
        _merge(merged, data)
    out: dict[str, Any] = {}
    if merged.get("ledger"):
        out["ledger"] = [r for r in (normalise_ledger_row(x) for x in _list(merged["ledger"])) if r]
    if merged.get("knowledge"):
        out["knowledge"] = [r for r in (normalise_knowledge_row(x) for x in _list(merged["knowledge"])) if r]
    card = normalise_series_card(merged.get("series_card"))
    if card.get("characters"):
        out["series_card"] = card
    return out


def apply_fields(contract: dict[str, Any], fields: dict[str, Any], *, language: str | None = None) -> dict[str, Any]:
    """A copy of ``contract`` with the WP6 fields added (rows deduplicated by id / content) and every ledger row's
    scene / anchor resolved to a ``shot_id`` where it can be.  For the WP2 compiler; pure."""
    out = dict(contract or {})
    if fields.get("ledger"):
        rows = [normalise_ledger_row(r) for r in _list(out.get("ledger"))] + list(fields["ledger"])
        seen: set[str] = set()
        uniq = []
        for row in rows:
            if not row:
                continue
            mark = row.get("id") or json.dumps(row, ensure_ascii=False, sort_keys=True)
            if mark not in seen:
                seen.add(mark)
                uniq.append(row)
        timeline = _timeline(out, language)
        shots = _shot_map(out, timeline)
        for row in uniq:
            if not row.get("shot_id"):
                sid, _how = resolve_shot(row, timeline, shots)
                if sid:
                    row["shot_id"] = sid
        out["ledger"] = uniq
    if fields.get("knowledge"):
        rows = [normalise_knowledge_row(r) for r in _list(out.get("knowledge"))] + list(fields["knowledge"])
        seen_k: set[str] = set()
        out["knowledge"] = []
        for row in rows:
            mark = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if row and mark not in seen_k:
                seen_k.add(mark)
                out["knowledge"].append(row)
    if fields.get("series_card") and not out.get("series_card"):
        out["series_card"] = fields["series_card"]
    return out


# --------------------------------------------------------------------------- normalisation
def normalise_kind(value: Any) -> str:
    raw = _clean(value)
    return _KIND_ALIASES.get(_upper(raw)) or _KIND_ALIASES.get(raw) or ""


def normalise_ledger_row(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    kind = normalise_kind(row.get("kind") or row.get("type"))
    out = {"id": _clean(row.get("id")), "kind": kind or _upper(row.get("kind") or row.get("type")),
           "thread": _clean(row.get("thread") or row.get("line") or row.get("线")),
           "shot_id": _clean(row.get("shot_id") or row.get("shot")),
           "pays_off": _clean(row.get("pays_off") or row.get("payoff_of") or row.get("ref")) or None,
           "from_episode": _clean(row.get("from_episode")).upper() or None}
    for key in ("scene_id", "anchor", "prop", "note", "episode"):
        value = row.get(key) if key != "scene_id" else (row.get("scene_id") or row.get("scene"))
        if _clean(value):
            out[key] = _clean(value)
    return out


def normalise_knowledge_row(row: Any) -> dict[str, Any] | None:
    """{scene_id, who, type KNOWS|BELIEVES|UNAWARE, fact, hidden_from?}; ``{who, believes: fact}`` and the zh keys
    知道 / 以为 / 不知道 are accepted."""
    if not isinstance(row, dict):
        return None
    kind, fact = _upper(row.get("type") or row.get("kind")), _clean(row.get("fact"))
    for key, value in (("knows", "KNOWS"), ("知道", "KNOWS"), ("believes", "BELIEVES"), ("以为", "BELIEVES"),
                       ("误以为", "BELIEVES"), ("unaware", "UNAWARE"), ("不知道", "UNAWARE")):
        if _clean(row.get(key)) and not isinstance(row.get(key), bool):
            kind, fact = value, fact or _clean(row.get(key))
            break
        if row.get(key) is True:
            kind = value
            break
    aliases = {"KNOW": "KNOWS", "BELIEF": "BELIEVES", "BELIEVE": "BELIEVES", "FALSE_BELIEF": "BELIEVES",
               "MISBELIEF": "BELIEVES", "DOES_NOT_KNOW": "UNAWARE", "IGNORANT": "UNAWARE"}
    kind = aliases.get(kind, kind)
    who = _clean(row.get("who") or row.get("character") or row.get("character_id"))
    if not who and not fact:
        return None
    out: dict[str, Any] = {"scene_id": _clean(row.get("scene_id") or row.get("scene")), "who": who,
                           "type": kind if kind in KNOWLEDGE_TYPES else (kind or "KNOWS"), "fact": fact}
    hidden = [_clean(x) for x in _list(row.get("hidden_from")) if _clean(x)]
    if hidden:
        out["hidden_from"] = hidden
    return out


def normalise_series_card(card: Any) -> dict[str, Any]:
    """{characters: [{character_id, name, signature_business, signature_prop, cues [..], main}]}."""
    if not isinstance(card, dict):
        return {}
    raw = card.get("characters") if "characters" in card else card.get("cast")
    if isinstance(raw, dict):
        raw = [{**(v if isinstance(v, dict) else {"signature_business": v}), "name": k} for k, v in raw.items()]
    chars = []
    for row in _list(raw):
        if not isinstance(row, dict):
            continue
        business = _clean(row.get("signature_business") or row.get("标志小动作"))
        cues = [_clean(c) for c in _list(row.get("cues") or row.get("signature_cues")) if _clean(c)]
        if not cues and business:
            cues = [c.strip() for c in _CUE_SPLIT.split(business) if len(c.strip()) >= 2]
        chars.append({"character_id": _clean(row.get("character_id") or row.get("id")),
                      "name": _clean(row.get("name") or row.get("canonical_name")),
                      "signature_business": business,
                      "signature_prop": _clean(row.get("signature_prop") or row.get("标志道具")),
                      "cues": cues, "main": row.get("main") is not False})
    return {**{k: v for k, v in card.items() if k not in ("characters", "cast")}, "characters": chars}


# --------------------------------------------------------------------------- series ledger
def series_id(contract: dict[str, Any] | None, runtime_root: Path | None) -> str | None:
    """The series the episode belongs to: contract ``series_id`` / ``series`` / ``work``, else the runtime's (first)
    ``sources/<work>/SOURCE_INDEX.json`` folder; None when neither exists."""
    for key in ("series_id", "series", "work", "source_work"):
        value = _clean((contract or {}).get(key))
        if value and "/" not in value and value not in (".", ".."):
            return value
    if runtime_root is None:
        return None
    try:
        hits = sorted(Path(runtime_root, "sources").glob("*/SOURCE_INDEX.json"))
    except OSError:
        return None
    return hits[0].parent.name if hits else None


def ledger_path(runtime_root: Path, series: str | None = None) -> Path:
    if series:
        return Path(runtime_root) / "sources" / series / "LEDGER.json"
    return Path(runtime_root) / "series" / "LEDGER.json"


def load_series_ledger(runtime_root: Path | None, series: str | None = None) -> dict[str, Any]:
    if runtime_root is None:
        return {"schema": LEDGER_SCHEMA, "episodes": {}}
    data = _read_json(ledger_path(runtime_root, series))
    if not isinstance(data, dict) or not isinstance(data.get("episodes"), dict):
        return {"schema": LEDGER_SCHEMA, "series": series, "episodes": {}}
    return data


def prior_episodes(ledger: dict[str, Any], episode: str) -> list[str]:
    """Recorded episodes of the series before ``episode`` (by episode number), oldest first."""
    current = episode_number(episode)
    rows = []
    for ep in (ledger.get("episodes") or {}):
        n = episode_number(ep)
        if n is not None and (current is None or n < current) and _clean(ep).upper() != _clean(episode).upper():
            rows.append((n, ep))
    return [ep for _, ep in sorted(rows)]


def _series_rows(ledger: dict[str, Any], episodes: list[str]) -> list[dict[str, Any]]:
    out = []
    for ep in episodes:
        for row in (ledger.get("episodes", {}).get(ep) or {}).get("rows") or []:
            norm = normalise_ledger_row(row)
            if norm:
                norm["episode"] = ep
                out.append(norm)
    return out


def open_threads(ledger: dict[str, Any], before_episode: str | None = None) -> list[dict[str, Any]]:
    """SETUP / HOOK rows of the series ledger that no later PAYOFF / CALLBACK names (what the next episode can pay
    off), oldest first."""
    episodes = prior_episodes(ledger, before_episode) if before_episode else sorted(
        (ledger.get("episodes") or {}), key=lambda e: episode_number(e) or 0)
    rows = _series_rows(ledger, episodes)
    paid = set()
    for row in rows:
        if row["kind"] in ("PAYOFF", "CALLBACK") and row.get("pays_off"):
            target = row["pays_off"]
            paid.add(target)
            ep, _, bare = _split_qualified(target)
            if ep:
                paid.add(bare)
    return [{"episode": r["episode"], "id": r["id"], "kind": r["kind"], "thread": r["thread"]}
            for r in rows if r["kind"] in ("SETUP", "HOOK") and r["id"]
            and r["id"] not in paid and f"{r['episode']}:{r['id']}" not in paid]


def _split_qualified(ref: str) -> tuple[str, str, str]:
    """``E02:L3`` / ``E02/L3`` -> ("E02", ":", "L3"); a plain id -> ("", "", id)."""
    m = re.match(r"^(E\d+)\s*[:/]\s*(.+)$", _clean(ref), re.IGNORECASE)
    return (m.group(1).upper(), ":", m.group(2).strip()) if m else ("", "", _clean(ref))


def record_episode(runtime_root: Path, episode: str, contract: dict[str, Any], *,
                   language: str | None = None) -> dict[str, Any]:
    """Append (or replace) ``episode``'s ledger rows in the series ledger once S1 admitted the script.  An episode
    without rows is still recorded (it counts toward the advisory window).  Never raises; {} on error."""
    try:
        series = series_id(contract, runtime_root)
        path = ledger_path(runtime_root, series)
        data = load_series_ledger(runtime_root, series)
        timeline = _timeline(contract, language)
        shots = _shot_map(contract, timeline)
        rows = []
        for raw in _list((contract or {}).get("ledger")):
            row = normalise_ledger_row(raw)
            if not row:
                continue
            if not row.get("shot_id") or row["shot_id"] not in {r["shot_id"] for r in timeline}:
                sid, _how = resolve_shot(row, timeline, shots)
                row["shot_id"] = sid or row.get("shot_id") or ""
            rows.append({k: v for k, v in row.items() if v not in (None, "")})
        beliefs = [r for r in (normalise_knowledge_row(x) for x in _list((contract or {}).get("knowledge")))
                   if r and r["type"] in ("BELIEVES", "UNAWARE")]
        data.setdefault("episodes", {})[episode] = {
            "rows": rows, "false_beliefs": beliefs[:12],
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        data["schema"], data["series"] = LEDGER_SCHEMA, series
        _write_json(path, data)
        return {"path": str(path), "series": series, "episodes": sorted(data["episodes"], key=lambda e: episode_number(e) or 0),
                "open_threads": open_threads(data)[:12]}
    except Exception:  # noqa: BLE001 -- bookkeeping must never fail a stage
        return {}


# --------------------------------------------------------------------------- contract views
def _timeline(contract: dict[str, Any], language: str | None = None) -> list[dict[str, Any]]:
    pace = _pace()
    return pace.timeline(contract or {}, pace.contract_language(contract or {}, language))


def _shot_map(contract: dict[str, Any], timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """shot_id (as the PACE timeline names it) -> shot dict."""
    shots = [s for s in (contract or {}).get("shots") or [] if isinstance(s, dict)]
    return {r["shot_id"]: s for r, s in zip(timeline, shots)}


def _shot_text(shot: dict[str, Any]) -> str:
    """Everything the shot shows physically: PACE action text + the WP2/WP3 action / reaction fields."""
    spec = _spec(shot)
    act = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    parts = [_pace().action_text(shot), act.get("business_en"), spec.get("listener_reaction"),
             spec.get("listener_reaction_en"), spec.get("lead_in_reaction_en"), shot.get("entry_state"),
             (shot.get("shot") or {}).get("entry_state") if isinstance(shot.get("shot"), dict) else None]
    return " ".join(_clean(p) for p in parts if _clean(p))


def _dialogue_text(shot: dict[str, Any]) -> str:
    spec = _spec(shot)
    value = spec.get("dialogue") if spec.get("dialogue") not in (None, "", []) else shot.get("dialogue")
    if isinstance(value, (list, tuple)):
        return " ".join(_clean(x.get("text") if isinstance(x, dict) else x) for x in value)
    return _clean(value)


def _names(contract: dict[str, Any]) -> dict[str, str]:
    """name / alias / id (normalised) -> character_id."""
    out: dict[str, str] = {}
    for row in (contract or {}).get("character_entities") or []:
        if not isinstance(row, dict):
            continue
        cid = _clean(row.get("character_id"))
        if not cid:
            continue
        for name in [cid, row.get("canonical_name"), row.get("display_name"), *(row.get("aliases") or [])]:
            if _key(name):
                out.setdefault(_key(name), cid)
    return out


def _who(value: Any, names: dict[str, str]) -> str:
    return names.get(_key(value), _key(value))


def _props_of(shot: dict[str, Any]) -> set[str]:
    out = set()
    for row in _list(_spec(shot).get("props")) + _list(shot.get("props")):
        if isinstance(row, dict):
            for key in ("entity_id", "prop_id", "id", "name"):
                if _key(row.get(key)):
                    out.add(_key(row.get(key)))
        elif _key(row):
            out.add(_key(row))
    return out


def resolve_shot(row: dict[str, Any], timeline: list[dict[str, Any]],
                 shots: dict[str, dict[str, Any]] | None = None) -> tuple[str, str]:
    """(shot_id, how) for a ledger row: its ``shot_id`` when it exists, else the shot of ``scene_id`` whose line or
    action text contains ``anchor``, else that scene's first shot (its last shot for a HOOK).  ("", "") if none."""
    ids = {r["shot_id"] for r in timeline}
    sid = _clean(row.get("shot_id"))
    if sid in ids:
        return sid, "shot_id"
    scene = _clean(row.get("scene_id"))
    rows = [r for r in timeline if not scene or r["scene_id"] == scene or r["scene_id"].endswith(f"-{scene}")]
    anchor = _key(row.get("anchor"))
    if anchor and shots:
        for r in rows:
            shot = shots.get(r["shot_id"]) or {}
            if anchor in _key(_dialogue_text(shot) + _shot_text(shot)):
                return r["shot_id"], "anchor"
    if scene and rows:
        pick = rows[-1] if row.get("kind") == "HOOK" else rows[0]
        return pick["shot_id"], "scene"
    return "", ""


# --------------------------------------------------------------------------- checks
def ledger_check(contract: dict[str, Any], episode: str, timeline: list[dict[str, Any]],
                 shots: dict[str, dict[str, Any]], series_ledger: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    rows = [r for r in (normalise_ledger_row(x) for x in _list((contract or {}).get("ledger"))) if r]
    prior = prior_episodes(series_ledger, episode)
    history = _series_rows(series_ledger, prior)
    current = episode_number(episode)
    duration = timeline[-1]["end"] if timeline else 0.0
    ends = {r["shot_id"]: r["end"] for r in timeline}
    failures: list[str] = []
    resolved: list[str] = []
    for row in rows:
        sid, _how = resolve_shot(row, timeline, shots)
        if not sid:
            failures.append(f"LEDGER_SHOT_UNKNOWN:{row['id'] or row['kind']}:{row.get('shot_id') or '-'}")
        resolved.append(sid)
    here = {r["id"]: r for r in rows if r["id"]}
    targets_here = {i for i, r in here.items() if r["kind"] in ("SETUP", "HOOK")}
    by_episode: dict[str, set[str]] = {}
    for r in history:
        if r["kind"] in ("SETUP", "HOOK") and r["id"]:
            by_episode.setdefault(r["episode"].upper(), set()).add(r["id"])
    history_ids = {i for ids in by_episode.values() for i in ids}
    recorded = {_clean(ep).upper() for ep in (series_ledger.get("episodes") or {})}

    def earlier(ref: str) -> bool:
        """``ref`` names a SETUP / HOOK of an earlier episode (a qualified ref to an earlier episode the series
        ledger never recorded -- e.g. before BILI_V1 was on -- is taken on trust)."""
        ep, _, bare = _split_qualified(ref)
        if ep:
            n = episode_number(ep)
            return bare in by_episode.get(ep, set()) or (
                ep not in recorded and n is not None and current is not None and n < current)
        return ref in history_ids

    setups = sum(1 for r in rows if r["kind"] == "SETUP")
    payoffs = callbacks = hooks = 0
    for row, sid in zip(rows, resolved):
        ref = row.get("pays_off") or ""
        if row["kind"] == "PAYOFF":
            payoffs += 1
            if not ref:
                failures.append(f"LEDGER_PAYOFF_UNRESOLVED:{row['id'] or '-'}:no_pays_off")
            elif ref in targets_here and ref != row["id"]:
                pass
            elif earlier(ref):
                callbacks += 1   # paying off an earlier episode's setup is a callback too
            else:
                failures.append(f"LEDGER_PAYOFF_UNRESOLVED:{row['id'] or '-'}:{ref}")
        elif row["kind"] == "CALLBACK":
            from_ep = episode_number(row.get("from_episode") or _split_qualified(ref)[0])
            if ref and not (ref in targets_here or earlier(ref)):
                failures.append(f"LEDGER_PAYOFF_UNRESOLVED:{row['id'] or '-'}:{ref}")
            elif from_ep is not None and current is not None and from_ep < current:
                callbacks += 1
            elif ref and earlier(ref):
                callbacks += 1
        elif row["kind"] == "HOOK":
            if sid and duration and ends.get(sid, 0.0) >= duration - HOOK_WINDOW_SECONDS:
                hooks += 1
    callback_required = bool(prior) or bool(current and current > 1 and history)
    thin = []
    if setups < MIN_SETUPS:
        thin.append(f"setup={setups}<{MIN_SETUPS}")
    if payoffs < MIN_PAYOFFS:
        thin.append(f"payoff={payoffs}<{MIN_PAYOFFS}")
    if callback_required and callbacks < MIN_CALLBACKS:
        thin.append(f"callback={callbacks}<{MIN_CALLBACKS}")
    if hooks < MIN_HOOKS:
        thin.append(f"hook_last_{HOOK_WINDOW_SECONDS:.0f}s={hooks}<{MIN_HOOKS}")
    if thin:
        failures.insert(0, "LEDGER_THIN:" + ",".join(thin))
    threads = {_key(r["thread"]) or _key(r["id"]) for r in rows if _key(r["thread"]) or _key(r["id"])}
    metrics = {"rows": len(rows), "setups": setups, "payoffs": payoffs, "callbacks": callbacks, "hooks": hooks,
               "threads": len(threads), "callback_required": callback_required, "prior_episodes": prior,
               "kinds_unknown": sorted({r["kind"] for r in rows if r["kind"] not in LEDGER_KINDS})}
    return failures, metrics


def irony_check(contract: dict[str, Any], timeline: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    rows = [r for r in (normalise_knowledge_row(x) for x in _list((contract or {}).get("knowledge"))) if r]
    scenes = {r["scene_id"] for r in timeline}
    warnings = [f"KNOWLEDGE_UNKNOWN_SCENE:{r['scene_id']}" for r in rows
                if r["scene_id"] and r["scene_id"] not in scenes
                and not any(s.endswith(f"-{r['scene_id']}") for s in scenes)][:4]
    false_beliefs = [r for r in rows if r["type"] == "BELIEVES"]
    unaware = [r for r in rows if r["type"] == "UNAWARE"]
    audience_edge = [r for r in rows if _upper(r["who"]) in (AUDIENCE, "观众") and r.get("hidden_from")]
    double = 0
    for shot in (contract or {}).get("shots") or []:
        if isinstance(shot, dict) and (_spec(shot).get("double_meaning") is True or shot.get("double_meaning") is True):
            double += 1
    for unit in ((contract or {}).get("audio_contract") or {}).get("dialogue_units") or []:
        if isinstance(unit, dict) and unit.get("double_meaning") is True:
            double += 1
    irony = len(false_beliefs) + len(unaware) + len(audience_edge) + double
    if not irony:
        warnings.insert(0, "NO_IRONY")
    return warnings, {"knowledge_rows": len(rows), "false_beliefs": len(false_beliefs), "unaware": len(unaware),
                      "audience_edge": len(audience_edge), "double_meaning_lines": double, "irony_points": irony}


_CJK = re.compile(r"[\u3400-\u9fff\u3041-\u30ff\uac00-\ud7a3]")


def cue_hit(cue: str, text: str) -> bool:
    """A signature cue in the action text: verbatim, or (CJK) its characters in order with at most two characters
    between them (捂嘴 ~ 捂住嘴, 抿嘴 ~ 抿住嘴唇, 摸后颈 ~ 摸了摸后颈)."""
    cue, text = _key(cue), _key(text)
    if not cue or not text:
        return False
    if cue in text:
        return True
    if len(cue) < 2 or not _CJK.search(cue):
        return False
    return bool(re.search(".{0,2}".join(re.escape(ch) for ch in cue), text))


def _signature_tagged(shot: dict[str, Any], who: set[str], names: dict[str, str], speaker: str) -> bool:
    tag = _spec(shot).get("signature_business", shot.get("signature_business"))
    if tag is True:
        return bool(speaker) and speaker in who
    return any(_who(t, names) in who for t in _list(tag) if not isinstance(t, bool))


def signature_check(contract: dict[str, Any], timeline: list[dict[str, Any]], shots: dict[str, dict[str, Any]],
                    card: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    chars = [c for c in (card or {}).get("characters") or [] if c.get("main")]
    if not chars:
        return ["SIGNATURE_CARD_MISSING"], {"card_characters": 0, "uses": {}}
    names = _names(contract)
    failures: list[str] = []
    uses: dict[str, int] = {}
    for char in chars:
        ident = {x for x in (_who(char["character_id"], names), _who(char["name"], names),
                             _key(char["character_id"]), _key(char["name"])) if x}
        present = [r for r in timeline if ident & {_who(c, names) for c in r["cast"]}
                   or _who(r["speaker"], names) in ident
                   or any(_who(ln.get("speaker"), names) in ident for ln in r["lines"])]
        if not present:
            continue
        label = char["character_id"] or char["name"]
        cues = [_key(c) for c in char.get("cues") or [] if _key(c)]
        count = 0
        for r in present:
            shot = shots.get(r["shot_id"]) or {}
            speaker = _who(r["speaker"], names)
            if _signature_tagged(shot, ident, names, speaker):
                count += 1
            elif cues and any(cue_hit(c, _key(_shot_text(shot))) for c in cues):
                count += 1
        uses[label] = count
        if not (char.get("signature_business") or cues):
            failures.append(f"SIGNATURE_CARD_MISSING:{label}")
        elif count < SIGNATURE_MIN_USES:
            failures.append(f"SIGNATURE_BUSINESS_UNUSED:{label}")
        elif count > SIGNATURE_MAX_USES:
            failures.append(f"SIGNATURE_BUSINESS_OVERUSED:{label}:{count}>{SIGNATURE_MAX_USES}")
    return failures, {"card_characters": len(chars), "uses": uses}


def _scene_plan(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    plan = _pace().pacing_block(contract or {}).get("scene_plan") or []
    return {_clean(r.get("scene_id")): r for r in plan if isinstance(r, dict) and _clean(r.get("scene_id"))}


def turn_check(contract: dict[str, Any], timeline: list[dict[str, Any]],
               shots: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    names = _names(contract)
    plan = _scene_plan(contract)
    pace = _pace()
    warnings: list[str] = []
    checked = 0
    for scene in dict.fromkeys(r["scene_id"] for r in timeline):
        rows = [r for r in timeline if r["scene_id"] == scene]
        card = plan.get(scene) or {}
        turn = next((r for r in rows if r["shot_id"] == _clean(card.get("turn_shot_id"))), None) or next(
            (r for r in rows if r["beat_role"] == "TURN"), None)
        if turn is None:
            continue
        checked += 1
        owner = _who(card.get("turn_owner"), names) if _clean(card.get("turn_owner")) else (
            _who(turn["speaker"], names) or (_who(turn["cast"][0], names) if turn["cast"] else ""))
        lines = sum(1 for r in rows for ln in r["lines"] if owner and _who(ln.get("speaker"), names) == owner)
        shot = shots.get(turn["shot_id"]) or {}
        spec = _spec(shot)
        text = _shot_text(shot)
        nxt = next((r for r in timeline if r["index"] == turn["index"] + 1), None)
        acted = (turn["physical"] or pace.strong_action(text) or pace.body_motion(text)
                 or any(_clean(spec.get(k)) for k in ("listener_reaction", "listener_reaction_en",
                                                      "lead_in_reaction_en"))
                 or bool(nxt and nxt["beat_role"] == "REACTION" and nxt["scene_id"] == scene)
                 or (not turn["lines"] and bool(_clean(text))))
        if lines > TURN_OWNER_MAX_LINES:
            warnings.append(f"TURN_TALKED:{scene}:{owner or '-'}:lines={lines}>{TURN_OWNER_MAX_LINES}")
        elif not acted:
            warnings.append(f"TURN_TALKED:{scene}:{turn['shot_id']}:no_action_or_reaction")
    return warnings[:6], {"turn_scenes_checked": checked}


def time_place_check(contract: dict[str, Any], timeline: list[dict[str, Any]]) -> list[str]:
    plan = _scene_plan(contract)
    states = {_clean(r.get("scene_id")): r for r in (contract or {}).get("scene_states") or []
              if isinstance(r, dict)}
    out = []
    for scene in dict.fromkeys(r["scene_id"] for r in timeline):
        card, state = plan.get(scene) or {}, states.get(scene) or {}
        missing = []
        if not any(_clean(src.get(k)) for src in (card, state)
                   for k in ("time_of_day", "time", "time_id", "时段")):
            missing.append("time")
        if not any(_clean(src.get(k)) for src in (card, state) for k in ("light", "weather", "光", "天气")):
            missing.append("light")
        if not any(_list(src.get(k)) for src in (card, state) for k in ("set_pieces", "set_piece", "陈设")):
            missing.append("set_piece")
        if missing:
            out.append(f"NO_TIME_PLACE:{scene}:{'/'.join(missing)}")
    return out[:6]


_MIRROR_FIELDS = ("shot_scale", "camera_height", "camera_side")


def mirror_setup_hints(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """L4 hook (WP3 director pass): for each scene with an in-episode ``mirror_of``, the camera setup fields
    (``speaking_unit_duration.SETUP_FIELDS``) of the mirrored scene's first shot, to reuse."""
    try:
        from speaking_unit_duration import SETUP_FIELDS  # type: ignore
    except Exception:  # noqa: BLE001
        SETUP_FIELDS = ("shot_scale", "camera_height", "camera_side", "motion_family", "motion_direction",
                        "start_framing")
    first: dict[str, dict[str, Any]] = {}
    for shot in (contract or {}).get("shots") or []:
        if isinstance(shot, dict):
            first.setdefault(_clean(shot.get("scene_id")), shot)
    out = {}
    for scene, card in _scene_plan(contract).items():
        target = _clean(card.get("mirror_of"))
        if target and target in first:
            plan = _camera_plan(first[target])
            fields = {k: plan.get(k) for k in SETUP_FIELDS if plan.get(k) not in (None, "")}
            if fields:
                out[scene] = {"mirror_of": target, **fields}
    return out


def mirror_check(contract: dict[str, Any], episode: str, timeline: list[dict[str, Any]],
                 shots: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    order = list(dict.fromkeys(r["scene_id"] for r in timeline))
    first = {}
    for r in timeline:
        first.setdefault(r["scene_id"], shots.get(r["shot_id"]) or {})
    current = episode_number(episode)
    out, mirrors = [], 0
    for scene, card in _scene_plan(contract).items():
        target = _clean(card.get("mirror_of"))
        if not target or target in ("-", "null", "None"):
            continue
        mirrors += 1
        if target in order and scene in order and order.index(target) < order.index(scene):
            a, b = _camera_plan(first[target]), _camera_plan(first[scene])
            diff = [k for k in _MIRROR_FIELDS if _clean(a.get(k)) and _clean(b.get(k))
                    and _upper(a.get(k)) != _upper(b.get(k))]
            if diff:
                out.append(f"MIRROR_SETUP_DIFFERS:{scene}<{target}:{'/'.join(diff)}")
            continue
        m = _SCENE_EP.match(target)
        n = episode_number(m.group(1)) if m else None
        if n is not None and current is not None and n < current:
            continue
        out.append(f"MIRROR_UNRESOLVED:{scene}:{target}")
    return out[:6], {"mirrored_scenes": mirrors}


def object_first_of(shot: dict[str, Any]) -> dict[str, Any] | None:
    """The shot's object-first entrance declaration, normalised ({subject, of, then}), or None."""
    spec = _spec(shot)
    raw = spec.get("object_first", shot.get("object_first"))
    if raw in (None, False, "", {}) and _upper(spec.get("entrance")) != "OBJECT_FIRST":
        return None
    raw = raw if isinstance(raw, dict) else ({"subject": raw} if isinstance(raw, str) else {})
    subject = _upper(raw.get("subject")) or "PROP"
    then = _upper(raw.get("then")) or "INSERT"
    return {"subject": subject if subject in OBJECT_FIRST_SUBJECTS else subject,
            "of": _clean(raw.get("of")), "then": then if then in OBJECT_FIRST_THEN else then}


def _faceless(shot: dict[str, Any]) -> bool:
    cast = [c for c in _spec(shot).get("cast") or [] if isinstance(c, dict)]
    return all(any(_PARTIAL.search(_clean(c.get(f))) for f in ("visible_body_range", "visible_extent",
                                                               "face_visibility")) for c in cast)


def insert_shots(timeline: list[dict[str, Any]], shots: dict[str, dict[str, Any]]) -> list[str]:
    """Dedicated insert units: beat_role INSERT, an object-first INSERT, or a silent PACE-measured INSERT shot."""
    out = []
    for r in timeline:
        shot = shots.get(r["shot_id"]) or {}
        of = object_first_of(shot)
        if r["beat_role"] == "INSERT" or (not r["lines"] and (r["kind"] == "INSERT"
                                                              or (of and of["then"] == "INSERT"))):
            out.append(r["shot_id"])
    return out


def insert_check(contract: dict[str, Any], timeline: list[dict[str, Any]],
                 shots: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    inserts = insert_shots(timeline, shots)
    failures = []
    if len(inserts) > INSERT_MAX:
        failures.append(f"INSERT_OVER:{len(inserts)}>{INSERT_MAX}")
    ledger_props: set[str] = set()
    for row in (normalise_ledger_row(x) for x in _list((contract or {}).get("ledger"))):
        if not row or row["kind"] not in ("SETUP", "PAYOFF", "CALLBACK", "HOOK"):
            continue
        if row.get("prop"):
            ledger_props.add(_key(row["prop"]))
        sid, _ = resolve_shot(row, timeline, shots)
        if sid and row["kind"] in ("SETUP", "PAYOFF"):
            ledger_props |= _props_of(shots.get(sid) or {})
    for sid in inserts:
        props = _props_of(shots.get(sid) or {})
        if not props & ledger_props:
            failures.append(f"INSERT_WITHOUT_LEDGER_PROP:{sid}")
    units = len(inserts)
    return failures[:6], {"insert_units": units, "insert_shot_ids": inserts[:12],
                          "insert_credits_estimate": round(units * UNIT_FLOOR_SECONDS * H3_CREDITS_PER_SECOND, 1)}


def object_first_check(timeline: list[dict[str, Any]],
                       shots: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    warnings, declared = [], 0
    faceless_inserts = 0
    for r in timeline:
        shot = shots.get(r["shot_id"]) or {}
        of = object_first_of(shot)
        if r["kind"] == "INSERT" and not r["lines"]:
            faceless_inserts += 1
        if not of:
            continue
        declared += 1
        if of["then"] == "INSERT" and not _faceless(shot):
            warnings.append(f"OBJECT_FIRST_FACE_SHOWN:{r['shot_id']}")
        elif of["then"] != "INSERT" and not _clean(_camera_plan(shot).get("start_framing")):
            warnings.append(f"OBJECT_FIRST_FACE_SHOWN:{r['shot_id']}:no_start_framing")
    if timeline and not declared and not faceless_inserts:
        warnings.insert(0, "OBJECT_FIRST_NONE")
    return warnings[:6], {"object_first_entrances": declared, "faceless_inserts": faceless_inserts}


def director_hints(contract: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    """L4 hooks for the WP3 director pass (pure; nothing is applied here): object-first entrances to frame on the
    detail first, mirrored scenes' camera setups to reuse, and the zero-cost insert alternative."""
    timeline = _timeline(contract, language)
    shots = _shot_map(contract, timeline)
    entrances = []
    for r in timeline:
        of = object_first_of(shots.get(r["shot_id"]) or {})
        if of:
            entrances.append({"shot_id": r["shot_id"], **of,
                              "counts_as_scene_move": of["then"] in ("TILT_UP", "PUSH_IN", "PAN")})
    return {"object_first": entrances, "mirror_setups": mirror_setup_hints(contract),
            "insert_alternative_en": INSERT_ALTERNATIVE_EN, "insert_max": INSERT_MAX}


# --------------------------------------------------------------------------- series card
def load_series_card(contract: dict[str, Any] | None, runtime_root: Path | None = None,
                     scripts_dir: Path | None = None) -> dict[str, Any]:
    """contract ``series_card`` -> runtime ``qingshan.json`` ``series_card`` (top level or ``project``) ->
    ``SERIES_CARD.yaml|json`` beside the scripts -> beside the series ledger.  {} when none."""
    card = normalise_series_card((contract or {}).get("series_card"))
    if card.get("characters"):
        return card
    if runtime_root is not None:
        config = _read_json(Path(runtime_root) / "qingshan.json")
        if isinstance(config, dict):
            for src in (config.get("series_card"), (config.get("project") or {}).get("series_card")
                        if isinstance(config.get("project"), dict) else None):
                card = normalise_series_card(src)
                if card.get("characters"):
                    return card
    dirs = [d for d in (scripts_dir, ledger_path(runtime_root, series_id(contract, runtime_root)).parent
                        if runtime_root is not None else None) if d]
    for folder in dirs:
        for name in ("SERIES_CARD.json", "SERIES_CARD.yaml", "SERIES_CARD.yml"):
            path = Path(folder) / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
                data = json.loads(text) if name.endswith(".json") else load_light_yaml(text)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                card = normalise_series_card(data.get("series_card") if "series_card" in data else data)
                if card.get("characters"):
                    return card
    return {}


# --------------------------------------------------------------------------- evaluate
def evaluate(contract: dict[str, Any], *, episode: str | None = None, runtime_root: Path | None = None,
             scripts_dir: Path | None = None, language: str | None = None,
             series_ledger: dict[str, Any] | None = None, series_card: dict[str, Any] | None = None,
             phase: str | None = None) -> dict[str, Any]:
    """The WP6 report: {schema, phase ADVISORY|REQUIRED, failures (taste codes for the revision loop), warnings,
    fixes, metrics}.  ``phase`` defaults to ADVISORY while the series ledger has fewer than ADVISORY_EPISODES
    episodes before this one; GRADUATED codes are failures only in REQUIRED."""
    contract = contract if isinstance(contract, dict) else {}
    episode = _clean(episode or contract.get("episode")) or "E00"
    timeline = _timeline(contract, language)
    shots = _shot_map(contract, timeline)
    series = series_id(contract, runtime_root)
    ledger = series_ledger if series_ledger is not None else load_series_ledger(runtime_root, series)
    card = normalise_series_card(series_card) if series_card is not None else load_series_card(
        contract, runtime_root, scripts_dir)
    prior = prior_episodes(ledger, episode)
    phase = phase or ("REQUIRED" if len(prior) >= ADVISORY_EPISODES else "ADVISORY")
    found: list[str] = []
    metrics: dict[str, Any] = {}
    for check in (lambda: ledger_check(contract, episode, timeline, shots, ledger),
                  lambda: irony_check(contract, timeline),
                  lambda: signature_check(contract, timeline, shots, card),
                  lambda: turn_check(contract, timeline, shots),
                  lambda: (time_place_check(contract, timeline), {}),
                  lambda: mirror_check(contract, episode, timeline, shots),
                  lambda: insert_check(contract, timeline, shots),
                  lambda: object_first_check(timeline, shots)):
        codes, m = check()
        found.extend(codes)
        metrics.update(m)
    failures, warnings = [], []
    for code in found:
        head = code.split(":", 1)[0]
        if head in TASTE_CODES or (head in GRADUATED_CODES and phase == "REQUIRED"):
            failures.append(code)
        else:
            warnings.append(code)
    heads = sorted({c.split(":", 1)[0] for c in found})
    return {"schema": SCHEMA, "profile": "BILI_V1", "episode": episode, "series": series, "phase": phase,
            "advisory_episodes_left": max(0, ADVISORY_EPISODES - len(prior)),
            "status": "PASS" if not failures else "FAIL", "failures": failures, "warnings": warnings,
            "fixes": {h: FIXES[h] for h in heads if h in FIXES}, "metrics": metrics,
            "open_threads": open_threads(ledger, episode)[:8]}


def merge_into_pacing(report: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """The SHORT_DRAMA_PACING_V1 report with the WP6 failures (revision loop) and warnings added; ``report`` itself
    when there is no WP6 result (LEGACY)."""
    if not result:
        return report
    out = dict(report)
    out["failures"] = list(report.get("failures") or []) + list(result.get("failures") or [])
    out["warnings"] = list(report.get("warnings") or []) + list(result.get("warnings") or [])
    out["status"] = "PASS" if not out["failures"] else "FAIL"
    out["fixes"] = {**(report.get("fixes") or {}), **(result.get("fixes") or {})}
    out["craft_ledger"] = summary(result)
    return out


def summary(result: dict[str, Any]) -> dict[str, Any]:
    m = result.get("metrics") or {}
    return {"schema": result.get("schema"), "phase": result.get("phase"), "status": result.get("status"),
            "series": result.get("series"), "advisory_episodes_left": result.get("advisory_episodes_left"),
            "failures": list(result.get("failures") or [])[:12], "warnings": list(result.get("warnings") or [])[:12],
            "metrics": {k: m.get(k) for k in ("setups", "payoffs", "callbacks", "hooks", "threads", "irony_points",
                                              "uses", "insert_units", "insert_credits_estimate",
                                              "object_first_entrances", "mirrored_scenes")},
            "open_threads": list(result.get("open_threads") or [])[:8]}


# --------------------------------------------------------------------------- pipeline / start prompt entry points
def s1_report(report: dict[str, Any], contract: dict[str, Any], *, episode: str, runtime_root: Path,
              scripts_dir: Path | None = None, language: str | None = None) -> dict[str, Any]:
    """S1 (BILI_V1 only -- the caller checks the profile): the pacing report with WP6 merged in.  Never raises;
    on any error the pacing report is returned unchanged with the error noted."""
    try:
        result = evaluate(contract, episode=episode, runtime_root=runtime_root, scripts_dir=scripts_dir,
                          language=language)
        return merge_into_pacing(report, result)
    except Exception as exc:  # noqa: BLE001 -- a craft check must never break S1
        return {**report, "craft_ledger": {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}}


CODEX_NOTE_TITLE = "## BILI_V1 账本 / 戏剧反讽 / 标志小动作（WP6）"
CODEX_NOTE_ZH = (
    "合同（或剧本 ```yaml 块）写 `ledger`：[{id, kind SETUP|PAYOFF|CALLBACK|HOOK, thread, shot_id 或 scene_id+anchor, "
    "pays_off, from_episode, prop}]，每集 ≥2 埋 ≥2 收、≥1 条回扣前集、最后 10 s 一个 HOOK；"
    "`knowledge`：[{scene_id, who, knows|believes|unaware: 事实}]，至少 1 处观众知道而角色不知道/误信，或台词 "
    "double_meaning: true；`series_card` 每个主角 1 个 signature_business（本集 1–3 次，含义不变）+ signature_prop；"
    "scene_plan 每场写 time_of_day、light、set_pieces，对照场写 mirror_of，转折场 turn_shot_id（转折的人本场 ≤2 句，用动作/反应演）；"
    "重要人物/道具登场先给手、脚、物件、轮子（prompt_spec.object_first + cast visible_body_range HANDS_ONLY/FEET_ONLY）；"
    "专用插入镜 beat_role INSERT 每集 ≤3（各约 +4 积分），只拍账本里的道具，其余用「前景手/物实焦、后景人脸虚」。"
    "系列前 3 集只提示，之后进改稿循环。自查：`python3 lines/nalu/runtime/tools/craft_ledger.py check --contract <合同>`；"
    "未回收的线：`craft_ledger.py open`。")


def codex_note_zh(runtime_root: Path | None = None, episode: str | None = None, *, limit: int = 1400) -> str:
    """The BILI_V1 start-prompt section (the caller checks the profile): the rules plus the series' open threads."""
    text = f"{CODEX_NOTE_TITLE}\n{CODEX_NOTE_ZH}"
    try:
        ledger = load_series_ledger(runtime_root, series_id(None, runtime_root)) if runtime_root else {}
        threads = open_threads(ledger, episode) if ledger.get("episodes") else []
        if threads:
            text += "\n本系列未回收的线（可在本集回收，pays_off 写 E<nn>:<id>）：" + "；".join(
                f"{t['episode']}:{t['id']}（{t['kind']} {t['thread']}）" for t in threads[:8])
    except Exception:  # noqa: BLE001
        pass
    return text[:limit]


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="WP6 checks on a generation contract (free; exit 0 unless --strict)")
    c.add_argument("--contract", required=True)
    c.add_argument("--episode")
    c.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT"))
    c.add_argument("--scripts-dir")
    c.add_argument("--phase", choices=("ADVISORY", "REQUIRED"))
    c.add_argument("--strict", action="store_true", help="exit 3 when a failure is reported")
    o = sub.add_parser("open", help="open setups / hooks of the series ledger")
    o.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT") or str(Path.home() / "nalu_runtime"))
    o.add_argument("--series")
    o.add_argument("--before")
    y = sub.add_parser("fields", help="WP6 contract fields from screenplay / YAML files (WP2 compiler input)")
    y.add_argument("paths", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "open":
        root = Path(args.runtime_root).expanduser()
        ledger = load_series_ledger(root, args.series or series_id(None, root))
        print(json.dumps(open_threads(ledger, args.before), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "fields":
        texts = [Path(p).read_text(encoding="utf-8") for p in args.paths]
        print(json.dumps(screenplay_fields(*texts), ensure_ascii=False, indent=1))
        return 0
    contract = _read_json(Path(args.contract)) or {}
    root = Path(args.runtime_root).expanduser() if args.runtime_root else None
    result = evaluate(contract, episode=args.episode, runtime_root=root,
                      scripts_dir=Path(args.scripts_dir) if args.scripts_dir else Path(args.contract).parent,
                      phase=args.phase)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 3 if (args.strict and result["failures"]) else 0


__all__ = [
    "SCHEMA", "LEDGER_SCHEMA", "ADVISORY_EPISODES", "LEDGER_KINDS", "KNOWLEDGE_TYPES", "BEAT_ROLES",
    "OBJECT_FIRST_SUBJECTS", "OBJECT_FIRST_THEN", "INSERT_MAX", "INSERT_ALTERNATIVE_EN", "GRADUATED_CODES",
    "TASTE_CODES", "ADVISORY_CODES", "FIXES", "FIELD_KEYS", "load_light_yaml", "extract_yaml_blocks",
    "screenplay_fields", "apply_fields", "normalise_ledger_row", "normalise_knowledge_row", "normalise_series_card",
    "series_id", "ledger_path", "load_series_ledger", "prior_episodes", "open_threads", "record_episode",
    "resolve_shot", "director_hints", "mirror_setup_hints", "object_first_of", "insert_shots", "load_series_card",
    "evaluate", "merge_into_pacing", "summary", "s1_report", "codex_note_zh", "CODEX_NOTE_ZH",
]

if __name__ == "__main__":
    raise SystemExit(main())
