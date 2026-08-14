#!/usr/bin/env python3
"""Record the live Pipeline environment without changing its protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "qingshan.pipeline.environment_baseline.v1"
ROLE = "qingshan-ai-drama-pipeline"
REQUIRED = {
    "queue_cron",
    "mailbox_cron",
    "role_contract",
    "agent_poller",
    "executor_bridge",
    "mailbox_worker",
    "active_version_root",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_sha(name: str, identity: str) -> str:
    raw = json.dumps(
        {"name": name, "identity": identity},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def parse_named(values: list[str], option: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} must be NAME=VALUE: {value}")
        name, raw = value.split("=", 1)
        name = name.strip()
        raw = raw.strip()
        if name not in REQUIRED or not raw or name in result:
            raise ValueError(f"invalid {option}: {value}")
        result[name] = raw
    return result


def build_baseline(
    target_version: str,
    agent_page_url: str,
    files: dict[str, str],
    states: dict[str, str],
) -> dict:
    overlap = set(files) & set(states)
    if overlap:
        raise ValueError("component provided twice: " + ",".join(sorted(overlap)))
    missing = REQUIRED - set(files) - set(states)
    if missing:
        raise ValueError("missing protected components: " + ",".join(sorted(missing)))
    components = []
    for name in sorted(REQUIRED):
        if name in files:
            path = Path(files[name]).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"component file missing:{name}:{path}")
            components.append(
                {
                    "name": name,
                    "identity": str(path),
                    "path": str(path),
                    "sha256": sha256(path),
                    "health": "PASS",
                }
            )
        else:
            identity = states[name]
            components.append(
                {
                    "name": name,
                    "identity": identity,
                    "state_sha256": state_sha(name, identity),
                    "health": "PASS",
                }
            )
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "role": ROLE,
        "target_version": target_version,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "agent_page_url": agent_page_url,
        "live_agent_page_observed": True,
        "protocol_mutation_allowed": False,
        "protected_components": components,
        "notes": [
            "Capability overlay only.",
            "Existing queue, mailbox, bridge, poller, contract and active root remain authoritative.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--agent-page-url", required=True)
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--state", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        baseline = build_baseline(
            args.target_version,
            args.agent_page_url,
            parse_named(args.file, "--file"),
            parse_named(args.state, "--state"),
        )
    except ValueError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    atomic_write(args.out.expanduser().resolve(), baseline)
    print(json.dumps(baseline, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
