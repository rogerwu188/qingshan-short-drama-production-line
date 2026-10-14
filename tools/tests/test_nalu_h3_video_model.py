"""NALU line on MiniMax-H3 (line owner 2026-10-13): order/gate follow the order's model, H3 pricing,
and the per-unit English contract request -> answer -> render round trip."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_nalu_paid_authority as pa  # noqa: E402  (fixture + loaded module)
import test_video_prompt_compiler as vpc  # noqa: E402
from tools import h3_english_contract_io as io  # noqa: E402
from tools.video_prompt_compiler import compile_model_prompt  # noqa: E402

mod = pa.mod


def _h3_fixture(root: Path):
    orders, _, payload = pa._write_fixture(root)
    order = payload["orders"][0]
    order["decision"]["video_model"] = mod.H3
    order["conditions"][0] = {"id": "VIDEO_MODEL_H3_ONLY", "text": "Use MiniMax-H3 only."}
    orders.write_text(json.dumps(payload), encoding="utf-8")
    return orders


class H3OrderTests(unittest.TestCase):
    def read(self, root, orders):
        return mod.read_order(orders, 1, "E01", 8000, expected_owner="owner-1", expected_latest_seq=1,
                              engine_root=root / "engine", paid_stage="S6", require_private=True)

    def test_h3_order_locks_video_to_h3(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            order = self.read(root, _h3_fixture(root))
            self.assertEqual(order["video_model"], mod.H3)
            h3_tasks = [{"model": mod.H3, "duration_seconds": 6}, {"model": mod.H3, "duration_seconds": 4}]
            report = mod.check_models({"model": mod.H3}, h3_tasks, video=True, allow_image_model=False,
                                      video_model=order["video_model"])
            self.assertTrue(report["model_lock_enforced"])
            with self.assertRaises(mod.Refused):
                mod.check_models({}, [{"model": mod.SD2, "duration_seconds": 6}], video=True,
                                 allow_image_model=False, video_model=mod.H3)
            priced = mod.price(h3_tasks, video=True, image_credits=11, video_credits_per_second=20,
                               video_model=mod.H3)
            self.assertEqual(priced["planned_credits"], 10 * 14 + 2 * 6)

    def test_sd2_order_still_refuses_h3_and_h3_condition_must_match(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders, _, _ = pa._write_fixture(root)
            order = self.read(root, orders)
            self.assertEqual(order["video_model"], mod.SD2)
            with self.assertRaises(mod.Refused):
                mod.check_models({}, [{"model": mod.H3, "duration_seconds": 6}], video=True,
                                 allow_image_model=False, video_model=order["video_model"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / "engine").mkdir()
            orders = _h3_fixture(root)
            payload = json.loads(orders.read_text())
            payload["orders"][0]["conditions"][0] = {"id": "VIDEO_MODEL_SD2_ONLY", "text": "Use seedance-2.0-pro only."}
            orders.write_text(json.dumps(payload))
            with self.assertRaises(mod.Refused):
                self.read(root, orders)


def _fill(template):
    if isinstance(template, dict):
        return {k: _fill(v) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v) for v in template]
    return "the visible state stays readable in frame"


class H3EnglishContractTests(unittest.TestCase):
    def unit(self):
        u = vpc._unit()
        u["model"], u["resolution"] = "MiniMax-H3", "768p"
        return u

    def test_request_answer_render_and_stale_detection(self):
        with tempfile.TemporaryDirectory() as d:
            answers_path = Path(d) / "E01_H3_ENGLISH_CONTRACTS.json"
            unit = self.unit()
            pending = io.bind_or_request([unit], answers_path)
            self.assertEqual(len(pending), 1)
            request = json.loads(answers_path.with_name("E01_H3_ENGLISH_CONTRACTS.REQUEST.json").read_text())
            row = request["units"][0]
            self.assertTrue(row["source"]["beats"][0]["entry_state"])  # Chinese source is shown
            answers = {"schema": io.ANSWERS_SCHEMA, "units": {row["answer_key"]: {
                "execution_semantics_sha256": row["execution_semantics_sha256"], "english": _fill(row["english"])}}}
            answers_path.write_text(json.dumps(answers), encoding="utf-8")

            unit = self.unit()
            self.assertEqual(io.bind_or_request([unit], answers_path), [])
            self.assertFalse(answers_path.with_name("E01_H3_ENGLISH_CONTRACTS.REQUEST.json").exists())
            text = compile_model_prompt(unit)
            self.assertTrue(text.startswith("subject_definitions:"))
            self.assertNotRegex(text.split("<d>")[0], r"[㐀-鿿]")

            changed = self.unit()
            changed["ordered_prompt_specs"][0]["action"]["primary_action"] = "白鲤放下车帘并后退半步"
            again = io.bind_or_request([changed], answers_path)
            self.assertEqual([r["reason"] for r in again], ["STALE_SOURCE_CHANGED"])

    def test_answer_with_chinese_or_wrong_shape_is_rejected(self):
        unit = self.unit()
        row = io.request_row(unit)
        bad = _fill(row["english"])
        bad["identity_prop_fact"] = "白鲤"
        bad["beats"] = []
        out = io.apply_answers(unit, {"units": {row["answer_key"]: {
            "execution_semantics_sha256": row["execution_semantics_sha256"], "english": bad}}})
        self.assertEqual(out["reason"], "ANSWER_INVALID")
        self.assertTrue(any("CHINESE_TEXT" in p for p in out["problems"]))
        self.assertTrue(any("beats:COUNT" in p for p in out["problems"]))
        self.assertNotIn("h3_provider_english_contract", unit)


if __name__ == "__main__":
    unittest.main()


class StickyVideoModelTests(unittest.TestCase):
    def test_in_flight_sd2_episode_keeps_sd2_after_config_flips_to_h3(self):
        import importlib
        import os
        with tempfile.TemporaryDirectory() as d:
            runtime, work = Path(d) / "runtime", Path(d) / "work"
            (runtime).mkdir()
            (runtime / "qingshan.json").write_text(json.dumps({"generation": {"video_model": "MiniMax-H3"}}))
            pre = work / "E07" / "preproduction"
            pre.mkdir(parents=True)
            (pre / "E07_EDITORIAL_SEEDANCE_MANIFEST_V1.json").write_text(
                json.dumps({"model_contract": {"model": "seedance-2.0-pro"}}))
            saved = {k: os.environ.get(k) for k in ("NALU_RUNTIME_ROOT", "NALU_WORK_ROOT")}
            os.environ.update(NALU_RUNTIME_ROOT=str(runtime), NALU_WORK_ROOT=str(work))
            try:
                sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
                import nalu_paths
                import nalu_video_model
                importlib.reload(nalu_paths); importlib.reload(nalu_video_model)
                self.assertEqual(nalu_video_model.episode_video_model("E07"), "seedance-2.0-pro")  # in flight
                self.assertEqual(nalu_video_model.episode_video_model("E08"), "MiniMax-H3")       # new episode
                rec = nalu_video_model.record_path("E08")
                rec.parent.mkdir(parents=True)
                rec.write_text(json.dumps({"video_model": "MiniMax-H3"}))
                (runtime / "qingshan.json").write_text(json.dumps({"generation": {"video_model": "seedance-2.0-pro"}}))
                self.assertEqual(nalu_video_model.episode_video_model("E08"), "MiniMax-H3")       # recorded wins
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                importlib.reload(nalu_paths)
