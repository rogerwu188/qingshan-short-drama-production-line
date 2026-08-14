#!/usr/bin/env python3
"""Read-only V45 projection-to-evidence correlation audit."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import run_e40_u29c_v17_atomic_link_publish_gate as base
V43=ROOT/'qa/e40_preproduction_20260808/u29c_v43_projection_keyset_crossfield_integrity_v1/E40_U29C_V43_PROJECTION_KEYSET_CROSSFIELD_INTEGRITY_AUDIT_V1.json';V43_SHA='d07461ee37047d986514824d1f55d04163257ac35c1040e8a1763cfbd3f70232'
V44_RUNNER=ROOT/'tools/run_e40_u29c_v44_pinned_projection_keyset_crossfield_regression.py';V44_RUNNER_SHA='4fb347fed7443f128383cf0bf9d94cc87e13cf33743f539a34d236986292b32f'
V44_MATRIX=ROOT/'qa/e40_preproduction_20260808/u29c_v44_pinned_projection_keyset_crossfield_regression_v1/E40_U29C_V44_PINNED_PROJECTION_KEYSET_CROSSFIELD_REGRESSION_MATRIX_V1.json';V44_MATRIX_SHA='3a99d1b5499a787963b7736ebe2e530719cffa61b2e422bdfdf2500eb721d114'
MEMORY=ROOT/'workflow/prompt_memory/E40_U29C_V41_QA_FALSE_NEGATIVE_MEMORY_V1.md';MEMORY_SHA='ac9e7b03d1362d185d17b7ab436306fd5ceb407a0b0f88be495c52a2462da00f'
SPEC=ROOT/'qa/e40_preproduction_20260808/u29c_v45_projection_evidence_correlation_v1/E40_U29C_V45_PROJECTION_EVIDENCE_CORRELATION_SPEC_V1.json';SPEC_SHA='1dd6b3b23b4b3ec58fd164523ae98b22724e81e9fcd0587eeda6250088a46f3d'
CANON=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CANON_SHA='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';MANIFEST=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';MANIFEST_SHA='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';SCHED=ROOT/'workflow/production_line/E40_TASK_LANES_V1.json'
REPORT=SPEC.parent/'E40_U29C_V45_PROJECTION_EVIDENCE_CORRELATION_AUDIT_V1.json';PASS='PASS_V23_TO_V38_EVIDENCE_CORRELATION_16_OF_16_PAYLOAD_STATUS_SHA_NO_MUTATION_NO_SUBMIT'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):
 s=os.lstat(p);return {'path':str(p.relative_to(ROOT)),'sha256':sha(p),'device':s.st_dev,'inode':s.st_ino,'mode':oct(s.st_mode&0o7777),'nlink':s.st_nlink,'uid':s.st_uid,'gid':s.st_gid,'size':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
def load43():
 s=importlib.util.spec_from_file_location('v43',ROOT/'tools/audit_e40_u29c_v43_projection_keyset_crossfield_integrity.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def negs():
 out=[]
 for flag in ('--v43-audit','--v44-runner','--v44-matrix','--memory','--spec','--scheduler','--canonical','--canonical-manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),flag,'/tmp/forbidden-substitution'],cwd=ROOT,text=True,capture_output=True,check=False);out.append({'argument':flag,'exit_code':p.returncode,'rejected_before_audit':p.returncode==2,'report_created':REPORT.exists()})
 return out
def main():
 argparse.ArgumentParser(description='Fixed V45 evidence correlation audit; substitutions forbidden.',allow_abbrev=False).parse_args()
 if REPORT.exists():raise SystemExit('REPORT_ALREADY_EXISTS')
 pins=[(V43,V43_SHA),(V44_RUNNER,V44_RUNNER_SHA),(V44_MATRIX,V44_MATRIX_SHA),(MEMORY,MEMORY_SHA),(SPEC,SPEC_SHA),(CANON,CANON_SHA),(MANIFEST,MANIFEST_SHA)];before=[ident(p) for p,_ in pins];matches=[x['sha256']==e for x,(_,e) in zip(before,pins)]
 if not all(matches):print(json.dumps({'status':'FAIL_CLOSED_PIN_MISMATCH','pin_matches':matches}));return 1
 fail=[];ns=negs()
 if REPORT.exists() or not all(x['rejected_before_audit'] and not x['report_created'] for x in ns):fail.append('SUBSTITUTION_NOT_REJECTED')
 authority=json.loads(V43.read_text());v44=json.loads(V44_MATRIX.read_text());authority_ok=authority.get('status')==load43().PASS and authority.get('failures')==[];v44_ok=v44.get('status')=='PASS_PINNED_V43_EXACT_15_KEY_CROSSFIELD_16_OF_16_MEMORY_PRESERVED_NO_MUTATION_NO_SUBMIT' and v44.get('failures')==[];memory_ok='status syntax is exactly `^PASS_[A-Z0-9_]+$`' in MEMORY.read_text()
 if not authority_ok:fail.append('V43_AUTHORITY_NOT_EXACT')
 if not v44_ok:fail.append('V44_AUTHORITY_NOT_EXACT')
 if not memory_ok:fail.append('V41_MEMORY_NOT_EXACT')
 expected=authority.get('projection_after') or [];sched=json.loads(SCHED.read_text());tm={t['task_id']:t for t in sched['tasks']};projection_before=[];rows=[]
 for ordinal,e in enumerate(expected,start=23):
  t=tm.get(e.get('task_id'));proj=load43().load_v41().project(t);projection_before.append(proj);p=ROOT/t['evidence_ref'] if t else None;payload=json.loads(p.read_text()) if p and p.is_file() else {};name=p.name if p else '';token=f'_V{ordinal}_';basename=bool(token in name and name.startswith('E40_U29C_') and name.endswith('.json'));schema=payload.get('schema','');schema_corr=bool(re.fullmatch(rf'qingshan\.e40\.u29c\.v{ordinal}\.[a-z0-9_.]+',schema));episode=payload.get('episode')=='E40';unit=payload.get('unit_id')=='U29C';status=payload.get('status')==t.get('terminal_status') if t else False;physical=bool(p and p.is_file() and sha(p)==t['evidence_sha256']);exact=proj==e;passed=all((basename,schema_corr,episode,unit,status,physical,exact));rows.append({'ordinal':ordinal,'task_id':e.get('task_id'),'evidence_ref':t.get('evidence_ref') if t else None,'evidence_basename':name,'basename_ordinal_correlation':basename,'schema_ordinal_correlation':schema_corr,'payload_episode_exact':episode,'payload_unit_exact':unit,'payload_status_equals_terminal_status':status,'physical_sha_exact':physical,'projection_authority_exact':exact,'passed':passed})
 if len(rows)!=16 or not all(x['passed'] for x in rows):fail.append('EVIDENCE_CORRELATION_NOT_16_OF_16')
 canonical=sched.get('canonical_script_sha256')==CANON_SHA and sched.get('canonical_manifest_sha256')==MANIFEST_SHA
 if not canonical:fail.append('CANONICAL_NOT_EXACT')
 after_sched=json.loads(SCHED.read_text());am={t['task_id']:t for t in after_sched['tasks']};projection_after=[load43().load_v41().project(am.get(e.get('task_id'))) for e in expected];after=[ident(p) for p,_ in pins]
 if projection_before!=projection_after:fail.append('PROJECTION_MUTATION')
 if before!=after:fail.append('PIN_MUTATION')
 status_out=PASS if not fail else 'FAIL';payload={'schema':'qingshan.e40.u29c.v45.projection_evidence_correlation_audit.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status_out,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pins_before':before,'pin_expected_sha256':[e for _,e in pins],'pin_match_count':sum(matches),'pins_after':after,'v43_authority_valid':authority_ok,'v44_authority_valid':v44_ok,'v41_failure_memory_exact':memory_ok,'canonical_binding_exact':canonical,'projection_task_count':len(rows),'basename_correlation_count':sum(x['basename_ordinal_correlation'] for x in rows),'schema_correlation_count':sum(x['schema_ordinal_correlation'] for x in rows),'payload_episode_count':sum(x['payload_episode_exact'] for x in rows),'payload_unit_count':sum(x['payload_unit_exact'] for x in rows),'payload_status_match_count':sum(x['payload_status_equals_terminal_status'] for x in rows),'physical_sha_match_count':sum(x['physical_sha_exact'] for x in rows),'projection_authority_exact_count':sum(x['projection_authority_exact'] for x in rows),'correlation_rows':rows,'projection_before':projection_before,'projection_after':projection_after,'no_authority_elevation':True,'substitution_negatives':ns,'substitution_negative_count':sum(x['rejected_before_audit'] for x in ns),'blind_replay_allowed':False,'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V46 pinned projection evidence correlation regression.'}
 fd=os.open(REPORT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(payload,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status_out,'pins':sum(matches),'projection':len(rows),'basename':payload['basename_correlation_count'],'schema':payload['schema_correlation_count'],'episode':payload['payload_episode_count'],'unit':payload['payload_unit_count'],'status_match':payload['payload_status_match_count'],'sha':payload['physical_sha_match_count'],'substitutions':payload['substitution_negative_count'],'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
