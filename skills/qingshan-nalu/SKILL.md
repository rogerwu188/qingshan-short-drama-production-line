---
name: qingshan-nalu
description: Pinned Qingshan/NALU StoryClaw production engine and deployment contract.
---

# Qingshan NALU StoryClaw skill

This skill belongs to the public Qingshan/NALU repository:
`https://github.com/rogerwu188/qingshan-short-drama-production-line`.
Use the release tag and SHA in the bundled `RELEASE_MANIFEST.json`; never
replace them with a moving checkout when deploying a published agent.

The complete release archive contains the existing engine, the NALU runtime
tools and the StoryClaw adapter. It deliberately excludes novels, reference
images, media, reviews, ledgers, transactions, credentials and episode state.

## Install

```bash
git clone --branch <release-tag> --depth 1 \
  https://github.com/rogerwu188/qingshan-short-drama-production-line qingshan-engine
cd qingshan-engine
python3.12 -m venv .qingshan-venv
.qingshan-venv/bin/pip install -e '.[media,asr,cloud]'
```

Set `NALU_ENGINE_ROOT`, `NALU_RUNTIME_ROOT`, `NALU_VENV_PYTHON` and the private
`QINGSHAN_VOICE_REGISTRY` before running. Keep the runtime on a persistent
local filesystem with POSIX `flock`. Run `python tools/storyclaw_nalu_runtime.py
preflight` before any stage.

## Required order

Read the private source, create the four script layers, run S1 and seq=29, and
only after an explicit S1 PASS derive one complete character/scene/prop asset
proposal. Before the user's single confirmation, do not create an order, enable
paid requests, mark an identity PASS, or POST to a provider.

The paid path remains double-locked (`--paid` plus both workspace paid flags),
uses transaction fingerprints and flock-protected storage, and rejects Kimi and
MiniMax. Resume from `runtime/pipeline_state/<EP>.json` after interruptions.

## Fix propagation

If StoryClaw debugging changes engine files, export a diff, apply it to this
repository, run the release checks, rebuild the source archive, and publish the
TalentHub agent only from that clean commit. A remote runtime change alone is
not a release.
