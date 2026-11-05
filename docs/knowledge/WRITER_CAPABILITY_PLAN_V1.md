# Writer capability v1 — where it plugs in, what it leaves alone, how to undo it

Status: **DRAFT** (policy `WRITER_CAPABILITY_V1`, 2026-11-01). No line owner decision is
outstanding for the parts marked *built*; the parts marked *needs a decision* are listed in
§6 and are the only things standing between this and a hard gate.

Background: `P0_INVENTORY.md`, `PILOT_RESULT.md` and `ADAPTATION_POLICY_DRAFT.md` in the
research folder for the offline pilot. The pilot's conclusion — two independent readers
preferred the arc-cut version of E11–E13 in every episode, 6/6 under both reading orders —
is a reason to build the checks, not evidence that the scripts are better. Nothing here
claims that.

## 1. The four inputs and their validators

| Input | Tool | What it validates |
| --- | --- | --- |
| Arc plan + hook/payoff ledger | `tools/writer_arc_ledger.py` (`validate`) | every episode in the window has `source_ref`, `chosen_events`, `delivered_experience`, `end_question`, `payoff_plan`, `scene_cards`; every hook has an `id`, a status in {OPEN, ADVANCED, PAID_OFF, DEFERRED} and non-empty `progress`; ADVANCED/PAID_OFF also carry `payoff`; DEFERRED carries a reason and a planned episode; an OPEN hook at the end of the arc must be listed. Schema: `configs/schemas/writer_arc_ledger_v1.schema.json`. |
| Per-episode adaptation disposition | `tools/adaptation_policy.py` (`validate`) with `configs/ADAPTATION_POLICY_V1.json` | every beat has a category among verbatim / condensed / reorganized / adapted_new / omitted / deferred, a `source_ref` and a reason; a verbatim quote occurs in the cited chapter read from the runtime's `sources/<work>/<reading_script>/chNNNN.md`; an `omitted` beat that a later episode depends on fails (it must be `deferred`); a MAJOR_CHANGE carries a kind, a description and an escalation naming the line-owner order. |
| Script-stage independent review | `lines/nalu/runtime/tools/script_review.py`, a kind of `vlm_review_protocol.py` | the reviewer read the anonymised synopsis (episode/version/chapter/season labels and the whole preamble removed); every question answered; every item carries an observation; each confusion point has a scene label, a question and a why. The reviewer never writes PASS. |
| Rule 8 response | `tools/writer_rule8_response.py` with `configs/WRITER_RULE8_RESPONSE_V1.json` | R8A/R8B/R8C each answered with either cited evidence or NOT_APPLICABLE + reason; every cited id must exist in that episode's contract (`shots`, `scene_states`) or narrative (`E<NN>-L<NN>`), which a made-up id cannot. |

## 2. Where each piece is called

```
pre-S1 (writer, before any layer is built)            S1 (nalu_pipeline.stage_s1)      writer finalize (storyclaw_writer_workflow)
-----------------------------------------------  -------------------------------  -------------------------------------------
writer_arc_ledger validate                        writer_capability_record()        verify_writer_handoff()
adaptation_policy validate (per episode)            -> tools/writer_capability.py    -> stage_summary()
script_review request / respond                     reads the four inputs from       -> sealed_binding()
writer_rule8_response evaluate                       <work>/writer_capability/         records it in `observed`
```

**pre-S1.** `tools/writer_capability.py check --episode <EP>` prints which of the four inputs
exist, what each validator said, and what is still owed. A writer about to build
`build_eNN_layers.py` runs this first and gets the list instead of discovering it at S1. This
is the "arc plan + adaptation decisions are inputs before the per-episode layers are built"
requirement: the layers are built from the disposition, not checked against it afterwards.

**S1.** `writer_capability_record()` runs next to `line_upgrade_preflight` and lands in
`StageResult.details["writer_capability"]` and in `S1_GATE_RECEIPT.json`'s
`writer_capability` block (profile, status, reason, owed inputs, seal binding). It reads
from `<NALU_WORK_ROOT>/<EP>/writer_capability/`:

