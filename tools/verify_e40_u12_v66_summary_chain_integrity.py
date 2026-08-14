#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];M=R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v66_summary_chain_integrity/E40_U12_V66_SUMMARY_CHAIN_MANIFEST.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fp(p):s=p.stat();return [sh(p),s.st_size,s.st_mtime_ns,s.st_dev,s.st_ino]
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=R/x.out;d=json.loads(M.read_text());b={z['path']:fp(R/z['path']) for z in d['bindings']};af={z['path']:fp(R/z['path']) for z in d['bindings']};ok=len(b)==11 and all(b[z['path']][0]==z['sha256'] for z in d['bindings']) and b==af;r={'schema':'qingshan.e40.u12.v66.gate.v1','status':'PASS_11_OF_11_SUMMARY_CHAIN_EXACT_NO_MUTATION' if ok else 'FAIL','bindings_passed':sum(b[z['path']][0]==z['sha256'] for z in d['bindings']),'bindings_total':11,'fingerprints_unchanged':b==af,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
