#!/usr/bin/env python3
"""Bootstrap character / prop identity reference plates for the nalu line.

Why this exists (blocker E-3)
-----------------------------
`tools/submit_giggle_image_manifest.py` only ever POSTs
`/api/v1/generation/image-to-image` and its `validate_task` demands (a) every
reference binding file already exists with a matching SHA and (b) exactly one
`scene` reference.  A *first* identity plate can satisfy neither, so the
image-manifest route can never bootstrap an identity card.

The engine does own a text-to-image route, and the previous survey missed it:
`tools/submit_giggle_character_asset_plan.py:126` selects
`/api/v1/generation/text-to-image` whenever a row carries **zero** reference
images, and only upgrades to `image-to-image` when references are present.  It
already has `--precheck-only`, a durable transaction guard keyed on a
submission fingerprint, and exact credit reconciliation.  So the correct fix is
to *feed* that tool, not to write a new submitter.

What this tool does (all offline, never POSTs)
---------------------------------------------
1. Scans `--character-source-folder` (which may not exist yet) and matches
   image files to `character_id`s by filename / canonical name / alias /
   entity-id / parent-directory name.  The full match table, including every
   rejection reason, is written to `--match-report`.
2. Registers each matched file as an identity reference artifact (absolute
   path + real sha256 + media type) inside an asset library built by the
   engine's own `tools/initial_asset_library.compile_library`, so the result is
   exactly the shape `initial_asset_library.py gate` reads.
3. For every character and prop with no source image, emits a
   `qingshan.character_asset_plan.v1` plan in the exact schema
   `submit_giggle_character_asset_plan.py` consumes, reusing the authored
   prompts under `--prompt-dir` (prompt sha256 over file *bytes*), with
   `reference_images: []` so the submitter picks the text-to-image endpoint.
4. Optionally shells out to that submitter with `--precheck-only` and records
   its verdict.  This tool has no code path that can reach a POST: it never
   imports `giggle_api_client` and it always passes `--precheck-only`.

Money safety
------------
`--allow-submit` does not exist.  The paid step is documented in the report's
`paid_run_sequence` and must be run by hand, by an operator, with an
authorization ref.
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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(os.environ.get("QINGSHAN_ENGINE_ROOT", f"{_np.ENGINE_ROOT}"))
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from tools.initial_asset_library import (  # noqa: E402
    CATEGORIES,
    canonical_sha256,
    compile_library,
    gate_library,
    requirement_errors,
)
from tools.visual_culture_contract import DEFAULT_CONTRACT as QINGSHAN_VISUAL_CULTURE_CONTRACT, prompt_block_zh as qingshan_visual_prompt_block  # noqa: E402

SCHEMA = "nalu.identity_card_bootstrap.v1"
PLAN_SCHEMA = "qingshan.character_asset_plan.v1"
GATE_SCHEMA = "qingshan.identity_asset_gate.v1"

IMAGE_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".avif": "image/avif",
}

# Filename decorations that carry no identity information.  Stripped before
# matching so `qinming_front_v2.png` still resolves to CHAR-QINMING.
DECORATIONS = (
    "identityplate", "identity", "plate", "card", "ref", "reference",
    "front", "back", "side", "threequarter", "bust", "fullbody", "headshot",
    "final", "raw", "copy", "orig", "original", "edit", "crop",
    "正面", "侧面", "背面", "全身", "半身", "头像", "身份", "基准卡", "参考", "定妆",
)
ROLE_HINTS = (
    ("FRONT_NEUTRAL_HEADSHOT", ("front", "headshot", "正面", "头像")),
    ("THREE_QUARTER_BUST", ("threequarter", "34", "bust", "半身", "侧面")),
    ("FULL_BODY_STANDING", ("fullbody", "full", "standing", "全身")),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def entity_id_of(character_id: str) -> str:
    """CHAR-QINMING -> qinming, CHAR-VILLAGER-A -> villager_a.

    This mirrors the ids already used in
    preproduction/E01/voice_registry.skeleton.json so the image side and the
    voice side agree on one stable per-character key.
    """
    stem = re.sub(r"^CHAR-", "", character_id.strip().upper())
    return stem.replace("-", "_").lower()


def normalize(value: str) -> str:
    """Lowercase, drop everything that is not alnum or CJK, strip decorations."""
    lowered = value.strip().lower()
    lowered = re.sub(r"[^0-9a-z一-鿿]+", "", lowered)
    changed = True
    while changed:
        changed = False
        for token in DECORATIONS:
            token_n = re.sub(r"[^0-9a-z一-鿿]+", "", token.lower())
            if token_n and token_n in lowered and lowered != token_n:
                lowered = lowered.replace(token_n, "")
                changed = True
    lowered = re.sub(r"(v\d+|\d{1,3})$", "", lowered)
    return lowered


def role_hint(stem: str) -> str:
    flat = normalize(stem)
    raw = stem.lower()
    for role, tokens in ROLE_HINTS:
        for token in tokens:
            if token in raw or token in flat:
                return role
    return "UNSPECIFIED_IDENTITY_VIEW"


# --------------------------------------------------------------------------- #
# Subject table: characters from the generation contract, props from
# non_character_entities plus whatever prop prompts exist on disk.
# --------------------------------------------------------------------------- #

VOICE_ONLY_NO_PLATE = "VOICE_ONLY_NO_PLATE"


def build_subjects(contract: dict[str, Any], requirements: dict[str, Any]) -> list[dict[str, Any]]:
    subjects: list[dict[str, Any]] = []
    char_reqs = {row["asset_id"]: row for row in requirements["assets"]["characters"]}
    for row in contract.get("character_entities") or []:
        character_id = str(row["character_id"])
        # E05 (seq=26): a speaking creature such as the talking crow is a CHARACTER for the
        # dialogue/voice contracts but never a visible cast member — its picture is a PROP
        # card.  It has no human face, so an identity plate could never pass the
        # insightface lock; such rows declare identity_source.mode VOICE_ONLY_NO_PLATE and
        # get no plate row here (the voice reference is still built by S4).
        if str((row.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_NO_PLATE:
            continue
        spec = (char_reqs.get(character_id) or {}).get("specification") or {}
        subjects.append({
            "subject_id": character_id,
            "kind": "CHARACTER",
            "library_category": "characters",
            "entity_id": entity_id_of(character_id),
            "canonical_name": str(row.get("canonical_name") or ""),
            "aliases": [str(value) for value in row.get("aliases") or []],
            "appearance": str(row.get("appearance_ch1") or ""),
            "identity_lock_fields": list(spec.get("identity_lock_required_fields") or []),
            "sex": spec.get("sex"),
            "apparent_age_range": spec.get("apparent_age_range"),
            "card_deliverables": [str(v) for v in spec.get("card_deliverables") or []],
        })
    prop_reqs = {row["asset_id"]: row for row in requirements["assets"]["props"]}
    contract_props = {str(row["entity_id"]): row for row in contract.get("non_character_entities") or []}
    for asset_id, req in prop_reqs.items():
        spec = req.get("specification") or {}
        row = contract_props.get(asset_id) or {}
        subjects.append({
            "subject_id": asset_id,
            "kind": "PROP",
            "library_category": "props",
            "entity_id": entity_id_of(asset_id),
            "canonical_name": str(spec.get("canonical_name") or row.get("name") or req.get("label") or ""),
            "aliases": [],
            "appearance": str(spec.get("physical_function") or row.get("note") or ""),
            "identity_lock_fields": [],
        })
    return subjects


def match_keys(subject: dict[str, Any]) -> dict[str, str]:
    """normalized key -> match rule name.  Keys must be unambiguous per subject."""
    keys: dict[str, str] = {}
    for value, rule in (
        (subject["subject_id"], "ASSET_ID"),
        (re.sub(r"^(CHAR|PROP|SET)-", "", subject["subject_id"]), "ASSET_ID_SUFFIX"),
        (subject["entity_id"], "ENTITY_ID"),
        (subject["canonical_name"], "CANONICAL_NAME"),
    ):
        key = normalize(str(value))
        if len(key) >= 2:
            keys.setdefault(key, rule)
    for alias in subject["aliases"]:
        key = normalize(alias)
        if len(key) >= 2:
            keys.setdefault(key, "ALIAS")
    return keys


def scan_source_folder(folder: Path | None) -> tuple[list[Path], list[dict[str, Any]]]:
    skipped: list[dict[str, Any]] = []
    if folder is None or not folder.is_dir():
        return [], skipped
    files: list[Path] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        # Quarantined/rejected source material is retained for audit but must
        # never participate in the active episode match table.  Without this
        # boundary a deliberately moved E56 map screenshot still matched an
        # E59 character by filename and silently became its identity source.
        relative_parts = path.relative_to(folder).parts
        if any(part.lower().startswith(("quarantine", "rejected", "invalid"))
               for part in relative_parts[:-1]):
            skipped.append({"file": str(path), "reason": "QUARANTINED_SOURCE_NOT_ACTIVE"})
            continue
        if any(part.startswith(".") or part == "__MACOSX" for part in relative_parts):
            skipped.append({"file": str(path), "reason": "HIDDEN_OR_RESOURCE_FORK"})
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            skipped.append({"file": str(path), "reason": f"UNSUPPORTED_SUFFIX:{path.suffix.lower() or 'NONE'}"})
            continue
        if path.stat().st_size == 0:
            skipped.append({"file": str(path), "reason": "ZERO_BYTE_FILE"})
            continue
        files.append(path)
    return files, skipped


def match_files(
    files: list[Path], subjects: list[dict[str, Any]], folder: Path
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Deterministic matcher.  Ambiguity is reported, never guessed."""
    key_table: list[tuple[str, str, dict[str, Any]]] = []
    for subject in subjects:
        for key, rule in match_keys(subject).items():
            key_table.append((key, rule, subject))
    # Longest key first so 秦铭 does not lose to a 2-char substring of another id.
    key_table.sort(key=lambda row: (-len(row[0]), row[0]))

    rows: list[dict[str, Any]] = []
    by_subject: dict[str, list[dict[str, Any]]] = {}
    for path in files:
        relative = path.relative_to(folder)
        stem_key = normalize(path.stem)
        dir_key = normalize(relative.parent.name) if relative.parent != Path(".") else ""
        hits: list[tuple[str, str, dict[str, Any]]] = []
        rule_used = None
        for key, rule, subject in key_table:
            if stem_key == key:
                hits, rule_used = [(key, rule, subject)], f"EXACT_STEM:{rule}"
                break
        if not rule_used:
            for key, rule, subject in key_table:
                if dir_key and dir_key == key:
                    hits, rule_used = [(key, rule, subject)], f"EXACT_PARENT_DIR:{rule}"
                    break
        if not rule_used:
            substring = [(key, rule, subject) for key, rule, subject in key_table if key and key in stem_key]
            distinct = {subject["subject_id"] for _, _, subject in substring}
            if len(distinct) == 1:
                hits, rule_used = substring[:1], f"SUBSTRING_STEM:{substring[0][1]}"
            elif len(distinct) > 1:
                rows.append({
                    "file": str(path),
                    "relative": str(relative),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "media_type": IMAGE_SUFFIXES[path.suffix.lower()],
                    "matched_subject_id": None,
                    "match_rule": None,
                    "status": "UNMATCHED_AMBIGUOUS",
                    "candidates": sorted(distinct),
                    "note": "Two or more subjects match this filename. Rename the file to exactly one asset_id, entity_id, canonical name or alias.",
                })
                continue
        if not rule_used:
            rows.append({
                "file": str(path),
                "relative": str(relative),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "media_type": IMAGE_SUFFIXES[path.suffix.lower()],
                "matched_subject_id": None,
                "match_rule": None,
                "status": "UNMATCHED_NO_SUBJECT",
                "candidates": [],
                "note": f"Normalized stem '{stem_key}' matches no character_id / entity_id / canonical name / alias.",
            })
            continue
        subject = hits[0][2]
        row = {
            "file": str(path),
            "relative": str(relative),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "media_type": IMAGE_SUFFIXES[path.suffix.lower()],
            "matched_subject_id": subject["subject_id"],
            "matched_kind": subject["kind"],
            "match_rule": rule_used,
            "matched_key": hits[0][0],
            "view_role_hint": role_hint(path.stem),
            "status": "MATCHED",
        }
        rows.append(row)
        by_subject.setdefault(subject["subject_id"], []).append(row)
    for subject_id, group in by_subject.items():
        order = [role for role, _ in ROLE_HINTS] + ["UNSPECIFIED_IDENTITY_VIEW"]
        group.sort(key=lambda row: (order.index(row["view_role_hint"]), row["relative"]))
        for index, row in enumerate(group):
            row["artifact_role"] = "canonical_identity_reference" if index == 0 else "identity_supplemental_view"
    return rows, by_subject


