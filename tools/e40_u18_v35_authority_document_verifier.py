#!/usr/bin/env python3
"""Offline format/binding verifier; never treats a document as executable authority."""
from __future__ import annotations
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HEX=re.compile(r'^[0-9a-f]{64}$');NONCE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$')
REQUIRED={'schema','episode','unit_id','authority_scope','bundle_sha256','v29_proposal_sha256','explicit_decision_sha256','branch','target_path','nonce','canonical_script_sha256','canonical_manifest_sha256','work_queue_sha256','formal_memory_sha256','nonce_ledger_sha256','issued_at','expires_at','single_use','consumed','signer'}
PINS={'canonical_script_sha256':'140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b','canonical_manifest_sha256':'773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1','work_queue_sha256':'ddeb34ddb5a5b8ff80ac7cf68a5b21557f6d524006f5496e79fb08cca3977b43','formal_memory_sha256':'e257682e39b941d8b994beb238591268ad9c059b2cbfc9787f9330151844a50b'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dt(v):return datetime.fromisoformat(v.replace('Z','+00:00')) if isinstance(v,str) else None
def verify(doc_path:Path,bundle_path:Path,ledger_path:Path,now:datetime|None=None,root:Path=ROOT):
 f=[];now=now or datetime.now(timezone.utc)
 try:d=json.loads(doc_path.read_text());b=json.loads(bundle_path.read_text());l=json.loads(ledger_path.read_text())
 except Exception:return {'status':'INVALID_AUTHORITY_DOCUMENT','failures':['INPUT_MISSING_OR_INVALID'],'execution_authorized':False}
 if set(d)!=REQUIRED:f.append('EXACT_FIELD_SET_REQUIRED')
 if d.get('schema')!='qingshan.e40.u18.v35.one_time_root_persistence_authorization.v1' or d.get('episode')!='E40' or d.get('unit_id')!='U18':f.append('SCHEMA_EPISODE_UNIT_MISMATCH')
 for k in ['bundle_sha256','v29_proposal_sha256','explicit_decision_sha256','nonce_ledger_sha256']:
  if not isinstance(d.get(k),str) or not HEX.fullmatch(d[k]):f.append(f'{k.upper()}_INVALID')
 if any(d.get(k)!=v for k,v in PINS.items()):f.append('CANONICAL_QUEUE_MEMORY_PIN_MISMATCH')
 if d.get('single_use') is not True or d.get('consumed') is not False:f.append('SINGLE_USE_UNCONSUMED_REQUIRED')
 signer=d.get('signer') or {}
 if set(signer)!={'role','identity'} or signer.get('role')!='ROOT_PERSISTENCE_AUTHORIZER' or not str(signer.get('identity') or '').strip():f.append('SIGNER_ROLE_OR_IDENTITY_INVALID')
 try:i,e=dt(d.get('issued_at')),dt(d.get('expires_at'))
 except Exception:i=e=None
 if not i or not e or not i.tzinfo or not e.tzinfo or not (i<=now<e) or e<=i:f.append('AUTHORITY_EXPIRED_OR_TIME_INVALID')
 if not isinstance(d.get('nonce'),str) or not NONCE.fullmatch(d['nonce']):f.append('NONCE_INVALID')
 if sha(ledger_path)!=d.get('nonce_ledger_sha256') or sum(1 for x in l.get('used_nonces',[]) if x==d.get('nonce'))!=0:f.append('NONCE_LEDGER_STALE_OR_REPLAYED')
 if b.get('schema')!='qingshan.e40.u18.v31.atomic_persistence_bundle.v1' or b.get('status')!='ATOMIC_PERSISTENCE_BUNDLE_READY_DRY_RUN_ONLY':f.append('V31_BUNDLE_INVALID')
 locks=b.get('locks') or {}
 if d.get('bundle_sha256')!=b.get('bundle_sha256') or d.get('v29_proposal_sha256')!=locks.get('v29_proposal_sha256') or d.get('explicit_decision_sha256')!=locks.get('explicit_decision_sha256') or d.get('nonce')!=b.get('nonce') or d.get('nonce_ledger_sha256')!=locks.get('nonce_ledger_sha256'):f.append('BUNDLE_PROPOSAL_DECISION_NONCE_BINDING_MISMATCH')
 if d.get('branch')!=b.get('branch') or d.get('target_path')!=locks.get('target_path'):f.append('BRANCH_OR_TARGET_MISMATCH')
 expected_scope='PERSIST_AUTHORIZATION_TARGET_ONLY' if b.get('branch')=='AUTHORIZATION' else 'PERSIST_FORMAL_MEMORY_EVENT_ONLY' if b.get('branch')=='FORMAL_MEMORY_UPDATE_EVENT' else None
 if d.get('authority_scope')!=expected_scope:f.append('GENERIC_OR_OTHER_ACTION_AUTHORITY_REJECTED')
 return {'schema':'qingshan.e40.u18.v35.authority_document_verification.v1','status':'VALID_AUTHORITY_DOCUMENT_NOT_EXECUTED' if not f else 'INVALID_AUTHORITY_DOCUMENT','failures':sorted(set(f)),'document_sha256':sha(doc_path),'bundle_file_sha256':sha(bundle_path),'execution_authorized':False,'nonce_registered':False,'target_written':False,'maximum_new_submissions':0}
def main():
 p=argparse.ArgumentParser();p.add_argument('--authority-document',type=Path,required=True);p.add_argument('--v31-bundle',type=Path,required=True);p.add_argument('--nonce-ledger',type=Path,required=True);p.add_argument('--out',type=Path);a=p.parse_args();r=verify(a.authority_document,a.v31_bundle,a.nonce_ledger);s=json.dumps(r,ensure_ascii=False,indent=2)+'\n';a.out.write_text(s) if a.out else print(s,end='');return 0 if r['status'].startswith('VALID_') else 3
if __name__=='__main__':raise SystemExit(main())
