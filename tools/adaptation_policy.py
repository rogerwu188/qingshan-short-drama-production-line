#!/usr/bin/env python3
"""Per-episode adaptation disposition: what the writer did to each source beat.

Why this exists
---------------
Under the nalu line the only adaptation record was the writer manifest's
``beat_disposition`` (landed / merged / dropped).  That table cannot tell a
verbatim landing from a paraphrase, and it has no way to say "this line was
written new, and here is the source beat it bridges from" — so the E11-E13 audit
(PILOT_RESULT.md) had to grep the narrative by hand to find that an episode had
silently dropped the set-ups a later episode depends on.

This tool validates a per-episode DISPOSITION FILE: one row per source beat, each
carrying its category, its ``source_ref`` and a reason.  The categories are the
line owner's (2026-11-01, recorded verbatim in
``configs/ADAPTATION_POLICY_V1.json``):

  verbatim       the line lands as written; the quote must occur in the cited chapter
  condensed      repetition compressed; the reason must say nothing causal was dropped
  reorganized    same causal chain, reordered or merged
  adapted_new    a new line or bridging action; allowed by default with a source trace
  omitted        cut, with a reason; may not cut anything a later episode depends on
  deferred       postponed, with the episode that will carry it

and MAJOR_CHANGE, which is a FLAG rather than a category: a beat that changes a
major relationship, a motive, a key established fact or a plot outcome must carry
``major_change`` and an escalation row naming the line-owner order that
authorised it.  Everything else — bridging dialogue, paraphrase, compressing
inner monologue into filmable action — is writer-owned and needs no escalation.

Verbatim checking
-----------------
``quote`` is compared against the real chapter text, read the same way the
line's source intake lays it out: ``<sources>/<work>/<reading_script>/chNNNN.md``
(``SOURCE_INDEX.json`` names ``canonical_reading_script``).  Comparison is exact
on the text with whitespace removed, because the intake writes one paragraph per
line and the writer's quote may wrap differently.  A match that needs that
whitespace normalisation is reported as ``quote_match=WHITESPACE_NORMALISED``
so the disclosure stays precise; a quote that matches nothing is a failure
listing the closest line, never a silent pass.

Omission vs deferral
--------------------
``omitted`` is rejected when a LATER episode's ``depends_on`` names that beat id
— that is exactly the E11-E13 failure, and the fix is ``deferred`` with the
planned episode named.  ``--later-dependencies <file>`` supplies those (an arc
ledger's chosen events or a hand-written list); without it only in-file
``depends_on`` rows are checked.

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.adaptation_disposition.v1"
POLICY_SCHEMA = "qingshan.adaptation_policy.v1"
REPORT_SCHEMA = "qingshan.adaptation_disposition_report.v1"
TOOL_ID = "adaptation_policy.v1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs/ADAPTATION_POLICY_V1.json"

CATEGORIES = ("verbatim", "condensed", "reorganized", "adapted_new", "omitted", "deferred")
MAJOR_CHANGE_KINDS = ("relationship", "motive", "key_fact", "plot_outcome")
EPISODE_RE = re.compile(r"^E\d{2,3}$")
CHAPTER_RE = re.compile(r"^ch(\d{1,4})(?::(.+))?$")
MIN_REASON_CHARS = 8


# --------------------------------------------------------------------------- policy


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy = json.loads(Path(path or POLICY_PATH).read_text(encoding="utf-8"))
    if policy.get("schema") != POLICY_SCHEMA:
        raise SystemExit(f"ADAPTATION_POLICY_SCHEMA_INVALID:{policy.get('schema')}")
    missing = [name for name in CATEGORIES if name not in (policy.get("categories") or {})]
    if missing:
        raise SystemExit("ADAPTATION_POLICY_CATEGORY_MISSING:" + ",".join(missing))
    return policy


def category_rule(policy: dict[str, Any], category: str) -> dict[str, Any]:
    return (policy.get("categories") or {}).get(category) or {}


def default_decision(policy: dict[str, Any], category: str) -> str:
    return str(category_rule(policy, category).get("default") or "UNKNOWN")


# --------------------------------------------------------------------------- source text


def resolve_sources_root(sources_root: Path | str) -> Path:
    return Path(sources_root).expanduser().resolve()


def find_work_dir(sources_root: Path, work: str | None) -> Path:
    root = resolve_sources_root(sources_root)
    if work:
        candidate = root / work
        if not candidate.is_dir():
            raise SystemExit(f"ADAPTATION_SOURCE_WORK_MISSING:{candidate}")
        return candidate
    works = sorted(path for path in root.glob("*") if path.is_dir()) if root.is_dir() else []
    if len(works) == 1:
        return works[0]
    raise SystemExit("ADAPTATION_SOURCE_WORK_AMBIGUOUS:pass --work")


def reading_script_dir(sources_root: Path, work: str | None = None) -> Path:
    """``SOURCE_INDEX.json`` names the script the source was canonicalised into."""
    work_dir = find_work_dir(sources_root, work)
    index = work_dir / "SOURCE_INDEX.json"
    name = "as_delivered"
    if index.is_file():
        try:
            declared = str((json.loads(index.read_text(encoding="utf-8")) or {}).get("canonical_reading_script") or "")
        except (OSError, json.JSONDecodeError):
            declared = ""
        # "zh-CN (OpenCC t2s of the delivered text)" -> "zh-CN"
        if declared:
            name = declared.split()[0]
    directory = work_dir / name
    if not directory.is_dir():
        raise SystemExit(f"ADAPTATION_READING_SCRIPT_MISSING:{directory}")
    return directory


def chapter_text(sources_root: Path, chapter: str, work: str | None = None) -> str:
    """Read one chapter of the canonical reading script, or raise SystemExit."""
    match = CHAPTER_RE.match(str(chapter or "").strip())
    if not match:
        raise SystemExit(f"ADAPTATION_SOURCE_REF_INVALID:{chapter}")
    number = int(match.group(1))
    path = reading_script_dir(sources_root, work) / f"ch{number:04d}.md"
    if not path.is_file():
        raise SystemExit(f"ADAPTATION_CHAPTER_MISSING:{path}")
    return path.read_text(encoding="utf-8")


def _squash(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def check_quote(quote: str, text: str) -> tuple[str, str | None]:
    """Return (verdict, nearest_line).  verdict ∈ EXACT | WHITESPACE_NORMALISED | NOT_FOUND."""
    needle = str(quote or "").strip()
    if not needle:
        return "NOT_FOUND", None
    if needle in text:
        return "EXACT", None
    squashed = _squash(needle)
    if squashed and squashed in _squash(text):
        return "WHITESPACE_NORMALISED", None
    # give the writer the nearest real line back, so the fix is mechanical
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first = squashed[:4] if squashed else ""
    nearest = next((line for line in lines if first and first in _squash(line)), None)
    return "NOT_FOUND", nearest


# --------------------------------------------------------------------------- validation


def validate_disposition(
    disposition: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    sources_root: Path | str | None = None,
    work: str | None = None,
    later_dependencies: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Validate one episode's disposition file.  Returns a report dict.

    ``later_dependencies`` maps a beat id to the episodes whose source_ref depends
    on it; an ``omitted`` beat listed there is a failure (it must be ``deferred``).
    """
    policy = policy or load_policy()
    failures: list[str] = []
    warnings: list[str] = []
    rows_out: list[dict[str, Any]] = []

    if not isinstance(disposition, dict):
        return _report(["DISPOSITION_NOT_AN_OBJECT"], [], [], {})
    if disposition.get("schema") != SCHEMA:
        failures.append(f"SCHEMA_INVALID:{disposition.get('schema')!r}")
    episode = str(disposition.get("episode") or "").strip()
    if not EPISODE_RE.match(episode):
        failures.append(f"EPISODE_INVALID:{disposition.get('episode')!r}")
    chapter = disposition.get("chapter")
    if chapter is not None and not CHAPTER_RE.match(str(chapter)):
        failures.append(f"CHAPTER_INVALID:{chapter!r}")

    later = {str(key): [str(value) for value in values]
             for key, values in (later_dependencies or {}).items()}
    text_cache: dict[str, str] = {}
    beats = disposition.get("beats")
    if not isinstance(beats, list) or not beats:
        failures.append("BEATS_MISSING")
        beats = []
    seen: set[str] = set()
    counts: dict[str, int] = {name: 0 for name in CATEGORIES}

    for index, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            failures.append(f"BEAT_NOT_AN_OBJECT:{index}")
            continue
        beat_id = str(beat.get("beat_id") or "").strip()
        label = beat_id or str(index)
        if not beat_id:
            failures.append(f"BEAT_ID_MISSING:{index}")
        elif beat_id in seen:
            failures.append(f"BEAT_ID_DUPLICATE:{beat_id}")
        else:
            seen.add(beat_id)

        category = str(beat.get("category") or "").strip()
        if category not in CATEGORIES:
            failures.append(f"CATEGORY_INVALID:{label}:{category!r}")
            continue
        counts[category] += 1
        rule = category_rule(policy, category)
        decision = default_decision(policy, category)
        if decision == "REQUIRES_LINE_OWNER":
            failures.append(f"CATEGORY_REQUIRES_LINE_OWNER:{label}:{category}")

        for field in ("source_ref", "reason"):
            if not str(beat.get(field) or "").strip():
                failures.append(f"FIELD_MISSING:{label}:{field}")
        reason = str(beat.get("reason") or "").strip()
        if reason and len(reason) < MIN_REASON_CHARS:
            warnings.append(f"REASON_TOO_SHORT:{label}:{len(reason)}")

        source_ref = str(beat.get("source_ref") or "").strip()
        ref_chapter = None
        if source_ref:
            match = CHAPTER_RE.match(source_ref)
            if not match:
                failures.append(f"SOURCE_REF_INVALID:{label}:{source_ref}")
            else:
                ref_chapter = f"ch{int(match.group(1)):04d}"

        verbatim_verdict = None
        if category == "verbatim":
            quote = str(beat.get("quote") or "").strip()
            if not quote:
                failures.append(f"QUOTE_MISSING_FOR_VERBATIM:{label}")
            elif sources_root is None:
                warnings.append(f"VERBATIM_NOT_CHECKED_NO_SOURCES_ROOT:{label}")
            elif ref_chapter is None:
                failures.append(f"QUOTE_CHAPTER_UNKNOWN:{label}")
            else:
                key = ref_chapter
                if key not in text_cache:
                    text_cache[key] = chapter_text(sources_root, ref_chapter, work)
                verdict, nearest = check_quote(quote, text_cache[key])
                verbatim_verdict = verdict
                if verdict == "NOT_FOUND":
                    failures.append(
                        f"VERBATIM_QUOTE_NOT_IN_CHAPTER:{label}:{ref_chapter}:"
                        f"nearest={nearest[:40] if nearest else 'NONE'}")
                elif verdict == "WHITESPACE_NORMALISED":
                    warnings.append(f"VERBATIM_QUOTE_MATCHED_AFTER_WHITESPACE_NORMALISATION:{label}")

        if category == "adapted_new":
            if not str(beat.get("trace") or "").strip():
                failures.append(f"ADAPTED_NEW_TRACE_MISSING:{label}")

        if category == "deferred":
            planned = str(beat.get("planned_payoff_episode") or "").strip()
            if not planned:
                failures.append(f"DEFERRED_PLANNED_EPISODE_MISSING:{label}")
            elif not EPISODE_RE.match(planned):
                failures.append(f"DEFERRED_PLANNED_EPISODE_INVALID:{label}:{planned}")
            elif planned <= episode:
                failures.append(f"DEFERRED_PLANNED_EPISODE_NOT_LATER:{label}:{planned}")

        if category == "omitted":
            dependents = later.get(beat_id) or []
            if dependents:
                failures.append(
                    f"OMITTED_BEAT_DEPENDED_ON_LATER:{label}:{','.join(sorted(dependents))}"
                    " (defer it instead of omitting)")

        major = beat.get("major_change")
        if category == "adapted_new" and (beat.get("new_character_fate") or beat.get("changes_outcome")):
            warnings.append(f"ADAPTED_NEW_TOUCHES_OUTCOME_DECLARE_MAJOR_CHANGE:{label}")
        if major is not None:
            _validate_major_change(label, major, failures)

        rows_out.append({
            "beat_id": beat_id or label,
            "category": category,
            "decision": decision,
            "source_ref": source_ref,
            "quote_match": verbatim_verdict,
            "major_change": bool(major),
        })

    measurements = {
        "episode": episode,
        "beat_count": len(beats),
        "by_category": counts,
        "major_change_rows": sum(1 for row in rows_out if row["major_change"]),
        "verbatim_checked": sum(1 for row in rows_out if row["quote_match"]),
        "verbatim_not_found": sum(1 for row in rows_out if row["quote_match"] == "NOT_FOUND"),
    }
    return _report(failures, warnings, rows_out, measurements)