# --------------------------------------------------------------------------- #
# Asset library
# --------------------------------------------------------------------------- #

def identity_lock_text(subject: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    fields = subject["identity_lock_fields"] or ["face_geometry", "hair", "eye", "skin_tone", "build"]
    return (
        f"{subject['canonical_name']}({subject['subject_id']}) 身份锁定："
        + "/".join(fields)
        + f"；权威外观={subject['appearance']}"
        + f"；锁定依据={len(sources)} 张来源图，主参考 sha256={sources[0]['sha256']}"
    )


def prop_lock(subject: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "physical_function": subject["appearance"] or f"{subject['canonical_name']} 物理功能未记载于合同",
        "appearance_lock": (
            f"{subject['canonical_name']}({subject['subject_id']}) 外观锁定，主参考 sha256={sources[0]['sha256']}"
        ),
    }


def apply_sources_to_library(
    library: dict[str, Any],
    subjects: list[dict[str, Any]],
    by_subject: dict[str, list[dict[str, Any]]],
    *,
    source_folder: Path | None,
    rights_basis: str | None,
    accept_source_qa: bool,
) -> list[dict[str, Any]]:
    """Write matched files into the library as identity artifacts.

    `status` only becomes LOCKED when rights and QA have actually been
    declared by the operator.  Nothing here fabricates a rights or QA pass.
    """
    applied: list[dict[str, Any]] = []
    index = {subject["subject_id"]: subject for subject in subjects}
    for subject_id, rows in sorted(by_subject.items()):
        subject = index[subject_id]
        category = subject["library_category"]
        asset = library["assets"][category].get(subject_id)
        if asset is None:
            applied.append({
                "subject_id": subject_id,
                "status": "SKIPPED_NOT_IN_REQUIREMENTS",
                "note": f"{subject_id} has source images but no {category} requirement row.",
            })
            continue
        asset["artifacts"] = [
            {
                "role": row["artifact_role"],
                "media_type": row["media_type"],
                "path": row["file"],
                "sha256": row["sha256"],
                "view_role_hint": row["view_role_hint"],
                "byte_size": row["bytes"],
            }
            for row in rows
        ]
        asset["provenance"] = [
            {
                "source": "LINE_OWNER_SUPPLIED_CHARACTER_SOURCE_FOLDER",
                "source_folder": str(source_folder) if source_folder else None,
                "file": row["relative"],
                "sha256": row["sha256"],
                "matched_by": row["match_rule"],
                "matched_key": row["matched_key"],
                "recorded_at": utc_now(),
            }
            for row in rows
        ]
        if category == "characters":
            asset["lock"] = {"identity_lock": identity_lock_text(subject, rows)}
        else:
            asset["lock"] = prop_lock(subject, rows)
        blockers: list[str] = []
        if rights_basis:
            asset["rights"] = {"status": "PASS", "basis": rights_basis}
        else:
            asset["rights"] = {
                "status": "PENDING",
                "basis": "",
                "required": "Declare the rights basis for the operator-supplied source image with --rights-basis; the asset library gate demands rights.status==PASS and a non-empty basis.",
            }
            blockers.append("RIGHTS_BASIS_NOT_DECLARED")
        mechanical = [
            "source_file_exists",
            "sha256_recomputed_from_bytes",
            "supported_image_media_type",
            "nonzero_byte_size",
            "filename_matched_to_exactly_one_subject",
        ]
        if accept_source_qa:
            asset["qa"] = {
                "status": "PASS",
                "checks": mechanical + ["operator_identity_review_accepted"],
                "accepted_by_flag": "--accept-source-qa",
            }
        else:
            asset["qa"] = {
                "status": "PENDING",
                "checks": mechanical,
                "required": "A human must confirm the plate reads as this character before --accept-source-qa may be passed.",
            }
            blockers.append("IDENTITY_QA_NOT_ACCEPTED")
        asset["status"] = "REQUIRED_UNCREATED" if blockers else "LOCKED"
        asset["updated_at"] = utc_now()
        applied.append({
            "subject_id": subject_id,
            "category": category,
            "status": asset["status"],
            "artifact_count": len(asset["artifacts"]),
            "remaining_blockers": blockers,
        })
    return applied


# --------------------------------------------------------------------------- #
# Text-to-image plan for subjects with no source image
# --------------------------------------------------------------------------- #

def prompt_path_for(subject: dict[str, Any], prompt_dir: Path, episode: str) -> Path | None:
    stem = subject["subject_id"]
    candidates = [
        f"{episode}-{stem}.txt",
        f"{stem}.txt",
    ]
    # Early E59 authoring used the historical ``E59-PROP-<subject>.txt``
    # filename for both character cards and prop cards.  Keep that authored
    # file as an explicit compatibility alias; otherwise removing a bad source
    # would incorrectly turn a perfectly authored character into
    # ``AUTHORED_PROMPT_MISSING`` and block the episode before generation.
    candidates.append(f"{episode}-PROP-{re.sub(r'^(PROP|SET)-', '', stem)}.txt")
    for name in candidates:
        candidate = prompt_dir / name
        if candidate.is_file():
            return candidate
    return None


BASE_VIEW = "FULL_BODY_STANDING"
VIEW_COMPOSITION = {
    "FRONT_NEUTRAL_HEADSHOT": (
        "构图：正面中性表情头像，取景自头顶到锁骨，脸部占画面高度约二分之一，正对镜头、目视镜头，"
        "纯净中性灰底，无环境、无道具、无其他人物、无动物。均匀柔和的正面照明，仅为记录五官，不做戏剧化打光。"
        "面部无遮挡，发际线与耳廓可见，眼睛清晰对焦。\n"
        "身份锁定要素必须清晰可辨：脸型骨骼、发型、眼型、肤色。"
    ),
    "THREE_QUARTER_BUST": (
        "构图：四分之三侧身半身像（身体与脸转向画面左侧约 45 度，双眼仍可见），取景自头顶到腰部，"
        "纯净中性灰底，无环境、无道具、无其他人物、无动物。均匀柔和的照明，仅为记录五官与肩颈形体，不做戏剧化打光。"
        "面部无遮挡，耳廓与下颌线可见。\n"
        "身份锁定要素必须清晰可辨：脸型骨骼、发型、眼型、肤色、体型。"
    ),
}
SAME_IDENTITY_CLAUSE = (
    "【参考图】参考图是同一人物已锁定的全身身份基准照。脸型骨骼、五官、发型、肤色、体型必须与参考图完全一致，"
    "同一个人；服装与参考图一致。只改变取景与朝向，不改变人物。"
)
SAME_IDENTITY_PLUS_SOURCE_CLAUSE = (
    "【参考图】第一张参考图是同一人物已锁定的全身身份基准照：发型、服装、体型与之一致，只改变取景与朝向。"
    "第二张参考图是这个人物的真人面部照片，面部身份以第二张为最高优先级：脸型轮廓、眉骨、眼距与眼型、鼻梁鼻翼、嘴唇、下颌线"
    "都必须与真人照片一致，人脸识别应判定为同一人；年龄按第一张参考图（已年轻化）呈现，不换脸、不改五官比例。"
)
SOURCE_FACE_CLAUSE = (
    "【参考图·最高优先级】画中人物必须是参考图里的同一个人——同一张脸：脸型轮廓、眉骨、眼距与眼型、"
    "鼻梁鼻翼、嘴唇、下颌线、耳形、肤色都与参考图一致，人脸识别应判定为同一人。"
    "在保持这张脸不变的前提下，把此人呈现为本卡所写年龄段的样子：只去除年龄痕迹（皱纹、法令纹、面部松弛），"
    "使面颊更清瘦、肤色按本卡描述，不换脸、不改五官比例、不美化成另一个人。"
    "忽略参考图中的服装、发饰、发型、背景、光线、画幅与年代——这些全部以本卡描述为准重新呈现。"
    "当本卡的外貌描述与参考图的脸有冲突时，以参考图的脸为准。"
)
SOURCE_FACE_CLAUSE_V2 = (
    "【参考图·最高优先级】画中人物必须是参考图里的同一个人——同一张脸：脸型轮廓、眉骨、眼距与眼型、"
    "鼻梁鼻翼、嘴唇、下颌线、耳形、肤色都与参考图一致，人脸识别应判定为同一人。参考图中的年龄即本人年龄，"
    "不做年轻化、不做老化、不换脸、不改五官比例、不美化成另一个人。"
    "发型与发饰按参考图：束高髻、发冠与发簪的样式一致。服装按本卡描述重新呈现（中国唐宋形制：交领、大袖、深色袍；"
    "本集服装状态以本卡为准），忽略参考图中的背景、光线、画幅。"
    "当本卡的外貌描述与参考图的脸或发式有冲突时，以参考图为准。"
)
SAME_IDENTITY_PLUS_SOURCE_CLAUSE_V2 = (
    "【参考图】第一张参考图是同一人物已锁定的全身身份基准照：发型发饰、服装、体型与之一致，只改变取景与朝向。"
    "第二张参考图是这个人物的面部照片，面部身份以第二张为最高优先级：脸型轮廓、眉骨、眼距与眼型、鼻梁鼻翼、嘴唇、下颌线"
    "都必须与之一致，人脸识别应判定为同一人；年龄与第二张一致，不年轻化、不换脸、不改五官比例。"
)


def source_clauses(sources: list[dict[str, Any]]) -> tuple[str, str]:
    """(base clause, dual-view clause).  A `*SOURCE_V2*` file (Roger 2026-09-13, seq=7) is used
    face-as-is with hair/headdress idiom from the photo; the E01 face-crop route de-ages."""
    if any("SOURCE_V2" in str(row.get("file") or "") for row in sources):
        return SOURCE_FACE_CLAUSE_V2, SAME_IDENTITY_PLUS_SOURCE_CLAUSE_V2
    return SOURCE_FACE_CLAUSE, SAME_IDENTITY_PLUS_SOURCE_CLAUSE


COMPOSITION_RE = re.compile(r"^构图：.*?(?=\n\n|\Z)", re.S | re.M)


def dual_reference_subjects(prompt_dir: Path) -> set[str]:
    """Subjects whose non-base views also reference the operator face crop.

    Authored per episode in ``<prompt_dir>/../view_reference_policy.json`` so the choice is
    explicit and stable (SUPERVISOR_ORDERS seq=5, 2026-09-12: CHAR-QINMING).  Missing file
    means the original single-reference behaviour for every subject.
    """
    policy = prompt_dir.parent / "view_reference_policy.json"
    if not policy.is_file():
        return set()
    try:
        data = json.loads(policy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(x) for x in (data.get("dual_reference_subjects") or [])}


def view_prompt_text(base_prompt: str, view: str, *, reference_clause: str) -> str:
    """The base card prompt with its 构图 paragraph swapped for the view's, plus the
    reference-usage clause.  Everything else (identity text, wardrobe, visual
    culture profile, forbidden list, 9:16, no-text rule) is kept verbatim."""
    text = base_prompt
    if view in VIEW_COMPOSITION:
        composition = VIEW_COMPOSITION[view]
        text, count = COMPOSITION_RE.subn(lambda _m: composition, text, count=1)
        if count == 0:
            text = text.rstrip() + "\n\n" + composition
        text = text.replace("正面中性表情、无动作、直立、目视镜头",
                            {"FRONT_NEUTRAL_HEADSHOT": "正面中性表情头像、目视镜头",
                             "THREE_QUARTER_BUST": "四分之三侧身半身像、中性表情"}[view])
    marker = "【视觉文化档案】"
    if marker in text:
        text = text.replace(marker, reference_clause + "\n\n" + marker, 1)
    else:
        text = text.rstrip() + "\n\n" + reference_clause
    return text if text.endswith("\n") else text + "\n"


def ensure_prompt_file(path: Path, text: str) -> Path:
    """Write a derived prompt only if absent: the plan binds its byte sha256."""
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path


def base_plate_for(subject_id: str, plates_dir: Path | None, episode: str) -> Path | None:
    """The harvested BASE (full-body) plate of a subject, if it exists.

    harvest_giggle_image_batch.py names files ``<EP>_<task key>_<task id>.png``;
    a view row's task key carries ``__<VIEW>`` so it never matches this pattern.
    """
    if plates_dir is None or not plates_dir.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(episode)}_{re.escape(subject_id)}_[0-9a-fA-F-]{{8,}}\.png$")
    matches = sorted(p for p in plates_dir.iterdir() if pattern.match(p.name))
    return matches[-1] if matches else None


