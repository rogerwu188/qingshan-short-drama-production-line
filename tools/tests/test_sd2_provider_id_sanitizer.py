#!/usr/bin/env python3
"""Internal space IDs must never reach the provider, including right after a CJK character.

Python's \\b treats CJK as word characters, so the old \\bLOC- / \\bSUBSPACE- patterns silently
missed every id written straight after Chinese text, and ZONE- ids were not handled at all
(E11-VU-021: 「刘老头与ZONE-STREET-SOUTH-APPROACH的接触」 went to the provider verbatim).
"""
from __future__ import annotations

import unittest

from tools.sd2_provider_prompt_renderer import _role_line, _sanitize_provider_ids as S


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



class BeatEvidenceSanitiserTest(unittest.TestCase):
    """The coverage receipt is measured against the rendered text, and the rendered text has the
    internal ids translated away.  Evidence that kept its raw id could never match, so an id in a
    beat's contact point failed the unit as PROVIDER_SEMANTIC_FACT_UNCOVERED instead of passing
    (E11-VU-002 BEAT.1/2 CONTACT_POINT + PRIMARY_FEEDBACK after the ZONE- id became translatable)."""

    def test_beat_evidence_is_sanitised_like_the_prompt(self):
        import inspect

        from tools import sd2_provider_prompt_renderer as R

        source = inspect.getsource(R.render_sd2_prompt)
        self.assertIn('clause_evidence[f"{prefix}.CONTACT_POINT"] = _sanitize_provider_ids(', source)
        self.assertIn('clause_evidence[f"{prefix}.PRIMARY_FEEDBACK"] = _sanitize_provider_ids(', source)

    def test_contact_point_after_sanitising_matches_the_prompt(self):
        beat = {"contact_point": "秦铭与ZONE-XU-HOUSE-INT-2的接触/反应落点：INTEGRITY：手背松弛→手背绷起"}
        prompt = S("秦铭与ZONE-XU-HOUSE-INT-2的接触/反应落点：INTEGRITY：手背松弛→手背绷起")
        self.assertIn(S(beat["contact_point"]), prompt)


class RoleLineNamesTest(unittest.TestCase):
    def row(self, names):
        return {"shot_id": "E11-S06-04", "primary_actor": "许岳平", "dialogue_speaker": "许岳平",
                "dialogue_listener": "秦铭", "entity_names": names,
                "entity_states": {"CHAR-XUYUEPING": "许岳平坐下", "CHAR-QINMING": "听者保持承接状态"}}

    def test_unnamed_listener_state_uses_the_listener_name_not_the_id(self):
        line = _role_line(self.row({"CHAR-XUYUEPING": "许岳平"}))
        self.assertNotIn("CHAR-", line)
        self.assertIn("秦铭的独立状态：听者保持承接状态", line)

    def test_named_entities_are_unchanged(self):
        line = _role_line(self.row({"CHAR-XUYUEPING": "许岳平", "CHAR-QINMING": "秦铭"}))
        self.assertIn("秦铭的独立状态", line)
        self.assertNotIn("CHAR-", line)

    def test_unknown_entity_without_listener_never_prints_its_id(self):
        row = self.row({"CHAR-XUYUEPING": "许岳平", "CHAR-QINMING": "秦铭"})
        row["entity_states"]["CHAR-STRANGER"] = "站着"
        self.assertNotIn("CHAR-STRANGER", _role_line(row))


if __name__ == "__main__":
    unittest.main()
