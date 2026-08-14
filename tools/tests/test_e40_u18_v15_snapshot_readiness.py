import json,tempfile,unittest
from pathlib import Path
from tools.e40_u18_v15_snapshot_readiness import NAMES,check
from tools.e40_u18_v9_offline_snapshot_ingest import EXPECTED,TEMPLATES
def write_valid(d):
 for name,(tid,(key,fp)) in zip(NAMES[:2],EXPECTED.items()):
  (d/name).write_text(json.dumps({'source':'EXACT_TASK_RESULT_SNAPSHOT','task_id':tid,'task_key':key,'submission_fingerprint':fp,'download_template_sha256':TEMPLATES['download'],'machine_contract_sha256':TEMPLATES['machine'],'status':'SUCCESS','output':{'path':'o.png','sha256':'a'*64}}))
 (d/NAMES[2]).write_text(json.dumps({'source':'AUTHORITATIVE_CREDIT_STATEMENT_SNAPSHOT','credit_template_sha256':TEMPLATES['credit'],'task_ids':list(EXPECTED),'rows':[{'row_id':'1'},{'row_id':'2'}],'classification':{'pay':10,'refund':0,'net':10,'status':'PASS'}}))
class T(unittest.TestCase):
 def test_no_files(self):
  with tempfile.TemporaryDirectory() as x:self.assertEqual(check(Path(x))['status'],'TASK_LOCAL_REMOTE_WAIT')
 def test_partial(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);(d/'x.part').write_text('{}');self.assertEqual(check(d)['status'],'TASK_LOCAL_REMOTE_WAIT')
 def test_complete_invalid(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);write_valid(d);q=json.loads((d/NAMES[2]).read_text());q['classification']['refund']=None;(d/NAMES[2]).write_text(json.dumps(q));self.assertEqual(check(d)['status'],'TASK_LOCAL_REMOTE_WAIT')
 def test_valid(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);write_valid(d);r=check(d);self.assertEqual(r['status'],'READY_FOR_LOCAL_OUTPUT_QA');self.assertFalse(r['blocks_other_lanes']);self.assertFalse(r['admission_permitted'])
if __name__=='__main__':unittest.main()
