"""An AUTHORED_WORLD contract (modern city) does not inherit the qingshan period forbidden set (…1037 E01)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "lines" / "nalu" / "runtime" / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import nalu_qa_common  # noqa: E402

SHOTS = {"E01-S02-03": {"prompt_spec": {"negative_prompts": ["watermark"]}}}


def terms(contract):
    return nalu_qa_common.Expectations.forbidden_terms(SimpleNamespace(contract=contract, shots=SHOTS))


class AuthoredWorldForbiddenTermsTest(unittest.TestCase):
    def test_modern_authored_world_allows_phone_and_car(self):
        out = terms({"visual_culture_contract": {"era_lock": "AUTHORED_WORLD",
                                                 "profile_id": "CONTEMPORARY_CHINESE_URBAN",
                                                 "forbidden_influences": ["fantasy armor"]}})
        self.assertNotIn("手机", out)
        self.assertNotIn("汽车", out)
        self.assertIn("fantasy armor", out)
        self.assertIn("watermark", out)

    def test_period_contract_keeps_engine_set(self):
        out = terms({"visual_culture_contract": {"era_lock": "EAST_ASIAN_PERIOD"}})
        self.assertIn("手机", out)
        self.assertIn("watermark", out)

    def test_undeclared_contract_keeps_engine_set(self):
        self.assertIn("手机", terms({}))


if __name__ == "__main__":
    unittest.main()
