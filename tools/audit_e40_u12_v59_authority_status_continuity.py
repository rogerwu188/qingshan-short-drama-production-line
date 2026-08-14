#!/usr/bin/env python3
"""Read-only scheduler/evidence continuity audit for U12 V46-V58."""
from __future__ import annotations
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v59_authority_status_continuity/E40_U12_V59_AUTHORITY_STATUS_CONTINUITY_SPEC.json';SPEC_SHA='bfea379826b7e4594a6820a0216fc44c7d86a9920523f15c8cc151a10309706c'
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
 spec=json.loads(SPEC.read_text());state=json.loads(STATE.read_text());wanted=set(spec['bounded_versions']);rows=[];before={};violations=[]
 for t in state['tasks']:
  m=re.match(r'E40-U12-V(\d+)-',t.get('task_id',''))
  if not m or int(m.group(1)) not in wanted:continue
  v=int(m.group(1));ref=t.get('evidence_ref');p=rp(ref) if ref else None;f=fp(p) if p and p.is_file() else None
  if ref:before[ref]=f
  ok=t.get('state')=='TERMINAL' and t.get('next_due_at') is None and bool(t.get('terminal_status')) and f is not None and f['sha256']==t.get('evidence_sha256') and t.get('authorization') is False and t.get('maximum_new_submissions')==0
  if not ok:violations.append({'version':v,'task_id':t.get('task_id'),'reason':'TERMINAL_OR_EVIDENCE_OR_AUTHORITY_MISMATCH'})
  rows.append({'version':v,'task_id':t.get('task_id'),'state':t.get('state'),'terminal_status':t.get('terminal_status'),'evidence_ref':ref,'expected_sha256':t.get('evidence_sha256'),'actual_sha256':f['sha256'] if f else None,'authorization':t.get('authorization'),'maximum_new_submissions':t.get('maximum_new_submissions'),'passed':ok})
 rows.sort(key=lambda x:x['version']);after={ref:fp(rp(ref)) if rp(ref).is_file() else None for ref in before}
 checks={'spec_sha_exact':sha(SPEC)==SPEC_SHA,'versions_exact_46_to_58':[x['version'] for x in rows]==list(range(46,59)),'terminal_count_13':len(rows)==spec['required_terminal_count']==13,'all_terminal_evidence_exact':len(violations)==0,'fingerprints_unchanged':before==after,'authority_closed':spec.get('authority_keys_admitted')==0 and spec.get('production_assets_admitted')==0 and spec.get('authorization') is False and spec.get('maximum_new_submissions')==0 and spec.get('execution') is False};passed=all(checks.values())
 r={'schema':'qingshan.e40.u12.v59.authority_status_continuity_audit.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_V46_TO_V58_13_OF_13_TERMINAL_EVIDENCE_EXACT_ADMISSION_CLOSED' if passed else 'FAIL_CLOSED_AUTHORITY_STATUS_CONTINUITY_REQUIRES_REVIEW','scheduler_sha256':sha(STATE),'spec_sha256':sha(SPEC),'checks':checks,'tasks':rows,'terminal_count':len(rows),'terminal_pass_count':sum(x['passed'] for x in rows),'violations':violations,'fingerprints_unchanged':before==after,'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':r['status'],'tasks':f"{r['terminal_pass_count']}/{r['terminal_count']}",'violations':len(violations)}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
