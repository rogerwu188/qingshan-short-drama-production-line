#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt_batch_qa.py — whole-batch prompt QA for one episode (nalu line).

Two halves, kept separate on purpose:

1. ``digest``  — deterministic cross-checks of every keyframe prompt and planned video prompt
   against the generation contract, the wardrobe bible, the global space map and the grouping
   plan, plus a compact per-unit digest (the semantic lines only: entry state, cast, wardrobe,
   scene state, dialogue, timeline, camera, transition) that a Claude reviewer reads in full.
   The boilerplate blocks (visual culture profile, forbidden list, reference-usage rules) are
   compared byte-for-byte across all prompts instead of being re-read 27 times.

2. ``receipts`` — writes one ``<unit>.json`` receipt per row in the exact shape
   tools/episode_prompt_batch_gate.py verifies, taking the reviewer's per-unit verdicts and
   observations from an answers file.  A unit whose deterministic checks failed, or whose
   reviewer verdict is not PASS, gets ``status: FAIL`` and the gate holds.

The gate verifies evidence; this tool records it.  It never writes PASS on its own.
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
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(f"{_np.ENGINE_ROOT}")
RUNTIME = Path(f"{_np.RUNTIME_ROOT}")
WORK = Path(os.environ.get("NALU_WORK_ROOT", str(_np.RUNTIME_ROOT / "workflow" / "nalu"))).expanduser().resolve()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ENGINE.resolve()))
    except ValueError:
        return str(resolved)


