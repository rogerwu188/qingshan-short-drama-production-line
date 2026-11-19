"""成功样例库 -- the collective library of proven directing examples (shots and episode practices that worked).

Three places use this module; it holds no I/O of its own:

* device capture (``lines/nalu/runtime/tools/nalu_knowledge_events.record_success_exemplars``) builds one
  exemplar per first-pass unit of a well-reviewed episode with :func:`shot_exemplar` / :func:`practice_exemplar`,
  scrubs it here and records it as a ``SUCCESS_EXEMPLAR`` event;
* the collector (``release_train.Train.exemplar_step``) runs :func:`curate` over those events and signs the
  result as a separate knowledge bundle (``nalu-exemplars``: ``rules: []`` plus ``exemplars: [...]``) through
  the same release gate, channels and device-sync path as the rule pack;
* the device's authoring injection (``authoring``) picks 2-3 matching entries with :func:`select_for_episode`
  and renders them as 「参考写法」 for Codex.

Exemplar (``qingshan.collective.success_exemplar.v1``) -- structural fields and short directing phrasing only::

    {schema, exemplar_id, kind: SHOT | EPISODE_PRACTICE,
     tags: {language, genre, model, setting, time_of_day, shot_size, camera_move, action_type, cast_count, dialogue},
     spec?: {camera, camera_motivation, blocking, action_beat, performance, constraints: [...]},     # SHOT
     practice?: {dimension, note},                                                                 # EPISODE_PRACTICE
     qa: {q1, q2, postgen},  final_review: {overall, dimensions?, dimension_score?},
     support?: {devices, episodes}}                                                                # library only

Privacy (the bucket is publicly readable): never a dialogue line, script text beyond a <= 60-char action beat,
a path, a URL or an id; cast names become 角色A/角色B (Character A/B); quoted spans become 「…」; every text field
is capped; :func:`validate_exemplar` runs ``contracts.sensitive_findings`` and the selection module's
CONTROL_LANGUAGE (money, gates, authority, secrets) and refuses on any hit.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from . import contracts as c

EXEMPLAR_SCHEMA = "qingshan.collective.success_exemplar.v1"
KINDS = ("SHOT", "EPISODE_PRACTICE")
FIELD_MAX = 120
BEAT_MAX = 60
CONSTRAINT_MAX = 40
CONSTRAINTS_MAX = 4
TAG_MAX = 40
RENDER_MAX = 300
SPEC_FIELDS = ("camera", "camera_motivation", "blocking", "action_beat", "performance")
QA_VALUES = ("FIRST_PASS", "NOT_RUN")
#: the final-review dimensions an EPISODE_PRACTICE can name (final_audience_review.DIMENSIONS)
PRACTICE_DIMENSIONS = ("story", "continuation", "pacing", "opening", "clarity", "visual", "anti_ai", "completeness")
ACTION_TYPES = ("FIGHT", "CHASE", "EMBRACE", "CONFRONTATION", "REVEAL", "GRIEF", "DIALOGUE", "PERFORMANCE")
SETTINGS = ("INTERIOR", "EXTERIOR", "UNKNOWN")
TIMES = ("DAY", "NIGHT", "DUSK", "DAWN", "UNKNOWN")

DEFAULTS: dict[str, Any] = {
    #: capture (device): final review overall >= this, no hard fail, verdict PASS, every dimension >= min_dimension
    "min_overall": 4.0,
    "min_dimension": 3.0,
    #: an EPISODE_PRACTICE is recorded for each dimension scored >= this (at most practices_per_episode)
    "practice_min_score": 4.5,
    "max_shots_per_episode": 4,
    "practices_per_episode": 2,
    #: curation (collector)
    "per_type": 2,
    "practice_per_type": 2,
    "max_exemplars": 60,
    "near_duplicate": 0.85,
    #: selection (device)
    "select_shots": 2,
    "select_practices": 1,
}

_URL_RE = re.compile(r"(?i)\b(?:https?|s3|gs|file|ftp)://\S+")
_PATH_RE = re.compile(r"(?:~|\.{1,2})?/(?:[^/\s「」，。；]+/)+[^/\s「」，。；]*")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\\S+")
_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+){1,}\b")  # LOC-RIVER-BOAT, ANGLE-X-01, E01-VU-003
_QUOTE_RES = (re.compile(r"「[^」]*」"), re.compile(r"『[^』]*』"), re.compile(r"“[^”]*”"),
              re.compile(r'"[^"]*"'), re.compile(r"‘[^’]*’"))
_SPACE_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- scrubbing
def role_map(names: Iterable[Any], language: str = "zh") -> dict[str, str]:
    """Cast names (longest first) -> 角色A / Character A.  Items are names or ``(character_key, name)`` pairs;
    every alias of one character key (Chinese name, provider label) gets the same letter."""
    letters: dict[str, str] = {}
    out: dict[str, str] = {}
    for item in names:
        key, name = (item if isinstance(item, tuple) else (item, item))
        text, key = str(name or "").strip(), str(key or name or "").strip()
        if len(text) < 2 or text in out:
            continue
        if key not in letters:
            letters[key] = chr(ord("A") + len(letters) % 26)
        out[text] = f"角色{letters[key]}" if language == "zh" else f"Character {letters[key]}"
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def scrub_text(value: Any, *, roles: dict[str, str] | None = None, limit: int = FIELD_MAX) -> str:
    """Directing phrasing only: quoted story text -> 「…」, cast names -> roles, ids/paths/URLs removed, capped."""
    text = str(value or "")
    text = _URL_RE.sub("", text)
    text = _WIN_PATH_RE.sub("", text)
    text = _PATH_RE.sub("", text)
    for pattern in _QUOTE_RES:
        text = pattern.sub("「…」", text)
    for name, role in (roles or {}).items():
        text = text.replace(name, role)
    text = _ID_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text).strip(" ，,；;。")
    text = re.sub(r"(「…」\s*){2,}", "「…」", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _norm(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


def genre_key(value: Any) -> str:
    """X2C category display name -> a comparable key ("Suspense & Horror" -> "suspensehorror", "悬疑" -> "悬疑")."""
    return _norm(value)[:TAG_MAX]


# --------------------------------------------------------------------------- tags
_INTERIOR = re.compile(r"(?i)(室内|屋内|屋里|房间|房内|舱内|教室|客厅|卧室|办公室|厨房|走廊|大厅|殿内|车内|病房|"
                       r"interior|indoor|room|classroom|hall|office|kitchen|corridor|bedroom|cabin)")
_EXTERIOR = re.compile(r"(?i)(室外|户外|街|江|河|湖|海|山|野|院子|庭院|广场|村口|码头|船舷|甲板|天台|"
                       r"exterior|outdoor|street|river|lake|sea|field|yard|square|rooftop|deck|forest|road)")
_ACTION_PATTERNS = (
    ("CHASE", re.compile(r"(?i)(追赶|追逐|追上|逃跑|奔逃|狂奔|chase|run(?:s|ning)? after|flee)")),
    ("EMBRACE", re.compile(r"(?i)(拥抱|抱住|相拥|搂住|embrace|hug)")),
    ("CONFRONTATION", re.compile(r"(?i)(质问|对峙|逼问|争执|争吵|怒斥|拍桌|推开|揪住|confront|argue|accuse|slam)")),
    ("REVEAL", re.compile(r"(?i)(发现|掏出|亮出|揭开|认出|reveal|discover|pull(?:s)? out|recogni[sz]e)")),
    ("GRIEF", re.compile(r"(?i)(哭|落泪|泪|哽咽|啜泣|cry|tears|sob)")),
)


def _first(*values: Any) -> str:
    return next((str(v) for v in values if isinstance(v, str) and v.strip()), "")


def unit_tags(unit: dict[str, Any], spec: dict[str, Any], *, language: str, genre: str, model: str) -> dict[str, Any]:
    """Scene/shot type tags read from the unit's own contract (no story text survives in a tag)."""
    state = spec.get("scene_state") if isinstance(spec.get("scene_state"), dict) else {}
    plan = spec.get("camera_plan") if isinstance(spec.get("camera_plan"), dict) else (
        unit.get("camera_plan") if isinstance(unit.get("camera_plan"), dict) else {})
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    space = spec.get("space") if isinstance(spec.get("space"), dict) else {}
    time_raw = str(state.get("time") or "").upper()
    time_of_day = next((t for t in ("NIGHT", "DUSK", "DAWN", "DAY") if t in time_raw), "UNKNOWN")
    if time_of_day == "UNKNOWN":
        time_of_day = {"EVENING": "DUSK", "MORNING": "DAWN", "NOON": "DAY"}.get(
            next((k for k in ("EVENING", "MORNING", "NOON") if k in time_raw), ""), "UNKNOWN")
    setting = "UNKNOWN"
    for source in (str(space.get("location") or ""), str(state.get("lighting") or ""),
                   " ".join(str(x) for x in ((spec.get("visual_design") or {}).get("depth_layers") or [])
                            if isinstance(spec.get("visual_design"), dict))):
        if _INTERIOR.search(source):
            setting = "INTERIOR"
            break
        if _EXTERIOR.search(source):
            setting = "EXTERIOR"
            break
    camera = str(spec.get("camera") or "")
    shot_size = _first(plan.get("shot_scale"), re.split(r"[／/;；\s]", camera)[0] if camera else "").upper()
    shot_size = re.sub(r"[^A-Z_]", "", shot_size)[:TAG_MAX] or "UNKNOWN"
    move = _first(plan.get("signature"))
    if not move and plan.get("motion_family"):
        move = f"{plan.get('motion_family')}:{plan.get('motion_direction') or 'NONE'}"
    move = re.sub(r"[^A-Z_:]", "", move.upper())[:TAG_MAX]
    if not move or move.startswith("LOCKED"):
        move = "LOCKED"
    cast = [r for r in spec.get("cast") or [] if isinstance(r, dict)]
    dialogue = bool(str(spec.get("dialogue") or "").strip())
    combat = bool(unit.get("combat_or_chase") or unit.get("fight_or_chase")) or action.get("action_kind") == "COMBAT"
    performance = spec.get("performance") if isinstance(spec.get("performance"), dict) else {}
    text = " ".join(str(x) for x in (action.get("primary_action"), performance.get("emotion"),
                                       (action.get("performance") or {}).get("emotion")
                                       if isinstance(action.get("performance"), dict) else "") if x)
    action_type = "FIGHT" if combat else next((name for name, rx in _ACTION_PATTERNS if rx.search(text)), "")
    if not action_type:
        action_type = "DIALOGUE" if dialogue else "PERFORMANCE"
    return {"language": str(language or "zh")[:8], "genre": genre_key(genre) or "UNKNOWN",
            "model": str(model or unit.get("model") or c.UNKNOWN)[:TAG_MAX], "setting": setting,
            "time_of_day": time_of_day, "shot_size": shot_size, "camera_move": move, "action_type": action_type,
            "cast_count": len(cast), "dialogue": dialogue}


