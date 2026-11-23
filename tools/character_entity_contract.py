#!/usr/bin/env python3
"""Canonical character identity graph shared by script, picture and sound.

Names are presentation labels.  ``character_id`` is the only identity key.
Aliases may resolve to that key, but may never create a second person.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from tools import voice_over_narration as _vo
except ImportError:  # direct execution from tools/
    import voice_over_narration as _vo  # type: ignore


SCHEMA = "qingshan.character_entity_contract.v1"
ACTIVE_FROM_EPISODE = 54
VISIBLE = {"VISIBLE_AND_IDENTITY_LOCKED", "OWNER_PARTIALLY_OCCLUDED_BUT_AN_CONTINUOUS"}
SILENT_MARKERS = ("闭口", "不得张口", "不可张口", "不说话", "silent")
# A shot whose entry line names somebody who is not in its cast.  The keyframe
# renderer binds the entry sentence to the shot's cast by id, so the name has
# to resolve here or the prompt goes out with two instructions that contradict
# each other (see check in validate_character_entity_contract).
CLAUSE_SPLIT = re.compile(r"[，,。；;]")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _speaker_is_marked_silent(value: Any) -> bool:
    text = _clean(value).lower()
    return any(
        text.startswith(prefix)
        for prefix in ("闭口", "全程闭口", "保持闭口", "不得张口", "不可张口", "不说话", "silent")
    )


def _episode_number(payload: dict[str, Any]) -> int:
    match = re.match(r"E(\d+)", _clean(payload.get("episode") or payload.get("unit_id")).upper())
    return int(match.group(1)) if match else 0


def _specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("ordered_prompt_specs")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return [row.get("prompt_spec") for row in payload.get("shots") or [] if isinstance(row.get("prompt_spec"), dict)]


def build_character_index(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[str]]:
    rows = payload.get("character_entities")
    failures: list[str] = []
    if not isinstance(rows, list) or not rows:
        return {}, {}, ["CHARACTER_ENTITY_REGISTRY_MISSING"]
    by_id: dict[str, dict[str, Any]] = {}
    alias_to_id: dict[str, str] = {}
    for row in rows:
        cid = _clean(row.get("character_id"))
        canonical = _clean(row.get("canonical_name"))
        if not cid or not canonical:
            failures.append("CHARACTER_ENTITY_ID_OR_CANONICAL_NAME_MISSING")
            continue
        if cid in by_id:
            failures.append(f"CHARACTER_ENTITY_ID_DUPLICATE:{cid}")
            continue
        by_id[cid] = row
        labels = [canonical, *list(row.get("aliases") or [])]
        for label in labels:
            name = _clean(label)
            if not name:
                continue
            previous = alias_to_id.get(name)
            if previous and previous != cid:
                failures.append(f"CHARACTER_ALIAS_COLLISION:{name}:{previous}:{cid}")
            alias_to_id[name] = cid
    return by_id, alias_to_id, failures


def resolve_character_id(value: Any, alias_to_id: dict[str, str]) -> str | None:
    name = _clean(value)
    return alias_to_id.get(name) or (name if name in set(alias_to_id.values()) else None)


def validate_character_entity_contract(payload: dict[str, Any]) -> dict[str, Any]:
    required = _episode_number(payload) >= ACTIVE_FROM_EPISODE
    if not required and not payload.get("character_entities"):
        return {"schema": "qingshan.character_entity_gate.v1", "status": "PASS", "required": False, "failures": []}
    by_id, aliases, failures = build_character_index(payload)
    # V.O. narrator (VOICE_ONLY_NO_PLATE, CURRENT_PORTABLE): never on screen, so it is judged like an
    # off-screen voice — no visible-cast row and no lip owner.  Empty set -> nothing changes.
    voice_over_ids = _vo.voice_over_character_ids(list(by_id.values()))
    # entry_state is authored on the shot while _specs() yields prompt_spec, so pair
    # the two lists positionally to keep each shot id and its entry line next to its
    # spec.  Some payloads carry no shot rows and inline entry_state in the spec.
    shot_rows = [row for row in payload.get("shots") or [] if isinstance(row, dict)]
    specs = _specs(payload)
    paired = bool(shot_rows) and not payload.get("ordered_prompt_specs") and len(shot_rows) == len(specs)
    for spec_index, spec in enumerate(specs, 1):
        sid = _clean(spec.get("shot_id")) or (
            _clean(shot_rows[spec_index - 1].get("shot_id")) if paired else ""
        ) or f"SPEC-{spec_index}"
        entry_at_shot = _clean(shot_rows[spec_index - 1].get("entry_state")) if paired else ""
        cast_ids: set[str] = set()
        cast_names: dict[str, str] = {}
        for cast in spec.get("cast") or []:
            name = _clean(cast.get("character"))
            cid = _clean(cast.get("character_id"))
            resolved = resolve_character_id(name, aliases)
            if not cid:
                failures.append(f"{sid}_CAST_CHARACTER_ID_MISSING:{name or 'UNKNOWN'}")
            elif cid not in by_id:
                failures.append(f"{sid}_CAST_CHARACTER_ID_UNREGISTERED:{cid}")
            elif resolved != cid:
                failures.append(f"{sid}_CAST_NAME_ID_MISMATCH:{name}:{cid}:{resolved or 'UNRESOLVED'}")
            if cid in cast_ids:
                failures.append(f"{sid}_CAST_CHARACTER_ID_DUPLICATE:{cid}")
            cast_ids.add(cid)
            cast_names[name] = cid

        dialogue = _clean(spec.get("dialogue"))
        speaker_name = ""
        speaker_id = None
        if dialogue:
            speaker_name, separator, _ = dialogue.partition("：")
            if not separator:
                failures.append(f"{sid}_DIALOGUE_FORMAT_INVALID")
            speaker_name = speaker_name.strip()
            speaker_id = resolve_character_id(speaker_name, aliases)
            if not speaker_id:
                failures.append(f"{sid}_DIALOGUE_SPEAKER_UNREGISTERED:{speaker_name}")

        role = spec.get("role_semantic_disambiguation") or {}
        for name_field, id_field in (
            ("primary_actor", "primary_actor_id"),
            ("dialogue_speaker", "dialogue_speaker_id"),
            ("dialogue_listener", "dialogue_listener_id"),
            ("action_patient", "action_patient_id"),
        ):
            name = _clean(role.get(name_field))
            cid = _clean(role.get(id_field))
            is_character_role = (
                name_field in {"dialogue_speaker", "dialogue_listener"}
                or (name_field == "primary_actor" and _clean(role.get("primary_actor_kind") or "CHARACTER") == "CHARACTER")
                or (name_field == "action_patient" and resolve_character_id(name, aliases) is not None)
            )
            if name and is_character_role and not cid:
                failures.append(f"{sid}_{id_field.upper()}_MISSING:{name}")
            if cid and (cid not in by_id or resolve_character_id(name, aliases) != cid):
                failures.append(f"{sid}_{name_field.upper()}_NAME_ID_MISMATCH:{name}:{cid}")

        role_speaker_id = _clean(role.get("dialogue_speaker_id"))
        role_actor_id = _clean(role.get("primary_actor_id"))
        action = spec.get("action") or {}
        action_subject_id = _clean(action.get("subject_id"))
        actor_is_character = _clean(role.get("primary_actor_kind") or "CHARACTER") == "CHARACTER"
        if _clean(action.get("primary_action")) and actor_is_character and not action_subject_id:
            failures.append(f"{sid}_ACTION_SUBJECT_ID_MISSING")
        elif action_subject_id and actor_is_character and action_subject_id != role_actor_id:
            failures.append(f"{sid}_ACTION_SUBJECT_ROLE_ACTOR_MISMATCH:{action_subject_id}:{role_actor_id}")

        # The keyframe renderer draws the entry_state sentence and then binds every
        # visible person to it; a name the cast does not contain has nowhere to
        # bind, so the prompt ships one block saying the person acts and another
        # saying nobody is in frame.  Both contradictions are refused here.
        #
        # E11 S03-01 (2026-10-07): subject 邻居甲 / cast [] / entry "冯易安转过身
        # 朝向门口" — paid keyframe came back as an empty doorway, i.e. the shot's
        # completion state.  E11 S08-01: entry "刘老头站着，木杖重重顿在地上"
        # carried verbatim from S07-03, whose cast is 刘老头 and whose prop is 木杖,
        # while S08-01's cast is 秦铭 — the keyframe came back with the wrong man.
        entry_text = _clean(spec.get("entry_state")) or entry_at_shot
        if entry_text:
            visible_cast = {
                _clean(c.get("character_id")) for c in spec.get("cast") or []
                if c.get("first_frame_visible", True) is not False
            }
            if actor_is_character and role_actor_id and role_actor_id in by_id and role_actor_id not in visible_cast:
                failures.append(f"{sid}_PRIMARY_ACTOR_NOT_IN_VISIBLE_CAST:{role_actor_id}")

            declared_non_character = {
                _clean(row.get("name")) for row in payload.get("non_character_entities") or []
                if _clean(row.get("name"))
            }
            entry_head = CLAUSE_SPLIT.split(entry_text)[0]
            if entry_head and not any(name in entry_head for name in declared_non_character):
                # Only a head that names *nobody* in this shot's cast is a defect.
                # A name that is in the cast but not first-frame visible is a gaze
                # or relationship target ("秦铭坐着盯着许岳平") and is left alone,
                # as is a creature whose role name differs from its character id.
                named_head = {
                    label for label in aliases
                    if len(label) >= 2 and label in entry_head
                }
                in_cast_named = {aliases[l] for l in named_head if aliases[l] in cast_ids}
                actor_label = _clean(role.get("primary_actor"))
                absent_named = {
                    aliases[l] for l in named_head
                    if aliases[l] not in cast_ids and l not in actor_label
                }
                if absent_named and not in_cast_named and role_actor_id not in absent_named:
                    failures.append(
                        f"{sid}_ENTRY_STATE_NAMES_ABSENT_CHARACTER:"
                        + ",".join(sorted(absent_named))
                    )
        if dialogue and role_speaker_id != speaker_id:
            failures.append(f"{sid}_DIALOGUE_ROLE_SPEAKER_MISMATCH:{speaker_name}:{speaker_id}:{role_speaker_id}")
        presence = role.get("entity_presence") or {}
        states = role.get("entity_states") or {}
        offscreen = role_speaker_id and (_clean(presence.get(role_speaker_id)) == "OFFSCREEN_VOICE_ONLY"
                                         or role_speaker_id in voice_over_ids)
        if role_speaker_id and role_speaker_id not in cast_ids and not offscreen:
            failures.append(f"{sid}_DIALOGUE_SPEAKER_NOT_IN_VISIBLE_CAST:{role_speaker_id}")
        lip_owner_id = _clean(role.get("lip_owner_id"))
        if role_speaker_id and not offscreen and lip_owner_id != role_speaker_id:
            failures.append(f"{sid}_VISIBLE_LIP_OWNER_SPEAKER_MISMATCH:{lip_owner_id or 'MISSING'}:{role_speaker_id}")
        if offscreen and lip_owner_id:
            failures.append(f"{sid}_OFFSCREEN_DIALOGUE_MUST_NOT_HAVE_VISIBLE_LIP_OWNER:{lip_owner_id}")
        if role_speaker_id:
            state = _clean(states.get(role_speaker_id)).lower()
            if _speaker_is_marked_silent(state):
                failures.append(f"{sid}_DIALOGUE_SPEAKER_MARKED_SILENT:{role_speaker_id}")
        # Character entries are keyed by IDs. Typed non-character entities may
        # retain their role-contract labels.
        for field, mapping in (("STATE", states), ("PRESENCE", presence)):
            for key in mapping:
                if _clean(key) in aliases:
                    failures.append(f"{sid}_ENTITY_{field}_KEY_NOT_CHARACTER_ID:{key}")

    failures.extend(integrity_failures(payload, by_id, aliases, voice_over_ids))

    return {
        "schema": "qingshan.character_entity_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "required": required,
        "character_count": len(by_id),
        "failures": failures,
    }


# --------------------------------------------------------------------------- S1 integrity (E24, 2026-11-23)
#
# Device 1101 E24: every shot was one person, yet the actions were two-person ("Lingyao presses a dagger to Wang Defa
# throat", cast [凌瑶], target = herself); audio listener ids CHAR-AYE and an antagonist CHAR-MUYUNER were never
# defined.  H3 can only draw who the cast names, so the second person vanished from every interaction.  These are
# data defects of the script, never taste: they return the script to the writer.

_CHAR_ID_RE = re.compile(r"\bCHAR-[A-Za-z0-9][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*")
_PROPER_RUN_RE = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*")
_RUN_STOPWORDS = frozenset({"THE", "A", "AN", "HE", "SHE", "HIS", "HER", "THEY", "THEIR", "IT", "ITS", "WHILE",
                            "THEN", "AS", "WHEN", "WITH", "AND", "BUT", "ONE", "TWO", "BOTH"})
_NONE_MODES = {"", "NONE", "SOLO", "SELF"}
_TARGET_FIELDS = ("target_entity_id", "target_id", "patient_id", "patient_entity_id", "receiver_entity_id")


def _slug(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _clean(value).upper())


def declared_offscreen_character_ids(payload: dict[str, Any]) -> set[str]:
    """Characters a contract names but never shows (a dead father, an absent sender): top-level
    ``offscreen_character_entities`` [{character_id}] or ``offscreen_character_ids``."""
    out: set[str] = set()
    for row in payload.get("offscreen_character_entities") or []:
        out.add(_clean(row.get("character_id")) if isinstance(row, dict) else _clean(row))
    out |= {_clean(x) for x in payload.get("offscreen_character_ids") or []}
    out.discard("")
    return out


def latin_name_index(payload: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """slug -> character_id for names written in Latin script: the id slug (CHAR-WANGDEFA -> WANGDEFA), declared
    English names / Latin aliases, and the leading proper-noun run of a one-person shot's action ("Wang Defa raises
    both hands" with cast [王德发] -> WANGDEFA)."""
    index: dict[str, str] = {}
    for cid, row in by_id.items():
        slug = _slug(cid[5:] if cid.upper().startswith("CHAR-") else cid)
        if len(slug) >= 4:
            index.setdefault(slug, cid)
        for key in ("english_name", "name_en", "display_name_en", "romanized_name"):
            if len(_slug(row.get(key))) >= 3:
                index.setdefault(_slug(row.get(key)), cid)
        for alias in row.get("aliases") or []:
            if re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", _clean(alias)) and len(_slug(alias)) >= 3:
                index.setdefault(_slug(alias), cid)
    for spec in _specs(payload):
        cast = [_clean(c.get("character_id")) for c in spec.get("cast") or [] if isinstance(c, dict)]
        text = _clean((spec.get("action") or {}).get("primary_action"))
        if len(cast) != 1 or cast[0] not in by_id or not text:
            continue
        match = _PROPER_RUN_RE.match(text)
        if not match:
            continue
        words = [w for w in match.group(0).split() if w.upper() not in _RUN_STOPWORDS]
        if words and len(_slug("".join(words))) >= 3:
            index.setdefault(_slug("".join(words)), cast[0])
    return index


