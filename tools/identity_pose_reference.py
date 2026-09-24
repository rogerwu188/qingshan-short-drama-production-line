"""Select existing verified angle references; never generate or invent coverage."""
import re


def supplement_pose_references(bindings, library, entry_state, *, limit=12):
    rows = [dict(row) for row in bindings]
    report = []
    for row in bindings:
        if row.get('role') != 'character':
            continue
        name = row.get('entity_name') or ''
        clauses = [s for s in re.split(r'[；;。\n]', entry_state) if name and name in s]
        relevant = ' '.join(clauses)
        # An unresolved alias must not silently be treated as a frontal pose.
        # Use only this same identity's approved supplement, without guessing
        # another character's clause, and retain the unresolved semantic status.
        oblique = not clauses or any(word in relevant for word in ('低头', '侧脸', '侧身', '俯视', '誊诗', '书写', '看纸'))
        if not oblique:
            continue
        matches = []
        for asset in (library.get('assets', {}).get('characters', {})).values():
            original = asset.get('original_identity_authority') or {}
            original_matches = original.get('path') == row.get('path') and original.get('sha256') == row.get('sha256')
            if not original_matches and not any(a.get('path') == row.get('path') and a.get('sha256') == row.get('sha256')
                       for a in asset.get('artifacts', [])):
                continue
            if asset.get('status') != 'LOCKED' or asset.get('qa', {}).get('status') != 'PASS':
                continue
            matches.extend(a for a in asset.get('artifacts', [])
                           if 'THREE_QUARTER' in str(a.get('view', '')) + str(a.get('path', ''))
                           and a.get('sha256')
                           and (not original or (
                               (a.get('original_identity_review') or {}).get('status') == 'PASS'
                               and (a.get('original_identity_review') or {}).get('source_sha256') == original.get('sha256')
                               and (a.get('original_identity_review') or {}).get('asset_sha256') == a.get('sha256')
                               and (a.get('original_identity_review') or {}).get('evidence_ref'))))
        record = {'entity_id': row.get('entity_id'), 'entry_clause': relevant,
                  'pose_assessment': 'EXPLICIT_OBLIQUE_CUE' if clauses else 'NOT_VERIFIED_NAME_OR_POSE_UNRESOLVED',
                  'status': 'ADVISORY', 'automatic_paid_regeneration': False,
                  'coverage': 'MISSING_APPROVED_OBLIQUE_REFERENCE'}
        if matches:
            ref = matches[0]
            existing = {r['path'] for r in rows}
            if ref['path'] in existing or len(existing) < limit:
                if ref['path'] not in existing:
                    extra = dict(row)
                    extra.update(role='character_reference', path=ref['path'], sha256=ref['sha256'],
                                 view='THREE_QUARTER_BUST', kind='SUPPLEMENTAL_IDENTITY_VIEW')
                    rows.append(extra)
                record.update(coverage='OBLIQUE_REFERENCE_INCLUDED_NOT_EXACT_POSE_PROOF',
                              reference_path=ref['path'], reference_sha256=ref['sha256'])
            else:
                record['coverage'] = 'REFERENCE_CAP_NO_ROOM_FOR_SUPPLEMENT'
        report.append(record)
    return rows, report
