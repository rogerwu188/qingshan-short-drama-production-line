#!/usr/bin/env python3
"""DIALOGUE_REGISTER_V1 — the line a character speaks must be theirs, not the novel's.

Roger 2026-11-08 (E15 看片, order seq=219): 「对话台词也不像是剧中人说的，更像是直接照搬小说原著对话，
AI 味太重。这些错误后续不再犯。」

E15 shipped 27 lines of which five were copied from the source chapter word for word (the longest
22 of 22 characters identical), the set overlapped the source at 49 % by length, and two lead
characters of very different age and station shared one clipped, judging register — the "AI voice"
the line owner heard. Every one of those passed every existing gate: nothing compared a line to the
chapter it came from, and nothing looked at how a character speaks.

Three rules, all offline (no provider call, no cost), run at S1:

  DR1 DIALOGUE_SOURCE_VERBATIM        a line shares a run of >= 8 characters with the episode's source
                                      text: the writer moved the novel's sentence into the script
  DR2 DIALOGUE_WRITTEN_REGISTER       a line is written prose, not speech: classical/register markers
                                      (为何, 之, 乃, 特制, 灵性 …) or a judged comparison the character
                                      narrates about himself ("我的力气比他大，速度比他慢")
  DR3 DIALOGUE_ONE_VOICE              two characters who each speak >= 3 lines have nearly the same
                                      sentence-length profile and vocabulary: they share one voice

Scope: episodes whose writing contract declares ``dialogue_register_policy`` (V1), or episode >=
``enabled_from_episode`` in configs/DIALOGUE_REGISTER_V1.json.  A line inside a ``<d>`` tag, a
contract ``prompt_spec.dialogue`` row, or a narrative file's quoted speech is judged the same way —
the check reads whichever the caller hands it.

exit 0 PASS / NOT_ACTIVE, 3 BLOCK, 2 unreadable.

Usage
  dialogue_register_gate.py --manifest <manifest.json> --source <chapter.md> [--out report.json]
  dialogue_register_gate.py --contract <contract.json> --source <chapter.md>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLICY_ID = "DIALOGUE_REGISTER_V1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / f"{POLICY_ID}.json"

#: a run this long shared with the source is the writer copying, not adapting
VERBATIM_MIN_RUN = 8

#: classical / instruction-manual markers that read as written prose when spoken
WRITTEN_REGISTER_MARKERS = (
    "为何", "何等", "之", "乃", "颇", "甚", "岂", "焉", "矣", "乎", "耳",
    "特制", "灵性", "好时机", "要熄灭", "提前安排", "围堵", "逃掉", "活捉",
)
#: a character narrating a comparison about himself is an inner judgement, not a spoken line
JUDGED_COMPARISON = re.compile(
    r"(?:我的?|他的?|你的?)[^，。！？]{0,6}(?:力气|速度|功\s*夫|本事)[^，。！？]{0,3}(?:比|不如|大于|小于)")

SPEAKER_SEPARATOR = re.compile(r"^([^：:]{1,12})[：:](.*)$")
QUOTED = re.compile(r"[「“\"]([^」”\"]{2,})[」”\"]")
TAG = re.compile(r"<d>(.*?)</d>", re.DOTALL)
ENUMERATION = re.compile(r"^(?:[一二三四五六七八九十]+[、.]|\d+[、.])\s*")

CJK = re.compile(r"[一-鿿]")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def policy_loaded(path: Path | None = None) -> dict[str, Any]:
    try:
        return _read_json(path or POLICY_PATH)
    except (OSError, ValueError):
        return {}


def policy_active(contract: dict[str, Any] | None, *, episode: str | None, policy: dict[str, Any]) -> bool:
    if not policy:
        return False
    declared = str((contract or {}).get("dialogue_register_policy") or "").strip()
    if declared == POLICY_ID:
        return True
    start = str(policy.get("enabled_from_episode") or "").strip()
    if not start or not episode:
        return False
    try:
        return int(re.sub(r"\D", "", episode)) >= int(re.sub(r"\D", "", start))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# text handling
# --------------------------------------------------------------------------- #

def _normalise(text: str) -> str:
    """Keep CJK and latin letters/digits; drop punctuation, spaces and markup so a run is word-level."""
    return "".join(ch for ch in text if CJK.match(ch) or ch.isalnum())


def longest_common_run(line: str, source: str) -> str:
    """Longest substring of ``line`` that occurs in ``source`` (both normalised), as original text."""
    a, b = _normalise(line), _normalise(source)
    if not a or not b:
        return ""
    best = ""
    n = len(a)
    # classic O(n*m) DP over a short line is fine (lines are <= 40 characters)
    prev = [0] * (len(b) + 1)
    end = 0
    for i in range(1, n + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > end:
                    end = cur[j]
        prev = cur
    if end == 0:
        return ""
    # locate one occurrence of the winning run in the normalised line
    for start in range(0, n - end + 1):
        candidate = a[start:start + end]
        if candidate in b:
            best = candidate
            break
    return best


def lines_from_contract(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Every authored spoken line, with the shot it belongs to and the declared speaker."""
    out: list[dict[str, str]] = []
    for shot in contract.get("shots") or []:
        sid = str(shot.get("shot_id") or shot.get("id") or "")
        raw = str(((shot.get("prompt_spec") or {}).get("dialogue")) or shot.get("dialogue") or "").strip()
        if not raw:
            continue
        m = SPEAKER_SEPARATOR.match(raw)
        speaker, words = (m.group(1).strip(), m.group(2).strip()) if m else ("", raw)
        for piece in [p.strip() for p in re.split(r"(?<=[。！？])", words) if p.strip()]:
            out.append({"shot_id": sid, "speaker": speaker, "text": piece})
    return out


