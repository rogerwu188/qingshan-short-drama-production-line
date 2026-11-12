"""Final cut fills the 9:16 frame instead of letterboxing near-9:16 clips (line owner 2026-11-12).

MiniMax-H3 768p clips are 768x1344; fit+pad into 720x1280 left a 10 px black band top and bottom of every
published episode.  Clips within FILL_CROP_ASPECT_TOLERANCE of 9:16 are now scaled to fill and centre-cropped;
anything further off (landscape cards) keeps fit+pad."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import render_portable_timeline as rpt  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class FillCropTest(unittest.TestCase):
    def _clip(self, root: Path, name: str, size: str) -> Path:
        out = root / name
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:s={size}:d=1:r=24",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", "-shortest",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
        return out

    def _graph(self, root: Path, sources: list[Path]) -> str:
        clips_v, clips_a, start = [], [], 0.0
        for src in sources:
            clips_v.append({"source": str(src), "start": start, "duration": 1.0, "in": 0})
            clips_a.append({"source": str(src), "start": start, "duration": 1.0, "in": 0, "volume": 1.0})
            start += 1.0
        project = {"metadata": {}, "output": {"path": str(root / "out.mp4")},
                   "timeline": {"videoTracks": [{"clips": clips_v}], "audioTracks": [{"clips": clips_a}]}}
        path = root / "p.json"
        path.write_text(json.dumps(project), encoding="utf-8")
        command = rpt.build_ffmpeg_command(path)
        return command[command.index("-filter_complex") + 1]

    def test_h3_768p_and_480p_fill_and_landscape_keeps_pad(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            h3_768 = self._clip(root, "h3_768.mp4", "768x1344")
            h3_480 = self._clip(root, "h3_480.mp4", "480x854")
            card = self._clip(root, "card.mp4", "1280x720")
            graph = self._graph(root, [h3_768, h3_480, card]).split(";")
            self.assertIn("force_original_aspect_ratio=increase,crop=720:1280", graph[0])
            self.assertNotIn("pad=", graph[0])
            fills = [g for g in graph if "crop=720:1280" in g]
            pads = [g for g in graph if "pad=720:1280" in g]
            self.assertEqual(len(fills), 2, "both near-9:16 H3 clips fill the frame")
            self.assertEqual(len(pads), 1, "the landscape card keeps fit+pad")

    def test_rendered_768p_clip_has_no_black_band(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = self._clip(root, "h3_768.mp4", "768x1344")
            graph_path = root / "p.json"
            self._graph(root, [src])
            command = rpt.build_ffmpeg_command(graph_path)
            subprocess.run(command, check=True)
            out = root / "out.mp4"
            row = subprocess.run([FFMPEG, "-v", "error", "-i", str(out), "-vf", "crop=720:4:0:0,format=gray",
                                  "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
            self.assertGreater(sum(row) / len(row), 40, "top rows are picture, not a black band")


if __name__ == "__main__":
    unittest.main()
