# StoryClaw NALU deployment

This adapter runs the repository's existing `lines/nalu/runtime/tools/nalu_pipeline.py`; it does not fork or reimplement the engine. StoryClaw supplies the process, model and secret injection. The runtime volume supplies episode state and private evidence.

## Services and volumes

- `nalu-production-worker`: one process per episode, using `storyclaw_nalu_runtime.py run`. Mount the engine checkout read-only and the runtime volume read-write, with the two nested private mounts described below.
- `nalu-review-worker`: independent reviewer process. It watches `runtime/reviews/<EP>/*_request.json`, opens the referenced media, and submits through `vlm_review_protocol.py`. It must never fill answers from the pipeline.
- `nalu-supervisor-interface`: writes only `workflow/claude_writer_agent/SUPERVISOR_ORDERS.json` in the private runtime/workspace and records `GATE_FAIL_ACCEPTANCE` or S8 approval.
- `nalu-heartbeat`: every 900 seconds, runs `heartbeat --episode ENN` and resumes only from `pipeline_state/<EP>.json` after an API/relay interruption.
- Persistent volume: `runtime/` (state, logs, reviews, registries and budget ledger), `sources/`, `deliverables/`, and the two `runtime/storyclaw_storage/workflow/` stores below. Keep both private stores on a local filesystem with working POSIX `flock`.

The engine still has repository-relative path contracts for the episode
workspace and exactly-once transaction store. Keep one engine version by
mounting private persistent directories at those exact paths:

| Private backing directory | Required mount target | Mode |
|---|---|---|
| `$RUNTIME_ROOT/runtime/storyclaw_storage/workflow/nalu` | `$ENGINE_ROOT/workflow/nalu` | read-write |
| `$RUNTIME_ROOT/runtime/storyclaw_storage/workflow/tasks` | `$ENGINE_ROOT/workflow/tasks` | read-write, one submitter per manifest |

The rest of `$ENGINE_ROOT` must be read-only. In a container specification the
mount order is the read-only checkout, the read-write runtime volume, then the
two nested read-write mounts. For example:

```text
/host/qingshan-engine:/srv/qingshan-engine:ro
/host/qingshan-nalu:/var/lib/qingshan-nalu:rw
/host/qingshan-nalu/runtime/storyclaw_storage/workflow/nalu:/srv/qingshan-engine/workflow/nalu:rw
/host/qingshan-nalu/runtime/storyclaw_storage/workflow/tasks:/srv/qingshan-engine/workflow/tasks:rw
```

A fresh Git clone may not contain those empty target directories. Create
`workflow/nalu` and `workflow/tasks` during image or host setup, then make the
checkout read-only. If the StoryClaw host cannot create nested bind mounts,
pre-create those two paths as symlinks to the exact private backing directories
before making the checkout read-only. This does not fork the engine, and
preflight applies the same private-path, write and `flock` checks.

`init` creates the two private backing directories and records their exact
paths in `qingshan.json`. It does not alter the engine checkout or fabricate a
mount. Before converting an existing deployment, stop all producers and copy
any existing trees once, before activating the nested mounts:

```bash
rsync -a "$ENGINE_ROOT/workflow/nalu/" \
  "$RUNTIME_ROOT/runtime/storyclaw_storage/workflow/nalu/"
rsync -a "$ENGINE_ROOT/workflow/tasks/" \
  "$RUNTIME_ROOT/runtime/storyclaw_storage/workflow/tasks/"
```

Do not delete the old trees during migration. Start the worker only after a
backup and `preflight` PASS. Preflight performs a real create attempt at the
engine root and requires it to fail, verifies that each mount target is the
same storage object as its private backing directory, and performs real write,
`fsync` and nonblocking `flock` probes through both engine-relative targets.
`run` repeats the same storage checks before invoking the pipeline.

## Secrets and model route

