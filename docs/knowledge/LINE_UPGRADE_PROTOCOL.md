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
