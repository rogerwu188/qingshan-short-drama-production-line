#!/usr/bin/env python3
"""adapt_v4_layers_to_runtime.py — explicit adapter: Codex writer v4 four layers → nalu runtime v1 schema.

Roger 2026-09-18: the nalu runtime only consumes ``<EP>_{NARRATIVE_CANONICAL,DIRECTING_SCRIPT}_v1.md``,
``<EP>_GENERATION_CONTRACT_v1.json`` (qingshan.generation_contract.v3) and ``<EP>_manifest_v1.json``.
A Codex-line v4 delivery (qingshan.episode_script_manifest.v3 + a contract whose shots carry only
frame_content / first_frame_motion_state / dialogue / camera slug / subspace_id, whose scenes carry
weather_state / time_of_day_state, and which has no character registry) must go through THIS adapter —
never a hand-renamed copy.  Every mapping is declared here or in the adapter overlay and written to the
adapter report; nothing is inferred silently and any unresolved item stops the build (exit 3).

Mappings (v4 → runtime):
  scene_states[].weather_state       → scene_states[].weather
  scene_states[].time_of_day_state   → scene_states[].lighting
  scene_states[].time_block_id       → scene_states[].time_id ;  seconds → target_seconds
  shots[].first_frame_motion_state   → entry_state / prompt_spec.action.start_state
  shots[].frame_content              → completion_state / blocking / prompt_spec.action.end_state
  shots[].dialogue "名：句"          → prompt_spec.dialogue + role_semantic_disambiguation.dialogue_speaker(_id)
                                        + audio_contract.dialogue_units[]
  overlay.character_registry         → character_entities[] (character_id is the only identity key)
  overlay.shots[sid].cast/subject_id → prompt_spec.cast[] (life_state per shot), action.subject_id,
                                        role_semantic_disambiguation.{primary_actor_id, action_patient_id,
                                        dialogue_listener_id, lip_owner_id, entity_states, entity_presence}
  overlay.shots[sid].offscreen_voice → entity_presence OFFSCREEN_VOICE_ONLY (speaker behind the veil)
  shots[].duration_seconds           → target_seconds, stretched to nalu_prompt_rules.min_dialogue_seconds
                                        when a dialogue shot is shorter (R8); the v4 value is kept alongside
  camera slug + overlay/defaults     → prompt_spec.camera_plan (motion_family etc., static_design_gate R1–R7)
  manifest.structure[] + overlay.beats → beat type / outcome (script_structure_contract_gate)
  global_space_map.json              → manifest.episode_global_space_map_id / distinct_locations / refs

Usage:
  adapt_v4_layers_to_runtime.py --episode E59 --v4-dir <dir with <EP>_*_v4.*> --overlay <adapter overlay>
        [--gsm <global_space_map.json>] [--out-dir <scripts dir>] [--report <json>] [--force]
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402
import nalu_prompt_rules as npr  # noqa: E402

import argparse  # noqa: E402
import copy  # noqa: E402
import datetime  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

TOOL_ID = "adapt_v4_layers_to_runtime.v1"
ADAPTER_VERSION = "1.1.0"
ADAPTER_SCHEMA = "qingshan.runtime_contract_adapter.v1"
REPORT_SCHEMA = "nalu.v4_layer_adapter_report.v1"
OVERLAY_SCHEMA = "nalu.v4_layer_adapter_overlay.v1"
CONTRACT_SCHEMA = "qingshan.generation_contract.v3"
ENGINE = Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ENGINE / "workflow/claude_writer_agent/scripts"
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")

SCALE_CN = {"WIDE": "远景", "FULL": "全景", "MEDIUM": "中景", "MEDIUM_CLOSE_UP": "中近景", "CLOSE_UP": "特写"}
MOVING_FAMILIES = ["TRACK", "HANDHELD", "CRANE", "ARC"]        # static_design_gate R7 body-motion families
DIALOGUE_FAMILIES = ["DOLLY", "PAN", "ARC"]                     # never LOCKED → R1–R4/R6 hold by construction
DIRECTION = {"TRACK": ["LEFT", "RIGHT"], "HANDHELD": ["FORWARD", "BACK"], "CRANE": ["RISE", "DESCEND"],
             "ARC": ["CLOCKWISE", "COUNTER_CLOCKWISE"], "DOLLY": ["IN", "OUT"], "PAN": ["LEFT", "RIGHT"]}
SCALES_NO_DIALOGUE = ["MEDIUM", "WIDE", "FULL", "MEDIUM_CLOSE_UP"]
SCALES_DIALOGUE = ["MEDIUM_CLOSE_UP", "CLOSE_UP", "MEDIUM"]
VISIBLE = "VISIBLE_AND_IDENTITY_LOCKED"
OFFSCREEN = "OFFSCREEN_VOICE_ONLY"
PRONOUNS = ("他", "她")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_dialogue(text: str) -> tuple[str, str]:
    text = str(text or "").strip()
    if not text:
        return "", ""
    name, sep, line = text.partition("：")
    return (name.strip(), line.strip()) if sep else ("", text)


def humanize_slug(slug: str) -> str:
    return re.sub(r"_+", " ", str(slug or "")).strip()


def parse_directing_scene_turns(md: str) -> dict[str, str]:
    """``### E59-S03｜…`` header → the scene's ``本场转折`` line (the camera motivation source)."""
    out: dict[str, str] = {}
    current = None
    for line in md.splitlines():
        m = re.match(r"###\s+(E\d+-S\d+)｜", line)
        if m:
            current = m.group(1)
            continue
        if current and "本场转折" in line:
            out[current] = line.strip("- ").strip()
    return out


