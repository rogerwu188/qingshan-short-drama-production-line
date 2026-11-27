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
#: two characters of the SAME sex and an overlapping apparent-age band are judged stricter (2026-11-21, KO E05 on
#: device ...0080: "the male lead speaking looks like the same person" -- the alternating speakers were two men of
#: the same age band): the registry's fail line 0.30 is "a different person"; a same-band pair above 0.32 already
#: reads as one face on a phone screen
SAME_BAND_TOO_SIMILAR_COSINE = 0.32
#: locked cards (earlier episodes) of a too-similar pair: at most this many are re-designed per episode
MAX_LOCKED_REGENERATIONS_PER_EPISODE = 2
LOCKED_SUPERSEDED_STATUS = "SUPERSEDED_DISTINCTNESS_PENDING_REGENERATION"
SAME_PERSON_COSINE = 0.45
MAX_REGENERATIONS_PER_PAIR = 1
AUTHORITY = "ADVISORY_NOT_A_GATE: at most one regeneration per pair, then accepted and recorded"

FACE_FIELDS_ZH = "脸型、下颌线、眼型与眼距、鼻梁与鼻型、眉形、唇形、颧骨、年龄感、体型、标志性特征（痣、疤、印记）"
FACE_FIELDS_EN = ("face shape, jawline, eye shape and spacing, nose bridge and shape, brows, lips, cheekbones, "
                  "apparent age, build and distinctive marks (moles, scars, marks)")


def regenerated_this_episode(episode: str, *, plan: dict[str, Any] | None = None,
                             libraries: Iterable[dict[str, Any] | None] = ()) -> set[str]:
    """Subjects this episode generates anew even though their requirement row may still say
    REUSED_FROM_PRIOR_LIBRARY (device ...1101 E29 2026-11-27: S3 re-designed the LOCKED card CHAR-MOHANYUAN for
    distinctness, but the cross-episode reuse marking dropped the new card from the identity review request, so it was
    never locked and the asset-library gate failed).  A regenerated card is never "reused": it is reviewed and locked
    by identity QA like a new card.  Covers (a) every subject the identity plan generates in this episode and (b) a
    library card S3 superseded for distinctness (status SUPERSEDED_DISTINCTNESS_PENDING_REGENERATION, or a
    ``distinctness_regeneration`` recorded for this episode).  Never raises."""
    out: set[str] = set()
    ep = str(episode or "").strip().upper()
    try:
        for row in (plan or {}).get("new_asset_groups") or []:
            if isinstance(row, dict):
                sid = str(row.get("subject_id") or row.get("id") or "").strip()
                if sid:
                    out.add(sid)
    except Exception:  # noqa: BLE001
        pass
    for library in libraries:
        try:
            for assets in ((library or {}).get("assets") or {}).values():
                if not isinstance(assets, dict):
                    continue
                for aid, asset in assets.items():
                    if not isinstance(asset, dict):
                        continue
                    regen = asset.get("distinctness_regeneration")
                    if (asset.get("status") == LOCKED_SUPERSEDED_STATUS
                            or (isinstance(regen, dict) and str(regen.get("episode") or "").strip().upper() == ep)):
                        out.add(str(aid))
        except Exception:  # noqa: BLE001
            continue
    return out


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


def pair_threshold(a: dict[str, Any] | None, b: dict[str, Any] | None, base: float = TOO_SIMILAR_COSINE) -> float:
    """The too-similar line of one pair: stricter for two characters of the same declared sex and an overlapping
    apparent-age band (both sexes must be declared), ``base`` otherwise."""
    a, b = a or {}, b or {}
    sa, sb = str(a.get("sex") or "").strip().lower(), str(b.get("sex") or "").strip().lower()
    if sa and sb and sa == sb and same_band(a, b):
        return min(base, SAME_BAND_TOO_SIMILAR_COSINE)
    return base


