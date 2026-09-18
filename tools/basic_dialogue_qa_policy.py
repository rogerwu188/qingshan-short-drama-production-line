"""Shared SD2/H3 postgen disposition; never infer audible facts from ASR spelling."""
import hashlib
import json
from pathlib import Path

POLICY_PATH=Path(__file__).resolve().parents[1]/'configs/BASIC_DIALOGUE_QA_POLICY.json'

def evaluate_dialogue_findings(findings):
    data=POLICY_PATH.read_bytes();policy=json.loads(data)
    codes=list(dict.fromkeys(findings))
    minor=[c for c in codes if c in policy['nonblocking_findings']]
    failures=[c for c in codes if c in policy['basic_failures_preserved']]
    unknown=[c for c in codes if c not in minor and c not in failures]
    return {
        'policy_id':policy['policy_id'],'policy_ref':'configs/BASIC_DIALOGUE_QA_POLICY.json',
        'policy_sha256':hashlib.sha256(data).hexdigest(),
        'status':'FAIL_BASIC_DIALOGUE' if failures else 'REVIEW_UNCLASSIFIED_FINDINGS' if unknown else 'PASS_WITH_NOTE' if minor else 'NO_DIALOGUE_FINDINGS',
        'advisories':minor,'failures':failures,'unclassified':unknown,
        'minor_difference_blocks_admission':False,
        'regeneration_for_minor_difference_allowed':False,
        'repeat_asr_for_minor_difference_allowed':False,
        'automatic_regeneration_authorized':False,
        'exact_pronunciation_verified':False,'voice_identity_verified':False,
        'scope':'POSTGEN_DIALOGUE_FINDING_DISPOSITION_NOT_FULL_MEDIA_OR_RELEASE_QA'}