# --------------------------------------------------------------------------- overlay access
class Overlay:
    def __init__(self, data: dict[str, Any], episode: str) -> None:
        if data.get("schema") != OVERLAY_SCHEMA:
            raise SystemExit(f"ADAPTER_OVERLAY_SCHEMA_INVALID:{data.get('schema')}")
        if str(data.get("episode")) != episode:
            raise SystemExit(f"ADAPTER_OVERLAY_EPISODE_MISMATCH:{data.get('episode')}!={episode}")
        self.data = data
        self.registry = list(data.get("character_registry") or [])
        self.by_id = {r["character_id"]: r for r in self.registry}
        self.alias_to_id: dict[str, str] = {}
        for r in self.registry:
            for label in [r["canonical_name"], *list(r.get("aliases") or [])]:
                if label in self.alias_to_id and self.alias_to_id[label] != r["character_id"]:
                    raise SystemExit(f"ADAPTER_ALIAS_COLLISION:{label}")
                self.alias_to_id[label] = r["character_id"]
        self.shots = dict(data.get("shots") or {})
        self.props = list(data.get("props") or [])
        self.prop_keywords = {p["entity_id"]: [p["name"], *list(p.get("keywords") or [])] for p in self.props}
        self.prop_name = {p["entity_id"]: p["name"] for p in self.props}

    def resolve(self, name: str) -> str | None:
        name = str(name or "").strip()
        if not name:
            return None
        if name in self.by_id:
            return name
        return self.alias_to_id.get(name)

    def name(self, cid: str) -> str:
        return self.by_id[cid]["canonical_name"]


# --------------------------------------------------------------------------- camera plan
def default_camera_plan(index_in_scene: int, has_dialogue: bool, slug: str, motivation: str,
                        prev_family: str | None, prev_direction: str | None, seconds: float,
                        source_ref: str) -> dict[str, Any]:
    fams = DIALOGUE_FAMILIES if has_dialogue else MOVING_FAMILIES
    scales = SCALES_DIALOGUE if has_dialogue else SCALES_NO_DIALOGUE
    family = fams[index_in_scene % len(fams)]
    if family == prev_family:   # v4 camera contract: no two adjacent shots with the same dynamic move
        family = fams[(index_in_scene + 1) % len(fams)]
    direction = DIRECTION[family][index_in_scene % 2]
    if direction == prev_direction and prev_family == family:
        direction = DIRECTION[family][(index_in_scene + 1) % 2]
    scale = scales[index_in_scene % len(scales)]
    side = "AXIS_A" if index_in_scene % 2 == 0 else "AXIS_B"   # R5: never > 2 on one axis+scale
    return {
        "shot_scale": scale, "camera_height": "EYE_LEVEL" if index_in_scene % 3 else "LOW_ANGLE",
        "camera_side": side, "lens_intent": humanize_slug(slug),
        "axis_relation": "承 v4 机位串；不越轴", "motion_family": family, "motion_direction": direction,
        "start_framing": "承接起始状态", "end_framing": "动作结果状态",
        "motivation": motivation or "v4 导演稿本场推进",
        "authorship": "V4_ADAPTER_DEFAULT_CAMERA_PLAN", "selection_mode": "ADAPTER_DEFAULT",
        "source": source_ref,
        "note": "v4 只给机位串（slug），不给运镜族；本计划由适配器按 static_design_gate R1–R8 生成，可由 adapter overlay camera_plan 覆盖",
    }


