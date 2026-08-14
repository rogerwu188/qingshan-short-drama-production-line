#!/usr/bin/env python3
"""Pinned V32 regression for the V31 closed-set directory inventory."""
from __future__ import annotations
import argparse, hashlib, json, os, stat, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
import audit_e40_u29c_v31_receipt_output_directory_entry_inventory as v31
V31_AUDITOR=ROOT/'tools/audit_e40_u29c_v31_receipt_output_directory_entry_inventory.py';V31_AUDITOR_SHA='2cd31090498533fc248b1f9d118234f11f72c20fde808c604f942a06a28eb367'
V31_AUDIT=ROOT/'qa/e40_preproduction_20260808/u29c_v31_directory_entry_inventory_v1/E40_U29C_V31_RECEIPT_OUTPUT_DIRECTORY_ENTRY_INVENTORY_AUDIT_V1.json';V31_AUDIT_SHA='471230d1e1f3c6fd6f715f9aa2212e86833d429eba189fb2b1d46b53fcee74dd'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v32_pinned_directory_inventory_regression_v1/E40_U29C_V32_PINNED_CLOSED_SET_DIRECTORY_INVENTORY_REGRESSION_SPEC_V1.json';SPEC_SHA='52fc3689a77f131074d98f6d068f12d2499ffa1bf3d5af00cddc75f96e2b5506'
REPORT=SPEC.parent/'E40_U29C_V32_PINNED_CLOSED_SET_DIRECTORY_INVENTORY_REGRESSION_MATRIX_V1.json'
PASS='PASS_PINNED_CLOSED_SET_3_RECEIPTS_14_OUTPUTS_17_EXACT_SNAPSHOT_NO_MUTATION_NO_SUBMIT'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':digest(p) if stat.S_ISREG(s.st_mode) else None,'device':s.st_dev,'inode':s.st_ino,'mode':oct(stat.S_IMODE(s.st_mode)),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'regular_file':stat.S_ISREG(s.st_mode),'directory':stat.S_ISDIR(s.st_mode),'symlink':stat.S_ISLNK(s.st_mode)}
def negatives():
 rows=[]
 for flag in ('--auditor','--audit','--spec','--receipt-root','--output-root','--classification'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False)
  rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V32 closed-set regression; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(V31_AUDITOR,V31_AUDITOR_SHA),(V31_AUDIT,V31_AUDIT_SHA),(SPEC,SPEC_SHA)];pb=[ident(p) for p,_ in pins];pm=[x['sha256']==e for x,(_,e) in zip(pb,pins)]
 if not all(pm):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':pm}));return 1
 authority=json.loads(V31_AUDIT.read_text());authority_ok=authority.get('status')=='PASS_CLOSED_SET_3_RECEIPTS_14_OUTPUTS_ALL_ENTRIES_CLASSIFIED_NO_MUTATION_NO_SUBMIT' and authority.get('closed_set_exact') is True and authority.get('current_binding_set_exact_3_of_3') is True and authority.get('failures')==[] and authority.get('execution_permitted') is False
 if not authority_ok:fail.append('V31_AUTHORITY_NOT_PASS_CLOSED')
 neg=negatives()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in neg):fail.append('SUBSTITUTION_NOT_REJECTED')
 receipts=sorted(writer.RECEIPT_ROOT.iterdir());outputs=sorted(recovery.FINAL_ROOT.iterdir());paths=receipts+outputs;before=[ident(p) for p in paths];roots_before=[ident(writer.RECEIPT_ROOT),ident(recovery.FINAL_ROOT)]
 receipt_rows=[]
 for p in receipts:
  x=ident(p);exp=v31.EXPECTED_RECEIPTS.get(p.name);ok=exp is not None and x['sha256']==exp and x['regular_file'] and not x['symlink'] and x['mode']=='0o600' and x['nlink']==1 and not p.name.startswith('.')
  receipt_rows.append({**x,'classification':'BOUND_CURRENT_RECEIPT' if exp else 'FORBIDDEN_UNEXPECTED_RECEIPT','expected_sha256':exp,'exact':ok})
 output_rows=[]
 for p in outputs:
  x=ident(p);exp=v31.EXPECTED_OUTPUTS.get(p.name);kind,sha=exp if exp else ('FORBIDDEN_UNCLASSIFIED_OUTPUT',None);ok=exp is not None and x['sha256']==sha and x['regular_file'] and not x['symlink'] and x['mode']=='0o600' and x['nlink']==1 and not p.name.startswith('.')
  output_rows.append({**x,'classification':kind,'expected_sha256':sha,'exact':ok})
 closed={p.name for p in receipts}==set(v31.EXPECTED_RECEIPTS) and {p.name for p in outputs}==set(v31.EXPECTED_OUTPUTS) and all(x['exact'] for x in receipt_rows+output_rows)
 if not closed:fail.append('CLOSED_SET_NOT_EXACT')
 bound={n for n,(k,_) in v31.EXPECTED_OUTPUTS.items() if k=='BOUND_CURRENT_RECOVERED_EVIDENCE'};restart={Path(writer.validate_restart(p)['output']).name for p in receipts};binding=restart==bound and len(restart)==3
 if not binding:fail.append('BINDING_SET_NOT_3_OF_3')
 counts={}
 for x in receipt_rows+output_rows:counts[x['classification']]=counts.get(x['classification'],0)+1
 expected={'BOUND_CURRENT_RECEIPT':3,'DOCUMENTED_LOCAL_HARNESS_EVIDENCE':10,'HISTORICAL_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE':1,'BOUND_CURRENT_RECOVERED_EVIDENCE':3}
 if counts!=expected:fail.append('CLASSIFICATION_COUNTS_MISMATCH')
 snapshot=roots_before==authority.get('root_identity_after') and before==authority.get('entry_identity_after')
 if not snapshot:fail.append('LIVE_IDENTITY_DRIFT_FROM_V31')
 after=[ident(p) for p in paths];roots_after=[ident(writer.RECEIPT_ROOT),ident(recovery.FINAL_ROOT)];pa=[ident(p) for p,_ in pins]
 if before!=after:fail.append('ENTRY_MUTATION')
 if roots_before!=roots_after:fail.append('ROOT_MUTATION')
 if pb!=pa:fail.append('PIN_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v32.pinned_closed_set_directory_inventory_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':pb,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(pm),'pins_after':pa,'v31_authority_valid':authority_ok,'receipt_entry_count':len(receipt_rows),'output_entry_count':len(output_rows),'total_entry_count':len(paths),'receipt_entries':receipt_rows,'output_entries':output_rows,'classification_counts':counts,'expected_classification_counts':expected,'closed_set_exact':closed,'current_binding_set_exact_3_of_3':binding,'v31_after_snapshot_exact':snapshot,'root_identity_before':roots_before,'root_identity_after':roots_after,'entry_identity_before':before,'entry_identity_after':after,'hidden_entry_count':sum(p.name.startswith('.') for p in paths),'symlink_entry_count':sum(x['symlink'] for x in receipt_rows+output_rows),'nonregular_entry_count':sum(not x['regular_file'] for x in receipt_rows+output_rows),'unclassified_entry_count':sum(x['classification'].startswith('FORBIDDEN_') for x in receipt_rows+output_rows),'substitution_negatives':neg,'substitution_negative_count':sum(x['rejected_before_verification'] for x in neg),'admission_closed':True,'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V33 exact closed-set manifest integrity audit.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'classified':len(paths),'v31_snapshot_exact':snapshot,'substitution_negatives':sum(x['rejected_before_verification'] for x in neg),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
