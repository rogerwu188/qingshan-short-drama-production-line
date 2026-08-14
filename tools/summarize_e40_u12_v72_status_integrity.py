#!/usr/bin/env python3
import argparse,hashlib,json,re
from pathlib import Path
R=Path(__file__).resolve().parents[1];S=R/'workflow/production_line/E40_TASK_LANES_V1.json'
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--out',required=True);x=a.parse_args();o=R/x.out;d=json.loads(S.read_text());z=[]
 for t in d['tasks']:
  m=re.match(r'E40-U12-V(6[3-9]|7[01])-',t.get('task_id',''))
  if m:
   p=R/t['evidence_ref'];z.append({'v':int(m.group(1)),'ok':t['state']=='TERMINAL' and p.is_file() and sh(p)==t['evidence_sha256'] and t['authorization'] is False})
 z.sort(key=lambda q:q['v']);ok=[q['v'] for q in z]==list(range(63,72)) and all(q['ok'] for q in z);r={'schema':'qingshan.e40.u12.v72.summary.v1','status':'PASS_V63_V71_9_OF_9_TERMINAL_EVIDENCE_EXACT' if ok else 'FAIL','rows':z,'passed':sum(q['ok'] for q in z),'total':9,'authorization':False,'maximum_new_submissions':0};o.parent.mkdir(parents=True,exist_ok=True);o.write_text(json.dumps(r,indent=2)+'\n');return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
