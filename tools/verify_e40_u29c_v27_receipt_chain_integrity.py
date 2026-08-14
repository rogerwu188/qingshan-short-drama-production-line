#!/usr/bin/env python3
"""Read-only verification of the V23-V26 receipt-chain manifest."""
from __future__ import annotations
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
MANIFEST=ROOT/"qa/e40_preproduction_20260808/u29c_v27_receipt_chain_integrity_v1/E40_U29C_V27_V23_TO_V26_RECEIPT_CHAIN_MANIFEST_V1.json";MANIFEST_SHA="081ce2fffb117615bf57eca5f8b208c9f1a74f79f0d9487d90471f0718f48d89"
REPORT=MANIFEST.parent/"E40_U29C_V27_V23_TO_V26_RECEIPT_CHAIN_INTEGRITY_AUDIT_V1.json"
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 raw=MANIFEST.read_bytes();manifest=json.loads(raw);before=[];fail=[]
 if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:fail.append('MANIFEST_SHA_MISMATCH')
 for e in manifest['bindings']:
  p=ROOT/e['path'];actual=dig(p) if p.is_file() else None;before.append({'path':e['path'],'expected':e['sha256'],'actual':actual,'match':actual==e['sha256']})
 if len(before)!=10 or not all(x['match'] for x in before):fail.append('CHAIN_NOT_10_OF_10')
 receipts=sorted(writer.RECEIPT_ROOT.glob('*.recovered-success-receipt.json'));valid=[]
 for p in receipts:
  try:r=writer.validate_restart(p);valid.append({'receipt':str(p.relative_to(ROOT)),'output':r['output'],'valid':True})
  except Exception as e:valid.append({'receipt':str(p.relative_to(ROOT)),'valid':False,'error':type(e).__name__})
 if len(valid)!=3 or not all(x['valid'] for x in valid):fail.append('CURRENT_BINDINGS_NOT_3_OF_3')
 allow=json.loads((ROOT/'qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_HISTORICAL_UNPAIRED_OUTPUT_ALLOWLIST_V1.json').read_text());entry=allow['entries'];allow_valid=len(entry)==1 and dig(ROOT/entry[0]['path'])==entry[0]['sha256'] and allow['status']=='FAIL_CLOSED_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE'
 if not allow_valid:fail.append('ALLOWLIST_INVALID')
 residue={'data':sorted(p.name for p in recovery.FINAL_ROOT.iterdir() if p.name.startswith('.u29c-v20-hidden-')),'receipt':sorted(p.name for p in writer.RECEIPT_ROOT.iterdir() if p.name.startswith('.u29c-v23-receipt-hidden-')),'stage':sorted(p.name for p in recovery.STAGING_ROOT.iterdir())}
 if any(residue.values()):fail.append('RESIDUE')
 after=[{'path':x['path'],'actual':dig(ROOT/x['path'])} for x in before]
 if any(a['actual']!=b['actual'] for a,b in zip(after,before)):fail.append('CHAIN_MUTATION')
 status='PASS_V23_TO_V26_CHAIN_10_OF_10_CURRENT_3_OF_3_ADMISSION_CLOSED_ZERO_RESIDUE' if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v27.receipt_chain_integrity_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'manifest':str(MANIFEST.relative_to(ROOT)),'manifest_sha256':MANIFEST_SHA,'chain_binding_count':len(before),'chain_match_count':sum(x['match'] for x in before),'bindings_before':before,'bindings_after':after,'current_receipt_count':len(valid),'current_valid_binding_count':sum(x['valid'] for x in valid),'current_bindings':valid,'allowlist_entry_count':len(entry),'allowlist_valid_non_admitted':allow_valid,'residue':residue,'admission_closed':True,'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V28 pinned full-chain verifier regression.'};fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'chain':sum(x['match'] for x in before),'receipts':sum(x['valid'] for x in valid),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
