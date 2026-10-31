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
from tools.h3_provider_prompt_renderer import ANTI_TEXT  # noqa: E402
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
            # K143 (2026-10-30): the TEXT-FREE FRAME rule is the first line, subject_definitions follows it
            self.assertTrue(text.startswith(ANTI_TEXT + ".\nsubject_definitions:"))
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


class H3FinalRenderReceiptTests(unittest.TestCase):
    """E02 (2026-10-14): the H3 final render changes the prompt sha after finalize attached the reviewed
    finalization receipt; the receipt must be re-attached against the final sha (or dropped)."""

    def run_render(self, receipt_sha):
        import hashlib
        import types
        sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
        import build_nalu_preproduction as bnp
        rendered = "subject_definitions:\n@Image1: final h3 text\n"
        stub_submit = types.SimpleNamespace(provider_prompt_unit=lambda task: {
            "unit_id": task["unit_id"], "h3_provider_english_contract": {"ok": True}})
        stub_compiler = types.SimpleNamespace(compile_model_prompt=lambda unit: rendered)
        stub_io = types.SimpleNamespace(apply_answers=lambda unit, answers: None, bind_or_request=None,
                                        ANSWERS_SCHEMA="x", REQUEST_SCHEMA="y")
        saved = {k: sys.modules.get(k) for k in ("tools.submit_giggle_video_manifest_v2",
                                                 "tools.video_prompt_compiler", "tools.h3_english_contract_io")}
        sys.modules["tools.submit_giggle_video_manifest_v2"] = stub_submit
        sys.modules["tools.video_prompt_compiler"] = stub_compiler
        sys.modules["tools.h3_english_contract_io"] = stub_io
        try:
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); out = root / "pre"; (out / "prompt_batch_finalization").mkdir(parents=True)
                prompt = out / "E02-VU-002.txt"; prompt.write_text("old 4.4 text")
                final_sha = hashlib.sha256(rendered.encode()).hexdigest()
                (out / "prompt_batch_finalization" / "E02-VU-002.json").write_text(json.dumps(
                    {"status": "PASS", "final_prompt_sha256": receipt_sha or final_sha}))
                task = {"unit_id": "E02-VU-002", "model": "MiniMax-H3", "prompt_file": str(prompt),
                        "prompt_batch_finalization": {"path": "stale", "sha256": "stale"}}
                out_res = bnp.render_h3_final_prompts({"tasks": [task]}, out_dir=out, root=root, episode="E02",
                                                      final_index_path=out / "index.json")
                return out_res, task, final_sha
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_receipt_reattached_against_final_sha(self):
        res, task, final_sha = self.run_render(None)
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(task["prompt_sha256"], final_sha)
        self.assertIn("prompt_batch_finalization", task)
        self.assertNotEqual(task["prompt_batch_finalization"]["path"], "stale")

    def test_stale_receipt_is_dropped(self):
        _, task, _ = self.run_render("0" * 64)
        self.assertNotIn("prompt_batch_finalization", task)


class LedgerParkedCopyTests(unittest.TestCase):
    def test_parked_dirs_are_not_charged_twice(self):
        sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
        import nalu_budget_ledger as led
        self.assertTrue(led._is_parked(Path("workflow/nalu/E02/_superseded_20261014_controlled_repair1/x_credit_statement.json")))
        self.assertTrue(led._is_parked(Path("keyframes/_rejected_v1/a.json")))
        self.assertFalse(led._is_parked(Path("workflow/nalu/E02/preproduction/reports/E02_S6_credit_statement.json")))