def lines_from_narrative(text: str) -> list[dict[str, str]]:
    """Quoted speech in a narrative file, speaker taken from the nearest preceding name+colon."""
    out: list[dict[str, str]] = []
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = ENUMERATION.sub("", raw_line.strip())
        m = SPEAKER_SEPARATOR.match(line)
        speaker, body = (m.group(1).strip(), m.group(2)) if m else ("", line)
        found = QUOTED.findall(body) or ([m.group(1)] if not speaker and (m := TAG.search(body)) else [])
        for piece in found:
            if _normalise(piece):
                out.append({"shot_id": f"L{number}", "speaker": speaker, "text": piece.strip()})
    return out


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #

def written_register_hits(text: str) -> list[str]:
    hits = [marker for marker in WRITTEN_REGISTER_MARKERS if marker in text]
    if JUDGED_COMPARISON.search(text):
        hits.append("JUDGED_COMPARISON")
    return hits


def _profile(lines: list[dict[str, str]]) -> dict[str, Any]:
    lengths = [len(_normalise(l["text"])) for l in lines]
    bigrams: set[str] = set()
    for line in lines:
        norm = _normalise(line["text"])
        bigrams.update(norm[i:i + 2] for i in range(len(norm) - 1))
    return {"lines": len(lines), "mean_length": sum(lengths) / len(lengths) if lengths else 0.0,
            "bigrams": bigrams}


def one_voice_pairs(lines: list[dict[str, str]], *, min_lines: int = 3,
                    max_mean_gap: float = 1.5, max_jaccard: float = 0.35) -> list[dict[str, Any]]:
    """Speakers whose sentence length and character bigrams are nearly identical share one voice."""
    by_speaker: dict[str, list[dict[str, str]]] = {}
    for line in lines:
        if line["speaker"]:
            by_speaker.setdefault(line["speaker"], []).append(line)
    ready = {name: _profile(rows) for name, rows in by_speaker.items() if len(rows) >= min_lines}
    out: list[dict[str, Any]] = []
    names = sorted(ready)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = ready[a], ready[b]
            union = pa["bigrams"] | pb["bigrams"]
            jaccard = len(pa["bigrams"] & pb["bigrams"]) / len(union) if union else 1.0
            gap = abs(pa["mean_length"] - pb["mean_length"])
            if jaccard >= max_jaccard and gap <= max_mean_gap:
                out.append({"a": a, "b": b, "bigram_jaccard": round(jaccard, 3),
                            "mean_length_gap": round(gap, 2), "lines": [pa["lines"], pb["lines"]]})
    return out


def fingerprint_drift(lines: list[dict[str, str]], fingerprints: dict[str, Any]) -> list[dict[str, Any]]:
    """A speaker whose lines break the declared ``speech_fingerprint`` (max_chars / banned words)."""
    out: list[dict[str, Any]] = []
    for line in lines:
        spec = fingerprints.get(line["speaker"]) or {}
        if not spec:
            continue
        limit = spec.get("max_chars")
        if isinstance(limit, int) and len(_normalise(line["text"])) > limit:
            out.append({"shot_id": line["shot_id"], "speaker": line["speaker"],
                        "code": "FINGERPRINT_MAX_CHARS", "limit": limit,
                        "measured": len(_normalise(line["text"])), "text": line["text"]})
        for word in spec.get("banned_words") or []:
            if word and word in line["text"]:
                out.append({"shot_id": line["shot_id"], "speaker": line["speaker"],
                            "code": "FINGERPRINT_BANNED_WORD", "word": word, "text": line["text"]})
    return out


