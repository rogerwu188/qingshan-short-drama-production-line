# Mandatory whole-batch prompt preparation

Before generating an episode, copy `configs/EPISODE_PROMPT_BATCH_POLICY.json` to `workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json` and register its complete approved unbound unit scope under `executions[execution_id]`. If no runtime override exists, the shipped default policy is enforced. The shipped policy has no customer executions: fresh episode generation fails closed until registered. Existing bound transactions remain recoverable.

Each execution has `unit_ids`, optional `unit_aliases` for shot-to-video-unit mapping, and `manifest_ref`. The manifest contains `execution_id` and `rows`. Every row has `unit_id` plus `keyframe_prompt`, `video_prompt`, and `prompt_qa`, each a project-relative `{path, sha256}` reference.

Write every keyframe and video prompt before starting generation. Review each prompt and all cross-unit continuity: story, cast, voice ownership, costume, props, persistent injury, environment, map, camera and timing. A QA receipt must contain `status: PASS`, matching `unit_id` and `execution_id`, `keyframe_prompt_sha256`, `video_prompt_sha256`, `scope: PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY`, and `cross_unit_continuity_checked: true`. The gate verifies evidence; it does not perform or fabricate creative QA.

Both paid image and video submitters enforce the batch after transaction recovery and before new uploads/intents/POSTs. A missing unit, stale file, duplicate unit or incomplete QA blocks the batch. Task flags cannot disable project policy. Model compiler grammar, original admission gates and budget guards remain unchanged.

Real predecessor media can delay final reference binding but never prompt authoring. If materialization changes a reviewed prompt, attach `prompt_batch_finalization: {path, sha256}` to the task. That receipt must bind `status: PASS`, `execution_id`, `unit_id`, `artifact_kind` (`keyframe_prompt` or `video_prompt`), `planned_prompt_sha256`, `final_prompt_sha256`, and `scope: INCREMENTAL_EXACT_MATERIALIZATION_QA`. Original exact-reference admission still applies.

Generic reusable assets without episode identity are outside episode-unit batching. Existing projects without this policy retain legacy compatibility; new deployments receive the policy by default. No generated media or paid validation is included in the software tests.

Tests: `python -m unittest tools.tests.test_episode_prompt_batch_gate tools.tests.test_episode_prompt_batch_paid_boundary`.
