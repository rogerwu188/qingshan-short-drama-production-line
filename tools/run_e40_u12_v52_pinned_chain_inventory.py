#!/usr/bin/env python3
"""Immutable pinned invoker for the V51 authority-boundary chain inventory."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
V52=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v52_pinned_chain_inventory_regression/E40_U12_V52_PINNED_CHAIN_INVENTORY_REGRESSION_SPEC.json';V52_SHA='e35839df6aaee5de69c5f79b6c37db905556731dd2a8d65cab20b23389e7788e'
V51=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v51_authority_boundary_chain_inventory/E40_U12_V51_AUTHORITY_BOUNDARY_CHAIN_INVENTORY_SPEC.json';V51_SHA='bc4056d9bc941a70144f6350147ba8eb20d5e5d3a82fcc7b8789516f54aec562'
SCANNER=ROOT/'tools/inventory_e40_u12_v51_authority_boundary_chain.py';SCANNER_SHA='760e83fa3755ce1ced88842da982b9e542a60fd7a72bda9ff89392d54514cf99'
INVENTORY=ROOT/'qa/e40_preproduction_20260812/u12_v51_authority_boundary_chain_inventory/E40_U12_V51_AUTHORITY_BOUNDARY_CHAIN_INVENTORY.json';INVENTORY_SHA='9b15ccb836bd6f453b2425e33256f74c0764aae4b1945badfd628d98fcb9f5af'
CLOSEOUT=ROOT/'workflow/releases/E40_U12_V51_AUTHORITY_BOUNDARY_CHAIN_INVENTORY_CLOSEOUT_20260812.json';CLOSEOUT_SHA='67ea9873bd39dcd0a80dc9efc95506e81191d141b603f4eed377b19d54179941'
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
 for p,e,n in [(V52,V52_SHA,'V52_SPEC'),(V51,V51_SHA,'V51_SPEC'),(SCANNER,SCANNER_SHA,'SCANNER'),(INVENTORY,INVENTORY_SHA,'INVENTORY'),(CLOSEOUT,CLOSEOUT_SHA,'CLOSEOUT')]:pin(p,e,n)
 return subprocess.run([sys.executable,str(SCANNER),'--out',str(out.relative_to(ROOT))],cwd=ROOT,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
