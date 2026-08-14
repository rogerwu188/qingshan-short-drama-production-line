#!/usr/bin/env python3
"""Immutable pinned invoker for the V57 safety-ledger integrity verifier."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v58_pinned_safety_integrity_invoker/E40_U12_V58_PINNED_SAFETY_INTEGRITY_INVOKER_SPEC.json';SPEC_SHA='866dac701b2aabc2710a766df78895adc824a84b5c133fb19b8eefd92556881c'
MANIFEST=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v57_safety_ledger_integrity/E40_U12_V57_SAFETY_LEDGER_INTEGRITY_MANIFEST.json';MANIFEST_SHA='400d71ac44fcbe309f163d28a3cd60377afb862d6f8ea49e97a5493a87f84fe5'
VERIFIER=ROOT/'tools/verify_e40_u12_v57_safety_ledger_integrity.py';VERIFIER_SHA='e38b6017dc5580d4fc41ea8004764ceab47d69b7ca4c050ab2a35b5fb54fcb21'
GATE=ROOT/'qa/e40_preproduction_20260812/u12_v57_safety_ledger_integrity/E40_U12_V57_SAFETY_LEDGER_INTEGRITY_GATE.json';GATE_SHA='0f20a1142542f62b789b2d4f64aff703a051dc69ecaca24e3870d8355905e430'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pin(p,e,n):
 if not p.is_file():raise SystemExit(f'PIN_FAIL_{n}_MISSING')
 a=sha(p)
 if a!=e:raise SystemExit(f'PIN_FAIL_{n}_SHA256:expected={e}:actual={a}')
def safe(raw):
 p=Path(raw)
 if p.is_absolute() or '..' in p.parts:raise SystemExit('OUT_MUST_BE_REPO_RELATIVE')
 r=(ROOT/p).resolve();r.relative_to(ROOT);return r
def main():
 ap=argparse.ArgumentParser(allow_abbrev=False);ap.add_argument('--out',required=True);a=ap.parse_args();out=safe(a.out)
 if out.suffix!='.json':raise SystemExit('OUT_MUST_BE_JSON')
 if out.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 for p,e,n in [(SPEC,SPEC_SHA,'SPEC'),(MANIFEST,MANIFEST_SHA,'MANIFEST'),(VERIFIER,VERIFIER_SHA,'VERIFIER'),(GATE,GATE_SHA,'GATE')]:pin(p,e,n)
 return subprocess.run([sys.executable,str(VERIFIER),'--out',str(out.relative_to(ROOT))],cwd=ROOT,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
