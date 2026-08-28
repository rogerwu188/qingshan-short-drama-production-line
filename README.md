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

For E41 and later Seedance 2.0 video jobs, the authorized model is `seedance-2.0-pro` (SD2 standard); `seedance-2.0-fast`, `seedance-2.0-mini`, and an unversioned bare `seedance-2.0` are prohibited. E40 remains abandoned and private.

## Grouped-video continuity gate

Every boundary between editorial beats packed into one provider video task must carry an authored `internal_transition_contract`. The compiler and submitter fail closed unless that contract is bound to both beats' exact:

- visible cast and dialogue speaker;
- global map, location, and shot subspace;
- prop set and ownership/handoff;
- ambience, foley, and action sound;
- previous action terminal state and successor initial state;
- camera transition and axis strategy; and
- reference-image entity mapping.

Different characters may not reuse the same mapped screen slot as an implicit identity transformation. That handoff must be split or expressed as an authored cut, reveal, or reframe. The compiled model prompt contains the full `【节拍内连续性硬合同】`; the same contract is fingerprinted and revalidated immediately before any paid provider POST.

Creative continuity is a pre-submission gate. Post-generation rejection is limited to technical integrity and basic plot/identity correctness; action taste, choreography preference, and micro-expression precision do not consume regeneration attempts after a technically usable result exists.
