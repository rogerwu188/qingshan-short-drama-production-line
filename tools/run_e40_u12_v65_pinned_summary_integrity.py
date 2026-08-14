#!/usr/bin/env python3
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[(R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v65_pinned_summary_integrity/E40_U12_V65_PINNED_SUMMARY_INTEGRITY_SPEC.json','282a2f4770d99dd88359749b9b528ec5cebaac413fc6fd0283e88927fb17b917'),(R/'tools/verify_e40_u12_v64_status_summary_integrity.py','205fcec904915fe9c0f9147ac8fd0773317824b76388581b891b2a1ba0d1e4a1'),(R/'qa/e40_preproduction_20260813/u12_v64_status_summary_integrity/E40_U12_V64_GATE.json','b572e0916df32bef0c330b99a8596027e0007b4d8f008b4c86463dd346b28c1d')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R)
 if any(sh(p)!=e for p,e in P):raise SystemExit('PIN_MISMATCH')
 return subprocess.run([sys.executable,str(P[1][0]),'--out',str(o.relative_to(R))],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
