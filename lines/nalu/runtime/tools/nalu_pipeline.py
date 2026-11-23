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
  approve --episode E01 --by <configured-line-owner-id> [--note "..."]   (only with project.owner_review_required)
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
import nalu_tail_ad_opt_in as _tail_ad_optin
if str(_np.ENGINE_ROOT / "tools") not in _sys.path:
    _sys.path.insert(0, str(_np.ENGINE_ROOT / "tools"))
from image_model_policy import ACTIVE_IMAGE_MODEL, ACTIVE_IMAGE_RESOLUTION, known_image_models, known_image_resolutions  # noqa: E402  (Roger 2026-10-30 seq=54/56)
import stage_time_ledger as _time_ledger
import episode_previs as _previs  # plan §4: zero-credit previs, run before every paid stage
import unit_timing_map as _timing  # plan §6: beat/shot/request/returned/cut durations, recorded separately
import voice_over_narration as _vo  # V.O. narration: S4 synthesis, S7 placement/mix
import lang_profile as _lang  # zh/en/ja/ko dialogue-language profile (2026-11-18)

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
BUILD_MEASURED_EDIT_CONSTRAINTS = RT_TOOLS / "build_measured_edit_constraints.py"

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

# tail-ad slot (optional, per-episode; codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md)
ADS_ROOT = RUNTIME / "ads"
ADS_INBOX = ADS_ROOT / "inbox"
ADS_BRIEFS = ADS_ROOT / "briefs"
ADS_PACKAGED = ADS_ROOT / "packaged"
ADS_PROMPTS = ADS_ROOT / "prompts"
ADS_POLICY = ADS_ROOT / "policy.json"
# Repo-shipped defaults (line owner 2026-10-22: every episode ends with the tail ad): the policy used when
# the runtime has no ads/policy.json, and a second lookup folder for INBOX:<sku>.mp4 drops.
ADS_DEFAULT_POLICY = ENGINE / "configs/ads/AD_POLICY_DEFAULT.json"
ADS_REPO_ASSETS = ENGINE / "assets/ads"
ADS_TRANSACTIONS = ADS_ROOT / "transactions"
AD_SLOT_CONTRACT = ENGINE / "configs/AD_SLOT_CONTRACT_V1.json"
AD_TAIL_PACKAGE_TOOL = ENGINE / "tools/ad_tail_package.py"
AD_TAIL_INSERT_TOOL = ENGINE / "tools/ad_tail_insert.py"
#: Writer-capability inputs (arc plan, adaptation disposition, script review, Rule 8
#: response).  Line owner 2026-11-01.  The profile switch lives in the tool so S1, the
#: writer finalize path and any CLI all read ONE decision.
WRITER_CAPABILITY_TOOL = ENGINE / "tools/writer_capability.py"
ADFORGE_ADAPTER_TOOL = ENGINE / "tools/adforge_adapter.py"

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
#: A step that did not run is never reported as PASS (AGENTS.md §0: 没跑标 NOT_RUN).
#: Under LEGACY_EPISODE_COMPAT the canonical writer handoff has no verifier, so its
#: receipt says this instead of borrowing the PASS the current-portable profile earns.
NOT_RUN = "NOT_RUN"
WRITER_HANDOFF_LEGACY_STATUS = "NOT_RUN_LEGACY_PROFILE"
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
from nalu_qa_common import review_identity as _review_identity
REVIEWER_ID, REVIEW_METHOD = _review_identity(os.environ)
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


def _hopsapi():
    """tools/hopsapi_video_client.py (engine, no network at import)."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools import hopsapi_video_client  # noqa: PLC0415
    return hopsapi_video_client


def video_provider_info() -> dict[str, str]:
    """The H3 video transport (owner 2026-10-29): env NALU_VIDEO_PROVIDER > qingshan.json
    generation.video_provider > hopsapi when HOPSAPI_API_KEY is set, else giggle.  Resolved in this
    process (which holds the keys) and handed to every child as NALU_VIDEO_PROVIDER, so a free child
    whose keys were stripped plans the same transport the paid child will use."""
    return _hopsapi().resolve_video_provider(config_path=CONFIG_PATH)


def video_provider_for(model: str) -> str:
    """hopsapi only for MiniMax-H3 under video_provider=hopsapi; giggle otherwise."""
    return _hopsapi().provider_for_model(model, video_provider_info()["provider"])


def video_key_env(model: str) -> str:
    return _hopsapi().required_key_env(video_provider_for(model))


def _image_client():
    """tools/hopsapi_image_client.py (engine, no network at import)."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools import hopsapi_image_client  # noqa: PLC0415
    return hopsapi_image_client


def image_provider_info() -> dict[str, str]:
    """The image transport (owner 2026-10-30): env NALU_IMAGE_PROVIDER > qingshan.json
    generation.image_provider > hopsapi when HOPSAPI_API_KEY is set, else giggle.  Resolved here (the
    process holding the keys) and handed to every child as NALU_IMAGE_PROVIDER."""
    return _image_client().resolve_image_provider(config_path=CONFIG_PATH)


def image_batch_credits(ctx: "Ctx", images: int) -> int:
    """Planned credits for ``images`` image tasks: HopsAPI gpt-image-2 at the configurable per-image
    rate, batch rounded up (default 1.2); Giggle at the cost plan's image_credits_per_task (11)."""
    if image_provider_info()["provider"] == "hopsapi":
        return _image_client().estimated_batch_credits(images, config_path=CONFIG_PATH)
    cost_plan = getattr(ctx, "cost_plan", None) or {}
    per = int(((cost_plan.get("price_basis") or {}).get("image_credits_per_task")) or 11)
    return max(0, int(images or 0)) * per

TERMINAL_OK = {PASS, SKIPPED}
COMPACT_OUTPUT = os.environ.get("NALU_COMPACT_OUTPUT", "").strip() == "1"
COMPACT_LINE_RE = re.compile(r"^\s*(?:-- S\d|S\d => |!!)")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def paid_config_lock(*, is_current: bool, config_paid_enabled: bool, storyclaw_paid_enabled: bool,
                     paid_order: dict[str, Any] | None) -> bool:
    """Whether a paid child gets NALU_PAID_CONFIG_LOCK=1.  CURRENT_PORTABLE: unchanged
    (config + storyclaw locks).  LEGACY_EPISODE_COMPAT (ROGER-20260926-S4-PAID-LOCK-PROPAGATION):
    the StoryClaw audio provider also demands the lock, so it is set only when
    generation.paid_requests_enabled is true AND a validated paid order is bound; fail-closed otherwise."""
    if is_current:
        return bool(config_paid_enabled and storyclaw_paid_enabled)
    return bool(config_paid_enabled and paid_order)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _unit_count(grouping_plan: Path) -> int | None:
    """Video units in the plan, or None when it has not been built yet.

    The checkpoint text used to hardcode this number ("29-unit grouping plan"): a per-episode
    figure frozen into shared code.  Read it instead so the line owner is never handed a count
    that does not match the plan next to it.
    """
    row = read_json(grouping_plan, {}) or {}
    value = row.get("video_unit_count")
    return int(value) if isinstance(value, int) else None


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


# --------------------------------------------------------------------------- #
# Plan §4: zero-credit previs gate in front of every paid stage
# --------------------------------------------------------------------------- #
#: One previs run per stage attempt is enough; the result is keyed by the exact
#: contract+grouping bytes it read, so a resume after an edit recomputes and a
#: resume after nothing changed reuses.  Never cached across an edit.
PREVIS_GATE_STAGES = ("S5", "S6")


def _previs_policy() -> dict[str, Any]:
    return _previs.policy_settings()


def previs_gate(ctx: "Ctx", stage: str) -> dict[str, Any]:
    """Run the episode previs and decide whether the paid stage may start.

    Read-only and free: it reads the generation contract, the grouping plan and
    whatever keyframes/audio already exist.  It never calls a provider.

    Returns a row the stage records as evidence.  ``blocked`` is True only for a
    machine failure under machine_failure_mode=BLOCK; the director-review
    questions are advisory and never block (plan §4.3).
    """
    p = ctx.p
    policy = _previs_policy()
    row: dict[str, Any] = {
        "schema": "nalu.previs_gate.v1",
        "stage": stage,
        "episode": ctx.episode,
        "ran_at": now(),
        "policy": str(_previs.POLICY_PATH),
        "blocks_paid_stage": (_previs_policy().get("blocks") or {}).get(stage),
    }
    if not _previs.gate_active(ctx.episode, contract=read_json(p.contract, {}) or {}):
        row.update({"status": "NOT_ENABLED", "blocked": False,
                    "note": "episode not listed in the previs policy and the contract does not opt in"})
        return row
    if not p.contract.is_file():
        row.update({"status": "BLOCKED", "blocked": True,
                    "failures": [f"GENERATION_CONTRACT_MISSING:{p.contract}"]})
        return row
    contract = read_json(p.contract, {}) or {}
    grouping = read_json(p.grouping_plan, {}) or {}
    if not grouping.get("units"):
        # The grouping plan is S2 output.  Without it the shot-to-unit coverage
        # check (§4.2.3) cannot run, and a paid stage without it would be
        # exactly the "sampled before the plan was read" failure plan §2 warns
        # about.
        row.update({"status": "BLOCKED", "blocked": True,
                    "failures": [f"GROUPING_PLAN_MISSING_OR_EMPTY:{p.grouping_plan}"]})
        return row
    try:
        previs = _previs.build_previs(
            contract, grouping,
            keyframe_dir=p.keyframes if p.keyframes.is_dir() else None)
    except Exception as exc:  # noqa: BLE001 — a gate crash must not read as PASS
        row.update({"status": "BLOCKED", "blocked": True,
                    "failures": [f"PREVIS_FAILED:{type(exc).__name__}:{exc}"]})
        return row
    round_number = 1 + int((ctx.state.get("previs_review_rounds") or {}).get(stage) or 0)
    max_rounds = int(policy.get("max_director_review_rounds") or _previs.MAX_REVIEW_ROUNDS)
    # The round budget counts ACCEPTED reviews, not stage invocations.  Keeping the
    # call counter here let three bare runs report "2 rounds done" with no reviewer
    # and no answers (CC_H3 audit 2026-10-26 §四-C); the counter is still advanced so
    # a re-run is visible, but it no longer decides the review status.  A review only
    # counts when it is bound to THIS sequence_digest (§四-缺口D): edit a shot's camera
    # or a boundary's transition and the previous round's receipt stops counting,
    # because it describes a sequence that no longer exists.
    sequence_digest = previs.get("sequence_digest")
    submitted_reviews = _previs.submitted_review_count(
        p.preprod_reports, ctx.episode, stage, sequence_digest)
    review = _previs.director_review_request(
        previs, round_number=max(1, min(round_number, max_rounds + 1)),
        submitted_reviews=submitted_reviews)
    ctx.state.setdefault("previs_review_rounds", {})[stage] = round_number
    machine_mode = "BLOCK" if policy.get("gate_on_machine_failures", True) else "ADVISORY"
    failures = previs.get("machine_failures") or []
    out_path = p.preprod_reports / f"{ctx.episode}_PREVIS_{stage}.json"
    previs["gate"] = {"stage": stage, "policy": str(_previs.POLICY_PATH),
                      "machine_failure_mode": machine_mode,
                      "request": "tools/episode_previs.py"}
    previs["director_review"] = review
    # Optional watchable render (CC_H3 audit 2026-10-26 §四-缺口B).  Machine
    # checks can agree while the sequence is unwatchable, and only a rendered
    # clip plus real dialogue shows whether a viewer follows the speaker and
    # the cut.  Off by default: it shells out to ffmpeg for the whole timeline,
    # so a gate that runs on every stage attempt must not pay that cost unless
    # the operator asked for a reviewable cut.  When enabled, a shot that has
    # declared dialogue but no supplied clip is reported, never faked as silence.
    render_target = os.environ.get("NALU_PREVIS_RENDER", "").strip()
    if render_target and os.environ.get("NALU_PREVIS_RENDER_ENABLED", "").strip() == "1":
        audio_map_path = os.environ.get("NALU_PREVIS_DIALOGUE_AUDIO", "").strip()
        try:
            dialogue_audio = (read_json(Path(audio_map_path), {}) or {}) if audio_map_path else None
            previs["render"] = _previs.render_previs(
                previs, Path(render_target),
                renderer=Path(_previs.__file__).with_name("render_portable_timeline.py"),
                dialogue_audio=dialogue_audio)
        except Exception as exc:  # noqa: BLE001 — a failed render must not read as a pass
            previs["render"] = {"status": "RENDER_FAILED", "error": f"{type(exc).__name__}:{exc}"}
    write_json(out_path, previs)
    blocked = bool(failures) and machine_mode == "BLOCK"
    row.update({
        "status": ("BLOCKED" if blocked else "PASS"),
        "blocked": blocked,
        "receipt": str(out_path),
        "receipt_sha256": sha256_file(out_path),
        "sequence_digest": sequence_digest,
        "review_receipt_path": str(_previs.review_receipt_path(p.preprod_reports, ctx.episode, stage)),
        "shot_count": previs.get("shot_count"),
        "total_seconds": previs.get("total_seconds"),
        "estimated_dialogue_lines": previs.get("estimated_dialogue_lines"),
        "measured_dialogue_lines": previs.get("measured_dialogue_lines"),
        "machine_failures": failures,
        "machine_failure_mode": machine_mode,
        "advisories": previs.get("advisories") or [],
        "director_review": {"status": review.get("status"), "round": review.get("round"),
                            "blocking": False, "max_rounds": max_rounds,
                            "submitted_reviews": review.get("submitted_reviews", submitted_reviews)},
        "note": ("a previs PASS means the plan is internally consistent enough to go on to "
                 "production; it is not a cut and not evidence that an action, an identity "
                 "or a lip sync works.  The director review is only complete when submitted "
                 "review receipts exist — re-running this stage does not advance it."),
    })
    if "render" in previs:
        row["render"] = {
            key: previs["render"].get(key)
            for key in ("status", "output", "shots_dialogue_audio_missing",
                        "camera_moves_animated", "error")
            if key in previs["render"]
        }
    return row


def timing_map(ctx: "Ctx", *, stage: str, media_dir: Path | None = None,
               edit_decisions: Path | dict[str, Any] | None = None) -> dict[str, Any]:
    """Plan §6: record the five durations separately, each with its source.

    story / dialogue / request / returned / cut.  One request is not assumed to
    be one final shot, and a line generated by two units is a failure rather
    than a silent double.  Read-only: it never edits a contract, never pads or
    trims, and never changes how units are scheduled.

    Recorded as evidence at each point the numbers actually change: after S2
    (request durations are known), after S6 (returned media is measurable) and
    after S7 (cut intervals exist).

    P1.4: ``edit_decisions`` can now be an AgentCut project object (dict with
    videoTracks/audioTracks) or a Path to one, for S7 compatibility.
    """
    p = ctx.p
    row: dict[str, Any] = {"schema": "nalu.timing_map_evidence.v1", "stage": stage,
                           "episode": ctx.episode, "ran_at": now()}
    contract = read_json(p.contract, {}) or {}
    grouping = read_json(p.grouping_plan, {}) or {}
    if not contract or not grouping.get("units"):
        row.update({"status": "SKIPPED_INPUTS_MISSING",
                    "detail": f"contract={p.contract.is_file()} grouping={bool(grouping.get('units'))}"})
        return row
    try:
        result = _timing.build_timing_map(
            contract, grouping,
            transaction_manifest=read_json(p.video_transaction, None),
            media_dir=media_dir,
            edit_decisions=(edit_decisions if isinstance(edit_decisions, dict)
                           else (read_json(edit_decisions, None) if edit_decisions else None)),
        )
    except Exception as exc:  # noqa: BLE001 — evidence must never crash a stage
        row.update({"status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"})
        return row
    out_path = p.preprod_reports / f"{ctx.episode}_UNIT_TIMING_MAP_{stage}.json"
    write_json(out_path, result)
    row.update({
        "status": result.get("status"),
        "receipt": str(out_path),
        "receipt_sha256": sha256_file(out_path),
        "unit_count": result.get("unit_count"),
        "tail_dependent_units": result.get("tail_dependent_units"),
        "independent_units": result.get("independent_units"),
        # §6: a failure here is a contract conflict.  It is recorded, and the
        # stage decides — S2 blocking would strand a free stage on a timing
        # note, so the paid-stage previs gate is where a conflict stops money.
        "failures": result.get("failures") or [],
        "notes": result.get("notes") or [],
    })
    return row


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


def writer_handoff_gate_status(ok: bool, verdict: dict[str, Any]) -> str:
    """The gate row for the canonical writer handoff, honestly labelled.

    ``PASS`` only when a verifier actually answered PASS.  A profile with no
    verifier reports ``NOT_RUN_LEGACY_PROFILE`` instead of a PASS it never earned
    (line owner 2026-11-01).  It is an accepted step — ``ok`` is True — because
    E01-E13 were sealed under that profile and the stage outcome must not change.
    """
    if not ok:
        return "FAIL"
    status = str((verdict or {}).get("status") or "")
    if status == PASS:
        return PASS
    return status or NOT_RUN


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
        # Roger 2026-10-30 (E12 成片审看 item 0): a cut that has not passed every S7 gate is never a
        # deliverable.  S7 levels, measures, detects and QA-checks the CANDIDATE here; only a full
        # S7 PASS promotes it (byte-copy, sha-verified) to deliverables/<EP>/<EP>_final_9x16.mp4.
        self.final_levelled = self.assembly / f"{prefix}final_levelled_9x16.mp4"      # leveller output (immutable)
        self.final_candidate = self.assembly / f"{prefix}final_candidate_9x16.mp4"     # after the post-level audio chain
        self.ad_tail_candidate = self.assembly / f"{prefix}final_candidate_9x16_AD.mp4"
        self.readback_asr = self.assembly / f"{prefix}FINAL_CUT_READBACK_ASR.json"

        # deliverables
        self.deliver = DELIVERABLES / episode
        self.final_mp4 = self.deliver / f"{episode}_final_9x16.mp4"
        self.qa_report = self.deliver / f"{episode}_QA_REPORT.json"
        self.checkpoint = self.deliver / "CHECKPOINT.md"

        # tail-ad slot (optional, per-episode)
        self.ad_prompt = ADS_PROMPTS / f"{episode}_AD_PROMPT.json"
        self.ad_answer = ADS_PROMPTS / f"{episode}_AD_ANSWER.json"
        self.ad_tail_video = self.deliver / f"{episode}_final_9x16_AD.mp4"
        self.ad_tail_qa_report = self.assembly / f"{episode}_AD_TAIL_QA.json"

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


def sealed_handoff_layers(episode: str, scope_id: str | None) -> dict[str, Path] | None:
    """The four layer paths bound by a SEALED writer handoff in the private runtime, or None."""
    if not scope_id:
        return None
    path = RUNTIME / "writer_layers" / str(scope_id) / episode / "ACTIVE_WRITER_HANDOFF.json"
    doc = read_json(path, {}) or {}
    if not isinstance(doc, dict) or doc.get("status") != "SEALED" or str(doc.get("episode") or "") != episode:
        return None
    out: dict[str, Path] = {}
    for key in ("narrative_canonical", "directing_script", "generation_contract", "writer_manifest"):
        row = (doc.get("layers") or {}).get(key)
        value = row.get("path") if isinstance(row, dict) else row
        if not value:
            return None
        candidate = Path(str(value)).expanduser()
        if not candidate.is_file():
            return None
        out[key] = candidate.resolve()
    return out


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
        scope_config = _scope.load_config()
        # A dedicated runtime may use its own runtime/ paths. They are not
        # another series' authorities merely because the relative names match.
        dedicated_runtime = (
            scope_config.get("dedicated_runtime") is True
            and scope_config.get("default_scope") == scope["scope_id"]
            and set((scope_config.get("scopes") or {})) == {scope["scope_id"]}
            and set((scope_config.get("episodes") or {}).values()) == {scope["scope_id"]}
            and project_id == scope["series_id"]
        )
        for key in scoped_authorities:
            value = Path(scope[key]).resolve()
            path_authority[key] = str(value)
            if not within(value, series_root):
                failures.append(f"SCOPE_PATH_OUTSIDE_SERIES_ROOT:{key}:{value}")
            default_rel = _scope.DEFAULT_PATHS.get(key)
            if isinstance(default_rel, str) and not default_rel.startswith("tools:"):
                default_path = (RUNTIME / default_rel).resolve()
                if value == default_path and not dedicated_runtime:
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


#: spoken-dialogue languages the production path supports ("zh" is the historical default); ja / ko since
#: 2026-11-18 (lang_profile.py holds every per-language value; tools/tests pins the two tuples equal)
DIALOGUE_LANGUAGES = ("zh", "en", "ja", "ko")
DIALOGUE_LANGUAGE_LOCALES = {"zh": "zh-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR"}


def _dialogue_language_code(value: Any) -> str | None:
    """"zh" / "zh-CN" / "zh-Hans" -> "zh"; "en-US" -> "en"; "ja-JP" -> "ja"; "ko-KR" -> "ko"; else None.
    Before 2026-11-18 only zh / en were known, so a ja / ko declaration was silently produced as Chinese."""
    text = str(value or "").strip().lower().replace("_", "-")
    for code in DIALOGUE_LANGUAGES:
        if text == code or text.startswith(code + "-"):
            return code
    return None


def resolve_dialogue_language(contract: Any, config: Any) -> str:
    """One source for the episode's spoken-dialogue language:
    generation contract ``dialogue_language`` -> runtime config ``project.language`` -> "zh"."""
    from_contract = _dialogue_language_code((contract or {}).get("dialogue_language")
                                            if isinstance(contract, dict) else None)
    if from_contract:
        return from_contract
    project = (config or {}).get("project") if isinstance(config, dict) else None
    from_config = _dialogue_language_code((project or {}).get("language")
                                          if isinstance(project, dict) else None)
    return from_config or "zh"


def _whisper_model_name(language: Any) -> str:
    """"small" (the historical model) for zh / en / ko; ja prefers a locally installed "medium"."""
    try:
        from portable_runtime import language_whisper_model_name  # engine tools/ is on sys.path
    except ImportError:  # pragma: no cover - a stripped deployment keeps the historical model
        return "small"
    return language_whisper_model_name(language)


def ctx_language(ctx: Any) -> str:
    """The run's resolved dialogue language (Ctx.language); stage test doubles without it
    are the historical Chinese line."""
    return getattr(ctx, "language", None) or "zh"


def resolve_render_style(contract: Any, config: Any, episode: str | None = None) -> str:
    """The series' render style ("live_action" | "anime", render_style.py): generation contract
    ``visual_culture_contract.render_style`` -> production brief ``render_style`` -> runtime config
    ``project.render_style`` -> "live_action"."""
    import render_style as _rs
    style = _rs.from_contract(contract)
    if style:
        return style
    brief = read_json(_rs.brief_path(RUNTIME, episode), None) if episode else None
    return _rs.resolve(None, brief, config)


def ctx_render_style(ctx: Any) -> str:
    """The run's resolved render style (Ctx.render_style); stage test doubles without it are live-action."""
    return getattr(ctx, "render_style", None) or "live_action"


def ctx_language_locale(ctx: Any) -> str:
    return DIALOGUE_LANGUAGE_LOCALES[ctx_language(ctx)]


def subtitles_ass_path(ctx: Any) -> Path:
    """Burn-in subtitle path; zh keeps the historical ``_subtitles_zh.ass`` name."""
    return ctx.p.assembly / f"{ctx.episode}_subtitles_{ctx_language(ctx)}.ass"


class Ctx:
    def __init__(self, episode: str, args: argparse.Namespace) -> None:
        self.episode = episode
        self.args = args
        self.p = Paths(episode)
        layers = explicit_layers_from_args(episode, args)
        layers_source = "CLI" if layers else None
        if not layers:
            # 2026-09-22 (device-2 finding #17): a sealed ACTIVE_WRITER_HANDOFF written by
            # storyclaw_writer_workflow.py finalize is the writer's authority for the four
            # layers and outranks paths remembered in the state file from an earlier run;
            # otherwise every new writer version needed a hand edit of pipeline_state.
            layers = sealed_handoff_layers(episode, self.p.scope.get("scope_id"))
            layers_source = "WRITER_HANDOFF" if layers else None
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
        # Provider-side concurrency ceiling, separate from the POST thread pool above.  Unset by
        # default: the scheduler then applies no remote-in-flight bound at all, exactly as before
        # 2026-10-13.  A deployment that knows its account's generator slots sets it.
        self.max_remote_inflight = int(gen["max_remote_inflight"]) if gen.get("max_remote_inflight") else None
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
        self._language: str | None = None
        self._render_style: str | None = None

    @property
    def render_style(self) -> str:
        """The series' render style ("live_action" | "anime"), resolved once per run by resolve_render_style.
        Not cached until the generation contract exists (S1 writes it)."""
        if self._render_style is None:
            contract = read_json(self.p.contract, None) if self.p.contract.is_file() else None
            style = resolve_render_style(contract, self.config, self.episode)
            if contract is None:
                return style
            self._render_style = style
        return self._render_style

    @property
    def language(self) -> str:
        """The episode's dialogue language ("zh" | "en" | "ja" | "ko"), resolved once per run by
        resolve_dialogue_language.  Not cached until the generation contract exists (S1 writes it)."""
        if self._language is None:
            contract = read_json(self.p.contract, None) if self.p.contract.is_file() else None
            language = resolve_dialogue_language(contract, self.config)
            if contract is None:
                return language
            self._language = language
        return self._language

    # ---------------------------------------------------------------- logging
    def log(self, line: str) -> None:
        stamped = f"[{now()}] {line}"
        # NALU_COMPACT_OUTPUT=1 (set for the Codex executor, 2026-11-16): the run log keeps every line; the terminal
        # gets only stage starts/results, so a model reading the output does not re-send pages of step lines.
        if not COMPACT_OUTPUT or COMPACT_LINE_RE.match(line):
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
        # Propagate the selected portable roots to every child.  A pipeline
        # launched with an explicit E59 runtime must not let a helper fall back
        # to the engine checkout's historical runtime (which would bind
        # NALU-YEWUJIANG assets into the QINGSHAN-E59 review request).
        env["NALU_ENGINE_ROOT"] = str(ENGINE)
        env["NALU_RUNTIME_ROOT"] = str(RUNTIME)
        env["NALU_WORK_ROOT"] = str(NALU_WORK)
        env["NALU_SERIES_SCOPES"] = str(RUNTIME / "runtime" / "series_scopes.json")
        env["NALU_SERIES_SCOPE_ID"] = str(self.p.scope["scope_id"])
        env["NALU_POLICY_PROFILE"] = "CURRENT_PORTABLE"
        env["QINGSHAN_VOICE_REGISTRY"] = str(self.p.scope["voice_registry"])
        env["QINGSHAN_ENTITY_REGISTRY"] = str(self.p.scope["entity_registry"])
        env["QINGSHAN_AGENTCUT_VOICE_POLICY"] = str(self.p.scope["agentcut_voice_policy"])
        # Collective learning (opt-in): only an episode whose S1 preflight locked a knowledge
        # snapshot exports it; every other episode's children see no QINGSHAN_KNOWLEDGE_* at all.
        collective = ((getattr(self, "state", None) or {}).get("line_upgrade_preflight") or {}).get("collective") or {}
        if collective.get("status") == "LOCKED":
            env.update({k: str(v) for k, v in (collective.get("child_env") or {}).items()
                        if k.startswith(("QINGSHAN_KNOWLEDGE_", "QINGSHAN_COLLECTIVE_", "QINGSHAN_ENGINE_API"))})
        if not _policy.uses_legacy_first_episode_exception(self.episode):
            # engine patch e16 (seq=7 PACING_E02_PLUS): grouped video units prefer 4-6 s, never above 7 s
            policy = self.p.scope.get("unit_duration_policy") or {}
            preferred = policy.get("preferred_seconds") or "4,6"
            env["QINGSHAN_UNIT_PREFERRED_SECONDS"] = ",".join(map(str, preferred)) if isinstance(preferred, (list, tuple)) else str(preferred)
            env["QINGSHAN_UNIT_MAX_SECONDS"] = str(policy.get("max_seconds") or 8)
            env["QINGSHAN_UNIT_MIN_SECONDS"] = str(policy.get("min_seconds") or 4)
        if self.p.scope["character_registry"].is_file():
            env["QINGSHAN_CHARACTER_REGISTRY"] = str(self.p.scope["character_registry"])
        try:
            env["NALU_VIDEO_PROVIDER"] = video_provider_info()["provider"]
        except ValueError:
            pass  # an invalid explicit value stays as given; the submitter refuses it
        try:
            env["NALU_IMAGE_PROVIDER"] = image_provider_info()["provider"]
        except ValueError:
            pass  # an invalid explicit value stays as given; the submitter refuses it
        if paid:
            # giggle_api_client.py:117-130 refuses every /api/v1/generation/ POST
            # unless a durable-submitter context is declared.  Set only for a
            # genuinely paid step, never for a precheck.
            env["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
        else:
            env.pop("GIGGLE_API_KEY", None)
            env.pop("HOPSAPI_API_KEY", None)
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
            self.log("  env " + " ".join(
                f"{key}=***" if SECRET_ENV_NAME.search(str(key)) else f"{key}={value}"
                for key, value in sorted(extra_env.items())))
        started = now()
        t0 = time.monotonic()
        try:
            completed = subprocess.run(
                argv, cwd=str(cwd), env=self.child_env(paid=paid, extra=extra_env),
                capture_output=True, text=True, timeout=timeout)
            rc, out, err = completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            rc, out, err = 124, exc.stdout or "", f"TIMEOUT after {timeout}s"
        except OSError as exc:
            rc, out, err = 127, "", f"{type(exc).__name__}: {exc}"
        # a child may echo a key (debug print, traceback with a header): never keep it
        secret_env = {**os.environ, **{str(k): str(v) for k, v in (extra_env or {}).items()}}
        out, err = redact_secrets(out, secret_env), redact_secrets(err, secret_env)
        log_path.write_text(
            f"# {started}\n# cwd={cwd}\n# paid={paid}\n# argv={q(argv)}\n"
            f"# exit={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n", encoding="utf-8")
        step = {
            "name": name, "argv": argv, "argv_shell": q(argv), "cwd": str(cwd),
            "extra_env": dict(extra_env or {}),
            "paid": paid, "exit_code": rc, "log": str(log_path),
            "started_at": started, "finished_at": now(),
            "duration_s": round(time.monotonic() - t0, 3),
            "stdout_tail": tail(out), "stderr_tail": tail(err),
        }
        # per-step wall time (S6 chain-step profiling, 2026-11-19): grep `dur=` in the pipeline log
        self.log(f"  -> exit={rc} log={log_path.name} dur={step['duration_s']:.1f}s")
        if check and rc != 0:
            step["fatal"] = True
        return step

    # ---------------------------------------------------------------- budget
    def reconcile_hopsapi_lost(self, *, label: str) -> dict[str, Any] | None:
        """Settle lost HopsAPI create responses against the billing usage API before a budget check.

        Lab E11 S6 (2026-10-31): four create POSTs timed out, the submitter recorded the two that
        reached the intent as RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION, and every re-entry's budget
        check refused (correct: no idempotency key) with no way out.  tools/hopsapi_usage.py lists
        the billed media rows of the window (GET only): one lost POST + one unattributed row -> adopted and
        polled; anything else (nothing billed, or rows that cannot be paired) -> written off at the reserved
        price with ONE new attempt (ruling A / K073; kill switch NALU_LOST_RESPONSE_AUTO_RECONCILE=0).  In-process (the key never reaches a child argv/env record),
        only on a real paid run with HOPSAPI_API_KEY set, at most once a minute; a failed usage read
        changes nothing, so the ledger keeps failing closed."""
        if getattr(self, "dry", True) or not getattr(self, "paid_enabled", False) \
                or not os.environ.get("HOPSAPI_API_KEY", "").strip():
            return None
        last = getattr(self, "_hopsapi_reconciled_at", 0.0)
        if time.time() - last < 60:
            return None
        if str(ENGINE / "tools") not in sys.path:
            sys.path.insert(0, str(ENGINE / "tools"))
        import hopsapi_usage  # noqa: PLC0415 - engine tool, GET-only
        tasks_root = ENGINE / "workflow" / "tasks"
        if not hopsapi_usage.pending_lost(self.episode, tasks_root):
            return None
        self._hopsapi_reconciled_at = time.time()
        report = hopsapi_usage.reconcile_episode(self.episode, tasks_root=tasks_root, auto=True)
        out = self.p.logs / f"{self.run_id}_hopsapi_usage_reconcile_{label}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary = {kind: row.get("status") for kind, row in (report.get("kinds") or {}).items()}
        self.say(f"   HopsAPI usage reconciliation of lost creates: {summary} ({out.name})")
        return report

    def lost_response_wait(self, budget: dict[str, Any], *, label: str) -> dict[str, Any] | None:
        """Was this budget refusal ONLY lost HopsAPI creates the engine settles by itself (ruling A)?

        Fleet devices 1485 E03 S6 and 1101 E20 S5 (2026-11-21): a 502 during a paid create left the
        transaction RESPONSE_LOST; the next budget check refused (correct) while the grace period ran, the
        stage stopped as HARD_STOP_BUDGET and the line waited for a human to paste ruling A.  When the refusal
        is nothing but such transactions (tools/hopsapi_usage.lost_response_wait reads the ledger's own report),
        the run records it on ``self`` and the stage loop turns the stop into a remote wait
        (HOPSAPI_LOST_RESPONSE_RECONCILING): the system tick re-runs the stage, whose preflight reconciles once
        the grace period passed.  Anything else -- the cap, other unresolved spend, the kill switch -- stays a
        hard stop.  Offline; never fatal."""
        self._lost_response_wait = None  # the LAST refusal of the stage decides
        try:
            report = json.loads((self.p.logs / f"{self.run_id}_budget_{label}.json").read_text(encoding="utf-8"))
            if str(ENGINE / "tools") not in sys.path:
                sys.path.insert(0, str(ENGINE / "tools"))
            import hopsapi_usage  # noqa: PLC0415 - engine tool, offline here
            stores = report.get("durable_transaction_stores") or {}
            wait = hopsapi_usage.lost_response_wait(
                self.episode, failures=report.get("failures") or [],
                unresolved=stores.get("unresolved_transactions") or [],
                tasks_root=ENGINE / "workflow" / "tasks")
        except Exception as exc:  # noqa: BLE001 - the hard stop stands
            self.say(f"   lost-response wait check skipped: {type(exc).__name__}: {str(exc)[:200]}")
            return None
        if wait:
            self._lost_response_wait = wait
            self.say(f"   budget refusal is only lost HopsAPI creates ({wait['lost']}, {wait['phase']}, eligible "
                     f"{wait['eligible_at']}): remote wait, the tick re-runs this stage and the engine reconciles "
                     "them (ruling A) -- no human needed")
        return wait

    def settle_unbound_audio(self, *, label: str) -> list[dict[str, Any]] | None:
        """Write off this episode's speech requests that never bound a task id, before a budget check.

        Fleet device 0899 E18 S4 (2026-11-17): a voice-over POST was interrupted, its transaction stayed
        INTENT_RECORDED with no task id, and every re-entry's budget check refused with
        AUDIO_UNRESOLVED_TRANSACTIONS -- no supported way out.  tools/storyclaw_audio_provider
        .settle_unbound_speech archives such a request once it is provably over (lock free, grace
        passed), the ledger counts its unit price as spent, and the line gets one new attempt
        (line-owner standing ruling A).  Only on a real paid run; never calls the provider."""
        if getattr(self, "dry", True) or not getattr(self, "paid_enabled", False) \
                or not AUDIO_TRANSACTION_ROOT.is_dir():
            return None
        paths = [path for path in AUDIO_TRANSACTION_ROOT.rglob("*.json")
                 if self.episode in path.relative_to(AUDIO_TRANSACTION_ROOT).parts]
        if not paths:
            return None
        if str(ENGINE / "tools") not in sys.path:
            sys.path.insert(0, str(ENGINE / "tools"))
        import storyclaw_audio_provider  # noqa: PLC0415 - engine tool, no provider call here
        rows = storyclaw_audio_provider.settle_unbound_speech(paths)
        if not rows:
            return None
        out = self.p.logs / f"{self.run_id}_audio_unbound_settle_{label}.json"
        out.write_text(json.dumps({"episode": self.episode, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        self.say(f"   unbound speech requests: {[row.get('status') for row in rows]} ({out.name})")
        return rows

    def settle_unbound_bgm(self, *, label: str) -> list[dict[str, Any]] | None:
        """The same write-off for this episode's selective-BGM music requests.

        Fleet devices 0891 E15 and 1144 E13 (2026-11-18): one music POST each came back without a
        task id (RESPONSE_LOST); the budget check refused every re-entry with
        BGM_UNRESOLVED_TRANSACTIONS and nothing could release it.  Only on a real paid run; never
        calls the provider."""
        if getattr(self, "dry", True) or not getattr(self, "paid_enabled", False):
            return None
        tx_dir = selective_bgm_transaction_dir(self)
        paths = sorted(tx_dir.glob("*.json")) if tx_dir.is_dir() else []
        if not paths:
            return None
        if str(ENGINE / "tools") not in sys.path:
            sys.path.insert(0, str(ENGINE / "tools"))
        import storyclaw_audio_provider  # noqa: PLC0415 - engine tool, no provider call here
        rows = storyclaw_audio_provider.settle_unbound_speech(
            paths, capability=storyclaw_audio_provider.BGM_CAPABILITY)
        if not rows:
            return None
        out = self.p.logs / f"{self.run_id}_bgm_unbound_settle_{label}.json"
        out.write_text(json.dumps({"episode": self.episode, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        self.say(f"   unbound music requests: {[row.get('status') for row in rows]} ({out.name})")
        return rows

    def budget_check(self, planned_credits: int, *, label: str,
                     reserve: bool = False) -> dict[str, Any]:
        """MANDATORY before every paid step.  Non-zero exit == HARD_STOP.

        ``reserve=True`` makes the ledger take an atomic reservation when the check
        passes (K111): two racing processes cannot both admit the same headroom.
        Lost HopsAPI creates are first reconciled against the billing usage API
        (``reconcile_hopsapi_lost``) so the ledger sees VERIFIED_ZERO / adopted states.
        """
        try:
            self.reconcile_hopsapi_lost(label=label)
        except Exception as exc:  # noqa: BLE001 - never fatal: the ledger still fails closed
            self.say(f"   HopsAPI usage reconciliation skipped: {type(exc).__name__}: {str(exc)[:200]}")
        try:
            self.settle_unbound_audio(label=label)
        except Exception as exc:  # noqa: BLE001 - never fatal: the ledger still fails closed
            self.say(f"   unbound speech settlement skipped: {type(exc).__name__}: {str(exc)[:200]}")
        try:
            self.settle_unbound_bgm(label=label)
        except Exception as exc:  # noqa: BLE001 - never fatal: the ledger still fails closed
            self.say(f"   unbound music settlement skipped: {type(exc).__name__}: {str(exc)[:200]}")
        bgm_transactions = selective_bgm_transaction_dir(self)
        argv = [VENV, BUDGET_LEDGER, "--check", "--episode", self.episode,
                "--planned-credits", int(planned_credits),
                "--bgm-transactions-dir", bgm_transactions,
                "--cap", self.cap, "--out",
                self.p.logs / f"{self.run_id}_budget_{label}.json"]
        if reserve:
            argv.append("--reserve")
        # The reservation's owner is this orchestrator: once it has exited, the ledger may treat
        # a reservation it left behind (non-zero step exit) as settled by the durable stores.
        step = self.run(argv, name=f"budget_check_{label}", paid=False,
                        extra_env={"NALU_BUDGET_RESERVATION_OWNER_PID": str(os.getpid())})
        verdict = {}
        for line in (step.get("stdout_tail") or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                verdict = json.loads(line)
        step["budget_verdict"] = verdict
        return step

    def budget_release(self, reservation_id: str, *, label: str) -> dict[str, Any]:
        """Append a release row once the spend is bound or proven not charged."""
        return self.run(
            [VENV, BUDGET_LEDGER, "--episode", self.episode,
             "--release-reservation", reservation_id],
            name=f"budget_release_{label}", paid=False,
        )

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
                  extra_env: dict[str, str] | None = None,
                  timeout: int | None = 3600) -> tuple[str, dict[str, Any]]:
        """Run a paid step, or its precheck twin plus a printed plan.

        Returns (status, step).  status is PASS / DRY / HARD_STOP / BLOCKED.
        ``timeout`` bounds the paid subprocess (the S6 video submitter passes video_submit_timeout_s()).
        """
        argv = [str(item) for item in argv]
        paid_env = dict(extra_env or {})
        if paid_config_lock(is_current=_policy.is_current(),
                            config_paid_enabled=getattr(self, "config_paid_enabled", False),
                            storyclaw_paid_enabled=getattr(self, "storyclaw_paid_enabled", False),
                            paid_order=getattr(self, "paid_order", None)):
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

        budget = self.budget_check(planned_credits, label=name,
                                   reserve=self.paid_enabled and not self.dry)
        verdict = budget.get("budget_verdict") or {}
        if budget["exit_code"] != 0:
            self.say(f"!! HARD_STOP budget guard refused {name}: "
                     f"{json.dumps(verdict, ensure_ascii=False)}")
            wait = self.lost_response_wait(budget, label=name)
            if wait:
                budget["lost_response_wait"] = wait
            return HARD_STOP, budget
        reservation_id = (verdict.get("reservation_result") or {}).get("reservation_id")
        self.say(f"   budget ok: planned={planned_credits} "
                 f"projected={verdict.get('projected_total_credits')} "
                 f"cap={verdict.get('cap_credits')}"
                 + (f" reserved={reservation_id}" if reservation_id else ""))

        if not self.paid_enabled:
            reason = (getattr(self, "paid_disabled_reason", None) or (
                      "--dry-run" if self.dry else
                      "--paid not given" if not self.want_paid else
                      "qingshan.json generation.paid_requests_enabled=false"))
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

        step = self.run(argv, name=name, paid=True, extra_env=paid_env, timeout=timeout)
        step["planned_credits"] = planned_credits
        step["budget"] = budget
        # A reservation is released only once the spend is bound (submitter exited 0)
        # or the step is proven not to have charged.  A non-zero exit keeps it: the
        # money may be in flight, and a timeout must never be read as "not charged".
        if reservation_id:
            step["budget_reservation"] = reservation_id
            if step["exit_code"] == 0:
                step["budget_release"] = self.budget_release(reservation_id, label=name)
            else:
                step["budget_reservation_held"] = (
                    "KEEP_UNTIL_LEDGER_RECONCILIATION: exit is non-zero; the charge may be in "
                    "flight, so the reservation is not released on a timeout")
        return (PASS if step["exit_code"] == 0 else BLOCKED), step


# --------------------------------------------------------------------------- #
# D-11 — paid authorisation, immediately before every paid submit
# --------------------------------------------------------------------------- #
def materialised_path(target: Path, suffix: str = "_PAID_AUTHORIZED") -> Path:
    """Where materialize_paid_authorization.py writes its copy (its target_path)."""
    target = Path(target)
    return target.parent / f"{target.stem}{suffix}{target.suffix}"


def paid_authorization_argv(ctx: Ctx, *, sid: str, target: Path, is_plan: bool,
                            task_keys: list[str] | None = None,
                            report: Path | None = None, out_dir: Path | None = None,
                            ledger: Path | None = None) -> list[Any]:
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
        "--ledger", ledger or LEDGER,
        "--report", report or REPORTS_DIR / f"{ctx.episode}_paid_authorization_{sid.lower()}.json",
    ]
    if out_dir is not None:
        argv += ["--out-dir", out_dir]
    # D-46 (2026-09-16 22:02Z): restrict the authorised copy to the tasks that still NEED a POST.
    # Without this a wave re-entry whose fingerprints changed (regenerated finalization receipts)
    # re-posted five units that already had clips on disk (680 cr, ~560 wasted).
    for key in task_keys or []:
        argv += ["--task-key", key]
    return argv


def materialize_paid_authorization(ctx: Ctx, res: StageResult, *, sid: str,
                                  target: Path, is_plan: bool,
                                  note: str = "", task_keys: list[str] | None = None,
                                  report: Path | None = None) -> tuple[str, Path, dict[str, Any]]:
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
    report_path = report or REPORTS_DIR / f"{ctx.episode}_paid_authorization_{sid.lower()}.json"
    argv = paid_authorization_argv(ctx, sid=sid, target=target, is_plan=is_plan,
                                   task_keys=task_keys, report=report_path)
    record["argv"] = [str(item) for item in argv]
    record["command"] = q(argv)
    if not target.is_file():
        record["status"] = BLOCKED
        record["blocker"] = f"PAID_AUTHORIZATION_INPUT_MISSING:{target}"
        ctx.say(f"   !! D-11 cannot authorise a file that does not exist: {target}")
        return BLOCKED, out, record

    if not ctx.paid_enabled:
        reason = (getattr(ctx, "paid_disabled_reason", None) or (
                  "--dry-run" if ctx.dry else
                  "--paid not given" if not ctx.want_paid else
                  "qingshan.json generation.paid_requests_enabled=false"))
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
    report = read_json(report_path, {}) or {}
    record["exit_code"] = step["exit_code"]
    record["report"] = str(report_path)
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


#: env var names whose VALUES are secrets (provider keys, tokens).  A child that echoes one (a debug
#: print, a traceback showing a request header) must not land it in a step log, a receipt or the
#: stage state that Codex / the orchestrator read back.
SECRET_ENV_NAME = re.compile(r"(API_KEY|_KEY$|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
SECRET_MIN_LENGTH = 8


def redact_secrets(text: str | None, env: dict[str, str] | None = None) -> str:
    """``text`` with every secret env value (see SECRET_ENV_NAME, >= 8 chars) replaced by
    ``***<NAME>***`` and bearer tokens masked.  Values come from ``env`` (default os.environ)."""
    text = text or ""
    if not text:
        return text
    source = os.environ if env is None else env
    secrets = sorted({(name, str(value)) for name, value in source.items()
                      if SECRET_ENV_NAME.search(str(name)) and len(str(value or "").strip()) >= SECRET_MIN_LENGTH},
                     key=lambda item: -len(item[1]))
    for name, value in secrets:
        text = text.replace(value, f"***{name}***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1***", text)


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


def _record_line_upgrade(ctx: Any, key: str, step: str) -> None:
    """Store the advisory result when the context carries state; never raise into the stage."""
    state = getattr(ctx, "state", None)
    if isinstance(state, dict) and getattr(ctx, "episode", None):
        state[key] = line_upgrade_gate_summary(ctx, step)


def line_upgrade_gate_summary(ctx: Ctx, step: str) -> dict[str, Any]:
    # advisory: any failure here is recorded, never raised into the stage that called it
    try:
        return _line_upgrade_gate_summary(ctx, step)
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{exc}"}


def _line_upgrade_gate_summary(ctx: Ctx, step: str) -> dict[str, Any]:
    """Shared line-upgrade gate (tools/line_upgrade_gate.py; docs/knowledge/LINE_UPGRADE_PROTOCOL.md).

    step="preflight" at S1: engine freshness/overlay check + writes the episode's
    knowledge briefing (the read side of the knowledge base).  step="close" at S8:
    verifies that briefing exists (the writer itself already ran via knowledge_sync).
    Advisory, never blocking: the result is recorded in state and CHECKPOINT only.
    """
    tool = ENGINE / "tools" / "line_upgrade_gate.py"
    if not tool.is_file():
        return {"status": "TOOL_MISSING", "tool": str(tool)}
    import subprocess as _sp
    cmd = [str(VENV), str(tool), step, "--line", "nalu", "--episode", ctx.episode,
           "--runtime-root", str(RT), "--engine-root", str(ENGINE)]
    if step == "close":
        cmd.append("--skip-sync")
    try:
        proc = _sp.run(cmd, cwd=str(ENGINE), capture_output=True, text=True, timeout=180)
    except (OSError, _sp.TimeoutExpired) as exc:
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{exc}", "argv": cmd}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        payload = {"status": "UNPARSEABLE", "stdout_tail": (proc.stdout or "")[-400:]}
    keep = ("status", "findings", "notes", "receipt", "knowledge", "knowledge_read", "collective", "error")
    summary = {key: payload[key] for key in keep if key in payload}
    if isinstance(payload.get("engine"), dict):
        summary["engine"] = {key: payload["engine"].get(key)
                             for key in ("head", "upstream", "behind", "status")}
    if isinstance(payload.get("overlays"), dict):
        summary["overlays"] = payload["overlays"].get("status")
    summary["exit_code"] = proc.returncode
    return summary


# Writer-capability input locations, relative to the episode's own directories.  A
# writer puts them where the tools' defaults already look; S1 only reads.
WRITER_CAPABILITY_INPUT_DIR = "writer_capability"


def writer_capability_record(ctx: "Ctx", p: "Paths") -> dict[str, Any]:
    """Read the four writer-capability inputs for this episode; never raise.

    Under LEGACY this returns ``NOT_APPLICABLE_LEGACY_PROFILE`` and nothing is read.
    Under WRITER_CAPABILITY_V1 it reports what exists, what its validator said and
    what is still owed.  It cannot block: the switches are in the config and all of
    them ship off.
    """
    try:
        import writer_capability as _wc
    except Exception as exc:  # noqa: BLE001 — a missing tool is a record, not a stage error
        return {"schema": "qingshan.writer_capability_stage.v1",
                "status": "TOOL_UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    root = Path(str(getattr(p, "work", "")) or "") / WRITER_CAPABILITY_INPUT_DIR
    return _wc.stage_summary(
        ctx.episode,
        arc_ledger=root / "ARC_LEDGER.json",
        adaptation_disposition=root / f"{ctx.episode}_ADAPTATION_DISPOSITION.json",
        script_review_report=root / f"{ctx.episode}_SCRIPT_REVIEW_REPORT.json",
        rule8_report=root / f"{ctx.episode}_RULE8_RESPONSE.json",
        narrative=getattr(p, "narrative", None),
    )


SCRIPT_LENGTH_RATIO = 1.3  # authored seconds may exceed the brief by 30 % (S7 cuts to the performance)
SCRIPT_SHORT_RATIO = 0.85  # E24 (device 1101, 2026-11-23): 62 s planned against a 110 s brief -> a 56 s episode
SCRIPT_DEFAULT_TARGET_SECONDS = 110.0  # line owner 2026-10-27: an episode is ~1 min 50 s
#: contract keys a writer may declare the episode's target duration under (the brief wins)
CONTRACT_TARGET_KEYS = ("target_seconds", "target_duration_seconds", "episode_target_seconds")


def script_length_check(ctx: Ctx) -> dict[str, Any]:
    """Stop an over-long or a degenerate short script at S1, while a rewrite is still free.

    Too long (line owner 2026-11-09; field device …1324 E03: 61 units, a 231 s cut against a 110 s brief and 860
    credits): sum of the shots' target_seconds > target x SCRIPT_LENGTH_RATIO -> BLOCKED (``blocker``).
    Too short (E24, device 1101, 2026-11-23: 22 shots / 62 s planned for a 110 s brief): planned < target x
    SCRIPT_SHORT_RATIO -> ``integrity_blocker`` SCRIPT_TOO_SHORT (an S1 integrity failure, returned to the writer;
    the other S1 gates still run so the writer sees everything at once).  The too-short floor applies only to a
    target the brief or the contract DECLARES (a lab without a brief is not held to the 110 s default) and never to
    an episode already past a paid stage.  Only CAMERA_GRAMMAR_V1 contracts are checked;
    NALU_SCRIPT_LENGTH_CHECK=off skips both."""
    if str(os.environ.get("NALU_SCRIPT_LENGTH_CHECK") or "").lower() == "off" or not _camera_grammar_on(ctx):
        return {"status": "NOT_APPLICABLE"}
    contract = read_json(ctx.p.contract, {}) or {}
    authored = round(sum(float(s.get("target_seconds") or 0) for s in contract.get("shots") or []), 1)
    brief = read_json(RUNTIME / "briefs" / f"{ctx.episode}_PRODUCTION_BRIEF.json", {}) or {}
    declared = brief.get("target_seconds") or next(
        (contract.get(k) for k in CONTRACT_TARGET_KEYS if contract.get(k)), None)
    try:
        declared = float(declared) if declared else None
    except (TypeError, ValueError):
        declared = None
    target = declared or SCRIPT_DEFAULT_TARGET_SECONDS
    limit = round(target * SCRIPT_LENGTH_RATIO, 1)
    floor = round(target * SCRIPT_SHORT_RATIO, 1)
    out = {"authored_seconds": authored, "target_seconds": target, "limit_seconds": limit,
           "floor_seconds": floor, "target_declared": declared is not None,
           "shots": len(contract.get("shots") or [])}
    if authored < floor and declared is not None and not s1_pacing_in_flight(ctx.p):
        return {**out, "status": BLOCKED,
                "integrity_blocker": f"SCRIPT_TOO_SHORT:{authored}s<{floor}s (target {target}s): the episode is "
                                     "short of its brief -- adapt more plot events (take the next source "
                                     "beats, add the interactions / reactions the scenes are missing) until the "
                                     "shots' target_seconds reach the floor (free)"}
    if authored <= limit:
        return {**out, "status": PASS}
    return {**out, "status": BLOCKED,
            "blocker": f"SCRIPT_TOO_LONG:{authored}s>{limit}s (target {target}s): rewrite the script layers shorter "
                       "before any paid stage -- merge or cut shots, keep the plot (free)"}


#: S1 blockers that are writer-fixable defects of the script itself (integrity, never taste): they return the
#: script to the writer, free, inside the bounded integrity loop below
S1_INTEGRITY_PREFIXES = ("SCRIPT_TOO_SHORT", "SCRIPT_TOO_LONG", "SCRIPT_INTEGRITY_FAIL", "DIRECTION_POLICY_INTEGRITY_FAIL",
                         "CHARACTER_ENTITY_CONTRACT_FAIL", "SCRIPT_STRUCTURE_CONTRACT_FAIL",
                         "CONTINUITY_STATE_CONTRACT_FAIL", "STATIC_DESIGN_GATE_FAIL",
                         "WRITER_CAPABILITY_STEP_OWED:SCRIPT_REVIEW_NOT_INDEPENDENT")
#: distinct failing scripts the writer gets; integrity failures are never admitted inside the taste loop, and after
#: this many revisions they are admitted and recorded so the line never stalls (owner standing rules 2026-11-23)
S1_INTEGRITY_MAX_ROUNDS = 4
S1_INTEGRITY_LEDGER = "S1_INTEGRITY_ROUNDS.json"


def s1_integrity_round(p: Any, layer_shas: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    """One S1 decision of the bounded integrity loop.  Each distinct set of layer bytes that fails an integrity
    check is one round; re-running S1 on the same bytes never uses up a round.  Rounds 1..S1_INTEGRITY_MAX_ROUNDS:
    REVISE (the writer fixes its own layers, the tick resumes Codex once per round); beyond: EXHAUSTED (the
    failures are admitted and recorded, no further resume).  Never raises."""
    codes = [b for b in blockers if str(b).startswith(S1_INTEGRITY_PREFIXES)]
    if not codes:
        return {"status": PASS, "decision": "PASS", "max_rounds": S1_INTEGRITY_MAX_ROUNDS}
    try:
        sha = hashlib.sha256(json.dumps(layer_shas or {}, sort_keys=True).encode("utf-8")).hexdigest()
        path = Path(getattr(p, "logs")) / S1_INTEGRITY_LEDGER
        state = read_json(path, {}) or {}
        rows = [r for r in state.get("rounds") or [] if isinstance(r, dict)]
        if not any(r.get("layers_sha256") == sha for r in rows):
            rows.append({"layers_sha256": sha, "codes": [str(c)[:160] for c in codes[:12]],
                         "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            write_json(path, {"schema": "nalu.s1_integrity_rounds.v1", "max_rounds": S1_INTEGRITY_MAX_ROUNDS,
                              "rounds": rows})
        n = next(i for i, r in enumerate(rows, 1) if r.get("layers_sha256") == sha)
    except Exception as exc:  # noqa: BLE001 -- the ledger must never break S1; an unknown round stays REVISE 1
        return {"status": BLOCKED, "decision": "REVISE", "round": 1, "max_rounds": S1_INTEGRITY_MAX_ROUNDS,
                "codes": codes[:12], "ledger_error": f"{type(exc).__name__}:{str(exc)[:160]}"}
    decision = "REVISE" if n <= S1_INTEGRITY_MAX_ROUNDS else "EXHAUSTED"
    return {"status": BLOCKED, "decision": decision, "round": n, "max_rounds": S1_INTEGRITY_MAX_ROUNDS,
            "codes": codes[:12], "ledger": str(path),
            "writer_instruction": ("revise the episode's own layers (narrative canonical -> four layers) for the "
                                   "integrity failures listed, then rerun S1; free, no owner decision"
                                   if decision == "REVISE" else
                                   f"{S1_INTEGRITY_MAX_ROUNDS} revisions did not clear the script's integrity "
                                   "failures: admitted and recorded (SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION); "
                                   "the line continues")}


def s1_integrity_blockers(decision: dict[str, Any], blockers: list[str]) -> list[str]:
    """The S1 blockers after the integrity loop's decision.  REVISE: prefixed with the round marker (the tick keys on
    ``SCRIPT_INTEGRITY_REVISE:round=``).  EXHAUSTED: the integrity failures are admitted (dropped from the blockers,
    recorded as SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION) -- only the non-integrity blockers remain."""
    if decision.get("decision") == "REVISE":
        return [f"SCRIPT_INTEGRITY_REVISE:round={decision['round']}/{decision['max_rounds']}"] + list(blockers)
    if decision.get("decision") == "EXHAUSTED":
        return [b for b in blockers if not str(b).startswith(S1_INTEGRITY_PREFIXES)]
    return list(blockers)


def s1_integrity_admission_marker(blockers: list[str]) -> str:
    """``SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:<codes>`` -- the gate (and the sub-code for the integrity
    families) of every admitted failure, deduplicated, no story text."""
    codes: list[str] = []
    for b in blockers:
        text = str(b)
        if not text.startswith(S1_INTEGRITY_PREFIXES):
            continue
        head, _, rest = text.partition(":")
        if head in ("SCRIPT_INTEGRITY_FAIL", "DIRECTION_POLICY_INTEGRITY_FAIL", "WRITER_CAPABILITY_STEP_OWED"):
            head = f"{head}:{rest.split(':', 1)[0]}"
        if head not in codes:
            codes.append(head)
    return "SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:" + ",".join(codes[:12])


def s1_integrity_fleet_note(ctx: Any, marker: str) -> None:
    """One line in ``<runtime>/series/STATUS.md`` (the tail fleet_sync reports) -- once per episode and marker."""
    try:
        path = RUNTIME / "series" / "STATUS.md"
        line = f"{ctx.episode} S1 {marker}"
        if path.is_file() and line in path.read_text(encoding="utf-8"):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- {time.strftime('%Y-%m-%d %H:%MZ', time.gmtime())} {line}\n")
    except OSError:
        pass


DIRECTION_POLICY_CONFIG = "configs/DIRECTION_POLICY_V1.json"


def s1_direction_policy(ctx: Ctx, p: Any, *, in_flight: bool = False) -> tuple[dict[str, Any], list[str]]:
    """direction_policy_gate at S1 (E24 2026-11-23: it existed but stage_s1 never called it).  The whole report is
    recorded; only its S1 integrity rules (DP9: CU+MCU <= 80 %, >= 2 two-person / group shots per multi-character
    scene) block, for every new episode -- an episode already past a paid stage is grandfathered.
    NALU_DIRECTION_POLICY_S1=off records without blocking.  Never raises."""
    try:
        import direction_policy_gate as _dpg  # noqa: PLC0415 -- engine tools/ is on sys.path
        contract = read_json(p.contract, {}) or {}
        report = _dpg.evaluate(contract, _dpg.load_policy(ENGINE / DIRECTION_POLICY_CONFIG))
        out = p.logs / f"{ctx.run_id}_direction_policy_gate.json"
        write_json(out, report)
        failures = _dpg.integrity_failures(report)
        switched_off = str(os.environ.get("NALU_DIRECTION_POLICY_S1") or "").lower() == "off"
        blocking = bool(failures) and not in_flight and not switched_off
        row = {"status": report.get("status"), "integrity_status": "FAIL" if failures else PASS,
               "integrity_failures": failures[:12], "blocking": blocking,
               "failures": (report.get("failures") or [])[:12], "report": str(out),
               "measurements": {"DP9": (report.get("measurements") or {}).get("DP9")},
               **({"grandfathered": "IN_FLIGHT_PAST_PAID_STAGE"} if failures and in_flight else {})}
        if failures:
            row["fix"] = ("give every scene with two or more characters at least two shots with both (or all) of "
                          "them in frame -- a silent two-shot / group action, or the listener over the speaker's "
                          "shoulder (back of head, face not visible) -- and keep CU+MCU at or under 80 % of shots")
        return row, ([f"DIRECTION_POLICY_INTEGRITY_FAIL:{f}" for f in failures[:8]] if blocking else [])
    except Exception as exc:  # noqa: BLE001 -- a policy measurement must never break S1
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}, []


def script_review_independence_row(writer_capability: dict[str, Any], contract_path: Any) -> dict[str, Any]:
    """Was the script reviewed by somebody other than the writer?  E24: ``contract.script_review`` said
    {reviewer: codex, status: PASS} -- the writer's own claim, never evidence.  Only the writer-capability review
    report counts, and only with an independent reviewer and the request sha (writer_capability.review_independence)."""
    row = ((writer_capability.get("inputs") or {}).get("script_review") or {}) if isinstance(
        writer_capability, dict) else {}
    self_claim = (read_json(Path(contract_path), {}) or {}).get("script_review") if contract_path else None
    if not row:
        status = "NOT_APPLICABLE" if writer_capability.get("profile") != "WRITER_CAPABILITY_V1" else "MISSING"
    elif not row.get("present"):
        status = "MISSING"
    else:
        status = PASS if row.get("independent") else "NOT_INDEPENDENT"
    return {"status": status, "reviewer": row.get("reviewer"), "request_sha256": row.get("request_sha256"),
            "failures": row.get("independence_failures") or [],
            "contract_self_review_ignored": bool(self_claim),
            "blocks": "SCRIPT_REVIEW_NOT_INDEPENDENT" in (writer_capability.get("blocks_stage") or [])}


#: stages whose start means money was spent on the episode: a default-policy pacing revision never reopens it
PACING_PAID_STAGES = ("S4", "S5", "S6", "S7", "S8")


def s1_pacing_in_flight(p: Any) -> bool:
    """The episode already ran a paid stage (S4+ has a recorded status other than a dry run) -- its script is
    grandfathered under the default SHORT_DRAMA_PACING_V1 (a contract that declares the policy is not)."""
    state_path = getattr(p, "state", None)
    if not state_path:
        return False
    stages = (read_json(Path(state_path), {}) or {}).get("stages") or {}
    for name in PACING_PAID_STAGES:
        status = str((stages.get(name) or {}).get("status") or "").upper()
        # any recorded run of a paid stage (PASS, BLOCKED after a partial spend, REMOTE_WAIT ...) counts; a dry
        # plan or a stage that never ran does not
        if status and not status.startswith("DRY") and status not in (NOT_RUN, ROUTE_MISSING, "NOT_STARTED",
                                                                      "PENDING"):
            return True
    return False


def s1_script_pacing(ctx: Ctx, p: Any, *, others_ok: bool) -> tuple[dict[str, Any], list[str]]:
    """SHORT_DRAMA_PACING_V1 at S1: (episode-record row, blockers).  The policy is the default of every contract
    (an explicit ``pacing_policy: OFF`` opts out; a default-policy episode already past a paid stage is
    grandfathered).  Blockers only in a revision round (script_pacing_check.decide); the report and the round
    ledger sit beside the other S1 logs and the series source coverage is updated once the script is admitted.
    Never raises: any error = no blocker."""
    try:
        import script_pacing_check as _pace  # noqa: PLC0415 -- same directory
        contract = read_json(p.contract, {}) or {}
        report = _pace.evaluate(contract, ctx_language(ctx), in_flight=s1_pacing_in_flight(p),
                                source_texts=_pace.source_texts_for(contract, RUNTIME))
        report_path = p.logs / f"{ctx.run_id}_script_pacing.json"
        write_json(report_path, report)
        integrity = _pace.integrity_blocker_codes(report)
        # a taste round is only counted on a script that is structurally whole (integrity is not taste)
        decision = _pace.decide(report, _pace.contract_sha(contract), p.logs / "SCRIPT_PACING_ROUNDS.json",
                                record=others_ok and not integrity)
        if integrity and decision.get("blocks"):
            decision = {**decision, "decision": "PENDING_SCRIPT_INTEGRITY", "blocks": False}
        if not others_ok and decision.get("blocks"):
            decision = {**decision, "decision": "PENDING_OTHER_S1_GATES", "blocks": False}
        row = {**_pace.summary(report, decision), "report": str(report_path), "fixes": report.get("fixes") or {}}
        if decision.get("decision") == "REVISE":
            row["writer_instruction"] = ("revise the episode's own layers (narrative canonical -> four layers) "
                                         "for the failures above, then rerun S1; free, no owner decision")
        if others_ok and not integrity and decision.get("decision") not in ("REVISE", "PENDING_SCRIPT_INTEGRITY"):
            cov = _pace.record_coverage(RUNTIME, ctx.episode, contract)
            if cov:
                row["source_coverage"] = {k: cov.get(k) for k in ("last_chapter", "next_chapter", "skipped_chapters")}
        if integrity:
            row["integrity_instruction"] = ("SCRIPT_INTEGRITY_FAIL is not taste: never admitted after revisions -- "
                                            "write each scene's own ambience / scene plan / location; see fixes")
        return row, _pace.blocker_codes(report, decision) + integrity
    except Exception as exc:  # noqa: BLE001 -- a pacing measurement must never break S1
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}, []


def stage_s1(ctx: Ctx) -> StageResult:
    p = ctx.p
    _record_line_upgrade(ctx, "line_upgrade_preflight", "preflight")  # advisory read side
    missing = [str(path) for path in p.layers().values() if not path.is_file()]
    if missing:
        res = StageResult(BLOCKED, missing_layers=missing, layer_sha256={})
        res.blockers = [f"SCRIPT_LAYER_MISSING:{path}" for path in missing]
        return res
    layer_shas = {name: sha256_file(path) for name, path in p.layers().items()}

    length = script_length_check(ctx)
    admitted_length: list[str] = []
    if length.get("status") == BLOCKED and length.get("blocker"):
        early = s1_integrity_round(p, layer_shas, [length["blocker"]])
        if early.get("decision") != "EXHAUSTED":
            res = StageResult(BLOCKED, missing_layers=[], layer_sha256=layer_shas, script_length=length)
            res.details = {"s1_integrity": early}
            res.blockers = s1_integrity_blockers(early, [length["blocker"]])
            return res
        # rounds exhausted: the over-long script is admitted with the others below (never stall the line)
        admitted_length = [length["blocker"]]
    integrity_blockers: list[str] = [length["integrity_blocker"]] if length.get("integrity_blocker") else []
    in_flight = s1_pacing_in_flight(p)
    direction_policy, direction_blockers = s1_direction_policy(ctx, p, in_flight=in_flight)
    integrity_blockers += direction_blockers

    # Writer-capability record (line owner 2026-11-01): under WRITER_CAPABILITY_V1 an
    # episode must show an arc ledger, its own adaptation disposition, an answered
    # pre-lock script review and its Rule 8 responses; under LEGACY none of it is
    # looked at.  Recorded, never raised: every blocking switch ships off, so this
    # cannot change what S1 decides today.  See docs/knowledge/WRITER_CAPABILITY_PLAN_V1.md.
    writer_capability = writer_capability_record(ctx, p)

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
        # HONESTY (line owner 2026-11-01): under LEGACY the canonical writer handoff
        # was never verified.  ``storyclaw_writer_workflow.py verify`` is the StoryClaw
        # private-project path and is a stub for this line (CLAUDE_CODE_PRODUCTION.md
        # §0 tells the writer never to run it as an S1 conclusion), so nothing checked
        # that the four layers came out of one sealed writer run.  The stage outcome is
        # unchanged — E01-E13 stay sealed — but the receipt now says NOT_RUN instead of
        # borrowing a PASS it did not earn.
        writer_handoff = {
            "exit_code": 0,
            "log": None,
            "stdout_tail": WRITER_HANDOFF_LEGACY_STATUS,
        }
        writer_handoff_verdict = {
            "status": WRITER_HANDOFF_LEGACY_STATUS,
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
    # seq=29 rule 7c: this tool's --lexicon is the PERFORMANCE EMOTION lexicon, not the period word
    # lexicon used by the structure gate above.  Passing the period lexicon loads an empty emotion set
    # and fails every authored emotion with R7C_EMOTION_NOT_IN_LEXICON, so the default is what we want.
    selfcheck_step = ctx.run([VENV, RT_TOOLS / "nalu_writer_selfcheck_seq29.py", "--contract", p.contract,
                              "--out", selfcheck_out],
                             name="s1_writer_selfcheck_seq29")
    selfcheck = read_json(selfcheck_out, {}) or {}
    selfcheck_ok = writer_selfcheck_admitted(
        selfcheck, int(selfcheck_step["exit_code"])
    )
    # DIALOGUE_REGISTER_V1 (Roger 2026-11-08 seq=219 「台词照搬小说原著，AI 味太重」): every spoken line is
    # checked against the episode's source chapter (verbatim runs), for written-register wording and for
    # two characters sharing one voice.  Offline and free.  Inactive policy / no source file = NOT_ACTIVE,
    # so delivered episodes and episodes without a source text are untouched.
    dialogue_register: dict[str, Any] = {"status": "NOT_ACTIVE"}
    dialogue_register_path = p.logs / f"{ctx.run_id}_dialogue_register_gate.json"
    # the source chapter follows the episode number (E15 -> ch0015.md); a contract may name its own file
    episode_index = re.sub(r"\D", "", str(ctx.episode)) or "0"
    declared_source = str(((read_json(p.contract, {}) or {}).get("source_text")) or "")
    source_candidates = [Path(declared_source) if declared_source else None,
                         RUNTIME / "sources" / "夜无疆" / "zh-CN" / f"ch{int(episode_index):04d}.md"]
    source_path = next((c for c in source_candidates if c and c.is_file()), None)
    if source_path is not None:
        register_step = ctx.run(
            [VENV, ENGINE / "tools/dialogue_register_gate.py", "--contract", str(p.contract),
             "--source", str(source_path), "--out", str(dialogue_register_path)],
            name="s1_dialogue_register_gate")
        dialogue_register = read_json(dialogue_register_path, {}) or {"status": "NOT_ACTIVE"}
        dialogue_register["exit_code"] = register_step["exit_code"]
    dialogue_register_ok = str(dialogue_register.get("status") or "") in {"PASS", "NOT_ACTIVE"}
    status = PASS if (writer_handoff_ok and gate10_ok and entity_ok and static_ok and structure_ok and continuity_ok and scope_ok and selfcheck_ok and dialogue_register_ok) else BLOCKED
    # SHORT_DRAMA_PACING_V1 (line owner 2026-11-22 「剧情推进太慢……一集基本就是人物在念台词」): free, deterministic
    # script pacing metrics on every contract; the policy is the DEFAULT (E07 2026-11-22: no ``pacing_policy`` key ->
    # advisory -> no revision), a failing script is sent back to the writer for at most MAX_REVISIONS revisions,
    # then admitted with the gaps recorded.  A round is only counted when every other S1 gate passed.  Never raises.
    script_pacing, pacing_blockers = s1_script_pacing(
        ctx, p, others_ok=(status == PASS and not integrity_blockers
                           and not (writer_capability.get("blocks_stage") or [])))
    if pacing_blockers and status == PASS:
        status = BLOCKED
    # S1 integrity (E24 2026-11-23): too short, CU/MCU-only singles, ... -- never admitted, returned to the writer
    if integrity_blockers and status == PASS:
        status = BLOCKED
    # Line owner 2026-11-01: under WRITER_CAPABILITY_V1 the writing PROCEDURE is required — a missing or unanswered
    # script review / Rule 8 answer / arc ledger / adaptation disposition keeps the script from being marked complete
    # for paid preparation.  LEGACY episodes return no blocks, so E01-E13 are untouched; opinion never blocks.
    capability_blocks = list(writer_capability.get("blocks_stage") or [])
    if capability_blocks and status == PASS:
        status = BLOCKED
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
    res.details["writer_capability"] = writer_capability
    res.details["project_scope_check"] = scope_check
    res.details["writer_selfcheck_seq29"] = {"status": selfcheck.get("status"), "enforced": selfcheck.get("enforced"),
                                             "failures": (selfcheck.get("failures") or [])[:12], "failure_count": len(selfcheck.get("failures") or []),
                                             "report": str(selfcheck_out), "exit_code": selfcheck_step["exit_code"]}
    if not selfcheck_ok:
        res.blockers = list(getattr(res, "blockers", []) or []) + [f"WRITER_SELFCHECK_SEQ29_FAIL:{code}" for code in (selfcheck.get("failures") or [])[:8]]
    # The register gate decided the stage but was shown nowhere: S1 came back BLOCKED with blockers [] and the
    # executor had to find the gate's own JSON to learn why (fleet device 0899 E17/E18, 1037 E16, 2026-11-17).
    res.details["dialogue_register_gate"] = dialogue_register_summary(dialogue_register, dialogue_register_path)
    if not dialogue_register_ok:
        res.blockers = list(getattr(res, "blockers", []) or []) + dialogue_register_blockers(dialogue_register)
    if capability_blocks:
        res.blockers = list(getattr(res, "blockers", []) or []) + [f"WRITER_CAPABILITY_STEP_OWED:{code}" for code in capability_blocks]
    res.details["script_pacing"] = script_pacing
    res.details["script_length"] = length
    res.details["direction_policy_gate"] = direction_policy
    res.details["script_review_independence"] = script_review_independence_row(writer_capability, p.contract)
    if pacing_blockers:
        res.blockers = list(getattr(res, "blockers", []) or []) + pacing_blockers
    if integrity_blockers:
        res.blockers = list(getattr(res, "blockers", []) or []) + integrity_blockers
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
    # The bounded integrity loop: every writer-fixable script defect above sends the script back to the writer
    # (the tick resumes Codex once per round); after S1_INTEGRITY_MAX_ROUNDS distinct failing scripts the remaining
    # integrity failures are ADMITTED and recorded (owner standing rules 2026-11-23: never stall the line, keep only
    # critical gates; a short cut is still held at release by the < 0.85 x target release hold) -- the loop
    # terminates and the tick has no round left to resume.
    current = admitted_length + list(getattr(res, "blockers", []) or [])
    integrity = s1_integrity_round(p, layer_shas, current)
    res.details["s1_integrity"] = integrity
    res.blockers = s1_integrity_blockers(integrity, current)
    if integrity.get("decision") == "EXHAUSTED":
        integrity["admitted"] = [str(b)[:200] for b in current if str(b).startswith(S1_INTEGRITY_PREFIXES)][:16]
        integrity["marker"] = s1_integrity_admission_marker(current)
        res.details["s1_integrity_admitted"] = integrity["marker"]
        s1_integrity_fleet_note(ctx, integrity["marker"])
        if not res.blockers and status == BLOCKED:
            status = PASS
            res.status = PASS
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
        # Recorded so a later reader can tell which writer-capability profile produced
        # this receipt without re-deriving it from the episode number.
        "writer_capability": {
            "profile": writer_capability.get("profile"),
            "status": writer_capability.get("status"),
            "reason": writer_capability.get("reason"),
            "owed": writer_capability.get("owed") or [],
            "sealed_binding": (writer_capability.get("sealed_binding") or {}).get("status"),
        },
        "gates": {
            "canonical_writer_handoff": writer_handoff_gate_status(writer_handoff_ok, writer_handoff_verdict),
            "gate10": PASS if gate10_ok else "FAIL",
            "character_entity_contract": PASS if entity_ok else "FAIL",
            "static_design_gate": PASS if static_ok else "FAIL",
            "script_structure_contract_gate": PASS if structure_ok else "FAIL",
            "continuity_state_contract_gate": PASS if continuity_ok else "FAIL",
            "project_scope_check": PASS if scope_ok else "FAIL",
            "script_length": str(length.get("status") or "NOT_APPLICABLE"),
            "direction_policy_integrity": direction_policy.get("integrity_status") or "NOT_RUN",
            "script_pacing_integrity": str(script_pacing.get("integrity_status") or "NOT_RUN"),
            "script_review_independent": res.details["script_review_independence"]["status"],
        },
    })
    res.details["s1_gate_receipt"] = {
        "path": str(s1_receipt),
        "sha256": sha256_file(s1_receipt),
        "status": status,
    }
    res.receipts.append(str(s1_receipt))
    return res


def dialogue_register_blockers(report: dict[str, Any]) -> list[str]:
    """S1 blocker codes for a failed DIALOGUE_REGISTER_V1 gate.  The gate's ``failures`` are rule totals
    (``DIALOGUE_SOURCE_VERBATIM:13``), never dialogue text, so they are safe to show as they are."""
    codes = [str(code) for code in (report.get("failures") or []) if isinstance(code, str) and code.strip()]
    if not codes:
        return [f"DIALOGUE_REGISTER_FAIL:{str(report.get('status') or 'NO_REPORT')}"]
    return [f"DIALOGUE_REGISTER_FAIL:{code}" for code in codes[:8]]


def dialogue_register_summary(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    return {"status": report.get("status"), "exit_code": report.get("exit_code"),
            "failures": [str(code) for code in (report.get("failures") or []) if isinstance(code, str)][:12],
            "report": str(report_path) if Path(report_path).is_file() else None,
            "fix": "rewrite the listed lines in the writer's own files as speech the character would say; "
                   "the canonical script is the line authority, the novel's wording is not"}


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
        "--language", ctx_language(ctx),
    ]
    if p.legacy_grouping_plan.is_file():
        argv += ["--legacy-plan", p.legacy_grouping_plan]
    authored_states = p.rt_pre / "shot_state_authoring.json"
    if authored_states.is_file():
        argv += ["--state-authoring", authored_states]
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
        "shot_state_authoring": sha256_file(p.rt_pre / "shot_state_authoring.json"),
        "overlay": sha256_file(p.overlay) if p.overlay else None,
        "keyframes": sorted(item.name for item in p.keyframes.glob("*.png")) if p.keyframes.is_dir() else [],
        # a config-only language switch re-runs S2; zh fingerprints are unchanged
        **({"dialogue_language": ctx_language(ctx)} if ctx_language(ctx) != "zh" else {}),
        # V.O. narration: an episode that passed S2 before the rule existed re-runs S2 once so its
        # editorial carries prompt_spec.voice_over; contracts without narration are unchanged
        **({"voice_over_rule": _vo.RULE_VERSION}
           if _vo.contract_has_voice_over(read_json(p.contract, {}) or {}, ctx_language(ctx)) else {}),
    }, sort_keys=True))


def fp_s4(ctx: Ctx) -> str | None:
    """S4 re-runs when the editorial's V.O. narration lines change (or first appear on an episode
    whose voices were LOCKED before the rule existed); no narration = no fingerprint = unchanged."""
    lines = editorial_voice_over_lines(read_json(ctx.p.editorial, {}) or {})
    if not lines:
        return None
    return sha256_text(json.dumps(
        [[line["shot_id"], int(line["line_index"]), str(line["character_id"]), _vo.text_sha256(line["text"])]
         for line in lines], sort_keys=True))


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
    # Plan §6: the grouping plan now exists, so the request duration of every
    # unit is known.  Record the five durations once here; S6 and S7 add the
    # returned-media and cut-interval halves as they become measurable.
    if status == PASS:
        timing = timing_map(ctx, stage="S2")
        res.details["unit_timing_map"] = timing
        if timing.get("receipt"):
            res.receipts.append(timing["receipt"])
        # A line generated by two units is the §6 defect this map exists for: it
        # means the same speech is bought twice and then stitched.  It is a
        # contract conflict, so it stops the stage before anything is paid — but
        # only for an episode the plan policy has been enabled for, so an
        # in-production episode keeps its locked behaviour until someone lists it.
        if _previs.gate_active(ctx.episode, contract=read_json(p.contract, {}) or {}):
            doubled = [f for f in timing.get("failures") or []
                       if f.get("code") == "DIALOGUE_GENERATED_BY_TWO_UNITS"]
            if doubled:
                res.status = BLOCKED
                res.blockers = [f"DOUBLED_DIALOGUE_LINE:{row.get('ref')}:{row.get('detail')}"
                                for row in doubled]
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


def s3_submission_plan(plan: dict[str, Any], locked: dict[str, Any],
                       subset: list[str]) -> dict[str, Any]:
    """Exclude verified reuse from the actual paid input, not just cost estimates.

    Keep transaction-bound non-reuse rows for the original submitter's recovery.
    Never mutate the full authored plan or its prompt/reference bindings.
    """
    selected = dict(plan)
    selected['new_asset_groups'] = [
        row for row in plan.get('new_asset_groups', [])
        if row['id'] not in locked and (not subset or row['id'] in subset)]
    selected['reuse_excluded_subject_ids'] = [
        row['id'] for row in plan.get('new_asset_groups', []) if row['id'] in locked]
    return selected


def voice_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """`major_roles` in runtime/voice_registry.json is a LIST of row objects."""
    rows = registry.get("major_roles")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(rows, dict):
        return [dict(row, entity_id=row.get("entity_id", key))
                for key, row in rows.items() if isinstance(row, dict)]
    return []


def locked_voice_entities(registry: dict[str, Any], *, require_public_url: bool = False) -> dict[str, dict[str, Any]]:
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
        # MiniMax-H3 takes voice references only as public HTTPS URLs: a row without one is redone
        if require_public_url and not str(row.get("remote_url") or "").startswith("https://"):
            continue
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
        # CAMERA_GRAMMAR_V1: the series library says which characters still need their H3 reference sheet
        "--series-asset-library", (getattr(p, "scope", None) or {}).get("asset_library") or ASSET_LIBRARY,
    ]
    if rights_basis:
        argv += ["--rights-basis", rights_basis]
    # Production authorization is not evidence that source images were reviewed.
    # Only the explicit review route may assert source QA.
    if accept_qa:
        argv += ["--accept-source-qa"]
    return argv


S3_MAX_ROUNDS = 6  # 2 rounds base + views, +2 for one distinctness regeneration, +2 slack
S3_IMAGE_MODEL, S3_IMAGE_RESOLUTION = ACTIVE_IMAGE_MODEL, ACTIVE_IMAGE_RESOLUTION   # registry policy; submit_giggle_character_asset_plan.py reads the same


def s3_transaction_bound(ctx: Ctx, row: dict[str, Any]) -> bool:
    """True when the durable store already holds a SUBMITTED_TASK_ID_BOUND
    transaction for this exact row (same fingerprint the submitter computes), so a
    re-submit is recovered for free and must not be counted as planned spend."""
    # A row bound under a retired image SKU (gpt-image-2-pro before seq=54) or a retired
    # resolution (2K before seq=56) is still bound: the plate exists and was paid for, so neither
    # switch may re-plan its spend.  The fingerprint is provider-independent (HopsAPI or Giggle).
    from itertools import product as _product
    active_fingerprint = ""
    for model, resolution in _product(sorted(known_image_models(), key=lambda m: m != S3_IMAGE_MODEL),
                                      known_image_resolutions()):
        contract = {
            "character_id": row.get("id"),
            "prompt_sha256": row.get("prompt_sha256"),
            "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
            "model": model, "aspect_ratio": "9:16", "resolution": resolution,
        }
        fingerprint = hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
        if model == S3_IMAGE_MODEL and resolution == S3_IMAGE_RESOLUTION:
            active_fingerprint = fingerprint
        path = (ENGINE / "workflow/tasks/giggle_submit_transactions" / ctx.episode
                / f"{row['id']}__{fingerprint[:16]}.json")
        if not path.is_file():
            continue
        transaction = read_json(path, {}) or {}
        if _image_client().terminal_failed_binding(transaction):
            return False  # HopsAPI task failed uncharged: the submitter retires it and POSTs again
        if (transaction.get("submission_fingerprint") == fingerprint
                and transaction.get("state") == "SUBMITTED_TASK_ID_BOUND"
                and bool(transaction.get("task_id"))):
            return True
    # Lab E08 2026-10-29: the multi-view sheet's reference list grew once the headshot was
    # harvested, the fingerprint drifted, and re-entry planned 11 credits for a sheet that was
    # bound and on disk.  The submitter reuses a bound + harvested take of the same row whatever
    # its recomputed fingerprint (tools/submit_giggle_character_asset_plan.harvested_binding,
    # mirrors tools/video_live_binding.py), so the planner must cost it at zero too.
    return s3_harvested_binding(ctx, row, active_fingerprint) is not None


def s3_harvested_binding(ctx: Ctx, row: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.submit_giggle_character_asset_plan import harvested_binding  # engine, read-only
    row = dict(row)
    row.setdefault("episode", ctx.episode)
    return harvested_binding(row, ENGINE / "workflow/tasks/giggle_submit_transactions" / ctx.episode,
                             ctx.p.identity_harvest_dir, current_fingerprint=fingerprint)


def s3_fresh_submit_report(path: Path, started: float) -> dict[str, Any]:
    """The submit report only when the child under judgement wrote it ({} for a stale one)."""
    try:
        if path.stat().st_mtime < started:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def s3_plate_on_disk(ctx: Ctx, row_id: str) -> bool:
    plates = ctx.p.identity_harvest_dir
    if not plates.is_dir():
        return False
    pattern = re.compile(rf"^{re.escape(ctx.episode)}_{re.escape(row_id)}_(?:[0-9a-fA-F-]{{8,}}|tsk_[0-9A-Za-z_]{{8,}})\.png$")
    return any(pattern.match(item.name) for item in plates.iterdir())


def s3_register_reference_sheets(ctx: Ctx) -> list[dict[str, Any]]:
    """CAMERA_GRAMMAR_V1 H3 multi-view reference sheets harvested this episode -> series library rows
    (character_reference_sheet.register; a face mismatch is recorded and H3 keeps the headshot).  Never
    blocks S3: the sheet is an H3 reference, not an identity authority."""
    try:
        import character_reference_sheet as _sheet
        library_path = Path((getattr(ctx.p, "scope", None) or {}).get("asset_library") or ASSET_LIBRARY)
        plates = ctx.p.identity_harvest_dir
        if not _sheet.harvested_sheets(plates, ctx.episode):
            return []
        if ctx_render_style(ctx) == "anime":  # InsightFace is NOT_APPLICABLE to anime faces (render_style.py)
            return _sheet.register(library_path, plates, ctx.episode, measure=None, render_style="anime")
        return _sheet.register(library_path, plates, ctx.episode, measure=_sheet.insightface_measure())
    except Exception as exc:  # noqa: BLE001 - advisory step
        return [{"status": "REGISTRATION_ERROR", "error": f"{type(exc).__name__}: {exc}"}]


def s3_distinctness_embedder() -> tuple[Callable[[Path], list[list[float]]], Callable[..., float]] | None:
    """(embed(path) -> [embedding], cosine) from the engine's own InsightFace backend, or None when unavailable."""
    try:
        from nalu_qa_common import engine_module as _engine_module, gate_parameters as _gate_parameters
        gate = _engine_module("character_identity_admission_gate")
        backend = gate.InsightFaceBackend(str(_gate_parameters("CHARACTER-IDENTITY-ADMISSION").get(
            "embedding_model", "buffalo_l")))
    except Exception:  # noqa: BLE001
        return None
    return (lambda path: [list(backend.embed(Path(path)))]), gate._cosine  # noqa: SLF001 -- engine's own metric


def s3_s6_started(ctx: Ctx) -> bool:
    """The episode's S6 already ran (wave state or a landed unit clip): its cards are on screen and stay."""
    try:
        if _wave_state_path(ctx).is_file():
            return True
        media = ctx.p.video_media
        return media.is_dir() and any(media.glob("*.mp4"))
    except Exception:  # noqa: BLE001 - unknown: treat as started (never re-design blindly)
        return True


def s3_screen_time(ctx: Ctx) -> dict[str, float]:
    """character id -> seconds on screen in this episode (shot durations of the editorial manifest's cast, else the
    generation contract's), the speaker's lines counted again: who the episode is about."""
    out: dict[str, float] = {}
    try:
        source = read_json(ctx.p.editorial, {}) or read_json(ctx.p.contract, {}) or {}
        for shot in source.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            spec = shot.get("prompt_spec") or {}
            seconds = float(shot.get("duration_seconds") or shot.get("duration") or 1.0)
            for row in spec.get("cast") or shot.get("cast") or []:
                cid = str((row or {}).get("character_id") or "") if isinstance(row, dict) else ""
                if cid:
                    out[cid] = out.get(cid, 0.0) + seconds
            for line in spec.get("dialogue") or shot.get("dialogue") or []:
                cid = str((line or {}).get("speaker_id") or (line or {}).get("character_id") or "") \
                    if isinstance(line, dict) else ""
                if cid:
                    out[cid] = out.get(cid, 0.0) + seconds
    except Exception:  # noqa: BLE001 - no data: equal screen time
        return {}
    return {k: round(v, 2) for k, v in out.items()}


def _operator_sourced(asset: Any) -> bool:
    """A library card made from an operator photo (``source_reference`` set anywhere / an operator-source rule)."""
    if isinstance(asset, dict):
        if asset.get("source_reference"):
            return True
        if str(asset.get("identity_rule") or asset.get("reference_role") or "").startswith("OPERATOR_SOURCE"):
            return True
        return any(_operator_sourced(v) for v in asset.values())
    if isinstance(asset, list):
        return any(_operator_sourced(v) for v in asset)
    return False


def s3_locked_card_redesignable(ctx: Ctx, cid: str, library: dict[str, Any]) -> bool:
    """A character LOCKED in an earlier episode whose card S3 may re-design once for distinctness (2026-11-21, KO
    E05): a text-to-image card (no operator photo in the library entry or runtime/character_sources), not re-designed
    before, with its authored card prompt still on disk.  Never anime (cast distinctness is a review answer there)."""
    try:
        if ctx_render_style(ctx) == "anime" or str(os.environ.get("NALU_S3_DISTINCT_LOCKED_REDESIGN", "1")).strip() \
                in ("0", "off", "false"):
            return False
        asset = (((library.get("assets") or {}).get("characters") or {}).get(cid))
        if not isinstance(asset, dict) or asset.get("status") != "LOCKED" or asset.get("distinctness_regeneration"):
            return False
        if _operator_sourced(asset):
            return False
        sources = Path(str((ctx.p.scope or {}).get("character_sources") or ""))
        if sources.is_dir() and any(sources.glob(f"{cid}__*")):
            return False
        return s3_card_prompt_source(ctx, cid) is not None
    except Exception:  # noqa: BLE001
        return False


def s3_card_prompt_source(ctx: Ctx, cid: str) -> Path | None:
    """The authored base-card prompt of a character from the earliest episode that wrote one."""
    root = ctx.p.rt_pre.parent
    found = sorted(root.glob(f"E*/prompts/E*-{cid}.txt"), key=lambda q: (episode_index(q.parent.parent.name), q.name))
    return found[0] if found else None


def s3_unlock_locked_card(ctx: Ctx, action: dict[str, Any]) -> dict[str, Any]:
    """Re-design one LOCKED card for distinctness: its authored prompt is copied into this episode's prompt dir
    (the regeneration block is appended by bootstrap_identity_cards from the policy file) and its series-library
    entry is set to ``SUPERSEDED_DISTINCTNESS_PENDING_REGENERATION`` with the old lock kept under
    ``superseded_locks`` -- the documented 换代重做 path: S3 plans it like a new card, identity QA locks the new card,
    and every later episode reuses the new one.  The card is marked ``distinctness_regeneration`` so it is never
    re-designed again.  Never raises."""
    import character_distinctness as _cd
    cid = str(action.get("subject_id") or "")
    try:
        if not getattr(ctx, "paid_enabled", False):
            return {"status": "NEEDS_PAID_RUN"}
        source = s3_card_prompt_source(ctx, cid)
        if source is None:
            return {"status": "CARD_PROMPT_MISSING"}
        lib_path = Path((getattr(ctx.p, "scope", None) or {}).get("asset_library") or ASSET_LIBRARY)
        library = read_json(lib_path, {}) or {}
        asset = (((library.get("assets") or {}).get("characters") or {}).get(cid))
        if not isinstance(asset, dict) or asset.get("status") != "LOCKED":
            return {"status": "NOT_LOCKED"}
        target = ctx.p.prompt_dir / f"{ctx.episode}-{cid}.txt"
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        snapshot = {k: copy.deepcopy(asset.get(k)) for k in ("status", "version", "qa", "lock", "artifacts")
                    if k in asset}
        asset.setdefault("superseded_locks", []).append({**snapshot, "superseded_at": now(),
                                                         "superseded_by": TOOL_ID,
                                                         "reason": "CHARACTER_DISTINCTNESS_REDESIGN"})
        asset["status"] = _cd.LOCKED_SUPERSEDED_STATUS
        asset["distinctness_regeneration"] = {
            "episode": ctx.episode, "against": list(action.get("against") or []),
            "cosine_before": action.get("cosine_before"), "threshold": action.get("threshold"),
            "screen_time": action.get("screen_time"), "kept": action.get("kept"), "at": now()}
        write_json(lib_path, library)
        ctx.say(f"   S3 distinctness: re-designing LOCKED card {cid} (vs {','.join(action.get('against') or [])}, "
                f"cosine {action.get('cosine_before')}, screen {action.get('screen_time')}s vs "
                f"{action.get('kept_screen_time')}s kept) once; later episodes reuse the new card")
        return {"status": "UNLOCKED", "library": str(lib_path), "prompt": str(target), "prompt_source": str(source)}
    except Exception as exc:  # noqa: BLE001 - advisory
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def s3_premodern_period(ctx: Ctx) -> bool:
    """The episode's world is pre-modern (visual_culture_contract.is_premodern_period); False on any error."""
    try:
        if str(ENGINE) not in sys.path:
            sys.path.insert(0, str(ENGINE))
        from tools.visual_culture_contract import is_premodern_period  # noqa: PLC0415
        contract = read_json(ctx.p.contract, {}) or {}
        return is_premodern_period(contract.get("visual_culture_contract"),
                                   dialogue_language=contract.get("dialogue_language"))
    except Exception:  # noqa: BLE001
        return False


def s3_period_recards(ctx: Ctx, subject_ids: list[str]) -> dict[str, list[str]]:
    """{character: forbidden period phrases in its card prompt} -- this episode's prompt, else the earliest episode's
    authored card prompt (a LOCKED card).  Never raises."""
    import character_distinctness as _cd
    out: dict[str, list[str]] = {}
    for cid in subject_ids:
        try:
            source = ctx.p.prompt_dir / f"{ctx.episode}-{cid}.txt"
            if not source.is_file():
                source = s3_card_prompt_source(ctx, cid)
            found = _cd.period_trait_findings(source.read_text(encoding="utf-8")) if source else []
        except Exception:  # noqa: BLE001
            found = []
        if found:
            out[cid] = found
    return out


def s3_character_distinctness(ctx: Ctx, res: StageResult, plan_rows: list[dict[str, Any]], *,
                              library: dict[str, Any] | None = None,
                              embedder: Any = "default") -> dict[str, Any]:
    """Cross-character distinctness of the harvested BASE cards (line owner 2026-11-19, character_distinctness.py).

    Live-action only (anime: InsightFace NOT_APPLICABLE; the identity review's descriptive question records it).
    Every pair of DIFFERENT characters -- this episode's harvested base plates plus characters LOCKED in earlier
    episodes -- is scored with InsightFace; a pair >= 0.38 regenerates the LATER episode-new text-to-image card once
    (policy file + parked plates; the next round's bootstrap plans the new prompt).  A pair already regenerated, or
    with no regenerable card, is accepted and recorded as an advisory.  Never blocks: any error is recorded and S3
    goes on.  Returns the report; ``report["regenerate"]`` non-empty means another round is needed."""
    import character_distinctness as _cd
    p = ctx.p
    out_path = p.identity / f"{ctx.episode}_{_cd.REPORT_SUFFIX}"
    try:
        if ctx_render_style(ctx) == "anime":
            return {"status": "NOT_APPLICABLE", "reason": "render_style=anime: identity review question "
                                                          f"{_cd.ANIME_QUESTION} records it"}
        base_rows = [row for row in plan_rows if isinstance(row, dict) and row.get("kind") == "CHARACTER"
                     and row.get("view") == "FULL_BODY_STANDING" and str(row.get("id") or "").startswith("CHAR-")]
        requirements = read_json(p.asset_requirements, {}) or {}
        cast: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for row in ((requirements.get("assets") or {}).get("characters") or []):
            if isinstance(row, dict) and str(row.get("asset_id") or "").startswith("CHAR-"):
                cast[row["asset_id"]] = _cd.cast_row(row.get("specification") or {}, row["asset_id"])
                order.append(row["asset_id"])
        plates: dict[str, Path] = {}
        regenerable: set[str] = set()
        bootstrap = __import__("bootstrap_identity_cards")
        for row in base_rows:
            plate = bootstrap.base_plate_for(str(row["id"]), p.identity_harvest_dir, ctx.episode)
            if plate is not None:
                plates[str(row["id"])] = plate
                if not row.get("reference_images"):          # text-to-image card: S3 chose the face
                    regenerable.add(str(row["id"]))
        locked = (library if library is not None else load_cross_episode_library(ctx.p.scope))
        for cid, asset in (((locked.get("assets") or {}).get("characters") or {}).items()):
            if cid in plates or not isinstance(asset, dict) or asset.get("status") != "LOCKED":
                continue
            ref = next((a for a in asset.get("artifacts") or [] if isinstance(a, dict)
                        and a.get("canonical_identity_reference") and Path(str(a.get("path") or "")).is_file()), None)
            if ref and cid in cast:
                plates[cid] = Path(str(ref["path"]))
        locked_regenerable: set[str] = set()
        for cid in plates:
            if cid not in order:
                order.append(cid)
            if cid not in {str(r["id"]) for r in base_rows} and s3_locked_card_redesignable(ctx, cid, locked):
                locked_regenerable.add(cid)
        if len(plates) < 2:
            return {"status": "NOT_ENOUGH_CHARACTERS", "characters": sorted(plates)}
        s6_started = s3_s6_started(ctx)
        if s6_started:  # never re-design a card the episode's video already shows
            locked_regenerable = set()
        pair = s3_distinctness_embedder() if embedder == "default" else embedder
        if pair is None:
            report = {"schema": _cd.SCHEMA, "status": "INSIGHTFACE_UNAVAILABLE", "authority": _cd.AUTHORITY}
            write_json(out_path, report)
            return report
        embed, cosine = pair
        embeddings: dict[str, list[list[float]]] = {}
        unmeasured: dict[str, str] = {}
        for cid, plate in plates.items():
            try:
                embeddings[cid] = embed(plate)
            except Exception as exc:  # noqa: BLE001 -- a card without one face is identity QA's business
                unmeasured[cid] = f"{type(exc).__name__}:{str(exc)[:80]}"
        policy = _cd.load_policy(p.prompt_dir)
        # PERIOD_TRAIT_LOCK (device 1101 E24): a pre-modern series regenerates a card whose prompt gave it glasses once
        period = s3_premodern_period(ctx)
        period_recards = s3_period_recards(ctx, [c for c in plates if c in regenerable or c in locked_regenerable]) \
            if period else {}
        report = _cd.evaluate(embeddings, order=[c for c in order if c in plates], cast=cast, policy=policy,
                              regenerable=regenerable, cosine=cosine, unmeasured=unmeasured,
                              locked_regenerable=locked_regenerable, screen_time=s3_screen_time(ctx),
                              period=period, period_recards=period_recards)
        if period_recards:
            report["period_recards"] = period_recards
        report["plates"] = {cid: str(path) for cid, path in plates.items()}
        report["locked_regenerable"] = sorted(locked_regenerable)
        if s6_started:
            report["locked_regeneration_deferred"] = "S6_STARTED: a card shown in this episode's video is kept"
        if report["regenerate"] and not getattr(ctx, "paid_enabled", False):
            # no paid image route this run (dry / paid disabled): never park a plate that cannot be replaced
            report["regenerate_not_applied"] = report["regenerate"]
            report["regenerate"] = []
            report["status"] = "ADVISORY_REGENERATION_NEEDS_PAID_RUN"
        unlocked: list[dict[str, Any]] = []
        for action in [a for a in report["regenerate"] if a.get("unlock_locked")]:
            outcome = s3_unlock_locked_card(ctx, action)
            unlocked.append({"subject_id": action["subject_id"], **outcome})
            if outcome.get("status") != "UNLOCKED":
                report["regenerate"].remove(action)
                report["advisories"].append({"a": action["subject_id"], "b": (action.get("against") or [None])[0],
                                             "cosine": action.get("cosine_before"),
                                             "reason": f"LOCKED_CARD_NOT_REDESIGNED:{outcome.get('status')}"})
        if unlocked:
            report["locked_unlocks"] = unlocked
            report["unlocked_locked"] = [u["subject_id"] for u in unlocked if u.get("status") == "UNLOCKED"]
            if not report["regenerate"]:
                report["status"] = "ADVISORY"
        if report["regenerate"]:
            report["applied"] = _cd.apply_regenerations(report, prompt_dir=p.prompt_dir,
                                                        plates_dir=p.identity_harvest_dir, episode=ctx.episode,
                                                        policy=policy)
            ctx.say("   S3 distinctness: regenerating " + ", ".join(
                f"{r['subject_id']} (period traits: {'/'.join(r.get('period_findings') or [])})"
                if r.get("cosine_before") is None else
                f"{r['subject_id']} (vs {','.join(r['against'])}, cosine {r['cosine_before']:.2f})"
                for r in report["regenerate"]) + " once with a face-differentiation / period prompt")
        history = (read_json(out_path, {}) or {}).get("history") or []
        report["history"] = (history + [{k: report.get(k) for k in ("evaluated_at", "status", "too_similar",
                                                                   "regenerate", "advisories")}])[-8:]
        write_json(out_path, report)
        report["report_path"] = str(out_path)
        res.receipts.append(str(out_path))
        if report.get("too_similar") or report.get("advisories"):  # knowledge base + next episode's identity design
            report["knowledge_events"] = kb_events("record_lookalike_cast", episode=ctx.episode,
                                                   report_path=str(out_path))
        return report
    except Exception as exc:  # noqa: BLE001 -- advisory step, never blocks S3
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


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
    image_provider = image_provider_info()

    res = StageResult(PASS)
    res.steps = []
    res.details = {
        "episode_inputs": {key: value for key, value in inputs.items() if key != "steps"},
        "rights_basis": ctx.rights_declaration,
        "plan": str(p.identity_plan),
        "rounds": [],
        "image_credits_per_task": image_credits,
        "image_provider": image_provider,
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
        # Cost filtering alone is insufficient: the authorizer marks every row
        # in its input READY_TO_SUBMIT, and the submitter POSTs all those rows.
        selected_plan = s3_submission_plan(plan, already, subset)
        selected_plan['deferred_view_rows'] = deferred
        selected_plan['source_plan'] = str(p.identity_plan)
        selected_plan['source_plan_sha256'] = sha256_file(p.identity_plan)
        subset_plan = p.identity / 'character_asset_plan_SUBMISSION.json'
        write_json(subset_plan, selected_plan)
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
        # Check for empty plan on first round, but allow all-reuse episodes
        reused = plan.get("verified_reused_subjects") or []
        if not pending and not reused and round_no == 1:
            res.status = BLOCKED
            res.blockers.append("IDENTITY_PLAN_EMPTY_NOTHING_TO_GENERATE_AND_NOTHING_LOCKED")
            return res
        if not pending and reused and round_no == 1:
            # All-reuse episode: nothing to generate; fall through so the engine's own
            # S3.qa gates decide the verdict (this orchestrator never writes its own PASS).
            res.details["all_reuse_episode"] = True
            res.details["reused_asset_count"] = len(reused)
            ctx.say(f"   S3: all-reuse episode ({len(reused)} verified reused assets, 0 new generation)")

        if not new_rows and not unharvested:
            if not deferred:
                # every plate is on disk: last chance for the cross-character distinctness check
                distinct = s3_character_distinctness(ctx, res, rows)
                round_rec["character_distinctness"] = {k: distinct.get(k) for k in ("status", "regenerate",
                                                                                   "advisories", "report_path")}
                if distinct.get("unlocked_locked"):  # a re-designed LOCKED card is planned like a new one
                    already = locked_subjects(load_cross_episode_library(ctx.p.scope))
                if distinct.get("regenerate"):
                    continue
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
            # studio asset library: archive each downloaded original (inert unless the library is enabled)
            "--studio-archive-project", ctx.p.scope["series_id"],
            "--watch", "--interval", 15,
        ]
        if new_rows:
            planned = image_batch_credits(ctx, len(new_rows))
            total_planned += planned
            ctx.say(f"   round {round_no}: {len(new_rows)} new rows via {image_provider['provider']} = {planned} cr "
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
                # a bound take whose image is already harvested here is reused, never re-POSTed
                "--plates-dir", p.identity_harvest_dir,
            ]
            dry_argv = [
                VENV, ENGINE / "tools/submit_giggle_character_asset_plan.py",
                "--plan", subset_plan,
                "--out", p.identity / f"{ctx.episode}_IDENTITY_PRECHECK.json",
                "--precheck-only",
            ]
            submit_started = time.time()
            status, submit = ctx.paid_step(
                paid_argv, name=f"s3_submit_giggle_character_asset_plan_r{round_no}", sid="S3",
                planned_credits=planned, dry_argv=dry_argv,
                note=(f"round {round_no}. Submitted file is the D-11 materialised copy "
                      f"{auth_plan.name} (authorization_ref = private SUPERVISOR_ORDERS "
                      f"seq={ctx.authority.get('paid_order_seq')} "
                      "order id, provider_post_allowed true).  Rows with reference_images go to "
                      "/api/v1/generation/image-to-image (own base plate or line-owner-supplied source photo), "
                      "rows without go to text-to-image (image_provider=hopsapi: HopsAPI gpt-image-2 "
                      "Img2Img / Txt2Img, references preprocessed + uploaded).  Durable transaction store: "
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
                ctx.say("   next (free, needs the image provider's key, no new POST):")
                ctx.say(f"     {q(harvest_argv)}")
                ctx.planned_commands.append({
                    "stage": "S3", "step": f"s3_harvest_giggle_image_batch_r{round_no}",
                    "planned_credits": 0, "paid_argv": [str(x) for x in harvest_argv],
                    "paid_command": q(harvest_argv),
                    "note": "download only, needs the image provider's key (GIGGLE_API_KEY / HOPSAPI_API_KEY), "
                            "issues no generation POST"})
                if deferred:
                    ctx.say(f"   (dry) {len(deferred)} view rows would be planned in round {round_no + 1} "
                            "once these base plates are harvested")
                break
            if status != PASS:
                # the submitter exits 2 when its credit-statement reconciliation could
                # not bound the charge even though every row was accepted.  Every row
                # SUBMITTED and zero failures = the images exist and the ledger refresh
                # will settle the charge; record it, do not lose the batch.
                # Lab E08 2026-10-29: the child crashed (exit 1, no report written) and the
                # PREVIOUS run's PASS report was harvested as if it were this run's.  Only a report
                # this child wrote, with exit 2 (the submitter's "reconciliation unbounded" exit),
                # zero failures and every submitted row accounted for, is a warning.
                submit_report = s3_fresh_submit_report(p.identity_submit, submit_started)
                results = submit_report.get("results") or []
                submitted_ids = {str(r.get("id")) for r in (read_json(auth_plan, {}) or {}).get(
                    "new_asset_groups") or [] if isinstance(r, dict)}
                accounted = {str(r.get("character_id")) for r in results if r.get("status") == "SUBMITTED"}
                if (submit.get("exit_code") == 2 and results and not submit_report.get("failures")
                        and submitted_ids and submitted_ids <= accounted):
                    round_rec["submit_warning"] = (
                        "CREDIT_RECONCILIATION_UNBOUNDED:"
                        + str((submit_report.get("credit_reconciliation") or {}).get("status")))
                    res.details.setdefault("warnings", []).append(round_rec["submit_warning"])
                else:
                    # Same overwrite loss as S5/S6: a failed identity round can still have
                    # charged part of the batch, and the statement sits under a fixed name.
                    # Archive it before returning, or the next round erases the evidence.
                    round_rec["credit_statement"] = archive_credit_statement(
                        ctx, ctx.p.identity_submit, f"{ctx.run_id}_r{round_no}")
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
        # Cross-character distinctness (line owner 2026-11-19): measured on the base plates as soon as they land
        # (round 1 normally, before the views are generated from them); a too-similar later card is regenerated
        # once, which needs another round.  Advisory otherwise, never a block.
        distinct = s3_character_distinctness(ctx, res, rows)
        round_rec["character_distinctness"] = {k: distinct.get(k) for k in ("status", "regenerate", "advisories",
                                                                           "report_path")}
        if distinct.get("unlocked_locked"):
            already = locked_subjects(load_cross_episode_library(ctx.p.scope))
        if distinct.get("regenerate"):
            continue
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
    if ctx_render_style(ctx) == "anime":  # anime cast distinctness = the identity review's descriptive answers
        res.details["knowledge_events_lookalike_cast"] = kb_events(
            "record_lookalike_cast", episode=ctx.episode,
            report_path=str(p.identity / f"{ctx.episode}_CHARACTER_DISTINCTNESS.json"))
    if admission["status"] == PASS:
        res.details["reference_sheets"] = s3_register_reference_sheets(ctx)
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

def s4_generate_all(ctx: "Ctx", p: Any, todo: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run every character's voice generation concurrently, results in `todo` order.

    Each character is independent: one durable audio transaction per entity, its own
    wav and its own upload receipt.  The registry row is applied by the caller in
    `todo` order because that file is one read-modify-write.
    """
    workers = min(int(getattr(ctx, "max_parallel", 6) or 6), len(todo))
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(s4_generate_one, ctx, p, task) for task in todo]
            return [future.result() for future in futures]
    return [s4_generate_one(ctx, p, task) for task in todo]


def s4_generate_one(ctx: "Ctx", p: Any, task: dict[str, Any]) -> dict[str, Any]:
    """Generate, normalize and upload one character's voice reference.

    Independent per character: the speech provider holds one durable
    transaction per entity, normalization writes that entity's wav and the
    upload writes that entity's receipt.  The registry row is NOT written
    here — the registry is one whole-file read-modify-write, so rows are
    applied in `todo` order by the caller after the pool drains.
    """
    entity = task["entity_id"]
    wav = Path(task["post_generation_normalization"]["target_wav"])
    mp3 = Path(task["request"]["output_mp3"])
    voice_id = str(task["request"].get("voice_id") or "").strip()
    if not voice_id:
        return {"entity": entity, "status": BLOCKED,
                "blockers": [f"VOICE_ID_NOT_SELECTED:{entity}"]}
    safe_entity = re.sub(r"[^A-Za-z0-9._-]+", "_", str(entity)).strip("._")[:48]
    safe_entity = safe_entity or sha256_text(str(entity))[:16]
    scope_id = str(p.scope["scope_id"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", scope_id):
        return {"entity": entity, "status": BLOCKED,
                "blockers": [f"SERIES_SCOPE_ID_UNSAFE_FOR_TRANSACTION_PATH:{scope_id}"]}
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

    # Each task reserves only its own 2 credits.  The reservation is atomic, so
    # concurrent characters cannot jointly overrun the cap; the old serial
    # `2 * remaining` argument assumed later characters were not yet guarded.
    status, step = ctx.paid_step(
        argv, name=f"s4_speech_generate_{entity}", sid="S4",
        planned_credits=2,
        note=(f"Portable Giggle speech provider, 2 credits. "
              f"voice_id={voice_id} ({task['request'].get('voice_name')}).  "
              f"Durable transaction={audio_transaction}; the provider records intent "
              "before its only POST, binds task_id immediately, and resumes without "
              "reposting."))
    steps: list[dict[str, Any]] = [step]
    if status == HARD_STOP:
        return {"entity": entity, "status": HARD_STOP, "steps": steps,
                "blockers": [f"BUDGET_HARD_STOP_S4:{entity}"]}
    if status == DRY:
        return {"entity": entity, "status": DRY, "steps": steps, "dry": True,
                "norm_argv": norm_argv, "upload_argv": upload_argv}
    if status != PASS:
        return {"entity": entity, "status": BLOCKED, "steps": steps,
                "blockers": [f"SPEECH_GENERATE_FAILED:{entity}"]}
    if not mp3.is_file():
        return {"entity": entity, "status": BLOCKED, "steps": steps,
                "blockers": [f"SPEECH_OUTPUT_MISSING:{mp3}"]}
    norm = ctx.run(norm_argv, name=f"s4_normalize_{entity}")
    steps.append(norm)
    if norm["exit_code"] != 0 or not wav.is_file():
        return {"entity": entity, "status": BLOCKED, "steps": steps,
                "blockers": [f"VOICE_NORMALIZATION_FAILED:{entity}"]}
    upload = ctx.run(upload_argv, name=f"s4_upload_{entity}", paid=True)
    steps.append(upload)
    receipt = upload_receipt_fields(read_json(upload_out, {}) or {})
    asset_id = receipt.get("asset_id") or receipt.get("assetId")
    if upload["exit_code"] != 0 or not asset_id:
        return {"entity": entity, "status": BLOCKED, "steps": steps,
                "blockers": [f"VOICE_UPLOAD_FAILED_NO_ASSET_ID:{entity}"]}
    return {"entity": entity, "status": PASS, "steps": steps, "task": task,
            "wav": wav, "receipt": receipt, "receipt_path": str(upload_out)}


# --------------------------------------------------------------------------- #
# S4 / S7 — V.O. narration (tools/voice_over_narration.py)
# --------------------------------------------------------------------------- #
def voice_over_manifest_path(ctx: Any) -> Path:
    return ctx.p.voice / "voice_over" / f"{ctx.episode}_voice_over_manifest.json"


def voice_over_placement_path(ctx: Any) -> Path:
    return ctx.p.assembly / f"{ctx.episode}_voice_over_placement.json"


def editorial_voice_over_lines(editorial: dict[str, Any]) -> list[dict[str, Any]]:
    """Every S2 ``prompt_spec.voice_over`` row, in episode order, with its shot id."""
    rows: list[dict[str, Any]] = []
    for shot in editorial.get("shots") or []:
        for line in (shot.get("prompt_spec") or {}).get("voice_over") or []:
            rows.append({"shot_id": str(shot.get("shot_id")), **line})
    return rows


def voice_over_reference(registry: dict[str, Any], payload_tasks: list[dict[str, Any]],
                         character_id: str) -> dict[str, Any] | None:
    """voice_id / emotion / speed of a V.O. character's LOCKED voice reference."""
    entity = re.sub(r"^CHAR-", "", character_id.strip().upper()).replace("-", "_").lower()
    candidates = {character_id, entity, canonical_voice_entity(entity)}
    row = next((r for r in voice_rows(registry)
                if r.get("status") == "LOCKED_PRODUCTION_READY" and str(r.get("voice_id") or "").strip()
                and (str(r.get("character_id") or "") == character_id
                     or str(r.get("entity_id") or "") in candidates
                     or canonical_voice_entity(str(r.get("entity_id") or "")) in candidates)), None)
    if row is None:
        return None
    task = next((t for t in payload_tasks
                 if str(t.get("character_id") or "") == character_id
                 or str(t.get("entity_id") or "") in candidates
                 or str(t.get("entity_id") or "") == str(row.get("entity_id") or "")), None) or {}
    request = task.get("request") or {}
    return {"entity_id": str(row.get("entity_id")), "voice_id": str(row["voice_id"]),
            "voice_name": row.get("voice_name"),
            "emotion": str(request.get("emotion") or row.get("generation_emotion") or "neutral"),
            "speed": float(request.get("speed") or row.get("generation_speed") or 1.0)}


def voice_over_minimum_recall() -> float:
    """The existing dialogue match threshold (BASIC_DIALOGUE_QA_POLICY rules.minimum_recall)."""
    for path in (RT / "configs/BASIC_DIALOGUE_QA_POLICY.json",
                 RT_TOOLS.parent / "configs/BASIC_DIALOGUE_QA_POLICY.json"):
        value = ((read_json(path, {}) or {}).get("rules") or {}).get("minimum_recall")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.55


def voice_over_asr(wav: Path, text: str, language: str) -> dict[str, Any]:
    """Free faster-whisper check of one V.O. wav (same model/settings/recall as source_video_dialogue_gate)."""
    import source_video_dialogue_gate as _svdg  # noqa: PLC0415 - engine tools/ is on sys.path
    from faster_whisper import WhisperModel  # type: ignore  # noqa: PLC0415
    model = WhisperModel(_whisper_model_name(language), device="cpu", compute_type="int8")
    joiner = " " if language == "en" else _lang.profile(language).joiner

    def _pass(prompt: str | None) -> tuple[str, float]:
        segments, _ = model.transcribe(str(wav), language=language, vad_filter=True, beam_size=5,
                                       initial_prompt=prompt)
        transcript = joiner.join(seg.text.strip() for seg in segments)
        return transcript, round(_svdg.recall(text, transcript, language), 3)

    transcript, recall = _pass(_svdg.transcription_prompt(text, language))
    result = {"transcript": transcript, "recall": recall, "asr_pass": "PROMPTED"}
    if recall < voice_over_minimum_recall():
        # a prompted pass can hallucinate a stock caption ("优优独播剧场——YoYo Television Series Exclusive") over a
        # clean read; one unprompted re-check decides (field fleet 2026-11-06, device …1324 E01 S4)
        plain, plain_recall = _pass(None)
        result["prompted"] = {"transcript": transcript, "recall": recall}
        if plain_recall > recall:
            result.update(transcript=plain, recall=plain_recall, asr_pass="UNPROMPTED_RECHECK")
    return result


def media_seconds(path: Path) -> float | None:
    probe = subprocess.run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=False)
    try:
        return round(float(probe.stdout.strip()), 3)
    except ValueError:
        return None


def s4_voice_over(ctx: Ctx, res: StageResult) -> None:
    """Synthesize every V.O. line after the voice references are LOCKED (S4 PASS requires it).

    One paid speech task per line through ``ctx.paid_step`` (2 credits, budget reservation,
    DRY / HARD_STOP like the references).  The durable transaction path is fixed per line, so a
    re-run resumes the provider without a second POST.  Each wav is normalized, measured and ASR
    checked (free); a recall below the dialogue threshold BLOCKS with no automatic paid retry.
    """
    p = ctx.p
    editorial = read_json(p.editorial, {}) or {}
    lines = editorial_voice_over_lines(editorial)
    if not lines:
        return
    manifest_path = voice_over_manifest_path(ctx)
    out_dir = manifest_path.parent / "lines"
    manifest = read_json(manifest_path, {}) or {}
    done = {(str(r.get("shot_id")), int(r.get("line_index", -1))): r for r in manifest.get("rows") or []}
    registry = read_json(ctx.p.scope["voice_registry"], {}) or {}
    payload_tasks = (read_json(p.speech_payloads, {}) or {}).get("tasks") or []
    units = (read_json(p.contract, {}) or {}).get("audio_contract", {}).get("dialogue_units") or []
    language = ctx_language(ctx)
    scope_id = str(p.scope["scope_id"])
    minimum = voice_over_minimum_recall()
    rows: list[dict[str, Any]] = []
    any_dry = False
    details: list[dict[str, Any]] = []
    for line in lines:
        sid, index, text = line["shot_id"], int(line["line_index"]), str(line["text"])
        text_sha = _vo.text_sha256(text)
        previous = done.get((sid, index))
        if (previous and previous.get("text_sha256") == text_sha and previous.get("wav")
                and sha256_file(Path(previous["wav"])) == previous.get("wav_sha256")):
            rows.append(previous)
            details.append({"shot_id": sid, "line_index": index, "status": "REUSED"})
            continue
        reference = voice_over_reference(registry, payload_tasks, str(line["character_id"]))
        if reference is None:
            res.status = BLOCKED
            res.blockers.append(f"VOICE_OVER_VOICE_NOT_LOCKED:{line['character_id']}")
            return
        unit = next((u for u in units if str(u.get("shot_id")) == sid
                     and str(u.get("speaker_id")) == str(line["character_id"])
                     and _vo.norm_text(u.get("text") or "") == _vo.norm_text(text)), {})
        emotion = str(unit.get("emotion") or reference["emotion"])
        # the text hash is part of the name: an edited line gets a new transaction (one new paid
        # synthesis) instead of colliding with the provider's fingerprint of the old text
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{sid}_{index}_{text_sha[:12]}").strip("._")[:96]
        mp3, wav = out_dir / f"{safe}.mp3", out_dir / f"{safe}.wav"
        transaction = (AUDIO_TRANSACTION_ROOT / scope_id / ctx.episode / "voice_over" / f"{safe}.json").resolve()
        argv = [VENV, PORTABLE_AUDIO_PROVIDER, "speech-generate", text,
                "--voice-id", reference["voice_id"], "--emotion", emotion, "--speed", str(reference["speed"]),
                "--output-dir", out_dir, "--file-name", mp3.name,
                "--poll-interval", "2", "--timeout", "300", "--transaction", transaction, "--paid"]
        norm_argv = [_media.require_ffmpeg(), "-y", "-i", str(mp3), "-vn", "-ac", "1", "-ar", "48000",
                     "-c:a", "pcm_s16le", str(wav)]
        out_dir.mkdir(parents=True, exist_ok=True)
        status, step = ctx.paid_step(
            argv, name=f"s4_voice_over_{safe}", sid="S4", planned_credits=2,
            note=(f"V.O. narration line {sid}#{index} ({line.get('speaker')}), voice_id={reference['voice_id']}; "
                  f"durable transaction={transaction} (resumes without reposting)."))
        res.steps.append(step)
        if status == HARD_STOP:
            res.status = HARD_STOP
            res.blockers.append(f"BUDGET_HARD_STOP_S4_VOICE_OVER:{sid}:{index}")
            return
        if status == DRY:
            any_dry = True
            ctx.planned_commands.append({
                "stage": "S4", "step": f"s4_voice_over_normalize_{safe}", "planned_credits": 0,
                "paid_argv": [str(x) for x in norm_argv], "paid_command": q(norm_argv),
                "note": "ffmpeg mono/48k/pcm_s16le — free, local"})
            continue
        if status != PASS or not mp3.is_file():
            res.status = BLOCKED
            res.blockers.append(f"VOICE_OVER_SPEECH_GENERATE_FAILED:{sid}:{index}")
            return
        norm = ctx.run(norm_argv, name=f"s4_voice_over_normalize_{safe}")
        res.steps.append(norm)
        if norm["exit_code"] != 0 or not wav.is_file():
            res.status = BLOCKED
            res.blockers.append(f"VOICE_OVER_NORMALIZATION_FAILED:{sid}:{index}")
            return
        try:
            check = voice_over_asr(wav, text, language)
        except Exception as exc:  # noqa: BLE001 - a missing ASR is not a pass
            res.status = BLOCKED
            res.blockers.append(f"VOICE_OVER_ASR_UNAVAILABLE:{sid}:{index}:{type(exc).__name__}")
            return
        details.append({"shot_id": sid, "line_index": index, "status": "GENERATED", **check})
        if check["recall"] < minimum:
            res.status = BLOCKED
            res.blockers.append(f"VOICE_OVER_ASR_MISMATCH:{sid}:{index}")
            res.details["voice_over"] = {"manifest": str(manifest_path), "lines": details,
                                         "minimum_recall": minimum}
            return
        row = {"shot_id": sid, "line_index": index, "speaker": line.get("speaker"),
               "character_id": line.get("character_id"), "text": text, "text_sha256": text_sha,
               "wav": str(wav), "wav_sha256": sha256_file(wav),
               "duration_seconds": media_seconds(wav), "transaction": str(transaction),
               "voice_id": reference["voice_id"], "emotion": emotion, "speed": reference["speed"],
               "asr_recall": check["recall"]}
        rows.append(row)
        # persist after every line so an interrupted run keeps what it already paid for
        done[(sid, index)] = row
        write_json(manifest_path, {"schema": _vo.MANIFEST_SCHEMA, "episode": ctx.episode,
                                   "editorial": str(p.editorial), "rows": list(done.values()),
                                   "complete": False, "updated_at": now()})
    res.details["voice_over"] = {"manifest": str(manifest_path), "lines": details, "minimum_recall": minimum}
    if any_dry:
        res.status = DRY
        return
    expected = {(line["shot_id"], int(line["line_index"])): _vo.text_sha256(line["text"]) for line in lines}
    write_json(manifest_path, {"schema": _vo.MANIFEST_SCHEMA, "episode": ctx.episode,
                               "editorial": str(p.editorial), "editorial_sha256": sha256_file(p.editorial),
                               "rows": rows, "complete": True, "updated_at": now()})
    got = {(r["shot_id"], int(r["line_index"])): r.get("text_sha256") for r in rows
           if r.get("wav") and Path(r["wav"]).is_file()}
    if got != expected:
        res.status = BLOCKED
        res.blockers.append("VOICE_OVER_MANIFEST_INCOMPLETE")
        return
    res.receipts.append(str(manifest_path))


def provider_voice_catalog_rows(ctx: Ctx) -> list[dict[str, Any]]:
    """The free provider voice list (list_voices.sh output: {voices: [{voice_id, gender, age, language, ...}]}) when
    one sits next to runtime/voice_catalog.json (voices_available.json / voices.json) or NALU_PROVIDER_VOICE_CATALOG
    names it; [] otherwise (the Japanese / Korean system voices come from voice_gender.SYSTEM_VOICE_GENDER)."""
    base = Path(str(ctx.p.scope["voice_catalog"])).parent
    paths = [Path(v) for v in [os.environ.get("NALU_PROVIDER_VOICE_CATALOG")] if v]
    paths += [base / "voices_available.json", base / "voices.json"]
    for path in paths:
        payload = read_json(path, {}) if path.is_file() else {}
        rows = payload.get("voices") if isinstance(payload, dict) else payload
        if isinstance(rows, list) and rows:
            return [r for r in rows if isinstance(r, dict)]
    return []


def s4_casting_gender_check(ctx: Ctx) -> dict[str, Any]:
    """Casting gender check + auto-recast, before S4 generates or reuses any voice (and so before S6).

    Line owner 2026-11-20, JA-01 E02 VU-020: Rei Taylor (a woman) was cast ``Japanese_OptimisticYouth`` (a young
    man's voice) and every one of her lines came out male.  For each character with a voice_catalog row the
    character's gender (contract character_entities) is compared with the voice's (voice_gender.py: provider catalog
    / system-voice table / voice name, reference F0 as a secondary sign).  A MISMATCH is recast automatically: the
    catalog row gets a voice of the right gender (same language, closest age, unused), a LOCKED registry row of the
    old voice moves to ``superseded_rows`` and this episode's speech transaction of that entity is set aside, so S4
    generates one new reference (2 credits).  REVIEW (F0-only / ambiguous evidence) is reported, never acted on.
    Never blocks: any error is recorded and S4 continues."""
    import voice_gender as _vg
    p = ctx.p
    report_path = p.voice / "voice_gender_check.json"
    try:
        catalog_path = Path(str(p.scope["voice_catalog"]))
        catalog = read_json(catalog_path, {}) or {}
        voices = catalog.get("voices") if isinstance(catalog.get("voices"), dict) else {}
        if not voices:
            return {"status": "NO_VOICE_CATALOG"}
        contract = read_json(p.contract, {}) or {}
        registry_path = Path(str(p.scope["voice_registry"]))
        registry = read_json(registry_path, {}) or {}
        cast = read_json(Path(str(p.scope["voice_cast"])), {}) if p.scope.get("voice_cast") else {}
        plan = _vg.plan_casting(contract.get("character_entities") or [], voices,
                                registry_rows=voice_rows(registry), voice_cast=cast or {},
                                language=ctx_language(ctx), provider_catalog=provider_voice_catalog_rows(ctx))
        plan["episode"] = ctx.episode
        plan["checked_at"] = now()
        applied = []
        for rc in plan["recasts"]:
            key, cid = rc["catalog_key"], rc["character_id"]
            row = voices[key]
            row.update({"voice_id": rc["to_voice_id"], "voice_name": rc["to_voice_name"], "voice_gender": rc["to_gender"],
                        "casting_rationale": (f"[auto-recast {now()[:10]}: {rc['from_voice_id']} is not a "
                                              f"{rc['to_gender']} voice] " + str(row.get("casting_rationale") or ""))[:600]})
            row.setdefault("gender_recasts", []).append({**rc, "episode": ctx.episode, "at": now()})
            moved = []
            roles = registry.get("major_roles")
            if isinstance(roles, list):
                keys = set(_vg.entity_keys(cid))
                keep = []
                for reg in roles:
                    if (isinstance(reg, dict) and (str(reg.get("entity_id")) in keys or str(reg.get("character_id")) in keys)
                            and str(reg.get("voice_id") or reg.get("generation_voice_id") or "") == rc["from_voice_id"]):
                        moved.append({**reg, "superseded_reason": f"VOICE_GENDER_RECAST:{rc['from_voice_id']}->"
                                                                  f"{rc['to_voice_id']}", "superseded_at": now()})
                    else:
                        keep.append(reg)
                if moved:
                    registry["major_roles"] = keep
                    registry.setdefault("superseded_rows", []).extend(moved)
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(key)).strip("._")[:48]
            txn = AUDIO_TRANSACTION_ROOT / str(p.scope["scope_id"]) / ctx.episode / "speech" / f"{safe}.json"
            if txn.is_file():
                aside = txn.parent / "_superseded"
                aside.mkdir(parents=True, exist_ok=True)
                os.replace(txn, aside / f"{txn.stem}.gender_recast_{now().replace(':', '')}.json")
            applied.append({**rc, "registry_rows_superseded": len(moved)})
            ctx.say(f"   VOICE_GENDER_RECAST {cid}: {rc['from_voice_id']} -> {rc['to_voice_id']} "
                    f"({rc['to_gender']}; {rc['source']})")
        for row in plan["rows"]:
            if row["status"] == _vg.REVIEW or (row["status"] == _vg.MISMATCH and not (row.get("recast") or {}).get("to_voice_id")):
                ctx.say(f"   VOICE_GENDER_{row['status']} {row['character_id']}: character {row['character_gender']} "
                        f"({row['character_basis']}), voice {row['voice_id']} {row['voice_gender']} ({row['voice_basis']}), "
                        f"F0 {row.get('f0_hz')}")
        if applied:
            catalog["voices"] = voices
            write_json(catalog_path, catalog)
            if registry:
                registry["updated_at_utc"] = now()
                write_json(registry_path, registry)
            if p.speech_payloads.is_file():  # payloads were compiled from the old voice ids: rebuild (free)
                p.speech_payloads.rename(p.speech_payloads.with_name(
                    p.speech_payloads.name + f".stale_gender_recast_{now().replace(':', '')}"))
        plan["applied"] = applied
        plan["status"] = "RECAST" if applied else "CHECKED"
    except Exception as exc:  # noqa: BLE001 - the check never blocks S4
        plan = {"schema": "nalu.voice_gender_check.v1", "status": "ERROR",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        ctx.say(f"   VOICE_GENDER_CHECK_ERROR {plan['error']}")
    try:
        write_json(report_path, plan)
    except Exception:  # noqa: BLE001
        pass
    return plan


def stage_s4(ctx: Ctx) -> StageResult:
    p = ctx.p
    gender_check = s4_casting_gender_check(ctx)
    catalog_path = Path(str(ctx.p.scope["voice_catalog"]))
    payloads_stale = (p.speech_payloads.is_file() and catalog_path.is_file()
                      and catalog_path.stat().st_mtime > p.speech_payloads.stat().st_mtime)
    if payloads_stale:
        # The catalog was filled/edited after the payloads were compiled (StoryClaw 2026-09-21: a
        # 9/19 payload set compiled from an empty catalog kept reporting VOICE_ID_NOT_SELECTED
        # for a catalog filled two days later).  Payloads are free to rebuild; retire the old set.
        p.speech_payloads.rename(p.speech_payloads.with_name(
            p.speech_payloads.name + f".stale_{now().replace(':', '')}"))
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
             "--language", ctx_language(ctx),
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
    already = locked_voice_entities(registry, require_public_url=episode_video_model(ctx.episode) == "MiniMax-H3")
    todo = [task for task in tasks
            if canonical_voice_entity(str(task.get("entity_id") or "")) not in already]

    res = StageResult(PASS)
    res.details = {
        "voice_gender_check": {k: gender_check.get(k) for k in ("status", "counts", "applied", "error") if k in gender_check},
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
        s4_voice_over(ctx, res)
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
    outcomes = s4_generate_all(ctx, p, todo)

    # Apply outcomes in `todo` order.  Ordering matters twice: journal/console order
    # must not depend on which character finished first, and every registry row is a
    # read-modify-write of ONE file, so rows are written here, never inside the pool.
    for outcome in outcomes:
        entity = outcome["entity"]
        res.steps.extend(outcome.get("steps") or [])
        if outcome.get("dry"):
            any_dry = True
            ctx.say(f"   then (free): {q(outcome['norm_argv'])}")
            ctx.say(f"   then (network write, no credits): {q(outcome['upload_argv'])}")
            ctx.planned_commands.append({
                "stage": "S4", "step": f"s4_normalize_{entity}", "planned_credits": 0,
                "paid_argv": outcome["norm_argv"], "paid_command": q(outcome["norm_argv"]),
                "note": "ffmpeg mono/48k/pcm_s16le — free, local"})
            ctx.planned_commands.append({
                "stage": "S4", "step": f"s4_upload_{entity}", "planned_credits": 0,
                "paid_argv": [str(x) for x in outcome["upload_argv"]],
                "paid_command": q(outcome["upload_argv"]),
                "note": ("upload_giggle_asset.py has NO dry mode and is an unconditional "
                         "network write; it costs no credits and returns asset_id (SD2 "
                         "remote_asset_id), file_url (H3 remote_url) and duration in one call")})
            continue
        if outcome["status"] in (HARD_STOP, BLOCKED):
            res.status = outcome["status"]
            res.blockers.extend(outcome.get("blockers") or [])
            return res
        write_voice_registry_row(ctx, entity, outcome["task"], outcome["wav"], outcome["receipt"])
        res.receipts.append(outcome["receipt_path"])

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
    if res.status == PASS:
        # V.O. narration lines are spoken with the narrator's now-LOCKED voice reference
        s4_voice_over(ctx, res)
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


def _voice_gender_fields(task: dict[str, Any], wav: Path) -> dict[str, Any]:
    """{voice_gender, voice_gender_basis, character_gender, reference_f0_hz} for a freshly locked voice row.
    Best-effort: a failed F0 measurement leaves it out."""
    import voice_gender as _vg
    f0 = None
    try:
        import dialogue_voice_metrics as _dvm  # engine tools/
        samples, sr = _dvm.load_audio(Path(wav))
        f0 = _dvm.estimate_f0_median(samples, sr)
    except Exception:  # noqa: BLE001
        f0 = None
    voice = _vg.voice_gender(task["request"].get("voice_id"), voice_name=task["request"].get("voice_name"), f0=f0)
    out = {"voice_gender": voice.get("gender"), "voice_gender_basis": voice.get("basis"),
           "character_gender": _vg.norm_gender(task.get("character_gender"))}
    if f0:
        out["reference_f0_hz"] = round(float(f0), 2)
    return out


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
        # both gates.  A regenerated (recast) row keeps the id it already had:
        # E10 recast overwrote CHAR-LIULAOTOU with the entity id ``liulaotou`` and
        # the non-plate lock could no longer find the voice.
        "character_id": task.get("character_id") or row.get("character_id") or str(entity),
        "voice_id": task["request"]["voice_id"],
        "voice_name": task["request"].get("voice_name"),
        # casting gender (2026-11-20, JA-01 E02: a woman cast with a young man's system voice): the voice's own
        # gender and its evidence, plus the character's, so every later check can compare them
        **_voice_gender_fields(task, wav),
        "remote_asset_id": receipt.get("asset_id") or receipt.get("assetId"),
        "remote_url": receipt.get("file_url") or receipt.get("fileUrl"),
        "local_reference": str(wav),
        "local_sha256": sha256_file(wav),
        "duration_seconds": receipt.get("duration"),
        "sample_text": task["request"]["text"],
        "language": ctx_language_locale(ctx),
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
def qa_run(ctx: Ctx, argv: list[Any], *, name: str, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run one of this pipeline's QA tools.  Always free, never a paid child."""
    step = (ctx.run([VENV, *argv], name=name, paid=False, cwd=ENGINE, extra_env=extra_env) if extra_env
            else ctx.run([VENV, *argv], name=name, paid=False, cwd=ENGINE))
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


def merge_keyframe_answers(ctx: Ctx, shots: list[str]) -> tuple[Path | None, list[str], list[str]]:
    return merge_review_answers(ctx, "keyframe", shots)


def merge_review_answers(ctx: Ctx, kind: str, shots: list[str],
                         expected_sha: dict[str, str] | None = None) -> tuple[Path | None, list[str], list[str]]:
    """One merged answer file covering ``shots``, built from the submitted reviews that touched them.

    ``latest_submitted_review`` returns only the NEWEST review of a kind, and the derived-Q1 branch
    used to decide "is this still answered?" from that single review.  Continuity-derived openers are
    reviewed one frame per request, so once two derived units are pending the newest review covers
    only the other one and each frame looks unanswered forever: E11 alternated
    S19-03 → S19-03 → S05-06 → S05-06, never reaching the Q1 build where the line owner's
    acceptance is applied (2026-10-11, order seq=29 already recorded).

    This gathers, per still, the newest valid submitted review whose media sha still matches what is
    on disk — the same staleness rule ``latest_submitted_review`` applies — and writes them as one
    review file the builder can materialise in a single pass.  Returns
    (merged_path, covered_shots, still_missing); nothing is written when a still is uncovered, so
    the caller keeps asking for a real review instead of building on absent answers.
    """
    directory = REVIEWS_ROOT / ctx.episode
    if not directory.is_dir():
        return None, [], list(shots)
    wanted = set(shots)
    picked: dict[str, dict[str, Any]] = {}
    source_files: list[str] = []
    source_sha: list[str] = []
    base: dict[str, Any] = {}
    for path in sorted(directory.glob("*_submitted.json"), reverse=True):
        payload = read_json(path)
        if (not isinstance(payload, dict) or payload.get("kind") != kind
                or (payload.get("validation") or {}).get("status") != "PASS"
                or str(payload.get("reviewer") or "") != REVIEWER_ID):
            continue
        if not base:
            base = payload
        for item in payload.get("items") or []:
            item_id = str(item.get("item_id"))
            if item_id not in wanted or item_id in picked:
                continue
            media = (item.get("request_item") or {}).get("media") or [{}]
            declared, media_path = media[0].get("sha256"), media[0].get("path")
            if not media_path or declared != sha256_file(Path(media_path)):
                continue  # a regenerated frame invalidates the review that judged the old bytes
            if expected_sha and expected_sha.get(item_id) and declared != expected_sha[item_id]:
                continue  # the reviewer looked at other bytes than the start frame admitted now
            picked[item_id] = item
            source_files.append(str(path))
            source_sha.append(sha256_file(path))
    missing = sorted(wanted - set(picked))
    if missing or not picked:
        return None, sorted(picked), missing
    merged = dict(base)
    merged["items"] = [picked[s] for s in sorted(picked)]
    merged["reviewer"] = REVIEWER_ID
    merged["review_method"] = base.get("review_method") or "CLAUDE_VLM_STRUCTURED_REVIEW"
    merged["reviewed_at"] = max(str((picked[s].get("reviewed_at") or "")) for s in picked)
    merged["_merged_from"] = {"reviews": sorted(set(source_files)), "sha256": source_sha,
                              "note": "one review file per still, merged so the Q1 builder can "
                                      "materialise a pending derived set in a single pass"}
    merged_path = REVIEWS_ROOT / ctx.episode / f"{ctx.episode}-{kind}-merged-{now().replace(':', '')}.json"
    write_json(merged_path, merged)
    return merged_path, sorted(picked), []


def request_review(ctx: Ctx, res: StageResult, kind: str, *, sub_stage: str,
                   note: str = "", items: list[str] | None = None,
                   skip_when_empty: bool = False) -> dict[str, Any]:
    """Write a review request, mark the stage REVIEW_REQUIRED, and say how to answer.

    ``skip_when_empty``: an episode whose every identity subject is
    REUSED_FROM_PRIOR_LIBRARY generates no plate of its own, so the request has no
    items — and a 0-item review is a request nobody can answer (``validate_answers``
    rejects an empty item list with ``answer_items_missing``), which would deadlock
    the stage forever.  With this flag the request is still written as evidence, but
    the stage is NOT marked REVIEW_REQUIRED; the caller continues to the reuse lock.
    """
    argv: list[Any] = [VLM_PROTOCOL, "request", "--kind", kind, "--episode", ctx.episode]
    if items:
        argv += ["--items", json.dumps(sorted(items))]
    step = qa_run(ctx, argv, name=f"{sub_stage}_review_request")
    res.steps.append(step)
    payload = qa_json(step)
    request_path = payload.get("request")
    detail = {
        "sub_stage": sub_stage,
        "kind": kind,
        "reviewer": REVIEWER_ID,
        "review_request": request_path,
        "review_request_sha256": payload.get("request_sha256"),
        "items": payload.get("items"),
        "media_missing": payload.get("media_missing"),
        "note": note,
    }
    if skip_when_empty and int(payload.get("items") or 0) == 0:
        detail["status"] = "NOT_REQUIRED_NO_SUBJECT"
        detail["reason"] = (
            "every requirement row for this kind is REUSED_FROM_PRIOR_LIBRARY, so this "
            "episode generates no plate and there is no subject for a reviewer to look at; "
            "the prior LOCKED rows (with their own recorded reviews) are copied into this "
            "episode's library by library_lock_non_plate and re-checked against the files' "
            "sha256.  A 0-item review is never submitted.")
        detail["how_to_answer"] = []
        res.receipts.append(str(request_path) if request_path else "")
        ctx.say(f"   {sub_stage}: no review required — the {kind} request has 0 items "
                "(every subject reused from the prior library)")
        return detail
    detail["status"] = REVIEW_REQUIRED
    detail["how_to_answer"] = [
        f"{VENV} {VLM_PROTOCOL} example-answers --request {request_path}",
        "open every media path in the request, answer every question of every "
        "item with an enumerated value, write an observation of >=20 chars and "
        "list every defect",
        f"{VENV} {VLM_PROTOCOL} submit --request {request_path} --answers <answers.json>",
        f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} run --episode {ctx.episode} "
        f"--from {sub_stage.split('.')[0].upper()}",
    ]
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
    # An all-reuse episode (every identity requirement REUSED_FROM_PRIOR_LIBRARY, nothing new to generate)
    # has no episode-local plates by design: let it reach the no-reviewable-subject path below, where the
    # prior LOCKED rows are copied and byte-checked by the non-plate lock and the engine gate.
    _plan_now = read_json(ctx.p.identity_plan, {}) or {}
    all_reuse = (not plates and bool(_plan_now.get("verified_reused_subjects"))
                 and not (_plan_now.get("new_asset_groups") or []))
    detail["all_reuse_episode"] = all_reuse
    if not plates and not all_reuse:
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
        requested = request_review(ctx, res, "identity", sub_stage="S3.qa",
                                   note="identity plates changed or were never reviewed",
                                   skip_when_empty=True)
        if requested.get("status") == REVIEW_REQUIRED:
            detail.update(requested)
            write_json(p.identity_admission, {
                "schema": "nalu.identity_qa_route_status.v1", "episode": ctx.episode,
                "recorded_at": now(), "recorded_by": TOOL_ID, **detail})
            res.receipts.append(str(p.identity_admission))
            return detail
        # No reviewable subject: every identity requirement is REUSED_FROM_PRIOR_LIBRARY.
        # Nothing to review and nothing to lock here — the prior LOCKED rows are copied
        # by library_lock_non_plate below and the engine gate re-checks their bytes.
        detail["review"] = requested
        detail["status"] = PASS
        # fall through to the non-plate lock + registry rebuild below, skipping the
        # review-driven lock step, which has nothing to materialise.
        review_path, review = None, None

    if review_path is not None:
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
             "--language", ctx_language(ctx),
             "--dry-run"],
            name="s3_qa_prepare_speech_payloads")
        res.steps.append(prep)
        if prep.get("exit_code") != 0 or not p.speech_payloads.is_file():
            detail["status"] = BLOCKED
            detail.setdefault("blockers", []).append(
                f"SPEECH_PAYLOAD_PREP_FAILED:exit={prep.get('exit_code')}:{prep.get('log')}")
    non_plate_step = qa_run(ctx, [RT_TOOLS / "library_lock_non_plate.py", "lock",
                                  "--episode", ctx.episode,
                                  "--rights-basis", ctx.rights_basis,
                                  "--report", p.identity / f"{ctx.episode}_NON_PLATE_LOCK.json"],
                            name="s3_qa_non_plate_library_lock")
    res.steps.append(non_plate_step)
    detail["non_plate_lock"] = qa_json(non_plate_step)
    # FAIL (exit 2) is the normal pre-S4 outcome — voice rows lock after S4.  A crash is not:
    # E10 (2026-09-29) the payload prep had failed silently (duplicate voice_id in the catalog),
    # the lock died on the missing payload file, no reused character was merged into the
    # episode library, and S5 later refused every keyframe with "unverified character identity".
    if non_plate_step.get("exit_code") not in (0, 2) or not detail["non_plate_lock"]:
        detail["status"] = BLOCKED
        detail.setdefault("blockers", []).append(
            f"NON_PLATE_LIBRARY_LOCK_CRASHED:exit={non_plate_step.get('exit_code')}:{non_plate_step.get('log')}")
    # Rebuild after the non-plate lock so reused characters from a previous
    # episode in the same private series scope remain resolvable.
    registry_step = qa_run(ctx, [IDENTITY_QA_LOCK, "registry", "--episode", ctx.episode],
                           name="s3_qa_character_registry_rebuild")
    res.steps.append(registry_step)
    detail["character_registry_rebuild"] = qa_json(registry_step)
    # E10 (2026-09-29): with no locked character in the library the rebuild writes nothing and the
    # previous episode's registry silently stays in force (two villagers and 陆文晖 had no identity
    # samples at Q1).  An episode that requires characters must not pass S3 that way.
    required_characters = ((read_json(p.asset_requirements, {}) or {}).get("assets") or {}).get("characters") or []
    if (detail["character_registry_rebuild"] or {}).get("status") != "WRITTEN" and required_characters:
        detail["status"] = BLOCKED
        detail.setdefault("blockers", []).append(
            "CHARACTER_REGISTRY_NOT_REBUILT:"
            + str((detail["character_registry_rebuild"] or {}).get("status") or f"exit={registry_step.get('exit_code')}"))
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
                             "--report", p.identity_library_gate,
                             "--voice-language", ctx_language_locale(ctx)],
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
    if ctx_render_style(ctx) == "anime":  # render_style.py: identity is the VLM review, InsightFace NOT_APPLICABLE
        detail["objective_method"] = "VLM_ANIME_CHARACTER_CONSISTENCY_V1"
        detail["render_style"] = "anime"
    elif not insight:
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
def keyframe_needs_post(ctx: Ctx, index: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Which keyframe tasks a paid S5 must POST, and which are already done.

    The third instance of D-46, after S3's round re-entry and S6's clip-on-disk rule.  E11
    (2026-10-09): the 50-keyframe batch was paid for and harvested, the keyframes on disk were
    reviewed, and a later free rebuild moved the prompt bytes of all 56 units; S5 — unlike S6 —
    had no rule excluding work that is already done, so the next paid S5 would have re-POSTed all
    50 (550 credits) to re-render images Q1 had just approved.

    Three cases, in this order:

    * Q1 reviewed this shot and admitted the image now on disk -> done.
    * Q1 reviewed this shot and did not admit it (REJECT / a gate FAIL) -> POST; this is the
      reroll the review actually asked for.  The row binds the sha it judged, so an image that
      was re-rendered after the review also lands here.
    * Q1 has no row for this shot -> it is not a shot Q1 reviews (the mid-unit keyframes: Q1
      covers the unit-start stills).  POST only when nothing is on disk; an image generated by an
      earlier paid batch is complete, and re-rendering it would produce another still that the
      same review still does not cover.

    Returns (task_keys_needing_a_post, task_keys_already_done).
    """
    p, need, done = ctx.p, [], []
    admitted: dict[str, str] = {}
    reviewed: set[str] = set()
    for row in index.get("results") or []:
        item = str(row.get("item_id") or "")
        if not item:
            continue
        reviewed.add(item)
        if (row.get("status") in ("PASS", "ADMITTED", "ADMITTED_BY_LINE_OWNER_ORDER")
                or row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT"):
            sha = str(row.get("asset_sha256") or "")
            if sha:
                admitted[item] = sha
    for task in (read_json(p.keyframe_manifest, {}) or {}).get("tasks") or []:
        key = str(task.get("task_key") or "")
        shot = str(task.get("shot_id") or task.get("unit_id") or "")
        name = task.get("output_contract", {}).get("expected_output_path")
        dest = Path(name) if name else p.keyframes / f"{shot}-keyframe-v1.png"
        if not dest.is_absolute():
            dest = ENGINE / dest
        versions = sorted(p.keyframes.glob(f"{shot}-keyframe-v*.png"))
        on_disk = {sha256_file(path) for path in ([dest] + versions) if path.is_file()}
        if shot in reviewed:
            # Q1 judged this shot: the admitted sha must be the image on disk now.
            if admitted.get(shot) and admitted[shot] in on_disk:
                done.append(key)
            else:
                need.append(key)
        elif on_disk:
            # not a Q1-reviewed shot, but an earlier paid batch produced it
            done.append(key)
        else:
            need.append(key)
    return need, done


def s5_keyframes_to_post(ctx: Ctx, q1_index: Path) -> tuple[list[str], list[str]]:
    """keyframe_needs_post over the Q1 index on disk, after the line-owner acceptance orders are applied to it.

    Device ...1101 E15 (2026-11-17): Q1 failed five stills on CHARACTER-IDENTITY-ADMISSION and the default
    acceptance orders were recorded for those exact images (seq 432-436).  The order overlay only ran in
    s5_q1, after the paid submit, so the next S5 entry read the raw FAIL rows as "re-roll these five", tried to
    POST them and died in the submitter (KEYFRAME_SUBMIT_FAILED) before the overlay was ever reached, while S6
    refused the units on Q1_START_FRAME_NOT_ADMITTED.  An accepted still is not re-rendered: the overlay
    (free, sha-bound, source-receipted orders only) runs first, and a row without a matching order still
    means a POST."""
    index = read_json(q1_index, {}) or {}
    if any(row.get("status") != "PASS" and row.get("downstream_status") != "ADMITTED_FOR_VIDEO_SUBMIT"
           for row in index.get("results") or []):
        accepted = apply_line_owner_q1_acceptance(ctx, index, q1_index).get("accepted_unit_ids") or []
        if accepted:
            ctx.say(f"   S5: {len(accepted)} Q1-rejected keyframe(s) are accepted by a line-owner order bound to "
                    f"the current image and are not re-rendered: {accepted}")
    return keyframe_needs_post(ctx, index)


def s5_unlocked_identity_assets(tasks: list[dict[str, Any]], needs_post: list[str]) -> list[str]:
    """Identity / prop assets a keyframe that still needs a POST binds, but the asset library has not locked.

    Device ...0030 E19 (2026-11-16): the script was revised after S3 had passed and the new text added a
    prop.  S3 has no input fingerprint, so it stayed SKIPPED_ALREADY_PASS; the keyframe manifest bound the
    prop as PENDING_ASSET_LIBRARY_ARTIFACT and S5 then died in the stamper and the submitter on the awaited
    file, with no route back to S3 through the paid entry.  Only tasks that are about to be POSTed count:
    a keyframe already admitted at its current image is not touched by a binding that went pending later.
    """
    wanted = set(needs_post)
    return sorted({str(row.get("entity_id") or "")
                   for task in tasks if str(task.get("task_key") or "") in wanted
                   for row in (task.get("pending_bindings") or [])
                   if isinstance(row, dict) and row.get("binding_status") == "PENDING_ASSET_LIBRARY_ARTIFACT"}
                  - {""})


def s5_q1_not_all_admitted(ctx: Ctx) -> bool:
    """A later Q1 review that rejected keyframes must re-open a passed S5 (lab E11: an honest re-review
    rejected 16/27 keyframes but S5 still reported SKIPPED_ALREADY_PASS from the earlier stale review)."""
    q1 = read_json(ctx.p.preprod / "reports/qa/q1" / f"{ctx.episode}_KEYFRAME_Q1_INDEX.json", {}) or {}
    return bool(q1) and q1.get("status") not in (None, "ALL_ADMITTED")


def s5_keyframes_missing(ctx: Ctx) -> list[str]:
    """Planned keyframe prompts whose image is not on disk (a §4 controlled redo parks the rejected one).

    CAMERA_GRAMMAR_V1: plus the own keyframe of a tail-derived unit whose tail start frame was rejected
    (start_frame_source OWN_KEYFRAME_TAIL_REJECTED) — its prompt is only written by the next build."""
    p = ctx.p
    missing = [prompt.name for prompt in sorted((p.preprod / "prompts" / "keyframes").glob("*-KEYFRAME-V1.txt"))
               if not (p.keyframes / prompt.name.replace("-KEYFRAME-V1.txt", "-keyframe-v1.png")).is_file()]
    decisions = start_frame_source_decisions(ctx)
    if decisions:
        derived = continuity_derived_units(ctx)
        for uid, row in sorted(decisions.items()):
            info = derived.get(uid)
            name = f"{(info or {}).get('first_shot_id')}-KEYFRAME-V1.txt"
            if (info and row.get("start_frame_source") == START_FRAME_OWN and not info["keyframe_path"].is_file()
                    and not (p.video_media / f"{uid}.mp4").is_file() and name not in missing):
                missing.append(name)
    return missing


def stage_s5(ctx: Ctx) -> StageResult:
    p = ctx.p
    # Plan §4: the zero-credit previs gate runs BEFORE any manifest is built and
    # before any POST.  A machine failure there is an objective contract
    # conflict; paying to render it would be paying twice.
    previs = previs_gate(ctx, "S5")
    if previs.get("blocked"):
        res = StageResult(BLOCKED, previs_gate=previs)
        res.blockers = [f"PREVIS_MACHINE_FAILURE:{row.get('code')}:{row.get('ref')}"
                        for row in previs.get("machine_failures") or []] or ["PREVIS_BLOCKED"]
        res.receipts = [previs["receipt"]] if previs.get("receipt") else []
        return res
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
    # ...but only while every keyframe the episode plans is still on disk: the §4 controlled redo parks a
    # rejected keyframe and reruns S5, which must then render the missing image instead of reusing the
    # stale ALL_ADMITTED index (urban lab E02 2026-10-23: a parked keyframe was never regenerated).
    keyframe_missing = s5_keyframes_missing(ctx)
    # The anchor plan is the authority on which shots need a keyframe: a planned anchor whose image is
    # absent (E12 S18-02, 2026-10-30: VU-051's own start frame authored in the builder, prompt never
    # written because S5 kept short-circuiting on a stale ALL_ADMITTED index) must send S5 through the
    # manifest build, where D-46 then POSTs only that image.
    anchor_missing = [str(x) for x in ((read_json(p.anchor_plan, {}) or {}).get("missing_anchor_shot_ids") or [])]
    if anchor_missing:
        keyframe_missing = list(keyframe_missing) + [f"{sid}-KEYFRAME-V1.txt" for sid in anchor_missing
                                                      if f"{sid}-KEYFRAME-V1.txt" not in keyframe_missing]
    if (q1.get("status") == "ALL_ADMITTED" and p.anchor_plan.is_file()
            and int(q1.get("unit_count") or 0) > 0 and not keyframe_missing
            and not redo_keyframes_unadmitted(ctx)):
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
        # SCENE_LOCATION_STILL_V1: a location still still missing is made here too (free when none is)
        res.details["scene_location_stills"] = s5_scene_location_stills(ctx, res)
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
        "--image-resolution", ACTIVE_IMAGE_RESOLUTION,   # registry policy (seq=56: 1K)
        "--precheck-only",
    ]
    # Provider reference exclusion (device …1324 E01, 2026-11-06): a declared non-identity reference the
    # provider deterministically refuses is kept as authority but not transmitted.  Absent = unchanged argv.
    exclusions = provider_reference_exclusions_path(ctx)
    if exclusions.is_file():
        build_argv += ["--provider-reference-exclusions", exclusions]
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

    # 1c) review binding (PROVIDER_REQUEST_REVIEW_BINDING_V1, enforced from E14): stamp reviewed_request_sha256
    # on every task whose keyframe prompt the registered whole-batch gate reviewed; the rest stay unstamped
    # and the submitter refuses them (per task, before any intent record).
    _batch_manifest = p.preprod / f"{ctx.episode}_PROMPT_BATCH_V1.json"
    _batch_report = p.preprod / "reports" / f"{ctx.episode}_PROMPT_BATCH_REGISTER.json"
    if _batch_manifest.is_file() and _batch_report.is_file():
        stamp_step = ctx.run([VENV, RT_TOOLS / "stamp_reviewed_keyframe_requests.py",
                              "--episode", ctx.episode, "--manifest", p.keyframe_manifest,
                              "--batch-manifest", _batch_manifest, "--register-report", _batch_report],
                             name="s5_stamp_reviewed_keyframe_requests")
        res.steps.append(stamp_step)

    # 2) D-11 paid authorisation, then the paid submit of the MATERIALISED manifest.
    # D-46 for S5: authorise a POST only for shots with no admitted keyframe of the CURRENT image.
    # S6 excludes tasks whose clip is on disk; S5 had no such rule, so every prompt byte that moved
    # in a free rebuild turned all 50 tasks into "new" ones.  See keyframe_needs_post().
    needs_post, keyframes_done = s5_keyframes_to_post(ctx, q1_index)
    if keyframes_done and needs_post:
        ctx.say(f"   D-46: {len(keyframes_done)} keyframe task(s) already admitted at the current "
                f"image sha and are excluded from the authorised copy; "
                f"{len(needs_post)} still need a POST: {needs_post}")
    res.details["d46_needs_post"] = needs_post
    res.details["d46_already_admitted"] = keyframes_done
    unlocked_assets = s5_unlocked_identity_assets(tasks, needs_post)
    if unlocked_assets:
        # Free, before any authorisation or POST: the submitter would refuse these tasks on the awaited
        # file anyway.  Re-open S3 so the paid entry can produce and lock the asset (rounds + D-46 there
        # POST only what the library does not hold yet).
        ctx.stage_state("S3")["reopen_required"] = {"by": "S5", "at": now(), "assets": unlocked_assets}
        ctx.save_state()
        res.status = BLOCKED
        res.blockers.append("IDENTITY_ASSET_NOT_LOCKED:" + ",".join(unlocked_assets))
        res.details["unlocked_identity_assets"] = unlocked_assets
        res.details["hint"] = (f"S3 is re-opened: run paid_stage.sh {ctx.episode} S3 S5 so S3 generates and "
                               "locks these assets (only the missing ones are POSTed), then S5 continues.")
        return res
    planned = ctx.planned_credits("S5")
    res.details["image_provider"] = image_provider_info()
    if res.details["image_provider"]["provider"] == "hopsapi":
        # HopsAPI gpt-image-2 (owner 2026-10-30): exactly the images this run will POST, at the
        # configurable per-image planning rate, rounded up.  The cost plan's figure is Giggle-priced.
        planned = image_batch_credits(ctx, len(needs_post))
    elif keyframes_done and needs_post:
        # a partial redo plans only the images it will POST, not the whole-episode default estimate
        planned = min(planned, image_batch_credits(ctx, len(needs_post)))
    if not needs_post:
        # Nothing to generate.  Do not materialise authority, do not POST, do not harvest — go
        # straight to the Q1 admission tail, which is what decides whether S5 is done.
        ctx.say("   D-46: every keyframe at the current image sha is already admitted — "
                "no POST, no spend; going straight to Q1")
        return s5_finish_q1(ctx, res)
    auth_status, auth_manifest, auth = materialize_paid_authorization(
        ctx, res, sid="S5", target=p.keyframe_manifest, is_plan=False,
        task_keys=(needs_post if (keyframes_done and needs_post) else None),
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
    # D-46 narrows the AUTHORISED copy (only the needed tasks get provider_post_allowed and the
    # manifest's maximum_new_submissions), but the image submitter selects every task in the file
    # unless told otherwise, and then refuses: "maximum_new_submissions is below the selected task
    # count" (E11 2026-10-10, before any POST).  The video submitter skips unauthorised tasks on
    # its own; this one needs the same selection passed explicitly.
    if keyframes_done and needs_post:
        for key in needs_post:
            paid_argv += ["--task-key", key]
    dry_argv = [VENV, ENGINE / "tools/submit_giggle_image_manifest.py",
                "--manifest", p.keyframe_manifest,
                "--out", p.preprod_reports / f"{ctx.episode}_KEYFRAME_PRECHECK.json",
                "--precheck-only"]
    submit_started = time.time() - 1  # mtime granularity
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
        ctx.say("   then (needs the image provider's key, no new POST, no dry mode exists):")
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
            harvest_status = read_json(p.keyframe_harvest_status, {}) or {}
            if harvest_status.get("provider_error_424_count"):
                rows = harvest_status.get("results") or []
                rejected = [str(row.get("task_key")) for row in rows
                            if row.get("failure_class") == "HOPSAPI_PROVIDER_ERROR_424"]
                if any(row.get("remote_status") == "completed" for row in rows):
                    # other tasks completed in the same batch: the 424s are those tasks' content /
                    # parameter rejections (device …1324 E01), rewrite their prompts -- no cooldown
                    res.blockers.append("HOPSAPI_IMAGE_TASK_REJECTED:" + ",".join(rejected))
                    res.details["provider_rejected_tasks"] = rejected
                else:
                    # uncharged upstream 424s: provider-side, rerun the same stage after the cooldown
                    res.blockers.append("HOPSAPI_IMAGE_PROVIDER_OUTAGE")
            return res
        rename = apply_keyframe_renames(ctx, manifest)
        res.details["deterministic_rename"] = rename
        if rename.get("missing"):
            res.status = BLOCKED
            res.blockers.append("KEYFRAME_RENAME_SOURCE_MISSING")
            return res
    else:
        # E10 (2026-09-29) fixed this for S6 and it reproduced on S5 (nalu E12, 2026-10-18):
        # submit_giggle_image_manifest.py writes its batch window statement next to the report
        # under a FIXED name whenever it is not a precheck, including the BLOCKED path where some
        # tasks genuinely charged.  Archiving only on PASS let the next round's statement overwrite
        # that evidence before nalu_budget_ledger.py ever globbed it, so recorded spend silently
        # dropped.  Archive on every outcome that has a statement (K054/K106).
        res.details["credit_statement"] = archive_credit_statement(
            ctx, ctx.p.keyframe_submit, ctx.run_id)
        res.status = BLOCKED
        res.blockers.append("KEYFRAME_SUBMIT_FAILED")
        submit_report = read_json(p.keyframe_submit, {}) or {}
        outage = submit_report.get("provider_outage")
        if outage:
            res.blockers.append("HOPSAPI_IMAGE_PROVIDER_OUTAGE")
            res.details["provider_outage"] = outage
        rejected = submit_report.get("provider_rejected_tasks") or []
        if rejected:
            # a canary 424 while a different task passed: per-task rejection, rewrite that prompt
            res.blockers.append("HOPSAPI_IMAGE_TASK_REJECTED:" + ",".join(str(row.get("task_key")) for row in rejected))
            res.details["provider_rejected_tasks"] = rejected
            res.details["canary_rotation"] = submit_report.get("canary_rotation")
        harvest_bound_after_failed_submit(ctx, res, submit, submit_report, harvest_argv, submit_started)
        return res

    # 4) S5.q1 — keyframe Q1 admission (D-4)
    return s5_finish_q1(ctx, res)


def bound_rows_of_failed_submit(submit_report: dict[str, Any]) -> list[str]:
    """Task keys a failed image submit left bound at the provider and still worth polling.

    A row counts when it carries a task id and the same report does not list that task as refused
    (a refused task's id is already terminal and uncharged).
    """
    refused = {str(row.get("task_key")) for key in ("provider_rejected_tasks", "failures")
               for row in (submit_report.get(key) or []) if isinstance(row, dict)}
    return [str(row.get("task_key")) for row in (submit_report.get("results") or [])
            if isinstance(row, dict) and row.get("task_id") and str(row.get("task_key")) not in refused]


def harvest_bound_after_failed_submit(ctx: Ctx, res: StageResult, submit: dict[str, Any],
                                      submit_report: dict[str, Any], harvest_argv: list[Any],
                                      submit_started: float) -> list[str]:
    """Poll the tasks a failed keyframe submit left bound, so a refused task cannot freeze the rest.

    Device ...0334 E05 S6 (2026-11-15): two keyframes were refused at POST three rounds running, so
    the submit failed each time and the thirteen tasks bound in the same batch were never polled --
    nothing could finish until every task passed in one round.  Query-only: no POST, the stage
    stays BLOCKED on the submit and the rename waits for a full batch; next round the submitter
    recovers the settled tasks and re-POSTs only the ones the provider failed.

    Exit 2 with a report written by this very run is the submitter's own FAIL verdict.  An
    authority refusal, a timeout or a crash leaves an older report behind, which is not polled.
    """
    report_path = ctx.p.keyframe_submit
    fresh = (submit.get("exit_code") == 2 and report_path.is_file()
             and report_path.stat().st_mtime >= submit_started)
    bound = bound_rows_of_failed_submit(submit_report) if fresh else []
    if bound:
        harvest = ctx.run(harvest_argv, name="s5_harvest_bound_after_failed_submit", paid=True)
        res.steps.append(harvest)
        res.details["bound_harvest_after_failed_submit"] = {
            "bound_task_keys": bound, "exit_code": harvest["exit_code"]}
    return bound


def materialise_monologue_reuse_keyframes(ctx: Ctx) -> list[dict[str, Any]]:
    """CAMERA_GRAMMAR_V1 monologue groups (owner 2026-11-01, lab E12 long take): a speaker's take that continues
    after a cutaway reuses the earlier take's keyframe (build_keyframe_manifest MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE,
    no paid image).  Copy the source keyframe's bytes to ``<first shot>-keyframe-v1.png`` -- again whenever the
    source image changed (a Q1 redo) -- with a sidecar naming the source.  Nothing to do on other episodes."""
    report = read_json(ctx.p.keyframe_manifest_report, {}) or {}
    rows = []
    for row in report.get("decision_table") or []:
        # EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME (same setup, same cast/wardrobe/entry state) was declared with a
        # COPY_EXACT_SHA_BYTES materialisation but never copied; a unit whose tail start frame S6 rejects then
        # needed its own keyframe and found none (lab 化神 E04 VU-028).  Copy those too, from the SOURCE keyframe.
        if row.get("reuse_mode") not in ("MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE", "EXACT_SHA_REUSE_OF_EARLIER_KEYFRAME"):
            continue
        shot, source = str(row.get("shot_id") or ""), str(row.get("reuse_source") or "")
        src = ctx.p.keyframes / f"{source}-keyframe-v1.png"
        dst = ctx.p.keyframes / f"{shot}-keyframe-v1.png"
        side_path = dst.with_suffix(".monologue_reuse.json")
        if not src.is_file():
            rows.append({"shot_id": shot, "status": "SOURCE_NOT_YET_ON_DISK", "source_shot_id": source}); continue
        src_sha = sha256_file(src)
        side = read_json(side_path, {}) or {}
        if dst.is_file() and side.get("source_sha256") == src_sha and sha256_file(dst) == src_sha:
            rows.append({"shot_id": shot, "status": "ALREADY_PRESENT", "path": str(dst)}); continue
        shutil.copyfile(src, dst)
        write_json(side_path, {"schema": "nalu.monologue_keyframe_reuse.v1", "shot_id": shot,
                               "unit_id": row.get("video_unit_id"), "source_shot_id": source,
                               "source_unit_id": row.get("reuse_source_unit_id"), "source_path": str(src),
                               "source_sha256": src_sha, "sha256": sha256_file(dst), "materialised_at": now(),
                               "recorded_by": TOOL_ID,
                               "reuse_mode": row.get("reuse_mode"),
                               "note": "exact keyframe reuse from the same camera setup (monologue continuation or "
                                       "production_efficiency exact-SHA reuse)"})
        rows.append({"shot_id": shot, "status": "MATERIALISED", "path": str(dst), "sha256": src_sha})
    return rows


def s5_finish_q1(ctx: Ctx, res: StageResult) -> StageResult:
    """S5's tail: Q1 admission, then the start-frame receipts.

    Split out of stage_s5 so the D-46 no-POST path reaches it without passing through the paid
    submit and its harvest.  First the monologue keyframe reuse copies (CAMERA_GRAMMAR_V1, free).
    """
    reused = materialise_monologue_reuse_keyframes(ctx)
    if reused:
        res.details["monologue_keyframe_reuse"] = reused
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
    # 6) SCENE_LOCATION_STILL_V1 (device 1101 E24): one people-free still per scene place, never blocks
    res.details["scene_location_stills"] = s5_scene_location_stills(ctx, res)
    return res


def s5_scene_location_stills(ctx: Ctx, res: StageResult) -> dict[str, Any]:
    """One image-to-image "this place, every person removed" still per scene location that has no LOCKED plate
    (scene_location_still.py), so every H3 unit carries its scene's place as a background-only reference
    (scene_location_lock.location_reference_for_unit).  ~1.2 credits per location (HopsAPI gpt-image-2 planning
    rate), one to three per episode (owner-approved 2026-11-23).  Only episodes built with SCENE_LOCATION_LOCK_V1
    (editorial marker); anything but a clean run is recorded and S5 goes on."""
    try:
        p = ctx.p
        editorial = read_json(p.editorial, {}) or {}
        if "scene_location_lock" not in editorial:
            return {"status": "NOT_APPLICABLE", "reason": "EPISODE_BUILT_BEFORE_SCENE_LOCATION_LOCK"}
        tool = RT_TOOLS / "scene_location_still.py"
        common = ["--episode", ctx.episode, "--editorial", p.editorial, "--keyframe-dir", p.keyframes,
                  "--runtime-root", RUNTIME, "--engine-root", ENGINE,
                  "--asset-library", (getattr(p, "scope", None) or {}).get("asset_library") or ""]
        plan_step = ctx.run([VENV, tool, "plan", *common], name="s5_scene_location_still_plan")
        res.steps.append(plan_step)
        planned_rows = (qa_json(plan_step) or {}).get("rows") or []
        if not planned_rows:
            return {"status": "NONE_NEEDED"}
        if image_provider_info()["provider"] != "hopsapi":
            return {"status": "SKIPPED_PROVIDER_NOT_HOPSAPI", "locations": [r["location_id"] for r in planned_rows]}
        planned = image_batch_credits(ctx, len(planned_rows))
        status, step = ctx.paid_step([VENV, tool, "generate", *common], name="s5_scene_location_stills", sid="S5",
                                     planned_credits=planned, dry_argv=[VENV, tool, "plan", *common],
                                     note="one image-to-image location still per scene place (no people)")
        res.steps.append(step)
        return {"status": status, "planned_credits": planned,
                "locations": [r["location_id"] for r in planned_rows], "result": qa_json(step) if status == PASS else None}
    except Exception as exc:  # noqa: BLE001 - never blocks S5
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


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
        # harvest_giggle_image_batch.py names files <EP>_<task key>_<task id>.png (observed
        # 2026-09-13: 29 harvested, 29 "NO_HARVESTED_FILE"); accept both spellings.
        candidates = sorted(set(p.keyframe_harvest_dir.glob(f"{row['task_key']}*"))
                            | set(p.keyframe_harvest_dir.glob(f"{ctx.episode}_{row['task_key']}_*")))
        if not candidates:
            if dest.is_file():
                moved.append({"task_key": row["task_key"], "dest": str(dest), "action": "ALREADY_PRESENT"})
            else:
                missing.append({"task_key": row["task_key"], "reason": "NO_HARVESTED_FILE",
                                "searched": str(p.keyframe_harvest_dir)})
            continue
        # A harvested file only exists between a harvest and this rename (the rename moves it out), so
        # one sitting next to an existing keyframe is a regeneration of it.  Keeping the old image
        # because "the destination already exists" sent E11's 50 paid redos to an unread directory
        # while Q1 re-reviewed the 2-day-old frames.  Park the old one instead of discarding it.
        parked = None
        if dest.is_file():
            if sha256_file(dest) == sha256_file(candidates[0]):
                candidates[0].unlink()
                moved.append({"task_key": row["task_key"], "dest": str(dest), "action": "ALREADY_PRESENT"})
                continue
            park_dir = dest.parent / f"_superseded_{ctx.run_id}"
            park_dir.mkdir(parents=True, exist_ok=True)
            parked = park_dir / dest.name
            os.replace(dest, parked)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidates[0], dest)
        moved.append({"task_key": row["task_key"], "src": str(candidates[0]),
                      "dest": str(dest), "sha256": sha256_file(dest),
                      "action": "REPLACED_PARKED_PREVIOUS" if parked else "RENAMED",
                      **({"parked_previous": str(parked)} if parked else {})})
    return {"mode": "APPLIED", "keyframe_dir": str(p.keyframes),
            "moved": moved, "missing": missing}


#: Gates the line owner may accept by order.  CHARACTER-IDENTITY-ADMISSION is the original; 2026-10-01
#: added a keyframe whose ONLY failing gate is PERIOD-ANACHRONISM-LOCK, e.g. a background prop the image
#: model keeps rendering anachronistically after the guarded rerolls.
Q1_ACCEPTABLE_GATES = ("CHARACTER-IDENTITY-ADMISSION", "PERIOD-ANACHRONISM-LOCK")

#: Gates a still failing SEVERAL gates at once may be accepted for, each by its own source-receipted,
#: media-sha-bound GATE_FAIL_ACCEPTANCE order (2026-10-14).  A derived start frame (the previous unit's
#: real tail) that does not show the next unit's entry state fails identity AND the action/state handoff
#: together — on the first MiniMax-H3 episode both derived stills of E02 did — and the one-gate rule above
#: left the "quality never blocks" default acceptance with no route.  Every failing gate must be in this
#: set and covered by its own order; any failure string not attributable to a registered gate keeps the
#: still rejected.  No standing rule applies on this path.
#: 2026-10-16 (miniPCs 400030 / 400926, S6 derived stills): a real previous tail used as the next unit's
#: start frame cannot meet the next shot's framing, and keyframe_q1_builder files framing/axis under
#: SCENE-AUTHORITY-LOCK, so that gate fails alongside the others and the default acceptance had no route.
#: It still needs its own sha-bound order like every gate here.
#: 2026-10-31: the same per-gate route also takes a still failing ONE gate of this set that is not in
#: Q1_ACCEPTABLE_GATES (the single action/state-handoff failure).  These are the four registered keyframe
#: Q1 gates; an unregistered gate id or an unattributed failure string is never waived.
Q1_MULTI_GATE_ACCEPTABLE = ("CHARACTER-IDENTITY-ADMISSION", "PERIOD-ANACHRONISM-LOCK",
                            "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF", "SCENE-AUTHORITY-LOCK")


def q1_gate_detectors(row: dict[str, Any], gate_id: str, failures: list[str],
                      decisions: list[dict[str, Any]]) -> list[str]:
    """The "<item_id>:<detector>" list one failing gate of a Q1 row asks the line owner to accept."""
    item_id = row.get("item_id")
    if gate_id != "CHARACTER-IDENTITY-ADMISSION":
        return [f"{item_id}:{gate_id}"]
    detectors = sorted({f"{item_id}:{d.get('character_id')}" for d in decisions
                        if str(d.get("source_id") or "").endswith(f":{item_id}")
                        and d.get("decision") not in ("PASS", "ADMIT_BEST_EFFORT")})
    if detectors:
        return detectors
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
    if detectors:
        return detectors
    # No per-character detector could be derived -- a character-free insert showing an undeclared
    # (often faceless) figure (Twelve Gazes E01-VU-004), or a declared character whose face was not
    # measurable so the reviewer answered UNCERTAIN (E01-VU-009).  Without a detector the "quality
    # never blocks" default acceptance had nothing to bind to and the still stayed rejected forever.
    # The gate itself is the detector here, exactly as for every other registered gate; the order is
    # still sha-bound to this still and the FAIL stays recorded.
    return [f"{item_id}:{gate_id}"]


def q1_identity_evidence(row: dict[str, Any], gate_id: str) -> tuple[dict[str, Any], str]:
    """The registered identity-gate evidence for one Q1 row: (payload, path).

    The index row carries only a one-line finding; the evidence file is what lists the
    declared characters and the raw failure codes, which is what the standing rule has to
    read.  Returns ({}, "") when the file is absent, and the caller then admits nothing.
    """
    req = read_json(Path(str(row.get("admission_request") or "")), {}) or {}
    for ev in req.get("evidence") or []:
        if not isinstance(ev, dict) or str(ev.get("gate_id") or "") != gate_id:
            continue
        raw = str(ev.get("evidence_path") or "")
        if not raw:
            continue
        path = Path(raw) if Path(raw).is_absolute() else ENGINE / raw
        return (read_json(path, {}) or {}), str(path)
    return {}, ""


#: The engine writes a failing registered gate in three shapes, with the gate id in a different
#: position in each: "evidence_1:<GATE>:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
#: "evidence_4:<GATE>:evidence_payload_not_pass:FAIL_NOT_ADMITTED" (seen 2026-10-16 on derived stills)
#: and "required_registered_gate_not_pass:<GATE>".  The first two capture BEFORE the marker.
FAILED_GATE_RE = re.compile(r"(?:^|:)([A-Z][A-Z0-9-]*):(?:registered_gate|evidence_payload)_not_pass:"
                            r"|^required_registered_gate_not_pass:([A-Z][A-Z0-9-]*)$")


def failing_registered_gates(failures: list[Any]) -> list[str]:
    """Registered gate ids a Q1 index row reports as not passing."""
    found: set[str] = set()
    for raw in failures:
        match = FAILED_GATE_RE.search(str(raw))
        if match:
            found.add(match.group(1) or match.group(2))
    return sorted(found)


def accept_q1_row(row: dict[str, Any], record: dict[str, Any], failures: list[str]) -> None:
    """Admit one Q1 row on a line-owner acceptance record; the engine's own result is kept beside it."""
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


def q1_order_bindings(row: dict[str, Any], detectors: list[str]) -> list[tuple[str, list[str]]]:
    """(media key, detectors) pairs one Q1 row's gate order may be recorded under.

    The Q1 row names a still by its shot (``item_id``); a continuity-derived start frame is also known by its
    unit (start-frame receipt, wave state, the S6 messages), and the recording agent of device 1485 (JA-01 E03,
    2026-11-21) had no way to tell which key the overlay reads.  The sha binding stays exact -- only the key the
    sha sits under and the "<key>:" prefix of each detector may be the shot or the unit."""
    item_id, uid = str(row.get("item_id") or ""), str(row.get("unit_id") or "")
    out: list[tuple[str, list[str]]] = []
    as_unit = [uid + d[len(item_id):] if item_id and uid and d.startswith(item_id + ":") else d for d in detectors]
    for key in (item_id, uid):
        for dets in (detectors, as_unit):
            if key and (key, dets) not in out:
                out.append((key, list(dets)))
    return out


def find_q1_gate_order(ctx: Ctx, orders: list[dict[str, Any]], row: dict[str, Any], gate_id: str,
                       detectors: list[str], issuer: str,
                       order_gate_id: str | None = None) -> tuple[dict[str, Any] | None, str, list[str]]:
    """The newest sha-bound order accepting ``gate_id``'s detectors on this Q1 row: (order, media key, detectors)."""
    sha = str(row.get("asset_sha256") or "")
    for key, dets in q1_order_bindings(row, detectors):
        order = _rga.find_acceptance(orders, episode=ctx.episode, gate_id=order_gate_id or gate_id, failing=dets,
                                     media_sha256=sha, media_item_id=key, expected_issuer=issuer,
                                     engine_root=ENGINE) if dets else None
        if order is not None:
            return order, key, dets
    return None, str(row.get("item_id") or ""), list(detectors)


def q1_orders_needed(ctx: Ctx, index: dict[str, Any], unit_ids: list[str]) -> list[dict[str, Any]]:
    """For every still-rejected Q1 row of ``unit_ids``: the exact default-acceptance order(s) that would admit it
    (one per failing registered gate, sha-bound to the still on disk), in record_supervisor_order.py terms.
    Advisory output only: it names what to record, it never records or admits anything."""
    ident = read_json(Path(str((index.get("identity_measurement") or {}).get("engine_report") or "")), {}) or {}
    decisions = ((ident.get("objective_verification") or {}).get("decisions")) or []
    out: list[dict[str, Any]] = []
    wanted = set(unit_ids)
    for row in index.get("results") or []:
        uid = str(row.get("unit_id") or "")
        if uid not in wanted or row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT":
            continue
        failures = [str(f) for f in (row.get("failures") or [])]
        gates = failing_registered_gates(failures)
        unattributed = [f for f in failures if not FAILED_GATE_RE.search(f)]
        entry: dict[str, Any] = {"unit_id": uid, "item_id": row.get("item_id"),
                                 "media": f"{row.get('item_id')}={row.get('asset_path') or ''}",
                                 "media_sha256": row.get("asset_sha256"), "orders": []}
        if unattributed or not gates:
            entry["not_acceptable"] = unattributed or ["NO_REGISTERED_GATE_FAILURE"]
        for gate in gates:
            entry["orders"].append({"gate_id": gate, "acceptable": gate in Q1_MULTI_GATE_ACCEPTABLE,
                                    "detectors": q1_gate_detectors(row, gate, failures, decisions)})
        out.append(entry)
    return out


def q1_multi_gate_acceptance(ctx: Ctx, orders: list[dict[str, Any]], row: dict[str, Any],
                             failures: list[str], failed_gates: list[str],
                             decisions: list[dict[str, Any]], issuer: str) -> dict[str, Any] | None:
    """Accept a still failing several registered gates only when EACH failing gate is covered by its own
    active, source-receipted GATE_FAIL_ACCEPTANCE order naming every one of that gate's detectors and bound
    to this still's exact sha256.  Returns None (still rejected) on any gap; never self-issued."""
    if not orders or not issuer:
        return None
    if any(g not in Q1_MULTI_GATE_ACCEPTABLE for g in failed_gates):
        return None
    if any(not FAILED_GATE_RE.search(f) for f in failures):  # an unattributed failure is never waived
        return None
    item_id, sha = row.get("item_id"), str(row.get("asset_sha256") or "")
    per_gate = []
    for gate in failed_gates:
        detectors = q1_gate_detectors(row, gate, failures, decisions)
        order, key, used = find_q1_gate_order(ctx, orders, row, gate, detectors, issuer)
        if order is None:
            return None
        per_gate.append(_rga.acceptance_record(order, episode=ctx.episode, gate_id=gate, failing=used,
                                               media_sha256=sha, media_item_id=key,
                                               gate_result_path=str(row.get("admission_result") or "")))
    return {
        "schema": "nalu.q1_multi_gate_line_owner_acceptance.v1",
        "episode": ctx.episode, "item_id": item_id, "unit_id": row.get("unit_id"),
        "gate_id": "+".join(failed_gates), "gate_ids": failed_gates,
        "gate_status_kept": "FAIL", "media_sha256": sha,
        "order_seqs": [r.get("order_seq") for r in per_gate],
        "per_gate": per_gate,
        "engine_status": row.get("status"), "engine_failures": failures,
        "accepted_under": "PER_ITEM_ORDER_PER_GATE",
        "self_issued": False,
    }


def apply_line_owner_q1_acceptance(ctx: Ctx, index: dict[str, Any], index_path: Path) -> dict[str, Any]:
    """Order-keyed acceptance of CHARACTER-IDENTITY-ADMISSION failures at S5 Q1.

    Two ways a still gets admitted, both requiring an active source-receipted line-owner order:

    * GATE_FAIL_ACCEPTANCE — names EVERY failing "<item_id>:<character_id>" detector and binds the
      current keyframe's sha256.  Exact, but it dies the moment the frame is regenerated.
    * STANDING_RULE — carries the NO_FACE_PIXELS_IN_STILL scope, so it covers a *condition* rather
      than a list of shas and the line applies it without stopping.  See roger_gate_acceptance for
      what the condition requires; the short version is that the identity gate must be the only
      failing gate, every identity failure must be a no-face-pixels code, and every other declared
      character must have measured a real PASS.

    The engine gate result keeps its FAIL row and evidence either way.  Never self-issued: no order,
    or a still that fails a second gate, stays rejected."""
    orders_path = ctx.authority.get("orders_path")
    orders = (_rga._orders(orders_path,
                           expected_latest_seq=ctx.authority.get("latest_order_seq") or 0,
                           engine_root=ENGINE)
              if orders_path and not ctx.authority_blockers else [])
    gate_id = "CHARACTER-IDENTITY-ADMISSION"
    ident = read_json(Path(str((index.get("identity_measurement") or {}).get("engine_report") or "")), {}) or {}
    decisions = ((ident.get("objective_verification") or {}).get("decisions")) or []
    accepted, still_rejected = [], []
    by_standing_rule: list[dict[str, Any]] = []
    rule_refused: list[dict[str, Any]] = []
    allowed = list(index.get("video_submission_allowed_unit_ids") or [])
    issuer = ctx.authority.get("line_owner_id") or ""
    standing_rule = (_rga.find_standing_rule(orders, episode=ctx.episode, gate_id=gate_id,
                                            expected_issuer=issuer, engine_root=ENGINE)
                     if orders else None)
    for row in index.get("results") or []:
        if row.get("status") == "PASS" or row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT":
            continue
        item_id, uid = row.get("item_id"), row.get("unit_id")
        failures = [str(f) for f in (row.get("failures") or [])]
        # 2026-10-01: the same order-keyed acceptance also covers a keyframe whose ONLY failing gate is
        # PERIOD-ANACHRONISM-LOCK (detector "<item_id>:PERIOD-ANACHRONISM-LOCK"), e.g. a background prop the
        # image model keeps rendering anachronistically after the guarded rerolls.  One gate per row; a row
        # failing two gates stays rejected.
        #
        # This substring test is the guard that keeps a still which failed something ELSE out of both
        # acceptance paths: an extra failing gate's own failure string does not name this gate, so
        # ``all(g in f ...)`` is false and the row never reaches the standing rule.
        row_gate = next((g for g in Q1_ACCEPTABLE_GATES if failures and all(g in f for f in failures)), None)
        multi_gates = failing_registered_gates(failures)
        # E12 2026-10-31 / lab E11: a still failing ONE gate that only the per-gate path knows (the
        # action/state handoff, the scene lock) was rejected forever even with its own sha-bound order,
        # while the same gate failing beside another one was acceptable.  One failing gate goes the same
        # per-gate way, which still requires every failing gate to be in Q1_MULTI_GATE_ACCEPTABLE, every
        # failure string to be attributable, and its own sha-bound order (CLAUDE_CODE_PRODUCTION §5).
        if row_gate is None and multi_gates:
            record = q1_multi_gate_acceptance(ctx, orders, row, failures, multi_gates, decisions, issuer)
            if record is None:
                still_rejected.append(uid)
                continue
            accept_q1_row(row, record, failures)
            if uid not in allowed:
                allowed.append(uid)
            accepted.append(record)
            continue
        if row_gate is None:
            still_rejected.append(uid)
            continue
        gate_id = row_gate
        # The standing rule is not given this row's gate alone but the whole failing-gate list, so it
        # can refuse a still that failed another registered gate too.  failing_registered_gates reads
        # the engine's two failure shapes rather than substring-matching; the gate under test is always
        # included even if a row's strings match neither shape, so the list is never short of it.
        failed_gates = sorted(set(failing_registered_gates(failures)) | {gate_id})
        detectors = q1_gate_detectors(row, gate_id, failures, decisions)
        # A per-item signature is exact and the cheapest thing to audit, so it is tried first; the
        # standing rule is the fallback for the case this feature exists for — the frame was
        # regenerated and the old sha binding no longer applies.
        order, order_key, order_dets = (find_q1_gate_order(ctx, orders, row, gate_id, detectors, issuer)
                                        if detectors else (None, item_id, detectors))
        if order is not None:
            cos = {f"{item_id}:{d.get('character_id')}": d.get("aggregate_median") for d in decisions
                   if str(d.get("source_id") or "").endswith(f":{item_id}")}
            record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=gate_id, failing=order_dets,
                                            media_sha256=str(row.get("asset_sha256") or ""),
                                            media_item_id=order_key,
                                            gate_result_path=str(row.get("admission_result") or ""))
            record.update({"item_id": item_id, "unit_id": uid, "cosines": cos,
                           "engine_status": row.get("status"), "engine_failures": failures,
                           "accepted_under": "PER_ITEM_ORDER"})
        elif standing_rule is not None:
            evidence, evidence_path = q1_identity_evidence(row, gate_id)
            verified = (evidence.get("objective_verification") or {})
            condition = _rga.standing_rule_condition(
                failed_gates=failed_gates,
                identity_failures=list(verified.get("failures") or []),
                identity_gate_id=gate_id,
                # the per-still decisions live in the evidence file's objective_verification, not in
                # the index-level identity report (whose source_ids are shaped E11:STILL:<item>)
                decisions=list(verified.get("decisions") or []),
                declared_characters=[str(c) for c in verified.get("declared_visible_character_ids") or []],
                render_style=ctx_render_style(ctx))
            if not condition.get("covered"):
                rule_refused.append({"item_id": item_id, "unit_id": uid, "condition": condition,
                                     "evidence_path": evidence_path})
                still_rejected.append(uid)
                continue
            cos = {f"{item_id}:{d.get('character_id')}": d.get("aggregate_median") for d in decisions
                   if str(d.get("source_id") or "").endswith(f":{item_id}")}
            record = _rga.standing_rule_acceptance(
                standing_rule, episode=ctx.episode, gate_id=gate_id,
                excused_detectors=[f"{item_id}:{c}" for c in condition.get("excused_characters") or []],
                condition=condition, media_sha256=str(row.get("asset_sha256") or ""),
                media_item_id=item_id, gate_result_path=str(row.get("admission_result") or ""))
            record.update({"item_id": item_id, "unit_id": uid, "cosines": cos,
                           "engine_status": row.get("status"), "engine_failures": failures,
                           "accepted_under": "STANDING_RULE"})
            by_standing_rule.append(record)
        else:
            still_rejected.append(uid)
            continue
        accept_q1_row(row, record, failures)
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
            "schema": "nalu.q1_line_owner_gate_acceptance.v2", "episode": ctx.episode,
            "gate_ids": sorted({r.get("gate_id") for r in accepted}),
            "recorded_at": now(), "recorded_by": TOOL_ID, "orders_path": str(orders_path),
            "standing_rule_order_seq": (standing_rule or {}).get("seq"),
            "accepted": accepted,
            "accepted_by_standing_rule": by_standing_rule,
            "standing_rule_refusals": rule_refused,
            "still_rejected_unit_ids": still_rejected})
    return {"accepted_unit_ids": [r["unit_id"] for r in accepted],
            "accepted_by_standing_rule_unit_ids": [r["unit_id"] for r in by_standing_rule],
            "standing_rule_refusals": rule_refused,
            "still_rejected_unit_ids": still_rejected,
            "effective_status": index.get("status")}


# Historical API alias for old runtime callers. New receipts and state keys are neutral.
apply_roger_q1_acceptance = apply_line_owner_q1_acceptance

#: Gate id of the start-frame receipt (start_frame_evidence_writer.START_FRAME_GATE_ID).
START_FRAME_GATE_ID = "START-FRAME-SEMANTIC-EVIDENCE"


def apply_derived_start_frame_acceptance(ctx: Ctx, index: dict[str, Any], index_path: Path) -> dict[str, Any]:
    """S6.q1_derived: admit a continuity-derived start frame whose line-owner (default) acceptance was
    recorded against the START-FRAME-SEMANTIC-EVIDENCE gate rather than per Q1 gate.

    Lab Holmes E03 (2026-10-24): VU-002/005/008 were reviewed FAIL (speaker edge crop, undeclared figure),
    one controlled redo was spent, and the default "quality never blocks" orders were recorded — bound to
    each derived still's exact sha — for the start-frame gate; the writer turned the receipts into
    ACCEPTED_BY_LINE_OWNER_ORDER.  The Q1 overlay only looks for orders keyed by the failing Q1 gates, so
    every S6 re-entry rejected the same stills and the line stopped for good.

    A still is admitted here only when ALL of these hold: the unit is continuity-derived; every Q1 failure
    names a registered gate in Q1_MULTI_GATE_ACCEPTABLE; its start-frame receipt is
    ACCEPTED_BY_LINE_OWNER_ORDER for this exact sha (== the Q1 row's sha == the keyframe on disk); and the
    order the receipt cites is re-found NOW — active, source-receipted, issued by the line owner, naming
    every accepted detector and bound to that sha.  The review answers and the engine FAIL stay recorded."""
    orders_path = ctx.authority.get("orders_path")
    orders = (_rga._orders(orders_path, expected_latest_seq=ctx.authority.get("latest_order_seq") or 0,
                           engine_root=ENGINE)
              if orders_path and not ctx.authority_blockers else [])
    issuer = ctx.authority.get("line_owner_id") or ""
    derived = tail_sourced_units(ctx)
    ident = read_json(Path(str((index.get("identity_measurement") or {}).get("engine_report") or "")), {}) or {}
    decisions = ((ident.get("objective_verification") or {}).get("decisions")) or []
    accepted: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    if not orders or not issuer:
        return {"accepted_unit_ids": [], "refused": [], "reason": "NO_LINE_OWNER_ORDERS"}
    allowed = list(index.get("video_submission_allowed_unit_ids") or [])
    for row in index.get("results") or []:
        if row.get("status") == "PASS" or row.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT":
            continue
        uid, sha = str(row.get("unit_id") or ""), str(row.get("asset_sha256") or "")
        info = derived.get(uid)
        if not info or not info["keyframe_path"].is_file():
            continue
        failures = [str(f) for f in (row.get("failures") or [])]
        gates = failing_registered_gates(failures)
        why = None
        if not failures or not gates or any(not FAILED_GATE_RE.search(f) for f in failures):
            why = "UNATTRIBUTED_Q1_FAILURE"
        elif any(g not in Q1_MULTI_GATE_ACCEPTABLE for g in gates):
            why = "Q1_GATE_NOT_ACCEPTABLE"
        elif sha != sha256_file(info["keyframe_path"]):
            why = "KEYFRAME_CHANGED_SINCE_Q1"
        receipt_path = ENGINE / "reports/start_frame_evidence" / f"{uid}_start_frame_evidence.json"
        receipt = read_json(receipt_path, {}) or {}
        owner = receipt.get("line_owner_acceptance") or {}
        # A receipt the reviewer PASSED needs no order: there is nothing to accept.  Before this,
        # only ACCEPTED_BY_LINE_OWNER_ORDER was admitted here, so a derived frame whose start frame
        # really was the inherited tail still stopped the line forever waiting for an order that
        # had no defect to accept (E14 VU-025, 2026-11-04).
        receipt_sha = str(receipt.get("reference_sha256") or "")
        passed_outright = receipt.get("status") == "PASS" and receipt_sha == sha
        if why is None and not passed_outright and (
                receipt.get("status") != "ACCEPTED_BY_LINE_OWNER_ORDER"
                or receipt_sha != sha
                or str(owner.get("media_sha256") or "") != sha):
            why = "NO_ACCEPTED_START_FRAME_RECEIPT_FOR_THIS_SHA"
            # Device 1485 (JA-01 E03, 2026-11-21): the start-frame receipt is only written AFTER the derived
            # still is Q1-admitted (S6.sfe_derived), so for a Q1-rejected still it can never exist here.  A
            # default acceptance the line owner recorded on this start-frame gate that names the still's
            # failing Q1 gates ("<shot|unit>:<GATE>", same detectors as the per-gate route) and binds this
            # exact sha admits the Q1 row; the receipt itself is still produced by the engine afterwards.
            per_gate = []
            for gate in gates:
                dets = q1_gate_detectors(row, gate, failures, decisions)
                order, key, used = find_q1_gate_order(ctx, orders, row, gate, dets, issuer,
                                                      order_gate_id=START_FRAME_GATE_ID)
                if order is None:
                    per_gate = []
                    break
                per_gate.append(_rga.acceptance_record(order, episode=ctx.episode, gate_id=START_FRAME_GATE_ID,
                                                       failing=used, media_sha256=sha, media_item_id=key,
                                                       gate_result_path=str(row.get("admission_result") or "")))
            if per_gate:
                record = {"schema": "nalu.q1_multi_gate_line_owner_acceptance.v1",
                          "episode": ctx.episode, "item_id": row.get("item_id"), "unit_id": uid,
                          "gate_id": START_FRAME_GATE_ID, "gate_ids": gates, "gate_status_kept": "FAIL",
                          "media_sha256": sha, "order_seqs": [r.get("order_seq") for r in per_gate],
                          "per_gate": per_gate, "self_issued": False,
                          "acceptance_status": "ACCEPTED_BY_DEFAULT_ORDER",
                          "accepted_under": "START_FRAME_GATE_ORDER_NAMING_Q1_GATES",
                          "q1_gate_ids_kept_fail": gates, "engine_status": row.get("status"),
                          "engine_failures": failures, "start_frame_receipt": str(receipt_path),
                          "start_frame_receipt_status": receipt.get("status") or "MISSING"}
                accept_q1_row(row, record, failures)
                if uid not in allowed:
                    allowed.append(uid)
                accepted.append(record)
                continue
        if passed_outright:
            record = {"acceptance_status": "ADMITTED_START_FRAME_RECEIPT_PASS",
                      "accepted_under": "START_FRAME_SEMANTIC_EVIDENCE_REVIEW_PASS",
                      "start_frame_receipt": str(receipt_path),
                      "start_frame_receipt_sha256": receipt.get("review_file_sha256"),
                      "reviewer": receipt.get("reviewer"), "review_method": receipt.get("review_method"),
                      "item_id": row.get("item_id"), "unit_id": uid,
                      "media_sha256": sha, "q1_gate_ids_kept_fail": gates,
                      "engine_status": row.get("status"), "engine_failures": failures}
            accept_q1_row(row, record, failures)
            if uid not in allowed:
                allowed.append(uid)
            accepted.append(record)
            continue
        detectors = [str(d) for d in owner.get("accepted_detectors") or [] if str(d)]
        order = (_rga.find_acceptance(orders, episode=ctx.episode, gate_id=START_FRAME_GATE_ID,
                                      failing=detectors, media_sha256=sha, media_item_id=uid,
                                      expected_issuer=issuer, engine_root=ENGINE)
                 if why is None and detectors else None)
        if why is None and order is None:
            why = "START_FRAME_ORDER_NOT_FOUND"
        if why is not None:
            refused.append({"unit_id": uid, "reason": why})
            continue
        record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=START_FRAME_GATE_ID,
                                        failing=detectors, media_sha256=sha, media_item_id=uid,
                                        gate_result_path=str(receipt_path))
        record.update({"item_id": row.get("item_id"), "unit_id": uid,
                       "acceptance_status": "ACCEPTED_BY_DEFAULT_ORDER",
                       "accepted_under": "START_FRAME_SEMANTIC_EVIDENCE_ORDER",
                       "q1_gate_ids_kept_fail": gates, "engine_status": row.get("status"),
                       "engine_failures": failures, "start_frame_receipt": str(receipt_path)})
        accept_q1_row(row, record, failures)
        if uid not in allowed:
            allowed.append(uid)
        accepted.append(record)
    if accepted:
        engine_index = index_path.with_suffix(".engine.json")
        if not engine_index.is_file() and index_path.is_file():
            shutil.copy2(index_path, engine_index)
        still = [u for u in index.get("rejected_unit_ids") or [] if u not in allowed]
        index["video_submission_allowed_unit_ids"] = allowed
        index["rejected_unit_ids"] = still
        index["admitted_count"] = len(allowed)
        index["engine_status"] = index.get("engine_status") or index.get("status")
        index["status"] = ("ALL_ADMITTED" if not still
                           else f"PARTIAL_{len(allowed)}_OF_{index.get('unit_count')}_ADMITTED")
        index["status_basis"] = "ENGINE_ADMITTED+LINE_OWNER_ORDER_ACCEPTANCE (source-receipted, never self-issued)"
        index["derived_start_frame_acceptance"] = accepted
        write_json(index_path, index)
    return {"accepted_unit_ids": [r["unit_id"] for r in accepted], "refused": refused,
            "effective_status": index.get("status")}


def start_frame_receipt_path(unit_id: str) -> Path:
    return ENGINE / "reports/start_frame_evidence" / f"{unit_id}_start_frame_evidence.json"


#: start-frame receipt states (start_frame_receipt_state)
SFE_CURRENT, SFE_CURRENT_FAIL, SFE_STALE, SFE_MISSING = "CURRENT", "CURRENT_FAIL", "STALE", "MISSING"


def start_frame_receipt_state(unit_id: str, keyframe: Path) -> str:
    """Whether the unit's START-FRAME-SEMANTIC-EVIDENCE receipt describes the start frame on disk NOW.

    Until 2026-11-21 S6 asked only "does the receipt file exist?".  A derived start frame rewritten after its
    receipt (re-materialised from a re-extracted / normalised / text-cleaned tail, PRs #277/#284; or a motivated
    cut whose tail is now rejected and that opens on its own keyframe, PR #286) kept the receipt of the OLD bytes,
    so S6 never asked for a new one and the derived acceptance / compile validator refused it for good
    (NO_ACCEPTED_START_FRAME_RECEIPT_FOR_THIS_SHA / RECEIPT_SHA_STALE).

    CURRENT: PASS or ACCEPTED_BY_LINE_OWNER_ORDER for these exact bytes.  CURRENT_FAIL: judged these bytes and
    not passing (the writer re-runs, so a default acceptance recorded since is picked up).  STALE: another sha,
    or unreadable.  MISSING: no receipt."""
    path = start_frame_receipt_path(unit_id)
    if not path.is_file():
        return SFE_MISSING
    receipt = read_json(path, {}) or {}
    if not keyframe.is_file() or str(receipt.get("reference_sha256") or "") != sha256_file(keyframe):
        return SFE_STALE
    if receipt.get("status") == "PASS":
        return SFE_CURRENT
    owner = receipt.get("line_owner_acceptance") or {}
    if (receipt.get("status") == "ACCEPTED_BY_LINE_OWNER_ORDER" and isinstance(owner, dict)
            and str(owner.get("media_sha256") or "") == str(receipt.get("reference_sha256") or "")):
        return SFE_CURRENT
    return SFE_CURRENT_FAIL


def start_frame_orders_needed(unit_ids: list[str]) -> list[dict[str, Any]]:
    """The START-FRAME-SEMANTIC-EVIDENCE default acceptance each failing current receipt needs (advisory)."""
    try:
        import start_frame_evidence_writer as _sfw  # noqa: PLC0415
        split = _sfw.blocker_detectors
        never = tuple(_sfw.NEVER_ACCEPTABLE_BLOCKERS)
    except Exception:  # noqa: BLE001 - the advice is best effort
        split = lambda uid, blockers: sorted({f"{uid}:{b}" for b in blockers})  # noqa: E731
        never = ("KEYFRAME_MISSING", "KEYFRAME_CHANGED_SINCE_REVIEW")
    out = []
    for uid in unit_ids:
        receipt = read_json(start_frame_receipt_path(uid), {}) or {}
        blockers = [str(b) for b in receipt.get("blockers") or []]
        out.append({"unit_id": uid, "gate_id": START_FRAME_GATE_ID,
                    "media": f"{uid}={receipt.get('reference_path') or ''}",
                    "media_sha256": receipt.get("reference_sha256"),
                    "detectors": split(uid, blockers),
                    "not_acceptable": [b for b in blockers if b.split(":")[0] in never]})
    return out


def ensure_derived_start_frame_receipts(ctx: Ctx, res: StageResult, units: dict[str, Path], *,
                                        sub_stage: str = "S6.sfe_derived") -> str:
    """Make the engine (never an agent) produce a current START-FRAME-SEMANTIC-EVIDENCE receipt for every
    admitted derived start frame in ``units`` (unit id -> start frame on disk).

    Returns "OK" (every receipt current), "WRITTEN" (receipts rewritten, re-plan) or "STOP" (``res`` carries the
    review request or the blocker).  A receipt is (re)written from the newest valid start_frame review answer
    whose media is these exact bytes (several reviews merged, one per still); a unit with no such answer gets
    a review request for exactly that still.  A receipt that judged these bytes and FAILs is re-written each
    pass so a default acceptance recorded since is picked up; still failing, the stop names the exact order."""
    need = {uid: kf for uid, kf in units.items() if start_frame_receipt_state(uid, kf) != SFE_CURRENT}
    if not need:
        return "OK"
    res.details["derived_units_need_start_frame_receipt"] = sorted(need)
    res.details["start_frame_receipt_states"] = {uid: start_frame_receipt_state(uid, kf) for uid, kf in need.items()}
    shas = {uid: sha256_file(kf) for uid, kf in need.items() if kf.is_file()}
    review_path, _covered, missing = merge_review_answers(ctx, "start_frame", sorted(need), expected_sha=shas)
    if missing:
        res.status = REVIEW_REQUIRED
        res.details.update(request_review(ctx, res, "start_frame", sub_stage=sub_stage,
                                          note="start-frame receipts for continuity-derived frames "
                                               "(exact bytes now on disk)",
                                          items=missing))
        res.blockers.append(f"{sub_stage}:REVIEW_REQUIRED:{len(missing)}_frames")
        return "STOP"
    write_step = qa_run(ctx, [START_FRAME_EVIDENCE, "write", "--episode", ctx.episode, "--review", review_path],
                        name="s6_sfe_write_receipts_derived")
    res.steps.append(write_step)
    still = sorted(uid for uid, kf in need.items() if start_frame_receipt_state(uid, kf) != SFE_CURRENT)
    if not still:
        return "WRITTEN"
    res.status = BLOCKED
    res.details["start_frame_orders_needed"] = start_frame_orders_needed(still)
    res.details["start_frame_receipt_states"] = {uid: start_frame_receipt_state(uid, need[uid]) for uid in still}
    res.blockers.append(f"{sub_stage}:START_FRAME_EVIDENCE_NOT_PASS:" + ",".join(still))
    res.details["next"] = ("record the default acceptance named in start_frame_orders_needed (CLAUDE_CODE_PRODUCTION "
                           "§5, --gate-id START-FRAME-SEMANTIC-EVIDENCE, one --detector per listed detector, "
                           "--media <unit_id>=<start frame>), then resume S6: the engine re-writes the receipt")
    return "STOP"


def kb_events(fn: str, **kwargs: Any) -> dict[str, Any]:
    """Collective knowledge-base event producer (runtime/tools/nalu_knowledge_events.py; audit 2026-11-12 §6).

    Best-effort by construction: any failure is returned as a status and never reaches the stage that
    called it; NALU_KNOWLEDGE_EVENTS=off disables it.  Returns a compact summary for the state file."""
    try:
        import nalu_knowledge_events as _kbe  # noqa: PLC0415
        if not _kbe.enabled():
            return {"status": "DISABLED"}
        out = getattr(_kbe, fn)(RT, **kwargs)
        events = out.get("events") if isinstance(out, dict) else None
        if isinstance(events, list):
            counts: dict[str, int] = {}
            for row in events:
                key = str((row or {}).get("status") or "?").lower()
                counts[key] = counts.get(key, 0) + 1
            return {"status": out.get("status"), **counts}
        return {"status": (out or {}).get("status")}
    except Exception as exc:  # noqa: BLE001 -- never into the stage
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def kb_review_rows(index: dict[str, Any], admitted_status: str) -> list[dict[str, Any]]:
    # ``source`` = the raw index row: the event layer takes the reviewer's defect codes/notes and the
    # scene/shot label from it (never paths) so a cluster carries causes, not just gate names
    return [{"unit_id": row.get("unit_id"), "passed": row.get("downstream_status") == admitted_status,
             "codes": list(row.get("failures") or []), "source": row}
            for row in (index.get("results") or []) if isinstance(row, dict)]


def kb_postgen_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Post-generation QA units for the knowledge events; a rejected unit carries its QA record (measured vs
    threshold, ASR transcript, reviewer defects) as ``source``."""
    rows = []
    for row in summary.get("units") or []:
        if not isinstance(row, dict):
            continue
        passed = row.get("verdict") == "ADMIT"
        record = (read_json(Path(str(row["record"])), {}) or {}) if not passed and row.get("record") else {}
        rows.append({"unit_id": row.get("unit_id"), "passed": passed, "codes": list(row.get("reasons") or []),
                     **({"source": record} if isinstance(record, dict) and record else {})})
    return rows


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
    if index.get("results"):  # one rate fact per review round + one event per Q1 failure code
        detail["knowledge_events"] = kb_events(
            "record_review_round", episode=ctx.episode, stage="S5", kind="Q1",
            round_key=detail["review_file_sha256"] or str(verdict.get("out") or ""),
            rows=kb_review_rows(index, "ADMITTED_FOR_VIDEO_SUBMIT"),
            evidence={"gate": "shot_media_admission_gate.KEYFRAME_Q1", "q1_status": effective})
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


def bgm_work_dir(ctx: Ctx) -> Path:
    """nalu_selective_bgm.Paths' default work dir (source plan lives here)."""
    return ENGINE / f"workflow/nalu/{ctx.episode}/preproduction/bgm"


def bgm_contract(ctx: Ctx) -> dict[str, Any]:
    """BGM default ON (line owner 2026-10-22): the contract the BGM tool / AgentCut builder get.

    Authored SELECTIVE/REQUIRED or an explicit NONE opt-out -> the sealed contract itself.  NO_BGM /
    omitted -> a derived copy with a default SELECTIVE_NARRATIVE_CUES declaration (nalu_bgm_default)."""
    import nalu_bgm_default as _bgm_default

    return _bgm_default.write_effective_contract(
        ctx.p.contract, bgm_work_dir(ctx) / f"{ctx.episode}_GENERATION_CONTRACT_BGM_DEFAULT.json")


def s7_bgm_contract(ctx: Ctx) -> dict[str, Any]:
    """S7 uses the default-BGM contract only when S6 generated its sources (S7 never generates
    music).  An episode whose S6 ran before the default existed keeps its authored no-BGM contract."""
    try:
        info = bgm_contract(ctx)
    except Exception as exc:  # noqa: BLE001 -- the default must never break the authored path
        return {"source": "DEFAULT_ERROR", "contract": str(ctx.p.contract),
                "reason": f"{type(exc).__name__}:{exc}"}
    if info.get("source") != "LINE_DEFAULT":
        return info
    source_plan = read_json(bgm_work_dir(ctx) / f"{ctx.episode}_BGM_SOURCE_PLAN.json", {}) or {}
    if source_plan.get("contract_sha256") != sha256_file(Path(info["contract"])):
        return {**info, "source": "LINE_DEFAULT_SKIPPED", "contract": str(ctx.p.contract),
                "reason": "S6_HAS_NO_DEFAULT_BGM_SOURCE_PLAN"}
    return info


def selective_bgm_common_argv(ctx: Ctx, contract: Path | None = None) -> list[Any]:
    """Bind BGM receipts to this run's exact private layer and episode work paths."""
    return ["--episode", ctx.episode, "--contract", contract or ctx.p.contract,
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
    # BGM default ON (2026-10-22): NO_BGM / omitted -> derived default-cue contract; NONE opt-out kept.
    try:
        default_info = bgm_contract(ctx)
    except Exception as exc:  # noqa: BLE001 -- unreadable contract: the authored path decides, as before
        default_info = {"source": "DEFAULT_ERROR", "contract": str(ctx.p.contract),
                        "reason": f"{type(exc).__name__}:{exc}"}
    contract_path = Path(default_info["contract"])
    contract = read_json(contract_path, {}) or {}
    bgm = (contract.get("audio_contract") or {}).get("bgm")
    mode = str((bgm or {}).get("mode") or (bgm or {}).get("usage_mode") or "").upper() \
        if isinstance(bgm, dict) else ""
    if mode not in {"SELECTIVE", "SELECTIVE_NARRATIVE_CUES"}:
        return {"status": "NOT_APPLICABLE", "mode": mode or "UNDECLARED", "provider_posts": 0,
                "bgm_default": default_info}
    res.details["bgm_default"] = default_info

    common = selective_bgm_common_argv(ctx, contract_path)
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
                "provider_posts": 0, "verify": qa_json(verify),
                "credit_reconciliation": (s6_bgm_reconcile_best_effort(ctx, res, common)
                                          if verify["exit_code"] == 0 else None)}

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
            "verify": qa_json(verify),
            "credit_reconciliation": s6_bgm_reconcile_best_effort(ctx, res, common)}


def bgm_credit_reconciled(ctx: Ctx) -> bool:
    """Every completed music transaction already carries a PASS_* credit reconciliation."""
    try:
        tx_dir = selective_bgm_transaction_dir(ctx)
    except Exception:  # noqa: BLE001
        return False
    rows = [read_json(path, {}) or {} for path in sorted(tx_dir.glob("*.json"))] if tx_dir.is_dir() else []
    completed = [row for row in rows if row.get("state") == "TERMINAL_COMPLETED" and row.get("task_id")]
    return bool(completed) and all(
        str((row.get("credit") or {}).get("statement_status") or "").startswith("PASS_") for row in completed)


def s6_bgm_reconcile_best_effort(ctx: Ctx, res: StageResult, common: list[Any]) -> dict[str, Any]:
    """Read-only credit reconciliation while the paid S6 run still holds the key (BGM default ON:
    S7 is normally run without GIGGLE_API_KEY).  Diagnostic here, never blocks S6; S7 re-checks."""
    if bgm_credit_reconciled(ctx):
        return {"status": "ALREADY_RECONCILED"}
    if not os.environ.get("GIGGLE_API_KEY"):
        return {"status": "SKIPPED_NO_KEY"}
    step = ctx.run([VENV, SELECTIVE_BGM, "reconcile", *common], name="s6_bgm_reconcile_read_only", paid=True)
    step["diagnostic_only"] = True
    res.steps.append(step)
    return {"status": PASS if step["exit_code"] == 0 else "NOT_YET_RECONCILED", "exit_code": step["exit_code"]}


def video_submit_argv(ctx: Ctx, *, manifest: Path, concurrency: int) -> list[Any]:
    return [VENV, ENGINE / "tools/submit_giggle_video_manifest_v2.py",
            "--manifest", manifest, "--out", ctx.p.video_submit,
            "--concurrency", concurrency, "--project-root", VIDEO_PROJECT_ROOT]


def video_submit_timeout_s() -> int:
    """Subprocess timeout of a paid video submit.  A MiniMax-H3 submit may wait in the fleet-wide H3 queue
    (tools/h3_fleet_queue.py; NALU_H3_QUEUE_MAX_WAIT_S, default 4 h) before its POSTs: the step timeout must
    outlast that wait plus the POSTs, or the kill could land in the middle of a create POST.  The waiting
    itself is pre-intent and never charged; the queue gives up on its own with H3_FLEET_QUEUE_WAIT_TIMEOUT."""
    try:
        wait = int(os.environ.get("NALU_H3_QUEUE_MAX_WAIT_S") or 4 * 3600)
    except ValueError:
        wait = 4 * 3600
    return max(3600, wait + 3600)


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


def _units_with_bound_submission(ctx: Ctx) -> set[str]:
    """Unit ids that have a SUBMITTED_TASK_ID_BOUND record in the durable submit store.

    A record bound BEFORE the unit's clip was last parked for a redo (video/_superseded*|_rejected*|
    _parked*|_archive*/<unit>.mp4, same rule as tools/video_live_binding) is the take that was parked,
    not a POST of the wave being looked at: device 0030 E15 (2026-11-15) parked 22 clips for a redo,
    the redo wave 25 was opened and never POSTed, and the old takes' records kept it frozen forever.
    A record with no timestamp, or a unit that was never parked, counts as bound exactly as before."""
    store_dir = ENGINE / "workflow/tasks/giggle_video_submit_transactions" / ctx.episode
    bound: set[str] = set()
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        from tools.video_live_binding import bound_at as _bound_at, park_time as _park_time
    except Exception:  # noqa: BLE001 - without the helper every bound record counts (old behaviour)
        _bound_at = _park_time = None
    parked_at: dict[str, float | None] = {}
    for path in (store_dir.glob("*.json") if store_dir.is_dir() else []):
        row = read_json(path, {}) or {}
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
            text = json.dumps(row, ensure_ascii=False)
            stamp = _bound_at(row) if _bound_at else None
            for uid in set(re.findall(rf"{re.escape(ctx.episode)}-VU-\d+", text)):
                if stamp is not None and _park_time is not None:
                    if uid not in parked_at:
                        parked_at[uid] = _park_time(uid, [ctx.p.video_media])
                    if parked_at[uid] is not None and stamp <= parked_at[uid]:
                        continue
                bound.add(uid)
    return bound


def park_stale_real_final_frames(ctx: Ctx, unit_ids: list[str]) -> list[dict[str, Any]]:
    """A real final frame is only real while the clip it was cut from is the unit's current clip.

    Readiness, the derived-keyframe copy and the wave compile all test ``real_final_frames/<unit>.png``
    for existence.  When a clip is parked for a redo its old tail stayed behind, so the tail-chained
    successor was planned into the same wave as its predecessor and bound to the tail of a clip that no
    longer exists (device 0030 E15 VU-002 -> VU-003, 2026-11-15).  The tail of a unit with no clip on
    disk is moved aside (never deleted); the tail of a unit whose clip changed is re-extracted; a
    tail-sourced start frame that was copied from a tail which is no longer current is moved aside with
    its sidecar and start-frame receipt, unless that unit already has a clip.  Free; never POSTs."""
    tails = ctx.p.preprod / "real_final_frames"
    out: list[dict[str, Any]] = []
    if getattr(ctx, "dry", False):
        return out

    def _park(paths: list[Path], park_dir: Path) -> list[str]:
        moved = []
        for path in paths:
            if path.is_file():
                park_dir.mkdir(parents=True, exist_ok=True)
                os.replace(path, park_dir / path.name)
                moved.append(str(path))
        return moved

    for uid in unit_ids:
        tail = tails / f"{uid}.png"
        if not tail.is_file():
            continue
        clip = ctx.p.video_media / f"{uid}.mp4"
        marker = tail.with_suffix(".source.sha256")
        if not clip.is_file():
            moved = _park([tail, marker], tails / f"_superseded_{ctx.run_id}")
            out.append({"unit_id": uid, "status": "TAIL_PARKED_CLIP_NOT_ON_DISK", "parked": moved})
        elif marker.is_file() and marker.read_text(encoding="utf-8").strip() != sha256_file(clip):
            row = extract_real_final_frame(ctx, uid)  # parks the stale tail itself, then re-extracts
            out.append({"unit_id": uid, "status": "TAIL_REEXTRACTED_CLIP_CHANGED", "extract": row.get("status")})
    for uid, info in tail_sourced_units(ctx).items():
        dst: Path = info["keyframe_path"]; prev = info.get("previous_unit_id")
        sidecar = dst.with_suffix(".derived.json")
        if not prev or not dst.is_file() or not sidecar.is_file() or (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        source_sha = str((read_json(sidecar, {}) or {}).get("source_sha256") or "")
        tail = tails / f"{prev}.png"
        if (ctx.p.video_media / f"{prev}.mp4").is_file():
            if not source_sha or not tail.is_file() or sha256_file(tail) == source_sha:
                continue
        receipt = ENGINE / "reports/start_frame_evidence" / f"{uid}_start_frame_evidence.json"
        moved = _park([dst, sidecar, receipt], dst.parent / f"_superseded_{ctx.run_id}_stale_tail")
        out.append({"unit_id": uid, "status": "DERIVED_START_FRAME_PARKED_TAIL_NOT_CURRENT",
                    "previous_unit_id": prev, "parked": moved})
    return out


def release_unposted_waves(ctx: Ctx, wave_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Release open waves that never reached a provider POST, so they are re-planned.

    A wave keeps a frozen membership because re-entering a SUBMITTED wave with a different list
    double-POSTed on 2026-09-13.  That protection is only meaningful once something was POSTed.
    E11's wave 1 was opened on 2026-10-06 when a forward run reached S6 before S5 had produced any
    keyframe; it never submitted, yet its frozen list held a unit id that is in no plan (VU-042)
    and a continuity-derived unit whose start frame cannot exist until its predecessor renders
    (VU-040).  Every later pass then asked for a review of a frame that did not exist.

    A wave is released only when ALL of these hold: no submit report on disk, no unit of it has a
    bound transaction in the durable store, and none of its videos is on disk.  Anything that
    may have POSTed keeps its frozen membership exactly as before."""
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    planned = {u["unit_id"] for u in plan.get("units") or []}
    bound = _units_with_bound_submission(ctx)
    released = []
    for w in wave_state.get("waves") or []:
        if w.get("completed_at") or w.get("released_at"):
            continue
        units = list(w.get("units") or [])
        report = Path(w["submit_report"]) if w.get("submit_report") else None
        if report is not None and report.is_file():
            continue
        if any(u in bound for u in units):
            continue
        if any((ctx.p.video_media / f"{u}.mp4").is_file() for u in units):
            continue
        unknown = sorted(u for u in units if u not in planned)
        reason = ("NEVER_POSTED" + (f"; unit(s) not in the grouping plan: {unknown}" if unknown else ""))
        w["released_at"] = now()
        w["completed_at"] = w["released_at"]
        w["release_reason"] = reason
        released.append({"wave": w.get("wave"), "reason": reason})
    return released


def _tail_text_clean(partial: Path, final: Path) -> dict[str, Any]:
    """Inpaint H3-burned caption text off the tail frame before it anchors the next unit
    (engine tools/tail_frame_text_clean.py; fail-open, NALU_TAIL_TEXT_CLEAN=0 opts out)."""
    try:
        import tail_frame_text_clean as _ttc  # engine tools/ is on sys.path
        orig, sidecar = _ttc.companion_paths(final)
        return _ttc.clean_tail_frame(partial, original_copy=orig, sidecar=sidecar)
    except Exception as exc:  # noqa: BLE001 - never block the pipeline on the cleaner
        print(f"[nalu_pipeline] WARNING: tail-frame text clean unavailable ({exc}); original frame kept",
              file=sys.stderr)
        return {"status": "FAIL_OPEN", "tail_text_cleaned": False, "boxes": [], "error": str(exc)}


def tail_normalize_anchor(ctx: Ctx, unit_id: str) -> Path | None:
    """The clean texture anchor for ``unit_id``'s tail: the generated keyframe of its tail chain's root.  A unit
    whose start frame is itself a predecessor tail (continuity-derived / hard continuation) walks back to the first
    unit of the chain that opened on its own S5 keyframe, so the anchor is never an H3 output frame.  None when the
    plan or the keyframe is missing (the normaliser then leaves the tail as it is)."""
    try:
        plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
        first_shot = {str(u.get("unit_id")): (u.get("editorial_shot_ids") or [None])[0] for u in plan.get("units") or []}
        sourced = tail_sourced_units(ctx)
        decisions = start_frame_source_decisions(ctx)
        uid, hops = unit_id, 0
        while uid in sourced and hops < 64:
            if (decisions.get(uid) or {}).get("start_frame_source") == START_FRAME_OWN:
                break  # this unit opened on its own keyframe after all
            prev = sourced[uid].get("previous_unit_id")
            if not prev:
                break
            uid, hops = str(prev), hops + 1
        shot = first_shot.get(uid)
        if not shot:
            return None
        key = ctx.p.preprod / "keyframes" / f"{shot}-keyframe-v1.png"
        if not key.is_file() or key.with_suffix(".derived.json").is_file():
            return None  # a derived keyframe is a tail copy, not a clean anchor
        return key
    except Exception:  # noqa: BLE001 - no anchor: no normalisation
        return None


def unit_start_keyframe(ctx: Ctx, unit_id: str) -> Path | None:
    """``keyframes/<first shot>-keyframe-v1.png`` of ``unit_id`` (for a tail-started unit: the predecessor's tail
    copy it opened on), or None."""
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    shot = next(((u.get("editorial_shot_ids") or [None])[0] for u in plan.get("units") or []
                 if str(u.get("unit_id")) == unit_id), None)
    key = ctx.p.preprod / "keyframes" / f"{shot}-keyframe-v1.png" if shot else None
    return key if key is not None and key.is_file() else None


def _tail_normalize(ctx: Ctx, unit_id: str, partial: Path, final: Path) -> dict[str, Any]:
    """Pull the tail frame's tone / sharpening / skin sheen back toward the scene's clean keyframe before it anchors
    the next unit (engine tools/tail_frame_normalize.py; fail-open, NALU_TAIL_NORMALIZE=0 opts out).  Line owner
    2026-11-20: H3 compounds contrast, sharpening and specular sheen down a tail chain (KO E01 "oily face")."""
    try:
        import tail_frame_normalize as _tfn  # engine tools/ is on sys.path
        raw, sidecar = _tfn.companion_paths(final)
        return _tfn.normalize_tail_frame(partial, anchor=tail_normalize_anchor(ctx, unit_id), raw_copy=raw,
                                         sidecar=sidecar, start=unit_start_keyframe(ctx, unit_id))
    except Exception as exc:  # noqa: BLE001 - never block the pipeline on the normaliser
        print(f"[nalu_pipeline] WARNING: tail-frame normalisation unavailable ({exc}); frame kept", file=sys.stderr)
        return {"status": "FAIL_OPEN", "tail_normalized": False, "error": str(exc)}


def s6_skin_sheen_check(ctx: Ctx, unit_id: str, clip: Path, clip_sha: str) -> dict[str, Any]:
    """QA-SKIN-SHEEN-DRIFT (line owner 2026-11-20): free per-unit measurement of a freshly landed clip -- an early and
    the last frame vs the image the unit opened on (its first-shot keyframe, a tail copy for a tail-started unit)
    and vs the scene's clean anchor keyframe: near-white specular share of the face region, Laplacian variance and
    local contrast (engine tools/tail_frame_normalize.sheen_drift).  Written to
    ``real_final_frames/<unit>.skin_sheen.json``; the final review's must-check list reads it as a measured lead and
    the final fix round redoes a confirmed unit once (paid, SKIN_SHEEN).  Never a gate; anime units and
    ``NALU_SKIN_SHEEN_CHECK=0`` skip it; any error is recorded and ignored."""
    if str(os.environ.get("NALU_SKIN_SHEEN_CHECK", "1")).strip().lower() in ("0", "false", "no", "off"):
        return {"status": "SKIPPED_OPT_OUT"}
    try:
        if ctx_render_style(ctx) == "anime":
            return {"status": "NOT_APPLICABLE", "reason": "RENDER_STYLE_ANIME"}
        import tail_frame_normalize as _tfn  # engine tools/ is on sys.path
        start = unit_start_keyframe(ctx, unit_id)
        anchor = tail_normalize_anchor(ctx, unit_id)
        refs = {"start_frame": start}
        if anchor is not None and (start is None or anchor != start):
            refs["anchor"] = anchor
        row = _tfn.sheen_drift(clip, refs)
        row.update(unit_id=unit_id, source_sha256=clip_sha, measured_at=now())
        write_json(ctx.p.preprod / "real_final_frames" / f"{unit_id}.skin_sheen.json", row)
        if row.get("flagged"):
            ctx.say(f"   S6 skin-sheen drift {unit_id}: {','.join(row.get('reasons') or [])} "
                    f"(QA-SKIN-SHEEN-DRIFT lead for the final review; not a gate)")
        return {k: row.get(k) for k in ("status", "flagged", "reasons", "error") if row.get(k) is not None}
    except Exception as exc:  # noqa: BLE001 - advisory measurement
        return {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def extract_real_final_frame(ctx: Ctx, unit_id: str) -> dict[str, Any]:
    """ffmpeg last-frame grab of the harvested unit video (same recipe as the engine's
    episode_parallel_batch_supervisor.bind_predecessor_tail_frame: -sseof -0.10/-0.20/-0.50)."""
    src = ctx.p.video_media / f"{unit_id}.mp4"
    dst_dir = ctx.p.preprod / "real_final_frames"; dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{unit_id}.png"
    if not src.is_file():
        return {"unit_id": unit_id, "status": "SOURCE_MISSING", "source": str(src)}
    # E12 audit (2026-10-18): ffmpeg used to write straight to `dst`, and a destination that
    # merely existed was reported ALREADY_PRESENT with no validity check.  A run killed mid-write
    # (SIGKILL/OOM/host crash) left a truncated PNG that every later tick trusted and handed
    # downstream as a paid unit's start-frame anchor.  Extract to a temp file, verify it decodes
    # to a non-empty image, then atomically replace; a destination is only ALREADY_PRESENT when
    # it still matches the source video it was derived from.
    source_sha = sha256_file(src)
    if dst.is_file():
        marker = dst.with_suffix(".source.sha256")
        recorded = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        if recorded == source_sha and dst.stat().st_size > 0:
            return {"unit_id": unit_id, "status": "ALREADY_PRESENT", "path": str(dst),
                    "sha256": sha256_file(dst), "source_sha256": source_sha}
        # stale or unverifiable: fall through and re-extract, keeping the old file aside
        park_dir = dst.parent / f"_superseded_{ctx.run_id}"
        park_dir.mkdir(parents=True, exist_ok=True)
        os.replace(dst, park_dir / dst.name)
        marker.unlink(missing_ok=True)
    for off in ("-0.10", "-0.20", "-0.50"):
        partial = dst.with_name(f"{dst.stem}.{ctx.run_id}.part.png")
        partial.unlink(missing_ok=True)
        proc = subprocess.run([_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-sseof", off,
                               "-i", str(src), "-frames:v", "1", "-q:v", "2", str(partial)], check=False)
        if proc.returncode == 0 and partial.is_file() and partial.stat().st_size > 0:
            clean = _tail_text_clean(partial, dst)
            norm = _tail_normalize(ctx, unit_id, partial, dst)
            os.replace(partial, dst)
            dst.with_suffix(".source.sha256").write_text(source_sha + "\n", encoding="utf-8")
            sheen = s6_skin_sheen_check(ctx, unit_id, src, source_sha)
            return {"unit_id": unit_id, "status": "EXTRACTED", "path": str(dst), "sha256": sha256_file(dst),
                    "source": str(src), "source_sha256": source_sha, "sseof": off,
                    "tail_text_cleaned": bool(clean.get("tail_text_cleaned")),
                    "tail_text_clean": clean,
                    "tail_normalized": bool(norm.get("tail_normalized")),
                    "tail_normalize": {k: norm.get(k) for k in ("status", "anchor", "error") if norm.get(k)},
                    "skin_sheen": sheen}
        partial.unlink(missing_ok=True)
    return {"unit_id": unit_id, "status": "EXTRACT_FAILED", "source": str(src)}


def _tail_is_current(ctx: Ctx, unit_id: str, clip_sha: str | None) -> bool:
    """The unit's real final frame was already cut from exactly this clip (so a successor may have used it)."""
    marker = ctx.p.preprod / "real_final_frames" / f"{unit_id}.source.sha256"
    try:
        return bool(clip_sha) and marker.is_file() and marker.read_text(encoding="utf-8").strip() == clip_sha
    except OSError:
        return False


def s6_burn_retry_indices(state: dict[str, Any] | None) -> dict[str, int]:
    """unit -> the burn-retry index its next / last submission carries (``s6_burn_retry`` attempts)."""
    import h3_burn_retry as _br
    return {str(uid): len(row.get("attempts") or [])
            for uid, row in ((state or {}).get(_br.STATE_KEY) or {}).items() if row.get("attempts")}


def s6_unit_lines(ctx: Any, uid: str) -> list[str]:
    """The contract dialogue lines of unit ``uid`` (grouping plan editorial shots -> audio_contract.dialogue_units),
    in order -- the S6 whole-frame text pass flags a read that says one of them.  [] on any error."""
    try:
        p = ctx.p
        shots: list[str] = []
        for unit in (read_json(p.grouping_plan, {}) or {}).get("units") or []:
            if str(unit.get("unit_id")) == str(uid):
                shots = [str(x) for x in unit.get("editorial_shot_ids") or []]
        units = ((read_json(p.contract, {}) or {}).get("audio_contract") or {}).get("dialogue_units") or []
        return [str(d.get("text") or "") for d in units if str(d.get("shot_id")) in shots and d.get("text")]
    except Exception:  # noqa: BLE001
        return []


def s6_burn_check_landed(ctx: Ctx, unit_ids: list[str]) -> list[dict[str, Any]]:
    """S6 burned-text check of every freshly landed H3 clip, BEFORE its tail frame is extracted (line owner
    2026-11-19: automatic paid retry only on detected burned text, at most NALU_S6_BURN_RETRY_MAX (2) per unit,
    no blur cover by default).

    A clip is "freshly landed" when its tail was not yet cut from it, so a successor never anchored on it.  Local
    OCR (tools/h3_burn_retry.detect, ~1 s per clip, zero credits).  On a burn with retries left and the episode
    headroom covering one more video, the take is parked to ``video/_superseded_<run>_burn_retry<n>/`` and the
    unit is redone by the normal wave machinery (D-11, budget, durable store): the recompile carries
    ``h3_burn_retry`` = n, so the prompt gets the retry sentence and the submitter perturbs the @Image1 bytes
    (HopsAPI returns a byte-identical clip for an identical request).  Still burned after the last retry, or a
    retry the budget / an owner acceptance rules out: the take with the fewest burned frames is kept on the
    assembly path and the unit is marked ``burned_text_unresolved`` (wave state; surfaced by the S8 QA-BURNED-TEXT
    checklist).  Never blocks; the detector fails open.  Records live in ``<EP>_S6_WAVE_STATE.json``
    ``s6_burn_retry``."""
    if getattr(ctx, "dry", False) or not unit_ids:
        return []
    try:
        if episode_video_model(ctx.episode) != "MiniMax-H3":
            return []  # the retry perturbation (prompt sentence, @Image1 bytes) exists for H3 only
    except Exception:  # noqa: BLE001 - unknown model: do not measure
        return []
    import h3_burn_retry as _br
    retry_max = _br.max_retries()
    state_path = _wave_state_path(ctx)
    out: list[dict[str, Any]] = []
    # a final-fix redo take is measured by the fix round's own loop (2026-11-20: a burned-text redo is detected and
    # retried with an escalated perturbation inside NALU_FINAL_FIX_BUDGET_CREDITS), never by the S6 retry counter
    final_fix_units = set(((read_json(final_fix_redo_path(ctx), {}) or {}).get("units") or {}))
    for uid in unit_ids:
        clip = ctx.p.video_media / f"{uid}.mp4"
        if not clip.is_file():
            continue
        clip_sha = sha256_file(clip)
        if _tail_is_current(ctx, uid, clip_sha):
            continue
        if uid in final_fix_units:
            fix_row = s6_final_fix_burn_check(ctx, uid, clip, clip_sha)
            if fix_row:
                out.append(fix_row)
            continue
        state = read_json(state_path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
        rec = dict((state.get(_br.STATE_KEY) or {}).get(uid) or {})
        pending_attempt = _s6_burn_attempt_awaiting_take(rec)
        if clip_sha in (rec.get("checks") or {}) and not pending_attempt:
            continue  # this exact take was already measured and decided
        if clip_sha in (rec.get("checks") or {}):
            # a submitted retry came back byte-identical to an earlier take (E23 device 1101, 2026-11-22): used to
            # be skipped as "already measured", leaving the record RETRY_SUBMITTED and the burned take unflagged
            ctx.say(f"{_br.SAME_RENDER_LOG} unit={uid} retry={pending_attempt.get('retry')} "
                    f"take={clip_sha[:12]} (byte-identical to an earlier take)")
        det = _br.detect(clip, lines=s6_unit_lines(ctx, uid), lang=ctx_language(ctx))
        _s6_burn_note_fail_open(ctx, uid, det)
        # a take that shows the unit's identity sheet as its picture is never CLEAN (JA-01 E04 VU-007 2026-11-21:
        # "clean" only because H3 drew the reference sheet instead of text) -- retried like burned text
        det = _br.combine_sheet_leak(det, s6_sheet_leak_check(ctx, uid, clip))
        attempts = list(rec.get("attempts") or [])
        # camera wobble (KO E05 2026-11-21): a locked-off unit whose take moves the set with the actor -- measured
        # only when the take carries no burned text (burned text is retried first, with its own sentence)
        wob = s6_camera_wobble_check(ctx, uid, clip) if det.get("status") != "BURNED" else None
        wobble = bool(wob and wob.get("status") == "WOBBLE")
        check = {k: det.get(k) for k in ("status", "frames_sampled", "burned_frames", "longest_run", "elapsed_ms",
                                         "error", _br.SHEET_LEAK_FLAG, "sheet_leak") if det.get(k) is not None}
        check.update(at=now(), retry=len(attempts), hits=(det.get("hits") or [])[:6])
        if det.get("status") == "BURNED" and det.get("ocr_frames"):
            # per-frame band OCR (text, conf, box) of a burned take: S7's strict burned-line check reads it instead of
            # re-reading the clip when the recogniser fits the dialogue language (owner 2026-11-23)
            check.update(ocr_frames=det.get("ocr_frames"), ocr_model=det.get("ocr_model"))
        if det.get("suspect_hits"):
            check["suspect_hits"] = det["suspect_hits"]
        if wob is not None:
            check[_br.WOBBLE_FLAG] = _wob_summary(wob)
        if det.get("status") != "BURNED" and not attempts and not wobble:
            continue  # clean first take: nothing to record
        rec.setdefault("checks", {})[clip_sha] = check
        takes = list(rec.get("takes") or [])
        # per-attempt request evidence (2026-11-22): the content fingerprint of the request that rendered this take
        # (prompt sha + every sent reference sha, from the bound transaction) and the returned clip sha
        request = _s6_take_request(ctx, uid)
        landed = _s6_burn_note_take(ctx, uid, attempts, takes, request, clip_sha, det)
        takes.append({"sha256": clip_sha, "retry": len(attempts), "burned_frames": int(det.get("burned_frames") or 0),
                      "status": det.get("status"), "path": str(clip),
                      **({"request": request} if request else {}), **landed,
                      **({_br.SHEET_LEAK_FLAG: True} if det.get(_br.SHEET_LEAK_FLAG) else {}),
                      **({_br.WOBBLE_FLAG: True, "wobble_pct": float((wob.get("metrics") or {}).get("excursion_pct")
                                                                      or 0.0)} if wobble else {})})

        def retry_terms() -> tuple[int, int | None, bool]:
            seconds = next((float(t.get("duration_seconds") or 0) for t in
                            (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []
                            if str(t.get("unit_id") or t.get("task_key")) == uid), 0.0) or 6.0
            cost_ = video_task_credits(episode_video_model(ctx.episode), seconds, 1,
                                       episode_video_resolution(ctx.episode))
            headroom_ = None
            try:
                verdict = ctx.budget_check(0, label="s6_burn_retry_headroom").get("budget_verdict") or {}
                headroom_ = verdict.get("headroom_credits")
            except Exception as exc:  # noqa: BLE001 - unknown headroom: no retry
                ctx.say(f"   S6 burn retry: budget headroom unavailable ({type(exc).__name__})")
            try:
                accepted_ = uid in _owner_accepted_clips(ctx, {uid: {}})
            except Exception:  # noqa: BLE001 - no readable orders: nothing accepted
                accepted_ = False
            return cost_, None if headroom_ is None else int(headroom_), accepted_

        decision: dict[str, Any]
        if det.get("status") == "BURNED" and retry_max > 0 and len(attempts) < retry_max:
            cost, headroom, accepted = retry_terms()
            decision = _br.plan(rec, det, retry_max=retry_max, headroom=headroom, cost=cost,
                                owner_accepted=accepted)
        elif det.get("status") != "BURNED" and wobble:
            import h3_camera_wobble as _wobm  # noqa: PLC0415 - engine tools/, like h3_burn_retry
            wob_max = _wobm.max_retries()
            if wob_max > 0 and len(attempts) < retry_max:
                cost, headroom, accepted = retry_terms()
            else:
                cost, headroom, accepted = 0, 0, False
            decision = _wobm.plan(rec, wob, retry_max=wob_max, total_max=retry_max, headroom=headroom, cost=cost,
                                  owner_accepted=accepted)
        else:
            decision = _br.plan(rec, det, retry_max=retry_max, headroom=0, cost=0)
        frames = f"{det.get('burned_frames')}/{det.get('frames_sampled')}"
        if det.get("status") == "BURNED":
            ctx.say(f"S6_BURN_DETECTED unit={uid} frames={frames} retry={len(attempts)}/{retry_max} "
                    + ("reference_sheet_leak=1 " if det.get(_br.SHEET_LEAK_FLAG) else "")
                    + f"elapsed={det.get('elapsed_ms')}ms -> {decision['action']} ({decision['reason']})")
        row = {"unit_id": uid, "clip_sha256": clip_sha, "detection": check, **decision}
        if det.get(_br.SHEET_LEAK_FLAG):  # global MODEL_CONSTRAINT lesson (best-effort, never into the stage)
            row["kb"] = kb_events("record_s6_reference_sheet_leak", episode=ctx.episode, unit_id=uid,
                                  detection=det.get("sheet_leak") or {}, clip_sha256=clip_sha)
        if wobble:
            ctx.say(f"S6_CAMERA_WOBBLE unit={uid} {_wob_summary(wob)} retry={len(attempts)}/{retry_max} -> "
                    f"{decision['action']} ({decision['reason']})")
            row["kb"] = kb_events("record_s6_camera_wobble", episode=ctx.episode, unit_id=uid,
                                  detection=_wob_summary(wob), clip_sha256=clip_sha)
        if decision["action"] == "RETRY":
            n = int(decision["retry"])
            park = ctx.p.video_media / f"_superseded_{ctx.run_id}_burn_retry{n}"
            park.mkdir(parents=True, exist_ok=True)
            os.replace(clip, park / clip.name)
            takes[-1]["path"] = str(park / clip.name)
            attempts.append({"retry": n, "failed_clip_sha256": clip_sha, "burned_frames": det.get("burned_frames"),
                             "parked_clip": str(park / clip.name), "cost": decision.get("cost"),
                             # the retry after a sheet leak sends the sheets as front-view crops + the sheet sentence
                             **({_br.SHEET_LEAK_FLAG: True} if det.get(_br.SHEET_LEAK_FLAG) else {}),
                             # the retry after a camera wobble carries the locked-off sentence
                             **({_br.WOBBLE_FLAG: True, "wobble": _wob_summary(wob)}
                                if wobble and det.get("status") != "BURNED" else {}),
                             "run_id": ctx.run_id, "recorded_at": now(), "recorded_by": TOOL_ID})
            rec.update(status="RETRY_PENDING", attempts=attempts)
            row["parked_clip"] = str(park / clip.name)
        elif decision["action"] == "KEEP":
            rec.update(status="RESOLVED" if det.get("status") == "CLEAN" else "KEPT_DETECTOR_FAIL_OPEN",
                       resolved_take_sha256=clip_sha, **{_br.UNRESOLVED_FLAG: False, "camera_wobble_unresolved": False})
            ctx.say(f"S6_BURN_RESOLVED unit={uid} retry={len(attempts)}/{retry_max} frames={frames}"
                    + ("" if det.get("status") == "CLEAN" else f" (detector {det.get('status')})"))
        else:
            best = _br.best_take(takes) or takes[-1]
            if best.get("sha256") != clip_sha and best.get("path") and Path(best["path"]).is_file():
                park = ctx.p.video_media / f"_superseded_{ctx.run_id}_burn_retry_final"
                park.mkdir(parents=True, exist_ok=True)
                os.replace(clip, park / clip.name)
                takes[-1]["path"] = str(park / clip.name)
                os.replace(best["path"], clip)
                row["restored_take"] = {"sha256": best["sha256"], "from": best["path"], "retry": best.get("retry")}
                best = {**best, "path": str(clip)}
                for take in takes:
                    if take.get("sha256") == best["sha256"]:
                        take["path"] = str(clip)
            # where the kept take's text sits: in our subtitle band it would stack under our caption (JA-01 E04
            # VU-004) -- S7 moves that caption above it and the final fix round gets the unit (2026-11-21)
            band = _br.residual_text_band(((rec.get("checks") or {}).get(best["sha256"]) or {}).get("hits"))
            kept_check = (rec.get("checks") or {}).get(best["sha256"]) or {}
            if band:  # what the burned line says: S7 suppresses our cue when it is the same line (E07 VU-004)
                band = {**band, "texts": _br.residual_band_texts(kept_check.get("hits"))}
            wobble_path = det.get("status") != "BURNED" and wobble
            burned_left = (not wobble_path) or int(best.get("burned_frames") or 0) > 0 \
                or bool(best.get(_br.SHEET_LEAK_FLAG))
            rec.update(status="UNRESOLVED", unresolved_reason=decision["reason"], kept_take_sha256=best["sha256"],
                       kept_take_burned_frames=best.get("burned_frames"), kept_take_retry=best.get("retry"),
                       kept_take_sheet_leak=bool(best.get(_br.SHEET_LEAK_FLAG)), residual_text_band=band,
                       camera_wobble_unresolved=bool(best.get(_br.WOBBLE_FLAG)),
                       kept_take_wobble=kept_check.get(_br.WOBBLE_FLAG) if best.get(_br.WOBBLE_FLAG) else None,
                       **{_br.UNRESOLVED_FLAG: burned_left})
            rec.setdefault("checks", {})[best["sha256"]] = {**(rec["checks"].get(best["sha256"]) or {}),
                                                            "kept_as_best": True}
            ctx.say(f"S6_BURN_UNRESOLVED unit={uid} retry={len(attempts)}/{retry_max} reason={decision['reason']} "
                    f"kept_take={str(best['sha256'])[:12]} burned_frames={best.get('burned_frames')}"
                    + (" reference_sheet_leak=1" if best.get(_br.SHEET_LEAK_FLAG) else "")
                    + (f" subtitle_band_text={band['y0']}-{band['y1']} (S7 moves our caption above it; final fix "
                       "round)" if band else ""))
            row["kept_take_sha256"] = best["sha256"]
        rec["takes"] = takes
        rec["updated_at"] = now()
        state = read_json(state_path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
        state.setdefault(_br.STATE_KEY, {})[uid] = rec
        write_json(state_path, state)
        out.append(row)
    return out


def _s6_burn_attempt_awaiting_take(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """The unit's latest burn-retry attempt when it was submitted and no take of it was measured yet, else None."""
    attempts = list((rec or {}).get("attempts") or [])
    last = attempts[-1] if attempts else None
    if isinstance(last, dict) and last.get("submitted_at") and not last.get("landed_clip_sha256"):
        return last
    return None


def _s6_take_request(ctx: Ctx, uid: str) -> dict[str, Any] | None:
    """The request content fingerprint (h3_burn_retry.request_fingerprint) of the unit's newest bound transaction in
    the durable store -- the request that rendered the take that just landed.  None when unknown; never raises."""
    try:
        import h3_burn_retry as _br  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415
        best, best_at = None, None
        store = video_store_dir(ctx.episode)
        for path in (store.glob(f"{uid}__*.json") if store.is_dir() else []):
            row = read_json(path, {}) or {}
            if row.get("state") != "SUBMITTED_TASK_ID_BOUND" or not row.get("task_id"):
                continue
            stamp = str(row.get("response_recorded_at") or row.get("intent_recorded_at") or "")
            try:
                at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if best_at is None or at > best_at:
                best, best_at = row, at
        fp = _br.request_fingerprint(best)
        if fp is None:
            return None
        return {**fp, "task_id": best.get("task_id"),
                "perturbation": next((n.get("burn_retry_perturbation", {}).get("method")
                                      for n in best.get("reference_encoding_notes") or []
                                      if isinstance(n, dict) and n.get("burn_retry_perturbation")), None)}
    except Exception:  # noqa: BLE001 - evidence only
        return None


def _s6_burn_note_take(ctx: Ctx, uid: str, attempts: list[dict[str, Any]], takes: list[dict[str, Any]],
                       request: dict[str, Any] | None, clip_sha: str, det: dict[str, Any]) -> dict[str, Any]:
    """Per-attempt evidence of a landed burn-retry take (2026-11-22, E23 device 1101: five units, three takes each,
    near-identical burned-frame counts).  Compares the take's request fingerprint and returned clip with the
    previous take of the unit and says ``S6_BURN_RETRY_SAME_REQUEST`` (the provider got the identical request
    again: the retry could not render anything new) / ``S6_BURN_RETRY_SAME_RENDER`` (byte-identical clip).  Marks
    the pending attempt with the landed clip.  Returns the take-row fields; mutates ``attempts`` in place."""
    import h3_burn_retry as _br  # noqa: PLC0415
    texts = sorted({str(h.get("text") or "") for h in det.get("hits") or []})
    out: dict[str, Any] = {"burn_texts": texts}
    previous = takes[-1] if takes else None
    if previous is None or not attempts:
        return out
    delta = _br.request_delta(previous.get("request"), request)
    out["request_delta"] = delta
    same_render = any(t.get("sha256") == clip_sha for t in takes)
    same_burn = (int(previous.get("burned_frames") or 0) == int(det.get("burned_frames") or 0)
                 and det.get("status") == "BURNED" and texts == previous.get("burn_texts"))
    last = attempts[-1]
    if not last.get("landed_clip_sha256"):
        last.update(landed_clip_sha256=clip_sha, landed_burned_frames=det.get("burned_frames"),
                    request_digest=(request or {}).get("digest"), request_delta=delta,
                    perturbation=(request or {}).get("perturbation"),
                    **({"same_render": True} if same_render else {}), **({"same_burn": True} if same_burn else {}))
    if delta["status"] == "SAME":
        out["same_request"] = True
        last["same_request"] = True
        ctx.say(f"{_br.SAME_REQUEST_LOG} unit={uid} retry={last.get('retry')} request={str(request.get('digest'))[:12]}"
                " -- the retry sent the identical prompt and reference bytes; nothing new could render")
    if same_render:
        out["same_render"] = True
    if same_burn:
        ctx.say(f"S6_BURN_RETRY_SAME_BURN unit={uid} retry={last.get('retry')} frames={det.get('burned_frames')} "
                f"request_changed={','.join(delta.get('changed') or []) or delta['status']}")
    return out


def _wob_summary(det: dict[str, Any] | None) -> dict[str, Any]:
    import h3_camera_wobble as _wobm  # noqa: PLC0415
    return _wobm.summary(det)


def s6_camera_wobble_check(ctx: Ctx, uid: str, clip: Path) -> dict[str, Any] | None:
    """Camera-wobble check of a landed take (tools/h3_camera_wobble.detect, free, advisory; KO E05 on device ...0080
    2026-11-21: "the person AND the background move together").  Only for a unit whose compiled camera plans are
    all locked off (a deliberate move is authored); None for any other unit, when NALU_S6_WOBBLE_CHECK=off, or on
    any error (fail-open)."""
    if str(os.environ.get("NALU_S6_WOBBLE_CHECK") or "").strip().lower() in ("off", "0", "false"):
        return None
    try:
        import h3_camera_wobble as _wobm  # noqa: PLC0415 - engine tools/, like h3_burn_retry
        task = next((t for t in (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []
                     if str(t.get("unit_id") or t.get("task_key")) == uid), None)
        if _wobm.static_plan(task) is not True:
            return None
        return _wobm.detect(clip, plan_static=True)
    except Exception as exc:  # noqa: BLE001 - advisory: never blocks
        return {"status": "FAIL_OPEN", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def s6_sheet_leak_check(ctx: Ctx, uid: str, clip: Path) -> dict[str, Any] | None:
    """Reference-sheet leak check of a landed take (tools/h3_reference_sheet_guard.detect_leak, free, advisory):
    does the picture show one of the multi-view identity sheets the unit's compiled task sent?  None when the task
    sent no sheet (most units; nothing measured) or on any error."""
    try:
        import h3_reference_sheet_guard as _sg  # noqa: PLC0415 - engine tools/, like h3_burn_retry
        task = next((t for t in (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []
                     if str(t.get("unit_id") or t.get("task_key")) == uid), None)
        sheets = [p if p.is_absolute() else ENGINE / p for p in _sg.unit_sheets(task)]
        if not sheets:
            return None
        return _sg.detect_leak(clip, sheets)
    except Exception as exc:  # noqa: BLE001 - advisory: never blocks
        return {"status": "FAIL_OPEN", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def s7_residual_burn_bands(ctx: Ctx) -> Path | None:
    """``<EP>_S6_RESIDUAL_BURN_BANDS.json`` {units: {uid: {y0, y1}}} of units whose kept S6 take still carries burned
    text in our subtitle band (``s6_burn_retry`` UNRESOLVED + residual_text_band), for build_burnin_subtitles
    --avoid-bands: that unit's captions are drawn above the burned line instead of stacking on it (JA-01 E04 VU-004,
    2026-11-21).  None when there is none."""
    import h3_burn_retry as _br
    units = {}
    for uid, rec in ((read_json(_wave_state_path(ctx), {}) or {}).get(_br.STATE_KEY) or {}).items():
        band = rec.get("residual_text_band") if isinstance(rec, dict) else None
        if isinstance(band, dict) and rec.get(_br.UNRESOLVED_FLAG) and band.get("y0") is not None:
            clip = ctx.p.video_media / f"{uid}.mp4"
            if rec.get("kept_take_sha256") and clip.is_file() and sha256_file(clip) != rec["kept_take_sha256"]:
                continue  # the unit was redone since: the band belongs to a superseded take
            # the OCR text of the burned line (JA-01 E07 VU-004 2026-11-22): build_burnin_subtitles suppresses our
            # cue when it is the same line (it is already on screen) instead of stacking a second copy above it
            texts = list(band.get("texts") or []) or _br.residual_band_texts(
                (((rec.get("checks") or {}).get(rec.get("kept_take_sha256")) or {}).get("hits")))
            units[str(uid)] = {"y0": float(band["y0"]), "y1": float(band["y1"]), **({"texts": texts} if texts else {}),
                               "ocr": s7_burned_line_ocr(ctx, clip, rec)}
    if not units:
        return None
    path = ctx.p.assembly / f"{ctx.episode}_S6_RESIDUAL_BURN_BANDS.json"
    write_json(path, {"schema": "nalu.s6_residual_burn_bands.v1", "episode": ctx.episode, "units": units,
                      "recorded_at": now(), "recorded_by": TOOL_ID})
    return path


def s7_burned_line_ocr(ctx: Any, clip: Path, rec: dict[str, Any]) -> dict[str, Any]:
    """Per-frame band OCR of a unit's kept take for the strict burned-line check (build_burnin_subtitles,
    owner 2026-11-23): a re-read of the kept take at h3_burn_retry.STRICT_FPS (12 fps, the prototype's rate) with
    the recogniser of the dialogue language (zh / en: RapidOCR's bundled one; ja / ko: tools/ocr_lang_models) --
    a few seconds per unresolved unit, free.  The S6 detection's 4 fps ``ocr_frames`` are the fallback when the
    re-read fails and they were read with the right recogniser (at 4 fps a steady line can measure as jittery: the
    check then rejects, never wrongly accepts).  {error} when neither exists -- the check cannot accept and our cue
    stays.  Never raises."""
    lang = ctx_language(ctx)
    try:
        import h3_burn_retry as _br  # noqa: PLC0415
        import ocr_lang_models as _olm  # noqa: PLC0415
        need = _olm.model_id(lang)
        kept = ((rec.get("checks") or {}).get(rec.get("kept_take_sha256")) or {}) if isinstance(rec, dict) else {}
        fresh = _br.ocr_band_frames(Path(clip), lang) if Path(clip).is_file() else {"error": "KEPT_TAKE_MISSING"}
        if fresh.get("frames") and not fresh.get("error"):
            return fresh
        if kept.get("ocr_frames") and kept.get("ocr_model") == need:
            return {"source": "S6_KEPT_TAKE", "model": need, "lang": lang, "sample_fps": _br.SAMPLE_FPS,
                    "frames": kept["ocr_frames"], "reread_error": fresh.get("error")}
        return {"source": "NONE", "lang": lang, "error": fresh.get("error") or "NO_OCR_FRAMES"}
    except Exception as exc:  # noqa: BLE001
        return {"source": "NONE", "lang": lang, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _s6_burn_note_fail_open(ctx: Ctx, uid: str, det: dict[str, Any]) -> None:
    """Say once per run when the burned-text detector cannot measure (OCR / OpenCV missing): a clean first take
    leaves no record at all, so without this line "no S6_BURN_* in the log" cannot tell CLEAN from not measured
    (E18 2026-11-20 investigation)."""
    if det.get("status") != "FAIL_OPEN" or getattr(ctx, "_s6_burn_fail_open_said", False):
        return
    try:
        ctx._s6_burn_fail_open_said = True
    except Exception:  # noqa: BLE001 - a frozen ctx: say it every time
        pass
    ctx.say(f"S6_BURN_DETECTOR_FAIL_OPEN unit={uid} error={str(det.get('error') or '')[:160]} "
            "(burned text is NOT being measured on this device)")


def s6_final_fix_burn_check(ctx: Ctx, uid: str, clip: Path, clip_sha: str) -> dict[str, Any] | None:
    """Burned-text detection + escalated retry of a final-fix redo take (owner 2026-11-20; E18 device 1101: three
    of four burned-text redos burned the same line again and the round never looked).

    Only for units the round redid for BURNED_TEXT.  The same local OCR as S6 (h3_burn_retry.detect; one sample
    with a hit is enough here -- the reviewer already confirmed the burn) runs on the landed redo take.  Still
    burned, with retries left (NALU_FINAL_FIX_BURN_RETRY_MAX, at most 2) and both the round's remaining budget
    (NALU_FINAL_FIX_BUDGET_CREDITS minus the planned redos minus earlier retries) and the episode headroom covering
    one more take: the take is parked to ``video/_superseded_<run>_final_fix_burn<n>/`` and the redo record gets
    ``burn_retry`` = n and the retry-indexed clean-picture sentence (final_fix_round.BURN_RETRY_SENTENCES); the
    recompile carries both, and the submitter perturbs @Image1 more strongly (1-2 % crop/scale jitter + a new JPEG
    quality, h3_burn_retry.perturb_start_frame_strong).  Otherwise the redo take with the fewest burned frames is
    kept.  Records live in ``reports/<EP>_FINAL_FIX_REDO.json``.  Never blocks; the detector fails open."""
    import final_fix_round as _ffr
    import h3_burn_retry as _br
    path = final_fix_redo_path(ctx)
    state = read_json(path, {}) or {}
    rec = dict((state.get("units") or {}).get(uid) or {})
    if "BURNED_TEXT" not in (rec.get("kinds") or [rec.get("kind")]):
        return None  # a costume / face / sheen redo is that unit's one take of the round
    checks = dict(rec.get("burn_checks") or {})
    if clip_sha in checks or clip_sha == rec.get("parked_clip_sha256"):
        return None
    det = _br.detect(clip, min_consecutive=1, lines=s6_unit_lines(ctx, uid), lang=ctx_language(ctx))
    _s6_burn_note_fail_open(ctx, uid, det)
    retries = list(rec.get("burn_retries") or [])
    checks[clip_sha] = {**{k: det.get(k) for k in ("status", "frames_sampled", "burned_frames", "longest_run",
                                                   "elapsed_ms", "error") if det.get(k) is not None},
                        "at": now(), "retry": len(retries), "hits": (det.get("hits") or [])[:6]}
    takes = list(rec.get("burn_takes") or [])
    request = _s6_take_request(ctx, uid)  # per-attempt request evidence, as in S6 (2026-11-22)
    landed = _s6_burn_note_take(ctx, uid, retries, takes, request, clip_sha, det)
    takes.append({"sha256": clip_sha, "retry": len(retries), "burned_frames": int(det.get("burned_frames") or 0),
                  "status": det.get("status"), "path": str(clip), **({"request": request} if request else {}),
                  **landed})
    retry_max = _ffr.burn_retry_max()
    cost, budget_left, headroom = 0, None, None
    if det.get("status") == "BURNED" and len(retries) < retry_max:
        seconds = next((float(t.get("duration_seconds") or 0) for t in
                        (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []
                        if str(t.get("unit_id") or t.get("task_key")) == uid), 0.0) or 6.0
        cost = video_task_credits(episode_video_model(ctx.episode), seconds, 1, episode_video_resolution(ctx.episode))
        budget_left = _ffr.round_budget_left(read_json(final_fix_record_path(ctx), {}) or {}, state)
        try:
            verdict = ctx.budget_check(0, label="final_fix_burn_retry_headroom").get("budget_verdict") or {}
            headroom = None if verdict.get("headroom_credits") is None else int(verdict["headroom_credits"])
        except Exception as exc:  # noqa: BLE001 - unknown headroom: no retry
            ctx.say(f"   final fix burn retry: budget headroom unavailable ({type(exc).__name__})")
    decision = _ffr.plan_burn_retry(rec, det, retry_max=retry_max, budget_left=budget_left, headroom=headroom,
                                    cost=cost)
    frames = f"{det.get('burned_frames')}/{det.get('frames_sampled')}"
    row: dict[str, Any] = {"unit_id": uid, "clip_sha256": clip_sha, "final_fix": True,
                           "detection": checks[clip_sha], **decision}
    if decision["action"] == "RETRY":
        n = int(decision["retry"])
        park = ctx.p.video_media / f"_superseded_{ctx.run_id}_final_fix_burn{n}"
        park.mkdir(parents=True, exist_ok=True)
        os.replace(clip, park / clip.name)
        takes[-1]["path"] = str(park / clip.name)
        rows, chars = _final_fix_wardrobe(ctx, uid) if "COSTUME_IDENTITY" in (rec.get("kinds") or []) else ([], [])
        sentence = _ffr.redo_sentence(rec.get("kinds") or [rec.get("kind")], wardrobe_rows=rows,
                                      character_ids=chars, burn_retry=n)
        retries.append({"retry": n, "failed_clip_sha256": clip_sha, "burned_frames": det.get("burned_frames"),
                        "parked_clip": str(park / clip.name), "cost": decision.get("cost"),
                        "budget_left_before": budget_left, "previous_sentence": rec.get("sentence"),
                        "sentence": sentence, "run_id": ctx.run_id, "recorded_at": now(), "recorded_by": TOOL_ID})
        rec.update(burn_retry=n, burn_retries=retries, sentence=sentence, status="BURN_RETRY_PENDING",
                   burn_status="RETRY_PENDING")
        row["parked_clip"] = str(park / clip.name)
        ctx.say(f"FINAL_FIX_BURN_RETRY unit={uid} frames={frames} retry={n}/{retry_max} cost={decision.get('cost')} "
                f"budget_left={budget_left}")
    elif decision["action"] == "KEEP":
        rec.update(burn_status="RESOLVED" if det.get("status") == "CLEAN" else "KEPT_DETECTOR_FAIL_OPEN",
                   kept_take_sha256=clip_sha, kept_take_burned_frames=0, status="LANDED")
        ctx.say(f"FINAL_FIX_BURN_RESOLVED unit={uid} retry={len(retries)}/{retry_max} frames={frames}"
                + ("" if det.get("status") == "CLEAN" else f" (detector {det.get('status')})"))
    else:
        best = _br.best_take(takes) or takes[-1]
        if best.get("sha256") != clip_sha and best.get("path") and Path(best["path"]).is_file():
            park = ctx.p.video_media / f"_superseded_{ctx.run_id}_final_fix_burn_final"
            park.mkdir(parents=True, exist_ok=True)
            os.replace(clip, park / clip.name)
            takes[-1]["path"] = str(park / clip.name)
            os.replace(best["path"], clip)
            row["restored_take"] = {"sha256": best["sha256"], "from": best["path"], "retry": best.get("retry")}
            for take in takes:
                if take.get("sha256") == best["sha256"]:
                    take["path"] = str(clip)
        # the cap arithmetic is recorded with the decision (E23 device 1101, 2026-11-22: FINAL_FIX_BUDGET_CAP next to
        # an episode headroom of 1341 read as a misjudgment; the round cap NALU_FINAL_FIX_BUDGET_CREDITS minus the
        # planned redos minus earlier retries is the limit, the episode headroom is a second, separate one)
        budget = ({"cost": decision.get("cost"), "round_budget_left": decision.get("budget_left"),
                   "round_cap": _ffr.budget_credits(), "episode_headroom": headroom}
                  if decision["reason"] in ("FINAL_FIX_BUDGET_CAP", "BUDGET_HEADROOM_SHORT") else None)
        rec.update(burn_status="UNRESOLVED", burn_unresolved_reason=decision["reason"],
                   kept_take_sha256=best["sha256"], kept_take_burned_frames=best.get("burned_frames"),
                   kept_take_retry=best.get("retry"), status="LANDED", **({"burn_unresolved_budget": budget}
                                                                          if budget else {}))
        checks.setdefault(best["sha256"], {})["kept_as_best"] = True
        ctx.say(f"FINAL_FIX_BURN_UNRESOLVED unit={uid} retry={len(retries)}/{retry_max} reason={decision['reason']} "
                f"kept_take={str(best['sha256'])[:12]} burned_frames={best.get('burned_frames')}"
                + (f" cost={budget['cost']} round_budget_left={budget['round_budget_left']} "
                   f"round_cap={budget['round_cap']} episode_headroom={budget['episode_headroom']}" if budget else ""))
        row["kept_take_sha256"] = best["sha256"]
    rec.update(burn_checks=checks, burn_takes=takes, updated_at=now())
    state = read_json(path, {}) or {}
    state.setdefault("units", {})[uid] = rec
    write_json(path, state)
    return row


def final_fix_burn_summary(redo_state: dict[str, Any] | None) -> dict[str, Any]:
    """unit -> {status, retries, kept_burned_frames, reason} of the round's burned-text redos (for the record)."""
    out = {}
    for uid, rec in ((redo_state or {}).get("units") or {}).items():
        if not isinstance(rec, dict) or "BURNED_TEXT" not in (rec.get("kinds") or [rec.get("kind")]):
            continue
        out[str(uid)] = {"status": rec.get("burn_status") or "NOT_MEASURED",
                         "retries": len(rec.get("burn_retries") or []),
                         "retry_credits": sum(float(r.get("cost") or 0) for r in rec.get("burn_retries") or []),
                         **({"kept_burned_frames": rec["kept_take_burned_frames"]}
                            if rec.get("kept_take_burned_frames") is not None else {}),
                         **({"reason": rec["burn_unresolved_reason"]} if rec.get("burn_unresolved_reason") else {})}
    return out


def s6_final_fix_finalization_receipts(ctx: Ctx, unbound: list[str], fin_report: dict[str, Any],
                                       fin_digest: Path) -> dict[str, Any]:
    """Engine receipts for final-fix redo prompts (final_fix_round.py, owner 2026-11-20) whose ONLY change from an
    already-approved prompt is the round's redo sentence: the final prompt minus exactly that sentence equals the
    batch-PLANNED prompt, the reviewer's PASS receipt, or the engine's burn-retry receipt (also: one of those plus
    exactly a burn-retry sentence).  Writes ``prompt_batch_finalization/<unit>.final_fix.json`` and attaches it;
    anything else still goes to the reviewer."""
    import final_fix_round as _ffr
    import h3_burn_retry as _br
    redo = (read_json(final_fix_redo_path(ctx), {}) or {}).get("units") or {}
    rows = {str(r.get("unit_id")): r for r in fin_report.get("rows") or []}
    fin_dir = ctx.p.preprod / "prompt_batch_finalization"
    tx = read_json(ctx.p.video_transaction, {}) or {}
    done: dict[str, Any] = {}

    def approved(sha: str, uid: str) -> str | None:
        if sha == (rows.get(uid) or {}).get("planned_sha256"):
            return "PLANNED_PROMPT"
        for name, label in ((f"{uid}.json", "REVIEWER_RECEIPT"), (f"{uid}.burn_retry.json", "BURN_RETRY_RECEIPT")):
            receipt = read_json(fin_dir / name, {}) or {}
            if receipt.get("status") == "PASS" and receipt.get("final_prompt_sha256") == sha:
                return label
        return None

    for uid in unbound:
        rec, row = redo.get(uid) or {}, rows.get(uid) or {}
        if not rec.get("sentence") or row.get("status") != "CHANGED":
            continue
        task = next((t for t in tx.get("tasks") or [] if t.get("unit_id") == uid), None)
        if task is None or not task.get("prompt_file"):
            continue
        final_path = Path(str(task["prompt_file"]))
        final_path = final_path if final_path.is_absolute() else ENGINE / final_path
        if not final_path.is_file() or sha256_file(final_path) != row.get("final_sha256"):
            continue
        base, found = _ffr.strip_sentence(final_path.read_text(encoding="utf-8"), rec["sentence"])
        if not found:
            continue
        authority = approved(sha256_text(base), uid)
        if authority is None:
            plain, index = _br.strip_retry_sentence(base)
            authority = (approved(sha256_text(plain), uid) + "+BURN_RETRY_SENTENCE"
                         if index and approved(sha256_text(plain), uid) else None)
        if authority is None:
            continue
        fin_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = fin_dir / f"{uid}.final_fix.json"
        write_json(receipt_path, {
            "status": "PASS", "execution_id": f"{ctx.episode}-PROMPT-BATCH-V1", "unit_id": uid,
            "artifact_kind": "video_prompt", "planned_prompt_sha256": row["planned_sha256"],
            "final_prompt_sha256": row["final_sha256"], "scope": "INCREMENTAL_EXACT_MATERIALIZATION_QA",
            "reviewer": "nalu_pipeline:FINAL_FIX_ROUND", "review_method": "ENGINE_EXACT_SENTENCE_DELTA",
            "reviewed_at": now(), "changed_line_count": 1, "final_fix_kinds": rec.get("kinds"),
            "base_prompt_sha256": sha256_text(base), "base_authority": authority,
            "reviewer_observation": ("the final prompt is the approved prompt plus exactly the final fix round's redo "
                                     "sentence (line owner 2026-11-20: never wait on quality)"),
            "digest_sha256": sha256_file(fin_digest)})
        try:
            ref_path = str(receipt_path.resolve().relative_to(ENGINE.resolve()))
        except ValueError:
            ref_path = str(receipt_path.resolve())
        task["prompt_batch_finalization"] = {"path": ref_path, "sha256": sha256_file(receipt_path)}
        task["prompt_sha256"] = row["final_sha256"]
        done[uid] = {"receipt": str(receipt_path), "base_authority": authority}
    if done:
        write_json(ctx.p.video_transaction, tx)
    return done

def _s6_sync_burn_state(wave_state: dict[str, Any], path: Path) -> None:
    """stage_s6 holds the wave state in memory and rewrites the whole file: carry the burn-retry records
    (written to disk by s6_burn_check_landed / s6_burn_retry_note_posted) into that copy so they survive."""
    import h3_burn_retry as _br
    fresh = (read_json(path, {}) or {}).get(_br.STATE_KEY)
    if fresh is not None:
        wave_state[_br.STATE_KEY] = fresh


def s6_burn_retry_note_posted(ctx: Ctx, posted: list[str]) -> list[str]:
    """``S6_BURN_RETRY_SUBMITTED`` for every posted unit whose burn retry was pending; marks the attempt."""
    import h3_burn_retry as _br
    path = _wave_state_path(ctx)
    state = read_json(path, {}) or {}
    records = state.get(_br.STATE_KEY) or {}
    noted = []
    for uid in posted:
        rec = records.get(uid) or {}
        attempts = rec.get("attempts") or []
        if rec.get("status") != "RETRY_PENDING" or not attempts or attempts[-1].get("submitted_at"):
            continue
        attempts[-1]["submitted_at"] = now()
        rec["status"] = "RETRY_SUBMITTED"
        noted.append(uid)
        ctx.say(f"S6_BURN_RETRY_SUBMITTED unit={uid} retry={attempts[-1].get('retry')}/{_br.max_retries()}")
    if noted:
        write_json(path, state)
    fix_path = final_fix_redo_path(ctx)
    fix_state = read_json(fix_path, {}) or {}
    fix_noted = []
    for uid in posted:
        rec = (fix_state.get("units") or {}).get(uid) or {}
        retries = rec.get("burn_retries") or []
        if rec.get("status") != "BURN_RETRY_PENDING" or not retries or retries[-1].get("submitted_at"):
            continue
        retries[-1]["submitted_at"] = now()
        rec["status"] = "BURN_RETRY_SUBMITTED"
        fix_noted.append(uid)
        ctx.say(f"FINAL_FIX_BURN_RETRY_SUBMITTED unit={uid} retry={retries[-1].get('retry')}")
    if fix_noted:
        write_json(fix_path, fix_state)
    return noted + fix_noted


def s6_burn_retry_finalization_receipts(ctx: Ctx, unbound: list[str], fin_report: dict[str, Any],
                                        fin_digest: Path) -> dict[str, Any]:
    """Engine receipts for burn-retry prompts whose ONLY change from an already-approved prompt is the engine's
    retry sentence (h3_burn_retry.apply_retry_sentence; owner-approved automatic retry 2026-11-19).

    For each changed unit with a burn-retry record: strip the retry sentence from the final prompt; when the rest
    is byte-identical to the batch-PLANNED prompt or to the final prompt of the reviewer's PASS receipt
    (``prompt_batch_finalization/<unit>.json``), write ``prompt_batch_finalization/<unit>.burn_retry.json`` (same
    INCREMENTAL_EXACT_MATERIALIZATION_QA fields the batch gate checks, reviewer ``nalu_pipeline:S6_BURN_RETRY``)
    and attach it to the task.  Anything else still goes to the reviewer."""
    import h3_burn_retry as _br
    indices = s6_burn_retry_indices(read_json(_wave_state_path(ctx), {}) or {})
    rows = {str(r.get("unit_id")): r for r in fin_report.get("rows") or []}
    fin_dir = ctx.p.preprod / "prompt_batch_finalization"
    done: dict[str, Any] = {}
    tx = read_json(ctx.p.video_transaction, {}) or {}
    for uid in unbound:
        row = rows.get(uid) or {}
        if uid not in indices or row.get("status") != "CHANGED":
            continue
        task = next((t for t in tx.get("tasks") or [] if t.get("unit_id") == uid), None)
        if task is None or not task.get("prompt_file"):
            continue
        final_path = Path(str(task["prompt_file"]))
        final_path = final_path if final_path.is_absolute() else ENGINE / final_path
        if not final_path.is_file() or sha256_file(final_path) != row.get("final_sha256"):
            continue
        base, index = _br.strip_retry_sentence(final_path.read_text(encoding="utf-8"))
        if index != indices[uid]:
            continue
        base_sha = sha256_text(base)
        reviewer = read_json(fin_dir / f"{uid}.json", {}) or {}
        if base_sha == row.get("planned_sha256"):
            authority = "PLANNED_PROMPT"
        elif reviewer.get("status") == "PASS" and reviewer.get("final_prompt_sha256") == base_sha:
            authority = "REVIEWER_RECEIPT"
        else:
            continue
        fin_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = fin_dir / f"{uid}.burn_retry.json"
        receipt = {"status": "PASS", "execution_id": f"{ctx.episode}-PROMPT-BATCH-V1", "unit_id": uid,
                   "artifact_kind": "video_prompt", "planned_prompt_sha256": row["planned_sha256"],
                   "final_prompt_sha256": row["final_sha256"], "scope": "INCREMENTAL_EXACT_MATERIALIZATION_QA",
                   "reviewer": "nalu_pipeline:S6_BURN_RETRY", "review_method": "ENGINE_EXACT_SENTENCE_DELTA",
                   "reviewed_at": now(), "changed_line_count": 1, "burn_retry": index,
                   "base_prompt_sha256": base_sha, "base_authority": authority,
                   "reviewer_observation": ("the final prompt is the approved prompt plus exactly the engine's "
                                            f"burn-retry sentence {index} (line owner 2026-11-19 automatic retry)"),
                   "digest_sha256": sha256_file(fin_digest)}
        write_json(receipt_path, receipt)
        try:
            ref_path = str(receipt_path.resolve().relative_to(ENGINE.resolve()))
        except ValueError:
            ref_path = str(receipt_path.resolve())
        task["prompt_batch_finalization"] = {"path": ref_path, "sha256": sha256_file(receipt_path)}
        task["prompt_sha256"] = row["final_sha256"]
        done[uid] = {"receipt": str(receipt_path), "burn_retry": index, "base_authority": authority}
    if done:
        write_json(ctx.p.video_transaction, tx)
    return done


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
            # a regenerated reference keeps its old row as history (superseded_rows / SUPERSEDED*); only
            # the live row binds the provider.  Scanning history kept the 1.405 s row of a reference
            # already regenerated at 3.239 s failing forever (Twelve Gazes E01 Elias, 2026-10-22).
            if str(node.get("status") or "").upper().startswith("SUPERSEDED"):
                return
            entity = str(node.get("entity_id") or "")
            seconds = node.get("duration_seconds")
            if entity in used and isinstance(seconds, (int, float)) and not (low <= float(seconds) <= high):
                bad.append({"entity_id": entity, "character": node.get("character"),
                            "duration_seconds": round(float(seconds), 3),
                            "provider_window_seconds": [low, high],
                            "remedy": "regenerate the reference with a longer sample_text on the same voice_id, "
                                      "re-upload, and update remote_asset_id/duration_seconds (see D-77)"})
            for key, value in node.items():
                if "superseded" not in str(key).lower():
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


def hard_continuation_units(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Units whose opening anchor is PREVIOUS_UNIT_REAL_FINAL_FRAME (hard continuation: same take, the
    start frame must be the previous unit's real tail).  Same shape as continuity_derived_units."""
    anchors = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_ANCHOR_PLAN_V1.json", {}) or {}
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    first_shot = {u["unit_id"]: (u.get("editorial_shot_ids") or [None])[0] for u in plan.get("units") or []}
    out: dict[str, dict[str, Any]] = {}
    for row in anchors.get("units") or []:
        oac = row.get("opening_anchor_contract") or {}
        if str(oac.get("source") or "") != "PREVIOUS_UNIT_REAL_FINAL_FRAME":
            continue
        uid = row["unit_id"]; shot = first_shot.get(uid)
        if not shot:
            continue
        out[uid] = {"previous_unit_id": oac.get("previous_unit_id"), "first_shot_id": shot,
                    "keyframe_path": ctx.p.preprod / "keyframes" / f"{shot}-keyframe-v1.png",
                    "hard_continuation": True}
    return out


def tail_sourced_units(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """Every unit whose start frame is the previous unit's real tail (continuity-derived + hard continuation).
    Both need the tail materialised as the first shot's keyframe and a Q1 admission of that exact image before
    the unit may join a wave: the video admission gate requires an exact-SHA Q1 admission for the start frame
    (E04 VU-012/020/023 on device 1101, E06 VU-006 on 1284, 2026-11-11: hard-continuation tails never got a
    Q1 request, so preflight failed SEMANTIC_ANCHOR_EVIDENCE_INVALID forever)."""
    return {**hard_continuation_units(ctx), **continuity_derived_units(ctx)}


#: CAMERA_GRAMMAR_V1 start-frame source per unit (line owner 2026-10-24, lab Holmes E03), recorded in the
#: S6 wave state under ``start_frame_source``: TAIL_FRAME (the previous unit's real tail, measured), or
#: OWN_KEYFRAME_TAIL_REJECTED (the unit starts from its own keyframe, generated through the normal S5
#: keyframe path when none exists — one image, ~11 credits).
START_FRAME_TAIL = "TAIL_FRAME"
START_FRAME_OWN = "OWN_KEYFRAME_TAIL_REJECTED"
#: An explicit line-owner start-frame decision (2026-10-29, E12 VU-006: the predecessor tail carried a second
#: face at the frame edge and the redesign needs the unit's own keyframe).  Honoured on every episode, policy
#: or not: it is a recorded decision with an authority string, never an automatic measurement.
LINE_OWNER_DECISION = "LINE_OWNER"


def line_owner_start_frame_decisions(ctx: Ctx) -> dict[str, dict[str, Any]]:
    return {uid: row for uid, row in start_frame_source_decisions(ctx).items()
            if isinstance(row, dict) and row.get("decided_by") == LINE_OWNER_DECISION}


def record_line_owner_start_frame_decision(ctx: Ctx, unit_id: str, *, authority: str, reason: str,
                                           park_derived: bool = True) -> dict[str, Any]:
    """Record that ``unit_id`` opens on its own keyframe by line-owner decision and park the derived tail
    copy so the next S5 regenerates the keyframe from the (rewritten) shot text.  Free; never POSTs."""
    info = continuity_derived_units(ctx).get(unit_id)
    if not info:
        raise SystemExit(f"{unit_id} is not a continuity-derived unit of {ctx.episode}; nothing to decide")
    if (ctx.p.video_media / f"{unit_id}.mp4").is_file():
        raise SystemExit(f"{unit_id} has a clip on disk; park or reject it through the QA route first")
    if not str(authority or "").strip():
        raise SystemExit("--authority is required (who decided, when)")
    tail = ctx.p.preprod / "real_final_frames" / f"{info['previous_unit_id']}.png"
    row: dict[str, Any] = {
        "start_frame_source": START_FRAME_OWN, "decided_by": LINE_OWNER_DECISION, "reason": reason,
        "authority": authority, "previous_unit_id": info["previous_unit_id"], "first_shot_id": info["first_shot_id"],
        "tail": str(tail) if tail.is_file() else None, "tail_sha256": sha256_file(tail) if tail.is_file() else None,
        "next": "S2 rebuild writes the own keyframe prompt; S5 keyframe path (~11 credits) renders it; Q1 reviews it",
    }
    dst: Path = info["keyframe_path"]
    if park_derived and dst.is_file():
        park_dir = dst.parent / f"_superseded_{ctx.run_id}"
        park_dir.mkdir(parents=True, exist_ok=True)
        parked = park_dir / dst.name
        os.replace(dst, parked)
        row["parked_derived_keyframe"] = str(parked)
        sidecar = dst.with_name(dst.name.replace(".png", ".derived.json"))
        if sidecar.is_file():
            os.replace(sidecar, park_dir / sidecar.name)
            row["parked_derived_sidecar"] = str(park_dir / sidecar.name)
    record_start_frame_source(ctx, unit_id, row)
    return row
#: Q2 objective failures whose controlled redo must not re-shoot from the same start frame.
REDO_START_FRAME_FAILURES = ("speaker_framing", "face_count")


def _camera_grammar_on(ctx: Ctx) -> bool:
    import camera_grammar_policy as _cgp
    return _cgp.active(read_json(ctx.p.contract, {}) or {}, episode=ctx.episode)


def _wave_state_path(ctx: Ctx) -> Path:
    return ctx.p.preprod_reports / f"{ctx.episode}_S6_WAVE_STATE.json"


def start_frame_source_decisions(ctx: Ctx) -> dict[str, dict[str, Any]]:
    return dict((read_json(_wave_state_path(ctx), {}) or {}).get("start_frame_source") or {})


def record_start_frame_source(ctx: Ctx, unit_id: str, row: dict[str, Any]) -> None:
    path = _wave_state_path(ctx)
    state = read_json(path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    state.setdefault("start_frame_source", {})[unit_id] = {**row, "recorded_at": now(), "recorded_by": TOOL_ID}
    write_json(path, state)


def bound_take_on_disk(ctx: Ctx, unit_id: str) -> dict[str, Any] | None:
    """The bound provider take that produced ``video/<unit>.mp4`` (the oldest live binding, which is the one the
    poll harvests to the assembly path), or None when there is no clip or no bound transaction."""
    if not (ctx.p.video_media / f"{unit_id}.mp4").is_file():
        return None
    live = s6_live_bindings(ctx, unit_id)
    return live[0] if live else None


def record_start_frames_as_submitted(ctx: Ctx) -> dict[str, dict[str, Any]]:
    """CAMERA_GRAMMAR_V1: per unit whose clip on disk came from a bound transaction, whether that submission
    carried the predecessor's real tail (its sha among the bound reference shas).  Written to the S6 wave state
    as ``start_frame_as_submitted`` (whole map, rewritten every pass, so a parked/redone unit drops out);
    build_nalu_preproduction never re-attaches a tail the submitted take did not have (lab Holmes E06)."""
    if not _camera_grammar_on(ctx):
        return {}
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    order = [str(u.get("unit_id") or "") for u in plan.get("units") or [] if u.get("unit_id")]
    tails = ctx.p.preprod / "real_final_frames"
    rows: dict[str, dict[str, Any]] = {}
    for idx, uid in enumerate(order):
        prev = order[idx - 1] if idx > 0 else None
        tail = tails / f"{prev}.png" if prev else None
        if tail is None or not tail.is_file():
            continue
        take = bound_take_on_disk(ctx, uid)
        if take is None:
            continue
        refs = [str(v) for v in take.get("reference_sha256") or []]
        tail_sha = sha256_file(tail)
        rows[uid] = {"predecessor_tail_submitted": tail_sha in refs, "previous_unit_id": prev,
                     "tail_sha256": tail_sha, "task_id": take.get("task_id"),
                     "transaction": _engine_rel(Path(str(take.get("transaction") or ""))),
                     "prompt_sha256": take.get("prompt_sha256"), "reference_sha256": refs}
    path = _wave_state_path(ctx)
    state = read_json(path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    if (state.get("start_frame_as_submitted") or {}) != rows:
        state["start_frame_as_submitted"] = rows
        write_json(path, state)
    return rows


def exempt_harvested_bound_takes(ctx: Ctx, unbound: list[str], fin_report: dict[str, Any],
                                 as_submitted: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    """CAMERA_GRAMMAR_V1: split the changed-without-receipt units into those that still need a finalization
    review and those whose clip on disk was produced by a bound transaction.  The latter are never submitted
    again, so a recompiled prompt for them needs no review: their authority is the bound submission (prompt /
    reference shas in the durable transaction store), recorded here for audit (lab Holmes E06 2026-10-26: the
    final pass asked to approve 10 recompiled prompts that would never be submitted)."""
    rows = {str(r.get("unit_id")): r for r in fin_report.get("rows") or []}
    harvested: dict[str, Any] = {}
    for uid in unbound:
        take = bound_take_on_disk(ctx, uid)
        if take is None:
            continue
        row = rows.get(uid) or {}
        receipt = read_json(ctx.p.preprod / "prompt_batch_finalization" / f"{uid}.json", {}) or {}
        submitted_sha = str(take.get("prompt_sha256") or "")
        harvested[uid] = {
            "task_id": take.get("task_id"), "transaction": _engine_rel(Path(str(take.get("transaction") or ""))),
            "submitted_prompt_sha256": submitted_sha, "recompiled_prompt_sha256": row.get("final_sha256"),
            "recompiled_matches_submitted": row.get("final_sha256") == submitted_sha,
            "submitted_reference_sha256": take.get("reference_sha256"),
            "start_frame_as_submitted": as_submitted.get(uid),
            "submitted_prompt_review": (
                "FINALIZATION_RECEIPT_PASS" if receipt.get("status") == "PASS"
                and receipt.get("final_prompt_sha256") == submitted_sha
                else "PLANNED_PROMPT_UNCHANGED" if row.get("planned_sha256") == submitted_sha
                else "NO_MATCHING_RECEIPT_ON_DISK")}
    return [uid for uid in unbound if uid not in harvested], harvested


#: start-frame cast check (metadata, free): shared with build_keyframe_manifest (plan time)
from tail_cast_check import (TAIL_CAST_METHOD, _shot_in_frame_cast, _shot_on_screen_speaker,  # noqa: E402,F401
                             tail_cast_mismatch, previous_unit_ids)


def ctx_tail_cast_mismatch(ctx: Ctx, unit_id: str, previous_unit_id: str | None) -> dict[str, Any]:
    try:
        editorial = read_json(ctx.p.editorial, {}) or {}
        plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
        return tail_cast_mismatch(editorial, plan, unit_id, previous_unit_id)
    except Exception as exc:  # noqa: BLE001 - a check that did not run never rejects
        return {"method": TAIL_CAST_METHOD, "verdict": "NOT_MEASURED", "status": "NOT_MEASURED",
                "reason": f"{type(exc).__name__}: {str(exc)[:160]}", "reasons": []}


def check_tail_start_frame(ctx: Ctx, unit_id: str, tail: Path, previous_unit_id: str | None = None) -> dict[str, Any]:
    """Objective speaker framing + face count of a candidate tail start frame (video_q2_builder
    start-frame-check, free).  A check that did not run never rejects (the tail stays, as before).
    The free declared-cast check (``tail_cast_mismatch``) runs first for every style and rejects a tail that shows
    another character; render_style=anime: the face check is InsightFace, NOT_APPLICABLE -> ACCEPT otherwise."""
    # the declared cast decides first (free, every style): a tail showing another character is never this unit's
    # start frame (JA-01 E01 2026-11-20, shot / reverse-shot dialogue morphed the speaker into the other character)
    cast = ctx_tail_cast_mismatch(ctx, unit_id, previous_unit_id) if previous_unit_id else {}
    if cast.get("verdict") == "REJECT":
        return {**cast, "render_style": ctx_render_style(ctx)}
    if ctx_render_style(ctx) == "anime":
        return {"verdict": "ACCEPT", "status": "NOT_APPLICABLE", "reason": "RENDER_STYLE_ANIME", "render_style": "anime",
                **({"cast_check": cast} if cast else {})}
    step = qa_run(ctx, [VIDEO_Q2, "start-frame-check", "--episode", ctx.episode, "--unit", unit_id,
                        "--image", tail], name=f"s6_tail_start_frame_check_{unit_id}")
    verdict = qa_json(step) or {}
    if verdict.get("verdict") not in ("ACCEPT", "REJECT"):
        return {"verdict": "ACCEPT", "status": "NOT_MEASURED", "reason": "START_FRAME_CHECK_DID_NOT_RUN",
                "exit_code": step.get("exit_code")}
    return verdict


def materialise_derived_keyframes(ctx: Ctx) -> list[dict[str, Any]]:
    """Copy the previous unit's real final frame into keyframes/<first_shot>-keyframe-v1.png for
    every continuity-derived unit whose tail exists (write-if-missing; sidecar records the source).

    CAMERA_GRAMMAR_V1: a unit whose first shot has a declared on-screen speaker only takes the tail when the
    objective speaker check accepts it; otherwise it starts from its own keyframe (start_frame_source)."""
    rows = []
    tails = ctx.p.preprod / "real_final_frames"
    stamped = _camera_grammar_on(ctx)
    decisions = start_frame_source_decisions(ctx) if stamped else line_owner_start_frame_decisions(ctx)
    for uid, info in tail_sourced_units(ctx).items():
        dst: Path = info["keyframe_path"]; prev = info["previous_unit_id"]
        src = tails / f"{prev}.png" if prev else None
        hard = bool(info.get("hard_continuation"))
        if dst.is_file():
            rows.append({"unit_id": uid, "status": "ALREADY_PRESENT", "path": str(dst)}); continue
        owner = {} if hard else (decisions.get(uid) or {})
        if owner.get("decided_by") == LINE_OWNER_DECISION and owner.get("start_frame_source") == START_FRAME_OWN:
            rows.append({"unit_id": uid, "status": "OWN_KEYFRAME_REQUIRED", "start_frame_source": START_FRAME_OWN,
                         "reason": owner.get("reason"), "decided_by": LINE_OWNER_DECISION, "path": str(dst)}); continue
        if not src or not src.is_file():
            if stamped and not hard and prev:
                # the declared-cast check needs no tail image: decide now, before the predecessor's clip lands,
                # so the unit's own keyframe is generated with the current S6 pass instead of one chain step
                # later (PR #286 follow-up, device 0080 E05 VU-001 2026-11-21)
                prior = decisions.get(uid) or {}
                if prior.get("start_frame_source") == START_FRAME_OWN:
                    rows.append({"unit_id": uid, "status": "OWN_KEYFRAME_REQUIRED", "start_frame_source": START_FRAME_OWN,
                                 "reason": prior.get("reason"), "path": str(dst)}); continue
                cast = ctx_tail_cast_mismatch(ctx, uid, prev)
                if cast.get("verdict") == "REJECT":
                    record_start_frame_source(ctx, uid, {
                        "start_frame_source": START_FRAME_OWN, "reason": "TAIL_REJECTED", "previous_unit_id": prev,
                        "tail": None, "tail_sha256": None, "first_shot_id": info["first_shot_id"],
                        "decided_before_tail": True,
                        "measurement": {k: cast.get(k) for k in ("method", "status", "verdict", "reasons",
                                                                 "speaker_ids") if k in cast},
                        "next": "the unit's own keyframe (S5 keyframe path; ~11 credits when none exists)"})
                    rows.append({"unit_id": uid, "status": "OWN_KEYFRAME_REQUIRED", "start_frame_source": START_FRAME_OWN,
                                 "reason": "TAIL_REJECTED", "reasons": cast.get("reasons")}); continue
            rows.append({"unit_id": uid, "status": "TAIL_NOT_YET_EXTRACTED", "previous_unit_id": prev}); continue
        check: dict[str, Any] | None = None
        if stamped and not hard:
            tail_sha = sha256_file(src)
            prior = decisions.get(uid) or {}
            if prior.get("start_frame_source") == START_FRAME_OWN and (
                    prior.get("reason") != "TAIL_REJECTED" or prior.get("tail_sha256") == tail_sha):
                rows.append({"unit_id": uid, "status": "OWN_KEYFRAME_REQUIRED", "start_frame_source": START_FRAME_OWN,
                             "reason": prior.get("reason"), "path": str(dst)}); continue
            check = check_tail_start_frame(ctx, uid, src, prev)
            measured = {k: check.get(k) for k in ("method", "status", "verdict", "reasons", "reason", "faces",
                                                  "declared_face_budget", "speaker_ids", "speaker_identity",
                                                  "measurement", "thresholds") if k in check}
            if check.get("verdict") == "REJECT":
                record_start_frame_source(ctx, uid, {
                    "start_frame_source": START_FRAME_OWN, "reason": "TAIL_REJECTED", "previous_unit_id": prev,
                    "tail": str(src), "tail_sha256": tail_sha, "first_shot_id": info["first_shot_id"],
                    "measurement": measured,
                    "next": "the unit's own keyframe (S5 keyframe path; ~11 credits when none exists)"})
                rows.append({"unit_id": uid, "status": "OWN_KEYFRAME_REQUIRED", "start_frame_source": START_FRAME_OWN,
                             "reason": "TAIL_REJECTED", "reasons": check.get("reasons")}); continue
            record_start_frame_source(ctx, uid, {
                "start_frame_source": START_FRAME_TAIL, "previous_unit_id": prev, "tail": str(src),
                "tail_sha256": tail_sha, "first_shot_id": info["first_shot_id"], "measurement": measured})
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        side = {"schema": "nalu.continuity_derived_keyframe.v1", "unit_id": uid, "shot_id": info["first_shot_id"],
                "source_real_final_frame": str(src), "source_sha256": sha256_file(src), "sha256": sha256_file(dst),
                "previous_unit_id": prev, "materialised_at": now(), "recorded_by": TOOL_ID,
                "note": ("PREVIOUS_UNIT_REAL_FINAL_FRAME (hard continuation)" if hard else "anchor policy v4 CONTINUITY_DERIVED_KEYFRAME")
                        + ": the start frame IS the previous unit's real tail; reviewed by the keyframe (Q1) questionnaire before the unit becomes wave-ready"}
        if check is not None:
            side["start_frame_source"] = START_FRAME_TAIL
            side["start_frame_check"] = {k: check.get(k) for k in ("verdict", "status", "reasons", "reason")
                                         if k in check}
        if hard:
            # a hard continuation always opens on the tail (same take); a declared cast change at its first shot is
            # an in-shot identity-swap risk (JA-01 E01 2026-11-20) -- recorded as an advisory lead, never a gate
            cast = ctx_tail_cast_mismatch(ctx, uid, prev)
            if cast.get("verdict") == "REJECT":
                side["identity_swap_risk"] = {k: cast.get(k) for k in ("method", "reasons", "tail_cast",
                                                                       "first_shot_cast", "speaker_ids") if k in cast}
                ctx.say(f"   S6 identity-swap risk {uid}: {','.join(cast.get('reasons') or [])} "
                        "(hard continuation opens on a tail without the declared on-screen speaker; advisory)")
        write_json(dst.with_suffix(".derived.json"), side)
        rows.append({"unit_id": uid, "status": "MATERIALISED", "path": str(dst), "sha256": side["sha256"]})
    return rows


def redo_switch_start_frames(ctx: Ctx) -> list[dict[str, Any]]:
    """CAMERA_GRAMMAR_V1 §4/§5 controlled redo (line owner 2026-10-24): a unit whose clip was parked for a
    redo after an objective Q2 speaker-framing / face-count FAIL must not re-shoot from the same start frame.
    The start frame that made the failed clip (older than that Q2 measurement) is parked so the unit gets its
    own keyframe again (S5 path, current framing rules); a tail-derived unit switches to OWN keyframe."""
    if not _camera_grammar_on(ctx):
        return []
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    derived = continuity_derived_units(ctx)
    hard = hard_continuation_units(ctx)
    out: list[dict[str, Any]] = []
    for unit in plan.get("units") or []:
        uid = str(unit.get("unit_id") or "")
        shots = unit.get("editorial_shot_ids") or []
        if not uid or not shots or uid in hard or (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        prepare = ctx.p.q2_dir / uid / "prepare.json"
        q2 = read_json(prepare, {}) or {}
        failed = [k for k in REDO_START_FRAME_FAILURES if (q2.get(k) or {}).get("status") == "FAIL"]
        if not failed:
            continue
        keyframe = ctx.p.keyframes / f"{shots[0]}-keyframe-v1.png"
        if not keyframe.is_file() or keyframe.stat().st_mtime > prepare.stat().st_mtime:
            continue  # already replaced after the failed measurement
        park = ctx.p.keyframes / f"_superseded_{ctx.run_id}_q2_redo_start_frame"
        park.mkdir(parents=True, exist_ok=True)
        moved = [str(keyframe)]
        os.replace(keyframe, park / keyframe.name)
        sidecar = keyframe.with_suffix(".derived.json")
        if sidecar.is_file():
            os.replace(sidecar, park / sidecar.name); moved.append(str(sidecar))
        receipt = ENGINE / "reports/start_frame_evidence" / f"{uid}_start_frame_evidence.json"
        if receipt.is_file():
            os.replace(receipt, park / receipt.name); moved.append(str(receipt))
        row = {"start_frame_source": START_FRAME_OWN, "reason": "Q2_REDO_" + "+".join(f.upper() for f in failed),
               "first_shot_id": shots[0], "failed_clip_sha256": q2.get("media_sha256"),
               "failed_measurement": {k: {kk: (q2.get(k) or {}).get(kk) for kk in ("status", "failure", "frames_flagged")}
                                      for k in failed},
               "parked": moved, "parked_to": str(park),
               "next": "own keyframe regenerated through the S5 keyframe path (current framing rules)"}
        if uid in derived:
            record_start_frame_source(ctx, uid, row)
        record_redo_start_frame_switch(ctx, uid, row)
        out.append({"unit_id": uid, **row})
    return out


def record_redo_start_frame_switch(ctx: Ctx, unit_id: str, row: dict[str, Any]) -> None:
    path = _wave_state_path(ctx)
    state = read_json(path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    state.setdefault("redo_start_frame_switch", {})[unit_id] = {**row, "recorded_at": now(), "recorded_by": TOOL_ID}
    write_json(path, state)


def _q1_admitted_now(ctx: Ctx, unit_id: str, keyframe: Path) -> bool:
    q1 = read_json(ctx.p.preprod_reports / "qa" / "q1" / unit_id / "admission_result.json", {}) or {}
    return (keyframe.is_file() and q1.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT"
            and q1.get("asset_sha256") == sha256_file(keyframe))


def redo_keyframes_unadmitted(ctx: Ctx) -> list[str]:
    """Units whose start keyframe a CAMERA_GRAMMAR_V1 redo switched (not tail-derived) and whose current
    image has no Q1 admission + start-frame receipt yet: S5 owns that review, so it must not reuse a stale
    ALL_ADMITTED index for them."""
    switched = (read_json(_wave_state_path(ctx), {}) or {}).get("redo_start_frame_switch") or {}
    if not switched:
        return []
    derived = continuity_derived_units(ctx)
    out = []
    for uid, row in sorted(switched.items()):
        if uid in derived or (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        keyframe = ctx.p.keyframes / f"{row.get('first_shot_id')}-keyframe-v1.png"
        if not _q1_admitted_now(ctx, uid, keyframe) or start_frame_receipt_state(uid, keyframe) == SFE_MISSING:
            out.append(uid)
    return out


def own_keyframes_needed(ctx: Ctx) -> list[str]:
    """CAMERA_GRAMMAR_V1: units without a video whose own start keyframe must be (re)generated now — a
    tail-derived unit whose tail was rejected / switched by a redo, or a keyframe a redo parked."""
    if not _camera_grammar_on(ctx):
        return []
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    # Hard continuations start from the previous unit's real tail, which only exists after that video is
    # downloaded; S5 deliberately skips their image, so an unused prompt file must not demand one
    # (device 1101 E05 VU-005/009/012/014/023, 2026-11-12: OWN_KEYFRAME_NOT_GENERATED before wave 1).
    derived = tail_sourced_units(ctx)
    decisions = start_frame_source_decisions(ctx)
    prompts = ctx.p.preprod / "prompts" / "keyframes"
    need = []
    for unit in plan.get("units") or []:
        uid = str(unit.get("unit_id") or "")
        shots = unit.get("editorial_shot_ids") or []
        if not uid or not shots or (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        if (ctx.p.keyframes / f"{shots[0]}-keyframe-v1.png").is_file():
            continue
        if uid in derived:
            if (decisions.get(uid) or {}).get("start_frame_source") == START_FRAME_OWN:
                need.append(uid)
        elif (prompts / f"{shots[0]}-KEYFRAME-V1.txt").is_file():
            need.append(uid)
    return sorted(set(need) | set(redo_keyframes_unadmitted(ctx)))


def _unit_first_shots(ctx: Ctx) -> dict[str, str]:
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    return {str(u.get("unit_id")): str((u.get("editorial_shot_ids") or [""])[0])
            for u in plan.get("units") or [] if u.get("unit_id") and u.get("editorial_shot_ids")}


def _iso_epoch(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def own_keyframe_images_missing(ctx: Ctx, unit_ids: list[str]) -> list[str]:
    """Of ``unit_ids``, the units whose own start keyframe ``<first shot>-keyframe-v1.png`` is not on disk."""
    first = _unit_first_shots(ctx)
    return [uid for uid in unit_ids
            if not first.get(uid) or not (ctx.p.keyframes / f"{first[uid]}-keyframe-v1.png").is_file()]


def _harvested_own_keyframe_plates(ctx: Ctx, shot: str) -> list[tuple[Path, dict[str, Any]]]:
    """Harvested image plates of ``shot``'s keyframe task (``<shot>-KEYFRAME-V<n>``) still waiting for the rename:
    files in the keyframe harvest dir (both harvester spellings) and completed rows of any keyframe harvest
    status report whose plate is still on disk with the sha it was downloaded with."""
    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    key = f"{shot}-KEYFRAME-V"
    hdir = getattr(ctx.p, "keyframe_harvest_dir", None) or ctx.p.preprod / "keyframe_harvest"
    if hdir.is_dir():
        for path in set(hdir.glob(f"{key}*.png")) | set(hdir.glob(f"{ctx.episode}_{key}*.png")):
            if path.is_file() and path.stat().st_size > 0:
                out[str(path)] = (path, {"source": "KEYFRAME_HARVEST_DIR"})
    rdir = getattr(ctx.p, "preprod_reports", None) or ctx.p.preprod / "reports"
    reports = sorted(rdir.glob("*KEYFRAME_HARVEST_STATUS*.json")) if rdir.is_dir() else []
    for report in reports:
        for row in (read_json(report, {}) or {}).get("results") or []:
            if not isinstance(row, dict) or not str(row.get("task_key") or "").startswith(key):
                continue
            if not str(row.get("remote_status") or "").startswith("completed") or not row.get("output_path"):
                continue
            path = Path(str(row["output_path"]))
            if not path.is_absolute():
                path = ENGINE / path
            if not path.is_file() or (row.get("sha256") and sha256_file(path) != row.get("sha256")):
                continue
            out[str(path)] = (path, {"source": "KEYFRAME_HARVEST_STATUS", "status_report": str(report),
                                     "task_key": row.get("task_key"), "task_id": row.get("task_id"),
                                     "transaction": row.get("transaction")})
    return sorted(out.values(), key=lambda item: item[0].stat().st_mtime, reverse=True)


def bind_harvested_own_keyframes(ctx: Ctx, unit_ids: list[str]) -> list[dict[str, Any]]:
    """Free: materialise an own start keyframe that was already generated and harvested but never renamed into
    ``keyframes/<first shot>-keyframe-v1.png`` -- the path S6, the anchor plan and Q1 read.

    Device 0080 E05 VU-001 (2026-11-21): the S6 tail-cast rejection (PR #286) needed the unit's own keyframe,
    the image task completed and was harvested, but the plate never reached the keyframe path, so S6 kept
    blocking OWN_KEYFRAME_NOT_GENERATED and the only engine route left was another paid image.  The S5 rename
    (apply_keyframe_renames) runs only on a paid S5 pass that harvested in the same run; a harvest by another
    run (a failed-submit poll, a re-entry, a maintainer-authorised manual harvest) left the plate behind.

    Only a plate harvested AFTER the unit's own-keyframe decision (start_frame_source / redo switch recorded_at)
    counts, so a plate of a superseded prompt is never bound.  Never POSTs, never overwrites a keyframe."""
    if not unit_ids:
        return []
    first = _unit_first_shots(ctx)
    state = read_json(_wave_state_path(ctx), {}) or {}
    decided = {**(state.get("start_frame_source") or {}), **(state.get("redo_start_frame_switch") or {})}
    rows: list[dict[str, Any]] = []
    for uid in unit_ids:
        shot = first.get(uid)
        if not shot:
            continue
        dest = ctx.p.keyframes / f"{shot}-keyframe-v1.png"
        if dest.is_file():
            continue
        since = _iso_epoch((decided.get(uid) or {}).get("recorded_at"))
        plates = [(path, meta) for path, meta in _harvested_own_keyframe_plates(ctx, shot)
                  if since is None or path.stat().st_mtime >= since - 1]
        if not plates:
            continue
        src, meta = plates[0]
        sha = sha256_file(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        hdir = getattr(ctx.p, "keyframe_harvest_dir", None) or ctx.p.preprod / "keyframe_harvest"
        if src.parent.resolve() == Path(hdir).resolve():
            os.replace(src, dest)
            action = "RENAMED"
        else:
            shutil.copyfile(src, dest)
            action = "COPIED"
        side = {"schema": "nalu.own_keyframe_binding.v1", "unit_id": uid, "shot_id": shot,
                "source_path": str(src), "sha256": sha, "action": action, **meta,
                "start_frame_source": (decided.get(uid) or {}).get("start_frame_source") or START_FRAME_OWN,
                "bound_at": now(), "recorded_by": TOOL_ID,
                "note": "harvested own start keyframe bound to its keyframe path (free); Q1 + the start-frame "
                        "receipt then review these exact bytes"}
        write_json(dest.with_suffix(".own_keyframe.json"), side)
        rows.append({"unit_id": uid, "shot_id": shot, "status": "BOUND_HARVESTED_PLATE", "path": str(dest),
                     "sha256": sha, "source": meta.get("source"), "action": action})
    return rows


def own_keyframe_diagnosis(ctx: Ctx, unit_ids: list[str]) -> dict[str, Any]:
    """Why each unit's own keyframe is still missing after the S5 keyframe path (free, read-only)."""
    first = _unit_first_shots(ctx)
    km, kr = getattr(ctx.p, "keyframe_manifest", None), getattr(ctx.p, "keyframe_manifest_report", None)
    manifest = (read_json(km, {}) or {}) if km else {}
    tasks = {str(t.get("shot_id") or ""): str(t.get("task_key") or "") for t in manifest.get("tasks") or []}
    table = {str(r.get("shot_id") or ""): r for r in
             ((read_json(kr, {}) or {}) if kr else {}).get("decision_table") or []}
    out: dict[str, Any] = {}
    for uid in unit_ids:
        shot = first.get(uid, "")
        row = table.get(shot) or {}
        out[uid] = {"first_shot_id": shot, "manifest_task_key": tasks.get(shot) or None,
                    "keyframe_decision": row.get("decision"), "decision_basis": row.get("decision_basis"),
                    "reuse_source": row.get("reuse_source"),
                    "harvested_plates": [str(p) for p, _ in _harvested_own_keyframe_plates(ctx, shot)]}
    return out


def ensure_own_keyframe_admission(ctx: Ctx, unit_ids: list[str]) -> StageResult | None:
    """Q1 admission + START-FRAME-SEMANTIC-EVIDENCE receipt for own start keyframes that are ON DISK but not bound
    yet (a redo-switched unit's regenerated keyframe, redo_keyframes_unadmitted).  Scoped to exactly these stills,
    the same route S6 runs for derived start frames: merge the valid submitted answers for these bytes, build the
    Q1 admission, apply the line owner's sha-bound orders, write the receipt.  A still nobody answered gets a
    review request for exactly that still.  Returns None when every unit is bound (re-plan), else the result."""
    first = _unit_first_shots(ctx)
    frames = {uid: ctx.p.keyframes / f"{first[uid]}-keyframe-v1.png" for uid in unit_ids
              if first.get(uid) and (ctx.p.keyframes / f"{first[uid]}-keyframe-v1.png").is_file()}
    if not frames:
        return None
    res = StageResult(REVIEW_REQUIRED)
    res.details["own_keyframe_units_pending_binding"] = sorted(frames)
    need_q1 = [uid for uid, kf in frames.items() if not _q1_admitted_now(ctx, uid, kf)]
    if need_q1:
        review_path, _covered, unanswered = merge_keyframe_answers(ctx, [first[uid] for uid in need_q1])
        if unanswered or review_path is None:
            res.details.update(request_review(ctx, res, "keyframe", sub_stage="S6.q1_own",
                                              note="own start keyframes (exact bytes now on disk) need the keyframe "
                                                   "questionnaire",
                                              items=unanswered or [first[uid] for uid in need_q1]))
            res.blockers.append(f"S6.q1_own:REVIEW_REQUIRED:{len(unanswered or need_q1)}_frames")
            return res
        build_step = qa_run(ctx, [KEYFRAME_Q1, "build", "--episode", ctx.episode, "--review", review_path],
                            name="s6_q1_build_admission_own")
        res.steps.append(build_step)
        index_path = Path(str((qa_json(build_step) or {}).get("out") or ""))
        index = read_json(index_path, {}) or {}
        if index:
            res.details["own_q1_line_owner_acceptance"] = apply_line_owner_q1_acceptance(ctx, index, index_path)
        still = [uid for uid in need_q1 if not _q1_admitted_now(ctx, uid, frames[uid])]
        if still:
            res.status = BLOCKED
            res.blockers.append("S6.q1_own:NOT_ADMITTED:" + ",".join(still))
            if index:
                res.details["q1_orders_needed"] = q1_orders_needed(ctx, index, still)
            res.details["next"] = ("quality never blocks: record one default-acceptance order per failing Q1 gate "
                                   "listed in q1_orders_needed, then resume S6")
            return res
    if ensure_derived_start_frame_receipts(ctx, res, frames, sub_stage="S6.sfe_own") == "STOP":
        return res
    return None


def own_keyframes_q1_stale(ctx: Ctx) -> list[str]:
    """Units that open on their OWN keyframe, have no clip yet, and whose Q1 admission is not about the
    image now on disk: no result for the unit, or a result bound to other bytes.

    Device 1101 E24 (2026-11-22): the units were renumbered after the S5 keyframe review, so
    ``q1/E24-VU-014/admission_result.json`` held the admission of S04-03 while VU-014 opens on S04-01.
    S5 short-circuited on the ALL_ADMITTED index, S6 only re-checked tail-sourced units, and preflight
    failed SEMANTIC_ANCHOR_EVIDENCE_INVALID (Q1_ASSET_SHA_MISMATCH) on every resume.  A result Q1 wrote
    for these exact bytes (admitted or not) is never touched here."""
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    derived = tail_sourced_units(ctx)
    out = []
    for unit in plan.get("units") or []:
        uid = str(unit.get("unit_id") or "")
        shots = unit.get("editorial_shot_ids") or []
        if not uid or not shots or uid in derived or (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        keyframe = ctx.p.keyframes / f"{shots[0]}-keyframe-v1.png"
        # Q1 and the anchor plan read the highest keyframe version; only the plain v1 case is decided here
        if not keyframe.is_file() or len(list(ctx.p.keyframes.glob(f"{shots[0]}-keyframe-v*.png"))) != 1:
            continue
        q1 = read_json(ctx.p.preprod_reports / "qa" / "q1" / uid / "admission_result.json", {}) or {}
        if q1.get("asset_sha256") != sha256_file(keyframe):
            out.append(uid)
    return out


def derived_units_pending_q1(ctx: Ctx) -> list[tuple[str, str]]:
    """(unit_id, first_shot_id) of derived units whose keyframe exists but has no ADMITTED Q1 result."""
    out = []
    for uid, info in tail_sourced_units(ctx).items():
        if not info["keyframe_path"].is_file():
            continue
        q1 = read_json(ctx.p.preprod_reports / "qa" / "q1" / uid / "admission_result.json", {}) or {}
        if q1.get("downstream_status") != "ADMITTED_FOR_VIDEO_SUBMIT" or q1.get("asset_sha256") != sha256_file(info["keyframe_path"]):
            out.append((uid, info["first_shot_id"]))
    return out


def own_done_units_q1_rejected(ctx: Ctx) -> list[tuple[str, str]]:
    """(unit_id, first_shot_id) of units that start from their OWN keyframe, already have their clip, and
    whose Q1 judged the keyframe now on disk and did not admit it.

    Device 0334 E05 VU-024 (2026-11-15): a re-review of all 31 keyframes failed S04-01 on
    PERIOD-ANACHRONISM-LOCK after its clip existed, the default acceptance was recorded for that exact sha
    (seq 120), and nothing read it: the final pass only re-checked tail-sourced units, and S5 short-circuited
    on an ALL_ADMITTED index the final pass itself had just rewritten for two derived stills.  Only a row
    Q1 wrote for these exact bytes counts; a unit Q1 never judged, or whose keyframe changed since, is not
    touched here."""
    plan = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    derived = tail_sourced_units(ctx)
    out = []
    for unit in plan.get("units") or []:
        uid = str(unit.get("unit_id") or "")
        shots = unit.get("editorial_shot_ids") or []
        if not uid or not shots or uid in derived or not (ctx.p.video_media / f"{uid}.mp4").is_file():
            continue
        keyframe = ctx.p.keyframes / f"{shots[0]}-keyframe-v1.png"
        if not keyframe.is_file():
            continue
        q1 = read_json(ctx.p.preprod_reports / "qa" / "q1" / uid / "admission_result.json", {}) or {}
        if (not q1 or q1.get("downstream_status") == "ADMITTED_FOR_VIDEO_SUBMIT"
                or q1.get("asset_sha256") != sha256_file(keyframe)):
            continue
        out.append((uid, str(shots[0])))
    return out


def done_units_pending_q1(ctx: Ctx) -> list[tuple[str, str]]:
    """Units with a clip on disk whose start frame has no Q1 admission: tail-sourced ones, then own-keyframe ones."""
    return ([(uid, shot) for uid, shot in derived_units_pending_q1(ctx)
             if (ctx.p.video_media / f"{uid}.mp4").is_file()] + own_done_units_q1_rejected(ctx))


def accept_done_derived_start_frames(ctx: Ctx) -> dict[str, Any]:
    """S6 final pass: apply the line owner's recorded acceptance to a start frame whose clip is ALREADY on
    disk -- a tail-sourced one, or (2026-11-15) the unit's own keyframe, see own_done_units_q1_rejected.

    The order overlays (apply_roger_q1_acceptance, apply_derived_start_frame_acceptance) ran only inside
    the wave loop, for units still waiting to be submitted.  Once every clip existed the loop was skipped
    and the full compile's video preflight read the unit's Q1 admission as FAIL_NOT_ADMITTED, so the
    episode stopped on INPUT_COMPLETENESS_FAILED:SEMANTIC_ANCHOR_EVIDENCE_INVALID with a valid sha-bound
    order in the box and no step left that reads it (device 1101 E10 VU-020, 2026-11-14, orders seq
    195/196).

    Free and never a review request: the Q1 admission is rebuilt from the reviewer's existing answers for
    this exact still (unchanged FAIL), then the same two overlays decide.  No valid answer for the bytes
    on disk, or no matching order: nothing changes and the preflight reports as before."""
    pending = done_units_pending_q1(ctx)
    if not pending:
        return {}
    out: dict[str, Any] = {"units": [uid for uid, _ in pending]}
    review_path, _covered, unanswered = merge_keyframe_answers(ctx, [shot for _, shot in pending])
    if review_path is None:
        out.update({"status": "NO_VALID_REVIEW_FOR_STILL_ON_DISK", "unanswered": unanswered})
        return out
    build_step = qa_run(ctx, [KEYFRAME_Q1, "build", "--episode", ctx.episode, "--review", review_path],
                        name="s6_q1_build_admission_derived_done")
    out["build_exit_code"] = build_step.get("exit_code")
    index_path = Path(str((qa_json(build_step) or {}).get("out") or ""))
    index = read_json(index_path, {}) or {}
    if not index:
        out["status"] = "Q1_BUILD_WROTE_NO_INDEX"
        return out
    out["q1_gate_order_acceptance"] = apply_roger_q1_acceptance(ctx, index, index_path)
    out["start_frame_order_acceptance"] = apply_derived_start_frame_acceptance(ctx, index, index_path)
    still = [uid for uid, _ in done_units_pending_q1(ctx)]
    out.update({"still_not_admitted": still, "status": "ADMITTED" if not still else "NOT_ADMITTED"})
    return out


# --------------------------------------------------------------------------- #
# S6 chain-step latency (2026-11-19): compile cache + in-run polling
# --------------------------------------------------------------------------- #
#: The rolling-wave loop's iteration budget per pass (unchanged); in-run poll iterations come on top of it.
S6_WAVE_LOOP_ITERATIONS = 7
#: Where the S6 compile cache record lives: the pipeline log dir, OUTSIDE every tree the fingerprint walks.
S6_COMPILE_CACHE_NAME = "S6_COMPILE_CACHE.json"
_S6_FP_SKIP_DIRS = {"__pycache__", ".git", "tests", "node_modules"}


def _s6_fp_walk(root: Path, out: list[Any], *, suffixes: tuple[str, ...] | None = None) -> None:
    """(relpath, size, mtime_ns) of every file under ``root`` (stat only, no content read)."""
    if not root:
        return
    root = Path(root)
    if root.is_file():
        st = root.stat()
        out.append([str(root), st.st_size, st.st_mtime_ns])
        return
    if not root.is_dir():
        out.append([str(root), None, None])
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _S6_FP_SKIP_DIRS)
        for name in sorted(filenames):
            if ".part" in name or name.endswith(".pyc") or name == S6_COMPILE_CACHE_NAME:
                continue
            if suffixes and not name.endswith(suffixes):
                continue
            path = Path(dirpath) / name
            try:
                st = path.stat()
            except OSError:
                continue
            out.append([str(path), st.st_size, st.st_mtime_ns])


def s6_compile_fingerprint(ctx: Ctx, argv: list[Any]) -> str:
    """Stat fingerprint of everything the S6 strict compile (build_nalu_preproduction --keyframe-dir) can read
    or write: the episode's whole work tree (preproduction outputs included, keyframes, tails, Q1/start-frame/
    action-role receipts, clips), its runtime preproduction inputs, the engine's receipt dirs, the durable
    video store, the writer layers / GSM / requirements / config / scoped library + registry / orders, the
    line and engine code + configs, the NALU_* environment and the exact argv.  Equal fingerprints mean the
    disk is byte-for-byte (by size + ns mtime) what the last compile left behind, so re-running it cannot
    produce anything different.  Any change anywhere -- including in the outputs -- is a miss."""
    p = ctx.p
    scope = getattr(p, "scope", None) or {}
    authority = getattr(ctx, "authority", None) or {}
    rows: list[Any] = []
    trees = [getattr(p, "work", None), getattr(p, "rt_pre", None), ENGINE / "reports",
             video_store_dir(ctx.episode), getattr(getattr(p, "legacy_grouping_plan", None), "parent", None),
             scope.get("voice_refs"), ENGINE / "configs", RT_TOOLS.parent / "configs"]
    for root in trees:
        if root:
            _s6_fp_walk(Path(root), rows)
    for root in (RT_TOOLS, ENGINE / "tools"):
        _s6_fp_walk(root, rows, suffixes=(".py", ".json"))
    for f in (getattr(p, "contract", None), getattr(p, "writer_manifest", None), getattr(p, "gsm", None),
              getattr(p, "asset_requirements", None), getattr(p, "overlay", None), CONFIG_PATH,
              scope.get("voice_registry"), scope.get("asset_library"), scope.get("asset_library_seed"),
              authority.get("orders_path")):
        if f:
            _s6_fp_walk(Path(f), rows)
    env = sorted((k, v) for k, v in os.environ.items()
                 if k.startswith(("NALU_", "QINGSHAN_", "STORYCLAW_")) and not SECRET_ENV_NAME.search(k)
                 and not k.startswith("NALU_S6_INRUN_"))
    return sha256_text(json.dumps({"argv": [str(a) for a in argv], "env": env, "files": rows},
                                  sort_keys=True, ensure_ascii=False))


def s6_compile(ctx: Ctx, *, ready_units=None) -> StageResult:
    """``stage_s2(with_keyframes=True, ready_units=...)``, skipped when nothing it could read or write changed
    since the last PASS compile with the same argv (s6_compile_fingerprint).  Typical hit: the ARE start-frame
    rebuild immediately followed by the 6.1 rebuild of the same wave, or a re-entry of an unchanged wave.
    The compile's own report is still what every later gate reads; a miss (any input or output changed, any
    non-PASS compile, NALU_S6_COMPILE_CACHE=0) runs the compile exactly as before."""
    argv = s2_argv(ctx, with_keyframes=True, ready_units=ready_units)
    logs = getattr(ctx.p, "logs", None)
    cache_path = Path(logs) / S6_COMPILE_CACHE_NAME if logs else None
    enabled = cache_path is not None and os.environ.get("NALU_S6_COMPILE_CACHE", "1") != "0"
    if enabled:
        try:
            fp = s6_compile_fingerprint(ctx, argv)
        except Exception as exc:  # noqa: BLE001 - no fingerprint, no cache: compile as before
            fp = None
            ctx.say(f"   S6 compile cache: fingerprint unavailable ({type(exc).__name__}); compiling")
        rec = read_json(cache_path, {}) or {}
        if fp and rec.get("fingerprint") == fp and rec.get("status") == PASS \
                and Path(ctx.p.preprod_report).is_file():
            ctx.say(f"-- S6 compile cache HIT: inputs/outputs unchanged since the compile at {rec.get('at')} "
                    f"(ready units {ready_units}); not recompiling")
            res = StageResult(PASS, compile_cache={"hit": True, "fingerprint": fp, "compiled_at": rec.get("at")})
            res.receipts = [str(ctx.p.preprod_report), str(ctx.p.machine_gate_bundle)]
            return res
    rebuilt = stage_s2(ctx, with_keyframes=True, ready_units=ready_units)
    if enabled:
        compiled_ok = rebuilt.status == PASS and all(
            int(step.get("exit_code") or 0) == 0 for step in rebuilt.steps
            if str(step.get("name") or "").startswith("s2_build_nalu_preproduction"))
        try:
            if compiled_ok:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(cache_path, {"schema": "nalu.s6_compile_cache.v1", "episode": ctx.episode,
                                        "fingerprint": s6_compile_fingerprint(ctx, argv), "status": PASS,
                                        "ready_units": list(ready_units) if ready_units is not None else None,
                                        "at": now(), "run_id": getattr(ctx, "run_id", None)})
            else:
                cache_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - a cache write never fails the stage
            ctx.say(f"   S6 compile cache: record not written ({type(exc).__name__})")
        rebuilt.details["compile_cache"] = {"hit": False}
    return rebuilt


def _s6_blocker_code(blocker: Any) -> str:
    text = re.sub(r"^(?:wave\d+:)+", "", str(blocker or "").strip())
    return text.split(":", 1)[0].strip()


#: test seams: the in-run poll sleeps and reads the clock only through these
_s6_sleep = time.sleep
_s6_clock = time.monotonic


class S6InRunPoll:
    """Keep an S6 run alive while a tail-chained successor waits on a unit this run just POSTed.

    Before (2026-11-19 diagnosis) every chain step cost ~12 min: the run POSTed, polled once, exited
    VIDEO_NOT_ALL_COMPLETED, and the next rerun came only after REMOTE_WAIT's 240 s + the 3-min tick.  Now,
    when this run has POSTed and the only thing left to do is wait for in-flight units that a successor's
    start frame depends on, the run sleeps ``interval`` and re-plans: the re-entry wave is live-bound, so that
    pass is a GET-only poll (no compile, no POST).  When the predecessor lands the same loop extracts its tail
    and prepares + submits the successor through every unchanged gate (order, budget, D-11, durable store).

    Bounds: one wait (since the last POST) <= ``max_wait_s`` (NALU_S6_INRUN_POLL_WAIT_SECONDS, 600), all
    in-run waiting <= ``max_total_s`` (NALU_S6_INRUN_POLL_MAX_SECONDS, 1500; 0 disables), interval
    NALU_S6_INRUN_POLL_INTERVAL_SECONDS (25, clamped 5..120).  Past a bound the run exits exactly as before
    and the system tick owns the long wait."""

    def __init__(self, ctx: Ctx) -> None:
        def _int(name: str, default: int) -> int:
            try:
                return int(float(os.environ.get(name) or default))
            except ValueError:
                return default
        self.max_total_s = max(0, _int("NALU_S6_INRUN_POLL_MAX_SECONDS", 1500))
        self.max_wait_s = max(0, _int("NALU_S6_INRUN_POLL_WAIT_SECONDS", 600))
        self.interval_s = min(120, max(5, _int("NALU_S6_INRUN_POLL_INTERVAL_SECONDS", 25)))
        self.enabled = bool(self.max_total_s and self.max_wait_s and getattr(ctx, "paid_enabled", False)
                            and not getattr(ctx, "dry", False))
        self.waited_total_s = 0
        self.waited_since_post_s = 0
        self.polls = 0
        self.posts: list[dict[str, Any]] = []
        self.chain_continuations = 0
        self.stop_reason: str | None = None
        self.started = _s6_clock()
        self.prep_started: float | None = self.started
        self.prep_origin = "RUN_START"

    # -- events ----------------------------------------------------------------------------------------
    def note_landed(self, units: list[str]) -> None:
        """A clip landed and its tail was extracted in this run: the next chain step's preparation starts now."""
        if not units:
            return
        if self.waited_since_post_s:
            self.chain_continuations += 1
        if self.prep_origin != "PREDECESSOR_LANDED":
            self.prep_started = _s6_clock()
            self.prep_origin = "PREDECESSOR_LANDED"

    def note_post(self, ctx: Ctx, wave_no: int, units: list[str], body_s: float) -> dict[str, Any]:
        t = _s6_clock()
        prep = t - (self.prep_started if self.prep_started is not None else t)
        row = {"wave": wave_no, "units": list(units), "prep_s": round(prep, 1), "prep_from": self.prep_origin,
               "body_s": round(body_s, 1), "wait_s": self.waited_since_post_s,
               "run_elapsed_s": round(t - self.started, 1)}
        self.posts.append(row)
        ctx.say(f"S6_CHAIN_STEP wave={wave_no} units={','.join(units)} prep={row['prep_s']}s "
                f"(from {self.prep_origin.lower()}; body={row['body_s']}s) wait={row['wait_s']}s "
                f"run_elapsed={row['run_elapsed_s']}s")
        self.waited_since_post_s = 0
        self.prep_started, self.prep_origin = t, "PREVIOUS_POST"
        return row

    # -- decision --------------------------------------------------------------------------------------
    def should_wait(self, pending: list[tuple[int, StageResult]], *, chain_blocked: list[str],
                    all_live_bound: bool) -> bool:
        """Sleep and re-plan in this run instead of exiting VIDEO_NOT_ALL_COMPLETED?"""
        reason = None
        if not self.enabled:
            reason = "DISABLED"
        elif not self.posts:
            reason = "NO_POST_THIS_RUN"
        elif not pending or any(r.status != BLOCKED or not r.blockers
                                or {_s6_blocker_code(b) for b in r.blockers} != {"VIDEO_NOT_ALL_COMPLETED"}
                                for _, r in pending):
            reason = "NOT_A_PURE_REMOTE_WAIT"
        elif not chain_blocked:
            reason = "NO_SUCCESSOR_WAITS_ON_AN_IN_FLIGHT_UNIT"
        elif not all_live_bound:
            reason = "IN_FLIGHT_WAVE_NOT_LIVE_BOUND"
        elif self.waited_total_s + self.interval_s > self.max_total_s:
            reason = "INRUN_POLL_MAX_SECONDS_REACHED"
        elif self.waited_since_post_s + self.interval_s > self.max_wait_s:
            reason = "INRUN_POLL_WAIT_SECONDS_REACHED"
        self.stop_reason = reason
        return reason is None

    def wait(self, ctx: Ctx, chain_blocked: list[str]) -> None:
        self.polls += 1
        ctx.say(f"-- S6 in-run poll {self.polls}: {sorted(chain_blocked)} wait(s) on an in-flight predecessor; "
                f"re-polling in {self.interval_s}s (waited {self.waited_since_post_s}s this step, "
                f"{self.waited_total_s}/{self.max_total_s}s this run)")
        _s6_sleep(self.interval_s)
        self.waited_total_s += self.interval_s
        self.waited_since_post_s += self.interval_s

    @property
    def extra_iterations(self) -> int:
        # every poll pass and every chain step continued in-run gets loop budget of its own
        return self.polls + S6_WAVE_LOOP_ITERATIONS * self.chain_continuations

    def summary(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "interval_s": self.interval_s, "max_wait_s": self.max_wait_s,
                "max_total_s": self.max_total_s, "polls": self.polls, "waited_total_s": self.waited_total_s,
                "chain_continuations": self.chain_continuations, "chain_steps": self.posts,
                "stop_reason": self.stop_reason}


def _s6_inrun_chain_state(ctx: Ctx, deps: list[tuple[str, str | None, bool]],
                          wave_state: dict[str, Any]) -> tuple[list[str], bool]:
    """(successors that wait on an in-flight unit's tail, every open wave's missing clips are live-bound)."""
    done_now = {uid for uid, _, _ in deps if (ctx.p.video_media / f"{uid}.mp4").is_file()}
    open_waves = [w for w in wave_state.get("waves") or [] if not w.get("completed_at")
                  and any(u not in done_now for u in w.get("units") or [])]
    in_flight = {u for w in open_waves for u in (w.get("units") or []) if u not in done_now}
    chain_blocked = [uid for uid, prev, needs in deps
                     if uid not in done_now and uid not in in_flight and needs and prev in in_flight]
    try:
        all_live = bool(open_waves) and all(_s6_live_bound_wave(ctx, list(w.get("units") or [])) is not None
                                            for w in open_waves)
    except Exception:  # noqa: BLE001 - cannot prove a GET-only re-entry: exit as before
        all_live = False
    return chain_blocked, all_live


def stage_s6(ctx: Ctx) -> StageResult:
    """Rolling-wave video stage (2026-09-13): wave N = units whose video is not yet on disk
    and whose predecessor tail (when the anchor plan demands one) has been extracted.  Each
    wave: strict compile on a partial-ready grouping, prompt-finalization checkpoint, D-11
    authorisation, paid submit, poll/download, tail extraction.  When every unit has its
    video, a final FULL compile (all tails present) rebuilds the complete transaction manifest
    and the post-generation QA / Q2 route runs over all units."""
    p = ctx.p
    tails_dir = p.preprod / "real_final_frames"
    # Plan §4: the same zero-credit previs gate guards the video stage.  It runs
    # before the wave scheduler plans anything, so a contract conflict is caught
    # before a single unit is authorised.
    previs = previs_gate(ctx, "S6")
    if previs.get("blocked"):
        res = StageResult(BLOCKED, previs_gate=previs)
        res.blockers = [f"PREVIS_MACHINE_FAILURE:{row.get('code')}:{row.get('ref')}"
                        for row in previs.get("machine_failures") or []] or ["PREVIS_BLOCKED"]
        res.receipts = [previs["receipt"]] if previs.get("receipt") else []
        return res
    # Wave membership is FROZEN once a wave has been submitted: the engine's submission
    # fingerprint covers position-dependent compiled contracts, so re-entering with a
    # different unit list (e.g. dropping the two units already downloaded) re-compiled
    # E01-VU-006 as a list head with a new fingerprint and the durable store let a second
    # paid POST through (2026-09-13 02:52Z, task 5f73dc87, ~200 credits wasted).  A wave
    # keeps exactly its recorded unit list until every one of its videos is on disk.
    wave_state_path = p.preprod_reports / f"{ctx.episode}_S6_WAVE_STATE.json"
    wave_state = read_json(wave_state_path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    released = release_unposted_waves(ctx, wave_state)
    if released:
        write_json(wave_state_path, wave_state)
        ctx.say(f"-- S6: released {len(released)} wave(s) that never POSTed: "
                + "; ".join(f"wave {r['wave']} ({r['reason']})" for r in released))
    inrun = S6InRunPoll(ctx)
    _iteration = 0
    while True:
        _iteration += 1
        if _iteration > S6_WAVE_LOOP_ITERATIONS + inrun.extra_iterations:
            break
        deps = unit_dependency_order(ctx)
        done = {uid for uid, _, _ in deps if (p.video_media / f"{uid}.mp4").is_file()}
        if not deps or len(done) == len(deps):
            break
        # E02+ continuity-derived start frames: materialise from the previous tail, then require a
        # Q1 (keyframe questionnaire) admission of that frame before the unit can join a wave.
        # CAMERA_GRAMMAR_V1: a §4/§5 redo after an objective speaker-framing / face-count FAIL first parks the
        # start frame that made the failed clip; a speaking unit only takes a tail that passes the objective
        # speaker check; either way the unit's own keyframe comes from the S5 keyframe path (one image each).
        stale_tails = park_stale_real_final_frames(ctx, [uid for uid, _, _ in deps])
        if stale_tails:
            ctx.say("-- S6: real final frames no longer current: "
                    + ", ".join(f"{r['unit_id']} ({r['status']})" for r in stale_tails))
        redo_switched = redo_switch_start_frames(ctx)
        if redo_switched:
            ctx.say("-- S6: controlled redo switches start frame to own keyframe: "
                    + ", ".join(f"{r['unit_id']} ({r['reason']})" for r in redo_switched))
        derived_rows = materialise_derived_keyframes(ctx)
        own_needed = own_keyframes_needed(ctx)
        own_touched = bool(own_needed) and not ctx.dry
        own_bound: list[dict[str, Any]] = []
        if own_needed and not ctx.dry:
            # an own keyframe generated + harvested earlier (another run, a failed-submit poll, a manual harvest)
            # is bound first, free -- never paid for twice (device 0080 E05 VU-001, 2026-11-21)
            own_bound = bind_harvested_own_keyframes(ctx, own_needed)
            if own_bound:
                ctx.say("-- S6: bound harvested own keyframe(s): "
                        + ", ".join(f"{r['unit_id']} <- {r['source']}" for r in own_bound))
                own_needed = own_keyframes_needed(ctx)
        if own_needed and not ctx.dry and own_keyframe_images_missing(ctx, own_needed):
            ctx.say(f"-- S6: {own_keyframe_images_missing(ctx, own_needed)} start from their own keyframe; generating "
                    "via the S5 keyframe path (~11 credits per image, D-46 plans only the missing images)")
            r5 = stage_s5(ctx)
            own_bound += bind_harvested_own_keyframes(ctx, own_keyframes_needed(ctx))
            still_missing = own_keyframe_images_missing(ctx, own_keyframes_needed(ctx))
            if r5.status != PASS or still_missing:
                r5.status = r5.status if r5.status in (HARD_STOP, REVIEW_REQUIRED) else BLOCKED
                r5.blockers = [f"S6.own_keyframe:{b}" for b in r5.blockers] or [
                    "S6.own_keyframe:OWN_KEYFRAME_NOT_GENERATED:" + ",".join(still_missing)]
                r5.details["own_keyframe_units"] = own_needed
                r5.details["own_keyframe_bound"] = own_bound
                r5.details["redo_start_frame_switch"] = redo_switched
                if still_missing:
                    r5.details["own_keyframe_diagnosis"] = own_keyframe_diagnosis(ctx, still_missing)
                return r5
            own_needed = own_keyframes_needed(ctx)
        # own keyframes whose Q1 admission names other bytes (units renumbered after the S5 review): same route
        q1_stale = [] if ctx.dry else own_keyframes_q1_stale(ctx)
        if q1_stale:
            ctx.say("-- S6: Q1 admission is not about the own keyframe on disk, re-admitting: " + ", ".join(q1_stale))
        if (own_needed or q1_stale) and not ctx.dry:
            # the image is on disk; what is left is its Q1 admission / start-frame receipt for these exact bytes
            # (a redo-switched unit).  S5's episode-wide Q1 reuses the newest review, which may not cover this
            # still, so the S6 loop asked S5 again and again and reported OWN_KEYFRAME_NOT_GENERATED.
            r_own = ensure_own_keyframe_admission(ctx, sorted(set(own_needed) | set(q1_stale)))
            if r_own is not None:
                r_own.details["own_keyframe_bound"] = own_bound
                return r_own
            if own_keyframes_needed(ctx):
                res = StageResult(BLOCKED)
                res.blockers.append("S6.own_keyframe:OWN_KEYFRAME_NOT_BOUND:" + ",".join(own_keyframes_needed(ctx)))
                res.details["own_keyframe_diagnosis"] = own_keyframe_diagnosis(ctx, own_keyframes_needed(ctx))
                return res
        if own_touched:
            derived_rows = materialise_derived_keyframes(ctx)
        pending_q1 = [(uid, shot) for uid, shot in derived_units_pending_q1(ctx) if uid not in done]
        # A unit waiting on its own Q1 must only hold ITSELF back.  Until 2026-10-01 any pending
        # derived unit returned here before the wave was planned, so one rejected start frame
        # (E10-VU-022) froze ten admitted, tail-ready units for two days.  Units run concurrently
        # unless they need a predecessor's tail (Roger: 能并发一定并发).
        pending_ids = {uid for uid, _ in pending_q1}
        _derived_now = tail_sourced_units(ctx)
        others_ready = [uid for uid, prev, needs in deps
                        if uid not in done and uid not in pending_ids
                        and (not needs or prev is None or (tails_dir / f"{prev}.png").is_file())
                        and (uid not in _derived_now or _derived_now[uid]["keyframe_path"].is_file())]
        if others_ready and pending_q1:
            ctx.say(f"-- S6: {sorted(pending_ids)} wait(s) on Q1; not holding back {len(others_ready)} ready unit(s)")
            pending_q1_deferred, pending_q1 = pending_q1, []
        else:
            pending_q1_deferred = []
        # D-5 receipts for derived frames that are already Q1-admitted (the review protocol's submit
        # may have materialised the admissions itself, so this must not depend on pending_q1)
        # keyed on the exact start frame on disk: a receipt of older bytes (frame re-materialised, normalised,
        # text-cleaned, or switched to the unit's own keyframe since) is regenerated, never trusted by its name
        need_sfe_now = {uid: info["keyframe_path"] for uid, info in tail_sourced_units(ctx).items()
                        if uid not in done and info["keyframe_path"].is_file()
                        and uid not in pending_ids
                        and start_frame_receipt_state(uid, info["keyframe_path"]) != SFE_CURRENT}
        # 2026-10-01: a review gate must not stop the pipeline from polling/downloading a wave that is
        # already submitted.  The review request is still issued at once (so the reviewer works while the
        # provider renders); its blocker is merged into the result after the wave poll.  With no wave in
        # flight the review returns exactly as before.
        _wave_in_flight = any(not w.get("completed_at") and any(u not in done for u in w.get("units") or [])
                              for w in wave_state.get("waves") or [])
        _CONT = object()

        def _derived_reviews():
            if need_sfe_now and not pending_q1:
                res = StageResult(REVIEW_REQUIRED)
                outcome = ensure_derived_start_frame_receipts(ctx, res, need_sfe_now)
                if outcome == "WRITTEN" or outcome == "OK":
                    return _CONT
                return res
            if pending_q1:
                res = StageResult(REVIEW_REQUIRED)
                res.details["derived_keyframes"] = derived_rows
                res.details["derived_units_pending_q1"] = pending_q1
                # One review file per still: gather the answered ones across every valid submitted
                # review (newest per still) instead of only the newest review, or two pending derived
                # frames ask for each other in turn and never reach the build below.
                review_path, covered, unanswered = merge_keyframe_answers(
                    ctx, [shot for _, shot in pending_q1])
                if unanswered:
                    # a still with no valid submitted answer: ask for exactly those
                    res.details.update(request_review(ctx, res, "keyframe", sub_stage="S6.q1_derived",
                                                      note="continuity-derived start frames (previous unit real tail) need the keyframe questionnaire",
                                                      items=unanswered))
                    res.blockers.append(f"S6.q1_derived:REVIEW_REQUIRED:{len(unanswered)}_frames")
                    return res
                if review_path is not None:
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
                        res.details["derived_start_frame_acceptance"] = apply_derived_start_frame_acceptance(
                            ctx, _ix, _ip)
                    still = [(uid, shot) for uid, shot in derived_units_pending_q1(ctx) if uid not in done]
                    if still:
                        res.status = BLOCKED
                        res.blockers.append("S6.q1_derived:NOT_ADMITTED:" + ",".join(uid for uid, _ in still))
                        # name the default acceptance that admits each still (device 1485 E03, 2026-11-21: only
                        # the start-frame route's refusal was shown, so the agent waited for a receipt the engine
                        # writes only AFTER Q1 admission, instead of recording the per-gate Q1 orders)
                        if _ix:
                            res.details["q1_orders_needed"] = q1_orders_needed(ctx, _ix, [u for u, _ in still])
                        res.details["next"] = (
                            "quality never blocks: record one default-acceptance order per failing Q1 gate listed in "
                            "q1_orders_needed (CLAUDE_CODE_PRODUCTION §5: --gate-id <gate_id>, one --detector per "
                            "listed detector, --media <item_id>=<start frame>; one order per gate may carry all "
                            "units), then resume S6.  The START-FRAME-SEMANTIC-EVIDENCE receipt is written by the "
                            "engine after admission -- it is not a precondition and must not be hand-made.")
                        return res
                    # D-5 start-frame receipt for the derived frames (same route as S5.sfe, scoped), keyed on the
                    # exact admitted bytes
                    _tsu = tail_sourced_units(ctx)
                    need_sfe = {uid: _tsu[uid]["keyframe_path"] for uid, _ in pending_q1 if uid in _tsu}
                    outcome = ensure_derived_start_frame_receipts(ctx, res, need_sfe)
                    if outcome == "STOP":
                        return res
                    return _CONT  # admissions + receipts present; re-plan the wave
                # no valid submitted answer covered the pending stills (merge_keyframe_answers
                # returned missing): ask for exactly those, never build on absent answers.
                missing_now = sorted(set(shot for _, shot in pending_q1) - set(covered))
                res.details.update(request_review(ctx, res, "keyframe", sub_stage="S6.q1_derived",
                                                  note="continuity-derived start frames (previous unit real tail) need the keyframe questionnaire",
                                                  items=missing_now or [shot for _, shot in pending_q1]))
                res.blockers.append(f"S6.q1_derived:REVIEW_REQUIRED:{len(missing_now or pending_q1)}_frames")
                return res
            return None

        _rv = _derived_reviews()
        if _rv is _CONT:
            continue
        deferred_review = None
        if _rv is not None:
            if _rv.status == REVIEW_REQUIRED and _wave_in_flight:
                deferred_review = _rv
                ctx.say(f"-- S6: review requested ({', '.join(_rv.blockers)}); polling the in-flight wave meanwhile")
            else:
                return _rv
        # Overlapping waves (2026-10-01).  A wave keeps its frozen membership until every video is on
        # disk (the 09-13 double-POST came from re-entering ONE wave with a different list), but a unit
        # that was never in any wave no longer waits for the in-flight wave to finish: it opens its own
        # wave in the same pass.  Each wave records its own submit/status report, because the submitter
        # overwrites its --out file and the poller only downloads what that report lists -- a shared
        # report would silently drop the in-flight wave's tasks.  Waves opened before this change have no
        # recorded report and keep the legacy shared paths.
        waves = wave_state.setdefault("waves", [])
        open_waves = [w for w in waves if not w.get("completed_at")
                      and any(uid not in done for uid in w.get("units") or [])]
        in_open = {u for w in open_waves for u in (w.get("units") or [])}
        derived = tail_sourced_units(ctx)
        # A clip harvested by a run that was killed before its tail frame was extracted (extraction
        # only runs inside the wave loop below) would keep its tail-chained successor "not ready"
        # forever: no open wave, no ready unit -> ROLLING_WAVE_NO_READY_UNITS on every tick
        # (Twelve Gazes E01, 2026-10-22).  Extract missing tails of on-disk clips first (idempotent).
        _no_tail = [uid for uid in sorted(done) if not (tails_dir / f"{uid}.png").is_file()]
        for row in s6_burn_check_landed(ctx, _no_tail):  # burned-text check before the tail is cut
            if row.get("action") == "RETRY":
                done.discard(row["unit_id"])
        _s6_sync_burn_state(wave_state, wave_state_path)
        for uid in sorted(done):
            if not (tails_dir / f"{uid}.png").is_file():
                extract_real_final_frame(ctx, uid)
        new_ready = [uid for uid, prev, needs in deps
                     if uid not in done and uid not in pending_ids and uid not in in_open
                     and (not needs or prev is None or (tails_dir / f"{prev}.png").is_file())
                     and (uid not in derived or derived[uid]["keyframe_path"].is_file())]
        # Remote-in-flight bound (2026-10-13).  ``--concurrency`` only bounds how many POST threads
        # the submitter runs; it says nothing about how many units are still generating on the
        # provider's side.  A wave used to open with EVERY ready unit, so one tick could put the whole
        # remaining episode into remote generation (E11 wave 1: 20 units) while --concurrency stayed
        # at 3.  The HTTP response returning a task_id does not free a provider generation slot, so a
        # ceiling on this has to be counted in remote tasks, not in POST threads.
        #
        # OPT-IN, and that is deliberate.  This bound is only applied when the runtime config names
        # one (generation.max_remote_inflight); with no configured limit the scheduler behaves exactly
        # as before.  Defaulting it to max_parallel would silently cap every wave at 3 and hand the
        # provider far less concurrent work than production deliberately does — a throughput
        # regression dressed as a fix.  The right ceiling is a property of the provider account, not
        # of a POST thread pool, so it is a deployment decision (proposal §5: do not write 1, 3 or 6
        # into every deployment).  Shadow-compare before enabling it.
        ceiling = getattr(ctx, "max_remote_inflight", None)
        if ceiling:
            # Units in open waves with no video on disk are still occupying the provider.
            remote_in_flight = {uid for w in open_waves
                                for uid in (w.get("units") or []) if uid not in done}
            headroom = max(0, int(ceiling) - len(remote_in_flight))
            if len(new_ready) > headroom:
                ctx.say(f"-- S6 remote in-flight bound: {len(remote_in_flight)}/{ceiling} provider "
                        f"task(s) still generating; deferring {len(new_ready) - headroom} of "
                        f"{len(new_ready)} ready unit(s)")
                new_ready = new_ready[:headroom]
        if not open_waves and not new_ready:
            res = StageResult(BLOCKED)
            res.blockers.append("ROLLING_WAVE_NO_READY_UNITS")
            res.details = {"done": sorted(done), "waiting": [uid for uid, _, _ in deps if uid not in done]}
            return res
        if new_ready:
            wave_no = max([int(w["wave"]) for w in waves] or [0]) + 1
            stem = ctx.p.video_submit.stem
            # Dispatch observability (proposal §5).  Record why the units that are NOT in this wave
            # are waiting, so a slow pass can be attributed instead of guessed at.  These counters
            # only observe: nothing here changes which units are submitted.
            blocked_by_tail = [uid for uid, prev, needs in deps
                               if uid not in done and uid not in pending_ids and uid not in in_open
                               and needs and prev is not None and not (tails_dir / f"{prev}.png").is_file()]
            ready_now = {uid for uid in new_ready}
            ready_units = {
                "ready_count": len(new_ready),
                "blocked_by_dependency": sorted(blocked_by_tail),
                "blocked_by_tail_frame_count": len(blocked_by_tail),
                "in_flight_waves": [int(w["wave"]) for w in open_waves],
                "in_flight_unit_count": len({uid for w in open_waves
                                             for uid in (w.get("units") or []) if uid not in done}),
                "videos_on_disk": len(done),
                "units_total": len(deps),
                "waves_opened_total": wave_no,
            }
            waves.append({"wave": wave_no, "units": new_ready, "opened_at": now(), "done_before": sorted(done),
                          "readiness": ready_units,
                          "submit_report": str(ctx.p.video_submit.with_name(f"{stem}_wave{wave_no}.json")),
                          "status_report": str(ctx.p.video_remote_status.with_name(
                              f"{ctx.p.video_remote_status.stem}_wave{wave_no}.json"))})
            write_json(wave_state_path, wave_state)
            ctx.say(f"-- S6 rolling wave {wave_no}: {len(new_ready)} ready unit(s) {sorted(ready_now)}; "
                    f"{len(done)}/{len(deps)} videos on disk"
                    + (f"; {len(blocked_by_tail)} blocked on a predecessor tail frame" if blocked_by_tail else "")
                    + (f"; overlapping in-flight wave(s) {[int(w['wave']) for w in open_waves]}" if open_waves else ""))
            open_waves.append(waves[-1])
        legacy_submit, legacy_status = ctx.p.video_submit, ctx.p.video_remote_status
        results: list[tuple[int, StageResult]] = []
        try:
            for w in open_waves:
                wave_no, ready = int(w["wave"]), list(w["units"])
                if w is not waves[-1] or not new_ready:
                    ctx.say(f"-- S6 rolling wave {wave_no} (re-entry, frozen membership): {len(ready)} unit(s) {ready}; "
                            f"{sum(1 for u in ready if u in done)} of them already on disk; {len(done)}/{len(deps)} videos on disk")
                ctx.p.video_submit = Path(w["submit_report"]) if w.get("submit_report") else legacy_submit
                ctx.p.video_remote_status = Path(w["status_report"]) if w.get("status_report") else legacy_status
                # Harvest before recompile (lab E05 2026-10-26).  A re-entry wave whose missing clips
                # are ALL live-bound to provider tasks is polled from the durable store directly: no
                # S2 rebuild, no fingerprint, no submitter.  Recompiling first drifted VU-001's
                # fingerprint and POSTed a duplicate 48-credit task for a redo that was still rendering.
                live_poll = None
                if w is not waves[-1] or not new_ready:
                    live_poll = _s6_live_bound_wave(ctx, ready)
                if live_poll is not None:
                    r = _s6_poll_live_bound_wave(ctx, w, live_poll)
                else:
                    _t_body = _s6_clock()
                    r = _stage_s6_body(ctx, ready_units=ready, run_qa=False)
                    if r.details.get("posted_task_keys"):
                        r.details["s6_chain_step"] = inrun.note_post(
                            ctx, wave_no, [str(k) for k in r.details["posted_task_keys"]], _s6_clock() - _t_body)
                        if s6_burn_retry_note_posted(ctx, [str(k) for k in r.details["posted_task_keys"]]):
                            _s6_sync_burn_state(wave_state, wave_state_path)
                r.details["rolling_wave"] = {"wave": wave_no, "ready_units": ready, "done_before": sorted(done)}
                # Extract each unit's real final frame as soon as ITS OWN video lands, not when the
                # whole wave passes poll (2026-10-13).  The extraction is what unblocks a tail-chained
                # successor, so tying it to wave completion made a ready successor wait for every
                # unrelated unit in its wave (E11 wave11 carried 6 units at concurrency 3; a chain
                # successor in it waited on all 6).  extract_real_final_frame is idempotent
                # (ALREADY_PRESENT), so re-running it per tick costs one stat per finished unit.
                # S6 burned-text check (line owner 2026-11-19) BEFORE the tail is cut: a burned take that is
                # retried is parked here, so no successor (nor the in-run poll) ever anchors on it
                burn = s6_burn_check_landed(
                    ctx, [uid for uid in ready if (ctx.p.video_media / f"{uid}.mp4").is_file()])
                if burn:
                    r.details["s6_burn_check"] = burn
                    _s6_sync_burn_state(wave_state, wave_state_path)
                on_disk = [uid for uid in ready if (ctx.p.video_media / f"{uid}.mp4").is_file()]
                extracted = [extract_real_final_frame(ctx, uid) for uid in on_disk]
                inrun.note_landed([str(row.get("unit_id")) for row in extracted if row.get("status") == "EXTRACTED"])
                if extracted:
                    # accumulate across ticks: the wave's row set must keep every unit it has
                    # finished, or a later tick would publish a receipt that lost earlier tails.
                    receipt_path = tails_dir / f"_extraction_wave{wave_no}.json"
                    prior = read_json(receipt_path, {}) or {}
                    merged = {str(row.get("unit_id")): row for row in (prior.get("rows") or [])}
                    for row in extracted:
                        merged[str(row.get("unit_id"))] = row
                    r.details["real_final_frames"] = extracted
                    write_json(receipt_path, {"wave": wave_no, "rows": [merged[k] for k in sorted(merged)],
                                              "at": now()})
                    bad = [row for row in extracted
                           if row["status"] not in ("EXTRACTED", "ALREADY_PRESENT")]
                    if bad:
                        r.status = BLOCKED
                        r.blockers.append(f"REAL_FINAL_FRAME_EXTRACTION_FAILED:{','.join(x['unit_id'] for x in bad)}")
                if r.status == PASS:
                    w["completed_at"] = now()
                    write_json(wave_state_path, wave_state)
                results.append((wave_no, r))
                if ctx.dry and live_poll is None:
                    break  # a live-bound poll wave compiles nothing: keep showing the other waves' plans
        finally:
            ctx.p.video_submit, ctx.p.video_remote_status = legacy_submit, legacy_status
        if ctx.dry:
            first = results[0][1]
            first.details["waves_this_pass"] = {str(n): r.status for n, r in results}
            first.details["live_bound_polls"] = {str(n): r.details["live_bound_poll"] for n, r in results
                                                 if r.details.get("live_bound_poll")}
            return first
        pending = [(n, r) for n, r in results if r.status != PASS]
        if pending and len(pending) < len(results) and deferred_review is None:
            # a wave completed this pass, so new tails exist: re-plan now and submit what they unblock,
            # instead of leaving it for the next loop tick.  Progress-only, bounded by the outer loop.
            continue
        if pending and deferred_review is None and inrun.enabled:
            # In-run polling (2026-11-19): this run POSTed and a tail-chained successor only waits on an
            # in-flight unit -> sleep and re-plan here (GET-only re-entry) instead of exiting for the tick.
            chain_blocked, all_live = (_s6_inrun_chain_state(ctx, deps, wave_state) if inrun.posts
                                       else ([], False))
            if inrun.should_wait(pending, chain_blocked=chain_blocked, all_live_bound=all_live):
                inrun.wait(ctx, chain_blocked)
                continue
            if inrun.posts:
                ctx.say(f"-- S6 in-run poll: stop ({inrun.stop_reason}); the system tick follows the remote wait")
        if pending or deferred_review is not None:
            # report the most actionable wave first (a review the agent can answer beats "still rendering")
            order = {REVIEW_REQUIRED: 0, BLOCKED: 1}
            pending.sort(key=lambda nr: order.get(nr[1].status, 2))
            res = pending[0][1] if pending else deferred_review
            for n, r in pending[1:]:
                res.blockers = list(res.blockers) + [f"wave{n}:{b}" for b in r.blockers if b not in res.blockers]
            if deferred_review is not None and res is not deferred_review:
                res.blockers = list(res.blockers) + [b for b in deferred_review.blockers if b not in res.blockers]
                res.details["deferred_review"] = deferred_review.details
            res.details["waves_this_pass"] = {str(n): r.status for n, r in results}
            res.details["s6_inrun_poll"] = inrun.summary()
            return res
    _deps_final = unit_dependency_order(ctx)
    _missing = [uid for uid, _, _ in _deps_final if not (p.video_media / f"{uid}.mp4").is_file()]
    if _missing:
        # the wave loop ran out of iterations with work still in flight; never fall into the
        # all-units final pass with videos missing -- report and let the next tick continue.
        res = StageResult(BLOCKED)
        res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
        res.details = {"missing_videos": _missing, "note": "wave loop iteration budget exhausted this pass",
                       "s6_inrun_poll": inrun.summary()}
        return res
    ctx.say("-- S6 final pass: all unit videos on disk; full compile + post-generation QA")
    # final pass = every unit with its real predecessor tail bound (the wave block of the builder
    # binds tails only for listed units), submit step SKIPPED: nothing may be POSTed here.
    done_derived = accept_done_derived_start_frames(ctx)
    if done_derived:
        ctx.say(f"-- S6 final pass: start frames of finished units re-checked against line-owner orders: "
                f"{done_derived.get('status')} {done_derived.get('units')}")
    result = _stage_s6_body(ctx, ready_units=[uid for uid, _, _ in deps], run_qa=True, final_pass=True)
    if done_derived:
        result.details["done_derived_start_frame_acceptance"] = done_derived
    # CAMERA_GRAMMAR_V1 engine redo: the Q2 sub-stage parked clips for their one controlled redo; run the wave
    # loop again in this same pass (own keyframe, single-unit wave) instead of waiting for an operator decision
    if (result.details.get("q2_admission") or {}).get("q2_auto_redo_parked") and not getattr(ctx, "_q2_auto_redo_reentered", False):
        ctx._q2_auto_redo_reentered = True
        return stage_s6(ctx)
    return result


ACTION_ROLE_EVIDENCE = RT_TOOLS / "action_role_evidence_writer.py"


def are_units_without_start_frame_media(ctx: Ctx, units: list[str]) -> list[str]:
    """Units (of ``units``) whose start-frame semantic contract binds no image that exists on disk."""
    anchors = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_ANCHOR_PLAN_V1.json", {}) or {}
    contracts = {str(row.get("unit_id")): (row.get("start_frame_semantic_contract") or {})
                 for row in anchors.get("units") or []}
    out = []
    for uid in units:
        ref = (contracts.get(uid) or {}).get("reference_path")
        if uid in contracts and not (ref and Path(str(ref)).is_file()):
            out.append(uid)
    return sorted(set(out))


def s6_action_role_evidence(ctx: Ctx, res: StageResult, units: list[str] | None) -> dict[str, Any]:
    """S6.are — exact-output action-role verification of every start frame in scope.

    shot_media_admission_gate.precheck_submission_inputs (run by the engine submitter
    before any paid video POST) demands ``action_role_verification`` in the start-frame
    admission JSON whenever interaction_topology_contract.required is true, which the
    compile's enrich_unit_contract sets for every E01 unit.  The engine ships only the
    consumer; runtime/tools/action_role_evidence_writer.py writes the receipt from a
    submitted ``action_role`` review (reviewer looked at the real keyframe).
    """
    scope = set(units) if units else None
    # Only the units in scope are validated (the rows outside it were never acted on): a chain step re-checks the
    # newly unblocked unit, not the whole episode.  The final pass passes every unit, so it still checks all.
    scope_argv = ["--units", json.dumps(sorted(scope))] if scope else []
    verify_step = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "verify", "--episode", ctx.episode, *scope_argv],
                         name="s6_are_verify")
    res.steps.append(verify_step)
    report = qa_json(verify_step)
    needing = [uid for uid in (report.get("missing") or []) + (report.get("failing") or [])
               if scope is None or uid in scope]
    detail: dict[str, Any] = {"sub_stage": "S6.are", "verify": {k: report.get(k) for k in ("units", "pass", "missing", "failing")},
                              "scope": sorted(scope) if scope else "ALL", "needing_evidence": needing}
    if not needing:
        detail["status"] = PASS
        return detail
    # The action-role review is answered by looking at each unit's START FRAME — the
    # keyframe.  Before S5 has produced them there is no media to look at, so a request
    # here would ask a reviewer to answer 20 items whose every media path is missing
    # (E11, 2026-10-06: S5 was still DRY_PLANNED and the forward run reached S6 anyway).
    # S5 already refuses in exactly this case ("No review is requested for media that
    # does not exist"); S6.are must refuse the same way instead of emitting the request.
    keyframes_on_disk = (sorted(ctx.p.keyframes.glob("*-keyframe-v*.png"))
                         if ctx.p.keyframes.is_dir() else [])
    if not keyframes_on_disk:
        detail["status"] = BLOCKED
        detail["blockers"] = ["KEYFRAMES_NOT_ON_DISK"]
        detail["reason"] = ("no start-frame keyframe exists yet (S5 has not produced them), "
                            "so the action-role review has no media to look at.  No review is "
                            "requested for media that does not exist.")
        return detail
    # A tail-sourced unit (CONTINUITY_DERIVED_KEYFRAME / PREVIOUS_UNIT_REAL_FINAL_FRAME) only has a start
    # frame once its predecessor's real tail is extracted AND the S6 rebuild bound that path into the start-
    # frame contract; until then a request would carry media null (E04 VU-012/020/023, fleet device 1101).
    no_media = are_units_without_start_frame_media(ctx, needing)
    if no_media:
        detail["status"] = BLOCKED
        detail["blockers"] = ["ARE_START_FRAME_MEDIA_NOT_BOUND:" + ",".join(no_media)]
        detail["units_without_media"] = no_media
        detail["reason"] = ("the start-frame contract binds no existing image for these units yet; "
                            "no review is requested for media that does not exist")
        return detail
    review_path, review = latest_submitted_review(ctx, "action_role")
    covered = {row.get("item_id") for row in (review.get("items") or [])} if review_path else set()
    if review_path is not None and set(needing) <= covered:
        write_step = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "write", "--episode", ctx.episode,
                                  "--review", review_path], name="s6_are_write_receipts")
        res.steps.append(write_step)
        detail["write"] = qa_json(write_step)
        verify_again = qa_run(ctx, [ACTION_ROLE_EVIDENCE, "verify", "--episode", ctx.episode, *scope_argv],
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



def episode_video_model(episode: str) -> str:
    """The episode's video model (nalu_video_model: recorded / existing build / qingshan.json)."""
    import nalu_video_model as _vm
    return _vm.episode_video_model(episode)


def episode_video_resolution(episode: str) -> str:
    """The episode's fixed video resolution (nalu_video_model: H3 480p for new episodes, 768p for every
    episode started before 2026-11-12; SD2 720p)."""
    import nalu_video_model as _vm
    return _vm.episode_video_resolution(episode)


def video_task_credits(model: str, seconds: float, tasks: int, resolution: str | None = "768p") -> int:
    """Planning price: SD2 720p 20 credits/s; MiniMax-H3 768p 14 credits/s + 6 per task
    (materialize_paid_authorization.H3_CREDITS_PER_SECOND / H3_CREDITS_PER_TASK) on Giggle (no 480p price
    on record: the 768p figure is kept as the conservative upper bound); on the HopsAPI router (owner
    2026-10-29) the configurable per-second price at ``resolution`` (768p default 1.56 credits/s, 480p
    1.09, tools/hopsapi_video_client.estimated_batch_credits), rounded up."""
    if model == "MiniMax-H3" and video_provider_for(model) == "hopsapi":
        return _hopsapi().estimated_batch_credits(seconds, tasks, resolution=resolution)
    if model == "MiniMax-H3":
        return int(round(seconds * _paid_order.H3_CREDITS_PER_SECOND)) + _paid_order.H3_CREDITS_PER_TASK * tasks
    return int(round(seconds * 20))


def s6_planned_credits_for_unbound(ctx: Ctx) -> int:
    """Credits a paid S6 submit can still spend (video_task_credits) for every task of the
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
    bound_keys = s6_bound_task_keys(ctx, tasks, task_fingerprint)
    unbound = [t for t in tasks if str(t.get("task_key")) not in bound_keys]
    planned = video_task_credits(episode_video_model(ctx.episode),
                                 sum(float(t.get("duration_seconds") or 0) for t in unbound), len(unbound),
                                 episode_video_resolution(ctx.episode))
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
    bound_keys = s6_bound_task_keys(ctx, tasks, task_fingerprint)
    return [str(t.get("task_key")) for t in tasks if str(t.get("task_key")) not in bound_keys]


def s6_live_bindings(ctx: Ctx, task_key: str, *, exclude_fingerprints=(),
                     current_task: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Live provider bindings of one task key, whatever its recompiled fingerprint
    (tools/video_live_binding.py): bound, not terminally failed, and newer than the unit's last
    park.  Such a task is polled and harvested, never POSTed again.  With ``current_task`` a
    COMPLETED take of a different request (prompt / source reference shas) is not live: the
    stale-binding guard (JA-01 E01 2026-11-19, s6_retire_stale_bindings) archives it instead."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.video_live_binding import live_bindings  # engine, read-only
    return live_bindings(video_store_dir(ctx.episode), str(task_key), root=ENGINE, episode=ctx.episode,
                         exclude_fingerprints=exclude_fingerprints, current_task=current_task,
                         video_dirs=[ctx.p.video_media] + ([ctx.p.work / AB_VIDEO_DIRNAME]
                                                           if getattr(ctx.p, "work", None) else []))


def s6_bound_task_keys(ctx: Ctx, tasks: list[dict[str, Any]], task_fingerprint) -> set[str]:
    """Task keys already bound to a remote task: by exact fingerprint, or -- when a recompile drifted
    the fingerprint (lab E05 2026-10-26, episode-wide generation_contract_sha256) -- by a live
    binding of the same task key.  The submitter applies the same rule before any POST."""
    store_dir = video_store_dir(ctx.episode)
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.video_live_binding import zero_cost_retryable  # engine, read-only
    bound = set()
    for path in (store_dir.glob("*.json") if store_dir.is_dir() else []):
        row = read_json(path, {}) or {}
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
            if zero_cost_retryable(path, row):
                continue  # terminally failed at zero cost: the submitter releases it to a new attempt
            bound.add(str(row.get("submission_fingerprint")))
    keys = set()
    for t in tasks:
        key = str(t.get("task_key"))
        if task_fingerprint(t) in bound:
            keys.add(key)
            continue
        declared = [str(v) for v in (t.get("supersedes_submission_fingerprints") or [])]
        if s6_live_bindings(ctx, key, exclude_fingerprints=declared, current_task=t):
            keys.add(key)
    return keys


def s6_retire_stale_bindings(ctx: Ctx, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Stale-binding guard (fleet device JA-01, E01, 2026-11-19), before any S6 planning / authorisation / POST.

    The line owner ordered E01 redone in anime style; the device archived workflow/nalu/E01/ but not the durable
    video store, and 28 units reused their completed OLD live-action takes because "a bound transaction is never
    resubmitted" never compared the request.  For every task of the current compile WITHOUT a clip on disk, a
    COMPLETED live binding whose recorded prompt / source reference shas differ from the task is moved (never
    deleted) to ``giggle_video_submit_transactions/<EP>/_stale_<stamp>/``, together with an alternate take and the
    unit's tail frame; the unit then goes through every normal gate as a fresh attempt.  A differing take still
    rendering is only warned about and kept (polled, never re-POSTed).  An identical request (crash re-entry,
    lab E05 fingerprint drift) is reused exactly as before.  Dry runs archive nothing (the planner already
    leaves such a take out, so the plan shows the POST).  NALU_S6_STALE_BINDING_GUARD=0 opts out."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.video_live_binding import retire_stale_bindings, stale_binding_guard_enabled  # engine
    out: dict[str, Any] = {"archived": [], "in_flight": []}
    if getattr(ctx, "dry", False) or not stale_binding_guard_enabled():
        out["status"] = "SKIPPED_DRY" if getattr(ctx, "dry", False) else "DISABLED"
        return out
    video_dirs = [ctx.p.video_media] + ([ctx.p.work / AB_VIDEO_DIRNAME] if getattr(ctx.p, "work", None) else [])
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for t in tasks:
        key = str(t.get("task_key") or "")
        if not key or (ctx.p.video_media / f"{key}.mp4").is_file():
            continue
        declared = [str(v) for v in (t.get("supersedes_submission_fingerprints") or [])]
        try:
            got = retire_stale_bindings(video_store_dir(ctx.episode), t, root=ENGINE, episode=ctx.episode,
                                        exclude_fingerprints=declared, video_dirs=video_dirs, stamp=stamp,
                                        log=ctx.say)
        except Exception as exc:  # noqa: BLE001 - the guard never blocks: the live take is reused as before
            ctx.say(f"S6_STALE_BINDING_GUARD_ERROR unit={key}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        if got["archived"]:
            tail = ctx.p.preprod / "real_final_frames" / f"{key}.png"
            moved = []
            for path in (tail, tail.with_suffix(".source.sha256")):
                if path.is_file():
                    park = tail.parent / f"_superseded_{ctx.run_id}_stale_binding"
                    park.mkdir(parents=True, exist_ok=True)
                    os.replace(path, park / path.name)
                    moved.append(str(path))
            for record in got["archived"]:
                record["tail_moved"] = moved
        out["archived"].extend(got["archived"])
        out["in_flight"].extend(got["in_flight"])
    out["status"] = "ARCHIVED" if out["archived"] else "NONE"
    return out


def s6_redo_identical_to_parked_take(ctx: Ctx, tasks: list[dict[str, Any]], task_fingerprint) -> list[str]:
    """Task keys with no clip on disk whose ONLY binding is the take that was parked for a redo.

    Fleet device ...1205 E13 (2026-11-17): seven QA-rejected clips were parked for a controlled redo
    but the redo requests were byte-identical to the parked takes.  The exact-fingerprint match in
    s6_bound_task_keys read each unit as "already bound -> poll only", the new wave had no submit
    report, the poll child died on FileNotFoundError, the parent reported VIDEO_NOT_ALL_COMPLETED,
    release_unposted_waves (which ignores a take bound before the park) released the wave, and the
    heartbeat repeated that 90 times over nine hours.  An identical request is never POSTed again
    (K130), so nothing could ever arrive.  Such a unit is: clip missing, a clip of it parked, every
    bound record of its current fingerprint older than the park, and no live binding."""
    store_dir = video_store_dir(ctx.episode)
    if not store_dir.is_dir():
        return []
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.video_live_binding import bound_at, park_time  # engine, read-only
    video_dirs = [ctx.p.video_media] + ([ctx.p.work / AB_VIDEO_DIRNAME] if getattr(ctx.p, "work", None) else [])
    stale = []
    for t in tasks:
        key = str(t.get("task_key"))
        if (ctx.p.video_media / f"{key}.mp4").is_file():
            continue
        parked = park_time(key, video_dirs)
        if parked is None:
            continue
        fingerprint = task_fingerprint(t)
        stamps = []
        for path in store_dir.glob(f"{key}__*.json"):
            row = read_json(path, {}) or {}
            if (row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id")
                    and str(row.get("submission_fingerprint")) == fingerprint):
                stamps.append(bound_at(row))
        if not stamps or any(stamp is None or stamp > parked for stamp in stamps):
            continue
        declared = [str(v) for v in (t.get("supersedes_submission_fingerprints") or [])]
        if s6_live_bindings(ctx, key, exclude_fingerprints=declared, current_task=t):
            continue
        stale.append(key)
    return stale


#: tools/video_live_binding.ALT_TAKES_DIRNAME: a second live take of a unit is harvested here,
#: never over the unit's assembly clip and never into a park directory.
S6_ALT_TAKES_DIRNAME = "_alt_takes"


def _s6_live_bound_wave(ctx: Ctx, units: list[str]) -> dict[str, Any] | None:
    """{missing, live} when every unit of a re-entry wave without a clip on disk is live-bound to a
    provider task (so the wave needs a poll, not a compile); None otherwise."""
    missing = [uid for uid in units if not (ctx.p.video_media / f"{uid}.mp4").is_file()]
    if not missing:
        return None
    manifest_path = getattr(ctx.p, "video_transaction", None)
    manifest = (read_json(manifest_path, {}) or {}) if manifest_path else {}
    declared = {str(t.get("task_key")): [str(v) for v in (t.get("supersedes_submission_fingerprints") or [])]
                for t in manifest.get("tasks") or []}
    # the last compile of the unit is its current request: a completed take of a DIFFERENT request is not live
    # (stale-binding guard), so such a wave is compiled and goes through s6_retire_stale_bindings + the gates
    current = {str(t.get("task_key")): t for t in manifest.get("tasks") or []}
    live = {uid: s6_live_bindings(ctx, uid, exclude_fingerprints=declared.get(uid) or (),
                                  current_task=current.get(uid)) for uid in missing}
    if not all(live.values()):
        return None
    return {"missing": missing, "live": live}


def _s6_poll_live_bound_wave(ctx: Ctx, wave: dict[str, Any], plan: dict[str, Any]) -> StageResult:
    """Poll/harvest a re-entry wave straight from its live bindings: GET only, zero POSTs.

    The poll input is written from the durable store, not from the wave's submit report: the
    submitter overwrites that report, so a take bound by an earlier run (E05 wave 28: 4e2d4a56)
    is missing from it.  The oldest live take lands at <unit>.mp4; any further live take of the
    same unit goes to video/_alt_takes/ for the reviewer to choose from."""
    res = StageResult(PASS)
    wave_no = int(wave["wave"])
    rows: list[dict[str, Any]] = []
    for uid in plan["missing"]:
        for index, take in enumerate(plan["live"][uid]):
            label = uid if index == 0 else f"{uid}__take_{take['task_id'][:8]}"
            row = {"task_key": label, "unit_id": uid, "task_id": take["task_id"],
                   "transaction": take["transaction"], "submission_fingerprint": take["submission_fingerprint"],
                   "bound_at": take["bound_at"], "request_sha256": take.get("request_sha256"),
                   "live_take": index + 1, "recovered_from_transaction": True}
            if index:
                row["output_name"] = f"{S6_ALT_TAKES_DIRNAME}/{label}.mp4"
            rows.append(row)
    submit_report = Path(wave.get("submit_report") or ctx.p.video_submit)
    live_report = submit_report.with_name(f"{submit_report.stem}_live_bindings.json")
    write_json(live_report, {
        "schema": "nalu.s6_live_binding_poll.v1", "episode": ctx.episode, "wave": wave_no,
        "generated_at": now(), "posts_planned": 0, "tasks": rows,
        "note": "re-entry wave whose missing clips are all live-bound: poll/harvest only, no compile, no POST"})
    poll_argv = [VENV, ENGINE / "tools/poll_giggle_submit_report.py",
                 "--submit-report", live_report, "--out-dir", ctx.p.video_media,
                 "--status-report", ctx.p.video_remote_status, "--download"]
    res.details["live_bound_poll"] = {
        "wave": wave_no, "units": plan["missing"], "posts_planned": 0, "poll_input": str(live_report),
        "tasks": [{"task_key": r["task_key"], "task_id": r["task_id"], "bound_at": r["bound_at"]} for r in rows]}
    ctx.say(f"-- S6 wave {wave_no}: every missing clip is live-bound ({len(rows)} provider task(s): "
            + ", ".join(f"{r['task_key']}={r['task_id'][:8]}" for r in rows)
            + "); poll/harvest only, no recompile, no POST")
    if not ctx.paid_enabled:
        res.status = DRY
        res.blockers.append("PAID_STEPS_DISABLED_WAVE_NOT_POLLED")
        ctx.say(f"   then (needs {video_key_env(episode_video_model(ctx.episode))}, GET only, no POST, free):")
        ctx.say(f"     {q(poll_argv)}")
        ctx.planned_commands.append({
            "stage": "S6", "step": f"s6_poll_live_bound_wave{wave_no}", "planned_credits": 0,
            "paid_argv": [str(x) for x in poll_argv], "paid_command": q(poll_argv), "posts": 0,
            "note": "polls the live-bound provider tasks from the durable store; downloads completed clips only"})
        return res
    poll = ctx.run(poll_argv, name=f"s6_poll_live_bound_wave{wave_no}", paid=True, extra_env=VIDEO_SUBMIT_ENV)
    res.steps.append(poll)
    res.receipts.append(str(ctx.p.video_remote_status))
    remote = read_json(ctx.p.video_remote_status, {}) or {}
    res.details["remote_status_counts"] = remote.get("status_counts")
    res.details["all_completed"] = remote.get("all_completed")
    terminal = []
    for row in remote.get("results") or []:
        if str(row.get("remote_status") or "").lower() in {"failed", "error", "cancelled", "canceled", "timeout"}:
            # durable mark: the status report is overwritten by the next poll, the transaction is not
            tx_path = Path(str(row.get("transaction") or ""))
            tx = read_json(tx_path, {}) if tx_path.is_file() else {}
            if tx and tx.get("task_id") == row.get("task_id") and not tx.get("remote_terminal_state"):
                tx.update({"remote_terminal_state": str(row.get("remote_status")), "remote_terminal_observed_at": now()})
                write_json(tx_path, tx)
            terminal.append(str(row.get("task_key")))
    if poll.get("exit_code") != 0 or not remote.get("all_completed"):
        res.status = BLOCKED
        res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
        if terminal:
            res.blockers.append("LIVE_BOUND_TASK_TERMINAL_REMOTE_FAILURE:" + ",".join(terminal))
    return res


# --------------------------------------------------------------------------- #
# A/B variant — ONE isolated paid video task through the S6 machinery
# (owner-approved constraint-language A/B, lab E05 2026-10-26)
# --------------------------------------------------------------------------- #
#: tools/h3_constraint_ab_variant.SCHEMA — the only producer this mode accepts.
AB_VARIANT_SCHEMA = "qingshan.h3_constraint_language_ab_variant.v1"
#: tools/h3_constraint_ab_variant.LOCK_SCHEMA (``--variant camera_lock_strict``, lab E06 2026-10-26)
AB_VARIANT_LOCK_SCHEMA = "qingshan.h3_camera_lock_ab_variant.v1"
#: schema -> (variant kind, manifest+task field, value, task-key suffix); same producer, same guards
AB_VARIANT_KINDS = {
    AB_VARIANT_SCHEMA: ("constraint_language_zh", "h3_constraint_language", "zh", "ZH"),
    AB_VARIANT_LOCK_SCHEMA: ("camera_lock_strict", "h3_camera_lock", "strict", "LOCK"),
}
AB_VARIANT_PRODUCER = ENGINE / "tools/h3_constraint_ab_variant.py"
AB_VIDEO_DIRNAME = "video_ab"


def video_store_dir(episode: str) -> Path:
    """The durable video transaction store the submitter writes (task fingerprint dedup)."""
    return ENGINE / "workflow/tasks/giggle_video_submit_transactions" / episode


def ab_variant_paths(ctx: Ctx, task_key: str) -> dict[str, Path]:
    """Everything an A/B run writes.  The clip lands in ``<EP>/video_ab/`` — never in ``<EP>/video/``,
    which is what S6 QA, Q2 and S7 assembly read — so the variant can never replace the original take."""
    root = ctx.p.work / AB_VIDEO_DIRNAME
    return {
        "dir": root,
        "clip": root / f"{task_key}.mp4",
        "submit": root / f"{task_key}_VIDEO_SUBMIT.json",
        "remote_status": root / f"{task_key}_VIDEO_REMOTE_STATUS.json",
        "authorization_report": root / f"{task_key}_PAID_AUTHORIZATION.json",
        "run_report": root / f"{task_key}_AB_RUN.json",
        "rehearsal": root / f".rehearsal_{ctx.run_id}",
        "finalization_digest": ctx.p.preprod_reports / f"{task_key}_AB_PROMPT_FINALIZATION_DIGEST.json",
        # prompt_batch_finalize.py names receipts <unit_id>.json: a separate directory keeps the
        # variant's receipt from overwriting the original unit's receipt (and, per variant kind, another
        # variant's receipt for the same unit: <UNIT>-ZH keeps the original directory).
        "finalization_dir": ctx.p.preprod / ("prompt_batch_finalization_ab" if task_key.endswith("-ZH") or "-" not in task_key
                                             else f"prompt_batch_finalization_ab_{task_key.rsplit('-', 1)[1].lower()}"),
    }


def _engine_rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ENGINE.resolve()))
    except ValueError:
        return str(Path(path).resolve())


def ab_variant_failures(ctx: Ctx, path: Path, doc: dict[str, Any]) -> list[str]:
    """Structural provenance checks (free, offline).  Every failure is a refusal before money moves.

    The variant must be exactly what tools/h3_constraint_ab_variant.py writes for a unit of THIS
    episode: its schema, one task keyed ``<UNIT>-ZH`` (``<UNIT>-LOCK`` for the camera-lock kind), not yet authorised, MiniMax-H3 under
    CAMERA_GRAMMAR_V1, built from this episode's grouped manifest, and its source unit present in
    the episode's authority (grouping plan + whole-batch prompt registry + the transaction manifest,
    or — when a rolling wave has narrowed that manifest — the source's bound English transaction,
    with the same references and model)."""
    failures: list[str] = []
    try:
        Path(path).resolve().relative_to(ctx.p.preprod.resolve())
    except ValueError:
        failures.append(f"AB_VARIANT_OUTSIDE_EPISODE_PREPRODUCTION:{path}")
    kind = AB_VARIANT_KINDS.get(str(doc.get("ab_variant_schema") or ""))
    if kind is None:
        failures.append(f"AB_VARIANT_SCHEMA_MISMATCH:{doc.get('ab_variant_schema')}")
        kind = AB_VARIANT_KINDS[AB_VARIANT_SCHEMA]
    elif kind[0] != "constraint_language_zh" and doc.get("ab_variant_kind") != kind[0]:
        failures.append(f"AB_VARIANT_KIND_MISMATCH:{doc.get('ab_variant_kind')}!={kind[0]}")
    if str(doc.get("episode") or "") != ctx.episode:
        failures.append(f"AB_VARIANT_FOREIGN_EPISODE:{doc.get('episode')}!={ctx.episode}")
    if doc.get("provider_post_allowed") is not False or doc.get("maximum_new_submissions") != 1:
        failures.append("AB_VARIANT_NOT_AS_PRODUCED:authority fields are set only on the D-11 copy")
    tasks = doc.get("tasks") or []
    if len(tasks) != 1:
        failures.append(f"AB_VARIANT_MUST_HAVE_EXACTLY_ONE_TASK:{len(tasks)}")
        return failures
    task = tasks[0]
    source = str(doc.get("ab_variant_of") or "")
    _kind_name, field, expected, suffix = kind
    value = str(doc.get(field) or "")
    if value != expected or task.get(field) != value:
        failures.append(("AB_VARIANT_LANGUAGE_UNSUPPORTED" if field == "h3_constraint_language"
                         else "AB_VARIANT_CAMERA_LOCK_UNSUPPORTED") + f":{value}/{task.get(field)}")
    if (not source.startswith(f"{ctx.episode}-") or task.get("ab_variant_of") != source
            or task.get("unit_id") != source or task.get("task_key") != f"{source}-{suffix}"):
        failures.append(f"AB_VARIANT_TASK_KEY_NOT_DERIVED_FROM_SOURCE:{task.get('task_key')}<-{source}")
    if str(task.get("episode") or "") != ctx.episode:
        failures.append(f"AB_VARIANT_TASK_FOREIGN_EPISODE:{task.get('episode')}")
    if str(task.get("model") or "") != "MiniMax-H3":
        failures.append(f"AB_VARIANT_MODEL_NOT_H3:{task.get('model')}")
    grammar = ((task.get("camera_plan") or {}).get("camera_grammar")
               or ((task.get("machine_contract") or {}).get("camera_plan") or {}).get("camera_grammar"))
    if grammar != "CAMERA_GRAMMAR_V1":
        failures.append(f"AB_VARIANT_NOT_CAMERA_GRAMMAR_V1:{grammar}")
    if str(doc.get("source_grouped_manifest") or "") != _engine_rel(ctx.p.grouped_seedance):
        failures.append(f"AB_VARIANT_SOURCE_MANIFEST_MISMATCH:{doc.get('source_grouped_manifest')}")
    prompt = ENGINE / str(task.get("prompt_file") or "")
    try:
        prompt.resolve().relative_to(ctx.p.preprod.resolve())
        if not prompt.is_file() or sha256_file(prompt) != task.get("prompt_sha256"):
            failures.append("AB_VARIANT_PROMPT_SHA_MISMATCH")
    except ValueError:
        failures.append(f"AB_VARIANT_PROMPT_OUTSIDE_EPISODE:{task.get('prompt_file')}")
    # the source unit, against the episode's own authority
    plan_units = {str(u.get("unit_id")) for u in (read_json(ctx.p.grouping_plan, {}) or {}).get("units") or []}
    if source not in plan_units:
        failures.append(f"AB_SOURCE_UNIT_NOT_IN_GROUPING_PLAN:{source}")
    batch = read_json(ctx.p.preprod / f"{ctx.episode}_PROMPT_BATCH_V1.json", {}) or {}
    row = next((r for r in batch.get("rows") or [] if r.get("unit_id") == source and not r.get("parent_unit_id")), None)
    if row is None or row.get("mode") == "REUSE_EXISTING_MEDIA":
        failures.append(f"AB_SOURCE_UNIT_NOT_IN_PROMPT_BATCH:{source}")
    authority = read_json(ctx.p.video_transaction, {}) or {}
    if any(str(t.get("task_key")) == str(task.get("task_key")) for t in authority.get("tasks") or []):
        failures.append(f"AB_VARIANT_TASK_KEY_COLLIDES_WITH_EPISODE_TASK:{task.get('task_key')}")
    # The A/B pairs with the English take that was actually submitted: prefer its immutable bound transaction.
    # A later recompile of the manifest may carry different references (e.g. a predecessor tail) that the
    # English clip never had (lab E05 2026-10-26).
    origin, origin_kind = None, "BOUND_TRANSACTION"
    store = video_store_dir(ctx.episode)
    bound = [read_json(c, {}) or {} for c in (sorted(store.glob(f"{source}__*.json")) if store.is_dir() else [])]
    bound = [r for r in bound if r.get("state") == "SUBMITTED_TASK_ID_BOUND" and r.get("task_id")]
    origin = next((r for r in bound if list(r.get("reference_sha256") or []) == list(task.get("reference_sha256") or [])
                   and str(r.get("model") or "") == str(task.get("model") or "")), None)
    if origin is None and bound:
        origin = bound[-1]
    if origin is None:
        origin = next((t for t in authority.get("tasks") or [] if str(t.get("task_key")) == source), None)
        origin_kind = "TRANSACTION_MANIFEST"
    if origin is None:
        failures.append(f"AB_SOURCE_UNIT_NOT_IN_AUTHORITATIVE_MANIFEST:{source}")
    else:
        if list(origin.get("reference_sha256") or []) != list(task.get("reference_sha256") or []):
            failures.append(f"AB_VARIANT_REFERENCES_DIFFER_FROM_SOURCE:{origin_kind}")
        if str(origin.get("model") or "") != str(task.get("model") or ""):
            failures.append(f"AB_VARIANT_MODEL_DIFFERS_FROM_SOURCE:{origin_kind}")
    planned = video_task_credits(str(task.get("model") or ""), float(task.get("duration_seconds") or 0), 1,
                                 task.get("resolution"))
    if doc.get("estimated_credits") != planned:
        failures.append(f"AB_VARIANT_ESTIMATE_MISMATCH:{doc.get('estimated_credits')}!={planned}")
    return failures


def ab_variant_registration(ctx: Ctx, task: dict[str, Any]) -> str | None:
    """None when the variant's exact prompt is registered in the whole-batch prompt QA (K041) the way
    the submitter will check it; otherwise the gate's refusal."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        from tools.episode_prompt_batch_gate import require_generation_batch  # engine, read-only
        require_generation_batch(task, VIDEO_PROJECT_ROOT, artifact_kind="video_prompt")
    except Exception as exc:  # noqa: BLE001 - the refusal text is the answer
        return f"{type(exc).__name__}:{exc}"
    return None


def ab_task_bound(ctx: Ctx, task: dict[str, Any]) -> bool:
    """The variant's exact fingerprint is already bound to a remote task (re-entry: poll only)."""
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from tools.submit_giggle_video_manifest_v2 import task_fingerprint  # engine, read-only
    store = video_store_dir(ctx.episode)
    fingerprint = task_fingerprint(task)
    for path in sorted(store.glob(f"{task.get('task_key')}__*.json")) if store.is_dir() else []:
        row = read_json(path, {}) or {}
        if (row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id")
                and str(row.get("submission_fingerprint")) == fingerprint):
            return True
    return False


def ab_poll_until_complete(ctx: Ctx, res: StageResult, poll_argv: list[Any], status_path: Path) -> bool:
    """Poll (no POST) until the one task completes and is downloaded, within a bounded wait.
    A timeout is not a failure of the spend: re-running the same command polls again."""
    timeout = int(os.environ.get("NALU_AB_POLL_TIMEOUT_SECONDS") or 1200)
    interval = max(5, int(os.environ.get("NALU_AB_POLL_INTERVAL_SECONDS") or 20))
    waited = 0
    while True:
        step = ctx.run(poll_argv, name="ab_poll_giggle_submit_report", paid=True, extra_env=VIDEO_SUBMIT_ENV)
        res.steps.append(step)
        remote = read_json(status_path, {}) or {}
        res.details["remote_status_counts"] = remote.get("status_counts")
        if remote.get("all_completed"):
            return True
        if any(str(k).lower() in {"failed", "error", "cancelled"} for k in (remote.get("status_counts") or {})):
            return False
        if waited >= timeout:
            return False
        time.sleep(interval)
        waited += interval


def run_ab_variant(ctx: Ctx, variant: Path) -> int:
    """``paid_stage.sh <EP> --ab-variant <manifest>``: one A/B task, isolated from the episode.

    Same machinery as a normal S6 submit, nothing bypassed: provenance + source checks, the whole-batch
    prompt registration (an INCREMENTAL_EXACT_MATERIALIZATION_QA receipt for the variant's exact text),
    D-11 materialisation from the active order restricted to this one task key, ``Ctx.paid_step``
    (order-stage check, budget check with an atomic reservation against the episode cap, release once
    the submitter exits 0), the durable fingerprint store, the batch credit statement archived where
    the ledger counts it, and a ledger entry.  Output goes to ``<EP>/video_ab/`` only.
    """
    res = StageResult(PASS)
    path = Path(variant)
    if not path.is_absolute():
        path = (Path.cwd() / path) if (Path.cwd() / path).is_file() else ENGINE / path
    doc = read_json(path, None)
    report: dict[str, Any] = {"schema": "nalu.ab_variant_run.v1", "episode": ctx.episode, "variant": str(path),
                              "variant_kind": ((AB_VARIANT_KINDS.get(str((doc or {}).get("ab_variant_schema") or ""))
                                                or ("UNKNOWN",))[0] if isinstance(doc, dict) else "UNKNOWN"),
                              "variant_sha256": sha256_file(path) if path.is_file() else None,
                              "run_id": ctx.run_id, "started_at": now(), "paid_enabled": ctx.paid_enabled}
    ab_key = video_key_env(episode_video_model(ctx.episode))
    if ctx.paid_enabled and not os.environ.get(ab_key, "").strip():
        # Never reserve credits or materialise authority for a submit that cannot start: the
        # submitter would exit "<KEY> is not set" after both, leaving a held reservation.
        ctx.paid_enabled = False
        ctx.paid_disabled_reason = f"{ab_key} is not set"
    ctx.say(f"-- A/B variant {path} ({'PAID' if ctx.paid_enabled else 'NO SPEND'})")

    def finish(status: str, blockers: list[str] | None = None, code: int | None = None) -> int:
        res.status = status
        res.blockers.extend(blockers or [])
        report.update({"status": status, "blockers": res.blockers, "details": res.details,
                       "steps": [{k: v for k, v in s.items() if k != "stdout_tail"} for s in res.steps],
                       "planned_commands": ctx.planned_commands, "finished_at": now()})
        out = report.get("run_report")
        if out:
            write_json(Path(out), report)
        ctx.say(f"   A/B => {status}" + (f"   blockers: {', '.join(res.blockers)}" if res.blockers else ""))
        if code is not None:
            return code
        return {PASS: 0, DRY: 0, REVIEW_REQUIRED: REVIEW_EXIT_CODE, HARD_STOP: 3}.get(status, 2)

    if not isinstance(doc, dict):
        return finish(BLOCKED, [f"AB_VARIANT_UNREADABLE:{path}"])
    failures = ab_variant_failures(ctx, path, doc)
    if failures:
        return finish(BLOCKED, failures)
    task = doc["tasks"][0]
    key = str(task["task_key"])
    paths = ab_variant_paths(ctx, key)
    if paths["dir"].resolve() == ctx.p.video_media.resolve():
        return finish(BLOCKED, ["AB_OUTPUT_WOULD_ENTER_EPISODE_VIDEO_DIR"])
    paths["dir"].mkdir(parents=True, exist_ok=True)
    report["run_report"] = str(paths["run_report"])
    report["outputs"] = {k: str(v) for k, v in paths.items() if k != "rehearsal"}

    # the producer re-renders the variant prompt and must reproduce these exact bytes
    verify = ctx.run([VENV, AB_VARIANT_PRODUCER, "--verify", path], name="ab_variant_verify")
    res.steps.append(verify)
    if verify["exit_code"] != 0:
        return finish(BLOCKED, ["AB_VARIANT_NOT_REPRODUCED_BY_PRODUCER:" + (verify.get("stdout_tail") or "")[-300:]])

    if paths["clip"].is_file():
        res.details["clip"] = str(paths["clip"])
        ctx.say(f"   already harvested: {paths['clip']} (no POST)")
        return finish(PASS)

    poll_argv = [VENV, ENGINE / "tools/poll_giggle_submit_report.py", "--submit-report", paths["submit"],
                 "--out-dir", paths["dir"], "--status-report", paths["remote_status"], "--download"]
    bound = ab_task_bound(ctx, task)
    res.details["bound_in_durable_store"] = bound
    status = PASS
    if not bound:
        refusal = ab_variant_registration(ctx, task)
        if refusal:
            fin = ctx.run([VENV, RT_TOOLS / "prompt_batch_finalize.py", "diff", "--episode", ctx.episode,
                           "--execution-id", f"{ctx.episode}-PROMPT-BATCH-V1", "--out", paths["finalization_digest"],
                           "--batch-path", ctx.p.preprod / f"{ctx.episode}_PROMPT_BATCH_V1.json",
                           "--transaction-path", path],
                          name="ab_prompt_batch_finalization_diff")
            res.steps.append(fin)
            res.details["prompt_registration"] = {"refusal": refusal, "digest": str(paths["finalization_digest"])}
            res.details["how_to_answer"] = [
                f"read {paths['finalization_digest']} (only the changed lines of {key})",
                "write answers {units: {<unit_id>: {verdict: PASS|FAIL, observation: ...}}, reviewer, review_method, reviewed_at}",
                f"{VENV} {RT_TOOLS / 'prompt_batch_finalize.py'} receipts --episode {ctx.episode} "
                f"--execution-id {ctx.episode}-PROMPT-BATCH-V1 --digest {paths['finalization_digest']} "
                f"--answers <answers.json> --out-dir {paths['finalization_dir']} "
                f"--batch-path {ctx.p.preprod / f'{ctx.episode}_PROMPT_BATCH_V1.json'} --transaction-path {path}",
                f"{RT_TOOLS / 'paid_stage.sh'} {ctx.episode} --ab-variant {path}",
            ]
            for line in res.details["how_to_answer"]:
                ctx.say(f"   {line}")
            return finish(REVIEW_REQUIRED, [f"AB.prompt_finalization:REVIEW_REQUIRED:{refusal}"])
        planned = max(int(doc.get("estimated_credits") or 0),
                      video_task_credits(str(task.get("model")), float(task.get("duration_seconds") or 0), 1,
                                         task.get("resolution")))
        res.details["planned_credits"] = planned
        submit_env = dict(VIDEO_SUBMIT_ENV)
        if ctx.paid_enabled:
            auth_status, auth_manifest, auth = materialize_paid_authorization(
                ctx, res, sid="S6", target=path, is_plan=False, task_keys=[key],
                report=paths["authorization_report"],
                note="A/B variant: one task, its own report; never the episode's S6 authorised copy")
            res.details["paid_authorization"] = auth
            if auth_status != PASS:
                return finish(BLOCKED, [auth.get("blocker") or "AB_PAID_AUTHORIZATION_REFUSED"])
            paid_argv = [VENV, ENGINE / "tools/submit_giggle_video_manifest_v2.py", "--manifest", auth_manifest,
                         "--out", paths["submit"], "--concurrency", 1, "--project-root", VIDEO_PROJECT_ROOT]
            status, submit = ctx.paid_step(paid_argv, name="ab_submit_giggle_video_manifest_v2", sid="S6",
                                           timeout=video_submit_timeout_s(),
                                           planned_credits=planned, extra_env=submit_env,
                                           note=f"A/B variant {key}: D-11 copy {auth_manifest.name}; clip -> {paths['dir']}")
        else:
            # Rehearsal, the convention for a free run of a D-11 step: the real tool against a scratch
            # --ledger / --out-dir / --report, then the submitter's own --precheck-only on that copy.
            # The scratch directory is removed afterwards: no authorised copy, no ledger row, no
            # reservation survives a run that spent nothing.
            scratch = paths["rehearsal"]
            scratch.mkdir(parents=True, exist_ok=True)
            try:
                rehearsal_argv = None
                if not ctx.authority_blockers and ctx.paid_order:
                    rehearsal_argv = paid_authorization_argv(
                        ctx, sid="S6", target=path, is_plan=False, task_keys=[key],
                        report=scratch / "paid_authorization.json", out_dir=scratch, ledger=scratch / "ledger.json")
                    rehearsal = ctx.run(rehearsal_argv, name="ab_d11_rehearsal")
                    res.steps.append(rehearsal)
                    rehearsed = scratch / f"{path.stem}_PAID_AUTHORIZED{path.suffix}"
                    res.details["d11_rehearsal"] = {
                        "exit_code": rehearsal["exit_code"], "materialised": rehearsed.is_file(),
                        "report": read_json(scratch / "paid_authorization.json", {}) or {}}
                    if rehearsal["exit_code"] != 0 or not rehearsed.is_file():
                        return finish(BLOCKED, ["AB_D11_REHEARSAL_REFUSED:" + (rehearsal.get("stderr_tail") or rehearsal.get("stdout_tail") or "")[-300:]])
                    ctx.say(f"   D-11 rehearsal PASS (scratch, removed afterwards): {rehearsed.name}")
                else:
                    rehearsed = path
                    res.details["d11_rehearsal"] = {"status": "NOT_RUN_AUTHORITY_INVALID",
                                                    "authority_failures": list(ctx.authority_blockers)}
                paid_argv = [VENV, ENGINE / "tools/submit_giggle_video_manifest_v2.py", "--manifest",
                             materialised_path(path), "--out", paths["submit"], "--concurrency", 1,
                             "--project-root", VIDEO_PROJECT_ROOT]
                dry_argv = [VENV, ENGINE / "tools/submit_giggle_video_manifest_v2.py", "--manifest", rehearsed,
                            "--out", scratch / "precheck.json", "--precheck-only", "--project-root", VIDEO_PROJECT_ROOT]
                status, submit = ctx.paid_step(paid_argv, name="ab_submit_giggle_video_manifest_v2", sid="S6",
                                               timeout=video_submit_timeout_s(),
                                               planned_credits=planned, dry_argv=dry_argv, extra_env=submit_env,
                                               note=f"A/B variant {key}; clip -> {paths['dir']}")
                precheck = (submit or {}).get("precheck") or {}
                if precheck:
                    res.details["submitter_precheck"] = {"exit_code": precheck.get("exit_code"),
                                                         "stdout_tail": (precheck.get("stdout_tail") or "")[-400:],
                                                         "stderr_tail": (precheck.get("stderr_tail") or "")[-400:]}
                    if precheck.get("exit_code") != 0:
                        res.steps.append(submit)
                        return finish(BLOCKED, ["AB_SUBMITTER_PRECHECK_FAILED"])
                if rehearsal_argv is not None:
                    ctx.say("   then, on the paid run, D-11 for real:  " + q(paid_authorization_argv(
                        ctx, sid="S6", target=path, is_plan=False, task_keys=[key],
                        report=paths["authorization_report"])))
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        res.steps.append(submit)
        res.planned_credits += planned
        if status == HARD_STOP:
            return finish(HARD_STOP, ["BUDGET_HARD_STOP_AB"])
        if status == DRY:
            ctx.say(f"   then (no POST): {q(poll_argv)}")
            reason = getattr(ctx, "paid_disabled_reason", None)
            return finish(DRY, ["PAID_STEPS_DISABLED:" + (reason or (submit or {}).get("reason_not_run") or "")],
                          code=2 if reason else None)
        res.details["credit_statement"] = archive_credit_statement(ctx, paths["submit"], f"{ctx.run_id}_ab")
        if status != PASS:
            return finish(BLOCKED, ["AB_VIDEO_SUBMIT_FAILED"])
    elif not ctx.paid_enabled:
        ctx.say(f"   {key} is bound to a remote task; poll (needs the key, no POST): {q(poll_argv)}")
        return finish(DRY, ["PAID_STEPS_DISABLED_POLL_NOT_RUN"],
                      code=2 if getattr(ctx, "paid_disabled_reason", None) else None)
    elif not paths["submit"].is_file():
        return finish(BLOCKED, [f"AB_BOUND_BUT_SUBMIT_REPORT_MISSING:{paths['submit']}"])

    completed = ab_poll_until_complete(ctx, res, poll_argv, paths["remote_status"])
    ledger = ctx.run([VENV, BUDGET_LEDGER, "--episode", ctx.episode, "--planned-credits", 0,
                      "--bgm-transactions-dir", selective_bgm_transaction_dir(ctx), "--cap", ctx.cap,
                      "--out", paths["dir"] / f"{key}_LEDGER_AFTER_AB.json"], name="ab_budget_ledger_record")
    res.steps.append(ledger)
    if not completed or not paths["clip"].is_file():
        return finish(BLOCKED, ["AB_VIDEO_NOT_YET_COMPLETED: re-run the same command to poll again (no POST)"])
    res.details["clip"] = str(paths["clip"])
    res.details["clip_sha256"] = sha256_file(paths["clip"])
    return finish(PASS)


def _stage_s6_body(ctx: Ctx, *, ready_units=None, run_qa: bool = True,
                   final_pass: bool = False) -> StageResult:
    p = ctx.p
    # 6.0 action-role evidence for every start frame in scope (fail closed, reviewer-only)
    res = StageResult(PASS)
    are = s6_action_role_evidence(ctx, res, ready_units)
    if any(str(b).startswith("ARE_START_FRAME_MEDIA_NOT_BOUND:") for b in are.get("blockers") or []):
        # the anchor plan predates the predecessor's tail: rebuild (offline, free) so the start-frame
        # contract binds the real tail, then ask again; still unbound -> fail closed, no null-media request
        ctx.say("-- S6.are: start frame not bound yet for " + ",".join(are.get("units_without_media") or [])
                + "; rebuilding the start-frame contracts first")
        pre = s6_compile(ctx, ready_units=ready_units)
        res.steps.extend(pre.steps)
        are = s6_action_role_evidence(ctx, res, ready_units)
        are["rebuilt_before_review"] = pre.status
    res.details = {"action_role_evidence": are}
    if are.get("status") != PASS:
        # request_review sets res.status itself; a non-review refusal (e.g. the start
        # frames do not exist yet) returns only its detail, so propagate it here —
        # otherwise the body reports PASS while its very first sub-step was BLOCKED.
        if not res.status or res.status == PASS:
            res.status = are.get("status") or BLOCKED
            res.blockers.extend(are.get("blockers") or [])
        return res
    # 6.1 re-run preproduction with --keyframe-dir (and, for a rolling wave, the ready subset).
    # CAMERA_GRAMMAR_V1: the recompile keeps each harvested take's start-frame decision (no tail re-attached).
    as_submitted = record_start_frames_as_submitted(ctx)
    rebuilt = s6_compile(ctx, ready_units=ready_units)
    res.steps.extend(rebuilt.steps)
    res.receipts = list(rebuilt.receipts)
    report = read_json(p.preprod_report, {}) or {}
    inner = {row.get("stage"): row.get("status") for row in (report.get("stages") or [])}
    res.details.update({
        "rebuild_with_keyframes": rebuilt.status,
        "compile_cache": rebuilt.details.get("compile_cache"),
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
             # MiniMax-H3 only: final prompts re-rendered from the finalized tasks (needs English contracts)
             and inner.get("4.5_h3_final_prompts_from_finalized_tasks", PASS) == PASS
             and inner.get("5_video_preflight") == PASS)
    res.details["video_preflight_pass"] = ready
    if not ready:
        res.status = BLOCKED
        res.blockers = [f"VIDEO_CHAIN_NOT_READY:{key}={value}" for key, value in inner.items()
                        if key.startswith(("4.3", "4.4", "4.5", "5")) and value != PASS]
        h3_block = next((row.get("blocking_check") for row in (report.get("stages") or [])
                         if row.get("stage") == "4.5_h3_final_prompts_from_finalized_tasks"
                         and row.get("status") != PASS), None)
        if h3_block:
            res.blockers.append(str(h3_block))
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
    if unbound:
        # S6 burn retry (owner 2026-11-19): a prompt changed ONLY by the engine's retry sentence gets an engine
        # receipt bound to the approved base prompt; any other change still goes to the reviewer
        burn_receipts = s6_burn_retry_finalization_receipts(ctx, unbound, fin_report, fin_digest)
        if burn_receipts:
            unbound = [uid for uid in unbound if uid not in burn_receipts]
            res.details["prompt_finalization"]["changed_without_receipt"] = unbound
            res.details["prompt_finalization"]["burn_retry_engine_receipts"] = burn_receipts
    if unbound:
        # final fix round redo (owner 2026-11-20): approved prompt + exactly the round's redo sentence
        fix_receipts = s6_final_fix_finalization_receipts(ctx, unbound, fin_report, fin_digest)
        if fix_receipts:
            unbound = [uid for uid in unbound if uid not in fix_receipts]
            res.details["prompt_finalization"]["changed_without_receipt"] = unbound
            res.details["prompt_finalization"]["final_fix_engine_receipts"] = fix_receipts
    if unbound:
        # Only units that will be (re)submitted need finalization receipts.  Introduced with
        # CAMERA_GRAMMAR_V1 (lab Holmes E06); applied to every episode since 2026-10-29: a legacy
        # episode's final pass recompiles a rerolled unit with its predecessor tail re-attached
        # (no start_frame_as_submitted withholding without the policy) and would otherwise ask a
        # reviewer to approve a prompt that can never be POSTed -- the bound transaction is the
        # authority for the clip on disk, recorded in harvested_bound_takes_exempt for audit.
        unbound, harvested = exempt_harvested_bound_takes(ctx, unbound, fin_report, as_submitted)
        if harvested:
            res.details["prompt_finalization"]["changed_without_receipt"] = unbound
            res.details["prompt_finalization"]["harvested_bound_takes_exempt"] = harvested
            res.details["prompt_finalization"]["exemption_policy"] = (
                "CAMERA_GRAMMAR_V1" if _camera_grammar_on(ctx) else "BOUND_TAKE_AUTHORITY_LEGACY")
            ctx.say(f"   prompt finalization: {len(harvested)} recompiled prompt(s) belong to clips already "
                    f"produced by bound transactions (never re-submitted, no review needed): {sorted(harvested)}")
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

    # 6.2d send-time review binding (PROVIDER_REQUEST_REVIEW_BINDING_V1, enforced from E14).
    # The rebuild above recomputes every video task, so a stamp written outside this stage is
    # already gone by the time the paid submit reads the manifest: E14's first S6 wave was
    # refused twelve times with REVIEWED_REQUEST_NOT_BOUND, before any charge, for exactly that
    # reason.  Stamp here, after the compile and after the finalization receipts are attached;
    # the stamper seals only a task whose prompt bytes a review actually covered and leaves the
    # rest unstamped so the submitter still refuses them.
    stamp = ctx.run([VENV, RT_TOOLS / "stamp_reviewed_video_requests.py",
                     "--episode", ctx.episode, "--manifest", p.video_transaction,
                     "--finalization-digest", fin_digest],
                    name="s6_stamp_reviewed_video_requests")
    res.steps.append(stamp)
    stamped = json.loads(stamp.get("stdout") or "{}") if stamp.get("stdout") else {}
    res.details["reviewed_request_binding"] = {
        "status": stamped.get("status"),
        "stamped": len(stamped.get("stamped") or []),
        "left_unstamped": stamped.get("left_unstamped") or [],
    }
    if stamp["exit_code"] != 0:
        res.status = BLOCKED
        res.blockers.append("VIDEO_REVIEW_BINDING_STAMP_FAILED")
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
        # Stale-binding guard (JA-01 E01 2026-11-19): before anything reads the durable store as "already
        # bound", a completed take of a request that is no longer the unit's is archived, so the unit is
        # planned, budgeted, authorised and reviewed as a fresh attempt.
        stale = s6_retire_stale_bindings(ctx, (read_json(p.video_transaction, {}) or {}).get("tasks") or [])
        if stale.get("archived") or stale.get("in_flight"):
            res.details["stale_bindings"] = stale
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
        # A re-entry whose remaining tasks are all already bound to remote task ids (charged, waiting for
        # download) must only poll: authorising them again priced the whole wave as new spend and the
        # budget guard refused a poll that costs nothing (lab E01 2026-10-22: 360 already charged).
        try:  # a lost create the usage API adopts is bound (poll it), a verified-zero one is re-POSTable
            ctx.reconcile_hopsapi_lost(label="s6_reentry")
        except Exception as exc:  # noqa: BLE001 - never fatal: the budget check still fails closed
            ctx.say(f"   HopsAPI usage reconciliation skipped: {type(exc).__name__}: {str(exc)[:200]}")
        unbound_keys = set(s6_unbound_task_keys(ctx))
        post_keys = [k for k in needs_post if k in unbound_keys]
        if on_disk and post_keys:
            # plan only what will actually be POSTed, not every recompiled-but-on-disk task
            post_rows = [t for t in manifest_now.get("tasks") or [] if str(t.get("task_key")) in set(post_keys)]
            planned = min(planned, video_task_credits(
                episode_video_model(ctx.episode),
                sum(float(t.get("duration_seconds") or 0) for t in post_rows), len(post_rows),
                episode_video_resolution(ctx.episode)))
        provider = video_provider_for(episode_video_model(ctx.episode))
        key_env = video_key_env(episode_video_model(ctx.episode))
        res.details["video_provider"] = {**video_provider_info(), "effective": provider, "key_env": key_env}
        if post_keys and ctx.paid_enabled and not os.environ.get(key_env, "").strip():
            # Refuse before authorisation and reservation: the submitter would exit on the missing key
            # after both and leave a held reservation (same rule as the A/B path).
            res.status = BLOCKED
            res.blockers.append(f"VIDEO_PROVIDER_KEY_MISSING:{provider}:{key_env}")
            return res
        if not post_keys:
            if needs_post and not p.video_submit.is_file():
                # No report to poll from.  When that is because the "bound" take is the one parked for
                # a redo, say so instead of crashing in the poll child and waiting on nothing.
                from tools.submit_giggle_video_manifest_v2 import task_fingerprint as _fingerprint
                identical = s6_redo_identical_to_parked_take(
                    ctx, [t for t in manifest_now.get("tasks") or [] if str(t.get("task_key")) in set(needs_post)],
                    _fingerprint)
                if identical:
                    res.status = BLOCKED
                    res.blockers.append("REDO_REQUEST_IDENTICAL_TO_PARKED_TAKE:" + ",".join(identical))
                    res.details["redo_identical_to_parked_take"] = {
                        "units": identical, "posts": 0,
                        "fix": "the clip was parked for a redo but the request is byte-identical to the parked "
                               "take, and an identical request is never POSTed again (K130).  Change the "
                               "unit's prompt or start frame for the rejection reason through the reviewed "
                               "prompt finalization, then re-enter S6.  This is not a remote wait."}
                    return res
            ctx.say("   every task without a clip is already bound to a remote task: poll only, no authorisation")
            status = PASS
        else:
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
                paid_argv, name="s6_submit_giggle_video_manifest_v2", sid="S6", timeout=video_submit_timeout_s(),
                planned_credits=planned, dry_argv=dry_argv, extra_env=VIDEO_SUBMIT_ENV,
                note=(f"Submitted file is the D-11 materialised copy {auth_manifest.name}.  "
                      + ("HopsAPI POST /v1/router/task/create (OmniVideo, MiniMax-H3; key HOPSAPI_API_KEY), "
                         if provider == "hopsapi" else "POST /api/v1/generation/omni-video, ")
                      + f"concurrency {concurrency} "
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
            if status == PASS:
                res.details["posted_task_keys"] = list(post_keys)  # S6_CHAIN_STEP timing + in-run polling

        poll_argv = video_poll_argv(ctx)
        # E10 (2026-09-29): the submitter writes its batch window statement next to the report under a
        # FIXED name, and this stage archived it only on PASS.  A wave that POSTed and was then cut
        # short before PASS (E10 wave 1: 1980 cr charged, wave stopped at a review blocker) left the
        # statement on disk, the next wave's submit overwrote it, and the ledger lost the whole batch
        # (K054 repeated).  Archive on every outcome that has a statement.
        if status != DRY and post_keys:  # a poll-only re-entry submitted nothing: no new statement
            res.details["credit_statement"] = archive_credit_statement(
                ctx, p.video_submit, f"{ctx.run_id}_wave{len(ready_units or [])}u")
        if status == DRY:
            res.status = DRY
            ctx.say(f"   then (needs {key_env}, no new POST, free):")
            ctx.say(f"     {q(poll_argv)}")
            ctx.planned_commands.append({
                "stage": "S6", "step": "s6_poll_giggle_submit_report", "planned_credits": 0,
                "paid_argv": [str(x) for x in poll_argv], "paid_command": q(poll_argv),
                "note": ("downloads only remote_status==completed, atomic .part->replace, "
                         "skips what already exists; omit --download for a query-only probe")})
        elif status == PASS:
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
        # Plan §6: timing map updated after video harvest completes.
        if final_pass:
            timing = timing_map(ctx, stage="S6", media_dir=ctx.p.video_media)
            res.details["unit_timing_map"] = timing
    return res


# --------------------------------------------------------------------------- #
# S6.q2 — Q2 VIDEO_ASSEMBLY content admission (D-7)
# --------------------------------------------------------------------------- #
def _owner_accepted_clips(ctx: Ctx, rows: dict[str, dict[str, Any]]) -> dict[str, int]:
    """unit -> seq of an active line-owner GATE_FAIL_ACCEPTANCE order for this episode bound (media_sha256_by_item
    or media_sha256) to the unit's CURRENT clip sha.  The owner kept that exact clip, so the engine's auto redo
    must not spend credits replacing it (field device …1324 E01, 2026-11-06).  Any gate: the binding is the clip."""
    authority = getattr(ctx, "authority", None) or {}
    orders_path = authority.get("orders_path")
    issuer = authority.get("line_owner_id") or ""
    if not orders_path or getattr(ctx, "authority_blockers", None) or not issuer:
        return {}
    orders = _rga._orders(orders_path, expected_latest_seq=authority.get("latest_order_seq") or 0,
                          engine_root=ENGINE)
    out: dict[str, int] = {}
    for uid in rows:
        clip_sha = sha256_file(ctx.p.video_media / f"{uid}.mp4")
        if not clip_sha:
            continue
        for row in orders:
            dec = row.get("decision") or {}
            if (str(row.get("issued_by") or "") != issuer or str(row.get("status") or "") != "active"
                    or dec.get("kind") != _rga.KIND or str(dec.get("episode") or "") != ctx.episode
                    or not _rga._receipt_valid(row, expected_issuer=issuer, engine_root=ENGINE)):
                continue
            by_item = dec.get("media_sha256_by_item") if isinstance(dec.get("media_sha256_by_item"), dict) else {}
            if clip_sha in (str(by_item.get(uid) or ""), str(dec.get("media_sha256") or "")):
                out[uid] = max(out.get(uid, 0), int(row.get("seq") or 0))
    return out


def s6_q2_auto_redo(ctx: Ctx, review: dict[str, Any] | None = None) -> dict[str, Any]:
    """CAMERA_GRAMMAR_V1: the engine's own one controlled redo after an objective Q2 FAIL (q2_auto_redo.py;
    CLAUDE_CODE_PRODUCTION §5).  Runs after ``prepare`` and before the video_q2 review: units it selects get
    their clip parked and the S6 wave loop redoes them (own keyframe for face count / speaker framing, the same
    start frame + the measured problem in the prompt for a push-in; single-unit wave).  A letterboxed / non-9:16
    clip (av_evidence_pack.clip_letterbox, 2026-11-19) is a technical failure, redo-eligible once in every render
    style and without CAMERA_GRAMMAR_V1 (same start frame).  With the submitted video_q2 ``review`` (device 1101 E24,
    2026-11-23) the VLM plan answers -- reversed role, person outside the cast, wrong location, modern object in a
    pre-modern world -- are objective failures too (q2_auto_redo.with_vlm_failures).  Never blocks."""
    import q2_auto_redo as _redo
    # InsightFace failures need CAMERA_GRAMMAR_V1 and live action; the technical letterbox check (2026-11-19) does not
    technical_only = not _camera_grammar_on(ctx) or ctx_render_style(ctx) == "anime"
    grouping = read_json(ctx.p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json", {}) or {}
    order = [str(u.get("unit_id") or "") for u in grouping.get("units") or [] if u.get("unit_id")]
    rows = {uid: read_json(ctx.p.q2_dir / uid / "prepare.json", {}) or {} for uid in order
            if (ctx.p.video_media / f"{uid}.mp4").is_file()}
    if review:
        rows = _redo.with_vlm_failures(rows, review)
    if not any(_redo.objective_failures(row, technical_only=technical_only) for row in rows.values()):
        if not _camera_grammar_on(ctx):
            return {"status": "NOT_APPLICABLE"}
        if ctx_render_style(ctx) == "anime":  # no InsightFace failure for anime (render_style.py)
            return {"status": "NOT_APPLICABLE", "reason": "RENDER_STYLE_ANIME"}
        return {"status": "NONE"}
    state_path = _wave_state_path(ctx)
    state = read_json(state_path, {}) or {"schema": "nalu.s6_wave_state.v1", "waves": []}
    attempted = dict(state.get(_redo.STATE_KEY) or {})
    # One redo per unit, whoever did it: a clip Codex already replaced under a controlled redo (parked in any
    # video/_superseded_*/) is not redone again by the engine (field device …1324 E03: VU-015 generated 3 times,
    # 30 redos = 230 credits).
    for uid in order:
        if uid not in attempted and any(ctx.p.video_media.glob(f"_superseded_*/{uid}.mp4")):
            attempted[uid] = {"source": "SUPERSEDED_CLIP_ON_DISK"}
    seconds = {str(t.get("unit_id") or t.get("task_key")): float(t.get("duration_seconds") or 0)
               for t in (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []}
    model = episode_video_model(ctx.episode)
    resolution = episode_video_resolution(ctx.episode)

    def unit_cost(uid: str) -> int:
        # video at the planning price (HopsAPI per-second estimate on the router) + an own keyframe only when the
        # failure needs a new start frame (a push-in redo keeps its start frame; owner 2026-10-29)
        keyframe = (image_batch_credits(ctx, 1) if _redo.needs_own_keyframe(
            _redo.objective_failures(rows.get(uid) or {}, technical_only=technical_only)) else 0)
        return video_task_credits(model, seconds.get(uid, 6.0), 1, resolution) + keyframe

    headroom = None
    if not ctx.dry:
        verdict = ctx.budget_check(0, label="s6_q2_auto_redo_headroom").get("budget_verdict") or {}
        headroom = verdict.get("headroom_credits")
    decision = _redo.plan(rows, attempted, headroom=None if headroom is None else int(headroom),
                          unit_cost=unit_cost, unit_order=order, owner_accepted=_owner_accepted_clips(ctx, rows),
                          technical_only=technical_only)
    if ctx.dry:
        decision["status"] = DRY
        decision["note"] = "dry run: would redo the failing units when the paid run has headroom"
        return decision
    park = ctx.p.video_media / f"_superseded_{ctx.run_id}_q2_auto_redo"
    for row in decision["selected"]:
        clip = ctx.p.video_media / f"{row['unit_id']}.mp4"
        if not clip.is_file():
            continue
        park.mkdir(parents=True, exist_ok=True)
        os.replace(clip, park / clip.name)
        state.setdefault(_redo.STATE_KEY, {})[row["unit_id"]] = {
            **row, "parked_clip": str(park / clip.name), "run_id": ctx.run_id, "headroom_at_decision": headroom,
            "recorded_at": now(), "recorded_by": TOOL_ID,
            "next": "S6 wave loop: redo_switch_start_frames -> own keyframe (S5, Q1) -> single-unit wave -> Q2"}
    if decision["selected"]:
        write_json(state_path, state)
    decision["status"] = "PARKED_FOR_REDO" if decision["selected"] else "NONE_SELECTED"
    for row in decision["skipped"]:
        ctx.say(f"   S6.q2 auto-redo skipped {row['unit_id']} ({row['reason']}): review + §5 default accept")
    return decision


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

    # CAMERA_GRAMMAR_V1: objective FAILs are redone by the engine once, before anyone reviews those clips
    auto_redo = s6_q2_auto_redo(ctx)
    detail["auto_redo"] = auto_redo
    if auto_redo.get("status") == "PARKED_FOR_REDO":
        units = [row["unit_id"] for row in auto_redo.get("selected") or []]
        ctx.say("-- S6.q2: engine redo (objective Q2 FAIL, once per unit): " + ", ".join(units))
        detail["status"] = BLOCKED
        detail["blockers"] = ["Q2_AUTO_REDO_PARKED:" + ",".join(units)]
        detail["q2_auto_redo_parked"] = units
        return detail

    review_path, review = latest_submitted_review(ctx, "video_q2")
    if review_path is None:
        detail.update(request_review(ctx, res, "video_q2", sub_stage="S6.q2",
                                     note="Q2 content admission: the reviewer looks at the "
                                          "original-resolution clip and its extracted frames"))
        return detail

    # device 1101 E24: the review's plan answers (role / cast / location / period) are objective failures too --
    # the same one engine redo per unit, within the episode headroom, before the admission is built
    vlm_redo = s6_q2_auto_redo(ctx, review=review)
    detail["vlm_auto_redo"] = vlm_redo
    if vlm_redo.get("status") == "PARKED_FOR_REDO":
        units = [row["unit_id"] for row in vlm_redo.get("selected") or []]
        ctx.say("-- S6.q2: engine redo (VLM plan failure, once per unit): " + ", ".join(units))
        detail["status"] = BLOCKED
        detail["blockers"] = ["Q2_AUTO_REDO_PARKED:" + ",".join(units)]
        detail["q2_auto_redo_parked"] = units
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
    if index.get("results"):
        detail["knowledge_events"] = kb_events(
            "record_review_round", episode=ctx.episode, stage="S6", kind="Q2",
            round_key=detail["review_file_sha256"] or str(verdict.get("out") or ""),
            rows=kb_review_rows(index, "ADMITTED_FOR_ASSEMBLY"),
            evidence={"gate": "shot_media_admission_gate.VIDEO_ASSEMBLY", "q2_status": verdict.get("status")})
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

    run_argv = [POST_GEN_QA, "run", "--episode", ctx.episode, "--review", review_path,
                "--language", ctx_language(ctx)]
    # the runner reads the private inbox from the environment; authority configured only in qingshan.json
    # never reached it, so every post-gen acceptance silently read the (refused) in-engine default inbox
    authority = getattr(ctx, "authority", None) or {}
    auth_env = {env: str(authority.get(key)) for key, env in AUTH_ENV.items()
                if key in ("orders_path", "latest_order_seq", "line_owner_id")
                and authority.get(key) and not os.environ.get(env)}
    run_step = (qa_run(ctx, run_argv, name="s6_qa_post_generation_qa_runner", extra_env=auth_env) if auth_env
                else qa_run(ctx, run_argv, name="s6_qa_post_generation_qa_runner"))
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
    summary = read_json(Path(str(verdict.get("out") or "")), {}) if verdict.get("out") else {}
    if isinstance(summary, dict) and summary.get("postgen_orders_needed") and detail["status"] != PASS:
        # quality never blocks (§5): name the exact order per still-rejected unit, why no recorded order
        # matched, and why no redo runs -- instead of a bare PARTIAL_N_OF_M the agent can only re-run into
        needed = summary["postgen_orders_needed"]
        detail["postgen_orders_needed"] = needed
        detail["record_hint"] = summary.get("postgen_record_hint")
        detail["postgen_acceptance_lookup"] = {
            "inbox": (summary.get("roger_gate_acceptance") or {}).get("inbox"),
            "orders_read": (summary.get("roger_gate_acceptance") or {}).get("orders_read")}
        detail["blockers"] += [f"{row['unit_id']}:{row.get('reason')}:REROLL_{row.get('reroll', '').split(':')[0]}"
                               for row in needed][:8]
        detail["next"] = ("record ONE default-acceptance order with details.post_generation_qa.record_hint "
                          "(gate POST-GENERATION-QA-ADMISSION, every --detector and --media listed), then rerun S6; "
                          "a unit whose reroll is AVAILABLE_ONCE may instead get one controlled redo")
    if isinstance(summary, dict) and summary.get("units"):
        detail["knowledge_events"] = kb_events(
            "record_review_round", episode=ctx.episode, stage="S6", kind="POSTGEN",
            round_key=sha256_file(Path(str(verdict["out"]))) or detail["review_file_sha256"],
            rows=kb_postgen_rows(summary),
            evidence={"gate": "post_generation_qa_runner", "qa_status": verdict.get("status")})
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
    if outro_seconds < 2.5:
        raise ValueError("REQUIRED_BRAND_OUTRO_MISSING: story footage is not a brand outro")
    project = read_json(p.agentcut_project, {}) or {}
    clips = []
    for track in ((project.get("timeline") or {}).get("videoTracks") or []):
        clips.extend(track.get("clips") or [])
    clips.sort(key=lambda c: float(c.get("start") or 0))
    probe = subprocess.run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(picture)], capture_output=True, text=True, check=False)
    release_runtime = round(float(probe.stdout.strip() or 0), 6)
    # Never steal story time to manufacture an outro window.
    content_runtime = round(max(release_runtime - outro_seconds, 0.0), 6)
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
        "outro_note": f"NALU MOTION studio end card appended ({outro_seconds:.3f} s)",
        "segments": segments, "recorded_at": now(),
    })
    return {"path": str(release_timeline), "segments": len(segments),
            "content_runtime_seconds": content_runtime, "release_runtime_seconds": release_runtime}


def s7_opening_title(ctx: Ctx, res: StageResult, picture: Path) -> Path:
    """Overlay the opening title on the subtitled picture; returns the picture to continue with.

    Never blocks: on SKIPPED/FAILED the input picture is returned unchanged and the reason is
    recorded in res.details["opening_title"]."""
    import nalu_opening_title as _title

    out = ctx.p.assembly / f"{ctx.episode}_picture_native_subbed_titled.mp4"
    info = _title.apply_opening_title(runtime_root=Path(f"{_np.RUNTIME_ROOT}"), episode=ctx.episode,
                                      language=ctx_language(ctx), source=picture, out=out)
    res.details["opening_title"] = info
    if info.get("status") == "APPLIED":
        return out
    ctx.say(f"   -- opening title {info.get('status')}: {info.get('reason')}")
    return picture


def s7_episode_endcard(ctx: Ctx, res: StageResult) -> Path | None:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-23, lab E03 reused E02's card): render this episode's
    own 3 s end card from the brief (series title, display number, episode title, language) with
    skills/nalu-claude-code/scripts/make_endcard.py.  None (-> the global brand card) outside the
    policy, without a brief title, or on any failure (recorded in res.details["episode_endcard"])."""
    import camera_grammar_policy as _cgp
    import nalu_opening_title as _title
    if not _cgp.active(read_json(ctx.p.contract, {}) or {}, episode=ctx.episode):
        return None
    out = ctx.p.assembly / f"{ctx.episode}_endcard_3s_9x16.mp4"
    try:
        brief = _title.load_brief(Path(f"{_np.RUNTIME_ROOT}"), ctx.episode)
        language = _lang.language_code(ctx_language(ctx)) or "zh"
        series, episode_line = _title.title_lines(brief, ctx.episode, language)
        if not series:
            res.details["episode_endcard"] = {"status": "SKIPPED", "reason": "NO_BRIEF_TITLE"}
            return None
        scripts = str(ENGINE / "skills/nalu-claude-code/scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import make_endcard as _endcard
        font = _endcard.resolve_font(language)
        out.parent.mkdir(parents=True, exist_ok=True)
        _endcard.make(series, episode_line, language, font, out.with_suffix(".png"), out,
                      ffmpeg=_media.require_ffmpeg())
    except (Exception, SystemExit) as exc:  # noqa: BLE001 -- fall back to the global card
        res.details["episode_endcard"] = {"status": "FAILED", "reason": f"{type(exc).__name__}:{exc}"}
        return None
    if not out.is_file():
        res.details["episode_endcard"] = {"status": "FAILED", "reason": "NO_OUTPUT"}
        return None
    res.details["episode_endcard"] = {"status": "APPLIED", "asset": str(out), "title": series,
                                      "subtitle": episode_line, "language": language}
    return out


def s7_tail_ad(ctx: Ctx, res: StageResult, *, endcard_seconds: float) -> dict[str, Any]:
    """Optional per-episode tail ad (codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md).

    MUST NEVER raise past this function and MUST NEVER touch res.status/
    res.blockers — a failed or skipped ad only means no AD_TAIL_* evidence
    gets produced; the episode's own final_mp4 is completely unaffected.
    Runs strictly after p.final_candidate is confirmed on disk (called from
    stage_s7 right after that gate) and never writes to that path; the AD
    variant is a candidate too and is promoted with the final (item 0).
    ``endcard_seconds`` is stage_s7's own already-computed outro_seconds
    (0.0 or 3.0) — never recomputed or hardcoded here.
    """
    try:
        return _s7_tail_ad_body(ctx, res, endcard_seconds=endcard_seconds)
    except Exception as exc:  # noqa: BLE001
        return {"status": "SKIPPED", "reason": f"EXCEPTION:{type(exc).__name__}:{exc}"}


def resolve_ad_inbox_asset(sku: str) -> Path | None:
    """INBOX:<sku> clip: runtime ads/inbox/<sku>.mp4 first, then the repo's assets/ads/<sku>.mp4."""
    for folder in (ADS_INBOX, ADS_REPO_ASSETS):
        candidate = folder / f"{sku}.mp4"
        if candidate.is_file():
            return candidate
    return None


def _s7_tail_ad_body(ctx: Ctx, res: StageResult, *, endcard_seconds: float) -> dict[str, Any]:
    p = ctx.p
    # No recorded decision (episode passed S1 before the 2026-10-22 default) or one that only holds a
    # policy default -> the current policy default for this episode's dialogue language.
    decision = _tail_ad_optin.default_decision_at_s7(
        ctx.state.get("tail_ad_opt_in"), policy_path=ADS_POLICY, language=ctx_language(ctx),
        default_policy_path=ADS_DEFAULT_POLICY)
    decision = _tail_ad_optin.recheck_before_s7(
        ctx.episode, answer_dir=ADS_PROMPTS, ledger_path=ADS_TRANSACTIONS / "opt_in_ledger.json",
        current_decision=decision, say=ctx.say)
    if decision != ctx.state.get("tail_ad_opt_in"):
        ctx.state["tail_ad_opt_in"] = decision  # state only — never the manifest, see
        ctx.save_state()                        # nalu_tail_ad_opt_in._write_manifest_ad_slot's docstring

    answer = str(decision.get("answer") or "NONE")
    if answer == "NONE" or not AD_SLOT_CONTRACT.is_file():
        return {"status": "SKIPPED", "reason": decision.get("reason", "NO_AD_SLOT")}

    sku = answer.split(":", 1)[1] if ":" in answer else ""
    if not sku:
        return {"status": "SKIPPED", "reason": f"MALFORMED_ANSWER:{answer}"}

    packaged = ADS_PACKAGED / f"{sku}_tail.mp4"
    packaged_qa = ADS_PACKAGED / f"{sku}_tail.qa.json"

    if answer.startswith("INBOX:"):
        raw_input = resolve_ad_inbox_asset(sku)
        if raw_input is None:
            return {"status": "SKIPPED", "reason": f"AD_ASSET_MISSING:{sku}", "sku": sku,
                    "searched": [str(ADS_INBOX / f"{sku}.mp4"), str(ADS_REPO_ASSETS / f"{sku}.mp4")]}
        provenance = "INBOX"
        # optional sidecar: a Mode-A drop may already carry its own burned-in CTA
        # (e.g. the AdForge demo); declare it here so AD_TAIL_OCR_CLEAN allows it
        # instead of misreading known, approved branding as anomalous text.
        meta_path = raw_input.with_name(f"{sku}.meta.json")
        cta_text = str((read_json(meta_path, {}) or {}).get("cta_text") or "") if meta_path.is_file() else None
    elif answer.startswith("BRIEF:"):
        brief_path = ADS_BRIEFS / f"{sku}.json"
        if not brief_path.is_file():
            return {"status": "SKIPPED", "reason": "BRIEF_SKU_MISSING", "sku": sku}
        run_id = f"{ctx.episode}_{sku}"
        adapter_report = ADS_TRANSACTIONS / ctx.p.scope["scope_id"] / ctx.episode / f"{sku}_adforge_report.json"
        adapter_video = ADS_TRANSACTIONS / ctx.p.scope["scope_id"] / ctx.episode / f"{sku}_adforge_output.mp4"
        adapter_argv = [VENV, ADFORGE_ADAPTER_TOOL, "generate", "--brief", brief_path, "--sku", sku,
                        "--episode", ctx.episode, "--run-id", run_id, "--slot-contract", AD_SLOT_CONTRACT,
                        "--out-video", adapter_video, "--out-report", adapter_report]
        if ctx.paid_enabled:
            adapter_argv.append("--paid")
        else:
            ctx.planned_commands.append({
                "stage": "S7", "step": "s7_adforge_adapter", "planned_credits": 0,
                "paid_argv": [str(item) for item in adapter_argv], "paid_command": q(adapter_argv),
                "note": "Mode-B tail ad: AdForge narration+video generation, gated on --paid "
                        "same as every other paid step; dry-plans (writes project.json only) "
                        "when not enabled.",
            })
        adapter_step = ctx.run(adapter_argv, name="s7_adforge_adapter", paid=ctx.paid_enabled)
        res.steps.append(adapter_step)
        if not ctx.paid_enabled:
            return {"status": "DRY_PLANNED", "sku": sku, "reason": "PAID_STEPS_DISABLED"}
        if adapter_step["exit_code"] == 2:
            return {"status": "SKIPPED", "reason": "ADAPTER_REQUIRED", "sku": sku}
        if adapter_step["exit_code"] != 0 or not adapter_video.is_file():
            return {"status": "SKIPPED", "reason": "ADFORGE_GENERATION_FAILED", "sku": sku}
        raw_input = adapter_video
        provenance = f"ADFORGE:{sku}/{run_id}"
        cta_text = str((read_json(brief_path, {}) or {}).get("cta") or "") or None
    else:
        return {"status": "SKIPPED", "reason": f"UNKNOWN_ANSWER_PREFIX:{answer}"}

    package_argv = [VENV, AD_TAIL_PACKAGE_TOOL, "package", "--input", raw_input, "--sku", sku,
                    "--provenance", provenance, "--slot-contract", AD_SLOT_CONTRACT,
                    "--out", packaged, "--out-qa", packaged_qa, "--language", ctx_language(ctx)]
    if cta_text:
        package_argv += ["--cta-text", cta_text]
    package_step = ctx.run(package_argv, name="s7_ad_tail_package")
    res.steps.append(package_step)
    if package_step["exit_code"] != 0 or not packaged_qa.is_file():
        return {"status": "SKIPPED", "reason": "PACKAGE_QA_FAIL", "sku": sku, "qa_report": str(packaged_qa)}
    packaged_qa_payload = read_json(packaged_qa, {}) or {}
    if packaged_qa_payload.get("status") != "PASS":
        return {"status": "SKIPPED", "reason": "PACKAGE_QA_FAIL", "sku": sku, "qa_report": str(packaged_qa)}

    # Re-entry on a NEW candidate (S7 re-run after a repair): ad_tail_insert refuses to overwrite its
    # --out/--out-qa, so an AD candidate built from different content bytes is parked (sha in the name,
    # never deleted) and rebuilt; one built from the current candidate is reused as is.
    content_sha = sha256_file(p.final_candidate)
    prior_qa = read_json(p.ad_tail_qa_report, {}) or {}
    if p.ad_tail_candidate.is_file() or p.ad_tail_qa_report.is_file():
        if (p.ad_tail_candidate.is_file() and prior_qa.get("status") == "PASS"
                and prior_qa.get("content_source_sha256") == content_sha
                and prior_qa.get("output_sha256") == sha256_file(p.ad_tail_candidate)):
            ctx.state["tail_ad"] = {
                "sku": sku, "provenance": provenance, "ad_tail_video": str(p.ad_tail_candidate),
                "ad_tail_video_sha256": prior_qa.get("output_sha256"), "qa_report": str(p.ad_tail_qa_report),
                "produced_at": prior_qa.get("recorded_at"), "candidate": True, "reused": True,
            }
            ctx.save_state()
            res.receipts.append(str(p.ad_tail_qa_report))
            return {"status": "PASS", "sku": sku, "provenance": provenance,
                    "ad_tail_video": str(p.ad_tail_candidate), "candidate": True, "reused": True}
        stale_tag = (str(prior_qa.get("content_source_sha256") or sha256_file(p.ad_tail_candidate) or "nosha"))[:12]
        for stale in (p.ad_tail_candidate, p.ad_tail_qa_report):
            if stale.is_file():
                stale.replace(stale.with_name(f"{stale.stem}__stale_{stale_tag}{stale.suffix}"))
    insert_argv = [VENV, AD_TAIL_INSERT_TOOL, "insert", "--content", p.final_candidate,
                   "--endcard-seconds", endcard_seconds,
                   "--packaged-ad", packaged, "--packaged-ad-qa", packaged_qa,
                   "--expected-packaged-sha256", packaged_qa_payload.get("packaged_sha256") or "",
                   "--sku", sku, "--provenance", provenance, "--episode", ctx.episode,
                   "--slot-contract", AD_SLOT_CONTRACT, "--out", p.ad_tail_candidate,
                   "--out-qa", p.ad_tail_qa_report]
    insert_step = ctx.run(insert_argv, name="s7_ad_tail_insert")
    res.steps.append(insert_step)
    if insert_step["exit_code"] != 0 or not p.ad_tail_candidate.is_file():
        return {"status": "SKIPPED", "reason": "INSERT_FAIL", "sku": sku}

    ctx.state["tail_ad"] = {
        "sku": sku, "provenance": provenance, "ad_tail_video": str(p.ad_tail_candidate),
        "ad_tail_video_sha256": sha256_file(p.ad_tail_candidate), "qa_report": str(p.ad_tail_qa_report),
        "produced_at": now(), "candidate": True,
    }
    ctx.save_state()
    res.receipts.append(str(p.ad_tail_qa_report))
    return {"status": "PASS", "sku": sku, "provenance": provenance, "ad_tail_video": str(p.ad_tail_candidate),
            "candidate": True}


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
             "--producer-process-id", producer_process_id,
             *(["--render-style", "anime"] if ctx_render_style(ctx) == "anime" else [])],
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
        if detail.get("report"):  # advisory DIRECTOR_SCORE_V1 outputs, only when the reviewer wrote them
            for suffix in ("DIRECTOR_EVALUATION.json", "DIRECTOR_EVALUATION.md", "NEXT_EPISODE_PLAN.json",
                           "CRAFT_STANDARD.json",  # + the advisory craft-standard block (never a gate)
                           "QA_DEFECT_CHECKLIST.json"):  # + the must-check defect list (never a gate)
                extra = Path(str(detail["report"])).parent / f"{ctx.episode}_{suffix}"
                if extra.is_file():
                    res.receipts.append(str(extra))
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


def s7_cut_crossfade_seconds(default: float) -> float:
    """The equal-power cut crossfade (s7_audio_smoothing.CUT_CROSSFADE_S), or ``NALU_S7_CUT_CROSSFADE_SECONDS``
    (0.04..0.30 s) -- the final fix round's AUDIO_SMOOTHING (owner 2026-11-20)."""
    raw = str(os.environ.get("NALU_S7_CUT_CROSSFADE_SECONDS") or "").strip()
    try:
        return round(min(0.30, max(0.04, float(raw))), 3) if raw else default
    except ValueError:
        return default


def s7_asr_model() -> str:
    """faster-whisper model for S7's own transcriptions (pitch-unify line windows, subtitle read-back).
    Default ``small``: on the 8 GB production machine large-v3 over a 226 s mix ran 2 h under memory thrash
    (F2 2026-10-30); override with NALU_S7_ASR_MODEL when a bigger machine is available."""
    return str(os.environ.get("NALU_S7_ASR_MODEL") or "small")


def _camera_workers(ctx: Ctx) -> int:
    import os as _os
    return max(1, min(8, (_os.cpu_count() or 2) - 1, max(int(getattr(ctx, "max_parallel", 1) or 1), 4)))


def s7_camera_stabilize(ctx: Ctx, res: StageResult) -> Path | None:
    """Measure camera motion on every admitted unit clip and stabilise the dialogue units that are not locked off.

    Roger 2026-10-30 (E12 成片审看 item 2): dialogue units default to a static camera.  Clips already paid for get a
    free lock-off / smoothing pass (clip_lockoff_stabilize.py: LOCK_OFF when the crop stays <= 20 %, else SMOOTH;
    audio copied bit-exact) instead of a reroll (K130).  Outputs go to video/_stabilized/, the summary to
    assembly/<EP>_CLIP_STABILIZE.json; the builder uses them through --stabilized-clips.  Never blocks: a tool
    failure is recorded and the original clips are used.  Returns the summary path when any unit was changed."""
    p = ctx.p
    metrics_before = p.assembly / f"{ctx.episode}_CAMERA_MOTION_METRICS_BEFORE.json"
    summary = p.assembly / f"{ctx.episode}_CLIP_STABILIZE.json"
    out_dir = p.video_media / "_stabilized"
    workers = _camera_workers(ctx)
    release_timeline = p.assembly / f"{ctx.episode}_release_timeline.json"
    grouping = p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    metrics_argv: list[Any] = [VENV, RT_TOOLS / "camera_motion_metrics.py", "--clips-dir", p.video_media,
                               "--grouping", grouping, "--contract", p.contract, "--out", metrics_before,
                               "--md", metrics_before.with_suffix(".md"), "--workers", workers, "--label", "before_stabilize"]
    if release_timeline.is_file():
        metrics_argv += ["--timeline", release_timeline]
    step = ctx.run(metrics_argv, name="s7_camera_motion_metrics_before")
    res.steps.append(step)
    before = read_json(metrics_before, {}) or {}
    detail: dict[str, Any] = {"metrics_before": str(metrics_before), "summary_before": before.get("summary"),
                              "workers": workers, "status": "MEASURED" if step["exit_code"] == 0 else "METRICS_FAILED"}
    res.details["camera_motion"] = detail
    res.details["commands"]["camera_motion_metrics_before"] = q(metrics_argv)
    if step["exit_code"] != 0 or not before.get("rows"):
        return None
    # stabilise: dialogue units that are not locked off (action units keep their authored moves).  Both the metrics
    # and the stabiliser track the SET, people masked out (2026-11-21, KO E05: the whole-frame tracker locked onto a
    # swaying actor and the stabilised clip moved the background with him)
    targets = [str(r["unit_id"]) for r in before["rows"]
               if "error" not in r and r.get("dialogue_unit") and not r.get("locked_off")]
    # ... plus units whose kept S6 take still wobbles (h3_camera_wobble): MILD ones only, crop <= 5 %
    wobble_targets = [uid for uid in s7_wobble_stabilize_units(ctx) if uid not in targets]
    detail["stabilize_targets"] = targets
    if wobble_targets:
        detail["wobble_stabilize_targets"] = wobble_targets
    if not targets and not wobble_targets:
        detail["status"] = "NOTHING_TO_STABILIZE"
        return None
    probe = next((r for r in before["rows"] if r.get("width") and r.get("height")), {})
    out_size = f"{probe.get('width')}x{probe.get('height')}" if probe else None
    import h3_camera_wobble as _wobm  # noqa: PLC0415 - engine tools/
    payload: dict[str, Any] = {}
    for label, units, crop, path in (("clip_lockoff_stabilize", targets, 0.20, summary),
                                     ("clip_wobble_stabilize", wobble_targets, _wobm.STABILIZE_MAX_CROP,
                                      summary.with_name(f"{ctx.episode}_CLIP_STABILIZE_WOBBLE.json"))):
        if not units:
            continue
        stab_argv: list[Any] = [VENV, RT_TOOLS / "clip_lockoff_stabilize.py", "--clips-dir", p.video_media,
                                "--out-dir", out_dir, "--max-crop", crop, "--summary", path, "--workers", workers]
        if out_size:
            stab_argv += ["--out-size", out_size]
        for uid in units:
            stab_argv += ["--only", uid]
        if label == "clip_wobble_stabilize":
            stab_argv.append("--wobble")
        res.details["commands"][label] = q(stab_argv)
        stab_step = ctx.run(stab_argv, name=f"s7_{label}")
        res.steps.append(stab_step)
        part = read_json(path, {}) or {}
        if not payload:
            payload = part
        elif part:
            payload["results"] = list(payload.get("results") or []) + list(part.get("results") or [])
            payload["failed"] = list(payload.get("failed") or []) + list(part.get("failed") or [])
            for key in ("modes",):
                payload[key] = {m: int((payload.get(key) or {}).get(m) or 0) + int((part.get(key) or {}).get(m) or 0)
                                for m in ("LOCK_OFF", "SMOOTH", "NONE")}
            for key in ("processed", "locked_off_before", "locked_off_after", "unstable_before", "unstable_after"):
                payload[key] = int(payload.get(key) or 0) + int(part.get(key) or 0)
    if payload and wobble_targets:
        write_json(summary, payload)  # one summary for the builder (--stabilized-clips)
    detail.update({"summary": str(summary), "out_dir": str(out_dir), "modes": payload.get("modes"),
                   "locked_off_before": payload.get("locked_off_before"), "locked_off_after": payload.get("locked_off_after"),
                   "unstable_before": payload.get("unstable_before"), "unstable_after": payload.get("unstable_after"),
                   "failed": payload.get("failed")})
    changed = [r for r in (payload.get("results") or []) if r.get("mode") in ("LOCK_OFF", "SMOOTH")]
    if not changed:
        detail["status"] = "NO_CLIP_CHANGED"
        return None
    detail["status"] = "STABILIZED"
    detail["changed_units"] = [Path(str(r.get("source"))).stem for r in changed]
    res.receipts.append(str(summary))
    return summary


def s7_wobble_stabilize_units(ctx: Ctx) -> list[str]:
    """Units whose kept S6 take still moves the set with the actor (``s6_burn_retry`` camera_wobble_unresolved) and
    whose wobble is MILD (h3_camera_wobble: excursion fits a <= 5 % lock-off crop), for the free S7 lock-off pass.
    A unit redone since (clip sha != kept take) is left out."""
    out = []
    try:
        state = read_json(_wave_state_path(ctx), {}) or {}
        for uid, rec in (state.get("s6_burn_retry") or {}).items():
            if not isinstance(rec, dict) or not rec.get("camera_wobble_unresolved"):
                continue
            kept = rec.get("kept_take_wobble") if isinstance(rec.get("kept_take_wobble"), dict) else {}
            if kept.get("severity") != "MILD":
                continue
            clip = ctx.p.video_media / f"{uid}.mp4"
            if rec.get("kept_take_sha256") and clip.is_file() and sha256_file(clip) != rec["kept_take_sha256"]:
                continue
            out.append(str(uid))
    except Exception:  # noqa: BLE001 - advisory
        return []
    return sorted(out)


def s7_text_removal_path(ctx: Any) -> Path:
    return ctx.p.assembly / f"{ctx.episode}_TEXT_REMOVAL.json"


def s7_text_removal_plan(ctx: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(targets, skipped) of the local burned-text removal (tools/burned_text_removal.plan_targets) from the S6 wave
    state, the final-fix redo state and the final-fix round record.  Read-only."""
    import burned_text_removal as _btr
    import final_fix_round as _ffr
    import h3_burn_retry as _br
    state = read_json(_wave_state_path(ctx), {}) or {}
    shas: dict[str, str | None] = {}

    def clip_sha(uid: str) -> str | None:
        if uid not in shas:
            shas[uid] = sha256_file(ctx.p.video_media / f"{uid}.mp4")
        return shas[uid]
    # the strict burned-line verdicts of the last S7 pass (build_burnin_subtitles ``burned_line_checks``); a unit's
    # verdicts count only when that report is newer than the unit's clip (not a verdict of a superseded take)
    burnin = ctx.p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json"
    verdicts: dict[str, list[str]] = {}
    if burnin.is_file():
        mtime = burnin.stat().st_mtime
        for uid, rows in _btr.burnin_verdicts(read_json(burnin, {}) or {}).items():
            clip = ctx.p.video_media / f"{uid}.mp4"
            if clip.is_file() and clip.stat().st_mtime <= mtime:
                verdicts[uid] = rows
    return _btr.plan_targets(s6_records=state.get(_br.STATE_KEY) or {},
                             redo_records=(read_json(final_fix_redo_path(ctx), {}) or {}).get("units") or {},
                             round_status=(read_json(final_fix_record_path(ctx), {}) or {}).get("status"),
                             rounds_enabled=_ffr.rounds() > 0, pending=final_fix_redo_pending(ctx), clip_sha=clip_sha,
                             line_verdicts=verdicts)


def s7_text_removal_picture_source(ctx: Any, uid: str, reports: dict[str, Path | None]) -> Path:
    """The file the AgentCut builder will use for ``uid``'s picture, mirroring its precedence: unit re-cut > lock-off
    stabilisation > push-in compensation > the admitted clip, then the audio-levelled remux of that picture.  The
    builder re-checks path + sha, so a mismatch here only means the cleaned clip is not used (never a wrong one)."""
    source = ctx.p.video_media / f"{uid}.mp4"
    src_sha = sha256_file(source)

    def rows(key: str, module: str) -> dict[str, Any]:
        path = reports.get(key)
        if not path or not Path(path).is_file():
            return {}
        try:
            mod = __import__(module)
            return mod.applied_sources(read_json(Path(path), {}) or {}) or {}
        except Exception:  # noqa: BLE001 - unreadable report: the builder ignores it too
            return {}

    def matches(row: Any, path: Path, sha: str | None) -> bool:
        return isinstance(row, dict) and bool(row.get("output")) \
            and str(Path(str(row.get("source"))).resolve()) == str(path.resolve()) and row.get("source_sha256") == sha
    recut = rows("unit_recut", "unit_recut").get(uid)
    stab = rows("stabilized", "clip_lockoff_stabilize").get(uid)
    push = rows("push_in", "push_in_compensation").get(uid)
    picture, derived = source, False
    if matches(recut, source, src_sha):
        picture, derived = Path(str(recut["output"])), True
    elif matches(stab, source, src_sha):
        picture, derived = Path(str(stab["output"])), True
    elif matches(push, source, src_sha):
        picture = Path(str(push["output"]))
    if not derived:
        level = rows("levelling", "s7_audio_smoothing").get(uid)
        if matches(level, source, src_sha) \
                and str(Path(str(level.get("picture_source"))).resolve()) == str(picture.resolve()) \
                and level.get("picture_sha256") == sha256_file(picture):
            picture = Path(str(level["output"]))
    return picture if picture.is_absolute() else ENGINE / picture


def s7_burned_text_removal(ctx: Ctx, res: StageResult, reports: dict[str, Path | None]) -> Path | None:
    """Local burned-text removal, the LAST resort (line owner 2026-11-23, option 2-E; tools/burned_text_removal.py).

    Units whose kept take still carries model-burned text after every paid option (S6 retries UNRESOLVED and the
    final-fix round settled, or the final-fix burn redo UNRESOLVED) and whose strict burned-line verdict is not
    ACCEPT_CORRECT (absent = REJECT): the picture file the builder would use is cleaned on the CPU (LaMa keyframes +
    optical-flow fill), one child process per unit, sequentially.  The original take is never touched; a cleaned copy
    goes to ``video/_text_removed/<unit>.mp4`` and ``<EP>_TEXT_REMOVAL.json`` (the builder's ``--text-removal``).
    Bounded: ``NALU_TEXT_REMOVAL_MAX_SECONDS`` (240) per unit, ``NALU_TEXT_REMOVAL_EPISODE_MAX_SECONDS`` (1200) for
    the episode across S7 passes; a result is cached per (input sha, algorithm) so an S7 re-run spends nothing.
    Off with ``NALU_TEXT_REMOVAL=0``.  Never blocks: every failure keeps the original picture.  Returns the report
    path when at least one unit is cleaned."""
    import burned_text_removal as _btr
    detail: dict[str, Any] = {}
    res.details["text_removal"] = detail
    if not _btr.enabled():
        detail["status"] = "OPT_OUT"
        return None
    if getattr(ctx, "dry", False):
        detail["status"] = DRY
        return None
    try:
        targets, skipped = s7_text_removal_plan(ctx)
    except Exception as exc:  # noqa: BLE001 - advisory
        detail.update(status="PLAN_UNREADABLE", error=f"{type(exc).__name__}: {exc}"[:200])
        return None
    detail["skipped"] = skipped
    if not targets:
        detail["status"] = "NO_TARGET"
        return None
    path = s7_text_removal_path(ctx)
    report = read_json(path, {}) or {}
    report = {"schema": _btr.REPORT_SCHEMA, "episode": ctx.episode, "units": dict(report.get("units") or {}),
              "spent_seconds": float(report.get("spent_seconds") or 0.0)}
    unit_cap, episode_cap = _btr.max_seconds(), _btr.episode_max_seconds()
    out_dir = ctx.p.video_media / "_text_removed"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: dict[str, Any] = {}
    for target in targets:
        uid = target["unit_id"]
        source = s7_text_removal_picture_source(ctx, uid, reports)
        source_sha = sha256_file(source)
        base = {**target, "source": str(source), "source_sha256": source_sha, "algo_version": _btr.ALGO_VERSION}
        cached = _btr.cached_row(report, uid, source_sha or "") if source_sha else None
        if cached is not None:
            row = {**cached, "cached": True}
        elif not source_sha:
            row = {**base, "status": _btr.NOT_APPLIED, "reason": "PICTURE_SOURCE_MISSING"}
        elif episode_cap - report["spent_seconds"] < 30.0:
            row = {**base, "status": _btr.NOT_APPLIED, "reason": "EPISODE_BUDGET_SPENT",
                   "episode_spent_seconds": round(report["spent_seconds"], 1)}
        else:
            budget = min(unit_cap, episode_cap - report["spent_seconds"])
            out = out_dir / f"{uid}.mp4"
            unit_report = out_dir / f"{uid}.text_removal.json"
            unit_report.unlink(missing_ok=True)
            step = ctx.run([VENV, ENGINE / "tools/burned_text_removal.py", source, "--out", out,
                            "--report", unit_report, "--max-seconds", f"{budget:.0f}", "--threads", _btr.threads()],
                           name=f"s7_text_removal_{uid}", timeout=int(budget) + 180)
            res.steps.append(step)
            report["spent_seconds"] += float(step.get("duration_s") or 0.0)
            got = read_json(unit_report, {}) or {}
            if not got.get("status"):
                got = {"status": _btr.NOT_APPLIED, "reason": "SUBPROCESS_FAILED", "exit_code": step.get("exit_code")}
            row = {**got, **base, "status": got.get("status"), "reason": got.get("reason"),
                   "wall_seconds": step.get("duration_s"), "at": now()}
            if row["status"] != _btr.APPLIED:
                out.unlink(missing_ok=True)
        report["units"][uid] = row
        rows[uid] = {k: row.get(k) for k in ("status", "reason", "stage", "strict_verdict", "seconds", "peak_rss_mb",
                                             "frames_processed", "burned_frames", "output", "cached")
                     if row.get(k) is not None}
        ctx.say(f"S7_TEXT_REMOVAL unit={uid} {row.get('status')} reason={row.get('reason')} "
                f"seconds={row.get('seconds')} peak_rss_mb={row.get('peak_rss_mb')} "
                f"frames={row.get('frames_processed')}" + (" (cached)" if row.get("cached") else ""))
    report["spent_seconds"] = round(report["spent_seconds"], 1)
    report["recorded_at"] = now()
    write_json(path, report)
    applied = sorted(u for u, r in rows.items() if r.get("status") == _btr.APPLIED)
    detail.update(status="APPLIED" if applied else "NOT_APPLIED", report=str(path), units=rows, applied=applied,
                  episode_spent_seconds=report["spent_seconds"], episode_cap_seconds=episode_cap)
    try:  # the episode record keeps the outcome next to the stage details (S8 / fleet status read it)
        ctx.state["text_removal"] = {"report": str(path), "applied": applied, "units": rows,
                                     "episode_spent_seconds": report["spent_seconds"], "at": now()}
    except Exception:  # noqa: BLE001
        pass
    if applied:
        res.receipts.append(str(path))
    return path if applied else None


def s7_text_removal_drop_bands(avoid_bands: Path | None, removal_report: Path | None) -> Path | None:
    """A unit whose burned line was removed locally no longer needs our caption moved above it (or suppressed):
    drop it from ``<EP>_S6_RESIDUAL_BURN_BANDS.json``.  Returns the (rewritten) path, or None when nothing is left."""
    if avoid_bands is None or removal_report is None:
        return avoid_bands
    try:
        import burned_text_removal as _btr
        cleaned = set(_btr.applied_sources(read_json(removal_report, {}) or {}))
        payload = read_json(avoid_bands, {}) or {}
        units = {u: v for u, v in (payload.get("units") or {}).items() if u not in cleaned}
        if units == (payload.get("units") or {}):
            return avoid_bands
        if not units:
            return None
        write_json(avoid_bands, {**payload, "units": units, "text_removed_units": sorted(cleaned)})
    except Exception:  # noqa: BLE001 - advisory placement: the bands as they were
        return avoid_bands
    return avoid_bands


def s7_camera_motion_gate(ctx: Ctx, res: StageResult) -> dict[str, Any] | None:
    """FINAL-CUT-CAMERA-MOTION: measure the clips that actually made the candidate and apply Roger's targets.

    Measured on the AgentCut project's clip sources (originals, stabilised or re-cut derived files), so the
    numbers describe the cut the viewer sees.  PASS iff locked_off_share >= 0.70 and no unit has >= 1 camera
    reversal per second.  A FAIL is honest and blocks; it may be carried only by a line-owner order bound to
    the candidate's sha (same mechanism as FINAL-CUT-AUDIENCE-DETECTORS).  Returns a step dict (or None when
    the project cannot be read)."""
    p = ctx.p
    project = read_json(p.agentcut_project, {}) or {}
    clips: list[tuple[str, str]] = []
    for track in (project.get("timeline") or {}).get("videoTracks") or []:
        for clip in track.get("clips") or []:
            uid = str((clip.get("metadata") or {}).get("source_id") or "")
            if uid and clip.get("source"):
                clips.append((uid, str(clip["source"])))
    if not clips:
        return None
    metrics_after = p.assembly / f"{ctx.episode}_CAMERA_MOTION_METRICS.json"
    gate_json = p.assembly / f"{ctx.episode}_FINAL_CUT_CAMERA_MOTION_GATE.json"
    grouping = p.preprod / f"{ctx.episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    # one --clip per project clip: derived files keep the unit stem, so rows stay keyed by unit id
    argv: list[Any] = [VENV, RT_TOOLS / "camera_motion_metrics.py", "--grouping", grouping, "--contract", p.contract,
                       "--out", metrics_after, "--md", metrics_after.with_suffix(".md"),
                       "--workers", _camera_workers(ctx), "--label", "final_candidate_clips"]
    recut_report = p.assembly / f"{ctx.episode}_UNIT_RECUT.json"
    if recut_report.is_file():
        # authored picture cuts inside re-cut units are shot changes, not camera reversals
        argv += ["--internal-cuts", recut_report]
    for _uid, source in clips:
        argv += ["--clip", source]
    step = ctx.run(argv, name="s7_camera_motion_metrics")
    res.details["commands"]["camera_motion_metrics"] = q(argv)
    payload = read_json(metrics_after, {}) or {}
    summary = payload.get("summary") or {}
    failing: list[str] = []
    share = summary.get("locked_off_share")
    if share is None or float(share) < 0.70:
        failing.append(f"CAMERA_LOCKED_OFF_SHARE_BELOW_70PCT:{share}")
    if int(summary.get("unstable_reversal_ge_1_per_s") or 0) > 0:
        failing.append(f"CAMERA_UNSTABLE_UNITS:{summary.get('unstable_reversal_ge_1_per_s')}")
    if step["exit_code"] != 0 or not summary:
        failing.append("CAMERA_METRICS_UNAVAILABLE")
    status = "PASS" if not failing else "FAIL"
    final_sha = sha256_file(p.final_candidate) if p.final_candidate.is_file() else None
    gate = {"schema": "nalu.final_cut_camera_motion_gate.v1", "gate_id": "FINAL-CUT-CAMERA-MOTION", "episode": ctx.episode,
            "status": status, "failures": failing, "media_sha256": final_sha, "metrics": str(metrics_after),
            "measured": {k: summary.get(k) for k in ("clips", "measured", "locked_off", "locked_off_share",
                                                      "unstable_reversal_ge_1_per_s", "classes", "dialogue_units",
                                                      "dialogue_units_locked_off")},
            "thresholds": summary.get("targets") or {"locked_off_share_min": 0.70, "unstable_max": 0},
            "authority": "Roger 2026-10-30 E12 成片审看 item 2 (对白单元默认固定机位；锁定 ≥70 %；每秒换向 ≥1 的镜头 = 0)",
            "recorded_at": now()}
    write_json(gate_json, gate)
    res.receipts.extend([str(metrics_after), str(gate_json)])
    res.details["final_cut_camera_motion"] = {"gate": str(gate_json), "status": status, "failures": failing,
                                              "measured": gate["measured"]}
    step = dict(step, name="s7_camera_motion_gate", exit_code=0 if status == "PASS" else 1, failing=failing,
                gate=str(gate_json))
    if status == "PASS" or not final_sha:
        return step
    orders = _gate_acceptance_orders(ctx)
    order = _rga.find_acceptance(orders, episode=ctx.episode, gate_id="FINAL-CUT-CAMERA-MOTION", failing=failing,
                                 media_sha256=final_sha, media_item_id="camera_motion",
                                 expected_issuer=ctx.authority.get("line_owner_id") or "", engine_root=ENGINE)
    if order is None:
        return step
    record = _rga.acceptance_record(order, episode=ctx.episode, gate_id="FINAL-CUT-CAMERA-MOTION", failing=failing,
                                    media_sha256=final_sha, media_item_id="camera_motion", gate_result_path=str(gate_json))
    acceptance_path = p.assembly / "final_qa" / f"{ctx.episode}_CAMERA_MOTION_GATE_ACCEPTANCE.json"
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    step["accepted_by_line_owner_order"] = order.get("seq")
    res.details["final_cut_camera_motion"]["line_owner_acceptance"] = {**record, "record_path": str(acceptance_path)}
    res.receipts.append(str(acceptance_path))
    ctx.say(f"   !! FINAL-CUT-CAMERA-MOTION stays FAIL ({', '.join(failing)}); continuing on line-owner order "
            f"seq={order.get('seq')} {order.get('order')!s:.40} -> {acceptance_path.name}")
    return step


BURNED_TEXT_COVER_GATE_ID = "H3-BURNED-TEXT-COVER"
BURNED_TEXT_COVER_DETECTOR = "H3_BURNED_TEXT_STILL_VISIBLE"


def s7_burned_text_cover_acceptance(ctx: Ctx, res: StageResult, subbed: Path, cover_check: Path,
                                    verify_step: dict[str, Any]) -> dict[str, Any] | None:
    """The line-owner order that carries a FAILed H3 burned-text cover verify, or None (S7 stays blocked).

    The verify is a quality verdict on the subtitled picture: text the OCR still reads in or near the burn
    band.  It had no acceptance route, so a residual hit stopped the episode at every re-run whatever the
    line owner ruled (fleet 2026-11-14, a device at E13 S7: 「安安安」 read inside the bar at 1.0-2.0 s; the
    device recorded an order on the final-cut audience gate, which S7 only consults after this step).  Same
    mechanism as FINAL-CUT-CAMERA-MOTION: the report keeps its FAIL and its hits, and the stage continues
    only on a source-receipted order for gate H3-BURNED-TEXT-COVER, detector H3_BURNED_TEXT_STILL_VISIBLE,
    bound to the sha256 of this exact subtitled picture (media item H3_BURNED_TEXT_STILL_VISIBLE).
    A verify that did not produce a FAIL report (crash, missing file) is not a quality verdict and is never carried.
    """
    report = read_json(cover_check, {}) or {}
    if str(report.get("status") or "") != "FAIL" or not Path(subbed).is_file():
        return None
    failing = [BURNED_TEXT_COVER_DETECTOR]
    media_sha = sha256_file(subbed)
    orders = _gate_acceptance_orders(ctx)
    order = _rga.find_acceptance(orders, episode=ctx.episode, gate_id=BURNED_TEXT_COVER_GATE_ID, failing=failing,
                                 media_sha256=media_sha, media_item_id=BURNED_TEXT_COVER_DETECTOR,
                                 expected_issuer=ctx.authority.get("line_owner_id") or "", engine_root=ENGINE)
    if order is None:
        res.details["burned_text_cover_acceptance_hint"] = {
            "gate_id": BURNED_TEXT_COVER_GATE_ID, "detector": BURNED_TEXT_COVER_DETECTOR,
            "media_item_id": BURNED_TEXT_COVER_DETECTOR, "media": str(subbed), "media_sha256": media_sha}
        return None
    record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=BURNED_TEXT_COVER_GATE_ID, failing=failing,
                                    media_sha256=media_sha, media_item_id=BURNED_TEXT_COVER_DETECTOR,
                                    gate_result_path=str(cover_check))
    acceptance_path = ctx.p.assembly / "final_qa" / f"{ctx.episode}_H3_BURNED_TEXT_COVER_ACCEPTANCE.json"
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    verify_step["accepted_by_line_owner_order"] = order.get("seq")
    res.details["burned_text_cover_acceptance"] = {**record, "record_path": str(acceptance_path)}
    res.receipts.append(str(acceptance_path))
    ctx.say(f"   !! H3 burned-text cover verify stays FAIL; continuing on line-owner order "
            f"seq={order.get('seq')} {order.get('order')!s:.40} -> {acceptance_path.name}")
    return record


def s7_unit_recut(ctx: Ctx, res: StageResult) -> tuple[Path | None, list[str]]:
    """Render the authored unit re-cut plan (assembly/<EP>_UNIT_RECUT_PLAN.json) into derived clips.

    Roger 2026-10-30 (E12 成片审看 item 3): faster conflict block, visible 起手—动作—反应, hallucinated
    inserts removed — edits the AgentCut builder cannot express per unit (dropped middles, reaction
    cutaways, picture swaps that keep the voice).  Free; sources are the admitted unit clips (or the
    lock-off-stabilised derived clips in video/_stabilized when present, so the re-cut reads stabilised
    frames).  Returns (report path, blockers); no plan file -> (None, []) and S7 runs as before."""
    p = ctx.p
    plan = p.assembly / f"{ctx.episode}_UNIT_RECUT_PLAN.json"
    if not plan.is_file():
        return None, []
    report = p.assembly / f"{ctx.episode}_UNIT_RECUT.json"
    out_dir = p.video_media / "_recut"
    overlay = p.video_media / "_stabilized"
    authored = plan
    plan, invariants = s7_recut_plan_invariants(ctx, res, plan)
    argv: list[Any] = [VENV, RT_TOOLS / "unit_recut.py", "--plan", plan, "--source-dir", p.video_media,
                       "--out-dir", out_dir, "--report", report]
    if overlay.is_dir():
        argv += ["--overlay-dir", overlay]
    step = ctx.run(argv, name="s7_unit_recut")
    res.steps.append(step)
    payload = read_json(report, {}) or {}
    res.details["unit_recut"] = {"plan": str(plan), "plan_sha256": sha256_file(plan), "report": str(report),
                                 "authored_plan": str(authored), "edit_invariants": invariants,
                                 "status": payload.get("status"), "applied": payload.get("applied") or [],
                                 "problems": payload.get("problems") or [], "out_dir": str(out_dir),
                                 "overlay_dir": str(overlay) if overlay.is_dir() else None}
    res.details["commands"]["unit_recut"] = q(argv)
    if step["exit_code"] != 0 or payload.get("status") != "PASS":
        return None, ["UNIT_RECUT_FAILED:" + ";".join(str(x) for x in (payload.get("problems") or [])[:5])]
    res.receipts.append(str(report))
    return report, []


def s7_recut_plan_invariants(ctx: Ctx, res: StageResult, plan: Path) -> tuple[Path, dict[str, Any]]:
    """S7 edit invariants on the unit re-cut plan (owner 2026-11-21, device 1101 E21; tools/s7_edit_invariants):
    the authored / final-fix plan's visible cuts are moved out of speech, fragments under the minimum shot and
    speaker-who-does-not-speak shots are merged into a neighbour's picture (the sound never moves).  Writes
    ``<EP>_UNIT_RECUT_PLAN.edit_invariants.json`` beside the authored plan (which is never touched) and returns it
    with a summary; an unchanged plan, or any error, returns the authored plan itself.  Free; never blocks."""
    p = ctx.p
    summary: dict[str, Any] = {"status": "UNCHANGED"}
    try:
        import s7_edit_invariants as _inv
        payload = read_json(plan, {}) or {}
        units = payload.get("units") or {}
        if not isinstance(units, dict) or not units:
            return plan, {"status": "EMPTY_PLAN"}
        if (res.details.get("dialogue_tail_trim") or {}).get("report"):
            asr = read_json(p.assembly / f"{ctx.episode}_unit_asr_untrimmed.json", {}) or {}
        else:
            try:
                asr = transcribe_units(ctx, p.video_media, ctx.episode, words=True)
            except Exception:  # noqa: BLE001 - no ASR: the minimum-shot merge still runs
                asr = read_json(p.assembly / f"{ctx.episode}_unit_asr.json", {}) or {}
        used = sorted({str(seg[k][0]) for row in units.values() if isinstance(row, dict)
                       for seg in row.get("segments") or [] for k in ("video", "audio")
                       if isinstance(seg, dict) and isinstance(seg.get(k), list) and seg[k]})
        overlay = p.video_media / "_stabilized"
        clip_seconds = {}
        for uid in used:
            clip = overlay / f"{uid}.mp4" if (overlay / f"{uid}.mp4").is_file() else p.video_media / f"{uid}.mp4"
            if clip.is_file():
                clip_seconds[uid] = _probe_seconds(clip)
        clip_seconds = {k: v for k, v in clip_seconds.items() if v}
        words = {uid: _inv.speech_words(asr.get(uid) or []) for uid in used}
        speaking = s7_speaking_units(ctx)
        out_units, rows = {}, []
        for uid, row in units.items():
            if not isinstance(row, dict) or not row.get("segments"):
                out_units[uid] = row
                continue
            got = _inv.sanitize_recut(str(uid), list(row["segments"]), words_by_unit=words,
                                      clip_seconds=clip_seconds, speaking_units=speaking)
            out_units[uid] = {**row, "segments": got["segments"]} if got["changed"] else row
            if got["actions"] or got["problems"]:
                rows.append({"unit_id": uid, "actions": got["actions"], "problems": got["problems"]})
        summary = {"status": "APPLIED" if any(r["actions"] for r in rows) else "UNCHANGED", "units": rows,
                   "min_shot_seconds": _inv.min_shot_seconds(), "asr_units": sorted(u for u in used if asr.get(u))}
        if summary["status"] != "APPLIED":
            return plan, summary
        out = p.assembly / f"{ctx.episode}_UNIT_RECUT_PLAN.edit_invariants.json"
        write_json(out, {**payload, "units": out_units, "edit_invariants": {
            "schema": _inv.SCHEMA, "authored_plan": str(plan), "authored_plan_sha256": sha256_file(plan),
            "units": rows}})
        for r in rows:
            for a in r["actions"]:
                ctx.say(f"S7_EDIT_INVARIANT unit={r['unit_id']} action={a.get('action')}")
        return out, summary
    except Exception as exc:  # noqa: BLE001 - an editing polish, never a blocker
        return plan, {"status": f"SKIPPED_ERROR:{type(exc).__name__}:{str(exc)[:160]}"}


def _park_superseded(*paths: Path) -> list[str]:
    """Move existing files aside as <stem>__superseded_<sha12><suffix> (evidence is never deleted)."""
    parked: list[str] = []
    for path in paths:
        path = Path(str(path))
        if path.is_file():
            target = path.with_name(f"{path.stem}__superseded_{(sha256_file(path) or 'nosha')[:12]}{path.suffix}")
            if not target.exists():
                path.replace(target)
            else:
                path.unlink()      # identical bytes already parked under this sha
            parked.append(str(target))
    return parked


def _report_sha(report: dict[str, Any], role: str) -> str | None:
    """A stage report's input/output sha under any of the shapes the audio tools write."""
    for key in (f"{role}_sha256", f"{role}_sha"):
        if isinstance(report.get(key), str):
            return report[key]
    nested = report.get(role)
    if isinstance(nested, dict):
        for key in ("sha256", "sha"):
            if isinstance(nested.get(key), str):
                return nested[key]
    return None


def _chain_stage_reusable(report_path: Path, output: Path, input_sha: str | None,
                          in_key: str = "input", out_key: str = "output") -> bool:
    report = read_json(report_path, {}) or {}
    return bool(input_sha and output.is_file() and _report_sha(report, in_key) == input_sha
                and _report_sha(report, out_key) == sha256_file(output))


def s7_voice_pitch_unify(ctx: Ctx, res: StageResult, steps: list[dict[str, Any]], source: Path) -> tuple[Path | None, list[str]]:
    """WORLD per-line voice pitch unify on the mixed-but-unlevelled picture, BEFORE release levelling.

    Roger 2026-10-30 E12 成片审看 1c.  Runs before the leveller (F4: resynthesis moved I −14.0 → −14.5 LUFS and
    TP −1.2 → −1.0; downstream the bed tool then had to give loudness away to hold true peak), so the leveller's
    oversampled limiter and line levelling see the corrected voices and the rebuilt line windows.  Picture
    bit-exact.  Reused when the report binds the same input/output shas; stale outputs parked by sha.
    Returns (pitch output or None when the stage does not apply, blockers)."""
    p = ctx.p
    pitch_tool = RT_TOOLS / "final_cut_voice_pitch_unify.py"
    # owner 2026-11-04 (lab 化神 E03): WORLD pitch shifts up to 6 st crackled audibly; off by default,
    # NALU_S7_PITCH_UNIFY=1 turns it back on (NALU_S7_SKIP_PITCH_UNIFY still skips)
    if not (pitch_tool.is_file() and Path(str(ctx.p.scope.get("voice_cast") or "")).is_file()) \
            or str(os.environ.get("NALU_S7_SKIP_PITCH_UNIFY") or "").strip() \
            or str(os.environ.get("NALU_S7_PITCH_UNIFY") or "").strip() not in ("1", "on", "true"):
        return None, []
    pitch_out = p.assembly / f"{ctx.episode}_picture_pitch_unified.mp4"
    pitch_report = p.assembly / f"{ctx.episode}_VOICE_PITCH_UNIFY.json"
    pitch_windows = p.assembly / f"{ctx.episode}_FINAL_CUT_ASR_WINDOWS_final.json"
    pitch_asr = p.assembly / f"{ctx.episode}_PREMIX_ASR_{s7_asr_model()}.json"
    source_sha = sha256_file(source)
    skip_cfg = read_json(p.assembly / f"{ctx.episode}_VOICE_PITCH_UNIFY_SKIP.json", {}) or {}
    skip_units = [str(u) for u in (skip_cfg.get("skip_units") or [])]
    if _chain_stage_reusable(pitch_report, pitch_out, source_sha):
        steps.append({"name": "s7_voice_pitch_unify", "exit_code": 0, "reused": True})
    else:
        _park_superseded(pitch_out, pitch_report, pitch_windows)
        argv: list[Any] = [VENV, pitch_tool, "--episode", ctx.episode, "--input", source, "--output", pitch_out,
                           "--report", pitch_report, "--windows-out", pitch_windows,
                           "--release-timeline", p.assembly / f"{ctx.episode}_release_timeline.json",
                           "--grouping-plan", p.grouping_plan, "--contract", p.contract,
                           "--voice-cast", ctx.p.scope["voice_cast"], "--asr-out", pitch_asr,
                           "--asr-model", s7_asr_model(), "--f0-estimator", "dio",
                           "--work", p.assembly / "_pitch_unify_work"]
        if skip_units:
            # operator-authored skip list (F4 2026-10-30): voices H3 produced an octave off the band — a <= 6 st
            # shift cannot repair them; they are redo candidates for the line owner
            argv += ["--skip-units", ",".join(skip_units)]
        res.details["commands"]["voice_pitch_unify"] = q(argv)
        steps.append(ctx.run(argv, name="s7_voice_pitch_unify"))
        if steps[-1]["exit_code"] != 0 or not pitch_out.is_file():
            return None, ["VOICE_PITCH_UNIFY_FAILED"]
    rep = read_json(pitch_report, {}) or {}
    res.details["voice_pitch_unify"] = {
        "input": str(source), "input_sha256": source_sha, "output": str(pitch_out), "output_sha256": sha256_file(pitch_out),
        "report": str(pitch_report), "windows": str(pitch_windows) if pitch_windows.is_file() else None,
        "skip_units": skip_units, "summary": {k: v for k, v in rep.items() if not isinstance(v, (list, dict))}}
    res.receipts.append(str(pitch_report))
    return pitch_out, []


def s7_candidate_source_bindings(ctx: Any) -> dict[str, Any]:
    """The inputs that decide what the S7 cut contains: admitted unit clips, Q2 index, contract, grouping,
    editorial and the authored S7 plans.  Equal bindings = the same cut, even when a re-render is not
    byte-identical."""
    p = ctx.p
    files = {"q2_index": p.q2_index, "contract": p.contract, "grouping_plan": p.grouping_plan,
             "editorial": p.editorial}
    for suffix in ("UNIT_RECUT_PLAN.json", "VOICE_PITCH_UNIFY_SKIP.json", "BGM_PLAN.json", "BGM_SELECTION.json"):
        files[suffix] = p.assembly / f"{ctx.episode}_{suffix}"
    out: dict[str, Any] = {key: sha256_file(Path(str(path))) if Path(str(path)).is_file() else None
                           for key, path in files.items()}
    settings = p.assembly / f"{ctx.episode}_FINAL_FIX_S7_SETTINGS.json"
    if settings.is_file():  # only when the final fix round wrote it: earlier manifests keep their exact bindings
        out["FINAL_FIX_S7_SETTINGS.json"] = sha256_file(settings)
    out["unit_clips"] = {mp4.name: sha256_file(mp4)
                         for mp4 in sorted(Path(str(p.video_media)).glob(f"{ctx.episode}-VU-*.mp4"))}
    out["music_mode"] = str(os.environ.get("NALU_S7_BED_MUSIC_MODE") or "wall_to_wall")
    return out


def _order_bound_candidate_seq(ctx: Any, candidate_sha: str) -> int | None:
    """seq of the newest active line-owner GATE_FAIL_ACCEPTANCE order of this episode bound (media_sha256 or any
    media_sha256_by_item value) to exactly this candidate; None without a readable order inbox.  This only keeps
    the cut on disk: each gate still validates issuer, receipt and detectors itself before it continues."""
    authority = getattr(ctx, "authority", None) or {}
    orders_path = authority.get("orders_path")
    if not orders_path or getattr(ctx, "authority_blockers", None) or not candidate_sha:
        return None
    orders = _rga._orders(orders_path, expected_latest_seq=authority.get("latest_order_seq") or 0, engine_root=ENGINE)
    best = None
    for row in orders:
        dec = row.get("decision") or {}
        if (str(row.get("status") or "") != "active" or dec.get("kind") != _rga.KIND
                or str(dec.get("episode") or "") != ctx.episode):
            continue
        by_item = dec.get("media_sha256_by_item") if isinstance(dec.get("media_sha256_by_item"), dict) else {}
        if candidate_sha != str(dec.get("media_sha256") or "") and candidate_sha not in {str(v) for v in by_item.values()}:
            continue
        seq = int(row.get("seq") or 0)
        best = seq if best is None or seq > best else best
    return best


def _review_bound_candidate_to_retain(ctx: Any, bindings: dict[str, Any], new_sha: str | None) -> dict[str, Any] | None:
    """The existing candidate, when an S7 re-entry must keep it instead of the fresh render.

    Only when (a) the current candidate differs from the fresh chain output, (b) the independent final-audience
    request names exactly the current candidate (a review is pending or submitted for it) OR an active line-owner
    gate-acceptance order of this episode is bound to its sha256, and (c) the previous chain manifest recorded
    that candidate with the same source bindings as now.  Anything else (changed clips, order-driven re-cut,
    legacy manifest) re-renders as before.  The fresh output stays on disk as evidence."""
    p = ctx.p
    if not (new_sha and p.final_candidate.is_file()):
        return None
    current_sha = sha256_file(p.final_candidate)
    if current_sha == new_sha:
        return None
    request = read_json(REVIEWS_ROOT / ctx.episode / "final_audience_request.json", {}) or {}
    review_bound = ((request.get("media") or {}).get("sha256")) == current_sha
    # field device …0736 E08 (2026-11-13): the S7 gates that FAIL before the review request exists (loudness,
    # camera motion, audience detectors) continue only on an order bound to the candidate's exact sha256.  The
    # next entry re-rendered a non byte-identical cut, so the order just recorded never matched and S7 looped.
    order_seq = None if review_bound else _order_bound_candidate_seq(ctx, current_sha)
    if not review_bound and order_seq is None:
        return None
    manifest = read_json(p.assembly / f"{ctx.episode}_FINAL_CANDIDATE_CHAIN.json", {}) or {}
    if manifest.get("final_candidate_sha256") != current_sha or not manifest.get("source_bindings") \
            or manifest.get("source_bindings") != bindings:
        return None
    if review_bound:
        return {"final_candidate_sha256": current_sha, "rerender_sha256": new_sha,
                "review_request_id": request.get("request_id"),
                "reason": "S7_REENTRY_SAME_SOURCES_REVIEW_BOUND_CANDIDATE"}
    return {"final_candidate_sha256": current_sha, "rerender_sha256": new_sha,
            "acceptance_order_seq": order_seq,
            "reason": "S7_REENTRY_SAME_SOURCES_ORDER_BOUND_CANDIDATE"}


def s7_post_level_audio_chain(ctx: Ctx, res: StageResult, steps: list[dict[str, Any]],
                              line_windows: Path) -> list[str]:
    """levelled release -> ambient bed + under-score -> final candidate (voice pitch unify ran BEFORE levelling).

    Roger 2026-10-30 E12 成片审看 1b (whole-film ambient bed + music, no silence < -50 dBFS, no cut in dead
    silence) and 1c (co-present voices >= 40 Hz apart).  Each stage reads the previous stage's file and is
    reused when its report binds the same input and output shas; stale outputs are parked by sha.  The
    last stage's file becomes <EP>_final_candidate_9x16.mp4 (byte copy, sha verified); nothing here
    touches deliverables/.  Returns blockers (empty on success)."""
    p = ctx.p
    chain: list[dict[str, Any]] = []
    current = p.final_levelled
    stage_in_sha = sha256_file(current)

    pitch = res.details.get("voice_pitch_unify") or {}
    if pitch.get("output"):
        chain.append({"stage": "voice_pitch_unify", "position": "BEFORE_RELEASE_LEVELLING", **pitch})
        if pitch.get("windows") and Path(str(pitch["windows"])).is_file():
            line_windows = Path(str(pitch["windows"]))

    # stage: ambient bed + under-score (F3 tool)
    bed_tool = RT_TOOLS / "final_cut_audio_bed.py"
    bed_out = p.assembly / f"{ctx.episode}_final_candidate_9x16_bed.mp4"
    bed_report = p.assembly / f"{ctx.episode}_AUDIO_BED.json"
    bed_windows = p.assembly / f"{ctx.episode}_FINAL_CUT_ASR_WINDOWS_unitclipped.json"
    music_mode = str(os.environ.get("NALU_S7_BED_MUSIC_MODE") or "wall_to_wall")
    if bed_tool.is_file():
        if _chain_stage_reusable(bed_report, bed_out, stage_in_sha) \
                and (read_json(bed_report, {}) or {}).get("music_mode", music_mode) == music_mode:
            steps.append({"name": "s7_final_cut_audio_bed", "exit_code": 0, "reused": True})
        else:
            _park_superseded(bed_out, bed_report, bed_windows)
            argv = [VENV, bed_tool, "--input", current, "--timeline", p.assembly / f"{ctx.episode}_release_timeline.json",
                    "--grouping", p.grouping_plan, "--contract", p.contract,
                    "--out", bed_out, "--report", bed_report, "--music-mode", music_mode]
            for flag, path in (("--bgm-plan", p.assembly / f"{ctx.episode}_BGM_PLAN.json"),
                               ("--bgm-selection", p.assembly / f"{ctx.episode}_BGM_SELECTION.json"),
                               ("--line-windows", line_windows)):
                if Path(str(path)).is_file():
                    argv += [flag, path]
            if line_windows and Path(str(line_windows)).is_file():
                argv += ["--windows-out", bed_windows]
            res.details["commands"]["final_cut_audio_bed"] = q(argv)
            steps.append(ctx.run(argv, name="s7_final_cut_audio_bed"))
            if steps[-1]["exit_code"] != 0 or not bed_out.is_file():
                return ["FINAL_CUT_AUDIO_BED_FAILED"]
        rep = read_json(bed_report, {}) or {}
        chain.append({"stage": "audio_bed", "input": str(current), "output": str(bed_out), "report": str(bed_report),
                      "music_mode": music_mode,
                      "summary": {k: rep.get(k) for k in ("status", "before", "after") if k in rep}})
        current = bed_out

    # the candidate = last stage output (byte copy; the stage files stay as evidence)
    final_sha = sha256_file(current)
    bindings = s7_candidate_source_bindings(ctx)
    retained = _review_bound_candidate_to_retain(ctx, bindings, final_sha)
    if retained is not None:
        # field device …1284 E06 (2026-11-12): S7 re-entry re-rendered a non byte-identical cut (12090d <-> 84afdc)
        # and replaced the candidate the independent reviewer had already been asked to watch, so its submitted
        # verdict went stale before S7 could read it, every time.  Same admitted sources -> keep the reviewed cut.
        final_sha = retained["final_candidate_sha256"]
        res.details["reviewed_candidate_retained"] = retained
        ctx.say(f"   == S7 re-entry: keeping review-bound candidate {final_sha[:12]} "
                f"(re-render {retained['rerender_sha256'][:12]} is evidence only, sources unchanged)")
    elif not (p.final_candidate.is_file() and sha256_file(p.final_candidate) == final_sha):
        _park_superseded(p.final_candidate)
        import shutil
        tmp = p.final_candidate.with_name(p.final_candidate.name + ".staging")
        shutil.copy2(str(current), str(tmp))
        if sha256_file(tmp) != final_sha:
            tmp.unlink(missing_ok=True)
            return ["FINAL_CANDIDATE_STAGING_SHA_MISMATCH"]
        tmp.replace(p.final_candidate)
    manifest = {"schema": "nalu.final_candidate_chain.v1", "episode": ctx.episode, "recorded_at": now(),
                "levelled": str(p.final_levelled), "levelled_sha256": sha256_file(p.final_levelled),
                "chain": chain, "final_candidate": str(p.final_candidate), "final_candidate_sha256": final_sha,
                "line_windows_for_detectors": str(line_windows) if line_windows else None,
                "source_bindings": bindings,
                **({"reviewed_candidate_retained": retained} if retained else {}),
                "authority": "Roger 2026-10-30 E12 成片审看 1b/1c"}
    write_json(p.assembly / f"{ctx.episode}_FINAL_CANDIDATE_CHAIN.json", manifest)
    res.details["final_candidate_chain"] = manifest
    res.receipts.append(str(p.assembly / f"{ctx.episode}_FINAL_CANDIDATE_CHAIN.json"))
    return []


FINAL_RELEASE_GATE_ID = "FINAL-RELEASE-DEFAULT-ACCEPTANCE"
FINAL_RELEASE_MEDIA_ITEM = "final"
#: final-bundle evidence the portable orchestrator never writes on this line (run_episode_qa.sh is recorded but not
#: run; watch_report is the S8 approval, which cannot exist before S7).  A gate FAILing only because one of these is
#: absent is a structural gap of the line, not missing proof of this cut (field device …1324 E01, 2026-11-07).
LINE_UNPRODUCED_EVIDENCE = frozenset({"final_package_manifest", "ci_report", "render_plan",
                                      "audio_provenance_manifest", "watch_report"})


def _evidence_missing_keys(failures: list[Any]) -> list[str] | None:
    """The evidence keys a gate row reports as missing, or None when any failure is something else."""
    keys = []
    for failure in failures or []:
        text = str(failure)
        if not text.startswith("required_evidence_missing:"):
            return None
        keys.append(text.split(":", 2)[1])
    return keys


def kb_final_review_reject(ctx: Ctx, final_audience: dict[str, Any]) -> dict[str, Any]:
    """The rejected final-audience review as knowledge events: one reject fact plus one per dimension the
    independent reviewer scored below 3 (finer clusters than "rejected").  Best-effort."""
    try:
        report = read_json(Path(str(final_audience.get("report") or "")), {}) if final_audience.get("report") else {}
        report = report if isinstance(report, dict) else {}
        dims = report.get("dimensions") if isinstance(report.get("dimensions"), dict) else {}
        low = sorted(name for name, score in dims.items()
                     if isinstance(score, (int, float)) and not isinstance(score, bool) and score < 3)
        hard = report.get("hard_fail")
        reasons = ([f"overall:{report.get('overall')}"] if report.get("overall") is not None else []) \
            + [f"low:{name}" for name in low] + (["hard_fail"] if hard else [])
        sha = final_audience.get("final_video_sha256") or report.get("media_sha256")
        review_report = str(final_audience.get("report") or "") or None
        out = kb_events("record_final_cut", episode=ctx.episode, kind="S7_FINAL_REVIEW_REJECT", items=reasons,
                        media_sha256=sha, evidence={"gate": "FINAL-AUDIENCE-REVIEW",
                                                    "verdict": report.get("verdict")},
                        review_report=review_report)
        if low:
            out = {"reject": out, "dimensions": kb_events(
                "record_final_cut", episode=ctx.episode, kind="S7_FINAL_REVIEW_LOW", items=low,
                media_sha256=sha, evidence={"gate": "FINAL-AUDIENCE-REVIEW"}, review_report=review_report)}
        return out
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def kb_success_exemplars(ctx: Ctx, final_audience: dict[str, Any]) -> dict[str, Any]:
    """成功样例库 capture (nalu_knowledge_events.record_success_exemplars): the episode's scene-type profile, and --
    when the independent review scored the cut well -- the first-pass units and praised practices as
    SUCCESS_EXEMPLAR events.  Best-effort; never changes what S7 decides."""
    try:
        brief = read_json(RUNTIME / "briefs" / f"{ctx.episode}_PRODUCTION_BRIEF.json", {}) or {}
        return kb_events("record_success_exemplars", episode=ctx.episode, manifest_path=str(ctx.p.grouped_seedance),
                         review_report=str(final_audience.get("report") or "") or None,
                         language=ctx_language(ctx), genre=str(brief.get("genre") or ""),
                         media_sha256=final_audience.get("final_video_sha256"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def kb_cast_and_lines(ctx: Ctx) -> tuple[list[tuple[Any, Any]], list[str]]:
    """The cast names (``(character_id, name)``, aliases included) and dialogue lines of the episode contract -- passed
    to the knowledge-event scrubbers only so they can keep them OUT of the fleet-shared events."""
    contract = read_json(ctx.p.contract, {}) or {}
    name_keys = ("canonical_name", "name", "display_name", "name_en", "english_name", "character")
    cast: list[tuple[Any, Any]] = []
    for row in contract.get("character_entities") or []:
        if not isinstance(row, dict):
            continue
        cast += [(row.get("character_id"), row.get(key)) for key in name_keys if row.get(key)]
        cast += [(row.get("character_id"), alias) for alias in row.get("aliases") or [] if isinstance(alias, str)]
    lines = [str(row.get("text") or "") for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []
             if isinstance(row, dict) and row.get("text")]
    return cast, lines


def kb_final_review_findings(ctx: Ctx, final_audience: dict[str, Any]) -> dict[str, Any]:
    """Every confirmed finding of the independent final review (reviewer problems, must-check DEFECTs, confirmed
    Gemini A/V findings -- the set the final fix round acts on) as ``FINAL_REVIEW:<kind>|<language>`` knowledge
    events (nalu_knowledge_events.record_final_review_findings), so the knowledge base learns author-side lessons
    from a poor episode.  Runs for the first review and for the review after a fix round (``review_round``); the
    release train counts distinct episodes, so a finding that survives the round does not double.  Best-effort."""
    try:
        report = str(final_audience.get("report") or "")
        if not report or not Path(report).is_file():
            return {"status": "NO_REVIEW_REPORT"}
        checklist = Path(report).parent / f"{ctx.episode}_QA_DEFECT_CHECKLIST.json"
        record = read_json(final_fix_record_path(ctx), {}) or {}
        first_sha = (record.get("first_review") or {}).get("final_video_sha256")
        sha = final_audience.get("final_video_sha256")
        review_round = ("after_fix" if record.get("status") in FINAL_FIX_IN_PROGRESS and first_sha and sha
                        and sha != first_sha else "first")
        cast, lines = kb_cast_and_lines(ctx)
        return kb_events("record_final_review_findings", episode=ctx.episode, report_path=report,
                         checklist_path=str(checklist) if checklist.is_file() else None, media_sha256=sha,
                         language=ctx_language(ctx), cast_names=cast, dialogue_lines=lines,
                         review_round=review_round)
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def kb_craft_standard_gaps(ctx: Ctx, final_audience: dict[str, Any]) -> dict[str, Any]:
    """NALU_CRAFT_STANDARD_v1 (owner 2026-11-17): the independent reviewer's top craft gaps
    (``<EP>_CRAFT_STANDARD.json`` beside the score report) as ``CRAFT_STD_GAP|<item id>`` knowledge events
    (nalu_knowledge_events.record_craft_gaps).  The cast names and dialogue lines are passed only so the scrubber
    can keep them OUT of the events.  Best-effort; never changes what S7 decides."""
    try:
        report = str(final_audience.get("report") or "")
        craft = Path(report).parent / f"{ctx.episode}_CRAFT_STANDARD.json" if report else None
        if craft is None or not craft.is_file():
            return {"status": "NO_CRAFT_STANDARD_BLOCK"}
        cast, lines = kb_cast_and_lines(ctx)
        return kb_events("record_craft_gaps", episode=ctx.episode, craft_path=str(craft),
                         media_sha256=final_audience.get("final_video_sha256"), language=ctx_language(ctx),
                         cast_names=cast, dialogue_lines=lines)
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def s7_default_release_acceptance(ctx: Ctx, final_qa: dict[str, Any], review_rejected: bool) -> dict[str, Any]:
    """Release a finished cut whose final review or final-package gates did not PASS, on one line-owner order.

    Line owner 2026-11-07 (field device …1324 E01): with ~100 unattended machines a rejected final review must not
    stop the line; the §5 default terms carry it like every other quality FAIL.  The order is recorded under those
    terms (record_supervisor_order.py, gate FINAL-RELEASE-DEFAULT-ACCEPTANCE, one ``final:<what failed>``
    detector per failure, ``--media final=<candidate>``) and binds the candidate's sha, so a re-cut needs a new
    order.  The reviewer's verdict, the score report and every FAIL row stay as recorded; nothing becomes PASS.
    Missing or invalid evidence is not a quality FAIL and is never accepted here."""
    if not ctx.p.final_candidate.is_file():
        return {"status": BLOCKED, "blockers": ["FINAL_CANDIDATE_MISSING"]}
    failing = ["final:FINAL_AUDIENCE_REVIEW_REJECTED"] if review_rejected else []
    summary = read_json(Path(str(final_qa.get("stage_gate_summary") or "")), {}) or {} \
        if final_qa.get("stage_gate_summary") else {}
    full_rows = {str(r.get("gate_id")): r for r in summary.get("results") or summary.get("gates") or []}
    evidence_gaps: list[str] = []
    gates: set[str] = set()
    for row in final_qa.get("stage_gate_rows") or []:
        gid = str(row.get("gate_id") or "")
        if not gid or row.get("status") == PASS:
            continue
        missing = _evidence_missing_keys((full_rows.get(gid) or {}).get("failures") or [row.get("first_failure")])
        if missing is not None:
            unproduced = [k for k in missing if k.split(":", 1)[0] in LINE_UNPRODUCED_EVIDENCE]
            if len(unproduced) != len(missing):  # real proof of this cut is missing: never released on an order
                evidence_gaps.append(gid)
                continue
        gates.add(f"final:{gid}")
    if evidence_gaps:
        return {"status": BLOCKED, "blockers": [f"FINAL_EVIDENCE_MISSING:{','.join(sorted(evidence_gaps))}"]}
    failing += sorted(gates)
    if not failing:  # the gates never produced rows: an evidence problem, not a quality verdict
        return {"status": BLOCKED, "blockers": list(final_qa.get("blockers") or ["FINAL_PACKAGE_QA_NOT_PASS"])}
    sha = sha256_file(ctx.p.final_candidate)
    authority = getattr(ctx, "authority", None) or {}
    issuer = authority.get("line_owner_id") or ""
    orders = _gate_acceptance_orders(ctx)
    order = _rga.find_acceptance(orders, episode=ctx.episode, gate_id=FINAL_RELEASE_GATE_ID, failing=failing,
                                 media_sha256=sha, media_item_id=FINAL_RELEASE_MEDIA_ITEM,
                                 expected_issuer=issuer, engine_root=ENGINE) if issuer else None
    if order is None:
        return {"status": BLOCKED, "failing": failing, "final_candidate_sha256": sha,
                "blockers": ["FINAL_RELEASE_DEFAULT_ACCEPTANCE_ORDER_REQUIRED:" + ",".join(failing)],
                "how": ("record one §5 default-terms order: record_supervisor_order.py --kind GATE_FAIL_ACCEPTANCE "
                        f"--gate-id {FINAL_RELEASE_GATE_ID} --episode {ctx.episode} "
                        + " ".join(f"--detector {f}" for f in failing)
                        + f" --media {FINAL_RELEASE_MEDIA_ITEM}={ctx.p.final_candidate} --orders <private inbox> ...")}
    record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=FINAL_RELEASE_GATE_ID, failing=failing,
                                    media_sha256=sha, media_item_id=FINAL_RELEASE_MEDIA_ITEM,
                                    gate_result_path=str(final_qa.get("stage_gate_summary") or ""))
    record.update({"final_audience_review_rejected": review_rejected,
                   "release_basis": "LINE_OWNER_DEFAULT_ACCEPTANCE"})
    path = ctx.p.assembly / "final_qa" / f"{ctx.episode}_FINAL_RELEASE_ACCEPTANCE.json"
    write_json(path, record)
    ctx.say(f"   !! final release on line-owner default order seq={order.get('seq')}: {', '.join(failing)} kept FAIL")
    return {"status": PASS, "record_path": str(path), "order_seq": order.get("seq"), "failing": failing}


# --------------------------------------------------------------------------- #
# S7 final fix round (line owner 2026-11-20: 「不要等我了，我自己看不过来」)
# --------------------------------------------------------------------------- #
FINAL_FIX_IN_PROGRESS = ("S7_RERUN", "S6_REDO_PENDING")
FINAL_FIX_REVIEW_FILES = ("AUDIENCE_SCORE_REPORT.json", "FINAL_CUT_EVENT_LEDGER.json",
                          "AUDIENCE_SCORE_GATE_RESULT.json", "FINAL_CUT_QUALITY_GATE_RESULT.json",
                          "QA_DEFECT_CHECKLIST.json", "DIRECTOR_EVALUATION.json", "CRAFT_STANDARD.json")


def final_fix_record_path(ctx: Any) -> Path:
    import final_fix_round as _ffr
    return ctx.p.assembly / "final_qa" / _ffr.RECORD_NAME


def final_fix_redo_path(ctx: Any) -> Path:
    return ctx.p.preprod_reports / f"{ctx.episode}_FINAL_FIX_REDO.json"


def final_fix_settings_path(ctx: Any) -> Path:
    return ctx.p.assembly / f"{ctx.episode}_FINAL_FIX_S7_SETTINGS.json"


def final_fix_redo_pending(ctx: Any) -> list[str]:
    """Units the final fix round parked for a paid S6 redo whose new take is not on disk yet."""
    redo = read_json(final_fix_redo_path(ctx), {}) or {}
    return sorted(uid for uid, row in (redo.get("units") or {}).items()
                  if isinstance(row, dict) and not (ctx.p.video_media / f"{uid}.mp4").is_file())


class _final_fix_env:
    """Apply the round's FREE S7 settings (``<EP>_FINAL_FIX_S7_SETTINGS.json``) to os.environ for one S7 pass.

    Once written the settings stay for every later S7 entry of the episode, so a re-entry renders the same cut the
    second review was asked to watch.  A name the operator already set is never overridden."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.applied: dict[str, str] = {}

    def __enter__(self) -> dict[str, str]:
        settings = read_json(final_fix_settings_path(self.ctx), {}) or {}
        for name, value in (settings.get("env") or {}).items():
            if not str(os.environ.get(name) or "").strip():
                os.environ[name] = str(value)
                self.applied[name] = str(value)
        return self.applied

    def __exit__(self, *_exc: Any) -> None:
        for name in self.applied:
            os.environ.pop(name, None)


def _final_fix_cut_windows(ctx: Any) -> dict[str, dict[str, float]]:
    """unit -> {in, duration, start} of the current AgentCut picture track (source seconds)."""
    project = read_json(ctx.p.agentcut_project, {}) or {}
    out: dict[str, dict[str, float]] = {}
    for track in ((project.get("timeline") or {}).get("videoTracks") or []):
        for clip in track.get("clips") or []:
            uid = str((clip.get("metadata") or {}).get("source_id") or "")
            if uid and uid not in out:
                out[uid] = {"in": float(clip.get("in") or 0.0), "duration": float(clip.get("duration") or 0.0),
                            "start": float(clip.get("start") or 0.0)}
    return out


def s7_speaking_units(ctx: Any) -> set[str]:
    """Units carrying an on-screen scripted line (a speaker on screen): the performance cut's SPEAKING rows when it
    ran, else the contract's dialogue units (V.O.-only speakers excluded) through the grouping plan."""
    perf = read_json(ctx.p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json", {}) or {}
    rows = perf.get("units") or []
    if rows:
        return {str(r.get("unit_id")) for r in rows if r.get("kind") == "SPEAKING"}
    try:
        import performance_cut as _perf  # noqa: PLC0415 - engine tools dir is on sys.path at S7
        lines_by_shot, voice_only = _perf._unit_lines(read_json(ctx.p.contract, {}) or {},
                                                      read_json(ctx.p.grouping_plan, {}) or {})
    except Exception:  # noqa: BLE001 - no contract: nobody is known to speak
        return set()
    out = set()
    for unit in (read_json(ctx.p.grouping_plan, {}) or {}).get("units") or []:
        if any(str(ln.get("speaker_id") or "") not in voice_only
               for sid in unit.get("editorial_shot_ids") or [] for ln in lines_by_shot.get(str(sid), [])):
            out.add(str(unit.get("unit_id")))
    return out


def s7_source_unit_asr(ctx: Any) -> dict[str, Any]:
    """Unit ASR in SOURCE seconds of the original unit clips, word timestamps when the S7 tail pass kept them
    (``<EP>_unit_asr_untrimmed.json``), else the captions' unit ASR (segments).  {} when S7 never transcribed."""
    for name in (f"{ctx.episode}_unit_asr_untrimmed.json", f"{ctx.episode}_unit_asr.json"):
        data = read_json(ctx.p.assembly / name, {}) or {}
        if isinstance(data, dict) and data:
            return data
    return {}


def final_fix_static_recut(ctx: Any, units: list[str], timeline_order: list[str]) -> list[dict[str, Any]]:
    """Add one unit_recut entry per over-long static unit to ``<EP>_UNIT_RECUT_PLAN.json`` (free; FREE_S7
    STATIC_SHOT_SPLIT).  Units the authored plan already re-cuts are left alone.  The authored plan, when there is
    one, is kept beside it as ``<EP>_UNIT_RECUT_PLAN.pre_final_fix.json``.  The split respects the S7 edit
    invariants (final_fix_round.static_shot_segments): cuts at line boundaries only, no piece under the minimum shot,
    cutaways only from silent neighbours' speech-free frames."""
    import final_fix_round as _ffr
    import unit_recut as _ur
    plan_path = ctx.p.assembly / f"{ctx.episode}_UNIT_RECUT_PLAN.json"
    plan = read_json(plan_path, {}) or {}
    if plan and plan.get("schema") != _ur.PLAN_SCHEMA:
        return [{"kind": "STATIC_SHOT_SPLIT", "status": "SKIPPED_FOREIGN_PLAN_SCHEMA", "units": units}]
    windows = _final_fix_cut_windows(ctx)
    seconds: dict[str, float | None] = {}
    asr = s7_source_unit_asr(ctx)
    speaking = s7_speaking_units(ctx)

    def clip_seconds(uid: str) -> float | None:
        if uid not in seconds:
            clip = ctx.p.video_media / f"{uid}.mp4"
            seconds[uid] = _probe_seconds(clip) if clip.is_file() else None
        return seconds[uid]

    actions, added = [], {}
    for uid in units:
        if uid in (plan.get("units") or {}):
            actions.append({"kind": "STATIC_SHOT_SPLIT", "unit_id": uid, "status": "SKIPPED_AUTHORED_RECUT"})
            continue
        win = windows.get(uid)
        if not win or win["duration"] <= 0:
            actions.append({"kind": "STATIC_SHOT_SPLIT", "unit_id": uid, "status": "SKIPPED_NOT_IN_CUT"})
            continue
        pos = timeline_order.index(uid) if uid in timeline_order else -1
        neighbours = []
        for nb in ([timeline_order[pos + 1]] if 0 <= pos < len(timeline_order) - 1 else []) + \
                  ([timeline_order[pos - 1]] if pos > 0 else []):
            nwin, total = windows.get(nb), clip_seconds(nb)
            if not nwin or not total or nb in (plan.get("units") or {}):
                continue
            unused = [(0.0, nwin["in"])] + [(nwin["in"] + nwin["duration"], float(total) - 0.05)]
            neighbours.append({"unit_id": nb, "unused": [(a, b) for a, b in unused if b - a > 0],
                               "speaking": nb in speaking, "speech": asr.get(nb) or []})
        got = _ffr.static_shot_segments(uid, (win["in"], win["in"] + win["duration"]), neighbours=neighbours,
                                        speech=asr.get(uid) or [], speaking=uid in speaking)
        if got.get("status") != "PLANNED":
            actions.append({"kind": "STATIC_SHOT_SPLIT", "unit_id": uid, "status": got.get("status")})
            continue
        added[uid] = {"segments": got["segments"], "reason": f"FINAL_FIX_ROUND static shot split ({got['method']})",
                      "final_fix_round": True}
        actions.append({"kind": "STATIC_SHOT_SPLIT", "unit_id": uid, "status": "PLANNED", "method": got["method"],
                        **({"borrowed_from": got["borrowed_from"]} if got.get("borrowed_from") else {})})
    if added:
        if plan_path.is_file():
            backup = plan_path.with_name(f"{ctx.episode}_UNIT_RECUT_PLAN.pre_final_fix.json")
            if not backup.exists():
                shutil.copy2(str(plan_path), str(backup))
        merged = {"schema": _ur.PLAN_SCHEMA, "episode": ctx.episode, **{k: v for k, v in plan.items()
                                                                         if k not in ("schema", "episode", "units")},
                  "units": {**(plan.get("units") or {}), **added}}
        write_json(plan_path, merged)
    return actions


def _final_fix_wardrobe(ctx: Any, uid: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The identity-card wardrobe rows of the characters a unit shows (editorial wardrobe contracts)."""
    grouping = read_json(ctx.p.grouping_plan, {}) or {}
    shot_ids = next((set(map(str, u.get("editorial_shot_ids") or [])) for u in grouping.get("units") or []
                     if str(u.get("unit_id")) == uid), set())
    editorial = read_json(ctx.p.editorial, {}) or {}
    rows: dict[str, dict[str, Any]] = {}
    for shot in editorial.get("shots") or []:
        if str(shot.get("shot_id")) not in shot_ids:
            continue
        for row in (shot.get("wardrobe_contract") or {}).get("characters") or []:
            key = str(row.get("character_id") or row.get("character") or "")
            if key:
                rows.setdefault(key, row)
    return list(rows.values()), list(rows)


def final_fix_park_units(ctx: Any, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Park each selected unit's clip for ONE paid redo and record its redo sentence in
    ``reports/<EP>_FINAL_FIX_REDO.json`` (the compile carries it as ``h3_final_fix``; S6 redoes the unit through
    every existing gate).  S6 is reopened so the next run that includes it re-enters the wave loop."""
    import final_fix_round as _ffr
    path = final_fix_redo_path(ctx)
    state = read_json(path, {}) or {"schema": _ffr.REDO_SCHEMA, "episode": ctx.episode, "units": {}}
    park = ctx.p.video_media / f"_superseded_{ctx.run_id}_final_fix"
    done = []
    for row in selected:
        uid = row["unit_id"]
        clip = ctx.p.video_media / f"{uid}.mp4"
        if not clip.is_file():
            continue
        rows, chars = _final_fix_wardrobe(ctx, uid) if "COSTUME_IDENTITY" in row["kinds"] else ([], [])
        sentence = _ffr.redo_sentence(row["kinds"], wardrobe_rows=rows, character_ids=chars)
        park.mkdir(parents=True, exist_ok=True)
        clip_sha = sha256_file(clip)
        os.replace(clip, park / clip.name)
        rec = {"round": 1, "kind": row["kind"], "kinds": row["kinds"], "sentence": sentence,
               "planned_credits": row.get("cost"), "parked_clip": str(park / clip.name),
               "parked_clip_sha256": clip_sha, "on_screen_seconds": row.get("on_screen_seconds"),
               "run_id": ctx.run_id, "recorded_at": now(), "recorded_by": TOOL_ID, "status": "PARKED"}
        state.setdefault("units", {})[uid] = rec
        ctx.say(f"FINAL_FIX_UNIT_REDO unit={uid} kind={row['kind']} kinds={','.join(row['kinds'])} "
                f"planned_credits={row.get('cost')}")
        done.append({"unit_id": uid, **{k: rec[k] for k in ("kind", "kinds", "planned_credits", "parked_clip")}})
    if done:
        write_json(path, state)
        s6 = ctx.stage_state("S6")
        s6["status"] = "REOPENED_FINAL_FIX"
        s6["reopened"] = {"by": "final_fix_round", "units": [d["unit_id"] for d in done], "at": now()}
        ctx.save_state()
    return done


def final_fix_archive_first_review(ctx: Any, report_path: str | None) -> dict[str, str]:
    """Copy the first review's report, ledger, gate results and must-check list aside before the second review
    overwrites them (``final_qa/final_fix_round/first_review/``)."""
    out: dict[str, str] = {}
    if not report_path:
        return out
    base = Path(str(report_path)).parent
    dest = ctx.p.assembly / "final_qa" / "final_fix_round" / "first_review"
    for suffix in FINAL_FIX_REVIEW_FILES:
        src = base / f"{ctx.episode}_{suffix}"
        if src.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dest / src.name))
            out[suffix] = str(dest / src.name)
    request = REVIEWS_ROOT / ctx.episode / "final_audience_request.json"
    if request.is_file():
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(request), str(dest / request.name))
        out["request"] = str(dest / request.name)
    return out


def _final_fix_credits(ctx: Any) -> float | None:
    try:
        return float(credits_summary(ctx).get("recorded_total_credits") or 0)
    except Exception:  # noqa: BLE001 - bookkeeping only
        return None


def final_fix_voice_check(ctx: Any, uid: str, window: list[float] | None = None) -> dict[str, Any]:
    """Speaker / voice gender mismatch at ``uid`` (E18 2026-11-20 P1): is the unit's speaker_voice_contract mapping
    wrong (final_fix_round.voice_assignment_check against the voice registry), or does a V.O. line placed by S7
    (``<EP>_voice_over_placement.json``) sound over the shot?  Read-only; the fix round never re-voices H3 native
    audio, so a MAPPING_BUG is reported (record + KB + fleet note), not auto-fixed."""
    import final_fix_round as _ffr
    task = next((t for t in (read_json(ctx.p.video_transaction, {}) or {}).get("tasks") or []
                 if str(t.get("unit_id") or "") == uid), None) or {}
    machine = task.get("machine_contract") or {}
    contract = task.get("speaker_voice_contract") or machine.get("speaker_voice_contract") or {}
    entities = task.get("character_entities") or machine.get("character_entities") or []
    registry_rows: list[dict[str, Any]] = []
    try:
        scope = getattr(ctx.p, "scope", None) or {}
        reg_path = scope.get("voice_registry") if isinstance(scope, dict) else None
        reg_path = reg_path or os.environ.get("QINGSHAN_VOICE_REGISTRY")
        if reg_path:
            registry_rows = list((read_json(Path(str(reg_path)), {}) or {}).get("major_roles") or [])
    except Exception:  # noqa: BLE001 - no registry: the check says UNKNOWN
        registry_rows = []
    out = _ffr.voice_assignment_check(contract.get("bindings") or [], registry_rows, entities)
    out["unit_id"] = uid
    if not task:
        out["status"] = "NO_TASK"
    if window:
        placement = read_json(voice_over_placement_path(ctx), {}) or {}
        hits = [{k: r.get(k) for k in ("shot_id", "line_index", "character_id", "start", "end")}
                for r in placement.get("rows") or []
                if _ffr._near([float(r.get("start") or 0), float(r.get("end") or 0)], window, 0.5)]
        if hits:
            out["voice_over_lines"] = hits
            out["cause_hint"] = "VOICE_OVER_PLACED_OVER_THIS_SHOT"
    return out


def _final_fix_annotate(ctx: Any, mapped: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    """In place: voice checks on speaker / voice gender findings and the measured cause of clipped line tails
    (tools/performance_cut rows of ``<EP>_PERFORMANCE_CUT.json``).  Best-effort, read-only."""
    import final_fix_round as _ffr
    perf = None
    order = [str(s.get("unit_id")) for s in segments or []]
    for f in mapped:
        uid = f.get("unit_id")
        try:
            if f.get("kind") == "VOICE_GENDER_MISMATCH" and uid:
                f["voice_check"] = final_fix_voice_check(ctx, str(uid), f.get("window"))
                if f["voice_check"].get("status") == "MAPPING_BUG":
                    ctx.say(f"FINAL_FIX_VOICE_MAPPING_BUG unit={uid} "
                            + ",".join(str(b.get("problem")) for b in f["voice_check"].get("bugs") or []))
                    # the bound reference itself is the wrong voice (mapping or casting): a re-render with the same
                    # reference repeats it -> recorded (and the S4 casting check recasts it), never a paid redo
                    f["class"] = _ffr.RECORD
                    f["redo_skipped"] = "VOICE_MAPPING_OR_CASTING_BUG"
            elif f.get("kind") == "DIALOGUE_TAIL_GUARD" and uid:
                if perf is None:
                    perf = {str(r.get("unit_id")): r for r in (read_json(
                        ctx.p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json", {}) or {}).get("units") or []}
                pos = order.index(str(uid)) if str(uid) in order else -1
                nxt = perf.get(order[pos + 1]) if 0 <= pos < len(order) - 1 else None
                f["tail_cause"] = _ffr.tail_cut_cause(perf.get(str(uid)), nxt)
        except Exception as exc:  # noqa: BLE001 - annotation never blocks the round
            f["annotation_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"


def s7_burned_line_summary(ctx: Any, report_path: Path) -> list[dict[str, Any]]:
    """The strict burned-line decisions of S7 (``burned_line_checks`` of <EP>_BURNIN_SUBTITLES.json) for the
    episode record, one log line each.  [] when none / unreadable."""
    rows = []
    for row in ((read_json(report_path, {}) or {}).get("burned_line_checks") or []):
        if not isinstance(row, dict):
            continue
        rows.append({k: row.get(k) for k in ("unit_id", "shot_id", "verdict", "reasons", "segments", "burn_window",
                                             "spoken_window", "ocr_source", "ocr_model", "suppressed")
                     if row.get(k) is not None})
        try:
            ctx.say(f"S7_BURNED_LINE_CHECK unit={row.get('unit_id')} shot={row.get('shot_id')} "
                    f"verdict={row.get('verdict')} -> {'cue suppressed' if row.get('suppressed') else 'cue kept'}"
                    + (f" ({'; '.join(str(r) for r in row.get('reasons') or [])[:200]})" if row.get('reasons') else ""))
        except Exception:  # noqa: BLE001 - a test double without say
            pass
    return rows


def final_fix_s6_rows(ctx: Any, checklist: dict[str, Any]) -> dict[str, Any]:
    """The must-check list with its S6 UNRESOLVED rows made reliable (JA-01 E07 VU-004 2026-11-22: the S6 burn of
    VU-004 stayed UNRESOLVED in our subtitle band, S7 moved our caption above it, yet the final fix round never redid
    the unit).  The rows used to reach the round only through ``<EP>_QA_DEFECT_CHECKLIST.json``, which is missing
    when the reviewer's must-check block was not requested or failed, and dropped whole when it is bound to another
    cut -- S8 already fell back to the S6 wave state, the round did not.  Now: rows missing from the list are read
    from the wave state (only units whose kept take is still the unit's clip), and each in-band row is marked
    ``duplicate_suppressed`` when S7 suppressed our copy of the line (``<EP>_BURNIN_SUBTITLES.json``
    ``suppressed_duplicate_cues``).  Read-only, never raises."""
    out = dict(checklist or {})
    try:
        import nalu_qa_defect_checklist as _qa
        def superseded(row: dict[str, Any]) -> bool:  # the unit was redone since: the row is of an older take
            clip = ctx.p.video_media / f"{row.get('unit_id')}.mp4"
            return bool(row.get("kept_take_sha256") and clip.is_file() and sha256_file(clip) != row["kept_take_sha256"])

        rows = [dict(r) for r in (out.get("s6_burn_unresolved") or []) if isinstance(r, dict) and not superseded(r)]
        state = read_json(_wave_state_path(ctx), {}) or {}
        have = {str(r.get("unit_id")) for r in rows}
        for row in ((_qa.measure_s6_burn_unresolved(state) or {}).get("units") or []):
            if str(row.get("unit_id")) in have or superseded(row):
                continue
            rows.append({**row, "source_fallback": "S6_WAVE_STATE"})
        burnin = read_json(ctx.p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json", {}) or {}
        suppressed = {str(r.get("unit_id")) for r in burnin.get("suppressed_duplicate_cues") or []
                      if isinstance(r, dict) and r.get("verdict") == "ACCEPT_CORRECT"}
        verdicts: dict[str, list[str]] = {}
        for r in burnin.get("burned_line_checks") or []:
            if isinstance(r, dict):
                verdicts.setdefault(str(r.get("unit_id")), []).append(str(r.get("verdict")))
        for row in rows:
            uid = str(row.get("unit_id"))
            if verdicts.get(uid):
                row["strict_burn_verdicts"] = verdicts[uid]
            # owner 2026-11-23: our copy counts as suppressed only when the strict check accepted the burned line as
            # exactly the cue's line, and no other line of the unit was rejected -- anything else stacks: P1 trigger
            if uid in suppressed and not any(v.startswith("REJECT") for v in verdicts.get(uid, [])):
                row["duplicate_suppressed"] = True
        if rows or out.get("s6_burn_unresolved"):
            out["s6_burn_unresolved"] = rows
    except Exception as exc:  # noqa: BLE001 - the list as it was
        out.setdefault("s6_rows_error", f"{type(exc).__name__}: {str(exc)[:160]}")
    return out


def final_fix_review_findings(ctx: Any, report_path: str, cand_sha: str,
                              segments: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The confirmed, mapped, deduped and annotated findings of one final review (None when its report is not
    readable).  A must-check list bound to another cut is ignored."""
    import final_fix_round as _ffr
    if not report_path or not Path(report_path).is_file():
        return None
    report = read_json(Path(report_path), {}) or {}
    checklist_path = Path(report_path).parent / f"{ctx.episode}_QA_DEFECT_CHECKLIST.json"
    checklist = read_json(checklist_path, {}) if checklist_path.is_file() else {}
    if isinstance(checklist, dict) and (checklist.get("bindings") or {}).get("final_video_sha256") not in (None, cand_sha):
        checklist = {}  # a must-check list of another cut is not a finding of this one
    checklist = final_fix_s6_rows(ctx, checklist if isinstance(checklist, dict) else {})
    mapped = _ffr.dedupe(_ffr.map_findings(_ffr.collect_findings(report, checklist), segments))
    _final_fix_annotate(ctx, mapped, segments)
    return mapped


def s7_final_fix_round(ctx: Any, res: Any, final_audience: dict[str, Any], review_rejected: bool) -> dict[str, Any]:
    """The S7 hook after the independent final review (PASS or REJECT_RECUT).  Returns {action, record} where action
    is PROCEED (continue to final QA / release exactly as before), S7_RERUN (free fixes applied: re-run S7 now) or
    S6_REDO_PENDING (units parked for a paid redo: S6 must run before S7).  At most one round per episode; whatever
    the second review says, the line proceeds."""
    import final_fix_round as _ffr
    p = ctx.p
    path = final_fix_record_path(ctx)
    record = read_json(path, {}) or {}
    cand_sha = str(final_audience.get("final_video_sha256") or sha256_file(p.final_candidate) or "")
    verdict = "REJECT_RECUT" if review_rejected else "PASS"
    report_path = str(final_audience.get("report") or "")

    def done(rec: dict[str, Any], note: str | None = None) -> dict[str, Any]:
        spent_now = _final_fix_credits(ctx)
        start = rec.get("credits_at_start")
        segments_now = (read_json(p.assembly / f"{ctx.episode}_release_timeline.json", {}) or {}).get("segments") or []
        # the second review of a NEW cut is reconciled against the first (2026-11-20 E18: 23 of 30 "unresolved"
        # were first-round findings never checked against the second review, counted twice)
        second = None if note else final_fix_review_findings(ctx, report_path, cand_sha, segments_now)
        rec.update(status="DONE", finished_at=now(),
                   second_review={"verdict": verdict, "final_video_sha256": cand_sha, "report": report_path or None,
                                  **({"note": note} if note else {}),
                                  **({"findings": second} if second is not None else {})},
                   credits_spent=(round(spent_now - float(start), 3)
                                  if spent_now is not None and start is not None else None))
        burn = final_fix_burn_summary(read_json(final_fix_redo_path(ctx), {}) or {})
        if burn:
            rec.setdefault("paid", {})["burn_checks"] = burn
        # dedupe again: a record started by an engine without the dedupe (an episode in flight) still reconciles 1:1
        rec["findings"] = _ffr.dedupe(rec.get("findings") or [])
        rec["reconciliation"] = _ffr.reconcile(rec["findings"], second)
        rec["unresolved"] = _ffr.unresolved(rec)
        _ffr.write_record(path, rec)
        counts = rec["reconciliation"]["counts"]
        ctx.say(f"FINAL_FIX_ROUND_DONE verdict={verdict} episode={ctx.episode} "
                f"units_redone={','.join(_ffr.summary(rec)['units_redone']) or '-'} "
                f"resolved={counts.get(_ffr.RESOLVED, 0)} persists={counts.get(_ffr.PERSISTS, 0)} "
                f"new={counts.get(_ffr.NEW, 0)} unverified={counts.get(_ffr.UNVERIFIED, 0)} "
                f"unresolved={len(rec['unresolved'])}" + (f" ({note})" if note else ""))
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(rec)}

    if getattr(ctx, "_text_removal_rerun", False) and record.get("status") in ("NOT_NEEDED", "NO_ACTIONABLE_FIX",
                                                                                "DISABLED"):
        # the re-run for the local burned-text removal (stage_s7) never opens a second round on its new cut
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(record)}
    if record.get("status") in FINAL_FIX_IN_PROGRESS:
        first_sha = (record.get("first_review") or {}).get("final_video_sha256")
        if cand_sha and cand_sha != first_sha:
            return done(record)
        pending = final_fix_redo_pending(ctx)
        if pending:
            return {"action": "S6_REDO_PENDING", "record": str(path), "units": pending, **_ffr.summary(record)}
        return done(record, "CANDIDATE_UNCHANGED_AFTER_FIX")
    if record.get("status") == "DONE":
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(record)}
    if record.get("status") and (record.get("first_review") or {}).get("final_video_sha256") == cand_sha:
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(record)}

    base = {"episode": ctx.episode, "recorded_by": TOOL_ID, "started_at": now(),
            "owner_policy": "never_wait_quality", "rounds_allowed": _ffr.rounds(),
            "first_review": {"verdict": verdict, "final_video_sha256": cand_sha, "report": report_path or None}}
    if _ffr.rounds() == 0:
        _ffr.write_record(path, {**base, "status": "DISABLED"})
        return {"action": "PROCEED", "record": str(path), "status": "DISABLED"}
    segments = (read_json(p.assembly / f"{ctx.episode}_release_timeline.json", {}) or {}).get("segments") or []
    # one finding per defect: the checklist path and the reviewer-problem path often name the same one (E18: 15
    # problems counted as 30) -- deduped before planning and counting
    mapped = final_fix_review_findings(ctx, report_path, cand_sha, segments) or []
    base["findings"] = mapped
    if not _ffr.triggered(review_rejected, mapped):
        rec = {**base, "status": "NOT_NEEDED", "note": "first review PASS without a confirmed must-check defect"}
        rec["unresolved"] = _ffr.unresolved(rec)
        _ffr.write_record(path, rec)
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(rec)}
    if not _ffr.actionable(mapped):
        rec = {**base, "status": "NO_ACTIONABLE_FIX",
               "note": "every confirmed finding is record-only (or has no unit); second review skipped"}
        rec["unresolved"] = _ffr.unresolved(rec)
        _ffr.write_record(path, rec)
        ctx.say(f"FINAL_FIX_ROUND_DONE verdict={verdict} episode={ctx.episode} (no actionable fix; "
                f"{len(rec['unresolved'])} finding(s) recorded)")
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(rec)}
    if getattr(ctx, "dry", False):
        return {"action": "PROCEED", "status": DRY, "findings": len(mapped)}

    free_kinds = sorted({f["kind"] for f in mapped if f["class"] == _ffr.FREE})
    ctx.say(f"FINAL_FIX_ROUND_START episode={ctx.episode} first_verdict={verdict} findings={len(mapped)} "
            f"free={','.join(free_kinds) or '-'} paid_candidates="
            f"{','.join(sorted({f['unit_id'] for f in mapped if f['class'] == _ffr.PAID and f.get('unit_id')})) or '-'}")
    base["credits_at_start"] = _final_fix_credits(ctx)
    base["first_review"]["archived"] = final_fix_archive_first_review(ctx, report_path)

    # paid plan: one redo per unit, round cap + episode headroom, burned > costume > face by on-screen time
    model = episode_video_model(ctx.episode)
    seconds = {str(t.get("unit_id") or t.get("task_key")): float(t.get("duration_seconds") or 0)
               for t in (read_json(p.video_transaction, {}) or {}).get("tasks") or []}
    already = set(((read_json(final_fix_redo_path(ctx), {}) or {}).get("units") or {}))
    headroom: int | None = None
    if any(f["class"] == _ffr.PAID for f in mapped):
        try:
            verdict_row = ctx.budget_check(0, label="final_fix_round_headroom").get("budget_verdict") or {}
            if verdict_row.get("headroom_credits") is not None:
                headroom = int(verdict_row["headroom_credits"])
        except Exception as exc:  # noqa: BLE001 - unknown headroom: no paid redo
            ctx.say(f"   final fix round: budget headroom unavailable ({type(exc).__name__})")

    def eligible(uid: str) -> str | None:
        if model != "MiniMax-H3":
            return f"MODEL_NOT_H3:{model}"
        if uid in already:
            return "ALREADY_REDONE_IN_FINAL_FIX"
        if not (p.video_media / f"{uid}.mp4").is_file():
            return "CLIP_NOT_ON_DISK"
        return None

    paid = _ffr.plan_paid(mapped, budget=_ffr.budget_credits(), headroom=0 if headroom is None else headroom,
                          unit_cost=lambda uid: video_task_credits(model, seconds.get(uid, 6.0), 1,
                                                                   episode_video_resolution(ctx.episode)),
                          eligible=eligible, unit_order=[str(s.get("unit_id")) for s in segments])
    if headroom is None:
        paid["headroom_note"] = "BUDGET_HEADROOM_UNKNOWN: no paid redo"

    # free fixes: S7 settings + static-shot re-cut entries
    free_actions: list[dict[str, Any]] = []
    settings = _ffr.free_settings(free_kinds)
    if settings["env"] or settings["kept_operator_env"]:
        write_json(final_fix_settings_path(ctx), {"schema": _ffr.SETTINGS_SCHEMA, "episode": ctx.episode,
                                                  "kinds": free_kinds, **settings, "recorded_at": now()})
        for kind in free_kinds:
            if kind in _ffr.FREE_SETTINGS:
                free_actions.append({"kind": kind, "status": "APPLIED_ON_S7_RERUN",
                                     "env": {k: v for k, v in settings["env"].items()
                                             if k in _ffr.FREE_SETTINGS[kind]}})
                ctx.say(f"FINAL_FIX_FREE_RECUT kind={kind} settings="
                        + ",".join(f"{k}={v}" for k, v in settings["env"].items() if k in _ffr.FREE_SETTINGS[kind]))
    static_units = sorted({f["unit_id"] for f in mapped if f["kind"] == "STATIC_SHOT_SPLIT" and f.get("unit_id")})
    if static_units:
        for action in final_fix_static_recut(ctx, static_units, [str(s.get("unit_id")) for s in segments]):
            free_actions.append(action)
            if action.get("status") == "PLANNED":
                ctx.say(f"FINAL_FIX_FREE_RECUT kind=STATIC_SHOT_SPLIT unit={action['unit_id']} "
                        f"method={action.get('method')}")
    parked = final_fix_park_units(ctx, paid["selected"])
    paid["selected"] = [row for row in paid["selected"] if row["unit_id"] in {d["unit_id"] for d in parked}]
    paid["planned_credits"] = sum(int(row.get("cost") or 0) for row in paid["selected"])
    applied_free = [a for a in free_actions if a.get("status") in ("PLANNED", "APPLIED_ON_S7_RERUN")]
    if not parked and not applied_free:
        rec = {**base, "status": "NO_ACTIONABLE_FIX", "paid": paid, "free_actions": free_actions,
               "note": "nothing could be applied (budget / eligibility / cut); second review skipped"}
        rec["unresolved"] = _ffr.unresolved(rec)
        _ffr.write_record(path, rec)
        ctx.say(f"FINAL_FIX_ROUND_DONE verdict={verdict} episode={ctx.episode} (nothing applicable)")
        return {"action": "PROCEED", "record": str(path), **_ffr.summary(rec)}
    status = "S6_REDO_PENDING" if parked else "S7_RERUN"
    rec = {**base, "status": status, "paid": paid, "free_actions": free_actions}
    _ffr.write_record(path, rec)
    return {"action": status, "record": str(path), "units": [d["unit_id"] for d in parked], **_ffr.summary(rec),
            **({"next": f"{RT_TOOLS / 'paid_stage.sh'} {ctx.episode} S6 S8"} if parked else {})}


def s7_review_plan_parity(ctx: Any, res: Any, final_audience: dict[str, Any]) -> dict[str, Any]:
    """After the final review (and its fix round) proceeds: the per-unit plan parity of the multi-pass review's
    pass D (gemini_review.json ``plan_parity``) is folded into ``<EP>_FINAL_CUT_SHOT_PLAN_PARITY.json`` / .md
    (final_cut_shot_plan_parity.merge_review_parity), and the final fix record gets ``plan_parity``, the objective
    defects left at release (runtime vs target, unresolved burns, stray voices, plan NO units) and the release
    policy (``release_block_objective_defects``, default OFF: recorded, never blocks) -- 2026-11-23, device 1101
    E24 shipped with wrong locations, reversed roles, invented people and 56 s of a 110 s brief.  The checkpoint and
    the fleet note read them from the record (final_fix_round.objective_lines / status_note).  Never raises."""
    import final_fix_round as _ffr
    p = ctx.p
    out: dict[str, Any] = {"status": "NONE"}
    try:
        cand_sha = str(final_audience.get("final_video_sha256") or sha256_file(p.final_candidate) or "")
        try:
            import final_audience_review as _far  # noqa: PLC0415 -- same directory
            gemini = read_json(_far.gemini_review_path(ctx.episode), {}) or {}
        except Exception:  # noqa: BLE001 - no record: nothing to fold
            gemini = {}
        bound = bool(gemini) and gemini.get("final_video_sha256") in (None, cand_sha)
        parity = dict(gemini.get("plan_parity") or {}) if bound else {}
        # the must-check list carries the reviewer's decision on each local suspect next to Gemini's
        report_path = str(final_audience.get("report") or "")
        checklist = (read_json(Path(report_path).parent / f"{ctx.episode}_QA_DEFECT_CHECKLIST.json", {}) or {}
                     if report_path else {})
        if (checklist.get("bindings") or {}).get("final_video_sha256") not in (None, cand_sha):
            checklist = {}
        checks = ((checklist.get("video_review") or {}).get("suspect_checks")
                  or (gemini.get("suspect_checks") if bound else None) or [])
        parity_json = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.json"
        report = read_json(parity_json, {}) or {}
        if report:
            import final_cut_shot_plan_parity as _parity  # noqa: PLC0415 -- same directory
            report = _parity.merge_review_parity(report, gemini if bound else None, final_sha256=cand_sha)
            write_json(parity_json, report)
            md = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.md"
            md.write_text(_parity.checkpoint_block(report), encoding="utf-8")
            row = res.details.get("shot_plan_parity") if isinstance(res.details.get("shot_plan_parity"), dict) else {}
            res.details["shot_plan_parity"] = {**row, "status": report.get("status"),
                                               "findings": [f.get("code") for f in report.get("findings") or []],
                                               "unit_parity": _ffr.plan_parity_summary(parity) or report.get(
                                                   "unit_parity", {}).get("status")}
        timeline = read_json(p.assembly / f"{ctx.episode}_release_timeline.json", {}) or {}
        brief = read_json(RUNTIME / "briefs" / f"{ctx.episode}_PRODUCTION_BRIEF.json", {}) or {}
        target = float(brief.get("target_seconds") or SCRIPT_DEFAULT_TARGET_SECONDS)
        path = final_fix_record_path(ctx)
        record = read_json(path, {}) or {}
        if not record.get("status"):  # no round recorded (dry run): the round owns its record
            return {**out, "status": "NO_FINAL_FIX_RECORD", "plan_parity": _ffr.plan_parity_summary(parity)}
        record["plan_parity"] = _ffr.plan_parity_summary(parity)
        record["objective_defects"] = _ffr.objective_defects(
            record, runtime_s=timeline.get("content_runtime_seconds"), target_s=target, plan_parity=parity,
            suspect_checks=checks)
        record["release_policy"] = _ffr.release_policy(record["objective_defects"])
        hold = _ffr.release_hold(record)
        if hold:
            record["release_hold"] = {"status": _ffr.RELEASE_HELD, "hold": hold, "final_video_sha256": cand_sha,
                                      "held_at": now(), "redo_backlog": str(series_redo_backlog(
                                          ctx, hold, record, cand_sha))}
        else:
            record.pop("release_hold", None)
        _ffr.write_record(path, record)
        out = {"status": "RECORDED", "record": str(path), **_ffr.objective_summary(record)}
        ctx.say(f"S7_OBJECTIVE_DEFECTS episode={ctx.episode} {_ffr.objective_note(record) or 'none'} "
                f"release={hold or 'RELEASE'}")
    except Exception as exc:  # noqa: BLE001 - diagnostic: never blocks by accident
        out = {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return out


REDO_BACKLOG_NAME = "REDO_BACKLOG.json"


def series_redo_backlog(ctx: Any, hold: str, record: dict[str, Any], cand_sha: str) -> Path:
    """Queue a RELEASE_HELD episode as a redo candidate (owner 2026-11-23: held, never waited on): one row per
    episode in ``<runtime>/series/REDO_BACKLOG.json`` (replaced when the cut changes) and one STATUS.md line per
    hold, so the episode can be regenerated later while production goes on.  Best effort."""
    series = RUNTIME / "series"
    path = series / REDO_BACKLOG_NAME
    try:
        series.mkdir(parents=True, exist_ok=True)
        backlog = read_json(path, {}) or {}
        rows = backlog.setdefault("episodes", {})
        prior = rows.get(ctx.episode) or {}
        obj = record.get("objective_defects") or {}
        rows[ctx.episode] = {"status": "REDO_CANDIDATE", "hold": hold, "final_video_sha256": cand_sha,
                             "queued_at": prior.get("queued_at") if prior.get("final_video_sha256") == cand_sha
                             else now(), "runtime": obj.get("runtime") or {},
                             "burn_units": sorted({str(b.get("unit_id")) for b in obj.get("unresolved_burns") or []
                                                   if b.get("blocking") and b.get("unit_id")}),
                             "plan_no_units": [u.get("unit_id") for u in obj.get("plan_no_units") or []]}
        write_json(path, {"schema": "nalu.series_redo_backlog.v1", **backlog, "updated_at": now()})
        status = series / "STATUS.md"
        line = f"{hold} {ctx.episode}: not sent to X2C, queued for a redo ({path.name}); next episode proceeds"
        if line not in (status.read_text(encoding="utf-8") if status.is_file() else ""):
            with status.open("a", encoding="utf-8") as fh:
                fh.write(f"- {now()} {line}\n")
    except OSError as exc:
        ctx.say(f"   redo backlog not written ({type(exc).__name__})")
    return path


def promote_final_candidate(p: Any) -> dict[str, Any]:
    """Copy the S7-approved candidate (and its tail-ad variant) into deliverables/, sha-verified.

    Roger 2026-10-30 (E12 成片审看 item 0): detectors FAIL ⇒ no deliverable render.  Called only
    from stage_s7 after every gate is PASS or order-carried.  Idempotent: an identical deliverable
    already in place is left alone; a different one is replaced (the candidate is the authority)
    and the replaced bytes are parked next to it with their sha in the name, never deleted."""
    import shutil
    out: dict[str, Any] = {"promoted_at": now(), "final_candidate": str(p.final_candidate),
                           "final_candidate_sha256": sha256_file(p.final_candidate)}
    p.deliver.mkdir(parents=True, exist_ok=True)
    for src, dst, key in ((p.final_candidate, p.final_mp4, "final_video"),
                          (p.ad_tail_candidate, p.ad_tail_video, "ad_tail_video")):
        if not src.is_file():
            if key == "final_video":
                raise FileNotFoundError(str(src))
            continue
        src_sha = sha256_file(src)
        if dst.is_file():
            if sha256_file(dst) == src_sha:
                out[key] = str(dst); out[f"{key}_sha256"] = src_sha; out[f"{key}_action"] = "ALREADY_IN_PLACE"
                continue
            parked = dst.with_name(f"{dst.stem}__superseded_{(sha256_file(dst) or 'nosha')[:12]}{dst.suffix}")
            shutil.move(str(dst), str(parked))
            out[f"{key}_superseded_parked"] = str(parked)
        tmp = dst.with_name(dst.name + ".promoting")
        shutil.copy2(str(src), str(tmp))
        if sha256_file(tmp) != src_sha:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"PROMOTION_SHA_MISMATCH:{src.name}")
        tmp.replace(dst)
        out[key] = str(dst); out[f"{key}_sha256"] = src_sha; out[f"{key}_action"] = "COPIED"
    return out


def _gate_acceptance_orders(ctx: Any) -> list[dict[str, Any]]:
    """The private order inbox as the S7 gate acceptances read it.

    Gate acceptances are non-paid: ``roger_gate_acceptance`` validates the inbox (schema, unique seqs, latest
    seq or self-acknowledging newer non-paid orders), the issuer and the source receipt itself.  They used to be
    read only when ``ctx.authority_blockers`` was empty -- but that list also carries the PAID order's refusals
    (episode scope, cap, issuer of the paid row ...), which say nothing about a gate acceptance.  A device whose
    paid order no longer covered the episode therefore read NO orders at every S7 gate, while the read-only
    helper (which reads the inbox directly) matched the same order (device 1101 E18, 2026-11-20).  Only the
    coordinates an acceptance needs are required here: an absolute inbox path and a configured line owner."""
    return _gate_acceptance_orders_diagnosed(ctx)[0]


def _gate_acceptance_orders_diagnosed(ctx: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``_gate_acceptance_orders`` plus how the inbox was read (``roger_gate_acceptance.gate_acceptance_orders``):
    a gate acceptance spends nothing, so an acknowledged seq that trails the inbox because of a paid row no longer
    blanks the whole inbox at S7 (device 1101 E19, 2026-11-21)."""
    authority = getattr(ctx, "authority", None) or {}
    orders_path = authority.get("orders_path")
    issuer = str(authority.get("line_owner_id") or "")
    if not orders_path or not issuer or not Path(str(orders_path)).is_absolute():
        return [], {"inbox": "NOT_CONFIGURED (orders_path absolute + line_owner_id required)",
                    "orders_path": str(orders_path or ""), "line_owner_id": issuer}
    return _rga.gate_acceptance_orders(orders_path, expected_latest_seq=authority.get("latest_order_seq") or 0,
                                       engine_root=ENGINE, expected_issuer=issuer)


RELEASE_LOUDNESS_GATE_ID = "RELEASE-AUDIO-LOUDNESS"
RELEASE_LOUDNESS_MEDIA_ITEM = "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE"   # historical binding key, still honoured first
_LOUDNESS_VALUE_RE = re.compile(r"^-?\d+(?:\.\d+)?(?:LU|LUFS|DBTP)?$", re.IGNORECASE)


def _loudness_failure_identity(failure: str) -> str:
    """A levelling failure without its measured values: ``UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-03:-20.1:DIALOGUE``
    -> ``UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-03:DIALOGUE``; ``ADJACENT_..:VU-01->VU-02:8.4LU`` -> ``ADJACENT_..:VU-01->VU-02``."""
    return ":".join(part for part in str(failure).split(":") if not _LOUDNESS_VALUE_RE.match(part.strip()))


def _loudness_binding_keys(failing: list[str]) -> list[str | None]:
    """Media-binding keys a RELEASE-AUDIO-LOUDNESS order may use for the levelled file: the historical key,
    every failure-code prefix (what record_supervisor_order.py derives from ``--detector``), the gate id, the
    file role, and the plain ``decision.media_sha256``.  The sha itself must still match exactly."""
    keys: list[str | None] = [RELEASE_LOUDNESS_MEDIA_ITEM]
    keys += sorted({str(f).split(":", 1)[0] for f in failing if str(f)})
    keys += [RELEASE_LOUDNESS_GATE_ID, "final_levelled", "loudness", None]
    return keys


def _loudness_tokens(text: str) -> frozenset[str]:
    """Order-insensitive identity tokens of a levelling failure / order detector: measured values dropped,
    ``VU-01->VU-02`` also split into its units, upper-cased."""
    out: set[str] = set()
    for part in _loudness_failure_identity(str(text)).split(":"):
        part = part.strip().upper()
        if not part:
            continue
        out.add(part)
        if "->" in part:
            out.update(x.strip() for x in part.split("->") if x.strip())
    return frozenset(out)


def _loudness_detector_covers(detector: Any, failure: str) -> bool:
    """Does one order detector cover one failure of the levelled file it is sha-bound to?

    The sha binding is exact, and a file's levelling failures are a pure function of its bytes, so on the
    exact file the detector only has to NAME the failure, in any of the shapes recording agents use: the
    verbatim failure; the failure with other measured values (copied from an earlier report); the failure code
    plus its units/role in any order (``VU-03:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE``, the ``<unit>:<blocker>``
    convention of every other gate); the bare failure code; or the gate / blocker name itself."""
    d = str(detector or "").strip()
    if not d:
        return False
    if d == failure:
        return True
    if _rga.normalize_gate_id(d) == RELEASE_LOUDNESS_GATE_ID:
        return True
    code = str(failure).split(":", 1)[0].strip().upper()
    td = _loudness_tokens(d)
    return code in td and td <= _loudness_tokens(failure)


def _loudness_prior_reports(p: Any, final_sha: str | None) -> dict[str, dict[str, Any]]:
    """Levelled reports this episode parked (``<stem>__superseded_*`` beside the report, or moved into an
    ``assembly/_superseded_*/`` folder by hand): ``{output sha: {path, picture, failures}}``."""
    report = Path(str(p.leveled_audio_report))
    found: list[Path] = sorted(report.parent.glob(f"{report.stem}__superseded_*{report.suffix}"))
    for folder in sorted(report.parent.glob("_superseded_*")):
        if folder.is_dir():
            found += sorted(folder.glob(f"{report.stem}*{report.suffix}"))
    prior: dict[str, dict[str, Any]] = {}
    for parked in found:
        old = read_json(parked, {}) or {}
        old_sha = str((old.get("output_release") or {}).get("sha256") or "")
        if old_sha and old_sha != final_sha:
            prior.setdefault(old_sha, {"path": str(parked), "picture": old.get("source_video_stream_sha256"),
                                       "failures": [str(f) for f in old.get("failures") or [] if str(f)]})
    return prior


def s7_release_loudness_acceptance(ctx: Any, p: Any, failing: list[str],
                                   final_sha: str | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """The line-owner order that carries a FAILed release levelling, plus how it matched (or exactly why not).

    Every order row must be an active, source-receipted GATE_FAIL_ACCEPTANCE of the line owner for this episode
    and gate (spelling normalised) -- ``roger_gate_acceptance.acceptance_row_refusal``.

    Rule 1 (EXACT_SHA): the order binds the sha256 of the CURRENT levelled file (under any key, or the plain
    ``media_sha256``) and its detectors name every current failure (``_loudness_detector_covers``).

    Rule 2 (RECORDED_DRIFT_SAME_PICTURE): the order binds the sha256 of a levelled file this episode parked
    (``_loudness_prior_reports``) that was made from the SAME picture stream, and every current failure is, by
    identity (code + units + role, measured LU values stripped), a failure the order covered on that file.  A
    re-level of the same cut (S7 re-entry, the final-fix-round S7 rerun, a hand-moved report) moves the numbers
    by a few tenths and changes the sha; it does not add a failing unit.  A different picture, a new failing
    unit/code, another episode/gate/issuer, or no receipt never matches.

    ``info`` always names the rule that matched, or ``reason`` plus one ``candidates`` row per order of this
    episode/gate saying which check refused it (row, sha, uncovered failures, drift)."""
    failing = list(dict.fromkeys(str(f) for f in failing if str(f)))
    info: dict[str, Any] = {"gate_id": RELEASE_LOUDNESS_GATE_ID, "failing": list(failing),
                            "media": str(p.final_levelled), "media_sha256": final_sha}
    if not failing or not final_sha:
        info["reason"] = ("NO_LEVELLED_FILE (leveller produced no output: see the s7_level_native_release_audio "
                          "step log)" if not final_sha else
                          "NO_FAILURES_RECORDED (leveller exit != 0 but its report lists no failures)")
        return None, info
    orders, inbox = _gate_acceptance_orders_diagnosed(ctx)
    info["orders_read"] = len(orders)
    info["inbox"] = inbox
    issuer = str((getattr(ctx, "authority", None) or {}).get("line_owner_id") or "")
    current = read_json(p.leveled_audio_report, {}) or {}
    picture = current.get("source_video_stream_sha256")
    prior = _loudness_prior_reports(p, final_sha)
    preferred = _loudness_binding_keys(failing)
    candidates: list[dict[str, Any]] = []

    def _pick(keys: list[Any]) -> Any:
        return next((k for k in preferred if k in keys), keys[0])

    for row in sorted(orders, key=lambda r: -int(r.get("seq") or 0)):
        dec = row.get("decision") or {}
        same_gate = (str(dec.get("episode") or "") == ctx.episode
                     and _rga.normalize_gate_id(dec.get("gate_id")) == RELEASE_LOUDNESS_GATE_ID)
        refusal = _rga.acceptance_row_refusal(row, episode=ctx.episode, gate_id=RELEASE_LOUDNESS_GATE_ID,
                                              expected_issuer=issuer, engine_root=ENGINE)
        if refusal:
            if same_gate:
                candidates.append({"seq": row.get("seq"), "refused": refusal})
            continue
        detectors = [str(d) for d in dec.get("detectors") or [] if str(d)]
        shas = _rga.bound_shas(dec)
        exact_keys = [k for k, v in shas.items() if v == final_sha]
        uncovered = [f for f in failing if not any(_loudness_detector_covers(d, f) for d in detectors)]
        if exact_keys and not uncovered:
            info.update(rule="EXACT_SHA", media_item_id=_pick(exact_keys),
                        coverage=("VERBATIM" if set(failing) <= set(detectors) else "BY_IDENTITY_OR_CODE"))
            return row, info
        cand: dict[str, Any] = {"seq": row.get("seq"),
                                "bound_sha256": {("media_sha256" if k is None else k): v for k, v in shas.items()},
                                "binds_current_sha": bool(exact_keys)}
        if exact_keys:
            cand["uncovered_failures"] = uncovered
        drift_refusals = []
        for key, sha in shas.items():
            old = prior.get(sha)
            if old is None:
                continue
            if not picture or old["picture"] != picture:
                drift_refusals.append({"bound_sha256": sha, "report": old["path"], "refused": "DIFFERENT_PICTURE"})
                continue
            covered = {_loudness_tokens(f) for f in old["failures"]
                       if any(_loudness_detector_covers(d, f) for d in detectors)}
            covered |= {_loudness_tokens(d) for d in detectors if ":" in d}
            new = [f for f in failing if _loudness_tokens(f) not in covered]
            if new:
                drift_refusals.append({"bound_sha256": sha, "report": old["path"],
                                       "refused": "FAILURES_NOT_COVERED_ON_BOUND_FILE", "uncovered_failures": new})
                continue
            info.update(rule="RECORDED_DRIFT_SAME_PICTURE", media_item_id=key, bound_sha256=sha,
                        bound_report=old["path"], source_video_stream_sha256=picture,
                        failure_identities=sorted(_loudness_failure_identity(f) for f in failing))
            return row, info
        if drift_refusals:
            cand["drift"] = drift_refusals
        elif not exact_keys:
            cand["refused"] = "SHA_NOT_CURRENT_AND_NOT_A_PARKED_LEVELLED_FILE_OF_THIS_EPISODE"
        candidates.append(cand)
    if not orders:
        info["reason"] = f"NO_ORDERS_READ ({inbox.get('inbox')})"
    else:
        info["reason"] = "NO_ORDER_MATCHES_EPISODE_GATE_FAILURES_AND_SHA"
        if not candidates:
            info["reason_detail"] = f"no active GATE_FAIL_ACCEPTANCE row for {ctx.episode} {RELEASE_LOUDNESS_GATE_ID}"
    info["candidates"] = candidates[:20]
    info["parked_levelled_reports"] = {k[:12]: v["path"] for k, v in prior.items()}
    info["record_hint"] = (f"record_supervisor_order.py --episode {ctx.episode} --gate-id {RELEASE_LOUDNESS_GATE_ID} "
                           + " ".join(f"--detector '{f}'" for f in failing)
                           + "".join(f" --media {code}={p.final_levelled}"
                                     for code in sorted({f.split(':', 1)[0] for f in failing}))
                           + " --order ... --context ... --orders <private inbox>; then resume S7")
    return None, info


def _reusable_release_level(p: Any, source: Any) -> dict[str, Any] | None:
    """The existing levelled release candidate made from the current source picture (PASS, or a recorded FAIL).

    A FAIL is reused too (field device …1324 E03, 2026-11-09): re-levelling a FAIL parked the output and wrote a
    new one, so a RELEASE-AUDIO-LOUDNESS order bound to the measured file's sha could never be honoured on
    re-entry.  The caller still routes a reused FAIL through the same order check (exit_code 1)."""
    report = read_json(p.leveled_audio_report, {}) or {}
    source = Path(str(source))
    status = str(report.get("status") or "")
    if not (p.final_levelled.is_file() and source.is_file()
            and (status.startswith("PASS") or status.startswith("FAIL"))
            and report.get("source_video_stream_sha256")):
        return None
    # the picture stream alone is not enough: the pitch-unify stage rewrites the AUDIO under a bit-exact
    # picture, so a levelled file made from the un-corrected mix must not be reused for the corrected one
    recorded_source = (report.get("source_release") or {}).get("sha256")
    if recorded_source and recorded_source != sha256_file(source):
        return None
    try:
        sys.path.insert(0, str(ENGINE / "tools"))
        import level_native_release_audio as _lvl
        current = _lvl.stream_hash(source, "0:v:0")
        final = _lvl.stream_hash(p.final_levelled, "0:v:0")
    except Exception:  # noqa: BLE001 -- if we cannot prove it is the same, run the leveller
        return None
    if current != report["source_video_stream_sha256"] or final != report.get("output_video_stream_sha256"):
        return None
    return {"report": str(p.leveled_audio_report), "status": report["status"],
            "source_video_stream_sha256": current, "final_sha256": sha256_file(p.final_levelled)}


def transcribe_clip(model: Any, mp4: Path, language: str, *, words: bool = False) -> list[dict[str, Any]]:
    """One unit clip through the S7 whisper pass (``model`` = faster-whisper ``WhisperModel("small", cpu, int8)``).
    Shared with video Q2's push-in kept window (CAMERA_GRAMMAR_V1, line owner 2026-10-29), which predicts the
    S7 dialogue head/tail trims from the same ASR."""
    if words:
        segs, _ = model.transcribe(str(mp4), language=language, beam_size=5, vad_filter=True,
                                   word_timestamps=True)
        return [{"start": round(x.start, 3), "end": round(x.end, 3), "text": x.text.strip(),
                 "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                           for w in (getattr(x, "words", None) or [])]}
                for x in segs]
    segs, _ = model.transcribe(str(mp4), language=language, beam_size=5, vad_filter=True)
    return [{"start": round(x.start, 3), "end": round(x.end, 3), "text": x.text.strip()}
            for x in segs]


def transcribe_units(ctx: Ctx, media_dir: Path, episode: str, *,
                     words: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Transcribe every unit clip for caption timing, concurrently.

    One ASR pass per unit; the clips are independent and a serial loop pays the
    whisper model's per-file overhead once per unit.  A single model instance is
    shared deliberately: loading it per worker would multiply its memory, and the
    ctranslate2 backend it wraps accepts concurrent calls on one model.  Results
    are keyed by clip stem, which is exactly how the subtitle builder consumes
    them, so completion order cannot affect the captions.  Any unit's exception
    still fails the whole step.

    ``words`` (CAMERA_GRAMMAR_V1 S7 only, 2026-10-26): the same pass also returns per-segment word timestamps
    (faster-whisper ``word_timestamps``) for the dialogue head trim; the default call is unchanged.
    """
    from faster_whisper import WhisperModel  # type: ignore

    clips = sorted(media_dir.glob(f"{episode}-VU-*.mp4"))
    if not clips:
        return {}
    model = WhisperModel(_whisper_model_name(ctx_language(ctx)), device="cpu", compute_type="int8")

    def _one(mp4: Path) -> list[dict[str, Any]]:
        return transcribe_clip(model, mp4, ctx_language(ctx), words=words)

    try:
        workers = max(1, int(os.environ.get("NALU_S7_ASR_WORKERS") or 2))
    except ValueError:
        workers = 2
    if workers <= 1 or len(clips) <= 1:
        return {mp4.stem: _one(mp4) for mp4 in clips}
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    with ThreadPoolExecutor(max_workers=min(workers, len(clips))) as pool:
        futures = [pool.submit(_one, mp4) for mp4 in clips]
        return {mp4.stem: future.result() for mp4, future in zip(clips, futures)}


def _video_stream_hash(path: Path) -> str:
    run = subprocess.run([_media.require_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                          "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True, check=False)
    return run.stdout.strip()


def voice_over_speech_windows(project: dict[str, Any], unit_asr: dict[str, Any],
                              speaking_units: set[str] | None = None) -> list[tuple[float, float]]:
    """In-video speech on the final timeline: each unit's ASR segment mapped through its clip.

    ``speaking_units`` limits the scan to units that carry in-video dialogue: a unit without
    any was admitted by the S6 no-speech ASR gate, so a transcript segment there is a known
    whisper hallucination on ambience, not speech the narration could collide with.
    """
    windows: list[tuple[float, float]] = []
    for track in (project.get("timeline") or {}).get("videoTracks") or []:
        for clip in track.get("clips") or []:
            uid = str((clip.get("metadata") or {}).get("source_id") or "")
            if speaking_units is not None and uid not in speaking_units:
                continue
            start, duration = float(clip.get("start") or 0), float(clip.get("duration") or 0)
            source_in = float(clip.get("in") or 0)
            for seg in unit_asr.get(uid) or []:
                if not _vo.norm_text(seg.get("text") or ""):
                    continue
                s0 = max(float(seg["start"]) - source_in, 0.0)
                s1 = min(float(seg.get("end") or seg["start"]) - source_in, duration)
                if s1 > s0:
                    windows.append((round(start + s0, 3), round(start + s1, 3)))
    return sorted(windows)


def trimmed_unit_bounds(contract: dict[str, Any], grouping: dict[str, Any], project: dict[str, Any]
                        ) -> dict[str, tuple[float, float]]:
    """shot_id -> (start, end) of its unit clip on the final timeline, for units whose clip is shorter
    than the sum of their shots' authored target_seconds (performance cut / tail trim)."""
    clips = {str((clip.get("metadata") or {}).get("source_id") or ""): clip
             for track in (project.get("timeline") or {}).get("videoTracks") or []
             for clip in track.get("clips") or []}
    target = {str(s.get("shot_id")): float(s.get("target_seconds") or 0.0) for s in contract.get("shots") or []}
    out: dict[str, tuple[float, float]] = {}
    for unit in grouping.get("units") or []:
        clip = clips.get(str(unit.get("unit_id")))
        if clip is None:
            continue
        sids = [str(sid) for sid in unit.get("editorial_shot_ids") or []]
        start, duration = float(clip.get("start") or 0), float(clip.get("duration") or 0)
        if duration <= 0 or duration + 1e-3 >= sum(target.get(sid, 0.0) for sid in sids):
            continue
        for sid in sids:
            out[sid] = (start, start + duration)
    return out


def s7_voice_over(ctx: Ctx, res: StageResult, picture: Path, unit_asr: dict[str, Any]
                  ) -> tuple[Path, list[str]]:
    """Place and mix V.O. narration onto the rendered native cut (before burn-in subtitles).

    Shot timing reuses build_final_cut_speaker_map.shot_start_times (unit clip start + earlier
    shots' target_seconds).  The native audio is ducked to 0.35 under each V.O. window with
    short fades; the S4 wavs are added at unity; the video stream is copied and verified
    bit-exact.  Writes <EP>_voice_over_placement.json (sha-bound to the S4 manifest) and records
    it in the AgentCut project (metadata.voice_over_narration).  Returns (picture, blockers).
    """
    p = ctx.p
    placement_path = voice_over_placement_path(ctx)
    editorial = read_json(p.editorial, {}) or {}
    lines = editorial_voice_over_lines(editorial)
    if not lines:
        placement_path.unlink(missing_ok=True)  # never let a stale placement reach BGM / captions
        return picture, []
    manifest_path = voice_over_manifest_path(ctx)
    manifest = read_json(manifest_path, {}) or {}
    by_key = {(str(r.get("shot_id")), int(r.get("line_index", -1))): r for r in manifest.get("rows") or []}
    ordered: list[dict[str, Any]] = []
    for line in lines:
        row = by_key.get((line["shot_id"], int(line["line_index"])))
        if (row is None or row.get("text_sha256") != _vo.text_sha256(line["text"])
                or sha256_file(Path(str(row.get("wav") or ""))) != row.get("wav_sha256")
                or not row.get("duration_seconds")):
            return picture, [f"VOICE_OVER_MANIFEST_INCOMPLETE:{line['shot_id']}:{line['line_index']}"]
        ordered.append(row)
    import build_final_cut_speaker_map as _speaker_map  # noqa: PLC0415 - runtime tools dir is on sys.path
    project = read_json(p.agentcut_project, {}) or {}
    unit_start = {str((clip.get("metadata") or {}).get("source_id") or ""): float(clip.get("start") or 0)
                  for track in (project.get("timeline") or {}).get("videoTracks") or []
                  for clip in track.get("clips") or []}
    grouping = read_json(p.grouping_plan, {}) or {}
    shot_starts, _ = _speaker_map.shot_start_times(read_json(p.contract, {}) or {}, grouping, unit_start)
    spoken_shots = {str(shot.get("shot_id")) for shot in editorial.get("shots") or []
                    if str((shot.get("prompt_spec") or {}).get("dialogue") or "").strip()}
    speaking_units = {str(unit.get("unit_id")) for unit in grouping.get("units") or []
                      if spoken_shots & {str(sid) for sid in unit.get("editorial_shot_ids") or []}}
    rows, failures = _vo.place(ordered, shot_starts, voice_over_speech_windows(project, unit_asr, speaking_units),
                               picture_end=media_seconds(picture),
                               trimmed_units=trimmed_unit_bounds(read_json(p.contract, {}) or {}, grouping, project))
    if failures:
        return picture, failures
    mixed = p.assembly / f"{ctx.episode}_picture_native_vo.mp4"
    argv = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture)]
    for row in rows:
        argv += ["-i", str(row["wav"])]
    argv += ["-filter_complex", _vo.mix_filter([(r["start"], r["end"]) for r in rows], len(rows)),
             "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(mixed)]
    run = subprocess.run(argv, capture_output=True, text=True, check=False)
    res.steps.append({"name": "s7_voice_over_mix", "exit_code": run.returncode, "argv": argv,
                      "log": "in-process ffmpeg", "stderr_tail": tail(run.stderr)})
    if run.returncode != 0 or not mixed.is_file():
        return picture, [f"VOICE_OVER_MIX_FAILED:{(run.stderr or '')[-200:]}"]
    if _video_stream_hash(picture) != _video_stream_hash(mixed):
        mixed.unlink(missing_ok=True)
        return picture, ["VOICE_OVER_MIX_CHANGED_VIDEO_STREAM"]
    write_json(placement_path, {
        "schema": _vo.PLACEMENT_SCHEMA, "episode": ctx.episode, "recorded_at": now(),
        "timeline": "final-timeline seconds of the native cut (before the end card)",
        "rule": {"lead_in_seconds": _vo.LEAD_IN_SECONDS, "line_gap_seconds": _vo.LINE_GAP_SECONDS,
                 "min_separation_seconds": _vo.MIN_SEPARATION_SECONDS, "native_duck_gain": _vo.DUCK_GAIN,
                 "duck_fade_seconds": _vo.DUCK_FADE_SECONDS,
                 "shot_timing": "build_final_cut_speaker_map.shot_start_times"},
        "voice_over_manifest": str(manifest_path), "voice_over_manifest_sha256": sha256_file(manifest_path),
        "source_picture": str(picture), "source_picture_sha256": sha256_file(picture),
        "output_picture": str(mixed), "output_picture_sha256": sha256_file(mixed),
        "video_stream_bit_exact": True,
        "rows": rows,
    })
    project.setdefault("metadata", {})["voice_over_narration"] = {
        "placement": str(placement_path), "placement_sha256": sha256_file(placement_path),
        "voice_over_manifest": str(manifest_path), "voice_over_manifest_sha256": sha256_file(manifest_path),
        "lines": len(rows), "audio_origin": "VOICE_OVER_NARRATION",
        "mix": "post-render ffmpeg: native ducked to 0.35 under each line, V.O. at unity, video copied",
    }
    write_json(p.agentcut_project, project)
    res.receipts.append(str(placement_path))
    res.details["voice_over"] = {"placement": str(placement_path), "picture": str(mixed), "lines": len(rows)}
    return mixed, []


def _probe_seconds(path: Path) -> float | None:
    probe = subprocess.run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=False)
    try:
        return round(float(probe.stdout.strip()), 6)
    except ValueError:
        return None


def _unit_energy_db(path: Path, hop: float = 0.02) -> list[float] | None:
    """Mono 16 kHz RMS dBFS per ``hop`` seconds of a unit clip's audio (free, local ffmpeg); None on failure."""
    import array
    import math
    run = subprocess.run([_media.require_ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=False)
    if run.returncode != 0 or not run.stdout:
        return None
    pcm = array.array("h")
    pcm.frombytes(run.stdout[:len(run.stdout) // 2 * 2])
    if sys.byteorder != "little":
        pcm.byteswap()
    n = max(1, int(16000 * hop))
    out = []
    for i in range(0, len(pcm) - n + 1, n):
        block = pcm[i:i + n]
        rms = math.sqrt(sum(v * v for v in block) / n) / 32768.0
        out.append(round(20 * math.log10(rms), 2) if rms > 0 else -120.0)
    return out


def _unit_motion_energy(path: Path, width: int = 64, height: int = 112) -> list[float] | None:
    """Per frame pair: mean absolute grey-level difference (0-255) of a ``width`` x ``height`` grey downscale of a unit
    clip (free, local ffmpeg; the craft-standard peak-window trim).  None when the clip cannot be decoded."""
    if not path.is_file():
        return None
    run = subprocess.run([_media.require_ffmpeg(), "-v", "error", "-i", str(path), "-an", "-vf",
                          f"scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=False)
    size = width * height
    if run.returncode != 0 or len(run.stdout) < 2 * size:
        return None
    count = len(run.stdout) // size
    try:
        import numpy as _np_motion  # noqa: PLC0415 -- the engine venv ships numpy
        frames = _np_motion.frombuffer(run.stdout[:count * size], dtype=_np_motion.uint8).reshape(count, size)
        diffs = _np_motion.abs(frames[1:].astype(_np_motion.int16) - frames[:-1].astype(_np_motion.int16))
        return [round(float(v), 4) for v in diffs.mean(axis=1)]
    except ImportError:  # pragma: no cover
        data = run.stdout
        return [round(sum(abs(data[i * size + j] - data[(i - 1) * size + j]) for j in range(size)) / size, 4)
                for i in range(1, count)]


def s7_peak_window_trim(ctx: Ctx, perf: dict[str, Any], contract: dict[str, Any],
                        grouping: dict[str, Any]) -> dict[str, Any]:
    """NALU_CRAFT_STANDARD_v1 S-03/S-05 (line owner 2026-11-17, option A): cut each eligible silent unit of the
    performance-cut plan to its v1 on-screen length around the take's motion peak (tools/performance_cut
    .apply_peak_windows; motion measured here on the unit clip, free).  The unit total never goes below the brief's
    target_seconds x NALU_S7_PEAK_TRIM_RUNTIME_FLOOR_RATIO (0.9); NALU_S7_PEAK_TRIM=off or contract
    ``"s7_peak_trim": "OFF"`` disables it.  Never raises: an error leaves the plan as it was."""
    import performance_cut as _perf
    try:
        enabled = _perf.peak_trim_enabled(contract)
        candidates = _perf.peak_candidates(perf, contract, grouping) if enabled else []
        motion = {c["unit_id"]: _unit_motion_energy(ctx.p.video_media / f"{c['unit_id']}.mp4") for c in candidates}
        brief = read_json(RUNTIME / "briefs" / f"{ctx.episode}_PRODUCTION_BRIEF.json", {}) or {}
        target = float(brief.get("target_seconds") or SCRIPT_DEFAULT_TARGET_SECONDS)
        floor = round(target * _perf.runtime_floor_ratio(), 3)
        return _perf.apply_peak_windows(perf, contract, grouping, motion, runtime_floor_seconds=floor,
                                        enabled=enabled)
    except Exception as exc:  # noqa: BLE001 -- a pacing polish, never a blocker
        return {"status": f"SKIPPED_ERROR:{type(exc).__name__}:{str(exc)[:160]}"}


def s7_dialogue_tail_trim(ctx: Ctx, res: StageResult, contract: dict[str, Any]
                          ) -> tuple[dict[str, Any] | None, Path | None]:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-23): cut each dialogue unit 0.5 s after its last line.

    H3 fills the slot after the line with garbled speech.  The unit ASR runs before the AgentCut
    build here, tools/dialogue_tail_trim.plan decides each unit's kept length, and the build cuts
    there (--dialogue-tail-trim), so render, captions, V.O., BGM and the release timeline all see
    the trimmed timeline.  Returns (unit ASR without the removed segments, report path when any
    unit is cut).  Any other episode returns (None, None) and S7 runs exactly as before.

    The same pass (with word timestamps) plans the dialogue HEAD trim (line owner 2026-10-26, lab E05:
    "Ha!" / "That." / "Closh key" before the scripted line; tools/dialogue_head_trim.py): report
    <EP>_DIALOGUE_HEAD_TRIM.json, ``res.details["dialogue_head_trim"]["apply"]`` is the report path for the
    AgentCut build (--dialogue-head-trim) when any unit is cut, and the returned ASR is shifted to match.
    """
    import camera_grammar_policy as _cgp
    import dialogue_head_trim as _head
    import dialogue_tail_trim as _trim
    if not _cgp.active(contract, episode=ctx.episode):
        return None, None
    p = ctx.p
    asr = transcribe_units(ctx, p.video_media, ctx.episode, words=True)
    write_json(p.assembly / f"{ctx.episode}_unit_asr_untrimmed.json", asr)
    clip_seconds = {mp4.stem: _probe_seconds(mp4) for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
    energy = {mp4.stem: _unit_energy_db(mp4, _trim.ENERGY_HOP)
              for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
    report = _trim.plan(contract, read_json(p.grouping_plan, {}) or {}, asr, clip_seconds,
                        unit_energy={k: v for k, v in energy.items() if v})
    report_path = p.assembly / f"{ctx.episode}_DIALOGUE_TAIL_TRIM.json"
    write_json(report_path, report)
    res.details["dialogue_tail_trim"] = {"report": str(report_path), "trimmed_units": report["trimmed_units"],
                                         "removed_seconds": report["removed_seconds"]}
    head = _head.plan(contract, read_json(p.grouping_plan, {}) or {}, asr, clip_seconds, report)
    head_path = p.assembly / f"{ctx.episode}_DIALOGUE_HEAD_TRIM.json"
    # Cut to the performance (owner 2026-11-02, lab 化神 E01; tools/performance_cut.py): every unit is cut at its
    # head/tail to the scripted performance (unscripted speech, a repeated take, talking in a silent unit removed);
    # the decided in/out points are written into the tail/head reports the build and later S7 steps follow.
    import performance_cut as _perf
    grouping = read_json(p.grouping_plan, {}) or {}
    shot_unit = {str(s): str(u.get("unit_id")) for u in grouping.get("units") or []
                 for s in u.get("editorial_shot_ids") or []}
    vo_seconds: dict[str, list[float]] = {}
    for row in (read_json(voice_over_manifest_path(ctx), {}) or {}).get("rows") or []:
        uid = shot_unit.get(str(row.get("shot_id")))
        if uid and row.get("duration_seconds"):
            vo_seconds.setdefault(uid, []).append(float(row["duration_seconds"]))
    perf = _perf.plan(contract, grouping, asr, clip_seconds, {k: v for k, v in energy.items() if v},
                      report, head, vo_seconds)
    # craft standard v1 (owner 2026-11-17, option A): silent units cut to their v1 length around the motion peak
    peak = s7_peak_window_trim(ctx, perf, contract, grouping)
    # device 1101 E24 (2026-11-23): fragments of H3's own internal cuts (0.25 s / 0.37 s flashes) are trimmed away
    internal = s7_internal_cut_trim(ctx, res, perf, asr)
    perf_path = p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json"
    write_json(perf_path, perf)
    report, head = _perf.merge(report, head, perf)
    write_json(report_path, report)
    write_json(head_path, head)
    res.receipts.append(str(perf_path))
    res.details["performance_cut"] = {
        "report": str(perf_path), "changed_units": perf["changed_units"],
        "before_total_seconds": perf["before_total_seconds"], "after_total_seconds": perf["after_total_seconds"],
        "units": [{k: r.get(k) for k in ("unit_id", "before_in", "before_out", "after_in", "after_out", "reasons")}
                  for r in perf["units"] if r.get("reasons")],
        "warnings": perf["warnings"],
        "peak_trim": {k: peak.get(k) for k in ("status", "candidates", "peak_units", "head_units", "scale",
                                               "removed_seconds", "before_total_seconds", "after_total_seconds")},
        "internal_cut_trim": {k: internal.get(k) for k in ("status", "report", "trimmed_units", "left_fragments",
                                                            "removed_seconds")}}
    if perf["warnings"]:
        res.details.setdefault("warnings", []).extend(perf["warnings"])
    res.details["dialogue_tail_trim"] = {"report": str(report_path), "trimmed_units": report["trimmed_units"],
                                         "removed_seconds": report["removed_seconds"]}
    res.details["dialogue_head_trim"] = {"report": str(head_path), "trimmed_units": head["trimmed_units"],
                                         "removed_seconds": head["removed_seconds"],
                                         "apply": str(head_path) if head["trimmed_units"] else None}
    # source seconds (captions / V.O. / sound bridge / burst mute map them through the clip in-point)
    cut = _perf.windows(report, head, clip_seconds)
    # the tail guard keeps a quarter second after the line even where unscripted speech starts right at its end
    # (owner 2026-11-19): segments starting after the line end stay out of the caption / V.O. timing
    trimmed = _head.strip_words(_trim.trim_unit_asr(_perf.cut_unit_asr(asr, cut, perf), report))
    return trimmed, (report_path if report["trimmed_units"] else None)


def s7_internal_cut_trim(ctx: Ctx, res: StageResult, perf: dict[str, Any], asr: dict[str, Any]) -> dict[str, Any]:
    """Trim fragments of H3's own internal cuts (tools/h3_internal_cut_trim.py; device 1101 E24 2026-11-23): every
    unit clip is scanned with ffmpeg scdet, the performance-cut row keeps the segment with its scripted line (silent:
    its motion peak, else the longest) plus neighbouring designed shots, fragments under the minimum shot at the head
    or tail are cut away.  Units carrying V.O. narration keep their window (the V.O. hold).  Report
    <EP>_H3_INTERNAL_CUT_TRIM.json; NALU_S7_INTERNAL_CUT_TRIM=off disables it.  Free; never raises."""
    import h3_internal_cut_trim as _ict
    report_path = ctx.p.assembly / f"{ctx.episode}_H3_INTERNAL_CUT_TRIM.json"
    if str(os.environ.get("NALU_S7_INTERNAL_CUT_TRIM") or "").strip().lower() in ("0", "off", "false"):
        return {"status": "DISABLED"}
    try:
        ffmpeg = _media.require_ffmpeg()
        clips = {mp4.stem: mp4 for mp4 in sorted(ctx.p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
        cuts, errors = _ict.measure_all(clips, lambda clip: _ict.scene_cuts(clip, ffmpeg=ffmpeg))
        skip = {str(r.get("unit_id")) for r in perf.get("units") or [] if r.get("vo_seconds")}
        report = _ict.apply(perf, cuts, asr, skip_units=skip)
        report.update(episode=ctx.episode, scan_errors=errors, skipped_vo_units=sorted(skip), status="PASS")
        if report["trimmed_units"]:
            perf["changed_units"] = sum(1 for r in perf.get("units") or [] if r.get("changed"))
            perf["after_total_seconds"] = round(sum(float(r["after_out"] or 0) - float(r["after_in"] or 0)
                                                    for r in perf.get("units") or []), 3)
            perf["removed_seconds"] = round(float(perf.get("before_total_seconds") or 0)
                                            - perf["after_total_seconds"], 3)
        write_json(report_path, report)
        res.receipts.append(str(report_path))
        return {"status": "PASS", "report": str(report_path), "trimmed_units": report["trimmed_units"],
                "left_fragments": report["left_fragments"], "removed_seconds": report["removed_seconds"]}
    except Exception as exc:  # noqa: BLE001 -- an edit polish, never a blocker
        write_json(report_path, {"schema": _ict.SCHEMA, "episode": ctx.episode,
                                 "status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"})
        return {"status": f"SKIPPED_ERROR:{type(exc).__name__}", "report": str(report_path)}


def s7_measured_edit_yield_to_performance_cut(ctx: Ctx, res: StageResult, constraints_file: Path | None) -> list[str]:
    """Units without an on-screen scripted line follow the performance cut, not the measured edit.

    The measured-edit constraints are built from the S6 dialogue QA before the performance cut runs,
    and the AgentCut build applies the measured in-point first, so a V.O.-only unit the performance
    cut held for its narration (VO_HOLD) was cut down to the speech heard in it and S7 stopped on
    VOICE_OVER_OVERLAPS_DIALOGUE (E13 VU-010 / VU-013).  Drops those rows from the constraints file
    (kept under ``yielded_to_performance_cut``) and returns the unit ids.  No performance-cut report
    (episode outside CAMERA_GRAMMAR_V1) or no constraints file: nothing changes."""
    perf_path = ctx.p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json"
    if constraints_file is None or not Path(constraints_file).is_file() or not perf_path.is_file():
        return []
    import measured_edit_constraints as _mec  # noqa: PLC0415 - engine tools dir is on sys.path
    payload, dropped = _mec.yield_to_performance_cut(read_json(constraints_file, {}) or {},
                                                     read_json(perf_path, {}) or {})
    if dropped:
        write_json(Path(constraints_file), payload)
        res.details["measured_edit_yielded_to_performance_cut"] = dropped
    return dropped


def s7_push_in_compensation(ctx: Ctx, res: StageResult, contract: dict[str, Any]) -> Path | None:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-26, lab Holmes E06): remove the push-in H3 still adds to
    locked-camera units (tools/push_in_compensation.py).  Each locked unit's largest face is measured on 9 frames
    of the clip as cut (after the dialogue head/tail trims); a monotonic push-in above 25 % gets a time-varying
    face-centred crop of the early frames (end framing kept, crop <= 1.6x, Lanczos, audio copied, duration
    unchanged) written to assembly/push_in_compensation/<unit>.mp4.  Report <EP>_PUSH_IN_COMPENSATION.json; the
    report path is returned for the AgentCut build (--push-in-compensation) when any unit was compensated.
    Free; any failure only skips the step (recorded), never blocks S7."""
    import camera_grammar_policy as _cgp
    import push_in_compensation as _pic
    if not _cgp.active(contract, episode=ctx.episode):
        return None
    p = ctx.p
    report_path = p.assembly / f"{ctx.episode}_PUSH_IN_COMPENSATION.json"
    if not _pic.applies(ctx_render_style(ctx)):  # InsightFace face widths: NOT_APPLICABLE to anime
        write_json(report_path, _pic.not_applicable_report(ctx.episode, ctx_render_style(ctx)))
        res.details["push_in_compensation"] = {"report": str(report_path), "status": "NOT_APPLICABLE"}
        return None
    try:
        clips = {mp4.stem: mp4 for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
        windows = _pic.cut_windows(
            list(clips), {uid: _probe_seconds(path) for uid, path in clips.items()},
            read_json(p.assembly / f"{ctx.episode}_DIALOGUE_TAIL_TRIM.json", {}) or {},
            read_json(p.assembly / f"{ctx.episode}_DIALOGUE_HEAD_TRIM.json", {}) or {})
        ffmpeg, ffprobe = _media.require_ffmpeg(), _media.require_ffprobe()
        app = _pic.face_backend()
        report = _pic.build_report(
            ctx.episode, read_json(p.grouping_plan, {}) or {}, clips, windows, p.assembly / "push_in_compensation",
            measure_fn=lambda clip, times: _pic.measure(clip, times, app, ffmpeg),
            render_fn=lambda clip, out, plan: _pic.render(clip, out, plan, ffmpeg=ffmpeg, ffprobe=ffprobe))
        write_json(report_path, report)
    except Exception as exc:  # noqa: BLE001 -- a polish step, never a blocker
        write_json(report_path, {"schema": _pic.SCHEMA, "episode": ctx.episode,
                                 "status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"})
        res.details["push_in_compensation"] = {"report": str(report_path), "status": "SKIPPED_ERROR"}
        return None
    res.receipts.append(str(report_path))
    res.details["push_in_compensation"] = {"report": str(report_path),
                                           "compensated_units": report["compensated_units"]}
    return report_path if report["compensated_units"] else None


def s7_unit_audio_levelling(ctx: Ctx, res: StageResult, contract: dict[str, Any],
                            unit_asr: dict[str, Any] | None) -> Path | None:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-27, lab Holmes E07: "the sound goes louder/quieter").  Each unit's
    integrated loudness is measured on the clip as cut (dialogue units on their ASR speech windows, other units over
    the whole cut window) and a static gain toward the release role target (native_audio_loudness_contract
    ROLE_TARGETS_LUFS, role as level_native_release_audio.unit_role) is applied, clamped to +-6 dB, with a 4x
    oversampled peak limiter (tools/s7_audio_smoothing.py).  Each levelled unit is a remux in
    assembly/unit_audio_levelling/ (the cut's video stream copied bit-exact + its own levelled audio); the AgentCut
    picture and sound clips both point at it (same in/out).
    Report <EP>_UNIT_AUDIO_LEVELLING.json; its path is returned for the build (--unit-audio-levelling) and the release
    leveller (--pre-levelled-units).  Free; any failure only skips the step (recorded), never blocks S7."""
    import camera_grammar_policy as _cgp
    if not _cgp.active(contract, episode=ctx.episode):
        return None
    import push_in_compensation as _pic
    import s7_audio_smoothing as _smooth
    from level_native_release_audio import unit_role as _unit_role
    from native_audio_loudness_contract import ROLE_TARGETS_LUFS as _targets
    p = ctx.p
    report_path = p.assembly / f"{ctx.episode}_UNIT_AUDIO_LEVELLING.json"
    try:
        clips = {mp4.stem: mp4 for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
        windows = _pic.cut_windows(
            list(clips), {uid: _probe_seconds(path) for uid, path in clips.items()},
            read_json(p.assembly / f"{ctx.episode}_DIALOGUE_TAIL_TRIM.json", {}) or {},
            read_json(p.assembly / f"{ctx.episode}_DIALOGUE_HEAD_TRIM.json", {}) or {})
        grouped = {str(u.get("unit_id")): u for u in (read_json(p.grouped_seedance, {}) or {}).get("units") or []}
        roles = {uid: (_unit_role(grouped[uid]) if uid in grouped else "AMBIENCE") for uid in clips}
        pictures = {uid: Path(str(row["output"])) for uid, row in _pic.applied_sources(
            read_json(p.assembly / f"{ctx.episode}_PUSH_IN_COMPENSATION.json", {}) or {}).items()}
        ffmpeg = _media.require_ffmpeg()
        import performance_cut as _perf  # unit ASR is in source seconds; levelling reads seconds from the in-point
        report = _smooth.build_levelling_report(
            ctx.episode, clips, windows, roles, _perf.shift_to_cut(unit_asr or {}, windows), dict(_targets),
            p.assembly / "unit_audio_levelling",
            measure_fn=lambda clip, spans: _smooth.measure_spans(clip, spans, ffmpeg=ffmpeg),
            render_fn=lambda clip, picture, out, gain: _smooth.render_levelled(clip, picture, out, gain, ffmpeg=ffmpeg),
            pictures=pictures)
        write_json(report_path, report)
    except Exception as exc:  # noqa: BLE001 -- a polish step, never a blocker
        write_json(report_path, {"schema": _smooth.SCHEMA, "episode": ctx.episode,
                                 "status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"})
        res.details["unit_audio_levelling"] = {"report": str(report_path), "status": "SKIPPED_ERROR"}
        return None
    res.receipts.append(str(report_path))
    res.details["unit_audio_levelling"] = {"report": str(report_path), "applied_units": report["applied_units"],
                                           "spread_lufs": report["spread_lufs"]}
    return report_path if report["applied_units"] else None


def s7_dialogue_sound_bridge(ctx: Ctx, res: StageResult, contract: dict[str, Any],
                             unit_asr: dict[str, Any] | None) -> Path | None:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-23): plan the authored L-cuts.

    A silent reaction shot right after a dialogue shot may author
    ``prompt_spec.transition.sound_bridge_from_previous_seconds``; tools/dialogue_sound_bridge.plan
    turns each into a REQUESTED/SKIPPED row, the AgentCut build applies them (--dialogue-sound-bridge)
    and s7_sound_bridge_mix lays the speaker's audio back over the reaction picture.  ``unit_asr`` is
    the tail-trimmed unit ASR (None outside the policy).  Returns the report path when any bridge is
    requested; otherwise nothing is written and S7 runs exactly as before.
    """
    import camera_grammar_policy as _cgp
    import dialogue_sound_bridge as _bridge
    if unit_asr is None or not _cgp.active(contract, episode=ctx.episode):
        return None
    report = _bridge.plan(contract, read_json(ctx.p.grouping_plan, {}) or {}, unit_asr)
    if not report["rows"]:
        return None
    path = ctx.p.assembly / f"{ctx.episode}_DIALOGUE_SOUND_BRIDGE.json"
    write_json(path, report)
    res.details["dialogue_sound_bridge"] = {"report": str(path), "requested": report["requested"],
                                            "skipped": len(report["rows"]) - report["requested"]}
    return path if report["requested"] else None


def s7_leading_burst_mute(ctx: Ctx, res: StageResult, picture: Path,
                          unit_asr: dict[str, Any] | None) -> Path:
    """CAMERA_GRAMMAR_V1 only (line owner 2026-10-23): mute the ~0.1 s vocal burst some H3 units open with.

    tools/dialogue_leading_burst.plan measures each unit clip's first 0.5 s and its ASR; the burst
    window of each flagged unit is muted on the rendered native cut (20/30 ms ramps, video stream
    copied, duration unchanged) BEFORE the L-cut mix, so a bridged speaker line is never touched.
    Report: <EP>_DIALOGUE_LEADING_BURST.json.  ``unit_asr`` is None outside the policy -> picture
    returned untouched; any failure only skips the mute (recorded), never blocks S7."""
    import camera_grammar_policy as _cgp
    import dialogue_leading_burst as _burst
    p = ctx.p
    if unit_asr is None or not _cgp.active(read_json(p.contract, {}) or {}, episode=ctx.episode):
        return picture
    report_path = p.assembly / f"{ctx.episode}_DIALOGUE_LEADING_BURST.json"
    try:
        clips = {mp4.stem: mp4 for mp4 in sorted(p.video_media.glob(f"{ctx.episode}-VU-*.mp4"))}
        report = _burst.plan(clips, unit_asr, ffmpeg=_media.require_ffmpeg())
        windows = _burst.timeline_windows(report, read_json(p.agentcut_project, {}) or {})
        report.update({"episode": ctx.episode, "source_picture": str(picture), "timeline_windows": windows})
        if not windows:
            write_json(report_path, report)
            res.details["dialogue_leading_burst"] = {"report": str(report_path), "muted_units": 0}
            return picture
        out = p.assembly / f"{ctx.episode}_picture_native_burstmute.mp4"
        argv = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture),
                "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", _burst.mix_filter(windows),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(out)]
        run = subprocess.run(argv, capture_output=True, text=True, check=False)
        res.steps.append({"name": "s7_dialogue_leading_burst_mute", "exit_code": run.returncode, "argv": argv,
                          "log": "in-process ffmpeg", "stderr_tail": tail(run.stderr)})
        if run.returncode != 0 or not out.is_file() or _video_stream_hash(picture) != _video_stream_hash(out):
            out.unlink(missing_ok=True)
            report["status"] = "SKIPPED_MIX_FAILED"
            write_json(report_path, report)
            res.details["dialogue_leading_burst"] = {"report": str(report_path), "status": report["status"]}
            return picture
        report.update({"status": "APPLIED", "output_picture": str(out), "output_picture_sha256": sha256_file(out),
                       "video_stream_bit_exact": True})
        write_json(report_path, report)
    except Exception as exc:  # noqa: BLE001 -- the mute is a polish step, never a blocker
        write_json(report_path, {"schema": _burst.SCHEMA, "episode": ctx.episode,
                                 "status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"})
        res.details["dialogue_leading_burst"] = {"report": str(report_path), "status": "SKIPPED_ERROR"}
        return picture
    res.receipts.append(str(report_path))
    res.details["dialogue_leading_burst"] = {"report": str(report_path), "muted_units": len(windows),
                                             "picture": str(out)}
    return out


def s7_silent_unit_stray_speech_mute(ctx: Ctx, res: StageResult, picture: Path) -> Path:
    """Stray voices in silent units muted (fleet 2026-11-13; device 1101 E24 2026-11-23: voices in
    five silent shots shipped because S6 whisper had dropped them), on the rendered native cut, BEFORE the L-cut and
    V.O. mixes so a bridged speaker line or narration is never touched.

    Every audio clip of the AgentCut project whose unit carries no on-screen scripted line (s7_speaking_units) is
    measured where it is placed (source, in-point, duration) with a VAD (tools/silent_unit_stray_speech.py) and each
    VAD speech window is muted; the rest keeps its full band (foley).  NALU_S7_SILENT_UNIT_AUDIO=ambience also plays
    the whole unit with the speech band removed; =off restores the untouched native cut.  30 ms ramps; video stream
    copied, duration unchanged.  Every episode.  Report <EP>_SILENT_UNIT_STRAY_SPEECH.json; any failure only skips the step (recorded),
    never blocks S7."""
    import silent_unit_stray_speech as _stray
    p = ctx.p
    report_path = p.assembly / f"{ctx.episode}_SILENT_UNIT_STRAY_SPEECH.json"
    try:
        ffmpeg = _media.require_ffmpeg()
        speaking = s7_speaking_units(ctx) if (p.contract.is_file() or (
            p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json").is_file()) else None
        report = _stray.plan(read_json(p.agentcut_project, {}) or {},
                             lambda src, a, d: _stray.measure_placed(src, a, d, ffmpeg=ffmpeg),
                             speaking_units=speaking)
        report.update({"episode": ctx.episode, "source_picture": str(picture)})
        if not report["ambience_windows"] and not report["mute_windows"]:
            write_json(report_path, report)
            res.details["silent_unit_stray_speech"] = {"report": str(report_path), "muted_units": 0,
                                                       "ambience_units": 0}
            return picture
        out = p.assembly / f"{ctx.episode}_picture_native_straymute.mp4"
        argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture),
                "-filter_complex", _stray.ambience_filter_complex(report["mute_windows"], report["ambience_windows"]),
                "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(out)]
        run = subprocess.run(argv, capture_output=True, text=True, check=False)
        res.steps.append({"name": "s7_silent_unit_stray_speech_mute", "exit_code": run.returncode, "argv": argv,
                          "log": "in-process ffmpeg", "stderr_tail": tail(run.stderr)})
        if run.returncode != 0 or not out.is_file() or _video_stream_hash(picture) != _video_stream_hash(out):
            out.unlink(missing_ok=True)
            report["status"] = "SKIPPED_MIX_FAILED"
            write_json(report_path, report)
            res.details["silent_unit_stray_speech"] = {"report": str(report_path), "status": report["status"]}
            return picture
        report.update({"status": "APPLIED", "output_picture": str(out), "output_picture_sha256": sha256_file(out),
                       "video_stream_bit_exact": True})
        write_json(report_path, report)
    except Exception as exc:  # noqa: BLE001 -- the mute is a polish step, never a blocker
        write_json(report_path, {"schema": _stray.SCHEMA, "episode": ctx.episode,
                                 "status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"})
        res.details["silent_unit_stray_speech"] = {"report": str(report_path), "status": "SKIPPED_ERROR"}
        return picture
    res.receipts.append(str(report_path))
    res.details["silent_unit_stray_speech"] = {"report": str(report_path), "muted_units": report["muted_units"],
                                               "flagged_units": report["flagged_units"],
                                               "ambience_units": report["ambience_units"], "picture": str(out)}
    return out


def s7_sound_bridge_mix(ctx: Ctx, res: StageResult, picture: Path) -> tuple[Path, list[str]]:
    """Mix each applied L-cut's speaker audio over the reaction picture (native ducked); video copied.

    Reads the bridges the AgentCut build recorded (metadata.dialogue_sound_bridge); none -> the
    picture is returned untouched.  The applied rows and the mix are written back into the S7 report
    <EP>_DIALOGUE_SOUND_BRIDGE.json.  Returns (picture, blockers).
    """
    import dialogue_sound_bridge as _bridge
    p = ctx.p
    meta = ((read_json(p.agentcut_project, {}) or {}).get("metadata") or {}).get("dialogue_sound_bridge") or {}
    bridges = [row for row in meta.get("bridges") or [] if row.get("status") == "APPLIED"]
    if not bridges:
        return picture, []
    mixed = p.assembly / f"{ctx.episode}_picture_native_lcut.mp4"
    argv = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(picture)]
    for row in bridges:
        argv += ["-i", str(row["audio_source"])]
    argv += ["-filter_complex", _bridge.mix_filter(bridges),
             "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(mixed)]
    run = subprocess.run(argv, capture_output=True, text=True, check=False)
    res.steps.append({"name": "s7_dialogue_sound_bridge_mix", "exit_code": run.returncode, "argv": argv,
                      "log": "in-process ffmpeg", "stderr_tail": tail(run.stderr)})
    if run.returncode != 0 or not mixed.is_file():
        return picture, [f"DIALOGUE_SOUND_BRIDGE_MIX_FAILED:{(run.stderr or '')[-200:]}"]
    if _video_stream_hash(picture) != _video_stream_hash(mixed):
        mixed.unlink(missing_ok=True)
        return picture, ["DIALOGUE_SOUND_BRIDGE_MIX_CHANGED_VIDEO_STREAM"]
    report_path = Path(str(meta.get("report") or p.assembly / f"{ctx.episode}_DIALOGUE_SOUND_BRIDGE.json"))
    report = read_json(report_path, {}) or {}
    report.update({"applied": meta.get("bridges") or [], "applied_count": len(bridges),
                   "mix": {"source_picture": str(picture), "output_picture": str(mixed),
                           "output_picture_sha256": sha256_file(mixed), "video_stream_bit_exact": True,
                           "native_duck_db": _bridge.DUCK_DB, "fade_seconds": _bridge.FADE_SECONDS}})
    write_json(report_path, report)
    res.receipts.append(str(report_path))
    res.details["dialogue_sound_bridge"] = {**(res.details.get("dialogue_sound_bridge") or {}),
                                            "applied": len(bridges), "picture": str(mixed)}
    return mixed, []


def stage_s7(ctx: Ctx) -> StageResult:
    """S7 with the final fix round (line owner 2026-11-20): the round's FREE settings are applied to every S7 pass of
    the episode; free fixes re-run S7 once in this process; units parked for a paid redo stop S7 until S6 landed
    them (``paid_stage.sh <EP> S6 S8``).  See :func:`s7_final_fix_round`."""
    import final_fix_round as _ffr
    pending = final_fix_redo_pending(ctx)
    if pending:
        res = StageResult(BLOCKED)
        res.blockers = [f"FINAL_FIX_ROUND_S6_REDO_PENDING:{','.join(pending)}"]
        res.details = {"final_fix_round": {"action": "S6_REDO_PENDING", "units": pending,
                                           **_ffr.summary(read_json(final_fix_record_path(ctx), {}) or {}),
                                           "next": f"{RT_TOOLS / 'paid_stage.sh'} {ctx.episode} S6 S8"}}
        ctx.say(f"   S7 waits for the final-fix S6 redo of {', '.join(pending)}: run "
                f"{RT_TOOLS / 'paid_stage.sh'} {ctx.episode} S6 S8")
        return res
    with _final_fix_env(ctx) as applied:
        res = _stage_s7_pass(ctx)
    if applied:
        res.details["final_fix_s7_settings"] = applied
    fix = (res.details or {}).get("final_fix_round") or {}
    if fix.get("action") == "S7_RERUN" and not getattr(ctx, "_final_fix_rerun", False):
        ctx._final_fix_rerun = True
        ctx.say("-- S7: re-running assembly once with the final fix round's free fixes")
        first = res
        with _final_fix_env(ctx) as applied:
            res = _stage_s7_pass(ctx)
        res.steps = list(first.steps) + list(res.steps)
        res.details["final_fix_round_first_pass"] = {"status": first.status, "blockers": first.blockers,
                                                     "final_fix_round": fix}
        if applied:
            res.details["final_fix_s7_settings"] = applied
    elif fix.get("action") == "PROCEED" and not getattr(ctx, "_final_fix_rerun", False) \
            and s7_text_removal_due_after_round(ctx, res):
        # the round settled without a paid redo for a unit that was waiting for it: the local burned-text removal
        # (last resort) is due now -- one more assembly pass, like the round's own free-fix re-run
        ctx._final_fix_rerun = True
        ctx._text_removal_rerun = True
        ctx.say("-- S7: re-running assembly once: the final fix round settled, local burned-text removal is due")
        first = res
        with _final_fix_env(ctx) as applied:
            res = _stage_s7_pass(ctx)
        res.steps = list(first.steps) + list(res.steps)
        res.details["text_removal_first_pass"] = {"status": first.status, "blockers": first.blockers,
                                                  "text_removal": (first.details or {}).get("text_removal")}
        if applied:
            res.details["final_fix_s7_settings"] = applied
    return res


def s7_text_removal_due_after_round(ctx: Any, res: Any) -> bool:
    """True when this S7 pass left a unit waiting for the final fix round (AWAITING_FINAL_FIX_ROUND) and, with the
    round now settled, the plan makes it a removal target.  Never raises."""
    try:
        import burned_text_removal as _btr
        if not _btr.enabled() or getattr(ctx, "dry", False):
            return False
        waiting = {r.get("unit_id") for r in ((res.details or {}).get("text_removal") or {}).get("skipped") or []
                   if r.get("reason") == "AWAITING_FINAL_FIX_ROUND"}
        if not waiting:
            return False
        targets, _ = s7_text_removal_plan(ctx)
        return any(t["unit_id"] in waiting for t in targets)
    except Exception:  # noqa: BLE001
        return False


def _stage_s7_pass(ctx: Ctx) -> StageResult:
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

    # -------------------------------------------------------- 2. measured edit constraints (opt-in per episode)
    import sys
    sys.path.insert(0, str(ENGINE / "tools"))
    from measured_edit_policy import active_for, get_policy_params
    import s7_edit_invariants as _s7_inv

    constraints_file = None
    if active_for(ctx.episode, line="nalu"):
        params = get_policy_params(ctx.episode, line="nalu")
        evidence_dir = p.assembly / "asr_evidence"
        constraints_file = p.assembly / f"{ctx.episode}_MEASURED_EDIT_CONSTRAINTS.json"

        build_constraints_argv = [
            VENV, BUILD_MEASURED_EDIT_CONSTRAINTS,
            "--episode", ctx.episode,
            "--postgen-dir", p.postgen_dir,
            "--video-media", p.video_media,
            "--grouping-plan", p.grouping_plan,
            "--out-constraints", constraints_file,
            "--out-evidence-dir", evidence_dir,
            # S7 edit invariant 1 (owner 2026-11-21, E21 lines cut off): the measured interval is built from S6 QA
            # SEGMENT ends, which run early on the final syllable -- never less than the sentence-end tail after
            # them, never less than the head lead before the first word
            "--lead-seconds", str(max(float(params.get("lead_seconds", 0.08)), _s7_inv.HEAD_LEAD_SECONDS)),
            "--trail-seconds", str(max(float(params.get("trail_seconds", 0.12)), _s7_inv.SENTENCE_TAIL_SECONDS)),
        ]

        log_path = LOG_ROOT / ctx.episode / "s7_build_measured_edit_constraints.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            cc = subprocess.run(build_constraints_argv, stdout=log, stderr=subprocess.STDOUT, text=True)
            if cc.returncode != 0:
                res.blockers = [f"MEASURED_EDIT_CONSTRAINTS_BUILD_FAILED:see {log_path}"]
                res.steps.append({
                    "name": "build_measured_edit_constraints",
                    "status": "FAIL",
                    "log": str(log_path),
                })
                return res

        res.steps.append({
            "name": "build_measured_edit_constraints",
            "status": "PASS",
            "constraints_file": str(constraints_file),
            "log": str(log_path),
        })

    # -------------------------------------------------------- 3. the chain argv
    s7_bgm = s7_bgm_contract(ctx)
    res.details["bgm_default"] = s7_bgm
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
        "--output-video", p.final_candidate,
        "--expected-slots", expected_slots,
        # required: audio_profile_binding classifies audio_contract.bgm and stamps
        # the contract's sha into the project (NONE -> NATIVE_MULTIMODAL_NO_EXTERNAL_BGM).  BGM default ON:
        # NO_BGM/omitted -> the derived default-cue contract (SELECTIVE) once S6 generated its sources.
        "--generation-contract", s7_bgm["contract"]]

    if constraints_file and constraints_file.is_file():
        build_argv += ["--measured-edit-constraints", constraints_file]

    render_dry_argv = [VENV, ENGINE / "tools/render_portable_timeline.py",
                       p.agentcut_project, "--output", p.picture_native, "--dry-run"]
    render_argv = [VENV, ENGINE / "tools/render_portable_timeline.py",
                   p.agentcut_project, "--output", p.picture_native]
    release_timeline = p.assembly / f"{ctx.episode}_release_timeline.json"
    level_argv: list[Any] = [VENV, ENGINE / "tools/level_native_release_audio.py",
                             "--source", p.picture_native,
                             "--timeline", release_timeline,
                             "--grouped", p.grouped_seedance,
                             "--output", p.final_levelled,
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
        "--video", p.final_candidate,
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
                  f"promote {p.final_candidate.name} -> {p.final_mp4} only on full S7 PASS (Roger 2026-10-30 item 0)",
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
        "final_candidate": str(p.final_candidate),
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

    # ------------------------------------------- 3b. dialogue tail trim (CAMERA_GRAMMAR_V1 only)
    try:
        trimmed_asr, tail_trim = s7_dialogue_tail_trim(ctx, res, read_json(p.contract, {}) or {})
    except Exception as exc:  # noqa: BLE001
        res.blockers = [f"SUBTITLE_ASR_FAILED:{type(exc).__name__}:{exc}"]
        return res
    if trimmed_asr is not None:  # the performance cut ran: silent / V.O.-only units follow it alone
        s7_measured_edit_yield_to_performance_cut(ctx, res, constraints_file)
    if tail_trim is not None:
        build_argv += ["--dialogue-tail-trim", tail_trim]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    head_trim = (res.details.get("dialogue_head_trim") or {}).get("apply")
    if head_trim:
        build_argv += ["--dialogue-head-trim", head_trim]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    # 3c. push-in compensation (CAMERA_GRAMMAR_V1 locked-camera units; measured on the trimmed cut, never blocks)
    push_in = s7_push_in_compensation(ctx, res, read_json(p.contract, {}) or {})
    if push_in is not None:
        build_argv += ["--push-in-compensation", push_in]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    sound_bridge = s7_dialogue_sound_bridge(ctx, res, read_json(p.contract, {}) or {}, trimmed_asr)
    if sound_bridge is not None:
        build_argv += ["--dialogue-sound-bridge", sound_bridge]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    # 3d. per-unit native-audio levelling + equal-power cut crossfades (CAMERA_GRAMMAR_V1; free, never blocks)
    unit_levelling = s7_unit_audio_levelling(ctx, res, read_json(p.contract, {}) or {}, trimmed_asr)
    if unit_levelling is not None:
        build_argv += ["--unit-audio-levelling", unit_levelling]
        level_argv = level_argv[:-2] + ["--pre-levelled-units", unit_levelling] + level_argv[-2:]
    # 3d'. camera motion: measure every unit clip, lock-off / smooth the dialogue units that are not locked
    # (Roger 2026-10-30 E12 item 2; free, derived clips with bit-exact audio).  The gate itself runs on the
    # finished candidate (6c) so a FAIL binds to the candidate sha like every other S7 gate.
    stabilized_summary = s7_camera_stabilize(ctx, res)
    if stabilized_summary is not None:
        build_argv += ["--stabilized-clips", stabilized_summary]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    # 3e. editorial unit re-cut (Roger 2026-10-30 E12 item 3; authored plan, free, derived clips).  A plan
    # that fails to render BLOCKS: an authored cut list that cannot be honoured is not something to skip.
    recut_report, recut_blockers = s7_unit_recut(ctx, res)
    if recut_blockers:
        res.blockers = recut_blockers
        return res
    if recut_report is not None:
        build_argv += ["--unit-recut", recut_report]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    # 3f. local burned-text removal (line owner 2026-11-23): the last resort for units whose burned line survived
    # every paid redo and was not accepted as the correct line -- CPU only, bounded, never blocks
    try:
        text_removal = s7_burned_text_removal(ctx, res, {"unit_recut": recut_report, "stabilized": stabilized_summary,
                                                         "push_in": push_in, "levelling": unit_levelling})
    except Exception as exc:  # noqa: BLE001 - the original pictures are used
        text_removal = None
        res.details.setdefault("warnings", []).append(f"TEXT_REMOVAL_FAILED:{type(exc).__name__}")
    if text_removal is not None:
        build_argv += ["--text-removal", text_removal]
        res.details["commands"]["build_agentcut"] = q(build_argv)
    import camera_grammar_policy as _cgp_xf
    if _cgp_xf.active(read_json(p.contract, {}) or {}, episode=ctx.episode):
        import s7_audio_smoothing as _smooth_xf
        build_argv += ["--audio-cut-crossfade-seconds", f"{s7_cut_crossfade_seconds(_smooth_xf.CUT_CROSSFADE_S):g}"]
    res.details["commands"]["build_agentcut"] = q(build_argv)
    res.details["commands"]["level_native_release_audio"] = q(level_argv)

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
        asr = trimmed_asr if trimmed_asr is not None else transcribe_units(ctx, p.video_media, ctx.episode)
        if recut_report is not None:
            # re-cut units are derived clips (in=0): their lines are timed on the derived clip, not the source
            applied = (res.details.get("unit_recut") or {}).get("applied") or []
            derived_asr = transcribe_units(ctx, p.video_media / "_recut", ctx.episode)
            asr = dict(asr)
            for uid in applied:
                if uid in derived_asr:
                    asr[uid] = derived_asr[uid]
            res.details["unit_recut"]["derived_asr_units"] = [u for u in applied if u in derived_asr]
        write_json(asr_json, asr)
    except Exception as exc:  # noqa: BLE001
        res.steps.extend(steps)
        res.blockers = [f"SUBTITLE_ASR_FAILED:{type(exc).__name__}:{exc}"]
        return res
    # 5a'. V.O. narration (VOICE_ONLY_NO_PLATE lines, S4 wavs): placed on the native cut, native audio
    # ducked under it, mixed in with the video stream copied — after the render, BEFORE the captions,
    # so the captions, end card, BGM, dips and release levelling all see the narrated picture.
    # Order: native cut -> V.O. mix -> subtitles -> end card -> BGM -> cut dips -> release levelling.
    # 5a. L-cuts (CAMERA_GRAMMAR_V1, authored sound bridges): the speaker's line plays on over the
    # reaction picture; no applied bridge -> the native picture continues unchanged.
    # 5a0. leading vocal burst (CAMERA_GRAMMAR_V1): muted on the native cut before the L-cut mix.
    # 5a00. silent units: VAD-measured stray voices muted (every episode) before the L-cut mix.
    native_source, bridge_blockers = s7_sound_bridge_mix(
        ctx, res, s7_silent_unit_stray_speech_mute(
            ctx, res, s7_leading_burst_mute(ctx, res, p.picture_native, trimmed_asr)))
    if bridge_blockers:
        res.steps.extend(steps)
        res.blockers = bridge_blockers
        return res
    captioned_source, vo_blockers = s7_voice_over(ctx, res, native_source, asr)
    if vo_blockers:
        res.steps.extend(steps)
        res.blockers = vo_blockers
        return res
    vo_placement = voice_over_placement_path(ctx)
    vo_argv: list[Any] = (["--voice-over-placement", vo_placement]
                          if captioned_source != native_source and vo_placement.is_file() else [])
    # CAMERA_GRAMMAR_V1 (lab E02 VU-001): a line too long for 2 normal-size rows becomes sequential cues
    import camera_grammar_policy as _cgp
    # final fix round (owner 2026-11-20): a confirmed bad caption wrap turns the splitter on for any episode
    split_argv: list[Any] = (["--split-long-captions"]
                             if _cgp.active(read_json(p.contract, {}) or {}, episode=ctx.episode)
                             or str(os.environ.get("NALU_S7_SPLIT_LONG_CAPTIONS") or "").strip().lower()
                             in ("1", "true", "on") else [])
    # H3_BURNED_TEXT_COVER_V1 (line owner 2026-10-31, E12): H3 burns the spoken line into the picture; OCR the
    # band, then the captions sit on a bar over it and the bar also covers every burned-text run.
    import burned_text_cover as _btc
    cover_argv: list[Any] = []
    if _btc.active(read_json(p.contract, {}) or {}, episode=ctx.episode, config=getattr(ctx, "config", None)):
        cover_json = p.assembly / f"{ctx.episode}_H3_BURNED_TEXT_INTERVALS.json"
        scan_step = ctx.run([VENV, ENGINE / "tools/burned_text_cover.py", "scan", captioned_source,
                             "--episode", ctx.episode, "--contract", p.contract, "--out", cover_json],
                            name="s7_burned_text_scan")
        steps.append(scan_step)
        if scan_step["exit_code"] != 0 or not cover_json.is_file():
            res.steps.extend(steps)
            res.blockers = ["H3_BURNED_TEXT_SCAN_FAILED"]
            return res
        cover_argv = ["--cover-band", "--cover-intervals", cover_json]
        # owner 2026-11-19: boxes over the area cap / on a face are not blurred; recorded for review, never a stop
        flagged = (read_json(cover_json, {}) or {}).get("flagged_for_review") or []
        if flagged:
            res.details["burned_text_cover_flagged_for_review"] = flagged
            res.details.setdefault("warnings", []).append(
                f"H3_BURNED_TEXT_FLAGGED_FOR_REVIEW:{len(flagged)} burned-text box(es) left unblurred "
                "(over the area cap or on a face); see " + str(cover_json))
    # an UNRESOLVED S6 burn in our subtitle band: that unit's captions go above the burned line (free, 2026-11-21)
    try:
        avoid_bands = s7_residual_burn_bands(ctx)
    except Exception as exc:  # noqa: BLE001 - advisory placement: captions stay where they were
        avoid_bands = None
        res.details.setdefault("warnings", []).append(f"S6_RESIDUAL_BURN_BANDS_UNREADABLE:{type(exc).__name__}")
    # a unit cleaned by the local text removal (3f) has no burned line left to avoid
    avoid_bands = s7_text_removal_drop_bands(avoid_bands, text_removal)
    avoid_argv: list[Any] = ["--avoid-bands", avoid_bands] if avoid_bands is not None else []
    sub_step = ctx.run([VENV, RT_TOOLS / "build_burnin_subtitles.py", "--episode", ctx.episode,
                        "--project", p.agentcut_project, "--asr", asr_json, "--contract", p.contract,
                        "--grouping", p.grouping_plan, "--source", captioned_source,
                        "--out-ass", subtitles_ass_path(ctx), "--out-video", subbed,
                        "--out-report", p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json",
                        "--language", ctx_language(ctx), *vo_argv, *split_argv, *cover_argv, *avoid_argv,
                        *(["--unit-recut", recut_report] if recut_report is not None else [])],
                       name="s7_burnin_subtitles")
    steps.append(sub_step)
    if sub_step["exit_code"] != 0 or not subbed.is_file():
        res.steps.extend(steps)
        res.blockers = ["SUBTITLE_BURNIN_FAILED"]
        return res
    if cover_argv:
        cover_check = p.assembly / f"{ctx.episode}_H3_BURNED_TEXT_COVER_CHECK.json"
        verify_step = ctx.run([VENV, ENGINE / "tools/burned_text_cover.py", "verify", subbed,
                               "--episode", ctx.episode,
                               "--captions", p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json",
                               "--intervals", cover_json, "--out", cover_check], name="s7_burned_text_verify")
        steps.append(verify_step)
        res.details["burned_text_cover"] = read_json(cover_check, {}) or {}
        if verify_step["exit_code"] != 0 and s7_burned_text_cover_acceptance(
                ctx, res, subbed, cover_check, verify_step) is None:
            res.steps.extend(steps)
            res.blockers = ["H3_BURNED_TEXT_STILL_VISIBLE"]
            return res
    res.details["subtitles"] = {"picture": str(subbed), "report": str(p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json")}
    # the strict burned-line decisions (owner 2026-11-23): our cue is suppressed only on ACCEPT_CORRECT
    checks = s7_burned_line_summary(ctx, p.assembly / f"{ctx.episode}_BURNIN_SUBTITLES.json")
    if checks:
        res.details["subtitles"]["burned_line_checks"] = checks
    # 5b'. opening title (line owner 2026-10-22: every episode needs a proper opening).  Free overlay of
    # the brief's series title + episode line on the first 2.5 s; no added duration, audio stream copy.
    # A missing brief title / font or an ffmpeg failure only skips it (recorded) and never blocks S7.
    subbed = s7_opening_title(ctx, res, subbed)
    # 5c. studio end card (Roger 2026-09-13): append nalu_runtime/brand/NALU_MOTION_endcard_3s_9x16.mp4
    # CAMERA_GRAMMAR_V1: this episode's own card when it renders; otherwise the global brand card.
    endcard = (s7_episode_endcard(ctx, res)
               or Path(f"{_np.RUNTIME_ROOT}/brand/NALU_MOTION_endcard_3s_9x16.mp4"))
    outro_seconds = 0.0
    if not endcard.is_file():
        res.steps.extend(steps)
        res.blockers = [f"REQUIRED_BRAND_OUTRO_ASSET_MISSING:{endcard}"]
        return res
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
        bgm_common = selective_bgm_common_argv(ctx, Path(s7_bgm["contract"]))
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
        # S7 normally runs without the key (env -u GIGGLE_API_KEY): reuse S6's PASS reconciliation then.
        if os.environ.get("GIGGLE_API_KEY") or not bgm_credit_reconciled(ctx):
            if not os.environ.get("GIGGLE_API_KEY"):
                res.steps.extend(steps)
                res.blockers = ["SELECTIVE_BGM_CREDIT_RECONCILIATION_NEEDS_KEY"]
                res.details["hint"] = ("S6 could not reconcile the music charge yet; rerun S7 with the key via "
                                       f"./lines/nalu/runtime/tools/paid_stage.sh {ctx.episode} S7 S7 "
                                       "(S7 has no provider POST route; the key is used for the read-only "
                                       "statement query only).")
                return res
            rec_step = ctx.run([VENV, SELECTIVE_BGM, "reconcile", *bgm_common], name="s7_bgm_reconcile_read_only", paid=True)
        else:
            rec_step = {"name": "s7_bgm_reconcile_read_only", "exit_code": 0, "reused": "S6_RECONCILIATION_PASS"}
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
    # 5e. cut-point audio continuity (W1 wiring).  Roger 2026-10-18: E65's published
    # repair removed wrong dialogue by silencing 1:10-1:14 / 1:25-1:28 / 1:52-1:55,
    # leaving the room sound broken at those cuts.  The dip never mutes and never
    # changes duration: at each unit boundary the same single audio stream is
    # lowered into the cut and restored out of it, so the space keeps one
    # continuous bed.  Off per episode unless the policy opts in; a failure here
    # blocks the assembly because a silent patch is worse than no dip at all.
    audio_continuity = None
    try:
        import assembly_audio_continuity_policy as _aac
    except ModuleNotFoundError:
        _aac = None
    if _aac is not None:
        contract_payload = read_json(p.contract, {}) or {}
        audio_continuity = {"status": "NOT_ENABLED"}
        if _aac.active_for(ctx.episode, contract=contract_payload):
            timeline_payload = read_json(release_timeline, {}) or {}
            boundaries = _aac.boundaries_from_release_timeline(timeline_payload)
            dipped = p.assembly / f"{ctx.episode}_picture_native_audio_continuous.mp4"
            try:
                import audio_cut_overlap as _cut
                report = _cut.apply_cut_point_dips(
                    subbed, boundaries, _aac.crossfade_seconds(), dipped)
            except Exception as exc:  # noqa: BLE001
                res.steps.extend(steps)
                res.blockers = [f"CUT_POINT_AUDIO_CONTINUITY_FAILED:{type(exc).__name__}:{exc}"]
                return res
            subbed = dipped
            audio_continuity = {"status": "PASS", "output": str(dipped),
                                "boundaries": len(boundaries), **report}
        res.details["cut_point_audio_continuity"] = audio_continuity
        if audio_continuity.get("status") == "PASS":
            step = {"name": "s7_cut_point_audio_continuity", "exit_code": 0,
                    "status": "PASS", "boundaries": audio_continuity["boundaries"],
                    "log": "in-process (audio_cut_overlap.apply_cut_point_dips)"}
            steps.append(step)
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
         "--unit-asr", p.assembly / f"{ctx.episode}_unit_asr.json", "--asr-windows-out", asr_windows_pre,
         *(["--performance-cut", p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json"]
           if (p.assembly / f"{ctx.episode}_PERFORMANCE_CUT.json").is_file() else []),
         *vo_argv],
        name="s7_build_final_cut_speaker_map"))
    # 5e'. voice pitch unify on the mixed, unlevelled picture (Roger 2026-10-30 1c; F4: before the leveller)
    _pre_level_source = Path(str(level_argv[level_argv.index("--source") + 1])) if "--source" in level_argv else p.picture_native
    pitch_out, pitch_blockers = s7_voice_pitch_unify(ctx, res, steps, _pre_level_source)
    if pitch_blockers:
        res.steps.extend(steps)
        res.blockers = pitch_blockers
        return res
    line_windows_for_level = asr_windows_pre
    if pitch_out is not None:
        level_argv[level_argv.index("--source") + 1] = pitch_out
        level_argv[-1] = sha256_file(pitch_out)
        _pw = (res.details.get("voice_pitch_unify") or {}).get("windows")
        if _pw and Path(str(_pw)).is_file():
            line_windows_for_level = Path(str(_pw))     # windows rebuilt on the cut, unit-bounded (F4)
    if Path(str(line_windows_for_level)).is_file():
        level_argv = level_argv[:-2] + ["--line-windows", line_windows_for_level] + level_argv[-2:]
    if vo_argv:
        level_argv = level_argv[:-2] + vo_argv + level_argv[-2:]
    res.details["commands"]["level_native_release_audio"] = q(level_argv)
    _lvl_source = level_argv[level_argv.index("--source") + 1] if "--source" in level_argv else p.picture_native
    reused_level = _reusable_release_level(p, _lvl_source)
    if reused_level:
        # Idempotent re-entry: the leveller refuses to overwrite its immutable output/QA, so a
        # re-run of S7 (e.g. after an audience-detector order) used to dead-end here even though
        # the release is unchanged.  Reuse only when the recorded report PASSed and the current
        # source picture stream is byte-for-byte the one it was levelled from (E10, 2026-10-02).
        res.details["release_audio_level_reused"] = reused_level
        steps.append({"name": "s7_level_native_release_audio", "reused": reused_level,
                      "exit_code": 0 if str(reused_level.get("status") or "").startswith("PASS") else 1})
    else:
        # The picture changed (re-cut / stabilised / re-rendered): the previous levelled file and its QA
        # are evidence of a cut that no longer exists.  Park them under their sha (never deleted) so the
        # leveller can write the new evidence at the same, state-tracked paths (Roger 2026-10-30 repair).
        parked = _park_superseded(p.final_levelled, p.leveled_audio_report)
        if parked:
            res.details["release_audio_level_superseded"] = parked
        steps.append(ctx.run(level_argv, name="s7_level_native_release_audio"))
    res.receipts.append(str(p.leveled_audio_report))
    if steps[-1]["exit_code"] != 0 or not p.final_levelled.is_file():
        # The measurement stays honest (leveled_audio_report keeps its real FAIL and
        # failures list); the stage may continue only on an explicit, source-receipted
        # line-owner order bound to this exact final-cut SHA — same shape as the
        # FINAL-CUT-AUDIENCE-DETECTORS acceptance a few steps below.
        level_report = read_json(p.leveled_audio_report, {}) or {}
        failing = list(level_report.get("failures") or [])
        final_sha = sha256_file(p.final_levelled) if p.final_levelled.is_file() else None
        order, match = s7_release_loudness_acceptance(ctx, p, failing, final_sha)
        # which S7 path produced this levelled file: the acceptance is looked up on both, the same way
        match["s7_path"] = ("REUSED_LEVELLED_FILE" if reused_level else
                            "RELEVELLED" + (" (previous levelled file parked)" if res.details.get(
                                "release_audio_level_superseded") else ""))
        match["level_step_exit_code"] = steps[-1].get("exit_code")
        if getattr(ctx, "_final_fix_rerun", False):
            match["s7_pass"] = "FINAL_FIX_ROUND_S7_RERUN"
        res.details["release_audio_loudness_acceptance_lookup"] = match
        if order is None:
            res.steps.extend(steps)
            res.blockers = ["RELEASE_AUDIO_LEVELLING_FAILED"]
            res.details["missing_input"] = str(p.final_levelled)
            res.details["hint"] = (f"release levelling FAIL not carried: {match.get('reason')} "
                                   f"[{match['s7_path']}] -- see details.release_audio_loudness_acceptance_lookup "
                                   "(candidates = why each order was refused; record_hint = the order that "
                                   "would match).")
            ctx.say(f"   !! RELEASE_AUDIO_LEVELLING_FAILED: {match.get('reason')} [{match['s7_path']}]")
            return res
        bound_sha = match.get("bound_sha256") or final_sha
        record = _rga.acceptance_record(order, episode=ctx.episode, gate_id=RELEASE_LOUDNESS_GATE_ID,
                                        failing=failing, media_sha256=bound_sha,
                                        media_item_id=match.get("media_item_id"),
                                        gate_result_path=str(p.leveled_audio_report))
        if match.get("rule") == "RECORDED_DRIFT_SAME_PICTURE":
            record.update(media_sha256=final_sha, binding_drift={
                k: match.get(k) for k in ("rule", "bound_sha256", "bound_report", "source_video_stream_sha256",
                                          "failure_identities")})
        acceptance_path = p.assembly / "final_qa" / f"{ctx.episode}_RELEASE_AUDIO_LOUDNESS_ACCEPTANCE.json"
        acceptance_path.parent.mkdir(parents=True, exist_ok=True)
        acceptance_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        steps[-1]["accepted_by_line_owner_order"] = order.get("seq")
        res.details["release_audio_loudness_acceptance"] = {**record, "record_path": str(acceptance_path)}
        res.receipts.append(str(acceptance_path))
        ctx.say(f"   !! RELEASE_AUDIO_LEVELLING stays FAIL ({', '.join(failing)}); continuing on line-owner order "
                f"seq={order.get('seq')} {order.get('order')!s:.40} -> {acceptance_path.name}")

    # ------------------------------------- 5c. post-level audio chain -> the candidate (Roger 2026-10-30 1b/1c)
    # levelled release -> [voice pitch unify] -> ambient bed + under-score -> <EP>_final_candidate_9x16.mp4.
    # Picture stays bit-exact through the chain; every stage is idempotent by input/output sha; a stage
    # failure blocks (the chain is the repair Roger asked for, not a nicety).
    chain_blockers = s7_post_level_audio_chain(ctx, res, steps, line_windows_for_level)
    if chain_blockers:
        res.steps.extend(steps)
        res.blockers = chain_blockers
        return res
    # ------------------------------------- 6a. optional tail ad (never blocks the episode)
    tail_ad = s7_tail_ad(ctx, res, endcard_seconds=outro_seconds)
    res.details["tail_ad"] = tail_ad

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
    if p.final_candidate.is_file():
        parity_json = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.json"
        parity_md = p.assembly / f"{ctx.episode}_FINAL_CUT_SHOT_PLAN_PARITY.md"
        parity_step = ctx.run([VENV, RT_TOOLS / "final_cut_shot_plan_parity.py", "--episode", ctx.episode,
                               "--final", p.final_candidate, "--contract", p.contract,
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

    # 6c. camera motion gate on the clips that made the candidate (Roger 2026-10-30 item 2: locked-off share
    # >= 70 % of units, 0 units with >= 1 reversal/s).  FAIL blocks unless a sha-bound line-owner order carries it.
    camera_step = s7_camera_motion_gate(ctx, res)
    if camera_step is not None:
        steps.append(camera_step)
        if camera_step["exit_code"] != 0 and not camera_step.get("accepted_by_line_owner_order"):
            res.steps.extend(steps)
            res.blockers = ["FINAL_CUT_CAMERA_MOTION_FAIL:" + ",".join(camera_step.get("failing") or [])]
            return res

    chain_windows = (res.details.get("final_candidate_chain") or {}).get("line_windows_for_detectors")
    chain_windows_ok = bool(chain_windows and Path(str(chain_windows)).is_file())
    detector_argv: list[Any] = [VENV, ENGINE / "tools/final_cut_audience_detectors.py",
                                "--media", p.final_candidate, "--out", detector_report,
                                "--lexicon", ctx.p.scope["lexicon"],
                                # the pre-levelling speaker map must not be laid over windows rebuilt on the
                                # candidate (F4: it re-attributed speakers within ±0.6 s and corrupted the measure)
                                *([] if chain_windows_ok else ["--speaker-map", speaker_map]),
                                "--story-segments", release_timeline,
                                "--voice-cast", ctx.p.scope["voice_cast"],
                                # Roger 2026-10-30 item 1a: ASR read-back of the mix vs burned subtitles
                                # (subtitle_asr_agreement >= 95 %, babble outside cues <= 1 s); read per
                                # release segment, cached incrementally by media sha (F2: large-v3 whole-file
                                # took 2 h on this 8 GB machine)
                                "--readback-asr-json", p.readback_asr, "--readback-model", s7_asr_model(),
                                # ja / ko read back in their own language (zh / en keep the historical call)
                                *(["--language", ctx_language(ctx)] if ctx_language(ctx) in ("ja", "ko") else [])]
    if chain_windows_ok:
        # line windows rebuilt on the finished candidate by the post-level chain (unit-bounded, Roger 2026-10-30):
        # the pre-levelling windows sat on pre-trim offsets (E12: 13 wholly outside their unit)
        detector_argv += ["--asr-json", chain_windows]
    elif asr_windows.is_file():
        # per-unit ASR windows (timing) with contract attribution; whole-file ASR of the levelled final
        # merges speech with wind/music into 10-20 s windows and mismeasures every line (E04 v2, 23:30Z)
        detector_argv += ["--asr-json", asr_windows]
    subtitles = subtitles_ass_path(ctx)
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
                         "--video", p.final_candidate, "--out", p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_GATE.json"],
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
        final_sha = sha256_file(p.final_candidate) if p.final_candidate.is_file() else None
        orders = _gate_acceptance_orders(ctx)
        order = _rga.find_acceptance(
            orders, episode=ctx.episode, gate_id="FINAL-CUT-AUDIENCE-DETECTORS",
            failing=failing, media_sha256=final_sha, media_item_id="loudness",
            expected_issuer=ctx.authority.get("line_owner_id") or "", engine_root=ENGINE)
        # recorded after the order lookup: a FAIL an order already carried is flagged default_accepted
        res.details["knowledge_events_detectors"] = kb_events(
            "record_final_cut", episode=ctx.episode, kind="S7_DETECTOR", items=failing, media_sha256=final_sha,
            evidence={"gate": "FINAL-CUT-AUDIENCE-DETECTORS"}, detector_report=str(detector_report),
            accepted_order_seq=(order or {}).get("seq"))
        if order is None:
            res.steps.extend(steps)
            res.blockers = ["FINAL_CUT_AUDIENCE_DETECTORS_FAIL:" + str(gate_step.get("stdout_tail") or "")[-400:]]
            return res
        record = _rga.acceptance_record(order, episode=ctx.episode, gate_id="FINAL-CUT-AUDIENCE-DETECTORS",
                                        failing=failing, media_sha256=final_sha, media_item_id="loudness",
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
    review_rejected = "FINAL_AUDIENCE_REVIEW_REJECTED" in (final_audience.get("blockers") or [])
    if review_rejected:
        res.details["knowledge_events_final_review"] = kb_final_review_reject(ctx, final_audience)
    if final_audience["status"] == PASS or review_rejected:
        res.details["knowledge_events_exemplars"] = kb_success_exemplars(ctx, final_audience)
        res.details["knowledge_events_craft_standard"] = kb_craft_standard_gaps(ctx, final_audience)
        res.details["knowledge_events_qa_defects"] = kb_qa_defects(ctx, final_audience)
        res.details["knowledge_events_final_review_findings"] = kb_final_review_findings(ctx, final_audience)
    if final_audience["status"] != PASS and not review_rejected:
        res.status = (REVIEW_REQUIRED
                      if final_audience["status"] == REVIEW_REQUIRED else BLOCKED)
        res.blockers = list(final_audience.get("blockers") or [])
        return res
    # ------------------------------------------- 7b. final fix round (line owner 2026-11-20: never wait on quality)
    # One automatic round after a REJECT_RECUT / confirmed DEFECT review: free S7 re-cuts and at most one paid S6 redo
    # per unit, then ONE more review; whatever that says, the line proceeds (final_fix_round.py).
    final_fix = s7_final_fix_round(ctx, res, final_audience, review_rejected)
    res.details["final_fix_round"] = final_fix
    if final_fix.get("action") in ("S7_RERUN", "S6_REDO_PENDING"):
        res.status = BLOCKED
        res.blockers = (["FINAL_FIX_ROUND_S7_RERUN"] if final_fix["action"] == "S7_RERUN"
                        else [f"FINAL_FIX_ROUND_S6_REDO_PENDING:{','.join(final_fix.get('units') or [])}"])
        return res
    # 7c. per-unit plan parity + objective defects at release (2026-11-23, device 1101 E24).  Owner policy (option
    # iii): a short runtime or unresolved burned text HOLDS the X2C release -- recorded as RELEASE_HELD:<classes> and
    # queued as a redo candidate; S7 / S8 finish as usual and the line moves on (never waits on the owner)
    objective = s7_review_plan_parity(ctx, res, final_audience)
    res.details["objective_defects"] = objective

    # ------------------------------------------- 8. final-package QA (D-9/D-12)
    final_qa = s7_qa(ctx, res)
    res.details["final_qa"] = final_qa
    failing_gates = [str(row.get("gate_id")) for row in (final_qa.get("stage_gate_rows") or [])
                     if isinstance(row, dict) and row.get("gate_id") and row.get("status") != PASS]
    res.status = PASS if (p.final_candidate.is_file()
                          and all(step["exit_code"] == 0 or step.get("accepted_by_line_owner_order") for step in steps)
                          and final_qa["status"] == PASS and not review_rejected) else BLOCKED
    release: dict[str, Any] = {}
    if res.status != PASS:
        release = s7_default_release_acceptance(ctx, final_qa, review_rejected)
        res.details["final_release_acceptance"] = release
    if failing_gates:
        # classified in the event layer: never-invoked / bookkeeping / combined-verdict rows are not failures of
        # their own; a FAIL the default-terms release order already carried is flagged default_accepted
        res.details["knowledge_events_final_gates"] = kb_events(
            "record_final_gates", episode=ctx.episode, summary_path=final_qa.get("stage_gate_summary"),
            rows=final_qa.get("stage_gate_rows") or [],
            media_sha256=sha256_file(p.final_candidate) if p.final_candidate.is_file() else None,
            accepted_order_seq=release.get("order_seq") if release.get("status") == PASS else None)
    if res.status != PASS:
        if release.get("status") != PASS:
            res.blockers = release.get("blockers") or [value for value in (final_qa.get("blockers") or [])] or \
                ["FINAL_PACKAGE_QA_NOT_PASS"]
            return res
        res.status = PASS
        res.receipts.append(str(release["record_path"]))
    # ------------------------------------------- 9. promotion: candidate -> deliverable (item 0)
    # Every S7 gate is PASS or carried by a sha-bound line-owner order; only now does the cut
    # become a deliverable.  Byte copy, sha verified, tail-ad variant alongside when it exists.
    try:
        promotion = promote_final_candidate(p)
    except Exception as exc:  # noqa: BLE001
        res.status = BLOCKED
        res.blockers = [f"FINAL_CANDIDATE_PROMOTION_FAILED:{type(exc).__name__}:{exc}"]
        return res
    res.details["release_promotion"] = promotion
    if ctx.state.get("tail_ad") and promotion.get("ad_tail_video"):
        ctx.state["tail_ad"]["ad_tail_video"] = promotion["ad_tail_video"]
        ctx.state["tail_ad"]["ad_tail_video_sha256"] = promotion["ad_tail_video_sha256"]
        ctx.save_state()
    res.blockers = []
    write_json(p.qa_report, {
        "schema": "nalu.episode_final_qa_report.v1", "episode": ctx.episode,
        "recorded_at": now(), "recorded_by": TOOL_ID,
        "final_video": str(p.final_mp4),
        "final_video_sha256": sha256_file(p.final_mp4),
        "final_candidate": str(p.final_candidate),
        "release_promotion": promotion,
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
        # reused stages ({"reused": ...}) and order-carried gate rows have no log: the report must not crash on them
        # (field device …1324 E01 + E02, 2026-11-07: KeyError 'log' after promotion left S7 CRASHED)
        "steps": [{"name": step.get("name"), "exit_code": step.get("exit_code"), "log": step.get("log"),
                   **({"reused": True} if step.get("reused") else {})}
                  for step in steps]})
    res.receipts.append(str(p.qa_report))
    # Plan §6: timing map updated after editing completes.
    timing = timing_map(ctx, stage="S7", media_dir=p.video_media, edit_decisions=p.agentcut_project)
    res.details["unit_timing_map"] = timing
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
def knowledge_sync_summary(ctx: Ctx) -> dict[str, Any]:
    """Let the pipeline upgrade the knowledge base itself (Roger 2026-10-01).

    Runs the writer before the checkpoint is written so CHECKPOINT.md can carry the
    result.  Advisory, never blocking: a bookkeeping tool must not hold an episode
    hostage.  When it reports gaps (causes this episode hit that nobody abstracted
    into a rule), those are surfaced in the checkpoint and in the state so a silent
    zero is visible instead of being forgotten — E02/E03/E07 finished with no
    entries at all and no stage ever failed for it.
    """
    tool = RT_TOOLS / "knowledge_sync.py"
    if not tool.is_file():
        return {"status": "TOOL_MISSING", "tool": str(tool)}
    import subprocess as _sp
    cmd = [str(VENV), str(tool), "--episode", ctx.episode, "--root", str(ENGINE), "--runtime-root", str(RT)]
    try:
        proc = _sp.run(cmd, cwd=str(ENGINE), capture_output=True, text=True, timeout=120)
    except (OSError, _sp.TimeoutExpired) as exc:
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{exc}", "argv": cmd}
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(proc.stdout or "{}")
    except ValueError:
        payload = {"status": "UNPARSEABLE", "stdout_tail": (proc.stdout or "")[-400:]}
    payload["argv"] = cmd
    payload["exit_code"] = proc.returncode
    if proc.returncode != 0 and payload.get("status") != "FAIL":
        payload["status"] = "FAIL"
    return payload


def owner_review_required(ctx: Any) -> bool:
    """``project.owner_review_required: true`` in the runtime qingshan.json restores the old S8 wait for the line
    owner's ``approve``.  Default false (line owner 2026-11-20: never wait on quality)."""
    config = getattr(ctx, "config", None) or {}
    project = config.get("project") if isinstance(config.get("project"), dict) else {}
    return project.get("owner_review_required") is True


ENGINE_APPROVER = "engine_default_terms"


def s8_auto_approve(ctx: Any) -> dict[str, Any]:
    """S8 approval under the default terms, written by the engine (line owner 2026-11-20: 「不要等我了」).

    Only for a released cut: S7 PASS (or reused PASS) and the deliverable on disk -- the same FINAL_CUT_READY state
    the heartbeat publishes and continues from.  The record names the engine, the policy and every finding the final
    fix round left unresolved.  The paid order's publication scope is carried, never widened: an order with
    NO_PLATFORM_PUBLICATION stays deliverable-only (this pipeline has no publish path either way)."""
    import final_fix_round as _ffr
    p = ctx.p
    s7 = ctx.stage_state("S7").get("status")
    if s7 not in TERMINAL_OK or not p.final_mp4.is_file():
        return {"status": "NOT_ELIGIBLE", "reason": f"S7={s7} deliverable={'yes' if p.final_mp4.is_file() else 'no'}"}
    record = read_json(final_fix_record_path(ctx), {}) or {}
    order = getattr(ctx, "paid_order", None) or {}
    conditions = list(order.get("condition_ids") or [c.get("id") for c in order.get("conditions") or []
                                                      if isinstance(c, dict)])
    publication = order.get("publication_allowed") is True
    payload = {
        "schema": "nalu.pipeline_approval.v1",
        "episode": ctx.episode,
        "approved_at": now(),
        "approved_by": ENGINE_APPROVER,
        "owner_policy": "never_wait_quality",
        "policy_source": "line owner 2026-11-20: 不要等我了，我自己看不过来 (quality never waits for the owner)",
        "note": "S8 auto-approved under the default terms; the owner may still review the checkpoint afterwards",
        "checkpoint": str(p.checkpoint),
        "checkpoint_sha256": sha256_file(p.checkpoint),
        "final_video": str(p.final_mp4),
        "final_video_sha256": sha256_file(p.final_mp4),
        "final_fix_round": _ffr.summary(record) if record else {"status": "NONE"},
        "unresolved_findings": record.get("unresolved") or _ffr.unresolved(record),
        # owner 2026-11-23: a held release is still approved and delivered -- only the X2C publisher skips it
        **({"release_hold": record["release_hold"]} if record.get("release_hold") else {}),
        "publication_allowed": publication,
        "release_scope": ("DELIVERABLE_AND_PUBLICATION_PER_ORDER" if publication
                          else "DELIVERABLE_ONLY_NO_PLATFORM_PUBLICATION"),
        "paid_order": {"seq": order.get("seq"), "id": order.get("id"), "conditions": conditions},
        "recorded_by": TOOL_ID,
    }
    write_json(p.approval, payload)
    ctx.state["approval"] = {"status": "APPROVED", "approved_at": payload["approved_at"], "by": ENGINE_APPROVER,
                             "note": payload["note"], "flag_file": str(p.approval),
                             "owner_policy": "never_wait_quality"}
    ctx.say(f"S8_AUTO_APPROVED episode={ctx.episode} by={ENGINE_APPROVER} "
            f"final_fix={payload['final_fix_round'].get('status')} "
            f"unresolved={len(payload['unresolved_findings'])} release_scope={payload['release_scope']}")
    return {"status": "APPROVED", "flag_file": str(p.approval), "approved_by": ENGINE_APPROVER,
            "release_scope": payload["release_scope"], "unresolved_findings": len(payload["unresolved_findings"])}


def stage_s8(ctx: Ctx) -> StageResult:
    import final_fix_round as _ffr
    p = ctx.p
    p.deliver.mkdir(parents=True, exist_ok=True)
    knowledge = knowledge_sync_summary(ctx)
    ctx.state["knowledge_sync"] = knowledge
    _record_line_upgrade(ctx, "line_upgrade_close", "close")  # advisory: was it read?
    write_checkpoint(ctx)
    approved = p.approval.is_file()
    auto: dict[str, Any] | None = None
    wait_for_owner = owner_review_required(ctx)
    if not approved and not wait_for_owner:
        auto = s8_auto_approve(ctx)
        approved = auto.get("status") == "APPROVED"
        if approved:
            write_checkpoint(ctx)  # the checkpoint names the engine approval
    res = StageResult(PASS if approved else "AWAITING_APPROVAL")
    res.details = {
        "checkpoint": str(p.checkpoint),
        "approval_flag": str(p.approval),
        "approved": approved,
        "approval_mode": ("OWNER_REVIEW_REQUIRED" if wait_for_owner else "ENGINE_DEFAULT_TERMS"),
        "auto_approval": auto,
        "final_fix_round": _ffr.summary(read_json(final_fix_record_path(ctx), {}) or {}),
        "knowledge_sync": knowledge,
        "unblock_with": (f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} approve --episode {ctx.episode} "
                         f"--by {shlex.quote(str(ctx.authority.get('line_owner_id') or '<LINE_OWNER_ID>'))}"),
        "platform_upload": "NEVER — this pipeline has no publish path.",
    }
    res.receipts = [str(p.checkpoint)]
    if not approved:
        res.blockers = (["AWAITING_LINE_OWNER_APPROVAL"] if wait_for_owner
                        else [f"S8_AUTO_APPROVE_NOT_ELIGIBLE:{(auto or {}).get('reason')}"])
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


def qa_defect_checkpoint_lines(ctx: Any) -> list[str]:
    """S8 owner-approval section: the final review's must-check defects (nalu_qa_defect_checklist record, with
    timestamps and routing) and the S3 cross-character similarity, so the owner sees them before approving.
    Advisory, never raises."""
    try:
        import nalu_qa_defect_checklist as _qa
        import character_distinctness as _cd
        p = ctx.p
        record = read_json(p.assembly / "final_qa" / f"{ctx.episode}_QA_DEFECT_CHECKLIST.json", {}) or {}
        lines = _qa.checkpoint_lines(record)
        reports = getattr(p, "preprod_reports", None)
        if reports is not None and not record.get("s6_burn_unresolved"):  # S6 burn retries that did not clear
            state = read_json(Path(reports) / f"{ctx.episode}_S6_WAVE_STATE.json", {}) or {}
            unresolved = (_qa.measure_s6_burn_unresolved(state) or {}).get("units")
            if unresolved:
                if not lines:
                    lines = ["## Final-review must-check defects (line owner 2026-11-19)", ""]
                lines += _qa.s6_burn_unresolved_lines(unresolved) + [""]
        distinct = read_json(p.identity / f"{ctx.episode}_{_cd.REPORT_SUFFIX}", {}) or {}
        pairs = _cd.lookalike_pairs(distinct)
        if pairs:
            if not lines:
                lines = ["## Final-review must-check defects (line owner 2026-11-19)", ""]
            lines += ["S3 look-alike cast (InsightFace between different characters' cards, threshold "
                      f"{distinct.get('threshold')}; advisory, one regeneration per pair):", ""]
            lines += [f"* `{r.get('a')}` ~ `{r.get('b')}` cosine {r.get('cosine')} — {r.get('state')}" for r in pairs]
            lines.append("")
        return lines
    except Exception as exc:  # noqa: BLE001 -- the checkpoint must always be written
        return [f"* must-check defect summary unavailable: {type(exc).__name__}", ""]


def kb_qa_defects(ctx: Ctx, final_audience: dict[str, Any]) -> dict[str, Any]:
    """The final review's must-check defects (``<EP>_QA_DEFECT_CHECKLIST.json`` beside the score report) as
    ``QA_DEFECT|<item id>`` knowledge events (nalu_knowledge_events.record_qa_defects).  Best-effort."""
    try:
        report = str(final_audience.get("report") or "")
        path = Path(report).parent / f"{ctx.episode}_QA_DEFECT_CHECKLIST.json" if report else None
        if path is None or not path.is_file():
            return {"status": "NO_QA_DEFECT_CHECKLIST"}
        return kb_events("record_qa_defects", episode=ctx.episode, checklist_path=str(path),
                         media_sha256=final_audience.get("final_video_sha256"))
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


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
    _s1_integrity = (ctx.stage_state("S1").get("details") or {}).get("s1_integrity") or {}
    if isinstance(_s1_integrity, dict) and _s1_integrity.get("marker"):
        add("## S1 script integrity admitted after exhaustion")
        add("")
        add(f"`{_s1_integrity['marker']}` -- {_s1_integrity.get('max_rounds')} writer revisions did not clear these "
            "structural failures; the script was admitted so the line keeps moving (the release hold still applies).")
        for _row in _s1_integrity.get("admitted") or []:
            add(f"* `{_row}`")
        add("")
    add("## What to watch (line-owner review list)")
    add("")
    if p.final_mp4.is_file():
        add(f"1. `{p.final_mp4}` — full episode, 9:16.")
        add(f"   sha256 `{sha256_file(p.final_mp4)}`")
        if p.qa_report.is_file():
            add(f"2. QA report `{p.qa_report}`")
        else:
            add("2. QA report: **not written** — S7 did not reach its final PASS for this file")
    elif p.final_candidate.is_file():
        add("**No deliverable yet.**  S7 stopped on a gate, so the cut below is a CANDIDATE in the")
        add("assembly directory — it is not released and must not be treated as the episode (Roger 2026-10-30 item 0).")
        add(f"1. candidate `{p.final_candidate}`")
        add(f"   sha256 `{sha256_file(p.final_candidate)}`")
        _det = p.assembly / f"{ctx.episode}_FINAL_CUT_AUDIENCE_DETECTORS.json"
        if _det.is_file():
            _detd = read_json(_det, {}) or {}
            _rows = ", ".join(f"{k}={v.get('status')}" for k, v in (_detd.get("detectors") or {}).items()
                              if isinstance(v, dict))
            add(f"2. audience detectors `{_det}` — overall **{_detd.get('status')}**: {_rows}")
    else:
        add("**There is no cut to watch yet.**  The pipeline stopped before S7 produced")
        add(f"`{p.final_mp4}`.  What exists to review instead:")
        for label, path in (
                ("preproduction report", p.preprod_report),
                # The unit count is read off the plan, never written as a literal: the label
                # said "29-unit" from E07 through E09, then kept saying it while the plan grew
                # (E11: 41).  A stale number here is a line-owner-facing lie about the episode
                # they are being asked to review, and the count moves for innocent reasons —
                # the builder re-cuts shots into 4–8 s units, so it is not even stable across
                # a text edit.  Read it, and say nothing when the plan is absent.
                (f"{_unit_count(p.grouping_plan)}-unit grouping plan"
                 if _unit_count(p.grouping_plan) else "video unit grouping plan", p.grouping_plan),
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
    add("## Knowledge base")
    add("")
    ks = state.get("knowledge_sync") or {}
    ks_status = ks.get("status") or "NOT_RUN"
    add(f"* sync: **{ks_status}** — new rows {json.dumps(ks.get('new_ids') or [], ensure_ascii=False)}, "
        f"registry now {ks.get('rule_count', '?')} entries")
    if ks.get("gaps"):
        add(f"* **unabstracted causes ({len(ks['gaps'])})** — this episode hit failures that are NOT yet "
            f"rules; write them before the next episode starts: "
            f"{'; '.join('`%s`' % g for g in ks['gaps'][:8])}")
    elif ks_status == "NO_NEW_KNOWLEDGE":
        add("* nothing new was abstracted this episode. If it hit a failure that cost money, that cause "
            "is not in the registry yet — see AGENTS.md §7 step 0.")
    recheck = ks.get("free_recheck") or []
    recheck_hit = [r["rule_id"] for r in recheck if r.get("free_matches")]
    recheck_miss = [r["rule_id"] for r in recheck if r.get("found") and not r.get("free_matches")]
    if recheck_hit:
        add(f"* **new rule(s) matched a free step already run this episode** — "
            f"{json.dumps(recheck_hit, ensure_ascii=False)}: re-run that free step before trusting its "
            f"cached PASS under the new rule (never resubmit a paid one for this). See `knowledge_sync.free_recheck` "
            f"in CHECKPOINT state for which step.")
    if recheck_miss:
        add(f"* new rule(s) {json.dumps(recheck_miss, ensure_ascii=False)} matched no free step this episode "
            f"ran; only verified via their own `regression` test under `tools/run_portable_ci.py`.")
    lu_pre = state.get("line_upgrade_preflight") or {}
    lu_close = state.get("line_upgrade_close") or {}
    add(f"* read before writing (S1 preflight): **{lu_pre.get('status') or 'NOT_RUN'}** "
        f"{json.dumps(lu_pre.get('findings') or [], ensure_ascii=False)}; "
        f"at close: **{lu_close.get('status') or 'NOT_RUN'}** "
        f"(briefing {(lu_close.get('knowledge_read') or {}).get('status') or '?'})")
    add("")
    for line in qa_defect_checkpoint_lines(ctx):  # final-review must-check defects + S3 look-alike cast (2026-11-19)
        add(line)
    try:  # the final fix round (owner 2026-11-20) and how S8 was approved
        import final_fix_round as _ffr
        for line in _ffr.checkpoint_lines(read_json(final_fix_record_path(ctx), {}) or {}):
            add(line)
    except Exception as exc:  # noqa: BLE001 -- the checkpoint must always be written
        add(f"* final fix round summary unavailable: {type(exc).__name__}")
        add("")
    approval_row = state.get("approval") or {}
    if approval_row.get("by") == ENGINE_APPROVER:
        add(f"* S8 approved by the engine under the default terms at {approval_row.get('approved_at')} "
            "(owner policy never_wait_quality); unresolved findings are listed in the approval record "
            f"`{approval_row.get('flag_file')}`")
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
    if owner_review_required(ctx):
        add("`project.owner_review_required: true`: this episode does NOT advance and the next episode does NOT "
            "start until the line owner runs:")
        add("")
        add("```")
        add(f"{VENV} {RT_TOOLS / 'nalu_pipeline.py'} approve --episode {ctx.episode} "
            f"--by {shlex.quote(str(ctx.authority.get('line_owner_id') or '<LINE_OWNER_ID>'))}")
        add("```")
        add("")
        add(f"That writes `{p.approval}`, which `loop` polls.  No platform upload is ever")
        add("performed by this pipeline.")
    else:
        add("Quality never waits for the line owner (owner policy 2026-11-20, `never_wait_quality`): once S7 has")
        add(f"released the cut, S8 writes `{p.approval}` itself as `{ENGINE_APPROVER}` with every unresolved")
        add("finding, and the line continues exactly as on FINAL_CUT_READY.  Nobody needs to run `approve` and no")
        add("agent should ask the owner about it.  No platform upload is ever performed by this pipeline; the paid")
        add("order's publication scope is unchanged.")
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
FINGERPRINTS: dict[str, Callable[[Ctx], str | None]] = {"S1": fp_s1, "S2": fp_s2, "S4": fp_s4}

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

    # tail-ad opt-in (optional, per-episode): asked exactly once, ever, right
    # before S1 on a fresh run whose four writer layers already exist.  Sticky
    # in ctx.state so a later --from S3-style resume never re-asks.  Runs as a
    # direct in-process call (not ctx.run()'s buffered subprocess) so the
    # question is visible on the live terminal while it polls.
    if "S1" in selected and ctx.state.get("tail_ad_opt_in") is None \
            and all(path.is_file() for path in ctx.p.layers().values()):
        decision = _tail_ad_optin.run_opt_in(
            ctx.episode, prompts_dir=ADS_PROMPTS, answer_dir=ADS_PROMPTS,
            policy_path=ADS_POLICY, ledger_path=ADS_TRANSACTIONS / "opt_in_ledger.json",
            manifest_path=ctx.p.writer_manifest, say=ctx.say,
            language=ctx_language(ctx), default_policy_path=ADS_DEFAULT_POLICY)
        ctx.state["tail_ad_opt_in"] = decision
        ctx.save_state()

    exit_code = 0
    looped_back = False
    position = 0
    while position < len(selected):
        sid = selected[position]
        position += 1
        row = ctx.stage_state(sid)
        fingerprint = FINGERPRINTS.get(sid, lambda _c: None)(ctx)
        if (not ctx.force and row.get("status") in TERMINAL_OK
                and (fingerprint is None or fingerprint == row.get("input_fingerprint"))
                and not (sid == "S5" and (s5_keyframes_missing(ctx) or s5_q1_not_all_admitted(ctx)))
                and not (sid == "S3" and row.get("reopen_required"))):
            ctx.say(f"\n-- {sid} {STAGE_TITLES[sid]}: SKIPPED (already PASS, inputs unchanged)")
            row["status"] = SKIPPED
            ctx.save_state()
            continue
        ctx.say(f"\n-- {sid} {STAGE_TITLES[sid]}")
        row["attempts"] = int(row.get("attempts") or 0) + 1
        row["started_at"] = now()
        row.pop("reopen_required", None)   # S5 sets it again if the asset is still not locked
        ctx._lost_response_wait = None
        try:
            result = STAGE_FUNCS[sid](ctx)
        except _media.MediaToolBlocked as exc:
            result = StageResult(BLOCKED, media_tool_error=str(exc))
            result.blockers = [str(exc)]
        except Exception as exc:  # noqa: BLE001 — a stage crash must not lose state
            result = StageResult("CRASHED", exception=f"{type(exc).__name__}: {exc}")
            result.blockers = [f"STAGE_CRASHED:{type(exc).__name__}:{exc}"]
        lost_wait = getattr(ctx, "_lost_response_wait", None)
        if result.status == HARD_STOP and lost_wait:
            # only lost HopsAPI creates refused the budget: a remote wait the system tick re-runs, not a stop
            # that waits for a human (Ctx.lost_response_wait; fleet 1485 E03 / 1101 E20, 2026-11-21)
            result.status = BLOCKED
            result.blockers = [lost_wait["blocker"]] + [b for b in result.blockers
                                                       if not str(b).startswith("BUDGET_HARD_STOP")]
            result.details["lost_response_wait"] = lost_wait
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
        if sid in ("S3", "S5", "S6"):  # HopsAPI 424s: content rejection (lesson) vs outage (anomaly)
            row["knowledge_events_provider"] = kb_events(
                "scan_provider_rejections", episode=ctx.episode,
                stores={"image": ENGINE / "workflow/tasks/giggle_submit_transactions" / ctx.episode,
                        "video": ENGINE / "workflow/tasks/giggle_video_submit_transactions" / ctx.episode})
        # Time/credit ledger (Roger 2026-09-25 §六, effective E09): one append-only event
        # per stage terminal status, reactive to what the loop already knows — no new timer.
        ledger_event = _time_ledger.append_event(
            episode=ctx.episode, stage=sid, status=result.status,
            started_at=row.get("started_at"), finished_at=row.get("finished_at"),
            credits=result.planned_credits, attempt=row.get("attempts") or 1,
            steps=result.steps, work_root=NALU_WORK,
        )
        ctx.state["time_ledger_cumulative"] = {
            "episode_cumulative_seconds": ledger_event["episode_cumulative_seconds"],
            "episode_cumulative_credits": ledger_event["episode_cumulative_credits"],
            "ledger_path": str(_time_ledger.ledger_path(ctx.episode, work_root=NALU_WORK)),
        }
        ctx.state["current_stage"] = sid
        ctx.state["credits"] = credits_summary(ctx)
        ctx.save_state()
        ctx.say(f"   {sid} => {result.status}"
                + (f"   blockers: {', '.join(result.blockers)}" if result.blockers else "")
                + f"   [{ledger_event['wall_seconds']:g}s, cum {ledger_event['episode_cumulative_seconds']:g}s]")

        # final fix round (owner 2026-11-20): units parked for a paid redo -> back to S6 once, when this paid run
        # includes S6 (paid_stage.sh <EP> S6 S8); otherwise S7 names that command and stops.
        if (sid == "S7" and not looped_back and "S6" in selected and getattr(ctx, "paid_enabled", False)
                and ((result.details or {}).get("final_fix_round") or {}).get("action") == "S6_REDO_PENDING"):
            looped_back = True
            position = selected.index("S6")
            ctx.say("-- final fix round: back to S6 for the parked unit redo(s), then S7 again")
            continue
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
        if COMPACT_OUTPUT:
            print(f"planned paid commands not executed ({len(ctx.planned_commands)}): "
                  f"{ctx.p.logs / f'{ctx.run_id}_planned_paid_commands.json'}")

    if COMPACT_OUTPUT:
        print(f"full run log: {ctx.run_log}")
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
    tail_ad = state.get("tail_ad_opt_in")
    if tail_ad:
        print(f"tail-ad opt-in     : {tail_ad.get('answer')} ({tail_ad.get('reason')})")
    produced_ad = state.get("tail_ad") or {}
    if produced_ad.get("ad_tail_video_sha256"):
        print(f"tail-ad produced   : {ctx.p.ad_tail_video}  "
              f"sha256={produced_ad['ad_tail_video_sha256'][:12]}...")
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
    cumulative = state.get("time_ledger_cumulative")
    if cumulative:
        print(f"time ledger        : {cumulative.get('ledger_path')}")
        print(f"  cumulative       : {cumulative.get('episode_cumulative_seconds'):g}s"
              f"  {cumulative.get('episode_cumulative_credits')} credits")
        summary = _time_ledger.episode_summary(ctx.episode, work_root=NALU_WORK)
        if summary.get("stages"):
            print(f"  {'stage':6} {'seconds':>8}  {'compute':>8} {'remote':>8} {'human':>8} {'idle':>8}")
            for stage_id in STAGE_IDS:
                ev = summary["stages"].get(stage_id)
                if not ev:
                    continue
                b = ev.get("breakdown") or {}
                print(f"  {stage_id:6} {ev.get('wall_seconds', 0):>8g}  "
                      f"{b.get('compute', 0):>8g} {b.get('remote_wait', 0):>8g} "
                      f"{b.get('human_wait', 0):>8g} {b.get('idle', 0):>8g}")
        print()


def cmd_status(args: argparse.Namespace) -> int:
    ctx = Ctx(args.episode, args)
    if args.json:
        print(json.dumps(ctx.state, ensure_ascii=False, indent=1))
        return 0
    print_status(ctx)
    return 0


def cmd_start_frame_decision(args: argparse.Namespace) -> int:
    ctx = Ctx(args.episode, args)
    row = record_line_owner_start_frame_decision(ctx, args.unit, authority=args.authority, reason=args.reason,
                                                 park_derived=not args.keep_derived)
    print(json.dumps({"episode": args.episode, "unit_id": args.unit, **row,
                      "wave_state": str(_wave_state_path(ctx))}, ensure_ascii=False, indent=1))
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

        # THE CHECKPOINT IS NOT SKIPPABLE.  Even a failed episode gets one.  A released cut was approved by
        # S8 itself under the default terms (owner policy 2026-11-20, never_wait_quality), so the wait below
        # ends at once; a failed episode, or a line with project.owner_review_required: true, still blocks
        # until the approval flag exists.  There is no --yes and no timeout that self-approves.
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


def cmd_ab_variant(args: argparse.Namespace) -> int:
    return run_ab_variant(Ctx(args.episode, args), Path(args.variant))


def provider_reference_exclusions_path(ctx: Ctx) -> Path:
    """tools/provider_reference_exclusions.py declaration for this episode (runtime preproduction)."""
    return ctx.p.rt_pre / "provider_reference_exclusions.json"


ISOLATE_REFERENCE_TOOL = ENGINE / "tools/isolate_rejected_reference.py"


def run_isolate_reference(ctx: Ctx, task_key: str, tries: int = 2) -> int:
    """``paid_stage.sh <EP> --isolate-reference <TASK_KEY>``: single-reference HopsAPI probes for ONE S5 task
    whose request settled as the zero-cost 424, through ``Ctx.paid_step`` (order must authorise S5, budget
    reservation against the episode cap, release on exit 0).  Without --paid it prints the plan only.
    A deterministic rejection is declared in provider_reference_exclusions.json; recompile S5 afterwards."""
    declaration = provider_reference_exclusions_path(ctx)
    base = [VENV, ISOLATE_REFERENCE_TOOL, "--episode", ctx.episode, "--task-key", task_key,
            "--manifest", ctx.p.keyframe_manifest, "--declaration", declaration, "--tries", tries]
    plan_step = ctx.run(base, name="isolate_reference_plan")
    if plan_step["exit_code"] != 0:
        ctx.say("   reference isolation refused before any POST: " + (plan_step.get("stdout_tail") or "")[-400:])
        return 2
    try:
        plan = json.loads((plan_step.get("stdout_tail") or "").strip().splitlines()[-1])
        planned = int(plan.get("planned_credits") or 0)
    except (ValueError, IndexError, AttributeError):
        planned = image_batch_credits(ctx, 12)  # isolate_rejected_reference.MAX_PROBES
    status, step = ctx.paid_step(base + ["--paid"], name="isolate_rejected_reference", sid="S5",
                                 planned_credits=planned, dry_argv=None,
                                 note=f"single-reference probes for {task_key}; declaration -> {declaration}")
    ctx.say(f"   isolate-reference {task_key} => {status}")
    if status == PASS:
        ctx.say(f"   next (free): recompile S5 so the declaration applies, re-review the prompt batch, then "
                f"{RT_TOOLS / 'paid_stage.sh'} {ctx.episode} S5 S5")
    return {PASS: 0, DRY: 0, HARD_STOP: 3}.get(status, 2)


def cmd_isolate_reference(args: argparse.Namespace) -> int:
    return run_isolate_reference(Ctx(args.episode, args), args.task_key, args.tries)


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

    sfd = subs.add_parser("start-frame-decision",
                          help="line owner: a continuity-derived unit opens on its own keyframe (parks the derived tail copy)")
    sfd.add_argument("--episode", required=True)
    sfd.add_argument("--unit", required=True)
    sfd.add_argument("--authority", required=True, help="who decided and when, verbatim")
    sfd.add_argument("--reason", default="LINE_OWNER_REDESIGN")
    sfd.add_argument("--keep-derived", action="store_true", help="do not park the derived keyframe copy")
    sfd.set_defaults(func=cmd_start_frame_decision, dry_run=False, paid=False, force=False,
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

    ab = subs.add_parser(
        "ab-variant", help="submit ONE A/B variant task (tools/h3_constraint_ab_variant.py) through the S6 "
                           "machinery; clip -> <EP>/video_ab/, never assembly.  Paid only via paid_stage.sh")
    ab.add_argument("--episode", required=True)
    ab.add_argument("--variant", required=True, help="the one-task manifest h3_constraint_ab_variant.py wrote")
    ab.add_argument("--paid", action="store_true")
    ab.add_argument("--dry-run", action="store_true")
    ab.set_defaults(func=cmd_ab_variant, force=False, from_stage=None, until=None)

    iso = subs.add_parser(
        "isolate-reference", help="single-reference HopsAPI probes for ONE S5 task rejected with a zero-cost 424; "
                                  "declares the refused non-identity reference.  Paid only via paid_stage.sh")
    iso.add_argument("--episode", required=True)
    iso.add_argument("--task-key", required=True)
    iso.add_argument("--tries", type=int, default=2)
    iso.add_argument("--paid", action="store_true")
    iso.add_argument("--dry-run", action="store_true")
    iso.set_defaults(func=cmd_isolate_reference, force=False, from_stage=None, until=None)

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
