"""MiniMax-H3 prompt in the OFFICIAL full-reference format (OFFICIAL_REF_V1).

MiniMax publishes how H3 reference-mode prompts are written (huggingface.co/MiniMaxAI/MiniMax-H3,
docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md + _base_en.md): six English sections in this order --
``subject_definitions``, ``summary`` (opens with a ``[task type]`` prefix), ``retention_analysis``,
``detailed_description`` (style opening, then ``[Shot 1] ...`` in playback order, 350-500 words for generation),
``overall_soundscape``, ``non_diegetic_music`` (``N/A`` when there is none).  References are ``<Picture N>``
(the N-th image input), ``<Subject N>`` (content abstracted from the references) and ``<Audio N>``; every
speaker gets a stable ``(S1)`` id and speaks ``(S1) says: <d>[Chinese] ...</d>`` with only the language tag and the
words inside ``<d>``.  The guides carry no negative lists and no "no subtitles" rule.

This module re-composes what DIRECTOR_PROMPT_V2 already resolved for a unit (references, cast, wardrobe, setting,
camera, the beat's action, the writer-authored performance, dialogue + delivery, sound) into those six sections, so
every engine check (English boundary, semantic coverage, shot-scope self check) still runs on the result.  The camera
lock and the identity binding are stated in the official places (retention_analysis + [Shot 1]); the V2 "Never" line
and the "picture stays clean" sentences are not sent.

Scope: craft_profile BILI_V1 units with people on screen, one continuous camera take and at least one image.
Everything else (multi-shot units, people-free inserts, single-subject rescue profiles) stays on V2.
Switch: the grouped compiler stamps ``h3_prompt_format`` on every BILI_V1 H3 unit -- the generation contract's
top-level ``h3_prompt_format`` when declared (``DIRECTOR_V2`` = the previous V2 text, byte-identical), else
``OFFICIAL_REF_V1``; the transaction task carries the field so the paid-boundary re-render matches.  An unstamped
unit renders V2.  env ``QINGSHAN_H3_PROMPT_FORMAT`` overrides everything (lab / emergency rollback).
Lab A/B (2026-11-27): ~/nalu_lab/perf_lab/OFFICIAL_FORMAT_AB.md.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from tools import bili_carry as _bili
except ModuleNotFoundError:  # pragma: no cover
    import bili_carry as _bili  # type: ignore

FORMAT = "OFFICIAL_REF_V1"
LEGACY_FORMAT = "DIRECTOR_V2"
FORMATS = (FORMAT, LEGACY_FORMAT)
ENV_SWITCH = "QINGSHAN_H3_PROMPT_FORMAT"
FIELD = "h3_prompt_format"
SECTIONS = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape",
            "non_diegetic_music")

#: the leading "WORLD VISUAL LOCK:" style title of a non-required lock (English authored-world lines, 1205
#: 2026-11-28: it reached detailed_description and failed H3_DIRECTOR_V2_SELF_CHECK:ALL_CAPS_LABEL_IN_PROMPT)
_LOCK_TITLE = re.compile(r"^[A-Z]{2,}(?:[ \t]+[A-Z]{2,})*[ \t]*(?:[\u2014\u2013-][^:\n]{0,40})?:\s*")
_IMAGE = re.compile(r"@Image(\d+)")
_AUDIO = re.compile(r"@Audio(\d+)")
_OPENING_ENTRY = re.compile(r"^\s*as (?:in|shown in) the (?:opening|first) frame\.?\s*$", re.IGNORECASE)
_OPENING_ROLES = {"ADMITTED_NEW_EVENT_ENTRY_STATE", "CONTINUITY_DERIVED_ENTRY_STATE", "PREVIOUS_UNIT_FINAL_FRAME",
                  "IDENTITY_OR_PROP_REANCHOR"}
_PREVIOUS_ROLES = {"PREVIOUS_REAL_TAIL_STATE_AUTHORITY", "PREVIOUS_UNIT_FINAL_FRAME"}
_SCALE = {"EXTREME_CLOSE_UP": "extreme close-up", "ECU": "extreme close-up", "CLOSE_UP": "close-up",
          "CU": "close-up", "MEDIUM_CLOSE_UP": "medium close-up", "MCU": "medium close-up", "MEDIUM": "medium shot",
          "MEDIUM_WIDE": "medium-wide shot", "MEDIUM_FULL": "medium-full shot", "FULL": "full shot",
          "WIDE": "wide shot", "EXTREME_WIDE": "extreme wide shot"}
_HEIGHT = {"EYE_LEVEL": "eye level", "LOW": "a low angle", "LOW_ANGLE": "a low angle", "HIGH": "a high angle",
           "HIGH_ANGLE": "a high angle"}
#: the official guide's playback-order sentence for the writer's performance rows (bili_carry.AUTHORED_ROWS keys)
_BEFORE_LINE = ("entry", "want", "hide", "leak")
_AFTER_LINE = ("crack", "visible", "end")


#: what the grouped compiler stamps on a BILI_V1 H3 unit when the generation contract names no format
BILI_V1_DEFAULT = FORMAT


def declared_format(payload: dict[str, Any] | None) -> str:
    value = str((payload or {}).get(FIELD) or "").strip().upper()
    return value if value in FORMATS else ""


def stamp_format(payload: dict[str, Any] | None) -> str:
    """The value the grouped compiler stamps on a BILI_V1 H3 unit: the contract's declared format, else the default."""
    return declared_format(payload) or BILI_V1_DEFAULT


