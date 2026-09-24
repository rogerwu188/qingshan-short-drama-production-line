#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_qa_evidence_bundle.py — D-9: which final-phase gates apply, and the bundle.

Findings that drove the design (all verified in this clone)
-----------------------------------------------------------
* ``episode_stage_gate_runner.py --phase final`` runs 19 gates and ``--phase
  release`` 2, and the evidence bundle they need is **15 keys**, not the 11 in
  the runbook: the two missing ones are ``credit_ledger``
  (GIGGLE-CREDIT-LEDGER-CLOSURE) and ``watch_report``
  (RELEASE-SIGNOFF-INTEGRITY), plus the sha-verified pair ``canonical_script`` /
  ``canonical_script_sha256``.
* The bundle itself is a FLAT ``{key: path}`` dict, loaded with no schema check;
  a relative path resolves against the ENGINE root; required keys are existence-
  checked only; ``canonical_script`` is the one sha-verified key.
* **There is no N/A, SKIP or waiver anywhere** — not in the registry (no
  ``applies_when`` field exists) and not in the runner.  ``gate_result_contract``
  has an ``N_A`` status but the runner can never emit it.  ``FINAL-CUT-NO-SELF-
  WAIVER`` exists precisely to punish hand-written waivers, so this tool writes
  none.
* Two structural mismatches with a native-audio SD2 line:
  - **no BGM.**  ``bgm_authenticity_gate.py`` requires an audible solo stem AND
    calls ``validate_audio_profile(require_music=True)``, which for the
    ``NATIVE_MULTIMODAL_NO_EXTERNAL_BGM`` profile
    (``configs/audio_postproduction_profiles_v1_20260821.json``,
    ``external_bgm_allowed: false``) raises
    ``BGM_GATE_CALLED_FOR_NO_EXTERNAL_BGM_PROFILE``.  Supplying a stem does not
    help; it adds ``AUDIO_BGM_TRACK_FORBIDDEN_BY_PROFILE``.  The gate cannot
    pass for this line by construction.
  - **no audience-score stage.**  ``audience_report`` (and ``final_cut_metrics``)
    gate AUDIENCE-SCORE-PRE-RELEASE and all seven ``FINAL-CUT-*`` gates, and
    ``audience_score_gate.py`` demands three completed viewing passes and eight
    scored dimensions.  Without that stage those eight gates cannot produce a
    PASS.

The decision this tool implements
---------------------------------
Historical replay keeps the explicit legacy subset recorded by old episodes.
``CURRENT_PORTABLE`` projects run every registered final and release gate.  A
missing audience review, objective metric, event ledger, BGM stem, or any other
required artifact is a real blocker; this tool never converts missing evidence
into ``N_A`` and never manufactures a PASS.

CLI
---
  applicability --episode EP           print the APPLICABLE / N_A classification
  build         --episode EP           assemble the bundle from what exists
  run           --episode EP [--gate-subset applicable|all] [--dry]
  status        --episode EP
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nalu_qa_common import (  # noqa: E402
    ENGINE, GATE_REGISTRY, RT, RUNTIME, VENV, QaPaths, now,
    portable, read_json, require_ffmpeg, sha256_file, write_json,
)
import nalu_policy_profile as _policy  # noqa: E402

TOOL_ID = "final_qa_evidence_bundle.v1"
BUNDLE_SCHEMA = "qingshan.episode_stage_gate_evidence_bundle.v1"

