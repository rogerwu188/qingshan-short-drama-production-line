#!/usr/bin/env python3
"""Canonical TalentHub-managed StoryClaw release surface.

Both the immutable release classifier and the installed-host updater import
these constants.  Keeping one list prevents an incorrectly labelled
``ENGINE_ONLY`` channel from bypassing a newly added Agent, skill, trust-root,
onboarding, or release-management file.
"""
from __future__ import annotations


TALENTHUB_MANAGED_EXACT = frozenset(
    {
        ".github/workflows/storyclaw-release-candidate.yml",
        ".github/workflows/storyclaw-stable-promote.yml",
        "AGENTS.md",
        "agent_factory/AGENTS.md",
        "agent_factory/STORYCLAW_WORKFLOW_POLICY.md",
        "configs/PORTABLE_CORE_MANIFEST.json",
        "configs/storyclaw_nalu_config.example.json",
        "configs/storyclaw_release_signing_probe.txt",
        "configs/storyclaw_release_signing_probe.txt.sig",
        "configs/storyclaw_release_signing_public_key.pem",
        "tools/build_storyclaw_talenthub_release.py",
        "tools/storyclaw_dependency_bundle.py",
        "tools/storyclaw_asset_plan_gate.py",
        "tools/storyclaw_audio_provider.py",
        "tools/storyclaw_guided_onboarding.py",
        "tools/storyclaw_install.py",
        "tools/storyclaw_nalu_runtime.py",
        "tools/storyclaw_project_intake.py",
        "tools/storyclaw_release_discovery.py",
        "tools/storyclaw_release_validation.py",
        "tools/storyclaw_release_surface.py",
        "tools/storyclaw_upgrade_classifier.py",
        "tools/storyclaw_upgrade_transaction.py",
        "tools/storyclaw_writer_workflow.py",
    }
)

# Entire subtrees interpreted or installed by TalentHub.
TALENTHUB_MANAGED_TREE_ROOTS = (
    "agent_factory/storyclaw_portable",
    "skills/qingshan-nalu",
)

# Filename prefixes whose members are individually compared by the updater.
TALENTHUB_MANAGED_FILE_PREFIXES = (
    "docs/STORYCLAW_",
    "tools/storyclaw_",
    ".github/workflows/storyclaw-",
)


def is_talenthub_managed(path: str) -> bool:
    return (
        path in TALENTHUB_MANAGED_EXACT
        or any(path == root or path.startswith(root + "/") for root in TALENTHUB_MANAGED_TREE_ROOTS)
        or path.startswith(TALENTHUB_MANAGED_FILE_PREFIXES)
    )
