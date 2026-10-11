#!/usr/bin/env python3
"""Internal space IDs must never reach the provider, including right after a CJK character.

Python's \\b treats CJK as word characters, so the old \\bLOC- / \\bSUBSPACE- patterns silently
missed every id written straight after Chinese text, and ZONE- ids were not handled at all
(E11-VU-021: 「刘老头与ZONE-STREET-SOUTH-APPROACH的接触」 went to the provider verbatim).
"""
from __future__ import annotations

import unittest

from tools.sd2_provider_prompt_renderer import _sanitize_provider_ids as S


class ProviderIdSanitizerTest(unittest.TestCase):
    def test_ids_after_cjk_are_translated(self):
        out = S("人物在LOC-XU-HOUSE-INT内，刘老头与ZONE-STREET-SOUTH-APPROACH的接触；同一SUBSPACE-E11-S19-00")
        for raw in ("LOC-", "ZONE-", "SUBSPACE-"):
            self.assertNotIn(raw, out)
        self.assertIn("已锁定的同一区域", out)

    def test_ids_after_ascii_space_and_at_start(self):
        out = S("GLOBAL-SPACE-A then LOC-B and SUB-C")
        self.assertEqual(out, "已锁定的同一全局空间 then 已锁定的同一地点 and 已锁定的同一子空间")

    def test_id_embedded_in_another_token_is_left_alone(self):
        self.assertEqual(S("PRELOC-X"), "PRELOC-X")

    def test_plain_text_unchanged(self):
        self.assertEqual(S("秦铭坐着，握了握拳"), "秦铭坐着，握了握拳")


if __name__ == "__main__":
    unittest.main()
