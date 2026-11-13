import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.render_portable_timeline import build_ffmpeg_command, execute_render


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

    def test_every_picture_segment_is_forced_to_square_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            command = build_ffmpeg_command(self._project(Path(directory)))
        graph = command[command.index("-filter_complex") + 1]
        segments = [part for part in graph.split(";") if part.startswith("[") and ":v:0]" in part]
        self.assertEqual(len(segments), 2)
        for part in segments:
            self.assertIn(",setsar=1,fps=", part)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
    def test_renders_clips_whose_sample_aspect_ratios_differ(self):
        # fleet E08 S7: concat rejected 720x1280 segments with SAR 0:1 vs 5120:5117 (PICTURE_RENDER_FAILED)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = self._project(root)
            for name, size, sar, seconds in (("v1.mp4", "720x1280", "1/1", 4), ("v2.mp4", "716x1280", "5120/5117", 3)):
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                     f"testsrc=size={size}:rate=24:duration={seconds}", "-vf", f"setsar={sar}",
                     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(root / name)],
                    check=True)
            for name, seconds in (("a1.wav", 4), ("a2.wav", 3)):
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                     f"anullsrc=r=48000:cl=stereo:d={seconds}", str(root / name)], check=True)
            command = build_ffmpeg_command(project)
            command[1:1] = ["-loglevel", "error"]
            self.assertEqual(execute_render(command), 0)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height,sample_aspect_ratio", "-of", "json", str(root / "out" / "final.mp4")],
                check=True, capture_output=True, text=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual((stream["width"], stream["height"]), (720, 1280))
            self.assertEqual(stream["sample_aspect_ratio"], "1:1")

    def test_rejects_timeline_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "gap/overlap"):
                build_ffmpeg_command(self._project(Path(directory), second_start=4.5))


if __name__ == "__main__":
    unittest.main()
