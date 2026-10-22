#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nalu_qa_common.py — shared primitives for the nalu QA route (D-1…D-9).

Everything in this module is deterministic and side-effect free apart from the
atomic writers.  It holds:

  * fixed geography (engine clone, runtime, venv) — identical to nalu_pipeline.py;
  * the reviewer identity constant that every machine-review record must carry;
  * sha256 / atomic-write / utc helpers that match the engine's own conventions;
  * ``engine_module()`` so the QA tools call the ENGINE's own gate code instead
    of re-implementing a check (the whole design contract of this line);
  * ``Expectations`` — the authoritative per-episode expectation extractor.  A
    review request must show the reviewer what the SCRIPT says, never what the
    image says, so every expectation here is read out of the authored layers
    (generation contract → editorial seedance manifest → anchor plan →
    start-frame contracts → asset library / wardrobe bible).
"""

from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import nalu_series_scope as _series_scope
import nalu_media_tools as _media

import hashlib
import importlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# fixed geography (must stay identical to nalu_pipeline.py)
# --------------------------------------------------------------------------- #
ENGINE = Path(f"{_np.ENGINE_ROOT}")
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")
VENV = Path(f"{_np.VENV_PYTHON}")
RT = RUNTIME / "runtime"
RT_TOOLS = Path(f"{_np.TOOLS_DIR}")  # port fix 2026-09-15
RT_CONFIGS = RT / "configs"
REVIEWS_ROOT = RT / "reviews"
STATE_DIR = RT / "pipeline_state"
ASSET_LIBRARY = RT / "asset_library.json"
CHARACTER_REGISTRY = Path(
    os.environ.get("QINGSHAN_CHARACTER_REGISTRY")
    or ((RT / "character_asset_registry.json")
        if (RT / "character_asset_registry.json").is_file()
        else (RT / "nalu_character_asset_registry.json"))
).expanduser().resolve()
CHARACTER_SOURCES = RT / "character_sources"
GATE_REGISTRY = ENGINE / "configs/GATE_REGISTRY_v3_20260716.json"
REROLL_POLICY = ENGINE / "configs/reroll_cost_guard_policy_v1_20260716.json"
DIALOGUE_QA_POLICY = RT_CONFIGS / "BASIC_DIALOGUE_QA_POLICY.json"
NALU_WORK = Path(os.environ.get("NALU_WORK_ROOT") or (ENGINE / "workflow/nalu")).expanduser().resolve()
SCRIPTS = ENGINE / "workflow/claude_writer_agent/scripts"


def require_ffmpeg() -> str:
    """Resolve the deployment's ffmpeg only when a media route needs it."""
    return _media.require_ffmpeg()


def require_ffprobe() -> str:
    """Resolve the deployment's ffprobe only when a media route needs it."""
    return _media.require_ffprobe()

# The start-frame receipt path convention is fixed by
# build_nalu_preproduction.py:1006-1007 (``expected_evidence_ref``) and resolved
# against the ENGINE root by grouped_anchor_semantic_contract._resolve, which
# compile_grouped_seedance_manifest.py:858 calls with root=ROOT.
START_FRAME_EVIDENCE_RELDIR = "reports/start_frame_evidence"

# --------------------------------------------------------------------------- #
# the reviewer identity — no record may claim a review it did not receive
# --------------------------------------------------------------------------- #
def review_identity(environ: dict[str, str]) -> tuple[str, str]:
    """Allow an explicit reviewer without silently inheriting another model's name.

    Both fields travel together through request, validation and materialisers.
    Existing deployments with neither override retain their configured legacy
    reviewer; specifying only one field is an error, never an inferred review.
    """
    keys = ("NALU_QA_REVIEWER_ID", "NALU_QA_REVIEW_METHOD")
    if not any(key in environ for key in keys):
        return "claude-code-nalu-vlm", "CLAUDE_VLM_STRUCTURED_REVIEW"
    values = tuple(str(environ.get(key) or "").strip() for key in keys)
    if not all(values):
        raise ValueError("QA_REVIEWER_ID_AND_METHOD_REQUIRED_TOGETHER")
    return values


REVIEWER_ID, REVIEW_METHOD = review_identity(os.environ)
#: reviewer_type accepted by shot_media_admission_gate.py:607 for a P0 gate.
REVIEWER_TYPE = "AI_VISUAL"
MIN_OBSERVATION_CHARS = 20

SCHEMA_REQUEST = "nalu.vlm_review_request.v1"
SCHEMA_ANSWERS = "nalu.vlm_review_answers.v1"
SCHEMA_SUBMITTED = "nalu.vlm_review_submitted.v1"

TEMPLATE_MARKER = "__NOT_A_REVIEW_FILL_EVERY_NULL__"

