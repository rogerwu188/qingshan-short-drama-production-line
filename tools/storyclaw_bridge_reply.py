#!/usr/bin/env python3
"""Send a Codex reply directly to the StoryClaw bridge mailbox.

This is the outgoing counterpart to storyclaw_outbox_poller.py. It writes a
local immutable copy for audit, then uploads that exact reply file to the
StoryClaw bridge so StoryClaw can consume the response without reading any
local Codex mailbox.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


from storyclaw_bridge_config import base_url as configured_base_url
from storyclaw_bridge_config import storyclaw_writes_enabled
from storyclaw_bridge_config import token as configured_token


DEFAULT_BASE_URL = configured_base_url()
DEFAULT_OUTDIR = "/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_bridge_outgoing"


def safe_slug(text: str) -> str:
    allowed = []
    for ch in text.strip().replace(" ", "_"):
        if ch.isalnum() or ch in ("_", "-", "."):
            allowed.append(ch)
    slug = "".join(allowed).strip("._-")
    return slug[:80] or "reply"


def upload(path: Path, bridge_name: str, base_url: str, token: str) -> dict:
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            "-F",
            f"file=@{path};filename={bridge_name}",
            f"{base_url.rstrip('/')}/upload?token={token}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip(), "bridge_name": bridge_name}
    try:
        data = json.loads(result.stdout)
        data.setdefault("bridge_name", bridge_name)
        return data
    except json.JSONDecodeError:
        return {"ok": False, "error": "non_json_response", "stdout": result.stdout[:500], "bridge_name": bridge_name}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reply directly to StoryClaw bridge mailbox.")
    parser.add_argument("--id", required=True, help="Stable outgoing id, e.g. C2SC-071")
    parser.add_argument("--title", required=True)
    parser.add_argument("--status", default="DONE")
    parser.add_argument("--body-file", help="Read body from a UTF-8 text/markdown file.")
    parser.add_argument("--body", help="Reply body text. If omitted, stdin is used.")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token-env", default="STORYCLAW_BRIDGE_TOKEN")
    args = parser.parse_args()

    if not storyclaw_writes_enabled():
        print(
            json.dumps(
                {
                    "ok": False,
                    "disabled": True,
                    "mode": "LOCAL_CLAUDE_PRIMARY",
                    "remote_request_performed": False,
                    "id": args.id,
                },
                ensure_ascii=False,
            )
        )
        return 0

    token = configured_token(args.token_env)
    if not token:
        raise SystemExit(f"Missing token env: {args.token_env}")

    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    elif args.body is not None:
        body = args.body
    else:
        body = sys.stdin.read()

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{args.id}_{safe_slug(args.title)}_{ts}.md"
    local = outdir / filename
    text = "\n".join(
        [
            f"# {args.id} | Codex -> StoryClaw | {args.status} | {args.title}",
            "",
            f"- created_at: {datetime.now().isoformat(timespec='seconds')}",
            "- channel: StoryClaw bridge mailbox",
            "- local_copy_role: audit-only; StoryClaw should consume the uploaded bridge file",
            "",
            body.strip(),
            "",
        ]
    )
    local.write_text(text, encoding="utf-8")
    bridge_name = f"CODEX_TO_STORYCLAW__{filename}"
    response = upload(local, bridge_name, args.base_url, token)

    receipt = outdir / "STORYCLAW_BRIDGE_REPLY_RECEIPT.md"
    previous = receipt.read_text(encoding="utf-8") if receipt.exists() else "# StoryClaw Bridge Reply Receipt\n\n"
    entry = "\n".join(
        [
            f"## {args.id} {datetime.now().isoformat(timespec='seconds')}",
            f"- title: {args.title}",
            f"- local: `{local}`",
            f"- bridge_name: `{bridge_name}`",
            f"- upload_ok: `{bool(response.get('ok'))}`",
            f"- response: `{json.dumps(response, ensure_ascii=False)}`",
            "",
        ]
    )
    receipt.write_text(previous.rstrip() + "\n\n" + entry, encoding="utf-8")
    print(json.dumps({"ok": bool(response.get("ok")), "local": str(local), "bridge_name": bridge_name, "receipt": str(receipt)}, ensure_ascii=False))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
