# Knowledge loop case 001 — the cover check only guards the burned dialogue line

Line owner 2026-11-01 item 5: prove the loop once, end to end, on a REAL production problem —
record fact → find cause → form a rule → verify the rule → use it in a later real build — and show
the difference it made.

This is case 1 of the loop, run on E13. Everything here is offline and free: no provider POST, no
paid stage, no network. The record lives in
`configs/knowledge_loop_cases/CASE_001_BURNED_TEXT_SCOPE.json`; the mechanism that drives it is
`tools/knowledge_loop_case.py`; the states are the ones that already existed in
`tools/collective_learning/adoption.py` (AVAILABLE → SELECTED → APPLIED → VERIFIED →
OUTCOME_OBSERVED). Nothing new was invented: the adoption receipt grew two optional, strictly
validated blocks for the inputs it always implied but never carried.

## Where the loop stands

| State | Reached? | Evidence |
|---|---|---|
| AVAILABLE | yes | rule cited at `tools/burned_text_cover.py:139` |
| SELECTED | yes | chosen for E13 S7, one unit |
| APPLIED | yes | clause present in the gate output with the rule, absent from the same input without it |
| VERIFIED | yes | free replay over E13's recorded OCR hits reproduces PASS with / FAIL without |
| OUTCOME_OBSERVED | **no** | requires a generated-media or final-film sha256 for a build run *with* the rule; E13's final cut predates it |
| real-run consumption | **NOT_YET_CONSUMED_BY_REAL_RUN** | no later real build has run since the rule landed |

`production_adoption` is `false` everywhere in this record

## 1. The fact (E13 S7 stopped)

E13's S7 run of 2026-11-01 T09:04Z ended `S7 => BLOCKED blockers: H3_BURNED_TEXT_STILL_VISIBLE`
after `s7_burned_text_verify` exited 2. The blocked verify wrote 8 CJK OCR hits that sat outside
the caption bar.

- artefact: `RUNTIME:pipeline_logs/E13/run_20261101T090410.343644Z_32124_551f2def.log`
- sha256 `9ae3108b3a46c382d227e34c2aa9c705322073e6444d3d52512012c19d60095f`
- measured: blocker `H3_BURNED_TEXT_STILL_VISIBLE`, verify exit 2, 8 hits, hit boxes at y 0.005–0.141
  of frame height, unit `E13-VU-014`

## 2. The cause

The cover check was scoped to *every* CJK character in the frame, while the policy's purpose
(`H3_BURNED_TEXT_COVER_V1`, `tools/burned_text_cover.py` docstring) is the **line H3 burns into the
picture**: the bar covers the burn band so the spoken line is never readable. The 8 hits were not
that line. They were the meaningless characters generated onto VU-014's gate plaque and door
couplet, which Q2 had already rated P2 as scene signage — the period/anachronism OCR gate's
business, not the subtitle-cover gate's.

Evidence artefacts:

- `RUNTIME:reviews/E13/E13-video_q2-20261101T073845Z_submitted.json` sha256 `eb5f960f…39dad` —
  Q2 records the plaque/couplet characters as set text, not subtitles, and rates the scene P2
- `RUNTIME:proposals/E13_Q2_BURNED_SUBTITLE_COVER_20261101.md` sha256 `bc3ac931…072a4` — the
  proposal the line owner answered on 2026-11-01: cover the burned line, QC by OCR outside the bar
- `WORKFLOW:nalu/E13/assembly/E13_H3_BURNED_TEXT_COVER_CHECK.json` sha256 `a2736978…320e2` — the
  PASS artefact listing exactly those 8 hits under `ignored_non_dialogue_text`

Related E13 facts that make the same point from the other side: `FINAL-CUT-CAMERA-MOTION` still
FAILs (locked-off share 0.2609, 3 unstable units) and S7 now blocks on
`FINAL_CUT_AUDIENCE_DETECTORS_FAIL`. Neither is this case, and neither is fixed by it.

## 3. The rule

The exact clause, at `tools/burned_text_cover.py:139`:

> scene signage away from the burn band is the period/anachronism gate's business

The operative narrowing lives in the same function: a hit outside the bar counts as a failure only
when its centre is within `dialogue_band_pad` (0.10, configured at
`configs/H3_BURNED_TEXT_COVER_V1.json:11`) of the burn band, or when it reads like the caption on
screen at that moment. Everything else is recorded in `ignored_non_dialogue_text`.

Implemented in `20dcd9d`. This record adds the rule's *evidence* chain, not the rule.

## 4. The verification (what the replay proves)

`tools/knowledge_loop_case.py verify` re-reads E13's own recorded OCR hits and burn-in captions and
calls the real `burned_text_cover.verify()` twice:

| arm | code | status | output sha256 |
|---|---|---|---|
| with the rule | `tools/burned_text_cover.py` @ HEAD | **PASS**, 0 outside bar, 8 ignored | `fa1f0f46…bcf2b` |
| without the rule | same file @ git `7ed3399` (the revision before `20dcd9d`) | **FAIL**, the same 8 rows in `text_outside_bar` | `b1bfeb71…a4896` |

