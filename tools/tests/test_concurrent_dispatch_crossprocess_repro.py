#!/usr/bin/env python3
"""Mock-only check: two independent submitter PROCESSES racing one unit --> exactly one POST.

Proposal §6.2 / §8 item 7 ("cross-process duplicate POST").  The submitter's idempotency is a
durable transaction file plus a per-task ``flock`` (``tools/submit_giggle_video_manifest_v2.py``,
``submit_one`` at ~990).  Inside that lock the whole read-transaction -> write-intent -> POST ->
bind sequence runs.

CONCLUSION OF THE AUDIT: this property HOLDS.  The transaction filename contains the
submission fingerprint, so a second process that has not yet written its own intent cannot see
a file at the path it is about to write -- but the competing processes reach the same path
(identical fingerprint) and a blocking ``flock`` serialises them, after which the loser reads
``SUBMITTED_TASK_ID_BOUND`` via ``prior_bound()`` and returns without a POST.  This test PASSES
on HEAD; it is kept as the guard for §8 item 7 rather than as a reproduction, and it is
deliberately NOT in configs/PORTABLE_CORE_MANIFEST.json (it forks real processes and is slower
than the core contract allows).

Both processes are real children running the real ``submit_one``.  Nothing external happens:
``_request`` is replaced by a fake that counts POSTs, the whole-batch prompt gate is
auto-passed, and any socket connection raises.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

WORKER_SOURCE = textwrap.dedent(
    '''
    """Child process: call the real submit_one once, with every network path faked."""
    import json, os, sys, time, socket, fcntl
    from pathlib import Path

    PROBE = Path(os.environ["RACE_PROBE_DIR"])
    REPO = Path(os.environ["RACE_REPO"])
    ROLE = os.environ.get("RACE_ROLE", "a")
    START = float(os.environ.get("RACE_START", "0") or "0")
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tools"))

    os.environ["GIGGLE_API_KEY"] = "MOCK-KEY-NO-NETWORK"
    os.environ.pop("NALU_RUNTIME_ROOT", None)

    def refuse(*_a, **_k):
        raise AssertionError("network access attempted in a mock-only probe")

    socket.socket.connect = refuse          # type: ignore[assignment]
    socket.socket.connect_ex = refuse       # type: ignore[assignment]
    socket.create_connection = refuse       # type: ignore[assignment]

    import tools.submit_giggle_video_manifest_v2 as submitter
    import tools.episode_prompt_batch_gate as batch_gate

    STATE = PROBE / "probe_state.json"


    def emit(kind):
        """One append-only write under flock: lines land atomically and in order."""
        line = f"{kind} {ROLE} {time.time() - START:.6f}\\n"
        with open(STATE, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


    def fake_request(path, payload, method=None):
        emit("REACHED")
        time.sleep(float(os.environ.get("RACE_REQUEST_SECONDS", "0.15")))
        emit("POST")
        time.sleep(float(os.environ.get("RACE_REQUEST_SECONDS", "0.15")))
        emit("POST_DONE")
        return {"data": {"task_id": f"mock-tid-{ROLE}-{os.getpid()}"}}


    def wait_for(name, timeout=15.0):
        target = PROBE / name
        deadline = time.time() + timeout
        while time.time() < deadline:
            if target.exists():
                return True
            time.sleep(0.005)
        return False


    def main():
        task = json.loads((PROBE / "task.json").read_text(encoding="utf-8"))
        receipt_dir = Path(os.environ["RACE_RECEIPT_DIR"])
        transaction_dir = Path(os.environ["RACE_TRANSACTION_DIR"])
        if not wait_for("barrier"):
            return 5
        from unittest import mock
        with mock.patch.object(batch_gate, "require_generation_batch",
                               lambda *a, **k: {"status": "NOT_REQUIRED"}), \\
                mock.patch.object(submitter, "prompt_scope_gate_active", lambda _t: False), \\
                mock.patch.object(submitter, "_request", fake_request):
            try:
                result = submitter.submit_one(task, receipt_dir, transaction_dir)
            except Exception as exc:  # noqa: BLE001
                emit("ERROR:%s:%s" % (type(exc).__name__, exc))
                return 2
        emit("RESULT:%s:recovered=%s" % (result.get("state"), bool(result.get("recovered_from_transaction"))))
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
)


class SubmitterCrossProcessDuplicatePostRepro(unittest.TestCase):
    """One unit, two concurrent processes, exactly one POST."""

    ATTEMPTS = 3

    def _prepare(self, tmp: Path) -> dict:
        probe = tmp / "probe"
        for name in ("transactions", "receipts"):
            (probe / name).mkdir(parents=True, exist_ok=True)
        task = {
            "task_key": "E99-VU-001", "unit_id": "E99-VU-001", "episode": "E99",
            "model": "Mock-Model-1", "duration_seconds": 5, "aspect_ratio": "9:16",
            "resolution": "720p", "prompt_file": str(probe / "prompt.txt"),
            # sha256(b"mock prompt") - submit_one re-verifies the prompt bytes it POSTs
            "prompt_sha256": "408fc14a6958ef21f3d7fb750443dbfa44628cf545afdf3f98bde55046405f84",
            "reference_images": [str(probe / "ref.png")],
            # sha256(b"mock-reference"), the bytes written below
            "reference_sha256": ["6a278161eb0cf3c35d6377ef2fad2370db6a687cec7f1ae10f6cacc727c530ca"],
        }
        (probe / "task.json").write_text(json.dumps(task), encoding="utf-8")
        (probe / "prompt.txt").write_text("mock prompt", encoding="utf-8")
        (probe / "ref.png").write_bytes(b"mock-reference")
        worker = tmp / "race_worker.py"
        worker.write_text(WORKER_SOURCE, encoding="utf-8")
        env = dict(os.environ)
        env.update({
            "RACE_PROBE_DIR": str(probe), "RACE_REPO": str(REPO),
            "RACE_TRANSACTION_DIR": str(probe / "transactions"),
            "RACE_RECEIPT_DIR": str(probe / "receipts"),
        })
        env.pop("NALU_RUNTIME_ROOT", None)
        return {"probe": probe, "worker": worker, "env": env}

    def _spawn(self, harness: dict, role: str, start: float, **extra):
        env = dict(harness["env"])
        env["RACE_ROLE"] = role
        env["RACE_START"] = f"{start:.6f}"
        env.update(extra)
        return subprocess.Popen([sys.executable, str(harness["worker"])], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def _events(self, probe: Path) -> list[tuple[str, str, float]]:
        path = probe / "probe_state.json"
        rows = []
        for line in (path.read_text(encoding="utf-8").splitlines() if path.is_file() else []):
            if not line.strip():
                continue
            kind, role, stamp = line.split(" ", 2)
            rows.append((kind, role, float(stamp)))
        return rows

    @staticmethod
    def _posts(events) -> list[tuple[str, str, float]]:
        return [row for row in events if row[0] == "POST"]

    def test_two_concurrent_processes_post_the_same_unit_only_once(self):
        counts: list[int] = []
        with tempfile.TemporaryDirectory() as tmp:
            harness = self._prepare(Path(tmp))
            probe = harness["probe"]
            start = time.time()
            for attempt in range(self.ATTEMPTS):
                (probe / "probe_state.json").unlink(missing_ok=True)
                (probe / "barrier").unlink(missing_ok=True)
                for name in ("transactions", "receipts"):
                    for stale in (probe / name).iterdir():
                        stale.unlink()
                workers = [self._spawn(harness, role, start, RACE_JITTER=str(0.003 * attempt))
                           for role in ("a", "b")]
                time.sleep(0.4)          # both children have imported and are waiting on the barrier
                (probe / "barrier").touch()
                codes = [self._finish(process) for process in workers]
                for code, out, err in codes:
                    self.assertEqual(code, 0, f"worker exited {code}\nstdout={out}\nstderr={err}")
                counts.append(len(self._posts(self._events(probe))))
                self.assertEqual(len(list((probe / "transactions").glob("*.json"))), 1,
                                 "one unit must own exactly one transaction file")
        self.assertEqual(
            counts, [1] * self.ATTEMPTS,
            "CROSS_PROCESS_DUPLICATE_POST: two concurrent submitter processes POSTed the same "
            f"unit (POSTs per attempt: {counts}) although the first attempt had already written "
            "SUBMITTED_TASK_ID_BOUND; the per-task flock serialises them, but submit_one re-reads "
            "the transaction only while still holding the lock it already had",
        )

    def _finish(self, process: subprocess.Popen) -> tuple[int, str, str]:
        out, err = process.communicate(timeout=90)
        return process.returncode, out, err


if __name__ == "__main__":
    unittest.main()