#: render_style tag (2026-11-19): only an anime exemplar carries ``tags.render_style = "anime"``; an untagged exemplar
#: is live-action, so every existing exemplar (and its id) is unchanged and the two styles never mix in selection.
RENDER_STYLE_TAG = "render_style"
ANIME = "anime"
LIVE_ACTION = "live_action"


def exemplar_render_style(ex: dict[str, Any]) -> str:
    return ANIME if str((ex.get("tags") or {}).get(RENDER_STYLE_TAG) or "").lower() == ANIME else LIVE_ACTION


def _style_tags(tags: dict[str, Any], render_style: Any) -> dict[str, Any]:
    return {**tags, RENDER_STYLE_TAG: ANIME} if str(render_style or "").lower() == ANIME else tags


def type_key(ex: dict[str, Any]) -> str:
    tags = ex.get("tags") or {}
    style = "ANIME|" if exemplar_render_style(ex) == ANIME else ""
    if ex.get("kind") == "EPISODE_PRACTICE":
        return f"{style}PRACTICE|{tags.get('language')}|{(ex.get('practice') or {}).get('dimension')}"
    return style + "|".join(str(tags.get(k)) for k in ("language", "action_type", "shot_size", "setting"))


# --------------------------------------------------------------------------- builders (device)
def _exemplar_id(body: dict[str, Any]) -> str:
    core = {k: body.get(k) for k in ("kind", "tags", "spec", "practice")}
    return "ex-" + hashlib.sha256(c.canonical_json(core)).hexdigest()[:16]


