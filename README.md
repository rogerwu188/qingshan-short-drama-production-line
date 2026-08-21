# Qingshan Short Drama Production Line

Private, code-only mirror of the local short-drama production pipeline. A clean clone contains the deployable pipeline definitions and installers; project media, credentials and episode runtime state are supplied separately.

Tracked scope:

- `tools/`: production orchestration, generation, QA, transaction, assembly, and continuity tooling.
- `agent_factory/`: agent operating rules and production-line documentation.
- `agent_factory/claude_writer/`: portable Claude Writer Scheduled Agent definition, runtime-state templates, installer and doctor.

The local canonical manifests, media assets, QA evidence, credit transactions, receipts, runtime logs, and credentials are intentionally excluded. They remain authoritative in the production workspace and must never be reconstructed from this repository.

## Bootstrap Claude Writer

From a clean clone:

```bash
python3 agent_factory/claude_writer/install.py doctor --project-root .
python3 agent_factory/claude_writer/install.py install --project-root .
python3 agent_factory/claude_writer/install.py doctor --project-root .
```

The installer deploys the versioned `SKILL.md` to Claude Desktop's Scheduled folder, creates only missing empty runtime-state files, and never overwrites episode content or credentials. If Claude Desktop has not created the scheduled task yet, create one named `qingshan-claude-writer-agent`, point it at the clone, use a 30-minute schedule, and rerun `doctor`.

See [`agent_factory/claude_writer/README.md`](agent_factory/claude_writer/README.md) for the complete local/cloud Writer deployment contract and clean-clone smoke test.

For E40 and later Seedance 2.0 video jobs, the authorized model is `seedance-2.0-fast`; `seedance-2.0-pro`, `seedance-2.0-mini`, and an unversioned bare `seedance-2.0` are prohibited.