#: ``video_q2`` is the Q2 VIDEO_ASSEMBLY content review (D-7).  It is a
#: separate kind from ``post_gen_plot`` on purpose: post_gen_plot asks only the
#: five basic-plot questions post_generation_qa_scope_gate.py ALLOWS, while
#: shot_media_admission_gate.py in VIDEO_ASSEMBLY mode additionally needs a
#: VLM_STRUCTURED_STATE_QA_V1 block and a closed-set anachronism answer.  Every
#: video_q2 question is inside the allowed scope — none of the sixteen
#: FORBIDDEN_POST_GENERATION_CHECKS (gesture / microexpression / choreography /
#: trajectory / optical-flow / motion-energy families) is asked.
#: ``action_role`` is the exact-output action-role verification of a unit's
#: START frame that shot_media_admission_gate.precheck_submission_inputs demands
#: (``_requires_exact_action_role_evidence``: interaction_topology_contract.required)
#: before any paid VIDEO submit: who initiates, who receives, who owns each prop.
KINDS = ("identity", "keyframe", "start_frame", "post_gen_plot", "video_q2", "action_role")
#: engine-root receipt dir for qingshan.exact_output_action_role_verification.v1
ACTION_ROLE_EVIDENCE_RELDIR = "reports/action_role_evidence"


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path | str) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")))


