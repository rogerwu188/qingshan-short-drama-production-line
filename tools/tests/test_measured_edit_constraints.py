import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.measured_edit_constraints import digest, load_constraints, resolve_source_interval
from tools.build_agentcut_from_admitted_storyboard_sources import build


class MeasuredEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'unit.mp4'
        self.media.write_bytes(b'test-media')
        self.asr = self.root / 'asr.json'
        self.asr.write_text(json.dumps({'unit_id':'U1', 'media_sha256':digest(self.media),
            'result':{'status':'PASS','segments':[{'start':3.98,'end':4.98}]}}))
        self.row = {'unit_id':'U1', 'media_path':str(self.media), 'media_sha256':digest(self.media),
            'source_asr_ref':str(self.asr),'source_asr_sha256':digest(self.asr),
            'recommended_source_in_seconds':0,'recommended_source_out_seconds':5.056}
        mock = patch('tools.measured_edit_constraints.subprocess.run',
            return_value=SimpleNamespace(stdout=json.dumps({'format':{'duration':'5.056'}})))
        mock.start()
        self.addCleanup(mock.stop)

    def test_actual_tail_preserved(self):
        start, duration, audit = resolve_source_interval(self.row, self.media, 4.6)
        self.assertEqual((start, duration), (0,5.056))
        self.assertEqual(audit['timeline_delta_seconds'], .456)
        self.assertFalse(audit['render_verified'])
        self.assertFalse(audit['applied_to_project'])

    def test_truncated_tail_rejected(self):
        self.row['recommended_source_out_seconds'] = 4.6
        with self.assertRaisesRegex(ValueError,'TRUNCATE_DIALOGUE'):
            resolve_source_interval(self.row,self.media,4.6)

    def test_stale_media_rejected(self):
        self.media.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'MEDIA_MISMATCH'):
            resolve_source_interval(self.row,self.media,4.6)

    def test_stale_asr_rejected(self):
        self.asr.write_text('{}')
        with self.assertRaisesRegex(ValueError,'ASR_SHA_MISMATCH'):
            resolve_source_interval(self.row,self.media,4.6)

    def test_out_of_bounds_rejected(self):
        self.row['recommended_source_out_seconds']=6
        with self.assertRaisesRegex(ValueError,'SOURCE_RANGE_INVALID'):
            resolve_source_interval(self.row,self.media,4.6)

    def test_duplicate_rejected_and_disabled_empty(self):
        self.assertEqual(load_constraints(None),{})
        path=self.root/'constraints.json'
        path.write_text(json.dumps({'units':[self.row,self.row]}))
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            load_constraints(path)

    def test_builder_consumes_native_av_interval_and_rebases_next_clip(self):
        receipt=self.root/'receipt.json'
        receipt.write_text(json.dumps({'tasks':[
            {'source_id':u,'status':'qa_pass','output_path':str(self.media),'duration':4.6}
            for u in ['U1','U2']]}))
        review=self.root/'review.json'
        review.write_text(json.dumps({'passed_items':[{'path':str(self.media)}]}))
        contract=self.root/'contract.json'
        contract.write_text(json.dumps({'episode':'TEST','audio_contract':
            {'bgm':'NONE_WHOLE_EPISODE','native_dialogue_only':True}}))
        constraints=self.root/'constraints.json'
        constraints.write_text(json.dumps({'units':[self.row]}))
        project=self.root/'project.json'
        build('TEST',[receipt],[review],project,self.root/'admission.json',self.root/'final.mp4',2,
              contract, constraints)
        result=json.loads(project.read_text())
        self.assertTrue(result['timeline']['videoTracks'][0]['clips'][0]['metadata']['measured_edit']['applied_to_project'])
        for track in ['videoTracks','audioTracks']:
            clips=result['timeline'][track][0]['clips']
            self.assertEqual(clips[0]['duration'],5.056)
            self.assertEqual(clips[1]['start'],5.056)
            self.assertEqual(clips[1]['duration'],4.6)


if __name__ == '__main__':
    unittest.main()
