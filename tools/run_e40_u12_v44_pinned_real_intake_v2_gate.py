#!/usr/bin/env python3
"""Pinned synthetic-negative-only invoker for E40/U12 real-intake V2 QA."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v43_real_intake_v2_contract/E40_U12_V43_REAL_FOUR_EVIDENCE_INTAKE_V2_CONTRACT.json';CONTRACT_SHA='2d33b700323195d8da9fcef49f73a9a23c7f46322ac69c20602acb71692323d5'
FIXTURES=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v43_real_intake_v2_contract/E40_U12_V43_BUNDLE_SHAPED_SYNTHETIC_NEGATIVE_MATRIX.json';FIXTURES_SHA='1448f907046f6a318360d63a1584f10ffe7368352f39a59b3e04dae0272b029c'
VALIDATOR=ROOT/'tools/validate_e40_u12_v43_real_intake_v2_synthetic_negative.py';VALIDATOR_SHA='5389af8542105abd78244662b45ac9b5f725582a36e8a3a42e47518b58592911'
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
 pin(CONTRACT,CONTRACT_SHA,'CONTRACT');pin(FIXTURES,FIXTURES_SHA,'FIXTURES');pin(VALIDATOR,VALIDATOR_SHA,'VALIDATOR')
 return subprocess.run([sys.executable,str(VALIDATOR),'--out',str(out.relative_to(ROOT))],cwd=ROOT,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
