#!/usr/bin/env python3
"""A 5-second generated unit is not a 5-second shot. Say where it gets cut.

Authorization: `B7-ADV-01` (CL2X-1024 / CL2X-1026), which registered a
*third-class* defect: two hard gates that are each individually correct, with
nobody owning the seam between them.

  - Generation floor (`ROGER-20260718`, CL2X-309): every unit is costed
    individually inside Seedance's 4-15s window. Batch 7 landed all fight units
    at 4-6s.
  - Fight baseline v2.1 (2026-07-13, Roger-approved, 莲花楼/刺客学苑 standard):
    a fight passes at ASL <=2.2s with >=15% of shots under 1s, over >=3
    burst<->wind-up rounds.

Measured on disk (three data points, not one accident):
    E57 30-1+30-2   13 units / 62s net -> one-cut-per-unit ASL 5.23s, needs >=28
    E58 31-3        10 units / 34s net -> 4.80s, needs >=15
    E51 24-3         8 units / 20s+   -> 5.50s, needs >=9

With a 4s generation floor and no subdivision, "shots under 1s >= 15%" is not
merely hard, it is arithmetically unreachable: the number is structurally 0.
The three escapes all hit an existing gate — one cut per unit fails the fight
baseline; cutting freely on the timeline is stopped by `cut_motivation_gate`
(the E19R disease: 71 seams, 0 reasons); stretching or ramping to fill is the
E17 disease (periodic duplicate frames are post-retime's fingerprint).

So the missing thing is not a threshold. It is a *field*: which frames inside
one generated performance become separate shots, and why each of them does.
This gate demands that field, then checks the plan actually delivers the
baseline instead of merely claiming it.

Ownership: `cut_plan` describes 怎么拍, never 拍什么, so under
`ROGER-20260718-SCENE-AUTHORITY-LOCK` it belongs to the production line.
The script layer writes zero new fields.

Outputs `qingshan.fight_cut_plan_gate_result.v1`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cut_motivation_gate import (  # noqa: E402
    CUT_REASONS,
    METRIC_LANGUAGE,
    required_cut_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_ID = "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
GATE_REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"


def _registered_parameters() -> dict[str, Any]:
    registry = json.loads(GATE_REGISTRY.read_text(encoding="utf-8"))
    gate = next((row for row in registry.get("gates") or [] if row.get("gate_id") == GATE_ID), None)
    if gate is None:
        raise RuntimeError("FIGHT_CUT_PLAN_GATE_AUTHORITY_NOT_REGISTERED")
    return gate.get("parameters") or {}


PARAMETERS = _registered_parameters()

# All thresholds are read from the existing registered action gate. The edit
# gate does not own a second set of numbers.
FIGHT_MAX_ASL = float(PARAMETERS["fight_cut_max_asl_seconds"])
FIGHT_MIN_SUB_SECOND_SHARE = float(PARAMETERS["fight_cut_min_sub_second_share"])
FIGHT_MIN_PHASE_ROUNDS = int(PARAMETERS["fight_cut_min_phase_rounds"])
FIGHT_MIN_SUB_CUTS_PER_UNIT = int(PARAMETERS["combat_editorial_cuts_per_generation_min"])
FIGHT_MAX_SUB_CUTS_PER_UNIT = int(PARAMETERS["combat_editorial_cuts_per_generation_max"])

# Below this, a "shot" is not a shot. Anything shorter is either a subliminal
# flash or the residue of a retime, and both are already banned elsewhere.
MIN_SUB_CUT_SECONDS = float(PARAMETERS["fight_cut_min_sub_cut_seconds"])

# Tolerance for sub-cut durations summing back to the generated unit. One frame
# at 30fps is 0.033s; 0.05 allows rounding in the plan, not a missing shot.
SUM_TOLERANCE_SECONDS = float(PARAMETERS["fight_cut_sum_tolerance_seconds"])

# Only these phases exist in the breathing structure (呼吸结构门).
PHASES = ("windup", "burst", "result")

# A retime is not a cutting decision, it is the thing this gate exists to make
# unnecessary. Declaring one anywhere in a fight plan is an immediate BLOCK.
RETIME_KEYS = ("speed_ramp", "retime", "time_stretch", "slowmo", "speed_factor")
CANONICAL_COMBAT_PATTERNS = (
    re.compile(r"△【打斗(?:[·・][^】]*)?】"),
    re.compile(r"FS-1\s*完整打斗"),
    re.compile(r"FS-1\s*窗口锚"),
)

# --- 净打斗秒数: one implementation, and it always says which ruler it used ---
#
# CL2X-1035 flagged that 净打斗秒数 had two definitions. CL2X-1039 measured the
# gap on the three batch-9 fight scenes as they stand on disk:
#
#   E62 35-4   script says 35s   scene sums to 45s   shortfall 7 vs 12 cuts
#   E63 36-4   script says 33s   scene sums to 42s   shortfall 6 vs 11 cuts
#   E64 37-3   script says 31s   scene sums to 36s   shortfall 7 vs  9 cuts
#
# The old `diagnose_unplanned` wrote `net_fight_seconds or sum(units)`, so an
# absent key silently swapped ruler and the output field kept the same name.
# That is not a false FAIL (B9-ADV-06) — it is worse in one specific way: the
# fallback returns a *plausible number* rather than an error, so nothing in the
# output tells the reader which of the two quantities they are holding. The
# shortfall is the only thing this diagnosis exists to produce, and it moved by
# 5/5/2 cuts on the key alone.
#
# Rule: the value and the basis travel together, always, and both rulers are
# reported so the reader can see the one that was not used.
NET_BASIS_DECLARED = "DECLARED"                      # script layer said so
NET_BASIS_DERIVED_FULL_SCENE = "DERIVED_FULL_SCENE"  # summed units; includes non-fight seconds
NET_BASIS_UNDETERMINED = "UNDETERMINED"              # neither available; refuse to invent one

# Declared vs derived may legitimately differ: a fight *scene* usually carries
# wind-up and aftermath seconds that are not fight. Beyond this the divergence
# is worth saying out loud, because it is the difference between two demands.
NET_DIVERGENCE_ADVISE_SECONDS = 0.5


def resolve_net_fight_seconds(scene: dict[str, Any]) -> dict[str, Any]:
    """Single source of truth for 净打斗秒数.

    Returns seconds + basis + both underlying rulers. Never substitutes one
    ruler for the other without saying so, and never returns a number when it
    has none — `UNDETERMINED` is a state, not a zero.
    """
    raw_declared = scene.get("net_fight_seconds")
    declared = (
        float(raw_declared)
        if isinstance(raw_declared, (int, float)) and not isinstance(raw_declared, bool) and raw_declared > 0
        else None
    )

    summed = 0.0
    for unit in scene.get("units") or []:
        value = unit.get("generated_duration") if isinstance(unit, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            summed += float(value)
    derived = round(summed, 2) if summed > 0 else None

    if declared is not None:
        seconds, basis = declared, NET_BASIS_DECLARED
    elif derived is not None:
        seconds, basis = derived, NET_BASIS_DERIVED_FULL_SCENE
    else:
        seconds, basis = None, NET_BASIS_UNDETERMINED

    diverges = (
        declared is not None
        and derived is not None
        and abs(declared - derived) > NET_DIVERGENCE_ADVISE_SECONDS
    )
    return {
        "seconds": seconds,
        "basis": basis,
        "declared": declared,
        "derived_full_scene": derived,
        "diverges": diverges,
    }


def _fail(gate: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"severity": "BLOCK", "gate": gate, "detail": detail, **extra}


def _advise(gate: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"severity": "ADVISE", "gate": gate, "detail": detail, **extra}


def check_unit(unit: dict[str, Any], *, scene_id: str) -> tuple[list[dict], list[dict]]:
    """Validate one generated unit's cut_plan. Returns (findings, sub_cuts)."""
    findings: list[dict[str, Any]] = []
    unit_id = str(unit.get("unit_id") or "?")
    generated = unit.get("generated_duration")

    for key in RETIME_KEYS:
        if unit.get(key):
            findings.append(
                _fail("F7_NO_RETIME", f"{unit_id} declares {key}={unit[key]!r}", unit_id=unit_id)
            )

    plan = unit.get("cut_plan")
    if not isinstance(plan, list) or not plan:
        # This is the whole point of the gate, so it is a BLOCK and not a warning.
        findings.append(
            _fail(
                "F1_PLAN_PRESENT",
                f"{unit_id} is a fight unit with no cut_plan; "
                f"one cut per unit cannot reach fight baseline v2.1",
                unit_id=unit_id,
            )
        )
        return findings, []

    if not FIGHT_MIN_SUB_CUTS_PER_UNIT <= len(plan) <= FIGHT_MAX_SUB_CUTS_PER_UNIT:
        findings.append(
            _fail(
                "F1_PLAN_PRESENT",
                f"{unit_id} has {len(plan)} sub-cuts; registered range is "
                f"{FIGHT_MIN_SUB_CUTS_PER_UNIT}-{FIGHT_MAX_SUB_CUTS_PER_UNIT}",
                unit_id=unit_id,
            )
        )

    if not isinstance(generated, (int, float)) or generated <= 0:
        findings.append(_fail("F2_SUM_MATCH", f"{unit_id} has no generated_duration", unit_id=unit_id))
        return findings, []

    subs: list[dict[str, Any]] = []
    notes_seen: list[str] = []
    for index, raw in enumerate(plan, start=1):
        label = f"{unit_id}#{index}"
        if not isinstance(raw, dict):
            findings.append(_fail("F3_REASON", f"{label} is not an object", unit_id=unit_id))
            continue

        # Continuity fields are inherited from the unit: sub-cuts of one
        # performance share scene, key light and axis by construction. Making
        # the author retype them would be the kind of ceremony that gets
        # rubber-stamped.
        merged = {**{k: v for k, v in unit.items() if k != "cut_plan"}, **raw}
        try:
            required_cut_metadata(merged, label=label)
        except ValueError as exc:
            findings.append(_fail("F3_REASON", str(exc), unit_id=unit_id, sub=label))
            continue

        duration = raw.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            findings.append(_fail("F2_SUM_MATCH", f"{label} has no positive duration", sub=label))
            continue
        if duration < MIN_SUB_CUT_SECONDS:
            findings.append(
                _fail(
                    "F2_SUM_MATCH",
                    f"{label} is {duration:.2f}s, under the {MIN_SUB_CUT_SECONDS}s floor",
                    sub=label,
                )
            )

        phase = raw.get("phase")
        if phase not in PHASES:
            findings.append(
                _fail("F6_PHASE", f"{label} phase={phase!r} not in {PHASES}", sub=label)
            )

        # Anti-Goodhart, same shape as the 573(4) mechanical-default lesson:
        # a plan that pastes one sentence onto every sub-cut has not made a
        # cutting decision, it has filled in a form.
        note = str(raw.get("cut_reason_note") or raw.get("action") or "").strip()
        if note:
            if METRIC_LANGUAGE.search(note):
                findings.append(_fail("F3_REASON", f"{label} uses metric language", sub=label))
            if note in notes_seen:
                findings.append(
                    _fail(
                        "F4_UNIQUE_ACTION",
                        f"{label} repeats an earlier justification verbatim: {note!r}",
                        sub=label,
                    )
                )
            notes_seen.append(note)

        subs.append({"label": label, "duration": float(duration), "phase": phase, "scene_id": scene_id})

    planned = sum(s["duration"] for s in subs)
    if subs and abs(planned - float(generated)) > SUM_TOLERANCE_SECONDS:
        findings.append(
            _fail(
                "F2_SUM_MATCH",
                f"{unit_id} cut_plan sums to {planned:.2f}s but the unit is {float(generated):.2f}s",
                unit_id=unit_id,
            )
        )
    return findings, subs


