"""A derived prompt kept from an earlier incomplete authoring run (still carrying an AUTHORING_REQUIRED_*
sentinel) is rewritten once the fresh body is sentinel-free; genuine operator edits are still kept
(fleet device 0841 E08, 2026-11-12: S2 PASS kept the CHAR-012 sentinel prompt and S3 paid for it)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_episode_asset_requirements as bear  # noqa: E402


class StaleAuthoringSentinelPromptTests(unittest.TestCase):

    def _prompt(self, tmp: str, text: str) -> Path:
        path = Path(tmp, "E08-CHAR-012.txt")
        path.write_text(text, encoding="utf-8")
        return path

    def test_sentinel_prompt_is_rewritten_when_fresh_body_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._prompt(tmp, "age AUTHORING_REQUIRED_APPARENT_AGE_RANGE, robe")
            self.assertFalse(bear.keep_existing_prompt(path, "age 31-35, dark-green robe", False))

    def test_operator_edit_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._prompt(tmp, "age 31-35 【双树颜色·硬性】")
            self.assertTrue(bear.keep_existing_prompt(path, "age 31-35", False))

    def test_sentinel_kept_while_inputs_still_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._prompt(tmp, "AUTHORING_REQUIRED_SEX edited")
            self.assertTrue(bear.keep_existing_prompt(path, "AUTHORING_REQUIRED_SEX", False))

    def test_missing_or_forced_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(bear.keep_existing_prompt(Path(tmp, "none.txt"), "x", False))
            path = self._prompt(tmp, "operator edit")
            self.assertFalse(bear.keep_existing_prompt(path, "x", True))


if __name__ == "__main__":
    unittest.main()