def requested_format(unit: dict[str, Any]) -> str:
    """env QINGSHAN_H3_PROMPT_FORMAT, else the unit's stamped ``h3_prompt_format``, else DIRECTOR_V2 (an unstamped
    unit -- every unit compiled before this format existed -- keeps its V2 text byte-identically)."""
    env = str(os.environ.get(ENV_SWITCH) or "").strip().upper()
    if env in FORMATS:
        return env
    return declared_format(unit) or LEGACY_FORMAT


def applies(unit: dict[str, Any], plan: dict[str, Any], *, stamped: bool, subjects: list[dict[str, Any]],
            camera: str, all_locked: bool, records: list[dict[str, Any]]) -> bool:
    if not (_bili.active(unit) and stamped and subjects and records):
        return False
    if requested_format(unit) != FORMAT:
        return False
    if str(unit.get("h3_prompt_profile") or "").strip():  # the single-subject rescue profiles keep their grammar
        return False
    lines = [line for line in camera.split("\n") if line.strip()]
    if any(line.startswith("Shot ") for line in lines):  # several camera setups: stays on V2
        return False
    return all_locked or "push-in" in camera


@dataclass
class Parts:
    unit: dict[str, Any]
    plan: dict[str, Any]
    contract: dict[str, Any]
    subjects: list[dict[str, Any]]
    label_by_id: dict[str, str]
    face_hidden: dict[str, str]
    looks: dict[str, str]
    crossmodal_rows: list[dict[str, Any]]
    setting_en: str
    space_weather: str
    env_rows: list[str]
    look: str
    period: bool
    anime: bool
    prop_fact: str
    prop_sentences: list[str]
    camera: str
    all_locked: bool
    records: list[dict[str, Any]]
    action_lines: list[str]
    beats_end: int
    dialogue_rows: list[dict[str, Any]]
    sound_rows: list[str]
    adult_line: str
    evidence: dict[str, str] = field(default_factory=dict)


