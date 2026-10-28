# Line upgrade protocol (all production lines)

Every production line built on this engine must, for every episode:

1. **read** the engineering knowledge base before the episode is written;
2. **write** what the episode taught back into it when the episode closes;
3. **run the current engine**: not a stale checkout, and not a local overlay that silently replaces engine modules.

The engine does this in one tool, `tools/line_upgrade_gate.py`. A line's orchestrator makes two calls to it and nothing else. The tool uses only the standard library, never posts to a provider, and never authorizes production.

## The two calls

`<engine>` is the engine checkout the line imports. `<runtime>` is the line's runtime state root for the episode, where the line keeps its `reports/` directory. `<line>` is a short line id. `<EP>` is the episode id.

### 1. Before writing an episode: `preflight`

```
python3 <engine>/tools/line_upgrade_gate.py preflight --line <line> --episode <EP> \
    --runtime-root <runtime> --engine-root <engine> [--declare-overlay <dir>]... [--fetch] [--strict]
```

What it does:

- **Engine freshness.** Compares the engine `HEAD` with its remote-tracking branch (`@{u}`, or `origin/main` if none is set). It uses the tracking ref as last fetched and only touches the network with `--fetch`. It also lists dirty tracked files.
- **Overlay check.** Scans for directories that could shadow engine modules: `--overlay-dir` arguments, `PYTHONPATH` entries outside the engine, and any `engine_overlay*` directory inside or next to the runtime root. In each one it compares every `.py` file with the engine file at the same relative path (`<rel>`, `tools/<rel>` or `qingshan_engine/<rel>`) by sha256. It reports whether the overlay file assigns into `sys.modules`.
- **Knowledge read.** Validates and exports the registry through `tools/knowledge_registry.py`. It writes `<runtime>/reports/<EP>_KNOWLEDGE_BRIEFING.json` (every rule, every failure-memory row, the registry sha256 and the engine HEAD) and a short `<EP>_KNOWLEDGE_BRIEFING.md`. The agent writing the episode reads the `.md`. The rows are abstract causes not to repeat, never text to copy.
- **Receipt.** Writes `<runtime>/reports/<EP>_LINE_UPGRADE_PREFLIGHT.json` for `close` to check.

Statuses:

| Status | Meaning |
| --- | --- |
| `PASS` | Nothing to report. |
| `STALE_ENGINE` | `HEAD` is behind the tracking branch. |
| `UNDECLARED_OVERLAY` | An undeclared directory shadows an engine module with different content. |
| `KNOWLEDGE_REGISTRY_INVALID` | The registry could not be read (exit 1). |

Notes that never fail the call: `DIRTY_TRACKED_FILES`, `DECLARED_OVERLAY`, `NO_UPSTREAM`, `ENGINE_NOT_GIT`, `FAILURE_MEMORY_DRIFT`.

Findings are advisory by default (exit 0). With `--strict`, `STALE_ENGINE` and `UNDECLARED_OVERLAY` exit 2. A line that has to stop on a stale engine uses `--strict`. An episode already in production records the result and keeps going.

### 2. After the episode is approved: `close`

```
python3 <engine>/tools/line_upgrade_gate.py close --line <line> --episode <EP> \
    --runtime-root <runtime> --engine-root <engine> [--from-file rows.json] [--strict]
```

What it does:

- **Runs the shared knowledge writer** (`tools/knowledge_sync_core.py`). It appends the rows the session authored in `<runtime>/reports/<EP>_knowledge_candidates.json`, plus any `--from-file` rows, to the registry, the knowledge-base markdown and `knowledge/failure_memory.jsonl` together.
  - Each row is validated first.
  - Rows are idempotent by slug.
  - A row without a real `recovery` is reported as a gap and not written.
  - `NO_NEW_KNOWLEDGE` is reported visibly.
  - Turning a failure into a rule is the session's job: write the candidates file before calling `close`.
- **Checks that the preflight briefing exists.** If it is missing, the status is `KNOWLEDGE_NOT_READ`. This is advisory; it exits 2 only with `--strict`.
- **Writes `<runtime>/reports/<EP>_LINE_UPGRADE_CLOSE.json`.**

The registry changes in the engine checkout. Merge it back to `main` through the normal S7-SYNC route (AGENTS.md §8), so that the next `preflight` of every line reads it.

A line that already runs the writer itself, such as nalu at S8, calls `close --skip-sync` to verify the read side only.

## Declaring overlays

An overlay is any local directory whose modules replace engine modules at run time: a directory put on `sys.path` ahead of the engine, or files loaded into `sys.modules` under an engine module name. Overlays are allowed only when declared. Declare each one with either:

- `--declare-overlay <dir>` on `preflight` (repeatable), or
- the environment variable `QINGSHAN_ENGINE_OVERLAY_DIRS` (list separated by `os.pathsep`).

A declared overlay that shadows modules is reported as `DECLARED_OVERLAY`, listing each shadowed module and both sha256 values, and does not fail. An undeclared one is `UNDECLARED_OVERLAY`. An overlay is a debt: once its change is right, merge it into the engine and delete the overlay.

## Adoption for a line whose engine is a git checkout of this repository

Use this when the checkout already contains `tools/line_upgrade_gate.py`. Otherwise run `git pull` on `main` first.

The single adoption step: add the `preflight` call as the first action of the line's episode start, and the `close` call as the last action after approval. Pass the line's overlay directories with `--declare-overlay`, or export `QINGSHAN_ENGINE_OVERLAY_DIRS` once in the line's environment.

