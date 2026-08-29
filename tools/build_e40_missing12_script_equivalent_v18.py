#!/usr/bin/env python3
"""Build all seven E40 missing-dialogue groups as non-dialogue visual candidates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "working_assets/e40_remake_20260822"
KF = BASE / "full_performance_native_dialogue_v1/keyframes"
KF_R = BASE / "full_performance_native_dialogue_v1/keyframes_recovery4_v2"
OUT_DIR = BASE / "full_performance_native_dialogue_v1/script_equivalent_v18"
V16_QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX_QA.json"
V16 = BASE / "assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V16_R04_DIALOGUE_ORDER_FIX.mp4"
V18 = BASE / "assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V18_MISSING12_SCRIPT_EQUIVALENT.mp4"
QA = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/script_equivalent_v18/E40_MISSING12_SCRIPT_EQUIVALENT_CANDIDATES_QA_V1.json"
V18_QA = ROOT / "qa/e40_remake_20260822/assembly_candidate_v1/E40_CURRENT_ALL_UNIT_COVERAGE_SEQUENCE_V18_MISSING12_SCRIPT_EQUIVALENT_QA.json"

IMG = {
    "ashuan": KF / "E40_E40-FP-R06-ASHUAN-A-V1-KF-QA-V2_c4eaf004-c4a2-4e70-9c40-0f1a72697983.png",
    "offer": KF / "E40_E40-FP-R01-CHENJI-B-V1-KF-QA-V2_2074b2a7-8514-4b9a-8aaa-2b7770c59cd5.png",
    "chenji": KF_R / "E40_E40-FP-R02-CHENJI-A-V1-KF-QA-V2_60fa4bb0-da40-40b1-9e81-47fe1a3c4ed9.png",
    "yunfei": KF / "E40_E40-FP-R04-YUNFEI-B-V1-KF-QA-V2_723e6861-6adc-4a18-bd9d-eca7bb003c54.png",
    "decision": KF / "E40_E40-FP-R08-CHENJI-B-V1-KF-QA-V2_5690f9aa-333c-4403-9351-6560ac877285.png",
    "frost_evidence": KF_R / "E40_E40-FP-R03-CHENJI-A-V1-KF-QA-V2_738525ab-fd8e-4081-8db7-d4fcafa8ad68.png",
    "seal_evidence": KF_R / "E40_E40-FP-R03-YUNFEI-B-V1-KF-QA-V2_cca0cd01-1ace-4bb7-a56b-e90f3da4c900.png",
}

SOURCE_FILTER = {
    # Exact-pixel prop crops. The full seal source was not admitted because of
    # its character/placement composition; this crop excludes every person and
    # re-enters Q1 only as a no-face period prop macro.
    "frost_evidence": "crop=iw:ih*0.46:0:ih*0.54,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
    "seal_evidence": "crop=iw*0.58:ih*0.30:iw*0.21:ih*0.68,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
}

GROUPS = [
    {"unit": "R01-YUNFEI-A", "task": "E40-MISSING12-SWITCH-COVERAGE-R01-DIA001-003-V1", "seconds": 8, "dialogue_ids": ["E40-DIA-001", "E40-DIA-002", "E40-DIA-003"], "images": [("ashuan", 2), ("offer", 3), ("decision", 3)], "meaning": ["阿栓受制", "交换被提出", "陈迹被迫选择"]},
    {"unit": "R02", "task": "E40-MISSING12-SWITCH-COVERAGE-R02-DIA005-007-V1", "seconds": 10, "dialogue_ids": ["E40-DIA-005", "E40-DIA-006", "E40-DIA-007"], "images": [("frost_evidence", 4), ("ashuan", 3), ("frost_evidence", 3)], "meaning": ["霜痕计数串联灭口", "阿栓反常存活", "阿栓被识别为饵"]},
    {"unit": "R03", "task": "E40-MISSING12-SWITCH-COVERAGE-R03-DIA008-V1", "seconds": 4, "dialogue_ids": ["E40-DIA-008"], "images": [("frost_evidence", 2), ("decision", 2)], "meaning": ["霜痕证据与人质选择形成双线断死"]},
    {"unit": "R03-YUNFEI-B", "task": "E40-MISSING12-SWITCH-COVERAGE-R03-DIA009-V1", "seconds": 4, "dialogue_ids": ["E40-DIA-009"], "images": [("yunfei", 3), ("frost_evidence", 1)], "meaning": ["云妃收起机锋并认可霜痕判断"]},
    {"unit": "R04-CHENJI-A", "task": "E40-MISSING12-SWITCH-COVERAGE-R04-DIA010-V1", "seconds": 4, "dialogue_ids": ["E40-DIA-010"], "images": [("seal_evidence", 2), ("yunfei", 2)], "meaning": ["旧印无脸特写指向云妃身侧"]},
    {"unit": "R08-YUNFEI-A", "task": "E40-MISSING12-SWITCH-COVERAGE-R08-DIA017-V1", "seconds": 4, "dialogue_ids": ["E40-DIA-017"], "images": [("offer", 2), ("decision", 2)], "meaning": ["交换筹码被撤回，选择权回到陈迹"]},
    {"unit": "R08-YUNFEI-C", "task": "E40-MISSING12-SWITCH-COVERAGE-R08-DIA019-020-V1", "seconds": 8, "dialogue_ids": ["E40-DIA-019", "E40-DIA-020"], "images": [("ashuan", 2), ("yunfei", 3), ("decision", 3)], "meaning": ["阿栓获释", "官面撤案", "选择交还白鲤"]},
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render(group: dict) -> Path:
    out = OUT_DIR / f"{group['task']}.mp4"
    args = ["ffmpeg", "-y", "-loglevel", "error"]
    for name, seconds in group["images"]:
        args += ["-loop", "1", "-t", str(seconds), "-i", str(IMG[name])]
    audio_index = len(group["images"])
    args += ["-f", "lavfi", "-t", str(group["seconds"]), "-i", "anullsrc=r=48000:cl=stereo"]
    filters = []
    labels = []
    for index, (name, seconds) in enumerate(group["images"]):
        label = f"v{index}"
        labels.append(f"[{label}]")
        source_filter = SOURCE_FILTER.get(name, "scale=720:1280")
        filters.append(
            f"[{index}:v]fps=24,{source_filter},zoompan=z='min(zoom+0.00022,1.016)':d=1:s=720x1280:fps=24,"
            f"trim=duration={seconds},setpts=PTS-STARTPTS,setsar=1[{label}]"
        )
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,format=yuv420p[v]")
    args += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", f"{audio_index}:a", "-t", str(group["seconds"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(out)]
    run(args)
    return out


def main() -> int:
    for path in [V16, V16_QA, *IMG.values()]:
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = []
    for group in GROUPS:
        out = render(group)
        outputs.append({**group, "path": str(out.relative_to(ROOT)), "sha256": sha(out)})

    sequence = json.loads(V16_QA.read_text(encoding="utf-8"))["sequence"]
    cursor = 0.0
    windows = {}
    targets = {group["unit"] for group in GROUPS}
    for item in sequence:
        start = cursor
        cursor += float(item["duration_seconds"])
        if item["unit_id"] in targets:
            windows[item["unit_id"]] = [start, cursor]
    if set(windows) != targets:
        raise SystemExit(f"replacement window mismatch: {set(windows) ^ targets}")

    ordered = sorted(outputs, key=lambda item: windows[item["unit"]][0])
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(V16)]
    for item in ordered:
        args += ["-i", str(ROOT / item["path"])]
    graph = []
    concat_inputs = []
    last = 0.0
    part = 0
    for input_index, item in enumerate(ordered, 1):
        start, end = windows[item["unit"]]
        if start > last:
            graph += [f"[0:v]trim=start={last}:end={start},setpts=PTS-STARTPTS[bv{part}]", f"[0:a]atrim=start={last}:end={start},asetpts=PTS-STARTPTS[ba{part}]"]
            concat_inputs += [f"[bv{part}]", f"[ba{part}]"]
            part += 1
        concat_inputs += [f"[{input_index}:v]", f"[{input_index}:a]"]
        last = end
    graph += [f"[0:v]trim=start={last},setpts=PTS-STARTPTS[bv{part}]", f"[0:a]atrim=start={last},asetpts=PTS-STARTPTS[ba{part}]"]
    concat_inputs += [f"[bv{part}]", f"[ba{part}]"]
    graph.append("".join(concat_inputs) + f"concat=n={len(concat_inputs)//2}:v=1:a=1[v][a]")
    args += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(V18)]
    run(args)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(V18), "-f", "null", "-"], check=True)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = {
        "schema": "qingshan.e40.missing12_script_equivalent_candidates.v1",
        "episode": "E40",
        "status": "CANDIDATES_BUILT_Q1_Q2_REQUIRED",
        "recorded_at": now,
        "source_disposition": "SWITCH_COVERAGE_NO_ATTEMPT4",
        "provider_post_allowed": False,
        "credits": 0,
        "audio_policy": "NO_DIALOGUE; still-image sources have no native audio to preserve; no TTS/BGM/cross-task audio.",
        "subtitle_policy": "The twelve retired spoken lines must not remain as faux dialogue subtitles.",
        "outputs": [{**item, "window_seconds": windows[item["unit"]]} for item in ordered],
    }
    write(QA, report)
    v18_report = {
        "schema": "qingshan.e40.assembly_candidate.v18.script_equivalent.v1",
        "episode": "E40",
        "status": "TECHNICAL_PASS_REGISTERED_CONTENT_QA_REQUIRED",
        "recorded_at": now,
        "baseline": {"path": str(V16.relative_to(ROOT)), "sha256": sha(V16)},
        "replacement_evidence_ref": str(QA.relative_to(ROOT)),
        "replacement_count": len(outputs),
        "retired_spoken_dialogue_count": 12,
        "asset_path": str(V18.relative_to(ROOT)),
        "asset_sha256": sha(V18),
        "decode_status": "PASS_ZERO_ERRORS",
        "release_allowed": False,
        "next_successor_task_id": "E40-V18-SCRIPT-EQUIVALENT-REGISTERED-Q1-Q2-V1",
    }
    write(V18_QA, v18_report)
    print(json.dumps({"outputs": len(outputs), "qa": str(QA.relative_to(ROOT)), "v18": v18_report["asset_path"], "v18_sha256": v18_report["asset_sha256"], "v18_qa": str(V18_QA.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
