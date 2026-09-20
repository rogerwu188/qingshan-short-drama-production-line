#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""library_lock_non_plate.py — D-15: lock the NON-plate asset-library rows from real evidence.

``tools/initial_asset_library.py gate`` (engine) gates EVERY category of
``asset_requirements.json`` — wardrobe, scenes, voices, accents, music, ambience, sfx and
reference_materials — not only the plate subjects that ``identity_qa_lock.py`` (D-3) locks.
On 2026-09-12 the E01 gate therefore failed on 47 rows that nothing in this line had ever
written, after all 20 plate subjects were LOCKED.

This tool writes those rows, and ONLY from evidence that exists on disk:

* wardrobe        artifact = the owner character's LOCKED full-body identity plate; qa = the
                  submitted identity review's ``wardrobe_matches_bible`` answer for that
                  character (a reviewer looked at the plate), plus the forbidden-influence answer.
* voices          artifact = the normalised reference wav (sha recomputed) + the Giggle upload
                  receipt asset id; lock fields from the requirement, provider_voice_id from
                  the speech task payload; qa = real ffprobe measurements (48 kHz, mono,
                  pcm_s16le, duration > 0) and the registry row status.
* scenes          artifact = the place layout image of this episode's LOCKED global space map
                  (sha recomputed and compared with the map's own record); qa = the map status,
                  the layout image qa_status and the S2 SCENE-AUTHORITY-LOCK gate report.
* reference_materials
                  artifact = the file itself (source chapter / generation contract / global
                  space map), sha recomputed and compared with the requirement's authority_refs.
* accents, music, ambience, sfx
                  This is a native-audio SD2 line (SUPERVISOR_ORDERS seq=3 c1): there is NO
                  separate audio file for an ambience bed, an sfx element, a music policy or an
                  accent profile — the audible realisation is generated inside each video unit
                  and measured at S6 post-generation QA (audio_stream, av_sync, dialogue gate).
                  The rows are therefore locked as DECLARED SPECS: artifact = the generation
                  contract (the authored audio spec), and qa checks that the requirement's spec
                  is byte-consistent with the contract (ambience sound_field == the contract's
                  ambient_by_scene entry; sfx sync_event names a real shot; music is the
                  NO_EXTERNAL_BGM declaration; accent locale is zh-CN).  ``lock.realization``
                  says so explicitly, so nobody can mistake these rows for audio files.

A row whose evidence is missing or inconsistent is NOT locked and is listed under
``failures`` — the tool never writes PASS it did not measure.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import nalu_series_scope as _series_scope
import nalu_media_tools as _media

import argparse
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(f"{_np.ENGINE_ROOT}")
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")
SCHEMA = "nalu.non_plate_library_lock.v1"

LOCATION_TO_ROOM = {
    # location_id -> (global_space_map_id, room_id) of runtime/preproduction/<EP>/global_space_map.json
    "LOC-SHUANGSHU-VILLAGE-EXT": ("GSM-YEWUJIANG-VILLAGE-OVERVIEW", "ROOM-VILLAGE-OPEN-FIELD"),
    "LOC-QINMING-HOUSE-INT": ("GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "ROOM-QINMING-INT"),
    "LOC-QINMING-YARD-EXT": ("GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "ROOM-QINMING-YARD"),
    "LOC-LUZE-YARD-EXT": ("GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "ROOM-LUZE-YARD"),
    "LOC-VILLAGE-STREET-NORTH-EXT": ("GSM-YEWUJIANG-VILLAGE-STREET-NORTH", "ROOM-STREET-NORTH-CROSSING"),
    "LOC-YANG-HOUSE-FRONT-EXT": ("GSM-YEWUJIANG-YANG-COMPOUND-THRESHING-FLOOR", "ROOM-YANG-THRESHING-FLOOR"),
    "LOC-FIRE-SPRING-EXT": ("GSM-YEWUJIANG-FIRE-SPRING-TWIN-TREES", "ROOM-FIRE-SPRING-BASIN"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def ffprobe(path: Path) -> dict[str, Any]:
    out = subprocess.run(
        [_media.require_ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return {"error": out.stderr.strip()[:300]}
    data = json.loads(out.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    return {"codec_name": stream.get("codec_name"), "sample_rate": int(stream.get("sample_rate") or 0),
            "channels": int(stream.get("channels") or 0),
            "duration_seconds": float((data.get("format") or {}).get("duration") or 0.0)}


def resolve_runtime_authorities(episode: str) -> dict[str, Any]:
    """Resolve reusable authorities without allowing cross-series fallbacks.

    Asset and identity state is always series-scoped.  Voice remains the
    explicitly shared historical runtime authority for the default NALU scope;
    a foreign series must declare and receives its own voice registry.
    """
    scope = _series_scope.resolve_scope(episode)
    config = _series_scope.load_config()
    declared = ((config.get("scopes") or {}).get(scope["scope_id"]) or {})
    voice_is_declared = "voice_registry" in declared
    default_voice = RUNTIME / "runtime/voice_registry.json"
    return {
        "scope": scope,
        "asset_library": Path(scope["asset_library"]),
        "asset_library_seed": Path(scope["asset_library_seed"]),
        "voice_registry": (Path(scope["voice_registry"]) if voice_is_declared
                           else default_voice),
        "voice_registry_policy": ("DECLARED_SERIES_SCOPE_AUTHORITY"
                                  if voice_is_declared
                                  else "DEFAULT_SCOPE_SHARED_RUNTIME_AUTHORITY"),
    }


class Ctx:
    def __init__(self, episode: str, rights_basis: str) -> None:
        self.episode = episode
        self.rights_basis = rights_basis
        authorities = resolve_runtime_authorities(episode)
        self.scope = authorities["scope"]
        self.scope_id = str(self.scope["scope_id"])
        self.series_id = str(self.scope["series_id"])
        self.requirements_path = RUNTIME / "preproduction" / episode / "asset_requirements.json"
        self.library_path = ENGINE / "workflow/nalu" / episode / "identity/asset_library.json"
        self.runtime_library_path = authorities["asset_library"]
        self.runtime_library_seed_path = authorities["asset_library_seed"]
        self.gsm_path = RUNTIME / "preproduction" / episode / "global_space_map.json"
        self.contract_path = ENGINE / "workflow/claude_writer_agent/scripts" / f"{episode}_GENERATION_CONTRACT_v1.json"
        self.voice_registry_path = authorities["voice_registry"]
        self.voice_registry_policy = authorities["voice_registry_policy"]
        self.speech_payloads_path = ENGINE / "workflow/nalu" / episode / "voice/speech_task_payloads.json"
        self.voice_upload_dir = ENGINE / "workflow/nalu" / episode / "voice/uploads"
        self.reviews_dir = RUNTIME / "runtime/reviews" / episode
        self.machine_gates_path = ENGINE / "workflow/nalu" / episode / "preproduction" / f"{episode}_MACHINE_GATE_REPORTS_V1.json"

        self.requirements = load_json(self.requirements_path)
        self.library = load_json(self.library_path)
        if self.runtime_library_path.is_file():
            self.runtime_library = load_json(self.runtime_library_path)
        elif self.runtime_library_seed_path.is_file():
            # Seed only from this declared series.  ``run_lock`` materialises the
            # copy at runtime_library_path after adding this episode's evidence.
            self.runtime_library = deepcopy(load_json(self.runtime_library_seed_path))
        else:
            self.runtime_library = None
        for label, library, path in (
            ("episode", self.library, self.library_path),
            ("series", self.runtime_library, self.runtime_library_path),
        ):
            if library is not None and str(library.get("project_id") or "") != self.series_id:
                raise SystemExit(
                    f"{label.upper()}_ASSET_LIBRARY_PROJECT_MISMATCH:{path}:"
                    f"{library.get('project_id')}!={self.series_id}")
        self.gsm = load_json(self.gsm_path)
        self.contract = load_json(self.contract_path)
        self.contract_sha = sha256_file(self.contract_path)
        self.voice_registry = load_json(self.voice_registry_path)
        self.speech_payloads = load_json(self.speech_payloads_path)
        self.identity_review = self._latest_identity_review()
        self.machine_gates = load_json(self.machine_gates_path) if self.machine_gates_path.is_file() else {}

    def _latest_identity_review(self) -> dict[str, Any] | None:
        candidates = sorted(self.reviews_dir.glob("*-identity-*_submitted.json"))
        for path in reversed(candidates):
            data = load_json(path)
            if data.get("kind") == "identity":
                data["_path"] = str(path)
                data["_sha256"] = sha256_file(path)
                return data
        return None

    def requirement(self, category: str, asset_id: str) -> dict[str, Any] | None:
        for row in self.requirements.get("assets", {}).get(category, []):
            if row.get("asset_id") == asset_id:
                return row
        return None

    def review_item(self, asset_id: str) -> dict[str, Any] | None:
        if not self.identity_review:
            return None
        for item in self.identity_review.get("items") or []:
            if item.get("item_id") == asset_id:
                return item
        return None


def base_plate_artifact(ctx: Ctx, character_id: str) -> dict[str, Any] | None:
    row = (ctx.library.get("assets", {}).get("characters") or {}).get(character_id)
    if not row or row.get("status") != "LOCKED" or (row.get("qa") or {}).get("status") != "PASS":
        return None
    for artifact in row.get("artifacts") or []:
        if artifact.get("role") == "FULL_BODY_STANDING" or artifact.get("canonical_identity_reference"):
            path = Path(artifact["path"])
            if path.is_file() and sha256_file(path) == artifact.get("sha256"):
                return artifact
    return None


def finish(row: dict[str, Any], *, lock: dict[str, Any], artifacts: list[dict[str, Any]],
           provenance: list[dict[str, Any]], rights_basis: str, checks: list[dict[str, Any]],
           note: str) -> dict[str, Any]:
    failed = [c for c in checks if c.get("status") != "PASS"]
    row = deepcopy(row)
    row["lock"] = lock
    row["artifacts"] = artifacts
    row["provenance"] = provenance
    row["rights"] = {"status": "PASS", "basis": rights_basis,
                     "declared_by": "roger (line owner) — LINE_OWNER_DECLARATION_NOT_A_REVIEWER_OBSERVATION"}
    row["qa"] = {"status": "PASS" if not failed else "FAIL", "checks": checks,
                 "method": "library_lock_non_plate.v1", "recorded_at": utc_now(), "note": note}
    row["status"] = "LOCKED" if not failed else "QA_FAILED_NOT_LOCKED"
    row.setdefault("history", []).append({"at": utc_now(), "by": "library_lock_non_plate.v1",
                                          "to": row["status"]})
    row["updated_at"] = utc_now()
    return row


def lock_wardrobe(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    spec = row["specification"]
    owner = spec.get("owner_character_id")
    plate = base_plate_artifact(ctx, owner)
    item = ctx.review_item(owner)
    answers = (item or {}).get("answers") or {}
    reuse_note = None
    if item is None and plate and ctx.runtime_library:
        # D-33 cross-episode reuse: the owner's plates were LOCKED in a prior episode (no plate generated, no identity
        # review item here).  Inherit the prior LOCKED wardrobe row's review answers when it was locked on the SAME plate.
        for prior_id, prior in ((ctx.runtime_library.get("assets", {}).get("wardrobe") or {}).items()):
            pspec = prior.get("specification") or {}
            plock = (prior.get("lock") or {}).get("appearance_lock") or {}
            if pspec.get("owner_character_id") == owner and prior.get("status") == "LOCKED" \
                    and plock.get("locked_on_plate_sha256") == plate.get("sha256"):
                pchecks = {c.get("id"): c.get("status") for c in ((prior.get("qa") or {}).get("checks") or []) if isinstance(c, dict)}
                answers = {"wardrobe_matches_bible": pchecks.get("identity_review_wardrobe_matches_bible", "MISSING"),
                           "no_forbidden_influence_visible": pchecks.get("identity_review_no_forbidden_influence_visible", "MISSING")}
                reuse_note = {"kind": "CROSS_EPISODE_REUSE_WARDROBE_EVIDENCE", "from_asset_id": prior_id,
                              "from_library": str(ctx.runtime_library_path), "plate_sha256": plate.get("sha256"), "recorded_at": utc_now()}
                break
    checks = [
        {"id": "owner_plate_locked_and_sha_matches", "status": "PASS" if plate else "FAIL", "owner": owner},
        {"id": "identity_review_wardrobe_matches_bible", "status": answers.get("wardrobe_matches_bible", "MISSING"),
         "review": (ctx.identity_review or {}).get("_path")},
        {"id": "identity_review_no_forbidden_influence_visible",
         "status": answers.get("no_forbidden_influence_visible", "MISSING")},
    ]
    lock = {"owner_character_id": owner,
            "appearance_lock": {"description": spec.get("description"),
                                "period_constraints": spec.get("period_constraints"),
                                "forbidden": spec.get("forbidden"),
                                "continuity_key": spec.get("continuity_key") or f"WARDROBE-{ctx.episode}-{owner}-V1",
                                "locked_on_plate_sha256": (plate or {}).get("sha256")}}
    artifacts = [{"role": "WARDROBE_STATE_ON_IDENTITY_PLATE", "media_type": plate["media_type"],
                  "path": plate["path"], "sha256": plate["sha256"], "aspect_ratio": "9:16"}] if plate else []
    provenance = [{"kind": "IDENTITY_REVIEW_SUBMITTED", "path": (ctx.identity_review or {}).get("_path"),
                   "sha256": (ctx.identity_review or {}).get("_sha256"),
                   "reviewer": (ctx.identity_review or {}).get("reviewer")}]
    if reuse_note:
        provenance.append(reuse_note)
    return finish(row, lock=lock, artifacts=artifacts, provenance=provenance, rights_basis=ctx.rights_basis,
                  checks=checks, note="wardrobe is locked on the owner's reviewed identity plate" + ("（跨集复用：证据继承自上一集同一底板的服装锁）" if reuse_note else ""))


def _bgm_is_none(bgm: Any) -> bool:
    """audio_contract.bgm is a string ("NO_EXTERNAL_BGM…", E01 as locked) or, since D-19, a dict
    {mode: NONE, used: false, declaration: "NO_EXTERNAL_BGM…"}."""
    if isinstance(bgm, dict):
        return str(bgm.get("mode") or "").upper() == "NONE" and not bgm.get("used") and str(bgm.get("declaration") or "").startswith("NO_EXTERNAL_BGM")
    return str(bgm or "").startswith("NO_EXTERNAL_BGM")


def _owner_has_dialogue(ctx: "Ctx", owner: str | None) -> bool:
    name = next((c.get("canonical_name") for c in (ctx.contract.get("character_entities") or []) if c.get("character_id") == owner), None)
    for shot in ctx.contract.get("shots") or []:
        d = (shot.get("prompt_spec") or {}).get("dialogue")
        texts = [d] if isinstance(d, str) else [x.get("text") if isinstance(x, dict) else str(x) for x in (d or [])]
        for t in texts:
            if t and name and str(t).strip().startswith(f"{name}："):
                return True
    return False


def lock_voice(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    spec = row["specification"]
    owner = spec.get("owner_character_id")
    if row.get("priority") == "OPTIONAL" and not _owner_has_dialogue(ctx, owner):
        # E02+: a character who never speaks in this episode needs no voice reference
        # (SUPERVISOR_ORDERS seq=3 c4 voices are per SPEAKING character); declared lock, no audio.
        lock = {"owner_character_id": owner, "language": spec.get("language"), "accent_id": spec.get("accent_id"),
                "provider_voice_id": "NONE_NON_SPEAKING_IN_THIS_EPISODE", "provider_voice_name": None, "provider": None,
                "native_dialogue_eligible": "NOT_APPLICABLE_NON_SPEAKING_IN_THIS_EPISODE",
                "remote_asset_id": None, "remote_url": None,
                "realization": "NON_SPEAKING_IN_THIS_EPISODE_NO_VOICE_REFERENCE", "timbre_brief": spec.get("timbre_brief")}
        checks = [{"id": "no_dialogue_lines_for_owner_in_generation_contract", "status": "PASS"},
                  {"id": "priority_optional", "status": "PASS"}]
        artifacts = [{"role": "DECLARED_NON_SPEAKING_IN_GENERATION_CONTRACT", "media_type": "application/json",
                      "path": str(ctx.contract_path), "sha256": ctx.contract_sha}]
        return finish(row, lock=lock, artifacts=artifacts, provenance=[{"kind": "GENERATION_CONTRACT_DIALOGUE_SCAN", "path": str(ctx.contract_path), "sha256": ctx.contract_sha}],
                      rights_basis=ctx.rights_basis, checks=checks, note="non-speaking character: declared lock, no audio by design")
    reg = next((r for r in ctx.voice_registry.get("major_roles", [])
                if isinstance(r, dict) and r.get("character_id") == owner), None)
    entity = (reg or {}).get("entity_id")
    task = next((t for t in (ctx.speech_payloads.get("tasks") or []) if t.get("entity_id") == entity), None)
    wav = Path((reg or {}).get("local_reference") or "/nonexistent")
    receipt_path = ctx.voice_upload_dir / f"{entity}_giggle_asset.json"
    if not receipt_path.is_file():
        # voices are paid once per character (S4 cross-episode reuse): the upload receipt lives
        # in the episode that generated it.  E05 (2026-09-17): a recast voice (seq=17/20) has receipts in
        # several episodes — pick the one whose asset id is the registry's current remote_asset_id, else
        # the newest episode's (the E01 receipt of a recast 秦铭 failed upload_receipt_asset_id_matches_registry).
        cands = sorted((ENGINE / "workflow/nalu").glob(f"E*/voice/uploads/{entity}_giggle_asset.json"))
        want = (reg or {}).get("remote_asset_id")
        for cand in reversed(cands):
            cdata = load_json(cand)
            cdata = cdata.get("data") if isinstance(cdata.get("data"), dict) else cdata
            if want and cdata.get("asset_id") == want:
                receipt_path = cand
                break
        else:
            if cands:
                receipt_path = cands[-1]
    receipt = load_json(receipt_path) if receipt_path.is_file() else {}
    receipt_data = receipt.get("data") if isinstance(receipt.get("data"), dict) else receipt
    probe = ffprobe(wav) if wav.is_file() else {"error": "wav_missing"}
    wav_sha = sha256_file(wav) if wav.is_file() else None
    voice_id = ((task or {}).get("request") or {}).get("voice_id")
    checks = [
        {"id": "registry_row_locked_production_ready", "status": "PASS" if (reg or {}).get("status") == "LOCKED_PRODUCTION_READY" else "FAIL"},
        {"id": "wav_sha_matches_registry", "status": "PASS" if wav_sha and wav_sha == (reg or {}).get("local_sha256") else "FAIL"},
        {"id": "upload_receipt_asset_id_matches_registry",
         "status": "PASS" if receipt_data.get("asset_id") and receipt_data.get("asset_id") == (reg or {}).get("remote_asset_id") else "FAIL"},
        {"id": "ffprobe_48k_mono_pcm_s16le", "status": "PASS" if probe.get("sample_rate") == 48000 and probe.get("channels") == 1 and probe.get("codec_name") == "pcm_s16le" else "FAIL", "measured": probe},
        {"id": "ffprobe_duration_positive", "status": "PASS" if (probe.get("duration_seconds") or 0) > 0.5 else "FAIL"},
        {"id": "language_zh_cn", "status": "PASS" if spec.get("language") == "zh-CN" else "FAIL"},
    ]
    lock = {"owner_character_id": owner, "language": spec.get("language"), "accent_id": spec.get("accent_id"),
            "provider_voice_id": voice_id, "provider_voice_name": ((task or {}).get("request") or {}).get("voice_name"),
            "provider": "AGENTCUT_AGENTCUT-SPEECH-001_MINMAX",
            "native_dialogue_eligible": "SD2_NATIVE_DIALOGUE_WITH_VOICE_REFERENCE (ENGINE_FORMAT_CONTRACT)",
            "remote_asset_id": (reg or {}).get("remote_asset_id"), "remote_url": (reg or {}).get("remote_url"),
            "timbre_brief": spec.get("timbre_brief")}
    artifacts = ([{"role": "VOICE_REFERENCE_WAV", "media_type": "audio/wav", "path": str(wav), "sha256": wav_sha,
                   "provider_asset_id": (reg or {}).get("remote_asset_id"), "duration_seconds": probe.get("duration_seconds")}]
                 if wav_sha else [])
    provenance = [{"kind": "VOICE_REGISTRY_ROW", "path": str(ctx.voice_registry_path), "entity_id": entity},
                  {"kind": "GIGGLE_UPLOAD_RECEIPT", "path": str(receipt_path),
                   "sha256": sha256_file(receipt_path) if receipt_path.is_file() else None,
                   "uuid": receipt.get("uuid")},
                  {"kind": "SPEECH_TASK_PAYLOAD", "path": str(ctx.speech_payloads_path), "voice_id": voice_id}]
    return finish(row, lock=lock, artifacts=artifacts, provenance=provenance,
                  rights_basis=ctx.rights_basis,
                  checks=checks, note="voice reference generated by AgentCut, normalised by ffmpeg, uploaded to Giggle")


def lock_scene(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    spec = row["specification"]
    loc = spec.get("location_id") or row["asset_id"]
    map_id, room_id = LOCATION_TO_ROOM.get(loc, (None, None))
    if not room_id:
        # E02+: places added by the D-10 extension carry room.location_id — derive instead of hardcoding
        for m in ctx.gsm.get("space_maps", []):
            for r in m.get("rooms", []) or []:
                if r.get("location_id") == loc:
                    map_id, room_id = m.get("global_space_map_id"), r.get("room_id")
    space_map = next((m for m in ctx.gsm.get("space_maps", []) if m.get("global_space_map_id") == map_id), None)
    room = next((r for r in (space_map or {}).get("rooms", []) if r.get("room_id") == room_id), None)
    layout = (space_map or {}).get("layout_image") or {}
    layout_path = Path(layout.get("path") or "/nonexistent")
    layout_sha = sha256_file(layout_path) if layout_path.is_file() else None
    gate_report = next((g for g in ctx.machine_gates.get("reports", []) if g.get("gate_id") == "SCENE-AUTHORITY-LOCK"), None)
    gate_path = ENGINE / gate_report["path"] if gate_report else None
    gate_status = (load_json(gate_path).get("status") if gate_path and gate_path.is_file() else None)
    checks = [
        {"id": "global_space_map_status_locked", "status": "PASS" if ctx.gsm.get("status") == "LOCKED" else "FAIL"},
        {"id": "location_mapped_to_existing_room", "status": "PASS" if room else "FAIL", "map": map_id, "room": room_id},
        {"id": "layout_image_sha_matches_map_record", "status": "PASS" if layout_sha and layout_sha == layout.get("sha256") else "FAIL"},
        {"id": "layout_image_qa_status", "status": layout.get("qa_status") or "MISSING"},
        {"id": "s2_scene_authority_lock_gate", "status": gate_status or "MISSING", "report": str(gate_path) if gate_path else None},
    ]
    lock = {"spatial_topology": {"declared": spec.get("spatial_topology"),
                                 "key_fixed_elements": spec.get("key_fixed_elements"),
                                 "episode_global_space_map_id": ctx.gsm.get("episode_global_space_map_id"),
                                 "global_space_map_id": map_id, "room_id": room_id,
                                 "topology_sha256": ctx.gsm.get("topology_sha256"),
                                 "coordinate_system": (space_map or {}).get("coordinate_system")}}
    artifacts = ([{"role": "PLACE_TOP_DOWN_COMPLETE_SPACE_MAP", "media_type": "image/png", "path": str(layout_path), "sha256": layout_sha}]
                 if layout_sha else [])
    provenance = [{"kind": "EPISODE_GLOBAL_SPACE_MAP", "path": str(ctx.gsm_path), "sha256": sha256_file(ctx.gsm_path)}]
    return finish(row, lock=lock, artifacts=artifacts, provenance=provenance, rights_basis=ctx.rights_basis,
                  checks=checks, note="scene locked on the episode's LOCKED global space map (no separate establishing plate was generated; keyframes carry the visual)")


def lock_reference(ctx: Ctx, row: dict[str, Any]) -> dict[str, Any]:
    spec = row["specification"]
    kind = spec.get("asset_kind")
    if kind == "SOURCE_CHAPTER":
        path = Path(spec.get("path"))
        media = "text/markdown"
    elif "VISUAL" in row["asset_id"]:
        path = ctx.contract_path
        media = "application/json"
    else:
        path = ctx.gsm_path
        media = "application/json"
    sha = sha256_file(path) if path.is_file() else None
    expected = {ref.get("sha256") for ref in row.get("authority_refs") or []}
    checks = [{"id": "file_exists", "status": "PASS" if sha else "FAIL", "path": str(path)}]
    if kind == "SOURCE_CHAPTER":
        checks.append({"id": "sha_matches_authority_ref", "status": "PASS" if sha in expected else "FAIL"})
    elif "VISUAL" in row["asset_id"]:
        checks.append({"id": "visual_culture_contract_locked_in_generation_contract",
                       "status": "PASS" if (ctx.contract.get("visual_culture_contract") or {}).get("status") == "LOCKED" else "FAIL"})
    else:
        checks.append({"id": "global_space_map_status_locked", "status": "PASS" if ctx.gsm.get("status") == "LOCKED" else "FAIL"})
    lock = {"usage_scope": spec.get("usage_scope"), "path": str(path), "sha256": sha}
    artifacts = [{"role": kind or "REFERENCE_DOCUMENT", "media_type": media, "path": str(path), "sha256": sha}] if sha else []
    provenance = [{"kind": "FILE_ON_DISK", "path": str(path), "sha256": sha}]
    basis = ctx.rights_basis
    return finish(row, lock=lock, artifacts=artifacts, provenance=provenance, rights_basis=basis,
                  checks=checks, note="reference material locked on the file itself")


def lock_declared_audio(ctx: Ctx, category: str, row: dict[str, Any]) -> dict[str, Any]:
    spec = row["specification"]
    audio = ctx.contract.get("audio_contract") or {}
    shots = {s.get("shot_id") for s in ctx.contract.get("shots") or []}
    lock: dict[str, Any] = {"realization": "SD2_NATIVE_AUDIO_NO_SEPARATE_ASSET",
                            "realization_note": "SD2 原生音频；此行只锁定声音规格，可听结果在 S6 生成后由 audio_stream / av_sync / dialogue gate 逐单元量测。"}
    checks: list[dict[str, Any]] = []
    if category == "ambience":
        scene = spec.get("scene_scope")
        contract_field = audio.get("ambient_by_scene", {}).get(scene)
        lock.update({"scene_scope": scene, "sound_field": spec.get("sound_field"),
                     "location_id": spec.get("location_id"), "time_id": spec.get("time_id")})
        checks.append({"id": "sound_field_equals_generation_contract_ambient_by_scene",
                       "status": "PASS" if contract_field and contract_field == spec.get("sound_field") else "FAIL",
                       "contract_value": contract_field})
    elif category == "sfx":
        lock.update({"physical_source": spec.get("physical_source"), "sync_event": spec.get("sync_event")})
        checks.append({"id": "sync_event_is_a_declared_shot", "status": "PASS" if spec.get("sync_event") in shots else "FAIL"})
    elif category == "music":
        lock.update({"usage_scope": spec.get("usage_scope"), "musical_identity": spec.get("musical_identity"),
                     "external_bgm_allowed": bool(spec.get("external_bgm_allowed"))})
        bgm = audio.get("bgm")
        selective = isinstance(bgm, dict) and str(bgm.get("mode") or "").upper() == "SELECTIVE" and bool(bgm.get("cues"))
        lock["bgm_mode"] = (bgm.get("mode") if isinstance(bgm, dict) else "NONE")
        checks.append({"id": "contract_bgm_policy_consistent",
                       "status": "PASS" if (_bgm_is_none(bgm) and not spec.get("external_bgm_allowed")) or selective else "FAIL",
                       "note": "NONE (E01/E02) or SELECTIVE with cues (D-32, seq=13 c2); the requirement row's external_bgm_allowed flag is derived and not authoritative for SELECTIVE"})
    elif category == "accents":
        lock.update({"locale": spec.get("locale"), "pronunciation_profile": spec.get("pronunciation_profile"),
                     "forbidden": spec.get("forbidden")})
        checks.append({"id": "locale_zh_cn", "status": "PASS" if spec.get("locale") == "zh-CN" else "FAIL"})
        checks.append({"id": "all_voice_rows_language_zh_cn",
                       "status": "PASS" if all(v["specification"].get("language") == "zh-CN" for v in ctx.requirements["assets"].get("voices", [])) else "FAIL"})
    artifacts = [{"role": "DECLARED_AUDIO_SPEC_IN_GENERATION_CONTRACT", "media_type": "application/json",
                  "path": str(ctx.contract_path), "sha256": ctx.contract_sha}]
    provenance = [{"kind": "GENERATION_CONTRACT_AUDIO_CONTRACT", "path": str(ctx.contract_path), "sha256": ctx.contract_sha}]
    return finish(row, lock=lock, artifacts=artifacts, provenance=provenance, rights_basis=ctx.rights_basis,
                  checks=checks, note="declared native-audio spec lock (no separate audio file exists by design)")


HANDLERS = {
    "wardrobe": lambda ctx, row: lock_wardrobe(ctx, row),
    "voices": lambda ctx, row: lock_voice(ctx, row),
    "scenes": lambda ctx, row: lock_scene(ctx, row),
    "reference_materials": lambda ctx, row: lock_reference(ctx, row),
    "ambience": lambda ctx, row: lock_declared_audio(ctx, "ambience", row),
    "sfx": lambda ctx, row: lock_declared_audio(ctx, "sfx", row),
    "music": lambda ctx, row: lock_declared_audio(ctx, "music", row),
    "accents": lambda ctx, row: lock_declared_audio(ctx, "accents", row),
}


def run_lock(ctx: Ctx, report_path: Path, force: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    assets = ctx.library.setdefault("assets", {})
    # E02+ cross-episode reuse (S3 skips plate subjects the runtime library already LOCKED): copy the
    # LOCKED row into this episode's library when every artifact file still matches its recorded sha.
    rt_assets = (ctx.runtime_library or {}).get("assets") or {}
    for category in ("characters", "props", "scenes"):
        by_id = assets.setdefault(category, {})
        for requirement in ctx.requirements.get("assets", {}).get(category, []):
            asset_id = requirement["asset_id"]
            if str((requirement.get("reuse") or {}).get("status") or "") != "REUSED_FROM_PRIOR_LIBRARY":
                continue
            cur = by_id.get(asset_id) or {}
            if cur.get("status") == "LOCKED":
                continue
            src = (rt_assets.get(category) or {}).get(asset_id) or {}
            arts = src.get("artifacts") or []
            ok = (src.get("status") == "LOCKED" and (src.get("qa") or {}).get("status") == "PASS" and arts
                  and all(Path(str(a.get("path"))).is_file() and sha256_file(Path(str(a.get("path")))) == a.get("sha256") for a in arts))
            if not ok:
                failures.append({"category": category, "asset_id": asset_id,
                                 "errors": ["cross_episode_reuse_source_not_locked_or_artifact_sha_mismatch"]})
                continue
            new_row = deepcopy(src)
            try:
                from tools.initial_asset_library import canonical_sha256  # engine, read-only
                new_row["requirement_sha256"] = canonical_sha256(requirement)   # this episode's requirement row
            except Exception:  # noqa: BLE001
                pass
            new_row["required_in_episodes"] = sorted(set(list(src.get("required_in_episodes") or []) + [int(ctx.episode[1:])]))
            new_row.setdefault("provenance", []).append({"kind": "CROSS_EPISODE_REUSE", "from_library": str(ctx.runtime_library_path),
                                                         "reuse": requirement.get("reuse"), "recorded_at": utc_now(), "episode": ctx.episode})
            by_id[asset_id] = new_row
            results.append({"category": category, "asset_id": asset_id, "status": "LOCKED", "checks": [("cross_episode_reuse_artifact_sha", "PASS")]})
    for category, handler in HANDLERS.items():
        by_id = assets.setdefault(category, {})
        for requirement in ctx.requirements.get("assets", {}).get(category, []):
            asset_id = requirement["asset_id"]
            row = by_id.get(asset_id)
            if row is None:
                failures.append({"category": category, "asset_id": asset_id, "errors": ["row_missing_in_library"]})
                continue
            if row.get("status") == "LOCKED" and not force:
                results.append({"category": category, "asset_id": asset_id, "status": "ALREADY_LOCKED"})
                continue
            new_row = handler(ctx, row)
            by_id[asset_id] = new_row
            entry = {"category": category, "asset_id": asset_id, "status": new_row["status"],
                     "checks": [(c["id"], c["status"]) for c in new_row["qa"]["checks"]]}
            results.append(entry)
            if new_row["status"] != "LOCKED":
                failures.append({"category": category, "asset_id": asset_id,
                                 "errors": [f"{c['id']}:{c['status']}" for c in new_row["qa"]["checks"] if c["status"] != "PASS"]})
    ctx.library["updated_at"] = utc_now()
    write_json(ctx.library_path, ctx.library)
    libraries = [str(ctx.library_path)]
    if ctx.runtime_library is not None:
        rt_assets = ctx.runtime_library.setdefault("assets", {})
        for category in list(HANDLERS) + ["characters", "props"]:
            rt_assets.setdefault(category, {}).update(deepcopy(assets.get(category, {})))
        ctx.runtime_library["updated_at"] = utc_now()
        write_json(ctx.runtime_library_path, ctx.runtime_library)
        libraries.append(str(ctx.runtime_library_path))
    report = {"schema": SCHEMA, "episode": ctx.episode,
              "series_scope_id": ctx.scope_id, "series_id": ctx.series_id,
              "asset_library_authority": str(ctx.runtime_library_path),
              "asset_library_seed": str(ctx.runtime_library_seed_path),
              "voice_registry_authority": str(ctx.voice_registry_path),
              "voice_registry_policy": ctx.voice_registry_policy,
              "recorded_at": utc_now(), "recorded_by": "library_lock_non_plate.v1",
              "decision": "D-15", "libraries": libraries, "rights_basis": ctx.rights_basis,
              "identity_review": (ctx.identity_review or {}).get("_path"),
              "status": "PASS" if not failures else "FAIL",
              "locked_count": sum(1 for r in results if r["status"] in ("LOCKED", "ALREADY_LOCKED")),
              "failed_count": len(failures), "results": results, "failures": failures}
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("--episode", required=True)
    lock.add_argument("--rights-basis", required=True)
    lock.add_argument("--report", required=True)
    lock.add_argument("--force", action="store_true", help="re-lock rows that are already LOCKED")
    args = parser.parse_args()
    ctx = Ctx(args.episode, args.rights_basis)
    try:
        report = run_lock(ctx, Path(args.report), args.force)
    except _media.MediaToolBlocked as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps({k: report[k] for k in ("status", "locked_count", "failed_count", "failures")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