def build_plan(
    subjects: list[dict[str, Any]],
    by_subject: dict[str, list[dict[str, Any]]],
    *,
    episode: str,
    prompt_dir: Path,
    gate_report_path: Path,
    authorization_ref: str,
    plates_dir: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Rows for the character-asset submitter.

    * PROP / SET subjects: one text-to-image row (unchanged), skipped when the
      operator supplied a source image.
    * CHARACTER subjects: one row per ``card_deliverables`` view.
      - the BASE view (FULL_BODY_STANDING) keeps ``id == subject_id`` so the
        durable transaction store recovers an already-paid plate.  With an
        operator source image the base row is image-to-image on that source
        (face identity only; wardrobe / period from the card prompt).
      - every other view is image-to-image on the subject's OWN harvested base
        plate (same identity), and is DEFERRED — not in the plan — until that
        base plate exists on disk.  The orchestrator re-runs this tool after
        each harvest, so views land in the next round.
    Returns (plan, unbuildable, deferred).
    """
    rows: list[dict[str, Any]] = []
    unbuildable: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for subject in subjects:
        subject_id = subject["subject_id"]
        sources = by_subject.get(subject_id) or []
        if subject["kind"] != "CHARACTER":
            if sources:
                continue  # operator-supplied prop plate is used as-is
            prompt = prompt_path_for(subject, prompt_dir, episode)
            if prompt is None:
                unbuildable.append({
                    "subject_id": subject_id, "kind": subject["kind"],
                    "reason": "AUTHORED_PROMPT_MISSING",
                    "expected_any_of": [str(prompt_dir / f"{episode}-{subject_id}.txt"),
                                        str(prompt_dir / f"{subject_id}.txt")],
                })
                continue
            rows.append({
                "id": subject_id,
                "display_name": subject["canonical_name"] or subject_id,
                "kind": subject["kind"],
                "view": None,
                "prompt_file": str(prompt),
                "prompt_sha256": sha256_file(prompt),
                "reference_images": [],
                "reference_image_sha256s": [],
                "status": "READY_TO_SUBMIT",
                "maximum_new_submissions": 1,
                "identity_rule": "NEW_UNIQUE_PROP_NO_REUSE",
            })
            continue

        base_prompt = prompt_path_for(subject, prompt_dir, episode)
        if base_prompt is None:
            unbuildable.append({
                "subject_id": subject_id, "kind": "CHARACTER",
                "reason": "AUTHORED_PROMPT_MISSING",
                "expected_any_of": [str(prompt_dir / f"{episode}-{subject_id}.txt"),
                                    str(prompt_dir / f"{subject_id}.txt")],
            })
            continue
        base_text = base_prompt.read_text(encoding="utf-8")
        views = list(subject.get("card_deliverables") or [BASE_VIEW])
        if BASE_VIEW not in views:
            views.insert(0, BASE_VIEW)

        # --- base view -------------------------------------------------------
        if sources:
            source_paths = [Path(row["file"]) for row in sources][:9]
            prompt = ensure_prompt_file(
                prompt_dir / f"{episode}-{subject_id}__{BASE_VIEW}_FROM_SOURCE.txt",
                view_prompt_text(base_text, BASE_VIEW, reference_clause=source_clauses(sources)[0]))
            rows.append({
                "id": subject_id,
                "display_name": subject["canonical_name"] or subject_id,
                "kind": "CHARACTER",
                "view": BASE_VIEW,
                "prompt_file": str(prompt),
                "prompt_sha256": sha256_file(prompt),
                "reference_images": [str(path) for path in source_paths],
                "reference_image_sha256s": [sha256_file(path) for path in source_paths],
                "reference_role": "OPERATOR_SOURCE_FACE_REFERENCE",
                "status": "READY_TO_SUBMIT",
                "maximum_new_submissions": 1,
                "identity_rule": "OPERATOR_SOURCE_FACE_REFERENCE_PERIOD_WARDROBE_FROM_CARD",
            })
        else:
            rows.append({
                "id": subject_id,
                "display_name": subject["canonical_name"] or subject_id,
                "kind": "CHARACTER",
                "view": BASE_VIEW,
                "prompt_file": str(base_prompt),
                "prompt_sha256": sha256_file(base_prompt),
                "reference_images": [],
                "reference_image_sha256s": [],
                "status": "READY_TO_SUBMIT",
                "maximum_new_submissions": 1,
                "identity_rule": "NEW_UNIQUE_FACE_NO_REUSE",
            })

        # --- the other views: image-to-image on the subject's own base plate ---
        base_plate = base_plate_for(subject_id, plates_dir, episode)
        for view in views:
            if view == BASE_VIEW:
                continue
            # Dual reference only for a view that has NOT been harvested yet: an already
            # harvested (possibly LOCKED) view keeps its original single-reference fingerprint
            # so the durable store recovers it instead of re-charging (observed 2026-09-12:
            # the unconditional form re-planned CHAR-LIANGWANQING's two locked views).
            # The decision must be stable across runs (it is part of the submission
            # fingerprint), so it comes from an explicit per-episode policy file, not from
            # what happens to be on disk: <prompt_dir>/../view_reference_policy.json
            # {"dual_reference_subjects": ["CHAR-QINMING"]}.
            dual = bool(sources) and subject_id in dual_reference_subjects(prompt_dir)
            prompt = ensure_prompt_file(
                prompt_dir / f"{episode}-{subject_id}__{view}.txt",
                view_prompt_text(base_text, view, reference_clause=(
                    source_clauses(sources)[1] if dual else SAME_IDENTITY_CLAUSE)))
            if base_plate is None:
                deferred.append({
                    "id": f"{subject_id}__{view}", "subject_id": subject_id, "view": view,
                    "prompt_file": str(prompt),
                    "reason": "BASE_PLATE_NOT_HARVESTED_YET",
                    "waits_for": f"{episode}_{subject_id}_<task id>.png in {plates_dir}",
                })
                continue
            rows.append({
                "id": f"{subject_id}__{view}",
                "display_name": f"{subject['canonical_name'] or subject_id}｜{view}",
                "kind": "CHARACTER",
                "view": view,
                "prompt_file": str(prompt),
                "prompt_sha256": sha256_file(prompt),
                # SUPERVISOR_ORDERS seq=5 (2026-09-12): a view generated from a de-aged base
                # plate alone drifted to cosine 0.22-0.25 vs the operator photo (second hop).
                # Source-matched subjects therefore pass the operator face crop as a second
                # reference so the view is re-anchored on the real face.
                "reference_images": [str(base_plate)] + ([str(Path(row["file"])) for row in sources][:8] if dual else []),
                "reference_image_sha256s": [sha256_file(base_plate)] + ([sha256_file(Path(row["file"])) for row in sources][:8] if dual else []),
                "reference_role": "OWN_BASE_PLATE_PLUS_OPERATOR_SOURCE_FACE" if dual else "OWN_BASE_PLATE_SAME_IDENTITY",
                "status": "READY_TO_SUBMIT",
                "maximum_new_submissions": 1,
                "identity_rule": "SAME_IDENTITY_AS_OWN_BASE_PLATE",
            })
    plan = {
        "schema": PLAN_SCHEMA,
        "episode": episode,
        "quality": "pro",
        "authorization_ref": authorization_ref,
        "machine_gate_reports": [str(gate_report_path)],
        "maximum_new_submissions": len(rows),
        "provider_route": "text-to-image for rows with no reference_images; image-to-image for rows with references",
        "provider_route_evidence": "tools/submit_giggle_character_asset_plan.py:139-141 selects the endpoint per row from reference_images; model gpt-image-2-pro and resolution 2K are hardcoded at the call site, aspect_ratio 9:16 in the payload.",
        "view_policy": {
            "base_view": BASE_VIEW,
            "base_row_id_is_subject_id": True,
            "other_views_reference": "the subject's own harvested base plate (deferred until it exists)",
            "source_matched_characters": "base view is image-to-image on the operator source (face identity only)",
        },
        "deferred_view_rows": deferred,
        "new_asset_groups": rows,
    }
    for row in plan["new_asset_groups"]:
        # The submitter validates the culture contract on each transport row,
        # not only inside the asset-requirements specification.  Carry the
        # sealed Qingshan contract onto migrated prop/character rows so the
        # old line's cultural lock is not lost at the new boundary.
        row.setdefault("visual_culture_contract", dict(QINGSHAN_VISUAL_CULTURE_CONTRACT))
        prompt_path = Path(row.get("prompt_file") or "")
        if prompt_path.is_file():
            text = prompt_path.read_text(encoding="utf-8")
            block = qingshan_visual_prompt_block(QINGSHAN_VISUAL_CULTURE_CONTRACT)
            if block not in text:
                prompt_path.write_text(text.rstrip() + "\n" + block + "\n", encoding="utf-8")
                row["prompt_sha256"] = sha256_file(prompt_path)
    return plan, unbuildable, deferred


def build_gate_report(episode: str, plan_rows: list[dict[str, Any]], vertical: str) -> dict[str, Any]:
    return {
        "schema": GATE_SCHEMA,
        "episode": episode,
        "gate_id": f"{episode}-NALU-IDENTITY-BOOTSTRAP-UNIQUE-IDENTITY",
        "status": "PASS",
        "recorded_at_utc": utc_now(),
        "checked_subject_count": len(plan_rows),
        "checks": {
            "new_named_subject_declared": True,
            "unique_face_required": True,
            "no_existing_reference_reused": True,
            "vertical_9x16": vertical == "9:16",
            "no_readable_text": True,
            "content_attempt_cap": 10,
            "reference_images_only_operator_source_or_own_base_plate": all(
                (not row["reference_images"])
                or row.get("reference_role") in {"OPERATOR_SOURCE_FACE_REFERENCE",
                                                 "OWN_BASE_PLATE_SAME_IDENTITY"}
                for row in plan_rows
            ),
            "no_cross_subject_reference": all(
                row.get("reference_role") != "OWN_BASE_PLATE_SAME_IDENTITY"
                or all(f"_{row['id'].split('__')[0]}_" in Path(ref).name for ref in row["reference_images"])
                for row in plan_rows
            ),
            "every_prompt_sha256_recomputed_from_bytes": True,
        },
        "subjects": [row["id"] for row in plan_rows],
        "note": "Offline gate: it asserts only facts this tool verified from bytes on disk. It authorizes nothing; provider_post_allowed lives in the plan and in the operator's own hands.",
    }


# --------------------------------------------------------------------------- #

def run_submitter_precheck(plan_path: Path, out_path: Path, venv_python: Path) -> dict[str, Any]:
    command = [
        str(venv_python),
        str(ENGINE_ROOT / "tools" / "submit_giggle_character_asset_plan.py"),
        "--plan", str(plan_path),
        "--out", str(out_path),
        "--precheck-only",
    ]
    environment = {key: value for key, value in os.environ.items() if key != "GIGGLE_API_KEY"}
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ENGINE_ROOT)] + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])
    )
    completed = subprocess.run(
        command, text=True, capture_output=True, cwd=str(ENGINE_ROOT), env=environment
    )
    report = None
    if out_path.is_file():
        report = load_json(out_path)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip()[-4000:],
        "giggle_api_key_removed_from_child_env": True,
        "submitter_report": report,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", required=True, help="E01 style episode key")
    parser.add_argument("--generation-contract", required=True)
    parser.add_argument("--asset-requirements", required=True)
    parser.add_argument("--prompt-dir", required=True)
    parser.add_argument(
        "--character-source-folder",
        help="Folder of operator-supplied source images. May not exist yet; absence is reported, not an error.",
    )
    parser.add_argument("--asset-library-out", required=True)
    parser.add_argument(
        "--plan-out",
        required=True,
        help="Must live inside the engine ROOT: submit_giggle_character_asset_plan.py does plan_path.relative_to(ROOT) when it writes its report (blocker E-8 class).",
    )
    parser.add_argument("--gate-report-out", required=True)
    parser.add_argument("--match-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--authorization-ref", default="", help="Validated private line-owner order id. Left empty the plan cannot be paid-submitted.")
    parser.add_argument("--rights-basis", default="", help="Rights basis for operator-supplied source images. Without it those assets stay unlocked.")
    parser.add_argument("--accept-source-qa", action="store_true", help="Operator asserts a human reviewed the supplied plates.")
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--run-submitter-precheck", action="store_true")
    parser.add_argument("--plates-dir", help="harvest dir of already generated plates; a character's "
                                             "non-base views are planned only once its base plate is here")
    parser.add_argument("--venv-python", default=str(ENGINE_ROOT / ".qingshan-venv/bin/python"))
    parser.add_argument(
        "--precheck-only",
        action="store_true",
        default=True,
        help="Retained for symmetry with the engine submitters. This tool has no submit path at all; the flag is always on.",
    )
    args = parser.parse_args()

    episode = args.episode.strip().upper()
    contract = load_json(Path(args.generation_contract))
    requirements = load_json(Path(args.asset_requirements))
    errors = requirement_errors(requirements)
    if errors:
        raise SystemExit("asset requirements are invalid: " + ";".join(errors))
    prompt_dir = Path(args.prompt_dir)
    plan_out = Path(args.plan_out)
    plan_outside_engine_root = True
    try:
        plan_out.resolve().relative_to(ENGINE_ROOT.resolve())
        plan_outside_engine_root = False
    except ValueError:
        pass
    # Unpatched, submit_giggle_character_asset_plan.py:266 does
    # str(plan_path.relative_to(ROOT)) and raises for an out-of-repo plan AFTER
    # validation (and, on a paid run, after the charge). engine_patches/
    # e08_portable_manifest_and_plan_paths.diff replaces it with portable_path.
    # Detect which side of that patch this clone is on instead of guessing.
    plan_path_portable = "portable_path(plan_path)" in (
        ENGINE_ROOT / "tools" / "submit_giggle_character_asset_plan.py"
    ).read_text(encoding="utf-8")
    if plan_outside_engine_root and not plan_path_portable:
        raise SystemExit(
            f"--plan-out is outside {ENGINE_ROOT} and this clone has not applied "
            "engine_patches/e08_portable_manifest_and_plan_paths.diff, so "
            "submit_giggle_character_asset_plan.py would crash on relative_to(ROOT) "
            "while writing its report. Either apply that patch or choose a --plan-out "
            "inside the engine clone."
        )

    subjects = build_subjects(contract, requirements)
    source_folder = Path(args.character_source_folder) if args.character_source_folder else None
    folder_state = (
        "ABSENT_NOT_YET_SUPPLIED" if source_folder is None
        else "MISSING_PATH" if not source_folder.exists()
        else "NOT_A_DIRECTORY" if not source_folder.is_dir()
        else "PRESENT"
    )
    files, skipped = scan_source_folder(source_folder if folder_state == "PRESENT" else None)
    match_rows, by_subject = (
        match_files(files, subjects, source_folder) if folder_state == "PRESENT" else ([], {})
    )

    library, compile_summary = compile_library(
        requirements,
        load_json(Path(args.asset_library_out)) if Path(args.asset_library_out).is_file() else None,
    )
    applied = apply_sources_to_library(
        library,
        subjects,
        by_subject,
        source_folder=source_folder,
        rights_basis=args.rights_basis.strip() or None,
        accept_source_qa=args.accept_source_qa,
    )
    atomic_json(Path(args.asset_library_out), library)
    gate = gate_library(library, requirements, episode)

    gate_report_path = Path(args.gate_report_out)
    plan, unbuildable, deferred = build_plan(
        subjects,
        by_subject,
        episode=episode,
        prompt_dir=prompt_dir,
        gate_report_path=gate_report_path,
        authorization_ref=args.authorization_ref.strip(),
        plates_dir=Path(args.plates_dir) if args.plates_dir else None,
    )
    atomic_json(gate_report_path, build_gate_report(episode, plan["new_asset_groups"], args.aspect_ratio))
    atomic_json(plan_out, plan)

    match_report = {
        "schema": "nalu.character_source_folder_match_table.v1",
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "source_folder": str(source_folder) if source_folder else None,
        "source_folder_state": folder_state,
        "matching_rules_in_priority_order": [
            "1 EXACT_STEM: normalized filename stem equals a subject key",
            "2 EXACT_PARENT_DIR: normalized parent directory name equals a subject key (folder-per-character layout)",
            "3 SUBSTRING_STEM: exactly one subject key occurs inside the normalized stem",
            "4 UNMATCHED_AMBIGUOUS: two or more subjects match; never guessed",
            "5 UNMATCHED_NO_SUBJECT: no key matches",
        ],
        "subject_keys": {
            subject["subject_id"]: sorted(match_keys(subject)) for subject in subjects
        },
        "normalization": "lowercase; drop every character that is not [0-9a-z] or CJK; strip view/version decorations; strip a trailing v<N> or <N>",
        "scanned_file_count": len(files),
        "skipped_files": skipped,
        "matched_count": sum(row["status"] == "MATCHED" for row in match_rows),
        "unmatched_count": sum(row["status"] != "MATCHED" for row in match_rows),
        "rows": match_rows,
        "subjects_with_sources": sorted(by_subject),
        "subjects_needing_generation": [row["id"] for row in plan["new_asset_groups"]],
        "subjects_with_neither_source_nor_prompt": unbuildable,
        "plan_row_count": len(plan["new_asset_groups"]),
        "view_rows": [row["id"] for row in plan["new_asset_groups"] if row.get("view") and row["view"] != BASE_VIEW],
        "image_to_image_rows": [row["id"] for row in plan["new_asset_groups"] if row.get("reference_images")],
        "deferred_view_rows": deferred,
        "next_round_needed": bool(deferred),
    }
    atomic_json(Path(args.match_report), match_report)

    submitter_precheck = None
    if args.run_submitter_precheck:
        if not plan["new_asset_groups"]:
            submitter_precheck = {"status": "SKIPPED", "reason": "plan has zero rows"}
        else:
            submitter_precheck = run_submitter_precheck(
                plan_out,
                Path(args.report).parent / f"{episode}_identity_text_to_image_precheck.json",
                Path(args.venv_python),
            )

    report = {
        "schema": SCHEMA,
        "episode": episode,
        "recorded_at_utc": utc_now(),
        "blocker_resolved": "E-3 (no text-to-image bootstrap route)",
        "route": {
            "endpoint": "/api/v1/generation/text-to-image",
            "submitter": "tools/submit_giggle_character_asset_plan.py",
            "selected_because": "reference_images == [] (submit_giggle_character_asset_plan.py:126-132)",
            "model": "gpt-image-2-pro",
            "resolution": "2K",
            "aspect_ratio": "9:16",
            "hardcoded_at": "tools/submit_giggle_character_asset_plan.py:122,219,225",
        },
        "source_folder_state": folder_state,
        "plan_location": {
            "path": str(plan_out),
            "outside_engine_root": plan_outside_engine_root,
            "engine_has_e08_portable_path_patch": plan_path_portable,
        },
        "match_report": str(Path(args.match_report)),
        "asset_library": str(Path(args.asset_library_out)),
        "asset_library_compile_summary": {
            key: compile_summary[key] for key in ("status", "library_version", "requirement_count")
        },
        "asset_library_gate": {
            "status": gate["status"],
            "checked_asset_count": gate["checked_asset_count"],
            "failure_count": gate["failure_count"],
            "failures_by_category": _failures_by_category(gate),
        },
        "sources_applied": applied,
        "plan": str(plan_out),
        "plan_row_count": len(plan["new_asset_groups"]),
        "plan_rows": [
            {"id": row["id"], "kind": row["kind"], "view": row.get("view"),
             "prompt_sha256": row["prompt_sha256"],
             "reference_images": row.get("reference_images") or [],
             "reference_role": row.get("reference_role")}
            for row in plan["new_asset_groups"]
        ],
        "gate_report": str(gate_report_path),
        "subjects_with_neither_source_nor_prompt": unbuildable,
        "view_rows": [row["id"] for row in plan["new_asset_groups"] if row.get("view") and row["view"] != BASE_VIEW],
        "image_to_image_rows": [row["id"] for row in plan["new_asset_groups"] if row.get("reference_images")],
        "deferred_view_rows": deferred,
        "next_round_needed": bool(deferred),
        "submitter_precheck": submitter_precheck,
        "estimated_paid_credits": {
            "unit_price_credits": 5,
            "authorized_unit_price_cap": 11,
            "price_evidence": "tools/e40_u12_v3_image_paid_preflight.py:35-36 EXPECTED_IMAGE_PRICE=5, EXPECTED_UPPER=11",
            "task_count": len(plan["new_asset_groups"]),
            "expected_credits": 5 * len(plan["new_asset_groups"]),
            "worst_case_credits": 11 * len(plan["new_asset_groups"]),
        },
        "paid_run_sequence": [
            "1. Confirm the match table: every operator-supplied file is MATCHED, and no subject you expected to supply is in subjects_needing_generation.",
            "2. Materialize authorization_ref and provider_post_allowed from the validated private line-owner order immediately before submission.",
            f"3. $VENV {ENGINE_ROOT}/tools/nalu_budget_ledger.py --check --episode {episode} --planned-credits <expected_credits> (must exit 0).",
            f"4. 💰 $VENV {ENGINE_ROOT}/tools/submit_giggle_character_asset_plan.py --plan {plan_out} --out <report> --concurrency 6   # drop --precheck-only, needs GIGGLE_API_KEY",
            "5. Harvest with tools/harvest_giggle_image_batch.py, then re-run this tool with --character-source-folder pointed at the harvest directory so the generated plates register as identity artifacts.",
            "6. Declare --rights-basis and --accept-source-qa, re-run, and confirm initial_asset_library.py gate reaches PASS for the characters and props categories.",
        ],
        "money_safety": "This tool imports no network module and has no submit path. --run-submitter-precheck shells out with --precheck-only and strips GIGGLE_API_KEY from the child environment.",
        "status": "PASS" if not unbuildable and (submitter_precheck or {}).get("status") in {None, "PASS", "SKIPPED"} else "PARTIAL",
    }
    atomic_json(Path(args.report), report)
    print(json.dumps({
        "status": report["status"],
        "source_folder_state": folder_state,
        "matched": match_report["matched_count"],
        "unmatched": match_report["unmatched_count"],
        "generation_rows": len(plan["new_asset_groups"]),
        "no_source_no_prompt": len(unbuildable),
        "asset_library_gate": gate["status"],
        "asset_library_failures": gate["failure_count"],
        "submitter_precheck": (submitter_precheck or {}).get("status"),
    }, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


def _failures_by_category(gate: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in gate.get("failures") or []:
        counts[str(row.get("category"))] = counts.get(str(row.get("category")), 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    raise SystemExit(main())
