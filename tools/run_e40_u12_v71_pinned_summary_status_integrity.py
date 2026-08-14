#!/usr/bin/env python3
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v71_pinned_summary_status_integrity/E40_U12_V71_PINNED_SUMMARY_STATUS_INTEGRITY_SPEC.json','dc6dc2d107cb9fdd674d2b366c46c709b092d2a1351fc9cbe052b9be4c24128a'),('workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v70_summary_status_integrity/E40_U12_V70_SUMMARY_STATUS_MANIFEST.json','1f815ee89e7c180a2050a2144bb7a6375c1c263d37b9c22477a46e516a5021fc'),('tools/verify_e40_u12_v70_summary_status_integrity.py','9eab6b86c776fe0f712206e9c3f4a1290921d533b9d7e3790152afaf35581728'),('qa/e40_preproduction_20260813/u12_v70_summary_status_integrity/E40_U12_V70_GATE.json','14b5f2463c95dd17666997d8c7f81edeffe997b48ddae9a0b70fb2d2ecbcc57d')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args()
 if any(sh(R/p)!=h for p,h in P):raise SystemExit('PIN')
 return subprocess.run([sys.executable,str(R/P[2][0]),'--out',x.out],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