# --------------------------------------------------------------------------- explicit differentiating traits
#: (zh, en) options per trait; a card's plan is picked deterministically from its id, a regenerated card's plan
#: avoids the options of the character it was too similar to (hair style, face shape, age look, glasses /
#: facial hair, build -- the traits a viewer separates two people by at phone size).  Hair options name a STYLE
#: only, never a colour: the bible's hair colour is the character's (device 1101 E24, 2026-11-23).
TRAITS: dict[str, list[tuple[str, str]]] = {
    "face": [("长窄脸、下颌线清晰", "a long narrow face with a defined jaw"),
             ("宽方脸、下颌方正", "a broad square face with a square jaw"),
             ("圆脸、下颌圆润", "a round face with a soft jaw"),
             ("心形脸、下巴尖", "a heart-shaped face with a pointed chin"),
             ("高颧骨的棱角脸", "an angular face with high cheekbones")],
    "hair_m": [("很短的寸头", "a very short crew cut"), ("整齐的侧分短发", "neat side-parted short hair"),
               ("向后梳的背头", "swept-back hair"), ("略带自然卷的中长发", "slightly wavy medium-length hair"),
               ("两鬓斑白的短发", "short hair greying at the temples")],
    "hair_f": [("长直发", "long straight hair"), ("齐肩短发", "a shoulder-length bob"),
               ("低马尾", "a low ponytail"), ("很短的精灵短发", "a short pixie cut"), ("盘起的微卷发", "wavy hair worn up")],
    "extra_m": [("干净无胡须", "clean-shaven"), ("淡淡的胡茬", "light stubble"), ("细框眼镜", "thin-rimmed glasses"),
                ("修剪整齐的短胡子", "a short neat beard"), ("黑框眼镜", "black-framed glasses")],
    "extra_f": [("不戴眼镜、眉形平直", "no glasses, straight brows"), ("细框眼镜", "thin-rimmed glasses"),
                ("眉形上扬", "arched brows"), ("眼下一颗小痣", "a small mole under one eye"),
                ("浓眉", "full, strong brows")],
    "build": [("清瘦", "a slim build"), ("结实宽肩", "a broad-shouldered, solid build"), ("高而偏瘦", "a tall lanky build"),
              ("中等偏壮", "a medium, sturdy build")],
    "age": [("看起来在年龄段的偏年轻一端", "looks at the younger end of the written age range"),
            ("看起来在年龄段的偏年长一端", "looks at the older end of the written age range")],
}

#: PERIOD_TRAIT_LOCK (device 1101 E24, 2026-11-23: the demon and a townsperson of a xianxia line wore modern round
#: eyeglasses).  A pre-modern series (visual_culture_contract.is_premodern_period) never gets glasses, greying hair
#: or a modern haircut from the trait plan; these options replace the modern ones trait by trait.
PERIOD_TRAITS: dict[str, list[tuple[str, str]]] = {
    "hair_m": [("高束发髻", "hair tied up in a high topknot"), ("高马尾", "hair in a high ponytail"),
               ("半束半披的长发", "long hair half tied up, half loose"), ("披肩散发", "loose shoulder-length hair"),
               ("低束的长发", "long hair tied low at the nape")],
    "hair_f": [("长直发披肩", "long straight hair worn loose"), ("盘起的发髻", "hair coiled up in a bun"),
               ("半束半披、一支素簪", "hair half up with one plain pin"), ("低垂的长辫", "a long low braid"),
               ("双髻", "hair in two buns")],
    "extra_m": [("干净无胡须", "clean-shaven"), ("淡淡的胡茬", "light stubble"), ("细长的八字胡", "a thin moustache"),
                ("修剪整齐的短胡子", "a short neat beard"), ("一侧眉骨上的小疤", "a small scar over one brow")],
    "extra_f": [("眉形平直", "straight brows"), ("眉心一点朱砂痣", "a small red mark between the brows"),
                ("眉形上扬", "arched brows"), ("眼下一颗小痣", "a small mole under one eye"),
                ("浓眉", "full, strong brows")],
}

#: words that make a card a modern face in a pre-modern world (zh / en / ko / ja): glasses and the modern haircuts of
#: the default trait table.  Greying or white hair is never a finding: an elder's bible may well say so.
PERIOD_FORBIDDEN_TRAIT = re.compile(
    r"[^、，,;；。.\n]*(?:眼镜|镜框|镜片|寸头|背头|侧分短发|精灵短发|안경|メガネ|眼鏡|"
    r"\b(?:eye ?glasses|spectacles|glasses|monocle|crew cut|side-parted|swept-back hair|pixie cut)\b)"
    r"[^、，,;；。.\n]*", re.IGNORECASE)
