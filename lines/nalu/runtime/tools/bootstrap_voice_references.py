#!/usr/bin/env python3
"""Design and stage portable speaker voice references for one private NALU project.

The paid route is the checked-in ``tools/storyclaw_audio_provider.py``.  It
uses a caller-selected durable transaction file, writes intent before its only
provider POST, binds the returned task id, and resumes without reposting.  The
legacy ``AGENTCUT-*`` strings in emitted registry rows are schema compatibility
identifiers consumed by existing admission gates.  They do not name a required
package, model, virtualenv, or runtime directory.

How SD2 gets the audio
----------------------
SD2 (`seedance-2.0-pro`) transports speaker voice as a **provider-registered
asset id**, not a URL: `tools/speaker_voice_contract.py:141` requires
`remote_asset_id`, and `tools/submit_giggle_video_manifest_v2.py:589-592`
rejects a URL where an asset id is expected.  One
`tools/upload_giggle_asset.py` call with `is_public=True` returns `asset_id`,
`file_url` and `duration` at once, which is why the same upload satisfies both
SD2 (`remote_asset_id`) and H3 (`remote_url`).

What this tool does — offline only
----------------------------------
* Builds a per-character voice design brief (age / sex / timbre) from
  `character_entities.appearance_ch1`, the voices requirements' `timbre_brief`
  and the authored `performance_brief` in the preproduction skeleton.
* Derives `sample_text` **verbatim from that character's own dialogue in the
  selected episode**, long enough to clear the audio QA floor.  Very short
  lines are accumulated in script order instead of inventing new dialogue.
* Emits portable text-to-audio task payloads in dry mode.
* Writes `voice_registry.json` in the exact schema the pipeline reads through
  `QINGSHAN_VOICE_REGISTRY` (`tools/speaker_voice_contract.py:78-90`), with
  `status: PENDING_GENERATION` and **null** asset ids / SHAs.  Nothing is
  fabricated.
* Writes the compatibility role policy consumed by the checked-in admission
  gates.
* Optionally probes the engine's real `compile_speaker_voice_contract` against
  the registry it just wrote (offline, free) to prove the name→entity→asset
  resolution chain works.

This tool performs no network I/O of any kind.
"""

from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(os.environ.get("QINGSHAN_ENGINE_ROOT", f"{_np.ENGINE_ROOT}"))
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

SCHEMA = "nalu.voice_reference_bootstrap.v1"
REGISTRY_SCHEMA = "qingshan.voice_reference_registry.v1"
POLICY_SCHEMA = "qingshan.agentcut_character_voice_reference_policy.v1"

# This is the same character class used by the checked-in ASR similarity gate,
# so sample-text length is measured consistently.
HAN_ALNUM = re.compile(r"[㐀-鿿A-Za-z0-9]")

# Shared duration and ASR thresholds consumed by the checked-in voice gates.
HARD_MIN_SECONDS = 1.0
SD2_MIN_SECONDS = 2.0
HARD_MAX_SECONDS = 30.0
RECOMMENDED_MIN_SECONDS = 3.0
RECOMMENDED_MAX_SECONDS = 10.0
ASR_SIMILARITY_FLOOR = 0.70
# Mandarin reading rate for a clean single-speaker reference read.
SYLLABLES_PER_SECOND = 4.2
AUDIO_UNIT_PRICE_CREDITS = 2

PRODUCTION_READY_STATUSES = {"LOCKED_PRODUCTION_READY", "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY"}
PENDING_STATUS = "PENDING_GENERATION"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def spoken_length(value: str) -> int:
    return len(HAN_ALNUM.findall(value))


def entity_id_of(character_id: str) -> str:
    return re.sub(r"^CHAR-", "", character_id.strip().upper()).replace("-", "_").lower()


# --------------------------------------------------------------------------- #
# Dialogue extraction
# --------------------------------------------------------------------------- #