class H3VisualCultureScopeTests(unittest.TestCase):
    """2026-10-16: the qingshan Northern-Song block belongs to the episodes its contract governs (as in SD2)."""

    def test_low_episode_gets_neutral_lock_high_episode_keeps_qingshan_block(self):
        from tools.h3_provider_prompt_renderer import H3_NEUTRAL_PERIOD_LOCK, h3_visual_culture_block
        from tools.visual_culture_contract import DEFAULT_CONTRACT, prompt_block_en
        qing = {"profile_id": "RULIN_QING_JIANGNAN_REALISM", "story_world": "清代江南"}
        low = h3_visual_culture_block({"unit_id": "E09-VU-003", "visual_culture_contract": qing})
        self.assertEqual(low, H3_NEUTRAL_PERIOD_LOCK)
        self.assertNotIn("Song", low)
        self.assertNotRegex(low, r"[㐀-鿿]")
        high = h3_visual_culture_block({"unit_id": "E64-VU-001", "visual_culture_contract": DEFAULT_CONTRACT})
        self.assertEqual(high, prompt_block_en(DEFAULT_CONTRACT))

    def test_authored_world_lock_for_english_lines_and_explicit_era_lock(self):
        # Twelve Gazes E01 (near-future English line) got the East-Asian period lock.
        from tools.h3_provider_prompt_renderer import (
            H3_AUTHORED_WORLD_LOCK, H3_NEUTRAL_PERIOD_LOCK, h3_visual_culture_block)
        world = {"profile_id": "TWELVE_GAZES_NEAR_FUTURE", "story_world": "near-future archive"}
        en = h3_visual_culture_block({"unit_id": "E01-VU-001", "dialogue_language": "en",
                                      "visual_culture_contract": world})
        self.assertEqual(en, H3_AUTHORED_WORLD_LOCK)
        self.assertNotIn("EAST-ASIAN", en)
        self.assertNotIn("modern objects", en)
        self.assertNotRegex(en, r"[㐀-鿿]")
        # Chinese lines are unchanged unless the writer declares otherwise
        self.assertEqual(h3_visual_culture_block({"unit_id": "E01-VU-001", "visual_culture_contract": world}),
                         H3_NEUTRAL_PERIOD_LOCK)
        self.assertEqual(h3_visual_culture_block({"unit_id": "E01-VU-001", "visual_culture_contract":
                                                  {**world, "era_lock": "AUTHORED_WORLD"}}), H3_AUTHORED_WORLD_LOCK)
        self.assertEqual(h3_visual_culture_block({"unit_id": "E01-VU-001", "dialogue_language": "en",
                                                  "visual_culture_contract": {**world, "era_lock": "EAST_ASIAN_PERIOD"}}),
                         H3_NEUTRAL_PERIOD_LOCK)


# --------------------------------------------------------------------------- #
# K145: explicit video-model selection, no silent default, refused before POST.
# Every case runs in a temporary runtime/work bound through nalu_paths; nothing
# is POSTed (the provider call is a mock whose call count is asserted).
# --------------------------------------------------------------------------- #
import contextlib  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
from unittest import mock  # noqa: E402

NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
SD2_ID, H3_ID = "seedance-2.0-pro", "MiniMax-H3"


@contextlib.contextmanager
def nalu_roots(qingshan=None, raw_config=None):
    """Temp runtime + work roots bound via nalu_paths; yields (tmp, runtime, work, nalu_video_model, bnp)."""
    import importlib
    if str(NALU_TOOLS) not in sys.path:
        sys.path.insert(0, str(NALU_TOOLS))
    keys = ("NALU_RUNTIME_ROOT", "NALU_WORK_ROOT", "NALU_IGNORE_DEPLOYMENT_PIN")
    saved = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        runtime, work = tmp / "runtime", tmp / "work"
        runtime.mkdir()
        work.mkdir()
        if raw_config is not None:
            (runtime / "qingshan.json").write_text(raw_config, encoding="utf-8")
        elif qingshan is not None:
            (runtime / "qingshan.json").write_text(json.dumps(qingshan), encoding="utf-8")
        os.environ.update(NALU_RUNTIME_ROOT=str(runtime), NALU_WORK_ROOT=str(work), NALU_IGNORE_DEPLOYMENT_PIN="1")
        try:
            import nalu_paths
            import nalu_video_model
            importlib.reload(nalu_paths)
            importlib.reload(nalu_video_model)
            import build_nalu_preproduction as bnp
            yield tmp, runtime, work, nalu_video_model, bnp
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            importlib.reload(nalu_paths)


def write_lock(runtime: Path, episode: str, model) -> Path:
    path = runtime / "preproduction" / episode / "video_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"episode": episode, "video_model": model}), encoding="utf-8")
    return path


def write_editorial(work: Path, episode: str, contract_model, top_model=None) -> Path:
    path = work / episode / "preproduction" / f"{episode}_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"model_contract": {"model": contract_model}}
    if top_model is not None:
        doc["model"] = top_model
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def nalu_manifest(episode: str, model: str, *, task_models=None, prompt: Path | None = None) -> dict:
    """The shape build_nalu_preproduction writes (generated_by, allowed_video_models, format_contract, tasks)."""
    task_models = task_models or [model]
    return {
        "schema": "qingshan.giggle_video_transaction_manifest.v1", "episode": episode,
        "generated_by": "build_nalu_preproduction.v1", "allowed_video_models": [model],
        "format_contract": {"model": model}, "machine_gate_reports": ["x"],
        "tasks": [{"task_key": f"{episode}-VU-{i + 1:03d}", "unit_id": f"{episode}-VU-{i + 1:03d}",
                   "episode": episode, "model": m, "duration_seconds": 6,
                   "resolution": "768p" if m == H3_ID else "720p", "aspect_ratio": "9:16",
                   "prompt_file": str(prompt) if prompt else "p.txt", "prompt_sha256": "0" * 64,
                   "reference_images": [], "reference_sha256": []}
                  for i, m in enumerate(task_models)],
    }


