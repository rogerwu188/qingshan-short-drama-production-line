#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v64_status_summary_integrity/E40_U12_V64_STATUS_SUMMARY_INTEGRITY_SPEC.json','e2a1dc074eea99243370fd19ccff3640ecbe0899e58e9b646b2d880364dc2a09'),('tools/summarize_e40_u12_v63_status_chain.py','6a7fa3e262162e50f4850e83c606d833fd5b9c999ac585010be7515302e75fb6'),('qa/e40_preproduction_20260812/u12_v63_status_chain_summary/E40_U12_V63_STATUS_CHAIN_SUMMARY.json','d2b4759698e386b51ae3b48dca8dca1ba1fcafa2b09c76446e4e612fe57baac8')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fp(p):s=p.stat();return [sh(p),s.st_size,s.st_mtime_ns,s.st_dev,s.st_ino]
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R);b={p:fp(R/p) for p,_ in P};d=json.loads((R/P[2][0]).read_text());af={p:fp(R/p) for p,_ in P};ok=all(b[p][0]==e for p,e in P) and b==af and d['entry_pass_count']==17 and d['authorization'] is False;r={'schema':'qingshan.e40.u12.v64.gate.v1','status':'PASS_V63_SUMMARY_3_OF_3_PINS_17_OF_17_NO_MUTATION' if ok else 'FAIL_CLOSED','pins_passed':sum(b[p][0]==e for p,e in P),'pins_total':3,'entries_passed':d['entry_pass_count'],'fingerprints_unchanged':b==af,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');print(r['status']);return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
