#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nalu_pipeline.py — resumable, idempotent per-episode orchestrator for the
《夜无疆》(nalu) short-drama production line.

Design contract
---------------
* This tool ORCHESTRATES the engine; it never re-implements an engine check and
  it never writes a PASS / LOCKED / ADMITTED verdict of its own.  Every verdict
  in every artifact it touches has to come out of an engine tool's own report.
  Where the engine has no route for a verdict, the stage stops with
  ``ROUTE_MISSING`` and the missing route is named in the state file and in the
  checkpoint.  See ``OPEN_DECISIONS`` at the bottom of this file.
* Money.  A paid step runs only when BOTH ``--paid`` was given AND
  ``<runtime>/qingshan.json`` ``generation.paid_requests_enabled`` is true.
  Otherwise the step runs in the engine tool's own precheck / dry mode (every
  paid tool in this line has one) and the exact paid argv is printed with fully
  resolved absolute paths.  Before every paid step the budget ledger is called
  with ``--check --episode <EP> --planned-credits <N>`` and a non-zero exit is a
  HARD_STOP for the whole run.
* Idempotence.  Stage state lives in
  ``<runtime>/runtime/pipeline_state/<EP>.json``.  A stage that already reached
  PASS with an unchanged input fingerprint is SKIPPED.  Paid steps additionally
  refuse to re-submit by delegating to the engine's own durable transaction
  stores (``workflow/tasks/giggle_submit_transactions/<EP>/``,
  ``workflow/tasks/giggle_video_submit_transactions/<EP>/``) and by SHA-keyed
  cross-episode reuse in ``<runtime>/runtime/asset_library.json`` and
  ``<runtime>/runtime/voice_registry.json``.
* No platform upload, ever.  There is no publish path in this file.

Subcommands
-----------
  run     --episode E01 [--dry-run] [--paid] [--from S3] [--until S6] [--force]
  status  --episode E01 [--json]
  approve --episode E01 --by <configured-line-owner-id> [--note "..."]
  loop    --start E01 --end E10 [--paid] [--poll-seconds 60]
"""

from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import nalu_series_scope as _scope  # per-episode asset-library / registry scope (Roger 2026-09-18, E59)
import materialize_paid_authorization as _paid_order
import nalu_media_tools as _media
import nalu_policy_profile as _policy
import roger_gate_acceptance as _rga

import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# --------------------------------------------------------------------------- #
# fixed geography
# --------------------------------------------------------------------------- #
ENGINE = Path(f"{_np.ENGINE_ROOT}")
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")

VENV = Path(f"{_np.VENV_PYTHON}")
PORTABLE_AUDIO_PROVIDER = ENGINE / "tools/storyclaw_audio_provider.py"
AUDIO_TRANSACTION_ROOT = ENGINE / "workflow/tasks/giggle_audio_transactions"

CONFIG_PATH = RUNTIME / "qingshan.json"
RT = RUNTIME / "runtime"
RT_TOOLS = Path(f"{_np.TOOLS_DIR}")  # tools live with the code, not under the runtime state root (port fix 2026-09-15)
STATE_DIR = RT / "pipeline_state"
APPROVAL_DIR = STATE_DIR / "approvals"
LOG_ROOT = RT / "pipeline_logs"
BUDGET_LEDGER = RT_TOOLS / "nalu_budget_ledger.py"

# cross-episode authorities this orchestrator maintains
ASSET_LIBRARY = RT / "asset_library.json"
ASSET_LIBRARY_SEED = RT / "E01_ASSET_LIBRARY_V1.json"
VOICE_REGISTRY = RT / "voice_registry.json"
ENTITY_REGISTRY = RT / "nalu_entity_registry.json"
AGENTCUT_VOICE_POLICY = RT / "agentcut_character_voice_reference_policy_nalu.json"
CHARACTER_REGISTRY = RT / "nalu_character_asset_registry.json"  # see OPEN_DECISIONS D-1
CHARACTER_SOURCES = RT / "character_sources"
VOICE_REFS_ROOT = RT / "voice_refs"

SCRIPTS = ENGINE / "workflow/claude_writer_agent/scripts"
# Episode working artifacts may be isolated from the engine checkout.  E59 uses
# its dedicated runtime root for preproduction, media, QA and delivery so that
# no task can accidentally write into the legacy NALU-YEWUJIANG workspace.
NALU_WORK = Path(os.environ.get("NALU_WORK_ROOT", str(ENGINE / "workflow/nalu"))).resolve()
DELIVERABLES = RUNTIME / "deliverables"

SCHEMA = "nalu.pipeline_state.v1"
TOOL_ID = "nalu_pipeline.v1"

STAGE_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
STAGE_TITLES = {
    "S1": "script-ready (four layers + gate 10 + character entity contract)",
    "S2": "preproduction (build_nalu_preproduction, free)",
    "S3": "identity cards (paid, SHA-reuse across episodes)",
    "S4": "voices (paid, once per speaking character)",
    "S5": "keyframes (paid) + Q1 admission + start-frame receipts",
    "S6": "video + selective-BGM sources (paid) + post-generation QA + Q2 assembly admission",
    "S7": "Q2 verify + assembly + BGM placement/QA/mix + release loudness + final QA (no provider POST)",
    "S8": "checkpoint + block for line-owner approval",
}

# planned credits per paid stage, from runtime/budget/<EP>_cost_plan.json when
# present, else these fall-backs (E01 plan: 198 / 12 / 330 / 3500, cap 8000).
DEFAULT_PLANNED_CREDITS = {"S3": 198, "S4": 12, "S5": 330, "S6": 3500}

# statuses
PASS = "PASS"
SKIPPED = "SKIPPED_ALREADY_PASS"
DRY = "DRY_PLANNED"
BLOCKED = "BLOCKED"
ROUTE_MISSING = "ROUTE_MISSING"
HARD_STOP = "HARD_STOP_BUDGET"
#: a machine review by the Claude reviewer process is outstanding.  The stage
#: has written a review request; the session performs the review, calls
#: vlm_review_protocol.py submit, and re-runs `run`.  Exit code 4.
REVIEW_REQUIRED = "REVIEW_REQUIRED"
REVIEW_EXIT_CODE = 4
#: a generated artifact carries an AUTHORING_REQUIRED_* sentinel (D-10).  The
#: file is written so the gaps are inspectable, but a sentinel must never be
#: baked into a paid prompt, so the stage fails closed.
AUTHORING_REQUIRED = "AUTHORING_REQUIRED"

# --------------------------------------------------------------------------- #
# QA route tools (this pipeline owns these; see PIPELINE_RUNBOOK.md §5)
# --------------------------------------------------------------------------- #
VLM_PROTOCOL = RT_TOOLS / "vlm_review_protocol.py"
IDENTITY_QA_LOCK = RT_TOOLS / "identity_qa_lock.py"
KEYFRAME_Q1 = RT_TOOLS / "keyframe_q1_builder.py"
START_FRAME_EVIDENCE = RT_TOOLS / "start_frame_evidence_writer.py"
POST_GEN_QA = RT_TOOLS / "post_generation_qa_runner.py"
FINAL_QA_BUNDLE = RT_TOOLS / "final_qa_evidence_bundle.py"
FINAL_AUDIENCE_REVIEW = RT_TOOLS / "final_audience_review.py"
REVIEWS_ROOT = RT / "reviews"
REVIEWER_ID = "claude-code-nalu-vlm"
VIDEO_Q2 = RT_TOOLS / "video_q2_builder.py"          # D-7 (this pipeline owns it)

# --------------------------------------------------------------------------- #
# D-10 / D-11 generalisation tools (runtime/tools/WIRING_NOTES.md)
# --------------------------------------------------------------------------- #
AR_BUILDER = RT_TOOLS / "build_episode_asset_requirements.py"   # D-10, requirements+prompts
GSM_EXTEND = RT_TOOLS / "extend_global_space_map.py"            # D-10, global space map
PAID_AUTH = RT_TOOLS / "materialize_paid_authorization.py"      # D-11, paid authority
BUDGET_DIR = RT / "budget"
LEDGER = BUDGET_DIR / "ledger.json"
REPORTS_DIR = RT / "reports"

# --------------------------------------------------------------------------- #
# private line-owner authority — no public or historical fallback
# --------------------------------------------------------------------------- #
AUTH_ENV = {
    "orders_path": "NALU_SUPERVISOR_ORDERS_PATH",
    "paid_order_seq": "NALU_PAID_ORDER_SEQ",
    "latest_order_seq": "NALU_LATEST_ORDER_SEQ",
    "line_owner_id": "NALU_LINE_OWNER_ID",
}


def _authority_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Resolve private authority coordinates; every field is explicit and fail-closed."""
    raw = config.get("authorization") if isinstance(config.get("authorization"), dict) else {}
    values = {key: os.environ.get(env) or raw.get(
        "supervisor_orders_path" if key == "orders_path" else key)
              for key, env in AUTH_ENV.items()}
    failures: list[str] = []
    path_text = str(values["orders_path"] or "").strip()
    owner = str(values["line_owner_id"] or "").strip()
    if not path_text:
        failures.append("SUPERVISOR_ORDERS_PATH_NOT_CONFIGURED")
    if not owner:
        failures.append("LINE_OWNER_ID_NOT_CONFIGURED")
    parsed: dict[str, int | None] = {}
    for key in ("paid_order_seq", "latest_order_seq"):
        try:
            value = int(values[key])
        except (TypeError, ValueError):
            value = 0
        if value < 1:
            failures.append(f"{key.upper()}_NOT_CONFIGURED")
            parsed[key] = None
        else:
            parsed[key] = value
    orders_path = Path(path_text).expanduser() if path_text else None
    if orders_path is not None and not orders_path.is_absolute():
        failures.append("SUPERVISOR_ORDERS_PATH_MUST_BE_ABSOLUTE")
    return {
        "orders_path": orders_path,
        "paid_order_seq": parsed["paid_order_seq"],
        "latest_order_seq": parsed["latest_order_seq"],
        "line_owner_id": owner or None,
        "sources": {key: ("environment" if os.environ.get(env) else "qingshan.json")
                    for key, env in AUTH_ENV.items()},
    }, failures

# --------------------------------------------------------------------------- #
# child env the engine's video submitter needs (WIRING_NOTES.md, last section)
# --------------------------------------------------------------------------- #
#: submit_giggle_video_manifest_v2.authoritative_pipeline_tools_dir() looks for
#: <project-root>/tools/production_video_submission_gate.py and dies with
#: "Production video gate is unavailable" BEFORE any manifest validation when it
#: is absent.  The gate lives in the engine clone, so both the submitter and the
#: poll tool get the engine's tools dir explicitly.
VIDEO_SUBMIT_ENV = {"BACKLOT_PIPELINE_TOOLS_DIR": str(ENGINE / "tools")}

TERMINAL_OK = {PASS, SKIPPED}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str | None:
    if not path or not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def q(argv: Iterable[Any]) -> str:
    return " ".join(shlex.quote(str(item)) for item in argv)


def writer_selfcheck_admitted(report: dict[str, Any], exit_code: int) -> bool:
    """Apply the selected profile to the writer's own S1 declaration.

    Current portable projects require an explicitly enforced PASS. Historical
    replay preserves the recorded opt-in behavior for old contracts.
    """
    if _policy.is_current():
        return (
            exit_code == 0
            and report.get("enforced") is True
            and report.get("status") == PASS
        )
    return not (report.get("enforced") and report.get("status") == "FAIL")


def episode_index(episode: str) -> int:
    match = re.fullmatch(r"E(\d{2,3})", episode)
    if not match:
        raise SystemExit(f"episode must look like E01: {episode!r}")
    return int(match.group(1))


def episode_range(start: str, end: str) -> list[str]:
    lo, hi = episode_index(start), episode_index(end)
    if hi < lo:
        raise SystemExit(f"--end {end} precedes --start {start}")
    width = max(len(start) - 1, len(end) - 1)
    return [f"E{index:0{width}d}" for index in range(lo, hi + 1)]


# --------------------------------------------------------------------------- #
# per-episode geography
# --------------------------------------------------------------------------- #
class Paths:
    """Every path this pipeline touches, resolved absolutely, for one episode."""

    def __init__(self, episode: str, layers: dict[str, Path] | None = None) -> None:
        self.episode = episode
        #: Roger 2026-09-18: every cross-episode registry/library path comes from the
        #: episode's series scope (runtime/series_scopes.json).  E01–E05 resolve to the
        #: historical NALU-YEWUJIANG paths; E59 resolves to series/qingshan_e59/ only.
        self.scope = _scope.resolve_scope(episode)
        # S1 — the four authored layers
        self.narrative = SCRIPTS / f"{episode}_NARRATIVE_CANONICAL_v1.md"
        self.directing = SCRIPTS / f"{episode}_DIRECTING_SCRIPT_v1.md"
        self.contract = SCRIPTS / f"{episode}_GENERATION_CONTRACT_v1.json"
        self.writer_manifest = SCRIPTS / f"{episode}_manifest_v1.json"
        #: Roger 2026-09-18 (E59 v4 adapter): the four layers may be handed in explicitly
        #: (--layers-dir / --narrative / --directing / --contract / --manifest) instead of the
        #: fixed *_v1 slot names; the choice is persisted in the state file (layers) and reused.
        self.layers_source = "DEFAULT_V1_SLOTS"
        if layers:
            self.narrative = Path(layers.get("narrative_canonical") or self.narrative)
            self.directing = Path(layers.get("directing_script") or self.directing)
            self.contract = Path(layers.get("generation_contract") or self.contract)
            self.writer_manifest = Path(layers.get("writer_manifest") or self.writer_manifest)
            self.layers_source = "EXPLICIT"
        self.gate10 = ENGINE / "agent_factory/claude_writer_v2/gates/writer_scene_source_declaration_gate.py"

        # runtime preproduction inputs (per-episode; D-10 generates them)
        self.rt_pre = RUNTIME / "preproduction" / episode
        self.gsm_own = self.rt_pre / "global_space_map.json"
        self.gsm_e01 = RUNTIME / "preproduction/E01/global_space_map.json"
        index = episode_index(episode)
        self.previous_episode = f"E{index - 1:02d}" if index > 1 else None
        #: base for extend_global_space_map.py — the PREVIOUS episode's locked GSM
        #: when it exists (so every episode inherits the whole accumulated series
        #: map, not just E01's), else E01's.
        self.gsm_prev = (RUNTIME / "preproduction" / self.previous_episode
                         / "global_space_map.json") if self.previous_episode else None
        self.asset_requirements = self.rt_pre / "asset_requirements.json"
        # Optional migration evidence from the prior local line.  It is only
        # consumed to recover authored internal transitions omitted by v4;
        # absent means the normal fail-closed path remains unchanged.
        self.legacy_grouping_plan = RUNTIME / "runtime" / "adapter" / episode / f"{episode}_LEGACY_GROUPING_PLAN.json"
        self.asset_requirements_report = self.rt_pre / "asset_requirements_build_report.json"
        self.prompt_dir = self.rt_pre / "prompts"
        #: the authored-prose overlay build_episode_asset_requirements.py takes.
        #: `asset_requirements_overlay.json` is the name its own --overlay-out
        #: extractor writes (E01's was produced that way); `overlay.json` is
        #: accepted as an alias so a hand-placed overlay is still picked up.
        self.overlay_primary = self.rt_pre / "asset_requirements_overlay.json"
        self.overlay_alias = self.rt_pre / "overlay.json"
        self.space_map_assets = self.rt_pre / "space_map_assets"
        self.rt_pre_reports = self.rt_pre / "reports"
        self.gsm_extension_report = self.rt_pre_reports / f"global_space_map_extension_{episode}.json"
        self.gsm_gate_report = self.rt_pre_reports / f"global_space_layout_gate_{episode}.json"

        # engine-side working tree (gitignored)
        self.work = NALU_WORK / episode
        self.preprod = self.work / "preproduction"
        self.preprod_reports = self.preprod / "reports"
        self.keyframes = self.preprod / "keyframes"
        self.identity = self.work / "identity"
        self.voice = self.work / "voice"
        self.video_media = self.work / "video"
        self.assembly = self.work / "assembly"

        prefix = f"{episode}_"
        self.preprod_report = self.preprod / f"{prefix}PREPRODUCTION_REPORT.json"
        self.editorial = self.preprod / f"{prefix}EDITORIAL_SEEDANCE_MANIFEST_V1.json"
        self.grouping_plan = self.preprod / f"{prefix}VIDEO_UNIT_GROUPING_PLAN_V1.json"
        self.anchor_plan = self.preprod / f"{prefix}VIDEO_UNIT_ANCHOR_PLAN_V1.json"
        self.start_frames = self.preprod / f"{prefix}START_FRAME_SEMANTIC_CONTRACTS_V1.json"
        self.start_frame_evidence = self.preprod_reports / "start_frame_evidence"
        self.video_transaction = self.preprod / f"{prefix}VIDEO_TRANSACTION_MANIFEST_V1.json"
        self.grouped_seedance = self.preprod / f"{prefix}GROUPED_SEEDANCE_MANIFEST_V1.json"
        self.machine_gate_bundle = self.preprod / f"{prefix}MACHINE_GATE_REPORTS_V1.json"

        # S3 identity
        self.identity_library = self.identity / "asset_library.json"
        self.identity_library_gate = self.identity / "asset_library_gate.json"
        self.identity_plan = self.identity / "character_asset_plan.json"
        self.identity_match = self.identity / "source_match_report.json"
        self.identity_report = self.identity / "bootstrap_report.json"
        self.identity_submit = self.identity / f"{prefix}IDENTITY_SUBMIT_REPORT.json"
        self.identity_harvest_dir = self.identity / "plates"
        self.identity_harvest_status = self.identity / f"{prefix}IDENTITY_HARVEST_STATUS.json"
        self.identity_admission = self.identity / f"{prefix}IDENTITY_ADMISSION.json"

        # S4 voice
        self.speech_payloads = self.voice / "speech_task_payloads.json"
        self.voice_report = self.voice / "voice_bootstrap_report.json"
        self.voice_upload_dir = self.voice / "uploads"
        self.voice_refs = self.scope["voice_refs"]

        # S5 keyframes
        self.keyframe_manifest = self.preprod / f"{prefix}KEYFRAME_IMAGE_MANIFEST_V1.json"
        self.keyframe_manifest_report = self.preprod / f"{prefix}KEYFRAME_IMAGE_MANIFEST_V1_report.json"
        self.keyframe_submit = self.preprod_reports / f"{prefix}KEYFRAME_SUBMIT_REPORT.json"
        self.keyframe_harvest_dir = self.preprod / "keyframe_harvest"
        self.keyframe_harvest_status = self.preprod_reports / f"{prefix}KEYFRAME_HARVEST_STATUS.json"
        self.keyframe_entry_gate = self.preprod_reports / f"{prefix}KEYFRAME_ENTRY_STATE_GATE.json"
        self.keyframe_admission = self.preprod_reports / f"{prefix}KEYFRAME_ADMISSION_Q1.json"

        # S6 video
        self.video_preflight = self.preprod_reports / f"{prefix}VIDEO_PREFLIGHT_V1.json"
        self.video_submit = self.preprod_reports / f"{prefix}VIDEO_SUBMIT_V1.json"
        self.video_remote_status = self.preprod_reports / f"{prefix}VIDEO_REMOTE_STATUS_V1.json"
        self.postgen_qa = self.preprod_reports / f"{prefix}POST_GENERATION_QA_SCOPE.json"
        self.efficiency = self.preprod_reports / f"{prefix}PRODUCTION_EFFICIENCY_V1.json"

        # S6.q2 / S7 Q2 VIDEO_ASSEMBLY admission (D-7)
        self.qa_root = self.preprod_reports / "qa"
        self.postgen_dir = self.qa_root / "post_generation"
        self.postgen_summary = self.postgen_dir / f"{prefix}POST_GENERATION_QA_SUMMARY.json"
        self.q2_dir = self.qa_root / "q2"
        self.q2_index = self.q2_dir / f"{prefix}VIDEO_Q2_INDEX.json"

        # S7 assembly
        self.picture_native = self.assembly / f"{prefix}picture_native.mp4"
        self.agentcut_project = self.assembly / f"{prefix}agentcut_project.json"
        self.agentcut_admission = self.assembly / f"{prefix}agentcut_admission.json"
        self.leveled_audio_report = self.assembly / f"{prefix}NATIVE_AUDIO_LOUDNESS.json"
        self.render_dry = self.assembly / f"{prefix}RENDER_DRYRUN.json"

        # deliverables
        self.deliver = DELIVERABLES / episode
        self.final_mp4 = self.deliver / f"{episode}_final_9x16.mp4"
        self.qa_report = self.deliver / f"{episode}_QA_REPORT.json"
        self.checkpoint = self.deliver / "CHECKPOINT.md"

        # bookkeeping
        self.state = STATE_DIR / f"{episode}.json"
        self.approval = APPROVAL_DIR / f"{episode}.APPROVED.json"
        self.logs = LOG_ROOT / episode

    @property
    def gsm(self) -> Path:
        """This episode's own locked global space map.

        D-10 generates it before S2 with ``extend_global_space_map.py``, so for a
        wired run this is always ``gsm_own``.  The fall-backs exist only so a
        diagnostic run of S2 on an episode whose pre-step has not been run yet
        still names a real authority: the previous episode's map first (it is a
        superset of E01's), then E01's.
        """
        if self.gsm_own.is_file():
            return self.gsm_own
        if self.gsm_prev is not None and self.gsm_prev.is_file():
            return self.gsm_prev
        return self.gsm_e01

    @property
    def overlay(self) -> Path | None:
        """The authored-prose overlay for this episode, if one exists."""
        for candidate in (self.overlay_primary, self.overlay_alias):
            if candidate.is_file():
                return candidate
        return None

    def layers(self) -> dict[str, Path]:
        return {
            "narrative_canonical": self.narrative,
            "directing_script": self.directing,
            "generation_contract": self.contract,
            "writer_manifest": self.writer_manifest,
        }


# --------------------------------------------------------------------------- #
# context: config, state, logging, subprocess, budget
# --------------------------------------------------------------------------- #
class StageResult:
    def __init__(self, status: str, **details: Any) -> None:
        self.status = status
        self.details: dict[str, Any] = details
        self.steps: list[dict[str, Any]] = []
        self.receipts: list[str] = []
        self.planned_credits = 0
        self.blockers: list[str] = []

    @property
    def ok(self) -> bool:
        return self.status in TERMINAL_OK


def explicit_layers_from_args(episode: str, args: argparse.Namespace) -> dict[str, Path] | None:
    """--layers-dir <dir> (the four <EP>_*_v1 names inside it) and/or the four explicit paths."""
    out: dict[str, Path] = {}
    layers_dir = getattr(args, "layers_dir", None)
    if layers_dir:
        base = Path(layers_dir).expanduser().resolve()
        out = {"narrative_canonical": base / f"{episode}_NARRATIVE_CANONICAL_v1.md",
               "directing_script": base / f"{episode}_DIRECTING_SCRIPT_v1.md",
               "generation_contract": base / f"{episode}_GENERATION_CONTRACT_v1.json",
               "writer_manifest": base / f"{episode}_manifest_v1.json"}
    for key, attr in (("narrative_canonical", "narrative"), ("directing_script", "directing"),
                      ("generation_contract", "contract"), ("writer_manifest", "manifest")):
        value = getattr(args, attr, None)
        if value:
            out[key] = Path(value).expanduser().resolve()
    return out or None


def project_scope_check(
    ctx: "Ctx", *, require_preproduction_map: bool = True
) -> dict[str, Any]:
    """Roger 2026-09-18 (E59): the asset library this episode will reuse from must belong to the
    episode's project (asset_library.project_id == scope series_id) and, for a non-default scope,
    the episode's own global space map must exist, be LOCKED and map every contract scene.
    The default NALU-YEWUJIANG scope keeps its historical library (project_id NALU-YEWUJIANG)."""
    scope = ctx.p.scope
    failures: list[str] = []
    lib_path = scope["asset_library"] if scope["asset_library"].is_file() else scope["asset_library_seed"]
    library = read_json(lib_path, {}) or {}
    project_id = library.get("project_id")
    if project_id != scope["series_id"]:
        failures.append(f"ASSET_LIBRARY_PROJECT_MISMATCH:{project_id}!={scope['series_id']}")
    detail: dict[str, Any] = {"scope_id": scope["scope_id"], "series_id": scope["series_id"], "asset_library": str(lib_path),
                              "asset_library_project_id": project_id, "default_scope": scope["is_default"]}
    if not scope["is_default"]:
        series_root = Path(scope["series_root"]).resolve()

        def within(path: Path | str, root: Path) -> bool:
            try:
                Path(path).resolve().relative_to(root)
                return True
            except ValueError:
                return False

        # These are private, mutable production authorities.  A foreign series
        # must keep every one below its declared series_root.  Checking the path
        # structure catches both ``nalu_runtime`` and StoryClaw's
        # ``nalu-runtime`` (and any future mount name); host-specific substrings
        # cannot provide that guarantee.
        scoped_authorities = (
            "asset_library", "asset_library_seed",
            "voice_registry", "voice_catalog", "voice_cast", "voice_refs",
            "entity_registry", "agentcut_voice_policy",
            "character_registry", "character_sources",
        )
        path_authority: dict[str, str] = {}
        for key in scoped_authorities:
            value = Path(scope[key]).resolve()
            path_authority[key] = str(value)
            if not within(value, series_root):
                failures.append(f"SCOPE_PATH_OUTSIDE_SERIES_ROOT:{key}:{value}")
            default_rel = _scope.DEFAULT_PATHS.get(key)
            if isinstance(default_rel, str) and not default_rel.startswith("tools:"):
                default_path = (RUNTIME / default_rel).resolve()
                if value == default_path:
                    failures.append(f"SCOPE_PATH_REUSES_DEFAULT_AUTHORITY:{key}:{value}")

        # A lexicon may be a public, versioned runtime config shared by all
        # series, or a private file under series_root.  A charter may likewise
        # be a versioned engine document or private series state.  These are
        # read-only policy inputs, never mutable identity/asset authorities.
        public_config_root = (Path(_np.TOOLS_DIR).parent / "configs").resolve()
        engine_root = Path(_np.ENGINE_ROOT).resolve()
        scope_episode = getattr(ctx, "episode", None) or getattr(ctx.p, "episode", None)
        writer_lexicon_root = (
            (RUNTIME / "writer_layers" / str(scope["scope_id"]) / str(scope_episode)).resolve()
            if scope_episode else None
        )
        lexicon = Path(scope["lexicon"]).resolve()
        path_authority["lexicon"] = str(lexicon)
        if not (
            within(lexicon, series_root)
            or within(lexicon, public_config_root)
            or (writer_lexicon_root is not None and within(lexicon, writer_lexicon_root))
        ):
            failures.append(f"SCOPE_LEXICON_OUTSIDE_ALLOWED_ROOTS:{lexicon}")
        charter = scope.get("charter")
        if charter is not None:
            charter_path = Path(charter).resolve()
            path_authority["charter"] = str(charter_path)
            if not (within(charter_path, series_root) or within(charter_path, engine_root)):
                failures.append(f"SCOPE_CHARTER_OUTSIDE_ALLOWED_ROOTS:{charter_path}")
        detail["series_root"] = str(series_root)
        detail["scope_path_authorities"] = path_authority
        lexicon_data = read_json(lexicon, {}) or {}
        detail["lexicon_status"] = lexicon_data.get("status")
        if lexicon_data.get("status") == "EMPTY_PENDING_SCRIPT_DERIVATION":
            failures.append("PROJECT_LEXICON_NOT_DERIVED_FROM_SCRIPT")

        # S1 is the script gate.  A new project's first global space map is an
        # S2 output, so requiring it during S1 makes a clean installation
        # impossible to start.  Historical callers and focused integrity tests
        # retain the strict default; stage_s1 opts out, while S2's real map
        # renderer/layout gate validates the generated authority before use.
        if require_preproduction_map:
            gsm = read_json(ctx.p.gsm_own, {}) or {}
            detail["global_space_map"] = str(ctx.p.gsm_own)
            detail["global_space_map_status"] = gsm.get("status")
            if not gsm:
                failures.append("GLOBAL_SPACE_MAP_MISSING")
            else:
                if gsm.get("status") != "LOCKED":
                    failures.append(f"GLOBAL_SPACE_MAP_NOT_LOCKED:{gsm.get('status')}")
                mapped = {m.get("scene_id") for sm in (gsm.get("space_maps") or []) for m in (sm.get("scene_mappings") or [])}
                contract = read_json(ctx.p.contract, {}) or {}
                unmapped = sorted({s.get("scene_id") for s in (contract.get("scene_states") or [])} - mapped)
                detail["scenes_unmapped"] = unmapped
                if unmapped:
                    failures.append("GLOBAL_SPACE_MAP_SCENES_UNMAPPED:" + ",".join(map(str, unmapped)))
    detail["status"] = PASS if not failures else "FAIL"
    detail["failures"] = failures
    return detail


