"""Offline regression: story tail cannot stand in for a required brand card."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class BrandOutroTimelineTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/nalu_pipeline.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "_write_release_timeline")
        self.output = {}
        env = {
            "Path": Path,
            "read_json": lambda *args: {"timeline": {"videoTracks": [{"clips": [
                {"id": "last", "start": 0, "duration": 10, "metadata": {"source_id": "last"}}
            ]}]}},
            "write_json": lambda path, value: self.output.update(value),
            "subprocess": SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout="13.0", returncode=0)),
            "_media": SimpleNamespace(require_ffprobe=lambda: "ffprobe"),
            "now": lambda: "test",
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), env)
        self.run_timeline = env["_write_release_timeline"]

    def call(self, seconds):
        return self.run_timeline(SimpleNamespace(episode="TEST"),
                                 SimpleNamespace(agentcut_project=Path("project.json")),
                                 Path("picture.mp4"), seconds, Path("timeline.json"))

    def test_missing_outro_blocks_before_any_report(self):
        with self.assertRaisesRegex(ValueError, "REQUIRED_BRAND_OUTRO_MISSING"):
            self.call(0)
        self.assertEqual(self.output, {})

    def test_fake_half_second_outro_is_rejected(self):
        with self.assertRaises(ValueError):
            self.call(0.5)

    def test_full_story_duration_is_preserved(self):
        self.call(3)
        self.assertEqual(self.output["content_runtime_seconds"], 10)
        self.assertEqual(self.output["segments"][-1]["output_end"], 10)
        self.assertEqual(self.output["release_runtime_seconds"], 13)


if __name__ == "__main__":
    unittest.main()