_NO_GLASSES = re.compile(r"不戴眼镜|无眼镜|no glasses|without glasses", re.IGNORECASE)
PERIOD_RECARD_REASON = "PERIOD_FORBIDDEN_TRAIT"


def traits_for(period: bool = False) -> dict[str, list[tuple[str, str]]]:
    """The trait table of a series: the pre-modern table for a pre-modern world, else the default one."""
    return {**TRAITS, **PERIOD_TRAITS} if period else TRAITS


def period_trait_findings(text: Any) -> list[str]:
    """The phrases of a card prompt that a pre-modern world forbids (glasses, greying hair, modern haircut).
    "不戴眼镜" / "no glasses" is not a finding."""
    found = []
    for match in PERIOD_FORBIDDEN_TRAIT.finditer(_NO_GLASSES.sub("", str(text or ""))):
        phrase = match.group(0).strip(" 、，,;；。.")
        if phrase and phrase not in found:
            found.append(phrase)
    return found


def strip_period_traits(text: str) -> str:
    """The card prompt with every forbidden-trait phrase removed (the phrase between list separators)."""
    out = _NO_GLASSES.sub("", str(text or ""))
    out = PERIOD_FORBIDDEN_TRAIT.sub("", out)
    out = re.sub(r"[、，,;；]\s*(?=[、，,;；。.]|$)", "", out)
    out = re.sub(r"([：:])\s*[、，,;；]\s*", r"\1 ", out)
    return re.sub(r"[ \t]{2,}", " ", out)


def period_block(own: dict[str, Any], findings: Iterable[str], *, language: str = "zh") -> str:
    """The paragraph a pre-modern card regenerated for a forbidden trait carries (bootstrap strips the phrases)."""
    named = "、".join(findings) if language == "zh" else "; ".join(findings)
    if language == "en":
        return (f"PERIOD LOOK (regenerated): the previous card of {own.get('name')} showed modern traits ({named}). "
                "This is a pre-modern world: no eyeglasses or spectacles, no modern haircut, no modern accessory; "
                "hair colour exactly as the description above. Keep the face, sex, age range, wardrobe and story "
                "description exactly as written above.")
    return (f"【时代造型·重做】上一版{own.get('name')}的身份卡出现了现代特征（{named}）。本剧是古代世界："
            "不戴任何眼镜，不用现代发型，不戴现代饰物；发色严格按上文描述。脸型、性别、年龄段、服装与剧情外貌描述照上文不变。")


def _sex_key(row: dict[str, Any] | None) -> str:
    sex = str((row or {}).get("sex") or "").strip().lower()
    return "f" if sex in ("female", "f", "woman", "女") else "m"


def trait_plan(row: dict[str, Any] | None, *, avoid: Iterable[dict[str, int]] = (),
               period: bool = False) -> dict[str, int]:
    """{trait: option index} for one card: deterministic from its subject id, never equal to any plan in ``avoid``
    on a trait (when another option exists).  Pure."""
    import hashlib  # noqa: PLC0415
    row = row or {}
    sex = _sex_key(row)
    avoid = list(avoid)
    out: dict[str, int] = {}
    table = traits_for(period)
    for trait in ("face", f"hair_{sex}", f"extra_{sex}", "build", "age"):
        options = table[trait]
        seed = int(hashlib.sha256(f"{row.get('subject_id')}|{trait}".encode()).hexdigest()[:8], 16)
        taken = {a.get(trait) for a in avoid if a.get(trait) is not None}
        for step in range(len(options)):
            index = (seed + step) % len(options)
            if index not in taken or step == len(options) - 1:
                out[trait] = index
                break
    return out


def trait_text(plan: dict[str, int], *, language: str = "zh", period: bool = False) -> str:
    """The plan as one phrase list (zh or en)."""
    pos = 0 if language == "zh" else 1
    table = traits_for(period)
    return ("、" if language == "zh" else "; ").join(table[t][i][pos] for t, i in plan.items() if t in table)


def cast_row(spec: dict[str, Any], subject_id: str) -> dict[str, Any]:
    """A requirement row's specification -> the small dict the blocks use."""
    return {"subject_id": subject_id,
            "name": spec.get("canonical_name") or spec.get("name") or subject_id,
            "sex": spec.get("sex"), "age": spec.get("apparent_age_range") or spec.get("age"),
            "appearance": spec.get("appearance_ch1") or spec.get("appearance") or ""}


