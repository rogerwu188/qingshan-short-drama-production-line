"""S1 stops an over-long script while a rewrite is still free (line owner 2026-11-09, field device …1324 E03)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402


class ScriptLengthCheckTest(unittest.TestCase):
    def check(self, seconds: list[float], target: float | None, stamped: bool = True):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            contract = d / "contract.json"
            contract.write_text(json.dumps({"shots": [{"target_seconds": s} for s in seconds]}), encoding="utf-8")
            (d / "briefs").mkdir()
            if target is not None:
                (d / "briefs" / "E03_PRODUCTION_BRIEF.json").write_text(json.dumps({"target_seconds": target}))
            ctx = SimpleNamespace(episode="E03", p=SimpleNamespace(contract=contract))
            with mock.patch.object(npl, "RUNTIME", d), mock.patch.object(npl, "_camera_grammar_on", lambda _c: stamped):
                return npl.script_length_check(ctx)

    def test_over_long_script_blocks_with_rewrite_instruction(self):
        out = self.check([4.0] * 60, 110)  # 240 s
        self.assertEqual(out["status"], npl.BLOCKED)
        self.assertTrue(out["blocker"].startswith("SCRIPT_TOO_LONG:240.0s>143.0s"))

    def test_within_limit_passes_and_default_target(self):
        self.assertEqual(self.check([4.0] * 30, 110)["status"], npl.PASS)  # 120 s
        self.assertEqual(self.check([4.0] * 35, None)["limit_seconds"], 143.0)

    def test_unstamped_or_switched_off_is_not_checked(self):
        self.assertEqual(self.check([4.0] * 60, 110, stamped=False)["status"], "NOT_APPLICABLE")
        with mock.patch.dict("os.environ", {"NALU_SCRIPT_LENGTH_CHECK": "off"}):
            self.assertEqual(self.check([4.0] * 60, 110)["status"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
