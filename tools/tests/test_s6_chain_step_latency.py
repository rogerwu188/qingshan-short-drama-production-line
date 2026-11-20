#!/usr/bin/env python3
"""S6 chain-step latency (2026-11-19): in-run polling, REMOTE_WAIT scaling, narrowed ARE verify, compile cache.

A tail-chained successor used to wait ~12 min per step: its predecessor's run POSTed, polled once and exited
VIDEO_NOT_ALL_COMPLETED; the tick re-ran it 240 s + up to 3 min later; and the re-run recompiled the episode
(twice when the start frame was not yet bound) before the successor's POST.  No network; no provider.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import nalu_pipeline as P  # noqa: E402
import paid_run_status as prs  # noqa: E402
import action_role_evidence_writer as are_writer  # noqa: E402


class _Provider:
    """Stands in for the paid submit (``_stage_s6_body``) and the GET-only live-bound poll."""

    def __init__(self, video: Path, render_polls: dict[str, int]):
        self.video = video
        self.render_polls = dict(render_polls)  # polls until the clip is complete (absent = never)
        self.submitted: list[str] = []
        self.polls = 0

    def _poll(self, units):
        self.polls += 1
        for uid in units:
            if uid in self.submitted and uid in self.render_polls:
                self.render_polls[uid] -= 1
                if self.render_polls[uid] <= 0:
                    (self.video / f"{uid}.mp4").write_bytes(b"clip")
        res = P.StageResult(P.PASS)
        if not all((self.video / f"{u}.mp4").is_file() for u in units):
            res.status = P.BLOCKED
            res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
        return res

    def body(self, _ctx, *, ready_units=None, run_qa=True, final_pass=False):
        units = list(ready_units or [])
        if final_pass:
            return P.StageResult(P.PASS)
        new = [u for u in units if u not in self.submitted and not (self.video / f"{u}.mp4").is_file()]
        self.submitted.extend(new)
        res = self._poll(units)
        if new:
            res.details["posted_task_keys"] = new
        return res

    def live_bound(self, _ctx, units):
        missing = [u for u in units if not (self.video / f"{u}.mp4").is_file()]
        if missing and all(u in self.submitted for u in missing):
            return {"missing": missing, "live": {u: [{"task_id": "t"}] for u in missing}}
        return None

    def poll_live(self, _ctx, _wave, plan):
        return self._poll(plan["missing"])


class _Harness:
    def __init__(self, tmp: Path, deps, render_polls, *, paid=True, live=True):
        self.video = tmp / "video"
        self.preprod = tmp / "preproduction"
        self.reports = self.preprod / "reports"
        for d in (self.video, self.reports):
            d.mkdir(parents=True, exist_ok=True)
        self.tails = self.preprod / "real_final_frames"
        self.provider = _Provider(self.video, render_polls)
        self.sleeps: list[int] = []
        self.said: list[str] = []
        self.ctx = SimpleNamespace(
            episode="E99", dry=False, paid_enabled=paid, say=self.said.append, run_id="RUN",
            p=SimpleNamespace(preprod=self.preprod, video_media=self.video, preprod_reports=self.reports,
                              video_submit=tmp / "submit.json", video_remote_status=tmp / "status.json",
                              contract=tmp / "contract.json"))

        def extract(_ctx, uid):
            if not (self.video / f"{uid}.mp4").is_file():
                return {"unit_id": uid, "status": "SOURCE_MISSING"}
            self.tails.mkdir(parents=True, exist_ok=True)
            dst = self.tails / f"{uid}.png"
            if dst.is_file():
                return {"unit_id": uid, "status": "ALREADY_PRESENT"}
            dst.write_bytes(b"tail")
            return {"unit_id": uid, "status": "EXTRACTED"}

        self.patches = [
            mock.patch.object(P, "ENGINE", tmp / "engine"),
            mock.patch.object(P, "previs_gate", lambda _c, _s: {}),
            mock.patch.object(P, "unit_dependency_order", lambda _c: list(deps)),
            mock.patch.object(P, "park_stale_real_final_frames", lambda _c, _u: []),
            mock.patch.object(P, "redo_switch_start_frames", lambda _c: []),
            mock.patch.object(P, "materialise_derived_keyframes", lambda _c: []),
            mock.patch.object(P, "own_keyframes_needed", lambda _c: []),
            mock.patch.object(P, "derived_units_pending_q1", lambda _c: []),
            mock.patch.object(P, "tail_sourced_units", lambda _c: {}),
            mock.patch.object(P, "release_unposted_waves", lambda _c, _s: []),
            mock.patch.object(P, "_stage_s6_body", self.provider.body),
            mock.patch.object(P, "_s6_live_bound_wave",
                              self.provider.live_bound if live else (lambda _c, _u: None)),
            mock.patch.object(P, "_s6_poll_live_bound_wave", self.provider.poll_live),
            mock.patch.object(P, "extract_real_final_frame", extract),
            mock.patch.object(P, "_s6_sleep", self.sleeps.append),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False

    def run(self):
        return P.stage_s6(self.ctx)


CHAIN = [("A1", None, False), ("A2", "A1", True), ("A3", "A2", True)]
ENV = {"NALU_S6_INRUN_POLL_MAX_SECONDS": "1500", "NALU_S6_INRUN_POLL_WAIT_SECONDS": "600",
       "NALU_S6_INRUN_POLL_INTERVAL_SECONDS": "25"}


class InRunPollingTest(unittest.TestCase):
    def test_the_chain_continues_in_the_same_run(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            with _Harness(Path(tmp), CHAIN, {"A1": 4, "A2": 3}) as h:
                res = h.run()
                submitted, sleeps = list(h.provider.submitted), list(h.sleeps)
                log = "\n".join(h.said)
        # A1 POSTed, the run polled until it landed, extracted its tail and POSTed A2, then A3 the same way
        self.assertEqual(submitted, ["A1", "A2", "A3"])
        self.assertTrue(sleeps and all(s == 25 for s in sleeps))
        summary = res.details["s6_inrun_poll"]
        self.assertEqual([row["units"] for row in summary["chain_steps"]], [["A1"], ["A2"], ["A3"]])
        self.assertEqual(summary["stop_reason"], "NO_SUCCESSOR_WAITS_ON_AN_IN_FLIGHT_UNIT")
        self.assertEqual(summary["chain_continuations"], 2)
        self.assertIn("S6_CHAIN_STEP wave=", log)
        self.assertIn("prep=", log)
        # A3 is still rendering and nothing waits on it: the run exits for the tick exactly as before
        self.assertEqual(res.status, P.BLOCKED)
        self.assertIn("VIDEO_NOT_ALL_COMPLETED", res.blockers)

    def test_the_total_bound_ends_the_in_run_wait(self):
        env = {**ENV, "NALU_S6_INRUN_POLL_MAX_SECONDS": "100"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env):
            with _Harness(Path(tmp), CHAIN, {}) as h:  # A1 never finishes
                res = h.run()
                self.assertEqual(h.provider.submitted, ["A1"])
                self.assertEqual(sum(h.sleeps), 100)
        self.assertEqual(res.details["s6_inrun_poll"]["stop_reason"], "INRUN_POLL_MAX_SECONDS_REACHED")
        self.assertEqual(res.status, P.BLOCKED)
        self.assertEqual({prs.blocker_code(b) for b in res.blockers}, {"VIDEO_NOT_ALL_COMPLETED"})

    def test_the_per_step_bound_ends_the_in_run_wait(self):
        env = {**ENV, "NALU_S6_INRUN_POLL_WAIT_SECONDS": "50"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env):
            with _Harness(Path(tmp), CHAIN, {}) as h:
                res = h.run()
                self.assertEqual(h.sleeps, [25, 25])
        self.assertEqual(res.details["s6_inrun_poll"]["stop_reason"], "INRUN_POLL_WAIT_SECONDS_REACHED")

    def test_a_poll_only_rerun_does_not_wait_in_run(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            with _Harness(Path(tmp), CHAIN, {}) as h:
                h.run()  # POSTs A1 (and waits until the bound)
                h.sleeps.clear()
                res = h.run()  # re-run: nothing new to POST -> one poll, exit for the tick
                self.assertEqual(h.sleeps, [])
        self.assertEqual(res.details["s6_inrun_poll"]["stop_reason"], "NO_POST_THIS_RUN")

    def test_disabled_without_paid_or_with_zero_budget_or_without_live_binding(self):
        cases = [({}, {"paid": False}), ({"NALU_S6_INRUN_POLL_MAX_SECONDS": "0"}, {}), ({}, {"live": False})]
        for extra_env, kw in cases:
            with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {**ENV, **extra_env}):
                with _Harness(Path(tmp), CHAIN, {"A1": 2}, **kw) as h:
                    h.run()
                    self.assertEqual(h.sleeps, [], (extra_env, kw))
                    self.assertEqual(h.provider.submitted, ["A1"], (extra_env, kw))

    def test_independent_units_do_not_hold_the_run(self):
        deps = [("B1", None, False), ("B2", None, False)]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, ENV):
            with _Harness(Path(tmp), deps, {}) as h:
                res = h.run()
                self.assertEqual(h.sleeps, [])
        self.assertEqual(res.details["s6_inrun_poll"]["stop_reason"], "NO_SUCCESSOR_WAITS_ON_AN_IN_FLIGHT_UNIT")


class RemoteWaitScalingTest(unittest.TestCase):
    def test_interval_lowered_and_cap_scaled_to_the_same_budget(self):
        row = prs.REMOTE_WAIT["VIDEO_NOT_ALL_COMPLETED"]
        self.assertTrue(60 <= row["interval_s"] <= 90)
        self.assertEqual(row["interval_s"] * row["max_reruns"], 90 * 240)
        out = prs.classify({"stages": {"S6": {"status": "BLOCKED", "blockers": ["VIDEO_NOT_ALL_COMPLETED"]}}},
                           "S6", "S6")
        self.assertEqual((out["interval_s"], out["max_reruns"]), (row["interval_s"], row["max_reruns"]))
        # the image outage wait is untouched
        self.assertEqual(prs.REMOTE_WAIT["HOPSAPI_IMAGE_PROVIDER_OUTAGE"], {"interval_s": 600, "max_reruns": 6})

    def test_inrun_poll_knobs(self):
        ctx = SimpleNamespace(paid_enabled=True, dry=False)
        with mock.patch.dict(os.environ, {"NALU_S6_INRUN_POLL_INTERVAL_SECONDS": "1"}):
            self.assertEqual(P.S6InRunPoll(ctx).interval_s, 5)
        with mock.patch.dict(os.environ, {"NALU_S6_INRUN_POLL_INTERVAL_SECONDS": "999"}):
            self.assertEqual(P.S6InRunPoll(ctx).interval_s, 120)
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ENV:
                os.environ.pop(k, None)
            poll = P.S6InRunPoll(ctx)
            self.assertEqual((poll.interval_s, poll.max_wait_s, poll.max_total_s), (25, 600, 1500))


class NarrowedActionRoleCheckTest(unittest.TestCase):
    def _ctx(self, tmp):
        return SimpleNamespace(episode="E99", p=SimpleNamespace(keyframes=Path(tmp)))

    def test_verify_is_scoped_to_the_wave_and_still_runs_for_the_new_unit(self):
        calls = []

        def fake_qa_run(_ctx, argv, *, name):
            calls.append([str(a) for a in argv])
            return {"name": name}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(P, "qa_run", fake_qa_run), \
                mock.patch.object(P, "qa_json", lambda _s: {"missing": [], "failing": []}):
            res = P.StageResult(P.PASS)
            detail = P.s6_action_role_evidence(self._ctx(tmp), res, ["E99-VU-004"])
            self.assertEqual(detail["status"], P.PASS)
            self.assertEqual(calls[-1][-2:], ["--units", json.dumps(["E99-VU-004"])])
            P.s6_action_role_evidence(self._ctx(tmp), res, None)  # final pass / unscoped: every unit
            self.assertNotIn("--units", calls[-1])

    def test_writer_verify_validates_only_the_units_asked_for(self):
        contracts = {"E99-VU-001": {"reference_path": ""}, "E99-VU-004": {"reference_path": ""}}
        validated = []
        gate = SimpleNamespace(_validate_action_role_verification=lambda payload, expected_sha: (
            validated.append(payload) or ["BAD"]))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(are_writer, "engine_module", lambda _n: gate), \
                mock.patch.object(are_writer, "Expectations", lambda _e: SimpleNamespace(start_frame_units=contracts)), \
                mock.patch.object(are_writer, "evidence_path", lambda _e, u: Path(tmp) / f"{u}.json"):
            (Path(tmp) / "E99-VU-004.json").write_text(json.dumps({"schema": "x"}))
            rep = are_writer.verify("E99", ["E99-VU-004"])
            self.assertEqual([r["unit_id"] for r in rep["rows"]], ["E99-VU-004"])
            self.assertEqual(rep["failing"], ["E99-VU-004"])  # the engine validator still ran on it
            self.assertEqual(len(validated), 1)
            full = are_writer.verify("E99")
            self.assertEqual(full["units"], 2)
            self.assertEqual(full["missing"], ["E99-VU-001"])


class CompileCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        work = root / "workflow" / "E99"
        preprod = work / "preproduction"
        (preprod / "real_final_frames").mkdir(parents=True)
        (preprod / "keyframes").mkdir()
        self.report = preprod / "E99_PREPRODUCTION_REPORT.json"
        self.report.write_text("{}")
        self.tail = preprod / "real_final_frames" / "E99-VU-001.png"
        self.tail.write_bytes(b"tail-1")
        self.ctx = SimpleNamespace(
            episode="E99", run_id="RUN", say=lambda *_a: None,
            p=SimpleNamespace(work=work, preprod=preprod, rt_pre=root / "rt_pre", logs=root / "logs",
                              preprod_report=self.report, machine_gate_bundle=preprod / "bundle.json",
                              contract=root / "contract.json", writer_manifest=root / "manifest.json",
                              gsm=root / "gsm.json", asset_requirements=root / "req.json", overlay=None,
                              scope={}, legacy_grouping_plan=root / "adapter" / "plan.json"))
        self.compiles = []
        self.status = P.PASS

        def fake_s2(ctx, *, with_keyframes=False, ready_units=None):
            self.compiles.append(list(ready_units or []))
            (ctx.p.preprod / "E99_VIDEO_TRANSACTION_MANIFEST_V1.json").write_text(
                json.dumps({"units": ready_units, "n": len(self.compiles)}))
            res = P.StageResult(self.status)
            res.steps = [{"name": "s2_build_nalu_preproduction_with_keyframes", "exit_code": 0}]
            return res

        self.patches = [
            mock.patch.object(P, "ENGINE", root / "engine"),
            mock.patch.object(P, "stage_s2", fake_s2),
            mock.patch.object(P, "s2_argv", lambda ctx, *, with_keyframes, ready_units=None:
                              ["build", "--ready-units", json.dumps(list(ready_units or []))]),
            mock.patch.dict(os.environ, {"NALU_S6_COMPILE_CACHE": "1"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()

    def test_an_unchanged_recompile_is_skipped(self):
        first = P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        second = P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.assertEqual(len(self.compiles), 1)
        self.assertEqual(first.status, P.PASS)
        self.assertEqual((second.status, second.details["compile_cache"]["hit"]), (P.PASS, True))
        self.assertIn(str(self.report), second.receipts)

    def test_an_input_change_invalidates_the_cache(self):
        P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.tail.write_bytes(b"tail-2, a new real final frame")
        P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.assertEqual(len(self.compiles), 2)
        # a change to a compile OUTPUT (e.g. someone edited the manifest) is a miss as well
        (self.ctx.p.preprod / "E99_VIDEO_TRANSACTION_MANIFEST_V1.json").write_text("{}")
        P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.assertEqual(len(self.compiles), 3)
        P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.assertEqual(len(self.compiles), 3)

    def test_a_different_wave_or_a_failed_compile_is_never_served_from_cache(self):
        P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        P.s6_compile(self.ctx, ready_units=["E99-VU-003"])
        self.assertEqual(len(self.compiles), 2)
        self.status = P.BLOCKED
        P.s6_compile(self.ctx, ready_units=["E99-VU-004"])
        P.s6_compile(self.ctx, ready_units=["E99-VU-004"])
        self.assertEqual(len(self.compiles), 4)

    def test_the_cache_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {"NALU_S6_COMPILE_CACHE": "0"}):
            P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
            P.s6_compile(self.ctx, ready_units=["E99-VU-002"])
        self.assertEqual(len(self.compiles), 2)


if __name__ == "__main__":
    unittest.main()
