#!/usr/bin/env python3
"""Poll StoryClaw bridge outbox, download new SC2X reports, and mirror them locally."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path


from storyclaw_bridge_config import base_url as configured_base_url
from storyclaw_bridge_config import storyclaw_reads_enabled
from storyclaw_bridge_config import token as configured_token


DEFAULT_BASE_URL = configured_base_url()


def curl_json(url: str) -> dict:
    result = subprocess.run(["curl", "-fsS", url], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def curl_download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-fsS", "-o", str(out), url], check=True)


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"seen": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepend_mailbox(mailbox: Path, report_name: str, report_path: Path, text: str) -> bool:
    mailbox.parent.mkdir(parents=True, exist_ok=True)
    old = mailbox.read_text(encoding="utf-8") if mailbox.exists() else "# 信箱:Claude → codex(append-only,新消息置顶;状态由 codex 更新)\n"
    if report_name in old:
        return False
    title = report_name.replace(".txt", "")
    entry = (
        "# 信箱:Claude → codex(append-only,新消息置顶;状态由 codex 更新)\n\n"
        f"## [{title}] {datetime.now().strftime('%Y-%m-%d')} | StoryClaw 云端监制 → codex | NEW_DOWNLOADED | 自动拉取待处理\n"
        f"- 来源文件: {report_path}\n"
        "- 处理状态: 已由 StoryClaw outbox poller 自动下载并回贴; codex 需按正文处理。\n\n"
        f"<{title}_FULL_TEXT>\n{text}\n</{title}_FULL_TEXT>\n\n"
    )
    if old.startswith("# 信箱:Claude"):
        rest = "\n".join(old.split("\n")[2:])
        mailbox.write_text(entry + rest.lstrip("\n"), encoding="utf-8")
    else:
        mailbox.write_text(entry + old, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll StoryClaw outbox and download new SC2X files.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token-env", default="STORYCLAW_BRIDGE_TOKEN")
    parser.add_argument("--outdir", default="/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_outbox")
    parser.add_argument("--state", default="/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_outbox/STORYCLAW_OUTBOX_POLLER_STATE.json")
    parser.add_argument("--mailbox", default="/Users/rogerwu/qingshan_short_drama/codex_docs/CLAUDE_TO_CODEX.md")
    parser.add_argument("--receipt", default="/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_outbox/STORYCLAW_OUTBOX_POLLER_RECEIPT.md")
    args = parser.parse_args()

    if not storyclaw_reads_enabled():
        receipt = Path(args.receipt).resolve()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            "\n".join(
                [
                    "# StoryClaw Outbox Poller Receipt",
                    "",
                    f"Updated: {datetime.now().isoformat(timespec='seconds')}",
                    "Status: DISABLED_LOCAL_CLAUDE_PRIMARY",
                    "Remote request performed: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "disabled": True,
                    "mode": "LOCAL_CLAUDE_PRIMARY",
                    "remote_request_performed": False,
                    "receipt": str(receipt),
                },
                ensure_ascii=False,
            )
        )
        return 0

    token = configured_token(args.token_env)
    if not token:
        raise SystemExit(f"Missing token env: {args.token_env}")

    base_url = args.base_url.rstrip("/")
    outdir = Path(args.outdir).resolve()
    state_path = Path(args.state).resolve()
    state = load_state(state_path)
    seen = state.setdefault("seen", {})

    outbox = curl_json(f"{base_url}/outbox?token={token}")
    files = sorted(outbox.get("files", []), key=lambda f: f.get("name", ""))
    downloaded = []
    mirrored = []
    for item in files:
        name = item.get("name", "")
        if not name.startswith("SC2X-") or not name.endswith(".txt"):
            continue
        key = f"{name}:{item.get('size')}:{item.get('mtime')}"
        if seen.get(name) == key and (outdir / name).exists():
            continue
        local = outdir / name
        curl_download(f"{base_url}/download?token={token}&name={name}", local)
        text = local.read_text(encoding="utf-8")
        did_mirror = prepend_mailbox(Path(args.mailbox).resolve(), name, local, text)
        seen[name] = key
        downloaded.append(name)
        if did_mirror:
            mirrored.append(name)

    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["last_outbox_count"] = outbox.get("count")
    state["last_outbox_names"] = [f.get("name") for f in files]
    save_state(state_path, state)

    receipt = Path(args.receipt).resolve()
    receipt.write_text(
        "\n".join([
            "# StoryClaw Outbox Poller Receipt",
            "",
            f"Updated: {state['updated_at']}",
            f"Outbox count: {outbox.get('count')}",
            f"Downloaded new/changed: {len(downloaded)}",
            f"Mirrored to mailbox: {len(mirrored)}",
            "",
            "## Outbox Names",
            *[f"- `{name}`" for name in state["last_outbox_names"]],
            "",
            "## Downloaded",
            *[f"- `{name}`" for name in downloaded],
            "",
            "## Mirrored",
            *[f"- `{name}`" for name in mirrored],
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"downloaded": downloaded, "mirrored": mirrored, "receipt": str(receipt)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
