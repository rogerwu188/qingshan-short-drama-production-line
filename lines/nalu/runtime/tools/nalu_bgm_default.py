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
selective-BGM tool's own defaults (volume 0.14, dialogue duck -10 dB; BILI_V1: volume 0.24, see
bgm_cue_shaping.bed_volume).

WP5-C mood cues (craft_profile BILI_V1 + ``bgm_mood_cues: true``; ``~/nalu_lab/bili_work/CHANGE_SPEC.md``): when the
default applies and the writer marked scene moods (``pacing.scene_plan[].mood`` / ``pacing_scene_plan`` /
``scene_states[].mood``, ids or aliases of ``configs/BGM_MOOD_PALETTE_V1.json``), the default is 2-3 mood cues
instead of the one episode bed (``mood_cues``): consecutive scenes of one mood are one cue, at most
``MAX_MOOD_CUES``; a scene-card ``music_stop`` (true = the scene's PUNCHLINE shot, else its last shot; or a shot id;
or a shot's own ``music_stop``) ends the music on that shot's start (the shot and the rest of its scene stay
unscored).  The declaration carries ``series_cache: true`` (each mood is paid once per series) and
``hard_stop_shots``.  Without marked moods, or with the switch off (every LEGACY series), nothing changes.
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

try:
    from tools import craft_profile as _cp
except ModuleNotFoundError:  # pragma: no cover - runtime tools dir only
    import craft_profile as _cp

MOOD_POLICY_ID = "NALU_BGM_MOOD_CUES_BILI_V1_20261123"
MOOD_PALETTE_PATH = Path(__file__).resolve().parents[1] / "configs" / "BGM_MOOD_PALETTE_V1.json"
MAX_MOOD_CUES = 3
MIN_MOOD_CUE_SECONDS = 12.0   # bgm_cue_shaping.MIN_CUE_SECONDS: a shorter mood run joins its neighbour

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


# --------------------------------------------------------------------------------------------- WP5-C mood cues
def load_palette(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or MOOD_PALETTE_PATH).read_text(encoding="utf-8"))


def _mood_key(value: Any, palette: dict[str, Any]) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return None
    moods = palette.get("moods") or {}
    if text in moods:
        return text
    for key, row in moods.items():
        if text in {str(a).strip().lower().replace("-", "_").replace(" ", "_") for a in row.get("aliases") or []}:
            return key
    return None


