#!/usr/bin/env python3
"""Create a fresh nalu runtime root from the templates (idempotent, offline).

    python3 bootstrap_runtime_root.py --runtime-root /path/to/my_runtime [--line-id my-line] [--work "My Work"]

Creates the directory layout the tools expect and installs every ``templates/*.TEMPLATE.json`` as its
runtime file name, never overwriting a file that already exists.  Nothing is downloaded and nothing is
paid: character photos, the licensed source text, provider credentials and the brand end card are the
line owner's inputs and are listed at the end as TODO items.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"

LAYOUT = [
    "runtime", "runtime/budget", "runtime/configs", "runtime/pipeline_state", "runtime/pipeline_state/approvals",
    "runtime/pipeline_logs", "runtime/reports", "runtime/reviews", "runtime/character_sources",
    "runtime/character_sources_hold", "runtime/casting", "runtime/voice_refs", "preproduction", "sources",
    "brand", "deliverables", "working_assets",
]
INSTALL = {  # template stem -> relative install path
    "asset_library": "runtime/asset_library.json",
    "nalu_character_asset_registry": "runtime/nalu_character_asset_registry.json",
    "nalu_entity_registry": "runtime/nalu_entity_registry.json",
    "character_source_map": "runtime/character_source_map.json",
    "episode_source_map": "runtime/episode_source_map.json",
    "voice_catalog": "runtime/voice_catalog.json",
    "voice_registry": "runtime/voice_registry.json",
    "agentcut_character_voice_reference_policy": "runtime/agentcut_character_voice_reference_policy.json",
    "budget_ledger": "runtime/budget/ledger.json",
}
POLICY_CONFIGS = ["BASIC_DIALOGUE_QA_POLICY.json", "GATE_REGISTRY_STILL_SCOPED_D13.json"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runtime-root", required=True)
    ap.add_argument("--line-id", default="my-line")
    ap.add_argument("--work", default="")
    a = ap.parse_args()
    root = Path(a.runtime_root).expanduser().resolve()
    created, kept = [], []
    for rel in LAYOUT:
        (root / rel).mkdir(parents=True, exist_ok=True)
    for stem, rel in INSTALL.items():
        src = TEMPLATES / f"{stem}.TEMPLATE.json"
        dst = root / rel
        if dst.exists():
            kept.append(rel); continue
        payload = json.loads(src.read_text(encoding="utf-8"))
        for key, value in (("line", a.line_id), ("work", a.work)):
            if key in payload and isinstance(payload[key], str) and payload[key].startswith("<") and value:
                payload[key] = value
        dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(rel)
    for name in POLICY_CONFIGS:
        src = HERE.parent / "configs" / name
        dst = root / "runtime" / "configs" / name
        if src.is_file() and not dst.exists():
            shutil.copy2(src, dst); created.append(f"runtime/configs/{name}")
        elif dst.exists():
            kept.append(f"runtime/configs/{name}")
    todo = [
        "runtime/character_sources/<CHAR-ID>__SOURCE_V2_TANG.png  (one frontal photo per character; register with tools/intake_character_sources.py)",
        "sources/<work>/  (licensed source text; ingest with ingest tooling, NALU_SOURCE_TXT)",
        "brand/  (9:16 end card PNG / 3 s mp4 used by S7)",
        "$ENGINE_ROOT/.env  (GIGGLE_API_KEY, GIGGLE_API_BASE) and $ENGINE_ROOT/qingshan.json (generation.paid_requests_enabled = second money lock)",
        "runtime/voice_catalog.json  (pick a provider voice per speaking character after `agentcut speech-voices`)",
    ]
    print(json.dumps({"status": "PASS", "runtime_root": str(root), "created": created, "kept_existing": kept,
                      "owner_inputs_todo": todo,
                      "next": "export NALU_RUNTIME_ROOT=<runtime_root> NALU_ENGINE_ROOT=<engine checkout>; "
                              "python3 nalu_pipeline.py status --episode E01"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
