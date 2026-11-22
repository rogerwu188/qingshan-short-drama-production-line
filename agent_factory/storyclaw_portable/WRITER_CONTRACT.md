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

## Adapt for viewers, not word for word (owner 2026-11-02)

Readers imagine; viewers only see shots and hear lines. Test: with the novel closed, a viewer can say what happened in
each scene and why each shot is there. Dramatize narration, summaries, inner states and time spans (characters,
dialogue, reactions) or carry them with one V.O./caption line; give every shot and insert a readable purpose; montage
needs progression and a payoff; actions H3 renders badly (sword play, fights, spell effects) become results or
reactions. Keep the source's key plot facts, character truths and best lines; under SHORT_DRAMA_PACING_V1 (below)
cutting, merging and compressing the rest is required, not optional. Principles and examples:
`docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md` §0.

## Adaptation compression and short-drama pacing (SHORT_DRAMA_PACING_V1, line owner 2026-11-22)

"The plot moves too slowly; an episode is basically characters reciting lines." When the dispatch carries
`pacing_policy: SHORT_DRAMA_PACING_V1` (every new dispatch; episodes already in flight without it are unchanged),
write `"pacing_policy": "SHORT_DRAMA_PACING_V1"` at the contract top level and:

- **Budget the episode by plot events, not chapters.** Cover at least max(4, floor(D / 25)) plot events (one major
  turn every ~25–30 s; ~4–6 for a 115 s episode), pulling from as many source chapters as that needs (typically
  2–5). You are licensed to cut filler, greetings and repeated exposition, merge scenes, drop minor characters,
  compress time, reorder for the hook and invent connective action; keep only the key plot facts and character
  truths. Declare it in `adaptation_plan`: `{"source_chapters": [N, ...], "plot_events": [{"event", "chapter",
  "shot_id"}], "cut": ["what was cut / merged / compressed"]}`; the manifest's `beat_disposition` still lists every
  source beat (`dropped` / `merged` are valid dispositions). S1 records the chapters in
  `<runtime>/series/SOURCE_COVERAGE.json`; the next episode starts at its `next_chapter`.
- **Beat structure.** Cold-open conflict in the first 3 s (`pacing.hook.at_seconds` <= 3). An escalation, reversal
  or reveal every ~20–30 s — humiliation then payback, a secret revealed, a power shift, a slap or confrontation, a
  romantic-tension spike, a threat confirmed — listed in `pacing.beat_sheet` (`[{"shot_id", "type":
  HUMILIATION_PAYBACK|IDENTITY_REVEAL|POWER_SHIFT|SECRET_REVEALED|THREAT_ESCALATION|CONFRONTATION|ROMANTIC_SPIKE|
  REVERSAL|DISCOVERY, "setup_shot_id"}]`, payoff shots also `prompt_spec.beat_role: PAYOFF`). End on the
  cliffhanger itself: `pacing.cliffhanger` = `{"shot_id": <last shot or within the last 8 s>, "open_question"}`.
- **Every scene has a visible objective, a conflict and a physical action** (`pacing.scene_plan`:
  `[{"scene_id", "objective", "conflict", "physical_action"}]`); no scene is only two people talking — at least one
  shot per scene changes a physical state (`state_delta_dimensions` MOMENTUM / CONTACT / POSSESSION / POSITION /
  INTEGRITY). Turn exposition into visible action and reaction. At most 2 short sentences per line; no
  back-to-back monologue over ~12 s; speaking shots without a MOMENTUM / CONTACT / POSSESSION / INTEGRITY action
  stay under ~60 % of the episode.
- **Free S1 self-check and revision.** S1 measures these numbers (`lines/nalu/runtime/tools/script_pacing_check.py`:
  turns per minute, seconds to first conflict, longest gap between turns, dialogue-only share, longest line, scenes
  without action, open ending, adapted plot events). A failing script gets `SCRIPT_PACING_REVISE:round=n/2`: revise
  your own layers and rerun S1 — no owner, no paid call. After two revisions the engine admits the script and records
  the gaps; the numbers also go to the final review's director pass as context.

## Camera grammar (CAMERA_GRAMMAR_V1)

