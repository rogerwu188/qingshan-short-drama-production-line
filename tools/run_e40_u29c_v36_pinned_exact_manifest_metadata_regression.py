#!/usr/bin/env python3
"""Pinned V36 regression over V35 manifest metadata integrity."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
AUDITOR=ROOT/'tools/audit_e40_u29c_v35_exact_manifest_metadata_integrity.py';AUDITOR_SHA='3f5039186e90a58b43aad7afe31f2ac640ef96d38d9df9df44a9d16a6b11ee7d'
AUDIT=ROOT/'qa/e40_preproduction_20260808/u29c_v35_manifest_metadata_integrity_v1/E40_U29C_V35_EXACT_MANIFEST_METADATA_INTEGRITY_AUDIT_V1.json';AUDIT_SHA='60b97ba733128d0437e256df32ee244833a70def7d665fe16c024b3e24bd68a9'
MANIFEST=ROOT/'qa/e40_preproduction_20260808/u29c_v33_closed_set_manifest_integrity_v1/E40_U29C_V33_EXACT_CLOSED_SET_MANIFEST_V1.json';MANIFEST_SHA='7a0e3cd56e2bf6d4bbeaef4222dae23333054ffa7e9c75d1b92e5c468feb0a42'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v36_pinned_metadata_regression_v1/E40_U29C_V36_PINNED_EXACT_MANIFEST_METADATA_REGRESSION_SPEC_V1.json';SPEC_SHA='d09288a7e75e25ae48d7b42584478d32f2943f909b6fcdc7d3239bf37ab6b388'
CANON=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CANON_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b'
CANON_MANIFEST=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';CANON_MANIFEST_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1'
REPORT=SPEC.parent/'E40_U29C_V36_PINNED_EXACT_MANIFEST_METADATA_REGRESSION_MATRIX_V1.json';PASS='PASS_PINNED_17_OF_17_METADATA_EXACT_V35_SNAPSHOT_CANONICAL_BOUND_NO_MUTATION_NO_SUBMIT'
RECEIPT_ROOT='qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipts_v1/';OUTPUT_ROOT='qa/e40_preproduction_20260808/u29c_v20_post_link_recovery_final_output_v1/'
VOCAB={'BOUND_CURRENT_RECEIPT','BOUND_CURRENT_RECOVERED_EVIDENCE','HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE','DOCUMENTED_LOCAL_HARNESS_EVIDENCE'};EXPECTED={'BOUND_CURRENT_RECEIPT':3,'BOUND_CURRENT_RECOVERED_EVIDENCE':3,'HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE':1,'DOCUMENTED_LOCAL_HARNESS_EVIDENCE':10};HEX=re.compile(r'^[0-9a-f]{64}$')
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 rows=[]
 for flag in ('--auditor','--audit','--manifest','--spec','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V36 metadata regression; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(AUDITOR,AUDITOR_SHA),(AUDIT,AUDIT_SHA),(MANIFEST,MANIFEST_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(CANON_MANIFEST,CANON_MANIFEST_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':matches}));return 1
 authority=json.loads(AUDIT.read_text());authority_ok=authority.get('status')=='PASS_17_OF_17_MANIFEST_METADATA_CANONICAL_UNIQUE_CONTAINED_ORDERED_NO_MUTATION_NO_SUBMIT' and authority.get('metadata_valid_count')==17 and authority.get('paths_unique_17_of_17') is True and authority.get('deterministic_receipts_then_outputs_lexical_order') is True and authority.get('failures')==[] and authority.get('execution_permitted') is False
 if not authority_ok:fail.append('V35_AUTHORITY_NOT_PASS_CLOSED')
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 manifest=json.loads(MANIFEST.read_text());bindings=manifest.get('bindings',[]);rows=[];paths=[]
 for index,b in enumerate(bindings):
  raw=b.get('path');pure=PurePosixPath(raw) if isinstance(raw,str) else None;parts=pure.parts if pure else ();canonical=isinstance(raw,str) and raw==pure.as_posix() and not pure.is_absolute() and raw and '\\' not in raw and all(x not in ('','.','..') for x in parts)
  root='RECEIPT_ROOT' if isinstance(raw,str) and raw.startswith(RECEIPT_ROOT) else 'OUTPUT_ROOT' if isinstance(raw,str) and raw.startswith(OUTPUT_ROOT) else None;contained=root is not None and (ROOT/raw).resolve().parent==Path(ROOT/(RECEIPT_ROOT if root=='RECEIPT_ROOT' else OUTPUT_ROOT)).resolve();sha_ok=isinstance(b.get('sha256'),str) and HEX.fullmatch(b['sha256']) is not None;vocab=b.get('classification') in VOCAB;semantics=(b.get('classification')=='BOUND_CURRENT_RECEIPT' and root=='RECEIPT_ROOT') or (b.get('classification')!='BOUND_CURRENT_RECEIPT' and vocab and root=='OUTPUT_ROOT')
  row={'index':index,'path':raw,'classification':b.get('classification'),'canonical_repository_relative':canonical,'exact_root':root,'root_contained':contained,'sha256_format_valid':sha_ok,'classification_in_vocabulary':vocab,'classification_root_semantics_valid':semantics};row['metadata_valid']=all((canonical,contained,sha_ok,vocab,semantics));rows.append(row);paths.append(raw)
 if len(rows)!=17 or not all(x['metadata_valid'] for x in rows):fail.append('METADATA_NOT_17_OF_17')
 unique=len(paths)==len(set(paths))==17;counts=dict(Counter(b.get('classification') for b in bindings));counts_ok=counts==EXPECTED==manifest.get('classification_counts');rp=[p for p in paths if p.startswith(RECEIPT_ROOT)];op=[p for p in paths if p.startswith(OUTPUT_ROOT)];order=paths==sorted(rp)+sorted(op) and len(rp)==3 and len(op)==14;snapshot=rows==authority.get('bindings')
 if not unique:fail.append('PATHS_NOT_UNIQUE')
 if not counts_ok:fail.append('COUNTS_MISMATCH')
 if not order:fail.append('ORDER_MISMATCH')
 if not snapshot:fail.append('METADATA_DRIFT_FROM_V35')
 policy=manifest.get('execution_permitted') is False and manifest.get('provider_post_allowed') is False and manifest.get('admission_closed') is True and manifest.get('blind_replay_allowed') is False
 if not policy:fail.append('ADMISSION_NOT_CLOSED')
 after=[ident(p) for p,_ in pins]
 if before!=after:fail.append('PIN_IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v36.pinned_exact_manifest_metadata_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(matches),'pins_after':after,'canonical_script_sha256':CANON_SHA,'canonical_manifest_sha256':CANON_MANIFEST_SHA,'v35_authority_valid':authority_ok,'binding_count':len(rows),'metadata_valid_count':sum(x['metadata_valid'] for x in rows),'bindings':rows,'paths_unique_17_of_17':unique,'classification_counts':counts,'classification_counts_exact':counts_ok,'deterministic_order_exact':order,'v35_metadata_snapshot_exact':snapshot,'admission_closed':policy,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_verification'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V37 canonical-bound receipt-chain authority audit.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'metadata':sum(x['metadata_valid'] for x in rows),'v35_snapshot_exact':snapshot,'pins':sum(matches),'substitution_negatives':sum(x['rejected_before_verification'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
