#!/usr/bin/env python3
"""Shared configuration loader for the Qingshan StoryClaw bridge."""

from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from typing import Optional


DEFAULT_BASE_URL = "https://qingshan-bridge-api.rogerwu188.workers.dev"
KEYCHAIN_SERVICE = "qingshan-storyclaw-bridge"
DEFAULT_MODE_FILE = (
    Path(__file__).resolve().parents[1]
    / "workflow"
    / "SUPERVISOR_COMMUNICATION_MODE.json"
)


def base_url() -> str:
    return os.environ.get("STORYCLAW_BRIDGE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def token(env_name: str = "STORYCLAW_BRIDGE_TOKEN") -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            env_name,
            "-w",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def communication_mode(path: Optional[Path] = None) -> dict:
    mode_path = path or Path(
        os.environ.get("QINGSHAN_SUPERVISOR_MODE_FILE", DEFAULT_MODE_FILE)
    )
    try:
        return json.loads(mode_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "mode": "DUAL_ASYNC",
            "storyclaw_remote": {
                "read_enabled": True,
                "write_enabled": True,
            },
        }


def storyclaw_reads_enabled(path: Optional[Path] = None) -> bool:
    if os.environ.get("STORYCLAW_BRIDGE_FORCE") == "1":
        return True
    remote = communication_mode(path).get("storyclaw_remote", {})
    return bool(remote.get("read_enabled", True))


def storyclaw_writes_enabled(path: Optional[Path] = None) -> bool:
    if os.environ.get("STORYCLAW_BRIDGE_FORCE") == "1":
        return True
    remote = communication_mode(path).get("storyclaw_remote", {})
    return bool(remote.get("write_enabled", True))
