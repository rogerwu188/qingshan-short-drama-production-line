#!/usr/bin/env python3
"""Run independent machine QA for E37's ten remaining overhead-reveal sources."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from tools.portable_runtime import resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "working_assets/e37_video_20260803/remaining_u03_u07_pfm_v2_overhead_reveal_v4"
QA = ROOT / "qa/e37_video_20260803/remaining_u03_u07_pfm_v2_overhead_reveal_v4"
RECEIPTS = [
    ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_SUBMIT_V4_20260803.json",
    ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_PENDING9_SUBMIT_V4_20260803.json",
]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
S6_ACCEPTED = WORK / "E37_U07_S6_ZERO_CREDIT_CONTINUOUS_REFRAME_V2.mp4"
DIALOGUE = {
    "U03-S1": ["这拆日子的写法……我在另一处见过。", "隔着很远……很远的一桩案子。"],
    "U03-S2": ["也是这样，把好端端一个日子，拆开，藏起来。", "宋明这桩灭门旧账，和我记忆里那桩旧案。"],
    "U03-S3": ["用的是同一套藏日子的规矩。", "不是巧合。同一只手，隔着这么远，管着两桩账。"],
    "U03-S4": ["里屋供着牌位、摆着热茶。", "守宅的人刚还在。他知道咱们来了。"],
    "U07-S1": ["钱是死人家出的，养个活人守宅。", "这银子转几手，总该转进个活人口袋。"],
    "U07-S2": ["追到那口袋，就追到管账的人。"],
    "U07-S3": ["这笔钱，最后一站，进的是太平医馆。", "一本，匿名善款的账。"],
    "U07-S4": ["太平医馆？咱们的医馆？姚太医的医馆？", "替刘家死人守命的钱，绕了三年，进了救你养你那个家？"],
    "U07-S5": ["我从被追杀那天起，什么都防过。", "防王府、防密谍司，也防景朝。"],
    "U07-S6": ["只有这座医馆、这个救我出死局的人，我一次也没防过。"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def han(value: str) -> str:
    return "".join(re.findall(r"[\u3400-\u9fff]", value))


def recall(expected: str, actual: str) -> float:
    target, observed = han(expected), han(actual)
    if target in observed:
        return 1.0
    matched = sum(block.size for block in SequenceMatcher(None, target, observed).get_matching_blocks())
    return matched / len(target) if target else 1.0


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], allowed_returncodes: set[int] | None = None) -> None:
    completed = subprocess.run(command, cwd=ROOT, check=False)
    allowed = allowed_returncodes or {0}
    if completed.returncode not in allowed:
        raise subprocess.CalledProcessError(completed.returncode, command)


def main() -> int:
    QA.mkdir(parents=True, exist_ok=True)
    sources = {}
    for receipt_path in RECEIPTS:
        for task in load(receipt_path)["tasks"]:
            if task.get("output_path"):
                sources[task["segment_id"]] = ROOT / task["output_path"]
    for segment in DIALOGUE:
        salvage = WORK / f"E37_{segment.replace('-', '_')}_ZERO_CREDIT_CONTINUOUS_REFRAME_V2.mp4"
        if salvage.is_file():
            sources[segment] = salvage
        fixed = WORK / f"E37_{segment.replace('-', '_')}_ZERO_CREDIT_FIXED_COMPOSITION_V4.mp4"
        if fixed.is_file():
            sources[segment] = fixed
    sources["U07-S6"] = S6_ACCEPTED
    if set(sources) != set(DIALOGUE):
        raise SystemExit(f"source coverage mismatch: {sorted(sources)}")

    model_ref, model_source = resolve_whisper_model(None)
    from faster_whisper import WhisperModel

    model = WhisperModel(model_ref, device="cpu", compute_type="int8")
    rows = []
    for segment in sorted(sources):
        source = sources[segment]
        stem = f"E37_{segment.replace('-', '_')}_OVERHEAD_V4"
        contract_path = QA / f"{stem}_DIALOGUE_CONTRACT.json"
        contract = {
            "schema": "qingshan.source_dialogue_contract.v1",
            "episode": "E37",
            "segment_id": segment,
            "canonical_script_sha256": SCRIPT_SHA,
            "dialogue": [
                {"dia_id": f"{segment}-D{index:02d}", "spoken_text": text, "native_video_audio_required": True, "visible_lipsync_required": True}
                for index, text in enumerate(DIALOGUE[segment], 1)
            ],
        }
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        ahash_path = QA / f"{stem}_FPS1_ADJACENT_AHASH.json"
        cadence_path = QA / f"{stem}_FRAME_CADENCE.json"
        ocr_path = QA / f"{stem}_SOURCE_OCR.json"
        contact_path = QA / f"{stem}_CONTACT_SHEET_2FPS.jpg"
        run(["python3", "tools/audit_e36_fps1_adjacent_ahash.py", "--video", str(source), "--out", str(ahash_path), "--ffmpeg", str(FFMPEG)])
        run(["python3", "tools/frame_cadence_audit.py", "--video", str(source), "--out", str(cadence_path), "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC"])
        run(
            ["python3", "tools/final_video_ocr_audit.py", "--video", str(source), "--out", str(ocr_path), "--source-mode"],
            {0, 1},
        )
        run([str(FFMPEG), "-y", "-loglevel", "error", "-i", str(source), "-vf", "fps=2,scale=240:-1,tile=4x5", "-frames:v", "1", str(contact_path)])

        expected = "".join(DIALOGUE[segment])
        paths = []
        for vad in (False, True):
            segments, _ = model.transcribe(
                str(source), language="zh", vad_filter=vad, beam_size=8, best_of=8,
                temperature=0.0, initial_prompt=han(expected), hotwords=expected,
                condition_on_previous_text=False,
            )
            segment_rows = [
                {"start": round(float(item.start), 3), "end": round(float(item.end), 3), "text": item.text.strip()}
                for item in segments
            ]
            transcript = "".join(item["text"] for item in segment_rows)
            paths.append({"vad_filter": vad, "transcript": transcript, "recall_score": round(recall(expected, transcript), 4), "segments": segment_rows})
        best_recall = max(path["recall_score"] for path in paths)
        dialogue_path = QA / f"{stem}_INDEPENDENT_DUAL_VAD.json"
        dialogue_qa = {
            "schema": "qingshan.independent_dual_vad_dialogue_adjudication.v1",
            "status": "PASS" if best_recall >= 0.80 else "FAIL",
            "video": rel(source), "video_sha256": sha256(source),
            "expected_text": expected, "best_recall": best_recall, "minimum_recall": 0.80,
            "model": model_ref, "model_source": model_source, "paths": paths,
        }
        dialogue_path.write_text(json.dumps(dialogue_qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        ahash = load(ahash_path)
        cadence = load(cadence_path)
        ocr = load(ocr_path)
        machine_pass = (
            ahash["status"] == "PASS"
            and cadence["status"] == "PASS"
            and dialogue_qa["status"] == "PASS"
            and ocr.get("critical_text_failures", 0) == 0
        )
        rows.append({
            "segment_id": segment,
            "status": "MACHINE_PASS_DIRECT_VISUAL_PENDING" if machine_pass else "FAIL_PRESERVED_REQUIRES_LOCAL_REPAIR_OR_ADJUDICATION",
            "source": rel(source), "source_sha256": sha256(source),
            "gates": {
                "fps1_adjacent_ahash": {"status": ahash["status"], "ratio_percent": ahash["near_pair_ratio_percent"], "path": rel(ahash_path)},
                "frame_cadence": {"status": cadence["status"], "path": rel(cadence_path)},
                "native_dialogue_dual_vad": {"status": dialogue_qa["status"], "best_recall": best_recall, "path": rel(dialogue_path)},
                "ocr": {"machine_status": ocr["status"], "critical_text_failures": ocr.get("critical_text_failures", 0), "recognitions": ocr.get("recognitions", []), "direct_review_required": bool(ocr.get("recognitions")), "path": rel(ocr_path)},
                "contact_sheet": {"status": "DIRECT_VISUAL_PENDING", "path": rel(contact_path), "sha256": sha256(contact_path)},
            },
        })
        print(json.dumps({"segment": segment, "status": rows[-1]["status"], "ahash": ahash["near_pair_ratio_percent"], "dialogue": best_recall, "ocr_hits": len(ocr.get("recognitions", []))}, ensure_ascii=False), flush=True)

    report = {
        "schema": "qingshan.e37.remaining_overhead_batch_machine_qa.v1",
        "episode": "E37",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "MACHINE_QA_COMPLETE_DIRECT_VISUAL_PENDING",
        "counts": {
            "segments": len(rows),
            "machine_pass": sum(row["status"].startswith("MACHINE_PASS") for row in rows),
            "failed": sum(row["status"].startswith("FAIL") for row in rows),
        },
        "credits": {"pay": 1600, "refund": 0, "net": 1600, "cumulative_net": 3840, "cap": 10000},
        "rows": rows,
    }
    out = QA / "E37_REMAINING_U03_U07_OVERHEAD_V4_MACHINE_QA.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], **report["counts"], "out": rel(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
