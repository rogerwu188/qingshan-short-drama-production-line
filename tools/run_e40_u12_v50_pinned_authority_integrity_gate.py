#!/usr/bin/env python3
"""Immutable pinned invoker for the V49 authority-boundary integrity gate."""
from __future__ import annotations
import argparse, hashlib, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v50_pinned_authority_integrity_invoker/E40_U12_V50_PINNED_AUTHORITY_INTEGRITY_INVOKER_CONTRACT.json';CONTRACT_SHA='ba54440e27562a5b9a6f6a9d9cb9bf3a6b76b29fe5c29f2ae163e5391cca7084'
MANIFEST=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v49_authority_boundary_integrity/E40_U12_V49_AUTHORITY_BOUNDARY_SAFETY_INTEGRITY_MANIFEST.json';MANIFEST_SHA='4550939a4159e3244787a7acff15d320eb0344535343303524c8e4afae13246b'
VERIFIER=ROOT/'tools/verify_e40_u12_v49_authority_boundary_safety_integrity.py';VERIFIER_SHA='66ce30bb5c51d4b40f643bf612089d732c1006eb23df74f4195a061566af0333'
GATE=ROOT/'qa/e40_preproduction_20260812/u12_v49_authority_boundary_integrity/E40_U12_V49_AUTHORITY_BOUNDARY_SAFETY_INTEGRITY_GATE.json';GATE_SHA='ed4ed116205de28161b75352528800a61df15d7762d49d48c4b52a68916b0372'
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
 pin(CONTRACT,CONTRACT_SHA,'CONTRACT');pin(MANIFEST,MANIFEST_SHA,'MANIFEST');pin(VERIFIER,VERIFIER_SHA,'VERIFIER');pin(GATE,GATE_SHA,'GATE')
 return subprocess.run([sys.executable,str(VERIFIER),'--out',str(out.relative_to(ROOT))],cwd=ROOT,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