def section(text: str, header: str) -> str:
    """Text of a 【header】 block up to the next 【."""
    m = re.search(r"【" + re.escape(header) + r"[^】]*】\s*(.*?)(?=\n【|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def foreign_dialogue(text: str, dialogue_by_shot: dict, unit_shots: list) -> list[str]:
    """A transition never exempts out-of-scope dialogue from pre-submit QA."""
    local = {line.split("：", 1)[1] for sid in unit_shots
             for line in dialogue_by_shot.get(sid, [])}
    return sorted({line.split("：", 1)[1]
                   for sid, lines in dialogue_by_shot.items() if sid not in unit_shots
                   for line in lines
                   if line.split("：", 1)[1] not in local
                   and len(line.split("：", 1)[1]) > 4
                   and line.split("：", 1)[1] in text})


#: Tokens that mean "an outer garment made of hide": 兽皮大衣 / 裘氅 / 兽皮短袄 / 皮袄.
HIDE_COAT_TOKENS = ("兽皮", "裘氅", "皮袄")
#: Words that negate a hide coat inside one wardrobe field.  The check below uses these to
#: strip negated spans before deciding whether the field asks for fur at all.
HIDE_COAT_NEGATIONS = ("不披", "不带", "没有", "无", "非", "不要")
#: A fur/hide HAT is not an outer coat (E03 兽皮护耳帽 / 皮帽).
HIDE_COAT_HAT_TOKENS = r"兽皮护耳帽|皮护耳帽|兽皮帽|皮帽"
#: A denial together with the garment words it scopes over.  The denial must swallow the whole
#: phrase: 不披兽皮裘氅 is one denial of one garment, and stripping only 「不披兽皮」 would leave
#: a bare 「裘氅」 behind and read the denial as a requirement.  A negation scoped to a different
#: garment (「无毛领的兽皮大衣」) still leaves its coat standing: 的 breaks the run and the coat
#: is not in the denial's word class.
HIDE_COAT_DENIAL_RE = re.compile(
    r"(?:不披|不带|不穿|没有|无|非)(?:兽皮|裘氅|毛领|皮袄|皮草|外披|外衣|大衣|衣)+")
#: Outside a denial run a negation must sit immediately before the token.  A looser window
#: would clear a real coat through a negation that addresses a different garment.
HIDE_COAT_NEGATION_MAX_GAP = 1


def mentions_hide_coat(text: str) -> bool:
    """True when the field asks for a hide/fur OUTER coat, not when it denies one.

    nalu E11 秦铭 renders 「…都不披兽皮裘氅、不带毛领…」 while the E01 library row said
    「陈旧兽皮大衣（外层…）」.  The old check scanned for the bare token 裘氅 and read the
    denial as a requirement, so the gate compared True against a correctly-plain line.
    Hat tokens are stripped too (E03 兽皮护耳帽).
    """
    value = re.sub(HIDE_COAT_HAT_TOKENS, "", str(text or ""))
    value = HIDE_COAT_DENIAL_RE.sub("", value)
    for clause in re.split(r"[；;，,。、（）()]", value):
        for token in HIDE_COAT_TOKENS:
            start = 0
            while True:
                found = clause.find(token, start)
                if found < 0:
                    break
                window = clause[max(0, found - HIDE_COAT_NEGATION_MAX_GAP):found]
                if not any(negation in window for negation in HIDE_COAT_NEGATIONS):
                    return True
                start = found + len(token)
    return False


def wardrobe_expectation(spec, name, bible_row):
    overrides = spec.get('wardrobe_state_overrides') or {}
    ids = [c.get('character_id') for c in spec.get('cast', [])
           if name in {c.get('character'), c.get('canonical_name')}]
    if bible_row.get('character_id'):
        ids.append(bible_row['character_id'])
    values = {str(overrides[cid]).strip() for cid in ids if overrides.get(cid)}
    if len(values) > 1:
        raise ValueError('AMBIGUOUS_WARDROBE_OVERRIDE:'+name)
    if values:
        value = next(iter(values))
        return value, value
    authored = str(bible_row.get('authored_description') or '')
    return authored.split('；')[0][:12], str(bible_row.get('outer_layer') or '')


def load(ep: str, *, preproduction_dir=None, contract_file=None):
    pre = Path(preproduction_dir).resolve() if preproduction_dir else WORK / ep / "preproduction"
    contract_candidates = [
        RUNTIME / "adapter" / ep / f"{ep}_GENERATION_CONTRACT_v1.json",
        ENGINE / "workflow/claude_writer_agent/scripts" / f"{ep}_GENERATION_CONTRACT_v1.json",
    ]
    contract_path = Path(contract_file).resolve() if contract_file else next((p for p in contract_candidates if p.is_file()), None)
    if contract_path is None:
        raise FileNotFoundError(f"no generation contract found for {ep}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    editorial = json.loads((pre / f"{ep}_EDITORIAL_SEEDANCE_MANIFEST_V1.json").read_text(encoding="utf-8"))
    ed_by_shot = {s["shot_id"]: s for s in editorial["shots"]}
    for shot in contract["shots"]:  # props live in the editorial spec, cast in both
        shot["prompt_spec"]["props"] = ed_by_shot[shot["shot_id"]]["prompt_spec"].get("props") or []
        if not shot["prompt_spec"].get("cast"):
            shot["prompt_spec"]["cast"] = ed_by_shot[shot["shot_id"]]["prompt_spec"].get("cast") or []
    grouping = json.loads((pre / f"{ep}_VIDEO_UNIT_GROUPING_PLAN_V1.json").read_text(encoding="utf-8"))
    for scene in contract.get("scene_states") or []:
        scene.setdefault("weather", scene.get("weather_state") or "")
        scene.setdefault("time_id", scene.get("time_block_id") or scene.get("time_of_day_state") or "")
        scene.setdefault("lighting", scene.get("lighting_state") or scene.get("lighting") or "")
    batch = json.loads((pre / f"{ep}_PROMPT_BATCH_V1.json").read_text(encoding="utf-8"))
    gsm = json.loads((RUNTIME / "preproduction" / ep / "global_space_map.json").read_text(encoding="utf-8"))
    return pre, contract, grouping, batch, gsm


def digest(ep: str, out: Path, **input_paths) -> dict:
    pre, contract, grouping, batch, gsm = load(ep, **input_paths)
    shots = {s["shot_id"]: s for s in contract["shots"]}
    scenes = {s["scene_id"]: s for s in contract["scene_states"]}
    units = {u["unit_id"]: u for u in grouping["units"]}
    bible = {r["character"]: r for r in grouping["wardrobe_bible"]["characters"]}
    for row in list(bible.values()):
        for alias in (row.get("aliases") or []):
            bible.setdefault(alias, row)
    # v4 uses the short display name in a few shots while the wardrobe bible
    # keeps the canonical role name.  This is an explicit authored alias, not
    # a fuzzy name guess.
    if "迎客姑娘" in bible:
        bible.setdefault("侍女", bible["迎客姑娘"])
    if "白鲤郡主" in bible:
        bible.setdefault("白鲤", bible["白鲤郡主"])
    elif "白鲤" in bible:
        # v4 grouping plans may retain the short authored display name while
        # shot contracts use the canonical title.  This is an explicit alias,
        # not fuzzy identity matching.
        bible.setdefault("白鲤郡主", bible["白鲤"])
    id2name = {e["character_id"]: e["canonical_name"] for e in contract["character_entities"]}
    rooms = {(m["global_space_map_id"], r["room_id"]) for m in gsm["space_maps"] for r in m.get("rooms", [])}
    dialogue_by_shot: dict[str, list[str]] = {}
    for d in contract["audio_contract"]["dialogue_units"]:
        speaker_name = id2name.get(d.get("speaker_id")) or d.get("speaker")
        if not speaker_name:
            # V4 legacy dialogue IDs are scoped labels; resolve only through
            # the authored display field, never by guessing from an ID suffix.
            speaker_name = str(d.get("speaker_id") or "UNRESOLVED")
        dialogue_by_shot.setdefault(d["shot_id"], []).append(f"{speaker_name}：{d['text']}")
    # boilerplate identity across prompts
    boiler_kf: dict[str, set] = {"视觉文化档案": set(), "严格禁止": set(), "参考图用途": set()}
    boiler_vp: dict[str, set] = {"限制": set()}
    rows = []
    for row in batch["rows"]:
        uid = row["unit_id"]
        kf_text = (ENGINE / row["keyframe_prompt"]["path"]).read_text(encoding="utf-8")
        vp_text = (ENGINE / row["video_prompt"]["path"]).read_text(encoding="utf-8")
        shot_id = row["keyframe_prompt"]["shot_id"]
        shot = shots[shot_id]
        unit = units.get(uid) or units[row.get("parent_unit_id")]
        checks = []
        derived = (row["keyframe_prompt"].get("derivation") or {}).get("kind")
        if derived:
            checks.append({"id": "kf_prompt_continuity_derived_from_previous_unit", "status": "PASS",
                           "detail": f"{derived}: keyframe checks not applicable; start frame is materialised from {row['keyframe_prompt']['derivation'].get('previous_unit_id')} real tail"})
        def chk(cid, ok, detail=""):
            if derived and cid.startswith("kf_"):
                return
            checks.append({"id": cid, "status": "PASS" if ok else "FAIL", "detail": detail})
        # keyframe prompt checks
        chk("kf_entry_state_verbatim", shot["entry_state"] in kf_text, shot["entry_state"])
        # Keep the authored display alias used by the rendered prompt; the
        # wardrobe bible above resolves 白鲤/白鲤郡主 explicitly.
        cast_names = [c["character"] for c in shot["prompt_spec"]["cast"]
                      if c.get("first_frame_visible", True) is not False]
        cast_names = list(dict.fromkeys(cast_names))
        allowed = re.search(r"本帧允许入画的人物[^\n]*：([^\n]*)", kf_text)
        allowed_names = [x.lstrip("、，, ") for x in re.findall(r"([^（）]+)（[^）]+）", allowed.group(1))] if allowed else []
        chk("kf_visible_cast_equals_contract", sorted(allowed_names) == sorted(cast_names), f"{allowed_names} vs {cast_names}")
        for name in cast_names:
            b = bible[name]
            ward_line = re.search(rf"- {re.escape(name)}（[^）]*）：([^\n]*)", kf_text)
            chk(f"kf_wardrobe_line_present:{name}", bool(ward_line), "")
            if ward_line:
                # the keyframe line is rendered from the bible's authored_description
                # (asset_requirements WARD-* text); compare against that and against the
                # hide-coat presence implied by outer_layer
                line = ward_line.group(1)
                head, expected_outer = wardrobe_expectation(shot['prompt_spec'], name, b)
                chk(f"kf_wardrobe_authored_text:{name}", bool(head) and head in line, f"{head!r} in line")
                # E04: 皮袄 (a hide jacket) and 裘氅 are hide coats too — the line-side test already counts them
                # K085: read the FIELD with the same negation-aware test as the line.  A denial
                # (「无外披（全集不披裘氅、不带毛领…）」) is not a requirement for fur.
                hide_expected = mentions_hide_coat(expected_outer)
                # E03: a fur/hide HAT (兽皮护耳帽 / 皮帽) is not an outer coat — the helper strips hats
                hide_in_line = mentions_hide_coat(line)
                chk(f"kf_wardrobe_hide_coat_consistent:{name}", hide_expected == hide_in_line, f"expected={hide_expected} line={hide_in_line}")
        sc = scenes[shot["scene_id"]]
        chk("kf_time_id", f"时间：{sc['time_id']}" in kf_text, sc["time_id"])
        scene_expected = sc
        projection_ref = row['keyframe_prompt'].get('scene_state_projection_ref')
        if projection_ref:
            from tools.keyframe_entry_scene_projection import validate_projection
            try:
                scene_expected = validate_projection(projection_ref, shot=shot, scene=sc, prompt_text=kf_text)
                chk('kf_entry_scene_projection', True, str(projection_ref))
            except (ValueError, KeyError, OSError, TypeError) as exc:
                chk('kf_entry_scene_projection', False, str(exc))
        chk("kf_weather", scene_expected["weather"] in kf_text, scene_expected["weather"])
        chk("kf_lighting", scene_expected["lighting"] in kf_text, scene_expected["lighting"][:30])
        loc = re.search(r"地点：(LOC-[A-Z0-9-]+)｜房间：(ROOM-[A-Z0-9-]+)", kf_text)
        gm = re.search(r"→ (GSM-[A-Z0-9-]+) → SUBSPACE", kf_text)
        chk("kf_location_matches_scene", bool(loc) and loc.group(1) == sc["location_id"], loc.group(1) if loc else "")
        chk("kf_room_exists_in_gsm", bool(loc and gm and loc.group(2) in kf_text), f"{gm.group(1) if gm else ''}/{loc.group(2) if loc else ''}")
        chk("kf_no_completion_state_leak", shot["completion_state"] not in section(kf_text, "entry_state") , shot["completion_state"][:30])
        chk("kf_9_16_and_no_text_rule", "9:16" in kf_text and "不得出现任何文字" in kf_text, "")
        # K087: an authored-prose gap must never reach the provider.  When the writer leaves a
        # wardrobe/voice/space field unfilled, the asset build inherits whatever the prior
        # library held — and for a character whose description was never authorised that is the
        # sentinel itself.  nalu E11 刘老头 rendered
        # 「AUTHORING_REQUIRED_WARDROBE_STATE_DESCRIPTION；拄着木杖…」 into the paid keyframe
        # prompt.  The build report calls this PASS, so nothing upstream stops it.
        sentinels = sorted(set(re.findall(r"AUTHORING_REQUIRED_[A-Z_]+", kf_text + "\n" + vp_text)))
        chk("kf_no_authoring_required_sentinel", not sentinels, ",".join(sentinels))
        for h in boiler_kf:
            boiler_kf[h].add(section(kf_text, h))
        # video prompt checks
        unit_shots = unit["editorial_shot_ids"]
        for sid in unit_shots:
            s = shots[sid]
            chk(f"vp_start_state_present:{sid}", s["entry_state"] in vp_text, s["entry_state"][:30])
            chk(f"vp_completion_state_present:{sid}", s["completion_state"] in vp_text, s["completion_state"][:30])
            for line in dialogue_by_shot.get(sid, []):
                spoken = line.split("：", 1)[1]
                chk(f"vp_dialogue_verbatim:{sid}", spoken in vp_text, spoken[:30])
        leaked = foreign_dialogue(vp_text, dialogue_by_shot, unit_shots)
        chk("vp_no_foreign_dialogue", not leaked, str(leaked[:2]))
        vp_cast = set()
        for sid in unit_shots:
            vp_cast.update(c["character"] for c in shots[sid]["prompt_spec"]["cast"])
        for name in vp_cast:
            chk(f"vp_cast_named:{name}", name in vp_text, "")
        chk("vp_duration_declared", str(int(round(unit["duration_seconds"]))) in vp_text or f"{unit['duration_seconds']}" in vp_text, str(unit["duration_seconds"]))
        chk("vp_required_sections", all(h in vp_text for h in ("【任务】", "【锚点】", "【时间轴】", "【摄影】", "【声音】", "【限制】")), "")
        chk("vp_rune_limit", len(vp_text) <= 10000, str(len(vp_text)))
        boiler_vp["限制"].add(section(vp_text, "限制"))
        age_note = ("十六七岁" in vp_text) or ("十六七岁" in kf_text)
        rows.append({
            "unit_id": uid, "shot_id": shot_id, "editorial_shot_ids": unit_shots,
            "scene_id": shot["scene_id"], "duration_seconds": unit["duration_seconds"],
            "checks": checks, "deterministic_status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
            "notes": (["AGE_TEXT_16_17_PRESENT (casting is 20-26 per seq=5; identity comes from the locked plate reference)"] if age_note else []),
            "digest": {
                "entry_state": shot["entry_state"], "completion_state": shot["completion_state"],
                "cast": cast_names, "props": [p["prop"] for p in shot["prompt_spec"]["props"]],
                "scene": f"{sc['location_id']} | {sc['time_id']} | {sc['weather']} | {sc['lighting']}",
                "dialogue": [l for sid in unit_shots for l in dialogue_by_shot.get(sid, [])],
                "kf_composition": section(kf_text, "景别与摄影")[:300],
                "kf_blocking": section(kf_text, "entry 时刻站位")[:300],
                "vp_task": section(vp_text, "任务")[:400],
                "vp_timeline": section(vp_text, "时间轴")[:900],
                "vp_camera": section(vp_text, "摄影")[:300],
                "vp_sound": section(vp_text, "声音")[:300],
                "vp_anchor": section(vp_text, "锚点")[:300],
                "transition_in": (unit.get("transition_contract") or {}).get("transition_mode"),
                "internal": [c.get("transition_mode") for c in unit.get("internal_transition_contracts") or []],
            },
        })
    boiler = {f"kf:{h}": len(v) for h, v in boiler_kf.items()} | {f"vp:{h}": len(v) for h, v in boiler_vp.items()}
    report = {"schema": "nalu.prompt_batch_digest.v1", "episode": ep, "execution_id": batch["execution_id"],
              "generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
              "boilerplate_variants": boiler,
              "deterministic_summary": {"rows": len(rows), "fail": sum(1 for r in rows if r["deterministic_status"] != "PASS")}}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def receipts(ep: str, digest_path: Path, answers_path: Path, out_dir: Path, **input_paths) -> dict:
    pre, contract, grouping, batch, gsm = load(ep, **input_paths)
    dg = json.loads(digest_path.read_text(encoding="utf-8"))
    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    by_uid = {r["unit_id"]: r for r in dg["rows"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    written, failed = [], []
    for row in batch["rows"]:
        uid = row["unit_id"]
        d = by_uid[uid]
        a = answers["units"].get(uid)
        if not a:
            failed.append(f"{uid}:NO_REVIEWER_ANSWER"); continue
        status = "PASS" if d["deterministic_status"] == "PASS" and a.get("verdict") == "PASS" else "FAIL"
        receipt = {
            "schema": "nalu.prompt_batch_qa_receipt.v1",
            "status": status,
            "execution_id": batch["execution_id"],
            "unit_id": uid,
            "keyframe_prompt_sha256": row["keyframe_prompt"]["sha256"],
            "video_prompt_sha256": row["video_prompt"]["sha256"],
            "scope": "PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY",
            "cross_unit_continuity_checked": bool(a.get("cross_unit_continuity_checked", False)),
            "reviewer": answers.get("reviewer"), "review_method": answers.get("review_method"),
            "reviewed_at": answers.get("reviewed_at"),
            "deterministic_checks": d["checks"],
            "deterministic_status": d["deterministic_status"],
            "reviewer_verdict": a.get("verdict"),
            "reviewer_observation": a.get("observation"),
            "reviewer_defects": a.get("defects", []),
            "notes": d.get("notes", []),
            "digest_sha256": sha(digest_path),
        }
        (out_dir / f"{uid}.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append((uid, status))
        if status != "PASS":
            failed.append(f"{uid}:{status}")
    summary = {"written": len(written), "pass": sum(1 for _, s in written if s == "PASS"), "failed": failed}
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("digest"); d.add_argument("--episode", required=True); d.add_argument("--out", required=True)
    r = sub.add_parser("receipts"); r.add_argument("--episode", required=True); r.add_argument("--digest", required=True)
    r.add_argument("--answers", required=True); r.add_argument("--out-dir", required=True)
    for parser in (d, r):
        parser.add_argument("--preproduction-dir", help="Explicit isolated repair inputs; default unchanged")
        parser.add_argument("--contract-file", help="Explicit approved/repaired contract; no fallback if missing")
    args = ap.parse_args()
    input_paths = dict(preproduction_dir=args.preproduction_dir, contract_file=args.contract_file)
    if args.cmd == "digest":
        rep = digest(args.episode, Path(args.out), **input_paths)
        print(json.dumps({"rows": rep["deterministic_summary"], "boilerplate_variants": rep["boilerplate_variants"]}, ensure_ascii=False))
        return 0
    s = receipts(args.episode, Path(args.digest), Path(args.answers), Path(args.out_dir), **input_paths)
    return 0 if not s["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