FINAL_GATES = (
    "FINAL-AUDIT-COMPLETENESS", "GATE-REGISTRY-INTEGRITY", "FINAL-AUDIO-BED-CONTINUITY",
    "FINAL-STATIC-HOLD", "FROZEN-THRESHOLD-PROFILE", "FINAL-FRAME-CADENCE-FREEZE",
    "FINAL-OCR-POLICY", "PACING-STYLE-BAN-V2_3", "FINAL-AUDIO-PROVENANCE",
    "BGM-SOURCE-PRIORITY-AUTHENTICITY", "FINAL-PACKAGE-BLOCKERS",
    "AUDIENCE-SCORE-PRE-RELEASE", "FINAL-CUT-VIEWING-EVIDENCE",
    "FINAL-CUT-PICTURE-REPETITION", "FINAL-CUT-GATE-NAMING-HONESTY",
    "FINAL-CUT-WEAKEST-LINK-SCORING", "FINAL-CUT-NO-SELF-WAIVER",
    "FINAL-CUT-EVENT-LEDGER", "FINAL-CUT-DIALOGUE-LEGIBILITY",
    "FINAL-CUT-AUDIENCE-DETECTORS",   # seq=19 (E04 review): the line's own audience-level detectors
)
RELEASE_GATES = ("RELEASE-SIGNOFF-INTEGRITY", "GIGGLE-CREDIT-LEDGER-CLOSURE")

NOT_APPLICABLE = {
    "BGM-SOURCE-PRIORITY-AUTHENTICITY": {
        "reason": "NO_EXTERNAL_BGM_BY_LINE_DESIGN",
        "detail": "This line's audio profile is NATIVE_MULTIMODAL_NO_EXTERNAL_BGM "
                  "(configs/audio_postproduction_profiles_v1_20260821.json, "
                  "external_bgm_allowed false, bgm_mode FORBIDDEN). "
                  "bgm_authenticity_gate.py requires an audible solo stem and calls "
                  "validate_audio_profile(require_music=True), which for this profile "
                  "emits BGM_GATE_CALLED_FOR_NO_EXTERNAL_BGM_PROFILE. Supplying a stem "
                  "instead adds AUDIO_BGM_TRACK_FORBIDDEN_BY_PROFILE. The gate cannot "
                  "pass for a no-BGM line under any bundle.",
        "escalation": "Registry needs an applies_when/profile condition so the runner can "
                      "emit gate_result_contract's existing N_A status. Until then this "
                      "gate is omitted by name, not waived.",
        "substitute_evidence": "level_native_release_audio.py loudness QA "
                               "(release band -17.0..-15.0 LUFS) + FINAL-AUDIO-BED-CONTINUITY "
                               "+ FINAL-AUDIO-PROVENANCE cover the whole audio bed, which for "
                               "this line IS the entire mix.",
    },
}
_AUDIENCE_REASON = {
    "reason": "NO_AUDIENCE_SCORE_STAGE_ON_THIS_LINE",
    "detail": "audience_score_gate.py demands technical_gate_status PASS, three completed "
              "viewing passes (FULL_1X / MUTED / SOUND), eight scored dimensions and eight "
              "evidence fields including a frame grid, an ASR json and a scene rotation "
              "table. This line has no audience-score stage: its only human step is Roger's "
              "post-episode checkpoint. No audience_report or final_cut_metrics can honestly "
              "be produced, so the gate is omitted by name rather than fed a fabricated one.",
    "escalation": "Either add a real audience-score stage, or have the registry mark these "
                  "gates conditional on one.",
    "substitute_evidence": "The S8 checkpoint blocks the loop until a human has watched the "
                           "episode; that approval is recorded with the final video's sha256.",
}
for _gate in ("AUDIENCE-SCORE-PRE-RELEASE", "FINAL-CUT-VIEWING-EVIDENCE",
              "FINAL-CUT-PICTURE-REPETITION", "FINAL-CUT-GATE-NAMING-HONESTY",
              "FINAL-CUT-WEAKEST-LINK-SCORING", "FINAL-CUT-NO-SELF-WAIVER",
              "FINAL-CUT-EVENT-LEDGER", "FINAL-CUT-DIALOGUE-LEGIBILITY"):
    NOT_APPLICABLE[_gate] = dict(_AUDIENCE_REASON)

APPLICABLE = tuple(g for g in (*FINAL_GATES, *RELEASE_GATES) if g not in NOT_APPLICABLE)

