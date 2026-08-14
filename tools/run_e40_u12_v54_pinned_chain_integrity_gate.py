#!/usr/bin/env python3
"""Immutable pinned invoker for the V53 chain-integrity verifier."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v54_pinned_chain_integrity_invoker/E40_U12_V54_PINNED_CHAIN_INTEGRITY_INVOKER_SPEC.json';SPEC_SHA='c395448a22423f977b22e8209adb1744c77ebff6f7ba2b93cca7cbd7c9ca5c28'
MANIFEST=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v53_pinned_chain_inventory_integrity/E40_U12_V53_PINNED_CHAIN_INVENTORY_INTEGRITY_MANIFEST.json';MANIFEST_SHA='5f14442738bdc5916ea1c1d0c7fc0bc3ca864bd6885311bbb6c37e0407ea98a4'
VERIFIER=ROOT/'tools/verify_e40_u12_v53_pinned_chain_inventory_integrity.py';VERIFIER_SHA='180c0ca78adc5f550ad3bd7a0b99873f6d109ac8d410fbb0cbf4ea2f2bed4e12'
GATE=ROOT/'qa/e40_preproduction_20260812/u12_v53_pinned_chain_inventory_integrity/E40_U12_V53_PINNED_CHAIN_INVENTORY_INTEGRITY_GATE.json';GATE_SHA='b06156aa66d42440715d03908eb22db63d629304744257b6e9b0d0f4f1a3aa89'
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