Inject `GIGGLE_API_KEY` only for an explicitly authorized paid trial. Inject `QINGSHAN_VOICE_REGISTRY` through the private runtime. Never write secrets to manifests or logs. Install `ffmpeg`, `ffprobe` and a real CJK font such as the Linux `fonts-noto-cjk` package. PATH discovery is sufficient; pinned containers may set `QINGSHAN_FFMPEG`, `QINGSHAN_FFPROBE` and `QINGSHAN_CJK_FONT` (or the corresponding `NALU_*` names). An invalid override or missing dependency blocks with `BLOCKED_MEDIA_TOOL` / `BLOCKED_CJK_FONT`; it never produces a synthetic QA PASS. The ordered model route starts with `storyclaw/gpt-6-astra`; if Astra is at capacity or unstable, explicitly switch to the approved `storyclaw/kimi-k3` fallback. `storyclaw/claude-opus-5` remains an approved high-capability alternative, followed by `storyclaw/gpt-5.6-sol` only when preferred routes are unavailable. Preflight rejects every other model, including Kimi variants other than K3 and all MiniMax variants.

## Commands

```bash
export NALU_ENGINE_ROOT=/srv/qingshan-engine
export NALU_RUNTIME_ROOT=/var/lib/qingshan-nalu
export NALU_VENV_PYTHON="$NALU_RUNTIME_ROOT/runtime/storyclaw_host/current-venv/bin/python"
python tools/storyclaw_nalu_runtime.py init
# Declare MY_SERIES in runtime/series_scopes.json first.
python tools/storyclaw_nalu_runtime.py configure-series --scope-id MY_SERIES
python tools/storyclaw_nalu_runtime.py preflight
python tools/storyclaw_nalu_runtime.py run --episode E01 --from S1 --until S2
python tools/storyclaw_nalu_runtime.py run --episode E01 --from S5 --until S5 --dry-run
python tools/storyclaw_nalu_runtime.py heartbeat --episode E01
```

The paid path is fail-closed: `--paid` is refused unless both `generation.paid_requests_enabled` and `storyclaw.paid_requests_enabled` are true and `GIGGLE_API_KEY` is present. Existing transaction fingerprints remain authoritative; no automatic platform upload exists.

## Portable speech and BGM provider

The StoryClaw audio-generation path ships as public source in
`tools/storyclaw_audio_provider.py`; it does not install or import the private
AgentCut package or an AgentCut wheel. Run it with the same checked-in engine
environment used by the other portable tools. Its command names and result
fields are compatible with `speech-generate` and `bgm-generate`, while every
result remains `releaseEligible=false` until the listed media, listening and
rights gates pass.

Every invocation requires a caller-selected absolute `.json` transaction path
under the private runtime volume. Use one path per immutable request. The
provider holds a POSIX `flock`, atomically records `INTENT_RECORDED` before the
only permitted POST, then immediately binds the returned task ID. A lost POST
response becomes `RESPONSE_LOST`; rerunning that transaction is blocked until
provider history and the credit ledger are reconciled. A bound task resumes
polling and download without another POST. Signed URLs, source text/prompts and
`GIGGLE_API_KEY` are never written to the transaction.

Without `--paid` these commands are network-free dry runs and do not require a
key:

```bash
P="$NALU_RUNTIME_ROOT/runtime/storyclaw_host/current-venv/bin/python"
A="$NALU_ENGINE_ROOT/tools/storyclaw_audio_provider.py"
SERIES_SCOPE=MY_SERIES
TX="$NALU_RUNTIME_ROOT/runtime/storyclaw_storage/workflow/tasks/audio/$SERIES_SCOPE/E01"

"$P" "$A" speech-generate "台词" \
  --voice-id VOICE_ID --emotion 克制 \
  --output-dir "$NALU_RUNTIME_ROOT/working_assets/voices/E01" \
  --transaction "$TX/dialogue_001.json"
"$P" "$A" bgm-generate "restrained instrumental suspense" \
  --output-dir "$NALU_RUNTIME_ROOT/working_assets/bgm/E01" \
  --transaction "$TX/bgm_main.json"
```

