"""A regenerated keyframe must replace the old one, not be ignored because the old one exists.

E11 (2026-10-09): a paid S5 redo harvested 50 new keyframes (550 credits), but the rename step
treated every existing ``keyframes/<shot>-keyframe-v1.png`` as ALREADY_PRESENT and skipped it.  The
new images stayed in ``keyframe_harvest/`` and Q1 re-issued a review of the two-day-old frames,
including the very defects the redo was paid to fix.  The old image is parked, never deleted.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

TOOLS = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"


def _pipeline():
    sys.path.insert(0, str(TOOLS))
    return importlib.import_module("nalu_pipeline")


class KeyframeRegenerationReplaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _pipeline()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.keyframes = root / "keyframes"
        self.harvest = root / "keyframe_harvest"
        self.keyframes.mkdir()
        self.harvest.mkdir()
        self.ctx = SimpleNamespace(
            episode="E99", run_id="RUN1",
            p=SimpleNamespace(keyframes=self.keyframes, keyframe_harvest_dir=self.harvest))
        self.dest = self.keyframes / "E99-S01-01-keyframe-v1.png"
        self.manifest = {"tasks": [{"task_key": "E99-S01-01-KEYFRAME-V1", "shot_id": "E99-S01-01",
                                    "output_contract": {"expected_output_path": str(self.dest)}}]}

    def harvested(self, data: bytes) -> Path:
        path = self.harvest / "E99_E99-S01-01-KEYFRAME-V1_task-123.png"
        path.write_bytes(data)
        return path

    def test_first_harvest_is_renamed(self) -> None:
        self.harvested(b"new")
        out = self.mod.apply_keyframe_renames(self.ctx, self.manifest)
        self.assertEqual(out["moved"][0]["action"], "RENAMED")
        self.assertEqual(self.dest.read_bytes(), b"new")

    def test_regeneration_replaces_and_parks_the_old_image(self) -> None:
        self.dest.write_bytes(b"old")
        self.harvested(b"new")
        out = self.mod.apply_keyframe_renames(self.ctx, self.manifest)
        row = out["moved"][0]
        self.assertEqual(row["action"], "REPLACED_PARKED_PREVIOUS")
        self.assertEqual(self.dest.read_bytes(), b"new")
        parked = Path(row["parked_previous"])
        self.assertEqual(parked.read_bytes(), b"old")
        self.assertEqual(parked.parent.name, "_superseded_RUN1")
        self.assertFalse(any(self.harvest.glob("*.png")))

    def test_identical_bytes_are_not_parked(self) -> None:
        self.dest.write_bytes(b"same")
        self.harvested(b"same")
        out = self.mod.apply_keyframe_renames(self.ctx, self.manifest)
        self.assertEqual(out["moved"][0]["action"], "ALREADY_PRESENT")
        self.assertFalse((self.keyframes / "_superseded_RUN1").exists())

    def test_nothing_harvested_keeps_the_existing_image(self) -> None:
        self.dest.write_bytes(b"old")
        out = self.mod.apply_keyframe_renames(self.ctx, self.manifest)
        self.assertEqual(out["moved"][0]["action"], "ALREADY_PRESENT")
        self.assertEqual(out["missing"], [])
        self.assertEqual(self.dest.read_bytes(), b"old")

    def test_nothing_anywhere_is_missing(self) -> None:
        out = self.mod.apply_keyframe_renames(self.ctx, self.manifest)
        self.assertEqual(out["missing"][0]["reason"], "NO_HARVESTED_FILE")


if __name__ == "__main__":
    unittest.main()
