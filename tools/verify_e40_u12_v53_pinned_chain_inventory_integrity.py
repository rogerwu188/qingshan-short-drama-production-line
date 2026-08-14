#!/usr/bin/env python3
"""Read-only SHA/stat/inode verifier for the V51-V52 pinned chain."""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v53_pinned_chain_inventory_integrity/E40_U12_V53_PINNED_CHAIN_INVENTORY_INTEGRITY_MANIFEST.json';MANIFEST_SHA='5f14442738bdc5916ea1c1d0c7fc0bc3ca864bd6885311bbb6c37e0407ea98a4'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rp(raw):
 p=Path(raw)
 if p.is_absolute() or '..' in p.parts:raise ValueError(raw)
 r=(ROOT/p).resolve();r.relative_to(ROOT);return r
def fp(p):
 s=p.stat();return {'sha256':sha(p),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'device':s.st_dev,'inode':s.st_ino}
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);a=ap.parse_args();out=rp(a.out)
 if out.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 m=json.loads(MANIFEST.read_text());before={};rows=[]
 for b in m['bindings']:
  p=rp(b['path']);f=fp(p) if p.is_file() else None;before[b['path']]=f;rows.append({'path':b['path'],'expected_sha256':b['sha256'],'actual_sha256':f['sha256'] if f else None,'status':'PASS' if f and f['sha256']==b['sha256'] else 'FAIL'})
 after={b['path']:fp(rp(b['path'])) if rp(b['path']).is_file() else None for b in m['bindings']}
 checks={'manifest_sha_exact':sha(MANIFEST)==MANIFEST_SHA,'binding_count_10':len(rows)==m['binding_count']==10,'paths_unique':len({x['path'] for x in rows})==10,'bindings_10_of_10_exact':all(x['status']=='PASS' for x in rows),'fingerprints_unchanged':before==after,'new_evidence_not_synthesized':m.get('new_evidence_synthesized') is False,'real_validation_forbidden':m.get('real_evidence_validation_authorized') is False,'positive_admission_forbidden':m.get('positive_admission_test_authorized') is False,'authority_admission_zero':m.get('authority_keys_admitted')==0 and m.get('production_assets_admitted')==0 and m.get('authorization') is False and m.get('maximum_new_submissions')==0 and m.get('execution') is False};passed=all(checks.values())
 report={'schema':'qingshan.e40.u12.v53.pinned_chain_inventory_integrity_gate.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_10_OF_10_PINNED_CHAIN_INVENTORY_BINDINGS_EXACT_NO_MUTATION' if passed else 'FAIL_CLOSED_PINNED_CHAIN_INVENTORY_INTEGRITY_MISMATCH','manifest_sha256':sha(MANIFEST),'bindings':rows,'checks':checks,'binding_count':len(rows),'binding_pass_count':sum(x['status']=='PASS' for x in rows),'failure_count':sum(not x for x in checks.values()),'fingerprints_before':before,'fingerprints_after':after,'fingerprints_unchanged':before==after,'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':report['status'],'bindings':f"{report['binding_pass_count']}/{report['binding_count']}",'failures':report['failure_count']}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
