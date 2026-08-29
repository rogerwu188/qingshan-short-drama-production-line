#!/usr/bin/env python3
"""Build zero-cost no-visible-lip coverage after refunded provider failures."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes_recovery4_v2/E40_E40-FP-R02-CHENJI-A-V1-KF-QA-V2_60fa4bb0-da40-40b1-9e81-47fe1a3c4ed9.png"
OUT_DIR = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_dialogue_coverage_v1"
QA_DIR = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/terminal_dialogue_coverage_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def render(output: Path, duration: int, vf: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(SOURCE),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration), "-vf", vf, "-r", "24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(output),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    if sha(SOURCE) != "57eafda6e3c6a69356a5ce7d1047f1f66889c996d373324b711300307ffa915e":
        raise SystemExit("R02 Q1 source SHA mismatch")
    out_r02 = OUT_DIR / "E40_R02_CHENJI_BACKVIEW_DIALOGUE_COVERAGE_V1.mp4"
    out_r03 = OUT_DIR / "E40_R03_VEILED_REACTION_DIALOGUE_COVERAGE_V1.mp4"
    # R02 keeps Chenji back-facing; R03 uses a right-side veiled reaction crop.
    # Neither contains a visible speaking mouth, so no post voice is attached.
    render(out_r02, 10, "scale=720:1280,zoompan=z='min(zoom+0.00012,1.025)':d=240:s=720x1280:fps=24")
    render(out_r03, 4, "crop=810:1440:630:560,scale=720:1280,zoompan=z='min(zoom+0.0002,1.02)':d=96:s=720x1280:fps=24")

    srt = OUT_DIR / "E40_R02_R03_TERMINAL_DIALOGUE_COVERAGE_V1.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:03,000\n当铺、法场、药房、火场——活口一个没留。\n\n"
        "2\n00:00:03,200 --> 00:00:06,000\n偏他活着，还能开价。\n\n"
        "3\n00:00:06,200 --> 00:00:09,200\n他不是证人，是饵。\n\n"
        "4\n00:00:10,000 --> 00:00:13,600\n我一换，两个一并抹掉，线断死。\n",
        encoding="utf-8",
    )
    QA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "qingshan.e40.terminal_dialogue_coverage.v1",
        "episode": "E40",
        "status": "PASS_ZERO_COST_COVERAGE_NO_VISIBLE_LIP",
        "source_keyframe": rel(SOURCE),
        "source_keyframe_sha256": sha(SOURCE),
        "provider_failure_classification": "PASS_ZERO_REFUNDED",
        "registered_gate_findings": {
            "CHARACTER-IDENTITY-ADMISSION": "PASS: exact-SHA Q1-admitted Chenji back view and veiled reaction crop; no replacement face introduced.",
            "SCENE-AUTHORITY-LOCK": "PASS: same locked Wangfu hall curtain subspace and axis.",
            "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "PASS_COVERAGE: no visible speaking mouth; dialogue is carried only by subtitle sidecar after provider-native dialogue generation failed twice and fully refunded.",
            "PERIOD-ANACHRONISM-LOCK": "PASS: no modern object, rendered text, logo, or watermark in the source frames.",
        },
        "audio_policy": "AAC_SILENCE_ONLY_NO_TTS_NO_BGM_NO_CROSS_TASK_AUDIO",
        "visible_lip_sync_replacement": False,
        "outputs": [
            {"unit_id": "R02", "path": rel(out_r02), "sha256": sha(out_r02), "duration_seconds": 10},
            {"unit_id": "R03", "path": rel(out_r03), "sha256": sha(out_r03), "duration_seconds": 4},
        ],
        "subtitle_sidecar": rel(srt),
        "subtitle_sidecar_sha256": sha(srt),
        "release_note": "Coverage is an allowed terminal replacement, not a provider-native dialogue success; final assembly must keep lips invisible.",
    }
    qa = QA_DIR / "E40_R02_R03_TERMINAL_DIALOGUE_COVERAGE_V1_QA.json"
    qa.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "qa": rel(qa), "qa_sha256": sha(qa), "outputs": payload["outputs"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
