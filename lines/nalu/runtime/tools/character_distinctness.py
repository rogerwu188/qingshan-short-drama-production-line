#!/usr/bin/env python3
"""Cross-character distinctness of the S3 identity cards (line owner 2026-11-19, 《摄政王她又来找茬了》 device …0841).

Two different characters of one episode came out of S3 with nearly the same face (same jaw, nose, eyes, smile):
a black-robed young man with a crescent forehead mark and a black-armoured young man with dragon pauldrons.  The
identity gates only ever asked "is this plate the declared character", never "is it also another character".

This module is the prevention and the check, stdlib only (the embedder is injected):

``contrast_block``          the face-structure contrast paragraph written into a NEW character card prompt
                            (build_episode_asset_requirements): face shape, jaw, eyes, nose, brows, age, build and
                            marks, contrasted with the other characters of the same sex and age band.
``differentiation_block``   the stronger paragraph a regenerated card carries (bootstrap_identity_cards reads it
                            from ``<prompt_dir>/../identity_distinctness.json``).
``pairwise``                InsightFace cosine between every pair of DIFFERENT characters' cards.
``evaluate``                live-action: pairs at/above ``TOO_SIMILAR_COSINE`` -> regenerate the LATER character's
                            card once with ``differentiation_block``; a pair already regenerated once is accepted and
                            recorded as an ADVISORY.  Never a block: nothing here can stop S3.
``anime_record``            anime: InsightFace is NOT_APPLICABLE (render_style.INSIGHTFACE_NOT_APPLICABLE_REASON); the
                            identity review's descriptive question ``anime_cast_design_distinct`` is the evidence and a
                            TOO_SIMILAR answer is recorded as an advisory (no regeneration, no block).

Threshold (gate registry ``CHARACTER-IDENTITY-ADMISSION``, configs/GATE_REGISTRY_v3_20260716.json):
``embedding_cosine_pass_threshold`` 0.45 = same person, ``embedding_cosine_fail_threshold`` 0.30 = a different
person, and ``embedding_cosine_boundary_auto_decision_midpoint`` 0.375 is where the gate's own boundary rule starts to
lean towards "same person".  Two DIFFERENT characters whose cards score >= 0.38 (just above that midpoint) are
therefore no longer separable by the downstream identity gates: a frame of B would sit in A's boundary band and be
arbitrated as A.  Hence ``TOO_SIMILAR_COSINE = 0.38``.

Cost: one regenerated base card per too-similar pair (+ its non-base views, which are image-to-image on the new base
plate and would have been generated anyway once) -- a few images, capped at one regeneration per pair.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = "nalu.character_distinctness.v1"
POLICY_SCHEMA = "nalu.identity_distinctness_policy.v1"
POLICY_NAME = "identity_distinctness.json"          # <prompt_dir>/../identity_distinctness.json
REPORT_SUFFIX = "CHARACTER_DISTINCTNESS.json"        # <identity dir>/<EP>_CHARACTER_DISTINCTNESS.json
METHOD = "INSIGHTFACE_COSINE_V1_CROSS_CHARACTER"
ANIME_METHOD = "VLM_ANIME_CAST_DESIGN_DISTINCT_V1"
ANIME_QUESTION = "anime_cast_design_distinct"
ANIME_ENUM = ["DISTINCT", "TOO_SIMILAR", "NOT_APPLICABLE"]
#: registry boundary midpoint 0.375 (see the module docstring), rounded up
TOO_SIMILAR_COSINE = 0.38
SAME_PERSON_COSINE = 0.45
MAX_REGENERATIONS_PER_PAIR = 1
AUTHORITY = "ADVISORY_NOT_A_GATE: at most one regeneration per pair, then accepted and recorded"

FACE_FIELDS_ZH = "脸型、下颌线、眼型与眼距、鼻梁与鼻型、眉形、唇形、颧骨、年龄感、体型、标志性特征（痣、疤、印记）"
FACE_FIELDS_EN = ("face shape, jawline, eye shape and spacing, nose bridge and shape, brows, lips, cheekbones, "
                  "apparent age, build and distinctive marks (moles, scars, marks)")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cjk(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", str(text or "")))


def _short(text: Any, limit: int = 60) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def age_range(value: Any) -> tuple[float, float] | None:
    """``"20-25岁"`` / ``"25–30"`` / ``"about 30"`` -> (lo, hi); None when no number."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]
    if not nums:
        return None
    return (min(nums[:2]), max(nums[:2]))


