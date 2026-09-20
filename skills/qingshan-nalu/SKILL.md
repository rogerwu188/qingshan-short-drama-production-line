---
name: qingshan-nalu
description: Pinned Qingshan/NALU StoryClaw production engine and deployment contract.
---

# Qingshan NALU StoryClaw skill

This skill belongs to the public Qingshan/NALU repository:
`https://github.com/rogerwu188/qingshan-short-drama-production-line`.
Use the release tag and SHA in the bundled `skills/qingshan-nalu/RELEASE_MANIFEST.json`; never
replace them with a moving checkout when deploying a published agent.

The complete release archive contains the existing engine, the NALU runtime
tools and the StoryClaw adapter. It deliberately excludes novels, reference
images, media, reviews, ledgers, transactions, credentials and episode state.

## Install

After TalentHub installs this skill, the Agent runs the bundled bootstrap once
for each project. The user only chooses a project location and may provide a
title; do not ask them to clone the repository or assemble installer flags.

```bash
python "$TALENTHUB_WORKSPACE/skills/qingshan-nalu/bootstrap_storyclaw.py" \
  --workspace "$TALENTHUB_WORKSPACE" \
  --project-home "$PRIVATE_PROJECT_HOME" \
  --title "$PROJECT_TITLE"
```

The stdlib-only bootstrap validates the installed prompt and skill hashes,
downloads and verifies the immutable release archive, obtains the exact tag and
40-character commit, selects the exact host dependency profile from the nested
release manifest, and downloads that profile's signed-size/SHA-bound manifest
and wheel archive into the private cache. The installer uses only that offline
archive with `pip --no-index --require-hashes`; it has no unpinned or network
fallback. Supported hosts are Linux x86_64, glibc 2.31 or newer, and CPython
3.10 or 3.11 CPU. Every other host fails closed. The bootstrap then initializes
private project state and creates the project engine link, project view, venv,
read-only seal, and trusted release baseline. It makes zero generation-provider
POSTs. Never substitute `main`, `latest`, or an unverified commit.
`tools/storyclaw_install.py install` remains the advanced recovery path
documented in `docs/STORYCLAW_HOST_INSTALL.md`.

Point `NALU_ENGINE_ROOT` at that project's `current` link and set
`NALU_RUNTIME_ROOT`, `NALU_VENV_PYTHON` and the private voice registry to paths
inside the same project runtime. Keep it on a persistent local filesystem with
POSIX `flock`, then run the adapter `preflight` before any stage. A direct
engine-root wiring is blocked by default; `--isolated-mount-namespace` is only
for a worker whose mount namespace is provably private to one project. See
[`docs/STORYCLAW_HOST_INSTALL.md`](../../docs/STORYCLAW_HOST_INSTALL.md) for the
complete host layout and upgrade procedure.

## Required order

Read the private source, create the four script layers, run S1 and seq=29, and
only after an explicit S1 PASS derive one complete character/scene/prop asset
proposal. Before the user's single confirmation, do not create an order, enable
paid requests, mark an identity PASS, or POST to a provider.

Create the private four-layer handoff only with
`tools/storyclaw_writer_workflow.py begin` and `finalize`, using the exact
host-supplied `STORYCLAW_MODEL` and real StoryClaw task/session id. Follow
`agent_factory/storyclaw_portable/WRITER_CONTRACT.md`. S1 verifies the active
handoff, full writer provenance, four-layer seal and SHA bindings, private
source receipts, and script-derived project lexicon before any script gate can
PASS. A revision uses a higher immutable writer version; it never overwrites v1.

The paid path remains double-locked (`--paid` plus both workspace paid flags),
uses transaction fingerprints and flock-protected storage, and rejects Kimi and
MiniMax. Resume from `runtime/pipeline_state/<EP>.json` after interruptions.

## Fix propagation

If StoryClaw debugging changes engine files, export a diff, apply it to this
repository, run the release checks, rebuild the source archive, and publish the
TalentHub agent only from that clean commit. A remote runtime change alone is
not a release.

## Daily upgrades

