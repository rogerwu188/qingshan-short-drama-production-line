#!/usr/bin/env python3
"""Read-only V49 extension-key vocabulary audit."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
V47=ROOT/'qa/e40_preproduction_20260808/u29c_v47_evidence_payload_keyset_integrity_v1/E40_U29C_V47_EVIDENCE_PAYLOAD_KEYSET_INTEGRITY_AUDIT_V1.json';V47_SHA='b16083b4a7360e41d88e0c7edb002ffa70bbe1c235010ffaf5dfcbb16b936385';V48R=ROOT/'tools/run_e40_u29c_v48_pinned_evidence_payload_keyset_regression.py';V48R_SHA='4f35d73b9381af7053f59ff8ec10c3cb07b665ef676ccc891d09bcc3c307ad55';V48M=ROOT/'qa/e40_preproduction_20260808/u29c_v48_pinned_evidence_payload_keyset_regression_v1/E40_U29C_V48_PINNED_EVIDENCE_PAYLOAD_KEYSET_REGRESSION_MATRIX_V1.json';V48M_SHA='c814a5a3af79a480ea3b9d73caee6cd4d70b67eeadfe137b4ebd671b5aa08c3b';MEM=ROOT/'workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md';MEM_SHA='ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f';SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v49_evidence_extension_key_vocabulary_v1/E40_U29C_V49_EVIDENCE_EXTENSION_KEY_VOCABULARY_SPEC_V1.json';SPEC_SHA='c6e1accb3e8b5766f26f9191291b5ce28223702171e8192cca4c556ed74d1d24';CAN=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CAN_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';MAN=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';MAN_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json';REPORT=SPEC.parent/'E40_U29C_V49_EVIDENCE_EXTENSION_KEY_VOCABULARY_AUDIT_V1.json';PASS='PASS_V23_TO_V38_EXTENSION_KEY_VOCABULARY_OBSERVED_ONLY_NO_AUTHORITY_NO_MUTATION_NO_SUBMIT';REQ={'schema','episode','unit_id','status','execution_permitted','provider_post_allowed','maximum_new_submissions','recorded_at','side_effects','failures','next_action'};KEY=re.compile(r'^[a-z][a-z0-9_]*$');FORBID={'authorization','provider_authorization','submit_authorized','paid_submit_allowed','retry_authorized','credits_authorized','external_mutation_allowed'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':sha(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 out=[]
 for f in ('--v47','--v48-runner','--v48-matrix','--memory','--spec','--scheduler','--canonical','--manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),f,'/tmp/x'],cwd=ROOT,capture_output=True,text=True);out.append({'argument':f,'exit_code':p.returncode,'rejected_before_audit':p.returncode==2,'report_created':REPORT.exists()})
 return out
def main():
 argparse.ArgumentParser(allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[(V47,V47_SHA),(V48R,V48R_SHA),(V48M,V48M_SHA),(MEM,MEM_SHA),(SPEC,SPEC_SHA),(CAN,CAN_SHA),(MAN,MAN_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):return 1
 fail=[];ns=negs();auth=json.loads(V47.read_text());sched=json.loads(SCHED.read_text());tm={t['task_id']:t for t in sched['tasks']};rows=[];freq=Counter();eb=[]
 if not all(x['rejected_before_audit'] and not x['report_created'] for x in ns):fail.append('SUBSTITUTION')
 for snap in auth['payload_rows']:
  t=tm[snap['task_id']];p=ROOT/t['evidence_ref'];d=json.loads(p.read_text());eb.append(ident(p));ext=sorted(set(d)-REQ);freq.update(ext);syntax=all(KEY.fullmatch(k) for k in ext);forbidden=sorted(set(ext)&FORBID);count=len(ext)==snap['extension_key_count'];closed=d['execution_permitted'] is False and d['provider_post_allowed'] is False and d['maximum_new_submissions']==0 and all(d['side_effects'].get(k)==0 for k in ('provider_calls','transactions','credits','retries','agentcut','assembly'));passed=syntax and not forbidden and count and closed;rows.append({'ordinal':snap['ordinal'],'task_id':snap['task_id'],'extension_keys':ext,'extension_key_count':len(ext),'v47_extension_count_exact':count,'snake_case_vocabulary':syntax,'forbidden_authority_keys':forbidden,'closed_policy_unchanged':closed,'passed':passed})
 if len(rows)!=16 or not all(x['passed'] for x in rows):fail.append('VOCABULARY_NOT_16')
 canonical=sched.get('canonical_script_sha256')==CAN_SHA and sched.get('canonical_manifest_sha256')==MAN_SHA
 if not canonical:fail.append('CANONICAL')
 after=[ident(p) for p,_ in pins];ea=[ident(ROOT/tm[x['task_id']]['evidence_ref']) for x in auth['payload_rows']]
 if before!=after or eb!=ea:fail.append('MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v49.evidence_extension_key_vocabulary_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_match_count':sum(matches),'pins_after':after,'canonical_binding_exact':canonical,'payload_count':len(rows),'vocabulary':sorted(freq),'vocabulary_size':len(freq),'vocabulary_frequency':dict(sorted(freq.items())),'payload_rows':rows,'syntax_pass_count':sum(x['snake_case_vocabulary'] for x in rows),'forbidden_authority_key_count':sum(len(x['forbidden_authority_keys']) for x in rows),'extension_count_snapshot_exact_count':sum(x['v47_extension_count_exact'] for x in rows),'closed_policy_count':sum(x['closed_policy_unchanged'] for x in rows),'extensions_observation_only':True,'evidence_identity_before':eb,'evidence_identity_after':ea,'substitution_negatives':ns,'substitution_negative_count':sum(x['rejected_before_audit'] for x in ns),'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V50 pinned extension-key vocabulary regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'pins':sum(matches),'payloads':len(rows),'vocabulary':len(freq),'syntax':payload['syntax_pass_count'],'forbidden':payload['forbidden_authority_key_count'],'snapshot':payload['extension_count_snapshot_exact_count'],'closed':payload['closed_policy_count'],'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
