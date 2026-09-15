#!/usr/bin/env python3
"""Fail-closed source reading and script-to-source Canon binding gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
REQUIRED_CANON_CATEGORIES = {
    "protagonist",
    "world",
    "era",
    "weather_daylight",
    "opening_event",
}
MAJOR_TRANSFORMATIONS = {
    "protagonist_identity",
    "era",
    "world",
    "opening_event",
    "core_causal_chain",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_ref(base_file: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_file.parent / path).resolve()


def valid_sha(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "").lower()))


def validate_source_chain(
    source_path: Path,
    canon_path: Path,
    beat_map_path: Path,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    source = load_json(source_path)
    canon = load_json(canon_path)
    beat_map = load_json(beat_map_path)

    if source.get("schema") != "qingshan.source_ingest_manifest.v1":
        failures.append("source_manifest_schema_invalid")
    if source.get("status") != "PASS":
        failures.append("source_manifest_not_pass")
    locked_ids = list((source.get("locked_scope") or {}).get("chapter_ids") or [])
    if not locked_ids or len(locked_ids) != len(set(locked_ids)):
        failures.append("source_scope_missing_or_duplicate")

    chapter_rows = source.get("chapters") or []
    chapters = {str(row.get("chapter_id")): row for row in chapter_rows}
    if set(chapters) != set(map(str, locked_ids)):
        failures.append("locked_scope_chapter_coverage_mismatch")
    for chapter_id in map(str, locked_ids):
        row = chapters.get(chapter_id) or {}
        if row.get("read_status") != "READ":
            failures.append(f"chapter_not_read:{chapter_id}")
        if not str(row.get("source_ref") or "").strip():
            failures.append(f"chapter_source_ref_missing:{chapter_id}")
        if not valid_sha(row.get("content_sha256")):
            failures.append(f"chapter_content_sha256_invalid:{chapter_id}")
        if not str(row.get("fetched_at") or "").strip():
            failures.append(f"chapter_fetched_at_missing:{chapter_id}")

    source_sha = sha256_file(source_path)
    if canon.get("schema") != "qingshan.canon_facts.v1":
        failures.append("canon_facts_schema_invalid")
    if canon.get("status") != "PASS":
        failures.append("canon_facts_not_pass")
    if canon.get("source_manifest_sha256") != source_sha:
        failures.append("canon_source_manifest_sha256_mismatch")

    fact_rows = canon.get("facts") or []
    facts = {str(row.get("fact_id")): row for row in fact_rows if row.get("fact_id")}
    categories = {str(row.get("category")) for row in fact_rows}
    for category in sorted(REQUIRED_CANON_CATEGORIES - categories):
        failures.append(f"required_canon_category_missing:{category}")
    if len(facts) != len(fact_rows):
        failures.append("canon_fact_id_missing_or_duplicate")
    for fact_id, fact in facts.items():
        if fact.get("value") in (None, "", [], {}):
            failures.append(f"canon_fact_value_missing:{fact_id}")
        refs = fact.get("source_refs") or []
        if not refs:
            failures.append(f"canon_fact_source_refs_missing:{fact_id}")
        for ref in refs:
            chapter_id = str(ref.get("chapter_id") or "")
            chapter = chapters.get(chapter_id)
            if not chapter:
                failures.append(f"canon_fact_unknown_chapter:{fact_id}:{chapter_id}")
            elif ref.get("content_sha256") != chapter.get("content_sha256"):
                failures.append(f"canon_fact_chapter_sha256_mismatch:{fact_id}:{chapter_id}")

    canon_sha = sha256_file(canon_path)
    if beat_map.get("schema") != "qingshan.chapter_beat_map.v1":
        failures.append("beat_map_schema_invalid")
    if beat_map.get("status") != "PASS":
        failures.append("beat_map_not_pass")
    if beat_map.get("source_manifest_sha256") != source_sha:
        failures.append("beat_map_source_manifest_sha256_mismatch")
    if beat_map.get("canon_facts_sha256") != canon_sha:
        failures.append("beat_map_canon_facts_sha256_mismatch")

    episode_rows = beat_map.get("episodes") or []
    episodes = {str(row.get("episode")): row for row in episode_rows if row.get("episode")}
    if not episodes or len(episodes) != len(episode_rows):
        failures.append("beat_map_episode_missing_or_duplicate")
    for episode, row in episodes.items():
        bound_chapters = set(map(str, row.get("source_chapters") or []))
        if not bound_chapters or not bound_chapters.issubset(chapters):
            failures.append(f"beat_map_source_chapters_invalid:{episode}")
        bound_facts = set(map(str, row.get("canon_fact_ids") or []))
        if not bound_facts or not bound_facts.issubset(facts):
            failures.append(f"beat_map_canon_fact_ids_invalid:{episode}")
        events = row.get("source_events") or []
        if not events:
            failures.append(f"beat_map_source_events_missing:{episode}")
        for event in events:
            chapter_id = str(event.get("chapter_id") or "")
            chapter = chapters.get(chapter_id)
            if not str(event.get("event_id") or "").strip():
                failures.append(f"source_event_id_missing:{episode}")
            if not chapter:
                failures.append(f"source_event_unknown_chapter:{episode}:{chapter_id}")
            elif event.get("content_sha256") != chapter.get("content_sha256"):
                failures.append(f"source_event_chapter_sha256_mismatch:{episode}:{chapter_id}")

    transform = source.get("adaptation_transform_authorization") or {}
    requested = set(map(str, transform.get("requested_transformations") or []))
    approved = set(map(str, transform.get("allowed_transformations") or []))
    unauthorized = requested & MAJOR_TRANSFORMATIONS - approved
    if unauthorized or (requested & MAJOR_TRANSFORMATIONS and transform.get("status") != "APPROVED"):
        failures.append(
            "unauthorized_major_transformation:" + ",".join(sorted(unauthorized or requested))
        )

    return failures, {
        "source": source,
        "canon": canon,
        "beat_map": beat_map,
        "chapters": chapters,
        "facts": facts,
        "episodes": episodes,
        "source_manifest_sha256": source_sha,
        "canon_facts_sha256": canon_sha,
        "beat_map_sha256": sha256_file(beat_map_path),
    }


def validate_series_manifest(
    series_path: Path,
    chain: dict[str, Any],
    episode: str | None,
    canonical_script_sha256: str | None,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    series = load_json(series_path)
    if series.get("schema") != "qingshan.full_series_manifest.v1":
        failures.append("full_series_manifest_schema_invalid")
    if series.get("status") != "PASS":
        failures.append("full_series_manifest_not_pass")
    for field in ("source_manifest_sha256", "canon_facts_sha256", "beat_map_sha256"):
        if series.get(field) != chain[field]:
            failures.append(f"full_series_{field}_mismatch")

    script_rows = series.get("scripts") or []
    scripts = {str(row.get("episode")): row for row in script_rows if row.get("episode")}
    expected_episodes = set(chain["episodes"])
    if set(scripts) != expected_episodes or len(scripts) != len(script_rows):
        failures.append("full_series_episode_coverage_mismatch")
    selected = [episode] if episode else sorted(expected_episodes)
    for episode_id in selected:
        row = scripts.get(episode_id) or {}
        if canonical_script_sha256 and row.get("sha256") != canonical_script_sha256:
            failures.append(f"canonical_script_sha256_not_bound_to_series:{episode_id}")
        script_ref = str(row.get("path") or "")
        script_path = resolve_ref(series_path, script_ref) if script_ref else None
        if not script_path or not script_path.is_file():
            failures.append(f"script_file_missing:{episode_id}")
        elif sha256_file(script_path) != row.get("sha256"):
            failures.append(f"script_sha256_mismatch:{episode_id}")
        beat = chain["episodes"].get(episode_id) or {}
        bindings = row.get("source_bindings") or {}
        if set(map(str, bindings.get("source_chapters") or [])) != set(map(str, beat.get("source_chapters") or [])):
            failures.append(f"script_source_chapter_binding_mismatch:{episode_id}")
        if not set(map(str, beat.get("canon_fact_ids") or [])).issubset(
            set(map(str, bindings.get("canon_fact_ids") or []))
        ):
            failures.append(f"script_canon_fact_binding_incomplete:{episode_id}")
        expected_events = {str(item.get("event_id")) for item in beat.get("source_events") or []}
        actual_events = set(map(str, bindings.get("source_event_ids") or []))
        if not expected_events or not expected_events.issubset(actual_events):
            failures.append(f"script_source_event_binding_incomplete:{episode_id}")
    return failures, {
        "series": series,
        "scripts": scripts,
        "full_series_manifest_sha256": sha256_file(series_path),
    }


def validate_fidelity_report(
    report_path: Path,
    chain: dict[str, Any],
    series_chain: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    report = load_json(report_path)
    if report.get("schema") != "qingshan.full_series_source_fidelity.v1":
        failures.append("source_fidelity_schema_invalid")
    if report.get("auditor_agent") != "qingshan-ai-aduit":
        failures.append("source_fidelity_independent_auditor_invalid")
    for field in ("source_manifest_sha256", "canon_facts_sha256", "beat_map_sha256"):
        if report.get(field) != chain[field]:
            failures.append(f"source_fidelity_{field}_mismatch")
    if report.get("full_series_manifest_sha256") != series_chain["full_series_manifest_sha256"]:
        failures.append("source_fidelity_full_series_manifest_sha256_mismatch")
    if report.get("status") != "PASS":
        failures.append("source_fidelity_not_pass")
    if float(report.get("score_100", 0) or 0) < 90:
        failures.append("source_fidelity_score_below_90")

    rows = report.get("episodes") or []
    episodes = {str(row.get("episode")): row for row in rows if row.get("episode")}
    if set(episodes) != set(series_chain["scripts"]) or len(episodes) != len(rows):
        failures.append("source_fidelity_episode_coverage_mismatch")
    for episode, script in series_chain["scripts"].items():
        row = episodes.get(episode) or {}
        if row.get("status") != "PASS" or float(row.get("score_100", 0) or 0) < 90:
            failures.append(f"source_fidelity_episode_not_pass:{episode}")
        if row.get("script_sha256") != script.get("sha256"):
            failures.append(f"source_fidelity_script_sha256_mismatch:{episode}")
        comparisons = row.get("critical_fact_comparisons") or []
        compared = {str(item.get("category")) for item in comparisons if item.get("matches") is True}
        missing = REQUIRED_CANON_CATEGORIES - compared
        if missing:
            failures.append(
                f"source_fidelity_critical_comparison_missing_or_failed:{episode}:"
                + ",".join(sorted(missing))
            )
    return failures


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.source_manifest.resolve()
    canon_path = args.canon_facts.resolve()
    beat_map_path = args.beat_map.resolve()
    failures, chain = validate_source_chain(source_path, canon_path, beat_map_path)
    evidence = {
        "source_manifest_sha256": chain["source_manifest_sha256"],
        "canon_facts_sha256": chain["canon_facts_sha256"],
        "beat_map_sha256": chain["beat_map_sha256"],
    }

    series_chain: dict[str, Any] | None = None
    if args.mode in {"script", "fidelity"}:
        if args.full_series_manifest is None:
            failures.append("full_series_manifest_missing")
        else:
            series_failures, series_chain = validate_series_manifest(
                args.full_series_manifest.resolve(),
                chain,
                args.episode,
                args.canonical_script_sha256,
            )
            failures.extend(series_failures)
            evidence["full_series_manifest_sha256"] = series_chain["full_series_manifest_sha256"]
    if args.mode == "fidelity":
        if args.fidelity_report is None:
            failures.append("source_fidelity_report_missing")
        elif series_chain is not None:
            failures.extend(
                validate_fidelity_report(args.fidelity_report.resolve(), chain, series_chain)
            )
            evidence["source_fidelity_report_sha256"] = sha256_file(args.fidelity_report.resolve())

    status = "PASS" if not failures else {
        "source": "BLOCKED_SOURCE_NOT_READ",
        "script": "BLOCKED_SOURCE_CANON_BINDING_MISSING",
        "fidelity": "BLOCKED_SCRIPT_CANON_MISMATCH",
    }[args.mode]
    return {
        "schema": "qingshan.source_canon_binding_gate_result.v1",
        "gate_id": {
            "source": "SOURCE-READ-COMPLETENESS",
            "script": "SCRIPT-SOURCE-CANON-BINDING",
            "fidelity": "FULL-SERIES-SOURCE-FIDELITY",
        }[args.mode],
        "mode": args.mode,
        "episode": args.episode,
        "invoked": True,
        "status": status,
        "score_100": 100 if not failures else 0,
        "minimum_score_100": 90,
        "evidence": evidence,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "script", "fidelity"), required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--canon-facts", type=Path, required=True)
    parser.add_argument("--beat-map", type=Path, required=True)
    parser.add_argument("--full-series-manifest", type=Path)
    parser.add_argument("--fidelity-report", type=Path)
    parser.add_argument("--episode")
    parser.add_argument("--canonical-script-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(args)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result = {
            "schema": "qingshan.source_canon_binding_gate_result.v1",
            "mode": args.mode,
            "episode": args.episode,
            "invoked": True,
            "status": "FAIL",
            "score_100": 0,
            "minimum_score_100": 90,
            "evidence": {},
            "failures": [f"invalid_gate_evidence:{type(exc).__name__}:{exc}"],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"]}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
