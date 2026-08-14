#!/usr/bin/env python3
import argparse,hashlib,json,re
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=R/x.out;d=json.loads(S.read_text());z=[]
 for t in d['tasks']:
  m=re.match(r'E40-U12-V(6[3-7])-',t.get('task_id',''))
  if m:
   p=R/t['evidence_ref'];z.append({'v':int(m.group(1)),'terminal':t['state']=='TERMINAL','evidence_exact':p.is_file() and sh(p)==t['evidence_sha256'],'auth_closed':t['authorization'] is False and t['maximum_new_submissions']==0})
 z.sort(key=lambda q:q['v']);ok=[q['v'] for q in z]==list(range(63,68)) and all(q['terminal'] and q['evidence_exact'] and q['auth_closed'] for q in z);r={'schema':'qingshan.e40.u12.v68.audit.v1','status':'PASS_V63_V67_5_OF_5_TERMINAL_EVIDENCE_EXACT' if ok else 'FAIL','rows':z,'passed':sum(q['terminal'] and q['evidence_exact'] and q['auth_closed'] for q in z),'total':5,'authority_keys_admitted':0,'production_assets_admitted':0,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
