# Qingshan Short Drama Engine — Open-Source Boundary

This repository distributes reusable engine code, provider-neutral configuration schemas, and operational guidance. It must not distribute episode scripts, frames, generated media, review records, credit ledgers, receipts, task state, browser profiles, secrets, or personal identifiers.

## Public contents

- `tools/`, `qingshan_engine/`, `libraries/`, and tests: reusable implementation.
- `configs/examples/` and `examples/`: synthetic, non-production examples only.
- `docs/`, `workflow/*_SCHEMA.md`, and this document: contracts and runbooks.

## Private contents

Production material belongs outside the public repository: `qa/`, `working_assets/`, `deliverables/`, `outputs/`, `storyboards/`, `ref_images/`, `assets/`, `workflow/tasks/`, `workflow/releases/`, episode-specific manifests, receipts, ledgers, and state snapshots.

Use `python tools/build_open_source_export.py --out <directory>` to create a clean export. The exporter fails closed for secrets and private-data paths and writes a file inventory for review.

Never commit API keys, browser profiles, provider task IDs, personal names/emails, generated media, or episode text to the public repository.
