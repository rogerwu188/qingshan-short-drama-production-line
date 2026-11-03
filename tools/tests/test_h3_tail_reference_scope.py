"""The previous unit's final frame carries place/light/state only under LOCKED_DIALOGUE_CAMERA_V1 (nalu E13 2026-11-01:
a speaker change inside one scene left the previous speakers in @Image2 with nothing saying they are not in this clip)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import h3_provider_prompt_renderer as h3  # noqa: E402


class TailReferenceScope(unittest.TestCase):
    def test_wording_is_gated_on_the_locked_dialogue_plan(self):
        source = (ROOT / "tools/h3_provider_prompt_renderer.py").read_text(encoding="utf-8")
        branch = source[source.index('elif role == "PREVIOUS_REAL_TAIL_STATE_AUTHORITY"'):]
        branch = branch[:branch.index("else:")]
        self.assertIn('_locked_dialogue_plan(plan.get("camera_plan") or {})', branch)
        self.assertIn("appears in this clip only if this clip", branch)
        self.assertTrue(h3._locked_dialogue_plan({"camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"}))
        self.assertFalse(h3._locked_dialogue_plan({}))


if __name__ == "__main__":
    unittest.main()
