"""S6 resume (Twelve Gazes E01, 2026-10-22): bound-and-charged tasks are not counted twice, and a
harvested clip whose tail frame was never extracted no longer leaves its successor un-ready."""
from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
TOOLS = ENGINE / "lines/nalu/runtime/tools"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _exposure(tmp: Path, estimates: list[int], non_video: dict) -> Decimal:
    ledger = _load("nalu_budget_ledger_s6", TOOLS / "nalu_budget_ledger.py")
    store = tmp / "workflow" / "tasks" / ledger.VIDEO_TRANSACTION_DIRNAME / "E01"
    store.mkdir(parents=True)
    for n, credits in enumerate(estimates):
        (store / f"E01-VU-{n:03d}__x.json").write_text(json.dumps({
            "state": "SUBMITTED_TASK_ID_BOUND", "task_id": f"t{n}", "estimated_credits": credits}))
    ledger.ENGINE_ROOT = tmp
    return ledger.scan_unevidenced_exposure("E01", non_video)


def _non_video(batch: int, matched: int, *, bound_upper: int = 330) -> dict:
    return {"per_task_credits": 0, "batch_reconciled_credits": batch,
            "bound_image_transaction_upper_credits": bound_upper,
            "batch_rows": [{"event_description": "SingleGenerateVideo", "status": "PASS_BOUNDED",
                            "matched_count": matched, "credits": 492}]}


def test_bound_and_charged_videos_are_not_counted_twice(tmp_path):
    # E01: 5 bound videos (492) whose statement matched 5 rows, batch layer 822 used by recorded
    assert _exposure(tmp_path, [90, 76, 118, 132, 76], _non_video(822, 5)) == Decimal("0")


def test_a_bound_video_without_a_statement_still_counts(tmp_path):
    # one more bound task than the statements matched -> the most expensive one stays as exposure
    assert _exposure(tmp_path, [90, 76, 600], _non_video(822, 2)) == Decimal("600")


def test_statements_only_cover_when_the_batch_layer_is_what_recorded_uses(tmp_path):
    # bound-image upper layer exceeds the batch layer -> recorded ignores the video statement
    assert _exposure(tmp_path, [90, 76], _non_video(150, 2, bound_upper=330)) == Decimal("166")


def test_missing_tails_of_on_disk_clips_are_extracted_before_readiness():
    src = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
    block = src[src.index("derived = continuity_derived_units(ctx)"):]
    block = block[:block.index("new_ready = [uid for uid, prev, needs in deps")]
    assert "for uid in sorted(done):" in block
    assert "extract_real_final_frame(ctx, uid)" in block
