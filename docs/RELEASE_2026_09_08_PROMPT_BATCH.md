# v2026.09.08.1 — Mandatory whole-batch prompt preproduction

- Paid image and H3/SD2 video submission requires complete batch keyframe/video prompt QA, including cross-unit continuity and exact SHA binding.
- Missing units, altered prompts and unregistered executions fail before new provider side effects.
- Existing transaction recovery remains available; actual-tail materialization uses incremental exact QA.
- No model prompt grammar, map, weather, camera, identity, budget or media-quality gate changes.
- Public default configuration ships without private episode data. Deployment instructions: [whole-batch preproduction](WHOLE_BATCH_PROMPT_PREPRODUCTION.md).

Validation in an isolated checkout of main: 15 new tests passed; portable core suite 368 tests passed with 11 explicitly skipped legacy/runtime tests. Deployment integrity inventory regenerated for 1,799 files. No paid generation or platform publication was performed by these tests.
