#!/usr/bin/env python3
"""Write side of the engineering knowledge base — the pipeline upgrades it itself.

`tools/knowledge_registry.py` is deliberately read-only: it validates and exports.
Nothing could therefore append to `configs/ENGINEERING_KNOWLEDGE_V1.json`, so the
knowledge base was write-only in theory and unwritten in practice — E02/E03/E07
finished with zero entries and no stage ever failed for it.  This tool is the
missing writer, called by S8 (see `nalu_pipeline.stage_s8`).

Three things it guarantees, because the alternative is a registry that CI rejects:
  1. Every row it writes passes `knowledge_registry.validate` — the registry, the
     markdown section and `knowledge/failure_memory.jsonl` are regenerated together
     and never allowed to drift apart.
  2. It is idempotent.  A row is keyed by its own id ("K0NN"); re-running an episode
     re-derives the same candidate ids and appends nothing new.
  3. It refuses to write a row it cannot make honest.  A candidate with no real
     `recovery` and no real `implementation` is reported as a gap for a human to
     fill, never padded with filler text to look complete.

It never writes an absolute path, a task id or a credential into the registry —
`tools/tests/test_knowledge_registry.py::test_no_personal_paths_or_live_task_identifiers`
forbids those tokens, and a row that would introduce one is rejected here first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_sys = sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402  portable ENGINE_ROOT / RUNTIME_ROOT

# The writer itself is line-agnostic and lives in the engine as
# `tools/knowledge_sync_core.py` (shared by every production line through
# `tools/line_upgrade_gate.py close`).  This file keeps the nalu CLI and module
# surface unchanged: every name below is the shared implementation.
def _load_core():
    import importlib.util as _ilu
    here = Path(__file__).resolve()
    for tools_dir in (here.parents[4] / "tools" if len(here.parents) > 4 else None,
                      Path(f"{_np.ENGINE_ROOT}") / "tools"):
        if tools_dir is None:
            continue
        path = tools_dir / "knowledge_sync_core.py"
        if path.is_file():
            spec = _ilu.spec_from_file_location("knowledge_sync_core", path)
            module = _ilu.module_from_spec(spec)
            _sys.modules.setdefault("knowledge_sync_core", module)
            spec.loader.exec_module(module)
            return module
    raise ImportError("knowledge_sync_core.py not found next to this checkout or under ENGINE_ROOT/tools")


_core = _load_core()
REGISTRY = _core.REGISTRY
MARKDOWN = _core.MARKDOWN
FAILURE_MEMORY = _core.FAILURE_MEMORY
DECISION_RECORD = _core.DECISION_RECORD
REGRESSION = _core.REGRESSION
_HOME_PREFIX = _core._HOME_PREFIX
FORBIDDEN_TOKENS = _core.FORBIDDEN_TOKENS
STATUSES = _core.STATUSES
_read_json = _core._read_json
_next_id = _core._next_id
_clean = _core._clean
candidates_from_evidence = _core.candidates_from_evidence
assign_ids = _core.assign_ids
_row_for_registry = _core._row_for_registry
_markdown_section = _core._markdown_section
sync = _core.sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--root", type=Path, default=_np.ENGINE_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=_np.RUNTIME_ROOT)
    parser.add_argument("--from-file", type=Path, help="extra rows (agent-authored) to merge")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    extra = _read_json(args.from_file, []) if args.from_file else []
    if not isinstance(extra, list):
        print(json.dumps({"status": "FAIL", "error": "FROM_FILE_NOT_A_LIST"}))
        return 1
    try:
        result = sync(args.root.resolve(), args.runtime_root.resolve(), args.episode,
                      extra=extra, dry_run=args.dry_run)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
