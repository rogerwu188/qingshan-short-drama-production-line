#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
P=[(R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v60_pinned_status_continuity/E40_U12_V60_PINNED_STATUS_CONTINUITY_SPEC.json','f62990938f00c723eb9f9ee93ea8d696a25e064e9aaed4fc1616db184e73b866'),(R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v59_authority_status_continuity/E40_U12_V59_AUTHORITY_STATUS_CONTINUITY_SPEC.json','bfea379826b7e4594a6820a0216fc44c7d86a9920523f15c8cc151a10309706c'),(R/'tools/audit_e40_u12_v59_authority_status_continuity.py','9f5464e4f9c39df60babdb149a934780b9142c3ab11a2a05a26afd70f3fff105'),(R/'qa/e40_preproduction_20260812/u12_v59_authority_status_continuity/E40_U12_V59_AUTHORITY_STATUS_CONTINUITY_AUDIT.json','81ede9be94fce8088385f95a378cb038db3c38948456a406532a0a9c1918f782')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R)
 if o.exists():raise SystemExit('OUT_OVERWRITE_FORBIDDEN')
 for p,e in P:
  if sh(p)!=e:raise SystemExit('PIN_MISMATCH')
 return subprocess.run([sys.executable,str(P[2][0]),'--out',str(o.relative_to(R))],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
