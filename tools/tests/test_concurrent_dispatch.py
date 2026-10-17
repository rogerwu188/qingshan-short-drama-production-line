#!/usr/bin/env python3
"""Regression tests for the concurrent-dispatch fixes (mock-only, no provider).

These three properties were FAILING reproductions until 2026-10-13; each is now FIXED
and green, so unlike the audit reproductions they BELONG IN portable CI: they are what
keeps the fix from being silently undone.  Each carries the concrete defect it was
written against.

  * SubmitterFixedWaveBarrierRepro -- submitter main() sliced tasks into
    range(0, len(tasks), concurrency) waves and opened the next slice only after
    as_completed() drained the whole wave.  Fixed by a bounded ready queue that
    refills a slot the moment ITS POST returns (FIRST_COMPLETED).  E11 wave11
    2026-10-11: 124.4 s spread over 6 tasks at concurrency 3.
  * S6TailChainWaveBarrierRepro -- stage_s6 extracted a wave's real final frames only
    after the WHOLE wave passed poll, so a ready tail-chained successor waited on
    every unrelated unit of its wave.  Fixed by per-unit extraction as soon as that
    unit's own video lands.
  * S6RemoteInflightBoundRepro -- a wave opened with every ready unit while
    --concurrency bounded only POST threads.  Fixed by an OPT-IN bound
    (generation.max_remote_inflight); with none configured the previous behaviour is
    preserved deliberately, because defaulting it to max_parallel would cap every wave
    at the deployment's POST-thread count and hand the provider less work than
    production intends.

The two BudgetConcurrentReservationRepro cases are NOT here: they are still failing by
design (a bounded-exposure approximation was tried and reverted, commit 29e3453) and
live in test_concurrent_dispatch_audit_repro.py, which is kept out of the CI manifest.

Money safety: nothing here may reach a provider.  The submitter's POST path, the pay
statement fetch and the S6 submit/poll body are replaced with in-process fakes, the API
key is a dummy, and a socket guard turns any outbound connection into a test error.
All filesystem state lives in a TemporaryDirectory.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


class _NoNetwork:
    """Any outbound connection attempt is a hard test error (belt and braces)."""

    def __enter__(self):
        def refuse(*_args, **_kwargs):
            raise AssertionError("network access attempted inside a mock-only reproduction test")

        self._patches = [
            mock.patch.object(socket.socket, "connect", refuse),
            mock.patch.object(socket.socket, "connect_ex", refuse),
            mock.patch.object(socket, "create_connection", refuse),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False

# --------------------------------------------------------------------------- #
# Submitter: tools/submit_giggle_video_manifest_v2.py main()
# --------------------------------------------------------------------------- #
class _SubmitterHarness:
    """Drive the real submitter main() with every gate, POST and statement call faked."""

    def __init__(self, tmp: Path, task_keys: list[str], concurrency: int, fake_submit_one):
        import tools.submit_giggle_video_manifest_v2 as submitter

        self.S = submitter
        self.tmp = tmp
        manifest = {
            "episode": "E99",
            # skip the cross-task camera/transition sequence gates: they are not under test
            "partial_repair_scope": True,
            "machine_gate_reports": ["gate.json"],
            "tasks": [{"task_key": key, "model": "MOCK-MODEL"} for key in task_keys],
        }
        self.manifest_path = tmp / "manifest.json"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.out = tmp / "out" / "submit_report.json"
        self.argv = ["submit_giggle_video_manifest_v2.py", "--project-root", str(tmp),
                     "--manifest", str(self.manifest_path), "--out", str(self.out),
                     "--concurrency", str(concurrency)]
        self.patches = [
            mock.patch.object(submitter, "ROOT", submitter.ROOT),  # main() rebinds the global
            mock.patch.object(submitter, "require_e47_efficiency_contract", lambda _m: {"status": "PASS"}),
            mock.patch.object(submitter, "run_authoritative_submission_gate", lambda _m, _p: {"status": "PASS"}),
            mock.patch.object(submitter, "validate_gate", lambda _v: {"status": "PASS"}),
            mock.patch.object(submitter, "validate_task", lambda _t: None),
            # main() now runs every pre-POST gate through one shared chain so the
            # repo entrypoint cannot validate less than the deployed one.  Those
            # gates are file- and contract-based; this harness isolates wave
            # scheduling, so it fakes the chain exactly as it fakes the rest.
            mock.patch.object(submitter, "validate_task_submission_gates", lambda _t: []),
            mock.patch.object(submitter, "submit_one", fake_submit_one),
            mock.patch.object(submitter, "_request", self._forbidden_request),
            mock.patch.object(submitter, "fetch_pay_statements", lambda: []),
            mock.patch.object(submitter, "reconcile_rows", self._reconcile),
            mock.patch.object(sys, "argv", self.argv),
            mock.patch.dict(os.environ, {"GIGGLE_API_KEY": "MOCK-KEY-NO-NETWORK"}),
        ]

    @staticmethod
    def _forbidden_request(*_args, **_kwargs):
        raise AssertionError("real _request reached in a mock-only test")

    @staticmethod
    def _reconcile(_rows, **kwargs):
        return {"status": "PASS", "matched_count": kwargs.get("expected_count", 0), "charged_credits": 0}

    def __enter__(self):
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()
        return False

    def report(self) -> dict:
        return json.loads(self.out.read_text(encoding="utf-8"))


class SubmitterFixedWaveBarrierRepro(unittest.TestCase):
    """Proposal §2/§5, §8 item 2: a slow POST must not hold a free submit slot idle.

    CONFIRMED root cause: ``main()`` slices ``tasks`` into ``range(0, len(tasks),
    concurrency)`` waves and wraps each slice in its own ``ThreadPoolExecutor``, so the next
    slice only opens after ``as_completed()`` has drained the whole wave (line ~1134-1138).
    """

    def test_slow_post_does_not_block_next_ready_task_from_free_slot(self):
        release_slow = threading.Event()
        started = {key: threading.Event() for key in ("T0", "T1", "T2", "T3")}

        def fake_submit_one(task, _receipts, _transactions):
            key = task["task_key"]
            started[key].set()
            if key == "T0":
                # the slow POST: still waiting for the provider's response
                release_slow.wait(timeout=10)
            return {"task_key": key, "task_id": f"tid-{key}", "state": "remote_running",
                    "recovered_from_transaction": False}

        with tempfile.TemporaryDirectory() as tmp, _NoNetwork():
            with _SubmitterHarness(Path(tmp), ["T0", "T1", "T2", "T3"], 2, fake_submit_one) as harness:
                runner = threading.Thread(target=harness.S.main, daemon=True)
                runner.start()
                try:
                    self.assertTrue(started["T1"].wait(timeout=5), "T1 never started")
                    # T1 has returned its task id, so one of the two submit slots is free.  T2 is an
                    # independent ready task; a bounded ready queue would start it now.
                    refilled = started["T2"].wait(timeout=1.5)
                    slow_still_blocked = not release_slow.is_set()
                finally:
                    release_slow.set()
                    runner.join(timeout=10)
                self.assertFalse(runner.is_alive(), "submitter main() did not finish")
                self.assertEqual(harness.report()["submitted"], 4)
        self.assertTrue(slow_still_blocked)
        self.assertTrue(
            refilled,
            "FIXED_WAVE_BARRIER: with --concurrency 2, T2 did not start while T0's POST was still "
            "pending although T1 had already returned; main() only opens the next "
            "range(0, len(tasks), concurrency) slice after the whole ThreadPoolExecutor wave exits",
        )


# --------------------------------------------------------------------------- #
# Nalu S6 rolling-wave scheduler: lines/nalu/runtime/tools/nalu_pipeline.py stage_s6()
# --------------------------------------------------------------------------- #
class _FakeProvider:
    """Stands in for _stage_s6_body: submit (once per unit), then poll/download what finished."""

    def __init__(self, video_dir: Path):
        self.video_dir = video_dir
        self.submitted: list[str] = []
        self.finished: set[str] = set()
        self.calls: list[list[str]] = []
        self.peak_in_flight = 0

    def in_flight(self) -> set[str]:
        return {uid for uid in self.submitted if not (self.video_dir / f"{uid}.mp4").is_file()}

    def body(self, _ctx, *, ready_units=None, run_qa=True, final_pass=False):
        import nalu_pipeline as P

        units = list(ready_units or [])
        self.calls.append(units)
        res = P.StageResult(P.PASS)
        if final_pass:
            return res
        for uid in units:
            if uid not in self.submitted and not (self.video_dir / f"{uid}.mp4").is_file():
                self.submitted.append(uid)
        self.peak_in_flight = max(self.peak_in_flight, len(self.in_flight()))
        for uid in units:  # the poller downloads only remote_status == completed
            if uid in self.finished:
                (self.video_dir / f"{uid}.mp4").write_bytes(b"mock-mp4")
        if not all((self.video_dir / f"{uid}.mp4").is_file() for uid in units):
            res.status = P.BLOCKED
            res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
        return res


class _S6Harness:
    def __init__(self, tmp: Path, deps: list[tuple[str, str | None, bool]], **ctx_extra):
        import nalu_pipeline as P

        self.P = P
        self.preprod = tmp / "preproduction"
        self.video = tmp / "video"
        self.reports = tmp / "reports"
        for path in (self.preprod, self.video, self.reports):
            path.mkdir(parents=True, exist_ok=True)
        self.tails = self.preprod / "real_final_frames"
        self.provider = _FakeProvider(self.video)
        self.ctx = SimpleNamespace(
            episode="E99", dry=False, say=lambda *_a, **_k: None,
            p=SimpleNamespace(preprod=self.preprod, video_media=self.video, preprod_reports=self.reports,
                              video_submit=tmp / "video_submit.json",
                              video_remote_status=tmp / "video_remote_status.json"),
            paths=SimpleNamespace(contract=tmp / "contract.json"),
            **ctx_extra,
        )

        def extract(_ctx, uid):
            src = self.video / f"{uid}.mp4"
            if not src.is_file():
                return {"unit_id": uid, "status": "SOURCE_MISSING"}
            self.tails.mkdir(parents=True, exist_ok=True)
            dst = self.tails / f"{uid}.png"
            if dst.is_file():
                return {"unit_id": uid, "status": "ALREADY_PRESENT", "path": str(dst)}
            dst.write_bytes(b"mock-tail")
            return {"unit_id": uid, "status": "EXTRACTED", "path": str(dst)}

        self.patches = [
            mock.patch.object(P, "ENGINE", tmp / "engine"),
            mock.patch.object(P, "unit_dependency_order", lambda _ctx: list(deps)),
            mock.patch.object(P, "materialise_derived_keyframes", lambda _ctx: []),
            mock.patch.object(P, "derived_units_pending_q1", lambda _ctx: []),
            mock.patch.object(P, "continuity_derived_units", lambda _ctx: {}),
            mock.patch.object(P, "_stage_s6_body", self.provider.body),
            mock.patch.object(P, "extract_real_final_frame", extract),
        ]

    def __enter__(self):
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()
        return False

    def tick(self):
        return self.P.stage_s6(self.ctx)


class S6TailChainWaveBarrierRepro(unittest.TestCase):
    """Proposal §3, §8 item 3: independent tail chains advance on their own evidence.

    CONFIRMED root cause: ``stage_s6`` extracts a wave's real final frames only after the
    whole wave passes poll (``r.status == PASS`` -> ``extract_real_final_frame`` per unit,
    line ~3985), and a unit that needs its predecessor's tail is only ready once
    ``real_final_frames/<prev>.png`` exists.  A ready successor therefore waits for every
    unrelated unit in its wave.
    """

    def test_chain_successor_starts_once_its_own_predecessor_is_done_not_the_whole_wave(self):
        # Chain A: A1 -> A2 (A2 genuinely needs A1's real final frame).  B1 is independent.
        deps = [("A1", None, False), ("A2", "A1", True), ("B1", "A2", False)]
        with tempfile.TemporaryDirectory() as tmp, _NoNetwork():
            with _S6Harness(Path(tmp), deps, max_parallel=6) as h:
                h.tick()  # wave 1 opens with A1 and B1
                self.assertEqual(sorted(h.provider.submitted), ["A1", "B1"])
                h.provider.finished.add("A1")  # A1 renders; B1 is still rendering remotely
                h.tick()  # poll: A1's video lands on disk
                h.tick()  # next scheduler tick, B1 still rendering
                a1_on_disk = (h.video / "A1.mp4").is_file()
                a1_tail = (h.tails / "A1.png").is_file()
                submitted = list(h.provider.submitted)
        self.assertTrue(a1_on_disk)
        self.assertIn(
            "A2", submitted,
            "S6_WAVE_COMPLETION_BARRIER: A1's video is on disk but its real final frame "
            f"(extracted={a1_tail}) is only taken after EVERY unit of its wave passes poll, so A2 "
            "waits for the unrelated B1; submitted so far=" + repr(submitted),
        )


class S6RemoteInflightBoundRepro(unittest.TestCase):
    """Proposal §5, §8 item 13: remote in-flight is bounded separately from submit workers.

    CONFIRMED root cause: ``stage_s6`` opens a wave with ``new_ready``, which is *every*
    ready unit, and hands the freeze ``--concurrency`` = ``min(ctx.max_parallel, 6)``.  The
    proposal's ``max_remote_inflight`` (vendor-acknowledged, not-yet-terminal tasks) has no
    representation anywhere in the tree, so it cannot bound the wave.
    """

    def test_ready_units_do_not_exceed_configured_remote_inflight_limit(self):
        deps = [(f"U{i}", None, False) for i in range(1, 6)]  # five independent ready units
        with tempfile.TemporaryDirectory() as tmp, _NoNetwork():
            # the only parallelism knob today is generation.max_parallel_tasks -> ctx.max_parallel,
            # which S6 passes to the submitter as --concurrency (POST threads).  max_remote_inflight
            # is the separately named limit the proposal asks for; both are set to 2 here.
            with _S6Harness(Path(tmp), deps, max_parallel=2, max_remote_inflight=2) as h:
                h.tick()
                peak = h.provider.peak_in_flight
                first_wave = h.provider.calls[0] if h.provider.calls else []
        self.assertLessEqual(
            peak, 2,
            f"REMOTE_INFLIGHT_UNBOUNDED: one S6 tick put {peak} units into remote generation "
            f"(wave={first_wave}) with max_parallel=2 / max_remote_inflight=2; new_ready is every "
            "ready unit, and --concurrency only bounds POST threads inside the submitter",
        )


class EngineSupervisorStreamingScheduler(unittest.TestCase):
    """Not a defect: the engine already has the scheduler the nalu S6 layer needs.

    ``tools/episode_parallel_batch_supervisor.py`` is the engine-side batch runner.  Its main
    loop reloads the submission scope every tick (``refresh_streaming_task_readiness``), submits
    every independent task plus one ready head per serial chain (``select_parallel_submission_wave``),
    and re-checks the episode credit gate before each submit.  It records
    ``streaming_readiness.batch_barrier = False``.  It is NOT in
    configs/PORTABLE_CORE_MANIFEST.json and the nalu line does not use it: S6 keeps its own
    rolling-wave scheduler in lines/nalu/runtime/tools/nalu_pipeline.py.  The two tests below
    document the behaviour that exists there, so the recommended fix is a port (reuse) rather
    than a new design.
    """

    def test_independent_tasks_and_one_head_per_chain_are_submitted_together(self):
        import tools.episode_parallel_batch_supervisor as supervisor

        def chained(key: str, chain: str, index: int) -> dict:
            return {"task_key": key, "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
                    "action_sequence_contract": {"chain_id": chain, "sequence_index": index}}

        selected, deferred = supervisor.select_parallel_submission_wave([
            chained("A1", "A", 1), chained("A2", "A", 2),
            chained("B1", "B", 1), chained("B2", "B", 2),
            {"task_key": "FREE", "generation_schedule_mode": "INDEPENDENT_PARALLEL"},
        ])
        self.assertEqual({task["task_key"] for task in selected}, {"A1", "B1", "FREE"})
        self.assertEqual([task["task_key"] for task in deferred], ["A2", "B2"])

    def test_readiness_streams_without_a_batch_barrier(self):
        import tools.episode_parallel_batch_supervisor as supervisor

        receipt = {"tasks": [{"task_key": "U01", "state": "waiting_dependencies"}]}
        config = {"qa_dir": "qa", "output_dir": "out", "tasks": [
            {"task_key": "U01", "status": "READY_TO_SUBMIT"},
            {"task_key": "U02", "status": "READY_TO_SUBMIT"},
        ]}
        supervisor.refresh_streaming_task_readiness(receipt, config)
        self.assertFalse(receipt["streaming_readiness"]["batch_barrier"])
        self.assertEqual([task["task_key"] for task in receipt["tasks"] if task["state"] == "pending"],
                         ["U01", "U02"])




if __name__ == "__main__":
    unittest.main()