#: words that show a brief already names concrete facial traits (face shape, hair, eyes, glasses, facial hair)
_TRAIT_WORDS = re.compile(r"脸|颌|眼|眉|鼻|发|胡|须|眼镜|痣|疤|face|jaw|eye|brow|nose|hair|beard|moustache|mustache|"
                          r"stubble|glasses|mole|scar|얼굴|눈|머리|수염|안경", re.IGNORECASE)


def has_facial_traits(appearance: Any) -> bool:
    """The brief names at least two concrete facial / hair traits (a "middle-aged man, dark suit" does not)."""
    return len(set(m.group(0).lower() for m in _TRAIT_WORDS.finditer(str(appearance or "")))) >= 2


def contrast_block(own: dict[str, Any], cast: Iterable[dict[str, Any]], *, language: str = "zh",
                   period: bool = False) -> str:
    """Prevention at S3 identity design: every NEW card prompt names its own face structure, and the characters of
    the same sex and age band it must not resemble.  '' never: a card with no peer still gets the face-structure line.
    A brief without concrete facial traits (2026-11-21, KO E05: the secretary's brief said only "middle-aged Korean
    man, dark suit") gets an explicit trait plan that differs from every same-band peer's."""
    cast = list(cast)
    peers = [row for row in cast if row.get("subject_id") != own.get("subject_id") and same_band(own, row)]
    if not has_facial_traits(own.get("appearance")):
        plan = trait_plan(own, avoid=[trait_plan(p, period=period) for p in peers if _sex_key(p) == _sex_key(own)],
                          period=period)
        traits = (f" Concrete traits for this card: {trait_text(plan, language='en', period=period)}." if language == "en"
                  else f"本卡具体特征：{trait_text(plan, language='zh', period=period)}。")
    else:
        traits = ""
    if language == "en":
        head = (f"FACE DESIGN (distinct from every other character): give {own.get('name')} a specific, "
                f"individual face — {FACE_FIELDS_EN} — not a generic handsome/pretty face.") + traits
        if not peers:
            return head
        names = "; ".join(f"{p['name']} ({_short(p.get('appearance'), 50)})" for p in peers[:4])
        return (head + f" Same sex and age band as: {names}. The face structure must be clearly different from "
                "theirs (different face shape, jaw, eyes, nose and brows), not only the costume or hair.")
    head = (f"【面部区分·硬性】{own.get('name')}的面孔必须具体、独特：{FACE_FIELDS_ZH}逐项写实，"
            "不画通用的俊美/秀美脸。") + traits
    if not peers:
        return head
    names = "；".join(f"{p['name']}（{_short(p.get('appearance'), 40)}）" for p in peers[:4])
    return (head + f"同性别、同年龄段的角色：{names}。本角色的脸型、下颌、眼型、鼻型、眉形必须与他们明显不同，"
            "不能只靠服装、发型或配饰区分；同一观众一眼能分出是两个人。")