The "without" arm is the earlier real code loaded from git — not a re-implementation and not string
surgery. The test asserts the two arms fail/pass on the *same rows*, so the difference is the rule's
scope and nothing else. Two controls keep the rule from being an excuse to stop checking:

- burned caption near the burn band but outside the bar → still FAIL
- caption text read anywhere, uncovered by the bar → still FAIL

## 5. What changed in the output

The gate verdict on E13 S7's own input moved from **FAIL (exit 2, S7 blocked on
`H3_BURNED_TEXT_STILL_VISIBLE`)** to **PASS**, which is what the recorded artefact now says, while
the 6 real burned captions the cover exists for stayed covered and the plaque characters are still
on the record (`ignored_non_dialogue_text`). S7 then advanced past this blocker — the later runs
stopped on the camera-motion and audience-detector blockers instead.

## 6. Consumer receipt — and what it does not claim

`tools/knowledge_loop_case.py replay` writes the consumer receipt:
`schema=qingshan.knowledge_loop_consumer_receipt.v1`, the consumer entrypoint
(`burned_text_cover.verify`), the input artefact sha, both arms' outputs, and the status.

**No real paid build has consumed this rule yet.** E13's final cut predates it, and E14 has not
run. So the status is `NOT_YET_CONSUMED_BY_REAL_RUN` with that reason on the record, and
`production_adoption: false`. The contract refuses to let this be rounded up:
`CONSUMED_BY_REAL_RUN` demands a later run whose own output carries the clause
(`clause_present: true`) and which postdates the rule record (`after_rule_recorded: true`); a replay
that lists itself as a consumer is rejected
(`CONSUMER_RUNS_LISTED_UNDER:CONSUMED_BY_REPLAY_ONLY`).

To close this case properly, run one more episode's S7 (free replay against a fresh cut is not
enough — it must be a real build) and record its output sha with `clause_present: true`.

## 7. What remains unproven

- **Real-run consumption.** Replay only. No later real build has consumed the clause. §6.
- **No OUTCOME_OBSERVED.** That needs a final film generated *after* the rule. E13's does not
  qualify and this record does not pretend otherwise.
- **The pre-rule FAIL report is not preserved.** The failing report was overwritten at the same
  path by the later PASS (`E13_H3_BURNED_TEXT_COVER_CHECK.json`, one file, two runs). What is
  preserved is the log with `exit=2` plus the pre-rule code replayed over the same recorded hits.
  The spec records `report_preserved: false` rather than implying the old bytes still exist.
- **Single case.** `evidence_level` is effectively SINGLE_CASE. The period/anachronism gate owning
  scene signage is an argument, not a measurement performed here; no one measured whether the
  plaque characters ever confuse a viewer.
- **A scope narrowing can hide a real defect.** The two controls (`FAIL` near the band, `FAIL` for
  an uncovered caption) bound the risk but do not prove no future burned caption lands far from the
  band. If H3 ever burns a line high in the frame, this rule must be revisited.
- **Second candidate not run.** The line owner also named the BGM vocal-confidence rule
  (`c4e972d`, `no_speech_prob` gating). It is not in this record; running it would be a second case
  with its own artefacts.

## 8. Demo fixtures — kept separate from the record

None of the following is evidence for case 001. They are synthetic, live only in
`tools/tests/test_knowledge_loop_case.py`, and the case spec refuses to carry them
(`CASE_SPEC_CARRIES_DEMO_FIXTURES`).

| fixture | what it demonstrates | not |
|---|---|---|
| `[(1.2, "猿明", …)]` single plaque hit | the mechanism: current module PASSes, pre-rule FAILs | E13 evidence |
| `"多谢邵兄好意"` at y 0.84 | a burned line near the band still FAILs | a real OCR sample |
| `"多谢邵兄好意"` at y 0.02 | an uncovered caption anywhere still FAILs | a real OCR sample |
| forged APPLIED receipt (state flipped by hand) | a receipt without evidence is not evidence | a real receipt |
| `CONSUMED_BY_REPLAY_ONLY` with a consumer run listed | the contract rejects self-promotion | a real consumption |

The real case's numbers come only from the artefacts pinned in the case spec, and each is
sha-checked before the case will run (`tools/knowledge_loop_case.py check`).

## 9. How to re-run

```bash
python3 tools/knowledge_loop_case.py check  --spec configs/knowledge_loop_cases/CASE_001_BURNED_TEXT_SCOPE.json \
    --state-root /tmp/case001 --workflow-root "$NALU_ENGINE_ROOT/workflow" --runtime-root "$NALU_RUNTIME_ROOT/runtime"
# then run / verify / replay against the same --state-root
python3 -m pytest -q tools/tests/test_knowledge_loop_case.py
```

The real-case tests skip when `NALU_ENGINE_ROOT` / `NALU_RUNTIME_ROOT` are unset, so a clean clone
reports skips rather than a false pass.
