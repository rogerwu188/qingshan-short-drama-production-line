import unittest

from tools.character_identity_admission_gate import evaluate


REGISTRY = {
    "characters": {
        "CHAR-A": {"status": "LOCKED_RETURNING"},
        "CHAR-NEW": {"status": "NEW"},
    }
}


def row(character_id="CHAR-A"):
    return {
        "character_id": character_id,
        "history_status": "RETURNING",
        "reroll_round": 1,
        "identity_qa_rerun": True,
        "sample_frame_paths": ["a.jpg", "b.jpg", "c.jpg"],
        "manual_identity_review_status": "PASS",
        "cross_source_consistency_status": "PASS",
        "identity_adjacent_styling_warning": False,
    }


class CharacterIdentityAdmissionGateTests(unittest.TestCase):
    def test_passes_complete_returning_character_evidence(self):
        manifest = {"sources": [{"source_id": "S1", "characters": [row()]}]}
        self.assertEqual(evaluate(manifest, REGISTRY)["status"], "PASS")

    def test_blocks_unregistered_or_unreviewed_character(self):
        bad = row("CHAR-MISSING")
        bad["identity_qa_rerun"] = False
        manifest = {"sources": [{"source_id": "S1", "characters": [bad]}]}
        report = evaluate(manifest, REGISTRY)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(item.startswith("character_not_registered") for item in report["failures"]))

    def test_new_character_requires_three_view_card_and_lock_fields(self):
        new = row("CHAR-NEW")
        new["history_status"] = "NEW"
        new["canonical_reference_paths"] = ["front.jpg"]
        manifest = {"sources": [{"source_id": "S1", "characters": [new]}]}
        report = evaluate(manifest, REGISTRY)
        self.assertIn("new_character_views_below_3:S1:CHAR-NEW", report["failures"])
        self.assertTrue(any(item.startswith("new_character_field_missing") for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
