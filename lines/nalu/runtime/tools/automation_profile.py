#!/usr/bin/env python3
"""automation_profile.py — write the three files that let a deployed line run unattended.

Why this is a tool and not a paragraph in a doc
-----------------------------------------------
"Run the pipeline with no human in the loop" needs three different things on disk, and two of
them must NOT live in the same place:

1. ``$ENGINE_ROOT/.claude/settings.json`` — permission allow/deny rules.  This one is **tracked**,
   so it may not contain a single absolute path: one machine's ``/Users/x/nalu`` would be
   meaningless (and a small privacy leak) on every other clone.  Everything in it is evaluated
   relative to the repository root.
2. ``$ENGINE_ROOT/.claude/settings.local.json`` — the same rules specialised with *this* machine's
   absolute runtime root, plus that root in ``additionalDirectories``.  Generated, never tracked.
3. ``$ENGINE_ROOT/.claude/unattended_runner.md`` — the standing instructions an unattended session
   reads at start: the loop, when to stop, and the four things it must never treat as auto-approve.

What is deliberately NOT here
-----------------------------
No order, no credit cap, no credential, no authorisation.  This tool writes *permissions*, and a
permission is not an authority.  The spend on any machine is still gated by the deployed order in
its private inbox (``materialize_paid_authorization.py``, D-11), the runtime's
``generation.paid_requests_enabled``, the per-episode cap in ``nalu_budget_ledger.py``, the
whole-batch prompt gate (K041) and the durable transaction store — all of which live inside the
repository's own code and none of which this file can widen.  A model that could grant itself
spend authority here would make the rest of the gate meaningless, so it cannot: this script writes
only names of commands, and the two order-bearing fields it would have to forge
(``NALU_PAID_ORDER_SEQ`` / ``paid_requests_allowed``) come from the deployer's private inbox.

Usage
-----
    automation_profile.py write --repo-root "$NALU_ENGINE_ROOT" --runtime-root "$NALU_RUNTIME_ROOT"
    automation_profile.py check --repo-root "$NALU_ENGINE_ROOT"
    automation_profile.py print --repo-root "$NALU_ENGINE_ROOT"     # show what write would emit
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# --- the tracked profile (relative paths only) --------------------------------------------------

# Denied first: a deny rule beats an allow rule.  These are the actions an unattended session must
# not take on its own initiative.  Note what is NOT denied: reading anything, and editing the
# line's own tools — camera/framing wording is the orchestrator's to fix, and the review loop needs
# to read receipts under workflow/.
TRACKED_DENY = [
    "Bash(sudo:*)",
    "Bash(rm -rf:*)",
    "Bash(git push:*)",                   # publication is the line owner's action
    "Bash(git reset --hard:*)",
    "Bash(git clean:*)",
    "Bash(git rebase:*)",
    "Bash(git filter-branch:*)",
    "Bash(git checkout --:*)",            # discards work without asking
    "Bash(gh repo:*)",
    "Bash(gh release:*)",
    "Bash(gh pr merge:*)",
    "Bash(curl:*)",                       # the pipeline uses its own provider client; a bare curl
    "Bash(wget:*)",                       # is how a credential or a file leaves the machine
    "Bash(nc:*)",
    "Bash(scp:*)",
    "Bash(ssh:*)",
    "Read(./.env)",
    "Read(./.env.*)",
    "Edit(./.env)",
    "Edit(./.env.*)",
    "Write(./.env)",
    "Write(./.env.*)",
    # The order file *is* the line's authority.  Editing it is how a model would manufacture its
    # own permission, so the edit is denied even though reading it is fine.
    "Edit(./workflow/**)",
    "Write(./workflow/**)",
    # The agent must not widen its own permission surface.
    "Edit(./.claude/**)",
    "Write(./.claude/**)",
]

# Allowed: the line's own documented entry points, plus the read-only shell a review loop needs.
# The narrow `paid_stage.sh` entry matters most — it collapses "source a secret file and run
# --paid" into one argv whose authority is checked by the line's own gates at run time.
TRACKED_ALLOW = [
    "Bash(lines/nalu/runtime/tools/paid_stage.sh:*)",
    "Bash(lines/nalu/runtime/tools/nalu_pipeline.py:*)",
    "Bash(lines/nalu/runtime/tools/record_supervisor_order.py:*)",
    "Bash(lines/nalu/runtime/tools/materialize_paid_authorization.py:*)",
    "Bash(lines/nalu/runtime/tools/nalu_budget_ledger.py:*)",
    "Bash(lines/nalu/runtime/tools/prompt_batch_qa.py:*)",
    "Bash(lines/nalu/runtime/tools/prompt_batch_register.py:*)",
    "Bash(lines/nalu/runtime/tools/review_fill/*)",
    "Bash(.qingshan-venv/bin/python:*)",
    "Bash(python3:*)",
    "Bash(bash lines/nalu/runtime/tools/:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git switch:*)",
    "Bash(git branch:*)",
    "Bash(git tag:*)",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    "Bash(grep:*)",
    "Bash(rg:*)",
    "Bash(find:*)",
    "Bash(sed -n:*)",
    "Bash(awk:*)",
    "Bash(sort:*)",
    "Bash(uniq:*)",
    "Bash(cut:*)",
    "Bash(jq:*)",
    "Bash(tee:*)",
    "Bash(diff:*)",
    "Bash(stat:*)",
    "Bash(du:*)",
    "Bash(df:*)",
    "Bash(date:*)",
    "Bash(realpath:*)",
    "Bash(basename:*)",
    "Bash(dirname:*)",
    "Bash(mkdir -p:*)",
    "Bash(cp:*)",
    "Bash(mv:*)",
    "Bash(touch:*)",
    "Bash(shasum:*)",
    "Bash(md5:*)",
    "Bash(pytest:*)",
]

# A question for a human has to be able to reach a human even when nobody is at the terminal.
# `open` is the one outward-facing call allowed, and it is allowed only in the local profile,
# because the URL is machine-independent but the command is not.
LOCAL_ALLOW = [
    "Bash(/usr/bin/open:*)",
    "Bash(open:*)",
]

ABSOLUTE_PATH = re.compile(r"(^|[\"'(\s])(/Users/|/home/|/Volumes/|[A-Za-z]:\\\\)")

RUNNER_TEMPLATE = """# 无人值守运行指令（由 automation_profile.py 生成，可改；改动请同步回模板）

