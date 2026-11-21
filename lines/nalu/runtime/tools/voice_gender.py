#!/usr/bin/env python3
"""Voice casting gender: the speaking character's gender against the cast voice's gender (pure, free).

Line owner 2026-11-20 (JA-01 anime E02 ~1:13, device evidence VU-020): Rei Taylor (a woman) spoke with a man's
voice.  Mapping and off-screen handling were correct -- the CASTING was wrong: runtime/voice_catalog.json locked
CHAR-REI-TAYLOR to the MiniMax system voice ``Japanese_OptimisticYouth`` (a young man's voice, reference F0 198 Hz).
The Japanese / Korean system voices are not in the free provider catalog, the production guide listed their ids
without a gender, and neither voice_cast.json nor voice_registry.json recorded one, so nothing compared the voice
with the character.

This module answers three questions, each with the evidence it used (``basis``):

* :func:`character_gender` -- the character's gender: an explicit field (gender / sex / immutable.gender), else
  unambiguous words of its appearance text (zh / en / ja / ko);
* :func:`voice_gender` -- the voice's gender: the registry / catalog row's own field, else the curated MiniMax
  system-voice table (:data:`SYSTEM_VOICE_GENDER`), else gendered words in the voice id / name, else the reference
  F0 (secondary: under 160 Hz male, over 210 Hz female, 160-210 Hz ambiguous -> review, never a recast on F0 alone);
* :func:`casting_check` -- MISMATCH (both known, they differ), REVIEW (F0-only or ambiguous evidence against the
  character), OK or UNKNOWN; and :func:`pick_recast` the replacement voice of the right gender (same language,
  closest age class, never a voice another character already uses).

nalu_pipeline.s4_casting_gender_check runs it at the start of S4 (before any voice is generated or reused and
before S6) and auto-recasts a contradicting catalog / locked voice: blocks nothing, one 2-credit reference.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

SCHEMA = "nalu.voice_gender_check.v1"
MALE, FEMALE = "male", "female"

#: MiniMax public system voices used for Japanese / Korean lines (not in the free Giggle catalog).  Gender from the
#: provider's voice names; ids whose gender the name does not settle are left out on purpose (-> UNKNOWN, no recast).
SYSTEM_VOICE_GENDER: dict[str, str] = {
    # Japanese
    "Japanese_IntellectualSenior": MALE, "Japanese_DecisivePrincess": FEMALE, "Japanese_LoyalKnight": MALE,
    "Japanese_DominantMan": MALE, "Japanese_SeriousCommander": MALE, "Japanese_ColdQueen": FEMALE,
    "Japanese_DependableWoman": FEMALE, "Japanese_GentleButler": MALE, "Japanese_KindLady": FEMALE,
    "Japanese_CalmLady": FEMALE, "Japanese_OptimisticYouth": MALE, "Japanese_GenerousIzakayaOwner": MALE,
    "Japanese_SportyStudent": MALE, "Japanese_InnocentBoy": MALE, "Japanese_GracefulMaiden": FEMALE,
    # Korean
    "Korean_SweetGirl": FEMALE, "Korean_CheerfulBoyfriend": MALE, "Korean_EnchantingSister": FEMALE,
    "Korean_ShyGirl": FEMALE, "Korean_ReliableSister": FEMALE, "Korean_StrictBoss": MALE, "Korean_SassyGirl": FEMALE,
    "Korean_ElegantPrincess": FEMALE, "Korean_BraveYouth": MALE, "Korean_CalmLady": FEMALE,
    "Korean_IntellectualSenior": MALE, "Korean_LonelyWarrior": MALE, "Korean_MatureLady": FEMALE,
    "Korean_InnocentBoy": MALE, "Korean_ColdYoungMan": MALE, "Korean_DominantMan": MALE, "Korean_GentleBoss": MALE,
    "Korean_ColdGirl": FEMALE, "Korean_HaughtyLady": FEMALE, "Korean_IntellectualMan": MALE,
    "Korean_CaringWoman": FEMALE, "Korean_ConfidentBoss": MALE, "Korean_PossessiveMan": MALE,
    "Korean_GentleWoman": FEMALE, "Korean_CalmGentleman": MALE,
}
#: age class of the system voices (for a like-for-like recast); everything else is "adult"
_YOUTH_TOKENS = ("youth", "boy", "girl", "student", "maiden", "princess", "sister", "boyfriend", "youngman", "young")
_SENIOR_TOKENS = ("senior", "elder", "grandma", "grandpa", "old")

#: gendered words inside a voice id / name (CamelCase or snake split, lower-case).  "youth" is not gendered.
_FEMALE_TOKENS = {"girl", "lady", "princess", "woman", "women", "sister", "queen", "maiden", "wife", "mother", "mom",
                  "girlfriend", "female", "miss", "madam", "diva", "heroine", "grandma", "aunt", "daughter", "actress",
                  "bride", "empress", "witch", "goddess"}
_MALE_TOKENS = {"boy", "man", "men", "gentleman", "boss", "knight", "butler", "commander", "warrior", "boyfriend",
                "husband", "father", "dad", "grandpa", "king", "prince", "guy", "male", "uncle", "son", "lord",
                "emperor", "monk", "captain"}

#: reference F0 bands (median Hz): a secondary check only
F0_MALE_MAX = 160.0
F0_FEMALE_MIN = 210.0

_GENDER_WORDS = {
    "female": FEMALE, "f": FEMALE, "woman": FEMALE, "girl": FEMALE, "女": FEMALE, "女性": FEMALE, "여성": FEMALE,
    "male": MALE, "m": MALE, "man": MALE, "boy": MALE, "男": MALE, "男性": MALE, "남성": MALE,
}
#: appearance text: unambiguous words only (female first: "woman" contains "man")
_APPEARANCE_FEMALE = re.compile(
    r"\b(?:woman|women|girl|lady|female|actress|princess|queen|wife|mother|daughter|sister|maiden|heroine|she|her)\b"
    r"|女性|女人|女子|少女|女孩|姑娘|妇人|老妇|夫人|小姐|公主|女士|母亲|妻子|女$|女，|女,|女。|女主"
    r"|お嬢|彼女|여성|여자|소녀|아가씨|어머니|아내|그녀", re.IGNORECASE)
_APPEARANCE_MALE = re.compile(
    r"\b(?:man|men|boy|gentleman|male|actor|prince|king|husband|father|son|brother|he|his|him)\b"
    r"|男性|男人|男子|少年|男孩|公子|先生|老头|老翁|王爷|父亲|丈夫|男，|男,|男。|男主|彼(?:は|が)|남성|남자|소년|아버지|남편|그는",
    re.IGNORECASE)


def norm_gender(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return _GENDER_WORDS.get(text)


def character_gender(entity: dict[str, Any] | None) -> dict[str, Any]:
    """{"gender": male|female|None, "basis": FIELD|APPEARANCE|AMBIGUOUS_APPEARANCE|NONE}."""
    entity = entity if isinstance(entity, dict) else {}
    for key in ("gender", "sex", "voice_gender"):
        g = norm_gender(entity.get(key))
        if g:
            return {"gender": g, "basis": f"FIELD:{key}"}
    for parent in ("immutable", "identity", "voice_requirement", "specification"):
        sub = entity.get(parent) if isinstance(entity.get(parent), dict) else {}
        for key in ("gender", "sex"):
            g = norm_gender(sub.get(key))
            if g:
                return {"gender": g, "basis": f"FIELD:{parent}.{key}"}
    text = " ".join(str(entity.get(k) or "") for k in ("appearance_en", "english_appearance", "appearance",
                                                         "appearance_ch1", "identity_card_appearance", "description"))
    female, male = bool(_APPEARANCE_FEMALE.search(text)), bool(_APPEARANCE_MALE.search(text))
    if female and not male:
        return {"gender": FEMALE, "basis": "APPEARANCE"}
    if male and not female:
        return {"gender": MALE, "basis": "APPEARANCE"}
    if female and male:
        # "a woman disguised as a young man": the first gendered word names the person
        f_at = _APPEARANCE_FEMALE.search(text).start()
        m_at = _APPEARANCE_MALE.search(text).start()
        return {"gender": FEMALE if f_at < m_at else MALE, "basis": "AMBIGUOUS_APPEARANCE_FIRST_WORD"}
    return {"gender": None, "basis": "NONE"}


def _tokens(value: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    return [t for t in re.split(r"[^A-Za-z]+", spaced.lower()) if t]


def name_gender(*names: Any) -> str | None:
    found = set()
    for name in names:
        toks = _tokens(str(name or ""))
        joined = "".join(toks)
        if any(t in _FEMALE_TOKENS for t in toks):
            found.add(FEMALE)
        if any(t in _MALE_TOKENS for t in toks) or "youngman" in joined:
            found.add(MALE)
    return found.pop() if len(found) == 1 else None


def f0_gender(f0: Any) -> str | None:
    """male under F0_MALE_MAX, female over F0_FEMALE_MIN, None (ambiguous / unknown) between."""
    try:
        value = float(f0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return MALE if value < F0_MALE_MAX else FEMALE if value > F0_FEMALE_MIN else None


def voice_gender(voice_id: Any, *, voice_name: Any = None, row: dict[str, Any] | None = None,
                 catalog: Iterable[dict[str, Any]] | None = None, f0: Any = None) -> dict[str, Any]:
    """{"gender", "basis", "f0_gender", "f0_hz"} of one cast voice.  Order: the row's own gender field, the provider
    catalog row, the curated system-voice table, gendered words in the id / name; F0 is reported alongside and used
    only when nothing else settles it (basis F0)."""
    vid = str(voice_id or "").strip()
    fg = f0_gender(f0)
    out: dict[str, Any] = {"voice_id": vid or None, "f0_hz": f0 if f0 is not None else None, "f0_gender": fg}
    g = norm_gender((row or {}).get("voice_gender") or (row or {}).get("gender"))  # legacy registry rows: "gender"
    if g:
        return {**out, "gender": g, "basis": "ROW_FIELD"}
    for c in catalog or []:
        if isinstance(c, dict) and str(c.get("voice_id") or "") == vid and norm_gender(c.get("gender")):
            return {**out, "gender": norm_gender(c.get("gender")), "basis": "PROVIDER_CATALOG"}
    if vid in SYSTEM_VOICE_GENDER:
        return {**out, "gender": SYSTEM_VOICE_GENDER[vid], "basis": "SYSTEM_VOICE_TABLE"}
    g = name_gender(vid, voice_name)
    if g:
        return {**out, "gender": g, "basis": "VOICE_NAME"}
    if fg:
        return {**out, "gender": fg, "basis": "F0"}
    return {**out, "gender": None, "basis": "NONE"}


MISMATCH, REVIEW, OK, UNKNOWN = "MISMATCH", "REVIEW", "OK", "UNKNOWN"


def casting_check(character: dict[str, Any], voice: dict[str, Any]) -> dict[str, Any]:
    """MISMATCH: the character's and the voice's gender are both known from non-F0 evidence and differ (auto-recast).
    REVIEW: the only evidence against the character is the reference F0, or the F0 contradicts a named voice gender.
    OK / UNKNOWN otherwise."""
    cg, vg = character.get("gender"), voice.get("gender")
    row = {"character_gender": cg, "character_basis": character.get("basis"), "voice_gender": vg,
           "voice_basis": voice.get("basis"), "voice_id": voice.get("voice_id"), "f0_hz": voice.get("f0_hz"),
           "f0_gender": voice.get("f0_gender")}
    if not cg or not vg:
        status = UNKNOWN
        if cg and voice.get("f0_hz") and not voice.get("f0_gender"):
            status = REVIEW  # ambiguous 160-210 Hz reference with an unnamed voice
    elif cg != vg:
        status = REVIEW if voice.get("basis") == "F0" else MISMATCH
    elif voice.get("f0_gender") and voice["f0_gender"] != cg:
        status = REVIEW  # the named gender matches but the reference pitch says otherwise
    else:
        status = OK
    return {**row, "status": status}


def age_class(value: Any) -> str:
    """youth / adult / senior from an apparent age range ("16-17", "25", "60-70") or a voice id / name."""
    text = str(value or "")
    nums = [int(n) for n in re.findall(r"\d{1,3}", text)]
    if nums:
        age = sum(nums[:2]) / len(nums[:2])
        return "youth" if age <= 25 else "senior" if age >= 55 else "adult"
    toks = "".join(_tokens(text))
    if any(t in toks for t in _SENIOR_TOKENS):
        return "senior"
    if any(t in toks for t in _YOUTH_TOKENS):
        return "youth"
    return "adult"


def _language_of(voice_id: str, row: dict[str, Any] | None = None) -> str:
    lang = str((row or {}).get("language") or "").lower()[:2]
    if lang:
        return lang
    head = voice_id.split("_", 1)[0].lower()
    return {"japanese": "ja", "korean": "ko", "english": "en", "chinese": "zh", "cantonese": "zh"}.get(head, "")


def candidate_pool(language: str, catalog: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Voices a recast may choose from for ``language``: the curated system voices of that language plus the
    provider catalog rows of that language with a gender."""
    lang = str(language or "").lower()[:2]
    pool: list[dict[str, Any]] = []
    for vid, g in SYSTEM_VOICE_GENDER.items():
        if _language_of(vid) == lang:
            pool.append({"voice_id": vid, "voice_name": vid.split("_", 1)[-1], "gender": g, "source": "SYSTEM_VOICE_TABLE"})
    seen = {row["voice_id"] for row in pool}
    for row in catalog or []:
        if not isinstance(row, dict) or not row.get("voice_id") or row["voice_id"] in seen:
            continue
        g = norm_gender(row.get("gender"))
        if g and _language_of(str(row["voice_id"]), row) == lang:
            pool.append({"voice_id": str(row["voice_id"]), "voice_name": str(row.get("voice_name") or row["voice_id"]),
                         "gender": g, "age": row.get("age"), "style": row.get("style"), "source": "PROVIDER_CATALOG"})
            seen.add(str(row["voice_id"]))
    return pool


