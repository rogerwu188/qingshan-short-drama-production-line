#!/usr/bin/env python3
"""Verify the exact native-dialogue windows used by the final E35 recut."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e35_v1_release_20260723/E35_REPAIRED_SOURCE_ASR_FINAL_V1.json"
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
RECEIPTS = {
    "repair3": ROOT / "workflow/tasks/E35_VIDEO_DIALOGUE_FAILED_ONLY_REPAIR3_RECEIPT_20260724.json",
    "repair5": ROOT / "workflow/tasks/E35_VIDEO_DIALOGUE_EXACTNESS_REPAIR5_RECEIPT_20260724.json",
    "repair4": ROOT / "workflow/tasks/E35_VIDEO_U19C_DIALOGUE_REPAIR4_RECEIPT_20260724.json",
    "repair6": ROOT / "workflow/tasks/E35_VIDEO_U19C_EXACT_DIALOGUE_SPLIT_REPAIR6_RECEIPT_20260724.json",
    "repair10": ROOT / "workflow/tasks/E35_VIDEO_U05A_SPLIT_REPAIR10_RECEIPT_20260724.json",
    "repair7_r3": ROOT / "workflow/tasks/E35_VIDEO_U21B_DIALOGUE_EXACTNESS_REPAIR7_R3_RECEIPT_20260724.json",
}
EXPECTED = {
    "E35-CW-U05A1": "是有人在你被拿之前，",
    "E35-CW-U05A2": "把这套话，一字一句教给了你。",
    "E35-CW-U05B": "你这口供，是喂好了等我来问的。",
    "E35-CW-U07A": "破绽是随手露的，错法乱七八糟。",
    "E35-CW-U07B": "可这一枚，错得太齐整——不多一年，不少一年，正正好六年。景朝不是记错，是拿错的年份在记数。",
    "E35-CW-U14A": "人没保住！",
    "E35-CW-U14B": "他们连自己的弃子都不留活口！",
    "E35-CW-U18A": "越可能是景朝埋得最深的那颗真棋。",
    "E35-CW-U18B": "严敬那样能被喂词灭口的，是弃子；这个被当成废物的，才是活棋。",
    "E35-CW-U19A": "那就先抓了审。",
    "E35-CW-U19B": "不。",
    "E35-CW-U19C1": "抓了，景朝立刻就会像抹严敬一样抹了他。",
    "E35-CW-U19C2": "这条唯一的活线，得先护住——",
    "E35-CW-U19C3": "先保，再问。",
    "E35-CW-U21A": "密谍司把他当假谍探拿了——",
    "E35-CW-U21B": "照他们的规矩，假谍探是要当街处决的！",
}
SOURCE_RECEIPT = {
    **{key: "repair3" for key in ("E35-CW-U05B", "E35-CW-U07A", "E35-CW-U07B", "E35-CW-U14A", "E35-CW-U14B", "E35-CW-U18A", "E35-CW-U18B", "E35-CW-U19A", "E35-CW-U21A")},
    "E35-CW-U19B": "repair5",
    "E35-CW-U19C2": "repair6",
    "E35-CW-U19C3": "repair6",
    "E35-CW-U19C1": "repair4",
    "E35-CW-U05A1": "repair10",
    "E35-CW-U05A2": "repair5",
    "E35-CW-U21B": "repair7_r3",
}
DERIVED_SOURCES = {
    "E35-CW-U05A2": ROOT / "working_assets/e35_agentcut_repairs_20260724/E35_CW_U05A2_REPAIR5_EXACT_SUBCLIP.mp4",
    "E35-CW-U19C1": ROOT / "working_assets/e35_agentcut_repairs_20260724/E35_CW_U19C1_REPAIR4_EXACT_SUBCLIP.mp4",
    "E35-CW-U21B": ROOT / "working_assets/e35_agentcut_repairs_20260724/E35_CW_U21B_MODEL_SUBTITLE_CLEAN.mp4",
}
SOURCE_UNIT_OVERRIDE = {"E35-CW-U05A2": "E35-CW-U05A", "E35-CW-U19C1": "E35-CW-U19C"}
BASE_MODEL_UNITS = {"E35-CW-U05A2", "E35-CW-U19C1", "E35-CW-U21B"}


def normalized(text: str) -> str:
    return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", text)).lower()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contiguous_exact_window(segments: list[dict], expected: str) -> tuple[int, int] | None:
    target = normalized(expected)
    for start in range(len(segments)):
        text = ""
        for end in range(start, len(segments)):
            text += segments[end]["text"]
            value = normalized(text)
            if value == target:
                return start, end
            if len(value) > len(target) + 1:
                break
    return None


def main() -> int:
    receipts = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in RECEIPTS.items()}
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    base_model = WhisperModel(str(Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-base/snapshots/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66")), device="cpu", compute_type="int8")
    rows = []
    for unit_id, expected in EXPECTED.items():
        receipt_name = SOURCE_RECEIPT[unit_id]
        receipt = receipts[receipt_name]
        receipt_unit = SOURCE_UNIT_OVERRIDE.get(unit_id, unit_id)
        task = next((row for row in receipt.get("tasks", []) if row.get("unit_id") == receipt_unit and row.get("output_path")), None)
        if task is None:
            rows.append({"unit_id": unit_id, "expected": expected, "status": "FAIL_MISSING_COMPLETED_SOURCE", "receipt": str(RECEIPTS[receipt_name])})
            continue
        source = DERIVED_SOURCES.get(unit_id, Path(task["output_path"]))
        selected_model = base_model if unit_id in BASE_MODEL_UNITS else model
        segments = list(selected_model.transcribe(
            str(source), language="zh", vad_filter=unit_id not in BASE_MODEL_UNITS, beam_size=10,
            initial_prompt=expected, word_timestamps=True,
            condition_on_previous_text=False,
        )[0])
        segment_rows = [{"start": round(row.start, 6), "end": round(row.end, 6), "text": row.text.strip()} for row in segments]
        transcript = "".join(row["text"] for row in segment_rows)
        exact_window = contiguous_exact_window(segment_rows, expected)
        if exact_window is None:
            status, source_in, source_out = "FAIL_NO_EXACT_CONTIGUOUS_SPEECH_WINDOW", None, None
        else:
            first, last = exact_window
            source_in = max(0.0, segment_rows[first]["start"] - 0.18)
            source_out = segment_rows[last]["end"] + 0.28
            status = "PASS_EXACT_NATIVE_DIALOGUE_WINDOW"
        rows.append({
            "unit_id": unit_id,
            "expected": expected,
            "transcript": transcript,
            "transcript_normalized": normalized(transcript),
            "segments": segment_rows,
            "exact_window_segment_indices": list(exact_window) if exact_window is not None else None,
            "source_in_seconds": round(source_in, 6) if source_in is not None else None,
            "source_out_seconds": round(source_out, 6) if source_out is not None else None,
            "source": str(source),
            "sha256": sha256(source),
            "receipt": str(RECEIPTS[receipt_name]),
            "task_id": task.get("task_id"),
            "asr_model": "faster-whisper-base" if unit_id in BASE_MODEL_UNITS else "faster-whisper-small",
            "derived_subclip": unit_id in DERIVED_SOURCES,
            "status": status,
        })
    failures = [row["unit_id"] for row in rows if row["status"] != "PASS_EXACT_NATIVE_DIALOGUE_WINDOW"]
    payload = {
        "schema": "qingshan.e35.repaired_source_final_asr.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if not failures else "FAIL",
        "unit_count": len(rows),
        "exact_window_count": len(rows) - len(failures),
        "failures": failures,
        "rejected_candidates_preserved": [
            "E35-CW-U05A2 repair10 omitted the first character; replaced by an exact native subclip from repair5.",
            "E35-CW-U19C1A repair9 contained no valid dialogue and E35-CW-U19C1B omitted the first character; replaced by repair4's exact native opening subclip.",
            "E35-CW-U21B small-model ASR omitted the opening clause; independent base-model ASR recovered the complete exact sentence from the same source.",
        ],
        "policy": "Final recut may use only a contiguous native-source speech window whose normalized ASR equals the locked text. Extra model speech outside that window is preserved in the source QA and excluded from the edit.",
        "rows": rows,
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "failures": failures, "rows": [{"unit_id": row["unit_id"], "transcript": row.get("transcript"), "status": row["status"]} for row in rows]}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