```
ARC_LEDGER.json                             arc plan + hook ledger for the arc this episode belongs to
<EP>_ADAPTATION_DISPOSITION.json            this episode's per-beat disposition
<EP>_SCRIPT_REVIEW_REPORT.json              the script_review report, writer responses applied
<EP>_RULE8_RESPONSE.json                    the writer_rule8_response result
```

**Writer finalize.** `verify_writer_handoff` adds the same summary under `observed.
writer_capability` for the CURRENT_PORTABLE writer lock path. `sealed_binding()` compares
the sha256 of the narrative being sealed against the sha256 the script review was bound to at
request time, so a revision made after the review shows up as
`SEALED_NARRATIVE_CHANGED_SINCE_REVIEW` instead of passing silently.

Neither call adds anything to `failures`. They record.

## 3. What stays unchanged (LEGACY)

One decision decides everything: `tools/writer_capability.py profile_for()`, read from
`configs/WRITER_CAPABILITY_V1.json` and overridable with `NALU_WRITER_CAPABILITY=off|on`
(off wins over on; a sealed episode is never re-judged either way).

| Condition | Profile | Behaviour |
| --- | --- | --- |
| episode in `profiles.LEGACY.sealed_episodes` (E01–E13) | `LEGACY` | nothing read, nothing required, `NOT_APPLICABLE_LEGACY_PROFILE` recorded |
| below `enabled_from_episode` (E14) | `LEGACY` | same |
| `enabled: false` in the config, or the config is missing | `LEGACY` | same |
| `NALU_WRITER_CAPABILITY=off` | `LEGACY` | same |
| E14 onwards, capability enabled, no override | `WRITER_CAPABILITY_V1` | the four inputs are read and recorded |

Already-produced episodes keep their bytes: no check here re-opens a sealed episode, no
ledger row is written for one, and the S1 receipt for a LEGACY episode differs from the old
one only by the new `writer_capability` block and by the honest handoff status of §5.

## 4. Nothing blocks by default

`configs/WRITER_CAPABILITY_V1.json` → `blocking` has four switches, all `false`:
`missing_inputs`, `unanswered_script_review`, `open_rule8_items`, `ledger_failures`. With them
off, a selected episode records `status: OWED` (inputs missing) or `RECORDED` and S1 continues.
`blocks_stage` is empty. A switch set to `true` turns exactly that one input into `BLOCKED`
for S1 — that is the only way this can stop an episode, and it is a line-owner decision per
switch, not a package deal.

The script review has a second, separate switch: `script_review.respond --blocking` marks the
report blocking and exits 1 while a confusion point is unanswered. It is off unless passed.

## 5. The honesty bug — FIXED (authorised 2026-11-01)

**What was wrong.** Under `LEGACY_EPISODE_COMPAT` S1 skipped the canonical writer handoff
(it belongs to the StoryClaw private-project path, `CLAUDE_CODE_PRODUCTION.md` §0 tells the
writer never to run it as an S1 conclusion) and set
`writer_handoff_verdict.status = "NOT_APPLICABLE_LEGACY_REPLAY"` with
`writer_handoff_ok = True`. The receipt then wrote
`gates.canonical_writer_handoff = PASS if writer_handoff_ok else "FAIL"` — so every E11/E12/E13
`S1_GATE_RECEIPT.json` printed `PASS` for a step that no verifier had run.

**The fix.** The gate row now goes through `writer_handoff_gate_status()`: `PASS` only when a
verifier answered `PASS`, `FAIL` when the step failed, and otherwise the verdict's own honest
status, which for LEGACY is `NOT_RUN_LEGACY_PROFILE` (constant
`WRITER_HANDOFF_LEGACY_STATUS`). The stage outcome is unchanged — `writer_handoff_ok` is still
`True` under LEGACY, so E01–E13 keep their `status: PASS` receipts and nothing downstream
moves.

