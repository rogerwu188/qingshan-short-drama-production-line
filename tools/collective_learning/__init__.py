"""Multi-device director evaluation and collective learning.

Work-agnostic by construction: nothing in this package may name a production,
a character, an episode number or a deployment path.  Lines pass their own
identities (tenant_id / line_id / device_id / run_id) in.

Modules:
  contracts       record shapes, enums, validation, canonical digests, sensitive-content scan
  device_store    SQLite event store + transactional outbox on one device (JSONL export for old tools)
  sync_client     background uploader: bounded batches, jittered backoff, per-item ack, quarantine
  service         cloud-side state machine on a relational DB (SQLite first version)
  http_api        HTTP binding of ``service`` (+ OpenAPI document, read-only admin pages)
  bundles         immutable knowledge bundles: build, sign, verify, cache, resolve, run lock
  selection       deterministic per-unit advisory selection with prompt-length caps
  adoption        AVAILABLE -> SELECTED -> APPLIED -> VERIFIED -> OUTCOME_OBSERVED receipts
  director_score  DIRECTOR_SCORE_V1 episode evaluation, coverage, next-episode plan
  impact          explicit rule impact scope -> which FREE cached checks go stale
"""