#: a name the sentence itself places outside the frame ("toward Holmes offscreen right", "质问画外谢衍", "Roylott is
#: outside this tight frame") is a gaze / address target the cast does not have to hold
_OFFSCREEN_AFTER_RE = re.compile(
    r"^(?:'s)?[\s,]{0,3}(?:\w+\s+){0,3}?(?:off[\s-]?screen|off[\s-]?frame|off[\s-]?lens|out of (?:the )?frame|"
    r"outside (?:of )?(?:this |the )?(?:tight |close )?(?:frame|shot)|unseen|\(off|\(o\.?s)", re.IGNORECASE)
_OFFSCREEN_BEFORE_RE = re.compile(r"(?:off[\s-]?screen|off[\s-]?frame|unseen)\s+(?:\w+\s+)?$", re.IGNORECASE)
_CJK_OFFSCREEN = ("画外", "画面外", "镜外", "镜头外", "画框外", "不入画", "出画")
#: a person the subject physically acts on / stands with must be in the frame (E24: "presses a dagger to Wang Defa
#: throat", "pulls Lingyao away", "lunges from behind Lingyao"); a gaze or a line addressed to an absent person is not
_CONTACT_EN = re.compile(
    # verbs that act on a person: the person may follow a few words later ("presses a dagger to Wang Defa")
    r"\b(?:(?:press(?:es|ed|ing)?|grab(?:s|bed|bing)?|seiz(?:es|ed|ing)|pull(?:s|ed|ing)?|drag(?:s|ged|ging)?|"
    r"push(?:es|ed|ing)?|shov(?:es|ed|ing)|binds?|binding|bound|ties|tied|tying|strik(?:es|ing)|struck|"
    r"slap(?:s|ped|ping)?|punch(?:es|ed|ing)?|kick(?:s|ed|ing)?|stab(?:s|bed|bing)?|hug(?:s|ged|ging)?|"
    r"embrac(?:es|ed|ing)|kiss(?:es|ed|ing)?|restrain(?:s|ed|ing)?|tackl(?:es|ed|ing)|chok(?:es|ed|ing)|"
    r"strangl(?:es|ed|ing)|lung(?:es|ed|ing))(?:\s+\S+){0,4}"
    # verbs / prepositions whose object must follow directly ("hands Holmes the letter", "beside Irene")
    r"|(?:hands|handed|handing|gives|giving|passes|passing|holds|holding|helps|helping|leads|leading|lifts|lifting|"
    r"carries|carrying|catches|catching|touches|touching|shakes|shaking|supports|supporting|pins|pinning|"
    r"beside|behind|next to|alongside|against|with)(?:\s+(?:the|a|an|over|up|down|onto|on|to))?)\s*$",
    re.IGNORECASE)
