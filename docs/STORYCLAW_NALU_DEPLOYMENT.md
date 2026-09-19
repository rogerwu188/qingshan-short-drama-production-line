# StoryClaw NALU deployment

This adapter runs the repository's existing `lines/nalu/runtime/tools/nalu_pipeline.py`; it does not fork or reimplement the engine. StoryClaw supplies the process, model and secret injection. The runtime volume supplies episode state and private evidence.

## Services and volumes

- `nalu-production-worker`: one process per episode, using `storyclaw_nalu_runtime.py run`; mount the engine checkout read-only and the runtime volume read-write.
- `nalu-review-worker`: independent reviewer process. It watches `runtime/reviews/<EP>/*_request.json`, opens the referenced media, and submits through `vlm_review_protocol.py`. It must never fill answers from the pipeline.
- `nalu-supervisor-interface`: writes only `workflow/claude_writer_agent/SUPERVISOR_ORDERS.json` in the private runtime/workspace and records `GATE_FAIL_ACCEPTANCE` or S8 approval.
- `nalu-heartbeat`: every 900 seconds, runs `heartbeat --episode ENN` and resumes only from `pipeline_state/<EP>.json` after an API/relay interruption.
- Persistent volume: `runtime/` (state, logs, reviews, registries, budget ledger, transaction receipts), `sources/`, `deliverables/`, and per-episode private workspaces. Keep transaction directories on a local filesystem with working POSIX `flock`.

## Secrets and model route

Inject `GIGGLE_API_KEY` only for an explicitly authorized paid trial. Inject `QINGSHAN_VOICE_REGISTRY` through the private runtime. Never write secrets to manifests or logs. The StoryClaw model allowlist is `storyclaw/gpt-6-astra` and `storyclaw/claude-opus-5`; MiniMax and Kimi are rejected by preflight and must not be selected.

## Commands

```bash
export NALU_ENGINE_ROOT=/srv/qingshan-engine
export NALU_RUNTIME_ROOT=/var/lib/qingshan-nalu
export NALU_VENV_PYTHON=/srv/qingshan-engine/.qingshan-venv/bin/python
python tools/storyclaw_nalu_runtime.py init
python tools/storyclaw_nalu_runtime.py preflight
python tools/storyclaw_nalu_runtime.py run --episode E06 --from S1 --until S2
python tools/storyclaw_nalu_runtime.py run --episode E06 --from S5 --until S5 --dry-run
python tools/storyclaw_nalu_runtime.py heartbeat --episode E06
```

The paid path is fail-closed: `--paid` is refused unless both `generation.paid_requests_enabled` and `storyclaw.paid_requests_enabled` are true and `GIGGLE_API_KEY` is present. Existing transaction fingerprints remain authoritative; no automatic platform upload exists.

## Verification and delivery

Run `qingshan doctor --profile all`, `python tools/run_portable_ci.py`, `python tools/knowledge_registry.py --validate`, and `python tools/deployment_code_integrity.py` before enabling paid work. Record the E06 S1→S2 dry run, E06 S5 dry run (`paid_posts=0`), the two-unit S3→S8 trial, both CHECKPOINT files, ledger reconciliation, and the public-main diff. A stage with missing evidence is `BLOCKED`, `NOT_RUN`, or `CAPABILITY_FAIL`, never PASS.