Never follow `main`, `latest`, or another moving ref. Compare the installed
exact tag with an exact candidate tag using
`tools/storyclaw_upgrade_classifier.py`, and promote the candidate only after
the full release checks and StoryClaw validation pass. `ENGINE_ONLY` releases
may be installed side by side at a recorded safe stop and selected by the
atomic project engine link; a failed preflight keeps or restores the old link.

The heartbeat discovers candidates only with
`tools/storyclaw_release_discovery.py`. It verifies the detached Ed25519
signature using the public-key digest pinned in the installed package, rejects
signed-index rollback by monotonic release sequence, then verifies the exact
tag-specific channel and archive hashes. Adapter preflight must pass the
checked-in `openssl pkeyutl` Ed25519 probe. `CURRENT` is silent; discovery
performs zero provider posts.

For `TALENTHUB_PACKAGE_REQUIRED`, keep the old engine selected and run the
official `talenthub agent update ai-drama-factory`. Then rerun
`tools/storyclaw_install.py upgrade` with
`--talenthub-release-manifest <installed-workspace>/skills/qingshan-nalu/RELEASE_MANIFEST.json` so
the updater can bind the new Agent id, skill, tag, commit, archive SHA, channel
SHA and update class. When the channel declares dependency changes, also pass
the exact release-bound `--dependency-manifest` and `--dependency-archive`, plus
`--install-deps --new-venv-path
<private-runtime>/runtime/storyclaw_host/venvs/<release-tag>`. The installer
preflights the new interpreter, then switches the project-local
`runtime/storyclaw_host/current-venv` selector and engine link while the same
exclusive barrier is held. Keep `NALU_VENV_PYTHON` pointed at that stable
selector; never point workers at a versioned venv or mutate the current venv.
Runs resolve and pin the selector only after taking the shared barrier. Never automate a
`RUNTIME_MIGRATION_REQUIRED` release; it needs an explicit migration and tested
rollback. Do not submit paid provider work during an upgrade.

Every run and heartbeat holds the runtime-wide shared engine barrier. The
updater holds the exclusive counterpart from its state/lock safety check
through extraction, candidate preflight, both selector switches, post-switch
verification, rollback if needed, and receipt write. A lock conflict blocks
immediately.

## Published release evidence

An official TalentHub publication must come from a clean commit whose release
tag is already present on `origin` and peels to that exact commit. The publisher
must validate a private `storyclaw.nalu.release_validation.v1` receipt bound to
the same commit. Its checks cover install preflight, private-source intake,
S1-S2, an S5 dry run with zero paid posts, a two-unit paid trial, ledger
reconciliation and the final checkpoint. Every check binds a real evidence
file by path and SHA-256.

The private receipt has this shape; each omitted `...` is a real evidence path
and its lowercase 64-character SHA-256:

```json
{
  "schema": "storyclaw.nalu.release_validation.v1",
  "status": "PASS",
  "release_commit": "<40-character git commit>",
  "remote_engine_commit": "<same commit>",
  "remote_worktree_clean": true,
  "remote_diff_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "checks": {
    "install_preflight": {"status": "PASS", "evidence_path": "...", "evidence_sha256": "..."},
    "source_intake": {"status": "PASS", "evidence_path": "...", "evidence_sha256": "..."},
    "s1_s2": {"status": "PASS", "evidence_path": "...", "evidence_sha256": "..."},
    "s5_dry_run": {"status": "PASS", "paid_posts": 0, "evidence_path": "...", "evidence_sha256": "..."},
    "two_unit_paid_trial": {"status": "PASS", "unit_count": 2, "evidence_path": "...", "evidence_sha256": "..."},
    "ledger_reconciliation": {"status": "PASS", "reconciled": true, "evidence_path": "...", "evidence_sha256": "..."},
    "checkpoint": {"status": "PASS", "evidence_path": "...", "evidence_sha256": "..."}
  }
}
```

Only the validation receipt SHA-256 and PASS summary enter the public TalentHub
workspace. The receipt, evidence files, source text, media, provider records,
orders, ledger and credentials remain on private storage. The installed release
block names the immutable GitHub Release archive and its exact byte size and
SHA-256; verify both before extraction.
