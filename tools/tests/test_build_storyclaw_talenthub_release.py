import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/build_storyclaw_talenthub_release.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_release", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class StoryClawTalentHubReleaseTest(unittest.TestCase):
    def test_workspace_contains_pinned_skill_and_public_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = MODULE.write_talenthub_workspace(
                Path(tmp), "v-test", "a" * 40, "b" * 64
            )
            manifest = json.loads((workspace / "manifest.json").read_text())
            release = json.loads((workspace / "RELEASE_MANIFEST.json").read_text())
            self.assertEqual(manifest["id"], "ai-drama-factory")
            self.assertEqual(manifest["skills"], [
                "https://github.com/rogerwu188/qingshan-short-drama-production-line@qingshan-nalu"
            ])
            self.assertEqual(release["source_archive_sha256"], "b" * 64)
            self.assertIn("S1", (workspace / "skills/qingshan-nalu/SKILL.md").read_text())
            self.assertIn("新剧项目的交互顺序", (workspace / "USER.md").read_text())


if __name__ == "__main__":
    unittest.main()