def _dialogue_lines(spec: dict[str, Any]) -> list[str]:
    raw = str(spec.get("dialogue") or "")
    lines = []
    for part in re.split(r"[\n/]", raw):
        line = part.partition("：")[2] or part.partition(":")[2] or part
        line = re.sub(r"[\s，,。.!！?？…、]+", "", line)
        if len(line) >= 6:
            lines.append(line)
    return lines


def _leaks_dialogue(text: str, lines: list[str]) -> bool:
    flat = re.sub(r"[\s，,。.!！?？…、]+", "", text)
    return any(line[i: i + 6] in flat for line in lines for i in range(0, max(1, len(line) - 5)))


def shot_exemplar(unit: dict[str, Any], *, language: str, genre: str, model: str, overall: float,
                  dimensions: dict[str, Any] | None = None, qa: dict[str, str] | None = None,
                  render_style: Any = None) -> dict[str, Any] | None:
    """One SHOT exemplar from a grouped unit's first prompt spec (scrubbed, validated) or None."""
    specs = [s for s in unit.get("ordered_prompt_specs") or [] if isinstance(s, dict)]
    if not specs:
        return None
    spec = specs[0]
    names: list[Any] = []
    for row in spec.get("cast") or []:
        if isinstance(row, dict):
            names.append((row.get("character_id") or row.get("character"), row.get("character")))
    for row in unit.get("reference_images") or []:
        if isinstance(row, dict) and row.get("provider_entity_label"):
            names.append((row.get("entity_id") or row["provider_entity_label"], row["provider_entity_label"]))
    for row in unit.get("character_entities") or []:
        if isinstance(row, dict):
            key = row.get("character_id") or row.get("entity_id") or row.get("name")
            names.extend((key, row.get(k)) for k in ("name", "display_name", "provider_entity_label") if row.get(k))
    roles = role_map(names, "zh" if str(language).startswith("zh") else "en")
    plan = spec.get("camera_plan") if isinstance(spec.get("camera_plan"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    performance = spec.get("performance") if isinstance(spec.get("performance"), dict) else {}
    tags = _style_tags(unit_tags(unit, spec, language=language, genre=genre, model=model), render_style)
    camera_bits = [tags["shot_size"], tags["camera_move"].replace(":", " ")]
    if plan.get("camera_height"):
        camera_bits.append(str(plan["camera_height"]))
    blocking = ""
    start, end = str(plan.get("start_framing") or "").strip(), str(plan.get("end_framing") or "").strip()
    if start or end:
        blocking = start if (start == end or not end) else (end if not start else f"{start} → {end}")
    spec_out = {
        "camera": scrub_text(" / ".join(b for b in camera_bits if b), roles=roles),
        "camera_motivation": scrub_text(plan.get("motivation"), roles=roles),
        "blocking": scrub_text(blocking, roles=roles),
        "action_beat": scrub_text(action.get("primary_action"), roles=roles, limit=BEAT_MAX),
        "performance": scrub_text(_first(performance.get("body_sync"), spec.get("microexpression_design"),
                                         action.get("physical_action_design")), roles=roles),
        "constraints": [],
    }
    seen: set[str] = set()
    for item in spec.get("negative_prompts") or []:
        text = scrub_text(item, roles=roles, limit=CONSTRAINT_MAX)
        if text and text not in seen and not any(name in str(item) for name in roles):
            seen.add(text)
            spec_out["constraints"].append(text)
        if len(spec_out["constraints"]) >= CONSTRAINTS_MAX:
            break
    lines = _dialogue_lines(spec)
    for key in SPEC_FIELDS:
        if spec_out[key] and (_leaks_dialogue(spec_out[key], lines) or not _clean_field(spec_out[key])):
            spec_out[key] = ""
    spec_out["constraints"] = [x for x in spec_out["constraints"]
                               if not _leaks_dialogue(x, lines) and _clean_field(x)]
    if not (spec_out["camera"] and (spec_out["blocking"] or spec_out["action_beat"] or spec_out["performance"])):
        return None
    body = {"schema": EXEMPLAR_SCHEMA, "kind": "SHOT", "tags": tags,
            "spec": {k: v for k, v in spec_out.items() if v},
            "qa": {k: (qa or {}).get(k, "FIRST_PASS") for k in ("q1", "q2", "postgen")},
            "final_review": _review_block(overall, dimensions)}
    body["exemplar_id"] = _exemplar_id(body)
    try:
        return validate_exemplar(body)
    except c.ContractError:
        return None


def practice_exemplar(dimension: str, score: float, reason: Any, *, language: str, genre: str, model: str,
                      overall: float, cast_names: Iterable[Any] = (), render_style: Any = None) -> dict[str, Any] | None:
    """One EPISODE_PRACTICE: what the independent reviewer praised in a high-scoring dimension."""
    if dimension not in PRACTICE_DIMENSIONS:
        return None
    roles = role_map(cast_names, "zh" if str(language).startswith("zh") else "en")
    note = scrub_text(reason, roles=roles)
    if len(note) < 8 or not _clean_field(note):
        return None
    body = {"schema": EXEMPLAR_SCHEMA, "kind": "EPISODE_PRACTICE",
            "tags": _style_tags({"language": str(language or "zh")[:8], "genre": genre_key(genre) or "UNKNOWN",
                                 "model": str(model or c.UNKNOWN)[:TAG_MAX]}, render_style),
            "practice": {"dimension": dimension, "note": note},
            "qa": {"q1": "NOT_RUN", "q2": "NOT_RUN", "postgen": "NOT_RUN"},
            "final_review": {**_review_block(overall, None), "dimension_score": round(float(score), 2)}}
    body["exemplar_id"] = _exemplar_id(body)
    try:
        return validate_exemplar(body)
    except c.ContractError:
        return None


def _review_block(overall: float, dimensions: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"overall": round(float(overall), 2)}
    dims = {k: round(float(v), 2) for k, v in (dimensions or {}).items()
            if k in PRACTICE_DIMENSIONS and isinstance(v, (int, float)) and not isinstance(v, bool)}
    if dims:
        out["dimensions"] = dims
    return out


def _clean_field(text: str) -> bool:
    from .selection import CONTROL_LANGUAGE  # noqa: PLC0415 -- selection imports contracts only
    return not CONTROL_LANGUAGE.search(text) and not c.sensitive_findings(text)


# --------------------------------------------------------------------------- validation
def validate_exemplar(ex: dict[str, Any]) -> dict[str, Any]:
    """The exemplar contract: shape, caps, no executable/authority keys, no sensitive or control text."""
    failures: list[str] = []
    if not isinstance(ex, dict):
        raise c.ContractError(["EXEMPLAR_NOT_OBJECT"])
    if ex.get("schema") != EXEMPLAR_SCHEMA:
        failures.append("EXEMPLAR_SCHEMA_INVALID")
    if ex.get("kind") not in KINDS:
        failures.append(f"EXEMPLAR_KIND_INVALID:{ex.get('kind')}")
    if not re.fullmatch(r"ex-[0-9a-f]{16}", str(ex.get("exemplar_id") or "")):
        failures.append("EXEMPLAR_ID_INVALID")
    allowed = {"schema", "exemplar_id", "kind", "tags", "spec", "practice", "qa", "final_review", "support"}
    failures.extend(f"EXEMPLAR_KEY_UNKNOWN:{k}" for k in sorted(set(ex) - allowed))
    tags = ex.get("tags")
    if not isinstance(tags, dict) or not tags.get("language"):
        failures.append("EXEMPLAR_TAGS_INVALID")
    else:
        for key, value in tags.items():
            if isinstance(value, str) and len(value) > TAG_MAX:
                failures.append(f"EXEMPLAR_TAG_TOO_LONG:{key}")
            elif not isinstance(value, (str, int, bool)):
                failures.append(f"EXEMPLAR_TAG_TYPE:{key}")
    texts: list[str] = []
    if ex.get("kind") == "SHOT":
        spec = ex.get("spec")
        if not isinstance(spec, dict) or not spec.get("camera"):
            failures.append("EXEMPLAR_SPEC_REQUIRED")
            spec = {}
        for key, value in spec.items():
            if key == "constraints":
                if not isinstance(value, list) or len(value) > CONSTRAINTS_MAX or not all(
                        isinstance(x, str) and len(x) <= CONSTRAINT_MAX for x in value):
                    failures.append("EXEMPLAR_CONSTRAINTS_INVALID")
                else:
                    texts.extend(value)
            elif key not in SPEC_FIELDS:
                failures.append(f"EXEMPLAR_SPEC_KEY_UNKNOWN:{key}")
            elif not isinstance(value, str) or len(value) > (BEAT_MAX if key == "action_beat" else FIELD_MAX):
                failures.append(f"EXEMPLAR_SPEC_FIELD_INVALID:{key}")
            else:
                texts.append(value)
        if "practice" in ex:
            failures.append("EXEMPLAR_SHOT_CANNOT_CARRY_PRACTICE")
    elif ex.get("kind") == "EPISODE_PRACTICE":
        practice = ex.get("practice")
        if not isinstance(practice, dict) or practice.get("dimension") not in PRACTICE_DIMENSIONS or not isinstance(
                practice.get("note"), str) or not practice["note"] or len(practice["note"]) > FIELD_MAX \
                or set(practice) - {"dimension", "note"}:
            failures.append("EXEMPLAR_PRACTICE_INVALID")
        else:
            texts.append(practice["note"])
        if "spec" in ex:
            failures.append("EXEMPLAR_PRACTICE_CANNOT_CARRY_SPEC")
    qa = ex.get("qa")
    if not isinstance(qa, dict) or any(qa.get(k) not in QA_VALUES for k in ("q1", "q2", "postgen")) \
            or set(qa) - {"q1", "q2", "postgen"}:
        failures.append("EXEMPLAR_QA_INVALID")
    review = ex.get("final_review")
    if not isinstance(review, dict) or not isinstance(review.get("overall"), (int, float)) \
            or isinstance(review.get("overall"), bool) or not 1 <= float(review["overall"]) <= 5:
        failures.append("EXEMPLAR_FINAL_REVIEW_INVALID")
    support = ex.get("support")
    if support is not None and (not isinstance(support, dict) or not all(
            isinstance(support.get(k), int) and support[k] >= 1 for k in ("devices", "episodes"))):
        failures.append("EXEMPLAR_SUPPORT_INVALID")
    from .selection import CONTROL_LANGUAGE  # noqa: PLC0415
    for index, text in enumerate(texts):
        if CONTROL_LANGUAGE.search(text):
            failures.append(f"EXEMPLAR_CONTROL_LANGUAGE:{index}")
        if _URL_RE.search(text) or _PATH_RE.search(text):
            failures.append(f"EXEMPLAR_PATH_OR_URL:{index}")
    for key in ("skill", "code", "python", "shell", "script", "exec", *c.AUTHORITY_FLAGS):
        if key in ex:
            failures.append(f"EXEMPLAR_FORBIDDEN_KEY:{key}")
    failures.extend(c.sensitive_findings(ex))
    if failures:
        raise c.ContractError(failures)
    return ex


def library_blockers(bundle: dict[str, Any]) -> list[str]:
    """Release-gate check for a bundle that carries an exemplar library (empty list = may be released)."""
    rows = bundle.get("exemplars")
    if rows is None:
        return []
    if not isinstance(rows, list):
        return ["EXEMPLARS_MUST_BE_LIST"]
    out: list[str] = []
    seen: set[str] = set()
    for index, ex in enumerate(rows):
        try:
            validate_exemplar(ex)
        except c.ContractError as exc:
            out.extend(f"EXEMPLAR_INVALID:{index}:{code}" for code in exc.codes[:4])
            continue
        if ex["exemplar_id"] in seen:
            out.append(f"EXEMPLAR_DUPLICATE:{ex['exemplar_id']}")
        seen.add(ex["exemplar_id"])
    if len(rows) > int(DEFAULTS["max_exemplars"]) * 2:
        out.append(f"EXEMPLAR_LIBRARY_TOO_LARGE:{len(rows)}")
    return out


# --------------------------------------------------------------------------- curation (collector)
def _signature(ex: dict[str, Any]) -> set[str]:
    body = ex.get("spec") or ex.get("practice") or {}
    text = _norm(" ".join(str(v) if not isinstance(v, list) else " ".join(v) for v in body.values()))
    return {text[i: i + 2] for i in range(max(1, len(text) - 1))}


def _similar(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def curate(rows: list[dict[str, Any]], *, config: dict[str, Any] | None = None,
           vetoed: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Cluster exemplar observations by scene type, merge near-duplicates, keep the best few per type, cap.

    ``rows`` = ``[{"exemplar": {...}, "device_id", "episode_id"}]`` (one per SUCCESS_EXEMPLAR event).
    Ranking inside a type: independent devices, then episodes, then final-review score.  Output is
    deterministic (sorted by type, then rank) and every entry carries ``support``.
    """
    cfg = {**DEFAULTS, **(config or {})}
    vetoed = set(vetoed)
    merged: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: (-(float(((r.get("exemplar") or {}).get("final_review") or {})
                                                     .get("overall") or 0)), str((r.get("exemplar") or {})
                                                                                   .get("exemplar_id")))):
        ex = row.get("exemplar")
        try:
            validate_exemplar({k: v for k, v in (ex or {}).items() if k != "support"})
        except c.ContractError:
            continue
        if ex["exemplar_id"] in vetoed:
            continue
        sig, key = _signature(ex), type_key(ex)
        twin = next((m for m in merged if m["key"] == key and (m["ex"]["exemplar_id"] == ex["exemplar_id"]
                                                               or _similar(m["sig"], sig) >= cfg["near_duplicate"])),
                    None)
        source = (str(row.get("device_id") or c.UNKNOWN), str(row.get("episode_id") or c.UNKNOWN))
        if twin is None:
            merged.append({"key": key, "sig": sig, "ex": {k: v for k, v in ex.items() if k != "support"},
                           "devices": {source[0]}, "episodes": {source}})
        else:
            twin["devices"].add(source[0])
            twin["episodes"].add(source)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for m in merged:
        by_type.setdefault(m["key"], []).append(m)
    picked: list[dict[str, Any]] = []
    for key in sorted(by_type):
        group = sorted(by_type[key], key=lambda m: (-len(m["devices"]), -len(m["episodes"]),
                                                    -float(m["ex"]["final_review"]["overall"]),
                                                    m["ex"]["exemplar_id"]))
        limit = int(cfg["practice_per_type"] if key.startswith("PRACTICE|") else cfg["per_type"])
        picked.extend(group[:limit])
    picked.sort(key=lambda m: (-len(m["devices"]), -len(m["episodes"]), -float(m["ex"]["final_review"]["overall"]),
                               m["key"], m["ex"]["exemplar_id"]))
    out = [{**m["ex"], "support": {"devices": len(m["devices"]), "episodes": len(m["episodes"])}}
           for m in picked[: int(cfg["max_exemplars"])]]
    return sorted(out, key=lambda e: (type_key(e), e["exemplar_id"]))


def library_digest(library: list[dict[str, Any]]) -> str:
    return c.digest(sorted(library, key=lambda e: e["exemplar_id"]))


def summarize(ex: dict[str, Any]) -> dict[str, Any]:
    """The compact line a patrol reviewer reads for one library change."""
    out = {"exemplar_id": ex.get("exemplar_id"), "kind": ex.get("kind"), "type": type_key(ex),
           "support": ex.get("support"), "overall": (ex.get("final_review") or {}).get("overall")}
    if ex.get("kind") == "SHOT":
        spec = ex.get("spec") or {}
        out["text"] = "；".join(str(spec.get(k)) for k in ("camera", "blocking", "action_beat") if spec.get(k))[:200]
    else:
        out["text"] = f"{(ex.get('practice') or {}).get('dimension')}: {(ex.get('practice') or {}).get('note')}"
    return out


# --------------------------------------------------------------------------- selection (device)
def select_for_episode(library: list[dict[str, Any]], *, language: str, genre: str = "", model: str = "",
                       scene_hints: dict[str, dict[str, int]] | None = None,
                       config: dict[str, Any] | None = None, render_style: Any = None) -> list[dict[str, Any]]:
    """2-3 exemplars for this episode: same language (required), genre/model/upcoming scene types preferred,
    different action types where possible (a writer learns more from two kinds than from two of one)."""
    cfg = {**DEFAULTS, **(config or {})}
    hints = scene_hints or {}
    want_genre = genre_key(genre)
    lang = str(language or "zh")[:8]
    want_style = ANIME if str(render_style or "").lower() == ANIME else LIVE_ACTION

    def score(ex: dict[str, Any]) -> tuple:
        tags = ex.get("tags") or {}
        s = 0.0
        if want_genre and tags.get("genre") == want_genre:
            s += 3
        if model and tags.get("model") == model:
            s += 1
        for field, weight in (("action_type", 2.0), ("shot_size", 0.75), ("setting", 0.75), ("time_of_day", 0.5)):
            counts = hints.get(field) or {}
            total = sum(counts.values()) or 0
            if total and tags.get(field) in counts:
                s += weight * (0.5 + counts[tags.get(field)] / total)
        support = ex.get("support") or {}
        return (-s, -int(support.get("devices") or 1), -float((ex.get("final_review") or {}).get("overall") or 0),
                str(ex.get("exemplar_id")))

    pool = []
    for ex in library:
        try:
            validate_exemplar({k: v for k, v in ex.items() if not str(k).startswith("_")})  # _bundle: cache note
        except c.ContractError:
            continue
        # same language AND same render style: an anime episode never learns from live-action shots, nor back
        if (ex.get("tags") or {}).get("language") == lang and exemplar_render_style(ex) == want_style:
            pool.append(ex)
    shots = sorted((e for e in pool if e["kind"] == "SHOT"), key=score)
    practices = sorted((e for e in pool if e["kind"] == "EPISODE_PRACTICE"), key=score)
    chosen: list[dict[str, Any]] = []
    used_types: set[str] = set()
    for ex in shots:
        if len(chosen) >= int(cfg["select_shots"]):
            break
        if ex["tags"].get("action_type") in used_types:
            continue
        chosen.append(ex)
        used_types.add(ex["tags"].get("action_type"))
    for ex in shots:  # fill up when there were not enough distinct types
        if len(chosen) >= int(cfg["select_shots"]):
            break
        if ex not in chosen:
            chosen.append(ex)
    chosen.extend(practices[: int(cfg["select_practices"])])
    return chosen


_LABELS_ZH = {"INTERIOR": "内景", "EXTERIOR": "外景", "DAY": "日", "NIGHT": "夜", "DUSK": "黄昏", "DAWN": "清晨",
              "FIGHT": "打斗", "CHASE": "追逐", "EMBRACE": "拥抱", "CONFRONTATION": "对峙", "REVEAL": "揭示",
              "GRIEF": "悲伤", "DIALOGUE": "对话", "PERFORMANCE": "表演"}
_DIM_ZH = {"story": "故事", "continuation": "承接", "pacing": "节奏", "opening": "开场", "clarity": "清晰",
           "visual": "画面", "anti_ai": "去AI感", "completeness": "完整"}


def render_line(ex: dict[str, Any]) -> str:
    """One prompt line for Codex (Chinese scaffolding; the phrasing stays in the exemplar's own language)."""
    review = ex.get("final_review") or {}
    if ex.get("kind") == "EPISODE_PRACTICE":
        practice = ex.get("practice") or {}
        dim = practice.get("dimension")
        return (f"- 终审高分做法［{_DIM_ZH.get(dim, dim)} {review.get('dimension_score', review.get('overall'))}］："
                f"{practice.get('note')}")
    tags = ex.get("tags") or {}
    head = "·".join(x for x in (_LABELS_ZH.get(tags.get("setting"), ""), _LABELS_ZH.get(tags.get("time_of_day"), ""),
                                str(tags.get("shot_size") or ""), _LABELS_ZH.get(tags.get("action_type"), ""))
                    if x and x != "UNKNOWN")
    spec = ex.get("spec") or {}
    parts = [f"机位 {spec['camera']}" if spec.get("camera") else "",
             f"动机：{spec['camera_motivation']}" if spec.get("camera_motivation") else "",
             f"走位：{spec['blocking']}" if spec.get("blocking") else "",
             f"动作拍：{spec['action_beat']}" if spec.get("action_beat") else "",
             f"表演：{spec['performance']}" if spec.get("performance") else "",
             f"约束：{'、'.join(spec['constraints'][:3])}" if spec.get("constraints") else ""]
    line = f"- {head}（首过 Q1/Q2，终审 {review.get('overall')}）" + "；".join(p for p in parts if p)
    return line if len(line) <= RENDER_MAX else line[: RENDER_MAX - 1] + "…"
