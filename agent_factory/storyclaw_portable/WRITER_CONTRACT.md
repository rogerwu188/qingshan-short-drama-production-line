# StoryClaw portable writer contract

This contract applies to every private project created by the TalentHub NALU
Agent. It contains no story, customer, character, episode outcome, or test data.

## Authority and order

The StoryClaw writer reads only the source artifacts named in the private writer
input bundle. It must not reconstruct missing source from search snippets, another
project, or a remembered test story. The writer creates these layers in order:

1. `<EP>_NARRATIVE_CANONICAL_v<V>.md` — story facts, performable action, and
   dialogue; no camera or provider instructions.
2. `<EP>_DIRECTING_SCRIPT_v<V>.md` — shot order, framing, camera, blocking,
   screen direction, and performance direction; it cannot change narrative facts.
3. `<EP>_GENERATION_CONTRACT_v<V>.json` — the structured production contract
   consumed by S1–S8. It uses `qingshan.generation_contract.v3` and must carry all
   writer-owned production fields required by the registered gates.
4. `<EP>_manifest_v<V>.json` — source beats, scene-level landings, insertions,
   timing, locations, script binding, and the four-layer manifest.

The writer also creates `<EP>_LEXICON_DRAFT_v<V>.json`. It declares only facts
for this project: `world_basis`, `forbidden_terms_basis`, `forbidden_terms`, and
`address_terms`. The workflow tool derives canonical names and aliases directly
from the generation contract, adds the public performance vocabulary, binds the
result to the source receipts and four-layer SHA-256 values, and writes an
immutable `<EP>_PROJECT_LEXICON_v<V>.json` beside the four layers. It also
refreshes the project's private `runtime/series/<SERIES_SCOPE_ID>/lexicon.json`
as a latest-status mirror; S1 reads the immutable snapshot selected by the
active handoff, so a later episode cannot invalidate an earlier seal.

## Private workflow

The host supplies the actual StoryClaw model in `STORYCLAW_MODEL`. Begin a run
with the real StoryClaw task or session id:

```bash
STORYCLAW_MODEL=<exact-host-model-id> \
python <engine>/tools/storyclaw_writer_workflow.py begin \
  --project-root <private-project-runtime> \
  --episode E01 \
  --version 1 \
  --session-or-task-id <real-storyclaw-task-id>
```

`begin` writes a private input bundle and returns the exact five output paths.
Read the source files from that bundle, author the three pre-manifest layers, the
manifest draft, and the lexicon draft, then finalize the same run:

```bash
python <engine>/tools/storyclaw_writer_workflow.py finalize \
  --project-root <private-project-runtime> \
  --episode E01 \
  --version 1 \
  --writer-run-id <id-returned-by-begin>
```

`finalize` must run under the same exact `STORYCLAW_MODEL` value recorded by
`begin`. If capacity or routing changes the model during authoring, abandon that
run and start a new higher writer version so the receipt names the model that
actually authored the bytes.

Only `finalize` may inject `writer_provenance`, derive the canonical project
lexicon, seal the four layers, and select the active writer handoff. Do not write
those authority records by hand. A revision uses a new higher version and a new
writer run; sealed older bytes remain unchanged.

## Source and manifest requirements

- Every scene in `manifest.structure` must land a real source beat in
  `beat_disposition`, or be listed in `★authorized_insertions` with its source
  basis and new-information disclosure.
- The manifest source binding identifies the private intake source/section used;
  it never copies source prose into public state.
- Dialogue, key quotes, identities, props, locations, causal state changes, and
  continuity must be traceable to the selected source or an explicit insertion.
- Character ids are stable within the private series. `canonical_name` and
  `aliases` in `character_entities` are the sole source of canonical-name rules.
- `writer_selfcheck_seq29.enforced` must be true. S1 runs it against the private
  project lexicon; an absent declaration or a failed report blocks the stage.
- The generation contract must specify a real hook, dialogue coverage, action
  outcomes, entity/prop setup, continuity states, visual culture, camera,
  performance, sound, and start/end state evidence required by the registered
  gates. Missing fields remain a failure; do not lower thresholds.

## Provenance and privacy

The installed TalentHub agent id is `ai-drama-factory`, the provider is
`storyclaw`, and the exact model and task/session id come from the host run.
Allowed model ids come from the project's private configuration. Generic names
such as `auto`, `opus`, or `default` are not provenance.

The source, input bundle, four layers, lexicon, receipts, lease, and seal stay
inside the private project root. The public repository and TalentHub workspace
contain only this contract, schemas, tools, and empty templates. A chat message,
an unsealed file set, or a self-written PASS cannot authorize S1.
