#!/usr/bin/env python3
"""Fail closed unless a release candidate contains subtitles and Nalu outro."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str | None, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _enabled_caption_rows(project: dict) -> list[dict]:
    rows: list[dict] = []
    for track in project.get("timeline", {}).get("subtitleTracks", []):
        if track.get("enabled", True):
            rows.extend(row for row in track.get("clips", []) if isinstance(row, dict))
    return rows


def evaluate(
    project: dict,
    *,
    root: Path = ROOT,
    render_manifest: dict | None = None,
    final_video: Path | None = None,
) -> dict:
    failures: list[str] = []
    expected_ids = [str(value) for value in project.get("expectedDialogueIds", [])]
    caption_rows = _enabled_caption_rows(project)
    caption_ids = [str(row.get("dialogue_id") or "") for row in caption_rows]

    if project.get("requireBurnedSubtitles") is not True:
        failures.append("burned_subtitles_not_required")
    if not expected_ids:
        failures.append("expected_dialogue_ids_missing")
    if caption_ids != expected_ids:
        failures.append("subtitle_order_or_coverage_mismatch")
    if len(caption_ids) != len(set(caption_ids)):
        failures.append("duplicate_subtitle_dialogue_ids")
    subtitle_contract = project.get("metadata", {}).get("subtitle_contract", {})
    expected_coverage = f"{len(expected_ids)}/{len(expected_ids)}"
    if subtitle_contract.get("burned_in") is not True:
        failures.append("subtitle_contract_not_burned_in")
    if subtitle_contract.get("coverage") != expected_coverage:
        failures.append("subtitle_contract_coverage_mismatch")

    outro = project.get("outro") or {}
    if project.get("requireBrandedOutro") is not True:
        failures.append("branded_outro_not_required")
    if outro.get("enabled") is not True:
        failures.append("outro_not_enabled")
    if str(outro.get("brand") or "").lower() != "nalu_motion":
        failures.append("outro_brand_mismatch")
    if float(outro.get("duration") or 0) < 2.5:
        failures.append("outro_duration_too_short")
    if outro.get("includeInTotalDuration") is not True:
        failures.append("outro_not_in_total_duration")
    for field in ("assetPath", "audioPath"):
        path = resolve_path(outro.get(field), root)
        if not path or not path.is_file():
            failures.append(f"outro_{field}_missing")

    if project.get("releaseGate", {}).get("required") is not True:
        failures.append("agentcut_release_gate_not_required")

    media_sha = None
    if final_video is not None:
        final_video = final_video.expanduser().resolve()
        if not final_video.is_file():
            failures.append("final_video_missing")
        else:
            media_sha = sha256(final_video)
        if render_manifest is None:
            failures.append("render_manifest_missing")

    if render_manifest is not None:
        coverage = render_manifest.get("coverage", {}).get("subtitles", {})
        if coverage.get("required") is not True:
            failures.append("render_subtitles_not_required")
        if coverage.get("count") != expected_coverage:
            failures.append("render_subtitle_coverage_mismatch")
        rendered_outro = render_manifest.get("outro", {})
        if rendered_outro.get("present") is not True:
            failures.append("render_outro_missing")
        if str(rendered_outro.get("brand") or "").lower() != "nalu_motion":
            failures.append("render_outro_brand_mismatch")
        if rendered_outro.get("endsAtTimelineEnd") is not True:
            failures.append("render_outro_not_at_timeline_end")
        if media_sha:
            manifest_sha = str(
                render_manifest.get("releaseGate", {}).get("finalSha256")
                or render_manifest.get("finalSha256")
                or ""
            ).lower()
            if manifest_sha != media_sha:
                failures.append("render_manifest_final_sha_mismatch")

    return {
        "schema": "qingshan.release_branding_contract_gate.v1",
        "episode": str(project.get("metadata", {}).get("episode") or "").upper(),
        "status": "PASS" if not failures else "FAIL",
        "hard_gate_passed": not failures,
        "subtitle_coverage": expected_coverage if expected_ids else "0/0",
        "subtitle_event_count": len(caption_rows),
        "nalu_motion_outro_required": True,
        "final_sha256": media_sha,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--render-manifest")
    parser.add_argument("--final-video")
    parser.add_argument("--out")
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    render_manifest = None
    if args.render_manifest:
        render_manifest = json.loads(
            Path(args.render_manifest).expanduser().resolve().read_text(encoding="utf-8")
        )
    final_video = Path(args.final_video) if args.final_video else None
    result = evaluate(
        project,
        root=ROOT,
        render_manifest=render_manifest,
        final_video=final_video,
    )
    result["project"] = str(project_path)
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["hard_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
