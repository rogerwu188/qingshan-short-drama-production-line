import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.compile_script_locked_still_batch import validate


class CompileScriptLockedStillBatchTest(unittest.TestCase):
    def test_accepts_short_editorial_cut(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "script.md"
            script.write_text("locked script", encoding="utf-8")
            manifest = {
                "source": {
                    "script": str(script),
                    "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                },
                "scene_count": 1,
                "shot_count": 2,
                "runtime_seconds": 6,
                "shots": [
                    {"shot_id": "SH01", "scene_id": "SC01", "duration_seconds": 2},
                    {"shot_id": "SH02", "scene_id": "SC01", "duration_seconds": 4},
                ],
            }
            scenes = {"scene_state": [{"scene_id": "SC01"}]}

            source, scene_by_id = validate(manifest, scenes)

            self.assertEqual(source, script)
            self.assertEqual(set(scene_by_id), {"SC01"})

    def test_rejects_zero_length_editorial_cut(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "script.md"
            script.write_text("locked script", encoding="utf-8")
            manifest = {
                "source": {
                    "script": str(script),
                    "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                },
                "scene_count": 1,
                "shot_count": 1,
                "runtime_seconds": 0,
                "shots": [
                    {"shot_id": "SH01", "scene_id": "SC01", "duration_seconds": 0},
                ],
            }
            scenes = {"scene_state": [{"scene_id": "SC01"}]}

            with self.assertRaisesRegex(ValueError, "outside 1-15 seconds"):
                validate(manifest, scenes)


if __name__ == "__main__":
    unittest.main()
