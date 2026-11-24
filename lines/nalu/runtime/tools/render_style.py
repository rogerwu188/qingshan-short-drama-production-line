#!/usr/bin/env python3
"""One per-series render style: ``live_action`` (the historical line, the default) or ``anime``.

Owner + boss 2026-11-19, after the paid JA-01 probe (``~/Desktop/动漫风格测试``): MiniMax-H3 holds 2D cel-shaded
TV-anime style, on-model characters and Japanese lip-sync from anime keyframes, but InsightFace cannot tell anime
characters apart (a DIFFERENT character's card scored 0.587 > the 0.45 pass threshold; the speaker was detected on
1 frame of 9).  So an anime series changes two things and nothing else:

* the prompt blocks (identity cards, plates, keyframes, H3, poster, Codex note) say "2D anime", never "live-action /
  real materials / photographic";
* every InsightFace identity / face-count / speaker-framing / push-in measurement is NOT_APPLICABLE and never blocks
  or auto-redoes; the identity evidence is the engine's existing VLM review (``vlm_review_protocol``) answering an
  anime character-consistency question (hair colour and style, eye colour, outfit, accessories vs the card).

Where a series declares it (first hit wins):

1. the generation contract ``visual_culture_contract.render_style`` (also a compiled unit's copy of it, or a
   top-level ``render_style`` on a unit);
2. the episode's production brief ``render_style`` (``<runtime>/briefs/<EP>_PRODUCTION_BRIEF.json``);
3. the runtime ``qingshan.json`` ``project.render_style`` (series-wide default);
4. ``live_action``.

Live-action output is byte-identical to before this module: every site keeps its historical text and only
branches when the resolved style is ``anime``.  Pure data and functions; the runtime lookups read two small JSON
files and never raise.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LIVE_ACTION = "live_action"
ANIME = "anime"
STYLES = (LIVE_ACTION, ANIME)
DEFAULT_STYLE = LIVE_ACTION
FIELD = "render_style"

_ALIASES = {
    "live_action": LIVE_ACTION, "liveaction": LIVE_ACTION, "live": LIVE_ACTION, "realistic": LIVE_ACTION,
    "real": LIVE_ACTION, "photographic": LIVE_ACTION, "真人": LIVE_ACTION, "实拍": LIVE_ACTION,
    "anime": ANIME, "2d_anime": ANIME, "japanese_anime": ANIME, "tv_anime": ANIME, "cel_shaded": ANIME,
    "animation": ANIME, "动漫": ANIME, "动画": ANIME, "アニメ": ANIME,
}


# --------------------------------------------------------------------------- resolution
def normalise(value: Any) -> str | None:
    """"anime" / "2D-anime" / "Live Action" ... -> one of STYLES; anything else -> None."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(text)


def from_contract(contract: Any) -> str | None:
    """The style a generation contract, a visual_culture_contract or a compiled unit declares (None = silent)."""
    if not isinstance(contract, dict):
        return None
    vcc = contract.get("visual_culture_contract")
    for source in (vcc if isinstance(vcc, dict) else None, contract):
        if isinstance(source, dict):
            style = normalise(source.get(FIELD))
            if style:
                return style
    return None


def from_brief(brief: Any) -> str | None:
    return normalise(brief.get(FIELD)) if isinstance(brief, dict) else None


def from_config(config: Any) -> str | None:
    project = config.get("project") if isinstance(config, dict) else None
    return normalise(project.get(FIELD)) if isinstance(project, dict) else None


def resolve(contract: Any = None, brief: Any = None, config: Any = None) -> str:
    """contract -> brief -> runtime config -> live_action."""
    return from_contract(contract) or from_brief(brief) or from_config(config) or DEFAULT_STYLE