**The test that guards it** — `tools/tests/test_writer_rule8_response.py::S1HandoffHonestyTests`:
the constant is not `PASS`; a no-verifier profile reports `NOT_RUN_LEGACY_PROFILE`; a verified
handoff still reports `PASS`; a failed one still reports `FAIL`; the LEGACY branch no longer
sets the old status; the receipt gate row no longer contains the old inline expression.

**Downstream consumers (checked, all safe):**

| Consumer | What it reads | Effect of the new status |
| --- | --- | --- |
| `tools/storyclaw_release_validation.py:617` | requires `policy_profile == "CURRENT_PORTABLE"` before it looks at `gates` at all | a LEGACY receipt never reaches that check |
| `tools/storyclaw_asset_plan_gate.py:226` | `_stage_s1_status(s1) == "PASS"` — the receipt's stage `status`, not the gate map | unchanged; the stage is still `PASS` under LEGACY |
| `tools/storyclaw_guided_onboarding.py:411`, `tools/storyclaw_nalu_runtime.py:1175` | receipt path only | unchanged |
| `nalu_pipeline.py` S2-S8 | no reader of `gates.canonical_writer_handoff` | unchanged |

A test asserts the first two readings so a future edit cannot quietly start comparing the gate
map to `PASS`.

## 6. Cross-shot state and perceived state (item 4, 2026-11-01)

The line owner asked that cross-shot checks cover character/prop state AND what the viewer
perceives, built on the state mechanism that already exists. Three pieces already existed and
none of them compared a shot pair on these dimensions:

| Existing piece | What it already did | What it could not say |
| --- | --- | --- |
| `tools/event_boundary_continuity_contract.py` | per-entity ledger; exit vs entry snapshots | who holds a prop, what a gaze addresses, whether the pair crossed a place or a time |
| `build_nalu_preproduction.build_transition` | writes a prose bridge between shots | nothing ever compared that prose |
| `tools/continuity_state_contract_gate.py` | life state, head count, creature form, costume | per entity across the episode, never per shot pair; nothing about props or screen position |
| `tools/prompt_scope_conflict_gate.py` / `prompt_batch_qa.py` | speaker/face/camera scope at send time; verbatim presence | cross-shot state at all |

**What was built** — one extension of the existing ledger, not a parallel system:

- `tools/event_boundary_continuity_contract.py` gains the vocabulary for five new declared
  dimensions (`PERCEPTION_PROP_HOLDER_SENTINELS`, `PROP_PICKUP_STATES`, `ACTION_REPEAT_VALUES`,
  `PERCEPTION_TIME_SPACE_VALUES`, `PERCEPTION_CHARACTER_FIELDS`) and
  `validate_perception_state()`, which checks a declared block's vocabulary and never demands
  that a block exist.
- `tools/cross_shot_state_perception.py` reads that ledger (the same
  `shot_state_authoring.json` / `qingshan.authored_shot_state_attachment.v1` S2 already
  consumes) and emits one row **per shot pair**: `prop_holder`, `prop_pickup_state`,
  `action_repeat`, `character_position` (screen slot + eye-line target) and `time_space`.
  A prop declared only through the legacy `persistent_state_contract.props` map is still read.
- `lines/nalu/runtime/tools/prompt_batch_qa.py` calls it per unit inside the existing digest
  (before submission), attaching `cross_shot_state` to each row and one batch-level summary.
  It is computed from the contract plus the ledger, so a unit's slice needs no other unit to
  have run: no global pass, no serialisation of generation.

**The six rules** (severity in brackets):

