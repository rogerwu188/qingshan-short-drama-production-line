"""Shared SD2/H3 postgen disposition; never infer audible facts from ASR spelling."""
import hashlib
import json
from pathlib import Path

import os
_ROOT=Path(__file__).resolve().parents[1]
def _policy_path():
    """QINGSHAN_BASIC_DIALOGUE_QA_POLICY → private configs/ (gitignored deployment file) → the tracked
    default template, so a clean clone and both production lines resolve one policy contract."""
    for candidate in (os.environ.get('QINGSHAN_BASIC_DIALOGUE_QA_POLICY') or '', _ROOT/'configs/BASIC_DIALOGUE_QA_POLICY.json', _ROOT/'tools/policies/BASIC_DIALOGUE_QA_POLICY.default.json'):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return _ROOT/'configs/BASIC_DIALOGUE_QA_POLICY.json'
POLICY_PATH=_policy_path()

def evaluate_dialogue_findings(findings):
    data=POLICY_PATH.read_bytes();policy=json.loads(data)
    codes=list(dict.fromkeys(findings))
    minor=[c for c in codes if c in policy['nonblocking_findings']]
    failures=[c for c in codes if c in policy['basic_failures_preserved']]
    unknown=[c for c in codes if c not in minor and c not in failures]
    return {
        'policy_id':policy['policy_id'],'policy_ref':str(POLICY_PATH.relative_to(_ROOT)) if str(POLICY_PATH).startswith(str(_ROOT)) else str(POLICY_PATH),
        'policy_sha256':hashlib.sha256(data).hexdigest(),
        'status':'FAIL_BASIC_DIALOGUE' if failures else 'REVIEW_UNCLASSIFIED_FINDINGS' if unknown else 'PASS_WITH_NOTE' if minor else 'NO_DIALOGUE_FINDINGS',
        'advisories':minor,'failures':failures,'unclassified':unknown,
        'minor_difference_blocks_admission':False,
        'regeneration_for_minor_difference_allowed':False,
        'repeat_asr_for_minor_difference_allowed':False,
        'automatic_regeneration_authorized':False,
        'exact_pronunciation_verified':False,'voice_identity_verified':False,
        'scope':'POSTGEN_DIALOGUE_FINDING_DISPOSITION_NOT_FULL_MEDIA_OR_RELEASE_QA'}
