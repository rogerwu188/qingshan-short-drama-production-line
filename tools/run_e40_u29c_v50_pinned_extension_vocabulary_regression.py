#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'));import run_e40_u29c_v17_atomic_link_publish_gate as base
A=ROOT/'tools/audit_e40_u29c_v49_evidence_extension_key_vocabulary.py';AS='3adfdf67dec4783e08e67dcc5ca0a2ce3a3773b6b0793578663ff300a982a42f';Q=ROOT/'qa/e40_preproduction_20260808/u29c_v49_evidence_extension_key_vocabulary_v1/E40_U29C_V49_EVIDENCE_EXTENSION_KEY_VOCABULARY_AUDIT_V1.json';QS='66276e698e6b0dfdc0c0350ed81f0b7071df56960a6e27ece0c6591b452dc6bb';S=ROOT/'qa/e40_preproduction_20260808/u29c_v50_pinned_extension_vocabulary_regression_v1/E40_U29C_V50_PINNED_EXTENSION_VOCABULARY_REGRESSION_SPEC_V1.json';SS='fcbe7e7a3d3c49ca3b8359d9be9f1045533d92870c8a76383325e66471039ec1';C=ROOT/'workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md';CS='140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b';M=ROOT/'workflow/claude_writer_agent/scripts/E40_manifest_v3.json';MS='773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1';OUT=S.parent/'E40_U29C_V50_PINNED_EXTENSION_VOCABULARY_REGRESSION_MATRIX_V1.json'
def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 argparse.ArgumentParser(allow_abbrev=False).parse_args();pins=[(A,AS),(Q,QS),(S,SS),(C,CS),(M,MS)];fail=[]
 if not all(p.is_file() and h(p)==s for p,s in pins):fail.append('PIN')
 q=json.loads(Q.read_text());freq=Counter();rows=[]
 for r in q['payload_rows']:
  freq.update(r['extension_keys']);rows.append(r['passed'] and not r['forbidden_authority_keys'] and r['closed_policy_unchanged'])
 if not(len(rows)==16 and all(rows) and sorted(freq)==q['vocabulary'] and dict(sorted(freq.items()))==q['vocabulary_frequency'] and len(freq)==106):fail.append('VOCAB')
 neg=[]
 for f in ('--auditor','--audit','--spec','--canonical','--manifest'):
  p=subprocess.run([sys.executable,str(Path(__file__).resolve()),f,'/tmp/x'],capture_output=True);neg.append(p.returncode==2)
 if not all(neg):fail.append('SUB')
 status='PASS_PINNED_106_EXTENSION_KEYS_16_PAYLOADS_ZERO_AUTHORITY_NO_MUTATION_NO_SUBMIT' if not fail else 'FAIL';o={'schema':'qingshan.e40.u29c.v50.pinned_extension_vocabulary_regression_matrix.v1','episode':'E40','unit_id':'U29C','recorded_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'status':status,'execution_permitted':False,'provider_post_allowed':False,'maximum_new_submissions':0,'pin_match_count':sum(p.is_file() and h(p)==s for p,s in pins),'payload_count':len(rows),'vocabulary_size':len(freq),'vocabulary_exact':sorted(freq)==q['vocabulary'],'frequency_exact':dict(sorted(freq.items()))==q['vocabulary_frequency'],'zero_authority':True,'substitution_negative_count':sum(neg),'failures':fail,'side_effects':{'provider_calls':0,'transactions':0,'credits':0,'retries':0,'agentcut':0,'assembly':0},'next_action':'Register V51 extension vocabulary digest audit.'};fd=os.open(OUT,base.create_flags(),0o600);base.write_all(fd,(json.dumps(o,indent=2)+'\n').encode());os.fsync(fd);os.close(fd);print(json.dumps({'status':status,'vocab':len(freq),'payloads':len(rows),'failures':fail}));return 0 if not fail else 1
if __name__=='__main__':raise SystemExit(main())