def _s(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _low(text: str) -> str:
    text = str(text or "").strip().rstrip(".")
    return text[:1].lower() + text[1:] if text and not text[:2].isupper() else text


def _flat(text: str) -> str:
    """The V2 renderer's sameness test (h3_director_prompt_v2._same)."""
    return re.sub(r"[\s.;,]+", " ", str(text or "")).strip().lower()


def _labels(text: str) -> str:
    """@ImageN -> <Picture N>, @AudioN -> <Audio N> (the official label names)."""
    return _AUDIO.sub(lambda m: f"<Audio {m.group(1)}>", _IMAGE.sub(lambda m: f"<Picture {m.group(1)}>", text))


def _join(names: list[str]) -> str:
    names = [n for n in names if n]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def _gender(unit: dict[str, Any], cid: str) -> str | None:
    try:
        from tools.h3_director_prompt_v2 import speaker_voice_gender
    except ModuleNotFoundError:  # pragma: no cover
        from h3_director_prompt_v2 import speaker_voice_gender  # type: ignore
    return speaker_voice_gender(unit, cid)


def _pronoun(unit: dict[str, Any], cid: str, label: str) -> str:
    gender = _gender(unit, cid)
    return "She" if gender == "female" else "He" if gender == "male" else label


def _reference_rows(unit: dict[str, Any]) -> list[dict[str, Any]]:
    scope = unit.get("provider_scope_projection") or {}
    bindings = {int(r["reference_index"]): r for r in scope.get("reference_identity_bindings") or []
                if r.get("reference_index") is not None}
    sequence = {str(r.get("path") or ""): r for r in unit.get("reference_image_sequence") or []
                if r.get("path") and str(r.get("entity_id") or "").startswith("CHAR-")}
    rows = []
    for index, raw in enumerate(unit.get("reference_images") or [], 1):
        ref = raw if isinstance(raw, dict) else {"path": str(raw)}
        bound = bindings.get(index) or sequence.get(str(ref.get("path") or ""), {})
        ref = {**bound, **ref}
        rows.append({"index": index, "role": str(ref.get("role") or "REFERENCE").upper(),
                     "entity_id": str(ref.get("entity_id") or "").strip(), "path": str(ref.get("path") or ""),
                     "identity": str(bound.get("binding_role") or "") == "IDENTITY"
                     or (not bound.get("binding_role") and str(bound.get("entity_id") or "").startswith("CHAR-"))})
    return rows


def _camera_sentence(p: Parts) -> str:
    cam = p.plan.get("camera_plan") or {}
    scale = _SCALE.get(str(cam.get("shot_scale") or "").upper(), "")
    height = _HEIGHT.get(str(cam.get("camera_height") or "").upper(), "")
    where = ", ".join(v for v in (f"at {height}" if height else "", f"framed as a {scale}" if scale else "") if v)
    dof = (" Shallow depth of field keeps the face sharp while the background falls into a soft blur."
           if "shallow depth of field" in p.camera.lower() else "")
    if p.all_locked:
        return (f"The camera holds a static shot on a tripod{', ' + where if where else ''}, one continuous take "
                "with no cuts; it does not push in, pull out, pan, tilt or follow anyone, the people stay the same "
                "size as in <Picture 1>, and only the people move." + dof)
    # BILI_V1's one slow push-in (director_pass), in the guide's motion type + amplitude + speed grammar
    return (f"The camera pushes in toward the speaker with small amplitude at slow speed{', ' + where if where else ''}"
            ", about 10% closer over the whole shot in one direction only, then holds, in one continuous take with "
            "no cuts; it never pulls back, pans or drifts." + dof)


def _performance(p: Parts, record: dict[str, Any], keys: tuple[str, ...], cid: str, label: str,
                 listener: str) -> list[str]:
    action = (record.get("spec") or {}).get("action") or {}
    rows = _bili.authored_performance_lines(action, label, listener)[1:]  # same filtering as the V2 block
    heads = {head: key for key, head in _bili.AUTHORED_ROWS}
    names = sorted({str(v) for v in p.label_by_id.values() if v} | {label, listener} - {""}, key=len, reverse=True)
    by_key: dict[str, str] = {}
    for row in rows:
        head, _, text = row[2:].partition(": ")
        key = heads.get(head.format(other=listener or "the other person")) or heads.get(head)
        if key:
            text = text.rstrip(".")
            for name in names:  # bili_carry lower-cases the row's first letter; a name keeps its capital
                if text.lower().startswith(name.lower() + " ") or text.lower() == name.lower():
                    text = name + text[len(name):]
            by_key[key] = text
    pronoun = _pronoun(p.unit, cid, label)
    poss = {"She": "her", "He": "his"}.get(pronoun, f"{label}'s")
    phrase = {
        "entry": lambda t: f"{label} starts with {t}",
        "want": lambda t: f"{pronoun} wants {t}" if t.lower().startswith("to ") else f"What {_low(pronoun) if pronoun in ('She', 'He') else pronoun} wants: {t}",
        "hide": lambda t: f"Underneath, {_low(pronoun) if pronoun in ('She', 'He') else pronoun} holds back: {t}",
        "leak": lambda t: f"What leaks out: {t}",
        "crack": lambda t: f"As the line lands, {poss} guard cracks: {t}",
        "visible": lambda t: f"Visibly, {t}",
        "end": lambda t: f"{pronoun} ends on {t}",
    }
    return [_s(phrase[k](by_key[k])) for k in keys if by_key.get(k)]


def compose(p: Parts) -> str:
    unit, plan, ev = p.unit, p.plan, p.evidence
    duration = float(plan["duration_seconds"])
    refs = _reference_rows(unit)
    people = [s for s in p.subjects if s["kind"] == "PERSON"]
    beings = [s for s in p.subjects if s["kind"] != "PERSON"]

    # --- labels: one <Subject N> per on-screen subject, then the setting -------------------------------
    subject_no = {s["entity_id"]: n for n, s in enumerate(p.subjects, 1)}
    setting_no = len(p.subjects) + 1
    tag = {cid: f"<Subject {n}>" for cid, n in subject_no.items()}
    speaker_ids: dict[str, str] = {}
    for row in p.dialogue_rows:
        speaker_ids.setdefault(row["label"], f"S{len(speaker_ids) + 1}")
    audio_by_label = {str(r.get("provider_entity_label") or ""): str(r.get("audio_slot") or "")
                      for r in p.crossmodal_rows}
    id_by_label = {s["label"]: s["entity_id"] for s in p.subjects}
    for row in p.crossmodal_rows:
        id_by_label.setdefault(str(row.get("provider_entity_label") or ""), str(row.get("character_id") or ""))

    # --- subject_definitions ------------------------------------------------------------------------------
    definitions: list[str] = []
    first = refs[0] if refs else None
    for s in p.subjects:
        cid, label = s["entity_id"], s["label"]
        pictures = [r for r in refs if r["entity_id"] == cid and r["identity"] and r["index"] > 1]
        source = _join([f"<Picture {r['index']}>" for r in pictures])
        wardrobe = _low(p.looks.get(cid) or "")
        gender = _gender(unit, cid)
        noun = ("a woman" if gender == "female" else "a man" if gender == "male" else
                "a living non-human subject" if s["kind"] != "PERSON" else "a person")
        hidden = p.face_hidden.get(cid)
        if hidden and source:
            body = (f"seen only from behind; {source} gives only {label}'s hair, build and wardrobe"
                    if hidden == "BEHIND" else f"{source} gives only {label}'s build and wardrobe")
            line = f"{_psp().official_subject_marker(subject_no[cid], label)}, {noun} {body}"
        elif source:
            line = f"{_psp().official_subject_marker(subject_no[cid], label)}, {noun} whose face, hair and build come from {source}"
        else:
            line = f"{_psp().official_subject_marker(subject_no[cid], label)}, {noun} already shown in <Picture 1>"
        if wardrobe:
            if wardrobe.startswith(("a living", "wearing")):
                line += f"; {wardrobe}"
            else:
                article = "" if re.match(r"(?:a|an|the|his|her|their)\b", wardrobe) else (
                    "an " if wardrobe[:1] in "aeiou" else "a ")
                line += f", wearing {article}{wardrobe}"
        definitions.append(_s(line))
    setting_words = " ".join(v for v in (p.setting_en, _s(p.space_weather)) if v).strip()
    definitions.append(_s(f"<Subject {setting_no}> is the setting shown in <Picture 1>: "
                          f"{_low(setting_words) if setting_words else 'the location of the opening frame'}"))
    if first is not None:
        facing = [s["label"] for s in people if s["entity_id"] not in p.face_hidden]
        behind = [s["label"] for s in people if p.face_hidden.get(s["entity_id"]) == "BEHIND"]
        shows = "; ".join(v for v in (f"{_join(facing)} facing the camera" if facing else "",
                                      f"{_join(behind)} from behind in the near foreground" if behind else "") if v)
        if first["role"] in _PREVIOUS_ROLES:
            definitions.append(_s(f"<Picture 1> is the first frame of [Shot 1]: the previous shot's last frame"
                                  + (f", showing {shows}" if shows else "")))
        else:
            definitions.append(_s("<Picture 1> is the first frame of [Shot 1]" + (f", showing {shows}" if shows else "")))
    for r in refs[1:]:
        if r["identity"] and r["entity_id"] in subject_no:
            continue  # cited inside that subject's definition
        if r["role"] in _PREVIOUS_ROLES:
            definitions.append(f"<Picture {r['index']}> is the previous shot's last frame, used only for positions, "
                               "clothing, props and light.")
        elif r["role"] == "SCENE_LOCATION_REFERENCE":
            definitions.append(f"<Picture {r['index']}> is this scene's location reference for the background, set "
                               "dressing and light.")
        elif r["entity_id"]:
            definitions.append(f"<Picture {r['index']}> is the reference for the "
                               f"{p.label_by_id.get(r['entity_id']) or 'prop'}: its shape, material and scale.")
        else:
            definitions.append(f"<Picture {r['index']}> is a continuity reference for the setting and props.")
    for row in p.crossmodal_rows:
        label = str(row.get("provider_entity_label") or "")
        slot = _labels(str(row.get("audio_slot") or "@Audio1"))
        cid = id_by_label.get(label, "")
        gender = _gender(unit, cid) if cid else None
        voice = "a woman's voice" if gender == "female" else "a man's voice" if gender == "male" else "a voice"
        who = f"{tag[cid]} ({speaker_ids.get(label, 'S1')})" if cid in tag else f"{label} ({speaker_ids.get(label, 'S1')})"
        definitions.append(f"{slot} is the voice-timbre reference for {who}, {voice}.")
        ev_key = next((k for k, v in ev.items() if k.startswith("VOICE_BINDING.") and label in v), None)
        if ev_key:
            ev[ev_key] = f"{slot} is the voice-timbre reference for {who}"

    # --- summary ----------------------------------------------------------------------------------------
    task = ["keyframe completion", "reference generation"] + (["audio reference"] if p.crossmodal_rows else [])
    speaking = [r["label"] for r in p.dialogue_rows]
    cam = plan.get("camera_plan") or {}
    scale = _SCALE.get(str(cam.get("shot_scale") or "").upper(), "shot")
    what = (f"{_join(list(dict.fromkeys(speaking)))} speak{'s' if len(set(speaking)) == 1 else ''} "
            f"{'one line' if len(speaking) == 1 else f'{len(speaking)} lines'}" if speaking
            else f"{_join([s['label'] for s in p.subjects])} act without dialogue")
    listeners = [s["label"] for s in people if s["label"] not in speaking]
    summary = (f"[{' + '.join(task)}] A {duration:g}-second vertical 9:16 live-action {scale} in one continuous take, "
               f"in which {what}" + (f" to {_join(listeners)}" if speaking and listeners else "")
               + f" in <Subject {setting_no}>. The video starts on <Picture 1>; "
               + _join([f"{tag[s['entity_id']]}" for s in p.subjects])
               + (" keeps" if len(p.subjects) == 1 else " keep") + " the identity from the reference pictures"
               + ("; " + _join([_labels(str(r.get('audio_slot') or '@Audio1')) for r in p.crossmodal_rows])
                  + " gives the speaking voice timbre." if p.crossmodal_rows else "."))
    if p.anime:
        summary = summary.replace(" live-action ", " anime ")

    # --- retention_analysis -----------------------------------------------------------------------------
    total = len(p.subjects)
    retention = [f"<Picture 1> ([Shot 1] first frame): fully_preserved - the video opens exactly on this frame with "
                 f"the same shot size, framing, camera position and {'the person' if total == 1 else 'everyone'}'s "
                 "place; the camera keeps this framing to the last frame."]
    for s in p.subjects:
        cid, label = s["entity_id"], s["label"]
        hidden = p.face_hidden.get(cid)
        if hidden:
            retention.append(f"{tag[cid]} (appears in [Shot 1]): partially_preserved - only {label}'s "
                             + ("hair, build and wardrobe from behind" if hidden == "BEHIND" else "build and wardrobe")
                             + f" are kept; {label}'s face is not shown.")
        else:
            retention.append(f"{tag[cid]} (appears in [Shot 1]): fully_preserved - {label}'s face, hair, build and "
                             f"wardrobe stay identical from the first frame to the last; {label} is the same person "
                             "already in <Picture 1> and appears exactly once.")
    retention.append(f"<Subject {setting_no}> (appears in [Shot 1]): fully_preserved - the location, set dressing, "
                     "period details and light of <Picture 1> are kept.")
    for row in p.crossmodal_rows:
        retention.append(f"{_labels(str(row.get('audio_slot') or '@Audio1'))}: reference - only "
                         f"{row.get('provider_entity_label')}'s voice timbre is followed; the reference recording's "
                         "own words are not spoken.")

    # --- detailed_description ---------------------------------------------------------------------------
    # the period lock stays whole where the visual-culture gate requires its tokens (EAST-ASIAN PERIOD VISUAL LOCK);
    # otherwise only its positive sentences open the description (the official guide carries no negative lists)
    required_lock = "EAST-ASIAN PERIOD VISUAL LOCK" in p.look
    style_bits = [sentence.strip() for sentence in re.split(r"(?<=\.)\s+", _labels(p.look).replace("Look: ", ""))
                  if sentence.strip() and (required_lock or not sentence.strip().lower().startswith(("never", "no ")))]
    style = ("The target video is a live-action, cinematic vertical drama with natural matte skin texture."
             if not p.anime else "The target video is a 2D anime vertical drama.")
    if not required_lock:  # an authored-world / neutral lock's all-caps title would trip the V2 self-check
        style_bits = [b for b in (_LOCK_TITLE.sub("", b, count=1).strip() for b in style_bits) if b]
    if style_bits:
        style += " " + " ".join(_s(b) for b in style_bits)
    body: list[str] = []
    entry_first = str(p.records[0]["entry"] or "")
    if _OPENING_ENTRY.match(entry_first):
        body.append(f"The shot begins exactly on <Picture 1>, {entry_first.strip().rstrip('.')}.")
    else:
        body.append("The shot begins exactly on <Picture 1>.")
    body.append(_camera_sentence(p))
    ev["CAMERA.PLAN"] = body[-1]
    roster = []
    english_camera = p.contract.get("camera_plan") or {}
    framing = str(english_camera.get("start_framing") or "").strip().rstrip(".")
    if framing:  # the authored framing, as the V2 Camera block states it
        roster.append(_s("Framing: " + framing))
    for s in p.subjects:
        cid, label = s["entity_id"], s["label"]
        partial = set(s.get("partial", {}).values())
        if _ots_part() in partial or p.face_hidden.get(cid) == "BEHIND":
            roster.append(_s(_ots(label)))
        else:
            roster.append(_s(f"{tag[cid]} is {label}, placed as in <Picture 1>"))
    scope = unit.get("provider_scope_projection") or {}
    counts = scope.get("visible_entity_instance_counts") or {}
    population = _psp().official_population_clause(
        sum(int(counts.get(s["entity_id"]) or 1) for s in people),
        sum(int(counts.get(s["entity_id"]) or 1) for s in beings),
        int(scope.get("unbound_visible_living_entity_count") or 0), scope.get("anonymous_role_descriptors") or [])
    body.append(_s(population[:1].upper() + population[1:] + ", each exactly once: "
                   + _join([s["label"] for s in p.subjects])
                   + (", each in their own clothes" if len(people) > 1 else "")))
    body.extend(roster)
    if p.adult_line:
        body.append(p.adult_line)
    scene = [v for v in (p.setting_en, _s(p.space_weather), *[_s(r) for r in p.env_rows], _s(p.prop_fact),
                         *([_s("Props: " + "; ".join(p.prop_sentences))] if p.prop_sentences else [])) if v]
    if scene:
        body.append(f"<Subject {setting_no}>: " + " ".join(scene))
    # V2's lines between the "Action (0-N s):" header and the first beat (content window, a non-equal inherited
    # opening, the "Throughout:" lock) are stated before the beats; dropping them left PACING.CONTENT_WINDOW
    # uncovered (1205 E17-VU-006)
    first_beat = p.records[0]["line_index"] if p.records else p.beats_end
    body.extend(_labels(x) for x in p.action_lines[1:first_beat] if x)
    multi = len(p.records) > 1
    for number, record in enumerate(p.records):
        prefix = f"BEAT.{number + 1}"
        out: list[str] = []
        label = record["speaker_label"]
        cid = id_by_label.get(label, "")
        row = p.dialogue_rows[record["dialogue_index"]] if record.get("dialogue_index") is not None else None
        listener = (row or {}).get("listeners") or []
        speaks = re.compile(rf"^{re.escape(label)} speaks(?: line \d+)?(?: from offscreen)?\.$") if label else None
        perf_before = _performance(p, record, _BEFORE_LINE, cid, label, _join(listener)) if row else []
        perf_after = _performance(p, record, _AFTER_LINE, cid, label, _join(listener)) if row else []
        if perf_before or perf_after:
            ev[f"{prefix}.PERFORMANCE_TIMELINE"] = " ".join(perf_before + perf_after)
        for part in record["parts"]:
            if part.startswith("Start"):
                entry = part.split(": ", 1)[1] if ": " in part else part
                if number == 0 and _OPENING_ENTRY.match(entry):
                    continue  # stated by the opening sentence
                out.append(_s(("Continuing straight from the previous shot with no reset, " if "inherited" in part
                               else "At the start, ") + _low(entry)))
                ev[f"{prefix}.ENTRY"] = out[-1].rstrip(".")
                continue
            if part.startswith("End: "):
                out.append(_s("By the end, " + _low(part[5:])))
                ev[f"{prefix}.EXIT"] = out[-1].rstrip(".")
                continue
            if speaks is not None and speaks.match(part) and row is not None:
                out.extend(perf_before)
                out.append(_dialogue_sentence(row, tag.get(cid, label), speaker_ids[label],
                                              audio_by_label.get(label, "")))
                ev[f"{prefix}.DIALOGUE_DELIVERY"] = out[-1].split(" <d>", 1)[0]
                out.extend(perf_after)
                continue
            out.append(_labels(part))
        if row is not None and not any("<d>" in o for o in out):  # no "X speaks" sentence: the line goes last
            out.extend(perf_before)
            out.append(_dialogue_sentence(row, tag.get(cid, label), speaker_ids[label], audio_by_label.get(label, "")))
            out.extend(perf_after)
        if row is not None and row.get("gaze"):
            out.append(row["gaze"])
        nxt = p.records[number + 1]["line_index"] if number + 1 < len(p.records) else p.beats_end
        out.extend(_labels(x) for x in p.action_lines[record["line_index"] + 1:nxt])
        text = " ".join(o for o in out if o)
        if multi:
            text = f"From {record['start']:g} to {record['end']:g} seconds, " + text[:1].lower() + text[1:]
        body.append(text)
    # an outgoing transition equal to the last beat's exit is covered by that exit sentence (V2 adds no handoff);
    # the official order rewrote it as "By the end, ...", so the evidence follows the rewritten text (1205 E17)
    last_exit_key = f"BEAT.{len(p.records)}.EXIT"
    outgoing = ev.get("TRANSITION.OUTGOING")
    if (outgoing and p.records and last_exit_key in ev
            and _flat(outgoing) == _flat(p.records[-1].get("exit") or "")):
        ev["TRANSITION.OUTGOING"] = ev[last_exit_key]
    # likewise an incoming transition equal to the first beat's entry: V2 adds no "Open directly from ..." sentence
    # and registers the raw entry; the official order rewrote it as "Continuing straight from ..." (1205 E17-VU-002)
    incoming = ev.get("TRANSITION.INCOMING")
    if (incoming and p.records and "BEAT.1.ENTRY" in ev
            and _flat(incoming) == _flat(p.records[0].get("entry") or "")):
        ev["TRANSITION.INCOMING"] = ev["BEAT.1.ENTRY"]
    # and a force origin V2 defaulted to the raw entry (no force_origin translation) follows the rewritten entry too
    for number, record in enumerate(p.records, 1):
        force, entry_key = ev.get(f"BEAT.{number}.FORCE_ORIGIN"), f"BEAT.{number}.ENTRY"
        if force and entry_key in ev and _flat(force) == _flat(record.get("entry") or ""):
            ev[f"BEAT.{number}.FORCE_ORIGIN"] = ev[entry_key]
    tail = p.action_lines[p.beats_end:]
    for line in tail:
        if line.startswith("Everyone keeps the posture"):
            body.append("Everyone keeps the posture of the first frame for the whole clip: whoever is seated stays "
                        "seated and whoever stands stays standing.")
            ev["PHYSICAL.POSTURE_HOLD"] = body[-1].rstrip(".")
        elif line.startswith("Every hand stays attached"):
            body.append("Every hand stays attached to its owner's body.")
            ev["PHYSICAL.INTERACTION_TOPOLOGY"] = body[-1].rstrip(".")
        else:
            body.append(_labels(line))
    if p.dialogue_rows:
        body.append("This is the only speech in the clip; before and after it only the room sound is heard."
                    if len(p.dialogue_rows) == 1 else
                    "These are the only lines spoken, each once and in this order; between and after them only the "
                    "room sound is heard.")
    else:
        body.append("Nobody speaks; every visible person keeps their mouth closed.")
    description = style + "\n[Shot 1] " + " ".join(b for b in body if b)

    soundscape = " ".join(_s(r) for r in p.sound_rows) or "Native location ambience and quiet foley."
    sections = [
        "subject_definitions:\n" + "\n".join(definitions),
        "summary:\n" + summary,
        "retention_analysis:\n" + "\n".join(retention),
        "detailed_description:\n" + description,
        "overall_soundscape:\n" + soundscape,
        "non_diegetic_music:\nN/A",
    ]
    return "\n\n".join(sections) + "\n"


def _psp():
    try:
        from tools import provider_scope_projection as psp
    except ModuleNotFoundError:  # pragma: no cover
        import provider_scope_projection as psp  # type: ignore
    return psp


def _ots_part() -> str:
    try:
        from tools.h3_provider_prompt_renderer import OTS_PART
    except ModuleNotFoundError:  # pragma: no cover
        from h3_provider_prompt_renderer import OTS_PART  # type: ignore
    return OTS_PART


def _ots(label: str) -> str:
    try:
        from tools.h3_provider_prompt_renderer import ots_clause
    except ModuleNotFoundError:  # pragma: no cover
        from h3_provider_prompt_renderer import ots_clause  # type: ignore
    return ots_clause(label)


def _dialogue_sentence(row: dict[str, Any], subject: str, speaker_id: str, audio_slot: str) -> str:
    delivery = str(row.get("delivery") or "").strip()
    delivery = re.sub(r"^Delivery:\s*", "", delivery).rstrip(".")
    voice = f", using the voice timbre referenced from {_labels(audio_slot)}," if audio_slot else ""
    lead = _s(delivery) + " " if delivery else ""
    if not row.get("visible"):
        listeners = row.get("listeners") or []
        closed = (f" while {_join(listeners)}'s lips remain completely closed" if listeners
                  else " while every visible mouth stays closed")
        return f"{lead}{subject} ({speaker_id}){voice} says in an off-screen voiceover: {row['literal']}{closed}."
    return f"{lead}{subject} ({speaker_id}){voice} says: {row['literal']}"
