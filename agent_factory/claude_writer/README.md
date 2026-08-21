# Claude Writer Agent portable deployment

This package makes the Claude Writer definition reproducible from a clean GitHub clone without publishing any episode runtime data.

## Included

- `SKILL.md`: versioned, episode-agnostic Claude Desktop Scheduled Agent definition.
- `install.py`: idempotent installer and doctor.
- `runtime_templates/`: empty initial state only; copied only when the destination file does not exist.
- `package_manifest.json`: machine-readable deployment contract.

The production repository also carries the Writer provenance dispatcher, script gates, schemas, local/cloud charters and StoryClaw prompt bundle.

## Deliberately excluded

Canonical scripts, manifests, media, QA evidence, credit transactions, receipts, work queues, logs, credentials and live `SUPERVISOR_ORDERS.json` are runtime/project data. A clean install creates empty state and waits for an authorized order; it never fabricates a historical receipt or production state.

## Install

Requirements: Python 3.11+ and Claude Desktop for local Scheduled Agent execution.

```bash
git clone git@github.com:rogerwu188/qingshan-short-drama-production-line.git
cd qingshan-short-drama-production-line
python3 agent_factory/claude_writer/install.py doctor --project-root .
python3 agent_factory/claude_writer/install.py install --project-root .
python3 agent_factory/claude_writer/install.py doctor --project-root .
```

Default deployment path:

```text
~/Documents/Claude/Scheduled/qingshan-claude-writer-agent/SKILL.md
```

Override it with `--scheduled-root`. Existing runtime state is preserved. An existing deployed `SKILL.md` is backed up to `SKILL.md.previous` before replacement.

Claude Desktop task configuration:

- name: `qingshan-claude-writer-agent`
- workspace/project folder: the clean clone
- schedule: every 30 minutes
- model: an exact provider model ID supported by the deployment; the Writer must record the actual model/session in the dispatcher receipt
- filesystem access: read/write to the clone only

The installer cannot create or authenticate a proprietary Claude Desktop account. Login and any OS permission prompt remain human actions.

## Runtime order

Each run reads `workflow/claude_writer_agent/SUPERVISOR_ORDERS.json`. No order means `IDLE_LEGAL`; it must not invent an episode. An authorized episode starts through `tools/canonical_writer_dispatcher.py start`, emits the four-layer Writer package, finishes the receipt, then runs the script-phase registered gates.

## Clean-clone acceptance

`doctor` must report:

- all repository dependencies present;
- portable template SHA equals deployed Scheduled Agent SHA;
- runtime state files present and parseable;
- no unresolved template placeholder;
- canonical writer dispatcher and gate runner import successfully.

Run tests:

```bash
python3 -m unittest tools.tests.test_claude_writer_portable_install
```
