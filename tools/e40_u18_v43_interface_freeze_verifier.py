#!/usr/bin/env python3
"""Verify exact frozen V41 interface compatibility. No executor or I/O mutation."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'qa/e40_preproduction_20260813/u18_v43_executor_interface_v1_freeze/E40_U18_V43_INTERFACE_V1_CONTENT_ADDRESSED_MANIFEST.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(candidate:dict,root:Path=ROOT)->dict:
 f=[]
 try:m=json.loads((root/MANIFEST.relative_to(ROOT)).read_text())
 except Exception:return {'status':'INTERFACE_V1_COMPATIBILITY_FAIL_CLOSED','failures':['FROZEN_MANIFEST_MISSING_OR_INVALID'],'execution_authorized':False}
 for row in m.get('frozen_artifacts',[]):
  p=root/row.get('path','')
  if not p.is_file() or p.is_symlink() or sha(p)!=row.get('sha256'):f.append('FROZEN_ARTIFACT_SHA_DRIFT:'+row.get('role','UNKNOWN'))
 if candidate.get('interface_version')!='v1':f.append('INTERFACE_VERSION_MISMATCH')
 expected=m.get('capability_matrix') or {}
 if candidate.get('allowed_future_business_writes_if_separately_authorized')!=expected.get('allowed_future_business_writes_if_separately_authorized'):f.append('BUSINESS_WRITE_SET_EXTENSION_OR_CHANGE')
 if candidate.get('allowed_protocol_metadata_if_separately_authorized')!=expected.get('allowed_protocol_metadata_if_separately_authorized'):f.append('PROTOCOL_METADATA_EXTENSION_OR_CHANGE')
 if candidate.get('network') is not False:f.append('NETWORK_CAPABILITY_FORBIDDEN')
 if candidate.get('subprocess') is not False:f.append('SUBPROCESS_CAPABILITY_FORBIDDEN')
 if candidate.get('rollback')!='COMPLETE_BOTH_OR_RESTORE_BOTH':f.append('ROLLBACK_RECOVERY_WEAKENED')
 if candidate.get('inherit_v41_tests_as_authority') is not False:f.append('V41_TEST_AUTHORITY_INHERITANCE_FORBIDDEN')
 exact={'interface_version','allowed_future_business_writes_if_separately_authorized','allowed_protocol_metadata_if_separately_authorized','network','subprocess','rollback','inherit_v41_tests_as_authority'}
 if set(candidate)!=exact:f.append('UNAUTHORIZED_EXTENSION_FIELD')
 return {'schema':'qingshan.e40.u18.v43.interface_freeze_verification.v1','status':'INTERFACE_V1_COMPATIBLE_NO_EXECUTION' if not f else 'INTERFACE_V1_COMPATIBILITY_FAIL_CLOSED','failures':sorted(set(f)),'execution_authorized':False,'executor_implemented':False,'requires_new_version_on_change':True,'requires_new_independent_security_audit':True,'requires_fresh_per_bundle_authority':True,'maximum_new_submissions':0}
