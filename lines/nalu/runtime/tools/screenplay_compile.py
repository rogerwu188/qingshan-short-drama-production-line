#!/usr/bin/env python3
"""SCREENPLAY_V1: the writer's Chinese prose screenplay + light YAML -> the legacy four S1 layers.

Owner 2026-11-23 (Bilibili benchmark ep2 + ep3, ``~/nalu_lab/bili_work/CHANGE_SPEC.md`` WP2).  Under ``craft_profile:
BILI_V1`` with ``writer_format: SCREENPLAY_V1`` the writer (Codex) no longer fills the 40-field contract with a
generator script (``build_<ep>_layers.py`` -- the source of rotating emotions, "gesture variation N" and identical
scene plans).  It writes four small files under ``workflow/claude_writer_agent/scripts/``:

* ``SERIES_CARD.yaml`` (once per series): premise, engine, per main character want / fear / voice /
  ``signature_business`` / ``signature_prop`` / palette (WP6 reads the signature fields);
* ``<EP>_OUTLINE.md`` (L1): prose plus one fenced ``yaml`` block (main / secondary event, must-land facts, hook, end
  hook, ``plot_events``, ``cut``, ``knowledge`` rows for WP6);
* ``<EP>_SCREENPLAY.md`` (L2 scene cards + L3 prose screenplay; the compile input, ``docs/knowledge/
  SCREENPLAY_FORMAT_V1.md``);
* ``<EP>_CAST_PROPS.yaml``: cast -> entity ids, props (owner, hand), locations (time, weather, light, set pieces,
  ambience), ``ledger`` (WP6).

``compile_episode`` turns them into ``<EP>_NARRATIVE_CANONICAL_v1.md``, ``<EP>_DIRECTING_SCRIPT_v1.md``,
``<EP>_GENERATION_CONTRACT_v1.json`` and ``<EP>_manifest_v1.json`` so S2-S8 are untouched.  Rules:

* one dialogue line = one shot (``beat_role: LINE`` unless tagged); an action line attaches to the next line's shot
  (or back to the previous shot when its subject just spoke and the next line is someone else's); a trailing
  action block or a ``（无声）`` line is its own silent shot;
* a reaction beat ``[X 反应：...]`` becomes ``listener_reaction`` (+ ``listener_reaction_en``) on the shot it
  follows, or ``lead_in_reaction`` on the next shot when nothing precedes it (WP3 decides the final placement);
* props (``{道具 名 @人.手}`` or YAML) become ``props.reference_cards`` and every shot's ``props`` list;
* ``@card`` becomes ``pacing.scene_plan`` (objective / conflict / physical_action = goal / obstacle / turn, plus
  ``source_detail_ids``, ``scene_type``, ``mirror_of``, ``mood``) and the ``screenplay_v1`` block the
  anti-template checks (``screenplay_checks.py``) read;
* the emotion is DERIVED (parenthetical cue -> lexicon word, else the scene type, else the line's punctuation);
  ``（情绪=怒）`` overrides.  Nothing rotates, because nothing cycles;
* every zh field H3 needs has an ``_en`` twin from ``<EP>_SCREENPLAY_EN.json`` (Codex translates the request rows
  this compile writes to ``<EP>_SCREENPLAY_EN_REQUEST.json`` in the same run; keyed by the zh text's sha, so an
  edit re-requests only what changed);
* a field the screenplay does not give is filled from the line itself and recorded in
  ``prompt_spec.action.field_sources`` as ``"fallback"`` (WP7 reports the share).

Pure functions + a CLI (``python3 screenplay_compile.py <EP> [--scripts-dir D] [--check]``).  Standard library
only (the light YAML subset parser below; JSON is accepted wherever YAML is).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

SCHEMA = "nalu.screenplay_compile.v1"
BLOCK_SCHEMA = "nalu.screenplay_v1.block.v1"
EN_SCHEMA = "nalu.screenplay_en.v1"
EN_REQUEST_SCHEMA = "nalu.screenplay_en_request.v1"
LEXICON_PATH = _HERE.parent / "configs" / "PERFORMANCE_EMOTION_LEXICON_v1.json"
SCREENPLAY_LEXICON_PATH = _HERE.parent / "configs" / "SCREENPLAY_LEXICON_V1.json"
TOOL_ID = "lines/nalu/runtime/tools/screenplay_compile.py"
SILENT_SECONDS = 4.0
FALLBACK = "fallback"
AUTHORED = "screenplay"


# =========================================================================== light YAML (subset)
class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str) -> Any:
    value = text.strip()
    if value == "":
        return None
    if value[0] in "[{":
        return _flow(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        return json.loads(f'"{inner}"') if value[0] == '"' else inner.replace("''", "'")
    low = value.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?\d+\.\d*", value):
        return float(value)
    return value


def _split_flow(body: str) -> list[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch in ",，" and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _flow(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(p) for p in _split_flow(text[1:-1])]
    if text.startswith("{") and text.endswith("}"):
        out: dict[str, Any] = {}
        for part in _split_flow(text[1:-1]):
            key, sep, value = part.partition(":")
            if not sep:
                raise YamlError(f"flow mapping item without ':' -> {part!r}")
            out[key.strip().strip("'\"")] = _scalar(value)
        return out
    return text


def _key_value(text: str) -> tuple[str, str] | None:
    """``key: value`` (the key may be quoted or CJK); None when the text is not a mapping entry."""
    m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:\s][^:]*?)\s*:(?:\s+(.*)|\s*)$", text)
    if not m:
        return None
    key = m.group(1).strip()
    if key[0] in "'\"":
        key = key[1:-1]
    return key, (m.group(2) or "")


def load_yaml(text: str) -> Any:
    """The light YAML the writer uses: block mappings / lists (2-space indents), flow ``[...]`` / ``{...}``, quoted
    and plain scalars, ``|`` / ``>`` blocks and comments.  A JSON document is read as JSON."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    if stripped[0] in "[{":
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    raw = (text or "").replace("\t", "  ").splitlines()
    lines: list[tuple[int, str, int]] = []
    block_indent: int | None = None
    for no, line in enumerate(raw, 1):
        if block_indent is not None:
            indent = len(line) - len(line.lstrip(" "))
            if line.strip() == "" or indent > block_indent:
                lines.append((-1, line, no))
                continue
            block_indent = None
        clean = _strip_comment(line)
        if not clean.strip() or clean.strip() == "---":
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        lines.append((indent, clean.strip(), no))
        if clean.rstrip().endswith(("|", ">", "|-", ">-")):
            block_indent = indent
    pos = 0

    def block_scalar(style: str, parent: int) -> str:
        nonlocal pos
        body: list[str] = []
        while pos < len(lines) and lines[pos][0] == -1:
            body.append(lines[pos][1])
            pos += 1
        nonblank = [b for b in body if b.strip()]
        cut = min((len(b) - len(b.lstrip(" ")) for b in nonblank), default=0)
        rows = [b[cut:] for b in body]
        while rows and not rows[-1].strip():
            rows.pop()
        return ("\n".join(rows) if style.startswith("|") else " ".join(r.strip() for r in rows if r.strip()))

    def parse_value(rest: str, indent: int) -> Any:
        nonlocal pos
        rest = rest.strip()
        if rest in ("|", ">", "|-", ">-"):
            return block_scalar(rest, indent)
        if rest:
            return _scalar(rest)
        if pos < len(lines) and lines[pos][0] > indent:
            return parse_block(lines[pos][0])
        if pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            return parse_block(indent)  # "key:\n- a" (list at the key's own indent)
        return None

    def parse_block(indent: int) -> Any:
        nonlocal pos
        if pos >= len(lines):
            return None
        if lines[pos][1].startswith("- ") or lines[pos][1] == "-":
            out_list: list[Any] = []
            while pos < len(lines) and lines[pos][0] == indent and (lines[pos][1].startswith("- ")
                                                                     or lines[pos][1] == "-"):
                item = lines[pos][1][1:].strip()
                no = lines[pos][2]
                pos += 1
                kv = _key_value(item) if not item.startswith(("[", "{", '"', "'")) else None
                if kv is None:
                    if item:
                        out_list.append(_scalar(item))
                    else:
                        out_list.append(parse_block(lines[pos][0]) if pos < len(lines)
                                        and lines[pos][0] > indent else None)
                    continue
                child = indent + 2
                row: dict[str, Any] = {}
                key, rest = kv
                row[key] = parse_value(rest, child)
                while pos < len(lines) and lines[pos][0] == child and not lines[pos][1].startswith("- "):
                    kv2 = _key_value(lines[pos][1])
                    if kv2 is None:
                        raise YamlError(f"line {lines[pos][2]}: expected 'key: value' in list item from line {no}")
                    pos += 1
                    row[kv2[0]] = parse_value(kv2[1], child)
                out_list.append(row)
            return out_list
        out: dict[str, Any] = {}
        while pos < len(lines) and lines[pos][0] == indent:
            text, no = lines[pos][1], lines[pos][2]
            if text.startswith("- "):
                break
            kv = _key_value(text)
            if kv is None:
                raise YamlError(f"line {no}: expected 'key: value', got {text!r}")
            pos += 1
            out[kv[0]] = parse_value(kv[1], indent)
        return out

    result = parse_block(lines[0][0]) if lines else None
    if pos < len(lines):
        raise YamlError(f"line {lines[pos][2]}: unexpected indentation")
    return result


def _craft_ledger() -> Any:
    """WP6's module (``craft_ledger.py``: ledger / knowledge / series_card fields + the shared light-YAML parser),
    or None on an engine that does not ship it yet."""
    try:
        import craft_ledger as _cl  # noqa: PLC0415 -- same directory
        return _cl
    except Exception:  # noqa: BLE001
        return None


def read_light_yaml(text: str) -> Any:
    """The shared light-YAML reader: WP6's ``craft_ledger.load_light_yaml`` when present, else ``load_yaml``."""
    cl = _craft_ledger()
    loader = getattr(cl, "load_light_yaml", None) if cl else None
    if loader is not None:
        try:
            return loader(text)
        except Exception as exc:  # noqa: BLE001 -- report as ours
            raise YamlError(str(exc)) from exc
    return load_yaml(text)


def yaml_blocks_in_markdown(text: str) -> Any:
    """The first fenced ```yaml (or ```json) block of a markdown file (OUTLINE.md), parsed; None without one."""
    m = re.search(r"```(?:yaml|yml|json)\s*\n(.*?)\n```", text or "", re.DOTALL)
    return read_light_yaml(m.group(1)) if m else None


# =========================================================================== lexicons
_LEX_CACHE: dict[str, Any] = {}


def _lexicon(path: Path) -> dict[str, Any]:
    key = str(path)
    if key not in _LEX_CACHE:
        try:
            _LEX_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LEX_CACHE[key] = {}
    return _LEX_CACHE[key]


def emotion_lexicon() -> dict[str, Any]:
    return _lexicon(LEXICON_PATH)


def screenplay_lexicon() -> dict[str, Any]:
    return _lexicon(SCREENPLAY_LEXICON_PATH)


# =========================================================================== parse
_HEADING = re.compile(r"^##\s+(?P<num>S\d+)\s*(?P<rest>.*)$")
_CARD = re.compile(r"^@card\s+(?P<body>.+)$")
_REACTION = re.compile(r"^\[(?P<who>[^\]\s：:]+?)\s*反应\s*[：:](?P<text>[^\]]+)\]$")
_PROP = re.compile(r"^\{道具\s+(?P<name>[^\s@}]+)\s*(?:@(?P<owner>[^.\s}]+)(?:\.(?P<hand>[^\s}]+))?)?\s*"
                   r"(?P<desc>[^}]*)\}$")
_SILENT = re.compile(r"^[（(](?:无声|silent)[)）]\s*")
_DIALOGUE = re.compile(r"^(?P<pre>[^：:（(\[{。！？]{1,40}?)(?:[（(](?P<paren>[^）)]*)[）)])?\s*[：:](?P<line>.+)$")
_TAG = re.compile(r"\s+#(?P<tag>[^\s#]+)\s*$")


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


def _strip_markup(line: str) -> str:
    line = re.sub(r"^\s*>\s?", "", line)
    line = line.replace("**", "").replace("__", "")
    line = re.sub(r"\s*←.*$", "", line)  # format-doc annotations ("← action line")
    return line.strip()


def _tags(text: str) -> tuple[str, list[str]]:
    tags: list[str] = []
    while True:
        m = _TAG.search(text)
        if not m:
            break
        tags.insert(0, m.group("tag"))
        text = text[:m.start()].rstrip()
    return text, tags


def parse_card(body: str) -> dict[str, Any]:
    card: dict[str, Any] = {"goals": []}
    for part in re.split(r"\s*\|\s*", body.strip()):
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        m = re.fullmatch(r"goal\[(?P<who>[^\]]+)\]", key)
        if m:
            card["goals"].append({"who": m.group("who").strip(), "goal": value})
            card.setdefault("goal", value)
            card.setdefault("goal_owner", m.group("who").strip())
            continue
        if key == "source":
            card["source_detail_ids"] = [x.strip() for x in re.split(r"[;；]", value) if x.strip()]
            continue
        if key == "source_lines":
            card["source_lines"] = [x.strip() for x in re.split(r"[;；]", value) if x.strip()]
            continue
        card[key] = None if value in ("-", "", "—") else value
    return card


def parse(md: str) -> dict[str, Any]:
    """The screenplay as data: {title, scenes: [{num, heading, location_name, time, light, card, items, line_no}],
    errors}.  Items: action / dialogue / reaction / prop (each with ``tags`` and ``line_no``); names are resolved
    later (``compile``), so parse never needs the cast."""
    scenes: list[dict[str, Any]] = []
    errors: list[str] = []
    title = ""
    current: dict[str, Any] | None = None
    for no, raw in enumerate((md or "").splitlines(), 1):
        line = _strip_markup(raw)
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("# ") and current is None:
            title = line[2:].strip()
            continue
        m = _HEADING.match(line)
        if m:
            parts = [p.strip() for p in re.split(r"\s*[·•|｜]\s*", m.group("rest").strip()) if p.strip()]
            current = {"num": m.group("num").upper(), "heading": m.group("rest").strip(),
                       "location_name": parts[0] if parts else "", "time": parts[1] if len(parts) > 1 else "",
                       "light": parts[2] if len(parts) > 2 else "", "card": {"goals": []}, "items": [],
                       "line_no": no}
            scenes.append(current)
            continue
        if current is None:
            continue  # prose before the first scene (notes, title block)
        m = _CARD.match(line)
        if m:
            card = parse_card(m.group("body"))
            goals = current["card"].get("goals", []) + card.pop("goals", [])
            current["card"].update(card)
            current["card"]["goals"] = goals
            continue
        text, tags = _tags(line)
        m = _REACTION.match(text)
        if m:
            current["items"].append({"kind": "reaction", "who": m.group("who").strip(), "text": m.group("text").strip(),
                                     "tags": tags, "line_no": no})
            continue
        m = _PROP.match(text)
        if m:
            current["items"].append({"kind": "prop", "name": m.group("name"), "owner": m.group("owner") or "",
                                     "hand": m.group("hand") or "", "description": (m.group("desc") or "").strip(),
                                     "tags": tags, "line_no": no})
            continue
        silent = bool(_SILENT.match(text))
        if silent:
            text = _SILENT.sub("", text)
        m = None if silent else _DIALOGUE.match(text)
        if m:
            current["items"].append({"kind": "dialogue_candidate", "pre": m.group("pre").strip(),
                                     "paren": (m.group("paren") or "").strip(), "line": m.group("line").strip(),
                                     "raw": text, "tags": tags, "line_no": no})
            continue
        current["items"].append({"kind": "action", "text": text, "silent": silent, "tags": tags, "line_no": no})
    if not scenes:
        errors.append("SCREENPLAY_NO_SCENES")
    seen: set[str] = set()
    for scene in scenes:
        if scene["num"] in seen:
            errors.append(f"SCREENPLAY_SCENE_DUPLICATE:{scene['num']}")
        seen.add(scene["num"])
    return {"title": title, "scenes": scenes, "errors": errors}


# =========================================================================== cast / names
class Cast:
    """Cast rows from CAST_PROPS (+ the series card) and their name index (longest label first)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.labels: list[tuple[str, str]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            cid = _clean(row.get("id") or row.get("character_id"))
            name = _clean(row.get("name") or row.get("canonical_name"))
            if not cid or not name:
                continue
            self.rows[cid] = row
            for label in [name] + [_clean(a) for a in row.get("aliases") or [] if _clean(a)] + \
                    [_clean(a) for a in row.get("short_names") or [] if _clean(a)]:
                self.labels.append((label, cid))
        self.labels.sort(key=lambda x: -len(x[0]))

    def name(self, cid: str) -> str:
        row = self.rows.get(cid) or {}
        return _clean(row.get("name") or row.get("canonical_name")) or cid

    def short(self, cid: str) -> str:
        row = self.rows.get(cid) or {}
        shorts = [_clean(a) for a in row.get("short_names") or [] if _clean(a)]
        return shorts[0] if shorts else self.name(cid)

    def resolve(self, label: str) -> str | None:
        label = _clean(label)
        for text, cid in self.labels:
            if text == label:
                return cid
        return None

    def prefix(self, text: str) -> tuple[str, str] | None:
        """(cid, label) of the cast name ``text`` starts with (longest label)."""
        for label, cid in self.labels:
            if text.startswith(label):
                return cid, label
        return None

    def mentions(self, text: str) -> list[str]:
        """Character ids named in ``text``, in order of first mention (longest label wins at a position)."""
        found: list[tuple[int, str]] = []
        taken: list[tuple[int, int]] = []
        for label, cid in self.labels:
            for m in re.finditer(re.escape(label), text or ""):
                span = (m.start(), m.end())
                if any(a < span[1] and span[0] < b for a, b in taken):
                    continue
                taken.append(span)
                found.append((m.start(), cid))
        out: list[str] = []
        for _, cid in sorted(found):
            if cid not in out:
                out.append(cid)
        return out


# =========================================================================== emotion
def derive_emotion(paren: str, line: str, scene_type: str, explicit: str = "") -> tuple[str, str]:
    """(lexicon word, basis): the parenthetical's cue words, else the scene type, else the line's punctuation."""
    lex = emotion_lexicon()
    allowed = set(lex.get("emotions") or [])
    if explicit and explicit in allowed:
        return explicit, "explicit"
    cues = screenplay_lexicon().get("emotion_cues") or {}
    best: tuple[int, int, str] | None = None
    for word, keys in cues.items():
        if word not in allowed:
            continue
        for key in keys:
            at = (paren or "").find(key)
            if at >= 0:
                cand = (at, -len(key), word)
                best = cand if best is None or cand < best else best
    if best:
        return best[2], "parenthetical"
    by_type = screenplay_lexicon().get("scene_type_emotion") or {}
    hits = [k for k, w in by_type.items() if k in (scene_type or "") and w in allowed]
    if hits:
        # the scene type's LAST matching word (争吵→喜剧落空 ends as comedy)
        return by_type[max(hits, key=lambda k: (scene_type or "").rfind(k))], "scene_type"
    text = line or ""
    if re.search(r"[？?]\s*$", text):
        return ("疑" if "疑" in allowed else sorted(allowed)[0]), "punctuation"
    if re.search(r"[！!]\s*$", text):
        return ("急" if "急" in allowed else sorted(allowed)[0]), "punctuation"
    return ("冷" if "冷" in allowed else sorted(allowed)[0]), "default"


# =========================================================================== translations
def en_key(field: str, zh: str) -> str:
    return hashlib.sha256(f"{field}\n{_clean(zh)}".encode("utf-8")).hexdigest()[:16]


class Translations:
    """The writer's English answers.  ``fallback=True`` (the request went unanswered past the writer resumes; owner
    rule "never stall the line") fills a missing row with the compiler's own English and logs it."""

    def __init__(self, answers: dict[str, Any] | None, *, fallback: bool = False) -> None:
        rows = (answers or {}).get("rows") if isinstance(answers, dict) else None
        self.rows: dict[str, str] = {str(k): _clean(v) for k, v in (rows or {}).items() if _clean(v)}
        self.requests: dict[str, dict[str, Any]] = {}
        self.used: set[str] = set()
        self.fallback = fallback
        self.fallback_log: list[tuple[str, str, str]] = []  # (where, field, key)

    def get(self, field: str, zh: str, where: str, fallback: str = "") -> str:
        zh = _clean(zh)
        if not zh:
            return ""
        key = en_key(field, zh)
        self.used.add(key)
        value = self.rows.get(key, "")
        if not value:
            self.requests.setdefault(key, {"key": key, "field": field, "zh": zh, "where": []})["where"].append(where)
            if self.fallback and fallback:
                self.fallback_log.append((where, field, key))
                return fallback
        return value

    def fallback_fields(self, where: str) -> list[str]:
        return list(dict.fromkeys(f for w, f, _ in self.fallback_log if w == where))


# =========================================================================== compile
def _sec_half(value: float) -> float:
    import math
    return math.ceil(value * 2 - 1e-9) / 2.0


def _dialogue_seconds(dialogue: str, language: str) -> float:
    try:
        import nalu_writer_selfcheck_seq29 as _s29  # noqa: PLC0415 -- same directory
        return float(_s29.derived_dialogue_seconds(dialogue, 4.0, {"chinese_characters_per_second": 4.0},
                                                   language))
    except Exception:  # noqa: BLE001
        spoken = dialogue.split("：", 1)[-1]
        return _sec_half(len(re.findall(r"[㐀-鿿]", spoken)) / 4.0 + 0.5)


def _has_any(text: str, words: list[str]) -> bool:
    return any(w and w in (text or "") for w in words)


def _contact(text: str) -> bool:
    return _has_any(text, screenplay_lexicon().get("contact_verbs_zh") or [])


def _dims(texts: list[str], speaking: bool) -> list[str]:
    blob = " ".join(texts)
    dims: list[str] = []
    if _contact(blob):
        dims.append("CONTACT")
    if _has_any(blob, ["递", "接过", "收回", "亮到", "拿起", "抢", "夺", "塞", "交给", "放下"]):
        dims.append("POSSESSION")
    if _has_any(blob, ["起身", "下两级", "走", "冲上", "进", "出殿", "退", "转身", "跨", "坐直", "站起", "离开"]):
        dims.append("POSITION")
    if not dims or speaking:
        dims.append("POSTURE")
    return list(dict.fromkeys(dims))


def _sentence(text: str) -> str:
    text = _clean(text)
    return text if re.search(r"[。！？…!?.]$", text) else text + "。"


def _scene_id(episode: str, num: str) -> str:
    return f"{episode}-{num}"


def _resolve_location(scene: dict[str, Any], locations: list[dict[str, Any]]) -> dict[str, Any]:
    wanted = _clean(scene["card"].get("location"))
    for row in locations:
        if wanted and _clean(row.get("id")) == wanted:
            return row
    name = scene.get("location_name") or ""
    for row in locations:
        names = [_clean(row.get("name"))] + [_clean(a) for a in row.get("aliases") or []]
        if any(n and (n == name or n in name or name in n) for n in names):
            return row
    return {}


def _shot_items(scene: dict[str, Any], cast: Cast, errors: list[str]) -> list[dict[str, Any]]:
    """Resolve dialogue candidates (a cast name before '：') and group the scene's items into shots."""
    items: list[dict[str, Any]] = []
    for it in scene["items"]:
        if it["kind"] != "dialogue_candidate":
            items.append(it)
            continue
        pre = it["pre"]
        cid = cast.resolve(pre)
        inline_action = ""
        if not cid:
            hit = cast.prefix(pre)
            if hit and len(pre) > len(hit[1]) and not it["paren"]:
                cid, inline_action = hit[0], pre
        if not cid:
            # not a speaker: an action sentence that happens to contain '：'
            items.append({"kind": "action", "text": it["raw"], "silent": False, "tags": it["tags"],
                          "line_no": it["line_no"]})
            continue
        items.append({"kind": "dialogue", "speaker": cid, "paren": it["paren"], "line": it["line"],
                      "inline_action": inline_action, "tags": it["tags"], "line_no": it["line_no"]})

    def subject_of(text: str) -> str:
        hit = cast.prefix(text)
        if hit:
            return hit[0]
        named = cast.mentions(text)
        return named[0] if named else ""

    shots: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    lead_in: list[dict[str, Any]] = []
    props_next: list[dict[str, Any]] = []

    def next_dialogue(index: int) -> dict[str, Any] | None:
        for it in items[index + 1:]:
            if it["kind"] == "dialogue":
                return it
            if it["kind"] == "action" and it.get("silent"):
                return None
        return None

    def new_shot(kind: str, **kw: Any) -> dict[str, Any]:
        shot = {"kind": kind, "actions": [], "reactions": [], "lead_in": list(lead_in), "props": list(props_next),
                "tags": [], **kw}
        lead_in.clear()
        props_next.clear()
        shots.append(shot)
        return shot

    for index, it in enumerate(items):
        kind = it["kind"]
        if kind == "prop":
            props_next.append(it)
            continue
        if kind == "dialogue":
            shot = new_shot("dialogue", speaker=it["speaker"], paren=it["paren"], line=it["line"],
                            line_no=it["line_no"])
            shot["actions"] = pending + ([{"kind": "action", "text": it["inline_action"], "tags": [],
                                            "line_no": it["line_no"], "inline": True}]
                                          if it["inline_action"] else [])
            shot["tags"] = list(dict.fromkeys([t for a in pending for t in a.get("tags") or []] + it["tags"]))
            pending = []
            continue
        if kind == "action":
            it = {**it, "subject": subject_of(it["text"])}
            if it.get("silent"):
                shot = new_shot("silent", line_no=it["line_no"])
                shot["actions"] = pending + [it]
                shot["tags"] = list(dict.fromkeys([t for a in shot["actions"] for t in a.get("tags") or []]))
                pending = []
                continue
            prev = shots[-1] if shots else None
            nxt = next_dialogue(index)
            if (prev is not None and not pending and prev["kind"] == "dialogue" and it["subject"]
                    and it["subject"] == prev.get("speaker") and (nxt is None or nxt["speaker"] != it["subject"])):
                prev["actions"].append(it)
                prev["tags"] = list(dict.fromkeys(prev["tags"] + (it.get("tags") or [])))
                continue
            pending.append(it)
            continue
        if kind == "reaction":
            who = cast.resolve(it["who"]) or (cast.prefix(it["who"]) or ("", ""))[0]
            if not who:
                errors.append(f"SCREENPLAY_REACTION_WHO_UNKNOWN:{scene['num']}:{it['who']}")
                continue
            row = {**it, "who_id": who}
            if pending or not shots:
                lead_in.append(row)
            else:
                shots[-1]["reactions"].append(row)
                shots[-1]["tags"] = list(dict.fromkeys(shots[-1]["tags"] + (it.get("tags") or [])))
    if pending:
        shot = new_shot("silent", line_no=pending[0]["line_no"])
        shot["actions"] = pending
        shot["tags"] = list(dict.fromkeys([t for a in pending for t in a.get("tags") or []]))
    if lead_in and shots:
        shots[-1]["reactions"].extend(lead_in)
        lead_in.clear()
    if props_next and shots:
        shots[-1]["props"].extend(props_next)
    return shots


def _offscreen(paren: str) -> bool:
    tokens = [t.strip() for t in re.split(r"[，,、；;\s]+", paren or "") if t.strip()]
    offs = set(screenplay_lexicon().get("offscreen_tokens") or [])
    return any(t.upper() in {o.upper() for o in offs} for t in tokens)


def _addressee(paren: str, cast: Cast) -> str:
    m = re.search(r"对([^，,、；;）)]+)", paren or "")
    if m:
        return cast.resolve(m.group(1)) or (cast.prefix(m.group(1)) or ("", ""))[0]
    return ""


def _explicit_emotion(paren: str) -> str:
    m = re.search(r"(?:情绪|emotion)\s*[=＝:：]\s*(\S)", paren or "")
    return m.group(1) if m else ""


def _delivery_cues(paren: str) -> str:
    tokens = [t.strip() for t in re.split(r"[，,、；;]+", paren or "") if t.strip()]
    offs = {o.upper() for o in screenplay_lexicon().get("offscreen_tokens") or []}
    keep = [t for t in tokens if t.upper() not in offs and not re.match(r"^(?:对|情绪|emotion)", t)]
    return "，".join(keep)


def compile_screenplay(parsed: dict[str, Any], cast_props: dict[str, Any], series_card: dict[str, Any] | None,
                       outline: dict[str, Any] | None, *, episode: str, translations: dict[str, Any] | None = None,
                       brief: dict[str, Any] | None = None, en_fallback: bool = False) -> dict[str, Any]:
    """{contract, narrative_md, directing_md, manifest, en_request, report}.  Pure.  ``en_fallback``: fill English
    twins the writer never answered with compiler English (marked fallback; ``report.en_fallback_used``)."""
    errors: list[str] = list(parsed.get("errors") or [])
    warnings: list[str] = []
    cast_props = cast_props if isinstance(cast_props, dict) else {}
    series_card = series_card if isinstance(series_card, dict) else {}
    outline = outline if isinstance(outline, dict) else {}
    brief = brief if isinstance(brief, dict) else {}
    episode = _clean(episode or cast_props.get("episode")).upper()
    language = _clean(cast_props.get("dialogue_language") or brief.get("dialogue_language") or "zh") or "zh"
    cast = Cast(list(cast_props.get("cast") or []))
    if not cast.rows:
        errors.append("CAST_PROPS_NO_CAST")
    tr = Translations(translations, fallback=en_fallback)
    locations = [r for r in cast_props.get("locations") or [] if isinstance(r, dict)]
    prop_rows: dict[str, dict[str, Any]] = {}
    for row in cast_props.get("props") or []:
        if isinstance(row, dict) and _clean(row.get("id")) and _clean(row.get("name")):
            prop_rows[_clean(row["id"])] = dict(row)

    def prop_by_name(name: str) -> str:
        for pid, row in prop_rows.items():
            if name in [_clean(row.get("name"))] + [_clean(a) for a in row.get("aliases") or []]:
                return pid
        return ""

    shots_out: list[dict[str, Any]] = []
    scene_states: list[dict[str, Any]] = []
    scene_plan: list[dict[str, Any]] = []
    block_scenes: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    dialogue_units: list[dict[str, Any]] = []
    ambient_by_scene: dict[str, Any] = {}
    beat_sheet: list[dict[str, Any]] = []
    first_shot: dict[str, str] = {}
    prop_uses: dict[str, list[str]] = {}
    narrative: list[str] = []
    directing: list[str] = []
    structure: list[dict[str, Any]] = []
    tag_roles = screenplay_lexicon().get("tag_beat_roles") or {}
    turn_shots: dict[str, tuple[str, str]] = {}

    for scene in parsed.get("scenes") or []:
        sid = _scene_id(episode, scene["num"])
        card = scene["card"]
        loc = _resolve_location(scene, locations)
        if not loc:
            errors.append(f"SCREENPLAY_LOCATION_UNDECLARED:{scene['num']}:{scene.get('location_name')}")
        loc_id = _clean(loc.get("id")) or f"LOC-{scene['num']}"
        loc_name = _clean(loc.get("name")) or scene.get("location_name") or loc_id
        set_pieces = [_clean(x) for x in loc.get("set_pieces") or [] if _clean(x)]
        ambience = _clean(loc.get("ambience")) or f"{loc_name}的环境声"
        if not _clean(loc.get("ambience")):
            warnings.append(f"LOCATION_AMBIENCE_FALLBACK:{loc_id}")
        time_of_day = scene.get("time") or _clean(loc.get("time"))
        light = scene.get("light") or _clean(loc.get("light"))
        weather = _clean(loc.get("weather")) or "晴"
        scene_type = _clean(card.get("type"))
        for pr in [it for it in scene["items"] if it["kind"] == "prop"]:
            pid = prop_by_name(pr["name"])
            owner = cast.resolve(pr["owner"]) if pr["owner"] else ""
            if not pid:
                pid = "PROP-" + hashlib.sha256(pr["name"].encode("utf-8")).hexdigest()[:8].upper()
                prop_rows[pid] = {"id": pid, "name": pr["name"], "owner": owner, "hand": pr["hand"],
                                  "description": pr["description"] or pr["name"], "declared_in": "screenplay"}
            else:
                prop_rows[pid].setdefault("owner", owner)
                if pr["hand"]:
                    prop_rows[pid]["hand"] = pr["hand"]
        shots = _shot_items(scene, cast, errors)
        present: list[str] = []
        for sh in shots:
            for cid in ([sh.get("speaker")] if sh.get("speaker") and not _offscreen(sh.get("paren", "")) else []) + \
                    [c for a in sh["actions"] for c in cast.mentions(a["text"])] + \
                    [r["who_id"] for r in sh["reactions"] + sh["lead_in"]]:
                if cid and cid not in present:
                    present.append(cid)
        block_lines: list[dict[str, Any]] = []
        prev_completion = ""
        prev_speaker = ""
        scene_shot_ids: list[str] = []
        narrative.append(f"## {sid}｜{loc_id}｜{time_of_day or '—'}｜线A")
        narrative.append("")
        directing.append(f"## {sid} {loc_name} · {time_of_day} · {light}")
        directing.append(f"场景卡：目标={card.get('goal') or '—'}｜阻力={card.get('obstacle') or '—'}｜"
                         f"转折={card.get('turn') or '—'}｜类型={scene_type or '—'}")
        directing.append("")
        for index, sh in enumerate(shots, 1):
            shot_id = f"{sid}-{index:02d}"
            scene_shot_ids.append(shot_id)
            speaking = sh["kind"] == "dialogue"
            speaker = sh.get("speaker") or ""
            paren = sh.get("paren") or ""
            offscreen_speaker = speaking and _offscreen(paren)
            action_texts = [_sentence(a["text"]) for a in sh["actions"]]
            own_actions = [a for a in sh["actions"] if a.get("subject") == speaker or a.get("inline")]
            subject = speaker if speaking and not offscreen_speaker else \
                (next((a.get("subject") for a in sh["actions"] if a.get("subject")), "") or speaker)
            if speaking and not offscreen_speaker and not own_actions:
                # the line's only action belongs to someone else (商余烬 laughs, 白桃 asks "你笑什么"): the frame's
                # action -- and the reaction WP3 measures -- is that character's, the speaker keeps the lips
                partner = next((a.get("subject") for a in sh["actions"] if a.get("subject") not in ("", speaker)), "")
                subject = partner or subject
            if not subject:
                subject = present[0] if present else ""
            addressee = _addressee(paren, cast) if speaking else ""
            if speaking and not addressee:
                # whoever the attached action puts opposite the speaker, else the last other speaker, else anyone
                partners = [a.get("subject") for a in sh["actions"] if a.get("subject") not in ("", speaker)] + \
                    [c for a in sh["actions"] for c in cast.mentions(a["text"]) if c != speaker]
                others = [c for c in present if c != speaker]
                addressee = (partners[0] if partners else
                             prev_speaker if prev_speaker and prev_speaker != speaker else (others[0] if others else ""))
            # who is visible: the speaker (unless OS), whoever the actions put on screen, the reaction owners, and
            # the addressee as an over-the-shoulder listener (11-23 rule: dialogue with the listener in frame)
            named: list[str] = []
            for a in sh["actions"]:
                for cid in cast.mentions(a["text"]):
                    if cid not in named:
                        named.append(cid)
            reactors = [r["who_id"] for r in sh["reactions"] + sh["lead_in"]]
            visible: list[tuple[str, str]] = []
            if speaking and not offscreen_speaker:
                visible.append((speaker, "FRONT_FACE_VISIBLE"))
            for cid in named + reactors:
                if cid and cid not in [v[0] for v in visible] and not (offscreen_speaker and cid == speaker
                                                                         and cid not in named):
                    visible.append((cid, "THREE_QUARTER_BUST" if speaking else "FRONT_FACE_VISIBLE"))
            if speaking and addressee and addressee not in [v[0] for v in visible] and len(present) >= 2:
                # an OS line plays on the listener's face; an on-screen line keeps the listener over the shoulder
                visible.append((addressee, "FRONT_FACE_VISIBLE" if offscreen_speaker else "BACK_AND_SHOULDERS_ONLY"))
            if not visible and subject:
                visible.append((subject, "FRONT_FACE_VISIBLE"))
            cast_rows = []
            for cid, face in visible:
                row = cast.rows.get(cid) or {}
                cast_rows.append({"character": cast.name(cid), "character_id": cid, "life_state": "alive",
                                  "face_visibility": face, "first_frame_visible": True,
                                  **({"wardrobe_garments": _wardrobe(row)} if _wardrobe(row) else {})})
            # props on this shot: declared on it, or named in its action text (owner + hand carried)
            shot_props: list[dict[str, Any]] = []
            for pr in sh["props"]:
                pid = prop_by_name(pr["name"])
                if pid and pid not in [p["prop_id"] for p in shot_props]:
                    shot_props.append(_prop_ref(prop_rows[pid], cast))
            blob = " ".join(action_texts + [r["text"] for r in sh["reactions"] + sh["lead_in"]])
            for pid, row in prop_rows.items():
                names = [_clean(row.get("name"))] + [_clean(a) for a in row.get("aliases") or []]
                if any(n and n in blob for n in names) and pid not in [p["prop_id"] for p in shot_props]:
                    shot_props.append(_prop_ref(row, cast))
            for p in shot_props:
                prop_uses.setdefault(p["prop_id"], []).append(shot_id)
            line = sh.get("line") or ""
            tags = list(sh.get("tags") or [])
            dialogue = f"{cast.name(speaker)}：{line}" if speaking else ""
            explicit = _explicit_emotion(paren)
            own_text = "".join(a["text"] for a in own_actions)
            emotion, emotion_basis = derive_emotion(paren + ("；" + own_text if own_text else ""), line, scene_type,
                                                    explicit)
            cues = _delivery_cues(re.sub(r"(?:情绪|emotion)\s*[=＝:：]\s*\S", "", paren))
            sources: dict[str, str] = {}
            listener_name = cast.name(addressee) if addressee else ""
            # primary action / states
            if action_texts:
                primary = "".join(action_texts)
                sources["primary_action"] = AUTHORED
            elif speaking:
                primary = f"{cast.name(speaker)}对{listener_name or '众人'}说出「{line}」"
                sources["primary_action"] = FALLBACK
            else:
                primary = ""
            reaction_zh = "；".join(f"{cast.name(r['who_id'])}：{r['text']}" for r in sh["reactions"])
            lead_zh = "；".join(f"{cast.name(r['who_id'])}：{r['text']}" for r in sh["lead_in"])
            if not prev_completion:
                opening = next((a for a in scene["items"] if a["kind"] == "action"), None)
                entry = _sentence(opening["text"]) if opening and index == 1 and action_texts else ""
                entry = entry or f"{loc_name}里，{'、'.join(cast.name(c) for c, _ in visible) or '众人'}已在场"
                sources["entry_state"] = AUTHORED if (opening and index == 1 and action_texts) else FALLBACK
                entry = "开场：" + entry if sources["entry_state"] == AUTHORED else entry
            else:
                # the head names this shot's own people (the keyframe binds them), then carries the last beat
                entry = (f"{'、'.join(cast.name(c) for c, _ in visible) or loc_name}在{loc_name}；"
                         f"承上一拍：{prev_completion}")
                sources["entry_state"] = "carried"
            if own_actions or (action_texts and not speaking):
                completion = _sentence((own_actions or sh["actions"])[-1]["text"])
                sources["completion_state"] = AUTHORED
            elif sh["reactions"]:
                completion = _sentence(f"{cast.name(sh['reactions'][-1]['who_id'])}{sh['reactions'][-1]['text']}")
                sources["completion_state"] = AUTHORED
            else:
                said = line if len(line) <= 16 else line[:15] + "…"
                completion = f"{cast.name(speaker)}说完「{said}」，{listener_name or '对方'}还没有接话"
                sources["completion_state"] = FALLBACK
            if _clean(entry) == _clean(completion):
                completion = completion + "（本拍结束）"
            prev_completion = completion.rstrip("。")
            body_action = "".join(_sentence(a["text"]) for a in own_actions) or (cues and f"{cast.name(speaker)}{cues}")
            sources["body_action"] = AUTHORED if body_action else FALLBACK
            if not body_action and speaking:
                body_action = f"{cast.name(speaker)}说「{line[:10]}」时身体前倾半步、视线压住{listener_name or '对方'}"
            delivery = cues or f"按「{emotion}」说出这一句"
            sources["delivery"] = AUTHORED if cues else FALLBACK
            # English twins (Codex translates the request rows in the same run)
            own_text = "".join(_sentence(a["text"]) for a in own_actions)
            business_en = tr.get("action", own_text, shot_id, _en_action_fallback(cast, own_text)) \
                if own_actions else ""
            action_en = tr.get("action", "".join(action_texts), shot_id,
                               _en_action_fallback(cast, "".join(action_texts))) if action_texts else ""
            delivery_en = tr.get("delivery", delivery, shot_id,
                                 EMOTION_EN.get(emotion, "steady") + ", clear and natural") if speaking and cues else ""
            # WP4 EN twins: an authored zh field is translated (request rows); a compiler fallback gets the
            # compiler's own English (marked fallback, never sent to the translator)
            if speaking and not action_texts:
                action_en = (f"{_en_name(cast, speaker)} says the line to {_en_name(cast, addressee)}"
                             if addressee else f"{_en_name(cast, speaker)} says the line")
                sources["business_en"] = FALLBACK
            if speaking and not cues:
                delivery_en = EMOTION_EN.get(emotion, "steady") + ", clear and natural, the voice unchanged"
                sources["delivery_en"] = FALLBACK
            reaction_en = tr.get("reaction", reaction_zh, shot_id, _en_reaction_fallback(cast, sh["reactions"])) \
                if reaction_zh else ""
            lead_en = tr.get("reaction", lead_zh, shot_id, _en_reaction_fallback(cast, sh["lead_in"])) \
                if lead_zh else ""
            for field in tr.fallback_fields(shot_id):
                sources[{"action": "business_en", "delivery": "delivery_en", "reaction": "reaction_en"}
                        .get(field, field + "_en")] = FALLBACK
            beat_role = "LINE" if speaking else "ACTION"
            for tag in tags:
                head, _, sub = tag.partition(":")
                role = tag_roles.get(head)
                if role and role != "REPORT":
                    beat_role = role
                if head in ("转折", "爽点", "揭示", "攻击", "笑点") and (sub or head in ("转折", "爽点", "揭示")):
                    kind = sub.upper() if sub else {"转折": "REVERSAL", "爽点": "POWER_SHIFT",
                                                    "揭示": "IDENTITY_REVEAL"}[head]
                    beat_sheet.append({"shot_id": shot_id, "type": kind,
                                       "setup_shot_id": scene_shot_ids[-2] if len(scene_shot_ids) > 1 else shot_id})
            is_turn = "转折" in [t.partition(":")[0] for t in tags] or \
                (card.get("turn_line") and str(card.get("turn_line")) in line)
            n_visible = len([v for v in visible if v[1] != "BACK_AND_SHOULDERS_ONLY"])
            entrance = _has_any(" ".join(action_texts), screenplay_lexicon().get("entrance_words_zh") or [])
            if not speaking or entrance:
                scale = "WIDE" if (entrance or len(visible) >= 3) else "MEDIUM"
            elif is_turn:
                scale = "CLOSE_UP"
            elif index == 1 or n_visible >= 2:
                scale = "MEDIUM"
            else:
                scale = "MEDIUM_CLOSE_UP"
            push = bool(is_turn)
            motion = {"motion_family": "DOLLY", "motion_direction": "PUSH_IN"} if push else \
                {"motion_family": "LOCKED", "motion_direction": "NONE"}
            names_visible = "、".join(cast.name(c) for c, f in visible if f != "BACK_AND_SHOULDERS_ONLY")
            ots = [cast.name(c) for c, f in visible if f == "BACK_AND_SHOULDERS_ONLY"]
            piece = set_pieces[(index - 1) % len(set_pieces)] if set_pieces else loc_name
            framing = (f"{names_visible or cast.name(subject)}在{loc_name}{piece}旁"
                       + (f"，{'、'.join(ots)}的后脑与肩在前景虚化" if ots else "")
                       + (f"，{light}" if light else ""))
            if speaking and not offscreen_speaker:
                framing += f"；{cast.name(speaker)}视线略偏离镜头，朝{listener_name or '对方'}一侧"
            camera_text = (f"{scale}，" + ("缓推约一成，「动机：本场转折」" if push else "固定机位")
                           + (f"，过肩{'、'.join(ots)}" if ots else ""))
            cps = 4.0
            if speaking:
                seconds = _dialogue_seconds(dialogue, language)
                target = max(_sec_half(seconds), 4.0)
            else:
                target = SILENT_SECONDS
            dims = _dims(action_texts, speaking)
            entity_states = {cid: (completion if cid == subject else f"{cast.name(cid)}在{piece}旁")
                             for cid, _ in visible}
            presence = {cid: "VISIBLE_AND_IDENTITY_LOCKED" for cid, _ in visible}
            if offscreen_speaker:
                presence[speaker] = "OFFSCREEN_VOICE_ONLY"
            role = {
                "status": "PASS",
                "primary_actor": cast.name(subject) if subject else "",
                "primary_actor_id": subject,
                "primary_actor_kind": "CHARACTER",
                "dialogue_speaker": cast.name(speaker) if speaking else "",
                "dialogue_speaker_id": speaker if speaking else "",
                "dialogue_listener": listener_name if speaking else "",
                "dialogue_listener_id": addressee if speaking else "",
                "lip_owner_id": speaker if speaking and not offscreen_speaker else "",
                "entity_states": entity_states,
                "entity_presence": presence,
            }
            if offscreen_speaker:
                # an OS line: the frame belongs to whoever is on screen
                role["primary_actor"] = cast.name(subject) if subject != speaker else (
                    cast.name(visible[0][0]) if visible else "")
                role["primary_actor_id"] = subject if subject != speaker else (visible[0][0] if visible else "")
            actor = role["primary_actor_id"]
            touch_partner = ""
            if _contact(" ".join(action_texts)):
                others_named = [c for c in named if c != actor]
                touch_partner = others_named[0] if others_named else ""
            action: dict[str, Any] = {
                "subject_id": actor,
                "initiator_entity_id": actor,
                "target_entity_id": touch_partner or actor,
                "interaction_mode": "CONTACT" if touch_partner else "NONE",
                "action_kind": "NON_COMBAT",
                "primary_action": primary,
                "start_state": entry,
                "completion_state": completion,
                "physical_causality": (f"{cast.name(actor)}的动作直接作用于{cast.name(touch_partner)}，对方随之反应"
                                       if touch_partner else f"由{cast.name(actor) if actor else '在场者'}的这一句/这一动作引出"),
                "state_delta_dimensions": dims,
                "state_delta_evidence": {d: {"entry": entry, "exit": completion} for d in dims},
                "source": AUTHORED if sources.get("primary_action") == AUTHORED else FALLBACK,
                "field_sources": sources,
            }
            if speaking:
                action["performance"] = {"emotion": emotion, "emotion_basis": emotion_basis,
                                         "body_action": body_action, "delivery": delivery,
                                         **({"delivery_en": delivery_en} if delivery_en else {}),
                                         **({"business_en": business_en} if business_en else {})}
            if reaction_zh:
                action["listener_reaction"] = reaction_zh
                if reaction_en:
                    action["listener_reaction_en"] = reaction_en
            if lead_zh:
                action["lead_in_reaction"] = lead_zh
                if lead_en:
                    action["lead_in_reaction_en"] = lead_en
            if action_en:
                action["action_en"] = action_en
                action["business_en"] = action_en  # WP4: primary_action's English twin
            for key, rows in (("listener_reaction_by", sh["reactions"]), ("lead_in_reaction_by", sh["lead_in"])):
                if rows:
                    action[key] = list(dict.fromkeys(r["who_id"] for r in rows))
            if touch_partner:
                action["contact_point"] = next((a["text"] for a in sh["actions"] if _contact(a["text"])), "")
            tag_heads = [t.partition(":")[0] for t in tags]
            wp6: dict[str, Any] = {}
            if "招牌" in tag_heads:
                wp6["signature_business"] = actor or speaker
            if "双关" in tag_heads:
                wp6["double_meaning"] = True
            for tag in tags:
                head, _, rest = tag.partition(":")
                if head == "先物":  # #先物:PROP:战神令:TILT_UP -- object-first entrance (WP6 / WP3 director pass)
                    bits = rest.split(":")
                    wp6["object_first"] = {"subject": (bits[0] or "PROP").upper(),
                                           **({"of": bits[1]} if len(bits) > 1 and bits[1] else {}),
                                           "then": (bits[2] if len(bits) > 2 and bits[2] else "TILT_UP").upper()}
            if push:
                turn_shots.setdefault(sid, (shot_id, actor or speaker))
            spec: dict[str, Any] = {
                "space": {"location": loc_id, "subspace": piece},
                "scene_state": {"time": time_of_day, "weather": weather, "light": light},
                "cast": cast_rows,
                "dialogue": dialogue,
                "dialogue_delivery": {"chinese_characters_per_second": cps},
                "action": action,
                "camera_plan": {"shot_scale": scale, "camera_height": "EYE_LEVEL",
                                "camera_side": "AXIS_A", **motion,
                                "lens_intent": f"{'过肩' if ots else '单人'}{'推近' if push else '固定'}：{(card.get('turn') if push else card.get('goal')) or line[:10] or primary[:10]}",
                                "axis_relation": "SAME_SIDE",
                                "start_framing": framing,
                                "end_framing": framing + ("（推近后略紧）" if push else ""),
                                "motivation": ("动机：本场转折——" + (card.get("turn") or line[:12])) if push else
                                              f"固定看清{cast.name(actor) if actor else loc_name}这一拍"},
                "role_semantic_disambiguation": role,
                "props": shot_props,
                "sound": {"ambience": ambience, "sfx": [], "music": "SELECTIVE_BGM"},
                "beat_role": beat_role,
                "internal_transition_authoring": {"transition_mode": "CONTINUOUS_ACTION",
                                                  "reason": f"{scene['num']}第{index}拍接上一拍"},
                **({"offscreen_character_ids": [speaker]} if offscreen_speaker else {}),
                **wp6,
            }
            shot = {
                "shot_id": shot_id, "scene_id": sid, "location_id": loc_id, "target_seconds": target,
                "shot_size": scale, "camera": camera_text, "subspace_id": piece,
                "frame_content": primary or framing, "blocking": primary or framing,
                "entry_state": entry, "completion_state": completion,
                "first_frame_motion_state": entry,
                "state_delta_dimensions": dims,
                "state_delta_evidence": {d: {"entry": entry, "exit": completion} for d in dims},
                "dialogue_delivery": {"chinese_characters_per_second": cps},
                **({"dialogue": dialogue} if dialogue else {}),
                "prompt_spec": spec,
                "internal_transition_authoring": dict(spec["internal_transition_authoring"]),
                "incoming_transition_mode": "CONTINUOUS_ACTION",
                "axis": _clean(loc.get("axis")) or f"{loc_name}：{'—'.join(set_pieces[:2]) or loc_name}一线",
                "screenplay_ref": {"line_no": sh.get("line_no"), "kind": sh["kind"]},
            }
            shots_out.append(shot)
            for cid, _ in visible:
                first_shot.setdefault(cid, shot_id)
            if speaking:
                dialogue_units.append({"shot_id": shot_id, "speaker_id": speaker, "listener_id": addressee or None,
                                       "text": line, "emotion": emotion, "language": "zh-CN" if language == "zh"
                                       else language,
                                       **({"offscreen": True} if offscreen_speaker else {})})
                if dialogue_units[-1]["listener_id"] is None:
                    dialogue_units[-1].pop("listener_id")
                prev_speaker = speaker
            if len(scene_shot_ids) > 1:
                transitions.append({"from_shot_id": scene_shot_ids[-2], "to_shot_id": shot_id,
                                    "transition_mode": "CONTINUOUS_ACTION",
                                    "reason": f"{scene['num']}第{index - 1}拍到第{index}拍：同场连续"})
            # the screenplay block row (what the anti-template checks read)
            for a in sh["actions"]:
                block_lines.append({"kind": "action", "text": a["text"], "subject": a.get("subject") or "",
                                    "named": cast.mentions(a["text"]), "shot_id": shot_id})
            for r in sh["lead_in"]:
                block_lines.append({"kind": "reaction", "who": r["who_id"], "text": r["text"], "shot_id": shot_id,
                                    "placement": "lead_in"})
            if speaking:
                block_lines.append({"kind": "dialogue", "speaker": speaker, "listener": addressee, "text": line,
                                    "paren": paren, "emotion": emotion, "shot_id": shot_id,
                                    **({"line_kind": "report"} if "交代" in tags or "交代" in paren else {}),
                                    **({"offscreen": True} if offscreen_speaker else {})})
            for r in sh["reactions"]:
                block_lines.append({"kind": "reaction", "who": r["who_id"], "text": r["text"], "shot_id": shot_id,
                                    "placement": "after"})
            # narrative / directing prose
            for a in sh["actions"]:
                narrative.append(_sentence(a["text"]))
            for r in sh["lead_in"]:
                narrative.append(f"（{cast.name(r['who_id'])}：{r['text']}）")
            if speaking:
                narrative.append(dialogue)
            for r in sh["reactions"]:
                narrative.append(f"（{cast.name(r['who_id'])}：{r['text']}）")
            directing.append(f"### {shot_id}｜{target:g}秒｜{scale}｜{'缓推' if push else '固定'}")
            directing.append(f"画内：{'、'.join(cast.name(c) + ('（过肩）' if f == 'BACK_AND_SHOULDERS_ONLY' else '') for c, f in visible)}")
            if primary:
                directing.append(f"动作：{primary}")
            if lead_zh:
                directing.append(f"先反应：{lead_zh}")
            if dialogue:
                directing.append(f"对白：{dialogue}（{emotion}；{delivery}）")
            if reaction_zh:
                directing.append(f"反应：{reaction_zh}")
            if shot_props:
                directing.append("道具：" + "、".join(f"{p['prop']}@{p.get('owner_name') or '—'}.{p.get('hand') or '—'}"
                                                   for p in shot_props))
            directing.append("")
        narrative.append("")
        scene_seconds = round(sum(s["target_seconds"] for s in shots_out if s["scene_id"] == sid), 3)
        ambient_life = loc.get("ambient_life") if isinstance(loc.get("ambient_life"), dict) else {}
        scene_states.append({
            "scene_id": sid, "location_id": loc_id, "time_id": time_of_day or "DAY",
            "time_of_day_state": time_of_day, "weather": weather, "weather_state": weather, "lighting": light,
            "target_seconds": scene_seconds,
            "ambient_life": {"grade": _clean(ambient_life.get("grade")) or "B",
                             "motion_trend": _clean(ambient_life.get("motion_trend")) or f"{loc_name}：{light or weather}下的细微流动",
                             "first_frame_state": _clean(ambient_life.get("first_frame_state")) or f"首帧{loc_name}已在{light or weather}之中",
                             "reaction_progression": _clean(ambient_life.get("reaction_progression")) or f"{scene_type or '冲突'}推进时{loc_name}的光影随人物走动变化"},
            "weather_provenance": {"source_type": "SCREENPLAY", "source_ref": f"{episode}_CAST_PROPS.yaml:{loc_id}",
                                   "visibility_mode": "VISIBLE"},
        })
        ambient_by_scene[sid] = {"ambience": ambience}
        plan_row = {"scene_id": sid,
                    "objective": card.get("goal") or "",
                    "objective_owner": cast.resolve(card.get("goal_owner") or "") or card.get("goal_owner") or "",
                    "conflict": card.get("obstacle") or "",
                    "physical_action": card.get("turn") or "",
                    "turn": card.get("turn") or "",
                    "scene_type": scene_type,
                    "source_detail_ids": list(card.get("source_detail_ids") or []),
                    **({"source_lines": list(card.get("source_lines") or [])} if card.get("source_lines") else {}),
                    "mirror_of": (_scene_id(episode, card["mirror_of"]) if re.fullmatch(r"S\d+", _clean(
                        card.get("mirror_of"))) else card.get("mirror_of")) or None,
                    # WP6 time / place / turn, WP5-C mood cue + hard stop
                    "time_of_day": time_of_day, "light": light, "weather": weather, "set_pieces": set_pieces,
                    **({"turn_shot_id": turn_shots[sid][0], "turn_owner": turn_shots[sid][1]}
                       if sid in turn_shots else {}),
                    **({"mood": card["mood"]} if card.get("mood") else {}),
                    **({"music_stop": _music_stop(card["music_stop"], episode)} if card.get("music_stop") else {}),
                    "goals": [{"who": cast.resolve(g["who"]) or g["who"], "goal": g["goal"]}
                              for g in card.get("goals") or []]}
        for key in ("goal", "obstacle", "turn"):
            if not _clean(card.get(key)):
                errors.append(f"SCENE_CARD_FIELD_MISSING:{scene['num']}:{key}")
        scene_plan.append(plan_row)
        block_scenes.append({"scene_id": sid, "heading": scene["heading"], "location_id": loc_id,
                             "time_of_day": time_of_day, "light": light, "weather": weather,
                             "set_pieces": set_pieces, "present": present, "card": {k: v for k, v in plan_row.items()
                                                                                       if k != "scene_id"},
                             "lines": block_lines, "shot_ids": scene_shot_ids})
        has_lines = any(s.get("kind") == "dialogue" for s in shots)
        structure.append({"beat_id": f"B{len(structure) + 1:02d}", "scene_id": sid, "target_seconds": scene_seconds,
                          "thread": "A", "location_id": loc_id,
                          # the structure gate's beat kinds; an "action" beat would owe an outcome row
                          "type": ("reveal" if "揭示" in scene_type else "dialogue") if has_lines else "transition",
                          **({"scene_type": scene_type} if scene_type else {}),
                          "shot_ids": scene_shot_ids})

    # ---- props
    reference_cards = []
    for pid, row in prop_rows.items():
        owner = cast.resolve(_clean(row.get("owner"))) or _clean(row.get("owner"))
        desc_en = _clean(row.get("description_en")) or tr.get(
            "prop", _clean(row.get("description") or row.get("name")), pid,
            f"the hand prop of {_en_name(cast, owner)}" if owner else "a hand prop")
        reference_cards.append({"entity_id": pid, "name": _clean(row.get("name")),
                                **({"aliases": [_clean(a) for a in row.get("aliases") or [] if _clean(a)]}
                                   if row.get("aliases") else {}),
                                "owner_id": owner,
                                "hand": _clean(row.get("hand")), "description": _clean(row.get("description")),
                                **({"description_en": desc_en} if desc_en else {}),
                                "acquired": {"episode": episode, "shot_id": (prop_uses.get(pid) or [""])[0]},
                                "used_in_shot_ids": prop_uses.get(pid) or [],
                                "payoff_shot_ids": (prop_uses.get(pid) or [])[-1:]})
    # ---- characters
    entities = []
    for cid, row in cast.rows.items():
        if cid not in first_shot and not row.get("always_declare"):
            continue
        entities.append(_character_entity(cid, row, series_card))
    shot_ids = [s["shot_id"] for s in shots_out]
    if not shots_out:
        errors.append("SCREENPLAY_NO_SHOTS")
    hook = outline.get("hook") if isinstance(outline.get("hook"), dict) else {}
    end_hook = outline.get("end_hook") if isinstance(outline.get("end_hook"), dict) else {}
    ending_shot = next((s["shot_id"] for s in reversed(shots_out)
                        if (s["prompt_spec"].get("beat_role") == "ENDING")), shot_ids[-1] if shot_ids else "")
    first = shots_out[0] if shots_out else {}
    first_line = _clean((first.get("prompt_spec") or {}).get("dialogue"))
    hook_type = "question" if re.search(r"[？?]", first_line) else ("dialogue" if first_line else "shock")
    pacing = {
        "hook": {"at_seconds": 0, "shot_id": shot_ids[0] if shot_ids else "", "type": hook_type,
                 **({"line_or_shot_id": shot_ids[0]} if shot_ids else {}),
                 **({"note": _clean(hook.get("text"))} if hook.get("text") else {}),
                 **({"authored_type": _clean(hook.get("type"))} if hook.get("type") else {})},
        "beat_sheet": beat_sheet,
        "cliffhanger": {"shot_id": ending_shot, "open_question": _clean(end_hook.get("open_question")
                                                                       or outline.get("end_hook_question"))},
        "scene_plan": scene_plan,
    }
    source = cast_props.get("source") if isinstance(cast_props.get("source"), dict) else {}
    chapters = [c for c in (outline.get("source_chapters") or source.get("chapters") or [])]
    plot_events = [e for e in outline.get("plot_events") or [] if isinstance(e, dict)]
    contract: dict[str, Any] = {
        "schema": "qingshan.generation_contract.v3",
        "episode": episode,
        "version": "v1",
        "craft_profile": "BILI_V1",
        "writer_format": "SCREENPLAY_V1",
        **({"project_id": cast_props["project_id"]} if cast_props.get("project_id") else {}),
        "episode_title": _clean(outline.get("title") or cast_props.get("title") or parsed.get("title")),
        "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
        "h3_prompt_style": "DIRECTOR_PROMPT_V2",
        "dialogue_language": language,
        "pacing_policy": "SHORT_DRAMA_PACING_V1",
        "writer_selfcheck_seq29": {"enforced": True},
        "visual_culture_contract": _visual_culture(series_card, cast_props),
        "character_entities": entities,
        "protagonist_ids": [cid for cid in (series_card.get("protagonist_ids") or cast_props.get("protagonist_ids")
                                            or []) if cid in cast.rows] or ([entities[0]["character_id"]]
                                                                           if entities else []),
        "non_character_entities": [],
        "scene_states": scene_states,
        "shots": shots_out,
        "internal_transition_authoring": transitions,
        "audio_contract": {"dialogue_units": dialogue_units, "ambient_by_scene": ambient_by_scene,
                           "bgm": cast_props.get("bgm") or series_card.get("bgm") or "NO_BGM"},
        "props": {"reference_cards": reference_cards},
        "entity_introductions": [{"entity_id": cid, "first_shot_id": sh, "setup": {"kind": "shot", "ref": sh},
                                  "payoff_shot_id": shot_ids[-1]} for cid, sh in first_shot.items()
                                 if cid in [e["character_id"] for e in entities]],
        "pacing": pacing,
        "adaptation_plan": {"source_chapters": chapters,
                            "plot_events": [{"event": _clean(e.get("event")), "chapter": e.get("chapter"),
                                             "role": _clean(e.get("role")).upper() or "MAIN",
                                             **({"shot_id": e["shot_id"]} if e.get("shot_id") else {})}
                                            for e in plot_events],
                            "cut": [c for c in outline.get("cut") or [] if c]},
        "source_binding": _source_binding(source, chapters),
        "arc_ledger": {"episode": episode, "carry_in": _clean(outline.get("carry_in")),
                       "ending_hook": _clean(end_hook.get("open_question") or outline.get("end_hook_question"))},
        **({"series_card": _series_card_block(series_card)} if _series_card_block(series_card) else {}),
        "screenplay_v1": {"schema": BLOCK_SCHEMA, "scenes": block_scenes,
                          "props": [{"id": c["entity_id"], "name": c["name"], "aliases": c.get("aliases") or [],
                                     "owner": c["owner_id"],
                                     "hand": c["hand"], "used_in": c["used_in_shot_ids"]} for c in reference_cards]},
        "pacing_scene_plan": scene_plan,
    }
    contract = _apply_wp6(contract, cast_props, outline, series_card, language)
    manifest = {
        "schema": "qingshan.writer.manifest.v2", "episode": episode, "version": "v1",
        "writer_format": "SCREENPLAY_V1",
        "canonical_script": f"{episode}_NARRATIVE_CANONICAL_v1.md",
        "source_binding": {k: v for k, v in contract["source_binding"].items() if k != "source_files"},
        "beat_disposition": [{"event_id": f"EV-{i + 1:02d}", "disposition": "LANDED",
                              "landed_at": e.get("shot_id") or _scene_for_event(e, scene_plan, block_scenes),
                              "source_event": _clean(e.get("event"))}
                             for i, e in enumerate(plot_events)] or
                            [{"event_id": f"SC-{i + 1:02d}", "disposition": "LANDED", "landed_at": row["scene_id"],
                              "source_event": row["objective"]} for i, row in enumerate(scene_plan)],
        "structure": structure,
        "scene_breakdown_seconds": {r["scene_id"]: r["target_seconds"] for r in structure},
        "total_seconds": round(sum(s["target_seconds"] for s in shots_out), 3),
    }
    inserted = [row["scene_id"] for row in scene_plan if not row["source_detail_ids"]]
    if inserted:
        manifest["authorized_insertions"] = [{"scene_id": sid, "reason": "screenplay scene without source details"}
                                             for sid in inserted]
    header = [f"# {contract['episode_title'] or episode} {episode} 叙事正典（由 {episode}_SCREENPLAY.md 编译）", "",
              f"集号 {episode}｜writer_format SCREENPLAY_V1｜本文件由 screenplay_compile.py 生成，改剧本请改 SCREENPLAY.md 后重编译。",
              ""]
    narrative_md = "\n".join(header + narrative).rstrip() + "\n"
    directing_md = "\n".join([f"# {episode} 导演稿（由 SCREENPLAY.md 编译；L4 导演 pass 可改景别/机位，不改内容）", ""]
                             + directing).rstrip() + "\n"
    manifest["script_sha256"] = hashlib.sha256(narrative_md.encode("utf-8")).hexdigest()
    en_request = {"schema": EN_REQUEST_SCHEMA, "episode": episode,
                  "instruction": ("translate each zh text literally into one English sentence for the H3 prompt: keep "
                                  "the object, the hand, the verb and who acts on whom; no paraphrase into mood words; "
                                  "write the answers to <EP>_SCREENPLAY_EN.json as {schema, rows: {key: english}}"),
                  "answer_schema": EN_SCHEMA, "rows": list(tr.requests.values())}
    fallback_fields = sum(1 for s in shots_out for v in s["prompt_spec"]["action"]["field_sources"].values()
                          if v == FALLBACK)
    all_fields = sum(len(s["prompt_spec"]["action"]["field_sources"]) for s in shots_out) or 1
    fallback_keys = {k for _, _, k in tr.fallback_log}
    unanswered = set(tr.requests) - fallback_keys
    report = {"schema": SCHEMA, "episode": episode, "status": "FAIL" if errors else
              ("NEEDS_EN" if unanswered else "PASS"),
              "en_fallback_used": len(fallback_keys),
              "errors": errors, "warnings": warnings, "shots": len(shots_out), "scenes": len(scene_plan),
              "seconds": manifest["total_seconds"], "en_missing": len(unanswered),
              "fallback_field_share": round(fallback_fields / all_fields, 3),
              "en_stale": len(set(tr.rows) - tr.used),
              "authored_action_shots": sum(1 for s in shots_out if s["prompt_spec"]["action"]["source"] == AUTHORED),
              "props": len(reference_cards)}
    return {"contract": contract, "narrative_md": narrative_md, "directing_md": directing_md, "manifest": manifest,
            "en_request": en_request, "report": report}


def _scene_for_event(event: dict[str, Any], plan: list[dict[str, Any]], scenes: list[dict[str, Any]]) -> str:
    want = _clean(event.get("scene"))
    for row in plan:
        if want and row["scene_id"].endswith(want):
            return row["scene_id"]
    return plan[0]["scene_id"] if plan else ""


def _wardrobe(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("wardrobe")
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if _clean(v)}
    if _clean(value):
        return {"outer_layer": _clean(value)}
    return {}


def _prop_ref(row: dict[str, Any], cast: Cast) -> dict[str, Any]:
    owner = cast.resolve(_clean(row.get("owner"))) or _clean(row.get("owner"))
    return {"prop": _clean(row.get("name")), "prop_id": _clean(row.get("id")), "entity_id": _clean(row.get("id")),
            **({"owner_id": owner, "owner_name": cast.name(owner)} if owner else {}),
            **({"hand": _clean(row.get("hand"))} if _clean(row.get("hand")) else {})}


def _character_entity(cid: str, row: dict[str, Any], series_card: dict[str, Any]) -> dict[str, Any]:
    card = {}
    for c in series_card.get("characters") or []:
        if isinstance(c, dict) and _clean(c.get("id")) == cid:
            card = c
    name = _clean(row.get("name") or row.get("canonical_name"))
    out = {"character_id": cid, "canonical_name": name,
           "aliases": [_clean(a) for a in row.get("aliases") or [] if _clean(a) and _clean(a) != name],
           "voice_entity_id": _clean(row.get("voice") or row.get("voice_entity_id")) or name,
           "identity_reference_entity_id": cid,
           "appearance_ch1": _clean(row.get("appearance")) or f"{name}，面部结构与年龄感见生产简报",
           "apparent_age_range": _clean(row.get("age") or row.get("apparent_age_range")) or "25-32",
           "gender": _clean(row.get("gender")) or "未定",
           "wardrobe_garments": _wardrobe(row) or {"outer_layer": "见生产简报"},
           "identity_source": {"mode": _clean(row.get("identity_mode")) or "TEXT_DESIGN"}}
    if _clean(row.get("english_name")):
        out["english_name"] = _clean(row["english_name"])
    for key in ("signature_business", "signature_prop", "want", "fear", "voice_note"):
        value = card.get(key) if key in card else row.get(key)
        if _clean(value):
            out[key] = _clean(value)
    mannerisms = [m for m in (row.get("mannerisms") or []) if _clean(m)]
    if mannerisms:
        out["mannerisms"] = mannerisms
    return out


def _visual_culture(series_card: dict[str, Any], cast_props: dict[str, Any]) -> dict[str, Any]:
    given = cast_props.get("visual_culture_contract") or series_card.get("visual_culture_contract")
    if isinstance(given, dict) and given:
        return {"schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED", **given}
    return {"schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
            "profile_id": _clean(series_card.get("profile_id")) or "SCREENPLAY_V1",
            "decision_owner": "WRITER_DIRECTOR",
            "decision_basis": _clean(series_card.get("premise")) or "series card",
            "source_ref": "SERIES_CARD.yaml"}


def _source_binding(source: dict[str, Any], chapters: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: source[k] for k in ("work", "author", "source_file", "source_sha256") if source.get(k)}
    if chapters:
        out["primary_source_chapter"] = str(chapters[0])
        out["source_chapters"] = [str(c) for c in chapters]
    files = [f for f in source.get("files") or [] if isinstance(f, dict)]
    if files:
        out["source_files"] = files
    return out


def _series_card_block(card: dict[str, Any]) -> dict[str, Any]:
    """The WP6 ``series_card`` shape: {characters: [{character_id, name, signature_business, signature_prop, ...}]}
    (+ premise / engine).  WP6's normaliser when present."""
    if not card:
        return {}
    cl = _craft_ledger()
    rows = []
    for c in card.get("characters") or []:
        if isinstance(c, dict):
            row = {k: c[k] for k in ("name", "want", "fear", "voice", "signature_business", "signature_prop",
                                     "palette", "cues", "main") if c.get(k) not in (None, "", [])}
            row["character_id"] = _clean(c.get("character_id") or c.get("id"))
            rows.append(row)
    out = {"characters": rows} if rows else {}
    if cl is not None and rows:
        try:
            out = cl.normalise_series_card({"characters": rows}) or out
        except Exception:  # noqa: BLE001
            pass
    out.update({k: card[k] for k in ("premise", "engine", "series_id") if card.get(k)})
    return out if out.get("characters") else {}


EMOTION_EN = {"急": "urgent", "怒": "angry", "惧": "afraid", "喜": "glad", "疑": "doubtful", "讥": "mocking",
              "慌": "flustered", "狠": "menacing", "哀": "sad", "羞": "shy", "傲": "haughty", "怯": "timid",
              "冷": "cold", "厌": "disgusted", "悔": "regretful", "惊": "startled", "怜": "tender", "嫉": "jealous",
              "贪": "greedy", "倦": "weary", "戏": "teasing", "愧": "ashamed", "盼": "hopeful", "坚": "firm"}


def _en_action_fallback(cast: "Cast", text: str) -> str:
    names = [_en_name(cast, c) for c in cast.mentions(text)]
    who = ", ".join(names[:3]) if names else "The character"
    return f"{who} perform the scripted action of this beat" if len(names) > 1 else \
        f"{who} performs the scripted action of this beat"


def _en_reaction_fallback(cast: "Cast", rows: list[dict[str, Any]]) -> str:
    who = ", ".join(dict.fromkeys(_en_name(cast, r["who_id"]) for r in rows)) or "The listener"
    return f"{who} reacts visibly without speaking"


def _en_name(cast: "Cast", cid: str) -> str:
    row = cast.rows.get(cid) or {}
    return _clean(row.get("english_name")) or ("the other person" if not cid else cid)


def _music_stop(value: Any, episode: str) -> Any:
    """WP5-C ``music_stop``: true (the scene's PUNCHLINE / last shot) or a shot id (``S01-07`` -> ``E25-S01-07``)."""
    if isinstance(value, bool):
        return value
    text = _clean(value)
    if text.lower() in ("true", "yes", "1", "是"):
        return True
    if re.fullmatch(r"S\d+-\d+", text):
        return f"{episode}-{text}"
    return text or True


def _apply_wp6(contract: dict[str, Any], cast_props: dict[str, Any], outline: dict[str, Any],
               series_card: dict[str, Any], language: str) -> dict[str, Any]:
    """ledger (CAST_PROPS), knowledge (OUTLINE) and the series card through WP6's ``screenplay_fields`` /
    ``apply_fields`` (anchors resolved to shot ids); a plain copy on an engine without craft_ledger."""
    ledger = [r for r in cast_props.get("ledger") or [] if isinstance(r, dict)]
    knowledge = [r for r in outline.get("knowledge") or [] if isinstance(r, dict)]
    cl = _craft_ledger()
    if cl is not None:
        try:
            fields = cl.screenplay_fields({"ledger": ledger} if ledger else {},
                                          {"knowledge": knowledge} if knowledge else {},
                                          {"series_card": contract["series_card"]} if contract.get("series_card")
                                          else {})
            return cl.apply_fields(contract, fields, language=language)
        except Exception:  # noqa: BLE001 -- the copy below is the same data, unresolved
            pass
    out = dict(contract)
    if ledger:
        out["ledger"] = ledger
    if knowledge:
        out["knowledge"] = knowledge
    return out


# =========================================================================== files / CLI
def paths(scripts: Path, episode: str) -> dict[str, Path]:
    scripts = Path(scripts)
    return {
        "series_card": scripts / "SERIES_CARD.yaml",
        "outline": scripts / f"{episode}_OUTLINE.md",
        "screenplay": scripts / f"{episode}_SCREENPLAY.md",
        "cast_props": scripts / f"{episode}_CAST_PROPS.yaml",
        "en_answers": scripts / f"{episode}_SCREENPLAY_EN.json",
        "en_request": scripts / f"{episode}_SCREENPLAY_EN_REQUEST.json",
        # written by the Codex tick when the request stayed unanswered past its resumes (never stall the line)
        "en_fallback": scripts / f"{episode}_SCREENPLAY_EN_FALLBACK.json",
        "report": scripts / f"{episode}_SCREENPLAY_COMPILE.json",
        "narrative": scripts / f"{episode}_NARRATIVE_CANONICAL_v1.md",
        "directing": scripts / f"{episode}_DIRECTING_SCRIPT_v1.md",
        "contract": scripts / f"{episode}_GENERATION_CONTRACT_v1.json",
        "manifest": scripts / f"{episode}_manifest_v1.json",
        "generator": _HERE / f"build_{episode.lower()}_layers.py",
    }


def input_paths(scripts: Path, episode: str) -> list[Path]:
    p = paths(scripts, episode)
    return [p[k] for k in ("series_card", "outline", "screenplay", "cast_props", "en_answers")]


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_yaml(path: Path) -> Any:
    text = _read_text(path)
    return read_light_yaml(text) if text.strip() else None


def compile_files(scripts: Path, episode: str, *, brief: dict[str, Any] | None = None,
                  en_fallback: bool = False) -> dict[str, Any]:
    p = paths(scripts, episode)
    if not p["screenplay"].is_file():
        return {"report": {"schema": SCHEMA, "episode": episode, "status": "FAIL",
                           "errors": [f"SCREENPLAY_MISSING:{p['screenplay']}"]}}
    try:
        cast_props = _read_yaml(p["cast_props"]) or {}
        series_card = _read_yaml(p["series_card"]) or {}
        outline = yaml_blocks_in_markdown(_read_text(p["outline"])) or {}
    except YamlError as exc:
        return {"report": {"schema": SCHEMA, "episode": episode, "status": "FAIL", "errors": [f"YAML_ERROR:{exc}"]}}
    answers = None
    if p["en_answers"].is_file():
        try:
            answers = json.loads(_read_text(p["en_answers"]))
        except ValueError:
            answers = None
    out = compile_screenplay(parse(_read_text(p["screenplay"])), cast_props, series_card, outline,
                             episode=episode, translations=answers, brief=brief, en_fallback=en_fallback)
    out["report"]["inputs"] = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
                               for k, v in p.items() if k in ("series_card", "outline", "screenplay", "cast_props",
                                                              "en_answers") and Path(v).is_file()}
    if p["generator"].is_file():
        out["report"]["generator_script_present"] = str(p["generator"])
    return out


