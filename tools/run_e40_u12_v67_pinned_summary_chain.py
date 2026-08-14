#!/usr/bin/env python3
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v67_pinned_summary_chain/E40_U12_V67_PINNED_SUMMARY_CHAIN_SPEC.json','ad8667cf75b581407ca4ea720f12a57eb75986b5c07dff14a73757f542697a48'),('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v66_summary_chain_integrity/E40_U12_V66_SUMMARY_CHAIN_INTEGRITY_SPEC.json','c862bd33217dcf24237b2d63f604f82d6aa00a338221c350d859cf11a5fbe955'),('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v66_summary_chain_integrity/E40_U12_V66_SUMMARY_CHAIN_MANIFEST.json','b6ca2150f4c9563093cd95736f3d97c7e64c484c784bfd5b92d6d915be8ee250'),('tools/verify_e40_u12_v66_summary_chain_integrity.py','8cd2f5c399cd516e73b1aa1a400bdde64ea9723e739f0ba6c18c3767ce030411'),('qa/e40_preproduction_20260813/u12_v66_summary_chain_integrity/E40_U12_V66_GATE.json','d0e6df4c7a2735efa3f18f6a7972a43b1f242ca7e35e87e122209acb56372151')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args();o=R/x.out
 if any(sh(R/p)!=e for p,e in P):raise SystemExit('PIN')
 return subprocess.run([sys.executable,str(R/P[3][0]),'--out',str(o.relative_to(R))],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
