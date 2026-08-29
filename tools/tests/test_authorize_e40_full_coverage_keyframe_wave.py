import unittest

from tools.authorize_e40_full_coverage_keyframe_wave import belongs_to_original_unit


class OriginalUnitAttemptOwnershipTest(unittest.TestCase):
    def test_original_r01_attempts_belong_to_original_lineage(self):
        self.assertTrue(belongs_to_original_unit("E40-REMAKE-R01-COMPOSITE-V1", "R01"))
        self.assertTrue(belongs_to_original_unit("E40-REMAKE-R01-KEYFRAME-QA-V2", "R01"))

    def test_switch_coverage_children_do_not_inflate_original_attempt_count(self):
        self.assertFalse(belongs_to_original_unit("E40-SWITCH-R01-COV-CURTAIN-FAN-KEYFRAME-QA-V2", "R01"))
        self.assertFalse(belongs_to_original_unit("E40-R01-COVERAGE-REACTION", "R01"))

    def test_other_unit_does_not_match(self):
        self.assertFalse(belongs_to_original_unit("E40-REMAKE-R06A-COMPOSITE-V2", "R01"))


if __name__ == "__main__":
    unittest.main()
