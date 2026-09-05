# Production / GitHub integrity audit — 2026-09-05

Release candidate: engine **0.3.1**, based on public main
`11f4743453bf54464c65635c39f25881ed7d1cab`.

## Scope and boundaries

Reviewed the reusable path from Writer Agent and canonical/registry validation,
image/video compilation and durable submission, polling, native-audio editing,
release QA through YouTube/Douyin order/receipts. Compared tracked reusable files
against the active production installation, not just the latest commit. No
paid generation, episode reconstruction, publication or private runtime mutation
is part of this audit. MIT applies to engine code, not third-party source novels,
model outputs, account credentials or other people's assets.

The source inventory is `configs/DEPLOYMENT_CODE_SHA256.json`. It covers Python
and shell tools, Writer code/resources, package metadata and shared registries.
Mutable Writer `state` and `SUPERVISOR_ORDERS.json` files are intentionally
excluded: production has real supervisory history where a clean install has
skeleton templates. Private episodes and historical evidence are also excluded.
Unlisted local scripts are not certified by this inventory. A PASS proves parity
of the listed files, **not** that private datasets are identical or models are
deterministic. Verification works from a GitHub source ZIP without Git.

## Defects repaired

| Area | Defect | Repair / non-regression boundary |
| --- | --- | --- |
| Paid submission | Concurrent workers could both pass the pre-submit read | Per-transaction process/thread file lock through POST and durable task binding; retain lock inode |
| Task recovery | Receipt write failure could lose the already returned task ID | Bind ID/full response in transaction first; recreate missing secondary receipt on resume without another POST |
| Transaction files | Shared `.part` filename raced; task keys allowed unsafe paths | Unique fsynced temp files with atomic replace; reject unsafe transaction keys |
| Transport context | Process-wide environment/depth leaked between concurrent requests | Context-local video/image authorization; image context cannot authorize video; no blind retry for generation POST |
| Billing | Missing/lagging aggregate ledger entry could be called a zero-charge failure | Remain unresolved unless specific evidence establishes safe recovery; never downgrade a bound task |
| Payload integrity | Prechecked prompt/reference files could change before submission | Recheck hashes under the submit lock; duration and image/audio slot types/bounds checked explicitly |
| Model separation | SD2 grouping could inadvertently enter H3-only speaker parsing | Limit the H3 parser to H3; retain SD2 model-specific grammar and shared structured contracts |
| H3 identity | Ambiguous or duplicate image/voice slot bindings | Strict slots/duplicate voice-row validation; explicit offscreen audio semantics |
| Release evidence | Stale PASS, mismatched final hash and mixed candidate evidence | Bind speaker evidence to actual final bytes; validate one complete candidate; reject malformed counts and wrong episodes |
| Stage execution | Previous output could masquerade as newly generated PASS | Archive previous report; missing/invalid/contradictory new output fails; source-read handles its intentionally absent canonical hash |
| Platform order | Unscoped text could incorrectly mark Douyin complete | Require platform-specific terminal state plus media ID/URL; invalid/missing queue holds |
| Media rendering | Duplicate decoding; ignored unsupported timeline features; partial overwrite | Reuse native A/V input, reject unsupported features rather than dropping them, validate finite dimensions/times, atomically replace only successful renders |
| Audio leveling | Failed render could erase an existing approved output | Require fresh distinct versioned media/QA paths; keep native audio and bit-exact video check |
| QA resources | Missing mandatory references could be silently skipped | Explicit failure; locate auditors in engine, not private manifest directory |
| CLI deployment | `--` forwarding and relative paths broke outside engine root | Normalize caller paths before launching engine tools; explicit runtime root |
| Optional dependencies | Importing pure boundary evidence checks required Pillow on clean CI | Load Pillow only in image-processing functions; media processing still requires the declared media extra |
| Writer self-check | Nonfinite limits could escape numeric comparisons | Fail nonfinite values; close read handles correctly |

## Local capabilities previously missing from the public version

Merged positive-only H3 single-subject and tight-POV projection, hidden-role
suppression, reviewed clean-anchor alternatives to contaminated predecessor tails,
changed-field-only state prose (full machine state retained), Writer-declared
civilian visual-domain constraints, short terminal defect exclusion and narrowly
evidenced motivated foreground occlusion handling. Preserved SD2 impulse vocabulary.
Added the existing Writer insertion/disclosure and version/self-limit helpers,
native release-audio leveling tool and structured opening-chain regressions.

Persistent publication authority is now read by the public release preflight;
the policy itself does not grant consent. A fresh deployer needs their own local
authority. E40 remains permanently excluded. Browser safety confirmations remain
subject to the browser runtime, not this repository's policy text.

## Quality and functional invariants

- No changes to map, weather, shot-type or camera-authority decisions.
- Writer/director remains the source of visual culture, performance and sound
  choices. Model-specific rendering does not invent alternate story facts.
- SD2 and H3 retain separate grammars, shared structured semantic contracts.
- Native same-task dialogue/environment/Foley retained; no TTS substitution.
- No new VLM, optical-flow, action-detail or motion-energy post-generation gates.
- Codec/CRF/preset/audio bitrate unchanged in the portable renderer. Unsupported
  advanced edits must use the advanced backend, never silently lose layers.
- Private order history, episode assets, credit ledger and platform receipts are
  not reset or replaced with clean-install templates.

## Verification and deployment contract

Local clean-core run: **368 tests, 11 explicit skips**, 47 modules and 55 required
files; registry closure passes. Skips are historical/private-evidence fixtures,
not claims that those episodes passed. Compileall covers tools, engine and Writer
source. New tests include concurrent image/video submission with mock providers,
task recovery after receipt failure, malformed evidence, source overwrite safety,
and a real FFmpeg synthetic native-A/V render. No provider credits were spent.

Fresh Python 3.9 virtual environment: upgrade pip, editable source installation,
and `qingshan doctor --profile core` pass. Installation requires the **complete
source checkout**, not the small Python wheel alone. See `DEPLOYMENT.md`.

GitHub CI must pass for the exact published commit on Python 3.9/3.11/3.12.
The SHA inventory and release tag identify the verified source. A production
comparison receipt is kept outside the public repository because installation
paths and runtime state are private.

## What this audit does not prove

It is not a paid end-to-end run using a third party's account, nor an assertion
that every historical script or model-generated scene is error-free. Browser
login, supported publisher integrations, provider availability, private source
rights and project credentials must be supplied by each deployer. The core suite
is deliberately offline; full historical replay requires the corresponding
private evidence store. SHA checks establish consistency, not supply-chain trust:
download the inventory from the same trusted release as the source.
