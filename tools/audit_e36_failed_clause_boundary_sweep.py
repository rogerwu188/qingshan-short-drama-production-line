#!/usr/bin/env python3
"""Zero-credit boundary sweep for the three remaining E36 clause failures."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
PRIOR = ROOT / "qa/e36_agentcut_20260730/local_clause_salvage_20260731/E36_LINES10_13_PARALLEL_CLAUSE_SALVAGE_AUDIT_V1.json"
OUT_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/local_clause_salvage_20260731/boundary_sweep"
SUMMARY = ROOT / "qa/e36_agentcut_20260730/local_clause_salvage_20260731/E36_FAILED_CLAUSE_BOUNDARY_SWEEP_V1.json"
EXPECTED_SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
SOURCE_CL2X = "CL2X-855"
MAILBOX_SHA = "f191f9a2eecd8e8fb43b85e7ce61eeb362bdfad2d9b3d4e7fd048490585289e1"
T2S = OpenCC("t2s")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))

LANES = [
    {
        "clause_id": "L10-C1",
        "line": 10,
        "expected": "从不许拆",
        "source": "working_assets/e36_dialogue_audio_refs_20260730/u09_r2_prosody_r2/E36-U09-R2-D02-PROSODY-R2.wav",
        "source_sha256": "5a204d12b2f119139d7ec9339bc05394a7b83d1f649ca981444fac54e9489c80",
        "windows": [(0.00, 0.80), (0.00, 0.90), (0.00, 1.00), (0.00, 1.15)],
    },
    {
        "clause_id": "L10-C2",
        "line": 10,
        "expected": "小的连字都不识几个",
        "source": "working_assets/e36_dialogue_audio_refs_20260730/u09_r2_prosody_r2/E36-U09-R2-D02-PROSODY-R2.wav",
        "source_sha256": "5a204d12b2f119139d7ec9339bc05394a7b83d1f649ca981444fac54e9489c80",
        "windows": [(1.15, 3.50), (1.20, 3.50), (1.15, 3.55), (1.20, 3.55)],
    },
    {
        "clause_id": "L13-C1",
        "line": 13,
        "expected": "小的自己也纳闷",
        "source": "working_assets/e36_dialogue_audio_refs_20260730/u10_line13_prosody_r2/E36-U10-L13-D01-PROSODY-R2.wav",
        "source_sha256": "e0d0efa9548fef63baa561c72146f2708b53e4317df5f1cc1c18e3e9bd152ab5",
        "windows": [(0.00, 2.28), (0.00, 2.35), (0.00, 2.45), (0.00, 2.55)],
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def gate() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    prior_counts = {
        row["clause_id"]: row["exact_count"]
        for line in prior["lines"].values()
        for row in line["clauses"]
    }
    checks = {
        "script_exists": SCRIPT.is_file(),
        "manifest_exists": MANIFEST.is_file(),
        "prior_audit_exists": PRIOR.is_file(),
        "script_sha_locked": sha(SCRIPT) == EXPECTED_SCRIPT_SHA,
        "manifest_matches_script": manifest.get("sha256") == sha(SCRIPT),
        "prior_failed_clause_set_exact": set(prior_counts) >= {"L10-C1", "L10-C2", "L13-C1"},
        "prior_failures_preserved": all(prior_counts[c] < 12 for c in ("L10-C1", "L10-C2", "L13-C1")),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "prior_exact_counts": prior_counts}


def make_clip(lane: dict, index: int, start: float, end: float) -> Path:
    source = ROOT / lane["source"]
    if not source.is_file() or sha(source) != lane["source_sha256"]:
        raise SystemExit(f"source SHA gate failed: {source}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clip = OUT_DIR / f"E36-{lane['clause_id']}-B{index:02d}.wav"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(clip)],
        check=True,
    )
    return clip


def decode(models: dict[str, WhisperModel], clip: Path, expected: str) -> dict:
    results = []
    for name, model in models.items():
        for beam in (1, 5, 8):
            for vad in (False, True):
                segments, _ = model.transcribe(
                    str(clip), language="zh", beam_size=beam, best_of=max(beam, 1),
                    temperature=0.0, condition_on_previous_text=False, vad_filter=vad,
                )
                transcript = "".join(segment.text.strip() for segment in segments)
                results.append({
                    "model": name,
                    "beam_size": beam,
                    "vad_filter": vad,
                    "transcript": transcript,
                    "normalized_exact": normalize(transcript) == normalize(expected),
                })
    exact = sum(row["normalized_exact"] for row in results)
    return {
        "exact_count": exact,
        "decode_count": len(results),
        "status": "PASS_ROBUST_EXACT_12_OF_12" if exact == 12 else "FAIL_ROBUST_NOT_EXACT_PRESERVED",
        "unique_transcripts": sorted({row["transcript"] for row in results}),
        "results": results,
    }


def main() -> int:
    canonical_gate = gate()
    if canonical_gate["status"] != "PASS":
        raise SystemExit(json.dumps(canonical_gate, ensure_ascii=False))
    models = {name: WhisperModel(name, device="cpu", compute_type="int8") for name in ("base", "small")}
    lanes = []
    for lane in LANES:
        variants = []
        for index, (start, end) in enumerate(lane["windows"], 1):
            clip = make_clip(lane, index, start, end)
            variants.append({
                "variant_id": f"{lane['clause_id']}-B{index:02d}",
                "window_seconds": [start, end],
                "clip": rel(clip),
                "clip_sha256": sha(clip),
                **decode(models, clip, lane["expected"]),
            })
        best = max(variants, key=lambda row: row["exact_count"])
        lanes.append({
            "line": lane["line"],
            "clause_id": lane["clause_id"],
            "expected": lane["expected"],
            "source": lane["source"],
            "source_sha256": lane["source_sha256"],
            "variants": variants,
            "best_variant_id": best["variant_id"],
            "best_exact_count": best["exact_count"],
            "robust_ready": best["exact_count"] == 12,
        })
    ready = [lane["clause_id"] for lane in lanes if lane["robust_ready"]]
    failed = [lane["clause_id"] for lane in lanes if not lane["robust_ready"]]
    payload = {
        "schema": "qingshan.e36.failed_clause_boundary_sweep.v1",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_gate": canonical_gate,
        "method": "Twelve zero-credit source-native boundary variants across the three remaining failed clauses; base+small x beam1/5/8 x VAD off/on, no prompt/hotwords, OpenCC t2s.",
        "lanes": lanes,
        "summary": {
            "variant_count": sum(len(lane["variants"]) for lane in lanes),
            "robust_ready_clauses": ready,
            "still_failed_clauses": failed,
            "all_remaining_clauses_robust_ready": not failed,
        },
        "credits": {"new_generation_credits": 0, "new_qa_credits": 0, "episode_exact_net": 7966},
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "source_sha_binding": "PASS",
            "prior_failures_preserved": "PASS",
            "boundary_sweep": "PASS_EXECUTED",
            "split_video_preproduction": "READY" if not failed else "HOLD",
        },
        "blocked_by": None,
        "next_action": "Use only a robust12/12 boundary variant for split-video preproduction; preserve all non-12/12 variants and do not submit unchanged paid retries.",
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": rel(SUMMARY), "sha256": sha(SUMMARY), "summary": payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