def run_submit_main(manifest: dict, tmp: Path, *, precheck: bool = False, path: Path | None = None):
    """Drive the real submit entry (submit_giggle_video_manifest_v2.main) with the provider POST mocked."""
    from tools import submit_giggle_video_manifest_v2 as video
    path = path or tmp / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    argv = ["submit_giggle_video_manifest_v2.py", "--manifest", str(path), "--out", str(tmp / "out.json"),
            "--project-root", str(tmp)] + (["--precheck-only"] if precheck else [])
    post = mock.Mock(return_value={"data": {"task_id": "MUST-NOT-HAPPEN"}})
    saved_root = video.ROOT
    try:
        with mock.patch.object(video, "_request", post), mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(os.environ, {"GIGGLE_API_KEY": ""}):
            try:
                video.main()
                error = None
            except BaseException as exc:  # noqa: BLE001 - the refusal is the answer
                error = exc
    finally:
        video.ROOT = saved_root
    return error, post


def capture_request_payload(video, task: dict, tmp: Path) -> dict:
    """The exact request body submit_one would POST, captured from a mocked provider call.

    Gates unrelated to the model (batch registry, reviewed-request binding, resubmission guard, scope
    gate) are stubbed; the payload construction and the POST call are the real submit_one code."""
    from tools import episode_prompt_batch_gate
    task = {**task, "prompt_sha256": video.sha256(Path(task["prompt_file"]))}
    post = mock.Mock(return_value={"data": {"task_id": "OFFLINE-CAPTURE"}})
    with mock.patch.object(episode_prompt_batch_gate, "require_generation_batch", lambda *a, **k: None), \
            mock.patch.object(video, "live_bound_elsewhere", lambda *a, **k: None), \
            mock.patch.object(video, "prompt_scope_gate_active", lambda *a, **k: False), \
            mock.patch.object(video, "task_request_digest", lambda *a, **k: {"request_sha256": "0" * 64}), \
            mock.patch.object(video, "require_reviewed_request", lambda *a, **k: {}), \
            mock.patch.object(video, "require_no_silent_resubmission", lambda *a, **k: None), \
            mock.patch.object(video, "paid_video_submission_context", contextlib.nullcontext), \
            mock.patch.object(video, "_request", post):
        video.submit_one(task, tmp / "receipts", tmp / "tx")
    assert post.call_count == 1
    return post.call_args[0][1]


