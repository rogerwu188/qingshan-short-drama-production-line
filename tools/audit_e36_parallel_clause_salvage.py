#!/usr/bin/env python3
"""Zero-credit clause salvage audit for actionable E36 dialogue lines 10 and 13."""

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
TRANSCRIPT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V7.json"
OUT_DIR = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/local_clause_salvage_20260731"
QA_DIR = ROOT / "qa/e36_agentcut_20260730/local_clause_salvage_20260731"
SUMMARY = QA_DIR / "E36_LINES10_13_PARALLEL_CLAUSE_SALVAGE_AUDIT_V1.json"
EXPECTED_SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
SOURCE_CL2X = "CL2X-855"
SOURCE_MAILBOX_SHA = "f191f9a2eecd8e8fb43b85e7ce61eeb362bdfad2d9b3d4e7fd048490585289e1"
T2S = OpenCC("t2s")
FFMPEG = shutil.which("ffmpeg") or str(next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg")))

LANES = [
    {
        "line": 10,
        "source": "working_assets/e36_dialogue_audio_refs_20260730/u09_r2_prosody_r2/E36-U09-R2-D02-PROSODY-R2.wav",
        "source_sha256": "5a204d12b2f119139d7ec9339bc05394a7b83d1f649ca981444fac54e9489c80",
        "clauses": [
            ("L10-C1", "从不许拆", 0.00, 1.00),
            ("L10-C2", "小的连字都不识几个", 1.10, 3.60),
            ("L10-C3", "拆了也白拆", 3.70, 5.40),
        ],
    },
    {
        "line": 13,
        "source": "working_assets/e36_dialogue_audio_refs_20260730/u10_line13_prosody_r2/E36-U10-L13-D01-PROSODY-R2.wav",
        "source_sha256": "e0d0efa9548fef63baa561c72146f2708b53e4317df5f1cc1c18e3e9bd152ab5",
        "clauses": [
            ("L13-C1", "小的自己也纳闷", 0.00, 2.45),
            ("L13-C2", "那信封里头一个字都没有", 2.55, 5.35),
            ("L13-C3", "空的", 5.40, 6.25),
        ],
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def canonical_gate() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    transcript = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    lines = {int(row["contract_line_number"]): row for row in transcript["line_results"]}
    checks = {
        "script_exists": SCRIPT.is_file(),
        "manifest_exists": MANIFEST.is_file(),
        "script_sha_locked": sha(SCRIPT) == EXPECTED_SCRIPT_SHA,
        "manifest_matches_script": manifest.get("sha256") == sha(SCRIPT),
        "line10_unproven": not lines[10]["covered_by_bound_accepted_transcripts"],
        "line13_unproven": not lines[13]["covered_by_bound_accepted_transcripts"],
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def make_clips() -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    clips = []
    for lane in LANES:
        source = ROOT / lane["source"]
        if not source.is_file() or sha(source) != lane["source_sha256"]:
            raise SystemExit(f"source gate failed: {source}")
        for clause_id, expected, start, end in lane["clauses"]:
            clip = OUT_DIR / f"E36-{clause_id}.wav"
            subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(clip)],
                check=True,
            )
            clips.append({
                "line": lane["line"],
                "clause_id": clause_id,
                "expected": expected,
                "source": lane["source"],
                "source_sha256": lane["source_sha256"],
                "window_seconds": [start, end],
                "clip": rel(clip),
                "clip_sha256": sha(clip),
            })
    return clips


def audit(clips: list[dict]) -> None:
    models = {
        name: WhisperModel(name, device="cpu", compute_type="int8")
        for name in ("base", "small")
    }
    for clip in clips:
        results = []
        for name, model in models.items():
            for beam in (1, 5, 8):
                for vad in (False, True):
                    segments, _ = model.transcribe(
                        str(ROOT / clip["clip"]), language="zh", beam_size=beam,
                        best_of=max(beam, 1), temperature=0.0,
                        condition_on_previous_text=False, vad_filter=vad,
                    )
                    transcript = "".join(segment.text.strip() for segment in segments)
                    results.append({
                        "model": name,
                        "beam_size": beam,
                        "vad_filter": vad,
                        "transcript": transcript,
                        "normalized_exact": normalize(transcript) == normalize(clip["expected"]),
                    })
        exact = sum(row["normalized_exact"] for row in results)
        clip["exact_count"] = exact
        clip["decode_count"] = len(results)
        clip["status"] = "PASS_ROBUST_EXACT_12_OF_12" if exact == 12 else "FAIL_ROBUST_NOT_EXACT_PRESERVED"
        clip["unique_transcripts"] = sorted({row["transcript"] for row in results})
        clip["results"] = results


def main() -> int:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    gate = canonical_gate()
    if gate["status"] != "PASS":
        raise SystemExit(json.dumps(gate, ensure_ascii=False))
    clips = make_clips()
    audit(clips)
    lines = {}
    for line in (10, 13):
        members = [clip for clip in clips if clip["line"] == line]
        lines[str(line)] = {
            "clauses": members,
            "all_clauses_robust_exact": all(clip["exact_count"] == 12 for clip in members),
            "admission": "READY_FOR_SPLIT_VIDEO_PREPRODUCTION" if all(clip["exact_count"] == 12 for clip in members) else "HOLD_PRESERVE_FAILURES",
        }
    payload = {
        "schema": "qingshan.e36.parallel_clause_salvage_audit.v1",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": SOURCE_MAILBOX_SHA,
        "canonical_gate": gate,
        "method": "Zero-credit source-native clause clips from already-paid materially changed WAVs; base+small x beam1/5/8 x VAD off/on, no prompt or hotwords, OpenCC t2s exact comparison.",
        "lines": lines,
        "credits": {"new_generation_credits": 0, "new_qa_credits": 0, "episode_exact_net": 7964},
        "gate_results": {
            "canonical": "PASS",
            "source_sha_binding": "PASS",
            "line10": lines["10"]["admission"],
            "line13": lines["13"]["admission"],
        },
        "blocked_by": None,
        "next_action": "Build split-video preproduction only for lines whose every clause passes robust12/12; preserve every failed clause and do not submit unchanged paid retries.",
    }
    SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": rel(SUMMARY), "sha256": sha(SUMMARY), "gate_results": payload["gate_results"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
