import unittest
from tools.basic_dialogue_qa_policy import evaluate_dialogue_findings

class BasicDialoguePolicyTests(unittest.TestCase):
    def test_minor_asr_or_near_sound_never_regenerates(self):
        for code in ('ASR_TEXT_MISMATCH','HOMOPHONE_DIFFERENCE','NEAR_SOUND_DIFFERENCE'):
            with self.subTest(code=code):
                r=evaluate_dialogue_findings([code])
                self.assertEqual(r['status'],'PASS_WITH_NOTE')
                self.assertFalse(r['regeneration_for_minor_difference_allowed'])
                self.assertFalse(r['repeat_asr_for_minor_difference_allowed'])
                self.assertFalse(r['voice_identity_verified'])
    def test_real_basic_failure_not_waived_by_minor_difference(self):
        for code in ('AUDIO_UNDECODABLE','DIALOGUE_INAUDIBLE','WRONG_SPEAKER','WHOLE_LINE_MISSING','DIALOGUE_CLIPPED'):
            with self.subTest(code=code):
                r=evaluate_dialogue_findings(['ASR_TEXT_MISMATCH',code])
                self.assertEqual(r['status'],'FAIL_BASIC_DIALOGUE')
                self.assertIn(code,r['failures'])
    def test_unknown_is_not_auto_accepted(self):
        self.assertEqual(evaluate_dialogue_findings(['UNKNOWN'])['status'],'REVIEW_UNCLASSIFIED_FINDINGS')
    def test_no_findings_not_whole_media_pass(self):
        self.assertEqual(evaluate_dialogue_findings([])['status'],'NO_DIALOGUE_FINDINGS')

if __name__=='__main__':unittest.main()
