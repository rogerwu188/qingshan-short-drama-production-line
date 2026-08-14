#!/usr/bin/env python3
"""Bounded read-only inventory for the V46-V50 authority-boundary chain."""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v51_authority_boundary_chain_inventory/E40_U12_V51_AUTHORITY_BOUNDARY_CHAIN_INVENTORY_SPEC.json';SPEC_SHA='bc4056d9bc941a70144f6350147ba8eb20d5e5d3a82fcc7b8789516f54aec562'
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
 spec=json.loads(SPEC.read_text());before={};artifacts=[];invalid=[];statuses={x:[] for x in spec['required_terminal_statuses']};violations=[]
 for rawroot in spec['scan_roots']:
  root=rp(rawroot)
  if not root.is_dir():violations.append({'path':rawroot,'reason':'SCAN_ROOT_MISSING'});continue
  for p in sorted(root.glob('*.json')):
   rel=str(p.relative_to(ROOT));before[rel]=fp(p)
   try:d=json.loads(p.read_text())
   except Exception as e:invalid.append({'path':rel,'error_class':type(e).__name__});continue
   status=d.get('status')
   if status in statuses:statuses[status].append(rel)
   fields={k:d.get(k) for k in ('authority_keys_admitted','production_assets_admitted','real_evidence_validation_authorized','positive_admission_test_authorized','authorization','maximum_new_submissions') if k in d}
   if fields.get('authority_keys_admitted',0)!=0 or fields.get('production_assets_admitted',0)!=0 or fields.get('authorization',False) is not False or fields.get('maximum_new_submissions',0)!=0 or fields.get('real_evidence_validation_authorized',False) is not False or fields.get('positive_admission_test_authorized',False) is not False:violations.append({'path':rel,'reason':'AUTHORITY_OR_ADMISSION_NOT_CLOSED','fields':fields})
   artifacts.append({'path':rel,'sha256':before[rel]['sha256'],'schema':d.get('schema'),'status':status,'authority_fields':fields})
 after={rel:fp(rp(rel)) for rel in before}
 status_rows=[{'status':s,'match_count':len(paths),'paths':paths,'present':len(paths)>0} for s,paths in statuses.items()]
 checks={'spec_sha_exact':sha(SPEC)==SPEC_SHA,'scan_root_count_10':len(spec['scan_roots'])==10,'artifact_count_11':len(artifacts)==11,'invalid_json_zero':len(invalid)==0,'all_five_statuses_present':all(r['present'] for r in status_rows),'authority_and_admission_closed':len(violations)==0,'fingerprints_unchanged':before==after,'spec_closes_authority':spec.get('authority_keys_admitted')==0 and spec.get('production_assets_admitted')==0 and spec.get('authorization') is False and spec.get('maximum_new_submissions')==0 and spec.get('execution') is False};passed=all(checks.values())
 report={'schema':'qingshan.e40.u12.v51.authority_boundary_chain_inventory.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_BOUNDED_V46_TO_V50_CHAIN_11_ARTIFACTS_5_OF_5_STATUSES_NO_ADMISSION' if passed else 'FAIL_CLOSED_AUTHORITY_BOUNDARY_CHAIN_INVENTORY_REQUIRES_REVIEW','spec_sha256':sha(SPEC),'checks':checks,'artifacts':artifacts,'artifact_count':len(artifacts),'status_inventory':status_rows,'required_status_count':len(status_rows),'required_statuses_present':sum(r['present'] for r in status_rows),'invalid_json':invalid,'violations':violations,'fingerprints_before':before,'fingerprints_after':after,'fingerprints_unchanged':before==after,'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':report['status'],'artifacts':len(artifacts),'statuses':f"{report['required_statuses_present']}/{report['required_status_count']}",'violations':len(violations)}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
