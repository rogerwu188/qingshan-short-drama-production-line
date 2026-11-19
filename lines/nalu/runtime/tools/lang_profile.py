#!/usr/bin/env python3
"""One profile per spoken-dialogue language (zh / en / ja / ko).

Before 2026-11-18 every language-aware site was an ``== "en"`` / else-Chinese binary and
``nalu_pipeline.resolve_dialogue_language`` silently coerced any other language to zh, so a Japanese
or Korean series counted 0 spoken units (Korean) or only its kanji (Japanese), normalised ASR text
to Han only (Korean expected text became "" and failed everywhere), and drew 第N集 on its title card.

This module is the single source for what a language needs:
  * the speech-character regex and the counting unit (``char`` = one character / syllable,
    ``word`` = one Latin word),
  * a speech rate (units per second) for timing estimates and reference reads,
  * the speaker separator(s) of ``speaker：line``, the joiner between fragments,
  * an ASR normaliser, the Whisper language code and the preferred Whisper model,
  * the H3 ``<d>[Tag]`` dialogue tag, the episode label, the end-card text,
    the voice-locale text and calibration sentences for reference reads.

Existing zh / en call sites keep their own historical regexes (they differ slightly per site and the
zh / en output must stay byte-identical); ja / ko and every new site route through here.
Pure data and functions: no I/O at import, no third-party imports.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

#: every dialogue language the production path supports ("zh" is the historical default)
LANGUAGES = ("zh", "en", "ja", "ko")
DEFAULT_LANGUAGE = "zh"

# --------------------------------------------------------------------------- character classes
HAN = "㐀-䶿一-鿿豈-﫿"
#: hiragana (no ゛゜ combining marks), katakana incl. ー (spoken: lengthens the vowel), 々 iteration mark,
#: half-width katakana; ・ (U+30FB, the name middle dot) is punctuation and excluded
KANA = "ぁ-ゖゝ-ゟァ-ヺー-ヿㇰ-ㇿｦ-ﾝ"
HANGUL = "가-힣ᄀ-ᇿㄱ-ㆎ"

#: any CJK speech character (Han, kana, Hangul): the "is this East-Asian script" test that the zh-only
#: ``[一-鿿]`` checks used to be
CJK_SPEECH_RE = re.compile(f"[{HAN}{KANA}々{HANGUL}]")
HAN_RE = re.compile(f"[{HAN}]")
KANA_RE = re.compile(f"[{KANA}]")
HANGUL_RE = re.compile(f"[{HANGUL}]")
EN_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*")


def _katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


# --------------------------------------------------------------------------- normalisers (ASR comparison)
def _norm_zh(text: str) -> str:
    return "".join(re.findall(r"[一-鿿]", str(text or "")))


def _norm_en(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)*", str(text or "").lower().replace("’", "'")))


def _norm_ja(text: str) -> str:
    """NFKC (half-width kana / full-width digits), katakana -> hiragana (Whisper writes the same word in
    either script), keep kana + kanji + 々 + ASCII alnum; punctuation and spaces dropped."""
    value = _katakana_to_hiragana(unicodedata.normalize("NFKC", str(text or "")).lower())
    return "".join(re.findall(f"[{HAN}ぁ-ゖゝ-ゟー々a-z0-9]", value))


def _norm_ko(text: str) -> str:
    """NFKC, keep Hangul syllables + ASCII alnum; spaces dropped (Whisper and writers space Korean
    differently, so word spacing must not cost recall)."""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(re.findall(r"[가-힣a-z0-9]", value))


# --------------------------------------------------------------------------- profile
@dataclass(frozen=True)
class LangProfile:
    code: str
    locale: str
    name: str                       # English language name
    unit: str                       # "char" (one character / syllable) or "word"
    speech_re: re.Pattern[str]      # one match = one counted speech unit
    rate: float                     # speech units per second (natural dialogue / reference read)
    separators: tuple[str, ...]     # speaker／line separators, tried in order
    joiner: str                     # between line fragments / ASR segments
    whisper: str                    # faster-whisper language code
    whisper_model: str              # preferred faster-whisper model (falls back to "small" when absent)
    h3_tag: str                     # <d>[Tag] words</d>
    endcard: str
    voice_locale_text: str
    calibration: tuple[str, ...]
    normalise: Callable[[str], str] = field(repr=False, compare=False, default=_norm_zh)
    reference_floor: int = 12       # reference-read sample window in units (~3 s .. ~10 s)
    reference_ceiling: int = 42
    line_units: tuple[int, int] = (10, 14)  # craft-standard spoken units of one ~3.5 s line
    verbatim_run: int = 16          # DR1: longest run of source text a line may copy verbatim
    episode_label: str = "第{n}集"   # {n} = display number ({cn} = Chinese numeral for zh)

    @property
    def is_cjk(self) -> bool:
        return self.unit == "char"


PROFILES: dict[str, LangProfile] = {
    "zh": LangProfile(
        code="zh", locale="zh-CN", name="Chinese", unit="char",
        speech_re=re.compile(r"[㐀-鿿]"), rate=4.2, separators=("：",), joiner="",
        whisper="zh", whisper_model="small", h3_tag="Chinese", endcard="未完待续",
        voice_locale_text="zh-CN Mandarin, no accent processing, no pitch shifting",
        calibration=("真的吗？你再说一遍！我等了整整三天，原来就为了这一句？", "怎么会这样？刚才还好好的，现在全都变了！"),
        normalise=_norm_zh, reference_floor=12, reference_ceiling=42, line_units=(10, 14), verbatim_run=16,
        episode_label="第{cn}集"),
    "en": LangProfile(
        code="en", locale="en-US", name="English", unit="word",
        speech_re=EN_WORD_RE, rate=2.7, separators=("：", ":"), joiner=" ",
        whisper="en", whisper_model="small", h3_tag="English", endcard="TO BE CONTINUED",
        voice_locale_text="en-US English, no accent processing, no pitch shifting",
        calibration=("What? Say that again! Three whole days I waited, and this is all you bring me?",
                     "How could this happen? A minute ago it was fine, and now everything has changed!"),
        normalise=_norm_en, reference_floor=8, reference_ceiling=27, line_units=(8, 10), verbatim_run=8,
        episode_label="EPISODE {n:02d}"),
    "ja": LangProfile(
        code="ja", locale="ja-JP", name="Japanese", unit="char",
        speech_re=re.compile(f"[{HAN}{KANA}々A-Za-z0-9０-９]"), rate=6.0,
        separators=("：", ":"), joiner="",
        # owner 2026-11-18: Japanese ASR uses a bigger Whisper model rather than a lower recall floor
        whisper="ja", whisper_model="medium", h3_tag="Japanese", endcard="つづく",
        voice_locale_text="ja-JP Japanese, standard Tokyo accent, no accent processing, no pitch shifting",
        calibration=("えっ、本当に？もう一度言って！三日も待ったのに、それだけなの？",
                     "どうしてこうなったの？さっきまで普通だったのに、全部変わっちゃった！"),
        normalise=_norm_ja, reference_floor=18, reference_ceiling=60, line_units=(18, 22), verbatim_run=12,
        episode_label="第{n}話"),
    "ko": LangProfile(
        code="ko", locale="ko-KR", name="Korean", unit="char",
        speech_re=re.compile(f"[가-힣A-Za-z0-9]"), rate=5.0,
        separators=("：", ":"), joiner=" ",
        whisper="ko", whisper_model="small", h3_tag="Korean", endcard="다음 화에 계속",
        voice_locale_text="ko-KR Korean, standard Seoul accent, no accent processing, no pitch shifting",
        calibration=("뭐라고? 다시 말해 봐! 사흘이나 기다렸는데, 고작 이 말 하려고?",
                     "어떻게 이럴 수가 있어? 조금 전까지 멀쩡했는데, 지금은 다 변했잖아!"),
        normalise=_norm_ko, reference_floor=15, reference_ceiling=50, line_units=(14, 18), verbatim_run=10,
        episode_label="제{n}화"),
}


def language_code(value: Any) -> str | None:
    """"zh" / "zh-CN" / "ja_JP" / "KO" -> the 2-letter code; anything unsupported -> None."""
    text = str(value or "").strip().lower().replace("_", "-")
    for code in LANGUAGES:
        if text == code or text.startswith(code + "-"):
            return code
    return None


def profile(language: Any = None) -> LangProfile:
    """The profile for ``language`` (code or locale); unknown / empty is the historical zh line."""
    return PROFILES[language_code(language) or DEFAULT_LANGUAGE]


def speech_units(text: Any, language: Any = None) -> int:
    """Spoken units: zh/ja characters, ko syllables, en words."""
    return len(profile(language).speech_re.findall(str(text or "")))


def speech_seconds(text: Any, language: Any = None, rate: float | None = None) -> float:
    prof = profile(language)
    return speech_units(text, language) / float(rate or prof.rate)


def split_speaker(raw: Any, language: Any = None) -> tuple[str, str, str]:
    """``speaker：words`` -> (speaker, separator, words), trying each separator of the language."""
    text = str(raw or "")
    for separator in profile(language).separators:
        speaker, sep, words = text.partition(separator)
        if sep:
            return speaker, sep, words
    return text, "", ""


def normalise(text: Any, language: Any = None) -> str:
    """ASR comparison text: only what is spoken, in one canonical script."""
    return profile(language).normalise(str(text or ""))


def episode_label(number: int, language: Any = None) -> str:
    prof = profile(language)
    if "{cn}" in prof.episode_label:
        return prof.episode_label.format(cn=zh_numeral(number))
    return prof.episode_label.format(n=int(number))


def zh_numeral(number: int) -> str:
    digits = "零一二三四五六七八九"
    n = int(number)
    if n < 0:
        return str(n)
    if n < 10:
        return digits[n]
    if n < 20:
        return "十" + (digits[n % 10] if n % 10 else "")
    if n < 100:
        return digits[n // 10] + "十" + (digits[n % 10] if n % 10 else "")
    return str(n)


def has_speech(text: Any, language: Any = None) -> bool:
    return bool(profile(language).speech_re.search(str(text or "")))


def is_cjk_language(language: Any) -> bool:
    """zh / ja / ko: no spaces between words is not a fault, one character is one timing unit."""
    return profile(language).is_cjk


#: one alignment token per character: the historical zh range (U+4E00-U+9FFF) plus kana and Hangul syllables
CJK_TOKEN_RE = re.compile("[\u4e00-\u9fff\u3041-\u3096\u30a1-\u30fa\uac00-\ud7a3]")


def cjk_tokens(text: Any) -> list[str]:
    """Character tokens for ASR / script alignment (head / tail trim, performance cut): Han as before, kana
    folded to hiragana, Hangul syllables.  A Chinese text yields exactly the historical Han-only tokens."""
    return [_katakana_to_hiragana(ch) for ch in CJK_TOKEN_RE.findall(str(text or ""))]


def is_cjk_token(ch: str) -> bool:
    return bool(CJK_TOKEN_RE.fullmatch(ch or ""))


def whisper_model_for(language: Any = None) -> str:
    return profile(language).whisper_model


__all__ = [
    "CJK_SPEECH_RE", "CJK_TOKEN_RE", "DEFAULT_LANGUAGE", "cjk_tokens", "is_cjk_token", "EN_WORD_RE", "HAN", "HANGUL", "HANGUL_RE", "HAN_RE", "KANA",
    "KANA_RE", "LANGUAGES", "LangProfile", "PROFILES", "episode_label", "has_speech", "is_cjk_language",
    "language_code", "normalise", "profile", "speech_seconds", "speech_units", "split_speaker",
    "whisper_model_for", "zh_numeral",
]
