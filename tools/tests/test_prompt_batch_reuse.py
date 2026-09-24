"""Reuse is evidence-backed preparation, never permission to POST again."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.episode_prompt_batch_gate import digest, evaluate, require_generation_batch


class ReuseBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'source.mp4'
        self.media.write_bytes(b'fixture: not a visual QA claim')
        self.context = self.root / 'contract.json'
        self.context.write_text('{}')
        self.admission = {'status': 'ADMITTED', 'downstream_status': 'ADMITTED_FOR_ASSEMBLY',
                          'asset_path': str(self.media), 'asset_sha256': digest(self.media), 'failures': []}
        self.assembly = {'unit_id': 'U1', 'downstream_status': 'ADMITTED_FOR_ASSEMBLY',
                         'admission_result': str(self.root / 'admission.json'),
                         'tasks': [{'source_id': 'U1', 'output_path': str(self.media),
                                    'sha256': digest(self.media), 'status': 'qa_pass'}]}
        self.review = {'status': 'PASS', 'execution_id': 'RUN', 'unit_id': 'U1',
                       'media_sha256': digest(self.media), 'scope': 'REPAIR_CONTEXT_CONTINUITY',
                       'cross_unit_continuity_checked': True, 'reviewer': 'test fixture',
                       'observation': 'Fixture only', 'context_refs': [self.ref(self.context)]}
        self.config = {'required': True, 'unit_ids': ['U1'], 'manifest_ref': 'batch.json'}
        policy = self.root / 'configs/EPISODE_PROMPT_BATCH_POLICY.json'
        policy.parent.mkdir()
        policy.write_text(json.dumps({'executions': {'RUN': self.config}}))
        self.save()

    def ref(self, path):
        return {'path': str(path), 'sha256': digest(path)}

    def save(self):
        refs = {'media': self.ref(self.media)}
        for name, obj, filename in [('assembly_receipt', self.assembly, 'assembly.json'),
                                    ('admission_result', self.admission, 'admission.json'),
                                    ('continuity_review', self.review, 'review.json')]:
            path = self.root / filename
            path.write_text(json.dumps(obj))
            refs[name] = self.ref(path)
        self.row = {'unit_id': 'U1', 'mode': 'REUSE_EXISTING_MEDIA', 'reuse_evidence': refs}
        self.write_batch()

    def write_batch(self):
        (self.root / 'batch.json').write_text(json.dumps({'execution_id': 'RUN', 'rows': [self.row]}))

    def check(self):
        return evaluate(self.root, self.config, execution_id='RUN', unit_id='U1')['status']

    def test_valid_reuse_needs_no_new_prompts(self):
        self.assertEqual(self.check(), 'PASS')

    def test_reuse_can_never_post(self):
        for kind in ('video_prompt', 'keyframe_prompt'):
            with self.assertRaisesRegex(ValueError, 'REUSE_ROW_CANNOT_GENERATE'):
                require_generation_batch({'episode': 'EP', 'execution_id': 'RUN', 'unit_id': 'U1'},
                                         self.root, artifact_kind=kind)

    def test_stale_media(self):
        self.media.write_bytes(b'changed')
        self.assertEqual(self.check(), 'HOLD')

    def test_wrong_unit(self):
        self.assembly['unit_id'] = 'OTHER'
        self.save()
        self.assertEqual(self.check(), 'HOLD')

    def test_revoked_admission(self):
        self.admission['status'] = 'REJECTED'
        self.save()
        self.assertEqual(self.check(), 'HOLD')

    def test_missing_current_review(self):
        self.review['status'] = 'NOT_VERIFIED'
        self.save()
        self.assertEqual(self.check(), 'HOLD')

    def test_changed_repair_context(self):
        self.context.write_text('{"changed":true}')
        self.assertEqual(self.check(), 'HOLD')

    def test_wrong_admitted_asset(self):
        self.admission['asset_sha256'] = 'other'
        self.save()
        self.assertEqual(self.check(), 'HOLD')

    def test_missing_reference(self):
        del self.row['reuse_evidence']['continuity_review']
        self.write_batch()
        self.assertEqual(self.check(), 'HOLD')

    def test_unknown_mode_not_silently_generation(self):
        self.row['mode'] = 'REUSE_TYPO'
        self.write_batch()
        self.assertEqual(self.check(), 'HOLD')


if __name__ == '__main__':
    unittest.main()
