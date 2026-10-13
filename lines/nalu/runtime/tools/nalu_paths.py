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

# Deployment pin (2026-10-10).  When a tool runs without NALU_RUNTIME_ROOT, the fallback below
# lands on the ENGINE checkout's own ``lines/nalu`` — which ships a character registry of a
# different work.  E11's Q1 submit ran exactly that way, read the wrong registry, measured no
# face, and recorded 26 identity P0s.  A deployment writes its roots ONCE into this gitignored
# file (``nalu_paths.py pin``), so every tool resolves the same roots whichever shell starts it.
DEPLOYMENT_PIN = ENGINE_ROOT / ".nalu_deployment.json"


def _pinned(key: str) -> Path | None:
    # NALU_IGNORE_DEPLOYMENT_PIN=1 lets a test check the clean-clone fallback on a deployed machine.
    if os.environ.get("NALU_IGNORE_DEPLOYMENT_PIN") == "1":
        return None
    try:
        import json as _json
        value = (_json.loads(DEPLOYMENT_PIN.read_text(encoding="utf-8")) or {}).get(key)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return Path(value).expanduser() if value else None


RUNTIME_ROOT: Path = (_env("NALU_RUNTIME_ROOT", "RUNTIME_ROOT") or _pinned("runtime_root")
                      or TOOLS_DIR.parents[1])
RUNTIME_ROOT_SOURCE = ("environment" if _env("NALU_RUNTIME_ROOT", "RUNTIME_ROOT")
                       else "deployment_pin" if _pinned("runtime_root") else "fallback_beside_tools")
# The per-episode worktree.  One definition: nalu_pipeline and nalu_qa_common defaulted it to
# <engine>/workflow/nalu while prompt_batch_qa / _finalize / _register defaulted it to
# <runtime>/workflow/nalu, so the same command worked from one shell and not another.
WORK_ROOT: Path = (_env("NALU_WORK_ROOT") or _pinned("work_root") or ENGINE_ROOT / "workflow" / "nalu")
VOICE_REGISTRY: Path = (_env("QINGSHAN_VOICE_REGISTRY") or _pinned("voice_registry")
                        or RUNTIME_ROOT / "runtime" / "voice_registry.json")
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
        "ENGINE_ROOT": str(ENGINE_ROOT), "RUNTIME_ROOT": str(RUNTIME_ROOT),
        "RUNTIME_ROOT_SOURCE": RUNTIME_ROOT_SOURCE, "WORK_ROOT": str(WORK_ROOT),
        "VOICE_REGISTRY": str(VOICE_REGISTRY), "TOOLS_DIR": str(TOOLS_DIR),
        "VENV_PYTHON": str(VENV_PYTHON), "RUNTIME_DIR": str(RUNTIME_DIR), "PREPRO_ROOT": str(PREPRO_ROOT),
        "engine_root_detected": str(bool((ENGINE_ROOT / "qingshan_engine").is_dir())),
    }


def pin(runtime_root: str, work_root: str | None = None, voice_registry: str | None = None) -> dict:
    """Write the deployment pin (machine-local, gitignored; holds paths, never credentials)."""
    import json as _json
    runtime = Path(runtime_root).expanduser().resolve()
    if not (runtime / "runtime").is_dir():
        raise SystemExit(f"REFUSED: {runtime} has no runtime/ directory; not a nalu runtime root")
    payload = {"schema": "nalu.deployment_pin.v1", "runtime_root": str(runtime),
               "work_root": str(Path(work_root).expanduser().resolve() if work_root
                                else ENGINE_ROOT / "workflow" / "nalu"),
               "voice_registry": str(Path(voice_registry).expanduser().resolve() if voice_registry
                                     else runtime / "runtime" / "voice_registry.json"),
               "note": "paths only; credentials and order coordinates stay in the deployment environment"}
    DEPLOYMENT_PIN.write_text(_json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    import json
    if len(sys.argv) >= 2 and sys.argv[1] == "pin":
        import argparse
        ap = argparse.ArgumentParser(prog="nalu_paths.py pin")
        ap.add_argument("pin")
        ap.add_argument("--runtime-root", required=True)
        ap.add_argument("--work-root")
        ap.add_argument("--voice-registry")
        a = ap.parse_args()
        print(json.dumps(pin(a.runtime_root, a.work_root, a.voice_registry), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(describe(), ensure_ascii=False, indent=2))
