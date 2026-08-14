#!/usr/bin/env python3
"""Immutable pinned invoker for the V55 safety ledger."""
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v56_pinned_safety_ledger_regression/E40_U12_V56_PINNED_SAFETY_LEDGER_REGRESSION_SPEC.json';SPEC_SHA='169e12c02bf7702ec3d3402d6b946f1a2e1cb88077a24af4537b370ebc2a5559'
V55=ROOT/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v55_authority_boundary_safety_ledger/E40_U12_V55_AUTHORITY_BOUNDARY_SAFETY_LEDGER_SPEC.json';V55_SHA='567fc59893995e295085e9eefedb59ac056aff783c43a292e4198387a3d368a3'
TOOL=ROOT/'tools/build_e40_u12_v55_authority_boundary_safety_ledger.py';TOOL_SHA='566a6355db0550beecc4ab5240e8be8b76c1e0f8eaaa4b3b3357b0f50eed0b86'
LEDGER=ROOT/'qa/e40_preproduction_20260812/u12_v55_authority_boundary_safety_ledger/E40_U12_V55_AUTHORITY_BOUNDARY_SAFETY_LEDGER.json';LEDGER_SHA='ece425fb13d5be5e3e009f416fce18b32a4d0fa467c0624e6f764bdf70ba18c6'
CLOSEOUT=ROOT/'workflow/releases/E40_U12_V55_AUTHORITY_BOUNDARY_SAFETY_LEDGER_CLOSEOUT_20260812.json';CLOSEOUT_SHA='80831b20e3023b0cabd1f1e67eec8b9a6557ab881cc11345f18afbf042cab202'
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
 for p,e,n in [(SPEC,SPEC_SHA,'SPEC'),(V55,V55_SHA,'V55_SPEC'),(TOOL,TOOL_SHA,'TOOL'),(LEDGER,LEDGER_SHA,'LEDGER'),(CLOSEOUT,CLOSEOUT_SHA,'CLOSEOUT')]:pin(p,e,n)
 return subprocess.run([sys.executable,str(TOOL),'--out',str(out.relative_to(ROOT))],cwd=ROOT,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
