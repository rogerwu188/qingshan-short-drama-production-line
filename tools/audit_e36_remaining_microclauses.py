#!/usr/bin/env python3
"""Fine-boundary and micro-clause source audit for E36 lines 10 and 13."""

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
PRIOR = ROOT / "qa/e36_agentcut_20260730/local_clause_salvage_20260731/E36_FAILED_CLAUSE_BOUNDARY_SWEEP_V1.json"
OUT_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/local_clause_salvage_20260731/microclauses"
SUMMARY = ROOT / "qa/e36_agentcut_20260730/local_clause_salvage_20260731/E36_REMAINING_MICROCLAUSE_AUDIT_V1.json"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
SOURCE_CL2X = "CL2X-856"
MAILBOX_SHA = "3e12aed6afdc0540f07ea50487cd3f19c15699cf0c91d13736c032cab944da79"
T2S = OpenCC("t2s")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))

L10_SOURCE = "working_assets/e36_dialogue_audio_refs_20260730/u09_r2_prosody_r2/E36-U09-R2-D02-PROSODY-R2.wav"
L10_SHA = "5a204d12b2f119139d7ec9339bc05394a7b83d1f649ca981444fac54e9489c80"
L13_SOURCE = "working_assets/e36_dialogue_audio_refs_20260730/u10_line13_prosody_r2/E36-U10-L13-D01-PROSODY-R2.wav"
L13_SHA = "e0d0efa9548fef63baa561c72146f2708b53e4317df5f1cc1c18e3e9bd152ab5"

LANES = [
    {"id": "L10-C1-FINE", "line": 10, "expected": "从不许拆", "source": L10_SOURCE, "sha": L10_SHA,
     "windows": [(0.00, end) for end in (0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96)]},
    {"id": "L10-C2A", "line": 10, "expected": "小的连字都", "source": L10_SOURCE, "sha": L10_SHA,
     "windows": [(1.15, 2.74), (1.20, 2.74)]},
    {"id": "L10-C2B", "line": 10, "expected": "不识几个", "source": L10_SOURCE, "sha": L10_SHA,
     "windows": [(2.72, 3.50), (2.74, 3.50), (2.72, 3.55)]},
    {"id": "L13-C1A", "line": 13, "expected": "小的自己", "source": L13_SOURCE, "sha": L13_SHA,
     "windows": [(0.00, 1.08), (0.00, 1.16)]},
    {"id": "L13-C1B", "line": 13, "expected": "也纳闷", "source": L13_SOURCE, "sha": L13_SHA,
     "windows": [(1.08, 2.28), (1.08, 2.40), (1.10, 2.35)]},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def norm(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def gate() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    checks = {
        "script_exists": SCRIPT.is_file(),
        "manifest_exists": MANIFEST.is_file(),
        "prior_boundary_audit_exists": PRIOR.is_file(),
        "script_sha_locked": sha(SCRIPT) == SCRIPT_SHA,
        "manifest_matches_script": manifest.get("sha256") == sha(SCRIPT),
        "prior_still_failed_set_exact": set(prior["summary"]["still_failed_clauses"]) == {"L10-C1", "L10-C2", "L13-C1"},
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "prior_sha256": sha(PRIOR)}


def clip(lane: dict, index: int, start: float, end: float) -> Path:
    source = ROOT / lane["source"]
    if not source.is_file() or sha(source) != lane["sha"]:
        raise SystemExit(f"source SHA gate failed: {source}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"E36-{lane['id']}-V{index:02d}.wav"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out)],
        check=True,
    )
    return out


def audit(models: dict[str, WhisperModel], audio: Path, expected: str) -> dict:
    rows = []
    for model_name, model in models.items():
        for beam in (1, 5, 8):
            for vad in (False, True):
                segments, _ = model.transcribe(
                    str(audio), language="zh", beam_size=beam, best_of=max(beam, 1),
                    temperature=0.0, condition_on_previous_text=False, vad_filter=vad,
                )
                transcript = "".join(segment.text.strip() for segment in segments)
                rows.append({
                    "model": model_name, "beam_size": beam, "vad_filter": vad,
                    "transcript": transcript, "normalized_exact": norm(transcript) == norm(expected),
                })
    exact = sum(row["normalized_exact"] for row in rows)
    return {
        "exact_count": exact,
        "decode_count": len(rows),
        "status": "PASS_ROBUST_EXACT_12_OF_12" if exact == 12 else "FAIL_ROBUST_NOT_EXACT_PRESERVED",
        "unique_transcripts": sorted({row["transcript"] for row in rows}),
        "results": rows,
    }


def main() -> int:
    canonical_gate = gate()
    if canonical_gate["status"] != "PASS":
        raise SystemExit(json.dumps(canonical_gate, ensure_ascii=False))
    models = {name: WhisperModel(name, device="cpu", compute_type="int8") for name in ("base", "small")}
    results = []
    for lane in LANES:
        variants = []
        for index, (start, end) in enumerate(lane["windows"], 1):
            audio = clip(lane, index, start, end)
            variants.append({
                "variant_id": f"{lane['id']}-V{index:02d}", "window_seconds": [start, end],
                "clip": rel(audio), "clip_sha256": sha(audio), **audit(models, audio, lane["expected"]),
            })
        best = max(variants, key=lambda row: row["exact_count"])
        results.append({
            "lane_id": lane["id"], "line": lane["line"], "expected": lane["expected"],
            "source": lane["source"], "source_sha256": lane["sha"], "variants": variants,
            "best_variant_id": best["variant_id"], "best_exact_count": best["exact_count"],
            "robust_ready": best["exact_count"] == 12,
        })
    by_id = {row["lane_id"]: row for row in results}
    line10_ready = all(by_id[key]["robust_ready"] for key in ("L10-C1-FINE", "L10-C2A", "L10-C2B"))
    line13_ready = all(by_id[key]["robust_ready"] for key in ("L13-C1A", "L13-C1B"))
    payload = {
        "schema": "qingshan.e36.remaining_microclause_audit.v1",
        "episode": "E36", "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_gate": canonical_gate,
        "method": "Fine boundary sweep for L10-C1 plus natural micro-clause splits for L10-C2 and L13-C1; base+small x beam1/5/8 x VAD off/on, no prompt/hotwords, OpenCC t2s, zero credits.",
        "lanes": results,
        "summary": {
            "variant_count": sum(len(row["variants"]) for row in results),
            "robust_ready_lanes": [row["lane_id"] for row in results if row["robust_ready"]],
            "still_failed_lanes": [row["lane_id"] for row in results if not row["robust_ready"]],
            "line10_all_required_microclauses_ready": line10_ready,
            "line13_all_required_microclauses_ready": line13_ready,
        },
        "credits": {"new_generation_credits": 0, "new_qa_credits": 0, "episode_exact_net": 7966},
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT", "source_sha_binding": "PASS",
            "microclause_audit": "PASS_EXECUTED", "line10_split_video": "READY" if line10_ready else "HOLD",
            "line13_split_video": "READY" if line13_ready else "HOLD",
        },
        "blocked_by": None,
        "next_action": "Only robust12/12 natural micro-clauses may enter split-video preproduction; preserve failures and prohibit unchanged paid retry.",
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": rel(SUMMARY), "sha256": sha(SUMMARY), "summary": payload["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
