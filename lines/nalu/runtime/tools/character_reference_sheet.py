#!/usr/bin/env python3
"""Multi-view character reference sheet for MiniMax-H3 (provider-expert advice, line owner 2026-10-26).

One image per character: a front face close-up plus full-body front / side / back views of the same person
on a plain grey background, same wardrobe (a standard turnaround sheet).  H3 reads it as that character's
face-and-body reference instead of the single headshot plate; the identity plates (headshot / bust / full
body) stay the InsightFace identity authority and are never replaced.

* Scope: CAMERA_GRAMMAR_V1 contracts only (``camera_grammar_policy.active``); a contract opts out with
  ``"character_reference_sheet": "NONE"``.  Every other episode plans, stores and references nothing new.
* Cost: generated once per character at S3 (one extra image-to-image row, ~11 credits, costed by the S3 round
  planner like any plan row).  A character already LOCKED in the series library gets its sheet on the next
  stamped episode, made from its locked full-body + headshot plates.
* Physical traits: an appearance that declares a missing limb, scar, eyepatch ... is restated as a must-show
  clause.  ``character_entities[].state_variants`` (``{"one_arm": "left arm missing below the elbow"}``)
  plans one extra sheet per declared state (no cost unless declared); a cast member selects it with
  ``reference_state``.
* Storage: ``assets.characters.<CID>.reference_sheets.<STATE|DEFAULT>`` in the series asset library (a field of
  its own, never ``artifacts``, so identity lock, registry and canonical views are unchanged).  A sheet is
  registered only when one of its faces matches the locked headshot (InsightFace cosine >= 0.45); without the
  runtime it is registered as NOT_MEASURED; a mismatch is recorded and H3 keeps the headshot.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

_ENGINE_ROOT = Path(__file__).resolve().parents[4]
for _entry in (str(_ENGINE_ROOT), str(_ENGINE_ROOT / "tools")):
    if _entry not in sys.path:
        sys.path.append(_entry)

SHEET_VIEW = "MULTIVIEW_REFERENCE_SHEET"
FIELD = "character_reference_sheet"
POLICY_ID = "MULTIVIEW_SHEET_V1"
DEFAULT_STATE = "DEFAULT"
MIN_FACE_COSINE = 0.45
VOICE_ONLY_NO_PLATE = "VOICE_ONLY_NO_PLATE"

#: physical-trait words: the sentence that carries one becomes a must-show clause on every view
_TRAIT = re.compile(
    r"(scar|missing|one[- ]armed|one[- ]legged|amputat|stump|prosthe|eye ?patch|one[- ]eyed|blind|burn mark|"
    r"birthmark|tattoo|limp|crutch|hook hand|wooden leg|疤|独臂|断臂|断腿|缺(?:了)?(?:一|左|右)?(?:只|条|根)?[手臂腿脚指眼耳]|"
    r"假肢|义肢|独眼|眼罩|瘸|跛|胎记|纹身|烧伤|拐杖)", re.IGNORECASE)


def sheet_id(character_id: str, state: str | None = None) -> str:
    key = state_key(state)
    return f"{character_id}__{SHEET_VIEW}" + ("" if key == DEFAULT_STATE else f"__{key}")


def state_key(state: str | None) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", str(state or "")).strip("_").upper()
    return value or DEFAULT_STATE


def active(contract: dict[str, Any] | None, *, episode: str | None = None) -> bool:
    import camera_grammar_policy
    declared = str((contract or {}).get(FIELD) or "").strip().upper()
    if declared in {"NONE", "OFF", "DISABLED"}:
        return False
    return camera_grammar_policy.active(contract, episode=episode)


def trait_clause(appearance: str) -> str:
    """The appearance sentences that declare a physical trait, restated as a must-show clause ("" if none)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.;。；！!？?])\s*", str(appearance or "")) if s.strip()]
    traits = [s.rstrip("。.;；") for s in sentences if _TRAIT.search(s)]
    if not traits:
        return ""
    return "【身体特征·必须呈现】" + "；".join(traits) + "。这一特征在脸部特写与正面、侧面、背面每个视图中都必须清楚可见、位置一致，不得被遮挡、补全或省略。"