| Rule | Meaning |
| --- | --- |
| `PROP_HELD_WITHOUT_PICKUP` [P1, blocking candidate] | held in N+1, the previous shot places it elsewhere, nothing picks it up, not INHERITED — both shots cited in the writer item |
| `PROP_RETAKE_UNDECLARED` [P2] | `PUT_DOWN_IN_SHOT`, held again with no declared re-take |
| `ACTION_REPEAT_WITHOUT_STATE_CHANGE` [MERGE] | identical action text and identical state across the pair — a merge proposal, never a failure |
| `EYELINE_ADDRESSEE_NOT_IN_FRAME` [P2] | a gaze addressed at a character while the shot declares nobody in frame |
| `SCREEN_SLOT_CHANGED_WITHOUT_CUT` [P2] | a person changes slot with no cut, jump cut or declared time/space change |
| `TIME_SPACE_CHANGE_UNDECLARED` [P2] | the pair crosses a location or a time while declaring `SAME_CONTINUOUS` |

**Three states per row, never two** — `PASS`, `FINDING`, `UNKNOWN`. An episode with no ledger
is `UNKNOWN` on every pair: never a failure, never a silent pass. Every report row carries
`planned` (ledger/contract) and `observed` (a real QA measurement, if one exists) separately;
no producer writes an observation file today, so `observed` is `UNKNOWN` and an inconclusive
measurement stays `UNKNOWN` too.

**Legal by construction** (each proven by a test): off-screen addressee with nobody in frame,
over-the-shoulder occlusion, declared jump cut, declared cut device, declared time jump,
declared scene change, a pickup staged on screen (`PICKED_UP_IN_SHOT`), a prop only mentioned
in the action text, an inherited holder, a declared repeat with a reason.

**Nothing blocks a paid run by default** — `configs/CROSS_SHOT_STATE_PERCEPTION_V1.json`
ships `blocking: false`; a missing config is report-only as well. The report and the writer
item list are written either way; turning the switch on only changes `would_block`.

## 7. What needs the line owner before it is wired harder

1. **Turn a blocking switch on.** Which of the four writer-capability switches, or the
   cross-shot `blocking` switch, if any, should stop S1/the batch rather than record.
2. **Who authors `perception_state`.** The five new dimensions are declared per shot; until an
   episode's writer/adaptor fills them the checks report `UNKNOWN`. E11–E13 have no ledger at
   all and E59 has 30/30 — whether backfilling E14+ is a writer task or an adapter task is a
   line-owner call.
3. **An observation producer.** No tool writes a per-shot observation file, so `observed` is
   `UNKNOWN` everywhere. Which existing measurement (Q1 frame identity, Q2 face crops) should
   be promoted into `observed` is a line-owner decision — this package does not guess one.
4. **Where `writer_capability/` lives.** This draft reads `<NALU_WORK_ROOT>/<EP>/writer_capability/`;
   the runtime root is the alternative, and the choice changes what the receipt can point at.
5. **Script-review reviewer identity.** The review reuses `NALU_QA_REVIEWER_ID` /
   `NALU_QA_REVIEW_METHOD`; whether a synopsis reader should be a distinct identity from the
   frame reviewer is a line-owner call.
6. **The `adapted_new` scope is already decided** (allowed with a source trace, no per-episode
   cap, MAJOR_CHANGE escalated separately). What is not decided is who signs a MAJOR_CHANGE
   escalation and where the signed order lives.
7. **Real audience read.** Everything here is AI_REVIEW. A human blind read is still the only
   thing that answers "would an audience watch this", and this package does not produce one.

## 8. Rollback

| To undo… | Do | Result |
| --- | --- | --- |
| a blocking switch someone turned on | set it back to `false` in `configs/WRITER_CAPABILITY_V1.json` | S1 records again instead of refusing |
| the whole capability for a stretch of episodes | `NALU_WRITER_CAPABILITY=off` in the environment, or `enabled: false` | every episode is LEGACY; no input is read |
| the capability permanently | delete the `writer_capability_record()` call in `stage_s1`, the `writer_capability` block in the S1 receipt, and the `writer_capability` summary in `verify_writer_handoff`; the tools and configs can stay (nothing imports them then) | old behaviour byte for byte |
| the §5 honesty fix | not recommended — it restores a PASS no verifier earned. If it has to happen, the tests in `S1HandoffHonestyTests` fail first, which is the point of them. | — |