#: bundle key -> (producer note, which gates consume it)
BUNDLE_KEYS: dict[str, dict[str, Any]] = {
    "canonical_script": {"gates": ["*"], "note": "the writer's narrative canonical; sha-verified"},
    "canonical_script_sha256": {"gates": ["*"], "note": "sha256 of the above, 64 hex"},
    "final_cut_audience_report": {"gates": ["FINAL-CUT-AUDIENCE-DETECTORS"],
                                  "note": "assembly/<EP>_FINAL_CUT_AUDIENCE_DETECTORS.json; sha-bound to the final"},
    "generation_contract": {"gates": ["SCRIPT-STRUCTURE-CONTRACT", "CONTINUITY-STATE-CONTRACT"],
                            "note": "the generation contract the S1 contract-holds gates ran on"},
    "writer_manifest": {"gates": ["SCRIPT-STRUCTURE-CONTRACT"], "note": "writer manifest (beat types/outcomes)"},
    "lexicon": {"gates": ["SCRIPT-STRUCTURE-CONTRACT", "FINAL-CUT-AUDIENCE-DETECTORS"], "note": "world lexicon"},
    "voice_cast": {"gates": ["VOICE-CAST-BINDING", "FINAL-CUT-AUDIENCE-DETECTORS"],
                   "note": "runtime/voice_cast.json (measured reference F0 bands)"},
    "final_video": {"gates": ["FINAL-AUDIT-COMPLETENESS", "FINAL-FRAME-CADENCE-FREEZE",
                              "FINAL-OCR-POLICY", "FINAL-AUDIO-PROVENANCE"],
                    "note": "deliverables/<EP>/<EP>_final_9x16.mp4; must resolve equal to "
                            "run_episode_qa.sh --video"},
    "final_package_manifest": {"gates": ["FINAL-PACKAGE-BLOCKERS"],
                               "note": "blocker manifest; must resolve equal to "
                                       "--blocker-manifest"},
    "ci_report": {"gates": ["GATE-REGISTRY-INTEGRITY", "FINAL-AUDIO-BED-CONTINUITY",
                            "FINAL-STATIC-HOLD", "FROZEN-THRESHOLD-PROFILE",
                            "PACING-STYLE-BAN-V2_3", "RELEASE-SIGNOFF-INTEGRITY"],
                  "note": "run_regression_ci.py report over the final video"},
    "render_plan": {"gates": ["PACING-STYLE-BAN-V2_3", "FINAL-FRAME-CADENCE-FREEZE"],
                    "note": "the render plan behind the cut"},
    "ffmpeg": {"gates": ["FINAL-AUDIO-PROVENANCE"], "note": "the ffmpeg binary path"},
    "published_mix": {"gates": ["FINAL-AUDIO-PROVENANCE"],
                      "note": "for a native-audio line the published mix IS the final video"},
    "audio_provenance_manifest": {"gates": ["FINAL-AUDIO-PROVENANCE"],
                                  "note": "whole-track fingerprint + declared processed intervals"},
    "edit_project": {"gates": ["BGM-SOURCE-PRIORITY-AUTHENTICITY"],
                     "note": "the rendered edit project consumed by the BGM authenticity gate"},
    "credit_ledger": {"gates": ["GIGGLE-CREDIT-LEDGER-CLOSURE"],
                      "note": "runtime/budget/ledger.json"},
    "watch_report": {"gates": ["RELEASE-SIGNOFF-INTEGRITY"],
                     "note": "the human checkpoint record; produced by `approve`"},
    "bgm_stem": {"gates": ["BGM-SOURCE-PRIORITY-AUTHENTICITY"],
                 "note": "real S6 selective-BGM stem; absent evidence blocks current projects"},
    "audience_report": {"gates": ["AUDIENCE-SCORE-PRE-RELEASE", "FINAL-CUT-*"],
                        "note": "reviewer-submitted, final-video-SHA-bound audience report"},
    "final_cut_metrics": {"gates": ["FINAL-CUT-*"],
                          "note": "objective metrics measured from the decoded final mp4"},
    "event_ledger": {"gates": ["FINAL-CUT-EVENT-LEDGER"],
                     "note": "reviewer-observed visible events with timestamps"},
}
UNSATISFIABLE = ("bgm_stem", "audience_report", "final_cut_metrics")


