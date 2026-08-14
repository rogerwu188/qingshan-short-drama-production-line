#!/usr/bin/env python3
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R);d=json.loads(S.read_text());rows=[]
 for t in d['tasks']:
  m=re.match(r'E40-U12-V(\d+)-',t.get('task_id',''))
  if m and 46<=int(m.group(1))<=62:
   p=R/t['evidence_ref'];rows.append({'version':int(m.group(1)),'task_id':t['task_id'],'state':t['state'],'terminal_status':t.get('terminal_status'),'evidence_ref':t['evidence_ref'],'evidence_exact':p.is_file() and sh(p)==t['evidence_sha256'],'authorization':t.get('authorization'),'maximum_new_submissions':t.get('maximum_new_submissions')})
 rows.sort(key=lambda z:z['version']);ok=[z['version'] for z in rows]==list(range(46,63)) and all(z['state']=='TERMINAL' and z['evidence_exact'] and z['authorization'] is False and z['maximum_new_submissions']==0 for z in rows);r={'schema':'qingshan.e40.u12.v63.summary.v1','recorded_at':datetime.now(timezone.utc).isoformat(),'status':'PASS_V46_TO_V62_17_OF_17_TERMINAL_EVIDENCE_EXACT_ADMISSION_CLOSED' if ok else 'FAIL_CLOSED','scheduler_sha256':sh(S),'entries':rows,'entry_count':len(rows),'entry_pass_count':sum(z['state']=='TERMINAL' and z['evidence_exact'] for z in rows),'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');print(r['status']);return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
