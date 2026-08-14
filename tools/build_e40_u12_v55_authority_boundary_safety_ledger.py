#!/usr/bin/env python3
"""Build a bounded read-only exact-SHA ledger of V46-V54 closeouts."""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v55_authority_boundary_safety_ledger/E40_U12_V55_AUTHORITY_BOUNDARY_SAFETY_LEDGER_SPEC.json';SPEC_SHA='567fc59893995e295085e9eefedb59ac056aff783c43a292e4198387a3d368a3'
CLOSEOUTS={
46:('workflow/releases/E40_U12_V46_POSITIVE_ADMISSION_AUTHORITY_BOUNDARY_CLOSEOUT_20260812.json','412ca025ca0b9c20863dfd1ddb867f6a7ad185e9410359370fc064d17085116c'),
47:('workflow/releases/E40_U12_V47_AUTHORITY_BOUNDARY_INVENTORY_CLOSEOUT_20260812.json','494eac5555a2f76cd83a3bc0941ee479ec4d5562e7f95c42a767552897120e00'),
48:('workflow/releases/E40_U12_V48_AUTHORITY_INVENTORY_FALSE_POSITIVE_REGRESSION_CLOSEOUT_20260812.json','b0cba660cb1944ac6b0f51863c03aa2697a57c9d579cafdc0653c35e94b46a6e'),
49:('workflow/releases/E40_U12_V49_AUTHORITY_BOUNDARY_SAFETY_INTEGRITY_CLOSEOUT_20260812.json','576802151c31c43ce935771acc567f127fface8e7204b1b957e3c527aa979e26'),
50:('workflow/releases/E40_U12_V50_PINNED_AUTHORITY_INTEGRITY_INVOKER_CLOSEOUT_20260812.json','fb498dd11d16dfde219e73c4918e6e7e19a203576d8b615314dbce3d97037a03'),
51:('workflow/releases/E40_U12_V51_AUTHORITY_BOUNDARY_CHAIN_INVENTORY_CLOSEOUT_20260812.json','67ea9873bd39dcd0a80dc9efc95506e81191d141b603f4eed377b19d54179941'),
52:('workflow/releases/E40_U12_V52_PINNED_AUTHORITY_CHAIN_INVENTORY_REGRESSION_CLOSEOUT_20260812.json','2022308365ba9b8becf5ce8cde7f1c521e387d350f04dd92ff11939efabfff47'),
53:('workflow/releases/E40_U12_V53_PINNED_CHAIN_INVENTORY_INTEGRITY_CLOSEOUT_20260812.json','633fa18d202bd5b049277b30ce25898bac99175a23f10ea5f27fe07104cd295a'),
54:('workflow/releases/E40_U12_V54_PINNED_CHAIN_INTEGRITY_INVOKER_CLOSEOUT_20260812.json','f996a993806d7e6c73355132a67ac3c9fce958692684563c8951ad3594900715')}
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
 spec=json.loads(SPEC.read_text());before={};rows=[];violations=[]
 for version in spec['bounded_versions']:
  raw,expected=CLOSEOUTS[version];p=rp(raw);before[raw]=fp(p) if p.is_file() else None
  if before[raw] is None:violations.append({'version':version,'path':raw,'reason':'MISSING'});continue
  d=json.loads(p.read_text());fields={k:d.get(k) for k in ('new_evidence_synthesized','authority_keys_admitted','production_assets_admitted','real_evidence_validation_authorized','positive_admission_test_authorized','authorization','maximum_new_submissions') if k in d}
  bad=before[raw]['sha256']!=expected or fields.get('new_evidence_synthesized',False) is not False or fields.get('authority_keys_admitted',0)!=0 or fields.get('production_assets_admitted',0)!=0 or fields.get('real_evidence_validation_authorized',False) is not False or fields.get('positive_admission_test_authorized',False) is not False or fields.get('authorization',False) is not False or fields.get('maximum_new_submissions',0)!=0
  if bad:violations.append({'version':version,'path':raw,'reason':'SHA_OR_AUTHORITY_CLOSURE_MISMATCH','fields':fields})
  rows.append({'version':version,'path':raw,'expected_sha256':expected,'actual_sha256':before[raw]['sha256'],'status':d.get('status'),'authority_fields':fields,'passed':not bad})
 after={raw:fp(rp(raw)) if rp(raw).is_file() else None for raw,_ in CLOSEOUTS.values()}
 checks={'spec_sha_exact':sha(SPEC)==SPEC_SHA,'versions_46_through_54_exact':spec['bounded_versions']==list(range(46,55)),'closeout_count_9':len(rows)==spec['required_closeout_count']==9,'all_closeout_shas_exact':all(r['expected_sha256']==r['actual_sha256'] for r in rows),'all_authority_fields_closed':len(violations)==0,'fingerprints_unchanged':before==after};passed=all(checks.values())
 report={'schema':'qingshan.e40.u12.v55.authority_boundary_safety_ledger.v1','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':'PASS_V46_TO_V54_NINE_CLOSEOUTS_EXACT_AUTHORITY_ADMISSION_CLOSED' if passed else 'FAIL_CLOSED_AUTHORITY_BOUNDARY_SAFETY_LEDGER_REQUIRES_REVIEW','spec_sha256':sha(SPEC),'checks':checks,'entries':rows,'entry_count':len(rows),'entry_pass_count':sum(r['passed'] for r in rows),'violations':violations,'fingerprints_before':before,'fingerprints_after':after,'fingerprints_unchanged':before==after,'new_evidence_synthesized':False,'authority_keys_admitted':0,'production_assets_admitted':0,'real_evidence_validation_authorized':False,'positive_admission_test_authorized':False,'authorization':False,'maximum_new_submissions':0,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'generation_actions':0,'renders':0,'agentcut_actions':0,'assembly_actions':0,'release_actions':0,'browser_started':False,'platform_state_changed':False,'work_queue_changed':False,'e38_state_changed':False,'e39_state_changed':False}}
 out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':report['status'],'entries':f"{report['entry_pass_count']}/{report['entry_count']}",'violations':len(violations)}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