def _audio_profile(episode: str) -> str:
    """The resolved audio profile stamped into the AgentCut project by audio_profile_binding (S7)."""
    p = QaPaths(episode)
    project = read_json(p.agentcut_project if hasattr(p, "agentcut_project")
                        else p.assembly / f"{episode}_agentcut_project.json", {}) or {}
    binding = (project.get("metadata") or {}).get("audio_profile_binding") or {}
    return str(binding.get("resolved_audio_profile_id") or "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM")


def _gate_sets(episode: str) -> tuple[tuple[str, ...], dict[str, dict[str, Any]], tuple[str, ...]]:
    """(APPLICABLE, NOT_APPLICABLE, UNSATISFIABLE) for this episode's audio profile.  With selective BGM
    (Roger 2026-09-14) BGM-SOURCE-PRIORITY-AUTHENTICITY becomes applicable and bgm_stem is produced by
    nalu_selective_bgm.py mix."""
    if _policy.is_current():
        # The generic StoryClaw product may not waive a registered gate merely
        # because a historical line never built its evidence producer.  Missing
        # evidence therefore remains visible in the bundle and blocks the run.
        return (*FINAL_GATES, *RELEASE_GATES), {}, ()
    profile = _audio_profile(episode)
    if profile in {"NATIVE_MULTIMODAL_SELECTIVE_BGM", "LAYERED_POST_WITH_BGM"}:
        na = {k: v for k, v in NOT_APPLICABLE.items() if k != "BGM-SOURCE-PRIORITY-AUTHENTICITY"}
        applicable = tuple(g for g in (*FINAL_GATES, *RELEASE_GATES) if g not in na)
        return applicable, na, tuple(k for k in UNSATISFIABLE if k != "bgm_stem")
    return APPLICABLE, NOT_APPLICABLE, UNSATISFIABLE


def applicability(episode: str) -> dict[str, Any]:
    registry = read_json(GATE_REGISTRY, {}) or {}
    stages = {row.get("gate_id"): row.get("stage") for row in registry.get("gates") or []}
    profile = _audio_profile(episode)
    APPLICABLE_E, NOT_APPLICABLE_E, _ = _gate_sets(episode)
    strict_current = _policy.is_current()
    return {
        "schema": "nalu.final_phase_gate_applicability.v1",
        "episode": episode,
        "recorded_at": now(),
        "recorded_by": TOOL_ID,
        "line_profile": {
            "audio": (f"{profile} (native SD2 audio" + (", selective narrative BGM stem)" if "BGM" in profile and "NO_EXTERNAL" not in profile else ", no BGM stem)")),
            "audience_score_stage": "REQUIRED_REVIEW" if strict_current else False,
            "publish_path": "NONE — this line never uploads to a platform",
            "human_step": "one checkpoint per finished episode (S8 approve)",
        },
        "phase_final_gate_count": len(FINAL_GATES),
        "phase_release_gate_count": len(RELEASE_GATES),
        "applicable": [{"gate_id": gate, "stage": stages.get(gate)} for gate in APPLICABLE_E],
        "not_applicable": [{"gate_id": gate, "stage": stages.get(gate), **detail}
                           for gate, detail in sorted(NOT_APPLICABLE_E.items())],
        "applicable_count": len(APPLICABLE_E),
        "not_applicable_count": len(NOT_APPLICABLE_E),
        "mechanism": {
            "registry_has_applies_when": False,
            "runner_has_skip_or_waiver": False,
            "n_a_status_exists_but_runner_cannot_emit_it":
                "tools/gate_result_contract.ALLOWED_STATUSES = {PASS, FAIL, N_A, PENDING_MANUAL}; "
                "episode_stage_gate_runner only ever writes PASS/FAIL",
            "chosen_route": (
                "CURRENT_PORTABLE executes every registered final/release gate; missing evidence "
                "blocks. Legacy replay invokes the historically recorded explicit gate list."
            ),
            "explicitly_not_done": "no hand-written N_A row in qa/gate_results/ "
                                   "(FINAL-CUT-NO-SELF-WAIVER forbids self-issued waivers) and "
                                   "no fabricated audience_report, objective metrics, event ledger, "
                                   "or bgm_stem",
            "run_episode_qa_sh_limitation":
                "tools/run_episode_qa.sh hardcodes --phase final --phase release, so it cannot "
                "express this narrowing; it also defaults PYTHON_BIN to "
                ".s3_relay_env_py312/bin/python3 which does not exist in this clone.",
        },
        "open_decision": "D-12 FINAL_PHASE_GATE_APPLICABILITY_HAS_NO_MECHANISM",
        "policy_profile": _policy.selected(),
        "registered_gate_omission_allowed": not strict_current,
    }


