#!/usr/bin/env python3
"""adforge_adapter.py — Mode B tail-ad adapter (brief -> generated ad clip).

AdForge (~/adforge, a separate, independently-evolving repo) is an optional
external engine.  When it is not configured, or a required local patch is
missing (see spec §四), this adapter fails closed with
``{"status": "ADAPTER_REQUIRED"}`` and nalu proceeds without ads — never a
crash, never a half-attempt.

Sequencing hard rule (spec §四, the demo's own K-lesson): generate narration
FIRST, measure its actual rendered duration, THEN size the video shot to that
duration (clamped into the slot contract's [min,max]).  Reversing this order
is exactly how the demo wasted credits (CTA line didn't fit a pre-committed
5s shot).  The CTA URL is captioned only, never spoken.

Web brief materials (``assets``/``brand_docs``) are read-only: this adapter
never follows links, fills forms, or downloads executables — only local file
paths or plain text already present in the brief are used.
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

try:
    from lines.nalu.runtime.tools.nalu_media_tools import require_ffprobe
except ModuleNotFoundError:
    sys.path.insert(0, str(ENGINE / "lines/nalu/runtime/tools"))
    from nalu_media_tools import require_ffprobe  # type: ignore


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def adapter_required(detail: str) -> dict[str, Any]:
    return {"status": "ADAPTER_REQUIRED", "detail": detail}


def _resolve_adforge_root() -> Path | None:
    raw = os.environ.get("ADFORGE_ROOT", "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser()
    return root if root.is_dir() else None


def _probe_capabilities(root: Path) -> list[str]:
    """Confirm the three local patches spec §四 depends on are present.  Whether
    to upstream them as a real AdForge PR is the line owner's call, not this
    adapter's — it only declares the version requirement and fails closed."""
    problems: list[str] = []
    generate_ad = root / "scripts/generate_ad.py"
    if not generate_ad.is_file():
        return [f"MISSING:{generate_ad}"]
    source = generate_ad.read_text(encoding="utf-8", errors="ignore")
    if "load_dotenv" not in source:
        problems.append("PATCH_MISSING:generate_ad.py does not read .env")
    if "SPEC" not in source or "aspect_ratio" not in source:
        problems.append("PATCH_MISSING:generate_ad.py does not read spec from project.json")
    verify_media = root / "packages/post/verify_media.py"
    if not verify_media.is_file():
        problems.append(f"MISSING:{verify_media}")
    else:
        try:
            spec = importlib.util.spec_from_file_location("adforge_verify_media", verify_media)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            params = inspect.signature(module.verify).parameters
            if "expected_duration" not in params or "expected_ratio" not in params:
                problems.append("PATCH_MISSING:verify_media.verify lacks expected_duration/expected_ratio")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"VERIFY_MEDIA_IMPORT_FAILED:{exc}")
    return problems


def _load_audio_adapter(root: Path):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from packages.providers.audio import AudioProviderError, GiggleAudioAdapter  # type: ignore
    return GiggleAudioAdapter, AudioProviderError


