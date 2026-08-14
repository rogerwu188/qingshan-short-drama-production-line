#!/usr/bin/env python3
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v69_pinned_summary_status/E40_U12_V69_PINNED_SUMMARY_STATUS_SPEC.json','31f67bd4e5b4c2491e16d5aef427e0d755fb17c5b29fd1f3b8acc4868e99be51'),('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v68_summary_chain_status/E40_U12_V68_SUMMARY_CHAIN_STATUS_SPEC.json','167acb8002edc3ba58a2a9e3b5df7c1ce593c3fd8eab988fdb8543121087a56d'),('tools/audit_e40_u12_v68_summary_chain_status.py','e142296d3f6cf42e2b8f85ddd58407c968f87bcf62c2fe069d731408e9ffbea4'),('qa/e40_preproduction_20260813/u12_v68_summary_chain_status/E40_U12_V68_AUDIT.json','1ceacaa90f32f40a5ee58db2682a6f3a4544e2c6164c3f2ebd091cd277a30337')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args()
 if any(sh(R/p)!=e for p,e in P):raise SystemExit('PIN')
 return subprocess.run([sys.executable,str(R/P[2][0]),'--out',x.out],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
