# Engine patches applied by the nalu line (historical record)

Each `eNN_*.diff` is the unified diff the nalu line applied to the engine (`tools/`, `qingshan_engine/`)
while producing episodes E01–E03. They are kept here so a reader can see *why* the engine changed; they
are not meant to be re-applied:

- **e08–e21** are already merged into the repository on branch `integration/e03-sync` (and on `nalu-line`),
  so a fresh clone of that branch or of `main` after it is merged already contains them.
- **e23** (`e23_bgm_authenticity_gate_window_isolated_label.diff`) is applied on branch `engine/e23-bgm-window-label` (accepted by the line owner 2026-09-15).
- **e22** (`e22_agentcut_bgm_cloudflare_user_agent.diff`) patches AgentCut, which lives in a separate
  repository (`rogerwu188/backlot-os`, branch `agent/hell-grind-v19-production`, commit `715e46f`). Install
  AgentCut from that branch or later.

Paths inside the diff headers were rewritten to `$ENGINE_ROOT` / `$RUNTIME_ROOT`; hunks are unchanged.
The reasoning for each patch is in `../../docs/PIPELINE_RUNBOOK.md` (decision records D-1…D-36) and, in
generalized form, in `docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md` at the repository root.