def same_band(a: dict[str, Any], b: dict[str, Any], *, slack: float = 5.0) -> bool:
    """Same sex (when both are declared) and apparent-age ranges within ``slack`` years of each other."""
    sa, sb = str(a.get("sex") or "").strip().lower(), str(b.get("sex") or "").strip().lower()
    if sa and sb and sa != sb:
        return False
    ra, rb = age_range(a.get("age")), age_range(b.get("age"))
    if ra is None or rb is None:
        return True
    return ra[0] - slack <= rb[1] and rb[0] - slack <= ra[1]


def cast_row(spec: dict[str, Any], subject_id: str) -> dict[str, Any]:
    """A requirement row's specification -> the small dict the blocks use."""
    return {"subject_id": subject_id,
            "name": spec.get("canonical_name") or spec.get("name") or subject_id,
            "sex": spec.get("sex"), "age": spec.get("apparent_age_range") or spec.get("age"),
            "appearance": spec.get("appearance_ch1") or spec.get("appearance") or ""}


def contrast_block(own: dict[str, Any], cast: Iterable[dict[str, Any]], *, language: str = "zh") -> str:
    """Prevention at S3 identity design: every NEW card prompt names its own face structure, and the characters of
    the same sex and age band it must not resemble.  '' never: a card with no peer still gets the face-structure line."""
    peers = [row for row in cast if row.get("subject_id") != own.get("subject_id") and same_band(own, row)]
    if language == "en":
        head = (f"FACE DESIGN (distinct from every other character): give {own.get('name')} a specific, "
                f"individual face — {FACE_FIELDS_EN} — not a generic handsome/pretty face.")
        if not peers:
            return head
        names = "; ".join(f"{p['name']} ({_short(p.get('appearance'), 50)})" for p in peers[:4])
        return (head + f" Same sex and age band as: {names}. The face structure must be clearly different from "
                "theirs (different face shape, jaw, eyes, nose and brows), not only the costume or hair.")
    head = (f"【面部区分·硬性】{own.get('name')}的面孔必须具体、独特：{FACE_FIELDS_ZH}逐项写实，"
            "不画通用的俊美/秀美脸。")
    if not peers:
        return head
    names = "；".join(f"{p['name']}（{_short(p.get('appearance'), 40)}）" for p in peers[:4])
    return (head + f"同性别、同年龄段的角色：{names}。本角色的脸型、下颌、眼型、鼻型、眉形必须与他们明显不同，"
            "不能只靠服装、发型或配饰区分；同一观众一眼能分出是两个人。")


def differentiation_block(own: dict[str, Any], against: Iterable[dict[str, Any]], *, cosine: float | None = None,
                          language: str = "zh") -> str:
    """The stronger paragraph a regenerated card carries: the measured lookalike is named and every face-structure
    field is pushed to the opposite of the other character's."""
    others = list(against)
    if language == "en":
        names = "; ".join(f"{o['name']} ({_short(o.get('appearance'), 60)})" for o in others) or "another character"
        measured = f" (face-embedding similarity {cosine:.2f})" if cosine is not None else ""
        return (f"DISTINCT FACE (regenerated): the previous card of {own.get('name')} looked like {names}{measured}. "
                f"Design a clearly different person: change {FACE_FIELDS_EN} so that each differs visibly from "
                f"{names}. Contrast, e.g. a longer/narrower or broader/squarer face, a different jaw, different eye "
                "shape and brow line, a different nose; keep the age, sex, wardrobe and story description exactly as "
                "written above.")
    names = "；".join(f"{o['name']}（{_short(o.get('appearance'), 50)}）" for o in others) or "另一角色"
    measured = f"（人脸相似度 {cosine:.2f}）" if cosine is not None else ""
    return (f"【面部区分·重做】上一版{own.get('name')}的身份卡与 {names} 长得太像{measured}。"
            f"重新设计成明显不同的另一个人：{FACE_FIELDS_ZH}逐项与对方拉开差异——例如脸型长窄对宽方、下颌尖对方、"
            "眼型细长对圆、眉形平直对上扬、鼻梁高窄对短宽；年龄、性别、服装与剧情外貌描述照上文不变。")


# --------------------------------------------------------------------------- measurement
def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return float(num / (na * nb)) if na and nb else 0.0


