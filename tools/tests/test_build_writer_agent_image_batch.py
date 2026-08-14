import json
import tempfile
import unittest
from pathlib import Path

from tools.build_writer_agent_image_batch import build


ROOT = Path(__file__).resolve().parents[2]


class WriterAgentImageBatchTest(unittest.TestCase):
    def test_e27_builds_all_agent_native_stills_with_provenance(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "workflow") as tmp:
            result = build(
                ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720/task2_compiled.json",
                ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720/generated.json",
                Path(tmp),
            )
            config = json.loads(Path(result["config"]).read_text(encoding="utf-8"))
            self.assertEqual(24, result["shots"])
            self.assertEqual(24, config["concurrency"])
            self.assertEqual("PASS", config["writer_agent_provenance"]["status"])
            self.assertTrue(all((ROOT / task["prompt_file"]).is_file() for task in config["tasks"]))
            self.assertIn("clear daytime", Path(tmp, "prompts", "E27-N01.txt").read_text(encoding="utf-8"))
            self.assertIn("female", Path(tmp, "prompts", "E27-N05.txt").read_text(encoding="utf-8"))
            manifest = Path(result["prompt_manifest"]).read_text(encoding="utf-8")
            self.assertEqual(24, manifest.count("## E27-N"))


if __name__ == "__main__":
    unittest.main()