你是 **{line_owner}** 的 nalu 生产线编排代理，在无人应答的会话里工作。工作目录 `{repo_root}`，
运行时根 `{runtime_root}`。本文件是你在没有人在场时的行为准则。

## 循环

1. `python3 lines/nalu/runtime/tools/nalu_pipeline.py status --episode <EP>` 看当前阶段。
2. 有 `REVIEW_REQUIRED`（exit 4）→ 该阶段在 `preproduction/<EP>/reviews/` 写了问卷。
   **实际打开图看**（contact sheet / video sheet），逐条填结构化答案，然后重跑。
   填答脚本在 `lines/nalu/runtime/tools/review_fill/`，按集复制改名。
3. 付费阶段：只通过 `lines/nalu/runtime/tools/paid_stage.sh <EP> <FROM> <UNTIL>` 提交，
   不要自己拼 `set -a; source .env; … --paid`。该脚本的运行前检查就是权威检查。
4. 波次未跑完（`VIDEO_NOT_ALL_COMPLETED`）→ 等 3 分钟重跑，别的阻塞停下来处理。
5. S8 写 CHECKPOINT 后**停**，等线主 `approve`。发布动作永远不属于你。

## 四件永远不能当成自动批准的事

- **订单里没有的付费类别**：首个 BGM、换装 i2i、超出返工守卫的重拍、单集缺陷预算超支。
  停下，把估算和理由留在 `runtime/reports/`，通知线主。
- **音色一致性失败**（`VOICE_OUT_OF_BAND` / `VOICE_COLLISION`）：交线主，不自动接受。
- **剧情与台词文本的改动**：交线主。镜头与取景措辞是你的事。
- **发布**：永远不是你的动作（本部署订单未授权发布）。

## 停下来的正确姿势

不是等到超时。写一份简短的待决说明到 `runtime/reports/`（要什么、为什么、估算花多少、
不做的后果），然后退出。线主回来只读这一个文件就能决定。

## 交付与记录

- 回执写 `runtime/reports/` 与 `preproduction/<EP>/reports/`；
- 收工写 K 号（`tools/knowledge_sync_core.py`），开工先读 `configs/ENGINEERING_KNOWLEDGE_V1.json`
  与 `knowledge/failure_memory.jsonl`——读的是原因，不是照搬旧集；
- 每份 QA 记录写明审核者是谁。禁止虚假 PASS：缺依赖标 `ADAPTER_REQUIRED`，没跑标 `NOT_RUN`。

## 关于权限