class ExplicitVideoModelSelectionTests(unittest.TestCase):
    # 1. new episode without an explicit, supported model: refused, no lock, no POST
    def test_new_episode_without_explicit_model_fails_closed(self):
        cases = {
            "no_file": dict(),
            "corrupt_json": dict(raw_config="{not json"),
            "top_level_list": dict(raw_config="[]"),
            "no_generation": dict(qingshan={"project": {}}),
            "no_field": dict(qingshan={"generation": {"provider": "giggle"}}),
            "empty": dict(qingshan={"generation": {"video_model": ""}}),
            "null": dict(qingshan={"generation": {"video_model": None}}),
            "non_string": dict(qingshan={"generation": {"video_model": 3}}),
            "list": dict(qingshan={"generation": {"video_model": [H3_ID]}}),
            "unknown": dict(qingshan={"generation": {"video_model": "MiniMax-H4"}}),
            "generation_not_object": dict(qingshan={"generation": "MiniMax-H3"}),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), nalu_roots(**kwargs) as (tmp, runtime, work, vm, bnp):
                with self.assertRaises(vm.VideoModelSelectionError) as caught:
                    vm.episode_video_model("E90")
                self.assertTrue(caught.exception.code.startswith("VIDEO_MODEL_CONFIG")
                                or caught.exception.code == "VIDEO_MODEL_NOT_CONFIGURED", caught.exception.code)
                self.assertIn("qingshan.json", str(caught.exception))
                with self.assertRaises(SystemExit) as stopped:
                    bnp.select_video_model("E90")
                self.assertIn("VIDEO_MODEL_SELECTION_BLOCKED", str(stopped.exception))
                self.assertFalse(vm.record_path("E90").exists(), "no lock may be written")
                self.assertFalse(vm.record_path("E90").parent.exists() and
                                 any(vm.record_path("E90").parent.iterdir()), "no stray lock temp file")
                error, post = run_submit_main(nalu_manifest("E90", SD2_ID), tmp)
                self.assertIsInstance(error, vm.VideoModelSelectionError)
                self.assertEqual(error.code, "VIDEO_MODEL_NOT_SELECTED")
                self.assertEqual(post.call_count, 0)

    # 2. explicit H3: resolution, S2 selection, lock, compiled model_contract and the request agree
    def test_configured_h3_flows_to_lock_contract_and_request(self):
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            self.assertEqual(vm.configured_video_model(), H3_ID)
            contract = bnp.select_video_model("E91")
            self.assertEqual(contract["model"], H3_ID)
            self.assertEqual(contract["resolution"], "768p")
            self.assertEqual(json.loads(vm.record_path("E91").read_text())["video_model"], H3_ID)
            # the builder writes the editorial manifest + transaction manifest from MODEL_CONTRACT
            write_editorial(work, "E91", bnp.MODEL_CONTRACT["model"], bnp.MODEL_CONTRACT["model"])
            prompt = tmp / "E91-VU-001.txt"
            prompt.write_text("subject_definitions:\n@Image1: h3\n", encoding="utf-8")
            manifest = nalu_manifest("E91", bnp.MODEL_CONTRACT["model"], prompt=prompt)
            from tools import submit_giggle_video_manifest_v2 as video
            self.assertEqual(video.require_episode_video_model(manifest, tmp / "m.json"), {"E91": H3_ID})
            payload = capture_request_payload(video, manifest["tasks"][0], tmp)
            self.assertEqual(payload["model"], H3_ID)
            self.assertEqual(payload["resolution"], "768p")
            # a config flip after the lock never re-models the episode
            (runtime / "qingshan.json").write_text(json.dumps({"generation": {"video_model": SD2_ID}}))
            self.assertEqual(bnp.select_video_model("E91")["model"], H3_ID)

    # 3. explicit SD2 stays selectable (no line is forced to H3)
    def test_configured_sd2_is_still_selectable(self):
        with nalu_roots(qingshan={"generation": {"video_model": SD2_ID}}) as (tmp, runtime, work, vm, bnp):
            self.assertEqual(bnp.select_video_model("E92")["model"], SD2_ID)
            self.assertEqual(json.loads(vm.record_path("E92").read_text())["video_model"], SD2_ID)
            self.assertEqual(vm.episode_video_model("E92"), SD2_ID)

    # 4. historical SD2 (lock or legacy manifest) and locked H3 keep their model when the config flips
    def test_historical_episodes_keep_their_model(self):
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            write_editorial(work, "E07", SD2_ID)                     # legacy: manifest only, no lock
            lock11 = write_lock(runtime, "E11", SD2_ID)
            write_editorial(work, "E11", SD2_ID)
            before = lock11.read_bytes()
            self.assertEqual(bnp.select_video_model("E07")["model"], SD2_ID)
            self.assertEqual(json.loads(vm.record_path("E07").read_text())["video_model"], SD2_ID)
            self.assertEqual(bnp.select_video_model("E11")["model"], SD2_ID)
            self.assertEqual(lock11.read_bytes(), before)
            from tools import submit_giggle_video_manifest_v2 as video
            self.assertEqual(video.require_episode_video_model(nalu_manifest("E11", SD2_ID), tmp / "m"), {"E11": SD2_ID})
            with self.assertRaises(vm.VideoModelSelectionError):  # no re-modelling of an SD2 episode's tasks
                video.require_episode_video_model(nalu_manifest("E11", H3_ID), tmp / "m")
        with nalu_roots(qingshan={"generation": {"video_model": SD2_ID}}) as (tmp, runtime, work, vm, bnp):
            write_lock(runtime, "E12", H3_ID)
            write_editorial(work, "E12", H3_ID, H3_ID)
            self.assertEqual(bnp.select_video_model("E12")["model"], H3_ID)
            self.assertEqual(vm.episode_video_model("E12"), H3_ID)

    # 5. corrupt lock / manifest, or lock vs manifest vs tasks conflict: blocked, nothing overwritten
    def test_corrupt_or_conflicting_records_block_without_overwrite(self):
        def lock_text(runtime, text):
            path = runtime / "preproduction" / "E93" / "video_model.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return path

        def manifest_text(work, text):
            path = work / "E93" / "preproduction" / "E93_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return path

        cases = {
            "lock_corrupt_json": (lambda rt, wk: lock_text(rt, '{"video_model": "MiniMax-H3"'),
                                  "VIDEO_MODEL_LOCK_UNREADABLE"),
            "lock_not_object": (lambda rt, wk: lock_text(rt, '"MiniMax-H3"'), "VIDEO_MODEL_LOCK_UNREADABLE"),
            "lock_empty_model": (lambda rt, wk: lock_text(rt, '{"video_model": ""}'), "VIDEO_MODEL_LOCK_INVALID"),
            "lock_unknown_model": (lambda rt, wk: write_lock(rt, "E93", "seedance-2.0-fast"),
                                   "VIDEO_MODEL_LOCK_INVALID"),
            "manifest_corrupt": (lambda rt, wk: manifest_text(wk, "{"), "VIDEO_MODEL_MANIFEST_UNREADABLE"),
            "manifest_without_model": (lambda rt, wk: write_editorial(wk, "E93", None), "VIDEO_MODEL_MANIFEST_INVALID"),
            "manifest_self_conflict": (lambda rt, wk: write_editorial(wk, "E93", SD2_ID, H3_ID),
                                       "VIDEO_MODEL_MANIFEST_SELF_CONFLICT"),
            "lock_vs_manifest": (lambda rt, wk: (write_lock(rt, "E93", H3_ID), write_editorial(wk, "E93", SD2_ID)),
                                 "VIDEO_MODEL_RECORDS_CONFLICT"),
        }
        for name, (setup, code) in cases.items():
            with self.subTest(name), nalu_roots(qingshan={"generation": {"video_model": SD2_ID}}) as (
                    tmp, runtime, work, vm, bnp):
                setup(runtime, work)
                lock = vm.record_path("E93")
                before = lock.read_bytes() if lock.exists() else None
                with self.assertRaises(vm.VideoModelSelectionError) as caught:
                    vm.episode_video_model("E93")
                self.assertEqual(caught.exception.code, code)
                with self.assertRaises(SystemExit) as stopped:
                    bnp.select_video_model("E93")
                self.assertIn(code, str(stopped.exception))
                self.assertEqual(lock.read_bytes() if lock.exists() else None, before, "lock must not be rewritten")
                error, post = run_submit_main(nalu_manifest("E93", SD2_ID), tmp)
                self.assertIsInstance(error, vm.VideoModelSelectionError)
                self.assertEqual(error.code, code)
                self.assertEqual(post.call_count, 0)
        # compiled manifest disagrees with the lock (format_contract / allowed list)
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            write_lock(runtime, "E94", H3_ID)
            write_editorial(work, "E94", H3_ID)
            for field, value in (("format_contract", {"model": SD2_ID}), ("allowed_video_models", [SD2_ID])):
                with self.subTest(field):
                    manifest = nalu_manifest("E94", H3_ID)
                    manifest[field] = value
                    error, post = run_submit_main(manifest, tmp)
                    self.assertIsInstance(error, vm.VideoModelSelectionError)
                    self.assertEqual(error.details["expected"], H3_ID)
                    self.assertEqual(error.details["source"], "episode_lock")
                    self.assertEqual(post.call_count, 0)

    # 6. a task (= the request's model field) tampered to another model: the real submit entry refuses pre-POST
    def test_real_submit_entry_refuses_tampered_task_model_before_post(self):
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            write_lock(runtime, "E95", H3_ID)
            write_editorial(work, "E95", H3_ID, H3_ID)
            manifest = nalu_manifest("E95", H3_ID, task_models=[H3_ID, SD2_ID, H3_ID])
            for precheck in (False, True):
                with self.subTest(precheck=precheck):
                    error, post = run_submit_main(manifest, tmp, precheck=precheck)
                    self.assertIsInstance(error, vm.VideoModelSelectionError)
                    self.assertEqual(error.code, "VIDEO_MODEL_MISMATCH")
                    self.assertEqual(error.details["expected"], H3_ID)
                    self.assertEqual(error.details["actual"], [f"task:E95-VU-002.model={SD2_ID}"])
                    self.assertIn(str(vm.record_path("E95")), error.details["files"])
                    self.assertEqual(post.call_count, 0)
                    self.assertFalse((tmp / "workflow/tasks/giggle_video_submit_transactions").exists())
            # control: the untampered manifest passes this check and stops later, at an unrelated gate
            error, post = run_submit_main(nalu_manifest("E95", H3_ID), tmp)
            self.assertIsNotNone(error)
            self.assertNotIsInstance(error, vm.VideoModelSelectionError)
            self.assertEqual(post.call_count, 0)

    # 7. two first selections racing: one lock, one model; the loser adopts the winner
    def test_first_selection_race_yields_one_model(self):
        with nalu_roots(qingshan={"generation": {"video_model": SD2_ID}}) as (tmp, runtime, work, vm, bnp):
            # deterministic interleaving: our read saw no lock and the config said SD2, then another
            # build locked H3 before our write.  The old is_file()-then-write_text kept SD2 here.
            real = vm.recorded_video_model

            def stale_then_other_writes(episode):
                result = real(episode)
                write_lock(runtime, episode, H3_ID)
                return result
            with mock.patch.object(vm, "recorded_video_model", stale_then_other_writes):
                self.assertEqual(bnp.select_video_model("E96")["model"], H3_ID)
            self.assertEqual(json.loads(vm.record_path("E96").read_text())["video_model"], H3_ID)
            # real processes racing on the first claim with different models
            go = tmp / "go"
            script = ("import os,sys,time\n"
                      f"sys.path.insert(0, {str(NALU_TOOLS)!r})\n"
                      "import nalu_video_model as vm\n"
                      f"while not os.path.exists({str(go)!r}): time.sleep(0.001)\n"
                      "print(vm.claim_video_model('E97', sys.argv[1]))\n")
            procs = [subprocess.Popen([sys.executable, "-c", script, (SD2_ID, H3_ID)[i % 2]], env=dict(os.environ),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
            go.write_text("1")
            outputs = [p.communicate(timeout=60) for p in procs]
            self.assertEqual([p.returncode for p in procs], [0] * 8, [err for _, err in outputs])
            winners = {out.strip() for out, _ in outputs}
            self.assertEqual(len(winners), 1, winners)
            self.assertEqual(json.loads(vm.record_path("E97").read_text())["video_model"], winners.pop())
            self.assertEqual([p.name for p in vm.record_path("E97").parent.iterdir()], ["video_model.json"])


# --------------------------------------------------------------------------- #
# K145 binding: a record is authority only for the episode it declares, and a manifest is judged only
# against the production scope (runtime/work roots + episode) it is bound to -- never by episode id alone.
# --------------------------------------------------------------------------- #
def bind_roots(runtime: Path, work: Path) -> None:
    """Point nalu_paths (and so nalu_video_model, which reads it at call time) at another line's roots.
    The surrounding nalu_roots() restores the environment and reloads nalu_paths on exit."""
    import importlib
    import nalu_paths
    runtime.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    os.environ.update(NALU_RUNTIME_ROOT=str(runtime), NALU_WORK_ROOT=str(work), NALU_IGNORE_DEPLOYMENT_PIN="1")
    importlib.reload(nalu_paths)


def scope_of(runtime: Path, work: Path, episode: str) -> dict:
    """What build_nalu_preproduction records as the manifest's production_scope."""
    return {"line": "nalu", "episode": episode, "runtime_root": str(runtime.resolve()),
            "work_root": str(work.resolve())}


class EpisodeAndScopeBindingTests(unittest.TestCase):
    # 8. a lock / editorial manifest / task row that declares ANOTHER episode is refused before any POST
    def test_wrong_episode_records_are_refused_and_left_untouched(self):
        def foreign_lock(rt, wk):
            path = rt / "preproduction" / "E67" / "video_model.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"episode": "E66", "video_model": SD2_ID}), encoding="utf-8")
            return path

        def foreign_editorial(rt, wk):
            path = write_editorial(wk, "E67", SD2_ID)
            path.write_text(json.dumps({"episode": "E66", "model_contract": {"model": SD2_ID}}), encoding="utf-8")
            return path

        def empty_episode_lock(rt, wk):
            path = foreign_lock(rt, wk)
            path.write_text(json.dumps({"episode": "", "video_model": SD2_ID}), encoding="utf-8")
            return path

        cases = {"lock": (foreign_lock, "VIDEO_MODEL_LOCK_EPISODE_MISMATCH"),
                 "lock_empty_episode": (empty_episode_lock, "VIDEO_MODEL_LOCK_EPISODE_MISMATCH"),
                 "editorial": (foreign_editorial, "VIDEO_MODEL_MANIFEST_EPISODE_MISMATCH")}
        for name, (setup, code) in cases.items():
            with self.subTest(name), nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (
                    tmp, runtime, work, vm, bnp):
                record = setup(runtime, work)
                before = record.read_bytes()
                with self.assertRaises(vm.VideoModelSelectionError) as caught:
                    vm.episode_video_model("E67")          # not SD2 from E66's record, not H3 from the config
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.details["expected"], "E67")
                with self.assertRaises(SystemExit) as stopped:
                    bnp.select_video_model("E67")
                self.assertIn(code, str(stopped.exception))
                for precheck in (False, True):
                    error, post = run_submit_main(nalu_manifest("E67", SD2_ID), tmp, precheck=precheck)
                    self.assertIsInstance(error, vm.VideoModelSelectionError)
                    self.assertEqual(error.code, code)
                    self.assertEqual(post.call_count, 0)
                self.assertEqual(record.read_bytes(), before, "the foreign record is neither deleted nor rewritten")
                if name != "editorial":
                    self.assertEqual(sorted(p.name for p in record.parent.iterdir()), ["video_model.json"])
        # a task row declaring another episode is not regrouped under (and judged by) that episode's lock
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            lock67, lock66 = write_lock(runtime, "E67", H3_ID), write_lock(runtime, "E66", SD2_ID)
            manifest = nalu_manifest("E67", H3_ID)
            manifest["tasks"].append({**deepcopy(manifest["tasks"][0]), "task_key": "E66-VU-009",
                                      "episode": "E66", "model": SD2_ID})
            error, post = run_submit_main(manifest, tmp)
            self.assertIsInstance(error, vm.VideoModelSelectionError)
            self.assertEqual(error.code, "VIDEO_MODEL_TASK_EPISODE_MISMATCH")
            self.assertEqual(error.details["actual"], ["task:E66-VU-009.episode=E66"])
            self.assertEqual(post.call_count, 0)
            with self.assertRaises(vm.VideoModelSelectionError):
                vm.check_task_models("E67", tasks=manifest["tasks"])
            self.assertEqual(json.loads(lock67.read_text())["video_model"], H3_ID)
            self.assertEqual(json.loads(lock66.read_text())["video_model"], SD2_ID)

    # 9. legacy records WITHOUT an episode field: accepted for the episode whose own path holds them
    def test_legacy_records_without_episode_field_are_path_attributed(self):
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            for ep, lock_doc in (("E05", {"video_model": SD2_ID}), ("E06", {"episode": None, "video_model": SD2_ID})):
                path = vm.record_path(ep)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(lock_doc), encoding="utf-8")
            write_editorial(work, "E05", SD2_ID)                      # editorial without an episode field
            sel = vm.recorded_selection("E05")
            self.assertEqual(sel["video_model"], SD2_ID)
            self.assertEqual(sel["episode_attribution"],
                             {"episode_lock": "path_legacy", "editorial_manifest": "path_legacy"})
            self.assertEqual(vm.recorded_selection("E06")["episode_attribution"], {"episode_lock": "path_legacy"})
            write_lock(runtime, "E08", H3_ID)
            self.assertEqual(vm.recorded_selection("E08")["episode_attribution"], {"episode_lock": "declared"})
            # a legacy record is authority for its OWN path only: E05's lock says nothing about E09
            self.assertIsNone(vm.recorded_selection("E09"))
            from tools import submit_giggle_video_manifest_v2 as video
            self.assertEqual(video.require_episode_video_model(nalu_manifest("E05", SD2_ID), tmp / "m"),
                             {"E05": SD2_ID})
            legacy_task = nalu_manifest("E05", SD2_ID)
            del legacy_task["tasks"][0]["episode"]                    # a row without episode = the manifest's
            self.assertEqual(video.require_episode_video_model(legacy_task, tmp / "m"), {"E05": SD2_ID})

    # 10. two independent lines, same episode id: each judged against its own records
    def test_two_lines_same_episode_id_correct_attribution_passes(self):
        from tools import submit_giggle_video_manifest_v2 as video
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime_a, work_a, vm, bnp):
            write_lock(runtime_a, "E12", H3_ID)
            write_editorial(work_a, "E12", H3_ID, H3_ID)
            runtime_b, work_b = tmp / "line_b" / "runtime", tmp / "line_b" / "work"
            lock_b = write_lock(runtime_b, "E12", SD2_ID)
            write_editorial(work_b, "E12", SD2_ID, SD2_ID)
            # line A: its own nalu manifest, in A's work root, declaring A's scope
            manifest_a = {**nalu_manifest("E12", H3_ID), "production_scope": scope_of(runtime_a, work_a, "E12")}
            path_a = work_a / "E12" / "preproduction" / "E12_VIDEO_TRANSACTION_MANIFEST_V1.json"
            self.assertEqual(video.require_episode_video_model(manifest_a, path_a), {"E12": H3_ID})
            # an independent project (non-nalu builder) with its own E12 on SD2: not judged by A's H3 lock
            other = {**nalu_manifest("E12", SD2_ID), "generated_by": "other_line_builder.v1",
                     "project_id": "INDEPENDENT_OTHER_SERIES"}
            other_path = tmp / "line_b_project" / "manifest.json"
            self.assertIsNone(video.require_episode_video_model(other, other_path))
            error, post = run_submit_main(other, tmp / "line_b_project", precheck=True, path=other_path)
            self.assertNotIsInstance(error, vm.VideoModelSelectionError)   # stops later, at its own gates
            self.assertEqual(post.call_count, 0)
            # a second nalu runtime B: judged against B's records when B's roots are the ones in effect
            manifest_b = {**nalu_manifest("E12", SD2_ID), "production_scope": scope_of(runtime_b, work_b, "E12")}
            path_b = work_b / "E12" / "preproduction" / "E12_VIDEO_TRANSACTION_MANIFEST_V1.json"
            bind_roots(runtime_b, work_b)
            self.assertEqual(video.require_episode_video_model(manifest_b, path_b), {"E12": SD2_ID})
            self.assertEqual(vm.recorded_selection("E12")["files"][0], str(lock_b))
            # the legacy E12-style manifest (nalu builder, no production_scope, in its work root) still passes
            bind_roots(runtime_a, work_a)
            legacy = nalu_manifest("E12", H3_ID)
            self.assertEqual(video.require_episode_video_model(legacy, path_a), {"E12": H3_ID})

    # 11. wrong attribution / lock-vs-manifest conflicts across scopes: refused in the real main(), POST=0
    def test_wrong_attribution_and_cross_scope_conflicts_fail_in_main(self):
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime_a, work_a, vm, bnp):
            lock_a = write_lock(runtime_a, "E12", H3_ID)
            write_editorial(work_a, "E12", H3_ID, H3_ID)
            runtime_b, work_b = tmp / "line_b" / "runtime", tmp / "line_b" / "work"
            lock_b = write_lock(runtime_b, "E12", SD2_ID)
            locks_before = (lock_a.read_bytes(), lock_b.read_bytes())
            in_a = work_a / "E12" / "preproduction" / "E12_VIDEO_TRANSACTION_MANIFEST_V1.json"
            b_project = tmp / "line_b_project" / "manifest.json"
            prompt_e13 = work_a / "E13" / "preproduction" / "video_prompts" / "E13-VU-001.txt"
            prompt_e13.parent.mkdir(parents=True)
            prompt_e13.write_text("x", encoding="utf-8")
            cases = {
                # built against runtime B (its SD2 lock), submitted with A's roots in effect
                "nalu_manifest_of_runtime_b_under_roots_a": (
                    {**nalu_manifest("E12", SD2_ID), "production_scope": scope_of(runtime_b, work_b, "E12")},
                    b_project, "VIDEO_MODEL_SCOPE_MISMATCH"),
                # same, but the scope names A's runtime with B's work root: any mismatching root refuses
                "half_rebound_scope": (
                    {**nalu_manifest("E12", H3_ID), "production_scope": {**scope_of(runtime_a, work_a, "E12"),
                                                                          "work_root": str(work_b)}},
                    in_a, "VIDEO_MODEL_SCOPE_MISMATCH"),
                "scope_episode_differs": (
                    {**nalu_manifest("E12", H3_ID), "production_scope": scope_of(runtime_a, work_a, "E13")},
                    in_a, "VIDEO_MODEL_SCOPE_MISMATCH"),
                # renaming generated_by does not move a manifest in A's work root out of A's check
                "generated_by_renamed_inside_a": (
                    {**nalu_manifest("E12", SD2_ID), "generated_by": "other_line_builder.v1"},
                    in_a, "VIDEO_MODEL_MISMATCH"),
                # nor does relabelling its scope as another line
                "relabelled_other_line_inside_a": (
                    {**nalu_manifest("E12", SD2_ID), "generated_by": "other_line_builder.v1",
                     "production_scope": {"line": "other"}}, in_a, "VIDEO_MODEL_SCOPE_CONFLICT"),
                "nalu_builder_claims_other_line": (
                    {**nalu_manifest("E12", SD2_ID), "production_scope": {"line": "other"}},
                    b_project, "VIDEO_MODEL_SCOPE_CONFLICT"),
                # lock-vs-manifest across scopes: B's SD2 manifest relabelled with A's scope meets A's H3 lock
                "b_manifest_relabelled_to_scope_a": (
                    {**nalu_manifest("E12", SD2_ID), "production_scope": scope_of(runtime_a, work_a, "E12")},
                    b_project, "VIDEO_MODEL_MISMATCH"),
                # an E12 manifest whose prompts live in A's E13 directory
                "prompt_in_other_episode_dir": (
                    {**nalu_manifest("E12", H3_ID, prompt=prompt_e13), "generated_by": "other_line_builder.v1"},
                    b_project, "VIDEO_MODEL_SCOPE_EPISODE_MISMATCH"),
                "scope_not_object": (
                    {**nalu_manifest("E12", H3_ID), "production_scope": "nalu"}, in_a, "VIDEO_MODEL_SCOPE_INVALID"),
            }
            for name, (manifest, path, code) in cases.items():
                for precheck in (False, True):
                    with self.subTest(name, precheck=precheck):
                        error, post = run_submit_main(manifest, path.parent, precheck=precheck, path=path)
                        self.assertIsInstance(error, vm.VideoModelSelectionError)
                        self.assertEqual(error.code, code, error)
                        self.assertEqual(post.call_count, 0)
                        self.assertFalse((path.parent / "workflow/tasks/giggle_video_submit_transactions").exists())
                        if code == "VIDEO_MODEL_MISMATCH":
                            self.assertEqual(error.details["expected"], H3_ID)
                            self.assertIn(str(lock_a), error.details["files"])
            self.assertEqual((lock_a.read_bytes(), lock_b.read_bytes()), locks_before)

    # 12. the builder records the scope it was built against, and that is what the submitter accepts
    def test_builder_records_production_scope(self):
        source = (NALU_TOOLS / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        self.assertIn('"production_scope": {"line": "nalu", "episode": episode,', source)
        with nalu_roots(qingshan={"generation": {"video_model": H3_ID}}) as (tmp, runtime, work, vm, bnp):
            import nalu_paths
            recorded = {"line": "nalu", "episode": "E12",
                        "runtime_root": str(Path(nalu_paths.RUNTIME_ROOT).expanduser().resolve()),
                        "work_root": str(Path(nalu_paths.WORK_ROOT).expanduser().resolve())}
            self.assertEqual(recorded, scope_of(runtime, work, "E12"))