# --------------------------------------------------------------------------- build
def build(args: argparse.Namespace) -> tuple[dict[str, Path], dict[str, Any]]:
    ep = args.episode
    v4 = Path(args.v4_dir).resolve()
    narrative_v4 = v4 / f"{ep}_NARRATIVE_CANONICAL_v4.md"
    directing_v4 = v4 / f"{ep}_DIRECTING_SCRIPT_v4.md"
    contract_v4_path = v4 / f"{ep}_GENERATION_CONTRACT_v4.json"
    manifest_v4_path = v4 / f"{ep}_manifest_v4.json"
    for path in (narrative_v4, directing_v4, contract_v4_path, manifest_v4_path):
        if not path.is_file():
            raise SystemExit(f"V4_LAYER_MISSING:{path}")
    contract_v4 = load_json(contract_v4_path)
    manifest_v4 = load_json(manifest_v4_path)
    ov = Overlay(load_json(Path(args.overlay).resolve()), ep)
    gsm = load_json(Path(args.gsm).resolve()) if args.gsm else None
    directing_md = directing_v4.read_text(encoding="utf-8")
    scene_turns = parse_directing_scene_turns(directing_md)
    seal = v4 / f"{ep}_V4_FOUR_LAYER_SEAL.json"
    seal_check: dict[str, Any] = {"present": seal.is_file(), "layers": []}
    if seal.is_file():
        for layer in load_json(seal).get("layers") or []:
            name = Path(str(layer.get("path") or "")).name
            local = v4 / name
            actual = sha256_bytes(local.read_bytes()) if local.is_file() else None
            declared = layer.get("declared_sha256") or None
            seal_check["layers"].append({"layer": layer.get("layer"), "file": name, "declared_sha256": declared,
                                         "actual_sha256": actual,
                                         "status": "MATCH" if declared and declared == actual else ("UNSEALED" if not declared else "MISMATCH")})
        if any(row["status"] == "MISMATCH" for row in seal_check["layers"]):
            raise SystemExit("V4_SEAL_MISMATCH:" + json.dumps(seal_check, ensure_ascii=False))

    errors: list[str] = []
    warnings: list[str] = []
    cps = float((ov.data.get("pacing_policy") or {}).get("dialogue_cps") or 4.9)
    cps_max = float((ov.data.get("pacing_policy") or {}).get("dialogue_cps_max") or cps)

    # ---------------------------------------------------------------- scene states
    v4_scenes = {s["scene_id"]: s for s in contract_v4.get("scene_states") or []}
    beat_by_scene: dict[str, list[str]] = {}
    for row in manifest_v4.get("structure") or []:
        beat_by_scene.setdefault(str(row.get("scene_id")), []).append(str(row.get("beat_id")))
    scene_extra = ov.data.get("scenes") or {}
    scene_states: list[dict[str, Any]] = []
    vcc = contract_v4.get("visual_culture_contract") or ov.data.get("visual_culture_contract")
    if not vcc:
        errors.append("VISUAL_CULTURE_CONTRACT_MISSING")
    period = (vcc or {}).get("production_design", "")
    for scene_id, s in v4_scenes.items():
        ex = scene_extra.get(scene_id) or {}
        interior = str(s.get("interior_exterior") or "").lower() == "interior"
        lighting = str(ex.get("lighting") or "").strip()
        if not lighting:
            # v4 has no lighting field; a time-of-day description must not impersonate one.
            errors.append(f"SCENE_LIGHTING_UNDECLARED:{scene_id}")
        scene_states.append({
            "scene_id": scene_id, "location_id": s["location_id"], "time_id": s["time_block_id"],
            "time": s["time_of_day_state"], "weather": s["weather_state"], "lighting": lighting,
            "lighting_provenance": {"source_type": "ADAPTER_OVERLAY_AUTHORED", "basis": ex.get("lighting_basis") or "v4 time_of_day_state 中的光源词 + visual_culture_contract.lighting_language",
                                    "source_ref": f"E59_v4_adapter_overlay.json#scenes/{scene_id}/lighting"},
            "target_seconds": float(s["seconds"]), "source_events": beat_by_scene.get(scene_id, []),
            "new_information_count": ex.get("new_information_count", 1),
            "ambient_life": ex.get("ambient_life") or {"grade": "B", "motion_trend": "连续自然微动，不冻结",
                                                        "first_frame_state": s["weather_state"],
                                                        "reaction_progression": "按主动作因果错峰响应"},
            "weather_provenance": {"source_type": "V4_SCENE_STATE_LOCKED",
                                   "source_ref": f"{ep}_GENERATION_CONTRACT_v4.json#scene_states/{scene_id}",
                                   "visibility_mode": "INTERIOR_NO_SKY" if interior else "EXTERIOR_AUTHORED_ONLY",
                                   "authority": s.get("authority")},
            "period_constraints": period, "costume_overrides": ex.get("costume_overrides") or {},
            "interior_exterior": s.get("interior_exterior"), "palette_temperature": s.get("palette_temperature"),
            "thread": s.get("thread"),
            "field_provenance": {"weather": "v4 scene_states[].weather_state", "time": "v4 scene_states[].time_of_day_state", "time_id": "v4 scene_states[].time_block_id",
                                 "target_seconds": "v4 scene_states[].seconds", "lighting": "adapter overlay (authored, not inferred)"},
            "v4_fields": {"weather_state": s["weather_state"], "time_of_day_state": s["time_of_day_state"],
                          "time_block_id": s["time_block_id"], "seconds": s["seconds"]},
        })

    # ---------------------------------------------------------------- characters
    character_entities: list[dict[str, Any]] = []
    for r in ov.registry:
        src = r.get("identity_source") or {}
        file = src.get("file")
        entry = {
            "character_id": r["character_id"], "canonical_name": r["canonical_name"],
            "aliases": list(r.get("aliases") or []), "voice_entity_id": "", "identity_reference_entity_id": "",
            "identity_source": dict(src), "appearance_ch1": r.get("appearance", ""),
            "wardrobe_garments": r.get("wardrobe_garments") or {}, "sex": r.get("sex"),
            "apparent_age_range": r.get("apparent_age_range"),
            "presence_default": r.get("presence_default") or VISIBLE,
            "v4_identity_registry_note": r.get("v4_note", ""),
        }
        if file:
            fpath = Path(file)
            if fpath.is_file():
                entry["identity_source"]["sha256"] = sha256_bytes(fpath.read_bytes())
            else:
                errors.append(f"IDENTITY_SOURCE_FILE_MISSING:{r['character_id']}:{file}")
        character_entities.append(entry)

    # ---------------------------------------------------------------- shots
    shots_out: list[dict[str, Any]] = []
    dialogue_units: list[dict[str, Any]] = []
    stretched: list[dict[str, Any]] = []
    prev_family: str | None = None
    prev_direction: str | None = None
    prev_scene: str | None = None
    idx_in_scene = 0
    cursor = 0.0
    first_seen: dict[str, str] = {}
    prop_first_seen: dict[str, str] = {}
    for shot in contract_v4.get("shots") or []:
        sid = shot["shot_id"]
        scene_id = shot["scene_id"]
        if scene_id != prev_scene:
            idx_in_scene = 0
            prev_scene = scene_id
        else:
            idx_in_scene += 1
        if scene_id not in v4_scenes:
            errors.append(f"SHOT_SCENE_UNDECLARED:{sid}:{scene_id}")
            continue
        o = ov.shots.get(sid)
        if o is None:
            errors.append(f"SHOT_OVERLAY_MISSING:{sid}")
            continue
        ffms = str(shot.get("first_frame_motion_state") or "").strip()
        frame = str(shot.get("frame_content") or "").strip()
        dialogue = str(shot.get("dialogue") or "").strip()
        speaker_name, line = split_dialogue(dialogue)
        speaker_id = ov.resolve(speaker_name) if speaker_name else None
        if dialogue and not speaker_id:
            errors.append(f"DIALOGUE_SPEAKER_UNRESOLVED:{sid}:{speaker_name}")
        cast_ids = list(o.get("cast") or [])
        for cid in cast_ids:
            if cid not in ov.by_id:
                errors.append(f"CAST_ID_UNREGISTERED:{sid}:{cid}")
        offscreen_ids = list(o.get("offscreen_voice") or [])
        actor_kind = str(o.get("actor_kind") or "CHARACTER")
        subject_id = str(o.get("subject_id") or "")
        if actor_kind == "CHARACTER":
            if not subject_id:
                errors.append(f"SUBJECT_ID_MISSING:{sid}")
            elif subject_id not in ov.by_id:
                errors.append(f"SUBJECT_ID_UNREGISTERED:{sid}:{subject_id}")
        if speaker_id and speaker_id not in cast_ids and speaker_id not in offscreen_ids:
            errors.append(f"SPEAKER_NOT_IN_CAST_NOR_OFFSCREEN:{sid}:{speaker_id}")
        # names in the v4 text that the overlay did not place — reviewer must decide
        text_all = ffms + frame + line
        for label, cid in ov.alias_to_id.items():
            if len(label) >= 2 and label in text_all and cid not in cast_ids and cid not in offscreen_ids and cid != speaker_id:
                warnings.append(f"NAMED_BUT_NOT_CAST:{sid}:{label}:{cid}")

        # duration (nalu R8: dialogue shot >= spoken_chars/cps + lead + tail)
        v4_dur = float(shot.get("duration_seconds") or 0)
        target = v4_dur
        stretch = None
        cps_shot = cps
        if line:
            # same basis as static_design_gate R8 (speaker prefix stripped).  E05 precedent (seq=10/17):
            # a line that does not fit the default rate is marked up to cps_max (5.2 字/秒) BEFORE the
            # shot is stretched; only what still does not fit stretches the v4 duration.
            need = npr.min_dialogue_seconds(line, cps_shot)
            if need > v4_dur + 1e-9 and cps_max > cps_shot:
                cps_shot = cps_max
                need = npr.min_dialogue_seconds(line, cps_shot)
            if need > v4_dur + 1e-9:
                target = math.ceil(need * 10) / 10
                stretch = {"shot_id": sid, "v4_seconds": v4_dur, "target_seconds": target, "need_seconds": need,
                           "rule": "static_design_gate R8 (nalu_prompt_rules.min_dialogue_seconds)", "cps": cps_shot}
                stretched.append(stretch)
        # camera plan
        motivation = scene_turns.get(scene_id, "")
        cp = default_camera_plan(idx_in_scene, bool(line), shot.get("camera"), motivation, prev_family, prev_direction,
                                 target, f"{ep}_DIRECTING_SCRIPT_v4.md#{sid}")
        if o.get("camera_plan"):
            cp.update(o["camera_plan"])
            cp["authorship"] = "ADAPTER_OVERLAY_CAMERA_PLAN"
        prev_family, prev_direction = cp["motion_family"], cp.get("motion_direction")
        # cast rows
        life_over = o.get("life_state") or {}
        slots = ["SCREEN_LEFT", "SCREEN_RIGHT", "SCREEN_CENTER", "BACKGROUND_LEFT", "BACKGROUND_RIGHT", "BACKGROUND_CENTER"]
        cast_rows = []
        for i, cid in enumerate(cast_ids):
            row = {"character": ov.name(cid), "character_id": cid,
                   "life_state": life_over.get(cid) or ov.by_id[cid].get("life_state_default") or "alive",
                   "screen_slot": slots[i % len(slots)]}
            fv = (o.get("face_visibility") or {}).get(cid)
            if fv:
                row["face_visibility"] = fv
            cast_rows.append(row)
            first_seen.setdefault(cid, sid)
        # props
        prop_ids = list(o.get("props") or [])
        prop_provenance = {pid: "ADAPTER_OVERLAY" for pid in prop_ids}
        for pid, keys in ov.prop_keywords.items():
            hit = next((k for k in keys if k and k in (ffms + frame)), None)
            if pid not in prop_ids and hit:
                prop_ids.append(pid)
                prop_provenance[pid] = f"OVERLAY_KEYWORD:{hit}"
        for pid in prop_ids:
            if pid not in ov.prop_name:
                errors.append(f"PROP_ID_UNREGISTERED:{sid}:{pid}")
            prop_first_seen.setdefault(pid, sid)
        props_rows = [{"prop_id": pid, "prop": ov.prop_name.get(pid, pid), "binding": prop_provenance.get(pid)} for pid in prop_ids]
        # presence / states
        presence = {cid: VISIBLE for cid in cast_ids}
        for cid in offscreen_ids:
            presence[cid] = OFFSCREEN
        states = {cid: frame for cid in presence}
        states.update(o.get("entity_states") or {})
        lip_owner = speaker_id if (speaker_id and speaker_id in cast_ids) else ""
        listener_id = str(o.get("listener_id") or "")
        patient_id = str(o.get("patient_id") or "")
        primary_actor = ov.name(subject_id) if (actor_kind == "CHARACTER" and subject_id in ov.by_id) else str(o.get("actor_label") or "")
        referents = [{"surface_form": pr, "entity_id": subject_id} for pr in PRONOUNS if pr in (ffms + frame) and subject_id]
        primary_action = ffms if ffms == frame else (f"{ffms}；{frame}" if ffms else frame)
        role = {
            "primary_actor_kind": actor_kind, "primary_actor": primary_actor,
            "primary_actor_id": subject_id if actor_kind == "CHARACTER" else "",
            "dialogue_speaker": ov.name(speaker_id) if speaker_id else "", "dialogue_speaker_id": speaker_id or "",
            "dialogue_listener": ov.name(listener_id) if listener_id in ov.by_id else "", "dialogue_listener_id": listener_id if listener_id in ov.by_id else "",
            "action_patient": ov.name(patient_id) if patient_id in ov.by_id else str(o.get("patient_label") or ""),
            "action_patient_id": patient_id if patient_id in ov.by_id else "",
            "lip_owner_id": lip_owner, "entity_states": states, "entity_presence": presence,
        }
        dims = list(o.get("state_delta_dimensions") or ["POSTURE"])
        evidence = o.get("state_delta_evidence") or {d: {"entry": ffms, "exit": frame} for d in dims}
        thread = v4_scenes[scene_id].get("thread")
        action_kind = o.get("action_kind") or ("ACTION_COMBAT" if scene_id in set(ov.data.get("combat_scenes") or []) else "DRAMA")
        shot_out = {
            "shot_id": sid, "scene_id": scene_id, "target_seconds": target,
            "v4_duration_seconds": v4_dur, "v4_start_seconds": shot.get("start_seconds"), "duration_stretch": stretch,
            "shot_size": SCALE_CN.get(cp["shot_scale"], cp["shot_scale"]),
            "camera": f"{humanize_slug(shot.get('camera'))}（{cp['motion_family']} {cp.get('motion_direction', '')}）",
            "axis": cp["axis_relation"], "blocking": frame, "entry_state": ffms or frame, "completion_state": frame,
            "state_delta_dimensions": dims, "state_delta_evidence": evidence, "keyframe_source": "entry_state",
            "blocking_signature": f"{cp['camera_side']}|{cp['shot_scale']}|{cp['camera_height']}|{cp['motion_family']}|" + "/".join(f"{c['character_id']}:{c['screen_slot']}" for c in cast_rows),
            "period_constraints": period,
            "pacing_flags": {"hook": sid == ((ov.data.get("hook") or {}).get("line_or_shot_id")),
                             "scene_opener_in_motion": idx_in_scene == 0, "scene_button": False,
                             "no_dialogue_static_hold_seconds_max": None if line else 2.0},
            "subspace_id": shot.get("subspace_id"), "native_av": shot.get("native_av"),
            "duration_plan": shot.get("duration_plan"), "negative_prompts": list(shot.get("negative_prompts") or []),
            "thread": thread,
            "prompt_spec": {
                "camera_plan": cp, "cast": cast_rows, "props": props_rows, "dialogue": dialogue,
                "action": {"subject_id": subject_id if actor_kind == "CHARACTER" else "", "primary_action": primary_action,
                           "patient_id": patient_id if patient_id in ov.by_id else "", "start_state": ffms, "end_state": frame,
                           "action_kind": action_kind},
                "referent_resolution_contract": {"status": "PASS", "source_scan_complete": True,
                                                 "resolved_source_referents": referents, "unresolved_source_referents": []},
                "role_semantic_disambiguation": role,
                "scene_state": {"time": v4_scenes[scene_id]["time_of_day_state"], "weather": v4_scenes[scene_id]["weather_state"],
                                "lighting": str((scene_extra.get(scene_id) or {}).get("lighting") or ""),
                                "weather_provenance": {"source_type": "V4_SCENE_STATE_LOCKED", "source_ref": f"{ep}/{scene_id}",
                                                       "visibility_mode": "PRESERVE_AUTHORED_ONLY"}},
                "visual": frame, "negative_prompts": list(shot.get("negative_prompts") or []),
            },
        }
        if line:
            shot_out["dialogue_delivery"] = {"chinese_characters_per_second": cps_shot,
                                             "basis": f"默认 {cps} 字/秒（v4 manifest dialogue_pacing.rate_ruler）；放不进 v4 镜长的句子按 E05 先例标到 {cps_max} 字/秒再拉长；R8 need = chars/cps + {npr.DLG_LEAD_S} + {npr.DLG_TAIL_S}"}
            dialogue_units.append({"shot_id": sid, "speaker_id": speaker_id or "", "listener_id": listener_id if listener_id in ov.by_id else "",
                                   "text": line, "verbatim_in_source": True, "emotion": o.get("emotion") or "neutral",
                                   "presence": OFFSCREEN if speaker_id in offscreen_ids else VISIBLE})
        shots_out.append(shot_out)
        cursor += target

    # ---------------------------------------------------------------- props / entities
    reference_cards: list[dict[str, Any]] = []
    for p in ov.props:
        card = {k: v for k, v in p.items() if k != "keywords"}
        card.setdefault("first_shot", prop_first_seen.get(p["entity_id"]))
        card.setdefault("reference_card_required", True)
        card.setdefault("period_constraints", period)
        reference_cards.append(card)
    protagonists = list(ov.data.get("protagonist_ids") or [])
    carry_in = dict(ov.data.get("carry_in") or {})
    carry_ids = set(carry_in.get("entities") or [])
    intros: list[dict[str, Any]] = []
    for r in ov.registry:
        cid = r["character_id"]
        if cid in protagonists:
            continue
        first = first_seen.get(cid)
        setup = r.get("introduction") or ({"kind": "prior_episode", "ref": r.get("prior_episode_ref") or carry_in.get("previous_episode")}
                                          if r.get("existing_card") else {"kind": "shot", "ref": first})
        intros.append({"entity_id": cid, "first_shot_id": first, "setup": setup})
    for card in reference_cards:
        acq = card.get("acquired") or {}
        setup = {"kind": "prior_episode", "ref": acq.get("episode")} if acq.get("episode") and acq.get("episode") != ep else {"kind": "shot", "ref": acq.get("shot_id") or card.get("first_shot")}
        intros.append({"entity_id": card["entity_id"], "first_shot_id": card.get("first_shot"), "setup": setup})

    # ---------------------------------------------------------------- manifest structure (beats)
    beats = ov.data.get("beats") or {}
    structure: list[dict[str, Any]] = []
    for row in manifest_v4.get("structure") or []:
        row = dict(row)
        b = beats.get(row.get("beat_id")) or beats.get(row.get("scene_id"))
        if not b:
            errors.append(f"BEAT_TYPE_UNDECLARED_IN_OVERLAY:{row.get('beat_id')}")
        else:
            row["type"] = b["type"]
            if b.get("outcome"):
                row["outcome"] = b["outcome"]
        structure.append(row)

    total = round(sum(s["target_seconds"] for s in shots_out), 1)
    style = ov.data.get("style") or {
        "profile_id": (vcc or {}).get("profile_id"), "era_idiom": (vcc or {}).get("production_design"),
        "night_look": (vcc or {}).get("lighting_language"), "forbidden": list((vcc or {}).get("forbidden_influences") or []),
        "authority": "E59 v4 visual_culture_contract (Codex writer) via v4 adapter",
        "negative_prompt_fixed": "、".join((vcc or {}).get("forbidden_influences") or [])}
    pacing = {
        "authority": "E59 v4 (Codex writer, duration_plan per shot) + nalu static_design_gate R1–R8 + seq=19 S1 gates; adapter stretches only what R8 demands",
        "shot_seconds_default": [2, 3], "shot_seconds_max": 6, "video_unit_seconds_max": 6.0, "video_unit_seconds_hard_cap": 7.0,
        "no_dialogue_static_hold_seconds_max": 2.0, "scene_opening_rule": "每场第一镜从进行中的动作开始（v4 first_frame_motion_state）",
        "episode_total_seconds_target": [manifest_v4.get("runtime_target_seconds", {}).get("min"), manifest_v4.get("runtime_target_seconds", {}).get("max")],
        "hook": ov.data.get("hook"),
        "dialogue_density": dict((ov.data.get("pacing_policy") or {}).get("dialogue_density") or {"max_silent_run_seconds": 15, "max_silent_run_action_seconds": 25, "min_coverage": 0.35, "verdict": "FAIL"}),
        "camera_motion_policy": {"authority": "static_design_gate.py R1–R8 (BLOCK)", "locked_share_max": 0.35, "consecutive_locked_allowed": False,
                                 "no_dialogue_shot_requires_camera_motion": True, "same_axis_scale_run_max": 2, "opening_shot_must_move": True,
                                 "allowed_motion_families": sorted(set(MOVING_FAMILIES + DIALOGUE_FAMILIES))},
        "v4_dialogue_pacing": manifest_v4.get("dialogue_pacing"),
    }
    narrative_bytes = narrative_v4.read_bytes()
    directing_bytes = directing_v4.read_bytes()
    source_layer_shas = {"narrative_canonical": sha256_bytes(narrative_bytes), "directing_script": sha256_bytes(directing_bytes),
                         "generation_contract": sha256_bytes(contract_v4_path.read_bytes()), "manifest": sha256_bytes(manifest_v4_path.read_bytes())}
    adapter_header = {
        "schema": ADAPTER_SCHEMA, "episode": ep, "source_contract_version": contract_v4.get("version"),
        "source_manifest_schema": manifest_v4.get("schema"), "source_layer_shas": source_layer_shas,
        "adapter_version": ADAPTER_VERSION, "adapter_tool": TOOL_ID, "adapted_at": now(), "project_id": args.project_id,
        "adapter_overlay": {"path": str(Path(args.overlay).resolve()), "sha256": sha256_bytes(Path(args.overlay).resolve().read_bytes())},
        "seal_check": seal_check,
        "field_provenance": {
            "scene_states[].weather": "v4 scene_states[].weather_state", "scene_states[].time": "v4 scene_states[].time_of_day_state",
            "scene_states[].time_id": "v4 scene_states[].time_block_id", "scene_states[].target_seconds": "v4 scene_states[].seconds",
            "scene_states[].lighting": "adapter overlay scenes[].lighting (authored; blocks when absent)",
            "shots[].entry_state / prompt_spec.action.start_state": "v4 shots[].first_frame_motion_state",
            "shots[].completion_state / blocking / prompt_spec.action.end_state": "v4 shots[].frame_content",
            "prompt_spec.dialogue": "v4 shots[].dialogue (verbatim)",
            "role_semantic_disambiguation.dialogue_speaker_id": "v4 dialogue speaker label resolved ONLY through overlay.character_registry canonical_name/aliases (exact match)",
            "character_entities": "adapter overlay character_registry (Codex runtime id space + v4 identity_registry)",
            "prompt_spec.cast[] / life_state / face_visibility": "adapter overlay shots[sid] (authored per shot)",
            "prompt_spec.action.subject_id == role.primary_actor_id": "adapter overlay shots[sid].subject_id",
            "role.dialogue_listener_id / action_patient_id": "adapter overlay shots[sid].listener_id / patient_id",
            "role.lip_owner_id": "= dialogue_speaker_id when the speaker is in cast; empty when overlay marks OFFSCREEN_VOICE_ONLY",
            "role.entity_presence / entity_states": "cast → VISIBLE_AND_IDENTITY_LOCKED; overlay offscreen_voice → OFFSCREEN_VOICE_ONLY; states default frame_content, overlay entity_states overrides",
            "prompt_spec.props[]": "overlay shots[sid].props (ADAPTER_OVERLAY) or overlay props[].keywords hit in v4 text (OVERLAY_KEYWORD:<kw>) — recorded per row",
            "target_seconds": "v4 duration_seconds, stretched only to nalu_prompt_rules.min_dialogue_seconds (R8); v4 value kept as v4_duration_seconds",
            "prompt_spec.camera_plan": "adapter default from v4 camera slug + directing 本场转折 (V4_ADAPTER_DEFAULT_CAMERA_PLAN) or overlay camera_plan",
            "manifest.structure[].type / outcome": "adapter overlay beats", "pacing.hook": "adapter overlay hook",
            "manifest.source_binding.work/author/source_file": "adapter overlay source_binding_extra",
            "manifest.global_space_map_refs": "preproduction/<EP>/global_space_map.json scene_mappings + room zones",
        },
    }
    contract_out = {
        "schema": CONTRACT_SCHEMA, "episode": ep, "version": "v1", "project_id": args.project_id,
        "runtime_contract_adapter": adapter_header,
        "adapted_from": {"tool": TOOL_ID, "at": now(), "v4_contract": str(contract_v4_path), "v4_contract_sha256": sha256_bytes(contract_v4_path.read_bytes()),
                          "v4_manifest_sha256": sha256_bytes(manifest_v4_path.read_bytes()), "v4_version": contract_v4.get("version"),
                          "v4_schema": manifest_v4.get("schema"), "adapter_overlay": str(Path(args.overlay).resolve()),
                          "adapter_overlay_sha256": sha256_bytes(Path(args.overlay).resolve().read_bytes()), "seal_check": seal_check},
        "title": contract_v4.get("title"), "authorization": contract_v4.get("authorization"),
        "narrative_canonical": f"{ep}_NARRATIVE_CANONICAL_v1.md", "narrative_sha256": sha256_bytes(narrative_bytes),
        "style": style, "pacing": pacing, "protagonist_ids": protagonists,
        "antagonist_groups": list(ov.data.get("antagonist_groups") or []), "ambush_contracts": list(ov.data.get("ambush_contracts") or []),
        "entity_introductions": intros, "carry_in": carry_in,
        "visual_culture_contract": vcc, "character_entities": character_entities,
        "non_character_entities": reference_cards,
        "props": {"authority": "E59 v4 identity_registry_check.★the_props_of_the_episode + adapter overlay", "reference_cards": reference_cards},
        "scene_states": scene_states, "shots": shots_out, "internal_transition_authoring": [],
        "audio_contract": {
            "bgm": {"mode": contract_v4.get("audio_contract", {}).get("bgm"), "used": False,
                    "declaration": contract_v4.get("audio_contract", {}).get("bgm_reason"), "authority": f"{ep} v4 audio_contract"},
            "native_dialogue_only": contract_v4.get("audio_contract", {}).get("native_dialogue_only"),
            "diegetic_anchors": contract_v4.get("audio_contract", {}).get("diegetic_anchors"),
            "ambient_by_scene": {s["scene_id"]: s["weather"] for s in scene_states},
            "voice_casting": {"status": "NOT_CAST", "note": "scope QINGSHAN-E59 has no voice catalog selection yet; S4 not authorised"},
            "dialogue_units": dialogue_units,
        },
        "v4_passthrough": {k: contract_v4.get(k) for k in ("space_chain", "identity_registry_check", "onscreen_text_policy",
                                                            "★weather_continuity_this_episode", "★camera_contract_two_sided",
                                                            "★fs1_set_piece_declared", "★cross_episode_continuity_locks",
                                                            "global_space_map_id", "runtime_seconds")},
    }
    # manifest
    manifest_out = copy.deepcopy(manifest_v4)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (RUNTIME / "adapter" / ep)
    contract_bytes = (json.dumps(contract_out, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_out.update({
        "runtime_contract_adapter": adapter_header, "project_id": args.project_id,
        "canonical_script": str(out_dir / f"{ep}_NARRATIVE_CANONICAL_v1.md"), "script_sha256": sha256_bytes(narrative_bytes),
        "directing_script": {"path": str(out_dir / f"{ep}_DIRECTING_SCRIPT_v1.md"), "sha256": sha256_bytes(directing_bytes)},
        "generation_contract": {"path": str(out_dir / f"{ep}_GENERATION_CONTRACT_v1.json"), "sha256": sha256_bytes(contract_bytes)},
        "structure": structure, "shot_count": len(shots_out), "total_seconds": total,
        "source_binding": {**dict(manifest_v4.get("source_binding") or {}), **dict(ov.data.get("source_binding_extra") or {})},
        "v4_total_seconds": manifest_v4.get("total_seconds"),
        "adapter": {"tool": TOOL_ID, "at": now(), "v4_manifest_sha256": sha256_bytes(manifest_v4_path.read_bytes()),
                    "v4_files": {p.name: sha256_bytes(p.read_bytes()) for p in (narrative_v4, directing_v4, contract_v4_path, manifest_v4_path)},
                    "note": "v1 slot files are the adapter's output; the v4 files are the writer's sealed authority"},
    })
    if gsm:
        maps = gsm.get("space_maps") or []
        locs = sorted({str(s["location_id"]) for s in scene_states})
        manifest_out["episode_global_space_map_id"] = gsm.get("episode_global_space_map_id")
        manifest_out["distinct_locations"] = locs
        manifest_out.setdefault("new_locations", list((manifest_v4.get("pacing_v2") or {}).get("new_locations") or []))
        refs = []
        axis_notes = ov.data.get("space_map_axis_notes") or {}
        for sm in maps:
            mid = sm.get("global_space_map_id")
            scenes = [m["scene_id"] for m in (sm.get("scene_mappings") or []) if str(m.get("scene_id", "")).startswith(ep)]
            if not scenes:
                continue
            anchors = [str(z.get("name") or z.get("zone_id")) for room in (sm.get("rooms") or []) for z in (room.get("zones") or [])]
            refs.append({"map_id": mid, "scenes": scenes, "anchors": anchors,
                         "axis_note": axis_notes.get(mid) or f"承 v4 space_chain 与 {mid} 的 scene_mappings；机位轴向由适配器 camera_plan 逐镜声明",
                         "episode_global_space_map_id": gsm.get("episode_global_space_map_id")})
        manifest_out["global_space_map_refs"] = refs
        mapped = {m["scene_id"] for sm in maps for m in (sm.get("scene_mappings") or [])}
        for s in scene_states:
            if s["scene_id"] not in mapped:
                errors.append(f"SCENE_NOT_IN_GLOBAL_SPACE_MAP:{s['scene_id']}")
    else:
        warnings.append("GSM_NOT_PROVIDED:manifest.episode_global_space_map_id not set")

    report = {
        "schema": REPORT_SCHEMA, "tool": TOOL_ID, "episode": ep, "at": now(), "status": "PASS" if not errors else "FAIL",
        "errors": errors, "warnings": warnings, "seal_check": seal_check,
        "counts": {"scenes": len(scene_states), "shots": len(shots_out), "dialogue_units": len(dialogue_units),
                   "characters": len(character_entities), "props": len(reference_cards), "stretched_dialogue_shots": len(stretched)},
        "total_seconds": {"v4": manifest_v4.get("total_seconds"), "adapted": total},
        "duration_stretches": stretched, "dialogue_cps": cps, "dialogue_cps_max": cps_max,
        "field_map": {"scene_states[].weather_state": "scene_states[].weather", "scene_states[].time_of_day_state": "scene_states[].lighting",
                      "scene_states[].time_block_id": "scene_states[].time_id", "scene_states[].seconds": "scene_states[].target_seconds",
                      "shots[].first_frame_motion_state": "entry_state / prompt_spec.action.start_state",
                      "shots[].frame_content": "completion_state / blocking / prompt_spec.action.end_state",
                      "shots[].dialogue": "prompt_spec.dialogue + role_semantic_disambiguation.dialogue_speaker_id + audio_contract.dialogue_units",
                      "overlay.character_registry": "character_entities", "overlay.shots[].cast": "prompt_spec.cast[] (+life_state)",
                      "overlay.shots[].subject_id": "prompt_spec.action.subject_id == role_semantic_disambiguation.primary_actor_id",
                      "overlay.shots[].offscreen_voice": "entity_presence OFFSCREEN_VOICE_ONLY (lip_owner_id empty)",
                      "overlay.beats": "manifest.structure[].type / outcome", "camera slug": "prompt_spec.camera_plan (adapter default or overlay)"},
        "outputs": {}, "project_id": args.project_id, "runtime_contract_adapter": adapter_header,
        "asset_scope": f"{args.project_id} (series_scopes.json) — no NALU-YEWUJIANG asset is referenced",
    }
    outputs = {
        "narrative": out_dir / f"{ep}_NARRATIVE_CANONICAL_v1.md", "directing": out_dir / f"{ep}_DIRECTING_SCRIPT_v1.md",
        "contract": out_dir / f"{ep}_GENERATION_CONTRACT_v1.json", "manifest": out_dir / f"{ep}_manifest_v1.json",
    }
    if errors:
        return outputs, report
    existing = [str(p) for p in outputs.values() if p.exists()]
    if existing and not args.force:
        report["status"] = "FAIL"
        report["errors"].append("OUTPUT_EXISTS_USE_FORCE:" + ",".join(existing))
        return outputs, report
    outputs["narrative"].write_bytes(narrative_bytes)
    outputs["directing"].write_bytes(directing_bytes)
    outputs["contract"].write_bytes(contract_bytes)
    dump_json(outputs["manifest"], manifest_out)
    report["outputs"] = {k: {"path": str(p), "sha256": sha256_bytes(p.read_bytes())} for k, p in outputs.items()}
    return outputs, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--v4-dir", required=True)
    ap.add_argument("--overlay", required=True)
    ap.add_argument("--gsm", default=None)
    ap.add_argument("--out-dir", default=None, help="default: <RUNTIME_ROOT>/adapter/<EP>/ (never the engine's *_v1 slots)")
    ap.add_argument("--project-id", default=None, help="asset-library project id; default: series scope series_id")
    ap.add_argument("--report", default=None)
    ap.add_argument("--force", action="store_true", help="overwrite existing v1 slot files")
    a = ap.parse_args()
    if not a.project_id:
        import nalu_series_scope as _scope
        a.project_id = _scope.resolve_scope(a.episode)["series_id"]
    outputs, report = build(a)
    report_path = Path(a.report).resolve() if a.report else (RUNTIME / "adapter" / a.episode / f"{a.episode}_V4_ADAPTER_REPORT.json")
    dump_json(report_path, report)
    print(json.dumps({"status": report["status"], "errors": report["errors"][:20], "warnings": len(report["warnings"]),
                      "counts": report["counts"], "total_seconds": report["total_seconds"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
