import json
import tempfile
import unittest
from pathlib import Path

from tools.render_portable_timeline import build_ffmpeg_command


class PortableTimelineRendererTests(unittest.TestCase):
    def _project(self, root: Path, *, second_start: float = 4.0) -> Path:
        for name in ("v1.mp4", "a1.wav", "v2.mp4", "a2.wav"):
            (root / name).write_bytes(b"fixture")
        payload = {
            "output": {"path": "out/final.mp4", "width": 720, "height": 1280, "fps": 24},
            "timeline": {
                "videoTracks": [{"clips": [
                    {"source": "v1.mp4", "start": 0, "in": 0, "duration": 4},
                    {"source": "v2.mp4", "start": second_start, "in": 0, "duration": 3},
                ]}],
                "audioTracks": [{"clips": [
                    {"source": "a1.wav", "start": 0, "in": 0, "duration": 4, "volume": 0.8},
                    {"source": "a2.wav", "start": second_start, "in": 0, "duration": 3, "volume": 1},
                ]}],
            },
        }
        path = root / "project.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_builds_stock_ffmpeg_concat_command(self):
        with tempfile.TemporaryDirectory() as directory:
            command = build_ffmpeg_command(self._project(Path(directory)))
        joined = " ".join(command)
        self.assertIn("concat=n=2:v=1:a=1", joined)
        self.assertIn("scale=720:1280", joined)
        self.assertIn("-movflags +faststart", joined)

    def test_rejects_timeline_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "gap/overlap"):
                build_ffmpeg_command(self._project(Path(directory), second_start=4.5))


if __name__ == "__main__":
    unittest.main()