def _read(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def default_runtime_root() -> Path | None:
    try:
        import nalu_paths as _np  # noqa: PLC0415 - runtime tools dir
    except ImportError:  # pragma: no cover - imported from engine tools/ without the runtime dir
        try:
            import importlib.util as _util  # noqa: PLC0415
            spec = _util.spec_from_file_location("nalu_paths", Path(__file__).resolve().parent / "nalu_paths.py")
            _np = _util.module_from_spec(spec)
            spec.loader.exec_module(_np)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return None
    return Path(f"{_np.RUNTIME_ROOT}")


def brief_path(runtime_root: Path, episode: str) -> Path:
    return Path(runtime_root) / "briefs" / f"{episode}_PRODUCTION_BRIEF.json"


def resolve_runtime(episode: str | None = None, *, contract: Any = None,
                    runtime_root: Path | str | None = None) -> str:
    """``resolve`` with the brief and ``qingshan.json`` read from the runtime root (env / pin / beside tools)."""
    style = from_contract(contract)
    if style:
        return style
    root = Path(runtime_root) if runtime_root else default_runtime_root()
    if root is None:
        return DEFAULT_STYLE
    brief = _read(brief_path(root, episode)) if episode else None
    return from_brief(brief) or from_config(_read(root / "qingshan.json")) or DEFAULT_STYLE


def is_anime(value: Any) -> bool:
    """True for "anime", or for a contract / unit that declares it."""
    if isinstance(value, dict):
        return from_contract(value) == ANIME
    return normalise(value) == ANIME


def stamp(contract: dict[str, Any] | None, style: str) -> dict[str, Any] | None:
    """A copy of a visual_culture_contract carrying ``render_style`` (only for anime: live-action stays unstamped
    so every live-action unit is byte-identical)."""
    if not isinstance(contract, dict) or normalise(style) != ANIME:
        return contract
    return {**contract, FIELD: ANIME}


# --------------------------------------------------------------------------- prompt blocks (anime only)
#: the wording that held in the paid probe (identity cards, keyframes)
STYLE_PHRASE_EN = ("modern high-quality Japanese TV anime, 2D cel-shaded, clean consistent line art, "
                   "not photorealistic, not 3D")
IMAGE_STYLE_BLOCK_EN = (
    "ART STYLE LOCK (anime): modern high-quality Japanese TV anime key visual, 2D cel-shaded animation style, clean "
    "consistent line art, flat cel shading with soft two-tone shadows, large expressive anime eyes, detailed hair "
    "strands drawn as clean shapes. Not photorealistic, not 3D, not a real person, no photographic skin texture."
)
IMAGE_STYLE_BLOCK_ZH = (
    "【画风锁·日式电视动画】modern high-quality Japanese TV anime, 2D cel-shaded, clean consistent line art, "
    "not photorealistic, not 3D：现代高品质日式电视动画，2D 赛璐璐上色，干净统一的线稿，平涂配柔和的两阶阴影，"
    "动画式大眼睛，发丝画成干净的块面；不写实、不做3D、不是真人，没有照片式皮肤质感。"
)
IMAGE_TEXTURE_ZH = "现代高品质日式电视动画：2D 赛璐璐上色、干净统一的线稿、平涂与柔和两阶阴影；不写实、不做3D、不是真人照片质感"
IMAGE_TEXTURE_EN = ("modern high-quality Japanese TV anime: 2D cel shading, clean consistent line art, flat colour "
                    "with soft two-tone shadows; not photorealistic, not 3D, no photographic skin")
#: replaces the live-action texture / ban pair of the authored-world fallback contract (bootstrap_identity_cards)
FORBIDDEN_INFLUENCES_EN = (
    "drift into another era or culture", "photorealistic, live-action or 3D CGI look",
    "style drift between frames or views", "black-gold fantasy poster light",
    "teal-orange blockbuster grade", "visible text and watermarks",
)

# H3 (English provider prompt)
H3_GENRE = "2D anime short drama"
H3_ART_STYLE_LINE = (
    "art_style: 2D Japanese TV anime, cel-shaded, clean line art, flat anime colouring, TV anime quality; NOT "
    "photorealistic, not live-action, not 3D CGI, no real human faces or photographic skin. Every frame stays a "
    "hand-drawn-looking anime frame matching @Image1."
)
H3_NEGATIVES = ("photorealistic, live-action, real people, 3D render", "style drift or face morphing")


def h3_insert_genre(props: str) -> str:
    return f"a single anime insert shot of {props}; 2D cel-shaded, no people, no hands, no body parts"


H3_RESCUE_HEADER = "H3 2D ANIME SHORT-DRAMA AUDIO RESCUE. MACHINE METADATA IS NEVER SPOKEN."
H3_RESCUE_STYLE = "STYLE=2D_JAPANESE_TV_ANIME_CEL_SHADED;NOT_PHOTOREAL;NOT_3D"

#: live-action lock wording -> anime wording (period / world locks, visual-culture prompt blocks).  Applied only
#: when the style is anime, so the live-action text never changes.
_LOCK_SUBSTITUTIONS_EN = (
    ("real materials, soft motivated light, muted natural palette",
     "clean anime line art and stable cel shading, soft motivated light, muted consistent palette"),
    ("real materials, soft motivated light, natural grade",
     "clean anime line art and stable cel shading, soft motivated light, consistent palette"),
    ("soft motivated daylight, real materials", "soft motivated daylight, clean anime line art and cel shading"),
    ("soft motivated light, real materials", "soft motivated light, clean anime line art and cel shading"),
    ("game-poster light", "photoreal or 3D CGI rendering"),
    ("game-poster", "photoreal or 3D CGI"),
)
_LOCK_SUBSTITUTIONS_ZH = (
    ("自然柔光、真实材质", "自然柔光、干净线稿与稳定的赛璐璐上色"),
    ("真实材质", "统一的动画材质表现（赛璐璐上色、干净线稿）"),
    ("黑金奇幻游戏海报", "黑金奇幻海报/写实或3D渲染"),
    ("游戏海报光", "写实或3D渲染光"),
)


def anime_lock(text: str) -> str:
    """A period / world lock with its live-action wording swapped for the anime wording."""
    out = str(text or "")
    for old, new in (*_LOCK_SUBSTITUTIONS_EN, *_LOCK_SUBSTITUTIONS_ZH):
        out = out.replace(old, new)
    return out


def style_lock(text: str, style: Any) -> str:
    """``text`` unchanged for live-action; the anime wording for anime."""
    return anime_lock(text) if normalise(style) == ANIME else text


# keyframes / plates (Chinese image prompts, build_keyframe_manifest + build_episode_asset_requirements)
KEYFRAME_HEADER_STYLE_ZH = "竖屏 9:16 日式电视动画（2D 赛璐璐上色、干净统一线稿，非写实、非3D）单帧画面，"
KEYFRAME_HARD_STYLE_ZH = ("透视合理、人物脚底落地、人体比例可信；角色造型与身份卡一致（发型发色、瞳色、服装配饰不变），"
                          "2D 赛璐璐上色、干净统一的线稿，不写实、不做3D渲染、无照片式皮肤质感；单帧静止画面，无运动模糊特效。")
TOPOLOGY_OUTPUT_ZH = "输出必须是日式电视动画风格画面（2D 赛璐璐上色、干净线稿），不得画成地图、示意图、平面图或带任何标注线条。"
LOCATION_OUTPUT_ZH = ("输出必须是日式电视动画风格的场景背景美术（2D 赛璐璐上色、干净线稿，非写实、非3D），"
                      "不得画成地图、示意图、平面图或带任何标注线条。")
PROMPT_BATCH_FRAME_EN = ("Create exactly one continuous 2D anime frame (modern Japanese TV anime, cel-shaded, clean line "
                         "art, not photorealistic, not 3D) with one camera position and one decisive dramatic moment; "
                         "no collage, panels, split screen, storyboard sheet, contact sheet, or inset image. ")

# identity cards (bootstrap_identity_cards, character_reference_sheet)
SAME_IDENTITY_CLAUSE_ZH = (
    "【参考图】参考图是同一角色已锁定的全身设定图：发型与发色、眼睛颜色与眼型、脸型、体型、服装与配饰必须与参考图完全一致，"
    "同一个动画角色设计（on-model）；只改变取景与朝向，不改变角色。"
)
SHEET_REFERENCE_CLAUSE_ZH = (
    "【参考图】参考图是同一角色已锁定的设定图：发型与发色、眼睛颜色、脸型、体型、服装与配饰必须与参考图完全一致，"
    "同一个动画角色设计（on-model）；只改变排版与朝向，不改变角色。"
)

# poster (tools/series_poster.py)
POSTER_OPENING_EN = "Modern high-quality Japanese TV anime key-visual poster, vertical 9:16, for an anime series. "
POSTER_COMPOSITION_EN = (
    "Composition: premium anime series key visual, 2D cel-shaded, clean consistent line art, rich anime colouring, "
    "dramatic anime lighting, characters exactly on-model with their references, not photorealistic, not 3D, the "
    "faces in the upper two thirds of the frame. "
)

# Codex start prompt (nalu_craft_standard.codex_section)
CODEX_NOTE_ZH = (
    "## 画风：日式电视动画（render_style=anime）\n"
    "本剧按 2D 日式电视动画制作（赛璐璐上色、干净统一线稿，非写实、非3D）。表演用动画惯例：姿态与表情清楚可读、"
    "口型开合对台词、眨眼与发丝衣摆的二次动作；不写真人皮肤质感、微表情或镜头光学参数。角色设计全剧一致："
    "发型发色、瞳色、服装配饰按身份卡，不换造型；身份卡由文字描述生成，不需要真人照片。"
    "每集生成合同保持 visual_culture_contract.render_style=\"anime\"。"
)

# --------------------------------------------------------------------------- identity (anime)
#: the identity method of an anime still / clip: the reviewer's structured anime character-consistency answers
VLM_IDENTITY_METHOD = "VLM_ANIME_CHARACTER_CONSISTENCY_V1"
VLM_IDENTITY_QUESTION = "anime_character_design_matches_card"
ART_STYLE_QUESTION = "plate_matches_declared_art_style"
INSIGHTFACE_NOT_APPLICABLE_REASON = (
    "render_style=anime: InsightFace does not separate anime characters (JA-01 probe 2026-11-19: different-character "
    "cosine 0.587 > 0.45 pass; speaker detected on 1/9 frames) -- the VLM character-consistency review is the "
    "identity evidence")
_PASS = {"PASS", "YES"}


def vlm_identity_question(kind: str) -> dict[str, Any]:
    """The closed anime character-consistency question for a review kind (identity / keyframe / video_q2)."""
    against = ("the identity card description (expectations.appearance / expectations.wardrobe)"
               if kind == "identity" else "its locked identity plates / reference images")
    scope = {"identity": "every plate", "keyframe": "the frame", "video_q2": "every frame of the clip"}.get(kind, "the media")
    return {
        "enum": ["PASS", "FAIL", "NOT_APPLICABLE", "UNCERTAIN"],
        "maps_to": ["CHARACTER-IDENTITY-ADMISSION", VLM_IDENTITY_METHOD],
        "question": (f"ANIME CHARACTER CONSISTENCY (render_style=anime; replaces the face-embedding measurement): in "
                     f"{scope}, is each visible character exactly on-model with {against} -- same hair colour and "
                     "hairstyle, same eye colour, same outfit and accessories, same face design -- with no off-model "
                     "frame and no character swapped for another"
                     + (" (nor a person who turns into a different character partway through the clip)"
                        if kind == "video_q2" else "")
                     + "?  NOT_APPLICABLE only when no character is declared visible."),
    }


#: JA-01 anime E04 VU-007 (2026-11-21): H3 drew the character's multi-view identity sheet as the picture and the Q2
#: VLM passed every identity question.  Asked of anime video_q2 items; a FAIL fails the anime identity check (redo /
#: order path as before), a missing answer (a request built before this question) is not counted.
SHEET_LEAK_QUESTION = "picture_is_performance_shot_not_character_sheet"
SHEET_LEAK_QUESTION_SPEC: dict[str, Any] = {
    "enum": ["PASS", "FAIL", "UNCERTAIN"],
    "maps_to": ["CHARACTER-IDENTITY-ADMISSION", "QA-REFERENCE-SHEET-LEAK"],
    "question": ("REFERENCE-SHEET LEAK: is every frame a normal performance shot of the scene -- NOT a character "
                 "sheet / turnaround / model sheet (the same character shown as front, side and back full-body "
                 "views side by side, often with a big face close-up inset on a flat background), NOT a collage, and "
                 "with no character appearing as two or more copies in one frame?  FAIL if any frame shows such a "
                 "sheet, collage or duplicated character."),
}


ART_STYLE_QUESTION_SPEC: dict[str, Any] = {
    "enum": ["PASS", "FAIL", "UNCERTAIN"],
    "maps_to": ["asset_library.qa.checks.REALISM"],
    "question": ("Is the plate consistent with the declared art style (render_style=anime: modern Japanese TV anime, "
                 "clean consistent line art, stable cel shading, on-model) -- not photorealistic, not 3D, not "
                 "mixed styles?"),
}


#: anime cast distinctness (line owner 2026-11-19): InsightFace cannot compare anime faces, so the identity review asks
#: whether this character's design is distinguishable from the other characters' plates.  Descriptive: no enum value
#: is a FAIL/UNCERTAIN answer, so it never rejects a plate; TOO_SIMILAR is recorded as an advisory
#: (character_distinctness.anime_record, identity_qa_lock).
CAST_DISTINCT_QUESTION = "anime_cast_design_distinct"
CAST_DISTINCT_QUESTION_SPEC: dict[str, Any] = {
    "enum": ["DISTINCT", "TOO_SIMILAR", "NOT_APPLICABLE"],
    "maps_to": ["identity_qa_lock.character_distinctness (advisory)", "VLM_ANIME_CAST_DESIGN_DISTINCT_V1"],
    "descriptive": True,
    "question": ("CAST DISTINCTNESS (render_style=anime; descriptive, never a failure): compared with the OTHER "
                 "characters' plates supplied as PEER_CHARACTER_PLATE media, is this character's design clearly "
                 "distinguishable at a glance -- hair colour and style, eye colour and shape, silhouette, outfit "
                 "palette?  TOO_SIMILAR when a viewer could mistake one for the other (name the other character in "
                 "the observation); NOT_APPLICABLE when no peer plate is supplied."),
}


def style_questionnaire(kind: str, questionnaire: dict[str, dict[str, Any]], style: Any) -> dict[str, dict[str, Any]]:
    """The questionnaire of one review kind for the style: unchanged for live-action; for anime the photographic
    realism question becomes the art-style question and the anime character-consistency question is added."""
    if normalise(style) != ANIME or kind not in ("identity", "keyframe", "video_q2"):
        return questionnaire
    out: dict[str, dict[str, Any]] = {}
    for key, row in questionnaire.items():
        if key == "plate_is_photographic_not_illustrated":
            out[ART_STYLE_QUESTION] = dict(ART_STYLE_QUESTION_SPEC)
            continue
        out[key] = row
    out[VLM_IDENTITY_QUESTION] = vlm_identity_question(kind)
    if kind == "video_q2":
        out[SHEET_LEAK_QUESTION] = dict(SHEET_LEAK_QUESTION_SPEC)
    if kind == "identity":
        out[CAST_DISTINCT_QUESTION] = dict(CAST_DISTINCT_QUESTION_SPEC)
    return out


def vlm_identity_failures(answers: Any, *, characters_declared: bool = True) -> list[str]:
    """[] when the anime VLM identity evidence is present and passing, else the reasons."""
    answer = str((answers or {}).get(VLM_IDENTITY_QUESTION) or "").strip().upper() if isinstance(answers, dict) else ""
    if not answer:
        return ["ANIME_VLM_IDENTITY_EVIDENCE_MISSING"]
    if answer in _PASS or (answer == "NOT_APPLICABLE" and not characters_declared):
        return []
    return [f"ANIME_VLM_IDENTITY_NOT_CONFIRMED:{answer}"]


def not_applicable_measurement(method: str, **extra: Any) -> dict[str, Any]:
    """The record an InsightFace-based measurement leaves for an anime series: never a failure."""
    return {"method": method, "status": "NOT_APPLICABLE", "decision": "NOT_APPLICABLE", "render_style": ANIME,
            "reason": INSIGHTFACE_NOT_APPLICABLE_REASON, "failures": [], **extra}


# --------------------------------------------------------------------------- final review (anime)
#: decision (2026-11-19): REDEFINE ``anti_ai`` for anime instead of adding an ``art_style_consistency`` dimension.
#: The dimension set is a schema shared by the reviewer contract, the 3.5 floor (final_cut_quality_gates /
#: audience_score_gate), the exemplar library and every stored review -- a new dimension would be a new required
#: score (a new gate) and split the history; the same key with an anime question keeps the floor and the gates
#: exactly as they are while asking the right thing.
ANTI_AI_QUESTION_ANIME = (
    "ANIME SERIES (render_style=anime): clean 2D cel-shaded stylization is the intended look and is NOT an 'AI look' "
    "-- never penalize it.  Does the film avoid AI defects: warping or melting shapes, off-model frames (a "
    "character's hair, eyes, outfit or face design changing), mid-clip style drift (toward photoreal or 3D, or "
    "between drawing styles), repetition and synthetic rhythm?"
)

#: live-action image prompts with people (identity cards, turnaround sheets, keyframes).  Line owner 2026-11-24 (KO
#: E01 0:32, device ...1437): a man's face read oily / wet with specular highlights; the H3 video prompt already
#: forbade sheen (h3_provider_prompt_renderer.SKIN_FINISH_NEGATIVE) but the images it starts from did not, and the
#: S6 sheen check only measures DRIFT from those images -- an oily card or keyframe passed as its own reference.
LIVE_SKIN_FINISH_ZH = ("皮肤质感：自然哑光肌肤，脸上无油光、无汗珠、无湿亮反光（额头、鼻梁、脸颊不发亮），头发干爽；"
                       "不做塑料感磨皮、不过度锐化（剧情明确写雨水、汗水、泪水时除外）。")

__all__ = [
    "LIVE_SKIN_FINISH_ZH", "LIVE_ACTION", "ANIME", "STYLES", "DEFAULT_STYLE", "FIELD", "normalise", "from_contract", "from_brief",
    "from_config", "resolve", "default_runtime_root", "brief_path", "resolve_runtime", "is_anime", "stamp",
    "STYLE_PHRASE_EN", "IMAGE_STYLE_BLOCK_EN", "IMAGE_STYLE_BLOCK_ZH", "IMAGE_TEXTURE_ZH", "IMAGE_TEXTURE_EN",
    "FORBIDDEN_INFLUENCES_EN", "H3_GENRE", "H3_ART_STYLE_LINE", "H3_NEGATIVES", "h3_insert_genre",
    "H3_RESCUE_HEADER", "H3_RESCUE_STYLE", "anime_lock", "style_lock", "KEYFRAME_HEADER_STYLE_ZH",
    "KEYFRAME_HARD_STYLE_ZH", "TOPOLOGY_OUTPUT_ZH", "LOCATION_OUTPUT_ZH", "PROMPT_BATCH_FRAME_EN",
    "SAME_IDENTITY_CLAUSE_ZH", "SHEET_REFERENCE_CLAUSE_ZH", "POSTER_OPENING_EN", "POSTER_COMPOSITION_EN",
    "CODEX_NOTE_ZH", "VLM_IDENTITY_METHOD", "VLM_IDENTITY_QUESTION", "ART_STYLE_QUESTION",
    "SHEET_LEAK_QUESTION", "SHEET_LEAK_QUESTION_SPEC",
    "INSIGHTFACE_NOT_APPLICABLE_REASON", "vlm_identity_question", "ART_STYLE_QUESTION_SPEC", "style_questionnaire",
    "vlm_identity_failures", "not_applicable_measurement", "ANTI_AI_QUESTION_ANIME", "CAST_DISTINCT_QUESTION",
    "CAST_DISTINCT_QUESTION_SPEC",
]
