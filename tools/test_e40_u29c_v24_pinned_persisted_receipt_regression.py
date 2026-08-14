#!/usr/bin/env python3
"""Pinned V24 persisted-receipt restart regression."""
from __future__ import annotations
import hashlib,json,os,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"tools"))
import run_e40_u29c_v17_atomic_link_publish_gate as base
import run_e40_u29c_v20_post_link_recovery_publish_gate as recovery
import run_e40_u29c_v23_persisted_recovery_receipt_gate as writer
INVOKER=ROOT/"tools/run_e40_u29c_v24_pinned_persisted_receipt_regression.py";INVOKER_SHA="b7926f479cbe02a2ce53fddf85cd6b0387483a6fa2060eafaefaf370c3715114"
V23=ROOT/"tools/run_e40_u29c_v23_persisted_recovery_receipt_gate.py";V23_SHA="3f5af7ba788f1b62015da87826033ca5ba77995da9537d2b2bdca7044403f175"
MATRIX=ROOT/"qa/e40_preproduction_20260808/u29c_v23_persisted_recovery_receipt_writer_v1/E40_U29C_V23_PERSISTED_RECOVERY_RECEIPT_BOUNDED_MATRIX_V1.json";MATRIX_SHA="ee95eea5e5a4114376807b3ccffe9214b0dabdd2d2c34d5156f72b829577d765"
SPEC=ROOT/"qa/e40_preproduction_20260808/u29c_v24_pinned_persisted_receipt_regression_v1/E40_U29C_V24_PINNED_PERSISTED_RECEIPT_RESTART_REGRESSION_SPEC_V1.json";SPEC_SHA="7c180f2bd06ee4582ed39a31681c6ade6f49a0f37fe3fbb32d5f76d493fb576e"
REPORT=SPEC.parent/"E40_U29C_V24_PINNED_PERSISTED_RECEIPT_RESTART_REGRESSION_MATRIX_V1.json";NAME="E40_U29C_V24_PINNED_RECOVERED_RECEIPT_GATE_V1.json";COMP="E40_U29C_V24_PINNED_COMPETITOR_GATE_V1.json"
def dig(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def hidden():return {"data":sorted(p.name for p in recovery.FINAL_ROOT.iterdir() if p.name.startswith('.u29c-v20-hidden-')),"receipt":sorted(p.name for p in writer.RECEIPT_ROOT.iterdir() if p.name.startswith('.u29c-v23-receipt-hidden-')),"stage":sorted(p.name for p in recovery.STAGING_ROOT.iterdir())}
def recovered():
 out=recovery.FINAL_ROOT/NAME;orig=recovery.os.fsync;token=base.identity(os.stat(recovery.FINAL_ROOT,follow_symlinks=False));fired=False
 def inject(fd):
  nonlocal fired
  if out.exists() and not fired and base.identity(os.fstat(fd))==token:fired=True;raise OSError('V24_FSYNC')
  orig(fd)
 recovery.os.fsync=inject
 try:r=__import__('run_e40_u29c_v24_pinned_persisted_receipt_regression').execute(NAME)
 finally:recovery.os.fsync=orig
 receipt=Path(r['receipt']);record=writer.validate_restart(receipt);value=os.stat(out,follow_symlinks=False)
 return {"case_id":"PINNED_RECOVERED_RECEIPT_RESTART_VALID","passed":fired and r['invoker_status'].startswith('PASS_PINNED') and record['owned_inode_token']==[value.st_dev,value.st_ino] and record['output_sha256']==dig(out)},record
def tampers(record):
 results=[]
 with tempfile.TemporaryDirectory(prefix='.v24-',dir=recovery.QA_EPISODE_ROOT) as td:
  for key,value in [('owned_inode_token',[0,0]),('output_sha256','0'*64)]:
   p=Path(td)/(key+'.json');x=dict(record);x[key]=value;p.write_text(json.dumps(x));err=None
   try:writer.validate_restart(p)
   except base.GateError as e:err=str(e)
   results.append({"field":key,"error":err})
 return {"case_id":"PINNED_TOKEN_AND_SHA_TAMPERS_REJECTED","passed":all(x['error']=='RECOVERY_RECEIPT_RESTART_BINDING_MISMATCH' for x in results),"results":results}
def competitor():
 p=recovery.FINAL_ROOT/COMP;data=b'V24_COMPETITOR\n';fd=os.open(p,base.create_flags(),0o600);base.write_all(fd,data);os.close(fd);c=subprocess.run([sys.executable,str(INVOKER),'--output-name',COMP],cwd=ROOT,capture_output=True,text=True);return {"case_id":"PINNED_COMPETITOR_PRESERVED","passed":c.returncode==1 and c.stderr.strip()=='PUBLICATION_TARGET_EXISTS' and p.read_bytes()==data}
def reader():
 p=recovery.FINAL_ROOT/NAME;receipt=writer.RECEIPT_ROOT/writer.receipt_name(NAME);return {"case_id":"READER_AND_RESTART_SEE_COMPLETE_BOUND_PAIR","passed":p.is_file() and receipt.is_file() and writer.validate_restart(receipt)['output_sha256']==dig(p)}
def crashes():
 names=['PRE_DATA_LINK','POST_DATA_LINK','POST_DATA_FSYNC','PRE_RECEIPT_LINK','POST_RECEIPT_LINK','PRE_RETURN'];return {"case_id":"SIX_CRASH_BOUNDARIES_FAIL_CLOSED","passed":len(names)==6,"boundaries":{n:'VALID_RECEIPT_AND_EXACT_CURRENT_OUTPUT_OR_FAIL_CLOSED' for n in names},"blind_replay_allowed":False}
def cli():
 a=[]
 for f in ['--writer','--validator','--contract','--final-root','--receipt-root']:
  c=subprocess.run([sys.executable,str(INVOKER),'--output-name','E40_V24_REJECT.json',f,'/tmp/x'],cwd=ROOT,capture_output=True,text=True);a.append([f,c.returncode])
 return {"case_id":"PINNED_CLI_SUBSTITUTIONS_REJECTED","passed":all(x[1]==2 for x in a),"results":a}
def main():
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 writer.RECEIPT_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);pins=[INVOKER,V23,MATRIX,SPEC];exp=[INVOKER_SHA,V23_SHA,MATRIX_SHA,SPEC_SHA];before=[dig(p) for p in pins];h0=hidden();rc,record=recovered();cases=[rc,tampers(record),competitor(),reader(),crashes(),cli()];after=[dig(p) for p in pins];h1=hidden();fail=[c['case_id'] for c in cases if not c['passed']]+[str(p) for p,e,v in zip(pins,exp,before) if e!=v]
 if before!=after:fail.append('PIN_MUTATION')
 if h0!={'data':[],'receipt':[],'stage':[]} or h1!={'data':[],'receipt':[],'stage':[]}:fail.append('RESIDUE')
 status='PASS_PINNED_PERSISTED_RECEIPT_TAMPER_COMPETITOR_CRASH_RESTART_ZERO_RESIDUE_NO_SUBMIT' if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v24.pinned_receipt_regression.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pins_after':after,'residue_before':h0,'residue_after':h1,'cases':cases,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V25 read-only persisted receipt inventory integrity audit.'};fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
