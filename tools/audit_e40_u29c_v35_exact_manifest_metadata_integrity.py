#!/usr/bin/env python3
"""Read-only metadata integrity audit for the V33 exact closed-set manifest."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
MANIFEST=ROOT/'qa/e40_preproduction_20260808/u29c_v33_closed_set_manifest_integrity_v1/E40_U29C_V33_EXACT_CLOSED_SET_MANIFEST_V1.json';MANIFEST_SHA='7a0e3cd56e2bf6d4bbeaef4222dae23333054ffa7e9c75d1b92e5c468feb0a42'
RUNNER=ROOT/'tools/run_e40_u29c_v34_pinned_exact_closed_set_manifest_regression.py';RUNNER_SHA='da4d67673986d095c42e1bf5fbdbfc2c4659a88385441b31fed1acf7f2c60f7f'
MATRIX=ROOT/'qa/e40_preproduction_20260808/u29c_v34_pinned_manifest_regression_v1/E40_U29C_V34_PINNED_EXACT_CLOSED_SET_MANIFEST_REGRESSION_MATRIX_V1.json';MATRIX_SHA='802300942a08cd2a972f0c021b6bc2181f3fc181c4cb9d67eee5098fcebfa14a'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v35_manifest_metadata_integrity_v1/E40_U29C_V35_EXACT_MANIFEST_METADATA_INTEGRITY_SPEC_V1.json';SPEC_SHA='1016d57a89f6e5eb89387d5ed794dd6f18f1f2efd91fea840e28e0e0c6c73195'
REPORT=SPEC.parent/'E40_U29C_V35_EXACT_MANIFEST_METADATA_INTEGRITY_AUDIT_V1.json';PASS='PASS_17_OF_17_MANIFEST_METADATA_CANONICAL_UNIQUE_CONTAINED_ORDERED_NO_MUTATION_NO_SUBMIT'
RECEIPT_ROOT='qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipts_v1/'
OUTPUT_ROOT='qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_final_output_v1/'
VOCAB={'BOUND_CURRENT_RECEIPT','BOUND_CURRENT_RECOVERED_EVIDENCE','HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE','DOCUMENTED_LOCAL_HARNESS_EVIDENCE'}
EXPECTED={'BOUND_CURRENT_RECEIPT':3,'BOUND_CURRENT_RECOVERED_EVIDENCE':3,'HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE':1,'DOCUMENTED_LOCAL_HARNESS_EVIDENCE':10}
HEX=re.compile(r'^[0-9a-f]{64}$')
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 rows=[]
 for flag in ('--manifest','--runner','--matrix','--spec'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_audit':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V35 manifest metadata audit; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(MANIFEST,MANIFEST_SHA),(RUNNER,RUNNER_SHA),(MATRIX,MATRIX_SHA),(SPEC,SPEC_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':matches}));return 1
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_audit'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 manifest=json.loads(MANIFEST.read_text());bindings=manifest.get('bindings',[]);rows=[];paths=[]
 for index,b in enumerate(bindings):
  raw=b.get('path');pure=PurePosixPath(raw) if isinstance(raw,str) else None;parts=pure.parts if pure else ();canonical=isinstance(raw,str) and raw==pure.as_posix() and not pure.is_absolute() and raw and '\\' not in raw and all(x not in ('','.','..') for x in parts)
  root='RECEIPT_ROOT' if isinstance(raw,str) and raw.startswith(RECEIPT_ROOT) else 'OUTPUT_ROOT' if isinstance(raw,str) and raw.startswith(OUTPUT_ROOT) else None
  contained=root is not None and (ROOT/raw).resolve().parent==Path(ROOT/(RECEIPT_ROOT if root=='RECEIPT_ROOT' else OUTPUT_ROOT)).resolve()
  sha_ok=isinstance(b.get('sha256'),str) and HEX.fullmatch(b['sha256']) is not None
  vocab_ok=b.get('classification') in VOCAB
  semantic_root=(b.get('classification')=='BOUND_CURRENT_RECEIPT' and root=='RECEIPT_ROOT') or (b.get('classification')!='BOUND_CURRENT_RECEIPT' and vocab_ok and root=='OUTPUT_ROOT')
  row={'index':index,'path':raw,'classification':b.get('classification'),'canonical_repository_relative':canonical,'exact_root':root,'root_contained':contained,'sha256_format_valid':sha_ok,'classification_in_vocabulary':vocab_ok,'classification_root_semantics_valid':semantic_root}
  row['metadata_valid']=all((canonical,contained,sha_ok,vocab_ok,semantic_root));rows.append(row);paths.append(raw)
 if len(rows)!=17 or not all(x['metadata_valid'] for x in rows):fail.append('METADATA_NOT_VALID_17_OF_17')
 unique=len(paths)==len(set(paths))==17
 if not unique:fail.append('PATHS_NOT_UNIQUE')
 counts=dict(Counter(b.get('classification') for b in bindings));counts_ok=counts==EXPECTED==manifest.get('classification_counts')
 if not counts_ok:fail.append('CLASSIFICATION_COUNTS_MISMATCH')
 receipt_paths=[p for p in paths if p.startswith(RECEIPT_ROOT)];output_paths=[p for p in paths if p.startswith(OUTPUT_ROOT)];order_ok=paths==sorted(receipt_paths)+sorted(output_paths) and len(receipt_paths)==3 and len(output_paths)==14
 if not order_ok:fail.append('DETERMINISTIC_ORDER_MISMATCH')
 schema_ok=manifest.get('schema')=='qingshan.e40.u29c.v33.exact_closed_set_manifest.v1' and manifest.get('episode')=='E40' and manifest.get('unit_id')=='U29C'
 policy_ok=manifest.get('execution_permitted') is False and manifest.get('provider_post_allowed') is False and manifest.get('admission_closed') is True and manifest.get('blind_replay_allowed') is False
 if not schema_ok:fail.append('MANIFEST_IDENTITY_METADATA_MISMATCH')
 if not policy_ok:fail.append('MANIFEST_POLICY_NOT_CLOSED')
 after=[ident(p) for p,_ in pins]
 if before!=after:fail.append('AUTHORITY_IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v35.exact_manifest_metadata_integrity_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(matches),'pins_after':after,'binding_count':len(rows),'metadata_valid_count':sum(x['metadata_valid'] for x in rows),'bindings':rows,'path_unique_count':len(set(paths)),'paths_unique_17_of_17':unique,'receipt_path_count':len(receipt_paths),'output_path_count':len(output_paths),'classification_vocabulary':sorted(VOCAB),'classification_counts':counts,'classification_counts_exact':counts_ok,'deterministic_receipts_then_outputs_lexical_order':order_ok,'schema_identity_valid':schema_ok,'admission_closed':policy_ok,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_audit'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V36 pinned manifest metadata regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'metadata':sum(x['metadata_valid'] for x in rows),'unique':len(set(paths)),'order':order_ok,'substitution_negatives':sum(x['rejected_before_audit'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