def build_bundle(episode: str, *, out: Path | None = None) -> dict[str, Any]:
    p = QaPaths(episode)
    deliver = RUNTIME / "deliverables" / episode
    # Versioned reruns (for example after a corrective audio pass) must not
    # overwrite immutable v1 evidence.  The normal path remains unchanged;
    # callers may explicitly select a verified final artifact for this QA run.
    final_video = Path(os.environ.get("NALU_FINAL_VIDEO_PATH") or
                       (deliver / f"{episode}_final_9x16.mp4"))
    canonical = p.narrative
    final_qa = p.final_qa_dir
    profile = _audio_profile(episode)
    applicable, not_applicable, unsatisfiable = _gate_sets(episode)
    bgm_description = (
        "selective narrative BGM stem"
        if profile in {"NATIVE_MULTIMODAL_SELECTIVE_BGM", "LAYERED_POST_WITH_BGM"}
        else "no external BGM stem"
    )
    bundle: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "episode": episode,
        "generated_at": now(),
        "generated_by": TOOL_ID,
        "_line_profile": (
            f"{profile}, {bgm_description}, 9:16 delivery, "
            "real audience detectors, no automatic publish path"
        ),
        "_applicable_gates": list(applicable),
        "_not_applicable_gates": sorted(not_applicable),
        "canonical_script": portable(canonical),
        "canonical_script_sha256": sha256_file(canonical),
        "final_video": portable(final_video),
        "final_package_manifest": portable(p.assembly / f"{episode}_FINAL_PACKAGE_BLOCKERS.json"),
        "ci_report": portable(final_qa / f"{episode}_REGRESSION_CI.json"),
        "render_plan": portable(p.assembly / f"{episode}_final_render_plan.json"),
        "ffmpeg": require_ffmpeg(),
        # native-audio line: the published mix and the final video are the same file
        "published_mix": portable(final_video),
        "audio_provenance_manifest": portable(
            p.assembly / f"{episode}_AUDIO_PROVENANCE_MANIFEST.json"),
        "edit_project": portable(p.agentcut_project if hasattr(p, "agentcut_project")
                                 else p.assembly / f"{episode}_agentcut_project.json"),
        "credit_ledger": portable(RT / "budget/ledger.json"),
        "watch_report": portable(RT / f"pipeline_state/approvals/{episode}.APPROVED.json"),
        # seq=19: sha-bound detector report written by S7 (tools/final_cut_audience_detectors.py)
        "final_cut_audience_report": portable(p.assembly / f"{episode}_FINAL_CUT_AUDIENCE_DETECTORS.json"),
        "generation_contract": portable(p.contract),
        "writer_manifest": portable(p.writer_manifest),
        "lexicon": portable(p.lexicon),
        "voice_cast": portable(p.voice_cast),
    }
    if not unsatisfiable:
        # Current portable policy: these files are real evidence producers, not
        # placeholders. Their absence is counted below and blocks S7.
        bundle.update({
            "audience_report": portable(
                p.final_qa_dir / f"{episode}_AUDIENCE_SCORE_REPORT.json"
            ),
            "final_cut_metrics": portable(
                p.final_qa_dir / f"{episode}_FINAL_CUT_OBJECTIVE_METRICS.json"
            ),
            "event_ledger": portable(
                p.final_qa_dir / f"{episode}_FINAL_CUT_EVENT_LEDGER.json"
            ),
        })
    if "bgm_stem" not in unsatisfiable:
        bundle["bgm_stem"] = portable(p.assembly / f"{episode}_bgm_stem.wav")
    missing: list[dict[str, Any]] = []
    for key in unsatisfiable:
        missing.append({
            "key": key,
            "status": "NOT_PRODUCED_BY_DESIGN",
            "consumed_by": BUNDLE_KEYS[key]["gates"],
            "reason": NOT_APPLICABLE.get(
                "BGM-SOURCE-PRIORITY-AUTHENTICITY" if key == "bgm_stem"
                else "AUDIENCE-SCORE-PRE-RELEASE")["reason"],
        })
    bundle["_keys_not_produced"] = missing
    present, absent = [], []
    for key, value in bundle.items():
        if key.startswith("_") or key in {"schema", "episode", "generated_at",
                                          "generated_by", "canonical_script_sha256"}:
            continue
        path = Path(str(value))
        resolved = path if path.is_absolute() else ENGINE / path
        (present if resolved.exists() else absent).append(
            {"key": key, "path": str(resolved)})
    bundle["_evidence_present"] = present
    bundle["_evidence_absent"] = absent
    out = Path(out) if out else p.evidence_bundle
    write_json(out, bundle)
    return {
        "schema": "nalu.final_qa_bundle_build.v1",
        "episode": episode,
        "bundle": str(out),
        "bundle_sha256": sha256_file(out),
        "keys_total": len([k for k in bundle if not k.startswith("_")
                           and k not in {"schema", "episode", "generated_at", "generated_by"}]),
        "keys_present": len(present),
        "keys_absent": len(absent),
        "absent": absent,
        "keys_not_produced": missing,
        "status": "COMPLETE" if not absent else "INCOMPLETE_EVIDENCE_NOT_YET_PRODUCED",
    }


