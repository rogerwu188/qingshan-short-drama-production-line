#!/usr/bin/env python3
"""Point Claude Code at the StoryClaw LLM relay that this OpenClaw host already uses.

Line-owner requirement (2026-10-09): production runs unattended on a dedicated miniPC and the
initial setup needs no human at the terminal.  The OpenClaw agent therefore runs this once:

* reads the provider (default ``storyclaw``) from ``~/.openclaw/openclaw.json`` — ``baseUrl``,
  ``apiKey`` and, when listed, the first Claude model id;
* writes them into Claude Code's user settings ``~/.claude/settings.json`` (``env`` block, mode 600);
* sets a permission policy for unattended production: Bash/Read/Edit/Write are allowed, while
  privilege escalation, recursive deletes, remote shells, git push, publishing and any access to
  ``~/.openclaw`` are denied;
* marks Claude Code onboarding complete so headless ``claude -p`` never stops at a first-run screen.

The key is never printed (only its last 4 characters).  Nothing is sent anywhere unless
``--verify`` is given, which runs one tiny ``claude -p`` call through the relay.

usage: configure_claude_code.py [--openclaw-config ~/.openclaw/openclaw.json] [--provider storyclaw]
                                [--model <relay model id>] [--verify]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ALLOW = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite"]
DENY = [
    "Bash(sudo:*)", "Bash(su:*)", "Bash(rm -rf:*)", "Bash(rm -r:*)", "Bash(ssh:*)", "Bash(scp:*)",
    "Bash(git push:*)", "Bash(talenthub:*)", "Bash(npm publish:*)",
    "Read(~/.openclaw/**)", "Edit(~/.openclaw/**)", "Write(~/.openclaw/**)",
]


def find_provider(cfg: dict[str, Any], name: str) -> dict[str, Any] | None:
    """OpenClaw keeps providers under models.providers.<name>; fall back to a recursive search."""
    providers = (cfg.get("models") or {}).get("providers") or {}
    if isinstance(providers, dict) and isinstance(providers.get(name), dict):
        return providers[name]
    stack: list[Any] = [cfg]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            hit = node.get(name)
            if isinstance(hit, dict) and (hit.get("baseUrl") or hit.get("baseURL")):
                return hit
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def claude_model(provider: dict[str, Any]) -> str | None:
    for row in provider.get("models") or []:
        mid = str(row.get("id") if isinstance(row, dict) else row or "")
        if "claude" in mid.lower():
            return mid
    return None


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openclaw-config", default="~/.openclaw/openclaw.json")
    ap.add_argument("--provider", default="storyclaw")
    ap.add_argument("--model", default="", help="relay model id; default: first Claude model the provider lists")
    ap.add_argument("--verify", action="store_true", help="run one tiny claude -p call through the relay")
    a = ap.parse_args()

    if os.geteuid() == 0:
        print(json.dumps({"status": "BLOCKED", "reason": "RUN_AS_THE_OPENCLAW_USER_NOT_ROOT"}))
        return 2
    cfg = load(Path(a.openclaw_config).expanduser())
    if not cfg:
        print(json.dumps({"status": "BLOCKED", "reason": f"OPENCLAW_CONFIG_MISSING:{a.openclaw_config}"}))
        return 2
    provider = find_provider(cfg, a.provider)
    if not provider:
        print(json.dumps({"status": "BLOCKED", "reason": f"PROVIDER_NOT_FOUND:{a.provider}"}))
        return 2
    base = str(provider.get("baseUrl") or provider.get("baseURL") or "").rstrip("/")
    key = str(provider.get("apiKey") or provider.get("api_key") or "")
    if not base or not key:
        print(json.dumps({"status": "BLOCKED", "reason": "PROVIDER_BASEURL_OR_APIKEY_EMPTY"}))
        return 2
    model = a.model or claude_model(provider)

    home = Path.home()
    settings_path = home / ".claude" / "settings.json"
    settings = load(settings_path)
    env = settings.setdefault("env", {})
    env.update({"ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": key,
                "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
                # paid stages poll remote renders and run local QA for minutes at a time
                "BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "1800000"})
    if model:
        env.update({"ANTHROPIC_MODEL": model, "ANTHROPIC_SMALL_FAST_MODEL": model,
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": model})
    perms = settings.setdefault("permissions", {})
    perms["allow"] = sorted(set(perms.get("allow") or []) | set(ALLOW))
    perms["deny"] = sorted(set(perms.get("deny") or []) | set(DENY))
    save(settings_path, settings)

    state_path = home / ".claude.json"
    state = load(state_path)
    state["hasCompletedOnboarding"] = True
    responses = state.get("customApiKeyResponses") or {}
    state["customApiKeyResponses"] = {"approved": sorted(set(responses.get("approved") or []) | {key[-20:]}),
                                      "rejected": responses.get("rejected") or []}
    save(state_path, state)

    out: dict[str, Any] = {"status": "CONFIGURED", "settings": str(settings_path), "base_url": base,
                           "api_key": f"...{key[-4:]}", "model": model or "CLAUDE_CODE_DEFAULT",
                           "env_written": sorted(env), "deny": DENY}
    if a.verify:
        exe = shutil.which("claude")
        if not exe:
            out["status"] = "CONFIGURED_CLAUDE_NOT_INSTALLED"
        else:
            run = subprocess.run([exe, "-p", "Reply with exactly: OK", "--output-format", "json"],
                                 capture_output=True, text=True, timeout=180)
            try:
                reply = str(json.loads(run.stdout).get("result") or "")
            except ValueError:
                reply = run.stdout[-300:]
            ok = run.returncode == 0 and "OK" in reply
            out.update(status="VERIFIED" if ok else "VERIFY_FAILED", verify_exit=run.returncode,
                       verify_reply=reply[-200:].replace(key, "<key>"),
                       verify_stderr=run.stderr[-300:].replace(key, "<key>"))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["status"] in ("CONFIGURED", "VERIFIED") else 3


if __name__ == "__main__":
    sys.exit(main())
