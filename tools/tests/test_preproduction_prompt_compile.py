from copy import deepcopy
import unittest
from tools.tests.test_shared_video_execution_compiler import _unit
from tools.video_prompt_compiler import compile_model_prompt, compile_receipt

class PreproductionCompileTests(unittest.TestCase):
    def draft(self):
        u=_unit()
        for s in u['ordered_prompt_specs']:
            for p in s['props']:
                p.pop('start_frame_visual_confirmation',None)
                p['state']['start_frame_visual_confirmation']={'status':'NOT_YET_VERIFIED'}
        return u
    def test_draft_can_compile_without_fake_visual_pass(self):
        u=self.draft();before=deepcopy(u)
        self.assertTrue(compile_model_prompt(u,preproduction_only=True))
        self.assertEqual(before,u)
        self.assertFalse(compile_receipt(u['unit_id'])['provider_post_allowed'])
    def test_final_compile_still_rejects_unobserved_media(self):
        u=self.draft()
        compile_model_prompt(u,preproduction_only=True)
        with self.assertRaisesRegex(ValueError,'NOT_VISUALLY_CONFIRMED'):compile_model_prompt(u)
    def test_task_field_cannot_enable_draft_bypass(self):
        u=self.draft();u['preproduction_only']=True
        with self.assertRaisesRegex(ValueError,'NOT_VISUALLY_CONFIRMED'):compile_model_prompt(u)
    def test_structural_prop_failures_still_block_draft(self):
        u=self.draft();u['ordered_prompt_specs'][0]['props'][0]['state']['entry'].pop('owner')
        with self.assertRaisesRegex(ValueError,'PROP_STATE_FIELDS_MISSING'):compile_model_prompt(u,preproduction_only=True)
    def test_existing_final_output_unchanged(self):
        u=_unit()
        self.assertEqual(compile_model_prompt(u),compile_model_prompt(u,preproduction_only=True))

if __name__=='__main__':unittest.main()