_CONTACT_ZH = re.compile(r"(?:抓住|抓着|拉住|拉着|拽住|拽着|推开|推倒|推着|按住|按着|掐住|扶住|扶着|抱住|抱着|搀扶|搀着|"
                         r"拖着|拖住|架着|架住|绑住|捆住|揪住|摁住|抵住|抵在|刺向|砍向|踢向|扇了|递给|交给|塞给|"
                         r"挡在|护住|护在|背起|背着|牵着|牵住|握住|拥住|靠在|站在|跪在|扑向|撞向|身旁的|身后的)"
                         r"[^，。；！？,.;!?]{0,4}$")
_CLAUSE_START = re.compile(r"(?:^|[.;!?。；！？，,:：]\s*)$")
#: an English clause subject is followed by its verb ("Irene is framed", "Holmes stands"); "Irene portrait" is a prop
_EN_PREDICATE = re.compile(r"^\s+(?:is|was|are|were|has|had|does|did|can|could|will|would|now|then|still|also|"
                           r"slowly|quickly|suddenly|[a-z]+(?:s|ed))\b")
_CLAUSE_OFFSCREEN = re.compile(r"off[\s-]?screen|off[\s-]?lens|off[\s-]?frame|outside (?:of )?(?:this |the )?"
                               r"(?:tight |close )?(?:frame|shot)|画外|画面外|镜外|不入画", re.IGNORECASE)


