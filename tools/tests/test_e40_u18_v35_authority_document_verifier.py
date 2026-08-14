import json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from tools.e40_u18_v35_authority_document_verifier import PINS,verify
from tools.e40_u18_v31_atomic_persistence_bundle import compile_bundle
from tools.tests.test_e40_u18_v31_atomic_persistence_bundle import setup
NOW=datetime(2026,8,13,12,0,tzinfo=timezone.utc)
def fixture(root,branch='ROOT'):
 p,t=setup(root,branch);b=compile_bundle(p,t,root)['bundle'];bp=root/'bundle.json';bp.write_text(json.dumps(b));lp=Path(b['locks']['nonce_ledger_path']);d={'schema':'qingshan.e40.u18.v35.one_time_root_persistence_authorization.v1','episode':'E40','unit_id':'U18','authority_scope':'PERSIST_AUTHORIZATION_TARGET_ONLY' if b['branch']=='AUTHORIZATION' else 'PERSIST_FORMAL_MEMORY_EVENT_ONLY','bundle_sha256':b['bundle_sha256'],'v29_proposal_sha256':b['locks']['v29_proposal_sha256'],'explicit_decision_sha256':b['locks']['explicit_decision_sha256'],'branch':b['branch'],'target_path':b['locks']['target_path'],'nonce':b['nonce'],**PINS,'nonce_ledger_sha256':b['locks']['nonce_ledger_sha256'],'issued_at':'2026-08-13T11:55:00Z','expires_at':'2026-08-13T12:05:00Z','single_use':True,'consumed':False,'signer':{'role':'ROOT_PERSISTENCE_AUTHORIZER','identity':'root-signer-fixture'}};dp=root/'auth.json';dp.write_text(json.dumps(d));return dp,bp,lp
class T(unittest.TestCase):
 def test_valid_both_branches_not_executed(self):
  for branch in ('ROOT','MEMORY'):
   with tempfile.TemporaryDirectory() as x:
    r=Path(x);d,b,l=fixture(r,branch);v=verify(d,b,l,NOW,r);self.assertEqual(v['status'],'VALID_AUTHORITY_DOCUMENT_NOT_EXECUTED');self.assertFalse(v['execution_authorized'])
 def test_generic_authority_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);d,b,l=fixture(r);q=json.loads(d.read_text());q['authority_scope']='ALL_ACTIONS';d.write_text(json.dumps(q));self.assertIn('GENERIC_OR_OTHER_ACTION_AUTHORITY_REJECTED',verify(d,b,l,NOW,r)['failures'])
 def test_expired_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);d,b,l=fixture(r);q=json.loads(d.read_text());q['expires_at']='2026-08-13T11:59:00Z';d.write_text(json.dumps(q));self.assertIn('AUTHORITY_EXPIRED_OR_TIME_INVALID',verify(d,b,l,NOW,r)['failures'])
 def test_branch_target_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);d,b,l=fixture(r);q=json.loads(d.read_text());q['target_path']='workflow/approvals/wrong.json';d.write_text(json.dumps(q));self.assertIn('BRANCH_OR_TARGET_MISMATCH',verify(d,b,l,NOW,r)['failures'])
 def test_replay_nonce_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);d,b,l=fixture(r);q=json.loads(d.read_text());ledger=json.loads(l.read_text());ledger['used_nonces']=[q['nonce']];l.write_text(json.dumps(ledger));q['nonce_ledger_sha256']=__import__('hashlib').sha256(l.read_bytes()).hexdigest();d.write_text(json.dumps(q));self.assertIn('NONCE_LEDGER_STALE_OR_REPLAYED',verify(d,b,l,NOW,r)['failures'])
 def test_other_action_field_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);d,b,l=fixture(r);q=json.loads(d.read_text());q['allow_provider_post']=True;d.write_text(json.dumps(q));self.assertIn('EXACT_FIELD_SET_REQUIRED',verify(d,b,l,NOW,r)['failures'])
if __name__=='__main__':unittest.main()
