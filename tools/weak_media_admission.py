"""Explicit, hash-bound weak-postcheck admission. Never rewrites QA facts."""
import hashlib
import json
from pathlib import Path

REQUIRED = ('decode', 'duration', 'video_track', 'audio_track', 'black_detector',
            'freeze_detector', 'audio_not_entirely_silent')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence(ref):
    path = Path(ref['path'])
    if not path.is_absolute() or sha(path) != ref['sha256']:
        raise ValueError('WEAK_ADMISSION_EVIDENCE_MISMATCH')
    return json.loads(path.read_text())


def load_admission(path, episode):
    bundle = json.loads(Path(path).read_text())
    if bundle.get('schema') != 'qingshan.weak_media_admission.v1' or bundle.get('episode') != episode:
        raise ValueError('WEAK_ADMISSION_SCOPE_MISMATCH')
    policy = evidence(bundle['policy'])
    if (policy.get('profile') != 'WEAK_TECHNICAL' or policy.get('episode') != episode
            or policy.get('allow_assembly') is not True or not policy.get('user_directive')):
        raise ValueError('WEAK_ADMISSION_POLICY_INVALID')
    rows = {}
    for row in bundle['units']:
        uid = row['unit_id']
        if uid in rows:
            raise ValueError('WEAK_ADMISSION_DUPLICATE_UNIT')
        source = Path(row['media_path']).resolve()
        if sha(source) != row['media_sha256']:
            raise ValueError('WEAK_ADMISSION_MEDIA_MISMATCH')
        if policy.get('authorized_media', {}).get(uid) != row['media_sha256']:
            raise ValueError('WEAK_ADMISSION_AUTHORIZATION_SCOPE')
        for finding_ref in row.get('known_findings', []):
            finding = evidence(finding_ref)
            if finding.get('media_sha256') != row['media_sha256'] or finding.get('unit_id') != uid:
                raise ValueError('WEAK_ADMISSION_FINDING_SCOPE')
            if finding.get('status') == 'HARD_FAIL':
                raise ValueError('WEAK_ADMISSION_CONFIRMED_HARD_FAIL:' + str(finding.get('reason')))
        report = evidence(row['evidence'])
        if row['basis'] == 'EXISTING_EXACT_SHA_ADMISSION':
            matches = [r for r in report.get('sources', []) if r.get('source_id') == uid]
            if report.get('episode') != episode or report.get('status') != 'PASS' or len(matches) != 1:
                raise ValueError('WEAK_ADMISSION_REUSE_INVALID')
            old = matches[0]
            if (old.get('status') != 'PASS' or old.get('video_sha256') != row['media_sha256']
                    or old.get('audio_sha256') != row['media_sha256']
                    or Path(old['video_path']).resolve() != source
                    or Path(old['audio_path']).resolve() != source):
                raise ValueError('WEAK_ADMISSION_REUSE_SHA_MISMATCH')
            checks = {'existing_admission': 'PASS', 'new_visual_review': 'NOT_VERIFIED'}
        elif row['basis'] == 'WEAK_TECHNICAL':
            matches = [r for r in report.get('units', []) if r.get('unit_id') == uid]
            if report.get('profile') != 'WEAK_TECHNICAL' or len(matches) != 1:
                raise ValueError('WEAK_ADMISSION_TECHNICAL_SCOPE')
            observed = matches[0]
            if observed['media_sha256'] != row['media_sha256'] or Path(observed['media_path']).resolve() != source:
                raise ValueError('WEAK_ADMISSION_TECHNICAL_MEDIA')
            checks = dict(observed['checks'])
            if any(checks.get(key) != 'PASS' for key in REQUIRED):
                raise ValueError('WEAK_ADMISSION_REQUIRED_TECHNICAL_FAIL')
            failures = {k for k, v in checks.items() if v in ('FAIL', 'HARD_FAIL')}
            if failures == {'dialogue_asr'} and row.get('tail_evidence'):
                tail = evidence(row['tail_evidence'])
                if (tail.get('asset_sha256') != row['media_sha256'] or tail.get('unit_id') != uid
                        or tail.get('raw_failures') != ['dialogue_tail_clipped_or_unverified']
                        or tail.get('status') != 'ADVISORY'):
                    raise ValueError('WEAK_ADMISSION_TAIL_EVIDENCE_INVALID')
                # This is evidence of detector ambiguity, not a blanket override.
                for ref in tail['evidence']:
                    if sha(ref['path']) != ref['sha256']:
                        raise ValueError('WEAK_ADMISSION_TAIL_EVIDENCE_STALE')
                failures.clear()
            if failures:
                raise ValueError('WEAK_ADMISSION_UNRESOLVED_FAILURE:' + ','.join(sorted(failures)))
            # Unexecuted optional visual checks stay unverified, never PASS.
            if checks.get('dialogue_asr') not in ('PASS', 'FAIL', 'ADVISORY'):
                raise ValueError('WEAK_ADMISSION_DIALOGUE_MISSING')
        else:
            raise ValueError('WEAK_ADMISSION_UNKNOWN_BASIS')
        rows[uid] = {**row, 'checks': checks, 'decision': 'ALLOW',
                     'profile': policy['profile'], 'policy_sha256': bundle['policy']['sha256']}
    return rows
