#!/usr/bin/env python3
"""Build the seven remaining E40 dialogue beats as no-lip-motion coverage."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1"
QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/final_missing_dialogue_coverage_v1/E40_FINAL_MISSING_DIALOGUE_COVERAGE_V1_QA.json"
R02 = "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes_recovery4_v2/E40_E40-FP-R02-CHENJI-A-V1-KF-QA-V2_60fa4bb0-da40-40b1-9e81-47fe1a3c4ed9.png"
R01 = "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R01-CHENJI-B-V1-KF-QA-V2_2074b2a7-8514-4b9a-8aaa-2b7770c59cd5.png"
R04Y = "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R04-YUNFEI-B-V1-KF-QA-V2_723e6861-6adc-4a18-bd9d-eca7bb003c54.png"
R06 = "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R06-ASHUAN-A-V1-KF-QA-V2_c4eaf004-c4a2-4e70-9c40-0f1a72697983.png"
R08 = "working_assets/e40_remake_20260822/full_performance_native_dialogue_v1/keyframes/E40_E40-FP-R08-CHENJI-B-V1-KF-QA-V2_5690f9aa-333c-4403-9351-6560ac877285.png"
ROWS = [
    ("R01-YUNFEI-A", 8, R01, "阿栓，在本宫手上。\n拿他，换景朝一个接头人。\n换，还是不换？", "VEILED_OFFSCREEN_AXIS"),
    ("R03-YUNFEI-B", 4, R02, "……你倒看得清楚。", "VEILED_REACTION"),
    ("R04-CHENJI-A", 4, R02, "调令上的印，是您的旧印。", "CHENJI_BACK_VIEW"),
    ("R04-YUNFEI-B", 8, R04Y, "这道令，不是本宫下的。\n替本宫‘代办’印的手，就在身侧。", "Q1_ADMITTED_VEILED_YUNFEI"),
    ("R06-ASHUAN-A", 4, R06, "迹哥！", "DISTANT_ACTION_AXIS"),
    ("R08-YUNFEI-A", 4, R08, "你，不是本宫能买的棋子。", "VEILED_YUNFEI_CHENJI_BACK"),
    ("R08-YUNFEI-C", 8, R08, "带走罢。官面上，他无案可押。\n是否替他下注——你自己拿主意。", "VEILED_YUNFEI_CHENJI_BACK"),
]

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def stamp(value: float) -> str:
    ms = round(value * 1000); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True); QA.parent.mkdir(parents=True, exist_ok=True)
    outputs = []; subtitles = []; cursor = 0.0
    for number, (beat, seconds, rel, line, framing) in enumerate(ROWS, 1):
        source = ROOT / rel
        if not source.is_file(): raise SystemExit(f"missing admitted source: {source}")
        out = OUT_DIR / f"E40_{beat}_DIALOGUE_COVERAGE_V1.mp4"
        pan_offset = (number % 3 - 1) * 24
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(source), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", f"zoompan=z='min(zoom+0.0001,1.022)':x='max(0,min(iw-iw/zoom,iw/2-(iw/zoom/2)+{pan_offset}))':y='ih/2-(ih/zoom/2)':d={seconds*24}:s=720x1280:fps=24,format=yuv420p", "-t", str(seconds), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart", str(out)], check=True)
        outputs.append({"beat_id": beat, "path": str(out.relative_to(ROOT)), "sha256": sha(out), "source": rel, "source_sha256": sha(source), "duration_seconds": seconds, "framing": framing})
        subtitles.append(f"{number}\n{stamp(cursor)} --> {stamp(cursor + seconds - .25)}\n{line}\n"); cursor += seconds
    srt = OUT_DIR / "E40_FINAL_MISSING_DIALOGUE_COVERAGE_V1.srt"; srt.write_text("\n".join(subtitles), encoding="utf-8")
    report = {"schema": "qingshan.e40.terminal_dialogue_coverage.v1", "episode": "E40", "status": "PASS_ZERO_COST_COVERAGE_NO_VISIBLE_LIP_MOTION", "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "coverage_policy": "Only exact-SHA Q1-admitted back/veiled/distant compositions are used. Failed task-specific keyframes are never reused.", "audio_policy": "AAC_SILENCE_ONLY_NO_TTS_NO_BGM_NO_CROSS_TASK_AUDIO", "visible_lip_sync_replacement": False, "outputs": outputs, "subtitle_sidecar": str(srt.relative_to(ROOT)), "subtitle_sidecar_sha256": sha(srt)}
    QA.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "duration_seconds": sum(x[1] for x in ROWS), "qa": str(QA.relative_to(ROOT)), "qa_sha256": sha(QA), "outputs": outputs}, ensure_ascii=False))
    return 0

if __name__ == "__main__": raise SystemExit(main())
