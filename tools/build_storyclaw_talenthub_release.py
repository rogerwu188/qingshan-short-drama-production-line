#!/usr/bin/env python3
"""Build the reproducible StoryClaw/NALU release and TalentHub agent workspace.

The release is intentionally two artifacts:

* a complete source archive containing the public engine and the StoryClaw
  adapter; and
* a small TalentHub agent workspace whose bundled skill points at the exact
  Git commit and source archive SHA.

Private runtime data, source novels, media, credentials, ledgers, reviews and
episode state are never copied.  Publishing is opt-in and is only possible
after the repository checks and a clean worktree have passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "storyclaw-talenthub"
GITHUB_REPO = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
SKILL_NAME = "qingshan-nalu"
AGENT_ID = "ai-drama-factory"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, check=check)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def assert_tag_points_to_head(tag: str, commit: str, allow_unreleased: bool) -> None:
    exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    if not exists:
        if allow_unreleased:
            return
        raise SystemExit(
            f"RELEASE_BLOCKED: tag {tag!r} does not exist; create the final tag before packaging"
        )
    tagged = git("rev-parse", "--verify", f"{tag}^{{commit}}")
    if tagged != commit:
        raise SystemExit(
            f"RELEASE_BLOCKED: tag {tag} resolves to {tagged}, but HEAD is {commit}"
        )


def assert_clean_worktree() -> None:
    status = git("status", "--porcelain")
    if status:
        raise SystemExit(
            "RELEASE_BLOCKED: git worktree is not clean; commit the final remote fixes first:\n"
            + status
        )


def run_release_checks() -> None:
    commands = [
        [sys.executable, "tools/deployment_code_integrity.py"],
        [sys.executable, "tools/knowledge_registry.py", "--validate"],
        [sys.executable, "tools/run_portable_ci.py"],
        [sys.executable, "-m", "unittest", "tools.tests.test_storyclaw_nalu_runtime"],
    ]
    for command in commands:
        print("RELEASE_CHECK", " ".join(command))
        run(command)


def archive_source(output: Path, tag: str, commit: str) -> tuple[Path, str]:
    archive = output / f"qingshan-storyclaw-workflow-{tag}.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        source = subprocess.check_output(
            ["git", "archive", "--format=tar", "--prefix=qingshan-storyclaw-workflow/", commit],
            cwd=ROOT,
        )
        import io

        source_tar = tarfile.open(fileobj=io.BytesIO(source), mode="r:")
        for member in source_tar.getmembers():
            extracted = source_tar.extractfile(member) if member.isfile() else None
            info = member
            if extracted is None:
                tar.addfile(info)
            else:
                tar.addfile(info, extracted)
        release_info = {
            "schema": "qingshan.storyclaw.release.v1",
            "release_tag": tag,
            "git_commit": commit,
            "repository": GITHUB_REPO,
            "source_scope": "PUBLIC_REUSABLE_ENGINE_NOT_PRIVATE_RUNTIME",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "talenthub_agent_id": AGENT_ID,
            "talenthub_skill": SKILL_NAME,
            "private_runtime_included": False,
            "credentials_included": False,
            "paid_requests_enabled": False,
        }
        payload = json.dumps(release_info, ensure_ascii=False, indent=2).encode() + b"\n"
        info = tarfile.TarInfo("qingshan-storyclaw-workflow/RELEASE_MANIFEST.json")
        info.size = len(payload)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(payload))
    return archive, sha256(archive)


def write_talenthub_workspace(output: Path, tag: str, commit: str, archive_sha: str) -> Path:
    workspace = output / "talenthub-agent"
    if workspace.exists():
        shutil.rmtree(workspace)
    (workspace / "skills" / SKILL_NAME).mkdir(parents=True)

    manifest = {
        "id": AGENT_ID,
        "name": "AI Drama Factory",
        "emoji": "🎬",
        "role": "Vertical drama production line director",
        "tagline": "Turn a novel into a gated, auditable vertical-drama production line.",
        "description": (
            "Runs the Qingshan/NALU S1-S8 production line on StoryClaw. "
            "It writes the script first, passes real gates, derives one complete asset plan, "
            "then waits for the user's single confirmation before any paid generation."
        ),
        "category": "creative",
        "skills": [f"{GITHUB_REPO}@{SKILL_NAME}"],
        "i18n": {
            "zh-CN": {
                "role": "竖屏短剧生产线导演",
                "tagline": "把原著变成有门禁、有收据、可复现的竖屏短剧生产线。",
                "description": "先生成剧本并通过 S1，再自动匹配角色、场景、道具和素材；一次性确认后才进入付费生成。",
            }
        },
        "minOpenClawVersion": "2026.3.1",
        "avatarUrl": None,
    }
    (workspace / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    identity = f"""# IDENTITY.md

