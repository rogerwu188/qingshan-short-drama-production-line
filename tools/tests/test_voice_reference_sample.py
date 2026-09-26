import unittest
from tools.voice_reference_sample import apply_reference_sample


class ReferenceSampleTests(unittest.TestCase):
    def sample(self):
        return {'reference_sample':{'text':'这是一段音色参考，请听我自然地说话，声音清楚，语句连贯。',
            'purpose':'VOICE_REFERENCE_ONLY','author':'fixture','source_ref':'fixture#sample','speed':1.2}}

    def test_reference_does_not_mutate_dialogue_or_input(self):
        brief={'all_lines':['原句。'],'sample_text':'原句。','risk_flags':['ESTIMATED_DURATION_BELOW_SD2_2S_FLOOR']}
        out=apply_reference_sample(brief,self.sample())
        self.assertEqual(out['all_lines'],['原句。'])
        self.assertEqual(brief['sample_text'],'原句。')
        self.assertFalse(out['sample_text_is_verbatim_script'])
        self.assertGreaterEqual(out['estimated_duration_seconds'],3)
        self.assertEqual(out['risk_flags'],[])

    def test_legacy_unchanged(self):
        b={'sample_text':'a'};self.assertIs(apply_reference_sample(b,{}),b)

    def test_missing_purpose_and_short_sample_rejected(self):
        s=self.sample();del s['reference_sample']['purpose']
        with self.assertRaises(ValueError):apply_reference_sample({},s)
        s=self.sample();s['reference_sample']['text']='短。'
        with self.assertRaises(ValueError):apply_reference_sample({},s)
