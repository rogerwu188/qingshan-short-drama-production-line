#!/usr/bin/env python3
"""english_contract_forbidden_terms_lint.py — FREE pre-paid check: the English (MiniMax-H3) contract and
final prompts must not name, in English, any object the engine's closed anachronism vocabulary forbids
in the picture (Roger 2026-10-30, 提速闭环 3c).

Why: E12-VU-041 was rejected at Q2 (PERIOD_ANACHRONISM_KEROSENE_LAMP, P1) after a paid render because
the English contract translated 琉璃灯盏 (a glazed lamp dish) as "glass lamp"; the Chinese forbidden
term 玻璃罩煤油灯/煤油灯 never appears in Chinese, so the Chinese gate could not see it.  A paid reroll
(62 credits) and one review round followed.  This lint reads the English text before any POST.

Scope: tools/anachronism_lock_gate.FORBIDDEN_VISIBLE_TERMS (the engine's own closed set) + the fixed
English renderings below for the Chinese-only terms.  A hit is reported with the unit, field and the
matched phrase.  Exit 1 on any hit (fail-closed, like every other pre-paid gate); the caller decides
whether to rewrite the wording or record a line-owner exception — this tool records nothing.

    english_contract_forbidden_terms_lint.py --contracts <EP>_H3_ENGLISH_CONTRACTS.json
                                             [--prompts-dir <video_prompts dir>] [--report <json>]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# English renderings of the Chinese-only forbidden visible terms (the gate's English rows are used as-is).
EN_RENDERINGS: dict[str, list[str]] = {
    "玻璃罩煤油灯": [r"glass[- ]?(chimney|shade|cover)?\s*(kerosene|oil|paraffin)?\s*lamp", r"hurricane lamp", r"storm lantern"],
    "煤油灯": [r"kerosene lamp", r"paraffin lamp", r"oil lamp with (a )?glass", r"glass lamp"],
    "手机": [r"\bcell ?phone\b", r"\bmobile phone\b", r"\bsmartphone\b"],
    "二维码": [r"\bqr code\b"],
    "条形码": [r"\bbar ?code\b"],
    "塑料瓶": [r"\bplastic bottle\b"],
    "汽车": [r"\b(car|automobile|truck|motor vehicle)\b"],
    "麦克风": [r"\bmicrophone\b"],
    "拉链": [r"\bzipper\b", r"\bzip fastener\b"],
    "大盖帽": [r"\bpeaked cap\b", r"\bpolice cap\b"],
    "现代警服": [r"\bpolice uniform\b"],
    "诊所招牌": [r"\bclinic sign(board)?\b"],
}


def forbidden_patterns() -> list[tuple[str, re.Pattern[str]]]:
    terms: list[str] = []
    try:
        import anachronism_lock_gate as g  # type: ignore
        terms = [str(t) for t in getattr(g, "FORBIDDEN_VISIBLE_TERMS", ())]
    except Exception:  # noqa: BLE001 — the fixed renderings still apply
        terms = list(EN_RENDERINGS)
    pats: list[tuple[str, re.Pattern[str]]] = []
    for t in terms:
        if re.search(r"[A-Za-z]", t):
            pats.append((t, re.compile(r"\b" + re.escape(t) + r"\b", re.I)))
        for rx in EN_RENDERINGS.get(t, []):
            pats.append((t, re.compile(rx, re.I)))
    return pats


def _walk(value: Any, path: str):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


def lint_text(text: str, pats) -> list[dict[str, str]]:
    hits = []
    for term, rx in pats:
        m = rx.search(text)
        if m:
            s = max(0, m.start() - 40); e = min(len(text), m.end() + 40)
            hits.append({"forbidden_term": term, "matched": m.group(0), "context": text[s:e]})
    return hits


def lint_contracts(doc: dict[str, Any], pats) -> list[dict[str, Any]]:
    out = []
    units = doc.get("units") or {}
    rows = units.items() if isinstance(units, dict) else enumerate(units)
    for key, unit in rows:
        english = unit.get("english") if isinstance(unit, dict) else None
        if english is None:
            continue
        for field, text in _walk(english, "english"):
            for h in lint_text(text, pats):
                out.append({"unit": str(key), "field": field, **h})
    return out


def lint_prompt_files(prompts_dir: Path, pats) -> list[dict[str, Any]]:
    out = []
    for p in sorted(glob.glob(str(prompts_dir / "*.txt"))):
        text = Path(p).read_text(encoding="utf-8", errors="replace")
        for h in lint_text(text, pats):
            out.append({"unit": Path(p).stem, "field": "final_prompt", **h})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contracts", help="<EP>_H3_ENGLISH_CONTRACTS.json")
    ap.add_argument("--prompts-dir", help="directory of rendered final prompt .txt files")
    ap.add_argument("--report")
    args = ap.parse_args()
    if not args.contracts and not args.prompts_dir:
        print(json.dumps({"status": "ERROR", "error": "give --contracts and/or --prompts-dir"}))
        return 2
    pats = forbidden_patterns()
    hits: list[dict[str, Any]] = []
    if args.contracts:
        hits += lint_contracts(json.loads(Path(args.contracts).read_text(encoding="utf-8")), pats)
    if args.prompts_dir:
        hits += lint_prompt_files(Path(args.prompts_dir), pats)
    units = sorted({h["unit"].split("@")[0] for h in hits})
    report = {"schema": "qingshan.english_forbidden_terms_lint.v1", "status": "PASS" if not hits else "FAIL",
              "hit_count": len(hits), "units_with_hits": units, "hits": hits,
              "closed_set_size": len(pats), "network_calls_made": 0}
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "hit_count", "units_with_hits")}, ensure_ascii=False))
    for h in hits[:40]:
        print(f"  {h['unit']} {h['field']}: [{h['forbidden_term']}] …{h['context']}…")
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
