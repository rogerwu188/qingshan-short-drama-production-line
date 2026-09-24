import json
import tempfile
import unittest
from pathlib import Path
from tools.weak_media_admission import REQUIRED, sha, load_admission
from tools.build_agentcut_from_admitted_storyboard_sources import build


class WeakAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'clip.mp4'
        self.media.write_bytes(b'fixture')
        self.checks = dict.fromkeys(REQUIRED, 'PASS')
        self.checks.update(dialogue_asr='PASS', identity_in_motion='NOT_VERIFIED')

    def save(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return {'path': str(path), 'sha256': sha(path)}

    def bundle(self):
        policy = self.save('policy.json', {'episode': 'TEST', 'profile': 'WEAK_TECHNICAL',
            'user_directive': 'Explicit weak postcheck policy', 'allow_assembly': True,
            'authorized_media': {'U1': sha(self.media)}})
        report = self.save('checks.json', {'profile': 'WEAK_TECHNICAL', 'units': [{
            'unit_id': 'U1', 'media_path': str(self.media), 'media_sha256': sha(self.media),
            'checks': self.checks}]})
        self.save('bundle.json', {'schema': 'qingshan.weak_media_admission.v1', 'episode': 'TEST',
            'policy': policy, 'units': [{'unit_id': 'U1', 'media_path': str(self.media),
            'media_sha256': sha(self.media), 'basis': 'WEAK_TECHNICAL', 'evidence': report}]})
        return self.root / 'bundle.json'

    def test_not_verified_stays_not_verified(self):
        rows = load_admission(self.bundle(), 'TEST')
        self.assertEqual(rows['U1']['decision'], 'ALLOW')
        self.assertEqual(rows['U1']['checks']['identity_in_motion'], 'NOT_VERIFIED')

    def test_required_missing_or_failure_blocks(self):
        for status in ('FAIL', 'NOT_VERIFIED', 'ADVISORY'):
            self.checks['decode'] = status
            with self.assertRaises(ValueError):
                load_admission(self.bundle(), 'TEST')

    def test_clear_identity_error_blocks(self):
        self.checks['identity_in_motion'] = 'HARD_FAIL'
        with self.assertRaises(ValueError):
            load_admission(self.bundle(), 'TEST')

    def test_stale_policy_blocks(self):
        path = self.bundle()
        (self.root / 'policy.json').write_text('{}')
        with self.assertRaises(ValueError):
            load_admission(path, 'TEST')

    def test_stale_media_blocks(self):
        path = self.bundle()
        self.media.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            load_admission(path, 'TEST')

    def test_builder_consumes_policy_without_fake_visual_pass(self):
        bundle = self.bundle()
        receipt = self.save('receipt.json', {'tasks': [{'source_id':'U1',
            'output_path':str(self.media), 'duration':5, 'status':'completed'}]})
        contract = self.save('contract.json', {'episode':'TEST', 'audio_contract':{
            'bgm':'NONE_WHOLE_EPISODE', 'native_dialogue_only':True}})
        project = self.root / 'project.json'
        build('TEST',[receipt['path']],[],project,self.root/'admission.json',
              self.root/'final.mp4',1,contract['path'],weak_admission=bundle)
        clip = json.loads(project.read_text())['timeline']['videoTracks'][0]['clips'][0]
        self.assertEqual(clip['metadata']['source_qa'], 'ALLOW_WEAK_POSTCHECK_NOT_FULL_VISUAL_PASS')
        self.assertEqual(clip['metadata']['policy_admission']['checks']['identity_in_motion'], 'NOT_VERIFIED')

    def test_legacy_still_requires_review(self):
        receipt = self.save('receipt.json', {'tasks':[{'source_id':'U1', 'status':'qa_pass',
            'output_path':str(self.media), 'duration':5}]})
        contract = self.save('contract.json', {'episode':'TEST'})
        with self.assertRaisesRegex(ValueError, 'missing AI-review'):
            build('TEST',[receipt['path']],[],self.root/'p.json',self.root/'a.json',
                  self.root/'v.mp4',1,contract['path'])

if __name__ == '__main__':
    unittest.main()
