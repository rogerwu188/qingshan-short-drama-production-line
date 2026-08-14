import copy,unittest
from tools.e40_u18_v43_interface_freeze_verifier import verify
BASE={'interface_version':'v1','allowed_future_business_writes_if_separately_authorized':['EXACT_NONCE_LEDGER_SINGLE_APPEND','EXACT_ONE_BRANCH_TARGET_CREATE'],'allowed_protocol_metadata_if_separately_authorized':['BOUND_DIRECTORY_EXCLUSIVE_LOCK','BOUND_DIRECTORY_RECOVERY_JOURNAL','BOUND_POST_WRITE_SHA_RECEIPT'],'network':False,'subprocess':False,'rollback':'COMPLETE_BOTH_OR_RESTORE_BOTH','inherit_v41_tests_as_authority':False}
class T(unittest.TestCase):
 def test_exact_v1_compatible_no_execution(self):
  r=verify(copy.deepcopy(BASE));self.assertEqual(r['status'],'INTERFACE_V1_COMPATIBLE_NO_EXECUTION');self.assertFalse(r['execution_authorized'])
 def test_new_path_rejected(self):
  x=copy.deepcopy(BASE);x['allowed_future_business_writes_if_separately_authorized'].append('workflow/other/new.json');self.assertIn('BUSINESS_WRITE_SET_EXTENSION_OR_CHANGE',verify(x)['failures'])
 def test_network_and_subprocess_rejected(self):
  for k in ['network','subprocess']:
   x=copy.deepcopy(BASE);x[k]=True;self.assertIn(k.upper()+'_CAPABILITY_FORBIDDEN',verify(x)['failures'])
 def test_third_write_target_rejected(self):
  x=copy.deepcopy(BASE);x['allowed_future_business_writes_if_separately_authorized'].append('THIRD_BUSINESS_TARGET');self.assertIn('BUSINESS_WRITE_SET_EXTENSION_OR_CHANGE',verify(x)['failures'])
 def test_rollback_weakening_rejected(self):
  x=copy.deepcopy(BASE);x['rollback']='BEST_EFFORT_PARTIAL_OK';self.assertIn('ROLLBACK_RECOVERY_WEAKENED',verify(x)['failures'])
 def test_v41_test_authority_inheritance_rejected(self):
  x=copy.deepcopy(BASE);x['inherit_v41_tests_as_authority']=True;self.assertIn('V41_TEST_AUTHORITY_INHERITANCE_FORBIDDEN',verify(x)['failures'])
 def test_extra_capability_field_rejected(self):
  x=copy.deepcopy(BASE);x['allow_shell']=True;self.assertIn('UNAUTHORIZED_EXTENSION_FIELD',verify(x)['failures'])
if __name__=='__main__':unittest.main()