def check_scene(scene: dict[str, Any]) -> dict[str, Any]:
    scene_id = str(scene.get("scene_id") or "?")
    findings: list[dict[str, Any]] = []
    subs: list[dict[str, Any]] = []
    for unit in scene.get("units") or []:
        unit_findings, unit_subs = check_unit(unit, scene_id=scene_id)
        findings.extend(unit_findings)
        subs.extend(unit_subs)

    net = resolve_net_fight_seconds(scene)
    metrics: dict[str, Any] = {
        "shot_count": len(subs),
        # Named for what it is. The seconds this gate divides by are the seconds
        # of authored cut plan, which is the whole scene — not 净打斗秒数.
        "net_fight_seconds": net["seconds"],
        "net_fight_basis": net["basis"],
        "net_fight_declared": net["declared"],
        "net_fight_derived_full_scene": net["derived_full_scene"],
    }
    if net["diverges"]:
        # Not a script defect and not a plan defect: it is the seam. The fight
        # baseline was standardised on fight footage, and nobody has ever ruled
        # on whether the wind-up/aftermath seconds inside a fight scene belong
        # in the ASL denominator. Say the two numbers; do not pick one quietly.
        findings.append(
            _advise(
                "F8_NET_BASIS",
                f"{scene_id} 净打斗 declared {net['declared']:.2f}s but the scene sums to "
                f"{net['derived_full_scene']:.2f}s; ASL below is measured over the scene, "
                f"which demands "
                f"{int(-(-net['derived_full_scene'] // FIGHT_MAX_ASL)) - int(-(-net['declared'] // FIGHT_MAX_ASL))}"
                f" more cuts than the declared fight portion would",
                scene_id=scene_id,
                declared=net["declared"],
                derived_full_scene=net["derived_full_scene"],
            )
        )
    if subs:
        total = sum(s["duration"] for s in subs)
        asl = total / len(subs)
        sub_second = sum(1 for s in subs if s["duration"] < 1.0) / len(subs)
        metrics.update(
            {
                "planned_seconds": round(total, 2),
                "asl": round(asl, 3),
                "asl_basis": "PLANNED_SECONDS_WHOLE_SCENE",
                "sub_second_share": round(sub_second, 4),
            }
        )
        if asl > FIGHT_MAX_ASL:
            findings.append(
                _fail("F5_BASELINE_V21", f"{scene_id} ASL {asl:.2f}s > {FIGHT_MAX_ASL}s", scene_id=scene_id)
            )
        if sub_second < FIGHT_MIN_SUB_SECOND_SHARE:
            findings.append(
                _fail(
                    "F5_BASELINE_V21",
                    f"{scene_id} shots under 1s = {sub_second:.1%} < {FIGHT_MIN_SUB_SECOND_SHARE:.0%}",
                    scene_id=scene_id,
                )
            )

        # Breathing structure: count burst<->wind-up alternations, not bursts.
        # Three bursts in a row is a machine-gun, which the baseline calls FAIL.
        phases = [s["phase"] for s in subs if s["phase"] in ("windup", "burst")]
        collapsed = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
        rounds = sum(1 for i in range(1, len(collapsed)) if collapsed[i] == "burst")
        metrics["phase_rounds"] = rounds
        if rounds < FIGHT_MIN_PHASE_ROUNDS:
            findings.append(
                _fail(
                    "F6_PHASE",
                    f"{scene_id} has {rounds} burst<->windup rounds, needs {FIGHT_MIN_PHASE_ROUNDS}",
                    scene_id=scene_id,
                )
            )

    return {"scene_id": scene_id, "metrics": metrics, "findings": findings}


