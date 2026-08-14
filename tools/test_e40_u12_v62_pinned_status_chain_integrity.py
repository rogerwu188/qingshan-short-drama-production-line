#!/usr/bin/env python3
import argparse,json,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];I=R/'tools/run_e40_u12_v62_pinned_status_chain_integrity.py'
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);a.add_argument('--canonical',required=True);x=a.parse_args();o=R/x.out;c=R/x.canonical;c.parent.mkdir(parents=True,exist_ok=True);q=subprocess.run([sys.executable,str(I),'--out',x.canonical],cwd=R);d=json.loads(c.read_text());cases=[q.returncode==0 and d['binding_pass_count']==10]
 for arg in ['--manifest','--verifier','--gate']:
  t=c.with_name(c.stem+arg[2:]+'.json');q=subprocess.run([sys.executable,str(I),'--out',str(t.relative_to(R)),arg,'x'],cwd=R,capture_output=True);cases.append(q.returncode==2 and not t.exists())
 r={'schema':'qingshan.e40.u12.v62.matrix.v1','status':'PASS_10_OF_10_AND_3_SUBSTITUTIONS_REJECTED' if all(cases) else 'FAIL','cases_passed':sum(cases),'cases_total':4,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');return 0 if all(cases) else 1
if __name__=='__main__':raise SystemExit(main())
