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

The check is a WRITER-LAYER self-check: it carries no gate_id.  It is enforced (S1 refuses to enter
S2) only when the contract declares ``writer_selfcheck_seq29.enforced: true`` (E06+ builders);
older contracts get a diagnostic report.  Exit 0 PASS / not enforced, 3 enforced FAIL.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import nalu_prompt_rules as npr  # noqa: E402

import argparse  # noqa: E402
import json  # noqa: E402
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
    return text.split("：", 1)[1] if "：" in text[:8] else text


def derived_dialogue_seconds(dialogue: str, cps: float | None) -> float:
    """Rule 5a: line seconds + 0.5, rounded UP to 0.5 s (10 chars @ 5.0 → 2.5 s)."""
    return npr.min_dialogue_seconds(_spoken(dialogue), cps)


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


def evaluate(contract: dict[str, Any], lexicon: dict[str, Any] | None = None) -> dict[str, Any]:
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
            if target > NO_DIALOGUE_SHOT_MAX_S:
                failures.append(f"R5C_NO_DIALOGUE_SHOT_OVER_5S:{sid}:{target:g}")
            if shot.get("scene_id") != prev_scene:
                prev_scene, run_word, run_len = shot.get("scene_id"), None, 0
            continue
        m["dialogue_shots"] += 1
        cps = (shot.get("dialogue_delivery") or {}).get("chinese_characters_per_second")
        derived = derived_dialogue_seconds(dialogue, cps)
        m["derived_seconds_by_shot"][sid] = derived
        # 5a — the shot length follows the line
        if target > derived + TEMPLATE_TOLERANCE_S + 1e-9:
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

    status = "PASS" if not failures else "FAIL"
    return {"schema": SCHEMA, "episode": contract.get("episode"), "authority": "SUPERVISOR_ORDERS seq=29 (Roger 2026-09-18 memo 九–十四)",
            "declared": bool(decl), "enforced": enforced, "rule8_authorized": rule8,
            "status": status, "failures": failures, "warnings": warnings, "measurements": m,
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