def pairwise(embeddings: dict[str, list[list[float]]], order: list[str] | None = None,
             cosine: Callable[[list[float], list[float]], float] | None = None) -> list[dict[str, Any]]:
    """One row per unordered pair of DIFFERENT characters: the highest cosine between any of their card embeddings
    (a, b in ``order``, so ``b`` is the later character)."""
    cos = cosine or _cos
    ids = [cid for cid in (order or sorted(embeddings)) if embeddings.get(cid)]
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            score = max(cos(x, y) for x in embeddings[a] for y in embeddings[b])
            rows.append({"a": a, "b": b, "pair": pair_key(a, b), "cosine": round(float(score), 6)})
    rows.sort(key=lambda r: -r["cosine"])
    return rows


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((str(a), str(b))))


def load_policy(prompt_dir: Path | str | None) -> dict[str, Any]:
    if prompt_dir is None:
        return {}
    path = Path(prompt_dir).parent / POLICY_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def regenerated_pairs(policy: dict[str, Any]) -> set[str]:
    return {str(p) for row in (policy.get("regenerations") or {}).values() if isinstance(row, dict)
            for p in row.get("pairs") or []}


def evaluate(embeddings: dict[str, list[list[float]]], *, order: list[str], cast: dict[str, dict[str, Any]],
             policy: dict[str, Any], regenerable: Iterable[str], threshold: float = TOO_SIMILAR_COSINE,
             cosine: Callable[[list[float], list[float]], float] | None = None,
             unmeasured: dict[str, str] | None = None) -> dict[str, Any]:
    """The distinctness verdict for one S3 round.

    ``regenerable``: subjects S3 may regenerate (episode-new, text-to-image cards; never an operator-photo card or a
    character LOCKED in an earlier episode).  A too-similar pair regenerates its LATER regenerable member once; a pair
    already in the policy's regenerations (cap reached) or with no regenerable member becomes an ADVISORY."""
    regenerable = set(regenerable)
    done = regenerated_pairs(policy)
    rows = pairwise(embeddings, order, cosine)
    position = {cid: i for i, cid in enumerate(order)}
    regenerate: dict[str, dict[str, Any]] = {}
    advisories: list[dict[str, Any]] = []
    for row in rows:
        if row["cosine"] < threshold:
            continue
        if row["pair"] in done:
            advisories.append({**row, "reason": "TOO_SIMILAR_AFTER_ONE_REGENERATION_ACCEPTED"})
            continue
        candidates = sorted((c for c in (row["a"], row["b"]) if c in regenerable),
                            key=lambda c: -position.get(c, -1))
        target = next((c for c in candidates if c not in regenerate), None)
        if target is None and candidates:
            regenerate[candidates[0]]["pairs"].append(row["pair"])  # one regeneration answers both pairs
            regenerate[candidates[0]]["against"].append(row["a"] if candidates[0] == row["b"] else row["b"])
            continue
        if target is None:
            advisories.append({**row, "reason": "TOO_SIMILAR_NO_REGENERABLE_CARD"})
            continue
        other = row["a"] if target == row["b"] else row["b"]
        regenerate[target] = {"subject_id": target, "pairs": [row["pair"]], "against": [other],
                              "cosine_before": row["cosine"]}
    for target, action in regenerate.items():
        own = cast.get(target) or {"subject_id": target, "name": target}
        lang = "zh" if _cjk(json.dumps(own, ensure_ascii=False)) else "en"
        action["block"] = differentiation_block(own, [cast.get(o) or {"name": o} for o in action["against"]],
                                                cosine=action["cosine_before"], language=lang)
    return {
        "schema": SCHEMA, "method": METHOD, "authority": AUTHORITY, "evaluated_at": _now(),
        "threshold": threshold, "threshold_basis": (
            "GATE_REGISTRY_v3 CHARACTER-IDENTITY-ADMISSION: pass 0.45 = same person, fail 0.30, boundary "
            "auto-decision midpoint 0.375; >= 0.38 between DIFFERENT characters = not separable downstream"),
        "characters": [cid for cid in order if embeddings.get(cid)],
        "unmeasured": dict(unmeasured or {}),
        "pairs": rows,
        "too_similar": [r for r in rows if r["cosine"] >= threshold],
        "regenerate": list(regenerate.values()),
        "advisories": advisories,
        "status": ("REGENERATE" if regenerate else "ADVISORY" if advisories else "PASS"),
    }