`.claude/settings.json` 里允许的是**这条线自己的入口**；禁止的是推送、发布、破坏性 git、
读取 `.env`、以及编辑订单文件与权限文件本身。权限不是授权来源：积分上限、订单范围、
整批提示词门（K041）和事务去重都在仓库自己的代码里，改这些设置不能放宽它们，也不许尝试。
"""


def _settings_payload(repo_root: Path, runtime_root: Path | None) -> dict:
    return {"permissions": {"deny": list(TRACKED_DENY), "allow": list(TRACKED_ALLOW)}}


def _local_payload(repo_root: Path, runtime_root: Path, existing: dict) -> dict:
    payload = dict(existing)
    permissions = dict(payload.get("permissions") or {})
    permissions["allow"] = sorted(set(permissions.get("allow") or []) | set(LOCAL_ALLOW))
    permission_deny = list(permissions.get("deny") or [])
    # The order file lives outside the repository, so its denial can only be written here.
    for name in ("SUPERVISOR_ORDERS.json", "qingshan.json", ".env"):
        permission_deny.append(f"Edit({runtime_root}/**/{name})")
        permission_deny.append(f"Write({runtime_root}/**/{name})")
    permissions["deny"] = sorted(set(permission_deny))
    additional = list(payload.get("additionalDirectories") or [])
    if str(runtime_root) not in additional:
        additional.append(str(runtime_root))
    payload["permissions"] = permissions
    payload["additionalDirectories"] = additional
    return payload


def _write(path: Path, payload: dict, *, force: bool) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") == text:
            return "UNCHANGED"
        if not force:
            return "PRESENT_DIFFERENT (use --force to overwrite)"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return "WRITTEN"


def cmd_write(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    claude_dir = repo_root / ".claude"
    report: dict[str, str] = {}

    tracked = _settings_payload(repo_root, runtime_root)
    if ABSOLUTE_PATH.search(json.dumps(tracked, ensure_ascii=False)):
        print(json.dumps({"status": "REFUSED", "reason": "TRACKED_SETTINGS_WOULD_CARRY_AN_ABSOLUTE_PATH",
                          "note": "the tracked profile must be machine-independent; put machine paths "
                                  "in settings.local.json instead"}, ensure_ascii=False))
        return 2
    report["settings.json"] = _write(claude_dir / "settings.json", tracked, force=True)

    local_path = claude_dir / "settings.local.json"
    existing = json.loads(local_path.read_text(encoding="utf-8")) if local_path.is_file() else {}
    report["settings.local.json"] = _write(
        local_path, _local_payload(repo_root, runtime_root, existing), force=args.force)

    runner = claude_dir / "unattended_runner.md"
    text = RUNNER_TEMPLATE.format(line_owner=args.line_owner, repo_root=repo_root,
                                  runtime_root=runtime_root)
    if runner.is_file() and runner.read_text(encoding="utf-8") != text and not args.force:
        report["unattended_runner.md"] = "PRESENT_DIFFERENT (use --force to overwrite)"
    elif runner.is_file() and runner.read_text(encoding="utf-8") == text:
        report["unattended_runner.md"] = "UNCHANGED"
    else:
        runner.write_text(text, encoding="utf-8")
        report["unattended_runner.md"] = "WRITTEN"

    print(json.dumps({"status": "PASS", "repo_root": str(repo_root), "runtime_root": str(runtime_root),
                      "files": report,
                      "note": "permissions only; no order, cap or credential is written here"},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    claude_dir = repo_root / ".claude"
    problems = []
    tracked_path = claude_dir / "settings.json"
    if not tracked_path.is_file():
        problems.append("MISSING_SETTINGS_JSON")
    else:
        raw = tracked_path.read_text(encoding="utf-8")
        if ABSOLUTE_PATH.search(raw):
            problems.append("TRACKED_SETTINGS_CARRIES_AN_ABSOLUTE_PATH")
        payload = json.loads(raw)
        deny = (payload.get("permissions") or {}).get("deny") or []
        for required in ("Bash(git push:*)", "Edit(./.claude/**)", "Edit(./workflow/**)"):
            if required not in deny:
                problems.append(f"DENY_RULE_MISSING:{required}")
        allow = (payload.get("permissions") or {}).get("allow") or []
        if not any(rule.startswith("Bash(lines/nalu/runtime/tools/paid_stage.sh") for rule in allow):
            problems.append("PAID_STAGE_ENTRY_NOT_ALLOWED")
    for name in ("settings.local.json", "unattended_runner.md"):
        if not (claude_dir / name).is_file():
            problems.append(f"MISSING_{name.upper().replace('.', '_')}")
    out = {"status": "PASS" if not problems else "FAIL", "repo_root": str(repo_root),
           "problems": problems}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not problems else 2


def cmd_print(args: argparse.Namespace) -> int:
    print(json.dumps(_settings_payload(Path(args.repo_root), None), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("write", "check", "print"):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", default=os.environ.get("NALU_ENGINE_ROOT", ""))
        p.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT", ""))
        p.add_argument("--line-owner", default=os.environ.get("NALU_LINE_OWNER_ID") or "线主")
        p.add_argument("--force", action="store_true")
        p.set_defaults(func={"write": cmd_write, "check": cmd_check, "print": cmd_print}[name])
    args = ap.parse_args()
    if not args.repo_root:
        print(json.dumps({"status": "REFUSED", "reason": "NO_REPO_ROOT"}, ensure_ascii=False))
        return 2
    if args.func is cmd_write and not args.runtime_root:
        print(json.dumps({"status": "REFUSED", "reason": "NO_RUNTIME_ROOT"}, ensure_ascii=False))
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