def extract_dialogue(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Every line, in shot order, as (shot_id, speaker, text).

    prompt_spec.dialogue is a single string using the engine's canonical
    `speaker：text` form, with `\\n` separating multiple lines in one shot
    (tools/speaker_voice_contract.py:46-53).
    """
    rows: list[dict[str, str]] = []
    for shot in contract.get("shots") or []:
        raw = str((shot.get("prompt_spec") or {}).get("dialogue") or "").strip()
        if not raw:
            continue
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            speaker, separator, spoken = line.partition("：")
            if not separator:
                raise ValueError(f"{shot.get('shot_id')} dialogue is not speaker：text: {line}")
            rows.append({
                "shot_id": str(shot.get("shot_id")),
                "scene_id": str(shot.get("scene_id") or ""),
                "speaker": speaker.strip(),
                "text": spoken.strip(),
            })
    return rows


def choose_sample_text(
    lines: list[str], *, floor_chars: int, ceiling_chars: int
) -> tuple[str, str, list[str]]:
    """Pick a verbatim sample_text from the character's own lines.

    Rule 1 — if a single line is inside [floor, ceiling], take the longest such
    line.  One continuous utterance is the best timbre reference and stays
    literally verbatim.
    Rule 2 — otherwise accumulate consecutive lines in script order until the
    floor is cleared.  Concatenation is safe for the ASR check because
    `normalized_text` strips all punctuation before comparing.
    Rule 3 — if the character's entire spoken material is still under the
    floor, use all of it and return a risk flag.  Nothing is invented.
    """
    flags: list[str] = []
    in_range = [line for line in lines if floor_chars <= spoken_length(line) <= ceiling_chars]
    if in_range:
        best = max(in_range, key=lambda line: (spoken_length(line), -lines.index(line)))
        return best, "LONGEST_SINGLE_IN_RANGE_LINE", flags
    accumulated: list[str] = []
    for line in lines:
        accumulated.append(line)
        if spoken_length("".join(accumulated)) >= floor_chars:
            break
    text = "".join(accumulated)
    if spoken_length(text) < floor_chars:
        flags.append("SHORT_SAMPLE_TEXT_ALL_LINES_BELOW_FLOOR")
        return text, "ALL_LINES_STILL_BELOW_FLOOR", flags
    if spoken_length(text) > ceiling_chars:
        flags.append("SAMPLE_TEXT_ABOVE_CEILING_MAY_EXCEED_10S")
    return text, "CONSECUTIVE_LINES_ACCUMULATED", flags


def estimated_seconds(text: str, speed: float) -> float:
    return round(spoken_length(text) / (SYLLABLES_PER_SECOND * max(speed, 0.01)), 2)


def choose_speed(text: str, *, default_speed: float) -> tuple[float, list[str]]:
    """Slow a very short sample down so it still clears the duration floor."""
    flags: list[str] = []
    speed = default_speed
    if estimated_seconds(text, speed) < SD2_MIN_SECONDS:
        speed = 0.85
        flags.append("SPEED_REDUCED_TO_0P85_TO_CLEAR_SD2_2S_FLOOR")
    return speed, flags


# --------------------------------------------------------------------------- #
# Design brief
# --------------------------------------------------------------------------- #

AGE_BAND = (
    (re.compile(r"十六七岁|十六|十七"), "16-17", "少年"),
    (re.compile(r"少年"), "16-18", "少年"),
    (re.compile(r"年轻男子|年轻男"), "26-32", "青年"),
    (re.compile(r"年轻妇人|年轻女"), "24-30", "青年"),
    (re.compile(r"中年"), "40-50", "中年"),
    (re.compile(r"老妇|阿婆|老太太"), "65-75", "老年"),
)
SEX_HINT = (
    (re.compile(r"男子|男声|少年|叔"), "male"),
    (re.compile(r"妇人|老妇|阿婆|女"), "female"),
)


def derive_age_and_band(appearance: str, declared_age: str | None) -> tuple[str, str]:
    for pattern, band, label in AGE_BAND:
        if pattern.search(appearance):
            return declared_age or band, label
    return declared_age or "UNSPECIFIED_IN_SOURCE", "UNSPECIFIED"


def derive_sex(appearance: str, declared: str | None) -> str:
    if declared in {"male", "female"}:
        return declared
    for pattern, value in SEX_HINT:
        if pattern.search(appearance):
            return value
    return "UNSPECIFIED_IN_SOURCE"


def build_brief(
    *,
    character: dict[str, Any],
    voice_requirement: dict[str, Any],
    skeleton_row: dict[str, Any] | None,
    lines: list[str],
    accent_id: str,
    floor_chars: int,
    ceiling_chars: int,
    default_speed: float,
    default_emotion: str,
) -> dict[str, Any]:
    appearance = str(character.get("appearance_ch1") or "")
    spec = voice_requirement.get("specification") or {}
    authored = (skeleton_row or {}).get("performance_brief") or {}
    declared_age = spec.get("apparent_age_range")
    age, band = derive_age_and_band(appearance, declared_age)
    sex = derive_sex(appearance, (skeleton_row or {}).get("gender") or spec.get("sex"))
    sample_text, rule, sample_flags = choose_sample_text(
        lines, floor_chars=floor_chars, ceiling_chars=ceiling_chars
    )
    speed, speed_flags = choose_speed(sample_text, default_speed=default_speed)
    seconds = estimated_seconds(sample_text, speed)
    duration_flags: list[str] = []
    if seconds < HARD_MIN_SECONDS:
        duration_flags.append("ESTIMATED_DURATION_BELOW_HARD_1S_FLOOR")
    if seconds < SD2_MIN_SECONDS:
        duration_flags.append("ESTIMATED_DURATION_BELOW_SD2_2S_FLOOR")
    if seconds > HARD_MAX_SECONDS:
        duration_flags.append("ESTIMATED_DURATION_ABOVE_HARD_30S_CEILING")
    if not (RECOMMENDED_MIN_SECONDS <= seconds <= RECOMMENDED_MAX_SECONDS):
        duration_flags.append("ESTIMATED_DURATION_OUTSIDE_RECOMMENDED_3_TO_10S")
    timbre = str(authored.get("timbre_brief") or spec.get("timbre_brief") or "")
    entity_id = entity_id_of(str(character["character_id"]))
    return {
        "entity_id": entity_id,
        "character_id": character["character_id"],
        "name": str(character.get("canonical_name") or ""),
        "aliases_in_script": [str(value) for value in character.get("aliases") or []],
        "gender": sex,
        "apparent_age_range": age,
        "age_band": band,
        "timbre_brief": timbre,
        "identity": str(authored.get("identity") or f"{character.get('canonical_name')}：{appearance}"),
        "social_position": str(authored.get("social_position") or "UNSPECIFIED_IN_SOURCE"),
        "temperament": str(authored.get("temperament") or "UNSPECIFIED_IN_SOURCE"),
        "dramatic_function": str(authored.get("dramatic_function") or "UNSPECIFIED_IN_SOURCE"),
        "appearance_source": appearance,
        "language": str(spec.get("language") or "zh-CN"),
        "accent_id": str(spec.get("accent_id") or accent_id),
        "line_count": len(lines),
        "all_lines": lines,
        "sample_text": sample_text,
        "sample_text_rule": rule,
        "sample_text_is_verbatim_script": all(part in "".join(lines) for part in [sample_text]) or sample_text in "".join(lines),
        "sample_text_spoken_length": spoken_length(sample_text),
        "emotion": default_emotion,
        "speed": speed,
        "estimated_duration_seconds": seconds,
        "duration_contract": {
            "hard_min_seconds": HARD_MIN_SECONDS,
            "sd2_min_seconds": SD2_MIN_SECONDS,
            "hard_max_seconds": HARD_MAX_SECONDS,
            "recommended_seconds": [RECOMMENDED_MIN_SECONDS, RECOMMENDED_MAX_SECONDS],
            "asr_similarity_floor": ASR_SIMILARITY_FLOOR,
        },
        "risk_flags": sample_flags + speed_flags + duration_flags,
        "voice_selection_criteria": {
            "language": "zh-CN Mandarin, no accent processing, no pitch shifting",
            "sex": sex,
            "apparent_age_range": age,
            "timbre": timbre,
            "must_be_unique_across_characters": True,
            "uniqueness_authority": "checked-in voice admission guard: VOICE_PRESET_REUSED_ACROSS_CHARACTERS",
        },
    }


# --------------------------------------------------------------------------- #
# Task payloads
# --------------------------------------------------------------------------- #

def build_task_payload(brief: dict[str, Any], *, episode: str, output_root: Path, voice: dict[str, Any] | None) -> dict[str, Any]:
    entity_id = brief["entity_id"]
    mp3 = output_root / entity_id / f"VOICE-{entity_id}-portable-v1.mp3"
    wav = output_root / entity_id / f"VOICE-{entity_id}-portable-v1.wav"
    voice_id = (voice or {}).get("voice_id")
    voice_name = (voice or {}).get("voice_name")
    argv = [
        "${VENV_PYTHON}", "${ENGINE_ROOT}/tools/storyclaw_audio_provider.py",
        "speech-generate", brief["sample_text"],
        "--voice-id", voice_id or "${VOICE_ID_PENDING_CATALOG_SELECTION}",
        "--emotion", brief["emotion"],
        "--speed", str(brief["speed"]),
        "--output-dir", str(mp3.parent),
        "--file-name", mp3.name,
        "--poll-interval", "2",
        "--timeout", "300",
        "--transaction", "${ABSOLUTE_DURABLE_TRANSACTION_JSON}",
        "--paid",
    ]
    return {
        "entity_id": entity_id,
        "character": brief["name"],
        "episode_scope": episode,
        "route": {
            "endpoint": "/api/v1/generation/text-to-audio",
            "driver": "tools/storyclaw_audio_provider.py speech-generate",
            "driver_evidence": "tools/storyclaw_audio_provider.py durable transaction provider",
            "engine": "Giggle speech via the public portable provider",
            "capability_id": "AGENTCUT-SPEECH-001",
        },
        "request": {
            "text": brief["sample_text"],
            "voice_id": voice_id,
            "voice_name": voice_name,
            "emotion": brief["emotion"],
            "speed": brief["speed"],
            "output_mp3": str(mp3),
        },
        "portable_audio_argv": argv,
        "post_generation_normalization": {
            "command": [
                "${FFMPEG}", "-y", "-i", str(mp3),
                "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav),
            ],
            "evidence": "checked-in portable ffmpeg normalization contract",
            "target_wav": str(wav),
        },
        "registration": {
            "command": ["tools/upload_giggle_asset.py", "--is-public", "true", str(wav)],
            "api_function": "tools.upload_giggle_asset.upload(wav, True)",
            "returns": {
                "asset_id": "-> registry remote_asset_id (SD2 transport)",
                "file_url": "-> registry remote_url (H3 transport)",
                "duration": "-> registry duration_seconds",
            },
            "evidence": "tools/upload_giggle_asset.py public asset registration contract",
        },
        "cost": {
            "unit_price_credits": AUDIO_UNIT_PRICE_CREDITS,
            "price_authority": "live provider billing record bound to the returned task id; the portable budget guard refuses a unit price above the configured cap",
            "must_reverify_before_paying": True,
        },
        "dry_run": True,
        "status": "PENDING_GENERATION" if voice_id else "BLOCKED_VOICE_ID_NOT_SELECTED",
    }


# --------------------------------------------------------------------------- #
# Registry and policy
# --------------------------------------------------------------------------- #

def build_registry(
    briefs: list[dict[str, Any]], *, episode: str, accent_id: str, output_root: Path, voices: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    for brief in briefs:
        entity_id = brief["entity_id"]
        voice = voices.get(entity_id) or {}
        rows.append({
            "character": brief["name"],
            "aliases_in_script": brief["aliases_in_script"],
            "entity_id": entity_id,
            "name": brief["name"],
            "gender": brief["gender"],
            "character_id": brief["character_id"],
            "status": PENDING_STATUS,
            "remote_asset_id": None,
            "remote_url": None,
            "local_reference": str(output_root / entity_id / f"VOICE-{entity_id}-portable-v1.wav"),
            "local_sha256": None,
            "duration_seconds": None,
            "source_type": "AGENTCUT_GENERATED_CHARACTER_REFERENCE",
            "source_generator": "AGENTCUT_SPEECH_GENERATION",
            "agentcut_capability": "AGENTCUT-SPEECH-001",
            "compatibility_note": "The AGENTCUT field names and values are retained only for the public engine's legacy gate schema; generation uses tools/storyclaw_audio_provider.py.",
            "agentcut_version": None,
            "generation_task_id": None,
            "generation_voice_id": voice.get("voice_id"),
            "generation_voice_name": voice.get("voice_name"),
            "generation_emotion": brief["emotion"],
            "generation_speed": brief["speed"],
            "performance_brief_sha256": None,
            "registration_receipt": None,
            "qa_receipt": None,
            "credit_status": None,
            "actual_charged_credits": None,
            "production_use": "BIND_AS_AUDIO_REFERENCE_TO_VIDEO_MODEL_FOR_NATIVE_DIALOGUE_AND_LIPSYNC",
            "forbidden_replacements": ["EPISODE_LOCAL_TTS", "GENERIC_NEURAL_TTS_VOICE"],
            "legacy_references": [],
            "pending_fields_explained": {
                "remote_asset_id": "written from upload_giggle_asset asset_id after portable paid generation; SD2 transport",
                "remote_url": "written from upload_giggle_asset file_url; H3 transport",
                "local_sha256": "computed from the normalized 48kHz mono PCM wav that does not exist yet",
                "performance_brief_sha256": "sha256 over the nine policy fields once voice_id and voice_name are bound",
                "generation_voice_id": "must come from the live provider catalog; never invented, must be unique across characters",
            },
        })
    return {
        "schema": REGISTRY_SCHEMA,
        "status": "PENDING_GENERATION_NOT_PRODUCTION_READY",
        "line": "nalu",
        "work": "PRIVATE_PROJECT",
        "episode_scope": episode,
        "recorded_at_utc": utc_now(),
        "read_via": "QINGSHAN_VOICE_REGISTRY (tools/speaker_voice_contract.py:78-90)",
        "registry_authority": "QINGSHAN_VOICE_REGISTRY points to this project's private scoped file",
        "policy": {
            "language": "zh-CN",
            "accent_id": accent_id,
            "max_audio_references_per_provider_task": 2,
            "h3_speaking_identities_per_task": 1,
            "tts_substitution_on_native_speaking_shots": "FORBIDDEN",
            "canonical_generator_for_nonexempt_characters": "PUBLIC_STORYCLAW_AUDIO_PROVIDER",
            "missing_reference_action": "AUTO_GENERATE_WITH_PORTABLE_PROVIDER_THEN_QA_AND_REGISTER_BEFORE_SPEAKING_GENERATION",
            # Read by the legacy-compatible voice reference gate.  A new
            # project claims no inherited voice exemptions.
            "only_legacy_native_voice_exemptions": [],
        },
        "no_fabrication_contract": "Every not-yet-real value in this file is null. No placeholder asset id, task id, receipt path or SHA appears anywhere; a null fails the gates loudly instead of passing them silently.",
        "major_roles": rows,
    }


def build_policy(briefs: list[dict[str, Any]], *, voices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    roles = []
    for brief in briefs:
        voice = voices.get(brief["entity_id"]) or {}
        roles.append({
            "entity_id": brief["entity_id"],
            "name": brief["name"],
            "gender": brief["gender"],
            "identity": brief["identity"],
            "social_position": brief["social_position"],
            "temperament": brief["temperament"],
            "dramatic_function": brief["dramatic_function"],
            "voice_id": voice.get("voice_id"),
            "voice_name": voice.get("voice_name"),
            "sample_text": brief["sample_text"],
            "emotion": brief["emotion"],
            "speed": brief["speed"],
        })
    return {
        "schema": POLICY_SCHEMA,
        "line": "nalu",
        "status": "PENDING_VOICE_CATALOG_SELECTION" if any(row["voice_id"] is None for row in roles) else "AGENTCUT_VOICE_POLICY_ACTIVE",
        "recorded_at_utc": utc_now(),
        "consumed_by": [
            "legacy-compatible character voice reference gate",
            "multimodal character binding gate",
        ],
        "performance_brief_sha256_fields": [
            "identity", "social_position", "temperament", "dramatic_function",
            "voice_id", "voice_name", "sample_text", "emotion", "speed",
        ],
        "roles": roles,
    }


def performance_brief_sha256(role: dict[str, Any]) -> str | None:
    keys = (
        "identity", "social_position", "temperament", "dramatic_function",
        "voice_id", "voice_name", "sample_text", "emotion", "speed",
    )
    if any(role.get(key) in (None, "") for key in keys):
        return None
    brief = {key: role[key] for key in keys}
    return hashlib.sha256(
        json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------- #

def probe_speaker_contract(registry_path: Path, briefs: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    """Run the engine's real contract compiler against our registry. Offline."""
    previous = os.environ.get("QINGSHAN_VOICE_REGISTRY")
    os.environ["QINGSHAN_VOICE_REGISTRY"] = str(registry_path)
    try:
        from tools.speaker_voice_contract import compile_speaker_voice_contract  # noqa: PLC0415

        dialogue = extract_dialogue(contract)
        by_speaker: dict[str, list[dict[str, str]]] = {}
        for row in dialogue:
            by_speaker.setdefault(row["speaker"], []).append(row)
        specs = []
        for brief in briefs:
            rows = by_speaker.get(brief["name"]) or []
            if not rows:
                continue
            specs.append({
                "dialogue": f"{brief['name']}：{rows[0]['text']}",
                "cast": [{"character": brief["name"], "face_visibility": "FULL_FACE_VISIBLE"}],
            })
        unit = {
            "unit_id": "PROBE-ALL-SPEAKERS",
            "model": "seedance-2.0-pro",
            "ordered_prompt_specs": specs,
            "character_entities": contract.get("character_entities"),
        }
        result = compile_speaker_voice_contract(unit)
        return {
            "status": result.get("status"),
            "resolution_chain_ok": all(
                row.get("voice_entity_id") and row.get("character_id")
                for row in result.get("bindings") or []
            ) and bool(result.get("bindings")),
            "voice_bindings": [
                {
                    "speaker": row.get("speaker"),
                    "character_id": row.get("character_id"),
                    "voice_entity_id": row.get("voice_entity_id"),
                    "audio_slot": row.get("audio_slot"),
                }
                for row in result.get("bindings") or []
            ],
            "failures": result.get("failures"),
            "interpretation": "Every failure must be a PENDING-value failure (NOT_PRODUCTION_READY / ASSET_ID_MISSING / REFERENCE_MISSING). Any *_UNRESOLVED or NOT_REGISTERED failure would mean the name→entity chain is broken.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "PROBE_ERROR", "exception": repr(exc)}
    finally:
        if previous is None:
            os.environ.pop("QINGSHAN_VOICE_REGISTRY", None)
        else:
            os.environ["QINGSHAN_VOICE_REGISTRY"] = previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--generation-contract", required=True)
    parser.add_argument("--asset-requirements", required=True)
    parser.add_argument("--voice-skeleton", help="preproduction voice_registry.skeleton.json, used for the authored performance_brief text")
    parser.add_argument("--registry-out", required=True, help="Written in the QINGSHAN_VOICE_REGISTRY schema")
    parser.add_argument("--policy-out", required=True)
    parser.add_argument("--task-payloads-out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--voice-catalog",
        help="JSON mapping entity_id -> {voice_id, voice_name} selected from the live provider catalog. Without it voice ids stay null: they are provider values and must never be invented.",
    )
    parser.add_argument("--audio-output-root")
    parser.add_argument("--accent-id", default="ACCENT-ZH-CN-STANDARD-V1")
    parser.add_argument("--emotion", default="neutral")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--floor-chars", type=int, default=12, help="Minimum spoken length of sample_text (fix for R-8)")
    parser.add_argument("--ceiling-chars", type=int, default=42)
    parser.add_argument("--probe-speaker-contract", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Always on. This tool has no submit path.")
    args = parser.parse_args()

    episode = args.episode.strip().upper()
    contract = load_json(Path(args.generation_contract))
    requirements = load_json(Path(args.asset_requirements))
    skeleton = load_json(Path(args.voice_skeleton)) if args.voice_skeleton else {}
    skeleton_rows = {str(row.get("entity_id")): row for row in (skeleton.get("major_roles") or [])}
    voice_requirements = {
        str((row.get("specification") or {}).get("owner_character_id")): row
        for row in requirements["assets"]["voices"]
    }
    voices: dict[str, dict[str, Any]] = {}
    if args.voice_catalog:
        catalog = load_json(Path(args.voice_catalog))
        voices = {str(key): dict(value) for key, value in (catalog.get("voices") or catalog).items()}
        seen: dict[str, str] = {}
        for entity_id, row in voices.items():
            voice_id = row.get("voice_id")
            if voice_id and voice_id in seen:
                raise SystemExit(
                    f"voice catalog reuses voice_id {voice_id} for {seen[voice_id]} and {entity_id}: "
                    "the voice reference gate forbids preset reuse across characters"
                )
            if voice_id:
                seen[voice_id] = entity_id

    dialogue = extract_dialogue(contract)
    lines_by_speaker: dict[str, list[str]] = {}
    for row in dialogue:
        lines_by_speaker.setdefault(row["speaker"], []).append(row["text"])

    briefs: list[dict[str, Any]] = []
    non_speaking: list[str] = []
    unknown_speakers = set(lines_by_speaker) - {
        str(row.get("canonical_name")) for row in contract.get("character_entities") or []
    }
    for character in contract.get("character_entities") or []:
        name = str(character.get("canonical_name") or "")
        lines = lines_by_speaker.get(name) or []
        if not lines:
            non_speaking.append(str(character.get("character_id")))
            continue
        briefs.append(build_brief(
            character=character,
            voice_requirement=voice_requirements.get(str(character["character_id"])) or {},
            skeleton_row=skeleton_rows.get(entity_id_of(str(character["character_id"]))),
            lines=lines,
            accent_id=args.accent_id,
            floor_chars=args.floor_chars,
            ceiling_chars=args.ceiling_chars,
            default_speed=args.speed,
            default_emotion=args.emotion,
        ))

    output_root = (
        Path(args.audio_output_root)
        if args.audio_output_root
        else Path(_np.RUNTIME_ROOT) / "working_assets" / "voices" / episode
    )
    registry = build_registry(
        briefs, episode=episode, accent_id=args.accent_id, output_root=output_root, voices=voices
    )
    policy = build_policy(briefs, voices=voices)
    for role in policy["roles"]:
        role_sha = performance_brief_sha256(role)
        if role_sha:
            for row in registry["major_roles"]:
                if row["entity_id"] == role["entity_id"]:
                    row["performance_brief_sha256_expected_once_generated"] = role_sha
    payloads = {
        "schema": "nalu.text_to_audio_task_payloads.v1",
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "mode": "DRY_RUN_NO_SUBMIT",
        "host_dependencies": {
            "portable_audio_provider": str(ENGINE_ROOT / "tools/storyclaw_audio_provider.py"),
            "portable_audio_provider_present": (ENGINE_ROOT / "tools/storyclaw_audio_provider.py").is_file(),
            "media_tools": "ffmpeg and ffprobe from NALU_* overrides or PATH",
            "whisper_model_required_for_qa": "faster-whisper model directory for measured ASR QA",
            "giggle_api_key_required": True,
        },
        "task_count": len(briefs),
        "expected_credits": AUDIO_UNIT_PRICE_CREDITS * len(briefs),
        "tasks": [
            build_task_payload(brief, episode=episode, output_root=output_root, voice=voices.get(brief["entity_id"]))
            for brief in briefs
        ],
    }
    atomic_json(Path(args.registry_out), registry)
    atomic_json(Path(args.policy_out), policy)
    atomic_json(Path(args.task_payloads_out), payloads)

    probe = probe_speaker_contract(Path(args.registry_out), briefs, contract) if args.probe_speaker_contract else None

    blockers: list[dict[str, Any]] = []
    if not voices:
        blockers.append({
            "id": "VOICE_ID_NOT_SELECTED",
            "severity": "HARD",
            "detail": "generation_voice_id must be a real live-provider catalog value, unique per character. Nothing here invents one.",
            "unblock": "Run storyclaw_audio_provider.py speech-voices, select suitable unique voices, then re-run this tool with --voice-catalog.",
        })
    if not (ENGINE_ROOT / "tools/storyclaw_audio_provider.py").is_file():
        blockers.append({
            "id": "PORTABLE_AUDIO_PROVIDER_ABSENT",
            "severity": "HARD",
            "detail": f"{ENGINE_ROOT}/tools/storyclaw_audio_provider.py is missing from this checkout.",
            "unblock": "Install the complete tagged NALU engine release before starting S4.",
        })
    risky = [brief for brief in briefs if brief["risk_flags"]]

    report = {
        "schema": SCHEMA,
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "blockers_addressed": ["voice sample duration/ASR floor", "portable durable voice generation route"],
        "route": {
            "endpoint": "/api/v1/generation/text-to-audio",
            "driver": "tools/storyclaw_audio_provider.py speech-generate",
            "engine": "Giggle speech via the public portable provider",
            "sd2_transport": "remote_asset_id (provider-registered audio asset id)",
            "sd2_transport_authority": "tools/speaker_voice_contract.py:141,314; tools/submit_giggle_video_manifest_v2.py:589-592",
            "h3_transport": "remote_url (public https)",
            "one_upload_yields_both": "tools/upload_giggle_asset.py with is_public=True returns asset_id + file_url + duration",
        },
        "speaking_character_count": len(briefs),
        "non_speaking_characters": non_speaking,
        "unknown_speakers_in_script": sorted(unknown_speakers),
        "registry": str(Path(args.registry_out)),
        "policy": str(Path(args.policy_out)),
        "task_payloads": str(Path(args.task_payloads_out)),
        "expected_credits": AUDIO_UNIT_PRICE_CREDITS * len(briefs),
        "r8_fix": [
            {
                "entity_id": brief["entity_id"],
                "character": brief["name"],
                "previous_skeleton_sample_text": (skeleton_rows.get(brief["entity_id"]) or {}).get("performance_brief", {}).get("sample_text"),
                "previous_spoken_length": spoken_length(
                    str((skeleton_rows.get(brief["entity_id"]) or {}).get("performance_brief", {}).get("sample_text") or "")
                ),
                "new_sample_text": brief["sample_text"],
                "new_spoken_length": brief["sample_text_spoken_length"],
                "rule": brief["sample_text_rule"],
                "verbatim_from_script": brief["sample_text_is_verbatim_script"],
                "estimated_duration_seconds": brief["estimated_duration_seconds"],
                "speed": brief["speed"],
                "risk_flags": brief["risk_flags"],
            }
            for brief in briefs
        ],
        "voice_design_briefs": briefs,
        "speaker_contract_probe": probe,
        "blockers": blockers,
        "risky_roles": [brief["entity_id"] for brief in risky],
        "paid_run_sequence": [
            "0. 💚 Free: this tool, then `nalu_budget_ledger.py --check --episode <EP> --planned-credits <expected_credits>`.",
            "1. Host prep: install ffmpeg/ffprobe and the faster-whisper model; inject GIGGLE_API_KEY only for paid execution.",
            "2. Run storyclaw_audio_provider.py speech-voices, automatically select one suitable unique provider voice per character, and re-run this tool with --voice-catalog.",
            "3. Keep the policy and registries in the selected private series scope; the pipeline exports their exact paths to the checked-in guards.",
            "4. 🔑 Re-verify the live audio price is still 2 credits on /api/v1/payment/credit-statements before paying.",
            f"5. 💰 One task per character ({len(briefs)} tasks, {AUDIO_UNIT_PRICE_CREDITS * len(briefs)} credits expected): run the portable provider through nalu_pipeline S4. Its absolute transaction path is flocked and binds taskId immediately.",
            "6. 💚 Normalize each mp3 to 48kHz mono 16-bit PCM wav; ffprobe must show exactly one audio stream and 1.0s <= duration <= 30.0s (SD2 wants >= 2.0s).",
            "7. 💚 ASR QA with the expected text as hotwords; difflib similarity over punctuation-stripped text must be >= 0.70.",
            "8. 🔑 upload_giggle_asset.py with is_public=True per wav; write asset_id -> remote_asset_id, file_url -> remote_url, duration -> duration_seconds.",
            "9. 🔑 Read the exact charge per taskId from /api/v1/payment/credit-statements; write credit_status and actual_charged_credits.",
            "10. 💚 Flip each row to the legacy-compatible AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY status only once remote_asset_id, local_sha256, receipts, performance_brief_sha256 and credit fields are all real, then run the checked-in voice admission guard and expect PASS.",
            "11. Rights: rights.status must reach PASS with a non-empty basis before release (initial_asset_library.py:340-342); provider commercialUseMetadata is checked by audit_e36_jiaotu_voice_rights_preflight.py:40-42.",
        ],
        "status": "PASS_DESIGN_COMPLETE_PENDING_PAID_STEP" if briefs else "FAIL_NO_SPEAKING_CHARACTERS",
    }
    atomic_json(Path(args.report), report)
    print(json.dumps({
        "status": report["status"],
        "speaking_characters": len(briefs),
        "expected_credits": report["expected_credits"],
        "risky_roles": report["risky_roles"],
        "blockers": [row["id"] for row in blockers],
        "probe": (probe or {}).get("status"),
        "probe_resolution_chain_ok": (probe or {}).get("resolution_chain_ok"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
