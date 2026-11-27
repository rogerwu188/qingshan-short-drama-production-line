#!/usr/bin/env python3
"""BILI_V1 adaptation and episode allocation checks (CHANGE_SPEC WP1, owner 2026-11-23, Bilibili benchmark ep2/ep3).

Runs inside ``script_pacing_check.evaluate`` only when the series' craft profile is ``BILI_V1``
(``craft_profile.py``); a LEGACY series never reaches this module, so its decisions stay byte-identical.

An episode is allocated by plot events (1 main + <= 1 secondary), not by chapters; rhythm comes from turns inside
the scenes.  Source detail is kept, report-style lines are capped, slogans need a source anchor and a reveal must
name what the source names.

Taste codes (the bounded REVISE loop of script_pacing_check, admitted after MAX_REVISIONS):

  ADAPTATION_TOO_DENSE:<n>>2          more than 2 plot events, or more than 1 MAIN / 1 SECONDARY
  SOURCE_DETAIL_MISSING:<scene>       a scene declares fewer than 2 ``source_detail_ids`` (pacing.scene_plan row)
  SOURCE_DETAIL_NOT_IN_SOURCE:<id>    a declared source detail is not found in the adapted source text
  REPORT_LINES_OVER:<pct>             more than 20 % of the spoken lines are report-style (告知 / 交代)
  SLOGAN_LINE:<shot>                  an oath / threat template without a source anchor in its scene
                                      (advisory on the first evaluation, a taste code from the first revision on)

Integrity code (S1 integrity loop: back to the writer for bounded rounds, then admitted and recorded):

  REVEAL_NAME_NOT_IN_SOURCE:<shot>:<name>   a reveal line names someone / something the source does not
                                            (E25: 「你是……商余烬天神」 where the source says 容凌天神)

Script-doctor advisories (E27 2026-11-25, Foyege 《奥斯卡AI短剧节拍法》; warnings only, never a failure / gate):
the four questions a script doctor asks, measured where the contract can answer them --

  DOCTOR_FIRST_HIT_LATE:<s>s            the first emotional hit (an ATTACK / REVEAL / TURN / PAYOFF / PUNCHLINE line)
                                        lands after DOCTOR_FIRST_HIT_MAX_S
  DOCTOR_SCENE_EXPLAINS_ONLY:<scene>    half or more of a scene's lines only explain (report-style): nothing in the
                                        relationship changes
  DOCTOR_GOAL_UNCLEAR:<scene>           the opening scene names no immediate goal for the protagonist
  DOCTOR_TURN_ON_EMPTY_LINE:<shot>      the turn / reveal lands on a bare line (no authored action or evidence)

Character voice advisories (E27 2026-11-25, line owner "人物还是不够生动"; warnings only):

  DOCTOR_VOICE_UNDECLARED:<character>   a main speaker (>= DOCTOR_MAIN_LINES lines) has no ``voice`` / ``verbal_habit``
                                        on the series card
  DOCTOR_VOICES_ALIKE:<a>|<b>           two main speakers talk alike (line length, questions, exclamations, breaks
                                        and sentence-final particles all within the margins)
  DOCTOR_EXPOSITION_LINE:<shot>         a line only tells the audience a fact (report-style), in a scene that is not
                                        already flagged as explaining only
  DOCTOR_LINE_LANDS_NOWHERE:<shot>      a line nobody reacts to or answers: no listener reaction, no lead-in reaction
                                        on the next shot, the next line is not the addressee's, no beat tag
  DOCTOR_QUEST_LINE:<shot>              (E28 review 2026-11-26) a quest-giver line: it hands over a fact or a plan
                                        (what is needed, where it is, who has it, "I can go and find him") with no
                                        demand, refusal, bargain or threat on the other person -- 「想压住邪气，得用清风
                                        神草」「青玄那里就有，我可以去找他」

Pure functions; never raises (any error = no finding).  Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

SCHEMA = "nalu.bili_adaptation_check.v1"
TARGETS = {
    "plot_events_max": 2,
    "plot_events_main_max": 1,
    "plot_events_secondary_max": 1,
    "source_details_per_scene": 2,
    "source_detail_max_chars": 30,
    "report_lines_max_share": 0.20,
}
EVENT_ROLES = ("MAIN", "SECONDARY")
REVEAL_TURN_TYPES = frozenset({"REVEAL", "IDENTITY_REVEAL", "SECRET_REVEALED"})
TAG_REPORT = re.compile(r"[（(\[【]\s*(?:交代|report)\s*[）)\]】]", re.IGNORECASE)
TAG_REVEAL = re.compile(r"[（(\[【]\s*(?:揭示|reveal)\s*[）)\]】]", re.IGNORECASE)
_TAGS = re.compile(r"[（(\[【]\s*(?:交代|揭示|report|reveal)\s*[）)\]】]", re.IGNORECASE)

# --------------------------------------------------------------------------- lexicons (configs/, with defaults)
_DEFAULT_REPORT = {
    "zh": {"report": ["已经", "正在", "据说", "传来", "压境", "来报", "听说", "消息", "已被", "已于", "已然", "如今",
                      "眼下", "此时", "目前", "大军", "天兵", "兵临", "失踪", "出事", "身亡", "驾崩", "下落"],
           "second_person": ["你", "您", "汝", "尔等"],
           "first_person": ["我", "咱", "俺", "本君", "本宫", "本座", "本王", "朕", "孤", "吾", "在下", "老子", "老夫"],
           "imperative": ["别", "不许", "不准", "快", "给我", "住手", "站住", "让开", "滚", "放下", "跟我", "随我",
                          "带上", "带我", "看好", "记住", "听着"]},
    "en": {"report": ["already", "has been", "have been", "is coming", "are coming", "reported", "news", "they say",
                      "word is", "the army", "is dead", "was killed", "disappeared"],
           "second_person": ["you", "your", "yours"],
           "imperative": ["stop", "don't", "get out", "listen", "look", "come", "go", "give me", "take", "stay"]},
    "ja": {"report": ["すでに", "もう", "らしい", "そうだ", "という", "知らせ", "報告", "迫って", "殺された", "亡くなった",
                      "行方不明", "大軍"],
           "second_person": ["あなた", "お前", "君", "貴様", "てめえ", "あんた"],
           "imperative": ["やめろ", "待て", "来い", "行け", "黙れ", "しろ", "なさい", "ください", "くれ"]},
    "ko": {"report": ["이미", "벌써", "한다더라", "라고 한다", "소식", "보고", "쳐들어", "죽었", "사라졌", "대군"],
           "second_person": ["너", "당신", "네가", "니가", "그대", "자네"],
           "imperative": ["멈춰", "가라", "와라", "해라", "하세요", "주세요", "그만", "닥쳐"]},
}
_DEFAULT_SLOGANS = {
    "zh": ["今天(?:不|就|便|谁)", "谁也(?:别|不)", "谁都(?:别|不)", "替我们", "让他们(?:看清|知道|明白|跪)", "踏平",
           "踏破", "一笔一笔", "跪着", "血债血偿", "绝不放过", "誓死", "必将", "不让任何人", "叫他们", "让天下人"],
    "en": [r"\bno one will\b", r"\bnever again\b", r"\bpay for this\b", r"\bwe will crush\b", r"\bon their knees\b",
           r"\bevery last one\b", r"\btoday we\b"],
    "ja": ["思い知らせ", "許さない", "絶対に", "必ず.*させる", "ひざまず"],
    "ko": ["절대 용서", "무릎 꿇", "본때", "오늘 반드시"],
}
REVEAL_TITLE = re.compile(r"(?:天神|战神|神君|帝君|天君|魔尊|仙尊|圣女|圣子|公主|太子|殿下|皇子|王爷|大人|将军|帝|皇|王|君|尊|神|仙)$")
#: 「你是……X！」 / 「原来是 X」 / 「竟然是 X」 -- an identity reveal spoken in the line (zh)
REVEAL_SPOKEN = re.compile(r"(?:(?:你|您|他|她)(?:就|竟|竟然|原来|果然|居然|才)?|原来|竟然|居然|果然)是[\s…．.。、，,]*"
                           r"([^\s，。！？!?…、,.]{2,12}?)[\s！!。…]*$")
_QUESTION_WORDS = ("谁", "什么", "哪", "怎么", "为何", "吗")
#: script doctor (advisory): the first emotional hit should land inside the opening beat
DOCTOR_FIRST_HIT_MAX_S = 8.0
DOCTOR_EXPLAIN_SHARE = 0.5
_HIT_ROLES = frozenset({"ATTACK", "REVEAL", "TURN", "PAYOFF", "PUNCHLINE"})
#: character voice (advisory): a main speaker has at least this many lines in the episode
DOCTOR_MAIN_LINES = 3
DOCTOR_VOICE_MARGINS = {"length": 2.0, "question": 0.2, "exclaim": 0.2, "break": 0.2}
_PARTICLES = "吧呢啊嘛呀哦哈啦咯哼喽罢"
DOCTOR_CAP = 4
#: a quest-giver line (zh): a need, a location of the item, a plan to fetch it (E28 review)
QUEST_PATTERNS_ZH = re.compile(r"得用|要用|需要用?|非得|只有[^，。！？]{0,10}才(?:能|行|可以)|[^，。！？]{1,8}那(?:里|儿)(?:就|才)?有|"
                               r"我(?:可以|能|这就|就)?去找|去找[^，。！？]{1,6}(?:要|拿|借|求)|可以用|办法是|法子是|据说|听说|传说")
#: ... unless it presses on the other person: a demand / refusal / bargain / threat / a dig
PRESSURE_ZH = re.compile(r"你(?:敢|得|必须|给我|别|不许|休想|凭什么)|给我|不许|休想|否则|不然|除非|条件|换|凭什么|别想|"
                         r"[！!]|不准|你要是|你若")


def _config(name: str) -> dict[str, Any]:
    for root in (_HERE.parents[3] / "configs", _HERE / "configs"):
        try:
            data = json.loads((root / name).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, IndexError):
            continue
    return {}


def report_lexicon(language: str) -> dict[str, list[str]]:
    data = (_config("REPORT_LINE_PATTERNS_V1.json").get("languages") or {}).get(language)
    return data if isinstance(data, dict) else _DEFAULT_REPORT.get(language) or _DEFAULT_REPORT["zh"]


def slogan_patterns(language: str) -> list[str]:
    data = (_config("SLOGAN_PATTERNS_V1.json").get("languages") or {}).get(language)
    return [str(p) for p in data] if isinstance(data, list) else list(_DEFAULT_SLOGANS.get(language) or [])


# --------------------------------------------------------------------------- text helpers
def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def norm(text: Any) -> str:
    """Whitespace and punctuation dropped, latin lower-cased: a quote matches the source across formatting."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def joined_source(texts: list[str] | None) -> str:
    return norm("\n".join(str(t or "") for t in texts or []))