def pick_recast(gender: str, language: str, *, age: Any = None, previous_voice_id: str = "",
                used: Iterable[str] = (), catalog: Iterable[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The replacement voice: right gender and language, not used by another character, the closest age class to
    the character (else to the voice being replaced), deterministic (pool order).  None when nothing fits."""
    taken = {str(v) for v in used if v}
    pool = [row for row in candidate_pool(language, catalog)
            if row["gender"] == gender and row["voice_id"] not in taken and row["voice_id"] != previous_voice_id]
    if not pool:
        return None
    want = age_class(age) if age not in (None, "", "UNSPECIFIED_IN_SOURCE") else age_class(previous_voice_id)

    def score(row: dict[str, Any]) -> int:
        have = age_class(row.get("age") or row["voice_id"])
        return 0 if have == want else 1 if "adult" in (have, want) else 2

    return sorted(pool, key=score)[0]


def gender_sentence(gender: str | None) -> str:
    """Plain words for a prompt: "a woman's voice" / "a man's voice" ('' when unknown)."""
    return "a woman's voice" if gender == FEMALE else "a man's voice" if gender == MALE else ""


# ------------------------------------------------------------------------------------------- episode plan
def entity_keys(character_id: str) -> list[str]:
    """Catalog / registry keys a character's voice row may sit under (bootstrap_voice_references.entity_id_of)."""
    cid = str(character_id or "").strip()
    slug = re.sub(r"^CHAR-", "", cid.upper()).replace("-", "_").lower()
    keys = [slug, cid, cid.lower()]
    if "_" in slug and re.match(r"e\d+_", slug):
        keys.append(slug.split("_", 1)[1])
    return list(dict.fromkeys(k for k in keys if k))


def plan_casting(character_entities: Iterable[dict[str, Any]], catalog_voices: dict[str, dict[str, Any]], *,
                 registry_rows: Iterable[dict[str, Any]] = (), voice_cast: dict[str, Any] | None = None,
                 language: str = "zh", provider_catalog: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One row per character with a catalog voice: the casting check and, for a MISMATCH, the recast voice.  Pure.

    ``catalog_voices`` is runtime/voice_catalog.json ``voices`` (key -> {voice_id, voice_name, ...}); registry rows
    (major_roles) give a locked row's gender / voice; ``voice_cast`` gives the measured reference F0 per CHAR id."""
    provider = [r for r in provider_catalog or [] if isinstance(r, dict)]
    reg_by_key: dict[str, dict[str, Any]] = {}
    for row in registry_rows or []:
        if isinstance(row, dict) and row.get("status") == "LOCKED_PRODUCTION_READY":
            for key in (row.get("entity_id"), row.get("character_id")):
                if key:
                    reg_by_key.setdefault(str(key), row)
    cast_chars = (voice_cast or {}).get("characters") or {}
    used = {str((row or {}).get("voice_id") or "") for row in (catalog_voices or {}).values() if isinstance(row, dict)}
    rows, recasts = [], []
    for entity in character_entities or []:
        if not isinstance(entity, dict) or not entity.get("character_id"):
            continue
        cid = str(entity["character_id"])
        keys = entity_keys(cid)
        key = next((k for k in keys if isinstance((catalog_voices or {}).get(k), dict)
                    and catalog_voices[k].get("voice_id")), None)
        if not key:
            continue
        cat = catalog_voices[key]
        reg = next((reg_by_key[k] for k in keys if k in reg_by_key), None)
        voice_id = str(cat.get("voice_id"))
        locked_voice = str((reg or {}).get("voice_id") or (reg or {}).get("generation_voice_id") or "")
        f0 = (cast_chars.get(cid) or {}).get("reference_f0_hz")
        ch = character_gender(entity)
        reg_for_voice = reg if (reg and (not locked_voice or locked_voice == voice_id)) else None
        vg = voice_gender(voice_id, voice_name=cat.get("voice_name"), row=reg_for_voice, catalog=provider,
                          f0=f0 if (not locked_voice or locked_voice == voice_id) else None)
        if not vg.get("gender") and norm_gender(cat.get("voice_gender")):
            vg = {**vg, "gender": norm_gender(cat.get("voice_gender")), "basis": "CATALOG_DECLARED"}
        check = casting_check(ch, vg)
        row = {"character_id": cid, "catalog_key": key, "name": entity.get("canonical_name"),
               "locked": bool(reg), "locked_voice_id": locked_voice or None, **check}
        if check["status"] == MISMATCH:
            pick = pick_recast(ch["gender"], language, age=entity.get("apparent_age_range"),
                               previous_voice_id=voice_id, used=used, catalog=provider)
            if pick:
                used.add(pick["voice_id"])
                row["recast"] = {"from_voice_id": voice_id, "to_voice_id": pick["voice_id"],
                                 "to_voice_name": pick["voice_name"], "to_gender": pick["gender"],
                                 "source": pick["source"]}
                recasts.append(row)
            else:
                row["recast"] = {"status": "NO_CANDIDATE", "from_voice_id": voice_id}
        rows.append(row)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (MISMATCH, REVIEW, OK, UNKNOWN)}
    return {"schema": SCHEMA, "language": language, "counts": counts, "rows": rows,
            "recasts": [r["recast"] | {"character_id": r["character_id"], "catalog_key": r["catalog_key"]}
                        for r in recasts]}