class Ctx:
    def __init__(self, episode: str, args: argparse.Namespace) -> None:
        self.episode = episode
        self.args = args
        self.p = Paths(episode)
        layers = explicit_layers_from_args(episode, args)
        layers_source = "CLI" if layers else None
        if not layers:
            remembered = (read_json(self.p.state, {}) or {}).get("layers") or {}
            if remembered.get("paths"):
                layers = {k: Path(v) for k, v in remembered["paths"].items()}
                layers_source = "STATE"
        if layers:
            self.p = Paths(episode, layers)
            self.p.layers_source = layers_source or "EXPLICIT"
        self.dry = bool(getattr(args, "dry_run", False))
        self.want_paid = bool(getattr(args, "paid", False))
        self.force = bool(getattr(args, "force", False))
        self.config = read_json(CONFIG_PATH, {}) or {}
        gen = self.config.get("generation") or {}
        self.config_paid_enabled = bool(gen.get("paid_requests_enabled"))
        self.storyclaw_paid_enabled = bool(
            (self.config.get("storyclaw") or {}).get("paid_requests_enabled")
        )
        self.max_parallel = int(gen.get("max_parallel_tasks") or 6)
        self.cap = int(
            gen.get("budget_cap_credits_per_episode")
            or gen.get("budget_credits_per_episode_cap")
            or 8000
        )
        portable_paid_lock = (
            self.storyclaw_paid_enabled if _policy.is_current() else True
        )
        self.paid_enabled = (
            self.want_paid and self.config_paid_enabled
            and portable_paid_lock and not self.dry
        )
        self.cost_plan = read_json(RT / "budget" / f"{episode}_cost_plan.json", {}) or {}
        self.authority, self.authority_blockers = _authority_config(self.config)
        self.paid_order: dict[str, Any] | None = None
        if not self.authority_blockers:
            try:
                self.paid_order = _paid_order.read_order(
                    self.authority["orders_path"], self.authority["paid_order_seq"],
                    episode, self.cap,
                    expected_owner=self.authority["line_owner_id"],
                    expected_latest_seq=self.authority["latest_order_seq"],
                    engine_root=ENGINE,
                    require_private=True,
                )
            except _paid_order.Refused as exc:
                self.authority_blockers.append(str(exc))
        order = self.paid_order or {}
        self.rights_basis = str(order.get("rights_basis") or "")
        self.rights_declaration = {
            "basis": self.rights_basis or None,
            "declared_by": order.get("rights_declared_by"),
            "declared_on": (order.get("source_receipt") or {}).get("recorded_at_utc"),
            "declaration_type": "LINE_OWNER_DECLARATION_NOT_A_REVIEWER_OBSERVATION",
            "authority": order.get("orders_file") or (str(self.authority.get("orders_path"))
                                                        if self.authority.get("orders_path") else None),
            "order_seq": order.get("seq") or self.authority.get("paid_order_seq"),
            "order_id": order.get("id"),
            "conditions": order.get("condition_ids") or [],
            "scope": order.get("rights_scope") or order.get("episode_scope"),
            "not_covered": (None if order.get("publication_allowed")
                            else "platform publication is not authorised by this paid-production order"),
            "source_receipt": order.get("source_receipt"),
            "validation": "PASS" if self.paid_order else "BLOCKED",
            "validation_failures": list(self.authority_blockers),
            "consumed_by": ["bootstrap_identity_cards.py --rights-basis",
                            "identity_qa_lock.py lock --rights-basis"],
        }
        self.p.logs.mkdir(parents=True, exist_ok=True)
        self.run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            + f"_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        )
        self.run_log = self.p.logs / f"run_{self.run_id}.log"
        self.state = self.load_state()
        self.planned_commands: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- logging
    def log(self, line: str) -> None:
        stamped = f"[{now()}] {line}"
        print(stamped, flush=True)
        with open(self.run_log, "a", encoding="utf-8") as handle:
            handle.write(stamped + "\n")

    def say(self, line: str) -> None:
        """Operator-facing line that is also logged."""
        self.log(line)

    # ------------------------------------------------------------------ state
    def load_state(self) -> dict[str, Any]:
        existing = read_json(self.p.state)
        if isinstance(existing, dict) and existing.get("schema") == SCHEMA:
            for sid in STAGE_IDS:
                existing.setdefault("stages", {}).setdefault(sid, blank_stage(sid))
            return existing
        return {
            "schema": SCHEMA,
            "episode": self.episode,
            "created_at": now(),
            "updated_at": now(),
            "tool": TOOL_ID,
            "current_stage": STAGE_IDS[0],
            "overall_status": "NOT_STARTED",
            "cap_credits": self.cap,
            "credits": {"planned_by_stage": {}, "recorded_total": 0, "cap": self.cap},
            "approval": {"status": "PENDING", "approved_at": None, "by": None, "note": None},
            "runs": [],
            "stages": {sid: blank_stage(sid) for sid in STAGE_IDS},
            "open_decisions": [],
        }

    def save_state(self) -> None:
        self.state["updated_at"] = now()
        write_json(self.p.state, self.state)

    def stage_state(self, sid: str) -> dict[str, Any]:
        return self.state.setdefault("stages", {}).setdefault(sid, blank_stage(sid))

    # ---------------------------------------------------------------- env
    def child_env(self, *, paid: bool,
                  extra: dict[str, str] | None = None) -> dict[str, str]:
        """Environment for engine child processes.

        The four QINGSHAN_* names come from
        runtime/engine_patches/e09_nalu_entity_registry_extension.diff — they
        relocate the qingshan-line tenant authority files onto the nalu line's
        own files, and QINGSHAN_ENTITY_REGISTRY additively registers the nalu
        cast so the multimodal binding guard APPLIES to them (it cannot exempt
        them).  GIGGLE_API_KEY is stripped from every non-paid child so a free
        step physically cannot reach a paid endpoint.
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ENGINE)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        env["QINGSHAN_VOICE_REGISTRY"] = str(self.p.scope["voice_registry"])
        env["QINGSHAN_ENTITY_REGISTRY"] = str(self.p.scope["entity_registry"])
        env["QINGSHAN_AGENTCUT_VOICE_POLICY"] = str(self.p.scope["agentcut_voice_policy"])
        if not _policy.uses_legacy_first_episode_exception(self.episode):
            # engine patch e16 (seq=7 PACING_E02_PLUS): grouped video units prefer 4-6 s, never above 7 s
            policy = self.p.scope.get("unit_duration_policy") or {}
            preferred = policy.get("preferred_seconds") or "4,6"
            env["QINGSHAN_UNIT_PREFERRED_SECONDS"] = ",".join(map(str, preferred)) if isinstance(preferred, (list, tuple)) else str(preferred)
            env["QINGSHAN_UNIT_MAX_SECONDS"] = str(policy.get("max_seconds") or 8)
            env["QINGSHAN_UNIT_MIN_SECONDS"] = str(policy.get("min_seconds") or 4)
        if self.p.scope["character_registry"].is_file():
            env["QINGSHAN_CHARACTER_REGISTRY"] = str(self.p.scope["character_registry"])
        if paid:
            # giggle_api_client.py:117-130 refuses every /api/v1/generation/ POST
            # unless a durable-submitter context is declared.  Set only for a
            # genuinely paid step, never for a precheck.
            env["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
        else:
            env.pop("GIGGLE_API_KEY", None)
            env.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        for key, value in (extra or {}).items():
            env[str(key)] = str(value)
        return env

    # ---------------------------------------------------------------- runner
    def run(self, argv: list[Any], *, name: str, paid: bool = False,
            cwd: Path = ENGINE, timeout: int | None = 3600,
            check: bool = False,
            extra_env: dict[str, str] | None = None) -> dict[str, Any]:
        argv = [str(item) for item in argv]
        log_path = self.p.logs / f"{self.run_id}_{name}.log"
        self.log(f"$ {q(argv)}")
        if extra_env:
            self.log("  env " + " ".join(f"{key}={value}" for key, value in
                                         sorted(extra_env.items())))
        started = now()
        try:
            completed = subprocess.run(
                argv, cwd=str(cwd), env=self.child_env(paid=paid, extra=extra_env),
                capture_output=True, text=True, timeout=timeout)
            rc, out, err = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            rc, out, err = 124, exc.stdout or "", f"TIMEOUT after {timeout}s"
        except OSError as exc:
            rc, out, err = 127, "", f"{type(exc).__name__}: {exc}"
        log_path.write_text(
            f"# {started}\n# cwd={cwd}\n# paid={paid}\n# argv={q(argv)}\n"
            f"# exit={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n", encoding="utf-8")
        step = {
            "name": name, "argv": argv, "argv_shell": q(argv), "cwd": str(cwd),
            "extra_env": dict(extra_env or {}),
            "paid": paid, "exit_code": rc, "log": str(log_path),
            "started_at": started, "finished_at": now(),
            "stdout_tail": tail(out), "stderr_tail": tail(err),
        }
        self.log(f"  -> exit={rc} log={log_path.name}")
        if check and rc != 0:
            step["fatal"] = True
        return step

    # ---------------------------------------------------------------- budget
    def budget_check(self, planned_credits: int, *, label: str) -> dict[str, Any]:
        """MANDATORY before every paid step.  Non-zero exit == HARD_STOP."""
        bgm_transactions = selective_bgm_transaction_dir(self)
        step = self.run(
            [VENV, BUDGET_LEDGER, "--check", "--episode", self.episode,
             "--planned-credits", int(planned_credits),
             "--bgm-transactions-dir", bgm_transactions,
             "--cap", self.cap, "--out",
             self.p.logs / f"{self.run_id}_budget_{label}.json"],
            name=f"budget_check_{label}", paid=False)
        verdict = {}
        for line in (step.get("stdout_tail") or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                verdict = json.loads(line)
        step["budget_verdict"] = verdict
        return step

    def planned_credits(self, sid: str) -> int:
        plan = self.cost_plan.get("first_pass") or {}
        mapping = {"S3": "identity_credits", "S4": "voice_credits",
                   "S5": "keyframe_credits", "S6": "video_credits"}
        key = mapping.get(sid)
        if key and isinstance(plan.get(key), (int, float)):
            return int(plan[key])
        return DEFAULT_PLANNED_CREDITS.get(sid, 0)

    # ------------------------------------------------------- paid dispatcher
    def paid_step(self, argv: list[Any], *, name: str, sid: str,
                  planned_credits: int, dry_argv: list[Any] | None = None,
                  note: str = "",
                  extra_env: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
        """Run a paid step, or its precheck twin plus a printed plan.

        Returns (status, step).  status is PASS / DRY / HARD_STOP / BLOCKED.
        """
        argv = [str(item) for item in argv]
        paid_env = dict(extra_env or {})
        if _policy.is_current() and self.config_paid_enabled and self.storyclaw_paid_enabled:
            paid_env.setdefault("NALU_PAID_CONFIG_LOCK", "1")
        if self.paid_order:
            paid_env.setdefault("NALU_PAID_AUTHORIZATION_REF", str(self.paid_order["id"]))
            paid_env.setdefault("NALU_PAID_ORDER_SEQ", str(self.paid_order["seq"]))
            paid_env.setdefault("NALU_SUPERVISOR_ORDERS_SHA256",
                                str(self.paid_order["orders_file_sha256"]))
        record = {
            "stage": sid, "step": name, "planned_credits": planned_credits,
            "paid_argv": argv, "paid_command": q(argv), "note": note,
            "env": paid_env,
            "requires": "export GIGGLE_API_KEY=… ; --paid ; "
                        "qingshan.json generation.paid_requests_enabled=true",
        }
        self.planned_commands.append(record)

        if self.paid_enabled and (self.authority_blockers or not self.paid_order
                                  or sid not in (self.paid_order.get("paid_stages") or [])):
            failures = list(self.authority_blockers)
            if self.paid_order and sid not in (self.paid_order.get("paid_stages") or []):
                failures.append(f"ORDER_DOES_NOT_AUTHORIZE_PAID_STAGE:{sid}")
            self.say("!! BLOCKED paid authority refused " + name + ": " + "; ".join(failures))
            return BLOCKED, {
                "name": name, "paid": True, "status": BLOCKED, "exit_code": 5,
                "blocker": "PAID_AUTHORITY_NOT_VALID_FOR_STAGE", "failures": failures,
                "argv": argv, "argv_shell": q(argv), "planned_credits": planned_credits,
            }

        budget = self.budget_check(planned_credits, label=name)
        verdict = budget.get("budget_verdict") or {}
        if budget["exit_code"] != 0:
            self.say(f"!! HARD_STOP budget guard refused {name}: "
                     f"{json.dumps(verdict, ensure_ascii=False)}")
            return HARD_STOP, budget
        self.say(f"   budget ok: planned={planned_credits} "
                 f"projected={verdict.get('projected_total_credits')} "
                 f"cap={verdict.get('cap_credits')}")

        if not self.paid_enabled:
            reason = ("--dry-run" if self.dry else
                      "--paid not given" if not self.want_paid else
                      "qingshan.json generation.paid_requests_enabled=false")
            self.say(f"   PAID STEP NOT EXECUTED ({reason}).  Exact command:")
            for key, value in sorted(paid_env.items()):
                self.say(f"     export {key}={value}")
            self.say(f"     {q(argv)}")
            step = {"name": name, "paid": True, "status": DRY,
                    "reason_not_run": reason, "argv": argv, "argv_shell": q(argv),
                    "extra_env": paid_env,
                    "planned_credits": planned_credits, "budget": budget}
            if dry_argv:
                twin = self.run(dry_argv, name=f"{name}_precheck", paid=False,
                                extra_env=paid_env)
                step["precheck"] = twin
            return DRY, step

        step = self.run(argv, name=name, paid=True, extra_env=paid_env)
        step["planned_credits"] = planned_credits
        step["budget"] = budget
        return (PASS if step["exit_code"] == 0 else BLOCKED), step


# --------------------------------------------------------------------------- #
# D-11 — paid authorisation, immediately before every paid submit
# --------------------------------------------------------------------------- #
def materialised_path(target: Path, suffix: str = "_PAID_AUTHORIZED") -> Path:
    """Where materialize_paid_authorization.py writes its copy (its target_path)."""
    target = Path(target)
    return target.parent / f"{target.stem}{suffix}{target.suffix}"


def paid_authorization_argv(ctx: Ctx, *, sid: str, target: Path, is_plan: bool,
                            task_keys: list[str] | None = None) -> list[Any]:
    if ctx.authority_blockers or not ctx.paid_order:
        raise ValueError("paid authority is not configured and validated")
    argv: list[Any] = [
        VENV, PAID_AUTH,
        "--episode", ctx.episode,
        "--stage", sid,
        "--orders", ctx.authority["orders_path"],
        "--order-seq", ctx.authority["paid_order_seq"],
        "--expected-latest-seq", ctx.authority["latest_order_seq"],
        "--line-owner-id", ctx.authority["line_owner_id"],
        "--cap", str(ctx.cap),
        ("--plan" if is_plan else "--manifest"), target,
        "--ledger", LEDGER,
        "--report", REPORTS_DIR / f"{ctx.episode}_paid_authorization_{sid.lower()}.json",
    ]
    # D-46 (2026-09-16 22:02Z): restrict the authorised copy to the tasks that still NEED a POST.
    # Without this a wave re-entry whose fingerprints changed (regenerated finalization receipts)
    # re-posted five units that already had clips on disk (680 cr, ~560 wasted).
    for key in task_keys or []:
        argv += ["--task-key", key]
    return argv


def materialize_paid_authorization(ctx: Ctx, res: StageResult, *, sid: str,
                                  target: Path, is_plan: bool,
                                  note: str = "", task_keys: list[str] | None = None) -> tuple[str, Path, dict[str, Any]]:
    """Turn the deployment-configured line-owner order into paid authority fields.

    Runs IMMEDIATELY before the paid submit, on the plan / manifest that is about
    to be submitted, and returns the path of the materialised ``_PAID_AUTHORIZED``
    copy — which is what the submitter is then given.  The original file is never
    edited (no ``--in-place``), so the un-authorised artifact stays on disk as
    evidence of what was compiled.

    What it sets (WIRING_NOTES §3): ``provider_post_allowed: true``,
    ``maximum_new_submissions``, a real ``authorization_ref`` (the order id),
    ``READY_TO_SUBMIT`` per selected task, a ``paid_authorization`` provenance
    block, and EXACTLY ONE ``GIGGLE-REROLL-COST-GUARD`` report in
    ``machine_gate_reports`` bound to the materialised manifest's own byte SHA —
    which is what ``submit_giggle_image_manifest.validate_submission_authority``
    demands and what ``--precheck-only`` SKIPS.

    In a dry run it is NOT executed: it appends to the real credit ledger through
    ``nalu_budget_ledger.py --check`` and it writes real authority files, so a
    rehearsal only PRINTS it.  ``provider_post_allowed: true`` in a file is still
    only ONE of the locks — ``--paid`` and ``qingshan.json
    generation.paid_requests_enabled`` remain independently required.

    Returns (status, materialised_path, record).  status is PASS / DRY / BLOCKED.
    """
    out = materialised_path(target)
    record: dict[str, Any] = {
        "decision": "D-11",
        "stage": sid,
        "tool": str(PAID_AUTH),
        "order_seq": ctx.authority.get("paid_order_seq"),
        "latest_order_seq": ctx.authority.get("latest_order_seq"),
        "order_id": (ctx.paid_order or {}).get("id"),
        "line_owner_id": ctx.authority.get("line_owner_id"),
        "orders_path": (str(ctx.authority.get("orders_path"))
                         if ctx.authority.get("orders_path") else None),
        "input": str(target),
        "input_sha256": sha256_file(target) if target.is_file() else None,
        "materialised": str(out),
        "sets": ["provider_post_allowed=true", "authorization_ref=<order id>",
                 "maximum_new_submissions=len(selected tasks)",
                 "status=READY_TO_SUBMIT per task",
                 "exactly one GIGGLE-REROLL-COST-GUARD report bound to the "
                 "materialised file's own sha256"],
        "second_lock_still_required": "--paid AND qingshan.json "
                                      "generation.paid_requests_enabled=true",
        "note": note,
    }
    if ctx.authority_blockers or not ctx.paid_order:
        record["status"] = BLOCKED if ctx.paid_enabled else DRY
        record["blocker"] = "PAID_AUTHORITY_CONFIGURATION_INVALID"
        record["authority_failures"] = list(ctx.authority_blockers)
        ctx.say("   !! D-11 paid authority is not configured and validated: "
                + "; ".join(ctx.authority_blockers))
        return record["status"], out, record
    argv = paid_authorization_argv(ctx, sid=sid, target=target, is_plan=is_plan,
                                   task_keys=task_keys)
    record["argv"] = [str(item) for item in argv]
    record["command"] = q(argv)
    if not target.is_file():
        record["status"] = BLOCKED
        record["blocker"] = f"PAID_AUTHORIZATION_INPUT_MISSING:{target}"
        ctx.say(f"   !! D-11 cannot authorise a file that does not exist: {target}")
        return BLOCKED, out, record

    if not ctx.paid_enabled:
        reason = ("--dry-run" if ctx.dry else
                  "--paid not given" if not ctx.want_paid else
                  "qingshan.json generation.paid_requests_enabled=false")
        record["status"] = DRY
        record["reason_not_run"] = reason
        ctx.say(f"   D-11 paid authorisation NOT EXECUTED ({reason}).  Exact command:")
        ctx.say(f"     {q(argv)}")
        ctx.say(f"   the submit below then takes {out}")
        ctx.planned_commands.append({
            "stage": sid, "step": f"{sid.lower()}_materialize_paid_authorization",
            "planned_credits": 0, "paid_argv": record["argv"],
            "paid_command": record["command"],
            "note": ("D-11: writes the _PAID_AUTHORIZED copy and the "
                     "GIGGLE-REROLL-COST-GUARD report bound to its sha256.  Offline, no POST, "
                     "no credits — but it DOES append to the credit ledger through "
                     "nalu_budget_ledger.py --check, so a rehearsal must pass a scratch "
                     "--ledger.  Re-run it after ANY edit to the input file: the guard report "
                     "binds the byte SHA.  " + note)})
        return DRY, out, record

    step = ctx.run(argv, name=f"{sid.lower()}_materialize_paid_authorization", paid=False)
    res.steps.append(step)
    report = read_json(REPORTS_DIR / f"{ctx.episode}_paid_authorization_{sid.lower()}.json",
                       {}) or {}
    record["exit_code"] = step["exit_code"]
    record["report"] = str(REPORTS_DIR / f"{ctx.episode}_paid_authorization_{sid.lower()}.json")
    record["refusal"] = report.get("refusal") or report.get("status")
    record["cost_guard"] = (report.get("cost_guard") or {}).get("status") \
        if isinstance(report.get("cost_guard"), dict) else report.get("cost_guard")
    record["materialised_sha256"] = sha256_file(out)
    if step["exit_code"] != 0 or not out.is_file():
        record["status"] = BLOCKED
        record["blocker"] = (f"PAID_AUTHORIZATION_REFUSED:exit={step['exit_code']}:"
                            f"{record['refusal']}")
        ctx.say(f"   !! D-11 refused to authorise {target.name}: {record['blocker']}")
        return BLOCKED, out, record
    record["status"] = PASS
    ctx.say(f"   D-11 authorised: {out.name}  (order seq={ctx.authority['paid_order_seq']}, "
            f"cost guard {record['cost_guard']})")
    return PASS, out, record


def tail(text: str | None, limit: int = 4000) -> str:
    text = text or ""
    return text if len(text) <= limit else "…" + text[-limit:]


def blank_stage(sid: str) -> dict[str, Any]:
    return {
        "stage": sid, "title": STAGE_TITLES[sid], "status": "NOT_RUN",
        "attempts": 0, "started_at": None, "finished_at": None,
        "input_fingerprint": None, "details": {}, "steps": [],
        "receipts": [], "blockers": [], "planned_credits": 0,
    }


# --------------------------------------------------------------------------- #
# S1 — script ready
# --------------------------------------------------------------------------- #
def fp_s1(ctx: Ctx) -> str:
    def digest(path: Path | str | None) -> str | None:
        if not path:
            return None
        candidate = Path(path)
        return sha256_file(candidate) if candidate.is_file() else None

    payload: dict[str, Any] = {
        "layers": {
            name: digest(path) for name, path in ctx.p.layers().items()
        },
        "policy_profile": _policy.selected(),
        "project_lexicon": digest(ctx.p.scope.get("lexicon")),
    }
    # CURRENT_PORTABLE S1 is also a provenance gate.  Include every private
    # authority behind ACTIVE_WRITER_HANDOFF in the fingerprint so a prior PASS
    # cannot be skipped after a receipt, source, rule, lexicon or seal drifts.
    if _policy.selected() == _policy.CURRENT:
        active_path = ctx.p.writer_manifest.parent / "ACTIVE_WRITER_HANDOFF.json"
        payload["active_handoff"] = digest(active_path)
        active = read_json(active_path, {}) or {}
        dependencies: dict[str, Any] = {}
        for key in ("input_bundle", "writer_receipt", "four_layer_seal", "project_lexicon"):
            row = active.get(key) or {}
            dependencies[key] = digest(row.get("path"))
        input_bundle = read_json(
            Path(str((active.get("input_bundle") or {}).get("path") or "")), {}
        ) or {}
        dependencies["source_receipts"] = {
            str(row.get("receipt_path") or ""): digest(row.get("receipt_path"))
            for row in (input_bundle.get("source_receipts") or [])
            if isinstance(row, dict)
        }
        dependencies["source_artifacts"] = {
            str(artifact.get("path") or ""): digest(artifact.get("path"))
            for row in (input_bundle.get("source_receipts") or [])
            if isinstance(row, dict)
            for artifact in (row.get("artifacts") or [])
            if isinstance(artifact, dict)
        }
        writer_receipt = read_json(
            Path(str((active.get("writer_receipt") or {}).get("path") or "")), {}
        ) or {}
        dependencies["writer_rules"] = {
            str(row.get("path") or ""): digest(row.get("path"))
            for row in ((writer_receipt.get("writer_rules") or {}).get("files") or [])
            if isinstance(row, dict)
        }
        payload["writer_handoff_dependencies"] = dependencies
    return sha256_text(json.dumps(payload, sort_keys=True))


def stage_s1(ctx: Ctx) -> StageResult:
    p = ctx.p
    missing = [str(path) for path in p.layers().values() if not path.is_file()]
    if missing:
        res = StageResult(BLOCKED, missing_layers=missing, layer_sha256={})
        res.blockers = [f"SCRIPT_LAYER_MISSING:{path}" for path in missing]
        return res
    layer_shas = {name: sha256_file(path) for name, path in p.layers().items()}

    writer_handoff_report = p.logs / f"{ctx.run_id}_writer_handoff_verification.json"
    if _policy.selected() == _policy.CURRENT:
        writer_handoff = ctx.run(
            [
                VENV, ENGINE / "tools/storyclaw_writer_workflow.py", "verify",
                "--project-root", RUNTIME,
                "--episode", ctx.episode,
                "--narrative", p.narrative,
                "--directing", p.directing,
                "--contract", p.contract,
                "--manifest", p.writer_manifest,
                "--out", writer_handoff_report,
            ],
            name="s1_canonical_writer_handoff",
        )
        writer_handoff_verdict = read_json(writer_handoff_report, {}) or {}
        writer_handoff_ok = (
            writer_handoff["exit_code"] == 0
            and writer_handoff_verdict.get("status") == PASS
        )
    else:
        writer_handoff = {
            "exit_code": 0,
            "log": None,
            "stdout_tail": "LEGACY_REPLAY_PROFILE",
        }
        writer_handoff_verdict = {
            "status": "NOT_APPLICABLE_LEGACY_REPLAY",
            "failures": [],
        }
        writer_handoff_ok = True

    gate10 = ctx.run(
        [VENV, p.gate10, p.writer_manifest, "--warn-is-fail",
         "--out", p.logs / f"{ctx.run_id}_gate10.json"],
        name="s1_gate10_writer_scene_source_declaration")
    contract_gate = ctx.run(
        [VENV, "-c",
         "import json,sys;sys.path.insert(0,'.')\n"
         "from tools.character_entity_contract import validate_character_entity_contract\n"
         f"print(json.dumps(validate_character_entity_contract(json.load(open({str(p.contract)!r}))),"
         "ensure_ascii=False))"],
        name="s1_character_entity_contract")

    entity_verdict: dict[str, Any] = {}
    for line in (contract_gate.get("stdout_tail") or "").splitlines():
        if line.strip().startswith("{"):
            entity_verdict = json.loads(line.strip())
    contract_gate["verdict"] = entity_verdict

    # Roger 2026-09-13 "编剧层设计了太多固定机位的静止段落": authored camera-motion gate
    # (report-only for E01, blocking from E02).  E01 baseline: 28/32 shots LOCKED (0.875).
    static_gate = ctx.run(
        [VENV, str(RT_TOOLS / "static_design_gate.py"), "--contract", str(p.contract), "--episode", ctx.episode,
         "--out", str(p.logs / f"{ctx.run_id}_static_design_gate.json")],
        name="s1_static_design_gate")
    static_ok = static_gate["exit_code"] == 0
    gate10_ok = gate10["exit_code"] == 0
    entity_ok = entity_verdict.get("status") == PASS

    # seq=19 (E04 review, D-40): "does the contract hold up" gates — hook, dialogue density,
    # action outcomes, antagonist motive, prop sources, entity introductions, lexicon (A1–A6),
    # and the continuity state contract (life state, group counts, creature cards, ambush space,
    # costume inheritance; B1–B5).  Both blocking; reports next to the other S1 logs.
    lexicon = ctx.p.scope["lexicon"]  # per-scope period lexicon
    structure_gate = ctx.run(
        [VENV, ENGINE / "tools/script_structure_contract_gate.py", "--contract", p.contract,
         "--manifest", p.writer_manifest, "--lexicon", lexicon,
         "--out", p.logs / f"{ctx.run_id}_script_structure_contract_gate.json"],
        name="s1_script_structure_contract_gate")
    continuity_gate = ctx.run(
        [VENV, ENGINE / "tools/continuity_state_contract_gate.py", "--contract", p.contract,
         "--out", p.logs / f"{ctx.run_id}_continuity_state_contract_gate.json"],
        name="s1_continuity_state_contract_gate")
    structure_ok = structure_gate["exit_code"] == 0
    continuity_ok = continuity_gate["exit_code"] == 0
    scope_check = project_scope_check(ctx, require_preproduction_map=False)
    scope_ok = scope_check["status"] == PASS
    # Writer-layer self-check. Historical replay keeps the contract-authored
    # enforcement bit. Every current portable project requires the declaration
    # and a real PASS, including its first episode; a reused E01 number cannot
    # inherit the legacy report-only window.
    selfcheck_out = p.logs / f"{ctx.run_id}_writer_selfcheck_seq29.json"
    selfcheck_step = ctx.run([VENV, RT_TOOLS / "nalu_writer_selfcheck_seq29.py", "--contract", p.contract,
                              "--lexicon", lexicon, "--out", selfcheck_out],
                             name="s1_writer_selfcheck_seq29")
    selfcheck = read_json(selfcheck_out, {}) or {}
    selfcheck_ok = writer_selfcheck_admitted(
        selfcheck, int(selfcheck_step["exit_code"])
    )
    status = PASS if (writer_handoff_ok and gate10_ok and entity_ok and static_ok and structure_ok and continuity_ok and scope_ok and selfcheck_ok) else BLOCKED
    res = StageResult(
        status,
        layer_sha256=layer_shas,
        gate10={"exit_code": gate10["exit_code"], "status": PASS if gate10_ok else "FAIL",
                "log": gate10["log"]},
        static_design_gate={"exit_code": static_gate["exit_code"], "status": PASS if static_ok else "FAIL",
                            "report": str(p.logs / f"{ctx.run_id}_static_design_gate.json"),
                            "stdout_tail": static_gate.get("stdout_tail")},
        character_entity_contract=entity_verdict,
        note="Both gates must PASS.  character_entity_contract 'required' is false "
             "below ACTIVE_FROM_EPISODE=54, but this pipeline treats it as blocking "
             "anyway — a role-semantics defect is a real data defect.")
    res.details = getattr(res, "details", {}) or {}
    res.details["canonical_writer_handoff"] = {
        "status": writer_handoff_verdict.get("status"),
        "failures": (writer_handoff_verdict.get("failures") or [])[:12],
        "report": str(writer_handoff_report),
        "exit_code": writer_handoff["exit_code"],
    }
    if not writer_handoff_ok:
        res.blockers = list(getattr(res, "blockers", []) or []) + [
            f"CANONICAL_WRITER_HANDOFF_FAIL:{code}"
            for code in (writer_handoff_verdict.get("failures") or ["VERIFY_FAILED"])[:8]
        ]
    res.details["project_scope_check"] = scope_check
    res.details["writer_selfcheck_seq29"] = {"status": selfcheck.get("status"), "enforced": selfcheck.get("enforced"),
                                             "failures": (selfcheck.get("failures") or [])[:12], "failure_count": len(selfcheck.get("failures") or []),
                                             "report": str(selfcheck_out), "exit_code": selfcheck_step["exit_code"]}
    if not selfcheck_ok:
        res.blockers = list(getattr(res, "blockers", []) or []) + [f"WRITER_SELFCHECK_SEQ29_FAIL:{code}" for code in (selfcheck.get("failures") or [])[:8]]
    res.details["layers"] = {"source": ctx.p.layers_source, "paths": {k: str(v) for k, v in p.layers().items()}}
    if not scope_ok:
        res.blockers = list(getattr(res, "blockers", []) or []) + [f"PROJECT_SCOPE_FAIL:{code}" for code in scope_check["failures"]]
    res.details["script_structure_contract_gate"] = {
        "exit_code": structure_gate["exit_code"], "status": PASS if structure_ok else "FAIL",
        "report": str(p.logs / f"{ctx.run_id}_script_structure_contract_gate.json"),
        "stdout_tail": structure_gate.get("stdout_tail")}
    res.details["continuity_state_contract_gate"] = {
        "exit_code": continuity_gate["exit_code"], "status": PASS if continuity_ok else "FAIL",
        "report": str(p.logs / f"{ctx.run_id}_continuity_state_contract_gate.json"),
        "stdout_tail": continuity_gate.get("stdout_tail")}
    res.steps = [writer_handoff, gate10, contract_gate, static_gate, structure_gate, continuity_gate]
    res.receipts = ([str(writer_handoff_report)] if _policy.selected() == _policy.CURRENT else []) + [
        gate10["log"], contract_gate["log"], static_gate["log"],
        structure_gate["log"], continuity_gate["log"],
    ]
    if not structure_ok:
        res.blockers.append("SCRIPT_STRUCTURE_CONTRACT_FAIL:" + str(structure_gate.get("stdout_tail") or "")[-300:])
    if not continuity_ok:
        res.blockers.append("CONTINUITY_STATE_CONTRACT_FAIL:" + str(continuity_gate.get("stdout_tail") or "")[-300:])
    if not gate10_ok:
        res.blockers.append("GATE10_WRITER_SCENE_SOURCE_DECLARATION_FAIL")
    if not static_ok:
        res.blockers.append("STATIC_DESIGN_GATE_FAIL:" + str(static_gate.get("stdout_tail") or "")[-200:])
    if not entity_ok:
        res.blockers.append("CHARACTER_ENTITY_CONTRACT_FAIL:"
                            + ",".join(str(f) for f in (entity_verdict.get("failures") or [])))
    # Downstream asset confirmation must bind stable S1 evidence.  The main
    # pipeline state is intentionally mutable as S2-S8 advance, so hashing that
    # file would invalidate a valid confirmation on every later stage update.
    # This dedicated receipt changes only when S1 is actually executed again.
    s1_receipt = p.logs / "S1_GATE_RECEIPT.json"
    write_json(s1_receipt, {
        "schema": "nalu.s1_gate_receipt.v1",
        "episode": ctx.episode,
        "series_scope_id": str(p.scope["scope_id"]),
        "stage": "S1",
        "status": status,
        "policy_profile": _policy.selected(),
        "layer_sha256": layer_shas,
        "writer_selfcheck_seq29": {
            "status": selfcheck.get("status"),
            "enforced": selfcheck.get("enforced"),
            "exit_code": selfcheck_step["exit_code"],
            "report": str(selfcheck_out),
            "report_sha256": sha256_file(selfcheck_out),
        },
        "gates": {
            "canonical_writer_handoff": PASS if writer_handoff_ok else "FAIL",
            "gate10": PASS if gate10_ok else "FAIL",
            "character_entity_contract": PASS if entity_ok else "FAIL",
            "static_design_gate": PASS if static_ok else "FAIL",
            "script_structure_contract_gate": PASS if structure_ok else "FAIL",
            "continuity_state_contract_gate": PASS if continuity_ok else "FAIL",
            "project_scope_check": PASS if scope_ok else "FAIL",
        },
    })
    res.details["s1_gate_receipt"] = {
        "path": str(s1_receipt),
        "sha256": sha256_file(s1_receipt),
        "status": status,
    }
    res.receipts.append(str(s1_receipt))
    return res


# --------------------------------------------------------------------------- #
# S2 — preproduction (free)
# --------------------------------------------------------------------------- #
def s2_argv(ctx: Ctx, *, with_keyframes: bool, ready_units=None) -> list[Any]:
    p = ctx.p
    argv: list[Any] = [
        VENV, RT_TOOLS / "build_nalu_preproduction.py",
        "--episode", ctx.episode,
        "--contract", p.contract,
        "--manifest", p.writer_manifest,
        "--gsm", p.gsm,
        "--out-dir", p.preprod,
        "--engine-root", ENGINE,
        # the authored WARD-* rows are the wardrobe bible authority (fp_s2 already
        # fingerprints this file)
        "--asset-requirements", p.asset_requirements,
    ]
    if p.legacy_grouping_plan.is_file():
        argv += ["--legacy-plan", p.legacy_grouping_plan]
    if with_keyframes:
        argv += ["--keyframe-dir", p.keyframes]
    if ready_units is not None:
        argv += ["--ready-units", json.dumps(list(ready_units)),
                 "--real-final-frames", p.preprod / "real_final_frames"]
    return argv


def fp_s2(ctx: Ctx) -> str:
    p = ctx.p
    return sha256_text(json.dumps({
        "contract": sha256_file(p.contract),
        "manifest": sha256_file(p.writer_manifest),
        "gsm": sha256_file(p.gsm),
        "gsm_path": str(p.gsm),
        # D-10: S2 now owns the pre-step that generates these, so an edited
        # overlay or a regenerated requirements file re-runs the stage.
        "asset_requirements": sha256_file(p.asset_requirements),
        "overlay": sha256_file(p.overlay) if p.overlay else None,
        "keyframes": sorted(item.name for item in p.keyframes.glob("*.png")) if p.keyframes.is_dir() else [],
    }, sort_keys=True))


def stage_s2(ctx: Ctx, *, with_keyframes: bool = False, ready_units=None) -> StageResult:
    p = ctx.p
    p.preprod.mkdir(parents=True, exist_ok=True)
    # D-10 pre-step: this episode's own global space map + asset requirements +
    # identity prompts, generated by the two episode-agnostic builders.  E01's
    # authored files are reused untouched.
    inputs = ensure_episode_inputs(ctx)
    if inputs["status"] != PASS:
        res = StageResult(inputs["status"], episode_inputs=inputs)
        res.steps = list(inputs.get("steps") or [])
        res.blockers = list(inputs.get("blockers") or [])
        res.details["hint"] = inputs.get("required_action") or inputs.get("note")
        return res
    if not p.gsm.is_file():
        res = StageResult(BLOCKED, missing_gsm=str(p.gsm_own), episode_inputs=inputs,
                          note="No per-episode global_space_map.json and no fallback.")
        res.blockers = [f"GLOBAL_SPACE_MAP_MISSING:{p.gsm_own}"]
        return res
    reused_gsm = p.gsm != p.gsm_own
    step = ctx.run(s2_argv(ctx, with_keyframes=with_keyframes, ready_units=ready_units),
                   name="s2_build_nalu_preproduction" + ("_with_keyframes" if with_keyframes else ""))
    report = read_json(p.preprod_report, {}) or {}
    stages = {row.get("stage"): row.get("status") for row in (report.get("stages") or [])}
    blockers = [row.get("id") for row in (report.get("remaining_blockers") or [])]
    # build_nalu_preproduction is PARTIAL_BLOCKED until keyframes + identity cards
    # exist; that is expected on the first pass and is not an orchestration error.
    inner_free_ok = all(
        stages.get(key) == PASS for key in
        ("1.4_subspace_plan_and_space_gate", "4.0_editorial_seedance_manifest",
         "4.1_grouping_spec", "4.2_compile_video_unit_plan", "4.2b_video_unit_grouping_gate"))
    status = PASS if (step["exit_code"] == 0 and inner_free_ok) else BLOCKED
    res = StageResult(
        status,
        report=str(p.preprod_report),
        engine_report_status=report.get("status"),
        video_unit_count=report.get("video_unit_count"),
        runtime_seconds=report.get("runtime_seconds"),
        machine_gate_reports=[row.get("gate_id") for row in (report.get("machine_gate_reports") or [])],
        inner_stages=stages,
        remaining_blockers=blockers,
        episode_inputs={key: value for key, value in inputs.items() if key != "steps"},
        gsm_used=str(p.gsm),
        gsm_reused_from_another_episode=reused_gsm,
        artifacts=report.get("artifacts") or {},
        keyframe_dir_passed=str(p.keyframes) if with_keyframes else None)
    res.steps = list(inputs.get("steps") or []) + [step]
    res.receipts = [str(p.preprod_report), str(p.machine_gate_bundle)]
    if inputs.get("gsm_gate_report") and Path(inputs["gsm_gate_report"]).is_file():
        # a real PASS SCENE-AUTHORITY-LOCK report from the GSM extension
        res.receipts.append(str(inputs["gsm_gate_report"]))
    if status != PASS:
        res.blockers = [f"PREPRODUCTION_INNER_STAGE_NOT_PASS:{key}={value}"
                        for key, value in stages.items() if value != PASS] or ["PREPRODUCTION_FAILED"]
    # Asset selection is derived from the free preproduction outputs.  Bind a
    # dedicated receipt only on that first S2 pass; later S5 keyframe rebuilds
    # must not mutate the evidence behind an already confirmed asset plan.
    if not with_keyframes:
        s2_receipt = p.logs / "S2_PREPRODUCTION_RECEIPT.json"
        write_json(s2_receipt, {
            "schema": "nalu.s2_preproduction_receipt.v1",
            "episode": ctx.episode,
            "series_scope_id": str(p.scope["scope_id"]),
            "stage": "S2",
            "status": status,
            "policy_profile": _policy.selected(),
            "generation_contract_sha256": sha256_file(p.contract),
            "writer_manifest_sha256": sha256_file(p.writer_manifest),
            "global_space_map_sha256": sha256_file(p.gsm),
            "asset_requirements_sha256": sha256_file(p.asset_requirements),
            "preproduction_report_sha256": sha256_file(p.preprod_report),
            "video_unit_count": report.get("video_unit_count"),
            "inner_stages": stages,
            "keyframes_included": False,
        })
        res.details["s2_preproduction_receipt"] = {
            "path": str(s2_receipt),
            "sha256": sha256_file(s2_receipt),
            "status": status,
        }
        res.receipts.append(str(s2_receipt))
    return res


# --------------------------------------------------------------------------- #
# cross-episode asset library / voice registry (the reuse authorities)
# --------------------------------------------------------------------------- #
def load_cross_episode_library(scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """The library this orchestrator maintains across episodes.

    Seeded from runtime/E01_ASSET_LIBRARY_V1.json the first time.  Only the
    engine's own admission route may set an entry to LOCKED / qa PASS; this
    loader never mutates a verdict.
    """
    lib_path = (scope or {}).get("asset_library") or ASSET_LIBRARY
    seed_path = (scope or {}).get("asset_library_seed") or ASSET_LIBRARY_SEED
    library = read_json(lib_path)
    # E59 migration imported the legacy Qingshan flat ``assets`` list.  The
    # nalu orchestrator uses the portable category-map form; normalize the
    # list in memory (and persist the normalized copy) without changing any
    # status, SHA, or QA verdict.
    if isinstance(library, dict) and isinstance(library.get("assets"), list):
        category_map = {name: {} for name in (
            "characters", "wardrobe", "scenes", "props", "voices", "accents",
            "music", "ambience", "sfx", "reference_materials")}
        for asset in library["assets"]:
            if not isinstance(asset, dict):
                continue
            kind = str(asset.get("asset_kind") or "").upper()
            category = "characters" if "CHARACTER" in kind else "props" if "PROP" in kind else "scenes" if "SCENE" in kind or "PLACE" in kind else "reference_materials"
            category_map[category][str(asset.get("asset_id"))] = asset
        library = copy.deepcopy(library)
        library["assets"] = category_map
        write_json(lib_path, library)
    if not isinstance(library, dict):
        library = read_json(seed_path) or {
            "schema": "ai_drama.production_asset_library.v1", "assets": {}}
        library = copy.deepcopy(library)
        library["maintained_by"] = TOOL_ID
        library["note"] = ("Cross-episode nalu asset library.  A subject is skipped in S3 "
                           "only when its entry here is status LOCKED with qa.status PASS "
                           "and an artifact sha256 that still matches the file on disk.")
        library["seeded_from"] = str(seed_path)
        library["seeded_at"] = now()
        # materialise it so the reuse authority is a real file from now on.  No
        # verdict is invented: whatever the seed said is what is written.
        write_json(lib_path, library)
    return library


def locked_subjects(library: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Subjects that are LOCKED with a still-valid SHA — safe to skip (paid reuse)."""
    out: dict[str, dict[str, Any]] = {}
    for category, rows in (library.get("assets") or {}).items():
        if not isinstance(rows, dict):
            continue
        for subject_id, asset in rows.items():
            if not isinstance(asset, dict):
                continue
            if asset.get("status") != "LOCKED":
                continue
            if ((asset.get("qa") or {}).get("status")) != PASS:
                continue
            artifacts = asset.get("artifacts") or []
            verified = []
            for artifact in artifacts:
                path = artifact.get("path")
                if path and sha256_file(Path(path)) == artifact.get("sha256"):
                    verified.append(artifact)
            if verified:
                out[subject_id] = {"category": category,
                                   "sha256": [row["sha256"] for row in verified],
                                   "views": sorted({str(row.get("role") or row.get("view") or "")
                                                    for row in verified} - {""})}
                # A LOCKED character carries one verified artifact per view; the S3 plan names
                # those views as separate rows (``<subject>__<VIEW>``).  Register them so a
                # locked character is never re-rendered view by view (StoryClaw 2026-09-21:
                # 16 duplicate view renders planned for 8 LOCKED characters).
                for view in out[subject_id]["views"]:
                    out.setdefault(f"{subject_id}__{view}", {"category": category, "via": subject_id,
                                                              "sha256": out[subject_id]["sha256"]})
    return out


def voice_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """`major_roles` in runtime/voice_registry.json is a LIST of row objects."""
    rows = registry.get("major_roles")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(rows, dict):
        return [dict(row, entity_id=row.get("entity_id", key))
                for key, row in rows.items() if isinstance(row, dict)]
    return []


