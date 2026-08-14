#!/usr/bin/env python3
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];M=R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v61_status_chain_integrity/E40_U12_V61_STATUS_CHAIN_INTEGRITY_MANIFEST.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def fp(p):s=p.stat();return [sh(p),s.st_size,s.st_mtime_ns,s.st_dev,s.st_ino]
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R);d=json.loads(M.read_text());b={z['path']:fp(R/z['path']) for z in d['bindings']};rows=[{'path':z['path'],'pass':b[z['path']][0]==z['sha256']} for z in d['bindings']];af={z['path']:fp(R/z['path']) for z in d['bindings']};ok=len(rows)==10 and all(z['pass'] for z in rows) and b==af and d['authorization'] is False;r={'schema':'qingshan.e40.u12.v61.gate.v1','recorded_at':datetime.now(timezone.utc).isoformat(),'status':'PASS_10_OF_10_STATUS_CHAIN_EXACT_NO_MUTATION' if ok else 'FAIL_CLOSED','manifest_sha256':sh(M),'bindings':rows,'binding_pass_count':sum(z['pass'] for z in rows),'binding_count':len(rows),'fingerprints_unchanged':b==af,'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');print(r['status']);return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