def sheet_prompt(entity: dict[str, Any], *, state: str | None = None, state_description: str = "",
                 wardrobe: str = "") -> str:
    name = str(entity.get("english_name") or entity.get("canonical_name") or entity.get("character_id") or "")
    appearance = str(entity.get("appearance_en") or entity.get("appearance_ch1") or entity.get("appearance") or "")
    parts = [
        f"角色设定图（多视图转面图 character turnaround sheet），只画一个人物：{name}。",
        f"外貌：{appearance}" if appearance else "",
        f"服装：{wardrobe}" if wardrobe else "",
        "构图：一张图内四个视图，都是同一个人、同一套服装、同一发型与配饰：上方是正面脸部特写（头顶到锁骨，正对镜头，"
        "中性表情，五官清晰）；下方从左到右并排三个全身像，从头顶到脚完整入画、站姿自然中性：全身正面、全身侧面（向右 90 度）、"
        "全身背面。四个视图大小协调、互不重叠。",
        "纯净中性灰色背景，无环境、无道具、无其他人物、无动物；无文字、无标签、无编号、无水印。均匀柔和的照明，只为记录长相与服装，"
        "不做戏剧化打光。",
        "【参考图】参考图是同一人物已锁定的身份照：脸型骨骼、五官、发型、肤色、体型与服装必须与参考图完全一致，同一个人；"
        "只改变排版与朝向，不改变人物。",
        trait_clause(appearance),
        (f"【本图状态·必须呈现】{state_description.rstrip('。.')}。该状态在每个视图中都必须清楚可见、位置一致。"
         if state and state_description else ""),
    ]
    return "\n\n".join(part for part in parts if part) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _library_row(library: dict[str, Any], character_id: str) -> dict[str, Any]:
    return (((library or {}).get("assets") or {}).get("characters") or {}).get(character_id) or {}


def registered_sheet(row: dict[str, Any], state: str | None = None) -> Path | None:
    """The registered sheet of a library row for ``state`` (sha verified), else None."""
    entry = (row.get("reference_sheets") or {}).get(state_key(state)) if isinstance(row, dict) else None
    if not isinstance(entry, dict) or entry.get("status") not in {"PASS", "NOT_MEASURED"}:
        return None
    path = Path(str(entry.get("path") or ""))
    if not path.is_file() or sha256_file(path) != entry.get("sha256"):
        return None
    return path


def _locked_view(row: dict[str, Any], view: str) -> Path | None:
    if row.get("status") != "LOCKED":
        return None
    for artifact in row.get("artifacts") or []:
        path = Path(str(artifact.get("path") or ""))
        role = str(artifact.get("role") or "")
        if (role == view or (view == "FULL_BODY_STANDING" and "__" not in path.name and role in {"", view})) \
                and path.is_file() and sha256_file(path) == artifact.get("sha256"):
            return path
    return None


def _harvested(plates_dir: Path | None, episode: str, row_id: str) -> Path | None:
    if plates_dir is None or not plates_dir.is_dir():
        return None
    pattern = re.compile(rf"^{re.escape(episode)}_{re.escape(row_id)}_[0-9a-fA-F-]{{8,}}\.png$")
    matches = sorted(p for p in plates_dir.iterdir() if pattern.match(p.name))
    return matches[-1] if matches else None