def _common_run(a: str, b: str) -> int:
    """Length of the longest common substring of two normalised strings."""
    if not a or not b:
        return 0
    best, prev = 0, [0] * (len(b) + 1)
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, other in enumerate(b, 1):
            if ch == other:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _scene_rows(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    import script_pacing_check as _sp  # noqa: PLC0415 -- same directory; loaded by the caller already
    return {_clean(p.get("scene_id")): p for p in _sp.pacing_block(contract).get("scene_plan") or []
            if isinstance(p, dict) and _clean(p.get("scene_id"))}


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    out = []
    for item in value or []:
        text = _clean(item.get("text") or item.get("quote") or item.get("id")) if isinstance(item, dict) else _clean(item)
        if text:
            out.append(text)
    return out


def source_detail_ids(row: dict[str, Any]) -> list[str]:
    return _str_list((row or {}).get("source_detail_ids"))


def source_lines(row: dict[str, Any]) -> list[str]:
    return _str_list((row or {}).get("source_lines"))


def spoken_lines(contract: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Every spoken line with its shot, scene, speaker, writer tags and the shot's beat role."""
    import script_pacing_check as _sp  # noqa: PLC0415
    out: list[dict[str, Any]] = []
    for shot in (contract or {}).get("shots") or []:
        if not isinstance(shot, dict):
            continue
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        raw = spec.get("dialogue") if spec.get("dialogue") not in (None, "", []) else shot.get("dialogue")
        kind = _clean(spec.get("line_kind") or shot.get("line_kind")).lower()
        for row in _sp._rows(raw):
            speaker, words = _sp.split_line(row, language)
            text = _TAGS.sub("", words).strip()
            if not norm(text):
                continue
            out.append({"shot_id": _clean(shot.get("shot_id")), "scene_id": _clean(shot.get("scene_id")) or "SCENE",
                        "speaker": speaker, "text": text,
                        "tag_report": bool(TAG_REPORT.search(words)) or kind == "report",
                        "tag_reveal": bool(TAG_REVEAL.search(words)) or kind == "reveal",
                        "beat_role": _clean(spec.get("beat_role")).upper()})
    return out


def _prop_names(contract: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    for row in (contract or {}).get("props") or []:
        if isinstance(row, dict):
            names |= {_clean(row.get(k)) for k in ("name", "label", "canonical_name", "name_zh")}
        elif isinstance(row, str):
            names.add(_clean(row))
    for shot in (contract or {}).get("shots") or []:
        spec = shot.get("prompt_spec") if isinstance(shot, dict) and isinstance(shot.get("prompt_spec"), dict) else {}
        for row in spec.get("props") or []:
            if isinstance(row, dict):
                names |= {_clean(row.get(k)) for k in ("name", "label", "prop", "name_zh")}
            elif isinstance(row, str):
                names.add(_clean(row))
    return sorted((n for n in names if len(n) >= 2), key=len, reverse=True)


# --------------------------------------------------------------------------- 1. event cap
def event_allocation(contract: dict[str, Any]) -> dict[str, Any]:
    plan = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
    events = [e for e in plan.get("plot_events") or [] if (isinstance(e, dict) and _clean(
        e.get("event") or e.get("summary"))) or (isinstance(e, str) and e.strip())]
    roles = [_clean(e.get("role")).upper() if isinstance(e, dict) else "" for e in events]
    return {"plot_event_count": len(events), "main": roles.count("MAIN"), "secondary": roles.count("SECONDARY"),
            "role_missing": sum(1 for r in roles if r not in EVENT_ROLES),
            "plot_events_max": TARGETS["plot_events_max"]}


# --------------------------------------------------------------------------- 5. source detail retention
def source_details(contract: dict[str, Any], scene_ids: list[str], source: str) -> dict[str, Any]:
    rows = _scene_rows(contract)
    need = int(TARGETS["source_details_per_scene"])
    missing, not_found, too_long, per_scene = [], [], [], {}
    for sid in scene_ids:
        ids = source_detail_ids(rows.get(sid) or {})
        per_scene[sid] = len(ids)
        if len(ids) < need:
            missing.append(sid)
        for quote in ids:
            if len(norm(quote)) > TARGETS["source_detail_max_chars"]:
                too_long.append(quote[:30])
            if source and norm(quote) and norm(quote) not in source:
                not_found.append(quote[:30])
    return {"per_scene": per_scene, "missing": missing, "not_in_source": list(dict.fromkeys(not_found)),
            "too_long": too_long, "required_per_scene": need, "source_available": bool(source)}


# --------------------------------------------------------------------------- 7. report-style lines
def _has_any(text: str, words: list[str], language: str) -> bool:
    if language == "en":
        low = text.lower()
        return any(re.search(rf"\b{re.escape(w.lower())}\b", low) for w in words if w)
    return any(w and w in text for w in words)


def _question(text: str, language: str) -> bool:
    t = text.rstrip(" 　")
    if t.endswith(("？", "?")):
        return True
    return {"zh": t.rstrip("。！!…").endswith(("吗", "呢", "么")), "ja": t.rstrip("。！!…").endswith(("か", "の")),
            "ko": t.rstrip(".!…").endswith(("까", "니", "냐", "나"))}.get(language, False)


def classify_line(line: dict[str, Any], language: str, lexicon: dict[str, list[str]], props: list[str]) -> str:
    """REPORT | SPEECH.  The writer's own tag wins; otherwise a line is REPORT when it has no address, imperative,
    question or named prop AND matches a report pattern."""
    if line.get("tag_report"):
        return "REPORT"
    text = line["text"]
    clauses = [c.strip("…．. ") for c in re.split(r"[，,；;：:、—]", text) if c.strip("…．. ")]
    engaged = (_has_any(text, lexicon.get("second_person") or [], language) or _question(text, language)
               or any(c.startswith(w) for c in clauses for w in lexicon.get("imperative") or [] if w)
               or (language != "zh" and _has_any(text, lexicon.get("imperative") or [], language))
               or any(p in text for p in props))
    if engaged:
        return "SPEECH"
    if _has_any(text, lexicon.get("report") or [], language):
        return "REPORT"
    # an impersonal statement: nobody in the scene is addressed or speaks of himself -- news told to the audience
    persons = lexicon.get("first_person") or []
    if persons and len(norm(text)) >= 6 and not _has_any(text, persons, language):
        return "REPORT"
    return "SPEECH"


def report_lines(contract: dict[str, Any], lines: list[dict[str, Any]], language: str) -> dict[str, Any]:
    lexicon = report_lexicon(language)
    props = _prop_names(contract)
    flagged = [ln for ln in lines if classify_line(ln, language, lexicon, props) == "REPORT"]
    share = round(len(flagged) / len(lines), 3) if lines else 0.0
    return {"lines": len(lines), "report_lines": len(flagged), "share": share,
            "max_share": TARGETS["report_lines_max_share"],
            "examples": [f"{ln['shot_id']}" for ln in flagged[:8]]}


# --------------------------------------------------------------------------- 8. anti-slogan
def slogan_lines(contract: dict[str, Any], lines: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    rows = _scene_rows(contract)
    patterns = []
    for p in slogan_patterns(language):
        try:
            patterns.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    out = []
    for ln in lines:
        hit = next((m for p in patterns for m in [p.search(ln["text"])] if m), None)
        if not hit:
            continue
        row = rows.get(ln["scene_id"]) or {}
        anchors = [norm(a) for a in source_detail_ids(row) + source_lines(row)]
        rest = norm(ln["text"].replace(hit.group(0), " "))
        if any(_common_run(rest, a) >= 2 for a in anchors if a):
            continue
        out.append({"shot_id": ln["shot_id"], "scene_id": ln["scene_id"], "pattern": hit.group(0)})
    return out


# --------------------------------------------------------------------------- 9. reveal fidelity
def _character_names(contract: dict[str, Any]) -> list[str]:
    import script_pacing_check as _sp  # noqa: PLC0415
    return _sp._names(contract)


def reveal_shots(contract: dict[str, Any]) -> set[str]:
    """Shots the writer marks as a reveal: a beat_sheet row of type REVEAL / IDENTITY_REVEAL / SECRET_REVEALED."""
    import script_pacing_check as _sp  # noqa: PLC0415
    out = set()
    for row in _sp.pacing_block(contract).get("beat_sheet") or []:
        if isinstance(row, dict) and _clean(row.get("type")).upper() in REVEAL_TURN_TYPES and _clean(row.get("shot_id")):
            out.add(_clean(row.get("shot_id")))
    return out


def reveal_failures(contract: dict[str, Any], lines: list[dict[str, Any]], source: str,
                    language: str) -> tuple[list[str], list[dict[str, Any]]]:
    """(codes, checked rows).  A reveal line = tagged (``beat_role: REVEAL``, ``[揭示]``, a REVEAL beat) or, in zh,
    a spoken identity reveal 「你是……X」 whose X carries a character name or a title.  Every name the reveal speaks
    must occur, as spoken, in the adapted source text.  No source text = nothing checked."""
    if not source:
        return [], []
    names = _character_names(contract)
    tagged_shots = reveal_shots(contract)
    codes, checked = [], []
    for ln in lines:
        tagged = ln["tag_reveal"] or ln["beat_role"] == "REVEAL" or ln["shot_id"] in tagged_shots
        phrases: list[str] = []
        if language == "zh" and not _question(ln["text"], language):
            m = REVEAL_SPOKEN.search(ln["text"])
            if m and not any(q in m.group(1) for q in _QUESTION_WORDS):
                phrase = m.group(1)
                if tagged or REVEAL_TITLE.search(phrase) or any(n in phrase for n in names):
                    phrases.append(phrase)
        if tagged:
            phrases += [n for n in names if n in ln["text"] and not any(n in p for p in phrases)]
        if not phrases:
            continue
        missing = [p for p in phrases if norm(p) and norm(p) not in source]
        checked.append({"shot_id": ln["shot_id"], "phrases": phrases, "missing": missing, "tagged": tagged})
        codes += [f"REVEAL_NAME_NOT_IN_SOURCE:{ln['shot_id']}:{p}" for p in missing]
    return list(dict.fromkeys(codes)), checked


# --------------------------------------------------------------------------- source texts (no-copy gate / checks)
def _chapter_no(value: Any) -> int | None:
    m = re.search(r"(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def declared_chapters(contract: dict[str, Any]) -> list[int]:
    """``adaptation_plan.source_chapters`` is authoritative (WP1 item 10); ``source_binding.source_chapters`` is the
    fallback when the plan declares none."""
    plan = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
    binding = contract.get("source_binding") if isinstance(contract.get("source_binding"), dict) else {}
    for raw in (plan.get("source_chapters"), binding.get("source_chapters")):
        chapters = sorted({c for c in (_chapter_no(x) for x in raw or []) if c is not None and c >= 0})
        if chapters:
            return chapters
    return []


def source_texts(contract: dict[str, Any], runtime_root: Path | None) -> list[str]:
    """Every declared chapter of the episode, concatenated by the caller: the contract's ``source_text`` file, the
    ``source_binding`` files and ``<runtime>/sources/<work>/<canonical_reading_script>/chNNNN.md`` for each declared
    chapter (any work whose SOURCE_INDEX.json the runtime holds -- not only 夜无疆).  [] when none.  Never raises."""
    out: list[str] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            key = str(path.resolve())
            if key in seen or not path.is_file():
                return
            seen.add(key)
            out.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return

    try:
        contract = contract if isinstance(contract, dict) else {}
        if _clean(contract.get("source_text")):
            add(Path(_clean(contract.get("source_text"))))
        binding = contract.get("source_binding") if isinstance(contract.get("source_binding"), dict) else {}
        for f in [binding.get("source_file")] + [r.get("path") if isinstance(r, dict) else r
                                                 for r in binding.get("source_files") or []]:
            if _clean(f):
                add(Path(_clean(f)))
        chapters = declared_chapters(contract)
        if chapters and runtime_root is not None:
            work = _clean(binding.get("work"))
            indexes = sorted(Path(runtime_root, "sources").glob("*/SOURCE_INDEX.json"))
            indexes.sort(key=lambda p: p.parent.name != work)        # the bound work first
            for index in indexes:
                try:
                    meta = json.loads(index.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    meta = {}
                folder = index.parent / _clean((meta or {}).get("canonical_reading_script") or "as_delivered")
                files = [folder / f"ch{c:04d}.md" for c in chapters]
                if any(f.is_file() for f in files):
                    for f in files:
                        add(f)
                    break
    except Exception:  # noqa: BLE001
        return out
    return out


# --------------------------------------------------------------------------- the check
def check(contract: dict[str, Any], language: str, scene_ids: list[str], source_texts_: list[str] | None, *,
          revision_round: int = 0) -> dict[str, Any]:
    """{failures (taste), warnings, integrity, metrics}.  ``revision_round``: failing scripts the writer already
    revised (0 = first evaluation; slogans are advisory then).  Never raises."""
    try:
        contract = contract if isinstance(contract, dict) else {}
        source = joined_source(source_texts_)
        failures: list[str] = []
        warnings: list[str] = []
        ev = event_allocation(contract)
        if (ev["plot_event_count"] > TARGETS["plot_events_max"] or ev["main"] > TARGETS["plot_events_main_max"]
                or ev["secondary"] > TARGETS["plot_events_secondary_max"]):
            failures.append(f"ADAPTATION_TOO_DENSE:{ev['plot_event_count']}>{TARGETS['plot_events_max']}"
                            f"(main={ev['main']},secondary={ev['secondary']})")
        if ev["role_missing"]:
            warnings.append(f"PLOT_EVENT_ROLE_MISSING:{ev['role_missing']}")
        details = source_details(contract, scene_ids, source)
        failures += [f"SOURCE_DETAIL_MISSING:{sid}" for sid in details["missing"][:8]]
        failures += [f"SOURCE_DETAIL_NOT_IN_SOURCE:{q}" for q in details["not_in_source"][:8]]
        warnings += [f"SOURCE_DETAIL_TOO_LONG:{q}" for q in details["too_long"][:4]]
        if not source:
            warnings.append("SOURCE_TEXT_UNAVAILABLE")
        lines = spoken_lines(contract, language)
        rep = report_lines(contract, lines, language)
        if rep["lines"] and rep["share"] > TARGETS["report_lines_max_share"]:
            failures.append(f"REPORT_LINES_OVER:{round(rep['share'] * 100)}%")
        slogans = slogan_lines(contract, lines, language)
        codes = [f"SLOGAN_LINE:{s['shot_id']}" for s in slogans[:8]]
        (failures if revision_round >= 1 else warnings).extend(codes)
        integrity, reveals = reveal_failures(contract, lines, source, language)
        doctor = script_doctor(contract, lines, language)
        warnings += doctor["warnings"]
        return {"schema": SCHEMA, "failures": failures, "warnings": warnings, "integrity": integrity[:8],
                "metrics": {"events": ev, "source_details": details, "report_lines": rep, "script_doctor": doctor,
                            "slogans": slogans[:8], "reveals": reveals[:8], "revision_round": revision_round,
                            "source_chars": len(source)}}
    except Exception as exc:  # noqa: BLE001 -- a check must never break S1
        return {"schema": SCHEMA, "failures": [], "warnings": [f"BILI_CHECK_ERROR:{type(exc).__name__}"],
                "integrity": [], "metrics": {}}


def script_doctor(contract: dict[str, Any], lines: list[dict[str, Any]] | None = None,
                  language: str = "zh") -> dict[str, Any]:
    """The four script-doctor questions as advisories ({warnings, answers}); never a failure.  Never raises."""
    try:
        contract = contract if isinstance(contract, dict) else {}
        shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
        lines = spoken_lines(contract, language) if lines is None else lines
        warnings: list[str] = []
        answers: dict[str, Any] = {}
        # 1. is the first emotional hit too late?
        clock, first_hit = 0.0, None
        for shot in shots:
            spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
            if _clean(spec.get("beat_role")).upper() in _HIT_ROLES:
                first_hit = clock
                break
            try:
                clock += float(shot.get("target_seconds") or 0)
            except (TypeError, ValueError):
                pass
        answers["first_hit_seconds"] = first_hit
        if shots and (first_hit is None or first_hit > DOCTOR_FIRST_HIT_MAX_S):
            warnings.append(f"DOCTOR_FIRST_HIT_LATE:{'none' if first_hit is None else round(first_hit, 1)}s")
        # 2. which scene only explains setting without changing a relationship?
        lexicon = report_lexicon(language)
        props = _prop_names(contract)
        by_scene: dict[str, list[str]] = {}
        for line in lines:
            by_scene.setdefault(line["scene_id"], []).append(classify_line(line, language, lexicon, props))
        explains = [sid for sid, kinds in by_scene.items()
                    if len(kinds) >= 2 and kinds.count("REPORT") / len(kinds) >= DOCTOR_EXPLAIN_SHARE]
        answers["explaining_scenes"] = explains
        warnings += [f"DOCTOR_SCENE_EXPLAINS_ONLY:{sid}" for sid in explains[:4]]
        # 3. is the protagonist's immediate goal clear?
        rows = list(_scene_rows(contract).values())
        protagonists = {_clean(p) for p in contract.get("protagonist_ids") or []}
        if rows:
            first = rows[0]
            owners = {_clean(first.get("objective_owner"))} | {_clean(g.get("who")) for g in first.get("goals") or []
                                                                if isinstance(g, dict)}
            clear = bool(_clean(first.get("objective"))) and (not protagonists or bool(protagonists & owners))
            answers["opening_goal"] = _clean(first.get("objective"))
            if not clear:
                warnings.append(f"DOCTOR_GOAL_UNCLEAR:{_clean(first.get('scene_id'))}")
        # 4. does the twist land on an action or on an empty line?
        turn_ids = {_clean(r.get("turn_shot_id")) for r in rows if _clean(r.get("turn_shot_id"))}
        empty = []
        for shot in shots:
            spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
            role = _clean(spec.get("beat_role")).upper()
            if _clean(shot.get("shot_id")) not in turn_ids and role not in {"TURN", "REVEAL"}:
                continue
            action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
            sources = action.get("field_sources") if isinstance(action.get("field_sources"), dict) else {}
            authored = _clean(sources.get("primary_action") or action.get("source")).lower() in {"screenplay",
                                                                                                "authored"}
            if not authored and not spec.get("props"):
                empty.append(_clean(shot.get("shot_id")))
        answers["turns_on_empty_lines"] = empty
        warnings += [f"DOCTOR_TURN_ON_EMPTY_LINE:{sid}" for sid in empty[:4]]
        # 5-8. character voice and lines that change something (E27)
        voice = voice_doctor(contract, lines, language, lexicon, props, set(explains))
        warnings += voice["warnings"]
        answers["voice"] = voice["answers"]
        return {"warnings": warnings, "answers": answers}
    except Exception as exc:  # noqa: BLE001 -- advisory only
        return {"warnings": [f"DOCTOR_CHECK_ERROR:{type(exc).__name__}"], "answers": {}}


def _voice_profile(texts: list[str]) -> dict[str, Any]:
    n = len(texts) or 1
    ends = [t.rstrip("。！？!?…—．. ") for t in texts]
    return {"length": sum(len(norm(t)) for t in texts) / n,
            "question": sum(1 for t in texts if re.search(r"[？?]", t)) / n,
            "exclaim": sum(1 for t in texts if re.search(r"[！!]", t)) / n,
            "break": sum(1 for t in texts if re.search(r"[…—]", t)) / n,
            "particles": sorted({e[-1] for e in ends if e and e[-1] in _PARTICLES})}


def _speaker_ids(contract: dict[str, Any]) -> dict[str, str]:
    """dialogue label -> character id (canonical name and aliases)."""
    out: dict[str, str] = {}
    for row in contract.get("character_entities") or []:
        if isinstance(row, dict) and _clean(row.get("character_id")):
            for name in [row.get("canonical_name"), row.get("name"), *(row.get("aliases") or [])]:
                if _clean(name):
                    out.setdefault(_clean(name), _clean(row["character_id"]))
    return out


def voice_doctor(contract: dict[str, Any], lines: list[dict[str, Any]], language: str = "zh",
                 lexicon: dict[str, list[str]] | None = None, props: list[str] | None = None,
                 explaining_scenes: set[str] | None = None) -> dict[str, Any]:
    """Character voice + lines that land (E27): {warnings, answers}.  Advisory only; never raises."""
    try:
        lexicon = lexicon if lexicon is not None else report_lexicon(language)
        props = props if props is not None else _prop_names(contract)
        warnings: list[str] = []
        by_speaker: dict[str, list[str]] = {}
        for line in lines:
            if line.get("speaker"):
                by_speaker.setdefault(line["speaker"], []).append(line["text"])
        main = [s for s, texts in by_speaker.items() if len(texts) >= DOCTOR_MAIN_LINES]
        ids = _speaker_ids(contract)
        card = contract.get("series_card") if isinstance(contract.get("series_card"), dict) else {}
        voiced = {_clean(r.get("character_id")) or _clean(r.get("name")): r for r in card.get("characters") or []
                  if isinstance(r, dict)}
        if voiced:
            for speaker in main:
                row = voiced.get(ids.get(speaker, "")) or voiced.get(speaker) or next(
                    (r for r in voiced.values() if _clean(r.get("name")) == speaker), None)
                if row is None or not (_clean(row.get("voice")) and _clean(row.get("verbal_habit"))):
                    warnings.append(f"DOCTOR_VOICE_UNDECLARED:{ids.get(speaker) or speaker}")
        profiles = {s: _voice_profile(by_speaker[s]) for s in main}
        alike = []
        for i, a in enumerate(main):
            for b in main[i + 1:]:
                pa, pb = profiles[a], profiles[b]
                if all(abs(pa[k] - pb[k]) <= m for k, m in DOCTOR_VOICE_MARGINS.items()) and \
                        pa["particles"] == pb["particles"]:
                    alike.append(f"{a}|{b}")
        warnings += [f"DOCTOR_VOICES_ALIKE:{pair}" for pair in alike[:DOCTOR_CAP]]
        explaining_scenes = explaining_scenes or set()
        exposition = [line["shot_id"] for line in lines if line["scene_id"] not in explaining_scenes
                      and classify_line(line, language, lexicon, props) == "REPORT"]
        warnings += [f"DOCTOR_EXPOSITION_LINE:{sid}" for sid in list(dict.fromkeys(exposition))[:DOCTOR_CAP]]
        quests = [line["shot_id"] for line in lines if language == "zh"
                  and QUEST_PATTERNS_ZH.search(line["text"]) and not PRESSURE_ZH.search(line["text"])]
        warnings += [f"DOCTOR_QUEST_LINE:{sid}" for sid in list(dict.fromkeys(quests))[:DOCTOR_CAP]]
        # a line that lands nowhere: nobody reacts to it or answers it
        shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
        pos = {_clean(s.get("shot_id")): i for i, s in enumerate(shots)}
        spoken_by_shot = {line["shot_id"]: line for line in lines}
        nowhere = []
        for line in lines:
            i = pos.get(line["shot_id"])
            if i is None:
                continue
            spec = shots[i].get("prompt_spec") if isinstance(shots[i].get("prompt_spec"), dict) else {}
            action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
            role = spec.get("role_semantic_disambiguation") if isinstance(
                spec.get("role_semantic_disambiguation"), dict) else {}
            if action.get("listener_reaction") or action.get("listener_reaction_en") or \
                    _clean(spec.get("beat_role")).upper() not in ("", "LINE"):
                continue
            nxt = shots[i + 1] if i + 1 < len(shots) else None
            if nxt is None or _clean(nxt.get("scene_id")) != _clean(shots[i].get("scene_id")):
                continue  # the scene's last line: the cut answers it
            nspec = nxt.get("prompt_spec") if isinstance(nxt.get("prompt_spec"), dict) else {}
            naction = nspec.get("action") if isinstance(nspec.get("action"), dict) else {}
            if naction.get("lead_in_reaction") or naction.get("lead_in_reaction_en"):
                continue
            answer = spoken_by_shot.get(_clean(nxt.get("shot_id")))
            listener = _clean(role.get("dialogue_listener_id"))
            if answer and answer.get("speaker") and answer["speaker"] != line.get("speaker") and (
                    not listener or ids.get(answer["speaker"], answer["speaker"]) == listener):
                continue
            if not answer and naction.get("primary_action"):
                continue  # a silent beat answers it with an action
            nowhere.append(line["shot_id"])
        warnings += [f"DOCTOR_LINE_LANDS_NOWHERE:{sid}" for sid in list(dict.fromkeys(nowhere))[:DOCTOR_CAP]]
        return {"warnings": warnings, "answers": {"main_speakers": main, "profiles": profiles, "alike": alike,
                                                 "exposition_lines": exposition, "quest_lines": quests,
                                                 "lands_nowhere": nowhere}}
    except Exception as exc:  # noqa: BLE001 -- advisory only
        return {"warnings": [f"DOCTOR_VOICE_CHECK_ERROR:{type(exc).__name__}"], "answers": {}}


#: failure code -> the fix the writer can act on (no story text)
FIXES = {
    "TOO_FEW_TURNS": "deepen the existing scenes: add turns inside a scene (a tactic change, a reveal, a reversal), "
                     "not new plot events",
    "ADAPTATION_TOO_DENSE": "one main plot event and at most one secondary per episode (adaptation_plan.plot_events "
                            "role MAIN / SECONDARY); move the other events to the next episodes -- take as many "
                            "chapters as those events need (often 1), an event-dense chapter may be split across 2 "
                            "episodes",
    "SOURCE_DETAIL_MISSING": "give each scene >= 2 source_detail_ids in pacing.scene_plan: short quotes (<= 30 chars) "
                             "of visible source details -- a posture, a prop, a gesture, an interrupted line -- and "
                             "stage them in the scene",
    "SOURCE_DETAIL_NOT_IN_SOURCE": "each source_detail_id must be quoted from the adapted chapter text as written "
                                   "(copy the short phrase; whitespace and punctuation do not matter)",
    "REPORT_LINES_OVER": "at most 20 % report lines: turn news / exposition into a line aimed at someone (a demand, "
                         "a question, a threat with a prop), or show it; tag a deliberate one (交代)",
    "SLOGAN_LINE": "no oath / threat templates the source does not carry: sharpen an attitude the source already "
                   "has (anchor it in the scene's source_detail_ids / source_lines) or cut the line",
    "REVEAL_NAME_NOT_IN_SOURCE": "a reveal must say what the source says: use the name / title the source chapter "
                                 "speaks at that reveal (integrity)",
    # script-doctor advisories (warnings, never blocking)
    "DOCTOR_FIRST_HIT_LATE": "open on the abnormal event: the first attack / reveal / turn inside the first ~8 s; "
                             "the opening beat runs abnormal event -> immediate goal -> deadly rule -> time-limited "
                             "obstacle -> identity / information reversal -> an unanswered question within ~35 s",
    "DOCTOR_SCENE_EXPLAINS_ONLY": "a world fact must change someone's situation right now: turn the explanation into "
                                  "a demand, a refusal or a choice between the people in the scene, or cut it",
    "DOCTOR_GOAL_UNCLEAR": "name the protagonist's immediate goal in the opening scene card (goal[protagonist]=...) "
                           "and make the first lines push toward it",
    "DOCTOR_TURN_ON_EMPTY_LINE": "land the twist on visible evidence or an action (a prop handed over, a mark shown, "
                                 "a door opened), not on a line alone",
    "DOCTOR_VOICE_UNDECLARED": "give each main character a voice on the series card: voice (diction, rhythm) and "
                               "verbal_habit (one habit: a clipped command, a rhetorical question, a pet word, a "
                               "trailing-off) and write every line of theirs in it",
    "DOCTOR_VOICES_ALIKE": "these two talk alike: change one's rhythm and diction (short commands vs. long winding "
                           "questions, plain words vs. formal ones, a particle or habit only one of them uses)",
    "DOCTOR_EXPOSITION_LINE": "no line tells the audience a fact: make it a demand, a threat, a refusal or a "
                              "dig at the other person, with the fact as its subtext, or show the fact as an object",
    "DOCTOR_LINE_LANDS_NOWHERE": "every line must change the other person's situation: give the addressee a visible "
                                 "reaction or an answer, or cut the line",
    "DOCTOR_QUEST_LINE": "no quest-giver lines (what is needed, where it is, who has it, 'I can go and find him'): turn "
                         "the line into a demand, a refusal, a bargain or a threat that changes the other person's "
                         "situation now, with the information as its subtext -- e.g. not 'X has it, I can go to him' "
                         "but a line that refuses the other's help or names the price she will pay",
}


__all__ = ["SCHEMA", "TARGETS", "FIXES", "check", "script_doctor", "voice_doctor", "source_texts", "declared_chapters", "event_allocation",
           "source_details", "report_lines", "classify_line", "slogan_lines", "reveal_failures", "spoken_lines",
           "norm", "joined_source"]
