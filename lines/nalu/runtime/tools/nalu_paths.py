#!/usr/bin/env python3
"""Portable path resolution for the nalu line tools.

Every tool in this directory used to carry the deployment machine's absolute paths.
They now import the constants below.  Resolution order for each root:

1. environment variable (first match wins):
     ENGINE_ROOT   NALU_ENGINE_ROOT, QINGSHAN_ENGINE_ROOT, ENGINE_ROOT
     RUNTIME_ROOT  NALU_RUNTIME_ROOT, RUNTIME_ROOT
     VENV_PYTHON   NALU_VENV_PYTHON
2. auto-detection relative to this file:
     ENGINE_ROOT   nearest ancestor that contains both ``qingshan_engine/`` and ``tools/``
                   (true when the tools run from a checkout of the engine repository under
                   ``lines/nalu/runtime/tools``)
     RUNTIME_ROOT  the directory two levels above ``tools/`` (``<RUNTIME_ROOT>/runtime/tools``)
     VENV_PYTHON   ``<ENGINE_ROOT>/.qingshan-venv/bin/python`` when it exists, else the
                   interpreter running this process

A production instance whose runtime lives outside the engine checkout MUST set
NALU_ENGINE_ROOT (there is deliberately no sibling-directory guess: a machine may hold
more than one engine checkout).  Keep the runtime STATE (preproduction/, sources/, the
asset library, ledgers, reviews) out of the repository by pointing NALU_RUNTIME_ROOT at a
separate directory; the tools themselves are always located via TOOLS_DIR.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
TOOLS_DIR = _HERE.parent                      # .../runtime/tools
REVIEW_FILL_DIR = TOOLS_DIR / "review_fill"


def _env(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def _find_engine_root() -> Path | None:
    for candidate in (_HERE, *_HERE.parents):
        if (candidate / "qingshan_engine").is_dir() and (candidate / "tools").is_dir():
            return candidate
    return None


ENGINE_ROOT: Path = _env("NALU_ENGINE_ROOT", "QINGSHAN_ENGINE_ROOT", "ENGINE_ROOT") or _find_engine_root() or Path.cwd()
RUNTIME_ROOT: Path = _env("NALU_RUNTIME_ROOT", "RUNTIME_ROOT") or TOOLS_DIR.parents[1]
_venv_default = ENGINE_ROOT / ".qingshan-venv" / "bin" / "python"
VENV_PYTHON: Path = _env("NALU_VENV_PYTHON") or (_venv_default if _venv_default.exists() else Path(sys.executable))

ENGINE_TOOLS = ENGINE_ROOT / "tools"
WORKFLOW_ROOT = ENGINE_ROOT / "workflow"
WRITER_SCRIPTS = WORKFLOW_ROOT / "claude_writer_agent" / "scripts"
SUPERVISOR_ORDERS = WORKFLOW_ROOT / "claude_writer_agent" / "SUPERVISOR_ORDERS.json"
AGENTCUT = ENGINE_ROOT / ".agentcut_env" / "bin" / "agentcut"

RUNTIME_DIR = RUNTIME_ROOT / "runtime"        # state + registries + ledgers live here
PREPRO_ROOT = RUNTIME_ROOT / "preproduction"
SOURCES_ROOT = RUNTIME_ROOT / "sources"
BRAND_ROOT = RUNTIME_ROOT / "brand"


def describe() -> dict[str, str]:
    return {
        "ENGINE_ROOT": str(ENGINE_ROOT), "RUNTIME_ROOT": str(RUNTIME_ROOT), "TOOLS_DIR": str(TOOLS_DIR),
        "VENV_PYTHON": str(VENV_PYTHON), "RUNTIME_DIR": str(RUNTIME_DIR), "PREPRO_ROOT": str(PREPRO_ROOT),
        "engine_root_detected": str(bool((ENGINE_ROOT / "qingshan_engine").is_dir())),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
