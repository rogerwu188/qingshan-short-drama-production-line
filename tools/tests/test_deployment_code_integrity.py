import tempfile
import unittest
from pathlib import Path
from tools.deployment_code_integrity import SCHEMA, digest, verify
from tools.level_native_release_audio import level_release
from tools.manifest_self_limit_and_version_assert import check_self_limits


class DeploymentIntegrityTests(unittest.TestCase):
    def test_verify_missing_changed_and_unlisted_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            source = root / "tools/example.py"
            source.write_text("pass\n")
            manifest = {"schema": SCHEMA, "file_count": 1,
                        "files": [{"path": "tools/example.py", "sha256": digest(source)}]}
            (root / "private.json").write_text("{}")
            self.assertEqual(verify(root, manifest)["status"], "PASS")
            source.write_text("changed")
            self.assertEqual(verify(root, manifest)["changed"], ["tools/example.py"])
            source.unlink()
            self.assertEqual(verify(root, manifest)["missing"], ["tools/example.py"])

    def test_reject_empty_traversal_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            for rows in ([], [{"path": "../secret", "sha256": "0" * 64}],
                         [{"path": "tools/a.py", "sha256": "0" * 64}] * 2):
                with self.assertRaises(ValueError):
                    verify(Path(directory), {"schema": SCHEMA, "file_count": len(rows), "files": rows})

    def test_nonfinite_self_limit_cannot_pass(self):
        self.assertEqual(check_self_limits({"self_limit_information_gap": float("nan")})
                         ["blocks"][0]["verdict"], "BLOCK_NONFINITE_SELF_LIMIT")

    def test_audio_leveler_preserves_existing_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "approved.mp4"
            output.write_bytes(b"approved")
            with self.assertRaises(FileExistsError):
                level_release(source=root / "source.mp4", timeline_path=root / "timeline.json",
                              grouped_path=root / "grouped.json", output=output,
                              qa_path=root / "qa.json", episode="E1", version="v1")
            self.assertEqual(output.read_bytes(), b"approved")