def _validate_major_change(label: str, major: Any, failures: list[str]) -> None:
    if not isinstance(major, dict):
        failures.append(f"MAJOR_CHANGE_NOT_AN_OBJECT:{label}")
        return
    if str(major.get("change_kind") or "") not in MAJOR_CHANGE_KINDS:
        failures.append(f"MAJOR_CHANGE_KIND_INVALID:{label}:{major.get('change_kind')}")
    if not str(major.get("description") or "").strip():
        failures.append(f"MAJOR_CHANGE_DESCRIPTION_MISSING:{label}")
    escalation = major.get("escalation")
    if not isinstance(escalation, dict):
        failures.append(f"MAJOR_CHANGE_NOT_ESCALATED:{label}")
        return
    if not str(escalation.get("authorization_order") or "").strip():
        failures.append(f"MAJOR_CHANGE_ESCALATION_WITHOUT_ORDER:{label}")
    if str(escalation.get("status") or "").strip() not in {"PENDING", "APPROVED"}:
        failures.append(f"MAJOR_CHANGE_ESCALATION_STATUS_INVALID:{label}:{escalation.get('status')}")
    if str(escalation.get("status") or "") == "APPROVED" and not str(escalation.get("order_sha256") or "").strip():
        failures.append(f"MAJOR_CHANGE_APPROVED_WITHOUT_RECEIPT:{label}")


