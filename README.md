# Qingshan Short Drama Production Line

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An open-source production line that helps ordinary creators build a genuinely commercial-ready AI film and short-drama workflow. A clean clone contains the deployable pipeline definitions and installers; project media, credentials and episode runtime state are supplied separately.

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

The production line supports two explicitly selected video models: Giggle `seedance-2.0-pro` (SD2 standard, provider-native 720p 9:16 in the current production contract) and Giggle `MiniMax-H3` (provider-native 768p 9:16). SD2 keeps its established complete prompt grammar unchanged. H3 uses a separate native audiovisual compiler with structured reference definitions, stable speaker IDs, `<d>`-isolated literal dialogue, separated soundscape/music fields, and a no-unprompted-speech gate. `seedance-2.0-fast`, `seedance-2.0-mini`, and an unversioned bare `seedance-2.0` remain prohibited. Any higher-resolution delivery derived from H3 must be labeled as an upscale; synthetic `2K` must never be represented as native generation. E40 remains abandoned and private.

Long-form episodes are compiled with media-safe segmentation: dialogue must finish before a safety pad and a 0.6–1.5 second bridge handle, every outgoing tail keeps residual breathing/clothing/environment motion instead of a freeze, and every adjacent pair receives real-media frame/audio evidence. Release is fail-closed until plot, identity/wardrobe, pose/blocking, complete-map axis, props, sound, and transition motivation all pass the boundary acceptance report. Character wardrobe is role/status-driven and same-tier characters must remain visually distinguishable by silhouette, palette, material, fastening, or accessories.

Install the official H3 prompt/API skill on an execution host before starting E45:

```bash
npx skills add https://github.com/giggle-official/skills --skill giggle-minimax-h3-gen
```

The durable project submitter remains the only paid-POST entrypoint. The installed skill supplies the official H3 capability and prompt contract; it does not bypass transaction recording, task-id binding, credit reconciliation, complete-map gates, or pre-submit continuity QA.

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

## License

The source code in this repository is released under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies subject to the license notice. Generated media, source novels/scripts, credentials, third-party models, provider services, and other separately supplied assets are not automatically relicensed by this repository.