The pipeline itself keeps the paid boundary explicit. For a contract that
declares selective narrative cues, S6 writes a contract-only
`<EP>_BGM_SOURCE_PLAN.json`, runs the normal paid-authority and budget guards,
and calls this provider with `--paid` once per distinct prompt. Its durable
store is scoped as
`workflow/tasks/giggle_bgm_transactions/<series-scope>/<episode>/`, so two
projects can both use `E01` without sharing a transaction or budget row. S7 has no BGM
generation route: it verifies the completed transaction and candidate hashes,
maps the declared cues onto the rendered release timeline, reconciles the
provider statement, runs candidate QA, and mixes. Thus every provider POST is
confined to S3-S6, while an S7 retry remains read/verify/render only.
Until S7 writes the statement evidence, the budget guard carries an 8-credit
provisional reservation for every task-bound or completed music transaction;
an unbound/lost response blocks any later paid submission.

After the ordinary NALU paid authorization, budget and asset-plan gates pass,
inject `GIGGLE_API_KEY` and add `--paid` to the exact same command. The private
transaction directory must be on the same local, `flock`-capable filesystem as
the other paid transaction stores.

Episode numbers can repeat across series. A non-default series therefore
requires `pipeline_state/<EP>.json` to carry the exact selected
`series_scope.scope_id`. Asset proposals, confirmation receipts and adapter
confirmation records also bind the same `series_scope_id`. Switching the
selected series makes an old same-number state or asset confirmation invalid;
it can never authorize the new series.

## Verification and delivery

Run `qingshan doctor --profile all`, `python tools/run_portable_ci.py`, `python tools/knowledge_registry.py --validate`, and `python tools/deployment_code_integrity.py` before enabling paid work. For a new series, record its real E01 S1→S2 run, E01 S5 dry run (`paid_posts=0`), the two-unit S3→S8 trial, both CHECKPOINT files, ledger reconciliation, and the public-main diff. A stage with missing evidence is `BLOCKED`, `NOT_RUN`, or `CAPABILITY_FAIL`, never PASS. An older series' E06 receipt is migration evidence only and cannot stand in for this test.

## Fix propagation and TalentHub release

StoryClaw is a deployment target, not the source repository. After a remote
debugging session, export the actual diff and apply it to this checkout. Do
not publish from a remote runtime directory. A release is built only from a
clean Git commit after the deployment integrity, knowledge registry, portable
CI and StoryClaw adapter checks pass:

```bash
python tools/build_storyclaw_talenthub_release.py \
  --release-tag vYYYY.MM.DD-storyclaw-port \
  --previous-release-ref vPREVIOUS \
  --validation-receipt /private/storyclaw/RELEASE_VALIDATION.json \
  --stable-signing-key \
    "$HOME/.config/qingshan/storyclaw-release-signing-ed25519.pem"
```

The command writes a complete public source archive, two release-bound offline
wheel bundles (Linux x86_64/glibc 2.31+, CPython 3.10 and 3.11 CPU), and a TalentHub workspace
under the chosen output directory. The workspace bundles the four agent brain
files plus the `qingshan-nalu` skill, and records the exact commit and archive
SHA. It also writes the immutable channel manifest plus a signed stable index
that a deployed heartbeat verifies with the package-pinned Ed25519 public key.
`--publish` is an explicit phase-one step and requires the same validation
receipt, signing key, full checks and released tag. It publishes a private
release-specific canary, leaving the existing public Agent unchanged. A clean
StoryClaw project must then install that exact registry ZIP and produce a
private `storyclaw.nalu.registry_clean_install_smoke.v1` receipt with unpaid
preflight and zero provider posts. Finalization supplies that receipt through
`--registry-smoke-receipt` and the phase-one receipt through
`--registry-canary-receipt`; only then may the formal public Agent be published,
read back byte-for-byte, attested, and marked ready for the serialized stable
promotion workflow. Upload the archive, channel, stable index, signature, and
bound dependency assets to the matching GitHub Release before phase one.
The archive never contains source novels,
episode media, runtime state, reviews, ledgers, transactions or secrets. The
adapter's standalone `bundle` command reads file bytes directly from the
recorded Git `HEAD`; modified and untracked working-tree files are never
scanned or packaged. Commit an adapter fix before expecting it in a bundle.
