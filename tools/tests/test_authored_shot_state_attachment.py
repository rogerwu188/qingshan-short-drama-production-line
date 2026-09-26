import copy
import unittest
from tools.authored_shot_state_attachment import apply_authored_states


class AuthoredStateTests(unittest.TestCase):
    def fixture(self):
        state={'presence':'PRESENT','posture':'SEATED','injury':'NONE','wardrobe':'APPROVED_A','position':'TABLE_EAST'}
        env={k:'declared' for k in ('time','weather','lighting','space_topology','population','ambient_life')}
        ledger={'status':'PASS','characters':[{'character_id':'C1','entry_state':state,'exit_state':dict(state)}],'environment':{'entry_state':env,'exit_state':dict(env)}}
        shots={sid:{'angle_id':'A1','axis_id':'X1','prompt_spec':{'camera_plan':{'shot_scale':'MEDIUM','lens_intent':'natural perspective','motion_family':'PAN'}}} for sid in ('S1','S2')}
        attachment={'schema':'qingshan.authored_shot_state_attachment.v1','episode':'TEST','source_contract_sha256':'abc','shots':[{'shot_id':sid,'author':'test author','source_ref':'sealed fixture','persistent_state_contract':copy.deepcopy(ledger)} for sid in shots],'internal_transitions':[]}
        spec={'groups':[{'unit_id':'UNIT1','editorial_shot_ids':['S1','S2']}]}
        return spec,shots,attachment

    def apply(self,spec,shots,attachment):
        return apply_authored_states(spec,shots,attachment,contract_sha256='abc',episode='TEST')

    def test_consumes_states_and_preserves_input(self):
        spec,shots,a=self.fixture(); before=copy.deepcopy(a)
        a['shots'][-1]['persistent_state_contract']['characters'][0]['exit_state']['posture']='STANDING'
        self.apply(spec,shots,a)
        g=spec['groups'][0]
        self.assertEqual(g['persistent_state_contract']['characters'][0]['exit_state']['posture'],'STANDING')
        self.assertEqual(g['shot_state_contracts'][0]['camera_state']['camera_position_id'],'A1')
        self.assertNotIn('camera_state',a['shots'][0])
        self.assertEqual(before['shots'][0],a['shots'][0])

    def test_stale_sha_blocks(self):
        spec,shots,a=self.fixture();a['source_contract_sha256']='old'
        with self.assertRaisesRegex(ValueError,'AUTHORITY_MISMATCH'):self.apply(spec,shots,a)

    def test_prop_envelope_uses_actual_last_exit(self):
        spec,shots,a=self.fixture()
        a['shots'][0]['persistent_state_contract']['props']={'entry_state':{'stick':'rack'},'exit_state':{'stick':'held'}}
        a['shots'][1]['persistent_state_contract']['props']={'entry_state':{'stick':'held'},'exit_state':{'stick':'returned'}}
        self.apply(spec,shots,a)
        self.assertEqual(spec['groups'][0]['persistent_state_contract']['props'],
                         {'entry_state':{'stick':'rack'},'exit_state':{'stick':'returned'}})

    def test_missing_shot_blocks(self):
        spec,shots,a=self.fixture();a['shots'].pop()
        with self.assertRaisesRegex(ValueError,'COVERAGE_MISMATCH'):self.apply(spec,shots,a)

    def test_missing_character_state_blocks(self):
        spec,shots,a=self.fixture();del a['shots'][0]['persistent_state_contract']['characters'][0]['entry_state']['posture']
        with self.assertRaisesRegex(ValueError,'FIELD_MISSING'):self.apply(spec,shots,a)

    def test_legacy_conflict_blocks(self):
        spec,shots,a=self.fixture();spec['groups'][0]['shot_state_contracts']=[{'shot_id':'S1'}]
        with self.assertRaisesRegex(ValueError,'LEGACY_AUTHORITY_CONFLICT'):self.apply(spec,shots,a)

if __name__=='__main__':unittest.main()
