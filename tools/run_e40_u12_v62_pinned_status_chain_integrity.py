#!/usr/bin/env python3
import argparse,hashlib,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];P=[(R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v62_pinned_status_chain_integrity/E40_U12_V62_PINNED_STATUS_CHAIN_INTEGRITY_SPEC.json','61f41fff59da498fb5fea6e46603dbf750a12e137e9df08d4815b7ccb450c615'),(R/'workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u12_v61_status_chain_integrity/E40_U12_V61_STATUS_CHAIN_INTEGRITY_MANIFEST.json','0cbc6a4e50f177cc735d14d465e538463eaa177f2e76d7266e99670178046a0e'),(R/'tools/verify_e40_u12_v61_status_chain_integrity.py','bfe15715998b22fff23fc695cd2dcc9691a191628753c113fb696fd2d90d5488'),(R/'qa/e40_preproduction_20260812/u12_v61_status_chain_integrity/E40_U12_V61_STATUS_CHAIN_INTEGRITY_GATE.json','80f5a16b3acbd0a9c175ecb7175b82035a022da8566fdf1b5dc0cfc90220bbb2')]
def sh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(allow_abbrev=False);a.add_argument('--out',required=True);x=a.parse_args();o=(R/x.out).resolve();o.relative_to(R)
 if o.exists():raise SystemExit('OVERWRITE')
 if any(sh(p)!=e for p,e in P):raise SystemExit('PIN_MISMATCH')
 return subprocess.run([sys.executable,str(P[2][0]),'--out',str(o.relative_to(R))],cwd=R).returncode
if __name__=='__main__':raise SystemExit(main())
