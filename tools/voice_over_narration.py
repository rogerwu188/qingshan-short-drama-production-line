#!/usr/bin/env python3
"""Voice-over (V.O.) narration: one shared definition for every stage.

A spoken line is a VOICE-OVER line iff its speaker resolves (canonical_name or
alias, exactly like ``build_nalu_preproduction.bind_dialogue_cast``) to a
character entity whose ``identity_source.mode == "VOICE_ONLY_NO_PLATE"``: a
narrator with no on-screen body.  Such a line never goes into the video model.
S2 moves it from ``prompt_spec.dialogue`` to ``prompt_spec.voice_over``, S4
synthesizes it with the character's locked voice, S7 places it on the final
timeline, ducks the native audio under it, mixes it in and captions it.

Every other line keeps the native multimodal path unchanged (including a
diegetic ``OFFSCREEN_VOICE_ONLY`` speaker who has a plate).

The split is active only under the CURRENT_PORTABLE policy profile; a legacy
replay (NALU-YEWUJIANG, e.g. the E05 talking crow that was generated natively)
keeps its recorded behaviour byte for byte.

Window rule (S2, free): for a shot carrying V.O.
    need = 0.3 s lead-in + sum(min_dialogue_seconds(line)) + 0.25 s between lines
    have = this shot's start .. start of the next shot that carries in-video
           dialogue or V.O. (or the episode end)
    need > have  ->  VOICE_OVER_WINDOW_TOO_SHORT:<shot>:<need>:<have>

Placement rule (S7): line start = shot start + 0.3 s; the next line in the same
shot starts at the previous line's end + 0.25 s; no line starts earlier than
the previous V.O. end + 0.2 s.  A V.O. window that overlaps measured in-video
speech blocks (VOICE_OVER_OVERLAPS_DIALOGUE).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"
PRESENCE = "VOICE_OVER"
LEAD_IN_SECONDS = 0.3
LINE_GAP_SECONDS = 0.25
MIN_SEPARATION_SECONDS = 0.2
DUCK_GAIN = 0.35
DUCK_FADE_SECONDS = 0.15
MANIFEST_SCHEMA = "nalu.voice_over_manifest.v1"
PLACEMENT_SCHEMA = "nalu.voice_over_placement.v1"

_RUNTIME_TOOLS = Path(__file__).resolve().parents[1] / "lines/nalu/runtime/tools"


def enabled() -> bool:
    """V.O. separation runs only under the CURRENT_PORTABLE policy profile."""
    try:
        if str(_RUNTIME_TOOLS) not in sys.path:
            sys.path.append(str(_RUNTIME_TOOLS))
        import nalu_policy_profile as _profile  # noqa: PLC0415
        return _profile.is_current()
    except ImportError:  # pragma: no cover - the engine tree always ships it
        explicit = str(os.environ.get("NALU_POLICY_PROFILE") or "").strip().upper()
        return explicit == "CURRENT_PORTABLE"


def _entity_rows(entities: Any) -> list[dict[str, Any]]:
    if isinstance(entities, dict):
        return [row for row in entities.values() if isinstance(row, dict)]
    return [row for row in entities or [] if isinstance(row, dict)]


def voice_over_character_ids(entities: Any, *, force: bool = False) -> set[str]:
    """character_id of every VOICE_ONLY_NO_PLATE entity (empty unless the split is enabled)."""
    if not force and not enabled():
        return set()
    return {
        str(row.get("character_id"))
        for row in _entity_rows(entities)
        if row.get("character_id")
        and str((row.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE
    }


def speaker_index(entities: Any) -> dict[str, str]:
    """canonical_name / alias -> character_id (same collision rule as bind_dialogue_cast)."""
    names: dict[str, str] = {}
    for row in _entity_rows(entities):
        cid = str(row.get("character_id") or "")
        for name in [row.get("canonical_name"), *(row.get("aliases") or [])]:
            if not name or not cid:
                continue
            if name in names and names[name] != cid:
                raise ValueError(f"DIALOGUE_ALIAS_COLLISION:{name}")
            names[name] = cid
    return names


def partition_line(line: str, language: str = "zh") -> tuple[str, str, str]:
    """``speaker：text``; English may also use an ASCII colon (as build_nalu_preproduction)."""
    speaker, separator, spoken = line.partition("：")
    if not separator and language == "en":
        speaker, separator, spoken = line.partition(":")
    return speaker, separator, spoken


def separate_voice_over(dialogue: str, entities: Any, language: str = "zh", *,
                        vo_ids: set[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Split authored shot dialogue into (in-video dialogue, V.O. rows).

    ``line_index`` is the 0-based index of the line inside the authored shot
    dialogue.  In-video lines are returned exactly as authored; with no V.O.
    speaker the input string comes back untouched.
    """
    text = str(dialogue or "")
    ids = voice_over_character_ids(entities) if vo_ids is None else set(vo_ids)
    if not ids or not text.strip():
        return text, []
    names = speaker_index(entities)
    by_id = {str(row.get("character_id")): row for row in _entity_rows(entities)}
    keep: list[str] = []
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines()):
        speaker, separator, spoken = partition_line(line, language)
        cid = names.get(speaker.strip()) if separator else None
        if cid and cid in ids:
            rows.append({
                "line_index": index,
                "speaker": str(by_id[cid].get("canonical_name") or speaker.strip()),
                "character_id": cid,
                "text": spoken.strip(),
            })
        else:
            keep.append(line)
    if not rows:
        return text, []
    return "\n".join(keep), rows


