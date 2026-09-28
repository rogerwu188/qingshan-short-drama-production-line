#!/usr/bin/env python3
"""unit_voice_consistency — S6 post-generation per-unit voice check (VOICE_TIMBRE_LOCK, E10+).

Roger 2026-09-28: E09's voices 「飘来飘去」.  The final-cut ``voice_distinctness`` detector saw it
(秦铭 per-scene F0 median 119–250 Hz against a 173–234 Hz band) but only after assembly, and a
final-cut failure cannot point at the unit to reroll.  This check measures every dialogue unit
right after generation, with the SAME measurement and band as the final-cut detector:

  * F0: ``tools/dialogue_voice_metrics.measure_segments`` over the unit's own ASR segments;
  * band: ``voice_cast.json`` ``characters.<id>.f0_band_hz`` (reference F0 median ±15 %),
    widened only by ``postgen_voice_consistency.band_extra_tolerance_ratio`` in
    ``configs/VOICE_TIMBRE_LOCK_V1.json`` (default 0 = the detector's own band).

Speaker attribution: a one-speaker unit owns all of its segments; in a multi-speaker unit each
ASR segment goes to the expected line it matches best (text similarity >= min_attribution_similarity
and a clear margin over the runner-up).  Anything that cannot be attributed or measured is
UNVERIFIED — never PASS.  Status: FAIL > UNVERIFIED > PASS; NOT_APPLICABLE for a unit with no line.

CLI (read-only, for offline validation of an already-generated episode):
    unit_voice_consistency.py --episode E09 --out /tmp/E09_voice_consistency.json
reads each unit's existing ``<unit>_source_video_dialogue_gate.json`` segments; writes only --out.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from statistics import median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nalu_qa_common import ENGINE, Expectations, QaPaths, engine_module, read_json, write_json  # noqa: E402

SCHEMA = "nalu.unit_voice_consistency.v1"
TOOL_ID = "unit_voice_consistency.v1"
ATTRIBUTION_MARGIN = 0.15


def _vtl():
    return engine_module("voice_timbre_lock")


def check_policy() -> dict[str, Any]:
    return (_vtl().load_policy().get("postgen_voice_consistency") or {})


def active_for(episode: str) -> bool:
    vtl = _vtl()
    return vtl.active_for(episode) and bool(check_policy().get("enabled"))


def _norm(text: str) -> str:
    try:
        import opencc  # type: ignore
        text = opencc.OpenCC("t2s").convert(text)
    except Exception:  # noqa: BLE001
        pass
    return re.sub(r"[\W_]+", "", str(text or ""))


def expected_lines(expected_dialogue: list[dict[str, Any]], name_to_id: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for row in expected_dialogue:
        raw = str(row.get("spoken_text") or "")
        name, sep, words = raw.partition("：")
        if not sep:
            continue
        rows.append({"shot_id": row.get("shot_id"), "speaker_name": name.strip(),
                     "character_id": name_to_id.get(name.strip(), ""), "text": _norm(words)})
    return rows


def attribute(segments: list[dict[str, Any]], lines: list[dict[str, Any]],
              min_similarity: float) -> list[dict[str, Any]]:
    speakers = sorted({row["character_id"] for row in lines if row["character_id"]})
    out = []
    for seg in segments:
        text = _norm(seg.get("text") or "")
        row = {"start": seg.get("start"), "end": seg.get("end"), "text": seg.get("text")}
        if not text:
            row.update(speaker=None, attribution="NO_TEXT")
        elif len(speakers) == 1:
            row.update(speaker=speakers[0], attribution="SINGLE_SPEAKER_UNIT")
        else:
            scored = sorted(((difflib.SequenceMatcher(None, text, line["text"]).ratio(), line["character_id"])
                             for line in lines if line["character_id"]), reverse=True)
            best = scored[0] if scored else (0.0, "")
            second = next((s for s in scored[1:] if s[1] != best[1]), (0.0, ""))
            if best[0] >= min_similarity and best[0] - second[0] >= ATTRIBUTION_MARGIN:
                row.update(speaker=best[1], attribution="TEXT_MATCH", similarity=round(best[0], 3))
            else:
                row.update(speaker=None, attribution="AMBIGUOUS", similarity=round(best[0], 3))
        out.append(row)
    return out


def check_unit(unit_id: str, media: Path, segments: list[dict[str, Any]],
               expected_dialogue: list[dict[str, Any]], cast: dict[str, Any],
               name_to_id: dict[str, str], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = check_policy() if policy is None else policy
    extra = float(policy.get("band_extra_tolerance_ratio") or 0.0)
    code = str(policy.get("reason_code") or "VOICE_OUT_OF_BAND")
    lines = expected_lines(expected_dialogue, name_to_id)
    base = {"schema": SCHEMA, "unit_id": unit_id, "measured_by": TOOL_ID,
            "band_source": "voice_cast.f0_band_hz", "band_extra_tolerance_ratio": extra}
    if not lines:
        return {**base, "status": "NOT_APPLICABLE", "failures": [], "unverified": [], "speakers": {}}
    unverified: list[str] = []
    attributed = attribute([s for s in segments or [] if s.get("text")], lines,
                           float(policy.get("min_attribution_similarity") or 0.5))
    for row in attributed:
        if not row.get("speaker"):
            unverified.append(f"SPEAKER_UNATTRIBUTED:{row.get('start')}:{row.get('attribution')}")
    measurable = [row for row in attributed if row.get("speaker")]
    if measurable:
        dvm = engine_module("dialogue_voice_metrics")
        samples, sr = dvm.load_audio(Path(media))
        for row, metric in zip(measurable, dvm.measure_segments(samples, sr, measurable)):
            row["f0_median_hz"] = metric.get("f0_median_hz")
    characters = (cast or {}).get("characters") or {}
    failures: list[str] = []
    speakers: dict[str, Any] = {}
    for cid in sorted({row["speaker"] for row in measurable}):
        values = [float(row["f0_median_hz"]) for row in measurable
                  if row["speaker"] == cid and row.get("f0_median_hz") is not None]
        band = (characters.get(cid) or {}).get("f0_band_hz")
        if not band:
            unverified.append(f"SPEAKER_NOT_IN_VOICE_CAST:{cid}")
            continue
        if not values:
            unverified.append(f"F0_UNAVAILABLE:{cid}")
            continue
        lo, hi = float(band[0]) * (1 - extra), float(band[1]) * (1 + extra)
        f0 = round(median(values), 2)
        in_band = lo <= f0 <= hi
        speakers[cid] = {"f0_median_hz": f0, "band_hz": [round(lo, 2), round(hi, 2)],
                         "segments": len(values), "in_band": in_band}
        if not in_band:
            failures.append(f"{code}:{cid}:{f0}")
    for line in lines:
        if line["character_id"] and line["character_id"] not in speakers \
                and not any(u.endswith(line["character_id"]) for u in unverified):
            unverified.append(f"SPEAKER_NOT_MEASURED:{line['character_id']}")
    status = "FAIL" if failures else ("UNVERIFIED" if unverified else "PASS")
    return {**base, "status": status, "failures": failures, "unverified": sorted(set(unverified)),
            "speakers": speakers, "segments": attributed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--unit", action="append", default=[])
    args = parser.parse_args()
    p = QaPaths(args.episode)
    exp = Expectations(args.episode)
    cast = read_json(p.voice_cast, {}) or {}
    name_to_id = exp.character_name_to_id()
    rows = []
    for item in exp.unit_plot_items():
        uid = item["unit_id"]
        if args.unit and uid not in args.unit:
            continue
        gate = read_json(p.postgen_dir / uid / f"{uid}_source_video_dialogue_gate.json", {}) or {}
        media = ENGINE / "workflow" / "nalu" / args.episode / "video" / f"{uid}.mp4"
        rows.append(check_unit(uid, media, gate.get("segments") or [],
                               item["expectations"].get("expected_dialogue") or [], cast, name_to_id))
    summary = {"schema": SCHEMA, "episode": args.episode, "mode": "OFFLINE_READ_ONLY",
               "active_for_episode": active_for(args.episode),
               "counts": {s: sum(1 for r in rows if r["status"] == s)
                          for s in ("PASS", "FAIL", "UNVERIFIED", "NOT_APPLICABLE")},
               "units": rows}
    write_json(args.out, summary)
    print(json.dumps({"out": str(args.out), **summary["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
