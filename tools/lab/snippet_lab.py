#!/usr/bin/env python3
"""Snippet lab: compile a few screenplay lines with the engine, print the exact H3 prompts, optionally run them on
MiniMax-H3 -- no device, no episode, minutes instead of a day (line owner 2026-11-26: "可以本地跑一些片段来测，不用跑
一整集").

A *lab dir* holds the writer's normal files for one snippet (the same names S1 compiles), plus ``LAB.json`` (the
English look of the cast / place and the reference images, standing in for S2-S5):

    <lab>/SERIES_CARD.yaml   <lab>/LAB_SCREENPLAY.md   <lab>/LAB_CAST_PROPS.yaml (JSON ok)
    <lab>/LAB_SCREENPLAY_EN.json (English twins; missing rows are listed and filled with compiler English)
    <lab>/LAB.json           {"episode": "LAB", "characters": {cid: {"wardrobe_en", "face", "voice"}},
                              "locations": {loc_id: {"setting_en", "sound_en"}}, "first_frames": {shot_id: path},
                              "duration": 4, "resolution": "480p"}

Commands (run from any engine checkout; ``--engine`` picks the engine that compiles / renders, so the same lab dir
renders with origin/main and with a branch for an A/B):

    snippet_lab.py extract  --contract E28_GENERATION_CONTRACT_v1.json --shots E28-S01-01,E28-S01-03 --out <lab>
    snippet_lab.py render   <lab> [--engine <checkout>] [--shots ...] [--arm NAME]   # prints + writes prompts
    snippet_lab.py run      <lab> --arm NAME [--samples 2] [--budget 40]               # paid: H3 480p
    snippet_lab.py check    <lab> --arm NAME                                           # OCR + 4 fps contact sheets

``render`` = ``screenplay_compile.compile_screenplay`` -> ``director_pass.direct`` -> one single-shot H3 unit per
dialogue shot -> ``h3_provider_prompt_renderer.render_h3_prompt``.  The unit wrapper (references, roster, setting,
sound, English entry / exit) is a lab stand-in for S2; everything the writer controls (action, performance,
delivery, 脑补 visuals, listener reaction) and every guardrail comes from the engine exactly as on a device.

An arm directory may hold its own ``LAB.json`` (deep-merged over the lab's: per-arm ``first_frames``, ``characters
.<cid>.face|voice``, ``duration``, ``generate_audio``) so input levers (reference source, voice anchor, duration) are
bisected side by side on one lab dir; ``run`` warns about inputs a device never sends (no voice anchor).  First
frames / faces must never come from subtitled footage, not even cropped above the band: render them clean with
gpt-image-2 (BURN_BISECT2).

``run`` is the only paid step: one POST per clip, never retried, a ledger per arm (``<lab>/<arm>/ledger.json``), a
credit budget checked before every POST.  The HopsAPI key is taken the way paid_stage.sh does (environment, else the
engine ``.env``, else ``~/nalu_runtime/credentials/llm_provider.json`` when that provider is HopsAPI) and never
printed.  ``check`` needs ``rapidocr_onnxruntime`` + ``cv2`` (``~/nalu_verify/engine/.qingshan-venv``).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
DEFAULT_ENGINE = HERE.parents[2]
EP = "LAB"
SHA = "0" * 64
CJK = re.compile(r"[㐀-鿿]")
SCALE_EN = {"EXTREME_CLOSE_UP": "Extreme close-up", "CLOSE_UP": "Close-up", "MEDIUM_CLOSE_UP": "Medium close-up",
            "MEDIUM": "Medium shot", "MEDIUM_WIDE": "Medium-wide shot", "FULL": "Full shot", "WIDE": "Wide shot"}
CREDITS_PER_SECOND_480P = 1.085  # observed 2026-11-26: 4 s 480p + audio = 4.34 credits


# =========================================================================== engine import
def load_engine(engine: Path) -> dict[str, Any]:
    engine = Path(engine).resolve()
    for p in (engine / "lines" / "nalu" / "runtime" / "tools", engine / "tools", engine):
        sys.path.insert(0, str(p))
    mods = {}
    for name in ("screenplay_compile", "director_pass"):
        mods[name] = importlib.import_module(name)
    mods["renderer"] = importlib.import_module("tools.h3_provider_prompt_renderer")
    mods["english_schema"] = importlib.import_module("tools.h3_provider_english_contract").SCHEMA
    return mods


# =========================================================================== extract: contract -> lab dir
def _scene_md(scene: dict[str, Any], names: dict[str, str], keep: set[str], visual: dict[str, Any]) -> list[str]:
    card = scene.get("card") or {}
    out = [f"## {scene['scene_id'].split('-')[-1]} {scene.get('heading') or ''}".rstrip()]
    goal = next(iter(card.get("goals") or []), {})
    out.append(f"@card goal[{names.get(goal.get('who'), goal.get('who') or '')}]={card.get('objective') or '-'} | "
               f"obstacle={card.get('conflict') or '-'} | turn={card.get('turn') or '-'} | "
               f"type={card.get('scene_type') or '-'}")
    see = []
    if visual.get("stakes"):
        see.append(f"赌注={visual['stakes']}")
    if visual.get("environment"):
        see.append(f"环境={visual['environment']}")
    for cid, text in (visual.get("business") or {}).items():
        see.append(f"{names.get(cid, cid)}={text}")
    if see:
        out.append("@see " + " | ".join(see))
    for row in scene.get("lines") or []:
        if row.get("shot_id") not in keep:
            continue
        if row["kind"] == "action":
            out.append(row["text"])
        elif row["kind"] == "dialogue":
            paren = f"（{row['paren']}）" if row.get("paren") else ""
            out.append(f"{names.get(row['speaker'], row['speaker'])}{paren}：{row['text']}")
        elif row["kind"] == "reaction":
            out.append(f"[{names.get(row['who'], row['who'])} 反应：{row['text']}]")
    return out


def extract(args: argparse.Namespace) -> int:
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    eng = load_engine(Path(args.engine or DEFAULT_ENGINE))
    spc = eng["screenplay_compile"]
    keep = set(s.strip() for s in args.shots.split(",") if s.strip())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ents = {e["character_id"]: e for e in contract.get("character_entities") or []}
    names = {cid: e.get("canonical_name") or cid for cid, e in ents.items()}
    shots = {s["shot_id"]: s for s in contract.get("shots") or []}
    md = [f"# lab snippet from {contract.get('episode')} ({', '.join(sorted(keep))})", ""]
    locations: dict[str, dict[str, Any]] = {}
    for scene in (contract.get("screenplay_v1") or {}).get("scenes") or []:
        ids = [sid for sid in scene.get("shot_ids") or [] if sid in keep]
        if not ids:
            continue
        first = (shots.get(ids[0]) or {}).get("prompt_spec") or {}
        md += _scene_md(scene, names, keep, first.get("visual") or {}) + [""]
        state = next((r for r in contract.get("scene_states") or [] if r.get("scene_id") == scene["scene_id"]), {})
        locations[scene["location_id"]] = {
            "id": scene["location_id"], "name": (scene.get("heading") or "").split(" · ")[0],
            "set_pieces": scene.get("set_pieces") or [], "weather": scene.get("weather") or state.get("weather") or "",
            "ambience": ((first.get("sound") or {}).get("ambience") or "")}
    cast = []
    for cid, e in ents.items():
        cast.append({"id": cid, "name": names[cid], "english_name": e.get("english_name") or "",
                     "aliases": e.get("aliases") or [], "gender": e.get("gender") or "",
                     "age": e.get("apparent_age_range") or "", "wardrobe": (e.get("wardrobe_garments") or {})})
    props = [{"id": c["entity_id"], "name": c["name"], "aliases": c.get("aliases") or [], "owner": c.get("owner_id") or "",
              "hand": c.get("hand") or "", "description": c.get("description") or "",
              **({"description_en": c["description_en"]} if c.get("description_en") else {})}
             for c in (contract.get("props") or {}).get("reference_cards") or []]
    cast_props = {"episode": EP, "dialogue_language": contract.get("dialogue_language") or "zh", "cast": cast,
                  "props": props, "locations": list(locations.values()),
                  "visual_culture_contract": {k: v for k, v in (contract.get("visual_culture_contract") or {}).items()
                                              if k not in ("schema", "status")}}
    card = contract.get("series_card") or {}
    series = {"premise": card.get("premise") or "", "engine": card.get("engine") or "",
              "characters": [{"id": r.get("character_id"), **{k: r[k] for k in ("name", "voice", "verbal_habit",
                                                                                 "signature_business", "signature_prop")
                                                               if r.get(k)}} for r in card.get("characters") or []]}
    # English twins harvested from the contract (same zh -> same key when the snippet recompiles)
    rows: dict[str, str] = {}

    def add(field: str, zh: Any, en: Any) -> None:
        if isinstance(zh, str) and isinstance(en, str) and zh.strip() and en.strip():
            rows[spc.en_key(field, zh)] = en

    for sid in keep:
        spec = (shots.get(sid) or {}).get("prompt_spec") or {}
        action = spec.get("action") or {}
        perf = action.get("performance") or {}
        add("action", action.get("primary_action"), action.get("action_en"))
        add("action", perf.get("body_action"), perf.get("business_en"))
        add("delivery", perf.get("delivery"), perf.get("delivery_en"))
        add("reaction", action.get("listener_reaction"), action.get("listener_reaction_en"))
        add("reaction", action.get("lead_in_reaction"), action.get("lead_in_reaction_en"))
        visual = spec.get("visual") or {}
        for key in ("stakes", "detail", "environment"):
            add("visual", visual.get(key), visual.get(f"{key}_en"))
        for cid, text in (visual.get("business") or {}).items():
            add("visual", text, (visual.get("business_en") or {}).get(cid))
    for c in props:
        add("prop", c.get("description") or c.get("name"), c.get("description_en"))
    (out / "LAB_SCREENPLAY.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    (out / "LAB_CAST_PROPS.yaml").write_text(json.dumps(cast_props, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    (out / "SERIES_CARD.yaml").write_text(json.dumps(series, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    en_path = out / "LAB_SCREENPLAY_EN.json"
    if not en_path.exists():
        en_path.write_text(json.dumps({"schema": spc.EN_SCHEMA, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
    lab = out / "LAB.json"
    if not lab.exists():
        lab.write_text(json.dumps({
            "episode": EP, "duration": 4, "resolution": "480p",
            "characters": {cid: {"wardrobe_en": "", "face": "", "voice": ""} for cid in ents},
            "locations": {lid: {"setting_en": "", "sound_en": ""} for lid in locations},
            "first_frames": {sid: "" for sid in sorted(keep)}}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    print(f"lab dir: {out}  (fill LAB.json: wardrobe_en / setting_en / sound_en / face / first_frames)")
    return 0


# =========================================================================== render
def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return text


def _yaml_or_json(spc: Any, text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return spc.read_light_yaml(text) if text.strip() else None


def compile_lab(lab: Path, eng: dict[str, Any]) -> dict[str, Any]:
    spc = eng["screenplay_compile"]
    cast_props = _yaml_or_json(spc, _read(lab / "LAB_CAST_PROPS.yaml")) or {}
    series = _yaml_or_json(spc, _read(lab / "SERIES_CARD.yaml")) or {}
    answers_path = lab / "LAB_SCREENPLAY_EN.json"
    answers = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.is_file() else None
    out = spc.compile_screenplay(spc.parse(_read(lab / "LAB_SCREENPLAY.md")), cast_props, series, {}, episode=EP,
                                 translations=answers, en_fallback=True)
    directed, report = eng["director_pass"].direct(out["contract"], force=True)
    out["contract"] = directed
    out["director_report"] = report
    return out


def _label(contract: dict[str, Any], cid: str) -> str:
    for e in contract.get("character_entities") or []:
        if e.get("character_id") == cid:
            return e.get("english_name") or cid
    return cid


def _framing(spec: dict[str, Any], labels: dict[str, str]) -> str:
    cam = spec.get("camera_plan") or {}
    scale = SCALE_EN.get(str(cam.get("shot_scale") or ""), "Medium shot")
    faces = [labels[c["character_id"]] for c in spec.get("cast") or [] if c.get("face_visibility") != "BACK_AND_SHOULDERS_ONLY"]
    backs = [labels[c["character_id"]] for c in spec.get("cast") or [] if c.get("face_visibility") == "BACK_AND_SHOULDERS_ONLY"]
    text = f"{scale}, vertical frame: {' and '.join(faces) or 'the subject'} facing camera"
    if backs:
        text += f", {' and '.join(backs)}'s back and shoulder soft in the near foreground"
    return text


def _exit_en(action: dict[str, Any]) -> str:
    perf = action.get("performance") or {}
    return perf.get("business_en") or action.get("action_en") or "the same positions as the first frame"


def lab_unit(contract: dict[str, Any], shot: dict[str, Any], lab_cfg: dict[str, Any], english_schema: str,
             *, voice: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = copy.deepcopy(shot["prompt_spec"])
    sid = shot["shot_id"]
    uid = f"{EP}-VU-{sid.split('-', 1)[-1]}"
    duration = float(lab_cfg.get("duration") or shot.get("target_seconds") or 4)
    role = spec.get("role_semantic_disambiguation") or {}
    cast_ids = [c["character_id"] for c in spec.get("cast") or []]
    labels = {cid: _label(contract, cid) for cid in cast_ids + [role.get("dialogue_speaker_id") or ""] if cid}
    chars = lab_cfg.get("characters") or {}
    speaker = role.get("dialogue_speaker_id") or ""
    refs = [{"path": f"{sid}_first.png", "role": "ADMITTED_NEW_EVENT_ENTRY_STATE"}]
    bindings = []
    for cid in cast_ids:
        if not (chars.get(cid) or {}).get("face"):
            continue  # no face image in LAB.json: the person is in the roster but has no identity reference
        refs.append({"path": f"{cid}.png", "role": "CHARACTER_IDENTITY_REFERENCE"})
        bindings.append({"reference_index": len(refs), "entity_id": cid, "provider_entity_label": labels[cid],
                         "exclusive_identity_owner": True, "role": "CHARACTER_IDENTITY_REFERENCE",
                         "binding_role": "IDENTITY", "may_define_identity": True})
    spec["role_semantic_disambiguation"] = {**role, "shot_id": sid, "entity_visible_extent": {}}
    spec["shot_id"] = sid
    cam = {**(spec.get("camera_plan") or {}), "camera_grammar": "CAMERA_GRAMMAR_V1"}
    framing = _framing(spec, labels)
    cam.update(start_framing=framing, end_framing=framing)
    spec["camera_plan"] = cam
    dialogue = shot.get("dialogue") or ""
    speakers = []
    if dialogue and speaker:
        slot = cast_ids.index(speaker) + 2 if speaker in cast_ids else 1
        speakers.append({"speaker": dialogue.split("：", 1)[0], "character_id": speaker,
                         "provider_entity_label": labels.get(speaker, speaker), "subject_token": f"SUBJECT_{slot}",
                         "image_slot": f"@Image{slot}", "speaker_slot": "SPEAKER_1", "audio_slot": "@Audio1",
                         "visible_speaker": speaker in cast_ids, "lip_sync": speaker in cast_ids})
    loc = (lab_cfg.get("locations") or {}).get(shot.get("location_id") or "", {})
    ambience_zh = str((spec.get("sound") or {}).get("ambience") or "环境声")
    sound_en = loc.get("sound_en") or "Quiet room tone"
    beat = {"source_index": 1, "start_seconds": 0.0, "end_seconds": duration, "entry_state": shot.get("entry_state"),
            "primary_action": (spec.get("action") or {}).get("primary_action") or "", "exit_state":
                shot.get("completion_state"), "interaction_mode": "NONE", "dialogue": dialogue,
            "dialogue_delivery": {}, "secondary_feedback": [], "shot_id": sid}
    plan = {
        "unit_id": uid, "model_family": "MINIMAX_H3", "duration_seconds": duration,
        "execution_semantics_sha256": SHA, "immutable_contract_sha256": SHA, "camera_language_selection": {},
        "motion_density_gate": {"status": "PASS"}, "camera_plan": cam, "beats": [beat],
        "role_bindings": [{"shot_id": sid, "entity_face_visibility": {c["character_id"]: c.get("face_visibility", "")
                                                                      for c in spec.get("cast") or []}}],
        "sounds": {"ambience": [ambience_zh], "foley": [], "action_sound": []},
        "environment_motion": [], "voice_bindings": [{"speaker": s["speaker"]} for s in speakers],
        "h3_crossmodal_speaker_binding": {"status": "PASS" if speakers else "NOT_APPLICABLE", "bindings": speakers,
                                          "failures": []},
        "transition": {}, "interaction_topology_required": len(cast_ids) > 1,
    }
    action = spec.get("action") or {}
    english = {
        "schema": english_schema, "source_execution_semantics_sha256": SHA,
        "identity_prop_fact": "Characters: " + ", ".join(labels[c] for c in cast_ids),
        "space_weather_fact": f"Time: {spec.get('scene_state', {}).get('time') and 'night' or 'day'}",
        "beats": [{"entry_state": "as in the opening frame",
                   "primary_action": action.get("action_en") or (action.get("performance") or {}).get("business_en")
                   or f"{labels.get(speaker, 'The subject')} faces the other person",
                   "exit_state": _exit_en(action), "secondary_feedback": []}],
        "sounds": {"ambience": [sound_en], "foley": [], "action_sound": []},
        "environment_motion": [], "camera_plan": {"start_framing": framing, "end_framing": framing},
        "director_v2": {"subjects": {cid: {"wardrobe": (chars.get(cid) or {}).get("wardrobe_en") or ""}
                                     for cid in cast_ids},
                        "setting": loc.get("setting_en") or ""},
    }
    if lab_cfg.get("time_en"):
        english["space_weather_fact"] = lab_cfg["time_en"]
    unit = {
        "unit_id": uid, "model": "MiniMax-H3", "episode": EP, "craft_profile": "BILI_V1",
        "h3_prompt_style": "DIRECTOR_PROMPT_V2", "dialogue_language": contract.get("dialogue_language") or "zh",
        "reference_images": refs,
        "provider_scope_projection": {
            "schema": "qingshan.provider_scope_projection.v1", "status": "LOCKED",
            "provider_reads_episode_global_contract_directly": False, "exclusive_visible_living_entity_set": True,
            "reference_identity_bindings": bindings, "visible_character_ids": cast_ids,
            "visible_entity_instance_counts": {c: 1 for c in cast_ids},
            "visible_living_entity_instance_total": len(cast_ids), "background_population_count": 0,
            "unbound_visible_living_entity_count": 0, "anonymous_role_descriptors": []},
        "ordered_prompt_specs": [spec],
        "visual_culture_contract": contract.get("visual_culture_contract") or {},
        "character_entities": [{**e, "english_name": e.get("english_name") or e["character_id"]}
                               for e in contract.get("character_entities") or [] if e["character_id"] in labels],
        "wardrobe_contract": {"characters": [{"character": e.get("canonical_name"), "character_id": e["character_id"],
                                              "authored_description": (chars.get(e["character_id"]) or {})
                                              .get("wardrobe_en") or ""}
                                             for e in contract.get("character_entities") or []
                                             if e["character_id"] in cast_ids]},
        "h3_provider_english_contract": english,
    }
    if lab_cfg.get("h3_prompt_format"):  # per-arm A/B of the H3 prompt format (OFFICIAL_REF_V1 / DIRECTOR_V2)
        unit["h3_prompt_format"] = lab_cfg["h3_prompt_format"]
    return unit, plan


def strip_voice_lines(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if not line.startswith("@Audio"))


def render(args: argparse.Namespace) -> int:
    lab = Path(args.lab)
    eng = load_engine(Path(args.engine or DEFAULT_ENGINE))
    out = compile_lab(lab, eng)
    report = out["report"]
    arm = args.arm or "render"
    dest = lab / arm
    dest.mkdir(parents=True, exist_ok=True)
    cfg = arm_config(lab, dest)  # the arm's own voice anchor / duration shape the rendered prompt too
    (dest / "compile_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (dest / "contract.json").write_text(json.dumps(out["contract"], ensure_ascii=False, indent=1) + "\n", "utf-8")
    (dest / "directing.md").write_text(out.get("directing_md") or "", "utf-8")
    if report.get("errors"):
        print("COMPILE ERRORS:", report["errors"])
        return 2
    if out["en_request"]["rows"]:
        (dest / "en_request.json").write_text(json.dumps(out["en_request"], ensure_ascii=False, indent=1) + "\n",
                                              "utf-8")
        print(f"NOTE {len(out['en_request']['rows'])} English twins missing (compiler English used): "
              f"{dest / 'en_request.json'}")
    for w in report.get("warnings") or []:
        print("warning:", w)
    wanted = {s.strip() for s in (args.shots or "").split(",") if s.strip()}
    voice = any((c or {}).get("voice") for c in (cfg.get("characters") or {}).values())
    prompts = {}
    for shot in out["contract"]["shots"]:
        if not shot.get("dialogue"):
            continue
        key = shot["shot_id"].replace(f"{EP}-", "")
        if wanted and key not in wanted and shot["shot_id"] not in wanted:
            continue
        unit, plan = lab_unit(out["contract"], shot, cfg, eng["english_schema"], voice=voice)
        text, receipt = eng["renderer"].render_h3_prompt(unit, plan)
        if not voice:
            text = strip_voice_lines(text)
        prompts[key] = {"text": text, "chars": len(text), "receipt_status": receipt.get("status"),
                        "dialogue": shot["dialogue"], "speaker": shot["prompt_spec"]["role_semantic_disambiguation"]
                        .get("dialogue_speaker_id"), "cast": [c["character_id"] for c in shot["prompt_spec"]["cast"]]}
        (dest / f"{key}.txt").write_text(text, "utf-8")
        print(f"\n===== {key} [{arm}] {len(text)} chars, receipt {receipt.get('status')} =====\n{text}")
    (dest / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return 0


# =========================================================================== run (paid)
def _env_value(path: Path, name: str) -> str:
    try:
        m = re.search(rf"^\s*(?:export\s+)?{re.escape(name)}=(.*)$", path.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return m.group(1).strip().strip("'\"") if m else ""


@contextlib.contextmanager
def hopsapi_key(engine: Path):
    """paid_stage.sh's lookup: environment, else <engine>/.env, else the Codex provider key when it is HopsAPI."""
    saved = os.environ.get("HOPSAPI_API_KEY")
    try:
        if not (saved or "").strip():
            key = _env_value(engine / ".env", "HOPSAPI_API_KEY")
            if not key:
                prov = Path.home() / "nalu_runtime" / "credentials" / "llm_provider.json"
                try:
                    row = json.loads(prov.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    row = {}
                if "hopsapi" in str(row.get("base_url") or "").lower():
                    key = str(row.get("api_key") or "").strip()
            if key:
                os.environ["HOPSAPI_API_KEY"] = key
        yield bool((os.environ.get("HOPSAPI_API_KEY") or "").strip())
    finally:
        if saved is None:
            os.environ.pop("HOPSAPI_API_KEY", None)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def arm_config(lab: Path, arm_dir: Path) -> dict[str, Any]:
    """LAB.json, deep-merged with an optional ``<arm>/LAB.json`` (per-arm first frames, faces, voice anchor,
    ``duration``, ``generate_audio``) so one lab dir holds input-lever arms side by side."""
    cfg = json.loads((lab / "LAB.json").read_text(encoding="utf-8"))
    over = arm_dir / "LAB.json"
    if over.exists():
        cfg = _merge(cfg, json.loads(over.read_text(encoding="utf-8")))
    return cfg


def input_warnings(row: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Lab inputs that make H3 burn the line as a subtitle where a device would not (BURN_BISECT2, 2026-11-26:
    E28 S01-05 / S01-03 / S01-06 burned in every render with first frame + faces cropped from E27's released,
    subtitled cut and no voice anchor; a gpt-image-2 re-render of the same refs, or an @Audio1 voice anchor, each
    gave 0 burned renders).  A device always sends both, so a burn seen without them is not a device burn."""
    out = []
    speaker = row.get("speaker") or ""
    if speaker and not ((cfg.get("characters") or {}).get(speaker) or {}).get("voice"):
        out.append(f"no voice anchor for speaker {speaker} (a device always sends @Audio1; without it H3 burns "
                   "far more often)")
    if cfg.get("generate_audio") is False:
        out.append("generate_audio=false is ignored by the HopsAPI router (the clip still speaks; observed "
                   "2026-11-26)")
    return out


def run(args: argparse.Namespace) -> int:
    lab = Path(args.lab)
    engine = Path(args.engine or DEFAULT_ENGINE).resolve()
    sys.path[:0] = [str(engine), str(engine / "tools")]
    from tools import hopsapi_video_client as hv  # noqa: PLC0415
    arm_dir = lab / args.arm
    cfg = arm_config(lab, arm_dir)
    prompts = json.loads((arm_dir / "prompts.json").read_text(encoding="utf-8"))
    ledger_path = arm_dir / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    shared_path = lab / "uploads.json"
    uploads = json.loads(shared_path.read_text()) if shared_path.exists() else {}

    def save() -> None:
        ledger_path.write_text(json.dumps(ledger, indent=1))
        shared_path.write_text(json.dumps(uploads, indent=1))

    duration = int(cfg.get("duration") or 4)
    per_clip = round(CREDITS_PER_SECOND_480P * duration, 2)
    spent = sum(float(r.get("cost") or per_clip) for r in ledger.values() if isinstance(r, dict) and r.get("task"))
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"  # lab ledger = this script's own transaction record
    with hopsapi_key(engine) as ok:
        if not ok:
            print("HOPSAPI_API_KEY not found (env, engine .env, ~/nalu_runtime/credentials)")
            return 2

        def upload(path: str, kind: str) -> str:
            p = Path(path).expanduser()
            data = p.read_bytes()
            key = hashlib.sha256(data).hexdigest()[:16]
            if key not in uploads:
                mime = "audio/wav" if kind == "audios" else hv.sniff_mime(data, str(p))
                uploads[key] = hv.upload_bytes(data, file_name=f"lab-{key}{p.suffix}", upload_path=kind,
                                               mime=mime)["url"]
                save()
            return uploads[key]

        chars = cfg.get("characters") or {}
        for key, row in prompts.items():
            first = (cfg.get("first_frames") or {}).get(key) or (cfg.get("first_frames") or {}).get(f"{EP}-{key}")
            if not first:
                print(f"skip {key}: no first frame in LAB.json")
                continue
            # same order as lab_unit's references: the first frame, then each cast member with a face image
            images = [upload(first, "images")] + [upload(chars[c]["face"], "images") for c in row["cast"]
                                                  if (chars.get(c) or {}).get("face")]
            voice = (chars.get(row.get("speaker") or "") or {}).get("voice")
            audios = [upload(voice, "audios")] if voice else []
            for problem in input_warnings(row, cfg):
                print(f"WARNING {key}: {problem}")
            for k in range(args.samples):
                name = f"{key}_{k}"
                rec = ledger.setdefault(name, {})
                if rec.get("task"):
                    continue
                if spent + per_clip > args.budget:
                    print(f"budget {args.budget} reached ({spent:.2f} spent); stop")
                    break
                payload = hv.build_omni_request(prompt=row["text"], image_urls=images, audio_urls=audios,
                                                duration=duration, resolution=cfg.get("resolution") or "480p",
                                                aspect_ratio="9:16",
                                                generate_audio=bool(cfg.get("generate_audio", True)))
                rec.update(state="INTENT", prompt_sha=hashlib.sha256(row["text"].encode()).hexdigest()[:12])
                save()
                rec["task"] = hv.create_task(payload)["task_id"]
                rec["state"] = "SUBMITTED"
                spent += per_clip
                save()
                print(f"submitted {args.arm}/{name}")
        pending = [k for k, r in ledger.items() if r.get("state") == "SUBMITTED"]
        while pending:
            for name in list(pending):
                rec = ledger[name]
                st = hv.query_task(rec["task"])
                if st["remote_status"] == "completed" and st["urls"]:
                    dest = arm_dir / f"{name}.mp4"
                    hv.download_video(st["urls"][0], dest)
                    rec.update(file=str(dest), cost=st.get("cost"), state="DONE")
                    pending.remove(name)
                elif st["remote_status"] in ("failed", "cancelled"):
                    rec.update(state="FAILED", status=str(st)[:300])
                    pending.remove(name)
                save()
            if pending:
                time.sleep(20)
    print(json.dumps({k: (r.get("state"), r.get("cost")) for k, r in ledger.items()}, indent=1))
    return 0


# =========================================================================== check: OCR + sheets
def check(args: argparse.Namespace) -> int:
    import cv2  # noqa: PLC0415
    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    arm_dir = Path(args.lab) / args.arm
    ocr = RapidOCR()
    result = {}
    for clip in sorted(arm_dir.glob("*.mp4")):
        frames_dir = arm_dir / "frames" / clip.stem
        frames_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", "fps=4,scale=240:-2",
                        str(frames_dir / "f%03d.jpg")], check=True)
        cap = cv2.VideoCapture(str(clip))
        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        hits, k, step = [], 0, fps / 4
        while k * step < n:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * step))
            ok, frame = cap.read()
            k += 1
            if not ok:
                break
            boxes, _ = ocr(frame)
            texts = [t for _b, t, c in (boxes or []) if float(c) >= 0.6 and CJK.search(t)]
            if texts:
                hits.append({"t": round((k - 1) * step / fps, 2), "text": texts})
        result[clip.stem] = {"frames": k, "text_frames": len(hits), "texts": sorted({t for h in hits for t in h["text"]})}
        sheet = arm_dir / f"{clip.stem}_sheet.jpg"
        count = len(list(frames_dir.glob("f*.jpg")))
        cols = 8
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", str(frames_dir / "f*.jpg"),
                        "-vf", f"tile={cols}x{(count + cols - 1) // cols}:padding=2", "-frames:v", "1", str(sheet)],
                       check=True)
        print(clip.stem, result[clip.stem])
    (arm_dir / "ocr.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("extract")
    a.add_argument("--contract", required=True)
    a.add_argument("--shots", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--engine")
    a = sub.add_parser("render")
    a.add_argument("lab")
    a.add_argument("--engine")
    a.add_argument("--shots")
    a.add_argument("--arm")
    a = sub.add_parser("run")
    a.add_argument("lab")
    a.add_argument("--arm", required=True)
    a.add_argument("--engine")
    a.add_argument("--samples", type=int, default=1)
    a.add_argument("--budget", type=float, default=20.0)
    a = sub.add_parser("check")
    a.add_argument("lab")
    a.add_argument("--arm", required=True)
    args = ap.parse_args(argv)
    return {"extract": extract, "render": render, "run": run, "check": check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
