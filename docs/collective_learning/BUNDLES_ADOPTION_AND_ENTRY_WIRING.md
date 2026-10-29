# Knowledge bundles, adoption receipts and real-entry wiring

Status: LOCAL_IMPLEMENTED + LOCAL_INTEGRATION_VERIFIED (offline tests, network forbidden).
Nothing here is cloud-deployed; nothing here grants money, publication or execution authority.

## Code

| Module | Responsibility |
| --- | --- |
| `tools/collective_learning/bundles.py` | Data-only knowledge bundles, Ed25519 signing/verification against a pinned trust store, signed revocation lists, content-addressed cache, offline baseline, local resolve, run lock, pre-send lock verification, executable skill-package verifier |
| `tools/collective_learning/selection.py` | Per-unit deterministic scope filter, scene-intent precedence, rank and caps, conflict resolution, application into source-contract carrier fields, dialogue invariance proof, real adjacency, deterministic checks |
| `tools/collective_learning/adoption.py` | SELECTED / APPLIED / VERIFIED / OUTCOME_OBSERVED receipts with the evidence each state needs |
| `tools/collective_learning/impact.py` | Explicit rule impact scope to stale FREE checks; paid steps listed, never re-run |
| `tools/collective_learning/runtime_wiring.py` | Env-driven hooks for the compile and submit entry points; inert without a run lock |

## Where advice lands, and why

`video_prompt_compiler.compile_model_prompt(unit, memory_rules)` accepts `memory_rules`, but neither
renderer reads them. The paid boundary (`submit_giggle_video_manifest_v2`) re-compiles every prompt from
`provider_prompt_unit(task)` and requires byte equality. So advice is written into the SOURCE CONTRACT
fields the renderers already turn into text. That is exactly where an authored fix lives today; no
parallel rules engine is involved.

| Family | Direction (`BEAT_DIRECTION`) | Prohibition (`NEGATIVE_CONSTRAINT`) |
| --- | --- | --- |
| SD2 | `ordered_prompt_specs[0].action.primary_action` (else `performance.event_reaction`) | `ordered_prompt_specs[0].negative_prompts` |
| H3 | `h3_provider_english_contract.beats[0].primary_action` (machine contract copy too) | `h3_provider_english_contract.negative_constraints` |

How the families are handled:

- **H3:** the Chinese source is never amended, because that would stale the bound English contract.
- **Missing language:** a rule with no clause in the grammar's language is `DEFERRED`. Nothing is
  machine-translated.
- **Engineering invariants** (`CHECK_ONLY`) never become prompt bans. They route to deterministic checks:
  - `CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT` calls the engine's own `validate_camera_sequence`.
  - `NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY`
  - `VISIBLE_CAST_BOUND_TO_PROJECTION`
  - `DIALOGUE_LINES_IN_COMPILED_PROMPT`

Limits and safety:

- **Caps:** at most 3 rules and 400 added characters per unit (configurable).
- **Dialogue:** proven byte-identical by a fingerprint taken before and after application.
- **Control language:** clauses that try to steer budget, paid redo, gates, secrets or publication are
  rejected at bundle validation. Selection rejects them again if one gets through.

## Entry points

| Entry | Wiring | Test |
| --- | --- | --- |
| S1 `line_upgrade_gate.preflight` | Opt-in when `<reports>/COLLECTIVE_LEARNING_CONFIG.json` exists. It resolves from the local verified cache, writes the run lock once (`<line>.<episode>.<batch_id>`), records SELECTED receipts and returns `collective.child_env`. READ stays a compatibility status and carries `knowledge_status_semantics: READ=BRIEFING_WRITTEN_NOT_APPLIED`. A failure is advisory: it is recorded and never blocks. | `PreflightAndPipelineWiringTest` |
| `nalu_pipeline.Ctx.child_env` | Exports `QINGSHAN_KNOWLEDGE_*` / `QINGSHAN_COLLECTIVE_*` only when the episode's preflight reports `collective.status == LOCKED`. | `test_pipeline_child_env_exports_only_a_locked_run` |
| SD2 strict compile `compile_grouped_seedance_manifest.compile_final_prompts` (the v4 `--final-prompt-dir` path; extracted from `main()` without behaviour change) | Applies to the unit's source contract before the strict compile and records APPLIED (`COMPILED_REQUEST`) with with/without-rule evidence. | `Sd2StrictCompileTest` |
| `build_nalu_preproduction.finalize_video_tasks` | Carries `knowledge_lock` + `knowledge_adoption` from the compiled unit onto the task. | (exercised through the submit test's task shape) |
| H3 `build_nalu_preproduction.render_h3_final_prompts` | Amends the bound English contract(s) the boundary reads. It keeps the pristine contract, so every S6 re-render is idempotent. | `H3FinalRenderTest` |
| POST `submit_giggle_video_manifest_v2.submit_one` | For a task with `knowledge_lock`, `verify_lock_for_send` runs before the intent record. If it fails, the NEW post is refused with a pre-intent block file: no transaction and no charge. After the task id is bound, a PROVIDER_REQUEST receipt is written only if the sent prompt bytes equal the verified compile. | `SubmitBoundaryTest` |
| Resume (`prior_bound`, `live_bound_elsewhere`) | Returns before the knowledge check, so it keeps its original binding and never POSTs again, even with a tampered lock. | `test_tampered_lock_refuses_new_post_but_resume_keeps_original_binding` |

Correction to the wiring audit: `compile_grouped_seedance_manifest.write_preflight_artifacts` is the
LEGACY grouped-preflight bundle. It is not reached by the v4 runtime, and at baseline 1221d64 it raises
`NameError: event_decision` if it ever is reached. That bug was not fixed here, because it is out of
scope.

## Known bypasses (left unmodified)

`tools/giggle_omni_video_fallback.py`, `tools/submit_e20_static_visual_lock_batch.py` and
`tools/giggle_asset_factory.py` POST with raw `urllib`, outside `giggle_api_client._request`'s guard.
They are not referenced by `nalu_pipeline`, the builder, the formal submitters, the compiler or any
`lines/nalu/runtime/tools` module (`KnownBypassInventoryTest`). Retiring them is a separate engine
change.

## Skill packages

Executable skills never travel through knowledge sync: a bundle carrying `skill`/`skills`/code is
rejected. A skill package is a signed manifest with these fields:

- `interface_version`, `entrypoint` (a relative engine module), `code_sha256`, `dependencies`
- `permissions{shell, network, paid, dynamic_install}`, `cost_capabilities`

`verify_skill` refuses shell, network and dynamic install unless the trust store's `skill_policy`
allows them. It always refuses `paid`, because money authority stays with the line's paid order.

The code itself ships through the engine release process (git, review, `deployment_code_integrity`).
The manifest only proves provenance and pins the code digest. A signature proves who published, not
that the content is correct.

## Opt-in config (per line)

```json
{"tenant_id": "...", "line_id": "...", "trust_store": "trust.json", "cache_dir": "bundle_cache",
 "channel": "RELEASED", "engine_api_version": "...", "capabilities": {"model": "MiniMax-H3"},
 "batch_id": "B1", "device_store": true,
 "revocations": "revocations.signed.json", "baseline": {"path": "...", "digest": "..."}}
```

Without this file, every hook returns `None` and production behaviour is unchanged.