def locked_voice_entities(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Speaking characters whose voice reference is already production-locked.

    Locked means: status LOCKED_PRODUCTION_READY, a real provider asset id, and a
    local wav whose sha256 still matches the one recorded.  Anything less is
    regenerated — a PENDING_GENERATION row with null ids is never treated as done.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in voice_rows(registry):
        entity_id = row.get("entity_id")
        if not entity_id or row.get("status") != "LOCKED_PRODUCTION_READY":
            continue
        local = row.get("local_reference")
        if row.get("remote_asset_id") and local and sha256_file(Path(local)) == row.get("local_sha256"):
            value = {"remote_asset_id": row["remote_asset_id"],
                     "remote_url": row.get("remote_url")}
            out[entity_id] = value
            # v4 authored contracts namespace the same long-lived character voice
            # (e.g. e59_linzhaojing, e50_chenji).  Reuse is keyed by the canonical
            # voice registry id, so expose deterministic aliases here; otherwise S4
            # would regenerate an already locked voice or emit a false pending row.
            aliases = {str(entity_id)}
            raw = str(entity_id)
            if "_" in raw:
                aliases.add(raw.rsplit("_", 1)[-1])
            aliases.update({
                "baili_junzhu": "baili",
                "gold_armored_man": "xuanyuan",
                "greeter": "maid_group",
                "linzhaojing": "linchaojing",
            }.get(alias, alias) for alias in list(aliases))
            for alias in aliases:
                out.setdefault(alias, value)
    return out


def canonical_voice_entity(entity_id: str) -> str:
    """Collapse a v4 episode-scoped speaking id to the registry character id."""
    raw = str(entity_id or "")
    # v4 ids are usually ``eNN_<canonical_id>``; retain the full character
    # portion so multiword ids such as ``baili_junzhu`` and
    # ``gold_armored_man`` remain resolvable.
    suffix = raw.split("_", 1)[1] if raw.startswith("e") and "_" in raw else raw
    return {
        "baili_junzhu": "baili",
        "gold_armored_man": "xuanyuan",
        "greeter": "maid_group",
        "linzhaojing": "linchaojing",
    }.get(suffix, suffix)


# --------------------------------------------------------------------------- #
# D-10 — per-episode preproduction inputs (global space map + asset
#        requirements + identity prompts), generated before S2 and S3
# --------------------------------------------------------------------------- #
def gsm_extend_argv(ctx: Ctx, *, with_requirements: bool, base: Path) -> list[Any]:
    p = ctx.p
    argv: list[Any] = [
        VENV, GSM_EXTEND,
        "--episode", ctx.episode,
        "--contract", p.contract,
        "--manifest", p.writer_manifest,
        "--base-gsm", base,
        "--out", p.gsm_own,
        "--asset-dir", p.space_map_assets,
        "--reports-dir", p.rt_pre_reports,
        "--engine-root", ENGINE,
        # NEVER resolve() this: .qingshan-venv/bin/python is a symlink to
        # python3.12 and resolving it leaves the venv, so PIL disappears and the
        # place-map render fails with ModuleNotFoundError (WIRING_NOTES §2).
        "--python", VENV,
    ]
    if with_requirements and p.asset_requirements.is_file():
        argv += ["--asset-requirements", p.asset_requirements]
    place_spec = p.rt_pre / "new_location_place_spec.json"
    if place_spec.is_file():
        argv += ["--place-spec", place_spec]
    return argv


def ar_build_argv(ctx: Ctx) -> list[Any]:
    p = ctx.p
    argv: list[Any] = [
        VENV, AR_BUILDER,
        "--episode", ctx.episode,
        "--contract", p.contract,
        "--narrative", p.narrative,
        "--manifest", p.writer_manifest,
        "--directing", p.directing,
        "--prior-library", ctx.p.scope["asset_library"],
        "--project-id", ctx.p.scope["series_id"],
        "--out-dir", p.rt_pre,
        "--gsm", p.gsm_own if p.gsm_own.is_file() else p.gsm,
    ]
    if ctx.p.scope.get("charter"):
        # a foreign scope names its own series authority; the default scope keeps the
        # builder's writer-charter default.
        argv += ["--charter", ctx.p.scope["charter"]]
    overlay = p.overlay
    if overlay is not None:
        # authored prose no script layer carries.  Without it every field that
        # cannot be derived lands as an AUTHORING_REQUIRED_* sentinel and the
        # tool exits 3 — which this stage treats as a blocking stop, because a
        # sentinel must never be baked into a paid prompt.
        argv += ["--overlay", overlay]
    return argv


def initial_global_space_map_seed(ctx: Ctx) -> Path:
    """Write a non-production empty seed for a brand-new series.

    ``extend_global_space_map.py`` historically required E01's hand-authored
    map as its base.  A portable installation has no earlier production, so
    the first episode needs an empty construction seed.  This file is never
    admitted as a map and carries no PASS verdict; the extender must still
    author every location, render real assets, and pass the registered layout
    gate before ``global_space_map.json`` exists.
    """
    scope_token = re.sub(r"[^A-Za-z0-9]+", "-", str(ctx.p.scope["series_id"])).strip("-") or "PROJECT"
    seed = ctx.p.rt_pre_reports / "initial_global_space_map_seed.json"
    payload = {
        "schema": "qingshan.episode_global_space_map.v1",
        "episode": "__PROJECT_BASE__",
        "episode_global_space_map_id": f"EGSM-{scope_token}-BASE",
        "map_version": 1,
        "authority_ref": "EMPTY_CONSTRUCTION_SEED_NOT_A_PRODUCTION_AUTHORITY",
        "status": "EMPTY_SEED_NOT_ADMITTED",
        "inheritance": {"mode": "NEW_PROJECT_EMPTY_SEED"},
        "map_image": {},
        "space_maps": [],
        "topology_sha256": sha256_text(
            json.dumps([], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        ),
    }
    current = read_json(seed, {}) or {}
    if current != payload:
        write_json(seed, payload)
    return seed


def ensure_episode_inputs(ctx: Ctx) -> dict[str, Any]:
    """D-10 — make sure this episode has its own GSM, asset requirements and prompts.

    E01 authored all three by hand and they are reused untouched: when both
    ``global_space_map.json`` and ``asset_requirements.json`` already exist this
    function runs nothing at all.

    For any other episode the two episode-agnostic generators
    (``runtime/tools/WIRING_NOTES.md`` §1 and §2) produce them:

      1. ``extend_global_space_map.py`` first, WITHOUT ``--asset-requirements``.
         It must run before ``build_nalu_preproduction.py`` because
         ``SpaceIndex`` hard-fails on a ``scene_id`` the GSM does not map, and
         because reusing E01's map is simply wrong for an episode that visits a
         new location.  The base is the PREVIOUS episode's locked map when it
         exists (it already carries every earlier episode's places), else E01's.
      2. ``build_episode_asset_requirements.py``, with ``--overlay`` when this
         episode has one.  Exit 3 means an ``AUTHORING_REQUIRED_*`` sentinel
         landed in the output: the files are written so the gaps are
         inspectable, but the stage FAILS CLOSED with AUTHORING_REQUIRED and
         names the overlay to author.
      3. ``extend_global_space_map.py`` again, now WITH ``--asset-requirements``,
         so a new location picks up its authored ``key_fixed_elements``.  This is
         free: for the same ``--episode`` the tool is byte-identical-idempotent.

    The result is cached on the stage result so S2 and S3 do not run it twice.
    """
    if isinstance(getattr(ctx, "_episode_inputs", None), dict):
        return ctx._episode_inputs
    p = ctx.p
    detail: dict[str, Any] = {
        "decision": "D-10",
        "episode": ctx.episode,
        "global_space_map": str(p.gsm_own),
        "asset_requirements": str(p.asset_requirements),
        "prompt_dir": str(p.prompt_dir),
        "overlay": str(p.overlay) if p.overlay else None,
        "steps": [],
        "actions": [],
        "warnings": [],
        "blockers": [],
    }
    have_gsm = p.gsm_own.is_file()
    have_ar = p.asset_requirements.is_file()
    if have_gsm and have_ar:
        detail["status"] = PASS
        detail["action"] = "REUSED_EXISTING"
        detail["note"] = (f"{ctx.episode} already has an authored global_space_map.json and "
                          "asset_requirements.json; neither generator was run.")
        ctx._episode_inputs = detail
        return detail

    p.rt_pre.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- 1. GSM
    if not have_gsm:
        base = (p.gsm_prev if (p.gsm_prev is not None and p.gsm_prev.is_file())
                else p.gsm_e01)
        if not base.is_file() and ctx.episode == "E01":
            base = initial_global_space_map_seed(ctx)
            detail["base_gsm_source"] = "NEW_PROJECT_EMPTY_SEED"
        else:
            detail["base_gsm_source"] = ("PREVIOUS_EPISODE" if base == p.gsm_prev else "E01")
        detail["base_gsm"] = str(base)
        if not base.is_file():
            detail["status"] = BLOCKED
            detail["blockers"] = [f"GLOBAL_SPACE_MAP_BASE_MISSING:{base}"]
            ctx._episode_inputs = detail
            return detail
        step = ctx.run(gsm_extend_argv(ctx, with_requirements=False, base=base),
                       name="d10_extend_global_space_map")
        detail["steps"].append(step)
        detail["actions"].append("EXTENDED_GLOBAL_SPACE_MAP")
        report = read_json(p.gsm_extension_report, {}) or {}
        detail["gsm_extension_report"] = str(p.gsm_extension_report)
        detail["gsm_new_locations"] = report.get("new_locations")
        detail["gsm_inheritance_mode"] = (report.get("inheritance") or {}).get("mode")
        detail["gsm_gate_report"] = str(p.gsm_gate_report)
        detail["gsm_gate_status"] = (read_json(p.gsm_gate_report, {}) or {}).get("status")
        auto_sited = report.get("auto_sited") or []
        if auto_sited:
            # the geometry is gate-clean, but WHERE the new place sits relative to
            # the village was chosen by the tool.  That is a directorial call.
            detail["warnings"].append(
                "AUTO_SITED_REQUIRES_SPATIAL_REVIEW:" + ",".join(map(str, auto_sited)))
        if step["exit_code"] != 0 or not p.gsm_own.is_file():
            detail["status"] = BLOCKED
            detail["blockers"] = [
                f"GLOBAL_SPACE_MAP_EXTENSION_FAILED:exit={step['exit_code']}",
                *[f"GSM_GATE:{value}" for value in (report.get("gate_failures") or [])[:6]]]
            ctx._episode_inputs = detail
            return detail

    # ------------------------------------------- 2. requirements + prompts
    if not have_ar or not p.prompt_dir.is_dir():
        step = ctx.run(ar_build_argv(ctx), name="d10_build_episode_asset_requirements")
        detail["steps"].append(step)
        detail["actions"].append("BUILT_ASSET_REQUIREMENTS_AND_PROMPTS")
        report = read_json(p.asset_requirements_report, {}) or {}
        detail["asset_requirements_report"] = str(p.asset_requirements_report)
        detail["subjects_new"] = report.get("new_subjects") or report.get("new_subject_count")
        detail["subjects_reused"] = report.get("reused_subjects") or report.get("reused_subject_count")
        detail["prompt_count"] = report.get("prompt_count")
        detail["authoring_gaps"] = report.get("authoring_gaps") or []
        if step["exit_code"] == 3:
            detail["status"] = AUTHORING_REQUIRED
            detail["blockers"] = [
                "D-10_AUTHORING_REQUIRED_SENTINEL_IN_ASSET_REQUIREMENTS",
                *[f"AUTHORING_GAP:{value}" for value in (detail["authoring_gaps"] or [])[:12]]]
            detail["required_action"] = (
                f"build_episode_asset_requirements.py wrote {p.asset_requirements} with at least "
                "one AUTHORING_REQUIRED_* sentinel, which must never reach a paid prompt.  "
                f"Author the overlay at {p.overlay_primary} "
                "(schema nalu.episode_asset_requirement_overlay.v1 — character priority / "
                "apparent age / sex, wardrobe state prose, per-location label + "
                "spatial_topology + key_fixed_elements, directing-script-only props, voice "
                "timbre briefs, the accent profile, the SFX table), then re-run "
                f"`run --episode {ctx.episode} --from S2`.  The gaps are listed in "
                f"{p.asset_requirements_report}.")
            ctx._episode_inputs = detail
            return detail
        if step["exit_code"] != 0 or not p.asset_requirements.is_file():
            detail["status"] = BLOCKED
            detail["blockers"] = [
                f"ASSET_REQUIREMENTS_BUILD_FAILED:exit={step['exit_code']}"]
            ctx._episode_inputs = detail
            return detail

        # ------------------------------- 3. GSM again, with authored elements
        if not have_gsm:
            if detail.get("base_gsm_source") == "NEW_PROJECT_EMPTY_SEED":
                base = Path(detail["base_gsm"])
            else:
                base = (p.gsm_prev if (p.gsm_prev is not None and p.gsm_prev.is_file())
                        else p.gsm_e01)
            step = ctx.run(gsm_extend_argv(ctx, with_requirements=True, base=base),
                           name="d10_extend_global_space_map_with_requirements")
            detail["steps"].append(step)
            detail["actions"].append("REFRESHED_GLOBAL_SPACE_MAP_WITH_KEY_FIXED_ELEMENTS")
            if step["exit_code"] != 0:
                detail["status"] = BLOCKED
                detail["blockers"] = [
                    f"GLOBAL_SPACE_MAP_REFRESH_FAILED:exit={step['exit_code']}"]
                ctx._episode_inputs = detail
                return detail

    if not p.prompt_dir.is_dir():
        detail["status"] = BLOCKED
        detail["blockers"] = [f"IDENTITY_PROMPT_DIR_MISSING:{p.prompt_dir}"]
        ctx._episode_inputs = detail
        return detail
    detail["prompts_on_disk"] = len(sorted(p.prompt_dir.glob("*.txt")))
    detail["status"] = PASS
    detail["action"] = "GENERATED"
    ctx._episode_inputs = detail
    return detail


# --------------------------------------------------------------------------- #
# S3 — identity cards (paid)
# --------------------------------------------------------------------------- #
def s3_bootstrap_argv(ctx: Ctx, *, accept_qa: bool, rights_basis: str | None,
                      source_folder: Path) -> list[Any]:
    p = ctx.p
    argv: list[Any] = [
        VENV, RT_TOOLS / "bootstrap_identity_cards.py",
        "--episode", ctx.episode,
        "--generation-contract", p.contract,
        "--asset-requirements", p.asset_requirements,
        "--prompt-dir", p.prompt_dir,
        "--character-source-folder", source_folder,
        "--asset-library-out", p.identity_library,
        "--plan-out", p.identity_plan,
        "--gate-report-out", p.identity_library_gate,
        "--match-report", p.identity_match,
        "--report", p.identity_report,
        "--aspect-ratio", "9:16",
        "--venv-python", VENV,
        "--run-submitter-precheck",
        # a character's non-base views are planned only once its base plate is here
        "--plates-dir", p.identity_harvest_dir,
    ]
    if rights_basis:
        argv += ["--rights-basis", rights_basis]
    # Production authorization is not evidence that source images were reviewed.
    # Only the explicit review route may assert source QA.
    if accept_qa:
        argv += ["--accept-source-qa"]
    return argv


S3_MAX_ROUNDS = 4
S3_IMAGE_MODEL, S3_IMAGE_RESOLUTION = "gpt-image-2-pro", "2K"   # submit_giggle_character_asset_plan.py call site


def s3_transaction_bound(ctx: Ctx, row: dict[str, Any]) -> bool:
    """True when the durable store already holds a SUBMITTED_TASK_ID_BOUND
    transaction for this exact row (same fingerprint the submitter computes), so a
    re-submit is recovered for free and must not be counted as planned spend."""
    contract = {
        "character_id": row.get("id"),
        "prompt_sha256": row.get("prompt_sha256"),
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "model": S3_IMAGE_MODEL, "aspect_ratio": "9:16", "resolution": S3_IMAGE_RESOLUTION,
    }
    fingerprint = hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
    path = (ENGINE / "workflow/tasks/giggle_submit_transactions" / ctx.episode
            / f"{row['id']}__{fingerprint[:16]}.json")
    if not path.is_file():
        return False
    transaction = read_json(path, {}) or {}
    return (transaction.get("submission_fingerprint") == fingerprint
            and transaction.get("state") == "SUBMITTED_TASK_ID_BOUND"
            and bool(transaction.get("task_id")))


def s3_plate_on_disk(ctx: Ctx, row_id: str) -> bool:
    plates = ctx.p.identity_harvest_dir
    if not plates.is_dir():
        return False
    pattern = re.compile(rf"^{re.escape(ctx.episode)}_{re.escape(row_id)}_[0-9a-fA-F-]{{8,}}\.png$")
    return any(pattern.match(item.name) for item in plates.iterdir())


def stage_s3(ctx: Ctx) -> StageResult:
    """Identity cards, in ROUNDS.

    Every character card is ``card_deliverables`` views (E01: 3), and the
    keyframe identity gate needs ``canonical_views_min`` (3) locked views per
    character.  bootstrap_identity_cards.py plans the BASE full-body view first
    (text-to-image, or image-to-image on the line-owner-supplied source photo for a
    source-matched character) and DEFERS the other views until the base plate is
    harvested, because they are image-to-image on that very plate.  So:

        round 1  base plates (+ views of characters whose base already exists)
        round 2  views of the characters whose base landed in round 1
        round n  until the bootstrap reports nothing deferred and nothing new

    Money: each round's planned credits = rows the durable store does NOT already
    hold × image price; recovered rows cost nothing.  Props/sets are one
    text-to-image row each, as before.
    """
    p = ctx.p
    p.identity.mkdir(parents=True, exist_ok=True)
    inputs = ensure_episode_inputs(ctx)
    if inputs["status"] != PASS:
        res = StageResult(inputs["status"], episode_inputs=inputs)
        res.steps = list(inputs.get("steps") or [])
        res.blockers = list(inputs.get("blockers") or [])
        res.details["hint"] = inputs.get("required_action") or inputs.get("note")
        return res

    library = load_cross_episode_library(ctx.p.scope)
    already = locked_subjects(library)
    image_credits = int(((ctx.cost_plan.get("price_basis") or {}).get("image_credits_per_task")) or 11)

    res = StageResult(PASS)
    res.steps = []
    res.details = {
        "episode_inputs": {key: value for key, value in inputs.items() if key != "steps"},
        "rights_basis": ctx.rights_declaration,
        "plan": str(p.identity_plan),
        "rounds": [],
        "image_credits_per_task": image_credits,
    }
    res.receipts = [str(p.identity_report), str(p.identity_match),
                    str(p.identity_library_gate), str(p.identity_plan)]
    total_planned = 0
    complete = False
    report: dict[str, Any] = {}
    for round_no in range(1, S3_MAX_ROUNDS + 1):
        boot = ctx.run(s3_bootstrap_argv(ctx, accept_qa=False,
                                         rights_basis=ctx.rights_basis,
                                         source_folder=ctx.p.scope["character_sources"]),
                       name=f"s3_bootstrap_identity_cards_r{round_no}")
        res.steps.append(boot)
        report = read_json(p.identity_report, {}) or {}
        plan = read_json(p.identity_plan, {}) or {}
        plan_rows = plan.get("new_asset_groups")
        if plan_rows is None:
            res.status = BLOCKED
            res.blockers.append("IDENTITY_PLAN_HAS_NO_new_asset_groups")
            return res
        if boot["exit_code"] not in (0, 2):
            res.status = BLOCKED
            res.blockers.append("IDENTITY_BOOTSTRAP_CRASHED")
            return res
        rows = [row for row in plan_rows if isinstance(row, dict)]
        pending = [row["id"] for row in rows]
        skipped = [rid for rid in pending if rid in already]
        new_rows = [row for row in rows
                    if row["id"] not in already and not s3_transaction_bound(ctx, row)]
        unharvested = [row["id"] for row in rows
                       if row["id"] not in already and s3_transaction_bound(ctx, row)
                       and not s3_plate_on_disk(ctx, row["id"])]
        deferred_all = list(report.get("deferred_view_rows") or [])
        # A deferred view can already be present in the cross-episode library.
        # Bootstrap reports it because it only inspects the episode-local base
        # plate flow; treating an already LOCKED/PASS view as missing makes S3
        # loop or request a duplicate paid render.  Apply the same reuse
        # authority used for base rows before deciding that a view is blocked.
        deferred_locked_skipped = [
            row["id"] for row in deferred_all
            if isinstance(row, dict) and row.get("id") in already
        ]
        deferred = [
            row for row in deferred_all
            if isinstance(row, dict) and row.get("id") not in already
        ]
        # --s3-subjects: submit only these rows this run (seq=7 condition 5 style sample).  The
        # filtered plan copy is what gets authorised and submitted; the durable store later
        # recovers these rows in the full round without a second POST.
        subset = [x.strip() for x in str(getattr(ctx.args, "s3_subjects", "") or "").split(",") if x.strip()]
        subset_plan = p.identity_plan
        if subset:
            new_rows = [row for row in new_rows if row["id"] in subset]
            unharvested = [uid for uid in unharvested if uid in subset]
            deferred = [row for row in deferred if row.get("id") in subset]
            sub = dict(plan)
            sub["new_asset_groups"] = [row for row in rows if row["id"] in subset]
            sub["deferred_view_rows"] = deferred
            sub["subject_subset"] = {
                "ids": subset,
                "authority": "CLI_S3_SUBJECTS_EXPLICIT_OPERATOR_SELECTION",
            }
            subset_plan = p.identity / "character_asset_plan_SUBSET.json"
            subset_plan.write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")
        round_rec: dict[str, Any] = {
            "round": round_no,
            "bootstrap_status": report.get("status"),
            "plan_row_count": len(rows),
            "cross_episode_locked_skipped": skipped,
            "already_submitted_recovered": [row["id"] for row in rows
                                            if row["id"] not in already and row not in new_rows],
            "to_submit": [row["id"] for row in new_rows],
            "image_to_image_rows": report.get("image_to_image_rows"),
            "deferred_view_rows": [row["id"] for row in deferred],
            "deferred_view_locked_skipped": deferred_locked_skipped,
            "unharvested": unharvested,
            "submitter_precheck": (report.get("submitter_precheck") or {}).get("status"),
            "asset_library_gate_status": (read_json(p.identity_library_gate, {}) or {}).get("status"),
        }
        res.details["rounds"].append(round_rec)
        res.details["subjects_to_generate"] = [row["id"] for row in new_rows]
        res.details["cross_episode_locked_skipped"] = skipped
        res.details["plan_row_count"] = len(rows)
        res.details["submitter_precheck"] = round_rec["submitter_precheck"]
        res.details["asset_library_gate"] = str(p.identity_library_gate)
        res.details["asset_library_gate_status"] = round_rec["asset_library_gate_status"]
        if not pending and round_no == 1:
            res.status = BLOCKED
            res.blockers.append("IDENTITY_PLAN_EMPTY_NOTHING_TO_GENERATE_AND_NOTHING_LOCKED")
            return res

        if not new_rows and not unharvested:
            if deferred:
                # every base plate should exist by now; a deferred view here means
                # a base plate never landed — stop, do not loop forever
                res.status = BLOCKED
                res.blockers.append(
                    "S3_VIEW_ROWS_DEFERRED_BASE_PLATE_MISSING:" + ",".join(row["id"] for row in deferred))
                return res
            complete = True
            ctx.say(f"   round {round_no}: nothing new to submit — "
                    f"{len(rows)} plan rows all paid-for and harvested")
            break

        harvest_argv = [
            VENV, ENGINE / "tools/harvest_giggle_image_batch.py",
            "--submit-report", p.identity_submit,
            "--output-dir", p.identity_harvest_dir,
            "--status-report", p.identity_harvest_status,
            "--raw-dir", p.identity_harvest_dir / "_raw",
            "--watch", "--interval", 15,
        ]
        if new_rows:
            planned = len(new_rows) * image_credits
            total_planned += planned
            ctx.say(f"   round {round_no}: {len(new_rows)} new rows × {image_credits} cr = {planned} cr "
                    f"({len(deferred)} view rows deferred to the next round)")
            auth_status, auth_plan, auth = materialize_paid_authorization(
                ctx, res, sid="S3", target=subset_plan, is_plan=True,
                note=f"round {round_no}: READY_TO_SUBMIT on every new_asset_groups row; "
                     "rows already SUBMITTED_TASK_ID_BOUND are recovered by the submitter without a POST")
            round_rec["paid_authorization"] = auth
            res.details["paid_authorization"] = auth
            if auth_status == BLOCKED:
                res.status = BLOCKED
                res.blockers.append(auth["blocker"])
                return res
            paid_argv = [
                VENV, ENGINE / "tools/submit_giggle_character_asset_plan.py",
                "--plan", auth_plan,
                "--out", p.identity_submit,
                "--concurrency", min(ctx.max_parallel, 6),
            ]
            dry_argv = [
                VENV, ENGINE / "tools/submit_giggle_character_asset_plan.py",
                "--plan", p.identity_plan,
                "--out", p.identity / f"{ctx.episode}_IDENTITY_PRECHECK.json",
                "--precheck-only",
            ]
            status, submit = ctx.paid_step(
                paid_argv, name=f"s3_submit_giggle_character_asset_plan_r{round_no}", sid="S3",
                planned_credits=planned, dry_argv=dry_argv,
                note=(f"round {round_no}. Submitted file is the D-11 materialised copy "
                      f"{auth_plan.name} (authorization_ref = private SUPERVISOR_ORDERS "
                      f"seq={ctx.authority.get('paid_order_seq')} "
                      "order id, provider_post_allowed true).  Rows with reference_images go to "
                      "/api/v1/generation/image-to-image (own base plate or line-owner-supplied source photo), "
                      "rows without go to text-to-image.  Durable transaction store: "
                      f"{ENGINE}/workflow/tasks/giggle_submit_transactions/{ctx.episode}/ — "
                      "re-running never re-charges an already-fingerprinted row."))
            res.steps.append(submit)
            round_rec["submit_status"] = status
            if status == HARD_STOP:
                res.status = HARD_STOP
                res.blockers.append("BUDGET_HARD_STOP_S3")
                return res
            if status == DRY:
                res.status = DRY
                ctx.say("   next (free, needs GIGGLE_API_KEY, no new POST):")
                ctx.say(f"     {q(harvest_argv)}")
                ctx.planned_commands.append({
                    "stage": "S3", "step": f"s3_harvest_giggle_image_batch_r{round_no}",
                    "planned_credits": 0, "paid_argv": [str(x) for x in harvest_argv],
                    "paid_command": q(harvest_argv),
                    "note": "download only, needs GIGGLE_API_KEY, issues no generation POST"})
                if deferred:
                    ctx.say(f"   (dry) {len(deferred)} view rows would be planned in round {round_no + 1} "
                            "once these base plates are harvested")
                break
            if status != PASS:
                # the submitter exits 2 when its credit-statement reconciliation could
                # not bound the charge even though every row was accepted.  Every row
                # SUBMITTED and zero failures = the images exist and the ledger refresh
                # will settle the charge; record it, do not lose the batch.
                submit_report = read_json(p.identity_submit, {}) or {}
                results = submit_report.get("results") or []
                if (results and not submit_report.get("failures")
                        and len(results) == len(rows)
                        and all(r.get("status") == "SUBMITTED" for r in results)):
                    round_rec["submit_warning"] = (
                        "CREDIT_RECONCILIATION_UNBOUNDED:"
                        + str((submit_report.get("credit_reconciliation") or {}).get("status")))
                    res.details.setdefault("warnings", []).append(round_rec["submit_warning"])
                else:
                    res.status = BLOCKED
                    res.blockers.append("IDENTITY_SUBMIT_FAILED")
                    return res
        else:
            ctx.say(f"   round {round_no}: {len(unharvested)} rows already submitted but not harvested")

        harvest = ctx.run(harvest_argv, name=f"s3_harvest_giggle_image_batch_r{round_no}", paid=True)
        res.steps.append(harvest)
        round_rec["harvest_exit"] = harvest["exit_code"]
        round_rec["credit_statement"] = archive_credit_statement(
            ctx, ctx.p.identity_submit, f"{ctx.run_id}_r{round_no}")
        if harvest["exit_code"] != 0:
            res.status = BLOCKED
            res.blockers.append("IDENTITY_HARVEST_FAILED")
            return res
        if not deferred:
            complete = True
            break
    res.planned_credits = total_planned

    if res.status == DRY:
        # rehearsal: report the route, request no review for an incomplete plate set
        res.details["identity_qa"] = {"sub_stage": "S3.qa", "status": DRY,
                                      "reason": "paid rounds not run; plate set incomplete"}
        if not complete:
            res.blockers.append("IDENTITY_PLATE_SET_INCOMPLETE")
        return res
    if not complete:
        res.status = BLOCKED
        res.blockers.append(f"IDENTITY_ROUNDS_EXHAUSTED_AFTER_{S3_MAX_ROUNDS}")
        return res

    # S3.qa — machine identity QA + LOCK + the D-1 character asset registry.
    admission = s3_qa(ctx, res, harvested_dir=p.identity_harvest_dir)
    res.details["identity_qa"] = admission
    if admission["status"] == REVIEW_REQUIRED:
        res.status = REVIEW_REQUIRED
        return res
    if admission["status"] != PASS:
        res.status = admission["status"]
        res.blockers.extend(admission.get("blockers") or [])
    return res


# --------------------------------------------------------------------------- #
# S4 — voices (paid, once per speaking character, 2 credits each)
# --------------------------------------------------------------------------- #
def stage_s4(ctx: Ctx) -> StageResult:
    p = ctx.p
    if not p.speech_payloads.is_file():
        # payloads are produced by bootstrap_voice_references.py (offline, free)
        boot = ctx.run(
            [VENV, RT_TOOLS / "bootstrap_voice_references.py",
             "--episode", ctx.episode,
             "--generation-contract", p.contract,
             "--asset-requirements", p.asset_requirements,
             "--registry-out", p.voice / "voice_registry.skeleton.json",
             "--policy-out", p.voice / "agentcut_voice_policy.json",
             "--task-payloads-out", p.speech_payloads,
             "--report", p.voice_report,
             "--voice-catalog", ctx.p.scope["voice_catalog"],
             "--audio-output-root", p.voice / "references",
             "--dry-run"],
            name="s4_bootstrap_voice_references")
        if boot["exit_code"] != 0 or not p.speech_payloads.is_file():
            res = StageResult(BLOCKED, bootstrap=boot["log"])
            res.steps = [boot]
            res.blockers = [f"SPEECH_TASK_PAYLOADS_MISSING:{p.speech_payloads}"]
            return res

    payloads = read_json(p.speech_payloads, {}) or {}
    tasks = payloads.get("tasks") or []
    registry = read_json(ctx.p.scope["voice_registry"], {}) or {}
    already = locked_voice_entities(registry)
    todo = [task for task in tasks
            if canonical_voice_entity(str(task.get("entity_id") or "")) not in already]

    res = StageResult(PASS)
    res.details = {
        "payloads": str(p.speech_payloads),
        "task_count": len(tasks),
        "already_locked": sorted(already),
        "to_generate": [task["entity_id"] for task in todo],
        "credits_per_task": 2,
        "registry": str(ctx.p.scope["voice_registry"]),
        "registry_write_route": (
            "This orchestrator writes the registry rows directly.  "
            "generate_agentcut_character_voice_references.update_registry is NOT used: "
            "it KeyErrors on non-qingshan entity ids."),
    }
    res.receipts = [str(ctx.p.scope["voice_registry"]), str(p.speech_payloads)]
    if not todo:
        ctx.say("   every speaking character already has a LOCKED_PRODUCTION_READY voice — "
                "nothing to generate")
        return res

    planned = 2 * len(todo)
    res.planned_credits = planned
    budget = ctx.budget_check(planned, label="s4_voices")
    res.steps.append(budget)
    if budget["exit_code"] != 0:
        res.status = HARD_STOP
        res.blockers.append("BUDGET_HARD_STOP_S4")
        return res

    any_dry = False
    for offset, task in enumerate(todo):
        entity = task["entity_id"]
        # charge the guard for every voice still outstanding, not just this one,
        # so the cap is tested against the whole remaining stage
        remaining_credits = 2 * (len(todo) - offset)
        wav = Path(task["post_generation_normalization"]["target_wav"])
        mp3 = Path(task["request"]["output_mp3"])
        voice_id = str(task["request"].get("voice_id") or "").strip()
        if not voice_id:
            res.status = BLOCKED
            res.blockers.append(f"VOICE_ID_NOT_SELECTED:{entity}")
            return res
        safe_entity = re.sub(r"[^A-Za-z0-9._-]+", "_", str(entity)).strip("._")[:48]
        safe_entity = safe_entity or sha256_text(str(entity))[:16]
        scope_id = str(p.scope["scope_id"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", scope_id):
            res.status = BLOCKED
            res.blockers.append(f"SERIES_SCOPE_ID_UNSAFE_FOR_TRANSACTION_PATH:{scope_id}")
            return res
        audio_transaction = (
            AUDIO_TRANSACTION_ROOT / scope_id / ctx.episode
            / "speech" / f"{safe_entity}.json"
        ).resolve()
        argv = [
            VENV, PORTABLE_AUDIO_PROVIDER, "speech-generate",
            str(task["request"]["text"]),
            "--voice-id", voice_id,
            "--emotion", str(task["request"]["emotion"]),
            "--speed", str(task["request"]["speed"]),
            "--output-dir", mp3.parent,
            "--file-name", mp3.name,
            "--poll-interval", "2",
            "--timeout", "300",
            "--transaction", audio_transaction,
            "--paid",
        ]
        norm_argv = [_media.require_ffmpeg() if item == "${FFMPEG}" else str(item)
                     for item in task["post_generation_normalization"]["command"]]
        upload_out = p.voice_upload_dir / f"{entity}_giggle_asset.json"
        # tools/upload_giggle_asset.py: --file / --out / --public  (verified from --help)
        upload_argv = [VENV, ENGINE / "tools/upload_giggle_asset.py",
                       "--file", wav, "--out", upload_out, "--public"]

        status, step = ctx.paid_step(
            argv, name=f"s4_speech_generate_{entity}", sid="S4",
            planned_credits=remaining_credits,
            note=(f"Portable Giggle speech provider, 2 credits. "
                  f"voice_id={voice_id} ({task['request'].get('voice_name')}).  "
                  f"Durable transaction={audio_transaction}; the provider records intent "
                  "before its only POST, binds task_id immediately, and resumes without "
                  "reposting."))
        res.steps.append(step)
        if status == HARD_STOP:
            res.status = HARD_STOP
            res.blockers.append(f"BUDGET_HARD_STOP_S4:{entity}")
            return res
        if status == DRY:
            any_dry = True
            ctx.say(f"   then (free): {q(norm_argv)}")
            ctx.say(f"   then (network write, no credits): {q(upload_argv)}")
            ctx.planned_commands.append({
                "stage": "S4", "step": f"s4_normalize_{entity}", "planned_credits": 0,
                "paid_argv": norm_argv, "paid_command": q(norm_argv),
                "note": "ffmpeg mono/48k/pcm_s16le — free, local"})
            ctx.planned_commands.append({
                "stage": "S4", "step": f"s4_upload_{entity}", "planned_credits": 0,
                "paid_argv": [str(x) for x in upload_argv], "paid_command": q(upload_argv),
                "note": ("upload_giggle_asset.py has NO dry mode and is an unconditional "
                         "network write; it costs no credits and returns asset_id (SD2 "
                         "remote_asset_id), file_url (H3 remote_url) and duration in one call")})
            continue
        if status != PASS:
            res.status = BLOCKED
            res.blockers.append(f"SPEECH_GENERATE_FAILED:{entity}")
            return res
        if not mp3.is_file():
            res.status = BLOCKED
            res.blockers.append(f"SPEECH_OUTPUT_MISSING:{mp3}")
            return res
        norm = ctx.run(norm_argv, name=f"s4_normalize_{entity}")
        res.steps.append(norm)
        if norm["exit_code"] != 0 or not wav.is_file():
            res.status = BLOCKED
            res.blockers.append(f"VOICE_NORMALIZATION_FAILED:{entity}")
            return res
        upload = ctx.run(upload_argv, name=f"s4_upload_{entity}", paid=True)
        res.steps.append(upload)
        receipt = upload_receipt_fields(read_json(upload_out, {}) or {})
        asset_id = receipt.get("asset_id") or receipt.get("assetId")
        if upload["exit_code"] != 0 or not asset_id:
            res.status = BLOCKED
            res.blockers.append(f"VOICE_UPLOAD_FAILED_NO_ASSET_ID:{entity}")
            return res
        write_voice_registry_row(ctx, entity, task, wav, receipt)
        res.receipts.append(str(upload_out))

    if any_dry:
        res.status = DRY
        return res

    # seq=19 (E04 review, C1): the character → voice table with MEASURED reference pitch bands
    # + the co-presence precheck.  REQUIRES_HUMAN (bands overlap > 50 % between characters who
    # share a scene) is the line owner's decision (D-40); FAIL blocks.
    voice_cast_step = ctx.run(
        [VENV, RT_TOOLS / "build_voice_cast.py", "--episode", ctx.episode, "--contract", p.contract,
         "--registry", ctx.p.scope["voice_registry"], "--out", ctx.p.scope["voice_cast"],
         "--report", p.voice / "voice_cast_gate.json"],
        name="s4_build_voice_cast")
    res.steps.append(voice_cast_step)
    res.receipts.append(str(p.voice / "voice_cast_gate.json"))
    res.details["voice_cast"] = {"table": str(ctx.p.scope["voice_cast"]), "report": str(p.voice / "voice_cast_gate.json"),
                                 "exit_code": voice_cast_step["exit_code"],
                                 "stdout_tail": voice_cast_step.get("stdout_tail")}
    if voice_cast_step["exit_code"] == 3:
        res.status = BLOCKED
        res.blockers.append("VOICE_CAST_REQUIRES_HUMAN:" + str(voice_cast_step.get("stdout_tail") or "")[-300:])
    elif voice_cast_step["exit_code"] != 0:
        res.status = BLOCKED
        res.blockers.append("VOICE_CAST_FAIL:" + str(voice_cast_step.get("stdout_tail") or "")[-300:])
    return res


def archive_credit_statement(ctx: "Ctx", submit_report: Path, tag: str) -> str | None:
    """Move ``<report>_credit_statement.json`` to ``<report>_<tag>_credit_statement.json``.

    The engine submitters (submit_giggle_character_asset_plan.py:272,
    submit_giggle_image_manifest.py:659) write the batch credit reconciliation next to the
    submit report under a FIXED name, so every later round of the same stage overwrote the
    previous round's statement and nalu_budget_ledger.py (which sums ``*_credit_statement.json``)
    only ever saw the latest batch.  Observed 2026-09-12: recorded_total went 198 -> 110 -> 44
    while the real identity spend was 352.  The archived name still ends in
    ``_credit_statement.json`` so the ledger glob keeps counting it; the original is moved, not
    copied, so nothing is counted twice.
    """
    src = submit_report.parent / f"{submit_report.stem}_credit_statement.json"
    if not src.is_file():
        return None
    dst = submit_report.parent / f"{submit_report.stem}_{tag}_credit_statement.json"
    os.replace(src, dst)
    ctx.say(f"   credit statement archived: {dst.name}")
    return str(dst)


def upload_receipt_fields(receipt: dict[str, Any]) -> dict[str, Any]:
    """Flatten an upload_giggle_asset.py receipt.

    The Giggle web asset endpoint answers ``{"code":200,"msg":"success","data":{asset_id,
    file_url,duration,...}}``; the tool writes that envelope verbatim.  Observed 2026-09-12 on
    E01 qinming: the pipeline looked for ``asset_id`` at the top level and declared
    VOICE_UPLOAD_FAILED_NO_ASSET_ID although the upload had succeeded.  Merge ``data`` over
    the envelope so both shapes resolve; nothing is invented — every field comes from the
    receipt file.
    """
    if not isinstance(receipt, dict):
        return {}
    data = receipt.get("data")
    if isinstance(data, dict):
        merged = dict(receipt)
        merged.update(data)
        return merged
    return receipt


def write_voice_registry_row(ctx: Ctx, entity: str, task: dict[str, Any],
                             wav: Path, receipt: dict[str, Any]) -> None:
    """Write one production-ready row into the nalu voice registry.

    Deliberately NOT routed through
    tools/generate_agentcut_character_voice_references.update_registry — that
    function indexes a qingshan-only id table and KeyErrors on nalu ids.  Every
    value written here is observed: the asset id and url come from the provider
    receipt, the sha and duration from the file on disk.
    """
    registry = read_json(ctx.p.scope["voice_registry"], {}) or {}
    roles = registry.setdefault("major_roles", [])
    if isinstance(roles, list):
        row = next((item for item in roles
                    if isinstance(item, dict) and item.get("entity_id") == entity), None)
        if row is None:
            row = {"entity_id": entity}
            roles.append(row)
    else:
        row = roles.setdefault(entity, {})
    row.update({
        "entity_id": entity,
        "character": task.get("character"),
        # library_lock_non_plate.lock_voice joins registry rows on character_id (E01 rows were
        # authored with it; the E02 S4 writer had dropped it)
        # E59/v4 contracts use the canonical lowercase character entity id
        # (e.g. ``lianggouer``), while older payload builders sometimes left
        # character_id unset.  Do not synthesize a ``CHAR-*`` id here: the
        # voice-cast and non-plate gates resolve against the contract's exact
        # id.  A fabricated prefix makes a real registered voice invisible to
        # both gates.
        "character_id": task.get("character_id") or str(entity),
        "voice_id": task["request"]["voice_id"],
        "voice_name": task["request"].get("voice_name"),
        "remote_asset_id": receipt.get("asset_id") or receipt.get("assetId"),
        "remote_url": receipt.get("file_url") or receipt.get("fileUrl"),
        "local_reference": str(wav),
        "local_sha256": sha256_file(wav),
        "duration_seconds": receipt.get("duration"),
        "sample_text": task["request"]["text"],
        "language": "zh-CN",
        "capability_id": "AGENTCUT-SPEECH-001",
        "status": "LOCKED_PRODUCTION_READY",
        "recorded_at_utc": now(),
        "recorded_by": TOOL_ID,
        "episode_first_locked": ctx.episode,
        "credits_charged": 2,
        "paid_authorization": {
            "order_id": (ctx.paid_order or {}).get("id"),
            "order_seq": (ctx.paid_order or {}).get("seq"),
            "orders_file_sha256": (ctx.paid_order or {}).get("orders_file_sha256"),
            "source_receipt": (ctx.paid_order or {}).get("source_receipt"),
        },
    })
    registry["updated_at_utc"] = now()
    write_json(ctx.p.scope["voice_registry"], registry)
    ctx.say(f"   voice_registry row LOCKED_PRODUCTION_READY: {entity}")


# --------------------------------------------------------------------------- #
# S3 admission — the ONLY sanctioned route to qa PASS + LOCKED
# --------------------------------------------------------------------------- #
GATE_REGISTRY = ENGINE / "configs/GATE_REGISTRY_v3_20260716.json"


# --------------------------------------------------------------------------- #
# machine-review plumbing (Roger's policy: the line runs continuously, with a
# human check only after a finished episode, so every per-asset QA is a MACHINE
# review — deterministic measurers plus a Claude VLM structured review)
# --------------------------------------------------------------------------- #
def qa_run(ctx: Ctx, argv: list[Any], *, name: str) -> dict[str, Any]:
    """Run one of this pipeline's QA tools.  Always free, never a paid child."""
    step = ctx.run([VENV, *argv], name=name, paid=False, cwd=ENGINE)
    return step


def qa_json(step: dict[str, Any]) -> dict[str, Any]:
    """The machine-readable JSON a QA tool prints.

    stdout_tail is truncated at 4 KB, so a pretty-printed payload can arrive with
    its opening brace missing.  Every QA tool therefore also prints one compact
    single-line summary, and this reads that last complete JSON line, falling
    back to parsing the whole captured stdout.
    """
    text = step.get("stdout_tail") or ""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def latest_submitted_review(ctx: Ctx, kind: str) -> tuple[Path | None, dict[str, Any]]:
    """The newest VALID submitted review of this kind whose media still matches.

    A review is only reusable while every asset it looked at is byte-identical to
    what is on disk now.  A rerolled keyframe therefore invalidates its own review
    automatically and the stage asks for a new one — a review can never be
    inherited by a different image.
    """
    directory = REVIEWS_ROOT / ctx.episode
    if not directory.is_dir():
        return None, {}
    for path in sorted(directory.glob("*_submitted.json"), reverse=True):
        payload = read_json(path)
        if not isinstance(payload, dict) or payload.get("kind") != kind:
            continue
        if (payload.get("validation") or {}).get("status") != "PASS":
            continue
        if str(payload.get("reviewer") or "") != REVIEWER_ID:
            continue
        stale: list[str] = []
        for item in payload.get("items") or []:
            for media in (item.get("request_item") or {}).get("media") or []:
                declared, media_path = media.get("sha256"), media.get("path")
                if not media_path:
                    continue
                if declared != sha256_file(Path(media_path)):
                    stale.append(f"{item.get('item_id')}:{Path(media_path).name}")
        if stale:
            continue
        return path, payload
    return None, {}


def request_review(ctx: Ctx, res: StageResult, kind: str, *, sub_stage: str,
                   note: str = "", items: list[str] | None = None) -> dict[str, Any]:
    """Write a review request, mark the stage REVIEW_REQUIRED, and say how to answer."""
    argv: list[Any] = [VLM_PROTOCOL, "request", "--kind", kind, "--episode", ctx.episode]
    if items:
        argv += ["--items", json.dumps(sorted(items))]
    step = qa_run(ctx, argv, name=f"{sub_stage}_review_request")
    res.steps.append(step)
    payload = qa_json(step)
    request_path = payload.get("request")
    detail = {
        "status": REVIEW_REQUIRED,
        "sub_stage": sub_stage,
        "kind": kind,
        "reviewer": REVIEWER_ID,
        "review_request": request_path,
        "review_request_sha256": payload.get("request_sha256"),
        "items": payload.get("items"),
        "media_missing": payload.get("media_missing"),
        "note": note,
        "how_to_answer": [
            f"{VENV} {VLM_PROTOCOL} example-answers --request {request_path}",
            "open every media path in the request, answer every question of every "
            "item with an enumerated value, write an observation of >=20 chars and "
            "list every defect",
            f"{VENV} {VLM_PROTOCOL} submit --request {request_path} --answers <answers.json>",
            f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} run --episode {ctx.episode} "
            f"--from {sub_stage.split('.')[0].upper()}",
        ],
    }
    res.status = REVIEW_REQUIRED
    res.blockers.append(f"{sub_stage}:REVIEW_REQUIRED:{kind}")
    res.receipts.append(str(request_path) if request_path else "")
    ctx.say(f"   !! {sub_stage}: machine review required ({kind}).  Request written:")
    ctx.say(f"      {request_path}")
    ctx.say(f"      answer it, then: {VENV} {VLM_PROTOCOL} submit --request {request_path} "
            "--answers <answers.json>")
    return detail


# --------------------------------------------------------------------------- #
# S3.qa — identity QA / LOCK (D-3) + the character asset registry (D-1)
# --------------------------------------------------------------------------- #
def s3_qa(ctx: Ctx, res: StageResult, *, harvested_dir: Path) -> dict[str, Any]:
    """Machine identity QA: a Claude VLM plate review + a real insightface cosine.

    Route (all of it real, none of it declared):
      runtime/tools/vlm_review_protocol.py request --kind identity   → the closed
        questionnaire a reviewer answers while looking at every plate;
      runtime/tools/identity_qa_lock.py lock                          → writes
        qa.status PASS/FAIL and status LOCKED (only on PASS) into
        ai_drama.production_asset_library.v1 in the exact shape
        tools/initial_asset_library.py gate demands, with provenance carrying the
        review file sha256, the reviewer id and both timestamps, and with an
        INSIGHTFACE_COSINE_V1 measurement through the engine's own backend;
      identity_qa_lock.py registry                                    → the D-1
        QINGSHAN_CHARACTER_REGISTRY built from LOCKED plates only.

    rights.status stays PENDING: a rights basis is a legal declaration by the line
    owner (R-2 / R-5), not something a reviewer can observe.
    """
    p = ctx.p
    status_step = qa_run(ctx, [IDENTITY_QA_LOCK, "status", "--episode", ctx.episode],
                         name="s3_qa_identity_route_status")
    res.steps.append(status_step)
    route = qa_json(status_step)
    plates = sorted(harvested_dir.glob("*")) if harvested_dir.is_dir() else []
    detail: dict[str, Any] = {
        "sub_stage": "S3.qa",
        "route": route,
        "harvested_dir": str(harvested_dir),
        "harvested_plates": [item.name for item in plates],
        "reviewer": REVIEWER_ID,
    }
    if not plates:
        detail["status"] = BLOCKED
        detail["blockers"] = ["IDENTITY_PLATES_NOT_ON_DISK"]
        detail["reason"] = ("S3 has not produced plates yet (paid step disabled or not run). "
                            "No review is requested for media that does not exist.")
        write_json(p.identity_admission, {
            "schema": "nalu.identity_qa_route_status.v1", "episode": ctx.episode,
            "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
        res.receipts.append(str(p.identity_admission))
        return detail

    review_path, review = latest_submitted_review(ctx, "identity")
    if review_path is None:
        detail.update(request_review(ctx, res, "identity", sub_stage="S3.qa",
                                     note="identity plates changed or were never reviewed"))
        write_json(p.identity_admission, {
            "schema": "nalu.identity_qa_route_status.v1", "episode": ctx.episode,
            "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
        res.receipts.append(str(p.identity_admission))
        return detail

    # identity_qa_lock.py writes qa.status from the review + the real cosine.
    # rights.status can only reach PASS with a NAMED basis, and a rights basis is
    # a legal declaration by the configured line owner — never a reviewer observation.
    lock_argv = [IDENTITY_QA_LOCK, "lock", "--episode", ctx.episode,
                 "--review", review_path,
                 "--rights-basis", ctx.rights_basis]
    detail["rights_basis"] = ctx.rights_declaration
    lock_step = qa_run(ctx, lock_argv, name="s3_qa_identity_lock")
    res.steps.append(lock_step)
    verdict = qa_json(lock_step)
    detail.update({
        "review_file": str(review_path),
        "review_file_sha256": sha256_file(review_path),
        "reviewed_at": review.get("reviewed_at"),
        "verdict_counts": review.get("verdict_counts"),
        "lock": verdict,
        "status": PASS if verdict.get("status") == "PASS" else BLOCKED,
        "blockers": ([] if verdict.get("status") == "PASS"
                     else ["S3_IDENTITY_QA_FAILED"] + list(verdict.get("remaining") or [])),
        "character_registry": str(ctx.p.scope["character_registry"]),
        "character_registry_present": ctx.p.scope["character_registry"].is_file(),
        "rights": (verdict.get("rights")
                   or {"status": "SEE_ASSET_LIBRARY", "basis": ctx.rights_basis}),
    })
    # D-15 (2026-09-12): the engine gate below checks EVERY requirement category, not only
    # the plate subjects D-3 locks.  Lock wardrobe / voices / scenes / reference materials /
    # declared native-audio rows from on-disk evidence first (see the tool's docstring).
    # D-33: library_lock_non_plate reads the S4 speech payloads (voice rows); on a fresh episode S4 has not run
    # yet, so build them here first (offline, free — the same argv stage_s4 uses).
    if not p.speech_payloads.is_file():
        p.voice.mkdir(parents=True, exist_ok=True)
        prep = ctx.run(
            [VENV, RT_TOOLS / "bootstrap_voice_references.py",
             "--episode", ctx.episode,
             "--generation-contract", p.contract,
             "--asset-requirements", p.asset_requirements,
             "--registry-out", p.voice / "voice_registry.skeleton.json",
             "--policy-out", p.voice / "agentcut_voice_policy.json",
             "--task-payloads-out", p.speech_payloads,
             "--report", p.voice_report,
             "--voice-catalog", ctx.p.scope["voice_catalog"],
             "--audio-output-root", p.voice / "references",
             "--dry-run"],
            name="s3_qa_prepare_speech_payloads")
        res.steps.append(prep)
    non_plate_step = qa_run(ctx, [RT_TOOLS / "library_lock_non_plate.py", "lock",
                                  "--episode", ctx.episode,
                                  "--rights-basis", ctx.rights_basis,
                                  "--report", p.identity / f"{ctx.episode}_NON_PLATE_LOCK.json"],
                            name="s3_qa_non_plate_library_lock")
    res.steps.append(non_plate_step)
    detail["non_plate_lock"] = qa_json(non_plate_step)
    # Rebuild after the non-plate lock so reused characters from a previous
    # episode in the same private series scope remain resolvable.
    registry_step = qa_run(ctx, [IDENTITY_QA_LOCK, "registry", "--episode", ctx.episode],
                           name="s3_qa_character_registry_rebuild")
    res.steps.append(registry_step)
    detail["character_registry_rebuild"] = qa_json(registry_step)
    # Bootstrap recompiles a full episode library, while S3 only admits the
    # identity/non-plate assets in the current S3 plan.  Audio accents/SFX and
    # reference-map rows are downstream S4/S2 contracts and must not block the
    # already-locked character/prop admission.  Build a scoped, immutable gate
    # input from the current plan; the full requirements remain authoritative
    # and are checked again by their owning stages.
    scoped_req = p.identity / f"{ctx.episode}_S3_ASSET_GATE_REQUIREMENTS.json"
    full_req = read_json(p.asset_requirements, {}) or {}
    plan_for_gate = read_json(p.identity_plan, {}) or {}
    plan_ids = {str(row.get("id")) for row in (plan_for_gate.get("new_asset_groups") or [])
                if isinstance(row, dict) and row.get("id")}
    scoped = dict(full_req)
    scoped["assets"] = {}
    for category, rows in (full_req.get("assets") or {}).items():
        scoped["assets"][category] = [row for row in rows
                                       if row.get("asset_id") in plan_ids]
    write_json(scoped_req, scoped)
    gate_step = qa_run(ctx, [ENGINE / "tools/initial_asset_library.py", "gate",
                             "--requirements", scoped_req,
                             "--library", p.identity_library,
                             "--episode", ctx.episode,
                             "--report", p.identity_library_gate],
                     name="s3_qa_initial_asset_library_gate")
    res.steps.append(gate_step)
    detail["asset_library_gate_status"] = (read_json(p.identity_library_gate, {}) or {}).get("status")
    detail["asset_library_gate_report"] = str(p.identity_library_gate)
    if detail["asset_library_gate_status"] != PASS:
        detail["status"] = BLOCKED
        detail.setdefault("blockers", []).append(
            f"ASSET_LIBRARY_GATE_{detail['asset_library_gate_status']}")
    write_json(p.identity_admission, {
        "schema": "nalu.identity_qa_route_status.v1", "episode": ctx.episode,
        "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
    res.receipts.append(str(p.identity_admission))
    return detail


def s3_admission(ctx: Ctx, res: StageResult, *, harvested_dir: Path) -> dict[str, Any]:
    """Objective identity admission for the freshly generated plates.

    Route (verified, not guessed):
      tools/character_identity_admission_gate.py  → gate_id CHARACTER-IDENTITY-ADMISSION,
      schema qingshan.character_identity_admission_gate.v3, method INSIGHTFACE_COSINE_V1,
      thresholds taken from configs/GATE_REGISTRY_v3_20260716.json (pass 0.45 / fail 0.30).
      It writes a REPORT and never a LOCKED status.
      tools/initial_asset_library.py gate then demands status=="LOCKED" and
      qa.status=="PASS" — and NO tool in the engine writes those two values.

    This orchestrator therefore refuses to advance S3 past ROUTE_MISSING until
    the two named prerequisites exist.  It never passes
    bootstrap_identity_cards.py --accept-source-qa on its own authority, because
    that flag is an operator declaration, not an engine verdict.
    """
    p = ctx.p
    blockers: list[str] = []
    detail: dict[str, Any] = {
        "route": "tools/character_identity_admission_gate.py (gate CHARACTER-IDENTITY-ADMISSION)",
        "gate_registry": str(GATE_REGISTRY),
        "gate_registry_present": GATE_REGISTRY.is_file(),
        "objective_method": "INSIGHTFACE_COSINE_V1",
        "lock_gate": f"{ENGINE}/tools/initial_asset_library.py gate",
    }
    registry_ok = ctx.p.scope["character_registry"].is_file()
    detail["character_registry"] = str(ctx.p.scope["character_registry"])
    detail["character_registry_present"] = registry_ok
    if not registry_ok:
        blockers.append("D-1_NALU_CHARACTER_ASSET_REGISTRY_ABSENT")
    try:
        __import__("insightface")
        insight = True
    except Exception:
        insight = False
    detail["insightface_runtime_available"] = insight
    if not insight:
        blockers.append("D-2_INSIGHTFACE_RUNTIME_UNAVAILABLE")
    detail["manifest_builder"] = None
    blockers.append("D-3_IDENTITY_ADMISSION_MANIFEST_BUILDER_ABSENT")
    detail["harvested_dir"] = str(harvested_dir)
    detail["harvested_plates"] = sorted(item.name for item in harvested_dir.glob("*")) \
        if harvested_dir.is_dir() else []
    detail["refusal"] = (
        "No qa_status PASS and no LOCKED status is written by this pipeline.  "
        "See PIPELINE_RUNBOOK.md 'Open decisions' D-1..D-3.")
    detail["status"] = ROUTE_MISSING
    detail["blockers"] = blockers
    write_json(p.identity_admission, {
        "schema": "nalu.identity_admission_route_status.v1",
        "episode": ctx.episode, "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
    res.receipts.append(str(p.identity_admission))
    return detail


# --------------------------------------------------------------------------- #
# S5 — keyframes (paid) + Q1 admission + start-frame receipts
# --------------------------------------------------------------------------- #
def stage_s5(ctx: Ctx) -> StageResult:
    p = ctx.p
    library = p.identity_library if p.identity_library.is_file() else ctx.p.scope["asset_library"]
    if not library.is_file():
        res = StageResult(BLOCKED, asset_library=str(library))
        res.blockers = [f"ASSET_LIBRARY_MISSING:{library}"]
        return res

    # E59 was admitted in the dedicated Q1 batch before the runtime adapter was
    # repaired.  When every unit already has a byte-checked Q1 admission and an
    # anchor plan, rebuilding the generic V1 manifest selects zero new tasks;
    # treating that as a paid-stage failure would either stall the line or invite
    # duplicate POSTs.  Reuse the admitted evidence and continue to S6.
    q1_index = p.preprod / "reports/qa/q1" / f"{ctx.episode}_KEYFRAME_Q1_INDEX.json"
    q1 = read_json(q1_index, {}) or {}
    if (q1.get("status") == "ALL_ADMITTED" and p.anchor_plan.is_file()
            and int(q1.get("unit_count") or 0) > 0):
        res = StageResult(PASS)
        res.details = {
            "reuse": "Q1_ALL_ADMITTED",
            "q1_index": str(q1_index),
            "unit_count": q1.get("unit_count"),
            "admitted_count": q1.get("admitted_count"),
            "anchor_plan": str(p.anchor_plan),
            "note": "No new keyframe POST; existing admitted assets are reused by SHA.",
        }
        res.receipts = [str(q1_index), str(p.anchor_plan)]
        return res

    # 1) build the keyframe image manifest (free; runs the submitter's precheck)
    build_argv = [
        VENV, RT_TOOLS / "build_keyframe_manifest.py",
        "--episode", ctx.episode,
        "--preproduction-dir", p.preprod,
        "--contract", p.contract,
        "--asset-library", library,
        "--out", p.keyframe_manifest,
        "--report", p.keyframe_manifest_report,
        "--prompt-dir", p.preprod / "prompts/keyframes",
        "--keyframe-dir", p.keyframes,
        "--engine-root", ENGINE,
        "--python", VENV,
        "--image-resolution", "2K",
        "--precheck-only",
    ]
    build = ctx.run(build_argv, name="s5_build_keyframe_manifest")
    manifest = read_json(p.keyframe_manifest, {}) or {}
    tasks = manifest.get("tasks") or []
    res = StageResult(PASS)
    res.steps = [build]
    res.receipts = [str(p.keyframe_manifest), str(p.keyframe_manifest_report)]
    res.details = {
        "manifest": str(p.keyframe_manifest),
        "task_count": len(tasks),
        "build_report": (read_json(p.keyframe_manifest_report, {}) or {}).get("status"),
        "asset_library_used": str(library),
        "keyframe_dir": str(p.keyframes),
        "naming_contract": "{shot_id}-keyframe-v1.png (flat dir; build_video_unit_anchor_plan globs it)",
    }
    if build["exit_code"] != 0 or not tasks:
        res.status = BLOCKED
        res.blockers.append("KEYFRAME_MANIFEST_NOT_BUILT")
        res.details["hint"] = ("build_keyframe_manifest.py needs a LOCKED asset library; "
                              "S3 must reach PASS first (see open decisions D-1..D-3).")
        return res

    # 1b) entry-state discipline gate (free, pre-generation)
    entry = ctx.run([VENV, ENGINE / "tools/keyframe_entry_state_gate.py",
                     p.keyframe_manifest, "--output", p.keyframe_entry_gate],
                    name="s5_keyframe_entry_state_gate")
    res.steps.append(entry)
    res.receipts.append(str(p.keyframe_entry_gate))
    res.details["keyframe_entry_state_gate"] = (read_json(p.keyframe_entry_gate, {}) or {}).get("status")

    # 2) D-11 paid authorisation, then the paid submit of the MATERIALISED manifest.
    planned = ctx.planned_credits("S5")
    auth_status, auth_manifest, auth = materialize_paid_authorization(
        ctx, res, sid="S5", target=p.keyframe_manifest, is_plan=False,
        note=("the image submitter's validate_submission_authority additionally demands "
              "EXACTLY ONE GIGGLE-REROLL-COST-GUARD report whose reviewed_manifest_sha256 "
              "equals the submitted manifest's own SHA — that report is what this produces"))
    res.details["paid_authorization"] = auth
    if auth_status == BLOCKED:
        res.status = BLOCKED
        res.blockers.append(auth["blocker"])
        return res
    paid_argv = [VENV, ENGINE / "tools/submit_giggle_image_manifest.py",
                 "--manifest", auth_manifest, "--out", p.keyframe_submit,
                 "--concurrency", min(ctx.max_parallel, 6)]
    dry_argv = [VENV, ENGINE / "tools/submit_giggle_image_manifest.py",
                "--manifest", p.keyframe_manifest,
                "--out", p.preprod_reports / f"{ctx.episode}_KEYFRAME_PRECHECK.json",
                "--precheck-only"]
    status, submit = ctx.paid_step(
        paid_argv, name="s5_submit_giggle_image_manifest", sid="S5",
        planned_credits=planned, dry_argv=dry_argv,
        note=(f"Submitted file is the D-11 materialised copy {auth_manifest.name}.  "
              "Durable transaction store "
              f"{ENGINE}/workflow/tasks/giggle_submit_transactions/{ctx.episode}/ — a task "
              "whose submission_fingerprint (task_key+prompt_sha+ref shas+model+aspect+"
              "resolution) is already SUBMITTED_TASK_ID_BOUND is recovered, never re-POSTed. "
              "--precheck-only SKIPS validate_submission_authority, so the paid run "
              "additionally requires provider_post_allowed=true, "
              "maximum_new_submissions>=len(tasks), a non-empty authorization_ref, and "
              "EXACTLY ONE machine_gate_reports entry with gate_id GIGGLE-REROLL-COST-GUARD "
              "whose reviewed_manifest_sha256 equals this manifest's SHA."))
    res.steps.append(submit)
    res.planned_credits = planned
    if status == HARD_STOP:
        res.status = HARD_STOP
        res.blockers.append("BUDGET_HARD_STOP_S5")
        return res

    # 3) harvest + deterministic rename
    harvest_argv = [VENV, ENGINE / "tools/harvest_giggle_image_batch.py",
                    "--submit-report", p.keyframe_submit,
                    "--output-dir", p.keyframe_harvest_dir,
                    "--status-report", p.keyframe_harvest_status,
                    "--raw-dir", p.keyframe_harvest_dir / "_raw",
                    "--watch", "--interval", 15]
    if status == DRY:
        res.status = DRY
        precheck = (submit.get("precheck") or {})
        res.details["submit_precheck_exit"] = precheck.get("exit_code")
        if precheck.get("exit_code") not in (None, 0):
            # the paid command is still printed, but this manifest would be
            # rejected today — say so instead of implying it is ready to submit
            lines = [row for row in (precheck.get("stderr_tail") or "").splitlines() if row.strip()]
            res.blockers.append("KEYFRAME_MANIFEST_PRECHECK_FAILS:" + (lines[-1] if lines else "?"))
        ctx.say("   then (needs GIGGLE_API_KEY, no new POST, no dry mode exists):")
        ctx.say(f"     {q(harvest_argv)}")
        ctx.planned_commands.append({
            "stage": "S5", "step": "s5_harvest_giggle_image_batch", "planned_credits": 0,
            "paid_argv": [str(x) for x in harvest_argv], "paid_command": q(harvest_argv),
            "note": ("harvest_giggle_image_batch.py has NO dry mode; the query-only "
                     "substitute is poll_giggle_submit_report.py without --download")})
        rename = plan_keyframe_renames(ctx, manifest)
        res.details["deterministic_rename"] = rename
    elif status == PASS:
        harvest = ctx.run(harvest_argv, name="s5_harvest_giggle_image_batch", paid=True)
        res.steps.append(harvest)
        res.details["credit_statement"] = archive_credit_statement(
            ctx, ctx.p.keyframe_submit, ctx.run_id)
        if harvest["exit_code"] != 0:
            res.status = BLOCKED
            res.blockers.append("KEYFRAME_HARVEST_FAILED")
            return res
        rename = apply_keyframe_renames(ctx, manifest)
        res.details["deterministic_rename"] = rename
        if rename.get("missing"):
            res.status = BLOCKED
            res.blockers.append("KEYFRAME_RENAME_SOURCE_MISSING")
            return res
    else:
        res.status = BLOCKED
        res.blockers.append("KEYFRAME_SUBMIT_FAILED")
        return res

    # 4) S5.q1 — keyframe Q1 admission (D-4)
    q1 = s5_q1(ctx, res)
    res.details["q1_admission"] = q1
    if q1["status"] == REVIEW_REQUIRED:
        res.status = REVIEW_REQUIRED
        return res
    if q1["status"] != PASS:
        res.status = q1["status"] if res.status != DRY else DRY
        res.blockers.extend(q1.get("blockers") or [])
        return res

    # 5) S5.sfe — start-frame observation receipts (D-5)
    sfe = s5_sfe(ctx, res)
    res.details["start_frame_evidence"] = sfe
    if sfe["status"] == REVIEW_REQUIRED:
        res.status = REVIEW_REQUIRED
        return res
    if sfe["status"] != PASS:
        res.status = sfe["status"] if res.status != DRY else DRY
        res.blockers.extend(sfe.get("blockers") or [])
    return res


def keyframe_rename_map(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """{harvested file} -> {shot_id}-keyframe-v1.png, from output_contract.

    The authority for the destination name is each task's
    output_contract.expected_output_path, which build_keyframe_manifest.py fills
    in; build_video_unit_anchor_plan.py globs `{shot_id}-keyframe-v*.png` in a
    single flat directory and takes the highest version.
    """
    rows: list[dict[str, Any]] = []
    for task in manifest.get("tasks") or []:
        contract = task.get("output_contract") or {}
        expected = contract.get("expected_output_path")
        rows.append({
            "task_key": task.get("task_key"),
            "shot_id": task.get("shot_id") or task.get("unit_id"),
            "expected_output_path": expected,
            "destination_name": Path(expected).name if expected else None,
        })
    return rows


def plan_keyframe_renames(ctx: Ctx, manifest: dict[str, Any]) -> dict[str, Any]:
    rows = keyframe_rename_map(manifest)
    return {"mode": "PLANNED_ONLY", "keyframe_dir": str(ctx.p.keyframes),
            "count": len(rows), "map": rows,
            "rule": "harvested <task_key>.png -> output_contract.expected_output_path"}


def apply_keyframe_renames(ctx: Ctx, manifest: dict[str, Any]) -> dict[str, Any]:
    p = ctx.p
    p.keyframes.mkdir(parents=True, exist_ok=True)
    moved, missing = [], []
    for row in keyframe_rename_map(manifest):
        expected = row.get("expected_output_path")
        if not expected:
            missing.append({"task_key": row["task_key"], "reason": "NO_EXPECTED_OUTPUT_PATH"})
            continue
        dest = Path(expected)
        if not dest.is_absolute():
            dest = ENGINE / dest
        if dest.is_file():
            moved.append({"task_key": row["task_key"], "dest": str(dest), "action": "ALREADY_PRESENT"})
            continue
        # harvest_giggle_image_batch.py names files <EP>_<task key>_<task id>.png (observed
        # 2026-09-13: 29 harvested, 29 "NO_HARVESTED_FILE"); accept both spellings.
        candidates = sorted(set(p.keyframe_harvest_dir.glob(f"{row['task_key']}*"))
                            | set(p.keyframe_harvest_dir.glob(f"{ctx.episode}_{row['task_key']}_*")))
        if not candidates:
            missing.append({"task_key": row["task_key"], "reason": "NO_HARVESTED_FILE",
                            "searched": str(p.keyframe_harvest_dir)})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidates[0], dest)
        moved.append({"task_key": row["task_key"], "src": str(candidates[0]),
                      "dest": str(dest), "sha256": sha256_file(dest), "action": "RENAMED"})
    return {"mode": "APPLIED", "keyframe_dir": str(p.keyframes),
            "moved": moved, "missing": missing}


def apply_line_owner_q1_acceptance(ctx: Ctx, index: dict[str, Any], index_path: Path) -> dict[str, Any]:
    """Order-keyed acceptance of CHARACTER-IDENTITY-ADMISSION failures at S5 Q1.

    The engine gate result keeps its FAIL row and evidence; a unit is admitted only when an active line-owner order of kind
    GATE_FAIL_ACCEPTANCE for this episode and gate names EVERY failing "<item_id>:<character_id>" detector of
    that keyframe and the order's item binding exactly matches the current keyframe sha256. Never self-issued; anything
    outside the order (another gate failing, another sha, another episode) stays rejected."""
    orders_path = ctx.authority.get("orders_path")
    orders = (_rga._orders(orders_path,
                           expected_latest_seq=ctx.authority.get("latest_order_seq") or 0,
                           engine_root=ENGINE)
              if orders_path and not ctx.authority_blockers else [])
    gate_id = "CHARACTER-IDENTITY-ADMISSION"
    ident = read_json(Path(str((index.get("identity_measurement") or {}).get("engine_report") or "")), {}) or {}
    decisions = ((ident.get("objective_verification") or {}).get("decisions")) or []
    accepted, still_rejected = [], []
    allowed = list(index.get("video_submission_allowed_unit_ids") or [])
    for row in index.get("results") or []:
        if row.get("status") == "PASS" or row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT":
            continue
        item_id, uid = row.get("item_id"), row.get("unit_id")
        failures = [str(f) for f in (row.get("failures") or [])]
        if not failures or any(gate_id not in f for f in failures):
            still_rejected.append(uid)
            continue
        detectors = sorted({f"{item_id}:{d.get('character_id')}" for d in decisions
                            if str(d.get("source_id") or "").endswith(f":{item_id}")
                            and d.get("decision") not in ("PASS", "ADMIT_BEST_EFFORT")})
        if not detectors:
            # D-70: a keyframe where InsightFace found NO face sample for a declared character has no
            # decision row at all (NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:<char>).  That failure is
            # still a "<item>:<char>" detector the line owner can accept by order (same sha binding).
            texts = list(failures)
            req = read_json(Path(str(row.get("admission_request") or "")), {}) or {}
            for ev in req.get("evidence") or []:
                if isinstance(ev, dict) and str(ev.get("gate_id") or "") == gate_id:
                    texts.append(str(ev.get("finding") or ""))
                    # the request copy of the finding is a summary; the registered evidence file carries
                    # the detector list (failures=NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:<char>,...)
                    evp = str(ev.get("evidence_path") or "")
                    if evp:
                        evd = read_json(Path(evp) if Path(evp).is_absolute() else ENGINE / evp, {}) or {}
                        texts.append(str(evd.get("finding") or ""))
            detectors = sorted({f"{item_id}:{m}" for f in texts
                                for m in re.findall(r"NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER:(CHAR-[A-Z0-9-]+)", f)})
        order = _rga.find_acceptance(
            orders, episode=ctx.episode, gate_id=gate_id, failing=detectors,
            media_sha256=str(row.get("asset_sha256") or ""), media_item_id=item_id,
            expected_issuer=ctx.authority.get("line_owner_id") or "", engine_root=ENGINE,
        ) if detectors else None
        if order is None:
            still_rejected.append(uid)
            continue
        cos = {f"{item_id}:{d.get('character_id')}": d.get("aggregate_median") for d in decisions
               if str(d.get("source_id") or "").endswith(f":{item_id}")}
        record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=gate_id, failing=detectors,
                                        media_sha256=str(row.get("asset_sha256") or ""),
                                        media_item_id=item_id,
                                        gate_result_path=str(row.get("admission_result") or ""))
        record.update({"item_id": item_id, "unit_id": uid, "cosines": cos, "engine_status": row.get("status"),
                       "engine_failures": failures})
        row.update({"engine_status": row.get("status"), "engine_failures": failures,
                    "status": "ADMITTED_BY_LINE_OWNER_ORDER", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                    "failures": [], "line_owner_acceptance": record})
        ar_path = Path(str(row.get("admission_result") or ""))
        if ar_path.is_file():
            engine_copy = ar_path.with_suffix(".engine.json")
            if not engine_copy.is_file():
                shutil.copy2(ar_path, engine_copy)
            ar = read_json(ar_path, {}) or {}
            ar.update({"engine_status": ar.get("status"), "engine_downstream_status": ar.get("downstream_status"),
                       "engine_failures": list(ar.get("failures") or []), "engine_result_copy": str(engine_copy),
                       "status": "ADMITTED_BY_LINE_OWNER_ORDER", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                       "failures": [], "line_owner_acceptance": record})
            write_json(ar_path, ar)
        if uid not in allowed:
            allowed.append(uid)
        accepted.append(record)
    if accepted:
        engine_index = index_path.with_suffix(".engine.json")
        if not engine_index.is_file() and index_path.is_file():
            shutil.copy2(index_path, engine_index)
        index["video_submission_allowed_unit_ids"] = allowed
        index["rejected_unit_ids"] = still_rejected
        index["admitted_count"] = len(allowed)
        index["engine_status"] = index.get("engine_status") or index.get("status")
        index["status"] = ("ALL_ADMITTED" if not still_rejected
                           else f"PARTIAL_{len(allowed)}_OF_{index.get('unit_count')}_ADMITTED")
        index["status_basis"] = "ENGINE_ADMITTED+LINE_OWNER_ORDER_ACCEPTANCE (source-receipted, never self-issued)"
        index["line_owner_gate_acceptance"] = accepted
        write_json(index_path, index)
        write_json(ctx.p.preprod_reports / "qa" / "q1" / f"{ctx.episode}_LINE_OWNER_GATE_ACCEPTANCE.json", {
            "schema": "nalu.q1_line_owner_gate_acceptance.v2", "episode": ctx.episode, "gate_id": gate_id,
            "recorded_at": now(), "recorded_by": TOOL_ID, "orders_path": str(orders_path),
            "accepted": accepted, "still_rejected_unit_ids": still_rejected})
    return {"accepted_unit_ids": [r["unit_id"] for r in accepted], "still_rejected_unit_ids": still_rejected,
            "effective_status": index.get("status")}


# Historical API alias for old runtime callers. New receipts and state keys are neutral.
apply_roger_q1_acceptance = apply_line_owner_q1_acceptance


def s5_q1(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """D-4 — keyframe Q1 admission through the engine's own admission gate.

    tools/shot_media_admission_gate.py is the ONLY engine code that writes
    status ADMITTED|ADMITTED_WITH_P2 with downstream_status
    ADMITTED_FOR_VIDEO_SUBMIT (:645-652).  runtime/tools/keyframe_q1_builder.py
    is the parameterised builder of its qingshan.shot_media_admission_request.v2
    input.  Each of the three P0 objective blocks is a real run:

      VLM_STRUCTURED_STATE_QA_V1     the submitted keyframe review
      CLOSED_SET_ANACHRONISM_OCR_V1  tools/still_image_ocr_audit.py (RapidOCR)
      INSIGHTFACE_COSINE_V1          the engine's own identity gate + backend
    """
    p = ctx.p
    p.preprod_reports.mkdir(parents=True, exist_ok=True)
    status_step = qa_run(ctx, [KEYFRAME_Q1, "status", "--episode", ctx.episode],
                         name="s5_q1_route_status")
    res.steps.append(status_step)
    route = qa_json(status_step)
    keyframes = sorted(p.keyframes.glob("*-keyframe-v*.png")) if p.keyframes.is_dir() else []
    detail: dict[str, Any] = {
        "sub_stage": "S5.q1",
        "route": route,
        "reviewer": REVIEWER_ID,
        "keyframes_on_disk": len(keyframes),
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "required_evidence_gates": ["CHARACTER-IDENTITY-ADMISSION", "SCENE-AUTHORITY-LOCK",
                                    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                                    "PERIOD-ANACHRONISM-LOCK"],
        "terminal_state_required": "status ADMITTED|ADMITTED_WITH_P2 + "
                                   "downstream_status ADMITTED_FOR_VIDEO_SUBMIT",
    }
    if not keyframes:
        detail["status"] = BLOCKED
        detail["blockers"] = ["KEYFRAMES_NOT_ON_DISK"]
        detail["reason"] = ("S5 has not produced keyframes yet (paid step disabled or not "
                            "run).  No review is requested for media that does not exist.")
        write_json(p.keyframe_admission, {
            "schema": "nalu.keyframe_q1_route_status.v1", "episode": ctx.episode,
            "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
        res.receipts.append(str(p.keyframe_admission))
        return detail

    review_path, review = latest_submitted_review(ctx, "keyframe")
    if review_path is None:
        detail.update(request_review(ctx, res, "keyframe", sub_stage="S5.q1",
                                     note="keyframes changed or were never reviewed"))
        write_json(p.keyframe_admission, {
            "schema": "nalu.keyframe_q1_route_status.v1", "episode": ctx.episode,
            "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
        res.receipts.append(str(p.keyframe_admission))
        return detail

    build_step = qa_run(ctx, [KEYFRAME_Q1, "build", "--episode", ctx.episode,
                              "--review", review_path], name="s5_q1_build_admission")
    res.steps.append(build_step)
    verdict = qa_json(build_step)
    index_path = Path(verdict.get("out") or "")
    index = read_json(index_path, {}) or {}
    acceptance = apply_line_owner_q1_acceptance(ctx, index, index_path) if index else {}
    effective = index.get("status") or verdict.get("status")
    detail.update({
        "review_file": str(review_path),
        "review_file_sha256": sha256_file(review_path),
        "reviewed_at": review.get("reviewed_at"),
        "verdict_counts": review.get("verdict_counts"),
        "q1_index": verdict.get("out"),
        "q1_status": verdict.get("status"),
        "q1_effective_status": effective,
        "line_owner_gate_acceptance": acceptance,
        "admitted": index.get("admitted_count", verdict.get("admitted")),
        "units": verdict.get("units"),
        "admitted_unit_ids": index.get("video_submission_allowed_unit_ids"),
        "rejected_unit_ids": index.get("rejected_unit_ids"),
        "identity_measurement": index.get("identity_measurement"),
        "status": PASS if effective == "ALL_ADMITTED" else BLOCKED,
        "blockers": ([] if effective == "ALL_ADMITTED"
                     else ["Q1_NOT_ALL_ADMITTED"]),
    })
    write_json(p.keyframe_admission, {
        "schema": "nalu.keyframe_q1_route_status.v1", "episode": ctx.episode,
        "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
    res.receipts.append(str(p.keyframe_admission))
    return detail


def s5_sfe(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """D-5 — the qingshan.start_frame_semantic_evidence.v1 receipt per unit.

    grouped_anchor_semantic_contract.validate_start_anchor_semantics (reached
    from compile_grouped_seedance_manifest.py:849-859) re-reads the receipt named
    by the contract's evidence_ref and compares every observed list and all three
    booleans for identity.  runtime/tools/start_frame_evidence_writer.py writes
    it from a submitted start_frame review with
    review_method CLAUDE_VLM_STRUCTURED_REVIEW, at the path
    build_nalu_preproduction.py already declares in expected_evidence_ref.
    """
    p = ctx.p
    p.start_frame_evidence.mkdir(parents=True, exist_ok=True)
    status_step = qa_run(ctx, [START_FRAME_EVIDENCE, "status", "--episode", ctx.episode],
                         name="s5_sfe_route_status")
    res.steps.append(status_step)
    route = qa_json(status_step)
    detail: dict[str, Any] = {
        "sub_stage": "S5.sfe",
        "route": route,
        "reviewer": REVIEWER_ID,
        "receipt_schema": "qingshan.start_frame_semantic_evidence.v1",
        "receipt_dir": str(ENGINE / "reports/start_frame_evidence"),
        "consumer": f"{ENGINE}/tools/grouped_anchor_semantic_contract.py "
                    "(via compile_grouped_seedance_manifest.py:849-859)",
    }
    keyframes = sorted(p.keyframes.glob("*-keyframe-v*.png")) if p.keyframes.is_dir() else []
    if not keyframes:
        detail["status"] = BLOCKED
        detail["blockers"] = ["KEYFRAMES_NOT_ON_DISK"]
        return detail

    review_path, review = latest_submitted_review(ctx, "start_frame")
    if review_path is None:
        detail.update(request_review(ctx, res, "start_frame", sub_stage="S5.sfe",
                                     note="start-frame observation receipts require a "
                                          "keyframe-vs-entry_state comparison"))
        return detail

    write_step = qa_run(ctx, [START_FRAME_EVIDENCE, "write", "--episode", ctx.episode,
                              "--review", review_path], name="s5_sfe_write_receipts")
    res.steps.append(write_step)
    verdict = qa_json(write_step)
    verify_step = qa_run(ctx, [START_FRAME_EVIDENCE, "verify", "--episode", ctx.episode],
                         name="s5_sfe_verify")
    res.steps.append(verify_step)
    detail.update({
        "review_file": str(review_path),
        "review_file_sha256": sha256_file(review_path),
        "reviewed_at": review.get("reviewed_at"),
        "receipts_written": verdict.get("units"),
        "receipts_pass": verdict.get("pass"),
        "index": verdict.get("out"),
        "engine_verify_exit_code": verify_step.get("exit_code"),
        "status": PASS if verdict.get("status") == PASS else BLOCKED,
        "blockers": [] if verdict.get("status") == PASS else ["START_FRAME_EVIDENCE_NOT_PASS"],
    })
    res.receipts.append(str(verdict.get("out") or ""))
    return detail


# --------------------------------------------------------------------------- #
# S6 — video (paid) + post-generation QA
# --------------------------------------------------------------------------- #
#: `--project-root` for every video-submitter invocation.
#:
#: The runbook originally prescribed the RUNTIME here.  That is wrong twice over:
#:   1. `authoritative_pipeline_tools_dir()` resolves
#:      `<project-root>/tools/production_video_submission_gate.py` and raises
#:      "Production video gate is unavailable" BEFORE any manifest validation —
#:      hence VIDEO_SUBMIT_ENV, which points BACKLOT_PIPELINE_TOOLS_DIR at the
#:      engine's tools dir (WIRING_NOTES, last section);
#:   2. `production_video_submission_gate.evaluate_manifest(..., root=ROOT)`
#:      resolves every task's RELATIVE `prompt_file`
#:      (`workflow/nalu/<EP>/preproduction/video_prompts/<UNIT>.txt`) against the
#:      same root, so a runtime root can only ever report
#:      CURRENT_PROMPT_FILE_MISSING, even after stage 4.4 compiles the prompts.
#: build_nalu_preproduction.py's own stage-5/5b invocations already use the
#: engine root, and this now matches them.
VIDEO_PROJECT_ROOT = ENGINE
SELECTIVE_BGM = RT_TOOLS / "nalu_selective_bgm.py"


def selective_bgm_transaction_dir(ctx: Ctx) -> Path:
    """Current projects isolate same-numbered episodes by series scope.

    Historical replay keeps its original ``<store>/<episode>`` location; only
    the current portable policy uses ``<store>/<scope>/<episode>``.
    """
    scope_id = str(ctx.p.scope["scope_id"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", scope_id):
        raise RuntimeError(f"SERIES_SCOPE_ID_UNSAFE_FOR_TRANSACTION_PATH:{scope_id}")
    base = ENGINE / "workflow/tasks/giggle_bgm_transactions"
    path = (base / scope_id / ctx.episode) if _policy.is_current() else (base / ctx.episode)
    return path.resolve()


def selective_bgm_common_argv(ctx: Ctx) -> list[Any]:
    """Bind BGM receipts to this run's exact private layer and episode work paths."""
    return ["--episode", ctx.episode, "--contract", ctx.p.contract,
            "--assembly", ctx.p.assembly, "--grouping", ctx.p.grouping_plan,
            "--project", ctx.p.agentcut_project,
            "--bgm-transactions-dir", selective_bgm_transaction_dir(ctx)]


def s6_selective_bgm_sources(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """Create and (when paid) generate selective-BGM sources inside S6.

    The source plan reads only the generation contract.  It does not need the
    rendered S7 release timeline.  Consequently this is the sole provider-POST
    route for BGM; S7 can only verify, place, reconcile, QA, and mix the already
    completed durable transactions.
    """
    contract = read_json(ctx.p.contract, {}) or {}
    bgm = (contract.get("audio_contract") or {}).get("bgm")
    mode = str((bgm or {}).get("mode") or (bgm or {}).get("usage_mode") or "").upper() \
        if isinstance(bgm, dict) else ""
    if mode not in {"SELECTIVE", "SELECTIVE_NARRATIVE_CUES"}:
        return {"status": "NOT_APPLICABLE", "mode": mode or "UNDECLARED", "provider_posts": 0}

    common = selective_bgm_common_argv(ctx)
    source = ctx.run([VENV, SELECTIVE_BGM, "source-plan", *common], name="s6_bgm_source_plan")
    res.steps.append(source)
    if source["exit_code"] != 0:
        return {"status": BLOCKED, "blocker": "SELECTIVE_BGM_SOURCE_PLAN_FAILED",
                "provider_posts": 0, "source_plan_step": source}

    pending_step = ctx.run([VENV, SELECTIVE_BGM, "pending", *common], name="s6_bgm_pending")
    res.steps.append(pending_step)
    pending = qa_json(pending_step) if pending_step["exit_code"] == 0 else {}
    if pending_step["exit_code"] != 0 or pending.get("status") != PASS:
        return {"status": BLOCKED, "blocker": "SELECTIVE_BGM_PENDING_CHECK_FAILED",
                "provider_posts": 0, "pending_step": pending_step}
    planned = int(pending.get("planned_credits") or 0)
    keys = list(pending.get("pending") or [])
    new_post_candidates = list(pending.get("new_post_candidates") or [])

    if not keys:
        verify = ctx.run([VENV, SELECTIVE_BGM, "verify", *common], name="s6_bgm_verify_existing")
        res.steps.append(verify)
        return {"status": PASS if verify["exit_code"] == 0 else BLOCKED,
                "blocker": None if verify["exit_code"] == 0 else "SELECTIVE_BGM_TRANSACTION_VERIFY_FAILED",
                "source_plan": qa_json(source), "pending": pending,
                "provider_posts": 0, "verify": qa_json(verify)}

    paid_argv = [VENV, SELECTIVE_BGM, "generate", *common, "--paid"]
    dry_argv = [VENV, SELECTIVE_BGM, "generate", *common]
    status, generation = ctx.paid_step(
        paid_argv, name="s6_bgm_generate", sid="S6", planned_credits=planned,
        dry_argv=dry_argv, extra_env={"NALU_PAID_CONFIG_LOCK": "1"},
        note=("Selective BGM is generated in S6 from a contract-only source plan.  "
              "tools/storyclaw_audio_provider.py requires an absolute per-source transaction path, "
              "flock, intent-before-POST, immediate task binding, and refuses automatic retry after "
              "a lost response.  S7 has no generate command and performs zero provider POSTs."))
    res.steps.append(generation)
    res.planned_credits += planned
    if status in {HARD_STOP, BLOCKED}:
        return {"status": status, "blocker": ("BUDGET_HARD_STOP_S6_BGM" if status == HARD_STOP
                                                else "SELECTIVE_BGM_GENERATION_FAILED"),
                "pending": pending, "planned_credits": planned,
                "provider_posts": (0 if status == HARD_STOP else None),
                "provider_post_evidence": "SEE_DURABLE_TRANSACTIONS"}
    if status == DRY:
        return {"status": DRY, "pending": pending, "planned_credits": planned,
                "provider_posts": 0, "precheck": generation.get("precheck")}

    verify = ctx.run([VENV, SELECTIVE_BGM, "verify", *common], name="s6_bgm_verify_generated")
    res.steps.append(verify)
    if verify["exit_code"] != 0:
        return {"status": BLOCKED, "blocker": "SELECTIVE_BGM_TRANSACTION_VERIFY_FAILED",
                "pending": pending, "planned_credits": planned,
                "provider_posts": len(keys), "verify": qa_json(verify)}
    return {"status": PASS, "pending_before": keys, "planned_credits": planned,
            "provider_posts": len(new_post_candidates),
            "resumed_without_post": list(pending.get("resume_without_post") or []),
            "verify": qa_json(verify)}


def video_submit_argv(ctx: Ctx, *, manifest: Path, concurrency: int) -> list[Any]:
    return [VENV, ENGINE / "tools/submit_giggle_video_manifest_v2.py",
            "--manifest", manifest, "--out", ctx.p.video_submit,
            "--concurrency", concurrency, "--project-root", VIDEO_PROJECT_ROOT]


def video_preflight_argv(ctx: Ctx) -> list[Any]:
    """`qingshan video-preflight` is literally the submitter with --precheck-only."""
    return [VENV, "-m", "qingshan_engine.cli", "video-preflight",
            "--manifest", ctx.p.video_transaction, "--out", ctx.p.video_preflight,
            "--project-root", VIDEO_PROJECT_ROOT]


def video_poll_argv(ctx: Ctx) -> list[Any]:
    return [VENV, ENGINE / "tools/poll_giggle_submit_report.py",
            "--submit-report", ctx.p.video_submit,
            "--out-dir", ctx.p.video_media,
            "--status-report", ctx.p.video_remote_status,
            "--download"]


def unit_dependency_order(ctx: Ctx) -> list[tuple[str, str | None, bool]]:
    """(unit_id, previous_unit_id or None, needs_previous_tail) in grouping order, from the
    FULL anchor plan.  A unit needs the previous unit's real final frame when its anchor
    roles include PREVIOUS_REAL_TAIL_STATE_AUTHORITY or PREVIOUS_UNIT_REAL_FINAL_FRAME."""
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    # A wave build rewrites <EP>_VIDEO_UNIT_ANCHOR_PLAN_V1.json with only the ready subset, so
    # prefer the full-grouping copy the builder writes alongside; fall back to the main file
    # only when it still covers every unit of the grouping plan.
    order = [u["unit_id"] for u in plan.get("units") or []]
    anchors = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_ANCHOR_PLAN_V1.json", {}) or {}
    by_unit = {row["unit_id"]: row for row in anchors.get("units") or []}
    missing = [uid for uid in order if uid not in by_unit]
    if missing:
        raise RuntimeError(f"wave scheduler: anchor plan lacks {len(missing)} unit(s) of the grouping plan "
                           f"(e.g. {missing[:3]}); refuse to treat them as ready")
    rows = []
    for idx, uid in enumerate(order):
        roles = ((by_unit.get(uid) or {}).get("anchor_count_decision") or {}).get("anchor_roles") or []
        needs = any("PREVIOUS" in str(r) for r in roles)
        rows.append((uid, order[idx - 1] if idx > 0 else None, needs))
    return rows


def extract_real_final_frame(ctx: Ctx, unit_id: str) -> dict[str, Any]:
    """ffmpeg last-frame grab of the harvested unit video (same recipe as the engine's
    episode_parallel_batch_supervisor.bind_predecessor_tail_frame: -sseof -0.10/-0.20/-0.50)."""
    src = ctx.p.video_media / f"{unit_id}.mp4"
    dst_dir = ctx.p.preprod / "real_final_frames"; dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{unit_id}.png"
    if not src.is_file():
        return {"unit_id": unit_id, "status": "SOURCE_MISSING", "source": str(src)}
    if dst.is_file():
        return {"unit_id": unit_id, "status": "ALREADY_PRESENT", "path": str(dst), "sha256": sha256_file(dst)}
    for off in ("-0.10", "-0.20", "-0.50"):
        proc = subprocess.run([_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-sseof", off,
                               "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)], check=False)
        if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return {"unit_id": unit_id, "status": "EXTRACTED", "path": str(dst), "sha256": sha256_file(dst),
                    "source": str(src), "source_sha256": sha256_file(src), "sseof": off}
    return {"unit_id": unit_id, "status": "EXTRACT_FAILED", "source": str(src)}


PROVIDER_VOICE_REFERENCE_SECONDS = (2.0, 15.0)


def voice_reference_duration_failures(ctx: Ctx) -> list[dict[str, Any]]:
    """D-77: every speaker voice reference bound by this episode's units must sit inside the
    provider's single-clip window (seedance-2.0-pro: 2–15 s).  The registry records the duration
    when the reference is generated, so this is a free pre-flight; without it the first the line
    hears of a short clip is a rejected paid submit (E08-VU-021, 1.649 s, 2026-09-21)."""
    registry = read_json(ctx.p.scope["voice_registry"], {}) or {}
    manifest = read_json(ctx.p.video_transaction, {}) or {}
    used: set[str] = set()
    for task in manifest.get("tasks") or []:
        for row in ((task.get("speaker_voice_contract") or {}).get("bindings")) or []:
            entity = str(row.get("voice_entity_id") or row.get("speaker_entity_id") or "").strip()
            if entity:
                used.add(entity)
    if not used:
        return []
    low, high = PROVIDER_VOICE_REFERENCE_SECONDS
    bad: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            entity = str(node.get("entity_id") or "")
            seconds = node.get("duration_seconds")
            if entity in used and isinstance(seconds, (int, float)) and not (low <= float(seconds) <= high):
                bad.append({"entity_id": entity, "character": node.get("character"),
                            "duration_seconds": round(float(seconds), 3),
                            "provider_window_seconds": [low, high],
                            "remedy": "regenerate the reference with a longer sample_text on the same voice_id, "
                                      "re-upload, and update remote_asset_id/duration_seconds (see D-77)"})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(registry)
    return bad


def continuity_derived_units(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """E02+ anchor policy v4: units whose opening anchor is CONTINUITY_DERIVED_KEYFRAME.
    unit_id -> {previous_unit_id, first_shot_id, keyframe_path}."""
    anchors = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_ANCHOR_PLAN_V1.json", {}) or {}
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    first_shot = {u["unit_id"]: (u.get("editorial_shot_ids") or [None])[0] for u in plan.get("units") or []}
    out: dict[str, dict[str, Any]] = {}
    for row in anchors.get("units") or []:
        oac = row.get("opening_anchor_contract") or {}
        if str(oac.get("source") or "") != "CONTINUITY_DERIVED_KEYFRAME":
            continue
        uid = row["unit_id"]; shot = first_shot.get(uid)
        if not shot:
            continue
        out[uid] = {"previous_unit_id": oac.get("previous_unit_id"), "first_shot_id": shot,
                    "keyframe_path": ctx.p.preprod / "keyframes" / f"{shot}-keyframe-v1.png"}
    return out


def materialise_derived_keyframes(ctx: Ctx) -> list[dict[str, Any]]:
    """Copy the previous unit's real final frame into keyframes/<first_shot>-keyframe-v1.png for
    every continuity-derived unit whose tail exists (write-if-missing; sidecar records the source)."""
    rows = []
    tails = ctx.p.preprod / "real_final_frames"
    for uid, info in continuity_derived_units(ctx).items():
        dst: Path = info["keyframe_path"]; prev = info["previous_unit_id"]
        src = tails / f"{prev}.png" if prev else None
        if dst.is_file():
            rows.append({"unit_id": uid, "status": "ALREADY_PRESENT", "path": str(dst)}); continue
        if not src or not src.is_file():
            rows.append({"unit_id": uid, "status": "TAIL_NOT_YET_EXTRACTED", "previous_unit_id": prev}); continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        side = {"schema": "nalu.continuity_derived_keyframe.v1", "unit_id": uid, "shot_id": info["first_shot_id"],
                "source_real_final_frame": str(src), "source_sha256": sha256_file(src), "sha256": sha256_file(dst),
                "previous_unit_id": prev, "materialised_at": now(), "recorded_by": TOOL_ID,
                "note": "anchor policy v4 CONTINUITY_DERIVED_KEYFRAME: the start frame IS the previous unit's real tail; reviewed by the keyframe (Q1) questionnaire before the unit becomes wave-ready"}
        write_json(dst.with_suffix(".derived.json"), side)
        rows.append({"unit_id": uid, "status": "MATERIALISED", "path": str(dst), "sha256": side["sha256"]})
    return rows


def derived_units_pending_q1(ctx: Ctx) -> list[tuple[str, str]]:
    """(unit_id, first_shot_id) of derived units whose keyframe exists but has no ADMITTED Q1 result."""
    out = []
    for uid, info in continuity_derived_units(ctx).items():
        if not info["keyframe_path"].is_file():
            continue
        q1 = read_json(ctx.p.preprod_reports / "qa" / "q1" / uid / "admission_result.json", {}) or {}
        if q1.get("downstream_status") != "ADMITTED_FOR_VIDEO_SUBMIT" or q1.get("asset_sha256") != sha256_file(info["keyframe_path"]):
            out.append((uid, info["first_shot_id"]))
    return out


def stage_s6(ctx: Ctx) -> StageResult:
    """Rolling-wave video stage (2026-09-13): wave N = units whose video is not yet on disk
    and whose predecessor tail (when the anchor plan demands one) has been extracted.  Each
    wave: strict compile on a partial-ready grouping, prompt-finalization checkpoint, D-11
    authorisation, paid submit, poll/download, tail extraction.  When every unit has its
    video, a final FULL compile (all tails present) rebuilds the complete transaction manifest
    and the post-generation QA / Q2 route runs over all units."""
    p = ctx.p
    tails_dir = p.preprod / "real_final_frames"
    # Wave membership is FROZEN once a wave has been submitted: the engine's submission
    # fingerprint covers position-dependent compiled contracts, so re-entering with a
    # different unit list (e.g. dropping the two units already downloaded) re-compiled
    # E01-VU-006 as a list head with a new fingerprint and the durable store let a second
    # paid POST through (2026-09-13 02:52Z, task 5f73dc87, ~200 credits wasted).  A wave
    # keeps exactly its recorded unit list until every one of its videos is on disk.
    wave_state_path = p.preprod_reports / f"{ctx.episode}_S6_WAVE_STATE.json"
    wave_state = read_json(wave_state_path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    for _iteration in range(1, 8):
        deps = unit_dependency_order(ctx)
        done = {uid for uid, _, _ in deps if (p.video_media / f"{uid}.mp4").is_file()}
        if not deps or len(done) == len(deps):
            break
        # E02+ continuity-derived start frames: materialise from the previous tail, then require a
        # Q1 (keyframe questionnaire) admission of that frame before the unit can join a wave.
        derived_rows = materialise_derived_keyframes(ctx)
        pending_q1 = [(uid, shot) for uid, shot in derived_units_pending_q1(ctx) if uid not in done]
        # D-5 receipts for derived frames that are already Q1-admitted (the review protocol's submit
        # may have materialised the admissions itself, so this must not depend on pending_q1)
        need_sfe_now = [uid for uid, info in continuity_derived_units(ctx).items()
                        if uid not in done and info["keyframe_path"].is_file()
                        and (uid, info["first_shot_id"]) not in pending_q1
                        and not (ENGINE / "reports/start_frame_evidence" / f"{uid}_start_frame_evidence.json").is_file()]
        if need_sfe_now and not pending_q1:
            res = StageResult(REVIEW_REQUIRED)
            res.details["derived_units_need_start_frame_receipt"] = need_sfe_now
            sf_path, sf_review = latest_submitted_review(ctx, "start_frame")
            sf_answered = {str(it.get("item_id")) for it in ((sf_review or {}).get("items") or [])}
            if sf_path is not None and all(uid in sf_answered for uid in need_sfe_now):
                write_step = qa_run(ctx, [START_FRAME_EVIDENCE, "write", "--episode", ctx.episode,
                                          "--review", sf_path], name="s6_sfe_write_receipts_derived")
                res.steps.append(write_step)
                if (qa_json(write_step) or {}).get("status") == PASS:
                    continue
                res.status = BLOCKED
                res.blockers.append("S6.sfe_derived:START_FRAME_EVIDENCE_NOT_PASS")
                return res
            res.details.update(request_review(ctx, res, "start_frame", sub_stage="S6.sfe_derived",
                                              note="start-frame receipts for continuity-derived frames",
                                              items=need_sfe_now))
            res.blockers.append(f"S6.sfe_derived:REVIEW_REQUIRED:{len(need_sfe_now)}_frames")
            return res
        if pending_q1:
            res = StageResult(REVIEW_REQUIRED)
            res.details["derived_keyframes"] = derived_rows
            res.details["derived_units_pending_q1"] = pending_q1
            review_path, review = latest_submitted_review(ctx, "keyframe")
            answered = set()
            if review_path is not None:
                answered = {str(it.get("item_id")) for it in (review.get("items") or [])}
            unanswered = [shot for _, shot in pending_q1 if shot not in answered]
            if not unanswered and review_path is not None:
                build_step = qa_run(ctx, [KEYFRAME_Q1, "build", "--episode", ctx.episode, "--review", review_path],
                                    name="s6_q1_build_admission_derived")
                res.steps.append(build_step)
                # D-70: the same order-keyed acceptance overlay as S5.q1 (roger_gate_acceptance, never
                # self-issued) — a continuity-derived opener is the previous clip's real final frame, so
                # a by-design profile/back/out-of-frame face there needs the line owner's order too.
                _dv = qa_json(build_step) or {}
                _ip = Path(str(_dv.get("out") or ""))
                _ix = read_json(_ip, {}) or {}
                if _ix:
                    res.details["derived_q1_roger_acceptance"] = apply_roger_q1_acceptance(ctx, _ix, _ip)
                still = [(uid, shot) for uid, shot in derived_units_pending_q1(ctx) if uid not in done]
                if still:
                    res.status = BLOCKED
                    res.blockers.append("S6.q1_derived:NOT_ADMITTED:" + ",".join(uid for uid, _ in still))
                    return res
                # D-5 start-frame receipt for the derived frames (same route as S5.sfe, scoped)
                need_sfe = [uid for uid, _ in pending_q1
                            if not (ENGINE / "reports/start_frame_evidence" / f"{uid}_start_frame_evidence.json").is_file()]
                if need_sfe:
                    sf_path, sf_review = latest_submitted_review(ctx, "start_frame")
                    sf_answered = {str(it.get("item_id")) for it in ((sf_review or {}).get("items") or [])}
                    if sf_path is not None and all(uid in sf_answered for uid in need_sfe):
                        write_step = qa_run(ctx, [START_FRAME_EVIDENCE, "write", "--episode", ctx.episode,
                                                  "--review", sf_path], name="s6_sfe_write_receipts_derived")
                        res.steps.append(write_step)
                        if (qa_json(write_step) or {}).get("status") == PASS:
                            continue  # receipts written; re-plan the wave
                        res.status = BLOCKED
                        res.blockers.append("S6.sfe_derived:START_FRAME_EVIDENCE_NOT_PASS")
                        return res
                    res.details.update(request_review(ctx, res, "start_frame", sub_stage="S6.sfe_derived",
                                                      note="start-frame receipts for continuity-derived frames",
                                                      items=need_sfe))
                    res.blockers.append(f"S6.sfe_derived:REVIEW_REQUIRED:{len(need_sfe)}_frames")
                    return res
                continue  # admissions + receipts present; re-plan the wave
            res.details.update(request_review(ctx, res, "keyframe", sub_stage="S6.q1_derived",
                                              note="continuity-derived start frames (previous unit real tail) need the keyframe questionnaire",
                                              items=unanswered))
            res.blockers.append(f"S6.q1_derived:REVIEW_REQUIRED:{len(unanswered)}_frames")
            return res
        open_wave = next((w for w in wave_state.get("waves") or []
                          if not w.get("completed_at")
                          and any(uid not in done for uid in w.get("units") or [])), None)
        if open_wave:
            wave_no, ready = int(open_wave["wave"]), list(open_wave["units"])
            ctx.say(f"-- S6 rolling wave {wave_no} (re-entry, frozen membership): {len(ready)} unit(s) {ready}; "
                    f"{sum(1 for u in ready if u in done)} of them already on disk; {len(done)}/{len(deps)} videos on disk")
        else:
            derived = continuity_derived_units(ctx)
            ready = [uid for uid, prev, needs in deps
                     if uid not in done and (not needs or prev is None or (tails_dir / f"{prev}.png").is_file())
                     and (uid not in derived or derived[uid]["keyframe_path"].is_file())]
            if not ready:
                res = StageResult(BLOCKED)
                res.blockers.append("ROLLING_WAVE_NO_READY_UNITS")
                res.details = {"done": sorted(done), "waiting": [uid for uid, _, _ in deps if uid not in done]}
                return res
            wave_no = len(wave_state.get("waves") or []) + 1
            wave_state.setdefault("waves", []).append({"wave": wave_no, "units": ready, "opened_at": now(),
                                                       "done_before": sorted(done)})
            write_json(wave_state_path, wave_state)
            ctx.say(f"-- S6 rolling wave {wave_no}: {len(ready)} ready unit(s) {ready}; {len(done)}/{len(deps)} videos on disk")
        res = _stage_s6_body(ctx, ready_units=ready, run_qa=False)
        res.details["rolling_wave"] = {"wave": wave_no, "ready_units": ready, "done_before": sorted(done)}
        if res.status != PASS:
            return res
        extracted = [extract_real_final_frame(ctx, uid) for uid in ready]
        res.details["real_final_frames"] = extracted
        write_json(tails_dir / f"_extraction_wave{wave_no}.json", {"wave": wave_no, "rows": extracted, "at": now()})
        for w in wave_state.get("waves") or []:
            if int(w["wave"]) == wave_no:
                w["completed_at"] = now()
        write_json(wave_state_path, wave_state)
        bad = [row for row in extracted if row["status"] not in ("EXTRACTED", "ALREADY_PRESENT")]
        if bad:
            res.status = BLOCKED
            res.blockers.append(f"REAL_FINAL_FRAME_EXTRACTION_FAILED:{','.join(r['unit_id'] for r in bad)}")
            return res
        if ctx.dry:
            return res
    ctx.say("-- S6 final pass: all unit videos on disk; full compile + post-generation QA")
    # final pass = every unit with its real predecessor tail bound (the wave block of the builder
    # binds tails only for listed units), submit step SKIPPED: nothing may be POSTed here.
    return _stage_s6_body(ctx, ready_units=[uid for uid, _, _ in deps], run_qa=True, final_pass=True)


ACTION_ROLE_EVIDENCE = RT_TOOLS / "action_role_evidence_writer.py"


def s6_action_role_evidence(ctx: Ctx, res: StageResult, units: list[str] | None) -> dict[str, Any]:
    """S6.are — exact-output action-role verification of every start frame in scope.

    shot_media_admission_gate.precheck_submission_inputs (run by the engine submitter
    before any paid video POST) demands ``action_role_verification`` in the start-frame
    admission JSON whenever interaction_topology_contract.required is true, which the
    compile's enrich_unit_contract sets for every E01 unit.  The engine ships only the
    consumer; runtime/tools/action_role_evidence_writer.py writes the receipt from a
    submitted ``action_role`` review (reviewer looked at the real keyframe).
    """
    verify_step = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "verify", "--episode", ctx.episode],
                         name="s6_are_verify")
    res.steps.append(verify_step)
    report = qa_json(verify_step)
    scope = set(units) if units else None
    needing = [uid for uid in (report.get("missing") or []) + (report.get("failing") or [])
               if scope is None or uid in scope]
    detail: dict[str, Any] = {"sub_stage": "S6.are", "verify": {k: report.get(k) for k in ("units", "pass", "missing", "failing")},
                              "scope": sorted(scope) if scope else "ALL", "needing_evidence": needing}
    if not needing:
        detail["status"] = PASS
        return detail
    review_path, review = latest_submitted_review(ctx, "action_role")
    covered = {row.get("item_id") for row in (review.get("items") or [])} if review_path else set()
    if review_path is not None and set(needing) <= covered:
        write_step = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "write", "--episode", ctx.episode,
                                  "--review", review_path], name="s6_are_write_receipts")
        res.steps.append(write_step)
        detail["write"] = qa_json(write_step)
        verify_again = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "verify", "--episode", ctx.episode],
                              name="s6_are_verify_after_write")
        res.steps.append(verify_again)
        report = qa_json(verify_again)
        still = [uid for uid in (report.get("missing") or []) + (report.get("failing") or [])
                 if scope is None or uid in scope]
        detail["still_needing_evidence"] = still
        if not still:
            detail["status"] = PASS
            return detail
        needing = still
    detail.update(request_review(ctx, res, "action_role", sub_stage="S6.are", items=needing,
                                 note="exact-output action-role verification of the start frame "
                                      "(initiator / target / prop ownership) required by the "
                                      "engine submitter's input-completeness precheck"))
    return detail



def s6_planned_credits_for_unbound(ctx: Ctx) -> int:
    """Credits a paid S6 submit can still spend: SD2 720p = 20 credits/s for every task of the
    current transaction manifest whose submission fingerprint is NOT already bound to a remote
    task in the durable store.  A frozen-wave re-entry (poll only) therefore plans 0 instead of
    the whole-episode estimate: on 2026-09-13 03:14Z the guard projected 4793 + 3500 > 8000 and
    hard-stopped a pure poll of wave 3, whose 840 credits were already charged."""
    manifest = read_json(ctx.p.video_transaction, {}) or {}
    tasks = manifest.get("tasks") or []
    if not tasks:
        return ctx.planned_credits("S6")
    try:
        if str(ENGINE) not in sys.path:
            sys.path.insert(0, str(ENGINE))
        from tools.submit_giggle_video_manifest_v2 import task_fingerprint  # engine, read-only
    except Exception as exc:  # noqa: BLE001 - fall back to the conservative plan
        ctx.say(f"   planned-credit refinement unavailable ({type(exc).__name__}); using cost plan")
        return ctx.planned_credits("S6")
    store_dir = ENGINE / "workflow/tasks/giggle_video_submit_transactions" / ctx.episode
    bound = set()
    for path in (store_dir.glob("*.json") if store_dir.is_dir() else []):
        row = read_json(path, {}) or {}
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
            bound.add(str(row.get("submission_fingerprint")))
    unbound = [t for t in tasks if task_fingerprint(t) not in bound]
    planned = int(round(sum(float(t.get("duration_seconds") or 0) for t in unbound) * 20))
    ctx.say(f"   S6 planned credits: {planned} for {len(unbound)} unbound task(s) "
            f"({len(tasks) - len(unbound)} already bound in the durable store)")
    return planned

def s6_unbound_task_keys(ctx: Ctx) -> list[str]:
    """Task keys of the current transaction manifest with no SUBMITTED_TASK_ID_BOUND record."""
    manifest = read_json(ctx.p.video_transaction, {}) or {}
    tasks = manifest.get("tasks") or []
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.submit_giggle_video_manifest_v2 import task_fingerprint  # engine, read-only
    store_dir = ENGINE / "workflow/tasks/giggle_video_submit_transactions" / ctx.episode
    bound = set()
    for path in (store_dir.glob("*.json") if store_dir.is_dir() else []):
        row = read_json(path, {}) or {}
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
            bound.add(str(row.get("submission_fingerprint")))
    return [str(t.get("task_key")) for t in tasks if task_fingerprint(t) not in bound]


def _stage_s6_body(ctx: Ctx, *, ready_units=None, run_qa: bool = True,
                   final_pass: bool = False) -> StageResult:
    p = ctx.p
    # 6.0 action-role evidence for every start frame in scope (fail closed, reviewer-only)
    res = StageResult(PASS)
    are = s6_action_role_evidence(ctx, res, ready_units)
    res.details = {"action_role_evidence": are}
    if are.get("status") != PASS:
        return res
    # 6.1 re-run preproduction with --keyframe-dir (and, for a rolling wave, the ready subset).
    rebuilt = stage_s2(ctx, with_keyframes=True, ready_units=ready_units)
    res.steps.extend(rebuilt.steps)
    res.receipts = list(rebuilt.receipts)
    report = read_json(p.preprod_report, {}) or {}
    inner = {row.get("stage"): row.get("status") for row in (report.get("stages") or [])}
    res.details.update({
        "rebuild_with_keyframes": rebuilt.status,
        "inner_stages": inner,
        "video_transaction_manifest": str(p.video_transaction),
        "grouped_seedance_manifest": str(p.grouped_seedance),
        "video_preflight_report": str(p.video_preflight),
        "keyframe_dir": str(p.keyframes),
        "keyframes_on_disk": len(sorted(p.keyframes.glob("*-keyframe-v*.png")))
                             if p.keyframes.is_dir() else 0,
    })
    ready = (inner.get("4.3_video_unit_anchor_plan") == PASS
             and inner.get("4.4_compile_grouped_seedance_manifest") == PASS
             and inner.get("5_video_preflight") == PASS)
    res.details["video_preflight_pass"] = ready
    if not ready:
        res.status = BLOCKED
        res.blockers = [f"VIDEO_CHAIN_NOT_READY:{key}={value}" for key, value in inner.items()
                        if key.startswith(("4.3", "4.4", "5")) and value != PASS]
        res.details["hint"] = ("S5 keyframes + Q1 admission + start-frame receipts must land "
                              "first; video-preflight fails closed on a missing gate report, "
                              "an uncompiled prompt, or a non-PASS start_frame_semantic_contract.")
        if ctx.dry:
            # the chain is not submittable yet, but the operator still asked to see
            # the paid commands.  Print them, flagged as not-yet-reachable.
            plan_s6_paid_commands(ctx, res, reachable=False)
        return res

    # 6.2 efficiency contract — the rolling-wave planner and the in-batch
    # duplicate-request detector.  Free, and it must run before money moves.
    eff = ctx.run([VENV, ENGINE / "tools/production_efficiency_contract.py",
                   "--manifest", p.grouped_seedance, "--output", p.efficiency],
                  name="s6_production_efficiency_contract")
    res.steps.append(eff)
    res.receipts.append(str(p.efficiency))
    efficiency = read_json(p.efficiency, {}) or {}
    waves = ((efficiency.get("rolling_execution") or {}).get("waves")) or []
    res.details["efficiency_status"] = efficiency.get("status")
    res.details["rolling_waves"] = len(waves)

    # 6.2b whole-batch prompt gate, incremental finalisation (engine PR #51 / nalu e13).
    # The strict compile above re-rendered every unit's FINAL prompt; wherever it differs
    # from the batch-approved PLANNED prompt, tools/episode_prompt_batch_gate.py demands a
    # reviewed INCREMENTAL_EXACT_MATERIALIZATION_QA receipt attached to the task.  Write the
    # diff digest and stop for the Claude reviewer when any changed unit has no receipt.
    fin_digest = p.preprod_reports / f"{ctx.episode}_PROMPT_FINALIZATION_DIGEST.json"
    fin = ctx.run([VENV, RT_TOOLS / "prompt_batch_finalize.py", "diff", "--episode", ctx.episode,
                   "--execution-id", f"{ctx.episode}-PROMPT-BATCH-V1", "--out", fin_digest],
                  name="s6_prompt_batch_finalization_diff")
    res.steps.append(fin)
    fin_report = read_json(fin_digest, {}) or {}
    tx_now = read_json(p.video_transaction, {}) or {}
    unbound = [row["unit_id"] for row in fin_report.get("rows") or []
               if row.get("status") == "CHANGED" and not any(
                   t.get("unit_id") == row["unit_id"] and isinstance(t.get("prompt_batch_finalization"), dict)
                   for t in tx_now.get("tasks") or [])]
    res.details["prompt_finalization"] = {"digest": str(fin_digest), "summary": fin_report.get("summary"),
                                          "changed_without_receipt": unbound}
    if fin["exit_code"] != 0 or (fin_report.get("summary") or {}).get("missing"):
        res.status = BLOCKED
        res.blockers.append("PROMPT_FINALIZATION_DIGEST_FAILED")
        return res
    if unbound:
        res.status = REVIEW_REQUIRED
        res.blockers.append(f"S6.prompt_finalization:REVIEW_REQUIRED:{len(unbound)}_units")
        res.details["how_to_answer"] = [
            f"read {fin_digest} (only changed lines per unit)",
            "write answers {units: {<unit_id>: {verdict: PASS|FAIL, observation: ...}}, reviewer, review_method, reviewed_at}",
            f"{VENV} {RT_TOOLS / 'prompt_batch_finalize.py'} receipts --episode {ctx.episode} --execution-id {ctx.episode}-PROMPT-BATCH-V1 --digest {fin_digest} --answers <answers.json> --out-dir {p.preprod / 'prompt_batch_finalization'}",
            f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} run --episode {ctx.episode} --from S6 --paid",
        ]
        return res

    if final_pass:
        # 6.3f final full pass: all videos already on disk, every task already bound in the
        # durable store -> the paid submit is skipped outright (a re-compiled fingerprint must
        # never turn a QA pass into a new POST); anything unbound or missing BLOCKS instead.
        try:
            unbound = s6_unbound_task_keys(ctx)
        except Exception as exc:  # noqa: BLE001
            res.status = BLOCKED
            res.blockers.append(f"FINAL_PASS_FINGERPRINT_CHECK_FAILED:{type(exc).__name__}")
            return res
        manifest_now = read_json(p.video_transaction, {}) or {}
        missing_videos = [str(t.get("task_key")) for t in manifest_now.get("tasks") or []
                          if not (p.video_media / f"{t.get('task_key')}.mp4").is_file()]
        res.details["final_pass"] = {"submit": "SKIPPED_NO_POST_ALLOWED_IN_FINAL_PASS",
                                     "unbound_tasks": unbound, "missing_videos": missing_videos,
                                     "note": "fingerprints of the full-list compile may differ from the "
                                             "frozen-wave submissions; that is reported, never re-posted"}
        if missing_videos:
            res.status = BLOCKED
            res.blockers.append("FINAL_PASS_VIDEO_MISSING:" + ",".join(missing_videos))
            return res
        if unbound:
            ctx.say(f"   final pass: {len(unbound)} task(s) re-compiled with a fingerprint not in the "
                    f"durable store (no POST): {unbound}")
    else:
        # 6.3 D-11 paid authorisation, then the paid submit of the MATERIALISED manifest.
        # D-77: refuse to spend when a speaker voice reference is outside the provider's
        # 2–15 s window.  E08-VU-021 was rejected at submit time for a 1.649 s 打补丁的小女孩
        # reference (her only line is four characters long); the registry had recorded that
        # duration all along and nothing read it before the POST.
        voice_bad = voice_reference_duration_failures(ctx)
        if voice_bad:
            res.status = BLOCKED
            res.blockers.append("VOICE_REFERENCE_DURATION_OUT_OF_PROVIDER_RANGE:"
                                + ",".join(f"{row['entity_id']}={row['duration_seconds']}" for row in voice_bad))
            res.details["voice_reference_duration_failures"] = voice_bad
            return res
        concurrency = min(ctx.max_parallel, 6)
        planned = s6_planned_credits_for_unbound(ctx)
        # D-46: only tasks WITHOUT a clip on disk may be authorised for a POST; a unit whose mp4
        # exists is complete whatever its recompiled fingerprint says (see PIPELINE_RUNBOOK D-46).
        manifest_now = read_json(p.video_transaction, {}) or {}
        needs_post = [str(t.get("task_key")) for t in manifest_now.get("tasks") or []
                      if not (p.video_media / f"{t.get('task_key')}.mp4").is_file()]
        on_disk = [str(t.get("task_key")) for t in manifest_now.get("tasks") or []
                   if str(t.get("task_key")) not in needs_post]
        if on_disk and needs_post:
            ctx.say(f"   D-46: {len(on_disk)} task(s) already have a clip on disk and are excluded from the "
                    f"authorised copy: {on_disk}")
        res.details["d46_needs_post"] = needs_post
        auth_status, auth_manifest, auth = materialize_paid_authorization(
            ctx, res, sid="S6", target=p.video_transaction, is_plan=False,
            task_keys=(needs_post if (on_disk and needs_post) else None),
            note=("production_video_submission_gate.py has NO authority-field checks, so for video "
                  "these fields are set for auditability and for the reroll guard, not because the "
                  "submitter enforces them"))
        res.details["paid_authorization"] = auth
        if auth_status == BLOCKED:
            res.status = BLOCKED
            res.blockers.append(auth["blocker"])
            return res
        paid_argv = video_submit_argv(ctx, manifest=auth_manifest, concurrency=concurrency)
        dry_argv = video_preflight_argv(ctx)
        status, submit = ctx.paid_step(
            paid_argv, name="s6_submit_giggle_video_manifest_v2", sid="S6",
            planned_credits=planned, dry_argv=dry_argv, extra_env=VIDEO_SUBMIT_ENV,
            note=(f"Submitted file is the D-11 materialised copy {auth_manifest.name}.  "
                  f"POST /api/v1/generation/omni-video, concurrency {concurrency} "
                  "(<=6 per production_efficiency_contract rolling waves).  Durable store "
                  f"{ENGINE}/workflow/tasks/giggle_video_submit_transactions/{ctx.episode}/, "
                  "per-task flock, intent-before-POST.  A lost HTTP response becomes "
                  "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION and MUST NOT be blindly resent. "
                  "qingshan video-preflight is literally this tool with --precheck-only."))
        res.steps.append(submit)
        res.planned_credits += planned
        if status == HARD_STOP:
            res.status = HARD_STOP
            res.blockers.append("BUDGET_HARD_STOP_S6")
            return res

        poll_argv = video_poll_argv(ctx)
        if status == DRY:
            res.status = DRY
            ctx.say("   then (needs GIGGLE_API_KEY, no new POST, free):")
            ctx.say(f"     {q(poll_argv)}")
            ctx.planned_commands.append({
                "stage": "S6", "step": "s6_poll_giggle_submit_report", "planned_credits": 0,
                "paid_argv": [str(x) for x in poll_argv], "paid_command": q(poll_argv),
                "note": ("downloads only remote_status==completed, atomic .part->replace, "
                         "skips what already exists; omit --download for a query-only probe")})
        elif status == PASS:
            # the engine video submitter writes <report>_credit_statement.json under a FIXED name;
            # a wave re-entry (poll-only, 0 new POSTs) overwrote wave 1's 1500-credit statement on
            # 2026-09-13 02:49Z (ledger 2413 -> 913).  Archive every run's statement uniquely.
            res.details["credit_statement"] = archive_credit_statement(
                ctx, p.video_submit, f"{ctx.run_id}_wave{len(ready_units or [])}u")
            poll = ctx.run(poll_argv, name="s6_poll_giggle_submit_report", paid=True,
                           extra_env=VIDEO_SUBMIT_ENV)
            res.steps.append(poll)
            res.receipts.append(str(p.video_remote_status))
            remote = read_json(p.video_remote_status, {}) or {}
            res.details["remote_status_counts"] = remote.get("status_counts")
            res.details["all_completed"] = remote.get("all_completed")
            if not remote.get("all_completed"):
                res.status = BLOCKED
                res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
                return res
        else:
            res.status = BLOCKED
            res.blockers.append("VIDEO_SUBMIT_FAILED")
            return res
        if not run_qa:
            if res.status == DRY:
                res.blockers.append("PAID_STEPS_DISABLED_WAVE_NOT_SUBMITTED")
                return res  # dry rolling wave: chain verified up to the paid boundary, nothing to extract
            res.status = PASS  # rolling wave: this wave's videos are on disk; the caller extracts tails
            return res

    # 6.4 post-generation QA scope policy (free) + the Q2 route status
    scope_argv = [VENV, ENGINE / "tools/post_generation_qa_scope_gate.py",
                  "--episode", ctx.episode, "--out", p.postgen_qa]
    for check in ("decode", "duration", "resolution", "aspect_ratio", "codec",
                  "audio_stream", "av_sync", "black_frame", "freeze", "corruption",
                  "frame_rate", "sample_rate",
                  "episode_scene_correspondence", "principal_character_presence",
                  "major_event_presence", "major_dialogue_presence",
                  "chronological_unit_order"):
        scope_argv += ["--check", check]
    scope = ctx.run(scope_argv, name="s6_post_generation_qa_scope_gate")
    res.steps.append(scope)
    res.receipts.append(str(p.postgen_qa))
    res.details["post_generation_qa_scope"] = (read_json(p.postgen_qa, {}) or {}).get("status")
    res.details["post_generation_qa_note"] = (
        "post_generation_qa_scope_gate.py only decides which checks are ALLOWED "
        "(12 technical + 5 basic-plot, 16 forbidden).  It measures nothing.  The VD-13 "
        "technical measurements and the Q2 content admission "
        "(shot_media_admission_gate.py --kind VIDEO_ASSEMBLY, terminal "
        "ADMITTED_FOR_ASSEMBLY) have no per-episode-parameterised producer in this "
        "engine — see open decisions D-6 and D-7.")
    # 6.5 S6.qa — the real post-generation measurements (D-6)
    qa = s6_qa(ctx, res)
    res.details["post_generation_qa"] = qa
    res.details["reroll_route"] = {
        "guard": f"{ENGINE}/tools/reroll_cost_guard.py",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "policy": str(ENGINE / "configs/reroll_cost_guard_policy_v1_20260716.json"),
        "argv_template": q([
            VENV, ENGINE / "tools/reroll_cost_guard.py",
            "--policy", ENGINE / "configs/reroll_cost_guard_policy_v1_20260716.json",
            "--ledger", p.preprod_reports / f"{ctx.episode}_REROLL_LEDGER.json",
            "--shot-id", "<SHOT_ID>", "--reroll-number", "1",
            "--failure-tier", "BLOCK", "--failure-reason", "<REASON>",
            "--total-paid-tasks", "29",
            "--out", p.preprod_reports / f"{ctx.episode}_REROLL_COST_GUARD.json"]),
        "rule": "a reroll runs only on status PASS_* from this guard AND a fresh "
                "nalu_budget_ledger.py --check inside the 8000-credit cap",
    }
    if res.status == PASS:
        if qa["status"] == REVIEW_REQUIRED:
            res.status = REVIEW_REQUIRED
            return res
        if qa["status"] != PASS:
            res.status = qa["status"]
            res.blockers.extend(qa.get("blockers") or [])
            return res
        # 6.6 S6.q2 — Q2 VIDEO_ASSEMBLY content admission (D-7).  This is the only
        # route to downstream_status ADMITTED_FOR_ASSEMBLY, which S7 requires.
        q2 = s6_q2(ctx, res)
        res.details["q2_admission"] = q2
        if q2["status"] == REVIEW_REQUIRED:
            res.status = REVIEW_REQUIRED
            return res
        if q2["status"] != PASS:
            res.status = q2["status"]
            res.blockers.extend(q2.get("blockers") or [])
            return res

        # 6.7 selective BGM source generation.  Keep this after every video
        # submit, QA, and Q2 gate: the BGM charge is reconciled read-only in S7,
        # so no later paid budget check may run while that completed transaction
        # is still awaiting its statement evidence.
        bgm_sources = s6_selective_bgm_sources(ctx, res)
        res.details["selective_bgm_sources"] = bgm_sources
        if bgm_sources.get("status") in {BLOCKED, HARD_STOP}:
            res.status = str(bgm_sources["status"])
            res.blockers.append(str(bgm_sources.get("blocker") or "SELECTIVE_BGM_S6_FAILED"))
        elif bgm_sources.get("status") == DRY:
            res.status = DRY
            res.blockers.append("SELECTIVE_BGM_GENERATION_NEEDS_PAID")
    return res


# --------------------------------------------------------------------------- #
# S6.q2 — Q2 VIDEO_ASSEMBLY content admission (D-7)
# --------------------------------------------------------------------------- #
def s6_q2(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """D-7 — the ONLY route to downstream_status ADMITTED_FOR_ASSEMBLY.

    ``tools/shot_media_admission_gate.py`` writes that state only for a request
    whose ``kind`` is ``VIDEO_ASSEMBLY``, which needs FIVE registered gates (the
    four keyframe gates plus ``DEFECT-TIER-TOLERANCE``) and a ``technical_qa``
    block whose status is exactly ``TECHNICAL_PASS_CONTENT_UNREVIEWED``.
    ``runtime/tools/video_q2_builder.py`` is the parameterised builder of that
    request.  Its inputs are all real:

      post_generation_qa_runner (D-6) records  the technical_qa block, verbatim
      the downloaded unit mp4s                 the asset under review
      the unit plan (grouping + editorial)     the contract-derived expectations
      a submitted `video_q2` VLM review        VLM_STRUCTURED_STATE_QA_V1
      a real RapidOCR pass per frame           CLOSED_SET_ANACHRONISM_OCR_V1
      a real insightface pass per unit         INSIGHTFACE_COSINE_V1
      a real defect_tolerance_gate.py run      DEFECT-TIER-TOLERANCE

    ``prepare`` runs first because the review request has to show the reviewer the
    ORIGINAL-RESOLUTION frames the gate's ``original_resolution_review`` claim is
    about.  No media is ever stubbed: a missing mp4 is reported as the precise
    missing input and the sub-stage BLOCKS.
    """
    p = ctx.p
    status_step = qa_run(ctx, [VIDEO_Q2, "status", "--episode", ctx.episode],
                         name="s6_q2_route_status")
    res.steps.append(status_step)
    route = qa_json(status_step)
    media = sorted(p.video_media.glob("*.mp4")) if p.video_media.is_dir() else []
    detail: dict[str, Any] = {
        "sub_stage": "S6.q2",
        "decision": "D-7",
        "route": route,
        "reviewer": REVIEWER_ID,
        "builder": str(VIDEO_Q2),
        "gate": str(ENGINE / "tools/shot_media_admission_gate.py"),
        "kind": "VIDEO_ASSEMBLY",
        "required_evidence_gates": route.get("required_registered_gates"),
        "terminal_state_required": "status ADMITTED|ADMITTED_WITH_P2 + "
                                   "downstream_status ADMITTED_FOR_ASSEMBLY",
        "unit_media_on_disk": len(media),
        "q2_index": route.get("q2_index"),
    }
    if not media:
        detail["status"] = BLOCKED
        detail["blockers"] = ["UNIT_VIDEO_NOT_DOWNLOADED"]
        detail["missing_input"] = str(p.video_media / "<UNIT_ID>.mp4")
        detail["reason"] = ("S6 has not produced unit videos yet (paid step disabled or not "
                           "run).  No frame is extracted and no review is requested for media "
                           "that does not exist; nothing is stubbed.")
        detail["commands_when_media_exists"] = [
            q([VENV, VIDEO_Q2, "prepare", "--episode", ctx.episode]),
            q([VENV, VLM_PROTOCOL, "request", "--kind", "video_q2", "--episode", ctx.episode]),
            q([VENV, VIDEO_Q2, "build", "--episode", ctx.episode, "--review", "<submitted>"]),
        ]
        for line in detail["commands_when_media_exists"]:
            ctx.say(f"   S6.q2 (blocked, would run): {line}")
        return detail

    prep_step = qa_run(ctx, [VIDEO_Q2, "prepare", "--episode", ctx.episode],
                       name="s6_q2_prepare_frames_ocr_identity")
    res.steps.append(prep_step)
    prepare = qa_json(prep_step)
    detail["prepare"] = prepare
    if prepare.get("status") != "READY":
        detail["status"] = BLOCKED
        detail["blockers"] = [f"Q2_PREPARE_{prepare.get('status')}"] + [
            f"{row.get('unit_id')}:{row.get('blocker') or row.get('status')}"
            for row in (prepare.get("blocked") or [])[:8]]
        return detail

    review_path, review = latest_submitted_review(ctx, "video_q2")
    if review_path is None:
        detail.update(request_review(ctx, res, "video_q2", sub_stage="S6.q2",
                                     note="Q2 content admission: the reviewer looks at the "
                                          "original-resolution clip and its extracted frames"))
        return detail

    build_step = qa_run(ctx, [VIDEO_Q2, "build", "--episode", ctx.episode,
                              "--review", review_path], name="s6_q2_build_admission")
    res.steps.append(build_step)
    verdict = qa_json(build_step)
    index = read_json(Path(verdict.get("out") or ""), {}) or {}
    detail.update({
        "review_file": str(review_path),
        "review_file_sha256": sha256_file(review_path),
        "reviewed_at": review.get("reviewed_at"),
        "verdict_counts": review.get("verdict_counts"),
        "q2_index": verdict.get("out"),
        "q2_status": verdict.get("status"),
        "admitted": verdict.get("admitted"),
        "units": verdict.get("units"),
        "assembly_allowed_unit_ids": index.get("assembly_allowed_unit_ids"),
        "rejected_unit_ids": index.get("rejected_unit_ids"),
        "receipts": index.get("receipts"),
        "review_results": index.get("review_results"),
        "status": PASS if verdict.get("status") == "ALL_ADMITTED" else BLOCKED,
        "blockers": ([] if verdict.get("status") == "ALL_ADMITTED"
                     else [f"Q2_{verdict.get('status')}"] + [
                         f"{row.get('unit_id')}:{(row.get('failures') or ['?'])[0]}"
                         for row in (index.get("results") or [])
                         if row.get("downstream_status") != "ADMITTED_FOR_ASSEMBLY"][:8]),
    })
    res.receipts.extend([str(value) for value in (index.get("receipts") or [])])
    return detail


# --------------------------------------------------------------------------- #
# S6.qa — post-generation technical + basic-plot QA (D-6)
# --------------------------------------------------------------------------- #
def s6_qa(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """The 12 allowed technical checks (real measurers) + the 5 basic-plot checks.

    post_generation_qa_scope_gate.py only classifies what is allowed; the
    measurements are performed by runtime/tools/post_generation_qa_runner.py:
    ffprobe, run_regression_ci.pure_black_frame_stats / freeze_stats /
    static_hold_stats, frame_cadence_audit.py, source_brightness_jump_audit.py,
    media_boundary_acceptance.py and source_video_dialogue_gate.py
    (faster-whisper, homophones RECORDED not rejected per
    runtime/configs/BASIC_DIALOGUE_QA_POLICY.json).  The five basic-plot checks
    come from a post_gen_plot VLM review over an ffmpeg 2-fps contact sheet.
    """
    p = ctx.p
    status_step = qa_run(ctx, [POST_GEN_QA, "status", "--episode", ctx.episode],
                         name="s6_qa_route_status")
    res.steps.append(status_step)
    route = qa_json(status_step)
    media = sorted(p.video_media.glob("*.mp4")) if p.video_media.is_dir() else []
    detail: dict[str, Any] = {"sub_stage": "S6.qa", "route": route,
                              "reviewer": REVIEWER_ID,
                              "unit_media_on_disk": len(media)}
    if not media:
        detail["status"] = BLOCKED
        detail["blockers"] = ["UNIT_VIDEO_NOT_DOWNLOADED"]
        return detail

    # contact sheets first — the reviewer needs them before it can answer
    sheet_step = qa_run(ctx, [POST_GEN_QA, "contact-sheet", "--episode", ctx.episode],
                        name="s6_qa_contact_sheets")
    res.steps.append(sheet_step)

    review_path, review = latest_submitted_review(ctx, "post_gen_plot")
    if review_path is None:
        detail.update(request_review(ctx, res, "post_gen_plot", sub_stage="S6.qa",
                                     note="the 5 basic-plot checks the scope gate allows"))
        return detail

    run_argv = [POST_GEN_QA, "run", "--episode", ctx.episode, "--review", review_path]
    run_step = qa_run(ctx, run_argv, name="s6_qa_post_generation_qa_runner")
    res.steps.append(run_step)
    verdict = qa_json(run_step)
    detail.update({
        "review_file": str(review_path),
        "review_file_sha256": sha256_file(review_path),
        "reviewed_at": review.get("reviewed_at"),
        "summary": verdict.get("out"),
        "qa_status": verdict.get("status"),
        "admitted": verdict.get("admitted"),
        "rejected": verdict.get("rejected"),
        "reroll_requests": verdict.get("rerolls"),
        "reroll_request_file": str(p.preprod_reports / "qa"
                                   / f"{ctx.episode}_REROLL_REQUESTS.json"),
        "status": PASS if verdict.get("status") == "ADMIT_ALL" else BLOCKED,
        "blockers": ([] if verdict.get("status") == "ADMIT_ALL"
                     else [f"POST_GENERATION_QA_{verdict.get('status')}"]),
    })
    res.receipts.append(str(verdict.get("out") or ""))
    return detail


def plan_s6_paid_commands(ctx: Ctx, res: StageResult, *, reachable: bool) -> None:
    """Record the S6 paid argv even when the chain is not yet submittable."""
    p = ctx.p
    concurrency = min(ctx.max_parallel, 6)
    planned = ctx.planned_credits("S6")
    auth_manifest = materialised_path(p.video_transaction)
    auth_argv = [str(x) for x in paid_authorization_argv(
        ctx, sid="S6", target=p.video_transaction, is_plan=False)]
    submit_argv = [str(x) for x in video_submit_argv(
        ctx, manifest=auth_manifest, concurrency=concurrency)]
    poll_argv = [str(x) for x in video_poll_argv(ctx)]
    prefix = "" if reachable else "NOT YET REACHABLE — video-preflight must PASS first.  "
    budget = ctx.budget_check(planned, label="s6_plan_only")
    verdict = budget.get("budget_verdict") or {}
    res.steps.append(budget)
    ctx.say(f"   budget {'ok' if budget['exit_code'] == 0 else 'REFUSED'}: planned={planned} "
            f"projected={verdict.get('projected_total_credits')} cap={verdict.get('cap_credits')}")
    ctx.say(f"   D-11 paid authorisation NOT EXECUTED (--dry-run).  {prefix}Exact command:")
    ctx.say(f"     {q(auth_argv)}")
    ctx.say(f"   PAID STEP NOT EXECUTED (--dry-run).  {prefix}Exact command:")
    for key, value in sorted(VIDEO_SUBMIT_ENV.items()):
        ctx.say(f"     export {key}={value}")
    ctx.say(f"     {q(submit_argv)}")
    ctx.say("   then (needs GIGGLE_API_KEY, no new POST, free):")
    ctx.say(f"     {q(poll_argv)}")
    ctx.planned_commands.append({
        "stage": "S6", "step": "s6_materialize_paid_authorization",
        "planned_credits": 0, "paid_argv": auth_argv, "paid_command": q(auth_argv),
        "reachable_today": reachable,
        "note": ("D-11: writes " + str(auth_manifest) + " plus the GIGGLE-REROLL-COST-GUARD "
                 "report bound to its sha256.  Offline, no POST, no credits.")})
    ctx.planned_commands.append({
        "stage": "S6", "step": "s6_submit_giggle_video_manifest_v2",
        "env": dict(VIDEO_SUBMIT_ENV),
        "planned_credits": planned, "paid_argv": submit_argv,
        "paid_command": q(submit_argv), "reachable_today": reachable,
        "note": (prefix + "submits the D-11 materialised copy; requires "
                 f"BACKLOT_PIPELINE_TOOLS_DIR={ENGINE / 'tools'} and "
                 f"--project-root {VIDEO_PROJECT_ROOT}.  "
                 f"POST /api/v1/generation/omni-video, 29 units / 175s, concurrency "
                 f"{concurrency} (<=6 rolling waves).  Durable store "
                 f"{ENGINE}/workflow/tasks/giggle_video_submit_transactions/{ctx.episode}/ with "
                 "per-task flock and intent-before-POST; a lost response becomes "
                 "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION and must never be blindly resent.")})
    res.planned_credits = planned
    ctx.planned_commands.append({
        "stage": "S6", "step": "s6_poll_giggle_submit_report", "planned_credits": 0,
        "paid_argv": poll_argv, "paid_command": q(poll_argv), "reachable_today": reachable,
        "note": "downloads only remote_status==completed; omit --download for a query-only probe"})

    # Run the precheck twin for real (free, no POST) with the engine tools dir
    # exported, so the state file records the CURRENT blocking reason rather than
    # an environment defect.  Expected today: CURRENT_PROMPT_FILE_MISSING — stage
    # 4.4 has not compiled workflow/nalu/<EP>/preproduction/video_prompts/ because
    # the keyframes do not exist yet.  "Production video gate is unavailable" here
    # would mean BACKLOT_PIPELINE_TOOLS_DIR did not reach the child.
    twin = ctx.run(video_preflight_argv(ctx), name="s6_video_preflight_precheck",
                   paid=False, extra_env=VIDEO_SUBMIT_ENV)
    res.steps.append(twin)
    reason = "PASS"
    for line in reversed((twin.get("stderr_tail") or "").splitlines()):
        if "gate failed:" in line or "gate is unavailable" in line:
            reason = line.strip()
            break
    res.details["video_preflight_precheck"] = {
        "argv": twin["argv_shell"],
        "env": dict(VIDEO_SUBMIT_ENV),
        "project_root": str(VIDEO_PROJECT_ROOT),
        "exit_code": twin["exit_code"],
        "blocking_reason": reason,
        "expected_until_keyframes_exist": "CURRENT_PROMPT_FILE_MISSING",
        "log": twin["log"],
    }
    ctx.say(f"   video-preflight precheck (free): exit={twin['exit_code']}  {reason}")


# --------------------------------------------------------------------------- #
# S7 — Q2 admission -> assembly -> render -> loudness -> final package QA (free)
# --------------------------------------------------------------------------- #
def s7_q2_gate(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """The head of the S7 chain: every unit must hold a Q2 ADMITTED_FOR_ASSEMBLY
    receipt whose reviewed asset sha256 still matches the mp4 on disk.

    ``build_agentcut_from_admitted_storyboard_sources.py`` hard-fails unless the
    admitted slot count equals ``--expected-slots``, and every admitted slot's
    output path must also appear in a ``--review-result``'s ``passed_items``
    (:70-74).  Both files are produced by S6.q2; this re-verifies them rather
    than trusting a stale index, because a rerolled unit invalidates its own
    receipt.
    """
    step = qa_run(ctx, [VIDEO_Q2, "status", "--episode", ctx.episode],
                  name="s7_q2_verify_admission")
    res.steps.append(step)
    detail = qa_json(step)
    index = read_json(ctx.p.q2_index, {}) or {}
    receipts = [Path(value) for value in (index.get("receipts") or [])
                if Path(value).is_file()]
    reviews = [Path(value) for value in (index.get("review_results") or [])
               if Path(value).is_file()]
    return {
        "sub_stage": "S7.q2",
        "decision": "D-7/D-8",
        "route_status": detail.get("status"),
        "q2_index": str(ctx.p.q2_index),
        "q2_status": detail.get("q2_status"),
        "admitted_count": detail.get("admitted_count"),
        "assembly_allowed_unit_ids": detail.get("assembly_allowed_unit_ids") or [],
        "stale_receipts": detail.get("stale_receipts") or [],
        "blockers": detail.get("blockers") or [],
        "receipts": [str(value) for value in receipts],
        "review_results": [str(value) for value in reviews],
        "status": PASS if detail.get("status") == "READY" else BLOCKED,
    }


def _write_release_timeline(ctx: "Ctx", p: "Paths", picture: Path, outro_seconds: float, release_timeline: Path) -> dict:
    """Derive the episode RELEASE timeline (unit windows on the rendered picture) from the AgentCut project."""
    project = read_json(p.agentcut_project, {}) or {}
    clips = []
    for track in ((project.get("timeline") or {}).get("videoTracks") or []):
        clips.extend(track.get("clips") or [])
    clips.sort(key=lambda c: float(c.get("start") or 0))
    probe = subprocess.run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(picture)], capture_output=True, text=True, check=False)
    release_runtime = round(float(probe.stdout.strip() or 0), 6)
    # outro window = the appended end card; without one, the last 0.5 s of the last unit
    content_runtime = round(max(release_runtime - (outro_seconds or 0.5), 0.0), 6)
    segments = []
    for clip in clips:
        uid = str((clip.get("metadata") or {}).get("source_id") or "")
        start = float(clip.get("start") or 0); end = start + float(clip.get("duration") or 0)
        segments.append({"unit_id": uid, "output_start": round(start, 6),
                         "output_end": round(min(end, content_runtime), 6), "clip_id": clip.get("id")})
    write_json(release_timeline, {
        "schema": "nalu.release_timeline.v1", "episode": ctx.episode,
        "source": str(p.agentcut_project), "picture": str(picture),
        "content_runtime_seconds": content_runtime, "release_runtime_seconds": release_runtime,
        "outro_note": ("NALU MOTION studio end card appended (3.0 s)" if outro_seconds else
                       "no outro card; the final 0.5 s of the last unit is the outro window"),
        "segments": segments, "recorded_at": now(),
    })
    return {"path": str(release_timeline), "segments": len(segments),
            "content_runtime_seconds": content_runtime, "release_runtime_seconds": release_runtime}


def s7_final_audience_review(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """Require an independent, SHA-bound final-audience review before final QA.

    The production process may prepare the request, contact sheet and objective
    metrics.  Only the separate reviewer process may submit answers and create
    the audience report/event ledger consumed by the registered gates.
    """
    producer_process_id = (
        f"nalu-production-{ctx.p.scope['scope_id']}-{ctx.episode}"
    )
    status_step = qa_run(
        ctx,
        [FINAL_AUDIENCE_REVIEW, "status", "--episode", ctx.episode],
        name="s7_final_audience_review_status",
    )
    res.steps.append(status_step)
    detail = qa_json(status_step)
    code = int(status_step.get("exit_code") or 0)

    if code == 4:
        prepare_step = qa_run(
            ctx,
            [FINAL_AUDIENCE_REVIEW, "prepare", "--episode", ctx.episode,
             "--producer-process-id", producer_process_id],
            name="s7_final_audience_review_prepare",
        )
        res.steps.append(prepare_step)
        prepared = qa_json(prepare_step)
        detail = {"status_before_prepare": detail, **prepared}
        if prepare_step.get("exit_code") != 0:
            return {
                **detail,
                "status": BLOCKED,
                "blockers": ["FINAL_AUDIENCE_REVIEW_PREPARE_FAILED"],
            }
        code = 10

    if code == 0 and detail.get("status") == PASS:
        for key in ("report", "event_ledger"):
            if detail.get(key):
                res.receipts.append(str(detail[key]))
        return {**detail, "status": PASS, "blockers": []}

    if code == 10:
        request = str(
            detail.get("request")
            or (REVIEWS_ROOT / ctx.episode / "final_audience_request.json")
        )
        if Path(request).is_file():
            res.receipts.append(request)
        return {
            **detail,
            "status": REVIEW_REQUIRED,
            "request": request,
            "submit_command": q([
                VENV, FINAL_AUDIENCE_REVIEW, "submit",
                "--episode", ctx.episode,
                "--request", request,
                "--answers", REVIEWS_ROOT / ctx.episode / "final_audience_answers.json",
            ]),
            "blockers": ["FINAL_AUDIENCE_REVIEW_REQUIRED"],
        }

    return {
        **detail,
        "status": BLOCKED,
        "blockers": [
            "FINAL_AUDIENCE_REVIEW_REJECTED"
            if code == 3 else "FINAL_AUDIENCE_REVIEW_EVIDENCE_INVALID"
        ],
    }


def stage_s7(ctx: Ctx) -> StageResult:
    """Q2 admission -> AgentCut project -> render -> release loudness -> final QA.

    Nothing in this stage stubs media.  Each link runs only when its real input
    exists; otherwise the stage records the exact command it WOULD run and the
    precise missing input, and BLOCKS.
    """
    p = ctx.p
    p.assembly.mkdir(parents=True, exist_ok=True)
    p.deliver.mkdir(parents=True, exist_ok=True)
    plan = read_json(p.grouping_plan, {}) or {}
    units = plan.get("units") or []
    expected_slots = len(units)

    res = StageResult(BLOCKED)
    # ---------------------------------------------------------------- 1. Q2
    q2 = s7_q2_gate(ctx, res)
    receipts = [Path(value) for value in q2["receipts"]]
    reviews = [Path(value) for value in q2["review_results"]]

    # -------------------------------------------------------- 2. the chain argv
    build_argv: list[Any] = [
        VENV, ENGINE / "tools/build_agentcut_from_admitted_storyboard_sources.py",
        "--episode", ctx.episode]
    for receipt in receipts or [p.q2_dir / "<UNIT_ID>/admission_result.json"]:
        build_argv += ["--receipt", receipt]
    for review in reviews or [p.q2_dir / "<UNIT_ID>/ai_review.json"]:
        build_argv += ["--review-result", review]
    build_argv += [
        "--out-project", p.agentcut_project,
        "--out-admission", p.agentcut_admission,
        "--output-video", p.final_mp4,
        "--expected-slots", expected_slots,
        # required: audio_profile_binding classifies audio_contract.bgm and stamps
        # the contract's sha into the project (NO_BGM -> NATIVE_MULTIMODAL_NO_EXTERNAL_BGM)
        "--generation-contract", p.contract]

    render_dry_argv = [VENV, ENGINE / "tools/render_portable_timeline.py",
                       p.agentcut_project, "--output", p.picture_native, "--dry-run"]
    render_argv = [VENV, ENGINE / "tools/render_portable_timeline.py",
                   p.agentcut_project, "--output", p.picture_native]
    release_timeline = p.assembly / f"{ctx.episode}_release_timeline.json"
    level_argv: list[Any] = [VENV, ENGINE / "tools/level_native_release_audio.py",
                             "--source", p.picture_native,
                             "--timeline", release_timeline,
                             "--grouped", p.grouped_seedance,
                             "--output", p.final_mp4,
                             "--qa", p.leveled_audio_report,
                             "--episode", ctx.episode,
                             "--version", "v1",
                             "--expected-sha256",
                             sha256_file(p.picture_native)
                             or "<sha256 of picture_native, computed after the render>"]
    final_qa_argv = [VENV, FINAL_QA_BUNDLE, "run", "--episode", ctx.episode,
                     "--gate-subset", "applicable"]
    evidence_bundle = p.assembly / f"{ctx.episode}_MANDATORY_GATE_EVIDENCE.json"
    run_episode_qa_argv = [
        ENGINE / "tools/run_episode_qa.sh",
        "--video", p.final_mp4,
        "--config", p.assembly / f"{ctx.episode}_continuity_config.json",
        "--manifest", p.assembly / f"{ctx.episode}_asset_binding_manifest.json",
        "--blocker-manifest", p.assembly / f"{ctx.episode}_FINAL_PACKAGE_BLOCKERS.json",
        "--speaker-evidence", p.assembly / f"{ctx.episode}_SPEAKER_IDENTITY_VOICE_EVIDENCE.json",
        "--episode", ctx.episode,
        "--evidence-bundle", evidence_bundle,
        "--render-plan", p.assembly / f"{ctx.episode}_final_render_plan.json",
        "--out", p.deliver / "final_qa"]

    res.details = {
        "q2_admission": q2,
        "expected_slots": expected_slots,
        "admitted_receipts_found": [str(value) for value in receipts],
        "review_results_found": [str(value) for value in reviews],
        "chain": ["S7.q2 Q2 VIDEO_ASSEMBLY admission",
                  "build_agentcut_from_admitted_storyboard_sources.py",
                  "render_portable_timeline.py --dry-run then for real",
                  "level_native_release_audio.py",
                  "final_audience_review.py status/prepare (independent submit required)",
                  "final_qa_evidence_bundle.py run --gate-subset applicable",
                  f"{p.final_mp4} + {p.checkpoint}"],
        "commands": {
            "q2_admission": q([VENV, VIDEO_Q2, "build", "--episode", ctx.episode,
                               "--review", "<submitted video_q2 review>"]),
            "build_agentcut": q(build_argv),
            "render_dry_run": q(render_dry_argv),
            "render": q(render_argv),
            "level_native_release_audio": q(level_argv),
            "final_audience_review_status": q(
                [VENV, FINAL_AUDIENCE_REVIEW, "status", "--episode", ctx.episode]
            ),
            "final_qa_evidence_bundle": q(final_qa_argv),
            "run_episode_qa_NOT_RUN": "PYTHON_BIN=" + str(VENV) + " " + q(run_episode_qa_argv),
        },
        "render_constraints": (
            "render_portable_timeline.py is the stock-ffmpeg backend (FFMPEG_BIN or "
            "which(ffmpeg)); exactly 1 videoTrack + 1 audioTrack with equal non-zero clip "
            "counts, even width/height, libx264|h264_videotoolbox + aac, no gaps beyond "
            "0.002s, and it hard-rejects effects/transitions/subtitleTracks/textTracks/"
            "overlays/volumeEnvelope and speed!=1.  Target 720x1280 9:16."),
        "loudness_contract": "native_audio_loudness_contract.py DEFAULT_RELEASE_RANGE_LUFS "
                             "= (-17.0, -15.0); level_native_release_audio.py refuses to "
                             "overwrite an existing --output/--qa, so bump --version.  It runs "
                             "AFTER the render because --source is the rendered picture and "
                             "--expected-sha256 binds that file's real bytes.",
        "run_episode_qa_note": (
            "tools/run_episode_qa.sh is recorded but the portable orchestrator invokes the "
            "same registered stage runner through final_qa_evidence_bundle.py with the exact "
            "deployment venv. CURRENT_PORTABLE requests every final/release gate; missing "
            "evidence and REVIEW_REQUIRED_BLOCKING remain blockers."),
        "deliverable": str(p.final_mp4),
        "qa_report": str(p.qa_report),
    }

    # ------------------------------------------------- 3. fail closed on Q2
    if q2["status"] != PASS or not receipts or not reviews:
        res.blockers = ["D-8_Q2_ADMISSION_NOT_COMPLETE_SO_ASSEMBLY_CANNOT_START"]
        res.blockers.extend(q2.get("blockers") or [])
        res.details["missing_input"] = (
            f"{expected_slots} ADMITTED_FOR_ASSEMBLY receipts under {p.q2_dir}/<UNIT_ID>/"
            "admission_result.json plus their ai_review.json; "
            f"found {len(receipts)} receipts / {len(reviews)} review results")
        ctx.say("   S7 BLOCKED — Q2 admission incomplete.  The chain would be:")
        for label in ("build_agentcut", "render_dry_run", "render",
                      "level_native_release_audio", "final_qa_evidence_bundle"):
            ctx.say(f"     [{label}] {res.details['commands'][label]}")
        final_qa = s7_qa(ctx, res)
        res.details["final_qa"] = final_qa
        res.blockers.extend(final_qa.get("blockers") or [])
        return res

    # ------------------------------------------------------------ 4. assemble
    steps: list[dict[str, Any]] = [ctx.run(build_argv, name="s7_build_agentcut_project")]
    if steps[-1]["exit_code"] != 0 or not p.agentcut_project.is_file():
        res.steps.extend(steps)
        res.blockers = ["AGENTCUT_PROJECT_NOT_BUILT"]
        res.details["missing_input"] = str(p.agentcut_project)
        return res
    res.receipts.append(str(p.agentcut_admission))

    # ------------------------------------------------------------- 5. render
    steps.append(ctx.run(render_dry_argv, name="s7_render_dry_run"))
    steps.append(ctx.run(render_argv, name="s7_render_portable_timeline"))
    if steps[-1]["exit_code"] != 0 or not p.picture_native.is_file():
        res.steps.extend(steps)
        res.blockers = ["PICTURE_RENDER_FAILED"]
        res.details["missing_input"] = str(p.picture_native)
        return res

    # ------------------------------------------------- 5b. burn-in subtitles (2026-09-13, Roger: 缺少字幕)
    # The portable renderer rejects subtitleTracks; captions (contract dialogue verbatim, timed by
    # the per-unit faster-whisper windows) are burned onto the rendered picture with PNG overlays.
    subbed = p.assembly / f"{ctx.episode}_picture_native_subbed.mp4"
    asr_json = p.assembly / f"{ctx.episode}_unit_asr.json"
    try:
        from faster_whisper import WhisperModel  # type: ignore
        model = WhisperModel("small", device="cpu", compute_type="int8")
        asr = {}
        for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4")):
            segs, _ = model.transcribe(str(mp4), language="zh", beam_size=5, vad_filter=True)
            asr[mp4.stem] = [{"start": round(x.start, 3), "end": round(x.end, 3), "text": x.text.strip()} for x in segs]
        write_json(asr_json, asr)
    except Exception as exc:  # noqa: BLE001
        res.steps.extend(steps)
        res.blockers = [f"SUBTITLE_ASR_FAILED:{type(exc).__name__}:{exc}"]
        return res
    sub_step = ctx.run([VENV, RT_TOOLS / "build_burnin_subtitles.py", "--episode", ctx.episode,
                        "--project", p.agentcut_project, "--asr", asr_json, "--contract", p.contract,
                        "--grouping", p.grouping_plan, "--source", p.picture_native,
                        "--out-ass", p.assembly / f"{ctx.episode}_subtitles_zh.ass", "--out-video", subbed,
                        "--out-report", p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json"],
                       name="s7_burnin_subtitles")
    steps.append(sub_step)
    if sub_step["exit_code"] != 0 or not subbed.is_file():
        res.steps.extend(steps)
        res.blockers = ["SUBTITLE_BURNIN_FAILED"]
        return res
    res.details["subtitles"] = {"picture": str(subbed), "report": str(p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json")}
    # 5c. studio end card (Roger 2026-09-13): append nalu_runtime/brand/NALU_MOTION_endcard_3s_9x16.mp4
    endcard = Path(f"{_np.RUNTIME_ROOT}/brand/NALU_MOTION_endcard_3s_9x16.mp4")
    outro_seconds = 0.0
    if endcard.is_file():
        with_endcard = p.assembly / f"{ctx.episode}_picture_native_subbed_endcard.mp4"
        cc = subprocess.run([_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(subbed), "-i", str(endcard),
                             "-filter_complex", "[0:v]fps=24,format=yuv420p[v0];[1:v]fps=24,format=yuv420p[v1];"
                             "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
                             "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
                             "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]",
                             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24",
                             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(with_endcard)],
                            capture_output=True, text=True, check=False)
        if cc.returncode != 0 or not with_endcard.is_file():
            res.steps.extend(steps)
            res.blockers = [f"ENDCARD_CONCAT_FAILED:{cc.stderr[-300:]}"]
            return res
        subbed = with_endcard
        outro_seconds = 3.0
        res.details["endcard"] = {"asset": str(endcard), "picture": str(with_endcard), "seconds": outro_seconds}
    # 5d. selective narrative BGM.  Only when the writer's audio_contract.bgm declares SELECTIVE
    # (audio_profile_binding -> NATIVE_MULTIMODAL_SELECTIVE_BGM).  Every provider POST already
    # happened in S6.  S7 has a deliberately read/verify-only chain: verify durable completed
    # transactions -> build the release-timeline placement plan -> reconcile statements -> QA -> mix.
    # No command in this block can generate or submit music.
    binding = ((read_json(p.agentcut_project, {}) or {}).get("metadata") or {}).get("audio_profile_binding") or {}
    profile = str(binding.get("resolved_audio_profile_id") or binding.get("profile") or "")
    if profile == "NATIVE_MULTIMODAL_SELECTIVE_BGM":
        bgm_common = selective_bgm_common_argv(ctx)
        verify_step = ctx.run([VENV, SELECTIVE_BGM, "verify", *bgm_common], name="s7_bgm_verify_s6_transactions")
        steps.append(verify_step)
        if verify_step["exit_code"] != 0:
            res.steps.extend(steps); res.blockers = ["SELECTIVE_BGM_S6_TRANSACTIONS_NOT_COMPLETE"]; return res
        # The release timeline is needed only to place the sources; derive it from the finished picture.
        _write_release_timeline(ctx, p, subbed, outro_seconds, release_timeline)
        plan_step = ctx.run([VENV, SELECTIVE_BGM, "plan", *bgm_common], name="s7_bgm_plan")
        steps.append(plan_step)
        if plan_step["exit_code"] != 0:
            res.steps.extend(steps); res.blockers = ["SELECTIVE_BGM_PLAN_FAILED"]; return res
        # Read-only statement query needs the key; nalu_selective_bgm reconcile has no POST route.
        rec_step = ctx.run([VENV, SELECTIVE_BGM, "reconcile", *bgm_common], name="s7_bgm_reconcile_read_only", paid=True)
        steps.append(rec_step)
        if rec_step["exit_code"] != 0:
            res.steps.extend(steps); res.blockers = ["SELECTIVE_BGM_CREDIT_RECONCILIATION_FAILED"]; return res
        qa_step = ctx.run([VENV, SELECTIVE_BGM, "qa", *bgm_common], name="s7_bgm_qa")
        steps.append(qa_step)
        if qa_step["exit_code"] != 0:
            res.steps.extend(steps); res.blockers = ["SELECTIVE_BGM_CANDIDATES_REJECTED"]; return res
        mixed = p.assembly / f"{ctx.episode}_picture_native_subbed_endcard_bgm.mp4"
        mix_step = ctx.run([VENV, SELECTIVE_BGM, "mix", *bgm_common, "--source", subbed, "--out", mixed],
                           name="s7_bgm_mix")
        steps.append(mix_step)
        if mix_step["exit_code"] != 0 or not mixed.is_file():
            res.steps.extend(steps); res.blockers = ["SELECTIVE_BGM_MIX_FAILED"]; return res
        subbed = mixed
        res.details["selective_bgm"] = {"picture": str(mixed), "plan": str(p.assembly / f"{ctx.episode}_BGM_PLAN.json"),
                                        "stem": str(p.assembly / f"{ctx.episode}_bgm_stem.wav"),
                                        "provider_posts": 0,
                                        "source_generation_stage": "S6"}
    level_argv[level_argv.index("--source") + 1] = subbed

    # ------------------------------------------------- 6. release loudness
    # level_native_release_audio.py reads an episode RELEASE timeline (segments with unit_id /
    # output_start / output_end, content_runtime_seconds, release_runtime_seconds), not the
    # AgentCut project; derive it from the project's video clips and the rendered picture's
    # decoded duration.  This line has no outro card, so the tool's outro window is the final
    # 0.5 s of the last unit (documented; measured and levelled like music).
    try:
        info = _write_release_timeline(ctx, p, subbed, outro_seconds, release_timeline)
        res.details["release_timeline"] = info
    except Exception as exc:  # noqa: BLE001
        res.steps.extend(steps)
        res.blockers = [f"RELEASE_TIMELINE_DERIVATION_FAILED:{type(exc).__name__}:{exc}"]
        return res
    level_argv[-1] = sha256_file(subbed)
    # seq=19 C1-C3: contract attribution + unit-ASR timing of every line on the release timeline,
    # built BEFORE levelling so the leveller can level dialogue windows into the release band
    # (line levelling) and the detectors measure the same windows afterwards.
    speaker_map_pre = p.assembly / f"{ctx.episode}_FINAL_CUT_SPEAKER_MAP.json"
    asr_windows_pre = p.assembly / f"{ctx.episode}_FINAL_CUT_ASR_WINDOWS.json"
    steps.append(ctx.run(
        [VENV, RT_TOOLS / "build_final_cut_speaker_map.py", "--contract", p.contract,
         "--grouping", p.grouping_plan, "--timeline", release_timeline, "--manifest", p.writer_manifest,
         "--out", speaker_map_pre, "--action-windows-out", p.assembly / f"{ctx.episode}_FINAL_CUT_ACTION_WINDOWS.json",
         "--unit-asr", p.assembly / f"{ctx.episode}_unit_asr.json", "--asr-windows-out", asr_windows_pre],
        name="s7_build_final_cut_speaker_map"))
    if asr_windows_pre.is_file():
        level_argv = level_argv[:-2] + ["--line-windows", asr_windows_pre] + level_argv[-2:]
    res.details["commands"]["level_native_release_audio"] = q(level_argv)
    steps.append(ctx.run(level_argv, name="s7_level_native_release_audio"))
    res.receipts.append(str(p.leveled_audio_report))
    if steps[-1]["exit_code"] != 0 or not p.final_mp4.is_file():
        res.steps.extend(steps)
        res.blockers = ["RELEASE_AUDIO_LEVELLING_FAILED"]
        res.details["missing_input"] = str(p.final_mp4)
        res.details["hint"] = ("level_native_release_audio.py refuses to overwrite an existing "
                             "--output/--qa — bump --version if this episode was levelled once "
                             "already.")
        return res

    # ---------------------------------- 6b. final-cut audience detectors (seq=19, D-40)
    # hook / dialogue coverage / silent runs / voice distinctness / emotion dynamics / lexicon /
    # mascot-in-story / loudness on the LEVELLED final; state machine, headcount and creature
    # gait stay NOT_IMPLEMENTED (human review questions).  FAIL blocks the deliverable.
    speaker_map = p.assembly / f"{ctx.episode}_FINAL_CUT_SPEAKER_MAP.json"
    action_windows = p.assembly / f"{ctx.episode}_FINAL_CUT_ACTION_WINDOWS.json"
    asr_windows = p.assembly / f"{ctx.episode}_FINAL_CUT_ASR_WINDOWS.json"   # unit ASR on the release timeline
    detector_report = p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_DETECTORS.json"
    # (the speaker map + ASR windows are built before levelling, see step 6)
    # ------------------------------------------- 6b. seq=27 §六: final cut vs shot table (diagnostic, never blocks)
    # Roger 2026-09-17 memo: scdet cut count vs planned shots, stretched segments, static holds, blank screens.
    # Written to assembly/<EP>_FINAL_CUT_SHOT_PLAN_PARITY.json (+ .md block copied into CHECKPOINT.md at S8).
    if p.final_mp4.is_file():
        parity_json = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.json"
        parity_md = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.md"
        parity_step = ctx.run([VENV, RT_TOOLS / "final_cut_shot_plan_parity.py", "--episode", ctx.episode,
                               "--final", p.final_mp4, "--contract", p.contract,
                               "--grouping-plan", p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json",
                               "--out", parity_json, "--checkpoint-block-out", parity_md],
                              name="s7_final_cut_shot_plan_parity")
        parity_step["diagnostic_only"] = True   # seq=27: no gate_id, never blocks
        parity_step["exit_code"] = 0 if parity_json.is_file() else parity_step["exit_code"]
        steps.append(parity_step)
        res.details["shot_plan_parity"] = {"report": str(parity_json), "checkpoint_block": str(parity_md),
                                           "status": (read_json(parity_json, {}) or {}).get("status"),
                                           "findings": [f.get("code") for f in ((read_json(parity_json, {}) or {}).get("findings") or [])],
                                           "authority": "ENGINE_FINAL_CUT_SHOT_PLAN_PARITY_DIAGNOSTIC_POLICY"}
        res.receipts.append(str(parity_json))

    detector_argv: list[Any] = [VENV, ENGINE / "tools/final_cut_audience_detectors.py",
                                "--media", p.final_mp4, "--out", detector_report,
                                "--lexicon", ctx.p.scope["lexicon"],
                                "--speaker-map", speaker_map, "--story-segments", release_timeline,
                                "--voice-cast", ctx.p.scope["voice_cast"]]
    if asr_windows.is_file():
        # per-unit ASR windows (timing) with contract attribution; whole-file ASR of the levelled final
        # merges speech with wind/music into 10-20 s windows and mismeasures every line (E04 v2, 23:30Z)
        detector_argv += ["--asr-json", asr_windows]
    subtitles = p.assembly / f"{ctx.episode}_subtitles_zh.ass"
    if subtitles.is_file():
        detector_argv += ["--subtitles", subtitles]
    if (RUNTIME / "brand").is_dir():
        detector_argv += ["--brand-dir", RUNTIME / "brand"]
    if action_windows.is_file():
        detector_argv += ["--action-windows", action_windows]
    res.details["commands"]["final_cut_audience_detectors"] = q(detector_argv)
    steps.append(ctx.run(detector_argv, name="s7_final_cut_audience_detectors"))
    res.receipts.append(str(detector_report))
    gate_step = ctx.run([VENV, ENGINE / "tools/final_cut_audience_gate.py", "--report", detector_report,
                         "--video", p.final_mp4, "--out", p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_GATE.json"],
                        name="s7_final_cut_audience_gate")
    steps.append(gate_step)
    res.details["final_cut_audience"] = {"report": str(detector_report),
                                         "gate": str(p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_GATE.json"),
                                         "stdout_tail": gate_step.get("stdout_tail")}
    if gate_step["exit_code"] != 0:
        # The gate row stays FAIL; the stage may continue only on an explicit,
        # source-receipted line-owner order bound to this exact final-cut SHA.
        gate_result = read_json(p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_GATE.json", {}) or {}
        failing = _rga.failing_detectors(gate_result)
        final_sha = sha256_file(p.final_mp4) if p.final_mp4.is_file() else None
        orders_path = ctx.authority.get("orders_path")
        orders = (_rga._orders(orders_path,
                               expected_latest_seq=ctx.authority.get("latest_order_seq") or 0,
                               engine_root=ENGINE)
                  if orders_path and not ctx.authority_blockers else [])
        order = _rga.find_acceptance(
            orders, episode=ctx.episode, gate_id="FINAL-CUT-AUDIENCE-DETECTORS",
            failing=failing, media_sha256=final_sha,
            expected_issuer=ctx.authority.get("line_owner_id") or "", engine_root=ENGINE)
        if order is None:
            res.steps.extend(steps)
            res.blockers = ["FINAL_CUT_AUDIENCE_DETECTORS_FAIL:" + str(gate_step.get("stdout_tail") or "")[-400:]]
            return res
        record = _rga.acceptance_record(order, episode=ctx.episode, gate_id="FINAL-CUT-AUDIENCE-DETECTORS",
                                        failing=failing, media_sha256=final_sha,
                                        gate_result_path=str(p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_GATE.json"))
        acceptance_path = p.assembly / "final_qa" / f"{ctx.episode}_LINE_OWNER_GATE_ACCEPTANCE.json"
        acceptance_path.parent.mkdir(parents=True, exist_ok=True)
        acceptance_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        gate_step["accepted_by_line_owner_order"] = order.get("seq")
        res.details["line_owner_gate_acceptance"] = {**record, "record_path": str(acceptance_path)}
        res.receipts.append(str(acceptance_path))
        ctx.say(f"   !! FINAL-CUT-AUDIENCE-DETECTORS stays FAIL ({', '.join(failing)}); continuing on line-owner order "
                f"seq={order.get('seq')} {order.get('order')!s:.40} -> {acceptance_path.name}")

    # ------------------------------- 7. independent final-audience review
    # The production process may create the media-bound request, but it cannot
    # submit the review.  The separate reviewer must watch the complete final
    # cut with picture+sound, muted, and sound-only, then submit per-shot notes,
    # scores and timestamped events.  Missing/rejected evidence blocks S7.
    res.steps.extend(steps)
    final_audience = s7_final_audience_review(ctx, res)
    res.details["final_audience_review"] = final_audience
    if final_audience["status"] != PASS:
        res.status = (REVIEW_REQUIRED
                      if final_audience["status"] == REVIEW_REQUIRED else BLOCKED)
        res.blockers = list(final_audience.get("blockers") or [])
        return res

    # ------------------------------------------- 8. final-package QA (D-9/D-12)
    final_qa = s7_qa(ctx, res)
    res.details["final_qa"] = final_qa
    res.status = PASS if (p.final_mp4.is_file()
                          and all(step["exit_code"] == 0 or step.get("accepted_by_line_owner_order") for step in steps)
                          and final_qa["status"] == PASS) else BLOCKED
    if res.status != PASS:
        res.blockers = [value for value in (final_qa.get("blockers") or [])] or \
            ["FINAL_PACKAGE_QA_NOT_PASS"]
        return res
    res.blockers = []
    write_json(p.qa_report, {
        "schema": "nalu.episode_final_qa_report.v1", "episode": ctx.episode,
        "recorded_at": now(), "recorded_by": TOOL_ID,
        "final_video": str(p.final_mp4),
        "final_video_sha256": sha256_file(p.final_mp4),
        "picture_native": str(p.picture_native),
        "picture_native_sha256": sha256_file(p.picture_native),
        "agentcut_project": str(p.agentcut_project),
        "agentcut_admission": str(p.agentcut_admission),
        "q2_admission_index": str(p.q2_index),
        "loudness_report": str(p.leveled_audio_report),
        "final_audience_review": final_audience,
        "final_gate_summary": final_qa.get("stage_gate_summary"),
        "final_gate_status": final_qa.get("stage_gate_status"),
        "evidence_bundle": final_qa.get("bundle"),
        "steps": [{"name": step["name"], "exit_code": step["exit_code"], "log": step["log"]}
                  for step in steps]})
    res.receipts.append(str(p.qa_report))
    return res


# --------------------------------------------------------------------------- #
# S7.qa — final-package QA: applicability decision + evidence bundle (D-9)
# --------------------------------------------------------------------------- #
def s7_qa(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """Build evidence and run the registered final/release gates.

    ``CURRENT_PORTABLE`` executes the complete registry set. Missing reviewer
    evidence, objective metrics, an event ledger, or a required BGM stem is a
    blocker. Historical replay may retain its recorded subset, but neither path
    writes an N/A/PASS row on behalf of a reviewer.
    """
    p = ctx.p
    applic_step = qa_run(ctx, [FINAL_QA_BUNDLE, "applicability", "--episode", ctx.episode],
                         name="s7_qa_gate_applicability")
    res.steps.append(applic_step)
    applicability_record = qa_json(applic_step)
    build_step = qa_run(ctx, [FINAL_QA_BUNDLE, "build", "--episode", ctx.episode],
                        name="s7_qa_build_evidence_bundle")
    res.steps.append(build_step)
    build = qa_json(build_step)
    detail: dict[str, Any] = {
        "sub_stage": "S7.qa",
        "bundle": build.get("bundle"),
        "bundle_sha256": build.get("bundle_sha256"),
        "keys_total": build.get("keys_total"),
        "keys_present": build.get("keys_present"),
        "keys_absent": [row.get("key") for row in build.get("absent") or []],
        "keys_not_produced": [row.get("key") for row in build.get("keys_not_produced") or []],
        "bundle_status": build.get("status"),
        "applicability_record": str(p.assembly / "final_qa"
                                    / f"{ctx.episode}_FINAL_GATE_APPLICABILITY.json"),
        "policy_profile": applicability_record.get("policy_profile") or _policy.selected(),
        "applicable_gates": applicability_record.get("applicable_count"),
        "not_applicable_gates": applicability_record.get("not_applicable_count"),
        "registered_gate_omission_allowed": applicability_record.get(
            "registered_gate_omission_allowed"
        ),
        "run_episode_qa_contract": (
            "CURRENT_PORTABLE runs the complete final/release registry. Missing evidence and "
            "REVIEW_REQUIRED are blocking states, never PASS."
        ),
    }
    gate_step = qa_run(ctx, [FINAL_QA_BUNDLE, "run", "--episode", ctx.episode,
                             "--gate-subset", "applicable"],
                       name="s7_qa_episode_stage_gate_runner")
    res.steps.append(gate_step)
    gate = qa_json(gate_step)
    summary_path = Path(gate.get("summary_path") or (
        p.assembly / "final_qa/mandatory_stage_gates"
        / "episode_stage_gate_execution_summary.json"))
    summary = read_json(summary_path, {}) or {}
    detail["stage_gate_status"] = gate.get("status") or summary.get("status")
    detail["stage_gate_exit_code"] = gate.get("exit_code", gate_step.get("exit_code"))
    detail["stage_gate_failures"] = (gate.get("failures")
                                     or (summary.get("failures") or [])[:12])
    detail["stage_gate_summary"] = str(summary_path)
    detail["stage_gate_rows"] = [
        {"gate_id": row.get("gate_id"), "status": row.get("status"),
         "first_failure": (row.get("failures") or [None])[0]}
        for row in summary.get("results") or []]
    detail["status"] = PASS if gate.get("status") == PASS else BLOCKED
    acceptance = (res.details or {}).get("line_owner_gate_acceptance")
    if detail["status"] != PASS and acceptance:
        # the accepted gate keeps its FAIL row; the package passes only if every OTHER applicable gate PASSes
        other_not_pass = [row.get("gate_id") for row in summary.get("results") or []
                          if row.get("status") != PASS and row.get("gate_id") != acceptance.get("gate_id")]
        if not other_not_pass:
            detail["status"] = PASS
            detail["status_note"] = (f"{acceptance.get('gate_id')} row kept FAIL; package continued on line-owner order "
                                     f"seq={acceptance.get('order_seq')} ({acceptance.get('record_path')})")
        else:
            detail["other_gates_not_pass"] = other_not_pass
    detail["blockers"] = ([] if detail["status"] == PASS else
                          ["FINAL_PHASE_REGISTERED_GATE_EVIDENCE_OR_REVIEW_NOT_PASS"])
    res.receipts.append(str(detail["bundle"]) if detail.get("bundle") else "")
    return detail


# --------------------------------------------------------------------------- #
# S8 — checkpoint (write CHECKPOINT.md, then block for `approve`)
# --------------------------------------------------------------------------- #
def stage_s8(ctx: Ctx) -> StageResult:
    p = ctx.p
    p.deliver.mkdir(parents=True, exist_ok=True)
    write_checkpoint(ctx)
    approved = p.approval.is_file()
    res = StageResult(PASS if approved else "AWAITING_APPROVAL")
    res.details = {
        "checkpoint": str(p.checkpoint),
        "approval_flag": str(p.approval),
        "approved": approved,
        "unblock_with": (f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} approve --episode {ctx.episode} "
                         f"--by {shlex.quote(str(ctx.authority.get('line_owner_id') or '<LINE_OWNER_ID>'))}"),
        "platform_upload": "NEVER — this pipeline has no publish path.",
    }
    res.receipts = [str(p.checkpoint)]
    if not approved:
        res.blockers = ["AWAITING_LINE_OWNER_APPROVAL"]
    return res


def credits_summary(ctx: Ctx) -> dict[str, Any]:
    ledger = read_json(RT / "budget/ledger.json", {}) or {}
    entries = [row for row in (ledger.get("entries") or [])
               if row.get("episode") == ctx.episode]
    latest = entries[-1] if entries else {}
    planned = {sid: ctx.stage_state(sid).get("planned_credits") or 0 for sid in STAGE_IDS}
    return {
        "cap": ctx.cap,
        "planned_by_stage": planned,
        "planned_total": sum(planned.values()),
        "recorded_total_credits": latest.get("recorded_total_credits", 0),
        "headroom_credits": latest.get("headroom_credits", ctx.cap),
        "cost_plan_first_pass_total": (ctx.cost_plan.get("first_pass") or {}).get("total"),
        "ledger": str(RT / "budget/ledger.json"),
    }


def write_checkpoint(ctx: Ctx) -> Path:
    p = ctx.p
    state = ctx.state
    credits = credits_summary(ctx)
    lines: list[str] = []
    add = lines.append
    add(f"# {ctx.episode} CHECKPOINT — {ctx.p.scope['series_id']} production line")
    add("")
    add(f"* written by `{TOOL_ID}` at {now()}")
    add(f"* state file `{p.state}`")
    add(f"* logs `{p.logs}`")
    add(f"* deliverable target `{p.final_mp4}`  (9:16, SD2 seedance-2.0-pro 720p → 720x1280)")
    add("")
    # SUPERVISOR_ORDERS seq=29 规则 6: the episode's realised speech rate goes to the S8 screening note
    postgen = read_json(p.postgen_summary, {}) or {}
    if isinstance(postgen.get("speech_rate_episode"), dict):
        add(str(postgen["speech_rate_episode"].get("checkpoint_line") or ""))
        add("")
    add("## Stage status")
    add("")
    add("| stage | what | status | blockers |")
    add("|---|---|---|---|")
    for sid in STAGE_IDS:
        row = ctx.stage_state(sid)
        blockers = ", ".join(row.get("blockers") or []) or "—"
        add(f"| {sid} | {STAGE_TITLES[sid]} | `{row.get('status')}` | {blockers} |")
    add("")
    add("## What to watch (line-owner review list)")
    add("")
    if p.final_mp4.is_file():
        add(f"1. `{p.final_mp4}` — full episode, 9:16.")
        add(f"   sha256 `{sha256_file(p.final_mp4)}`")
        add(f"2. QA report `{p.qa_report}`")
    else:
        add("**There is no cut to watch yet.**  The pipeline stopped before S7 produced")
        add(f"`{p.final_mp4}`.  What exists to review instead:")
        for label, path in (
                ("preproduction report", p.preprod_report),
                ("29-unit grouping plan", p.grouping_plan),
                ("video transaction manifest", p.video_transaction),
                ("identity bootstrap report", p.identity_report),
                ("identity admission route status", p.identity_admission),
                ("keyframe admission route status", p.keyframe_admission),
                ("Q2 assembly admission index", p.q2_index),
                ("post-generation QA summary", p.postgen_summary),
                ("AgentCut admission", p.agentcut_admission),
                ("release loudness report", p.leveled_audio_report),
                ("voice payloads", p.speech_payloads)):
            if Path(path).is_file():
                add(f"* {label}: `{path}`")
        add("")
        add("The first stage that did not pass names its own missing input in the state")
        add(f"file's `blockers` and in `details.missing_input`: `{p.state}`.")
    add("")
    add("## QA summary")
    add("")
    for sid in STAGE_IDS:
        row = ctx.stage_state(sid)
        details = row.get("details") or {}
        interesting = {key: value for key, value in details.items()
                       if key in ("gate10", "character_entity_contract", "engine_report_status",
                                  "machine_gate_reports", "keyframe_entry_state_gate",
                                  "asset_library_gate_status", "post_generation_qa_scope",
                                  "video_preflight_pass", "efficiency_status",
                                  "bootstrap_status", "submitter_precheck")}
        if interesting:
            add(f"* **{sid}** — " + "; ".join(
                f"`{key}`={json.dumps(value, ensure_ascii=False)}" for key, value in interesting.items()))
    add("")
    add("## Rights basis on record")
    add("")
    rights = state.get("rights_basis") or {}
    add(f"* basis: `{rights.get('basis')}`")
    add(f"* declared by **{rights.get('declared_by')}** on {rights.get('declared_on')} — "
        f"`{rights.get('declaration_type')}`")
    add(f"* authority: `{rights.get('authority')}` seq={rights.get('order_seq')} "
        f"({rights.get('order_id')}), conditions {', '.join(rights.get('conditions') or [])}")
    add(f"* scope: {rights.get('scope')}")
    add(f"* **not covered**: {rights.get('not_covered')}")
    add("")
    add("## Credits spent vs cap")
    add("")
    add(f"* cap: **{credits['cap']}** credits per episode "
        f"(private line-owner order seq={ctx.authority.get('paid_order_seq')}, HARD_STOP)")
    add(f"* recorded spend this episode: **{credits['recorded_total_credits']}**")
    add(f"* planned this run: **{credits['planned_total']}** "
        f"({json.dumps(credits['planned_by_stage'])})")
    add(f"* cost plan first pass: **{credits['cost_plan_first_pass_total']}** "
        "(identity 198 + voices 12 + keyframes 330 + video 3500)")
    add(f"* ledger: `{credits['ledger']}`")
    add("")
    add("## Known defects / open decisions blocking release")
    add("")
    decisions = state.get("open_decisions") or []
    blocking = [row for row in decisions if row.get("status") != "RESOLVED"]
    resolved = [row for row in decisions if row.get("status") == "RESOLVED"]
    if blocking:
        for row in blocking:
            add(f"* **{row.get('id')}** — {row.get('detail')}")
            if row.get("missing"):
                add(f"  * still missing: {row['missing']}")
    else:
        add("* none recorded")
    if resolved:
        add("")
        add("### Resolved since the last checkpoint")
        add("")
        for row in resolved:
            add(f"* **{row.get('id')}** — {row.get('resolution') or row.get('detail')}")
            if row.get("residual"):
                add(f"  * residual: {row['residual']}")
    parity_md = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.md"
    if parity_md.is_file():  # seq=27 §六: diagnostic block for the line owner's screening
        add("")
        add(parity_md.read_text(encoding="utf-8").rstrip())
    add("")
    add("## Approval")
    add("")
    add("This episode does NOT advance and the next episode does NOT start until:")
    add("")
    add("```")
    add(f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} approve --episode {ctx.episode} "
        f"--by {shlex.quote(str(ctx.authority.get('line_owner_id') or '<LINE_OWNER_ID>'))}")
    add("```")
    add("")
    add(f"That writes `{p.approval}`, which `loop` polls.  No platform upload is ever")
    add("performed by this pipeline.")
    add("")
    p.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    p.checkpoint.write_text("\n".join(lines), encoding="utf-8")
    return p.checkpoint


# --------------------------------------------------------------------------- #
# stage dispatch table
# --------------------------------------------------------------------------- #
STAGE_FUNCS: dict[str, Callable[[Ctx], StageResult]] = {
    "S1": stage_s1,
    "S2": stage_s2,
    "S3": stage_s3,
    "S4": stage_s4,
    "S5": stage_s5,
    "S6": stage_s6,
    "S7": stage_s7,
    "S8": stage_s8,
}
FINGERPRINTS: dict[str, Callable[[Ctx], str]] = {"S1": fp_s1, "S2": fp_s2}

OPEN_DECISIONS = [
    # --------------------------------------------------------------- resolved
    {"id": "D-1", "stage": "S3", "status": "RESOLVED",
     "detail": "The nalu character asset registry for QINGSHAN_CHARACTER_REGISTRY is now "
               "generated by runtime/tools/identity_qa_lock.py registry, from LOCKED plates "
               "only, in the shape multimodal_character_binding_guard._character_authority "
               "reads (characters[<registry_id>].generation_reference_image, guard:204-206 "
               "and 430-436) and character_identity_admission_gate.evaluate membership-tests.",
     "resolution": "runtime/tools/identity_qa_lock.py registry --episode <EP>",
     "residual": "the registry is only written once at least one character reaches "
                 "status LOCKED + qa.status PASS; an unlocked character is deliberately "
                 "absent so the binding guard reports CANONICAL_VISUAL_REFERENCE_MISMATCH"},
    {"id": "D-2", "stage": "S3", "status": "RESOLVED",
     "detail": "insightface 2.0 is installed in .qingshan-venv (with onnx 1.22, "
               "opencv-python 5.0, scikit-image 0.26) and the buffalo_l ONNX weights are "
               "already present under ~/.insightface/models/buffalo_l, so "
               "CHARACTER-IDENTITY-ADMISSION runs INSIGHTFACE_COSINE_V1 for real.",
     "resolution": "verified: FaceAnalysis(name='buffalo_l').prepare(ctx_id=-1) loads and "
                   "embeds a real 512-d normed_embedding from a source plate",
     "residual": "the weights live in the user's home, not in the clone. On a fresh machine "
                 "the first prepare() downloads buffalo_l (~289 MB) from the insightface "
                 "model zoo; if that download is blocked the gate raises "
                 "INSIGHTFACE_RUNTIME_UNAVAILABLE and every identity QA FAILs closed."},
    {"id": "D-3", "stage": "S3", "status": "RESOLVED",
     "detail": "runtime/tools/identity_qa_lock.py writes qa.status PASS/FAIL and status "
               "LOCKED (only on PASS) into ai_drama.production_asset_library.v1 in exactly "
               "the shape initial_asset_library.gate_asset demands (status == 'LOCKED' by "
               "exact equality, non-empty lock fields per category, artifacts with "
               "role/media_type/path/sha256, non-empty provenance, qa.checks). The verdict "
               "comes from a Claude VLM plate review plus a real insightface cosine — not "
               "from --accept-source-qa, which is an operator declaration.",
     "resolution": "runtime/tools/vlm_review_protocol.py request --kind identity → "
                   "identity_qa_lock.py lock --episode <EP> --review <submitted>",
     "residual": "gate_asset also demands rights.status PASS with a named basis. The basis now "
                 "comes only from the validated deployment-private paid-production order and "
                 "its confirmed source receipt; it is never a reviewer observation or an engine "
                 "default. It is passed as --rights-basis to bootstrap_identity_cards.py and "
                 "identity_qa_lock.py and recorded under rights_basis with declaration_type "
                 "LINE_OWNER_DECLARATION_NOT_A_REVIEWER_OBSERVATION. Publication remains outside "
                 "scope unless the order explicitly says publication_allowed=true."},
    {"id": "D-4", "stage": "S5", "status": "RESOLVED",
     "detail": "runtime/tools/keyframe_q1_builder.py is the parameterised builder of "
               "qingshan.shot_media_admission_request.v2 and invokes "
               "tools/shot_media_admission_gate.py for real. Its three P0 objective blocks "
               "are real runs: VLM_STRUCTURED_STATE_QA_V1 from the submitted keyframe "
               "review, CLOSED_SET_ANACHRONISM_OCR_V1 from tools/still_image_ocr_audit.py "
               "(RapidOCR/ONNX, rapidocr-onnxruntime 1.4.4 installed), and "
               "INSIGHTFACE_COSINE_V1 through the engine's own identity gate.",
     "resolution": "route validated end to end: a real review of a real image returned "
                   "FAIL / FAIL_NOT_ADMITTED with the named P0 gate failures, and a "
                   "labelled positive control returned ADMITTED / ADMITTED_FOR_VIDEO_SUBMIT "
                   "with all four registered gates passing — for both the "
                   "STRUCTURED_NO_VISIBLE_CHARACTER_V1 and the INSIGHTFACE_COSINE_V1 "
                   "identity block. See runtime/reviews/_route_validation/.",
     "residual": "see D-13: a still cannot supply 3 sample frames from one source, so the "
                 "identity measurement is corpus-scoped per character."},
    {"id": "D-5", "stage": "S5", "status": "RESOLVED",
     "detail": "runtime/tools/start_frame_evidence_writer.py writes "
               "qingshan.start_frame_semantic_evidence.v1 per unit with review_method "
               "CLAUDE_VLM_STRUCTURED_REVIEW, at the path build_nalu_preproduction.py "
               "already declares in expected_evidence_ref "
               "(reports/start_frame_evidence/<UNIT>_start_frame_evidence.json, resolved "
               "against the engine root by grouped_anchor_semantic_contract._resolve). "
               "build_nalu_preproduction.build_start_frame_contracts now READS that path "
               "and adopts only what the receipt itself states; a missing, non-PASS or "
               "sha-stale receipt leaves the contract BLOCKED exactly as before.",
     "resolution": "vlm_review_protocol.py request --kind start_frame → "
                   "start_frame_evidence_writer.py write, then the S6 preproduction "
                   "rebuild picks it up and 4.4 re-verifies every field",
     "residual": "none"},
    {"id": "D-6", "stage": "S6", "status": "RESOLVED",
     "detail": "runtime/tools/post_generation_qa_runner.py performs all 12 allowed "
               "technical checks and all 5 allowed basic-plot checks, and no forbidden "
               "check. Real measurers: ffprobe (decode/duration/resolution/aspect_ratio/"
               "codec/audio_stream/av_sync/frame_rate/sample_rate/corruption), "
               "run_regression_ci.pure_black_frame_stats (black_frame), "
               "run_regression_ci.freeze_stats + static_hold_stats (freeze), "
               "tools/frame_cadence_audit.py, tools/source_brightness_jump_audit.py, "
               "tools/media_boundary_acceptance.py, and tools/source_video_dialogue_gate.py "
               "(faster-whisper 1.2.1) for dialogue presence. It writes "
               "TECHNICAL_PASS_CONTENT_UNREVIEWED per unit, an ADMIT/REJECT with reasons, "
               "and a reroll request list the real reroll_cost_guard accepts.",
     "resolution": "validated against a real 720x1280/24fps/48kHz clip: all 12 technical "
                   "checks measured and PASSed, the ASR gate ran, the 2-fps contact sheet "
                   "rendered, and reroll_cost_guard.py returned "
                   "PASS_AUTO_REROLL_ALLOWED for a generated request row",
     "residual": "homophones are RECORDED and never rejected, per "
                 "runtime/configs/BASIC_DIALOGUE_QA_POLICY.json — see D-14 for that file's "
                 "provenance."},
    {"id": "D-9", "stage": "S7", "status": "RESOLVED",
     "detail": "runtime/tools/final_qa_evidence_bundle.py classifies 12 final/release gates "
               "APPLICABLE and 9 NOT_APPLICABLE for a native-audio SD2 line with no BGM and "
               "no audience-score stage, assembles the 15-key bundle (the runbook's 11 plus "
               "credit_ledger, watch_report and the sha-verified canonical_script pair) and "
               "invokes episode_stage_gate_runner.py with an explicit --gate list.",
     "resolution": "proved against E01's current empty state: the runner parsed the bundle, "
                   "the sha-verified canonical_script binding passed (zero canonical_script "
                   "failures), 11 gates failed only on required_evidence_missing:<key> and "
                   "GIGGLE-CREDIT-LEDGER-CLOSURE actually executed on the real "
                   "runtime/budget/ledger.json. The bundle SHAPE is accepted.",
     "residual": "see D-12."},
    # ----------------------------------------------------------------- open
    {"id": "D-7", "stage": "S6", "status": "RESOLVED",
     "detail": "Q2 content admission (shot_media_admission_gate.py kind VIDEO_ASSEMBLY, "
               "terminal downstream_status ADMITTED_FOR_ASSEMBLY) needs FIVE registered gates "
               "— the four keyframe gates plus DEFECT-TIER-TOLERANCE — and a technical_qa "
               "block whose status is exactly TECHNICAL_PASS_CONTENT_UNREVIEWED (the keyframe "
               "branch forbids that string; the video branch demands it). The only precedent, "
               "tools/build_e40_video_q2_evidence.py, is hard-disabled "
               "(LEGACY_E40_Q2_EVIDENCE_BUILDER_DISABLED) and its evidence rows predate the P0 "
               "objective requirement entirely, so it would fail today with "
               "p0_objective_method_invalid:MISSING on three gates.",
     "resolution": "runtime/tools/video_q2_builder.py is the parameterised builder, invoked as "
                   "sub-stage S6.q2 and re-verified at the head of S7. Every block is a real "
                   "run: VLM_STRUCTURED_STATE_QA_V1 from a submitted `video_q2` review (a new "
                   "closed 12-question kind added to vlm_review_protocol.py, every question "
                   "inside post_generation_qa_scope_gate's ALLOWED scope — none of its 16 "
                   "forbidden gesture/choreography/trajectory/optical-flow checks is asked); "
                   "CLOSED_SET_ANACHRONISM_OCR_V1 from a real still_image_ocr_audit.py pass "
                   "over EVERY extracted original-resolution frame; INSIGHTFACE_COSINE_V1 "
                   "through the engine's own character_identity_admission_gate; "
                   "DEFECT-TIER-TOLERANCE from a real tools/defect_tolerance_gate.py run over "
                   "the reviewer's own defect list at the unit's measured ffprobe duration; and "
                   "technical_qa copied verbatim from the D-6 record.",
     "residual": "a clip reaches sample_frames_per_source_min from ONE source (5 real distinct "
                 "frames of that very asset), so D-13's corpus-scoping is neither needed nor "
                 "used here. A P2 defect the reviewer did not locate (shot_index + at_seconds) "
                 "is NOT guessed and NOT dropped: the unit is REJECTED with "
                 "DEFECT_TIER_LOCATION_MISSING, because defect_tolerance_gate.py prices its "
                 "opening-10s / tail-5s zero-tolerance windows from that location."},
    {"id": "D-8", "stage": "S7", "status": "RESOLVED",
     "detail": "build_agentcut_from_admitted_storyboard_sources.py requires --receipt "
               "(tasks[].source_id/output_path/status/duration) and --review-result "
               "(passed_items[].path) inputs that only exist once D-7 is resolved, and it "
               "hard-fails unless the count of distinct admitted source_ids equals "
               "--expected-slots exactly AND every admitted slot's path also appears in a "
               "review result's passed_items.",
     "resolution": "S6.q2 writes both per unit — admission_result.json (the gate's own report) "
                   "and ai_review.json (passed_items only for a unit whose downstream_status is "
                   "ADMITTED_FOR_ASSEMBLY). S7 is wired as Q2 verify -> "
                   "build_agentcut_from_admitted_storyboard_sources.py --generation-contract -> "
                   "render_portable_timeline.py (--dry-run then real) -> "
                   "level_native_release_audio.py -> final_qa_evidence_bundle.py run "
                   "--gate-subset applicable -> deliverables/<EP>/<EP>_final_9x16.mp4 + "
                   "CHECKPOINT.md.",
     "residual": "no media is ever stubbed. Until the paid video stage runs, S7 prints every "
                 "command it would run and BLOCKS on the precise missing input (the "
                 "ADMITTED_FOR_ASSEMBLY receipts). The final gate execution still carries "
                 "D-12."},
    {"id": "D-10", "stage": "S2/S3 (E02+)", "status": "RESOLVED",
     "detail": "asset_requirements.json, the identity prompts and the global space map existed "
               "only for E01, and the E01 generators under runtime/preproduction/E01/tools/ "
               "take no arguments and hardcode E01 paths.",
     "resolution": "S2 and S3 now run a shared, cached pre-step (ensure_episode_inputs): "
                   "extend_global_space_map.py first WITHOUT --asset-requirements (base = the "
                   "previous episode's locked GSM when it exists, else E01's), then "
                   "build_episode_asset_requirements.py with --overlay when "
                   "preproduction/<EP>/asset_requirements_overlay.json (or overlay.json) "
                   "exists and without it otherwise, then extend_global_space_map.py again WITH "
                   "--asset-requirements so a new location picks up its authored "
                   "key_fixed_elements. E01 keeps its authored files: when both the GSM and the "
                   "requirements already exist the pre-step runs nothing at all. Exit 3 from "
                   "the requirements builder (an AUTHORING_REQUIRED_* sentinel landed in the "
                   "output) is a FAIL-CLOSED stop with state AUTHORING_REQUIRED, the authoring "
                   "gaps listed and the overlay path to author named.",
     "residual": "series_bible_sha256 is still a stand-in (stage-map blocker R-1). A new "
                 "location the tool auto-sited is gate-clean but its position relative to the "
                 "village was chosen by the tool, so the stage records "
                 "AUTO_SITED_REQUIRES_SPATIAL_REVIEW as a warning for a human to confirm or to "
                 "author preproduction/<EP>/new_location_place_spec.json."},
    {"id": "D-11", "stage": "S3/S5/S6", "status": "RESOLVED",
     "detail": "Every paid submit needs a real authorization_ref and provider_post_allowed "
               "true, and the image submitter's validate_submission_authority (which "
               "--precheck-only SKIPS) additionally needs EXACTLY ONE GIGGLE-REROLL-COST-GUARD "
               "report bound to the submitted manifest's exact SHA.",
     "resolution": "The deployment explicitly configures a private SUPERVISOR_ORDERS path, "
                   "paid order sequence, observed latest sequence and line-owner identity. "
                   "The materialiser validates the order schema, unique sequence, confirmed "
                   "source receipt, exact episode scope, rights declaration, cap, model and "
                   "paid_requests_allowed=true. Immediately before each paid submit the "
                   "orchestrator runs materialize_paid_authorization.py on the plan (S3) or the "
                   "manifest (S5 keyframes, S6 video), which writes a "
                   "*_PAID_AUTHORIZED copy plus the real reroll-cost-guard report, and the "
                   "submitter is fed THAT copy — never the original, which stays on disk "
                   "un-authorised as evidence of what was compiled. In a dry run the exact "
                   "command is printed and NOT executed (it appends to the real credit ledger "
                   "through nalu_budget_ledger.py --check).",
     "residual": "provider_post_allowed:true in a file is only ONE of the locks: --paid and "
                 "qingshan.json generation.paid_requests_enabled=true remain independently "
                 "required, and today the config still says false. The materialiser must be "
                 "re-run after ANY edit to the input file, because the guard report binds its "
                 "byte SHA."},
    {"id": "D-12", "stage": "S7",
     "detail": "Neither configs/GATE_REGISTRY_v3_20260716.json nor "
               "tools/episode_stage_gate_runner.py has ANY applicability mechanism: there "
               "is no applies_when field, no required_inputs, no waiver and no skip. "
               "tools/gate_result_contract.py already allows an N_A status but the runner "
               "can only ever write PASS or FAIL. So a line with no BGM and no "
               "audience-score stage can only express 'this gate does not apply' by "
               "omitting it from the --gate list, which REGISTRY-META-05-RUNTIME-INVOCATION "
               "calls fail-closed. tools/run_episode_qa.sh cannot express it at all because "
               "it hardcodes --phase final --phase release.",
     "candidates": ["configs/GATE_REGISTRY_v3_20260716.json",
                    "tools/episode_stage_gate_runner.py", "tools/gate_result_contract.py",
                    "tools/run_episode_qa.sh"],
     "missing": "an engine-side applies_when (or profile-scoped gate set) the runner honours "
                "by emitting the existing N_A status, plus a run_episode_qa.sh that accepts "
                "a gate list. Until then this pipeline omits the 9 inapplicable gates BY "
                "NAME with a written reason and writes no self-issued waiver — "
                "FINAL-CUT-NO-SELF-WAIVER exists to forbid that."},
    {"id": "D-13", "stage": "S5",
     "detail": "CHARACTER-IDENTITY-ADMISSION is registered with "
               "sample_frames_per_source_min 3 and character_identity_admission_gate "
               "enforces it literally, but a keyframe is one still and can only ever supply "
               "one sample. keyframe_q1_builder therefore scopes the measurement to one "
               "source PER CHARACTER over every keyframe the script declares that character "
               "visible in, which reaches the minimum with real distinct frames and still "
               "reports each keyframe's own cosine. A character declared visible in fewer "
               "than three keyframes cannot reach the minimum and its keyframes are "
               "REJECTED with SAMPLE_MINIMUM_UNREACHABLE.",
     "candidates": ["tools/character_identity_admission_gate.py",
                    "configs/GATE_REGISTRY_v3_20260716.json"],
     "missing": "a line-owner decision: accept the corpus-scoped reading, or register a "
                "still-specific sample minimum. Nothing is waived either way — a character "
                "below the minimum blocks."},
    {"id": "D-14", "stage": "S6",
     "detail": "configs/BASIC_DIALOGUE_QA_POLICY.json does not exist in this engine clone. "
               "runtime/configs/BASIC_DIALOGUE_QA_POLICY.json was authored for this line "
               "and every threshold in it is copied verbatim from the engine code that "
               "already enforces it (source_video_dialogue_gate.py --minimum-recall 0.55 "
               "and its failure codes, run_regression_ci.speech_density_stats 15.0/10.0 "
               "segments per minute, source_video_dialogue_gate's orthographic variants, "
               "apply_asr_homophone_adjudication.py's HOMOPHONE_OR_SCRIPT_VARIANT).",
     "candidates": ["runtime/configs/BASIC_DIALOGUE_QA_POLICY.json",
                    "tools/source_video_dialogue_gate.py",
                    "tools/apply_asr_homophone_adjudication.py"],
     "missing": "confirmation from the engine owner that the recorded thresholds are the "
                "intended line policy, or an engine-side config to supersede it"},
]


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #
def run_episode(ctx: Ctx) -> int:
    args = ctx.args
    order = STAGE_IDS
    first = args.from_stage or order[0]
    last = args.until or order[-1]
    if first not in order or last not in order:
        raise SystemExit(f"--from/--until must be one of {order}")
    selected = order[order.index(first): order.index(last) + 1]

    ctx.say("=" * 78)
    ctx.say(f"nalu_pipeline run  episode={ctx.episode}  stages={selected[0]}..{selected[-1]}")
    ctx.say(f"  mode: dry_run={ctx.dry}  --paid={ctx.want_paid}  "
            f"qingshan.json paid_requests_enabled={ctx.config_paid_enabled}  "
            f"=> PAID STEPS {'ENABLED' if ctx.paid_enabled else 'DISABLED'}")
    ctx.say(f"  cap={ctx.cap} credits/episode   concurrency<= {min(ctx.max_parallel, 6)}")
    ctx.say(f"  state={ctx.p.state}")
    ctx.say(f"  logs={ctx.p.logs}")
    ctx.say("=" * 78)

    ctx.state["open_decisions"] = OPEN_DECISIONS
    # The rights basis is recorded in the state file as what it is: the line
    # owner's own declaration.  No measurer and no reviewer can observe a rights
    # basis, so nothing in this pipeline may derive, widen or invent one.
    ctx.state["rights_basis"] = ctx.rights_declaration
    ctx.state["line_owner_authority"] = {
        "orders_path": (str(ctx.authority.get("orders_path"))
                        if ctx.authority.get("orders_path") else None),
        "paid_order_seq": ctx.authority.get("paid_order_seq"),
        "latest_order_seq": ctx.authority.get("latest_order_seq"),
        "line_owner_id": ctx.authority.get("line_owner_id"),
        "status": "PASS" if ctx.paid_order else "BLOCKED",
        "failures": list(ctx.authority_blockers),
        "order_id": (ctx.paid_order or {}).get("id"),
        "orders_file_sha256": (ctx.paid_order or {}).get("orders_file_sha256"),
        "source_receipt": (ctx.paid_order or {}).get("source_receipt"),
    }
    ctx.state.pop("review_required", None)
    ctx.state["layers"] = {"source": ctx.p.layers_source, "paths": {k: str(v) for k, v in ctx.p.layers().items()}}
    ctx.state["series_scope"] = {"scope_id": ctx.p.scope["scope_id"], "series_id": ctx.p.scope["series_id"], "asset_library": str(ctx.p.scope["asset_library"])}
    ctx.state["runs"] = (ctx.state.get("runs") or [])[-19:] + [{
        "run_id": ctx.run_id, "at": now(), "stages": selected,
        "dry_run": ctx.dry, "paid_requested": ctx.want_paid,
        "paid_enabled": ctx.paid_enabled, "log": str(ctx.run_log)}]
    ctx.save_state()

    exit_code = 0
    for sid in selected:
        row = ctx.stage_state(sid)
        fingerprint = FINGERPRINTS.get(sid, lambda _c: None)(ctx)
        if (not ctx.force and row.get("status") in TERMINAL_OK
                and (fingerprint is None or fingerprint == row.get("input_fingerprint"))):
            ctx.say(f"\n-- {sid} {STAGE_TITLES[sid]}: SKIPPED (already PASS, inputs unchanged)")
            row["status"] = SKIPPED
            ctx.save_state()
            continue
        ctx.say(f"\n-- {sid} {STAGE_TITLES[sid]}")
        row["attempts"] = int(row.get("attempts") or 0) + 1
        row["started_at"] = now()
        try:
            result = STAGE_FUNCS[sid](ctx)
        except _media.MediaToolBlocked as exc:
            result = StageResult(BLOCKED, media_tool_error=str(exc))
            result.blockers = [str(exc)]
        except Exception as exc:  # noqa: BLE001 — a stage crash must not lose state
            result = StageResult("CRASHED", exception=f"{type(exc).__name__}: {exc}")
            result.blockers = [f"STAGE_CRASHED:{type(exc).__name__}:{exc}"]
        row.update({
            "status": result.status,
            "finished_at": now(),
            "input_fingerprint": fingerprint,
            "details": result.details,
            "receipts": result.receipts,
            "blockers": result.blockers,
            "planned_credits": result.planned_credits,
            "steps": [{key: value for key, value in step.items()
                       if key != "stdout_tail" or len(str(value)) < 2000}
                      for step in result.steps],
        })
        ctx.state["current_stage"] = sid
        ctx.state["credits"] = credits_summary(ctx)
        ctx.save_state()
        ctx.say(f"   {sid} => {result.status}"
                + (f"   blockers: {', '.join(result.blockers)}" if result.blockers else ""))

        if result.status == HARD_STOP:
            ctx.say("!! budget HARD_STOP — stopping the run.  Nothing was submitted.")
            exit_code = 3
            break
        if result.status == REVIEW_REQUIRED:
            requests = [str(value) for value in (result.receipts or [])
                        if str(value).endswith("_request.json")]
            ctx.state["review_required"] = {
                "stage": sid,
                "sub_stage": (result.details.get("identity_qa")
                              or result.details.get("q1_admission")
                              or result.details.get("start_frame_evidence")
                              or result.details.get("post_generation_qa")
                              or result.details.get("q2_admission")
                              or {}).get("sub_stage"),
                "requests": requests,
                "reviewer": REVIEWER_ID,
                "at": now(),
                "resume": f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} run "
                          f"--episode {ctx.episode} --from {sid}",
            }
            ctx.save_state()
            ctx.say(f"!! {sid} needs a machine review before it can advance.  "
                    "Answer the request, submit it, then re-run.")
            exit_code = REVIEW_EXIT_CODE
            if not ctx.dry:
                break
            ctx.say(f"   (dry-run: continuing past {sid} so the whole plan prints)")
            continue
        if result.status not in TERMINAL_OK and result.status != DRY:
            exit_code = max(exit_code, 2)
            if not ctx.dry:
                ctx.say(f"!! {sid} did not pass — stopping (resume with "
                        f"--from {sid} once the blocker is cleared)")
                break
            ctx.say(f"   (dry-run: continuing past {sid} so the whole plan prints)")

    # S8 always leaves a checkpoint behind when it was in scope
    if "S8" in selected:
        write_checkpoint(ctx)
    ctx.state["overall_status"] = overall_status(ctx)
    ctx.state["credits"] = credits_summary(ctx)
    ctx.save_state()

    if ctx.planned_commands:
        ctx.say("\n" + "=" * 78)
        ctx.say(f"PAID / NETWORK COMMANDS NOT EXECUTED ({len(ctx.planned_commands)})")
        ctx.say("=" * 78)
        for record in ctx.planned_commands:
            ctx.say(f"[{record['stage']}] {record['step']}  "
                    f"(planned_credits={record['planned_credits']})")
            ctx.say(f"  {record['paid_command']}")
            if record.get("note"):
                ctx.say(f"  note: {record['note']}")
        write_json(ctx.p.logs / f"{ctx.run_id}_planned_paid_commands.json", {
            "schema": "nalu.pipeline_planned_paid_commands.v1",
            "episode": ctx.episode, "recorded_at": now(),
            "paid_enabled": ctx.paid_enabled,
            "commands": ctx.planned_commands})

    print_status(ctx)
    return exit_code


def overall_status(ctx: Ctx) -> str:
    rows = [ctx.stage_state(sid).get("status") for sid in STAGE_IDS]
    if all(status in TERMINAL_OK for status in rows):
        return ("READY_FOR_CHECKPOINT" if ctx.state["approval"]["status"] != "APPROVED"
                else "APPROVED")
    if HARD_STOP in rows:
        return "STOPPED_BUDGET_HARD_STOP"
    if REVIEW_REQUIRED in rows:
        return "REVIEW_REQUIRED"
    if any(status == "AWAITING_APPROVAL" for status in rows):
        return "AWAITING_APPROVAL"
    for sid in STAGE_IDS:
        status = ctx.stage_state(sid).get("status")
        if status not in TERMINAL_OK:
            return f"STOPPED_AT_{sid}_{status}"
    return "UNKNOWN"


# --------------------------------------------------------------------------- #
# status / approve / loop
# --------------------------------------------------------------------------- #
def print_status(ctx: Ctx) -> None:
    state = ctx.state
    credits = state.get("credits") or credits_summary(ctx)
    print()
    print(f"===== {ctx.episode} status =====")
    print(f"overall            : {state.get('overall_status')}")
    print(f"approval           : {state['approval'].get('status')}"
          + (f" ({state['approval'].get('approved_at')})"
             if state["approval"].get("approved_at") else ""))
    print(f"paid steps enabled : {ctx.paid_enabled}  "
          f"(--paid={ctx.want_paid}, config={ctx.config_paid_enabled}, dry_run={ctx.dry})")
    print(f"credits cap        : {credits.get('cap')}   recorded={credits.get('recorded_total_credits')}"
          f"   planned_this_run={credits.get('planned_total')}")
    print(f"state file         : {ctx.p.state}")
    print(f"logs               : {ctx.p.logs}")
    print(f"checkpoint         : {ctx.p.checkpoint}"
          + ("" if ctx.p.checkpoint.is_file() else "  (not written yet)"))
    print()
    print(f"{'stage':6} {'status':34} {'cr':>5}  blockers")
    print("-" * 110)
    for sid in STAGE_IDS:
        row = ctx.stage_state(sid)
        blockers = ", ".join(row.get("blockers") or []) or "-"
        print(f"{sid:6} {str(row.get('status')):34} {row.get('planned_credits') or 0:>5}  "
              f"{blockers[:60]}")
    print()
    review = state.get("review_required")
    if review:
        print(f"MACHINE REVIEW REQUIRED at {review.get('stage')} "
              f"({review.get('sub_stage')}), reviewer {review.get('reviewer')}")
        for request in review.get("requests") or []:
            print(f"  request : {request}")
        print(f"  answer  : {VENV} {VLM_PROTOCOL} example-answers --request <request>")
        print(f"  submit  : {VENV} {VLM_PROTOCOL} submit --request <request> "
              "--answers <answers.json>")
        print(f"  resume  : {review.get('resume')}")
        print()
    rights = state.get("rights_basis") or {}
    if rights:
        print(f"rights basis      : {rights.get('basis')}")
        print(f"  declared by     : {rights.get('declared_by')} on {rights.get('declared_on')} "
              f"({rights.get('declaration_type')})")
        print(f"  authority       : {rights.get('authority')} seq={rights.get('order_seq')}")
        print(f"  NOT covered     : {rights.get('not_covered')}")
        print()
    decisions = state.get("open_decisions") or []
    blocking = [row for row in decisions if row.get("status") != "RESOLVED"]
    resolved = [row for row in decisions if row.get("status") == "RESOLVED"]
    if resolved:
        print(f"resolved decisions ({len(resolved)}): "
              + ", ".join(str(row.get("id")) for row in resolved))
    if blocking:
        print(f"open decisions ({len(blocking)}): "
              + ", ".join(str(row.get("id")) for row in blocking))
        print("  detail: see PIPELINE_RUNBOOK.md and the state file's open_decisions[]")
    print()


def cmd_status(args: argparse.Namespace) -> int:
    ctx = Ctx(args.episode, args)
    if args.json:
        print(json.dumps(ctx.state, ensure_ascii=False, indent=1))
        return 0
    print_status(ctx)
    return 0


def cmd_qa_status(args: argparse.Namespace) -> int:
    """One place to see every QA route's readiness and any outstanding review."""
    ctx = Ctx(args.episode, args)
    rows = []
    for label, tool in (("S3.qa identity", IDENTITY_QA_LOCK),
                        ("S5.q1 keyframe", KEYFRAME_Q1),
                        ("S5.sfe start-frame", START_FRAME_EVIDENCE),
                        ("S6.qa post-generation", POST_GEN_QA),
                        ("S6.q2 video assembly admission", VIDEO_Q2),
                        ("S7.qa final package", FINAL_QA_BUNDLE)):
        completed = subprocess.run(
            [str(VENV), str(tool), "status", "--episode", ctx.episode],
            cwd=str(ENGINE), env=ctx.child_env(paid=False), capture_output=True, text=True)
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            payload = {"error": (completed.stderr or "")[-400:]}
        rows.append({"sub_stage": label, "tool": str(tool), "status": payload})
    review = ctx.state.get("review_required")
    requests = sorted((REVIEWS_ROOT / ctx.episode).glob("*_request.json")) \
        if (REVIEWS_ROOT / ctx.episode).is_dir() else []
    submitted = sorted((REVIEWS_ROOT / ctx.episode).glob("*_submitted.json")) \
        if (REVIEWS_ROOT / ctx.episode).is_dir() else []
    payload = {
        "schema": "nalu.qa_route_status.v1",
        "episode": ctx.episode,
        "reviewer": REVIEWER_ID,
        "review_protocol": str(VLM_PROTOCOL),
        "review_kinds": ["identity", "keyframe", "start_frame", "post_gen_plot", "video_q2"],
        "rights_basis": ctx.rights_declaration,
        "reviews_dir": str(REVIEWS_ROOT / ctx.episode),
        "review_requests": [str(item) for item in requests],
        "submitted_reviews": [str(item) for item in submitted],
        "review_required": review,
        "routes": rows,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    ctx = Ctx(args.episode, args)
    p = ctx.p
    if ctx.authority_blockers or args.by != ctx.authority.get("line_owner_id"):
        print("refusing to approve: --by must exactly match the validated deployment "
              "line_owner_id and the private order inbox must be current", file=sys.stderr)
        return 2
    if not p.checkpoint.is_file():
        print(f"refusing to approve: no checkpoint at {p.checkpoint}. "
              f"Run `run --episode {ctx.episode}` through S8 first.", file=sys.stderr)
        return 2
    payload = {
        "schema": "nalu.pipeline_approval.v1",
        "episode": ctx.episode,
        "approved_at": now(),
        "approved_by": args.by,
        "note": args.note,
        "checkpoint": str(p.checkpoint),
        "checkpoint_sha256": sha256_file(p.checkpoint),
        "final_video": str(p.final_mp4) if p.final_mp4.is_file() else None,
        "final_video_sha256": sha256_file(p.final_mp4),
        "recorded_by": TOOL_ID,
    }
    write_json(p.approval, payload)
    ctx.state["approval"] = {"status": "APPROVED", "approved_at": payload["approved_at"],
                            "by": args.by, "note": args.note,
                            "flag_file": str(p.approval)}
    ctx.stage_state("S8")["status"] = PASS
    ctx.state["overall_status"] = overall_status(ctx)
    ctx.save_state()
    print(json.dumps({"status": "APPROVED", "episode": ctx.episode,
                      "flag_file": str(p.approval),
                      "next_episode_may_start": True}, ensure_ascii=False, indent=1))
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    episodes = episode_range(args.start, args.end)
    print(f"loop over {len(episodes)} episodes: {episodes[0]}..{episodes[-1]}  "
          f"--paid={args.paid}  poll={args.poll_seconds}s")
    for episode in episodes:
        sub = argparse.Namespace(
            episode=episode, dry_run=args.dry_run, paid=args.paid, force=False,
            from_stage=None, until=None)
        ctx = Ctx(episode, sub)
        code = run_episode(ctx)

        # THE CHECKPOINT IS NOT SKIPPABLE.  Even a failed episode gets one, and
        # the loop still blocks: a human has to look before the next episode
        # starts.  There is no --yes, no --auto-approve, no timeout that
        # self-approves.
        checkpoint = write_checkpoint(ctx)
        print(f"\n>>> CHECKPOINT {episode}: {checkpoint}", flush=True)
        print(f">>> run exit code {code}; overall {ctx.state.get('overall_status')}", flush=True)
        print(f">>> blocked until: {VENV} {RT_TOOLS / 'nalu_pipeline.py'} "
              f"approve --episode {episode} "
              f"--by {shlex.quote(str(ctx.authority.get('line_owner_id') or '<LINE_OWNER_ID>'))}")
        waited = 0
        while not ctx.p.approval.is_file():
            time.sleep(max(5, int(args.poll_seconds)))
            waited += max(5, int(args.poll_seconds))
            if waited % 600 == 0:
                print(f"    … still waiting for approval of {episode} ({waited // 60} min)", flush=True)
        approval = read_json(ctx.p.approval, {}) or {}
        print(f">>> {episode} APPROVED at {approval.get('approved_at')} "
              f"by {approval.get('approved_by')} — continuing")
        ctx.state["approval"] = {"status": "APPROVED",
                                 "approved_at": approval.get("approved_at"),
                                 "by": approval.get("approved_by"),
                                 "note": approval.get("note"),
                                 "flag_file": str(ctx.p.approval)}
        ctx.save_state()
    print("loop complete", flush=True)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return run_episode(Ctx(args.episode, args))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nalu_pipeline.py",
        description="Resumable per-episode orchestrator for the nalu (《夜无疆》) line. "
                    "9:16, seedance-2.0-pro 720p.  No platform upload, ever.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "money safety\n"
            "  A paid step runs only when --paid is given AND\n"
            f"  {CONFIG_PATH} generation.paid_requests_enabled is true.\n"
            "  Otherwise the engine tool's own precheck/dry mode runs and the exact paid\n"
            "  argv is printed.  Every paid step is preceded by\n"
            f"  {BUDGET_LEDGER} --check --episode <EP> --planned-credits <N>\n"
            "  and a non-zero exit stops the run.\n"))
    subs = parser.add_subparsers(dest="command", required=True)

    run = subs.add_parser("run", help="run one episode's stages")
    run.add_argument("--episode", required=True)
    run.add_argument("--dry-run", action="store_true",
                     help="execute every free stage for real; print paid S3-S6 commands only")
    run.add_argument("--paid", action="store_true",
                     help="permit paid steps (still requires paid_requests_enabled)")
    run.add_argument("--from", dest="from_stage", metavar="STAGE",
                     help=f"first stage to run, one of {STAGE_IDS}")
    run.add_argument("--until", metavar="STAGE", help="last stage to run")
    run.add_argument("--s3-subjects", default=None,
                     help="comma-separated subject ids: S3 submits only these rows this run (style sample)")
    for sub in (run,):
        sub.add_argument("--layers-dir", default=None, help="directory holding the four <EP>_*_v1 layer files (E59 v4 adapter output)")
        sub.add_argument("--narrative", default=None); sub.add_argument("--directing", default=None)
        sub.add_argument("--contract", default=None); sub.add_argument("--manifest", default=None)
    run.add_argument("--force", action="store_true",
                     help="re-run stages that already reached PASS")
    run.set_defaults(func=cmd_run)

    status = subs.add_parser("status", help="show one episode's state")
    status.add_argument("--episode", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status, dry_run=False, paid=False, force=False,
                        from_stage=None, until=None)

    qa = subs.add_parser("qa-status",
                         help="show every QA route's readiness and any outstanding review")
    qa.add_argument("--episode", required=True)
    qa.set_defaults(func=cmd_qa_status, dry_run=False, paid=False, force=False,
                    from_stage=None, until=None, json=False)

    approve = subs.add_parser(
        "approve", help="record the configured line owner's approval after the human checkpoint")
    approve.add_argument("--episode", required=True)
    approve.add_argument("--by", required=True)
    approve.add_argument("--note", default=None)
    approve.set_defaults(func=cmd_approve, dry_run=False, paid=False, force=False,
                         from_stage=None, until=None)

    loop = subs.add_parser("loop", help="run episodes in sequence, blocking at each checkpoint")
    loop.add_argument("--start", required=True)
    loop.add_argument("--end", required=True)
    loop.add_argument("--paid", action="store_true")
    loop.add_argument("--dry-run", action="store_true")
    loop.add_argument("--poll-seconds", type=int, default=60)
    loop.set_defaults(func=cmd_loop)
    return parser


def main(argv: list[str] | None = None) -> int:
    if os.geteuid() == 0:
        print("refusing to run as root", file=sys.stderr)
        return 2
    args = build_parser().parse_args(argv)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
