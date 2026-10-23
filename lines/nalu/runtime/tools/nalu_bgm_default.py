"""Background music default ON for the nalu line (line owner 2026-10-22: 「背景音乐开吧」).

The writer still owns the creative decision in ``audio_contract.bgm`` of the generation contract:

* an authored SELECTIVE / REQUIRED declaration is used exactly as written;
* an explicit opt-out — a string starting with ``NONE`` (``NONE``, ``NONE_WHOLE_EPISODE`` ...),
  ``FORBIDDEN``, or an object whose ``mode`` is ``NONE``/``FORBIDDEN`` or that sets ``"opt_out": true`` —
  still disables music;
* anything else (``bgm`` missing/empty, ``NO_BGM`` — the value writers used while BGM was a separate
  paid category — or an object without a mode) is treated as "not decided" and gets the line default:
  ``SELECTIVE_NARRATIVE_CUES`` with one ending cue under the trailing shots of the last scene
  (CAMERA_GRAMMAR_V1 contracts: one restrained bed over the trailing shots across scenes, entering on a
  scene cut after the opening hook and running to the end, with 2.0 s / 1.5 s fades).

The writer-sealed contract is never modified.  When the default applies, the pipeline writes a derived
copy (identical except ``audio_contract.bgm``) and hands only that copy to the selective-BGM tool (S6
source plan / S7 plan-QA-mix) and to the S7 AgentCut builder (so audio_profile_binding resolves
NATIVE_MULTIMODAL_SELECTIVE_BGM and stays sha-bound to the copy).  Video prompt compilation keeps the
original contract, so native video generation is untouched.  Loudness/ducking parameters are the
selective-BGM tool's own defaults (volume 0.14, dialogue duck -8 dB).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[4] / "tools") not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parents[4] / "tools"))
import camera_grammar_policy as _cg

DEFAULT_POLICY_ID = "NALU_BGM_DEFAULT_ON_20261022"
DEFAULT_MODE = "SELECTIVE_NARRATIVE_CUES"
DEFAULT_CUE_ID = "DEFAULT_EPISODE_ENDING"
DEFAULT_NARRATIVE_FUNCTION = "EPISODE_ENDING_CLIFFHANGER"
DEFAULT_BRIEF = ("restrained cinematic instrumental underscore for the closing moments of a short-drama "
                 "episode: low sustained strings, a soft piano pulse and a slow build of tension toward a "
                 "cliffhanger; no vocals, no lyrics, no drum hits")
#: CAMERA_GRAMMAR_V1 contracts (lab Holmes E01: the last-scene cue entered abruptly on a scene cut at 37 s):
#: one restrained bed from just after the opening hook to the end, entering on a scene cut, longer fades.
EPISODE_BRIEF = ("restrained cinematic instrumental underscore for a whole short-drama episode: low sustained "
                 "strings and a soft piano pulse that stay under the dialogue, slowly building tension toward "
                 "the closing cliffhanger; no vocals, no lyrics, no drum hits")
SCENE_CUT_SNAP_SECONDS = 3.0
EPISODE_FADE_IN_S, EPISODE_FADE_OUT_S = 2.0, 1.5
#: Margins under nalu_selective_bgm's coverage policy (<= 85 % coverage, >= 8 s ambience-only), so the
#: rendered-window plan (proportional unit windows) cannot tip a default cue over the limits.
MAX_DEFAULT_COVERAGE_RATIO = 0.80
MIN_DEFAULT_AMBIENCE_SECONDS = 9.0

SELECTIVE_MODES = {"SELECTIVE", "SELECTIVE_NARRATIVE_CUES"}
REQUIRED_MODES = {"REQUIRED", "WHOLE_EPISODE", "LAYERED"}
OPT_OUT_MODES = {"NONE", "FORBIDDEN"}


def _mode(declaration: Any) -> str:
    if isinstance(declaration, dict):
        return str(declaration.get("mode") or declaration.get("usage_mode") or "").strip().upper()
    return str(declaration or "").strip().upper()


def is_explicit_opt_out(declaration: Any) -> bool:
    if isinstance(declaration, dict):
        if declaration.get("opt_out") is True:
            return True
        mode = _mode(declaration)
        return mode in OPT_OUT_MODES or mode.startswith("NONE")
    mode = _mode(declaration)
    return mode in OPT_OUT_MODES or mode.startswith("NONE")


def is_authored_music(declaration: Any) -> bool:
    """An authored decision that already asks for music (selective cues / windows or required)."""
    if isinstance(declaration, dict):
        mode = _mode(declaration)
        if mode in SELECTIVE_MODES or mode in REQUIRED_MODES:
            return True
        return declaration.get("used") is True and bool(declaration.get("windows"))
    if declaration is None:
        return False
    text = str(declaration).strip()
    upper = text.upper()
    if not text or upper == "NO_BGM" or is_explicit_opt_out(declaration):
        return False
    return True  # authored prose (e.g. "LAST_SCENE_ONLY_LOW_SUSTAIN") stays with audio_profile_binding


def default_cues(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """One ending cue over the trailing shots of the last scene, inside the coverage margins; [] if the
    contract is too short or has no usable shots."""
    shots = [row for row in (contract.get("shots") or []) if isinstance(row, dict)
             and str(row.get("shot_id") or "") and float(row.get("target_seconds") or 0) > 0]
    if not shots:
        return []
    total = sum(float(row["target_seconds"]) for row in shots)
    limit = min(total * MAX_DEFAULT_COVERAGE_RATIO, total - MIN_DEFAULT_AMBIENCE_SECONDS)
    if limit <= 0:
        return []
    if _cg.active(contract):
        return _episode_cues(shots, limit)
    last_scene = str(shots[-1].get("scene_id") or "")
    picked: list[str] = []
    seconds = 0.0
    for row in reversed(shots):
        if str(row.get("scene_id") or "") != last_scene:
            break
        if seconds + float(row["target_seconds"]) > limit:
            break
        picked.insert(0, str(row["shot_id"]))
        seconds += float(row["target_seconds"])
    if not picked:
        return []
    return [{"cue_id": DEFAULT_CUE_ID, "shots": picked, "narrative_function": DEFAULT_NARRATIVE_FUNCTION,
             "brief": DEFAULT_BRIEF}]


def _episode_cues(shots: list[dict[str, Any]], limit: float) -> list[dict[str, Any]]:
    """Trailing shots across scenes, from the end backwards up to the coverage limit; the start moves
    forward to a scene cut when one lies within SCENE_CUT_SNAP_SECONDS of it (never earlier: limits hold)."""
    seconds = 0.0
    first = len(shots)
    for index in range(len(shots) - 1, -1, -1):
        if seconds + float(shots[index]["target_seconds"]) > limit:
            break
        seconds += float(shots[index]["target_seconds"])
        first = index
    if first >= len(shots):
        return []
    starts = [0.0]
    for row in shots:
        starts.append(starts[-1] + float(row["target_seconds"]))
    for index in range(first, len(shots)):
        if starts[index] - starts[first] > SCENE_CUT_SNAP_SECONDS + 1e-9:
            break
        if index == 0 or str(shots[index].get("scene_id") or "") != str(shots[index - 1].get("scene_id") or ""):
            first = index
            break
    return [{"cue_id": DEFAULT_CUE_ID, "shots": [str(row["shot_id"]) for row in shots[first:]],
             "narrative_function": DEFAULT_NARRATIVE_FUNCTION, "brief": EPISODE_BRIEF,
             "fade_in_s": EPISODE_FADE_IN_S, "fade_out_s": EPISODE_FADE_OUT_S}]


def resolve(contract: dict[str, Any]) -> dict[str, Any]:
    """{"source": AUTHORED|AUTHORED_OPT_OUT|LINE_DEFAULT|DEFAULT_NOT_APPLICABLE, "declaration": ...}."""
    audio = contract.get("audio_contract") if isinstance(contract.get("audio_contract"), dict) else {}
    authored = audio.get("bgm")
    if is_explicit_opt_out(authored):
        return {"source": "AUTHORED_OPT_OUT", "declaration": authored}
    if is_authored_music(authored):
        return {"source": "AUTHORED", "declaration": authored}
    cues = default_cues(contract)
    if not cues:
        return {"source": "DEFAULT_NOT_APPLICABLE", "declaration": authored,
                "reason": "NO_SHOTS_OR_TOO_SHORT_FOR_A_DEFAULT_CUE"}
    return {"source": "LINE_DEFAULT", "policy": DEFAULT_POLICY_ID,
            "declaration": {"mode": DEFAULT_MODE, "cues": cues, "default_policy": DEFAULT_POLICY_ID,
                            "authored_declaration": authored}}


def effective_contract(contract: dict[str, Any]) -> dict[str, Any] | None:
    """The derived contract when the line default applies, else None (use the authored contract)."""
    decision = resolve(contract)
    if decision["source"] != "LINE_DEFAULT":
        return None
    derived = copy.deepcopy(contract)
    derived.setdefault("audio_contract", {})["bgm"] = decision["declaration"]
    return derived


def write_effective_contract(contract_path: Path, out_path: Path) -> dict[str, Any]:
    """Write the derived contract (byte-stable: rewritten only when its content changes).

    Returns {"source", "contract": <path to hand to the BGM tool / AgentCut builder>, ...}."""
    contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    decision = resolve(contract)
    derived = effective_contract(contract)
    if derived is None:
        return {"source": decision["source"], "contract": str(contract_path),
                **({"reason": decision["reason"]} if decision.get("reason") else {})}
    payload = json.dumps(derived, ensure_ascii=False, indent=2) + "\n"
    out_path = Path(out_path)
    if not out_path.is_file() or out_path.read_text(encoding="utf-8") != payload:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
    return {"source": "LINE_DEFAULT", "policy": DEFAULT_POLICY_ID, "contract": str(out_path),
            "authored_contract": str(contract_path), "cues": derived["audio_contract"]["bgm"]["cues"]}
