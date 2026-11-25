"""E28 S3 (device …1101, 2026-11-25): a LOCKED library row whose artifact an engine restart moved into
~/nalu_archive/<EP>_abandoned_*/ is restored from the archive by exact sha (never regenerated, never overwritten)."""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))


class ArchiveRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.engine, self.runtime, self.archive = base / "engine", base / "runtime", base / "nalu_archive"
        for d in (self.engine, self.runtime, self.archive):
            d.mkdir()
        self.mod = importlib.import_module("studio_asset_resolve")
        np = self.mod._np
        patches = [mock.patch.object(np, "ENGINE_ROOT", self.engine), mock.patch.object(np, "RUNTIME_ROOT", self.runtime),
                   mock.patch.dict(os.environ, {"NALU_ARCHIVE_ROOT": str(self.archive)})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.rel = Path("workflow/nalu/E28/identity/plates/CHAR-AYE-plate-v1.png")
        self.recorded = self.engine / self.rel
        self.data = b"plate-bytes"
        self.sha = hashlib.sha256(self.data).hexdigest()

    def archived(self, name="E28_abandoned_20261125T123003Z_75d79da", data=None):
        path = self.archive / name / "engine" / self.rel
        path.parent.mkdir(parents=True)
        path.write_bytes(self.data if data is None else data)
        return path

    def test_moved_artifact_is_copied_back_by_sha(self):
        src = self.archived()
        self.assertEqual(self.mod.restore_from_archive(self.recorded, self.sha), self.recorded)
        self.assertEqual(self.recorded.read_bytes(), self.data)
        self.assertTrue(src.is_file())                       # the archive is never emptied

    def test_resolve_falls_back_to_the_archive(self):
        self.archived()
        with mock.patch.object(self.mod, "_studio") as studio:
            def real_old_path_only(path, sha, cache_dir=None):  # studio disabled: only a verifying old path
                c = Path(str(path))
                return c if c.is_file() and hashlib.sha256(c.read_bytes()).hexdigest() == sha else None
            studio.return_value.resolve_reference.side_effect = real_old_path_only
            studio.return_value.StudioError = RuntimeError
            self.assertEqual(self.mod.resolve(str(self.recorded), self.sha), self.recorded)
            self.assertTrue(self.mod.present({"path": str(self.recorded), "sha256": self.sha}))

    def test_wrong_bytes_or_occupied_path_are_never_used(self):
        self.archived(data=b"other")
        self.assertIsNone(self.mod.restore_from_archive(self.recorded, self.sha))
        self.recorded.parent.mkdir(parents=True)
        self.recorded.write_bytes(b"new episode bytes")
        self.archived(name="E28_abandoned_20261125T114503Z_72e7d47")
        self.assertIsNone(self.mod.restore_from_archive(self.recorded, self.sha))
        self.assertEqual(self.recorded.read_bytes(), b"new episode bytes")

    def test_paths_outside_the_roots_are_ignored(self):
        self.archived()
        self.assertIsNone(self.mod.restore_from_archive("/elsewhere/x.png", self.sha))


if __name__ == "__main__":
    unittest.main()
