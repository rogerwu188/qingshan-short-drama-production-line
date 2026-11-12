#!/usr/bin/env python3
"""Which account production bills: fingerprints only, never key values (fleet diagnose).

Line owner 2026-11-12 (after checking with the boss): StoryClaw agent turns, Codex, gpt-image and H3 video
all bill ONE HopsAPI credit pool -- the StoryClaw account; a separate setup key is only an edge case.  So
nothing here blocks: ``report`` tells a maintainer whether the Codex / video key is the StoryClaw platform
key or a separate one, so a billing question is answered from facts (2026-11-12 took hours without them).

usage: billing_key_guard.py report           JSON for fleet diagnose (provenance, never values)
       billing_key_guard.py check-env NAME   exit 0 = separate key, 3 = StoryClaw platform key, 2 = unset
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

KEY_FIELD = re.compile(r"^(api_?key|apikey|key|token|access_?token|secret)$", re.I)
MAX_FILE_BYTES = 2_000_000
SKIP_DIRS = {"shared", "workspace", "workspaces", "sessions", "logs", "media", "node_modules", "cache"}
BLOCKER = "STORYCLAW_PLATFORM_KEY"  # check-env status for a platform key (informational)


def digest(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _walk_values(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and KEY_FIELD.match(str(k)) and len(v.strip()) >= 16:
                out.add(digest(v))
            else:
                _walk_values(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_values(v, out)


def _config_files(root: Path, depth: int = 4) -> Iterable[Path]:
    if depth < 0 or not root.is_dir():
        return
    for p in root.iterdir():
        if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."):
            yield from _config_files(p, depth - 1)
        elif p.is_file() and p.suffix == ".json":
            yield p


def platform_digests(home: Path | None = None) -> set[str]:
    """SHA-256 of every credential-looking string in the OpenClaw / StoryClaw configuration."""
    home = home or Path.home()
    out: set[str] = set()
    for root in (home / ".openclaw", home / ".storyclaw"):
        for path in _config_files(root):
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                _walk_values(json.loads(path.read_text(encoding="utf-8")), out)
            except (OSError, ValueError):
                continue
    return out


def is_platform_key(value: str | None, home: Path | None = None) -> bool:
    return bool(value and value.strip()) and digest(value) in platform_digests(home)


def _env_file_value(path: Path, name: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(rf"^\s*(?:export\s+)?{re.escape(name)}=(.*)$", text, re.M)
    return m.group(1).strip().strip("'\"") if m else ""


def report(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or home / "nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or home / "nalu_runtime").expanduser()
    platform = platform_digests(home)
    try:
        codex = str(json.loads((runtime / "credentials" / "llm_provider.json").read_text(encoding="utf-8"))
                    .get("api_key") or "")
    except (OSError, ValueError):
        codex = ""
    hops = _env_file_value(engine / ".env", "HOPSAPI_API_KEY")
    effective = hops or codex  # paid_stage.sh: .env first, then the Codex provider key
    return {
        "platform_keys_found": len(platform),
        "codex_key_present": bool(codex), "codex_key_is_storyclaw": bool(codex) and digest(codex) in platform,
        "hopsapi_key_source": ".env" if hops else ("llm_provider.json" if codex else "none"),
        "hopsapi_key_is_storyclaw": bool(effective) and digest(effective) in platform,
        "hopsapi_equals_codex": bool(hops and codex) and digest(hops) == digest(codex),
    }


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "check-env":
        value = os.environ.get(argv[1], "")
        if not value.strip():
            print(json.dumps({"status": "UNSET", "name": argv[1]}))
            return 2
        if is_platform_key(value):
            print(json.dumps({"status": BLOCKER, "name": argv[1]}))
            return 3
        print(json.dumps({"status": "OWN_KEY", "name": argv[1]}))
        return 0
    if argv == ["report"]:
        print(json.dumps(report(), ensure_ascii=False))
        return 0
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
