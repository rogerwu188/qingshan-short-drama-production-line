import json,tempfile,unittest
from pathlib import Path
from tools.e40_u18_v9_offline_snapshot_ingest import EXPECTED,TEMPLATES,validate
class TestOffline(unittest.TestCase):
 def fixtures(self,d):
  ps=[]
  for i,(tid,(key,fp)) in enumerate(EXPECTED.items()):
   p=d/f'r{i}.json';p.write_text(json.dumps({'source':'EXACT_TASK_RESULT_SNAPSHOT','task_id':tid,'task_key':key,'submission_fingerprint':fp,'download_template_sha256':TEMPLATES['download'],'machine_contract_sha256':TEMPLATES['machine'],'status':'SUCCESS','output':{'path':f'o{i}.png','sha256':str(i+1)*64}}));ps.append(p)
  c=d/'c.json';c.write_text(json.dumps({'source':'AUTHORITATIVE_CREDIT_STATEMENT_SNAPSHOT','credit_template_sha256':TEMPLATES['credit'],'task_ids':list(EXPECTED),'rows':[{'row_id':'p1'},{'row_id':'p2'}],'classification':{'pay':10,'refund':0,'net':10,'status':'PASS'}}));return ps,c
 def test_positive(self):
  with tempfile.TemporaryDirectory() as x:
   ps,c=self.fixtures(Path(x));self.assertEqual(validate(ps,c)['status'],'PASS')
 def test_reject_sibling(self):
  with tempfile.TemporaryDirectory() as x:
   ps,c=self.fixtures(Path(x));d=json.loads(ps[0].read_text());d['task_id']='sibling';ps[0].write_text(json.dumps(d));self.assertIn('SIBLING_OR_HISTORY_TASK_REJECTED:sibling',validate(ps,c)['failures'])
 def test_reject_history(self):
  with tempfile.TemporaryDirectory() as x:
   ps,c=self.fixtures(Path(x));d=json.loads(ps[0].read_text());d['source']='TASK_HISTORY';ps[0].write_text(json.dumps(d));self.assertTrue(any('HISTORY_OR_NONEXACT' in z for z in validate(ps,c)['failures']))
 def test_reject_missing_refund(self):
  with tempfile.TemporaryDirectory() as x:
   ps,c=self.fixtures(Path(x));d=json.loads(c.read_text());d['classification']['refund']=None;c.write_text(json.dumps(d));self.assertIn('MISSING_PAY_REFUND_NET_CLASSIFICATION',validate(ps,c)['failures'])
 def test_reject_unbound_output(self):
  with tempfile.TemporaryDirectory() as x:
   ps,c=self.fixtures(Path(x));d=json.loads(ps[0].read_text());d['output']['sha256']=None;ps[0].write_text(json.dumps(d));self.assertTrue(any('UNBOUND_OUTPUT_SHA' in z for z in validate(ps,c)['failures']))
 def test_reject_path_traversal(self):
  with tempfile.TemporaryDirectory() as x,tempfile.TemporaryDirectory() as y:
   ps,c=self.fixtures(Path(x));outside=Path(y)/'outside.json';outside.write_text(ps[0].read_text());ps[0]=outside;self.assertTrue(any('PATH_TRAVERSAL' in z for z in validate(ps,c,Path(x))['failures']))
 def test_reject_symlink(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);ps,c=self.fixtures(d);link=d/'link.json';link.symlink_to(ps[0]);ps[0]=link;self.assertTrue(any('SYMLINK_REJECTED' in z for z in validate(ps,c,d)['failures']))
 def test_reject_partial_json(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);ps,c=self.fixtures(d);ps[0].write_text('{');self.assertTrue(any('INVALID_RESULT_JSON' in z for z in validate(ps,c,d)['failures']))
 def test_reject_duplicate_task_id(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);ps,c=self.fixtures(d);ps[1].write_text(ps[0].read_text());self.assertIn('EXACT_TASK_ID_CLOSED_SET_MISMATCH',validate(ps,c,d)['failures'])
 def test_reject_duplicate_credit_row(self):
  with tempfile.TemporaryDirectory() as x:
   d=Path(x);ps,c=self.fixtures(d);q=json.loads(c.read_text());q['rows'][1]['row_id']='p1';c.write_text(json.dumps(q));self.assertIn('DUPLICATE_CREDIT_ROW_REJECTED',validate(ps,c,d)['failures'])
if __name__=='__main__':unittest.main()
