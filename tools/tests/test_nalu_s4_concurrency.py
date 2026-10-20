"""S4 voices: every speaking character's reference is generated concurrently.

The S4 loop used to generate, normalize and upload one character at a time, each
waiting for the speech provider to poll its task to completion (2 s interval, up
to 300 s).  N characters therefore cost N sequential waits on independent work.

What must stay true: results are applied in the input order, a failing character
blocks the stage instead of being skipped silently, and each task reserves only
its own 2 credits (the old serial guard charged `2 x remaining`, which assumed
later characters were not yet guarded).
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import nalu_pipeline  # noqa: E402  (runtime tools dir added above)


class _FakePaths:
    def __init__(self, root: Path):
        self.scope = {"scope_id": "E99"}
        self.voice_upload_dir = root / "uploads"
        self.voice_upload_dir.mkdir(parents=True, exist_ok=True)


class _FakeCtx:
    def __init__(self, root: Path, *, workers: int = 4, behaviour: dict | None = None):
        self.episode = "E99"
        self.max_parallel = workers
        self.say = lambda *_a, **_k: None
        self.planned_commands: list[dict] = []
        self.reserved: list[int] = []
        self.behaviour = behaviour or {}
        self.target_wav: dict[str, Path] = {}

    def paid_step(self, argv, *, name, sid, planned_credits, note=""):
        self.reserved.append(planned_credits)
        entity = name.rsplit("_", 1)[-1]
        action = self.behaviour.get(entity, "pass")
        mp3 = Path(argv[argv.index("--output-dir") + 1]) / argv[argv.index("--file-name") + 1]
        if action == "error":
            raise AssertionError(f"{entity} provider exploded")
        if action == "hard_stop":
            return nalu_pipeline.HARD_STOP, {"name": name, "status": nalu_pipeline.HARD_STOP}
        mp3.parent.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(b"mp3")
        return nalu_pipeline.PASS, {"name": name, "status": nalu_pipeline.PASS, "exit_code": 0}

    def run(self, argv, *, name, paid=False, **_kwargs):
        argv = [str(item) for item in argv]
        if name.startswith("s4_normalize_"):
            # the real command's last argument is the normalization target wav
            wav = Path(argv[-1])
            wav.parent.mkdir(parents=True, exist_ok=True)
            wav.write_bytes(b"wav")
        elif name.startswith("s4_upload_"):
            out = Path(argv[argv.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"asset_id": "asset-1", "duration": 3.0}), encoding="utf-8")
        return {"name": name, "exit_code": 0}


def _task(root: Path, entity: str) -> dict:
    return {
        "entity_id": entity,
        "character": entity,
        "request": {
            "text": "台词",
            "voice_id": "v1",
            "voice_name": "voice",
            "emotion": "calm",
            "speed": "1.0",
            "output_mp3": str(root / "mp3" / f"{entity}.mp3"),
        },
        "post_generation_normalization": {
            "target_wav": str(root / "wav" / f"{entity}.wav"),
            "command": ["ffmpeg", str(root / "mp3" / f"{entity}.mp3"),
                        str(root / "wav" / f"{entity}.wav")],
        },
    }


class S4ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.p = _FakePaths(self.root)

    def test_characters_are_generated_concurrently(self):
        barrier = threading.Barrier(3, timeout=4.0)
        ctx = _FakeCtx(self.root, workers=3)
        original = ctx.paid_step

        def synced(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait()  # a serial loop deadlocks here and fails the test
            return result

        ctx.paid_step = synced
        todo = [_task(self.root, entity) for entity in ("CH-A", "CH-B", "CH-C")]
        outcomes = nalu_pipeline.s4_generate_all(ctx, self.p, todo)
        self.assertEqual([row["status"] for row in outcomes], ["PASS"] * 3)

    def test_outcomes_keep_the_todo_order(self):
        ctx = _FakeCtx(self.root, workers=3)
        todo = [_task(self.root, entity) for entity in ("CH-A", "CH-B", "CH-C")]
        outcomes = nalu_pipeline.s4_generate_all(ctx, self.p, todo)
        self.assertEqual([row["entity"] for row in outcomes], ["CH-A", "CH-B", "CH-C"])

    def test_each_task_reserves_only_its_own_two_credits(self):
        ctx = _FakeCtx(self.root, workers=3)
        todo = [_task(self.root, entity) for entity in ("CH-A", "CH-B", "CH-C")]
        nalu_pipeline.s4_generate_all(ctx, self.p, todo)
        self.assertEqual(ctx.reserved, [2, 2, 2],
                         "a concurrent run must not charge 2 x remaining per task")

    def test_a_hard_stop_is_reported_not_swallowed(self):
        ctx = _FakeCtx(self.root, workers=2, behaviour={"CH-B": "hard_stop"})
        todo = [_task(self.root, entity) for entity in ("CH-A", "CH-B")]
        outcomes = nalu_pipeline.s4_generate_all(ctx, self.p, todo)
        self.assertEqual(outcomes[1]["status"], nalu_pipeline.HARD_STOP)
        self.assertIn("BUDGET_HARD_STOP_S4:CH-B", outcomes[1]["blockers"])

    def test_workers_one_keeps_the_serial_path(self):
        ctx = _FakeCtx(self.root, workers=1)
        todo = [_task(self.root, entity) for entity in ("CH-A", "CH-B")]
        outcomes = nalu_pipeline.s4_generate_all(ctx, self.p, todo)
        self.assertEqual([row["entity"] for row in outcomes], ["CH-A", "CH-B"])


if __name__ == "__main__":
    unittest.main()
