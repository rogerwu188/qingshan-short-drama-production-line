#!/usr/bin/env python3
"""Fix the bootstrap templates of a fresh nalu runtime root so S1-S8 can run (offline, idempotent).

Run AFTER lines/nalu/runtime/tools/bootstrap_runtime_root.py.  Each fix below was found on a real end-to-end run:
  1. runtime/nalu_entity_registry.json  template schema is wrong -> S2 crashes; rewritten with
     schema qingshan.entity_registry_extension.v1 and one [display_name, CHAR-ID] row per speaking character.
  2. runtime/asset_library.json         schema must be ai_drama.production_asset_library.v1 (identity lock) and
     project_id must equal the series id NALU-YEWUJIANG (S1 project_scope_check).
  3. runtime/series_scopes.json         child processes run CURRENT_PORTABLE and refuse to start without it.
  4. qingshan.json                      authorization block placeholder + episode budget cap (paid lock stays false).

usage: apply_runtime_fixups.py --runtime-root $NALU_RUNTIME_ROOT --character <角色名>=CHAR-<ID>:<pinyin_slug> \
           [--character ... ] [--cap <credits>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("fixed", path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-root", required=True)
    ap.add_argument("--character", action="append", default=[],
                    help="<display name>=<CHAR-ID>:<pinyin_slug>, one per speaking character")
    ap.add_argument("--cap", type=int, default=2500)
    a = ap.parse_args()
    root = Path(a.runtime_root).expanduser().resolve()
    rt = root / "runtime"

    aliases = {}
    for spec in a.character:
        name, _, rest = spec.partition("=")
        cid, _, slug = rest.partition(":")
        if not (name and cid and slug):
            raise SystemExit(f"bad --character {spec}")
        aliases[slug] = [name, cid]
    if aliases:
        dump(rt / "nalu_entity_registry.json", {"schema": "qingshan.entity_registry_extension.v1", "line": "nalu",
                                                "entity_aliases": aliases})

    lib = load(rt / "asset_library.json")
    lib["schema"] = "ai_drama.production_asset_library.v1"
    lib["project_id"] = "NALU-YEWUJIANG"
    dump(rt / "asset_library.json", lib)

    if not (rt / "series_scopes.json").is_file():
        dump(rt / "series_scopes.json", {"schema": "nalu.series_scopes.v1", "default_scope": "NALU-YEWUJIANG",
                                         "scopes": {}, "episodes": {}})

    cfg = load(root / "qingshan.json")
    gen = cfg.setdefault("generation", {})
    gen.setdefault("paid_requests_enabled", False)
    gen["budget_cap_credits_per_episode"] = a.cap
    cfg.setdefault("authorization", {"supervisor_orders_path": str(rt / "SUPERVISOR_ORDERS.json"),
                                     "paid_order_seq": 0, "latest_order_seq": 0, "line_owner_id": ""})
    dump(root / "qingshan.json", cfg)
    ledger = load(rt / "budget" / "ledger.json")
    if ledger:
        ledger["cap_credits_per_episode"] = a.cap
        dump(rt / "budget" / "ledger.json", ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