def differentiation_block(own: dict[str, Any], against: Iterable[dict[str, Any]], *, cosine: float | None = None,
                          language: str = "zh", period: bool = False) -> str:
    """The stronger paragraph a regenerated card carries: the measured lookalike is named and every face-structure
    field is pushed to the opposite of the other character's."""
    others = list(against)
    # explicit, concrete traits that differ from every named lookalike's own plan (2026-11-21, KO E05: a secretary
    # whose brief said only "middle-aged Korean man, dark suit" came out with the lead's face)
    plan = trait_plan(own, avoid=[trait_plan(o, period=period) for o in others], period=period)
    if language == "en":
        names = "; ".join(f"{o['name']} ({_short(o.get('appearance'), 60)})" for o in others) or "another character"
        measured = f" (face-embedding similarity {cosine:.2f})" if cosine is not None else ""
        return (f"DISTINCT FACE (regenerated): the previous card of {own.get('name')} looked like {names}{measured}. "
                f"Design a clearly different person: change {FACE_FIELDS_EN} so that each differs visibly from "
                f"{names}. Contrast, e.g. a longer/narrower or broader/squarer face, a different jaw, different eye "
                "shape and brow line, a different nose. Give this card exactly these differentiating traits: "
                f"{trait_text(plan, language='en', period=period)}; keep the sex, the age range, the wardrobe and the story "
                "description exactly as written above.")
    names = "；".join(f"{o['name']}（{_short(o.get('appearance'), 50)}）" for o in others) or "另一角色"
    measured = f"（人脸相似度 {cosine:.2f}）" if cosine is not None else ""
    return (f"【面部区分·重做】上一版{own.get('name')}的身份卡与 {names} 长得太像{measured}。"
            f"重新设计成明显不同的另一个人：{FACE_FIELDS_ZH}逐项与对方拉开差异——例如脸型长窄对宽方、下颌尖对方、"
            "眼型细长对圆、眉形平直对上扬、鼻梁高窄对短宽。本卡必须具备这些区分特征："
            f"{trait_text(plan, language='zh', period=period)}；性别、年龄段、服装与剧情外貌描述照上文不变。")


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
             unmeasured: dict[str, str] | None = None,
             locked_regenerable: Iterable[str] = (), screen_time: dict[str, float] | None = None,
             locked_cap: int = MAX_LOCKED_REGENERATIONS_PER_EPISODE, period: bool = False,
             period_recards: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """The distinctness verdict for one S3 round.  EVERY pair of different characters is scored (not only
    neighbours); a pair of the same declared sex and an overlapping age band uses the stricter
    :data:`SAME_BAND_TOO_SIMILAR_COSINE` (:func:`pair_threshold`).

    ``regenerable``: subjects S3 may regenerate (episode-new, text-to-image cards; never an operator-photo card).  A
    too-similar pair regenerates its LATER regenerable member once.  ``locked_regenerable`` (2026-11-21, KO E05 on
    device ...0080: cards locked in E01 made the check a no-op for the whole series): text-to-image cards LOCKED in
    an earlier episode that may be re-designed once -- when a too-similar pair has no episode-new regenerable member,
    the member with LESS ``screen_time`` (the secondary character; the lead keeps the card the series has shown) is
    re-designed, at most ``locked_cap`` per episode, and each card at most once (``regenerations`` of the policy).
    A pair already regenerated, or with nothing left to regenerate, becomes an ADVISORY.

    ``period`` (pre-modern world, visual_culture_contract.is_premodern_period): the differentiation traits come from
    the pre-modern table.  ``period_recards`` {subject: forbidden phrases found in its card prompt} (PERIOD_TRAIT_LOCK,
    device 1101 E24: glasses on a demon and a townsperson): each such card is regenerated ONCE through the same path
    (episode-new card, or a LOCKED one within its own ``locked_cap``), its block naming the phrases to drop."""
    regenerable = set(regenerable)
    locked_ok = set(locked_regenerable)
    screen = dict(screen_time or {})
    done = regenerated_pairs(policy)
    done_cards = {str(k) for k in (policy.get("regenerations") or {})}
    rows = pairwise(embeddings, order, cosine)
    position = {cid: i for i, cid in enumerate(order)}
    regenerate: dict[str, dict[str, Any]] = {}
    advisories: list[dict[str, Any]] = []
    too_similar: list[dict[str, Any]] = []
    locked_used = 0
    for row in rows:
        line = pair_threshold(cast.get(row["a"]), cast.get(row["b"]), threshold)
        row["threshold"] = line
        if line < threshold:
            row["same_band"] = True
        if row["cosine"] < line:
            continue
        too_similar.append(row)
        if row["pair"] in done:
            advisories.append({**row, "reason": "TOO_SIMILAR_AFTER_ONE_REGENERATION_ACCEPTED"})
            continue
        members = (row["a"], row["b"])
        already = next((c for c in members if c in regenerate), None)
        if already is not None:  # one regeneration answers both pairs
            regenerate[already]["pairs"].append(row["pair"])
            regenerate[already]["against"].append(row["a"] if already == row["b"] else row["b"])
            continue
        candidates = sorted((c for c in members if c in regenerable and c not in done_cards),
                            key=lambda c: -position.get(c, -1))
        target, unlock = (candidates[0], False) if candidates else (None, False)
        if target is None:
            locked = [c for c in members if c in locked_ok and c not in done_cards]
            if locked and locked_used < max(0, int(locked_cap)):
                # the secondary character: less screen time, then the later one in first-appearance order; the
                # member with MORE screen time (the lead) is never re-designed
                other_member = {row["a"]: row["b"], row["b"]: row["a"]}
                locked.sort(key=lambda c: (screen.get(c, 0.0), -position.get(c, -1)))
                pick = locked[0]
                if screen.get(pick, 0.0) <= screen.get(other_member[pick], 0.0):
                    target, unlock = pick, True
        if target is None:
            reason = ("TOO_SIMILAR_LOCKED_REGENERATION_CAP_REACHED" if any(c in locked_ok for c in members)
                      else "TOO_SIMILAR_NO_REGENERABLE_CARD")
            advisories.append({**row, "reason": reason})
            continue
        other = row["a"] if target == row["b"] else row["b"]
        regenerate[target] = {"subject_id": target, "pairs": [row["pair"]], "against": [other],
                              "cosine_before": row["cosine"], "threshold": line,
                              **({"unlock_locked": True, "screen_time": screen.get(target, 0.0),
                                  "kept": other, "kept_screen_time": screen.get(other, 0.0)} if unlock else {})}
        if unlock:
            locked_used += 1
    for target, action in regenerate.items():
        own = cast.get(target) or {"subject_id": target, "name": target}
        lang = "zh" if _cjk(json.dumps(own, ensure_ascii=False)) else "en"
        # differentiate from every same-band character, not only the measured lookalike (a card pushed away from
        # one face must not land on a third one)
        peers = [o for o in order if o != target and o not in action["against"]
                 and same_band(own, cast.get(o) or {}) and _sex_key(own) == _sex_key(cast.get(o))]
        action["block"] = differentiation_block(own, [cast.get(o) or {"name": o} for o in action["against"] + peers],
                                                cosine=action["cosine_before"], language=lang, period=period)
    period_used = 0
    for target, findings in (period_recards or {}).items():
        if not findings or target in done_cards:
            continue
        own = cast.get(target) or {"subject_id": target, "name": target}
        lang = "zh" if _cjk(json.dumps(own, ensure_ascii=False)) else "en"
        block = period_block(own, findings, language=lang)
        if target in regenerate:  # one regeneration answers both
            regenerate[target]["block"] += "\n" + block
            regenerate[target]["period_findings"] = list(findings)
            continue
        unlock = target not in regenerable
        if unlock and (target not in locked_ok or period_used >= max(0, int(locked_cap))):
            advisories.append({"subject_id": target, "reason": "PERIOD_TRAIT_CARD_NOT_REGENERABLE",
                               "period_findings": list(findings)})
            continue
        period_used += int(unlock)
        regenerate[target] = {"subject_id": target, "pairs": [], "against": [], "cosine_before": None,
                              "reason": PERIOD_RECARD_REASON, "period_findings": list(findings), "block": block,
                              **({"unlock_locked": True, "screen_time": screen.get(target, 0.0)} if unlock else {})}
    return {
        "schema": SCHEMA, "method": METHOD, "authority": AUTHORITY, "evaluated_at": _now(),
        "threshold": threshold, "threshold_basis": (
            "GATE_REGISTRY_v3 CHARACTER-IDENTITY-ADMISSION: pass 0.45 = same person, fail 0.30, boundary "
            "auto-decision midpoint 0.375; >= 0.38 between DIFFERENT characters = not separable downstream"),
        "characters": [cid for cid in order if embeddings.get(cid)],
        "unmeasured": dict(unmeasured or {}),
        "pairs": rows,
        "same_band_threshold": SAME_BAND_TOO_SIMILAR_COSINE,
        "too_similar": too_similar,
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
                       **({"reason": action["reason"]} if action.get("reason") else {}),
                       **({"period_findings": action["period_findings"]} if action.get("period_findings") else {}),
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
        if float(row.get("cosine") or 0.0) >= float(row.get("threshold") or report.get("threshold")
                                                     or TOO_SIMILAR_COSINE):
            out.append({k: row.get(k) for k in ("a", "b", "cosine")}
                       | {"state": "REGENERATING" if row.get("pair") in regenerated else "ACCEPTED_ADVISORY"})
    for row in report.get("advisories") or []:
        if row.get("subject_id"):
            out.append({"a": row.get("subject_id"), "b": None, "cosine": None, "state": row.get("reason")})
    return out
