#!/usr/bin/env python3
"""L3 -> H3 carry report (CHANGE_SPEC WP4 acceptance; report only, never a gate).

For every shot of a generation contract, the English twins the writer authored for what the screenplay says
(``action.business_en`` / ``performance.business_en``, ``listener_reaction_en``, ``lead_in_reaction_en``, prop
``description_en`` / ``english_name``) are reduced to their content words (nouns and verbs, >= 4 letters, no stop
words), and each word is looked up in the rendered H3 prompt of the unit that carries the shot.  The share of words
found is the noun carry; the WP4 acceptance is >= 95 %.

    python3 tools/check_l3_to_h3_carry.py --contract <EP>_GENERATION_CONTRACT.json \
        --grouped-manifest <grouped manifest .json> --prompt-dir <dir of <unit_id>.txt> [--out report.json] \
        [--min-carry 0.95 --require]

Exit 0 unless ``--require`` is given and the carry is below ``--min-carry``.  Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "nalu.l3_to_h3_carry.v1"
MIN_CARRY = 0.95
STOP = {
    "with", "that", "this", "then", "from", "into", "onto", "over", "under", "again", "still", "while", "their",
    "them", "they", "there", "where", "when", "what", "which", "your", "very", "just", "once", "only", "each",
    "both", "other", "another", "before", "after", "about", "around", "slowly", "quickly", "himself", "herself",
    "itself", "away", "back", "down", "toward", "towards", "across", "against", "between", "through", "without",
    "first", "seconds", "second", "speaking", "speaks", "line", "beat", "shot", "frame", "camera", "does", "keeps",
    "keep", "stays", "stay", "eyes", "hand", "hands", "face",
}
WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")


def _texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(v) for v in value.values() if isinstance(v, str)]
    return [str(value)] if isinstance(value, str) and value.strip() else []


def shot_twins(shot: dict[str, Any]) -> dict[str, list[str]]:
    """{field: [English texts]} of one contract shot."""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    performance = action.get("performance") if isinstance(action.get("performance"), dict) else {}
    out = {
        "business_en": _texts(action.get("business_en")) or _texts(performance.get("business_en")),
        "listener_reaction_en": _texts(action.get("listener_reaction_en")),
        "lead_in_reaction_en": _texts(action.get("lead_in_reaction_en")),
        "props": [t for prop in spec.get("props") or [] if isinstance(prop, dict)
                  for t in _texts(prop.get("description_en") or prop.get("english_name"))],
    }
    return {k: v for k, v in out.items() if v}


def content_words(text: str) -> list[str]:
    words = [w.lower().strip("'-") for w in WORD.findall(text)]
    return list(dict.fromkeys(w for w in words if w not in STOP and not w.endswith("'s")))


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def carry(contract: dict[str, Any], prompts_by_shot: dict[str, str]) -> dict[str, Any]:
    """The report: per shot, which twin words reached its unit prompt; ``carry`` = found / words."""
    rows = []
    found_total = words_total = 0
    for shot in contract.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        sid = str(shot.get("shot_id") or "")
        prompt = prompts_by_shot.get(sid)
        twins = shot_twins(shot)
        if prompt is None or not twins:
            continue
        low = prompt.lower()
        missing: dict[str, list[str]] = {}
        n = f = 0
        for field, texts in twins.items():
            for word in content_words(" ".join(texts)):
                n += 1
                if re.search(r"\b" + re.escape(_stem(word)), low):
                    f += 1
                else:
                    missing.setdefault(field, []).append(word)
        rows.append({"shot_id": sid, "words": n, "found": f, "missing": missing})
        found_total += f
        words_total += n
    share = round(found_total / words_total, 4) if words_total else None
    return {"schema": SCHEMA, "report_only": True, "shots_checked": len(rows), "words": words_total,
            "found": found_total, "carry": share, "target": MIN_CARRY,
            "status": ("NOT_APPLICABLE" if share is None else "PASS" if share >= MIN_CARRY else "BELOW_TARGET"),
            "shots": rows}


def prompts_from(manifest: dict[str, Any], prompt_dir: Path) -> dict[str, str]:
    """shot id -> the rendered prompt text of the unit that carries it (``<prompt_dir>/<unit_id>.txt``)."""
    out: dict[str, str] = {}
    for unit in manifest.get("units") or []:
        if not isinstance(unit, dict):
            continue
        path = prompt_dir / f"{unit.get('unit_id')}.txt"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        shot_ids = [str(s.get("shot_id")) for s in unit.get("ordered_prompt_specs") or [] if isinstance(s, dict)]
        shot_ids += [str(s) for s in unit.get("shot_ids") or []]
        for sid in shot_ids:
            if sid and sid != "None":
                out[sid] = out.get(sid, "") + "\n" + text
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--grouped-manifest", type=Path, required=True)
    parser.add_argument("--prompt-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--min-carry", type=float, default=MIN_CARRY)
    parser.add_argument("--require", action="store_true", help="exit 1 when the carry is below --min-carry")
    args = parser.parse_args(argv)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    manifest = json.loads(args.grouped_manifest.read_text(encoding="utf-8"))
    report = carry(contract, prompts_from(manifest, args.prompt_dir))
    report["target"] = args.min_carry
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if args.require and report["carry"] is not None and report["carry"] < args.min_carry else 0


if __name__ == "__main__":
    raise SystemExit(main())