def _report(failures: list[str], warnings: list[str], rows: list[dict[str, Any]],
            measurements: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "tool": TOOL_ID,
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "warnings": warnings,
        "rows": rows,
        "measurements": measurements,
    }


def load_later_dependencies(path: Path | str) -> dict[str, list[str]]:
    """Read ``{beat_id: [episode, ...]}`` from a hand-off file.

    Accepts either that map directly, or an arc ledger whose episodes carry
    ``chosen_events`` rows with ``depends_on`` pointing at beat ids.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("later_dependencies"), dict):
        payload = payload["later_dependencies"]
    if isinstance(payload, dict) and not isinstance(payload.get("episodes"), list):
        return {str(key): [str(value) for value in (values if isinstance(values, list) else [values])]
                for key, values in payload.items()}
    out: dict[str, list[str]] = {}
    for episode_row in (payload.get("episodes") or []) if isinstance(payload, dict) else []:
        if not isinstance(episode_row, dict):
            continue
        episode = str(episode_row.get("episode") or "")
        for event in episode_row.get("chosen_events") or []:
            if not isinstance(event, dict):
                continue
            for beat in event.get("depends_on") or []:
                out.setdefault(str(beat), []).append(episode)
    return out


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("validate", help="validate one episode's disposition file")
    check.add_argument("--disposition", type=Path, required=True)
    check.add_argument("--policy", type=Path, default=POLICY_PATH)
    check.add_argument("--sources-root", type=Path,
                       help="runtime sources root (enables the verbatim quote check)")
    check.add_argument("--work", default=None, help="work folder under sources-root")
    check.add_argument("--later-dependencies", type=Path,
                       help="map of beat_id -> episodes that depend on it")
    check.add_argument("--out", type=Path)

    defaults = sub.add_parser("defaults", help="print each category's default decision")
    defaults.add_argument("--policy", type=Path, default=POLICY_PATH)

    args = parser.parse_args(argv)
    if args.command == "defaults":
        policy = load_policy(args.policy)
        print(json.dumps({name: default_decision(policy, name) for name in CATEGORIES},
                         ensure_ascii=False, indent=2))
        return 0

    report = validate_disposition(
        json.loads(args.disposition.read_text(encoding="utf-8")),
        policy=load_policy(args.policy),
        sources_root=args.sources_root,
        work=args.work,
        later_dependencies=(load_later_dependencies(args.later_dependencies)
                            if args.later_dependencies else None),
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"]},
                     ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