`finalize` stamps `"camera_grammar_policy": "CAMERA_GRAMMAR_V1"` on every newly sealed contract. It adds no
blocking check; direct the episode the way people watch films:

- The camera does not have to move. A no-dialogue shot may be `LOCKED` or a slow `DOLLY` `PUSH_IN` when someone
  performs inside the frame, or when it is a short evidence insert. Do not move the camera to avoid a
  static shot, and do not alternate directions for their own sake.
- Move the camera only for a reason: follow a moving subject, reveal what comes next, emphasise a beat, or a
  character's point of view. Never sweep across empty space or let the subject leave frame and return.
- No establishing shots (NALU_CRAFT_STANDARD_v1 C-01, line owner 2026-11-17): enter every location inside the
  conflict; the first two-shot of the conflict (an over-the-shoulder `MEDIUM`) gives the geography. `MCU`/`CU`
  dominate; `WIDE` / `MEDIUM_WIDE` at most ~3 per episode and only when the space itself is the drama (a chase, the
  distance of a stand-off, the creature appearing). At most three consecutive shots at the same `shot_scale`.
- Do not cut on every line of a dialogue scene, and do not put two people in frame while one of them speaks
  (line owner 2026-10-23; four lab runs: H3 turns/pushes the camera to the speaker, drops the listener, and ghosts
  or duplicates a person who is both in the opening frame and a face reference). One H3 unit carries one speaker.
  (1) Speaking shots show only the speaker: a single, or an over-the-shoulder with a sliver of the listener, speaker
  centred and the only front face; one speaker's consecutive lines stay in one shot. (2) Two-shots only when nobody
  speaks: a silent stand-off, a physical reaction. (3) Rhythm: the first shot is already the conflict (no silent
  two-shot first), play the lines in singles, cut tighter at the turn, give the hardest line the tightest shot, and
  after every payoff cut to the loser's or an onlooker's silent close-up reaction. (4) L-cut: a silent reaction shot that directly follows a
  dialogue shot (next unit) may set `prompt_spec.transition.sound_bridge_from_previous_seconds` (0.3–2.0): S7 cuts the
  speaker's picture that much earlier and lets the line (and its subtitle) finish over the reaction, the reaction's own
  sound ducked to ambience. Omit it for a plain cut. Vertical silent two-shots: stack them front/back
  (over-the-shoulder), never two people pinned to the left and right edges. No extra cost: no multi-take, no post fixes.
  (5) During a spoken line the speaker's eyes stay on the listener (or just off-lens toward the listener's side).
  The engine writes the eyeline into the H3 prompt and the keyframe (line owner 2026-10-26, lab E05: "eyes on the
  listener" alone made speakers stare into the lens): "<name> looks just off the lens to the left/right, at
  <listener>, never into the camera"; the two singles of a shot/reverse pair look to opposite sides. To fix the
  side, add `role_semantic_disambiguation.dialogue_listener_screen_side: LEFT|RIGHT` (the listener's screen side).
  Never write the speaker turning to look at a window / door / off-screen object, or "eyes fixed on X", inside a
  speaking shot: H3 pans to reveal what they look at and loses the speaker (line owner 2026-10-24, lab Holmes E03).
  A look at something gets its own silent shot, or an insert of the thing.
- Every on-screen spoken line is written to take about 3.5 s to say (English ~9–11 words, Chinese ~14–16
  characters; line owner 2026-10-29, lab E08: with the 4 s HopsAPI minimum, shorter lines made H3 invent speech that
  S7 trimmed away, 96 s final instead of ~110 s). A shorter line gets a performed action in the same shot or is
  merged with the same speaker's next line. Speaking shots stay 4–5 s. Author ~115–120 s of shots so the episode
  lands at ~110 s after the trims.
  **Superseded 2026-11-02 (line owner, lab 化神 E01): keep the source's short lines; never pad a line to the 4 s floor.**
  Generation still requests 4 s; S7 cuts to the performance (`tools/performance_cut.py`: first scripted word − 0.15 s
  to last scripted word + 0.4 s, invented speech / a repeated line / talking in a silent unit cut away at the head or
  tail, min 1.2 s). Aim ~2–3 s per short shot in the edit. One speaker's CONTINUOUS_ACTION same-setup lines run back
  to back (no per-line 4 s slot). A line under 2.8 s is only an advisory (`SHORT_LINE_OK_S7_CUTS_TO_PERFORMANCE`,
  writer self-check advisory `R11_SHORT_LINE_OK_S7_CUTS`).
- One speaker's consecutive lines are ONE take (line owner 2026-11-01, lab Holmes E12 long-take test: a continuous
  12–14 s take of a monologue with a silent insert between groups played far better than one shot per line). Keep
  writing one ~3.5 s line per shot, but give those shots the SAME locked `camera_plan` (`shot_scale`,
  `camera_height`, `camera_side`, `motion_family: LOCKED`, `motion_direction`, `start_framing` identical) and
  `CONTINUOUS_ACTION` between them — never author a cut between two consecutive lines of one speaker. (Several lines
  of one speaker in one shot, one `Name：line` per row, are also fine; timed by their sum.) The grouper makes them one
  video unit of at most 12 s (H3 maximum 15 s). After about 8 s of one speaker's
  same-setup lines write a silent 1.5–2 s listener reaction (or evidence insert; `MOTIVATED_CUT` / `REACTION_CUT`,
  `target_seconds` 1.5–2: generated at 4 s, S7 keeps the window where it peaks), then return to the SAME setup (same
  `camera_plan`, `MOTIVATED_CUT` in); the engine reuses the earlier group's keyframe (no new image). The engine still
  splits a take at 12 s at the latest (H3 maximum 15 s). A change of speaker, of camera setup or an authored cut starts a new unit. Warnings only:
  grouping `writer_warning: MONOLOGUE_CUTAWAY_REQUIRED`, self-check `R12_MONOLOGUE_CUT_BETWEEN_LINES`,
  `R12_MONOLOGUE_OVER_12S_ADD_CUTAWAY`.
- Optional `prompt_spec.beat_role` (NALU_CRAFT_STANDARD_v1 S-02/S-05): `SETUP` (the provocation a payoff answers),
  `PAYOFF` (the visible power / information flip), `REACTION` (the silent close-up right after a payoff). S7 cuts a
  silent reaction to 1.5–2.5 s and any other silent shot to 2–3 s around the take's motion peak (free; never below
  the episode's runtime floor). Write silent action from frame 0 so the peak lands inside that window. Omitted =
  treated as an ordinary silent shot.
- Write the cuts the script implies: `internal_transition_authoring.transition_mode` `MOTIVATED_CUT` /
  `REACTION_CUT` / `MATCH_CUT` / `HARD_CUT` (or a scene change) makes the next video unit open on its own
  keyframe, a clean cut; continuous modes keep the previous unit's real tail as the start frame.
- Dialogue shots may add `prompt_spec.action.performance.delivery_en` (optional): one short English sentence of
  emotion + how the line is said, e.g. `"cold and contemptuous, low and clipped, a beat of silence before the
  second sentence"`. H3 reads it instead of the generic brisk-delivery line; without it, a common `emotion` word
  (厌/怒/冷/疑/…) is mapped to English, otherwise the generic line stays.
- Dialogue shots may add `prompt_spec.action.performance.business_en` (optional, PERFORMANCE_VARIETY_V1): one
  English verb phrase of the speaker's concrete physical business + micro-expression for this beat, motivated by its
  intent (`"adjusts one cuff, eyes still on him"`, `"glances away, then back"`, `"takes a half step closer"`).  No
  gesture family twice within 4 dialogue beats or more than twice per scene; never the stock "both palms spread
  outward / open-arms shrug" unless the beat is a shrug or a plea; face-only business in close-ups; no props that are
  not in the shot.  Characters may carry `character_entities[].mannerisms` (1-3 English verb phrases).  Without it
  the engine picks a non-repeating business (tools/performance_variety.py) and gives listeners reactive business.
- Optional `"h3_prompt_style": "DIRECTOR_PROMPT_V2"` (contract top level) switches the episode's H3 units to the
  director-style prompt (docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md §7b); absent = the current prompt, unchanged.
  Under it, dialogue shots may add `prompt_spec.action.listener_reaction_en` (optional): one English sentence of what
  the listener(s) do while the line is spoken, or `{<character_id or English name>: sentence}` per listener; without
  it the listener "listens without speaking, holding the speaker's gaze".

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
