import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.episode_prompt_batch_gate import require_generation_batch
from tools import submit_giggle_image_manifest as image
from tools import submit_giggle_video_manifest_v2 as video

class PaidBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);p=self.root/'workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json'
        p.parent.mkdir(parents=True);p.write_text(json.dumps({'executions':{}}))
        self.task={'task_key':'E56-NEW','episode':'E56','unit_id':'U1','execution_id':'NEW'}
    def test_missing_execution_cannot_opt_out(self):
        with self.assertRaisesRegex(ValueError,'EXECUTION_NOT_REGISTERED'):require_generation_batch(self.task,self.root)
    def test_image_direct_entry_blocked_before_upload_or_post(self):
        with patch.object(image,'ROOT',self.root),patch.object(image,'prior_submission_result',return_value=None),patch.object(image,'_request') as post:
            with self.assertRaisesRegex(ValueError,'WHOLE_BATCH'):image._submit_one_locked(self.task,self.root,self.root)
            post.assert_not_called()
    def test_image_bound_recovery_unchanged(self):
        with patch.object(image,'ROOT',self.root),patch.object(image,'prior_submission_result',return_value={'task_id':'bound'}):
            self.assertEqual(image._submit_one_locked(self.task,self.root,self.root),{'task_id':'bound'})
    def test_video_direct_entry_blocked_before_post(self):
        with patch.object(video,'ROOT',self.root),patch.object(video,'prior_bound',return_value=None),patch.object(video,'_request') as post:
            with self.assertRaisesRegex(ValueError,'WHOLE_BATCH'):video.submit_one(self.task,self.root,self.root)
            post.assert_not_called()
    def test_video_bound_recovery_unchanged(self):
        with patch.object(video,'ROOT',self.root),patch.object(video,'prior_bound',return_value={'task_id':'bound'}):
            self.assertEqual(video.submit_one(self.task,self.root,self.root),{'task_id':'bound'})

if __name__=='__main__':unittest.main()
