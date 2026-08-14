#!/usr/bin/env python3
"""Verify the independent V33 exact closed-set manifest read-only."""
from __future__ import annotations
import argparse,hashlib,json,os,stat,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
RUNNER=ROOT/'tools/run_e40_u29c_v32_pinned_closed_set_directory_inventory_regression.py';RUNNER_SHA='6b6ec825f7956bccff06463a4a32d83da371161062fb910c2915de14c34cb513'
MATRIX=ROOT/'qa/e40_preproduction_20260808/u29c_v32_pinned_directory_inventory_regression_v1/E40_U29C_V32_PINNED_CLOSED_SET_DIRECTORY_INVENTORY_REGRESSION_MATRIX_V1.json';MATRIX_SHA='6ff4188d2a24a788f29cc8930d4f8647971969bd0d9524050be7777773cc2b1f'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v33_closed_set_manifest_integrity_v1/E40_U29C_V33_EXACT_CLOSED_SET_MANIFEST_INTEGRITY_SPEC_V1.json';SPEC_SHA='51669ddefa2c6c09f178f22d30a3acaea787bd88b9934e25f0bc97f8be46a4f0'
MANIFEST=SPEC.parent/'E40_U29C_V33_EXACT_CLOSED_SET_MANIFEST_V1.json';MANIFEST_SHA='7a0e3cd56e2bf6d4bbeaef4222dae23333054ffa7e9c75d1b92e5c468feb0a42'
REPORT=SPEC.parent/'E40_U29C_V33_EXACT_CLOSED_SET_MANIFEST_INTEGRITY_AUDIT_V1.json';PASS='PASS_EXACT_MANIFEST_17_OF_17_CLOSED_SET_CLASSIFICATIONS_NO_MUTATION_NO_SUBMIT'
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':dig(p) if stat.S_ISREG(s.st_mode) else None,'device':s.st_dev,'inode':s.st_ino,'mode':oct(stat.S_IMODE(s.st_mode)),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'regular_file':stat.S_ISREG(s.st_mode),'symlink':stat.S_ISLNK(s.st_mode)}
def negs():
 rows=[]
 for flag in ('--manifest','--receipt-root','--output-root'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);rows.append({'argument':flag,'exit_code':p.returncode,'rejected_before_verification':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(description='Fixed V33 manifest verifier; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 fail=[];pins=[(RUNNER,RUNNER_SHA),(MATRIX,MATRIX_SHA),(SPEC,SPEC_SHA),(MANIFEST,MANIFEST_SHA)];pb=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(pb,pins)]
 if not all(matches):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':matches}));return 1
 negatives=negs()
 if REPORT.exists() or not all(x['rejected_before_verification'] and not x['report_created'] for x in negatives):fail.append('SUBSTITUTION_NOT_REJECTED')
 manifest=json.loads(MANIFEST.read_text());bindings=manifest.get('bindings',[]);paths=[ROOT/x['path'] for x in bindings];before=[ident(p) for p in paths];rows=[]
 for b,x in zip(bindings,before):
  exact=x['sha256']==b['sha256'] and x['regular_file'] and not x['symlink'] and x['mode']=='0o600' and x['nlink']==1
  rows.append({'path':b['path'],'classification':b['classification'],'expected_sha256':b['sha256'],'actual_sha256':x['sha256'],'exact':exact})
 if len(rows)!=17 or not all(x['exact'] for x in rows):fail.append('MANIFEST_NOT_17_OF_17')
 observed=set(p for root in (writer.RECEIPT_ROOT,recovery.FINAL_ROOT) for p in root.iterdir());closed=observed==set(paths)
 if not closed:fail.append('LIVE_DIRECTORY_SET_NOT_EXACT_MANIFEST')
 counts=Counter(x['classification'] for x in bindings);counts_exact=dict(counts)==manifest.get('classification_counts')
 if not counts_exact:fail.append('CLASSIFICATION_COUNTS_MISMATCH')
 receipt_paths=[ROOT/x['path'] for x in bindings if x['classification']=='BOUND_CURRENT_RECEIPT'];bound_outputs={Path(x['path']).name for x in bindings if x['classification']=='BOUND_CURRENT_RECOVERED_EVIDENCE'};restart={Path(writer.validate_restart(p)['output']).name for p in receipt_paths};restart_exact=restart==bound_outputs and len(restart)==3
 if not restart_exact:fail.append('RESTART_BINDINGS_NOT_EXACT_3_OF_3')
 closed_policy=manifest.get('execution_permitted') is False and manifest.get('provider_post_allowed') is False and manifest.get('admission_closed') is True and manifest.get('blind_replay_allowed') is False
 if not closed_policy:fail.append('MANIFEST_ADMISSION_NOT_CLOSED')
 after=[ident(p) for p in paths];pa=[ident(p) for p,_ in pins]
 if before!=after:fail.append('ENTRY_IDENTITY_MUTATION')
 if pb!=pa:fail.append('PIN_IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v33.exact_closed_set_manifest_integrity_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':pb,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(matches),'pins_after':pa,'manifest':str(MANIFEST.relative_to(ROOT)),'manifest_sha256':MANIFEST_SHA,'manifest_binding_count':len(rows),'manifest_match_count':sum(x['exact'] for x in rows),'bindings':rows,'live_directory_set_exact_manifest':closed,'classification_counts':dict(counts),'classification_counts_exact':counts_exact,'restart_binding_set_exact_3_of_3':restart_exact,'admission_closed':closed_policy,'entry_identity_before':before,'entry_identity_after':after,'substitution_negatives':negatives,'substitution_negative_count':sum(x['rejected_before_verification'] for x in negatives),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V34 pinned exact-manifest regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'bindings':sum(x['exact'] for x in rows),'closed_set':closed,'substitution_negatives':sum(x['rejected_before_verification'] for x in negatives),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