def read_json(path: Path | str, default: Any = None) -> Any:
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path | str, payload: Any) -> Path:
    """Atomic write — temp file then os.replace, the engine's own convention."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)
    return path


def portable(path: Path | str, root: Path = ENGINE) -> str:
    """Engine-root-relative when possible — what the engine gates expect."""
    path = Path(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def engine_module(name: str):
    """Import an ENGINE tool module so its own logic is used, never a copy."""
    for entry in (str(ENGINE), str(ENGINE / "tools")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return importlib.import_module(name)


def gate_parameters(gate_id: str) -> dict[str, Any]:
    registry = read_json(GATE_REGISTRY, {}) or {}
    for row in registry.get("gates") or []:
        if row.get("gate_id") == gate_id:
            return row.get("parameters") or {}
    return {}


# --------------------------------------------------------------------------- #
# per-episode paths (the subset the QA route needs; mirrors nalu_pipeline.Paths)
# --------------------------------------------------------------------------- #
class QaPaths:
    def __init__(self, episode: str) -> None:
        self.episode = episode
        # Episode names are not globally unique (a new production also starts at
        # E01).  Every reusable authority therefore comes from the selected
        # series scope, never from the historical NALU-YEWUJIANG constants above.
        self.scope = _series_scope.resolve_scope(episode)
        self.scope_id = str(self.scope["scope_id"])
        self.series_id = str(self.scope["series_id"])
        self.asset_library = Path(self.scope["asset_library"])
        self.asset_library_seed = Path(self.scope["asset_library_seed"])
        self.character_registry = Path(self.scope["character_registry"])
        self.character_sources = Path(self.scope["character_sources"])
        self.entity_registry = Path(self.scope["entity_registry"])
        self.voice_registry = Path(self.scope["voice_registry"])
        self.voice_cast = Path(self.scope["voice_cast"])
        self.lexicon = Path(self.scope["lexicon"])
        prefix = f"{episode}_"
        self.work = NALU_WORK / episode
        self.preprod = self.work / "preproduction"
        self.preprod_reports = self.preprod / "reports"
        self.keyframes = self.preprod / "keyframes"
        self.identity = self.work / "identity"
        self.plates = self.identity / "plates"
        self.video_media = self.work / "video"
        self.assembly = self.work / "assembly"
        state = read_json(STATE_DIR / f"{episode}.json", {}) or {}
        remembered = (state.get("layers") or {}).get("paths") or {}
        state_scope = ((state.get("series_scope") or {}).get("scope_id")
                       or state.get("series_scope_id"))
        if remembered and state_scope not in (None, self.scope_id):
            raise SystemExit(
                f"PIPELINE_STATE_SCOPE_MISMATCH:{state_scope}!={self.scope_id}"
            )
        self.narrative = Path(
            remembered.get("narrative_canonical")
            or SCRIPTS / f"{episode}_NARRATIVE_CANONICAL_v1.md"
        )
        self.directing = Path(
            remembered.get("directing_script")
            or SCRIPTS / f"{episode}_DIRECTING_SCRIPT_v1.md"
        )
        self.contract = Path(
            remembered.get("generation_contract")
            or SCRIPTS / f"{episode}_GENERATION_CONTRACT_v1.json"
        )
        self.writer_manifest = Path(
            remembered.get("writer_manifest")
            or SCRIPTS / f"{episode}_manifest_v1.json"
        )
        # Optional repair QA context: never replace the active episode state or
        # write new-image receipts into the previous production's QA directory.
        context_path = os.environ.get("NALU_QA_CONTEXT")
        context = None
        if context_path:
            context = read_json(Path(context_path), {}) or {}
            if (context.get("episode") != episode
                    or context.get("scope_id") != self.scope_id):
                raise SystemExit("QA_CONTEXT_SCOPE_MISMATCH")
            selected = {}
            for name in ("preproduction", "contract", "identity_library"):
                row = context.get(name) or {}
                path = Path(str(row.get("path") or "")).resolve()
                if not path.is_relative_to(self.work.resolve()):
                    raise SystemExit(f"QA_CONTEXT_OUTSIDE_EPISODE:{name}")
                if name == "preproduction":
                    if not path.is_dir():
                        raise SystemExit("QA_CONTEXT_PREPRODUCTION_MISSING")
                elif not path.is_file() or sha256_file(path) != row.get("sha256"):
                    raise SystemExit(f"QA_CONTEXT_SHA_MISMATCH:{name}")
                selected[name] = path
            self.preprod = selected["preproduction"]
            self.preprod_reports = self.preprod / "reports"
            self.keyframes = self.preprod / "keyframes"
            self.contract = selected["contract"]
        self.editorial = self.preprod / f"{prefix}EDITORIAL_SEEDANCE_MANIFEST_V1.json"
        self.grouping_plan = self.preprod / f"{prefix}VIDEO_UNIT_GROUPING_PLAN_V1.json"
        self.anchor_plan = self.preprod / f"{prefix}VIDEO_UNIT_ANCHOR_PLAN_V1.json"
        self.start_frames = self.preprod / f"{prefix}START_FRAME_SEMANTIC_CONTRACTS_V1.json"
        # A repaired anchor selection and its semantic contracts form one
        # snapshot. Never mix a newly reviewed still with default old contracts.
        if context is not None:
            names = ("anchor_plan", "start_frames")
            present = [name in context for name in names]
            if any(present) and not all(present):
                raise SystemExit("QA_CONTEXT_ANCHORS_REQUIRED_TOGETHER")
            for name in names if all(present) else ():
                row = context[name]
                if not isinstance(row, dict) or not row.get("path"):
                    raise SystemExit(f"QA_CONTEXT_INVALID_REFERENCE:{name}")
                path = Path(row["path"]).resolve()
                if not path.is_relative_to(self.work.resolve()):
                    raise SystemExit(f"QA_CONTEXT_OUTSIDE_EPISODE:{name}")
                if not path.is_file() or sha256_file(path) != row.get("sha256"):
                    raise SystemExit(f"QA_CONTEXT_SHA_MISMATCH:{name}")
                setattr(self, name, path)
        self.identity_library = self.identity / "asset_library.json"
        self.reviewed_identity_regions = None
        if context is not None:
            self.identity_library = selected["identity_library"]
            if "reviewed_identity_regions" in context:
                row = context["reviewed_identity_regions"]
                path = Path(str(row.get("path") or "")).resolve()
                if not path.is_relative_to(self.work.resolve()):
                    raise SystemExit("QA_CONTEXT_OUTSIDE_EPISODE:reviewed_identity_regions")
                if not path.is_file() or sha256_file(path) != row.get("sha256"):
                    raise SystemExit("QA_CONTEXT_SHA_MISMATCH:reviewed_identity_regions")
                self.reviewed_identity_regions = path
        self.asset_requirements = RUNTIME / "preproduction" / episode / "asset_requirements.json"
        # QA outputs
        self.reviews = REVIEWS_ROOT / episode
        if context is not None:
            self.reviews = self.preprod_reports / "reviews"
        self.qa_root = self.preprod_reports / "qa"
        self.q1_dir = self.qa_root / "q1"
        #: Q2 VIDEO_ASSEMBLY admission (D-7) — one directory per video unit, with
        #: its extracted original-resolution frames, its five evidence files, its
        #: admission_request.json and the gate's own admission_result.json.
        self.q2_dir = self.qa_root / "q2"
        self.identity_qa = self.identity / f"{prefix}IDENTITY_QA_LOCK.json"
        self.identity_embed_cache = self.qa_root / "identity_face_crops"
        self.postgen_dir = self.qa_root / "post_generation"
        self.final_qa_dir = self.assembly / "final_qa"
        self.evidence_bundle = self.assembly / f"{prefix}MANDATORY_GATE_EVIDENCE.json"
        self.reroll_requests = self.qa_root / f"{prefix}REROLL_REQUESTS.json"
        self.reroll_ledger = self.qa_root / f"{prefix}REROLL_LEDGER.json"
        # engine-root canonical start-frame receipt dir (see the constant above)
        self.start_frame_evidence = ENGINE / START_FRAME_EVIDENCE_RELDIR
        self.start_frame_evidence_mirror = self.preprod_reports / "start_frame_evidence"
        if context is not None:
            self.start_frame_evidence = self.start_frame_evidence_mirror

    def keyframe(self, shot_id: str) -> Path:
        candidates = list(self.keyframes.glob(f"{shot_id}-keyframe-v*.png"))
        if not candidates:
            return self.keyframes / f"{shot_id}-keyframe-v1.png"

        def version(path: Path) -> tuple[int, str]:
            match = re.search(r"-keyframe-v(\d+)\.png$", path.name, re.I)
            return (int(match.group(1)) if match else 0, path.name)

        return max(candidates, key=version)

    def reusable_asset_library(self) -> Path:
        """Return this series' materialised library, or its declared seed.

        A foreign scope is required by ``nalu_series_scope`` to declare both
        paths.  Deliberately do not fall back to the default series when either
        is absent: an empty/new production must fail closed instead of reusing
        a same-named E01 from another show.
        """
        return self.asset_library if self.asset_library.is_file() else self.asset_library_seed


SOURCE_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def find_scoped_operator_source(asset_id: str, folder: Path | str) -> Path | None:
    """Find one source image below a series-scoped private source root.

    StoryClaw stores new-series references in nested episode directories, for
    example ``character_sources/fobenshidao/E01``.  Matching stays anchored on
    the complete asset id so ``CHAR-LU`` cannot capture ``CHAR-LUWENHUI``.
    The priority order preserves the historical identity-lock behaviour.
    """
    root = Path(folder)
    if not root.is_dir():
        return None
    patterns = (
        f"{asset_id}.png",
        f"{asset_id}__SOURCE*",
        f"{asset_id}.*",
        f"{asset_id}__*",
        f"{asset_id}_*",
    )
    for pattern in patterns:
        candidates = sorted(
            (path for path in root.rglob(pattern)
             if path.is_file() and path.suffix.lower() in SOURCE_IMAGE_SUFFIXES
             # retired / held sources live in "_retired*" / "_hold*" folders and must never re-bind
             and not any(part.startswith("_") for part in path.relative_to(root).parts[:-1])),
            key=lambda path: str(path),
        )
        if candidates:
            return candidates[0]
    return None


# --------------------------------------------------------------------------- #
# authoritative expectations
# --------------------------------------------------------------------------- #
class Expectations:
    """Everything a reviewer is allowed to be told, read from authored layers.

    The reviewer never sees a "hint" derived from the image under review.  Every
    field here comes from the writer's four layers by way of the preproduction
    compiler, or from the asset library / wardrobe bible.
    """

    def __init__(self, episode: str) -> None:
        self.episode = episode
        self.p = QaPaths(episode)
        self.editorial = read_json(self.p.editorial, {}) or {}
        self.anchor_plan = read_json(self.p.anchor_plan, {}) or {}
        self.grouping = read_json(self.p.grouping_plan, {}) or {}
        self.start_frames = read_json(self.p.start_frames, {}) or {}
        episode_library = read_json(self.p.identity_library)
        if episode_library:
            project_id = str(episode_library.get("project_id") or "")
            if project_id != self.p.series_id:
                raise SystemExit(
                    f"EPISODE_ASSET_LIBRARY_PROJECT_MISMATCH:{self.p.identity_library}:"
                    f"{project_id}!={self.p.series_id}")
            self.library = episode_library
        else:
            self.library = read_json(self.p.reusable_asset_library(), {}) or {}
        if self.library:
            project_id = str(self.library.get("project_id") or "")
            if project_id != self.p.series_id:
                raise SystemExit(
                    f"SCOPED_ASSET_LIBRARY_PROJECT_MISMATCH:"
                    f"{self.p.reusable_asset_library()}:{project_id}!={self.p.series_id}")
        self.requirements = read_json(self.p.asset_requirements, {}) or {}
        # the generation contract (writer-agent scripts dir); D-35 creature/prop subjects are resolved from it
        self.contract = read_json(self.p.contract, {}) or {}
        self.shots = {str(row.get("shot_id")): row for row in self.editorial.get("shots") or []}
        bible = self.editorial.get("wardrobe_bible") or {}
        self.wardrobe_by_id = {str(row.get("character_id")): row
                               for row in bible.get("characters") or []}
        self.wardrobe_by_name = {str(row.get("character")): row
                                 for row in bible.get("characters") or []}
        self.units = {str(row.get("unit_id")): row for row in self.anchor_plan.get("units") or []}
        self.grouping_units = {str(row.get("unit_id")): row
                               for row in self.grouping.get("units") or []}
        self.start_frame_units = {str(row.get("unit_id")): row
                                  for row in self.start_frames.get("units") or []}

    # ------------------------------------------------------------ vocabulary
    def character_ids(self) -> list[str]:
        return sorted(self.wardrobe_by_id)

    def character_name_to_id(self) -> dict[str, str]:
        return {str(row.get("character")): str(row.get("character_id"))
                for row in self.wardrobe_by_id.values()}

    def forbidden_terms(self) -> list[str]:
        """The closed anachronism vocabulary actually enforced by the engine.

        Source of truth: anachronism_lock_gate.FORBIDDEN_VISIBLE_TERMS (the
        engine's own hardcoded closed set), unioned with this episode's authored
        negative_prompts so the review is contract-derived as the registry
        requires (``p0_questions_must_be_closed_and_contract_derived``).
        """
        terms: list[str] = []
        try:
            gate = engine_module("anachronism_lock_gate")
            terms.extend(str(value) for value in getattr(gate, "FORBIDDEN_VISIBLE_TERMS", ()))
        except Exception:  # noqa: BLE001 — a missing engine module is reported, not fatal
            pass
        for shot in self.shots.values():
            for value in (shot.get("prompt_spec") or {}).get("negative_prompts") or []:
                if str(value) not in terms:
                    terms.append(str(value))
        return terms

    # -------------------------------------------------------------- identity
    def identity_subjects(self, *, categories=("characters", "wardrobe", "props")) -> list[dict[str, Any]]:
        """One row per identity-plate subject, with its authored appearance."""
        rows: list[dict[str, Any]] = []
        assets = (self.library.get("assets") or {})
        for category in categories:
            for asset_id, asset in sorted((assets.get(category) or {}).items()):
                spec = asset.get("specification") or {}
                rows.append({
                    "item_id": asset_id,
                    "asset_id": asset_id,
                    "category": category,
                    "label": asset.get("label"),
                    "expectations": {
                        "asset_kind": spec.get("asset_kind"),
                        "canonical_name": spec.get("canonical_name") or asset.get("label"),
                        "aliases": spec.get("aliases") or [],
                        "appearance": spec.get("appearance_ch1") or spec.get("appearance")
                                      or spec.get("physical_function"),
                        "apparent_age_range": spec.get("apparent_age_range"),
                        "sex": spec.get("sex"),
                        "identity_lock_required_fields": spec.get("identity_lock_required_fields") or [],
                        "card_deliverables": spec.get("card_deliverables") or [],
                        "aspect_ratio": spec.get("aspect_ratio") or "9:16",
                        "wardrobe": self._wardrobe_expectation(asset_id, spec),
                        "visual_culture_palette": {
                            key: (spec.get("visual_culture") or {}).get(key)
                            for key in ("palette_base", "palette_accent", "palette_skin",
                                        "lighting_language", "image_texture")},
                        "forbidden_influences":
                            (spec.get("visual_culture") or {}).get("forbidden_influences") or [],
                    },
                })
        return rows

    def _wardrobe_expectation(self, asset_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        override = (spec.get("wardrobe_state_overrides") or {}).get(asset_id)
        if override:
            # Match the image compiler: the authored per-shot state replaces,
            # rather than supplements, global clothing/condition descriptions.
            return {"character_id": asset_id,
                    "authored_description": str(override).strip(),
                    "source": "SHOT_WARDROBE_STATE_OVERRIDE"}
        row = self.wardrobe_by_id.get(asset_id)
        if row is None:
            owner = str(spec.get("owner_character_id") or "")
            row = self.wardrobe_by_id.get(owner)
        if row is None:
            return {}
        keys = ("character_id", "authored_description", "silhouette", "outer_layer", "inner_layer",
                "primary_color", "secondary_color", "material", "pattern", "belt_or_fastening",
                "footwear", "accessory", "condition", "continuity_key", "role_basis")
        # null = the authored wardrobe text does not decide this field; a reviewer
        # must not be asked to verify a value nobody authored.
        return {key: row.get(key) for key in keys if row.get(key) not in (None, "")}

    # -------------------------------------------------------------- keyframe
    def keyframe_items(self) -> list[dict[str, Any]]:
        """One row per planned keyframe (unit first shot), with its expectations."""
        rows: list[dict[str, Any]] = []
        # E02+ anchor policy v4: a unit whose opening anchor is CONTINUITY_DERIVED_KEYFRAME has no
        # keyframe task; its start frame is materialised at S6 from the previous unit's real tail
        # and reviewed then (same questionnaire).  Until that file exists it is not a Q1 item.
        derived: dict[str, dict[str, Any]] = {}
        try:
            anchors = json.loads(self.p.anchor_plan.read_text(encoding="utf-8")).get("units") or []
            for a in anchors:
                oac = a.get("opening_anchor_contract") or {}
                if str(oac.get("source") or "") == "CONTINUITY_DERIVED_KEYFRAME":
                    derived[a["unit_id"]] = oac
        except Exception:  # noqa: BLE001
            derived = {}
        self.keyframe_items_skipped_continuity_derived = []
        for unit_id, unit in sorted(self.units.items()):
            shot_id = self._unit_first_shot_id(unit)
            if unit_id in derived and not self.p.keyframe(shot_id).is_file():
                self.keyframe_items_skipped_continuity_derived.append(
                    {"unit_id": unit_id, "shot_id": shot_id, "previous_unit_id": derived[unit_id].get("previous_unit_id")})
                continue
            shot = self.shots.get(shot_id) or {}
            spec = shot.get("prompt_spec") or {}
            cast = spec.get("cast") or []
            name_to_id = self.character_name_to_id()
            visible = [row for row in cast
                       if str(row.get("face_visibility")) != "OFFSCREEN_VOICE_ONLY"]
            rows.append({
                "item_id": shot_id,
                "unit_id": unit_id,
                "shot_id": shot_id,
                "media_path": str(self.p.keyframe(shot_id)),
                "expectations": {
                    "entry_state": (spec.get("action") or {}).get("start_state"),
                    "forbidden_completion_state": (spec.get("action") or {}).get("completion_state"),
                    "still_prompt_contract": (spec.get("visual_design") or {}).get("still_prompt_contract"),
                    "cast": [{"character": row.get("character"),
                              "character_id": row.get("character_id"),
                              "screen_slot": row.get("screen_slot"),
                              "depth_plane": row.get("depth_plane"),
                              "face_visibility": row.get("face_visibility"),
                              "entity_presence": row.get("entity_presence")} for row in cast],
                    "required_visible_characters": sorted(
                        {str(row.get("character")) for row in visible if row.get("character")}),
                    "required_visible_character_ids": sorted(
                        {str(row.get("character_id") or name_to_id.get(str(row.get("character")), ""))
                         for row in visible if row.get("character")} - {""}),
                    "props": spec.get("props") or [],
                    "creature_cards": self.seq19_expectations([shot_id]).get("creature_cards") or {},
                    "required_visible_props": sorted(
                        {str(row.get("prop")) for row in (spec.get("props") or []) if row.get("prop")}),
                    "space": spec.get("space") or {},
                    "required_space_anchors": [
                        (spec.get("space") or {}).get("location"),
                        (spec.get("space") or {}).get("subspace")],
                    "scene_state": spec.get("scene_state") or {},
                    "camera": spec.get("camera"),
                    "camera_start_framing": (unit.get("event_boundary_decision") or {}).get("boundary_class"),
                    "shot_size": shot.get("shot_size"),
                    "axis": shot.get("axis"),
                    "wardrobe": [self._wardrobe_expectation(
                        str(row.get("character_id") or name_to_id.get(str(row.get("character")), "")), spec)
                        for row in visible],
                    "dialogue": spec.get("dialogue") or "",
                    "key_light": (spec.get("visual_design") or {}).get("key_light"),
                    "palette": (spec.get("visual_design") or {}).get("palette") or {},
                    "atmosphere": (spec.get("visual_design") or {}).get("atmosphere"),
                    "negative_prompts": spec.get("negative_prompts") or [],
                    "aspect_ratio": shot.get("aspect_ratio") or "9:16",
                    "resolution": shot.get("resolution") or "720p",
                },
            })
        return rows

    def _unit_first_shot_id(self, unit: dict[str, Any]) -> str:
        keys = unit.get("reference_image_task_keys") or []
        if keys:
            return str(keys[0]).split(":")[0]
        shots = unit.get("editorial_shot_ids") or []
        return str(shots[0]) if shots else ""

    # ------------------------------------------------------------ action role
    def action_role_items(self) -> list[dict[str, Any]]:
        """One row per unit: the declared initiator / target / props of the unit's
        FIRST editorial shot (its start frame), for the exact-output action-role
        verification.  Everything comes from the authored action block and the
        role_semantic_disambiguation of that shot; nothing is read from the image."""
        rows: list[dict[str, Any]] = []
        name_to_id = self.character_name_to_id()
        for unit_id, contract in sorted(self.start_frame_units.items()):
            derived = contract.get("derived_from") or {}
            shot_id = str(derived.get("shot_id") or self._unit_first_shot_id(self.units.get(unit_id) or {}))
            shot = self.shots.get(shot_id) or {}
            spec = shot.get("prompt_spec") or {}
            action = spec.get("action") or {}
            roles = spec.get("role_semantic_disambiguation") or {}
            scene_id = str(shot.get("scene_id") or contract.get("scene_id") or "")
            initiator_id = str(action.get("subject_id") or roles.get("primary_actor_id") or "")
            initiator_kind = str(roles.get("primary_actor_kind") or ("CHARACTER" if initiator_id else "ENVIRONMENT"))
            if not initiator_id:
                if initiator_kind == "ENVIRONMENT":
                    initiator_id = f"SPACE-{scene_id}"
                else:
                    # D-35: a creature/prop subject keeps subject_id "" in the contract (the engine
                    # character_entity_contract rejects non-character ids there); resolve the initiator to the
                    # PROP-* entity whose name equals primary_actor so the action-role evidence is non-empty.
                    actor_name = str(roles.get("primary_actor") or "")
                    for row in spec.get("props") or []:
                        if actor_name and str(row.get("prop") or "") == actor_name:
                            initiator_id = str(row.get("prop_id") or ""); break
                    if not initiator_id:
                        # the editorial manifest drops creature props from the shot row (E04-S03-03 props=[]);
                        # the generation contract's own shot row still carries the PROP-* card
                        c_shots = self.contract.get("shots") or []
                        c_shots = c_shots if isinstance(c_shots, list) else list(c_shots.values())
                        for c_shot in c_shots:
                            if str(c_shot.get("shot_id") or "") != shot_id:
                                continue
                            for row in ((c_shot.get("prompt_spec") or c_shot).get("props") or []):
                                if actor_name and str(row.get("prop") or "") == actor_name:
                                    initiator_id = str(row.get("prop_id") or ""); break
                            break
                    if not initiator_id:
                        for row in self.contract.get("non_character_entities") or []:
                            if actor_name and str(row.get("name") or "") == actor_name:
                                initiator_id = str(row.get("entity_id") or ""); break
            target_id = str(action.get("patient_id") or roles.get("action_patient_id") or "")
            # the contract names a fixed surface / place as the receiver when no character
            # receives the action ("X 与 火炕 的接触/反应落点"); the receiver is then the
            # mapped start space itself
            target_kind = "CHARACTER" if target_id else "FIXED_ELEMENT_OR_SPACE"
            if not target_id:
                target_id = f"SPACE-{scene_id}"
            props = [{"prop_id": str(row.get("prop_id") or ""), "prop": str(row.get("prop") or ""),
                      "anchor": row.get("anchor"), "note": row.get("note")}
                     for row in spec.get("props") or []]
            cast = [{"character_id": str(row.get("character_id") or name_to_id.get(str(row.get("character")), "")),
                     "character": row.get("character"), "face_visibility": row.get("face_visibility"),
                     "first_frame_visible": row.get("first_frame_visible", True)}
                    for row in spec.get("cast") or []]
            rows.append({
                "item_id": unit_id,
                "unit_id": unit_id,
                "shot_id": shot_id,
                "media_path": contract.get("reference_path"),
                "expectations": {
                    "scene_id": scene_id,
                    "entry_state": derived.get("entry_state") or shot.get("entry_state"),
                    "primary_action": action.get("primary_action"),
                    "physical_causality": action.get("physical_causality"),
                    "contact_point": action.get("contact_point"),
                    "initiator_entity_id": initiator_id,
                    "initiator_kind": initiator_kind,
                    "initiator_name": roles.get("primary_actor") or "",
                    "target_entity_id": target_id,
                    "target_kind": target_kind,
                    "target_name": roles.get("action_patient") or "",
                    "cast_at_entry": cast,
                    "props": props,
                    "interaction_state_expected_at_start_frame":
                        "PRE_CONTACT (the start frame shows the entry state, before the "
                        "unit's action makes contact) unless entry_state says otherwise",
                },
            })
        return rows

    # ------------------------------------------------------------ start frame
    def start_frame_items(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        # continuity-derived units (anchor policy v4) are reviewed at S6 once their start frame
        # is materialised from the previous unit's real tail (see keyframe_items)
        cd: set[str] = set()
        try:
            for a in json.loads(self.p.anchor_plan.read_text(encoding="utf-8")).get("units") or []:
                if str(((a.get("opening_anchor_contract") or {}).get("source")) or "") == "CONTINUITY_DERIVED_KEYFRAME":
                    cd.add(a["unit_id"])
        except Exception:  # noqa: BLE001
            cd = set()
        self.start_frame_items_skipped_continuity_derived = []
        for unit_id, contract in sorted(self.start_frame_units.items()):
            derived = contract.get("derived_from") or {}
            ref = contract.get("reference_path")
            if unit_id in cd and not (ref and Path(str(ref)).is_file()):
                self.start_frame_items_skipped_continuity_derived.append(unit_id)
                continue
            rows.append({
                "item_id": unit_id,
                "unit_id": unit_id,
                "shot_id": derived.get("shot_id"),
                "media_path": contract.get("reference_path"),
                "expectations": {
                    "entry_state": derived.get("entry_state"),
                    "keyframe_source": derived.get("keyframe_source"),
                    "camera_start_framing": derived.get("camera_start_framing"),
                    "start_frame_must_show_only_entry_state":
                        contract.get("start_frame_must_show_only_entry_state"),
                    "required_visible_characters": contract.get("required_visible_characters") or [],
                    "required_visible_props": contract.get("required_visible_props") or [],
                    "required_space_anchors": contract.get("required_space_anchors") or [],
                    "empty_establishing_frame_expected": contract.get("empty_establishing_frame"),
                    "expected_evidence_ref": contract.get("expected_evidence_ref"),
                },
            })
        return rows

    # ------------------------------------------------------- Q2 video unit
    def video_unit_items(self) -> list[dict[str, Any]]:
        """One row per video unit, for the Q2 VIDEO_ASSEMBLY content review.

        The unit is the paid video asset, so its expectations are the union of
        its editorial shots' declared cast / props / space anchors / wardrobe /
        negative prompts, with the entry state of its FIRST shot and the
        completion state of its LAST shot — which is exactly the state handoff
        ``ACTION-SHOT-DESIGN-AND-STATE-HANDOFF`` is registered to check.
        """
        name_to_id = self.character_name_to_id()
        rows: list[dict[str, Any]] = []
        for plot in self.unit_plot_items():
            unit_id = plot["unit_id"]
            unit = self.grouping_units.get(unit_id) or {}
            anchor = self.units.get(unit_id) or {}
            shot_ids = [str(value) for value in plot["expectations"]["editorial_shot_ids"]]
            cast_rows: list[dict[str, Any]] = []
            visible_names: set[str] = set()
            visible_ids: set[str] = set()
            props: set[str] = set()
            anchors: list[str] = []
            negatives: list[str] = []
            wardrobe: list[dict[str, Any]] = []
            for shot_id in shot_ids:
                spec = (self.shots.get(shot_id) or {}).get("prompt_spec") or {}
                for row in spec.get("cast") or []:
                    if not row.get("character"):
                        continue
                    cast_rows.append({"shot_id": shot_id,
                                      "character": row.get("character"),
                                      "character_id": row.get("character_id"),
                                      "screen_slot": row.get("screen_slot"),
                                      "depth_plane": row.get("depth_plane"),
                                      "face_visibility": row.get("face_visibility")})
                    if str(row.get("face_visibility")) != "OFFSCREEN_VOICE_ONLY":
                        visible_names.add(str(row["character"]))
                        char_id = str(row.get("character_id")
                                      or name_to_id.get(str(row["character"]), ""))
                        if char_id:
                            visible_ids.add(char_id)
                for row in spec.get("props") or []:
                    if row.get("prop"):
                        props.add(str(row["prop"]))
                for value in ((spec.get("space") or {}).values()):
                    if value and str(value) not in anchors:
                        anchors.append(str(value))
                for value in spec.get("negative_prompts") or []:
                    if str(value) not in negatives:
                        negatives.append(str(value))
            for char_id in sorted(visible_ids):
                row = self._wardrobe_expectation(char_id, {})
                if row:
                    wardrobe.append(row)
            first = (self.shots.get(shot_ids[0]) or {}).get("prompt_spec") or {} if shot_ids else {}
            last = (self.shots.get(shot_ids[-1]) or {}).get("prompt_spec") or {} if shot_ids else {}
            expectations = dict(plot["expectations"])
            expectations.update({
                "shot_count": len(shot_ids),
                "cast": cast_rows,
                "required_visible_characters": sorted(visible_names),
                "required_visible_character_ids": sorted(visible_ids),
                "required_visible_props": sorted(props),
                "required_space_anchors": anchors,
                "space": first.get("space") or {},
                "scene_state": first.get("scene_state") or {},
                "entry_state": (first.get("action") or {}).get("start_state"),
                "required_completion_state": (last.get("action") or {}).get("completion_state"),
                "camera": first.get("camera"),
                "camera_start_framing": (unit.get("event_boundary_decision") or {}).get(
                    "boundary_class"),
                "wardrobe": wardrobe,
                "key_light": (first.get("visual_design") or {}).get("key_light"),
                "palette": (first.get("visual_design") or {}).get("palette") or {},
                "atmosphere": (first.get("visual_design") or {}).get("atmosphere"),
                "negative_prompts": negatives,
                "start_frame_reference": (anchor.get("start_frame")
                                          or {}).get("reference_path"),
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "model": "seedance-2.0-pro",
            })
            rows.append({"item_id": unit_id, "unit_id": unit_id,
                         "chronological_index": plot["chronological_index"],
                         "expectations": expectations})
        return rows

    # --------------------------------------------------------- post-gen plot
    # ------------------------------------------------------- seq=19 contract-holds
    def seq19_expectations(self, shot_ids: list[str]) -> dict[str, Any]:
        """The 'does the contract hold up' facts a reviewer needs for the seq=19 questions
        (E04 review): beat type/outcome, first antagonist action, newly introduced entities,
        declared life states, group counts and creature cards — all read from the generation
        contract + writer manifest, never inferred from media.  Empty values mean 'not declared'."""
        c = self.contract or {}
        manifest = read_json(SCRIPTS / f"{self.episode}_manifest_v1.json", {}) or {}
        ids = [str(x) for x in shot_ids]
        beat_type, outcome = "", None
        for row in manifest.get("structure") or []:
            row_shots = [str(x) for x in row.get("shot_ids") or []]
            if row_shots and set(row_shots) & set(ids):
                beat_type = str(row.get("type") or "")
                outcome = row.get("outcome")
                break
        first_actions = [g for g in c.get("antagonist_groups") or []
                         if str(g.get("first_action_shot_id")) in ids]
        new_entities = [e for e in c.get("entity_introductions") or []
                        if str(e.get("first_shot_id")) in ids]
        life_states: dict[str, dict[str, str]] = {}
        group_counts: dict[str, Any] = {}
        creature_cards: dict[str, Any] = {}
        cards = {str(r.get("entity_id")): r.get("creature_card")
                 for r in c.get("non_character_entities") or [] if r.get("creature_card")}
        for shot in c.get("shots") or []:
            sid = str(shot.get("shot_id"))
            if sid not in ids:
                continue
            spec = shot.get("prompt_spec") or {}
            for row in spec.get("cast") or []:
                if row.get("life_state"):
                    life_states.setdefault(sid, {})[str(row.get("character_id") or row.get("character"))] = str(row["life_state"])
            if shot.get("group_counts"):
                group_counts[sid] = shot["group_counts"]
            for row in spec.get("props") or []:
                pid = str(row.get("prop_id") or "")
                if pid in cards:
                    creature_cards[pid] = cards[pid]
        return {"beat_type": beat_type, "action_outcome": outcome,
                "antagonist_first_action": [{"group_id": g.get("group_id"), "member_ids": g.get("member_ids"),
                                             "motive_setup": g.get("motive_setup")} for g in first_actions],
                "new_entities": [{"entity_id": e.get("entity_id"), "setup": e.get("setup"),
                                  "payoff_shot_id": e.get("payoff_shot_id")} for e in new_entities],
                "life_states": life_states, "group_counts": group_counts,
                "creature_cards": creature_cards}

    def unit_plot_items(self) -> list[dict[str, Any]]:
        """One row per video unit: its ordered beats, cast, events and dialogue."""
        rows: list[dict[str, Any]] = []
        ordered = sorted(self.grouping_units.items(),
                         key=lambda kv: str(kv[0]))
        for index, (unit_id, unit) in enumerate(ordered, 1):
            shot_ids = [str(value) for value in unit.get("editorial_shot_ids") or []]
            beats, cast, props, dialogue = [], set(), set(), []
            for shot_id in shot_ids:
                spec = (self.shots.get(shot_id) or {}).get("prompt_spec") or {}
                action = spec.get("action") or {}
                beats.append({
                    "shot_id": shot_id,
                    "entry_state": action.get("start_state"),
                    "primary_action": action.get("primary_action"),
                    "completion_state": action.get("completion_state"),
                })
                for row in spec.get("cast") or []:
                    if row.get("character"):
                        cast.add(str(row["character"]))
                for row in spec.get("props") or []:
                    if row.get("prop"):
                        props.add(str(row["prop"]))
                if str(spec.get("dialogue") or "").strip():
                    dialogue.append({"shot_id": shot_id, "spoken_text": str(spec["dialogue"]).strip()})
            rows.append({
                "item_id": unit_id,
                "unit_id": unit_id,
                "chronological_index": index,
                "expectations": {
                    "scene_id": unit.get("scene_id"),
                    "narrative_beat": unit.get("narrative_beat"),
                    "duration_seconds": unit.get("duration_seconds"),
                    "editorial_shot_ids": shot_ids,
                    "ordered_beats": beats,
                    "principal_characters": sorted(cast),
                    "props": sorted(props),
                    "expected_dialogue": dialogue,
                    "chronological_position": f"{index} of {len(ordered)}",
                    **self.seq19_expectations(shot_ids),
                },
            })
        return rows
