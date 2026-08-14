#!/usr/bin/env python3
"""Pinned V48 regression over V47 evidence payload keyset/type authority."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
AUDITOR=ROOT/'tools/audit_e40_u29c_v47_evidence_payload_keyset_integrity.py';AUDITOR_SHA='4f4a62e3f9c246c29c90391c9034f8efda8fbc025421b722167e22115b78f818';AUDIT=ROOT/'qa/e40_preproduction_20260808/u29c_v47_evidence_payload_keyset_integrity_v1/E40_U29C_V47_EVIDENCE_PAYLOAD_KEYSET_INTEGRITY_AUDIT_V1.json';AUDIT_SHA='b16083b4a7360e41d88e0c7edb002ffa70bbe1c235010ffaf5dfcbb16b936385';MEM=ROOT/'workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md';MEM_SHA='ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f';SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v48_pinned_evidence_payload_keyset_regression_v1/E40_U29C_V48_PINNED_EVIDENCE_PAYLOAD_KEYSET_REGRESSION_SPEC_V1.json';SPEC_SHA='f2814cb92523614d98b0400336c52985d6033be81b7fc7aff229b3f34e920417';CAN=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CAN_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';MAN=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';MAN_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json';REPORT=SPEC.parent/'E40_U29C_V48_PINNED_EVIDENCE_PAYLOAD_KEYSET_REGRESSION_MATRIX_V1.json';PASS='PASS_PINNED_V47_PAYLOAD_KEYS_TYPES_16_OF_16_EXTENSIONS_OBSERVED_NO_MUTATION_NO_SUBMIT';REQ={'schema':str,'episode':str,'unit_id':str,'status':str,'execution_permitted':bool,'provider_post_allowed':bool,'maximum_new_submissions':int,'recorded_at':str,'side_effects':dict,'failures':list,'next_action':str};SIDE=('provider_calls','transactions','credits','retries','agentcut','assembly')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':sha(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def negs():
 rows=[]
 for f in ('--auditor','--audit','--memory','--spec','--scheduler','--canonical','--manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),f,'/tmp/x'],cwd=ROOT,capture_output=True,text=True);rows.append({'argument':f,'exit_code':p.returncode,'rejected_before_regression':p.returncode==2,'report_created':REPORT.exists()})
 return rows
def main():
 argparse.ArgumentParser(allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[(AUDITOR,AUDITOR_SHA),(AUDIT,AUDIT_SHA),(MEM,MEM_SHA),(SPEC,SPEC_SHA),(CAN,CAN_SHA),(MAN,MAN_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):return 1
 fail=[];ns=negs()
 if not all(x['rejected_before_regression'] and not x['report_created'] for x in ns):fail.append('SUBSTITUTION')
 auth=json.loads(AUDIT.read_text());sched=json.loads(SCHED.read_text());tm={t['task_id']:t for t in sched['tasks']};rows=[];eb=[]
 authority=auth.get('status')=='PASS_V23_TO_V38_EVIDENCE_PAYLOAD_REQUIRED_KEYS_TYPES_16_OF_16_NO_MUTATION_NO_SUBMIT' and auth.get('failures')==[]
 if not authority:fail.append('AUTHORITY')
 for snap in auth['payload_rows']:
  t=tm[snap['task_id']];p=ROOT/t['evidence_ref'];d=json.loads(p.read_text());i=ident(p);eb.append(i);present=all(k in d for k in REQ);types=present and all(type(d[k]) is v for k,v in REQ.items());policy=types and d['episode']=='E40' and d['unit_id']=='U29C' and d['status']==t['terminal_status'] and d['execution_permitted'] is False and d['provider_post_allowed'] is False and d['maximum_new_submissions']==0 and d['failures']==[];side=types and all(type(d['side_effects'].get(k)) is int and d['side_effects'][k]==0 for k in SIDE);physical=i['sha256']==t['evidence_sha256'];ext=len(set(d)-set(REQ));snapshot=all((present==snap['required_keys_present'],types==snap['exact_json_types'],policy==snap['closed_policy_values'],side==snap['side_effects_six_zero_ints'],physical==snap['physical_sha_exact'],ext==snap['extension_key_count']));passed=all((present,types,policy,side,physical,snapshot));rows.append({'ordinal':snap['ordinal'],'task_id':snap['task_id'],'required_keys_present':present,'exact_json_types':types,'closed_policy_values':policy,'side_effects_six_zero_ints':side,'physical_sha_exact':physical,'extension_key_count':ext,'v47_snapshot_exact':snapshot,'passed':passed})
 if len(rows)!=16 or not all(x['passed'] for x in rows):fail.append('REGRESSION_NOT_16')
 canonical=sched.get('canonical_script_sha256')==CAN_SHA and sched.get('canonical_manifest_sha256')==MAN_SHA
 if not canonical:fail.append('CANONICAL')
 after=[ident(p) for p,_ in pins];ea=[ident(ROOT/tm[x['task_id']]['evidence_ref']) for x in auth['payload_rows']]
 if before!=after or eb!=ea:fail.append('MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v48.pinned_evidence_payload_keyset_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_match_count':sum(matches),'pins_after':after,'v47_authority_valid':authority,'canonical_binding_exact':canonical,'payload_count':len(rows),'required_keys_count':sum(x['required_keys_present'] for x in rows),'exact_types_count':sum(x['exact_json_types'] for x in rows),'closed_policy_count':sum(x['closed_policy_values'] for x in rows),'zero_side_effect_count':sum(x['side_effects_six_zero_ints'] for x in rows),'physical_sha_count':sum(x['physical_sha_exact'] for x in rows),'v47_snapshot_count':sum(x['v47_snapshot_exact'] for x in rows),'payload_rows':rows,'extension_keys_observed_only':True,'evidence_identity_before':eb,'evidence_identity_after':ea,'substitution_negatives':ns,'substitution_negative_count':sum(x['rejected_before_regression'] for x in ns),'failures':fail,'side_effects':{k:0 for k in SIDE},'next_action':'Register V49 evidence extension-key vocabulary integrity audit.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'pins':sum(matches),'payloads':len(rows),'keys':payload['required_keys_count'],'types':payload['exact_types_count'],'policy':payload['closed_policy_count'],'side':payload['zero_side_effect_count'],'sha':payload['physical_sha_count'],'snapshot':payload['v47_snapshot_count'],'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
