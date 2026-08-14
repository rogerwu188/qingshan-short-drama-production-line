#!/usr/bin/env python3
"""Read-only inventory and integrity audit for persisted recovery receipts."""
from __future__ import annotations
import hashlib,json,os,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
V23=ROOT/"tools/run_e40_u29c_v23_persisted_recovery_receipt_gate.py";V23_SHA="3f5af7ba788f1b62015da87826033ca5ba77995da9537d2b2bdca7044403f175"
V24=ROOT/"tools/run_e40_u29c_v24_pinned_persisted_receipt_regression.py";V24_SHA="b7926f479cbe02a2ce53fddf85cd6b0387483a6fa2060eafaefaf370c3715114"
MATRIX=ROOT/"qa/e40_preproduction_20260808/u29c_v24_pinned_persisted_receipt_regression_v1/E40_U29C_V24_PINNED_PERSISTED_RECEIPT_RESTART_REGRESSION_MATRIX_V1.json";MATRIX_SHA="0e24f3045d8d14d7f1a68e9dda4f79ac332969eeee3eb0d5c45faeffd834851c"
SPEC=ROOT/"qa/e40_preproduction_20260808/u29c_v25_persisted_receipt_inventory_integrity_v1/E40_U29C_V25_PERSISTED_RECEIPT_INVENTORY_INTEGRITY_AUDIT_SPEC_V1.json";SPEC_SHA="9ad504636f160439fdf46ea34594290db71e8d95c3d0ad887a5f74bfdb4fce96"
REPORT=SPEC.parent/"E40_U29C_V25_PERSISTED_RECEIPT_INVENTORY_INTEGRITY_AUDIT_V1.json"
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[V23,V24,MATRIX,SPEC];expected=[V23_SHA,V24_SHA,MATRIX_SHA,SPEC_SHA];before=[dig(p) for p in pins]
 receipts=sorted(p for p in writer.RECEIPT_ROOT.glob('*.recovered-success-receipt.json') if p.is_file());rows=[];outputs=[];fail=[]
 for receipt in receipts:
  try:
   record=writer.validate_restart(receipt);output=ROOT/record['output'];value=os.stat(output,follow_symlinks=False);row={'receipt':str(receipt.relative_to(ROOT)),'receipt_sha256':dig(receipt),'output':record['output'],'output_sha256':dig(output),'owned_inode_token':[value.st_dev,value.st_ino],'writer_sha256':record['writer_sha256'],'validator_status':record['validator_status'],'link_count':value.st_nlink,'valid':True};outputs.append(record['output'])
  except Exception as exc:row={'receipt':str(receipt.relative_to(ROOT)),'valid':False,'error':type(exc).__name__};fail.append(str(receipt.relative_to(ROOT)))
  rows.append(row)
 duplicates=sorted(k for k,v in Counter(outputs).items() if v>1);orphans=[r['receipt'] for r in rows if not r['valid']]
 all_v23_v24_outputs=sorted(p for p in recovery.FINAL_ROOT.glob('E40_U29C_V2[34]*.json') if p.is_file());bound={ROOT/r['output'] for r in rows if r['valid']};unpaired=sorted(str(p.relative_to(ROOT)) for p in all_v23_v24_outputs if p not in bound and ('RECOVERED' in p.name))
 residue={'data_hidden':sorted(p.name for p in recovery.FINAL_ROOT.iterdir() if p.name.startswith('.u29c-v20-hidden-')),'receipt_hidden':sorted(p.name for p in writer.RECEIPT_ROOT.iterdir() if p.name.startswith('.u29c-v23-receipt-hidden-')),'stage':sorted(p.name for p in recovery.STAGING_ROOT.iterdir())}
 after=[dig(p) for p in pins]
 if before!=expected:fail.append('PIN_MISMATCH')
 if before!=after:fail.append('PIN_MUTATION')
 if duplicates:fail.append('DUPLICATE_OUTPUT_BINDINGS')
 if orphans:fail.append('ORPHAN_RECEIPTS')
 # Unpaired recovered-looking outputs from failed historical local harness runs are evidence, not valid admissions.
 if residue!={'data_hidden':[],'receipt_hidden':[],'stage':[]}:fail.append('RESIDUE')
 status='PASS_READ_ONLY_RECEIPT_INVENTORY_VALID_BINDINGS_AND_HISTORICAL_UNPAIRED_CLASSIFIED_FAIL_CLOSED' if not fail else 'FAIL'
 payload={'schema':'qingshan.e40.u29c.v25.receipt_inventory_integrity_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pins_after':after,'receipt_count':len(receipts),'valid_binding_count':sum(r['valid'] for r in rows),'receipts':rows,'duplicate_output_bindings':duplicates,'orphan_receipts':orphans,'historical_unpaired_recovered_named_outputs':unpaired,'historical_unpaired_classification':'FAIL_CLOSED_NON_ADMITTED_LOCAL_HARNESS_EVIDENCE','residue':residue,'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V26 exact-SHA inventory verifier and historical-unpaired allowlist contract.'}
 REPORT.parent.mkdir(parents=True,exist_ok=True);fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'receipts':len(receipts),'valid':sum(r['valid'] for r in rows),'unpaired':len(unpaired),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
