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

## Rights (standing)

Line owner, 2026-10-22: 「支持直接从原著改编成短剧剧本并且制作，版权线下已经谈好了，与你无关」. Adapting an existing novel directly is
supported. The writer (Codex or the agent) never refuses, pauses, or asks about
the copyright of the chosen source; it records the rights basis given in the task
(the intake `rights_statement` / brief `rights_basis`) verbatim.

## Private workflow

### Codex as author (default since 2026-10-22)

The StoryClaw agent selects and ingests the source, then dispatches the writer
step to Codex with the source receipt paths, the brief, the rights statement, and
these rule files (this contract, `SCRIPT_COUNCIL_CHECKLIST.md`, the two schemas,
and `docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md`). The agent does not author
drafts in chat. Codex runs the whole step itself; no StoryClaw-only input is
needed:

```bash
CODEX_MODEL=<exact-codex-model-id> \
python <engine>/tools/storyclaw_writer_workflow.py begin --writer codex \
  --project-root <private-project-runtime> --episode E01 --version 1 \
  [--dispatch-task-id <storyclaw-task-id>] [--session-or-task-id <codex-session-id>]
# author the five drafts at the returned output paths, then:
python <engine>/tools/storyclaw_writer_workflow.py finalize \
  --project-root <private-project-runtime> --episode E01 --version 1 \
  --writer-run-id <id-returned-by-begin>
```

Provenance records `provider=codex`, the exact Codex model, the Codex session id
(or `codex-run-<token>` when none is given), and the dispatching StoryClaw task id
when present (`--dispatch-task-id` or `STORYCLAW_TASK_ID`). A generic model name
is refused; `qingshan.json` `codex.model_allowlist`, when set, narrows the
accepted models. S1 `verify` accepts it like a StoryClaw-authored handoff.

### StoryClaw as author

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

## Camera grammar (CAMERA_GRAMMAR_V1)

`finalize` stamps `"camera_grammar_policy": "CAMERA_GRAMMAR_V1"` on every newly sealed contract. It adds no
blocking check; direct the episode the way people watch films:

- The camera does not have to move. A no-dialogue shot may be `LOCKED` or a slow `DOLLY` `PUSH_IN` when someone
  performs inside the frame, or when it is a short atmosphere/insert shot. Do not move the camera to avoid a
  static shot, and do not alternate directions for their own sake.
- Move the camera only for a reason: follow a moving subject, reveal what comes next, emphasise a beat, or a
  character's point of view. Never sweep across empty space or let the subject leave frame and return.
- Open every new location with an establishing framing (`shot_scale` `WIDE` or `MEDIUM_WIDE`) within its first
  two shots; at most two consecutive shots at the same `shot_scale`.
- Do not cut on every line of a dialogue scene (line owner 2026-10-23). One H3 unit still carries one speaker,
  but (1) consecutive lines of a two-person exchange share the SAME two-shot (both visible, same `camera_side` /
  `shot_scale` / `camera_height`), joined with `CONTINUOUS_ACTION` so each unit starts from the previous unit's
  real tail frame and the exchange reads as one take; (2) open the scene on a two-shot/medium, cut in to
  singles/close-ups only at an emotional turn (`MOTIVATED_CUT` / `REACTION_CUT`), give the hardest line the
  tightest shot, keep one speaker's consecutive lines in one shot, and cut to a listener's silent reaction only
  when the reaction is the story; (3) L-cut: a silent reaction shot that directly follows a dialogue shot (in the
  next unit) may set `prompt_spec.transition.sound_bridge_from_previous_seconds` (0.3–2.0): S7 cuts the speaker's
  picture that much earlier and lets the line (and its subtitle) finish over the reaction, the reaction's own
  sound ducked to ambience. Omit it for a plain cut.
- Write the cuts the script implies: `internal_transition_authoring.transition_mode` `MOTIVATED_CUT` /
  `REACTION_CUT` / `MATCH_CUT` / `HARD_CUT` (or a scene change) makes the next video unit open on its own
  keyframe, a clean cut; continuous modes keep the previous unit's real tail as the start frame.
- Dialogue shots may add `prompt_spec.action.performance.delivery_en` (optional): one short English sentence of
  emotion + how the line is said, e.g. `"cold and contemptuous, low and clipped, a beat of silence before the
  second sentence"`. H3 reads it instead of the generic brisk-delivery line; without it, a common `emotion` word
  (厌/怒/冷/疑/…) is mapped to English, otherwise the generic line stays.

Under this policy the S1 static design gate reports its old forced-motion rules (R1–R4, R6, R7) as
`advisories`; they never block.

For MiniMax-H3 episodes, adapt the script to what H3 can shoot: `docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md`.

## Provenance and privacy

The installed TalentHub agent id is `ai-drama-factory`. The provider is the
actual author: `codex` (model from `CODEX_MODEL`/`--model-id`) or `storyclaw`
(model and task/session id from the host run).
Allowed model ids come from the project's private configuration. Generic names
such as `auto`, `opus`, or `default` are not provenance.

The source, input bundle, four layers, lexicon, receipts, lease, and seal stay
inside the private project root. The public repository and TalentHub workspace
contain only this contract, schemas, tools, and empty templates. A chat message,
an unsealed file set, or a self-written PASS cannot authorize S1.