def _ffprobe_duration(path: Path) -> float:
    result = subprocess.run([require_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", str(path)], text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr[-2000:]}")
    return float(result.stdout.strip())


def _narration_text(brief: dict[str, Any]) -> str:
    """Spoken script: hook + proof lines.  CTA is deliberately excluded — it is
    caption-only, per the slot contract."""
    parts = []
    idea = str(brief.get("idea") or "").strip()
    if idea:
        parts.append(idea)
    for proof in brief.get("proof") or []:
        text = str(proof).strip()
        if text:
            parts.append(text)
    return "".join(parts) if parts else str(brief.get("idea") or brief.get("cta") or "")


def _build_project_json(brief: dict[str, Any], *, sku: str, shot_duration_seconds: float) -> dict[str, Any]:
    cta = str(brief.get("cta") or "")
    narration_text = _narration_text(brief)
    return {
        "product_name": brief.get("product_name") or sku,
        "product_description": brief.get("idea") or "",
        "lang": "zh",
        "mode": "BR",
        "aspect_ratio": "9:16",
        "shot_duration_seconds": round(shot_duration_seconds, 1),
        "resolution": "720p",
        "shots": [[f"{sku}_tail", brief.get("idea") or narration_text]],
        "creative_brief": {"hook": narration_text[:40], "proof": brief.get("proof") or [], "cta": cta},
        "identity_contract": brief.get("identity_contract") or {},
        "verified_selling_points": brief.get("verified_selling_points") or [],
        "unverified_claims": brief.get("unverified_claims") or [],
        "narration_lines": [{"t": [0.0, shot_duration_seconds], "text": narration_text}],
        "subtitle_style": brief.get("subtitle_style") or {},
        # CTA is a caption-layer concern (ad_tail_package.py burns it via --subtitle-ass /
        # --cta-text), never part of the spoken narration script above.
        "cta_caption_only": cta,
    }


def generate(*, brief_path: Path, sku: str, episode: str, run_id: str,
             voice_reference: Path | None, slot_contract_path: Path,
             out_video: Path, out_report: Path, paid: bool) -> dict[str, Any]:
    root = _resolve_adforge_root()
    if root is None:
        return adapter_required("ADFORGE_ROOT is not set or is not a directory")
    problems = _probe_capabilities(root)
    if problems:
        return adapter_required("; ".join(problems))

    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    slot = json.loads(slot_contract_path.read_text(encoding="utf-8"))
    dur = slot["duration_seconds"]
    project_dir = root / "projects" / sku
    project_dir.mkdir(parents=True, exist_ok=True)
    narration_path = project_dir / "narration.mp3"
    narration_text = _narration_text(brief)

    if not paid:
        planned_project = _build_project_json(brief, sku=sku, shot_duration_seconds=float(dur["min"]))
        planned_project_path = project_dir / "project.json"
        planned_project_path.write_text(json.dumps(planned_project, ensure_ascii=False, indent=2), encoding="utf-8")
        planned_cmd = [sys.executable, str(root / "scripts/generate_ad.py"), "--project", sku,
                       "--run-id", run_id, "--audio-mode", "auto"]
        report = {"status": "DRY_PLANNED", "sku": sku, "episode": episode, "run_id": run_id,
                  "project_json": str(planned_project_path), "narration_text": narration_text,
                  "planned_tts_call": "GiggleAudioAdapter.generate_tts (not invoked, --paid not set)",
                  "planned_generate_ad_argv": planned_cmd, "recorded_at": now()}
        out_report.parent.mkdir(parents=True, exist_ok=True)
        out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report

    # Step 1: narration FIRST (spec §四's own lesson — never reverse this order).
    try:
        GiggleAudioAdapter, AudioProviderError = _load_audio_adapter(root)
        adapter = GiggleAudioAdapter(root)
        if voice_reference is not None and voice_reference.is_file():
            # this show's protagonist voice reference, when the brief doesn't override
            pass  # GiggleAudioAdapter.generate_tts's own voice selection is provider-side;
                  # a reference-audio clone path is a future extension, not required by the demo.
        adapter.generate_tts(narration_text, narration_path, run_id)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "sku": sku, "episode": episode,
                "failures": [f"NARRATION_TTS_FAILED:{type(exc).__name__}:{exc}"], "recorded_at": now()}

    measured_duration = _ffprobe_duration(narration_path)
    shot_duration = max(float(dur["min"]), min(float(dur["max"]), measured_duration + 0.5))
    if narration_text.strip() and str(brief.get("cta") or "").strip() in narration_text:
        return {"status": "FAIL", "sku": sku, "episode": episode,
                "failures": ["CTA_URL_LEAKED_INTO_NARRATION_SCRIPT"], "recorded_at": now()}

    project = _build_project_json(brief, sku=sku, shot_duration_seconds=shot_duration)
    project_json_path = project_dir / "project.json"
    project_json_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    # Step 2: video generation, only now that the shot duration matches the real narration.
    argv = [sys.executable, str(root / "scripts/generate_ad.py"), "--project", sku,
            "--run-id", run_id, "--audio-mode", "auto"]
    result = subprocess.run(argv, cwd=str(root), text=True, capture_output=True)
    if result.returncode != 0:
        return {"status": "FAIL", "sku": sku, "episode": episode,
                "failures": [f"GENERATE_AD_FAILED:{result.stderr[-4000:]}"],
                "argv": argv, "recorded_at": now()}

    outputs_dir = project_dir / "outputs"
    candidates = sorted(outputs_dir.glob(f"*{run_id}*.mp4")) or sorted(outputs_dir.glob("*.mp4"))
    if not candidates:
        return {"status": "FAIL", "sku": sku, "episode": episode,
                "failures": [f"NO_OUTPUT_VIDEO_IN:{outputs_dir}"], "recorded_at": now()}
    produced = max(candidates, key=lambda path: path.stat().st_mtime)
    out_video.parent.mkdir(parents=True, exist_ok=True)
    out_video.write_bytes(produced.read_bytes())

    report = {"status": "PASS", "sku": sku, "episode": episode, "run_id": run_id,
              "project_json": str(project_json_path), "narration_path": str(narration_path),
              "narration_measured_seconds": round(measured_duration, 3),
              "shot_duration_seconds": shot_duration, "source_output": str(produced),
              "out_video": str(out_video), "recorded_at": now()}
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("generate")
    p.add_argument("--brief", required=True, type=Path)
    p.add_argument("--sku", required=True)
    p.add_argument("--episode", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--voice-reference", type=Path)
    p.add_argument("--slot-contract", required=True, type=Path)
    p.add_argument("--out-video", required=True, type=Path)
    p.add_argument("--out-report", required=True, type=Path)
    p.add_argument("--paid", action="store_true")
    args = parser.parse_args()

    report = generate(
        brief_path=args.brief.resolve(), sku=args.sku, episode=args.episode, run_id=args.run_id,
        voice_reference=args.voice_reference.resolve() if args.voice_reference else None,
        slot_contract_path=args.slot_contract.resolve(),
        out_video=args.out_video.resolve(), out_report=args.out_report.resolve(), paid=args.paid,
    )
    print(json.dumps({k: v for k, v in report.items() if k not in ("narration_text",)}, ensure_ascii=False))
    if report["status"] == "ADAPTER_REQUIRED":
        return 2
    return 0 if report["status"] in ("PASS", "DRY_PLANNED") else 3


if __name__ == "__main__":
    raise SystemExit(main())