def apply_regenerations(report: dict[str, Any], *, prompt_dir: Path, plates_dir: Path, episode: str,
                        policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the regenerations in the policy file (bootstrap_identity_cards reads it and plans a new prompt, i.e. a
    new fingerprint) and park the subject's harvested plates, so the submitter's harvested-binding reuse does not
    hand the old face back.  Plates are moved, never deleted."""
    policy = dict(policy if policy is not None else load_policy(prompt_dir))
    policy.setdefault("schema", POLICY_SCHEMA)
    regens = dict(policy.get("regenerations") or {})
    parked: list[str] = []
    for action in report.get("regenerate") or []:
        sid = action["subject_id"]
        prior = regens.get(sid) or {}
        round_no = int(prior.get("round") or 0) + 1
        regens[sid] = {"pairs": sorted(set(prior.get("pairs") or []) | set(action["pairs"])),
                       "against": sorted(set(prior.get("against") or []) | set(action["against"])),
                       "cosine_before": action.get("cosine_before"), "block": action["block"],
                       "round": round_no, "suffix": f"__DISTINCT_R{round_no}", "at": _now()}
        parked += park_subject_plates(plates_dir, episode, sid)
    policy["regenerations"] = regens
    policy["updated_at"] = _now()
    path = Path(prompt_dir).parent / POLICY_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"policy": str(path), "parked": parked}


def park_subject_plates(plates_dir: Path, episode: str, subject_id: str) -> list[str]:
    plates_dir = Path(plates_dir)
    if not plates_dir.is_dir():
        return []
    pattern = re.compile(rf"^{re.escape(episode)}_{re.escape(subject_id)}(?:__[A-Z][A-Z_]*[A-Z])?_"
                         r"(?:[0-9a-fA-F-]{8,}|tsk_[0-9A-Za-z_]{8,})\.(?:png|jpe?g|webp)$")
    target = plates_dir / "_distinctness_superseded"
    out = []
    for item in sorted(plates_dir.iterdir()):
        if item.is_file() and pattern.match(item.name) and "__MULTIVIEW_REFERENCE_SHEET" not in item.name:
            target.mkdir(parents=True, exist_ok=True)
            dest = target / item.name
            item.replace(dest)
            out.append(str(dest))
    return out


def regeneration_for(prompt_dir: Path | str | None, subject_id: str) -> dict[str, Any] | None:
    row = (load_policy(prompt_dir).get("regenerations") or {}).get(subject_id)
    return row if isinstance(row, dict) and row.get("block") else None


# --------------------------------------------------------------------------- anime
# the question itself lives in render_style.CAST_DISTINCT_QUESTION_SPEC (the identity questionnaire of an anime series)


def anime_record(items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The anime distinctness record from the identity review items ({item_id, answers, observation})."""
    rows, advisories = [], []
    for item in items:
        answer = str(((item.get("answers") or {}).get(ANIME_QUESTION)) or "").strip().upper()
        if not answer:
            continue
        row = {"subject_id": item.get("item_id"), "answer": answer,
               "observation": _short(item.get("observation"), 200)}
        rows.append(row)
        if answer == "TOO_SIMILAR":
            advisories.append({**row, "reason": "ANIME_DESIGN_TOO_SIMILAR_REVIEWER"})
    return {"schema": SCHEMA, "method": ANIME_METHOD, "authority": AUTHORITY, "evaluated_at": _now(),
            "insightface": "NOT_APPLICABLE", "answers": rows, "advisories": advisories,
            "status": "ADVISORY" if advisories else ("PASS" if rows else "NOT_REVIEWED")}


def lookalike_pairs(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pairs a later stage should know about (final review measurement / S8): every pair at/above the threshold of
    the latest S3 measurement, with the regeneration state."""
    if not isinstance(report, dict):
        return []
    out = []
    regenerated = {p for r in report.get("regenerate") or [] for p in r.get("pairs") or []}
    for row in report.get("pairs") or []:
        if float(row.get("cosine") or 0.0) >= float(report.get("threshold") or TOO_SIMILAR_COSINE):
            out.append({k: row.get(k) for k in ("a", "b", "cosine")}
                       | {"state": "REGENERATING" if row.get("pair") in regenerated else "ACCEPTED_ADVISORY"})
    for row in report.get("advisories") or []:
        if row.get("subject_id"):
            out.append({"a": row.get("subject_id"), "b": None, "cosine": None, "state": row.get("reason")})
    return out