def write_outputs(scripts: Path, episode: str, out: dict[str, Any], *, backup: bool = True) -> list[str]:
    """Write the four layers (+ request + report).  Existing layers are kept once as ``*.pre_compile``."""
    p = paths(scripts, episode)
    written: list[str] = []
    if out.get("contract") is None:
        p["report"].write_text(json.dumps(out["report"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return [str(p["report"])]
    payloads = {"narrative": out["narrative_md"], "directing": out["directing_md"],
                "contract": json.dumps(out["contract"], ensure_ascii=False, indent=1) + "\n",
                "manifest": json.dumps(out["manifest"], ensure_ascii=False, indent=1) + "\n"}
    for key, text in payloads.items():
        target = p[key]
        if backup and target.is_file():
            keep = target.with_name(target.name + ".pre_compile")
            if not keep.exists():
                keep.write_bytes(target.read_bytes())
        target.write_text(text, encoding="utf-8")
        written.append(str(target))
    if out["en_request"]["rows"]:
        p["en_request"].write_text(json.dumps(out["en_request"], ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")
        written.append(str(p["en_request"]))
    elif p["en_request"].is_file():
        p["en_request"].unlink()
    p["report"].write_text(json.dumps(out["report"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    written.append(str(p["report"]))
    return written


def needs_compile(scripts: Path, episode: str) -> bool:
    """A screenplay input is newer than the contract (or the contract is missing)."""
    p = paths(scripts, episode)
    if not p["screenplay"].is_file():
        return False
    if not p["contract"].is_file():
        return True
    built = p["contract"].stat().st_mtime
    return any(f.is_file() and f.stat().st_mtime > built for f in input_paths(scripts, episode))


def default_scripts_dir() -> Path:
    return _HERE.parents[3] / "workflow" / "claude_writer_agent" / "scripts"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("episode")
    ap.add_argument("--scripts-dir", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="compile in memory and print the report only")
    ap.add_argument("--en-fallback", action="store_true",
                    help="fill unanswered English twins with compiler English (marked fallback)")
    args = ap.parse_args(argv)
    episode = args.episode.strip().upper()
    scripts = args.scripts_dir or default_scripts_dir()
    out = compile_files(scripts, episode, en_fallback=args.en_fallback)
    report = out["report"]
    if not args.check and out.get("contract") is not None:
        report["written"] = write_outputs(scripts, episode, out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report.get("status") == "FAIL":
        return 2
    return 3 if report.get("status") == "NEEDS_EN" else 0


if __name__ == "__main__":
    sys.exit(main())