def _offscreen_marked(text: str, start: int, end: int) -> bool:
    before, after = text[max(0, start - 24):start], text[end:end + 40]
    if _OFFSCREEN_AFTER_RE.match(after) or _OFFSCREEN_BEFORE_RE.search(before):
        return True
    return any(m in before[-6:] or m in after[:8] for m in _CJK_OFFSCREEN)


def _on_screen_role(text: str, start: int, end: int) -> bool:
    """The mention puts the person in the frame: the clause's subject ("Irene is framed", "林乔转身离开画面"), or the
    one acted on / stood with ("pulls Lingyao away", "匕首抵住王德发的咽喉")."""
    if _offscreen_marked(text, start, end):
        return False
    clause_end = re.search(r"[.;!?。；！？]", text[end:])
    if _CLAUSE_OFFSCREEN.search(text[end:end + clause_end.start()] if clause_end else text[end:]):
        return False  # "The King gives Holmes the address, looking toward him offscreen left"
    before = text[max(0, start - 48):start]
    after = text[end:end + 24]
    latin = text[start:end].isascii()
    if _CLAUSE_START.search(before) and not after.startswith(("的", "之", "'s", "’s")):
        if not latin or _EN_PREDICATE.match(after):
            return True
    return bool(_CONTACT_EN.search(before) or _CONTACT_ZH.search(before[-12:]))


