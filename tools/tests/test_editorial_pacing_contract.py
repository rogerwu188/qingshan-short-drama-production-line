import copy
import unittest
from tools.editorial_pacing_contract import delivery_clause, continuous_bridge, edit_interval, map_interval, editorial_duration, content_window_clause
from tools.sd2_provider_prompt_renderer import _dialogue
from tools.h3_provider_prompt_renderer import _beat
from tools.provider_semantic_coverage import required_fact_ids, build_semantic_coverage_receipt


class PacingTests(unittest.TestCase):
    def test_content_window_consumed_and_cannot_exceed_provider(self):
        p={'duration_seconds':4,'duration_authority':{'authorized_content_seconds':3}}
        self.assertIn('3秒',content_window_clause(p))
        self.assertIn('PACING.CONTENT_WINDOW',required_fact_ids(p))
        p['duration_authority']['authorized_content_seconds']=5
        with self.assertRaises(ValueError):content_window_clause(p)
    def test_delivery_cannot_be_dropped_from_coverage(self):
        plan={'unit_id':'TEST','beats':[{'dialogue':'甲：话','dialogue_delivery':{'chinese_characters_per_second':5.8}}]}
        self.assertIn('BEAT.1.DIALOGUE_DELIVERY',required_fact_ids(plan))
        r=build_semantic_coverage_receipt(plan=plan,prompt_text='话',model_family='SEEDANCE_2',clause_evidence={})
        self.assertTrue(any('DIALOGUE_DELIVERY' in f for f in r['failures']))

    def test_sd2_delivery_outside_literal(self):
        b={'dialogue':'老人：修行。','dialogue_delivery':{'chinese_characters_per_second':5.8}}
        before=copy.deepcopy(b)
        self.assertIn('：“修行。”',_dialogue(b))
        self.assertIn('每秒5.8',_dialogue(b))
        self.assertEqual(b,before)

    def test_h3_tags_and_binding_unchanged(self):
        b=dict(source_index=1,start_seconds=0,end_seconds=4,dialogue='老人：修行。',dialogue_delivery={'chinese_characters_per_second':5.8})
        t=dict(entry_state='sitting',primary_action='speaks',exit_state='sitting')
        binding=dict(provider_entity_label='ELDER',subject_token='SUBJECT_1',image_slot='@Image1',speaker_slot='SPEAKER_1',audio_slot='@Audio1',visible_speaker=True)
        text,e=_beat(b,t,dialogue_binding=binding)
        self.assertIn('<d>[Chinese] 修行。</d>',text)
        self.assertIn('5.8 Chinese characters per second',text)
        self.assertIn('BEAT.1.DIALOGUE_DELIVERY',e)

    def test_invalid_rates(self):
        for rate in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):
                delivery_clause({'dialogue':'甲：话','dialogue_delivery':{'chinese_characters_per_second':rate}})

    def test_only_legacy_wait_is_migrated(self):
        old='前段最后0.8秒落稳“持刀”并保留自然余振；后段前0.8秒承接同一状态后才开始新动作。'
        self.assertIn('立即',continuous_bridge(old))
        self.assertIn('持刀',continuous_bridge(old))
        self.assertEqual(continuous_bridge('导演授权停顿1秒'), '导演授权停顿1秒')

    def test_mapping(self):
        e=edit_interval(1,4,1.2,10)
        self.assertAlmostEqual(e['output_end'],12.5)
        self.assertEqual(map_interval(1,4,e),(10,2.5))
        with self.assertRaises(ValueError):map_interval(0,.5,e)

    def test_provider_padding_not_edit_duration(self):
        u=dict(duration_seconds=4,editorial_keep_seconds=3)
        self.assertEqual(editorial_duration(u,4),3)
        with self.assertRaises(ValueError):editorial_duration(u,4,contains_dialogue=True)
        self.assertEqual(editorial_duration(u,4,contains_dialogue=True,verified_end=3.5),3.5)

if __name__=='__main__':unittest.main()