def plan_rows(contract: dict[str, Any], library: dict[str, Any], *, episode: str, prompt_dir: Path,
              plates_dir: Path | None, new_subject_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                                                          list[dict[str, Any]]]:
    """(plan rows, deferred rows, skipped rows) for the sheets this episode still needs.

    References: the character's own harvested base + headshot plates of this episode (a new character), else
    its LOCKED full-body + headshot artifacts in the series library.  A new character's sheet is deferred until
    its base plate is harvested; a character with neither is skipped (H3 keeps the headshot) and reported.
    """
    if not active(contract, episode=episode):
        return [], [], []
    wardrobe_by_id = {str(row.get("character_id") or ""): str(row.get("authored_description") or "")
                      for row in (contract.get("wardrobe_contract") or {}).get("characters") or []
                      if isinstance(row, dict)}
    rows: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entity in contract.get("character_entities") or []:
        cid = str(entity.get("character_id") or "")
        if not cid or str((entity.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_NO_PLATE:
            continue
        library_row = _library_row(library, cid)
        variants = entity.get("state_variants") if isinstance(entity.get("state_variants"), dict) else {}
        for state, description in [(None, "")] + [(str(k), str(v)) for k, v in variants.items()]:
            row_id = sheet_id(cid, state)
            if registered_sheet(library_row, state) is not None:
                continue
            prompt_path = prompt_dir / f"{episode}-{row_id}.txt"
            if not prompt_path.is_file():  # written once: the plan binds its byte sha256
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                prompt_path.write_text(sheet_prompt(entity, state=state, state_description=description,
                                                    wardrobe=wardrobe_by_id.get(cid, "")), encoding="utf-8")
            base = _harvested(plates_dir, episode, cid)
            head = _harvested(plates_dir, episode, f"{cid}__FRONT_NEUTRAL_HEADSHOT")
            if base is None:
                base = _locked_view(library_row, "FULL_BODY_STANDING")
                head = _locked_view(library_row, "FRONT_NEUTRAL_HEADSHOT")
            if base is None:
                (deferred if cid in new_subject_ids else skipped).append({
                    "id": row_id, "subject_id": cid, "view": SHEET_VIEW, "prompt_file": str(prompt_path),
                    "reason": ("BASE_PLATE_NOT_HARVESTED_YET" if cid in new_subject_ids
                               else "NO_LOCKED_FULL_BODY_PLATE_H3_KEEPS_HEADSHOT")})
                continue
            references = [base] + ([head] if head is not None else [])
            rows.append({
                "id": row_id,
                "display_name": f"{entity.get('canonical_name') or cid}｜{SHEET_VIEW}"
                                + (f"｜{state_key(state)}" if state else ""),
                "kind": "CHARACTER",
                "view": SHEET_VIEW,
                "reference_state": state_key(state),
                "prompt_file": str(prompt_path),
                "prompt_sha256": sha256_file(prompt_path),
                "reference_images": [str(path) for path in references],
                "reference_image_sha256s": [sha256_file(path) for path in references],
                "reference_role": "OWN_LOCKED_PLATES_SAME_IDENTITY",
                "status": "READY_TO_SUBMIT",
                "maximum_new_submissions": 1,
                "identity_rule": "SAME_IDENTITY_AS_OWN_LOCKED_PLATES",
            })
    return rows, deferred, skipped


def harvested_sheets(plates_dir: Path, episode: str) -> list[tuple[str, str, Path]]:
    """(character_id, state key, path) of every sheet harvested in this episode."""
    pattern = re.compile(rf"^{re.escape(episode)}_(CHAR-[^_]+(?:_[^_]+)*?)__{SHEET_VIEW}(?:__([A-Z0-9_]+?))?_[0-9a-fA-F-]{{8,}}\.png$")
    found: dict[tuple[str, str], Path] = {}
    if plates_dir.is_dir():
        for path in sorted(plates_dir.iterdir()):
            match = pattern.match(path.name)
            if match:
                found[(match.group(1), state_key(match.group(2)))] = path
    return [(cid, key, path) for (cid, key), path in sorted(found.items())]


def register(library_path: Path, plates_dir: Path, episode: str,
             measure: Callable[[Path, Path], float | None] | None = None) -> list[dict[str, Any]]:
    """Record harvested sheets on their library rows; returns one report row per sheet.

    ``measure(sheet, headshot)`` returns the best face cosine (None = runtime unavailable)."""
    if not library_path.is_file():
        return []
    library = json.loads(library_path.read_text(encoding="utf-8"))
    characters = ((library.get("assets") or {}).get("characters") or {})
    report: list[dict[str, Any]] = []
    changed = False
    for cid, key, path in harvested_sheets(plates_dir, episode):
        row = characters.get(cid)
        if not isinstance(row, dict):
            report.append({"character_id": cid, "state": key, "path": str(path), "status": "NO_LIBRARY_ROW"})
            continue
        sha = sha256_file(path)
        current = (row.get("reference_sheets") or {}).get(key) or {}
        if current.get("sha256") == sha:
            continue
        head = _locked_view(row, "FRONT_NEUTRAL_HEADSHOT") or _harvested(plates_dir, episode, f"{cid}__FRONT_NEUTRAL_HEADSHOT")
        cosine = measure(path, head) if (measure and head is not None) else None
        status = "NOT_MEASURED" if cosine is None else ("PASS" if cosine >= MIN_FACE_COSINE else "FAIL_FACE_MISMATCH")
        entry = {"path": str(path), "sha256": sha, "episode": episode, "view": SHEET_VIEW, "state": key,
                 "status": status, "identity_measurement": {
                     "method": "INSIGHTFACE_MAX_FACE_COSINE_VS_LOCKED_HEADSHOT", "cosine": cosine,
                     "threshold": MIN_FACE_COSINE, "headshot": str(head) if head else None},
                 "role": "H3_FACE_AND_BODY_REFERENCE_NOT_IDENTITY_AUTHORITY"}
        row.setdefault("reference_sheets", {})[key] = entry
        changed = True
        report.append({"character_id": cid, **entry})
    if changed:
        library_path.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def insightface_measure() -> Callable[[Path, Path], float | None] | None:
    """Best face cosine between a sheet (several faces) and the locked headshot; None without the runtime."""
    try:
        from tools.character_identity_admission_gate import InsightFaceBackend, _cosine
        backend = InsightFaceBackend("buffalo_l")
    except Exception:  # noqa: BLE001 - runtime optional; registration records NOT_MEASURED
        return None

    def measure(sheet: Path, head: Path) -> float | None:
        try:
            reference = backend.embed(Path(head))
            return max((_cosine(reference, face) for face in backend.embed_all(Path(sheet))), default=0.0)
        except Exception:  # noqa: BLE001
            return None
    return measure