def run(plan: dict[str, Any], *, canonical_text: str | None = None) -> dict[str, Any]:
    scenes = [check_scene(s) for s in plan.get("fight_scenes") or []]
    findings = [f for s in scenes for f in s["findings"]]
    canonical_combat = (
        any(pattern.search(canonical_text) for pattern in CANONICAL_COMBAT_PATTERNS)
        if canonical_text is not None else None
    )
    if not scenes:
        if plan.get("applicable") is False and canonical_combat is False:
            status = "PASS"
        else:
            status = "INVALID"
            findings = [_fail("F0_INPUT", "no fight_scenes in plan or no canonical no-fight proof")]
    elif plan.get("applicable") is False:
        status = "BLOCK"
        findings.append(_fail("F0_INPUT", "fight_scenes exist but plan declares applicable=false"))
    elif canonical_combat is False:
        status = "BLOCK"
        findings.append(_fail("F0_INPUT", "fight plan exists but canonical has no registered combat marker"))
    elif any(f["severity"] == "BLOCK" for f in findings):
        status = "BLOCK"
    elif findings:
        status = "ADVISE"
    else:
        status = "PASS"
    return {
        "schema": "qingshan.fight_cut_plan_gate_result.v1",
        "gate_id": GATE_ID,
        "authorization_ref": "B7-ADV-01 / CL2X-1224",
        "episode": plan.get("episode"),
        "applicability": "NOT_APPLICABLE" if not scenes and status == "PASS" else "APPLICABLE",
        "gate_status": status,
        "scenes": scenes,
        "findings": findings,
    }


