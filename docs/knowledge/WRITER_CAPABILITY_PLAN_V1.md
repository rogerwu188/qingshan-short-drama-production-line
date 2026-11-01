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

## 6. What needs the line owner before it is wired harder

1. **Turn a blocking switch on.** Which of the four, if any, should stop S1 rather than record.
2. **Where `writer_capability/` lives.** This draft reads `<NALU_WORK_ROOT>/<EP>/writer_capability/`;
   the runtime root is the alternative, and the choice changes what the receipt can point at.
3. **Script-review reviewer identity.** The review reuses `NALU_QA_REVIEWER_ID` /
   `NALU_QA_REVIEW_METHOD`; whether a synopsis reader should be a distinct identity from the
   frame reviewer is a line-owner call.
4. **The `adapted_new` scope is already decided** (allowed with a source trace, no per-episode
   cap, MAJOR_CHANGE escalated separately). What is not decided is who signs a MAJOR_CHANGE
   escalation and where the signed order lives.
5. **Real audience read.** Everything here is AI_REVIEW. A human blind read is still the only
   thing that answers "would an audience watch this", and this package does not produce one.

## 7. Rollback

| To undo… | Do | Result |
| --- | --- | --- |
| a blocking switch someone turned on | set it back to `false` in `configs/WRITER_CAPABILITY_V1.json` | S1 records again instead of refusing |
| the whole capability for a stretch of episodes | `NALU_WRITER_CAPABILITY=off` in the environment, or `enabled: false` | every episode is LEGACY; no input is read |
| the capability permanently | delete the `writer_capability_record()` call in `stage_s1`, the `writer_capability` block in the S1 receipt, and the `writer_capability` summary in `verify_writer_handoff`; the tools and configs can stay (nothing imports them then) | old behaviour byte for byte |
| the §5 honesty fix | not recommended — it restores a PASS no verifier earned. If it has to happen, the tests in `S1HandoffHonestyTests` fail first, which is the point of them. | — |

Nothing here mutates a sealed episode, a paid receipt or a transaction, so a rollback never
requires touching production evidence.

## 8. Tests

```
/Users/rogerwu/nalu/.qingshan-venv/bin/python -m pytest \
  tools/tests/test_writer_arc_ledger.py \
  tools/tests/test_adaptation_policy.py \
  tools/tests/test_script_review.py \
  tools/tests/test_writer_rule8_response.py \
  tools/tests/test_writer_capability.py
```

No test reads `workflow/`, no test reaches the network, and every fixture chapter and every
narrative fragment used in a test is invented for the test. The repo continues to hold no
script text from the novel or from any episode.

## 9. Not built, on purpose

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