def names_in_text(text: str, aliases: dict[str, str], latin: dict[str, str]) -> set[str]:
    """Character ids a sentence puts ON SCREEN (subject of a clause or acted on / stood with): CJK canonical names /
    aliases (2+ characters) and Latin proper-noun runs.  A gaze or a line addressed to someone ("toward Holmes",
    "向武松劝酒") or a mention the sentence marks off-screen is not one."""
    text = text or ""
    found: set[str] = set()
    for label, cid in aliases.items():
        if len(label) < 2 or label.isascii():
            continue
        for match in re.finditer(re.escape(label), text):
            if _on_screen_role(text, match.start(), match.end()):
                found.add(cid)
    for match in _PROPER_RUN_RE.finditer(text):
        words = match.group(0).split()
        spans = [m.span() for m in re.finditer(r"\S+", match.group(0))]
        for i in range(len(words)):
            for j in range(i + 1, min(len(words), i + 3) + 1):
                cid = latin.get(_slug("".join(words[i:j])))
                if not cid:
                    continue
                a, b = match.start() + spans[i][0], match.start() + spans[j - 1][1]
                # a name inside a capitalised run ("The Lingyao") counts as the run's own position
                head = a if i else match.start()
                if _on_screen_role(text, head, b) or (i and _on_screen_role(text, a, b)):
                    found.add(cid)
    return found