def analyse(lines: list[dict[str, str]], source_text: str, *, fingerprints: dict[str, Any] | None = None,
            verbatim_min_run: int = VERBATIM_MIN_RUN) -> dict[str, Any]:
    """Pure function over authored lines; testable without files or a provider."""
    verbatim: list[dict[str, Any]] = []
    written: list[dict[str, Any]] = []
    total_chars = 0
    overlap_chars = 0
    for line in lines:
        norm_len = len(_normalise(line["text"]))
        total_chars += norm_len
        run = longest_common_run(line["text"], source_text) if source_text else ""
        overlap_chars += len(run)
        if len(run) >= verbatim_min_run:
            verbatim.append({"shot_id": line["shot_id"], "speaker": line["speaker"], "text": line["text"],
                             "run": run, "run_chars": len(run), "line_chars": norm_len,
                             "code": "DIALOGUE_SOURCE_VERBATIM"})
        hits = written_register_hits(line["text"])
        if hits:
            written.append({"shot_id": line["shot_id"], "speaker": line["speaker"], "text": line["text"],
                            "markers": hits, "code": "DIALOGUE_WRITTEN_REGISTER"})
    voices = one_voice_pairs(lines)
    drift = fingerprint_drift(lines, fingerprints or {})
    failures: list[str] = []
    if verbatim:
        failures.append(f"DIALOGUE_SOURCE_VERBATIM:{len(verbatim)}")
    if written:
        failures.append(f"DIALOGUE_WRITTEN_REGISTER:{len(written)}")
    if voices:
        failures.append(f"DIALOGUE_ONE_VOICE:{len(voices)}")
    if drift:
        failures.append(f"DIALOGUE_FINGERPRINT_DRIFT:{len(drift)}")
    return {
        "schema": "nalu.dialogue_register_report.v1", "policy_id": POLICY_ID,
        "status": "FAIL" if failures else "PASS", "failures": failures,
        "lines": len(lines), "chars": total_chars,
        "source_overlap_ratio": round(overlap_chars / total_chars, 3) if total_chars else 0.0,
        "verbatim": verbatim, "written_register": written, "one_voice": voices, "fingerprint_drift": drift,
        "thresholds": {"verbatim_min_run": verbatim_min_run},
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def load_subject(*, contract: Path | None, narrative: Path | None, source: Path) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    contract_payload: dict[str, Any] = {}
    lines: list[dict[str, str]] = []
    if contract and contract.is_file():
        contract_payload = _read_json(contract)
        lines.extend(lines_from_contract(contract_payload))
    if narrative and narrative.is_file():
        lines.extend(lines_from_narrative(narrative.read_text(encoding="utf-8")))
    source_text = source.read_text(encoding="utf-8") if source.is_file() else ""
    return contract_payload, lines, source_text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{POLICY_ID} — spoken lines must be the character's own.")
    ap.add_argument("--contract")
    ap.add_argument("--manifest")
    ap.add_argument("--narrative")
    ap.add_argument("--source", required=True, help="the episode's source chapter (.md)")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true", help="print the report")
    args = ap.parse_args(argv)

    policy = policy_loaded()
    contract_path = Path(args.contract).expanduser() if args.contract else None
    episode = None
    if args.manifest:
        manifest = _read_json(Path(args.manifest).expanduser())
        episode = str(manifest.get("episode") or "") or None
        contract_path = Path(manifest.get("generation_contract") or manifest.get("contract") or "").expanduser() \
            if (manifest.get("generation_contract") or manifest.get("contract")) else contract_path
    if args.contract:
        try:
            episode = episode or str(_read_json(Path(args.contract).expanduser()).get("episode") or "") or None
        except (OSError, ValueError):
            pass
    if not policy_active(_read_json(contract_path) if contract_path and contract_path.is_file() else {},
                         episode=episode, policy=policy):
        report = {"schema": "nalu.dialogue_register_report.v1", "policy_id": POLICY_ID,
                  "status": "NOT_ACTIVE", "episode": episode, "failures": []}
        if args.out:
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"status": "NOT_ACTIVE", "episode": episode}))
        return 0

    contract_payload, lines, source_text = load_subject(
        contract=contract_path, narrative=Path(args.narrative).expanduser() if args.narrative else None,
        source=Path(args.source).expanduser())
    if not source_text:
        print(f"source text missing or empty: {args.source}", file=sys.stderr)
        return 2
    fingerprints = {name: spec for name, spec in ((contract_payload.get("speech_fingerprints") or {}).items())}
    report = analyse(lines, source_text, fingerprints=fingerprints,
                     verbatim_min_run=int(policy.get("verbatim_min_run") or VERBATIM_MIN_RUN))
    report["episode"] = episode
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"status": report["status"], "failures": report["failures"],
                          "lines": report["lines"], "source_overlap_ratio": report["source_overlap_ratio"]}))
    return 3 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