def run_stage_gates(episode: str, *, gates: tuple[str, ...] | None = None,
                    bundle: Path | None = None, out_dir: Path | None = None
                    ) -> dict[str, Any]:
    p = QaPaths(episode)
    gates = gates if gates is not None else _gate_sets(episode)[0]
    bundle = Path(bundle) if bundle else p.evidence_bundle
    out_dir = Path(out_dir) if out_dir else (p.final_qa_dir / "mandatory_stage_gates")
    argv: list[Any] = [VENV, ENGINE / "tools/episode_stage_gate_runner.py",
                       "--episode", episode, "--evidence-bundle", bundle,
                       "--out-dir", out_dir, "--registry", GATE_REGISTRY]
    for gate in gates:
        argv += ["--gate", gate]
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ENGINE), str(ENGINE / "tools")])
    completed = subprocess.run([str(item) for item in argv], cwd=str(ENGINE), env=env,
                               capture_output=True, text=True, timeout=3600)
    summary = read_json(out_dir / "episode_stage_gate_execution_summary.json", {}) or {}
    return {
        "argv": [str(item) for item in argv],
        "command": " ".join(str(item) for item in argv),
        "exit_code": completed.returncode,
        "summary_path": str(out_dir / "episode_stage_gate_execution_summary.json"),
        "status": summary.get("status"),
        "failures": (summary.get("failures") or [])[:12],
        "gates_requested": list(gates),
        "gate_rows": [{"gate_id": row.get("gate_id"), "status": row.get("status"),
                       "implementation_status": row.get("implementation_status"),
                       "failures": (row.get("failures") or [])[:4]}
                      for row in summary.get("gates") or summary.get("results") or []],
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }


def route_status(episode: str) -> dict[str, Any]:
    p = QaPaths(episode)
    deliver = RUNTIME / "deliverables" / episode
    final_video = Path(os.environ.get("NALU_FINAL_VIDEO_PATH") or
                       (deliver / f"{episode}_final_9x16.mp4"))
    qa_sh = [str(ENGINE / "tools/run_episode_qa.sh"),
             "--video", str(final_video),
             "--config", str(p.assembly / f"{episode}_continuity_config.json"),
             "--manifest", str(p.assembly / f"{episode}_asset_binding_manifest.json"),
             "--blocker-manifest", str(p.assembly / f"{episode}_FINAL_PACKAGE_BLOCKERS.json"),
             "--speaker-evidence",
             str(p.assembly / f"{episode}_SPEAKER_IDENTITY_VOICE_EVIDENCE.json"),
             "--episode", episode,
             "--evidence-bundle", str(p.evidence_bundle),
             "--render-plan", str(p.assembly / f"{episode}_final_render_plan.json"),
             "--out", str(deliver / "final_qa")]
    applicable_gates, not_applicable, _ = _gate_sets(episode)
    return {
        "producer": f"{__file__} build --episode {episode}",
        "bundle": str(p.evidence_bundle),
        "bundle_present": p.evidence_bundle.is_file(),
        "policy_profile": _policy.selected(),
        "applicable_gates": list(applicable_gates),
        "not_applicable_gates": sorted(not_applicable),
        "runner_command": " ".join([str(VENV),
                                    str(ENGINE / "tools/episode_stage_gate_runner.py"),
                                    "--episode", episode, "--evidence-bundle",
                                    str(p.evidence_bundle), "--out-dir",
                                    str(p.final_qa_dir / "mandatory_stage_gates"),
                                    "--registry", str(GATE_REGISTRY)]
                                   + [x for gate in applicable_gates for x in ("--gate", gate)]),
        "run_episode_qa_command": "PYTHON_BIN=" + str(VENV) + " /bin/bash " + " ".join(qa_sh),
        "run_episode_qa_caveats": [
            "CURRENT_PORTABLE intentionally runs every registered final/release gate; missing "
            "BGM or audience evidence is blocking rather than silently narrowed",
            "PYTHON_BIN default .s3_relay_env_py312/bin/python3 does not exist in this clone",
            "REVIEW_REQUIRED_BLOCKING is a block, not a pass; exit 1 with an empty "
            "machine_failures list means anchor review is outstanding",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("applicability", "build", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--episode", required=True)
        if name == "build":
            sp.add_argument("--out", type=Path)
    rn = sub.add_parser("run")
    rn.add_argument("--episode", required=True)
    rn.add_argument("--gate-subset", choices=["applicable", "all"], default="applicable")
    rn.add_argument("--bundle", type=Path)
    rn.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    if args.command == "applicability":
        record = applicability(args.episode)
        p = QaPaths(args.episode)
        write_json(p.final_qa_dir / f"{args.episode}_FINAL_GATE_APPLICABILITY.json", record)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(route_status(args.episode), ensure_ascii=False, indent=2))
        return 0
    if args.command == "build":
        record = build_bundle(args.episode, out=args.out)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0 if record["status"] == "COMPLETE" else 2

    gates = (_gate_sets(args.episode)[0] if args.gate_subset == "applicable"
             else (*FINAL_GATES, *RELEASE_GATES))
    record = run_stage_gates(args.episode, gates=gates, bundle=args.bundle,
                             out_dir=args.out_dir)
    print(json.dumps({k: v for k, v in record.items()
                      if k not in ("stdout_tail", "stderr_tail", "argv")},
                     ensure_ascii=False, indent=2))
    # a compact, never-truncated machine line for the orchestrator
    print(json.dumps({"status": record["status"], "exit_code": record["exit_code"],
                      "summary_path": record["summary_path"],
                      "gates_requested": len(record["gates_requested"]),
                      "failures": record["failures"][:6]}, ensure_ascii=False))
    return record["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