For example, a line whose episode scripts import the engine by inserting the checkout into `sys.path` adds this to its startup procedure:

```
python3 <engine>/tools/line_upgrade_gate.py preflight --line <line> --episode <EP> --runtime-root <runtime> \
    --engine-root <engine> --declare-overlay <runtime>/engine_overlay_<name>
```

It then hands `<runtime>/reports/<EP>_KNOWLEDGE_BRIEFING.md` to the agent that writes the episode.

## Proving a rule was actually applied, not just read (gap closed 2026-10-28)

Codex knowledge-loop audit 2026-10-27 found that `preflight`'s `knowledge.status = "READ"` means only that the briefing *file* was written — `verify_briefing` checks file existence (and, separately, a sha match that nothing currently gates on), never whether a single rule in it was consulted while the episode was written. "Exported" (in the briefing), "applied" (a rule's clause actually fired on a real shot) and "verified" (that firing's effect was checked against real compiled/submitted content) are three different claims. `preflight`/`close` still own EXPORTED; the other two are `tools/knowledge_consumption_ledger.py`'s job, fed from the one real place a prompt-stage rule can fire: `nalu_prompt_rules.apply(shot, ctx)`.

Every `nalu` episode builder already calls `apply` once per shot and collects the result (`build_e12_layers.py:1497-1498`, unchanged since E02): `clauses, applied, blocks = NPR.apply(shot, ctx)` then `NPR_APPLIED[shot_id] = applied`. Until now `NPR_APPLIED` was discarded after the builder printed its length. The one-line adoption, added once at the end of the shot loop (after `NPR_BLOCKS` is confirmed empty, so a restaged shot is never recorded as applied):

```python
import knowledge_consumption_ledger as _kcl
_kcl.record_application(RUNTIME_ROOT, episode=EP, line="nalu", stage="S1", npr_applied=NPR_APPLIED)
```

`record_application` reshapes `NPR_APPLIED` through `nalu_prompt_rules.applied_summary` (reverse-indexed by rule tag) and keeps only `KNOWLEDGE:<id>` tags as registry-rule evidence — `apply`'s own hardcoded guards (`SOLO_FACE`, `NO_BLACK`, ...) are not auto-claimed as a registry rule's evidence unless the caller passes `tag_to_rule_id={"SOLO_FACE": "K009", ...}` explicitly. It never reads episode text and never touches a paid task, transaction or budget ledger.

A regression test that has actually asserted a rule's effect on real compiled/submitted content (not merely that a test file exists) calls the companion `record_verification(runtime_root, rule_id=..., test_name=..., assertion=..., checked_output=...)`.

`tools/knowledge_consumption_ledger.status_for_rule(engine_root, runtime_root, episode, rule_id)` composes all three claims from their real sources (the briefing file for exported, this ledger for applied/verified) into one report — `{"exported": bool, "applied": bool, "applied_evidence": [...], "verified": bool, "verified_evidence": [...]}` — so nothing downstream has to re-derive "applied" from "exported" the way `KNOWLEDGE_NOT_READ` used to stand in for both.

This was deliberately NOT retrofitted into any already-running episode's builder: `build_eNN_layers.py` is a private, gitignored, per-episode file (`.gitignore:144`, never a git-tracked path), and an in-production episode's generation contract is not something this change touches. The one-line call above is for the next episode's builder to adopt when it is written.

## Pointing new knowledge at what to recheck, never at what to resubmit (gap closed 2026-10-28)

Constraint 4 of the same audit: a newly-synced rule may trigger a recheck of the FREE checks it affects, but must never auto-resubmit a paid task and must never add a paid-redo condition. `close`/`sync` already load `pipeline_state/<episode>.json` into a local `state` variable (`tools/knowledge_sync_core.sync`) and, until now, never used it — the docstring explains why nothing derives a *candidate row* from it (a status table names no cause), which is a different question from this one: given a row a human/agent already authored, which of this episode's already-recorded steps does it affect.

`tools/knowledge_sync_core.free_recheck_targets(state, rows, rule_ids)` answers that by a direct, textual match: a rule's `implementation` file against the exact `argv` `nalu_pipeline.py` already recorded for every step it ran. Every matched step carries the run's own `paid` flag, so the function partitions matches into `free_matches` (safe to point at) and `paid_matches_excluded` (named for transparency, never recommended). A rule whose implementation is a library imported by other code rather than a step's own script correctly reports no direct match — its `fallback_verification` is that rule's own `regression` field, already re-run by every `tools/run_portable_ci.py` pass, rather than a guessed import chain.

`sync()` calls this once, only on its `SYNCED` branch, for the ids it just appended, and adds the result under the returned `free_recheck` key — `DRY_RUN` and `NO_NEW_KNOWLEDGE` are untouched. Because every line's real sync entry point already returns through this function (`tools/line_upgrade_gate.py close`, or nalu's own `lines/nalu/runtime/tools/knowledge_sync.py` called from `nalu_pipeline.stage_s8`), nothing new had to be wired to reach it — `nalu_pipeline.py`'s existing CHECKPOINT.md writer now also renders which new rule ids matched a free step this episode already ran (re-run that step before trusting its cached PASS) versus which matched none (trust only the regression suite). No file is written that was not already being written, and no provider is ever called from this path.