- **Name:** AI Drama Factory
- **Chinese name:** AI短剧工厂
- **Release:** `{tag}` (`{commit}`)
- **Role:** Vertical-drama production-line director

You operate the public Qingshan/NALU engine pinned by the `qingshan-nalu` skill.
The engine is the source of truth for gates, receipts, transactions, budgets and
stage state. Never manufacture PASS, receipts, orders or paid submissions.
"""
    (workspace / "IDENTITY.md").write_text(identity, encoding="utf-8")
    for filename in ("USER.md", "SOUL.md", "AGENTS.md"):
        source = ROOT / "agent_factory" / filename
        shutil.copy2(source, workspace / filename)

    skill = f"""---
name: {SKILL_NAME}
description: Pinned Qingshan/NALU StoryClaw production engine and deployment contract.
---

# Qingshan NALU StoryClaw skill

This skill is released from `{GITHUB_REPO}` at tag `{tag}` (commit `{commit}`).
The complete public source archive is `qingshan-storyclaw-workflow-{tag}.tar.gz`
with SHA-256 `{archive_sha}`.  Do not substitute a moving branch or another
engine checkout.

## Install

```bash
git clone --branch {tag} --depth 1 {GITHUB_REPO} qingshan-engine
cd qingshan-engine
python3.12 -m venv .qingshan-venv
.qingshan-venv/bin/pip install -e '.[media,asr,cloud]'
```

Set `NALU_ENGINE_ROOT`, `NALU_RUNTIME_ROOT`, `NALU_VENV_PYTHON` and the private
`QINGSHAN_VOICE_REGISTRY` before running. Keep source novels, reference images,
media, reviews, ledgers, transactions and credentials on the private runtime
volume. Run `python tools/storyclaw_nalu_runtime.py preflight` before any stage.

## Required order

For a new production, read the private source, create the four script layers,
run S1 and seq=29, and only after an explicit S1 PASS derive one complete
character/scene/prop asset proposal. Before user confirmation, do not create an
order, enable paid requests, mark an identity PASS, or POST to a provider.

The paid path remains double-locked (`--paid` plus both workspace paid flags),
uses flock-protected transaction storage, and rejects Kimi/MiniMax. Resume from
`runtime/pipeline_state/<EP>.json` after interruptions.

## Release provenance

The matching source archive, its SHA, and the release manifest must be retained
with every deployment. If StoryClaw debugging changes engine files, export a
diff, apply it to the repository, run the release checks, rebuild this archive,
and publish the TalentHub agent only from that clean commit.
"""
    (workspace / "skills" / SKILL_NAME / "SKILL.md").write_text(skill, encoding="utf-8")
    release_manifest = {
        "schema": "qingshan.storyclaw.talenthub.release.v1",
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": tag,
        "git_commit": commit,
        "source_archive_sha256": archive_sha,
        "repository": GITHUB_REPO,
        "public_runtime_only": True,
    }
    (workspace / "RELEASE_MANIFEST.json").write_text(
        json.dumps(release_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return workspace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--publish", action="store_true", help="publish the generated TalentHub workspace")
    parser.add_argument("--skip-checks", action="store_true", help="for local packaging experiments only")
    parser.add_argument("--allow-unreleased", action="store_true", help="local packaging experiment; do not use for publication")
    args = parser.parse_args()

    assert_clean_worktree()
    commit = git("rev-parse", "HEAD")
    assert_tag_points_to_head(args.release_tag, commit, args.allow_unreleased)
    if not args.skip_checks:
        run_release_checks()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive, archive_sha = archive_source(args.output_dir, args.release_tag, commit)
    workspace = write_talenthub_workspace(args.output_dir, args.release_tag, commit, archive_sha)
    receipt = {
        "schema": "qingshan.storyclaw.release.receipt.v1",
        "release_tag": args.release_tag,
        "git_commit": commit,
        "source_archive": str(archive),
        "source_archive_sha256": archive_sha,
        "talenthub_workspace": str(workspace),
        "talenthub_agent_id": AGENT_ID,
        "talenthub_skill": SKILL_NAME,
        "checks": "SKIPPED" if args.skip_checks else "PASS",
        "publish_requested": args.publish,
    }
    receipt_path = args.output_dir / "RELEASE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if args.publish:
        run(["talenthub", "agent", "publish", "--dir", str(workspace)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
