"""Q1 admissions follow the CURRENT unit numbering (fleet device 1101 E24 VU-014 / VU-018, 2026-11-22).

The units were renumbered after the S5 keyframe review.  The Q1 builder wrote each admission under the unit
id recorded in the review item, so q1/E24-VU-014 held the admission of S04-03 while VU-014 opens on S04-01;
S5 short-circuited on the ALL_ADMITTED index, S6 only re-checked tail-sourced units, and the video admission
gate failed SEMANTIC_ANCHOR_EVIDENCE_INVALID (Q1_ASSET_SHA_MISMATCH) on every resume."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT))

import keyframe_q1_builder as q1b  # noqa: E402
import nalu_pipeline as npl  # noqa: E402


def _item(shot: str, unit: str) -> dict:
    return {"item_id": shot, "request_item": {"unit_id": unit, "shot_id": shot}}


def _exp(units: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(units={uid: {"unit_id": uid, "editorial_shot_ids": [shot]} for uid, shot in units.items()},
                           _unit_first_shot_id=lambda unit: unit["editorial_shot_ids"][0])


class ResolveItemUnitsTest(unittest.TestCase):
    def test_a_shot_is_admitted_for_the_unit_it_opens_now(self):
        exp = _exp({"E24-VU-014": "E24-S04-01", "E24-VU-016": "E24-S04-03"})
        resolved, superseded = q1b.resolve_item_units(
            [_item("E24-S04-01", "E24-VU-013"), _item("E24-S04-03", "E24-VU-014")], exp)
        self.assertEqual(resolved, {"E24-S04-01": "E24-VU-014", "E24-S04-03": "E24-VU-016"})
        self.assertEqual(superseded, [])

    def test_an_item_whose_unit_now_opens_on_another_shot_is_superseded(self):
        exp = _exp({"E24-VU-014": "E24-S04-01"})
        resolved, superseded = q1b.resolve_item_units(
            [_item("E24-S04-03", "E24-VU-014"), _item("E24-S04-01", "E24-VU-013")], exp)
        self.assertEqual(resolved, {"E24-S04-01": "E24-VU-014"})
        self.assertEqual(superseded, [{"item_id": "E24-S04-03", "review_unit_id": "E24-VU-014",
                                       "unit_now_opens_on": "E24-S04-01"}])

    def test_without_a_plan_every_item_keeps_its_unit(self):
        items = [_item("E24-S04-01", "E24-VU-014"), {"item_id": "E24-S09-02", "request_item": {}}]
        for exp in (SimpleNamespace(), _exp({})):
            resolved, superseded = q1b.resolve_item_units(items, exp)
            self.assertEqual(resolved, {"E24-S04-01": "E24-VU-014", "E24-S09-02": "E24-S09-02"})
            self.assertEqual(superseded, [])

    def test_an_unchanged_plan_changes_nothing(self):
        exp = _exp({"E24-VU-014": "E24-S04-01", "E24-VU-015": "E24-S04-03"})
        resolved, superseded = q1b.resolve_item_units(
            [_item("E24-S04-01", "E24-VU-014"), _item("E24-S04-03", "E24-VU-015")], exp)
        self.assertEqual(resolved, {"E24-S04-01": "E24-VU-014", "E24-S04-03": "E24-VU-015"})
        self.assertEqual(superseded, [])


def _ctx(tmp: Path) -> SimpleNamespace:
    preprod = tmp / "preproduction"
    for sub in ("keyframes", "reports"):
        (preprod / sub).mkdir(parents=True, exist_ok=True)
    (tmp / "video").mkdir()
    (preprod / "E24_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E24-VU-014", "editorial_shot_ids": ["E24-S04-01", "E24-S04-02"]},
        {"unit_id": "E24-VU-015", "editorial_shot_ids": ["E24-S04-03"]},
        {"unit_id": "E24-VU-016", "editorial_shot_ids": ["E24-S04-04"]}]}))
    (preprod / "E24_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": [
        {"unit_id": "E24-VU-014", "opening_anchor_contract": {"source": "NEW_EVENT_GENERATED_KEYFRAME"}},
        {"unit_id": "E24-VU-015", "opening_anchor_contract": {"source": "NEW_EVENT_GENERATED_KEYFRAME"}},
        {"unit_id": "E24-VU-016", "opening_anchor_contract": {"source": "PREVIOUS_UNIT_REAL_FINAL_FRAME",
                                                              "previous_unit_id": "E24-VU-015"}}]}))
    for shot in ("E24-S04-01", "E24-S04-03", "E24-S04-04"):
        (preprod / "keyframes" / f"{shot}-keyframe-v1.png").write_bytes(f"still of {shot}".encode())
    return SimpleNamespace(
        episode="E24", dry=False, say=lambda *_a, **_k: None,
        p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", video_media=tmp / "video",
                          keyframes=preprod / "keyframes"))


def _admit(ctx: SimpleNamespace, unit: str, shot: str, status: str = "ADMITTED_FOR_VIDEO_SUBMIT") -> None:
    path = ctx.p.preprod_reports / "qa" / "q1" / unit / "admission_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"downstream_status": status, "asset_sha256": npl.sha256_file(
        ctx.p.keyframes / f"{shot}-keyframe-v1.png")}))


class OwnKeyframeQ1StaleTest(unittest.TestCase):
    def test_an_admission_of_another_shot_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = _ctx(Path(d))
            _admit(ctx, "E24-VU-014", "E24-S04-03")   # the 1101 state: VU-014 holds the admission of S04-03
            _admit(ctx, "E24-VU-015", "E24-S04-03")
            self.assertEqual(npl.own_keyframes_q1_stale(ctx), ["E24-VU-014"])
            _admit(ctx, "E24-VU-014", "E24-S04-01")
            self.assertEqual(npl.own_keyframes_q1_stale(ctx), [])

    def test_a_unit_q1_never_judged_is_stale_and_a_tail_sourced_unit_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = _ctx(Path(d))
            _admit(ctx, "E24-VU-014", "E24-S04-01")
            self.assertEqual(npl.own_keyframes_q1_stale(ctx), ["E24-VU-015"])   # VU-016 is a hard continuation

    def test_a_rejection_of_these_bytes_a_finished_clip_and_a_versioned_keyframe_are_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = _ctx(Path(d))
            _admit(ctx, "E24-VU-014", "E24-S04-01", status="FAIL_NOT_ADMITTED")
            (ctx.p.video_media / "E24-VU-015.mp4").write_bytes(b"clip")
            self.assertEqual(npl.own_keyframes_q1_stale(ctx), [])
            _admit(ctx, "E24-VU-014", "E24-S04-03")
            (ctx.p.keyframes / "E24-S04-01-keyframe-v2.png").write_bytes(b"v2")
            self.assertEqual(npl.own_keyframes_q1_stale(ctx), [])


if __name__ == "__main__":
    unittest.main()
