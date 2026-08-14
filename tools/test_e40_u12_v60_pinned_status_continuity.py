#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];I=R/'tools/run_e40_u12_v60_pinned_status_continuity.py'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rp(x):p=(R/x).resolve();p.relative_to(R);return p
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--canonical-output',required=True);x=a.parse_args();o=rp(x.out);c=rp(x.canonical_output);c.parent.mkdir(parents=True,exist_ok=True);cases=[]
 q=subprocess.run([sys.executable,str(I),'--out',str(c.relative_to(R))],cwd=R,capture_output=True);d=json.loads(c.read_text()) if c.exists() else {};cases.append({'case':'CANONICAL','rc':q.returncode,'created':c.exists(),'passed':q.returncode==0 and d.get('terminal_pass_count')==13 and d.get('authorization') is False})
 for n,arg in [('STATE','--state'),('SPEC','--spec'),('TOOL','--tool')]:
  t=c.with_name(c.stem+n+'.json');q=subprocess.run([sys.executable,str(I),'--out',str(t.relative_to(R)),arg,'x'],cwd=R,capture_output=True);cases.append({'case':n,'rc':q.returncode,'created':t.exists(),'passed':q.returncode==2 and not t.exists()})
 ok=all(z['passed'] for z in cases);dout={'schema':'qingshan.e40.u12.v60.pinned_status_continuity_matrix.v1','recorded_at':datetime.now(timezone.utc).isoformat(),'status':'PASS_PINNED_13_OF_13_AND_3_SUBSTITUTIONS_REJECTED_NO_ADMISSION' if ok else 'FAIL_CLOSED','invoker_sha256':sh(I),'cases':cases,'case_pass_count':sum(z['passed'] for z in cases),'case_count':4,'nested_terminal_pass_count':d.get('terminal_pass_count'),'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(dout,indent=2)+'\n');print(dout['status']);return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
