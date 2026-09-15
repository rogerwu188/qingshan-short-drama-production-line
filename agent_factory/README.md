# Agent packages

This directory contains reusable agents for the Qingshan Short Drama Engine. It contains code, schemas and empty runtime templates only; credentials, episode media, receipts and project history belong in an external deployment workspace.

## Writer Agent v2

`claude_writer_v2/` is the supported Writer Agent. It converts an authorized source chapter into four versioned layers:

1. narrative canonical;
2. directing script;
3. generation contract;
4. manifest.

It then runs registered, fail-closed script gates before downstream image, video and editing work may start. Run its smoke tests from the repository root:

```bash
python3 -m unittest agent_factory.claude_writer_v2.tests.test_smoke
```

See [`claude_writer_v2/README.md`](claude_writer_v2/README.md) for usage and [`claude_writer_v2/docs/CHARTER.md`](claude_writer_v2/docs/CHARTER.md) for the authoritative Writer contract.

## Writer Agent v1

`claude_writer/` is retained as a migration-compatible legacy package. New deployments should use v2. Its installer must copy empty templates into the target workspace and must never treat repository files as live production state.

## Runtime data boundary

The following are deliberately excluded from the reusable agent package:

- source novels and copyrighted project material;
- live supervisor orders and progress ledgers;
- character references and generated media;
- provider credentials and platform sessions;
- QA receipts, credit transactions and release receipts.

Create a safe external workspace with `qingshan init <directory>` and point the engine at it with `QINGSHAN_ENGINE_ROOT` when needed.
