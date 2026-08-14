#!/usr/bin/env python3
"""Read-only V47 required-key/type audit for 16 evidence payloads."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
V45=ROOT/'qa/e40_preproduction_20260808/u29c_v45_projection_evidence_correlation_v1/E40_U29C_V45_PROJECTION_EVIDENCE_CORRELATION_AUDIT_V1.json';V45_SHA='4518ed804dfafde040ac089c48466df95453d234155bee28494e718ebf2d4913';V46R=ROOT/'tools/run_e40_u29c_v46_pinned_projection_evidence_correlation_regression.py';V46R_SHA='c087871e85d0dfec07e4d9e9fe2c4c0773872d2591c18eff9244eb2e6a015912';V46M=ROOT/'qa/e40_preproduction_20260808/u29c_v46_pinned_projection_evidence_correlation_regression_v1/E40_U29C_V46_PINNED_PROJECTION_EVIDENCE_CORRELATION_REGRESSION_MATRIX_V1.json';V46M_SHA='3b80516ec4089f08340c7eec5b60a341975d2492f8ff3106ee0b42995a83d495';MEM=ROOT/'workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md';MEM_SHA='ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f';SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v47_evidence_payload_keyset_integrity_v1/E40_U29C_V47_EVIDENCE_PAYLOAD_KEYSET_INTEGRITY_SPEC_V1.json';SPEC_SHA='41b85ebabd0b33e8f55ec0c35250c7a96f36470e1a118fa638bec8e5700585e8';CANON=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CANON_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';MAN=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';MAN_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json';REPORT=SPEC.parent/'E40_U29C_V47_EVIDENCE_PAYLOAD_KEYSET_INTEGRITY_AUDIT_V1.json';PASS='PASS_V23_TO_V38_EVIDENCE_PAYLOAD_REQUIRED_KEYS_TYPES_16_OF_16_NO_MUTATION_NO_SUBMIT'
REQ={'schema':str,'episode':str,'unit_id':str,'status':str,'execution_permitted':bool,'provider_post_allowed':bool,'maximum_new_submissions':int,'recorded_at':str,'side_effects':dict,'failures':list,'next_action':str};SIDE=('provider_calls','transactions','credits','retries','agentcut','assembly')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':sha(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def utc(s):
 try:return isinstance(s,str) and s.endswith('Z') and datetime.fromisoformat(s[:-1]+'+00:00').utcoffset()==timezone.utc.utcoffset(None)
 except:return False
def negs():
 out=[]
 for f in ('--v45','--v46-runner','--v46-matrix','--memory','--spec','--scheduler','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),f,'/tmp/x'],cwd=ROOT,capture_output=True,text=True);out.append({'argument':f,'exit_code':p.returncode,'rejected_before_audit':p.returncode==2,'report_created':REPORT.exists()})
 return out
def main():
 argparse.ArgumentParser(allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[(V45,V45_SHA),(V46R,V46R_SHA),(V46M,V46M_SHA),(MEM,MEM_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(MAN,MAN_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):return 1
 fail=[];ns=negs()
 if not all(x['rejected_before_audit'] and not x['report_created'] for x in ns):fail.append('SUBSTITUTION')
 auth=json.loads(V45.read_text());sched=json.loads(SCHED.read_text());tm={t['task_id']:t for t in sched['tasks']};rows=[];evid_before=[]
 for row in auth['correlation_rows']:
  t=tm[row['task_id']];p=ROOT/t['evidence_ref'];data=json.loads(p.read_text());identity=ident(p);evid_before.append(identity);present=all(k in data for k in REQ);types=present and all(type(data[k]) is typ for k,typ in REQ.items());policy=types and data['episode']=='E40' and data['unit_id']=='U29C' and data['status']==t['terminal_status'] and data['execution_permitted'] is False and data['provider_post_allowed'] is False and data['maximum_new_submissions']==0 and data['failures']==[] and utc(data['recorded_at']);side=types and all(type(data['side_effects'].get(k)) is int and data['side_effects'][k]==0 for k in SIDE);physical=identity['sha256']==t['evidence_sha256'];passed=all((present,types,policy,side,physical));rows.append({'ordinal':row['ordinal'],'task_id':row['task_id'],'required_keys_present':present,'exact_json_types':types,'closed_policy_values':policy,'side_effects_six_zero_ints':side,'physical_sha_exact':physical,'extension_key_count':len(set(data)-set(REQ)),'passed':passed})
 if len(rows)!=16 or not all(x['passed'] for x in rows):fail.append('PAYLOAD_NOT_16_OF_16')
 canonical=sched.get('canonical_script_sha256')==CANON_SHA and sched.get('canonical_manifest_sha256')==MAN_SHA
 if not canonical:fail.append('CANONICAL')
 after=[ident(p) for p,_ in pins];evid_after=[ident(ROOT/tm[r['task_id']]['evidence_ref']) for r in auth['correlation_rows']]
 if before!=after or evid_before!=evid_after:fail.append('IDENTITY_MUTATION')
 status=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v47.evidence_payload_keyset_integrity_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_match_count':sum(matches),'pins_after':after,'canonical_binding_exact':canonical,'payload_count':len(rows),'required_keys_present_count':sum(x['required_keys_present'] for x in rows),'exact_json_types_count':sum(x['exact_json_types'] for x in rows),'closed_policy_count':sum(x['closed_policy_values'] for x in rows),'side_effects_zero_count':sum(x['side_effects_six_zero_ints'] for x in rows),'physical_sha_count':sum(x['physical_sha_exact'] for x in rows),'payload_rows':rows,'evidence_identity_before':evid_before,'evidence_identity_after':evid_after,'extension_keys_allowed':True,'substitution_negatives':ns,'substitution_negative_count':sum(x['rejected_before_audit'] for x in ns),'failures':fail,'side_effects':{k:0 for k in SIDE},'next_action':'Register V48 pinned evidence payload keyset/type regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'pins':sum(matches),'payloads':len(rows),'keys':payload['required_keys_present_count'],'types':payload['exact_json_types_count'],'policy':payload['closed_policy_count'],'side':payload['side_effects_zero_count'],'sha':payload['physical_sha_count'],'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