def _scene_cards(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """scene_id -> merged scene card fields (pacing.scene_plan > pacing_scene_plan > scene_states)."""
    pacing = contract.get("pacing") if isinstance(contract.get("pacing"), dict) else {}
    cards: dict[str, dict[str, Any]] = {}
    for rows in (contract.get("scene_states"), contract.get("pacing_scene_plan"), pacing.get("scene_plan")):
        for row in rows or []:
            if isinstance(row, dict) and str(row.get("scene_id") or ""):
                cards.setdefault(str(row["scene_id"]), {}).update({k: v for k, v in row.items() if v not in (None, "")})
    return cards


def _beat_role(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    return str(spec.get("beat_role") or shot.get("beat_role") or "").strip().upper()


def _shot_flag(shot: dict[str, Any], key: str) -> bool:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    return shot.get(key) is True or spec.get(key) is True


def mood_cues_enabled(contract: dict[str, Any]) -> bool:
    """BILI_V1 + bgm_mood_cues (contract -> brief -> runtime qingshan.json); always False under LEGACY."""
    try:
        episode = str(contract.get("episode") or "") or None
        return _cp.bgm_mood_cues(contract, episode=episode)
    except Exception:  # noqa: BLE001 -- the switch must never break the default
        return False


def mood_cues(contract: dict[str, Any], palette: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """{"cues", "hard_stop_shots", "moods"} for a contract whose scenes carry moods; None when none is marked."""
    palette = palette or load_palette()
    moods_cfg = palette.get("moods") or {}
    max_cues = int(palette.get("max_cues_per_episode") or MAX_MOOD_CUES)
    shots = [row for row in (contract.get("shots") or []) if isinstance(row, dict)
             and str(row.get("shot_id") or "") and float(row.get("target_seconds") or 0) > 0]
    if not shots:
        return None
    cards = _scene_cards(contract)
    scenes: list[str] = []
    for row in shots:
        sid = str(row.get("scene_id") or "")
        if not scenes or scenes[-1] != sid:
            scenes.append(sid)
    marked = [_mood_key(cards.get(sid, {}).get("mood"), palette) for sid in scenes]
    if not any(marked):
        return None
    # unmarked scenes inherit the previous mood (a leading run: the first marked one)
    first = next(m for m in marked if m)
    moods, current = [], first
    for m in marked:
        current = m or current
        moods.append(current)
    # hard stops: the shot whose start ends the music; it and the rest of its scene stay unscored
    stop_ids: list[str] = []
    for sid in scenes:
        scene_shots = [row for row in shots if str(row.get("scene_id") or "") == sid]
        value = cards.get(sid, {}).get("music_stop")
        chosen = None
        if isinstance(value, str) and any(str(r["shot_id"]) == value for r in scene_shots):
            chosen = value
        elif value is True:
            chosen = next((str(r["shot_id"]) for r in scene_shots if _beat_role(r) == "PUNCHLINE"),
                          str(scene_shots[-1]["shot_id"]))
        chosen = chosen or next((str(r["shot_id"]) for r in scene_shots if _shot_flag(r, "music_stop")), None)
        if chosen:
            stop_ids.append(chosen)
    seconds = {str(r["shot_id"]): float(r["target_seconds"]) for r in shots}
    # runs of one mood over consecutive scenes
    runs: list[dict[str, Any]] = []
    for sid, mood in zip(scenes, moods):
        scene_shots = [str(r["shot_id"]) for r in shots if str(r.get("scene_id") or "") == sid]
        if runs and runs[-1]["mood"] == mood:
            runs[-1]["scenes"].append(sid); runs[-1]["shots"] += scene_shots
        else:
            runs.append({"mood": mood, "scenes": [sid], "shots": scene_shots})

    def run_seconds(run: dict[str, Any]) -> float:
        return sum(seconds[x] for x in run["shots"])

    def merge_adjacent() -> None:
        i = 0
        while i + 1 < len(runs):
            if runs[i]["mood"] == runs[i + 1]["mood"]:
                runs[i]["scenes"] += runs[i + 1]["scenes"]; runs[i]["shots"] += runs[i + 1]["shots"]
                del runs[i + 1]
            else:
                i += 1

    # at most max_cues runs, none shorter than a cue may be: the shortest joins its longer neighbour
    while len(runs) > 1 and (len(runs) > max_cues or min(run_seconds(r) for r in runs) < MIN_MOOD_CUE_SECONDS):
        k = min(range(len(runs)), key=lambda i: run_seconds(runs[i]))
        nbrs = [i for i in (k - 1, k + 1) if 0 <= i < len(runs)]
        j = max(nbrs, key=lambda i: run_seconds(runs[i]))
        runs[k]["mood"] = runs[j]["mood"]
        merge_adjacent()
    # split at hard stops (the stop shot + the rest of its scene unscored)
    scene_of = {str(r["shot_id"]): str(r.get("scene_id") or "") for r in shots}
    pieces: list[dict[str, Any]] = []
    for run in runs:
        piece: list[str] = []
        skip_scene = None
        for sid in run["shots"]:
            if skip_scene is not None and scene_of[sid] == skip_scene:
                continue
            skip_scene = None
            if sid in stop_ids:
                if piece:
                    pieces.append({"mood": run["mood"], "shots": piece})
                piece, skip_scene = [], scene_of[sid]
                continue
            piece.append(sid)
        if piece:
            pieces.append({"mood": run["mood"], "shots": piece})
    # coverage inside the default margins: trim leading shots (never a MUSIC_PASSAGE shot), the first cue first
    total = sum(seconds.values())
    limit = min(total * MAX_DEFAULT_COVERAGE_RATIO, total - MIN_DEFAULT_AMBIENCE_SECONDS)
    if limit <= 0:
        return None
    role = {str(r["shot_id"]): _beat_role(r) for r in shots}
    covered = sum(seconds[x] for piece in pieces for x in piece["shots"])
    for piece in pieces:
        while covered > limit + 1e-9 and piece["shots"] and role[piece["shots"][0]] != "MUSIC_PASSAGE":
            covered -= seconds[piece["shots"].pop(0)]
        if covered <= limit + 1e-9:
            break
    while covered > limit + 1e-9 and pieces:   # protected passages everywhere: drop whole cues from the front
        covered -= sum(seconds[x] for x in pieces.pop(0)["shots"])
    pieces = [piece for piece in pieces if piece["shots"]]
    # the cap holds after the stop splits too: the shortest pieces go first
    while len(pieces) > max_cues:
        pieces.remove(min(pieces, key=lambda piece: sum(seconds[x] for x in piece["shots"])))
    if not pieces:
        return None
    cues = []
    for i, piece in enumerate(pieces, 1):
        row = moods_cfg[piece["mood"]]
        cues.append({"cue_id": f"MOOD_{i}_{piece['mood'].upper()}", "shots": piece["shots"],
                     "narrative_function": str(row.get("narrative_function") or f"MOOD_{piece['mood'].upper()}"),
                     "brief": str(row["brief"]), "mood": piece["mood"]})
    return {"cues": cues, "hard_stop_shots": stop_ids, "moods": sorted({c["mood"] for c in cues})}


def resolve(contract: dict[str, Any]) -> dict[str, Any]:
    """{"source": AUTHORED|AUTHORED_OPT_OUT|LINE_DEFAULT|DEFAULT_NOT_APPLICABLE, "declaration": ...}."""
    audio = contract.get("audio_contract") if isinstance(contract.get("audio_contract"), dict) else {}
    authored = audio.get("bgm")
    if is_explicit_opt_out(authored):
        return {"source": "AUTHORED_OPT_OUT", "declaration": authored}
    if is_authored_music(authored):
        return {"source": "AUTHORED", "declaration": authored}
    if mood_cues_enabled(contract):
        try:
            planned = mood_cues(contract)
        except Exception:  # noqa: BLE001 -- a broken palette / card falls back to the line default
            planned = None
        if planned:
            return {"source": "LINE_DEFAULT", "policy": MOOD_POLICY_ID,
                    "declaration": {"mode": DEFAULT_MODE, "cues": planned["cues"], "default_policy": MOOD_POLICY_ID,
                                    "authored_declaration": authored, "mood_cues": True, "series_cache": True,
                                    "hard_stop_shots": planned["hard_stop_shots"],
                                    "palette": "BGM_MOOD_PALETTE_V1"}}
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
    return {"source": "LINE_DEFAULT", "policy": derived["audio_contract"]["bgm"].get("default_policy", DEFAULT_POLICY_ID),
            "contract": str(out_path),
            "authored_contract": str(contract_path), "cues": derived["audio_contract"]["bgm"]["cues"]}
