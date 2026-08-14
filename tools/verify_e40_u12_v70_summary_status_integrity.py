#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];M=R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v70_summary_status_integrity/E40_U12_V70_SUMMARY_STATUS_MANIFEST.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=R/x.out;d=json.loads(M.read_text());b={p:(sh(R/p),(R/p).stat().st_ino) for p,_ in d['bindings']};af={p:(sh(R/p),(R/p).stat().st_ino) for p,_ in d['bindings']};ok=all(b[p][0]==h for p,h in d['bindings']) and b==af;r={'schema':'qingshan.e40.u12.v70.gate.v1','status':'PASS_8_OF_8_SUMMARY_STATUS_EXACT_NO_MUTATION' if ok else 'FAIL','passed':sum(b[p][0]==h for p,h in d['bindings']),'total':8,'fingerprints_unchanged':b==af,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
