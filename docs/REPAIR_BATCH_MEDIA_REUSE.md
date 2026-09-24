# Repair batches: generation and existing-media reuse

`tools/episode_prompt_batch_gate.py` supports explicit per-row modes. Omitted
`mode` retains the original `GENERATE` behavior and all prompt QA requirements.
Unknown modes fail closed.

`REUSE_EXISTING_MEDIA` rows do not need newly compiled hypothetical prompts.
They require SHA-bound `reuse_evidence` entries for:

- `media`: the exact already-generated file;
- `assembly_receipt`: the original unit-bound assembly receipt;
- `admission_result`: the original admission, bound to the same media;
- `continuity_review`: a separate review of reuse in the current repair context.

The assembly receipt must identify the unit (or an explicitly declared
`parent_unit_id` for an intermediate-shot row), exact media path and SHA, and
`ADMITTED_FOR_ASSEMBLY`. The admission must be `ADMITTED`, have no failures and
identify the exact same media. Historical admission is not a fresh visual QA.

The continuity review must include `status=PASS`, current `execution_id`, parent
`unit_id`, `media_sha256`, `scope=REPAIR_CONTEXT_CONTINUITY`,
`cross_unit_continuity_checked=true`, reviewer and substantive observation.
It must also list nonempty SHA-bound `context_refs` for the inputs actually
reviewed. A changed context invalidates that review. Missing or unperformed
reviews are never generated as PASS by the gate.

`require_generation_batch` rejects reuse rows for both image and video
submissions, even if the preparation batch passes. Existing bound-transaction
recovery remains upstream; this change does not alter transactions or billing.
The gate neither generates media nor changes final assembly/release admission.

Regression tests: `tools/tests/test_prompt_batch_reuse.py` covers valid reuse,
denied POST, changed media/context, wrong unit, revoked admission, missing or
unverified review, wrong admitted asset and unknown mode. Existing generation
and paid-boundary tests must also pass before deployment.
