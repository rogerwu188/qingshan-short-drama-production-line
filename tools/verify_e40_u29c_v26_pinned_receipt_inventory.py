#!/usr/bin/env python3
"""Pinned read-only verifier for V25 receipt inventory and exact allowlist."""
from __future__ import annotations
import hashlib,json,os,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
V25_TOOL=ROOT/"tools/audit_e40_u29c_v25_persisted_receipt_inventory_integrity.py";V25_TOOL_SHA="12eeaaec8cb10d8b29aadb41aa85df77b3ad90cf131d6e23a8f2ca62b1d6ed15"
V25=ROOT/"qa/e40_preproduction_20260808/u29c_v25_persisted_receipt_inventory_integrity_v1/E40_U29C_V25_PERSISTED_RECEIPT_INVENTORY_INTEGRITY_AUDIT_V1.json";V25_SHA="7b07147eaabad8c304814a0b6a9fb8914c39ab8a10012b99c79565e9ec100950"
ALLOW=ROOT/"qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_HISTORICAL_UNPAIRED_OUTPUT_ALLOWLIST_V1.json";ALLOW_SHA="5e25fbc2c9aa33865e4679b2bebc330522cf28925446daf6c684859fa60ab863"
SPEC=ROOT/"qa/e40_preproduction_20260808/u29c_v26_pinned_receipt_inventory_v1/E40_U29C_V26_PINNED_RECEIPT_INVENTORY_AND_UNPAIRED_ALLOWLIST_SPEC_V1.json";SPEC_SHA="1ae08a8d94b13bfe6fec9de14a31f66aff79e05779767ef63374795244e7f04c"
REPORT=SPEC.parent/"E40_U29C_V26_PINNED_RECEIPT_INVENTORY_VERIFICATION_V1.json"
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[V25_TOOL,V25,ALLOW,SPEC];exp=[V25_TOOL_SHA,V25_SHA,ALLOW_SHA,SPEC_SHA];before=[dig(p) for p in pins];fail=[]
 if before!=exp:fail.append('PIN_MISMATCH')
 allow=json.loads(ALLOW.read_text());allowed={e['path']:e['sha256'] for e in allow['entries']};receipts=sorted(writer.RECEIPT_ROOT.glob('*.recovered-success-receipt.json'));rows=[];outputs=[]
 for p in receipts:
  try:r=writer.validate_restart(p);out=ROOT/r['output'];rows.append({'receipt':str(p.relative_to(ROOT)),'output':r['output'],'valid':True});outputs.append(r['output'])
  except Exception as e:rows.append({'receipt':str(p.relative_to(ROOT)),'valid':False,'error':type(e).__name__});fail.append('ORPHAN_OR_DRIFT')
 duplicates=[k for k,v in Counter(outputs).items() if v>1]
 candidates=sorted(p for p in recovery.FINAL_ROOT.glob('E40_U29C_V2[34]*.json') if p.is_file() and 'RECOVERED' in p.name);bound={ROOT/x for x in outputs};unpaired={str(p.relative_to(ROOT)):dig(p) for p in candidates if p not in bound}
 if len(rows)!=3 or sum(r['valid'] for r in rows)!=3:fail.append('BINDING_COUNT_NOT_3_OF_3')
 if duplicates:fail.append('DUPLICATES')
 if unpaired!=allowed:fail.append('UNPAIRED_ALLOWLIST_MISMATCH')
 residue={'data':sorted(p.name for p in recovery.FINAL_ROOT.iterdir() if p.name.startswith('.u29c-v20-hidden-')),'receipt':sorted(p.name for p in writer.RECEIPT_ROOT.iterdir() if p.name.startswith('.u29c-v23-receipt-hidden-')),'stage':sorted(p.name for p in recovery.STAGING_ROOT.iterdir())}
 if any(residue.values()):fail.append('RESIDUE')
 after=[dig(p) for p in pins]
 if before!=after:fail.append('PIN_MUTATION')
 status='PASS_PINNED_3_OF_3_BINDINGS_EXACT_UNPAIRED_ALLOWLIST_ZERO_RESIDUE_NO_SUBMIT' if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v26.pinned_inventory_verification.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pins_after':after,'receipt_count':len(rows),'valid_binding_count':sum(r['valid'] for r in rows),'bindings':rows,'duplicates':duplicates,'observed_unpaired':unpaired,'exact_allowlist':allowed,'unpaired_exact_match':unpaired==allowed,'residue':residue,'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V27 read-only full V23-V26 chain integrity manifest.'};fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'valid':sum(r['valid'] for r in rows),'unpaired_exact':unpaired==allowed,'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