def in_video_dialogue(dialogue: str, entities: Any, language: str = "zh") -> str:
    return separate_voice_over(dialogue, entities, language)[0]


def contract_language(contract: dict[str, Any]) -> str:
    value = str((contract or {}).get("dialogue_language") or "").strip().lower()
    return "en" if value.startswith("en") else "zh"


def voice_over_unit(row: dict[str, Any], vo_ids: set[str]) -> bool:
    """A contract ``audio_contract.dialogue_units`` row spoken by a V.O. character."""
    return str(row.get("speaker_id") or "") in vo_ids


def text_sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def file_sha256(path: Path | str) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def norm_text(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


# --------------------------------------------------------------------------- S2
def estimate_seconds(texts: Iterable[str], estimate: Callable[[str], float]) -> float:
    texts = list(texts)
    if not texts:
        return 0.0
    return LEAD_IN_SECONDS + sum(float(estimate(t)) for t in texts) + LINE_GAP_SECONDS * (len(texts) - 1)


def window_failures(shots: list[dict[str, Any]], runtime: float,
                    estimate: Callable[[str], float]) -> list[dict[str, Any]]:
    """``shots``: [{shot_id, start, has_in_video, voice_over: [{text}]}] in episode order."""
    out: list[dict[str, Any]] = []
    for position, shot in enumerate(shots):
        lines = shot.get("voice_over") or []
        if not lines:
            continue
        end = runtime
        for later in shots[position + 1:]:
            if later.get("has_in_video") or later.get("voice_over"):
                end = float(later["start"])
                break
        have = end - float(shot["start"])
        need = estimate_seconds([row["text"] for row in lines], estimate)
        out.append({"shot_id": shot["shot_id"], "need": round(need, 3), "have": round(have, 3),
                    "status": "PASS" if need <= have + 1e-9 else "FAIL"})
    return out


# --------------------------------------------------------------------------- S7
def place(lines: list[dict[str, Any]], shot_starts: dict[str, float],
          speech: list[tuple[float, float]], *, picture_end: float | None = None
          ) -> tuple[list[dict[str, Any]], list[str]]:
    """Place V.O. lines on the final timeline.

    ``lines``: manifest rows in editorial order with ``duration_seconds``.
    ``speech``: in-video speech windows (final-timeline seconds) from the unit ASR.
    """
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    previous_end: float | None = None
    previous_shot: str | None = None
    for line in lines:
        sid = str(line["shot_id"])
        if sid not in shot_starts:
            failures.append(f"VOICE_OVER_SHOT_NOT_ON_TIMELINE:{sid}:{line['line_index']}")
            continue
        start = shot_starts[sid] + LEAD_IN_SECONDS
        if previous_shot == sid and previous_end is not None:
            start = max(start, previous_end + LINE_GAP_SECONDS)
        if previous_end is not None:
            start = max(start, previous_end + MIN_SEPARATION_SECONDS)
        end = start + float(line["duration_seconds"])
        row = {"shot_id": sid, "line_index": int(line["line_index"]), "speaker": line.get("speaker"),
               "character_id": line.get("character_id"), "text": line["text"],
               "start": round(start, 3), "end": round(end, 3),
               "wav": line.get("wav"), "wav_sha256": line.get("wav_sha256")}
        for s0, s1 in speech:
            if s1 > start and s0 < end:
                failures.append(f"VOICE_OVER_OVERLAPS_DIALOGUE:{sid}:{line['line_index']}")
                break
        if picture_end is not None and end > picture_end + 1e-6:
            failures.append(f"VOICE_OVER_RUNS_PAST_PICTURE_END:{sid}:{line['line_index']}")
        rows.append(row)
        previous_end, previous_shot = end, sid
    return rows, failures


def duck_expression(windows: list[tuple[float, float]], *, gain: float = DUCK_GAIN,
                    fade: float = DUCK_FADE_SECONDS) -> str:
    """ffmpeg ``volume`` expression: 1 outside V.O., ``gain`` inside, linear fades of ``fade`` s."""
    parts = [
        f"max(0,min(1,min((t-({s - fade:.3f}))/{fade:g},(({e + fade:.3f})-t)/{fade:g})))"
        for s, e in windows
    ]
    if not parts:
        return "1"
    env = parts[0]
    for part in parts[1:]:
        env = f"max({env},{part})"
    return f"1-(1-{gain:.4f})*({env})"


def mix_filter(windows: list[tuple[float, float]], count: int) -> str:
    """filter_complex: duck input 0's audio under every window, add inputs 1..count at unity."""
    chains = [
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"volume='{duck_expression(windows)}':eval=frame[native]"
    ]
    labels = ["[native]"]
    for index, (start, _end) in enumerate(windows, 1):
        ms = int(round(start * 1000))
        chains.append(f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      f"adelay={ms}|{ms}[vo{index}]")
        labels.append(f"[vo{index}]")
    if count != len(windows):
        raise ValueError("VOICE_OVER_MIX_INPUT_COUNT_MISMATCH")
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[aout]")
    return ";".join(chains)


def read_json(path: Path | str, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def binding_failures(placement_path: Path | str) -> list[str]:
    """A placement is admitted only when it is sha-bound to the S4 manifest and every wav.

    Used by the release leveller and the audio-profile contract: mixed-in V.O.
    is non-native speech by construction, so it is accepted only with this
    evidence chain; anything else keeps failing.
    """
    path = Path(placement_path)
    placement = read_json(path, None)
    if not isinstance(placement, dict) or placement.get("schema") != PLACEMENT_SCHEMA:
        return [f"VOICE_OVER_PLACEMENT_INVALID:{path}"]
    failures: list[str] = []
    manifest_path = Path(str(placement.get("voice_over_manifest") or ""))
    manifest_sha = file_sha256(manifest_path) if str(manifest_path) not in ("", ".") else None
    if not manifest_sha or manifest_sha != placement.get("voice_over_manifest_sha256"):
        return [f"VOICE_OVER_MANIFEST_SHA_MISMATCH:{manifest_path}"]
    manifest = read_json(manifest_path, {}) or {}
    by_key = {(str(r.get("shot_id")), int(r.get("line_index", -1))): r for r in manifest.get("rows") or []}
    for row in placement.get("rows") or []:
        key = (str(row.get("shot_id")), int(row.get("line_index", -1)))
        ref = by_key.get(key)
        label = f"{key[0]}:{key[1]}"
        if ref is None:
            failures.append(f"VOICE_OVER_LINE_NOT_IN_MANIFEST:{label}")
            continue
        if text_sha256(row.get("text") or "") != ref.get("text_sha256"):
            failures.append(f"VOICE_OVER_TEXT_SHA_MISMATCH:{label}")
        if not ref.get("wav_sha256") or file_sha256(ref.get("wav") or "") != ref.get("wav_sha256") \
                or row.get("wav_sha256") != ref.get("wav_sha256"):
            failures.append(f"VOICE_OVER_WAV_SHA_MISMATCH:{label}")
    return failures


def bound_wav_shas(placement_path: Path | str) -> set[str]:
    if binding_failures(placement_path):
        return set()
    placement = read_json(placement_path, {}) or {}
    return {str(row.get("wav_sha256")) for row in placement.get("rows") or [] if row.get("wav_sha256")}


def windows_from_placement(placement_path: Path | str | None) -> list[dict[str, Any]]:
    if not placement_path:
        return []
    placement = read_json(placement_path, {}) or {}
    return [{"start": float(r["start"]), "end": float(r["end"]), "shot_id": r.get("shot_id"),
             "line_index": r.get("line_index"), "speaker": r.get("speaker"), "text": r.get("text")}
            for r in placement.get("rows") or [] if r.get("start") is not None and r.get("end") is not None]
