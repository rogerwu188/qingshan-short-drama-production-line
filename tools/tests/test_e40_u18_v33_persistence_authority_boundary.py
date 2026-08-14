import json,tempfile,unittest
from pathlib import Path
from tools.e40_u18_v33_persistence_authority_boundary import ROOT,V5_AUTH,check
from tools.e40_u18_v31_atomic_persistence_bundle import compile_bundle
from tools.tests.test_e40_u18_v31_atomic_persistence_bundle import setup
def fixture(root,branch='ROOT'):
 proposal,target=setup(root,branch);old=root/V5_AUTH[0];old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes((ROOT/V5_AUTH[0]).read_bytes());bundle=compile_bundle(proposal,target,root)['bundle'];bp=root/'bundle.json';bp.write_text(json.dumps(bundle));return bp,bundle
def auth(root,bundle,source='FRESH_ROOT_PERSISTENCE_DECISION'):
 d={'schema':'qingshan.e40.u18.v33.one_time_root_persistence_authorization.v1','authority_source':source,'one_time':True,'consumed':False,'bundle_sha256':bundle['bundle_sha256'],'branch':bundle['branch']};p=root/'authority.json';p.write_text(json.dumps(d));return p
class T(unittest.TestCase):
 def test_no_fresh_authority_valid_wait(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,_=fixture(r);self.assertEqual(check(bp,None,r)['status'],'TASK_LOCAL_REMOTE_WAIT')
 def test_old_v5_image_authorization_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r);a=auth(r,b,'E40_U18_V5_IMAGE_AUTHORIZATION');self.assertIn('INVALID_INHERITED_AUTHORITY_SOURCE',check(bp,a,r)['failures'])
 def test_seedance_fast_authorization_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r);a=auth(r,b,'ROGER_SEEDANCE_FAST_MODEL_AUTHORIZATION');self.assertIn('INVALID_INHERITED_AUTHORITY_SOURCE',check(bp,a,r)['failures'])
 def test_heartbeat_instruction_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r);a=auth(r,b,'HEARTBEAT_INSTRUCTIONS');self.assertIn('INVALID_INHERITED_AUTHORITY_SOURCE',check(bp,a,r)['failures'])
 def test_stale_queue_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r);a=auth(r,b);(r/'workflow/work_queue.json').write_text('{}');self.assertIn('WORK_QUEUE_FRESH_LOCK_FAILED',check(bp,a,r)['failures'])
 def test_branch_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r);a=auth(r,b);d=json.loads(a.read_text());d['branch']='FORMAL_MEMORY_UPDATE_EVENT';a.write_text(json.dumps(d));self.assertIn('ROOT_PERSISTENCE_AUTHORITY_NOT_EXACT_FRESH_PER_BUNDLE',check(bp,a,r)['failures'])
 def test_valid_fresh_authority_preconditions_only_not_execution(self):
  with tempfile.TemporaryDirectory() as x:
   r=Path(x);bp,b=fixture(r,'MEMORY');a=auth(r,b);result=check(bp,a,r);self.assertTrue(result['status'].startswith('PRECONDITIONS_PASS'));self.assertFalse(result['execution_authorized']);self.assertFalse(result['nonce_registration_permitted']);self.assertFalse(result['target_write_permitted'])
if __name__=='__main__':unittest.main()
