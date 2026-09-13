#!/usr/bin/env python3
"""Build a sanitized source export containing code, config schemas, and runbooks."""
from __future__ import annotations
import argparse, hashlib, json, shutil, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {"tools", "qingshan_engine", "libraries", "tests", "docs", "examples", "configs", "agent_factory"}
DENY_PARTS = {"qa", "working_assets", "deliverables", "outputs", "storyboards", "ref_images", "assets", "logs", "evidence", "handoff", "releases", "secrets", ".secrets", "workflow", ".git"}
DENY_SUFFIX = (".mp4", ".mov", ".wav", ".mp3", ".png", ".jpg", ".jpeg", ".webm")
SECRET_WORDS = ("api_key", "apikey", "token", "secret", "credential", "password", "cookies")

def safe(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & DENY_PARTS or rel.suffix.lower() in DENY_SUFFIX:
        return False
    low = rel.name.lower()
    if low in {".ds_store"} or re.search(r"(?:^|[_-])e\d{1,3}(?:[_-]|\.)", low):
        return False
    if any(w in low for w in SECRET_WORDS) or any(w in low for w in ("ledger", "receipt", "manifest", "snapshot", "state", "task")):
        return False
    return True

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, required=True); args = ap.parse_args()
    out = args.out.resolve(); shutil.rmtree(out, ignore_errors=True); out.mkdir(parents=True)
    inventory=[]
    for top in sorted(ALLOW):
        src=ROOT/top
        if not src.exists(): continue
        for p in src.rglob("*"):
            if not p.is_file(): continue
            rel=p.relative_to(ROOT)
            if not safe(rel): continue
            dst=out/rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p,dst)
            inventory.append({"path":str(rel),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
    (out/"OPEN_SOURCE_INVENTORY.json").write_text(json.dumps({"schema":"qingshan.open_source_inventory.v1","files":inventory},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"PASS","out":str(out),"files":len(inventory)},ensure_ascii=False))
    return 0
if __name__ == "__main__": raise SystemExit(main())
