#!/usr/bin/env python3
"""Install the OpenAI Codex CLI and point it at the LLM provider the line owner gave the agent.

Line owner 2026-10-13: the miniPCs produce with Codex only (gpt-6.1-sol since 2026-10-16; was gpt-5.6), and the provider URL + key are
asked from the owner once at first setup instead of being copied from the StoryClaw/OpenClaw config.

* Provider: ``$NALU_RUNTIME_ROOT/credentials/llm_provider.json`` (mode 600, written by the agent):
  ``{"base_url": "https://…/v1", "api_key": "…", "model": "gpt-6.1-sol"}``.  The relay must speak the
  OpenAI Responses API over plain HTTP.  Hosts that predate this file (``credentials/codex_api_key`` +
  an existing ~/.codex/config.toml) are migrated once, keeping their URL and model.
* The key never goes into config.toml and is never printed: codex_production.py hands it to codex as
  $HOPS_API_KEY, and the shell policy keeps it (and GIGGLE_API_KEY) out of every command Codex runs.
* ``@openai/codex`` is installed with npm (user prefix) when ``codex`` is not on PATH.
* ``--verify`` sends one tiny prompt through the provider.

Ends with one line:  CODEX_CONFIG: {"status": "CONFIGURED|VERIFIED|NEEDS_PROVIDER|BLOCKED|VERIFY_FAILED", ...}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DEFAULT_MODEL = "gpt-6.1-sol"
#: earlier defaults, written verbatim into every provider file; line owner 2026-10-16: "默认 codex 模型都用 GPT 6.1 Sol"
#: so they follow the default.  Applied when setup reconfigures Codex (not while an episode is in flight).
RETIRED_DEFAULT_MODELS = frozenset({"gpt-5.6"})
KEY_ENV = "HOPS_API_KEY"  # the name codex_production.py exports; kept for hosts configured before 2026-10-13


def say(status: str, **kw: object) -> int:
    print("CODEX_CONFIG: " + json.dumps({"status": status, **kw}, ensure_ascii=False))
    return 0 if status in ("CONFIGURED", "VERIFIED") else 2


def toml_value(text: str, key: str) -> str:
    m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', text, re.M)
    return m.group(1) if m else ""


def load_provider(cred: Path, cfg: Path) -> dict[str, str] | None:
    path = cred / "llm_provider.json"
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        p = {}
    if p.get("base_url") and p.get("api_key"):
        os.chmod(path, 0o600)
        return {"base_url": str(p["base_url"]).rstrip("/"), "api_key": str(p["api_key"]).strip(),
                # "model_locked": true keeps a retired default as written (e.g. one episode measured per model)
                "model": (DEFAULT_MODEL if str(p.get("model") or "") in RETIRED_DEFAULT_MODELS
                          and not p.get("model_locked")
                          else str(p.get("model") or DEFAULT_MODEL))}
    legacy = cred / "codex_api_key"
    old = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    if legacy.is_file() and legacy.read_text(encoding="utf-8").strip() and toml_value(old, "base_url"):
        p = {"base_url": toml_value(old, "base_url").rstrip("/"), "api_key": legacy.read_text(encoding="utf-8").strip(),
             "model": toml_value(old, "model") or DEFAULT_MODEL, "migrated_from": "credentials/codex_api_key"}
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
        return p
    return None


def ensure_codex() -> str | None:
    os.environ["PATH"] = f"{Path.home()}/.local/bin:{Path.home()}/.npm-global/bin:" + os.environ.get("PATH", "")
    if not shutil.which("codex") and shutil.which("npm"):
        prefix = subprocess.run(["npm", "config", "get", "prefix"], capture_output=True, text=True).stdout.strip()
        if not prefix.startswith(str(Path.home())):
            subprocess.run(["npm", "config", "set", "prefix", str(Path.home() / ".npm-global")], capture_output=True)
        subprocess.run(["npm", "install", "-g", "@openai/codex"], capture_output=True)
    return shutil.which("codex")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="send one tiny prompt through the provider")
    a = ap.parse_args()

    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    cred = runtime / "credentials"
    cfg = Path.home() / ".codex" / "config.toml"
    p = load_provider(cred, cfg)
    if not p:
        return say("NEEDS_PROVIDER", file=str(cred / "llm_provider.json"),
                   hint='ask the line owner for the provider base URL and API key; write '
                        '{"base_url","api_key","model":"gpt-6.1-sol"} there with mode 600')
    exe = ensure_codex()
    if not exe:
        return say("BLOCKED", reason="CODEX_INSTALL_FAILED" if shutil.which("npm") else "NPM_MISSING_CANNOT_INSTALL_CODEX")
    version = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()

    cfg.parent.mkdir(parents=True, exist_ok=True)
    if cfg.is_file() and not cfg.read_text(encoding="utf-8").startswith("# NALU"):
        cfg.with_name("config.toml.before_nalu").write_text(cfg.read_text(encoding="utf-8"), encoding="utf-8")
    cfg.write_text(f'''# NALU configure_codex.py — production executor for the 短剧工作流 agent. The key is only in ${KEY_ENV}.
model_provider = "nalu"
model = "{p['model']}"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "danger-full-access"

[model_providers.nalu]
name = "nalu-provider"
base_url = "{p['base_url']}"
env_key = "{KEY_ENV}"
wire_api = "responses"
supports_websockets = false
request_max_retries = 6
stream_max_retries = 10
stream_idle_timeout_ms = 600000

[shell_environment_policy]
inherit = "all"
# never hand Codex's own key or the Giggle key to the commands it runs
exclude = ["{KEY_ENV}", "GIGGLE_API_KEY", "OPENAI_API_KEY"]

[projects."{engine}"]
trust_level = "trusted"
''', encoding="utf-8")
    info = {"codex": version, "model": p["model"], "base_url": p["base_url"], "key_tail": p["api_key"][-4:],
            "config": str(cfg)}
    if not a.verify:
        return say("CONFIGURED", **info)

    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env[KEY_ENV] = p["api_key"]
    with tempfile.TemporaryDirectory() as tmp:
        last = Path(tmp) / "last.txt"
        try:
            r = subprocess.run([exe, "exec", "--skip-git-repo-check", "-o", str(last), "Reply with exactly: OK"],
                               cwd=tmp, env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            reply = last.read_text(encoding="utf-8").strip() if last.is_file() else ""
            err = (r.stderr or r.stdout or "")[-300:]
        except subprocess.TimeoutExpired:
            reply, err = "", "timeout after 180 s"
    if "OK" in reply:
        return say("VERIFIED", **info)
    return say("VERIFY_FAILED", **info, detail=err.replace(p["api_key"], "***"))


if __name__ == "__main__":
    raise SystemExit(main())