def diagnose_unplanned(scene: dict[str, Any]) -> dict[str, Any]:
    """What a fight scene scores with one cut per generated unit.

    Diagnostic only — this is how E57/E58/E51 were measured for B7-ADV-01. It
    never admits anything; it exists so the size of the gap is a number rather
    than an assertion.
    """
    units = scene.get("units") or []
    resolved = resolve_net_fight_seconds(scene)
    net = resolved["seconds"]
    if net is None:
        # An undetermined input used to come back as a confident 0.0s, which
        # reads as "no fight to cut" — the most reassuring possible way to say
        # "I was not given anything to measure".
        return {
            "scene_id": scene.get("scene_id"),
            "units": len(units),
            "net_fight_seconds": None,
            "net_fight_basis": NET_BASIS_UNDETERMINED,
            "diagnosis": "UNDETERMINED_NO_NET_FIGHT_SECONDS",
            "note": "no declared 净打斗秒数 and no unit durations; nothing was measured",
        }
    count = len(units) or 1
    asl = net / count
    needed = int(-(-net // FIGHT_MAX_ASL))  # ceil
    return {
        "scene_id": scene.get("scene_id"),
        "units": len(units),
        "net_fight_seconds": round(net, 2),
        "net_fight_basis": resolved["basis"],
        "net_fight_declared": resolved["declared"],
        "net_fight_derived_full_scene": resolved["derived_full_scene"],
        "one_cut_per_unit_asl": round(asl, 2),
        "cuts_needed_for_baseline": needed,
        "shortfall": max(0, needed - len(units)),
        "sub_second_share_reachable": False,
        "note": "generation floor is 4s, so shots under 1s are structurally 0 without a cut_plan",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_positional", nargs="?", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--canonical-script", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--diagnose", action="store_true", help="report the gap, admit nothing")
    args = parser.parse_args()

    plan_path = args.plan or args.plan_positional
    if plan_path is None:
        parser.error("a plan path or --plan is required")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if args.diagnose:
        result = {
            "schema": "qingshan.fight_cut_plan_diagnosis.v1",
            "episode": plan.get("episode"),
            "scenes": [diagnose_unplanned(s) for s in plan.get("fight_scenes") or []],
        }
    else:
        canonical_text = args.canonical_script.read_text(encoding="utf-8") if args.canonical_script else None
        result = run(plan, canonical_text=canonical_text)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("gate_status") in (None, "PASS", "ADVISE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
