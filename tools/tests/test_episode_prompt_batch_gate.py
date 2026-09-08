import json
import tempfile
import unittest
from pathlib import Path
from tools.episode_prompt_batch_gate import evaluate,digest,require_generation_batch

class BatchGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={'required':True,'unit_ids':['U1','U2'],'manifest_ref':'batch.json'}
        self.rows=[]
        for uid in self.config['unit_ids']:
            row={'unit_id':uid}
            for name in ('keyframe_prompt','video_prompt'):
                p=self.root/f'{uid}_{name}.txt';p.write_text(uid+name)
                row[name]={'path':p.name,'sha256':digest(p)}
            qa={'execution_id':'RUN','unit_id':uid,'status':'PASS','scope':'PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY','cross_unit_continuity_checked':True}
            qa.update({n+'_sha256':row[n]['sha256'] for n in ('keyframe_prompt','video_prompt')})
            p=self.root/f'{uid}_qa.json';p.write_text(json.dumps(qa))
            row['prompt_qa']={'path':p.name,'sha256':digest(p)};self.rows.append(row)
        self.save()
    def save(self):
        (self.root/'batch.json').write_text(json.dumps({'execution_id':'RUN','rows':self.rows}))
    def check(self):return evaluate(self.root,self.config,execution_id='RUN',unit_id='U1')
    def test_complete_batch_passes_without_any_media(self):self.assertEqual(self.check()['status'],'PASS')
    def test_missing_other_unit_blocks_first(self):
        self.rows.pop();self.save();self.assertEqual(self.check()['status'],'HOLD')
    def test_changed_prompt_invalidates_batch(self):
        (self.root/'U2_video_prompt.txt').write_text('changed');self.assertEqual(self.check()['status'],'HOLD')
    def test_duplicate_unit_rejected(self):
        self.rows.append(self.rows[0]);self.save();self.assertEqual(self.check()['status'],'HOLD')
    def test_unverified_cross_unit_qa_blocks(self):
        p=self.root/'U2_qa.json';q=json.loads(p.read_text());q['cross_unit_continuity_checked']=False;p.write_text(json.dumps(q))
        self.rows[1]['prompt_qa']['sha256']=digest(p);self.save();self.assertEqual(self.check()['status'],'HOLD')
    def test_off_is_compatible(self):self.assertEqual(evaluate(self.root,None,execution_id='RUN',unit_id='U1')['status'],'NOT_REQUIRED')
    def test_missing_evidence_is_not_approval(self):
        (self.root/'batch.json').unlink();self.assertEqual(self.check()['status'],'HOLD')
    def paid_task(self):
        p=self.root/'workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json';p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({'executions':{'RUN':self.config}}))
        return {'episode':'E56','execution_id':'RUN','unit_id':'U1','prompt_sha256':self.rows[0]['video_prompt']['sha256']}
    def test_paid_exact_prompt_binding(self):
        self.assertEqual(require_generation_batch(self.paid_task(),self.root)['status'],'PASS')
    def test_paid_changed_text_requires_incremental_review(self):
        t=self.paid_task();t['prompt_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'FINAL_PROMPT_NOT_BOUND'):require_generation_batch(t,self.root)
    def test_incremental_binding_checks_final_hash(self):
        t=self.paid_task();t['prompt_sha256']='new-final'
        q={'status':'PASS','execution_id':'RUN','unit_id':'U1','artifact_kind':'video_prompt',
           'planned_prompt_sha256':self.rows[0]['video_prompt']['sha256'],'final_prompt_sha256':'new-final',
           'scope':'INCREMENTAL_EXACT_MATERIALIZATION_QA'}
        p=self.root/'incremental.json';p.write_text(json.dumps(q));t['prompt_batch_finalization']={'path':p.name,'sha256':digest(p)}
        self.assertEqual(require_generation_batch(t,self.root)['status'],'PASS')
        t['prompt_sha256']='another-final'
        with self.assertRaisesRegex(ValueError,'FINALIZATION_QA_MISMATCH'):require_generation_batch(t,self.root)

if __name__=='__main__':unittest.main()