def integrity_failures(payload: dict[str, Any], by_id: dict[str, dict[str, Any]], aliases: dict[str, str],
                       voice_over_ids: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Two-person actions with one-person casts, a target that is the subject, audio ids nobody defined."""
    if not by_id:
        return []
    failures: list[str] = []
    offscreen_declared = declared_offscreen_character_ids(payload)
    known = set(by_id) | offscreen_declared
    latin = latin_name_index(payload, by_id)
    shot_rows = [row for row in payload.get("shots") or [] if isinstance(row, dict)]
    specs = _specs(payload)
    paired = bool(shot_rows) and not payload.get("ordered_prompt_specs") and len(shot_rows) == len(specs)
    for index, spec in enumerate(specs, 1):
        sid = _clean(spec.get("shot_id")) or (_clean(shot_rows[index - 1].get("shot_id")) if paired else "") \
            or f"SPEC-{index}"
        cast_ids = {_clean(c.get("character_id")) for c in spec.get("cast") or [] if isinstance(c, dict)}
        cast_ids.discard("")
        role = spec.get("role_semantic_disambiguation") or {}
        presence = role.get("entity_presence") if isinstance(role.get("entity_presence"), dict) else {}
        action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
        offscreen = set(offscreen_declared) | set(voice_over_ids) | {
            _clean(k) for k, v in presence.items() if _clean(v).upper().startswith("OFFSCREEN")}
        offscreen |= {_clean(x) for x in action.get("offscreen_entity_ids") or []}
        offscreen |= {_clean(x) for x in spec.get("offscreen_character_ids") or []}
        subject = _clean(action.get("subject_id") or action.get("initiator_entity_id"))
        mode = _clean(action.get("interaction_mode")).upper()
        targets = {_clean(action.get(f)) for f in _TARGET_FIELDS} | {_clean(role.get("action_patient_id"))}
        targets.discard("")
        for target in sorted(targets):
            is_character = target in by_id or target.upper().startswith("CHAR-")
            if not is_character:
                continue
            if mode not in _NONE_MODES and target == subject:
                failures.append(f"{sid}_ACTION_TARGET_IS_SUBJECT:{target}:{mode}")
            elif (mode not in _NONE_MODES and target != subject and target not in cast_ids
                  and target not in offscreen):
                # a declared physical interaction with someone the frame does not hold (a gaze / address target
                # with interaction_mode NONE stays legal: "陈迹坐着盯着轩辕")
                failures.append(f"{sid}_ACTION_TARGET_NOT_IN_CAST:{target}:{mode}")
        text = _clean(action.get("primary_action"))
        if text:
            # a label that is part of a declared prop / creature name ("乌鸦" in the prop 紫眼乌鸦) names the prop
            prop_names = [_clean(r.get("name")) for r in payload.get("non_character_entities") or []
                          if isinstance(r, dict)] + [_clean(p.get("prop") or p.get("name"))
                                                     for p in spec.get("props") or [] if isinstance(p, dict)]
            usable = {label: cid for label, cid in aliases.items()
                      if not any(label in name for name in prop_names if name)}
            named = names_in_text(text, usable, latin) - cast_ids - offscreen
            if named:
                failures.append(f"{sid}_ACTION_NAMES_CHARACTER_NOT_IN_CAST:{','.join(sorted(named))}")
    audio = payload.get("audio_contract") if isinstance(payload.get("audio_contract"), dict) else {}
    for unit in audio.get("dialogue_units") or []:
        if not isinstance(unit, dict):
            continue
        usid = _clean(unit.get("shot_id")) or "UNIT"
        speaker, listener = _clean(unit.get("speaker_id")), _clean(unit.get("listener_id"))
        if speaker and speaker not in known:
            failures.append(f"{usid}_AUDIO_SPEAKER_UNDEFINED:{speaker}")
        if listener and listener not in known:
            failures.append(f"{usid}_AUDIO_LISTENER_UNDEFINED:{listener}")
        if speaker and listener and speaker == listener:
            failures.append(f"{usid}_AUDIO_LISTENER_IS_SPEAKER:{speaker}")
    import json as _json  # noqa: PLC0415
    referenced = set(_CHAR_ID_RE.findall(_json.dumps(payload, ensure_ascii=False)))
    for cid in sorted(referenced - known):
        failures.append(f"CHARACTER_ID_REFERENCED_BUT_UNDEFINED:{cid}")
    return failures
