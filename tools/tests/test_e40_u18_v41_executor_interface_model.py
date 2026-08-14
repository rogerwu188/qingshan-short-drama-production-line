import unittest
from tools.e40_u18_v41_executor_interface_model import run_model

LEDGER='workflow/nonce_ledgers/E40_U18_NONCE_LEDGER.json'
AUTH='workflow/approvals/E40_U18_AUTHORIZATION.json'
MEMORY='workflow/claude_writer_agent/formal_memory_updates/E40_U18_MEMORY.json'

class T(unittest.TestCase):
 def test_valid_both_branches_model_only(self):
  for branch,target in [('AUTHORIZATION',AUTH),('FORMAL_MEMORY_UPDATE_EVENT',MEMORY)]:
   with self.subTest(branch=branch):
    r=run_model(branch,'E40-U18-V41-model-nonce-0001',LEDGER,target)
    self.assertEqual(r['status'],'MODEL_COMMIT_COMPLETE_NOT_EXECUTED');self.assertTrue(r['state'].authority_consumed);self.assertIsNotNone(r['state'].receipt)
 def test_path_escape_rejected(self):
  for path in ['workflow/approvals/../secrets/x.json','/tmp/x.json','workflow/approvals2/x.json']:
   r=run_model('AUTHORIZATION','E40-U18-V41-model-nonce-0001',LEDGER,path)
   self.assertEqual(r['status'],'FAIL_CLOSED_NO_CHANGE');self.assertIn('TARGET_PATH_ESCAPE_OR_WRONG_BRANCH',r['failures'])
 def test_symlink_rejected(self):
  r=run_model('AUTHORIZATION','E40-U18-V41-model-nonce-0001',LEDGER,AUTH,symlinks={AUTH})
  self.assertIn('SYMLINK_REJECTED',r['failures']);self.assertFalse(r['state'].authority_consumed)
 def test_wrong_branch_rejected(self):
  for branch,target in [('AUTHORIZATION',MEMORY),('FORMAL_MEMORY_UPDATE_EVENT',AUTH),('ALL',AUTH)]:
   r=run_model(branch,'E40-U18-V41-model-nonce-0001',LEDGER,target)
   self.assertEqual(r['status'],'FAIL_CLOSED_NO_CHANGE')
 def test_second_target_rejected(self):
  r=run_model('AUTHORIZATION','E40-U18-V41-model-nonce-0001',LEDGER,AUTH,write_targets=[LEDGER,AUTH,'workflow/other/hidden.json'])
  self.assertIn('SECOND_OR_MISSING_TARGET_REJECTED',r['failures']);self.assertEqual(r['state'].targets,{})
 def test_partial_crashes_recover_both_unchanged(self):
  for point in ['NONCE_STAGED','TARGET_STAGED','ONE_SIDE_INSTALLED']:
   with self.subTest(point=point):
    r=run_model('AUTHORIZATION','E40-U18-V41-model-nonce-0001',LEDGER,AUTH,crash_at=point)
    self.assertEqual(r['status'],'MODEL_CRASH_RECOVERED_BOTH_UNCHANGED');self.assertTrue(r['recoverable']);self.assertEqual(r['state'].ledger,[]);self.assertEqual(r['state'].targets,{});self.assertFalse(r['state'].authority_consumed);self.assertIsNone(r['state'].receipt)
if __name__=='__main__':unittest.main()
