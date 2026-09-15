#!/usr/bin/env python3
"""intake_character_sources.py — register the deployer's likeness photos as character source references.

What a production line actually did by hand (2026-09-09 … 09-13), made repeatable:

* the deployer drops photos in a folder and tells the agent which character each one is for;
* every binding is written to ``<runtime>/runtime/character_source_map.json`` with the file's sha256, byte
  size, usage (``FACE_IDENTITY_REFERENCE`` / ``FACE_AND_WARDROBE_REFERENCE``), the deployer's likeness-rights
  note (verbatim, never verified by the engine) and an adaptation note;
* the production copy is placed at ``<runtime>/runtime/character_sources/<CHAR-ID>__SOURCE_V2_TANG.png``
  (the name the identity bootstrapper's ``SOURCE_V2`` face-as-is policy keys on); originals stay untouched and
  a copy is parked under ``<runtime>/runtime/character_sources_hold/`` (never committed).

It does NOT crop faces, de-age, restyle or measure likeness — those were paid or manual steps
(MANUAL_REQUIRED) on the line that used this.  No network, no provider, no credentials.
Status: REFERENCE_IMPLEMENTATION.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

USAGES = ("FACE_IDENTITY_REFERENCE", "FACE_AND_WARDROBE_REFERENCE")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runtime", required=True, help="$RUNTIME_ROOT (contains runtime/)")
    ap.add_argument("--bind", action="append", required=True, metavar="CHAR-ID=path[:usage]",
                    help="e.g. CHAR-LEAD=/photos/lead.png:FACE_AND_WARDROBE_REFERENCE (repeatable)")
    ap.add_argument("--rights-note", required=True, help="deployer's likeness-rights statement, recorded verbatim")
    ap.add_argument("--authorization", default="", help="order / instruction reference (e.g. SUPERVISOR_ORDERS seq)")
    ap.add_argument("--suffix", default="SOURCE_V2_TANG", help="production copy suffix (bootstrapper policy key)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    runtime = Path(args.runtime).resolve()
    sources = runtime / "runtime" / "character_sources"
    hold = runtime / "runtime" / "character_sources_hold"
    map_path = runtime / "runtime" / "character_source_map.json"
    existing = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else {
        "schema": "nalu.character_source_map.v1", "bindings": []}
    by_id = {row.get("character_id"): row for row in existing.get("bindings") or []}

    plan = []
    for spec in args.bind:
        if "=" not in spec:
            raise SystemExit(f"--bind must be CHAR-ID=path[:usage]: {spec}")
        char_id, rest = spec.split("=", 1)
        path_str, _, usage = rest.rpartition(":") if rest.count(":") and rest.rsplit(":", 1)[-1] in USAGES else (rest, "", "")
        usage = usage or "FACE_IDENTITY_REFERENCE"
        src = Path(path_str).expanduser().resolve()
        if not src.is_file():
            raise SystemExit(f"photo not found: {src}")
        if usage not in USAGES:
            raise SystemExit(f"usage must be one of {USAGES}: {usage}")
        plan.append({"character_id": char_id.strip(), "file": str(src), "usage": usage,
                     "sha256": sha256_file(src), "bytes": src.stat().st_size,
                     "production_copy": str(sources / f"{char_id.strip()}__{args.suffix}{src.suffix.lower() if src.suffix.lower() in ('.png', '.jpg', '.jpeg') else '.png'}"),
                     "hold_copy": str(hold / src.name),
                     "likeness_rights_note": args.rights_note, "authorization": args.authorization,
                     "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})

    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", "bindings": plan}, ensure_ascii=False, indent=2))
        return 0

    sources.mkdir(parents=True, exist_ok=True)
    hold.mkdir(parents=True, exist_ok=True)
    for row in plan:
        shutil.copy2(row["file"], row["hold_copy"])
        shutil.copy2(row["file"], row["production_copy"])
        by_id[row["character_id"]] = row
    existing["bindings"] = [by_id[key] for key in sorted(by_id)]
    existing["recorded_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    existing.setdefault("note", "the engine records the deployer's likeness-rights statement; it does not verify it. "
                                "character_sources_hold/ must never be committed.")
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "WRITTEN", "map": str(map_path), "bindings": len(existing["bindings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
