#!/usr/bin/env python3
"""nalu_writer_selfcheck_seq29.py — writer-layer self-check for SUPERVISOR_ORDERS seq=29 (rules 5–8).

Roger 2026-09-18《E05/E06 生产线补正 —— 追加：语速 / 镜长 / 表演指令 / 压力源》(ADVISORY, E06+):

  规则 5  镜长跟台词走，禁「说完保持」
    5a  对白镜 target_seconds = ceil_0.5(台词字数 / 字每秒 + 0.5)；不得套模板（超出 +0.5 s 即 FAIL）
    5b  action 字段（primary_action / performance / constraints）不得出现 保持/口型闭合/静止/定住 类收尾指令
    5c  无对白镜 ≤ 5 s；对白镜 performance.body_action 必须是进行中的身体动作（琐碎动作不算）
  规则 7  禁令与表演分栏，每个对白镜必有情绪动词＋身体动作
    7b  performance = {emotion, body_action, delivery} 三要素必填
    7c  emotion 必须在闭集词表；同一场连续 3 个对白镜同一情绪词 = FAIL
    7d  儿童角色台词字/秒目标 ≥ 4.5
  规则 8  外部压力源（仅当合同声明 rule8_authorized 时执行；否则只报告）
    8a  pressure_source 在前 30 s；8b episode_payoff 二选一；8c action_chain 想要→受阻→出手
  规则 10 对白镜的动作文字不得要求换嗓子（压着嗓子/扯着嗓子/声音发颤…，词表 configs/VOICE_TIMBRE_LOCK_V1.json）；
          默认只警告，配置 selfcheck.blocking 或合同 voice_timbre_policy.enforced 时阻断
  规则 11 （仅 CAMERA_GRAMMAR_V1；线主 2026-11-02 实验集化神 E01 起降为提示）画内台词估算 < 2.8 s 只进 advisories
          R11_SHORT_LINE_OK_S7_CUTS：保留原著的短句，不要为凑 4 s 加词；生成仍按 4 s 下限请求，S7 剪到表演
          （tools/performance_cut.py）。同一说话人 CONTINUOUS_ACTION 同机位的连续台词（独白组）每句不受 4 s 下限，
          编译器按台词估算首尾相接排时间（speaking_unit_duration.monologue_group_durations）
  规则 12 （仅 CAMERA_GRAMMAR_V1，线主 2026-11-01，实验集 E12 长镜头）同一说话人的连续台词是一个镜头（同一锁定机位，
          CONTINUOUS_ACTION，≤12 s），只警告：R12_MONOLOGUE_CUT_BETWEEN_LINES（两句之间写了切镜或换了机位）、
          R12_MONOLOGUE_OVER_12S_ADD_CUTAWAY（同机位连续台词超过 12 s：在两组之间插一个无台词的反应/道具插入镜头，
          再回到同一机位）。一个镜头里写同一人的多句台词也可以（5a 按多句总时长计，≤12 s）

The check is a WRITER-LAYER self-check: it carries no gate_id.  It is enforced (S1 refuses to enter
S2) only when the contract declares ``writer_selfcheck_seq29.enforced: true`` (E06+ builders);
older contracts get a diagnostic report.  Exit 0 PASS / not enforced, 3 enforced FAIL.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import nalu_prompt_rules as npr  # noqa: E402

import argparse  # noqa: E402
import json
import re  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

SCHEMA = "nalu.writer_selfcheck_seq29.v1"
LEXICON_PATH = Path(__file__).resolve().parent.parent / "configs" / "PERFORMANCE_EMOTION_LEXICON_v1.json"
#: rule 5a says line + 0.5 s; the engine's dialogue_cut_safety additionally needs 0.12 s lead + 0.32 s pad + 0.25 s
#: unit tail + 0.16 s per punctuation mark, so a derived length may sit up to 1.0 s above the bare rule (rounded to 0.5).
TEMPLATE_TOLERANCE_S = 1.0
NO_DIALOGUE_SHOT_MAX_S = 5.0
CHILD_CPS_MIN = 4.5
PRESSURE_SOURCE_WINDOW_S = 30.0
CONSECUTIVE_EMOTION_MAX = 2   # the third identical word in a row fails


def load_lexicon(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))


def _spoken(dialogue: str) -> str:
    text = str(dialogue or "").strip()
    return text.split("：", 1)[1] if "：" in text[:24] else text  # long English speaker names too (lab E09)


def derived_dialogue_seconds(dialogue: str, cps: float | None) -> float:
    """Rule 5a: line seconds + 0.5, rounded UP to 0.5 s (10 chars @ 5.0 → 2.5 s).

    A shot with several lines (one speaker's lines in one take, owner 2026-11-01) is timed by all its lines
    together, each without its ``Speaker：`` prefix; a single line is timed exactly as before.

    A line with no CJK character at all is English: timed by words (same as static_design_gate R8),
    never letter by letter; Chinese lines always contain CJK and are unchanged."""
    rows = [row for row in str(dialogue or "").splitlines() if row.strip()]
    spoken = _spoken(dialogue) if len(rows) < 2 else " ".join(_spoken(row) for row in rows)
    if not re.search(r"[\u3400-\u9fff]", spoken) and re.search(r"[A-Za-z]", spoken):
        spoken = spoken.split(":", 1)[1] if ":" in spoken[:24] else spoken
        return npr.min_dialogue_seconds(spoken, None, "en")
    return npr.min_dialogue_seconds(spoken, cps)


def action_texts(shot: dict[str, Any]) -> list[str]:
    spec = shot.get("prompt_spec") or {}
    action = spec.get("action") or {}
    out = [str(action.get(k) or "") for k in ("primary_action", "start_state", "end_state", "completion_state")]
    perf = action.get("performance") if isinstance(action.get("performance"), dict) else {}
    out += [str(v or "") for v in perf.values()]
    out += [str(x or "") for x in (action.get("constraints") or []) if not isinstance(x, (dict, list))]
    return [t for t in out if t]


def is_child(character: dict[str, Any]) -> bool:
    if character.get("child") is True:
        return True
    rng = str(character.get("apparent_age_range") or "")
    try:
        hi = int(rng.replace("–", "-").split("-")[-1])
        return hi <= 12
    except ValueError:
        return False


#: posture classes read from state texts; longest tokens first (盘坐 before 坐, 跪坐 before 跪).
POSTURE_CLASSES = (
    ("SIT", ("盘坐", "坐")), ("KNEEL", ("跪坐", "跪")), ("CROUCH", ("蹲",)),
    ("LIE", ("半撑", "躺", "伏", "趴", "倒在")),
    ("STAND", ("站", "走", "跨", "跑", "奔", "迎上", "迈", "踱", "冲")),
)


def posture_class(text: str) -> str | None:
    """First posture class whose token appears in the text (None = no posture word)."""
    t = str(text or "")
    for cls, toks in POSTURE_CLASSES:
        if any(tok in t for tok in toks):
            return cls
    return None


def posture_words(text: str) -> set[str]:
    cls = posture_class(text)
    return {cls} if cls else set()


def shot_subject(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") or {}
    action = spec.get("action") or {}
    sid = action.get("subject_id") or action.get("initiator_entity_id")
    if sid:
        return str(sid)
    cast = spec.get("cast") or []
    return str((cast[0] or {}).get("character_id") or (cast[0] or {}).get("character")) if cast else ""


def posture_continuity_failures(shots: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """R9 (D-68): inside a scene, a character's posture persists from the last state text that named it;
    the next shot's ENTRY posture for the same character must equal it — the change is authored INSIDE
    the shot (e.g. 「盘坐着睁开眼睛起身」, not 「站在磨盘旁」).  Returns (failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []
    prev = None
    posture: dict[str, str] = {}
    for shot in shots:
        if prev is None or shot.get("scene_id") != prev.get("scene_id"):
            posture = {}
        subject = shot_subject(shot)
        entry_cls = posture_class(shot.get("entry_state"))
        if prev is not None and shot.get("scene_id") == prev.get("scene_id"):
            pe = ((prev.get("state_delta_evidence") or {}).get("POSTURE") or {})
            ne = ((shot.get("state_delta_evidence") or {}).get("POSTURE") or {})
            if pe.get("exit_code") and ne.get("entry_code") and pe["exit_code"] != ne["entry_code"] and shot_subject(prev) == subject:
                warnings.append(f"R9A_POSTURE_CODE_NOT_CONTINUOUS:{prev.get('shot_id')}->{shot.get('shot_id')}:{pe['exit_code']}!={ne['entry_code']}")
            known = posture.get(subject)
            if known and entry_cls and entry_cls != known:
                failures.append(f"R9B_ENTRY_POSTURE_JUMP:{prev.get('shot_id')}->{shot.get('shot_id')}:{subject}:{known}->{entry_cls}")
        # update the character's posture from this shot's texts (entry first, completion last wins)
        if subject:
            if entry_cls:
                posture[subject] = entry_cls
            exit_cls = posture_class(shot.get("completion_state"))
            if exit_cls:
                posture[subject] = exit_cls
        prev = shot
    return failures, warnings


def voice_timbre_findings(contract: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """R10: voice-changing delivery terms in dialogue shots (configs/VOICE_TIMBRE_LOCK_V1.json)."""
    import nalu_paths as _np
    if str(_np.ENGINE_TOOLS) not in _sys.path:
        _sys.path.insert(0, str(_np.ENGINE_TOOLS))
    import voice_timbre_lock as vtl
    policy = vtl.load_policy() if policy is None else policy
    rule = policy.get("selfcheck") or {}
    decl = contract.get("voice_timbre_policy") if isinstance(contract.get("voice_timbre_policy"), dict) else {}
    blocking = bool(rule.get("blocking")) or bool(decl.get("enforced"))
    codes: list[str] = []
    by_shot: dict[str, list[str]] = {}
    for shot in contract.get("shots") or []:
        spec = shot.get("prompt_spec") or {}
        if not str(spec.get("dialogue") or "").strip():
            continue
        sid = str(shot.get("shot_id") or "?")
        terms = sorted({row["term"] for text in action_texts(shot) for row in vtl.terms_in(text, policy)})
        if terms:
            by_shot[sid] = terms
            codes.extend(f"R10_VOICE_TIMBRE_DIRECTION:{sid}:{term}" for term in terms)
    return {"blocking": blocking and bool(policy), "codes": codes, "by_shot": by_shot}


def in_video_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """The contract as the video model will see it: V.O. narrator lines removed.

    A VOICE_ONLY_NO_PLATE speaker's line (tools/voice_over_narration.py, CURRENT_PORTABLE) is
    synthesized in S4 and mixed in S7; its shot is timed by the S2 V.O. window rule, not 5a/5c/7b.
    Without a V.O. speaker the contract object is returned unchanged.
    """
    tools_dir = _pathlib.Path(__file__).resolve().parents[4] / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.append(str(tools_dir))
    import voice_over_narration as _vo
    entities = contract.get("character_entities") or []
    if not _vo.voice_over_character_ids(entities):
        return contract
    language = _vo.contract_language(contract)
    shots = []
    for shot in contract.get("shots") or []:
        spec = shot.get("prompt_spec") if isinstance(shot, dict) else None
        if isinstance(spec, dict) and isinstance(spec.get("dialogue"), str):
            in_video, voice_over = _vo.separate_voice_over(spec["dialogue"], entities, language)
            if voice_over:
                shot = {**shot, "prompt_spec": {**spec, "dialogue": in_video},
                        "_voice_over_lines": len(voice_over)}
        shots.append(shot)
    return {**contract, "shots": shots}


def provider_floor_seconds(contract: dict[str, Any]) -> float:
    """CAMERA_GRAMMAR_V1 contracts: the H3 request floor (HopsAPI: 4 s).  A dialogue shot may be that long even
    when its line is shorter — the writer rule then requires a performed action (R11 warns).  Others: 0."""
    tools_dir = _pathlib.Path(__file__).resolve().parents[4] / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.append(str(tools_dir))
    import camera_grammar_policy as _cg
    if not _cg.active(contract, episode=str(contract.get("episode") or "")):
        return 0.0
    import speaking_unit_duration as _sud
    return float(_sud.MIN_SECONDS)


def short_speaking_line_warnings(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """CAMERA_GRAMMAR_V1 contracts: dialogue shots whose in-video line is estimated under
    speaking_unit_duration.SHORT_LINE_WARN_SECONDS (same estimate the compiler uses).  Other contracts: []."""
    tools_dir = _pathlib.Path(__file__).resolve().parents[4] / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.append(str(tools_dir))
    import camera_grammar_policy as _cg
    if not _cg.active(contract, episode=str(contract.get("episode") or "")):
        return []
    import speaking_unit_duration as _sud
    import voice_over_narration as _vo
    language = _vo.contract_language(contract)
    rows = []
    for shot in contract.get("shots") or []:
        lines = [line for line in str(((shot.get("prompt_spec") or {}).get("dialogue")) or "").splitlines() if line.strip()]
        if not lines:
            continue
        seconds = _sud.estimated_line_seconds(lines, language, shot.get("dialogue_delivery"))
        if 0 < seconds < _sud.SHORT_LINE_WARN_SECONDS:
            rows.append({"shot_id": str(shot.get("shot_id") or "?"), "estimated_seconds": seconds})
    return rows


def monologue_warnings(contract: dict[str, Any]) -> list[str]:
    """R12 (CAMERA_GRAMMAR_V1 only, never blocks; owner 2026-11-01, lab E12 long-take test): one speaker's
    consecutive on-screen lines are one take -- same locked camera setup, no authored cut between them -- of at
    most speaking_unit_duration.GROUP_MAX_SECONDS; a longer monologue is split by a silent cutaway insert, then
    returns to the same setup.  Other contracts: []."""
    tools_dir = _pathlib.Path(__file__).resolve().parents[4] / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.append(str(tools_dir))
    import camera_grammar_policy as _cg
    if not _cg.active(contract, episode=str(contract.get("episode") or "")):
        return []
    import speaking_unit_duration as _sud
    authored = {str(r.get("to_shot_id")): str(r.get("transition_mode") or "").upper()
                for r in contract.get("internal_transition_authoring") or [] if isinstance(r, dict)}

    def speaker(shot: dict[str, Any]) -> str:
        spec = shot.get("prompt_spec") or {}
        if not str(spec.get("dialogue") or "").strip():
            return ""
        role = spec.get("role_semantic_disambiguation") or {}
        who = str(role.get("lip_owner_id") or role.get("dialogue_speaker_id") or "")
        offscreen = {str(m.get("character_id") or "") for m in spec.get("cast") or []
                     if str(m.get("face_visibility") or "") == "OFFSCREEN_VOICE_ONLY"}
        return "" if who in offscreen else who

    def cut_into(shot: dict[str, Any]) -> bool:
        mode = authored.get(str(shot.get("shot_id"))) or str(
            (shot.get("internal_transition_authoring") or {}).get("transition_mode") or "").upper()
        return mode.endswith("_CUT")

    out: list[str] = []
    run_start, run_seconds = None, 0.0
    prev: dict[str, Any] | None = None
    for shot in contract.get("shots") or []:
        sid = str(shot.get("shot_id") or "?")
        who = speaker(shot)
        setup = _sud.setup_key((shot.get("prompt_spec") or {}).get("camera_plan"))
        same_take = False
        if prev is not None and who and who == speaker(prev) and shot.get("scene_id") == prev.get("scene_id"):
            prev_setup = _sud.setup_key((prev.get("prompt_spec") or {}).get("camera_plan"))
            if cut_into(shot) or setup != prev_setup:
                out.append(f"R12_MONOLOGUE_CUT_BETWEEN_LINES:{sid}")
            else:
                same_take = True
        if same_take:
            run_seconds += float(shot.get("target_seconds") or 0)
        else:
            if run_start and run_seconds > _sud.GROUP_MAX_SECONDS + 1e-9:
                out.append(f"R12_MONOLOGUE_OVER_12S_ADD_CUTAWAY:{run_start}:{run_seconds:g}")
            run_start, run_seconds = (sid, float(shot.get("target_seconds") or 0)) if who else (None, 0.0)
        prev = shot
    if run_start and run_seconds > _sud.GROUP_MAX_SECONDS + 1e-9:
        out.append(f"R12_MONOLOGUE_OVER_12S_ADD_CUTAWAY:{run_start}:{run_seconds:g}")
    return out


def evaluate(contract: dict[str, Any], lexicon: dict[str, Any] | None = None) -> dict[str, Any]:
    floor_s = provider_floor_seconds(contract)
    contract = in_video_contract(contract)
    lex = lexicon or load_lexicon()
    emotions = set(lex.get("emotions") or [])
    trivial = list(lex.get("trivial_body_actions") or [])
    hold_words = list(lex.get("hold_instructions") or [])
    decl = contract.get("writer_selfcheck_seq29") if isinstance(contract.get("writer_selfcheck_seq29"), dict) else {}
    enforced = bool(decl.get("enforced"))
    rule8 = bool(decl.get("rule8_authorized"))
    failures: list[str] = []
    warnings: list[str] = []
    m: dict[str, Any] = {"dialogue_shots": 0, "no_dialogue_shots": 0, "derived_seconds_by_shot": {}, "emotions_by_scene": {}}
    children = {str(c.get("character_id")) for c in (contract.get("character_entities") or []) if isinstance(c, dict) and is_child(c)}

    prev_scene, run_word, run_len = None, None, 0
    cursor = 0.0
    for shot in contract.get("shots") or []:
        sid = str(shot.get("shot_id") or "?")
        spec = shot.get("prompt_spec") or {}
        action = spec.get("action") or {}
        dialogue = str(spec.get("dialogue") or "").strip()
        target = float(shot.get("target_seconds") or 0)
        start = cursor
        cursor += target
        # 5b — hold / freeze instructions anywhere in the action columns
        for text in action_texts(shot):
            hit = next((w for w in hold_words if w in text), None)
            if hit:
                failures.append(f"R5B_ACTION_HOLD_INSTRUCTION:{sid}:{hit}")
                break
        if not dialogue:
            m["no_dialogue_shots"] += 1
            # a shot carrying V.O. narration is not a silent hold; the S2 V.O. window rule times it
            if target > NO_DIALOGUE_SHOT_MAX_S and not shot.get("_voice_over_lines"):
                failures.append(f"R5C_NO_DIALOGUE_SHOT_OVER_5S:{sid}:{target:g}")
            if shot.get("scene_id") != prev_scene:
                prev_scene, run_word, run_len = shot.get("scene_id"), None, 0
            continue
        m["dialogue_shots"] += 1
        cps = (shot.get("dialogue_delivery") or {}).get("chinese_characters_per_second")
        derived = derived_dialogue_seconds(dialogue, cps)
        m["derived_seconds_by_shot"][sid] = derived
        # 5a — the shot length follows the line
        if target > max(derived + TEMPLATE_TOLERANCE_S, floor_s) + 1e-9:
            failures.append(f"R5A_DIALOGUE_SHOT_TEMPLATE_DURATION:{sid}:{target:g}>{derived:g}")
        elif target + 1e-9 < derived:
            failures.append(f"R5A_DIALOGUE_SHOT_TOO_SHORT:{sid}:{target:g}<{derived:g}")
        # 7b — performance triad
        perf = action.get("performance") if isinstance(action.get("performance"), dict) else None
        if not perf:
            failures.append(f"R7B_PERFORMANCE_MISSING:{sid}")
            emotion = None
        else:
            for field in ("emotion", "body_action", "delivery"):
                if not str(perf.get(field) or "").strip():
                    failures.append(f"R7B_PERFORMANCE_INCOMPLETE:{sid}:{field}")
            emotion = str(perf.get("emotion") or "").strip() or None
            body = str(perf.get("body_action") or "").strip()
            # 5c — a real, ongoing body action
            if body and (body in trivial or any(body == t or body.startswith(t) and len(body) <= len(t) + 1 for t in trivial)):
                failures.append(f"R5C_DIALOGUE_SHOT_WITHOUT_BODY_ACTION:{sid}:{body}")
            # 7c — closed emotion set
            if emotion and emotion not in emotions:
                failures.append(f"R7C_EMOTION_NOT_IN_LEXICON:{sid}:{emotion}")
        # 7c — three in a row inside one scene
        scene = shot.get("scene_id")
        if scene != prev_scene:
            prev_scene, run_word, run_len = scene, None, 0
        if emotion and emotion == run_word:
            run_len += 1
            if run_len > CONSECUTIVE_EMOTION_MAX:
                failures.append(f"R7C_EMOTION_REPEATED_3_IN_SCENE:{scene}:{emotion}:{sid}")
        else:
            run_word, run_len = emotion, 1 if emotion else 0
        m["emotions_by_scene"].setdefault(str(scene), []).append(emotion)
        # 7d — children are not slowed down
        speaker = str(((spec.get("role_semantic_disambiguation") or {}).get("dialogue_speaker_id")) or "")
        if speaker in children and cps is not None and float(cps) < CHILD_CPS_MIN:
            failures.append(f"R7D_CHILD_SPEECH_RATE_TARGET_LOW:{sid}:{float(cps):g}")

    # rule 8 — only when the line owner authorised compression
    r8: list[str] = []
    ps = contract.get("pressure_source") if isinstance(contract.get("pressure_source"), dict) else None
    if not ps or not str(ps.get("description") or "").strip() or not ps.get("shot_id"):
        r8.append("R8A_PRESSURE_SOURCE_MISSING")
    else:
        at = ps.get("at_seconds")
        if at is None or float(at) > PRESSURE_SOURCE_WINDOW_S:
            r8.append(f"R8A_PRESSURE_SOURCE_LATE:{at}")
        if str(ps.get("kind") or "") not in {"PURSUIT", "LOSS_IMMINENT", "DEADLINE", "ARRIVAL"}:
            r8.append(f"R8A_PRESSURE_SOURCE_NOT_CONCRETE:{ps.get('kind')}")
    ep = contract.get("episode_payoff") if isinstance(contract.get("episode_payoff"), dict) else None
    if not ep or str(ep.get("kind") or "") not in {"PAYOFF", "THREAT_ADVANCES"} or not ep.get("shot_id"):
        r8.append("R8B_EPISODE_PAYOFF_MISSING")
    chain = contract.get("action_chain") if isinstance(contract.get("action_chain"), dict) else None
    if not chain or not all(chain.get(k) for k in ("want_shot_id", "blocked_shot_id", "act_shot_id")):
        if not (contract.get("transitional_episode_approved") is True):
            r8.append("R8C_ACTION_CHAIN_MISSING")
    if rule8:
        failures.extend(r8)
    else:
        warnings.extend(f"RULE8_NOT_AUTHORISED_INFO:{code}" for code in r8)

    # R9 (D-68, Roger seq=36 2026-09-18) — posture continuity: inside a scene the next shot's entry
    # posture must be the previous shot's exit posture; the change happens INSIDE the next shot.
    r9_fail, r9_warn = posture_continuity_failures(contract.get("shots") or [])
    failures.extend(r9_fail)
    warnings.extend(r9_warn)

    # R10 (Roger 2026-09-28, E09 声线漂移) — a dialogue shot's action text must not tell the model
    # to change the voice itself (压着嗓子 / 扯着嗓子 / 声音发颤 …).  Words from
    # configs/VOICE_TIMBRE_LOCK_V1.json; non-blocking unless the config or the contract's
    # voice_timbre_policy.enforced says so.  The SD2 renderer turns each hit into a tone-only clause.
    r10 = voice_timbre_findings(contract)
    m["voice_timbre_terms_by_shot"] = r10["by_shot"]
    (failures if r10["blocking"] else warnings).extend(r10["codes"])

    # R11 (CAMERA_GRAMMAR_V1 only, never blocks).  Owner 2026-11-02 (lab 化神 E01): a short line is fine -- the
    # writer keeps the source's line and never pads it to the 4 s floor; S7 cuts to the performance.  Advisory only.
    advisories: list[str] = []
    r11 = short_speaking_line_warnings(contract)
    if r11:
        m["short_speaking_lines"] = r11
        advisories.extend(f"R11_SHORT_LINE_OK_S7_CUTS:{row['shot_id']}:{row['estimated_seconds']:g}" for row in r11)

    # R12 (owner 2026-11-01, lab E12 long take; CAMERA_GRAMMAR_V1 only, never blocks) — one speaker's consecutive
    # lines are one take (same locked setup, no cut, <= 12 s); a longer monologue gets a silent cutaway
    r12 = monologue_warnings(contract)
    if r12:
        m["monologue_warnings"] = r12
        warnings.extend(r12)

    # R13 FIGHT_DESIGN_V1 (Roger 2026-11-07「以后的打斗片段，生产线都能学会怎么生产，不要再犯同类错误」):
    # the writer sees the fight rules while writing (docs/knowledge/FIGHT_DIRECTION_PLAYBOOK.md); S1
    # static_design_gate enforces the same rules whether or not this self-check is enforced.
    try:
        _repo_tools = str(Path(__file__).resolve().parents[4] / "tools")
        if _repo_tools not in _sys.path:
            _sys.path.append(_repo_tools)
        import fight_design_gate as _fdg
        fight = _fdg.evaluate(contract)
    except Exception as exc:  # noqa: BLE001 - the gate module is optional for old checkouts
        fight = {"status": f"UNAVAILABLE:{type(exc).__name__}", "failures": []}
    if fight.get("status") == "BLOCK":
        m["fight_design"] = fight
        failures.extend(f"R13_{row['code']}:{row.get('shot_id') or row.get('scene_id') or ','.join(row.get('shot_ids') or [])}"
                        for row in fight["failures"])

    status = "PASS" if not failures else "FAIL"
    return {"schema": SCHEMA, "episode": contract.get("episode"), "authority": "SUPERVISOR_ORDERS seq=29 (Roger 2026-09-18 memo 九–十四)",
            "declared": bool(decl), "enforced": enforced, "rule8_authorized": rule8,
            "status": status, "failures": failures, "warnings": warnings,
            **({"advisories": advisories} if advisories else {}), "measurements": m,
            "note": "writer-layer self-check, no gate_id; enforced only when the contract declares writer_selfcheck_seq29.enforced"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--lexicon", default=None)
    a = ap.parse_args()
    report = evaluate(json.loads(Path(a.contract).read_text(encoding="utf-8")), load_lexicon(Path(a.lexicon)) if a.lexicon else None)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "enforced": report["enforced"], "failures": len(report["failures"]), "warnings": len(report["warnings"])}, ensure_ascii=False))
    return 3 if (report["enforced"] and report["status"] == "FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