Nothing here mutates a sealed episode, a paid receipt or a transaction, so a rollback never
requires touching production evidence.

## 8b. Building one episode: cut the work by file, not by step

Line owner, 2026-11-05: 「并行是必须的，这个功能必须要整合入生产线，成为标配」. Serial
construction — run the builder, read the first failing assertion, fix, run again — is the
reason an episode took dozens of rounds. It is also self-inflicted: an episode's layers are
nearly disjoint files, so almost all of that work can run at once.

The split that works, and the rule that makes it safe:

| Worker | Owns | Must not touch |
| --- | --- | --- |
| narrative canon | `<EP>_NARRATIVE_CANONICAL_v1.md`; dialogue lines verbatim, in shot order, with the cast's names as the line prefix | the shot table, the builder, any `.part` |
| tail / contract / manifest | the part file that assembles `contract`, `manifest`, `ADAPTATION_DISPOSITION`, character and prop tables | the shot table, the narrative, the parts another worker owns |
| main path | shot table, the `.part` slices, assembly, the assertion chain | the files the other two own |

Three rules keep it from turning into crossed writes:

1. **A file has one owner for the duration.** Each worker's brief names the files it may write
   and the files it must leave alone. Overlapping writes are the only way this gets slower.
2. **Every worker self-checks with the builder's own regexes** before reporting — the line
   extractor for dialogue order and speaker, the verbatim-in-chapter check, the header quote —
   and returns the result, not "done".
3. **The main path accumulates failures instead of stopping at the first.** Writer-layer
   assertions feed one `_FAILS` list and report together (K079). Parallelism without this just
   moves the bottleneck from waiting on a fix to waiting on the next round.

A worker reporting a defect in someone else's file is a finding, not an edit: it comes back to
the main path, which decides and applies it.

## 9. Tests

```
/Users/rogerwu/nalu/.qingshan-venv/bin/python -m pytest \
  tools/tests/test_writer_arc_ledger.py \
  tools/tests/test_adaptation_policy.py \
  tools/tests/test_script_review.py \
  tools/tests/test_writer_rule8_response.py \
  tools/tests/test_writer_capability.py \
  tools/tests/test_cross_shot_state_perception.py \
  tools/tests/test_cross_shot_prompt_batch_wiring.py
```

`test_cross_shot_state_perception.py` proves each of the six rules fires on an invented pair
and each legal case (off-screen addressee with nobody in frame, over-the-shoulder occlusion,
declared jump cut, declared cut device, declared time jump, declared scene change, on-screen
pickup, prop only mentioned, inherited holder, declared repeat with a reason) stays silent.
`test_cross_shot_prompt_batch_wiring.py` drives the real per-unit slice: a missing ledger is
`UNKNOWN` and the digest still completes, a P1 is listed and refuses nothing, and two units
give identical results whichever order they run in.

No test reads `workflow/`, no test reaches the network, and every fixture chapter and every
narrative fragment used in a test is invented for the test. The repo continues to hold no
script text from the novel or from any episode.

## 10. Not built, on purpose

- No fixed counts anywhere: no hooks per episode, no fights per N episodes, no "hook within N
  seconds". The arc ledger's 3–6 episode window is how far ahead the sheet must look, not what
  happens inside those episodes.
- No score. A script review produces confusion points and writer responses; it never produces
  a number a threshold could be set on.
- No second review system: `script_review` is a kind of `vlm_review_protocol.py`, sharing its
  reviewer identity, request/answers schemas, sha binding and materialiser hook.
- No montage/score integration with `episode_stage_gate_runner.py --phase script` and its
  council gates; those carry fixed quotas (`dramatic_quality_gate.py` is the example) and
  wiring them would template the writing. See P0_INVENTORY §4.
